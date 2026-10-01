"""
tests/conftest.py — Pytest fixtures and mock providers for testing Visual Search API.
Enables fast, isolated testing without downloading or loading 3GB+ ML models.
"""
import os
os.environ["TESTING"] = "true"
from typing import AsyncGenerator
import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from src.core.security import get_verified_keys
from src.api.dependencies import get_upload_service, get_search_service
from src.services.upload_service import UploadService
from src.services.search_service import SearchService


class MockUploadService(UploadService):
    """Mock upload service returning deterministic test data."""

    def __init__(self):
        super().__init__(ai=None, ai_semaphore=None, pc_pool=None)

    async def ensure_db_indexes(self, pc) -> bool:
        return False

    async def process_sync(
        self,
        *,
        file_bytes_list,
        filenames,
        folder,
        detect_faces,
        user_id,
        keys,
        ip="127.0.0.1",
    ) -> dict:
        return {
            "message": "Done!",
            "urls": [f"https://res.cloudinary.com/demo/image/upload/{fn}" for fn in filenames],
            "summary": {
                "files": len(file_bytes_list),
                "face_vectors": 2 if detect_faces else 0,
                "adaface_vectors": 2 if detect_faces else 0,
                "object_vectors": 1,
                "index_mode": "split",
            },
        }

    async def enqueue_async(
        self,
        *,
        file_bytes_list,
        filenames,
        folder,
        detect_faces,
        user_id,
        keys,
        ip="127.0.0.1",
    ) -> dict:
        return {
            "message": "Upload queued",
            "job_id": "test_job_12345",
            "status_url": "/api/jobs/test_job_12345",
            "total_files": len(file_bytes_list),
        }


class MockSearchService(SearchService):
    """Mock search service returning deterministic match results."""

    def __init__(self):
        super().__init__(ai=None, ai_semaphore=None, pc_pool=None)

    async def search_image(
        self,
        *,
        file_bytes,
        filename,
        detect_faces,
        user_id,
        keys,
        ip="127.0.0.1",
    ) -> dict:
        return {
            "mode": "face" if detect_faces else "object",
            "face_groups": [
                {
                    "face_idx": 0,
                    "query_crop": "data:image/jpeg;base64,mockcrop",
                    "matches": [
                        {
                            "id": "match_vec_1",
                            "score": 0.94,
                            "url": "https://res.cloudinary.com/demo/image/upload/match1.jpg",
                            "folder": "wedding",
                            "metadata": {},
                        }
                    ],
                }
            ] if detect_faces else [],
            "results": [
                {
                    "id": "match_vec_1",
                    "score": 0.94,
                    "url": "https://res.cloudinary.com/demo/image/upload/match1.jpg",
                    "folder": "wedding",
                    "metadata": {},
                }
            ] if detect_faces else [],
            "object_results": [],
        }

    async def search_by_face_multi_angle(
        self,
        *,
        images_bytes,
        user_id,
        keys,
        ip="127.0.0.1",
    ) -> dict:
        return {
            "mode": "face",
            "face_groups": [],
            "results": [
                {
                    "id": "fused_match_1",
                    "score": 0.98,
                    "url": "https://res.cloudinary.com/demo/image/upload/fused1.jpg",
                    "folder": "family",
                    "metadata": {},
                }
            ],
            "object_results": [],
        }


async def mock_get_verified_keys():
    """Mock credentials provider for tests."""
    return {
        "cloudinary_url": "cloudinary://123:abc@test",
        "cloudinary_creds": {"cloud_name": "test", "api_key": "123", "api_secret": "abc"},
        "pinecone_key": "local-faiss",
    }


def mock_get_upload_service():
    """Mock UploadService factory."""
    return MockUploadService()


def mock_get_search_service():
    """Mock SearchService factory."""
    return MockSearchService()


@pytest.fixture
def mock_app():
    """FastAPI app instance with mocked dependencies."""
    app.dependency_overrides[get_verified_keys] = mock_get_verified_keys
    app.dependency_overrides[get_upload_service] = mock_get_upload_service
    app.dependency_overrides[get_search_service] = mock_get_search_service
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
async def client(mock_app) -> AsyncGenerator[AsyncClient, None]:
    """Asynchronous HTTP test client bound to mocked FastAPI application."""
    transport = ASGITransport(app=mock_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
