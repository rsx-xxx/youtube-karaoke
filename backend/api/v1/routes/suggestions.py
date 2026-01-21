# File: backend/api/v1/routes/suggestions.py
"""YouTube search suggestions endpoint."""
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query

from ....schemas import SuggestionItem
from ....core.downloader import get_youtube_suggestions

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/suggestions", response_model=List[SuggestionItem])
async def get_suggestions(
    q: str = Query(..., min_length=1, description="Search query")
) -> List[SuggestionItem]:
    """
    Get YouTube video suggestions for a search query.

    Returns a list of matching videos with titles, thumbnails, and URLs.
    """
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query 'q' cannot be empty")

    try:
        results = await get_youtube_suggestions(query, max_results=10)
        return [SuggestionItem(**item) for item in results]
    except Exception as e:
        logger.error(f"Suggestion fetch error: {e}", exc_info=True)
        return []
