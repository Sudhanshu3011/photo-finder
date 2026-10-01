"""
tests/integration/test_api_upload.py — Integration tests for image upload and indexing endpoint.
Tests multipart file uploads with form metadata, dependency overrides, and error edge cases.
"""
import io
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_upload_images_sync_success(client: AsyncClient):
    """
    Test uploading multiple mock files with metadata.
    Uses MockUploadService via FastAPI dependency injection.
    """
    mock_file1 = ("test1.jpg", io.BytesIO(b"dummy image 1 bytes"), "image/jpeg")
    mock_file2 = ("test2.png", io.BytesIO(b"dummy image 2 bytes"), "image/png")

    files = [
        ("files", mock_file1),
        ("files", mock_file2),
    ]
    data = {
        "folder_name": "vacation_photos",
        "detect_faces": "true",
        "user_id": "test_user_1",
    }

    response = await client.post("/api/upload", files=files, data=data)
    assert response.status_code == 200

    body = response.json()
    assert body["message"] == "Done!"
    assert len(body["urls"]) == 2
    assert body["summary"]["files"] == 2
    assert body["summary"]["face_vectors"] == 2


@pytest.mark.asyncio
async def test_upload_images_async_mode(client: AsyncClient):
    """Test async upload enqueue mode."""
    mock_file = ("async_test.jpg", io.BytesIO(b"async dummy bytes"), "image/jpeg")
    files = [("files", mock_file)]
    data = {
        "folder_name": "background_batch",
        "detect_faces": "false",
    }

    response = await client.post("/api/upload?async=true", files=files, data=data)
    assert response.status_code == 200

    body = response.json()
    assert body["message"] == "Upload queued"
    assert "job_id" in body
    assert body["total_files"] == 1


@pytest.mark.asyncio
async def test_upload_missing_folder_name_fails(client: AsyncClient):
    """Test that missing required folder_name returns 422 Unprocessable Entity."""
    mock_file = ("test.jpg", io.BytesIO(b"dummy bytes"), "image/jpeg")
    files = [("files", mock_file)]

    response = await client.post("/api/upload", files=files, data={})
    assert response.status_code == 422
