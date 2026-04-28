import re
import math
from fastapi import Request


def get_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def is_default_key(key: str, default: str) -> bool:
    if not key or not default:
        return False
    return key.strip() == default.strip()


def get_cloudinary_creds(url: str) -> dict:
    if not url or not url.startswith("cloudinary://"):
        return {}
    try:
        creds = url.replace("cloudinary://", "")
        auth, cloud_name = creds.split("@")
        api_key, api_secret = auth.split(":")
        return {
            "cloud_name": cloud_name,
            "api_key": api_key,
            "api_secret": api_secret,
        }
    except ValueError:
        return {}


def sanitize_filename(filename: str) -> str:
    if not filename:
        return "unnamed_file"
    return re.sub(r'[^a-zA-Z0-9_\-\.]', '_', filename)


def standardize_category_name(name: str) -> str:
    if not name:
        return "uncategorized"
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', name.lower())


def to_list(vector) -> list[float]:
    if vector is None:
        return []
    try:
        return [float(x) for x in vector]
    except TypeError:
        return []


def url_to_public_id(url: str) -> str:
    if not url:
        return ""
    try:
        parts = url.split("/upload/")
        if len(parts) > 1:
            path = parts[1].split("/", 1)[-1]
            return path.rsplit(".", 1)[0]
        return ""
    except Exception:
        return ""


def cld_thumb_url(url: str) -> str:
    if not url:
        return ""
    return url.replace("/upload/", "/upload/c_limit,w_500/")


def face_ui_score(raw_score: float, mode: str = "fused") -> float:
    """
    Platt-scaled probability score for the UI.
    Different calibration depending on which backend produced the raw score.

    mode="fused"  — new split-index fused score (0.6*arcface + 0.4*adaface)
                   Decision boundary at ~0.30, steep drop-off for imposters.
    mode="legacy" — old 1024-d concatenated vector cosine
                   Decision boundary at 0.50 (original calibration).

    The sigmoid maps raw cosine → probability of match for the UI.
    """
    if mode == "fused":
        threshold = 0.30   # Balanced boundary for fused scores
        k = 20.0           # Steep drop-off
    else:
        threshold = 0.50
        k = 18.0

    probability = 1 / (1 + math.exp(-k * (raw_score - threshold)))
    return min(1.0, max(0.0, round(probability, 4)))