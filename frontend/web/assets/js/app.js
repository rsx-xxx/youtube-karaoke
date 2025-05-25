// File: frontend/web/assets/js/app.js
// Main application logic, event handling, and coordination between modules.
// UPDATED (v5): Implement Enter key selects suggestion, use combined metadata/suggestion fetch trigger.

console.log("[App] Module loaded.");

// Import necessary modules and DOM references
import * as DOM from './dom.js';
import * as UI from './ui.js';
import * as API from './api.js';
import * as Suggestions from './suggestions.js'; // Import Suggestions module itself
import * as Stems from './stems.js';
import { connectWebSocket, closeWebSocket } from './websocket.js';
import * as Theme from './theme.js';
import { STEM_DEFINITIONS } from './config.js';

// Global state variable to hold the current job ID
let currentJobId = null;
let currentCancelController = null; // AbortController for cancellation fetch

/**
 * Main entry point. Runs after the DOM is fully loaded.
 */
document.addEventListener('DOMContentLoaded', () => {
    console.log("[App] DOMContentLoaded event fired. Initializing App...");
    try {
        Theme.initTheme();
        Suggestions.initSuggestions(); // Initializes suggestion listeners (input, focus, blur etc)
        setupCoreListeners(); // Sets up button clicks, checkboxes etc.
        UI.resetUI(); // Call reset which now includes toggleSubOptionsVisibility
        console.log("[App] Initialization complete.");
    } catch (e) {
        console.error("[App] CRITICAL ERROR during initialization:", e);
        alert("Application failed to initialize. Please check the console for details and refresh the page.");
    }
});

/**
 * Sets up all main UI event listeners for buttons, checkboxes, video player, etc.
 */
function setupCoreListeners() {
    console.log("[App] Setting up core listeners...");

    // --- Process Button ---
    if (DOM.processBtn) {
        DOM.processBtn.addEventListener("click", handleProcessClick);
        console.log("[App] Process button listener attached.");
    } else {
        console.error("[App] Process button not found!");
    }

    // --- Cancel Button ---
    const cancelBtn = document.getElementById('cancel-job-btn');
    if(cancelBtn) {
        cancelBtn.addEventListener('click', handleCancelClick);
        console.log("[App] Cancel button listener attached.");
    } else {
        console.warn("[App] Cancel button not found.");
    }

    // --- Subtitle Options ---
    if (DOM.generateSubtitlesCheckbox) {
        DOM.generateSubtitlesCheckbox.addEventListener("change", UI.toggleSubOptionsVisibility);
        console.log("[App] Subtitle checkbox listener attached.");
    } else {
        console.warn("[App] Subtitle checkbox not found.");
    }

    // --- Input Field Enter Key ---
     if (DOM.youtubeInput) {
        // Use keyup for Enter to ensure input value is finalized, but check keydown might be needed for prevention
        DOM.youtubeInput.addEventListener('keydown', handleInputEnterKey);
        console.log("[App] Input Enter key listener attached.");
    }

    // --- Stem Controls & Video ---
    setupGlobalStemControls();
    setupVideoEventListeners();

    // --- Stem Locking ---
    if (DOM.lockStems) {
        DOM.lockStems.addEventListener('change', Stems.handleLockStemsChange);
        console.log("[App] Lock stems listener attached.");
    } else {
        // This is fine if the element isn't critical
        // console.log("[App] Lock stems checkbox not found (element ID: #lock-stems).");
    }

    // --- Page Unload ---
    window.addEventListener("beforeunload", handlePageUnload);

    console.log("[App] Core listeners setup complete.");
}

/**
 * Handles Enter key press on the main input field.
 * Selects the first suggestion if dropdown is visible, otherwise triggers processing.
 */
function handleInputEnterKey(e) {
    // Check if Enter key was pressed and input is not empty
    if (e.key === 'Enter' && !e.isComposing && DOM.youtubeInput.value.trim()) {
        console.log("[App] Enter key detected in input.");
        e.preventDefault(); // Prevent default form submission/newline

        const dropdown = DOM.suggestionDropdownElement;
        const firstSuggestionItem = dropdown?.querySelector('.suggestion-item'); // Get first suggestion element

        // Check if dropdown is currently visible and has items
        // Check visibility property as opacity might still be transitioning
        if (dropdown && dropdown.style.visibility === 'visible' && firstSuggestionItem) {
            console.log("[App] Enter pressed with suggestions visible. Selecting first suggestion.");

            // Simulate a mousedown event on the first item to trigger selection
            // Mousedown is used in suggestions.js to prevent input blur before selection
             firstSuggestionItem.dispatchEvent(new MouseEvent('mousedown', {
                bubbles: true,
                cancelable: true,
                view: window
            }));
             // Immediately hide dropdown after selection via Enter
             UI.hideSuggestionDropdown();
             // Suggestions.isDropdownOpen = false; // Ensure state is updated if accessible

        } else {
            console.log("[App] Enter pressed, no suggestions visible/available. Triggering process click.");
            // Trigger processing if button is enabled
            if (DOM.processBtn && !DOM.processBtn.disabled) {
                handleProcessClick(); // Trigger the same function as clicking the button
            } else {
                console.log("[App] Process button is disabled, cannot process via Enter.");
            }
        }
    }
}


// setupGlobalStemControls remains the same
function setupGlobalStemControls() {
    if (DOM.playAllStemsBtn) {
        DOM.playAllStemsBtn.onclick = handlePlayPauseAll;
    }
    if (DOM.resetAllStemsBtn) {
        DOM.resetAllStemsBtn.onclick = handleResetAll;
    }
    if (DOM.globalSpeedSlider) {
        const speedValueDisplay = DOM.globalSpeedValue;
        if (speedValueDisplay) {
            DOM.globalSpeedSlider.addEventListener('input', (e) => {
                const speed = parseFloat(e.target.value);
                speedValueDisplay.textContent = `${speed.toFixed(2)}x`;
                Stems.updateVideoPlaybackRate(); // Ensure this function exists and works
            });
            speedValueDisplay.textContent = `${parseFloat(DOM.globalSpeedSlider.value).toFixed(2)}x`;
        } else {
             console.warn("[App] Global speed value display element not found.");
         }
    } else {
         console.warn("[App] Global speed slider element not found.");
     }
}

// setupVideoEventListeners remains the same
function setupVideoEventListeners() {
    if (!DOM.karaokeVideo) {
        console.warn("[App] Main karaoke video element not found.");
        return;
    }
    // Play Sync
    DOM.karaokeVideo.addEventListener('play', () => {
        const videoTime = DOM.karaokeVideo.currentTime;
        // console.log(`[Sync] Video played at ${videoTime.toFixed(2)}s. Syncing stems.`);
        const stems = Stems.getStemInstances();
        stems.forEach((ws, i) => {
            if (ws && Stems.isStemReady(i) && !ws.isPlaying()) {
                try {
                     const dur = ws.getDuration();
                     if (dur > 0) {
                         ws.seekTo(Math.max(0, Math.min(videoTime / dur, 1)));
                         // console.log(`[Sync] Seeking stem ${i} to match video time.`);
                     }
                     ws.play();
                } catch (e) { console.warn(`[Sync] Error playing/seeking stem ${i}:`, e); }
            }
        });
        if (DOM.playAllStemsBtn) {
            DOM.playAllStemsBtn.innerHTML = '<span class="button-icon">⏸️</span> Pause All';
        }
    });
    // Pause Sync
    DOM.karaokeVideo.addEventListener('pause', () => {
        // console.log("[Sync] Video paused. Pausing stems.");
        Stems.getStemInstances().forEach((ws, i) => {
            if (ws && ws.isPlaying() && Stems.isStemReady(i)) {
                try { ws.pause(); } catch (e) { console.warn(`[Sync] Error pausing stem ${i}:`, e); }
            }
        });
        if (DOM.playAllStemsBtn) {
            DOM.playAllStemsBtn.innerHTML = '<span class="button-icon">▶️</span> Play All';
        }
    });
    // Seek Sync
    let seekTimer;
    DOM.karaokeVideo.addEventListener('seeking', () => { clearTimeout(seekTimer); });
    DOM.karaokeVideo.addEventListener('seeked', () => {
        clearTimeout(seekTimer);
        seekTimer = setTimeout(() => {
            const videoTime = DOM.karaokeVideo.currentTime;
            console.log(`[Sync] Video seeked to ${videoTime.toFixed(2)}s. Syncing stems.`);
            Stems.getStemInstances().forEach((ws, i) => {
                if (ws && Stems.isStemReady(i)) {
                     try {
                        const dur = ws.getDuration();
                        if (dur > 0) {
                            const targetRatio = Math.max(0, Math.min(videoTime / dur, 1));
                             if (Math.abs(ws.getCurrentTime() - videoTime) > 0.2) { // Only seek if needed
                                ws.seekTo(targetRatio);
                                // console.log(`[Sync] Seeking stem ${i} to match video time after seek.`);
                            }
                             // Sync play/pause state after seek
                             if (!DOM.karaokeVideo.paused && !ws.isPlaying()) { ws.play(); }
                             else if (DOM.karaokeVideo.paused && ws.isPlaying()) { ws.pause(); }
                        }
                     } catch(e) { console.warn(`[Sync] Error seeking/playing stem ${i} after video seek:`, e); }
                }
            });
        }, 200); // Increased delay slightly
    });
    // End Sync
    DOM.karaokeVideo.addEventListener('ended', () => {
        // console.log("[Sync] Video ended. Resetting play button.");
        if (DOM.playAllStemsBtn) {
            DOM.playAllStemsBtn.innerHTML = '<span class="button-icon">▶️</span> Play All';
        }
    });
     // Rate Change (currently just logs)
     DOM.karaokeVideo.addEventListener('ratechange', () => {
        // console.log(`[Sync] Video rate changed to ${DOM.karaokeVideo.playbackRate}.`);
    });
}

// handlePlayPauseAll remains the same
function handlePlayPauseAll() {
    const video = DOM.karaokeVideo;
    if (!video || !DOM.playAllStemsBtn || DOM.playAllStemsBtn.disabled) return;
    if (video.paused) {
        console.log("[App] Play All requested.");
        video.play().catch(e => console.warn("Video play failed:", e));
    } else {
        console.log("[App] Pause All requested.");
        video.pause();
    }
}

// handleResetAll remains the same
function handleResetAll() {
     if (!DOM.resetAllStemsBtn || DOM.resetAllStemsBtn.disabled) return;
    console.log("[App] Reset All requested.");
    if (DOM.karaokeVideo) {
        DOM.karaokeVideo.pause();
        DOM.karaokeVideo.currentTime = 0;
    }
    Stems.getStemInstances().forEach(ws => {
        if (ws) {
            try { ws.seekTo(0); ws.pause(); }
            catch (e) { console.warn("[App] Error resetting stem:", e); }
        }
    });
    if (DOM.playAllStemsBtn) {
        DOM.playAllStemsBtn.innerHTML = '<span class="button-icon">▶️</span> Play All';
    }
}

// handlePageUnload remains the same
function handlePageUnload(event) {
    console.log("[App] Page unloading...");
    if (currentJobId) {
        API.cancelJobBeacon(currentJobId);
        console.log(`[App] Sent cancellation beacon for job ${currentJobId}.`);
    }
    closeWebSocket(1001, "Page unloading");
    Stems.destroyStemPlayers();
}

// handleCancelClick remains the same
async function handleCancelClick() {
    const btn = document.getElementById('cancel-job-btn');
    if (!currentJobId || !btn || btn.disabled) return;
    console.log(`[App] Attempting to cancel job: ${currentJobId}`);
    btn.disabled = true;
    btn.innerHTML = `<span class="button-icon">⏳</span> Cancelling...`;
    if (currentCancelController) currentCancelController.abort("New cancel request");
    currentCancelController = new AbortController();
    const signal = currentCancelController.signal;
    try {
        const response = await fetch(`${API.API_CANCEL_JOB}?job_id=${encodeURIComponent(currentJobId)}`, { method: 'POST', signal });
        if (signal.aborted) { console.log("[App] Cancel request aborted."); return; }
        if (response.ok) { console.log("[App] Job cancellation request successful:", await response.json()); }
        else {
            const errorData = await response.text();
            console.error(`[App] Failed to cancel job ${currentJobId}. Status: ${response.status}, Response: ${errorData}`);
            UI.showStatus(`Failed to cancel job: ${response.statusText || 'Server error'}`, true);
             btn.disabled = false; btn.innerHTML = `<span class="button-icon">✖️</span> Cancel Job`;
        }
    } catch (error) {
        if (error.name === 'AbortError') { console.log("[App] Cancel fetch aborted."); }
        else {
            console.error("[App] Error sending cancel request:", error);
            UI.showStatus(`Error cancelling job: ${error.message}`, true);
            btn.disabled = false; btn.innerHTML = `<span class="button-icon">✖️</span> Cancel Job`;
        }
    } finally { currentCancelController = null; }
}


/**
 * Handles the click event on the main "Process" button.
 */
async function handleProcessClick() {
    console.log("[App] Process button clicked.");

    if (!DOM.youtubeInput) {
        console.error("[App] YouTube input element not found!");
        return;
    }
    const urlOrSearch = DOM.youtubeInput.value.trim();
    if (!urlOrSearch) {
        UI.showStatus("Please enter a YouTube link or search query.", true);
        DOM.youtubeInput.focus();
        return;
    }

    console.log(`[App] Processing requested for: "${urlOrSearch}"`);

    // --- Prepare for new job ---
    console.log("[App] Cleaning up UI for new job...");
    Suggestions.clearSuggestionTimeout(); // Ensure suggestion fetching stops
    UI.hideSuggestionDropdown(); // Explicitly hide dropdown
    // Suggestions.isDropdownOpen = false; // Reset state if accessible

    UI.resetUI(); // Use consolidated reset function (this also hides sections)

    // --- Show processing state ---
    UI.showProcessingUI(); // Handles disabling button, showing progress, etc.

    try {
        // --- Gather Inputs & Options ---
        const customLyrics = window.selectedGeniusLyrics || null; // Get selected lyrics
        const language = DOM.languageSelect?.value || 'auto';
        const position = DOM.subtitlePositionSelect?.value || 'bottom';
        const generateSubs = DOM.generateSubtitlesCheckbox?.checked ?? true;
        const finalSubtitleSize = parseInt(DOM.finalSubtitleSizeSelect?.value || '30', 10);

        // --- Gather Pitch Shifts (Optional Refinement Check) ---
        let finalPitchShifts = null;
        if (DOM.stemsContainer && DOM.stemsContainer.children.length > 0) { // Check if stems UI exists
            const pitchValues = Stems.getStemPitches();
            const pitchShiftsPayload = {};
            let hasPitchShift = false;
            STEM_DEFINITIONS.forEach((stemDef, index) => {
                const pitch = pitchValues[index];
                if (pitch !== undefined && pitch !== 0 && index < pitchValues.length) {
                    pitchShiftsPayload[stemDef.name.toLowerCase()] = pitch;
                    hasPitchShift = true;
                }
            });
            if (hasPitchShift) finalPitchShifts = pitchShiftsPayload;
        } else {
             // console.log("[App] No existing stems UI found, skipping pitch retrieval."); // Less verbose
        }
        // ---------------------------------------

        console.log("[App] Final Subtitle Size to send:", finalSubtitleSize);
        console.log("[App] Pitch shift settings to send:", finalPitchShifts);
        console.log("[App] Custom Lyrics selected:", !!customLyrics);

        // --- Start Backend Job ---
        console.log("[App] Calling API.startProcessingJob...");
        const jobId = await API.startProcessingJob(
            urlOrSearch, language, position, generateSubs,
            customLyrics, finalPitchShifts, finalSubtitleSize
        );
        currentJobId = jobId; // Store the new job ID
        console.log(`[App] Job initiated with ID: ${jobId}. Connecting WebSocket...`);

        // --- Connect WebSocket ---
        connectWebSocket(currentJobId); // Connect with the new job ID
        console.log("[App] WebSocket connection initiated.");

    } catch (error) {
        console.error("[App] Failed to start processing job via API:", error);
        handleProcessingFailure(`Job start failed: ${error.message || 'Unknown API error'}`);
    }
}

// handleProcessingFailure remains the same
function handleProcessingFailure(errorMessage) {
    console.error(`[App] Processing start failed: ${errorMessage}`);
    UI.showStatus(errorMessage, true);
    if (DOM.processBtn) DOM.processBtn.disabled = false;
    if (DOM.progressDisplay) {
        DOM.progressDisplay.style.opacity = '0';
        DOM.progressDisplay.style.maxHeight = '0';
        setTimeout(() => { if (DOM.progressDisplay && DOM.progressDisplay.style.opacity === '0') DOM.progressDisplay.style.display = 'none'; }, 400);
    }
     const cancelBtn = document.getElementById('cancel-job-btn');
     if (cancelBtn) cancelBtn.style.display = 'none';
    currentJobId = null;
    Stems.destroyStemPlayers();
    if (DOM.stemsSection) {
        DOM.stemsSection.style.display = 'none';
        DOM.stemsSection.style.opacity = '0';
        DOM.stemsSection.style.maxHeight = '0';
    }
    closeWebSocket(1011, "Processing start failed");
    UI.resetTitleAndFavicon(); // Ensure title/favicon are reset on failure
}