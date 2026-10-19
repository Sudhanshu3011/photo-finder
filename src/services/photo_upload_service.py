import logging
import uuid
import os
from typing import Dict, Any, List, Optional
from fastapi import UploadFile

from src.modules.vision.image_quality import assess_image_quality
from src.modules.storage.local_storage import save_image_bytes, get_image_path
from src.modules.storage.s3_storage import upload_image_to_s3, list_s3_objects
from src.modules.infra.postgres_repository import get_repository
from src.modules.infra.kv_cache import get_kv_cache
from src.common.utils import fetch_image_bytes_from_url
from src.core.config import MAX_UPLOAD_SIZE_BYTES, MAX_UPLOAD_SIZE_MB

try:
    from celery import chord, chain
    from src.tasks.ingest_tasks import task_process_image_upload, task_batch_completion_callback
    from src.tasks.inference_tasks import task_extract_embeddings
    CELERY_AVAILABLE = True
except ImportError:
    chord = None
    chain = None
    task_process_image_upload = None
    task_batch_completion_callback = None
    task_extract_embeddings = None
    CELERY_AVAILABLE = False


logger = logging.getLogger("src.services.photo_upload_service")


class PhotoUploadService:
    """Orchestrator for photo upload, validation, persistence, and ingestion."""

    def __init__(self, repo=None, cache=None):
        self.repo = repo or get_repository()
        self.cache = cache or get_kv_cache()

    async def ingest_single_photo(
        self,
        file: Optional[UploadFile] = None,
        image_url: Optional[str] = None,
        folder_name: str = "general",
        user_id: Optional[str] = None,
        save_to_cloud: bool = True,
        tenant_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Validate, save, and record a single photo from an uploaded file or remote URL.
        Associates photo with the specified folder_name in S3 and metadata.
        """
        image_id = f"img_{uuid.uuid4().hex[:12]}"
        filename = "uploaded_image.jpg"

        if file is not None:
            filename = file.filename or "uploaded_image.jpg"
            contents = await file.read()
        elif image_url:
            filename = image_url.split("/")[-1].split("?")[0] or "remote_image.jpg"
            try:
                contents = await fetch_image_bytes_from_url(image_url)
            except Exception as e:
                logger.warning("[photo_upload_service.ingest_single_photo] Failed to fetch image from URL %s: %s", image_url, e)
                return {
                    "image_id": image_id,
                    "filename": filename,
                    "folder": folder_name,
                    "status": "failed",
                    "message": f"Could not download image from URL: {str(e)}"
                }
        else:
            return {
                "image_id": image_id,
                "filename": filename,
                "folder": folder_name,
                "status": "failed",
                "message": "Neither file nor image_url was provided"
            }

        logger.info("[photo_upload_service.ingest_single_photo] Ingesting '%s' (folder='%s') as %s",
                    filename, folder_name, image_id)

        if not contents or len(contents) == 0:
            logger.warning("[photo_upload_service.ingest_single_photo] File %s is empty", filename)
            return {
                "image_id": image_id,
                "filename": filename,
                "folder": folder_name,
                "status": "failed",
                "message": "File is empty"
            }

        # Size check (Max 20MB per image)
        if len(contents) > MAX_UPLOAD_SIZE_BYTES:
            size_mb = len(contents) / (1024 * 1024)
            logger.warning("[photo_upload_service.ingest_single_photo] File %s exceeds %dMB limit (%.1fMB)",
                           filename, MAX_UPLOAD_SIZE_MB, size_mb)
            return {
                "image_id": image_id,
                "filename": filename,
                "folder": folder_name,
                "status": "failed",
                "message": f"File size exceeds maximum allowed limit of {MAX_UPLOAD_SIZE_MB}MB ({size_mb:.1f}MB uploaded)."
            }

        # 1. Quality, Format & Dimension check
        quality = assess_image_quality(contents, filename=filename)
        if not quality["is_valid"]:
            logger.warning("[photo_upload_service.ingest_single_photo] Validation failed for %s: %s", filename, quality["reason"])
            return {
                "image_id": image_id,
                "filename": filename,
                "folder": folder_name,
                "status": "failed",
                "message": quality["reason"]
            }

        # 2. Cloud Object Storage (AWS S3) Primary
        cloud_url = None
        s3_key = None
        local_path = None
        storage_type = "s3"

        if save_to_cloud:
            if image_url and ("s3.amazonaws.com" in image_url or "s3." in image_url):
                cloud_url = image_url
            else:
                try:
                    cloud_res = upload_image_to_s3(
                        contents,
                        folder=folder_name,
                        key=image_id,
                        tenant_id=tenant_id,
                    )
                    if cloud_res:
                        cloud_url = cloud_res.get("secure_url") or cloud_res.get("url")
                        s3_key = cloud_res.get("key")
                except Exception as e:
                    logger.warning("[photo_upload_service.ingest_single_photo] S3 primary upload failed: %s. Falling back to local storage.", e)

        # 3. Graceful Local Storage Fallback if S3 is unavailable or failed
        if not cloud_url:
            local_path = save_image_bytes(contents, f"{image_id}_{filename}")
            storage_type = "local_fallback"
            logger.info("[photo_upload_service.ingest_single_photo] Stored asset in local disk fallback at %s", local_path)

        # 4. Cache Metadata
        meta = {
            "image_id": image_id,
            "filename": filename,
            "local_path": local_path,
            "cloud_url": cloud_url,
            "s3_key": s3_key,
            "storage_type": storage_type,
            "folder": folder_name,
            "tenant_id": tenant_id or "default",
            "width": quality.get("width"),
            "height": quality.get("height"),
            "is_blurry": quality.get("is_blurry"),
            "user_id": user_id,
            "status": "stored"
        }
        self.cache.set(f"meta:{image_id}", meta)

        logger.info("[photo_upload_service.ingest_single_photo] Successfully ingested %s (folder=%s, tenant=%s, cloud=%s)",
                    image_id, folder_name, tenant_id or "default", bool(cloud_url))

        return {
            "image_id": image_id,
            "filename": filename,
            "folder": folder_name,
            "tenant_id": tenant_id or "default",
            "status": "success",
            "message": "Photo uploaded and stored successfully",
            "width": quality.get("width"),
            "height": quality.get("height"),
            "is_blurry": quality.get("is_blurry"),
            "cloud_url": cloud_url
        }

    async def ingest_batch_photos(
        self,
        files: List[UploadFile],
        folder_name: str = "general",
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Handle batch photo uploads into a specific folder, tracking via database.
        """
        tid = tenant_id or "default"
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        total = len(files)
        logger.info("[photo_upload_service.ingest_batch_photos] Starting batch job_id=%s with %d files into folder '%s' (tenant: '%s')",
                    job_id, total, folder_name, tid)

        self.repo.create_job(job_id=job_id, total_images=total, user_id=user_id or "anonymous", folder=folder_name, tenant_id=tid)

        items = []
        successful = 0
        failed = 0

        for file in files:
            res = await self.ingest_single_photo(
                file=file,
                folder_name=folder_name,
                user_id=user_id,
                tenant_id=tid,
            )
            items.append(res)
            if res.get("status") == "success":
                successful += 1
            else:
                failed += 1

        job_status = "completed" if failed == 0 else "completed_with_errors"
        self.repo.update_job(job_id=job_id, processed_images=successful, status=job_status, tenant_id=tid)

        # Cache fast-path lookup in Redis for immediate polling
        job_data = {
            "job_id": job_id,
            "tenant_id": tid,
            "user_id": user_id or "anonymous",
            "folder": folder_name,
            "status": job_status,
            "current_stage": "completed",
            "total_files": total,
            "processed_files": successful,
            "successful_files": successful,
            "failed_files": failed,
            "logs": [f"Batch job {job_id}: {successful}/{total} photos uploaded successfully."],
        }
        self.cache.set(f"job:{tid}:{job_id}", job_data)
        self.cache.set(f"job:{job_id}", job_data)

        logger.info("[photo_upload_service.ingest_batch_photos] Completed job %s: %d success, %d failed", job_id, successful, failed)
        return {
            "job_id": job_id,
            "total": total,
            "successful": successful,
            "failed": failed,
            "items": items
        }

    async def dispatch_batch_celery(
        self,
        files: List[UploadFile],
        folder_name: str = "general",
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Dispatches batch photo upload to Celery worker fleet via chord.
        Returns job_id and status: 'queued' within < 15ms.
        """
        tid = tenant_id or "default"
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        total = len(files)
        logger.info("[photo_upload_service.dispatch_batch_celery] Enqueueing batch job %s with %d files", job_id, total)

        self.repo.create_job(job_id=job_id, total_images=total, user_id=user_id or "anonymous", folder=folder_name, tenant_id=tid)

        # Initialize atomic multi-counter state in Redis
        initial_job_data = {
            "job_id": job_id,
            "tenant_id": tid,
            "user_id": user_id or "anonymous",
            "folder": folder_name,
            "status": "pending",
            "current_stage": "queued",
            "total_files": total,
            "processed_files": 0,
            "successful_files": 0,
            "duplicate_files": 0,
            "failed_files": 0,
            "logs": [f"Batch job {job_id} queued with {total} items across worker fleet"],
        }
        self.cache.set(f"job:{tid}:{job_id}", initial_job_data)
        self.cache.set(f"job:{job_id}", initial_job_data)

        pipelines = []
        for file in files:
            img_id = uuid.uuid4().hex
            filename = file.filename or f"{img_id}.jpg"
            contents = await file.read()

            # Store original image in AWS S3 (durable single source of truth)
            payload_ref = None
            try:
                cloud_res = upload_image_to_s3(
                    contents,
                    folder=folder_name,
                    key=img_id,
                    tenant_id=tid,
                )
                if cloud_res:
                    payload_ref = cloud_res.get("key")
            except Exception as e:
                logger.warning(
                    "[photo_upload_service.dispatch_batch_celery] S3 upload failed for %s: %s. Using local fallback.",
                    img_id,
                    e,
                )

            # Fallback to local storage if S3 upload was unavailable
            if not payload_ref:
                payload_ref = save_image_bytes(contents, f"{img_id}_{filename}")

            pipeline = chain(
                task_process_image_upload.s(
                    file_bytes_or_path=payload_ref,
                    folder_name=folder_name,
                    user_id=user_id or "anonymous",
                    tenant_id=tid,
                    image_id=img_id,
                    filename=filename,
                    job_id=job_id,
                ),
                task_extract_embeddings.s(),
            )
            pipelines.append(pipeline)

        task_chord = chord(
            pipelines,
            task_batch_completion_callback.s(job_id=job_id, tenant_id=tid, folder_name=folder_name)
        )
        task_chord.apply_async()

        return {
            "job_id": job_id,
            "status": "queued",
            "total": total,
            "tenant_id": tid,
        }


    async def sync_from_s3_prefix(
        self,
        folder_name: str,
        user_id: Optional[str] = None,
        bucket: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ingest all image assets from an existing AWS S3 prefix / folder.
        """
        logger.info("[photo_upload_service.sync_from_s3_prefix] Syncing prefix '%s'", folder_name)

        resources = list_s3_objects(prefix=folder_name, bucket=bucket)

        items = []
        synced = 0
        failed = 0

        for r in resources:
            sec_url = r.get("url")
            if not sec_url:
                continue
            res = await self.ingest_single_photo(
                image_url=sec_url,
                folder_name=folder_name,
                user_id=user_id,
                save_to_cloud=False,  # Already hosted on S3
                tenant_id=tenant_id,
            )
            items.append(res)
            if res.get("status") == "success":
                synced += 1
            else:
                failed += 1

        return {
            "folder": folder_name,
            "total_found": len(resources),
            "synced": synced,
            "failed": failed,
            "items": items,
        }


_photo_upload_service_instance: Optional[PhotoUploadService] = None

def get_upload_service() -> PhotoUploadService:
    global _photo_upload_service_instance
    if _photo_upload_service_instance is None:
        _photo_upload_service_instance = PhotoUploadService()
    return _photo_upload_service_instance

