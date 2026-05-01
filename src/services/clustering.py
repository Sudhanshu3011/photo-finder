"""
src/services/clustering.py — Phase 3: HDBSCAN face clustering (People View)

Clusters all face vectors in the faces-arcface Pinecone index using HDBSCAN,
then stores cluster assignments in Supabase (face_clusters table).

Algorithm choice:
  - HDBSCAN on ArcFace 512-d vectors (euclidean after L2 normalisation)
  - min_cluster_size=3, min_samples=3, cluster_selection_epsilon=0.35
  - Noise points (label=-1) are left unclustered — not forced into clusters
  - Representative face = the vector closest to the cluster centroid

Pinecone fetch strategy:
  - Pinecone free tier has no "list all vectors" endpoint
  - We use a dummy query with random vectors + large top_k to page through
    vectors. This is imperfect but works within free-tier constraints.
  - Production alternative: store vector_ids in Supabase on upload (Phase 4)

Entry points:
  run_clustering(pc, user_id, keys) — full re-cluster, called by API endpoint
  get_people(user_id) — read cluster list from Supabase
  get_person_images(cluster_id, user_id) — images for one cluster
  rename_cluster(cluster_id, name, user_id) — label "Mom", "John", etc.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import numpy as np

from src.core.config import (
    IDX_FACES_ARCFACE,
    SUPABASE_URL, SUPABASE_SERVICE_KEY,
    CLUSTER_MIN_SAMPLES, CLUSTER_MIN_CLUSTER_SIZE, CLUSTER_EPSILON,
    FACE_SEARCH_TOP_K, CLUSTERING_BLUR_THRESHOLD,
)
from src.common.utils import cld_face_thumb_url


# ──────────────────────────────────────────────────────────────
# Supabase helpers
# ──────────────────────────────────────────────────────────────
def _hdr() -> dict:
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


async def _supa_upsert(table: str, rows: list[dict]) -> None:
    if not SUPABASE_URL or not rows:
        return
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {**_hdr(), "Prefer": "resolution=merge-duplicates,return=minimal"}
    async with aiohttp.ClientSession() as s:
        await s.post(url, headers=headers, json=rows)


async def _supa_select(table: str, filters: str = "") -> list[dict]:
    if not SUPABASE_URL:
        return []
    url = f"{SUPABASE_URL}/rest/v1/{table}?{filters}"
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers=_hdr()) as r:
            if r.status == 200:
                return await r.json()
    return []


async def _supa_patch(table: str, filters: str, patch: dict) -> None:
    if not SUPABASE_URL:
        return
    url = f"{SUPABASE_URL}/rest/v1/{table}?{filters}"
    async with aiohttp.ClientSession() as s:
        await s.patch(url, headers=_hdr(), json=patch)


async def _supa_delete(table: str, filters: str) -> None:
    if not SUPABASE_URL:
        return
    url = f"{SUPABASE_URL}/rest/v1/{table}?{filters}"
    async with aiohttp.ClientSession() as s:
        await s.delete(url, headers=_hdr())


# ──────────────────────────────────────────────────────────────
# Pinecone vector fetch helpers
# ──────────────────────────────────────────────────────────────
def _fetch_all_vectors(idx, dim: int = 512, max_vectors: int = 10000) -> list[dict]:
    """
    Fetches as many vectors as possible from a Pinecone index using
    random-probe queries. Free-tier Pinecone has no scan endpoint, so
    we use diverse random probes to discover vectors.

    Returns list of dicts: {id, values, metadata}
    """
    seen_ids: set = set()
    collected: list[dict] = []
    rng = np.random.default_rng(seed=42)

    # 20 random probes — covers most of the index for typical gallery sizes
    for _ in range(20):
        probe = rng.standard_normal(dim).astype(np.float32)
        probe /= np.linalg.norm(probe)

        res = idx.query(
            vector=probe.tolist(),
            top_k=min(FACE_SEARCH_TOP_K, 1000),
            include_metadata=True,
            include_values=True,
        )
        for match in res.get("matches", []):
            vid = match["id"]
            if vid in seen_ids:
                continue
            seen_ids.add(vid)
            values = match.get("values")
            if values:
                collected.append({
                    "id": vid,
                    "values": values,
                    "metadata": match.get("metadata", {}),
                })
            if len(collected) >= max_vectors:
                break
        if len(collected) >= max_vectors:
            break

    return collected


# ──────────────────────────────────────────────────────────────
# Core clustering logic
# ──────────────────────────────────────────────────────────────
def _run_hdbscan(vectors: np.ndarray) -> np.ndarray:
    """
    Runs HDBSCAN on the provided L2-normalised 512-d face vectors.
    Returns integer label array (−1 = noise / unclustered).
    """
    try:
        import hdbscan
    except ImportError:
        raise RuntimeError(
            "hdbscan not installed. Add hdbscan>=0.8.33 to requirements.txt"
        )

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=CLUSTER_MIN_CLUSTER_SIZE,
        min_samples=CLUSTER_MIN_SAMPLES,
        cluster_selection_epsilon=CLUSTER_EPSILON,
        metric="euclidean",
        core_dist_n_jobs=1,  # HF CPU — avoid multiprocessing overhead
    )
    clusterer.fit(vectors)
    return clusterer.labels_


def _pick_representative(cluster_vecs: np.ndarray, cluster_meta: list[dict]) -> dict:
    """
    Picks the non-blurry face closest to the cluster centroid as the representative.
    Prefers sharpest (highest blur_score) faces. Returns the metadata dict for that face.
    """
    centroid = cluster_vecs.mean(axis=0)
    centroid /= np.linalg.norm(centroid) + 1e-8
    sims = cluster_vecs @ centroid

    # Sort by similarity, but prefer non-blurry faces (higher blur_score)
    sorted_indices = np.argsort(sims)[::-1]  # highest similarity first
    for idx in sorted_indices:
        blur_score = cluster_meta[idx].get("blur_score", 100.0)
        if blur_score >= CLUSTERING_BLUR_THRESHOLD:
            return cluster_meta[int(idx)]

    # Fallback: if all faces are blurry, pick the sharpest one
    best_idx = max(range(len(cluster_meta)), key=lambda i: cluster_meta[i].get("blur_score", 0))
    return cluster_meta[best_idx]


# ──────────────────────────────────────────────────────────────
# Public entry points
# ──────────────────────────────────────────────────────────────
async def run_clustering(pc, user_id: str) -> dict:
    """
    Full re-cluster pipeline:
    1. Fetch all ArcFace vectors from Pinecone
    2. Run HDBSCAN
    3. Write cluster assignments to Supabase face_clusters table
    4. Write per-vector assignments to face_vector_clusters table

    Returns a summary dict.
    """
    idx = pc.Index(IDX_FACES_ARCFACE)

    # 1. Fetch vectors (blocking — run in thread pool)
    raw = await asyncio.to_thread(_fetch_all_vectors, idx)
    if len(raw) < CLUSTER_MIN_CLUSTER_SIZE:
        return {"status": "skipped", "reason": "not enough vectors", "vectors": len(raw)}

    ids = [r["id"] for r in raw]
    metas = [r["metadata"] for r in raw]

    # Filter out blurry faces before clustering
    valid_indices = [i for i, meta in enumerate(metas) if meta.get("blur_score", 100.0) >= CLUSTERING_BLUR_THRESHOLD]

    if len(valid_indices) < CLUSTER_MIN_CLUSTER_SIZE:
        return {"status": "skipped", "reason": f"only {len(valid_indices)} non-blurry vectors after blur filtering", "vectors": len(raw), "valid_vectors": len(valid_indices)}

    ids = [ids[i] for i in valid_indices]
    metas = [metas[i] for i in valid_indices]
    raw_values = [r["values"] for r in raw]
    matrix = np.array([raw_values[i] for i in valid_indices], dtype=np.float32)

    # L2-normalise before euclidean HDBSCAN (equivalent to angular distance)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = matrix / (norms + 1e-8)

    # 2. Cluster (blocking)
    labels = await asyncio.to_thread(_run_hdbscan, matrix)

    unique_labels = set(labels) - {-1}
    now_iso = datetime.now(timezone.utc).isoformat()

    # 3. Delete existing clusters for this user (full re-cluster)
    await _supa_delete("face_clusters", f"user_id=eq.{user_id}")
    await _supa_delete("face_vector_clusters", f"user_id=eq.{user_id}")

    cluster_rows = []
    vector_rows = []

    for label in sorted(unique_labels):
        cluster_id = str(uuid.uuid4())
        mask = labels == label
        c_indices = np.where(mask)[0]
        c_vecs = matrix[c_indices]
        c_meta = [metas[i] for i in c_indices]
        c_ids = [ids[i] for i in c_indices]

        rep_meta = _pick_representative(c_vecs, c_meta)

        cluster_rows.append({
            "cluster_id": cluster_id,
            "user_id": user_id,
            "representative_face_crop": rep_meta.get("face_crop", ""),
            "representative_vector_id": c_ids[0],
            "face_count": int(len(c_indices)),
            "name": None,
            "created_at": now_iso,
            "updated_at": now_iso,
        })

        for vid, meta in zip(c_ids, c_meta):
            vector_rows.append({
                "vector_id": vid,
                "cluster_id": cluster_id,
                "user_id": user_id,
                "image_url": meta.get("url", ""),
                "folder": meta.get("folder", ""),
                "face_crop": meta.get("face_crop", ""),
                "updated_at": now_iso,
            })

    # 4. Batch write to Supabase (200 rows per request)
    for i in range(0, len(cluster_rows), 200):
        await _supa_upsert("face_clusters", cluster_rows[i:i + 200])
    for i in range(0, len(vector_rows), 200):
        await _supa_upsert("face_vector_clusters", vector_rows[i:i + 200])

    return {
        "status": "ok",
        "total_vectors": len(ids),
        "clusters_found": len(unique_labels),
        "noise_vectors": int(np.sum(labels == -1)),
    }


async def get_people(user_id: str) -> list[dict]:
    """Returns all identity clusters for a user, ordered by face_count desc."""
    rows = await _supa_select(
        "face_clusters",
        f"user_id=eq.{user_id}&order=face_count.desc",
    )
    return [
        {
            "cluster_id": r["cluster_id"],
            "name": r.get("name"),
            "face_count": r.get("face_count", 0),
            "representative_face_crop": r.get("representative_face_crop", ""),
        }
        for r in rows
    ]


async def get_person_images(cluster_id: str, user_id: str) -> list[dict]:
    """Returns all images belonging to a cluster."""
    rows = await _supa_select(
        "face_vector_clusters",
        f"cluster_id=eq.{cluster_id}&user_id=eq.{user_id}",
    )
    # Dedupe by image_url (multiple face vectors can come from the same image)
    seen: set = set()
    out = []
    for r in rows:
        url = r.get("image_url", "")
        if url and url not in seen:
            seen.add(url)
            out.append({
                "url": url,
                "thumb_url": cld_face_thumb_url(url),
                "folder": r.get("folder", ""),
                "face_crop": r.get("face_crop", ""),
            })
    return out


async def rename_cluster(cluster_id: str, name: str, user_id: str) -> bool:
    """Assigns a human-readable name to a cluster ('Mom', 'John', etc.)."""
    await _supa_patch(
        "face_clusters",
        f"cluster_id=eq.{cluster_id}&user_id=eq.{user_id}",
        {"name": name, "updated_at": datetime.now(timezone.utc).isoformat()},
    )
    return True


async def search_cluster_aware(
    pc, image_map: dict, user_id: str
) -> dict:
    """
    Cluster-aware search expansion (Phase 3 recall win).

    Given an initial image_map from search_faces_split, look up which
    clusters the matched faces belong to, then return ALL images in those
    clusters. This achieves near-100% recall for well-indexed people.

    Returns an expanded image_map in the same format as search_faces_split.
    """
    if not image_map:
        return image_map

    # Find which vector_ids were returned in the initial search
    matched_vids = {v.get("vector_id") for v in image_map.values() if v.get("vector_id")}
    if not matched_vids:
        return image_map

    # Look up cluster membership for those vector_ids
    vid_list = ",".join(f'"{v}"' for v in matched_vids)
    rows = await _supa_select(
        "face_vector_clusters",
        f"vector_id=in.({vid_list})&user_id=eq.{user_id}",
    )

    if not rows:
        return image_map

    # Collect all cluster_ids matched
    cluster_ids = {r["cluster_id"] for r in rows}

    # Fetch all images in those clusters
    expanded = dict(image_map)
    for cluster_id in cluster_ids:
        cluster_images = await get_person_images(cluster_id, user_id)
        for img in cluster_images:
            url = img["url"]
            if url not in expanded:
                # Add with a slightly lower score than the worst match
                # so cluster-expanded results sort after direct hits
                min_score = min(
                    (v["fused_score"] for v in image_map.values()), default=0.3
                )
                expanded[url] = {
                    "fused_score": max(min_score - 0.01, 0.01),
                    "arcface_score": 0.0,
                    "adaface_score": 0.0,
                    "raw_score": 0.0,
                    "face_crop": img.get("face_crop", ""),
                    "folder": img.get("folder", "uncategorized"),
                    "vector_id": None,
                    "cluster_expanded": True,
                }

    return expanded