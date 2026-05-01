"""
src/api/people.py — Phase 3: People View endpoints

GET  /api/people                → list all identity clusters
GET  /api/people/{cluster_id}   → all images in that cluster
PATCH /api/people/{cluster_id}  → rename a cluster
POST /api/reindex-clusters      → trigger full re-cluster

All endpoints require the standard pinecone/cloudinary auth headers
(via get_verified_keys). user_id is derived from the Pinecone key hash
so different users don't see each other's clusters even though they share
the same Supabase table.
"""

import hashlib

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request

from src.core.config import USE_CLUSTER_AWARE_SEARCH
from src.core.security import get_verified_keys
from src.core.logging import log
from src.services.clustering import (
    get_people,
    get_person_images,
    rename_cluster,
    run_clustering,
)
from src.services.db_client import pinecone_pool, ensure_indexes
from src.common.utils import get_ip

import asyncio

router = APIRouter()


def _user_id_from_key(pinecone_key: str) -> str:
    """
    Derives a stable, opaque user_id from the Pinecone API key.
    Users bring their own key, so this is the closest we have to an identity.
    Short SHA256 prefix is enough for row isolation — not a security measure.
    """
    return hashlib.sha256(pinecone_key.encode()).hexdigest()[:16]


@router.post("/api/people")
async def list_people(
    request: Request,
    keys: dict = Depends(get_verified_keys),
):
    """
    Returns all identity clusters for the authenticated user, ordered by
    face_count descending (most-seen people first).

    Request: FormData with user_pinecone_key + user_cloudinary_url

    Response shape:
    {
      "people": [
        {
          "cluster_id": "uuid",
          "name": "Mom" | null,
          "face_count": 42,
          "representative_face_crop": "<base64 jpg>"
        },
        ...
      ],
      "total": 3
    }
    """
    ip = get_ip(request)
    user_id = _user_id_from_key(keys["pinecone_key"])

    try:
        people = await get_people(user_id)
        log("INFO", "people.list", ip=ip, user_id=user_id, count=len(people))
        return {"people": people, "total": len(people)}
    except Exception as e:
        log("ERROR", "people.list.error", ip=ip, user_id=user_id, error=str(e))
        raise HTTPException(500, f"Failed to fetch people: {e}")


@router.post("/api/people/{cluster_id}")
async def get_cluster_images(
    cluster_id: str,
    request: Request,
    keys: dict = Depends(get_verified_keys),
):
    """
    Returns all images belonging to a specific identity cluster.

    Request: FormData with user_pinecone_key + user_cloudinary_url

    Response shape:
    {
      "cluster_id": "uuid",
      "images": [
        {"url": "...", "thumb_url": "...", "folder": "...", "face_crop": "<base64>"},
        ...
      ],
      "total": 12
    }
    """
    ip = get_ip(request)
    user_id = _user_id_from_key(keys["pinecone_key"])

    try:
        images = await get_person_images(cluster_id, user_id)
        log("INFO", "people.cluster_images",
            ip=ip, user_id=user_id, cluster_id=cluster_id, count=len(images))
        return {
            "cluster_id": cluster_id,
            "images": images,
            "total": len(images),
        }
    except Exception as e:
        log("ERROR", "people.cluster_images.error",
            ip=ip, user_id=user_id, cluster_id=cluster_id, error=str(e))
        raise HTTPException(500, f"Failed to fetch cluster images: {e}")


@router.post("/api/people/{cluster_id}/rename")
async def update_cluster_name(
    cluster_id: str,
    request: Request,
    name: str = Form(...),
    keys: dict = Depends(get_verified_keys),
):
    """
    Assigns a human-readable name to a cluster.

    Request: FormData with user_pinecone_key + user_cloudinary_url + name
    Response: {"cluster_id": "uuid", "name": "Mom", "ok": true}
    """
    ip = get_ip(request)
    user_id = _user_id_from_key(keys["pinecone_key"])

    if not name or len(name.strip()) == 0:
        raise HTTPException(400, "name must be a non-empty string")
    if len(name) > 100:
        raise HTTPException(400, "name must be 100 characters or fewer")

    try:
        await rename_cluster(cluster_id, name.strip(), user_id)
        log("INFO", "people.rename",
            ip=ip, user_id=user_id, cluster_id=cluster_id, name=name)
        return {"cluster_id": cluster_id, "name": name.strip(), "ok": True}
    except Exception as e:
        log("ERROR", "people.rename.error",
            ip=ip, user_id=user_id, cluster_id=cluster_id, error=str(e))
        raise HTTPException(500, f"Failed to rename cluster: {e}")


@router.post("/api/reindex-clusters")
async def reindex_clusters(
    request: Request,
    keys: dict = Depends(get_verified_keys),
):
    """
    Triggers a full HDBSCAN re-cluster of the user's face vectors.

    This is a synchronous (blocking) endpoint — clustering typically takes
    5-30 seconds depending on library size. For large libraries, consider
    running this in a background task (Phase 4).

    Response:
    {
      "status": "ok",
      "total_vectors": 3200,
      "clusters_found": 14,
      "noise_vectors": 80
    }
    """
    ip = get_ip(request)
    user_id = _user_id_from_key(keys["pinecone_key"])

    log("INFO", "people.reindex_start", ip=ip, user_id=user_id)

    try:
        pc = pinecone_pool.get(keys["pinecone_key"])

        # Ensure indexes exist before fetching vectors
        await asyncio.to_thread(ensure_indexes, pc)

        result = await run_clustering(pc, user_id)
        log("INFO", "people.reindex_done", ip=ip, user_id=user_id, **result)
        return result

    except RuntimeError as e:
        # e.g. hdbscan not installed
        raise HTTPException(503, str(e))
    except Exception as e:
        log("ERROR", "people.reindex_error", ip=ip, user_id=user_id, error=str(e))
        raise HTTPException(500, f"Clustering failed: {e}")