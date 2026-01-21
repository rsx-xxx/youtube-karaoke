# File: backend/api/v1/routes/process.py
"""Video processing endpoints."""
import asyncio
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, File, UploadFile, Depends

from ....schemas import ProcessRequest, JobResponse
from ....config import settings
from ....processing import process_video_job
from ....utils.progress_manager import job_tasks, get_manager
from ..dependencies import progress_service_dep, ProgressServiceDep

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/process", response_model=JobResponse, status_code=202)
async def start_processing(
    request: ProcessRequest,
    progress_service: ProgressServiceDep = Depends(progress_service_dep)
) -> JobResponse:
    """
    Start processing a YouTube video into karaoke format.

    - **url**: YouTube URL or search query
    - **language**: Transcription language (default: auto)
    - **subtitle_position**: Position of subtitles (top/bottom)
    - **generate_subtitles**: Whether to add lyrics/subtitles
    - **custom_lyrics**: Optional user-provided lyrics
    - **pitch_shifts**: Optional per-stem pitch adjustments
    - **final_subtitle_size**: Font size for subtitles
    """
    url = request.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Field 'url' is empty")

    job_id = str(uuid.uuid4())

    logger.info(
        f"Job {job_id} • url='{url[:80]}' gen_subs={request.generate_subtitles} "
        f"lang={request.language} font_size={request.final_subtitle_size.value}"
    )

    # Initialize job progress using proper API
    manager = get_manager()
    manager.create_job(job_id, "Job accepted, preparing...")

    # Create processing task
    task = asyncio.create_task(
        process_video_job(
            job_id=job_id,
            url_or_search=url,
            language=request.language,
            sub_pos=request.subtitle_position.value,
            gen_subs=request.generate_subtitles,
            selected_lyrics=request.custom_lyrics,
            pitch_shifts=request.pitch_shifts,
            final_font_size=request.final_subtitle_size.value,
        )
    )
    manager.register_task(job_id, task)
    job_tasks[job_id] = task

    return JobResponse(job_id=job_id)


@router.post("/process-local-file", response_model=JobResponse, status_code=202)
async def start_processing_local_file(
    file: UploadFile = File(..., description="Video/audio file to process"),
    language: str = "auto",
    subtitle_position: str = "bottom",
    generate_subtitles: bool = True,
    custom_lyrics: str = None,
    final_subtitle_size: int = 30,
    progress_service: ProgressServiceDep = Depends(progress_service_dep)
) -> JobResponse:
    """
    Process a locally uploaded video/audio file into karaoke format.
    """
    job_id = str(uuid.uuid4())

    # Create temp directory for upload
    upload_temp_dir = settings.DOWNLOADS_DIR / job_id
    upload_temp_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize filename
    original_filename = file.filename or "uploaded_file"
    safe_stem = "".join(c if c.isalnum() else '_' for c in Path(original_filename).stem)
    safe_filename = f"{safe_stem}{Path(original_filename).suffix}"
    local_file_path = upload_temp_dir / safe_filename

    try:
        with open(local_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        logger.error(f"Failed to save uploaded file {local_file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {e}")
    finally:
        await file.close()

    logger.info(f"Job {job_id} • Local file '{local_file_path.name}' uploaded for processing.")

    # Initialize job progress using proper API
    manager = get_manager()
    manager.create_job(job_id, "Local file job accepted, preparing...")

    # Create processing task
    task = asyncio.create_task(
        process_video_job(
            job_id=job_id,
            url_or_search=None,
            local_file_path_str=str(local_file_path),
            language=language,
            sub_pos=subtitle_position,
            gen_subs=generate_subtitles,
            selected_lyrics=custom_lyrics,
            pitch_shifts=None,
            final_font_size=final_subtitle_size,
        )
    )
    manager.register_task(job_id, task)
    job_tasks[job_id] = task

    return JobResponse(job_id=job_id)
