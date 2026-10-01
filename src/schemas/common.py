"""Common Pydantic V2 schemas and response wrappers."""
from typing import Generic, Optional, TypeVar
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class BaseResponse(BaseModel):
    """Standard success response wrapper."""
    model_config = ConfigDict(populate_by_name=True)

    success: bool = Field(default=True, description="Indicates request success")
    message: Optional[str] = Field(default=None, description="Human-readable status message")


class ErrorDetail(BaseModel):
    """Structured error details."""
    field: Optional[str] = Field(default=None, description="Field name where error occurred")
    message: str = Field(..., description="Error explanation")


class ErrorResponse(BaseModel):
    """Standardized API error response contract."""
    model_config = ConfigDict(populate_by_name=True)

    success: bool = Field(default=False)
    error_code: str = Field(..., description="Machine-readable error identifier")
    detail: str = Field(..., description="User-facing error description")
    errors: Optional[list[ErrorDetail]] = Field(default=None, description="Field-level errors if applicable")


class PaginationParams(BaseModel):
    """Standard pagination query parameters."""
    page: int = Field(default=1, ge=1, description="Page number starting at 1")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")


class PaginatedResponse(BaseResponse, Generic[T]):
    """Generic paginated container for list responses."""
    items: list[T] = Field(default_factory=list, description="Page items")
    total: int = Field(..., ge=0, description="Total items across all pages")
    page: int = Field(..., ge=1, description="Current page")
    page_size: int = Field(..., ge=1, description="Page size")
    total_pages: int = Field(..., ge=0, description="Total computed pages")
