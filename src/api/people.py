"""
src/api/people.py — People View endpoints for identity clustering and face albums.
Backed by local FAISS vector stores, HDBSCAN clustering, and SQLite persistence.
Endpoints:
POST  /api/people                → list all identity clusters
POST  /api/people/{cluster_id}   → all images in that cluster
PATCH /api/people/{cluster_id}  → rename a cluster
POST  /api/reindex-clusters      → trigger full re-clustering on FAISS vectors
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from src.core.logging import log
from src.core.security import get_verified_keys, get_user_id
from src.common.utils import get_ip
from src.services.clustering_service import (
    get_people,
    get_person_images,
    rename_cluster,
    run_clustering,
)

router = APIRouter(prefix="/api", tags=["People"])


@router.post(
    "/people",
    status_code=status.HTTP_200_OK,
    summary="List identity clusters",
    description="Returns all face identity clusters for the user, ordered by face count descending.",
)
async def list_people(
    request: Request,
    user_id: str = Depends(get_user_id),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    try:
        people = await get_people(user_id)
        log("INFO", "people.list", ip=ip, user_id=user_id, count=len(people))
        return {"people": people, "total": len(people)}
    except Exception as e:
        log("ERROR", "people.list.error", ip=ip, user_id=user_id, error=str(e))
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to fetch people: {e}")


@router.post(
    "/people/{cluster_id}",
    status_code=status.HTTP_200_OK,
    summary="List photos in cluster",
    description="Returns all images associated with a specific identity cluster.",
)
async def get_cluster_images(
    cluster_id: str,
    request: Request,
    user_id: str = Depends(get_user_id),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    try:
        images = await get_person_images(cluster_id, user_id)
        log("INFO", "people.images", ip=ip, user_id=user_id, cluster_id=cluster_id, count=len(images))
        return {
            "cluster_id": cluster_id,
            "images": images,
            "total": len(images),
        }
    except Exception as e:
        log("ERROR", "people.images.error", ip=ip, user_id=user_id, cluster_id=cluster_id, error=str(e))
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to fetch cluster images: {e}")


@router.patch(
    "/people/{cluster_id}",
    status_code=status.HTTP_200_OK,
    summary="Rename identity cluster",
    description="Assigns a person name to an identity cluster album.",
)
async def update_person_name(
    cluster_id: str,
    request: Request,
    name: str = Body(..., embed=True, description="New name for the person"),
    user_id: str = Depends(get_user_id),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    clean_name = name.strip() if name else ""
    try:
        ok = await rename_cluster(cluster_id, clean_name, user_id)
        if not ok:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Cluster {cluster_id} not found.")

        log("INFO", "people.renamed", ip=ip, user_id=user_id, cluster_id=cluster_id, name=clean_name)
        return {
            "status": "ok",
            "cluster_id": cluster_id,
            "name": clean_name,
        }
    except HTTPException:
        raise
    except Exception as e:
        log("ERROR", "people.rename.error", ip=ip, user_id=user_id, cluster_id=cluster_id, error=str(e))
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to rename cluster: {e}")


@router.post(
    "/reindex-clusters",
    status_code=status.HTTP_200_OK,
    summary="Reindex and cluster face vectors",
    description="Clusters all indexed face vectors using HDBSCAN over local FAISS embeddings.",
)
async def reindex_clusters(
    request: Request,
    user_id: str = Depends(get_user_id),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    log("INFO", "people.reindex_start", ip=ip, user_id=user_id)

    try:
        result = await run_clustering(user_id)
        log("INFO", "people.reindex_done", ip=ip, user_id=user_id, **result)
        return result
    except RuntimeError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    except Exception as e:
        log("ERROR", "people.reindex_error", ip=ip, user_id=user_id, error=str(e))
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Clustering failed: {e}")