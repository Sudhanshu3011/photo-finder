"""
src/services/jobs.py — Asynchronous upload background job queue backed by PostgreSQL & Redis.
Manages job creation, status polling, real-time logging, and background worker execution.
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
from src.core.tenant_context import get_current_tenant_id
from src.modules.infra.kv_cache import cache
from src.modules.infra.postgres_repository import (
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
    job_payload: Optional[dict] = None,
    job_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> str:
    jid = job_id or str(uuid.uuid4())
    tid = (tenant_id or get_current_tenant_id()).strip()
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    initial_log = f"[{ts}] Job queued: {total_files} images scheduled for folder '{folder}' (tenant: '{tid}')"
    payload_dict = job_payload or {}

    # Persist in database
    await db_create_job(
        job_id=jid,
        user_id=user_id or "anonymous",
        folder=folder,
        total_files=total_files,
        payload=payload_dict,
        tenant_id=tid,
    )

    # Cache fast-path lookup in Redis / KV Cache
    job_data = {
        "job_id": jid,
        "tenant_id": tid,
        "user_id": user_id or "anonymous",
        "folder": folder,
        "status": "pending",
        "current_stage": "queued",
        "total_files": total_files,
        "processed_files": 0,
        "logs": [initial_log],
        "payload": payload_dict,
    }
    await cache.set_json(f"job:{tid}:{jid}", job_data, ttl=JOB_TTL)
    await cache.set_json(f"job:{jid}", job_data, ttl=JOB_TTL)
    await cache.lpush(f"{QUEUE_KEY}:{tid}", jid)
    await cache.lpush(QUEUE_KEY, jid)

    log(
        "INFO",
        "job.created",
        job_id=jid,
        tenant_id=tid,
        user_id=user_id or "anonymous",
        folder=folder,
        total_files=total_files,
    )
    return jid


async def append_job_log(job_id: str, message: str, stage: str = "", tenant_id: Optional[str] = None) -> None:
    """Appends an execution log message to both local DB and memory cache."""
    await db_append_job_log(job_id, message)
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    entry = f"[{ts}] {message}"

    tid = (tenant_id or get_current_tenant_id()).strip()
    cached = await cache.get_json(f"job:{tid}:{job_id}") or await cache.get_json(f"job:{job_id}") or {}
    logs = cached.get("logs", [])
    logs.append(entry)
    cached["logs"] = logs
    if stage:
        cached["current_stage"] = stage
    await cache.set_json(f"job:{tid}:{job_id}", cached, ttl=JOB_TTL)
    await cache.set_json(f"job:{job_id}", cached, ttl=JOB_TTL)


async def get_job_status(job_id: str, tenant_id: Optional[str] = None) -> Optional[dict]:
    """Retrieve job status, enforcing tenant isolation to prevent IDOR."""
    tid = (tenant_id or get_current_tenant_id()).strip()

    # Check cache fast-path first
    cached = await cache.get_json(f"job:{tid}:{job_id}") or await cache.get_json(f"job:{job_id}")
    if cached:
        # Verify tenant ownership if requested
        cached_tid = cached.get("tenant_id", "default")
        if tid != "default" and cached_tid != "default" and cached_tid != tid:
            return None  # IDOR prevention: Job belongs to another tenant
        cached.pop("payload", None)
        return cached

    # Fallback to database
    job = await db_get_job(job_id)
    if job:
        job_tid = job.get("tenant_id", "default")
        if tid != "default" and job_tid != "default" and job_tid != tid:
            return None  # IDOR prevention
        job.pop("payload", None)
    return job


async def update_job_progress(
    job_id: str,
    processed: int,
    total: int = 0,
    stage: str = "processing",
    log_msg: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> None:
    tid = (tenant_id or get_current_tenant_id()).strip()
    patch = {
        "status": "processing",
        "processed_files": processed,
    }
    await db_update_job(job_id, patch)

    cached = await cache.get_json(f"job:{tid}:{job_id}") or await cache.get_json(f"job:{job_id}") or {}
    cached.update(patch)
    cached["current_stage"] = stage
    await cache.set_json(f"job:{tid}:{job_id}", cached, ttl=JOB_TTL)
    await cache.set_json(f"job:{job_id}", cached, ttl=JOB_TTL)

    if log_msg:
        await append_job_log(job_id, log_msg, stage=stage, tenant_id=tid)

    log(
        "INFO",
        "job.progress",
        job_id=job_id,
        tenant_id=tid,
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


async def process_one_file(
    *,
    file_bytes: bytes,
    folder: str,
    detect_faces: bool,
    keys: dict,
    ai,
    sem,
):
    import io
    from src.modules.storage.s3_storage import upload_image_to_s3
    file_id = uuid.uuid4().hex

    async def _run_ai():
        async with sem:
            return await ai.process_image_bytes_async(file_bytes, detect_faces=detect_faces)

    s3_task = asyncio.to_thread(
        upload_image_to_s3, io.BytesIO(file_bytes), folder=folder, key=file_id
    )
    ai_task = _run_ai()
    s3_res, vectors = await asyncio.gather(s3_task, ai_task)
    return file_id, (s3_res or {}).get("secure_url", ""), vectors


async def batch_upsert_all(*, results: list, folder: str, vector_store=None) -> dict:
    from src.modules.infra.faiss_engine import vector_engine
    from src.common.utils import to_list
    from src.core.config import (
        IDX_FACES,
        IDX_OBJECTS,
        IDX_FACES_ARCFACE,
        IDX_FACES_ADAFACE,
    )
    store = vector_store or vector_engine
    arcface_upserts = []
    adaface_upserts = []
    object_upserts = []
    uploaded_urls = []

    for file_id, image_url, vectors in results:
        uploaded_urls.append(image_url)
        for i, v in enumerate(vectors):
            vector_id = f"{file_id}_{i}"
            if v.get("type") == "face":
                meta_common = {
                    "url": image_url,
                    "folder": folder,
                    "face_crop": v.get("face_crop", ""),
                    "det_score": float(v.get("det_score", 1.0)),
                    "face_width_px": int(v.get("face_width_px", 0)),
                    "blur_score": float(v.get("blur_score", 100.0)),
                }
                arcface_upserts.append({
                    "id": vector_id,
                    "values": to_list(v["arcface_vector"]),
                    "metadata": meta_common,
                })
                if v.get("has_adaface") and v.get("adaface_vector") is not None:
                    adaface_upserts.append({
                        "id": vector_id,
                        "values": to_list(v["adaface_vector"]),
                        "metadata": meta_common,
                    })
            elif v.get("type") == "object":
                object_upserts.append({
                    "id": vector_id,
                    "values": to_list(v["vector"]),
                    "metadata": {"url": image_url, "folder": folder},
                })

    # Delegate all vector insertions directly to FAISSEngine
    if arcface_upserts:
        store.upsert_vectors(IDX_FACES_ARCFACE, arcface_upserts)
        store.upsert_vectors(IDX_FACES, arcface_upserts)
    if adaface_upserts:
        store.upsert_vectors(IDX_FACES_ADAFACE, adaface_upserts)
    if object_upserts:
        store.upsert_vectors(IDX_OBJECTS, object_upserts)

    return {
        "uploaded_urls": uploaded_urls,
        "arcface_vecs": len(arcface_upserts),
        "adaface_vecs": len(adaface_upserts),
        "object_vecs": len(object_upserts),
    }


async def _execute_upload_job(job_id: str, payload: dict, app_state) -> None:
    from src.modules.infra.faiss_engine import vector_engine as faiss_store

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

        # Mode A: Decoupled Upload (files are on local disk in temp_dir, already uploaded to S3 / Object Storage)
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
                from src.services.image_processing_service import ImageProcessingService
                ImageProcessingService().trigger_face_clustering()
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