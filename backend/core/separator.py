# File: backend/core/separator.py
import asyncio
import logging
import subprocess
import sys
import time
import os
from pathlib import Path
from typing import Tuple, Dict, Optional

import ffmpeg as ffmpeg_python
from config import settings

logger = logging.getLogger(__name__)

DEMUCS_EXPECTED_STEMS = ["vocals.wav", "drums.wav", "bass.wav", "other.wav"]
INSTRUMENTAL_STEM_FILENAME = "instrumental.wav"
VOCALS_STEM_FILENAME = "vocals.wav"

async def separate_tracks(
    job_id: str,
    audio_path: Path,
    video_id: str,
    processed_dir: Path,
    demucs_model: str,
    device: str
) -> Tuple[Path, Path, Path]:
    """
    Separates audio using Demucs. Adjusted to expect output structure based on logs:
    .../VIDEO_ID/MODEL_NAME/INPUT_STEM/*.wav
    """
    input_stem = audio_path.stem # Get the base name of the input audio file (e.g., 'OZxLbNQtPRA')
    if not input_stem:
        raise ValueError(f"Could not determine input stem from audio path: {audio_path}")

    instrumental_path_cache, vocals_path_cache, stems_dir_cache = get_existing_stems(video_id, processed_dir, demucs_model, input_stem)
    if instrumental_path_cache and vocals_path_cache and stems_dir_cache:
        logger.info(f"Job {job_id}: [CACHE] Using cached stems for {video_id} (stem: {input_stem}) model {demucs_model} in {stems_dir_cache}")
        return instrumental_path_cache, vocals_path_cache, stems_dir_cache

    try:
        instrumental_path, vocals_path, stems_dir = await asyncio.to_thread(
            _separate_tracks_sync, audio_path, video_id, input_stem, job_id, processed_dir, demucs_model, device
        )
        if not instrumental_path or not vocals_path or not stems_dir:
             raise RuntimeError("Track separation sync function failed to return valid paths.")
        if not instrumental_path.exists() or not vocals_path.exists():
             missing = []
             if not instrumental_path.exists(): missing.append(instrumental_path.name)
             if not vocals_path.exists(): missing.append(vocals_path.name)
             logger.error(f"Job {job_id}: Post-thread check failed. Missing files {missing} in {stems_dir}")
             raise FileNotFoundError(f"Separation function finished but output stem file(s) not found post-thread: Missing {missing} in {stems_dir}")
        return instrumental_path, vocals_path, stems_dir
    except Exception as e:
        logger.error(f"Track separation step failed for job {job_id}: {e}", exc_info=True)
        if isinstance(e, FileNotFoundError):
             raise FileNotFoundError(f"Demucs output verification failed: {e}") from e
        elif isinstance(e, TimeoutError):
            raise TimeoutError(f"Demucs separation timed out: {e}") from e
        raise RuntimeError(f"Track separation failed: {e}") from e


def _separate_tracks_sync(
    audio_path: Path,
    video_id: str,
    input_stem: str, # Pass the input stem name
    job_id: str,
    processed_dir: Path,
    demucs_model: str,
    device: str
) -> Tuple[Path, Path, Path]:
    """
    Synchronous function to separate audio using Demucs.
    Uses simplified command: --out target_base_dir -n model_name
    *** Expects output in target_base_dir / model_name / input_stem / *.wav *** based on os.listdir logs
    """
    output_dir_job = processed_dir / video_id
    # *** Expected final stems location based on os.listdir log ***
    stems_output_dir = output_dir_job / demucs_model / input_stem

    logger.info(f"Job {job_id}: Running Demucs (model: {demucs_model}) on '{audio_path.name}' (input stem: '{input_stem}')...")
    output_dir_job.mkdir(parents=True, exist_ok=True) # Ensure parent exists

    resolved_audio_path = audio_path.resolve()
    resolved_output_dir_job = output_dir_job.resolve()

    # Use the simplified command, hoping Demucs creates the INPUT_STEM subfolder implicitly
    cmd = [
        sys.executable, "-m", "demucs.separate",
        "--out", str(resolved_output_dir_job), # Base output dir (e.g., .../VIDEO_ID/)
        "-n", demucs_model,                   # Model name (e.g., htdemucs)
        '-d', device,
        str(resolved_audio_path)
        # Demucs *should* create .../VIDEO_ID/htdemucs/INPUT_STEM/ based on logs
    ]
    logger.debug(f"Job {job_id}: Demucs command: {' '.join(cmd)}")
    logger.info(f"Job {job_id}: Expecting Demucs to create stem files in: {stems_output_dir}")

    try:
        process = subprocess.run(
            cmd, check=True, capture_output=True, text=True, encoding='utf-8', timeout=settings.DEMUCS_TIMEOUT
        )
        if process.stdout: logger.info(f"Job {job_id}: Demucs stdout:\n{process.stdout.strip()}")
        if process.stderr: logger.info(f"Job {job_id}: Demucs stderr:\n{process.stderr.strip()}")
        logger.info(f"Job {job_id}: Demucs process finished with exit code {process.returncode}.")

    except subprocess.TimeoutExpired:
         logger.error(f"Job {job_id}: Demucs command timed out after {settings.DEMUCS_TIMEOUT} seconds.")
         raise TimeoutError("Demucs separation timed out.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Job {job_id}: Demucs failed with exit code {e.returncode}")
        if e.stdout: logger.error(f"Demucs stdout (on error):\n{e.stdout.strip()}")
        if e.stderr: logger.error(f"Demucs stderr (on error):\n{e.stderr.strip()}")
        last_err_line = e.stderr.strip().splitlines()[-1] if e.stderr.strip() else "Unknown Demucs error"
        raise RuntimeError(f"Demucs separation failed: {last_err_line}") from e
    except Exception as e:
        logger.error(f"Job {job_id}: Unexpected error running Demucs command: {e}", exc_info=True)
        raise RuntimeError(f"Unexpected error during track separation command: {e}") from e

    logger.info(f"Job {job_id}: Waiting 2s after Demucs process completion before verification...")
    time.sleep(2.0)

    logger.info(f"Job {job_id}: Starting verification for stem files in target directory: {stems_output_dir}")

    # Check if the expected *nested* stems directory exists
    if not stems_output_dir.is_dir():
        logger.error(f"Job {job_id}: Verification failed: Expected nested stem output directory '{stems_output_dir}' does not exist.")
        # Log contents of the *parent* (model directory) this time
        model_dir = stems_output_dir.parent
        parent_contents = []
        try:
            parent_contents = [p.name for p in model_dir.iterdir()] if model_dir.is_dir() else f"Parent dir '{model_dir}' not found"
        except Exception as list_err:
            parent_contents = [f"Error listing parent '{model_dir}': {list_err}"]
        logger.error(f"Job {job_id}: Contents of parent (model dir) '{model_dir}': {parent_contents}")
        raise FileNotFoundError(f"Demucs did not create the expected nested output directory: {stems_output_dir.name}")
    else:
        logger.info(f"Job {job_id}: Target directory '{stems_output_dir}' exists.")


    # Verify individual stem files within the nested directory
    stem_paths = get_stem_paths(video_id, processed_dir, demucs_model, input_stem) # Uses nested path logic
    missing_stems = []
    wait_start_time = time.monotonic()
    all_found = False
    last_logged_missing = None
    loop_count = 0

    # Verification loop
    while time.monotonic() - wait_start_time < settings.DEMUCS_WAIT_TIMEOUT + 2:
        loop_count += 1
        missing_stems = []
        all_found = True

        for stem_name in DEMUCS_EXPECTED_STEMS:
            p = stem_paths.get(stem_name)
            if not p or not p.is_file():
                 missing_stems.append(p.name if p else stem_name)
                 all_found = False
                 continue
            try:
                 if p.stat().st_size < 1024:
                     missing_stems.append(f"{p.name}(small)")
                     all_found = False
            except FileNotFoundError:
                 missing_stems.append(f"{p.name}(disappeared)")
                 all_found = False

        if all_found:
             logger.info(f"Job {job_id}: Found all expected stem files in {stems_output_dir} after {time.monotonic() - wait_start_time:.2f}s (Loop {loop_count}).")
             break

        current_missing_str = ", ".join(missing_stems)
        if current_missing_str != last_logged_missing:
             logger.warning(f"Job {job_id} Loop {loop_count}: Waiting for stem files in {stems_output_dir}. Still missing/small: [{current_missing_str}]")
             try:
                  os_list = os.listdir(stems_output_dir)
                  logger.warning(f"Job {job_id} Loop {loop_count}: os.listdir content of '{stems_output_dir}': {os_list}")
             except Exception as e:
                  logger.warning(f"Job {job_id} Loop {loop_count}: Error using os.listdir on '{stems_output_dir}': {e}")
             last_logged_missing = current_missing_str

        time.sleep(settings.DEMUCS_CHECK_INTERVAL)

    if not all_found:
        wait_duration = time.monotonic() - wait_start_time
        logger.error(f"Job {job_id}: Verification FAILED. Demucs did not produce all required/valid stem files in '{stems_output_dir}' after waiting {wait_duration:.1f}s.")
        logger.error(f"Job {job_id}: Final missing or small stems: {missing_stems}")
        final_contents_path = []
        final_contents_os = []
        try: final_contents_path = [f"{p.name} ({p.stat().st_size}b)" for p in stems_output_dir.iterdir() if p.is_file()]
        except Exception as e: final_contents_path = [f"Error listing with Path: {e}"]
        try: final_contents_os = os.listdir(stems_output_dir)
        except Exception as e: final_contents_os = [f"Error listing with os: {e}"]
        logger.error(f"Job {job_id}: Final contents via Path: {final_contents_path}")
        logger.error(f"Job {job_id}: Final contents via os.listdir: {final_contents_os}")
        raise FileNotFoundError(f"Demucs did not produce all required/valid stems in '{stems_output_dir.name}'. Missing/Empty: {missing_stems}")

    # --- Create Instrumental Track ---
    instrumental_out_path = stem_paths.get(INSTRUMENTAL_STEM_FILENAME)
    vocals_out_path = stem_paths.get(VOCALS_STEM_FILENAME)
    drums_path = stem_paths.get("drums.wav")
    bass_path = stem_paths.get("bass.wav")
    other_path = stem_paths.get("other.wav")

    input_stems_for_instrumental = { "drums": drums_path, "bass": bass_path, "other": other_path }
    missing_inputs = [name for name, p in input_stems_for_instrumental.items() if not p or not p.is_file() or p.stat().st_size == 0]
    if missing_inputs:
        logger.error(f"Job {job_id}: Cannot create instrumental track. Missing/empty input stems: {missing_inputs} in {stems_output_dir}")
        raise FileNotFoundError(f"Cannot create instrumental track due to missing/empty input stems: {missing_inputs}")
    if not vocals_out_path or not vocals_out_path.is_file() or vocals_out_path.stat().st_size == 0:
        logger.error(f"Job {job_id}: Required vocal stem file missing or empty: {vocals_out_path}")
        raise FileNotFoundError(f"Required vocal stem file missing or empty: {vocals_out_path.name}")
    if not instrumental_out_path:
        logger.error(f"Job {job_id}: Could not determine path for instrumental output file.")
        raise ValueError("Instrumental output path could not be determined.")

    logger.info(f"Job {job_id}: Creating instrumental track -> {instrumental_out_path.name} in {instrumental_out_path.parent}")
    try:
        input_drums = ffmpeg_python.input(str(drums_path))
        input_bass = ffmpeg_python.input(str(bass_path))
        input_other = ffmpeg_python.input(str(other_path))
        stream = ffmpeg_python.filter(
            [input_drums, input_bass, input_other], 'amix', inputs=3, duration='first', dropout_transition=2
        )
        stream = ffmpeg_python.output(stream, str(instrumental_out_path), acodec='pcm_s16le', loglevel="warning")
        ffmpeg_python.run(stream, capture_stdout=True, capture_stderr=True, overwrite_output=True)
        if not instrumental_out_path.is_file() or instrumental_out_path.stat().st_size < 1024:
             raise RuntimeError("ffmpeg command ran but failed to create a valid instrumental track.")
        logger.info(f"Job {job_id}: Instrumental track created successfully: {instrumental_out_path.name}")
    except ffmpeg_python.Error as e:
        stderr = e.stderr.decode(errors='ignore') if e.stderr else 'No stderr'
        logger.error(f"Job {job_id}: ffmpeg error creating instrumental track:\n{stderr}")
        raise RuntimeError(f"Failed to create instrumental track: {stderr.strip().splitlines()[-1] if stderr.strip() else 'ffmpeg error'}") from e
    except Exception as e:
        logger.error(f"Job {job_id}: Unexpected error creating instrumental track: {e}", exc_info=True)
        raise RuntimeError(f"Unexpected error creating instrumental track: {e}") from e

    # Return paths using the nested structure: .../VIDEO_ID/MODEL/INPUT_STEM/
    return instrumental_out_path, vocals_out_path, stems_output_dir

# --- Helper functions for checking cache ---

def get_stem_paths(video_id: str, processed_dir: Path, demucs_model: str, input_stem: str) -> Dict[str, Path]:
    """
    Constructs the expected paths for stem files.
    *** Uses nested structure based on logs: processed/VIDEO_ID/MODEL/INPUT_STEM/*.wav ***
    """
    if not video_id or not demucs_model or not input_stem:
        logger.error("get_stem_paths called with invalid video_id, demucs_model, or input_stem")
        return {}
    # *** Adjusted stems_dir location based on os.listdir log ***
    stems_dir = processed_dir / video_id / demucs_model / input_stem

    paths = {
        stem_name: stems_dir / stem_name
        for stem_name in DEMUCS_EXPECTED_STEMS
    }
    paths[INSTRUMENTAL_STEM_FILENAME] = stems_dir / INSTRUMENTAL_STEM_FILENAME
    return paths

def stems_exist(video_id: str, processed_dir: Path, demucs_model: str, input_stem: str) -> bool:
    """
    Checks if all necessary files exist in the nested structure.
    """
    stem_paths = get_stem_paths(video_id, processed_dir, demucs_model, input_stem)
    if not stem_paths: return False

    # *** Check the nested stems_dir path ***
    stems_dir = processed_dir / video_id / demucs_model / input_stem
    if not stems_dir.is_dir():
         logger.debug(f"[CACHE] Stem check failed for {video_id}/{input_stem}: Expected nested stems directory '{stems_dir}' does not exist.")
         return False

    all_required_files = list(DEMUCS_EXPECTED_STEMS) + [INSTRUMENTAL_STEM_FILENAME]
    for stem_filename in all_required_files:
        p = stem_paths.get(stem_filename)
        if not p or not p.is_file():
             logger.debug(f"[CACHE] Stem check failed for {video_id}/{input_stem}: Missing file '{p.name if p else stem_filename}' in expected dir {stems_dir}")
             return False
        try:
            if p.stat().st_size < 1024:
                logger.debug(f"[CACHE] Stem check failed for {video_id}/{input_stem}: File '{p.name}' in {stems_dir} is too small (< 1KB).")
                return False
        except FileNotFoundError:
             logger.debug(f"[CACHE] Stem check failed for {video_id}/{input_stem}: File '{p.name}' not found during size check in {stems_dir}.")
             return False

    logger.info(f"[CACHE] All required stems found and valid in nested dir {stems_dir} for {video_id}/{input_stem}")
    return True

def get_existing_stems(video_id: str, processed_dir: Path, demucs_model: str, input_stem: str) -> Tuple[Optional[Path], Optional[Path], Optional[Path]]:
    """
    Returns paths from the nested directory if valid.
    """
    # Pass input_stem to stems_exist
    if stems_exist(video_id, processed_dir, demucs_model, input_stem):
        stem_paths = get_stem_paths(video_id, processed_dir, demucs_model, input_stem)
        instrumental = stem_paths.get(INSTRUMENTAL_STEM_FILENAME)
        vocals = stem_paths.get(VOCALS_STEM_FILENAME)
        # *** Get the nested stems_dir path ***
        stems_dir = processed_dir / video_id / demucs_model / input_stem

        if instrumental and vocals and stems_dir and instrumental.is_file() and vocals.is_file():
             logger.info(f"[CACHE] Returning existing stems from nested directory {stems_dir}")
             return instrumental, vocals, stems_dir
        else:
             logger.error(f"[CACHE] Inconsistency: stems_exist() passed for {video_id}/{input_stem} (nested path) but couldn't retrieve valid file paths/dir.")
    # else: logger.debug(f"[CACHE] Valid stems not found for {video_id}/{input_stem} in expected nested dir.")

    return None, None, None