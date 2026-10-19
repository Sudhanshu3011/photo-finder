"""
tests/unit/test_schemas.py — Unit tests for modern Pydantic V2 schemas.
Verifies validation rules, defaults, and serializations for the modular schema architecture.
"""
import pytest
from pydantic import ValidationError

from src.schemas.auth_schemas import (
    RegisterTenantRequest,
    AcceptInviteRequest,
    InvitePreviewResponse,
    LoginRequest,
    TokenResponse,
    UserProfileResponse,
    TenantRole,
)
from src.schemas.upload_schemas import PhotoUploadItem, PhotoUploadResponse, BatchUploadResponse
from src.schemas.processing_schemas import JobProgressResponse, FaceClusterResponse, ClusterRenameRequest
from src.schemas.search_schemas import MatchItem, SearchResponse


def test_auth_schemas_validation():
    # Valid register tenant request
    reg = RegisterTenantRequest(
        username="testuser",
        email="test@example.com",
        password="securepassword123",
        organization_name="Acme Studio",
    )
    assert reg.username == "testuser"
    assert reg.email == "test@example.com"
    assert reg.organization_name == "Acme Studio"
    assert reg.ignore_pending_invite is False

    # Valid accept invite request
    acc = AcceptInviteRequest(
        invite_token="inv_1234567890abcdef",
        username="invitee_user",
        password="securepassword123",
    )
    assert acc.username == "invitee_user"
    assert acc.invite_token == "inv_1234567890abcdef"

    # Missing required password
    with pytest.raises(ValidationError):
        RegisterTenantRequest(username="testuser", email="test@example.com", organization_name="Acme Studio")


def test_upload_schemas():
    item = PhotoUploadItem(
        image_id="img_100",
        filename="photo.jpg",
        status="uploaded",
        cloud_url="https://s3.amazonaws.com/test-bucket/test.jpg"
    )
    resp = PhotoUploadResponse(status="success", data=item)
    assert resp.status == "success"
    assert resp.data.image_id == "img_100"

    batch = BatchUploadResponse(
        job_id="job_123",
        total=1,
        successful=1,
        failed=0,
        items=[item]
    )
    assert batch.total == 1
    assert len(batch.items) == 1


def test_processing_schemas():
    job = JobProgressResponse(
        job_id="job_999",
        status="processing",
        total_images=5,
        processed_images=2,
    )
    assert job.job_id == "job_999"
    assert job.total_images == 5
    assert job.processed_images == 2

    rename = ClusterRenameRequest(person_name="Alice")
    assert rename.person_name == "Alice"

    with pytest.raises(ValidationError):
        ClusterRenameRequest()  # person_name required


def test_search_schemas():
    item = MatchItem(
        image_id="img_1",
        score=0.92,
        person_name="Bob",
        cluster_id="cluster_1"
    )
    assert item.score == 0.92
    assert item.person_name == "Bob"

    search_resp = SearchResponse(
        query_type="face",
        total_matches=1,
        results=[item]
    )
    assert search_resp.query_type == "face"
    assert len(search_resp.results) == 1


def test_cluster_status_and_health_schemas():
    from src.schemas.processing_schemas import ClusterStatusResponse
    from src.schemas.upload_schemas import ClientLogEventRequest, S3HealthResponse

    # ClusterStatusResponse
    csr = ClusterStatusResponse(
        folder_name="vacation",
        total_photos=30,
        last_clustered_count=0,
        new_photos_since_last_cluster=30,
        ready_for_clustering=True,
    )
    assert csr.folder_name == "vacation"
    assert csr.ready_for_clustering is True
    assert csr.threshold == 25

    # S3HealthResponse
    s3h = S3HealthResponse(
        status="healthy",
        storage="aws_s3",
        bucket="my-bucket",
        region="ap-south-1",
        accessible=True,
        latency_ms=12.5,
        timestamp="2026-10-16T10:00:00Z",
    )
    assert s3h.status == "healthy"
    assert s3h.accessible is True

    # ClientLogEventRequest valid
    log_req = ClientLogEventRequest(event="user.clicked_upload", level="INFO", payload={"count": 5})
    assert log_req.event == "user.clicked_upload"

