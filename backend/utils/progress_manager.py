# File: backend/utils/progress_manager.py
import asyncio
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# --- Global State for Job Tracking (Consider alternatives for large scale) ---
progress_dict: Dict[str, Dict[str, Any]] = {}
job_tasks: Dict[str, asyncio.Task] = {}

# --- Step Definitions ---
# Define rough percentage ranges for each step (adjust based on typical performance)
# These ranges are used to map the *start* and *end* of a step to the overall progress.
STEP_RANGES = {
    "download": (0, 15),
    "extract_audio": (15, 25),
    "separate_tracks": (25, 65), # Can take the longest time
    "transcribe": (65, 85),      # Also potentially long
    "process_lyrics": (85, 90),
    "generate_srt": (90, 93),
    "merge": (93, 99),
    "finalize": (99, 100),
}

# --- Progress Management Functions ---

def set_progress(job_id: str, progress: int, message: str, result: Optional[Dict] = None, is_step_start: bool = False, step_name: Optional[str] = None):
    """
    Updates the progress status for a given job ID.

    Args:
        job_id: The unique identifier for the job.
        progress: Absolute progress percentage (0-100).
        message: A descriptive message about the current status.
        result: Optional dictionary containing final results upon completion.
        is_step_start: Boolean indicating if this message marks the *start* of a major processing step.
        step_name: (Optional) The name of the current processing step (used for logging).
    """
    # Avoid updating progress for jobs that are no longer tracked or have finished
    if job_id not in progress_dict and job_id not in job_tasks:
        # logger.warning(f"Attempted to set progress for non-existent or cancelled job {job_id}. Ignoring.")
        return
    # Also check if job is already marked as 100% complete with a result (unless it's an error override)
    current_data = progress_dict.get(job_id, {})
    is_already_final_success = current_data.get("progress", 0) >= 100 and current_data.get("result") is not None
    is_error_override = "error" in message.lower()

    if is_already_final_success and not is_error_override:
        # logger.debug(f"Skipping progress update for already completed job {job_id}")
        return

    # Ensure progress is within bounds 0-100
    clamped_progress = max(0, min(int(progress), 100))

    # Determine if an update should be sent (significant progress change, step start, message change, or final state)
    should_update = (
        clamped_progress >= current_data.get("progress", -1) + 1 or # Progress increased by >= 1%
        is_step_start or
        (clamped_progress == 100 and result is not None) or # Final success
        (clamped_progress == 100 and ("error" in message.lower() or "cancel" in message.lower())) or # Final error/cancel
        message != current_data.get("message", "") # Message changed
    )

    if should_update:
        progress_dict[job_id] = {
            "progress": clamped_progress,
            "message": message,
            "result": result if result is not None else current_data.get("result"), # Preserve existing result
            "is_step_start": is_step_start,
            # Add timestamp? 'timestamp': time.time()
        }
        # Log more verbosely for step starts/ends and final states
        log_level = logging.INFO if is_step_start or clamped_progress == 100 else logging.DEBUG
        logger.log(log_level, f"Job {job_id}: Progress={clamped_progress}%, Step='{step_name or 'N/A'}', Message='{message[:100]}...', IsNewStep={is_step_start}")


def get_progress(job_id: str) -> Optional[Dict]:
    """Retrieves the current progress data for a job ID."""
    return progress_dict.get(job_id)

# --- Task Management Functions ---

def kill_job(job_id: str):
    """Attempts to cancel a running job task and updates its status."""
    logger.info(f"Cancellation requested for job {job_id}")
    task = job_tasks.pop(job_id, None) # Remove task from tracking immediately

    cancelled_task = False
    if task and not task.done():
        if task.cancel("User requested cancellation"): # Pass reason
            logger.info(f"Successfully initiated cancellation for job task {job_id}")
            cancelled_task = True
        else:
            # Task might have finished between check and cancel call
            logger.warning(f"Failed to initiate cancellation for job task {job_id} (may already be done or uncancelable)")

    # Update progress dict regardless of task cancellation success
    current_data = progress_dict.get(job_id)
    if current_data:
        current_message = current_data.get("message", "").lower()
        is_final_state = current_data.get("progress", 0) >= 100 or \
                         any(keyword in current_message for keyword in ["error", "success", "cancel", "complete"])

        if not is_final_state:
            final_message = f"Job cancelled by user."
            set_progress(job_id, 100, final_message, is_step_start=False) # Use set_progress for consistency
            logger.info(f"Set final cancelled status message for job {job_id}")
        # else: logger.info(f"Job {job_id} already in final state ('{current_message}').")
    else:
        # If progress dict entry doesn't exist (e.g., cleaned up early), create one
        logger.info(f"Job {job_id} progress entry not found during cancellation. Creating final cancel status.")
        progress_dict[job_id] = {
             "progress": 100,
             "message": f"Job cancelled by user (task likely finished/removed).",
             "result": None,
             "is_step_start": False
         }
    # Note: File cleanup is not automatically triggered on cancel


def cancel_all_tasks():
    """Cancels all tracked background tasks."""
    logger.info(f"Cancelling all active job tasks ({len(job_tasks)})...")
    active_job_ids = list(job_tasks.keys())
    for jid in active_job_ids:
        kill_job(jid) # kill_job now removes from job_tasks
    logger.info(f"All ({len(active_job_ids)}) tracked background tasks marked for cancellation.")
