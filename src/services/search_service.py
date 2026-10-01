"""
src/services/search_service.py — Multi-modal visual and semantic search engine backed by FAISS.
Encapsulates AI embedding queries, local FAISS vector search, multi-index routing, and score fusion.
Zero Pinecone dependency: executes sub-millisecond local similarity searches.
"""
import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.core.config import (
    IDX_FACES, IDX_OBJECTS,
    IDX_FACES_ARCFACE, IDX_FACES_ADAFACE,
    USE_SPLIT_FACE_INDEXES, USE_CLUSTER_AWARE_SEARCH,
    ARCFACE_WEIGHT, ADAFACE_WEIGHT,
    FACE_MATCH_THRESHOLD, FUSED_MATCH_THRESHOLD, ARCFACE_SOLO_THRESHOLD,
    FACE_SEARCH_TOP_K, OBJECT_SEARCH_TOP_K,
    FACE_RESULTS_PER_QUERY_CAP, FACE_BLUR_THRESHOLD,
)
from src.core.logging import log
from src.common.utils import face_ui_score, to_list
from src.services.faiss_service import faiss_store


def search_faces_split(
    store,
    arcface_vec: List[float],
    adaface_vec: Optional[List[float]],
    filter_dict: Optional[dict] = None,
    top_k: int = FACE_SEARCH_TOP_K,
) -> Dict[str, Any]:
    """
    Queries BOTH FAISS face indexes (ArcFace + AdaFace) and score-fuses per vector_id.
    """
    arc_matches = store.search(
        index_name=IDX_FACES_ARCFACE,
        query_vector=arcface_vec,
        top_k=top_k,
        filter_dict=filter_dict,
    )

    has_ada = adaface_vec is not None and any(abs(x) > 1e-6 for x in adaface_vec)
    if has_ada:
        ada_matches = store.search(
            index_name=IDX_FACES_ADAFACE,
            query_vector=adaface_vec,
            top_k=top_k,
            filter_dict=filter_dict,
        )
    else:
        ada_matches = []

    ada_by_id = {m["id"]: m.get("score", 0.0) for m in ada_matches}

    image_map: Dict[str, Any] = {}

    for match in arc_matches:
        vid = match["id"]
        arc_score = match.get("score", 0.0)

        # Primary filter on ArcFace
        if arc_score < FACE_MATCH_THRESHOLD:
            continue

        ada_score = ada_by_id.get(vid, None)
        if ada_score is None:
            if arc_score < ARCFACE_SOLO_THRESHOLD:
                continue
            fused = arc_score
        else:
            fused = ARCFACE_WEIGHT * arc_score + ADAFACE_WEIGHT * ada_score
            if fused < FUSED_MATCH_THRESHOLD:
                continue

        meta = match.get("metadata", {})
        url = meta.get("url")
        if not url:
            continue
        if meta.get("blur_score", 100.0) < FACE_BLUR_THRESHOLD:
            continue

        existing = image_map.get(url)
        if not existing or existing["score"] < fused:
            image_map[url] = {
                "id": vid,
                "score": round(float(fused), 4),
                "fused_score": fused,
                "arcface_score": arc_score,
                "adaface_score": ada_score if ada_score is not None else 0.0,
                "raw_score": arc_score,
                "face_crop": meta.get("face_crop", ""),
                "folder": meta.get("folder", "uncategorized"),
                "url": url,
            }

    if len(image_map) > FACE_RESULTS_PER_QUERY_CAP:
        top = sorted(
            image_map.items(),
            key=lambda kv: kv[1]["score"],
            reverse=True,
        )[:FACE_RESULTS_PER_QUERY_CAP]
        image_map = dict(top)

    return image_map


def search_faces_legacy(
    store,
    vec: List[float],
    filter_dict: Optional[dict] = None,
    top_k: int = FACE_SEARCH_TOP_K,
) -> Dict[str, Any]:
    """Legacy single-index face search for backward compatibility."""
    matches = store.search(
        index_name=IDX_FACES,
        query_vector=vec,
        top_k=top_k,
        filter_dict=filter_dict,
    )
    image_map = {}
    for match in matches:
        raw_score = match.get("score", 0.0)
        if raw_score < 0.35:
            continue
        meta = match.get("metadata", {})
        url = meta.get("url")
        if not url:
            continue
        if url not in image_map or image_map[url]["score"] < raw_score:
            image_map[url] = {
                "id": match["id"],
                "score": round(float(raw_score), 4),
                "face_crop": meta.get("face_crop", ""),
                "folder": meta.get("folder", "uncategorized"),
                "url": url,
            }
    return image_map


def search_objects(
    store,
    vec: List[float],
    top_k: int = OBJECT_SEARCH_TOP_K,
) -> List[Dict[str, Any]]:
    """Query object embeddings from FAISS."""
    matches = store.search(index_name=IDX_OBJECTS, query_vector=vec, top_k=top_k)
    results = []
    for match in matches:
        meta = match.get("metadata", {})
        results.append({
            "url": meta.get("url", ""),
            "score": round(match.get("score", 0.0), 4),
            "raw_score": match.get("score", 0.0),
            "folder": meta.get("folder", "uncategorized"),
        })
    return results


def merge_face_results(groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Dedupe across multiple query faces, keeping the best score per URL."""
    merged = {}
    for group in groups:
        for match in group.get("matches", []):
            url = match["url"]
            if url not in merged or merged[url]["score"] < match["score"]:
                merged[url] = match
    return sorted(merged.values(), key=lambda x: x["score"], reverse=True)


def merge_object_results(nested_results: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Dedupe object results across multiple detections."""
    merged = {}
    for res_list in nested_results:
        for match in res_list:
            url = match["url"]
            if url not in merged or merged[url]["score"] < match["score"]:
                merged[url] = match
    return sorted(merged.values(), key=lambda x: x["score"], reverse=True)


class SearchService:
    """Service orchestrating visual search, vector similarity, and multi-angle face fusion."""

    def __init__(self, ai=None, ai_semaphore=None, vector_store=None):
        self.ai = ai
        self.sem = ai_semaphore
        self.vector_store = vector_store or faiss_store

    async def _query_face_split(self, fv: dict, user_id: Optional[str] = None) -> dict:
        """Parallel query to ArcFace + AdaFace FAISS indexes, then fuse."""
        arcface_vec = to_list(fv["arcface_vector"])
        adaface_vec = to_list(fv.get("adaface_vector")) if fv.get("has_adaface") else None

        image_map = await asyncio.to_thread(
            search_faces_split,
            self.vector_store,
            arcface_vec=arcface_vec,
            adaface_vec=adaface_vec,
            top_k=FACE_SEARCH_TOP_K,
        )

        sorted_matches = sorted(image_map.values(), key=lambda x: x["score"], reverse=True)

        # Cluster-aware search expansion
        if USE_CLUSTER_AWARE_SEARCH and user_id and sorted_matches:
            top_hit = sorted_matches[0]
            if top_hit.get("score", 0) >= 0.70:
                try:
                    from src.services.clustering_service import expand_matches_with_cluster
                    cluster_images = await expand_matches_with_cluster(
                        user_id, top_hit["id"]
                    )
                    existing_urls = {m["url"] for m in sorted_matches}
                    for ci in cluster_images:
                        if ci["url"] not in existing_urls:
                            sorted_matches.append({
                                "id": ci["id"],
                                "score": round(top_hit["score"] * 0.95, 4),
                                "url": ci["url"],
                                "folder": ci.get("folder", ""),
                                "cluster_expanded": True,
                            })
                            existing_urls.add(ci["url"])
                except Exception as e:
                    log("WARNING", "search.cluster_expansion_failed", error=str(e))

        return {
            "face_idx": fv["face_idx"],
            "query_crop": fv.get("face_crop", ""),
            "matches": sorted_matches,
        }

    async def _query_face_legacy(self, fv: dict) -> dict:
        """Legacy single-index face query."""
        vec = to_list(fv["vector"])
        image_map = await asyncio.to_thread(
            search_faces_legacy, self.vector_store, vec
        )
        return {
            "face_idx": fv["face_idx"],
            "query_crop": fv.get("face_crop", ""),
            "matches": sorted(image_map.values(), key=lambda x: x["score"], reverse=True),
        }

    async def search_image(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        detect_faces: bool,
        user_id: str,
        keys: dict,
        ip: str = "127.0.0.1",
    ) -> dict:
        """Run full multimodal search on an uploaded query image."""
        start = time.perf_counter()

        log("INFO", "search.start",
            user_id=user_id or "anonymous", ip=ip,
            filename=filename, detect_faces=detect_faces)

        # Run query inference under semaphore
        async with self.sem:
            vectors = await self.ai.process_image_bytes_async(
                file_bytes, detect_faces=detect_faces
            )

        inference_ms = round((time.perf_counter() - start) * 1000)
        face_vectors = [v for v in vectors if v["type"] == "face"]
        object_vectors = [v for v in vectors if v["type"] == "object"]

        log("INFO", "search.inference_done",
            user_id=user_id or "anonymous", ip=ip,
            face_vecs=len(face_vectors), obj_vecs=len(object_vectors),
            inference_ms=inference_ms)

        if detect_faces and face_vectors:
            # Query face lanes
            if USE_SPLIT_FACE_INDEXES:
                face_tasks = [
                    self._query_face_split(fv, user_id=user_id)
                    for fv in face_vectors
                ]
            else:
                face_tasks = [self._query_face_legacy(fv) for fv in face_vectors]

            async def _query_obj_single(ov):
                vec = to_list(ov["vector"])
                return await asyncio.to_thread(search_objects, self.vector_store, vec)

            obj_tasks = [_query_obj_single(ov) for ov in object_vectors]
            all_results = await asyncio.gather(*face_tasks, *obj_tasks)

            raw_groups = list(all_results[:len(face_tasks)])
            obj_nested = list(all_results[len(face_tasks):])

            merged_face = merge_face_results(raw_groups)
            merged_objects = merge_object_results(obj_nested)
            face_groups = [g for g in raw_groups if g.get("matches")]

            duration_ms = round((time.perf_counter() - start) * 1000)
            log("INFO", "search.complete",
                user_id=user_id or "anonymous", ip=ip,
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

        # Object-only search
        if not object_vectors:
            return {"mode": "none", "results": [], "face_groups": [], "object_results": []}

        async def _query_obj(ov):
            vec = to_list(ov["vector"])
            return await asyncio.to_thread(search_objects, self.vector_store, vec)

        nested = await asyncio.gather(*[_query_obj(ov) for ov in object_vectors])
        final_objects = merge_object_results(nested)

        duration_ms = round((time.perf_counter() - start) * 1000)
        log("INFO", "search.complete",
            user_id=user_id or "anonymous", ip=ip,
            lanes=["object"], results=len(final_objects), duration_ms=duration_ms)

        return {
            "mode": "object",
            "results": [],
            "face_groups": [],
            "object_results": final_objects,
        }

    async def search_by_face_multi_angle(
        self,
        *,
        images_bytes: Dict[str, bytes],
        user_id: str,
        keys: dict,
        ip: str = "127.0.0.1",
    ) -> dict:
        """Fuses multiple face angles server-side and performs single FAISS search."""
        start = time.perf_counter()

        # Run inference in parallel across angles
        async def _infer(angle: str, b: bytes):
            async with self.sem:
                vecs = await self.ai.process_image_bytes_async(b, detect_faces=True)
                return angle, [v for v in vecs if v["type"] == "face"]

        infer_tasks = [_infer(angle, b) for angle, b in images_bytes.items()]
        results = await asyncio.gather(*infer_tasks)

        face_vectors_by_angle = {angle: fvs for angle, fvs in results if fvs}
        if not face_vectors_by_angle:
            return {"mode": "face", "face_groups": [], "results": [], "object_results": []}

        arcface_vectors = []
        adaface_vectors = []
        det_scores = []
        front_face_crop = ""

        for angle in ["front", "left", "right"]:
            if angle in face_vectors_by_angle:
                fvs = face_vectors_by_angle[angle]
                best_face = max(fvs, key=lambda f: float(f.get("det_score", 0.0)))
                arcface_vectors.append(best_face["arcface_vector"])
                det_scores.append(float(best_face.get("det_score", 1.0)))
                if angle == "front" or not front_face_crop:
                    front_face_crop = best_face.get("face_crop", "")
                if best_face.get("has_adaface") and best_face.get("adaface_vector"):
                    adaface_vectors.append(best_face["adaface_vector"])

        fused_arcface = np.sum(arcface_vectors, axis=0)
        fused_arcface = fused_arcface / (np.linalg.norm(fused_arcface) + 1e-7)

        fused_adaface = None
        has_adaface = False
        if adaface_vectors:
            fused_adaface = np.sum(adaface_vectors, axis=0)
            fused_adaface = fused_adaface / (np.linalg.norm(fused_adaface) + 1e-7)
            has_adaface = True

        fv = {
            "face_idx": 0,
            "det_score": float(np.mean(det_scores)),
            "arcface_vector": fused_arcface.tolist(),
            "has_adaface": has_adaface,
            "adaface_vector": fused_adaface.tolist() if has_adaface else None,
            "bbox": [0, 0, 0, 0],
            "face_width_px": 0,
            "face_crop": front_face_crop,
        }

        if USE_SPLIT_FACE_INDEXES:
            face_group = await self._query_face_split(fv, user_id=user_id)
        else:
            face_group = await self._query_face_legacy(fv)

        matches = face_group.get("matches", [])
        return {
            "mode": "face",
            "face_groups": [face_group] if matches else [],
            "results": matches,
            "object_results": [],
        }
