from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, File, UploadFile, Form, Depends
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketState
from pydantic import BaseModel, Field, field_validator
import shutil

from genius_client import GeniusClient
from rapidfuzz.fuzz import WRatio
from config import settings

try:
    from .processing import process_video_job, get_progress, job_tasks
    from .utils.progress_manager import kill_job, progress_dict
    from .core.downloader import get_youtube_suggestions
except ImportError:
    from processing import process_video_job, get_progress, job_tasks
    from utils.progress_manager import kill_job, progress_dict
    from core.downloader import get_youtube_suggestions

log = logging.getLogger(__name__)
router = APIRouter()
_genius = GeniusClient(hits=15)

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

_RX_NONWORD = re.compile(r"[^\w\s]")
_RX_WS = re.compile(r"\s+")

def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = _RX_NONWORD.sub(" ", text)
    return _RX_WS.sub(" ", text).strip()

@router.post("/process", status_code=202)
async def start_processing(req: ProcessRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(400, "Field 'url' is empty")
    job_id = str(uuid.uuid4())
    log.info(
        "Job %s • url='%s' gen_subs=%s lang=%s font_size=%s",
        job_id, url[:80], req.generate_subtitles, req.language, req.final_subtitle_size
    )
    progress_dict[job_id] = {
        "progress": 0, "message": "Job accepted, preparing…",
        "result": None, "is_step_start": True, "job_id": job_id,
    }
    job_tasks[job_id] = asyncio.create_task(
        process_video_job(
            job_id=job_id, url_or_search=url, language=req.language,
            sub_pos=req.subtitle_position, gen_subs=req.generate_subtitles,
            selected_lyrics=req.custom_lyrics, pitch_shifts=req.pitch_shifts,
            final_font_size=req.final_subtitle_size,
        )
    )
    return JSONResponse({"job_id": job_id})

@router.get("/suggestions", response_model=List[Dict[str, Any]])
async def suggestions(q: str = Query(..., min_length=1)):
    if not (query := q.strip()):
        raise HTTPException(400, "Query 'q' cannot be empty")
    try:
        return await get_youtube_suggestions(query, max_results=10)
    except Exception as exc:
        log.error("Suggestion fetch error: %s", exc, exc_info=True)
        return []

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
            if state is None: break
            if state != last_state:
                await ws.send_json({**state, "job_id": job_id})
                last_state = state
            if state.get("progress", 0) >= 100: break
    except WebSocketDisconnect:
        pass
    finally:
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.close()

@router.post("/cancel_job", status_code=200)
@router.get("/cancel_job", status_code=200)
async def cancel(job_id: str = Query(...)):
    if job_id not in job_tasks and job_id not in progress_dict:
        raise HTTPException(404, f"Job '{job_id}' not found")
    try:
        kill_job(job_id)
        return JSONResponse({"status": "cancellation_requested", "job_id": job_id})
    except Exception as exc:
        log.error("Cancel error: %s", exc, exc_info=True)
        raise HTTPException(500, "Internal cancellation error")

@router.get("/genius_candidates", response_model=List[GeniusCandidate])
async def genius_candidates(title: str, artist: str):
    if not _genius.enabled:
        raise HTTPException(503, "Genius integration disabled on server")

    hits = await asyncio.to_thread(_genius.search, title, artist)
    if not hits:
        # Do not raise HTTPException here, return empty list to frontend
        # Frontend will show "No potential lyrics found"
        log.info(f"No Genius API hits for title='{title}', artist='{artist}'. Returning empty list to client.")
        return []

    q_title_norm = _norm(title)
    q_artist_norm = _norm(artist)
    scored: List[tuple[int, Dict]] = []
    for h in hits:
        t_score = WRatio(_norm(h["title"]), q_title_norm)
        a_score = WRatio(_norm(h["artist"]), q_artist_norm) if q_artist_norm else 0
        total = round(0.7 * t_score + 0.3 * a_score)
        scored.append((total, h))
    scored.sort(key=lambda x: x[0], reverse=True)

    MIN_ACCEPTABLE_SCORE = 50
    MAX_CANDIDATES_TO_PROCESS = 7
    
    candidates_to_fetch_lyrics_for = []
    for score_val, hit_data in scored:
        if len(candidates_to_fetch_lyrics_for) >= MAX_CANDIDATES_TO_PROCESS:
            break
        if score_val >= MIN_ACCEPTABLE_SCORE:
            candidates_to_fetch_lyrics_for.append(hit_data)
        elif not candidates_to_fetch_lyrics_for and len(scored) > 0 : # if no one meets threshold, take the best one
             candidates_to_fetch_lyrics_for.append(scored[0][1]) # add hit_data of the best one
             break


    out: List[GeniusCandidate] = []
    if not candidates_to_fetch_lyrics_for and scored: # If still empty, but had initial hits (e.g. all below threshold)
         # Try to fetch lyrics for the absolute top hit if it exists
         top_hit_if_any = scored[0][1]
         text = await asyncio.to_thread(_genius.lyrics, top_hit_if_any["id"])
         if text:
             out.append(GeniusCandidate(
                 title=top_hit_if_any["title"], artist=top_hit_if_any["artist"],
                 lyrics=text.strip(), url=top_hit_if_any["url"] or None
             ))
             if not out: # If even top one had no lyrics
                 log.info(f"Lyrics not available for top Genius hit for: '{title} - {artist}'.")
                 return [] # Return empty if top hit has no lyrics
             return out # Return just the top one


    for h_data in candidates_to_fetch_lyrics_for:
        text = await asyncio.to_thread(_genius.lyrics, h_data["id"])
        if not text:
            continue
        out.append(
            GeniusCandidate(
                title=h_data["title"], artist=h_data["artist"],
                lyrics=text.strip(), url=h_data["url"] or None,
            )
        )
        if len(out) >= MAX_CANDIDATES_TO_PROCESS: # Redundant check, but safe
            break
            
    if not out:
        log.info(f"Lyrics not available for any sufficiently matching Genius songs for: '{title} - {artist}'.")
        return [] # Return empty list if no lyrics found for any candidate

    return out


class LocalProcessRequestForm(BaseModel):
    language: str = "auto"
    subtitle_position: str = "bottom"
    generate_subtitles: bool = True
    custom_lyrics: Optional[str] = None
    final_subtitle_size: int = 30

@router.post("/process-local-file", status_code=202)
async def start_processing_local_file(
        file: UploadFile = File(...),
        form_data: ProcessRequest = Depends(ProcessRequest)
):
    job_id = str(uuid.uuid4())
    upload_temp_dir = settings.DOWNLOADS_DIR / job_id
    upload_temp_dir.mkdir(parents=True, exist_ok=True)
    original_filename = file.filename if file.filename else "uploaded_file"
    safe_filename_stem = "".join(c if c.isalnum() else '_' for c in Path(original_filename).stem)
    safe_filename = f"{safe_filename_stem}{Path(original_filename).suffix}"
    local_file_path = upload_temp_dir / safe_filename

    try:
        with open(local_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        log.error(f"Failed to save uploaded file {local_file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {e}")
    finally:
        await file.close()

    log.info(f"Job {job_id} • Local file '{local_file_path.name}' uploaded for processing.")
    progress_dict[job_id] = {
        "progress": 0, "message": "Local file job accepted, preparing…",
        "result": None, "is_step_start": True, "job_id": job_id
    }
    job_tasks[job_id] = asyncio.create_task(
        process_video_job(
            job_id=job_id, url_or_search=None,
            local_file_path_str=str(local_file_path),
            language=form_data.language,
            sub_pos=form_data.subtitle_position,
            gen_subs=form_data.generate_subtitles,
            selected_lyrics=form_data.custom_lyrics,
            pitch_shifts=form_data.pitch_shifts,
            final_font_size=form_data.final_subtitle_size
        )
    )
    return {"job_id": job_id}