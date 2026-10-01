"""
src/api/jobs.py — Async upload job status and real-time execution logs endpoint.
GET /api/jobs/{job_id} → poll job status, stage, progress, and real-time execution logs.
"""
from fastapi import APIRouter, HTTPException, Request, status

from src.core.logging import log
from src.services.jobs import get_job_status
from src.common.utils import get_ip
from src.schemas.jobs import JobStatusResponse

router = APIRouter()


@router.get(
    "/api/jobs/{job_id}",
    response_model=JobStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Poll upload job status and execution logs",
    description="Returns current progress, status ('pending', 'processing', 'completed', 'failed'), real-time logs, and results.",
)
async def poll_job(
    job_id: str,
    request: Request,
):
    ip = get_ip(request)

    job = await get_job_status(job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job {job_id} not found")

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
        "current_stage": job.get("current_stage", ""),
        "logs": job.get("logs", []),
    }

    if job.get("status") == "completed":
        response["result"] = job.get("result", {})

    if job.get("status") == "failed":
        response["error"] = job.get("error", "unknown error")

    log("INFO", "jobs.poll", ip=ip, job_id=job_id, status=response["status"], progress=f"{processed}/{total}")
    return response