"""
src/api/folder_routes.py — Folder Management and Granular Access Control (ACL) Router.
Enforces the Two-Tier Hybrid Permission Model, eliminates the Orphaned Creator bug,
and provides high-throughput Bulk Access endpoints.
"""
import logging
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.schemas.folder_schemas import (
    CreateFolderRequest,
    UpdateFolderRequest,
    FolderResponse,
    SingleFolderAccessGrantRequest,
    BulkFolderAccessRequest,
    FolderMemberAccessItem,
)
from src.api.dependencies import (
    require_current_user,
    require_folder_creation_permission,
    get_current_tenant_id,
    get_user_accessible_folders,
    check_folder_capability,
)
from src.modules.infra.postgres_repository import get_repository, PostgresRepository

logger = logging.getLogger("src.api.folder_routes")

router = APIRouter(prefix="/api/folders", tags=["Folders & Access Control (ACL)"])


@router.post("", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
def create_folder(
    req: CreateFolderRequest,
    current_user: dict = Depends(require_folder_creation_permission),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
):
    """
    Create a new folder/album inside the organization.
    Atomically grants the creator 'manager' access level to prevent the Orphaned Creator Bug.
    """
    clean_name = req.folder_name.strip()
    existing = repo.get_folder_by_name(clean_name, tenant_id=tenant_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A folder named '{clean_name}' already exists in this organization."
        )

    folder_id = f"fld_{uuid.uuid4().hex[:12]}"
    user_id = current_user["user_id"]

    try:
        repo.create_folder(
            folder_id=folder_id,
            tenant_id=tenant_id,
            folder_name=clean_name,
            description=req.description,
            visibility=req.visibility.value,
            created_by=user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.error("[folder_routes.create] Failed to create folder: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create folder")

    created = repo.get_folder_by_id(folder_id, tenant_id=tenant_id)
    return FolderResponse(
        folder_id=folder_id,
        folder_name=clean_name,
        description=req.description,
        visibility=req.visibility.value,
        photo_count=0,
        effective_access="manager",
        can_upload=True,
        can_delete=True,
        can_manage=True,
        created_by=user_id,
        created_at=str(created.get("created_at", "")),
    )


@router.get("", response_model=List[FolderResponse], status_code=status.HTTP_200_OK)
def list_accessible_folders(
    limit: int = Query(50, ge=1, le=200, description="Maximum folders to return per page"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    visibility: Optional[str] = Query(None, description="Filter by visibility: tenant_wide or restricted"),
    accessible_folders: List[dict] = Depends(get_user_accessible_folders),
):
    """
    Retrieve all folders accessible to the caller with pagination and visibility filtering.
    Uses the Single-Query Permission Resolver; honors 'tenant_wide' visibility and explicit ACLs.
    Excludes folders with 'revoked' access level.
    """
    filtered = accessible_folders
    if visibility and visibility.strip():
        vis = visibility.strip().lower()
        filtered = [f for f in filtered if f.get("visibility", "").lower() == vis]

    paginated = filtered[offset:offset + limit]

    return [
        FolderResponse(
            folder_id=f["folder_id"],
            folder_name=f["folder_name"],
            description=f.get("description"),
            visibility=f.get("visibility", "restricted"),
            photo_count=f.get("photo_count", 0),
            effective_access=f["effective_access"],
            can_upload=f["can_upload"],
            can_delete=f["can_delete"],
            can_manage=f["can_manage"],
            created_by=f.get("created_by"),
            created_at=str(f.get("created_at", "")),
        )
        for f in paginated
    ]


@router.get("/{folder_id}", response_model=FolderResponse, status_code=status.HTTP_200_OK)
def get_folder_details(
    folder_id: str,
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
):
    """Retrieve details for a specific folder if caller has access."""
    folder = check_folder_capability(folder_id, "view", current_user, tenant_id, repo)
    fid = folder["folder_id"]

    # Resolve caller's effective access
    accessible = repo.resolve_user_accessible_folders(
        user_id=current_user["user_id"],
        tenant_id=tenant_id,
        role=current_user.get("role", "viewer"),
    )
    matching = next((f for f in accessible if f["folder_id"] == fid), None)
    eff = matching["effective_access"] if matching else "viewer"

    return FolderResponse(
        folder_id=fid,
        folder_name=folder["folder_name"],
        description=folder.get("description"),
        visibility=folder.get("visibility", "restricted"),
        photo_count=folder.get("photo_count", 0),
        effective_access=eff,
        can_upload=eff in ("uploader", "editor", "manager"),
        can_delete=eff in ("editor", "manager"),
        can_manage=eff == "manager",
        created_by=folder.get("created_by"),
        created_at=str(folder.get("created_at", "")),
    )


@router.patch("/{folder_id}", response_model=FolderResponse, status_code=status.HTTP_200_OK)
def update_folder(
    folder_id: str,
    req: UpdateFolderRequest,
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
):
    """Update folder properties (rename, description, visibility). Requires 'manager' capability."""
    folder = check_folder_capability(folder_id, "manage", current_user, tenant_id, repo)
    fid = folder["folder_id"]

    if req.folder_name:
        existing = repo.get_folder_by_name(req.folder_name.strip(), tenant_id=tenant_id)
        if existing and existing["folder_id"] != fid:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A folder named '{req.folder_name}' already exists."
            )

    updated = repo.update_folder(
        folder_id=fid,
        tenant_id=tenant_id,
        folder_name=req.folder_name,
        description=req.description,
        visibility=req.visibility.value if req.visibility else None,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update folder")

    latest = repo.get_folder_by_id(fid, tenant_id=tenant_id)
    return FolderResponse(
        folder_id=fid,
        folder_name=latest["folder_name"],
        description=latest.get("description"),
        visibility=latest.get("visibility", "restricted"),
        photo_count=latest.get("photo_count", 0),
        effective_access="manager",
        can_upload=True,
        can_delete=True,
        can_manage=True,
        created_by=latest.get("created_by"),
        created_at=str(latest.get("created_at", "")),
    )


@router.delete("/{folder_id}", status_code=status.HTTP_200_OK)
def delete_folder(
    folder_id: str,
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
):
    """Delete a folder and its photo records. Requires 'manager' capability."""
    folder = check_folder_capability(folder_id, "manage", current_user, tenant_id, repo)
    fid = folder["folder_id"]

    deleted = repo.delete_folder(folder_id=fid, tenant_id=tenant_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete folder")

    return {
        "status": "success",
        "message": f"Folder '{folder['folder_name']}' deleted successfully",
        "folder_id": fid,
    }


# -------------------------------------------------------------------
# Folder Access Control (ACL) Endpoints
# -------------------------------------------------------------------

@router.post("/access/bulk", status_code=status.HTTP_200_OK)
def bulk_set_folder_access(
    req: BulkFolderAccessRequest,
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
):
    """
    Assign multiple members to multiple folders in a single batch request.
    Reduces admin fatigue by eliminating repetitive single-assignment calls.
    """
    role = str(current_user.get("role", "viewer")).lower()
    if role not in ("owner", "admin"):
        # For non-admin, ensure user is manager for all target folders
        for fid in req.folder_ids:
            check_folder_capability(fid, "manage", current_user, tenant_id, repo)

    count = repo.bulk_set_folder_access(
        tenant_id=tenant_id,
        folder_ids=req.folder_ids,
        user_ids=req.user_ids,
        access_level=req.access_level.value,
        granted_by=current_user["user_id"],
    )

    return {
        "status": "success",
        "message": f"Assigned {len(req.user_ids)} users to {len(req.folder_ids)} folders with access level '{req.access_level.value}'",
        "assigned_mappings_count": count,
    }


@router.post("/{folder_id}/access", status_code=status.HTTP_200_OK)
def set_single_folder_access(
    folder_id: str,
    req: SingleFolderAccessGrantRequest,
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
):
    """
    Grant or update a specific member's access level for a folder.
    Supports setting access_level to 'revoked' to exclude a user from a tenant_wide folder (Trap 2).
    """
    folder = check_folder_capability(folder_id, "manage", current_user, tenant_id, repo)
    fid = folder["folder_id"]

    # Verify target user belongs to this tenant
    target_user = repo.get_user_by_id(req.user_id, tenant_id=tenant_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target user not found in organization")

    repo.set_folder_access(
        folder_id=fid,
        user_id=req.user_id,
        tenant_id=tenant_id,
        access_level=req.access_level.value,
        granted_by=current_user["user_id"],
    )

    return {
        "status": "success",
        "message": f"Set access level '{req.access_level.value}' for user '{target_user.get('username')}' on folder '{folder['folder_name']}'",
        "folder_id": fid,
        "user_id": req.user_id,
        "access_level": req.access_level.value,
    }


@router.delete("/{folder_id}/access/{user_id}", status_code=status.HTTP_200_OK)
def revoke_single_folder_access(
    folder_id: str,
    user_id: str,
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
):
    """Revoke a member's explicit access record for a folder."""
    folder = check_folder_capability(folder_id, "manage", current_user, tenant_id, repo)
    fid = folder["folder_id"]

    repo.remove_folder_access(folder_id=fid, user_id=user_id, tenant_id=tenant_id)

    return {
        "status": "success",
        "message": f"Revoked explicit access record for user '{user_id}' on folder '{folder['folder_name']}'",
        "folder_id": fid,
        "user_id": user_id,
    }


@router.get("/{folder_id}/members", response_model=List[FolderMemberAccessItem], status_code=status.HTTP_200_OK)
def list_folder_members(
    folder_id: str,
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
):
    """List all members with explicit access records for this folder."""
    folder = check_folder_capability(folder_id, "manage", current_user, tenant_id, repo)
    fid = folder["folder_id"]

    members = repo.get_folder_members(folder_id=fid, tenant_id=tenant_id)
    return [
        FolderMemberAccessItem(
            user_id=m["user_id"],
            username=m.get("username", "Unknown"),
            email=m.get("email", ""),
            tenant_role=m.get("tenant_role", "viewer"),
            access_level=m.get("access_level", "inherit"),
            granted_by=m.get("granted_by"),
            created_at=str(m.get("created_at", "")),
        )
        for m in members
    ]

