import time
from typing import Any, Dict, List

import cloudinary
import cloudinary.uploader
import cloudinary.api
from pinecone import Pinecone, ServerlessSpec

from src.core.config import (
    IDX_FACES, IDX_OBJECTS,
    IDX_FACES_ARCFACE, IDX_FACES_ADAFACE,
    USE_SPLIT_FACE_INDEXES,
    ARCFACE_WEIGHT, ADAFACE_WEIGHT,
    FACE_MATCH_THRESHOLD, FUSED_MATCH_THRESHOLD, ARCFACE_SOLO_THRESHOLD,
    FACE_SEARCH_TOP_K, OBJECT_SEARCH_TOP_K,
    FACE_RESULTS_PER_QUERY_CAP,
    FACE_DIM, ADAFACE_DIM, FUSED_FACE_DIM,
    FACE_BLUR_THRESHOLD,
)


# ──────────────────────────────────────────────────────────────
# Pinecone client pool
# ──────────────────────────────────────────────────────────────
class PineconePool:
    def __init__(self):
        self._clients = {}

    def get(self, api_key: str) -> Pinecone:
        if api_key not in self._clients:
            self._clients[api_key] = Pinecone(api_key=api_key)
        return self._clients[api_key]


pinecone_pool = PineconePool()


# ──────────────────────────────────────────────────────────────
# Cloudinary helpers (unchanged from Phase 1)
# ──────────────────────────────────────────────────────────────
def _set_cld_config(creds: dict):
    cloudinary.config(
        cloud_name=creds.get("cloud_name"),
        api_key=creds.get("api_key"),
        api_secret=creds.get("api_secret"),
        secure=True,
    )


def cld_ping(creds: dict):
    _set_cld_config(creds)
    cloudinary.api.ping()


def cld_upload(file_obj, folder: str, creds: dict) -> dict:
    _set_cld_config(creds)
    return cloudinary.uploader.upload(file_obj, folder=folder)


def cld_root_folders(creds: dict) -> dict:
    _set_cld_config(creds)
    return cloudinary.api.root_folders()


def cld_list_folder_images(folder: str, creds: dict, cursor: str = None, page_size: int = 100) -> dict:
    _set_cld_config(creds)
    kwargs = {"type": "upload", "prefix": f"{folder}/", "max_results": page_size}
    if cursor:
        kwargs["next_cursor"] = cursor
    return cloudinary.api.resources(**kwargs)


def cld_delete_resource(public_id: str, creds: dict):
    _set_cld_config(creds)
    cloudinary.uploader.destroy(public_id)


def cld_delete_folder_resources(folder: str, creds: dict):
    _set_cld_config(creds)
    cloudinary.api.delete_resources_by_prefix(f"{folder}/")


def cld_remove_folder(folder: str, creds: dict):
    _set_cld_config(creds)
    try:
        cloudinary.api.delete_folder(folder)
    except Exception:
        pass


def cld_delete_all_paginated(creds: dict) -> int:
    _set_cld_config(creds)
    deleted = 0
    cursor = None
    while True:
        kwargs = {"type": "upload", "max_results": 500}
        if cursor:
            kwargs["next_cursor"] = cursor
        res = cloudinary.api.resources(**kwargs)
        resources = res.get("resources", [])
        if not resources:
            break
        pids = [r["public_id"] for r in resources]
        cloudinary.api.delete_resources(pids)
        deleted += len(pids)
        cursor = res.get("next_cursor")
        if not cursor:
            break
    return deleted


# ──────────────────────────────────────────────────────────────
# Index management
# ──────────────────────────────────────────────────────────────
def ensure_indexes(pc: Pinecone) -> List[str]:
    """
    Ensures all required indexes exist.
    - Objects index: 1536d (unchanged)
    - Legacy faces index: 1024d (kept for backward compat)
    - New split indexes: 512d each (ArcFace + AdaFace separately)
    """
    created = []
    existing = {idx.name for idx in pc.list_indexes()}

    index_specs = [
        (IDX_OBJECTS, 1536),
        (IDX_FACES, FUSED_FACE_DIM),  # legacy — only created on first run if missing
    ]

    if USE_SPLIT_FACE_INDEXES:
        index_specs.extend([
            (IDX_FACES_ARCFACE, FACE_DIM),
            (IDX_FACES_ADAFACE, ADAFACE_DIM),
        ])

    for name, dim in index_specs:
        if name not in existing:
            pc.create_index(
                name=name,
                dimension=dim,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )
            created.append(name)
    return created


def delete_and_recreate_indexes(pc: Pinecone):
    """Used by /api/reset-database. Now also resets split indexes."""
    existing = {idx.name for idx in pc.list_indexes()}
    targets = [IDX_FACES, IDX_OBJECTS]
    if USE_SPLIT_FACE_INDEXES:
        targets.extend([IDX_FACES_ARCFACE, IDX_FACES_ADAFACE])
    for name in targets:
        if name in existing:
            pc.delete_index(name)
    time.sleep(5)
    ensure_indexes(pc)


# ──────────────────────────────────────────────────────────────
# LEGACY face search (for backward compat / fallback)
# ──────────────────────────────────────────────────────────────
def search_faces(idx, vec: List[float], det_score: float, filter_dict: dict = None) -> Dict[str, Any]:
    query_kwargs = {"vector": vec, "top_k": FACE_SEARCH_TOP_K, "include_metadata": True}
    if filter_dict:
        query_kwargs["filter"] = filter_dict
    res = idx.query(**query_kwargs)
    image_map = {}
    LEGACY_THRESHOLD = 0.45  # on old fused 1024-d vector

    for match in res.get("matches", []):
        raw_score = match.get("score", 0)
        if raw_score < LEGACY_THRESHOLD:
            continue
        meta = match.get("metadata", {})
        url = meta.get("url")
        if not url:
            continue
        if url not in image_map or image_map[url]["raw_score"] < raw_score:
            image_map[url] = {
                "raw_score": raw_score,
                "face_crop": meta.get("face_crop", ""),
                "folder": meta.get("folder", "uncategorized"),
            }
    return image_map


# ──────────────────────────────────────────────────────────────
# PHASE 2: Split-index face search with score fusion
# ──────────────────────────────────────────────────────────────
def search_faces_split(
    idx_arcface, idx_adaface,
    arcface_vec: List[float], adaface_vec: List[float],
    filter_dict: dict = None,
) -> Dict[str, Any]:
    """
    Queries BOTH face indexes, fuses scores per vector_id, returns a map
    keyed by url with the best fused score across all query augmentations.

    Score fusion formula:
        fused_score = ARCFACE_WEIGHT * arcface_cos + ADAFACE_WEIGHT * adaface_cos

    When a vector exists in only one index (e.g. AdaFace failed on upload),
    we scale the single-index score by its weight + max possible from the
    other side (treat missing as average of its distribution = ~0.15).
    """
    query_kwargs_base = {"top_k": FACE_SEARCH_TOP_K, "include_metadata": True}
    if filter_dict:
        query_kwargs_base["filter"] = filter_dict

    # Query both indexes in parallel (caller uses asyncio.gather)
    arc_res = idx_arcface.query(vector=arcface_vec, **query_kwargs_base)

    # Only query AdaFace if we have a valid vector (not all zeros)
    has_ada = adaface_vec is not None and any(abs(x) > 1e-6 for x in adaface_vec)
    if has_ada:
        ada_res = idx_adaface.query(vector=adaface_vec, **query_kwargs_base)
    else:
        ada_res = {"matches": []}

    # Index AdaFace results by vector_id
    ada_by_id = {
        m["id"]: m.get("score", 0.0)
        for m in ada_res.get("matches", [])
    }

    # Index AdaFace metadata by vector_id (in case a vector_id is only in AdaFace)
    ada_meta_by_id = {
        m["id"]: m.get("metadata", {})
        for m in ada_res.get("matches", [])
    }

    image_map: Dict[str, Any] = {}
    seen_vector_ids = set()

    # ── Pass 1: ArcFace matches (the primary signal) ─────────────
    for match in arc_res.get("matches", []):
        vid = match["id"]
        seen_vector_ids.add(vid)
        arc_score = match.get("score", 0.0)

        # Hard floor: if ArcFace says no, it's no. This kills imposters.
        if arc_score < FACE_MATCH_THRESHOLD:
            continue

        ada_score = ada_by_id.get(vid, None)
        if ada_score is None:
            # No AdaFace confirmation — apply stricter solo threshold.
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
        if not existing or existing["fused_score"] < fused:
            image_map[url] = {
                "fused_score": fused,
                "arcface_score": arc_score,
                "adaface_score": ada_score if ada_score is not None else 0.0,
                "raw_score": arc_score,  # for UI back-compat
                "face_crop": meta.get("face_crop", ""),
                "folder": meta.get("folder", "uncategorized"),
                "vector_id": vid,
            }

    # Cap at most N results per query face
    if len(image_map) > FACE_RESULTS_PER_QUERY_CAP:
        top = sorted(
            image_map.items(),
            key=lambda kv: kv[1]["fused_score"],
            reverse=True,
        )[:FACE_RESULTS_PER_QUERY_CAP]
        image_map = dict(top)

    return image_map


# ──────────────────────────────────────────────────────────────
# Object search (unchanged)
# ──────────────────────────────────────────────────────────────
def search_objects(idx, vec: List[float]) -> List[Dict[str, Any]]:
    res = idx.query(vector=vec, top_k=OBJECT_SEARCH_TOP_K, include_metadata=True)
    results = []
    for match in res.get("matches", []):
        meta = match.get("metadata", {})
        results.append({
            "url": meta.get("url", ""),
            "score": round(match.get("score", 0), 4),
            "raw_score": match.get("score", 0),
            "folder": meta.get("folder", "uncategorized"),
        })
    return results


# ──────────────────────────────────────────────────────────────
# Result merging
# ──────────────────────────────────────────────────────────────
def merge_face_results(groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Dedupe across multiple query faces (or augmentations), keep best score per URL."""
    merged = {}
    for group in groups:
        for match in group.get("matches", []):
            url = match["url"]
            if url not in merged or merged[url]["score"] < match["score"]:
                merged[url] = match
    return sorted(merged.values(), key=lambda x: x["score"], reverse=True)


def merge_object_results(nested_results: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    merged = {}
    for res_list in nested_results:
        for match in res_list:
            url = match["url"]
            if url not in merged or merged[url]["score"] < match["score"]:
                merged[url] = match
    return sorted(merged.values(), key=lambda x: x["score"], reverse=True)