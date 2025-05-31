# File: backend/core/subtitles.py
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# --- Timing Constants for Subtitle Generation ---
SUBTITLE_LEAD_TIME_SECONDS = 0.40  # How early a regular subtitle line appears before its audio
SUBTITLE_PERSIST_SECONDS = 0.75  # How long a regular subtitle line stays after its audio ends
MIN_LINE_DURATION_SECONDS = 1.2  # Minimum display duration for any subtitle line

# Constants for karaoke effect (k tags)
MIN_K_DURATION_CS = 8  # Minimum duration for a \k tag in centiseconds (0.08s)
MAX_K_DURATION_CS = 300 # Maximum duration for a \k tag in centiseconds (3.0s)

# Constants for "Next Up" and "Countdown" cues
GAP_THRESHOLD_FOR_CUES = 5.0  # Min seconds of silence to trigger advance cues
COUNTDOWN_TOTAL_DURATION = 3.0 # Total duration of "3, 2, 1" countdown
LYRIC_PREP_LEAD_TIME = 1.5     # How early the "Next Up" lyric line appears *before* countdown starts
COUNTDOWN_STEP_DURATION = 1.0  # Duration for each countdown number (e.g., "3" shows for 1s)

ASS_HEADER_TEMPLATE = """
[Script Info]
Title: Karaoke Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None
PlayResX: 1280
PlayResY: 720
Collisions: Normal

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H{alpha_pri}{color_pri},&H{alpha_sec}{color_sec},&H{alpha_out}{color_out},&H{alpha_back}{color_back},{bold},0,0,0,100,100,0.2,0,{border_style},{outline:.2f},{shadow:.2f},{alignment},20,20,{margin_v},1
Style: Highlight,{font_name},{font_size},&H{alpha_sec}{color_sec},&H{alpha_pri}{color_pri},&H{alpha_out}{color_out},&H{alpha_back}{color_back},{bold},0,0,0,100,100,0.2,0,{border_style},{outline:.2f},{shadow:.2f},{alignment},20,20,{margin_v},1
Style: Countdown,{font_name},{countdown_font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,5,20,20,30,1
Style: NextUp,{font_name},{next_up_font_size},&HAA{color_pri},&HAA{color_sec},&H88{color_out},&H99{color_back},0,0,0,0,100,100,0.1,0,{border_style},{outline_next_up:.2f},{shadow_next_up:.2f},8,20,20,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def format_ass_time(seconds: float) -> str:
    """Formats time in seconds to ASS H:MM:SS.cc format."""
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
    """Escapes characters that have special meaning in ASS event lines."""
    if not isinstance(text, str): return ""
    # Primary issue is with inline style overrides using {}
    text = text.replace('{', r'\{')
    text = text.replace('}', r'\}')
    # Commas in text can break Dialogue line parsing if not handled by player,
    # but generally, players are robust. Sticking to {} escaping primarily.
    # text = text.replace(',', r'\;') # Example if comma escaping needed, less common.
    return text


async def generate_ass_karaoke(
        job_id: str,
        karaoke_segments: List[Dict], # These segments should have word-level timings
        video_id: str,
        processed_dir: Path,
        font_name: str = 'Poppins Bold', # Default font
        font_size: int = 30, # Default font size for main lyrics
        position: str = 'bottom', # Default position for main lyrics
        primary_color: str = 'FFFFFF', # White
        secondary_color: str = '00F0FF', # Cyan for highlight
        outline_color: str = '000000', # Black
        back_color: str = '000000', # Black for shadow/backing box
        primary_alpha: str = '00', # Fully opaque
        secondary_alpha: str = '00', # Fully opaque
        outline_alpha: str = '00', # Fully opaque for outline
        back_alpha: str = '80' # Semi-transparent for backing box/shadow
) -> Optional[Path]:
    r"""
    Generates an Advanced SubStation Alpha (ASS) subtitle file with karaoke highlighting.
    Includes countdowns and advance lyric display ("Next Up") for long instrumental breaks.

    Karaoke effect is achieved using {\k<duration_cs>} tags for word-by-word highlighting.
    """
    final_font_size = font_size if isinstance(font_size, int) and font_size >= 10 else 30
    ass_path = processed_dir / f"{video_id}.ass"
    logger.info(
        f"Job {job_id}: Generating ASS karaoke file: '{ass_path.name}' Font: {font_name} {final_font_size}px, Pos: {position}")

    if not karaoke_segments:
        logger.warning(f"Job {job_id}: No segments provided for ASS generation. Skipping.")
        return None

    # Validate segments structure (text, start, end, and words with their timings)
    valid_segments = []
    for i, seg in enumerate(karaoke_segments):
        if (isinstance(seg, dict) and 'start' in seg and 'end' in seg and
                isinstance(seg.get('start'), (int, float)) and isinstance(seg.get('end'), (int, float)) and seg['end'] >= seg['start'] and
                isinstance(seg.get('text'), str) and seg['text'].strip() and # Segment must have text
                isinstance(seg.get('words'), list) and seg['words'] and # Segment must have a list of words
                all(isinstance(w, dict) and 'text' in w and 'start' in w and 'end' in w and
                    isinstance(w.get('text'), str) and w['text'].strip() and # Each word must have text
                    isinstance(w.get('start'), (int, float)) and isinstance(w.get('end'), (int, float)) and
                    w['end'] >= w['start'] # Each word must have valid timing
                    for w in seg['words'])):
            valid_segments.append(seg)
        else:
            logger.warning(
                f"Job {job_id}: Skipping segment {i} due to missing/invalid structure or word timings: {str(seg)[:100]}...")

    if not valid_segments:
        logger.error(
            f"Job {job_id}: No valid segments with timed words available after final check. Cannot generate ASS.")
        return None

    try:
        # Run the synchronous file generation in a separate thread
        await asyncio.to_thread(
            _generate_ass_file_sync,
            valid_segments, # Pass only validated segments
            ass_path, job_id,
            font_name, final_font_size, position,
            primary_color, secondary_color, outline_color, back_color,
            primary_alpha, secondary_alpha, outline_alpha, back_alpha
        )
        if not ass_path.exists():
            logger.error(f"Job {job_id}: ASS generation finished but file not found: {ass_path}")
            raise IOError("ASS generation failed, file not created.")
        elif ass_path.stat().st_size < 100: # Basic check for empty or near-empty file
            logger.warning(f"Job {job_id}: Generated ASS file is very small (<100 bytes). Check content: {ass_path}")
        return ass_path
    except Exception as e:
        logger.error(f"ASS generation failed for job {job_id}: {e}", exc_info=True)
        # Attempt to clean up partially created file
        try:
            ass_path.unlink(missing_ok=True)
        except OSError:
            pass # Ignore if deletion fails
        raise IOError(f"ASS generation failed: {e}") from e


def _generate_ass_file_sync(
        karaoke_segments: List[Dict], # Assumed to be validated and sorted by start time
        ass_path: Path,
        job_id: str, # For logging
        font_name: str, font_size: int, position: str,
        pri_color: str, sec_color: str, out_color: str, back_color: str,
        pri_alpha: str, sec_alpha: str, out_alpha: str, back_alpha: str
):
    """Synchronous function to write the ASS file content."""

    # --- Style Definitions ---
    alignment = 8 if position == "top" else 2 # 8=TopCenter, 2=BottomCenter for ASS numpad alignment
    margin_v = max(20, int(font_size * 1.1)) if position == "bottom" else max(25, int(font_size * 1.3))
    outline_thickness = max(1.0, font_size / 16.0) # Scale outline with font size
    shadow_depth = max(0.8, font_size / 22.0) # Scale shadow with font size
    border_style = 1 # Outline + opaque box (shadow)
    bold_flag = -1 # Enable bold

    countdown_font_size = int(font_size * 1.5)  # Larger for countdown
    next_up_font_size = int(font_size * 0.8)  # Smaller for "Next Up" cue
    outline_next_up = max(0.8, next_up_font_size / 18.0)
    shadow_next_up = max(0.5, next_up_font_size / 25.0)

    # Helper to format color strings from RRGGBB (hex) to BBGGRR (ASS)
    def format_ass_color_val(hex_color_str: str) -> str:
        if not isinstance(hex_color_str, str) or len(hex_color_str) != 6: return 'FFFFFF' # Default white
        try:
            int(hex_color_str, 16) # Validate it's hex
            return hex_color_str[4:6] + hex_color_str[2:4] + hex_color_str[0:2] # BBGGRR
        except ValueError:
            return 'FFFFFF'

    # Populate the ASS header template with style values
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
    last_segment_end_time = 0.0 # Tracks the end time of the previously processed main lyric segment

    # --- Generate Event Lines ---
    for segment_index, segment in enumerate(karaoke_segments):
        seg_start = segment.get('start')
        seg_end = segment.get('end')
        words = segment.get('words', []) # This is a list of timed words for this segment
        segment_text_full_line = segment.get('text', " ")  # Full line text for NextUp preview

        # These should be guaranteed by prior validation, but double check
        if seg_start is None or seg_end is None or seg_end <= seg_start or not words:
            logger.debug(f"Job {job_id}: Skipping segment index {segment_index} in ASS gen (final check).")
            continue

        # --- Advance Cues (Next Up & Countdown) for Gaps ---
        gap_before_segment = seg_start - last_segment_end_time
        if gap_before_segment >= GAP_THRESHOLD_FOR_CUES:
            # Calculate start time for the "Next Up" lyric preview
            # It should appear LYRIC_PREP_LEAD_TIME before the countdown starts
            next_up_start_time = max(last_segment_end_time + 0.1, seg_start - COUNTDOWN_TOTAL_DURATION - LYRIC_PREP_LEAD_TIME)
            # "Next Up" line ends when countdown begins
            next_up_end_time = max(next_up_start_time + 0.5, seg_start - COUNTDOWN_TOTAL_DURATION - 0.1) # Show for a bit or until countdown

            if next_up_end_time > next_up_start_time:
                # Truncate "Next Up" text if too long
                preview_text_raw = segment_text_full_line
                next_up_text_preview = escape_ass_text(
                    preview_text_raw[:80] + ('...' if len(preview_text_raw) > 80 else '')
                )
                event_lines.append(
                    f"Dialogue: 1,{format_ass_time(next_up_start_time)},{format_ass_time(next_up_end_time)},NextUp,,0,0,0,,{next_up_text_preview}")

            # Add Countdown events ("3", "2", "1")
            for i in range(int(COUNTDOWN_TOTAL_DURATION / COUNTDOWN_STEP_DURATION), 0, -1):
                countdown_val = i # The number to display (3, 2, or 1)
                # Start time for this countdown number
                countdown_start_time = max(next_up_end_time, seg_start - (countdown_val * COUNTDOWN_STEP_DURATION))
                # End time for this countdown number
                countdown_end_time = seg_start - ((countdown_val - 1) * COUNTDOWN_STEP_DURATION) - 0.05 # Small gap before next number or lyric

                if countdown_end_time > countdown_start_time:
                    event_lines.append(
                        f"Dialogue: 2,{format_ass_time(countdown_start_time)},{format_ass_time(countdown_end_time)},Countdown,,0,0,0,,{countdown_val}")

        # --- Main Lyric Line Event ---
        # Adjust display start/end times for the main lyric line
        display_start_time = max(0.0, seg_start - SUBTITLE_LEAD_TIME_SECONDS)
        display_end_time = max(seg_end + SUBTITLE_PERSIST_SECONDS, display_start_time + MIN_LINE_DURATION_SECONDS)
        ass_start_time_str = format_ass_time(display_start_time)
        ass_end_time_str = format_ass_time(display_end_time)

        line_text_parts_with_k_tags = []
        for i, word_info in enumerate(words):
            word_text = word_info.get('text', '').strip()
            word_start_time = word_info.get('start') # Relative to segment start, or absolute? ASSUME ABSOLUTE.
            word_end_time = word_info.get('end')

            # Word timings should be valid from previous steps
            if not word_text or word_start_time is None or word_end_time is None or word_end_time < word_start_time:
                logger.warning(
                    f"Job {job_id}: Skipping invalid word in ASS (Seg {segment_index}, Word {i}): {word_info}")
                continue

            # Calculate karaoke tag duration in centiseconds
            # The \k tag duration is relative to the *start of the word's appearance* within the line.
            # For ASS, the word itself doesn't have a start/end time in the event, the line does.
            # The {\k<duration_cs>} makes the word highlighted for that duration.
            k_duration_s = max(0.01, word_end_time - word_start_time)
            k_duration_cs = round(k_duration_s * 100)
            # Clamp duration to avoid issues with extremely short/long words in some players
            k_duration_cs = max(MIN_K_DURATION_CS, min(k_duration_cs, MAX_K_DURATION_CS))

            space_prefix = " " if i > 0 and line_text_parts_with_k_tags else "" # Add space before non-first words
            escaped_word_text = escape_ass_text(word_text)
            line_text_parts_with_k_tags.append(f"{{\\k{k_duration_cs}}}{space_prefix}{escaped_word_text}")
            word_count_total += 1

        if line_text_parts_with_k_tags:
            full_line_ass_text = "".join(line_text_parts_with_k_tags)
            # Layer 0 is default for lyrics. Name field is not typically used.
            # Margins L, R, V are already defined in Style. Effect field is empty.
            event_lines.append(f"Dialogue: 0,{ass_start_time_str},{ass_end_time_str},Default,,0,0,0,,{full_line_ass_text}")

        last_segment_end_time = seg_end  # Update for calculating next gap

    # --- Write to File ---
    try:
        ass_path.parent.mkdir(parents=True, exist_ok=True) # Ensure directory exists
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(header.strip() + "\n\n") # Write header and V4+ Styles
            for line in event_lines:
                f.write(line + "\n")
        logger.info(
            f"Job {job_id}: ASS file generated with {len(event_lines)} event lines ({word_count_total} words processed). Path: {ass_path}")
        if not event_lines and karaoke_segments: # Input had segments, but output has no events
            logger.warning(f"Job {job_id}: Generated ASS file has no event lines despite input segments. This might indicate all words were invalid or processing failed.")
    except IOError as e:
        logger.error(f"Job {job_id}: Failed to write ASS file {ass_path}: {e}", exc_info=True)
        raise # Re-throw to be caught by the async wrapper
    except Exception as e:
        logger.error(f"Job {job_id}: Unexpected error writing ASS file {ass_path}: {e}", exc_info=True)
        raise RuntimeError("Unexpected error during ASS file writing") from e