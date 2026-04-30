import asyncio
import hashlib
import time
import traceback
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, Depends

from src.core.config import (
    DEFAULT_PINECONE_KEY, IDX_FACES, IDX_OBJECTS,
    IDX_FACES_ARCFACE, IDX_FACES_ADAFACE,
    USE_SPLIT_FACE_INDEXES, USE_CLUSTER_AWARE_SEARCH,
)
from src.core.security import get_verified_keys
from src.services.db_client import (
    merge_face_results, merge_object_results,
    pinecone_pool, search_faces, search_faces_split, search_objects,
    ensure_indexes,
)
from src.core.logging import log
from src.common.utils import face_ui_score, get_ip, is_default_key, to_list

router = APIRouter()


@router.post("/api/search")
async def search_database(
    request: Request,
    file: UploadFile = File(...),
    detect_faces: bool = Form(True),
    user_id: str = Form(""),
    keys: dict = Depends(get_verified_keys),
):
    ip = get_ip(request)
    start = time.perf_counter()
    mode = "guest" if is_default_key(keys["pinecone_key"], DEFAULT_PINECONE_KEY) else "personal"

    log("INFO", "search.start",
        user_id=user_id or "anonymous", ip=ip, mode=mode,
        filename=file.filename, detect_faces=detect_faces)

    try:
        file_bytes = await file.read()
        ai_manager = request.app.state.ai
        sem = request.app.state.ai_semaphore

        # Run query inference
        async with sem:
            vectors = await ai_manager.process_image_bytes_async(
                file_bytes, detect_faces=detect_faces
            )

        inference_ms = round((time.perf_counter() - start) * 1000)
        face_vectors = [v for v in vectors if v["type"] == "face"]
        object_vectors = [v for v in vectors if v["type"] == "object"]

        log("INFO", "search.inference_done",
            user_id=user_id or "anonymous", ip=ip, mode=mode,
            face_vecs=len(face_vectors), obj_vecs=len(object_vectors),
            inference_ms=inference_ms)

        pc = pinecone_pool.get(keys["pinecone_key"])
        # Stable opaque user identity derived from the Pinecone key — matches
        # what clustering.py writes to Supabase so cluster lookups work.
        cluster_uid = hashlib.sha256(keys["pinecone_key"].encode()).hexdigest()[:16]

        # Auto-create indexes if missing. Self-heals the case where user
        # hasn't triggered verify-keys yet.
        try:
            created = await asyncio.to_thread(ensure_indexes, pc)
            if created:
                log("INFO", "search.indexes_auto_created",
                    user_id=user_id or "anonymous", ip=ip, created=created)
                await asyncio.sleep(8)
        except Exception as e:
            log("ERROR", "search.ensure_indexes_failed",
                user_id=user_id or "anonymous", ip=ip, error=str(e))

        idx_obj = pc.Index(IDX_OBJECTS)

        if USE_SPLIT_FACE_INDEXES:
            idx_arcface = pc.Index(IDX_FACES_ARCFACE)
            idx_adaface = pc.Index(IDX_FACES_ADAFACE)
            idx_face_legacy = None
        else:
            idx_face_legacy = pc.Index(IDX_FACES)
            idx_arcface = None
            idx_adaface = None

        if detect_faces and face_vectors:
            return await _run_face_search(
                face_vectors, object_vectors,
                idx_arcface, idx_adaface, idx_face_legacy, idx_obj,
                start, user_id, ip, mode,
                pc=pc, cluster_uid=cluster_uid,
            )
        return await _run_object_search(
            object_vectors, idx_obj, start, user_id, ip, mode
        )

    except HTTPException:
        raise
    except Exception as e:
        log("ERROR", "search.error",
            user_id=user_id or "anonymous", ip=ip, mode=mode,
            error=str(e), traceback=traceback.format_exc()[-800:])
        raise HTTPException(500, str(e))


async def _query_face_split(fv, idx_arcface, idx_adaface, pc=None, cluster_uid=None):
    """Parallel query to ArcFace + AdaFace indexes, then fuse.
    When USE_CLUSTER_AWARE_SEARCH is on, expands results to include every
    image in the matched person clusters for near-100% recall."""
    arcface_vec = to_list(fv["arcface_vector"])
    adaface_vec = to_list(fv.get("adaface_vector")) if fv.get("has_adaface") else None

    try:
        image_map = await asyncio.to_thread(
            search_faces_split,
            idx_arcface, idx_adaface,
            arcface_vec, adaface_vec,
        )
    except Exception as e:
        if "404" in str(e):
            raise HTTPException(
                404,
                "Face indexes not found. Go to Settings → Verify & Save to create them."
            )
        raise

    # Only expand clusters for high-confidence matches (fused_score >= 0.50).
    # A borderline match at 0.40 could be a different person; cluster expansion
    # would then pull in an entire wrong identity — exactly what we want to avoid.
    CLUSTER_EXPAND_MIN_SCORE = 0.50
    high_confidence = {
        url: d for url, d in image_map.items()
        if d.get("fused_score", 0.0) >= CLUSTER_EXPAND_MIN_SCORE
    }
    if USE_CLUSTER_AWARE_SEARCH and high_confidence and pc is not None and cluster_uid:
        from src.services.clustering import search_cluster_aware
        image_map = await search_cluster_aware(pc, high_confidence, cluster_uid)

    return _format_face_group(fv, image_map, scoring="fused")


async def _query_face_legacy(fv, idx_face):
    """Legacy single-index query for pre-Phase-2 data."""
    vec = to_list(fv["vector"])
    det_score = fv.get("det_score", 1.0)
    try:
        image_map = await asyncio.to_thread(search_faces, idx_face, vec, det_score)
    except Exception as e:
        if "404" in str(e):
            raise HTTPException(404, "Pinecone index not found.")
        raise
    return _format_face_group(fv, image_map, scoring="legacy")


def _format_face_group(fv, image_map, scoring: str):
    """Shape the response the same way regardless of scoring backend."""
    matches = []
    for url, d in image_map.items():
        if scoring == "fused":
            display_score = face_ui_score(d["fused_score"], mode="fused")
            raw_score = round(d["fused_score"], 4)
        else:
            display_score = face_ui_score(d["raw_score"], mode="legacy")
            raw_score = round(d["raw_score"], 4)

        matches.append({
            "url": url,
            "score": display_score,
            "raw_score": raw_score,
            "arcface_score": round(d.get("arcface_score", 0), 4),
            "adaface_score": round(d.get("adaface_score", 0), 4),
            "face_crop": d["face_crop"],
            "folder": d["folder"],
            "caption": "👤 Verified Identity",
        })

    matches.sort(key=lambda x: x["score"], reverse=True)

    return {
        "query_face_idx": fv.get("face_idx", 0),
        "query_face_crop": fv.get("face_crop", ""),
        "query_bbox": fv.get("bbox", []),
        "det_score": fv.get("det_score", 1.0),
        "face_width_px": fv.get("face_width_px", 0),
        "matches": matches,
    }


async def _run_face_search(
    face_vectors, object_vectors,
    idx_arcface, idx_adaface, idx_face_legacy, idx_obj,
    start, user_id, ip, mode,
    pc=None, cluster_uid=None,
) -> dict:
    # Build face query tasks
    if USE_SPLIT_FACE_INDEXES:
        face_tasks = [
            _query_face_split(fv, idx_arcface, idx_adaface, pc=pc, cluster_uid=cluster_uid)
            for fv in face_vectors
        ]
    else:
        face_tasks = [_query_face_legacy(fv, idx_face_legacy) for fv in face_vectors]

    # Object queries run in parallel with face queries
    async def _query_obj_single(ov):
        vec = to_list(ov["vector"])
        try:
            return await asyncio.to_thread(search_objects, idx_obj, vec)
        except Exception as e:
            if "404" in str(e):
                raise HTTPException(404, "Pinecone index not found.")
            raise

    obj_tasks = [_query_obj_single(ov) for ov in object_vectors]
    all_results = await asyncio.gather(*face_tasks, *obj_tasks)

    raw_groups = list(all_results[:len(face_tasks)])
    obj_nested = list(all_results[len(face_tasks):])

    merged_face = merge_face_results(raw_groups)
    merged_objects = merge_object_results(obj_nested)
    face_groups = [g for g in raw_groups if g.get("matches")]

    duration_ms = round((time.perf_counter() - start) * 1000)
    log("INFO", "search.complete",
        user_id=user_id or "anonymous", ip=ip, mode=mode,
        lanes=["face", "object"],
        face_groups=len(face_groups),
        face_results=len(merged_face),
        object_results=len(merged_objects),
        duration_ms=duration_ms,
        index_mode="split" if USE_SPLIT_FACE_INDEXES else "legacy")

    return {
        "mode": "face",
        "face_groups": face_groups,
        "results": merged_face,
        "object_results": merged_objects,
    }


async def _run_object_search(object_vectors, idx_obj, start, user_id, ip, mode) -> dict:
    if not object_vectors:
        return {"mode": "object", "results": [], "face_groups": []}

    async def _query_obj(ov):
        vec = to_list(ov["vector"])
        try:
            return await asyncio.to_thread(search_objects, idx_obj, vec)
        except Exception as e:
            if "404" in str(e):
                raise HTTPException(404, "Pinecone index not found.")
            raise

    nested = await asyncio.gather(*[_query_obj(ov) for ov in object_vectors])
    final = merge_object_results(nested)

    duration_ms = round((time.perf_counter() - start) * 1000)
    log("INFO", "search.complete",
        user_id=user_id or "anonymous", ip=ip, mode=mode,
        lanes=["object"], results=len(final), duration_ms=duration_ms)

    return {"mode": "object", "results": final, "face_groups": []}


@router.post("/api/search-by-face")
async def search_by_face(
    request: Request,
    front: UploadFile = File(...),
    left: Optional[UploadFile] = File(None),
    right: Optional[UploadFile] = File(None),
    user_id: str = Form(""),
    keys: dict = Depends(get_verified_keys),
):
    """
    Multi-angle face search: accepts 1-3 face images, fuses embeddings server-side,
    performs single Pinecone query. 3x faster + lower quota usage vs 3 sequential queries.
    """
    import numpy as np

    ip = get_ip(request)
    start = time.perf_counter()
    mode = "guest" if is_default_key(keys["pinecone_key"], DEFAULT_PINECONE_KEY) else "personal"

    log("INFO", "search.search_by_face.start",
        user_id=user_id or "anonymous", ip=ip, mode=mode)

    try:
        ai_manager = request.app.state.ai
        sem = request.app.state.ai_semaphore

        log("DEBUG", "search.search_by_face.received_files",
            user_id=user_id or "anonymous", ip=ip,
            front=bool(front), left=bool(left), right=bool(right))

        # Read all image bytes in parallel
        images = {}
        for name, file in [("front", front), ("left", left), ("right", right)]:
            if file:
                file_bytes = await file.read()
                images[name] = file_bytes
                log("DEBUG", "search.search_by_face.file_read",
                    user_id=user_id or "anonymous", ip=ip,
                    angle=name, size_bytes=len(file_bytes))

        if not images:
            log("ERROR", "search.search_by_face.no_images",
                user_id=user_id or "anonymous", ip=ip)
            raise HTTPException(400, "At least front image required")

        # Process all images in parallel
        async def process_img(name, data):
            async with sem:
                return name, await ai_manager.process_image_bytes_async(
                    data, detect_faces=True
                )

        results = await asyncio.gather(
            *[process_img(name, data) for name, data in images.items()],
            return_exceptions=True
        )

        # Extract face vectors from successful results
        face_vectors_by_angle = {}
        for result in results:
            if isinstance(result, Exception):
                log("WARN", "search.search_by_face.process_error",
                    user_id=user_id or "anonymous", ip=ip,
                    error=str(result), traceback=traceback.format_exc()[-500:])
                continue

            name, vectors = result
            face_vecs = [v for v in vectors if v["type"] == "face"]
            if face_vecs:
                face_vectors_by_angle[name] = face_vecs[0]
                log("DEBUG", "search.search_by_face.face_detected",
                    user_id=user_id or "anonymous", ip=ip,
                    angle=name, det_score=face_vecs[0].get("det_score", 0))
            else:
                log("WARN", "search.search_by_face.no_face_in_angle",
                    user_id=user_id or "anonymous", ip=ip,
                    angle=name, vectors_count=len(vectors) if vectors else 0)

        if not face_vectors_by_angle:
            log("ERROR", "search.search_by_face.no_faces_detected",
                user_id=user_id or "anonymous", ip=ip)
            raise HTTPException(400, "No face detected in provided images")

        # Fuse embeddings: front weighted higher
        weights = {"front": 0.5, "left": 0.25, "right": 0.25}
        arcface_vectors = []
        adaface_vectors = []
        det_scores = []

        for angle, vec in face_vectors_by_angle.items():
            w = weights.get(angle, 0)
            if w > 0:
                arcface_vectors.append(np.array(to_list(vec["arcface_vector"])) * w)
                det_scores.append(vec.get("det_score", 1.0))

                if vec.get("has_adaface") and vec.get("adaface_vector") is not None:
                    adaface_vectors.append(np.array(to_list(vec["adaface_vector"])) * w)

        if not arcface_vectors:
            raise HTTPException(400, "Could not fuse face embeddings")

        # Fuse and normalize
        fused_arcface = np.sum(arcface_vectors, axis=0)
        fused_arcface = fused_arcface / (np.linalg.norm(fused_arcface) + 1e-7)

        fused_adaface = None
        has_adaface = False
        if adaface_vectors and len(adaface_vectors) > 0:
            fused_adaface = np.sum(adaface_vectors, axis=0)
            fused_adaface = fused_adaface / (np.linalg.norm(fused_adaface) + 1e-7)
            has_adaface = True

        # Build synthetic face vector dict for query
        fv = {
            "face_idx": 0,
            "det_score": float(np.mean(det_scores)),
            "arcface_vector": fused_arcface.tolist(),
            "has_adaface": has_adaface,
            "adaface_vector": fused_adaface.tolist() if has_adaface else None,
            "bbox": [0, 0, 0, 0],
            "face_width_px": 0,
            "face_crop": "",
        }

        inference_ms = round((time.perf_counter() - start) * 1000)
        log("INFO", "search.search_by_face.fused",
            user_id=user_id or "anonymous", ip=ip,
            angles=list(face_vectors_by_angle.keys()),
            inference_ms=inference_ms)

        pc = pinecone_pool.get(keys["pinecone_key"])
        cluster_uid = hashlib.sha256(keys["pinecone_key"].encode()).hexdigest()[:16]

        # Ensure indexes exist
        try:
            created = await asyncio.to_thread(ensure_indexes, pc)
            if created:
                log("INFO", "search.indexes_auto_created",
                    user_id=user_id or "anonymous", ip=ip, created=created)
                await asyncio.sleep(8)
        except Exception as e:
            log("ERROR", "search.ensure_indexes_failed",
                user_id=user_id or "anonymous", ip=ip, error=str(e))

        # Setup indexes
        if USE_SPLIT_FACE_INDEXES:
            idx_arcface = pc.Index(IDX_FACES_ARCFACE)
            idx_adaface = pc.Index(IDX_FACES_ADAFACE)
            idx_face_legacy = None
        else:
            idx_face_legacy = pc.Index(IDX_FACES)
            idx_arcface = None
            idx_adaface = None

        # Query with fused vector
        if USE_SPLIT_FACE_INDEXES:
            face_group = await _query_face_split(fv, idx_arcface, idx_adaface, pc=pc, cluster_uid=cluster_uid)
        else:
            face_group = await _query_face_legacy(fv, idx_face_legacy)

        duration_ms = round((time.perf_counter() - start) * 1000)
        log("INFO", "search.search_by_face.complete",
            user_id=user_id or "anonymous", ip=ip,
            results=len(face_group.get("matches", [])),
            duration_ms=duration_ms)

        return {
            "mode": "face",
            "face_groups": [face_group] if face_group.get("matches") else [],
            "results": [],
            "object_results": [],
        }

    except HTTPException:
        raise
    except Exception as e:
        log("ERROR", "search.search_by_face.error",
            user_id=user_id or "anonymous", ip=ip, mode=mode,
            error=str(e), traceback=traceback.format_exc()[-800:])
        raise HTTPException(500, str(e))