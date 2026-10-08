"""
src/modules/storage/local_storage.py — Local Filesystem Storage Client.
Provides persistent on-disk saving, deletion, and directory handling for images (e.g. saved_images/).
"""
import os
import uuid
from typing import Optional

from src.core.logging import log

STORAGE_ROOT = os.path.join(os.getcwd(), "saved_images")


def get_image_path(filename: str, folder: str = "general") -> str:
    """Returns local path for an image filename."""
    return os.path.join(STORAGE_ROOT, folder, filename)


def save_local_image(file_bytes: bytes, filename: str, folder: str = "general") -> str:
    """Saves image bytes to the local saved_images directory. Returns local file path."""
    folder_dir = os.path.join(STORAGE_ROOT, folder)
    os.makedirs(folder_dir, exist_ok=True)
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    unique_name = f"{uuid.uuid4().hex}_{filename}" if not filename.startswith("img_") else filename
    target_path = os.path.join(folder_dir, unique_name)

    with open(target_path, "wb") as f:
        f.write(file_bytes)

    log("INFO", "storage.local.saved", folder=folder, filename=unique_name, bytes=len(file_bytes))
    return target_path


save_image_bytes = save_local_image


def delete_local_image(filepath: str) -> bool:
    """Deletes an image file from the local storage if present."""
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            log("INFO", "storage.local.deleted", filepath=filepath)
            return True
        except Exception as e:
            log("ERROR", "storage.local.delete_failed", filepath=filepath, error=str(e))
            return False
    return False

