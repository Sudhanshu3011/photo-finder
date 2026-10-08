import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.schemas.processing_schemas import (
    JobProgressResponse,
    FaceClusterResponse,
    ClusterRenameRequest,
    ClusteringTriggerResponse,
    ImageProcessResponse,
)
from src.services.image_processing_service import ImageProcessingService
from src.api.dependencies import get_image_processing_service, require_current_user
from src.services.jobs import get_job_status as fetch_job_status

logger = logging.getLogger("src.api.processing_routes")

router = APIRouter(tags=["Face Clustering & Albums"])


@router.post("/api/process/image/{image_id}", response_model=ImageProcessResponse, tags=["Photo Upload & Ingestion"])
def process_uploaded_image(
    image_id: str,
    service: ImageProcessingService = Depends(get_image_processing_service),
    current_user: dict = Depends(require_current_user),
):
    """
    Trigger AI inference pipeline for an uploaded image.
    Extracts face landmarks, ArcFace embeddings, and scene/object vectors into FAISS.
    """
    user_id = current_user.get("user_id")
    res = service.process_image_by_id(image_id=image_id, user_id=user_id)
    if res.get("status") == "failed":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=res.get("message", "Processing failed"))

    return ImageProcessResponse(
        image_id=res["image_id"],
        faces_detected=res.get("faces_detected", 0),
        objects_detected=res.get("objects_detected", 0),
        status=res.get("status", "success"),
        message=res.get("message")
    )


@router.post("/api/clusters/generate", response_model=ClusteringTriggerResponse)
@router.post("/api/process/cluster-faces", response_model=ClusteringTriggerResponse, include_in_schema=False)
async def trigger_face_clustering(
    request: Request,
    folder_name: Optional[str] = Query(None, description="Cloudinary folder name to cluster faces from"),
    min_cluster_size: int = Query(3, ge=2, description="Minimum face count required to form an identity cluster"),
    epsilon: float = Query(0.25, ge=0.01, le=1.0, description="DBSCAN / HDBSCAN cluster distance tolerance"),
    service: ImageProcessingService = Depends(get_image_processing_service),
    current_user: dict = Depends(require_current_user),
):
    """
    Run HDBSCAN clustering over extracted face embeddings to group identities into albums.
    Can be scoped to a specific folder_name.
    """
    target_folder = folder_name
    if not target_folder:
        try:
            body = await request.json()
            if isinstance(body, dict):
                target_folder = body.get("folder_name") or body.get("folder")
                if "min_cluster_size" in body and body["min_cluster_size"]:
                    min_cluster_size = int(body["min_cluster_size"])
                if "epsilon" in body and body["epsilon"]:
                    epsilon = float(body["epsilon"])
        except Exception:
            pass

    user_id = current_user.get("user_id")
    res = service.trigger_face_clustering(
        min_cluster_size=min_cluster_size,
        epsilon=epsilon,
        folder_name=target_folder,
        user_id=user_id,
    )
    return ClusteringTriggerResponse(
        status=res.get("status", "success"),
        clusters_found=res.get("clusters_found", 0),
        total_faces=res.get("total_faces", 0),
        message=res.get("message", "")
    )


@router.get("/api/clusters", response_model=List[FaceClusterResponse])
@router.get("/api/process/clusters", response_model=List[FaceClusterResponse], include_in_schema=False)
def get_all_clusters(
    folder_name: Optional[str] = Query(None, description="Filter clusters by Cloudinary folder name"),
    service: ImageProcessingService = Depends(get_image_processing_service),
    current_user: dict = Depends(require_current_user),
):
    """List all identified face clusters (people albums), optionally filtered by folder."""
    user_id = current_user.get("user_id")
    clusters = service.get_clusters(folder=folder_name, user_id=user_id)
    return [FaceClusterResponse(**c) for c in clusters]


@router.patch("/api/clusters/{cluster_id}", response_model=FaceClusterResponse)
@router.patch("/api/process/clusters/{cluster_id}", response_model=FaceClusterResponse, include_in_schema=False)
def rename_face_cluster(
    cluster_id: str,
    req: ClusterRenameRequest,
    service: ImageProcessingService = Depends(get_image_processing_service),
    current_user: dict = Depends(require_current_user),
):
    """Rename a face cluster to assign a person's real name."""
    success = service.rename_cluster(cluster_id=cluster_id, new_name=req.person_name)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cluster {cluster_id} not found")

    user_id = current_user.get("user_id")
    clusters = service.get_clusters(user_id=user_id)
    matching = [c for c in clusters if c["cluster_id"] == cluster_id]
    if not matching:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cluster {cluster_id} not found")

    return FaceClusterResponse(**matching[0])


@router.get("/api/jobs/{job_id}", response_model=JobProgressResponse, tags=["Photo Upload & Ingestion"])
async def get_job_progress(
    job_id: str,
    current_user: dict = Depends(require_current_user),
):
    """Check the status and progress of an asynchronous batch processing job."""
    job = await fetch_job_status(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found")

    return JobProgressResponse(
        job_id=job["job_id"],
        status=job["status"],
        total_images=job.get("total_files", 0),
        processed_images=job.get("processed_files", 0),
        total_files=job.get("total_files", 0),
        processed_files=job.get("processed_files", 0),
        current_stage=job.get("current_stage") or job.get("status"),
        logs=job.get("logs", []),
        error_message=job.get("error"),
        created_at=job.get("created_at"),
        updated_at=job.get("updated_at")
    )


