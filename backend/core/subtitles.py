# File: backend/core/subtitles.py
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

SUBTITLE_LEAD_TIME_SECONDS = 0.30
SUBTITLE_PERSIST_SECONDS = 0.50
MIN_LINE_DURATION_SECONDS = 1.0

MIN_K_DURATION_CS = 5
MAX_K_DURATION_CS = 350

GAP_THRESHOLD_FOR_CUES = 4.0
COUNTDOWN_TOTAL_DURATION = 3.0
LYRIC_PREP_LEAD_TIME = 1.2
COUNTDOWN_STEP_DURATION = 1.0

ASS_HEADER_TEMPLATE = """
[Script Info]
Title: Karaoke Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None
PlayResX: 1920
PlayResY: 1080
Collisions: Normal

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H{alpha_pri}{color_pri},&H{alpha_sec}{color_sec},&H{alpha_out}{color_out},&H{alpha_back}{color_back},{bold},0,0,0,100,100,1.0,0,{border_style},{outline:.2f},{shadow:.2f},{alignment},30,30,{margin_v},1
Style: Highlight,{font_name},{font_size},&H{alpha_sec}{color_sec},&H{alpha_pri}{color_pri},&H{alpha_out}{color_out},&H{alpha_back}{color_back},{bold},0,0,0,100,100,1.0,0,{border_style},{outline:.2f},{shadow:.2f},{alignment},30,30,{margin_v},1
Style: Countdown,{font_name},{countdown_font_size},&H00FFFFFF,&H0000DDFF,&H50000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,2,5,30,30,40,1
Style: NextUp,{font_name},{next_up_font_size},&H88{color_pri},&H88{color_sec},&H60{color_out},&H80{color_back},0,0,0,0,100,100,0.5,0,{border_style},{outline_next_up:.2f},{shadow_next_up:.2f},8,30,30,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def format_ass_time(seconds: float) -> str:
    if not isinstance(seconds, (int, float)) or seconds < 0: seconds = 0.0
    total_centiseconds = round(seconds * 100)
    centiseconds = total_centiseconds % 100
    total_seconds = total_centiseconds // 100
    secs = total_seconds % 60
    total_minutes = total_seconds // 60
    mins = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours:d}:{mins:02d}:{secs:02d}.{centiseconds:02d}"


def escape_ass_text(text: str) -> str:
    if not isinstance(text, str): return ""
    text = text.replace('{', r'\{')
    text = text.replace('}', r'\}')
    return text


async def generate_ass_karaoke(
        job_id: str,
        karaoke_segments: List[Dict],
        video_id: str,
        processed_dir: Path,
        font_name: str = 'Montserrat',
        font_size: int = 32,
        position: str = 'bottom',
        primary_color: str = 'FFFFFF',
        secondary_color: str = '00DDFF',
        outline_color: str = '000000',
        back_color: str = '000000',
        primary_alpha: str = '00',
        secondary_alpha: str = '00',
        outline_alpha: str = '40',
        back_alpha: str = '60'
) -> Optional[Path]:
    r"""
    Generates an Advanced SubStation Alpha (ASS) subtitle file with karaoke highlighting.
    Includes countdowns and advance lyric display ("Next Up") for long instrumental breaks.
    Karaoke effect is achieved using {\k<duration_cs>} tags for word-by-word highlighting.
    """
    final_font_size = font_size if isinstance(font_size, int) and font_size >= 10 else 30
    ass_path = processed_dir / f"{video_id}.ass"
    logger.info(
        f"Job {job_id}: Generating ASS karaoke: '{ass_path.name}' Font: {font_name} {final_font_size}px, Pos: {position}")

    if not karaoke_segments:
        logger.warning(f"Job {job_id}: No segments for ASS generation. Skipping.")
        return None

    valid_segments = []
    for i, seg in enumerate(karaoke_segments):
        if (isinstance(seg, dict) and 'start' in seg and 'end' in seg and
                isinstance(seg.get('start'), (int, float)) and isinstance(seg.get('end'), (int, float)) and seg['end'] >
                seg['start'] and  # Ensure end > start
                isinstance(seg.get('text'), str) and seg['text'].strip() and
                isinstance(seg.get('words'), list) and seg['words'] and
                all(isinstance(w, dict) and 'text' in w and 'start' in w and 'end' in w and
                    isinstance(w.get('text'), str) and w['text'].strip() and
                    isinstance(w.get('start'), (int, float)) and isinstance(w.get('end'), (int, float)) and
                    w['end'] > w['start']  # Ensure word end > word start
                    for w in seg['words'])):
            valid_segments.append(seg)
        else:
            logger.warning(
                f"Job {job_id}: Skipping segment {i} due to invalid structure/timing: {str(seg)[:100]}...")
            # Log more details about the invalid segment
            if not (isinstance(seg, dict) and 'start' in seg and 'end' in seg):
                logger.debug(f"Segment {i} missing start/end keys or not a dict.")
            elif not (isinstance(seg.get('start'), (int, float)) and isinstance(seg.get('end'), (int, float)) and seg[
                'end'] > seg['start']):
                logger.debug(f"Segment {i} has invalid start/end times: start={seg.get('start')}, end={seg.get('end')}")
            elif not (isinstance(seg.get('text'), str) and seg['text'].strip()):
                logger.debug(f"Segment {i} has missing or empty text.")
            elif not (isinstance(seg.get('words'), list) and seg['words']):
                logger.debug(f"Segment {i} has missing or empty words list.")
            else:  # Problem is within the words list
                for word_idx, w_debug in enumerate(seg['words']):
                    if not (isinstance(w_debug,
                                       dict) and 'text' in w_debug and 'start' in w_debug and 'end' in w_debug and
                            isinstance(w_debug.get('text'), str) and w_debug['text'].strip() and
                            isinstance(w_debug.get('start'), (int, float)) and isinstance(w_debug.get('end'),
                                                                                          (int, float)) and
                            w_debug['end'] > w_debug['start']):
                        logger.debug(f"Segment {i}, Word {word_idx} is invalid: {str(w_debug)[:100]}")
                        break  # Log first invalid word

    if not valid_segments:
        logger.error(
            f"Job {job_id}: No valid segments with timed words after validation. Cannot generate ASS.")
        return None

    try:
        await asyncio.to_thread(
            _generate_ass_file_sync,
            valid_segments,
            ass_path, job_id,
            font_name, final_font_size, position,
            primary_color, secondary_color, outline_color, back_color,
            primary_alpha, secondary_alpha, outline_alpha, back_alpha
        )
        if not ass_path.exists():
            logger.error(f"Job {job_id}: ASS generation finished but file not found: {ass_path}")
            raise IOError("ASS generation failed, file not created.")
        elif ass_path.stat().st_size < 100:
            logger.warning(f"Job {job_id}: Generated ASS file is very small (<100 bytes). Content: {ass_path}")
        return ass_path
    except Exception as e:
        logger.error(f"ASS generation failed for job {job_id}: {e}", exc_info=True)
        try:
            ass_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise IOError(f"ASS generation failed: {e}") from e


def _generate_ass_file_sync(
        karaoke_segments: List[Dict],
        ass_path: Path,
        job_id: str,
        font_name: str, font_size: int, position: str,
        pri_color: str, sec_color: str, out_color: str, back_color: str,
        pri_alpha: str, sec_alpha: str, out_alpha: str, back_alpha: str
):
    alignment = 8 if position == "top" else 2
    margin_v = max(40, int(font_size * 1.5)) if position == "bottom" else max(35, int(font_size * 1.4))
    # Improved outline and shadow for better readability
    outline_thickness = max(2.0, font_size / 12.0)
    shadow_depth = max(1.5, font_size / 16.0)
    border_style = 1
    bold_flag = -1

    countdown_font_size = int(font_size * 1.4)
    next_up_font_size = int(font_size * 0.75)
    outline_next_up = max(1.5, next_up_font_size / 14.0)
    shadow_next_up = max(1.0, next_up_font_size / 20.0)

    def format_ass_color_val(hex_color_str: str) -> str:
        if not isinstance(hex_color_str, str) or len(hex_color_str) != 6: return 'FFFFFF'
        try:
            int(hex_color_str, 16)
            return hex_color_str[4:6] + hex_color_str[2:4] + hex_color_str[0:2]
        except ValueError:
            return 'FFFFFF'

    header = ASS_HEADER_TEMPLATE.format(
        font_name=escape_ass_text(font_name), font_size=font_size,
        color_pri=format_ass_color_val(pri_color), color_sec=format_ass_color_val(sec_color),
        color_out=format_ass_color_val(out_color), color_back=format_ass_color_val(back_color),
        alpha_pri=pri_alpha, alpha_sec=sec_alpha, alpha_out=out_alpha, alpha_back=back_alpha,
        bold=bold_flag, border_style=border_style, outline=outline_thickness,
        shadow=shadow_depth, alignment=alignment, margin_v=margin_v,
        countdown_font_size=countdown_font_size,
        next_up_font_size=next_up_font_size,
        outline_next_up=outline_next_up,
        shadow_next_up=shadow_next_up
    )

    event_lines: List[str] = []
    word_count_total = 0
    last_segment_end_time = 0.0

    for segment_index, segment in enumerate(karaoke_segments):
        seg_start = segment.get('start')
        seg_end = segment.get('end')
        words = segment.get('words', [])
        segment_text_full_line = segment.get('text', " ")

        if seg_start is None or seg_end is None or seg_end <= seg_start or not words:
            logger.debug(f"Job {job_id}: Skipping segment idx {segment_index} in ASS gen (final check).")
            continue

        gap_before_segment = seg_start - last_segment_end_time
        if gap_before_segment >= GAP_THRESHOLD_FOR_CUES and segment_index > 0:  # Cue only after first segment
            next_up_start_time = max(last_segment_end_time + 0.1,
                                     seg_start - COUNTDOWN_TOTAL_DURATION - LYRIC_PREP_LEAD_TIME)
            next_up_end_time = max(next_up_start_time + 0.5, seg_start - COUNTDOWN_TOTAL_DURATION - 0.1)

            if next_up_end_time > next_up_start_time:
                preview_text_raw = segment_text_full_line
                next_up_text_preview = escape_ass_text(
                    preview_text_raw[:80] + ('...' if len(preview_text_raw) > 80 else '')
                )
                event_lines.append(
                    f"Dialogue: 1,{format_ass_time(next_up_start_time)},{format_ass_time(next_up_end_time)},NextUp,,0,0,0,,{next_up_text_preview}")

            for i in range(int(COUNTDOWN_TOTAL_DURATION / COUNTDOWN_STEP_DURATION), 0, -1):
                countdown_val = i
                countdown_start_time = max(next_up_end_time, seg_start - (countdown_val * COUNTDOWN_STEP_DURATION))
                countdown_end_time = seg_start - ((countdown_val - 1) * COUNTDOWN_STEP_DURATION) - 0.05

                if countdown_end_time > countdown_start_time:
                    event_lines.append(
                        f"Dialogue: 2,{format_ass_time(countdown_start_time)},{format_ass_time(countdown_end_time)},Countdown,,0,0,0,,{countdown_val}")

        display_start_time = max(0.0, seg_start - SUBTITLE_LEAD_TIME_SECONDS)
        # Line display ends a bit after the last word in it, or min duration
        display_end_time = max(seg_end + SUBTITLE_PERSIST_SECONDS, display_start_time + MIN_LINE_DURATION_SECONDS)

        ass_start_time_str = format_ass_time(display_start_time)
        ass_end_time_str = format_ass_time(display_end_time)

        line_text_parts_with_k_tags = []
        accumulated_k_offset_cs = 0  # Time from display_start_time to first word's actual start, in cs

        first_word_start_abs = words[0]['start']
        # Time from when the line *appears* on screen to when the *first word* should start highlighting
        # This is crucial for `\k` tag accumulation if words don't start highlighting immediately
        # when the line appears.
        initial_delay_s = max(0, first_word_start_abs - display_start_time)
        initial_delay_cs = round(initial_delay_s * 100)

        if initial_delay_cs > 0:
            line_text_parts_with_k_tags.append(
                f"{{\\k{initial_delay_cs}}}")  # Initial delay before first word highlights

        for i, word_info in enumerate(words):
            word_text = word_info.get('text', '').strip()
            word_start_time_abs = word_info.get('start')
            word_end_time_abs = word_info.get('end')

            if not word_text or word_start_time_abs is None or word_end_time_abs is None or word_end_time_abs <= word_start_time_abs:
                logger.warning(
                    f"Job {job_id}: Skipping invalid word in ASS (Seg {segment_index}, Word {i}): {word_info}")
                continue

            k_duration_s = max(0.01, word_end_time_abs - word_start_time_abs)
            k_duration_cs = round(k_duration_s * 100)
            k_duration_cs = max(MIN_K_DURATION_CS, min(k_duration_cs, MAX_K_DURATION_CS))

            space_prefix = " " if i > 0 or initial_delay_cs > 0 else ""
            escaped_word_text = escape_ass_text(word_text)

            if i == 0 and initial_delay_cs == 0:  # First word, no initial delay on line
                line_text_parts_with_k_tags.append(f"{{\\k{k_duration_cs}}}{escaped_word_text}")
            elif i > 0:
                # Calculate time gap from PREVIOUS word's END to THIS word's START
                prev_word_end_abs = words[i - 1]['end']
                gap_before_this_word_s = max(0, word_start_time_abs - prev_word_end_abs)
                gap_before_this_word_cs = round(gap_before_this_word_s * 100)

                if gap_before_this_word_cs > 0:
                    # Add a \k tag for the silent gap, then the word with its duration
                    line_text_parts_with_k_tags.append(
                        f"{{\\k{gap_before_this_word_cs}}}{space_prefix}{{\\k{k_duration_cs}}}{escaped_word_text}")
                else:  # No gap or negligible, just add the word
                    line_text_parts_with_k_tags.append(f"{space_prefix}{{\\k{k_duration_cs}}}{escaped_word_text}")
            elif i == 0 and initial_delay_cs > 0:  # First word, but after initial delay on line
                line_text_parts_with_k_tags.append(f"{space_prefix}{{\\k{k_duration_cs}}}{escaped_word_text}")

            word_count_total += 1

        if line_text_parts_with_k_tags:
            full_line_ass_text = "".join(line_text_parts_with_k_tags)
            event_lines.append(
                f"Dialogue: 0,{ass_start_time_str},{ass_end_time_str},Default,,0,0,0,,{full_line_ass_text}")

        last_segment_end_time = seg_end

    try:
        ass_path.parent.mkdir(parents=True, exist_ok=True)
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(header.strip() + "\n\n")
            for line in event_lines:
                f.write(line + "\n")
        logger.info(
            f"Job {job_id}: ASS file generated with {len(event_lines)} event lines ({word_count_total} words). Path: {ass_path}")
        if not event_lines and karaoke_segments:
            logger.warning(f"Job {job_id}: Generated ASS file has no event lines despite input segments.")
    except IOError as e:
        logger.error(f"Job {job_id}: Failed to write ASS file {ass_path}: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Job {job_id}: Unexpected error writing ASS file {ass_path}: {e}", exc_info=True)
        raise RuntimeError("Unexpected error during ASS file writing") from e