# File: backend/utils/progress_manager.py
"""
Thread-safe progress management with TTL-based cleanup.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from threading import Lock
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@dataclass
class ProgressEntry:
    """Progress entry with TTL support."""
    progress: int = 0
    message: str = ""
    result: Optional[Dict] = None
    is_step_start: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "is_step_start": self.is_step_start,
        }

    def is_expired(self, ttl_seconds: int) -> bool:
        return (time.time() - self.updated_at) > ttl_seconds


class ThreadSafeProgressManager:
    """Thread-safe progress tracking with automatic TTL cleanup."""

    def __init__(self, ttl_seconds: int = 3600):
        self._progress: Dict[str, ProgressEntry] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._lock = Lock()
        self._ttl = ttl_seconds
        self._cleanup_task: Optional[asyncio.Task] = None

    @contextmanager
    def _locked(self):
        """Context manager for thread-safe operations."""
        self._lock.acquire()
        try:
            yield
        finally:
            self._lock.release()

    def set_progress(
        self,
        job_id: str,
        progress: int,
        message: str,
        result: Optional[Dict] = None,
        is_step_start: bool = False,
        step_name: Optional[str] = None
    ) -> None:
        """Updates progress for a job ID (thread-safe)."""
        with self._locked():
            # Skip if job doesn't exist and isn't being tracked
            if job_id not in self._progress and job_id not in self._tasks:
                return

            current = self._progress.get(job_id)

            # Skip if already completed successfully
            if current:
                is_already_final = current.progress >= 100 and current.result is not None
                is_error_override = "error" in message.lower()
                if is_already_final and not is_error_override:
                    return

            # Clamp progress
            clamped = max(0, min(int(progress), 100))

            # Determine if update is needed
            should_update = (
                current is None or
                clamped >= current.progress + 1 or
                is_step_start or
                (clamped == 100 and result is not None) or
                (clamped == 100 and any(kw in message.lower() for kw in ["error", "cancel"])) or
                message != current.message
            )

            if should_update:
                if current:
                    current.progress = clamped
                    current.message = message
                    current.result = result if result is not None else current.result
                    current.is_step_start = is_step_start
                    current.updated_at = time.time()
                else:
                    self._progress[job_id] = ProgressEntry(
                        progress=clamped,
                        message=message,
                        result=result,
                        is_step_start=is_step_start
                    )

                log_level = logging.INFO if is_step_start or clamped == 100 else logging.DEBUG
                logger.log(
                    log_level,
                    f"Job {job_id}: Progress={clamped}%, Step='{step_name or 'N/A'}', "
                    f"Message='{message[:100]}...', IsNewStep={is_step_start}"
                )

    def get_progress(self, job_id: str) -> Optional[Dict]:
        """Retrieves progress for a job ID (thread-safe)."""
        with self._locked():
            entry = self._progress.get(job_id)
            if entry:
                return {**entry.to_dict(), "job_id": job_id}
            return None

    def create_job(self, job_id: str, initial_message: str = "Job accepted, preparing...") -> None:
        """Creates a new job entry."""
        with self._locked():
            self._progress[job_id] = ProgressEntry(
                progress=0,
                message=initial_message,
                is_step_start=True
            )

    def register_task(self, job_id: str, task: asyncio.Task) -> None:
        """Registers an asyncio task for a job."""
        with self._locked():
            self._tasks[job_id] = task

    def get_task(self, job_id: str) -> Optional[asyncio.Task]:
        """Gets the task for a job."""
        with self._locked():
            return self._tasks.get(job_id)

    def job_exists(self, job_id: str) -> bool:
        """Checks if a job exists."""
        with self._locked():
            return job_id in self._progress or job_id in self._tasks

    def get_active_job_count(self) -> int:
        """Returns the count of non-completed jobs."""
        with self._locked():
            return sum(
                1 for entry in self._progress.values()
                if entry.progress < 100
            )

    def kill_job(self, job_id: str) -> bool:
        """Cancels a running job task."""
        logger.info(f"Cancellation requested for job {job_id}")

        with self._locked():
            task = self._tasks.pop(job_id, None)
            cancelled = False

            if task and not task.done():
                if task.cancel("User requested cancellation"):
                    logger.info(f"Successfully initiated cancellation for job {job_id}")
                    cancelled = True
                else:
                    logger.warning(f"Failed to initiate cancellation for job {job_id}")

            # Update progress
            current = self._progress.get(job_id)
            if current:
                is_final = current.progress >= 100 or any(
                    kw in current.message.lower()
                    for kw in ["error", "success", "cancel", "complete"]
                )
                if not is_final:
                    current.progress = 100
                    current.message = "Job cancelled by user."
                    current.updated_at = time.time()
                    logger.info(f"Set cancelled status for job {job_id}")
            else:
                self._progress[job_id] = ProgressEntry(
                    progress=100,
                    message="Job cancelled by user (task not found)."
                )

            return cancelled

    def cancel_all_tasks(self) -> int:
        """Cancels all active tasks. Returns count of cancelled tasks."""
        with self._locked():
            job_ids = list(self._tasks.keys())

        cancelled_count = 0
        for job_id in job_ids:
            if self.kill_job(job_id):
                cancelled_count += 1

        logger.info(f"Cancelled {cancelled_count} of {len(job_ids)} active tasks")
        return cancelled_count

    def cleanup_expired(self) -> int:
        """Removes expired progress entries. Returns count of removed entries."""
        with self._locked():
            expired_ids = [
                job_id for job_id, entry in self._progress.items()
                if entry.is_expired(self._ttl) and entry.progress >= 100
            ]
            for job_id in expired_ids:
                del self._progress[job_id]
                self._tasks.pop(job_id, None)

            if expired_ids:
                logger.info(f"Cleaned up {len(expired_ids)} expired progress entries")

            return len(expired_ids)

    async def start_cleanup_loop(self, interval: int = 300) -> None:
        """Starts periodic cleanup of expired entries."""
        async def cleanup_loop():
            while True:
                await asyncio.sleep(interval)
                self.cleanup_expired()

        self._cleanup_task = asyncio.create_task(cleanup_loop())
        logger.info(f"Started progress cleanup loop (interval: {interval}s)")

    def stop_cleanup_loop(self) -> None:
        """Stops the cleanup loop."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            logger.info("Stopped progress cleanup loop")

    def get_stats(self) -> Dict[str, int]:
        """Returns statistics about current state."""
        with self._locked():
            total = len(self._progress)
            active = sum(1 for e in self._progress.values() if e.progress < 100)
            tasks = len(self._tasks)
            return {
                "total_jobs": total,
                "active_jobs": active,
                "registered_tasks": tasks
            }


# --- Global Instance ---
# Import settings after class definition to avoid circular imports
try:
    from config import settings
    _ttl = settings.PROGRESS_TTL
except ImportError:
    _ttl = 3600

_manager = ThreadSafeProgressManager(ttl_seconds=_ttl)

# --- Backward-compatible API ---
progress_dict = _manager._progress  # For legacy access (avoid using directly)
job_tasks = _manager._tasks  # For legacy access (avoid using directly)


def set_progress(
    job_id: str,
    progress: int,
    message: str,
    result: Optional[Dict] = None,
    is_step_start: bool = False,
    step_name: Optional[str] = None
) -> None:
    """Updates progress (backward-compatible wrapper)."""
    _manager.set_progress(job_id, progress, message, result, is_step_start, step_name)


def get_progress(job_id: str) -> Optional[Dict]:
    """Gets progress (backward-compatible wrapper)."""
    return _manager.get_progress(job_id)


def kill_job(job_id: str) -> bool:
    """Kills a job (backward-compatible wrapper)."""
    return _manager.kill_job(job_id)


def cancel_all_tasks() -> int:
    """Cancels all tasks (backward-compatible wrapper)."""
    return _manager.cancel_all_tasks()


def get_manager() -> ThreadSafeProgressManager:
    """Returns the global manager instance."""
    return _manager


# Step ranges for progress calculation
STEP_RANGES = {
    "download": (0, 15),
    "extract_audio": (15, 25),
    "analyze_audio": (25, 30),
    "separate_tracks": (30, 60),
    "transcribe": (60, 80),
    "process_lyrics": (80, 88),
    "generate_srt": (88, 92),
    "generate_ass": (88, 92),  # Alias for generate_srt
    "merge": (92, 99),
    "finalize": (99, 100),
}
