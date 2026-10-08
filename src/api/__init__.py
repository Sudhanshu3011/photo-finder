"""API Route module exports."""

from src.api.auth_routes import router as auth_router
from src.api.upload_routes import router as upload_router
from src.api.processing_routes import router as processing_router
from src.api.search_routes import router as search_router
from src.api.system_routes import router as system_router
from src.api.ui import router as ui_router

__all__ = [
    "auth_router",
    "upload_router",
    "processing_router",
    "search_router",
    "system_router",
    "ui_router",
]

