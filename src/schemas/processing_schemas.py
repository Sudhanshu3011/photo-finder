from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field

class JobProgressResponse(BaseModel):
    job_id: str
    status: str
    total_images: int = 0
    processed_images: int = 0
    total_files: Optional[int] = 0
    processed_files: Optional[int] = 0
    current_stage: Optional[str] = None
    logs: List[str] = []
    error_message: Optional[str] = None
    created_at: Optional[Union[str, datetime]] = None
    updated_at: Optional[Union[str, datetime]] = None

class FaceClusterResponse(BaseModel):
    cluster_id: str
    person_name: str
    face_count: int
    folder: Optional[str] = None
    medoid_image_url: Optional[str] = None
    sample_crop_urls: List[str] = []
    created_at: Optional[Union[str, datetime]] = None

class ClusterRenameRequest(BaseModel):
    person_name: str = Field(..., min_length=1, max_length=100, description="New name for the person")

class ClusteringTriggerResponse(BaseModel):
    status: str
    clusters_found: int
    total_faces: int
    message: str

class ClusterStatusResponse(BaseModel):
    folder_name: str
    total_photos: int
    last_clustered_count: int
    new_photos_since_last_cluster: int
    threshold: int = 25
    ready_for_clustering: bool

class ImageProcessResponse(BaseModel):
    image_id: str
    faces_detected: int
    objects_detected: int
    status: str
    message: Optional[str] = None

