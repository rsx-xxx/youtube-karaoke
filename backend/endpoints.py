# File: backend/endpoints.py
import asyncio
import uuid
import logging
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, Query, Depends, WebSocketDisconnect
from fastapi.responses import JSONResponse

# Import functions and state from processing module
from processing import (
    process_video_job,
    get_progress,
    job_tasks,        # Dict of active asyncio tasks
    get_youtube_suggestions # Function for fetching suggestions
)
from utils.progress_manager import kill_job, progress_dict # Dict holding job progress info
# --- Setup Logger ---
logger = logging.getLogger(__name__)

# Create a separate router for API endpoints
router = APIRouter()

# --- Video Processing Endpoint ---
@router.post("/process", status_code=202) # 202 Accepted: request accepted, processing started
async def start_processing_endpoint(request: Request):
    """
    Accepts a video URL or search query, along with processing options,
    and initiates a background processing job.
    Returns a unique job_id for tracking progress via WebSocket.
    """
    try:
        data = await request.json()
    except Exception:
        logger.warning("Received invalid JSON in /process request body")
        raise HTTPException(status_code=400, detail="Invalid JSON body provided.")

    url_or_search = data.get("url", "").strip()
    if not url_or_search:
        logger.warning("/process request missing 'url' field")
        raise HTTPException(status_code=400, detail="Missing 'url' field (YouTube link or search query).")

    # Get parameters with default values and basic validation
    language = data.get("language", "en").lower() # Default to English
    subtitle_position = data.get("subtitle_position", "bottom").lower()
    generate_subtitles = data.get("generate_subtitles", True) # Default to generating subs

    if subtitle_position not in ["top", "bottom"]:
         logger.warning(f"Invalid subtitle_position received: {subtitle_position}")
         raise HTTPException(status_code=400, detail="Invalid 'subtitle_position'. Must be 'top' or 'bottom'.")
    # Add language validation if needed (e.g., check against supported list)

    # Generate a unique Job ID
    job_id = str(uuid.uuid4())
    logger.info(f"Received processing request. Assigning Job ID: {job_id}")
    logger.info(f"Job {job_id} Params: URL/Search='{url_or_search[:50]}...', Lang='{language}', SubPos='{subtitle_position}', GenSubs={generate_subtitles}")

    # Initialize job state immediately to avoid race conditions with WebSocket connections
    progress_dict[job_id] = {
        "progress": 0,
        "message": "Job accepted, preparing...", # Initial message
        "result": None,
        "is_step": True # Mark as a distinct step
    }

    # Start the background processing task (without awaiting its completion here)
    asyncio.create_task(
        process_video_job(job_id, url_or_search, language, subtitle_position, generate_subtitles)
    )
    logger.info(f"Background task created for Job ID: {job_id}")

    # Return the job ID to the client
    return JSONResponse({"job_id": job_id})

# --- Job Cancellation Endpoint ---
# Changed to POST as it modifies server state (cancels a job)
@router.post("/cancel_job", status_code=200)
async def cancel_job_endpoint(job_id: str = Query(..., description="The ID of the job to cancel")):
    """
    Attempts to cancel a running processing job identified by its job_id.
    """
    logger.info(f"Received cancellation request for Job ID: {job_id}")
    # Check if the job is currently active or has recent progress data
    if job_id in job_tasks or job_id in progress_dict:
        try:
             # Call the cancellation function from processing.py
             kill_job(job_id)
             logger.info(f"Cancellation processed for Job ID: {job_id}")
             return JSONResponse({"status": "cancellation_requested", "job_id": job_id})
        except Exception as e:
             # Log unexpected errors during the cancellation process itself
             logger.error(f"Error trying to execute cancellation for job {job_id}: {e}", exc_info=True)
             raise HTTPException(status_code=500, detail=f"Internal error during cancellation request for job {job_id}.")
    else:
        # Job ID not found in active tasks or recent progress
        logger.warning(f"Cancellation request for unknown or already completed/cleaned Job ID: {job_id}")
        raise HTTPException(status_code=404, detail=f"Job with ID '{job_id}' not found or already completed.")

# --- Suggestion Endpoint ---
@router.get("/suggestions", response_model=List[Dict[str, Any]])
async def get_suggestions_endpoint(q: str = Query(..., min_length=2, description="Search query or YouTube link")):
    """
    Provides YouTube video suggestions based on the input query 'q'.
    Fetches data using yt-dlp (via processing.py).
    """
    # Query parameter 'q' is required and validated by FastAPI's Query `...` and `min_length`
    logger.info(f"Received suggestion request for query: '{q[:50]}...'")

    try:
        suggestions = await get_youtube_suggestions(q, max_results=7) # Fetch up to 7 suggestions
        logger.info(f"Returning {len(suggestions)} suggestions for query: '{q[:50]}...'")
        return suggestions
    except Exception as e:
        # Log the error for server diagnostics
        logger.error(f"Failed to fetch suggestions for query '{q}': {e}", exc_info=True)
        # Return an empty list for a more graceful frontend experience instead of raising 500
        # raise HTTPException(status_code=500, detail="Failed to fetch suggestions from YouTube.")
        return []

# --- Progress Tracking WebSocket ---
@router.websocket("/ws/progress/{job_id}")
async def websocket_progress_endpoint(websocket: WebSocket, job_id: str):
    """
    WebSocket endpoint for streaming job progress updates to the client.
    Clients connect using the job_id obtained from the /process endpoint.
    """
    await websocket.accept()
    logger.info(f"[WS] Client connected for Job ID: {job_id}")

    # Check if the job ID is known immediately upon connection
    if job_id not in progress_dict and job_id not in job_tasks:
         logger.warning(f"[WS] Connection attempt for unknown or already completed/cleaned Job ID: {job_id}")
         await websocket.send_json({
             "progress": 0, # Indicate no progress
             "message": "Job not found. It might be completed, cancelled, or never existed.",
             "is_step": False,
             "error": True # Add an error flag
         })
         await websocket.close(code=1008) # Policy Violation (or custom code like 4004 for Not Found)
         logger.info(f"[WS] Closed connection for unknown Job ID: {job_id}")
         return

    # Send initial state if available
    initial_data = get_progress(job_id)
    if initial_data:
        try:
            await websocket.send_json(initial_data)
            logger.debug(f"[WS] Sent initial state for job {job_id}: {initial_data}")
        except WebSocketDisconnect:
             logger.info(f"[WS] Client for job {job_id} disconnected immediately after connect.")
             return # Exit if client disconnected right away
        except Exception as e:
             logger.error(f"[WS] Error sending initial state for job {job_id}: {e}", exc_info=True)
             # Decide whether to close or continue

    last_sent_progress = initial_data.get("progress", -1) if initial_data else -1
    last_sent_message = initial_data.get("message", "") if initial_data else ""

    try:
        while True:
            # Get current progress data for the job
            data = get_progress(job_id)

            if data is None:
                 # This could happen if the job finishes and gets cleaned up *between* checks
                 logger.warning(f"[WS] Progress data for job {job_id} disappeared unexpectedly. Assuming completion/removal.")
                 # Send a final message indicating data loss or completion
                 try:
                    await websocket.send_json({
                         "progress": 100,
                         "message": "Job completed or data removed.",
                         "is_step": False
                    })
                 except WebSocketDisconnect:
                     pass # Client already gone
                 break # Exit the loop

            current_progress = data.get("progress", 0)
            current_message = data.get("message", "")

            # Send update only if progress or message has changed significantly
            # Avoid flooding with identical messages
            if current_progress > last_sent_progress or current_message != last_sent_message:
                 try:
                     await websocket.send_json(data)
                     logger.debug(f"[WS] Sent update for job {job_id}: P={current_progress}%, M='{current_message}'")
                     last_sent_progress = current_progress
                     last_sent_message = current_message
                 except WebSocketDisconnect:
                     logger.info(f"[WS] Client disconnected while sending update for job {job_id}.")
                     break # Exit loop if client disconnects

            # Check for job completion condition (progress >= 100)
            if current_progress >= 100:
                logger.info(f"[WS] Job {job_id} reached 100%. Closing WebSocket connection.")
                break # Exit the loop

            # Wait before the next progress check to avoid busy-waiting
            await asyncio.sleep(0.8) # Check interval (e.g., 800ms)

    except WebSocketDisconnect:
        # Handle client-initiated disconnect gracefully
        logger.info(f"[WS] Client disconnected for Job ID: {job_id}")
    except Exception as e:
        # Handle unexpected errors during the WebSocket loop
        logger.error(f"[WS] Unexpected error in progress loop for job_id={job_id}: {type(e).__name__} - {e}", exc_info=True)
    finally:
        # Ensure WebSocket connection is closed cleanly from the server side
        try:
            await websocket.close()
            logger.info(f"[WS] Connection definitively closed for Job ID: {job_id}")
        except RuntimeError as e:
             # Ignore benign errors like 'WebSocket is already closed'
             if "WebSocket is already closed" not in str(e):
                  logger.warning(f"[WS] Error during final WebSocket close for {job_id}: {e}")
        # Optional: Could perform final cleanup here if needed,
        # e.g., removing progress_dict entry if it shouldn't persist after disconnect.
        # However, current design lets it persist for potential later checks.