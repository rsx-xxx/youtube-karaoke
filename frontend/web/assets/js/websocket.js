// File: frontend/web/assets/js/websocket.js
// Handles WebSocket connection for real-time progress updates.

import * as UI from './ui.js';
import { createStemPlayers, destroyStemPlayers } from './stems.js';
import * as DOM from './dom.js'; // Ensure DOM is imported
import { BASE_TITLE, DEFAULT_FAVICON, FAVICON_FRAMES } from './config.js'; // Import config

let currentWebSocket = null;
let currentJobId = null;
let jobStartTime = null; // Timestamp when the current job started
let progressUpdateInterval = null; // Interval timer for favicon/title animation
let faviconFrameIndex = 0; // Current frame index for animation

/**
 * Connects to the WebSocket endpoint for the given job ID.
 * Handles opening, message receiving, errors, and closing.
 * @param {string} jobId - The unique ID of the job to track.
 */
export function connectWebSocket(jobId) {
    // Close any existing connection cleanly before starting a new one
    if (currentWebSocket && currentWebSocket.readyState !== WebSocket.CLOSED) {
        console.warn("[WS] Attempting to connect while previous socket exists. Closing old one.");
        closeWebSocket(1001, "New connection requested"); // Use custom close code
    }
    clearProgressAnimation(); // Stop any previous animation

    // Store job info and start time
    currentJobId = jobId;
    jobStartTime = Date.now(); // Record start time for elapsed calculation

    // Determine WebSocket protocol (ws or wss)
    const proto = (location.protocol === "https:") ? "wss://" : "ws://";
    // Construct the WebSocket URL
    const wsUrl = `${proto}${location.host}/api/ws/progress/${jobId}`;
    console.log("[WS] Connecting to:", wsUrl);

    try {
        // Create the WebSocket instance
        currentWebSocket = new WebSocket(wsUrl);

        // Assign event handlers
        currentWebSocket.onopen = onOpen;
        currentWebSocket.onmessage = onMessage;
        currentWebSocket.onerror = onError;
        currentWebSocket.onclose = onClose;

    } catch (e) {
        console.error("[WS] Error creating WebSocket instance:", e);
        handleConnectionError("Failed to create WebSocket connection.");
    }
}

/** WebSocket onOpen event handler. Called when connection is established. */
function onOpen() {
    console.log(`[WS] Connection successfully opened for job ${currentJobId}`);
    startProgressAnimation(); // Start favicon/title animation
}

/** WebSocket onMessage event handler. Processes incoming progress data. */
function onMessage(event) {
    try {
        const data = JSON.parse(event.data);
        // console.debug("[WS] Received data:", data); // Uncomment for verbose logging

        // Update the main progress UI elements (bar, text, steps)
        UI.updateProgressUI(data, jobStartTime); // Pass start time for elapsed calculation

        // Check if the job has reached 100% progress
        if (data.progress >= 100) {
            console.log("[WS] Progress reached 100%. Checking for results...");
            clearProgressAnimation(); // Stop animation on completion

            if (data.result) {
                // --- Job Success ---
                console.log("[WS] Received final result message:", data.result);
                UI.displayResults(data.result); // Show video, download/share buttons

                // --- Stem Player Logic ---
                if (data.result.stems_base_path && data.result.video_id) {
                    console.log("[WS] Stems data found in result. Preparing to display stems section.");
                    if (DOM.stemsSection) {
                        // *** Ensure section is visible BEFORE creating players ***
                        console.log("[WS] Making stems section visible (display: block).");
                        DOM.stemsSection.style.display = 'block';
                        requestAnimationFrame(() => { // Use rAF for smoother transition start
                            DOM.stemsSection.style.opacity = '1';
                            DOM.stemsSection.style.maxHeight = '3000px'; // Allow height
                            console.log("[WS] Stems section opacity and max-height set for visibility.");

                             // Now create the players *after* the container is potentially visible
                            console.log("[WS] Calling createStemPlayers...");
                            if (typeof WaveSurfer !== 'undefined') {
                                createStemPlayers(data.result.stems_base_path, data.result.video_id);
                            } else {
                                console.error("[WS] WaveSurfer library not loaded! Cannot create stem players.");
                                if (DOM.stemsContainer) {
                                    DOM.stemsContainer.innerHTML = '<p class="error-message">Error: WaveSurfer library failed to load.</p>';
                                }
                            }
                        });
                    } else {
                        console.warn("[WS] Stems section element (#stems-section) not found in DOM. Cannot display stems.");
                    }
                } else {
                    // No stems data in result, ensure section is hidden and players are cleaned up
                    console.log("[WS] No stems_base_path in result. Hiding stems section and destroying players.");
                    if (DOM.stemsSection) {
                        DOM.stemsSection.style.display = 'none'; // Hide section
                        DOM.stemsSection.style.opacity = '0';
                        DOM.stemsSection.style.maxHeight = '0';
                    }
                    destroyStemPlayers(); // Clean up any residual players
                }
                 // ---------------------------

            } else {
                // --- Job Finished but No Result (Likely Error) ---
                const errorMessage = data.message || "Processing finished with incomplete data or an error.";
                console.warn(`[WS] Reached 100% but no 'result' object. Message: "${errorMessage}"`);
                handleProcessingError(errorMessage); // Use the dedicated error handler
                // Ensure stems section is hidden on error
                 if (DOM.stemsSection) {
                    DOM.stemsSection.style.display = 'none';
                    DOM.stemsSection.style.opacity = '0';
                    DOM.stemsSection.style.maxHeight = '0';
                 }
                 destroyStemPlayers();
            }

            // Optional: Close WebSocket explicitly after processing is fully complete
            // Consider keeping it open briefly in case of delayed cleanup messages?
            // closeWebSocket(1000, "Processing complete");

        } else if (data.error) {
            // --- Explicit Error Flag from Backend ---
             console.error("[WS] Received explicit error flag from backend:", data.message);
             handleProcessingError(data.message || "An unknown error occurred during processing.");
             clearProgressAnimation();
             closeWebSocket(1011, "Backend reported error"); // Use specific code for server error
        }

    } catch (e) {
        // --- Error Parsing Message or Updating UI ---
        console.error("[WS] Error parsing message or updating UI:", e, "\nRaw data:", event.data);
        // Attempt to show a generic error to the user
        handleProcessingError("Failed to process WebSocket update. Check console.");
        clearProgressAnimation();
        // Consider closing the socket here if errors persist
        // closeWebSocket(1011, "WebSocket message processing error");
    }
}

/** WebSocket onError event handler. Usually followed by onClose. */
function onError(error) {
    console.error("[WS] WebSocket error event:", error);
    // Don't necessarily show a user-facing error here, as onClose will handle the disconnection
    // handleProcessingError("WebSocket connection error occurred.");
    clearProgressAnimation();
    // The 'onclose' event will likely provide more details via the event code.
}

/** WebSocket onClose event handler. Cleans up state and handles unexpected closures. */
function onClose(event) {
    const closedJobId = currentJobId; // Capture before resetting
    console.log(`[WS] Connection closed for job ${closedJobId}. Code: ${event.code}, Reason: '${event.reason}', Clean: ${event.wasClean}`);

    clearProgressAnimation(); // Ensure animation stops

    // Check current UI state to determine if job finished successfully before closure
    const progress = parseInt(DOM.progressBar?.style.width || "0", 10);
    const statusEl = DOM.statusMessage;
    // Check if an error was already displayed or if close code indicates an issue
    const wasErrorOrCancel = statusEl?.classList.contains('error') ||
                             event.code !== 1000; // 1000 is normal closure
    const isSuccess = progress >= 100 && !wasErrorOrCancel;

    // If closed unexpectedly *before* reaching 100% success state
    if (!isSuccess && event.code !== 1000 && event.code !== 1001) { // 1001 = Going Away (e.g., page navigation)
        console.warn(`[WS] WebSocket closed unexpectedly (Code: ${event.code}) before job completion.`);
        const closeReason = event.reason || `Code ${event.code}`;
        // Show error only if a specific error wasn't already displayed
        if (!statusEl || !statusEl.textContent || !statusEl.classList.contains('error')) {
             handleProcessingError(`Connection lost unexpectedly (${closeReason}). Job status uncertain.`);
        }
    }

    // Re-enable process button if the job didn't finish successfully
    if (!isSuccess && DOM.processBtn) {
        DOM.processBtn.disabled = false;
    }

    // Reset title/favicon if the job didn't complete successfully
    if (!isSuccess) {
        UI.resetTitleAndFavicon();
    }

     // Mark the last active step as completed visually if it exists and job didn't error
     if (!wasErrorOrCancel) {
         const lastStep = document.querySelector('#progress-steps-container .progress-step.active-step');
         if(lastStep) {
             lastStep.classList.remove('active-step');
             lastStep.classList.add('completed-step');
         }
     }

    // Clean up global state associated with this connection
    currentWebSocket = null;
    currentJobId = null;
    jobStartTime = null; // Reset job start time
}

/** Handles WebSocket connection errors *during initial connection attempt*. */
function handleConnectionError(errorMessage) {
    UI.showStatus(errorMessage, true); // Show error message
    if (DOM.processBtn) DOM.processBtn.disabled = false; // Re-enable button
    if (DOM.progressDisplay) DOM.progressDisplay.style.display = "none"; // Hide progress
    clearProgressAnimation();
    UI.resetTitleAndFavicon();
    // Ensure state is reset
    currentWebSocket = null;
    currentJobId = null;
    jobStartTime = null;
}

/**
 * Handles errors reported *during* processing (via onMessage error flag or onError/onClose).
 * Updates UI to reflect the error state.
 * @param {string} errorMessage - The error message to display.
 */
function handleProcessingError(errorMessage) {
     // Show error status, preventing overwrite if a more specific error exists
     if (DOM.statusMessage && (!DOM.statusMessage.textContent || !DOM.statusMessage.classList.contains('error'))) {
        UI.showStatus(`Error: ${errorMessage}`, true);
    }
     // Visually mark progress bar as error state (e.g., red)
     if(DOM.progressBar) {
         DOM.progressBar.style.width = '100%'; // Show full bar but in error color
         DOM.progressBar.classList.add('error');
         DOM.progressBar.setAttribute('aria-invalid', 'true');
     }
     // Update progress text to show error
     if (DOM.progressText) {
         DOM.progressText.textContent = `Error - ${errorMessage}`;
     }
     // Re-enable process button
     if (DOM.processBtn) DOM.processBtn.disabled = false;

     clearProgressAnimation(); // Stop animation
     UI.resetTitleAndFavicon(); // Reset title/favicon

     // Hide results and stems sections if an error occurred
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
     destroyStemPlayers(); // Clean up stem players
     jobStartTime = null; // Reset job start time
}


/** Starts the favicon and title animation interval timer. */
function startProgressAnimation() {
    if (progressUpdateInterval) return; // Prevent multiple intervals
    faviconFrameIndex = 0; // Reset animation frame
    console.log("[Animation] Starting progress animation.");
    // Update animation every 500ms
    progressUpdateInterval = setInterval(updateProgressAnimation, 500);
}

/** Clears the favicon and title animation interval and resets them to default. */
function clearProgressAnimation() {
    if (progressUpdateInterval) {
        console.log("[Animation] Clearing progress animation interval.");
        clearInterval(progressUpdateInterval);
        progressUpdateInterval = null;
        // Reset title and favicon smoothly after clearing interval
        requestAnimationFrame(UI.resetTitleAndFavicon);
    } else {
         // Ensure reset happens even if interval wasn't running (e.g., error before start)
         requestAnimationFrame(UI.resetTitleAndFavicon);
    }
}

/** Updates the favicon and title for the current animation frame. */
function updateProgressAnimation() {
    // Stop animation if job ended or socket closed/closing
    if (!currentJobId || !currentWebSocket || currentWebSocket.readyState !== WebSocket.OPEN) {
        clearProgressAnimation();
        return;
    }

    // Cycle through favicon frames
    const frame = FAVICON_FRAMES[faviconFrameIndex % FAVICON_FRAMES.length];
    // Get current progress percentage from UI
    const progress = parseInt(DOM.progressBar?.style.width || "0", 10);

    // Update document title
    document.title = `(${progress}%) ${frame} Processing...`;

    // Update favicon using SVG data URI
    if (DOM.faviconElement) {
        const svg = `<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>${frame}</text></svg>`;
        DOM.faviconElement.href = `data:image/svg+xml,${svg}`;
    }
    faviconFrameIndex++; // Move to next frame
}

/**
 * Closes the current WebSocket connection gracefully if it exists and is open or connecting.
 * @param {number} [code=1000] - WebSocket close code (1000 for normal closure).
 * @param {string} [reason="Client action"] - Reason for closing.
 */
export function closeWebSocket(code = 1000, reason = "Client action") {
    const ws = currentWebSocket; // Capture current socket instance

    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        console.log(`[WS] Closing WebSocket connection for job ${currentJobId} manually (Code: ${code}, Reason: ${reason}).`);
        // Clean up handlers *before* closing to prevent them firing unexpectedly
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null; // Prevent the onClose handler from running again for this manual close
        try {
            ws.close(code, reason);
        } catch (e) {
            console.warn("[WS] Error during manual WebSocket close:", e);
        }
    } else {
        // console.log("[WS] closeWebSocket called but no active/connecting socket found.");
    }

    // Always clear animation and reset state variables when explicitly closing
    clearProgressAnimation();
    currentWebSocket = null;
    currentJobId = null;
    jobStartTime = null;
}

/**
 * Returns the current WebSocket instance (or null if not connected).
 * @returns {WebSocket|null}
 */
export function getCurrentWebSocket() {
    return currentWebSocket;
}