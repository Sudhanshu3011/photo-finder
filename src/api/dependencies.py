"""
src/api/dependencies.py — Centralized FastAPI Dependency Injection providers.
Decouples router endpoints from concrete service instances, enabling seamless unit testing and mocking.
Implements Top-Level Import Hygiene and Two-Tier RBAC permission guards.
"""
from typing import Optional, Dict, Any, List, Set, Callable
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.core.tenant_context import set_current_tenant_id
from src.modules.infra.postgres_repository import get_repository, PostgresRepository
from src.services.user_auth_service import get_auth_service, UserAuthService
from src.services.image_processing_service import ImageProcessingService
from src.services.image_search_service import ImageSearchService
from src.services.photo_upload_service import get_upload_service
from src.services.inference_client import get_inference_client, InferenceClient

bearer_scheme = HTTPBearer(auto_error=False)


def get_ai_manager(request: Request):
    """Retrieve initialized AIModelManager singleton from app state."""
    return getattr(request.app.state, "ai", None)


def get_ai_semaphore(request: Request):
    """Retrieve concurrency semaphore from app state."""
    return getattr(request.app.state, "ai_semaphore", None)


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    auth_service: UserAuthService = Depends(get_auth_service),
) -> Optional[Dict[str, Any]]:
    """Extract and verify user from Bearer authorization header if present."""
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    else:
        raw_header = request.headers.get("authorization")
        if raw_header:
            scheme, _, raw_token = raw_header.partition(" ")
            if scheme.lower() == "bearer" and raw_token:
                token = raw_token.strip()

    if not token:
        return None
    return auth_service.verify_token(token)


def require_current_user(
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Dependency requiring an authenticated user."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


def get_current_tenant_id(
    request: Request,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user),
) -> str:
    """
    Extract and enforce tenant context without cluttering endpoint documentation.
    Priority:
    1. Authenticated user's tenant_id (cryptographically signed in JWT)
    2. Explicit X-Tenant-ID header (read directly from request headers)
    3. request.state.tenant_id if set by middleware
    4. Default fallback: 'default'
    """
    tenant_id = "default"
    if current_user and current_user.get("tenant_id"):
        tenant_id = str(current_user["tenant_id"]).strip()
    else:
        raw_header = request.headers.get("x-tenant-id") or request.headers.get("X-Tenant-ID")
        if raw_header and raw_header.strip():
            tenant_id = raw_header.strip()
        elif request.query_params.get("tenant_id") and request.query_params.get("tenant_id").strip():
            tenant_id = request.query_params.get("tenant_id").strip()
        elif hasattr(request.state, "tenant_id") and request.state.tenant_id:
            tenant_id = str(request.state.tenant_id).strip()

    request.state.tenant_id = tenant_id
    set_current_tenant_id(tenant_id)
    return tenant_id


# -------------------------------------------------------------------
# RBAC & Folder Permission Dependencies
# -------------------------------------------------------------------

ROLE_HIERARCHY: Dict[str, int] = {
    "viewer": 1,
    "contributor": 2,
    "editor": 3,
    "admin": 4,
    "owner": 5,
}


def has_minimum_role(user_role: str, required_role: str) -> bool:
    """Returns True if user_role's rank >= required_role's rank in hierarchy."""
    user_level = ROLE_HIERARCHY.get(str(user_role or "viewer").strip().lower(), 1)
    req_level = ROLE_HIERARCHY.get(str(required_role).strip().lower(), 1)
    return user_level >= req_level


def require_minimum_role(required_role: str):
    """FastAPI dependency factory enforcing minimum role level."""
    def _dependency(current_user: Dict[str, Any] = Depends(require_current_user)) -> Dict[str, Any]:
        role = current_user.get("role", "viewer")
        if not has_minimum_role(role, required_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{required_role}' or higher required for this operation. Current role: '{role}'."
            )
        return current_user
    return _dependency


def require_editor_or_higher(
    current_user: Dict[str, Any] = Depends(require_current_user),
) -> Dict[str, Any]:
    """Requires caller to be at least an 'editor' (editor, admin, owner)."""
    role = current_user.get("role", "viewer")
    if not has_minimum_role(role, "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Editor, Administrator, or Owner role required for this operation"
        )
    return current_user


def require_tenant_admin(
    current_user: Dict[str, Any] = Depends(require_current_user),
) -> Dict[str, Any]:
    """Requires caller to be an Organization 'owner' or 'admin'."""
    role = str(current_user.get("role", "viewer")).lower()
    if not has_minimum_role(role, "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant administrator or owner privileges required"
        )
    return current_user


def require_folder_creation_permission(
    current_user: Dict[str, Any] = Depends(require_current_user),
) -> Dict[str, Any]:
    """Requires caller to have folder creation rights (contributor or higher)."""
    role = str(current_user.get("role", "viewer")).lower()
    if not has_minimum_role(role, "contributor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to create folders. Role 'viewer' cannot create albums."
        )
    return current_user


def get_user_accessible_folders(
    current_user: Dict[str, Any] = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
) -> List[Dict[str, Any]]:
    """Resolves all accessible folders and effective capabilities for the caller via Single-Query Resolver."""
    uid = current_user.get("user_id", "")
    role = current_user.get("role", "viewer")
    return repo.resolve_user_accessible_folders(user_id=uid, tenant_id=tenant_id, role=role)


def check_folder_capability(
    folder_identifier: str,
    capability: str,
    current_user: Dict[str, Any],
    tenant_id: str,
    repo: PostgresRepository,
) -> Dict[str, Any]:
    """
    Validates caller's permission ('view', 'upload', 'delete', 'manage') on a folder.
    Accepts folder_id or folder_name.
    Raises HTTPException(403) or HTTPException(404) on failure.
    """
    clean_target = (folder_identifier or "").strip()
    if not clean_target:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Folder identifier required")

    role = str(current_user.get("role", "viewer")).lower()
    uid = current_user.get("user_id", "")

    # Resolve target folder record
    folder = repo.get_folder_by_id(clean_target, tenant_id=tenant_id)
    if not folder:
        folder = repo.get_folder_by_name(clean_target, tenant_id=tenant_id)
    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Folder '{clean_target}' not found in organization."
        )

    fid = folder["folder_id"]

    # Tenant admins have universal manager access
    if role in ("owner", "admin"):
        return folder

    # Evaluate via accessible folders resolver
    accessible = repo.resolve_user_accessible_folders(user_id=uid, tenant_id=tenant_id, role=role)
    matching = next((f for f in accessible if f["folder_id"] == fid), None)

    if not matching:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied to folder '{folder['folder_name']}'. Folder is restricted or access revoked."
        )

    cap = capability.lower()
    if cap == "view":
        return folder
    elif cap == "upload" and not matching.get("can_upload"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Upload permission denied for folder '{folder['folder_name']}'."
        )
    elif cap == "delete" and not matching.get("can_delete"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Delete permission denied for folder '{folder['folder_name']}'."
        )
    elif cap == "manage" and not matching.get("can_manage"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Folder management permission denied for folder '{folder['folder_name']}'."
        )

    return folder


# -------------------------------------------------------------------
# Service Dependencies
# -------------------------------------------------------------------

def get_inference_client_dep() -> InferenceClient:
    """Dependency injecting unified InferenceClient singleton."""
    return get_inference_client()


def get_image_processing_service(
    request: Request,
    ai=Depends(get_ai_manager),
    inference_client: InferenceClient = Depends(get_inference_client_dep),
) -> ImageProcessingService:
    """Dependency injecting ImageProcessingService with decoupled InferenceClient."""
    return ImageProcessingService(ai=ai, inference_client=inference_client)


def get_image_search_service(
    request: Request,
    ai=Depends(get_ai_manager),
    inference_client: InferenceClient = Depends(get_inference_client_dep),
) -> ImageSearchService:
    """Dependency injecting ImageSearchService with decoupled InferenceClient."""
    return ImageSearchService(ai=ai, inference_client=inference_client)


get_search_service = get_image_search_service
