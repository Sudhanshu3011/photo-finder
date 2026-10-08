"""
src/modules/clustering/hdbscan_clusterer.py — HDBSCAN Identity Clustering.
Groups normalized facial embeddings into distinct identity clusters (albums) using precomputed cosine distance.
"""
from typing import Any, Dict, List, Tuple
import numpy as np
from src.core.logging import log


def run_hdbscan_clustering(
    vectors: np.ndarray,
    min_cluster_size: int = 5,
    min_samples: int = 5,
    epsilon: float = 0.20,
) -> np.ndarray:
    """
    Runs HDBSCAN clustering on normalized face vectors using cosine distance.
    Returns array of cluster labels (-1 for noise/outliers).
    """
    if len(vectors) < min_cluster_size:
        log("INFO", "clustering.hdbscan.too_few_vectors", count=len(vectors), required=min_cluster_size)
        return np.full((len(vectors),), -1)

    try:
        import hdbscan

        # Cosine distance = 1 - dot_product for normalized vectors
        sim_matrix = vectors @ vectors.T
        dist_matrix = np.clip(1.0 - sim_matrix, 0.0, 2.0).astype(np.float64)
        np.fill_diagonal(dist_matrix, 0.0)

        clusterer = hdbscan.HDBSCAN(
            metric="precomputed",
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
            cluster_selection_epsilon=epsilon,
            cluster_selection_method="eom",
        )
        labels = clusterer.fit_predict(dist_matrix)
        unique_labels = set(labels) - {-1}
        log("INFO", "clustering.hdbscan.success", vectors_clustered=len(vectors), clusters_found=len(unique_labels))
        return labels
    except Exception as e:
        log("ERROR", "clustering.hdbscan.failed", error=str(e))
        raise


def select_cluster_representative(cluster_vectors: np.ndarray, cluster_metadata: List[dict]) -> dict:
    """
    Selects the most representative face (medoid) with highest sharpness/blur score.
    """
    if len(cluster_vectors) == 1:
        return cluster_metadata[0]

    centroid = np.mean(cluster_vectors, axis=0)
    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid /= norm

    similarities = cluster_vectors @ centroid

    best_score = -1.0
    best_idx = 0
    for i, (sim, meta) in enumerate(zip(similarities, cluster_metadata)):
        blur = float(meta.get("blur_score", 50.0))
        blur_factor = min(blur / 100.0, 1.5)
        combined = sim * blur_factor
        if combined > best_score:
            best_score = combined
            best_idx = i

    return cluster_metadata[best_idx]

