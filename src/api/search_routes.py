"""
src/api/search_routes.py — Visual & Face Search API Endpoints.
Scopes FAISS vector search strictly to permitted folders via the Single-Query Permission Resolver.
"""
import logging
from typing import Optional, List
import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, Request, status

from src.schemas.search_schemas import SearchResponse, MatchItem
from src.services.image_search_service import ImageSearchService
from src.api.dependencies import (
    get_image_search_service,
    require_current_user,
    get_current_tenant_id,
    check_folder_capability,
)
from src.modules.vision.face_detector import detect_faces
from src.modules.vision.face_embedder import extract_face_embeddings
from src.modules.infra.postgres_repository import (
    get_repository,
    PostgresRepository,
    sync_get_folder_image_count,
    sync_list_all_indexed_folders,
)
from src.common.utils import fetch_image_bytes_from_url
from src.modules.storage.s3_storage import build_s3_url
from src.modules.vision.image_quality import detect_image_format_from_bytes
from src.core.config import MAX_UPLOAD_SIZE_BYTES, MAX_UPLOAD_SIZE_MB

logger = logging.getLogger("src.api.search_routes")

router = APIRouter(prefix="/api/search", tags=["Visual & Face Search"])


def _resolve_search_filter(
    target_folder: Optional[str],
    current_user: dict,
    tenant_id: str,
    repo: PostgresRepository,
) -> Optional[dict]:
    """
    Resolves folder scope for vector similarity search.
    - If target_folder provided: verifies caller has 'view' access on it.
    - If target_folder omitted:
        * 'owner' and 'admin' search entire tenant gallery.
        * Other roles search only their accessible folders via allowed_folders filter.
    """
    clean_target = (target_folder or "").strip()
    role = str(current_user.get("role", "viewer")).lower()
    uid = current_user.get("user_id", "")

    if clean_target:
        folder = check_folder_capability(clean_target, "view", current_user, tenant_id, repo)
        return {"folder": folder["folder_name"]}

    if role in ("owner", "admin"):
        return None

    accessible = repo.resolve_user_accessible_folders(user_id=uid, tenant_id=tenant_id, role=role)
    if not accessible:
        return {"allowed_folders": ["__no_accessible_folders__"]}

    allowed_names = [f["folder_name"] for f in accessible]
    return {"allowed_folders": allowed_names}


@router.post("/image", response_model=SearchResponse, status_code=status.HTTP_200_OK)
async def search_by_image(
    request: Request,
    file: UploadFile = File(..., description="Query image file upload (mandatory)"),
    folder_name: str = Form(..., description="Target folder/album to search within (mandatory)"),
    top_k: int = Query(20, ge=1, le=30, description="Maximum number of matches to return"),
    threshold: float = Query(0.60, ge=0.0, le=1.0, description="Cosine similarity threshold"),
    service: ImageSearchService = Depends(get_image_search_service),
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
):
    """
    Search gallery using an uploaded query image file scoped strictly to the specified folder/album.
    Folder-level capability is verified before querying ('view' access required).
    Pre-filters candidate search vectors strictly to the permitted folder.
    """
    clean_folder = (folder_name or "").strip()
    if not clean_folder:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="folder_name is mandatory and must not be empty"
        )

    # 1. Enforce folder-level security: Caller MUST have 'view' capability on this folder
    folder = check_folder_capability(clean_folder, "view", current_user, tenant_id, repo)
    filter_dict = {"folder": folder["folder_name"]}

    # 2. Read and validate query image file
    contents = await file.read()
    if not contents or len(contents) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty query image file provided"
        )

    if len(contents) > MAX_UPLOAD_SIZE_BYTES:
        size_mb = len(contents) / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Query image exceeds maximum allowed limit of {MAX_UPLOAD_SIZE_MB}MB ({size_mb:.1f}MB uploaded)."
        )

    if detect_image_format_from_bytes(contents) is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported query image format. Allowed formats: JPEG, PNG, WebP, BMP, TIFF."
        )

    nparr = np.frombuffer(contents, np.uint8)
    cv_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if cv_img is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Corrupted or invalid image format")

    logger.info("[Search Route] Visual search (tenant='%s', folder='%s', top_k=%d, threshold=%.2f)",
                tenant_id, folder["folder_name"], top_k, threshold)

    res = service.search_by_image(
        cv_img=cv_img,
        top_k=top_k,
        threshold=threshold,
        filter_dict=filter_dict,
        tenant_id=tenant_id,
    )

    matches = []
    for m in res.get("results", []):
        img_id = m.get("image_id", "")
        meta = dict(m.get("metadata", {}) or {})
        c_url = m.get("cloud_url") or meta.get("url") or ""
        if not c_url and img_id:
            pid = img_id if img_id.startswith("img_") else f"img_{img_id}"
            fld = clean_folder or meta.get("folder") or "general"
            c_url = build_s3_url(key=f"{fld}/{pid}.jpg")
        meta["url"] = c_url

        matches.append(
            MatchItem(
                image_id=img_id,
                score=float(m.get("score", 0.0)),
                bbox=m.get("bbox"),
                person_name=m.get("person_name"),
                cluster_id=m.get("cluster_id") or meta.get("cluster_id"),
                thumbnail_url=m.get("thumbnail_url"),
                cloud_url=c_url,
                metadata=meta
            )
        )

    return SearchResponse(
        query_type=res.get("query_type", "none"),
        total_matches=len(matches),
        results=matches
    )


@router.post("/multi-angle", response_model=SearchResponse, status_code=status.HTTP_200_OK)
async def search_by_multi_angle(
    request: Request,
    front_file: Optional[UploadFile] = File(None, description="Frontal face image"),
    left_file: Optional[UploadFile] = File(None, description="Optional left profile image"),
    right_file: Optional[UploadFile] = File(None, description="Optional right profile image"),
    front_url: Optional[str] = Form(None, description="Frontal face image URL"),
    left_url: Optional[str] = Form(None, description="Optional left profile image URL"),
    right_url: Optional[str] = Form(None, description="Optional right profile image URL"),
    folder_name: Optional[str] = Form(None, description="Restrict search to this folder/album"),
    top_k: int = Query(20, ge=1, le=30, description="Maximum number of matches to return"),
    threshold: float = Query(0.60, ge=0.0, le=1.0, description="Cosine similarity threshold"),
    service: ImageSearchService = Depends(get_image_search_service),
    current_user: dict = Depends(require_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
    repo: PostgresRepository = Depends(get_repository),
):
    """
    Search using multi-angle face embeddings (front, left, right profile).
    Fuses feature vectors and scopes search strictly to permitted folders.
    """
    angle_inputs = {
        "front": (front_file, front_url),
        "left": (left_file, left_url),
        "right": (right_file, right_url),
    }

    angle_embeddings = {}
    for angle, (f, u) in angle_inputs.items():
        data = None
        if f:
            data = await f.read()
        elif u:
            try:
                data = await fetch_image_bytes_from_url(u)
            except Exception:
                data = None

        if not data:
            continue

        cv_img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if cv_img is None:
            continue

        faces = detect_faces(service.ai, cv_img) if service.ai else []
        if faces:
            target_face = faces[0] if (isinstance(faces[0], dict) and "arcface_vector" in faces[0]) else faces[0].get("face_obj", faces[0])
            emb = extract_face_embeddings(service.ai, target_face)
            vec = emb.get("arcface_vector")
            if vec:
                angle_embeddings[angle] = np.array(vec, dtype=np.float32)

    if not angle_embeddings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No faces detected in the provided angle images"
        )

    target_folder = (folder_name or request.query_params.get("folder_name") or request.query_params.get("folder") or "").strip()
    filter_dict = _resolve_search_filter(target_folder, current_user, tenant_id, repo)

    if filter_dict and filter_dict.get("allowed_folders") == ["__no_accessible_folders__"]:
        return SearchResponse(query_type="face_multi_angle", total_matches=0, results=[])

    logger.info("[Multi-Angle Search] Multi-angle search for tenant '%s' with angles %s (scope='%s', top_k=%d)",
                tenant_id, list(angle_embeddings.keys()), target_folder or "Permitted Folders", top_k)

    matches_data = service.search_multi_angle(
        angle_embeddings=angle_embeddings,
        top_k=top_k,
        threshold=threshold,
        filter_dict=filter_dict,
        tenant_id=tenant_id,
    )

    matches = []
    for m in matches_data:
        img_id = m.get("image_id", "")
        meta = dict(m.get("metadata", {}) or {})
        c_url = m.get("cloud_url") or meta.get("url") or ""
        if not c_url and img_id:
            pid = img_id if img_id.startswith("img_") else f"img_{img_id}"
            fld = target_folder or meta.get("folder") or "general"
            c_url = build_s3_url(key=f"{fld}/{pid}.jpg")
        meta["url"] = c_url

        matches.append(
            MatchItem(
                image_id=img_id,
                score=float(m.get("score", 0.0)),
                bbox=m.get("bbox"),
                person_name=m.get("person_name"),
                cluster_id=m.get("cluster_id") or meta.get("cluster_id"),
                thumbnail_url=m.get("thumbnail_url"),
                cloud_url=c_url,
                metadata=meta
            )
        )

    return SearchResponse(
        query_type="face_multi_angle",
        total_matches=len(matches),
        results=matches
    )
