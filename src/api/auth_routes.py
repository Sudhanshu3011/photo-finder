import logging
from fastapi import APIRouter, Depends, HTTPException, status
from src.schemas.auth_schemas import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    UserProfileResponse,
    CloudinaryConfigRequest,
    CloudinaryConfigResponse,
)
from src.services.user_auth_service import UserAuthService, get_auth_service
from src.api.dependencies import require_current_user

logger = logging.getLogger("src.api.auth_routes")

router = APIRouter(prefix="/api/auth", tags=["Authentication & Users"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register_user(
    req: RegisterRequest,
    service: UserAuthService = Depends(get_auth_service),
):
    """Register a new user account and receive an access token."""
    try:
        user = service.register(
            username=req.username,
            email=req.email,
            password=req.password,
            role=req.role or "user",
            cloudinary_url=req.cloudinary_url,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("[auth_routes.register] Internal error: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Registration failed")

    token = service.issue_token(user)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user_id=user["user_id"],
        username=user["username"],
        role=user.get("role", "user"),
    )


@router.post("/login", response_model=TokenResponse)
def login_user(
    req: LoginRequest,
    service: UserAuthService = Depends(get_auth_service),
):
    """Authenticate with username/email and password to obtain an access token."""
    user = service.authenticate(req.username, req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    token = service.issue_token(user)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user_id=user["user_id"],
        username=user["username"],
        role=user.get("role", "user"),
    )


@router.get("/me", response_model=UserProfileResponse)
def get_current_user_profile(
    current_user: dict = Depends(require_current_user),
):
    """Retrieve profile information for the authenticated user."""
    return UserProfileResponse(
        user_id=current_user["user_id"],
        username=current_user["username"],
        email=current_user["email"],
        role=current_user.get("role", "user"),
        cloudinary_url=current_user.get("cloudinary_url"),
        created_at=current_user.get("created_at", ""),
    )


@router.post("/cloudinary-config", response_model=CloudinaryConfigResponse)
def set_cloudinary_configuration(
    req: CloudinaryConfigRequest,
    current_user: dict = Depends(require_current_user),
    service: UserAuthService = Depends(get_auth_service),
):
    """
    Configure and verify Cloudinary credentials for the authenticated user.
    Validates connection with a live ping before saving to user profile.
    """
    from src.common.utils import get_cloudinary_creds
    from src.modules.storage.cloudinary_storage import ping_cloudinary
    from src.modules.infra.kv_cache import get_kv_cache

    cld_url = req.cloudinary_url.strip()
    creds = get_cloudinary_creds(cld_url)
    if not creds.get("cloud_name") or not creds.get("api_key") or not creds.get("api_secret"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Cloudinary URL format. Expected: cloudinary://api_key:api_secret@cloud_name"
        )

    try:
        ping_cloudinary(creds)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cloudinary connection test failed: {str(e)}"
        )

    # Save to user's database record
    service.update_cloudinary_url(current_user["user_id"], cld_url)

    cache = get_kv_cache()
    cache.set(f"user_cld:{current_user['user_id']}", cld_url)
    cache.set("system_cld_config", cld_url)

    return CloudinaryConfigResponse(
        status="success",
        message="User Cloudinary storage verified and saved successfully to profile",
        cloud_name=creds.get("cloud_name"),
        configured=True,
    )


@router.get("/cloudinary-config", response_model=CloudinaryConfigResponse)
def get_cloudinary_configuration(
    current_user: dict = Depends(require_current_user),
):
    """Check current Cloudinary configuration status for the authenticated user."""
    from src.common.utils import get_cloudinary_creds
    from src.modules.infra.kv_cache import get_kv_cache
    from src.core.config import DEFAULT_CLOUDINARY_URL

    cache = get_kv_cache()
    cld_url = (
        current_user.get("cloudinary_url")
        or cache.get(f"user_cld:{current_user['user_id']}")
        or cache.get("system_cld_config")
        or DEFAULT_CLOUDINARY_URL
    )
    creds = get_cloudinary_creds(str(cld_url)) if cld_url else {}

    if creds.get("cloud_name"):
        return CloudinaryConfigResponse(
            status="success",
            message=f"Cloudinary storage is configured for {current_user['username']}",
            cloud_name=creds.get("cloud_name"),
            configured=True,
        )
    return CloudinaryConfigResponse(
        status="unconfigured",
        message="Cloudinary storage is not configured",
        cloud_name=None,
        configured=False,
    )



