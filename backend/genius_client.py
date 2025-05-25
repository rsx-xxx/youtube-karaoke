"""
Genius REST-API wrapper без внешних SDK.

• search(title, artist)  → list[{id,title,artist,url}]
• lyrics(song_id)        → plain-text lyrics   (HTML → Clean)

Требует переменной окружения GENIUS_API_TOKEN или передачи токена при
инициализации.
"""
from __future__ import annotations

import html
import logging
import os
import re
from functools import lru_cache
from typing import Dict, List, Optional

import requests # Ensure requests is imported
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)
_HTTP = requests.Session()
_HTTP.headers["User-Agent"] = "yt-karaoke/1.0 (+github.com/yourrepo)" # Consider making this configurable or more generic

# ─────────────────────────── helpers ───────────────────────────── #
_STOP = {
    "official",
    "video",
    "audio",
    "lyrics",
    "lyric",
    "vevo",
    "hd",
    "remastered",
    "feat",
    "ft",
    "featuring",
    "remix",
    "edit",
    "live",
    "cover",
    "visualizer",
    "visualiser",
}
_PARENS = re.compile(r"\([^)]*\)|\[[^]]*]|\{[^}]*}")
_SPACES = re.compile(r"\s{2,}")


def _clean_tokens(text: str) -> List[str]:
    text = _PARENS.sub(" ", text)
    text = re.sub(r"[^\w\s]", " ", text) # Keep apostrophes if they are considered part of words by \w
    text = _SPACES.sub(" ", text).strip().lower()
    out, seen = [], set()
    for tok in text.split():
        if tok in _STOP or tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out


def _strip_garbage(lines: List[str]) -> List[str]:
    junk = re.compile(
        r"^(?:\d+\s*contributors?|you might also like|embed|\d+k? embed)$", re.IGNORECASE # Use IGNORECASE
    )
    out: List[str] = []
    for ln in lines:
        ln = ln.strip()
        if not ln or junk.match(ln): # Simpler check
            continue
        out.append(ln)
    return out


# ───────────────────────── main wrapper ───────────────────────── #
class GeniusClient:
    API = "https://api.genius.com"
    WEB = "https://genius.com" # Base URL for song pages

    def __init__(self, token: Optional[str] = None, *, hits: int = 5) -> None:
        token = token or os.getenv("GENIUS_API_TOKEN")
        self.enabled = bool(token)
        self._hits = max(1, min(hits, 10)) # Ensure hits is within a reasonable range (e.g., 1-10)
        self._token = token

        if self.enabled:
            _HTTP.headers["Authorization"] = f"Bearer {self._token}"
        else:
            log.warning("GENIUS_API_TOKEN not set — Genius integration will be disabled.")

    # ------------------------------ search --------------------- #
    @lru_cache(maxsize=256)
    def search(self, title: str, artist: str | None = None) -> List[Dict]:
        if not self.enabled:
            return []

        # Clean search terms (artist can be None)
        cleaned_title = " ".join(_clean_tokens(title))
        query_parts = []
        if artist:
            cleaned_artist_tokens = _clean_tokens(artist)
            if cleaned_artist_tokens:
                 query_parts.extend(cleaned_artist_tokens)

        if not cleaned_title: # If title becomes empty after cleaning, maybe just search by artist if available
            if not query_parts: # No artist either
                 log.warning("Genius search: Both title and artist are empty after cleaning.")
                 return []
            search_query = " ".join(query_parts)
        else:
            query_parts.append(cleaned_title)
            search_query = " ".join(query_parts)


        log.debug(f"Genius search: Original Title='{title}', Artist='{artist}'. Cleaned Query='{search_query}'")

        if not search_query: # Final check if query is empty
            return []

        # Simplified query attempts: full, then just title if artist was part of it
        queries_to_try = [search_query]
        if artist and cleaned_title != search_query : # If artist was part of the first query
            queries_to_try.append(cleaned_title)


        api_hits = []
        for q_idx, q_str in enumerate(queries_to_try):
            if not q_str: continue
            log.debug(f"Genius API search attempt #{q_idx+1} with query: '{q_str}'")
            try:
                res = _HTTP.get(f"{self.API}/search", params={"q": q_str, "per_page": self._hits}, timeout=10) # Added timeout
                res.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
                response_json = res.json()
                current_hits = response_json.get("response", {}).get("hits", [])
                if current_hits:
                    api_hits = current_hits
                    log.debug(f"Found {len(api_hits)} hits with query '{q_str}'.")
                    break # Found hits, stop trying other queries
            except requests.exceptions.RequestException as e:
                log.warning(f"Genius API search request failed for query '{q_str}': {e}")
                continue # Try next query if any
            except ValueError as e: # JSON decoding error
                log.warning(f"Genius API search: Error decoding JSON response for query '{q_str}': {e}")
                continue


        if not api_hits:
            log.info(f"No Genius API hits found for title='{title}', artist='{artist}'.")
            return []

        out: List[Dict] = []
        for hit_data in api_hits:
            result_info = hit_data.get("result", {})
            if not result_info.get("id"): # Skip if no ID
                continue
            primary_artist_info = result_info.get("primary_artist", {})
            out.append(
                {
                    "id": result_info.get("id"),
                    "title": result_info.get("title", result_info.get("full_title", "")).strip(),
                    "artist": primary_artist_info.get("name", artist or "").strip(),
                    "url": result_info.get("url", "").strip(),
                }
            )
        return out

    # ------------------------------ lyrics --------------------- #
    @lru_cache(maxsize=1024) # Increased cache for lyrics
    def lyrics(self, song_id: int) -> str:
        """
        HTML → plain текст.
        Genius API не отдаёт лирику напрямую, поэтому тянем страницу
        https://genius.com/songs/{id} и вытаскиваем элементы
        `<div data-lyrics-container="true">`.
        """
        if not self.enabled or not song_id:
            return ""

        song_url = f"{self.WEB}/songs/{song_id}" # Use the base WEB URL
        log.debug(f"Fetching lyrics from URL: {song_url}")

        try:
            # Use a timeout for the request
            response = _HTTP.get(song_url, timeout=15) # Increased timeout
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            html_page = response.text
        except requests.exceptions.Timeout:
            log.error(f"Timeout while fetching lyrics for song ID {song_id} from {song_url}")
            return ""
        except requests.exceptions.HTTPError as http_err:
            log.error(f"HTTP error {http_err.response.status_code} fetching lyrics for song ID {song_id} from {song_url}")
            return ""
        except requests.exceptions.RequestException as req_err: # Catch other network related errors
            log.error(f"Request failed while fetching lyrics for song ID {song_id} from {song_url}: {req_err}")
            return ""
        except Exception as exc: # Catch any other unexpected errors
            log.error(f"Unexpected error fetching lyrics page for song ID {song_id}: {exc}", exc_info=True)
            return ""


        if not html_page:
            log.warning(f"Lyrics page for song ID {song_id} was empty.")
            return ""

        soup = BeautifulSoup(html_page, "html.parser")
        # Genius often uses multiple divs with this attribute now, sometimes nested.
        # Find all, then process to avoid missing parts or getting duplicates.
        lyrics_containers = soup.select("div[data-lyrics-container='true']")

        if not lyrics_containers:
            # Fallback for different structures (seen in some cases like Google Cache)
            lyrics_containers = soup.select('div[class^="Lyrics__Container"], div[class*=" Lyrics__Container"]')
            if lyrics_containers:
                log.debug(f"Found lyrics using fallback selector for song ID {song_id}")
            else:
                log.warning(f"Lyrics container 'div[data-lyrics-container=true]' not found for song ID {song_id} on page {song_url}")
                return ""

        all_lines: List[str] = []
        seen_fragments = set() # To handle potential duplicate fragments from nested divs

        for container in lyrics_containers:
            # Replace <br> tags with newlines for proper splitting
            for br_tag in container.find_all("br"):
                br_tag.replace_with("\n")

            # Get text, split into lines, and process each line
            # .get_text(separator='\n', strip=True) helps with initial cleaning
            container_text = container.get_text(separator='\n', strip=True)

            # Avoid processing the same large block of text if nested divs repeat content
            if container_text in seen_fragments and len(container_text) > 100: # Heuristic for repeated blocks
                continue
            seen_fragments.add(container_text)

            current_lines = container_text.split('\n')
            for line in current_lines:
                # Unescape HTML entities like &amp;
                line_unescaped = html.unescape(line.strip())
                # Remove common [Verse], [Chorus] type headers often left by scrapers or Genius itself
                # This regex also handles leading/trailing whitespace around the brackets
                cleaned_line = re.sub(r"^\s*\[[^\]]+\]\s*$", "", line_unescaped).strip()

                if cleaned_line: # Add if not empty after cleaning
                    all_lines.append(cleaned_line)

        if not all_lines:
            log.warning(f"No lyrics text extracted from containers for song ID {song_id}")
            return ""

        # Final cleaning of collected lines (e.g., common junk footers from Genius)
        final_lyrics_text = "\n".join(_strip_garbage(all_lines)).strip()

        # Additional check for common leftover headers that might not be at start/end of line
        # Example: "1 ContributorLyrics" or "You might also likeEmbed" - _strip_garbage handles some of these
        # This is more of a fine-tuning step
        final_lyrics_text = re.sub(r"\d+\s*Contributors?\s*Lyrics", "", final_lyrics_text, flags=re.IGNORECASE).strip()

        if not final_lyrics_text:
             log.warning(f"Lyrics for song ID {song_id} became empty after all cleaning stages.")
        else:
            log.debug(f"Successfully extracted and cleaned lyrics for song ID {song_id}. Length: {len(final_lyrics_text)}")

        return final_lyrics_text