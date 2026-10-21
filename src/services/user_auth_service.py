"""
src/services/user_auth_service.py — Orchestrator for Multi-Tenant Auth, Registration, and JWT Issuance.
Implements decoupled tenant creation (register-tenant), invite previews, locked invite acceptance,
per-tenant identity scoping, and multi-tenant workspace login disambiguation.
"""
import logging
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Union

from src.schemas.auth_schemas import (
    RegisterTenantRequest,
    AcceptInviteRequest,
    InvitePreviewResponse,
    TenantRole,
)
from src.modules.infra.postgres_repository import get_repository
from src.modules.infra.kv_cache import get_kv_cache
from src.modules.auth.password_hasher import hash_password, verify_password
from src.modules.auth.jwt_manager import create_access_token, decode_access_token

logger = logging.getLogger("src.services.user_auth_service")


class UserAuthService:
    """Orchestrator for decoupled multi-tenant authentication, registration, and authorization."""

    def __init__(self, repo=None):
        self.repo = repo or get_repository()

    # -------------------------------------------------------------------
    # Flow 1: Founding Admin Registration (Creates New Tenant)
    # -------------------------------------------------------------------
    def register_tenant(self, req: RegisterTenantRequest) -> Dict[str, Any]:
        """
        Creates a new tenant organization and assigns the registering user role = 'owner'.
        Validates against active pending invites to prevent accidental orphan tenant creation.
        """
        clean_email = req.email.strip().lower()
        clean_username = req.username.strip()
        org_name = req.organization_name.strip()
        logger.info("[user_auth_service.register_tenant] Creating tenant '%s' for email=%s", org_name, clean_email)

        # 1. Prevent accidental orphan tenant creation if user has an active invite elsewhere
        if not req.ignore_pending_invite:
            pending_invite = self.repo.get_active_invite_by_email(clean_email)
            if pending_invite:
                inv_org = pending_invite.get("organization_name", "another organization")
                raise ValueError(
                    f"You have a pending invitation to join '{inv_org}'. "
                    "Please use your invitation link to join, or set ignore_pending_invite=True to create your own workspace."
                )

        # 2. Generate unique tenant_id and user_id
        assigned_tenant = f"tenant_{uuid.uuid4().hex[:12]}"
        user_id = f"usr_{uuid.uuid4().hex[:12]}"
        storage_bucket = f"vs-{assigned_tenant}"
        hashed_pw = hash_password(req.password)

        # 3. Create tenant record
        self.repo.create_tenant(
            tenant_id=assigned_tenant,
            name=org_name,
            storage_bucket=storage_bucket,
        )

        # 4. Create owner user bound to new tenant
        created = self.repo.create_user(
            user_id=user_id,
            username=clean_username,
            email=clean_email,
            hashed_password=hashed_pw,
            role=TenantRole.OWNER.value,
            storage_bucket=storage_bucket,
            tenant_id=assigned_tenant,
        )
        if not created:
            raise RuntimeError("Database error while creating organization owner")

        # 5. Atomically seed default 'general' album with creator as manager
        default_folder_id = f"fld_{uuid.uuid4().hex[:12]}"
        try:
            self.repo.create_folder(
                folder_id=default_folder_id,
                tenant_id=assigned_tenant,
                folder_name="general",
                description="Default organization photos",
                visibility="tenant_wide",
                created_by=user_id,
            )
        except Exception as e:
            logger.warning("[user_auth_service.register_tenant] Default folder seed warning: %s", e)

        logger.info("[user_auth_service.register_tenant] Tenant %s and owner %s created successfully", assigned_tenant, user_id)
        user = self.repo.get_user_by_id(user_id, tenant_id=assigned_tenant) or {
            "user_id": user_id,
            "username": clean_username,
            "email": clean_email,
            "role": TenantRole.OWNER.value,
            "tenant_id": assigned_tenant,
        }
        user["organization_name"] = org_name
        return user

    # -------------------------------------------------------------------
    # Flow 2: Invited Member Onboarding (Preview & Accept)
    # -------------------------------------------------------------------
    def preview_invite(self, invite_token: str) -> Dict[str, Any]:
        """
        Public preview of an invitation token for the landing page.
        Returns organization name, locked email, and assigned role.
        """
        invite = self.repo.get_invite_by_token(invite_token)
        if not invite:
            raise ValueError("Invitation link is invalid, expired, or has already been used.")

        return {
            "invite_id": invite["invite_id"],
            "tenant_id": invite["tenant_id"],
            "organization_name": invite.get("organization_name", "Organization"),
            "email": invite["email"],
            "role": invite["role"],
            "expires_at": str(invite["expires_at"]),
        }

    def accept_invite(self, req: AcceptInviteRequest) -> Dict[str, Any]:
        """
        Consumes an invitation token and registers the member into the existing tenant.
        The user's email is strictly locked to the invited email (0% hijacking risk).
        """
        token = req.invite_token.strip()
        invite = self.repo.get_invite_by_token(token)
        if not invite:
            raise ValueError("Invitation link is invalid, expired, or has already been used.")

        target_tenant = invite["tenant_id"]
        invited_email = invite["email"].strip().lower()
        clean_username = req.username.strip()
        assigned_role = str(invite.get("role", "viewer")).lower()
        storage_bucket = invite.get("storage_bucket")

        # Check per-tenant uniqueness constraints
        existing_email_in_tenant = self.repo.get_user_by_tenant_and_email(target_tenant, invited_email)
        if existing_email_in_tenant:
            raise ValueError(f"An account for '{invited_email}' already exists in this workspace. Please log in.")

        existing_user_in_tenant = self.repo.get_user_by_tenant_and_username(target_tenant, clean_username)
        if existing_user_in_tenant:
            raise ValueError(f"Username '{clean_username}' is already taken in this workspace.")

        user_id = f"usr_{uuid.uuid4().hex[:12]}"
        hashed_pw = hash_password(req.password)

        created = self.repo.create_user(
            user_id=user_id,
            username=clean_username,
            email=invited_email,
            hashed_password=hashed_pw,
            role=assigned_role,
            storage_bucket=storage_bucket,
            tenant_id=target_tenant,
        )
        if not created:
            raise RuntimeError("Failed to create user record for workspace")

        # Atomically grant pre-assigned folders
        initial_folders = invite.get("initial_folder_ids", [])
        initial_access = invite.get("initial_access_level", "inherit")
        for fid in initial_folders:
            self.repo.set_folder_access(
                folder_id=fid,
                user_id=user_id,
                tenant_id=target_tenant,
                access_level=initial_access,
                granted_by=invite.get("invited_by"),
            )

        # Mark invitation consumed
        self.repo.mark_invite_accepted(token)
        logger.info("[user_auth_service.accept_invite] User %s joined workspace %s via invite", user_id, target_tenant)

        user = self.repo.get_user_by_id(user_id, tenant_id=target_tenant) or {
            "user_id": user_id,
            "username": clean_username,
            "email": invited_email,
            "role": assigned_role,
            "tenant_id": target_tenant,
        }
        user["organization_name"] = invite.get("organization_name", "Organization")
        return user

    # -------------------------------------------------------------------
    # Flow 3: Unified Login & Tenant Disambiguation
    # -------------------------------------------------------------------
    def authenticate(
        self,
        email_or_username: str,
        password: str,
        tenant_id: Optional[str] = None,
    ) -> Union[Dict[str, Any], List[Dict[str, Any]], None]:
        """
        Authenticates credentials across tenants using pre-auth lookup.
        - If matching accounts exist in exactly 1 tenant: returns the user dict.
        - If matching accounts exist in multiple tenants and tenant_id is provided: returns user in target tenant.
        - If matching accounts exist in multiple tenants and tenant_id is NOT provided: returns list of matching user dicts.
        """
        clean_key = email_or_username.strip().lower()
        logger.info("[user_auth_service.authenticate] Authenticating key: %s (tenant_id=%s)", clean_key, tenant_id)

        # Look up all active tenant accounts matching this email globally
        matching_users = self.repo.get_users_by_email_preauth(clean_key)
        if not matching_users:
            # Fallback check by username if not found by email
            fallback_user = self.repo.get_user_preauth(clean_key)
            if fallback_user and fallback_user.get("is_active", True):
                matching_users = [fallback_user]

        if not matching_users:
            logger.warning("[user_auth_service.authenticate] No account found for: %s", clean_key)
            return None

        # Verify password on candidates
        valid_users = [
            u for u in matching_users
            if u.get("hashed_password") and verify_password(password, u["hashed_password"])
        ]
        if not valid_users:
            logger.warning("[user_auth_service.authenticate] Password verification failed for: %s", clean_key)
            return None

        # If caller explicitly provided tenant_id, select that specific tenant account
        if tenant_id and tenant_id.strip():
            tid = tenant_id.strip()
            chosen = next((u for u in valid_users if u.get("tenant_id") == tid), None)
            if not chosen:
                logger.warning("[user_auth_service.authenticate] User has no membership in tenant_id=%s", tid)
                return None
            return chosen

        # If user belongs to exactly one workspace, return it directly
        if len(valid_users) == 1:
            return valid_users[0]

        # Multi-tenant user without tenant_id specified: return list for disambiguation modal
        logger.info("[user_auth_service.authenticate] Multi-tenant disambiguation needed (%d tenants)", len(valid_users))
        return valid_users

    # -------------------------------------------------------------------
    # Flow 4: Workspace Switching
    # -------------------------------------------------------------------
    def switch_tenant(self, email: str, target_tenant_id: str) -> Dict[str, Any]:
        """
        Switch active session context to another organization where the user has an active membership.
        """
        tid = target_tenant_id.strip()
        user = self.repo.get_user_by_tenant_and_email(tid, email)
        if not user or not user.get("is_active", True):
            raise PermissionError(f"You do not have an active membership in workspace '{tid}'.")

        logger.info("[user_auth_service.switch_tenant] Switched session for %s to workspace %s", email, tid)
        return user

    # -------------------------------------------------------------------
    # Token & Cache Management
    # -------------------------------------------------------------------
    def issue_token(self, user: Dict[str, Any]) -> str:
        """Issue a JWT access token stamped with token_version and cache credentials in Redis."""
        tid = user.get("tenant_id") or "default"
        uid = user["user_id"]
        role = user.get("role", "viewer")
        org_name = user.get("organization_name", "")
        token_ver = int(user.get("token_version", 1))

        token_data = {
            "sub": uid,
            "username": user["username"],
            "email": user.get("email", ""),
            "role": role,
            "tenant_id": tid,
            "org": org_name,
            "token_version": token_ver,
        }
        token = create_access_token(data=token_data, tenant_id=tid, token_version=token_ver)

        # Cache in Redis with 5-minute TTL to mitigate Trap 3 (Stale JWT Claims)
        try:
            cache = get_kv_cache()
            cache.set(f"user_auth:{tid}:{uid}", f"{role}:active", ttl=300)
            cache.set(f"user_token_version:{tid}:{uid}", str(token_ver), ttl=86400)
        except Exception:
            pass

        logger.info("[user_auth_service.issue_token] Issued token for user_id=%s, tenant_id=%s, token_version=%d", uid, tid, token_ver)
        return token

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Validate token signature, verify active status with cache or DB, and reject stale token versions."""
        payload = decode_access_token(token)
        if not payload or "sub" not in payload:
            logger.warning("[user_auth_service.verify_token] Invalid or expired token")
            return None

        uid = payload["sub"]
        tid = payload.get("tenant_id", "default")
        token_ver = int(payload.get("token_version", 1))

        # Check instant revocation in cache if present
        try:
            cache = get_kv_cache()
            cached_auth = cache.get(f"user_auth:{tid}:{uid}")
            if cached_auth:
                parts = str(cached_auth).split(":")
                status = parts[1] if len(parts) > 1 else "active"
                if status == "revoked":
                    logger.warning("[user_auth_service.verify_token] Token rejected by cache revocation for user=%s", uid)
                    return None

            cached_ver = cache.get(f"user_token_version:{tid}:{uid}")
            if cached_ver is not None and int(cached_ver) > token_ver:
                logger.warning(
                    "[user_auth_service.verify_token] Stale token rejected (cached_ver=%s > token_ver=%s) for user=%s",
                    cached_ver, token_ver, uid
                )
                return None
        except Exception:
            pass

        user = self.repo.get_user_by_id(uid, tenant_id=tid)
        if not user:
            user = self.repo.get_user_preauth(uid)

        if not user or not user.get("is_active", True):
            return None

        # Verify DB token_version
        active_ver = int(user.get("token_version", 1))
        if active_ver > token_ver:
            logger.warning(
                "[user_auth_service.verify_token] Stale token rejected by DB (active_ver=%s > token_ver=%s) for user=%s",
                active_ver, token_ver, uid
            )
            return None

        if not user.get("tenant_id"):
            user["tenant_id"] = tid

        if not user.get("organization_name"):
            t = self.repo.get_tenant_by_id(tid)
            if t:
                user["organization_name"] = t.get("name", "Organization")

        return user

    def invalidate_auth_cache(self, tenant_id: str, user_id: str):
        """Immediately evict user authorization cache upon role change or deletion, bumping token version."""
        tid = tenant_id.strip()
        uid = user_id.strip()
        try:
            cache = get_kv_cache()
            cache.set(f"user_auth:{tid}:{uid}", "none:revoked", ttl=300)
            if hasattr(cache, "delete_sync"):
                cache.delete_sync(f"user_auth:{tid}:{uid}")
            else:
                cache._mem_store.pop(f"user_auth:{tid}:{uid}", None)
            cache.incr(f"user_token_version:{tid}:{uid}")
        except Exception as e:
            logger.debug("[invalidate_auth_cache] Cache bump error: %s", e)

        try:
            self.repo.increment_token_version(user_id=uid, tenant_id=tid)
        except Exception as e:
            logger.warning("[invalidate_auth_cache] Failed to increment DB token version: %s", e)

    def create_invite(
        self,
        tenant_id: str,
        email: str,
        role: str,
        invited_by: str,
        initial_folder_ids: Optional[List[str]] = None,
        initial_access_level: str = "inherit",
    ) -> Dict[str, Any]:
        """Create an organization invitation token."""
        invite_id = f"inv_{uuid.uuid4().hex[:12]}"
        invite_token = f"inv_{secrets.token_urlsafe(24)}"
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        folder_ids = initial_folder_ids or []

        created = self.repo.create_tenant_invite(
            invite_id=invite_id,
            tenant_id=tenant_id,
            email=email,
            role=role,
            initial_folder_ids=folder_ids,
            initial_access_level=initial_access_level,
            invited_by=invited_by,
            invite_token=invite_token,
            expires_at=expires_at,
        )
        if not created:
            raise RuntimeError("Failed to create tenant invite")

        return {
            "invite_id": invite_id,
            "tenant_id": tenant_id,
            "email": email,
            "role": role,
            "invite_token": invite_token,
            "initial_folder_ids": folder_ids,
            "expires_at": expires_at.isoformat(),
        }

    def get_profile(self, user_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieve user profile by ID with organization_name."""
        tid = (tenant_id or "default").strip()
        user = self.repo.get_user_by_id(user_id, tenant_id=tid)
        if user and not user.get("organization_name"):
            t = self.repo.get_tenant_by_id(tid)
            if t:
                user["organization_name"] = t.get("name", "Organization")
        return user

    def update_storage_config(self, user_id: str, bucket_or_config: str, tenant_id: Optional[str] = None) -> bool:
        """Update storage bucket on user's profile."""
        return self.repo.update_user_storage_bucket(user_id, bucket_or_config, tenant_id=tenant_id)


_auth_service_instance: Optional[UserAuthService] = None


def get_auth_service() -> UserAuthService:
    global _auth_service_instance
    if _auth_service_instance is None:
        _auth_service_instance = UserAuthService()
    return _auth_service_instance
