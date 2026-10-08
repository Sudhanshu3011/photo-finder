"""
tests/unit/test_schemas.py — Unit tests for modern Pydantic V2 schemas.
Verifies validation rules, defaults, and serializations for the modular schema architecture.
"""
import pytest
from pydantic import ValidationError

from src.schemas.auth_schemas import RegisterRequest, LoginRequest, TokenResponse, UserProfileResponse
from src.schemas.upload_schemas import PhotoUploadItem, PhotoUploadResponse, BatchUploadResponse
from src.schemas.processing_schemas import JobProgressResponse, FaceClusterResponse, ClusterRenameRequest
from src.schemas.search_schemas import MatchItem, SearchResponse


def test_auth_schemas_validation():
    # Valid register request
    reg = RegisterRequest(username="testuser", email="test@example.com", password="securepassword")
    assert reg.username == "testuser"
    assert reg.email == "test@example.com"
    assert reg.password == "securepassword"
    assert reg.role == "user"

    # Missing required password
    with pytest.raises(ValidationError):
        RegisterRequest(username="testuser", email="test@example.com")


def test_upload_schemas():
    item = PhotoUploadItem(
        image_id="img_100",
        filename="photo.jpg",
        status="uploaded",
        cloud_url="https://cloudinary.com/test.jpg"
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
