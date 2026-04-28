import asyncio
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Form, HTTPException, Request, Depends

from src.core.config import DEFAULT_PINECONE_KEY
from src.core.security import get_verified_keys
from src.services.db_client import cld_ping, ensure_indexes, pinecone_pool
from src.core.logging import log
from src.common.utils import get_ip, is_default_key

router = APIRouter()

@router.get("/")
async def root():
    return {"status": "ok"}

@router.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

@router.post("/api/log")
async def frontend_log(
    request:  Request,
    event:    str = Form(...),
    user_id:  str = Form(""),
    page:     str = Form(""),
    metadata: str = Form("{}"),
):
    import json
    ip = get_ip(request)
    try:
        meta = json.loads(metadata) if metadata else {}
    except Exception:
        meta = {}
    log(
        "INFO", f"frontend.{event}",
        user_id=user_id or "anonymous",
        page=page, ip=ip,
        ua=request.headers.get("User-Agent", "")[:120],
        **meta,
    )
    return {"ok": True}

@router.post("/api/verify-keys")
async def verify_keys(
    request: Request,
    user_id: str = Form(""),
    keys: dict = Depends(get_verified_keys)
):
    ip    = get_ip(request)
    mode  = "guest" if is_default_key(keys["pinecone_key"], DEFAULT_PINECONE_KEY) else "personal"
    start = time.perf_counter()
    log("INFO", "settings.verify_keys.start", user_id=user_id or "anonymous", mode=mode, ip=ip)

    try:
        await asyncio.to_thread(cld_ping, keys["cloudinary_creds"])
    except Exception as e:
        log("ERROR", "settings.verify_keys.cloudinary_fail", user_id=user_id or "anonymous", ip=ip, error=str(e))
        raise HTTPException(400, "Invalid Cloudinary Environment URL.")

    indexes_created: list[str] = []
    try:
        pc = pinecone_pool.get(keys["pinecone_key"])
        indexes_created = await asyncio.to_thread(ensure_indexes, pc)
    except Exception as e:
        err = str(e)
        clean = "Invalid Pinecone API Key." if "401" in err or "unauthorized" in err.lower() else f"Pinecone Error: {err}"
        log("ERROR", "settings.verify_keys.pinecone_fail", user_id=user_id or "anonymous", ip=ip, error=clean)
        raise HTTPException(400, clean)

    log("INFO", "settings.verify_keys.success", user_id=user_id or "anonymous", mode=mode, ip=ip,
        indexes_created=indexes_created, duration_ms=round((time.perf_counter() - start) * 1000))
    return {"message": "Keys verified and indexes ready!"}
