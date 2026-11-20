import io
import logging
import mimetypes
from typing import Optional
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from src.modules.storage.s3_storage import (
    download_image_from_s3,
    extract_s3_key,
)

logger = logging.getLogger("src.api.media_routes")

router = APIRouter(prefix="/api/media", tags=["Media Delivery & Fallback Proxy"])


@router.get("/proxy", status_code=status.HTTP_200_OK)
@router.head("/proxy", status_code=status.HTTP_200_OK)
def proxy_media_asset(
    key: str = Query(..., description="S3 object key or full S3 URL to stream"),
    download: bool = Query(False, description="Whether to force download attachment"),
):
    """
    Streams an image asset directly from AWS S3 via server credentials.
    Acts as a secure fallback when client networks block direct S3 access.
    """
    clean_target = unquote(key.strip())
    clean_key = extract_s3_key(clean_target)

    if not clean_key or ".." in clean_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or unauthorized object key identifier."
        )

    try:
        data = download_image_from_s3(clean_key)
        if not data:
            raise FileNotFoundError(f"Object {clean_key} returned 0 bytes")
    except FileNotFoundError:
        logger.warning("[media_routes.proxy] Media asset not found: %s", clean_key)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media asset not found in storage."
        )
    except Exception as e:
        logger.error("[media_routes.proxy] Error streaming S3 asset %s: %s", clean_key, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream cloud storage error while retrieving media asset."
        )

    # Determine accurate MIME type
    content_type, _ = mimetypes.guess_type(clean_key)
    if not content_type:
        content_type = "image/jpeg"

    filename = clean_key.split("/")[-1]
    disposition = "attachment" if download else "inline"

    return StreamingResponse(
        io.BytesIO(data),
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Content-Length": str(len(data)),
        },
    )


@router.get("/image/{image_id}", status_code=status.HTTP_200_OK)
@router.head("/image/{image_id}", status_code=status.HTTP_200_OK)
def get_media_image(
    image_id: str,
    folder: Optional[str] = Query(None, description="Folder/collection name"),
    tenant_id: Optional[str] = Query(None, description="Workspace tenant identifier"),
    download: bool = Query(False, description="Whether to force download attachment"),
):
    """
    Resolves and streams an image by ID, checking possible key patterns in S3.
    """
    clean_id = image_id.strip()
    if not clean_id or ".." in clean_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image identifier."
        )

    # Build potential key candidates
    candidates = []
    has_ext = any(clean_id.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"])
    base_id = clean_id if has_ext else f"{clean_id}.jpg"

    if tenant_id and folder:
        candidates.append(f"{tenant_id.strip()}/{folder.strip()}/{base_id}")
    if folder:
        candidates.append(f"{folder.strip()}/{base_id}")
    candidates.append(base_id)

    data = None
    for cand in candidates:
        try:
            data = download_image_from_s3(cand)
            if data:
                clean_id = cand
                break
        except Exception:
            continue

    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Image '{clean_id}' not found in media storage."
        )

    content_type, _ = mimetypes.guess_type(clean_id)
    if not content_type:
        content_type = "image/jpeg"

    filename = clean_id.split("/")[-1]
    disposition = "attachment" if download else "inline"

    return StreamingResponse(
        io.BytesIO(data),
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Content-Length": str(len(data)),
        },
    )
