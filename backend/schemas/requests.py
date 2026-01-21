# File: backend/schemas/requests.py
"""Request schemas for API endpoints."""
import logging
from typing import Dict, Optional

from pydantic import BaseModel, Field, field_validator

from .enums import SubtitlePosition, FontSize, StemType

logger = logging.getLogger(__name__)


class ProcessRequest(BaseModel):
    """Request schema for video processing."""
    url: str = Field(..., description="YouTube URL or search query", min_length=1)
    language: str = Field("auto", description="Transcription language or 'auto'")
    subtitle_position: SubtitlePosition = Field(
        SubtitlePosition.BOTTOM,
        description="Position of subtitles on video"
    )
    generate_subtitles: bool = Field(True, description="Add lyrics/subtitles to video")
    custom_lyrics: Optional[str] = Field(
        None,
        description="User-provided full lyrics (overrides Genius)"
    )
    global_pitch: Optional[float] = Field(
        None,
        ge=-12,
        le=12,
        description="Global pitch shift in semitones (-12 to +12), applies to all audio without changing tempo"
    )
    pitch_shifts: Optional[Dict[str, float]] = Field(
        None,
        description="[DEPRECATED] Per-stem semitone shifts. Use global_pitch instead."
    )
    final_subtitle_size: FontSize = Field(
        FontSize.MEDIUM,
        description="Font size for final subtitles"
    )

    @field_validator("pitch_shifts")
    @classmethod
    def validate_pitch_shifts(cls, shifts: Optional[Dict[str, float]]) -> Optional[Dict[str, float]]:
        """Validate pitch shift values are within acceptable range."""
        if shifts is None:
            return None

        allowed_stems = {stem.value for stem in StemType}
        validated: Dict[str, float] = {}

        for stem, value in shifts.items():
            stem_lower = stem.lower()
            if stem_lower not in allowed_stems:
                logger.warning(f"Ignoring unknown stem '{stem}'")
                continue
            if not isinstance(value, (int, float)):
                raise ValueError(f"Shift for '{stem}' must be numeric")
            if not -24 <= value <= 24:
                raise ValueError(f"Shift {value} for '{stem}' outside valid range (-24 to 24)")
            validated[stem_lower] = float(value)

        return validated or None

    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "language": "auto",
                "subtitle_position": "bottom",
                "generate_subtitles": True,
                "final_subtitle_size": 30
            }
        }


class LocalProcessRequest(BaseModel):
    """Request schema for local file processing (form data)."""
    language: str = Field("auto", description="Transcription language")
    subtitle_position: SubtitlePosition = Field(SubtitlePosition.BOTTOM)
    generate_subtitles: bool = Field(True)
    custom_lyrics: Optional[str] = Field(None)
    final_subtitle_size: FontSize = Field(FontSize.MEDIUM)
