# File: backend/app.py
"""
FastAPI application with rate limiting, graceful shutdown, and proper lifecycle management.
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Dict

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

# --- Early Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- Configuration ---
from .config import settings, get_gpu_info

# --- Import Core Components ---
from .api.v1 import router as api_router
from .utils.progress_manager import cancel_all_tasks, get_manager


# --- Rate Limiter Implementation ---
class RateLimiter:
    """Simple in-memory rate limiter."""

    def __init__(self, requests: int, window: int):
        self.requests = requests
        self.window = window
        self._clients: Dict[str, list] = {}

    def _cleanup(self, client_id: str) -> None:
        """Remove expired timestamps."""
        now = time.time()
        if client_id in self._clients:
            self._clients[client_id] = [
                ts for ts in self._clients[client_id]
                if now - ts < self.window
            ]

    def is_allowed(self, client_id: str) -> bool:
        """Check if client is within rate limit."""
        self._cleanup(client_id)
        if client_id not in self._clients:
            self._clients[client_id] = []

        if len(self._clients[client_id]) >= self.requests:
            return False

        self._clients[client_id].append(time.time())
        return True

    def get_remaining(self, client_id: str) -> int:
        """Get remaining requests for client."""
        self._cleanup(client_id)
        used = len(self._clients.get(client_id, []))
        return max(0, self.requests - used)


# Global rate limiter instance
rate_limiter = RateLimiter(
    requests=settings.RATE_LIMIT_REQUESTS,
    window=settings.RATE_LIMIT_WINDOW
)


# --- Concurrency Limiter ---
class JobSemaphore:
    """Manages concurrent job limit."""

    def __init__(self, max_jobs: int):
        self._semaphore = asyncio.Semaphore(max_jobs)
        self._max = max_jobs
        self._current = 0

    async def acquire(self) -> bool:
        """Try to acquire a slot."""
        acquired = await asyncio.wait_for(
            self._semaphore.acquire(),
            timeout=0.1
        )
        if acquired:
            self._current += 1
        return acquired

    def release(self) -> None:
        """Release a slot."""
        self._semaphore.release()
        self._current = max(0, self._current - 1)

    @property
    def available(self) -> int:
        return self._max - self._current

    @property
    def is_full(self) -> bool:
        return self._current >= self._max


job_semaphore = JobSemaphore(settings.MAX_CONCURRENT_JOBS)


# --- Application Lifecycle ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Async context manager for application lifecycle."""
    logger.info("[LIFESPAN] Application startup...")

    # Ensure directories exist
    settings.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Ensured directories: {settings.PROCESSED_DIR}, {settings.DOWNLOADS_DIR}")

    # Start progress cleanup loop
    manager = get_manager()
    await manager.start_cleanup_loop(interval=300)

    yield  # Application runs here

    # --- Graceful Shutdown ---
    logger.info("[LIFESPAN] Graceful shutdown initiated...")

    # Stop cleanup loop
    manager.stop_cleanup_loop()

    # Cancel all running tasks
    active_count = manager.get_active_job_count()
    if active_count > 0:
        logger.info(f"[LIFESPAN] Waiting for {active_count} active jobs to complete...")

        # Wait up to SHUTDOWN_TIMEOUT for tasks to complete
        for _ in range(settings.SHUTDOWN_TIMEOUT):
            if manager.get_active_job_count() == 0:
                break
            await asyncio.sleep(1)

        # Force cancel remaining tasks
        remaining = manager.get_active_job_count()
        if remaining > 0:
            logger.warning(f"[LIFESPAN] Force cancelling {remaining} remaining tasks")
            cancel_all_tasks()

    await asyncio.sleep(0.5)  # Brief delay for cleanup
    logger.info("[LIFESPAN] Shutdown complete.")


# --- FastAPI App ---
app = FastAPI(
    title="Karaoke Generator API",
    description="API for converting YouTube videos to Karaoke with modern AI processing.",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)


# --- Rate Limiting Middleware ---
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Apply rate limiting to API endpoints."""
    # Skip rate limiting for static files
    if not request.url.path.startswith("/api/"):
        return await call_next(request)

    # Skip rate limiting for WebSocket upgrades
    if request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)

    # Get client identifier (IP + User-Agent hash for basic fingerprinting)
    client_ip = request.client.host if request.client else "unknown"
    client_id = f"{client_ip}"

    if not rate_limiter.is_allowed(client_id):
        logger.warning(f"Rate limit exceeded for {client_id}")
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Too many requests. Please try again later.",
                "retry_after": settings.RATE_LIMIT_WINDOW
            },
            headers={"Retry-After": str(settings.RATE_LIMIT_WINDOW)}
        )

    # Add rate limit headers
    response = await call_next(request)
    response.headers["X-RateLimit-Remaining"] = str(rate_limiter.get_remaining(client_id))
    response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_REQUESTS)
    return response


# --- Exception Handlers ---
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    logger.warning(f"HTTP {exc.status_code}: {exc.detail} for {request.method} {request.url}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(
        f"Unhandled Exception: {type(exc).__name__} - {exc} for {request.method} {request.url}",
        exc_info=True
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred."},
    )


# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- API Router ---
app.include_router(api_router, prefix="/api")


# --- Health Check Endpoint ---
@app.get("/health")
async def health_check():
    """Health check endpoint with status info."""
    manager = get_manager()
    stats = manager.get_stats()
    return {
        "status": "healthy",
        "version": "2.0.0",
        "device": settings.DEVICE,
        "genius_enabled": settings.ENABLE_GENIUS_FETCH,
        "jobs": stats,
        "rate_limit": {
            "requests": settings.RATE_LIMIT_REQUESTS,
            "window": settings.RATE_LIMIT_WINDOW
        }
    }


# --- Static Files ---
if not settings.FRONTEND_WEB_DIR.is_dir():
    logger.warning(f"Frontend directory not found: {settings.FRONTEND_WEB_DIR}")
else:
    logger.info(f"Found frontend directory: {settings.FRONTEND_WEB_DIR}")

# Mount processed files
app.mount("/processed", StaticFiles(directory=settings.PROCESSED_DIR), name="processed-files")
logger.info(f"Serving processed files from '/processed' -> {settings.PROCESSED_DIR}")

# Mount frontend
if settings.FRONTEND_WEB_DIR.is_dir():
    index_path = settings.FRONTEND_WEB_DIR / "index.html"
    if index_path.is_file():
        app.mount("/", StaticFiles(directory=settings.FRONTEND_WEB_DIR, html=True), name="frontend")
        logger.info(f"Serving frontend from '/' -> {settings.FRONTEND_WEB_DIR}")
    else:
        logger.warning(f"index.html not found in {settings.FRONTEND_WEB_DIR}")


# --- Startup Event ---
@app.on_event("startup")
async def startup_event():
    logger.info("=" * 60)
    logger.info("  Karaoke Generator API v2.0.0")
    logger.info("=" * 60)
    logger.info(f"  Web Interface: http://{settings.HOST}:{settings.PORT}")
    logger.info(f"  API Docs:      http://{settings.HOST}:{settings.PORT}/docs")
    logger.info(f"  Health Check:  http://{settings.HOST}:{settings.PORT}/health")
    logger.info("=" * 60)

    # Check GPU
    gpu_available, gpu_name = get_gpu_info()
    if gpu_available:
        logger.info(f"[HARDWARE] Using GPU: {gpu_name}")
    else:
        logger.info(f"[HARDWARE] Using CPU (GPU not available)")


# --- Export semaphore for endpoints ---
def get_job_semaphore() -> JobSemaphore:
    return job_semaphore
