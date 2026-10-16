"""
src/tasks/ingest_tasks.py — Distributed Image Ingestion Tasks (queue.ingest).
Handles raw file validation, SHA256 & pHash deduplication, durable S3 object reference creation,
atomic multi-counter telemetry, and outcome-aware batch completion.
"""
import io
import os
import uuid
from typing import Any, Dict, Optional

from celery_app import app
from src.core.logging import log
from src.core.config import MAX_UPLOAD_SIZE_BYTES, MAX_UPLOAD_SIZE_MB
from src.core.tenant_context import DEFAULT_TENANT_ID, set_current_tenant_id
from src.modules.deduplication.image_hasher import (
    compute_phash,
    compute_sha256,
    find_duplicate_image,
)
from src.modules.infra.kv_cache import get_kv_cache
from src.modules.storage.local_storage import save_image_bytes
from src.modules.storage.s3_storage import check_s3_object_exists, upload_image_to_s3
from src.modules.vision.image_quality import assess_image_quality
from src.tasks.base import (
    TenantAwareTask,
    record_task_outcome,
    sync_job_progress_increment,
)


@app.task(
    bind=True,
    base=TenantAwareTask,
    name="src.tasks.ingest_tasks.task_process_image_upload",
    max_retries=3,
    default_retry_delay=5,
)
def task_process_image_upload(
    self,
    file_bytes_or_path: Any,
    folder_name: str = "general",
    user_id: str = "anonymous",
    tenant_id: str = DEFAULT_TENANT_ID,
    image_id: Optional[str] = None,
    filename: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Ingest task executing in queue.ingest pool.
    1. Validates file bytes and assesses image quality.
    2. Computes SHA256 & pHash for instant duplicate checking.
    3. Uploads raw image to AWS S3 bucket under deterministic key: {tenant_id}/{folder}/{image_id}.jpg.
    4. Emits a lightweight durable object reference dictionary for downstream inference.
    """
    set_current_tenant_id(tenant_id)
    img_id = image_id or uuid.uuid4().hex
    fname = filename or f"{img_id}.jpg"
    ext = os.path.splitext(fname)[1] or ".jpg"
    if not img_id.endswith((".jpg", ".jpeg", ".png")):
        s3_filename = f"{img_id}{ext}"
    else:
        s3_filename = img_id
    s3_key = f"{tenant_id}/{folder_name.strip('/')}/{s3_filename}"

    try:
        # 1. Read file bytes
        if isinstance(file_bytes_or_path, (bytes, bytearray)):
            contents = bytes(file_bytes_or_path)
        elif isinstance(file_bytes_or_path, str) and os.path.exists(file_bytes_or_path):
            with open(file_bytes_or_path, "rb") as f:
                contents = f.read()
        else:
            raise ValueError(f"Invalid image payload format: {type(file_bytes_or_path)}")

        if not contents:
            raise ValueError("Empty image payload received")

        # Size check (Max 20MB per image)
        if len(contents) > MAX_UPLOAD_SIZE_BYTES:
            size_mb = len(contents) / (1024 * 1024)
            reason = f"File size exceeds maximum allowed limit of {MAX_UPLOAD_SIZE_MB}MB ({size_mb:.1f}MB uploaded)."
            log("WARN", "tasks.ingest.file_too_large", filename=fname, size_mb=round(size_mb, 2))
            record_task_outcome(
                job_id=job_id,
                tenant_id=tenant_id,
                outcome="failed",
                log_msg=f"Image '{fname}' rejected: {reason}",
            )
            return {
                "image_id": img_id,
                "status": "failed",
                "reason": reason,
                "tenant_id": tenant_id,
                "job_id": job_id,
            }

        # 2. Quality & Format assessment
        quality = assess_image_quality(contents, filename=fname)
        if not quality.get("is_valid"):
            reason = quality.get("reason", "Corrupted image")
            log("WARN", "tasks.ingest.invalid_quality", filename=fname, reason=reason)
            record_task_outcome(
                job_id=job_id,
                tenant_id=tenant_id,
                outcome="failed",
                log_msg=f"Image '{fname}' rejected: {reason}",
            )
            return {
                "image_id": img_id,
                "status": "failed",
                "reason": reason,
                "tenant_id": tenant_id,
                "job_id": job_id,
            }

        # 3. Deduplication Check (SHA256 & pHash)
        sha256 = compute_sha256(contents)
        phash = compute_phash(contents)
        duplicate = find_duplicate_image(sha256=sha256, phash=phash, tenant_id=tenant_id)

        if duplicate:
            existing_vec_id = duplicate.get("vector_id")
            log("INFO", "tasks.ingest.duplicate_skipped", image_id=img_id, existing_id=existing_vec_id, tenant_id=tenant_id)
            record_task_outcome(
                job_id=job_id,
                tenant_id=tenant_id,
                outcome="duplicate",
                log_msg=f"Image '{fname}' duplicate skipped (reusing vector {existing_vec_id})",
            )
            return {
                "image_id": img_id,
                "filename": fname,
                "s3_key": s3_key,
                "status": "duplicate_skipped",
                "existing_vector_id": existing_vec_id,
                "sha256": sha256,
                "phash": phash,
                "tenant_id": tenant_id,
                "job_id": job_id,
            }

        # 4. Optional local worker cache (avoids re-download if same pod)
        local_path = save_image_bytes(contents, f"{img_id}_{fname}")

        # 5. Upload to AWS S3 Object Storage (Resilient with existence pre-check)
        cloud_url = None
        try:
            if not check_s3_object_exists(s3_key):
                s3_res = upload_image_to_s3(
                    file_obj=io.BytesIO(contents),
                    folder=folder_name,
                    key=s3_filename,
                    tenant_id=tenant_id,
                )
                if s3_res:
                    cloud_url = s3_res.get("secure_url") or s3_res.get("url")
            else:
                from src.modules.storage.s3_storage import build_s3_url, get_s3_bucket
                cloud_url = build_s3_url(s3_key, get_s3_bucket())
        except Exception as e:
            log("WARN", "tasks.ingest.s3_upload_warning", image_id=img_id, error=str(e))

        # 6. Return durable reference for downstream inference worker in the chord chain
        return {
            "image_id": img_id,
            "filename": fname,
            "folder_name": folder_name,
            "s3_key": s3_key,
            "local_path": local_path,
            "cloud_url": cloud_url,
            "status": "ingested",
            "sha256": sha256,
            "phash": phash,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "job_id": job_id,
        }

    except Exception as exc:
        log("ERROR", "tasks.ingest.failed", image_id=img_id, error=str(exc))
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        record_task_outcome(
            job_id=job_id,
            tenant_id=tenant_id,
            outcome="failed",
            log_msg=f"Ingestion failed for '{fname}': {str(exc)}",
        )
        return {
            "image_id": img_id,
            "filename": fname,
            "status": "failed",
            "error": str(exc),
            "tenant_id": tenant_id,
            "job_id": job_id,
        }


@app.task(
    bind=True,
    base=TenantAwareTask,
    name="src.tasks.ingest_tasks.task_batch_completion_callback",
)
def task_batch_completion_callback(
    self,
    results: Any,
    job_id: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    folder_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Chord callback task invoked ONLY when ALL pipeline stages (ingest + inference)
    have finished across every image in the batch.
    Computes outcome-aware final status: 'completed', 'completed_with_errors', or 'failed'.
    """
    set_current_tenant_id(tenant_id)
    cache = get_kv_cache()
    cached = cache.get(f"job:{tenant_id}:{job_id}") or cache.get(f"job:{job_id}") or {}

    total = cached.get("total_files", 0)
    successful = cached.get("successful_files", 0)
    duplicate = cached.get("duplicate_files", 0)
    failed = cached.get("failed_files", 0)

    # Compute actual business outcome status
    if failed == 0:
        status = "completed"
    elif (successful + duplicate) == 0:
        status = "failed"
    else:
        status = "completed_with_errors"

    cached["status"] = status
    cached["current_stage"] = "done"
    summary_log = f"Batch finished: {successful} indexed, {duplicate} duplicate skipped, {failed} failed."
    logs = cached.get("logs", [])
    logs.append(summary_log)
    cached["logs"] = logs

    cache.set(f"job:{tenant_id}:{job_id}", cached)
    cache.set(f"job:{job_id}", cached)

    log("INFO", "tasks.batch.completed", job_id=job_id, status=status, successful=successful, duplicates=duplicate, failed=failed, tenant_id=tenant_id)

    # Only trigger face clustering if at least one image was successfully embedded
    if folder_name and successful > 0:
        from src.tasks.clustering_tasks import task_run_face_clustering
        task_run_face_clustering.apply_async(
            kwargs={
                "folder_name": folder_name,
                "tenant_id": tenant_id,
                "job_id": job_id,
            },
            queue="queue.clustering",
        )

    return {
        "job_id": job_id,
        "status": status,
        "total": total,
        "successful": successful,
        "duplicate": duplicate,
        "failed": failed,
        "tenant_id": tenant_id,
    }


# Backward-compatibility alias for internal task imports
_sync_job_progress_increment = sync_job_progress_increment
