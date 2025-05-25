// Dark mode functionality
const USER_SETTINGS_KEY_DARK_MODE = 'darkModeEnabled';
const LOCAL_STORAGE_THEME_KEY = 'simplechat-theme';

// DOM Elements
const darkModeToggle = document.getElementById('darkModeToggle');
const lightModeIcon = document.getElementById('lightModeIcon');
const darkModeIcon = document.getElementById('darkModeIcon');
const lightModeContainer = lightModeIcon ? lightModeIcon.parentElement : null;
const darkModeContainer = darkModeIcon ? darkModeIcon.parentElement : null;
const htmlRoot = document.getElementById('htmlRoot');

// Save user setting to API
async function saveUserSetting(settingsToUpdate) {
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
function toggleDarkMode() {
    const isDarkMode = htmlRoot.getAttribute('data-bs-theme') === 'dark';
    const newMode = isDarkMode ? 'light' : 'dark';
    
    // Update the theme
    setThemeMode(newMode);
    
    // Save the preference to localStorage and API
    localStorage.setItem(LOCAL_STORAGE_THEME_KEY, newMode);
    saveUserSetting({ [USER_SETTINGS_KEY_DARK_MODE]: newMode === 'dark' });
}

// Apply theme mode and update UI
function setThemeMode(mode) {
    // Update the theme attribute
    if (htmlRoot) {
        htmlRoot.setAttribute('data-bs-theme', mode);
    }
    
    // Update icons and text if they exist
    if (lightModeContainer && darkModeContainer) {
        if (mode === 'dark') {
            lightModeContainer.classList.add('d-none');
            darkModeContainer.classList.remove('d-none');
        } else {
            lightModeContainer.classList.remove('d-none');
            darkModeContainer.classList.add('d-none');
        }
    }
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
    if (darkModeToggle) {
        // Add click event listener to toggle
        darkModeToggle.addEventListener('click', toggleDarkMode);
        
        // Load user preference (to sync with server)
        loadDarkModePreference();
    }
});