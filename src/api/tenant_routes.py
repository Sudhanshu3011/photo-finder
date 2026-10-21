"""
src/api/tenant_routes.py — Organization member management and invitation endpoints.
Restricted to Organization Owners and Administrators.
"""
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.schemas.auth_schemas import (
    TenantInviteRequest,
    TenantInviteResponse,
    UpdateMemberRoleRequest,
    TenantMemberItem,
)
from src.services.user_auth_service import UserAuthService, get_auth_service
from src.api.dependencies import require_tenant_admin, get_current_tenant_id
from src.modules.infra.postgres_repository import get_repository, PostgresRepository

logger = logging.getLogger("src.api.tenant_routes")

router = APIRouter(prefix="/api/tenant", tags=["Tenant Administration"])


@router.get("/members", response_model=List[TenantMemberItem], status_code=status.HTTP_200_OK)
def list_organization_members(
    limit: int = Query(50, ge=1, le=200, description="Maximum members to return per page"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_admin: dict = Depends(require_tenant_admin),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
):
    """List registered members in the organization with pagination."""
    members = repo.list_tenant_members(tenant_id=tenant_id, limit=limit, offset=offset)
    return [
        TenantMemberItem(
            user_id=m["user_id"],
            username=m.get("username", ""),
            email=m.get("email", ""),
            role=m.get("role", "viewer"),
            is_active=m.get("is_active", True),
            created_at=str(m.get("created_at", "")),
            last_seen=str(m.get("last_seen", "")),
        )
        for m in members
    ]


@router.post("/invites", response_model=TenantInviteResponse, status_code=status.HTTP_201_CREATED)
def invite_organization_member(
    req: TenantInviteRequest,
    current_admin: dict = Depends(require_tenant_admin),
    tenant_id: str = Depends(get_current_tenant_id),
    service: UserAuthService = Depends(get_auth_service),
):
    """
    Invite a new member to the organization by email with assigned role and optional pre-granted folders.
    Solves admin fatigue by auto-granting folders upon registration.
    """
    try:
        invite_data = service.create_invite(
            tenant_id=tenant_id,
            email=req.email,
            role=req.role.value,
            invited_by=current_admin["user_id"],
            initial_folder_ids=req.initial_folder_ids,
            initial_access_level=req.initial_access_level.value,
        )
        return TenantInviteResponse(**invite_data)
    except Exception as e:
        logger.error("[tenant_routes.invite] Failed to create invite: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create invitation: {str(e)}"
        )


@router.patch("/members/{user_id}/role", status_code=status.HTTP_200_OK)
def update_member_role(
    user_id: str,
    req: UpdateMemberRoleRequest,
    current_admin: dict = Depends(require_tenant_admin),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
    service: UserAuthService = Depends(get_auth_service),
):
    """
    Update an organization member's Tier 1 base role.
    Evicts Redis authentication cache immediately to prevent Stale JWT permissions (Trap 3).
    """
    target_user = repo.get_user_by_id(user_id, tenant_id=tenant_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found in organization")

    # Prevent demoting the sole organization owner (Pillar 11 protection)
    if target_user.get("role") == "owner" and req.role.value != "owner":
        owner_count = repo.count_tenant_owners(tenant_id)
        if owner_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote the sole organization owner. Transfer ownership or promote another member to owner first."
            )

    # Prevent modifying another owner's role unless caller is the owner
    if target_user.get("role") == "owner" and current_admin.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify the role of another Organization Owner"
        )

    updated = repo.update_tenant_member_role(tenant_id=tenant_id, user_id=user_id, role=req.role.value)
    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update member role")

    # Immediately evict user authorization cache in Redis
    service.invalidate_auth_cache(tenant_id=tenant_id, user_id=user_id)

    return {
        "status": "success",
        "message": f"Updated member '{target_user.get('username')}' role to '{req.role.value}'",
        "user_id": user_id,
        "new_role": req.role.value,
    }


@router.delete("/members/{user_id}", status_code=status.HTTP_200_OK)
def remove_organization_member(
    user_id: str,
    current_admin: dict = Depends(require_tenant_admin),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
    service: UserAuthService = Depends(get_auth_service),
):
    """
    Remove a member from the organization.
    Audit references are safely preserved via ON DELETE SET NULL.
    """
    if user_id == current_admin.get("user_id"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove yourself from the organization")

    target_user = repo.get_user_by_id(user_id, tenant_id=tenant_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found in organization")

    if target_user.get("role") == "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot remove the Organization Owner")

    removed = repo.remove_tenant_member(tenant_id=tenant_id, user_id=user_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to remove member")

    # Evict cache immediately
    service.invalidate_auth_cache(tenant_id=tenant_id, user_id=user_id)

    return {
        "status": "success",
        "message": f"Member '{target_user.get('username')}' removed from organization",
        "user_id": user_id,
    }

