"""
tests/unit/test_schemas.py — Unit tests for Pydantic V2 schemas.
Verifies input validation, error handling, and payload schemas.
"""
import pytest
from pydantic import ValidationError

from src.schemas.common import BaseResponse, ErrorResponse, PaginationParams
from src.schemas.upload import UploadMetadata, UploadResponse, UploadVectorSummary
from src.schemas.system import FrontendLogRequest, HealthResponse
from src.schemas.jobs import JobStatusResponse


def test_base_response():
    resp = BaseResponse(success=True, message="Test OK")
    assert resp.success is True
    assert resp.message == "Test OK"


def test_upload_vector_summary_validation():
    summary = UploadVectorSummary(
        files=3,
        face_vectors=5,
        adaface_vectors=5,
        object_vectors=3,
        index_mode="split",
    )
    assert summary.files == 3
    assert summary.face_vectors == 5

    # Should raise error if negative
    with pytest.raises(ValidationError):
        UploadVectorSummary(files=-1)


def test_frontend_log_request():
    payload = FrontendLogRequest(
        event="user_search_clicked",
        user_id="user_42",
        page="/gallery",
        metadata={"query": "beach", "results_count": 12},
    )
    assert payload.event == "user_search_clicked"
    assert payload.metadata["results_count"] == 12

    # Event is required
    with pytest.raises(ValidationError):
        FrontendLogRequest()


def test_job_status_response():
    job = JobStatusResponse(
        job_id="job_abc123",
        status="completed",
        total_files=10,
        processed_files=10,
        progress_pct=100,
        status_url="/api/jobs/job_abc123",
    )
    assert job.status == "completed"
    assert job.progress_pct == 100
