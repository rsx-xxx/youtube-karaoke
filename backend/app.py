# File: backend/app.py
import asyncio
import importlib
import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
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
# Load settings from config.py, which handles .env loading
from config import settings, get_gpu_info

# --- Import Core Components (after config) ---
from endpoints import router as api_router
from utils.progress_manager import cancel_all_tasks, progress_dict, job_tasks # Import state from manager
# Load transcriber model early if desired (or let it load on first use)
# from core.transcriber import load_whisper_model
# load_whisper_model()


# --- Logging Configuration Details ---
logger.info(f"Configuration loaded. Device: {settings.DEVICE}")
if settings.ENABLE_GENIUS_FETCH:
    logger.info("GENIUS_API_TOKEN found, Genius lyrics fetching enabled.")
else:
    logger.warning("GENIUS_API_TOKEN not found. Lyrics fetching via Genius will be disabled.")
logger.info(f"[CONFIG] Allowing CORS origins: {settings.ALLOWED_ORIGINS}")


# --- Application Lifecycle ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Asynchronous context manager for application lifecycle events."""
    logger.info("[LIFESPAN] Application startup...")
    # Ensure directories exist (redundant if config does it, but safe)
    settings.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Ensured directories exist: {settings.PROCESSED_DIR}, {settings.DOWNLOADS_DIR}")
    yield # Application runs here
    # --- Shutdown Logic ---
    logger.info("[LIFESPAN] Application shutdown requested...")
    await asyncio.sleep(0.1) # Short delay
    cancel_all_tasks() # Initiate cancellation for all background tasks
    logger.info("[LIFESPAN] Shutdown complete.")


# --- FastAPI App Instantiation ---
app = FastAPI(
    title="Karaoke Generator API",
    description="API for converting YouTube videos to Karaoke with a modern touch.",
    version="1.6.0", # Version updated
    lifespan=lifespan
)


# --- Exception Handling ---
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    logger.warning(f"HTTP Exception: {exc.status_code} - {exc.detail} for {request.method} {request.url}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled Exception: {type(exc).__name__} - {exc} for {request.method} {request.url}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please check the server logs."},
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


# --- Static Files ---
# Check and log frontend directory status
if not settings.FRONTEND_WEB_DIR.is_dir():
    logger.warning(f"Frontend web directory not found at expected location: {settings.FRONTEND_WEB_DIR}")
else:
    logger.info(f"Found frontend web directory: {settings.FRONTEND_WEB_DIR}")

# Mount processed files directory
app.mount("/processed", StaticFiles(directory=settings.PROCESSED_DIR), name="processed-files")
logger.info(f"Serving processed files from '/processed' mapped to {settings.PROCESSED_DIR}")

# Mount frontend static files (HTML, CSS, JS)
if settings.FRONTEND_WEB_DIR.is_dir():
     index_path = settings.FRONTEND_WEB_DIR / "index.html"
     if index_path.is_file():
         app.mount("/", StaticFiles(directory=settings.FRONTEND_WEB_DIR, html=True), name="frontend-web")
         logger.info(f"Serving frontend static files from '/' mapped to {settings.FRONTEND_WEB_DIR}")
     else:
         logger.warning(f"index.html not found in {settings.FRONTEND_WEB_DIR}. Root path '/' will not serve frontend.")
else:
    logger.warning("Frontend web directory not found, skipping mount for '/'")


# --- Optional: Enhanced Startup Info ---
@app.on_event("startup")
async def startup_event():
     logger.info(f"Karaoke Generator API starting up...")
     logger.info(f" >> Access the web interface at http://{settings.HOST}:{settings.PORT}")
     logger.info(f" >> API documentation available at http://{settings.HOST}:{settings.PORT}/docs")

     # Check and log GPU availability
     gpu_available, gpu_name = get_gpu_info()
     if gpu_available:
          logger.info(f"[HARDWARE] CUDA (GPU) is available: {gpu_name}. Processing will use GPU ({settings.DEVICE}).")
     else:
          logger.info(f"[HARDWARE] CUDA (GPU) not available. Processing will use CPU ({settings.DEVICE}).")


# --- Direct Run (for debugging, use uvicorn command generally) ---
# import uvicorn
# if __name__ == "__main__":
#     logger.info("Running Uvicorn directly for debugging...")
#     uvicorn.run(
#         "app:app",
#         host=settings.HOST,
#         port=settings.PORT,
#         reload=True, # Enable reload for development
#         log_level="debug"
#      )