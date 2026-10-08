"""
src/modules/auth/password_hasher.py — Secure Password Hashing & Verification.
Uses PBKDF2-HMAC-SHA256 with cryptographically random salt and constant-time comparison.
Zero external C-dependency risk: runs purely on Python hashlib.
"""
import hashlib
import hmac
import os
import secrets


def hash_password(password: str) -> str:
    """Hashes a password with a random 16-byte salt using PBKDF2-HMAC-SHA256."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations=100_000,
    )
    return f"{salt}:{key.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against the stored salt:hash string."""
    try:
        salt, expected_hash = hashed_password.split(":", 1)
        key = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations=100_000,
        )
        return hmac.compare_digest(key.hex(), expected_hash)
    except Exception:
        return False

