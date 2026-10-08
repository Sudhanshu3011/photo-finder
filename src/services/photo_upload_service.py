import logging
import uuid
import os
from typing import Dict, Any, List, Optional
from fastapi import UploadFile

from src.modules.vision.image_quality import assess_image_quality
from src.modules.storage.local_storage import save_image_bytes, get_image_path
from src.modules.storage.cloudinary_storage import upload_image_to_cloudinary
from src.modules.infra.sqlite_repository import get_repository
from src.modules.infra.kv_cache import get_kv_cache

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
        cloudinary_creds: Optional[dict] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Validate, save, and record a single photo from an uploaded file or remote URL.
        Associates photo with the specified folder_name on Cloudinary and in metadata.
        """
        image_id = f"img_{uuid.uuid4().hex[:12]}"
        filename = "uploaded_image.jpg"

        if file is not None:
            filename = file.filename or "uploaded_image.jpg"
            contents = await file.read()
        elif image_url:
            from src.common.utils import fetch_image_bytes_from_url
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

        # 1. Quality & Dimension check
        quality = assess_image_quality(contents)
        if not quality["is_valid"]:
            logger.warning("[photo_upload_service.ingest_single_photo] Validation failed for %s: %s", filename, quality["reason"])
            return {
                "image_id": image_id,
                "filename": filename,
                "folder": folder_name,
                "status": "failed",
                "message": quality["reason"]
            }

        # 2. Local Storage
        local_path = save_image_bytes(contents, f"{image_id}_{filename}")
        
        # 3. Cloudinary Storage
        cloud_url = None
        if save_to_cloud:
            if image_url and "cloudinary.com" in image_url:
                cloud_url = image_url
            else:
                try:
                    cloud_res = upload_image_to_cloudinary(
                        contents,
                        folder=folder_name,
                        creds=cloudinary_creds,
                        public_id=image_id
                    )
                    if cloud_res:
                        cloud_url = cloud_res.get("secure_url") or cloud_res.get("url")
                except Exception as e:
                    logger.warning("[photo_upload_service.ingest_single_photo] Cloud upload skipped/failed: %s", e)

        # 4. Cache Metadata
        meta = {
            "image_id": image_id,
            "filename": filename,
            "local_path": local_path,
            "cloud_url": cloud_url,
            "folder": folder_name,
            "width": quality.get("width"),
            "height": quality.get("height"),
            "is_blurry": quality.get("is_blurry"),
            "user_id": user_id,
            "status": "stored"
        }
        self.cache.set(f"meta:{image_id}", meta)

        logger.info("[photo_upload_service.ingest_single_photo] Successfully ingested %s (folder=%s, cloud=%s)",
                    image_id, folder_name, bool(cloud_url))

        return {
            "image_id": image_id,
            "filename": filename,
            "folder": folder_name,
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
        cloudinary_creds: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """
        Handle batch photo uploads into a specific folder, tracking via SQLite.
        """
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        total = len(files)
        logger.info("[photo_upload_service.ingest_batch_photos] Starting batch job_id=%s with %d files into folder '%s'",
                    job_id, total, folder_name)

        self.repo.create_job(job_id=job_id, total_images=total)

        items = []
        successful = 0
        failed = 0

        for file in files:
            res = await self.ingest_single_photo(
                file=file,
                folder_name=folder_name,
                user_id=user_id,
                cloudinary_creds=cloudinary_creds,
            )
            items.append(res)
            if res.get("status") == "success":
                successful += 1
            else:
                failed += 1

        self.repo.update_job(job_id=job_id, processed_images=successful, status="completed" if failed == 0 else "completed_with_errors")

        logger.info("[photo_upload_service.ingest_batch_photos] Completed job %s: %d success, %d failed", job_id, successful, failed)
        return {
            "job_id": job_id,
            "total": total,
            "successful": successful,
            "failed": failed,
            "items": items
        }

    async def sync_from_cloudinary_folder(
        self,
        folder_name: str,
        user_id: Optional[str] = None,
        cloudinary_creds: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """
        Ingest all image assets from an existing Cloudinary folder.
        """
        from src.modules.storage.cloudinary_storage import list_folder_images
        logger.info("[photo_upload_service.sync_from_cloudinary_folder] Syncing folder '%s'", folder_name)

        creds = cloudinary_creds or {}
        resources_res = list_folder_images(folder=folder_name, creds=creds)
        resources = resources_res.get("resources", [])

        items = []
        synced = 0
        failed = 0

        for r in resources:
            sec_url = r.get("secure_url") or r.get("url")
            if not sec_url:
                continue
            res = await self.ingest_single_photo(
                image_url=sec_url,
                folder_name=folder_name,
                user_id=user_id,
                save_to_cloud=False,  # Already hosted on Cloudinary
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

