"""
src/api/dependencies.py — Centralized FastAPI Dependency Injection providers.
Decouples router endpoints from concrete service instances, enabling seamless unit testing and mocking.
"""
from typing import Optional, Dict, Any
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.services.user_auth_service import get_auth_service, UserAuthService
from src.services.image_processing_service import ImageProcessingService
from src.services.image_search_service import ImageSearchService

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


def get_image_processing_service(
    request: Request,
    ai=Depends(get_ai_manager),
) -> ImageProcessingService:
    """Dependency injecting ImageProcessingService."""
    return ImageProcessingService(ai=ai)


def get_image_search_service(
    request: Request,
    ai=Depends(get_ai_manager),
) -> ImageSearchService:
    """Dependency injecting ImageSearchService."""
    return ImageSearchService(ai=ai)


from src.services.photo_upload_service import get_upload_service

get_search_service = get_image_search_service

