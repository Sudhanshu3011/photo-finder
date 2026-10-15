"""
src/tasks/inference_tasks.py — Distributed AI Inference Tasks (queue.inference).
Executes face detection (InsightFace/YOLO), feature extraction (ArcFace/AdaFace 512-dim),
and FAISS vector upserting with strict tenant isolation.
Uses durable S3 object references (s3_key) to execute seamlessly across independent worker pods.
"""
import os
from typing import Any, Dict, Optional
import cv2
import numpy as np

from celery_app import app
from src.core.logging import log
from src.core.tenant_context import DEFAULT_TENANT_ID, set_current_tenant_id
from src.modules.infra.postgres_repository import get_repository
from src.modules.storage.s3_storage import download_image_from_s3
from src.services.image_processing_service import ImageProcessingService
from src.tasks.base import (
    TenantAwareTask,
    record_task_outcome,
    sync_job_progress_increment,
)


@app.task(
    bind=True,
    base=TenantAwareTask,
    name="src.tasks.inference_tasks.task_extract_embeddings",
    max_retries=3,
    default_retry_delay=10,
)
def task_extract_embeddings(
    self,
    ingest_payload_or_image_id: Any = None,
    local_path: Optional[str] = None,
    s3_key: Optional[str] = None,
    tenant_id: str = DEFAULT_TENANT_ID,
    folder_name: str = "general",
    cloud_url: Optional[str] = None,
    user_id: Optional[str] = None,
    job_id: Optional[str] = None,
    sha256: Optional[str] = None,
    phash: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Inference worker task executing in queue.inference pool.
    Can be invoked directly or piped from task_process_image_upload via Celery chain.
    Retrieves image data via durable S3 object reference (s3_key) for cross-pod portability.
    """
    # 1. Unpack piped input from Celery chain if provided
    if isinstance(ingest_payload_or_image_id, dict):
        payload = ingest_payload_or_image_id
        # Short-circuit if ingestion already marked item as duplicate or rejected
        status = payload.get("status")
        if status in ("duplicate_skipped", "failed"):
            return payload

        image_id = payload.get("image_id", "unknown")
        s3_key = payload.get("s3_key") or s3_key
        local_path = payload.get("local_path") or local_path
        cloud_url = payload.get("cloud_url") or cloud_url
        folder_name = payload.get("folder_name") or folder_name
        tenant_id = payload.get("tenant_id") or tenant_id
        user_id = payload.get("user_id") or user_id
        job_id = payload.get("job_id") or job_id
        sha256 = payload.get("sha256") or sha256
        phash = payload.get("phash") or phash
    else:
        image_id = str(ingest_payload_or_image_id or "unknown")

    set_current_tenant_id(tenant_id)
    log("INFO", "tasks.inference.start", image_id=image_id, s3_key=s3_key, tenant_id=tenant_id)

    try:
        cv_img = None

        # 2. Fast local path check if worker happens to share storage
        if local_path and os.path.exists(local_path):
            cv_img = cv2.imread(local_path)

        # 3. Durable S3 Object Reference: fetch directly from S3 (enables multi-pod isolation)
        if cv_img is None:
            resolved_key = s3_key or f"{tenant_id}/{folder_name.strip('/')}/{image_id}.jpg"
            raw_bytes = download_image_from_s3(resolved_key)
            nparr = np.frombuffer(raw_bytes, np.uint8)
            cv_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if cv_img is None:
            raise FileNotFoundError(f"Could not load image for '{image_id}' from local path or S3 key: {s3_key}")

        # 4. Run AI Inference (Face Detection, ArcFace/AdaFace Embeddings, Object Detection)
        svc = ImageProcessingService()
        result = svc.process_image_cv(
            image_id=image_id,
            cv_img=cv_img,
            user_id=user_id,
            folder_name=folder_name,
            cloud_url=cloud_url,
            tenant_id=tenant_id,
        )

        # 5. Record hash telemetry for future deduplication lookups
        if sha256 or phash:
            _attach_hash_to_metadata(image_id=image_id, tenant_id=tenant_id, sha256=sha256, phash=phash)

        # 6. Record atomic success outcome for job
        if job_id:
            faces_count = result.get("faces_detected", 0)
            record_task_outcome(
                job_id=job_id,
                tenant_id=tenant_id,
                outcome="successful",
                log_msg=f"Image '{image_id}' indexed ({faces_count} faces)",
            )

        log("INFO", "tasks.inference.success", image_id=image_id, faces=result.get("faces_detected", 0), tenant_id=tenant_id)
        return result

    except Exception as exc:
        log("ERROR", "tasks.inference.error", image_id=image_id, tenant_id=tenant_id, error=str(exc))
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

        if job_id:
            record_task_outcome(
                job_id=job_id,
                tenant_id=tenant_id,
                outcome="failed",
                log_msg=f"Inference failed for '{image_id}': {str(exc)}",
            )

        return {
            "image_id": image_id,
            "status": "failed",
            "error": str(exc),
            "tenant_id": tenant_id,
            "job_id": job_id,
        }


def _attach_hash_to_metadata(image_id: str, tenant_id: str, sha256: Optional[str], phash: Optional[str]) -> None:
    """Stores image hashes in vector metadata for fast future deduplication lookups."""
    try:
        repo = get_repository()
        records = [
            {
                "id": f"hash_{image_id}",
                "url": "",
                "folder": "hash_registry",
                "metadata": {"sha256": sha256, "phash": phash, "image_id": image_id},
            }
        ]
        repo.save_batch_metadata("enterprise-faces", records, tenant_id=tenant_id)
    except Exception as e:
        log("WARN", "tasks.inference.hash_attach_failed", image_id=image_id, error=str(e))
