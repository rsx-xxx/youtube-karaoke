# File: backend/core/separator.py
import asyncio
import logging
import subprocess
import sys
import time
import os
from pathlib import Path
from typing import Tuple, Dict, Optional, List

import ffmpeg as ffmpeg_python
from ..config import settings
from ..utils.version_tracker import (
    get_file_hash,
    is_stems_cache_valid,
    update_stems_cache_metadata
)

logger = logging.getLogger(__name__)

# Expected stem filenames relative to the *final* Demucs output subdirectory
# e.g., .../processed/VIDEO_ID/htdemucs/htdemucs/INPUT_STEM_NAME/vocals.wav
DEMUCS_EXPECTED_STEMS_RELATIVE: List[str] = ["vocals.wav", "drums.wav", "bass.wav", "other.wav"]
# Output filename for the combined instrumental track (will be placed alongside other stems)
INSTRUMENTAL_STEM_FILENAME: str = "instrumental.wav"
# Key stem filename used for transcription and primary output check
VOCALS_STEM_FILENAME: str = "vocals.wav"

async def separate_tracks(
    job_id: str,
    audio_path: Path,
    video_id: str,
    processed_dir: Path,
    demucs_model: str,
    device: str
) -> Tuple[Path, Path, Path]:
    """
    Separates audio using Demucs. Output is expected in a deeply nested structure:
    .../processed/VIDEO_ID/MODEL_NAME/MODEL_NAME/INPUT_AUDIO_STEM/*.wav (based on demucs logs)
    Returns (instrumental_path, vocals_path, actual_stems_directory)
    """
    if not audio_path or not audio_path.stem:
         raise ValueError(f"Job {job_id}: Invalid audio path or could not get stem name from {audio_path}")
    input_audio_stem = audio_path.stem

    # Base directory for the model's output passed to --out
    model_base_output_dir = processed_dir / video_id / demucs_model
    # *** ACTUAL directory where Demucs places stems (based on logs: includes model name AND input stem name) ***
    actual_stems_dir = model_base_output_dir / demucs_model / input_audio_stem
    actual_stems_dir.mkdir(parents=True, exist_ok=True) # Ensure the final target directory exists

    # Check cache in the ACTUAL stems directory (with version validation)
    instrumental_path_cache, vocals_path_cache = get_existing_stems(
        actual_stems_dir,
        video_id=video_id,
        demucs_model=demucs_model,
        audio_path=audio_path,
        processed_dir=processed_dir
    )
    if instrumental_path_cache and vocals_path_cache:
        logger.info(f"Job {job_id}: [CACHE] Using cached stems for {video_id}/{input_audio_stem} model {demucs_model} in {actual_stems_dir}")
        return instrumental_path_cache, vocals_path_cache, actual_stems_dir

    logger.info(f"Job {job_id}: No valid cache found in {actual_stems_dir}. Proceeding with separation.")
    try:
        # Pass the BASE output directory to the sync function (Demucs creates the nested ones)
        instrumental_path, vocals_path = await asyncio.to_thread(
            _separate_tracks_sync, audio_path, job_id, model_base_output_dir, actual_stems_dir, demucs_model, device
        )
        if not instrumental_path or not vocals_path:
            raise RuntimeError("Track separation sync function failed to return valid paths.")
        if not instrumental_path.exists() or not vocals_path.exists():
            missing = []
            if not instrumental_path.exists(): missing.append(instrumental_path.name)
            if not vocals_path.exists(): missing.append(vocals_path.name)
            logger.error(f"Job {job_id}: Post-thread check failed. Missing files {missing} in {actual_stems_dir}")
            raise FileNotFoundError(f"Separation function finished but output stem file(s) not found post-thread: Missing {missing} in {actual_stems_dir}")

        logger.info(f"Job {job_id}: Separation successful. Instrumental: {instrumental_path}, Vocals: {vocals_path}, Dir: {actual_stems_dir}")

        # Update cache metadata with model version info
        try:
            audio_hash = get_file_hash(audio_path)
            update_stems_cache_metadata(processed_dir, video_id, demucs_model, audio_hash)
            logger.info(f"Job {job_id}: Saved stems cache metadata for {video_id}")
        except Exception as cache_err:
            logger.warning(f"Job {job_id}: Failed to save stems cache metadata: {cache_err}")

        return instrumental_path, vocals_path, actual_stems_dir

    except Exception as e:
        logger.error(f"Track separation step failed for job {job_id}: {e}", exc_info=True)
        # Re-raise specific errors for better handling upstream if needed
        if isinstance(e, FileNotFoundError):
            raise FileNotFoundError(f"Demucs output verification failed: {e}") from e
        elif isinstance(e, TimeoutError):
            raise TimeoutError(f"Demucs separation timed out: {e}") from e
        raise RuntimeError(f"Track separation failed: {e}") from e


def _separate_tracks_sync(
    audio_path: Path,
    job_id: str,
    model_base_output_dir: Path, # Directory passed to --out
    actual_stems_dir: Path,      # Directory where files are EXPECTED (e.g., .../htdemucs/htdemucs/INPUT_STEM/)
    demucs_model: str,
    device: str
) -> Tuple[Path, Path]:
    """
    Synchronous function to separate audio using Demucs.
    Runs the command and then verifies output in the `actual_stems_dir`.
    """
    input_audio_stem = audio_path.stem # Needed for logging and potential fallback checks
    logger.info(f"Job {job_id}: Running Demucs (model: {demucs_model}, device: {device}) on '{audio_path.name}' (stem: '{input_audio_stem}')...")
    logger.info(f"Job {job_id}: Demucs '--out' parameter set to: {model_base_output_dir}")
    logger.info(f"Job {job_id}: Expecting actual stem files in: {actual_stems_dir}")

    resolved_audio_path = audio_path.resolve()
    resolved_base_output_dir = model_base_output_dir.resolve()

    cmd = [
        sys.executable, "-m", "demucs.separate",
        "--out", str(resolved_base_output_dir),
        "-n", demucs_model,
        '-d', device,
        str(resolved_audio_path)
    ]
    logger.debug(f"Job {job_id}: Demucs command: {' '.join(cmd)}")

    # --- Run Demucs Process ---
    try:
        process = subprocess.run(
            cmd, check=True, capture_output=True, text=True, encoding='utf-8', timeout=settings.DEMUCS_TIMEOUT
        )
        # Always log stdout/stderr from Demucs for debugging purposes
        if process.stdout: logger.info(f"Job {job_id}: Demucs stdout:\n{process.stdout.strip()}")
        if process.stderr: logger.info(f"Job {job_id}: Demucs stderr:\n{process.stderr.strip()}") # Log stderr even on success
        logger.info(f"Job {job_id}: Demucs process finished with exit code {process.returncode}.")

    except subprocess.TimeoutExpired:
        logger.error(f"Job {job_id}: Demucs command timed out after {settings.DEMUCS_TIMEOUT} seconds.")
        raise TimeoutError(f"Demucs separation timed out after {settings.DEMUCS_TIMEOUT}s.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Job {job_id}: Demucs failed with exit code {e.returncode}")
        if e.stdout: logger.error(f"Demucs stdout (on error):\n{e.stdout.strip()}")
        stderr_output = e.stderr.strip() if e.stderr else "No stderr captured."
        logger.error(f"Demucs stderr (on error):\n{stderr_output}")
        last_err_line = stderr_output.splitlines()[-1] if stderr_output else "Unknown Demucs error"
        raise RuntimeError(f"Demucs separation failed: {last_err_line}") from e
    except Exception as e:
        logger.error(f"Job {job_id}: Unexpected error running Demucs command: {e}", exc_info=True)
        raise RuntimeError(f"Unexpected error during track separation command: {e}") from e

    # --- Verification Step ---
    logger.info(f"Job {job_id}: Waiting briefly after Demucs process completion before verification...")
    time.sleep(1.5)

    # *** Verify in the ACTUAL stems directory ***
    logger.info(f"Job {job_id}: Starting verification for stem files in ACTUAL target directory: {actual_stems_dir}")
    if not actual_stems_dir.is_dir():
         logger.error(f"Job {job_id}: Verification failed: Expected ACTUAL stems directory '{actual_stems_dir}' does not exist.")
         # Log content of parent to see what happened
         parent_dir = actual_stems_dir.parent
         parent_content = []
         try:
             parent_content = [p.name for p in parent_dir.iterdir()] if parent_dir.is_dir() else f"Parent '{parent_dir}' not found"
         except Exception as list_e: parent_content = [f"Error listing parent: {list_e}"]
         logger.error(f"Job {job_id}: Contents of parent directory '{parent_dir}': {parent_content}")
         raise FileNotFoundError(f"Demucs did not create the expected ACTUAL output directory: {actual_stems_dir}")

    # Get expected paths *within* the actual_stems_dir
    stem_paths = get_stem_paths(actual_stems_dir) # Pass the correct dir
    missing_stems = []
    wait_start_time = time.monotonic()
    all_found_valid = False
    last_logged_missing = None
    loop_count = 0

    # Verification loop
    while time.monotonic() - wait_start_time < settings.DEMUCS_WAIT_TIMEOUT:
        loop_count += 1
        missing_stems = []
        all_found_valid = True

        # Check only for the core stems Demucs creates directly
        for stem_name in DEMUCS_EXPECTED_STEMS_RELATIVE:
             p = stem_paths.get(stem_name) # Should exist based on get_stem_paths call
             if not p: # Should not happen if get_stem_paths is correct
                  missing_stems.append(f"{stem_name}(path_error)")
                  all_found_valid = False
                  continue
             try:
                if not p.is_file():
                    missing_stems.append(p.name)
                    all_found_valid = False
                elif p.stat().st_size < 1024:
                    missing_stems.append(f"{p.name}(small)")
                    all_found_valid = False
             except FileNotFoundError:
                 missing_stems.append(f"{p.name}(not found)")
                 all_found_valid = False
                 # Don't break here, check others too
             except Exception as stat_e:
                 logger.warning(f"Job {job_id}: Error checking file {p.name}: {stat_e}")
                 missing_stems.append(f"{p.name}(check error)")
                 all_found_valid = False

        if all_found_valid:
            logger.info(f"Job {job_id}: Found all expected core stem files in {actual_stems_dir} after {time.monotonic() - wait_start_time:.2f}s (Loop {loop_count}).")
            break

        current_missing_str = ", ".join(missing_stems)
        if current_missing_str != last_logged_missing:
             logger.warning(f"Job {job_id} Loop {loop_count}: Waiting for CORE stem files in {actual_stems_dir}. Still missing/small: [{current_missing_str}]")
             try:
                 # Log directory content for debugging
                 dir_content = os.listdir(actual_stems_dir)
                 logger.warning(f"Job {job_id} Loop {loop_count}: Directory content of '{actual_stems_dir}': {dir_content}")
             except Exception as list_e:
                 logger.warning(f"Job {job_id} Loop {loop_count}: Error listing directory '{actual_stems_dir}': {list_e}")
             last_logged_missing = current_missing_str

        time.sleep(settings.DEMUCS_CHECK_INTERVAL)

    if not all_found_valid:
        wait_duration = time.monotonic() - wait_start_time
        logger.error(f"Job {job_id}: Verification FAILED. Demucs did not produce all required/valid CORE stem files in '{actual_stems_dir}' after waiting {wait_duration:.1f}s.")
        logger.error(f"Job {job_id}: Final missing or small CORE stems: {missing_stems}")
        try:
             final_contents = [f"{p.name} ({p.stat().st_size if p.is_file() else 'N/A'}b)" for p in actual_stems_dir.iterdir()]
        except Exception as e: final_contents = [f"Error listing dir: {e}"]
        logger.error(f"Job {job_id}: Final contents of {actual_stems_dir}: {final_contents}")
        raise FileNotFoundError(f"Demucs did not produce all required/valid CORE stems in {actual_stems_dir.name}. Missing/Empty: {missing_stems}")

    # --- Create Instrumental Track ---
    vocals_out_path = stem_paths.get(VOCALS_STEM_FILENAME) # Path to vocals stem
    instrumental_out_path = stem_paths.get(INSTRUMENTAL_STEM_FILENAME) # Path for the combined instrumental (uses get_stem_paths logic)

    # Collect paths for non-vocal stems needed for the instrumental mix
    input_stems_for_instrumental = [
        stem_paths[name] for name in DEMUCS_EXPECTED_STEMS_RELATIVE if name != VOCALS_STEM_FILENAME and name in stem_paths
    ]

    # Verify required input stems exist and are valid before trying to mix
    missing_inputs = [p.name for p in input_stems_for_instrumental if not p or not p.is_file() or p.stat().st_size < 1024]
    if missing_inputs:
        logger.error(f"Job {job_id}: Cannot create instrumental track. Missing/empty input stems: {missing_inputs} in {actual_stems_dir}")
        raise FileNotFoundError(f"Cannot create instrumental track due to missing/empty input stems: {missing_inputs}")
    if not vocals_out_path or not vocals_out_path.is_file() or vocals_out_path.stat().st_size < 1024:
        logger.error(f"Job {job_id}: Required vocal stem file missing or empty: {vocals_out_path}")
        raise FileNotFoundError(f"Required vocal stem file missing or empty: {VOCALS_STEM_FILENAME}")
    if not instrumental_out_path: # Should be set by get_stem_paths
         logger.error(f"Job {job_id}: Could not determine path for instrumental output file.")
         raise ValueError("Instrumental output path could not be determined.")

    logger.info(f"Job {job_id}: Creating instrumental track -> {instrumental_out_path.name} in {instrumental_out_path.parent}")
    try:
        # High-quality mixing using amerge + pan for proper stereo summing
        # This avoids the volume normalization issues of amix
        ffmpeg_inputs = [ffmpeg_python.input(str(p)) for p in input_stems_for_instrumental]

        # Use amerge to combine all inputs, then pan to mix down to stereo
        # This preserves the original levels better than amix
        num_inputs = len(ffmpeg_inputs)
        amerge_stream = ffmpeg_python.filter(ffmpeg_inputs, 'amerge', inputs=num_inputs)
        # Pan filter to mix multiple stereo inputs into single stereo output
        # Each input contributes equally
        pan_expr = f"stereo|FL<{'+'.join([f'c{i*2}' for i in range(num_inputs)])}|FR<{'+'.join([f'c{i*2+1}' for i in range(num_inputs)])}"
        mixed_stream = ffmpeg_python.filter(amerge_stream, 'pan', pan_expr)
        # Normalize volume to prevent clipping
        mixed_stream = ffmpeg_python.filter(mixed_stream, 'dynaudnorm', p=0.9, s=5)
        output_stream = ffmpeg_python.output(mixed_stream, str(instrumental_out_path), acodec='pcm_s24le', ar='48000', loglevel="warning")
        # Run ffmpeg command
        stdout, stderr = ffmpeg_python.run(output_stream, capture_stdout=True, capture_stderr=True, overwrite_output=True)
        # Log ffmpeg output for debugging if needed
        # if stdout: logger.debug(f"FFmpeg stdout (instrumental):\n{stdout.decode(errors='ignore')}")
        # if stderr: logger.debug(f"FFmpeg stderr (instrumental):\n{stderr.decode(errors='ignore')}")

        if not instrumental_out_path.is_file() or instrumental_out_path.stat().st_size < 1024:
            raise RuntimeError("ffmpeg command ran but failed to create a valid instrumental track.")
        logger.info(f"Job {job_id}: Instrumental track created successfully: {instrumental_out_path.name}")

    except ffmpeg_python.Error as e:
        stderr_msg = e.stderr.decode(errors='ignore') if e.stderr else 'No stderr'
        logger.error(f"Job {job_id}: ffmpeg error creating instrumental track:\n{stderr_msg}")
        raise RuntimeError(f"Failed to create instrumental track: {stderr_msg.strip().splitlines()[-1] if stderr_msg.strip() else 'ffmpeg error'}") from e
    except Exception as e:
        logger.error(f"Job {job_id}: Unexpected error creating instrumental track: {e}", exc_info=True)
        raise RuntimeError(f"Unexpected error creating instrumental track: {e}") from e

    # Return the paths to the essential generated files (vocals + combined instrumental)
    return instrumental_out_path, vocals_out_path


# --- Helper functions for checking cache ---

def get_stem_paths(actual_stems_dir: Path) -> Dict[str, Path]:
    """
    Constructs the expected paths for CORE stem files plus the combined instrumental
    within the *actual* Demucs output directory (e.g., .../htdemucs/htdemucs/INPUT_STEM/).
    """
    if not actual_stems_dir or not actual_stems_dir.is_dir(): # Check if the *actual* dir exists
         # logger.error(f"get_stem_paths called with invalid actual_stems_dir: {actual_stems_dir}") # Less verbose
         return {}

    # Paths are relative to the actual_stems_dir where Demucs puts them
    paths = { name: actual_stems_dir / name for name in DEMUCS_EXPECTED_STEMS_RELATIVE }
    # Add the path for the instrumental file we *will* create in this same directory
    paths[INSTRUMENTAL_STEM_FILENAME] = actual_stems_dir / INSTRUMENTAL_STEM_FILENAME
    return paths

def get_existing_stems(
    actual_stems_dir: Path,
    video_id: Optional[str] = None,
    demucs_model: Optional[str] = None,
    audio_path: Optional[Path] = None,
    processed_dir: Optional[Path] = None
) -> Tuple[Optional[Path], Optional[Path]]:
    """
    Checks if essential stem files (instrumental, vocals) exist and are valid
    in the specified *actual* Demucs output directory. Also validates cache metadata
    for model/version match if video_id and demucs_model are provided.
    Returns their paths if found and valid, else (None, None).
    """
    if not actual_stems_dir or not actual_stems_dir.is_dir():
        return None, None

    # Check version-aware cache metadata if parameters provided
    if video_id and demucs_model and processed_dir:
        if not is_stems_cache_valid(processed_dir, video_id, demucs_model, audio_path):
            logger.info(f"[CACHE] Stems cache metadata invalid for {video_id}")
            return None, None

    # Use get_stem_paths to determine the expected full paths
    expected_paths = get_stem_paths(actual_stems_dir)
    instrumental_path = expected_paths.get(INSTRUMENTAL_STEM_FILENAME)
    vocals_path = expected_paths.get(VOCALS_STEM_FILENAME)

    if not instrumental_path or not vocals_path:
        logger.warning(f"[CACHE] Could not determine expected paths for instrumental/vocals in {actual_stems_dir}")
        return None, None

    instrumental_ok = False
    vocals_ok = False

    try:
        if instrumental_path.is_file() and instrumental_path.stat().st_size > 1024:
            instrumental_ok = True
        if vocals_path.is_file() and vocals_path.stat().st_size > 1024:
            vocals_ok = True
    except FileNotFoundError:
        return None, None
    except Exception as e:
        logger.warning(f"[CACHE] Error during file stat check in {actual_stems_dir}: {e}")
        return None, None

    if instrumental_ok and vocals_ok:
        return instrumental_path, vocals_path
    else:
        return None, None