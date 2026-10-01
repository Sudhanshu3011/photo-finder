"""
src/core/security.py — Industry-standard API credential resolution and User ID tracking.
Extracts credentials from Headers, Form data, or environment defaults without polluting GET request bodies.
Eliminates Pinecone key requirements in favor of local FAISS vector storage.
Maintains persistent user UUIDs in the local SQLite database.
"""
from typing import Optional
from fastapi import Header, HTTPException, Request

from src.core.config import DEFAULT_CLOUDINARY_URL
from src.common.utils import get_cloudinary_creds
from src.services.local_db import get_or_create_user


async def get_verified_keys(
    request: Request,
    x_cloudinary_url: Optional[str] = Header(None, alias="X-Cloudinary-Url"),
    x_pinecone_key: Optional[str] = Header(None, alias="X-Pinecone-Key"),  # Optional legacy header
) -> dict:
    """
    Industry-standard credentials dependency:
    1. Checks X-Cloudinary-Url header.
    2. For POST/PUT requests, checks form data if headers are not set.
    3. Falls back to server environment defaults (DEFAULT_CLOUDINARY_URL).
    Vector operations run locally on FAISS, requiring no external vector API key.
    """
    cld_url = (x_cloudinary_url or "").strip()

    # Check separate header components if full URL header is not present
    if not cld_url:
        h_name = request.headers.get("X-Cloudinary-Cloud-Name", "").strip()
        h_key = request.headers.get("X-Cloudinary-Api-Key", "").strip()
        h_sec = request.headers.get("X-Cloudinary-Api-Secret", "").strip()
        if h_name and h_key and h_sec:
            cld_url = f"cloudinary://{h_key}:{h_sec}@{h_name}"

    # If not in headers, inspect form body if available on POST/PUT
    if request.method in ("POST", "PUT", "PATCH") and not cld_url:
        content_type = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            try:
                form = await request.form()
                cld_url = str(form.get("user_cloudinary_url") or form.get("cloudinary_url") or "").strip()
                if not cld_url:
                    f_name = str(form.get("cloud_name") or form.get("cloudinary_cloud_name") or "").strip()
                    f_key = str(form.get("api_key") or form.get("cloudinary_api_key") or "").strip()
                    f_sec = str(form.get("api_secret") or form.get("cloudinary_api_secret") or "").strip()
                    if f_name and f_key and f_sec:
                        cld_url = f"cloudinary://{f_key}:{f_sec}@{f_name}"
            except Exception:
                pass

    actual_cld_url = cld_url or DEFAULT_CLOUDINARY_URL
    creds = get_cloudinary_creds(actual_cld_url)
    if not creds.get("cloud_name"):
        raise HTTPException(
            400,
            "Cloudinary configuration is missing or invalid. Set DEFAULT_CLOUDINARY_URL in .env, "
            "or pass the X-Cloudinary-Url header (or individual Cloudinary credentials)."
        )

    return {
        "cloudinary_url": actual_cld_url,
        "cloudinary_creds": creds,
        "pinecone_key": "local-faiss",  # Backwards compatibility dummy
    }


async def get_user_id(
    request: Request,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
) -> str:
    """
    Resolves, tracks, and persists user UUID in the local SQLite database.
    Checks X-User-ID header, query param, or form body. Generates and persists a new UUID if missing.
    """
    uid = (x_user_id or "").strip()

    if not uid and request.method in ("POST", "PUT", "PATCH"):
        content_type = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            try:
                form = await request.form()
                uid = str(form.get("user_id") or "").strip()
            except Exception:
                pass

    if not uid:
        uid = request.query_params.get("user_id", "").strip()

    # Automatically persist and resolve UUID in local SQLite
    resolved_uid = await get_or_create_user(uid)
    return resolved_uid