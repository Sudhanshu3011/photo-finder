"""
src/modules/infra/faiss_engine.py — Production-grade local FAISS Vector Storage Engine.
Provides sub-millisecond cosine similarity search over normalized embeddings.
Persistent to disk (data/faiss/*.index) with metadata synced to PostgreSQL.
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
    OBJECT_DIM,
)
from src.core.logging import log, warn
from src.core.tenant_context import get_current_tenant_id
from src.modules.infra.postgres_repository import (
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
        self.d = dimension
        self.vectors: Dict[int, np.ndarray] = {}  # int_id -> normalized vector
        self.lock = threading.RLock()

    def add_with_ids(self, x: np.ndarray, ids: np.ndarray):
        with self.lock:
            for vec, int_id in zip(x, ids):
                self.vectors[int(int_id)] = vec.astype(np.float32)

    def search(self, x: np.ndarray, k: int) -> Tuple[np.ndarray, np.ndarray]:
        with self.lock:
            if not self.vectors:
                return np.zeros((x.shape[0], 0), dtype=np.float32), np.zeros((x.shape[0], 0), dtype=np.int64)

            v_ids = list(self.vectors.keys())
            matrix = np.stack([self.vectors[i] for i in v_ids])  # (N, D)

            # Cosine similarity via inner product on normalized vectors
            scores = np.dot(x, matrix.T)  # (Q, N)

            q_scores_list = []
            q_ids_list = []

            for row in scores:
                top_k_indices = np.argsort(row)[::-1][:k]
                q_scores_list.append([row[idx] for idx in top_k_indices])
                q_ids_list.append([v_ids[idx] for idx in top_k_indices])

            return np.array(q_scores_list, dtype=np.float32), np.array(q_ids_list, dtype=np.int64)

    def remove_ids(self, ids: np.ndarray) -> int:
        removed = 0
        with self.lock:
            for int_id in ids:
                if int(int_id) in self.vectors:
                    del self.vectors[int(int_id)]
                    removed += 1
        return removed

    @property
    def ntotal(self) -> int:
        return len(self.vectors)


class FAISSEngine:
    """Local vector store orchestrating indices across face and object domains with tenant partitioning."""

    DIMENSIONS = {
        IDX_FACES: FACE_DIM,
        IDX_OBJECTS: OBJECT_DIM,
        IDX_FACES_ARCFACE: FACE_DIM,
        IDX_FACES_ADAFACE: ADAFACE_DIM,
    }

    def __init__(self, data_dir: str = "data/faiss"):
        env_dir = os.environ.get("FAISS_DATA_DIR")
        self.data_dir = env_dir if env_dir else os.path.join(os.getcwd(), data_dir)
        os.makedirs(self.data_dir, exist_ok=True)
        # Partitioned index storage keyed by (tenant_id, index_name)
        self.indices: Dict[Tuple[str, str], Any] = {}
        self.lock = threading.RLock()
        self._init_indices("default")

    def _get_index_path(self, index_name: str, tenant_id: str = "default") -> str:
        tid = (tenant_id or "default").strip()
        tenant_dir = os.path.join(self.data_dir, tid)
        os.makedirs(tenant_dir, exist_ok=True)
        return os.path.join(tenant_dir, f"{index_name}.index")

    def _init_indices(self, tenant_id: str = "default"):
        tid = (tenant_id or "default").strip()
        with self.lock:
            for idx_name, dim in self.DIMENSIONS.items():
                key = (tid, idx_name)
                path = self._get_index_path(idx_name, tid)
                legacy_path = os.path.join(self.data_dir, f"{idx_name}.index")
                if not os.path.exists(path) and os.path.exists(legacy_path) and tid == "default":
                    path = legacy_path

                if HAS_FAISS:
                    if os.path.exists(path):
                        try:
                            loaded = faiss.read_index(path)
                            if loaded.d != dim:
                                warn(f"Index dimension mismatch for {idx_name} (tenant {tid}): expected {dim}, found {loaded.d}. Recreating index.")
                                raw = faiss.IndexFlatIP(dim)
                                self.indices[key] = faiss.IndexIDMap2(raw)
                            else:
                                self.indices[key] = loaded
                        except Exception as e:
                            warn(f"Failed to load FAISS index from {path}: {e}. Creating new.")
                            raw = faiss.IndexFlatIP(dim)
                            self.indices[key] = faiss.IndexIDMap2(raw)
                    else:
                        raw = faiss.IndexFlatIP(dim)
                        self.indices[key] = faiss.IndexIDMap2(raw)
                else:
                    self.indices[key] = NumpyVectorIndex(dim)

    def get_index(self, index_name: str, tenant_id: Optional[str] = None, dim: Optional[int] = None):
        tid = (tenant_id or get_current_tenant_id()).strip()
        key = (tid, index_name)
        with self.lock:
            if key not in self.indices:
                d = dim or self.DIMENSIONS.get(index_name, 512)
                path = self._get_index_path(index_name, tid)
                legacy_path = os.path.join(self.data_dir, f"{index_name}.index")
                if not os.path.exists(path) and os.path.exists(legacy_path) and tid == "default":
                    path = legacy_path

                if HAS_FAISS:
                    if os.path.exists(path):
                        try:
                            self.indices[key] = faiss.read_index(path)
                        except Exception:
                            raw = faiss.IndexFlatIP(d)
                            self.indices[key] = faiss.IndexIDMap2(raw)
                    else:
                        raw = faiss.IndexFlatIP(d)
                        self.indices[key] = faiss.IndexIDMap2(raw)
                else:
                    self.indices[key] = NumpyVectorIndex(d)
            return self.indices[key]

    def save_to_disk(self, index_name: Optional[str] = None, tenant_id: Optional[str] = None):
        """Persist native FAISS indexes to disk scoped to tenant."""
        if not HAS_FAISS:
            return
        target_tid = (tenant_id or get_current_tenant_id()).strip() if tenant_id else None
        with self.lock:
            targets = list(self.indices.keys())
            for (tid, name) in targets:
                if (index_name is None or name == index_name) and (target_tid is None or tid == target_tid):
                    idx = self.indices.get((tid, name))
                    if idx is not None:
                        path = self._get_index_path(name, tid)
                        try:
                            faiss.write_index(idx, path)
                        except Exception as e:
                            warn(f"Failed to persist FAISS index {name} for tenant {tid}: {e}")

    def upsert(self, index_name: str, records: List[dict], tenant_id: Optional[str] = None) -> int:
        """
        Upsert a batch of vectors with metadata scoped to tenant.
        Each record: {"id": str, "vector"|"values": list[float], "url": str, "folder": str, "metadata": dict}
        """
        if not records:
            return 0

        tid = (tenant_id or get_current_tenant_id()).strip()
        int_ids = sync_save_vector_metadata_batch(index_name, records, tenant_id=tid)
        vec_list = [r.get("vector") if "vector" in r else r.get("values") for r in records]
        vecs = np.array(vec_list, dtype=np.float32)

        # L2-normalize vectors for cosine similarity via inner product
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1e-12
        vecs = vecs / norms

        target_dim = vecs.shape[1]
        with self.lock:
            idx = self.get_index(index_name, tenant_id=tid, dim=target_dim)
            key = (tid, index_name)
            if idx.ntotal == 0 and idx.d != target_dim:
                if HAS_FAISS:
                    raw = faiss.IndexFlatIP(target_dim)
                    self.indices[key] = faiss.IndexIDMap2(raw)
                else:
                    self.indices[key] = NumpyVectorIndex(target_dim)
                idx = self.indices[key]

            id_array = np.array(int_ids, dtype=np.int64)
            if HAS_FAISS:
                idx.remove_ids(id_array)
                idx.add_with_ids(vecs, id_array)
            else:
                idx.add_with_ids(vecs, id_array)

        self.save_to_disk(index_name, tenant_id=tid)
        return len(records)

    def upsert_vectors(
        self,
        index_name: str,
        records: Optional[List[dict]] = None,
        vectors: Optional[List] = None,
        ids: Optional[List] = None,
        metadata: Optional[List] = None,
        tenant_id: Optional[str] = None,
    ) -> int:
        """Convenience method accepting either a list of records or explicit vector arrays."""
        if records is None:
            records = []
            if vectors and ids:
                for i, (v, vid) in enumerate(zip(vectors, ids)):
                    m = metadata[i] if (metadata and i < len(metadata)) else {}
                    records.append({
                        "id": vid,
                        "vector": v,
                        "url": m.get("url", ""),
                        "folder": m.get("folder", ""),
                        "metadata": m,
                    })
        return self.upsert(index_name, records, tenant_id=tenant_id)

    def delete_by_ids(self, index_name: str, vector_ids: List[str], tenant_id: Optional[str] = None) -> int:
        """Delete vectors by vector_ids from an index scoped to tenant."""
        tid = (tenant_id or get_current_tenant_id()).strip()
        affected = sync_delete_vectors_by_ids(index_name, vector_ids, tenant_id=tid)
        key = (tid, index_name)
        if not affected or key not in self.indices:
            return 0
        with self.lock:
            idx = self.indices[key]
            arr = np.array(affected, dtype=np.int64)
            removed = idx.remove_ids(arr)
            self.save_to_disk(index_name, tenant_id=tid)
        return removed

    def delete_by_id(self, index_name: str, vector_ids: List[str], tenant_id: Optional[str] = None) -> int:
        return self.delete_by_ids(index_name, vector_ids, tenant_id=tenant_id)

    def search(
        self,
        index_name: str,
        query_vector: List[float],
        top_k: int = 20,
        filter_dict: Optional[dict] = None,
        tenant_id: Optional[str] = None,
    ) -> List[dict]:
        """
        Run similarity search against an index scoped to tenant.
        Returns [{"id": str, "score": float, "url": str, "folder": str, "metadata": dict}, ...]
        """
        if not query_vector:
            return []

        tid = (tenant_id or get_current_tenant_id()).strip()
        q_vec = np.array([query_vector], dtype=np.float32)
        norm = np.linalg.norm(q_vec)
        if norm > 0:
            q_vec = q_vec / norm

        target_dim = q_vec.shape[1]
        idx = self.get_index(index_name, tenant_id=tid, dim=target_dim)
        fetch_k = top_k * 3 if filter_dict else top_k

        with self.lock:
            if idx.ntotal == 0 or idx.d != target_dim:
                return []
            k_actual = min(fetch_k, idx.ntotal)
            scores, int_ids = idx.search(q_vec, k_actual)

        if len(int_ids) == 0 or len(int_ids[0]) == 0:
            return []

        matched_int_ids = [int(i) for i in int_ids[0] if i >= 0]
        meta_lookup = sync_get_vector_metadata_by_int_ids(index_name, matched_int_ids, tenant_id=tid)

        results = []
        for score, int_id in zip(scores[0], int_ids[0]):
            if int_id < 0 or int(int_id) not in meta_lookup:
                continue

            entry = meta_lookup[int(int_id)]
            meta = entry.get("metadata", {})

            if filter_dict:
                match = True
                for fk, fv in filter_dict.items():
                    if meta.get(fk) != fv and entry.get(fk) != fv:
                        match = False
                        break
                if not match:
                    continue

            results.append({
                "id": entry["id"],
                "score": float(np.clip(score, 0.0, 1.0)),
                "url": entry.get("url", ""),
                "folder": entry.get("folder", ""),
                "metadata": meta,
            })

            if len(results) >= top_k:
                break

        return results

    def search_vectors(
        self,
        index_name: str,
        query_vector: List[float],
        top_k: int = 20,
        filter_dict: Optional[dict] = None,
        tenant_id: Optional[str] = None,
    ) -> List[dict]:
        return self.search(index_name, query_vector, top_k, filter_dict, tenant_id=tenant_id)

    def delete_by_url(self, url: str, tenant_id: Optional[str] = None) -> int:
        """Delete all vectors matching a specific image URL across all indexes scoped to tenant."""
        tid = (tenant_id or get_current_tenant_id()).strip()
        affected = sync_delete_vectors_by_url(url, tenant_id=tid)
        total_removed = 0

        with self.lock:
            for idx_name, int_ids in affected.items():
                key = (tid, idx_name)
                if int_ids and key in self.indices:
                    idx = self.indices[key]
                    arr = np.array(int_ids, dtype=np.int64)
                    idx.remove_ids(arr)
                    total_removed += len(int_ids)
                    self.save_to_disk(idx_name, tenant_id=tid)

        return total_removed

    def delete_by_folder(self, folder: str, tenant_id: Optional[str] = None) -> int:
        """Delete all vectors for a given folder across all indexes scoped to tenant."""
        tid = (tenant_id or get_current_tenant_id()).strip()
        affected = sync_delete_vectors_by_folder(folder, tenant_id=tid)
        total_removed = 0

        with self.lock:
            for idx_name, int_ids in affected.items():
                key = (tid, idx_name)
                if int_ids and key in self.indices:
                    idx = self.indices[key]
                    arr = np.array(int_ids, dtype=np.int64)
                    idx.remove_ids(arr)
                    total_removed += len(int_ids)
                    self.save_to_disk(idx_name, tenant_id=tid)

        return total_removed

    def reset_all(self, tenant_id: Optional[str] = None):
        """Wipe all vector stores and metadata scoped to tenant."""
        tid = (tenant_id or get_current_tenant_id()).strip()
        with self.lock:
            sync_clear_vector_metadata(tenant_id=tid)
            keys_to_remove = [k for k in self.indices.keys() if k[0] == tid]
            for k in keys_to_remove:
                self.indices.pop(k, None)
            tenant_dir = os.path.join(self.data_dir, tid)
            if os.path.exists(tenant_dir):
                import shutil
                shutil.rmtree(tenant_dir, ignore_errors=True)
            self._init_indices(tid)

    def get_all_records(self, index_name: str, limit: int = 10000, tenant_id: Optional[str] = None) -> List[dict]:
        """Retrieve all vector metadata records for an index scoped to tenant."""
        tid = (tenant_id or get_current_tenant_id()).strip()
        return sync_get_all_vector_metadata(index_name, limit=limit, tenant_id=tid)

    def reconstruct_vector(self, index_name: str, int_id: int, tenant_id: Optional[str] = None) -> Optional[np.ndarray]:
        """Reconstruct vector by integer id from the index scoped to tenant."""
        tid = (tenant_id or get_current_tenant_id()).strip()
        key = (tid, index_name)
        idx = self.indices.get(key)
        if idx is None:
            return None
        if hasattr(idx, "vectors") and int(int_id) in idx.vectors:
            return idx.vectors[int(int_id)]
        if hasattr(idx, "reconstruct"):
            try:
                return idx.reconstruct(int(int_id))
            except Exception:
                return None
        return None


vector_engine = FAISSEngine()
FAISSVectorStore = FAISSEngine

