"""
src/api/system_routes.py — System Health, Developer S3 Diagnostics, and Telemetry Ingestion.
"""
import time
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, status

from src.core.logging import log
from src.core.config import AWS_REGION
from src.schemas.upload_schemas import (
    ClientLogEventRequest,
    ClientLogEventResponse,
    S3HealthResponse,
)
from src.modules.storage.s3_storage import get_s3_bucket, ping_s3

router = APIRouter(tags=["System & Health"])


@router.get("/api/health", status_code=status.HTTP_200_OK, summary="API health check")
def health_check():
    """System liveness and readiness probe."""
    return {
        "status": "ok",
        "app": "Visual Search API",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/health/s3", response_model=S3HealthResponse, status_code=status.HTTP_200_OK, summary="Developer AWS S3 Health Check")
def s3_health_check():
    """
    Probes AWS S3 bucket connectivity, permissions, and network latency.
    Provides diagnostic status on whether AWS S3 is active or local storage fallback is engaged.
    """
    bucket = get_s3_bucket()
    t0 = time.perf_counter()
    err_detail = None
    is_ok = False
    try:
        is_ok = ping_s3(bucket=bucket)
    except Exception as exc:
        err_detail = str(exc)
        is_ok = False

    latency = round((time.perf_counter() - t0) * 1000, 2)

    if is_ok:
        return S3HealthResponse(
            status="healthy",
            storage="aws_s3",
            bucket=bucket,
            region=AWS_REGION,
            accessible=True,
            latency_ms=latency,
            error=None,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    return S3HealthResponse(
        status="degraded",
        storage="local_fallback_active",
        bucket=bucket,
        region=AWS_REGION,
        accessible=False,
        latency_ms=latency,
        error=err_detail or "Unable to access S3 bucket (check credentials or network)",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/api/log", response_model=ClientLogEventResponse, status_code=status.HTTP_200_OK, summary="Frontend telemetry ingestion")
async def log_client_event(req: ClientLogEventRequest):
    """Captures client telemetry events with strict schema validation and 16 KB size cap."""
    log(req.level, f"client.{req.event}", payload=req.payload)
    return ClientLogEventResponse(success=True, message="Event logged successfully")
