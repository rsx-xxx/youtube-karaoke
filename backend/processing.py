# File: backend/processing.py
import asyncio
import logging
import time
import shutil
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional

from core.downloader import download_video
from core.audio_extractor import extract_audio
from core.separator import separate_tracks
from core.transcriber import transcribe_audio
from core.subtitles import generate_ass_karaoke
from core.merger import merge_with_subtitles, merge_without_subtitles
from lyrics_processing import (
    fetch_lyrics_from_genius,
    prepare_segments_for_karaoke,
    align_custom_lyrics_with_word_times
)
from utils.progress_manager import set_progress, get_progress, STEP_RANGES, job_tasks, progress_dict
from utils.file_system import cleanup_job_files
from config import settings

logger = logging.getLogger(__name__)


async def _process_lyrics_wrapper(
        job_id: str,
        transcript_segments_with_words: List[Dict],
        title: str,
        uploader: str,
        selected_lyrics: Optional[str] = None
) -> List[Dict]:
    """
    Orchestrates lyrics fetching and preparation.
    Priority: Custom Lyrics > Genius Lyrics > Whisper Transcription.
    """
    karaoke_ready_segments: List[Dict] = []
    lyrics_source_used = "None"

    # 1. Try Custom Lyrics if provided
    if selected_lyrics:
        logger.info(f"Job {job_id}: Using provided custom lyrics. Aligning timings.")
        lyrics_source_used = "Custom"
        try:
            karaoke_ready_segments = await asyncio.to_thread(
                align_custom_lyrics_with_word_times,
                selected_lyrics,
                transcript_segments_with_words
            )
            logger.info(f"Job {job_id}: Applied word timings to {len(karaoke_ready_segments)} lines of custom lyrics.")
        except Exception as e:
            logger.error(f"Job {job_id}: Error applying timings to custom lyrics: {e}. Will attempt fallback.",
                         exc_info=True)
            karaoke_ready_segments = []  # Ensure empty to trigger fallback

    # 2. If no custom lyrics (or custom failed), try Genius if enabled
    if not karaoke_ready_segments and settings.ENABLE_GENIUS_FETCH:
        logger.info(f"Job {job_id}: Attempting Genius lyrics fetch for Title='{title}', Artist='{uploader}'")
        official_lines: Optional[List[str]] = None
        try:
            genius_result_tuple = await asyncio.to_thread(fetch_lyrics_from_genius, title, uploader)
            if genius_result_tuple:
                official_lines, _ = genius_result_tuple
        except Exception as e:
            logger.warning(f"Job {job_id}: Error during Genius fetch: {e}.", exc_info=False)

        # IMPORTANT: Check if official_lines actually has content
        if official_lines and len(official_lines) > 0:
            lyrics_source_used = "Genius"
            logger.info(
                f"Job {job_id}: Found {len(official_lines)} non-empty official lines from Genius. Preparing segments...")
            try:
                karaoke_ready_segments = await asyncio.to_thread(
                    prepare_segments_for_karaoke,
                    transcript_segments_with_words,
                    official_lines
                )
                logger.info(
                    f"Job {job_id}: Prepared {len(karaoke_ready_segments)} karaoke segments using aligned Genius lyrics.")
            except Exception as e:
                logger.error(
                    f"Job {job_id}: Error preparing karaoke segments with Genius lyrics: {e}. Will attempt fallback.",
                    exc_info=True)
                karaoke_ready_segments = []  # Ensure empty for fallback
        else:
            # This case means Genius was tried but returned no usable lyrics (None or empty list)
            logger.info(
                f"Job {job_id}: Official lyrics from Genius are empty or were not found. Will use Whisper transcription if available.")
            # Fallback to Whisper will happen in the next block if karaoke_ready_segments is still empty

    elif not karaoke_ready_segments and not settings.ENABLE_GENIUS_FETCH:
        logger.info(f"Job {job_id}: Genius fetch disabled and no custom lyrics provided.")
        # Fallback to Whisper will happen in the next block

    # 3. Fallback to Whisper transcription if previous steps didn't yield segments
    if not karaoke_ready_segments:
        if transcript_segments_with_words and len(transcript_segments_with_words) > 0:
            lyrics_source_used = "Whisper"
            logger.info(
                f"Job {job_id}: Using original Whisper transcription ({len(transcript_segments_with_words)} segments) for lyrics and timing (fallback).")
            try:
                karaoke_ready_segments = await asyncio.to_thread(
                    prepare_segments_for_karaoke,
                    transcript_segments_with_words,
                    None  # Explicitly pass None for official_lyrics to use Whisper text
                )
                logger.info(
                    f"Job {job_id}: Prepared {len(karaoke_ready_segments)} segments using Whisper transcription as fallback.")
            except Exception as e:
                logger.error(f"Job {job_id}: Error preparing segments from Whisper transcription (fallback): {e}",
                             exc_info=True)
                karaoke_ready_segments = []
        else:
            logger.warning(f"Job {job_id}: No Whisper transcription segments available for fallback.")
            lyrics_source_used = "None (No transcription)"

    if not karaoke_ready_segments:
        logger.warning(
            f"Job {job_id}: No karaoke-ready segments could be produced. Lyrics source attempt: {lyrics_source_used}.")
    else:
        logger.info(
            f"Job {job_id}: Successfully produced {len(karaoke_ready_segments)} karaoke segments using lyrics from: {lyrics_source_used}.")

    return karaoke_ready_segments


async def _finalize_step(
        job_id: str,
        video_id: str,
        processed_video_path: Optional[Path],
        title: str,
        stems_dir: Optional[Path],
        processed_base_dir: Path
):
    if not processed_video_path or not processed_video_path.is_file():
        logger.error(
            f"Finalization failed for job {job_id}: Processed video path invalid or file missing: {processed_video_path}")
        raise FileNotFoundError(f"Final karaoke video file not found or invalid: {processed_video_path}")

    final_video_uri = None
    relative_stems_base_uri = None

    try:
        abs_processed_base = processed_base_dir.resolve()
        abs_video_path = processed_video_path.resolve()

        if abs_video_path.is_relative_to(abs_processed_base):
            relative_video_path_posix = abs_video_path.relative_to(abs_processed_base).as_posix()
        else:
            logger.warning(
                f"Job {job_id}: Final video path {abs_video_path} is not relative to processed base {abs_processed_base}. Using filename only.")
            relative_video_path_posix = processed_video_path.name
        final_video_uri = f"processed/{relative_video_path_posix.lstrip('/')}"
    except ValueError as e:
        logger.error(
            f"Job {job_id}: Could not create relative path for video {processed_video_path} from base {processed_base_dir}: {e}")
        final_video_uri = f"processed/{video_id}_karaoke.mp4"
    logger.debug(f"Job {job_id}: Final video URI constructed: {final_video_uri}")

    if stems_dir and stems_dir.is_dir():
        try:
            abs_stems_dir = stems_dir.resolve()
            abs_processed_base = processed_base_dir.resolve()

            if abs_stems_dir.is_relative_to(abs_processed_base):
                relative_stems_path_posix = abs_stems_dir.relative_to(abs_processed_base).as_posix()
                relative_stems_base_uri = f"processed/{relative_stems_path_posix.lstrip('/')}"
            else:
                logger.warning(
                    f"Job {job_id}: Stems dir {abs_stems_dir} not directly relative to processed_base {abs_processed_base}. Attempting alternative relative path construction.")
                # This part can be tricky if the structure isn't fixed.
                # Assuming stems_dir is something like .../processed/VIDEO_ID/MODEL/MODEL/AUDIO_STEM_NAME/
                # and we want processed/VIDEO_ID/MODEL/MODEL/AUDIO_STEM_NAME
                if video_id in abs_stems_dir.parts:
                    # Try to build from video_id folder, assuming it's inside processed_base_dir
                    video_id_folder_path = processed_base_dir / video_id
                    if abs_stems_dir.is_relative_to(video_id_folder_path):
                        relative_to_video_id_folder = abs_stems_dir.relative_to(video_id_folder_path).as_posix()
                        relative_stems_base_uri = f"processed/{video_id}/{relative_to_video_id_folder.lstrip('/')}"
                    else:  # Fallback if not relative to video_id_folder as expected
                        relative_stems_base_uri = None
                        logger.error(
                            f"Job {job_id}: Stems dir {abs_stems_dir} is not relative to expected video_id folder {video_id_folder_path} or processed base.")
                else:
                    relative_stems_base_uri = None
                    logger.error(
                        f"Job {job_id}: Cannot determine a sensible relative URI for stems directory {abs_stems_dir} based on video_id or processed_base_dir.")
        except ValueError as e:
            logger.error(f"Job {job_id}: Could not create relative path for stems directory {stems_dir}: {e}")
            relative_stems_base_uri = None
    else:
        logger.warning(f"Job {job_id}: Stems directory not provided or not found: {stems_dir}. Stems URI will be null.")

    result_data = {
        "video_id": video_id,
        "processed_path": final_video_uri,
        "title": title,
        "stems_base_path": relative_stems_base_uri
    }
    set_progress(job_id, 100, "Karaoke video created successfully!", result=result_data, is_step_start=False,
                 step_name="finalize")
    logger.info(f"Job {job_id} finalized successfully. Result: {result_data}")
    return result_data


async def process_video_job(
        job_id: str,
        language: str,
        sub_pos: str,
        gen_subs: bool,
        final_font_size: int,
        url_or_search: Optional[str] = None,
        local_file_path_str: Optional[str] = None,
        selected_lyrics: Optional[str] = None,
        pitch_shifts: Optional[Dict[str, float]] = None
):
    loop = asyncio.get_running_loop()
    start_time = time.monotonic()
    set_progress(job_id, 0, "Job accepted, preparing...", is_step_start=True, step_name="init")

    task = loop.create_task(
        _run_job(job_id, url_or_search, local_file_path_str, language, sub_pos, gen_subs, selected_lyrics, pitch_shifts,
                 final_font_size)
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
            logger.warning(
                f"Job task {job_id} finished, but final status seems incomplete or errored. Time: {elapsed_time:.2f}s. Status: {final_status}")
            if not final_status or final_status.get("progress", 0) < 100:
                existing_message = final_status.get("message", "") if final_status else ""
                if not any(keyword in existing_message.lower() for keyword in ["error", "cancel", "fail"]):
                    set_progress(job_id, 100, "Job finished with uncertain status.", is_step_start=False,
                                 step_name="uncertain_finish")
                else:
                    logger.info(
                        f"Job {job_id} already has a final error/cancel status: '{existing_message}'. Not overwriting.")
    except asyncio.CancelledError:
        elapsed_time = time.monotonic() - start_time
        logger.warning(f"Job task {job_id} was explicitly cancelled after {elapsed_time:.2f} seconds.")
        current_status = get_progress(job_id)
        if current_status and current_status.get("progress", 0) < 100:
            if "cancel" not in current_status.get("message", "").lower():
                set_progress(job_id, 100, "Job cancelled during execution.", is_step_start=False, step_name="cancelled")
    except Exception as e:
        elapsed_time = time.monotonic() - start_time
        error_type = type(e).__name__
        error_message_detail = f"Processing error: {error_type}"
        full_error_log = f"Unhandled error during job {job_id} execution ({error_type})"
        logger.error(f"{full_error_log} after {elapsed_time:.2f} seconds. Details: {e}", exc_info=True)
        set_progress(job_id, 100, f"Error: {error_message_detail}. Check server logs for job ID {job_id}.",
                     is_step_start=False, step_name="pipeline_error")
    finally:
        finished_task = job_tasks.pop(job_id, None)
        if finished_task:
            logger.debug(f"Removed task reference for completed/failed job {job_id}")


async def _run_job(
        job_id: str,
        url_or_search: Optional[str],
        local_file_path_str: Optional[str],
        language: str,
        sub_pos: str,
        gen_subs: bool,
        selected_lyrics: Optional[str] = None,
        pitch_shifts: Optional[Dict[str, float]] = None,
        final_font_size: int = 30
):
    video_id_for_cleanup: Optional[str] = None
    job_succeeded = False

    video_id: Optional[str] = None
    video_path: Optional[Path] = None
    audio_path: Optional[Path] = None
    subtitle_path: Optional[Path] = None
    processed_video_path: Optional[Path] = None
    stems_output_dir: Optional[Path] = None
    title: str = "Karaoke Track"
    uploader: str = "Local File" if local_file_path_str else "YouTube"
    instrumental_path: Optional[Path] = None
    vocals_path: Optional[Path] = None
    transcript_segments_with_words: List[Dict] = []
    step_timings = {}

    local_upload_temp_job_folder: Optional[Path] = None
    if local_file_path_str:
        local_upload_temp_job_folder = Path(local_file_path_str).parent

    async def run_step(step_name: str, coro, *args, **kwargs):
        nonlocal video_id, video_path, title, uploader, audio_path, \
            instrumental_path, vocals_path, stems_output_dir, subtitle_path, \
            processed_video_path, transcript_segments_with_words, \
            video_id_for_cleanup

        step_start_time = time.monotonic()
        start_progress, end_progress = STEP_RANGES.get(step_name, (0, 0))
        step_title_display = step_name.replace('_', ' ').title()

        if job_id not in job_tasks:
            logger.warning(f"Job {job_id} task missing, likely cancelled before starting step '{step_name}'.")
            raise asyncio.CancelledError(f"Job {job_id} cancelled before step {step_name}")

        set_progress(job_id, start_progress, f"Starting: {step_title_display}...", is_step_start=True,
                     step_name=step_name)

        try:
            result = await coro(job_id, *args, **kwargs)

            if step_name == "download":
                video_id_from_dl, video_path_from_dl, title_from_dl, uploader_from_dl = result
                video_id, video_path, title, uploader = video_id_from_dl, video_path_from_dl, title_from_dl, uploader_from_dl
                video_id_for_cleanup = video_id
            elif step_name == "extract_audio":
                audio_path = result
            elif step_name == "separate_tracks":
                instrumental_path, vocals_path, stems_output_dir = result
            elif step_name == "transcribe":
                transcript_segments_with_words, _ = result
            elif step_name == "generate_ass":
                subtitle_path = result
            elif step_name == "merge":
                processed_video_path = result

            elapsed = time.monotonic() - step_start_time
            step_timings[step_name] = elapsed
            logger.info(f"Job {job_id}: Step '{step_name}' completed in {elapsed:.2f}s.")
            set_progress(job_id, end_progress, f"Completed: {step_title_display}", is_step_start=False,
                         step_name=step_name)
            return result

        except asyncio.CancelledError:
            logger.warning(f"Job {job_id}: Step '{step_name}' was cancelled.")
            current_status = get_progress(job_id)
            if current_status and "cancel" not in current_status.get("message", "").lower():
                set_progress(job_id, 100, f"Job cancelled during {step_title_display}.", is_step_start=False,
                             step_name="cancelled_in_step")
            raise
        except Exception as e:
            elapsed = time.monotonic() - step_start_time
            step_timings[step_name] = elapsed
            step_error_message = f"Error during '{step_title_display}': {str(e) or type(e).__name__}"
            logger.error(f"Job {job_id}: Step '{step_name}' failed after {elapsed:.2f}s: {e}", exc_info=True)
            set_progress(job_id, 100, step_error_message, is_step_start=False, step_name=f"{step_name}_error")
            raise e

    try:
        if local_file_path_str:
            set_progress(job_id, 0, "Processing local file...", is_step_start=True, step_name="local_file_setup")
            video_path = Path(local_file_path_str)
            if not video_path.is_file():
                raise FileNotFoundError(f"Local file not found or is not a file: {video_path}")
            video_id = video_path.stem
            video_id_for_cleanup = video_id
            title = video_path.name
            uploader = "Local Upload"
            _, download_end_progress = STEP_RANGES.get("download", (0, 15))
            set_progress(job_id, download_end_progress, "Local file provided", is_step_start=False,
                         step_name="download")
            logger.info(f"Job {job_id}: Using local file: {video_path}. Derived Video ID: {video_id}")
        elif url_or_search:
            await run_step("download", download_video, url_or_search, settings.DOWNLOADS_DIR)
        else:
            raise ValueError("No input provided: Either url_or_search or local_file_path_str is required.")

        if not video_id or not video_path:
            raise ValueError("video_id or video_path not established after input processing.")

        await run_step("extract_audio", extract_audio, video_path, video_id, settings.DOWNLOADS_DIR)
        if not audio_path: raise ValueError("Audio path not set after extraction.")

        await run_step("separate_tracks", separate_tracks, audio_path, video_id, settings.PROCESSED_DIR,
                       settings.DEMUCS_MODEL, settings.DEVICE)
        if not vocals_path or not instrumental_path: raise ValueError("Stems paths not set after separation.")

        merge_kwargs = {"stem_config": {"pitch_shifts": pitch_shifts} if pitch_shifts else None}
        logger.info(f"Job {job_id}: Preparing merge step with pitch config: {merge_kwargs.get('stem_config')}")

        karaoke_ready_segments_for_ass: List[Dict] = []
        if gen_subs:
            logger.info(f"Job {job_id}: Subtitle generation is ENABLED.")
            await run_step("transcribe", transcribe_audio, vocals_path, language)

            if not transcript_segments_with_words:
                logger.warning(
                    f"Job {job_id}: Transcription produced no segments. Skipping lyrics processing and ASS generation.")
                _, lyrics_end = STEP_RANGES["process_lyrics"];
                set_progress(job_id, lyrics_end, "Skipped lyrics (no transcription)", False, "skip_lyrics_notranscript")
                # Renamed generate_srt to generate_ass for consistency
                _, ass_end = STEP_RANGES.get("generate_ass", STEP_RANGES.get("generate_srt", (90, 93)));
                set_progress(job_id, ass_end, "Skipped ASS (no transcription)", False, "skip_ass_notranscript")
            else:
                logger.info(f"Job {job_id}: Transcription produced {len(transcript_segments_with_words)} segments.")
                karaoke_ready_segments_for_ass = await run_step(
                    "process_lyrics",
                    _process_lyrics_wrapper,
                    transcript_segments_with_words,
                    title,
                    uploader,
                    selected_lyrics
                )
                if not karaoke_ready_segments_for_ass:
                    logger.warning(
                        f"Job {job_id}: Lyrics processing produced no karaoke-ready segments. Skipping ASS generation.")
                    _, ass_end = STEP_RANGES.get("generate_ass", STEP_RANGES.get("generate_srt", (90, 93)));
                    set_progress(job_id, ass_end, "Skipped ASS (no lyrics)", False, "skip_ass_nolyrics")
                else:
                    logger.info(
                        f"Job {job_id}: Lyrics processing produced {len(karaoke_ready_segments_for_ass)} segments for ASS generation.")
                    await run_step("generate_ass", generate_ass_karaoke,  # Changed from generate_srt
                                   karaoke_ready_segments_for_ass, video_id, settings.PROCESSED_DIR,
                                   font_name='Poppins Bold', font_size=final_font_size, position=sub_pos)
                    if subtitle_path and subtitle_path.exists():
                        logger.info(f"Job {job_id}: ASS file generated successfully at: {subtitle_path}")
                    else:
                        logger.warning(
                            f"Job {job_id}: ASS generation completed, but file path is invalid or file missing: {subtitle_path}. Merging without subtitles.")
                        subtitle_path = None
        else:
            logger.info(
                f"Job {job_id}: Subtitle generation is DISABLED. Skipping transcription, lyrics, and ASS steps.")
            _, transcribe_end = STEP_RANGES["transcribe"];
            set_progress(job_id, transcribe_end, "Skipped transcription (disabled)", False, "skip_transcribe")
            _, lyrics_end = STEP_RANGES["process_lyrics"];
            set_progress(job_id, lyrics_end, "Skipped lyrics processing (disabled)", False, "skip_lyrics")
            _, ass_end = STEP_RANGES.get("generate_ass", STEP_RANGES.get("generate_srt", (90, 93)));
            set_progress(job_id, ass_end, "Skipped subtitle generation (disabled)", False, "skip_ass")
            subtitle_path = None

        if subtitle_path and subtitle_path.exists() and subtitle_path.stat().st_size > 100:
            logger.info(f"Job {job_id}: Merging with ASS subtitles from {subtitle_path}.")
            await run_step("merge", merge_with_subtitles,
                           video_path, instrumental_path, subtitle_path, video_id,
                           sub_pos, settings.PROCESSED_DIR,
                           **merge_kwargs, font_size=final_font_size)
        else:
            if gen_subs and karaoke_ready_segments_for_ass:  # Log only if subs were intended and lyrics were processed
                logger.warning(f"Job {job_id}: Proceeding to merge without subtitles (ASS file issue or empty).")
            else:
                logger.info(f"Job {job_id}: Merging without subtitles (subtitles disabled or no lyrics to process).")
            await run_step("merge", merge_without_subtitles,
                           video_path, instrumental_path, video_id,
                           settings.PROCESSED_DIR, **merge_kwargs)

        if not processed_video_path or not processed_video_path.exists():
            raise RuntimeError(f"Merge step finished but the final video file is missing: {processed_video_path}")

        await run_step("finalize", _finalize_step, video_id, processed_video_path, title,
                       stems_output_dir, settings.PROCESSED_DIR)
        job_succeeded = True

    except asyncio.CancelledError:
        logger.info(f"Job {job_id} execution pipeline was cancelled.")
    except Exception as e:
        current_status = get_progress(job_id)
        if current_status and current_status.get("progress", 0) < 100 and \
                not any(err_kw in current_status.get("message", "").lower() for err_kw in ["error", "fail", "cancel"]):
            error_message = f"Pipeline failed for job {job_id}: {type(e).__name__}"
            logger.error(f"{error_message} - Details: {e}", exc_info=True)
            detailed_error_msg = str(e) if str(e) else type(e).__name__
            set_progress(job_id, 100, f"Error: Pipeline failed: {detailed_error_msg}. Check logs.", False,
                         "pipeline_error_runjob_final")
    finally:
        if local_upload_temp_job_folder and local_upload_temp_job_folder.exists():
            logger.info(f"Job {job_id}: Removing temporary local upload job folder: {local_upload_temp_job_folder}")
            try:
                await asyncio.to_thread(shutil.rmtree, local_upload_temp_job_folder, ignore_errors=True)
            except Exception as e:
                logger.error(
                    f"Job {job_id}: Failed to remove temporary local upload folder {local_upload_temp_job_folder}: {e}")

        if not job_succeeded and video_id_for_cleanup:
            logger.warning(
                f"Job {job_id} did not succeed. Initiating cleanup for identifier '{video_id_for_cleanup}'.")
            try:
                await asyncio.to_thread(
                    cleanup_job_files,
                    video_id_for_cleanup,
                    settings.DOWNLOADS_DIR,
                    settings.PROCESSED_DIR
                )
                logger.info(
                    f"Job {job_id}: File cleanup for identifier '{video_id_for_cleanup}' completed after failure/cancellation.")
            except Exception as cleanup_exc:
                logger.error(
                    f"Job {job_id}: Error during file cleanup for identifier '{video_id_for_cleanup}' after failure/cancellation: {cleanup_exc}",
                    exc_info=True)
        elif job_succeeded:
            logger.info(f"Job {job_id} succeeded. Files for '{video_id_for_cleanup}' will be retained.")


__all__ = ["process_video_job"]