"""
tests/integration/test_api_search.py — Integration tests for visual search API endpoints.
Tests multimodal image query and multi-angle face search with mocked vector search.
"""
import io
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_search_image_success(client: AsyncClient):
    """Test POST /api/search with valid query image returns matches adhering to SearchResponse schema."""
    mock_query = ("query.jpg", io.BytesIO(b"fake query image bytes"), "image/jpeg")
    files = {"file": mock_query}
    data = {"detect_faces": "true", "user_id": "search_user_1"}

    response = await client.post("/api/search", files=files, data=data)
    assert response.status_code == 200

    body = response.json()
    assert body["mode"] == "face"
    assert len(body["face_groups"]) == 1
    assert len(body["results"]) == 1
    assert body["results"][0]["id"] == "match_vec_1"
    assert body["results"][0]["score"] == 0.94


@pytest.mark.asyncio
async def test_search_by_face_multi_angle_success(client: AsyncClient):
    """Test POST /api/search-by-face with front, left, and right angles."""
    front = ("front.jpg", io.BytesIO(b"fake front bytes"), "image/jpeg")
    left = ("left.jpg", io.BytesIO(b"fake left bytes"), "image/jpeg")
    right = ("right.jpg", io.BytesIO(b"fake right bytes"), "image/jpeg")

    files = {
        "front": front,
        "left": left,
        "right": right,
    }

    response = await client.post("/api/search-by-face", files=files, data={})
    assert response.status_code == 200

    body = response.json()
    assert body["mode"] == "face"
    assert len(body["results"]) == 1
    assert body["results"][0]["id"] == "fused_match_1"
    assert body["results"][0]["score"] == 0.98


@pytest.mark.asyncio
async def test_search_empty_file_fails(client: AsyncClient):
    """Test that uploading an empty 0-byte file returns 400 Bad Request."""
    empty_file = ("empty.jpg", io.BytesIO(b""), "image/jpeg")
    files = {"file": empty_file}

    response = await client.post("/api/search", files=files)
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()
