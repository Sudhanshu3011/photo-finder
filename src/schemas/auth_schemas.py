from typing import Optional
from pydantic import BaseModel, Field

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="Unique username", examples=["johndoe"])
    email: str = Field(
        ...,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Valid email address",
        examples=["user@example.com"],
    )
    password: str = Field(..., min_length=6, description="Password (at least 6 characters)", examples=["secret123"])
    role: Optional[str] = Field("user", description="User role ('user' or 'admin')", examples=["user"])
    cloudinary_url: Optional[str] = Field(None, description="Optional Cloudinary connection string (cloudinary://api_key:api_secret@cloud_name)")

class LoginRequest(BaseModel):
    username: str = Field(..., description="Username or email", examples=["johndoe"])
    password: str = Field(..., description="Account password", examples=["secret123"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    role: str

class UserProfileResponse(BaseModel):
    user_id: str
    username: str
    email: str
    role: str
    cloudinary_url: Optional[str] = None
    created_at: str

class CloudinaryConfigRequest(BaseModel):
    cloudinary_url: str = Field(..., description="Cloudinary connection string (cloudinary://api_key:api_secret@cloud_name)")

class CloudinaryConfigResponse(BaseModel):
    status: str
    message: str
    cloud_name: Optional[str] = None
    configured: bool = True


