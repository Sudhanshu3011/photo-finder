"""
src/api/search.py — Presentation layer (router) for multimodal visual search.
Adheres to MVC architecture: delegates vector querying and fusion to SearchService.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from src.core.security import get_verified_keys, get_user_id
from src.services.local_db import get_or_create_user
from src.common.utils import get_ip
from src.schemas.search import SearchResponse
from src.services.search_service import SearchService
from src.api.dependencies import get_search_service

router = APIRouter()


@router.post(
    "/api/search",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Multimodal image search",
    description="Accepts a query image, extracts face and object embeddings, and returns matching images.",
)
async def search_database(
    request: Request,
    file: UploadFile = File(..., description="Query image file to search for"),
    detect_faces: bool = Form(True, description="Whether to detect faces in query image"),
    user_id: str = Form("", description="Optional user ID"),
    keys: dict = Depends(get_verified_keys),
    search_service: SearchService = Depends(get_search_service),
):
    ip = get_ip(request)
    resolved_uid = await get_or_create_user(user_id)

    if not file or not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No valid query image provided.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded query image is empty.")

    try:
        result = await search_service.search_image(
            file_bytes=file_bytes,
            filename=file.filename,
            detect_faces=detect_faces,
            user_id=resolved_uid,
            keys=keys,
            ip=ip,
        )
        return result
    except RuntimeError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))


@router.post(
    "/api/search-by-face",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Multi-angle face search",
    description="Fuses 1-3 face images (front, left, right profile) server-side for high-recall face identification.",
)
async def search_by_face(
    request: Request,
    front: UploadFile = File(..., description="Frontal face image (required)"),
    left: Optional[UploadFile] = File(None, description="Left profile face image (optional)"),
    right: Optional[UploadFile] = File(None, description="Right profile face image (optional)"),
    user_id: str = Form("", description="Optional user ID"),
    keys: dict = Depends(get_verified_keys),
    search_service: SearchService = Depends(get_search_service),
):
    ip = get_ip(request)
    resolved_uid = await get_or_create_user(user_id)

    if not front or not front.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Frontal face image is required.")

    # Read all present files in parallel
    files_to_read = [("front", front)]
    if left and left.filename:
        files_to_read.append(("left", left))
    if right and right.filename:
        files_to_read.append(("right", right))

    bytes_list = await asyncio.gather(*[f.read() for _, f in files_to_read])
    images_bytes = {angle: b for (angle, _), b in zip(files_to_read, bytes_list) if b}

    if not images_bytes.get("front"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Frontal face image is empty.")

    try:
        result = await search_service.search_by_face_multi_angle(
            images_bytes=images_bytes,
            user_id=resolved_uid,
            keys=keys,
            ip=ip,
        )
        return result
    except RuntimeError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))