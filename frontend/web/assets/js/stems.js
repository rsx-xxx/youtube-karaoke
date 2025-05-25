// File: frontend/web/assets/js/stems.js
// Handles creation, management, and interaction with WaveSurfer stem players.
// UPDATED: Added pitch reset button logic and volume zero styling trigger.
// UPDATED (v2): Implemented actual pitch shifting via playback rate.

console.log("[Stems] Module loaded.");

import * as DOM from './dom.js';
import { STEM_DEFINITIONS } from './config.js';

let stemWaveSurfers = [];
let stemReadyState = [];
let allStemsInitiallyReady = false;

// NOTE: WaveSurfer changes pitch by changing playback rate.
// We store the *desired* playback rate multiplier based on pitch shift.
let stemPlaybackRates = []; // Array to store target playback rate for each stem

/**
 * Converts semitones to a playback rate multiplier.
 * Rate = 2^(semitones / 12)
 * @param {number} semitones - Pitch shift in semitones.
 * @returns {number} Playback rate multiplier.
 */
function semitonesToPlaybackRate(semitones) {
    if (semitones === 0) return 1.0;
    // Clamp semitones to avoid extreme rates (e.g., -12 to +12)
    const clampedSemitones = Math.max(-12, Math.min(semitones, 12));
    return Math.pow(2, clampedSemitones / 12.0);
}

/**
 * Destroys existing WaveSurfer instances and clears the UI container.
 * Resets internal state arrays.
 */
export function destroyStemPlayers() {
    console.log(`[STEMS] Destroying ${stemWaveSurfers.length} stem players...`);
    stemWaveSurfers.forEach((ws, idx) => {
        try { if (ws) ws.destroy(); }
        catch (e) { console.warn(`[STEMS] Error destroying wavesurfer instance for index ${idx}:`, e); }
    });
    stemWaveSurfers = [];
    stemPlaybackRates = []; // Reset playback rates
    stemReadyState = [];
    allStemsInitiallyReady = false;

    if (DOM.stemsContainer) DOM.stemsContainer.innerHTML = "";
    if (DOM.playAllStemsBtn) DOM.playAllStemsBtn.innerHTML = '<span class="button-icon">▶️</span> Play All';
    enableGlobalControls(false);
    console.log("[STEMS] Player destruction and state reset complete.");
}

/** Checks if a specific stem at the given index is loaded and ready. */
export function isStemReady(index) {
    return stemReadyState[index] === true;
}

// --- Helper function to handle vertical slider dragging ---
// (handleVerticalSliderDrag remains the same as in your provided code)
// ... handleVerticalSliderDrag function definition ...
function handleVerticalSliderDrag(sliderElement, valueDisplayElement, min, max, step, updateCallback) {
    let isDragging = false;
    let sliderRect;
    const calculateValue = (clientY) => {
        if (!sliderRect) sliderRect = sliderElement.getBoundingClientRect();
        if (!sliderRect || sliderRect.height === 0) return parseFloat(sliderElement.value);
        const top = sliderRect.top; const height = sliderRect.height;
        let normalizedY = 1 - ((clientY - top) / height);
        normalizedY = Math.max(0, Math.min(normalizedY, 1));
        let value = min + normalizedY * (max - min);
        if (step) { const numSteps = Math.round((value - min) / step); value = min + numSteps * step; }
        value = Math.max(min, Math.min(value, max));
        if (sliderElement.classList.contains('stem-volume-slider') && value < 0.005) { value = 0; }
        return value;
    };
    const onPointerMove = (event) => {
        if (!isDragging) return; event.preventDefault();
        const value = calculateValue(event.clientY); sliderElement.value = value;
        if (updateCallback) { updateCallback(value, valueDisplayElement); }
        sliderElement.dispatchEvent(new Event('input', {bubbles: true}));
    };
    const onPointerUp = () => {
        if (!isDragging) return; isDragging = false;
        document.removeEventListener('pointermove', onPointerMove);
        document.removeEventListener('pointerup', onPointerUp);
        document.removeEventListener('pointercancel', onPointerUp);
        sliderElement.style.cursor = 'grab';
    };
    sliderElement.addEventListener('pointerdown', (event) => {
        if (sliderElement.disabled) return; isDragging = true;
        sliderRect = sliderElement.getBoundingClientRect(); sliderElement.style.cursor = 'grabbing';
        event.preventDefault(); event.stopPropagation();
        const initialValue = calculateValue(event.clientY); sliderElement.value = initialValue;
        if (updateCallback) { updateCallback(initialValue, valueDisplayElement); }
        sliderElement.dispatchEvent(new Event('input', {bubbles: true}));
        document.addEventListener('pointermove', onPointerMove, {passive: false});
        document.addEventListener('pointerup', onPointerUp);
        document.addEventListener('pointercancel', onPointerUp);
    });
    sliderElement.addEventListener('touchstart', (event) => { if (!sliderElement.disabled) { event.preventDefault(); } }, {passive: false});
    sliderElement.addEventListener('keydown', (event) => {
        if (sliderElement.disabled) return; let currentValue = parseFloat(sliderElement.value); let changed = false;
        if (event.key === 'ArrowUp' || event.key === 'ArrowRight') { currentValue += step || 0.1; changed = true; }
        else if (event.key === 'ArrowDown' || event.key === 'ArrowLeft') { currentValue -= step || 0.1; changed = true; }
        if (changed) {
            event.preventDefault(); currentValue = Math.max(min, Math.min(currentValue, max));
            if (step) { const numSteps = Math.round((currentValue - min) / step); currentValue = min + numSteps * step; currentValue = Math.max(min, Math.min(currentValue, max)); }
            if (sliderElement.classList.contains('stem-volume-slider') && currentValue < 0.005) { currentValue = 0; }
            sliderElement.value = currentValue;
            if (updateCallback) { updateCallback(currentValue, valueDisplayElement); }
            sliderElement.dispatchEvent(new Event('input', {bubbles: true}));
        }
    });
}

/**
 * Creates and initializes WaveSurfer players for all defined stems.
 * Fetches audio files based on the provided basePath.
 * @param {string} basePath - The base URL path where stem audio files reside.
 * @param {string} videoId - The ID of the video, potentially useful for unique IDs.
 */
export function createStemPlayers(basePath, videoId) {
    console.log(`[STEMS] createStemPlayers called with basePath='${basePath}', videoId='${videoId}'`);

    if (typeof WaveSurfer === 'undefined') {
        console.error("[STEMS] WaveSurfer library not loaded. Cannot create players.");
        if (DOM.stemsContainer) DOM.stemsContainer.innerHTML = '<p class="error-message">WaveSurfer library failed to load. Stems cannot be displayed.</p>';
        return;
    }

    destroyStemPlayers();

    if (!DOM.stemsContainer) {
        console.error("[STEMS] #stems-container element not found in the DOM.");
        return;
    }

    const safeBasePath = `/${basePath.replace(/^\/|\/$/g, '')}`;
    let expectedLoads = 0;

    stemWaveSurfers = new Array(STEM_DEFINITIONS.length).fill(null);
    stemPlaybackRates = new Array(STEM_DEFINITIONS.length).fill(1.0); // Initialize rates to 1.0
    stemReadyState = new Array(STEM_DEFINITIONS.length).fill(false);
    allStemsInitiallyReady = false;

    const isLockedInitially = DOM.lockStems?.checked ?? true;
    DOM.stemsContainer.innerHTML = "";

    STEM_DEFINITIONS.forEach((stemDef, index) => {
        let stemUrl;
        try { stemUrl = new URL(`${safeBasePath}/${stemDef.file}`, window.location.origin).href; }
        catch (e) {
            console.error(`[STEMS] Failed to construct valid URL for ${stemDef.name} from path "${safeBasePath}/${stemDef.file}":`, e);
            const errorDiv = document.createElement('div'); errorDiv.className = 'stem-player load-error';
            errorDiv.innerHTML = `<div class="stem-label-container"><span class="stem-icon">⚠️</span><div class="stem-label">${stemDef.name} (Invalid URL)</div></div>`;
            DOM.stemsContainer.appendChild(errorDiv);
            return;
        }
        expectedLoads++;

        // --- Create DOM elements (identical to your provided code) ---
        const stemWrapper = document.createElement("div"); stemWrapper.className = "stem-player"; stemWrapper.dataset.stemIndex = index;
        const labelContainer = document.createElement("div"); labelContainer.className = "stem-label-container";
        const iconSpan = document.createElement("span"); iconSpan.className = "stem-icon";
        const icons = {"Instrumental": "🎼", "Vocals": "🎤", "Drums": "🥁", "Bass": "🎸", "Other": "🎹"};
        iconSpan.textContent = icons[stemDef.name] || "🎵"; iconSpan.setAttribute("aria-hidden", "true");
        const label = document.createElement("div"); label.className = "stem-label"; label.textContent = `${stemDef.name} (Loading...)`;
        labelContainer.appendChild(iconSpan); labelContainer.appendChild(label);

        const waveAndControlsContainer = document.createElement("div"); waveAndControlsContainer.className = "stem-wave-controls-container";
        const waveformDiv = document.createElement("div"); waveformDiv.className = "waveform-container"; waveformDiv.id = `waveform-${index}`; waveformDiv.style.pointerEvents = isLockedInitially ? 'none' : 'auto';
        const controlsDiv = document.createElement("div"); controlsDiv.className = "stem-controls";

        // Volume
        const volumeControlGroup = document.createElement('div'); volumeControlGroup.className = 'stem-control-group vertical-group';
        const volumeLabel = document.createElement('label'); volumeLabel.htmlFor = `volume-${index}`; volumeLabel.textContent = 'Vol'; volumeLabel.className = 'control-label';
        const volumeSlider = document.createElement("input"); volumeSlider.type = "range"; volumeSlider.id = `volume-${index}`; volumeSlider.min = "0"; volumeSlider.max = "1"; volumeSlider.step = "0.01"; volumeSlider.title = `Volume for ${stemDef.name}`;
        volumeSlider.value = "1"; // Default volume to 1 (unmuted) now? Or keep 0? Let's try 1.
        volumeSlider.disabled = true; volumeSlider.className = "stem-range stem-volume-slider";
        volumeControlGroup.appendChild(volumeLabel); volumeControlGroup.appendChild(volumeSlider);

        // Pitch
        const pitchControlGroup = document.createElement('div'); pitchControlGroup.className = 'stem-control-group vertical-group';
        const pitchLabel = document.createElement('label'); pitchLabel.htmlFor = `pitch-${index}`; pitchLabel.textContent = 'Pitch'; pitchLabel.className = 'control-label';
        const pitchSlider = document.createElement("input"); pitchSlider.type = "range"; pitchSlider.id = `pitch-${index}`; pitchSlider.min = "-12"; pitchSlider.max = "12"; pitchSlider.step = "0.5"; pitchSlider.value = "0"; pitchSlider.title = `Pitch shift (semitones) for ${stemDef.name}`; pitchSlider.disabled = true; pitchSlider.className = "stem-range stem-pitch-slider";
        const pitchValueDisplay = document.createElement('span'); pitchValueDisplay.className = 'control-value pitch-value'; pitchValueDisplay.textContent = '0 st';
        const pitchResetBtn = document.createElement('button'); pitchResetBtn.className = 'pitch-reset-btn'; pitchResetBtn.textContent = '0'; pitchResetBtn.title = `Reset pitch for ${stemDef.name}`; pitchResetBtn.disabled = true; pitchResetBtn.type = 'button'; pitchResetBtn.dataset.targetSlider = `pitch-${index}`;
        pitchControlGroup.appendChild(pitchLabel); pitchControlGroup.appendChild(pitchSlider); pitchControlGroup.appendChild(pitchValueDisplay); pitchControlGroup.appendChild(pitchResetBtn);

        // Download
        const downloadLink = document.createElement("a"); downloadLink.href = stemUrl; downloadLink.download = stemDef.file; downloadLink.className = "stem-download-btn action-button"; downloadLink.title = `Download ${stemDef.name} stem`; downloadLink.innerHTML = `<span class="button-icon" aria-hidden="true">💾</span>`; downloadLink.style.display = 'none';

        controlsDiv.appendChild(volumeControlGroup); controlsDiv.appendChild(pitchControlGroup); controlsDiv.appendChild(downloadLink);
        waveAndControlsContainer.appendChild(waveformDiv); waveAndControlsContainer.appendChild(controlsDiv);
        stemWrapper.appendChild(labelContainer); stemWrapper.appendChild(waveAndControlsContainer);
        DOM.stemsContainer.appendChild(stemWrapper);

        // --- Initialize WaveSurfer ---
        try {
            const computedBodyStyle = getComputedStyle(document.body);
            const waveColor = computedBodyStyle.getPropertyValue(stemDef.colorVar).trim() || '#888888';
            const progressColor = computedBodyStyle.getPropertyValue(stemDef.progressVar).trim() || '#cccccc';
            const cursorColor = computedBodyStyle.getPropertyValue('--wavesurfer-cursor').trim() || '#8a2be2';

            const ws = WaveSurfer.create({
                container: waveformDiv, waveColor: waveColor, progressColor: progressColor, cursorColor: cursorColor,
                cursorWidth: 2, barWidth: 3, barGap: 1, height: 90,
                normalize: true, responsive: true, hideScrollbar: true,
                volume: parseFloat(volumeSlider.value), // Initial volume
                interact: false, // Let CSS handle pointer events
                // ** No built-in pitch property, use playbackRate **
            });
            stemWaveSurfers[index] = ws;
            stemPlaybackRates[index] = 1.0; // Initialize rate

            // --- WaveSurfer Event Handlers ---
            ws.on('ready', () => {
                // console.log(`[STEMS] WaveSurfer ready for: ${stemDef.name}`);
                label.textContent = stemDef.name;
                volumeSlider.disabled = false; pitchSlider.disabled = false; pitchResetBtn.disabled = false;
                downloadLink.style.display = 'inline-flex';
                stemReadyState[index] = true;
                ws.setVolume(parseFloat(volumeSlider.value)); // Apply initial volume
                ws.setPlaybackRate(stemPlaybackRates[index], false); // Apply initial rate (no pitch preservation needed here)
                volumeSlider.dispatchEvent(new Event('input', {bubbles: true})); // Trigger styling

                const allNowReady = stemReadyState.every(r => r === true);
                if (allNowReady && !allStemsInitiallyReady && stemReadyState.length === expectedLoads) {
                    allStemsInitiallyReady = true;
                    console.log("[STEMS] All expected stems loaded successfully.");
                    enableGlobalControls(true);
                    handleLockStemsChange(); // Apply initial lock state
                }
            });
            ws.on('loading', (percent) => { label.textContent = `${stemDef.name} (Loading ${percent}%)`; });
            ws.on('error', (err) => {
                console.error(`[STEMS] WaveSurfer error loading ${stemDef.name}:`, err);
                label.textContent = `${stemDef.name} (Load Error)`; stemWrapper.classList.add('load-error');
                volumeSlider.disabled = true; pitchSlider.disabled = true; pitchResetBtn.disabled = true;
                downloadLink.style.display = 'none'; stemReadyState[index] = false; waveformDiv.style.pointerEvents = 'none';
            });

            ws.load(stemUrl);

        } catch (err) {
            console.error(`[STEMS] Failed to initialize WaveSurfer for ${stemDef.name}:`, err);
            label.textContent = `${stemDef.name} (Init Error)`; stemWrapper.classList.add('load-error');
            volumeSlider.disabled = true; pitchSlider.disabled = true; pitchResetBtn.disabled = true;
            downloadLink.style.display = 'none'; stemReadyState[index] = false; waveformDiv.style.pointerEvents = 'none';
        }

        // --- Control Event Listeners ---

        // Volume (remains the same, using custom handler)
        handleVerticalSliderDrag(volumeSlider, null, 0, 1, 0.01,
            (newValue) => {
                const wsInstance = stemWaveSurfers[index];
                if (wsInstance && isStemReady(index)) { wsInstance.setVolume(newValue); }
            }
        );
        volumeSlider.addEventListener('input', (e) => { // For zero styling
            e.target.classList.toggle('at-zero', parseFloat(e.target.value) === 0);
        });

        // Pitch (use custom handler, update playback rate in callback)
        handleVerticalSliderDrag(pitchSlider, pitchValueDisplay, -12, 12, 0.5,
            (newValue, displayEl) => {
                const newRate = semitonesToPlaybackRate(newValue);
                stemPlaybackRates[index] = newRate;
                if (displayEl) displayEl.textContent = `${newValue >= 0 ? '+' : ''}${newValue.toFixed(1)} st`;
                pitchResetBtn.disabled = (newValue === 0);

                // Apply playback rate change to WaveSurfer instance
                const wsInstance = stemWaveSurfers[index];
                if (wsInstance && isStemReady(index)) {
                    // console.log(`[STEMS] Setting playback rate for ${stemDef.name} to ${newRate.toFixed(3)} (Semitones: ${newValue})`);
                    // The second arg `false` means *don't* preserve pitch (which is what we want to *change* pitch)
                    wsInstance.setPlaybackRate(newRate, false);
                }
            }
        );

        // Pitch Reset Button Listener
        pitchResetBtn.addEventListener('click', () => {
            // console.log(`[STEMS] Resetting pitch for index ${index}`);
            pitchSlider.value = 0;
            const newRate = 1.0;
            stemPlaybackRates[index] = newRate;
            pitchValueDisplay.textContent = '0 st';
            pitchResetBtn.disabled = true;
            const wsInstance = stemWaveSurfers[index];
            if (wsInstance && isStemReady(index)) {
                wsInstance.setPlaybackRate(newRate, false); // Reset rate
            }
        });

    }); // End forEach STEM_DEFINITIONS

    console.log(`[STEMS] Finished setting up ${expectedLoads} stem players.`);
}


// --- Playback Rate Update ---
// This now ONLY affects the main video, stems handle their own rate via pitch slider
export function updateVideoPlaybackRate() {
    if (!DOM.karaokeVideo || !DOM.globalSpeedSlider) return;
    const globalSpeed = parseFloat(DOM.globalSpeedSlider.value || "1.0");
    const clampedRate = Math.max(0.25, Math.min(globalSpeed, 4.0));
    DOM.karaokeVideo.playbackRate = clampedRate;
    if (DOM.globalSpeedValue) {
        DOM.globalSpeedValue.textContent = `${clampedRate.toFixed(2)}x`;
    }
    // console.log(`[STEMS] Video playback rate set to: ${clampedRate}`);
}

// --- Getters ---
export function getStemInstances() { return stemWaveSurfers; }

// getStemPitches now returns the *semitone values* from the sliders
export function getStemPitches() {
    const currentPitches = new Array(STEM_DEFINITIONS.length).fill(0);
    for (let i = 0; i < STEM_DEFINITIONS.length; i++) {
        const slider = document.getElementById(`pitch-${i}`);
        if (slider) {
            currentPitches[i] = parseFloat(slider.value);
        }
    }
    // This function is used by app.js to send data to backend.
    // The backend currently ONLY uses pitch_shifts['instrumental'].
    // So, even though we collect all pitches here, only the instrumental one
    // will be used by the current backend merger.py logic.
    return currentPitches;
}


export function areAnyStemsPlaying() { return stemWaveSurfers.some((ws, i) => ws && ws.isPlaying() && isStemReady(i)); }

// --- Controls Enabling ---
function enableGlobalControls(enable) {
    const controls = [DOM.playAllStemsBtn, DOM.stopAllStemsBtn, DOM.resetAllStemsBtn, DOM.globalSpeedSlider, DOM.lockStems];
    controls.forEach(control => { if (control) control.disabled = !enable; });
    // console.log(`[STEMS] Global stem controls ${enable ? 'enabled' : 'disabled'}.`);
}

/** Toggles the pointer events on waveform containers based on the lock checkbox. */
export function handleLockStemsChange() {
    if (!DOM.lockStems) return;
    const isLocked = DOM.lockStems.checked;
    // console.log(`[STEMS] Lock stems checkbox changed. Locked: ${isLocked}`);
    for (let i = 0; i < STEM_DEFINITIONS.length; i++) {
        const waveformDiv = document.getElementById(`waveform-${i}`);
        if (waveformDiv) waveformDiv.style.pointerEvents = isLocked ? 'none' : 'auto';
    }
}

// Initialize volume/pitch slider styling on load (might not be needed as they are dynamic)
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.stem-volume-slider').forEach(slider => {
        slider.classList.toggle('at-zero', parseFloat(slider.value) === 0);
    });
    document.querySelectorAll('.stem-pitch-slider').forEach(slider => {
        const resetButton = slider.parentElement?.querySelector('.pitch-reset-btn');
        if (resetButton) resetButton.disabled = (parseFloat(slider.value) === 0);
    });
});