# File: backend/api/v1/dependencies.py
"""Dependency injection for API endpoints."""
from functools import lru_cache
from typing import AsyncGenerator

from fastapi import Depends

from ...services.genius_service import GeniusService
from ...services.progress_service import ProgressService
from ...genius_client import GeniusClient
from ...config import settings


# === Singleton Instances ===
# Using lru_cache for simple singleton pattern

@lru_cache()
def get_genius_client() -> GeniusClient:
    """Get or create Genius API client singleton."""
    return GeniusClient(hits=15)


@lru_cache()
def get_genius_service() -> GeniusService:
    """Get or create Genius service singleton."""
    client = get_genius_client()
    return GeniusService(client=client)


@lru_cache()
def get_progress_service() -> ProgressService:
    """Get or create Progress service singleton."""
    return ProgressService()


# === Dependency Providers ===
# These are what endpoints should use via Depends()

async def genius_service_dep() -> GeniusService:
    """Dependency provider for GeniusService."""
    return get_genius_service()


async def progress_service_dep() -> ProgressService:
    """Dependency provider for ProgressService."""
    return get_progress_service()


# === Type Aliases for cleaner endpoint signatures ===
GeniusServiceDep = GeniusService
ProgressServiceDep = ProgressService
