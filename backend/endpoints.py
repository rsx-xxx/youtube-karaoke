"""
backend.endpoints
~~~~~~~~~~~~~~~~~
FastAPI routes: job processing, YouTube-→Genius suggestions, progress WS, cancel.
"""
from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketState

from genius_client import GeniusClient
from rapidfuzz.fuzz import WRatio

# ── internal imports (dual-mode: package / script) ────────────────────────
try:
    from .processing import process_video_job, get_progress, job_tasks
    from .utils.progress_manager import kill_job, progress_dict
    from .core.downloader import get_youtube_suggestions
except ImportError:                     # fallback for “python backend/app.py”
    from processing import process_video_job, get_progress, job_tasks       # type: ignore
    from utils.progress_manager import kill_job, progress_dict              # type: ignore
    from core.downloader import get_youtube_suggestions                     # type: ignore

log = logging.getLogger(__name__)
router = APIRouter()
_genius = GeniusClient()

# ──────────────────────────── Pydantic models ─────────────────────────── #
from pydantic import BaseModel, Field, field_validator  # noqa: E402


class ProcessRequest(BaseModel):
    url: str = Field(..., description="YouTube URL or search query")
    language: str = Field("auto", description="Transcription language or 'auto'")
    subtitle_position: str = Field("bottom", description="'top' or 'bottom'")
    generate_subtitles: bool = Field(True, description="Add lyrics/subtitles")
    custom_lyrics: Optional[str] = Field(
        None, description="User-provided full lyrics (overrides Genius)"
    )
    pitch_shifts: Optional[Dict[str, float]] = Field(
        None, description="Per-stem semitone shifts, e.g. {'vocals': 2}"
    )
    final_subtitle_size: int = Field(
        30, ge=10, le=100, description="Font size for final subtitles (px)"
    )

    @field_validator("subtitle_position")
    @classmethod
    def _pos_ok(cls, v: str) -> str:
        if v not in {"top", "bottom"}:
            raise ValueError("subtitle_position must be 'top' or 'bottom'")
        return v

    @field_validator("pitch_shifts")
    @classmethod
    def _validate_shifts(cls, shifts: Optional[Dict[str, float]]):
        if shifts is None:
            return None
        allowed = {"vocals", "instrumental", "drums", "bass", "other"}
        out: Dict[str, float] = {}
        for stem, val in shifts.items():
            stem_l = stem.lower()
            if stem_l not in allowed:
                log.warning("Ignoring unknown stem '%s'", stem)
                continue
            if not isinstance(val, (int, float)):
                raise ValueError(f"Shift for '{stem}' must be numeric")
            if not -24 <= val <= 24:
                raise ValueError(f"Shift {val} for '{stem}' outside -24…24")
            out[stem_l] = float(val)
        return out or None

    @field_validator("final_subtitle_size")
    @classmethod
    def _size_ok(cls, v: int) -> int:
        if v not in {24, 30, 36, 42}:
            raise ValueError("final_subtitle_size must be 24/30/36/42")
        return v


class GeniusCandidate(BaseModel):
    title: str
    artist: Optional[str] = None
    lyrics: str
    url: Optional[str] = None


# ───────────────────────────────────────────────────────────────────────── #
# Helper: lightweight normalizer
# ───────────────────────────────────────────────────────────────────────── #
_RX_NONWORD = re.compile(r"[^\w\s]")
_RX_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = _RX_NONWORD.sub(" ", text)
    return _RX_WS.sub(" ", text).strip()


# ───────────────────────────── /process (unchanged) ───────────────────── #
@router.post("/process", status_code=202)
async def start_processing(req: ProcessRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(400, "Field 'url' is empty")

    job_id = str(uuid.uuid4())
    log.info(
        "Job %s • url='%s' gen_subs=%s lang=%s",
        job_id,
        url[:80],
        req.generate_subtitles,
        req.language,
    )

    progress_dict[job_id] = {
        "progress": 0,
        "message": "Job accepted, preparing…",
        "result": None,
        "is_step_start": True,
        "job_id": job_id,
    }

    job_tasks[job_id] = asyncio.create_task(
        process_video_job(
            job_id=job_id,
            url_or_search=url,
            language=req.language,
            sub_pos=req.subtitle_position,
            gen_subs=req.generate_subtitles,
            selected_lyrics=req.custom_lyrics,
            pitch_shifts=req.pitch_shifts,
            final_font_size=req.final_subtitle_size,
        )
    )
    return JSONResponse({"job_id": job_id})


# ─────────────────────────── /suggestions (unchanged) ─────────────────── #
@router.get("/suggestions", response_model=List[Dict[str, Any]])
async def suggestions(q: str = Query(..., min_length=1)):
    if not (query := q.strip()):
        raise HTTPException(400, "Query 'q' cannot be empty")
    try:
        return await get_youtube_suggestions(query)
    except Exception as exc:  # noqa: BLE001
        log.error("Suggestion fetch error: %s", exc, exc_info=True)
        return []


# ─────────────────────────── /ws/progress (unchanged) ─────────────────── #
@router.websocket("/ws/progress/{job_id}")
async def websocket_progress(ws: WebSocket, job_id: str):
    await ws.accept()
    if job_id not in progress_dict and job_id not in job_tasks:
        await ws.send_json({"progress": 100, "message": "Job not found", "error": True})
        await ws.close(code=1008)
        return

    last_state: Dict[str, Any] = progress_dict.get(job_id, {})
    await ws.send_json({**last_state, "job_id": job_id})

    try:
        while True:
            await asyncio.sleep(0.3)
            state = progress_dict.get(job_id)
            if state is None:
                break
            if state != last_state:
                await ws.send_json({**state, "job_id": job_id})
                last_state = state
            if state.get("progress", 0) >= 100:
                break
    except WebSocketDisconnect:
        pass
    finally:
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.close()


# ───────────────────────────── /cancel_job (unchanged) ────────────────── #
@router.post("/cancel_job", status_code=200)
@router.get("/cancel_job", status_code=200)
async def cancel(job_id: str = Query(...)):
    if job_id not in job_tasks and job_id not in progress_dict:
        raise HTTPException(404, f"Job '{job_id}' not found")
    try:
        kill_job(job_id)
        return JSONResponse({"status": "cancellation_requested", "job_id": job_id})
    except Exception as exc:  # noqa: BLE001
        log.error("Cancel error: %s", exc, exc_info=True)
        raise HTTPException(500, "Internal cancellation error")


# ─────────────────────── /genius_candidates (optimized) ───────────────── #
@router.get("/genius_candidates", response_model=List[GeniusCandidate])
async def genius_candidates(title: str, artist: str):
    """
    • Запрашивает до 5 хитов у Genius.
    • Считает fuzzy-баллы (WRatio 0-100) для title и artist.
    • Если лучший результат ≥85 **и** опережает 2-е место ≥10 — вернёт только его.
      И фронтенд сразу поставит его по-умолчанию.
    • Иначе вернёт 2-3 почти равных варианта.
    """
    if not _genius.enabled:
        raise HTTPException(503, "Genius integration disabled on server")

    hits = await asyncio.to_thread(_genius.search, title, artist)
    if not hits:
        raise HTTPException(404, "No results on Genius")

    q_title_norm = _norm(title)
    q_artist_norm = _norm(artist)

    scored: List[tuple[int, Dict]] = []
    for h in hits:
        t_score = WRatio(_norm(h["title"]), q_title_norm)
        a_score = WRatio(_norm(h["artist"]), q_artist_norm) if q_artist_norm else 0
        total = round(0.7 * t_score + 0.3 * a_score)  # 0-100
        scored.append((total, h))
    scored.sort(key=lambda x: x[0], reverse=True)

    best_score = scored[0][0]
    candidates = [scored[0]]
    # keep additional results only if score almost equal (±5)
    for s, h in scored[1:]:
        if best_score - s <= 5:
            candidates.append((s, h))
        else:
            break

    # if candidate #2 отстаёт >=10 — оставляем только top-1
    if len(candidates) > 1 and best_score - candidates[1][0] >= 10:
        candidates = candidates[:1]

    out: List[GeniusCandidate] = []
    for _, h in candidates:
        text = await asyncio.to_thread(_genius.lyrics, h["id"])
        if not text:
            continue
        out.append(
            GeniusCandidate(
                title=h["title"],
                artist=h["artist"],
                lyrics=text.strip(),
                url=h["url"] or None,
            )
        )

    if not out:
        raise HTTPException(404, "Lyrics not available for found songs")
    return out