# File: backend/core/downloader.py
# UPDATED: Switched to a more general yt-dlp format string. Added format string to error log.

import asyncio
import logging
import re # Import regex for URL check
from pathlib import Path
from typing import Tuple, Optional, List, Dict, Any # Added Any
import yt_dlp

from utils.file_system import find_existing_file, COMMON_VIDEO_FORMATS, COMMON_AUDIO_FORMATS
from config import settings # Import settings for timeouts/retries

logger = logging.getLogger(__name__)
logger_sugg = logging.getLogger(__name__ + ".suggestions") # Logger specific for suggestions

# More robust regex for YouTube URLs (including shorts, music, etc.)
YOUTUBE_URL_REGEX = re.compile(
    r'^(?:https?:\/\/)?(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)\/(?:watch\?v=|embed\/|v\/|shorts\/|playlist\?list=|channel\/|user\/)?([a-zA-Z0-9_-]{11})(?:\S+)?$'
)


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
        if not video_id or not video_path or not video_path.exists(): # Added path exists check
            raise ValueError("Download failed to return a valid video ID or existing path.")
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
    # Use regex to check if it looks like a valid YouTube URL
    is_url = bool(YOUTUBE_URL_REGEX.match(url_or_search))

    target_input = url_or_search
    # Use ytsearch1: prefix ONLY if it's NOT detected as a URL
    if not is_url:
        target_input = f"ytsearch1:{url_or_search}"
        logger.info(f"Job {job_id}: Input doesn't look like a YouTube URL, treating as search: '{target_input}'")
    else:
        logger.info(f"Job {job_id}: Input looks like a YouTube URL: '{target_input[:100]}...'")


    output_template_pattern = str(download_dir / '%(id)s.%(ext)s')

    # Using the most general format string for higher success rate.
    # Subsequent ffmpeg steps will handle conversion if needed.
    chosen_format_string = 'bestvideo+bestaudio/best'

    ydl_opts: Dict[str, Any] = {
        'format': chosen_format_string,
        'outtmpl': output_template_pattern,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'socket_timeout': settings.YTDLP_SOCKET_TIMEOUT,
        'retries': settings.YTDLP_RETRIES,
        'ignoreerrors': False, # Ensure errors are raised for format issues
        # 'verbose': True, # Uncomment for detailed yt-dlp logs during debugging
        # 'writethumbnail': True, # If you need thumbnail directly from yt-dlp
        # 'postprocessors': [{ # Example: If you wanted to ensure MP4 output directly from yt-dlp
        #     'key': 'FFmpegVideoConvertor',
        #     'preferedformat': 'mp4',
        # }],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info(f"Job {job_id}: Extracting video info for: '{target_input[:100]}...' using format: '{chosen_format_string}'")
            info = ydl.extract_info(target_input, download=False)

            if not info:
                raise ValueError("yt-dlp extract_info returned no data.")

            if 'entries' in info and info.get('entries'):
                logger.debug(f"Job {job_id}: Search result structure detected ('entries'), using first entry for download.")
                info = info['entries'][0]
            elif info.get('_type') == 'playlist' and info.get('entries'):
                 logger.debug(f"Job {job_id}: Playlist structure detected for URL, using first entry.")
                 info = info['entries'][0]

            video_id = info.get('id')
            if not video_id:
                raise ValueError("Could not extract video ID from metadata.")

            title = info.get('title', 'Unknown Title')
            uploader = info.get('uploader', 'Unknown Uploader')
            uploader_id = info.get('uploader_id', uploader)
            logger.info(f"Job {job_id}: Found video: ID={video_id}, Title='{title[:60]}...', Uploader='{uploader[:40]}...', UploaderID='{uploader_id}'")

            existing_path = find_existing_file(download_dir, video_id, COMMON_VIDEO_FORMATS + COMMON_AUDIO_FORMATS)
            if existing_path:
                logger.info(f"Job {job_id}: [CACHE] Using existing download for {video_id}: {existing_path}")
                return video_id, existing_path, title, uploader_id

            logger.info(f"Job {job_id}: Downloading video {video_id} ('{title[:60]}...'). Target URL/ID for download: '{info.get('webpage_url', target_input)}'")
            # For the actual download, yt-dlp will use the formats determined by extract_info based on the 'format' preference.
            # We don't need to re-initialize ydl_opts here unless we want different options for the download phase.
            ydl.download([info.get('webpage_url') or target_input]) # Pass the URL or original target_input

            downloaded_path = find_existing_file(download_dir, video_id, COMMON_VIDEO_FORMATS + COMMON_AUDIO_FORMATS)
            if not downloaded_path:
                files_in_downloads = [f.name for f in download_dir.iterdir() if f.is_file()]
                logger.error(f"Job {job_id}: Downloaded file for {video_id} not found in {download_dir} after download call. Files present: {files_in_downloads}")
                raise FileNotFoundError(f"Downloaded file for {video_id} not found post-download.")

            logger.info(f"Job {job_id}: Successfully downloaded video to: {downloaded_path} (format: {info.get('format', 'N/A')}, ext: {info.get('ext', 'N/A')})")
            return video_id, downloaded_path, title, uploader_id

    except yt_dlp.utils.DownloadError as e:
        error_message = str(e).lower()
        # Log the format string that was used, for easier debugging
        logger.error(
            f"Job {job_id}: yt-dlp download error for '{target_input[:100]}...' "
            f"(using format: '{chosen_format_string}'): {str(e)}",
            exc_info=False # exc_info=True can be very verbose for yt-dlp errors
        )
        if "requested format is not available" in error_message:
            logger.error(f"Job {job_id}: Specific 'format not available' error for video {target_input[:100]}. "
                         f"The general format string '{chosen_format_string}' also failed. "
                         f"The video might have unusual restrictions or no processable formats available via yt-dlp.")
            raise ValueError(f"Format not available: {e}") from e
        elif "unsupported url" in error_message: raise ValueError("Unsupported URL provided.")
        elif "video unavailable" in error_message: raise ValueError("Video is unavailable.")
        elif "private video" in error_message: raise ValueError("Video is private.")
        elif "live event will begin" in error_message: raise ValueError("Video is a future live event.")
        elif "login required" in error_message: raise ValueError("Video requires login.")
        elif "urlopen error" in error_message or "timed out" in error_message: raise ConnectionError("Network error during download.")
        elif "no search results" in error_message: raise ValueError(f"No search results found for '{url_or_search}'.")
        elif "unable to download webpage" in error_message: raise ConnectionError("Network error: Unable to download webpage.")
        elif "copyright" in error_message: raise ValueError("Video unavailable due to copyright claim.")
        else: raise ValueError(f"Download error: {e}")
    except Exception as e:
        logger.error(f"Job {job_id}: Unexpected error during download for '{target_input[:100]}...': {e}", exc_info=True)
        raise RuntimeError(f"An unexpected download error occurred: {e}")


async def get_youtube_metadata(url: str) -> Optional[Dict]:
    """Fetches metadata (title, thumb, uploader) for a single YouTube URL."""
    logger_sugg.info(f"Fetching metadata for URL: '{url[:100]}'")
    if not YOUTUBE_URL_REGEX.match(url):
        logger_sugg.warning(f"Input '{url[:100]}' is not a valid YouTube URL for metadata fetch.")
        return None

    ydl_opts: Dict[str, Any] = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'socket_timeout': 15,
        'retries': 2,
        'dump_single_json': True,
        'extract_flat': False,
        'skip_download': True,
        'ignoreerrors': True,
    }

    def run_ydl_metadata():
        thread_logger = logging.getLogger(__name__ + ".ydl_metadata_thread")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                thread_logger.debug(f"Running extract_info for metadata: {url[:100]}")
                info = ydl.extract_info(url, download=False)
                return info
            except Exception as inner_e:
                thread_logger.error(f"Error getting metadata for URL '{url[:100]}': {inner_e}", exc_info=False)
                return None

    info = await asyncio.to_thread(run_ydl_metadata)

    if info:
        if info.get('_type') == 'playlist' and info.get('entries'):
             logger_sugg.debug("Playlist structure detected for URL metadata, using first entry.")
             info = info['entries'][0]
        if not info.get('id') and not info.get('url'):
             logger_sugg.warning(f"Metadata received for URL '{url[:100]}' is missing essential ID or URL.")
             return None
        parsed = _parse_ydl_entry(info)
        if parsed:
             logger_sugg.info(f"Metadata fetched successfully for URL: ID={parsed.get('id')}")
             return parsed
        else:
             logger_sugg.warning(f"Failed to parse metadata received for URL: {url[:100]}")
             return None
    else:
        logger_sugg.warning(f"No metadata received from yt-dlp for URL: {url[:100]}")
        return None


async def get_youtube_suggestions(query: str, max_results: int = 4) -> List[Dict]:
    """
    Fetches YouTube video suggestions for a search query OR
    metadata for a single YouTube URL.
    """
    query_stripped = query.strip()

    if YOUTUBE_URL_REGEX.match(query_stripped):
        logger_sugg.info("Input looks like a URL. Fetching single metadata instead of suggestions.")
        metadata = await get_youtube_metadata(query_stripped)
        return [metadata] if metadata else []

    if len(query_stripped) < 2:
        logger_sugg.debug("Query too short for search, skipping suggestions fetch.")
        return []

    logger_sugg.info(f"Fetching suggestions for search query: '{query_stripped[:100]}' (max: {max_results})")
    results = []
    try:
        target_query = f'ytsearch{max_results}:{query_stripped}'
        ydl_opts: Dict[str, Any] = {
            'quiet': True, 'no_warnings': True, 'noplaylist': True,
            'socket_timeout': 10, 'retries': 1, 'dump_single_json': True,
            'extract_flat': True, 'force_generic_extractor': True,
            'ignoreerrors': True, 'geo_bypass': False,
        }

        def run_ydl_search():
            thread_logger = logging.getLogger(__name__ + ".ydl_sugg_thread")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    thread_logger.debug(f"Running extract_info for suggestions: {target_query[:100]}")
                    info = ydl.extract_info(target_query, download=False)
                    return info
                except yt_dlp.utils.DownloadError as dl_err:
                    err_str = str(dl_err).lower()
                    if "no search results" in err_str: thread_logger.warning(f"No search results found for: {target_query[:100]}")
                    elif "urlopen error" in err_str or "timed out" in err_str: thread_logger.warning(f"Network error getting suggestions for '{target_query[:100]}': {dl_err}")
                    else: thread_logger.error(f"yt-dlp DownloadError getting suggestions for '{target_query[:100]}': {dl_err}")
                    return None
                except Exception as inner_e:
                    thread_logger.error(f"Unexpected error inside yt-dlp for suggestions '{target_query[:100]}': {inner_e}", exc_info=False)
                    return None

        info = await asyncio.to_thread(run_ydl_search)

        if info and 'entries' in info:
            for entry in info['entries']:
                parsed = _parse_ydl_entry(entry)
                if parsed: results.append(parsed)
        elif info and info.get('id') and info.get('_type') in ['video', 'url']:
            parsed = _parse_ydl_entry(info)
            if parsed: results.append(parsed)

    except Exception as e:
        logger_sugg.error(f"Unexpected error getting suggestions for search '{query_stripped[:100]}': {e}", exc_info=True)
        return []

    unique_results = []
    seen_ids = set()
    for res in results:
        if res and isinstance(res, dict) and res.get("id") and res["id"] not in seen_ids:
            unique_results.append(res)
            seen_ids.add(res["id"])

    logger_sugg.info(f"Returning {len(unique_results)} unique suggestions for search '{query_stripped[:100]}...'")
    return unique_results


def _parse_ydl_entry(entry: Dict) -> Optional[Dict]:
    """Helper to parse a yt-dlp info dictionary into our suggestion format."""
    if not isinstance(entry, dict): return None

    entry_type = entry.get('_type', 'video')
    if entry_type not in ['video', 'url'] or entry.get('ie_key') in ['YoutubePlaylist', 'YoutubeChannel']:
        return None

    video_id = entry.get("id")
    url = entry.get("webpage_url") or entry.get("url")

    if not video_id and url:
         match = YOUTUBE_URL_REGEX.match(url)
         if match: video_id = match.group(1)

    if not video_id:
        return None

    if not url or not YOUTUBE_URL_REGEX.match(url):
         url = f"https://www.youtube.com/watch?v={video_id}"

    title = entry.get("title", "Unknown Title").strip()
    uploader = (entry.get("uploader") or entry.get("channel") or "Unknown Uploader")
    uploader = uploader.strip() if isinstance(uploader, str) else "Unknown Uploader"
    uploader_id = entry.get("uploader_id") or entry.get("channel_id")

    thumbnail_url = entry.get("thumbnail")
    thumbnails_list = entry.get("thumbnails")
    if isinstance(thumbnails_list, list) and thumbnails_list:
        hq_thumb = next((t.get('url') for t in reversed(thumbnails_list) if t.get('url') and t.get('width', 0) >= 480), None)
        mq_thumb = next((t.get('url') for t in reversed(thumbnails_list) if t.get('url') and t.get('width', 0) >= 300), None)
        lq_thumb = next((t.get('url') for t in reversed(thumbnails_list) if t.get('url') and t.get('width', 0) >= 120), None)
        best_thumb_from_list = thumbnails_list[-1].get('url') if thumbnails_list else None
        thumbnail_url = hq_thumb or mq_thumb or lq_thumb or best_thumb_from_list or thumbnail_url

    if not title or "[deleted video]" in title.lower() or \
       "[private video]" in title.lower() or \
       "[unavailable video]" in title.lower():
        return None

    return {
        "id": video_id, "title": title, "thumbnail": thumbnail_url,
        "url": url, "uploader": uploader, "uploader_id": uploader_id
    }