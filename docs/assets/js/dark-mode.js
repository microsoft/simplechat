/**
 * Dark Mode Toggle Functionality
 * Handles theme switching between light and dark modes
 */

(function() {
  'use strict';

  // Theme constants
  const THEME_KEY = 'simplechat-theme';
  const THEMES = {
    LIGHT: 'light',
    DARK: 'dark'
  };

  // Get current theme
  function getCurrentTheme() {
    return localStorage.getItem(THEME_KEY) || THEMES.LIGHT;
  }

  // Set theme
  function setTheme(theme) {
    document.documentElement.setAttribute('data-bs-theme', theme);
    localStorage.setItem(THEME_KEY, theme);
    
    // Update toggle buttons text/icons
    updateToggleButtons(theme);
    
    // Trigger custom event for other components
    document.dispatchEvent(new CustomEvent('themeChanged', { detail: { theme } }));
  }

  // Update toggle button states
  function updateToggleButtons(theme) {
    const toggles = document.querySelectorAll('.dark-mode-toggle');
    toggles.forEach(toggle => {
      const lightElements = toggle.querySelectorAll('.d-light-mode-only');
      const darkElements = toggle.querySelectorAll('.d-dark-mode-only');
      
      if (theme === THEMES.DARK) {
        lightElements.forEach(el => el.style.display = 'none');
        darkElements.forEach(el => el.style.display = 'inline');
      } else {
        lightElements.forEach(el => el.style.display = 'inline');
        darkElements.forEach(el => el.style.display = 'none');
      }
    });
  }

  // Toggle theme
  function toggleTheme() {
    const currentTheme = getCurrentTheme();
    const newTheme = currentTheme === THEMES.LIGHT ? THEMES.DARK : THEMES.LIGHT;
    setTheme(newTheme);
  }

  // Initialize theme on page load
  function initTheme() {
    const savedTheme = getCurrentTheme();
    setTheme(savedTheme);
  }

  // Set up event listeners
  function setupEventListeners() {
    // Handle toggle button clicks
    document.addEventListener('click', function(e) {
      if (e.target.closest('.dark-mode-toggle')) {
        e.preventDefault();
        toggleTheme();
      }
    });

    // Handle keyboard shortcuts (Ctrl/Cmd + Shift + L)
    document.addEventListener('keydown', function(e) {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'L') {
        e.preventDefault();
        toggleTheme();
      }
    });
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      initTheme();
      setupEventListeners();
    });
  } else {
    initTheme();
    setupEventListeners();
  }

  // Expose utilities globally
  window.SimpleChat = window.SimpleChat || {};
  window.SimpleChat.Theme = {
    getCurrentTheme,
    setTheme,
    toggleTheme,
    THEMES
  };

})();