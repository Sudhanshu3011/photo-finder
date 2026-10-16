"""
src/schemas/folder_schemas.py — Pydantic schemas for Folders and Granular Access Control (ACL).
"""
from typing import List, Optional
from pydantic import BaseModel, Field

from src.schemas.auth_schemas import FolderVisibility, FolderAccessLevel, TenantRole


class CreateFolderRequest(BaseModel):
    folder_name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_\-\s]+$", description="Unique folder/album name inside the tenant", examples=["wedding_2026"])
    description: Optional[str] = Field(None, max_length=255, examples=["Raw photos from ceremony"])
    visibility: FolderVisibility = Field(FolderVisibility.RESTRICTED, description="Visibility mode: 'tenant_wide' or 'restricted'")


class UpdateFolderRequest(BaseModel):
    folder_name: Optional[str] = Field(None, min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_\-\s]+$", description="New folder name")
    description: Optional[str] = Field(None, max_length=255)
    visibility: Optional[FolderVisibility] = None


class FolderResponse(BaseModel):
    folder_id: str
    folder_name: str
    description: Optional[str] = None
    visibility: str
    photo_count: int = 0
    effective_access: str
    can_upload: bool
    can_delete: bool
    can_manage: bool
    created_by: Optional[str] = None
    created_at: str


class SingleFolderAccessGrantRequest(BaseModel):
    user_id: str = Field(..., description="ID of the user to grant access to")
    access_level: FolderAccessLevel = Field(FolderAccessLevel.INHERIT, description="Folder access level override")


class BulkFolderAccessRequest(BaseModel):
    user_ids: List[str] = Field(..., min_length=1, description="List of user IDs")
    folder_ids: List[str] = Field(..., min_length=1, description="List of folder IDs")
    access_level: FolderAccessLevel = Field(FolderAccessLevel.INHERIT, description="Access level to set for all specified users and folders")


class FolderMemberAccessItem(BaseModel):
    user_id: str
    username: str
    email: str
    tenant_role: str
    access_level: str
    granted_by: Optional[str] = None
    created_at: str

