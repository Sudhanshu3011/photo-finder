"""
src/modules/vision/face_embedder.py — ArcFace & AdaFace Feature Embedding Extraction.
Generates 512-dimensional normalized embeddings for face identification and verification.
"""
from typing import Any, Dict, List, Optional
import numpy as np
from src.core.logging import log


def extract_face_embeddings(ai_manager, face_obj) -> Dict[str, Any]:
    """
    Extracts ArcFace and optional AdaFace embeddings from a detected face object or dict.
    Returns normalized vectors ready for cosine similarity comparison.
    """
    try:
        arcface_vec = None
        adaface_vec = None
        has_adaface = False

        # 1. If face_obj is a dict containing pre-computed vectors (from AIModelManager)
        if isinstance(face_obj, dict) and "arcface_vector" in face_obj and face_obj["arcface_vector"] is not None:
            raw_arc = face_obj["arcface_vector"]
            if hasattr(raw_arc, "tolist"):
                arcface_vec = raw_arc.tolist()
            elif isinstance(raw_arc, (list, tuple)):
                arcface_vec = [float(x) for x in raw_arc]

            raw_ada = face_obj.get("adaface_vector")
            if raw_ada is not None:
                if hasattr(raw_ada, "tolist"):
                    adaface_vec = raw_ada.tolist()
                elif isinstance(raw_ada, (list, tuple)):
                    adaface_vec = [float(x) for x in raw_ada]
            has_adaface = face_obj.get("has_adaface", bool(adaface_vec))

        # 2. Fallback: extract from InsightFace Face object (or dict with embedding/normed_embedding)
        if arcface_vec is None:
            normed_arcface = getattr(face_obj, "normed_embedding", None)
            if normed_arcface is None and isinstance(face_obj, dict):
                normed_arcface = face_obj.get("normed_embedding")

            if normed_arcface is None:
                emb = getattr(face_obj, "embedding", None)
                if emb is None and isinstance(face_obj, dict):
                    emb = face_obj.get("embedding")
                if emb is not None:
                    norm = np.linalg.norm(emb)
                    normed_arcface = emb / norm if norm > 0 else emb

            if normed_arcface is not None:
                if hasattr(normed_arcface, "tolist"):
                    arcface_vec = normed_arcface.tolist()
                else:
                    arcface_vec = [float(x) for x in normed_arcface]

            ada_emb = getattr(face_obj, "adaface_embedding", None)
            if ada_emb is not None:
                if hasattr(ada_emb, "tolist"):
                    adaface_vec = ada_emb.tolist()
                else:
                    adaface_vec = [float(x) for x in ada_emb]
                has_adaface = True

        arc_status = f"{len(arcface_vec)}D" if arcface_vec else "None"
        ada_status = f"{len(adaface_vec)}D" if (adaface_vec and has_adaface) else "None"
        log("INFO", "vision.embedder.face_extracted",
            message=f"Face embedding extraction complete: ArcFace={arc_status}, AdaFace={ada_status}")
        return {
            "arcface_vector": arcface_vec or [],
            "adaface_vector": adaface_vec,
            "has_adaface": has_adaface,
        }
    except Exception as e:
        log("ERROR", "vision.embedder.face_failed", error=f"Failed extracting face embeddings: {str(e)}")
        return {"arcface_vector": [], "adaface_vector": None, "has_adaface": False}


