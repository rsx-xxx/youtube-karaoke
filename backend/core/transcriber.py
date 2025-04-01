# File: backend/core/transcriber.py
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import whisper
import torch

# Import centralized settings
from config import settings

logger = logging.getLogger(__name__)

# --- Model Loading ---
# Use a global variable to hold the loaded model instance
MODEL: Optional[whisper.Whisper] = None

def load_whisper_model():
    """Loads the Whisper model based on configuration settings."""
    global MODEL
    if MODEL is not None:
        return MODEL # Already loaded

    # Use settings from config.py
    model_tag = settings.WHISPER_MODEL_TAG
    device = settings.DEVICE

    try:
        logger.info(f"Loading Whisper model '{model_tag}' onto device '{device}'...")
        MODEL = whisper.load_model(model_tag, device=device)
        logger.info(f"Whisper model '{model_tag}' loaded successfully on '{device}'.")
        return MODEL
    except Exception as e:
        logger.error(f"Fatal: Failed to load Whisper model '{model_tag}' on device '{device}': {e}", exc_info=True)
        logger.error("Audio transcription will likely fail.")
        MODEL = None # Ensure model is None on failure
        return None

# --- Transcription ---

async def transcribe_audio(job_id: str, vocals_path: Path, language: Optional[str]) -> List[Dict]:
    """
    Transcribes the given vocal audio file using the loaded Whisper model.
    Runs the synchronous transcription function in a separate thread.
    Uses model and device from config settings.
    """
    global MODEL
    # Ensure model is loaded (idempotent)
    model = load_whisper_model()
    if model is None:
         raise RuntimeError("Whisper model failed to load and is required for transcription.")

    if not vocals_path or not vocals_path.is_file():
         logger.warning(f"Job {job_id}: Vocals file for transcription is missing or invalid: {vocals_path}. Skipping transcription.")
         return []
    try:
        if vocals_path.stat().st_size < 512: # Check size > 512 bytes
            logger.warning(f"Job {job_id}: Vocals file for transcription is too small: {vocals_path} ({vocals_path.stat().st_size} bytes). Skipping transcription.")
            return []
    except FileNotFoundError:
         logger.warning(f"Job {job_id}: Vocals file not found at path: {vocals_path}. Skipping transcription.")
         return []


    try:
        # Pass model tag and device from settings for logging in sync function
        transcript_segments = await asyncio.to_thread(
            _transcribe_audio_sync, model, vocals_path, language, job_id, settings.WHISPER_MODEL_TAG, settings.DEVICE
        )
        return transcript_segments
    except Exception as e:
        logger.error(f"Transcription step failed for job {job_id}: {e}", exc_info=True)
        raise RuntimeError(f"Transcription failed: {e}") from e


def _transcribe_audio_sync(
    model: whisper.Whisper,
    vocals_path: Path,
    language: Optional[str],
    job_id: str,
    model_tag: str, # Receive from caller for logging
    device: str     # Receive from caller for logging
    ) -> List[Dict]:
    """
    Synchronous function to transcribe audio using the provided Whisper model instance.
    """
    logger.info(f"Job {job_id}: Transcribing '{vocals_path.name}' (model: {model_tag}, lang: {language or 'auto'}, device: {device})...")
    # FP16 is only available on CUDA devices
    use_fp16 = (device == "cuda")
    transcribe_args = {"task": "transcribe", "fp16": use_fp16}
    if language and language != "auto":
        transcribe_args["language"] = language
        # logger.info(f"Job {job_id}: Transcription language specified: {language}")

    try:
        # Execute transcription
        # word_timestamps=False is faster, verbose=None uses default logging behavior (less noisy)
        result = model.transcribe(str(vocals_path.resolve()), verbose=None, **transcribe_args)

        # Process the transcription result
        segments = []
        if 'segments' in result and result['segments']:
            for seg in result['segments']:
                start_time = seg.get('start')
                end_time = seg.get('end')
                text = seg.get('text', "").strip()
                # Add segment only if it has valid timing and non-empty text
                if text and start_time is not None and end_time is not None and end_time >= start_time: # Allow zero duration for very short sounds
                    # Perform basic type checking/conversion for safety
                    try:
                         start_float = float(start_time)
                         end_float = float(end_time)
                         # Optional: Add threshold check if needed (e.g., end_float > start_float + 0.01)
                         segments.append({
                             "start": start_float,
                             "end": end_float,
                             "text": text
                         })
                    except (ValueError, TypeError) as time_err:
                         logger.warning(f"Job {job_id}: Skipping segment due to invalid time format: Start={start_time}, End={end_time}, Error={time_err}")
                         continue
                # else: logger.debug(f"Job {job_id}: Skipping segment with invalid data: Start={start_time}, End={end_time}, Text='{text[:20]}...'")

            detected_lang = result.get('language', 'unknown')
            logger.info(f"Job {job_id}: Transcription finished. Lang detected: {detected_lang}. Segments extracted: {len(segments)}")
            if not segments and result.get('text'):
                 logger.warning(f"Job {job_id}: Transcription produced text ('{result['text'][:50]}...') but 0 valid segments. Check audio quality or Whisper segmentation.")
            elif not segments:
                 logger.warning(f"Job {job_id}: Transcription produced 0 valid segments and no text.")
            return segments
        else:
             full_text = result.get('text', '(no text found)')
             logger.warning(f"Job {job_id}: Whisper transcription returned no 'segments'. Full text result: '{full_text[:100]}...'")
             return []

    except Exception as e:
        logger.error(f"Job {job_id}: Whisper transcription process failed for '{vocals_path.name}': {e}", exc_info=True)
        # Provide specific error if it's about file issues vs model issues
        if isinstance(e, FileNotFoundError):
             raise FileNotFoundError(f"Whisper failed: Input audio file not found at {vocals_path}") from e
        # Example: Check for common CUDA errors if applicable
        elif "CUDA" in str(e) and device == "cuda":
             raise RuntimeError(f"Whisper CUDA error during transcription: {e}. Check GPU resources/setup.") from e
        else:
             raise RuntimeError(f"Whisper transcription failed: {e}") from e

# Removed redundant check_gpu_availability() and get_device() as config.py handles this.