import re
import math
import httpx
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

# S3 and Image URL Helpers
def get_s3_key_from_url(url: str) -> str:
    """Extract object key from standard S3 URL format."""
    if not url:
        return ""
    if ".amazonaws.com/" in url:
        return url.split(".amazonaws.com/", 1)[-1].split("?")[0]
    return url.split("/")[-1]


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


async def fetch_image_bytes_from_url(url: str, timeout: float = 15.0) -> bytes:
    """Download image bytes from an HTTP/HTTPS URL (e.g. AWS S3 / CDN)."""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content