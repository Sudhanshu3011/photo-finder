"""
src/services/jobs.py — Asynchronous upload background job queue backed by local SQLite.
Zero Supabase/Redis dependencies: manages job creation, status polling, real-time logging, and background worker execution.
Decouples fast image ingestion from heavy deep learning AI inference and FAISS indexing.
"""
import asyncio
from datetime import datetime, timezone
import json
import os
import shutil
import uuid
from typing import Any, Optional

from src.core.config import USE_ASYNC_UPLOADS, CLUSTER_AUTO_TRIGGER_EVERY
from src.core.logging import log, warn
from src.services.cache import cache
from src.services.local_db import (
    db_create_job,
    db_get_job,
    db_update_job,
    db_append_job_log,
)

QUEUE_KEY = "upload_jobs_queue"
JOB_TTL = 86400  # 24 h


# ──────────────────────────────────────────────────────────────
# Public Job Management API
# ──────────────────────────────────────────────────────────────
async def create_job(
    user_id: str,
    folder: str,
    total_files: int,
    job_payload: dict,
    job_id: Optional[str] = None,
) -> str:
    jid = job_id or str(uuid.uuid4())
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    initial_log = f"[{ts}] Job queued: {total_files} images scheduled for folder '{folder}'"

    # Persist in local SQLite database
    await db_create_job(
        job_id=jid,
        user_id=user_id or "anonymous",
        folder=folder,
        total_files=total_files,
        payload=job_payload,
    )

    # Cache fast-path lookup
    job_data = {
        "job_id": jid,
        "user_id": user_id or "anonymous",
        "folder": folder,
        "status": "pending",
        "current_stage": "queued",
        "total_files": total_files,
        "processed_files": 0,
        "logs": [initial_log],
        "payload": job_payload,
    }
    await cache.set_json(f"job:{jid}", job_data, ttl=JOB_TTL)
    await cache.lpush(QUEUE_KEY, jid)

    log(
        "INFO",
        "job.created",
        job_id=jid,
        user_id=user_id or "anonymous",
        folder=folder,
        total_files=total_files,
    )
    return jid


async def append_job_log(job_id: str, message: str, stage: str = "") -> None:
    """Appends an execution log message to both local DB and memory cache."""
    await db_append_job_log(job_id, message)
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    entry = f"[{ts}] {message}"

    cached = await cache.get_json(f"job:{job_id}") or {}
    logs = cached.get("logs", [])
    logs.append(entry)
    cached["logs"] = logs
    if stage:
        cached["current_stage"] = stage
    await cache.set_json(f"job:{job_id}", cached, ttl=JOB_TTL)


async def get_job_status(job_id: str) -> Optional[dict]:
    # Check cache fast-path first
    cached = await cache.get_json(f"job:{job_id}")
    if cached:
        cached.pop("payload", None)
        return cached

    # Fallback to local SQLite database
    job = await db_get_job(job_id)
    if job:
        job.pop("payload", None)
    return job


async def update_job_progress(
    job_id: str,
    processed: int,
    total: int,
    stage: str = "processing",
    log_msg: Optional[str] = None,
) -> None:
    patch = {
        "status": "processing",
        "processed_files": processed,
    }
    await db_update_job(job_id, patch)

    cached = await cache.get_json(f"job:{job_id}") or {}
    cached.update(patch)
    cached["current_stage"] = stage

    if log_msg:
        await append_job_log(job_id, log_msg, stage=stage)
    else:
        await cache.set_json(f"job:{job_id}", cached, ttl=JOB_TTL)

    log(
        "INFO",
        "job.progress",
        job_id=job_id,
        processed=processed,
        total=total,
        stage=stage,
    )


async def complete_job(job_id: str, result: dict) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    completion_msg = (
        f"[{ts}] Job completed successfully: {result.get('files', 0)} images processed and indexed into FAISS."
    )

    patch = {
        "status": "completed",
        "processed_files": result.get("files", 0),
        "result": result,
    }
    await db_update_job(job_id, patch)
    await db_append_job_log(job_id, "Job finished: all vector indexes updated.")

    cached = await cache.get_json(f"job:{job_id}") or {}
    cached.update(patch)
    cached["current_stage"] = "completed"
    logs = cached.get("logs", [])
    logs.append(completion_msg)
    cached["logs"] = logs
    cached.pop("payload", None)
    await cache.set_json(f"job:{job_id}", cached, ttl=JOB_TTL)

    log(
        "INFO",
        "job.completed",
        job_id=job_id,
        total_files=result.get("files", 0),
    )


async def fail_job(job_id: str, error: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    fail_msg = f"[{ts}] Error: {str(error)[:300]}"

    patch = {
        "status": "failed",
        "error": str(error)[:500],
    }
    await db_update_job(job_id, patch)
    await db_append_job_log(job_id, f"Execution failed: {str(error)[:300]}")

    cached = await cache.get_json(f"job:{job_id}") or {}
    cached.update(patch)
    cached["current_stage"] = "failed"
    logs = cached.get("logs", [])
    logs.append(fail_msg)
    cached["logs"] = logs
    cached.pop("payload", None)
    await cache.set_json(f"job:{job_id}", cached, ttl=JOB_TTL)

    log(
        "ERROR",
        "job.failed",
        job_id=job_id,
        error=str(error),
    )


# ──────────────────────────────────────────────────────────────
# Background worker
# ──────────────────────────────────────────────────────────────
async def run_worker(app_state) -> None:
    log("INFO", "job.worker.started", message="Background job worker thread active")
    while True:
        try:
            job_id = await cache.rpop(QUEUE_KEY)
            if not job_id:
                await asyncio.sleep(1.5)
                continue

            log("INFO", "job.worker.dequeue", job_id=job_id)
            cached = await cache.get_json(f"job:{job_id}")
            if not cached:
                cached = await db_get_job(job_id)

            if not cached:
                log("WARNING", "job.worker.not_found", job_id=job_id)
                continue

            payload = cached.get("payload", {})
            await _execute_upload_job(job_id, payload, app_state)

        except asyncio.CancelledError:
            log("INFO", "job.worker.cancelled", message="Background worker shutting down")
            break
        except Exception as e:
            log("ERROR", "job.worker.unhandled_error", error=str(e))
            await asyncio.sleep(5)


async def _execute_upload_job(job_id: str, payload: dict, app_state) -> None:
    from src.services.upload_service import batch_upsert_all
    from src.services.faiss_service import faiss_store

    files_list = payload.get("files", [])
    files_data = payload.get("files_data", [])
    folder: str = payload.get("folder", "uncategorized")
    detect_faces: bool = payload.get("detect_faces", True)
    user_id: str = payload.get("user_id", "anonymous")
    keys: dict = payload.get("keys", {})
    temp_dir = os.path.join("temp_uploads", job_id)

    total = len(files_list) or len(files_data)

    log(
        "INFO",
        "job.execute.start",
        job_id=job_id,
        user_id=user_id,
        total_files=total,
        folder=folder,
    )
    await append_job_log(
        job_id,
        f"Worker assigned. Starting background AI model inference for {total} images in '{folder}'...",
        stage="ai_processing",
    )

    try:
        all_results = []
        processed = 0

        # Mode A: Decoupled Upload (files are on local disk in temp_dir, already uploaded to Cloudinary)
        if files_list:
            for i, f_info in enumerate(files_list):
                file_id = f_info["file_id"]
                image_url = f_info["url"]
                temp_path = f_info["temp_path"]

                # Read image bytes
                if os.path.exists(temp_path):
                    with open(temp_path, "rb") as f:
                        file_bytes = f.read()
                else:
                    file_bytes = None

                if file_bytes:
                    async with app_state.ai_semaphore:
                        vectors = await app_state.ai.process_image_bytes_async(
                            file_bytes, detect_faces=detect_faces
                        )
                else:
                    vectors = []

                all_results.append((file_id, image_url, vectors))
                processed += 1

                if processed % 5 == 0 or processed == total:
                    pct = round(processed / total * 100)
                    await update_job_progress(
                        job_id,
                        processed,
                        total,
                        stage="ai_processing",
                        log_msg=f"Extracted AI features for {processed}/{total} images ({pct}%).",
                    )

        # Mode B: Direct memory/payload fallback (if files_data was passed)
        elif files_data:
            from src.services.upload_service import process_one_file
            CHUNK = 10
            for chunk_start in range(0, total, CHUNK):
                chunk = files_data[chunk_start:chunk_start + CHUNK]
                batch_num = (chunk_start // CHUNK) + 1
                total_batches = (total + CHUNK - 1) // CHUNK

                chunk_results = await asyncio.gather(*[
                    process_one_file(
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
                await update_job_progress(
                    job_id,
                    processed,
                    total,
                    stage="ai_processing",
                    log_msg=f"Batch {batch_num}/{total_batches} processed ({processed}/{total}).",
                )

        # Step 2: Vector Store Indexing
        await append_job_log(
            job_id,
            f"AI embeddings ready. Indexing {len(all_results)} images into local FAISS vector stores...",
            stage="faiss_indexing",
        )

        summary = await batch_upsert_all(
            results=all_results,
            folder=folder,
            vector_store=faiss_store,
        )

        await append_job_log(
            job_id,
            f"FAISS indexing complete: {summary['arcface_vecs']} ArcFace, {summary['adaface_vecs']} AdaFace, {summary['object_vecs']} object vectors.",
            stage="indexing_done",
        )

        # Step 3: Auto-trigger clustering if threshold crossed
        if CLUSTER_AUTO_TRIGGER_EVERY > 0 and summary["arcface_vecs"] > 0:
            try:
                from src.services.clustering_service import run_clustering
                await run_clustering(user_id=user_id)
                await append_job_log(job_id, "Face identity albums re-clustered successfully.")
            except Exception as ce:
                warn(f"Auto-clustering warning: {ce}")

        # Complete job
        await complete_job(job_id, {
            "files": len(summary["uploaded_urls"]),
            "urls": summary["uploaded_urls"],
            "summary": {
                "face_vectors": summary["arcface_vecs"] or summary["legacy_face_vecs"],
                "adaface_vectors": summary["adaface_vecs"],
                "object_vectors": summary["object_vecs"],
                "index_mode": "split",
            },
        })

    except Exception as e:
        log("ERROR", "job.execute.failed", job_id=job_id, error=str(e))
        import traceback
        traceback.print_exc()
        await fail_job(job_id, str(e))
    finally:
        # Clean up temporary upload directory
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass