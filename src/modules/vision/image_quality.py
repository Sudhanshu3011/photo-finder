import os
from typing import Dict, Any, Union, Optional
import cv2
import numpy as np
from src.core.logging import log
from src.core.config import ALLOWED_IMAGE_EXTENSIONS, ALLOWED_IMAGE_MIMES


def is_supported_image_extension(filename: str) -> bool:
    """Validate file extension against allowed image types (.jpg, .jpeg, .png, .webp, .bmp, .tiff)."""
    if not filename:
        return True
    ext = os.path.splitext(filename.lower())[1]
    return ext in ALLOWED_IMAGE_EXTENSIONS


def detect_image_format_from_bytes(data: bytes) -> Optional[str]:
    """Detect image format by inspecting file signature / magic bytes."""
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if len(data) >= 2 and data[:2] == b"BM":
        return "bmp"
    if len(data) >= 4 and (data[:4] in (b"II*\x00", b"MM\x00*")):
        return "tiff"
    return None


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
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Evaluates image validity, format, dimensions, and sharpness.
    `image_input` can be either raw bytes or np.ndarray.
    """
    # 1. Extension whitelist check
    if filename and not is_supported_image_extension(filename):
        ext = os.path.splitext(filename.lower())[1] or "unknown"
        log("WARN", "vision.quality.unsupported_extension", filename=filename, ext=ext)
        return {
            "is_valid": False,
            "reason": f"Unsupported file extension '{ext}'. Allowed formats: {', '.join(sorted(ALLOWED_IMAGE_EXTENSIONS))}",
            "width": 0,
            "height": 0,
            "blur_score": 0.0,
            "is_blurry": True,
            "format": None,
        }

    # 2. Magic byte inspection & decoding
    detected_format = None
    if isinstance(image_input, (bytes, bytearray)):
        raw_b = bytes(image_input)
        detected_format = detect_image_format_from_bytes(raw_b)
        if detected_format is None:
            log("WARN", "vision.quality.unsupported_magic_bytes")
            return {
                "is_valid": False,
                "reason": "Unsupported image format or invalid image signature. Allowed formats: JPEG, PNG, WebP, BMP, TIFF.",
                "width": 0,
                "height": 0,
                "blur_score": 0.0,
                "is_blurry": True,
                "format": None,
            }
        nparr = np.frombuffer(raw_b, np.uint8)
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
            "format": detected_format,
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
        "format": detected_format,
    }

