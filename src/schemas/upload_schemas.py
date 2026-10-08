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




