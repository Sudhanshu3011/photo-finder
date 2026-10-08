import os
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from fastapi import APIRouter, Body, Request, status

from src.core.logging import log

router = APIRouter(tags=["System & Health"])


@router.get("/", include_in_schema=False)
@router.get("/api/health", summary="API health check")
def health_check():
    """System liveness and readiness probe."""
    return {
        "status": "ok",
        "app": "Visual Search API",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/api/log", status_code=status.HTTP_200_OK, summary="Frontend telemetry ingestion")
async def log_client_event(request: Request, payload: Dict[str, Any] = Body(...)):
    """Captures client telemetry events and errors."""
    event = payload.get("event")
    if not event:
        from fastapi import HTTPException
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Event name is required")

    log("INFO", f"client.{event}", payload=payload)
    return {"success": True, "message": "Event logged successfully"}

