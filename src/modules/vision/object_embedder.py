"""
src/modules/vision/object_embedder.py — General Visual & Object Feature Extraction.
Generates 1536-dimensional normalized embeddings using SigLIP (768D) + DINOv2 (768D) foundation models.
"""
from typing import Any, List, Optional
import numpy as np
from src.core.logging import log


def extract_object_embedding(ai_manager, cv_img: np.ndarray) -> List[float]:
    """
    Extracts L2-normalized 1536-dimensional visual embedding for scene & object recognition.
    """
    if ai_manager is None:
        return []

    try:
        if hasattr(ai_manager, "extract_object_embedding"):
            vec = ai_manager.extract_object_embedding(cv_img)
            log("DEBUG", "vision.embedder.object_extracted", dim=len(vec))
            return [float(x) for x in vec]
        return []
    except Exception as e:
        log("ERROR", "vision.embedder.object_failed", error=str(e))
        return []

