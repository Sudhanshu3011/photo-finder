"""
src/api/jobs.py — Phase 3: Async upload job status endpoints

GET /api/jobs/{job_id}   → poll job status + progress

This is the API router. The job queue worker lives in src/services/jobs.py.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from src.core.security import get_verified_keys
from src.core.logging import log
from src.services.jobs import get_job_status
from src.common.utils import get_ip

router = APIRouter()


@router.get("/api/jobs/{job_id}")
async def poll_job(
    job_id: str,
    request: Request,
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)

    job = await get_job_status(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")

    total = job.get("total_files", 0)
    processed = job.get("processed_files", 0)
    pct = round(processed / total * 100) if total else 0

    response = {
        "job_id": job_id,
        "status": job.get("status", "unknown"),
        "total_files": total,
        "processed_files": processed,
        "progress_pct": pct,
        "status_url": f"/api/jobs/{job_id}",
    }

    if job.get("status") == "completed":
        response["result"] = job.get("result", {})

    if job.get("status") == "failed":
        response["error"] = job.get("error", "unknown error")

    log("INFO", "jobs.poll", ip=ip, job_id=job_id, status=response["status"])
    return response