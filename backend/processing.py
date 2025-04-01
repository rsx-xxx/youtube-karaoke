# File: backend/processing.py
"""
Main processing pipeline orchestrator.
Imports step functions from core modules and manages the job lifecycle.
"""
import asyncio
import logging
import time
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional

# Core processing steps
from core.downloader import download_video, get_youtube_suggestions
from core.audio_extractor import extract_audio
from core.separator import separate_tracks
from core.transcriber import transcribe_audio
from core.subtitles import generate_srt
from core.merger import merge_with_subtitles, merge_without_subtitles

# Lyrics processing
from lyrics_processing import fetch_lyrics_from_genius, align_lyrics, force_only_words

# Utilities
# *** FIXED: Import progress_dict along with other items ***
from utils.progress_manager import set_progress, get_progress, STEP_RANGES, job_tasks, progress_dict
from config import settings # Import unified settings

logger = logging.getLogger(__name__)

# --- Main Processing Job ---

async def process_video_job(job_id: str, url_or_search: str, language: str, sub_pos: str, gen_subs: bool):
    """
    Manages the asynchronous execution of the video processing pipeline (_run_job).
    Handles task creation, monitoring, and final state updates.
    Relies on progress_manager for state tracking.
    """
    loop = asyncio.get_running_loop()
    start_time = time.monotonic()

    # Set initial progress via progress_manager
    set_progress(job_id, 0, "Job accepted, preparing...", is_step_start=True, step_name="init")

    # Create and track the background task using the dict from progress_manager
    task = loop.create_task(_run_job(job_id, url_or_search, language, sub_pos, gen_subs))
    job_tasks[job_id] = task # Track the task
    logger.info(f"Created background task for job {job_id}")

    try:
        await task # Wait for the task to complete or raise an exception
        elapsed_time = time.monotonic() - start_time
        final_status = get_progress(job_id)
        # Check if the job genuinely succeeded (status set by finalize step)
        if final_status and final_status.get("progress", 0) >= 100 and final_status.get("result"):
            logger.info(f"Job task {job_id} completed successfully in {elapsed_time:.2f} seconds.")
        else:
             logger.warning(f"Job task {job_id} finished, but final status seems incomplete or errored. Time: {elapsed_time:.2f}s. Status: {final_status}")
             # Ensure a final state is recorded if somehow missed
             if not final_status or final_status.get("progress", 0) < 100:
                  # Check if an error message already exists before overwriting
                  existing_message = final_status.get("message", "") if final_status else ""
                  if "error" not in existing_message.lower() and "cancel" not in existing_message.lower():
                      set_progress(job_id, 100, "Job finished with uncertain status.", is_step_start=False)
                  else:
                      logger.info(f"Job {job_id} already has a final error/cancel status: '{existing_message}'. Not overwriting.")


    except asyncio.CancelledError:
        elapsed_time = time.monotonic() - start_time
        logger.warning(f"Job task {job_id} was explicitly cancelled after {elapsed_time:.2f} seconds.")
        # kill_job (called externally) should handle setting the final 'cancelled' status

    except Exception as e:
        elapsed_time = time.monotonic() - start_time
        error_type = type(e).__name__
        # Ensure a user-friendly message, avoid leaking full exception details unless necessary
        error_message_detail = f"Error during processing: {e}" # Default detail
        if isinstance(e, FileNotFoundError):
             error_message_detail = f"Processing error: A required file was not found. ({e})"
        elif isinstance(e, ValueError):
             error_message_detail = f"Processing error: Invalid input or data. ({e})"
        elif isinstance(e, ConnectionError):
             error_message_detail = f"Processing error: Network connection issue. ({e})"
        elif isinstance(e, RuntimeError):
             error_message_detail = f"Processing error: Runtime issue occurred. ({e})"

        full_error_log = f"Unhandled error during job {job_id} execution ({error_type})"
        logger.error(f"{full_error_log} after {elapsed_time:.2f} seconds. Details: {e}", exc_info=True)

        # Ensure a final error status is set in the progress dict, using the cleaner message
        set_progress(job_id, 100, f"Error: {error_message_detail} - Check logs.", is_step_start=False)

    finally:
        # Clean up task tracking from progress_manager dict
        finished_task = job_tasks.pop(job_id, None)
        if finished_task:
             # logger.debug(f"Removed task tracking for job {job_id}")
             pass
        # Optional: Schedule automatic cleanup of progress_dict entry and files after a delay
        # Needs cleanup logic implemented (e.g., in file_system.py) and uncommented
        # from utils.file_system import schedule_job_cleanup
        # schedule_job_cleanup(job_id, loop)


async def _run_job(job_id: str, url_or_search: str, language: str, sub_pos: str, gen_subs: bool):
    """
    The core video processing pipeline, orchestrating calls to core modules.
    Updates progress via progress_manager.
    """
    video_id: Optional[str] = None
    video_path: Optional[Path] = None
    audio_path: Optional[Path] = None
    srt_path: Optional[Path] = None
    processed_video_path: Optional[Path] = None
    stems_output_dir: Optional[Path] = None
    title: str = "Input Query" # Default title
    uploader: str = ""
    instrumental_path: Optional[Path] = None
    vocals_path: Optional[Path] = None

    step_timings = {} # Track duration of each step

    async def run_step(step_name: str, coro, *args):
        """Helper to run a step, update progress, time it, and handle errors."""
        nonlocal video_id, video_path, title, uploader, audio_path, instrumental_path, vocals_path, stems_output_dir, srt_path, processed_video_path # Allow modification
        step_start_time = time.monotonic()
        start_progress, end_progress = STEP_RANGES.get(step_name, (0, 0))
        step_title = step_name.replace('_', ' ').title()

        # logger.info(f"Job {job_id}: Starting step '{step_name}'...")
        set_progress(job_id, start_progress, f"Starting: {step_title}...", is_step_start=True, step_name=step_name)

        try:
            result = await coro(job_id, *args) # Execute the actual step logic from core module

            # --- Store results based on step name ---
            if step_name == "download":
                 video_id, video_path, title, uploader = result # Unpack download results
                 logger.info(f"Job {job_id}: Download complete. Video ID: {video_id}, Title: {title[:50]}...")
            elif step_name == "extract_audio":
                 audio_path = result
            elif step_name == "separate_tracks":
                 instrumental_path, vocals_path, stems_output_dir = result
            elif step_name == "transcribe":
                 # Result is transcript_segments, handled in main logic flow
                 pass # No variable assignment needed here
            elif step_name == "process_lyrics":
                 # Result is cleaned_segments, handled in main logic flow
                 pass
            elif step_name == "generate_srt":
                 srt_path = result
            elif step_name == "merge":
                 processed_video_path = result
            elif step_name == "finalize":
                 pass # Finalize sets progress directly

            # --- Step Timing & Progress Update ---
            elapsed = time.monotonic() - step_start_time
            step_timings[step_name] = elapsed
            logger.info(f"Job {job_id}: Step '{step_name}' completed in {elapsed:.2f}s.")
            # Set progress to the defined end percentage for this step
            set_progress(job_id, end_progress, f"Completed: {step_title}", is_step_start=False, step_name=step_name)
            return result
        except Exception as e:
             elapsed = time.monotonic() - step_start_time
             step_timings[step_name] = elapsed
             error_type = type(e).__name__
             # Provide more user-friendly error messages from steps
             if isinstance(e, FileNotFoundError):
                 step_error_message = f"Error during '{step_title}': Required file not found. Check logs."
             elif isinstance(e, (ValueError, ConnectionError, RuntimeError)):
                 # Use the error message directly for these types if it's informative
                 step_error_message = f"Error during '{step_title}': {e}"
             else: # Generic fallback
                 step_error_message = f"Error during '{step_title}': An unexpected issue occurred ({error_type}). Check logs."

             logger.error(f"Job {job_id}: Step '{step_name}' failed after {elapsed:.2f}s: {e}", exc_info=True) # Log full trace
             # Set final error status immediately via progress manager
             set_progress(job_id, 100, step_error_message, is_step_start=False)
             raise e # Re-raise to stop the _run_job execution

    # --- Pipeline Execution ---
    try:
        # Step 1: Download
        await run_step("download", download_video, url_or_search, settings.DOWNLOADS_DIR)
        # video_id, video_path, title, uploader are now set

        # Step 2: Extract Audio
        await run_step("extract_audio", extract_audio, video_path, video_id, settings.DOWNLOADS_DIR)
        # audio_path is now set

        # Step 3: Separate Tracks
        await run_step("separate_tracks", separate_tracks, audio_path, video_id, settings.PROCESSED_DIR, settings.DEMUCS_MODEL, settings.DEVICE)
        # instrumental_path, vocals_path, stems_output_dir are now set

        # Step 4: Transcribe (conditional)
        transcript_segments = []
        if gen_subs:
            transcript_segments = await run_step("transcribe", transcribe_audio, vocals_path, language)
        else:
             logger.info(f"Job {job_id}: Skipping transcription step (subtitles disabled).")
             _, transcribe_end = STEP_RANGES["transcribe"]
             set_progress(job_id, transcribe_end, "Skipped transcription.", is_step_start=False, step_name="skip_transcribe")

        # Steps 5 & 6: Lyrics/SRT/Merge (conditional on gen_subs)
        if gen_subs:
            # Step 5a: Process Lyrics (Clean/Fetch/Align)
            cleaned_segments = await run_step("process_lyrics", _process_lyrics_wrapper, transcript_segments, title, uploader)

            # Step 5b: Generate SRT (Only if segments remain)
            if cleaned_segments:
                await run_step("generate_srt", generate_srt, cleaned_segments, video_id, settings.PROCESSED_DIR)
                # srt_path is now set
            else:
                 logger.warning(f"Job {job_id}: Skipping SRT generation as no text segments remain after processing.")
                 _, srt_end = STEP_RANGES["generate_srt"]
                 set_progress(job_id, srt_end, "Skipped SRT generation (no lyrics).", is_step_start=False, step_name="skip_srt_nolyr")
                 srt_path = None # Ensure srt_path is None

            # Step 6a: Merge (Handles missing SRT internally if needed)
            await run_step("merge", merge_with_subtitles, video_path, instrumental_path, srt_path, video_id, sub_pos, settings.PROCESSED_DIR)
            # processed_video_path is now set
        else:
            # Step 6b: Merge without Subtitles (Skip lyrics/SRT steps)
            logger.info(f"Job {job_id}: Skipping lyrics processing and SRT generation steps.")
            _, srt_end = STEP_RANGES["generate_srt"] # Use SRT end progress marker
            set_progress(job_id, srt_end, "Skipped subtitle generation.", is_step_start=False, step_name="skip_srt")

            await run_step("merge", merge_without_subtitles, video_path, instrumental_path, video_id, settings.PROCESSED_DIR)
            # processed_video_path is now set


        # Step 7: Finalize (Prepare result data)
        await run_step("finalize", _finalize_step, video_id, processed_video_path, title, stems_output_dir, settings.PROCESSED_DIR)

    except Exception as e:
        # This catches errors propagating up from run_step or errors between steps
        # Check if progress_dict exists and if job isn't already marked completed/errored
        # *** FIXED: Use imported progress_dict ***
        if job_id in progress_dict and progress_dict[job_id].get("progress", 0) < 100:
             error_message = f"Pipeline failed unexpectedly for job {job_id}: {type(e).__name__} - {e}"
             logger.error(error_message, exc_info=True)
             # Set a generic error if not already set by run_step
             set_progress(job_id, 100, f"Error: Pipeline failed unexpectedly. Check logs.", is_step_start=False)
        # Error is already logged by run_step if it originated there.
        # The outer process_video_job handler will catch this.


# --- Wrapper & Finalize Helper Functions ---

async def _process_lyrics_wrapper(job_id: str, transcript_segments: List[Dict], title: str, uploader: str) -> List[Dict]:
    """Wrapper for lyrics fetching and alignment logic."""
    # Always start by cleaning the raw transcript segments
    try:
        cleaned_raw_segments = await asyncio.to_thread(force_only_words, transcript_segments)
    except Exception as clean_e:
        logger.error(f"Error cleaning initial transcript segments for job {job_id}: {clean_e}. Proceeding with raw.", exc_info=False)
        cleaned_raw_segments = transcript_segments # Use uncleaned as fallback

    if not cleaned_raw_segments:
        logger.info(f"Job {job_id}: Skipping lyrics alignment/fetching as initial cleaning yielded no segments.")
        return []

    # Attempt to fetch and align with official lyrics only if Genius is enabled
    if settings.ENABLE_GENIUS_FETCH:
        logger.info(f"Job {job_id}: Genius fetch enabled. Attempting lyrics fetch for '{title}'")
        try:
            official_lines = await asyncio.to_thread(fetch_lyrics_from_genius, title)

            if official_lines:
                logger.debug(f"Job {job_id}: Found {len(official_lines)} official lines. Aligning...")
                # Align using the initially cleaned segments
                aligned_segments = await asyncio.to_thread(align_lyrics, official_lines, cleaned_raw_segments, uploader)
                # Clean *again* after alignment to handle any artifacts from official lyrics
                final_cleaned_segments = await asyncio.to_thread(force_only_words, aligned_segments)
                logger.info(f"Job {job_id}: Lyrics aligned and cleaned using Genius data.")
                return final_cleaned_segments
            else:
                logger.info(f"Job {job_id}: Official lyrics not found via Genius for '{title}'. Using cleaned original transcription.")
                # No alignment happened, return the already cleaned raw segments
                return cleaned_raw_segments

        except Exception as e:
            logger.warning(f"Error during Genius fetch/alignment for job {job_id}: {e}. Using cleaned raw transcription.", exc_info=False)
            # Fallback to the cleaned raw segments
            return cleaned_raw_segments
    else:
        # Genius fetch disabled, just return the cleaned original transcription
        logger.info(f"Job {job_id}: Genius fetch disabled. Using cleaned original transcription.")
        return cleaned_raw_segments


async def _finalize_step(job_id: str, video_id: str, processed_video_path: Path, title: str, stems_dir: Optional[Path], processed_base_dir: Path):
    """Prepares the final result data and sets the final success status."""
    if not processed_video_path or not processed_video_path.is_file():
         logger.error(f"Finalization failed for job {job_id}: Processed video path invalid: {processed_video_path}")
         raise FileNotFoundError(f"Final karaoke video file not found or invalid: {processed_video_path}")

    # --- Construct relative paths for client access ---
    final_video_uri = None
    relative_stems_base_path = None

    try:
        # Video path relative to PROCESSED_DIR base
        relative_video_path = processed_video_path.relative_to(processed_base_dir).as_posix()
        # Prepend 'processed/' which is the mount point in FastAPI
        final_video_uri = f"processed/{relative_video_path}"
        logger.debug(f"Job {job_id}: Final video URI constructed: {final_video_uri}")
    except ValueError as e:
         logger.error(f"Could not create relative path for video {processed_video_path} based on {processed_base_dir}: {e}")
         # Fallback: Use only the filename, assuming it's directly under /processed mount
         final_video_uri = f"processed/{processed_video_path.name}"
         logger.warning(f"Job {job_id}: Using fallback video URI: {final_video_uri}")


    if stems_dir and stems_dir.is_dir():
        try:
            # Stems path relative to PROCESSED_DIR base
            relative_stems_path = stems_dir.relative_to(processed_base_dir).as_posix()
            # Prepend 'processed/' mount point
            relative_stems_base_path = f"processed/{relative_stems_path}"
            logger.debug(f"Job {job_id}: Stems base URI constructed: {relative_stems_base_path}")
        except ValueError as e:
             logger.error(f"Could not create relative path for stems {stems_dir} based on {processed_base_dir}: {e}")
             # Fallback might be difficult here, depends on structure. Null is safer.
             relative_stems_base_path = None
             logger.warning(f"Job {job_id}: Could not determine relative stems path. Setting stems path to null.")


    # --- Prepare result dictionary ---
    result_data = {
        "video_id": video_id,
        "processed_path": final_video_uri, # Relative path including mount point
        "title": title,
        "stems_base_path": relative_stems_base_path # Relative path including mount point or null
    }

    # Final progress update marking success
    set_progress(job_id, 100, "Karaoke video created successfully!", result=result_data, is_step_start=False, step_name="finalize")
    logger.info(f"Job {job_id} finalized successfully. Result: {result_data}")
    # Return result data (although it's primarily passed via set_progress)
    return result_data

# Make suggestion function accessible (could also be in endpoints if preferred)
__all__ = ["process_video_job", "get_youtube_suggestions"]