# File: backend/api/v1/router.py
"""Main API v1 router that combines all route modules."""
from fastapi import APIRouter

from .routes import process, suggestions, progress, genius

router = APIRouter()

# Include all route modules
router.include_router(process.router, tags=["Processing"])
router.include_router(suggestions.router, tags=["Search"])
router.include_router(progress.router, tags=["Progress"])
router.include_router(genius.router, tags=["Lyrics"])
