"""
tests/conftest.py — Pytest fixtures and providers for testing Visual Search API.
Provides isolated mock environments and async HTTP test client.
"""
import os
os.environ["TESTING"] = "true"
os.environ["SQLITE_DB_PATH"] = "/tmp/test_local_storage.db"
os.environ["FAISS_DATA_DIR"] = "/tmp/test_faiss_data"
from typing import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app
from src.core.security import get_verified_keys
from src.api.dependencies import get_upload_service, get_search_service, require_current_user
from src.services.photo_upload_service import PhotoUploadService, get_upload_service as real_get_upload_service
from src.services.image_search_service import ImageSearchService, get_image_search_service


from PIL import Image
import io


def create_mock_jpeg(width: int = 120, height: int = 120) -> bytes:
    """Generate valid in-memory JPEG bytes for upload testing."""
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


async def mock_get_verified_keys():
    """Mock credentials provider for tests."""
    return {
        "cloudinary_url": "cloudinary://123:abc@test",
        "cloudinary_creds": {"cloud_name": "test", "api_key": "123", "api_secret": "abc"},
    }


from fastapi import Request, HTTPException, status
from src.services.user_auth_service import get_auth_service


def mock_require_current_user(request: Request):
    """Mock authenticated user provider for tests supporting real tokens or test bypass."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
        user = get_auth_service().verify_token(token)
        if user:
            return user
        if token in ("mock_test_token", "mock_token"):
            return {
                "user_id": "test_user_id",
                "username": "testuser",
                "email": "testuser@example.com",
                "role": "admin",
                "cloudinary_url": "cloudinary://123:abc@test",
            }
    # Enforce strict 401 on /api/auth/me if unauthenticated
    if request.url.path == "/api/auth/me":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {
        "user_id": "test_user_id",
        "username": "testuser",
        "email": "testuser@example.com",
        "role": "admin",
        "cloudinary_url": "cloudinary://123:abc@test",
    }


def mock_get_upload_service():
    """Test PhotoUploadService provider (local storage only, skips cloud)."""
    svc = PhotoUploadService()
    # Wrap ingest to skip cloud
    orig_ingest = svc.ingest_single_photo

    async def _test_ingest(*args, **kwargs):
        kwargs["save_to_cloud"] = False
        return await orig_ingest(*args, **kwargs)

    svc.ingest_single_photo = _test_ingest
    return svc


def mock_get_search_service():
    """Test ImageSearchService provider."""
    return ImageSearchService(ai=None)


@pytest.fixture
def mock_app():
    """FastAPI app instance with mocked dependencies."""
    app.dependency_overrides[get_verified_keys] = mock_get_verified_keys
    app.dependency_overrides[get_upload_service] = mock_get_upload_service
    app.dependency_overrides[get_search_service] = mock_get_search_service
    app.dependency_overrides[require_current_user] = mock_require_current_user
    yield app
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(mock_app) -> AsyncGenerator[AsyncClient, None]:
    """Asynchronous HTTP test client bound to FastAPI application."""
    transport = ASGITransport(app=mock_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
