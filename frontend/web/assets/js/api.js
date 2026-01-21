// File: frontend/web/assets/js/api.js
/**
 * Functions for interacting with the backend API.
 * UPDATED (v3): Added final_font_size parameter.
 */

export const API_SUGGESTIONS = '/api/suggestions';
export const API_PROCESS = '/api/process';
export const API_CANCEL_JOB = '/api/cancel_job';
export const API_GENIUS_CANDIDATES = '/api/genius_candidates';

/** Fetches video suggestions from the backend. */
export async function fetchSuggestions(query, signal) {
    // console.log(`[API] Fetching suggestions for query: ${query}`);
    try {
        const params = new URLSearchParams({ q: query });
        const response = await fetch(`${API_SUGGESTIONS}?${params.toString()}`, { signal });

        if (!response.ok) {
            throw new Error(`HTTP error ${response.status} fetching suggestions`);
        }
        const suggestions = await response.json();
        // console.log(`[API] Received ${suggestions?.length ?? 0} suggestions.`);
        return suggestions;
    } catch (error) {
        if (error.name === 'AbortError') {
            console.log("[API] Suggestion fetch aborted by user or new request.");
            return null; // Indicate abortion without throwing error
        }
        console.error("[API] Failed to fetch suggestions:", error);
        throw error; // Re-throw other errors
    }
}

export async function startProcessingJob(
    urlOrSearch,
    language,
    position,
    generateSubs,
    customLyrics,
    globalPitch,
    finalFontSize
) {
    const body = {
        url: urlOrSearch,
        language,
        subtitle_position: position,
        generate_subtitles: !!generateSubs,
        custom_lyrics: customLyrics,
        global_pitch: globalPitch || null,  // New: global pitch instead of pitch_shifts
        final_subtitle_size: parseInt(finalFontSize, 10) || 30
    }
    const r = await fetch(API_PROCESS, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const j = await r.json()
    if (!j || !j.job_id) throw new Error('Invalid response')
    return j.job_id
}

export async function cancelJob(jobId, signal) {
    const r = await fetch(`${API_CANCEL_JOB}?job_id=${encodeURIComponent(jobId)}`, {
        method: 'POST',
        signal
    })
    if (!r.ok) throw new Error(`Cancel failed ${r.status}`)
    return r.json()
}
/** Sends a request to cancel a job using the Beacon API (best effort). */
export function cancelJobBeacon(jobId) {
    if (!jobId) {
        console.warn("[API] cancelJobBeacon called without a valid jobId.");
        return;
    }
    try {
        const beaconUrl = `${API_CANCEL_JOB}?job_id=${encodeURIComponent(jobId)}`;
        // Use GET for beacon as body might not be reliable
        if (navigator.sendBeacon && navigator.sendBeacon(beaconUrl)) {
            console.log(`[API] Sent cancellation request for job ${jobId} via Beacon API.`);
        } else {
            console.warn("[API] navigator.sendBeacon not supported or failed. Cancellation may not register on unload.");
            // Fallback: Try a sync XHR if beacon fails? (Generally discouraged)
        }
    } catch (e) {
        console.error("[API] Error attempting to send cancel beacon:", e);
    }
}

/** Fetches Genius lyrics candidates from the backend. */
export async function fetchGeniusCandidates(title, artist = "", signal) {
    console.log(`[API] Fetching Genius candidates for Title: "${title}", Artist: "${artist}"`);
    try {
        const params = new URLSearchParams({ title });
        if (artist) {
            params.append('artist', artist);
        }
        const response = await fetch(`${API_GENIUS_CANDIDATES}?${params.toString()}`, { signal });

        if (!response.ok) {
            let errorMsg = `Error ${response.status}`;
            try {
                const errData = await response.json();
                errorMsg = errData?.detail || `${errorMsg}: ${response.statusText}`;
            } catch (e) { errorMsg = `${errorMsg}: ${response.statusText}`; }
            throw new Error(`Failed to fetch Genius candidates. ${errorMsg}`);
        }
        const candidates = await response.json();
        console.log(`[API] Received ${candidates?.length ?? 0} Genius candidates.`);
        return candidates;

    } catch (error) {
        if (error.name === 'AbortError') {
            console.log("[API] Genius candidates fetch aborted.");
            return null; // Indicate abortion
        }
        console.error("[API] Failed to fetch Genius candidates:", error);
        throw error; // Re-throw other errors
    }
}