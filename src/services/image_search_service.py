import asyncio
import logging
import time
from typing import Dict, Any, List, Optional
import numpy as np

from src.core.config import (
    IDX_FACES,
    IDX_FACES_ARCFACE,
    IDX_FACES_ADAFACE,
    IDX_OBJECTS,
    FACE_MATCH_THRESHOLD,
    OBJECT_MATCH_THRESHOLD,
    FACE_SEARCH_TOP_K,
    OBJECT_SEARCH_TOP_K,
    FACE_DIM,
    ADAFACE_DIM,
)
from src.modules.infra.faiss_engine import vector_engine
from src.modules.search.vector_scorer import score_face_matches, score_object_matches
from src.modules.search.angle_fuser import fuse_angle_embeddings
from src.modules.vision.face_detector import detect_faces
from src.modules.vision.face_embedder import extract_face_embeddings
from src.modules.vision.object_embedder import extract_object_embedding

logger = logging.getLogger("src.services.image_search_service")

class ImageSearchService:
    """
    High-level orchestrator for multimodal visual search.
    Delegates similarity scoring and angle fusion to src.modules.search.*
    and indexing to src.modules.infra.faiss_engine.
    """

    def __init__(self, ai=None, engine=None):
        self.ai = ai
        self.engine = engine or vector_engine

    def search_by_face_vector(
        self,
        arcface_vec: List[float],
        adaface_vec: Optional[List[float]] = None,
        top_k: int = FACE_SEARCH_TOP_K,
        threshold: float = FACE_MATCH_THRESHOLD,
        filter_dict: Optional[dict] = None
    ) -> List[Dict[str, Any]]:
        """Search faces using raw embedding vectors with score fusion."""
        has_ada = bool(adaface_vec and len(adaface_vec) == ADAFACE_DIM)
        scope = f"folder='{filter_dict['folder']}'" if (filter_dict and "folder" in filter_dict) else "all gallery folders"
        fusion_info = "Dual-model (ArcFace 512D + AdaFace 512D)" if has_ada else "Single-model (ArcFace 512D)"
        logger.info("[Face Search] Querying %s | Scope: %s | Max matches: %d | Min similarity threshold: %.2f",
                    fusion_info, scope, top_k, threshold)

        # 1. Search primary ArcFace index
        arc_matches = self.engine.search_vectors(
            index_name=IDX_FACES_ARCFACE if IDX_FACES_ARCFACE in self.engine.indices else IDX_FACES,
            query_vector=arcface_vec,
            top_k=top_k * 2,
            filter_dict=filter_dict
        )
        if not arc_matches and IDX_FACES in self.engine.indices and IDX_FACES != IDX_FACES_ARCFACE:
            arc_matches = self.engine.search_vectors(
                index_name=IDX_FACES,
                query_vector=arcface_vec,
                top_k=top_k * 2,
                filter_dict=filter_dict
            )

        # 2. Search AdaFace index if vector is provided
        ada_matches = []
        if has_ada and IDX_FACES_ADAFACE in self.engine.indices:
            ada_matches = self.engine.search_vectors(
                index_name=IDX_FACES_ADAFACE,
                query_vector=adaface_vec,
                top_k=top_k * 2,
                filter_dict=filter_dict
            )

        # 3. Fuse scores (0.6 * ArcFace + 0.4 * AdaFace)
        scored = score_face_matches(
            arc_matches=arc_matches,
            ada_matches=ada_matches if ada_matches else None,
            threshold=threshold
        )
        return scored[:top_k]

    def search_by_object_vector(
        self,
        object_vec: List[float],
        top_k: int = OBJECT_SEARCH_TOP_K,
        threshold: float = OBJECT_MATCH_THRESHOLD,
        filter_dict: Optional[dict] = None
    ) -> List[Dict[str, Any]]:
        """Search scenes/objects using visual embedding vectors."""
        scope = f"folder='{filter_dict['folder']}'" if (filter_dict and "folder" in filter_dict) else "all gallery folders"
        logger.info("[Object Search] Querying DINOv2+SigLIP fused vectors | Scope: %s | Max matches: %d | Min similarity threshold: %.2f",
                    scope, top_k, threshold)
        
        matches = self.engine.search_vectors(
            index_name=IDX_OBJECTS,
            query_vector=object_vec,
            top_k=top_k * 2,
            filter_dict=filter_dict
        )

        scored = score_object_matches(
            matches=matches,
            threshold=threshold
        )
        return scored[:top_k]

    def search_by_image(
        self,
        cv_img: np.ndarray,
        search_faces: bool = True,
        search_objects: bool = True,
        top_k: int = FACE_SEARCH_TOP_K,
        threshold: float = FACE_MATCH_THRESHOLD,
        filter_dict: Optional[dict] = None
    ) -> Dict[str, Any]:
        """
        Multimodal search by query image. Detects faces or extracts object embeddings,
        then queries the corresponding indices.
        """
        results: Dict[str, Any] = {
            "query_type": "none",
            "total_matches": 0,
            "results": []
        }

        # 1. Face lane
        if search_faces and self.ai is not None:
            faces = detect_faces(self.ai, cv_img)
            if faces:
                results["query_type"] = "face"
                logger.info("[Image Search] Detected %d face candidate(s) in query image. Proceeding with face search.", len(faces))
                face_matches_acc = []
                for idx, f in enumerate(faces):
                    target_face = f if (isinstance(f, dict) and "arcface_vector" in f) else f.get("face_obj", f)
                    emb = extract_face_embeddings(self.ai, target_face)
                    arc_vec = emb.get("arcface_vector")
                    ada_vec = emb.get("adaface_vector")

                    if arc_vec and len(arc_vec) == FACE_DIM:
                        has_valid_ada = bool(ada_vec and len(ada_vec) == ADAFACE_DIM)
                        logger.info("[Image Search] Face #%d embeddings extracted (ArcFace=512D, AdaFace=%s). Running vector matching...",
                                    idx + 1, "512D" if has_valid_ada else "Not Available")
                        m = self.search_by_face_vector(
                            arcface_vec=arc_vec,
                            adaface_vec=ada_vec if has_valid_ada else None,
                            top_k=top_k,
                            threshold=threshold,
                            filter_dict=filter_dict
                        )
                        face_matches_acc.extend(m)
                    else:
                        logger.warning("[Image Search] Face #%d did not produce valid ArcFace embeddings. Skipping.", idx + 1)
                
                # Deduplicate by image_id keeping highest score
                best_by_img: Dict[str, Dict[str, Any]] = {}
                for m in face_matches_acc:
                    img_id = m.get("image_id")
                    if not img_id:
                        continue
                    if img_id not in best_by_img or m.get("score", 0) > best_by_img[img_id].get("score", 0):
                        best_by_img[img_id] = m
                
                sorted_res = sorted(best_by_img.values(), key=lambda x: x.get("score", 0), reverse=True)[:top_k]
                results["results"] = sorted_res
                results["total_matches"] = len(sorted_res)
                logger.info("[Image Search] Face search complete. Discovered %d unique matching photo(s).", len(sorted_res))
                return results

        # 2. Object lane
        if search_objects and self.ai is not None:
            logger.info("[Image Search] No faces detected in query image. Routing to general scene/object visual matching.")
            obj_vec = extract_object_embedding(self.ai, cv_img)
            if obj_vec:
                results["query_type"] = "object"
                obj_matches = self.search_by_object_vector(
                    object_vec=obj_vec,
                    top_k=top_k,
                    threshold=threshold,
                    filter_dict=filter_dict
                )
                results["results"] = obj_matches
                results["total_matches"] = len(obj_matches)
                logger.info("[Image Search] Object search complete. Discovered %d matching photo(s).", len(obj_matches))
                return results

        return results

    def search_multi_angle(
        self,
        angle_embeddings: Dict[str, np.ndarray],
        top_k: int = FACE_SEARCH_TOP_K,
        threshold: float = FACE_MATCH_THRESHOLD,
        filter_dict: Optional[dict] = None
    ) -> List[Dict[str, Any]]:
        """
        Fuses multi-angle embeddings (e.g. 'front', 'left', 'right')
        into a composite vector and queries the face store.
        """
        fused = fuse_angle_embeddings(angle_embeddings)
        if fused is None:
            logger.warning("[image_search_service.search_multi_angle] Multi-angle fusion yielded empty vector")
            return []

        return self.search_by_face_vector(
            arcface_vec=[float(x) for x in fused],
            top_k=top_k,
            threshold=threshold,
            filter_dict=filter_dict
        )


_image_search_service_instance: Optional[ImageSearchService] = None


def get_image_search_service() -> ImageSearchService:
    global _image_search_service_instance
    if _image_search_service_instance is None:
        _image_search_service_instance = ImageSearchService()
    return _image_search_service_instance

