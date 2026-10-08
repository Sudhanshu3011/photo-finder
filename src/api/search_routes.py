import logging
from typing import Optional
import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, Request, status

from src.schemas.search_schemas import SearchResponse, MatchItem
from src.services.image_search_service import ImageSearchService
from src.api.dependencies import get_image_search_service, require_current_user
from src.modules.vision.face_detector import detect_faces
from src.modules.vision.face_embedder import extract_face_embeddings
from src.modules.infra.sqlite_repository import sync_get_folder_image_count, sync_list_all_indexed_folders
from src.common.utils import fetch_image_bytes_from_url

logger = logging.getLogger("src.api.search_routes")

router = APIRouter(prefix="/api/search", tags=["Visual & Face Search"])


@router.post("/image", response_model=SearchResponse)
async def search_by_image(
    request: Request,
    file: Optional[UploadFile] = File(None, description="Query image file upload"),
    image_url: Optional[str] = Form(None, description="Direct Cloudinary or image URL to query"),
    folder_name: Optional[str] = Form(None, description="Restrict search to this Cloudinary folder/album"),
    top_k: int = Query(20, ge=1, le=30, description="Maximum number of matches to return"),
    threshold: float = Query(0.60, ge=0.0, le=1.0, description="Cosine similarity threshold"),
    service: ImageSearchService = Depends(get_image_search_service),
    current_user: dict = Depends(require_current_user),
):
    """
    Search gallery using an input query image file or direct Cloudinary URL.
    Optionally scopes/filters search to a specific Cloudinary folder.
    Automatically detects whether the query contains faces or objects.
    """
    contents = None
    if file is not None:
        contents = await file.read()
    elif image_url:
        try:
            contents = await fetch_image_bytes_from_url(image_url)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not download query image from URL: {str(e)}"
            )

    if not contents or len(contents) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty query image: please provide an image file or valid image_url"
        )

    nparr = np.frombuffer(contents, np.uint8)
    cv_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if cv_img is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image format")

    # Resolve folder name from form data or query param fallback
    target_folder = (folder_name or request.query_params.get("folder_name") or request.query_params.get("folder") or "").strip()

    # Validate target folder availability if scoping is requested
    if target_folder:
        folder_count = sync_get_folder_image_count(target_folder)
        if folder_count == 0:
            available = sync_list_all_indexed_folders()
            avail_msg = f" Available indexed folders: {', '.join(available)}" if available else " No folders are currently indexed."
            logger.warning("[Search Route] Folder '%s' is not available. %s", target_folder, avail_msg)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Folder '{target_folder}' is not available or contains no indexed images.{avail_msg}"
            )

    filter_dict = {"folder": target_folder} if target_folder else None
    logger.info("[Search Route] Executing visual search (folder_scope='%s', top_k=%d, threshold=%.2f)",
                target_folder or "All Folders", top_k, threshold)

    res = service.search_by_image(
        cv_img=cv_img,
        top_k=top_k,
        threshold=threshold,
        filter_dict=filter_dict
    )

    matches = []
    for m in res.get("results", []):
        img_id = m.get("image_id", "")
        meta = dict(m.get("metadata", {}) or {})
        c_url = m.get("cloud_url") or meta.get("url") or ""
        if not c_url and img_id:
            pid = img_id if img_id.startswith("img_") else f"img_{img_id}"
            fld = target_folder or meta.get("folder") or "general"
            c_url = f"https://res.cloudinary.com/ks28qusz/image/upload/{fld}/{pid}.jpg"
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


@router.post("/multi-angle", response_model=SearchResponse)
async def search_by_multi_angle(
    request: Request,
    front_file: Optional[UploadFile] = File(None, description="Frontal face image"),
    left_file: Optional[UploadFile] = File(None, description="Optional left profile image"),
    right_file: Optional[UploadFile] = File(None, description="Optional right profile image"),
    front_url: Optional[str] = Form(None, description="Frontal face image URL"),
    left_url: Optional[str] = Form(None, description="Optional left face image URL"),
    right_url: Optional[str] = Form(None, description="Optional right face image URL"),
    folder_name: Optional[str] = Form(None, description="Restrict search to this Cloudinary folder/album"),
    top_k: int = Query(20, ge=1, le=30),
    threshold: float = Query(0.60, ge=0.0, le=1.0),
    service: ImageSearchService = Depends(get_image_search_service),
    current_user: dict = Depends(require_current_user),
):
    """
    Search faces using multiple perspective angles (front, left, right).
    Accepts files or Cloudinary URLs. Fuses embeddings into a composite representation.
    """
    target_folder = (folder_name or request.query_params.get("folder_name") or request.query_params.get("folder") or "").strip()

    if target_folder:
        folder_count = sync_get_folder_image_count(target_folder)
        if folder_count == 0:
            available = sync_list_all_indexed_folders()
            avail_msg = f" Available indexed folders: {', '.join(available)}" if available else " No folders are currently indexed."
            logger.warning("[Multi-Angle Search] Folder '%s' is not available. %s", target_folder, avail_msg)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Folder '{target_folder}' is not available or contains no indexed images.{avail_msg}"
            )

    angle_inputs = {
        "front": (front_file, front_url),
        "left": (left_file, left_url),
        "right": (right_file, right_url)
    }
    angle_embeddings = {}

    for angle, (f, u) in angle_inputs.items():
        data = None
        if f is not None:
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

    filter_dict = {"folder": target_folder} if target_folder else None
    logger.info("[Multi-Angle Search] Executing multi-angle search with angles %s (folder_scope='%s', top_k=%d)",
                list(angle_embeddings.keys()), target_folder or "All Folders", top_k)

    matches_data = service.search_multi_angle(
        angle_embeddings=angle_embeddings,
        top_k=top_k,
        threshold=threshold,
        filter_dict=filter_dict
    )

    matches = []
    for m in matches_data:
        img_id = m.get("image_id", "")
        meta = dict(m.get("metadata", {}) or {})
        c_url = m.get("cloud_url") or meta.get("url") or ""
        if not c_url and img_id:
            pid = img_id if img_id.startswith("img_") else f"img_{img_id}"
            fld = target_folder or meta.get("folder") or "general"
            c_url = f"https://res.cloudinary.com/ks28qusz/image/upload/{fld}/{pid}.jpg"
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


