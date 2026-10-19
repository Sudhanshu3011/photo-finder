"""
src/api/auth_routes.py — Authentication, Registration, and Profile Management endpoints.
Implements decoupled tenant creation (register-tenant), invite previews, locked invite acceptance (accept-invite),
unified login with multi-tenant disambiguation, and workspace switching.
"""
import logging
from typing import Optional, Union, List
from fastapi import APIRouter, Depends, HTTPException, status
from src.schemas.auth_schemas import (
    RegisterTenantRequest,
    InvitePreviewResponse,
    AcceptInviteRequest,
    LoginRequest,
    TokenResponse,
    TenantOptionItem,
    MultiTenantLoginResponse,
    SwitchTenantRequest,
    UserProfileResponse,
)
from src.services.user_auth_service import UserAuthService, get_auth_service
from src.api.dependencies import require_current_user
from src.modules.infra.kv_cache import get_kv_cache

logger = logging.getLogger("src.api.auth_routes")

router = APIRouter(prefix="/api/auth", tags=["Authentication & Users"])


# -------------------------------------------------------------------
# Flow 1: Founding Admin Registration (Creates New Workspace/Tenant)
# -------------------------------------------------------------------
@router.post("/register-tenant", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register_tenant(
    req: RegisterTenantRequest,
    service: UserAuthService = Depends(get_auth_service),
):
    """
    Creates a new organization workspace and registers the caller as 'owner'.
    Rejects with 409 Conflict if email has an active pending invite elsewhere (unless ignore_pending_invite=True).
    """
    try:
        user = service.register_tenant(req)
    except ValueError as e:
        error_msg = str(e)
        status_code = status.HTTP_409_CONFLICT if "pending invitation" in error_msg else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=error_msg)
    except Exception as e:
        logger.error("[auth_routes.register_tenant] Failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Tenant registration failed: {str(e)}"
        )

    token = service.issue_token(user)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user_id=user["user_id"],
        username=user["username"],
        email=user["email"],
        role=user.get("role", "owner"),
        tenant_id=user.get("tenant_id", "default"),
        organization_name=user.get("organization_name", req.organization_name),
    )


# -------------------------------------------------------------------
# Flow 2: Invited Member Onboarding (Preview & Accept)
# -------------------------------------------------------------------
@router.get("/invites/{invite_token}", response_model=InvitePreviewResponse, status_code=status.HTTP_200_OK)
def preview_invitation(
    invite_token: str,
    service: UserAuthService = Depends(get_auth_service),
):
    """
    Public validation of an invite token.
    Returns organization name, locked email, and role for the onboarding UI.
    """
    try:
        preview = service.preview_invite(invite_token)
        return InvitePreviewResponse(**preview)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("[auth_routes.preview_invitation] Failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch invitation")


@router.post("/accept-invite", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def accept_invitation(
    req: AcceptInviteRequest,
    service: UserAuthService = Depends(get_auth_service),
):
    """
    Accepts an invitation, creates member account locked to the invited email,
    and auto-grants pre-assigned folder permissions atomically.
    """
    try:
        user = service.accept_invite(req)
    except ValueError as e:
        error_msg = str(e)
        status_code = status.HTTP_409_CONFLICT if "already exists" in error_msg or "taken" in error_msg else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=error_msg)
    except Exception as e:
        logger.error("[auth_routes.accept_invitation] Failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invite acceptance failed: {str(e)}"
        )

    token = service.issue_token(user)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user_id=user["user_id"],
        username=user["username"],
        email=user["email"],
        role=user.get("role", "viewer"),
        tenant_id=user.get("tenant_id", "default"),
        organization_name=user.get("organization_name", "Organization"),
    )


# -------------------------------------------------------------------
# Flow 3: Unified Login & Multi-Tenant Disambiguation
# -------------------------------------------------------------------
@router.post("/login", response_model=Union[TokenResponse, MultiTenantLoginResponse], status_code=status.HTTP_200_OK)
def login_user(
    req: LoginRequest,
    service: UserAuthService = Depends(get_auth_service),
):
    """
    Authenticates user credentials.
    - If user belongs to 1 workspace (or tenant_id provided): returns TokenResponse.
    - If user belongs to multiple workspaces and tenant_id is omitted: returns MultiTenantLoginResponse
      listing available workspaces for user selection.
    """
    result = service.authenticate(
        email_or_username=req.email,
        password=req.password,
        tenant_id=req.tenant_id,
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # Disambiguation needed
    if isinstance(result, list):
        options = [
            TenantOptionItem(
                tenant_id=u["tenant_id"],
                organization_name=u.get("organization_name", u["tenant_id"]),
                role=u.get("role", "viewer"),
            )
            for u in result
        ]
        return MultiTenantLoginResponse(
            status="select_tenant",
            message="Multiple workspace memberships found. Please select which workspace to enter.",
            available_tenants=options,
        )

    # Single user authenticated
    token = service.issue_token(result)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user_id=result["user_id"],
        username=result["username"],
        email=result["email"],
        role=result.get("role", "viewer"),
        tenant_id=result.get("tenant_id", "default"),
        organization_name=result.get("organization_name", "Organization"),
    )


# -------------------------------------------------------------------
# Flow 4: Workspace Switching
# -------------------------------------------------------------------
@router.post("/switch-tenant", response_model=TokenResponse, status_code=status.HTTP_200_OK)
def switch_workspace(
    req: SwitchTenantRequest,
    current_user: dict = Depends(require_current_user),
    service: UserAuthService = Depends(get_auth_service),
):
    """
    Issues a new access token for another authorized workspace the user belongs to.
    """
    email = current_user.get("email")
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current session lacks email context")

    try:
        switched_user = service.switch_tenant(email=email, target_tenant_id=req.tenant_id)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error("[auth_routes.switch_workspace] Failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Workspace switch failed")

    token = service.issue_token(switched_user)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user_id=switched_user["user_id"],
        username=switched_user["username"],
        email=switched_user["email"],
        role=switched_user.get("role", "viewer"),
        tenant_id=switched_user["tenant_id"],
        organization_name=switched_user.get("organization_name", "Organization"),
    )


# -------------------------------------------------------------------
# User Profile & S3 Storage Configuration
# -------------------------------------------------------------------
@router.get("/me", response_model=UserProfileResponse, status_code=status.HTTP_200_OK)
def get_current_user_profile(
    current_user: dict = Depends(require_current_user),
    service: UserAuthService = Depends(get_auth_service),
):
    """Retrieve profile information for the authenticated user."""
    profile = service.get_profile(current_user["user_id"], current_user.get("tenant_id"))
    user = profile or current_user

    return UserProfileResponse(
        user_id=user["user_id"],
        username=user["username"],
        email=user.get("email", ""),
        role=user.get("role", "viewer"),
        tenant_id=user.get("tenant_id", "default"),
        organization_name=user.get("organization_name", "Organization"),
        is_active=user.get("is_active", True),
        storage_bucket=user.get("storage_bucket"),
        created_at=str(user.get("created_at", "")),
        last_seen=str(user.get("last_seen", "")),
    )

