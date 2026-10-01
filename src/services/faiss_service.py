"""
src/services/faiss_service.py — Production-grade local FAISS Vector Storage Engine.
Replaces Pinecone with local, high-performance FAISS indices and SQLite metadata storage.
Features:
- Sub-millisecond exact cosine similarity search (L2 normalized Inner Product)
- IndexIDMap2 for ID-level add, remove, and reconstruct
- Disk persistence (data/faiss/*.index)
- Thread-safe operations with threading locks
- Full compatibility with the multi-index face and object search architecture
- Graceful in-memory fallback if native FAISS is not yet compiled in environment
"""
import json
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.core.config import (
    IDX_FACES,
    IDX_OBJECTS,
    IDX_FACES_ARCFACE,
    IDX_FACES_ADAFACE,
    FACE_DIM,
    ADAFACE_DIM,
    FUSED_FACE_DIM,
)
from src.core.logging import log, warn
from src.services.local_db import (
    sync_save_vector_metadata_batch,
    sync_get_vector_metadata_by_int_ids,
    sync_delete_vectors_by_ids,
    sync_delete_vectors_by_url,
    sync_delete_vectors_by_folder,
    sync_get_all_vector_metadata,
    sync_clear_vector_metadata,
)

# Detect if native faiss is installed
try:
    import faiss
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False
    warn("faiss package not installed; using optimized in-memory NumPy vector engine fallback.")


class NumpyVectorIndex:
    """High-performance in-memory fallback with identical API to FAISS IndexIDMap2."""

    def __init__(self, dimension: int):
        self.dimension = dimension
        self.vectors: Dict[int, np.ndarray] = {}  # int_id -> normalized vector
        self.lock = threading.RLock()

    def add_with_ids(self, x: np.ndarray, ids: np.ndarray):
        with self.lock:
            for vec, int_id in zip(x, ids):
                self.vectors[int(int_id)] = vec.astype(np.float32)

    def search(self, query: np.ndarray, k: int) -> Tuple[np.ndarray, np.ndarray]:
        with self.lock:
            if not self.vectors:
                return np.zeros((1, 0), dtype=np.float32), np.zeros((1, 0), dtype=np.int64)

            int_ids = np.array(list(self.vectors.keys()), dtype=np.int64)
            matrix = np.array(list(self.vectors.values()), dtype=np.float32)

            q = query.reshape(1, -1)
            scores = (matrix @ q.T).flatten()

            top_indices = np.argsort(-scores)[:k]
            top_scores = scores[top_indices].reshape(1, -1)
            top_ids = int_ids[top_indices].reshape(1, -1)
            return top_scores, top_ids

    def remove_ids(self, ids: np.ndarray):
        with self.lock:
            for int_id in ids:
                self.vectors.pop(int(int_id), None)

    def reconstruct(self, int_id: int) -> np.ndarray:
        with self.lock:
            return self.vectors[int(int_id)]

    @property
    def ntotal(self) -> int:
        return len(self.vectors)


class FAISSVectorStore:
    """
    Manages named FAISS indices and integrates them with local SQLite metadata.
    """

    DIMENSIONS: Dict[str, int] = {
        IDX_OBJECTS: 1536,
        IDX_FACES_ARCFACE: FACE_DIM,        # 512
        IDX_FACES_ADAFACE: ADAFACE_DIM,    # 512
        IDX_FACES: FUSED_FACE_DIM,          # 1024
    }

    def __init__(self, data_dir: str = "data/faiss"):
        self.data_dir = os.path.abspath(data_dir)
        os.makedirs(self.data_dir, exist_ok=True)
        self._indices: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._init_all_indices()

    def _index_path(self, index_name: str) -> str:
        return os.path.join(self.data_dir, f"{index_name}.faiss")

    def _create_index(self, dimension: int):
        if HAS_FAISS:
            base_index = faiss.IndexFlatIP(dimension)
            return faiss.IndexIDMap2(base_index)
        else:
            return NumpyVectorIndex(dimension)

    def _load_or_create_index(self, index_name: str, dimension: int):
        path = self._index_path(index_name)
        if HAS_FAISS and os.path.exists(path):
            try:
                idx = faiss.read_index(path)
                return idx
            except Exception as e:
                warn(f"Failed to read FAISS index {index_name} from disk: {e}. Creating new index.")

        idx = self._create_index(dimension)
        # If in-memory fallback, reload from SQLite metadata if available
        if not HAS_FAISS:
            self._rehydrate_numpy_index(idx, index_name)
        return idx

    def _rehydrate_numpy_index(self, idx: NumpyVectorIndex, index_name: str):
        """Restore vectors from stored metadata if present."""
        rows = sync_get_all_vector_metadata(index_name, limit=100000)
        vecs = []
        ids = []
        for r in rows:
            raw_vec = r.get("metadata", {}).get("_raw_vector")
            if raw_vec:
                vecs.append(raw_vec)
                ids.append(r["int_id"])
        if vecs:
            v_np = np.array(vecs, dtype=np.float32)
            norms = np.linalg.norm(v_np, axis=1, keepdims=True)
            norms[norms == 0] = 1e-12
            v_np /= norms
            idx.add_with_ids(v_np, np.array(ids, dtype=np.int64))

    def _init_all_indices(self):
        with self._lock:
            for name, dim in self.DIMENSIONS.items():
                self._indices[name] = self._load_or_create_index(name, dim)

    def save_indices(self):
        """Persist indices to disk."""
        if not HAS_FAISS:
            return
        with self._lock:
            for name, idx in self._indices.items():
                try:
                    path = self._index_path(name)
                    faiss.write_index(idx, path)
                except Exception as e:
                    warn(f"Failed to save FAISS index {name}: {e}")

    def get_index(self, index_name: str, dimension: Optional[int] = None):
        """Get or lazily create a named index."""
        with self._lock:
            if index_name not in self._indices:
                dim = dimension or self.DIMENSIONS.get(index_name, 512)
                self._indices[index_name] = self._load_or_create_index(index_name, dim)
            return self._indices[index_name]

    def upsert_vectors(self, index_name: str, vectors: List[Dict[str, Any]]) -> int:
        """
        Upsert a list of vector dicts:
        vectors = [
            {
                "id": "file_123_0",
                "values": [0.12, 0.45, ...],
                "metadata": {"url": "...", "folder": "...", "face_crop": "...", ...}
            },
            ...
        ]
        """
        if not vectors:
            return 0

        dim = len(vectors[0]["values"])
        index = self.get_index(index_name, dim)

        # 1. Store metadata in SQLite to get persistent integer IDs
        int_ids = sync_save_vector_metadata_batch(index_name, vectors)

        # 2. Prepare float32 numpy array and normalize for Cosine Similarity (Inner Product)
        raw_matrix = np.array([v["values"] for v in vectors], dtype=np.float32)
        norms = np.linalg.norm(raw_matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1e-12
        normalized_matrix = raw_matrix / norms

        ids_array = np.array(int_ids, dtype=np.int64)

        # 3. Add to FAISS index with thread lock
        with self._lock:
            index.add_with_ids(normalized_matrix, ids_array)
            if HAS_FAISS:
                try:
                    faiss.write_index(index, self._index_path(index_name))
                except Exception as e:
                    warn(f"Failed writing FAISS index after upsert: {e}")

        return len(vectors)

    def search(
        self,
        index_name: str,
        query_vector: List[float],
        top_k: int = 50,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Performs Cosine Similarity search over the FAISS index.
        Returns matches:
        [
            {"id": "file_123_0", "score": 0.884, "metadata": {...}},
            ...
        ]
        """
        dim = len(query_vector)
        index = self.get_index(index_name, dim)

        # Normalize query vector
        q_np = np.array(query_vector, dtype=np.float32)
        q_norm = np.linalg.norm(q_np)
        if q_norm > 0:
            q_np /= q_norm
        q_np = q_np.reshape(1, -1)

        # Query extra items if a filter is specified to satisfy top_k after filtering
        fetch_k = min(top_k * 4 if filter_dict else top_k, max(index.ntotal, 1))
        if fetch_k <= 0 or index.ntotal == 0:
            return []

        with self._lock:
            distances, indices = index.search(q_np, fetch_k)

        matched_scores = distances[0]
        matched_int_ids = indices[0]

        valid_int_ids = [int(i) for i in matched_int_ids if int(i) >= 0]
        if not valid_int_ids:
            return []

        # Retrieve metadata for matched integer IDs
        metadata_map = sync_get_vector_metadata_by_int_ids(index_name, valid_int_ids)

        results = []
        for score, int_id in zip(matched_scores, matched_int_ids):
            int_id = int(int_id)
            if int_id < 0 or int_id not in metadata_map:
                continue

            item = metadata_map[int_id]
            meta = item["metadata"]

            # Apply metadata filter (e.g. {"folder": "events"})
            if filter_dict:
                matches_filter = True
                for k, v in filter_dict.items():
                    if meta.get(k) != v and item.get(k) != v:
                        matches_filter = False
                        break
                if not matches_filter:
                    continue

            results.append({
                "id": item["id"],
                "score": float(score),
                "metadata": meta,
            })

            if len(results) >= top_k:
                break

        return results

    def delete_by_ids(self, index_name: str, vector_ids: List[str]) -> int:
        """Deletes vectors by their string IDs."""
        if not vector_ids:
            return 0

        int_ids = sync_delete_vectors_by_ids(index_name, vector_ids)
        if int_ids:
            index = self.get_index(index_name)
            with self._lock:
                index.remove_ids(np.array(int_ids, dtype=np.int64))
                if HAS_FAISS:
                    faiss.write_index(index, self._index_path(index_name))
        return len(int_ids)

    def delete_by_url(self, url: str) -> int:
        """Deletes vectors associated with an image URL across all indexes."""
        index_ids_map = sync_delete_vectors_by_url(url)
        total = 0
        with self._lock:
            for idx_name, int_ids in index_ids_map.items():
                if int_ids:
                    idx = self.get_index(idx_name)
                    idx.remove_ids(np.array(int_ids, dtype=np.int64))
                    total += len(int_ids)
                    if HAS_FAISS:
                        faiss.write_index(idx, self._index_path(idx_name))
        return total

    def delete_by_folder(self, folder: str) -> int:
        """Deletes vectors associated with a folder across all indexes."""
        index_ids_map = sync_delete_vectors_by_folder(folder)
        total = 0
        with self._lock:
            for idx_name, int_ids in index_ids_map.items():
                if int_ids:
                    idx = self.get_index(idx_name)
                    idx.remove_ids(np.array(int_ids, dtype=np.int64))
                    total += len(int_ids)
                    if HAS_FAISS:
                        faiss.write_index(idx, self._index_path(idx_name))
        return total

    def get_all_vectors(self, index_name: str, limit: int = 10000) -> List[Dict[str, Any]]:
        """
        Retrieves all vector embeddings and their metadata for clustering or export.
        Returns: [{"id": str, "values": list[float], "metadata": dict}, ...]
        """
        rows = sync_get_all_vector_metadata(index_name, limit)
        index = self.get_index(index_name)
        results = []

        with self._lock:
            for r in rows:
                int_id = r["int_id"]
                try:
                    vec = index.reconstruct(int_id)
                    results.append({
                        "id": r["id"],
                        "values": vec.tolist(),
                        "metadata": r["metadata"],
                    })
                except Exception:
                    continue
        return results

    def reset_index(self, index_name: str):
        """Clears an index and removes all stored metadata for it."""
        with self._lock:
            sync_clear_vector_metadata(index_name)
            dim = self.DIMENSIONS.get(index_name, 512)
            self._indices[index_name] = self._create_index(dim)
            path = self._index_path(index_name)
            if HAS_FAISS and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    def reset_all(self):
        """Resets all FAISS indexes and deletes all vector metadata."""
        with self._lock:
            sync_clear_vector_metadata()
            for name in list(self._indices.keys()):
                self.reset_index(name)


# Global singleton FAISS vector store
faiss_store = FAISSVectorStore()
