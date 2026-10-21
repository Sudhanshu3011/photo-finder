"""
src/modules/infra/faiss_engine.py — Production-grade local FAISS Vector Storage Engine.
Provides sub-millisecond cosine similarity search over normalized embeddings.
Persistent to disk (data/faiss/*.index) with metadata synced to PostgreSQL.
"""
import collections
import json
import os
import shutil
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple, Set, Union

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
    USE_HNSW_INDEX,
    HNSW_M,
    HNSW_EF_CONSTRUCTION,
    HNSW_EF_SEARCH,
    ENVIRONMENT,
)
from src.core.logging import log, warn
from src.core.tenant_context import get_current_tenant_id
from src.modules.infra.postgres_repository import (
    sync_save_vector_metadata_batch,
    sync_get_vector_metadata_by_int_ids,
    sync_get_int_ids_by_folders,
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

    def search(self, x: np.ndarray, k: int, allowed_ids: Optional[Any] = None) -> Tuple[np.ndarray, np.ndarray]:
        with self.lock:
            if not self.vectors:
                return np.zeros((x.shape[0], 0), dtype=np.float32), np.zeros((x.shape[0], 0), dtype=np.int64)

            if allowed_ids is not None:
                allowed_set = set(allowed_ids)
                v_ids = [i for i in self.vectors.keys() if i in allowed_set]
            else:
                v_ids = list(self.vectors.keys())

            if not v_ids:
                return np.zeros((x.shape[0], 0), dtype=np.float32), np.zeros((x.shape[0], 0), dtype=np.int64)

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


def build_vector_index(
    dimension: int,
    use_hnsw: bool = USE_HNSW_INDEX,
    m: int = HNSW_M,
    ef_construction: int = HNSW_EF_CONSTRUCTION,
    ef_search: int = HNSW_EF_SEARCH,
) -> Any:
    """
    Instantiate an IndexIDMap2 vector index wrapping either IndexHNSWFlat or IndexFlatIP.
    In production environments, fails closed if native FAISS is missing.
    """
    if HAS_FAISS:
        if use_hnsw:
            quantizer = faiss.IndexHNSWFlat(dimension, m, faiss.METRIC_INNER_PRODUCT)
            quantizer.hnsw.efConstruction = ef_construction
            quantizer.hnsw.efSearch = ef_search
            return faiss.IndexIDMap2(quantizer)
        else:
            raw = faiss.IndexFlatIP(dimension)
            return faiss.IndexIDMap2(raw)
    else:
        if ENVIRONMENT == "production":
            raise RuntimeError(
                "FAISS native library is not installed in production environment. "
                "NumPy fallback is strictly prohibited in production."
            )
        return NumpyVectorIndex(dimension)



class FAISSEngine:
    """Local vector store orchestrating indices across face and object domains with tenant partitioning."""

    DIMENSIONS = {
        IDX_FACES: FACE_DIM,
        IDX_OBJECTS: OBJECT_DIM,
        IDX_FACES_ARCFACE: FACE_DIM,
        IDX_FACES_ADAFACE: ADAFACE_DIM,
    }

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is not None:
            self.data_dir = data_dir
        else:
            env_dir = os.environ.get("FAISS_DATA_DIR")
            self.data_dir = env_dir if env_dir else os.path.join(os.getcwd(), "data/faiss")
        os.makedirs(self.data_dir, exist_ok=True)
        # Partitioned index storage keyed by (tenant_id, index_name) with LRU eviction
        self.indices: collections.OrderedDict[Tuple[str, str], Any] = collections.OrderedDict()
        self.max_loaded_indices: int = int(os.getenv("FAISS_MAX_LOADED_INDICES", "50"))
        # Track disk modification timestamps to detect cross-process worker updates
        self._index_mtimes: Dict[Tuple[str, str], float] = {}
        self.lock = threading.RLock()
        self._init_indices("default")

    def _get_index_path(self, index_name: str, tenant_id: str = "default") -> str:
        tid = (tenant_id or "default").strip()
        tenant_dir = os.path.join(self.data_dir, tid)
        os.makedirs(tenant_dir, exist_ok=True)
        return os.path.join(tenant_dir, f"{index_name}.index")

    def _save_single_index_to_disk(self, index_name: str, tenant_id: str, idx: Any) -> bool:
        """Persist a single FAISS index using atomic POSIX rename to avoid partial reader loads."""
        if not HAS_FAISS or idx is None:
            return False
        path = self._get_index_path(index_name, tenant_id)
        tmp_path = f"{path}.tmp.{uuid.uuid4().hex}"
        try:
            faiss.write_index(idx, tmp_path)
            os.replace(tmp_path, path)
            self._index_mtimes[(tenant_id, index_name)] = os.path.getmtime(path)
            return True
        except Exception as e:
            warn(f"Failed to persist FAISS index {index_name} for tenant {tenant_id}: {e}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            return False

    def _evict_lru_index_if_needed(self) -> None:
        """Evict oldest loaded tenant indices from memory if max capacity is exceeded."""
        while len(self.indices) > self.max_loaded_indices:
            (old_tid, old_name), old_idx = self.indices.popitem(last=False)
            self._save_single_index_to_disk(old_name, old_tid, old_idx)
            self._index_mtimes.pop((old_tid, old_name), None)

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
                                self.indices[key] = build_vector_index(dim)
                            else:
                                base = faiss.downcast_index(loaded.index) if hasattr(loaded, "index") else faiss.downcast_index(loaded)
                                if hasattr(base, "hnsw"):
                                    base.hnsw.efSearch = HNSW_EF_SEARCH
                                self.indices[key] = loaded
                            self._index_mtimes[key] = os.path.getmtime(path)
                        except Exception as e:
                            warn(f"Failed to load FAISS index from {path}: {e}. Creating new.")
                            self.indices[key] = build_vector_index(dim)
                    else:
                        self.indices[key] = build_vector_index(dim)
                else:
                    self.indices[key] = build_vector_index(dim)

    def get_index(self, index_name: str, tenant_id: Optional[str] = None, dim: Optional[int] = None):
        tid = (tenant_id or get_current_tenant_id()).strip()
        key = (tid, index_name)
        d = dim or self.DIMENSIONS.get(index_name, 512)
        path = self._get_index_path(index_name, tid)
        legacy_path = os.path.join(self.data_dir, f"{index_name}.index")
        if not os.path.exists(path) and os.path.exists(legacy_path) and tid == "default":
            path = legacy_path

        with self.lock:
            if HAS_FAISS:
                if os.path.exists(path):
                    disk_mtime = os.path.getmtime(path)
                    cached_mtime = self._index_mtimes.get(key, 0.0)
                    # Automatically reload index if not loaded or if disk snapshot was updated by worker fleet
                    if key not in self.indices or disk_mtime > cached_mtime:
                        try:
                            loaded = faiss.read_index(path)
                            if loaded.d == d or dim is None:
                                base = faiss.downcast_index(loaded.index) if hasattr(loaded, "index") else faiss.downcast_index(loaded)
                                if hasattr(base, "hnsw"):
                                    base.hnsw.efSearch = HNSW_EF_SEARCH
                                self.indices[key] = loaded
                                self._index_mtimes[key] = disk_mtime
                            else:
                                self.indices[key] = build_vector_index(d)
                        except Exception as e:
                            warn(f"Failed to load/reload FAISS index from {path}: {e}")
                            if key not in self.indices:
                                self.indices[key] = build_vector_index(d)
                else:
                    if key not in self.indices:
                        self.indices[key] = build_vector_index(d)
            else:
                if key not in self.indices:
                    self.indices[key] = build_vector_index(d)

            if key in self.indices:
                self.indices.move_to_end(key)
            self._evict_lru_index_if_needed()
            return self.indices[key]

    def save_to_disk(self, index_name: Optional[str] = None, tenant_id: Optional[str] = None):
        """Persist native FAISS indexes to disk scoped to tenant using atomic snapshot publishing."""
        if not HAS_FAISS:
            return
        target_tid = (tenant_id or get_current_tenant_id()).strip() if tenant_id else None
        with self.lock:
            targets = list(self.indices.keys())
            for (tid, name) in targets:
                if (index_name is None or name == index_name) and (target_tid is None or tid == target_tid):
                    idx = self.indices.get((tid, name))
                    if idx is not None:
                        self._save_single_index_to_disk(name, tid, idx)

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
                self.indices[key] = build_vector_index(target_dim)
                idx = self.indices[key]

            id_array = np.array(int_ids, dtype=np.int64)
            if HAS_FAISS:
                try:
                    idx.remove_ids(id_array)
                except Exception:
                    pass
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
            try:
                removed = idx.remove_ids(arr)
            except Exception:
                # IndexHNSWFlat does not support physical node deletion;
                # vector is unlinked from PostgreSQL metadata and excluded by IDSelector pre-filtering
                removed = len(arr)
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
        allowed_int_ids: Optional[Union[List[int], Set[int]]] = None,
    ) -> List[dict]:
        """
        Run similarity search against an index scoped to tenant.
        Supports search-time pre-filtering via faiss.IDSelectorBatch to prevent cross-tenant contamination.
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
        fetch_k = top_k * 5 if filter_dict else top_k

        # Resolve target allowed integer IDs for search-time pre-filtering
        target_allowed: Optional[List[int]] = None
        if allowed_int_ids is not None:
            target_allowed = list(allowed_int_ids)
            if not target_allowed:
                return []
        elif filter_dict and "allowed_int_ids" in filter_dict and filter_dict["allowed_int_ids"] is not None:
            target_allowed = list(filter_dict["allowed_int_ids"])
            if not target_allowed:
                return []
        elif filter_dict and ("allowed_folders" in filter_dict or "folder" in filter_dict):
            folders = []
            if "allowed_folders" in filter_dict and isinstance(filter_dict["allowed_folders"], (list, set, tuple)):
                folders = [f for f in filter_dict["allowed_folders"] if f]
            elif "folder" in filter_dict and filter_dict["folder"]:
                folders = [filter_dict["folder"]]
            if folders:
                target_allowed = sync_get_int_ids_by_folders(index_name, folders, tenant_id=tid)
                if not target_allowed:
                    return []

        with self.lock:
            if idx.ntotal == 0 or idx.d != target_dim:
                return []
            k_actual = min(fetch_k, idx.ntotal)
            if HAS_FAISS and hasattr(idx, "search"):
                if target_allowed is not None:
                    sel_arr = np.array(target_allowed, dtype=np.int64)
                    selector = faiss.IDSelectorBatch(sel_arr)
                    base = faiss.downcast_index(idx.index) if hasattr(idx, "index") else faiss.downcast_index(idx)
                    if hasattr(base, "hnsw") or isinstance(base, faiss.IndexHNSW):
                        params = faiss.SearchParametersHNSW(sel=selector, efSearch=HNSW_EF_SEARCH)
                    else:
                        params = faiss.SearchParameters(sel=selector)
                    scores, int_ids = idx.search(q_vec, k_actual, params=params)
                else:
                    scores, int_ids = idx.search(q_vec, k_actual)
            else:
                scores, int_ids = idx.search(q_vec, k_actual, allowed_ids=target_allowed)

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
                    if fk in ("allowed_folders", "allowed_int_ids"):
                        continue  # Already pre-filtered at index level
                    elif fk == "folder":
                        entry_fld = entry.get("folder") or meta.get("folder")
                        if entry_fld != fv:
                            match = False
                            break
                    elif meta.get(fk) != fv and entry.get(fk) != fv:
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
        allowed_int_ids: Optional[Union[List[int], Set[int]]] = None,
    ) -> List[dict]:
        return self.search(
            index_name=index_name,
            query_vector=query_vector,
            top_k=top_k,
            filter_dict=filter_dict,
            tenant_id=tenant_id,
            allowed_int_ids=allowed_int_ids,
        )

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
                    try:
                        idx.remove_ids(arr)
                    except Exception:
                        pass
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
                    try:
                        idx.remove_ids(arr)
                    except Exception:
                        pass
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


def get_faiss_engine() -> FAISSEngine:
    """Return the global FAISSEngine singleton."""
    return vector_engine

