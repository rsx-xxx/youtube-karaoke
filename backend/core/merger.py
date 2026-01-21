# File: backend/core/merger.py
import asyncio
import logging
from pathlib import Path
import ffmpeg as ffmpeg_python
from typing import Optional, Dict, Union

logger = logging.getLogger(__name__)


def build_rubberband_filter(pitch_shift_semitones: Optional[float]) -> Optional[str]:
    """Build rubberband filter for pitch shift (changes tempo proportionally)."""
    if pitch_shift_semitones is None or pitch_shift_semitones == 0:
        logger.debug("No pitch shift requested (value is None or 0).")
        return None
    try:
        shift = float(pitch_shift_semitones)
        pitch_scale = pow(2, shift / 12.0)
        pitch_scale = max(0.5, min(pitch_scale, 2.0))
        filter_str = f"rubberband=pitch={pitch_scale:.4f}"
        logger.info(f"Applying rubberband pitch shift: {shift} semitones -> scale factor {pitch_scale:.4f}")
        return filter_str
    except (ValueError, TypeError) as e:
        logger.error(f"Error calculating pitch scale for '{pitch_shift_semitones}': {e}")
        return None


def build_global_pitch_filter(semitones: Optional[float]) -> Optional[str]:
    """
    Build rubberband filter for global pitch shift WITHOUT changing tempo.

    Args:
        semitones: Number of semitones to shift (-12 to +12)

    Returns:
        FFmpeg filter string for rubberband with tempo preservation, or None if no shift
    """
    if semitones is None or semitones == 0:
        logger.debug("No global pitch shift requested (value is None or 0).")
        return None
    try:
        shift = float(semitones)
        # Clamp to reasonable range
        shift = max(-12, min(shift, 12))
        pitch_scale = pow(2, shift / 12.0)
        # tempo=1 preserves original tempo while changing pitch
        filter_str = f"rubberband=pitch={pitch_scale:.4f}:tempo=1"
        logger.info(f"Applying global pitch shift: {shift} semitones -> scale {pitch_scale:.4f} (tempo preserved)")
        return filter_str
    except (ValueError, TypeError) as e:
        logger.error(f"Error calculating global pitch scale for '{semitones}': {e}")
        return None


def get_basic_ffmpeg_subtitle_style_options(position: str = 'bottom', font_size: int = 30,
                                            font_name: str = 'Poppins Bold') -> Dict[str, Union[str, int]]:
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
    output_path = processed_dir / f"{video_id}_karaoke.mp4"
    logger.info(
        f"Job {job_id}: Merging with ASS subtitles '{ass_path.name}' into '{output_path.name}' (Pos: {subtitle_position}, Font Size: {font_size} used in ASS)...")

    if not original_video_path.is_file(): raise FileNotFoundError(f"Original video not found: {original_video_path}")
    if not instrumental_audio_path.is_file(): raise FileNotFoundError(
        f"Instrumental audio not found: {instrumental_audio_path}")

    ass_exists_and_valid = ass_path.is_file() and ass_path.stat().st_size > 100
    if not ass_exists_and_valid:
        logger.warning(f"Job {job_id}: ASS file invalid or empty: {ass_path}. Merging without subtitles fallback.")
        return _merge_audio_without_subtitles_sync(
            original_video_path, instrumental_audio_path, video_id, job_id, processed_dir, stem_config
        )

    ass_filter_path = str(ass_path.resolve()).replace('\\', '/').replace(':', r'\:')
    vf_string = f"subtitles=filename='{ass_filter_path}'"
    logger.info(f"Job {job_id}: Using subtitles filter: {vf_string}")

    audio_filter = None
    # Check for global_pitch first (new approach - preserves tempo)
    if stem_config and "global_pitch" in stem_config:
        global_pitch = stem_config.get("global_pitch")
        if global_pitch is not None and global_pitch != 0:
            logger.info(f"Job {job_id}: Applying global pitch shift: {global_pitch} semitones")
            audio_filter = build_global_pitch_filter(global_pitch)
    # Fallback to legacy pitch_shifts if no global_pitch
    elif stem_config and "pitch_shifts" in stem_config and isinstance(stem_config["pitch_shifts"], dict):
        pitch_shift_semitones = stem_config["pitch_shifts"].get("instrumental")
        logger.info(f"Job {job_id}: Checking for instrumental pitch shift: value = {pitch_shift_semitones}")
        audio_filter = build_rubberband_filter(pitch_shift_semitones)
    else:
        logger.debug(f"Job {job_id}: No pitch shift data found in stem_config.")

    try:
        input_video = ffmpeg_python.input(str(original_video_path))
        input_audio = ffmpeg_python.input(str(instrumental_audio_path))

        video_stream = input_video['v']
        audio_stream = input_audio['a']

        output_args = {
            'vcodec': 'libx264',
            'preset': 'medium',      # Better quality than 'fast'
            'crf': 20,               # Higher quality (lower = better, 18-23 is good)
            'acodec': 'aac',
            'audio_bitrate': '320k', # High quality audio
            'ar': '48000',           # 48kHz audio
            'vf': vf_string,
            'movflags': '+faststart', # Web optimization
            'loglevel': 'warning',
        }

        if audio_filter:
            output_args['af'] = audio_filter
            logger.info(f"Job {job_id}: Applying audio filter via -af: {audio_filter}")
            output_args['acodec'] = 'aac'
            output_args['audio_bitrate'] = '192k'

        stream = ffmpeg_python.output(
            video_stream,
            audio_stream,
            str(output_path),
            **output_args
        ).overwrite_output()

        logger.info(f"Job {job_id}: Running ffmpeg command (merge with ASS): {' '.join(stream.get_args())}")
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
    output_path = processed_dir / f"{video_id}_karaoke.mp4"
    logger.info(f"Job {job_id}: Merging without subtitles into '{output_path.name}'...")

    if not original_video_path.is_file(): raise FileNotFoundError(f"Original video not found: {original_video_path}")
    if not instrumental_audio_path.is_file(): raise FileNotFoundError(
        f"Instrumental audio not found: {instrumental_audio_path}")

    audio_filter = None
    # Check for global_pitch first (new approach - preserves tempo)
    if stem_config and "global_pitch" in stem_config:
        global_pitch = stem_config.get("global_pitch")
        if global_pitch is not None and global_pitch != 0:
            logger.info(f"Job {job_id}: Applying global pitch shift: {global_pitch} semitones")
            audio_filter = build_global_pitch_filter(global_pitch)
    # Fallback to legacy pitch_shifts if no global_pitch
    elif stem_config and "pitch_shifts" in stem_config and isinstance(stem_config["pitch_shifts"], dict):
        pitch_shift_semitones = stem_config["pitch_shifts"].get("instrumental")
        logger.info(f"Job {job_id}: Checking for instrumental pitch shift: value = {pitch_shift_semitones}")
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
                'vcodec': 'copy',
                'acodec': 'aac',
                'audio_bitrate': '320k',
                'ar': '48000',
                'af': audio_filter,
                'movflags': '+faststart',
            })
        else:
            logger.info(f"Job {job_id}: No audio filter. Will copy video and re-encode audio to AAC.")
            output_args.update({
                'vcodec': 'copy',
                'acodec': 'aac',
                'audio_bitrate': '320k',
                'ar': '48000',
                'movflags': '+faststart',
            })

        stream = ffmpeg_python.output(
            input_video['v'],
            input_audio['a'],
            str(output_path),
            **output_args
        ).overwrite_output()

        logger.info(
            f"Job {job_id}: Running ffmpeg command (merge without subs, attempt 1): {' '.join(stream.get_args())}")
        stdout, stderr = ffmpeg_python.run(stream, capture_stdout=True, capture_stderr=True)

        if not output_path.is_file() or output_path.stat().st_size < 1024:
            logger.warning(
                f"Job {job_id}: Initial merge attempt failed (Args: {output_args}). Retrying with video re-encode.")

            output_args['vcodec'] = 'libx264';
            output_args['preset'] = 'fast';
            output_args['crf'] = 23

            stream_recode = ffmpeg_python.output(
                input_video['v'],
                input_audio['a'],
                str(output_path),
                **output_args
            ).overwrite_output()

            logger.info(f"Job {job_id}: Retrying ffmpeg merge with re-encode: {' '.join(stream_recode.get_args())}")
            stdout_recode, stderr_recode = ffmpeg_python.run(stream_recode, capture_stdout=True, capture_stderr=True)

            if not output_path.is_file() or output_path.stat().st_size < 1024:
                logger.error(f"Job {job_id}: ffmpeg merge failed even after re-encoding.")
                if stderr_recode:
                    logger.error(f"ffmpeg stderr (re-encode):\n{stderr_recode.decode(errors='ignore')}")
                elif stderr:
                    logger.error(f"ffmpeg stderr (initial attempt):\n{stderr.decode(errors='ignore')}")
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
