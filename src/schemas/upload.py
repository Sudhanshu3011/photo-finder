"""Pydantic V2 schemas for image uploads."""
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class UploadMetadata(BaseModel):
    """Multipart metadata parameters passed alongside files."""
    model_config = ConfigDict(populate_by_name=True)

    folder_name: str = Field(..., description="Target category or folder name (e.g. 'wedding', 'event')")
    detect_faces: bool = Field(default=True, description="Whether to run face detection and embedding")
    user_id: Optional[str] = Field(default="", description="Optional user ID for isolation")
    async_mode: bool = Field(default=False, description="Enqueue processing as background job")


class UploadVectorSummary(BaseModel):
    """Breakdown of generated vector embeddings."""
    files: int = Field(..., ge=0, description="Number of files processed")
    face_vectors: int = Field(default=0, ge=0, description="Face embeddings count (ArcFace / legacy)")
    adaface_vectors: int = Field(default=0, ge=0, description="AdaFace embeddings count")
    object_vectors: int = Field(default=0, ge=0, description="General object embeddings count (DINOv2 / SigLIP)")
    index_mode: str = Field(default="split", description="Index routing mode: 'split' or 'legacy'")


class UploadResponse(BaseModel):
    """Synchronous upload completion response."""
    model_config = ConfigDict(populate_by_name=True)

    message: str = Field(default="Done!", description="Status message")
    user_id: Optional[str] = Field(default=None, description="Persistent user UUID")
    urls: List[str] = Field(default_factory=list, description="Cloudinary CDN URLs of stored images")
    summary: UploadVectorSummary = Field(..., description="Summary of extracted vectors")


class AsyncUploadQueuedResponse(BaseModel):
    """Asynchronous upload queued response."""
    model_config = ConfigDict(populate_by_name=True)

    message: str = Field(default="Upload queued", description="Status message")
    job_id: str = Field(..., description="Unique job identifier")
    user_id: Optional[str] = Field(default=None, description="Persistent user UUID")
    status_url: str = Field(..., description="Status polling endpoint")
    total_files: int = Field(..., ge=1, description="Total files queued for processing")
    urls: List[str] = Field(default_factory=list, description="Cloudinary CDN URLs of stored images")
