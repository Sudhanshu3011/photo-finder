"""
src/services/jobs.py — Phase 3: Async upload job queue
"""

import asyncio
import json
import uuid
from typing import Any, Optional

import aiohttp

from src.core.config import (
    SUPABASE_URL, SUPABASE_SERVICE_KEY,
    USE_ASYNC_UPLOADS,
)
from src.services.cache import cache

QUEUE_KEY = "upload_jobs_queue"
JOB_TTL = 86400  # 24 h


# ──────────────────────────────────────────────────────────────
# Supabase helpers
# ──────────────────────────────────────────────────────────────
def _supa_headers() -> dict:
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",  # FIX: was "return=representation" which requires 200 not 201
    }


def _clean_row(row: dict) -> dict:
    """
    Remove None values before sending to Supabase.
    Supabase REST rejects Python None in JSON — omit the key entirely
    and let Postgres use the column default instead.
    """
    return {k: v for k, v in row.items() if v is not None}


async def _supa_insert(table: str, row: dict) -> bool:
    """Returns True on success, False on failure. Logs errors explicitly."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print(f"[Supabase] SUPABASE_URL or SUPABASE_SERVICE_KEY not set — skipping insert")
        return False

    url = f"{SUPABASE_URL}/rest/v1/{table}"
    clean = _clean_row(row)

    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=_supa_headers(), json=clean) as r:
                if r.status in (200, 201):
                    return True
                else:
                    body = await r.text()
                    print(f"[Supabase INSERT ERROR] table={table} status={r.status} body={body[:500]}")
                    print(f"[Supabase INSERT ERROR] row_keys={list(clean.keys())}")
                    return False
    except Exception as e:
        print(f"[Supabase INSERT EXCEPTION] table={table} error={e}")
        return False


async def _supa_patch(table: str, job_id: str, patch: dict) -> bool:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return False
    url = f"{SUPABASE_URL}/rest/v1/{table}?job_id=eq.{job_id}"
    clean = _clean_row(patch)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.patch(url, headers=_supa_headers(), json=clean) as r:
                if r.status not in (200, 201, 204):
                    body = await r.text()
                    print(f"[Supabase PATCH ERROR] job_id={job_id} status={r.status} body={body[:300]}")
                    return False
                return True
    except Exception as e:
        print(f"[Supabase PATCH EXCEPTION] job_id={job_id} error={e}")
        return False


async def _supa_get(table: str, job_id: str) -> Optional[dict]:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return None
    # Use select= to avoid ambiguity with column names
    url = f"{SUPABASE_URL}/rest/v1/{table}?select=*&job_id=eq.{job_id}&limit=1"
    headers = {**_supa_headers(), "Prefer": "return=representation"}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers) as r:
                if r.status == 200:
                    data = await r.json()
                    return data[0] if data else None
    except Exception as e:
        print(f"[Supabase GET EXCEPTION] job_id={job_id} error={e}")
    return None


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────
async def create_job(
    user_id: str,
    folder: str,
    total_files: int,
    job_payload: dict,
) -> str:
    job_id = str(uuid.uuid4())

    # FIX: Only send columns that definitely exist in the table.
    # Do NOT send result/error (null) — let Postgres default them.
    # Do NOT send created_at/updated_at if table has DEFAULT NOW().
    row = {
        "job_id": job_id,
        "user_id": user_id or "anonymous",
        "folder": folder,
        "status": "pending",
        "total_files": total_files,
        "processed_files": 0,
    }

    success = await _supa_insert("upload_jobs", row)
    if success:
        print(f"[Jobs] Created job {job_id} in Supabase ✓")
    else:
        print(f"[Jobs] Supabase insert FAILED for job {job_id} — job will still work via Redis")

    # Redis is the source of truth for polling — works even if Supabase fails
    await cache.set_json(
        f"job:{job_id}",
        {**row, "payload": job_payload, "status": "pending"},
        ttl=JOB_TTL,
    )
    await cache.lpush(QUEUE_KEY, job_id)

    return job_id


async def get_job_status(job_id: str) -> Optional[dict]:
    # Check Redis first (fast path)
    cached = await cache.get_json(f"job:{job_id}")
    if cached:
        cached.pop("payload", None)
        return cached
    # Fallback to Supabase
    return await _supa_get("upload_jobs", job_id)


async def update_job_progress(job_id: str, processed: int, total: int) -> None:
    patch = {
        "status": "processing",
        "processed_files": processed,
    }
    await _supa_patch("upload_jobs", job_id, patch)

    cached = await cache.get_json(f"job:{job_id}") or {}
    cached.update(patch)
    await cache.set_json(f"job:{job_id}", cached, ttl=JOB_TTL)


async def complete_job(job_id: str, result: dict) -> None:
    patch = {
        "status": "completed",
        "processed_files": result.get("files", 0),
        "result": json.dumps(result),  # JSONB column — serialize explicitly
    }
    await _supa_patch("upload_jobs", job_id, patch)

    cached = await cache.get_json(f"job:{job_id}") or {}
    cached.update({**patch, "result": result})  # keep as dict in Redis
    cached.pop("payload", None)
    await cache.set_json(f"job:{job_id}", cached, ttl=JOB_TTL)


async def fail_job(job_id: str, error: str) -> None:
    patch = {
        "status": "failed",
        "error": str(error)[:500],  # truncate to avoid DB limit issues
    }
    await _supa_patch("upload_jobs", job_id, patch)

    cached = await cache.get_json(f"job:{job_id}") or {}
    cached.update(patch)
    cached.pop("payload", None)
    await cache.set_json(f"job:{job_id}", cached, ttl=JOB_TTL)


# ──────────────────────────────────────────────────────────────
# Background worker
# ──────────────────────────────────────────────────────────────
async def run_worker(app_state) -> None:
    print("[JobWorker] started")
    while True:
        try:
            job_id = await cache.rpop(QUEUE_KEY)
            if not job_id:
                await asyncio.sleep(2)
                continue

            print(f"[JobWorker] picked up job {job_id}")
            cached = await cache.get_json(f"job:{job_id}")
            if not cached:
                print(f"[JobWorker] job {job_id} not found in Redis — skipping")
                continue

            payload = cached.get("payload", {})
            await _execute_upload_job(job_id, payload, app_state)

        except asyncio.CancelledError:
            print("[JobWorker] cancelled — shutting down")
            break
        except Exception as e:
            print(f"[JobWorker] unhandled error: {e}")
            await asyncio.sleep(5)


async def _execute_upload_job(job_id: str, payload: dict, app_state) -> None:
    from src.services.db_client import pinecone_pool, ensure_indexes
    from src.api.upload import _process_one_file, _batch_upsert_all

    files_data: list[dict] = payload.get("files_data", [])
    folder: str = payload.get("folder", "uncategorized")
    detect_faces: bool = payload.get("detect_faces", True)
    user_id: str = payload.get("user_id", "anonymous")
    keys: dict = payload.get("keys", {})
    total = len(files_data)

    print(f"[JobWorker] executing job {job_id}: {total} files in '{folder}'")

    try:
        pc = pinecone_pool.get(keys["pinecone_key"])
        created = await asyncio.to_thread(ensure_indexes, pc)
        if created:
            await asyncio.sleep(8)

        CHUNK = 10
        all_results = []
        processed = 0

        for chunk_start in range(0, total, CHUNK):
            chunk = files_data[chunk_start:chunk_start + CHUNK]
            chunk_results = await asyncio.gather(*[
                _process_one_file(
                    file_bytes=bytes(f["bytes"]),
                    folder=folder,
                    detect_faces=detect_faces,
                    keys=keys,
                    ai=app_state.ai,
                    sem=app_state.ai_semaphore,
                )
                for f in chunk
            ])
            all_results.extend(chunk_results)
            processed += len(chunk)
            await update_job_progress(job_id, processed, total)
            print(f"[JobWorker] job {job_id}: {processed}/{total} processed")

        summary = await _batch_upsert_all(results=all_results, folder=folder, pc=pc)

        await complete_job(job_id, {
            "files": len(summary["uploaded_urls"]),
            "urls": summary["uploaded_urls"],
            "summary": {
                "arcface_vecs": summary["arcface_vecs"],
                "adaface_vecs": summary["adaface_vecs"],
                "object_vecs": summary["object_vecs"],
            },
        })
        print(f"[JobWorker] job {job_id} COMPLETED ✓")

    except Exception as e:
        print(f"[JobWorker] job {job_id} FAILED: {e}")
        import traceback
        traceback.print_exc()
        await fail_job(job_id, str(e))


# ──────────────────────────────────────────────────────────────
# Utility
# ──────────────────────────────────────────────────────────────
def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()