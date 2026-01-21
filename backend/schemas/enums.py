# File: backend/schemas/enums.py
"""Enum definitions for karaoke processing options."""
from enum import Enum


class SubtitlePosition(str, Enum):
    """Position of subtitles on the video."""
    TOP = "top"
    BOTTOM = "bottom"


class FontSize(int, Enum):
    """Available font sizes for subtitles."""
    SMALL = 24
    MEDIUM = 30
    LARGE = 36
    XLARGE = 42


class StemType(str, Enum):
    """Audio stem types from Demucs separation."""
    VOCALS = "vocals"
    INSTRUMENTAL = "instrumental"
    DRUMS = "drums"
    BASS = "bass"
    OTHER = "other"
