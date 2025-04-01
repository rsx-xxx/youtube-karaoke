# File: backend/lyrics_processing.py
"""
Handles fetching song lyrics from the Genius API and aligning them
with transcription segments. Includes text normalization and cleaning.
"""
import os
import re
import difflib
import logging
import unicodedata  # For robust text normalization
from typing import Optional
# Attempt to import lyricsgenius, handle potential ImportError
try:
    import lyricsgenius
except ImportError:
    lyricsgenius = None  # Set to None if not installed
    logging.getLogger(__name__).warning("`lyricsgenius` library not found. Genius lyrics fetching will be disabled.")

# --- Setup Logger ---
logger = logging.getLogger(__name__)

# --- Configuration ---
# Genius API Token should be set as an environment variable
LYRICS_ALIGNMENT_THRESHOLD = 0.60  # Confidence threshold for matching (0.0 to 1.0)
# Keywords to identify potential non-lyric lines
NON_LYRIC_KEYWORDS = [
    "transl", "перев", "interpret", "оригин", "subtit", "caption", "sync",
    "chorus", "verse", "bridge", "intro", "outro", "guitar solo", "instrumental",
    "spoken", "ad lib", "applause", "cheering", "laughing"  # Added more common markers
]
# Regex pattern to remove common annotations, timestamps, etc.
# Added removal of lines starting with # (comments) and potential HTML tags
CLEANING_PATTERN = r'\[[^\]]*?\]|\([^)]*?\)|<[^>]*?>|\*.*?\*|^\s*#.*$'


# --- Text Processing Functions ---

def normalize_text(text: str) -> str:
    """
    Normalizes text for comparison: Unicode normalization, lowercase, removes punctuation.
    """
    if not isinstance(text, str) or not text: return ""
    try:
        # NFKC handles compatibility characters and composition (e.g., accents)
        normalized = unicodedata.normalize('NFKC', text)
        normalized = normalized.lower()
        # Remove punctuation but keep word characters (letters, numbers, underscore) and whitespace
        normalized = re.sub(r'[^\w\s]', '', normalized, flags=re.UNICODE)
        # Collapse multiple whitespace characters into one space
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized
    except Exception as e:
        logger.warning(f"Error during text normalization for input '{text[:50]}...': {e}")
        # Fallback to basic lowercasing and stripping
        return re.sub(r'\s+', ' ', text.lower()).strip()


def force_only_words(transcript_segments: list[dict]) -> list[dict]:
    """
    Cleans text within transcript segments: removes annotations, normalizes whitespace,
    and removes segments that become empty or contain only punctuation/symbols.
    """
    cleaned_segments = []
    # Compile regex patterns once for efficiency
    pattern_clean = re.compile(CLEANING_PATTERN)
    pattern_whitespace = re.compile(r'\s+')
    # Pattern to check if only punctuation/symbols remain (non-alphanumeric or underscore)
    pattern_only_punct = re.compile(r'^[\W_]+$')

    for seg in transcript_segments:
        original_text = seg.get("text", "")
        if not original_text: continue  # Skip segments with no text

        # Remove specified patterns (brackets, etc.)
        cleaned_text = pattern_clean.sub('', original_text)
        # Normalize whitespace
        cleaned_text = pattern_whitespace.sub(' ', cleaned_text).strip()

        # Only add segment if meaningful text remains (not empty or just symbols)
        if cleaned_text and not pattern_only_punct.match(cleaned_text):
            # Create a copy to avoid modifying the original segment list directly
            new_seg = seg.copy()
            new_seg["text"] = cleaned_text
            cleaned_segments.append(new_seg)
            # logger.debug(f"Cleaned segment: '{original_text}' -> '{cleaned_text}'")
        # else: logger.debug(f"Discarded empty/symbol-only segment from: '{original_text}' -> '{cleaned_text}'")

    return cleaned_segments


# --- Lyrics Fetching and Alignment ---

def fetch_lyrics_from_genius(song_title: str) -> Optional[list[str]]:
    """
    Retrieves and cleans song lyrics from the Genius API using the song title.
    Requires `lyricsgenius` library and GENIUS_API_TOKEN environment variable.
    Returns a list of cleaned lyric lines, or None if failed.
    """
    if lyricsgenius is None:
        logger.warning("Cannot fetch from Genius: lyricsgenius library not installed.")
        return None

    token = os.environ.get("GENIUS_API_TOKEN")
    if not token:
        logger.warning("Cannot fetch from Genius: GENIUS_API_TOKEN environment variable not set.")
        return None

    logger.info(f"Attempting to fetch lyrics from Genius for title: '{song_title}'")
    try:
        # Initialize Genius client with common settings
        genius = lyricsgenius.Genius(
            token,
            timeout=25,
            retries=3,
            verbose=False,  # Suppress library's console output
            remove_section_headers=True,  # Remove [Chorus], [Verse], etc.
            skip_non_songs=True,
            excluded_terms=["(Remix)", "(Live)", "Acoustic", "Cover"]  # Exclude common variations
        )

        # Search for the song
        song = genius.search_song(song_title)

        if song is None or not hasattr(song, 'lyrics') or not song.lyrics:
            logger.info(f"Lyrics not found on Genius for: '{song_title}'")
            return None

        raw_lyrics = song.lyrics
        # logger.debug(f"Raw lyrics received from Genius for '{song_title}':\n{raw_lyrics[:300]}...")

        # Additional cleaning specific to Genius artifacts (headers/footers)
        patterns_to_remove = [
            r'^\d*EmbedShare URLCopyEmbedCopy.*<span class="math-inline">',  # Common header junk
            r'\\d\*Contributors?\.\*Lyrics\\b',  # Contributor headers
            re.escape(song.title) + r"\\s\*Lyrics\\b",  # Song title header itself \(case\-insensitive\)
            r'You might also like\.\*',  # "You might also like" section
            r'\\d\+Embed</span>',  # Numeric embed code at end
            r'See .* Live$'  # Ad links
        ]
        removal_pattern = re.compile('|'.join(patterns_to_remove), flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
        cleaned_lyrics_text = removal_pattern.sub('', raw_lyrics).strip()

        lines = []
        # Compile pattern here if needed per line, but CLEANING_PATTERN is likely sufficient
        # bracket_pattern = re.compile(CLEANING_PATTERN)

        for line in cleaned_lyrics_text.split('\n'):
            cleaned_line = line.strip()
            # Optional: Apply CLEANING_PATTERN per line if remove_section_headers wasn't enough
            # cleaned_line = bracket_pattern.sub('', cleaned_line).strip()

            # Add line if it's not empty after cleaning
            if cleaned_line:
                lines.append(cleaned_line)

        # Final filtering pass: Remove lines that seem like annotations or are too short
        final_lines = [
            line for line in lines
            if not any(keyword in normalize_text(line) for keyword in NON_LYRIC_KEYWORDS)
               and len(normalize_text(line)) > 2  # Require at least 3 alphanumeric chars after normalization
        ]

        if not final_lines:
            logger.warning(f"No valid lyric lines remained after cleaning Genius lyrics for '{song_title}'.")
            return None

        logger.info(f"Found {len(final_lines)} potentially valid lines of lyrics on Genius for '{song_title}'.")
        return final_lines

    except Exception as e:
        # Catch potential timeouts, network errors, or parsing issues
        logger.error(f"Error fetching or processing lyrics from Genius for '{song_title}': {e}", exc_info=True)
        return None  # Return None on any exception during fetch/process


def align_lyrics(official_lines: list[str], recognized_segments: list[dict], uploader: str = "") -> list[dict]:
    """
    Aligns recognized transcription segments with official lyrics using fuzzy string matching.
    Replaces segment text with the official lyric line if match confidence is high enough.

    Args:
        official_lines: List of strings representing cleaned official lyrics.
        recognized_segments: List of dicts, each with 'start', 'end', 'text'.
        uploader: Optional uploader name (currently unused).

    Returns:
        A new list of segments, potentially with updated 'text' and alignment info.
    """
    if not official_lines:
        # logger.info("No official lyrics provided for alignment. Returning original segments.")
        return recognized_segments  # Return original if no official lyrics

    logger.info(
        f"Aligning {len(recognized_segments)} recognized segments with {len(official_lines)} official lyric lines.")

    # Prepare official lyrics by normalizing them once for efficient comparison
    normalized_official = [
        (normalize_text(line), line) for line in official_lines if normalize_text(line)
    ]

    if not normalized_official:
        logger.warning("No valid official lyric lines remained after normalization for alignment.")
        return recognized_segments

    aligned_segments = []
    matcher = difflib.SequenceMatcher(isjunk=None, autojunk=False)  # Use SequenceMatcher for fuzzy matching
    used_official_indices = set()  # Track used lines to prefer 1-to-1 alignment
    num_aligned = 0

    for i, seg in enumerate(recognized_segments):
        recognized_text = seg.get("text", "")
        if not recognized_text:
            aligned_segments.append(seg)  # Keep segments without text
            continue

        normalized_recognized = normalize_text(recognized_text)
        if not normalized_recognized:
            aligned_segments.append(seg)  # Keep segments that become empty after normalization
            continue

        best_match_line = recognized_text  # Default to original text
        best_ratio = 0.0
        best_match_idx = -1  # Index of the best matching official line

        # Compare normalized recognized text against each *unused* normalized official line
        matcher.set_seq1(normalized_recognized)
        for idx, (norm_official, original_official) in enumerate(normalized_official):
            if idx in used_official_indices: continue  # Skip if already used

            matcher.set_seq2(norm_official)
            ratio = matcher.ratio()

            # --- Optional: Advanced Heuristic (e.g., prefer matches closer in sequence) ---
            # Add logic here if needed to bias towards lines closer to the expected position

            if ratio > best_ratio:
                best_ratio = ratio
                best_match_line = original_official  # Store the *original* official line text
                best_match_idx = idx

        # Create a new segment dictionary (copy to avoid modifying original)
        new_seg = seg.copy()

        # If match confidence is above threshold, replace recognized text
        if best_ratio >= LYRICS_ALIGNMENT_THRESHOLD and best_match_idx != -1:
            new_seg["text"] = best_match_line
            new_seg["aligned"] = True  # Add flag indicating alignment
            new_seg["confidence"] = round(best_ratio, 2)  # Store alignment score
            used_official_indices.add(best_match_idx)  # Mark this official line as used
            num_aligned += 1
            # logger.debug(f"Aligned segment (Conf: {best_ratio:.2f}): '{recognized_text}' -> '{best_match_line}'")
        else:
            # Keep original text if confidence is too low or no suitable unused match found
            new_seg["aligned"] = False
            new_seg["confidence"] = round(best_ratio, 2)  # Store the best score found, even if below threshold
            # logger.debug(f"Segment NOT aligned (Best Conf: {best_ratio:.2f}): '{recognized_text}'")

        aligned_segments.append(new_seg)

    logger.info(f"Alignment complete. {num_aligned} segments were aligned with official lyrics.")
    # Note: Final cleaning (like force_only_words) is usually applied *after* alignment.
    return aligned_segments
