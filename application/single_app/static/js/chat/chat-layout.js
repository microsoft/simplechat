// static/js/chat/chat-layout.js

// Sidebar is always docked: remove all toggle, split, and user settings logic

// DOM elements
const leftPane = document.getElementById('left-pane');
const rightPane = document.getElementById('right-pane');

// Layout initialization is now handled in base.html to prevent shifting
// No need for DOMContentLoaded listener here since early initialization prevents the issue

// Remove Split.js, toggle, and user settings logic entirely

// If any other modules import setSplitContainerMode, keep it as a no-op for compatibility
export function setSplitContainerMode(isSplit) {
  // No-op: always fluid, always docked
}

// Load user settings from API
export async function loadUserSettings() {
    try {
        const response = await fetch('/api/user/settings');
        if (!response.ok) {
            console.warn('Failed to load user settings via API:', response.statusText);
            return {};
        }
        const data = await response.json();
        const settings = data && data.settings ? data.settings : {};
        console.log('User settings loaded via API:', settings);
        return settings;
    } catch (error) {
        console.error('Error fetching user settings:', error);
        return {};
    }
}

// Save individual user setting
export function saveUserSetting(settingUpdate) {
    if (!settingUpdate || typeof settingUpdate !== 'object') {
        console.warn('Cannot save user setting: invalid setting update provided');
        return;
    }

    // First, load current settings, then merge and save
    fetch('/api/user/settings')
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            // Get current settings or initialize empty object
            const currentSettings = data && data.settings ? data.settings : {};
            
            // Merge the new setting(s) with existing settings
            const updatedSettings = { ...currentSettings, ...settingUpdate };
            
            // Save the updated settings
            return fetch('/api/user/settings', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'same-origin',
                body: JSON.stringify({ settings: updatedSettings })
            });
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            console.log('User setting saved successfully:', settingUpdate);
        })
        .catch(error => {
            console.error('Failed to save user setting:', error);
            // Graceful degradation - continue without saving
        });
}