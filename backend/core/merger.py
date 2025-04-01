# File: backend/core/merger.py
import asyncio
import logging
from pathlib import Path

import ffmpeg as ffmpeg_python

logger = logging.getLogger(__name__)

async def merge_with_subtitles(
    job_id: str,
    video_path: Path,
    instrumental_path: Path,
    srt_path: Path,
    video_id: str,
    sub_pos: str,
    processed_dir: Path
    ) -> Path:
    """
    Merges video, instrumental audio, and subtitles using ffmpeg.
    Runs the synchronous merge function in a separate thread.
    """
    try:
        processed_video_path = await asyncio.to_thread(
            _merge_audio_with_subtitles_sync,
            video_path, instrumental_path, srt_path, video_id, sub_pos, job_id, processed_dir
        )
        if not processed_video_path or not processed_video_path.exists():
             raise RuntimeError("Merging function completed but final video file not found.")
        return processed_video_path
    except Exception as e:
         logger.error(f"Merging step (with subs) failed for job {job_id}: {e}", exc_info=True)
         raise RuntimeError(f"Merging failed: {e}") from e

async def merge_without_subtitles(
    job_id: str,
    video_path: Path,
    instrumental_path: Path,
    video_id: str,
    processed_dir: Path
    ) -> Path:
    """
    Merges video and instrumental audio (no subtitles).
    Runs the synchronous merge function in a separate thread.
    """
    try:
        processed_video_path = await asyncio.to_thread(
            _merge_audio_without_subtitles_sync,
            video_path, instrumental_path, video_id, job_id, processed_dir
        )
        if not processed_video_path or not processed_video_path.exists():
             raise RuntimeError("Merging function completed but final video file not found.")
        return processed_video_path
    except Exception as e:
         logger.error(f"Merging step (without subs) failed for job {job_id}: {e}", exc_info=True)
         raise RuntimeError(f"Merging failed: {e}") from e


def _merge_audio_with_subtitles_sync(
    original_video_path: Path, instrumental_audio_path: Path,
    srt_path: Path, video_id: str, subtitle_position: str, job_id: str, processed_dir: Path):
    """Synchronous function to merge video, instrumental audio, and subtitles using ffmpeg."""
    output_path = processed_dir / f"{video_id}_karaoke.mp4"
    logger.info(f"Job {job_id}: Merging with subtitles into '{output_path.name}' (Pos: {subtitle_position})...")

    # Validate input files exist before starting ffmpeg
    if not original_video_path.is_file(): raise FileNotFoundError(f"Original video not found: {original_video_path}")
    if not instrumental_audio_path.is_file(): raise FileNotFoundError(f"Instrumental audio not found: {instrumental_audio_path}")
    # Allow SRT to be missing or empty if subtitle generation was skipped or yielded no results
    srt_exists_and_valid = srt_path.is_file() and srt_path.stat().st_size > 0
    if not srt_exists_and_valid:
         logger.warning(f"Job {job_id}: SRT file '{srt_path.name}' not found or empty. Merging without subtitles.")
         # Fallback to merging without subtitles if SRT is invalid
         return _merge_audio_without_subtitles_sync(
             original_video_path, instrumental_audio_path, video_id, job_id, processed_dir
         )


    alignment = 8 if subtitle_position == "top" else 2 # Numpad alignment
    # Ensure SRT path is correctly formatted for ffmpeg filtergraph
    srt_filter_path = str(srt_path.resolve()).replace("\\", "/").replace(":", r"\:")

    # Consistent subtitle style
    subtitle_style = (
        r"FontName='Sora',"
        r"FontSize=26,"
        r"PrimaryColour=&HFFFFFF,"     # White
        r"OutlineColour=&HAA000000,"   # Darker translucent outline
        r"BackColour=&HAA000000,"      # Darker translucent background
        r"BorderStyle=1,"              # Outline + Shadow
        r"Outline=1.5,"
        r"Shadow=1,"
        rf"Alignment={alignment},"
        r"MarginV=30,"
        r"Spacing=0.2,"
        r"Bold=-1"
    )
    vf_string = f"subtitles=filename='{srt_filter_path}':force_style='{subtitle_style}'"
    # logger.debug(f"Job {job_id}: Using ffmpeg vf filter: {vf_string}")

    try:
        input_video = ffmpeg_python.input(str(original_video_path))
        input_audio = ffmpeg_python.input(str(instrumental_audio_path))
        # Combine video, new audio, and apply subtitles filter
        stream = ffmpeg_python.output(
            input_video['v'], input_audio['a'], str(output_path),
            vcodec='libx264', preset='fast', crf=23, # Video encoding
            acodec='aac', audio_bitrate='192k',      # Audio encoding
            vf=vf_string,                            # Subtitle filter
            loglevel="warning"                       # Reduce ffmpeg noise
        ).overwrite_output() # Add overwrite_output() here

        logger.info(f"Job {job_id}: Running ffmpeg merge command...")
        stdout, stderr = ffmpeg_python.run(stream, capture_stdout=True, capture_stderr=True) # No overwrite needed here

        # Log ffmpeg output for debugging if needed
        # if stdout: logger.debug(f"FFmpeg stdout:\n{stdout.decode(errors='ignore')}")
        # if stderr: logger.debug(f"FFmpeg stderr:\n{stderr.decode(errors='ignore')}")

        # Verify output
        if not output_path.is_file() or output_path.stat().st_size < 1024:
            logger.error(f"FFmpeg command seemed to run but failed to create valid output file: {output_path}")
            if stderr: logger.error(f"FFmpeg stderr:\n{stderr.decode(errors='ignore')}")
            raise RuntimeError("ffmpeg failed to create final video with subtitles.")

        logger.info(f"Job {job_id}: Successfully merged video with subtitles: {output_path.name}")
        return output_path

    except ffmpeg_python.Error as e:
        stderr_decoded = e.stderr.decode(errors='ignore') if e.stderr else 'No stderr captured'
        logger.error(f"Job {job_id}: ffmpeg error merging with subtitles:\n{stderr_decoded}")
        # Attempt to get a useful error message line
        last_line = stderr_decoded.strip().splitlines()[-1] if stderr_decoded.strip() else "ffmpeg error (no details)"
        raise RuntimeError(f"Merge failed: {last_line}") from e
    except Exception as e:
        logger.error(f"Job {job_id}: Unexpected error merging with subtitles: {e}", exc_info=True)
        raise RuntimeError(f"Unexpected error merging video with subtitles: {e}") from e


def _merge_audio_without_subtitles_sync(
    original_video_path: Path, instrumental_audio_path: Path, video_id: str, job_id: str, processed_dir: Path):
    """Synchronous function to merge video and instrumental audio (no subtitles)."""
    output_path = processed_dir / f"{video_id}_karaoke.mp4"
    logger.info(f"Job {job_id}: Merging without subtitles into '{output_path.name}'...")

    # Validate inputs
    if not original_video_path.is_file(): raise FileNotFoundError(f"Original video not found: {original_video_path}")
    if not instrumental_audio_path.is_file(): raise FileNotFoundError(f"Instrumental audio not found: {instrumental_audio_path}")

    try:
        input_video = ffmpeg_python.input(str(original_video_path))
        input_audio = ffmpeg_python.input(str(instrumental_audio_path))

        # Attempt to copy video codec, re-encode audio
        stream = ffmpeg_python.output(
            input_video['v'], input_audio['a'], str(output_path),
            vcodec='copy', acodec='aac', audio_bitrate='192k', loglevel="warning"
        ).overwrite_output()

        logger.info(f"Job {job_id}: Running ffmpeg merge command (copy video codec)...")
        ffmpeg_python.run(stream, capture_stdout=True, capture_stderr=True)

        # Verify output
        if not output_path.is_file() or output_path.stat().st_size < 1024:
             raise RuntimeError("ffmpeg failed to create final video (copy codec).") # Will be caught below

        logger.info(f"Job {job_id}: Successfully merged video without subtitles (copy codec): {output_path.name}")
        return output_path

    except ffmpeg_python.Error as e:
        # If codec copy failed, retry with re-encoding video
        stderr_str = e.stderr.decode(errors='ignore').lower() if e.stderr else ""
        # Check for common copy errors
        if 'codec copy' in stderr_str or 'incompatible' in stderr_str or 'invalid' in stderr_str or 'could not find tag' in stderr_str:
             logger.warning(f"Job {job_id}: Video codec copy failed (Error hint: {stderr_str.strip().splitlines()[-1] if stderr_str.strip() else 'N/A'}), retrying with libx264 re-encoding...")
             try:
                  # Re-encode video using libx264
                  stream_recode = ffmpeg_python.output(
                      input_video['v'], input_audio['a'], str(output_path),
                      vcodec='libx264', preset='fast', crf=23,
                      acodec='aac', audio_bitrate='192k', loglevel="warning"
                  ).overwrite_output()

                  logger.info(f"Job {job_id}: Running ffmpeg merge command (re-encode video codec)...")
                  ffmpeg_python.run(stream_recode, capture_stdout=True, capture_stderr=True)

                  # Verify output again
                  if not output_path.is_file() or output_path.stat().st_size < 1024:
                      raise RuntimeError("ffmpeg re-encoding retry also failed to create final video.")

                  logger.info(f"Job {job_id}: Successfully merged video without subtitles (re-encoded): {output_path.name}")
                  return output_path
             except Exception as retry_e:
                  logger.error(f"Job {job_id}: ffmpeg re-encoding retry also failed: {retry_e}", exc_info=True)
                  # If retry fails, raise the error from the retry attempt
                  raise RuntimeError(f"Merge failed even with re-encoding: {retry_e}") from retry_e
        else:
             # Log other unexpected ffmpeg errors
             logger.error(f"Job {job_id}: ffmpeg error merging without subtitles:\n{stderr_str}")
             last_line = stderr_str.strip().splitlines()[-1] if stderr_str.strip() else "ffmpeg error (no details)"
             raise RuntimeError(f"Merge failed: {last_line}") from e
    except Exception as e:
        # Catch other potential errors (e.g., file not found before ffmpeg run)
        logger.error(f"Job {job_id}: Unexpected error merging without subtitles: {e}", exc_info=True)
        raise RuntimeError(f"Unexpected error merging video without subtitles: {e}") from e
