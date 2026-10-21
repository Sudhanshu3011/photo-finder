"""
tests/integration/test_mvc_services_and_api.py — End-to-end integration tests
for the clean MVC architecture and 4 explicit services:
1. User Authentication & Authorization Service (/api/auth)
2. Photo Upload Service (/api/upload)
3. Image Processing & Clustering Service (/api/process)
4. Image Search Service (/api/search)
"""
import io
import pytest
from PIL import Image
from httpx import AsyncClient


def create_mock_jpeg(width: int = 120, height: int = 120) -> bytes:
    """Generate valid in-memory JPEG bytes for upload testing."""
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_auth_service_lifecycle(client: AsyncClient):
    """Test user registration, login, JWT token issuance, and authenticated profile retrieval."""
    import uuid
    suffix = uuid.uuid4().hex[:6]
    test_username = f"user_{suffix}"
    test_email = f"user_{suffix}@example.com"

    # 1. Register new tenant organization & owner
    register_payload = {
        "username": test_username,
        "email": test_email,
        "password": "securepassword123",
        "organization_name": f"{test_username} Studio",
    }
    reg_resp = await client.post("/api/auth/register-tenant", json=register_payload)
    assert reg_resp.status_code == 201
    reg_data = reg_resp.json()
    assert "access_token" in reg_data
    assert reg_data["username"] == test_username
    token = reg_data["access_token"]

    # 2. Login with credentials
    login_resp = await client.post(
        "/api/auth/login",
        json={"email": test_email, "password": "securepassword123"}
    )
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert login_data["access_token"] is not None

    # 4. Get current user profile with JWT
    headers = {"Authorization": f"Bearer {token}"}
    me_resp = await client.get("/api/auth/me", headers=headers)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["username"] == test_username
    assert me_data["email"] == test_email
    assert me_data["role"] == "owner"

    # 5. Accessing /me without token fails with 401
    unauth_resp = await client.get("/api/auth/me")
    assert unauth_resp.status_code == 401


@pytest.mark.asyncio
async def test_photo_upload_service(client: AsyncClient):
    """Test single photo ingestion, validation, and batch upload tracking."""
    # 1. Upload valid single photo
    img_bytes = create_mock_jpeg(150, 150)
    files = {"file": ("portrait.jpg", img_bytes, "image/jpeg")}
    up_resp = await client.post("/api/upload/photo", files=files)
    assert up_resp.status_code == 201
    up_data = up_resp.json()
    assert up_data["status"] == "success"
    assert up_data["data"]["image_id"].startswith("img_")
    assert up_data["data"]["width"] == 150
    assert up_data["data"]["height"] == 150

    # 3. Empty file should fail with 400
    empty_files = {"file": ("empty.jpg", b"", "image/jpeg")}
    empty_resp = await client.post("/api/upload/photo", files=empty_files)
    assert empty_resp.status_code == 400

    # 4. Batch photo upload
    batch_files = [
        ("files", ("pic1.jpg", create_mock_jpeg(100, 100), "image/jpeg")),
        ("files", ("pic2.jpg", create_mock_jpeg(100, 100), "image/jpeg")),
    ]
    batch_resp = await client.post("/api/upload/batch", files=batch_files)
    assert batch_resp.status_code == 201
    b_data = batch_resp.json()
    assert b_data["total"] == 2
    assert b_data["successful"] == 2
    assert "job_id" in b_data


@pytest.mark.asyncio
async def test_image_processing_and_clustering(client: AsyncClient):
    # 1. Trigger clustering without 25 photos -> 422 Unprocessable Entity
    rej_resp = await client.post("/api/clusters/generate?folder_name=general&min_cluster_size=2")
    assert rej_resp.status_code == 422

    # 2. Trigger clustering with admin force=true -> 200 OK
    cluster_resp = await client.post("/api/clusters/generate?folder_name=general&min_cluster_size=2&force=true")
    assert cluster_resp.status_code == 200
    assert "status" in cluster_resp.json()

    # 2. Get clusters list
    list_resp = await client.get("/api/clusters")
    assert list_resp.status_code == 200
    assert isinstance(list_resp.json(), list)


@pytest.mark.asyncio
async def test_image_search_service(client: AsyncClient):
    """Test search endpoint query input parsing and response format."""
    query_bytes = create_mock_jpeg(120, 120)
    files = {"file": ("query.jpg", query_bytes, "image/jpeg")}
    
    data = {"folder_name": "general"}
    search_resp = await client.post("/api/search/image?top_k=10", files=files, data=data)
    assert search_resp.status_code == 200
    s_data = search_resp.json()
    assert "query_type" in s_data
    assert "results" in s_data
    assert isinstance(s_data["results"], list)


@pytest.mark.asyncio
async def test_storage_config_and_folder_scoping(client: AsyncClient):
    """Test object storage configuration, folder-targeted upload, and folder-scoped search."""
    # 1. Check current S3 health
    cfg_resp = await client.get("/api/health/s3")
    assert cfg_resp.status_code == 200
    assert "status" in cfg_resp.json()
    assert "storage" in cfg_resp.json()

    # 2. Upload photo with explicit folder_name
    img_bytes = create_mock_jpeg(140, 140)
    files = {"file": ("wedding_photo.jpg", img_bytes, "image/jpeg")}
    data = {"folder_name": "wedding_2026"}
    up_resp = await client.post("/api/upload/photo", files=files, data=data)
    assert up_resp.status_code == 201
    item = up_resp.json()["data"]
    assert item["folder"] == "wedding_2026"

    # 3. Search with folder scoping (unindexed folder returns 404)
    search_files = {"file": ("query.jpg", img_bytes, "image/jpeg")}
    search_resp = await client.post("/api/search/image?top_k=5", files=search_files, data={"folder_name": "wedding_2026"})
    assert search_resp.status_code in [200, 404]
    if search_resp.status_code == 200:
        assert "results" in search_resp.json()

    # 4. RESTful clusters routes with folder scoping (using admin force=true)
    c_gen = await client.post("/api/clusters/generate?min_cluster_size=2&folder_name=wedding_2026&force=true")
    assert c_gen.status_code == 200
    c_list = await client.get("/api/clusters?folder_name=wedding_2026")
    assert c_list.status_code == 200
    assert isinstance(c_list.json(), list)


@pytest.mark.asyncio
async def test_process_image_by_id_direct_s3_retrieval(client: AsyncClient):
    """Test process_image_by_id fetches directly from S3 bucket without local disk check."""
    from unittest.mock import patch
    from src.services.image_processing_service import ImageProcessingService

    service = ImageProcessingService()
    test_img_bytes = create_mock_jpeg(100, 100)

    # 1. Success case: image fetched directly from S3
    with patch("src.services.image_processing_service.download_image_from_s3", return_value=test_img_bytes) as mock_s3:
        res = service.process_image_by_id("img_s3_direct_test", tenant_id="test_tenant")
        assert res["image_id"] == "img_s3_direct_test"
        assert res["status"] == "success"
        mock_s3.assert_called_once_with("test_tenant/general/img_s3_direct_test.jpg")

    # 2. Failure case: image missing in S3 returns failure status
    with patch("src.services.image_processing_service.download_image_from_s3", side_effect=FileNotFoundError("Not found")):
        res_fail = service.process_image_by_id("img_s3_missing", tenant_id="test_tenant")
        assert res_fail["status"] == "failed"
        assert "could not be retrieved from S3" in res_fail["message"]


