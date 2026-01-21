# YouTube Karaoke Generator 🎤

[![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/framework-FastAPI-green.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **⚠️ DISCLAIMER: This software is provided for educational and personal use only.**
>
> This tool is intended for:
> - Educational purposes (learning about audio processing, ML models, web development)
> - Personal use with content you own or have explicit permission to use
> - Research and development purposes
>
> **By using this software, you agree that:**
> - You will only process content that you own, have created, or have explicit permission to use
> - You are solely responsible for ensuring your use complies with all applicable laws and terms of service
> - The developers are not responsible for any misuse of this software
> - This software does not host, store, or distribute any copyrighted content
>
> **This project is not affiliated with, endorsed by, or connected to YouTube, Google, or any content creators.**

Transform YouTube videos or search queries into karaoke-style videos with separated instrumental tracks and synchronized lyrics.

This project uses modern tools to download YouTube videos, separate audio stems (vocals, drums, bass, other), transcribe vocals, fetch lyrics from Genius, align them, and merge everything back into a final karaoke video with subtitles.

## ✨ Features

* **YouTube Input:** Accepts direct YouTube video URLs or search terms.
* **Audio Separation:** Uses Demucs (`htdemucs` by default) to separate audio into instrumental, vocals, drums, bass, and other stems.
* **Transcription:** Uses OpenAI Whisper (`large-v2` by default) to transcribe the vocals.
* **Lyrics Fetching:** Optionally fetches lyrics from Genius using song title and artist/uploader name.
* **Lyrics Alignment:** Aligns the fetched Genius lyrics with the transcribed segments using fuzzy matching.
* **Subtitle Generation:** Creates an SRT subtitle file from the aligned lyrics.
* **Video Merging:** Combines the original video (without audio), the generated instrumental track, and the generated subtitles into a final MP4 karaoke video.
* **Web Interface:** Modern UI built with HTML, CSS, and vanilla JavaScript (ESM modules).
    * YouTube suggestions dropdown.
    * Real-time progress tracking via WebSockets.
    * Displays final karaoke video.
    * Interactive stem players (using WaveSurfer.js) to listen to individual tracks.
    * Theme switcher (Dark/Light).
* **Docker Support:** Includes a `Dockerfile` for easy containerization of the backend.

## 🛠️ Tech Stack

**Backend:**

* **Python 3.10+**
* **FastAPI:** Web framework for the API and WebSockets.
* **Uvicorn:** ASGI server.
* **yt-dlp:** Downloading YouTube videos and fetching metadata/suggestions.
* **Demucs:** Audio source separation.
* **OpenAI Whisper:** Audio transcription.
* **ffmpeg-python:** Audio extraction and video/audio merging.
* **lyricsgenius:** Fetching lyrics from Genius.com.
* **python-dotenv:** Loading environment variables.

**Frontend:**

* **HTML5**
* **CSS3:** Modern styling with CSS variables, Flexbox, Grid.
* **Vanilla JavaScript (ES Modules):** Frontend logic, API interaction, WebSocket handling, UI updates.
* **WaveSurfer.js:** Displaying waveforms and controlling audio stems.

## 🚀 Setup & Installation

1.  **Clone the Repository:**
    ```bash
    git clone https://your-repository-url/yt-karaoke.git
    cd yt-karaoke
    ```

2.  **Backend Setup:**
    * Navigate to the `backend` directory: `cd backend`
    * **Create Virtual Environment:** (Recommended)
        ```bash
        python -m venv .venv
        source .venv/bin/activate # On Windows use `.venv\Scripts\activate`
        ```
    * **Install Python Dependencies:**
        ```bash
        pip install -r requirements.txt
        # Ensure torch is installed correctly for your system (CPU/GPU)
        # See: [https://pytorch.org/get-started/locally/](https://pytorch.org/get-started/locally/)
        # Example CPU-only: pip install torch torchvision torchaudio
        # Example CUDA 11.8: pip install torch torchvision torchaudio --index-url [https://download.pytorch.org/whl/cu118](https://download.pytorch.org/whl/cu118)
        ```
    * **Install Backend System Dependencies:**
        * `ffmpeg`: Essential for audio/video processing. ([Installation Guide](https://ffmpeg.org/download.html))
        * `git`: Required by some dependencies.
        * `sox`: Optional, might be needed by some audio libraries indirectly.
        (These are installed in the Dockerfile; ensure they are available on your host if running locally without Docker).
    * **Environment Variables:**
        * Create a `.env` file in the `backend` directory.
        * Add your Genius API token (required for lyrics fetching):
            ```dotenv
            GENIUS_API_TOKEN="YOUR_GENIUS_API_TOKEN_HERE"
            # Optional: Override default models or ports
            # WHISPER_MODEL_TAG="base"
            # DEMUCS_MODEL="mdx_extra_q"
            # PORT=8001
            ```
        * Get a Genius API token from [http://genius.com/api-clients](http://genius.com/api-clients).

    * **(Optional) YouTube Cookies:**
        If you encounter "Sign in to confirm you're not a bot" errors from YouTube, you can provide cookies:
        ```dotenv
        # Option 1: Extract cookies from your browser automatically
        YTDLP_COOKIES_FROM_BROWSER="chrome"  # or: firefox, safari, edge, opera, brave, chromium

        # Option 2: Use a cookies.txt file (Netscape format)
        YTDLP_COOKIES_FILE="/path/to/your/cookies.txt"
        ```
        **Important:** Never commit cookies files to git - they contain session data!

3.  **Running the Application (Locally):**
    * **Start the Backend:** From the `backend` directory:
        ```bash
        # Ensure your virtual environment is active
        uvicorn app:app --reload --host 0.0.0.0 --port 8000
        ```
        (`--reload` is for development, remove for production).
    * **Access the Frontend:** Open your web browser and go to `http://localhost:8000` (or the port you configured).

## 🐳 Docker Instructions

1.  **Build the Docker Image:**
    * From the **root** directory of the project:
        ```bash
        docker build -t youtube-karaoke-backend -f backend/Dockerfile .
        ```

2.  **Run the Docker Container:**
    * Make sure to pass the `GENIUS_API_TOKEN` environment variable.
    * Map the container port (8000) to a host port (e.g., 8000).
    * Mount volumes for persistent downloads and processed files (optional but recommended).
        ```bash
        docker run -d --name karaoke-app \
          -p 8000:8000 \
          -e GENIUS_API_TOKEN="YOUR_GENIUS_API_TOKEN_HERE" \
          -e PORT=8000 \
          -e HOST="0.0.0.0" \
          # Optional: Mount volumes for persistence
          # -v $(pwd)/backend/downloads:/app/downloads \
          # -v $(pwd)/backend/processed:/app/processed \
          # Optional: Add --gpus all for GPU acceleration if Docker supports it
          youtube-karaoke-backend
        ```
    * Access the application at `http://localhost:8000`.

## 使い方 (Usage)

1.  Open the web interface in your browser.
2.  Enter a YouTube video URL or a search query (e.g., "Song Title Artist").
3.  Suggestions will appear below the input field. Click one or proceed with the entered text.
4.  Select desired options (Add Lyrics, Language, Position). Subtitle options appear after selecting a video.
5.  Click the "Process" button.
6.  Monitor the progress bar and steps log.
7.  Once complete, the karaoke video will appear.
8.  You can play the video, download it, or copy the link.
9.  If audio stems were generated, interactive players for each stem will appear below the video.

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file (you'll need to create this file) for details.

## 💡 Future Enhancements

* [ ] Genius: Handle ambiguous search results (allow user selection).
* [ ] Frontend: More robust stem player synchronization.
* [ ] Frontend: Custom video player skin matching the theme.
* [ ] Backend: Option to choose different Demucs/Whisper models via UI.
* [ ] Backend: Asynchronous file cleanup mechanism.
* [ ] Backend: More sophisticated error handling and reporting.
* [ ] Testing: Add more comprehensive unit and integration tests.

## ⚖️ Legal Notice

### Intended Use
This software is designed as an **educational project** demonstrating:
- Modern Python web development with FastAPI
- Machine learning integration (Whisper, Demucs)
- Real-time WebSocket communication
- Audio/video processing pipelines

### User Responsibility
- Users must ensure they have the legal right to process any content
- This tool should only be used with content you own, have created, or have explicit permission to use
- Users are responsible for compliance with their local laws and all applicable terms of service

### No Warranty
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED. THE AUTHORS ARE NOT LIABLE FOR ANY CLAIM, DAMAGES, OR OTHER LIABILITY ARISING FROM THE USE OF THIS SOFTWARE.

### DMCA
If you believe any content processed using this tool infringes your copyright, please contact the user who processed the content, not the developers of this tool. This software does not host, store, or distribute any content.