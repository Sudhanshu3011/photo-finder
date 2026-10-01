"""
src/api/upload.py — HTTP presentation layer for image uploads and background AI indexing.
Adheres to decoupled async architecture:
1. Fast image ingestion (photos are uploaded to Cloudinary immediately).
2. Background AI indexing job is triggered and tracked via job_id.
3. Client can poll /api/jobs/{job_id} for live progress and execution logs.
"""
import asyncio
import uuid
from typing import List, Union

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status

from src.core.config import MAX_FILES_PER_UPLOAD, USE_ASYNC_UPLOADS
from src.core.security import get_verified_keys, get_user_id
from src.core.logging import log
from src.common.utils import get_ip
from src.services.local_db import get_or_create_user
from src.services.upload_service import (
    UploadService,
    process_one_file as _process_one_file,
    batch_upsert_all as _batch_upsert_all,
)
from src.api.dependencies import get_upload_service
from src.schemas.upload import UploadResponse, AsyncUploadQueuedResponse

router = APIRouter()


# ──────────────────────────────────────────────────────────────
# Upload endpoint (Decoupled Ingestion & Background AI Processing)
# ──────────────────────────────────────────────────────────────
@router.post(
    "/api/upload",
    response_model=Union[AsyncUploadQueuedResponse, UploadResponse],
    status_code=status.HTTP_200_OK,
    summary="Upload images and trigger background AI indexing",
    description="Uploads images to Cloudinary immediately, dispatches background AI feature extraction & FAISS vector indexing, and returns job_id for status tracking.",
)
async def upload_images(
    request: Request,
    files: List[UploadFile] = File(..., description="Select image files to upload"),
    folder_name: str = Form(..., description="Target category or folder name"),
    detect_faces: bool = Form(True, description="Whether to detect and index faces"),
    user_id: str = Form("", description="Optional user ID for isolation (persisted in local DB)"),
    sync: bool = Query(False, description="Set true to block and wait synchronously until AI indexing finishes"),
    keys: dict = Depends(get_verified_keys),
    upload_service: UploadService = Depends(get_upload_service),
):
    ip = get_ip(request)

    # Persist and resolve user UUID in local database
    resolved_user_id = await get_or_create_user(user_id)

    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No files provided for upload.")

    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Too many files. Max {MAX_FILES_PER_UPLOAD} per request.",
        )

    # Read all files in parallel
    file_bytes_list = await asyncio.gather(*[f.read() for f in files])
    filenames = [f.filename or f"image_{i}.jpg" for i, f in enumerate(files)]

    # ── Synchronous Mode (Only if explicitly requested) ────────
    if sync:
        try:
            result = await upload_service.process_sync(
                file_bytes_list=file_bytes_list,
                filenames=filenames,
                folder=folder_name,
                detect_faces=detect_faces,
                user_id=resolved_user_id,
                keys=keys,
                ip=ip,
            )
            result["user_id"] = resolved_user_id
            return result
        except RuntimeError as e:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))

    # ── Decoupled Async Mode (Default): Photos uploaded -> Job queued -> Background AI ──
    try:
        queued_result = await upload_service.upload_and_dispatch_job(
            file_bytes_list=file_bytes_list,
            filenames=filenames,
            folder=folder_name,
            detect_faces=detect_faces,
            user_id=resolved_user_id,
            keys=keys,
            ip=ip,
        )
        return queued_result
    except Exception as e:
        log("ERROR", "upload.failed", user_id=resolved_user_id, ip=ip, error=str(e))
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Upload failed: {e}")


__all__ = ["upload_images", "_process_one_file", "_batch_upsert_all"]