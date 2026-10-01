"""
src/api/gallery.py — Media library and gallery folder management.
Renamed from ambiguous 'explorer.py' to accurately reflect its domain purpose.
Provides category/folder navigation, folder image listings, and asset deletion.
Synchronously syncs asset deletions with local FAISS vector stores.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status

from src.core.logging import log, warn
from src.core.security import get_verified_keys, get_user_id
from src.common.utils import cld_thumb_url, get_ip, url_to_public_id
from src.services.cloudinary_service import (
    cld_delete_folder_resources,
    cld_delete_resource,
    cld_list_folder_images,
    cld_remove_folder,
    cld_root_folders,
)
from src.services.faiss_service import faiss_store

router = APIRouter(prefix="/api", tags=["Gallery"])


@router.post(
    "/categories",
    status_code=status.HTTP_200_OK,
    summary="List media categories/folders",
    description="Fetches all root folder categories from Cloudinary.",
)
async def get_categories(
    request: Request,
    user_id: str = Depends(get_user_id),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    try:
        result = await asyncio.to_thread(cld_root_folders, keys["cloudinary_creds"])
        categories = [f["name"] for f in result.get("folders", [])]
        log("INFO", "gallery.categories.fetched", user_id=user_id, ip=ip, count=len(categories))
        return {"categories": categories}
    except Exception as e:
        log("ERROR", "gallery.categories.error", user_id=user_id, ip=ip, error=str(e))
        return {"categories": []}


@router.post(
    "/cloudinary/folder-images",
    status_code=status.HTTP_200_OK,
    summary="List images in a category/folder",
    description="Retrieves a paginated list of image assets stored in a specific folder.",
)
async def list_folder_images(
    request: Request,
    folder_name: str = Form(..., description="Name of the folder"),
    next_cursor: Optional[str] = Form(None, description="Pagination cursor"),
    page_size: int = Form(100, description="Items per page"),
    user_id: str = Depends(get_user_id),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    result = await asyncio.to_thread(
        cld_list_folder_images,
        folder_name,
        keys["cloudinary_creds"],
        next_cursor or None,
        page_size,
    )
    resources = result.get("resources", [])
    images = [
        {
            "public_id": r["public_id"],
            "url": r["secure_url"],
            "thumb_url": cld_thumb_url(r["secure_url"]),
            "created_at": r.get("created_at", ""),
            "bytes": r.get("bytes", 0),
            "width": r.get("width", 0),
            "height": r.get("height", 0),
        }
        for r in resources
    ]
    log(
        "INFO",
        "gallery.folder_images.fetched",
        user_id=user_id,
        ip=ip,
        folder=folder_name,
        count=len(images),
        has_next=bool(result.get("next_cursor")),
    )
    return {
        "folder": folder_name,
        "images": images,
        "next_cursor": result.get("next_cursor"),
        "total": len(images),
    }


@router.post(
    "/delete-image",
    status_code=status.HTTP_200_OK,
    summary="Delete image asset and vectors",
    description="Deletes an image from Cloudinary and purges its vector embeddings from FAISS.",
)
async def delete_image(
    request: Request,
    image_url: str = Form("", description="Direct image URL"),
    public_id: str = Form("", description="Cloudinary public ID"),
    user_id: str = Depends(get_user_id),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    pid = public_id or url_to_public_id(image_url)
    if not pid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Could not determine public_id.")

    # 1. Delete asset from Cloudinary
    await asyncio.to_thread(cld_delete_resource, pid, keys["cloudinary_creds"])

    # 2. Delete vectors from FAISS index and local metadata
    if image_url:
        vectors_removed = faiss_store.delete_by_url(image_url)
    else:
        vectors_removed = 0

    log("INFO", "gallery.image_deleted",
        user_id=user_id, ip=ip,
        image_url=image_url, public_id=pid, vectors_removed=vectors_removed)
    return {"message": "Image deleted successfully.", "vectors_removed": vectors_removed}


@router.post(
    "/delete-folder",
    status_code=status.HTTP_200_OK,
    summary="Delete folder and associated vectors",
    description="Deletes all images in a folder from Cloudinary and purges their FAISS vectors.",
)
async def delete_folder(
    request: Request,
    folder_name: str = Form(..., description="Target folder to delete"),
    user_id: str = Depends(get_user_id),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    all_images, cursor = [], None
    while True:
        result = await asyncio.to_thread(
            cld_list_folder_images, folder_name, keys["cloudinary_creds"], cursor
        )
        all_images.extend(result.get("resources", []))
        cursor = result.get("next_cursor")
        if not cursor:
            break

    await asyncio.to_thread(cld_delete_folder_resources, folder_name, keys["cloudinary_creds"])
    await asyncio.to_thread(cld_remove_folder, folder_name, keys["cloudinary_creds"])

    # Purge vectors from FAISS
    vectors_removed = faiss_store.delete_by_folder(folder_name)

    log("INFO", "gallery.folder_deleted",
        user_id=user_id, ip=ip,
        folder=folder_name, deleted_count=len(all_images), vectors_removed=vectors_removed)
    return {
        "message": f"Folder '{folder_name}' and contents deleted.",
        "deleted_count": len(all_images),
        "vectors_removed": vectors_removed,
    }
