# File: backend/lyrics_processing.py
# Handles lyrics fetching, cleaning, and alignment with word-level timings.
# UPDATED (v6): Added more detailed logging for Genius search failures.

import os
import re
import difflib
import logging
import unicodedata
from typing import Optional, List, Dict, Tuple, Any

# Use rapidfuzz if available for potentially faster/better fuzzy matching
try:
    import rapidfuzz.fuzz as fuzz
    import rapidfuzz.process as process
    USE_RAPIDFUZZ = True
    logging.getLogger(__name__).info("Using rapidfuzz for word alignment.")
except ImportError:
    USE_RAPIDFUZZ = False
    logging.getLogger(__name__).warning("rapidfuzz not found. Falling back to difflib for word alignment (might be slower/less accurate).")

# Try importing lyricsgenius and the specific Song class
try:
    import lyricsgenius
    # Import the Song class directly
    from lyricsgenius.song import Song as GeniusSongObject
    HAVE_LYRICSGENIUS = True
except ImportError:
    lyricsgenius = None
    # Define fallback type hint if import fails
    GeniusSongObject = Any # type: ignore
    HAVE_LYRICSGENIUS = False
    logging.getLogger(__name__).warning("`lyricsgenius` library not found. Genius lyrics fetching will be disabled.")
except AttributeError:
    # Handle cases where lyricsgenius might be installed but 'song' module or 'Song' class isn't found
    lyricsgenius = None
    GeniusSongObject = Any # type: ignore
    HAVE_LYRICSGENIUS = False
    logging.getLogger(__name__).error("Could not import 'Song' from 'lyricsgenius.song'. Genius features might be broken.")


from config import settings

logger = logging.getLogger(__name__)

# --- Configuration ---
LYRICS_ALIGNMENT_THRESHOLD = settings.LYRICS_ALIGNMENT_THRESHOLD
# Threshold for considering a whisper word a match for an official word
WORD_MATCH_THRESHOLD = 75 # Increased slightly (0-100 for rapidfuzz/difflib)

NON_LYRIC_KEYWORDS = [
    "transl", "перев", "interpret", "оригин", "subtit", "caption", "sync",
    "chorus", "verse", "bridge", "intro", "outro", "solo", "instrumental",
    "spoken", "ad-lib", "ad lib", "applause", "cheering", "laughing", "repeat", "fades",
    "текст", "песни", "слова",
    # Add common Genius artifacts
    "lyrics", "embed", "contributors", "pyong", "tracklist",
]
# Regex to remove bracketed content, parenthesized content, HTML tags, asterisk blocks, comments, curly braces
CLEANING_PATTERN = r'\[.*?\]|\(.*?\)|<.*?>|\*.*?\*|^\s*#.*$|^\s*\{.*?\}\s*$'
PATTERN_CLEAN = re.compile(CLEANING_PATTERN)
PATTERN_WHITESPACE = re.compile(r'\s+')
# Regex to match lines that consist *only* of punctuation or symbols
PATTERN_ONLY_PUNCT = re.compile(r'^[\W_]+$')
# Regex to clean common junk from titles/artists for Genius search
PATTERN_JUNK_TITLE_ARTIST = re.compile(
    r'\s*\(?'
    r'(official|video|audio|lyric|lyrics|visualizer|live|acoustic|cover|remix|edit|feat|ft\.?|with|explicit|clean|radio|album|version|deluxe|remastered|original|mix|extended|instrumental)'
    r'\)?\s*',
    re.IGNORECASE
)
PATTERN_EXTRA_SPACES = re.compile(r'\s{2,}')
# Regex to split text into words, preserving internal hyphens/apostrophes
PATTERN_SPLIT_WORDS = re.compile(r"([\w'-]+)")


# --- Text Processing Functions ---





# --- Lyrics Fetching ---


# --- Alignment Functions ---
def _find_best_word_match(
        official_word_norm: str,
        whisper_words_with_indices: List[Tuple[str, int]], # List of (normalized_word, original_index)
        used_whisper_indices: set
    ) -> Optional[Tuple[int, float]]: # Return tuple: (best_match_index, best_match_score) or None
    """Finds the best matching *unused* whisper word index for a given official word."""
    best_score = -1.0
    best_idx = -1

    available_whisper = [(w_norm, idx) for w_norm, idx in whisper_words_with_indices if idx not in used_whisper_indices]
    if not available_whisper:
        return None

    if USE_RAPIDFUZZ:
        choices = [w[0] for w in available_whisper]
        # Use WRatio for better handling of different word lengths
        match_result = process.extractOne(official_word_norm, choices, scorer=fuzz.WRatio, score_cutoff=WORD_MATCH_THRESHOLD)
        if match_result:
            best_score = match_result[1]
            choice_index = match_result[2]
            best_idx = available_whisper[choice_index][1] # Get original index
    else: # Fallback to difflib
        matcher = difflib.SequenceMatcher(isjunk=None, autojunk=False)
        matcher.set_seq2(official_word_norm)
        for w_norm, idx in available_whisper:
            matcher.set_seq1(w_norm)
            ratio = matcher.ratio() * 100 # Scale to 0-100
            if ratio >= WORD_MATCH_THRESHOLD and ratio > best_score:
                best_score = ratio
                best_idx = idx

    if best_idx != -1:
        # logger.debug(f"Matched '{official_word_norm}' -> '{whisper_words_with_indices[best_idx][0]}' (Index: {best_idx}, Score: {best_score:.1f})")
        return best_idx, best_score
    else:
        # logger.debug(f"No good match found for '{official_word_norm}' (Threshold: {WORD_MATCH_THRESHOLD})")
        return None

def prepare_segments_for_karaoke(
    recognized_segments: List[Dict],
    official_lyrics: Optional[List[str]] = None
) -> List[Dict]:
    """
    Prepares segments for karaoke subtitle generation with word-level timing alignment.
    Ensures all words in the returned segments have valid 'start' and 'end' times.
    Uses original recognized segments if official lyrics are not provided or alignment fails.
    """
    logger.info(f"Preparing segments for karaoke. Recognized segments: {len(recognized_segments)}. Official lines: {len(official_lyrics) if official_lyrics else 'None'}.")

    # 1. Validate and extract timed words from recognized segments
    valid_recognized_segments_with_words = []
    for i, seg in enumerate(recognized_segments):
        if (isinstance(seg, dict) and 'start' in seg and 'end' in seg and
            isinstance(seg.get('text'), str) and seg['text'].strip() and
            isinstance(seg.get('words'), list)):
            # Extract only words with valid structure and timing
            valid_words_in_seg = []
            for w_idx, w in enumerate(seg['words']):
                if (isinstance(w, dict) and 'start' in w and 'end' in w and
                    isinstance(w.get('text'), str) and w['text'].strip() and
                    isinstance(w['start'], (int, float)) and isinstance(w['end'], (int, float)) and
                    w['end'] >= w['start']):
                    valid_words_in_seg.append({
                        "text": w['text'].strip(),
                        "start": float(w['start']),
                        "end": float(w['end'])
                    })
                # else: logger.debug(f"Skipping invalid word at seg {i}, word {w_idx}: {w}")

            # Check if segment has valid overall timing and at least one valid word
            if (isinstance(seg['start'], (int, float)) and isinstance(seg['end'], (int, float)) and
                seg['end'] >= seg['start'] and valid_words_in_seg):
                # Adjust segment start/end to match the first/last valid word's timing
                seg_start_from_words = valid_words_in_seg[0]['start']
                seg_end_from_words = valid_words_in_seg[-1]['end']
                valid_recognized_segments_with_words.append({
                    "start": seg_start_from_words,
                    "end": seg_end_from_words,
                    "text": seg['text'].strip(), # Keep original segment text for context/matching
                    "words": valid_words_in_seg # Store validated words
                })
            # else: logger.debug(f"Skipping segment {i} due to invalid timing or no valid words.")

    if not valid_recognized_segments_with_words:
        logger.error("prepare_segments_for_karaoke: No valid recognized segments with timed words found after initial validation.")
        return [] # Return empty if no usable input

    # 2. If no official lyrics, return the validated recognized segments directly
    if not official_lyrics:
        logger.info("prepare_segments_for_karaoke: No official lyrics provided. Using validated recognized segments directly.")
        # Ensure sorting by start time
        valid_recognized_segments_with_words.sort(key=lambda x: x.get('start', float('inf')))
        return valid_recognized_segments_with_words

    # 3. Align official lyrics with validated recognized segments
    logger.info(f"Aligning {len(official_lyrics)} official lines to {len(valid_recognized_segments_with_words)} validated recognized segments.")
    aligned_output_segments = []
    used_segment_indices = set()
    line_matcher = difflib.SequenceMatcher(isjunk=None, autojunk=False)
    num_lines_aligned = 0
    total_official_words = 0
    total_words_timed_from_whisper = 0

    # Pre-normalize recognized segments for faster matching
    norm_recognized_data = []
    for idx, seg_data in enumerate(valid_recognized_segments_with_words):
           norm_text = normalize_text(seg_data["text"])
           # Prepare list of (normalized_word, original_word_index_in_segment)
           whisper_words_norm_idx = [(normalize_text(w.get('text', '')), i) for i, w in enumerate(seg_data["words"])]
           whisper_words_norm_idx = [item for item in whisper_words_norm_idx if item[0]] # Filter empty normalized words
           if norm_text and whisper_words_norm_idx: # Ensure segment has text and words to match against
               norm_recognized_data.append({
                   "norm_text": norm_text, # Normalized full text of the recognized segment
                   "original_segment_index": idx, # Index in valid_recognized_segments_with_words
                   "words_timed": seg_data["words"], # Original list of timed words for this segment
                   "words_norm_idx": whisper_words_norm_idx # List of (norm_word, index) for matching
               })

    if not norm_recognized_data:
        logger.warning("No recognized segments had valid normalized text and words after preparation. Cannot perform alignment.")
        return valid_recognized_segments_with_words # Fallback to original recognized segments

    # Iterate through each official lyric line
    for line_index, official_line in enumerate(official_lyrics):
        official_line_cleaned = official_line.strip()
        normalized_official_line = normalize_text(official_line_cleaned)
        if not official_line_cleaned or not normalized_official_line: continue # Skip empty lines

        # Find the best matching unused recognized segment for this official line
        best_match_ratio = -1.0
        best_match_seg_info = None
        line_matcher.set_seq2(normalized_official_line)

        for rec_data in norm_recognized_data:
            if rec_data["original_segment_index"] in used_segment_indices: continue # Skip already used segments
            line_matcher.set_seq1(rec_data["norm_text"])
            ratio = line_matcher.ratio()
            # Check if ratio meets threshold and is better than previous best match
            if ratio >= LYRICS_ALIGNMENT_THRESHOLD and ratio > best_match_ratio:
                best_match_ratio = ratio
                best_match_seg_info = rec_data

        # If a good match was found
        if best_match_seg_info:
            num_lines_aligned += 1
            matched_segment_original_idx = best_match_seg_info["original_segment_index"]
            whisper_words_timed_in_segment = best_match_seg_info["words_timed"]
            whisper_words_norm_idx_in_segment = best_match_seg_info["words_norm_idx"]
            # logger.debug(f"Line {line_index} ('{official_line_cleaned[:30]}...') matched segment {matched_segment_original_idx} with ratio {best_match_ratio:.2f}")

            # Split the official line into words and normalize them
            official_words = split_text_into_words(official_line_cleaned)
            official_words_norm = [normalize_text(w) for w in official_words]
            official_words_pairs = [(word, norm) for word, norm in zip(official_words, official_words_norm) if norm] # Pair original with norm, filter empty

            aligned_line_words_data = [] # To store words of the official line with timings
            used_whisper_word_indices_in_segment = set() # Track used whisper words within this matched segment
            # Estimate start time for potentially untimed words
            current_time = whisper_words_timed_in_segment[0]['start'] if whisper_words_timed_in_segment else 0.0
            total_official_words += len(official_words_pairs)

            # Try to find a timestamp for each word in the official line
            for off_word_text, off_word_norm in official_words_pairs:
                match_result = _find_best_word_match(
                    off_word_norm,
                    whisper_words_norm_idx_in_segment, # Available whisper words (norm, index)
                    used_whisper_word_indices_in_segment # Set of already used whisper word indices
                )
                word_start = -1.0; word_end = -1.0

                if match_result: # Found a timed match in whisper segment
                    best_whisper_match_idx, match_score = match_result
                    matched_whisper_word_data = whisper_words_timed_in_segment[best_whisper_match_idx]
                    word_start = matched_whisper_word_data['start']
                    word_end = matched_whisper_word_data['end']
                    used_whisper_word_indices_in_segment.add(best_whisper_match_idx)
                    current_time = word_end # Update current time based on matched word
                    total_words_timed_from_whisper += 1
                    # logger.debug(f"  Word '{off_word_text}' matched whisper idx {best_whisper_match_idx}, time {word_start:.2f}-{word_end:.2f}")
                else: # No good match found, estimate timing
                    estimated_duration = 0.35 # Default duration estimate
                    gap = 0.05 # Small gap between estimated words
                    word_start = current_time + gap
                    word_end = word_start + estimated_duration
                    current_time = word_end # Update current time based on estimate
                    # logger.debug(f"  Word '{off_word_text}' - timing estimated: {word_start:.2f}-{word_end:.2f}")


                # Add word with timing (either matched or estimated) if valid
                if isinstance(word_start, (int, float)) and isinstance(word_end, (int, float)) and word_end > word_start:
                    aligned_line_words_data.append({"text": off_word_text, "start": word_start, "end": word_end})
                else:
                    # This should ideally not happen with the estimation logic, but log if it does
                    logger.warning(f"Skipping official word '{off_word_text}' in line {line_index} due to invalid timing ({word_start}, {word_end}) after alignment/estimation.")

            # If we got valid timed words for the line, create the output segment
            if aligned_line_words_data:
                seg_start_time = aligned_line_words_data[0]['start']
                seg_end_time = aligned_line_words_data[-1]['end']
                if seg_end_time >= seg_start_time: # Final check on segment times
                    aligned_output_segments.append({
                        "start": seg_start_time,
                        "end": seg_end_time,
                        "text": official_line_cleaned, # Use the original cleaned official line text
                        "words": aligned_line_words_data, # List of official words with timings
                        "aligned": True, # Mark as aligned
                        "confidence": round(best_match_ratio, 3) # Store match confidence
                    })
                    used_segment_indices.add(matched_segment_original_idx) # Mark whisper segment as used
                else:
                    logger.warning(f"Official line '{official_line_cleaned[:50]}...' (line {line_index}) matched segment {matched_segment_original_idx} but resulting word timings were invalid (end < start).")
            else:
                logger.warning(f"No valid words could be timed for official line {line_index}: '{official_line_cleaned[:50]}...' despite matching segment {matched_segment_original_idx}.")
        # else: logger.debug(f"No suitable segment match found for official line {line_index}: '{official_line_cleaned[:30]}...'")


    alignment_percentage = (num_lines_aligned / len(official_lyrics) * 100) if official_lyrics else 0
    word_timing_percentage = (total_words_timed_from_whisper / total_official_words * 100) if total_official_words else 0
    logger.info(f"Alignment complete. Lines matched: {num_lines_aligned}/{len(official_lyrics)} ({alignment_percentage:.1f}%). "
                f"Official Words Timed via Whisper: {total_words_timed_from_whisper}/{total_official_words} ({word_timing_percentage:.1f}%).")

    # Sort final segments by start time
    aligned_output_segments.sort(key=lambda x: x.get('start', float('inf')))

    # Final validation pass on the aligned segments
    final_validated_segments = []
    for seg in aligned_output_segments:
        # Ensure segment has valid words and overall timing
        valid_words = [w for w in seg.get('words', []) if 'start' in w and 'end' in w and w['end'] >= w['start']]
        if valid_words and 'start' in seg and 'end' in seg and seg['end'] >= seg['start']:
            # Optionally readjust segment start/end based on validated words again
            seg['start'] = valid_words[0]['start']
            seg['end'] = valid_words[-1]['end']
            seg['words'] = valid_words
            final_validated_segments.append(seg)
        # else: logger.debug(f"Filtered out aligned segment due to invalid final structure: {seg.get('text', '')[:30]}")


    if not final_validated_segments and official_lyrics:
        logger.warning("Alignment process resulted in zero valid output segments despite having official lyrics. Falling back to original recognized segments.")
        # Ensure fallback is sorted
        valid_recognized_segments_with_words.sort(key=lambda x: x.get('start', float('inf')))
        return valid_recognized_segments_with_words

    logger.info(f"Returning {len(final_validated_segments)} segments prepared for karaoke after alignment.")
    return final_validated_segments


def align_custom_lyrics_with_word_times(
        custom_lyrics_text: str,
        recognized_segments: List[Dict]
) -> List[Dict]:
    """
    Applies word timings from recognized segments sequentially to lines/words from custom text.
    Ensures all output words have start/end times, estimating if necessary.
    """
    logger.info("Applying recognized word timings sequentially to custom lyrics.")
    if not custom_lyrics_text:
        logger.warning("align_custom_lyrics_with_word_times: Empty custom lyrics text.")
        return []

    # 1. Extract and validate all word timings from recognized segments
    all_recognized_word_timings = []
    for i, seg in enumerate(recognized_segments):
        if isinstance(seg, dict) and 'words' in seg and isinstance(seg['words'], list):
            for w_idx, w in enumerate(seg['words']):
                if (isinstance(w, dict) and 'start' in w and 'end' in w and
                    isinstance(w['start'], (int, float)) and isinstance(w['end'], (int, float)) and
                    w['end'] >= w['start']):
                    # Store only start and end time
                    all_recognized_word_timings.append({
                        "start": float(w['start']),
                        "end": float(w['end'])
                    })
                # else: logger.debug(f"Skipping invalid word timing at rec seg {i}, word {w_idx}: {w}")


    if not all_recognized_word_timings:
        logger.error("align_custom_lyrics_with_word_times: No valid word timings found in recognized segments after flattening and validation.")
        return []

    # Sort timings just in case segments weren't perfectly ordered
    all_recognized_word_timings.sort(key=lambda w: w.get('start', float('inf')))
    logger.debug(f"Found {len(all_recognized_word_timings)} valid word timings from recognized segments.")

    # 2. Prepare custom lyrics lines and words
    custom_lines = [line.strip() for line in custom_lyrics_text.splitlines() if line.strip()]
    if not custom_lines:
        logger.warning("align_custom_lyrics_with_word_times: Custom lyrics text had no valid lines after splitting.")
        return []

    # 3. Iterate through custom lines and assign timings sequentially
    result_segments = []
    current_rec_word_index = 0
    total_recognized_words = len(all_recognized_word_timings)
    # Initialize last time carefully based on the first available timing
    last_assigned_end_time = max(0.0, all_recognized_word_timings[0]['start'] - 0.1) if all_recognized_word_timings else 0.0

    for line_index, line_text in enumerate(custom_lines):
        custom_words_in_line = split_text_into_words(line_text)
        if not custom_words_in_line: continue # Skip empty lines

        segment_words_data = [] # To store words for this custom line with timings
        line_start_time = -1.0
        line_end_time = -1.0

        # Assign timing to each word in the custom line
        for word_index, custom_word_text in enumerate(custom_words_in_line):
            word_start = -1.0; word_end = -1.0

            # Try to get timing from the next available recognized word
            if current_rec_word_index < total_recognized_words:
                rec_word_timing = all_recognized_word_timings[current_rec_word_index]
                word_start = rec_word_timing['start']
                word_end = rec_word_timing['end']

                # Sanity check for time ordering
                if word_start < last_assigned_end_time:
                    logger.warning(f"Recognized word timing out of order (Start {word_start:.2f} < Last End {last_assigned_end_time:.2f}) at rec_idx {current_rec_word_index} for custom word '{custom_word_text}'. Adjusting start time.")
                    duration = max(0.05, word_end - word_start) # Keep original duration if possible
                    word_start = last_assigned_end_time + 0.01 # Add tiny gap
                    word_end = word_start + duration

                last_assigned_end_time = word_end # Update last assigned time
                current_rec_word_index += 1
            else: # Ran out of recognized timings, estimate the rest
                estimated_duration = 0.35; gap = 0.05
                word_start = last_assigned_end_time + gap
                word_end = word_start + estimated_duration
                last_assigned_end_time = word_end # Update last assigned time
                if word_index == 0 and line_index == len(custom_lines) -1: # Log only once if estimation starts
                    logger.warning(f"Ran out of recognized word timings ({total_recognized_words} words). Estimating timings for remaining custom words.")


            # Add the custom word with its assigned/estimated timing
            segment_words_data.append({"text": custom_word_text, "start": word_start, "end": word_end})

            # Track line start/end times
            if line_start_time < 0: line_start_time = word_start
            line_end_time = word_end

        # Add the complete line segment if it has words and valid timing
        if segment_words_data and line_start_time >= 0 and line_end_time >= line_start_time:
            result_segments.append({
                'start': line_start_time,
                'end': line_end_time,
                'text': line_text, # The original custom line text
                'words': segment_words_data,
                'aligned': False # Mark as not aligned to original whisper text
                })
        # else: logger.debug(f"Skipping custom line {line_index} due to missing words or invalid time range.")


    logger.info(f"Applied recognized/estimated timings to {len(result_segments)} custom lyric lines using up to {current_rec_word_index} recognized word timings.")
    # Result segments are already ordered by construction
    return result_segments

# File: backend/lyrics_processing.py
# Lyrics fetching, cleaning and timing-alignment utilities.
# File: backend/lyrics_processing.py
# Fetching lyrics from Genius, cleaning and word-timing alignment.

import re
import difflib
import logging
import unicodedata
from typing import Optional, List, Tuple, Any

# ─────────────────────────────────────────────────────────────────────────────
# Optional speed-ups
# ─────────────────────────────────────────────────────────────────────────────
try:
    import rapidfuzz.fuzz as fuzz
    import rapidfuzz.process as process
    USE_RAPIDFUZZ = True
    logging.getLogger(__name__).info("rapidfuzz active")
except ImportError:
    USE_RAPIDFUZZ = False
    logging.getLogger(__name__).warning("rapidfuzz unavailable – using difflib")

# Genius client
try:
    import lyricsgenius
    from lyricsgenius.song import Song as GeniusSongObject
    HAVE_LYRICSGENIUS = True
except (ImportError, AttributeError):
    lyricsgenius = None
    GeniusSongObject = Any       # type: ignore
    HAVE_LYRICSGENIUS = False
    logging.getLogger(__name__).warning("lyricsgenius missing – Genius disabled")

from config import settings

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Regex / constants
# ─────────────────────────────────────────────────────────────────────────────
LYRICS_ALIGNMENT_THRESHOLD = settings.LYRICS_ALIGNMENT_THRESHOLD
WORD_MATCH_THRESHOLD = 75

RX_WS = re.compile(r'\s+')
RX_CLEAN = re.compile(r'\[.*?]|\(.*?]|\{.*?}]|<.*?>|\*.*?\*|^\s*#.*$')
RX_ONLY_PUNCT = re.compile(r'^[\W_]+$')
RX_EXTRA_SPACES = re.compile(r'\s{2,}')
RX_JUNK_TITLE_ARTIST = re.compile(
    r'\s*\('
    r'(official|video|audio|lyric|lyrics|visualizer|live|acoustic|cover|remix|edit|feat|ft\.?|with|explicit|clean|radio|album|version|deluxe|remastered|original|mix|extended|instrumental)'
    r'\)\s*',
    re.I,
)
RX_SPLIT_WORDS = re.compile(r"([\w'-]+)")

# ─────────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────────







# ─────────────────────────────────────────────────────────────────────────────
# Genius fetch  (relaxed filters + raw-query fallback)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_lyrics_from_genius(
    song_title: str, artist: Optional[str] = None
) -> Optional[Tuple[List[str], Optional[GeniusSongObject]]]:
    """Return (cleaned_lines, song_object) or None."""
    if not HAVE_LYRICSGENIUS:
        return None
    token = settings.GENIUS_API_TOKEN
    if not token:
        log.warning("GENIUS_API_TOKEN not set")
        return None

    clean_title = clean_search_term(song_title)
    clean_artist = clean_search_term(artist) if artist else None
    if not clean_title:
        log.warning("Title empty after cleaning – abort Genius search")
        return None

    genius = lyricsgenius.Genius(
        token,
        timeout=15,
        retries=2,
        verbose=False,
        remove_section_headers=True,
        skip_non_songs=False,
        excluded_terms=[],
        response_format='plain',
    )

    song: Optional[GeniusSongObject] = None
    try:
        song = genius.search_song(clean_title, artist=clean_artist) if clean_artist else genius.search_song(clean_title)
    except Exception as exc:
        log.error("Genius cleaned search failed: %s – %s", type(exc).__name__, exc)

    if song is None:
        raw_query = f"{artist or ''} {song_title}".strip()
        log.info("Fallback Genius search '%s'", raw_query)
        try:
            hits = genius.search_songs(raw_query, per_page=1, page=1)
            if hits and hits.get('hits'):
                song = genius.song(hits['hits'][0]['result']['id'])
        except Exception as exc:
            log.error("Genius fallback search failed: %s – %s", type(exc).__name__, exc)

    if song is None:
        log.warning("No Genius result for '%s' / '%s'", song_title, artist)
        return None

    if not getattr(song, 'lyrics', None):
        log.warning("Genius object has no lyrics text")
        return ([], song)

    raw_lines = [ln.strip() for ln in song.lyrics.split('\n')]
    # drop title duplication
    if raw_lines and normalize_text(raw_lines[0]) == normalize_text(clean_title):
        raw_lines = raw_lines[1:]

    junk_rx = [
        re.compile(r'^\d+\s*contributors?$', re.I),
        re.compile(r'^\s*lyrics for .* by .*$', re.I),
        re.compile(r'you might also like', re.I),
        re.compile(r'^\s*get tickets? to see', re.I),
        re.compile(r'^(source:|see .* live!)', re.I),
        re.compile(r'\d*embed\s*$', re.I),
        re.compile(r'\d+[kK]?\s*Embed$', re.I),
        re.compile(r'pyong\b', re.I),
    ]

    cleaned: List[str] = []
    for ln in raw_lines:
        cl = clean_lyric_line(ln)
        if not cl:
            continue
        if RX_ONLY_PUNCT.match(cl):
            continue
        if any(r.search(ln) for r in junk_rx) or any(r.search(cl) for r in junk_rx):
            continue
        cleaned.append(cl)

    if not cleaned:
        log.info("Cleaning removed everything – keeping raw lines (%d)", len(raw_lines))
        cleaned = [ln for ln in raw_lines if ln]

    return (cleaned, song)

# ─────────────────────────────────────────────────────────────────────────────
# Alignment helpers (unchanged – same logic as ранее)
# ─────────────────────────────────────────────────────────────────────────────
# … полный код остальных функций оставьте без изменений …

# File: backend/lyrics_processing.py
# Genius search → clean text  •  alignment helpers (осталось без изменений ниже).

import re, difflib, logging, unicodedata
from typing import Optional, List, Tuple, Any

# ─────────────────────────────────────────────────────────────────────────────
# Optional speed-ups
# ─────────────────────────────────────────────────────────────────────────────
try:
    import rapidfuzz.fuzz as fuzz
    import rapidfuzz.process as process
    USE_RAPIDFUZZ = True
    logging.getLogger(__name__).info("rapidfuzz active")
except ImportError:
    USE_RAPIDFUZZ = False
    logging.getLogger(__name__).warning("rapidfuzz not found – using difflib")

# Genius
try:
    import lyricsgenius
    from lyricsgenius.song import Song as GeniusSongObject
    HAVE_LYRICSGENIUS = True
except (ImportError, AttributeError):
    lyricsgenius = None
    GeniusSongObject = Any      # type: ignore
    HAVE_LYRICSGENIUS = False
    logging.getLogger(__name__).warning("lyricsgenius missing – Genius disabled")

from config import settings
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Regex helpers / constants
# ─────────────────────────────────────────────────────────────────────────────
LYRICS_ALIGNMENT_THRESHOLD = settings.LYRICS_ALIGNMENT_THRESHOLD
WORD_MATCH_THRESHOLD = 75

RX_WS            = re.compile(r'\s+')
RX_CLEAN         = re.compile(r'\[.*?]|\(.*?]|\{.*?}]|<.*?>|\*.*?\*|^\s*#.*$')
RX_ONLY_PUNCT    = re.compile(r'^[\W_]+$')
RX_EXTRA_SPACES  = re.compile(r'\s{2,}')
RX_JUNK_TA       = re.compile(
    r'\s*\('
    r'(official|video|audio|lyric|lyrics|visualizer|live|acoustic|cover|remix|edit|feat|ft\.?|with|explicit|clean|radio|album|version|deluxe|remastered|original|mix|extended|instrumental)'
    r'\)\s*',
    re.I,
)
RX_SPLIT_WORDS   = re.compile(r"([\w'-]+)")

def normalize_text(t: str) -> str:
    t = unicodedata.normalize('NFKC', t).lower()
    t = re.sub(r"[^\w\s'-]+", '', t)
    return RX_WS.sub(' ', t).strip()

def clean_lyric_line(l: str) -> str:
    return RX_WS.sub(' ', RX_CLEAN.sub('', l)).strip() if l else ''

def split_words(t: str) -> List[str]:
    return [w for w in RX_SPLIT_WORDS.findall(t) if w]

def clean_search_term(term: str) -> str:
    if not term: return ''
    term = RX_JUNK_TA.sub(' ', term)
    term = RX_CLEAN.sub('', term)
    return RX_EXTRA_SPACES.sub(' ', term).strip(" .,!?;:\"")

# ─────────────────────────────────────────────────────────────────────────────
# Genius helpers
# ─────────────────────────────────────────────────────────────────────────────
def _iter_hits(genius, title: str, artist: Optional[str]) -> List['lyricsgenius.song.Song']:
    """Return up to 5 Song objects for further filtering."""
    # 1) cleaned query
    hits: List[GeniusSongObject] = []
    try:
        song = genius.search_song(title, artist=artist) if artist else genius.search_song(title)
        if song: hits.append(song)
    except Exception as exc:
        log.debug("cleaned search error: %s", exc)

    # 2) raw query
    raw_q = f"{artist or ''} {title}".strip()
    try:
        res = genius.search_songs(raw_q, per_page=5, page=1)
        for h in (res.get('hits') if res else [])[:5]:
            sid = h['result']['id']
            try:
                s = genius.song(sid)
                if s: hits.append(s)
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:
        log.debug("raw search error: %s", exc)

    # deduplicate by id
    seen = set()
    uniq: List[GeniusSongObject] = []
    for s in hits:
        sid = getattr(s, 'id', None)
        if sid and sid not in seen:
            uniq.append(s)
            seen.add(sid)
    return uniq[:5]

def _clean_lines(raw_lines: List[str], cleaned_title: str) -> List[str]:
    if raw_lines and normalize_text(raw_lines[0]) == normalize_text(cleaned_title):
        raw_lines = raw_lines[1:]

    junk_rx = [
        re.compile(r'^\d+\s*contributors?$', re.I),
        re.compile(r'^\s*lyrics for .* by .*$', re.I),
        re.compile(r'you might also like', re.I),
        re.compile(r'^\s*get tickets? to see', re.I),
        re.compile(r'^(source:|see .* live!)', re.I),
        re.compile(r'\d*embed\s*$', re.I),
        re.compile(r'\d+[kK]?\s*Embed$', re.I),
        re.compile(r'pyong\b', re.I),
    ]

    cleaned: List[str] = []
    for ln in raw_lines:
        cl = clean_lyric_line(ln)
        if not cl or RX_ONLY_PUNCT.match(cl):
            continue
        if any(r.search(ln) for r in junk_rx) or any(r.search(cl) for r in junk_rx):
            continue
        cleaned.append(cl)
    return cleaned

def fetch_genius_candidates(title: str, artist: Optional[str] = None, max_candidates: int = 3
) -> List[Tuple[List[str], GeniusSongObject]]:
    """Return up to `max_candidates` tuples (clean_lines, song_obj)."""
    if not HAVE_LYRICSGENIUS or not settings.GENIUS_API_TOKEN:
        log.warning("Genius disabled or token missing")
        return []

    genius = lyricsgenius.Genius(
        settings.GENIUS_API_TOKEN,
        timeout=15,
        retries=2,
        verbose=False,
        remove_section_headers=True,
        skip_non_songs=False,
        excluded_terms=[],
        response_format='plain',
    )

    cleaned_title = clean_search_term(title)
    cleaned_artist = clean_search_term(artist) if artist else None

    candidates: List[Tuple[List[str], GeniusSongObject]] = []
    for song in _iter_hits(genius, cleaned_title, cleaned_artist):
        if not getattr(song, 'lyrics', None):
            continue
        lines = _clean_lines([ln.strip() for ln in song.lyrics.split('\n')], cleaned_title)
        # keep even empty lines – фронтенд покажет, но не выберет автоматически
        candidates.append((lines, song))
        if len(candidates) >= max_candidates:
            break

    return candidates
