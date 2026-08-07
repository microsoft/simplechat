// chat-orchestration-interaction.js

import { loadUserSettings, saveUserSetting } from './chat-layout.js';
import { showToast } from './chat-toast.js';

const EXECUTION_MODE_LABELS = {
    manual: 'Manual',
    balanced: 'Balanced',
    auto: 'Auto',
};

const EXECUTION_MODE_DESCRIPTIONS = {
    manual: 'Ask before optional tools or artifacts.',
    balanced: 'Use safe automation, ask when needed.',
    auto: 'Run governed plans until approval is required.',
};

const REVIEW_VISIBILITY_LABELS = {
    collapsed: 'Collapsed',
    expanded: 'Expanded',
};

const DEFAULT_POLICY = {
    enabled_execution_modes: ['manual', 'balanced', 'auto'],
    default_execution_mode: 'balanced',
    enabled_review_visibility: ['collapsed', 'expanded'],
    default_review_visibility: 'collapsed',
    allow_conversation_execution_mode: true,
    allow_per_message_execution_mode: true,
    allow_conversation_review_visibility: true,
    allow_per_message_review_visibility: true,
    context_execution_modes: {
        personal: ['manual', 'balanced', 'auto'],
        group: ['manual', 'balanced', 'auto'],
        public: ['manual', 'balanced', 'auto'],
        external: ['manual', 'balanced', 'auto'],
    },
};

const container = document.getElementById('orchestration-mode-container');
const dropdownButton = document.getElementById('orchestration-mode-dropdown-button');
const dropdownText = document.getElementById('orchestration-mode-dropdown-text');
const optionsContainer = document.getElementById('orchestration-mode-options');
const reviewToggle = document.getElementById('orchestration-review-visibility-toggle');
const saveConversationDefaultBtn = document.getElementById('orchestration-save-conversation-default-btn');
const saveUserDefaultBtn = document.getElementById('orchestration-save-user-default-btn');
const statusEl = document.getElementById('orchestration-mode-status');

let userPreference = {};
let conversationPreference = {};
let currentContextType = 'personal';
let selectedExecutionMode = null;
let selectedReviewVisibility = null;
let perMessageExecutionModeOverride = false;
let perMessageReviewVisibilityOverride = false;

function normalizeArray(value, fallback) {
    if (!Array.isArray(value)) {
        return fallback.slice();
    }
    const normalized = [];
    value.forEach(item => {
        const text = String(item || '').trim().toLowerCase();
        if (text && !normalized.includes(text)) {
            normalized.push(text);
        }
    });
    return normalized.length ? normalized : fallback.slice();
}

function getPolicy() {
    const rawPolicy = window.appSettings?.orchestrationInteractionPolicy;
    const policy = rawPolicy && typeof rawPolicy === 'object' ? rawPolicy : {};
    const enabledExecutionModes = normalizeArray(
        policy.enabled_execution_modes,
        DEFAULT_POLICY.enabled_execution_modes,
    ).filter(mode => EXECUTION_MODE_LABELS[mode]);
    const enabledReviewVisibility = normalizeArray(
        policy.enabled_review_visibility,
        DEFAULT_POLICY.enabled_review_visibility,
    ).filter(visibility => REVIEW_VISIBILITY_LABELS[visibility]);
    const contextModes = policy.context_execution_modes && typeof policy.context_execution_modes === 'object'
        ? policy.context_execution_modes
        : DEFAULT_POLICY.context_execution_modes;

    return {
        ...DEFAULT_POLICY,
        ...policy,
        enabled_execution_modes: enabledExecutionModes.length ? enabledExecutionModes : DEFAULT_POLICY.enabled_execution_modes.slice(),
        enabled_review_visibility: enabledReviewVisibility.length ? enabledReviewVisibility : DEFAULT_POLICY.enabled_review_visibility.slice(),
        context_execution_modes: contextModes,
    };
}

function getAllowedExecutionModes(contextType = currentContextType) {
    const policy = getPolicy();
    const enabledModes = policy.enabled_execution_modes;
    const contextModes = normalizeArray(
        policy.context_execution_modes?.[contextType],
        enabledModes,
    ).filter(mode => enabledModes.includes(mode));
    return contextModes.length ? contextModes : enabledModes.slice(0, 1);
}

function getAllowedReviewVisibility() {
    return getPolicy().enabled_review_visibility;
}

function pickAllowed(value, allowedValues, fallback) {
    const normalized = String(value || '').trim().toLowerCase();
    if (normalized && allowedValues.includes(normalized)) {
        return normalized;
    }
    if (allowedValues.includes(fallback)) {
        return fallback;
    }
    return allowedValues[0] || fallback;
}

function normalizePreference(preference) {
    if (!preference || typeof preference !== 'object') {
        return {};
    }
    const nested = preference.orchestration_interaction;
    return nested && typeof nested === 'object' ? nested : preference;
}

function deriveContextType(metadata = {}) {
    const chatType = String(metadata.chat_type || '').trim().toLowerCase();
    if (chatType.startsWith('group')) {
        return 'group';
    }
    if (chatType.startsWith('public')) {
        return 'public';
    }
    const context = Array.isArray(metadata.context) ? metadata.context : [];
    const primary = context.find(item => item && item.type === 'primary');
    const scope = String(primary?.scope || '').trim().toLowerCase();
    if (scope === 'group' || scope === 'public') {
        return scope;
    }
    return 'personal';
}

function getDefaultExecutionMode() {
    const policy = getPolicy();
    const allowedModes = getAllowedExecutionModes();
    return pickAllowed(
        conversationPreference.execution_mode
            || userPreference.default_execution_mode
            || policy.default_execution_mode,
        allowedModes,
        policy.default_execution_mode || 'balanced',
    );
}

function getDefaultReviewVisibility() {
    const policy = getPolicy();
    const allowedVisibility = getAllowedReviewVisibility();
    return pickAllowed(
        conversationPreference.review_visibility
            || userPreference.default_review_visibility
            || policy.default_review_visibility,
        allowedVisibility,
        policy.default_review_visibility || 'collapsed',
    );
}

function setStatus(message) {
    if (!statusEl) {
        return;
    }
    statusEl.textContent = message || '';
}

function setSelectedExecutionMode(mode, options = {}) {
    const allowedModes = getAllowedExecutionModes();
    selectedExecutionMode = pickAllowed(mode, allowedModes, getDefaultExecutionMode());
    perMessageExecutionModeOverride = Boolean(options.perMessageOverride);
    render();
}

function setSelectedReviewVisibility(visibility, options = {}) {
    const allowedVisibility = getAllowedReviewVisibility();
    selectedReviewVisibility = pickAllowed(visibility, allowedVisibility, getDefaultReviewVisibility());
    perMessageReviewVisibilityOverride = Boolean(options.perMessageOverride);
    render();
}

function getSelectedExecutionMode() {
    return selectedExecutionMode || getDefaultExecutionMode();
}

function getSelectedReviewVisibility() {
    return selectedReviewVisibility || getDefaultReviewVisibility();
}

function createModeOption(mode) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-sm text-start border d-flex flex-column align-items-start';
    button.dataset.executionMode = mode;

    const label = document.createElement('span');
    label.className = 'fw-semibold';
    label.textContent = EXECUTION_MODE_LABELS[mode] || mode;

    const description = document.createElement('span');
    description.className = 'small text-muted';
    description.textContent = EXECUTION_MODE_DESCRIPTIONS[mode] || '';

    button.append(label, description);
    button.addEventListener('click', () => {
        setSelectedExecutionMode(mode, { perMessageOverride: true });
        setStatus(`${EXECUTION_MODE_LABELS[mode]} applies to the next message.`);
    });
    return button;
}

function renderModeOptions() {
    if (!optionsContainer) {
        return;
    }
    const allowedModes = getAllowedExecutionModes();
    optionsContainer.replaceChildren();
    allowedModes.forEach(mode => {
        const option = createModeOption(mode);
        option.classList.toggle('btn-primary', getSelectedExecutionMode() === mode);
        option.classList.toggle('btn-outline-secondary', getSelectedExecutionMode() !== mode);
        option.setAttribute('aria-pressed', getSelectedExecutionMode() === mode ? 'true' : 'false');
        optionsContainer.appendChild(option);
    });
}

function render() {
    if (!container) {
        return;
    }
    const policy = getPolicy();
    const allowedModes = getAllowedExecutionModes();
    const allowedVisibility = getAllowedReviewVisibility();
    if (!allowedModes.length) {
        container.classList.add('d-none');
        return;
    }
    container.classList.remove('d-none');

    selectedExecutionMode = pickAllowed(getSelectedExecutionMode(), allowedModes, policy.default_execution_mode || 'balanced');
    selectedReviewVisibility = pickAllowed(getSelectedReviewVisibility(), allowedVisibility, policy.default_review_visibility || 'collapsed');

    if (dropdownText) {
        dropdownText.textContent = EXECUTION_MODE_LABELS[selectedExecutionMode] || 'Balanced';
    }
    if (dropdownButton) {
        const label = EXECUTION_MODE_LABELS[selectedExecutionMode] || selectedExecutionMode;
        const visibilityLabel = REVIEW_VISIBILITY_LABELS[selectedReviewVisibility] || selectedReviewVisibility;
        dropdownButton.title = `${label} mode, ${visibilityLabel} review visibility`;
        dropdownButton.setAttribute('aria-label', dropdownButton.title);
    }
    if (reviewToggle) {
        reviewToggle.checked = selectedReviewVisibility === 'expanded';
        reviewToggle.disabled = !allowedVisibility.includes('expanded');
    }
    if (saveConversationDefaultBtn) {
        saveConversationDefaultBtn.disabled = !window.currentConversationId || !policy.allow_conversation_execution_mode;
    }
    if (saveUserDefaultBtn) {
        saveUserDefaultBtn.disabled = false;
    }
    renderModeOptions();
}

function resetPerMessageOverrides() {
    perMessageExecutionModeOverride = false;
    perMessageReviewVisibilityOverride = false;
    selectedExecutionMode = getDefaultExecutionMode();
    selectedReviewVisibility = getDefaultReviewVisibility();
    setStatus('');
    render();
}

async function refreshConversationPreference(conversationId) {
    conversationPreference = {};
    currentContextType = 'personal';
    if (!conversationId) {
        resetPerMessageOverrides();
        return;
    }
    try {
        const response = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}/metadata`, {
            credentials: 'same-origin',
        });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const metadata = await response.json();
        currentContextType = deriveContextType(metadata);
        conversationPreference = normalizePreference(metadata.orchestration_interaction || {});
    } catch (error) {
        console.warn('Unable to load conversation orchestration interaction preference:', error);
    }
    resetPerMessageOverrides();
}

async function initializeUserPreference() {
    try {
        const settings = await loadUserSettings();
        userPreference = normalizePreference(settings?.orchestration_interaction || {});
    } catch (error) {
        console.warn('Unable to load orchestration interaction user preference:', error);
    }
    resetPerMessageOverrides();
}

async function saveConversationDefault() {
    const conversationId = String(window.currentConversationId || '').trim();
    if (!conversationId) {
        showToast('Open a conversation before saving a conversation default.', 'warning');
        return;
    }
    const payload = {
        execution_mode: getSelectedExecutionMode(),
        review_visibility: getSelectedReviewVisibility(),
    };
    try {
        const response = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}/orchestration-interaction`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'same-origin',
            body: JSON.stringify(payload),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.success !== true) {
            throw new Error(result.error || 'Unable to save conversation default.');
        }
        conversationPreference = normalizePreference(result.orchestration_interaction || payload);
        resetPerMessageOverrides();
        showToast('Conversation orchestration default saved.', 'success');
    } catch (error) {
        showToast(error.message || 'Unable to save conversation default.', 'danger');
    }
}

async function saveUserDefault() {
    const preference = {
        default_execution_mode: getSelectedExecutionMode(),
        default_review_visibility: getSelectedReviewVisibility(),
    };
    const saved = await saveUserSetting({ orchestration_interaction: preference });
    if (saved) {
        userPreference = preference;
        resetPerMessageOverrides();
        showToast('Default orchestration mode saved.', 'success');
    } else {
        showToast('Unable to save orchestration default.', 'danger');
    }
}

export function getOrchestrationInteractionRequest() {
    const payload = {};
    if (perMessageExecutionModeOverride) {
        payload.execution_mode = getSelectedExecutionMode();
    }
    if (perMessageReviewVisibilityOverride) {
        payload.review_visibility = getSelectedReviewVisibility();
    }
    return payload;
}

export function markOrchestrationInteractionSubmitted() {
    resetPerMessageOverrides();
}

export function initializeOrchestrationInteractionControls() {
    if (!container) {
        return;
    }
    reviewToggle?.addEventListener('change', () => {
        setSelectedReviewVisibility(reviewToggle.checked ? 'expanded' : 'collapsed', {
            perMessageOverride: true,
        });
        setStatus(`${reviewToggle.checked ? 'Expanded' : 'Collapsed'} review applies to the next message.`);
    });
    saveConversationDefaultBtn?.addEventListener('click', () => {
        void saveConversationDefault();
    });
    saveUserDefaultBtn?.addEventListener('click', () => {
        void saveUserDefault();
    });
    window.addEventListener('chat:conversation-context-changed', event => {
        void refreshConversationPreference(event.detail?.conversationId || window.currentConversationId || '');
    });
    void initializeUserPreference();
    render();
}

initializeOrchestrationInteractionControls();

window.chatOrchestrationInteraction = {
    getOrchestrationInteractionRequest,
    markOrchestrationInteractionSubmitted,
    initializeOrchestrationInteractionControls,
};