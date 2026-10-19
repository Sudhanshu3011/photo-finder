"""
src/api/upload_routes.py — Photo Upload, Batch Ingestion, and S3 Sync Router.
Enforces folder-level upload permissions and auto-creates managed folders for authorized creators.
"""
import logging
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, UploadFile, status, HTTPException

from src.schemas.upload_schemas import (
    PhotoUploadItem,
    PhotoUploadResponse,
    BatchUploadResponse,
    FolderSyncResponse,
)
from src.services.photo_upload_service import PhotoUploadService, get_upload_service
from src.api.dependencies import require_current_user, get_current_tenant_id, check_folder_capability
from src.modules.infra.postgres_repository import get_repository, PostgresRepository
from src.modules.infra.kv_cache import get_kv_cache
from src.modules.storage.s3_storage import get_s3_bucket
from src.core.config import MAX_UPLOAD_SIZE_MB, MAX_UPLOAD_SIZE_BYTES

logger = logging.getLogger("src.api.upload_routes")

router = APIRouter(prefix="/api/upload", tags=["Photo Upload & Ingestion"])


def resolve_user_s3_bucket(current_user: Optional[dict] = None) -> str:
    """Returns the server configured AWS S3 bucket."""
    return get_s3_bucket()


def _ensure_upload_permission(
    folder_name: str,
    current_user: dict,
    tenant_id: str,
    repo: PostgresRepository,
) -> str:
    """
    Verifies that the caller has upload rights for the target folder.
    If the folder does not exist, checks creation rights and auto-creates with creator as manager.
    Returns the resolved folder_name.
    """
    clean_name = (folder_name or "general").strip()
    folder = repo.get_folder_by_name(clean_name, tenant_id=tenant_id) or repo.get_folder_by_id(clean_name, tenant_id=tenant_id)

    if folder:
        check_folder_capability(folder["folder_id"], "upload", current_user, tenant_id, repo)
        return folder["folder_name"]

    # Target folder doesn't exist: check folder creation capability
    role = str(current_user.get("role", "viewer")).lower()
    if role not in ("owner", "admin", "editor", "contributor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Folder '{clean_name}' does not exist and role '{role}' is not permitted to create new folders."
        )

    # Auto-create folder with caller as manager
    new_fid = f"fld_{uuid.uuid4().hex[:12]}"
    user_id = current_user.get("user_id")
    repo.create_folder(
        folder_id=new_fid,
        tenant_id=tenant_id,
        folder_name=clean_name,
        description="Auto-created upon photo upload",
        visibility="tenant_wide" if role in ("owner", "admin") else "restricted",
        created_by=user_id,
    )
    return clean_name


@router.post("/photo", response_model=PhotoUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_single_photo(
    file: Optional[UploadFile] = File(None),
    image_url: Optional[str] = Form(None, description="Direct S3 or image URL"),
    folder_name: str = Form("general", description="Folder/album name to categorize the photo"),
    service: PhotoUploadService = Depends(get_upload_service),
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
):
    """
    Ingest, validate, and store a single image file or image URL into a target folder.
    Enforces folder-level upload permissions. Uploads directly to AWS S3 with local disk fallback.
    """
    if file is None and not image_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide an image file upload or an image_url"
        )

    resolved_folder = _ensure_upload_permission(folder_name, current_user, tenant_id, repo)
    user_id = current_user.get("user_id")

    res = await service.ingest_single_photo(
        file=file,
        image_url=image_url,
        folder_name=resolved_folder,
        user_id=user_id,
        tenant_id=tenant_id,
    )
    if res.get("status") == "failed":
        err_msg = res.get("message", "Upload failed")
        if "exceeds maximum allowed limit" in err_msg:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=err_msg)
        if "Unsupported file extension" in err_msg or "Unsupported image format" in err_msg:
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=err_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)

    return PhotoUploadResponse(
        status="success",
        data=PhotoUploadItem(**res)
    )


@router.post("/batch", response_model=BatchUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_batch_photos(
    files: List[UploadFile] = File(...),
    folder_name: str = Form("general", description="Folder/album name to upload photos into"),
    use_celery: bool = Form(False, description="Process batch asynchronously through Celery worker fleet"),
    service: PhotoUploadService = Depends(get_upload_service),
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
):
    """
    Upload and ingest multiple images into a specific folder/album in a single request.
    Enforces folder-level upload permissions.
    Supports asynchronous Celery worker fleet execution when use_celery is True.
    """
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files provided")

    if len(files) > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch size exceeds maximum limit of 50 images (received {len(files)} files). Please upload up to 50 images per batch."
        )

    resolved_folder = _ensure_upload_permission(folder_name, current_user, tenant_id, repo)
    user_id = current_user.get("user_id")

    if use_celery:
        res = await service.dispatch_batch_celery(
            files=files,
            folder_name=resolved_folder,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        return BatchUploadResponse(
            job_id=res["job_id"],
            total=res["total"],
            successful=0,
            failed=0,
            items=[]
        )

    res = await service.ingest_batch_photos(
        files=files,
        folder_name=resolved_folder,
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


@router.post("/from-s3-prefix", response_model=FolderSyncResponse, status_code=status.HTTP_200_OK)
async def ingest_from_s3_prefix(
    folder_name: str = Form(..., description="S3 prefix / folder name to sync images from"),
    service: PhotoUploadService = Depends(get_upload_service),
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
):
    """
    Fetch and index all photos from an existing AWS S3 bucket prefix / folder.
    Enforces folder-level upload permissions.
    """
    resolved_folder = _ensure_upload_permission(folder_name, current_user, tenant_id, repo)
    user_id = current_user.get("user_id")
    bucket = resolve_user_s3_bucket(current_user)

    res = await service.sync_folder_from_s3(
        folder_name=resolved_folder,
        bucket=bucket,
        user_id=user_id,
        tenant_id=tenant_id,
    )

    if res.get("status") == "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=res.get("message", "S3 sync failed")
        )

    return FolderSyncResponse(**res)
