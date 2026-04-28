import asyncio
import io
import time
import uuid
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, Depends

from src.core.config import (
    IDX_FACES, IDX_OBJECTS,
    IDX_FACES_ARCFACE, IDX_FACES_ADAFACE,
    MAX_FILES_PER_UPLOAD, USE_SPLIT_FACE_INDEXES,
    USE_ASYNC_UPLOADS, CLUSTER_AUTO_TRIGGER_EVERY,
)
from src.core.security import get_verified_keys
from src.services.db_client import cld_upload, pinecone_pool, ensure_indexes
from src.core.logging import log
from src.common.utils import get_ip, standardize_category_name, to_list

router = APIRouter()


def chunker(seq, size):
    return (seq[pos:pos + size] for pos in range(0, len(seq), size))


# ──────────────────────────────────────────────────────────────
# Per-file processor — Cloudinary upload + AI inference only.
# Vectors are RETURNED, not upserted here. Caller batches all
# files' vectors into single Pinecone upserts (same as Phase 2).
# ──────────────────────────────────────────────────────────────
async def _process_one_file(
    *,
    file_bytes: bytes,
    folder: str,
    detect_faces: bool,
    keys: dict,
    ai,
    sem,
) -> tuple[str, str, list]:
    """Returns (file_id, image_url, vectors). Mirrors Phase 2 signature."""
    file_id = uuid.uuid4().hex

    async def _run_ai():
        async with sem:
            return await ai.process_image_bytes_async(file_bytes, detect_faces=detect_faces)

    cld_task = asyncio.to_thread(
        cld_upload, io.BytesIO(file_bytes), folder, keys["cloudinary_creds"]
    )
    ai_task = _run_ai()
    cld_res, vectors = await asyncio.gather(cld_task, ai_task)
    return file_id, cld_res["secure_url"], vectors


# ──────────────────────────────────────────────────────────────
# Shared batch-upsert logic — used by sync upload AND job worker
# ──────────────────────────────────────────────────────────────
async def _batch_upsert_all(
    *, results: list, folder: str, pc,
) -> dict:
    """
    Takes [(file_id, url, vectors), ...] from all files, groups them by
    target index, and upserts in one batch per index (single Pinecone
    call per index, not per-file).
    """
    arcface_upserts = []
    adaface_upserts = []
    legacy_face_upserts = []
    object_upserts = []
    uploaded_urls = []

    for file_id, image_url, vectors in results:
        uploaded_urls.append(image_url)
        for i, v in enumerate(vectors):
            vector_id = f"{file_id}_{i}"

            if v["type"] == "face":
                meta_common = {
                    "url": image_url,
                    "folder": folder,
                    "face_crop": v.get("face_crop", ""),
                    "det_score": float(v.get("det_score", 1.0)),
                    "face_width_px": int(v.get("face_width_px", 0)),
                    "blur_score": float(v.get("blur_score", 100.0)),
                }
                if USE_SPLIT_FACE_INDEXES:
                    arcface_upserts.append({
                        "id": vector_id,
                        "values": to_list(v["arcface_vector"]),
                        "metadata": meta_common,
                    })
                    if v.get("has_adaface"):
                        adaface_upserts.append({
                            "id": vector_id,
                            "values": to_list(v["adaface_vector"]),
                            "metadata": meta_common,
                        })
                else:
                    legacy_face_upserts.append({
                        "id": vector_id,
                        "values": to_list(v["vector"]),
                        "metadata": meta_common,
                    })
            else:
                object_upserts.append({
                    "id": vector_id,
                    "values": to_list(v["vector"]),
                    "metadata": {"url": image_url, "folder": folder},
                })

    idx_obj = pc.Index(IDX_OBJECTS)
    if USE_SPLIT_FACE_INDEXES:
        idx_arcface = pc.Index(IDX_FACES_ARCFACE)
        idx_adaface = pc.Index(IDX_FACES_ADAFACE)
    else:
        idx_face_legacy = pc.Index(IDX_FACES)

    def batched_upsert(index, vectors):
        for batch in chunker(vectors, 200):
            index.upsert(vectors=batch)

    db_tasks = []
    if USE_SPLIT_FACE_INDEXES:
        if arcface_upserts:
            db_tasks.append(asyncio.to_thread(batched_upsert, idx_arcface, arcface_upserts))
        if adaface_upserts:
            db_tasks.append(asyncio.to_thread(batched_upsert, idx_adaface, adaface_upserts))
    else:
        if legacy_face_upserts:
            db_tasks.append(asyncio.to_thread(batched_upsert, idx_face_legacy, legacy_face_upserts))
    if object_upserts:
        db_tasks.append(asyncio.to_thread(batched_upsert, idx_obj, object_upserts))

    if db_tasks:
        await asyncio.gather(*db_tasks)

    return {
        "uploaded_urls": uploaded_urls,
        "arcface_vecs": len(arcface_upserts),
        "adaface_vecs": len(adaface_upserts),
        "legacy_face_vecs": len(legacy_face_upserts),
        "object_vecs": len(object_upserts),
    }


# ──────────────────────────────────────────────────────────────
# Upload endpoint
# ──────────────────────────────────────────────────────────────
@router.post("/api/upload")
async def upload_images(
    request: Request,
    files: List[UploadFile] = File(...),
    folder_name: str = Form(...),
    detect_faces: bool = Form(True),
    user_id: str = Form(""),
    async_mode: bool = Query(False, alias="async"),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    start = time.perf_counter()

    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(400, f"Too many files. Max {MAX_FILES_PER_UPLOAD} per request.")

    folder = standardize_category_name(folder_name)
    pc = pinecone_pool.get(keys["pinecone_key"])

    # Auto-create indexes if missing. Idempotent.
    try:
        created = await asyncio.to_thread(ensure_indexes, pc)
        if created:
            log("INFO", "upload.indexes_auto_created",
                user_id=user_id or "anonymous", ip=ip, created=created)
            await asyncio.sleep(8)
    except Exception as e:
        log("ERROR", "upload.ensure_indexes_failed",
            user_id=user_id or "anonymous", ip=ip, error=str(e))
        raise HTTPException(500, f"Failed to initialize indexes: {e}")

    # ── Async mode: enqueue job, return immediately ──────────────
    if async_mode and USE_ASYNC_UPLOADS:
        from src.services.jobs import create_job

        files_data = []
        for f in files:
            b = await f.read()
            files_data.append({"bytes": list(b), "filename": f.filename})

        job_payload = {
            "files_data": files_data,
            "folder": folder,
            "detect_faces": detect_faces,
            "user_id": user_id or "anonymous",
            "keys": {
                "pinecone_key": keys["pinecone_key"],
                "cloudinary_creds": keys["cloudinary_creds"],
            },
        }

        job_id = await create_job(
            user_id=user_id or "anonymous",
            folder=folder,
            total_files=len(files),
            job_payload=job_payload,
        )

        log("INFO", "upload.async_enqueued",
            user_id=user_id or "anonymous", ip=ip,
            job_id=job_id, files=len(files), folder=folder)

        return {
            "message": "Upload queued",
            "job_id": job_id,
            "status_url": f"/api/jobs/{job_id}",
            "total_files": len(files),
        }

    # ── Synchronous mode (default, matches original Phase 2 perf) ─
    ai = request.app.state.ai
    sem = request.app.state.ai_semaphore

    # Read all files in parallel first, THEN fan out to _process_one_file.
    # Doing `await f.read()` inside the list-comp would serialize reads.
    file_bytes_list = await asyncio.gather(*[f.read() for f in files])

    results = await asyncio.gather(*[
        _process_one_file(
            file_bytes=fb,
            folder=folder,
            detect_faces=detect_faces,
            keys=keys,
            ai=ai,
            sem=sem,
        )
        for fb in file_bytes_list
    ])

    summary = await _batch_upsert_all(results=results, folder=folder, pc=pc)

    duration_ms = round((time.perf_counter() - start) * 1000)
    log(
        "INFO", "upload.complete",
        user_id=user_id or "anonymous", ip=ip,
        files=len(files), folder=folder, duration_ms=duration_ms,
        mode="split" if USE_SPLIT_FACE_INDEXES else "legacy",
        arcface_vecs=summary["arcface_vecs"],
        adaface_vecs=summary["adaface_vecs"],
        legacy_face_vecs=summary["legacy_face_vecs"],
        object_vecs=summary["object_vecs"],
    )

    # Log this sync upload to upload_jobs so the table isn't empty.
    # Sync uploads bypass the job queue entirely; this fire-and-forget task
    # writes a completed row for visibility without changing the upload flow.
    asyncio.create_task(
        _log_sync_upload(user_id=user_id or "anonymous", folder=folder, summary=summary)
    )

    # Auto-trigger clustering if threshold crossed (fire and forget)
    if CLUSTER_AUTO_TRIGGER_EVERY > 0 and summary["arcface_vecs"] > 0:
        asyncio.create_task(
            _maybe_trigger_clustering(pc, user_id, keys["pinecone_key"])
        )

    return {
        "message": "Done!",
        "urls": summary["uploaded_urls"],
        "summary": {
            "files": len(files),
            "face_vectors": summary["arcface_vecs"] or summary["legacy_face_vecs"],
            "adaface_vectors": summary["adaface_vecs"],
            "object_vectors": summary["object_vecs"],
            "index_mode": "split" if USE_SPLIT_FACE_INDEXES else "legacy",
        },
    }


async def _log_sync_upload(user_id: str, folder: str, summary: dict) -> None:
    """Write a completed row to upload_jobs for sync upload visibility.
    Sync uploads skip the job queue; without this the table stays empty and
    makes it impossible to audit what was indexed."""
    import json
    from src.services.jobs import _supa_insert
    row = {
        "job_id": uuid.uuid4().hex,
        "user_id": user_id,
        "folder": folder,
        "status": "completed",
        "total_files": len(summary["uploaded_urls"]),
        "processed_files": len(summary["uploaded_urls"]),
        "result": json.dumps({
            "face_vectors": summary["arcface_vecs"] or summary["legacy_face_vecs"],
            "adaface_vectors": summary["adaface_vecs"],
            "object_vectors": summary["object_vecs"],
        }),
    }
    try:
        await _supa_insert("upload_jobs", row)
    except Exception:
        pass  # Supabase not configured — silently skip, don't crash the upload


async def _maybe_trigger_clustering(pc, user_id: str, pinecone_key: str) -> None:
    """Background auto-cluster trigger when CLUSTER_AUTO_TRIGGER_EVERY crossed."""
    try:
        from src.services.cache import cache
        from src.services.clustering import run_clustering
        import hashlib

        uid = hashlib.sha256(pinecone_key.encode()).hexdigest()[:16]
        counter_key = f"upload_count:{uid}"
        count = await cache.incr(counter_key)

        if count >= CLUSTER_AUTO_TRIGGER_EVERY:
            await cache.delete(counter_key)
            log("INFO", "upload.auto_cluster_triggered",
                user_id=user_id or "anonymous", trigger_count=count)
            await run_clustering(pc, uid)
    except Exception as e:
        log("ERROR", "upload.auto_cluster_error", error=str(e))


# ──────────────────────────────────────────────────────────────
# Exported for jobs.py worker — same batched upsert path
# ──────────────────────────────────────────────────────────────
__all__ = ["upload_images", "_process_one_file", "_batch_upsert_all"]