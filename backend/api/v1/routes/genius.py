# File: backend/api/v1/routes/genius.py
"""Genius lyrics search endpoint."""
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query, Depends

from ....schemas import GeniusCandidate
from ..dependencies import genius_service_dep, GeniusServiceDep

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/genius_candidates", response_model=List[GeniusCandidate])
async def get_genius_candidates(
    title: str = Query(..., description="Song title to search"),
    artist: str = Query("", description="Artist name (optional)"),
    genius_service: GeniusServiceDep = Depends(genius_service_dep)
) -> List[GeniusCandidate]:
    """
    Search Genius for lyrics matching the given title and artist.

    Returns a list of potential matches with full lyrics text.
    """
    if not genius_service.enabled:
        raise HTTPException(
            status_code=503,
            detail="Genius integration disabled on server"
        )

    try:
        candidates = await genius_service.search_candidates(title, artist)

        if not candidates:
            logger.info(f"No lyrics found for: '{title}' - '{artist}'")

        return candidates

    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Genius search error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to search Genius")
