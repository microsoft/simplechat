// chat-reasoning.js
import { loadUserSettings, saveUserSetting } from './chat-layout.js';
import { showToast } from './chat-toast.js';

let reasoningEffortSettings = {}; // Per-model settings: {modelName: 'low', ...}
let settingsLoaded = false;
let pendingLevels = {};
const shownAdjustments = new Set();
const levelLabels = { none: 'None', minimal: 'Minimal', low: 'Low', medium: 'Medium', high: 'High', xhigh: 'XHigh' };

export function getMessageReasoningAdjustments(message, previous = []) {
    const latest = new Map();
    const entries = [
        ...(Array.isArray(previous) ? previous : []),
        ...(Array.isArray(message?.metadata?.reasoning_adjustments) ? message.metadata.reasoning_adjustments : []),
        ...(Array.isArray(message?.reasoning_adjustments) ? message.reasoning_adjustments : []),
    ];
    for (const entry of entries) {
        if (!entry || typeof entry !== 'object' ||
            !['explicit', 'model_default'].includes(entry.mode) ||
            !(entry.requested_effort === null || typeof entry.requested_effort === 'string') ||
            !(entry.effective_effort === null || typeof entry.effective_effort === 'string') ||
            !(entry.adjustment_reason === null || typeof entry.adjustment_reason === 'string')) {
            continue;
        }
        const stage = ['planner', 'answer'].includes(entry.stage) ? entry.stage : undefined;
        const modelName = typeof entry.model_name === 'string' ? entry.model_name : undefined;
        latest.set(JSON.stringify([stage, modelName]), {
            requested_effort: entry.requested_effort,
            effective_effort: entry.effective_effort,
            mode: entry.mode,
            adjustment_reason: entry.adjustment_reason,
            stage,
            model_name: modelName,
        });
    }
    return [...latest.values()];
}

export function renderMessageReasoningAdjustments(messageElement, adjustments) {
    const bubble = messageElement?.querySelector('.message-bubble');
    if (!bubble) return;
    const existing = bubble.querySelector('.reasoning-adjustment-notices');
    const messages = getMessageReasoningAdjustments({ reasoning_adjustments: adjustments })
        .filter((entry) => entry.adjustment_reason)
        .map((entry) => {
            const label = (effort) => levelLabels[effort] || (effort ? 'Saved effort' : 'Model default');
            const stage = entry.stage === 'planner' ? 'Planner: ' : entry.stage === 'answer' ? 'Answer: ' : '';
            const effective = entry.mode === 'model_default' ? 'Model default' : label(entry.effective_effort);
            const model = entry.model_name ? ` for ${entry.model_name}` : '';
            return `${stage}${label(entry.requested_effort)} could not be used${model}; using ${effective}.`;
        });
    if (!messages.length) {
        existing?.remove();
        return;
    }
    const signature = JSON.stringify(messages);
    if (existing?.dataset.reasoningSignature === signature) return;
    const notice = existing || document.createElement('div');
    notice.className = 'reasoning-adjustment-notices alert alert-warning py-2 small';
    notice.setAttribute('role', 'status');
    notice.setAttribute('aria-live', 'polite');
    notice.setAttribute('aria-atomic', 'true');
    notice.dataset.reasoningSignature = signature;
    notice.replaceChildren(...messages.map((message) => {
        const paragraph = document.createElement('p');
        paragraph.className = 'mb-0';
        paragraph.textContent = message;
        return paragraph;
    }));
    if (!existing) {
        const footer = bubble.querySelector('.message-footer');
        if (footer) footer.before(notice);
        else bubble.appendChild(notice);
    }
}

function setTooltipText(element, text, options = {}) {
    if (!element) {
        return;
    }

    if (typeof bootstrap === 'undefined' || !bootstrap.Tooltip) {
        element.title = text;
        return;
    }

    element.setAttribute('data-bs-toggle', 'tooltip');
    element.setAttribute('data-bs-title', text);
    element.setAttribute('data-bs-original-title', text);
    element.removeAttribute('title');

    if (options.placement) {
        element.setAttribute('data-bs-placement', options.placement);
    }

    if (options.trigger) {
        element.setAttribute('data-bs-trigger', options.trigger);
    }

    const tooltip = bootstrap.Tooltip.getOrCreateInstance(element, options);
    if (typeof tooltip.setContent === 'function') {
        tooltip.setContent({ '.tooltip-inner': text });
    }
}

function applyReasoningSettings(settings = {}) {
    reasoningEffortSettings = { ...(settings.reasoningEffortSettings || {}), ...pendingLevels };
    settingsLoaded = true;
    if (Object.keys(pendingLevels).length) {
        pendingLevels = {};
        saveUserSetting({ reasoningEffortSettings });
    }
    syncReasoningStateForCurrentModel();
}

/**
 * Initialize the reasoning effort toggle button
 */
export function initializeReasoningToggle(initialSettings = null) {
    const reasoningToggleBtn = document.getElementById('reasoning-toggle-btn');
    if (!reasoningToggleBtn) {
        console.warn('Reasoning toggle button not found');
        return;
    }
    
    console.log('Initializing reasoning toggle...');
    
    // Load initial state from user settings
    if (initialSettings) {
        applyReasoningSettings(initialSettings);
    } else {
        loadUserSettings().then(settings => {
            applyReasoningSettings(settings);
        }).catch(error => {
            console.error('Error loading reasoning settings:', error);
            syncReasoningStateForCurrentModel();
        });
    }
    
    // Handle toggle click - show slider modal
    reasoningToggleBtn.addEventListener('click', () => {
        showReasoningSlider();
    });
    
    // Listen for model changes
    const modelSelect = document.getElementById('model-select');
    if (modelSelect) {
        modelSelect.addEventListener('change', () => {
            syncReasoningStateForCurrentModel();
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

export function syncReasoningStateForCurrentModel() {
    updateReasoningIconForCurrentModel();
    updateReasoningButtonVisibility();
    const modelName = getCurrentModelName();
    const requested = reasoningEffortSettings[modelName];
    const effective = getCurrentModelReasoningEffort();
    const noticeId = 'reasoning-adjustment-notice';
    const existingNotice = document.getElementById(noticeId);
    if (existingNotice && (
        existingNotice.dataset.modelKey !== modelName ||
        existingNotice.dataset.effectiveEffort !== (effective || '')
    )) {
        existingNotice.remove();
    }
    if (!settingsLoaded || !requested || requested === effective) return;
    const adjustmentKey = JSON.stringify([modelName, requested, effective]);
    if (!shownAdjustments.has(adjustmentKey)) {
        shownAdjustments.add(adjustmentKey);
        const modelSelect = document.getElementById('model-select');
        const option = modelSelect?.options[modelSelect.selectedIndex];
        const notice = document.getElementById(noticeId) || document.createElement('p');
        notice.id = noticeId;
        notice.className = 'alert alert-warning py-2 small';
        notice.setAttribute('role', 'status');
        notice.dataset.modelKey = modelName;
        notice.dataset.effectiveEffort = effective || '';
        notice.textContent = `${levelLabels[requested] || 'Saved effort'} could not be used for ${option?.dataset.modelName || option?.textContent?.trim() || 'this model'}; using ${levelLabels[effective] || 'Model default'}.`;
        document.getElementById('reasoning-toggle-btn')?.parentElement?.prepend(notice);
    }
    if (effective) saveReasoningEffort(modelName, effective);
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
        reasoningToggleBtn.classList.add('d-none');
        return;
    }
    
    // Hide reasoning button when agents are active
    if (enableAgentsBtn && enableAgentsBtn.classList.contains('active')) {
        reasoningToggleBtn.classList.add('d-none');
        return;
    }
    
    // Hide reasoning button if current model doesn't support reasoning
    const modelName = getCurrentModelName();
    if (modelName) {
        const supportedLevels = getModelSupportedLevels(modelName);
        if (supportedLevels.length === 0) {
            reasoningToggleBtn.classList.add('d-none');
            return;
        }
    }
    
    // Otherwise show the button
    reasoningToggleBtn.classList.toggle('d-none', !modelName);
}

/**
 * Get the current model name from the model selector
 */
function getCurrentModelName() {
    const modelSelect = document.getElementById('model-select');
    if (!modelSelect || !modelSelect.value) {
        return null;
    }

    const selectedOption = modelSelect.options[modelSelect.selectedIndex];
    return selectedOption?.dataset?.modelId || selectedOption?.dataset?.deploymentName || modelSelect.value;
}

/**
 * Determine which reasoning effort levels are supported by a given model
 * @param {string} modelName - The name of the model
 * @returns {Array<string>} Array of supported effort levels
 */
function getReasoningPolicy(modelName) {
    const modelSelect = document.getElementById('model-select');
    const selected = modelSelect?.options[modelSelect.selectedIndex];
    const option = modelName === getCurrentModelName() ? selected :
        Array.from(modelSelect?.options || []).find((item) =>
            item.dataset.modelId === modelName || item.dataset.deploymentName === modelName || item.value === modelName);
    try {
        const policy = JSON.parse(option?.dataset.reasoningCapabilities || '{}');
        return policy && typeof policy === 'object' && !Array.isArray(policy) ? policy : {};
    } catch {
        return {};
    }
}

export function getModelSupportedLevels(modelName) {
    const policy = getReasoningPolicy(modelName);
    return policy.status === 'supported' && Array.isArray(policy.efforts)
        ? policy.efforts.filter((level) => Object.hasOwn(levelLabels, level))
        : [];
}

/**
 * Get the reasoning effort level for the current model
 * @returns {string} The effort level (none, minimal, low, medium, high)
 */
export function getCurrentModelReasoningEffort() {
    const modelName = getCurrentModelName();
    if (!modelName) {
        return null;
    }
    
    const supportedLevels = getModelSupportedLevels(modelName);
    const savedEffort = reasoningEffortSettings[modelName];
    
    // If saved effort exists and is supported, use it
    if (savedEffort && supportedLevels.includes(savedEffort)) {
        return savedEffort;
    }
    
    // Default to 'low' if supported, otherwise first supported level
    if (supportedLevels.includes('low')) {
        return 'low';
    }
    
    const defaultEffort = getReasoningPolicy(modelName).default_effort;
    return supportedLevels.includes(defaultEffort) ? defaultEffort : null;
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
        'high': 'bi-reception-4',
        'xhigh': 'bi-reception-4'
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
        'high': 'High reasoning effort',
        'xhigh': 'XHigh reasoning effort'
    };
    setTooltipText(reasoningToggleBtn, labelMap[level] || 'Configure reasoning effort');
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
    const levelIcons = {
        'none': 'bi-reception-0',
        'minimal': 'bi-reception-1',
        'low': 'bi-reception-2',
        'medium': 'bi-reception-3',
        'high': 'bi-reception-4',
        'xhigh': 'bi-reception-4'
    };
    const levelDescriptions = {
        'none': 'No additional reasoning - fastest responses, suitable for simple questions',
        'minimal': 'Light reasoning - quick responses with basic logical steps',
        'low': 'Moderate reasoning - balanced speed and thoughtfulness for everyday questions',
        'medium': 'Enhanced reasoning - more deliberate thinking for complex questions',
        'high': 'High reasoning - deeper analysis for challenging problems',
        'xhigh': 'Extra high reasoning - most deliberate analysis'
    };
    
    // Build level buttons (reversed for bottom-to-top display)
    levelsContainer.replaceChildren();
    supportedLevels.forEach(level => {
        const isActive = level === currentEffort;
        
        const levelDiv = document.createElement('button');
        levelDiv.type = 'button';
        levelDiv.className = `reasoning-level ${isActive ? 'active' : ''}`;
        levelDiv.dataset.level = level;
        levelDiv.setAttribute('aria-pressed', String(isActive));
        const icon = document.createElement('i');
        icon.className = `bi ${levelIcons[level]}`;
        icon.setAttribute('aria-hidden', 'true');
        const label = document.createElement('span');
        label.className = 'reasoning-level-label';
        label.textContent = levelLabels[level];
        levelDiv.append(icon, label);

        setTooltipText(levelDiv, levelDescriptions[level], { placement: 'right' });
        
        levelDiv.addEventListener('click', () => {
            selectReasoningLevel(level, modelName);
        });
        
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
    document.getElementById('reasoning-adjustment-notice')?.remove();
    // Update the settings
    reasoningEffortSettings[modelName] = level;
    
    // Save to user settings
    saveReasoningEffort(modelName, level);
    
    // Update UI
    updateReasoningIcon(level);
    
    // Update active state in modal
    document.querySelectorAll('.reasoning-level').forEach(el => {
        el.classList.remove('active');
        el.setAttribute('aria-pressed', String(el.dataset.level === level));
        if (el.dataset.level === level) {
            el.classList.add('active');
        }
    });
    
    // Show feedback
    showToast(`Reasoning effort set to ${levelLabels[level]}`, 'success');
    
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
    if (settingsLoaded) {
        saveUserSetting({ reasoningEffortSettings });
    } else {
        pendingLevels = { ...pendingLevels, [modelName]: effort };
    }
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
 * @returns {string|null} A supported explicit effort, or null for model default
 */
export function getCurrentReasoningEffort() {
    const effort = getCurrentModelReasoningEffort();
    return effort;
}
