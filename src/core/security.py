from fastapi import Form, HTTPException
from src.core.config import DEFAULT_PINECONE_KEY, DEFAULT_CLOUDINARY_URL
from src.common.utils import get_cloudinary_creds

def get_verified_keys(
    user_pinecone_key: str = Form(""),
    user_cloudinary_url: str = Form("")
) -> dict:
    """Dependency to extract and validate keys."""
    actual_pc_key = user_pinecone_key or DEFAULT_PINECONE_KEY
    actual_cld_url = user_cloudinary_url or DEFAULT_CLOUDINARY_URL
    
    creds = get_cloudinary_creds(actual_cld_url)
    if not creds.get("cloud_name"):
        raise HTTPException(400, "Invalid Cloudinary URL.")
        
    if not actual_pc_key:
        raise HTTPException(400, "Pinecone key is missing.")

    return {
        "pinecone_key": actual_pc_key,
        "cloudinary_url": actual_cld_url,
        "cloudinary_creds": creds
    }