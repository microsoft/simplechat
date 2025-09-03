// Dark Mode Functionality
const USER_SETTINGS_KEY_DARK_MODE = 'darkModeEnabled';
const LOCAL_STORAGE_THEME_KEY = 'simplechat-theme';

// DOM Elements
const htmlRoot = document.getElementById('htmlRoot');

// Support multiple dark mode toggles (top nav, sidebar, etc)
function getAllDarkModeToggles() {
  return Array.from(document.querySelectorAll('.dark-mode-toggle'));
}

function getToggleParts(toggle) {
  return {
    lightText: toggle.querySelector('#topNavSwitchToLightText, #sidebarSwitchToLightText'),
    darkText: toggle.querySelector('#topNavSwitchToDarkText, #sidebarSwitchToDarkText')
  };
}

// Save dark mode setting to API
async function saveDarkModeSetting(settingsToUpdate) {
    try {
        const response = await fetch('/api/user/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ settings: settingsToUpdate }),
        });
        if (!response.ok) {
            console.error('Failed to save dark mode setting:', response.statusText);
        } else {
            console.log('Dark mode setting saved successfully');
        }
    } catch (error) {
        console.error('Error saving dark mode setting:', error);
    }
}

// Function to toggle dark mode
function toggleDarkMode(e) {
    e && e.preventDefault && e.preventDefault();
    const currentTheme = htmlRoot.getAttribute('data-bs-theme');
    const isDarkMode = currentTheme === 'dark';
    const newMode = isDarkMode ? 'light' : 'dark';

    // Debug: log toggle
    console.log('Toggling dark mode. Current:', currentTheme, 'New:', newMode);

    // Update the theme
    setThemeMode(newMode);

    // Save the preference to localStorage and API
    localStorage.setItem(LOCAL_STORAGE_THEME_KEY, newMode);
    saveDarkModeSetting({ [USER_SETTINGS_KEY_DARK_MODE]: newMode === 'dark' });
}

// Apply theme mode and update UI
function setThemeMode(mode) {
    // Update the theme attribute
    if (htmlRoot) {
        htmlRoot.setAttribute('data-bs-theme', mode);
    }

    // Update all toggles' icons and text
    getAllDarkModeToggles().forEach(toggle => {
        const { lightText, darkText } = getToggleParts(toggle);
        if (mode === 'dark') {
            // In dark mode, show "Light Mode" (to switch back to light), hide "Dark Mode"
            if (lightText) lightText.classList.remove('d-none');
            if (darkText) darkText.classList.add('d-none');
        } else {
            // In light mode, show "Dark Mode" (to switch to dark), hide "Light Mode"
            if (lightText) lightText.classList.add('d-none');
            if (darkText) darkText.classList.remove('d-none');
        }
        // Always ensure the toggle itself is visible
        if (toggle && toggle.classList) toggle.classList.remove('d-none');
    });
}

// Load dark mode preference
async function loadDarkModePreference() {
    try {
        // Check for localStorage theme first (already applied in head for fast loading)
        let localTheme = localStorage.getItem(LOCAL_STORAGE_THEME_KEY);
        
        // Default from app settings if no localStorage
        if (!localTheme && typeof appSettings !== 'undefined' && appSettings.enable_dark_mode_default) {
            localTheme = 'dark';
        }
        
        // Sync with server - which may override localStorage if user has multiple devices
        const response = await fetch('/api/user/settings');
        if (response.ok) {
            const data = await response.json();
            const settings = data.settings || {};
            
            // If user has a saved preference in their account, use it and update localStorage
            if (USER_SETTINGS_KEY_DARK_MODE in settings) {
                const serverTheme = settings[USER_SETTINGS_KEY_DARK_MODE] === true ? 'dark' : 'light';
                
                // Update localStorage if server setting differs
                if (!localTheme || serverTheme !== localTheme) {
                    localStorage.setItem(LOCAL_STORAGE_THEME_KEY, serverTheme);
                    localTheme = serverTheme;
                }
            }
        }
        
        // Apply the theme if we have one from any source (should already be applied, but this ensures UI is consistent)
        if (localTheme) {
            setThemeMode(localTheme);
        }
    } catch (error) {
        console.error('Error loading dark mode preference:', error);
    }
}

// Initialize dark mode
document.addEventListener('DOMContentLoaded', () => {
    // Add click event listeners to all dark mode toggles
    getAllDarkModeToggles().forEach(toggle => {
        toggle.addEventListener('click', toggleDarkMode);
    });
    
    // Load user preference (to sync with server)
    loadDarkModePreference();
    
    // Ensure UI is in sync on load
    const currentTheme = localStorage.getItem(LOCAL_STORAGE_THEME_KEY) || 
                        (typeof appSettings !== 'undefined' && appSettings.enable_dark_mode_default ? 'dark' : 'light');
    setThemeMode(currentTheme);
});

// Export functions for use in other modules if needed
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        toggleDarkMode,
        setThemeMode,
        loadDarkModePreference,
        getAllDarkModeToggles,
        getToggleParts,
        saveDarkModeSetting
    };
}