import logging
import uuid
import os
from typing import Dict, Any, List, Optional
import cv2
import numpy as np

from src.core.config import (
    IDX_FACES,
    IDX_FACES_ARCFACE,
    IDX_FACES_ADAFACE,
    IDX_OBJECTS,
    FACE_DIM,
    ADAFACE_DIM,
)
from src.modules.infra.sqlite_repository import get_repository
from src.modules.infra.faiss_engine import vector_engine
from src.modules.infra.kv_cache import get_kv_cache
from src.modules.vision.face_detector import detect_faces
from src.modules.vision.face_embedder import extract_face_embeddings
from src.modules.vision.object_embedder import extract_object_embedding
from src.modules.clustering.hdbscan_clusterer import run_hdbscan_clustering, select_cluster_representative
from src.modules.storage.local_storage import get_image_path

logger = logging.getLogger("src.services.image_processing_service")

class ImageProcessingService:
    """
    High-level orchestrator for AI inference, feature extraction, 
    vector indexing, and face clustering.
    Delegates all algorithm details to src.modules.*
    """

    def __init__(self, ai=None, repo=None, engine=None):
        self.ai = ai
        self.repo = repo or get_repository()
        self.engine = engine or vector_engine
        self.cache = get_kv_cache()

    def process_image_cv(
        self,
        image_id: str,
        cv_img: np.ndarray,
        user_id: Optional[str] = None,
        folder_name: Optional[str] = None,
        cloud_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Runs face and object embedding pipelines on an OpenCV BGR image
        and inserts resulting vectors into the FAISS engine.
        """
        logger.info("[Image Processing] Ingesting image_id=%s for folder='%s' (resolution: %dx%d)",
                    image_id, folder_name or "general", cv_img.shape[1], cv_img.shape[0])
        
        # 1. Face Detection & Feature Extraction
        detected_faces = detect_faces(self.ai, cv_img)
        faces_saved = 0

        for f in detected_faces:
            target_obj = f if (isinstance(f, dict) and "arcface_vector" in f) else f.get("face_obj", f)
            if target_obj is None:
                continue

            emb_data = extract_face_embeddings(self.ai, target_obj)
            arcface_vec = emb_data.get("arcface_vector")
            adaface_vec = emb_data.get("adaface_vector")

            if arcface_vec is not None and len(arcface_vec) == FACE_DIM:
                vec_id = f"face_{image_id}_{f['face_idx']}"
                meta = {
                    "image_id": image_id,
                    "bbox": f.get("bbox"),
                    "blur_score": f.get("blur_score"),
                    "user_id": user_id,
                    "face_idx": f["face_idx"],
                    "folder": folder_name or "general",
                    "url": cloud_url or "",
                }
                # Upsert into ArcFace stores
                self.engine.upsert_vectors(
                    index_name=IDX_FACES,
                    vectors=[arcface_vec],
                    ids=[vec_id],
                    metadata=[meta]
                )
                self.engine.upsert_vectors(
                    index_name=IDX_FACES_ARCFACE,
                    vectors=[arcface_vec],
                    ids=[vec_id],
                    metadata=[meta]
                )

                # Upsert into AdaFace store if available
                if emb_data.get("has_adaface") and adaface_vec and len(adaface_vec) == ADAFACE_DIM:
                    self.engine.upsert_vectors(
                        index_name=IDX_FACES_ADAFACE,
                        vectors=[adaface_vec],
                        ids=[vec_id],
                        metadata=[meta]
                    )

                faces_saved += 1

        # 2. Object & Scene Embedding Extraction
        obj_vec = extract_object_embedding(self.ai, cv_img)
        objects_saved = 0
        if obj_vec and len(obj_vec) > 0:
            obj_id = f"obj_{image_id}"
            meta = {
                "image_id": image_id,
                "user_id": user_id,
                "folder": folder_name or "general",
                "url": cloud_url or "",
            }
            self.engine.upsert_vectors(
                index_name=IDX_OBJECTS,
                vectors=[obj_vec],
                ids=[obj_id],
                metadata=[meta]
            )
            objects_saved += 1

        logger.info("[Image Processing] Finished image_id=%s: indexed %d face vectors and %d scene/object descriptors into FAISS",
                    image_id, faces_saved, objects_saved)

        return {
            "image_id": image_id,
            "faces_detected": faces_saved,
            "objects_detected": objects_saved,
            "folder": folder_name or "general",
            "status": "success",
            "message": f"Extracted {faces_saved} faces and {objects_saved} object descriptors"
        }

    def process_image_by_id(self, image_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Load image from cache/disk and process."""
        meta = self.cache.get(f"meta:{image_id}")
        local_path = meta.get("local_path") if meta else None
        folder_name = meta.get("folder") if meta else None
        cloud_url = meta.get("cloud_url") if meta else None

        if not local_path or not os.path.exists(local_path):
            local_path = get_image_path(f"{image_id}.jpg")

        if not os.path.exists(local_path):
            logger.error("[Image Processing] Local image file not found for image_id=%s", image_id)
            return {"image_id": image_id, "status": "failed", "message": "Image file not found"}

        cv_img = cv2.imread(local_path)
        if cv_img is None:
            logger.error("[Image Processing] Could not decode image file %s for image_id=%s", local_path, image_id)
            return {"image_id": image_id, "status": "failed", "message": "Corrupted or undecodable image"}

        return self.process_image_cv(
            image_id=image_id,
            cv_img=cv_img,
            user_id=user_id,
            folder_name=folder_name,
            cloud_url=cloud_url,
        )

    def trigger_face_clustering(
        self,
        min_cluster_size: int = 3,
        epsilon: float = 0.25,
        folder_name: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Gathers all stored face vectors (optionally filtered by folder), 
        groups them with HDBSCAN, and updates cluster mappings in SQLite.
        """
        logger.info("[Face Clustering] Initiating identity clustering (folder='%s', min_cluster_size=%d, epsilon=%.2f)",
                    folder_name or "ALL", min_cluster_size, epsilon)

        # Retrieve vectors from faiss engine
        idx = self.engine.indices.get(IDX_FACES)
        if not idx or idx.ntotal == 0:
            logger.warning("[Face Clustering] No face vectors available in index. Skipping clustering.")
            return {
                "status": "success",
                "clusters_found": 0,
                "total_faces": 0,
                "folder": folder_name,
                "message": "No face vectors available to cluster"
            }

        # Query all vectors and metadata
        records = self.engine.get_all_records(IDX_FACES)

        # Filter by folder if specified
        if folder_name and folder_name.strip():
            target_folder = folder_name.strip()
            records = [
                r for r in records
                if (r.get("metadata") or {}).get("folder") == target_folder
                or r.get("folder") == target_folder
            ]

        if len(records) < min_cluster_size:
            logger.info("[Face Clustering] Insufficient face vectors to form clusters (%d available < %d required)",
                        len(records), min_cluster_size)
            return {
                "status": "success",
                "clusters_found": 0,
                "total_faces": len(records),
                "folder": folder_name,
                "message": f"Too few face vectors for clustering in folder '{folder_name}'" if folder_name else "Too few face vectors for clustering"
            }

        # Extract vectors for each record
        vectors_list = []
        valid_metas = []
        for r in records:
            i_id = r.get("int_id")
            if i_id is None:
                continue
            vec = self.engine.reconstruct_vector(IDX_FACES, int(i_id))
            if vec is not None:
                vectors_list.append(vec)
                meta = dict(r.get("metadata", {}) or {})
                if "image_id" not in meta and "id" in r:
                    parts = r["id"].split("_")
                    if len(parts) >= 2:
                        meta["image_id"] = parts[1]
                if "url" not in meta and "url" in r:
                    meta["url"] = r["url"]
                valid_metas.append(meta)

        if len(vectors_list) < min_cluster_size:
            return {
                "status": "success",
                "clusters_found": 0,
                "total_faces": len(vectors_list),
                "folder": folder_name,
                "message": "Not enough reconstructible vectors to cluster"
            }

        vectors = np.array(vectors_list, dtype=np.float32)
        labels = run_hdbscan_clustering(vectors, min_cluster_size=min_cluster_size, epsilon=epsilon)

        unique_labels = [lbl for lbl in set(labels) if lbl != -1]
        clusters_created = 0

        for lbl in unique_labels:
            indices = np.where(labels == lbl)[0]
            cluster_vecs = vectors[indices]
            cluster_metas = [valid_metas[i] for i in indices]

            rep = select_cluster_representative(cluster_vecs, cluster_metas)
            prefix = f"{folder_name}_" if folder_name else ""
            cluster_id = f"cluster_{prefix}{lbl}"
            person_name = f"{folder_name} - Person {lbl + 1}" if folder_name else f"Person {lbl + 1}"

            self.repo.save_face_cluster(
                cluster_id=cluster_id,
                person_name=person_name,
                face_count=len(indices),
                sample_crop_urls=[rep.get("image_id", "")],
                user_id=user_id or "system",
                folder=folder_name,
            )
            clusters_created += 1

        logger.info("[Face Clustering] Finished clustering: discovered %d identity clusters across %d indexed faces",
                    clusters_created, len(vectors))
        return {
            "status": "success",
            "clusters_found": clusters_created,
            "total_faces": len(vectors),
            "folder": folder_name,
            "message": f"Successfully clustered {len(vectors)} faces into {clusters_created} identity groups"
        }

    def get_clusters(self, folder: Optional[str] = None, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.repo.get_all_face_clusters(folder=folder, user_id=user_id)

    def rename_cluster(self, cluster_id: str, new_name: str) -> bool:
        return self.repo.update_cluster_name(cluster_id, new_name)

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.repo.get_job_by_id(job_id)

