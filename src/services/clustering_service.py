"""
src/services/clustering_service.py — Face clustering and identity albums backed by FAISS & SQLite.
Zero external cloud dependencies: clusters faces with HDBSCAN and persists clusters locally.
"""
import asyncio
from datetime import datetime, timezone
import json
import uuid
from typing import Optional

import numpy as np

from src.core.config import (
    IDX_FACES_ARCFACE,
    CLUSTER_MIN_SAMPLES, CLUSTER_MIN_CLUSTER_SIZE, CLUSTER_EPSILON,
    FACE_SEARCH_TOP_K, CLUSTERING_BLUR_THRESHOLD,
)
from src.common.utils import cld_face_thumb_url
from src.services.local_db import (
    db_save_clusters,
    db_get_clusters,
    db_get_cluster_images,
    db_rename_cluster,
    _get_connection,
)
from src.services.faiss_service import faiss_store


def _pick_representative(c_vecs: np.ndarray, c_meta: list[dict]) -> dict:
    """Select the medoid face vector with highest sharpness."""
    if len(c_vecs) == 1:
        return c_meta[0]

    centroid = np.mean(c_vecs, axis=0)
    centroid /= (np.linalg.norm(centroid) + 1e-8)
    sims = c_vecs @ centroid

    best_score = -1.0
    best_idx = 0
    for i, (sim, meta) in enumerate(zip(sims, c_meta)):
        blur = float(meta.get("blur_score", 50.0))
        blur_factor = min(blur / 100.0, 1.5)
        combined = sim * blur_factor
        if combined > best_score:
            best_score = combined
            best_idx = i

    return c_meta[best_idx]


def _run_hdbscan(matrix: np.ndarray) -> np.ndarray:
    """Run HDBSCAN on cosine distance matrix."""
    import hdbscan
    sim_matrix = matrix @ matrix.T
    dist_matrix = np.clip(1.0 - sim_matrix, 0.0, 2.0).astype(np.float64)
    np.fill_diagonal(dist_matrix, 0.0)

    clusterer = hdbscan.HDBSCAN(
        metric="precomputed",
        min_cluster_size=CLUSTER_MIN_CLUSTER_SIZE,
        min_samples=CLUSTER_MIN_SAMPLES,
        cluster_selection_epsilon=CLUSTER_EPSILON,
        cluster_selection_method="eom",
    )
    clusterer.fit(dist_matrix)
    return clusterer.labels_


async def run_clustering(user_id: str, pc: Optional[object] = None) -> dict:
    """Fetch ArcFace vectors from FAISS, cluster them with HDBSCAN, and save to local SQLite."""
    matches = await asyncio.to_thread(faiss_store.get_all_vectors, IDX_FACES_ARCFACE)

    if not matches:
        return {"status": "empty", "clusters_found": 0, "total_vectors": 0}

    valid_matches = [
        m for m in matches
        if m.get("values") and float(m.get("metadata", {}).get("blur_score", 100.0)) >= CLUSTERING_BLUR_THRESHOLD
    ]

    if len(valid_matches) < CLUSTER_MIN_CLUSTER_SIZE:
        return {
            "status": "not_enough_faces",
            "clusters_found": 0,
            "total_vectors": len(valid_matches),
            "required": CLUSTER_MIN_CLUSTER_SIZE,
        }

    raw_matrix = np.array([m["values"] for m in valid_matches], dtype=np.float32)
    norms = np.linalg.norm(raw_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1e-8
    norm_matrix = raw_matrix / norms

    labels = await asyncio.to_thread(_run_hdbscan, norm_matrix)

    now = datetime.now(timezone.utc).isoformat()
    unique_labels = [lbl for lbl in set(labels) if lbl != -1]

    cluster_rows = []
    vector_rows = []

    for lbl in unique_labels:
        indices = [i for i, l in enumerate(labels) if l == lbl]
        c_vecs = norm_matrix[indices]
        c_meta = [valid_matches[i]["metadata"] for i in indices]
        c_ids = [valid_matches[i]["id"] for i in indices]

        rep = _pick_representative(c_vecs, c_meta)
        cluster_id = str(uuid.uuid4())

        cluster_rows.append({
            "cluster_id": cluster_id,
            "person_name": None,
            "representative_face_url": rep.get("face_crop") or rep.get("url", ""),
            "face_count": len(indices),
            "created_at": now,
            "updated_at": now,
        })

        for vid, meta in zip(c_ids, c_meta):
            vector_rows.append({
                "vector_id": vid,
                "cluster_id": cluster_id,
                "image_url": meta.get("url", ""),
                "folder": meta.get("folder", "uncategorized"),
            })

    await db_save_clusters(user_id, cluster_rows, vector_rows)

    return {
        "status": "success",
        "clusters_found": len(unique_labels),
        "total_vectors": len(valid_matches),
        "noise_faces": int(np.sum(labels == -1)),
    }


async def get_people(user_id: str) -> list[dict]:
    """Returns all identity clusters for a user from local SQLite."""
    return await db_get_clusters(user_id)


async def get_person_images(cluster_id: str, user_id: str) -> list[dict]:
    """Returns all images belonging to a cluster from local SQLite."""
    images = await db_get_cluster_images(user_id, cluster_id)
    seen = set()
    out = []
    for r in images:
        url = r.get("image_url", "")
        if url and url not in seen:
            seen.add(url)
            out.append({
                "url": url,
                "thumb_url": cld_face_thumb_url(url),
                "folder": r.get("folder", ""),
            })
    return out


async def rename_cluster(cluster_id: str, name: str, user_id: str) -> bool:
    """Assigns a human-readable name to a cluster in local SQLite."""
    return await db_rename_cluster(user_id, cluster_id, name)


async def expand_matches_with_cluster(user_id: str, vector_id: str, pc: Optional[object] = None) -> list[dict]:
    """Look up cluster membership for top match and retrieve all cluster photos from local SQLite."""
    def _sync_expand():
        conn = _get_connection()
        try:
            row = conn.execute(
                "SELECT cluster_id FROM face_vector_clusters WHERE user_id = ? AND vector_id = ?",
                (user_id, vector_id),
            ).fetchone()
            if not row:
                return []
            cid = row["cluster_id"]
            rows = conn.execute(
                "SELECT image_url as url, folder, vector_id as id FROM face_vector_clusters WHERE user_id = ? AND cluster_id = ?",
                (user_id, cid),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    return await asyncio.to_thread(_sync_expand)
