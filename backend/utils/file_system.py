# File: backend/utils/file_system.py
import logging
import shutil
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# --- Constants ---
COMMON_AUDIO_FORMATS = [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".opus", ".aac"]
COMMON_VIDEO_FORMATS = [".mp4", ".webm", ".mkv", ".mov", ".avi", ".flv"]

# --- File System Functions ---

def find_existing_file(directory: Path, base_name: str, extensions: List[str]) -> Optional[Path]:
    """
    Generic function to find a file with a base name and allowed extensions
    in the specified directory. Checks for non-empty files.
    """
    if not base_name or not directory.is_dir():
        return None
    for ext in extensions:
        p = directory / f"{base_name}{ext}"
        # Check existence and ensure file is not empty (e.g., > 100 bytes)
        try:
            if p.is_file() and p.stat().st_size > 100:
                # logger.debug(f"[CACHE] Found existing, non-empty file: {p}")
                return p
        except FileNotFoundError: # Can happen in rare race conditions
            continue
        except Exception as e: # Catch other potential stat errors
             logger.warning(f"Error checking file {p}: {e}")
             continue
    return None


def cleanup_job_files(job_id: str, download_dir: Path, processed_dir: Path):
    """
    Removes intermediate and final files associated with a specific job ID.
    Use with caution.
    """
    logger.warning(f"Initiating cleanup of files for job {job_id}...")
    count_deleted = 0

    # --- Remove files from downloads directory ---
    possible_download_extensions = COMMON_VIDEO_FORMATS + COMMON_AUDIO_FORMATS + [".wav"]
    for ext in possible_download_extensions:
        file_path = download_dir / f"{job_id}{ext}"
        if file_path.is_file():
            try:
                file_path.unlink()
                # logger.info(f"Deleted download/temp file: {file_path}")
                count_deleted += 1
            except OSError as e:
                logger.warning(f"Could not delete file {file_path}: {e}")

    # --- Remove processed directory structure and files ---
    # Stems are in: processed/JOB_ID/MODEL/JOB_ID/
    processed_job_base_dir = processed_dir / job_id
    if processed_job_base_dir.is_dir():
        try:
            shutil.rmtree(processed_job_base_dir)
            logger.info(f"Deleted processed job directory and contents: {processed_job_base_dir}")
            count_deleted += 1 # Count the directory itself
        except OSError as e:
            logger.warning(f"Could not delete directory {processed_job_base_dir}: {e}")

    # Remove final karaoke file and SRT file (usually directly in processed_dir)
    karaoke_file_path = processed_dir / f"{job_id}_karaoke.mp4"
    srt_file_path = processed_dir / f"{job_id}.srt"

    for file_path in [karaoke_file_path, srt_file_path]:
         if file_path.is_file():
              try:
                   file_path.unlink()
                   # logger.info(f"Deleted final file: {file_path}")
                   count_deleted += 1
              except OSError as e:
                   logger.warning(f"Could not delete file {file_path}: {e}")

    logger.info(f"File cleanup attempt finished for job {job_id}. Deleted {count_deleted} items (files/dirs).")
