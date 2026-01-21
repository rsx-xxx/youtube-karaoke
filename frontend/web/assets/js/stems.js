// File: frontend/web/assets/js/stems.js
// Handles creation, management, and interaction with WaveSurfer stem players.
// UPDATED: Removed individual pitch sliders - only global pitch/speed controls
// UPDATED: Added proper download filenames with track info, BPM, key
// UPDATED: Integrated Web Audio API pitch shifter for true pitch shifting

console.log("[Stems] Module loaded.");

import * as DOM from './dom.js';
import { STEM_DEFINITIONS } from './config.js';
import * as PitchShifter from './pitch-shifter.js';

let stemWaveSurfers = [];
let stemReadyState = [];
let allStemsInitiallyReady = false;

// Global pitch state (semitones) - affects all stems
let globalPitchSemitones = 0;

// Global speed state - affects all stems and video
let globalSpeedRate = 1.0;

// Original track key and BPM (set by UI when result comes in)
let originalTrackKey = null;
let originalBpm = null;

// Track metadata for download filenames
let currentTrackTitle = null;
let currentTrackArtist = null;

// Musical key names for transposition
const KEY_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

/**
 * Sets track metadata for download filenames
 */
export function setTrackMetadata(title, artist) {
    currentTrackTitle = title;
    currentTrackArtist = artist;
    updateAllDownloadLinks();
}

/**
 * Generates a download filename for a stem
 * Format: Artist - Title (StemType) [Key | BPM] (+pitch st) (speed x).wav
 */
function generateStemFilename(stemName) {
    const parts = [];

    // Artist and title
    if (currentTrackArtist) {
        parts.push(sanitizeFilename(currentTrackArtist));
    }
    if (currentTrackTitle) {
        parts.push(sanitizeFilename(currentTrackTitle));
    }

    // Build base filename: "Artist - Title"
    let filename = parts.join(' - ');

    // Add stem type in parentheses: "(Vocals)"
    filename += ` (${stemName})`;

    // Key and BPM in square brackets (not for Drums)
    const infoParts = [];
    if (originalTrackKey && stemName !== 'Drums') {
        let displayKey = originalTrackKey;
        if (globalPitchSemitones !== 0) {
            const transposed = transposeKey(originalTrackKey, globalPitchSemitones);
            if (transposed) displayKey = transposed;
        }
        infoParts.push(displayKey);
    }
    if (originalBpm && stemName !== 'Drums') {
        const adjustedBpm = Math.round(originalBpm * globalSpeedRate);
        infoParts.push(`${adjustedBpm}bpm`);
    }

    if (infoParts.length > 0) {
        filename += ` [${infoParts.join(' | ')}]`;
    }

    // Add pitch/speed modifiers if changed
    const modifiers = [];
    if (globalPitchSemitones !== 0) {
        const sign = globalPitchSemitones > 0 ? '+' : '';
        modifiers.push(`(${sign}${globalPitchSemitones}st)`);
    }
    if (Math.abs(globalSpeedRate - 1.0) > 0.01) {
        modifiers.push(`(${globalSpeedRate.toFixed(2)}x)`);
    }
    if (modifiers.length > 0) {
        filename += ` ${modifiers.join(' ')}`;
    }

    return filename + '.wav';
}

/**
 * Sanitizes a string for use in a filename
 */
function sanitizeFilename(str) {
    if (!str) return '';
    return str
        .replace(/[<>:"/\\|?*]/g, '')  // Remove invalid characters
        .replace(/\s+/g, ' ')           // Normalize whitespace
        .trim()
        .substring(0, 100);             // Limit length
}

/**
 * Updates all stem download links with current settings
 */
function updateAllDownloadLinks() {
    STEM_DEFINITIONS.forEach((stemDef, index) => {
        const downloadLink = document.querySelector(`.stem-player[data-stem-index="${index}"] .stem-download-btn`);
        if (downloadLink) {
            downloadLink.download = generateStemFilename(stemDef.name);
        }
    });
}

/**
 * Transposes a musical key by a number of semitones.
 */
export function transposeKey(original, semitones) {
    if (!original || semitones === 0) return null;

    const isMinor = original.endsWith('m');
    const root = isMinor ? original.slice(0, -1) : original;
    const idx = KEY_NAMES.indexOf(root);

    if (idx === -1) {
        console.warn(`[Stems] Unknown key root: ${root}`);
        return null;
    }

    const newIdx = (idx + semitones + 12) % 12;
    return `${KEY_NAMES[newIdx]}${isMinor ? 'm' : ''}`;
}

/**
 * Sets the original track key (called when results are displayed).
 */
export function setOriginalKey(key) {
    originalTrackKey = key;
    updateKeyDisplay();
}

/**
 * Sets the original BPM (called when results are displayed).
 */
export function setOriginalBpm(bpm) {
    originalBpm = bpm;
    updateBpmDisplay();
}

/**
 * Updates the key display to show transposed key if pitch is shifted.
 */
function updateKeyDisplay() {
    if (!DOM.trackKeyTransposedEl) return;

    if (globalPitchSemitones !== 0 && originalTrackKey) {
        const transposed = transposeKey(originalTrackKey, globalPitchSemitones);
        if (transposed) {
            DOM.trackKeyTransposedEl.textContent = ` → ${transposed}`;
        } else {
            DOM.trackKeyTransposedEl.textContent = '';
        }
    } else {
        DOM.trackKeyTransposedEl.textContent = '';
    }
}

/**
 * Updates the BPM display based on current speed.
 */
function updateBpmDisplay() {
    if (!DOM.trackBpmEl || !originalBpm) return;

    const adjustedBpm = originalBpm * globalSpeedRate;
    DOM.trackBpmEl.textContent = adjustedBpm.toFixed(1);
}

/**
 * Updates global pitch for all stems.
 * Uses Web Audio API PitchShifter for true pitch shifting without speed change.
 * Falls back to playback rate change if PitchShifter is not available.
 */
export function updateGlobalPitch(semitones) {
    globalPitchSemitones = semitones;

    // Try to use true pitch shifting via PitchShifter module
    if (PitchShifter.hasTruePitchShift()) {
        PitchShifter.setGlobalPitch(semitones);
        // Speed remains unchanged - only update playback rate for speed, not pitch
        stemWaveSurfers.forEach((ws, index) => {
            if (ws && isStemReady(index)) {
                ws.setPlaybackRate(globalSpeedRate, true); // preservesPitch = true
            }
        });
    } else {
        // Fallback: combined rate (pitch affects speed)
        const pitchRate = Math.pow(2, semitones / 12.0);
        const combinedRate = globalSpeedRate * pitchRate;

        stemWaveSurfers.forEach((ws, index) => {
            if (ws && isStemReady(index)) {
                ws.setPlaybackRate(combinedRate, false);
            }
        });

        if (DOM.karaokeVideo) {
            DOM.karaokeVideo.playbackRate = combinedRate;
        }
    }

    // Update global pitch display
    if (DOM.globalPitchValue) {
        const sign = semitones >= 0 ? '+' : '';
        DOM.globalPitchValue.textContent = `${sign}${semitones} st`;
    }

    // Update reset button state
    if (DOM.resetPitchBtn) {
        DOM.resetPitchBtn.disabled = (semitones === 0);
    }

    // Update key display
    updateKeyDisplay();

    // Update download links with new pitch value
    updateAllDownloadLinks();

    console.log(`[Stems] Global pitch set to ${semitones} semitones`);
}

/**
 * Updates global speed for all stems and video.
 */
export function updateGlobalSpeed(speed) {
    globalSpeedRate = speed;

    // Update pitch shifter speed if available
    if (PitchShifter.hasTruePitchShift()) {
        PitchShifter.setGlobalSpeed(speed);
        // Use playbackRate with preservesPitch for speed-only change
        stemWaveSurfers.forEach((ws, index) => {
            if (ws && isStemReady(index)) {
                ws.setPlaybackRate(speed, true); // preservesPitch = true
            }
        });
    } else {
        // Fallback: combined rate
        const pitchRate = Math.pow(2, globalPitchSemitones / 12.0);
        const combinedRate = globalSpeedRate * pitchRate;

        stemWaveSurfers.forEach((ws, index) => {
            if (ws && isStemReady(index)) {
                ws.setPlaybackRate(combinedRate, false);
            }
        });
    }

    // Update video playback rate (video doesn't use pitch shifting)
    if (DOM.karaokeVideo) {
        DOM.karaokeVideo.playbackRate = speed;
    }

    // Update speed display
    if (DOM.globalSpeedValue) {
        DOM.globalSpeedValue.textContent = `${speed.toFixed(2)}x`;
    }

    // Update BPM display
    updateBpmDisplay();

    // Update download links with new speed value
    updateAllDownloadLinks();

    console.log(`[Stems] Global speed set to ${speed.toFixed(2)}x`);
}

/**
 * Resets global pitch to 0.
 */
export function resetGlobalPitch() {
    if (DOM.globalPitchSlider) {
        DOM.globalPitchSlider.value = 0;
    }
    updateGlobalPitch(0);
}

/**
 * Gets the current global pitch value in semitones.
 */
export function getGlobalPitch() {
    return globalPitchSemitones;
}

/**
 * Gets the current global speed value.
 */
export function getGlobalSpeed() {
    return globalSpeedRate;
}

/**
 * Destroys existing WaveSurfer instances and clears the UI container.
 */
export function destroyStemPlayers() {
    console.log(`[STEMS] Destroying ${stemWaveSurfers.length} stem players...`);

    // Destroy pitch shifters first
    PitchShifter.destroyAllPitchShifters();

    stemWaveSurfers.forEach((ws, idx) => {
        try { if (ws) ws.destroy(); }
        catch (e) { console.warn(`[STEMS] Error destroying wavesurfer instance for index ${idx}:`, e); }
    });
    stemWaveSurfers = [];
    stemReadyState = [];
    allStemsInitiallyReady = false;

    // Reset global states
    globalPitchSemitones = 0;
    globalSpeedRate = 1.0;
    originalTrackKey = null;
    originalBpm = null;
    currentTrackTitle = null;
    currentTrackArtist = null;

    if (DOM.globalPitchSlider) DOM.globalPitchSlider.value = 0;
    if (DOM.globalPitchValue) DOM.globalPitchValue.textContent = '0 st';
    if (DOM.globalSpeedSlider) DOM.globalSpeedSlider.value = 1.0;
    if (DOM.globalSpeedValue) DOM.globalSpeedValue.textContent = '1.00x';
    if (DOM.trackKeyTransposedEl) DOM.trackKeyTransposedEl.textContent = '';

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
 * Individual pitch sliders have been REMOVED - only global pitch control.
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

        // --- Create DOM elements ---
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

        // Volume - Instrumental muted by default, others at full volume
        const volumeControlGroup = document.createElement('div'); volumeControlGroup.className = 'stem-control-group vertical-group';
        const volumeLabel = document.createElement('label'); volumeLabel.htmlFor = `volume-${index}`; volumeLabel.textContent = 'Vol'; volumeLabel.className = 'control-label';
        const volumeSlider = document.createElement("input"); volumeSlider.type = "range"; volumeSlider.id = `volume-${index}`; volumeSlider.min = "0"; volumeSlider.max = "1"; volumeSlider.step = "0.01"; volumeSlider.title = `Volume for ${stemDef.name}`;
        // Mute Instrumental by default (index 0), full volume for others
        volumeSlider.value = (stemDef.name === "Instrumental") ? "0" : "1";
        volumeSlider.disabled = true; volumeSlider.className = "stem-range stem-volume-slider";
        volumeControlGroup.appendChild(volumeLabel); volumeControlGroup.appendChild(volumeSlider);

        // NO individual pitch slider - removed per user request

        // Download - filename will be updated when track metadata is available
        const downloadLink = document.createElement("a");
        downloadLink.href = stemUrl;
        downloadLink.download = generateStemFilename(stemDef.name);
        downloadLink.className = "stem-download-btn action-button";
        downloadLink.title = `Download ${stemDef.name} stem`;
        downloadLink.innerHTML = `<span class="button-icon" aria-hidden="true">💾</span>`;
        downloadLink.style.display = 'none';

        controlsDiv.appendChild(volumeControlGroup);
        // Removed: controlsDiv.appendChild(pitchControlGroup);
        controlsDiv.appendChild(downloadLink);

        waveAndControlsContainer.appendChild(waveformDiv); waveAndControlsContainer.appendChild(controlsDiv);
        stemWrapper.appendChild(labelContainer); stemWrapper.appendChild(waveAndControlsContainer);
        DOM.stemsContainer.appendChild(stemWrapper);

        // --- Initialize WaveSurfer ---
        try {
            const computedBodyStyle = getComputedStyle(document.body);
            const waveColor = computedBodyStyle.getPropertyValue(stemDef.colorVar).trim() || '#888888';
            const progressColor = computedBodyStyle.getPropertyValue(stemDef.progressVar).trim() || '#cccccc';
            const cursorColor = computedBodyStyle.getPropertyValue('--wavesurfer-cursor').trim() || '#8a2be2';

            // Create our own audio element for pitch shifting control
            const audioElement = new Audio();
            audioElement.crossOrigin = 'anonymous';
            audioElement.preload = 'auto';
            audioElement.src = stemUrl;

            const ws = WaveSurfer.create({
                container: waveformDiv,
                waveColor: waveColor,
                progressColor: progressColor,
                cursorColor: cursorColor,
                cursorWidth: 2,
                barWidth: 3,
                barGap: 1,
                height: 90,
                normalize: true,
                responsive: true,
                hideScrollbar: true,
                interact: false,
                media: audioElement, // Use our audio element
            });
            stemWaveSurfers[index] = ws;

            // Store audio element reference for pitch shifter
            ws._audioElement = audioElement;

            // --- WaveSurfer Event Handlers ---
            ws.on('ready', () => {
                label.textContent = stemDef.name;
                volumeSlider.disabled = false;
                downloadLink.style.display = 'inline-flex';
                stemReadyState[index] = true;

                // Connect pitch shifter to our audio element
                const stemId = `stem-${index}`;
                const mediaEl = ws._audioElement || audioElement;

                if (PitchShifter.isSoundTouchAvailable() && mediaEl) {
                    // Resume audio context first (needed after user gesture)
                    PitchShifter.resumeAudioContext().then(() => {
                        const shifter = PitchShifter.createPitchShifterForElement(stemId, mediaEl);
                        if (shifter) {
                            // Set initial volume via pitch shifter gain
                            const initialVolume = parseFloat(volumeSlider.value);
                            PitchShifter.setVolume(stemId, initialVolume);
                            console.log(`[STEMS] Connected pitch shifter for ${stemDef.name}`);
                        } else {
                            // Fallback to WaveSurfer volume if shifter creation failed
                            ws.setVolume(parseFloat(volumeSlider.value));
                        }
                    }).catch(e => {
                        console.warn(`[STEMS] AudioContext resume failed for ${stemDef.name}:`, e);
                        ws.setVolume(parseFloat(volumeSlider.value));
                    });
                } else {
                    // No pitch shifting available - use WaveSurfer's volume
                    ws.setVolume(parseFloat(volumeSlider.value));
                }

                // Apply current global speed
                ws.setPlaybackRate(globalSpeedRate, true);

                volumeSlider.dispatchEvent(new Event('input', {bubbles: true}));

                const allNowReady = stemReadyState.every(r => r === true);
                if (allNowReady && !allStemsInitiallyReady && stemReadyState.length === expectedLoads) {
                    allStemsInitiallyReady = true;
                    console.log("[STEMS] All expected stems loaded successfully.");
                    enableGlobalControls(true);
                    handleLockStemsChange();
                }
            });
            ws.on('loading', (percent) => { label.textContent = `${stemDef.name} (Loading ${percent}%)`; });
            ws.on('error', (err) => {
                console.error(`[STEMS] WaveSurfer error loading ${stemDef.name}:`, err);
                label.textContent = `${stemDef.name} (Load Error)`; stemWrapper.classList.add('load-error');
                volumeSlider.disabled = true;
                downloadLink.style.display = 'none'; stemReadyState[index] = false; waveformDiv.style.pointerEvents = 'none';
            });

            // Don't call ws.load() - the media element already has the source

        } catch (err) {
            console.error(`[STEMS] Failed to initialize WaveSurfer for ${stemDef.name}:`, err);
            label.textContent = `${stemDef.name} (Init Error)`; stemWrapper.classList.add('load-error');
            volumeSlider.disabled = true;
            downloadLink.style.display = 'none'; stemReadyState[index] = false; waveformDiv.style.pointerEvents = 'none';
        }

        // --- Volume Control Event Listener ---
        handleVerticalSliderDrag(volumeSlider, null, 0, 1, 0.01,
            (newValue) => {
                const stemId = `stem-${index}`;
                // Use pitch shifter volume if connected, otherwise WaveSurfer
                if (PitchShifter.hasTruePitchShift()) {
                    PitchShifter.setVolume(stemId, newValue);
                } else {
                    const wsInstance = stemWaveSurfers[index];
                    if (wsInstance && isStemReady(index)) { wsInstance.setVolume(newValue); }
                }
            }
        );
        volumeSlider.addEventListener('input', (e) => {
            e.target.classList.toggle('at-zero', parseFloat(e.target.value) === 0);
        });

    }); // End forEach STEM_DEFINITIONS

    console.log(`[STEMS] Finished setting up ${expectedLoads} stem players.`);
}


// --- Playback Rate Update (called from app.js on speed slider change) ---
export function updateVideoPlaybackRate() {
    if (!DOM.globalSpeedSlider) return;
    const speed = parseFloat(DOM.globalSpeedSlider.value || "1.0");
    updateGlobalSpeed(speed);
}

// --- Getters ---
export function getStemInstances() { return stemWaveSurfers; }

export function areAnyStemsPlaying() { return stemWaveSurfers.some((ws, i) => ws && ws.isPlaying() && isStemReady(i)); }

// --- Controls Enabling ---
function enableGlobalControls(enable) {
    const controls = [DOM.playAllStemsBtn, DOM.stopAllStemsBtn, DOM.resetAllStemsBtn, DOM.globalSpeedSlider, DOM.lockStems, DOM.globalPitchSlider, DOM.resetPitchBtn];
    controls.forEach(control => { if (control) control.disabled = !enable; });
    if (enable && DOM.resetPitchBtn && DOM.globalPitchSlider) {
        DOM.resetPitchBtn.disabled = (parseInt(DOM.globalPitchSlider.value, 10) === 0);
    }
}

/** Toggles the pointer events on waveform containers based on the lock checkbox. */
export function handleLockStemsChange() {
    if (!DOM.lockStems) return;
    const isLocked = DOM.lockStems.checked;
    for (let i = 0; i < STEM_DEFINITIONS.length; i++) {
        const waveformDiv = document.getElementById(`waveform-${i}`);
        if (waveformDiv) waveformDiv.style.pointerEvents = isLocked ? 'none' : 'auto';
    }
}

// Initialize event listeners
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.stem-volume-slider').forEach(slider => {
        slider.classList.toggle('at-zero', parseFloat(slider.value) === 0);
    });

    // Global pitch slider event listener
    if (DOM.globalPitchSlider) {
        DOM.globalPitchSlider.addEventListener('input', (e) => {
            const semitones = parseInt(e.target.value, 10) || 0;
            updateGlobalPitch(semitones);
        });
    }

    // Global pitch reset button event listener
    if (DOM.resetPitchBtn) {
        DOM.resetPitchBtn.addEventListener('click', () => {
            resetGlobalPitch();
        });
    }

    // Global speed slider event listener
    if (DOM.globalSpeedSlider) {
        DOM.globalSpeedSlider.addEventListener('input', (e) => {
            const speed = parseFloat(e.target.value) || 1.0;
            updateGlobalSpeed(speed);
        });
    }
});
