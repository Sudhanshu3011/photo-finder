"""
src/api/dependencies.py — Centralized FastAPI Dependency Injection providers.
Decouples router endpoints from concrete service instances, enabling seamless unit testing and mocking.
Injects local FAISS vector stores and AI model managers.
"""
from fastapi import Depends, Request

from src.core.security import get_verified_keys
from src.services.upload_service import UploadService
from src.services.search_service import SearchService
from src.services.faiss_service import faiss_store


def get_ai_manager(request: Request):
    """Retrieve initialized AIModelManager singleton from app state."""
    return getattr(request.app.state, "ai", None)


def get_ai_semaphore(request: Request):
    """Retrieve concurrency semaphore from app state."""
    return getattr(request.app.state, "ai_semaphore", None)


def get_vector_store():
    """Retrieve FAISS Vector Store singleton."""
    return faiss_store


def get_upload_service(
    request: Request,
    ai=Depends(get_ai_manager),
    sem=Depends(get_ai_semaphore),
    vector_store=Depends(get_vector_store),
) -> UploadService:
    """Factory dependency injecting UploadService with AI and local FAISS vector store."""
    return UploadService(
        ai=ai,
        ai_semaphore=sem,
        vector_store=vector_store,
    )


def get_search_service(
    request: Request,
    ai=Depends(get_ai_manager),
    sem=Depends(get_ai_semaphore),
    vector_store=Depends(get_vector_store),
) -> SearchService:
    """Factory dependency injecting SearchService with AI and local FAISS vector store."""
    return SearchService(
        ai=ai,
        ai_semaphore=sem,
        vector_store=vector_store,
    )
