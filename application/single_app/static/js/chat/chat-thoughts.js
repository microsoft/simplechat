// chat-thoughts.js

import { updateLoadingIndicatorText } from './chat-loading-indicator.js';
import { escapeHtml } from './chat-utils.js';

let thoughtPollingInterval = null;
let lastSeenThoughtIndex = -1;
let activeStreamingThoughtTargetId = null;
let activeStreamingServerMessageId = null;

// ---------------------------------------------------------------------------
// Icon map: step_type → Bootstrap Icon class
// ---------------------------------------------------------------------------
function getThoughtIcon(stepType) {
    const iconMap = {
        'search': 'bi-search',
        'tabular_analysis': 'bi-table',
        'web_search': 'bi-globe',
        'agent_tool_call': 'bi-robot',
        'generation': 'bi-lightning',
        'content_safety': 'bi-shield-check'
    };
    return iconMap[stepType] || 'bi-stars';
}

// ---------------------------------------------------------------------------
// Polling (non-streaming mode)
// ---------------------------------------------------------------------------

/**
 * Start polling for pending thoughts while waiting for a non-streaming response.
 * @param {string} conversationId - The current conversation ID.
 */
function startThoughtPollingWithHandler(conversationId, thoughtHandler) {
    if (!conversationId) return;
    if (!window.appSettings?.enable_thoughts) return;

    stopThoughtPolling(); // clear any previous interval
    lastSeenThoughtIndex = -1;

    thoughtPollingInterval = setInterval(() => {
        fetch(`/api/conversations/${conversationId}/thoughts/pending`, {
            credentials: 'same-origin'
        })
            .then(r => r.json())
            .then(data => {
                if (data.thoughts && data.thoughts.length > 0) {
                    const latest = data.thoughts[data.thoughts.length - 1];
                    if (latest.step_index > lastSeenThoughtIndex) {
                        lastSeenThoughtIndex = latest.step_index;
                        thoughtHandler(latest);
                    }
                }
            })
            .catch(() => { /* ignore polling errors */ });
    }, 2000);
}


export function startThoughtPolling(conversationId) {
    startThoughtPollingWithHandler(conversationId, latest => {
        const icon = getThoughtIcon(latest.step_type);
        updateLoadingIndicatorText(latest.content, icon);
    });
}


export function startStreamingThoughtPolling(conversationId) {
    startThoughtPollingWithHandler(conversationId, latest => {
        handleStreamingThought(latest);
    });
}

export function beginStreamingThoughtSession(targetMessageId) {
    activeStreamingThoughtTargetId = targetMessageId || null;
    activeStreamingServerMessageId = null;
}

export function clearStreamingThoughtSession(targetMessageId = null) {
    if (targetMessageId && activeStreamingThoughtTargetId && activeStreamingThoughtTargetId !== targetMessageId) {
        return;
    }

    activeStreamingThoughtTargetId = null;
    activeStreamingServerMessageId = null;
}

/**
 * Stop the thought polling interval.
 */
export function stopThoughtPolling() {
    if (thoughtPollingInterval) {
        clearInterval(thoughtPollingInterval);
        thoughtPollingInterval = null;
    }
    lastSeenThoughtIndex = -1;
}

// ---------------------------------------------------------------------------
// Streaming handler
// ---------------------------------------------------------------------------

/**
 * Handle a streaming thought event received via SSE.
 * Updates the streaming message placeholder with a styled thought indicator.
 * When actual content starts streaming, updateStreamingMessage() will overwrite this.
 * @param {object} thoughtData - { message_id, step_index, step_type, content }
 * @param {string|null} targetMessageId - Temporary DOM message ID for the active stream.
 */
export function handleStreamingThought(thoughtData, targetMessageId = null) {
    if (targetMessageId) {
        activeStreamingThoughtTargetId = targetMessageId;
    }

    if (!activeStreamingThoughtTargetId) {
        return;
    }

    if (thoughtData.message_id) {
        if (activeStreamingServerMessageId && activeStreamingServerMessageId !== thoughtData.message_id) {
            return;
        }

        activeStreamingServerMessageId = thoughtData.message_id;
    }

    const messageElement = document.querySelector(`[data-message-id="${activeStreamingThoughtTargetId}"]`);
    if (!messageElement) return;

    if (messageElement.dataset.streamingHasContent === 'true') {
        return;
    }

    if (activeStreamingServerMessageId) {
        messageElement.dataset.streamingServerMessageId = activeStreamingServerMessageId;
    }

    const contentElement = messageElement.querySelector('.message-text');
    if (!contentElement) return;

    const icon = getThoughtIcon(thoughtData.step_type);
    // Replace entire content with styled thought indicator (visually distinct from AI response)
    contentElement.innerHTML = `<div class="streaming-thought-display">
        <span class="badge bg-info bg-opacity-10 text-info border border-info-subtle px-3 py-2 animate-pulse" style="font-size: 0.85rem; font-weight: 500;">
            <i class="bi ${icon} me-2"></i>${escapeHtml(thoughtData.content)}
        </span>
    </div>`;
}

// ---------------------------------------------------------------------------
// Per-message collapsible: toggle button + container HTML
// ---------------------------------------------------------------------------

/**
 * Create HTML for the thoughts toggle button and hidden container.
 * Returns an object with { toggleHtml, containerHtml }.
 * @param {string} messageId
 */
export function createThoughtsToggleHtml(messageId) {
    if (!window.appSettings?.enable_thoughts) {
        return { toggleHtml: '', containerHtml: '' };
    }

    const containerId = `thoughts-${messageId || Date.now()}`;
    const toggleHtml = `<button class="btn btn-sm btn-link text-muted thoughts-toggle-btn" title="Show processing thoughts" aria-expanded="false" aria-controls="${containerId}"><i class="bi bi-stars"></i></button>`;
    const containerHtml = `<div id="${containerId}" class="thoughts-container d-none mt-2 pt-2 border-top"><div class="text-muted small">Loading thoughts...</div></div>`;

    return { toggleHtml, containerHtml };
}

/**
 * Attach event listener for the thoughts toggle button inside a message div.
 * @param {HTMLElement} messageDiv
 * @param {string} messageId
 * @param {string} conversationId
 */
export function attachThoughtsToggleListener(messageDiv, messageId, conversationId) {
    const toggleBtn = messageDiv.querySelector('.thoughts-toggle-btn');
    if (!toggleBtn) return;

    toggleBtn.addEventListener('click', () => {
        const targetId = toggleBtn.getAttribute('aria-controls');
        const container = messageDiv.querySelector(`#${targetId}`);
        if (!container) return;

        // Store scroll position
        const scrollContainer = document.getElementById('chat-messages-container');
        const currentScroll = scrollContainer?.scrollTop || window.pageYOffset;

        const isExpanded = !container.classList.contains('d-none');
        if (isExpanded) {
            container.classList.add('d-none');
            toggleBtn.setAttribute('aria-expanded', 'false');
            toggleBtn.title = 'Show processing thoughts';
            toggleBtn.innerHTML = '<i class="bi bi-stars"></i>';
        } else {
            container.classList.remove('d-none');
            toggleBtn.setAttribute('aria-expanded', 'true');
            toggleBtn.title = 'Hide processing thoughts';
            toggleBtn.innerHTML = '<i class="bi bi-chevron-up"></i>';

            // Lazy-load thoughts on first expand
            if (container.innerHTML.includes('Loading thoughts')) {
                loadThoughtsForMessage(conversationId, messageId, container);
            }
        }

        // Restore scroll position
        setTimeout(() => {
            if (scrollContainer) {
                scrollContainer.scrollTop = currentScroll;
            } else {
                window.scrollTo(0, currentScroll);
            }
        }, 10);
    });
}

// ---------------------------------------------------------------------------
// Fetch + render thoughts for a message
// ---------------------------------------------------------------------------

/**
 * Fetch thoughts for a specific message from the API and render them.
 * @param {string} conversationId
 * @param {string} messageId
 * @param {HTMLElement} container
 */
function loadThoughtsForMessage(conversationId, messageId, container) {
    fetch(`/api/conversations/${conversationId}/messages/${messageId}/thoughts`, {
        credentials: 'same-origin'
    })
        .then(r => r.json())
        .then(data => {
            if (!data.enabled) {
                container.innerHTML = '<div class="text-muted small">Processing thoughts are disabled.</div>';
                return;
            }
            if (!data.thoughts || data.thoughts.length === 0) {
                container.innerHTML = '<div class="text-muted small">No processing thoughts recorded for this message.</div>';
                return;
            }
            container.innerHTML = renderThoughtsList(data.thoughts);
        })
        .catch(err => {
            console.error('Error loading thoughts:', err);
            container.innerHTML = '<div class="text-danger small">Failed to load processing thoughts.</div>';
        });
}

/**
 * Render a list of thought steps as HTML.
 * @param {Array} thoughts
 * @returns {string} HTML string
 */
function renderThoughtsList(thoughts) {
    let html = '<div class="thoughts-list">';
    thoughts.forEach(t => {
        const icon = getThoughtIcon(t.step_type);
        const durationStr = t.duration_ms != null ? `<span class="text-muted ms-2">(${t.duration_ms}ms)</span>` : '';
        html += `<div class="thought-step small py-1">
            <i class="bi ${icon} me-2 text-muted"></i>
            <span>${escapeHtml(t.content || '')}</span>
            ${durationStr}
        </div>`;
    });
    html += '</div>';
    return html;
}
