// File: frontend/web/assets/js/websocket.js
// Handles WebSocket connection for real-time progress updates with automatic reconnection.

import * as UI from './ui.js';
import { createStemPlayers, destroyStemPlayers } from './stems.js';
import * as DOM from './dom.js';
import { BASE_TITLE, DEFAULT_FAVICON, FAVICON_FRAMES } from './config.js';

// === Connection State ===
let currentWebSocket = null;
let currentJobId = null;
let jobStartTime = null;
let progressUpdateInterval = null;
let faviconFrameIndex = 0;

// === Reconnection State ===
let reconnectAttempts = 0;
let reconnectTimeout = null;
let isManualClose = false;
let lastReceivedProgress = 0;

// === Reconnection Configuration ===
const RECONNECT_CONFIG = {
    maxAttempts: 5,
    baseDelay: 1000,       // 1 second
    maxDelay: 30000,       // 30 seconds
    backoffMultiplier: 2,  // Exponential backoff factor
};

/**
 * Calculates reconnection delay with exponential backoff and jitter.
 * @param {number} attempt - Current reconnection attempt number.
 * @returns {number} - Delay in milliseconds.
 */
function calculateReconnectDelay(attempt) {
    const delay = Math.min(
        RECONNECT_CONFIG.baseDelay * Math.pow(RECONNECT_CONFIG.backoffMultiplier, attempt),
        RECONNECT_CONFIG.maxDelay
    );
    // Add jitter (±20%) to prevent thundering herd
    const jitter = delay * 0.2 * (Math.random() * 2 - 1);
    return Math.round(delay + jitter);
}

/**
 * Connects to the WebSocket endpoint for the given job ID.
 * Handles opening, message receiving, errors, and closing with auto-reconnect.
 * @param {string} jobId - The unique ID of the job to track.
 */
export function connectWebSocket(jobId) {
    // Close any existing connection cleanly before starting a new one
    if (currentWebSocket && currentWebSocket.readyState !== WebSocket.CLOSED) {
        console.warn("[WS] Attempting to connect while previous socket exists. Closing old one.");
        closeWebSocket(1001, "New connection requested");
    }

    clearReconnectTimeout();
    clearProgressAnimation();

    // Reset reconnect state for new job
    isManualClose = false;
    reconnectAttempts = 0;
    lastReceivedProgress = 0;

    // Store job info and start time
    currentJobId = jobId;
    jobStartTime = Date.now();

    performConnect(jobId);
}

/**
 * Performs the actual WebSocket connection.
 * @param {string} jobId - The job ID to connect to.
 */
function performConnect(jobId) {
    const proto = (location.protocol === "https:") ? "wss://" : "ws://";
    const wsUrl = `${proto}${location.host}/api/ws/progress/${jobId}`;

    console.log(`[WS] Connecting to: ${wsUrl}${reconnectAttempts > 0 ? ` (attempt ${reconnectAttempts + 1})` : ''}`);

    try {
        currentWebSocket = new WebSocket(wsUrl);
        currentWebSocket.onopen = onOpen;
        currentWebSocket.onmessage = onMessage;
        currentWebSocket.onerror = onError;
        currentWebSocket.onclose = onClose;
    } catch (e) {
        console.error("[WS] Error creating WebSocket instance:", e);
        handleConnectionError("Failed to create WebSocket connection.");
    }
}

/**
 * Schedules a reconnection attempt with exponential backoff.
 */
function scheduleReconnect() {
    if (isManualClose || !currentJobId) {
        console.log("[WS] Not scheduling reconnect: manual close or no job ID.");
        return;
    }

    if (reconnectAttempts >= RECONNECT_CONFIG.maxAttempts) {
        console.error(`[WS] Max reconnection attempts (${RECONNECT_CONFIG.maxAttempts}) reached. Giving up.`);
        handleConnectionError("Connection lost. Maximum reconnection attempts exceeded.");
        return;
    }

    const delay = calculateReconnectDelay(reconnectAttempts);
    reconnectAttempts++;

    console.log(`[WS] Scheduling reconnect in ${delay}ms (attempt ${reconnectAttempts}/${RECONNECT_CONFIG.maxAttempts})`);

    // Update UI to show reconnection status
    if (DOM.progressText) {
        DOM.progressText.textContent = `Reconnecting... (attempt ${reconnectAttempts}/${RECONNECT_CONFIG.maxAttempts})`;
    }

    reconnectTimeout = setTimeout(() => {
        if (currentJobId && !isManualClose) {
            performConnect(currentJobId);
        }
    }, delay);
}

/**
 * Clears any pending reconnection timeout.
 */
function clearReconnectTimeout() {
    if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
        reconnectTimeout = null;
    }
}

/** WebSocket onOpen event handler. Called when connection is established. */
function onOpen() {
    console.log(`[WS] Connection successfully opened for job ${currentJobId}`);

    // Reset reconnect attempts on successful connection
    reconnectAttempts = 0;
    clearReconnectTimeout();

    startProgressAnimation();

    // Restore progress display if we reconnected
    if (lastReceivedProgress > 0 && DOM.progressText) {
        DOM.progressText.textContent = `${lastReceivedProgress}% - Reconnected, waiting for updates...`;
    }
}

/** WebSocket onMessage event handler. Processes incoming progress data. */
function onMessage(event) {
    try {
        const data = JSON.parse(event.data);

        // Track last received progress for reconnection recovery
        if (data.progress !== undefined) {
            lastReceivedProgress = data.progress;
        }

        UI.updateProgressUI(data, jobStartTime);

        if (data.progress >= 100) {
            console.log("[WS] Progress reached 100%. Checking for results...");
            clearProgressAnimation();

            if (data.result) {
                console.log("[WS] Received final result message:", data.result);
                UI.displayResults(data.result);

                // Populate lyrics sidebar with selected lyrics or transcription
                populateLyricsSidebar(data.result);

                if (data.result.stems_base_path && data.result.video_id) {
                    console.log("[WS] Stems data found in result. Preparing to display stems section.");
                    if (DOM.stemsSection) {
                        console.log("[WS] Making stems section visible (display: block).");
                        DOM.stemsSection.style.display = 'block';
                        requestAnimationFrame(() => {
                            DOM.stemsSection.style.opacity = '1';
                            DOM.stemsSection.style.maxHeight = '3000px';
                            console.log("[WS] Stems section opacity and max-height set for visibility.");

                            console.log("[WS] Calling createStemPlayers...");
                            if (typeof WaveSurfer !== 'undefined') {
                                createStemPlayers(data.result.stems_base_path, data.result.video_id);
                            } else {
                                console.error("[WS] WaveSurfer library not loaded! Cannot create stem players.");
                                if (DOM.stemsContainer) {
                                    DOM.stemsContainer.innerHTML = '';
                                    const errorP = document.createElement('p');
                                    errorP.className = 'error-message';
                                    errorP.textContent = 'Error: WaveSurfer library failed to load.';
                                    DOM.stemsContainer.appendChild(errorP);
                                }
                            }
                        });
                    } else {
                        console.warn("[WS] Stems section element (#stems-section) not found in DOM.");
                    }
                } else {
                    console.log("[WS] No stems_base_path in result. Hiding stems section.");
                    if (DOM.stemsSection) {
                        DOM.stemsSection.style.display = 'none';
                        DOM.stemsSection.style.opacity = '0';
                        DOM.stemsSection.style.maxHeight = '0';
                    }
                    destroyStemPlayers();
                }
            } else {
                const errorMessage = data.message || "Processing finished with incomplete data or an error.";
                console.warn(`[WS] Reached 100% but no 'result' object. Message: "${errorMessage}"`);
                handleProcessingError(errorMessage);
                if (DOM.stemsSection) {
                    DOM.stemsSection.style.display = 'none';
                    DOM.stemsSection.style.opacity = '0';
                    DOM.stemsSection.style.maxHeight = '0';
                }
                destroyStemPlayers();
            }
        } else if (data.error) {
            console.error("[WS] Received explicit error flag from backend:", data.message);
            handleProcessingError(data.message || "An unknown error occurred during processing.");
            clearProgressAnimation();
            closeWebSocket(1011, "Backend reported error");
        }
    } catch (e) {
        console.error("[WS] Error parsing message or updating UI:", e, "\nRaw data:", event.data);
        handleProcessingError("Failed to process WebSocket update. Check console.");
        clearProgressAnimation();
    }
}

/** WebSocket onError event handler. Usually followed by onClose. */
function onError(error) {
    console.error("[WS] WebSocket error event:", error);
    // Don't show error here, onClose will handle it and potentially reconnect
}

/** WebSocket onClose event handler. Handles cleanup and reconnection logic. */
function onClose(event) {
    const closedJobId = currentJobId;
    console.log(`[WS] Connection closed for job ${closedJobId}. Code: ${event.code}, Reason: '${event.reason}', Clean: ${event.wasClean}`);

    clearProgressAnimation();

    // Check current UI state
    const progress = parseInt(DOM.progressBar?.style.width || "0", 10);
    const statusEl = DOM.statusMessage;
    const wasErrorOrCancel = statusEl?.classList.contains('error') || event.code !== 1000;
    const isSuccess = progress >= 100 && !wasErrorOrCancel;
    const isJobComplete = progress >= 100;

    // Handle unexpected closure that warrants reconnection
    const shouldReconnect = !isManualClose &&
                            !isJobComplete &&
                            currentJobId &&
                            event.code !== 1000 &&
                            event.code !== 1001;

    if (shouldReconnect) {
        console.warn(`[WS] Unexpected closure (Code: ${event.code}). Attempting to reconnect...`);
        currentWebSocket = null; // Clear the socket reference before reconnecting
        scheduleReconnect();
        return; // Don't clean up state yet, we're trying to reconnect
    }

    // Normal closure or job complete - clean up
    if (!isSuccess && event.code !== 1000 && event.code !== 1001) {
        console.warn(`[WS] WebSocket closed unexpectedly (Code: ${event.code}) and not reconnecting.`);
        const closeReason = event.reason || `Code ${event.code}`;
        if (!statusEl || !statusEl.textContent || !statusEl.classList.contains('error')) {
            handleProcessingError(`Connection lost (${closeReason}). Processing may have failed.`);
        }
    }

    if (!isSuccess && DOM.processBtn) {
        DOM.processBtn.disabled = false;
    }

    if (!isSuccess) {
        UI.resetTitleAndFavicon();
    }

    if (!wasErrorOrCancel) {
        const lastStep = document.querySelector('#progress-steps-container .progress-step.active-step');
        if (lastStep) {
            lastStep.classList.remove('active-step');
            lastStep.classList.add('completed-step');
        }
    }

    // Clean up global state
    currentWebSocket = null;
    currentJobId = null;
    jobStartTime = null;
    lastReceivedProgress = 0;
}

/** Handles WebSocket connection errors during initial connection attempt. */
function handleConnectionError(errorMessage) {
    UI.showStatus(errorMessage, true);
    if (DOM.processBtn) DOM.processBtn.disabled = false;
    if (DOM.progressDisplay) DOM.progressDisplay.style.display = "none";
    clearProgressAnimation();
    clearReconnectTimeout();
    UI.resetTitleAndFavicon();

    currentWebSocket = null;
    currentJobId = null;
    jobStartTime = null;
    lastReceivedProgress = 0;
}

/**
 * Handles errors reported during processing.
 * @param {string} errorMessage - The error message to display.
 */
function handleProcessingError(errorMessage) {
    if (DOM.statusMessage && (!DOM.statusMessage.textContent || !DOM.statusMessage.classList.contains('error'))) {
        UI.showStatus(`Error: ${errorMessage}`, true);
    }

    if (DOM.progressBar) {
        DOM.progressBar.style.width = '100%';
        DOM.progressBar.classList.add('error');
        DOM.progressBar.setAttribute('aria-invalid', 'true');
    }

    if (DOM.progressText) {
        DOM.progressText.textContent = `Error - ${errorMessage}`;
    }

    if (DOM.processBtn) DOM.processBtn.disabled = false;

    clearProgressAnimation();
    clearReconnectTimeout();
    UI.resetTitleAndFavicon();

    if (DOM.resultsArea) {
        DOM.resultsArea.style.display = 'none';
        DOM.resultsArea.style.opacity = '0';
        DOM.resultsArea.style.maxHeight = '0';
    }

    if (DOM.stemsSection) {
        DOM.stemsSection.style.display = 'none';
        DOM.stemsSection.style.opacity = '0';
        DOM.stemsSection.style.maxHeight = '0';
    }

    destroyStemPlayers();
    jobStartTime = null;
    lastReceivedProgress = 0;
}

/** Starts the favicon and title animation interval timer. */
function startProgressAnimation() {
    if (progressUpdateInterval) return;
    faviconFrameIndex = 0;
    console.log("[Animation] Starting progress animation.");
    progressUpdateInterval = setInterval(updateProgressAnimation, 500);
}

/** Clears the favicon and title animation interval. */
function clearProgressAnimation() {
    if (progressUpdateInterval) {
        console.log("[Animation] Clearing progress animation interval.");
        clearInterval(progressUpdateInterval);
        progressUpdateInterval = null;
        requestAnimationFrame(UI.resetTitleAndFavicon);
    } else {
        requestAnimationFrame(UI.resetTitleAndFavicon);
    }
}

/** Updates the favicon and title for the current animation frame. */
function updateProgressAnimation() {
    if (!currentJobId || !currentWebSocket || currentWebSocket.readyState !== WebSocket.OPEN) {
        clearProgressAnimation();
        return;
    }

    const frame = FAVICON_FRAMES[faviconFrameIndex % FAVICON_FRAMES.length];
    const progress = parseInt(DOM.progressBar?.style.width || "0", 10);

    document.title = `(${progress}%) ${frame} Processing...`;

    if (DOM.faviconElement) {
        const svg = `<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>${frame}</text></svg>`;
        DOM.faviconElement.href = `data:image/svg+xml,${svg}`;
    }

    faviconFrameIndex++;
}

/**
 * Closes the current WebSocket connection gracefully.
 * @param {number} [code=1000] - WebSocket close code.
 * @param {string} [reason="Client action"] - Reason for closing.
 */
export function closeWebSocket(code = 1000, reason = "Client action") {
    isManualClose = true; // Prevent reconnection attempts
    clearReconnectTimeout();

    const ws = currentWebSocket;

    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        console.log(`[WS] Closing WebSocket connection for job ${currentJobId} manually (Code: ${code}, Reason: ${reason}).`);
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        try {
            ws.close(code, reason);
        } catch (e) {
            console.warn("[WS] Error during manual WebSocket close:", e);
        }
    }

    clearProgressAnimation();
    currentWebSocket = null;
    currentJobId = null;
    jobStartTime = null;
    lastReceivedProgress = 0;
}

/**
 * Returns the current WebSocket instance (or null if not connected).
 * @returns {WebSocket|null}
 */
export function getCurrentWebSocket() {
    return currentWebSocket;
}

/**
 * Returns the current job ID being tracked.
 * @returns {string|null}
 */
export function getCurrentJobId() {
    return currentJobId;
}

/**
 * Populates the lyrics sidebar with lyrics data.
 * Prioritizes: 1) Genius lyrics selected by user, 2) Lyrics from result, 3) Transcription from result
 * @param {Object} result - The processing result object
 */
function populateLyricsSidebar(result) {
    const textarea = DOM.fullLyricsTextarea;
    if (!textarea) {
        console.warn("[WS] Full lyrics textarea not found in DOM");
        return;
    }

    // Priority 1: Use Genius lyrics that were selected during the session
    if (window.selectedGeniusLyrics) {
        textarea.value = window.selectedGeniusLyrics;
        console.log("[WS] Populated lyrics sidebar with selected Genius lyrics");
        return;
    }

    // Priority 2: Use lyrics from result object (if backend returned them)
    if (result.lyrics) {
        textarea.value = result.lyrics;
        console.log("[WS] Populated lyrics sidebar with lyrics from result");
        return;
    }

    // Priority 3: Use transcription text from result
    if (result.transcription_text) {
        textarea.value = result.transcription_text;
        console.log("[WS] Populated lyrics sidebar with transcription text");
        return;
    }

    // No lyrics available
    textarea.value = "";
    textarea.placeholder = "No lyrics available for this track.";
    console.log("[WS] No lyrics data available for sidebar");
}
