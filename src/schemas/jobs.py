"""Pydantic V2 schemas for asynchronous background jobs."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class JobStatusResponse(BaseModel):
    """Status, real-time logs, and progress response when polling an async upload job."""
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(..., description="Unique job ID")
    status: str = Field(..., description="Current status: 'pending', 'processing', 'completed', 'failed'")
    total_files: int = Field(default=0, ge=0, description="Total files in batch")
    processed_files: int = Field(default=0, ge=0, description="Files processed so far")
    progress_pct: int = Field(default=0, ge=0, le=100, description="Completion percentage (0-100)")
    status_url: str = Field(..., description="URL to poll for updates")
    current_stage: Optional[str] = Field(default="", description="Current operational stage (e.g. uploading, inference, indexing)")
    logs: List[str] = Field(default_factory=list, description="Real-time execution log trail and progress events")
    result: Optional[Dict[str, Any]] = Field(default=None, description="Final job result payload if completed")
    error: Optional[str] = Field(default=None, description="Error message if failed")
