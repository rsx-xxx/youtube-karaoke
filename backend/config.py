# File: backend/config.py
"""
Centralized configuration settings for the backend application.
Reads from environment variables with sensible defaults.
"""
import os
import logging # *** FIX: Use standard logging ***
from pathlib import Path
from typing import Optional, Tuple
# from loguru import logger # Using loguru here, ensure it's installed or switch to standard logging # *** FIX: Remove loguru import ***
from dotenv import load_dotenv
import torch

# *** FIX: Get logger instance ***
logger = logging.getLogger(__name__)

# Load .env file variables, but do not override existing environment variables
load_dotenv(override=False)

class Settings:
    BASE_DIR: Path = Path(__file__).parent.resolve()
    ROOT_DIR: Path = BASE_DIR.parent
    DOWNLOADS_DIR: Path = BASE_DIR / "downloads"
    PROCESSED_DIR: Path = BASE_DIR / "processed"
    FRONTEND_WEB_DIR: Path = ROOT_DIR / "frontend" / "web"

    # --- Model Configuration ---
    # Define the recommended powerful defaults
    DEFAULT_WHISPER_MODEL = "large-v2"
    DEFAULT_DEMUCS_MODEL = "mdx_extra_q"

    # Get model tags from environment variables, falling back to defaults
    WHISPER_MODEL_TAG: str = os.environ.get("WHISPER_MODEL_TAG", DEFAULT_WHISPER_MODEL)
    DEMUCS_MODEL: str = os.environ.get("DEMUCS_MODEL", DEFAULT_DEMUCS_MODEL)

    # --- Hardware Configuration ---
    DEVICE: str = "cuda" if torch.cuda.is_available() else "cpu"

    # --- API Keys ---
    GENIUS_API_TOKEN: Optional[str] = os.environ.get("GENIUS_API_TOKEN")

    # --- Server Configuration ---
    HOST: str = os.environ.get("HOST", "127.0.0.1")
    PORT: int = int(os.environ.get("PORT", 8000))

    # --- CORS Configuration ---
    _default_origins = "http://localhost,http://127.0.0.1,http://localhost:8000,http://127.0.0.1:8000" # Added ports
    CORS_ORIGINS_STR: str = os.environ.get("CORS_ORIGINS", _default_origins)
    @property
    def ALLOWED_ORIGINS(self) -> list[str]:
        # Ensure correct splitting and stripping of whitespace
        return [origin.strip() for origin in self.CORS_ORIGINS_STR.split(',') if origin.strip()]

    # --- Processing Timeouts & Thresholds ---
    YTDLP_SOCKET_TIMEOUT: int = int(os.environ.get("YTDLP_SOCKET_TIMEOUT", 60))
    YTDLP_RETRIES: int = int(os.environ.get("YTDLP_RETRIES", 3))
    DEMUCS_TIMEOUT: int = int(os.environ.get("DEMUCS_TIMEOUT", 2400)) # e.g., 40 minutes
    DEMUCS_WAIT_TIMEOUT: int = int(os.environ.get("DEMUCS_WAIT_TIMEOUT", 15)) # Wait for files after process ends
    DEMUCS_CHECK_INTERVAL: float = float(os.environ.get("DEMUCS_CHECK_INTERVAL", 0.5))
    # Alignment threshold - lower means more lenient matching
    LYRICS_ALIGNMENT_THRESHOLD: float = float(os.environ.get("LYRICS_ALIGNMENT_THRESHOLD", 0.45)) # Lowered threshold slightly

    # --- Cleanup Delays (in seconds) ---
    CLEANUP_DELAY_PROGRESS: int = int(os.environ.get("CLEANUP_DELAY_PROGRESS", 600)) # 10 minutes for progress data
    CLEANUP_DELAY_FILES: int = int(os.environ.get("CLEANUP_DELAY_FILES", 700)) # ~11.5 minutes for files

    # --- Feature Flags ---
    ENABLE_GENIUS_FETCH: bool = GENIUS_API_TOKEN is not None

# Instantiate settings
settings = Settings()

# --- Create Directories ---
settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
settings.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# --- Hardware Info Function ---
def get_gpu_info() -> Tuple[bool, Optional[str]]:
    """Checks for CUDA availability and returns GPU name if available."""
    try:
        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            total_mem_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            # *** FIX: Use standard logger ***
            logger.info(f"[HARDWARE] CUDA Device Found: {device_name}, Total Memory: {total_mem_gb:.2f} GB")
            return True, device_name
        else:
            # *** FIX: Use standard logger ***
            logger.info("[HARDWARE] CUDA not available or PyTorch not built with CUDA support.")
            return False, None
    except Exception as e:
        # *** FIX: Use standard logger ***
        logger.error(f"[HARDWARE] Error checking CUDA availability: {e}", exc_info=False)
        return False, None

# --- Log Final Configuration ---
# *** FIX: Use standard logger for all config logging ***
logger.info(f"Configuration Loaded:")
logger.info(f"  - Device: {settings.DEVICE}")
logger.info(f"  - Whisper Model: {settings.WHISPER_MODEL_TAG}")
# *** ADDED WARNING ***
if settings.WHISPER_MODEL_TAG != Settings.DEFAULT_WHISPER_MODEL:
    logger.warning(f"    -> Whisper model overridden by environment variable. Default is '{Settings.DEFAULT_WHISPER_MODEL}'.")
logger.info(f"  - Demucs Model: {settings.DEMUCS_MODEL}")
if settings.DEMUCS_MODEL != Settings.DEFAULT_DEMUCS_MODEL:
    logger.warning(f"    -> Demucs model overridden by environment variable. Default is '{Settings.DEFAULT_DEMUCS_MODEL}'.")
# *** END ADDED WARNING ***
logger.info(f"  - Genius Fetching Enabled: {settings.ENABLE_GENIUS_FETCH}")
logger.info(f"  - CORS Origins Allowed: {settings.ALLOWED_ORIGINS}")
logger.info(f"  - Alignment Threshold: {settings.LYRICS_ALIGNMENT_THRESHOLD}")