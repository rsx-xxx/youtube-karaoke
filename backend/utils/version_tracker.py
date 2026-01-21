# File: backend/utils/version_tracker.py
"""Utilities for tracking model versions and cache management."""
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..schemas.cache import VideoCacheMetadata

logger = logging.getLogger(__name__)

# Cache metadata filename
CACHE_METADATA_FILENAME = "cache_metadata.json"


def get_demucs_version() -> str:
    """Get the installed Demucs library version."""
    try:
        import demucs
        return getattr(demucs, '__version__', 'unknown')
    except ImportError:
        logger.warning("Demucs not installed, returning 'unknown' version")
        return "unknown"
    except Exception as e:
        logger.warning(f"Error getting Demucs version: {e}")
        return "unknown"


def get_whisper_version() -> str:
    """Get the installed Whisper library version."""
    try:
        import whisper
        return getattr(whisper, '__version__', 'unknown')
    except ImportError:
        logger.warning("Whisper not installed, returning 'unknown' version")
        return "unknown"
    except Exception as e:
        logger.warning(f"Error getting Whisper version: {e}")
        return "unknown"


def get_file_hash(file_path: Path, chunk_size: int = 8192) -> str:
    """
    Calculate SHA256 hash of a file.

    Args:
        file_path: Path to the file to hash
        chunk_size: Size of chunks to read (default 8KB)

    Returns:
        Hexadecimal SHA256 hash string
    """
    if not file_path.is_file():
        raise FileNotFoundError(f"Cannot hash non-existent file: {file_path}")

    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    except Exception as e:
        logger.error(f"Error hashing file {file_path}: {e}")
        raise


def get_cache_metadata_path(processed_dir: Path, video_id: str) -> Path:
    """Get the path to the cache metadata file for a video."""
    return processed_dir / video_id / CACHE_METADATA_FILENAME


def load_cache_metadata(processed_dir: Path, video_id: str) -> Optional[VideoCacheMetadata]:
    """
    Load cache metadata for a video.

    Args:
        processed_dir: Base processed directory
        video_id: Video identifier

    Returns:
        VideoCacheMetadata if found and valid, None otherwise
    """
    metadata_path = get_cache_metadata_path(processed_dir, video_id)

    if not metadata_path.is_file():
        logger.debug(f"No cache metadata found at {metadata_path}")
        return None

    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        metadata = VideoCacheMetadata.model_validate(data)
        logger.debug(f"Loaded cache metadata for video {video_id}")
        return metadata
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON in cache metadata {metadata_path}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error loading cache metadata from {metadata_path}: {e}")
        return None


def save_cache_metadata(processed_dir: Path, video_id: str, metadata: VideoCacheMetadata) -> bool:
    """
    Save cache metadata for a video.

    Args:
        processed_dir: Base processed directory
        video_id: Video identifier
        metadata: Cache metadata to save

    Returns:
        True if saved successfully, False otherwise
    """
    video_dir = processed_dir / video_id
    video_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = get_cache_metadata_path(processed_dir, video_id)

    try:
        # Convert to dict with datetime serialization
        data = metadata.model_dump(mode='json')
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        logger.debug(f"Saved cache metadata for video {video_id}")
        return True
    except Exception as e:
        logger.error(f"Error saving cache metadata to {metadata_path}: {e}")
        return False


def update_stems_cache_metadata(
    processed_dir: Path,
    video_id: str,
    demucs_model: str,
    audio_hash: str
) -> bool:
    """
    Update the stems cache metadata for a video.

    Args:
        processed_dir: Base processed directory
        video_id: Video identifier
        demucs_model: Demucs model used
        audio_hash: SHA256 hash of input audio

    Returns:
        True if updated successfully
    """
    from ..schemas.cache import StemCacheMetadata

    # Load existing metadata or create new
    metadata = load_cache_metadata(processed_dir, video_id)
    if metadata is None:
        metadata = VideoCacheMetadata(video_id=video_id)

    # Update stems metadata
    metadata.stems = StemCacheMetadata(
        demucs_model=demucs_model,
        demucs_version=get_demucs_version(),
        audio_hash=audio_hash
    )

    return save_cache_metadata(processed_dir, video_id, metadata)


def update_transcription_cache_metadata(
    processed_dir: Path,
    video_id: str,
    whisper_model: str,
    language: str
) -> bool:
    """
    Update the transcription cache metadata for a video.

    Args:
        processed_dir: Base processed directory
        video_id: Video identifier
        whisper_model: Whisper model used
        language: Transcription language

    Returns:
        True if updated successfully
    """
    from ..schemas.cache import TranscriptionCacheMetadata

    # Load existing metadata or create new
    metadata = load_cache_metadata(processed_dir, video_id)
    if metadata is None:
        metadata = VideoCacheMetadata(video_id=video_id)

    # Update transcription metadata
    metadata.transcription = TranscriptionCacheMetadata(
        whisper_model=whisper_model,
        whisper_version=get_whisper_version(),
        language=language
    )

    return save_cache_metadata(processed_dir, video_id, metadata)


def update_audio_analysis_cache_metadata(
    processed_dir: Path,
    video_id: str,
    bpm: Optional[float],
    key: Optional[str],
    key_confidence: Optional[float]
) -> bool:
    """
    Update the audio analysis cache metadata for a video.

    Args:
        processed_dir: Base processed directory
        video_id: Video identifier
        bpm: Detected BPM
        key: Detected musical key
        key_confidence: Key detection confidence

    Returns:
        True if updated successfully
    """
    from ..schemas.cache import AudioAnalysisMetadata

    # Load existing metadata or create new
    metadata = load_cache_metadata(processed_dir, video_id)
    if metadata is None:
        metadata = VideoCacheMetadata(video_id=video_id)

    # Update audio analysis metadata
    metadata.audio_analysis = AudioAnalysisMetadata(
        bpm=bpm,
        key=key,
        key_confidence=key_confidence
    )

    return save_cache_metadata(processed_dir, video_id, metadata)


def is_stems_cache_valid(
    processed_dir: Path,
    video_id: str,
    expected_model: str,
    audio_path: Optional[Path] = None
) -> bool:
    """
    Check if the cached stems are valid for the current configuration.

    Args:
        processed_dir: Base processed directory
        video_id: Video identifier
        expected_model: Expected Demucs model
        audio_path: Optional path to audio file for hash verification

    Returns:
        True if cache is valid, False otherwise
    """
    metadata = load_cache_metadata(processed_dir, video_id)

    if metadata is None or metadata.stems is None:
        logger.debug(f"No stems cache metadata for {video_id}")
        return False

    stems_meta = metadata.stems
    current_version = get_demucs_version()

    # Check model match
    if stems_meta.demucs_model != expected_model:
        logger.info(f"Stems cache invalidated: model mismatch ({stems_meta.demucs_model} != {expected_model})")
        return False

    # Check version match
    if stems_meta.demucs_version != current_version:
        logger.info(f"Stems cache invalidated: version mismatch ({stems_meta.demucs_version} != {current_version})")
        return False

    # Optionally check audio hash
    if audio_path and audio_path.is_file():
        try:
            current_hash = get_file_hash(audio_path)
            if stems_meta.audio_hash != current_hash:
                logger.info(f"Stems cache invalidated: audio hash mismatch")
                return False
        except Exception as e:
            logger.warning(f"Could not verify audio hash: {e}")
            # Continue without hash verification

    logger.debug(f"Stems cache valid for {video_id}")
    return True


def is_transcription_cache_valid(
    processed_dir: Path,
    video_id: str,
    expected_model: str,
    expected_language: str
) -> bool:
    """
    Check if the cached transcription is valid for the current configuration.

    Args:
        processed_dir: Base processed directory
        video_id: Video identifier
        expected_model: Expected Whisper model
        expected_language: Expected transcription language

    Returns:
        True if cache is valid, False otherwise
    """
    metadata = load_cache_metadata(processed_dir, video_id)

    if metadata is None or metadata.transcription is None:
        logger.debug(f"No transcription cache metadata for {video_id}")
        return False

    trans_meta = metadata.transcription
    current_version = get_whisper_version()

    # Check model match
    if trans_meta.whisper_model != expected_model:
        logger.info(f"Transcription cache invalidated: model mismatch ({trans_meta.whisper_model} != {expected_model})")
        return False

    # Check version match
    if trans_meta.whisper_version != current_version:
        logger.info(f"Transcription cache invalidated: version mismatch ({trans_meta.whisper_version} != {current_version})")
        return False

    # Check language match
    if trans_meta.language != expected_language:
        logger.info(f"Transcription cache invalidated: language mismatch ({trans_meta.language} != {expected_language})")
        return False

    logger.debug(f"Transcription cache valid for {video_id}")
    return True
