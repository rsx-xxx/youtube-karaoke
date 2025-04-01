# File: backend/config.py
"""
Centralized configuration settings for the backend application.
Reads from environment variables with sensible defaults.
"""
import os
import logging # Added for logging GPU check errors
from pathlib import Path
from typing import Optional, Tuple

from dotenv import load_dotenv
import torch

# Load .env file first
load_dotenv(override=False) # Existing env vars take precedence

class Settings:
    # --- Core Paths ---
    BASE_DIR: Path = Path(__file__).parent.resolve() # backend/
    ROOT_DIR: Path = BASE_DIR.parent # Project root
    DOWNLOADS_DIR: Path = BASE_DIR / "downloads"
    PROCESSED_DIR: Path = BASE_DIR / "processed"
    FRONTEND_WEB_DIR: Path = ROOT_DIR / "frontend" / "web"

    # --- Model Configuration ---
    WHISPER_MODEL_TAG: str = os.environ.get("WHISPER_MODEL_TAG", "base") # tiny, base, small, medium, large
    # Changed default to match usage in logs
    DEMUCS_MODEL: str = os.environ.get("DEMUCS_MODEL", "htdemucs") # Demucs model name (e.g., htdemucs, mdx_extra_q)

    # --- Hardware Configuration ---
    # Determine compute device (prioritize CUDA if available)
    DEVICE: str = "cuda" if torch.cuda.is_available() else "cpu"

    # --- API Keys ---
    GENIUS_API_TOKEN: Optional[str] = os.environ.get("GENIUS_API_TOKEN")

    # --- Web Server Configuration ---
    HOST: str = os.environ.get("HOST", "127.0.0.1") # Use 0.0.0.0 inside Docker
    PORT: int = int(os.environ.get("PORT", 8000))

    # --- CORS Configuration ---
    _default_origins = "http://localhost,http://127.0.0.1,http://localhost:8080,http://localhost:5173,http://localhost:3000"
    CORS_ORIGINS_STR: str = os.environ.get("CORS_ORIGINS", _default_origins)
    @property
    def ALLOWED_ORIGINS(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS_STR.split(',') if origin.strip()]

    # --- Processing Parameters ---
    YTDLP_SOCKET_TIMEOUT: int = int(os.environ.get("YTDLP_SOCKET_TIMEOUT", 45))
    YTDLP_RETRIES: int = int(os.environ.get("YTDLP_RETRIES", 3))
    DEMUCS_TIMEOUT: int = int(os.environ.get("DEMUCS_TIMEOUT", 1800)) # 30 minutes
    DEMUCS_WAIT_TIMEOUT: int = int(os.environ.get("DEMUCS_WAIT_TIMEOUT", 10)) # Wait for output dir/files
    DEMUCS_CHECK_INTERVAL: float = float(os.environ.get("DEMUCS_CHECK_INTERVAL", 0.5))
    LYRICS_ALIGNMENT_THRESHOLD: float = float(os.environ.get("LYRICS_ALIGNMENT_THRESHOLD", 0.60))

    # --- Cleanup Configuration (Example) ---
    CLEANUP_DELAY_PROGRESS: int = int(os.environ.get("CLEANUP_DELAY_PROGRESS", 600)) # 10 minutes for progress entry
    CLEANUP_DELAY_FILES: int = int(os.environ.get("CLEANUP_DELAY_FILES", 700)) # ~11 minutes for files

    # --- Feature Flags ---
    ENABLE_GENIUS_FETCH: bool = GENIUS_API_TOKEN is not None

# Create a single instance for easy import
settings = Settings()

# Ensure required directories exist at startup (can also be done in lifespan)
settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
settings.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# --- Helper for logging GPU info ---
def get_gpu_info() -> Tuple[bool, Optional[str]]:
    """Checks if CUDA GPU is available and returns status and device name."""
    try:
        if torch.cuda.is_available():
             # Check if device initialization is needed or if get_device_name works directly
             if not torch.cuda.is_initialized():
                  torch.cuda.init() # Ensure CUDA context is initialized if needed
             if torch.cuda.device_count() > 0:
                  device_name = torch.cuda.get_device_name(0)
                  return True, device_name
             else:
                  # This case might indicate an issue even if is_available() is true
                  logging.getLogger(__name__).warning("[HARDWARE] CUDA reports available but no devices found.")
                  return False, None
        else:
             return False, None
    except RuntimeError as e:
         # Catch specific runtime errors often related to drivers or CUDA setup
         logging.getLogger(__name__).error(f"[HARDWARE] Error checking for CUDA (RuntimeError): {e}")
         return False, None
    except Exception as e:
         # Catch other unexpected errors
         logging.getLogger(__name__).error(f"[HARDWARE] Unexpected error checking for CUDA availability: {e}", exc_info=True)
         return False, None

# Optionally print some config on load for verification
# import logging
# logging.info(f"Config loaded: DEVICE={settings.DEVICE}, DEMUCS_MODEL={settings.DEMUCS_MODEL}, GENIUS_ENABLED={settings.ENABLE_GENIUS_FETCH}")