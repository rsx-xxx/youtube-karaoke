console.log("[App] Module loaded.")

import * as DOM from './dom.js'
import * as UI from './ui.js'
import * as API from './api.js'
import * as Suggestions from './suggestions.js'
import * as Stems from './stems.js'
import {connectWebSocket, closeWebSocket} from './websocket.js'
import * as Theme from './theme.js'
import {STEM_DEFINITIONS} from './config.js'

let currentJobId = null
let currentCancelController = null

document.addEventListener('DOMContentLoaded', () => {
    console.log("[App] DOMContentLoaded")
    Theme.initTheme()
    Suggestions.initSuggestions()
    setupCoreListeners()
    UI.resetUI()
    UI.toggleSubOptionsVisibility()
    console.log("[App] Init complete")
})

function setupCoreListeners() {
    if (DOM.processBtn) DOM.processBtn.addEventListener("click", handleProcessClick)
    const cancelBtn = document.getElementById('cancel-job-btn')
    if (cancelBtn) cancelBtn.addEventListener('click', handleCancelClick)
    if (DOM.generateSubtitlesCheckbox) DOM.generateSubtitlesCheckbox.addEventListener("change", UI.toggleSubOptionsVisibility)
    if (DOM.youtubeInput) DOM.youtubeInput.addEventListener('keydown', handleInputEnterKey)
    setupGlobalStemControls()
    setupVideoEventListeners()
    if (DOM.lockStems) DOM.lockStems.addEventListener('change', Stems.handleLockStemsChange)
    window.addEventListener("beforeunload", handlePageUnload)
}

function handleInputEnterKey(e) {
    if (e.key !== 'Enter' || e.isComposing || !DOM.youtubeInput.value.trim()) return
    e.preventDefault()
    const d = DOM.suggestionDropdownElement
    const f = d?.querySelector('.suggestion-item')
    if (d && d.style.visibility === 'visible' && f) {
        f.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true, view: window}))
        UI.hideSuggestionDropdown()
    } else if (DOM.processBtn && !DOM.processBtn.disabled) {
        handleProcessClick()
    }
}

function setupGlobalStemControls() {
    if (DOM.playAllStemsBtn) DOM.playAllStemsBtn.onclick = handlePlayPauseAll
    if (DOM.resetAllStemsBtn) DOM.resetAllStemsBtn.onclick = handleResetAll
    if (!DOM.globalSpeedSlider) return
    const disp = DOM.globalSpeedValue
    if (!disp) return
    DOM.globalSpeedSlider.addEventListener('input', e => {
        const s = parseFloat(e.target.value)
        disp.textContent = `${s.toFixed(2)}x`
        Stems.updateVideoPlaybackRate()
    })
    disp.textContent = `${parseFloat(DOM.globalSpeedSlider.value).toFixed(2)}x`
}

function setupVideoEventListeners() {
    if (!DOM.karaokeVideo) return
    DOM.karaokeVideo.addEventListener('play', () => {
        const t = DOM.karaokeVideo.currentTime
        Stems.getStemInstances().forEach((ws, i) => {
            if (!ws || !Stems.isStemReady(i) || ws.isPlaying()) return
            const d = ws.getDuration()
            if (d > 0) ws.seekTo(Math.max(0, Math.min(t / d, 1)))
            ws.play()
        })
        if (DOM.playAllStemsBtn) DOM.playAllStemsBtn.innerHTML = '<span class="button-icon">⏸️</span> Pause All'
    })
    DOM.karaokeVideo.addEventListener('pause', () => {
        Stems.getStemInstances().forEach((ws, i) => {
            if (ws && ws.isPlaying() && Stems.isStemReady(i)) ws.pause()
        })
        if (DOM.playAllStemsBtn) DOM.playAllStemsBtn.innerHTML = '<span class="button-icon">▶️</span> Play All'
    })
    let seekTimer
    DOM.karaokeVideo.addEventListener('seeking', () => clearTimeout(seekTimer))
    DOM.karaokeVideo.addEventListener('seeked', () => {
        clearTimeout(seekTimer)
        seekTimer = setTimeout(() => {
            const t = DOM.karaokeVideo.currentTime
            Stems.getStemInstances().forEach((ws, i) => {
                if (!ws || !Stems.isStemReady(i)) return
                const d = ws.getDuration()
                if (d <= 0) return
                const r = Math.max(0, Math.min(t / d, 1))
                if (Math.abs(ws.getCurrentTime() - t) > 0.2) ws.seekTo(r)
                if (!DOM.karaokeVideo.paused && !ws.isPlaying()) ws.play()
                else if (DOM.karaokeVideo.paused && ws.isPlaying()) ws.pause()
            })
        }, 200)
    })
    DOM.karaokeVideo.addEventListener('ended', () => {
        if (DOM.playAllStemsBtn) DOM.playAllStemsBtn.innerHTML = '<span class="button-icon">▶️</span> Play All'
    })
}

function handlePlayPauseAll() {
    const v = DOM.karaokeVideo
    if (!v || !DOM.playAllStemsBtn || DOM.playAllStemsBtn.disabled) return
    if (v.paused) v.play().catch(e => console.warn("Video play failed", e))
    else v.pause()
}

function handleResetAll() {
    if (!DOM.resetAllStemsBtn || DOM.resetAllStemsBtn.disabled) return
    if (DOM.karaokeVideo) {
        DOM.karaokeVideo.pause()
        DOM.karaokeVideo.currentTime = 0
    }
    Stems.getStemInstances().forEach(ws => {
        if (ws) {
            ws.seekTo(0);
            ws.pause()
        }
    })
    if (DOM.playAllStemsBtn) DOM.playAllStemsBtn.innerHTML = '<span class="button-icon">▶️</span> Play All'
}

function handlePageUnload() {
    if (currentJobId) API.cancelJobBeacon(currentJobId)
    closeWebSocket(1001, "Page unloading")
    Stems.destroyStemPlayers()
}

async function handleCancelClick() {
    const btn = document.getElementById('cancel-job-btn')
    if (!currentJobId || !btn || btn.disabled) return
    btn.disabled = true
    btn.innerHTML = `<span class="button-icon">⏳</span> Cancelling...`
    if (currentCancelController) currentCancelController.abort()
    currentCancelController = new AbortController()
    const signal = currentCancelController.signal
    try {
        await API.cancelJob(currentJobId, signal)
    } catch (e) {
        if (e.name !== 'AbortError') UI.showStatus(`Error cancelling job: ${e.message}`, true)
    } finally {
        currentCancelController = null
    }
}

// File: frontend/web/assets/js/app.js

// ... other imports and code ...

async function handleProcessClick() {
    if (!DOM.youtubeInput) return;
    const urlOrSearch = DOM.youtubeInput.value.trim();
    if (!urlOrSearch) {
        UI.showStatus("Please enter a YouTube link or search query.", true);
        DOM.youtubeInput.focus();
        return;
    }

    // ============== PATCHED LINE =======================================
    // If DOM.generateSubtitlesCheckbox is not found or .checked is undefined,
    // default to false (do not generate subtitles).
    // This is safer than defaulting to true.
    const generateSubs = DOM.generateSubtitlesCheckbox?.checked ?? false;
    // ===================================================================

    const language = DOM.languageSelect?.value || 'auto';
    const position = DOM.subtitlePositionSelect?.value || 'bottom';
    const size = parseInt(DOM.finalSubtitleSizeSelect?.value || '30', 10);
    const customLyrics = window.selectedGeniusLyrics || null;

    Suggestions.clearSuggestionTimeout();
    UI.hideSuggestionDropdown();

    const previewVisible = DOM.videoPreview && DOM.videoPreview.style.display !== 'none' && DOM.videoPreview.src;
    UI.resetUI(previewVisible); // Call resetUI

    // Ensure the checkbox state visually reflects the 'generateSubs' value that will be used.
    // This line re-affirms the checkbox state based on the (potentially safer defaulted) generateSubs.
    if (DOM.generateSubtitlesCheckbox) {
        DOM.generateSubtitlesCheckbox.checked = generateSubs;
    }

    UI.toggleSubOptionsVisibility(); // Update visibility of related options
    UI.showProcessingUI(); // Show spinners, progress bars etc.

    try {
        let pitchShifts = null;
        if (DOM.stemsContainer && DOM.stemsContainer.children.length > 0) {
            const vals = Stems.getStemPitches();
            const payload = {};
            let has = false;
            STEM_DEFINITIONS.forEach((def, idx) => {
                const p = (idx < vals.length && typeof vals[idx] === 'number') ? vals[idx] : 0;
                if (p !== 0) {
                    payload[def.name.toLowerCase()] = p;
                    has = true;
                }
            });
            if (has) pitchShifts = payload;
        }

        const jobId = await API.startProcessingJob(
            urlOrSearch,
            language,
            position,
            generateSubs, // Use the (potentially safer defaulted) generateSubs value
            customLyrics,
            pitchShifts,
            size
        );
        currentJobId = jobId;
        connectWebSocket(currentJobId);
    } catch (e) {
        console.error("[App] startProcessingJob failed", e);
        handleProcessingFailure(`Job start failed: ${e.message}`);
    }
}


function handleProcessingFailure(msg) {
    UI.showStatus(msg, true)
    if (DOM.processBtn) DOM.processBtn.disabled = false
    if (DOM.progressDisplay) {
        DOM.progressDisplay.style.opacity = '0'
        DOM.progressDisplay.style.maxHeight = '0'
        setTimeout(() => {
            if (DOM.progressDisplay && parseFloat(DOM.progressDisplay.style.opacity || 0) === 0) DOM.progressDisplay.style.display = 'none'
        }, 400)
    }
    const cancelBtn = document.getElementById('cancel-job-btn')
    if (cancelBtn) cancelBtn.style.display = 'none'
    currentJobId = null
    Stems.destroyStemPlayers()
    if (DOM.stemsSection) {
        DOM.stemsSection.style.display = 'none'
        DOM.stemsSection.style.opacity = '0'
        DOM.stemsSection.style.maxHeight = '0'
    }
    closeWebSocket(1011, "Processing start failed")
    UI.resetTitleAndFavicon()
}