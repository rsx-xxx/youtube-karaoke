# File: backend/core/transcriber.py
import asyncio
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

import whisper  # type: ignore
import torch

from ..config import settings
from ..utils.version_tracker import (
    get_whisper_version,
    is_transcription_cache_valid,
    update_transcription_cache_metadata
)

logger = logging.getLogger(__name__)

# Transcription cache filename pattern
TRANSCRIPTION_CACHE_PATTERN = "transcription_{model}_{lang}.json"


def _get_transcription_cache_path(processed_dir: Path, video_id: str, model: str, language: str) -> Path:
    """Get the path to the transcription cache file."""
    lang = language if language else "auto"
    filename = TRANSCRIPTION_CACHE_PATTERN.format(model=model, lang=lang)
    return processed_dir / video_id / filename


def _load_transcription_cache(cache_path: Path, expected_version: str) -> Optional[Tuple[List[Dict], Any]]:
    """
    Load transcription from cache if valid.

    Returns:
        Tuple of (segments, full_result) if cache is valid, None otherwise
    """
    if not cache_path.is_file():
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Validate whisper version
        cached_version = data.get("whisper_version", "")
        if cached_version != expected_version:
            logger.info(f"Transcription cache version mismatch: {cached_version} != {expected_version}")
            return None

        segments = data.get("segments", [])
        full_result = data.get("full_result")

        if not segments:
            logger.warning("Transcription cache has no segments")
            return None

        return segments, full_result

    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON in transcription cache {cache_path}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error loading transcription cache from {cache_path}: {e}")
        return None


def _save_transcription_cache(
    cache_path: Path,
    segments: List[Dict],
    full_result: Any,
    whisper_version: str,
    model: str,
    language: str
) -> bool:
    """Save transcription to cache."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "whisper_version": whisper_version,
            "whisper_model": model,
            "language": language,
            "segments": segments,
            "full_result": full_result
        }

        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.debug(f"Saved transcription cache to {cache_path}")
        return True

    except Exception as e:
        logger.warning(f"Failed to save transcription cache: {e}")
        return False

MODEL: Optional[whisper.Whisper] = None
MODEL_LOAD_LOCK = asyncio.Lock()

async def load_whisper_model():
    global MODEL
    if MODEL is not None:
        return MODEL

    async with MODEL_LOAD_LOCK:
        if MODEL is not None:
            return MODEL

        model_tag = settings.WHISPER_MODEL_TAG
        device = settings.DEVICE

        try:
            logger.info(f"Loading Whisper model '{model_tag}' onto device '{device}'...")
            MODEL = await asyncio.to_thread(whisper.load_model, model_tag, device=device)
            if MODEL is None:
                raise RuntimeError("whisper.load_model returned None unexpectedly.")
            logger.info(f"Whisper model '{model_tag}' loaded successfully on '{device}'.")
            return MODEL
        except Exception as e:
            logger.error(f"FATAL: Failed to load Whisper model '{model_tag}' on device '{device}': {e}", exc_info=True)
            MODEL = None
            raise RuntimeError(f"Whisper model '{model_tag}' failed to load.") from e


async def transcribe_audio(
    job_id: str,
    vocals_path: Path,
    language: Optional[str],
    video_id: Optional[str] = None,
    processed_dir: Optional[Path] = None
) -> Tuple[List[Dict], Optional[Any]]:
    """
    Transcribe audio with caching support.

    Args:
        job_id: Job identifier for logging
        vocals_path: Path to the vocals audio file
        language: Transcription language or None for auto-detect
        video_id: Video identifier for cache lookup
        processed_dir: Base processed directory for cache storage

    Returns:
        Tuple of (processed_segments, full_result)
    """
    model_tag = settings.WHISPER_MODEL_TAG
    lang_for_cache = language if language else "auto"

    # Check cache first if video_id and processed_dir provided
    if video_id and processed_dir:
        whisper_version = get_whisper_version()
        cache_path = _get_transcription_cache_path(processed_dir, video_id, model_tag, lang_for_cache)

        # Check if cache is valid (model + version + language match)
        if is_transcription_cache_valid(processed_dir, video_id, model_tag, lang_for_cache):
            cached = _load_transcription_cache(cache_path, whisper_version)
            if cached:
                segments, full_result = cached
                logger.info(f"Job {job_id}: [CACHE] Using cached transcription for {video_id} ({len(segments)} segments)")
                return segments, full_result

    try:
        model = await load_whisper_model()
        if model is None:
            raise RuntimeError("Whisper model failed to load and is required for transcription.")
    except Exception as load_err:
        logger.error(f"Job {job_id}: Transcription failed due to model load error: {load_err}", exc_info=True)
        raise RuntimeError(f"Transcription failed: Could not load Whisper model ({load_err})") from load_err

    if not vocals_path or not vocals_path.is_file():
        logger.warning(f"Job {job_id}: Vocals file missing or not a file: {vocals_path}. Skipping transcription.")
        return [], None

    try:
        if vocals_path.stat().st_size < 1024:
            logger.warning(f"Job {job_id}: Vocals file too small (<1KB): {vocals_path}. Skipping transcription.")
            return [], None
    except FileNotFoundError:
        logger.warning(f"Job {job_id}: Vocals file not found during size check: {vocals_path}. Skipping transcription.")
        return [], None
    except Exception as stat_err:
        logger.warning(f"Job {job_id}: Error checking vocals file size {vocals_path}: {stat_err}. Skipping transcription.")
        return [], None

    try:
        processed_segments, full_result = await asyncio.to_thread(
            _transcribe_audio_sync, model, vocals_path, language, job_id, model_tag, settings.DEVICE
        )

        # Save to cache if video_id and processed_dir provided
        if video_id and processed_dir and processed_segments:
            try:
                whisper_version = get_whisper_version()
                cache_path = _get_transcription_cache_path(processed_dir, video_id, model_tag, lang_for_cache)
                _save_transcription_cache(cache_path, processed_segments, full_result, whisper_version, model_tag, lang_for_cache)
                update_transcription_cache_metadata(processed_dir, video_id, model_tag, lang_for_cache)
                logger.info(f"Job {job_id}: Saved transcription to cache")
            except Exception as cache_err:
                logger.warning(f"Job {job_id}: Failed to save transcription cache: {cache_err}")

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
    ) -> Tuple[List[Dict], Optional[Any]]:
    logger.info(f"Job {job_id}: Transcribing '{vocals_path.name}' (model: {model_tag}, lang: {language or 'auto'}, device: {device}, word_timestamps=True)...")
    # fp16 only works reliably on CUDA, not on MPS or CPU
    use_fp16 = (device == "cuda")

    # Build initial prompt for better language recognition
    initial_prompt = None
    if language and language != "auto":
        # Language-specific prompts help with recognition accuracy
        lang_prompts = {
            "ru": "Это русская песня с чётким произношением слов.",
            "en": "This is an English song with clear pronunciation.",
            "ja": "これは日本語の歌です。",
            "ko": "이것은 한국어 노래입니다.",
            "zh": "这是一首中文歌曲。",
        }
        initial_prompt = lang_prompts.get(language)

    transcribe_args = {
        "word_timestamps": True,
        "fp16": use_fp16,
        "language": language if (language and language != "auto") else None,
        "beam_size": 5,
        "temperature": 0.0,
        "patience": 2.0,  # Higher patience for better accuracy
        "condition_on_previous_text": False,  # Prevent error propagation between segments
        "compression_ratio_threshold": 2.4,  # Default, helps filter bad segments
        "no_speech_threshold": 0.6,  # Default, helps with music sections
    }

    if initial_prompt:
        transcribe_args["initial_prompt"] = initial_prompt

    if transcribe_args["language"] is None:
        del transcribe_args["language"]


    full_result: Optional[Any] = None
    try:
        logger.debug(f"Job {job_id}: Calling model.transcribe with args: {transcribe_args}")
        full_result = model.transcribe(str(vocals_path.resolve()), **transcribe_args)
        logger.debug(f"Job {job_id}: model.transcribe call finished.")

        if not full_result or not isinstance(full_result, dict) or 'segments' not in full_result or not isinstance(full_result['segments'], list):
            full_text = full_result.get('text', '(no text found)') if isinstance(full_result, dict) else '(invalid result type)'
            logger.warning(f"Job {job_id}: Whisper transcription returned no valid segments structure. Full text: '{full_text[:100]}...'")
            return [], full_result

        processed_segments = []
        num_raw_segments = len(full_result['segments'])
        num_processed_words = 0
        num_segments_skipped = 0

        for seg_index, seg in enumerate(full_result['segments']):
            if not isinstance(seg, dict):
                logger.warning(f"Job {job_id}: Skipping invalid segment data (not a dict) at index {seg_index}.")
                num_segments_skipped += 1
                continue

            start_time = seg.get('start')
            end_time = seg.get('end')
            text = seg.get('text', "").strip()
            words_data = seg.get('words', [])

            if not text or start_time is None or end_time is None or not isinstance(start_time, (int, float)) or not isinstance(end_time, (int, float)) or end_time < start_time:
                logger.warning(f"Job {job_id}: Skipping segment index {seg_index} due to missing/invalid timing or empty text: Start={start_time}, End={end_time}, Text='{text[:30]}...'")
                num_segments_skipped += 1
                continue

            valid_words = []
            if isinstance(words_data, list):
                for word_index, word_info in enumerate(words_data):
                     word_key = 'word' if 'word' in word_info else 'text'
                     if (isinstance(word_info, dict) and
                         word_key in word_info and 'start' in word_info and 'end' in word_info and
                         isinstance(word_info[word_key], str) and
                         isinstance(word_info['start'], (int, float)) and
                         isinstance(word_info['end'], (int, float)) and
                         word_info['end'] >= word_info['start']):

                         cleaned_word_text = word_info[word_key].strip()
                         if not cleaned_word_text: continue

                         valid_words.append({
                             "text": cleaned_word_text,
                             "start": float(word_info['start']),
                             "end": float(word_info['end'])
                         })
                         num_processed_words += 1
                     else:
                        pass

            if text and valid_words:
                processed_segments.append({
                    "start": float(start_time),
                    "end": float(end_time),
                    "text": text,
                    "words": valid_words
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

        return processed_segments, full_result

    except TypeError as te:
        logger.error(f"Job {job_id}: TypeError during Whisper transcription: {te}", exc_info=True)
        if "unexpected keyword argument" in str(te).lower(): # More generic check
            raise RuntimeError("Whisper transcription failed: Mismatch in expected arguments for transcribe. Check library version compatibility or arguments.") from te
        else:
            raise RuntimeError(f"Whisper transcription failed due to TypeError: {te}") from te
    except Exception as e:
        logger.error(f"Job {job_id}: Whisper transcription process failed inside _transcribe_audio_sync: {e}", exc_info=True)
        if isinstance(e, FileNotFoundError):
             raise FileNotFoundError(f"Whisper failed: Input audio file not found at {vocals_path}") from e
        elif "CUDA" in str(e).upper() and device == "cuda":
             if "out of memory" in str(e).lower():
                  raise RuntimeError(f"Whisper CUDA Error: Out of memory on device '{device}'. Try a smaller model or restart runtime.") from e
             else:
                  raise RuntimeError(f"Whisper CUDA error during transcription on device '{device}': {e}. Check GPU/driver/torch setup.") from e
        else:
             raise RuntimeError(f"Whisper transcription failed: {e}") from e