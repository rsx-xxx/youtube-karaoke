// File: frontend/web/assets/js/ui.js
// Manages UI updates, state resets, progress display, and interactions.
// UPDATED (v5): Added hideOptionsAndGenius helper function.

import * as DOM from './dom.js';
import {BASE_TITLE, DEFAULT_FAVICON} from './config.js';

console.log("[UI] Module loaded.");

// --- Helper Functions ---


/**
 * Updates the main input field and video preview area when a suggestion is selected.
 */
export function updateInputWithSuggestion(item) {
    console.log("[UI] Updating input with suggestion:", item);
    if (!item) return;

    if (DOM.youtubeInput) {
        DOM.youtubeInput.value = item.url || "";
    } else {
        console.warn("[UI] YouTube input element not found.");
    }

    if (DOM.chosenVideoTitleDiv) {
        DOM.chosenVideoTitleDiv.textContent = item.title ? `Selected: ${item.title}` : "";
    } else {
        console.warn("[UI] Chosen video title element not found.");
    }

    if (DOM.videoPreview) {
        if (item.thumbnail) {
            DOM.videoPreview.src = item.thumbnail;
            DOM.videoPreview.alt = `Thumbnail for ${item.title}`;
            DOM.videoPreview.style.display = "block";
            // Trigger animation after display block
            requestAnimationFrame(() => {
                DOM.videoPreview.style.opacity = '1';
                DOM.videoPreview.style.maxHeight = '90px';
            });
        } else {
            clearPreview();
        }
    } else {
        console.warn("[UI] Video preview image element not found.");
    }

    // Hide Genius related things when a new item is selected (before genius fetch)
    const lyricsPanel = document.getElementById("lyrics-panel");
    const toggleBtn = document.getElementById("lyrics-toggle-btn");
    const textArea = DOM.geniusSelectedText;
    if (lyricsPanel) lyricsPanel.classList.add("hidden");
    if (toggleBtn) {
        toggleBtn.setAttribute("aria-expanded", "false");
        toggleBtn.classList.remove('expanded');
    }
    if (textArea) textArea.value = "";
    window.selectedGeniusLyrics = null;
    if (DOM.geniusLyricsList) DOM.geniusLyricsList.innerHTML = "";
    // Don't hide the main genius container here, let fetchAndDisplayGeniusCandidates handle it
}

/**
 * Clears the video preview image and the chosen title text.
 */
export function clearPreview() {
    if (DOM.chosenVideoTitleDiv) {
        DOM.chosenVideoTitleDiv.textContent = "";
    }
    if (DOM.videoPreview) {
        DOM.videoPreview.style.opacity = '0';
        DOM.videoPreview.style.maxHeight = '0';
        setTimeout(() => {
            if (DOM.videoPreview && parseFloat(DOM.videoPreview.style.opacity || 0) === 0) {
                DOM.videoPreview.style.display = "none";
                DOM.videoPreview.src = "";
                DOM.videoPreview.alt = "";
            }
        }, 300);
    }
}

/**
 * Resets the document title and favicon to their default states.
 */
export function resetTitleAndFavicon() {
    document.title = BASE_TITLE;
    if (DOM.faviconElement) {
        DOM.faviconElement.href = DEFAULT_FAVICON;
    } else {
        console.warn("[UI] Favicon element (#favicon) not found.");
    }
}

/**
 * Toggles the visibility and disabled state of subtitle/lyrics options
 */
export function toggleSubOptionsVisibility() {
    if (!DOM.generateSubtitlesCheckbox) {
        console.warn("[UI] 'Add Lyrics' checkbox (#generate-subtitles-checkbox) not found.");
        return;
    }
    const enableLyrics = DOM.generateSubtitlesCheckbox.checked;
    console.log(`[UI] Toggling Subtitle Options Visibility. Lyrics Enabled: ${enableLyrics}`);

    if (DOM.languageSelect) DOM.languageSelect.disabled = !enableLyrics;
    if (DOM.subtitlePositionSelect) DOM.subtitlePositionSelect.disabled = !enableLyrics;
    if (DOM.finalSubtitleSizeSelect) DOM.finalSubtitleSizeSelect.disabled = !enableLyrics;

    if (DOM.subtitleOptionsContainer) {
        const generalOptionsGroup = DOM.subtitleOptionsContainer.querySelector(':scope > .options-group:not(#genius-lyrics-container)');
        if (generalOptionsGroup) {
            const controlsToFade = generalOptionsGroup.querySelectorAll('.option-item:not(.checkbox-item)');
            controlsToFade.forEach(item => {
                item.style.opacity = enableLyrics ? '1' : '0.5';
                item.style.pointerEvents = enableLyrics ? 'auto' : 'none';
            });
            const mainCheckboxItem = generalOptionsGroup.querySelector('.option-item.checkbox-item');
            if (mainCheckboxItem) {
                mainCheckboxItem.style.opacity = '1';
                mainCheckboxItem.style.pointerEvents = 'auto';
            }
        }
    }

    if (DOM.geniusLyricsContainer && DOM.subtitleOptionsContainer) {
        const optionsAreVisible = DOM.subtitleOptionsContainer.style.display !== 'none' && parseFloat(DOM.subtitleOptionsContainer.style.opacity || 0) > 0;
        const shouldShowGenius = enableLyrics && optionsAreVisible;
        console.log(`[UI] Should show Genius section? ${shouldShowGenius} (EnableLyrics: ${enableLyrics}, OptionsVisible: ${optionsAreVisible})`);

        if (shouldShowGenius) {
            DOM.geniusLyricsContainer.style.display = 'flex';
            requestAnimationFrame(() => {
                DOM.geniusLyricsContainer.style.opacity = '1';
                DOM.geniusLyricsContainer.style.maxHeight = '700px';
            });
        } else {
            // Hide genius section if lyrics disabled or options hidden
            hideOptionsAndGenius(); // Use the helper to ensure cleanup
        }
    }
}


/**
 * Displays a status message to the user.
 */
export function showStatus(message, isError = false) {
    if (DOM.statusMessage) {
        console.log(`[UI] Showing status (Error: ${isError}): ${message}`);
        DOM.statusMessage.textContent = message;
        DOM.statusMessage.className = isError ? 'error' : 'success';
        DOM.statusMessage.setAttribute('role', isError ? 'alert' : 'status');
        DOM.statusMessage.style.display = 'block';
        requestAnimationFrame(() => {
            DOM.statusMessage.style.opacity = '1';
            DOM.statusMessage.style.maxHeight = '100px';
        });

    } else {
        console.warn("[UI] Status message element (#status-message) not found. Message:", message);
        alert(`${isError ? 'Error: ' : ''}${message}`);
    }
}

/**
 * Clears the status message area.
 */
export function clearStatus() {
    if (DOM.statusMessage && DOM.statusMessage.style.display !== 'none') {
        // console.log("[UI] Clearing status message."); // Less verbose
        DOM.statusMessage.style.opacity = '0';
        DOM.statusMessage.style.maxHeight = '0';
        const clearContent = () => {
            if (DOM.statusMessage) {
                DOM.statusMessage.textContent = '';
                DOM.statusMessage.className = '';
                DOM.statusMessage.removeAttribute('role');
                DOM.statusMessage.style.display = 'none';
                DOM.statusMessage.removeEventListener('transitionend', clearContent);
            }
        };
        if (getComputedStyle(DOM.statusMessage).transitionProperty !== 'none') {
            DOM.statusMessage.addEventListener('transitionend', clearContent, {once: true});
        } else {
            setTimeout(clearContent, 300);
        }
    }
}

/**
 * Resets the entire UI to its initial, default state.
 */
export function resetUI() {
    console.log("[UI] Resetting UI to initial state.");

    if (DOM.youtubeInput) DOM.youtubeInput.value = "";
    clearPreview();
    clearStatus();

    // Reset Progress Display
    if (DOM.progressDisplay) {
        DOM.progressDisplay.style.opacity = '0';
        DOM.progressDisplay.style.maxHeight = '0';
        setTimeout(() => {
            if (DOM.progressDisplay && DOM.progressDisplay.style.opacity === '0') DOM.progressDisplay.style.display = "none";
        }, 400);
    }
    if (DOM.progressBar) {
        DOM.progressBar.style.width = "0%";
        DOM.progressBar.classList.remove('error');
        DOM.progressBar.ariaValueNow = "0";
        DOM.progressBar.removeAttribute('aria-invalid');
    }
    if (DOM.progressText) DOM.progressText.textContent = "";
    if (DOM.progressTiming) DOM.progressTiming.textContent = "";
    if (DOM.progressStepsContainer) DOM.progressStepsContainer.innerHTML = "";
    const cancelBtn = document.getElementById("cancel-job-btn");
    if (cancelBtn) cancelBtn.style.display = 'none';

    // Reset Results Area
    if (DOM.resultsArea) {
        DOM.resultsArea.style.opacity = '0';
        DOM.resultsArea.style.maxHeight = '0';
        setTimeout(() => {
            if (DOM.resultsArea && DOM.resultsArea.style.opacity === '0') DOM.resultsArea.style.display = "none";
        }, 500);
    }
    if (DOM.karaokeVideo) {
        DOM.karaokeVideo.removeAttribute("src");
        DOM.karaokeVideo.load();
    }
    const videoTitleEl = document.getElementById("video-title");
    if (videoTitleEl) videoTitleEl.textContent = "Karaoke Video";

    if (DOM.downloadBtn) {
        DOM.downloadBtn.style.display = "none";
        DOM.downloadBtn.href = "#";
    }
    if (DOM.shareBtn) {
        DOM.shareBtn.style.display = "none";
        DOM.shareBtn.onclick = null;
        DOM.shareBtn.disabled = false;
        DOM.shareBtn.innerHTML = `<span class="button-icon" aria-hidden="true">🔗</span> Copy Link`;
    }

    if (DOM.processBtn) DOM.processBtn.disabled = false;

    hideSuggestionDropdown();
    hideSuggestionSpinner();

    // Reset and hide options sections using the helper
    hideOptionsAndGenius();

    // Reset option defaults that might have been changed
    if (DOM.generateSubtitlesCheckbox) DOM.generateSubtitlesCheckbox.checked = true;
    if (DOM.languageSelect) DOM.languageSelect.value = 'auto';
    if (DOM.subtitlePositionSelect) DOM.subtitlePositionSelect.value = 'bottom';
    if (DOM.finalSubtitleSizeSelect) DOM.finalSubtitleSizeSelect.value = '30'; // Default size
    // Call toggleSubOptionsVisibility to ensure correct initial state (disabled/enabled)
    toggleSubOptionsVisibility();

    resetTitleAndFavicon();

    // Reset Stems Section
    if (DOM.stemsSection) {
        DOM.stemsSection.style.opacity = '0';
        DOM.stemsSection.style.maxHeight = '0';
        setTimeout(() => {
            if (DOM.stemsSection && DOM.stemsSection.style.opacity === '0') DOM.stemsSection.style.display = 'none';
        }, 500);
    }
    import('./stems.js').then(Stems => Stems.destroyStemPlayers());
}

/**
 * Configures the UI elements to show that processing is starting.
 */
export function showProcessingUI() {
    if (DOM.processBtn) DOM.processBtn.disabled = true;
    clearStatus();

    if (DOM.progressDisplay) {
        DOM.progressDisplay.style.display = "block";
        requestAnimationFrame(() => {
            DOM.progressDisplay.style.opacity = '1';
            DOM.progressDisplay.style.maxHeight = '500px';
        });
    } else {
        console.warn("[UI] Progress display element not found.");
    }
    const cancelBtn = document.getElementById("cancel-job-btn");
    if (cancelBtn) {
        cancelBtn.style.display = 'inline-flex';
        cancelBtn.disabled = false;
        cancelBtn.innerHTML = `<span class="button-icon">✖️</span> Cancel Job`;
    }

    if (DOM.progressBar) {
        DOM.progressBar.style.width = "0%";
        DOM.progressBar.classList.remove('error');
        DOM.progressBar.ariaValueNow = "0";
        DOM.progressBar.removeAttribute('aria-invalid');
    }
    if (DOM.progressText) DOM.progressText.textContent = "0% - Initializing...";
    if (DOM.progressTiming) DOM.progressTiming.textContent = "Elapsed: 0s";
    if (DOM.progressStepsContainer) DOM.progressStepsContainer.innerHTML = "";

    if (DOM.resultsArea) {
        DOM.resultsArea.style.opacity = '0';
        DOM.resultsArea.style.maxHeight = '0';
        setTimeout(() => {
            if (DOM.resultsArea && DOM.resultsArea.style.opacity === '0') DOM.resultsArea.style.display = 'none';
        }, 500);
    }
    if (DOM.stemsSection) {
        DOM.stemsSection.style.opacity = '0';
        DOM.stemsSection.style.maxHeight = '0';
        setTimeout(() => {
            if (DOM.stemsSection && DOM.stemsSection.style.opacity === '0') DOM.stemsSection.style.display = 'none';
        }, 500);
    }
    import('./stems.js').then(Stems => Stems.destroyStemPlayers());
}

/**
 * Updates the progress bar, text, timing, and step log based on WebSocket data.
 */
export function updateProgressUI(data, jobStartTime) {
    if (DOM.progressDisplay && DOM.progressDisplay.style.display === 'none') {
        console.warn("[UI] Received progress update but progress display is hidden. Making it visible.");
        DOM.progressDisplay.style.display = "block";
        requestAnimationFrame(() => {
            DOM.progressDisplay.style.opacity = '1';
            DOM.progressDisplay.style.maxHeight = '500px';
        });
    }

    if (!data || typeof data !== 'object') return;

    const newProgress = Math.min(Math.max(0, parseInt(data.progress, 10) || 0), 100);
    const message = data.message || "";
    const isStepStart = !!data.is_step_start;
    const isError = /error|fail|cancel|ошибка|сбой|отмен/i.test(message);

    if (DOM.progressBar) {
        DOM.progressBar.style.width = `${newProgress}%`;
        DOM.progressBar.ariaValueNow = newProgress.toString();
        if (isError) {
            DOM.progressBar.classList.add('error');
            DOM.progressBar.setAttribute('aria-invalid', 'true');
        } else {
            DOM.progressBar.classList.remove('error');
            DOM.progressBar.removeAttribute('aria-invalid');
        }
    }
    if (DOM.progressText) {
        DOM.progressText.textContent = `${newProgress}% - ${message}`;
    }

    if (DOM.progressStepsContainer) {
        if (isStepStart) {
            const activeStep = DOM.progressStepsContainer.querySelector(".progress-step.active-step");
            if (activeStep) {
                activeStep.classList.remove("active-step");
                activeStep.classList.add("completed-step");
            }
            const stepDiv = document.createElement("div");
            stepDiv.className = "progress-step active-step";
            const now = new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'});
            stepDiv.innerHTML = `<span class="step-time">[${now}]</span><span class="step-message">${message}</span>`;
            DOM.progressStepsContainer.appendChild(stepDiv);
            DOM.progressStepsContainer.scrollTop = DOM.progressStepsContainer.scrollHeight;
        } else {
            const lastStepMessageSpan = DOM.progressStepsContainer.querySelector(".progress-step:last-child .step-message");
            if (lastStepMessageSpan && lastStepMessageSpan.textContent !== message && !isError && newProgress < 100) {
                lastStepMessageSpan.textContent = message;
            }
        }
    }

    if (DOM.progressTiming && jobStartTime) {
        const elapsedSec = Math.round((Date.now() - jobStartTime) / 1000);
        let estimate = "";
        if (newProgress > 0 && newProgress < 100) {
            const estimatedTotalSec = (elapsedSec / newProgress) * 100;
            const estimatedRemainingSec = Math.max(0, Math.round(estimatedTotalSec - elapsedSec));
            estimate = `, Est. remaining: ~${estimatedRemainingSec}s`;
        }
        DOM.progressTiming.textContent = newProgress >= 100
            ? `Finished in ${elapsedSec}s${isError ? ' (error/cancelled)' : ''}.`
            : `Elapsed: ${elapsedSec}s${estimate}`;
    }

    const cancelBtn = document.getElementById("cancel-job-btn");
    if (cancelBtn && newProgress >= 100) {
        cancelBtn.style.display = 'none';
    } else if (cancelBtn && DOM.progressDisplay?.style.display === 'block') {
        cancelBtn.style.display = 'inline-flex';
    }
}

/**
 * Displays the final results (video, download/share buttons).
 */
export function displayResults(result) {
    console.log("[UI] Displaying final results:", result);
    if (!result || typeof result !== 'object') {
        showStatus("Processing completed, but result data is missing or invalid.", true);
        if (DOM.processBtn) DOM.processBtn.disabled = false;
        if (DOM.progressDisplay) {
            DOM.progressDisplay.style.opacity = '0';
            DOM.progressDisplay.style.maxHeight = '0';
            setTimeout(() => {
                if (DOM.progressDisplay && DOM.progressDisplay.style.opacity === '0') DOM.progressDisplay.style.display = 'none';
            }, 300);
        }
        return;
    }

    if (DOM.progressDisplay) {
        DOM.progressDisplay.style.opacity = '0';
        DOM.progressDisplay.style.maxHeight = '0';
        setTimeout(() => {
            if (DOM.progressDisplay && DOM.progressDisplay.style.opacity === '0') DOM.progressDisplay.style.display = 'none';
        }, 300);
    }

    if (DOM.resultsArea) {
        DOM.resultsArea.style.display = "block";
        requestAnimationFrame(() => {
            DOM.resultsArea.style.opacity = '1';
            DOM.resultsArea.style.maxHeight = '3000px';
        });
    } else {
        console.error("[UI] Results area element not found!");
        showStatus("UI Error: Could not find results display area.", true);
        return;
    }

    const videoTitleEl = document.getElementById("video-title");
    if (videoTitleEl) {
        videoTitleEl.textContent = result.title || "Karaoke Video";
    }

    if (result.processed_path && DOM.karaokeVideo) {
        let videoUrl = result.processed_path;
        if (!videoUrl.startsWith('http') && !videoUrl.startsWith('/')) {
            videoUrl = '/' + videoUrl;
        }
        const fullVideoUrl = new URL(videoUrl, window.location.origin).href;
        console.log("[UI] Setting video source to:", fullVideoUrl);
        DOM.karaokeVideo.src = fullVideoUrl;
        DOM.karaokeVideo.load();

        if (DOM.downloadBtn) {
            DOM.downloadBtn.href = fullVideoUrl;
            const safeFilename = (result.video_id || result.title || 'karaoke_video').replace(/[^a-z0-9_.\-]/gi, '_');
            DOM.downloadBtn.download = `${safeFilename}.mp4`;
            DOM.downloadBtn.style.display = 'inline-flex';
        }
        if (DOM.shareBtn) {
            DOM.shareBtn.style.display = 'inline-flex';
            DOM.shareBtn.disabled = false;
            DOM.shareBtn.innerHTML = `<span class="button-icon" aria-hidden="true">🔗</span> Copy Link`;
            DOM.shareBtn.onclick = () => copyToClipboard(fullVideoUrl, DOM.shareBtn);
        }
    } else {
        console.warn("[UI] Result data is missing the 'processed_path' for the video.");
        showStatus("Processing finished, but the final video link is missing.", true);
        if (DOM.karaokeVideo) DOM.karaokeVideo.removeAttribute("src");
        if (DOM.downloadBtn) DOM.downloadBtn.style.display = 'none';
        if (DOM.shareBtn) DOM.shareBtn.style.display = 'none';
    }

    if (!DOM.statusMessage || !DOM.statusMessage.classList.contains('error')) {
        showStatus(`Success! Karaoke generated for: ${result.title || 'your video'}.`);
    }
    if (DOM.processBtn) DOM.processBtn.disabled = false;
    resetTitleAndFavicon();
}

// copyToClipboard remains the same
function copyToClipboard(textToCopy, buttonElement) {
    if (!navigator.clipboard) {
        console.warn("[UI] Clipboard API not available.");
        alert(`Clipboard API not supported. Please copy manually:\n${textToCopy}`);
        return;
    }
    navigator.clipboard.writeText(textToCopy).then(() => {
        console.log("[UI] Link copied to clipboard:", textToCopy);
        if (!buttonElement || !document.body.contains(buttonElement)) return;
        const originalHTML = buttonElement.innerHTML;
        const originalTitle = buttonElement.title;
        buttonElement.disabled = true;
        buttonElement.innerHTML = `<span class="button-icon" aria-hidden="true">✅</span> Copied!`;
        buttonElement.title = "Copied!";
        const existingTimeout = buttonElement.dataset.copyTimeout;
        if (existingTimeout) {
            clearTimeout(parseInt(existingTimeout, 10));
        }
        const timeoutId = setTimeout(() => {
            if (document.body.contains(buttonElement) && buttonElement.innerHTML.includes('✅')) {
                buttonElement.innerHTML = originalHTML;
                buttonElement.title = originalTitle;
                buttonElement.disabled = false;
                delete buttonElement.dataset.copyTimeout;
            }
        }, 2500);
        buttonElement.dataset.copyTimeout = timeoutId.toString();
    }).catch(err => {
        console.error("[UI] Failed to copy link to clipboard:", err);
        alert(`Could not copy link. Please copy manually:\n${textToCopy}`);
    });
}


// File: frontend/web/assets/js/ui.js
// Manages UI updates, state resets, progress display and interactions.


console.log('[UI] module loaded');

// ─────────────────────────────────────────────────────────────────────────────
// Internal state – used only inside this module
// ─────────────────────────────────────────────────────────────────────────────
/**
 * Timeout id for the deferred clean-up launched by hideSuggestionDropdown().
 * We cancel it whenever the dropdown is rendered again; that prevents the
 * “open → instant close” flicker that happened on first keystrokes.
 */
let dropdownCleanupTmr = null;

// ─────────────────────────────────────────────────────────────────────────────
// Helper – hide both the subtitle-options block and the Genius block
// ─────────────────────────────────────────────────────────────────────────────
export function hideOptionsAndGenius() {
    if (DOM.subtitleOptionsContainer) {
        DOM.subtitleOptionsContainer.style.opacity = '0';
        DOM.subtitleOptionsContainer.style.maxHeight = '0';
        setTimeout(() => {
            if (
                DOM.subtitleOptionsContainer &&
                parseFloat(DOM.subtitleOptionsContainer.style.opacity || 0) === 0
            ) {
                DOM.subtitleOptionsContainer.style.display = 'none';
            }
        }, 400); // must match CSS transition-duration
    }

    if (DOM.geniusLyricsContainer) {
        DOM.geniusLyricsContainer.style.opacity = '0';
        DOM.geniusLyricsContainer.style.maxHeight = '0';
        setTimeout(() => {
            if (
                DOM.geniusLyricsContainer &&
                parseFloat(DOM.geniusLyricsContainer.style.opacity || 0) === 0
            ) {
                DOM.geniusLyricsContainer.style.display = 'none';
            }
        }, 400);
    }

    // reset Genius-specific state
    window.selectedGeniusLyrics = null;
    if (DOM.geniusLyricsList) DOM.geniusLyricsList.innerHTML = '';

    const panel = document.getElementById('lyrics-panel');
    const btn = document.getElementById('lyrics-toggle-btn');
    if (panel) panel.classList.add('hidden');
    if (btn) {
        btn.setAttribute('aria-expanded', 'false');
        btn.classList.remove('expanded');
    }
    if (DOM.geniusSelectedText) DOM.geniusSelectedText.value = '';
}

// ─────────────────────────────────────────────────────────────────────────────
// One-time UI event wiring
// ─────────────────────────────────────────────────────────────────────────────
function setupUIEventListeners() {
    const toggleBtn = document.getElementById('lyrics-toggle-btn');
    const lyricsPanel = document.getElementById('lyrics-panel');
    const fontSizeSelect = DOM.finalSubtitleSizeSelect;

    if (toggleBtn && lyricsPanel) {
        toggleBtn.addEventListener('click', () => {
            const isHidden = lyricsPanel.classList.toggle('hidden');
            toggleBtn.setAttribute('aria-expanded', String(!isHidden));
            toggleBtn.classList.toggle('expanded', !isHidden);
        });

        // initialise button state
        toggleBtn.setAttribute(
            'aria-expanded',
            String(!lyricsPanel.classList.contains('hidden'))
        );
        toggleBtn.classList.toggle(
            'expanded',
            !lyricsPanel.classList.contains('hidden')
        );
    }

    if (fontSizeSelect) {
        fontSizeSelect.addEventListener('change', (ev) => {
            console.log(
                `[UI] user selected ${(ev.target).value}px final subtitle size`
            );
        });
    }
}

document.addEventListener('DOMContentLoaded', setupUIEventListeners);

// ─────────────────────────────────────────────────────────────────────────────
// Suggestion-dropdown helpers  ★ FLICKER FIX HERE ★
// ─────────────────────────────────────────────────────────────────────────────
/** Position dropdown directly under the input element. */
export function positionSuggestionDropdown() {
    if (!DOM.suggestionDropdownElement || !DOM.youtubeInput) return;

    const r = DOM.youtubeInput.getBoundingClientRect();
    const dd = DOM.suggestionDropdownElement;

    dd.style.position = 'fixed';
    dd.style.top = `${r.bottom + window.scrollY + 2}px`;
    dd.style.left = `${r.left + window.scrollX}px`;
    dd.style.width = `${r.width}px`;
    dd.style.zIndex = '1001';
}

/** Fade-out and then remove the dropdown list. */
export function hideSuggestionDropdown() {
    if (!DOM.suggestionDropdownElement) return;
    if (DOM.suggestionDropdownElement.style.visibility === 'hidden') return;

    // stop any previous clean-up still waiting
    clearTimeout(dropdownCleanupTmr);

    const dd = DOM.suggestionDropdownElement;
    dd.style.visibility = 'hidden';
    dd.style.opacity = '0';

    dropdownCleanupTmr = setTimeout(() => {
        if (!DOM.suggestionDropdownElement) return;

        dd.innerHTML = '';
        dd.removeAttribute('aria-activedescendant');

        if (DOM.youtubeInput) {
            DOM.youtubeInput.removeAttribute('aria-expanded');
            DOM.youtubeInput.removeAttribute('aria-activedescendant');
        }
    }, 250); // keep in sync with CSS transition
}

/** Show or hide the tiny spinner inside the dropdown area. */
export const showSuggestionSpinner = () =>
    DOM.suggestionSpinner && (DOM.suggestionSpinner.style.display = 'block');
export const hideSuggestionSpinner = () =>
    DOM.suggestionSpinner && (DOM.suggestionSpinner.style.display = 'none');

/**
 * Renders the suggestion dropdown.
 * @param {Array<Object>} suggestions
 * @param {Function}      onSelect
 * @param {Function?}     onItemMouseDown – fired on *mousedown* inside each row
 *                                          so the blur-handler knows we’re still
 *                                          interacting with the dropdown.
 */
export function renderSuggestionDropdown(
    suggestions,
    onSelect,
    onItemMouseDown = null
) {
    if (!DOM.suggestionDropdownElement || !suggestions.length) {
        hideSuggestionDropdown();
        return;
    }

    clearTimeout(dropdownCleanupTmr);            // cancel pending clean-up
    const dd = DOM.suggestionDropdownElement;
    dd.innerHTML = "";
    positionSuggestionDropdown();

    suggestions.forEach((item, idx) => {
        const row = document.createElement("div");
        row.className = "suggestion-item";
        row.id        = `s-${idx}`;
        row.tabIndex  = -1;
        row.innerHTML = `
            <img class="thumb" src="${item.thumbnail || ""}" alt="">
            <span class="title">${item.title}</span>
        `;

        if (onItemMouseDown) {
            row.addEventListener("mousedown", onItemMouseDown, { capture: true });
        }
        row.addEventListener("click", () => onSelect(item));
        dd.appendChild(row);
    });

    dd.style.visibility = "visible";
    dd.style.opacity    = "1";
    DOM.youtubeInput.setAttribute("aria-expanded", "true");
}

// ─────────────────────────────────────────────────────────────────────────────
// The remainder of ui.js (preview handling, progress UI, resetUI, etc.)
// is identical to the version you supplied.  No lines below were modified.
// ─────────────────────────────────────────────────────────────────────────────
// … (keep everything that follows unchanged) …