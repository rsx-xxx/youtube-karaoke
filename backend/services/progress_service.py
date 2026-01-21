# File: backend/services/progress_service.py
"""Service for job progress tracking."""
import logging
from typing import Any, Dict, Optional

from ..utils.progress_manager import get_manager, kill_job

logger = logging.getLogger(__name__)


class ProgressService:
    """Service for managing job progress and lifecycle."""

    def __init__(self):
        self._manager = get_manager()

    def create_job(self, job_id: str, initial_message: str = "Job accepted, preparing...") -> None:
        """Initialize a new job in the progress tracker."""
        self._manager.create_job(job_id, initial_message)
        logger.info(f"Created job {job_id}")

    def update_progress(
        self,
        job_id: str,
        progress: int,
        message: str,
        is_step_start: bool = False,
        result: Optional[Dict[str, Any]] = None
    ) -> None:
        """Update job progress."""
        self._manager.set_progress(job_id, progress, message, result=result, is_step_start=is_step_start)

    def get_progress(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get current progress for a job."""
        return self._manager.get_progress(job_id)

    def job_exists(self, job_id: str) -> bool:
        """Check if a job exists."""
        return self._manager.job_exists(job_id)

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job."""
        if not self.job_exists(job_id):
            return False
        self._manager.kill_job(job_id)
        logger.info(f"Cancelled job {job_id}")
        return True

    def get_stats(self) -> Dict[str, Any]:
        """Get overall job statistics."""
        return self._manager.get_stats()

    def get_active_count(self) -> int:
        """Get number of active jobs."""
        return self._manager.get_active_job_count()
