"""
src/modules/storage/cloudinary_storage.py — Cloudinary CDN Integration Client.
Handles file uploads, folder navigation, asset deletions, and storage health checks with pinpoint logging.
"""
from typing import Any, Dict, List, Optional
import cloudinary
import cloudinary.api
import cloudinary.uploader

from src.core.logging import log, warn


def set_cloudinary_config(creds: dict):
    """Configures the Cloudinary SDK with provided credentials."""
    cloudinary.config(
        cloud_name=creds.get("cloud_name"),
        api_key=creds.get("api_key"),
        api_secret=creds.get("api_secret"),
        secure=True,
    )


def ping_cloudinary(creds: dict) -> bool:
    """Verifies connection and credentials with Cloudinary."""
    try:
        set_cloudinary_config(creds)
        cloudinary.api.ping()
        log("INFO", "storage.cloudinary.ping_ok")
        return True
    except Exception as e:
        log("ERROR", "storage.cloudinary.ping_failed", error=str(e))
        raise


def upload_to_cloudinary(file_obj, folder: str, creds: dict) -> dict:
    """Uploads an image file-like object to a Cloudinary folder."""
    try:
        set_cloudinary_config(creds)
        res = cloudinary.uploader.upload(file_obj, folder=folder)
        log("INFO", "storage.cloudinary.upload_success", folder=folder, public_id=res.get("public_id"))
        return res
    except Exception as e:
        log("ERROR", "storage.cloudinary.upload_failed", folder=folder, error=str(e))
        raise


def upload_image_to_cloudinary(
    file_obj,
    folder: str = "general",
    creds: Optional[dict] = None,
    public_id: Optional[str] = None,
) -> Optional[dict]:
    """Uploads an image file or bytes to Cloudinary with graceful exception handling."""
    try:
        if creds:
            set_cloudinary_config(creds)
        kwargs: Dict[str, Any] = {"folder": folder}
        if public_id:
            kwargs["public_id"] = public_id
        res = cloudinary.uploader.upload(file_obj, **kwargs)
        log("INFO", "storage.cloudinary.upload_success", folder=folder, public_id=res.get("public_id"))
        return res
    except Exception as e:
        log("WARN", "storage.cloudinary.upload_skipped_or_failed", error=str(e))
        return None


def list_root_folders(creds: dict) -> List[str]:
    """Retrieves list of top-level folder names from Cloudinary."""
    try:
        set_cloudinary_config(creds)
        result = cloudinary.api.root_folders()
        folders = [f["name"] for f in result.get("folders", [])]
        log("INFO", "storage.cloudinary.folders_listed", count=len(folders))
        return folders
    except Exception as e:
        log("ERROR", "storage.cloudinary.folders_failed", error=str(e))
        return []


def list_folder_images(
    folder: str,
    creds: dict,
    cursor: Optional[str] = None,
    page_size: int = 100,
) -> dict:
    """Lists images within a specific folder using cursor pagination."""
    try:
        set_cloudinary_config(creds)
        kwargs = {"type": "upload", "prefix": f"{folder}/", "max_results": page_size}
        if cursor:
            kwargs["next_cursor"] = cursor
        res = cloudinary.api.resources(**kwargs)
        log("INFO", "storage.cloudinary.list_images_success", folder=folder, count=len(res.get("resources", [])))
        return res
    except Exception as e:
        log("ERROR", "storage.cloudinary.list_images_failed", folder=folder, error=str(e))
        return {"resources": [], "next_cursor": None}


def delete_cloudinary_resource(public_id: str, creds: dict) -> dict:
    """Deletes an image asset by public_id."""
    try:
        set_cloudinary_config(creds)
        res = cloudinary.uploader.destroy(public_id)
        log("INFO", "storage.cloudinary.delete_success", public_id=public_id, result=res.get("result"))
        return res
    except Exception as e:
        log("ERROR", "storage.cloudinary.delete_failed", public_id=public_id, error=str(e))
        raise


def delete_cloudinary_folder(folder: str, creds: dict) -> None:
    """Deletes all resources in a folder prefix and then deletes the empty folder."""
    try:
        set_cloudinary_config(creds)
        cloudinary.api.delete_resources_by_prefix(f"{folder}/")
        cloudinary.api.delete_folder(folder)
        log("INFO", "storage.cloudinary.delete_folder_success", folder=folder)
    except Exception as e:
        log("ERROR", "storage.cloudinary.delete_folder_failed", folder=folder, error=str(e))
        raise

