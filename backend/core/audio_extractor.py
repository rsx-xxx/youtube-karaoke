# File: backend/core/audio_extractor.py
import asyncio
import logging
from pathlib import Path
from typing import Optional

import ffmpeg as ffmpeg_python

from utils.file_system import find_existing_file, COMMON_AUDIO_FORMATS

logger = logging.getLogger(__name__)

async def extract_audio(job_id: str, video_path: Path, video_id: str, download_dir: Path) -> Path:
    """
    Extracts audio from video to WAV format (44.1kHz, stereo), using cache.
    Runs the synchronous extraction function in a separate thread.
    """
    try:
        # Ensure download directory exists (where WAV will be placed)
        download_dir.mkdir(parents=True, exist_ok=True)

        audio_path = await asyncio.to_thread(
            _extract_audio_sync, video_path, video_id, job_id, download_dir
        )
        if not audio_path or not audio_path.exists():
             raise RuntimeError(f"Audio extraction did not produce a valid file: {audio_path}")
        return audio_path
    except Exception as e:
        logger.error(f"Audio extraction step failed for job {job_id}: {e}", exc_info=True)
        raise RuntimeError(f"Audio extraction failed: {e}") from e

def find_existing_audio(download_dir: Path, video_id: str) -> Optional[Path]:
    """Finds an extracted WAV audio file or a suitable audio download."""
    # Prioritize the standard WAV file we create
    wav_path = download_dir / f"{video_id}.wav"
    if wav_path.is_file() and wav_path.stat().st_size > 1024: # Check size
        # logger.info(f"[CACHE] Found existing WAV audio: {wav_path}")
        return wav_path

    # Fallback: Check if the original download was an audio file we can use
    original_download = find_existing_file(download_dir, video_id, COMMON_AUDIO_FORMATS)
    if original_download:
        # logger.info(f"[CACHE] Found original download is audio: {original_download}. Will ensure WAV format.")
        return original_download # _extract_audio_sync will handle conversion if needed

    # logger.info(f"No suitable existing audio file found for {video_id} in {download_dir}")
    return None

def _extract_audio_sync(video_path: Path, video_id: str, job_id: str, download_dir: Path) -> Path:
    """
    Synchronous function to extract audio to WAV format.
    Handles caching and cases where input is already audio.
    """
    audio_path_wav = download_dir / f"{video_id}.wav"

    # Check cache for the target WAV file first
    cached_audio = find_existing_audio(download_dir, video_id)
    if cached_audio and cached_audio.suffix.lower() == ".wav":
        logger.info(f"Job {job_id}: [CACHE] Using existing WAV audio file: {cached_audio}")
        return cached_audio

    # Source path is either the original download or the cached audio (if not WAV)
    source_path = cached_audio or video_path

    if not source_path or not source_path.exists():
         raise FileNotFoundError(f"Job {job_id}: Source file for audio extraction not found: {source_path or video_path}")

    logger.info(f"Job {job_id}: Converting/Extracting audio from '{source_path.name}' to '{audio_path_wav.name}'...")
    try:
        # Use ffmpeg-python for extraction/conversion
        stream = ffmpeg_python.input(str(source_path))
        # ac=2: Stereo, ar=44100: Sample rate 44.1kHz, format=wav, acodec=pcm_s16le standard WAV codec
        stream = ffmpeg_python.output(stream, str(audio_path_wav), format="wav", ac=2, ar="44100", acodec="pcm_s16le", loglevel="warning")
        # Overwrite if exists from a partial previous run
        stdout, stderr = ffmpeg_python.run(stream, capture_stdout=True, capture_stderr=True, overwrite_output=True)

        # Verify output file was created and is not empty
        if not audio_path_wav.is_file() or audio_path_wav.stat().st_size < 1024: # Check minimum size
            stderr_decoded = stderr.decode(errors='ignore') if stderr else 'No stderr'
            logger.error(f"Job {job_id}: ffmpeg command ran but failed to create a valid audio file: {audio_path_wav}\nFFmpeg stderr:\n{stderr_decoded}")
            raise RuntimeError(f"ffmpeg failed to create a valid audio file: {audio_path_wav.name}")

        logger.info(f"Job {job_id}: Audio successfully extracted/converted to {audio_path_wav.name}")
        return audio_path_wav

    except ffmpeg_python.Error as e:
        stderr = e.stderr.decode(errors='ignore') if e.stderr else 'No stderr captured'
        logger.error(f"Job {job_id}: ffmpeg error during audio extraction/conversion:\n{stderr}")
        # Provide a cleaner error message if possible
        last_line = stderr.strip().splitlines()[-1] if stderr.strip() else 'ffmpeg error (no details)'
        raise RuntimeError(f"Audio processing failed: {last_line}") from e
    except Exception as e:
        logger.error(f"Job {job_id}: Unexpected error during audio extraction: {e}", exc_info=True)
        raise RuntimeError(f"Unexpected audio processing error: {e}") from e
