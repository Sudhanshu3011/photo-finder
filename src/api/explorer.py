import asyncio

from fastapi import APIRouter, Form, HTTPException, Request, Depends

from src.core.config import (
    DEFAULT_PINECONE_KEY, IDX_FACES, IDX_OBJECTS,
    IDX_FACES_ARCFACE, IDX_FACES_ADAFACE,
    USE_SPLIT_FACE_INDEXES,
)
from src.core.security import get_verified_keys
from src.services.db_client import (
    cld_delete_folder_resources, cld_delete_resource, cld_list_folder_images,
    cld_remove_folder, cld_root_folders, pinecone_pool,
)
from src.core.logging import log, warn
from src.common.utils import cld_thumb_url, get_ip, url_to_public_id

router = APIRouter()


def _get_face_index_names() -> list[str]:
    """Returns list of face index names to operate on based on current mode."""
    if USE_SPLIT_FACE_INDEXES:
        # Try both new and legacy — delete from both in case data exists in either
        return [IDX_FACES_ARCFACE, IDX_FACES_ADAFACE, IDX_FACES]
    return [IDX_FACES]


@router.post("/api/categories")
async def get_categories(
    request: Request,
    user_id: str = Form(""),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    try:
        result = await asyncio.to_thread(cld_root_folders, keys["cloudinary_creds"])
        categories = [f["name"] for f in result.get("folders", [])]
        log("INFO", "categories.fetched",
            user_id=user_id or "anonymous", ip=ip, count=len(categories))
        return {"categories": categories}
    except Exception as e:
        log("ERROR", "categories.error",
            user_id=user_id or "anonymous", ip=ip, error=str(e))
        return {"categories": []}


@router.post("/api/cloudinary/folder-images")
async def list_folder_images(
    request: Request,
    folder_name: str = Form(...),
    user_id: str = Form(""),
    next_cursor: str = Form(""),
    page_size: int = Form(100),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    result = await asyncio.to_thread(
        cld_list_folder_images,
        folder_name, keys["cloudinary_creds"], next_cursor or None, page_size,
    )
    images = [
        {
            "url": r["secure_url"],
            "thumb_url": cld_thumb_url(r["secure_url"]),
            "public_id": r["public_id"],
        }
        for r in result.get("resources", [])
    ]
    next_cur = result.get("next_cursor") or ""
    log("INFO", "explorer.folder_opened",
        user_id=user_id or "anonymous", ip=ip,
        folder=folder_name, count=len(images), has_more=bool(next_cur))
    return {"images": images, "count": len(images), "next_cursor": next_cur}


@router.post("/api/delete-image")
async def delete_image(
    request: Request,
    image_url: str = Form(""),
    public_id: str = Form(""),
    user_id: str = Form(""),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    pid = public_id or url_to_public_id(image_url)
    if not pid:
        raise HTTPException(400, "Could not determine public_id.")

    # Delete from Cloudinary
    await asyncio.to_thread(cld_delete_resource, pid, keys["cloudinary_creds"])

    # Delete from ALL vector indexes (split + legacy + objects)
    try:
        pc = pinecone_pool.get(keys["pinecone_key"])
        existing = {idx.name for idx in pc.list_indexes()}

        all_indexes = [IDX_OBJECTS] + _get_face_index_names()

        for idx_name in all_indexes:
            if idx_name not in existing:
                continue
            try:
                await asyncio.to_thread(
                    pc.Index(idx_name).delete,
                    filter={"url": {"$eq": image_url}},
                )
            except Exception as e:
                warn(f"Pinecone delete warning on {idx_name}: {e}")
    except Exception as e:
        warn(f"Pinecone delete outer warning: {e}")

    log("INFO", "explorer.image_deleted",
        user_id=user_id or "anonymous", ip=ip,
        image_url=image_url, public_id=pid)
    return {"message": "Image deleted successfully."}


@router.post("/api/delete-folder")
async def delete_folder(
    request: Request,
    folder_name: str = Form(...),
    user_id: str = Form(""),
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

    await asyncio.to_thread(
        cld_delete_folder_resources, folder_name, keys["cloudinary_creds"]
    )
    await asyncio.to_thread(
        cld_remove_folder, folder_name, keys["cloudinary_creds"]
    )

    # Delete from ALL vector indexes
    try:
        pc = pinecone_pool.get(keys["pinecone_key"])
        existing = {idx.name for idx in pc.list_indexes()}

        all_indexes = [IDX_OBJECTS] + _get_face_index_names()

        for idx_name in all_indexes:
            if idx_name not in existing:
                continue
            idx = pc.Index(idx_name)
            try:
                # Try metadata filter first (fast)
                await asyncio.to_thread(
                    idx.delete, filter={"folder": {"$eq": folder_name}}
                )
            except Exception:
                # Fallback: delete by URL one-by-one
                for img in all_images:
                    url = img.get("secure_url", "")
                    if url:
                        try:
                            await asyncio.to_thread(
                                idx.delete, filter={"url": {"$eq": url}}
                            )
                        except Exception:
                            pass
    except Exception as e:
        warn(f"Pinecone folder delete warning: {e}")

    log("INFO", "explorer.folder_deleted",
        user_id=user_id or "anonymous", ip=ip,
        folder=folder_name, deleted_count=len(all_images))
    return {
        "message": f"Folder '{folder_name}' and contents deleted.",
        "deleted_count": len(all_images),
    }