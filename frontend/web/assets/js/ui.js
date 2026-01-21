// File: frontend/web/assets/js/ui.js
import * as DOM from './dom.js'
import { BASE_TITLE, DEFAULT_FAVICON } from './config.js'
import { setOriginalKey, setOriginalBpm, setTrackMetadata } from './stems.js'

console.log("[UI] Module loaded.")

export function updateInputWithSuggestion(item) {
    if (!item) return
    if (DOM.youtubeInput) DOM.youtubeInput.value = item.url || ""
    if (DOM.chosenVideoTitleDiv) DOM.chosenVideoTitleDiv.textContent = item.title ? `Selected: ${item.title}` : ""
    if (DOM.videoPreview) {
        if (item.thumbnail) {
            DOM.videoPreview.src = item.thumbnail
            DOM.videoPreview.alt = `Thumbnail for ${item.title}`
            DOM.videoPreview.style.display = "block"
            requestAnimationFrame(() => {
                DOM.videoPreview.style.opacity = '1'
                DOM.videoPreview.style.maxHeight = '90px'
            })
        } else {
            clearPreview(true)
        }
    }
    const lyricsPanel = document.getElementById("lyrics-panel")
    const toggleBtn = document.getElementById("lyrics-toggle-btn")
    const textArea = DOM.geniusSelectedText
    if (lyricsPanel) lyricsPanel.classList.add("hidden")
    if (toggleBtn) {
        toggleBtn.setAttribute("aria-expanded", "false")
        toggleBtn.classList.remove('expanded')
    }
    if (textArea) textArea.value = ""
    window.selectedGeniusLyrics = null
    if (DOM.geniusLyricsList) DOM.geniusLyricsList.innerHTML = ""
}

export function clearPreview(forceClear = false) {
    if (DOM.processBtn?.disabled && !forceClear) return
    if (DOM.chosenVideoTitleDiv) DOM.chosenVideoTitleDiv.textContent = ""
    if (DOM.videoPreview) {
        DOM.videoPreview.style.opacity = '0'
        DOM.videoPreview.style.maxHeight = '0'
        setTimeout(() => {
            if (DOM.videoPreview && parseFloat(DOM.videoPreview.style.opacity || 0) === 0) {
                DOM.videoPreview.style.display = "none"
                DOM.videoPreview.src = ""
                DOM.videoPreview.alt = ""
            }
        }, 300)
    }
}

export function resetTitleAndFavicon() {
    document.title = BASE_TITLE
    if (DOM.faviconElement) DOM.faviconElement.href = DEFAULT_FAVICON
}

export function toggleSubOptionsVisibility() {
    if (!DOM.generateSubtitlesCheckbox) return
    const enable = DOM.generateSubtitlesCheckbox.checked
    if (DOM.languageSelect) DOM.languageSelect.disabled = !enable
    if (DOM.subtitlePositionSelect) DOM.subtitlePositionSelect.disabled = !enable
    if (DOM.finalSubtitleSizeSelect) DOM.finalSubtitleSizeSelect.disabled = !enable
    const group = DOM.subtitleOptionsContainer?.querySelector(':scope > .options-group:not(#genius-lyrics-container)')
    if (group) {
        const controls = group.querySelectorAll('.option-item.lyrics-option')
        controls.forEach(i => {
            i.style.opacity = enable ? '1' : '0.5'
            i.style.pointerEvents = enable ? 'auto' : 'none'
        })
        const main = group.querySelector('.option-item.checkbox-item')
        if (main) {
            main.style.opacity = '1'
            main.style.pointerEvents = 'auto'
        }
    }
    if (!DOM.geniusLyricsContainer || !DOM.subtitleOptionsContainer) return
    const optsVisible = DOM.subtitleOptionsContainer.style.display !== 'none' && parseFloat(DOM.subtitleOptionsContainer.style.opacity || 0) > 0
    const show = enable && optsVisible
    if (show) {
        DOM.geniusLyricsContainer.style.display = 'flex'
        requestAnimationFrame(() => {
            DOM.geniusLyricsContainer.style.opacity = '1'
            DOM.geniusLyricsContainer.style.maxHeight = '700px'
        })
    } else hideGeniusSectionOnly()
}

function hideGeniusSectionOnly() {
    if (!DOM.geniusLyricsContainer) return
    DOM.geniusLyricsContainer.style.opacity = '0'
    DOM.geniusLyricsContainer.style.maxHeight = '0'
    setTimeout(() => {
        if (DOM.geniusLyricsContainer && parseFloat(DOM.geniusLyricsContainer.style.opacity || 0) === 0)
            DOM.geniusLyricsContainer.style.display = 'none'
    }, 400)
}

export function showStatus(message, isError = false) {
    if (DOM.statusMessage) {
        DOM.statusMessage.textContent = message
        DOM.statusMessage.className = isError ? 'error' : 'success'
        DOM.statusMessage.setAttribute('role', isError ? 'alert' : 'status')
        DOM.statusMessage.style.display = 'block'
        requestAnimationFrame(() => {
            DOM.statusMessage.style.opacity = '1'
            DOM.statusMessage.style.maxHeight = '100px'
        })
    } else alert(`${isError ? 'Error: ' : ''}${message}`)
}

export function clearStatus() {
    if (!DOM.statusMessage || DOM.statusMessage.style.display === 'none') return
    DOM.statusMessage.style.opacity = '0'
    DOM.statusMessage.style.maxHeight = '0'
    const clear = () => {
        if (!DOM.statusMessage) return
        DOM.statusMessage.textContent = ''
        DOM.statusMessage.className = ''
        DOM.statusMessage.removeAttribute('role')
        DOM.statusMessage.style.display = 'none'
        DOM.statusMessage.removeEventListener('transitionend', clear)
    }
    const style = getComputedStyle(DOM.statusMessage)
    if (style.transitionProperty !== 'none' && (style.transitionDuration !== '0s' || style.transitionDelay !== '0s'))
        DOM.statusMessage.addEventListener('transitionend', clear, { once: true })
    else setTimeout(clear, 0)
}

export function resetUI(keepPreviewAndTitle = false) {
    if (!keepPreviewAndTitle) {
        if (DOM.youtubeInput) DOM.youtubeInput.value = ""
        clearPreview(true)
    }
    clearStatus()
    if (DOM.progressDisplay) {
        DOM.progressDisplay.style.opacity = '0'
        DOM.progressDisplay.style.maxHeight = '0'
        setTimeout(() => {
            if (DOM.progressDisplay && parseFloat(DOM.progressDisplay.style.opacity || 0) === 0)
                DOM.progressDisplay.style.display = "none"
        }, 400)
    }
    if (DOM.progressBar) {
        DOM.progressBar.style.width = "0%"
        DOM.progressBar.classList.remove('error')
        DOM.progressBar.ariaValueNow = "0"
        DOM.progressBar.removeAttribute('aria-invalid')
    }
    if (DOM.progressText) DOM.progressText.textContent = ""
    if (DOM.progressTiming) DOM.progressTiming.textContent = ""
    if (DOM.progressStepsContainer) DOM.progressStepsContainer.innerHTML = ""
    const cancelBtn = document.getElementById("cancel-job-btn")
    if (cancelBtn) cancelBtn.style.display = 'none'
    if (DOM.resultsArea) {
        DOM.resultsArea.style.opacity = '0'
        DOM.resultsArea.style.maxHeight = '0'
        setTimeout(() => {
            if (DOM.resultsArea && parseFloat(DOM.resultsArea.style.opacity || 0) === 0)
                DOM.resultsArea.style.display = "none"
        }, 500)
    }
    if (DOM.karaokeVideo) {
        DOM.karaokeVideo.removeAttribute("src")
        try { DOM.karaokeVideo.load() } catch {}
    }
    const videoTitleEl = document.getElementById("video-title")
    if (videoTitleEl) videoTitleEl.textContent = "Karaoke Video"
    if (DOM.downloadBtn) {
        DOM.downloadBtn.style.display = "none"
        DOM.downloadBtn.href = "#"
    }
    if (DOM.shareBtn) {
        DOM.shareBtn.style.display = "none"
        DOM.shareBtn.onclick = null
        DOM.shareBtn.disabled = false
        DOM.shareBtn.innerHTML = `<span class="button-icon" aria-hidden="true">🔗</span> Copy Link`
    }
    if (DOM.processBtn) DOM.processBtn.disabled = false
    hideSuggestionDropdown()
    hideSuggestionSpinner()
    if (DOM.languageSelect) DOM.languageSelect.value = 'auto'
    if (DOM.subtitlePositionSelect) DOM.subtitlePositionSelect.value = 'bottom'
    if (DOM.finalSubtitleSizeSelect) DOM.finalSubtitleSizeSelect.value = '30'
    if (!keepPreviewAndTitle) resetTitleAndFavicon()
    if (DOM.stemsSection) {
        DOM.stemsSection.style.opacity = '0'
        DOM.stemsSection.style.maxHeight = '0'
        setTimeout(() => {
            if (DOM.stemsSection && parseFloat(DOM.stemsSection.style.opacity || 0) === 0)
                DOM.stemsSection.style.display = 'none'
        }, 500)
    }
    if (!keepPreviewAndTitle || (DOM.stemsSection && DOM.stemsSection.style.display === 'none'))
        import('./stems.js').then(S => S.destroyStemPlayers()).catch(err => console.error("Error destroying stems", err))

    // Reset BPM/Key display
    if (DOM.trackBpmEl) DOM.trackBpmEl.textContent = '--';
    if (DOM.trackKeyEl) {
        DOM.trackKeyEl.textContent = '--';
        DOM.trackKeyEl.dataset.originalKey = '';
    }
    if (DOM.trackKeyTransposedEl) DOM.trackKeyTransposedEl.textContent = '';

    // Reset lyrics sidebar
    if (DOM.resultsLayout) DOM.resultsLayout.dataset.lyricsExpanded = 'false';
    if (DOM.fullLyricsTextarea) {
        DOM.fullLyricsTextarea.value = '';
        DOM.fullLyricsTextarea.placeholder = 'Lyrics will appear here after processing...';
    }
}

export function showProcessingUI() {
    if (DOM.processBtn) DOM.processBtn.disabled = true
    clearStatus()
    if (DOM.progressDisplay) {
        DOM.progressDisplay.style.display = "block"
        requestAnimationFrame(() => {
            DOM.progressDisplay.style.opacity = '1'
            DOM.progressDisplay.style.maxHeight = '500px'
        })
    }
    const cancelBtn = document.getElementById("cancel-job-btn")
    if (cancelBtn) {
        cancelBtn.style.display = 'inline-flex'
        cancelBtn.disabled = false
        cancelBtn.innerHTML = `<span class="button-icon">✖️</span> Cancel Job`
    }
    if (DOM.progressBar) {
        DOM.progressBar.style.width = "0%"
        DOM.progressBar.classList.remove('error')
        DOM.progressBar.ariaValueNow = "0"
        DOM.progressBar.removeAttribute('aria-invalid')
    }
    if (DOM.progressText) DOM.progressText.textContent = "0% - Initializing..."
    if (DOM.progressTiming) DOM.progressTiming.textContent = "Elapsed: 0s"
    if (DOM.progressStepsContainer) DOM.progressStepsContainer.innerHTML = ""
    if (DOM.resultsArea) {
        DOM.resultsArea.style.opacity = '0'
        DOM.resultsArea.style.maxHeight = '0'
        setTimeout(() => {
            if (DOM.resultsArea && parseFloat(DOM.resultsArea.style.opacity || 0) === 0)
                DOM.resultsArea.style.display = 'none'
        }, 500)
    }
    if (DOM.stemsSection) {
        DOM.stemsSection.style.opacity = '0'
        DOM.stemsSection.style.maxHeight = '0'
        setTimeout(() => {
            if (DOM.stemsSection && parseFloat(DOM.stemsSection.style.opacity || 0) === 0)
                DOM.stemsSection.style.display = 'none'
        }, 500)
    }
    import('./stems.js').then(S => S.destroyStemPlayers()).catch(err => console.error("Error destroying stems", err))
}


export function updateProgressUI(data, jobStartTime) {
    if (DOM.progressDisplay && DOM.progressDisplay.style.display === 'none') {
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
    const isError = /error|fail|cancel|ошибка|сбой|отмен/i.test(message.toLowerCase());

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

            // Safe DOM construction (prevents XSS)
            const timeSpan = document.createElement("span");
            timeSpan.className = "step-time";
            timeSpan.textContent = `[${now}]`;

            const messageSpan = document.createElement("span");
            messageSpan.className = "step-message";
            messageSpan.textContent = message;

            stepDiv.appendChild(timeSpan);
            stepDiv.appendChild(messageSpan);
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
        if (newProgress > 0 && newProgress < 100 && !isError) {
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

export function displayResults(result) {
    console.log("[UI] Displaying final results:", result);
    if (!result || typeof result !== 'object') {
        showStatus("Processing completed, but result data is missing or invalid.", true);
        if (DOM.processBtn) DOM.processBtn.disabled = false;
        if (DOM.progressDisplay) {
            DOM.progressDisplay.style.opacity = '0';
            DOM.progressDisplay.style.maxHeight = '0';
            setTimeout(() => { if (DOM.progressDisplay && parseFloat(DOM.progressDisplay.style.opacity || 0) === 0) DOM.progressDisplay.style.display = 'none'; }, 300);
        }
        return;
    }

    if (DOM.progressDisplay) {
        DOM.progressDisplay.style.opacity = '0';
        DOM.progressDisplay.style.maxHeight = '0';
        setTimeout(() => {
            if (DOM.progressDisplay && parseFloat(DOM.progressDisplay.style.opacity || 0) === 0) DOM.progressDisplay.style.display = 'none';
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

    // Set track metadata for stem download filenames
    setTrackMetadata(result.title || null, result.artist || result.uploader || null);

    if (result.processed_path && DOM.karaokeVideo) {
        let videoUrl = result.processed_path;
        if (!videoUrl.startsWith('http') && !videoUrl.startsWith('/')) {
            videoUrl = '/' + videoUrl;
        }
        const fullVideoUrl = new URL(videoUrl, window.location.origin).href;
        console.log("[UI] Setting video source to:", fullVideoUrl);

        DOM.karaokeVideo.src = fullVideoUrl;
        DOM.karaokeVideo.muted = true; // Mute video by default - stems provide audio
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

    // Display BPM and key if available
    if (DOM.trackBpmEl) {
        DOM.trackBpmEl.textContent = result.bpm ? result.bpm.toFixed(1) : '--';
    }
    // Set the original BPM in stems module for speed-adjusted display
    setOriginalBpm(result.bpm || null);

    if (DOM.trackKeyEl) {
        DOM.trackKeyEl.textContent = result.key || '--';
        DOM.trackKeyEl.dataset.originalKey = result.key || '';
        // Set the original key in stems module for transposition display
        setOriginalKey(result.key || null);
    }
    // Clear transposed key display (will be updated when pitch changes)
    if (DOM.trackKeyTransposedEl) {
        DOM.trackKeyTransposedEl.textContent = '';
    }

    if (!DOM.statusMessage || !DOM.statusMessage.classList.contains('error')) {
         showStatus(`Success! Karaoke generated for: ${result.title || 'your video'}.`);
    }
    if (DOM.processBtn) DOM.processBtn.disabled = false;
    resetTitleAndFavicon();
}

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
        }, 400);
    }
    hideGeniusSectionOnly();

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
            const target = ev.target;
            if (target instanceof HTMLSelectElement) {
                console.log(
                    `[UI] User selected ${target.value}px final subtitle size (display only, actual value sent on process).`
                );
            }
        });
    }
}
document.addEventListener('DOMContentLoaded', setupUIEventListeners);

let dropdownCleanupTmr = null;

export function positionSuggestionDropdown() {
    if (!DOM.suggestionDropdownElement || !DOM.youtubeInput) return;

    const inputRect = DOM.youtubeInput.getBoundingClientRect();
    const dropdown = DOM.suggestionDropdownElement;

    dropdown.style.position = 'fixed';
    dropdown.style.top = `${inputRect.bottom + 2}px`;
    dropdown.style.left = `${inputRect.left}px`;
    dropdown.style.width = `${inputRect.width}px`;
    dropdown.style.zIndex = '1001';
}

export function hideSuggestionDropdown() {
    if (!DOM.suggestionDropdownElement) return;

    if (DOM.suggestionDropdownElement.style.visibility === 'hidden' &&
        parseFloat(DOM.suggestionDropdownElement.style.opacity || '0') === 0) {
        return;
    }

    clearTimeout(dropdownCleanupTmr);

    const dropdown = DOM.suggestionDropdownElement;
    dropdown.style.opacity = '0';

    const style = getComputedStyle(dropdown);
    const transitionDuration = parseFloat(style.transitionDuration) * 1000;

    dropdownCleanupTmr = setTimeout(() => {
        if (!DOM.suggestionDropdownElement) return;
        if (parseFloat(dropdown.style.opacity || '0') === 0) {
            dropdown.style.visibility = 'hidden';
            dropdown.innerHTML = '';
            if (DOM.youtubeInput) {
                DOM.youtubeInput.removeAttribute('aria-expanded');
                DOM.youtubeInput.removeAttribute('aria-activedescendant');
            }
            dropdown.removeAttribute('aria-activedescendant');
        }
    }, transitionDuration || 0);
}

export const showSuggestionSpinner = () =>
    DOM.suggestionSpinner && (DOM.suggestionSpinner.style.display = 'block');
export const hideSuggestionSpinner = () =>
    DOM.suggestionSpinner && (DOM.suggestionSpinner.style.display = 'none');

export function renderSuggestionDropdown(
    suggestions,
    onSelect,
    onItemMouseDown = null
) {
    if (!DOM.suggestionDropdownElement || !suggestions || !suggestions.length) {
        hideSuggestionDropdown();
        return;
    }

    clearTimeout(dropdownCleanupTmr);

    const dropdown = DOM.suggestionDropdownElement;
    dropdown.innerHTML = "";
    positionSuggestionDropdown();

    suggestions.forEach((item, index) => {
        const row = document.createElement("div");
        row.className = "suggestion-item";
        row.id = `suggestion-item-${index}`;
        row.tabIndex = -1;
        row.setAttribute('role', 'option');

        // Safe DOM construction (prevents XSS)
        const img = document.createElement("img");
        img.className = "suggestion-thumbnail";
        img.alt = "";
        // Validate thumbnail URL to prevent javascript: protocol attacks
        const thumbnailSrc = item.thumbnail || '';
        if (thumbnailSrc && (thumbnailSrc.startsWith('http://') || thumbnailSrc.startsWith('https://') || thumbnailSrc.startsWith('data:'))) {
            img.src = thumbnailSrc;
        } else {
            img.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
        }

        const titleSpan = document.createElement("span");
        titleSpan.className = "suggestion-title";
        titleSpan.textContent = item.title || 'Unknown Title';

        row.appendChild(img);
        row.appendChild(titleSpan);

        if (onItemMouseDown) {
            row.addEventListener("mousedown", onItemMouseDown, { capture: true });
        }
        row.addEventListener("click", () => onSelect(item));

        dropdown.appendChild(row);
    });

    dropdown.style.visibility = "visible";
    requestAnimationFrame(() => {
        dropdown.style.opacity = "1";
    });

    if (DOM.youtubeInput) {
        DOM.youtubeInput.setAttribute("aria-expanded", "true");
    }
}