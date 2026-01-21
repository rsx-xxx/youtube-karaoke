# File: backend/api/v1/routes/progress.py
"""Job progress tracking endpoints."""
import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketState

from ....utils.progress_manager import get_manager
from ..dependencies import progress_service_dep, ProgressServiceDep

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/progress/{job_id}")
async def websocket_progress(websocket: WebSocket, job_id: str):
    """
    WebSocket endpoint for real-time job progress updates.

    Sends progress updates as JSON messages until job completes.
    """
    await websocket.accept()
    manager = get_manager()

    # Check if job exists
    if not manager.job_exists(job_id):
        await websocket.send_json({
            "progress": 100,
            "message": "Job not found",
            "error": True
        })
        await websocket.close(code=1008)
        return

    # Send initial state
    last_state: Optional[Dict[str, Any]] = manager.get_progress(job_id)
    if last_state:
        await websocket.send_json(last_state)
    else:
        await websocket.send_json({"progress": 0, "message": "Initializing...", "job_id": job_id})

    last_progress = last_state.get("progress", 0) if last_state else 0
    last_message = last_state.get("message", "") if last_state else ""

    try:
        while True:
            await asyncio.sleep(0.3)

            state = manager.get_progress(job_id)
            if state is None:
                break

            # Send update if state changed (compare key fields)
            current_progress = state.get("progress", 0)
            current_message = state.get("message", "")

            if current_progress != last_progress or current_message != last_message:
                await websocket.send_json(state)
                last_progress = current_progress
                last_message = current_message

            # Exit when complete
            if current_progress >= 100:
                break

    except WebSocketDisconnect:
        logger.debug(f"WebSocket disconnected for job {job_id}")
    finally:
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()


@router.post("/cancel_job", status_code=200)
@router.get("/cancel_job", status_code=200)
async def cancel_job(
    job_id: str = Query(..., description="Job ID to cancel"),
    progress_service: ProgressServiceDep = Depends(progress_service_dep)
):
    """
    Cancel a running job.

    Returns confirmation of cancellation request.
    """
    if not progress_service.job_exists(job_id):
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    try:
        progress_service.cancel_job(job_id)
        return JSONResponse({
            "status": "cancellation_requested",
            "job_id": job_id
        })
    except Exception as e:
        logger.error(f"Cancel error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal cancellation error")
