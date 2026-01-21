# File: backend/lyrics_processing.py
# Handles lyrics fetching, cleaning, and alignment with word-level timings.
import os
import re
import difflib
import logging
import unicodedata
from typing import Optional, List, Dict, Tuple, Any

# Use rapidfuzz if available for potentially faster/better fuzzy matching
try:
    import rapidfuzz.fuzz as fuzz
    import rapidfuzz.process as process  # For extractOne

    USE_RAPIDFUZZ = True
    logging.getLogger(__name__).info("Using rapidfuzz for word alignment.")
except ImportError:
    USE_RAPIDFUZZ = False
    logging.getLogger(__name__).warning(
        "rapidfuzz not found. Falling back to difflib for word alignment (might be slower/less accurate).")

# Try importing lyricsgenius and the specific Song class
try:
    import lyricsgenius
    # Import the Song class - location changed in newer versions
    try:
        from lyricsgenius.types import Song as GeniusSongObject
    except ImportError:
        from lyricsgenius.song import Song as GeniusSongObject

    HAVE_LYRICSGENIUS = True
    logging.getLogger(__name__).info("lyricsgenius library loaded successfully.")
except ImportError:
    lyricsgenius = None
    # Define fallback type hint if import fails
    GeniusSongObject = Any  # type: ignore
    HAVE_LYRICSGENIUS = False
    logging.getLogger(__name__).warning("`lyricsgenius` library not found. Genius lyrics fetching will be disabled.")

from .config import settings

logger = logging.getLogger(__name__)

# --- Configuration ---
LYRICS_ALIGNMENT_THRESHOLD = settings.LYRICS_ALIGNMENT_THRESHOLD
# Threshold for considering a whisper word a match for an official word
WORD_MATCH_THRESHOLD = 65  # (0-100 for rapidfuzz/difflib) - lowered for Cyrillic tolerance

NON_LYRIC_KEYWORDS = [
    "transl", "перев", "interpret", "оригин", "subtit", "caption", "sync",
    "chorus", "verse", "bridge", "intro", "outro", "solo", "instrumental",
    "spoken", "ad-lib", "ad lib", "applause", "cheering", "laughing", "repeat", "fades",
    "текст", "песни", "слова",
    # Add common Genius artifacts
    "lyrics", "embed", "contributors", "pyong", "tracklist", "lyricscontributor", "albumdiscussion"
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
    r'(official|video|audio|lyric|lyrics|visualizer|live|acoustic|cover|remix|edit|feat|ft\.?|with|explicit|clean|radio|album|version|deluxe|remastered|original|mix|extended|instrumental|hq|hd|4k|mv|pv)'
    r'\)?\s*',
    re.IGNORECASE
)
PATTERN_EXTRA_SPACES = re.compile(r'\s{2,}')
# Regex to split text into words, preserving internal hyphens/apostrophes
PATTERN_SPLIT_WORDS = re.compile(r"([\w'-]+)")


# --- Text Processing Functions ---
def normalize_text(text: str) -> str:
    """Normalizes text for matching: NFKC, lowercase, keep letters (including Cyrillic), numbers, spaces."""
    if not isinstance(text, str): return ""
    text = unicodedata.normalize('NFKC', text).lower()
    # Keep Unicode letters (\p{L}), numbers, spaces, hyphens, apostrophes
    # This regex keeps Cyrillic and other non-Latin scripts
    text = re.sub(r"[^\w\s'-]", '', text, flags=re.UNICODE)
    text = PATTERN_WHITESPACE.sub(' ', text).strip()
    return text


def clean_lyric_line(line: str) -> str:
    """Cleans a single lyric line by removing common non-lyric patterns."""
    if not isinstance(line, str): return ""
    cleaned_line = PATTERN_CLEAN.sub('', line).strip()
    # Remove lines that are only keywords after cleaning
    # Check against lowercased keywords for broader matching
    if cleaned_line.lower() in NON_LYRIC_KEYWORDS or cleaned_line.lower().replace(" ", "") in NON_LYRIC_KEYWORDS:
        return ""
    # Remove lines that become only punctuation after cleaning
    if PATTERN_ONLY_PUNCT.match(cleaned_line):
        return ""
    return cleaned_line


def split_text_into_words(text: str) -> List[str]:
    """Splits text into words, respecting hyphens and apostrophes, filters empty."""
    if not isinstance(text, str): return []
    return [word for word in PATTERN_SPLIT_WORDS.findall(text) if word]


def clean_search_term(term: Optional[str]) -> str:
    """Cleans a search term (title/artist) for Genius query."""
    if not term or not isinstance(term, str): return ''
    cleaned = PATTERN_JUNK_TITLE_ARTIST.sub(' ', term)
    cleaned = PATTERN_CLEAN.sub('', cleaned)  # Remove brackets etc.
    cleaned = PATTERN_EXTRA_SPACES.sub(' ', cleaned).strip(" .,!?;:\"")
    return cleaned


# --- Lyrics Fetching (adapted from one of the provided versions) ---
def fetch_lyrics_from_genius(
        song_title: str, artist: Optional[str] = None
) -> Optional[Tuple[List[str], Optional[GeniusSongObject]]]:
    """
    Fetches lyrics from Genius.
    Returns a tuple: (list_of_cleaned_lyric_lines, genius_song_object) or None if failed.
    """
    if not HAVE_LYRICSGENIUS or not settings.GENIUS_API_TOKEN:
        logger.warning("Genius client not available or API token missing. Skipping Genius fetch.")
        return None

    genius = lyricsgenius.Genius(
        settings.GENIUS_API_TOKEN,
        timeout=20,  # Increased timeout
        retries=2,
        verbose=False,  # Set to True for debugging genius client
        remove_section_headers=True,  # Remove things like [Chorus], [Verse]
        skip_non_songs=True,
        excluded_terms=["(Remix)", "(Live)"],  # Exclude common terms
        response_format='plain',  # Get plain text lyrics
    )

    clean_title_for_search = clean_search_term(song_title)
    clean_artist_for_search = clean_search_term(artist) if artist else ""

    if not clean_title_for_search:
        logger.warning(f"Song title '{song_title}' became empty after cleaning. Cannot search Genius.")
        return None

    logger.info(
        f"Searching Genius for title: '{clean_title_for_search}', artist: '{clean_artist_for_search or 'Any'}'.")
    song_object: Optional[GeniusSongObject] = None
    search_query_attempts = [
        (clean_title_for_search, clean_artist_for_search if clean_artist_for_search else None),
    ]
    # If artist was provided, try a search with only the title as a fallback
    if clean_artist_for_search:
        search_query_attempts.append((clean_title_for_search, None))
    # Fallback to original uncleaned title if cleaned one fails.
    if clean_title_for_search != song_title or (artist and clean_artist_for_search != artist):
        search_query_attempts.append((song_title, artist if artist else None))

    for title_q, artist_q in search_query_attempts:
        if not title_q: continue  # Skip if title query part is empty
        try:
            logger.debug(f"Genius API call with Title='{title_q}', Artist='{artist_q or 'Any'}'")
            # search_song should handle artist being None or empty string appropriately.
            song_candidate = genius.search_song(title_q, artist_q if artist_q else "")
            if song_candidate and isinstance(song_candidate, GeniusSongObject) and song_candidate.lyrics:
                song_object = song_candidate
                logger.info(f"Genius found: '{song_object.title}' by '{song_object.artist}'.")
                break  # Found a suitable song
        except Exception as e:
            # lyricsgenius can raise various exceptions, including network errors or custom ones.
            logger.warning(f"Genius search attempt (Title: {title_q}, Artist: {artist_q}) failed: {e}",
                           exc_info=False)  # Keep log concise

    if not song_object or not song_object.lyrics:
        logger.warning(f"No lyrics found on Genius for '{song_title}' by '{artist}'.")
        return None

    # Process lyrics
    raw_lyrics_text = song_object.lyrics
    lines = raw_lyrics_text.split('\n')

    cleaned_lines_final: List[str] = []
    title_norm_for_check = normalize_text(song_object.title)

    for idx, line_text in enumerate(lines):
        line_content_stripped = line_text.strip()

        # Stronger check for first line being a title repetition
        if idx == 0:
            normalized_line_content = normalize_text(line_content_stripped)
            is_likely_header = False
            if title_norm_for_check:  # Proceed only if title_norm is not empty
                if (title_norm_for_check in normalized_line_content or \
                    normalized_line_content in title_norm_for_check or \
                    fuzz.partial_ratio(normalized_line_content, title_norm_for_check) > 85) and \
                        len(normalized_line_content) < len(title_norm_for_check) + 20:
                    is_likely_header = True
                    if "lyrics" in normalized_line_content and len(normalized_line_content.split()) < len(
                            title_norm_for_check.split()) + 3:
                        pass
                    elif len(normalized_line_content.split()) > 10 and fuzz.ratio(normalized_line_content,
                                                                                  title_norm_for_check) < 70:
                        is_likely_header = False

            if is_likely_header:
                logger.debug(f"Skipping first line as it appears to be a title header: '{line_content_stripped}'")
                continue

        cleaned = clean_lyric_line(line_content_stripped)
        if cleaned:
            cleaned_lines_final.append(cleaned)

    if not cleaned_lines_final:
        logger.warning(f"Lyrics for '{song_object.title}' were empty after all cleaning processes.")
        return ([], song_object)

    logger.info(
        f"Successfully fetched and cleaned {len(cleaned_lines_final)} lines from Genius for '{song_object.title}'.")
    return (cleaned_lines_final, song_object)


# --- Alignment Functions ---

# Improved thresholds for better alignment
EXACT_MATCH_THRESHOLD = 90  # Very high confidence match
GOOD_MATCH_THRESHOLD = 70   # Good match (lowered for better recall)
MIN_MATCH_THRESHOLD = 50    # Minimum acceptable match (lowered for Cyrillic/non-Latin)
CONTEXT_WINDOW_BONUS = 20   # Bonus for matches within expected position (increased)

def _calculate_word_similarity(word1: str, word2: str) -> float:
    """Calculate similarity between two normalized words using multiple methods."""
    if not word1 or not word2:
        return 0.0

    # Exact match
    if word1 == word2:
        return 100.0

    # One word is a substring of the other (common for contractions, prefixes)
    if word1 in word2 or word2 in word1:
        len_ratio = min(len(word1), len(word2)) / max(len(word1), len(word2))
        return 75.0 + 25.0 * len_ratio  # 75-100 based on length ratio

    if USE_RAPIDFUZZ:
        # Use multiple scorers and take the best result
        ratio_score = fuzz.ratio(word1, word2)
        partial_score = fuzz.partial_ratio(word1, word2)
        token_sort_score = fuzz.token_sort_ratio(word1, word2)

        # Weight the scores based on word length
        if len(word1) <= 2 or len(word2) <= 2:
            # Very short words - be more lenient with partial matches
            return max(ratio_score, partial_score * 0.85)
        elif len(word1) <= 4 or len(word2) <= 4:
            # Short words - partial match still important
            return max(ratio_score, partial_score * 0.92, token_sort_score * 0.85)
        else:
            # Longer words - all methods equally weighted
            return max(ratio_score, partial_score * 0.95, token_sort_score * 0.92)
    else:
        matcher = difflib.SequenceMatcher(isjunk=None, autojunk=False)
        matcher.set_seqs(word1, word2)
        return matcher.ratio() * 100


def _find_best_word_match_improved(
        official_word_norm: str,
        whisper_words_candidates: List[Tuple[str, int, float]],  # (norm_text, global_idx, start_time)
        expected_time: Optional[float] = None,
        time_tolerance: float = 5.0,  # seconds
) -> Optional[Tuple[int, float, int]]:
    """
    Improved word matching that considers:
    - Fuzzy text similarity
    - Temporal proximity to expected position
    - Context from surrounding words

    Returns: (index_in_candidates, score, global_whisper_idx) or None
    """
    if not whisper_words_candidates or not official_word_norm:
        return None

    best_score = -1.0
    best_idx_in_candidates = -1
    best_global_idx = -1

    for i, (w_norm, global_idx, start_time) in enumerate(whisper_words_candidates):
        # Calculate base text similarity
        text_score = _calculate_word_similarity(official_word_norm, w_norm)

        if text_score < MIN_MATCH_THRESHOLD:
            continue

        # Apply temporal proximity bonus if expected time is known
        time_bonus = 0.0
        if expected_time is not None and start_time >= 0:
            time_diff = abs(start_time - expected_time)
            if time_diff <= time_tolerance:
                # Linear bonus based on proximity - closer = more bonus
                time_bonus = CONTEXT_WINDOW_BONUS * (1.0 - time_diff / time_tolerance)

        # Position bonus - prefer earlier matches when scores are similar
        position_bonus = max(0, (len(whisper_words_candidates) - i) * 0.1)

        final_score = text_score + time_bonus + position_bonus

        if final_score > best_score:
            best_score = final_score
            best_idx_in_candidates = i
            best_global_idx = global_idx

    if best_idx_in_candidates != -1 and best_score >= MIN_MATCH_THRESHOLD:
        return best_idx_in_candidates, best_score, best_global_idx
    return None


def _align_line_to_whisper_segment(
        line_words_norm: List[str],
        whisper_words: List[Dict],
        start_search_idx: int,
        expected_start_time: Optional[float] = None,
) -> Tuple[List[Optional[int]], int]:
    """
    Align a single line of official lyrics to whisper words.
    Returns: (list of matched whisper indices for each word, next search start index)
    """
    matched_indices: List[Optional[int]] = [None] * len(line_words_norm)
    current_idx = start_search_idx
    last_matched_time = expected_start_time or 0.0
    last_matched_idx = start_search_idx

    for word_idx, official_word in enumerate(line_words_norm):
        if not official_word:
            continue

        # Adaptive window - larger when we're uncertain, smaller when confident
        # Also allow looking backward a bit if we haven't matched anything yet
        base_window = 50  # Increased base window
        if word_idx > 0 and matched_indices[word_idx - 1] is not None:
            # Previous word matched - use smaller window but still reasonable
            base_window = 35

        # Allow looking back slightly if no matches yet in this line
        lookback = 5 if word_idx == 0 else 2
        search_start = max(0, current_idx - lookback)

        # Build candidate list
        window_end = min(len(whisper_words), search_start + base_window)
        candidates = []
        for i in range(search_start, window_end):
            w = whisper_words[i]
            candidates.append((w['norm_text'], i, w['start']))

        # Try to find match with reasonable time tolerance
        expected_time = last_matched_time + 0.3 if word_idx > 0 else expected_start_time
        match = _find_best_word_match_improved(
            official_word, candidates,
            expected_time=expected_time,
            time_tolerance=5.0  # Increased tolerance
        )

        if match:
            _, score, global_idx = match
            matched_indices[word_idx] = global_idx
            last_matched_time = whisper_words[global_idx]['start']
            last_matched_idx = global_idx
            # Move current_idx forward
            current_idx = global_idx + 1
        else:
            # No match found - try with much larger window as fallback
            extended_window_end = min(len(whisper_words), search_start + 100)  # Much larger
            extended_candidates = []
            for i in range(search_start, extended_window_end):
                w = whisper_words[i]
                extended_candidates.append((w['norm_text'], i, w['start']))

            extended_match = _find_best_word_match_improved(
                official_word, extended_candidates,
                expected_time=last_matched_time + 0.5 if last_matched_time > 0 else expected_start_time,
                time_tolerance=15.0  # Very tolerant for fallback
            )

            if extended_match:
                _, score, global_idx = extended_match
                matched_indices[word_idx] = global_idx
                last_matched_time = whisper_words[global_idx]['start']
                last_matched_idx = global_idx
                current_idx = global_idx + 1

    # Return the next search position, allowing some overlap for the next line
    next_search_idx = max(start_search_idx + 1, last_matched_idx - 3)
    return matched_indices, next_search_idx


def _interpolate_timings(
        matched_indices: List[Optional[int]],
        whisper_words: List[Dict],
        official_words: List[str],
        line_start_time: float,
        line_end_time: float,
) -> List[Dict]:
    """
    Create timed word list, interpolating timings for unmatched words.
    """
    timed_words = []
    n_words = len(official_words)

    # Find anchor points (words with matched timings)
    anchors = []  # (word_idx, start_time, end_time)
    for idx, matched_idx in enumerate(matched_indices):
        if matched_idx is not None and matched_idx < len(whisper_words):
            w = whisper_words[matched_idx]
            anchors.append((idx, w['start'], w['end']))

    if not anchors:
        # No anchors - distribute evenly
        total_duration = max(0.5, line_end_time - line_start_time)
        word_duration = total_duration / n_words
        for idx, word in enumerate(official_words):
            start = line_start_time + idx * word_duration
            end = start + word_duration * 0.95  # Small gap between words
            timed_words.append({'text': word, 'start': start, 'end': end})
        return timed_words

    # Interpolate between anchors
    for idx, word in enumerate(official_words):
        matched_idx = matched_indices[idx]

        if matched_idx is not None and matched_idx < len(whisper_words):
            # Direct match - use whisper timing
            w = whisper_words[matched_idx]
            timed_words.append({'text': word, 'start': w['start'], 'end': w['end']})
        else:
            # Find surrounding anchors for interpolation
            prev_anchor = None
            next_anchor = None

            for a_idx, a_start, a_end in anchors:
                if a_idx < idx:
                    prev_anchor = (a_idx, a_start, a_end)
                elif a_idx > idx and next_anchor is None:
                    next_anchor = (a_idx, a_start, a_end)
                    break

            # Calculate interpolated timing
            if prev_anchor and next_anchor:
                # Interpolate between two anchors
                prev_idx, prev_start, prev_end = prev_anchor
                next_idx, next_start, next_end = next_anchor
                words_between = next_idx - prev_idx
                position = idx - prev_idx
                time_span = next_start - prev_end
                word_duration = time_span / words_between if words_between > 0 else 0.2
                start = prev_end + position * word_duration
                end = start + word_duration * 0.95
            elif prev_anchor:
                # Only have previous anchor - estimate forward
                prev_idx, prev_start, prev_end = prev_anchor
                gap = idx - prev_idx
                word_duration = max(0.15, min(len(word) * 0.06, 0.5))
                start = prev_end + (gap - 1) * word_duration + 0.05
                end = start + word_duration
            elif next_anchor:
                # Only have next anchor - estimate backward
                next_idx, next_start, next_end = next_anchor
                gap = next_idx - idx
                word_duration = max(0.15, min(len(word) * 0.06, 0.5))
                end = next_start - (gap - 1) * word_duration - 0.05
                start = max(line_start_time, end - word_duration)
            else:
                # Should not happen if we have anchors
                word_duration = 0.3
                start = line_start_time + idx * word_duration
                end = start + word_duration * 0.95

            # Ensure valid timing
            start = max(0, start)
            end = max(start + 0.05, end)

            timed_words.append({'text': word, 'start': start, 'end': end})

    # Fix overlaps and ensure monotonic timing
    for i in range(1, len(timed_words)):
        if timed_words[i]['start'] < timed_words[i-1]['end']:
            # Overlap detected - adjust
            mid_point = (timed_words[i-1]['end'] + timed_words[i]['start']) / 2
            timed_words[i-1]['end'] = mid_point - 0.01
            timed_words[i]['start'] = mid_point + 0.01

    return timed_words


def prepare_segments_for_karaoke(
        recognized_segments: List[Dict],
        official_lyrics_lines: Optional[List[str]] = None
) -> List[Dict]:
    """
    Improved karaoke segment preparation with better fuzzy matching.
    Uses a two-phase approach: line-level alignment followed by word-level refinement.
    """
    job_id_for_log = "N/A"
    logger.info(
        f"Job {job_id_for_log}: Preparing segments for karaoke. Recognized segments: {len(recognized_segments)}. Official lines: {len(official_lyrics_lines) if official_lyrics_lines else 'None'}.")

    # Extract all timed words from Whisper recognition
    all_whisper_words_timed: List[Dict] = []
    for seg_idx, seg in enumerate(recognized_segments):
        if not (isinstance(seg, dict) and 'start' in seg and 'end' in seg and \
                isinstance(seg.get('text'), str) and seg['text'].strip() and \
                isinstance(seg.get('words'), list)):
            continue

        for w_idx, w in enumerate(seg['words']):
            w_text_value = w.get('text')
            w_start_value = w.get('start')
            w_end_value = w.get('end')

            if not (isinstance(w, dict) and \
                    'start' in w and 'end' in w and \
                    isinstance(w_text_value, str) and \
                    isinstance(w_start_value, (int, float)) and \
                    isinstance(w_end_value, (int, float)) and \
                    w_end_value >= w_start_value):
                continue

            w_text_strip = w_text_value.strip()
            if not w_text_strip:
                continue

            all_whisper_words_timed.append({
                "text": w_text_strip,
                "norm_text": normalize_text(w_text_strip),
                "start": float(w_start_value),
                "end": float(w_end_value),
                "original_segment_idx": seg_idx,
                "original_word_idx": w_idx
            })
    all_whisper_words_timed.sort(key=lambda x: x['start'])

    if not all_whisper_words_timed:
        logger.warning(
            f"Job {job_id_for_log}: No valid timed words found in recognized_segments. Cannot generate timed lyrics.")
        return []

    # If no official lyrics, use Whisper transcription directly
    if not official_lyrics_lines:
        logger.info(f"Job {job_id_for_log}: No official lyrics provided. Using Whisper's transcription directly.")
        karaoke_segments_from_whisper = []
        for seg in recognized_segments:
            segment_text = seg.get('text', '').strip()
            words_in_segment = []

            seg_start_time = seg.get('start')
            seg_end_time = seg.get('end')

            if not (segment_text and isinstance(seg_start_time, (int, float)) and isinstance(seg_end_time, (int, float))):
                continue

            for w_data in seg.get('words', []):
                w_text_val = w_data.get('text')
                w_start_val = w_data.get('start')
                w_end_val = w_data.get('end')

                if not (isinstance(w_data, dict) and 'start' in w_data and 'end' in w_data and \
                        isinstance(w_text_val, str) and \
                        isinstance(w_start_val, (int, float)) and \
                        isinstance(w_end_val, (int, float)) and \
                        w_end_val >= w_start_val):
                    continue

                w_text_strip_inner = w_text_val.strip()
                if not w_text_strip_inner:
                    continue

                words_in_segment.append({
                    "text": w_text_strip_inner,
                    "start": float(w_start_val),
                    "end": float(w_end_val)
                })

            if words_in_segment:
                seg_start_actual = words_in_segment[0]['start']
                seg_end_actual = words_in_segment[-1]['end']
                karaoke_segments_from_whisper.append({
                    "start": seg_start_actual,
                    "end": seg_end_actual,
                    "text": segment_text,
                    "words": words_in_segment,
                    "aligned": False
                })
        logger.info(
            f"Job {job_id_for_log}: Prepared {len(karaoke_segments_from_whisper)} segments using Whisper transcription.")
        return karaoke_segments_from_whisper

    # === IMPROVED ALIGNMENT ALGORITHM ===
    logger.info(
        f"Job {job_id_for_log}: Aligning {len(official_lyrics_lines)} official lines with {len(all_whisper_words_timed)} Whisper words using improved algorithm.")

    aligned_karaoke_segments = []
    current_search_idx = 0
    total_audio_duration = all_whisper_words_timed[-1]['end'] if all_whisper_words_timed else 0

    # Calculate rough time per line for initial positioning
    valid_lines = [l.strip() for l in official_lyrics_lines if l.strip()]
    time_per_line = total_audio_duration / len(valid_lines) if valid_lines else 3.0

    for line_idx, official_line_text in enumerate(official_lyrics_lines):
        official_line_text_strip = official_line_text.strip()
        if not official_line_text_strip:
            continue

        official_words_in_line = split_text_into_words(official_line_text_strip)
        if not official_words_in_line:
            continue

        # Normalize words for matching
        official_words_norm = [normalize_text(w) for w in official_words_in_line]

        # Estimate expected start time for this line
        expected_line_start = line_idx * time_per_line if line_idx > 0 else 0

        # Use improved line-level alignment
        matched_indices, next_search_idx = _align_line_to_whisper_segment(
            official_words_norm,
            all_whisper_words_timed,
            current_search_idx,
            expected_start_time=expected_line_start
        )

        # Determine line boundaries based on matches
        matched_times = []
        for idx, match_idx in enumerate(matched_indices):
            if match_idx is not None and match_idx < len(all_whisper_words_timed):
                w = all_whisper_words_timed[match_idx]
                matched_times.append((w['start'], w['end']))

        if matched_times:
            line_start = matched_times[0][0]
            line_end = matched_times[-1][1]
        elif aligned_karaoke_segments:
            # No matches - estimate based on previous segment
            prev_end = aligned_karaoke_segments[-1]['end']
            line_start = prev_end + 0.1
            line_end = line_start + len(official_words_in_line) * 0.3
        else:
            # First line with no matches
            line_start = expected_line_start
            line_end = line_start + len(official_words_in_line) * 0.3

        # Interpolate timings for all words in the line
        timed_words = _interpolate_timings(
            matched_indices,
            all_whisper_words_timed,
            official_words_in_line,
            line_start,
            line_end
        )

        if timed_words:
            seg_start = timed_words[0]['start']
            seg_end = timed_words[-1]['end']
            if seg_end >= seg_start:
                aligned_karaoke_segments.append({
                    "start": seg_start,
                    "end": seg_end,
                    "text": official_line_text_strip,
                    "words": timed_words,
                    "aligned": True
                })

        # Update search position
        current_search_idx = next_search_idx

    # Post-processing: fix any overlapping segments
    for i in range(1, len(aligned_karaoke_segments)):
        prev_seg = aligned_karaoke_segments[i - 1]
        curr_seg = aligned_karaoke_segments[i]
        if curr_seg['start'] < prev_seg['end']:
            # Fix overlap
            gap = 0.05
            mid_point = (prev_seg['end'] + curr_seg['start']) / 2
            prev_seg['end'] = mid_point - gap / 2
            curr_seg['start'] = mid_point + gap / 2
            # Also fix word timings
            if prev_seg['words']:
                prev_seg['words'][-1]['end'] = prev_seg['end']
            if curr_seg['words']:
                curr_seg['words'][0]['start'] = curr_seg['start']

    logger.info(
        f"Job {job_id_for_log}: Improved alignment created {len(aligned_karaoke_segments)} segments from official lyrics.")

    # Log alignment statistics
    total_words = sum(len(seg['words']) for seg in aligned_karaoke_segments)
    matched_count = sum(
        1 for seg in aligned_karaoke_segments
        for w in seg.get('words', [])
        if w.get('start', 0) > 0
    )
    logger.info(f"Job {job_id_for_log}: Aligned {matched_count}/{total_words} words successfully.")

    if not aligned_karaoke_segments and official_lyrics_lines:
        logger.warning(f"Job {job_id_for_log}: Alignment with official lyrics resulted in zero segments.")

    return aligned_karaoke_segments


def align_custom_lyrics_with_word_times(
        custom_lyrics_text: str,
        recognized_segments: List[Dict]
) -> List[Dict]:
    """
    Align custom lyrics with Whisper word timings using improved fuzzy matching.
    This function is used when the user provides custom lyrics (e.g., from Genius selection).
    """
    job_id_for_log = "N/A"
    logger.info(f"Job {job_id_for_log}: Aligning custom lyrics with Whisper word timings (improved algorithm).")

    if not custom_lyrics_text:
        logger.warning(f"Job {job_id_for_log}: Empty custom lyrics text provided.")
        return []

    # Extract all timed words with their text for fuzzy matching
    all_whisper_words: List[Dict] = []
    for seg in recognized_segments:
        if isinstance(seg, dict) and 'words' in seg and isinstance(seg['words'], list):
            for w in seg['words']:
                w_text = w.get('text', '').strip()
                w_start = w.get('start')
                w_end = w.get('end')
                if (isinstance(w, dict) and w_text and
                        isinstance(w_start, (int, float)) and isinstance(w_end, (int, float)) and
                        w_end >= w_start):
                    all_whisper_words.append({
                        "text": w_text,
                        "norm_text": normalize_text(w_text),
                        "start": float(w_start),
                        "end": float(w_end)
                    })
    all_whisper_words.sort(key=lambda x: x['start'])

    if not all_whisper_words:
        logger.error(f"Job {job_id_for_log}: No valid word timings from Whisper. Cannot align custom lyrics.")
        return []

    logger.debug(f"Job {job_id_for_log}: Extracted {len(all_whisper_words)} timed words from Whisper.")

    # Parse custom lyrics into lines
    custom_lines = [line.strip() for line in custom_lyrics_text.splitlines() if line.strip()]
    if not custom_lines:
        logger.warning(f"Job {job_id_for_log}: Custom lyrics text had no valid lines.")
        return []

    # Use the improved alignment approach
    total_audio_duration = all_whisper_words[-1]['end'] if all_whisper_words else 0
    time_per_line = total_audio_duration / len(custom_lines) if custom_lines else 3.0

    result_segments = []
    current_search_idx = 0

    for line_idx, line_text in enumerate(custom_lines):
        custom_words = split_text_into_words(line_text)
        if not custom_words:
            continue

        custom_words_norm = [normalize_text(w) for w in custom_words]
        expected_line_start = line_idx * time_per_line

        # Use line-level alignment
        matched_indices, next_search_idx = _align_line_to_whisper_segment(
            custom_words_norm,
            all_whisper_words,
            current_search_idx,
            expected_start_time=expected_line_start
        )

        # Determine line time boundaries
        matched_times = []
        for idx, match_idx in enumerate(matched_indices):
            if match_idx is not None and match_idx < len(all_whisper_words):
                w = all_whisper_words[match_idx]
                matched_times.append((w['start'], w['end']))

        if matched_times:
            line_start = matched_times[0][0]
            line_end = matched_times[-1][1]
        elif result_segments:
            prev_end = result_segments[-1]['end']
            line_start = prev_end + 0.1
            line_end = line_start + len(custom_words) * 0.3
        else:
            line_start = expected_line_start
            line_end = line_start + len(custom_words) * 0.3

        # Interpolate timings
        timed_words = _interpolate_timings(
            matched_indices,
            all_whisper_words,
            custom_words,
            line_start,
            line_end
        )

        if timed_words:
            seg_start = timed_words[0]['start']
            seg_end = timed_words[-1]['end']
            if seg_end >= seg_start:
                result_segments.append({
                    'start': seg_start,
                    'end': seg_end,
                    'text': line_text,
                    'words': timed_words,
                    'aligned': True
                })

        current_search_idx = next_search_idx

    # Fix overlapping segments
    for i in range(1, len(result_segments)):
        prev_seg = result_segments[i - 1]
        curr_seg = result_segments[i]
        if curr_seg['start'] < prev_seg['end']:
            gap = 0.05
            mid_point = (prev_seg['end'] + curr_seg['start']) / 2
            prev_seg['end'] = mid_point - gap / 2
            curr_seg['start'] = mid_point + gap / 2
            if prev_seg['words']:
                prev_seg['words'][-1]['end'] = prev_seg['end']
            if curr_seg['words']:
                curr_seg['words'][0]['start'] = curr_seg['start']

    logger.info(f"Job {job_id_for_log}: Aligned {len(result_segments)} custom lyric lines with improved algorithm.")
    return result_segments