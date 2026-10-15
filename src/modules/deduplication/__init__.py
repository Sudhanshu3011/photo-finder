"""
src/modules/deduplication/__init__.py — Image Deduplication Module.
Provides cryptographic (SHA256) and perceptual (dHash) deduplication.
"""
from src.modules.deduplication.image_hasher import (
    compute_sha256,
    compute_phash,
    hamming_distance,
    is_perceptual_duplicate,
    find_duplicate_image,
)

__all__ = [
    "compute_sha256",
    "compute_phash",
    "hamming_distance",
    "is_perceptual_duplicate",
    "find_duplicate_image",
]

