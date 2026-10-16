from typing import List, Optional
from pydantic import BaseModel, Field

class PhotoUploadItem(BaseModel):
    image_id: str
    filename: str
    status: str
    folder: Optional[str] = "general"
    message: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    is_blurry: Optional[bool] = None
    cloud_url: Optional[str] = None

class PhotoUploadResponse(BaseModel):
    status: str
    data: PhotoUploadItem

class BatchUploadResponse(BaseModel):
    job_id: str
    total: int
    successful: int
    failed: int
    items: List[PhotoUploadItem]

class FolderSyncResponse(BaseModel):
    folder: str
    total_found: int
    synced: int
    failed: int
    items: List[PhotoUploadItem]


class ClientLogEventRequest(BaseModel):
    event: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_\.\-]+$", description="Telemetry event name")
    level: str = Field("INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$", description="Log level")
    payload: Optional[dict] = Field(default_factory=dict, description="Additional context payload (max 16KB)")


class ClientLogEventResponse(BaseModel):
    success: bool
    message: str


class S3HealthResponse(BaseModel):
    status: str
    storage: str
    bucket: str
    region: Optional[str] = None
    accessible: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    timestamp: str




