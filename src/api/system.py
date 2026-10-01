"""
src/api/system.py — System health, telemetry logging, and storage verification endpoints.
Zero Pinecone dependency: validates Cloudinary and local FAISS vector stores.
"""
import asyncio
import time
from datetime import datetime, timezone
from typing import Optional, Union

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request, status

from src.core.security import get_verified_keys, get_user_id
from src.core.logging import log
from src.common.utils import get_ip
from src.schemas.common import BaseResponse
from src.schemas.system import HealthResponse, FrontendLogRequest
from src.services.cloudinary_service import cld_ping
from src.services.faiss_service import faiss_store

router = APIRouter()


@router.get("/", summary="Root health ping")
async def root():
    return {"status": "ok"}


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health check",
    description="Returns API service health, vector backend, and UTC server timestamp.",
)
async def health():
    return HealthResponse(
        status="ok",
        version="5.0.0-faiss",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.post(
    "/api/log",
    response_model=BaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Frontend telemetry ingestion",
    description="Captures user actions, client timings, and client errors from the frontend.",
)
async def log_frontend_event(
    request: Request,
    payload: Optional[FrontendLogRequest] = Body(None),
    user_id: str = Depends(get_user_id),
):
    ip = get_ip(request)
    if payload:
        event = payload.event
        level = payload.level
        data = payload.data
    else:
        try:
            body = await request.json()
            event = body.get("event", "unknown")
            level = body.get("level", "INFO")
            data = body.get("data", {})
        except Exception:
            event = "unknown"
            level = "INFO"
            data = {}

    log(
        level,
        f"frontend.{event}",
        user_id=user_id,
        ip=ip,
        data=data,
    )
    return BaseResponse(success=True, message="Event logged successfully")


@router.post(
    "/api/verify-keys",
    status_code=status.HTTP_200_OK,
    summary="Verify storage and vector DB credentials",
    description="Pings Cloudinary and initializes local FAISS vector indexes.",
)
async def verify_keys(
    request: Request,
    user_id: str = Depends(get_user_id),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    start = time.perf_counter()
    log("INFO", "settings.verify_keys.start", user_id=user_id, ip=ip)

    try:
        await asyncio.to_thread(cld_ping, keys["cloudinary_creds"])
    except Exception as e:
        log("ERROR", "settings.verify_keys.cloudinary_fail", user_id=user_id, ip=ip, error=str(e))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Cloudinary Environment URL.")

    indexes_ready: list[str] = []
    try:
        indexes_ready = list(faiss_store.DIMENSIONS.keys())
        for idx_name in indexes_ready:
            faiss_store.get_index(idx_name)
    except Exception as e:
        log("ERROR", "settings.verify_keys.faiss_fail", user_id=user_id, ip=ip, error=str(e))
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"FAISS Vector Store Error: {e}")

    duration_ms = round((time.perf_counter() - start) * 1000)
    log("INFO", "settings.verify_keys.success", user_id=user_id, ip=ip,
        indexes_ready=indexes_ready, duration_ms=duration_ms)
    return {
        "message": "Storage and FAISS vector indexes ready!",
        "valid": True,
        "indexes": indexes_ready,
        "vector_backend": "FAISS (Local In-Process)",
        "duration_ms": duration_ms,
        "user_id": user_id,
    }
