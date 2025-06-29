// static/js/chat/chat-layout.js

// Constants for user settings keys
const USER_SETTINGS_KEY_LAYOUT = 'chatLayout';
const USER_SETTINGS_KEY_SPLIT = 'chatSplitSizes';

// DOM elements
const leftPane = document.getElementById('left-pane');
const rightPane = document.getElementById('right-pane');
const dockToggleButton = document.getElementById('dock-toggle-btn');
const splitContainer = document.getElementById('split-container'); // Might not be needed directly if targeting body

// Track current layout state
let currentLayout = 'split'; // Default to split view
let currentSplitSizes = [25, 75]; // Default split sizes [left, right]
let splitInstance = null; // Will hold the Split.js instance

// --- API Function for User Settings ---
export async function saveUserSetting(settingsToUpdate) {


    try {
        const response = await fetch('/api/user/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ settings: settingsToUpdate }), // Send nested structure
        });
        if (!response.ok) {
            console.error('Failed to save user settings:', response.statusText);
            const errorData = await response.json().catch(() => ({})); // Try to get error details
            console.error('Error details:', errorData);
             // Fallback to localStorage on API failure?
            // localStorage.setItem(key, JSON.stringify(value));
        } else {
            console.log('User settings saved successfully via API for:', Object.keys(settingsToUpdate));
        }
    } catch (error) {
        console.error('Error calling save settings API:', error);
         // Fallback to localStorage on network error?
        // localStorage.setItem(key, JSON.stringify(value));
    }
}

export async function loadUserSettings() {
    let settings = {};

    try {
        const response = await fetch('/api/user/settings');
        if (response.ok) {
            const data = await response.json();
            settings = data.settings || {}; // Expect settings under a 'settings' key
            console.log('User settings loaded via API:', settings);
        } else {
            console.warn('Failed to load user settings via API:', response.statusText);
            // Optionally fallback to localStorage here too
        }
    } catch (error) {
        console.error('Error fetching user settings:', error);
            // Optionally fallback to localStorage here too
    }

    // Apply loaded settings
    currentLayout = settings[USER_SETTINGS_KEY_LAYOUT] || 'split'; // Default to 'split'
    currentSplitSizes = settings[USER_SETTINGS_KEY_SPLIT] || [25, 75]; // Default sizes

    console.log(`Applying initial layout: ${currentLayout}, sizes: ${currentSplitSizes}`);
    applyLayout(currentLayout, false); // Apply layout without saving again
    
    // Return the settings object so it can be used by other components
    return settings;
}


// --- Split.js Initialization ---
function initializeSplit() {
    if (splitInstance) {
        splitInstance.destroy(); // Destroy existing instance if any
        splitInstance = null;
        console.log('Split.js instance destroyed.');
    }

    console.log('Initializing Split.js with sizes:', currentSplitSizes);
    splitInstance = Split(['#left-pane', '#right-pane'], {
        sizes: currentSplitSizes, // Use potentially loaded sizes
        minSize: [200, 350], // Min width in pixels [left, right] - adjust as needed
        gutterSize: 8, // Width of the draggable gutter
        cursor: 'col-resize',
        direction: 'horizontal',
        onDragEnd: function(sizes) {
            console.log('Split drag ended. New sizes:', sizes);
            currentSplitSizes = sizes; // Update current sizes
            // Debounce saving split sizes to avoid rapid API calls
            debounceSaveSplitSizes(sizes);
        },
        elementStyle: (dimension, size, gutterSize) => ({
            // Use flex-basis for sizing to work well with flex container
            'flex-basis': `calc(${size}% - ${gutterSize}px)`,
        }),
        gutterStyle: (dimension, gutterSize) => ({
            'flex-basis': `${gutterSize}px`,
        }),
    });
    console.log('Split.js initialized.');
}

// Debounce function
let debounceTimer;
function debounceSaveSplitSizes(sizes) {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
         saveUserSetting({ [USER_SETTINGS_KEY_SPLIT]: sizes });
    }, 500); // Save 500ms after dragging stops
}

// --- Layout Switching Logic ---
function applyLayout(layout, shouldSave = true) {
    currentLayout = layout; // Update global state

    // Remove previous layout classes
    document.body.classList.remove('layout-split', 'layout-docked', 'left-pane-hidden');

    if (layout === 'docked') {
        console.log('Applying docked layout.');
        document.body.classList.add('layout-docked');
        if (splitInstance) {
            currentSplitSizes = splitInstance.getSizes(); // Save sizes before destroying
            splitInstance.destroy();
            splitInstance = null;
            console.log('Split.js instance destroyed for docking.');
        }
         // Ensure panes have correct styles applied by CSS (.layout-docked)
        leftPane.style.width = ''; // Let CSS handle width
        leftPane.style.flexBasis = ''; // Remove split.js style
        rightPane.style.marginLeft = ''; // Let CSS handle margin
         rightPane.style.width = ''; // Let CSS handle width
        rightPane.style.flexBasis = ''; // Remove split.js style

    } else { // 'split' layout
        console.log('Applying split layout.');
        document.body.classList.add('layout-split'); // Use a class for split state too? Optional.
        // Re-initialize Split.js if it's not already running
        if (!splitInstance) {
             initializeSplit();
        }
        // Remove fixed positioning styles if they were somehow manually added
        leftPane.style.position = '';
        leftPane.style.top = '';
        leftPane.style.left = '';
        leftPane.style.height = '';
        leftPane.style.zIndex = '';
        rightPane.style.marginLeft = '';
        rightPane.style.width = '';
    }

    // Update toggle button icon/title
    updateDockToggleButton();

    // Save the new layout preference
    if (shouldSave) {
        saveUserSetting({ [USER_SETTINGS_KEY_LAYOUT]: layout });
    }
}

function toggleDocking() {
    const nextLayout = currentLayout === 'split' ? 'docked' : 'split';
    applyLayout(nextLayout, true); // Apply and save
}

// Maybe add a function to toggle the docked sidebar visibility
function toggleDockedSidebarVisibility() {
    if (currentLayout === 'docked') {
        document.body.classList.toggle('left-pane-hidden');
        const isHidden = document.body.classList.contains('left-pane-hidden');
        saveUserSetting({ 'dockedSidebarHidden': isHidden }); // Save visibility state if needed
         updateDockToggleButton(); // Update icon maybe
    }
}

function updateDockToggleButton() {
    const icon = dockToggleButton.querySelector('i');
    if (!icon) return; // Add safety check

    if (currentLayout === 'docked') {
       icon.classList.remove('bi-layout-sidebar-inset');
       icon.classList.add('bi-layout-sidebar-inset-reverse');
       dockToggleButton.title = "Undock Sidebar (Split View)";
       // NO MORE onclick assignment here
       // If you need the hide/show functionality, you might need a separate button
       // or add logic within the main toggleDocking based on state,
       // but avoid direct onclick reassignment here.

    } else { // 'split' layout
        icon.classList.remove('bi-layout-sidebar-inset-reverse');
        icon.classList.add('bi-layout-sidebar-inset');
        dockToggleButton.title = "Dock Sidebar Left";
        // NO MORE onclick assignment here either
    }
}


// --- Event Listeners ---
if (dockToggleButton) {
    dockToggleButton.addEventListener('click', toggleDocking);
} else {
    console.error('Dock toggle button not found.');
}

// --- Initial Load ---
document.addEventListener('DOMContentLoaded', () => {
    loadUserSettings(); // Load settings and apply initial layout
});