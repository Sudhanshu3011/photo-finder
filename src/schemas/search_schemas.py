from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

class MatchItem(BaseModel):
    image_id: str
    score: float
    bbox: Optional[List[int]] = None
    person_name: Optional[str] = None
    cluster_id: Optional[str] = None
    thumbnail_url: Optional[str] = None
    cloud_url: Optional[str] = None
    metadata: Dict[str, Any] = {}

class SearchResponse(BaseModel):
    query_type: str
    total_matches: int
    results: List[MatchItem]

class MultiAngleSearchRequest(BaseModel):
    threshold: Optional[float] = 0.60
    top_k: Optional[int] = 20

