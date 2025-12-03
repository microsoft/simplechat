// chat-reasoning.js
import { loadUserSettings, saveUserSetting } from './chat-layout.js';
import { showToast } from './chat-toast.js';

let reasoningEffortSettings = {}; // Per-model settings: {modelName: 'low', ...}

/**
 * Initialize the reasoning effort toggle button
 */
export function initializeReasoningToggle() {
    const reasoningToggleBtn = document.getElementById('reasoning-toggle-btn');
    if (!reasoningToggleBtn) {
        console.warn('Reasoning toggle button not found');
        return;
    }
    
    console.log('Initializing reasoning toggle...');
    
    // Load initial state from user settings
    loadUserSettings().then(settings => {
        console.log('Loaded reasoning settings:', settings);
        reasoningEffortSettings = settings.reasoningEffortSettings || {};
        console.log('Reasoning effort settings:', reasoningEffortSettings);
        
        // Update icon based on current model
        updateReasoningIconForCurrentModel();
    }).catch(error => {
        console.error('Error loading reasoning settings:', error);
    });
    
    // Handle toggle click - show slider modal
    reasoningToggleBtn.addEventListener('click', () => {
        showReasoningSlider();
    });
    
    // Listen for model changes
    const modelSelect = document.getElementById('model-select');
    if (modelSelect) {
        modelSelect.addEventListener('change', () => {
            updateReasoningIconForCurrentModel();
            updateReasoningButtonVisibility();
        });
    }
    
    // Listen for image generation toggle - hide reasoning button when image gen is active
    const imageGenBtn = document.getElementById('image-generate-btn');
    if (imageGenBtn) {
        const observer = new MutationObserver(() => {
            updateReasoningButtonVisibility();
        });
        observer.observe(imageGenBtn, { attributes: true, attributeFilter: ['class'] });
    }
    
    // Listen for agents toggle - hide reasoning button when agents are active
    const enableAgentsBtn = document.getElementById('enable-agents-btn');
    if (enableAgentsBtn) {
        const observer = new MutationObserver(() => {
            updateReasoningButtonVisibility();
        });
        observer.observe(enableAgentsBtn, { attributes: true, attributeFilter: ['class'] });
    }
    
    updateReasoningButtonVisibility();
}

/**
 * Update reasoning button visibility based on image generation state, agent state, and model support
 */
function updateReasoningButtonVisibility() {
    const reasoningToggleBtn = document.getElementById('reasoning-toggle-btn');
    const imageGenBtn = document.getElementById('image-generate-btn');
    const enableAgentsBtn = document.getElementById('enable-agents-btn');
    
    if (!reasoningToggleBtn) return;
    
    // Hide reasoning button when image generation is active
    if (imageGenBtn && imageGenBtn.classList.contains('active')) {
        reasoningToggleBtn.style.display = 'none';
        return;
    }
    
    // Hide reasoning button when agents are active
    if (enableAgentsBtn && enableAgentsBtn.classList.contains('active')) {
        reasoningToggleBtn.style.display = 'none';
        return;
    }
    
    // Hide reasoning button if current model doesn't support reasoning
    const modelName = getCurrentModelName();
    if (modelName) {
        const supportedLevels = getModelSupportedLevels(modelName);
        // If model only supports 'none', hide the button
        if (supportedLevels.length === 1 && supportedLevels[0] === 'none') {
            reasoningToggleBtn.style.display = 'none';
            return;
        }
    }
    
    // Otherwise show the button
    reasoningToggleBtn.style.display = 'flex';
}

/**
 * Get the current model name from the model selector
 */
function getCurrentModelName() {
    const modelSelect = document.getElementById('model-select');
    if (!modelSelect || !modelSelect.value) {
        return null;
    }
    return modelSelect.value;
}

/**
 * Determine which reasoning effort levels are supported by a given model
 * @param {string} modelName - The name of the model
 * @returns {Array<string>} Array of supported effort levels
 */
export function getModelSupportedLevels(modelName) {
    if (!modelName) {
        return ['none', 'minimal', 'low', 'medium', 'high'];
    }
    
    const lowerModelName = modelName.toLowerCase();
    
    // Models without reasoning support: gpt-4o, gpt-4.1, gpt-4.1-mini, gpt-5-chat, gpt-5-codex
    if (lowerModelName.includes('gpt-4o') || 
        lowerModelName.includes('gpt-4.1') || 
        lowerModelName.includes('gpt-5-chat') || 
        lowerModelName.includes('gpt-5-codex')) {
        return ['none'];
    }
    
    // gpt-5-pro: high only
    if (lowerModelName.includes('gpt-5-pro')) {
        return ['high'];
    }
    
    // gpt-5.1 series: none, minimal, medium, high (skip low/2 bars)
    if (lowerModelName.includes('gpt-5.1')) {
        return ['none', 'minimal', 'medium', 'high'];
    }
    
    // gpt-5 series (but not 5.1, 5-pro, 5-chat, or 5-codex): minimal, low, medium, high
    // Includes: gpt-5, gpt-5-nano, gpt-5-mini
    if (lowerModelName.includes('gpt-5')) {
        return ['minimal', 'low', 'medium', 'high'];
    }
    
    // o-series (o1, o3, etc): low, medium, high
    if (lowerModelName.match(/\bo[0-9]/)) {
        return ['low', 'medium', 'high'];
    }
    
    // Default: all levels
    return ['none', 'minimal', 'low', 'medium', 'high'];
}

/**
 * Get the reasoning effort level for the current model
 * @returns {string} The effort level (none, minimal, low, medium, high)
 */
export function getCurrentModelReasoningEffort() {
    const modelName = getCurrentModelName();
    if (!modelName) {
        return 'low'; // Default
    }
    
    const supportedLevels = getModelSupportedLevels(modelName);
    const savedEffort = reasoningEffortSettings[modelName];
    
    // If gpt-5-pro, always return high
    if (modelName.toLowerCase().includes('gpt-5-pro')) {
        return 'high';
    }
    
    // If saved effort exists and is supported, use it
    if (savedEffort && supportedLevels.includes(savedEffort)) {
        return savedEffort;
    }
    
    // Default to 'low' if supported, otherwise first supported level
    if (supportedLevels.includes('low')) {
        return 'low';
    }
    
    return supportedLevels[0];
}

/**
 * Update the reasoning icon based on the current model's saved effort
 */
function updateReasoningIconForCurrentModel() {
    const effort = getCurrentModelReasoningEffort();
    updateReasoningIcon(effort);
}

/**
 * Update the reasoning toggle button icon based on effort level
 * @param {string} level - The effort level (none, minimal, low, medium, high)
 */
export function updateReasoningIcon(level) {
    const reasoningToggleBtn = document.getElementById('reasoning-toggle-btn');
    if (!reasoningToggleBtn) return;
    
    const iconElement = reasoningToggleBtn.querySelector('i');
    if (!iconElement) return;
    
    // Map effort levels to Bootstrap Icons signal strength
    const iconMap = {
        'none': 'bi-reception-0',
        'minimal': 'bi-reception-1',
        'low': 'bi-reception-2',
        'medium': 'bi-reception-3',
        'high': 'bi-reception-4'
    };
    
    // Remove all reception classes
    iconElement.className = '';
    
    // Add the appropriate icon class
    const iconClass = iconMap[level] || 'bi-reception-2';
    iconElement.classList.add('bi', iconClass);
    
    // Update tooltip
    const labelMap = {
        'none': 'No reasoning effort',
        'minimal': 'Minimal reasoning effort',
        'low': 'Low reasoning effort',
        'medium': 'Medium reasoning effort',
        'high': 'High reasoning effort'
    };
    reasoningToggleBtn.title = labelMap[level] || 'Configure reasoning effort';
}

/**
 * Show the reasoning effort slider modal
 */
export function showReasoningSlider() {
    const modelName = getCurrentModelName();
    if (!modelName) {
        showToast('Please select a model first', 'warning');
        return;
    }
    
    const modal = new bootstrap.Modal(document.getElementById('reasoning-slider-modal'));
    const modelNameElement = document.getElementById('reasoning-model-name');
    const levelsContainer = document.querySelector('.reasoning-levels');
    
    if (!modelNameElement || !levelsContainer) {
        console.error('Reasoning modal elements not found');
        return;
    }
    
    // Set model name
    modelNameElement.textContent = modelName;
    
    // Get supported levels and current effort
    const supportedLevels = getModelSupportedLevels(modelName);
    const currentEffort = getCurrentModelReasoningEffort();
    
    // All possible levels in order (for display from bottom to top)
    const allLevels = ['none', 'minimal', 'low', 'medium', 'high'];
    const levelLabels = {
        'none': 'None',
        'minimal': 'Minimal',
        'low': 'Low',
        'medium': 'Medium',
        'high': 'High'
    };
    const levelIcons = {
        'none': 'bi-reception-0',
        'minimal': 'bi-reception-1',
        'low': 'bi-reception-2',
        'medium': 'bi-reception-3',
        'high': 'bi-reception-4'
    };
    const levelDescriptions = {
        'none': 'No additional reasoning - fastest responses, suitable for simple questions',
        'minimal': 'Light reasoning - quick responses with basic logical steps',
        'low': 'Moderate reasoning - balanced speed and thoughtfulness for everyday questions',
        'medium': 'Enhanced reasoning - more deliberate thinking for complex questions',
        'high': 'Maximum reasoning - deepest analysis for challenging problems and nuanced topics'
    };
    
    // Build level buttons (reversed for bottom-to-top display)
    levelsContainer.innerHTML = '';
    allLevels.forEach(level => {
        const isSupported = supportedLevels.includes(level);
        const isActive = level === currentEffort;
        
        const levelDiv = document.createElement('div');
        levelDiv.className = `reasoning-level ${isActive ? 'active' : ''} ${!isSupported ? 'disabled' : ''}`;
        levelDiv.dataset.level = level;
        levelDiv.title = levelDescriptions[level];
        
        levelDiv.innerHTML = `
            <div class="reasoning-level-icon">
                <i class="bi ${levelIcons[level]}"></i>
            </div>
            <div class="reasoning-level-label">${levelLabels[level]}</div>
        `;
        
        if (isSupported) {
            levelDiv.addEventListener('click', () => {
                selectReasoningLevel(level, modelName);
            });
        }
        
        levelsContainer.appendChild(levelDiv);
    });
    
    modal.show();
}

/**
 * Handle selection of a reasoning level
 * @param {string} level - The selected effort level
 * @param {string} modelName - The model name
 */
function selectReasoningLevel(level, modelName) {
    // Update the settings
    reasoningEffortSettings[modelName] = level;
    
    // Save to user settings
    saveReasoningEffort(modelName, level);
    
    // Update UI
    updateReasoningIcon(level);
    
    // Update active state in modal
    document.querySelectorAll('.reasoning-level').forEach(el => {
        el.classList.remove('active');
        if (el.dataset.level === level) {
            el.classList.add('active');
        }
    });
    
    // Show feedback
    const levelLabels = {
        'none': 'None',
        'minimal': 'Minimal',
        'low': 'Low',
        'medium': 'Medium',
        'high': 'High'
    };
    showToast(`Reasoning effort set to ${levelLabels[level]} for ${modelName}`, 'success');
    
    // Close modal after a short delay
    setTimeout(() => {
        const modal = bootstrap.Modal.getInstance(document.getElementById('reasoning-slider-modal'));
        if (modal) {
            modal.hide();
        }
    }, 500);
}

/**
 * Save the reasoning effort setting for a model
 * @param {string} modelName - The model name
 * @param {string} effort - The effort level
 */
export function saveReasoningEffort(modelName, effort) {
    reasoningEffortSettings[modelName] = effort;
    saveUserSetting({ reasoningEffortSettings });
}

/**
 * Check if reasoning effort is enabled for the current model
 * @returns {boolean} True if reasoning effort is enabled
 */
export function isReasoningEffortEnabled() {
    const effort = getCurrentModelReasoningEffort();
    return effort && effort !== 'none';
}

/**
 * Get the current reasoning effort to send to the backend
 * @returns {string|null} The effort level or null if 'none'
 */
export function getCurrentReasoningEffort() {
    const effort = getCurrentModelReasoningEffort();
    return effort === 'none' ? null : effort;
}
