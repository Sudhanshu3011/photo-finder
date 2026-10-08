"""
src/modules/vision/face_detector.py — Face Detection & Alignment Module.
Detects faces using YOLO / InsightFace models, computes quality filters, and extracts aligned crops.
Delegates to unified AIModelManager multi-scale detection and parallel dual-embedding extraction.
"""
from typing import Any, Dict, List, Optional
import numpy as np

from src.core.logging import log
from src.modules.vision.image_quality import compute_blur_score


def detect_faces(ai_manager, cv_img: np.ndarray, min_blur: float = 15.0) -> List[Dict[str, Any]]:
    """
    Detects faces in an image, computes landmarks, and extracts aligned crops.
    Extracts ArcFace embeddings via InsightFace and AdaFace embeddings via iResNet.
    Returns list of detected face objects with bounding box, crop, and quality metadata.
    """
    if ai_manager is None:
        log("WARN", "vision.detector.no_ai_model", message="AI Model Manager is not loaded.")
        return []

    try:
        # 1. Use the unified AIModelManager multi-scale & CLAHE detection pipeline if available
        if hasattr(ai_manager, "_detect_and_encode_faces"):
            faces = ai_manager._detect_and_encode_faces(cv_img, is_bgr=True)
            valid = []
            for f in faces:
                if f.get("blur_score", 100.0) < min_blur:
                    continue
                if "face_obj" not in f:
                    f["face_obj"] = f
                valid.append(f)
            log("INFO", "vision.detector.faces_accepted",
                message=f"Face detection completed: accepted {len(valid)} sharp face(s) out of {len(faces)} total candidate(s)")
            return valid

        # 2. Fallback for test mocks that only expose face_app
        faces = ai_manager.face_app.get(cv_img) if hasattr(ai_manager, "face_app") and ai_manager.face_app else []
        log("INFO", "vision.detector.raw_faces_found", message=f"Fallback face_app detected {len(faces)} raw face candidate(s)")

        results = []
        for idx, face in enumerate(faces):
            bbox = face.bbox.astype(int)
            x1, y1, x2, y2 = max(0, bbox[0]), max(0, bbox[1]), min(cv_img.shape[1], bbox[2]), min(cv_img.shape[0], bbox[3])
            crop = cv_img[y1:y2, x1:x2]

            blur_val = compute_blur_score(crop)
            if blur_val < min_blur:
                log("DEBUG", "vision.detector.face_rejected_blur",
                    message=f"Rejected face candidate #{idx}: blur score {blur_val:.1f} below minimum threshold {min_blur}")
                continue

            results.append({
                "face_idx": idx,
                "bbox": [int(x) for x in bbox],
                "blur_score": blur_val,
                "face_obj": face,
            })

        log("INFO", "vision.detector.faces_accepted",
            message=f"Face detection completed: accepted {len(results)} sharp face(s) out of {len(faces)} total candidate(s)")
        return results
    except Exception as e:
        log("ERROR", "vision.detector.failed", error=str(e))
        return []
