// File: frontend/web/assets/js/theme.js
/**
 * Handles theme switching logic.
 */
import * as DOM from './dom.js';
import { getStemInstances } from './stems.js'; // Import stem instances to update cursor color

/** Initializes the theme based on localStorage. */
export function initTheme() {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'light') {
        document.body.classList.add('light-mode');
    } else {
        document.body.classList.remove('light-mode'); // Default to dark
    }
    updateThemeIcon();
    if (DOM.themeSwitcher) {
         DOM.themeSwitcher.addEventListener("click", toggleTheme);
    }
}

/** Toggles between light and dark mode. */
function toggleTheme() {
    const isLight = document.body.classList.toggle("light-mode");
    updateThemeIcon();
    localStorage.setItem('theme', isLight ? 'light' : 'dark');

    // Update WaveSurfer cursor color dynamically
    const computedStyle = getComputedStyle(document.body);
    const cursorColor = computedStyle.getPropertyValue('--wavesurfer-cursor').trim() || '#8a2be2';
    const stemInstances = getStemInstances(); // Get current instances
    stemInstances.forEach(ws => {
        if (ws) {
            try { ws.setCursorColor(cursorColor); } catch (e) { console.warn("Could not set cursor color on stem") }
        }
    });
}

/** Updates the theme switcher button icon and title. */
function updateThemeIcon() {
    if (!DOM.themeSwitcher) return;
    const iconSpan = DOM.themeSwitcher.querySelector('.icon');
    if (!iconSpan) return; // Ensure icon span exists
    if (document.body.classList.contains("light-mode")) {
        iconSpan.textContent = "🌙";
        DOM.themeSwitcher.title = "Switch to Dark Mode";
    } else {
        iconSpan.textContent = "☀️";
        DOM.themeSwitcher.title = "Switch to Light Mode";
    }
}