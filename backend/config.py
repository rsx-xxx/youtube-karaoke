# File: backend/config.py
"""
Centralized configuration using Pydantic Settings.
Supports environment variables and .env files with type validation.
"""
import logging
from pathlib import Path
from typing import List, Optional
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
import torch

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Directories
    BASE_DIR: Path = Path(__file__).parent.resolve()

    @property
    def ROOT_DIR(self) -> Path:
        return self.BASE_DIR.parent

    @property
    def DOWNLOADS_DIR(self) -> Path:
        return self.BASE_DIR / "downloads"

    @property
    def PROCESSED_DIR(self) -> Path:
        return self.BASE_DIR / "processed"

    @property
    def FRONTEND_WEB_DIR(self) -> Path:
        return self.ROOT_DIR / "frontend" / "web"

    # ML Models
    DEFAULT_WHISPER_MODEL: str = "large-v3"
    DEFAULT_DEMUCS_MODEL: str = "mdx_extra_q"

    WHISPER_MODEL_TAG: str = Field(default="large-v3", alias="WHISPER_MODEL_TAG")
    DEMUCS_MODEL: str = Field(default="mdx_extra_q", alias="DEMUCS_MODEL")

    # Hardware
    @property
    def DEVICE(self) -> str:
        # Priority: CUDA > CPU (MPS has issues with Whisper sparse tensors)
        # M4 Pro CPU is very fast, so CPU is fine for Apple Silicon
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    # API Keys
    GENIUS_API_TOKEN: Optional[str] = Field(default=None, alias="GENIUS_API_TOKEN")

    @property
    def ENABLE_GENIUS_FETCH(self) -> bool:
        return self.GENIUS_API_TOKEN is not None

    # Server
    HOST: str = Field(default="127.0.0.1")
    PORT: int = Field(default=8000, ge=1, le=65535)
    DEBUG: bool = Field(default=False)

    # CORS
    CORS_ORIGINS: str = Field(
        default="http://localhost,http://127.0.0.1,http://localhost:8000,http://127.0.0.1:8000"
    )

    @property
    def ALLOWED_ORIGINS(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(',') if origin.strip()]

    # Rate Limiting
    RATE_LIMIT_REQUESTS: int = Field(default=10, ge=1, description="Max requests per window")
    RATE_LIMIT_WINDOW: int = Field(default=60, ge=1, description="Window size in seconds")
    MAX_CONCURRENT_JOBS: int = Field(default=3, ge=1, le=10, description="Max parallel processing jobs")

    # yt-dlp Settings
    YTDLP_SOCKET_TIMEOUT: int = Field(default=60, ge=10, le=300)
    YTDLP_RETRIES: int = Field(default=3, ge=1, le=10)
    YTDLP_COOKIES_FROM_BROWSER: Optional[str] = Field(
        default=None,  # Disabled by default - auto-extraction often fails on macOS
        description="Browser to extract cookies from: chrome, firefox, safari, edge, opera, brave, chromium"
    )
    YTDLP_COOKIES_FILE: Optional[str] = Field(
        default=None,
        description="Path to cookies.txt file (Netscape format)"
    )
    DEMUCS_TIMEOUT: int = Field(default=2400, ge=300, le=7200)
    DEMUCS_WAIT_TIMEOUT: int = Field(default=15, ge=5, le=60)
    DEMUCS_CHECK_INTERVAL: float = Field(default=0.5, ge=0.1, le=5.0)

    # Lyrics
    LYRICS_ALIGNMENT_THRESHOLD: float = Field(default=0.45, ge=0.0, le=1.0)

    # Cleanup
    CLEANUP_DELAY_PROGRESS: int = Field(default=600, ge=60, le=3600, description="Seconds before progress cleanup")
    CLEANUP_DELAY_FILES: int = Field(default=700, ge=60, le=7200, description="Seconds before file cleanup")
    PROGRESS_TTL: int = Field(default=3600, ge=300, le=86400, description="Progress entry TTL in seconds")

    # Memory Management
    WHISPER_UNLOAD_TIMEOUT: int = Field(default=300, ge=60, le=3600, description="Seconds of inactivity before unloading Whisper model")

    # Graceful Shutdown
    SHUTDOWN_TIMEOUT: int = Field(default=30, ge=5, le=120, description="Seconds to wait for tasks during shutdown")

    @field_validator('WHISPER_MODEL_TAG')
    @classmethod
    def validate_whisper_model(cls, v: str) -> str:
        # large-v3 = best quality, turbo = fast with good quality
        valid_models = {'tiny', 'base', 'small', 'medium', 'large', 'large-v2', 'large-v3', 'turbo'}
        if v not in valid_models:
            logger.warning(f"Unknown Whisper model '{v}', using default 'large-v3'")
            return 'large-v3'
        return v


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Create singleton instance
settings = get_settings()

# Ensure directories exist
settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
settings.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def get_gpu_info() -> tuple[bool, Optional[str]]:
    """Check GPU availability and return info."""
    try:
        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            total_mem_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            logger.info(f"[HARDWARE] CUDA Device Found: {device_name}, Total Memory: {total_mem_gb:.2f} GB")
            return True, device_name
        else:
            logger.info("[HARDWARE] CUDA not available or PyTorch not built with CUDA support.")
            return False, None
    except Exception as e:
        logger.error(f"[HARDWARE] Error checking CUDA availability: {e}", exc_info=False)
        return False, None


# Log configuration on import
logger.info("Configuration Loaded:")
logger.info(f"  - Device: {settings.DEVICE}")
logger.info(f"  - Whisper Model: {settings.WHISPER_MODEL_TAG}")
if settings.WHISPER_MODEL_TAG != settings.DEFAULT_WHISPER_MODEL:
    logger.warning(f"    -> Whisper model overridden. Default is '{settings.DEFAULT_WHISPER_MODEL}'.")
logger.info(f"  - Demucs Model: {settings.DEMUCS_MODEL}")
logger.info(f"  - Genius Fetching Enabled: {settings.ENABLE_GENIUS_FETCH}")
logger.info(f"  - CORS Origins: {settings.ALLOWED_ORIGINS}")
logger.info(f"  - Rate Limit: {settings.RATE_LIMIT_REQUESTS} requests per {settings.RATE_LIMIT_WINDOW}s")
logger.info(f"  - Max Concurrent Jobs: {settings.MAX_CONCURRENT_JOBS}")
