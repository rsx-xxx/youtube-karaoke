# File: backend/core/audio_analyzer.py
"""Audio analysis module for BPM and key detection using librosa."""
import asyncio
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

from ..config import settings
from ..utils.version_tracker import (
    load_cache_metadata,
    update_audio_analysis_cache_metadata
)

logger = logging.getLogger(__name__)

# Musical key names in chromatic order starting from C
KEY_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# Krumhansl-Schmuckler key profiles for major and minor keys
# These represent the expected distribution of pitch classes for each key type
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def _detect_key_from_chroma(chroma: np.ndarray) -> Tuple[int, bool, float]:
    """
    Detect musical key from chroma features using Krumhansl-Schmuckler algorithm.

    Args:
        chroma: Chromagram array (12 x time_frames)

    Returns:
        Tuple of (key_index, is_major, confidence)
        - key_index: 0-11 corresponding to C through B
        - is_major: True for major, False for minor
        - confidence: Correlation coefficient (0.0 to 1.0)
    """
    # Average the chroma features over time to get pitch class distribution
    chroma_mean = np.mean(chroma, axis=1)

    # Normalize
    if np.sum(chroma_mean) > 0:
        chroma_mean = chroma_mean / np.sum(chroma_mean)

    best_correlation = -1.0
    best_key = 0
    best_is_major = True

    # Test all 24 possible keys (12 major + 12 minor)
    for key_idx in range(12):
        # Rotate the profiles to match each key
        major_rotated = np.roll(MAJOR_PROFILE, key_idx)
        minor_rotated = np.roll(MINOR_PROFILE, key_idx)

        # Normalize profiles
        major_rotated = major_rotated / np.sum(major_rotated)
        minor_rotated = minor_rotated / np.sum(minor_rotated)

        # Calculate correlation with major profile
        major_corr = np.corrcoef(chroma_mean, major_rotated)[0, 1]
        if np.isnan(major_corr):
            major_corr = 0.0

        # Calculate correlation with minor profile
        minor_corr = np.corrcoef(chroma_mean, minor_rotated)[0, 1]
        if np.isnan(minor_corr):
            minor_corr = 0.0

        # Update best match
        if major_corr > best_correlation:
            best_correlation = major_corr
            best_key = key_idx
            best_is_major = True

        if minor_corr > best_correlation:
            best_correlation = minor_corr
            best_key = key_idx
            best_is_major = False

    # Convert correlation to confidence (0-1 range)
    confidence = max(0.0, min(1.0, (best_correlation + 1.0) / 2.0))

    return best_key, best_is_major, confidence


def _analyze_sync(audio_path: Path) -> Dict:
    """
    Synchronous audio analysis function.

    Args:
        audio_path: Path to the audio file

    Returns:
        Dict with 'bpm', 'key', 'key_confidence' fields
    """
    try:
        import librosa
    except ImportError:
        logger.error("librosa not installed. Cannot perform audio analysis.")
        return {'bpm': None, 'key': None, 'key_confidence': None}

    logger.info(f"Analyzing audio: {audio_path}")

    try:
        # Load audio file (mono, 22050 Hz for efficiency)
        y, sr = librosa.load(str(audio_path), sr=22050, mono=True)

        # BPM Detection
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        # Handle numpy array vs scalar for tempo
        if hasattr(tempo, '__iter__'):
            bpm = float(tempo[0]) if len(tempo) > 0 else 120.0
        else:
            bpm = float(tempo)
        bpm = round(bpm, 1)

        # Key Detection using Constant-Q Transform chromagram
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        key_idx, is_major, confidence = _detect_key_from_chroma(chroma)

        # Format key string (e.g., "Am", "C", "G#m")
        key_string = f"{KEY_NAMES[key_idx]}{'m' if not is_major else ''}"

        logger.info(f"Analysis complete - BPM: {bpm}, Key: {key_string}, Confidence: {confidence:.2f}")

        return {
            'bpm': bpm,
            'key': key_string,
            'key_confidence': round(confidence, 3)
        }

    except Exception as e:
        logger.error(f"Error during audio analysis: {e}", exc_info=True)
        return {'bpm': None, 'key': None, 'key_confidence': None}


async def analyze_audio(
    job_id: str,
    audio_path: Path,
    video_id: str,
    processed_dir: Optional[Path] = None
) -> Dict:
    """
    Analyze audio for BPM and musical key with caching support.

    Args:
        job_id: Job identifier for logging
        audio_path: Path to the audio file to analyze
        video_id: Video identifier for cache lookup
        processed_dir: Base processed directory for cache storage

    Returns:
        Dict with 'bpm', 'key', 'key_confidence' fields
    """
    if processed_dir is None:
        processed_dir = settings.PROCESSED_DIR

    # Check cache first
    cached_metadata = load_cache_metadata(processed_dir, video_id)
    if cached_metadata and cached_metadata.audio_analysis:
        analysis = cached_metadata.audio_analysis
        logger.info(f"Job {job_id}: [CACHE] Using cached audio analysis for {video_id} - BPM: {analysis.bpm}, Key: {analysis.key}")
        return {
            'bpm': analysis.bpm,
            'key': analysis.key,
            'key_confidence': analysis.key_confidence
        }

    # Validate audio file
    if not audio_path or not audio_path.is_file():
        logger.warning(f"Job {job_id}: Audio file not found: {audio_path}. Skipping analysis.")
        return {'bpm': None, 'key': None, 'key_confidence': None}

    try:
        if audio_path.stat().st_size < 1024:
            logger.warning(f"Job {job_id}: Audio file too small: {audio_path}. Skipping analysis.")
            return {'bpm': None, 'key': None, 'key_confidence': None}
    except Exception as e:
        logger.warning(f"Job {job_id}: Error checking audio file: {e}")
        return {'bpm': None, 'key': None, 'key_confidence': None}

    # Perform analysis in thread pool
    logger.info(f"Job {job_id}: Starting audio analysis for {audio_path.name}")
    result = await asyncio.to_thread(_analyze_sync, audio_path)

    # Save to cache
    if result.get('bpm') is not None or result.get('key') is not None:
        try:
            update_audio_analysis_cache_metadata(
                processed_dir,
                video_id,
                result.get('bpm'),
                result.get('key'),
                result.get('key_confidence')
            )
            logger.debug(f"Job {job_id}: Saved audio analysis to cache")
        except Exception as e:
            logger.warning(f"Job {job_id}: Failed to save analysis to cache: {e}")

    return result


def transpose_key(original: str, semitones: int) -> Optional[str]:
    """
    Transpose a musical key by a number of semitones.

    Args:
        original: Original key string (e.g., "Am", "C", "G#m")
        semitones: Number of semitones to transpose (positive = up, negative = down)

    Returns:
        Transposed key string, or None if input is invalid
    """
    if not original or semitones == 0:
        return original if original else None

    # Parse the key string
    is_minor = original.endswith('m')
    root = original[:-1] if is_minor else original

    # Find the root note index
    try:
        root_idx = KEY_NAMES.index(root)
    except ValueError:
        logger.warning(f"Unknown key root: {root}")
        return None

    # Calculate new key
    new_idx = (root_idx + semitones) % 12

    # Format result
    return f"{KEY_NAMES[new_idx]}{'m' if is_minor else ''}"
