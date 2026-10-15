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
from src.api.dependencies import require_current_user, get_current_tenant_id
from src.modules.infra.kv_cache import get_kv_cache
from src.modules.storage.s3_storage import get_s3_bucket

logger = logging.getLogger("src.api.upload_routes")

router = APIRouter(prefix="/api/upload", tags=["Photo Upload & Ingestion"])


def resolve_user_s3_bucket(current_user: Optional[dict] = None, override_bucket: Optional[str] = None) -> str:
    if override_bucket and override_bucket.strip():
        return override_bucket.strip()
    if current_user and current_user.get("storage_bucket"):
        return current_user["storage_bucket"].strip()
    if current_user and current_user.get("user_id"):
        cached_user = get_kv_cache().get(f"user_storage:{current_user['user_id']}")
        if cached_user:
            return str(cached_user).strip()
    return get_s3_bucket()


@router.post("/photo", response_model=PhotoUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_single_photo(
    file: Optional[UploadFile] = File(None),
    image_url: Optional[str] = Form(None, description="Direct S3 or image URL"),
    folder_name: str = Form("general", description="Folder/album name to categorize the photo"),
    s3_bucket: Optional[str] = Form(None, description="Optional target S3 bucket override"),
    cloudinary_url: Optional[str] = Form(None, description="Deprecated: legacy parameter"),
    service: PhotoUploadService = Depends(get_upload_service),
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """
    Ingest, validate, and store a single image file or image URL into a target folder.
    Performs quality assessment, saves to AWS S3, and records tenant-isolated metadata.
    """
    if file is None and not image_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide an image file upload or an image_url"
        )

    user_id = current_user.get("user_id")

    res = await service.ingest_single_photo(
        file=file,
        image_url=image_url,
        folder_name=folder_name,
        user_id=user_id,
        tenant_id=tenant_id,
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
    folder_name: str = Form("general", description="Folder/album name to upload photos into"),
    s3_bucket: Optional[str] = Form(None, description="Optional target S3 bucket override"),
    cloudinary_url: Optional[str] = Form(None, description="Deprecated: legacy parameter"),
    service: PhotoUploadService = Depends(get_upload_service),
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """
    Upload and ingest multiple images into a specific folder/album in a single request.
    Dispatches distributed background ingestion and AI inference workers.
    """
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files provided")

    if len(files) > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch size exceeds maximum limit of 50 images (received {len(files)} files). Please upload up to 50 images per batch."
        )

    user_id = current_user.get("user_id")

    res = await service.ingest_batch_photos(
        files=files,
        folder_name=folder_name,
        user_id=user_id,
        tenant_id=tenant_id,
    )

    return BatchUploadResponse(
        job_id=res["job_id"],
        total=res["total"],
        successful=res["successful"],
        failed=res["failed"],
        items=[PhotoUploadItem(**item) for item in res["items"]]
    )


@router.post("/from-s3-prefix", response_model=FolderSyncResponse)
@router.post("/from-cloudinary-folder", response_model=FolderSyncResponse)
async def ingest_from_s3_prefix(
    folder_name: str = Form(..., description="S3 prefix / folder name to sync images from"),
    s3_bucket: Optional[str] = Form(None, description="Optional S3 bucket name"),
    cloudinary_url: Optional[str] = Form(None, description="Deprecated: legacy parameter"),
    service: PhotoUploadService = Depends(get_upload_service),
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """
    Fetch and index all photos from an existing AWS S3 bucket prefix / folder.
    Allows processing an entire album directly without re-uploading file bytes.
    """
    user_id = current_user.get("user_id")
    bucket = resolve_user_s3_bucket(current_user, s3_bucket)

    res = await service.sync_from_s3_prefix(
        folder_name=folder_name,
        user_id=user_id,
        bucket=bucket,
        tenant_id=tenant_id,
    )

    if res.get("total_found", 0) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"S3 prefix '{folder_name}' contains no supported image assets in bucket '{bucket}'."
        )

    return FolderSyncResponse(
        folder=res["folder"],
        total_found=res["total_found"],
        synced=res["synced"],
        failed=res["failed"],
        items=[PhotoUploadItem(**item) for item in res["items"]]
    )



