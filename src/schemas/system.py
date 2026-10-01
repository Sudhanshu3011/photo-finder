"""Pydantic V2 schemas for system, health, and observability endpoints."""
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Health check response schema."""
    model_config = ConfigDict(populate_by_name=True)

    status: str = Field(default="ok", description="Service health status")
    timestamp: str = Field(..., description="UTC ISO timestamp")


class FrontendLogRequest(BaseModel):
    """Structured telemetry/logging payload from frontend applications."""
    model_config = ConfigDict(populate_by_name=True)

    event: str = Field(..., description="Event name/category (e.g. 'search_click', 'upload_failed')")
    user_id: Optional[str] = Field(default="", description="User identifier")
    page: Optional[str] = Field(default="", description="Frontend route or page URL")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary event metadata payload")


class VerifyKeysResponse(BaseModel):
    """Response returned when validating Cloudinary storage and local FAISS vector stores."""
    model_config = ConfigDict(populate_by_name=True)

    valid: bool = Field(default=True, description="Whether all credentials are valid")
    mode: str = Field(..., description="'guest' or 'personal' credential mode")
    duration_ms: int = Field(..., description="Verification duration in milliseconds")
