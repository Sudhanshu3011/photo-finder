"""
src/modules/auth/jwt_manager.py — Standard-compliant HS256 JWT Token Issuance & Verification.
Uses Python standard library (hmac + hashlib + base64 + json) with zero third-party dependencies.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional

JWT_SECRET = os.getenv("JWT_SECRET", "visual-search-default-secret-key-replace-in-production").encode("utf-8")
DEFAULT_TOKEN_EXPIRY_SECONDS = int(os.getenv("JWT_EXPIRY_SECONDS", "86400"))  # 24 hours


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (4 - (len(data) % 4)) if (len(data) % 4) != 0 else ""
    return base64.urlsafe_b64decode(data + padding)


def create_access_token(
    data: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    role: str = "user",
    expires_in_seconds: int = DEFAULT_TOKEN_EXPIRY_SECONDS,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Issues an HS256 signed JWT token.
    Supports either passing a dictionary via `data` or keyword parameters `user_id`, `role`.
    """
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    if data:
        payload.update(data)
    elif user_id:
        payload["sub"] = user_id
        payload["role"] = role

    if extra_claims:
        payload.update(extra_claims)

    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    msg = f"{header_b64}.{payload_b64}".encode("utf-8")
    sig = hmac.new(JWT_SECRET, msg, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decodes and validates HS256 signature and token expiry.
    Returns payload dictionary or None if invalid or expired.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, sig_b64 = parts
        msg = f"{header_b64}.{payload_b64}".encode("utf-8")
        expected_sig = hmac.new(JWT_SECRET, msg, hashlib.sha256).digest()
        actual_sig = _b64url_decode(sig_b64)

        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        payload_bytes = _b64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))

        # Expiry check
        exp = payload.get("exp")
        if exp is not None and time.time() > float(exp):
            return None

        return payload
    except Exception:
        return None

