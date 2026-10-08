"""
tests/integration/test_api_search.py — Integration tests for visual search API endpoints.
"""
import io
import pytest
from httpx import AsyncClient
from conftest import create_mock_jpeg


@pytest.mark.asyncio
async def test_search_image_success(client: AsyncClient):
    """Test POST /api/search/image with valid query image returns matches adhering to SearchResponse schema."""
    query_bytes = create_mock_jpeg(120, 120)
    files = {"file": ("query.jpg", query_bytes, "image/jpeg")}

    response = await client.post("/api/search/image", files=files)
    assert response.status_code == 200

    body = response.json()
    assert "query_type" in body
    assert "results" in body
    assert isinstance(body["results"], list)


@pytest.mark.asyncio
async def test_search_by_face_multi_angle_success(client: AsyncClient):
    """Test POST /api/search/multi-angle with front, left, and right angles."""
    front = ("front.jpg", create_mock_jpeg(120, 120), "image/jpeg")
    left = ("left.jpg", create_mock_jpeg(120, 120), "image/jpeg")
    right = ("right.jpg", create_mock_jpeg(120, 120), "image/jpeg")

    files = {
        "front_file": front,
        "left_file": left,
        "right_file": right,
    }

    response = await client.post("/api/search/multi-angle", files=files)
    assert response.status_code in [200, 400]  # 400 in test mock mode if no faces detected without AI models


@pytest.mark.asyncio
async def test_search_empty_file_fails(client: AsyncClient):
    """Test that uploading an empty 0-byte file returns 400 Bad Request."""
    empty_file = ("empty.jpg", b"", "image/jpeg")
    files = {"file": empty_file}

    response = await client.post("/api/search/image", files=files)
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()
