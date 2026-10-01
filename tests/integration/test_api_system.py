"""
tests/integration/test_api_system.py — Integration tests for system health and frontend telemetry.
Tests receiving JSON body data from frontend applications.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Test health endpoint returns 200 OK and valid ISO timestamp."""
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_frontend_log_json_body(client: AsyncClient):
    """
    Test frontend telemetry API accepts JSON body payloads.
    Verifies frontend can send structured JSON objects.
    """
    payload = {
        "event": "filter_applied",
        "user_id": "test_user_99",
        "page": "/explorer",
        "metadata": {
            "category": "nature",
            "threshold": 0.75,
            "viewport": "1920x1080",
        },
    }

    response = await client.post("/api/log", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Event logged successfully"


@pytest.mark.asyncio
async def test_frontend_log_missing_event_fails(client: AsyncClient):
    """Test validation failure (422) when required fields are missing."""
    invalid_payload = {
        "user_id": "missing_event_user",
        "page": "/home",
    }
    response = await client.post("/api/log", json=invalid_payload)
    assert response.status_code == 422
