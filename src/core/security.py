"""
src/core/security.py — Industry-standard API credential resolution and User ID tracking.
Extracts credentials from Headers, Form data, or environment defaults without polluting GET request bodies.
Eliminates Pinecone key requirements in favor of local FAISS vector storage.
Maintains persistent user UUIDs in the PostgreSQL database.
"""
from typing import Optional
from fastapi import Header, HTTPException, Request

from src.modules.storage.s3_storage import get_s3_bucket
from src.modules.infra.postgres_repository import get_or_create_anonymous_user as get_or_create_user


async def get_verified_keys(
    request: Request,
    x_s3_bucket: Optional[str] = Header(None, alias="X-S3-Bucket"),
    x_cloudinary_url: Optional[str] = Header(None, alias="X-Cloudinary-Url"),  # Backward compatibility
) -> dict:
    """
    Resolved storage credentials dependency:
    Inspects S3 bucket configurations from headers or system defaults.
    """
    bucket = (x_s3_bucket or "").strip() or get_s3_bucket()
    return {
        "storage_bucket": bucket,
        "s3_bucket": bucket,
        "storage_type": "s3",
    }


async def get_user_id(
    request: Request,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
) -> str:
    """
    Resolves, tracks, and persists user UUID in PostgreSQL database.
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

    # Automatically persist and resolve UUID in PostgreSQL
    resolved_uid = await get_or_create_user(uid)
    return resolved_uid