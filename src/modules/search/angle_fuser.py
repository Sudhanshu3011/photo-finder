import logging
from typing import Dict, List, Optional
import numpy as np

logger = logging.getLogger("src.modules.search.angle_fuser")

def fuse_angle_embeddings(
    embeddings: Dict[str, np.ndarray],
    weights: Optional[Dict[str, float]] = None
) -> Optional[np.ndarray]:
    """
    Fuse multi-angle face embeddings (e.g. 'front', 'left', 'right') into a single normalized vector.
    
    Default weights:
        front: 0.50
        left:  0.25
        right: 0.25
    """
    if not embeddings:
        logger.warning("[angle_fuser.fuse] No embeddings provided for fusion")
        return None

    if weights is None:
        weights = {"front": 0.50, "left": 0.25, "right": 0.25}

    valid_vectors = []
    valid_weights = []

    for angle, vec in embeddings.items():
        if vec is not None and isinstance(vec, np.ndarray) and vec.size > 0:
            norm = np.linalg.norm(vec)
            if norm > 1e-6:
                norm_vec = vec.astype(np.float32) / norm
                valid_vectors.append(norm_vec)
                w = weights.get(angle.lower(), 1.0)
                valid_weights.append(w)

    if not valid_vectors:
        logger.warning("[angle_fuser.fuse] All provided embeddings were zero or invalid")
        return None

    total_weight = sum(valid_weights)
    if total_weight <= 0:
        total_weight = 1.0

    normalized_weights = [w / total_weight for w in valid_weights]
    
    fused = np.zeros_like(valid_vectors[0], dtype=np.float32)
    for vec, w in zip(valid_vectors, normalized_weights):
        fused += vec * w

    fused_norm = np.linalg.norm(fused)
    if fused_norm > 1e-6:
        fused = fused / fused_norm

    logger.debug("[angle_fuser.fuse] Successfully fused %d angle embeddings into vector of shape %s", len(valid_vectors), fused.shape)
    return fused

