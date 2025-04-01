/*
 main.js - Frontend Logic for Karaoke App
 - Fetches suggestions from backend API (with loading indicator).
 - Handles video processing requests via WebSocket.
 - Displays progress, steps with activity indicator, results, and stems.
 - Updates title/favicon with progress.
 - Includes theme toggler and basic stem synchronization controls.
*/

// --- DOM Elements ---
const processBtn = document.getElementById("process-btn");
const youtubeInput = document.getElementById("youtube-url");
const statusMessage = document.getElementById("status-message");
const progressDisplay = document.getElementById("progress-display");
const progressBarContainer = document.getElementById("progress-bar-container");
const progressBar = document.getElementById("progress-bar");
const progressTextContainer = document.getElementById("progress-text-container");
const progressText = document.getElementById("progress-text");
const progressTiming = document.getElementById("progress-timing");
const progressStepsContainer = document.getElementById("progress-steps-container");
const languageSelect = document.getElementById("language-select");
const subtitlePositionSelect = document.getElementById("subtitle-position-select");
const generateSubtitlesCheckbox = document.getElementById("generate-subtitles-checkbox");
const karaokeVideo = document.getElementById("karaoke-video");
const resultsArea = document.querySelector(".results-area");
const videoContainer = document.querySelector(".video-container");
const stemsSection = document.getElementById("stems-section");
const globalStemControlsDiv = document.getElementById("global-stem-controls");
const stemsContainer = document.getElementById("stems-container");
const downloadBtn = document.getElementById("download-btn");
const shareBtn = document.getElementById("share-btn");
const themeSwitcher = document.getElementById("theme-switcher");
const videoPreview = document.getElementById("video-preview");
const chosenVideoTitleDiv = document.getElementById("chosen-video-title");
const suggestionSpinner = document.getElementById("suggestion-spinner"); // Get spinner element
const faviconElement = document.getElementById("favicon"); // Get favicon link element

// --- State Variables ---
let currentJobId = null;
let currentWebSocket = null;
let jobStartTime = null;
let lastStepElement = null; // Keep track of the last step's DOM element
let suggestionAbortController = null;
let stemWaveSurfers = [];
let currentProgressPercent = 0;
let suggestionDropdownElement = null; // Define globally
const baseTitle = "Karaoke Generator"; // Store base title
let suggestionTimeout = null; // Timeout for debouncing
let spinnerTimeout = null; // Timeout for showing spinner

// --- Favicon Emojis for Progress ---
const faviconFrames = ['🎤', '🎧', '🎶', '🎵', '🎼', '⭐', '🌟']; // Example sequence
const defaultFavicon = "data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🎤</text></svg>";

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
    document.title = baseTitle; // Set base title on load
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'light') {
        document.body.classList.add('light-mode');
    } else {
        document.body.classList.remove('light-mode');
    }
    updateThemeIcon();
    toggleSubOptions();
    createSuggestionDropdown(); // Create dropdown element on load
    setupEventListeners();
});

// --- Event Listeners Setup ---
function setupEventListeners() {
    processBtn.addEventListener("click", startProcessing);

    window.addEventListener("beforeunload", () => {
        if (currentJobId) {
            // Use sendBeacon for reliable background cancellation attempt
            try {
                const cancelUrl = `/api/cancel_job`; // Use POST endpoint
                // Create a simple body for sendBeacon POST if needed, though query param might work
                // For simplicity, let's assume the backend /cancel_job can handle GET with query param too
                 const beaconUrl = `/api/cancel_job?job_id=${currentJobId}`; // Try GET first
                 if (navigator.sendBeacon(beaconUrl)) {
                    console.log(`Sent cancel request for job ${currentJobId} via Beacon (GET)`);
                 } else {
                     // Fallback or alternative if needed, maybe POST is strictly required
                     console.warn("Beacon GET failed, might need POST.");
                 }

            } catch (e) { console.error("Error sending beacon:", e); }
        }
    });


    generateSubtitlesCheckbox.addEventListener("change", toggleSubOptions);

    youtubeInput.addEventListener("input", () => {
        const query = youtubeInput.value.trim();
        if (!suggestionDropdownElement) createSuggestionDropdown();

        chosenVideoTitleDiv.textContent = "";
        videoPreview.style.display = "none";
        videoPreview.src = "";

        // Clear previous timeouts
        if (suggestionTimeout) clearTimeout(suggestionTimeout);
        if (spinnerTimeout) clearTimeout(spinnerTimeout);
        if (suggestionAbortController) suggestionAbortController.abort();
        if (suggestionSpinner) suggestionSpinner.style.display = 'none'; // Hide spinner immediately on new input

        if (query.length < 2) {
            hideSuggestionDropdown();
            return;
        }

        // Set timeout to show spinner after delay (e.g., 500ms)
        spinnerTimeout = setTimeout(() => {
             console.log("Spinner timeout reached, showing spinner.");
             if (suggestionSpinner) suggestionSpinner.style.display = 'block';
        }, 500); // Show spinner after 500ms of inactivity

        // Set timeout to fetch suggestions after a slightly longer delay
        suggestionTimeout = setTimeout(() => {
            // If fetch starts, we don't need the spinner timeout anymore
            if (spinnerTimeout) clearTimeout(spinnerTimeout);
            console.log("Suggestion timeout reached, fetching suggestions.");
            // Spinner will be shown inside fetchSuggestions if not already visible
            fetchSuggestions(query);
        }, 700); // Fetch after 700ms of inactivity
    });


    document.addEventListener("click", (evt) => {
        if (suggestionDropdownElement && !youtubeInput.contains(evt.target) && !suggestionDropdownElement.contains(evt.target)) {
            hideSuggestionDropdown();
        }
    });

    youtubeInput.addEventListener("blur", () => {
        // Delay hiding to allow clicking on suggestion items
        setTimeout(() => {
             // Check if the focus has moved to an element within the dropdown
             if (!document.activeElement || !suggestionDropdownElement || !suggestionDropdownElement.contains(document.activeElement)) {
                hideSuggestionDropdown();
            }
        }, 200);
    });


    themeSwitcher.addEventListener("click", toggleTheme);
    window.addEventListener("resize", () => {
        if (suggestionDropdownElement && suggestionDropdownElement.style.display === 'block') {
            positionSuggestionDropdown();
        }
    });

    // Global stem controls
    const playAllBtn = document.getElementById('play-all-stems');
    const pauseAllBtn = document.getElementById('pause-all-stems');
    const stopAllBtn = document.getElementById('stop-all-stems');
    const resetAllBtn = document.getElementById('reset-all-stems'); // Get new button

    // Ensure buttons exist before adding listeners
    if (playAllBtn) playAllBtn.onclick = () => stemWaveSurfers.forEach(ws => { try { if(ws && ws.isReady) ws.play(); } catch(e){ console.warn('Error playing stem:', e)} });
    if (pauseAllBtn) pauseAllBtn.onclick = () => stemWaveSurfers.forEach(ws => { try { if(ws) ws.pause(); } catch(e){ console.warn('Error pausing stem:', e)} });
    if (stopAllBtn) stopAllBtn.onclick = () => stemWaveSurfers.forEach(ws => { try { if(ws) ws.stop(); } catch(e){ console.warn('Error stopping stem:', e)} });
    if (resetAllBtn) resetAllBtn.onclick = () => stemWaveSurfers.forEach(ws => { try { if(ws) ws.seekTo(0); } catch(e){ console.warn('Error seeking stem:', e)} });

}

// --- UI Functions ---

function toggleSubOptions() {
    const isEnabled = generateSubtitlesCheckbox.checked;
    const langOptionItem = languageSelect.closest('.option-item');
    const posOptionItem = subtitlePositionSelect.closest('.option-item');

    if (langOptionItem) langOptionItem.classList.toggle('hidden', !isEnabled);
    if (posOptionItem) posOptionItem.classList.toggle('hidden', !isEnabled);

    languageSelect.disabled = !isEnabled;
    subtitlePositionSelect.disabled = !isEnabled;

    const optionsGroup = languageSelect.closest('.options-group');
    if (optionsGroup) optionsGroup.classList.toggle('lyrics-disabled', !isEnabled);
}


function updateThemeIcon() {
    const iconSpan = themeSwitcher.querySelector('.icon');
    if (document.body.classList.contains("light-mode")) {
        iconSpan.textContent = "🌙";
        themeSwitcher.title = "Switch to Dark Mode";
    } else {
        iconSpan.textContent = "☀️";
        themeSwitcher.title = "Switch to Light Mode";
    }
}

function toggleTheme() {
    const isLight = document.body.classList.toggle("light-mode");
    updateThemeIcon();
    localStorage.setItem('theme', isLight ? 'light' : 'dark');

    const computedStyle = getComputedStyle(document.body);
    const cursorColor = computedStyle.getPropertyValue('--wavesurfer-cursor').trim() || '#8a2be2';
    stemWaveSurfers.forEach(ws => {
        if (ws) {
            try { ws.setCursorColor(cursorColor); } catch(e) {}
        }
    });
}


function resetUI() {
    // Clear timeouts
    if (suggestionTimeout) clearTimeout(suggestionTimeout);
    if (spinnerTimeout) clearTimeout(spinnerTimeout);

    statusMessage.textContent = "";
    statusMessage.className = "";
    progressDisplay.style.display = "none";
    progressBar.style.width = "0%";
    progressText.textContent = "";
    progressTiming.textContent = ""; // Clear timing info
    progressStepsContainer.innerHTML = "";
    lastStepElement = null;
    resultsArea.style.display = "none";
    videoContainer.style.display = "block";
    karaokeVideo.src = "";
    stemsSection.style.display = "none";
    globalStemControlsDiv.style.display = "none";
    stemsContainer.innerHTML = "";
    downloadBtn.style.display = 'none';
    downloadBtn.href = '#';
    shareBtn.style.display = 'none';
    shareBtn.onclick = null;
    processBtn.disabled = false;
    chosenVideoTitleDiv.textContent = "";
    videoPreview.style.display = "none";
    videoPreview.src = "";
    if (suggestionSpinner) suggestionSpinner.style.display = 'none';

    stemWaveSurfers.forEach(ws => { try { if (ws) ws.destroy(); } catch(e){} });
    stemWaveSurfers = [];
    currentProgressPercent = 0;
    if (currentWebSocket && currentWebSocket.readyState === WebSocket.OPEN) {
        console.log("[Reset] Closing active WebSocket connection.");
        currentWebSocket.close(1000, "Client reset");
    }
    currentJobId = null;
    currentWebSocket = null;
    hideSuggestionDropdown();
    resetTitleAndFavicon(); // Reset title/favicon
}

function showProcessingUI() {
     // Clear suggestion-related timeouts
     if (suggestionTimeout) clearTimeout(suggestionTimeout);
     if (spinnerTimeout) clearTimeout(spinnerTimeout);

     processBtn.disabled = true;
     statusMessage.textContent = "";
     statusMessage.className = "";
     progressDisplay.style.display = "block";
     progressBarContainer.setAttribute('aria-valuenow', '0');
     progressBar.style.width = "0%";
     progressText.textContent = "0% - Initializing...";
     progressTiming.textContent = "Elapsed: 0s"; // Show only elapsed time initially
     progressStepsContainer.innerHTML = "";
     lastStepElement = null;
     jobStartTime = Date.now();
     currentProgressPercent = 0;
     hideSuggestionDropdown();
     if (suggestionSpinner) suggestionSpinner.style.display = 'none';
     updateTitleAndFavicon(0); // Set initial processing state in title/favicon
}

// --- Title and Favicon Update ---
function updateTitleAndFavicon(progress) {
    if (!faviconElement) return;
    if (progress < 0) progress = 0;
    if (progress > 100) progress = 100;

    const titlePrefix = (progress > 0 && progress < 100) ? `(${progress}%) ` : "";
    const newTitle = titlePrefix + baseTitle;
    if (document.title !== newTitle) {
         document.title = newTitle;
    }

    let newFaviconHref = defaultFavicon;
    if (progress > 0 && progress < 100) {
        const frameIndex = Math.min(faviconFrames.length - 1, Math.floor((progress / 100) * faviconFrames.length));
         const emoji = faviconFrames[frameIndex];
         newFaviconHref = `data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>${emoji}</text></svg>`;
    } else if (progress === 100) {
         // Check status class for final icon
         if (statusMessage.classList.contains('success')) {
            newFaviconHref = `data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>✅</text></svg>`;
         } else if (statusMessage.classList.contains('error') || statusMessage.classList.contains('cancelled')) {
             newFaviconHref = `data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>⚠️</text></svg>`;
         }
        // Revert after a delay only if a final status icon was set
        if (newFaviconHref !== defaultFavicon) {
             setTimeout(resetTitleAndFavicon, 4000);
        }
    }
     if (faviconElement.href !== newFaviconHref) {
         faviconElement.href = newFaviconHref;
     }
}

function resetTitleAndFavicon() {
    if (document.title !== baseTitle) {
         document.title = baseTitle;
    }
    if (faviconElement && faviconElement.href !== defaultFavicon) {
        faviconElement.href = defaultFavicon;
    }
}


// --- Suggestions Logic ---

function createSuggestionDropdown() {
    if (document.getElementById("suggestion-dropdown")) {
        suggestionDropdownElement = document.getElementById("suggestion-dropdown");
        return;
    };
    console.log("Creating suggestion dropdown element.");
    suggestionDropdownElement = document.createElement("div");
    suggestionDropdownElement.id = "suggestion-dropdown";
    suggestionDropdownElement.setAttribute('role', 'listbox');
    document.body.appendChild(suggestionDropdownElement);
}

function positionSuggestionDropdown() {
    if (!suggestionDropdownElement || !youtubeInput) {
        console.warn("Cannot position suggestion dropdown, element missing.");
        return;
    }
    const inputRect = youtubeInput.getBoundingClientRect();
    const top = window.scrollY + inputRect.bottom + 2;
    const left = window.scrollX + inputRect.left;
    const width = inputRect.width;
    suggestionDropdownElement.style.position = 'absolute';
    suggestionDropdownElement.style.top = `${top}px`;
    suggestionDropdownElement.style.left = `${left}px`;
    suggestionDropdownElement.style.width = `${width}px`;
    suggestionDropdownElement.style.zIndex = '1001';
}

function hideSuggestionDropdown() {
    if (suggestionDropdownElement) {
        suggestionDropdownElement.style.display = "none";
    }
    // Also hide spinner if dropdown is hidden
    if (suggestionSpinner) suggestionSpinner.style.display = 'none';
    if (spinnerTimeout) clearTimeout(spinnerTimeout); // Clear spinner timeout too
}

function showSuggestionDropdown() {
     if (!suggestionDropdownElement) return;
     if (suggestionDropdownElement.hasChildNodes()) {
         positionSuggestionDropdown();
         suggestionDropdownElement.style.display = "block";
     } else {
          hideSuggestionDropdown(); // Hide if empty
     }
}

async function fetchSuggestions(query) {
    if (suggestionAbortController) {
        suggestionAbortController.abort();
    }
    suggestionAbortController = new AbortController();
    const signal = suggestionAbortController.signal;

    console.log(`[FETCH] Starting suggestions fetch for: ${query}`);
    // Show spinner now that the actual fetch is initiated
    if (suggestionSpinner) suggestionSpinner.style.display = 'block';

    try {
        const response = await fetch(`/api/suggestions?q=${encodeURIComponent(query)}`, { signal });

        if (signal.aborted) return;
        if (!response.ok) throw new Error(`HTTP error ${response.status}`);

        const suggestions = await response.json();
        if (signal.aborted) return;

        console.log(`[FETCH] Received ${suggestions?.length ?? 0} suggestions from backend.`);
        if (suggestions && suggestions.length > 0) console.log("[FETCH] First suggestion:", suggestions[0]);

        renderSuggestionDropdown(suggestions);

    } catch (error) {
        if (error.name === 'AbortError') {
             console.log("[FETCH] Suggestion fetch explicitly aborted.");
        } else {
            console.error("[FETCH] Failed to fetch suggestions:", error);
            renderSuggestionDropdown([]); // Render empty to hide
        }
    } finally {
         // Ensure spinner hides when fetch is done
         if (suggestionSpinner) suggestionSpinner.style.display = 'none';
        if (!signal.aborted) {
             suggestionAbortController = null;
        }
    }
}

function renderSuggestionDropdown(suggestions) {
    if (!suggestionDropdownElement) return;

    suggestionDropdownElement.innerHTML = "";

    if (!suggestions || !Array.isArray(suggestions) || suggestions.length === 0) {
        showSuggestionDropdown(); // Handles hiding if empty
        return;
    }

    suggestions.forEach(item => {
        if (!item || typeof item !== 'object' || !item.id || !item.title || !item.url) {
            console.warn("[RENDER] Skipping invalid suggestion item:", item);
            return;
        }

        const div = document.createElement("div");
        div.className = "suggestion-item";
        div.setAttribute('role', 'option');
        div.setAttribute('aria-selected', 'false');
        div.tabIndex = -1; // Make it focusable for accessibility if needed later

        const thumbnail = document.createElement("img");
        thumbnail.className = "suggestion-thumbnail";
        thumbnail.src = (item.thumbnail && typeof item.thumbnail === 'string')
            ? item.thumbnail
            : 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="90" height="50" viewBox="0 0 90 50"><rect width="90" height="50" fill="%23555"/><text x="50%" y="50%" fill="%23ccc" font-size="10" text-anchor="middle" dy=".3em">No Thumb</text></svg>';
        thumbnail.alt = `Thumbnail for ${item.title}`;
        thumbnail.loading = 'lazy';
        thumbnail.onerror = (e) => { e.target.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="90" height="50" viewBox="0 0 90 50"><rect width="90" height="50" fill="%23555"/><text x="50%" y="50%" fill="%23ccc" font-size="10" text-anchor="middle" dy=".3em">Error</text></svg>'; }

        const titleDiv = document.createElement("div");
        titleDiv.className = "suggestion-title";
        titleDiv.textContent = item.title;

        div.appendChild(thumbnail);
        div.appendChild(titleDiv);

        div.addEventListener('mousedown', (e) => {
            e.preventDefault();
            console.log("[SELECT] Suggestion selected:", item.title, item.url);
            youtubeInput.value = item.url;
            chosenVideoTitleDiv.textContent = `Selected: ${item.title}`;
            if (thumbnail.src.startsWith('http')) {
                videoPreview.src = thumbnail.src;
                videoPreview.style.display = "block";
            } else {
                 videoPreview.style.display = "none";
                 videoPreview.src = "";
            }
            hideSuggestionDropdown();
            youtubeInput.focus();
        });

        suggestionDropdownElement.appendChild(div);
    });

    showSuggestionDropdown(); // Show after populating
}


// --- Processing Logic ---
async function startProcessing() {
    const urlOrSearch = youtubeInput.value.trim();
    if (!urlOrSearch) {
        statusMessage.textContent = "Please enter a YouTube link or search query.";
        statusMessage.className = 'error';
        youtubeInput.focus();
        return;
    }
    console.log("Starting processing for:", urlOrSearch);
    resetUI();
    showProcessingUI();

    if (currentWebSocket && currentWebSocket.readyState === WebSocket.OPEN) {
        currentWebSocket.close(1001, "Starting new job");
        currentWebSocket = null;
    }

    try {
        const language = languageSelect.value;
        const position = subtitlePositionSelect.value;
        const generateSubs = generateSubtitlesCheckbox.checked;

        const requestBody = { url: urlOrSearch, language, subtitle_position: position, generate_subtitles: generateSubs };
        console.log("Sending request to /api/process with body:", JSON.stringify(requestBody));

        const response = await fetch("/api/process", {
            method: "POST",
            headers: { "Content-Type": "application/json", "Accept": "application/json" },
            body: JSON.stringify(requestBody)
        });

        console.log("Response status:", response.status);
        if (!response.ok) {
            let errorMsg = `Error ${response.status}: ${response.statusText}`;
            try { const errorData = await response.json(); errorMsg = (errorData && errorData.detail) ? errorData.detail : errorMsg; console.error("Backend error detail:", errorData); } catch (e) { console.warn("Could not parse error JSON."); }
            throw new Error(errorMsg);
        }

        const data = await response.json();
        if (!data || !data.job_id) throw new Error("Backend response missing job_id.");

        currentJobId = data.job_id;
        console.log("Processing started successfully. Job ID:", currentJobId);
        connectWebSocket(currentJobId);

    } catch (err) {
        console.error("Failed to start processing:", err);
        statusMessage.textContent = `Request failed: ${err.message}`;
        statusMessage.className = 'error';
        processBtn.disabled = false;
        progressDisplay.style.display = "none";
        resetTitleAndFavicon();
    }
}

// --- WebSocket Handling ---
function connectWebSocket(jobId) {
    if (currentWebSocket && currentWebSocket.readyState !== WebSocket.CLOSED) {
       console.warn("[WS] Attempting to connect while previous socket exists. Closing old one.");
       currentWebSocket.close(1001, "New connection requested");
    }

    const proto = (location.protocol === "https:") ? "wss://" : "ws://";
    const wsUrl = `${proto}${location.host}/api/ws/progress/${jobId}`;
    console.log("[WS] Connecting to:", wsUrl);

    try { currentWebSocket = new WebSocket(wsUrl); }
    catch (e) {
         console.error("[WS] Error creating WebSocket:", e);
         statusMessage.textContent = "Failed to create WebSocket connection."; statusMessage.className = 'error';
         processBtn.disabled = false; progressDisplay.style.display = "none"; resetTitleAndFavicon(); return;
    }

    currentWebSocket.onopen = () => {
        console.log(`[WS] Connection opened for job ${jobId}`);
        jobStartTime = jobStartTime || Date.now();
        updateTitleAndFavicon(currentProgressPercent > 0 ? currentProgressPercent : 1); // Show busy state
    };

    currentWebSocket.onmessage = (event) => {
        try { const data = JSON.parse(event.data); updateProgress(data); }
        catch (e) { console.error("[WS] Error parsing message:", e, event.data); }
    };

    currentWebSocket.onerror = (error) => {
        console.error("[WS] WebSocket error:", error);
        const errorText = (error && typeof error === 'object' && error.message) ? error.message : 'Unknown WebSocket error';
        statusMessage.textContent = `WebSocket connection error: ${errorText}`; statusMessage.className = 'error';
        processBtn.disabled = false; if (lastStepElement) lastStepElement.classList.remove('active-step'); resetTitleAndFavicon();
        if (currentWebSocket && currentWebSocket.readyState !== WebSocket.CLOSED) { currentWebSocket.close(1011, "WebSocket error encountered"); }
        currentWebSocket = null;
    };

    currentWebSocket.onclose = (event) => {
        console.log(`[WS] Connection closed for job ${jobId}. Code: ${event.code}, Reason: '${event.reason}', Clean: ${event.wasClean}`);
        if (jobId === currentJobId) {
            const isErrorOrCancel = statusMessage.classList.contains('error') || statusMessage.classList.contains('cancelled');
            const isCompleteSuccess = currentProgressPercent >= 100 && !isErrorOrCancel;

            if (!isCompleteSuccess) resetTitleAndFavicon(); // Reset if not success

            if (isCompleteSuccess) {
                 console.log("[WS] Connection closed normally after job completion.");
                 if (!progressTiming.textContent.startsWith("Finished")) {
                    const elapsedSeconds = Math.round((Date.now() - jobStartTime) / 1000);
                    progressTiming.textContent = `Finished in ${elapsedSeconds}s`;
                 }
                 processBtn.disabled = false;
            } else if (!isErrorOrCancel && event.code !== 1000 && event.code !== 1001) {
                 console.warn("[WS] WebSocket closed unexpectedly before job finished.");
                 if (!statusMessage.textContent) { statusMessage.textContent = "Connection lost during processing."; statusMessage.className = 'error'; }
                 processBtn.disabled = false;
            } else {
                 console.log("[WS] Connection closed after job ended with status:", statusMessage.textContent);
                 processBtn.disabled = false;
            }
             if (lastStepElement) { lastStepElement.classList.remove('active-step'); lastStepElement.classList.add('completed-step'); }
             currentJobId = null;
        } else {
             console.log(`[WS] Closed connection for a previous/mismatched job (${jobId}), current job is ${currentJobId}`);
        }
        currentWebSocket = null;
    };
}

// Modified updateProgress to remove remaining time
function updateProgress(data) {
    if (!data || typeof data !== 'object') return;

    const newProgress = Math.min(Math.max(0, parseInt(data.progress || 0, 10)), 100);
    const message = (typeof data.message === 'string') ? data.message : "";
    const result = (data.result && typeof data.result === 'object') ? data.result : null;
    const isStepStart = data.is_step_start === true;
    const isError = message.toLowerCase().includes("error");
    const isCancel = message.toLowerCase().includes("cancel");

    if (newProgress > currentProgressPercent || isStepStart || result || isError || isCancel || message !== progressText.textContent.split(' - ')[1]) {
         currentProgressPercent = newProgress;

        progressBar.style.width = `${currentProgressPercent}%`;
        progressBarContainer.setAttribute('aria-valuenow', currentProgressPercent);
        progressText.textContent = `${currentProgressPercent}% - ${message}`;
        updateTitleAndFavicon(currentProgressPercent);

        if (isStepStart && message) {
            if (lastStepElement) {
                lastStepElement.classList.remove('active-step');
                lastStepElement.classList.add('completed-step');
            }
            const stepDiv = document.createElement("div");
            stepDiv.className = "progress-step active-step";
            const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            const safeMessage = message.replace(/</g, "&lt;").replace(/>/g, "&gt;");
            stepDiv.innerHTML = `<span class="step-time">[${time}]</span> <span class="step-message">${safeMessage}</span>`;
            progressStepsContainer.appendChild(stepDiv);
            progressStepsContainer.scrollTop = progressStepsContainer.scrollHeight;
            lastStepElement = stepDiv;
        }

        // Update timing info - ONLY Elapsed time
        const elapsedSeconds = Math.round((Date.now() - jobStartTime) / 1000);
        const elapsedFormatted = `${elapsedSeconds}s`;

        if (currentProgressPercent < 100) {
             progressTiming.textContent = `Elapsed: ${elapsedFormatted}`;
        } else {
            // Final timing update
            progressTiming.textContent = `Finished in ${elapsedFormatted}`;
        }


        if (currentProgressPercent >= 100) {
             if (lastStepElement) {
                 lastStepElement.classList.remove('active-step');
                 lastStepElement.classList.add('completed-step');
             }

            if (result) {
                console.log("[WS] Result received via WebSocket, processing completion.");
                onProcessingComplete(result);
            } else if (isError) {
                console.error("[WS] Error message received via WebSocket:", message);
                statusMessage.textContent = `${message}`;
                statusMessage.className = 'error';
                // Title/favicon reset happens in onclose or next update
            } else if (isCancel) {
                console.warn("[WS] Cancellation message received via WebSocket:", message);
                statusMessage.textContent = `${message}`;
                statusMessage.className = 'cancelled';
                 // Title/favicon reset happens in onclose or next update
            } else {
                console.log("[WS] Reached 100%, waiting for final status or result...");
                if (!statusMessage.textContent) {
                    statusMessage.textContent = "Processing finished. Waiting for results...";
                    statusMessage.className = '';
                }
            }
        }
    }
}

// onProcessingComplete - remains the same
function onProcessingComplete(result) {
    console.log("[COMPLETE] Processing complete. Result:", result);
    processBtn.disabled = false;
    resultsArea.style.display = "block";
    statusMessage.textContent = `Success! Karaoke ready for: ${result.title || 'your video'}`;
    statusMessage.className = 'success';
    updateTitleAndFavicon(100); // Show success state in title/favicon

    if (result.processed_path) {
        videoContainer.style.display = "block";
        const videoUrl = result.processed_path.startsWith('/')
                       ? result.processed_path
                       : `/${result.processed_path}`;
        const fullVideoUrl = new URL(videoUrl, window.location.origin).href;
        console.log("[COMPLETE] Setting video source:", fullVideoUrl);
        karaokeVideo.src = fullVideoUrl;
        karaokeVideo.load();

        downloadBtn.href = fullVideoUrl;
        downloadBtn.download = `${result.video_id || 'karaoke'}_video.mp4`;
        downloadBtn.style.display = 'inline-flex';

        shareBtn.onclick = () => {
             if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(fullVideoUrl)
                    .then(() => {
                        shareBtn.disabled = true;
                        shareBtn.innerHTML = `<span class="button-icon" aria-hidden="true">✅</span> Copied!`;
                        setTimeout(() => {
                            shareBtn.innerHTML = `<span class="button-icon" aria-hidden="true">🔗</span> Copy Link`;
                            shareBtn.disabled = false;
                        }, 1500);
                    })
                    .catch(err => {
                        console.error("Failed to copy video link:", err);
                        alert(`Could not copy automatically. Link:\n${fullVideoUrl}`);
                    });
            } else {
                alert(`Clipboard not available. Link:\n${fullVideoUrl}`);
            }
        };
        shareBtn.style.display = 'inline-flex';

    } else {
        console.error("[COMPLETE] Result received but 'processed_path' is missing!");
        videoContainer.style.display = "none";
        statusMessage.textContent = `Error: Processed video path missing in result.`;
        statusMessage.className = 'error';
        resetTitleAndFavicon(); // Reset on error
    }

    if (result.stems_base_path && result.video_id) {
        console.log("[COMPLETE] Stems path found, creating stem players:", result.stems_base_path);
        stemsSection.style.display = "block";
        globalStemControlsDiv.style.display = 'flex';
        if (typeof WaveSurfer !== 'undefined') {
            createStemPlayers(result.stems_base_path, result.video_id);
        } else {
             console.error("WaveSurfer library not loaded. Cannot create stem players.");
             stemsContainer.innerHTML = '<p style="color: var(--error-color);">Error: WaveSurfer library failed to load.</p>';
        }
    } else {
         console.log("[COMPLETE] No stems path in result, hiding stems section.");
         stemsSection.style.display = 'none';
         globalStemControlsDiv.style.display = 'none';
         stemsContainer.innerHTML = '';
         stemWaveSurfers = [];
    }

    resultsArea.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// --- Stem Player Logic ---
// createStemPlayers - remains the same
function createStemPlayers(basePath, videoId) {
    if (typeof WaveSurfer === 'undefined') {
        console.error("WaveSurfer is not defined. Cannot create players.");
        stemsContainer.innerHTML = '<p class="error">Error: Audio player library (WaveSurfer) not loaded.</p>';
        return;
    }

    stemsContainer.innerHTML = "";
    stemWaveSurfers.forEach(ws => { try { if (ws) ws.destroy(); } catch(e){ console.warn("Error destroying old wavesurfer:", e)} });
    stemWaveSurfers = [];

    const stems = [
        { name: "Instrumental", file: "instrumental.wav", color: 'rgb(100, 180, 100)', progressColor: 'rgb(60, 120, 60)' },
        { name: "Vocals", file: "vocals.wav", color: 'rgb(200, 100, 100)', progressColor: 'rgb(140, 60, 60)' },
        { name: "Drums", file: "drums.wav", color: 'rgb(130, 130, 200)', progressColor: 'rgb(80, 80, 140)' },
        { name: "Bass", file: "bass.wav", color: 'rgb(180, 100, 180)', progressColor: 'rgb(120, 60, 120)' },
        { name: "Other", file: "other.wav", color: 'rgb(170, 170, 170)', progressColor: 'rgb(100, 100, 100)' }
    ];

    const computedStyle = getComputedStyle(document.body);
    const cursorColor = computedStyle.getPropertyValue('--wavesurfer-cursor').trim() || '#8a2be2';

    let loadedCount = 0;
    const totalStems = stems.length;
    console.log(`[STEMS] Creating ${totalStems} stem players... Base path: ${basePath}`);

    stems.forEach((stem, index) => {
        const safeBasePath = basePath.startsWith('/') ? basePath : `/${basePath}`;
        const stemUrl = new URL(safeBasePath + `/${stem.file}`, window.location.origin).href;
        console.log(`[STEMS] Creating player for: ${stem.name} at ${stemUrl}`);

        const stemWrapper = document.createElement("div");
        stemWrapper.className = "stem-player";

        const label = document.createElement("div");
        label.className = "stem-label";
        label.textContent = `${stem.name} (Loading...)`;

        const waveformDiv = document.createElement("div");
        waveformDiv.id = `waveform-${index}`;
        waveformDiv.className = "waveform-container";

        const controlsDiv = document.createElement("div");
        controlsDiv.className = "stem-controls";

        const playPauseBtn = document.createElement("button");
        playPauseBtn.innerHTML = `<span class="button-icon" aria-hidden="true">▶️</span>`;
        playPauseBtn.className = "stem-control-btn play-pause-btn";
        playPauseBtn.title = "Play/Pause";
        playPauseBtn.disabled = true;
        playPauseBtn.setAttribute('aria-label', `Play or pause ${stem.name} stem`);

        const stopBtn = document.createElement("button");
        stopBtn.innerHTML = `<span class="button-icon" aria-hidden="true">⏹️</span>`;
        stopBtn.className = "stem-control-btn stop-btn";
        stopBtn.title = "Stop";
        stopBtn.disabled = true;
        stopBtn.setAttribute('aria-label', `Stop ${stem.name} stem`);

        const volumeSlider = document.createElement("input");
        volumeSlider.type = "range";
        volumeSlider.min = "0";
        volumeSlider.max = "1";
        volumeSlider.step = "0.01";
        volumeSlider.value = "0.8";
        volumeSlider.title = `Volume for ${stem.name}`;
        volumeSlider.className = "stem-volume-slider";
        volumeSlider.setAttribute('aria-label', `Volume for ${stem.name} stem`);

        controlsDiv.appendChild(playPauseBtn);
        controlsDiv.appendChild(stopBtn);
        controlsDiv.appendChild(volumeSlider);
        stemWrapper.appendChild(label);
        stemWrapper.appendChild(waveformDiv);
        stemWrapper.appendChild(controlsDiv);
        stemsContainer.appendChild(stemWrapper);

        let wavesurfer = null;
        try {
            wavesurfer = WaveSurfer.create({
                container: waveformDiv,
                waveColor: stem.color, progressColor: stem.progressColor, cursorColor: cursorColor,
                barWidth: 3, barRadius: 3, cursorWidth: 2, height: 70, barGap: 2,
                responsive: true, normalize: true,
                url: stemUrl,
            });

            stemWaveSurfers[index] = wavesurfer;

            playPauseBtn.onclick = () => { if (wavesurfer) wavesurfer.playPause(); };
            stopBtn.onclick = () => { if (wavesurfer) wavesurfer.stop(); };
            volumeSlider.oninput = (e) => { if (wavesurfer) wavesurfer.setVolume(Number(e.target.value)); };

            wavesurfer.on('ready', () => {
                console.log(`[STEMS] ${stem.name} waveform ready.`);
                label.textContent = stem.name; playPauseBtn.disabled = false; stopBtn.disabled = false;
                wavesurfer.setVolume(Number(volumeSlider.value)); loadedCount++;
                if (loadedCount === totalStems) console.log("[STEMS] All stems loaded.");
            });
            wavesurfer.on('play', () => playPauseBtn.innerHTML = `<span class="button-icon" aria-hidden="true">⏸️</span>`);
            wavesurfer.on('pause', () => playPauseBtn.innerHTML = `<span class="button-icon" aria-hidden="true">▶️</span>`);
            wavesurfer.on('finish', () => playPauseBtn.innerHTML = `<span class="button-icon" aria-hidden="true">▶️</span>`);
            wavesurfer.on('destroy', () => {
                 console.log(`[STEMS] Destroyed instance for ${stem.name}`);
                 const wsIndex = stemWaveSurfers.indexOf(wavesurfer); if (wsIndex > -1) stemWaveSurfers[wsIndex] = null;
            });
            wavesurfer.on('error', (err) => {
                 console.error(`[STEMS] Error loading ${stem.name} (${stemUrl}):`, err);
                 label.textContent = `${stem.name} (Load Error)`; stemWrapper.classList.add('load-error');
                 playPauseBtn.disabled = true; stopBtn.disabled = true; volumeSlider.disabled = true;
            });

        } catch (error) {
             console.error(`[STEMS] Failed to init WaveSurfer for ${stem.name}:`, error);
             label.textContent = `${stem.name} (Init Error)`; stemWrapper.classList.add('load-error');
             stemWaveSurfers[index] = null;
        }
    });
}