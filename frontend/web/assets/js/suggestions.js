// File: frontend/web/assets/js/suggestions.js
import * as DOM from './dom.js';
import * as UI from './ui.js';
import { SUGGESTION_DEBOUNCE_MS, SPINNER_DELAY_MS } from './config.js';
import * as API from './api.js';

let suggestionTimeout = null;
let spinnerTimeout = null;
let suggestionAbortController = null;
let geniusFetchAbortController = null;

let isDropdownOpen = false;
let isDropdownMousedown = false;
let isSelectingSuggestion = false;

export function initSuggestions() {
    if (!DOM.youtubeInput || !DOM.suggestionDropdownElement) {
        return;
    }
    DOM.youtubeInput.addEventListener("input", handleInput);
    DOM.youtubeInput.addEventListener("focus", handleFocus);
    DOM.youtubeInput.addEventListener('focusout', handleInputFocusOut);
    DOM.suggestionDropdownElement.addEventListener('mousedown', () => {
        isDropdownMousedown = true;
    }, true);
    document.addEventListener("click", handleDocumentClick);
}

function handleInputFocusOut(event) {
    queueMicrotask(() => {
        if (!isDropdownMousedown && isDropdownOpen && document.activeElement !== DOM.youtubeInput) {
            UI.hideSuggestionDropdown();
            isDropdownOpen = false;
        }
        isDropdownMousedown = false;
    });
}

function handleDocumentClick(event) {
    if (isDropdownOpen && DOM.youtubeInput && DOM.suggestionDropdownElement) {
        if (!DOM.youtubeInput.contains(event.target) &&
            !DOM.suggestionDropdownElement.contains(event.target)) {
            UI.hideSuggestionDropdown();
            isDropdownOpen = false;
            isDropdownMousedown = false;
        }
    }
}

function handleInput(e) {
    if (isSelectingSuggestion) {
        return;
    }
    const query = e.target.value.trim();
    const wasOpen = isDropdownOpen;

    clearTimeout(suggestionTimeout); suggestionTimeout = null;
    clearTimeout(spinnerTimeout); spinnerTimeout = null;
    if (suggestionAbortController) {
        suggestionAbortController.abort("New input received");
        suggestionAbortController = null;
    }
    clearGeniusFetch();
    UI.clearPreview();
    UI.hideOptionsAndGenius();
    UI.hideSuggestionSpinner();

    if (query.length < 2) {
        if (wasOpen) {
            UI.hideSuggestionDropdown();
            isDropdownOpen = false;
        }
        return;
    }

    spinnerTimeout = setTimeout(() => {
        if (!suggestionAbortController && suggestionTimeout) {
             UI.showSuggestionSpinner();
        }
    }, SPINNER_DELAY_MS);

    suggestionTimeout = setTimeout(() => {
        if (DOM.youtubeInput.value.trim() === query) {
            fetchAndRenderSuggestionsOrMetadata(query);
        } else {
            clearTimeout(spinnerTimeout);
            UI.hideSuggestionSpinner();
        }
        suggestionTimeout = null;
    }, SUGGESTION_DEBOUNCE_MS);
}

async function fetchAndRenderSuggestionsOrMetadata(query) {
    if (suggestionAbortController) {
        suggestionAbortController.abort("Starting new fetch");
    }
    suggestionAbortController = new AbortController();
    const signal = suggestionAbortController.signal;

    UI.showSuggestionSpinner();
    clearTimeout(spinnerTimeout);

    try {
        const results = await API.fetchSuggestions(query, signal);
        if (signal.aborted) return;

        const currentQueryInInput = DOM.youtubeInput.value.trim();
        if (currentQueryInInput !== query) {
            UI.hideSuggestionSpinner();
            return;
        }

        const inputHasFocus = document.activeElement === DOM.youtubeInput;
        if (!inputHasFocus && !isDropdownMousedown) {
             UI.hideSuggestionSpinner();
             return;
        }

        if (results && results.length > 0) {
            const isUrlMetadataResult = results.length === 1 && results[0].url === query;
            if (isUrlMetadataResult) {
                handleSuggestionSelect(results[0]);
            } else {
                UI.renderSuggestionDropdown(results, handleSuggestionSelect, () => {
                    isDropdownMousedown = true;
                });
                isDropdownOpen = true;
            }
        } else {
            UI.hideSuggestionDropdown();
            isDropdownOpen = false;
        }
    } catch (err) {
        if (err.name !== 'AbortError') {
            UI.hideSuggestionDropdown();
            isDropdownOpen = false;
        }
    } finally {
        UI.hideSuggestionSpinner();
        if (suggestionAbortController && suggestionAbortController.signal === signal) {
            suggestionAbortController = null;
        }
    }
}

function handleFocus() {
    const query = DOM.youtubeInput?.value.trim();
    if (query && query.length >= 2 && !isDropdownOpen && !suggestionTimeout && !suggestionAbortController) {
        fetchAndRenderSuggestionsOrMetadata(query);
    } else if (isDropdownOpen) {
        UI.positionSuggestionDropdown();
    }
}

function handleSuggestionSelect(item) {
    if (!item || typeof item.url !== 'string') return;
    isSelectingSuggestion = true;
    UI.updateInputWithSuggestion(item);
    queueMicrotask(() => {
        isSelectingSuggestion = false;
    });

    clearSuggestionTimeout();
    UI.hideSuggestionDropdown();
    UI.hideSuggestionSpinner();
    isDropdownOpen = false;
    isDropdownMousedown = false;

    if (DOM.subtitleOptionsContainer) {
        DOM.subtitleOptionsContainer.style.display = 'block';
        requestAnimationFrame(() => {
            DOM.subtitleOptionsContainer.style.opacity = '1';
            DOM.subtitleOptionsContainer.style.maxHeight = '500px';
        });
        UI.toggleSubOptionsVisibility();
    }

    clearGeniusFetch();
    const searchTitle = (item.title && item.title !== item.url) ? item.title : item.url;
    let artistGuess = item.uploader || "";

    // Clean up YouTube's auto-generated channel suffixes
    if (artistGuess) {
        artistGuess = artistGuess
            .replace(/\s*-\s*Topic$/i, '')  // "Artist - Topic" -> "Artist"
            .replace(/\s*VEVO$/i, '')        // "ArtistVEVO" -> "Artist"
            .replace(/\s*Official$/i, '')   // "Artist Official" -> "Artist"
            .trim();
    }

    if (!artistGuess && item.title && item.title !== item.url) {
        const parts = item.title.split(/\s*-\s*|\s*–\s*|\s*—\s*(?!feat|ft)/i);
        if (parts.length > 1) {
             const potentialArtist = parts[0].trim();
             if (!/\b(lyrics?|official|video|audio|feat|ft|remix|edit|live|cover|acoustic|visualizer|album|ep)\b/i.test(potentialArtist.toLowerCase())) {
                 artistGuess = potentialArtist;
             }
        }
    }
    fetchAndDisplayGeniusCandidates(searchTitle, artistGuess);
}

export function clearSuggestionTimeout() {
    clearTimeout(suggestionTimeout); suggestionTimeout = null;
    clearTimeout(spinnerTimeout); spinnerTimeout = null;
    if (suggestionAbortController) {
        suggestionAbortController.abort("Suggestion timeout cleared");
        suggestionAbortController = null;
    }
    UI.hideSuggestionSpinner();
}

function clearGeniusFetch() {
    if (geniusFetchAbortController) {
        geniusFetchAbortController.abort("New action triggered");
        geniusFetchAbortController = null;
    }
}

async function fetchAndDisplayGeniusCandidates(title, artist = "") {
    if (!DOM.geniusLyricsContainer || !DOM.geniusLyricsList) {
        return;
    }
    if (DOM.generateSubtitlesCheckbox?.checked) {
        DOM.geniusLyricsContainer.style.display = 'flex';
        requestAnimationFrame(() => {
             DOM.geniusLyricsContainer.style.opacity = '1';
             DOM.geniusLyricsContainer.style.maxHeight = '700px';
        });
    } else {
        DOM.geniusLyricsContainer.style.display = 'none';
        return;
    }

    clearGeniusFetch();
    geniusFetchAbortController = new AbortController();
    const signal = geniusFetchAbortController.signal;

    // Safe DOM construction (prevents XSS) - improved spinner
    DOM.geniusLyricsList.innerHTML = '';
    const searchingLi = document.createElement('li');
    searchingLi.className = 'genius-search-loading';

    const spinnerSpan = document.createElement('span');
    spinnerSpan.className = 'spinner';

    const textSpan = document.createElement('span');
    textSpan.className = 'spinner-text';
    textSpan.textContent = 'Searching Genius...';

    searchingLi.appendChild(spinnerSpan);
    searchingLi.appendChild(textSpan);
    DOM.geniusLyricsList.appendChild(searchingLi);
    const lyricsPanel = document.getElementById("lyrics-panel");
    const toggleBtn = document.getElementById("lyrics-toggle-btn");
    const textArea = DOM.geniusSelectedText;
    if (lyricsPanel) lyricsPanel.classList.add('hidden');
    if (toggleBtn) { toggleBtn.setAttribute("aria-expanded", "false"); toggleBtn.classList.remove('expanded'); }
    if (textArea) textArea.value = "";
    window.selectedGeniusLyrics = null;

    try {
        const candidates = await API.fetchGeniusCandidates(title, artist, signal);
        if (signal.aborted) return;

        DOM.geniusLyricsList.innerHTML = '';
        const noGeniusLi = createLyricOptionItem("Use Original Transcription", null, "Use the text directly recognized by the AI model.");
        DOM.geniusLyricsList.appendChild(noGeniusLi);

        let validCandidatesFound = 0;
        let firstValidCandidateElement = null;

        if (Array.isArray(candidates) && candidates.length > 0) {
            candidates.forEach((candidate) => {
                if (!candidate || typeof candidate.title !== 'string' || typeof candidate.lyrics !== 'string') {
                    return;
                }
                 if (!candidate.lyrics.trim()) {
                     return;
                 }
                validCandidatesFound++;
                const geniusLi = createLyricOptionItem(
                    `${candidate.title}${candidate.artist ? ` - ${candidate.artist}` : ''}`,
                    candidate.lyrics,
                    `Preview:\n${candidate.lyrics.substring(0, 150).replace(/\n/g, ' ')}...`
                );
                 if (candidate.url) {
                     const link = document.createElement('a'); link.href = candidate.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = 'View'; link.className = 'view-lyrics-btn'; link.style.marginLeft = '10px';
                     link.addEventListener('mousedown', (e) => e.stopPropagation());
                     link.addEventListener('click', (e) => e.stopPropagation());
                     geniusLi.appendChild(link);
                 }
                DOM.geniusLyricsList.appendChild(geniusLi);
                if (validCandidatesFound === 1) {
                    firstValidCandidateElement = geniusLi;
                }
            });
        }

        if (validCandidatesFound === 0) {
            const li = document.createElement('li'); li.textContent = 'No potential lyrics found on Genius.'; li.style.fontStyle = 'italic';
            DOM.geniusLyricsList.appendChild(li);
             setTimeout(() => noGeniusLi.click(), 50);
        } else if (validCandidatesFound === 1 && firstValidCandidateElement) {
             setTimeout(() => firstValidCandidateElement.click(), 50);
        } else {
              setTimeout(() => noGeniusLi.click(), 50);
        }
    } catch (error) {
        if (error.name !== 'AbortError') {
            // Safe DOM construction (prevents XSS)
            DOM.geniusLyricsList.innerHTML = '';
            const errorLi = document.createElement('li');
            errorLi.textContent = `Error fetching lyrics: ${error.message}`;
            DOM.geniusLyricsList.appendChild(errorLi);

            const noGeniusLiOnError = createLyricOptionItem("Use Original Transcription", null, "Use the text directly recognized by the AI model.");
            DOM.geniusLyricsList.insertBefore(noGeniusLiOnError, DOM.geniusLyricsList.firstChild);
            setTimeout(() => noGeniusLiOnError.click(), 50);
        }
    } finally {
        if (geniusFetchAbortController && geniusFetchAbortController.signal === signal) {
            geniusFetchAbortController = null;
        }
    }
}

function createLyricOptionItem(text, lyricsData, titleAttr) {
    const li = document.createElement('li');
    li.textContent = text;
    li.style.cursor = 'pointer';
    li.title = titleAttr;
    li.setAttribute('role', 'option');
    li.tabIndex = 0;

    if (lyricsData !== null) {
        li.dataset.lyrics = lyricsData;
    }

    li.addEventListener('click', (e) => {
        window.selectedGeniusLyrics = li.dataset.lyrics || null;
        highlightSelectedLyric(li);
        const lyricsPanel = document.getElementById("lyrics-panel");
        const toggleBtn = document.getElementById("lyrics-toggle-btn");
        const txtArea = DOM.geniusSelectedText;

        if (!txtArea) { return; }

        if (window.selectedGeniusLyrics === null) {
            if (lyricsPanel) lyricsPanel.classList.add('hidden');
            if (toggleBtn) { toggleBtn.setAttribute("aria-expanded", "false"); toggleBtn.classList.remove('expanded'); }
            txtArea.value = "";
        } else {
            if (lyricsPanel) lyricsPanel.classList.remove('hidden');
            if (toggleBtn) { toggleBtn.setAttribute("aria-expanded", "true"); toggleBtn.classList.add('expanded'); }
            txtArea.value = window.selectedGeniusLyrics;
        }
    });

    li.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            li.click();
        }
    });
    return li;
}

function highlightSelectedLyric(selectedLi) {
    if (!DOM.geniusLyricsList) return;
    const allLis = DOM.geniusLyricsList.querySelectorAll(":scope > li[role='option']");
    allLis.forEach(li => {
        li.classList.remove("selected-lyric");
        li.setAttribute("aria-selected", "false");
    });
    if (selectedLi) {
        selectedLi.classList.add("selected-lyric");
        selectedLi.setAttribute("aria-selected", "true");
    }
}