# File: backend/core/merger.py
# Merges video, audio, and ASS subtitles.
# UPDATED: Removed explicit '-map' argument causing ffmpeg error.
# UPDATED (v2): Added logging for pitch shift application.

import asyncio
import logging
from pathlib import Path
import ffmpeg as ffmpeg_python
from typing import Optional, Dict, Union

logger = logging.getLogger(__name__)

# --- Helper to build rubberband filter string ---
def build_rubberband_filter(pitch_shift_semitones: Optional[float]) -> Optional[str]:
    """Builds the rubberband filter string for ffmpeg if pitch shift is needed."""
    if pitch_shift_semitones is None or pitch_shift_semitones == 0:
        logger.debug("No pitch shift requested (value is None or 0).")
        return None
    try:
        shift = float(pitch_shift_semitones)
        # pow(2, semitones / 12.0) calculates the pitch factor
        pitch_scale = pow(2, shift / 12.0)
        # Clamp to reasonable range (e.g., 0.5x to 2x pitch) to avoid extreme artifacts
        pitch_scale = max(0.5, min(pitch_scale, 2.0))
        filter_str = f"rubberband=pitch={pitch_scale:.4f}" # Format factor
        logger.info(f"Applying rubberband pitch shift: {shift} semitones -> scale factor {pitch_scale:.4f}")
        return filter_str
    except (ValueError, TypeError) as e:
        logger.error(f"Error calculating pitch scale for '{pitch_shift_semitones}': {e}")
        return None

# --- Function to get basic subtitle style options (less critical now with ASS) ---
def get_basic_ffmpeg_subtitle_style_options(position: str = 'bottom', font_size: int = 30, font_name: str = 'Poppins Bold') -> Dict[str, Union[str, int]]:
    """Creates a dictionary of basic subtitle style options for FFmpeg's filter."""
    alignment = 8 if position == "top" else 2
    margin_v = 35
    outline = 1.8
    shadow = 1.2
    primary_color = "&HFFFFFF"
    outline_color = "&H000000"

    style_options = {
        'FontName': font_name,
        'FontSize': str(font_size),
        'PrimaryColour': primary_color,
        'OutlineColour': outline_color,
        'BorderStyle': '1',
        'Outline': str(outline),
        'Shadow': str(shadow),
        'Alignment': str(alignment),
        'MarginV': str(margin_v),
        'Bold': '-1'
    }
    return style_options

# --- Merge Functions ---

async def merge_with_subtitles(
    job_id: str,
    video_path: Path,
    instrumental_path: Path,
    ass_path: Path,
    video_id: str,
    sub_pos: str,
    processed_dir: Path,
    stem_config: Optional[Dict] = None,
    font_size: int = 30
    ) -> Path:
    """
    Merges video, instrumental audio (with potential pitch shift), and ASS subtitles.
    """
    try:
        processed_video_path = await asyncio.to_thread(
            _merge_audio_with_subtitles_sync,
            video_path, instrumental_path, ass_path, video_id, sub_pos, job_id, processed_dir, stem_config, font_size
        )
        if not processed_video_path or not processed_video_path.exists():
            raise RuntimeError("Merging function completed but final video file not found.")
        return processed_video_path
    except Exception as e:
        logger.error(f"Merging step (with ASS subs) failed for job {job_id}: {e}", exc_info=True)
        raise RuntimeError(f"Merging failed: {e}") from e

async def merge_without_subtitles(
    job_id: str,
    video_path: Path,
    instrumental_path: Path,
    video_id: str,
    processed_dir: Path,
    stem_config: Optional[Dict] = None
    ) -> Path:
    """
    Merges video and instrumental audio (with potential pitch shift), no subtitles.
    """
    try:
        processed_video_path = await asyncio.to_thread(
            _merge_audio_without_subtitles_sync,
            video_path, instrumental_path, video_id, job_id, processed_dir, stem_config
        )
        if not processed_video_path or not processed_video_path.exists():
            raise RuntimeError("Merging function completed but final video file not found.")
        return processed_video_path
    except Exception as e:
        logger.error(f"Merging step (without subs) failed for job {job_id}: {e}", exc_info=True)
        raise RuntimeError(f"Merging failed: {e}") from e


# --- Sync Merge Functions ---

def _merge_audio_with_subtitles_sync(
    original_video_path: Path,
    instrumental_audio_path: Path,
    ass_path: Path,
    video_id: str,
    subtitle_position: str,
    job_id: str,
    processed_dir: Path,
    stem_config: Optional[Dict] = None,
    font_size: int = 30
) -> Path:
    """
    Synchronous function to merge video, instrumental audio (pitch shifted if requested),
    and ASS subtitles using the 'subtitles' filter.
    """
    output_path = processed_dir / f"{video_id}_karaoke.mp4"
    logger.info(f"Job {job_id}: Merging with ASS subtitles '{ass_path.name}' into '{output_path.name}' (Pos: {subtitle_position}, Font Size: {font_size} used in ASS)...")

    if not original_video_path.is_file(): raise FileNotFoundError(f"Original video not found: {original_video_path}")
    if not instrumental_audio_path.is_file(): raise FileNotFoundError(f"Instrumental audio not found: {instrumental_audio_path}")

    ass_exists_and_valid = ass_path.is_file() and ass_path.stat().st_size > 100
    if not ass_exists_and_valid:
        logger.warning(f"Job {job_id}: ASS file invalid or empty: {ass_path}. Merging without subtitles fallback.")
        return _merge_audio_without_subtitles_sync(
            original_video_path, instrumental_audio_path, video_id, job_id, processed_dir, stem_config
        )

    # Prepare ASS Subtitle Filter
    ass_filter_path = str(ass_path.resolve()).replace('\\', '/').replace(':', r'\:')
    vf_string = f"subtitles=filename='{ass_filter_path}'"
    logger.info(f"Job {job_id}: Using subtitles filter: {vf_string}")

    # Pitch Shift Filter
    audio_filter = None
    if stem_config and "pitch_shifts" in stem_config and isinstance(stem_config["pitch_shifts"], dict):
        pitch_shift_semitones = stem_config["pitch_shifts"].get("instrumental")
        logger.info(f"Job {job_id}: Checking for instrumental pitch shift: value = {pitch_shift_semitones}") # Log received value
        audio_filter = build_rubberband_filter(pitch_shift_semitones)
    else:
        logger.debug(f"Job {job_id}: No pitch shift data found in stem_config.")


    # FFmpeg Command
    try:
        input_video = ffmpeg_python.input(str(original_video_path))
        input_audio = ffmpeg_python.input(str(instrumental_audio_path))

        video_stream = input_video['v']
        audio_stream = input_audio['a']

        output_args = {
            'vcodec': 'libx264', 'preset': 'fast', 'crf': 23,
            'acodec': 'aac', 'audio_bitrate': '192k',
            'vf': vf_string,
            'loglevel': 'warning',
        }

        if audio_filter:
            output_args['af'] = audio_filter
            logger.info(f"Job {job_id}: Applying audio filter via -af: {audio_filter}")
            output_args['acodec'] = 'aac' # Force re-encode if filter applied
            output_args['audio_bitrate'] = '192k'

        # Build the output stream definition
        stream = ffmpeg_python.output(
            video_stream,
            audio_stream,
            str(output_path),
            **output_args
        ).overwrite_output()

        logger.info(f"Job {job_id}: Running ffmpeg command (merge with ASS): {' '.join(stream.get_args())}") # Log the command args
        stdout, stderr = ffmpeg_python.run(stream, capture_stdout=True, capture_stderr=True)

        if not output_path.is_file() or output_path.stat().st_size < 1024:
            logger.error(f"Job {job_id}: ffmpeg produced no valid file: {output_path}")
            if stderr: logger.error(f"ffmpeg stderr:\n{stderr.decode(errors='ignore')}")
            raise RuntimeError("ffmpeg failed to create final video with ASS subtitles.")

        logger.info(f"Job {job_id}: Merged video with ASS subtitles successfully: {output_path.name}")
        return output_path

    except ffmpeg_python.Error as e:
        stderr_decoded = e.stderr.decode(errors='ignore') if e.stderr else 'No stderr'
        logger.error(f"Job {job_id}: ffmpeg error merging with ASS subtitles:\n{stderr_decoded}")
        if "rubberband" in stderr_decoded.lower():
            logger.error("Error likely related to rubberband filter. Ensure FFmpeg has librubberband support.")
        last_line = stderr_decoded.strip().splitlines()[-1] if stderr_decoded.strip() else "ffmpeg error (no details)"
        raise RuntimeError(f"Merge failed: {last_line}") from e
    except Exception as e:
        logger.error(f"Job {job_id}: Unexpected error merging with ASS subtitles: {e}", exc_info=True)
        raise RuntimeError(f"Unexpected error merging video with ASS subtitles: {e}") from e


def _merge_audio_without_subtitles_sync(
    original_video_path: Path,
    instrumental_audio_path: Path,
    video_id: str,
    job_id: str,
    processed_dir: Path,
    stem_config: Optional[Dict] = None
) -> Path:
    """
    Synchronous function to merge video and instrumental audio (pitch shifted if requested).
    """
    output_path = processed_dir / f"{video_id}_karaoke.mp4"
    logger.info(f"Job {job_id}: Merging without subtitles into '{output_path.name}'...")

    if not original_video_path.is_file(): raise FileNotFoundError(f"Original video not found: {original_video_path}")
    if not instrumental_audio_path.is_file(): raise FileNotFoundError(f"Instrumental audio not found: {instrumental_audio_path}")

    audio_filter = None
    if stem_config and "pitch_shifts" in stem_config and isinstance(stem_config["pitch_shifts"], dict):
        pitch_shift_semitones = stem_config["pitch_shifts"].get("instrumental")
        logger.info(f"Job {job_id}: Checking for instrumental pitch shift: value = {pitch_shift_semitones}") # Log received value
        audio_filter = build_rubberband_filter(pitch_shift_semitones)
    else:
        logger.debug(f"Job {job_id}: No pitch shift data found in stem_config.")


    try:
        input_video = ffmpeg_python.input(str(original_video_path))
        input_audio = ffmpeg_python.input(str(instrumental_audio_path))

        output_args = {
            'loglevel': 'warning',
        }

        if audio_filter:
            logger.info(f"Job {job_id}: Applying audio filter: {audio_filter}")
            output_args.update({
                'vcodec': 'copy', # Try copying video first
                'acodec': 'aac', 'audio_bitrate': '192k', # Re-encode audio due to filter
                'af': audio_filter # Set audio filter
            })
        else:
            # Try copying both streams if no filter
            output_args.update({'vcodec': 'copy', 'acodec': 'copy'})

        stream = ffmpeg_python.output(
            input_video['v'], # Explicitly select video stream 0 from input 0
            input_audio['a'], # Explicitly select audio stream 0 from input 1
            str(output_path),
            **output_args
        ).overwrite_output()

        logger.info(f"Job {job_id}: Running ffmpeg command (merge without subs, attempt 1): {' '.join(stream.get_args())}") # Log the command args
        stdout, stderr = ffmpeg_python.run(stream, capture_stdout=True, capture_stderr=True)

        if not output_path.is_file() or output_path.stat().st_size < 1024:
            logger.warning(f"Job {job_id}: Initial merge attempt failed (Args: {output_args}). Retrying with video re-encode.")
            # --- Retry Logic ---
            output_args['vcodec'] = 'libx264'; output_args['preset'] = 'fast'; output_args['crf'] = 23
            if output_args.get('acodec') == 'copy' and not audio_filter:
                output_args['acodec'] = 'aac'; output_args['audio_bitrate'] = '192k'
            if audio_filter and 'af' not in output_args: output_args['af'] = audio_filter

            stream_recode = ffmpeg_python.output(
                input_video['v'],
                input_audio['a'],
                str(output_path),
                **output_args
            ).overwrite_output()

            logger.info(f"Job {job_id}: Retrying ffmpeg merge with re-encode: {' '.join(stream_recode.get_args())}") # Log the command args
            stdout, stderr = ffmpeg_python.run(stream_recode, capture_stdout=True, capture_stderr=True)

            if not output_path.is_file() or output_path.stat().st_size < 1024:
                logger.error(f"Job {job_id}: ffmpeg merge failed even after re-encoding.")
                if stderr: logger.error(f"ffmpeg stderr (re-encode):\n{stderr.decode(errors='ignore')}")
                raise RuntimeError("ffmpeg failed to create final video even with re-encoding.")
            else:
                logger.info(f"Job {job_id}: Successfully merged video (re-encoded): {output_path.name}")
        else:
            logger.info(f"Job {job_id}: Successfully merged video (initial attempt): {output_path.name}")

        return output_path

    except ffmpeg_python.Error as e:
        stderr_decoded = e.stderr.decode(errors='ignore') if e.stderr else 'No stderr'
        logger.error(f"Job {job_id}: ffmpeg error during merge:\n{stderr_decoded}")
        if "rubberband" in stderr_decoded.lower():
            logger.error("Error likely related to rubberband filter. Ensure FFmpeg has librubberband support.")
        last_line = stderr_decoded.strip().splitlines()[-1] if stderr_decoded.strip() else "ffmpeg error"
        raise RuntimeError(f"Merge failed: {last_line}") from e
    except Exception as e:
        logger.error(f"Job {job_id}: Unexpected error merging without subtitles: {e}", exc_info=True)
        raise RuntimeError(f"Unexpected error merging video: {e}") from e