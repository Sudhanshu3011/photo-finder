"""Pydantic V2 schemas for search requests, filters, and matches."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class SearchParams(BaseModel):
    """Multipart search parameters for query image upload."""
    model_config = ConfigDict(populate_by_name=True)

    detect_faces: bool = Field(default=True, description="Whether to detect and search faces")
    user_id: str = Field(default="", description="Optional user ID for isolation")
    folder_name: Optional[str] = Field(default=None, description="Filter matches by specific folder")
    score_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Minimum similarity score")


class MatchItem(BaseModel):
    """Individual vector match item returned by similarity search."""
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., description="Vector ID")
    score: float = Field(..., description="Similarity confidence score (0.0 to 1.0)")
    url: Optional[str] = Field(default=None, description="Image URL")
    folder: Optional[str] = Field(default=None, description="Folder / category name")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Metadata stored in FAISS vector store")


class FaceGroupResult(BaseModel):
    """Group of matches corresponding to a single detected query face."""
    model_config = ConfigDict(populate_by_name=True)

    face_idx: int = Field(..., description="Index of face in query image")
    query_crop: Optional[str] = Field(default=None, description="Base64 thumbnail of query face")
    matches: List[MatchItem] = Field(default_factory=list, description="Top matching gallery faces")


class SearchResponse(BaseModel):
    """Complete search response contract."""
    model_config = ConfigDict(populate_by_name=True)

    mode: str = Field(..., description="Search match mode: 'face', 'object', 'both', or 'none'")
    face_groups: List[FaceGroupResult] = Field(default_factory=list, description="Matches grouped by query face")
    results: List[MatchItem] = Field(default_factory=list, description="Flat list of face matches")
    object_results: List[MatchItem] = Field(default_factory=list, description="General object similarity matches")
