# File: backend/schemas/responses.py
"""Response schemas for API endpoints."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class JobResponse(BaseModel):
    """Response for job creation."""
    job_id: str = Field(..., description="Unique job identifier")

    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "550e8400-e29b-41d4-a716-446655440000"
            }
        }


class JobResult(BaseModel):
    """Result data for completed job."""
    video_id: str = Field(..., description="Video identifier")
    processed_path: str = Field(..., description="URL path to processed video")
    title: str = Field(..., description="Video title")
    stems_base_path: Optional[str] = Field(None, description="URL path to stems directory")
    bpm: Optional[float] = Field(None, description="Detected tempo in BPM")
    key: Optional[str] = Field(None, description="Detected musical key, e.g. 'Am', 'C', 'G#m'")
    key_confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Key detection confidence")


class ProgressResponse(BaseModel):
    """Response for job progress updates."""
    job_id: str = Field(..., description="Job identifier")
    progress: int = Field(..., ge=0, le=100, description="Progress percentage")
    message: str = Field(..., description="Current status message")
    is_step_start: bool = Field(False, description="Whether this is a new step")
    result: Optional[JobResult] = Field(None, description="Final result when complete")
    error: bool = Field(False, description="Whether an error occurred")

    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "550e8400-e29b-41d4-a716-446655440000",
                "progress": 45,
                "message": "Separating audio tracks...",
                "is_step_start": True,
                "result": None,
                "error": False
            }
        }


class GeniusCandidate(BaseModel):
    """Genius lyrics search result."""
    title: str = Field(..., description="Song title")
    artist: Optional[str] = Field(None, description="Artist name")
    lyrics: str = Field(..., description="Full lyrics text")
    url: Optional[str] = Field(None, description="URL to Genius page")

    class Config:
        json_schema_extra = {
            "example": {
                "title": "Never Gonna Give You Up",
                "artist": "Rick Astley",
                "lyrics": "We're no strangers to love...",
                "url": "https://genius.com/Rick-astley-never-gonna-give-you-up-lyrics"
            }
        }


class SuggestionItem(BaseModel):
    """YouTube search suggestion item."""
    url: str = Field(..., description="YouTube video URL")
    title: str = Field(..., description="Video title")
    thumbnail: Optional[str] = Field(None, description="Thumbnail URL")
    uploader: Optional[str] = Field(None, description="Channel name")
    duration: Optional[int] = Field(None, description="Duration in seconds")

    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "title": "Rick Astley - Never Gonna Give You Up",
                "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
                "uploader": "Rick Astley",
                "duration": 213
            }
        }


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field("healthy", description="Service status")
    version: str = Field(..., description="API version")
    device: str = Field(..., description="Computing device (cpu/cuda)")
    genius_enabled: bool = Field(..., description="Whether Genius API is enabled")
    jobs: Dict[str, Any] = Field(..., description="Job statistics")
    rate_limit: Dict[str, int] = Field(..., description="Rate limit configuration")


class ErrorResponse(BaseModel):
    """Standard error response."""
    detail: str = Field(..., description="Error message")
    retry_after: Optional[int] = Field(None, description="Seconds to wait before retry")
