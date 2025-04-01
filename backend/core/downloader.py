# File: backend/core/downloader.py
import asyncio
import logging
from pathlib import Path
from typing import Tuple, Optional, List, Dict
import yt_dlp

from utils.file_system import find_existing_file, COMMON_VIDEO_FORMATS, COMMON_AUDIO_FORMATS

logger = logging.getLogger(__name__)

async def download_video(job_id: str, url_or_search: str, download_dir: Path) -> Tuple[str, Path, str, str]:
    """
    Downloads video/audio using yt-dlp or searches and downloads the first result.
    Returns: (video_id, downloaded_path, title, uploader)
    Runs the synchronous download function in a separate thread.
    """
    try:
        # Ensure download directory exists
        download_dir.mkdir(parents=True, exist_ok=True)

        video_id, video_path, title, uploader = await asyncio.to_thread(
            _download_video_sync, url_or_search, job_id, download_dir
        )
        if not video_id or not video_path:
             raise ValueError("Download failed to return a valid video ID or path.")
        return video_id, video_path, title, uploader
    except Exception as e:
        logger.error(f"Download step failed for job {job_id}: {e}", exc_info=True)
        # Propagate a cleaner error message
        raise ValueError(f"Download failed: {e}") from e

def _download_video_sync(url_or_search: str, job_id: str, download_dir: Path) -> Tuple[str, Path, str, str]:
    """
    Synchronous function to download video using yt-dlp.
    Handles search vs URL, caching, and error reporting.
    """
    is_search = not (url_or_search.startswith("http://") or url_or_search.startswith("https://"))
    target_input = url_or_search

    logger.info(f"Job {job_id}: yt-dlp: Processing input: '{target_input[:100]}...'")

    output_template_pattern = str(download_dir / '%(id)s.%(ext)s')

    ydl_opts = {
        'format': 'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/best[height<=1080]/best',
        'outtmpl': output_template_pattern,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'socket_timeout': 45, # Increased slightly
        'retries': 3,
        'default_search': 'ytsearch1', # Only 1 result needed for actual download
        # 'verbose': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info(f"Job {job_id}: Extracting video info for: '{target_input[:100]}...'")
            info = ydl.extract_info(target_input, download=False)

            if not info:
                 raise ValueError("yt-dlp extract_info returned no data.")

            if 'entries' in info and info['entries']:
                 logger.debug(f"Job {job_id}: Search result detected, using first entry for download.")
                 info = info['entries'][0]

            video_id = info.get('id')
            if not video_id:
                raise ValueError("Could not extract video ID from metadata.")

            title = info.get('title', 'Unknown Title')
            uploader = info.get('uploader', 'Unknown Uploader')
            logger.info(f"Job {job_id}: Found video: ID={video_id}, Title='{title[:60]}...', Uploader='{uploader[:40]}...'")

            existing_path = find_existing_file(download_dir, video_id, COMMON_VIDEO_FORMATS + COMMON_AUDIO_FORMATS)
            if existing_path:
                 logger.info(f"Job {job_id}: [CACHE] Using existing download for {video_id}: {existing_path}")
                 return video_id, existing_path, title, uploader

            logger.info(f"Job {job_id}: Downloading video {video_id} ('{title[:60]}...')...")
            download_target = info.get('webpage_url') or info.get('original_url') or f"https://https://www.youtube.com/watch?v=dQw4w9WgXcQ?v={video_id}"
            # Re-init ydl *with download=True* (implicit in ydl.download)
            # No need for a separate 'download=True' ydl instance
            ydl.download([download_target])

            downloaded_path = find_existing_file(download_dir, video_id, COMMON_VIDEO_FORMATS + COMMON_AUDIO_FORMATS)
            if not downloaded_path:
                 files_in_downloads = [f.name for f in download_dir.iterdir() if f.is_file()]
                 logger.error(f"Job {job_id}: Downloaded file for {video_id} not found in {download_dir} after download call. Files present: {files_in_downloads}")
                 raise FileNotFoundError(f"Downloaded file for {video_id} not found post-download.")

            logger.info(f"Job {job_id}: Successfully downloaded video to: {downloaded_path}")
            return video_id, downloaded_path, title, uploader

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"Job {job_id}: yt-dlp download error for '{target_input[:100]}...': {e}", exc_info=False)
        error_str = str(e).lower()
        if "unsupported url" in error_str: raise ValueError(f"Unsupported URL provided.")
        elif "video unavailable" in error_str: raise ValueError(f"Video is unavailable.")
        elif "private video" in error_str: raise ValueError(f"Video is private.")
        elif "live event will begin" in error_str: raise ValueError(f"Video is a future live event.")
        elif "urlopen error" in error_str or "timed out" in error_str: raise ConnectionError(f"Network error during download.")
        elif "no search results" in error_str: raise ValueError(f"No search results found for '{url_or_search}'.")
        else: raise ValueError(f"Download error occurred: {e}") # Include original error message
    except Exception as e:
        logger.error(f"Job {job_id}: Unexpected error during download for '{target_input[:100]}...': {e}", exc_info=True)
        raise RuntimeError(f"An unexpected download error occurred.")

# *** Reduced max_results to 4 ***
async def get_youtube_suggestions(query: str, max_results: int = 4) -> List[Dict]:
    """
    Fetches YouTube video suggestions using yt-dlp in a separate thread.
    Returns list of suggestion dicts or empty list on error.
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Fetching suggestions for query: '{query[:100]}' (max: {max_results})")
    results = []
    query_stripped = query.strip()

    try:
        target_query = query_stripped

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'socket_timeout': 15, # Shorter timeout for suggestions
            'retries': 2,
            'dump_single_json': True,
            'extract_flat': 'discard_in_playlist',
             # *** Use max_results from function argument ***
            'default_search': f'ytsearch{max_results}',
            # 'verbose': True,
        }

        def run_ydl():
            thread_logger = logging.getLogger(__name__ + ".ydl_thread")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    thread_logger.debug(f"Running extract_info for suggestions: {target_query[:100]}")
                    info = ydl.extract_info(target_query, download=False)
                    return info
                except yt_dlp.utils.DownloadError as dl_err:
                     if "no search results" in str(dl_err).lower():
                          thread_logger.warning(f"No search results found for: {target_query[:100]}")
                     else:
                          thread_logger.warning(f"yt-dlp DownloadError getting suggestions for '{target_query[:100]}': {dl_err}")
                     return None
                except Exception as inner_e:
                     thread_logger.error(f"Unexpected error inside yt-dlp for suggestions '{target_query[:100]}': {inner_e}", exc_info=False)
                     return None

        info = await asyncio.to_thread(run_ydl)

        if info:
            if 'entries' in info:
                for entry in info['entries']:
                    parsed = _parse_ydl_entry(entry)
                    if parsed: results.append(parsed)
            elif info.get('id'):
                 parsed = _parse_ydl_entry(info)
                 if parsed: results.append(parsed)

    except Exception as e:
        logger.error(f"Unexpected error getting suggestions for '{query_stripped[:100]}': {e}", exc_info=True)
        return []

    unique_results = []
    seen_ids = set()
    for res in results:
        if res and isinstance(res, dict) and res.get("id") and res["id"] not in seen_ids:
            unique_results.append(res)
            seen_ids.add(res["id"])

    logger.info(f"Returning {len(unique_results)} unique suggestions for '{query_stripped[:100]}...'")
    return unique_results


def _parse_ydl_entry(entry: Dict) -> Optional[Dict]:
    """Helper to parse a yt-dlp info dictionary into our suggestion format."""
    entry_type = entry.get('_type', 'video')
    if entry_type not in ['video', 'url'] or entry.get('ie_key') in ['YoutubePlaylist', 'YoutubeChannel']:
        return None

    video_id = entry.get("id")
    if not video_id: return None

    title = entry.get("title", "Unknown Title").strip()
    thumbnail_url = entry.get("thumbnail")
    thumbnails_list = entry.get("thumbnails")

    # Prioritize higher quality thumbnail
    if isinstance(thumbnails_list, list) and thumbnails_list:
         hq_thumb = next((t.get('url') for t in reversed(thumbnails_list) if t.get('url') and t.get('width', 0) >= 300), None)
         mq_thumb = next((t.get('url') for t in reversed(thumbnails_list) if t.get('url') and t.get('width', 0) >= 121), None) # Medium quality as fallback
         best_thumb = thumbnails_list[-1].get('url') if thumbnails_list else None
         thumbnail_url = hq_thumb or mq_thumb or best_thumb or thumbnail_url

    # Ensure URL is valid
    url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
    if not url and video_id: url = f"https://https://www.youtube.com/watch?v=dQw4w9WgXcQ?v={video_id}"
    elif not url: return None # Skip if no usable URL

    return { "id": video_id, "title": title, "thumbnail": thumbnail_url, "url": url }