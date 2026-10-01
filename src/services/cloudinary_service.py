"""
src/services/cloudinary_service.py — Clean, decoupled Cloudinary storage client.
Handles image uploads, asset destruction, folder pagination, and connection health checks.
"""
from typing import Any, Dict, Optional
import cloudinary
import cloudinary.uploader
import cloudinary.api


def _set_cld_config(creds: dict):
    """Configures the Cloudinary SDK with provided credentials."""
    cloudinary.config(
        cloud_name=creds.get("cloud_name"),
        api_key=creds.get("api_key"),
        api_secret=creds.get("api_secret"),
        secure=True,
    )


def cld_ping(creds: dict):
    """Pings Cloudinary to test connection and credential validity."""
    _set_cld_config(creds)
    cloudinary.api.ping()


def cld_upload(file_obj, folder: str, creds: dict) -> dict:
    """Uploads an image file object to the specified Cloudinary folder."""
    _set_cld_config(creds)
    return cloudinary.uploader.upload(file_obj, folder=folder)


def cld_root_folders(creds: dict) -> dict:
    """Retrieves top-level Cloudinary folders."""
    _set_cld_config(creds)
    return cloudinary.api.root_folders()


def cld_list_folder_images(
    folder: str,
    creds: dict,
    cursor: Optional[str] = None,
    page_size: int = 100,
) -> dict:
    """Lists images within a specific folder using cursor pagination."""
    _set_cld_config(creds)
    kwargs = {"type": "upload", "prefix": f"{folder}/", "max_results": page_size}
    if cursor:
        kwargs["next_cursor"] = cursor
    return cloudinary.api.resources(**kwargs)


def cld_delete_resource(public_id: str, creds: dict):
    """Destroys a specific resource by public_id."""
    _set_cld_config(creds)
    return cloudinary.uploader.destroy(public_id)


def cld_delete_folder_resources(folder: str, creds: dict):
    """Deletes all resources within a specified folder prefix."""
    _set_cld_config(creds)
    return cloudinary.api.delete_resources_by_prefix(f"{folder}/")


def cld_remove_folder(folder: str, creds: dict):
    """Removes an empty folder."""
    _set_cld_config(creds)
    try:
        return cloudinary.api.delete_folder(folder)
    except Exception:
        pass


def cld_delete_all_paginated(creds: dict) -> int:
    """Wipes all uploaded resources from Cloudinary, paginating through all pages."""
    _set_cld_config(creds)
    deleted = 0
    cursor = None
    while True:
        kwargs = {"type": "upload", "max_results": 500}
        if cursor:
            kwargs["next_cursor"] = cursor
        res = cloudinary.api.resources(**kwargs)
        resources = res.get("resources", [])
        if not resources:
            break
        pids = [r["public_id"] for r in resources]
        cloudinary.api.delete_resources(pids)
        deleted += len(pids)
        cursor = res.get("next_cursor")
        if not cursor:
            break
    return deleted
