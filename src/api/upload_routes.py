import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, UploadFile, status, HTTPException

from src.schemas.upload_schemas import (
    PhotoUploadItem,
    PhotoUploadResponse,
    BatchUploadResponse,
    FolderSyncResponse,
)
from src.services.photo_upload_service import PhotoUploadService, get_upload_service
from src.api.dependencies import require_current_user
from src.common.utils import get_cloudinary_creds
from src.modules.infra.kv_cache import get_kv_cache
from src.core.config import DEFAULT_CLOUDINARY_URL

logger = logging.getLogger("src.api.upload_routes")

router = APIRouter(prefix="/api/upload", tags=["Photo Upload & Ingestion"])


def resolve_user_cloudinary_url(current_user: Optional[dict] = None, override_url: Optional[str] = None) -> str:
    if override_url and override_url.strip():
        return override_url.strip()
    if current_user and current_user.get("cloudinary_url"):
        return current_user["cloudinary_url"].strip()
    if current_user and current_user.get("user_id"):
        cached_user = get_kv_cache().get(f"user_cld:{current_user['user_id']}")
        if cached_user:
            return str(cached_user).strip()
    system_cached = get_kv_cache().get("system_cld_config")
    if system_cached:
        return str(system_cached).strip()
    return DEFAULT_CLOUDINARY_URL


def _resolve_cloudinary_creds(current_user: Optional[dict] = None, override_url: Optional[str] = None) -> dict:
    url = resolve_user_cloudinary_url(current_user, override_url)
    return get_cloudinary_creds(url) if url else {}


@router.post("/photo", response_model=PhotoUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_single_photo(
    file: Optional[UploadFile] = File(None),
    image_url: Optional[str] = Form(None, description="Direct Cloudinary or image URL"),
    folder_name: str = Form("general", description="Cloudinary folder name"),
    cloudinary_url: Optional[str] = Form(None, description="Optional Cloudinary connection URL override"),
    service: PhotoUploadService = Depends(get_upload_service),
    current_user: dict = Depends(require_current_user),
):
    """
    Ingest, validate, and store a single image file or Cloudinary URL into a target folder.
    Performs quality assessment and saves to local disk and Cloudinary under the folder.
    Requires user authentication; user's saved Cloudinary credentials are used automatically.
    """
    if file is None and not image_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide an image file upload or an image_url"
        )

    user_id = current_user.get("user_id")
    creds = _resolve_cloudinary_creds(current_user, cloudinary_url)

    res = await service.ingest_single_photo(
        file=file,
        image_url=image_url,
        folder_name=folder_name,
        user_id=user_id,
        cloudinary_creds=creds,
    )
    if res.get("status") == "failed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=res.get("message", "Upload failed"))

    return PhotoUploadResponse(
        status="success",
        data=PhotoUploadItem(**res)
    )


@router.post("/batch", response_model=BatchUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_batch_photos(
    files: List[UploadFile] = File(...),
    folder_name: str = Form("general", description="Cloudinary folder name to upload photos into"),
    cloudinary_url: Optional[str] = Form(None, description="Optional Cloudinary connection URL override"),
    service: PhotoUploadService = Depends(get_upload_service),
    current_user: dict = Depends(require_current_user),
):
    """
    Upload and ingest multiple images into a specific Cloudinary folder in a single request.
    Creates a batch processing job record to track progress.
    Requires user authentication; user's saved Cloudinary credentials are used automatically.
    """
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files provided")

    if len(files) > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch size exceeds maximum limit of 50 images (received {len(files)} files). Please upload up to 50 images per batch."
        )

    user_id = current_user.get("user_id")
    creds = _resolve_cloudinary_creds(current_user, cloudinary_url)

    res = await service.ingest_batch_photos(
        files=files,
        folder_name=folder_name,
        user_id=user_id,
        cloudinary_creds=creds,
    )

    return BatchUploadResponse(
        job_id=res["job_id"],
        total=res["total"],
        successful=res["successful"],
        failed=res["failed"],
        items=[PhotoUploadItem(**item) for item in res["items"]]
    )


@router.post("/from-cloudinary-folder", response_model=FolderSyncResponse)
async def ingest_from_cloudinary_folder(
    folder_name: str = Form(..., description="Cloudinary folder name to sync images from"),
    cloudinary_url: Optional[str] = Form(None, description="Optional Cloudinary connection URL override"),
    service: PhotoUploadService = Depends(get_upload_service),
    current_user: dict = Depends(require_current_user),
):
    """
    Fetch and index all photos from an existing Cloudinary folder.
    Allows processing an entire album directly without re-uploading file bytes.
    Requires user authentication; user's saved Cloudinary credentials are used automatically.
    """
    user_id = current_user.get("user_id")
    creds = _resolve_cloudinary_creds(current_user, cloudinary_url)

    res = await service.sync_from_cloudinary_folder(
        folder_name=folder_name,
        user_id=user_id,
        cloudinary_creds=creds,
    )

    if res.get("total_found", 0) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cloudinary folder '{folder_name}' is not available, does not exist, or contains no supported image assets."
        )

    return FolderSyncResponse(
        folder=res["folder"],
        total_found=res["total_found"],
        synced=res["synced"],
        failed=res["failed"],
        items=[PhotoUploadItem(**item) for item in res["items"]]
    )



