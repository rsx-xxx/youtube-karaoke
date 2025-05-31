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
    # Import the Song class directly if possible for type hinting
    from lyricsgenius.song import Song as GeniusSongObject

    HAVE_LYRICSGENIUS = True
except ImportError:
    lyricsgenius = None
    # Define fallback type hint if import fails
    GeniusSongObject = Any  # type: ignore
    HAVE_LYRICSGENIUS = False
    logging.getLogger(__name__).warning("`lyricsgenius` library not found. Genius lyrics fetching will be disabled.")
except AttributeError:
    # Handle cases where lyricsgenius might be installed but 'song' module or 'Song' class isn't found
    lyricsgenius = None
    GeniusSongObject = Any  # type: ignore
    HAVE_LYRICSGENIUS = False
    logging.getLogger(__name__).error(
        "Could not import 'Song' from 'lyricsgenius.song'. Genius features might be broken.")

from config import settings

logger = logging.getLogger(__name__)

# --- Configuration ---
LYRICS_ALIGNMENT_THRESHOLD = settings.LYRICS_ALIGNMENT_THRESHOLD
# Threshold for considering a whisper word a match for an official word
WORD_MATCH_THRESHOLD = 75  # (0-100 for rapidfuzz/difflib)

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
    """Normalizes text for matching: NFKC, lowercase, remove non-alphanum (keep spaces, hyphens, apostrophes)."""
    if not isinstance(text, str): return ""
    text = unicodedata.normalize('NFKC', text).lower()
    # Allow letters, numbers, spaces, hyphens, apostrophes
    text = re.sub(r"[^a-z0-9\s'-]", '', text)
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
def _find_best_word_match(
        official_word_norm: str,
        whisper_words_candidates: List[Tuple[str, int]],
) -> Optional[Tuple[int, float]]:
    """Finds the best matching whisper word index from the candidates list for a given official word."""
    best_score = -1.0
    best_idx_in_candidates = -1

    if not whisper_words_candidates:
        return None

    if USE_RAPIDFUZZ:
        choices = [w_candidate[0] for w_candidate in whisper_words_candidates]
        match_result = process.extractOne(official_word_norm, choices, scorer=fuzz.WRatio,
                                          score_cutoff=WORD_MATCH_THRESHOLD)
        if match_result:
            best_score = match_result[1]
            best_idx_in_candidates = match_result[2]
    else:
        matcher = difflib.SequenceMatcher(isjunk=None, autojunk=False)
        matcher.set_seq2(official_word_norm)
        for i, (w_norm_candidate, _) in enumerate(whisper_words_candidates):
            matcher.set_seq1(w_norm_candidate)
            ratio = matcher.ratio() * 100
            if ratio >= WORD_MATCH_THRESHOLD and ratio > best_score:
                best_score = ratio
                best_idx_in_candidates = i

    if best_idx_in_candidates != -1:
        return best_idx_in_candidates, best_score
    return None


def prepare_segments_for_karaoke(
        recognized_segments: List[Dict],
        official_lyrics_lines: Optional[List[str]] = None
) -> List[Dict]:
    job_id_for_log = "N/A"
    logger.info(
        f"Job {job_id_for_log}: Preparing segments for karaoke. Recognized segments: {len(recognized_segments)}. Official lines: {len(official_lyrics_lines) if official_lyrics_lines else 'None'}.")

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

    if not official_lyrics_lines:
        logger.info(f"Job {job_id_for_log}: No official lyrics provided. Using Whisper's transcription directly.")
        karaoke_segments_from_whisper = []
        for seg in recognized_segments:  # Iterate original segments for structure
            segment_text = seg.get('text', '').strip()
            words_in_segment = []

            seg_start_time = seg.get('start')
            seg_end_time = seg.get('end')

            if not (segment_text and isinstance(seg_start_time, (int, float)) and isinstance(seg_end_time,
                                                                                             (int, float))):
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

    logger.info(
        f"Job {job_id_for_log}: Aligning {len(official_lyrics_lines)} official lines with {len(all_whisper_words_timed)} Whisper words.")
    aligned_karaoke_segments = []
    current_global_whisper_idx = 0

    for official_line_text in official_lyrics_lines:
        official_line_text_strip = official_line_text.strip()
        if not official_line_text_strip: continue

        official_words_in_line = split_text_into_words(official_line_text_strip)
        if not official_words_in_line: continue

        timed_words_for_this_line = []

        for official_word_idx, official_word_text in enumerate(official_words_in_line):
            official_word_norm = normalize_text(official_word_text)
            if not official_word_norm: continue

            word_start, word_end = -1.0, -1.0

            search_window_start_idx = current_global_whisper_idx
            search_window_end_idx = min(len(all_whisper_words_timed), search_window_start_idx + 20)

            whisper_candidates_in_window = []
            for i in range(search_window_start_idx, search_window_end_idx):
                whisper_candidates_in_window.append(
                    (all_whisper_words_timed[i]['norm_text'], i)
                )

            match_info = None
            if whisper_candidates_in_window:
                match_info = _find_best_word_match(official_word_norm, whisper_candidates_in_window)

            if match_info:
                best_match_idx_in_window = match_info[0]
                matched_global_whisper_idx = whisper_candidates_in_window[best_match_idx_in_window][1]

                matched_whisper_data = all_whisper_words_timed[matched_global_whisper_idx]
                word_start = matched_whisper_data['start']
                word_end = matched_whisper_data['end']

                current_global_whisper_idx = matched_global_whisper_idx + 1
            else:
                prev_timed_word_end = timed_words_for_this_line[-1]['end'] if timed_words_for_this_line else -1.0

                if prev_timed_word_end > 0:
                    word_start = prev_timed_word_end + 0.05
                elif current_global_whisper_idx < len(all_whisper_words_timed):
                    word_start = all_whisper_words_timed[current_global_whisper_idx]['start']
                elif aligned_karaoke_segments:
                    word_start = aligned_karaoke_segments[-1]['end'] + 0.1
                else:
                    word_start = 0.0

                estimated_duration = max(0.15, min(len(official_word_norm) * 0.07, 0.6))
                word_end = word_start + estimated_duration

                new_global_idx_after_estimation = current_global_whisper_idx
                while new_global_idx_after_estimation < len(all_whisper_words_timed) and \
                        all_whisper_words_timed[new_global_idx_after_estimation]['start'] < word_end:
                    new_global_idx_after_estimation += 1

                current_global_whisper_idx = new_global_idx_after_estimation

            if word_start >= 0 and word_end > word_start:
                timed_words_for_this_line.append({
                    "text": official_word_text, "start": word_start, "end": word_end
                })
            else:
                logger.warning(
                    f"Job {job_id_for_log}: Could not assign valid timing for official word '{official_word_text}'. Skipping.")

        if timed_words_for_this_line:
            seg_start = timed_words_for_this_line[0]['start']
            seg_end = timed_words_for_this_line[-1]['end']
            if seg_end >= seg_start:
                aligned_karaoke_segments.append({
                    "start": seg_start, "end": seg_end, "text": official_line_text_strip,
                    "words": timed_words_for_this_line, "aligned": True
                })

    logger.info(
        f"Job {job_id_for_log}: Alignment process created {len(aligned_karaoke_segments)} segments from official lyrics.")
    if not aligned_karaoke_segments and official_lyrics_lines:
        logger.warning(f"Job {job_id_for_log}: Alignment with official lyrics resulted in zero segments.")

    return aligned_karaoke_segments


def align_custom_lyrics_with_word_times(
        custom_lyrics_text: str,
        recognized_segments: List[Dict]
) -> List[Dict]:
    job_id_for_log = "N/A"
    logger.info(f"Job {job_id_for_log}: Applying recognized word timings sequentially to custom lyrics.")
    if not custom_lyrics_text:
        logger.warning(f"Job {job_id_for_log}: Empty custom lyrics text provided.")
        return []

    all_recognized_word_timings: List[Dict] = []
    for seg in recognized_segments:
        if isinstance(seg, dict) and 'words' in seg and isinstance(seg['words'], list):
            for w in seg['words']:
                w_start_value = w.get('start')
                w_end_value = w.get('end')
                if (isinstance(w, dict) and 'start' in w and 'end' in w and
                        isinstance(w_start_value, (int, float)) and isinstance(w_end_value, (int, float)) and
                        w_end_value >= w_start_value):
                    all_recognized_word_timings.append({"start": float(w_start_value), "end": float(w_end_value)})
    all_recognized_word_timings.sort(key=lambda x: x['start'])

    if not all_recognized_word_timings:
        logger.error(f"Job {job_id_for_log}: No valid word timings from Whisper. Cannot apply to custom lyrics.")
        return []
    logger.debug(
        f"Job {job_id_for_log}: Extracted {len(all_recognized_word_timings)} timed words from Whisper for custom lyrics.")

    custom_lines = [line.strip() for line in custom_lyrics_text.splitlines() if line.strip()]
    if not custom_lines:
        logger.warning(f"Job {job_id_for_log}: Custom lyrics text had no valid lines after splitting.")
        return []

    result_segments = []
    current_rec_word_timing_idx = 0
    total_rec_timings = len(all_recognized_word_timings)
    last_assigned_end_time = 0.0
    if total_rec_timings > 0:
        last_assigned_end_time = max(0.0, all_recognized_word_timings[0]['start'] - 0.1)

    for line_text in custom_lines:
        custom_words_in_line = split_text_into_words(line_text)
        if not custom_words_in_line: continue

        segment_words_data = []
        line_start_time, line_end_time = -1.0, -1.0

        for custom_word_text in custom_words_in_line:
            word_start, word_end = -1.0, -1.0

            if current_rec_word_timing_idx < total_rec_timings:
                rec_timing = all_recognized_word_timings[current_rec_word_timing_idx]
                word_start = rec_timing['start']
                word_end = rec_timing['end']
                if word_start < last_assigned_end_time:
                    duration = max(0.1, word_end - word_start)
                    word_start = last_assigned_end_time + 0.01
                    word_end = word_start + duration
                last_assigned_end_time = word_end
                current_rec_word_timing_idx += 1
            else:
                estimated_duration = max(0.15, min(len(custom_word_text) * 0.07, 0.6))
                word_start = last_assigned_end_time + 0.05
                word_end = word_start + estimated_duration
                last_assigned_end_time = word_end
                if current_rec_word_timing_idx == total_rec_timings:  # Log only once
                    logger.info(
                        f"Job {job_id_for_log}: Exhausted Whisper timings. Estimating for remaining custom words.")
                    current_rec_word_timing_idx += 1

            segment_words_data.append({"text": custom_word_text, "start": word_start, "end": word_end})
            if line_start_time < 0: line_start_time = word_start
            line_end_time = word_end

        if segment_words_data and line_start_time >= 0 and line_end_time >= line_start_time:
            result_segments.append({
                'start': line_start_time, 'end': line_end_time, 'text': line_text,
                'words': segment_words_data, 'aligned': False
            })

    logger.info(f"Job {job_id_for_log}: Applied timings to {len(result_segments)} custom lyric lines.")
    return result_segments