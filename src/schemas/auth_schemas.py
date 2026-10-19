"""
src/schemas/auth_schemas.py — Pydantic schemas for Multi-Tenant Auth, RBAC, and Member Lifecycle.
Implements decoupled tenant creation, invite previews, locked invite acceptance, and multi-tenant workspace login.
"""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class TenantRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    CONTRIBUTOR = "contributor"
    VIEWER = "viewer"


class FolderVisibility(str, Enum):
    TENANT_WIDE = "tenant_wide"
    RESTRICTED = "restricted"


class FolderAccessLevel(str, Enum):
    INHERIT = "inherit"
    REVOKED = "revoked"
    VIEWER = "viewer"
    UPLOADER = "uploader"
    EDITOR = "editor"
    MANAGER = "manager"


# ── 1. Founding Admin (New Tenant) Registration ─────────────────────
class RegisterTenantRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_\-]+$", description="Unique admin username", examples=["alex_founder"])
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", description="Administrator email address", examples=["alex@studiopro.com"])
    password: str = Field(..., min_length=8, description="Secure account password (min 8 chars)", examples=["SecurePass123!"])
    organization_name: str = Field(..., min_length=2, max_length=100, description="Organization or workspace name", examples=["Studio Pro NYC"])
    ignore_pending_invite: bool = Field(
        False,
        description="If True, permits creating a new tenant even if this email has an active pending invite to another workspace"
    )


# ── 2. Invited Member Onboarding ────────────────────────────────────
class InvitePreviewResponse(BaseModel):
    invite_id: str
    tenant_id: str
    organization_name: str
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", description="Invited email address")
    role: TenantRole
    expires_at: str


class AcceptInviteRequest(BaseModel):
    invite_token: str = Field(..., min_length=16, description="Cryptographic token from invite link")
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_\-]+$", description="Unique username in workspace", examples=["sarah_photographer"])
    password: str = Field(..., min_length=8, description="Account password (min 8 chars)", examples=["MemberSecure123!"])


# ── 3. Unified Authentication, Disambiguation & Token Responses ─────
class LoginRequest(BaseModel):
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", description="Registered account email", examples=["user@example.com"])
    password: str = Field(..., description="Account password", examples=["secret123"])
    tenant_id: Optional[str] = Field(None, description="Optional tenant_id to select workspace directly when user belongs to multiple organizations")


class TenantOptionItem(BaseModel):
    tenant_id: str
    organization_name: str
    role: str


class MultiTenantLoginResponse(BaseModel):
    status: str = "select_tenant"
    message: str = "Multiple workspace memberships found. Please select which workspace to enter."
    available_tenants: List[TenantOptionItem]


class SwitchTenantRequest(BaseModel):
    tenant_id: str = Field(..., description="Target workspace ID to switch active session to")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", description="Account email")
    role: str
    tenant_id: str
    organization_name: str


class UserProfileResponse(BaseModel):
    user_id: str
    username: str
    email: str
    role: str
    tenant_id: str
    organization_name: str
    is_active: bool = True
    storage_bucket: Optional[str] = None
    created_at: str
    last_seen: Optional[str] = None


# ── 4. Member Management & Invitation Administration ────────────────
class TenantInviteRequest(BaseModel):
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", description="Email of user to invite", examples=["colleague@example.com"])
    role: TenantRole = Field(TenantRole.VIEWER, description="Tenant-wide base role (default: viewer)")
    initial_folder_ids: List[str] = Field(default_factory=list, description="List of folder IDs pre-granted upon signup")
    initial_access_level: FolderAccessLevel = Field(FolderAccessLevel.INHERIT, description="Access level for initial folders")


class TenantInviteResponse(BaseModel):
    invite_id: str
    tenant_id: str
    email: str
    role: str
    invite_token: str
    initial_folder_ids: List[str]
    expires_at: str


class UpdateMemberRoleRequest(BaseModel):
    role: TenantRole = Field(..., description="Updated tenant-wide role")


class TenantMemberItem(BaseModel):
    user_id: str
    username: str
    email: str
    role: str
    is_active: bool = True
    created_at: str
    last_seen: str


class StorageConfigRequest(BaseModel):
    s3_bucket: Optional[str] = Field(None, description="AWS S3 bucket name")
    aws_region: Optional[str] = Field(None, description="AWS Region (e.g. us-east-1)")


class StorageConfigResponse(BaseModel):
    status: str
    message: str
    bucket: Optional[str] = None
    configured: bool = True
