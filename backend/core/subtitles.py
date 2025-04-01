# File: backend/core/subtitles.py
import asyncio
import logging
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)

async def generate_srt(job_id: str, cleaned_segments: List[Dict], video_id: str, processed_dir: Path) -> Path:
    """
    Generates the SRT subtitle file from cleaned segments.
    Runs the synchronous file generation in a separate thread.
    """
    # Place SRT in the main processed directory for easier access by merge step
    srt_path = processed_dir / f"{video_id}.srt"
    try:
        await asyncio.to_thread(_generate_srt_file_sync, cleaned_segments, srt_path, job_id)
        # Check if file exists, allow empty file if no segments were provided
        if not srt_path.exists():
             if cleaned_segments: # Only raise error if segments existed but file wasn't created
                 raise IOError("SRT generation function completed but file not found.")
             else: # Log warning if segments were empty and file doesn't exist (expected)
                  logger.warning(f"Job {job_id}: No SRT file created as no text segments were provided.")
        elif srt_path.stat().st_size == 0 and cleaned_segments:
             logger.warning(f"Job {job_id}: Generated SRT file '{srt_path.name}' is empty despite having segments.")

        return srt_path
    except Exception as e:
        logger.error(f"SRT generation step failed for job {job_id}: {e}", exc_info=True)
        raise IOError(f"SRT generation failed: {e}") from e


def _generate_srt_file_sync(transcript_segments: List[Dict], srt_path: Path, job_id: str):
    """Synchronous function to generate an SRT subtitle file."""

    def format_time(seconds: float) -> str:
        """Converts seconds to SRT time format HH:MM:SS,ms."""
        if not isinstance(seconds, (int, float)) or seconds < 0:
            # logger.warning(f"Job {job_id}: Invalid time value encountered in SRT: {seconds}. Using 0.")
            seconds = 0.0
        # Calculate time components safely
        total_milliseconds = round(seconds * 1000)
        milliseconds = total_milliseconds % 1000
        total_seconds = total_milliseconds // 1000
        secs = total_seconds % 60
        total_minutes = total_seconds // 60
        mins = total_minutes % 60
        hours = total_minutes // 60
        return f"{hours:02d}:{mins:02d}:{secs:02d},{milliseconds:03d}"

    logger.info(f"Job {job_id}: Generating SRT file: '{srt_path.name}'...")
    entry_count = 0
    try:
        # Ensure parent directory exists
        srt_path.parent.mkdir(parents=True, exist_ok=True)
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, segment in enumerate(transcript_segments):
                start_time = segment.get('start')
                end_time = segment.get('end')
                text = segment.get('text', "").strip()

                # Validate segment data before writing
                if start_time is not None and end_time is not None and text and end_time > start_time:
                    start_formatted = format_time(start_time)
                    end_formatted = format_time(end_time)

                    entry_count += 1
                    f.write(f"{entry_count}\n")
                    f.write(f"{start_formatted} --> {end_formatted}\n")
                    f.write(f"{text}\n\n") # Ensure double newline
                # else: logger.warning(f"Job {job_id}: Skipping invalid segment in SRT generation: Start={start_time}, End={end_time}, Text='{text[:20]}...'")

        if entry_count == 0 and transcript_segments: # Log only if segments existed but none were valid
             logger.warning(f"Job {job_id}: Generated SRT file '{srt_path.name}' is empty (0 valid entries from {len(transcript_segments)} segments).")
        elif entry_count > 0:
             logger.info(f"Job {job_id}: SRT file generated with {entry_count} valid entries.")
        # No log needed if transcript_segments was initially empty

    except IOError as e:
        logger.error(f"Job {job_id}: Failed to write SRT file {srt_path}: {e}", exc_info=True)
        raise # Re-raise the specific IO error
    except Exception as e:
        logger.error(f"Job {job_id}: Unexpected error generating SRT file {srt_path}: {e}", exc_info=True)
        raise RuntimeError("Unexpected error during SRT generation") from e
