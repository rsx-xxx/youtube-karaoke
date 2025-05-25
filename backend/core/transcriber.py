# File: backend/core/transcriber.py
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any # Added Any for result type

import whisper
import torch

# Import centralized settings
from config import settings

logger = logging.getLogger(__name__)

# --- Model Loading ---
MODEL: Optional[whisper.Whisper] = None
MODEL_LOAD_LOCK = asyncio.Lock() # Prevent race conditions during model loading

async def load_whisper_model():
    """Loads the Whisper model based on configuration settings, ensuring thread-safety."""
    global MODEL
    # Fast check without lock
    if MODEL is not None:
        return MODEL

    # Acquire lock to prevent multiple threads loading simultaneously
    async with MODEL_LOAD_LOCK:
        # Double check after acquiring lock
        if MODEL is not None:
            return MODEL

        model_tag = settings.WHISPER_MODEL_TAG
        device = settings.DEVICE

        try:
            logger.info(f"Loading Whisper model '{model_tag}' onto device '{device}'...")
            # Use asyncio.to_thread for the blocking load_model call
            MODEL = await asyncio.to_thread(whisper.load_model, model_tag, device=device)
            if MODEL is None: # Should not happen if load_model doesn't raise, but check
                raise RuntimeError("whisper.load_model returned None unexpectedly.")
            logger.info(f"Whisper model '{model_tag}' loaded successfully on '{device}'.")
            return MODEL
        except Exception as e:
            logger.error(f"FATAL: Failed to load Whisper model '{model_tag}' on device '{device}': {e}", exc_info=True)
            MODEL = None # Ensure MODEL is None on failure
            # Optionally re-raise or handle differently depending on desired app behavior
            raise RuntimeError(f"Whisper model '{model_tag}' failed to load.") from e


# --- Transcription ---

async def transcribe_audio(job_id: str, vocals_path: Path, language: Optional[str]) -> Tuple[List[Dict], Optional[Any]]:
    """
    Transcribes the vocal audio file using Whisper, requesting word timestamps.
    Returns a tuple: (list_of_segments_with_words, full_whisper_result_object)
    Runs the synchronous transcription function in a separate thread.
    Loads the model if necessary.
    """
    # Ensure model is loaded before proceeding
    try:
        model = await load_whisper_model()
        if model is None: # Should not happen if load_whisper_model raises error, but good practice
            raise RuntimeError("Whisper model failed to load and is required for transcription.")
    except Exception as load_err:
         logger.error(f"Job {job_id}: Transcription failed due to model load error: {load_err}", exc_info=True)
         raise RuntimeError(f"Transcription failed: Could not load Whisper model ({load_err})") from load_err


    if not vocals_path or not vocals_path.is_file():
         logger.warning(f"Job {job_id}: Vocals file missing or not a file: {vocals_path}. Skipping transcription.")
         return [], None # Return empty list and None result

    try:
        # Check file size synchronously before potentially long async call
        if vocals_path.stat().st_size < 1024: # Increased threshold slightly
            logger.warning(f"Job {job_id}: Vocals file too small (<1KB): {vocals_path}. Skipping transcription.")
            return [], None
    except FileNotFoundError:
         logger.warning(f"Job {job_id}: Vocals file not found during size check: {vocals_path}. Skipping transcription.")
         return [], None
    except Exception as stat_err:
         logger.warning(f"Job {job_id}: Error checking vocals file size {vocals_path}: {stat_err}. Skipping transcription.")
         return [], None


    try:
        # Pass model object, path, language, etc. to the sync function run in a thread
        processed_segments, full_result = await asyncio.to_thread(
            _transcribe_audio_sync, model, vocals_path, language, job_id, settings.WHISPER_MODEL_TAG, settings.DEVICE
        )
        return processed_segments, full_result
    except Exception as e:
        logger.error(f"Transcription step failed for job {job_id}: {e}", exc_info=True)
        raise RuntimeError(f"Transcription failed: {e}") from e


def _transcribe_audio_sync(
    model: whisper.Whisper,
    vocals_path: Path,
    language: Optional[str],
    job_id: str,
    model_tag: str,
    device: str
    ) -> Tuple[List[Dict], Optional[Any]]: # Return tuple: processed segments, full result
    """
    Synchronous function to transcribe audio using Whisper with word timestamps.
    Returns a tuple: (list_of_processed_segments, full_whisper_result_object)
    """
    logger.info(f"Job {job_id}: Transcribing '{vocals_path.name}' (model: {model_tag}, lang: {language or 'auto'}, device: {device}, word_timestamps=True)...")
    use_fp16 = (device == "cuda")

    # *** FIX: Remove word_timestamps=True from DecodingOptions ***
    # Configure transcription options (other options can still go here)
    transcribe_options = whisper.DecodingOptions(
        fp16=use_fp16,
        language=language if (language and language != "auto") else None,
        without_timestamps=False, # We need timestamps
        # Add other options if needed, e.g., beam_size, temperature
        # verbose=None # Whisper default handles verbosity
        # word_timestamps=True # <--- REMOVED THIS LINE
    )

    full_result: Optional[Any] = None
    try:
        # Execute transcription using model.transcribe and passing necessary arguments directly
        # Using .resolve() ensures the path is absolute, which might help on some systems
        logger.debug(f"Job {job_id}: Calling model.transcribe with word_timestamps=True")
        full_result = model.transcribe(
            str(vocals_path.resolve()),
            task="transcribe", # Specify task explicitly
            word_timestamps=True, # <<< Pass word_timestamps HERE >>>
            # verbose=False, # Set verbosity level if needed (True, False, None)
            fp16=use_fp16, # Pass fp16 directly too
            language=language if (language and language != "auto") else None, # Pass language directly
            # You can pass other relevant arguments accepted by model.transcribe() here
            # beam_size=5, # Example
            # temperature=0.0, # Example
        )
        logger.debug(f"Job {job_id}: model.transcribe call finished.")


        # Validate the structure of the result
        if not full_result or not isinstance(full_result, dict) or 'segments' not in full_result or not isinstance(full_result['segments'], list):
            full_text = full_result.get('text', '(no text found)') if isinstance(full_result, dict) else '(invalid result type)'
            logger.warning(f"Job {job_id}: Whisper transcription returned no valid segments structure. Full text: '{full_text[:100]}...'")
            # Return empty list for segments, but still return the potentially useful result object
            return [], full_result

        # Process segments and embed word timings more carefully
        processed_segments = []
        num_raw_segments = len(full_result['segments'])
        num_processed_words = 0
        num_segments_skipped = 0

        for seg_index, seg in enumerate(full_result['segments']):
            # Validate segment structure
            if not isinstance(seg, dict):
                logger.warning(f"Job {job_id}: Skipping invalid segment data (not a dict) at index {seg_index}.")
                num_segments_skipped += 1
                continue

            start_time = seg.get('start')
            end_time = seg.get('end')
            text = seg.get('text', "").strip()
            words_data = seg.get('words', []) # Get word data if available

            # Basic validation for the segment itself (timing and text)
            if not text or start_time is None or end_time is None or not isinstance(start_time, (int, float)) or not isinstance(end_time, (int, float)) or end_time < start_time:
                logger.warning(f"Job {job_id}: Skipping segment index {seg_index} due to missing/invalid timing or empty text: Start={start_time}, End={end_time}, Text='{text[:30]}...'")
                num_segments_skipped += 1
                continue

            valid_words = []
            if isinstance(words_data, list):
                for word_index, word_info in enumerate(words_data):
                     # Validate word structure and timing robustly
                     # *** Ensure whisper output format uses 'word' key (or adjust if it uses 'text') ***
                     word_key = 'word' if 'word' in word_info else 'text' # Adapt if needed
                     if (isinstance(word_info, dict) and
                         word_key in word_info and 'start' in word_info and 'end' in word_info and
                         isinstance(word_info[word_key], str) and # Ensure word is string
                         isinstance(word_info['start'], (int, float)) and
                         isinstance(word_info['end'], (int, float)) and
                         word_info['end'] >= word_info['start']): # Check end >= start

                         cleaned_word_text = word_info[word_key].strip()
                         # Optional: Skip words that are just punctuation after stripping?
                         # if not cleaned_word_text or not any(c.isalnum() for c in cleaned_word_text): continue

                         valid_words.append({
                             "text": cleaned_word_text, # Store cleaned word text
                             "start": float(word_info['start']),
                             "end": float(word_info['end'])
                         })
                         num_processed_words += 1
                     else:
                        # Log invalid word structure less verbosely
                        # logger.debug(f"Job {job_id}: Skipping invalid word data at seg {seg_index}, word {word_index}: {word_info}")
                        pass # Silently skip invalid words

            # Only add the segment if it has text *and* at least one valid word with timing
            if text and valid_words:
                processed_segments.append({
                    "start": float(start_time),
                    "end": float(end_time),
                    "text": text, # Keep original segment text for context/debugging
                    "words": valid_words # Embed the list of valid words with timings
                })
            else:
                 logger.warning(f"Job {job_id}: Skipping segment index {seg_index} ('{text[:30]}...') because it lacked valid timed words after processing.")
                 num_segments_skipped +=1


        detected_lang = full_result.get('language', 'unknown')
        logger.info(f"Job {job_id}: Transcription finished. Lang: {detected_lang}. Raw Segments: {num_raw_segments}, Processed/Valid Segments: {len(processed_segments)}, Skipped Segments: {num_segments_skipped}. Words processed: {num_processed_words}")

        if not processed_segments and full_result.get('text'):
             logger.warning(f"Job {job_id}: Transcription had text but 0 segments remained after processing/validation. Check Whisper output or word timing quality.")
        elif not processed_segments:
             logger.warning(f"Job {job_id}: Transcription produced 0 valid segments and likely no text.")

        # Return both the list of processed segments and the original full result object
        return processed_segments, full_result

    except TypeError as te:
        # Catch the specific TypeError we encountered before
        logger.error(f"Job {job_id}: TypeError during Whisper transcription: {te}", exc_info=True)
        if "unexpected keyword argument 'word_timestamps'" in str(te):
            raise RuntimeError("Whisper transcription failed: Mismatch in expected arguments for transcribe/DecodingOptions. Check library version compatibility.") from te
        else:
            raise RuntimeError(f"Whisper transcription failed due to TypeError: {te}") from te
    except Exception as e:
        logger.error(f"Job {job_id}: Whisper transcription process failed inside _transcribe_audio_sync: {e}", exc_info=True)
        # Provide more context in the raised error
        if isinstance(e, FileNotFoundError):
             raise FileNotFoundError(f"Whisper failed: Input audio file not found at {vocals_path}") from e
        elif "CUDA" in str(e).upper() and device == "cuda":
             # Specific CUDA error handling (e.g., out of memory)
             if "out of memory" in str(e).lower():
                  raise RuntimeError(f"Whisper CUDA Error: Out of memory on device '{device}'. Try a smaller model or reduce batch size if applicable.") from e
             else:
                  raise RuntimeError(f"Whisper CUDA error during transcription on device '{device}': {e}. Check GPU/driver/torch setup.") from e
        else:
             # Generic re-throw
             raise RuntimeError(f"Whisper transcription failed: {e}") from e