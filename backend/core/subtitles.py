# File: backend/core/subtitles.py
# Generates karaoke-style ASS subtitles with word highlighting.
# UPDATED: Increased lead time and persistence, allow overlap for karaoke feel, clamped K duration.
# UPDATED (v2): Accepts final_font_size parameter and uses it in the ASS header.
# UPDATED (v3): Use raw string for docstring to fix SyntaxWarning.

import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# --- Constants ---
# *** FIX: Increased lead time and persistence, slightly increased minimum duration ***
SUBTITLE_LEAD_TIME_SECONDS = 0.40 # How early the line should appear before the first word
SUBTITLE_PERSIST_SECONDS = 0.75 # How long the line stays after the last word
MIN_LINE_DURATION_SECONDS = 1.2 # Minimum display duration for a line
# *** FIX: Clamp K duration to prevent super fast/slow highlights (in centiseconds) ***
MIN_K_DURATION_CS = 5   # Minimum duration (5cs = 0.05s)
MAX_K_DURATION_CS = 500 # Maximum duration (500cs = 5.0s)

# ASS Header Template (adjust PlayRes if desired, e.g., 1920x1080)
# *** FIX: Uses passed font_size for both Default and Highlight styles ***
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

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# --- Helper Functions ---

def format_ass_time(seconds: float) -> str:
    """Converts seconds to ASS time format H:MM:SS.cc."""
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
    """Escapes characters special to ASS format (curly braces and commas within text)."""
    if not isinstance(text, str): return "" # Handle non-string input
    text = text.replace('{', r'\{')
    text = text.replace('}', r'\}')
    # Escape commas too if they appear in actual lyric text (rare but possible)
    # text = text.replace(',', r'\,') # Usually not needed unless comma is part of the lyrics
    return text

# --- Main ASS Generation Function ---

# *** FIX: Added font_size parameter ***
async def generate_ass_karaoke(
    job_id: str,
    karaoke_segments: List[Dict],
    video_id: str,
    processed_dir: Path,
    # --- Styling parameters ---
    font_name: str = 'Poppins Bold', # Consider a common bold font
    font_size: int = 30, # *** Default size, will be overridden by API call ***
    position: str = 'bottom',
    primary_color: str = 'FFFFFF', # White (inactive)
    secondary_color: str = '00F0FF', # Cyan (active)
    outline_color: str = '000000', # Black
    back_color: str = '000000',    # Black (shadow)
    primary_alpha: str = '00',     # Fully opaque
    secondary_alpha: str = '00',   # Fully opaque
    outline_alpha: str = '00',     # Outline opacity (00=opaque, FF=transparent)
    back_alpha: str = '80'         # Shadow opacity (semi-transparent)

) -> Optional[Path]:
    # *** FIX: Use raw string r"""...""" here to avoid SyntaxWarning ***
    r"""
    Generates an ASS subtitle file with karaoke highlighting (using {\k} tags).
    Incorporates lead time and persistence for better karaoke experience, allowing overlap.
    Uses the provided font_size.
    """
    # *** FIX: Use the passed font_size parameter ***
    # Validation ensures font_size is one of the allowed integers (e.g., 24, 30, 36, 42)
    final_font_size = font_size if isinstance(font_size, int) and font_size >= 10 else 30 # Fallback size if validation somehow failed upstream

    ass_path = processed_dir / f"{video_id}.ass"
    logger.info(f"Job {job_id}: Generating ASS karaoke file: '{ass_path.name}' Font: {font_name} {final_font_size}px, Pos: {position}, Lead: {SUBTITLE_LEAD_TIME_SECONDS}s, Persist: {SUBTITLE_PERSIST_SECONDS}s")

    if not karaoke_segments:
        logger.warning(f"Job {job_id}: No segments provided for ASS generation. Skipping.")
        return None

    # Validate segments have words with timing required for {\k} tags
    # This validation should happen *before* calling this function (in processing.py or lyrics_processing.py)
    # Assuming input segments are already validated here for simplicity, but double-checking is safer.
    valid_segments = []
    for i, seg in enumerate(karaoke_segments):
        # Check segment structure and word structure (stricter validation)
        if (isinstance(seg, dict) and 'start' in seg and 'end' in seg and
            isinstance(seg.get('start'), (int, float)) and isinstance(seg.get('end'), (int, float)) and seg['end'] >= seg['start'] and # Valid timing
            isinstance(seg.get('text'), str) and seg['text'].strip() and # Valid text
            isinstance(seg.get('words'), list) and seg['words'] and # Must have a non-empty list of words
            all(isinstance(w, dict) and 'text' in w and 'start' in w and 'end' in w and # Check word dict structure
                isinstance(w.get('text'), str) and w['text'].strip() and # Word text must be valid
                isinstance(w.get('start'), (int, float)) and isinstance(w.get('end'), (int, float)) and # Word timing types
                w['end'] >= w['start'] # Ensure end >= start for word
                for w in seg['words'])):
            valid_segments.append(seg)
        else:
            logger.warning(f"Job {job_id}: Skipping segment {i} due to missing/invalid structure or timed words: {str(seg)[:100]}...") # Log beginning of segment data

    if not valid_segments:
            logger.error(f"Job {job_id}: No valid segments with timed words available after final check. Cannot generate ASS.")
            return None

    try:
        await asyncio.to_thread(
            _generate_ass_file_sync,
            valid_segments, # Use only valid segments
            ass_path, job_id,
            font_name, final_font_size, position, # *** FIX: Pass the final font size ***
            primary_color, secondary_color, outline_color, back_color,
            primary_alpha, secondary_alpha, outline_alpha, back_alpha
        )
        # Verification
        if not ass_path.exists():
            logger.error(f"Job {job_id}: ASS generation finished but file not found: {ass_path}")
            raise IOError("ASS generation failed, file not created.")
        elif ass_path.stat().st_size < 100: # Check if file is too small (likely just header)
            logger.warning(f"Job {job_id}: Generated ASS file is very small (<100 bytes). Check content: {ass_path}")

        return ass_path

    except Exception as e:
        logger.error(f"ASS generation failed for job {job_id}: {e}", exc_info=True)
        # Attempt to clean up partial file on error
        try: ass_path.unlink(missing_ok=True)
        except OSError: pass
        raise IOError(f"ASS generation failed: {e}") from e

def _generate_ass_file_sync(
    karaoke_segments: List[Dict],
    ass_path: Path,
    job_id: str,
    # --- Styling ---
    font_name: str, font_size: int, position: str, # *** FIX: font_size parameter ***
    pri_color: str, sec_color: str, out_color: str, back_color: str,
    pri_alpha: str, sec_alpha: str, out_alpha: str, back_alpha: str
):
    """Synchronous function to generate the ASS file with lead time, persistence, and overlap."""

    # --- Prepare Styling ---
    # Position: 2=bottom center, 8=top center, 5=middle center
    alignment = 8 if position == "top" else 2
    # MarginV: Vertical margin from edge (adjust based on final_font_size for better placement)
    margin_v = max(20, int(font_size * 1.1)) if position == "bottom" else max(25, int(font_size * 1.3))
    outline_thickness = max(1.0, font_size / 16.0) # Scale outline with font size
    shadow_depth = max(0.8, font_size / 22.0)      # Scale shadow with font size
    border_style = 1 # 1=Outline+Shadow, 3=Opaque box
    bold_flag = -1   # -1=Bold, 0=Regular

    # Function to convert RRGGBB hex to ASS BBGGRR format
    def format_ass_color(hex_color):
        # Ensure valid hex color input
        if not isinstance(hex_color, str) or len(hex_color) != 6:
            logger.warning(f"Invalid hex color '{hex_color}', using default white.")
            return 'FFFFFF' # Default to white on error
        try:
            int(hex_color, 16) # Check if valid hex
            return hex_color[4:6] + hex_color[2:4] + hex_color[0:2]
        except ValueError:
            logger.warning(f"Invalid hex color value '{hex_color}', using default white.")
            return 'FFFFFF'

    # *** FIX: Use the passed font_size in the header format ***
    header = ASS_HEADER_TEMPLATE.format(
        font_name=escape_ass_text(font_name), # Escape font name just in case
        font_size=font_size, # *** Use the passed font size ***
        color_pri=format_ass_color(pri_color),
        color_sec=format_ass_color(sec_color),
        color_out=format_ass_color(out_color),
        color_back=format_ass_color(back_color),
        alpha_pri=pri_alpha, alpha_sec=sec_alpha, alpha_out=out_alpha, alpha_back=back_alpha,
        bold=bold_flag, border_style=border_style, outline=outline_thickness, # Pass float for formatting
        shadow=shadow_depth, alignment=alignment, margin_v=margin_v # Pass float for formatting
    )

    # --- Generate Event Lines ---
    event_lines = []
    word_count_total = 0
    # Overlap is allowed, no need to track last_event_end_time strictly for non-overlap

    for segment_index, segment in enumerate(karaoke_segments):
        # Use validated start/end times from the segment itself
        seg_start = segment.get('start')
        seg_end = segment.get('end')
        words = segment.get('words', []) # Already validated to have start/end/text

        # Skip segments without valid overall timing or words (should not happen after validation)
        if seg_start is None or seg_end is None or seg_end <= seg_start or not words:
            logger.debug(f"Job {job_id}: Skipping segment index {segment_index} due to missing timing/words: Start={seg_start}, End={seg_end}")
            continue

        # Calculate display start time with lead-in
        display_start_time = max(0.0, seg_start - SUBTITLE_LEAD_TIME_SECONDS)

        # Calculate display end time with persistence, ensuring minimum duration
        display_end_time = max(seg_end + SUBTITLE_PERSIST_SECONDS, display_start_time + MIN_LINE_DURATION_SECONDS)

        # Format times for ASS
        ass_start_time = format_ass_time(display_start_time)
        ass_end_time = format_ass_time(display_end_time)

        line_text_parts = []
        # last_word_end_time_in_segment = seg_start # Not needed currently

        for i, word_info in enumerate(words):
            word_text = word_info.get('text', '').strip()
            word_start = word_info.get('start')
            word_end = word_info.get('end')

            # Should be valid from pre-filtering, but double check
            if not word_text or word_start is None or word_end is None or word_end < word_start:
                logger.warning(f"Job {job_id}: Skipping invalid word in ASS generation (Segment {segment_index}, Word {i}): {word_info}")
                continue

            # Calculate karaoke duration (\k tag value in centiseconds)
            k_duration_s = max(0.01, word_end - word_start) # Duration of the word itself
            k_duration_cs = round(k_duration_s * 100)

            # *** FIX: Clamp the duration to prevent extreme values ***
            k_duration_cs = max(MIN_K_DURATION_CS, min(k_duration_cs, MAX_K_DURATION_CS))

            space_prefix = " " if i > 0 else "" # Add space before word if not the first
            escaped_word = escape_ass_text(word_text)
            # Build the karaoke tag and word part
            line_text_parts.append(f"{{\\k{k_duration_cs}}}{space_prefix}{escaped_word}")
            word_count_total += 1
            # last_word_end_time_in_segment = word_end # Not needed

        if line_text_parts:
            full_line_text = "".join(line_text_parts)
            # Use Layer 0 for standard subtitles, Default style
            # ASS Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
            event_line = f"Dialogue: 0,{ass_start_time},{ass_end_time},Default,,0,0,0,,{full_line_text}"
            event_lines.append(event_line)
            # Overlap is allowed, no need to track last_event_end_time

    # --- Write to File ---
    try:
        # Ensure parent directory exists
        ass_path.parent.mkdir(parents=True, exist_ok=True)
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(header.strip() + "\n\n") # Write header
            for line in event_lines:
                f.write(line + "\n") # Write each event line

        logger.info(f"Job {job_id}: ASS file generated with {len(event_lines)} lines ({word_count_total} words processed for karaoke tags).")
        if not event_lines and karaoke_segments:
            logger.warning(f"Job {job_id}: Generated ASS file has no event lines despite input segments.")

    except IOError as e:
        logger.error(f"Job {job_id}: Failed to write ASS file {ass_path}: {e}", exc_info=True)
        raise # Re-raise the IOError
    except Exception as e:
        logger.error(f"Job {job_id}: Unexpected error generating ASS file {ass_path}: {e}", exc_info=True)
        raise RuntimeError("Unexpected error during ASS generation") from e