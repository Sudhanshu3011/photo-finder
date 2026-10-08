"""
tests/integration/test_api_upload.py — Integration tests for image upload and ingestion endpoint.
"""
import io
import pytest
from httpx import AsyncClient
from conftest import create_mock_jpeg


@pytest.mark.asyncio
async def test_upload_images_sync_success(client: AsyncClient):
    """Test uploading single image via clean /api/upload/photo endpoint."""
    img_bytes = create_mock_jpeg(120, 120)
    files = {"file": ("test1.jpg", img_bytes, "image/jpeg")}

    response = await client.post("/api/upload/photo", files=files)
    assert response.status_code == 201

    body = response.json()
    assert body["status"] == "success"
    assert "image_id" in body["data"]
    assert body["data"]["width"] == 120
    assert body["data"]["height"] == 120


@pytest.mark.asyncio
async def test_upload_images_batch_mode(client: AsyncClient):
    """Test batch upload via clean /api/upload/batch endpoint."""
    batch_files = [
        ("files", ("pic1.jpg", create_mock_jpeg(100, 100), "image/jpeg")),
        ("files", ("pic2.jpg", create_mock_jpeg(100, 100), "image/jpeg")),
    ]

    response = await client.post("/api/upload/batch", files=batch_files)
    assert response.status_code == 201

    body = response.json()
    assert body["total"] == 2
    assert body["successful"] == 2
    assert "job_id" in body


@pytest.mark.asyncio
async def test_upload_empty_file_fails(client: AsyncClient):
    """Test that uploading an empty 0-byte file returns 400 Bad Request."""
    files = {"file": ("empty.jpg", b"", "image/jpeg")}

    response = await client.post("/api/upload/photo", files=files)
    assert response.status_code == 400
