// File: frontend/web/assets/js/suggestions.js
// Handles fetching and displaying YouTube video suggestions and Genius lyrics candidates.
// UPDATED (v10): Added flag to prevent input handler running immediately after selection.

console.log("[Suggestions] Module loaded.");

import * as DOM from './dom.js';
import * as UI from './ui.js';
import { SUGGESTION_DEBOUNCE_MS, SPINNER_DELAY_MS } from './config.js';
import * as API from './api.js';

let suggestionTimeout = null;
let spinnerTimeout = null;
let suggestionAbortController = null;
let geniusFetchAbortController = null;

let isDropdownOpen = false;
let isDropdownMousedown = false; // Flag for mousedown specifically on dropdown items/scrollbar
let isSelectingSuggestion = false; // *** NEW: Flag to ignore input event during selection ***

/**
 * Initializes suggestion functionality by adding event listeners.
 */
export function initSuggestions() {
    console.log("[Suggestions] Initializing...");
    if (!DOM.youtubeInput || !DOM.suggestionDropdownElement) {
        console.error("[Suggestions] Critical error: Input field or suggestion dropdown element not found!");
        return;
    }
    DOM.youtubeInput.addEventListener("input", handleInput);
    DOM.youtubeInput.addEventListener("focus", handleFocus);
    // Use focusout to detect when focus leaves the input field
    DOM.youtubeInput.addEventListener('focusout', handleInputFocusOut);

    // Listen for mousedown on the dropdown container itself to set the flag
    // Use capture phase to catch mousedown on scrollbar before it bubbles
    DOM.suggestionDropdownElement.addEventListener('mousedown', () => {
        // console.log('[Suggestions] Mousedown detected on dropdown container.');
        isDropdownMousedown = true;
    }, true); // Use capture phase

    // Global click listener to hide dropdown if click is truly outside
    document.addEventListener("click", handleDocumentClick);

    console.log("[Suggestions] Event listeners initialized.");
}

/**
 * Handles focus leaving the input field. Hides dropdown unless mousedown occurred on it.
 */
function handleInputFocusOut(event) {
    // console.log('[Suggestions] Input focusout triggered.');
    // Use queueMicrotask for a micro-delay, allowing mousedown events to register
    queueMicrotask(() => {
        // Hide dropdown ONLY if focus left the input AND mousedown wasn't on the dropdown itself.
        if (!isDropdownMousedown && isDropdownOpen && document.activeElement !== DOM.youtubeInput) {
            // console.log('[Suggestions] Focus left input, no dropdown interaction detected. Hiding.');
            UI.hideSuggestionDropdown();
            isDropdownOpen = false;
        }
        // Always reset the flag after the check within the microtask
        isDropdownMousedown = false;
    });
}


/**
 * Hides the suggestion dropdown if a click occurs outside the input field and the dropdown itself.
 */
function handleDocumentClick(event) {
    if (isDropdownOpen && DOM.youtubeInput && DOM.suggestionDropdownElement) {
        if (!DOM.youtubeInput.contains(event.target) &&
            !DOM.suggestionDropdownElement.contains(event.target))
        {
            // console.log("[Suggestions] Click truly outside detected. Hiding dropdown.");
            UI.hideSuggestionDropdown();
            isDropdownOpen = false;
            isDropdownMousedown = false; // Reset flag
        }
    }
}

/**
 * Handles the 'input' event on the YouTube URL/search field.
 */
function handleInput(e) {
    // *** FIX: Ignore input event if it was triggered by suggestion selection ***
    if (isSelectingSuggestion) {
        // console.log("[Suggestions] Input event ignored during suggestion selection.");
        return;
    }
    // *** END FIX ***

    const query = e.target.value.trim();
    const wasOpen = isDropdownOpen; // Store if dropdown was open before clearing things
    // console.log(`[Suggestions] Input event. Query: "${query}", WasOpen: ${wasOpen}`);

    // --- FIX: Clear previous timeouts/fetches ---
    clearTimeout(suggestionTimeout); suggestionTimeout = null;
    clearTimeout(spinnerTimeout); spinnerTimeout = null;
    if (suggestionAbortController) {
        // console.log("[Suggestions] Aborting previous suggestion fetch due to new input.");
        suggestionAbortController.abort("New input received");
        suggestionAbortController = null;
    }
    clearGeniusFetch(); // Also clear any pending Genius fetch
    // --- End fix ---

    UI.clearPreview();
    UI.hideOptionsAndGenius(); // Hide options/genius immediately on input change
    UI.hideSuggestionSpinner(); // Hide spinner immediately

    // --- FIX: Check query length *after* clearing/aborting ---
    if (query.length < 2) {
        // console.log("[Suggestions] Query too short or empty.");
        if (wasOpen) { // Only hide if it was previously open and now query is too short
            // console.log("[Suggestions] Hiding dropdown because query became too short.");
            UI.hideSuggestionDropdown();
            isDropdownOpen = false;
        }
        return; // Stop further processing for short queries
    }
    // --- End fix ---

    // If query is long enough, proceed with debounce logic

    spinnerTimeout = setTimeout(() => {
        // Only show spinner if a fetch is actually pending (debounce hasn't been cleared again)
        if (!suggestionAbortController && suggestionTimeout) {
             // console.log("[Suggestions] Showing spinner after delay.");
             UI.showSuggestionSpinner();
        }
    }, SPINNER_DELAY_MS);

    suggestionTimeout = setTimeout(() => {
        if (DOM.youtubeInput.value.trim() === query) { // Check if query hasn't changed again during debounce
            // console.log(`[Suggestions] Debounce timer expired for query: "${query}". Fetching...`);
            fetchAndRenderSuggestionsOrMetadata(query);
        } else {
            // console.log("[Suggestions] Query changed during debounce, skipping fetch.");
            clearTimeout(spinnerTimeout);
            UI.hideSuggestionSpinner();
        }
        suggestionTimeout = null; // Mark debounce timer as finished
    }, SUGGESTION_DEBOUNCE_MS);
}


/**
 * Fetches suggestions (for search) or metadata (for URL) and renders them.
 */
async function fetchAndRenderSuggestionsOrMetadata(query) {
    // console.log(`[Suggestions] Fetching suggestions/metadata for query: "${query}"`);

    if (suggestionAbortController) { // Should be null here normally, but double-check
        suggestionAbortController.abort("Starting new fetch");
    }
    suggestionAbortController = new AbortController();
    const signal = suggestionAbortController.signal;

    // Show spinner immediately when fetch starts after debounce
    UI.showSuggestionSpinner();
    clearTimeout(spinnerTimeout); // Clear any pending spinner timeout

    try {
        const results = await API.fetchSuggestions(query, signal);

        if (signal.aborted) {
            // console.log("[Suggestions] Fetch aborted after API call started.");
            return; // Don't process results if aborted
        }

        // console.log("[Suggestions] API fetch returned results:", results);

        // Ensure the input hasn't changed *again* since the fetch completed
        const currentQueryInInput = DOM.youtubeInput.value.trim();
        if (currentQueryInInput !== query) {
            // console.log("[Suggestions] Input value changed after fetch completed. Discarding results.");
            UI.hideSuggestionSpinner(); // Still hide spinner
            return;
        }

        // Check if input still has focus before rendering
        const inputHasFocus = document.activeElement === DOM.youtubeInput;
        if (!inputHasFocus && !isDropdownMousedown) {
             // console.log("[Suggestions] Input lost focus after fetch completed. Not rendering.");
             UI.hideSuggestionSpinner();
             return;
        }

        if (results && results.length > 0) {
            // Simple check if the first result's URL exactly matches the query
            const isUrlMetadataResult = results.length === 1 && results[0].url === query;

            if (isUrlMetadataResult) {
                // console.log("[Suggestions] Single result matching input URL - selecting metadata.");
                handleSuggestionSelect(results[0]); // Select it (this hides dropdown)
            } else {
                // console.log("[Suggestions] Rendering search suggestions dropdown.");
                // Pass the mousedown handler for items
                UI.renderSuggestionDropdown(results, handleSuggestionSelect, () => {
                    // console.log('[Suggestions] Suggestion Item Mousedown handler fired.');
                    isDropdownMousedown = true; // Set flag on item mousedown
                });
                isDropdownOpen = true; // Mark dropdown as open
            }
        } else {
            // console.log("[Suggestions] No results found. Hiding dropdown.");
            UI.hideSuggestionDropdown();
            isDropdownOpen = false;
        }

    } catch (err) {
        if (err.name === 'AbortError') {
            // This specific error is expected when input changes, log less severely
            // console.log("[Suggestions] Fetch explicitly aborted (likely due to new input).");
        } else {
            console.error("[Suggestions] Error fetching suggestions/metadata:", err);
            UI.hideSuggestionDropdown(); // Hide on unexpected error
            isDropdownOpen = false;
        }
    } finally {
        UI.hideSuggestionSpinner();
        // Clear controller only if it's the one that just finished
        if (suggestionAbortController && suggestionAbortController.signal === signal) {
            suggestionAbortController = null;
        }
    }
}


/**
 * Handles the 'focus' event on the input field.
 */
function handleFocus() {
    const query = DOM.youtubeInput?.value.trim();
    // console.log(`[Suggestions] Input focused. Query: "${query}", DropdownOpen: ${isDropdownOpen}`);
    // If input has content and dropdown isn't already open, try fetching
    // Avoid fetching immediately if a fetch is already in progress or debouncing
    if (query && query.length >= 2 && !isDropdownOpen && !suggestionTimeout && !suggestionAbortController) {
        // console.log("[Suggestions] Input focused with valid query, dropdown hidden/idle. Fetching...");
        fetchAndRenderSuggestionsOrMetadata(query);
    } else if (isDropdownOpen) {
        // console.log("[Suggestions] Input focused, dropdown already open.");
        // Ensure dropdown is positioned correctly if it was already open
        UI.positionSuggestionDropdown();
    }
}

/**
 * Handles the selection of a suggestion item or direct URL metadata result.
 */
function handleSuggestionSelect(item) {
    console.log("[Suggestions] Suggestion selected:", item);
    if (!item || typeof item.url !== 'string') return;

    // *** FIX: Set flag before updating input ***
    isSelectingSuggestion = true;

    UI.updateInputWithSuggestion(item); // This might trigger 'input' event

    // *** FIX: Reset flag after input value change likely processed ***
    // Use queueMicrotask to ensure it runs after potential synchronous event handling
    queueMicrotask(() => {
        isSelectingSuggestion = false;
        // console.log("[Suggestions] Reset isSelectingSuggestion flag.");
    });
    // *** END FIX ***

    clearSuggestionTimeout(); // Clear any pending suggestion fetches
    UI.hideSuggestionDropdown(); // Hide dropdown *after* updating input
    UI.hideSuggestionSpinner();
    isDropdownOpen = false;
    isDropdownMousedown = false; // Reset interaction flag

    // Show relevant options (like subtitles checkbox, language etc.)
    if (DOM.subtitleOptionsContainer) {
        DOM.subtitleOptionsContainer.style.display = 'block';
        requestAnimationFrame(() => {
            DOM.subtitleOptionsContainer.style.opacity = '1';
            DOM.subtitleOptionsContainer.style.maxHeight = '500px';
        });
        UI.toggleSubOptionsVisibility(); // Apply initial enabled/disabled state based on checkbox
    }

    // Attempt to fetch Genius lyrics candidates
    clearGeniusFetch();
    const searchTitle = (item.title && item.title !== item.url) ? item.title : item.url;
    let artistGuess = item.uploader || "";
    // Simple heuristic to extract artist from title if not provided by uploader
    if (!artistGuess && item.title && item.title !== item.url) {
        const parts = item.title.split(/\s*-\s*|\s*–\s*|\s*—\s*(?!feat|ft)/i);
        if (parts.length > 1) {
             const potentialArtist = parts[0].trim();
             // Basic check to avoid common non-artist terms
             if (!/\b(lyrics?|official|video|audio|feat|ft|remix|edit|live|cover|acoustic|visualizer|album|ep)\b/i.test(potentialArtist.toLowerCase())) {
                 artistGuess = potentialArtist;
             }
        }
    }
    fetchAndDisplayGeniusCandidates(searchTitle, artistGuess);
}


// --- Utility Functions ---

/** Clears pending suggestion timeouts and aborts active fetch. */
export function clearSuggestionTimeout() {
    clearTimeout(suggestionTimeout); suggestionTimeout = null;
    clearTimeout(spinnerTimeout); spinnerTimeout = null;
    if (suggestionAbortController) {
        suggestionAbortController.abort("Suggestion timeout cleared");
        suggestionAbortController = null;
    }
    UI.hideSuggestionSpinner();
}

/** Aborts active Genius fetch request. */
function clearGeniusFetch() {
    if (geniusFetchAbortController) {
        geniusFetchAbortController.abort("New action triggered");
        geniusFetchAbortController = null;
    }
}


// --- Genius Lyrics Handling ---

/** Fetches and displays Genius lyrics candidates. */
async function fetchAndDisplayGeniusCandidates(title, artist = "") {
    if (!DOM.geniusLyricsContainer || !DOM.geniusLyricsList) {
        console.warn("[Suggestions] Genius lyrics container or list element not found.");
        return;
    }
    // Show Genius container *only* if lyrics are enabled via checkbox
    if (DOM.generateSubtitlesCheckbox?.checked) {
        DOM.geniusLyricsContainer.style.display = 'flex'; // Make container visible (it's a flex container)
        requestAnimationFrame(() => { // Start transition
             DOM.geniusLyricsContainer.style.opacity = '1';
             DOM.geniusLyricsContainer.style.maxHeight = '700px'; // Allow space to expand
        });
    } else {
        console.log("[Suggestions] Lyrics checkbox is unchecked, skipping Genius display.");
        DOM.geniusLyricsContainer.style.display = 'none'; // Ensure it's hidden if checkbox is off
        return;
    }

    clearGeniusFetch();
    geniusFetchAbortController = new AbortController();
    const signal = geniusFetchAbortController.signal;

    // Clear previous results and show loading state
    DOM.geniusLyricsList.innerHTML = '<li><span class="spinner"></span> Searching Genius...</li>';
    const lyricsPanel = document.getElementById("lyrics-panel");
    const toggleBtn = document.getElementById("lyrics-toggle-btn");
    const textArea = DOM.geniusSelectedText; // Use textarea ref
    if (lyricsPanel) lyricsPanel.classList.add('hidden'); // Collapse panel
    if (toggleBtn) { toggleBtn.setAttribute("aria-expanded", "false"); toggleBtn.classList.remove('expanded'); }
    if (textArea) textArea.value = ""; // Clear text area
    window.selectedGeniusLyrics = null; // Reset global selection state

    try {
        const candidates = await API.fetchGeniusCandidates(title, artist, signal);

        if (signal.aborted) { console.log("[Suggestions] Genius fetch aborted."); return; }

        DOM.geniusLyricsList.innerHTML = ''; // Clear loading/previous content

        // Always add "Use Original" option first
        const noGeniusLi = createLyricOptionItem("Use Original Transcription", null, "Use the text directly recognized by the AI model.");
        DOM.geniusLyricsList.appendChild(noGeniusLi);

        let validCandidatesFound = 0;
        let firstValidCandidateElement = null;

        if (Array.isArray(candidates) && candidates.length > 0) {
            candidates.forEach((candidate) => {
                // Basic validation of candidate structure
                if (!candidate || typeof candidate.title !== 'string' || typeof candidate.lyrics !== 'string') {
                    console.warn("[Suggestions] Skipping invalid Genius candidate structure:", candidate); return;
                }
                 // Basic check for non-empty lyrics (backend should ideally provide cleaned lyrics)
                 if (!candidate.lyrics.trim()) {
                     console.warn(`[Suggestions] Skipping Genius candidate '${candidate.title}' due to empty lyrics.`); return;
                 }

                validCandidatesFound++;
                const geniusLi = createLyricOptionItem(
                    `${candidate.title}${candidate.artist ? ` - ${candidate.artist}` : ''}`, // Display format
                    candidate.lyrics, // Store full lyrics in dataset
                    `Preview:\n${candidate.lyrics.substring(0, 150).replace(/\n/g, ' ')}...` // Tooltip preview
                );
                 if (candidate.url) { // Add link to Genius page if available
                     const link = document.createElement('a'); link.href = candidate.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = 'View'; link.className = 'view-lyrics-btn'; link.style.marginLeft = '10px';
                     // Prevent selection when clicking the link itself
                     link.addEventListener('mousedown', (e) => e.stopPropagation());
                     link.addEventListener('click', (e) => e.stopPropagation());
                     geniusLi.appendChild(link);
                 }
                DOM.geniusLyricsList.appendChild(geniusLi);
                if (validCandidatesFound === 1) { // Store reference to the first valid one
                    firstValidCandidateElement = geniusLi;
                }
            });
        }

        // Handle selection logic based on number of candidates found
        if (validCandidatesFound === 0) {
            const li = document.createElement('li'); li.textContent = 'No potential lyrics found on Genius.'; li.style.fontStyle = 'italic';
            DOM.geniusLyricsList.appendChild(li);
             // Default to "Use Original" if none found
             console.log("[Genius] No valid candidates found. Defaulting to 'Use Original'.");
             setTimeout(() => noGeniusLi.click(), 50); // Use timeout to ensure element is selectable
        } else if (validCandidatesFound === 1 && firstValidCandidateElement) {
             // Auto-select if exactly one valid candidate was found
             console.log("[Genius] Exactly one valid candidate found. Auto-selecting.");
             setTimeout(() => firstValidCandidateElement.click(), 50);
        } else {
             // Multiple candidates found, default selection to "Use Original"
              console.log(`[Genius] ${validCandidatesFound} candidates found. Defaulting to 'Use Original'.`);
              setTimeout(() => noGeniusLi.click(), 50); // Default selection
        }

    } catch (error) {
        if (error.name !== 'AbortError') {
            console.error("[Genius] Error fetching/displaying lyrics candidates:", error);
            DOM.geniusLyricsList.innerHTML = `<li>Error fetching lyrics: ${error.message}</li>`;
             // Default to "Use Original" on error
             const noGeniusLi = createLyricOptionItem("Use Original Transcription", null, "Use the text directly recognized by the AI model.");
             DOM.geniusLyricsList.insertBefore(noGeniusLi, DOM.geniusLyricsList.firstChild); // Add if not already there
             setTimeout(() => noGeniusLi.click(), 50);
        } else {
            console.log("[Genius] Lyrics fetch aborted."); // Expected if user action cancels it
        }
    } finally {
        // Clean up abort controller reference
        if (geniusFetchAbortController && geniusFetchAbortController.signal === signal) {
            geniusFetchAbortController = null;
        }
    }
}

/** Creates a list item element for the Genius selection list. */
function createLyricOptionItem(text, lyricsData, titleAttr) {
    const li = document.createElement('li');
    li.textContent = text;
    li.style.cursor = 'pointer';
    li.title = titleAttr; // Tooltip
    li.setAttribute('role', 'option');
    li.tabIndex = 0; // Make it focusable

    if (lyricsData !== null) {
        li.dataset.lyrics = lyricsData; // Store lyrics string in dataset attribute
    }

    // Use 'click' for selection (safer than mousedown with focus interactions)
    li.addEventListener('click', (e) => {
        // console.log(`[Suggestions] Click on lyric option: "${text}"`);

        // Store selected lyrics (or null for "Original") globally for process click handler
        window.selectedGeniusLyrics = li.dataset.lyrics || null;
        // console.log(`[Suggestions] window.selectedGeniusLyrics set to: ${window.selectedGeniusLyrics ? window.selectedGeniusLyrics.substring(0, 30) + '...' : 'null'}`);

        highlightSelectedLyric(li); // Highlight this item in the list

        // Update the preview text area and panel visibility
        const lyricsPanel = document.getElementById("lyrics-panel");
        const toggleBtn = document.getElementById("lyrics-toggle-btn");
        const txtArea = DOM.geniusSelectedText;

        if (!txtArea) { console.error("[Suggestions] Genius text area element not found!"); return; }

        if (window.selectedGeniusLyrics === null) { // "Use Original" selected
            // console.log("[Genius] User selected: Use Original Transcription.");
            if (lyricsPanel) lyricsPanel.classList.add('hidden'); // Hide panel
            if (toggleBtn) { toggleBtn.setAttribute("aria-expanded", "false"); toggleBtn.classList.remove('expanded'); }
            txtArea.value = ""; // Clear text area
        } else { // A specific Genius option selected
            // console.log(`[Genius] User selected: ${text}.`);
            if (lyricsPanel) lyricsPanel.classList.remove('hidden'); // Show panel
            if (toggleBtn) { toggleBtn.setAttribute("aria-expanded", "true"); toggleBtn.classList.add('expanded'); }
            txtArea.value = window.selectedGeniusLyrics; // Populate text area with selected lyrics
        }
    });

    // Allow selection using Enter or Space keys when focused
    li.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault(); // Prevent default space scroll or enter submit
            li.click(); // Trigger the click handler
        }
    });

    return li;
}

/** Highlights the selected item in the Genius list and deselects others. */
function highlightSelectedLyric(selectedLi) {
    if (!DOM.geniusLyricsList) return;
    // Select only direct children options to avoid selecting elements within links etc.
    const allLis = DOM.geniusLyricsList.querySelectorAll(":scope > li[role='option']");
    allLis.forEach(li => {
        li.classList.remove("selected-lyric"); // CSS class for highlighting
        li.setAttribute("aria-selected", "false");
    });
    if (selectedLi) { // Check if selectedLi is a valid element
        selectedLi.classList.add("selected-lyric");
        selectedLi.setAttribute("aria-selected", "true");
    }
}