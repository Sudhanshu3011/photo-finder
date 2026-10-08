"""
src/modules/search/vector_scorer.py — Multi-Vector Fusion & Threshold Scoring.
Fuses ArcFace and AdaFace similarity signals and applies strict quality thresholds to reject false positives.
"""
from typing import Any, Dict, List, Optional
from src.core.config import (
    IDX_FACES_ARCFACE,
    IDX_FACES_ADAFACE,
    IDX_OBJECTS,
    ARCFACE_WEIGHT,
    ADAFACE_WEIGHT,
    FACE_MATCH_THRESHOLD,
    FUSED_MATCH_THRESHOLD,
    ARCFACE_SOLO_THRESHOLD,
    FACE_SEARCH_TOP_K,
    OBJECT_SEARCH_TOP_K,
    FACE_RESULTS_PER_QUERY_CAP,
    FACE_BLUR_THRESHOLD,
)
from src.core.logging import log


def score_face_matches(
    arc_matches: List[Dict[str, Any]],
    ada_matches: Optional[List[Dict[str, Any]]] = None,
    threshold: float = FACE_MATCH_THRESHOLD,
) -> List[Dict[str, Any]]:
    """
    Combines ArcFace and optional AdaFace search matches and applies threshold filtering.
    """
    ada_by_id = {m.get("id"): m.get("score", 0.0) for m in (ada_matches or [])}
    scored = []

    for match in arc_matches:
        vid = match.get("id", "")
        arc_score = float(match.get("score", 0.0))
        meta = match.get("metadata", {})

        ada_score = ada_by_id.get(vid)
        if ada_score is not None:
            fused = ARCFACE_WEIGHT * arc_score + ADAFACE_WEIGHT * float(ada_score)
        else:
            fused = arc_score

        if fused < threshold:
            continue

        cloud_url = meta.get("url") or meta.get("cloud_url") or match.get("url") or ""
        img_id = meta.get("image_id", vid)
        if not cloud_url and img_id:
            pid = img_id if img_id.startswith("img_") else f"img_{img_id}"
            fld = meta.get("folder") or "general"
            cloud_url = f"https://res.cloudinary.com/ks28qusz/image/upload/{fld}/{pid}.jpg"
            meta["url"] = cloud_url

        scored.append({
            "image_id": img_id,
            "score": round(float(fused), 4),
            "bbox": meta.get("bbox"),
            "person_name": meta.get("person_name"),
            "cluster_id": meta.get("cluster_id"),
            "thumbnail_url": meta.get("thumbnail_url"),
            "cloud_url": cloud_url,
            "metadata": meta,
        })

    return sorted(scored, key=lambda x: x["score"], reverse=True)


def score_object_matches(
    matches: List[Dict[str, Any]],
    threshold: float = 0.25,
) -> List[Dict[str, Any]]:
    """
    Filters and formats object search matches.
    """
    scored = []
    for match in matches:
        score = float(match.get("score", 0.0))
        if score < threshold:
            continue
        meta = match.get("metadata", {})
        cloud_url = meta.get("url") or meta.get("cloud_url") or match.get("url") or ""
        img_id = meta.get("image_id", match.get("id"))
        if not cloud_url and img_id:
            pid = img_id if str(img_id).startswith("img_") else f"img_{img_id}"
            fld = meta.get("folder") or "general"
            cloud_url = f"https://res.cloudinary.com/ks28qusz/image/upload/{fld}/{pid}.jpg"
            meta["url"] = cloud_url

        scored.append({
            "image_id": img_id,
            "score": round(score, 4),
            "thumbnail_url": meta.get("thumbnail_url"),
            "cloud_url": cloud_url,
            "metadata": meta,
        })
    return sorted(scored, key=lambda x: x["score"], reverse=True)


def score_and_fuse_faces(
    vector_engine,
    arcface_vec: List[float],
    adaface_vec: Optional[List[float]] = None,
    filter_dict: Optional[dict] = None,
    top_k: int = FACE_SEARCH_TOP_K,
) -> List[Dict[str, Any]]:
    """
    Queries both ArcFace and AdaFace vector stores and combines scores per image asset.
    """
    arc_matches = vector_engine.search(
        index_name=IDX_FACES_ARCFACE,
        query_vector=arcface_vec,
        top_k=top_k,
        filter_dict=filter_dict,
    )

    has_ada = adaface_vec is not None and any(abs(x) > 1e-6 for x in adaface_vec)
    if has_ada:
        ada_matches = vector_engine.search(
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

        # Basic filter on ArcFace
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
                "face_crop": meta.get("face_crop", ""),
                "folder": meta.get("folder", "uncategorized"),
                "url": url,
            }

    sorted_results = sorted(image_map.values(), key=lambda x: x["score"], reverse=True)
    if len(sorted_results) > FACE_RESULTS_PER_QUERY_CAP:
        sorted_results = sorted_results[:FACE_RESULTS_PER_QUERY_CAP]

    log("INFO", "search.scorer.faces_fused", raw_arc=len(arc_matches), accepted_matches=len(sorted_results))
    return sorted_results


def score_objects(
    vector_engine,
    query_vector: List[float],
    top_k: int = OBJECT_SEARCH_TOP_K,
    filter_dict: Optional[dict] = None,
) -> List[Dict[str, Any]]:
    """Runs cosine similarity query against the general objects index."""
    matches = vector_engine.search(
        index_name=IDX_OBJECTS,
        query_vector=query_vector,
        top_k=top_k,
        filter_dict=filter_dict,
    )
    log("INFO", "search.scorer.objects_searched", results=len(matches))
    return matches

