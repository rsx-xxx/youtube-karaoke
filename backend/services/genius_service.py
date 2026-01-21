# File: backend/services/genius_service.py
"""Service for Genius lyrics fetching and matching."""
import asyncio
import logging
import re
import unicodedata
from typing import List, Optional

from rapidfuzz.fuzz import WRatio

from ..genius_client import GeniusClient
from ..schemas.responses import GeniusCandidate

logger = logging.getLogger(__name__)

# Regex patterns for text normalization
_RX_NONWORD = re.compile(r"[^\w\s]")
_RX_WS = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    """Normalize text for fuzzy matching."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = _RX_NONWORD.sub(" ", text)
    return _RX_WS.sub(" ", text).strip()


class GeniusService:
    """Service for fetching and processing Genius lyrics."""

    MIN_ACCEPTABLE_SCORE = 50
    MAX_CANDIDATES = 7

    def __init__(self, client: Optional[GeniusClient] = None, max_hits: int = 15):
        self._client = client or GeniusClient(hits=max_hits)

    @property
    def enabled(self) -> bool:
        """Check if Genius API is enabled."""
        return self._client.enabled

    async def search_candidates(
        self,
        title: str,
        artist: str = ""
    ) -> List[GeniusCandidate]:
        """
        Search for lyrics candidates matching the given title and artist.

        Returns sorted list of candidates with lyrics.
        """
        if not self.enabled:
            raise RuntimeError("Genius integration is disabled on server")

        # Fetch initial hits from Genius API
        hits = await asyncio.to_thread(self._client.search, title, artist)
        if not hits:
            logger.info(f"No Genius API hits for title='{title}', artist='{artist}'")
            return []

        # Score and sort hits
        scored_hits = self._score_hits(hits, title, artist)

        # Filter candidates above threshold
        candidates_to_fetch = self._filter_candidates(scored_hits)

        # Fetch lyrics for each candidate
        return await self._fetch_lyrics_for_candidates(candidates_to_fetch)

    def _score_hits(
        self,
        hits: List[dict],
        query_title: str,
        query_artist: str
    ) -> List[tuple]:
        """Score hits based on title and artist similarity."""
        title_norm = _normalize_text(query_title)
        artist_norm = _normalize_text(query_artist)

        scored = []
        for hit in hits:
            title_score = WRatio(_normalize_text(hit["title"]), title_norm)
            artist_score = WRatio(_normalize_text(hit["artist"]), artist_norm) if artist_norm else 0
            total = round(0.7 * title_score + 0.3 * artist_score)
            scored.append((total, hit))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def _filter_candidates(self, scored_hits: List[tuple]) -> List[dict]:
        """Filter scored hits to get candidates worth fetching lyrics for."""
        candidates = []

        for score, hit_data in scored_hits:
            if len(candidates) >= self.MAX_CANDIDATES:
                break
            if score >= self.MIN_ACCEPTABLE_SCORE:
                candidates.append(hit_data)

        # If no candidates meet threshold, take the best one
        if not candidates and scored_hits:
            candidates.append(scored_hits[0][1])

        return candidates

    async def _fetch_lyrics_for_candidates(
        self,
        candidates: List[dict]
    ) -> List[GeniusCandidate]:
        """Fetch lyrics for each candidate from Genius."""
        results = []

        for hit_data in candidates:
            try:
                lyrics_text = await asyncio.to_thread(
                    self._client.lyrics,
                    hit_data["id"]
                )
                if not lyrics_text:
                    continue

                results.append(GeniusCandidate(
                    title=hit_data["title"],
                    artist=hit_data.get("artist"),
                    lyrics=lyrics_text.strip(),
                    url=hit_data.get("url")
                ))

                if len(results) >= self.MAX_CANDIDATES:
                    break

            except Exception as e:
                logger.warning(f"Failed to fetch lyrics for {hit_data.get('title')}: {e}")
                continue

        return results
