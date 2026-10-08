"""
src/modules/vision/image_quality.py — Image Quality & Sharpness Assessment.
Calculates Laplacian variance to detect blurry images and evaluates image resolution.
"""
from typing import Dict, Any, Union
import cv2
import numpy as np
from src.core.logging import log


def compute_blur_score(cv_img: np.ndarray) -> float:
    """
    Computes image sharpness score using the variance of the Laplacian.
    Higher values indicate sharp edges; values below threshold (e.g. 15.0) indicate blur.
    """
    if cv_img is None or cv_img.size == 0:
        return 0.0

    if len(cv_img.shape) == 3:
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    else:
        gray = cv_img

    score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return score


def is_acceptable_resolution(cv_img: np.ndarray, min_dimension: int = 50) -> bool:
    """Checks whether an image meets minimal resolution requirements."""
    if cv_img is None:
        return False
    h, w = cv_img.shape[:2]
    return h >= min_dimension and w >= min_dimension


def assess_image_quality(
    image_input: Union[bytes, np.ndarray],
    min_dimension: int = 50,
    blur_threshold: float = 15.0,
) -> Dict[str, Any]:
    """
    Evaluates image validity, dimensions, and sharpness.
    `image_input` can be either raw bytes or np.ndarray.
    """
    if isinstance(image_input, (bytes, bytearray)):
        nparr = np.frombuffer(image_input, np.uint8)
        cv_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    else:
        cv_img = image_input

    if cv_img is None or cv_img.size == 0:
        log("WARN", "vision.quality.decode_failed")
        return {
            "is_valid": False,
            "reason": "Could not decode image or empty data",
            "width": 0,
            "height": 0,
            "blur_score": 0.0,
            "is_blurry": True,
        }

    h, w = cv_img.shape[:2]
    if not is_acceptable_resolution(cv_img, min_dimension):
        log("WARN", "vision.quality.resolution_low", width=w, height=h, min_dim=min_dimension)
        return {
            "is_valid": False,
            "reason": f"Image dimensions ({w}x{h}) smaller than required minimum ({min_dimension}px)",
            "width": w,
            "height": h,
            "blur_score": 0.0,
            "is_blurry": False,
        }

    blur = compute_blur_score(cv_img)
    is_blurry = blur < blur_threshold

    log("DEBUG", "vision.quality.assessed", width=w, height=h, blur_score=blur, is_blurry=is_blurry)
    return {
        "is_valid": True,
        "reason": None,
        "width": w,
        "height": h,
        "blur_score": blur,
        "is_blurry": is_blurry,
    }

