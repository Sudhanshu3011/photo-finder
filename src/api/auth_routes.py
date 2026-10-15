import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from src.schemas.auth_schemas import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    UserProfileResponse,
    StorageConfigRequest,
    StorageConfigResponse,
    CloudinaryConfigRequest,
    CloudinaryConfigResponse,
)
from src.services.user_auth_service import UserAuthService, get_auth_service
from src.api.dependencies import require_current_user
from src.modules.infra.kv_cache import get_kv_cache
from src.modules.storage.s3_storage import get_s3_bucket, ping_s3

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
            storage_bucket=req.storage_bucket,
            tenant_id=req.tenant_id or "default",
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
        tenant_id=user.get("tenant_id", "default"),
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
        tenant_id=user.get("tenant_id", "default"),
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
        tenant_id=current_user.get("tenant_id", "default"),
        storage_bucket=current_user.get("storage_bucket") or current_user.get("cloudinary_url"),
        cloudinary_url=current_user.get("cloudinary_url"),
        created_at=current_user.get("created_at", ""),
    )


@router.post("/storage-config", response_model=StorageConfigResponse)
@router.post("/cloudinary-config", response_model=StorageConfigResponse)
def set_storage_configuration(
    req: StorageConfigRequest,
    current_user: dict = Depends(require_current_user),
    service: UserAuthService = Depends(get_auth_service),
):
    """
    Configure and verify AWS S3 bucket storage for the authenticated user.
    """
    bucket = req.s3_bucket or get_s3_bucket()
    try:
        ping_s3(bucket=bucket)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"S3 storage connection test failed: {str(e)}"
        )

    service.update_storage_config(current_user["user_id"], bucket)

    cache = get_kv_cache()
    cache.set(f"user_storage:{current_user['user_id']}", bucket)

    return StorageConfigResponse(
        status="success",
        message="AWS S3 storage bucket verified and saved successfully to profile",
        bucket=bucket,
        cloud_name=bucket,
        configured=True,
    )


@router.get("/storage-config", response_model=StorageConfigResponse)
@router.get("/cloudinary-config", response_model=StorageConfigResponse)
def get_storage_configuration(
    current_user: dict = Depends(require_current_user),
):
    """Check current S3 object storage configuration status for the authenticated user."""
    cache = get_kv_cache()
    bucket = (
        current_user.get("storage_bucket")
        or cache.get(f"user_storage:{current_user['user_id']}")
        or get_s3_bucket()
    )

    if bucket:
        return StorageConfigResponse(
            status="success",
            message=f"AWS S3 storage is configured for {current_user['username']}",
            bucket=str(bucket),
            cloud_name=str(bucket),
            configured=True,
        )
    return StorageConfigResponse(
        status="unconfigured",
        message="Object storage is not configured",
        bucket=None,
        cloud_name=None,
        configured=False,
    )



