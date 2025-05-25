// File: frontend/web/assets/js/dom.js
/**
 * Exports references to frequently used DOM elements.
 */

export const processBtn = document.getElementById("process-btn");
export const youtubeInput = document.getElementById("youtube-url");
export const statusMessage = document.getElementById("status-message");
export const progressDisplay = document.getElementById("progress-display");
export const progressBarContainer = document.getElementById("progress-bar-container");
export const progressBar = document.getElementById("progress-bar");
export const progressTextContainer = document.getElementById("progress-text-container");
export const progressText = document.getElementById("progress-text");
export const progressTiming = document.getElementById("progress-timing");
export const progressStepsContainer = document.getElementById("progress-steps-container");
export const languageSelect = document.getElementById("language-select");
export const subtitlePositionSelect = document.getElementById("subtitle-position-select");
export const generateSubtitlesCheckbox = document.getElementById("generate-subtitles-checkbox");
export const karaokeVideo = document.getElementById("karaoke-video");
export const resultsArea = document.querySelector(".results-area");
export const videoContainer = document.querySelector(".video-container"); // Added for consistency
export const stemsSection = document.getElementById("stems-section");
export const globalStemControlsDiv = document.getElementById("global-stem-controls"); // Renamed for clarity
export const stemsContainer = document.getElementById("stems-container");
export const downloadBtn = document.getElementById("download-btn");
export const shareBtn = document.getElementById("share-btn");
export const themeSwitcher = document.getElementById("theme-switcher");
export const videoPreview = document.getElementById("video-preview");
export const chosenVideoTitleDiv = document.getElementById("chosen-video-title");
export const suggestionSpinner = document.getElementById("suggestion-spinner");
export const faviconElement = document.getElementById("favicon");
export const suggestionDropdownElement = document.getElementById("suggestion-dropdown");

// Container for subtitle options (Added)
export const subtitleOptionsContainer = document.getElementById('subtitle-options-container');

// Genius Lyrics container elements (Added)
export const geniusLyricsContainer = document.getElementById("genius-lyrics-container");
export const geniusLyricsList = document.getElementById("genius-lyrics-list");
// *** NEW: Added reference for Genius text area ***
export const geniusSelectedText = document.getElementById("genius-selected-text");

// *** NEW: Added reference for Font Size select ***
export const subtitleFontsizeSelect = document.getElementById("subtitle-fontsize-select");

// Global stem buttons & speed slider (Added/Corrected IDs)
export const playAllStemsBtn = document.getElementById('play-all-stems');
// Note: No separate pause button in the updated HTML, playAllStemsBtn handles toggle
export const stopAllStemsBtn = document.getElementById('stop-all-stems');
export const resetAllStemsBtn = document.getElementById('reset-all-stems');
export const globalSpeedSlider = document.getElementById('global-speed');
export const globalSpeedValue = document.getElementById('global-speed-value'); // Added value display
export const lockStems = document.getElementById('lock-stems'); // Added lock stems checkbox reference

// Export all elements needed by other modules