import html
import logging
import os
import re
from functools import lru_cache
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)
_HTTP = requests.Session()
_HTTP.headers["User-Agent"] = "yt-karaoke/1.0 (+github.com/yourrepo)"

_STOP = {
    "official", "video", "audio", "lyrics", "lyric", "vevo", "hd",
    "remastered", "feat", "ft", "featuring", "remix", "edit", "live",
    "cover", "visualizer", "visualiser",
}
_PARENS = re.compile(r"\([^)]*\)|\[[^]]*]|\{[^}]*}")
_SPACES = re.compile(r"\s{2,}")

def _clean_tokens(text: str) -> List[str]:
    text = _PARENS.sub(" ", text)
    text = re.sub(r"[^\w\s]", " ", text)
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
        r"^(?:\d+\s*contributors?|you might also like|embed|\d+k? embed)$", re.IGNORECASE
    )
    out: List[str] = []
    for ln in lines:
        ln = ln.strip()
        if not ln or junk.match(ln):
            continue
        out.append(ln)
    return out

class GeniusClient:
    API = "https://api.genius.com"
    WEB = "https://genius.com"

    def __init__(self, token: Optional[str] = None, *, hits: int = 15) -> None:
        # Import here to avoid circular imports and ensure settings are loaded
        from .config import settings
        token = token or settings.GENIUS_API_TOKEN
        self.enabled = bool(token)
        self._hits = max(1, min(hits, 20))
        self._token = token

        if self.enabled:
            _HTTP.headers["Authorization"] = f"Bearer {self._token}"
            log.info("Genius API client initialized with token.")
        else:
            log.warning("GENIUS_API_TOKEN not set — Genius integration will be disabled.")

    @lru_cache(maxsize=256)
    def search(self, title: str, artist: str | None = None) -> List[Dict]:
        if not self.enabled:
            return []

        cleaned_title = " ".join(_clean_tokens(title))

        # Extract primary artist name (first name before comma, typically the band/artist name)
        primary_artist = None
        if artist:
            # Split by comma and take first part (usually the main artist/band name)
            first_artist = artist.split(',')[0].strip()
            # Also handle " & " and " feat " separators
            first_artist = re.split(r'\s*[&]\s*|\s+feat\.?\s+|\s+ft\.?\s+', first_artist, flags=re.IGNORECASE)[0].strip()
            if first_artist:
                primary_artist = first_artist

        query_parts = []
        if primary_artist:
            cleaned_artist_tokens = _clean_tokens(primary_artist)
            if cleaned_artist_tokens:
                query_parts.extend(cleaned_artist_tokens)

        if not cleaned_title:
            if not query_parts:
                log.warning("Genius search: Both title and artist are empty after cleaning.")
                return []
            search_query = " ".join(query_parts)
        else:
            query_parts.append(cleaned_title)
            search_query = " ".join(query_parts)

        log.debug(f"Genius search: Original Title='{title}', Artist='{artist}', Primary Artist='{primary_artist}'. Cleaned Query='{search_query}'")

        if not search_query:
            return []

        queries_to_try = [search_query]
        if artist and cleaned_title != search_query :
            queries_to_try.append(cleaned_title)

        api_hits = []
        for q_idx, q_str in enumerate(queries_to_try):
            if not q_str: continue
            log.debug(f"Genius API search attempt #{q_idx+1} with query: '{q_str}' (asking for {self._hits} hits)")
            try:
                res = _HTTP.get(f"{self.API}/search", params={"q": q_str, "per_page": self._hits}, timeout=10)
                res.raise_for_status()
                response_json = res.json()
                current_hits = response_json.get("response", {}).get("hits", [])
                if current_hits:
                    api_hits = current_hits
                    log.debug(f"Found {len(api_hits)} hits with query '{q_str}'.")
                    break
            except requests.exceptions.RequestException as e:
                log.warning(f"Genius API search request failed for query '{q_str}': {e}")
                continue
            except ValueError as e:
                log.warning(f"Genius API search: Error decoding JSON response for query '{q_str}': {e}")
                continue

        if not api_hits:
            log.info(f"No Genius API hits found for title='{title}', artist='{artist}'.")
            return []

        out: List[Dict] = []
        for hit_data in api_hits:
            result_info = hit_data.get("result", {})
            if not result_info.get("id"):
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

    @lru_cache(maxsize=1024)
    def lyrics(self, song_id: int) -> str:
        if not self.enabled or not song_id:
            return ""

        song_url = f"{self.WEB}/songs/{song_id}"
        log.debug(f"Fetching lyrics from URL: {song_url}")

        try:
            response = _HTTP.get(song_url, timeout=15)
            response.raise_for_status()
            html_page = response.text
        except requests.exceptions.Timeout:
            log.error(f"Timeout while fetching lyrics for song ID {song_id} from {song_url}")
            return ""
        except requests.exceptions.HTTPError as http_err:
            log.error(f"HTTP error {http_err.response.status_code} fetching lyrics for song ID {song_id} from {song_url}")
            return ""
        except requests.exceptions.RequestException as req_err:
            log.error(f"Request failed while fetching lyrics for song ID {song_id} from {song_url}: {req_err}")
            return ""
        except Exception as exc:
            log.error(f"Unexpected error fetching lyrics page for song ID {song_id}: {exc}", exc_info=True)
            return ""

        if not html_page:
            log.warning(f"Lyrics page for song ID {song_id} was empty.")
            return ""

        soup = BeautifulSoup(html_page, "html.parser")
        lyrics_containers = soup.select("div[data-lyrics-container='true']")

        if not lyrics_containers:
            lyrics_containers = soup.select('div[class^="Lyrics__Container"], div[class*=" Lyrics__Container"]')
            if lyrics_containers:
                log.debug(f"Found lyrics using fallback selector for song ID {song_id}")
            else:
                log.warning(f"Lyrics container 'div[data-lyrics-container=true]' not found for song ID {song_id} on page {song_url}")
                return ""

        all_lines: List[str] = []
        seen_fragments = set()

        for container in lyrics_containers:
            for br_tag in container.find_all("br"):
                br_tag.replace_with("\n")
            container_text = container.get_text(separator='\n', strip=True)
            if container_text in seen_fragments and len(container_text) > 100:
                continue
            seen_fragments.add(container_text)
            current_lines = container_text.split('\n')
            for line in current_lines:
                line_unescaped = html.unescape(line.strip())
                cleaned_line = re.sub(r"^\s*\[[^\]]+\]\s*$", "", line_unescaped).strip()
                if cleaned_line:
                    all_lines.append(cleaned_line)

        if not all_lines:
            log.warning(f"No lyrics text extracted from containers for song ID {song_id}")
            return ""

        final_lyrics_text = "\n".join(_strip_garbage(all_lines)).strip()
        final_lyrics_text = re.sub(r"\d+\s*Contributors?\s*Lyrics", "", final_lyrics_text, flags=re.IGNORECASE).strip()

        if not final_lyrics_text:
            log.warning(f"Lyrics for song ID {song_id} became empty after all cleaning stages.")
        else:
            log.debug(f"Successfully extracted and cleaned lyrics for song ID {song_id}. Length: {len(final_lyrics_text)}")
        return final_lyrics_text