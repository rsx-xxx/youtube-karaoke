// File: frontend/web/assets/js/pitch-shifter.js
// Real-time pitch shifting using SoundTouchJS library
// Provides independent pitch and speed control for audio stems

console.log("[PitchShifter] Module loaded.");

// Shared AudioContext
let audioContext = null;

// Track active pitch shifter nodes
const activeShifters = new Map();

// Global state
let globalPitchSemitones = 0;
let globalSpeedRate = 1.0;

/**
 * Get or create shared AudioContext
 */
export function getAudioContext() {
    if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        console.log("[PitchShifter] Created AudioContext, sample rate:", audioContext.sampleRate);
    }
    return audioContext;
}

/**
 * Resume AudioContext if suspended (needed after user gesture)
 */
export async function resumeAudioContext() {
    const ctx = getAudioContext();
    if (ctx.state === 'suspended') {
        await ctx.resume();
        console.log("[PitchShifter] AudioContext resumed");
    }
    return ctx;
}

/**
 * Check if SoundTouch library is available
 */
export function isSoundTouchAvailable() {
    const available = typeof SoundTouch !== 'undefined';
    if (!available) {
        console.warn("[PitchShifter] SoundTouch not available");
    }
    return available;
}

/**
 * Check if true pitch shifting is available
 */
export function hasTruePitchShift() {
    return isSoundTouchAvailable();
}

/**
 * Create a pitch shifter for an audio element using SoundTouch
 * @param {string} id - Unique identifier for this shifter
 * @param {HTMLAudioElement} audioElement - Source audio element
 * @returns {Object|null} Shifter control object
 */
export function createPitchShifterForElement(id, audioElement) {
    if (!audioElement) {
        console.error("[PitchShifter] No audio element provided");
        return null;
    }

    // Check if already connected
    if (audioElement._pitchShifterConnected) {
        console.warn(`[PitchShifter] Audio element already connected for ${id}`);
        return activeShifters.get(id) || null;
    }

    if (!isSoundTouchAvailable()) {
        console.warn("[PitchShifter] SoundTouch not available, using fallback");
        return null;
    }

    const ctx = getAudioContext();

    try {
        // Create source from audio element
        const source = ctx.createMediaElementSource(audioElement);
        audioElement._pitchShifterConnected = true;

        // Create SoundTouch instance
        const soundTouch = new SoundTouch();
        const pitchFactor = Math.pow(2, globalPitchSemitones / 12.0);
        soundTouch.pitch = pitchFactor;
        soundTouch.tempo = 1.0;
        soundTouch.rate = 1.0;

        // Create script processor for real-time processing
        const bufferSize = 4096;
        const scriptNode = ctx.createScriptProcessor(bufferSize, 2, 2);

        // Create gain node for volume control
        const gainNode = ctx.createGain();
        gainNode.gain.value = 1.0;

        // Pre-allocate buffers
        const inputBuffer = new Float32Array(bufferSize * 2);
        const outputBuffer = new Float32Array(bufferSize * 2);

        scriptNode.onaudioprocess = (e) => {
            const inputL = e.inputBuffer.getChannelData(0);
            const inputR = e.inputBuffer.numberOfChannels > 1 ?
                          e.inputBuffer.getChannelData(1) : inputL;
            const outputL = e.outputBuffer.getChannelData(0);
            const outputR = e.outputBuffer.getChannelData(1);

            // Check if pitch is neutral - pass through directly
            if (Math.abs(soundTouch.pitch - 1.0) < 0.001) {
                outputL.set(inputL);
                outputR.set(inputR);
                return;
            }

            // Interleave input samples
            for (let i = 0; i < inputL.length; i++) {
                inputBuffer[i * 2] = inputL[i];
                inputBuffer[i * 2 + 1] = inputR[i];
            }

            // Feed to SoundTouch
            soundTouch.inputBuffer.putSamples(inputBuffer, 0, inputL.length);

            // Get processed samples
            const framesExtracted = soundTouch.outputBuffer.receiveSamples(outputBuffer, inputL.length);

            // Deinterleave to output
            for (let i = 0; i < framesExtracted; i++) {
                outputL[i] = outputBuffer[i * 2];
                outputR[i] = outputBuffer[i * 2 + 1];
            }

            // Fill remaining with zeros if not enough samples
            for (let i = framesExtracted; i < outputL.length; i++) {
                outputL[i] = 0;
                outputR[i] = 0;
            }
        };

        // Connect: source -> scriptNode -> gainNode -> destination
        source.connect(scriptNode);
        scriptNode.connect(gainNode);
        gainNode.connect(ctx.destination);

        const shifter = {
            id,
            audioElement,
            source,
            scriptNode,
            gainNode,
            soundTouch,
            connected: true
        };

        activeShifters.set(id, shifter);
        console.log(`[PitchShifter] Created SoundTouch shifter for ${id}, pitch=${pitchFactor.toFixed(3)}`);
        return shifter;

    } catch (error) {
        console.error(`[PitchShifter] Error creating shifter for ${id}:`, error);
        audioElement._pitchShifterConnected = false;
        return null;
    }
}

/**
 * Set global pitch for all shifters
 * @param {number} semitones - Pitch shift in semitones (-12 to +12)
 */
export function setGlobalPitch(semitones) {
    globalPitchSemitones = semitones;
    const pitchFactor = Math.pow(2, semitones / 12.0);

    activeShifters.forEach((shifter, id) => {
        if (shifter.soundTouch) {
            shifter.soundTouch.pitch = pitchFactor;
            console.log(`[PitchShifter] Set pitch for ${id}: ${pitchFactor.toFixed(4)}`);
        }
    });

    console.log(`[PitchShifter] Global pitch: ${semitones}st (factor: ${pitchFactor.toFixed(4)}), active shifters: ${activeShifters.size}`);
}

/**
 * Set global speed (affects playbackRate on audio elements)
 * @param {number} rate - Speed rate (0.5 to 2.0)
 */
export function setGlobalSpeed(rate) {
    globalSpeedRate = rate;

    activeShifters.forEach((shifter) => {
        if (shifter.audioElement) {
            shifter.audioElement.playbackRate = rate;
        }
    });

    console.log(`[PitchShifter] Global speed: ${rate.toFixed(2)}x`);
}

/**
 * Set volume for a specific shifter
 * @param {string} id - Shifter identifier
 * @param {number} volume - Volume (0 to 1)
 */
export function setVolume(id, volume) {
    const shifter = activeShifters.get(id);
    if (shifter && shifter.gainNode) {
        const ctx = getAudioContext();
        shifter.gainNode.gain.setTargetAtTime(volume, ctx.currentTime, 0.01);
    }
}

/**
 * Get current pitch for a shifter
 */
export function getCurrentPitch() {
    return globalPitchSemitones;
}

/**
 * Get current speed
 */
export function getCurrentSpeed() {
    return globalSpeedRate;
}

/**
 * Destroy a pitch shifter
 * @param {string} id - Shifter identifier
 */
export function destroyPitchShifter(id) {
    const shifter = activeShifters.get(id);
    if (!shifter) return;

    try {
        if (shifter.scriptNode) {
            shifter.scriptNode.disconnect();
            shifter.scriptNode.onaudioprocess = null;
        }
        if (shifter.gainNode) {
            shifter.gainNode.disconnect();
        }
        if (shifter.source) {
            shifter.source.disconnect();
        }
        if (shifter.audioElement) {
            shifter.audioElement._pitchShifterConnected = false;
        }
    } catch (e) {
        console.warn(`[PitchShifter] Cleanup error for ${id}:`, e);
    }

    activeShifters.delete(id);
    console.log(`[PitchShifter] Destroyed ${id}`);
}

/**
 * Destroy all pitch shifters
 */
export function destroyAllPitchShifters() {
    const ids = Array.from(activeShifters.keys());
    ids.forEach(id => destroyPitchShifter(id));
    console.log("[PitchShifter] Destroyed all shifters");
}

/**
 * Get number of active shifters
 */
export function getActiveShifterCount() {
    return activeShifters.size;
}

/**
 * Get active shifters info
 */
export function getActiveShiftersInfo() {
    const info = [];
    activeShifters.forEach((shifter, id) => {
        info.push({
            id,
            connected: shifter.connected,
            pitch: shifter.soundTouch ? shifter.soundTouch.pitch : 1.0
        });
    });
    return info;
}
