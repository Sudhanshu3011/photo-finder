"""Pydantic V2 Schemas for Visual Search API."""

from src.schemas.auth_schemas import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    UserProfileResponse,
)
from src.schemas.upload_schemas import (
    PhotoUploadItem,
    PhotoUploadResponse,
    BatchUploadResponse,
    CategoryListResponse,
)
from src.schemas.processing_schemas import (
    JobProgressResponse,
    FaceClusterResponse,
    ClusterRenameRequest,
    ClusteringTriggerResponse,
    ImageProcessResponse,
)
from src.schemas.search_schemas import (
    MatchItem,
    SearchResponse,
    MultiAngleSearchRequest,
)

__all__ = [
    "RegisterRequest",
    "LoginRequest",
    "TokenResponse",
    "UserProfileResponse",
    "PhotoUploadItem",
    "PhotoUploadResponse",
    "BatchUploadResponse",
    "CategoryListResponse",
    "JobProgressResponse",
    "FaceClusterResponse",
    "ClusterRenameRequest",
    "ClusteringTriggerResponse",
    "ImageProcessResponse",
    "MatchItem",
    "SearchResponse",
    "MultiAngleSearchRequest",
]
