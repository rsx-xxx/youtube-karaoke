// File: frontend/web/assets/js/config.js
/**
 * Configuration constants for the frontend application.
 */

export const BASE_TITLE = "Karaoke Generator";
export const DEFAULT_FAVICON = "data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🎤</text></svg>";

// Emojis for favicon progress animation
export const FAVICON_FRAMES = ['🎤', '🎧', '🎶', '🎵', '🎼', '⭐', '🌟'];

// API endpoints (example - ensure they match your setup)
// export const API_BASE_URL = 'http://localhost:8000'; // Uncomment and set if needed
// export const API_SUGGESTIONS = '/api/suggestions';
// export const API_PROCESS = '/api/process';
// export const API_CANCEL_JOB = '/api/cancel_job';
// export const API_GENIUS_CANDIDATES = '/api/genius_candidates';

// Debounce time for suggestions fetch
export const SUGGESTION_DEBOUNCE_MS = 600;
export const SPINNER_DELAY_MS = 500; // Delay before showing spinner

// Stem definitions for WaveSurfer - using CSS variable names now
export const STEM_DEFINITIONS = [
    { name: "Instrumental", file: "instrumental.wav", colorVar: '--stem-instrumental-wave', progressVar: '--stem-instrumental-progress' },
    { name: "Vocals",       file: "vocals.wav",       colorVar: '--stem-vocals-wave',       progressVar: '--stem-vocals-progress' },
    { name: "Drums",        file: "drums.wav",        colorVar: '--stem-drums-wave',        progressVar: '--stem-drums-progress' },
    { name: "Bass",         file: "bass.wav",         colorVar: '--stem-bass-wave',         progressVar: '--stem-bass-progress' },
    { name: "Other",        file: "other.wav",        colorVar: '--stem-other-wave',        progressVar: '--stem-other-progress' }
];