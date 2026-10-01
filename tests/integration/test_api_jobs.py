"""
tests/integration/test_api_jobs.py — Integration tests for job status polling and real-time execution logs.
"""
import pytest
from httpx import AsyncClient

from src.services.jobs import create_job, update_job_progress, append_job_log, complete_job


@pytest.mark.asyncio
async def test_job_polling_with_real_time_logs(client: AsyncClient):
    """Verify that polling a job returns progress, status, and real-time logs."""
    job_id = await create_job(
        user_id="test_user_logs",
        folder="vacation",
        total_files=5,
        job_payload={"files": 5},
    )

    # 1. Check initial queued state
    res = await client.get(f"/api/jobs/{job_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["job_id"] == job_id
    assert data["status"] == "pending"
    assert len(data["logs"]) >= 1
    assert "Job queued" in data["logs"][0]

    # 2. Append processing progress and log
    await update_job_progress(
        job_id,
        processed=2,
        total=5,
        stage="processing",
        log_msg="Processed 2 of 5 files successfully",
    )

    res2 = await client.get(f"/api/jobs/{job_id}")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "processing"
    assert data2["processed_files"] == 2
    assert data2["current_stage"] == "processing"
    assert any("Processed 2 of 5" in log_entry for log_entry in data2["logs"])

    # 3. Complete the job
    await complete_job(job_id, {"files": 5, "urls": ["http://img1.jpg"]})
    res3 = await client.get(f"/api/jobs/{job_id}")
    assert res3.status_code == 200
    data3 = res3.json()
    assert data3["status"] == "completed"
    assert data3["processed_files"] == 5
    assert any("completed" in log_entry.lower() for log_entry in data3["logs"])
