import asyncio
import time

from fastapi import APIRouter, Form, HTTPException, Request, Depends

from src.core.config import (
    DEFAULT_CLOUDINARY_URL, DEFAULT_PINECONE_KEY,
    IDX_FACES, IDX_OBJECTS,
    IDX_FACES_ARCFACE, IDX_FACES_ADAFACE,
    USE_SPLIT_FACE_INDEXES,
)
from src.core.security import get_verified_keys
from src.services.db_client import (
    cld_delete_all_paginated, cld_remove_folder, cld_root_folders,
    delete_and_recreate_indexes, pinecone_pool,
)
from src.core.logging import log, warn
from src.common.utils import get_ip, is_default_key

router = APIRouter()


def _all_index_names() -> list[str]:
    """All possible index names across both modes — used for exhaustive cleanup."""
    if USE_SPLIT_FACE_INDEXES:
        return [IDX_FACES, IDX_OBJECTS, IDX_FACES_ARCFACE, IDX_FACES_ADAFACE]
    return [IDX_FACES, IDX_OBJECTS]


@router.post("/api/reset-database")
async def reset_database(
    request: Request,
    user_id: str = Form(""),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    start = time.perf_counter()
    log("WARNING", "danger.reset_database.attempt",
        user_id=user_id or "anonymous", ip=ip)

    if is_default_key(keys["pinecone_key"], DEFAULT_PINECONE_KEY) or \
       is_default_key(keys["cloudinary_url"], DEFAULT_CLOUDINARY_URL):
        log("WARNING", "danger.reset_database.blocked",
            user_id=user_id or "anonymous", ip=ip)
        raise HTTPException(403, "Reset is not allowed on the shared demo database.")

    try:
        deleted = await asyncio.to_thread(
            cld_delete_all_paginated, keys["cloudinary_creds"]
        )
        log("INFO", "danger.reset_database.cloudinary_wiped", deleted=deleted)
    except Exception as e:
        warn(f"Cloudinary wipe error: {e}")

    try:
        folders_res = await asyncio.to_thread(
            cld_root_folders, keys["cloudinary_creds"]
        )
        folder_tasks = [
            asyncio.to_thread(
                cld_remove_folder, f["name"], keys["cloudinary_creds"]
            )
            for f in folders_res.get("folders", [])
        ]
        if folder_tasks:
            await asyncio.gather(*folder_tasks, return_exceptions=True)
    except Exception as e:
        warn(f"Cloudinary folder cleanup error: {e}")

    try:
        pc = pinecone_pool.get(keys["pinecone_key"])
        await asyncio.to_thread(delete_and_recreate_indexes, pc)
    except Exception as e:
        log("ERROR", "danger.reset_database.pinecone_error",
            user_id=user_id or "anonymous", ip=ip, error=str(e))
        raise HTTPException(500, f"Pinecone reset error: {e}")

    log("WARNING", "danger.reset_database.complete",
        user_id=user_id or "anonymous", ip=ip,
        duration_ms=round((time.perf_counter() - start) * 1000))
    return {"message": "Database reset complete. All data wiped and indexes recreated."}


@router.post("/api/delete-account")
async def delete_account(
    request: Request,
    user_id: str = Form(""),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    start = time.perf_counter()
    log("WARNING", "danger.delete_account.attempt",
        user_id=user_id or "anonymous", ip=ip)

    if is_default_key(keys["pinecone_key"], DEFAULT_PINECONE_KEY) or \
       is_default_key(keys["cloudinary_url"], DEFAULT_CLOUDINARY_URL):
        log("WARNING", "danger.delete_account.blocked",
            user_id=user_id or "anonymous", ip=ip)
        raise HTTPException(403, "Account deletion is not allowed on the shared demo database.")

    try:
        deleted = await asyncio.to_thread(
            cld_delete_all_paginated, keys["cloudinary_creds"]
        )
        log("INFO", "danger.delete_account.cloudinary_wiped", deleted=deleted)
    except Exception as e:
        warn(f"Account delete Cloudinary error: {e}")

    try:
        folders_res = await asyncio.to_thread(
            cld_root_folders, keys["cloudinary_creds"]
        )
        folder_tasks = [
            asyncio.to_thread(
                cld_remove_folder, f["name"], keys["cloudinary_creds"]
            )
            for f in folders_res.get("folders", [])
        ]
        if folder_tasks:
            await asyncio.gather(*folder_tasks, return_exceptions=True)
    except Exception as e:
        warn(f"Account delete folders error: {e}")

    try:
        pc = pinecone_pool.get(keys["pinecone_key"])

        def _delete_all_indexes():
            existing = {idx.name for idx in pc.list_indexes()}
            for name in _all_index_names():
                if name in existing:
                    pc.delete_index(name)

        await asyncio.to_thread(_delete_all_indexes)
    except Exception as e:
        warn(f"Account delete Pinecone error: {e}")

    log("WARNING", "danger.delete_account.complete",
        user_id=user_id or "anonymous", ip=ip,
        duration_ms=round((time.perf_counter() - start) * 1000))
    return {"message": "Account data deleted. Sign out initiated."}