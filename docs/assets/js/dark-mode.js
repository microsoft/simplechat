// dark-mode.js
/**
 * Light and dark theme switching for the documentation site.
 */

(function() {
    "use strict";

    const THEME_KEY = "simplechat-theme";
    const THEMES = {
        LIGHT: "light",
        DARK: "dark"
    };

    function getCurrentTheme() {
        return localStorage.getItem(THEME_KEY) || THEMES.LIGHT;
    }

    function updateToggleButtons(theme) {
        const toggles = document.querySelectorAll(".dark-mode-toggle");
        const isDark = theme === THEMES.DARK;

        toggles.forEach(function(toggle) {
            toggle.classList.toggle("is-dark", isDark);
            toggle.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
        });
    }

    function setTheme(theme) {
        document.documentElement.setAttribute("data-bs-theme", theme);
        localStorage.setItem(THEME_KEY, theme);
        updateToggleButtons(theme);
        document.dispatchEvent(new CustomEvent("themeChanged", { detail: { theme } }));
    }

    function toggleTheme() {
        const currentTheme = getCurrentTheme();
        const newTheme = currentTheme === THEMES.LIGHT ? THEMES.DARK : THEMES.LIGHT;
        setTheme(newTheme);
    }

    function initTheme() {
        setTheme(getCurrentTheme());
    }

    function setupEventListeners() {
        document.addEventListener("click", function(event) {
            if (event.target.closest(".dark-mode-toggle")) {
                event.preventDefault();
                toggleTheme();
            }
        });

        document.addEventListener("keydown", function(event) {
            if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key === "L") {
                event.preventDefault();
                toggleTheme();
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function() {
            initTheme();
            setupEventListeners();
        });
    } else {
        initTheme();
        setupEventListeners();
    }

    window.SimpleChat = window.SimpleChat || {};
    window.SimpleChat.Theme = {
        getCurrentTheme,
        setTheme,
        toggleTheme,
        THEMES
    };
})();