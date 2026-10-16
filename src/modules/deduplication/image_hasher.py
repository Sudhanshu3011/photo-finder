"""
src/modules/deduplication/image_hasher.py — Image Deduplication and Hashing.
Calculates SHA256 cryptographic checksum and perceptual difference hash (dHash)
to eliminate redundant deep learning inferences across burst-mode and re-uploaded photos.
"""
import hashlib
import io
from typing import Optional
from PIL import Image

from src.core.logging import log
from src.core.tenant_context import get_current_tenant_id


def compute_sha256(image_bytes: bytes) -> str:
    """Computes exact cryptographic SHA256 hex digest of raw image bytes."""
    return hashlib.sha256(image_bytes).hexdigest()


def compute_phash(image_bytes: bytes) -> str:
    """
    Computes perceptual difference hash (dHash) using Pillow.
    Resizes image to 9x8 grayscale, evaluates row-wise adjacent pixel gradients,
    and returns a 64-bit hex string.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("L")
        img = img.resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(img.getdata())

        diff = []
        for row in range(8):
            for col in range(8):
                pixel_left = pixels[row * 9 + col]
                pixel_right = pixels[row * 9 + col + 1]
                diff.append(pixel_left > pixel_right)

        decimal_value = 0
        for bit in diff:
            decimal_value = (decimal_value << 1) | int(bit)

        return f"{decimal_value:016x}"
    except Exception as e:
        log("WARN", "dedup.phash_failed", error=str(e))
        return ""


def hamming_distance(hash1: str, hash2: str) -> int:
    """Calculates bitwise Hamming distance between two 64-bit hex perceptual hashes."""
    if not hash1 or not hash2 or len(hash1) != len(hash2):
        return 64
    try:
        val1 = int(hash1, 16)
        val2 = int(hash2, 16)
        return bin(val1 ^ val2).count("1")
    except ValueError:
        return 64


def is_perceptual_duplicate(phash1: str, phash2: str, max_distance: int = 3) -> bool:
    """
    Determines if two images are perceptual near-duplicates.
    Default threshold <= 3 allows minor compression artifacts or scaling differences.
    """
    return hamming_distance(phash1, phash2) <= max_distance


def find_duplicate_image(
    sha256_hash: Optional[str] = None,
    phash: Optional[str] = None,
    tenant_id: Optional[str] = None,
    sha256: Optional[str] = None,
) -> Optional[dict]:
    """
    Looks up existing vector metadata for the tenant to determine if an identical
    or near-duplicate image was already processed and indexed.
    """
    from src.modules.infra.postgres_repository import get_postgres_repo

    hash_val = sha256 or sha256_hash or ""
    tid = (tenant_id or get_current_tenant_id()).strip()
    repo = get_postgres_repo()
    return repo.find_duplicate_by_hash(sha256=hash_val, phash=phash, tenant_id=tid)

