import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.schemas.processing_schemas import (
    JobProgressResponse,
    FaceClusterResponse,
    ClusterRenameRequest,
    ClusteringTriggerResponse,
    ClusterStatusResponse,
    ImageProcessResponse,
)
from src.services.image_processing_service import ImageProcessingService
from src.api.dependencies import (
    get_image_processing_service,
    require_current_user,
    get_current_user,
    get_current_tenant_id,
    has_minimum_role,
    check_folder_capability,
)
from src.modules.infra.postgres_repository import get_repository, PostgresRepository
from src.services.jobs import get_job_status as fetch_job_status

logger = logging.getLogger("src.api.processing_routes")

router = APIRouter(tags=["Face Clustering & Albums"])


@router.post("/api/process/image/{image_id}", response_model=ImageProcessResponse, status_code=status.HTTP_200_OK, tags=["Photo Upload & Ingestion"])
def process_uploaded_image(
    image_id: str,
    service: ImageProcessingService = Depends(get_image_processing_service),
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """
    Trigger AI inference pipeline for an uploaded image.
    Extracts face landmarks, ArcFace embeddings, and scene/object vectors into FAISS.
    """
    user_id = current_user.get("user_id")
    res = service.process_image_by_id(image_id=image_id, user_id=user_id, tenant_id=tenant_id)
    if res.get("status") == "failed":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=res.get("message", "Processing failed"))

    return ImageProcessResponse(
        image_id=res["image_id"],
        faces_detected=res.get("faces_detected", 0),
        objects_detected=res.get("objects_detected", 0),
        status=res.get("status", "success"),
        message=res.get("message")
    )


@router.get("/api/clusters/status", response_model=ClusterStatusResponse, status_code=status.HTTP_200_OK)
def get_cluster_readiness_status(
    folder_name: str = Query(..., description="Folder/album name to check clustering readiness for"),
    service: ImageProcessingService = Depends(get_image_processing_service),
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
):
    """
    Check the current clustering readiness and new photo delta for a folder.
    Enforces folder view capability.
    """
    target_folder = folder_name.strip() if folder_name else ""
    if not target_folder:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="folder_name must not be empty")

    check_folder_capability(target_folder, "view", current_user, tenant_id, repo)
    status_data = service.get_cluster_status(folder_name=target_folder, tenant_id=tenant_id)
    return ClusterStatusResponse(**status_data)


@router.post("/api/clusters/generate", response_model=ClusteringTriggerResponse, status_code=status.HTTP_200_OK)
async def trigger_face_clustering(
    request: Request,
    folder_name: str = Query(..., description="Folder/album name to cluster faces from"),
    min_cluster_size: int = Query(3, ge=2, description="Minimum face count required to form an identity cluster"),
    epsilon: float = Query(0.25, ge=0.01, le=1.0, description="DBSCAN / HDBSCAN cluster distance tolerance"),
    force: bool = Query(False, description="Bypass the 25 new images threshold (Admins and Owners only)"),
    service: ImageProcessingService = Depends(get_image_processing_service),
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
):
    """
    Run HDBSCAN clustering over extracted face embeddings to group identities into albums.
    Enforces hierarchical role check (Editor or higher) and the 25-image ingestion pipeline gate.
    """
    target_folder = folder_name.strip() if folder_name else ""
    if not target_folder:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="folder_name must not be empty"
        )

    # 1. Validate folder view access
    check_folder_capability(target_folder, "view", current_user, tenant_id, repo)

    # 2. Enforce role hierarchy: Editor (3) or higher required
    user_role = current_user.get("role", "viewer")
    if not has_minimum_role(user_role, "editor"):
        # Check if caller has explicit folder manager grant
        try:
            check_folder_capability(target_folder, "manage", current_user, tenant_id, repo)
        except HTTPException:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Role 'editor' or higher (or folder manager capability) is required to trigger face clustering."
            )

    # 3. 25-image delta check
    cluster_status = service.get_cluster_status(folder_name=target_folder, tenant_id=tenant_id)
    if not cluster_status["ready_for_clustering"]:
        if force and has_minimum_role(user_role, "admin"):
            logger.info("Admin %s force-triggering clustering for folder '%s'", current_user.get("user_id"), target_folder)
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Clustering requires at least 25 new photos since last run. Currently only {cluster_status['new_photos_since_last_cluster']}/25 new photos ingested."
            )

    user_id = current_user.get("user_id")
    res = service.trigger_face_clustering(
        min_cluster_size=min_cluster_size,
        epsilon=epsilon,
        folder_name=target_folder,
        user_id=user_id,
        tenant_id=tenant_id,
    )
    return ClusteringTriggerResponse(
        status=res.get("status", "success"),
        clusters_found=res.get("clusters_found", 0),
        total_faces=res.get("total_faces", 0),
        message=res.get("message", "")
    )


@router.get("/api/clusters", response_model=List[FaceClusterResponse], status_code=status.HTTP_200_OK)
def get_all_clusters(
    folder_name: Optional[str] = Query(None, description="Filter clusters by folder/album name"),
    service: ImageProcessingService = Depends(get_image_processing_service),
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """List all identified face clusters (people albums), optionally filtered by folder."""
    user_id = current_user.get("user_id")
    clusters = service.get_clusters(folder=folder_name, user_id=user_id, tenant_id=tenant_id)
    return [FaceClusterResponse(**c) for c in clusters]


@router.patch("/api/clusters/{cluster_id}", response_model=FaceClusterResponse, status_code=status.HTTP_200_OK)
def rename_face_cluster(
    cluster_id: str,
    req: ClusterRenameRequest,
    service: ImageProcessingService = Depends(get_image_processing_service),
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """
    Rename a face cluster to assign a person's real name.
    Restricted to Editor (3) or higher.
    """
    user_role = current_user.get("role", "viewer")
    if not has_minimum_role(user_role, "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Role 'editor' or higher required to rename face identity clusters."
        )

    success = service.rename_cluster(cluster_id=cluster_id, new_name=req.person_name, tenant_id=tenant_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cluster {cluster_id} not found")

    user_id = current_user.get("user_id")
    clusters = service.get_clusters(user_id=user_id, tenant_id=tenant_id)
    matching = [c for c in clusters if c["cluster_id"] == cluster_id]
    if not matching:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cluster {cluster_id} not found")

    return FaceClusterResponse(**matching[0])


@router.get("/api/jobs/{job_id}", response_model=JobProgressResponse, status_code=status.HTTP_200_OK, tags=["Photo Upload & Ingestion"])
async def get_job_progress(
    job_id: str,
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Check the status and progress of an asynchronous batch processing job."""
    eff_tenant = (tenant_id or "default").strip()
    job = await fetch_job_status(job_id, tenant_id=eff_tenant)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found")

    created_val = job.get("created_at")
    updated_val = job.get("updated_at")
    c_str = created_val.isoformat() if hasattr(created_val, "isoformat") else (str(created_val) if created_val else None)
    u_str = updated_val.isoformat() if hasattr(updated_val, "isoformat") else (str(updated_val) if updated_val else None)

    return JobProgressResponse(
        job_id=job["job_id"],
        status=job["status"],
        total_images=job.get("total_files", 0) or job.get("total_images", 0),
        processed_images=job.get("processed_files", 0) or job.get("processed_images", 0),
        total_files=job.get("total_files", 0) or job.get("total_images", 0),
        processed_files=job.get("processed_files", 0) or job.get("processed_images", 0),
        current_stage=job.get("current_stage") or job.get("status"),
        logs=job.get("logs", []),
        error_message=job.get("error"),
        created_at=c_str,
        updated_at=u_str,
    )


