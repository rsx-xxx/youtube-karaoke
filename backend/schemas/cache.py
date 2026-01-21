# File: backend/schemas/cache.py
"""Cache metadata schemas for versioned caching of stems and transcriptions."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class StemCacheMetadata(BaseModel):
    """Metadata for cached audio stem separation results."""
    demucs_model: str = Field(..., description="Demucs model name, e.g. 'mdx_extra_q'")
    demucs_version: str = Field(..., description="Demucs library version, e.g. '4.0.1'")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    audio_hash: str = Field(..., description="SHA256 hash of input audio file")


class TranscriptionCacheMetadata(BaseModel):
    """Metadata for cached transcription results."""
    whisper_model: str = Field(..., description="Whisper model name, e.g. 'large-v3'")
    whisper_version: str = Field(..., description="Whisper library version")
    language: str = Field(..., description="Transcription language or 'auto'")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AudioAnalysisMetadata(BaseModel):
    """Metadata for cached audio analysis results (BPM, key)."""
    bpm: Optional[float] = Field(None, description="Detected tempo in BPM")
    key: Optional[str] = Field(None, description="Detected musical key, e.g. 'Am', 'C', 'G#m'")
    key_confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Confidence score for key detection")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class VideoCacheMetadata(BaseModel):
    """Combined cache metadata for a processed video."""
    video_id: str = Field(..., description="Video identifier")
    stems: Optional[StemCacheMetadata] = None
    transcription: Optional[TranscriptionCacheMetadata] = None
    audio_analysis: Optional[AudioAnalysisMetadata] = None
