"""
src/api/admin.py — System administration and database reset endpoints.
Renamed from ambiguous 'danger.py' to adhere to standard REST API naming conventions.
"""
import asyncio
import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status

from src.core.config import DEFAULT_CLOUDINARY_URL
from src.core.logging import log, warn
from src.core.security import get_verified_keys, get_user_id
from src.common.utils import get_ip, is_default_key
from src.services.cloudinary_service import (
    cld_delete_all_paginated,
    cld_remove_folder,
    cld_root_folders,
)
from src.services.faiss_service import faiss_store
from src.services.local_db import (
    sync_clear_vector_metadata,
    _get_connection,
)

router = APIRouter(prefix="/api", tags=["Admin"])


@router.post(
    "/reset-database",
    status_code=status.HTTP_200_OK,
    summary="Reset vector indexes and storage",
    description="Wipes local FAISS indexes, local database records, and Cloudinary media.",
)
async def reset_database(
    request: Request,
    user_id: str = Depends(get_user_id),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    start = time.perf_counter()
    log("WARNING", "admin.reset_database.attempt", user_id=user_id, ip=ip)

    if is_default_key(keys.get("cloudinary_url", ""), DEFAULT_CLOUDINARY_URL):
        log("WARNING", "admin.reset_database.blocked", user_id=user_id, ip=ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reset is not allowed on the shared demo storage.",
        )

    # 1. Clean Cloudinary assets
    try:
        deleted = await asyncio.to_thread(cld_delete_all_paginated, keys["cloudinary_creds"])
        log("INFO", "admin.reset_database.cloudinary_wiped", deleted=deleted)
    except Exception as e:
        warn(f"Cloudinary wipe warning: {e}")

    try:
        folders_res = await asyncio.to_thread(cld_root_folders, keys["cloudinary_creds"])
        folder_tasks = [
            asyncio.to_thread(cld_remove_folder, f["name"], keys["cloudinary_creds"])
            for f in folders_res.get("folders", [])
        ]
        if folder_tasks:
            await asyncio.gather(*folder_tasks, return_exceptions=True)
    except Exception as e:
        warn(f"Cloudinary folder cleanup warning: {e}")

    # 2. Reset FAISS Vector Stores and SQLite vector metadata
    try:
        faiss_store.reset_all()
        # Clean relational tables for this user or completely
        conn = _get_connection()
        try:
            with conn:
                conn.execute("DELETE FROM upload_jobs")
                conn.execute("DELETE FROM face_clusters")
                conn.execute("DELETE FROM face_vector_clusters")
                conn.execute("DELETE FROM kv_cache")
        finally:
            conn.close()
    except Exception as e:
        log("ERROR", "admin.reset_database.faiss_error", user_id=user_id, ip=ip, error=str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database reset error: {e}")

    duration_ms = round((time.perf_counter() - start) * 1000)
    log("WARNING", "admin.reset_database.complete", user_id=user_id, ip=ip, duration_ms=duration_ms)
    return {"message": "Database reset complete. All local FAISS vector stores and storage wiped."}


@router.post(
    "/delete-account",
    status_code=status.HTTP_200_OK,
    summary="Purge account data",
    description="Deletes all user assets, identity clusters, and FAISS vectors.",
)
async def delete_account(
    request: Request,
    user_id: str = Depends(get_user_id),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    start = time.perf_counter()
    log("WARNING", "admin.delete_account.attempt", user_id=user_id, ip=ip)

    if is_default_key(keys.get("cloudinary_url", ""), DEFAULT_CLOUDINARY_URL):
        log("WARNING", "admin.delete_account.blocked", user_id=user_id, ip=ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deletion is not allowed on the shared demo storage.",
        )

    try:
        await asyncio.to_thread(cld_delete_all_paginated, keys["cloudinary_creds"])
    except Exception as e:
        warn(f"Account delete Cloudinary error: {e}")

    faiss_store.reset_all()

    duration_ms = round((time.perf_counter() - start) * 1000)
    log("WARNING", "admin.delete_account.complete", user_id=user_id, ip=ip, duration_ms=duration_ms)
    return {"message": "Account data deleted and FAISS indexes purged."}
