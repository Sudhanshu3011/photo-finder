import re
import math
from fastapi import Request

# Get the Real IP of the User not the infra IP (if behind proxy) for logging and abuse monitoring.
def get_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

# Returns Boolean indicating if the provided key is the same as the default value (ignoring whitespace).
def is_default_key(key: str, default: str) -> bool:
    if not key or not default:
        return False
    return key.strip() == default.strip()

# Takes The Cloduinary URL and extracts the credentials from it and returns a dict with cloud_name, api_key and api_secret.
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

# Replace everything except letters, numbers, _, -, . with underscores
def sanitize_filename(filename: str) -> str:
    if not filename:
        return "unnamed_file"
    return re.sub(r'[^a-zA-Z0-9_\-\.]', '_', filename)

# Lower Casing the File Name
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

# Extracting the ID from The URL
def url_to_public_id(url: str) -> str:
    if not url:
        return ""
    try:
        parts = url.split("/upload/")
        if len(parts) > 1:
            path = parts[1].split("/", 1)[-1]
            # Splits From Right and place that thing first in list
            return path.rsplit(".", 1)[0]
        return ""
    except Exception:
        return ""


def cld_thumb_url(url: str) -> str:
    if not url:
        return ""
    return url.replace("/upload/", "/upload/c_limit,w_500/")


def cld_face_thumb_url(url: str, width: int = 300) -> str:
    """Generate optimized thumbnail URL for face images (smaller than general thumbs)."""
    if not url:
        return ""
    return url.replace("/upload/", f"/upload/c_limit,w_{width},q_30,f_auto/")


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
        threshold = 0.26   # Lowered to match new FUSED_MATCH_THRESHOLD
        k = 15.0           # Gentler curve — more visible results
    else:
        threshold = 0.50
        k = 18.0

    probability = 1 / (1 + math.exp(-k * (raw_score - threshold)))
    return min(1.0, max(0.0, round(probability, 4)))