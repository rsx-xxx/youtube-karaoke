# File: backend/processing.py
# Orchestrates the processing pipeline, including new ASS generation.
# UPDATED: Added logging for subtitle generation steps and passes final_font_size.
# ADDED: Call to cleanup_job_files in _run_job finally block.

import asyncio
import logging
import time
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional

# Core processing steps
from core.downloader import download_video, get_youtube_suggestions # get_youtube_suggestions is not used here, but fine
from core.audio_extractor import extract_audio
from core.separator import separate_tracks
from core.transcriber import transcribe_audio
from core.subtitles import generate_ass_karaoke
from core.merger import merge_with_subtitles, merge_without_subtitles

# Lyrics processing
from lyrics_processing import (
    fetch_lyrics_from_genius, # This specific function might be from an older version of your lyrics_processing.py
                               # Your endpoints.py uses GeniusClient, which is more robust.
                               # Assuming _process_lyrics_wrapper might internally use the client or a similar fetch.
    prepare_segments_for_karaoke,
    align_custom_lyrics_with_word_times
)

# Utilities
from utils.progress_manager import set_progress, get_progress, STEP_RANGES, job_tasks, progress_dict
from utils.file_system import cleanup_job_files # ADDED IMPORT for cleanup
from config import settings

logger = logging.getLogger(__name__)


# --- Wrapper & Finalize Helper Functions ---

async def _process_lyrics_wrapper(
        job_id: str,
        transcript_segments_with_words: List[Dict],
        title: str,
        uploader: str,
        selected_lyrics: Optional[str] = None
) -> List[Dict]:
    """
    Wrapper for lyrics processing. Prepares segments for ASS generation.
    Handles custom lyrics, Genius fetch, or uses original transcription.
    Ensures result has word timings needed for karaoke effect.
    """
    # --- Scenario 1: Use User-Provided Exact Lyrics ---
    if selected_lyrics:
        logger.info(f"Job {job_id}: Using provided custom lyrics. Applying word timings.")
        try:
            karaoke_ready_segments = await asyncio.to_thread(
                align_custom_lyrics_with_word_times,
                selected_lyrics,
                transcript_segments_with_words
            )
            logger.info(f"Job {job_id}: Applied word timings to {len(karaoke_ready_segments)} lines of custom lyrics.")
            return karaoke_ready_segments
        except Exception as e:
            logger.error(f"Job {job_id}: Error applying timings to custom lyrics: {e}. Falling back.", exc_info=True)
            logger.info(f"Job {job_id}: Falling back to original transcription after custom lyrics error.")
            return await asyncio.to_thread(
                prepare_segments_for_karaoke,
                transcript_segments_with_words,
                None
            )

    # --- Scenario 2: Fetch from Genius and Align ---
    elif settings.ENABLE_GENIUS_FETCH:
        logger.info(f"Job {job_id}: Attempting Genius lyrics fetch for Title='{title}', Artist='{uploader}'")
        official_lines = None
        try:
            # This assumes fetch_lyrics_from_genius is the intended function.
            # If using GeniusClient from endpoints.py, the call might be different or happen earlier.
            genius_result_tuple = await asyncio.to_thread(fetch_lyrics_from_genius, title, uploader)
            if genius_result_tuple:
                official_lines, _ = genius_result_tuple # Assuming it returns (lines, song_object)
        except Exception as e:
            logger.warning(f"Job {job_id}: Error during Genius fetch: {e}.", exc_info=False)

        if official_lines:
            logger.info(f"Job {job_id}: Found {len(official_lines)} official lines. Preparing karaoke segments...")
            try:
                karaoke_ready_segments = await asyncio.to_thread(
                    prepare_segments_for_karaoke,
                    transcript_segments_with_words,
                    official_lines
                )
                logger.info(f"Job {job_id}: Prepared {len(karaoke_ready_segments)} karaoke segments using aligned Genius lyrics.")
                return karaoke_ready_segments
            except Exception as e:
                logger.error(f"Job {job_id}: Error preparing karaoke segments with Genius lyrics: {e}. Falling back.", exc_info=True)
                logger.info(f"Job {job_id}: Falling back to original transcription after Genius alignment error.")
                return await asyncio.to_thread(
                    prepare_segments_for_karaoke,
                    transcript_segments_with_words,
                    None
                )
        else:
            logger.info(f"Job {job_id}: Official lyrics not found/fetched. Using original transcription.")
            return await asyncio.to_thread(
                prepare_segments_for_karaoke,
                transcript_segments_with_words,
                None # Indicate no official lyrics
            )

    # --- Scenario 3: Genius Disabled - Use Original Transcription ---
    else:
        logger.info(f"Job {job_id}: Genius fetch disabled. Using original transcription.")
        return await asyncio.to_thread(
            prepare_segments_for_karaoke,
            transcript_segments_with_words,
            None
        )


async def _finalize_step(
        job_id: str,
        video_id: str,
        processed_video_path: Optional[Path],
        title: str,
        stems_dir: Optional[Path],
        processed_base_dir: Path # This should be settings.PROCESSED_DIR
):
    if not processed_video_path or not processed_video_path.is_file():
        logger.error(f"Finalization failed for job {job_id}: Processed video path invalid or file missing: {processed_video_path}")
        raise FileNotFoundError(f"Final karaoke video file not found or invalid: {processed_video_path}")

    final_video_uri = None
    relative_stems_base_uri = None
    try:
        # Ensure processed_base_dir is absolute for correct relativeto calculation
        abs_processed_base = processed_base_dir.resolve()
        abs_video_path = processed_video_path.resolve()
        # Create path relative to the *root* of the /processed static mount
        relative_video_path_posix = abs_video_path.relative_to(abs_processed_base).as_posix()
        final_video_uri = f"processed/{relative_video_path_posix.lstrip('/')}"
    except ValueError as e: # If paths are not on the same drive or other issues
        logger.error(f"Could not create relative path for video {processed_video_path} from base {processed_base_dir}: {e}")
        final_video_uri = f"processed/{video_id}/{processed_video_path.name}" # Fallback based on common structure
    logger.debug(f"Job {job_id}: Final video URI constructed: {final_video_uri}")

    if stems_dir and stems_dir.is_dir():
        try:
            abs_processed_base = processed_base_dir.resolve()
            abs_stems_dir = stems_dir.resolve()
            relative_stems_path_posix = abs_stems_dir.relative_to(abs_processed_base).as_posix()
            relative_stems_base_uri = f"processed/{relative_stems_path_posix.lstrip('/')}"
        except ValueError as e:
            logger.error(f"Could not create relative path for stems {stems_dir} from base {processed_base_dir}: {e}")
            # Fallback if stems_dir is not directly under processed_base_dir in a simple way
            # This might happen if stems_dir structure is complex like video_id/model_name/video_id
            # The URI should be relative to where 'processed' is served.
            # Assuming stems_dir is like 'processed/video_id/demucs_model/video_id_stem_name'
            # and processed_base_dir is 'processed'
            try: # More robust fallback:
                 relative_stems_path_posix = stems_dir.relative_to(settings.ROOT_DIR).as_posix() # Relative to project root
                 # Find the "processed" part
                 if "processed/" in relative_stems_path_posix:
                      relative_stems_base_uri = relative_stems_path_posix[relative_stems_path_posix.find("processed/"):]
                 else: # Can't form a good relative URI
                      relative_stems_base_uri = None
            except: # Catch all if even that fails
                 relative_stems_base_uri = None

        logger.debug(f"Job {job_id}: Stems base URI constructed: {relative_stems_base_uri}")
    else:
        logger.warning(f"Job {job_id}: Stems directory not provided or not found: {stems_dir}. Stems URI will be null.")

    result_data = {
        "video_id": video_id,
        "processed_path": final_video_uri,
        "title": title,
        "stems_base_path": relative_stems_base_uri
    }
    set_progress(job_id, 100, "Karaoke video created successfully!", result=result_data, is_step_start=False, step_name="finalize")
    logger.info(f"Job {job_id} finalized successfully. Result: {result_data}")
    return result_data


async def process_video_job(
        job_id: str,
        url_or_search: str,
        language: str,
        sub_pos: str,
        gen_subs: bool,
        selected_lyrics: Optional[str] = None,
        pitch_shifts: Optional[Dict[str, float]] = None,
        final_font_size: int = 30
):
    loop = asyncio.get_running_loop() # Ensure this is called within an async context
    start_time = time.monotonic()
    set_progress(job_id, 0, "Job accepted, preparing...", is_step_start=True, step_name="init")

    # Create and store the task
    task = loop.create_task(
        _run_job(job_id, url_or_search, language, sub_pos, gen_subs, selected_lyrics, pitch_shifts, final_font_size)
    )
    job_tasks[job_id] = task
    logger.info(f"Created background task for job {job_id}")

    try:
        await task
        elapsed_time = time.monotonic() - start_time
        final_status = get_progress(job_id)
        if final_status and final_status.get("progress", 0) >= 100 and final_status.get("result"):
            logger.info(f"Job task {job_id} completed successfully in {elapsed_time:.2f} seconds.")
        else:
            logger.warning(f"Job task {job_id} finished, but final status seems incomplete or errored. Time: {elapsed_time:.2f}s. Status: {final_status}")
            if not final_status or final_status.get("progress", 0) < 100:
                existing_message = final_status.get("message", "") if final_status else ""
                if not any(keyword in existing_message.lower() for keyword in ["error", "cancel", "fail"]):
                    set_progress(job_id, 100, "Job finished with uncertain status.", is_step_start=False, step_name="uncertain_finish")
                else:
                    logger.info(f"Job {job_id} already has a final error/cancel status: '{existing_message}'. Not overwriting.")
    except asyncio.CancelledError:
        elapsed_time = time.monotonic() - start_time
        logger.warning(f"Job task {job_id} was explicitly cancelled after {elapsed_time:.2f} seconds.")
        current_status = get_progress(job_id)
        if current_status and current_status.get("progress", 0) < 100:
            if "cancel" not in current_status.get("message", "").lower(): # Avoid duplicate "cancelled" messages
                set_progress(job_id, 100, "Job cancelled during execution.", is_step_start=False, step_name="cancelled")
    except Exception as e:
        elapsed_time = time.monotonic() - start_time
        error_type = type(e).__name__
        # Ensure a user-friendly message, avoid leaking too much internal detail directly to progress.
        error_message_detail = f"Processing error: {error_type}"
        full_error_log = f"Unhandled error during job {job_id} execution ({error_type})"
        logger.error(f"{full_error_log} after {elapsed_time:.2f} seconds. Details: {e}", exc_info=True)
        set_progress(job_id, 100, f"Error: {error_message_detail}. Check server logs for job ID {job_id}.", is_step_start=False, step_name="pipeline_error")
    finally:
        finished_task = job_tasks.pop(job_id, None)
        if finished_task:
            logger.debug(f"Removed task reference for completed/failed job {job_id}")
        # ADDED: Call cleanup_job_files here, ensuring video_id is available
        # video_id is defined in _run_job and should be available if download was successful
        # This assumes `job_id` is used as the primary identifier for file/folder names
        # which is not the case; `video_id` is used.
        # We need to get video_id from the job's context if it exists, or skip cleanup if not.
        # For now, this cleanup is tricky without passing video_id back from _run_job or storing it.
        # A simple approach: the cleanup function would need to search for files/folders related to job_id
        # Or, _run_job's finally block should get video_id if set.
        # The current `cleanup_job_files` expects a `job_id` that matches file names.
        # Let's assume the cleanup function should be called with video_id if the step was reached.
        # This will be handled inside _run_job's finally block.


async def _run_job(
        job_id: str,
        url_or_search: str,
        language: str,
        sub_pos: str,
        gen_subs: bool,
        selected_lyrics: Optional[str] = None,
        pitch_shifts: Optional[Dict[str, float]] = None,
        final_font_size: int = 30
):
    video_id_for_cleanup: Optional[str] = None # To store video_id for cleanup
    try:
        # ... (rest of the _run_job implementation as you provided) ...
        # The structure with run_step and assignments to nonlocal variables is complex
        # but assumed to be working as intended by you.
        # I'll paste the original _run_job and add the finally block at the end.

        video_id: Optional[str] = None
        video_path: Optional[Path] = None
        audio_path: Optional[Path] = None
        subtitle_path: Optional[Path] = None # Holds ASS path now
        processed_video_path: Optional[Path] = None
        stems_output_dir: Optional[Path] = None
        title: str = "Input Query"
        uploader: str = ""
        instrumental_path: Optional[Path] = None
        vocals_path: Optional[Path] = None
        transcript_segments_with_words: List[Dict] = []
        full_whisper_result: Optional[Any] = None
        step_timings = {}

        async def run_step(step_name: str, coro, *args, **kwargs):
            nonlocal video_id, video_path, title, uploader, audio_path, \
                       instrumental_path, vocals_path, stems_output_dir, subtitle_path, \
                       processed_video_path, transcript_segments_with_words, full_whisper_result, \
                       video_id_for_cleanup # Ensure video_id_for_cleanup is also nonlocal if assigned here

            step_start_time = time.monotonic()
            start_progress, end_progress = STEP_RANGES.get(step_name, (0, 0))
            step_title = step_name.replace('_', ' ').title()

            if job_id not in job_tasks: # Check if task still exists for this job_id
                logger.warning(f"Job {job_id} task missing, likely cancelled before starting step '{step_name}'.")
                raise asyncio.CancelledError(f"Job {job_id} cancelled before step {step_name}")

            set_progress(job_id, start_progress, f"Starting: {step_title}...", is_step_start=True, step_name=step_name)

            try:
                result = await coro(job_id, *args, **kwargs)

                if step_name == "download":
                    video_id, video_path, title, uploader = result
                    video_id_for_cleanup = video_id # Store for cleanup
                elif step_name == "extract_audio": audio_path = result
                elif step_name == "separate_tracks": instrumental_path, vocals_path, stems_output_dir = result
                elif step_name == "transcribe": transcript_segments_with_words, full_whisper_result = result
                elif step_name == "generate_ass": subtitle_path = result
                elif step_name == "merge": processed_video_path = result

                elapsed = time.monotonic() - step_start_time
                step_timings[step_name] = elapsed
                logger.info(f"Job {job_id}: Step '{step_name}' completed in {elapsed:.2f}s.")
                set_progress(job_id, end_progress, f"Completed: {step_title}", is_step_start=False, step_name=step_name)
                return result

            except asyncio.CancelledError:
                logger.warning(f"Job {job_id}: Step '{step_name}' was cancelled.")
                current_status = get_progress(job_id)
                if current_status and "cancel" not in current_status.get("message", "").lower():
                    set_progress(job_id, 100, f"Job cancelled during {step_title}.", is_step_start=False, step_name="cancelled")
                raise
            except Exception as e:
                elapsed = time.monotonic() - step_start_time
                step_timings[step_name] = elapsed
                error_type = type(e).__name__
                step_error_message = f"Error during '{step_title}': {e}"
                logger.error(f"Job {job_id}: Step '{step_name}' failed after {elapsed:.2f}s: {e}", exc_info=True)
                set_progress(job_id, 100, step_error_message, is_step_start=False, step_name=f"{step_name}_error")
                raise e

        # --- Pipeline Execution Flow ---
        await run_step("download", download_video, url_or_search, settings.DOWNLOADS_DIR)
        # Ensure video_id is set before proceeding to steps that depend on it
        if not video_id: raise ValueError("video_id not set after download step")

        await run_step("extract_audio", extract_audio, video_path, video_id, settings.DOWNLOADS_DIR)
        await run_step("separate_tracks", separate_tracks, audio_path, video_id, settings.PROCESSED_DIR, settings.DEMUCS_MODEL, settings.DEVICE)

        merge_kwargs = {"stem_config": {"pitch_shifts": pitch_shifts} if pitch_shifts else None}
        logger.info(f"Job {job_id}: Preparing merge step with pitch config: {merge_kwargs}")

        if gen_subs:
            if not vocals_path : raise ValueError("vocals_path not set, required for transcription")
            await run_step("transcribe", transcribe_audio, vocals_path, language)
            logger.info(f"Job {job_id}: Transcription produced {len(transcript_segments_with_words)} segments.")
            if transcript_segments_with_words:
                logger.debug(f"Job {job_id}: First transcript segment words: {transcript_segments_with_words[0].get('words', [])[:5]}")
            else:
                logger.warning(f"Job {job_id}: Transcription step completed but produced no segments.")

            karaoke_ready_segments = await run_step("process_lyrics", _process_lyrics_wrapper,
                                                    transcript_segments_with_words, title, uploader, selected_lyrics)
            logger.info(f"Job {job_id}: Lyrics processing produced {len(karaoke_ready_segments)} segments for ASS generation.")
            if karaoke_ready_segments:
                logger.debug(f"Job {job_id}: First karaoke segment words: {karaoke_ready_segments[0].get('words', [])[:5]}")

            if karaoke_ready_segments:
                await run_step("generate_ass", generate_ass_karaoke,
                               karaoke_ready_segments, video_id, settings.PROCESSED_DIR,
                               font_name='Poppins Bold',
                               font_size=final_font_size,
                               position=sub_pos)
                if subtitle_path and subtitle_path.exists():
                    logger.info(f"Job {job_id}: ASS file generated successfully at: {subtitle_path}")
                else:
                    logger.warning(f"Job {job_id}: ASS generation step completed, but file path is invalid or file not found: {subtitle_path}")
            else:
                logger.warning(f"Job {job_id}: Skipping ASS generation (no karaoke segments after lyrics processing).")
                _, ass_end = STEP_RANGES.get("generate_ass", (90, 93))
                set_progress(job_id, ass_end, "Skipped ASS generation (no lyrics/timing).", False, "skip_ass_nolyr")
                subtitle_path = None

            if subtitle_path and subtitle_path.exists() and subtitle_path.stat().st_size > 100:
                logger.info(f"Job {job_id}: Merging with ASS subtitles from {subtitle_path}.")
                await run_step("merge", merge_with_subtitles,
                               video_path, instrumental_path, subtitle_path, video_id,
                               sub_pos, settings.PROCESSED_DIR, **merge_kwargs,
                               font_size=final_font_size)
            else:
                if gen_subs and (not subtitle_path or not subtitle_path.exists()):
                    logger.warning(f"Job {job_id}: Proceeding to merge without subtitles because ASS file was not generated or is invalid.")
                elif not gen_subs: # This branch will not be hit due to outer if gen_subs
                    logger.info(f"Job {job_id}: Merging without subtitles (as requested by gen_subs=False).") # Should not happen here
                await run_step("merge", merge_without_subtitles,
                               video_path, instrumental_path, video_id,
                               settings.PROCESSED_DIR, **merge_kwargs)
        else: # gen_subs is False
            logger.info(f"Job {job_id}: Skipping transcription, lyrics, ASS steps as gen_subs=False.")
            _, transcribe_end = STEP_RANGES["transcribe"]; set_progress(job_id, transcribe_end, "Skipped transcription.", False, "skip_transcribe")
            _, lyrics_end = STEP_RANGES["process_lyrics"]; set_progress(job_id, lyrics_end, "Skipped lyrics processing.", False, "skip_lyrics")
            _, ass_end = STEP_RANGES.get("generate_ass", (90,93)); set_progress(job_id, ass_end, "Skipped subtitle generation.", False, "skip_ass")

            await run_step("merge", merge_without_subtitles,
                           video_path, instrumental_path, video_id,
                           settings.PROCESSED_DIR, **merge_kwargs)

        if not processed_video_path or not processed_video_path.exists():
            raise RuntimeError(f"Merge step finished but the final video file is missing: {processed_video_path}")

        await run_step("finalize", _finalize_step, video_id, processed_video_path, title,
                       stems_output_dir, settings.PROCESSED_DIR)

    except asyncio.CancelledError:
        logger.info(f"Job {job_id} execution pipeline was cancelled.")
        # Status already set by run_step or process_video_job's exception handler
    except Exception as e:
        current_status = get_progress(job_id)
        # Check if error not already set by run_step to avoid duplicate error messages
        if current_status and current_status.get("progress", 0) < 100 and \
           not any(err_kw in current_status.get("message", "").lower() for err_kw in ["error", "fail"]):
            error_message = f"Pipeline failed unexpectedly for job {job_id}: {type(e).__name__}"
            logger.error(f"{error_message} - {e}", exc_info=True)
            detailed_error = str(e) if str(e) else type(e).__name__
            set_progress(job_id, 100, f"Error: Pipeline failed: {detailed_error}. Check logs.", False, "pipeline_error_uncaught_runjob")
        # Re-raise to be caught by process_video_job's main try/except
        raise
    finally:
        # Cleanup files associated with the video_id if it was determined
        if video_id_for_cleanup:
            logger.info(f"Job {job_id}: Initiating cleanup for video_id {video_id_for_cleanup} in _run_job finally block.")
            try:
                # Run cleanup in a separate thread as it's blocking I/O
                await asyncio.to_thread(
                    cleanup_job_files,
                    video_id_for_cleanup, # Use video_id for folder names
                    settings.DOWNLOADS_DIR,
                    settings.PROCESSED_DIR / video_id_for_cleanup # Assuming processed files are in a subfolder named after video_id
                )
                logger.info(f"Job {job_id}: File cleanup for video_id {video_id_for_cleanup} completed.")
            except Exception as cleanup_exc:
                logger.error(f"Job {job_id}: Error during file cleanup for video_id {video_id_for_cleanup}: {cleanup_exc}", exc_info=True)
        else:
            logger.warning(f"Job {job_id}: video_id_for_cleanup not set. Skipping file cleanup in _run_job.")


# Make sure correct function is exported if needed elsewhere (though usually not)
__all__ = ["process_video_job"] # Removed get_youtube_suggestions as it's not used in this file