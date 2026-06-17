// chat-streaming.js
import { appendMessage, renderAiMessageContent, updateUserMessageId } from './chat-messages.js';
import { applyConversationMetadataUpdate, markConversationRead } from './chat-conversations.js';
import { hideLoadingIndicatorInChatbox, showLoadingIndicatorInChatbox } from './chat-loading-indicator.js';
import { showToast } from './chat-toast.js';
import { applyScopeLock } from './chat-documents.js';
import { beginStreamingThoughtSession, clearStreamingThoughtSession, handleStreamingThought, markStreamingThoughtContentStarted, stopThoughtPolling } from './chat-thoughts.js';
import { destroyInlineCharts, hydrateInlineCharts } from './chat-inline-charts.js';
import { hydrateInlineImageProposals } from './chat-inline-image-proposals.js';
import { escapeHtml } from './chat-utils.js';

let currentStreamController = null;
let currentStreamContext = null;
const MAX_STREAM_CLIENT_ERROR_LENGTH = 500;

function normalizeLegacyEscapedSseDelimiters(chunk) {
    return String(chunk || '').replace(/(\})\\n\\n(?=(?:data:|event:|id:|retry:|:|$))/g, '$1\n\n');
}

function parseSseEventPayload(eventBlock) {
    const dataLines = eventBlock
        .split('\n')
        .filter(line => line.startsWith('data:'));

    if (dataLines.length === 0) {
        return null;
    }

    return dataLines
        .map(line => line.substring(5).trimStart())
        .join('\n');
}

function getStreamingPlaceholderLabel(statusLabel) {
    const normalizedStatusLabel = String(statusLabel || '').trim().replace(/\.+$/, '');

    if (/reconnect/i.test(normalizedStatusLabel)) {
        return 'Reconnecting';
    }

    if (normalizedStatusLabel && !/^streaming$/i.test(normalizedStatusLabel)) {
        return normalizedStatusLabel;
    }

    return 'Thinking';
}

function createStreamingPlaceholderContent(statusLabel) {
    const placeholderLabel = getStreamingPlaceholderLabel(statusLabel);
    const ariaLabel = placeholderLabel === 'Reconnecting'
        ? 'Reconnecting to the response'
        : 'Thinking while the response starts';

    return `<div class="streaming-thought-display streaming-thinking-placeholder" role="status" aria-live="polite" aria-label="${escapeHtml(ariaLabel)}">
        <span class="streaming-thinking-chip">
            <span class="streaming-thinking-icon" aria-hidden="true"><i class="bi bi-stars"></i></span>
            <span class="streaming-thinking-label">${escapeHtml(placeholderLabel)}</span>
        </span>
    </div>`;
}

function createStreamingPlaceholder(statusLabel = 'Thinking') {
    const tempAiMessageId = `temp_ai_${Date.now()}_${Math.floor(Math.random() * 10000)}`;
    appendMessage('AI', createStreamingPlaceholderContent(statusLabel), null, tempAiMessageId);
    beginStreamingThoughtSession(tempAiMessageId);
    return tempAiMessageId;
}

function getStreamingMessageElement(messageId) {
    if (!messageId) {
        return null;
    }

    return document.querySelector(`[data-message-id="${messageId}"]`);
}

function buildDefaultCancelEndpoint(conversationId) {
    const normalizedConversationId = String(conversationId || '').trim();
    if (!normalizedConversationId) {
        return null;
    }

    return `/api/chat/stream/cancel/${encodeURIComponent(normalizedConversationId)}`;
}

function resolveCancelEndpoint(conversationId, explicitCancelEndpoint) {
    const normalizedExplicitEndpoint = String(explicitCancelEndpoint || '').trim();
    if (normalizedExplicitEndpoint) {
        return normalizedExplicitEndpoint;
    }

    return buildDefaultCancelEndpoint(conversationId);
}

function setStreamingStopButtonState(messageId, state = 'ready') {
    const messageElement = getStreamingMessageElement(messageId);
    const stopButton = messageElement?.querySelector('.stream-stop-btn');
    if (!stopButton) {
        return;
    }

    stopButton.classList.toggle('disabled', state !== 'ready');
    stopButton.disabled = state !== 'ready';
    stopButton.classList.toggle('opacity-75', state === 'stopping');

    if (state === 'stopping') {
        stopButton.title = 'Stopping response';
        stopButton.setAttribute('aria-label', 'Stopping response');
        return;
    }

    if (state === 'waiting_for_conversation') {
        stopButton.title = 'Preparing stop control';
        stopButton.setAttribute('aria-label', 'Preparing stop control');
        return;
    }

    stopButton.title = 'Stop generating';
    stopButton.setAttribute('aria-label', 'Stop generating response');
}

function removeStreamingStopButton(messageId) {
    const messageElement = getStreamingMessageElement(messageId);
    const stopButton = messageElement?.querySelector('.stream-stop-btn');
    if (stopButton) {
        stopButton.remove();
    }
    messageElement?.classList.remove('streaming-message');
}

function attachStreamingStopButton(messageId, streamContext) {
    const messageElement = getStreamingMessageElement(messageId);
    if (!messageElement || messageElement.querySelector('.stream-stop-btn')) {
        return;
    }

    const footer = messageElement.querySelector('.message-footer');
    const actionsContainer = messageElement.querySelector('.message-actions') || footer?.firstElementChild || footer;
    if (!actionsContainer) {
        return;
    }

    messageElement.classList.add('streaming-message');

    const stopButton = document.createElement('button');
    stopButton.type = 'button';
    stopButton.className = 'btn btn-sm stream-stop-btn d-inline-flex align-items-center justify-content-center rounded-circle p-0 border-0';
    stopButton.dataset.messageId = messageId;

    const icon = document.createElement('i');
    icon.className = 'bi bi-stop-fill';
    icon.setAttribute('aria-hidden', 'true');
    icon.style.fontSize = '0.95rem';
    stopButton.appendChild(icon);

    stopButton.addEventListener('click', () => {
        void requestStreamCancellation(streamContext);
    });

    actionsContainer.appendChild(stopButton);
    setStreamingStopButtonState(messageId, streamContext?.cancelEndpoint ? 'ready' : 'waiting_for_conversation');
}

function clearCurrentStreamController(controller) {
    if (currentStreamController === controller) {
        currentStreamController = null;
    }
    if (currentStreamContext?.controller === controller) {
        currentStreamContext = null;
    }
}

function removeStreamingPlaceholder(messageId) {
    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (messageElement) {
        messageElement.remove();
    }
}

function normalizeStreamErrorMessage(errorLike) {
    const normalized = String(errorLike || '').trim();
    if (normalized.length <= MAX_STREAM_CLIENT_ERROR_LENGTH) {
        return normalized;
    }

    return `${normalized.slice(0, MAX_STREAM_CLIENT_ERROR_LENGTH)}...`;
}

function normalizeStreamHttpUrl(value) {
    const rawUrl = String(value || '').trim();
    if (!rawUrl) {
        return '';
    }

    try {
        const parsedUrl = new URL(rawUrl);
        if (!['http:', 'https:'].includes(parsedUrl.protocol) || !parsedUrl.hostname) {
            return '';
        }
        return parsedUrl.toString();
    } catch (error) {
        return '';
    }
}

function getStreamErrorPayload(errorDetails) {
    if (!errorDetails || typeof errorDetails !== 'object') {
        return {};
    }

    if (errorDetails.streamErrorData && typeof errorDetails.streamErrorData === 'object') {
        return errorDetails.streamErrorData;
    }

    return errorDetails;
}

function getStreamAuthUrl(errorDetails) {
    const errorPayload = getStreamErrorPayload(errorDetails);
    return normalizeStreamHttpUrl(errorPayload.auth_url || errorPayload.consent_url || '');
}

function buildStreamingRequestError(errorData, status) {
    const streamErrorData = errorData && typeof errorData === 'object' ? errorData : {};
    const errorMessage = String(streamErrorData.error || `HTTP error! status: ${status}`).trim();
    const streamError = new Error(errorMessage || `HTTP error! status: ${status}`);
    streamError.streamErrorData = streamErrorData;
    streamError.status = status;
    return streamError;
}

function appendStreamErrorBanner(contentElement, errorMessage, errorDetails = {}) {
    const errorPayload = getStreamErrorPayload(errorDetails);
    const authRequired = errorPayload.auth_required === true;
    const authUrl = getStreamAuthUrl(errorPayload);
    const displayMessage = String(
        errorMessage || errorPayload.error || errorPayload.message || 'An unknown streaming error occurred.'
    ).trim();

    const errorBanner = document.createElement('div');
    errorBanner.className = 'alert alert-warning mt-2 mb-0';

    const icon = document.createElement('i');
    icon.className = 'bi bi-exclamation-triangle me-2';
    icon.setAttribute('aria-hidden', 'true');

    const title = document.createElement('strong');
    title.textContent = authRequired ? 'Foundry access required:' : 'Stream interrupted:';

    errorBanner.appendChild(icon);
    errorBanner.appendChild(title);
    errorBanner.appendChild(document.createTextNode(` ${displayMessage}`));

    if (authRequired && authUrl) {
        const actionRow = document.createElement('div');
        actionRow.className = 'mt-2';

        const authLink = document.createElement('a');
        authLink.href = authUrl;
        authLink.target = '_blank';
        authLink.rel = 'noopener noreferrer';
        authLink.textContent = 'Sign in or grant Foundry access';

        actionRow.appendChild(authLink);
        errorBanner.appendChild(actionRow);
    }

    const detailRow = document.createElement('div');
    detailRow.className = 'mt-1';

    const detailText = document.createElement('small');
    detailText.textContent = authRequired
        ? 'After access is granted, send the message again.'
        : 'Response may be incomplete. The partial content above has been saved.';

    detailRow.appendChild(detailText);
    errorBanner.appendChild(detailRow);
    contentElement.appendChild(errorBanner);
}

function reportClientStreamEvent(eventType, payload = {}) {
    const normalizedEventType = String(eventType || '').trim();
    if (!normalizedEventType) {
        return Promise.resolve(false);
    }

    const requestBody = {
        event_type: normalizedEventType,
        ...payload,
    };

    if (requestBody.error_message) {
        requestBody.error_message = normalizeStreamErrorMessage(requestBody.error_message);
    }
    if (requestBody.abort_reason) {
        requestBody.abort_reason = normalizeStreamErrorMessage(requestBody.abort_reason);
    }

    return fetch('/api/chat/stream/client-event', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify(requestBody),
        keepalive: true,
    }).then(() => true).catch(error => {
        console.warn('Failed to report stream client event:', error);
        return false;
    });
}

function updateStreamContextConversation(streamContext, conversationId) {
    if (!streamContext || !conversationId) {
        return;
    }

    streamContext.conversationId = conversationId;
    if (!streamContext.explicitCancelEndpoint) {
        streamContext.cancelEndpoint = buildDefaultCancelEndpoint(conversationId);
    }
    setStreamingStopButtonState(streamContext.tempAiMessageId, streamContext.cancelEndpoint ? 'ready' : 'waiting_for_conversation');
}

async function requestStreamCancellation(streamContext = currentStreamContext) {
    if (!streamContext || streamContext.cancellationRequested) {
        return false;
    }

    if (!streamContext.cancelEndpoint) {
        const fallbackEndpoint = buildDefaultCancelEndpoint(streamContext.conversationId || window.currentConversationId);
        if (fallbackEndpoint) {
            streamContext.cancelEndpoint = fallbackEndpoint;
        }
    }

    if (!streamContext.cancelEndpoint) {
        setStreamingStopButtonState(streamContext.tempAiMessageId, 'waiting_for_conversation');
        showToast('Stop will be available once the conversation is ready.', 'info');
        return false;
    }

    streamContext.cancellationRequested = true;
    setStreamingStopButtonState(streamContext.tempAiMessageId, 'stopping');

    void reportClientStreamEvent('stream_cancel_requested', {
        conversation_id: streamContext.conversationId || window.currentConversationId || null,
        cancel_endpoint: streamContext.explicitCancelEndpoint ? 'custom' : 'chat',
    });

    try {
        const response = await fetch(streamContext.cancelEndpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'same-origin',
            body: JSON.stringify({ reason: 'user_requested' }),
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `Failed to stop stream (${response.status})`);
        }

        return true;
    } catch (error) {
        if (currentStreamContext !== streamContext) {
            return false;
        }
        streamContext.cancellationRequested = false;
        setStreamingStopButtonState(streamContext.tempAiMessageId, 'ready');
        console.warn('Failed to request stream cancellation:', error);
        showToast(error.message || 'Failed to stop the response.', 'warning');
        return false;
    }
}

function findConversationListItem(conversationId) {
    const normalizedConversationId = String(conversationId || '');
    return Array.from(document.querySelectorAll('.conversation-item')).find(item => (
        item.getAttribute('data-conversation-id') === normalizedConversationId
    )) || null;
}

export function applyStreamingConversationMetadata(data = {}) {
    const conversationId = data.conversation_id || data.conversationId;
    if (!conversationId) {
        return;
    }

    if (!window.currentConversationId) {
        window.currentConversationId = conversationId;
    }

    const metadataUpdates = {};
    const conversationTitle = data.conversation_title ?? data.title;
    if (conversationTitle !== undefined) {
        metadataUpdates.title = String(conversationTitle || '').trim() || 'New Conversation';
    }
    if (Array.isArray(data.classification)) {
        metadataUpdates.classification = data.classification;
    }
    if (Array.isArray(data.context)) {
        metadataUpdates.context = data.context;
    }
    if (data.chat_type !== undefined) {
        metadataUpdates.chat_type = data.chat_type || null;
    }

    if (Object.keys(metadataUpdates).length === 0) {
        return;
    }

    const existingItem = findConversationListItem(conversationId);
    const canAddMissingActiveConversation = !window.currentConversationId || window.currentConversationId === conversationId;
    if (!existingItem && canAddMissingActiveConversation && window.chatConversations?.addConversationToList && metadataUpdates.title) {
        window.chatConversations.addConversationToList(
            conversationId,
            metadataUpdates.title,
            metadataUpdates.classification || []
        );
    }

    applyConversationMetadataUpdate(conversationId, metadataUpdates);
}

async function getStreamingStatus(conversationId) {
    if (!conversationId) {
        return null;
    }

    const statusResponse = await fetch(`/api/chat/stream/status/${conversationId}`, {
        credentials: 'same-origin',
    });
    const statusData = await statusResponse.json().catch(() => ({}));

    if (!statusResponse.ok) {
        return null;
    }

    return statusData;
}

async function attemptStreamingRecovery(conversationId, failedMessageId, tempUserMessageId, options = {}) {
    const {
        onDone = null,
        onError = null,
        onFinally = null,
        reconnectStatusLabel = 'Reconnecting...',
    } = options;

    if (!conversationId) {
        return false;
    }

    try {
        const statusData = await getStreamingStatus(conversationId);
        if (!statusData?.pending) {
            void reportClientStreamEvent('stream_recovery_unavailable', {
                conversation_id: conversationId,
                pending: Boolean(statusData?.pending),
                reattachable: Boolean(statusData?.reattachable),
                status: statusData?.status || null,
            });
            return false;
        }

        void reportClientStreamEvent('stream_recovery_attempt', {
            conversation_id: conversationId,
            pending: Boolean(statusData?.pending),
            reattachable: Boolean(statusData?.reattachable),
            status: statusData?.status || null,
        });

        clearStreamingThoughtSession(failedMessageId);
        removeStreamingPlaceholder(failedMessageId);

        const reconnectMessageId = createStreamingPlaceholder(reconnectStatusLabel);
        void reportClientStreamEvent('stream_recovery_attached', {
            conversation_id: conversationId,
            pending: Boolean(statusData?.pending),
            reattachable: Boolean(statusData?.reattachable),
            status: statusData?.status || null,
        });
        return consumeStreamingResponse(
            signal => fetch(`/api/chat/stream/reattach/${conversationId}`, {
                method: 'GET',
                credentials: 'same-origin',
                signal,
            }),
            reconnectMessageId,
            tempUserMessageId,
            {
                onDone,
                onError,
                onFinally,
                allowRecovery: false,
                recoveryConversationId: conversationId,
                reconnectStatusLabel,
            },
        );
    } catch (error) {
        console.warn('Failed to recover streaming conversation automatically:', error);
        return false;
    }
}

function consumeStreamingResponse(requestFactory, tempAiMessageId, tempUserMessageId, options = {}) {
    const {
        onDone = null,
        onError = null,
        onFinally = null,
        allowRecovery = true,
        recoveryConversationId = null,
        cancelEndpoint = null,
        reconnectStatusLabel = 'Reconnecting...',
        fallbackAgentInfo = null,
    } = options;

    if (currentStreamController) {
        removeStreamingStopButton(currentStreamContext?.tempAiMessageId);
        currentStreamController.abort('replaced');
        currentStreamContext = null;
    }

    const abortController = new AbortController();
    currentStreamController = abortController;
    const streamContext = {
        controller: abortController,
        tempAiMessageId,
        conversationId: recoveryConversationId,
        explicitCancelEndpoint: Boolean(cancelEndpoint),
        cancelEndpoint: resolveCancelEndpoint(recoveryConversationId, cancelEndpoint),
        cancellationRequested: false,
    };
    currentStreamContext = streamContext;
    attachStreamingStopButton(tempAiMessageId, streamContext);
    const streamStartedAt = Date.now();
    let accumulatedContent = '';
    let hasStreamedContent = false;
    let streamError = false;
    let streamCompleted = false;
    let lastChunkAt = null;
    let eventCount = 0;

    requestFactory(abortController.signal).then(response => {
        if (!response.ok) {
            if (response.status === 404) {
                throw new Error('No active stream is available for this conversation.');
            }
            return response.json().then(errData => {
                throw buildStreamingRequestError(errData, response.status);
            });
        }

        if (!response.body) {
            throw new Error('Streaming response body is unavailable.');
        }

        void reportClientStreamEvent('stream_response_opened', {
            conversation_id: recoveryConversationId,
            elapsed_ms: Date.now() - streamStartedAt,
            had_streamed_content: hasStreamedContent,
            event_count: eventCount,
        });
        
        // Read the streaming response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let sseBuffer = '';

        function processStreamData(data) {
            eventCount += 1;
            lastChunkAt = Date.now();

            if (data.error) {
                stopThoughtPolling();
                streamError = true;
                clearStreamingThoughtSession(tempAiMessageId);
                removeStreamingStopButton(tempAiMessageId);
                void reportClientStreamEvent('stream_read_error', {
                    conversation_id: recoveryConversationId,
                    elapsed_ms: Date.now() - streamStartedAt,
                    time_since_last_chunk_ms: 0,
                    had_streamed_content: hasStreamedContent,
                    event_count: eventCount,
                    error_message: data.error,
                });
                handleStreamError(tempAiMessageId, data.partial_content || accumulatedContent, data.error, data);
                clearCurrentStreamController(abortController);
                if (typeof onError === 'function') {
                    onError(data.error, data);
                }
                if (typeof onFinally === 'function') {
                    onFinally();
                }
                return true;
            }

            if (data.type === 'thought') {
                if (!hasStreamedContent && !streamCompleted) {
                    handleStreamingThought(data, tempAiMessageId);
                }
                return false;
            }

            if (data.type === 'conversation_metadata') {
                applyStreamingConversationMetadata(data);
                updateStreamContextConversation(streamContext, data.conversation_id || data.conversationId);
                return false;
            }

            if (data.conversation_id || data.conversationId) {
                updateStreamContextConversation(streamContext, data.conversation_id || data.conversationId);
            }

            if (data.content) {
                accumulatedContent += data.content;
                hasStreamedContent = true;
                updateStreamingMessage(tempAiMessageId, accumulatedContent);
            }

            if (data.done) {
                stopThoughtPolling();
                streamCompleted = true;
                clearStreamingThoughtSession(tempAiMessageId);

                if (data.cancelled || data.canceled || data.type === 'cancelled' || data.type === 'canceled') {
                    finalizeCancelledStreamingMessage(
                        tempAiMessageId,
                        tempUserMessageId,
                        data,
                        accumulatedContent,
                    );

                    if (typeof onDone === 'function') {
                        onDone(data);
                    }

                    if (typeof onFinally === 'function') {
                        onFinally();
                    }

                    clearCurrentStreamController(abortController);
                    return true;
                }

                finalizeStreamingMessage(
                    tempAiMessageId,
                    tempUserMessageId,
                    data,
                    fallbackAgentInfo
                );

                if (typeof onDone === 'function') {
                    onDone(data);
                }

                if (typeof onFinally === 'function') {
                    onFinally();
                }

                clearCurrentStreamController(abortController);
                return true;
            }

            return false;
        }

        function processSseEventBlock(eventBlock) {
            const jsonStr = parseSseEventPayload(eventBlock);
            if (!jsonStr) {
                return false;
            }

            try {
                const data = JSON.parse(jsonStr);
                return processStreamData(data);
            } catch (error) {
                console.error('Error parsing SSE data:', error);
                return false;
            }
        }

        function processSseBuffer(flush = false) {
            let delimiterIndex = sseBuffer.indexOf('\n\n');

            while (delimiterIndex !== -1) {
                const eventBlock = sseBuffer.slice(0, delimiterIndex);
                sseBuffer = sseBuffer.slice(delimiterIndex + 2);

                if (processSseEventBlock(eventBlock)) {
                    return true;
                }

                delimiterIndex = sseBuffer.indexOf('\n\n');
            }

            if (flush) {
                const trailingBlock = sseBuffer.trim();
                sseBuffer = '';

                if (trailingBlock) {
                    return processSseEventBlock(trailingBlock);
                }
            }

            return false;
        }
        
        function readStream() {
            reader.read().then(async ({ done, value }) => {
                if (done) {
                    stopThoughtPolling();

                    sseBuffer += normalizeLegacyEscapedSseDelimiters(decoder.decode());
                    const processedFinalEvent = processSseBuffer(true);

                    if (!processedFinalEvent && !streamCompleted && !streamError) {
                        clearCurrentStreamController(abortController);

                        void reportClientStreamEvent('stream_premature_end', {
                            conversation_id: recoveryConversationId,
                            elapsed_ms: Date.now() - streamStartedAt,
                            time_since_last_chunk_ms: lastChunkAt ? Date.now() - lastChunkAt : 0,
                            had_streamed_content: hasStreamedContent,
                            event_count: eventCount,
                            status: 'done_without_terminal_event',
                        });

                        if (allowRecovery) {
                            const recovered = await attemptStreamingRecovery(
                                recoveryConversationId,
                                tempAiMessageId,
                                tempUserMessageId,
                                {
                                    onDone,
                                    onError,
                                    onFinally,
                                    reconnectStatusLabel,
                                },
                            );
                            if (recovered) {
                                return;
                            }
                        }

                        clearStreamingThoughtSession(tempAiMessageId);
                        handleStreamError(
                            tempAiMessageId,
                            accumulatedContent,
                            'Stream ended before completion metadata was received.'
                        );

                        if (typeof onError === 'function') {
                            onError('Stream ended before completion metadata was received.');
                        }

                        if (typeof onFinally === 'function') {
                            onFinally();
                        }
                    }

                    return;
                }
                
                sseBuffer += normalizeLegacyEscapedSseDelimiters(
                    decoder.decode(value, { stream: true }).replace(/\r/g, '')
                );

                if (processSseBuffer() || streamCompleted || streamError) {
                    return;
                }
                
                readStream(); // Continue reading
            }).catch(async err => {
                if (abortController.signal.aborted) {
                    void reportClientStreamEvent('stream_aborted', {
                        conversation_id: recoveryConversationId,
                        elapsed_ms: Date.now() - streamStartedAt,
                        time_since_last_chunk_ms: lastChunkAt ? Date.now() - lastChunkAt : 0,
                        had_streamed_content: hasStreamedContent,
                        event_count: eventCount,
                        abort_reason: abortController.signal.reason || 'aborted',
                    });
                    clearStreamingThoughtSession(tempAiMessageId);
                    clearCurrentStreamController(abortController);
                    if (typeof onFinally === 'function') {
                        onFinally();
                    }
                    return;
                }

                stopThoughtPolling();
                console.error('Stream reading error:', err);
                void reportClientStreamEvent('stream_read_error', {
                    conversation_id: recoveryConversationId,
                    elapsed_ms: Date.now() - streamStartedAt,
                    time_since_last_chunk_ms: lastChunkAt ? Date.now() - lastChunkAt : 0,
                    had_streamed_content: hasStreamedContent,
                    event_count: eventCount,
                    error_message: err.message,
                });

                clearCurrentStreamController(abortController);
                if (allowRecovery) {
                    const recovered = await attemptStreamingRecovery(
                        recoveryConversationId,
                        tempAiMessageId,
                        tempUserMessageId,
                        {
                            onDone,
                            onError,
                            onFinally,
                            reconnectStatusLabel,
                        },
                    );
                    if (recovered) {
                        return;
                    }
                }

                clearStreamingThoughtSession(tempAiMessageId);
                handleStreamError(tempAiMessageId, accumulatedContent, err.message, err);
                if (typeof onError === 'function') {
                    onError(err.message, err);
                }
                if (typeof onFinally === 'function') {
                    onFinally();
                }
            });
        }
        
        readStream();
        
    }).catch(async error => {
        if (abortController.signal.aborted) {
            void reportClientStreamEvent('stream_aborted', {
                conversation_id: recoveryConversationId,
                elapsed_ms: Date.now() - streamStartedAt,
                time_since_last_chunk_ms: lastChunkAt ? Date.now() - lastChunkAt : 0,
                had_streamed_content: hasStreamedContent,
                event_count: eventCount,
                abort_reason: abortController.signal.reason || 'aborted',
            });
            clearStreamingThoughtSession(tempAiMessageId);
            clearCurrentStreamController(abortController);
            if (typeof onFinally === 'function') {
                onFinally();
            }
            return;
        }

        stopThoughtPolling();
        console.error('Streaming request error:', error);
        void reportClientStreamEvent('stream_request_error', {
            conversation_id: recoveryConversationId,
            elapsed_ms: Date.now() - streamStartedAt,
            time_since_last_chunk_ms: lastChunkAt ? Date.now() - lastChunkAt : 0,
            had_streamed_content: hasStreamedContent,
            event_count: eventCount,
            error_message: error.message,
        });

        clearCurrentStreamController(abortController);
        if (allowRecovery) {
            const recovered = await attemptStreamingRecovery(
                recoveryConversationId,
                tempAiMessageId,
                tempUserMessageId,
                {
                    onDone,
                    onError,
                    onFinally,
                    reconnectStatusLabel,
                },
            );
            if (recovered) {
                return;
            }
        }

        clearStreamingThoughtSession(tempAiMessageId);
        handleStreamError(tempAiMessageId, accumulatedContent, error.message, error);

        if (typeof onError === 'function') {
            onError(error.message, error);
        }

        if (typeof onFinally === 'function') {
            onFinally();
        }
    });

    return true; // Indicates streaming was initiated
}

export function sendMessageWithStreaming(messageData, tempUserMessageId, currentConversationId, options = {}) {
    const { endpoint = '/api/chat/stream' } = options;
    const tempAiMessageId = createStreamingPlaceholder();
    const recoveryConversationId = currentConversationId || messageData?.conversation_id || window.currentConversationId || null;

    return consumeStreamingResponse(
        signal => fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'same-origin',
            body: JSON.stringify(messageData),
            signal,
        }),
        tempAiMessageId,
        tempUserMessageId,
        {
            ...options,
            recoveryConversationId,
        },
    );
}

export async function reattachStreamingConversation(conversationId, options = {}) {
    const { statusLabel = 'Reconnecting...' } = options;

    if (!conversationId) {
        return false;
    }

    try {
        const statusData = await getStreamingStatus(conversationId);
        if (!statusData?.pending) {
            return false;
        }

        const tempAiMessageId = createStreamingPlaceholder(statusLabel);
        return consumeStreamingResponse(
            signal => fetch(`/api/chat/stream/reattach/${conversationId}`, {
                method: 'GET',
                credentials: 'same-origin',
                signal,
            }),
            tempAiMessageId,
            null,
            {
                allowRecovery: false,
                recoveryConversationId: conversationId,
                reconnectStatusLabel: statusLabel,
            },
        );
    } catch (error) {
        console.warn('Failed to reattach streaming conversation:', error);
        return false;
    }
}

export function updateStreamingMessage(messageId, content) {
    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageElement) return;

    markStreamingThoughtContentStarted(messageId);
    
    const contentElement = messageElement.querySelector('.message-text');
    if (contentElement) {
        // Render markdown during streaming for proper formatting
        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            const stableChartNodes = collectStableStreamingChartNodes(contentElement);
            const renderedContent = renderAiMessageContent(content);
            contentElement.innerHTML = renderedContent.htmlContent;
            restoreStableStreamingChartNodes(contentElement, stableChartNodes);
            hydrateInlineCharts(messageElement);
            hydrateInlineImageProposals(messageElement);
        } else {
            contentElement.textContent = content;
        }
        
        // Add subtle streaming cursor indicator
        if (!messageElement.querySelector('.streaming-cursor')) {
            const cursor = document.createElement('span');
            cursor.className = 'streaming-cursor';
            cursor.innerHTML = '<span class="badge bg-primary ms-2 animate-pulse"><i class="bi bi-lightning-fill"></i> Streaming</span>';
            contentElement.appendChild(cursor);
        }
    }
}

function getStreamingChartInstance(chartContainer) {
    const canvas = chartContainer?.querySelector('canvas');
    if (!canvas) {
        return null;
    }

    if (chartContainer._chartInstance) {
        return chartContainer._chartInstance;
    }

    if (typeof window.Chart !== 'undefined' && typeof window.Chart.getChart === 'function') {
        return window.Chart.getChart(canvas);
    }

    return null;
}

function collectStableStreamingChartNodes(contentElement) {
    const stableChartNodes = new Map();
    contentElement.querySelectorAll('.sc-inline-chart:not([data-chart-hydrated="status"])').forEach(chartContainer => {
        const chartSpec = chartContainer.getAttribute('data-chart-spec') || '';
        if (!chartSpec || chartContainer.getAttribute('data-chart-hydrated') !== 'true') {
            return;
        }

        if (!getStreamingChartInstance(chartContainer)) {
            return;
        }

        if (!stableChartNodes.has(chartSpec)) {
            stableChartNodes.set(chartSpec, []);
        }
        stableChartNodes.get(chartSpec).push(chartContainer);
    });
    return stableChartNodes;
}

function restoreStableStreamingChartNodes(contentElement, stableChartNodes) {
    const reusedChartNodes = new Set();
    contentElement.querySelectorAll('.sc-inline-chart:not([data-chart-hydrated="status"])').forEach(newChartContainer => {
        const chartSpec = newChartContainer.getAttribute('data-chart-spec') || '';
        const matchingChartNodes = chartSpec ? stableChartNodes.get(chartSpec) : null;
        const stableChartNode = matchingChartNodes?.shift();
        if (!stableChartNode) {
            return;
        }

        newChartContainer.replaceWith(stableChartNode);
        reusedChartNodes.add(stableChartNode);
    });

    stableChartNodes.forEach(chartNodes => {
        chartNodes.forEach(chartNode => {
            if (!reusedChartNodes.has(chartNode)) {
                destroyInlineCharts(chartNode);
            }
        });
    });
}

function appendStoppedResponseBanner(messageElement, hasPartialContent) {
    const contentElement = messageElement?.querySelector('.message-text');
    if (!contentElement || contentElement.querySelector('.stream-stopped-banner')) {
        return;
    }

    const banner = document.createElement('div');
    banner.className = 'alert alert-info stream-stopped-banner mt-2 mb-0';

    const icon = document.createElement('i');
    icon.className = 'bi bi-stop-circle me-2';
    icon.setAttribute('aria-hidden', 'true');
    banner.appendChild(icon);

    const strong = document.createElement('strong');
    strong.textContent = 'Stopped by you.';
    banner.appendChild(strong);

    banner.appendChild(document.createTextNode(
        hasPartialContent ? ' Response may be incomplete.' : ' No response content was received.'
    ));

    contentElement.appendChild(banner);
}

function renderStoppedContent(messageElement, partialContent) {
    const contentElement = messageElement?.querySelector('.message-text');
    if (!contentElement) {
        return;
    }

    const cursor = contentElement.querySelector('.streaming-cursor');
    if (cursor) {
        cursor.remove();
    }

    const normalizedContent = String(partialContent || '').trim();
    if (normalizedContent) {
        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            const renderedContent = renderAiMessageContent(normalizedContent);
            contentElement.innerHTML = renderedContent.htmlContent;
            hydrateInlineCharts(messageElement);
        } else {
            contentElement.textContent = normalizedContent;
        }
    } else {
        contentElement.textContent = 'Response stopped before any content was received.';
    }

    appendStoppedResponseBanner(messageElement, Boolean(normalizedContent));
}

function finalizeCancelledStreamingMessage(messageId, userMessageId, finalData, fallbackContent = '') {
    const messageElement = getStreamingMessageElement(messageId);
    const partialContent = finalData.full_content || finalData.partial_content || fallbackContent || '';

    if (finalData.user_message_id && userMessageId) {
        updateUserMessageId(userMessageId, finalData.user_message_id);
    }

    removeStreamingStopButton(messageId);

    if (finalData.message_id && finalData.message_persisted) {
        if (messageElement) {
            messageElement.remove();
        }

        const existingFinalMessage = document.querySelector(`[data-message-id="${finalData.message_id}"]`);
        if (!existingFinalMessage) {
            const finalMessageObject = {
                ...finalData,
                content: partialContent,
                role: finalData.role || 'assistant',
                metadata: {
                    ...(finalData.metadata || {}),
                    incomplete: true,
                    canceled: true,
                },
            };

            appendMessage(
                'AI',
                partialContent,
                finalData.model_deployment_name,
                finalData.message_id,
                finalData.augmented,
                finalData.hybrid_citations || [],
                finalData.web_search_citations || [],
                finalData.agent_citations || [],
                finalData.agent_display_name || null,
                finalData.agent_name || null,
                finalMessageObject,
                false
            );
        }

        appendStoppedResponseBanner(
            document.querySelector(`[data-message-id="${finalData.message_id}"]`),
            Boolean(String(partialContent || '').trim())
        );
    } else if (messageElement) {
        renderStoppedContent(messageElement, partialContent);
    }

    if (finalData.conversation_id) {
        markConversationRead(finalData.conversation_id, { force: true, suppressErrorToast: true }).catch(error => {
            console.warn('Failed to clear unread state after stream cancellation:', error);
        });
    }
}

function normalizeFallbackAgentIcon(iconPayload) {
    if (!iconPayload || typeof iconPayload !== 'object' || Array.isArray(iconPayload)) {
        return null;
    }

    const kind = String(iconPayload.kind || '').trim().toLowerCase();
    const value = String(iconPayload.value || '').trim();
    if (kind === 'bootstrap' && /^bi-[a-z0-9][a-z0-9-]{0,80}$/.test(value)) {
        return { kind, value };
    }
    if (kind === 'image' && /^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(value) && value.length <= 350000) {
        return { kind, value };
    }
    return null;
}

function applyFallbackAgentIcon(finalData = {}, fallbackAgentInfo = null) {
    if (!fallbackAgentInfo || typeof fallbackAgentInfo !== 'object' || finalData.agent_icon) {
        return finalData;
    }

    const fallbackIcon = normalizeFallbackAgentIcon(fallbackAgentInfo.icon || fallbackAgentInfo.agent_icon);
    if (!fallbackIcon) {
        return finalData;
    }

    return {
        ...finalData,
        agent_icon: fallbackIcon,
        metadata: {
            ...(finalData.metadata || {}),
            agent_selection: {
                ...(finalData.metadata?.agent_selection || {}),
                agent_icon: fallbackIcon,
            },
        },
    };
}

function handleStreamError(messageId, partialContent, errorMessage, errorDetails = {}) {
    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageElement) return;

    const errorPayload = getStreamErrorPayload(errorDetails);
    const displayMessage = String(
        errorMessage || errorPayload.error || errorPayload.message || 'An unknown streaming error occurred.'
    ).trim();

    removeStreamingStopButton(messageId);
    
    const contentElement = messageElement.querySelector('.message-text');
    if (contentElement) {
        // Remove streaming cursor
        const cursor = contentElement.querySelector('.streaming-cursor');
        if (cursor) cursor.remove();
        
        // Show partial content with error banner
        let finalContent = partialContent || 'Stream interrupted before any content was received.';
        
        // Parse markdown for partial content
        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            finalContent = renderAiMessageContent(finalContent).htmlContent;
        }
        
        contentElement.innerHTML = finalContent;
        hydrateInlineCharts(messageElement);

        appendStreamErrorBanner(contentElement, displayMessage, errorPayload);
    }

    showToast(`Stream error: ${displayMessage}`, 'error');
}

function finalizeStreamingMessage(messageId, userMessageId, finalData, fallbackAgentInfo = null) {
    finalData = applyFallbackAgentIcon(finalData, fallbackAgentInfo);
    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageElement) return;

    removeStreamingStopButton(messageId);
    
    // Update user message ID first
    if (finalData.user_message_id && userMessageId) {
        updateUserMessageId(userMessageId, finalData.user_message_id);
    }
    
    // Remove the temporary streaming message
    messageElement.remove();

    const existingFinalMessage = finalData.message_id
        ? document.querySelector(`[data-message-id="${finalData.message_id}"]`)
        : null;

    if (finalData.kernel_fallback_notice) {
        showToast(finalData.kernel_fallback_notice, 'warning');
    }

    if (existingFinalMessage) {
        if (finalData.conversation_id) {
            markConversationRead(finalData.conversation_id, { force: true, suppressErrorToast: true }).catch(error => {
                console.warn('Failed to clear unread state after live streaming completion:', error);
            });
        }
        return;
    }

    const finalMessageObject = {
        ...finalData,
        content: finalData.full_content || finalData.content || '',
        role: finalData.role || 'assistant',
    };

    if (finalData.image_url) {
        appendMessage(
            'image',
            finalData.image_url,
            finalData.model_deployment_name,
            finalData.message_id,
            false,
            [],
            [],
            finalData.agent_citations || [],
            finalData.agent_display_name || null,
            finalData.agent_name || null,
            finalMessageObject,
            true
        );

        if (finalData.reload_messages && finalData.conversation_id && typeof window.chatMessages?.loadMessages === 'function') {
            window.chatMessages.loadMessages(finalData.conversation_id);
        }
        return;
    }

    const sender = finalData.role === 'safety' || finalData.blocked ? 'safety' : 'AI';
    
    // Create proper message with all metadata using appendMessage
    appendMessage(
        sender,
        finalData.full_content || '',
        finalData.model_deployment_name,
        finalData.message_id,
        finalData.augmented,
        finalData.hybrid_citations || [],
        finalData.web_search_citations || [],
        finalData.agent_citations || [],
        finalData.agent_display_name || null,
        finalData.agent_name || null,
        finalMessageObject,
        true // isNewMessage - trigger autoplay for new streaming responses
    );
    
    // Update conversation if needed
    if (finalData.conversation_id && window.currentConversationId !== finalData.conversation_id) {
        window.currentConversationId = finalData.conversation_id;
    }
    
    const metadataUpdates = {};
    if (finalData.conversation_title !== undefined) {
        metadataUpdates.title = finalData.conversation_title;
    }
    if (Array.isArray(finalData.classification)) {
        metadataUpdates.classification = finalData.classification;
    }
    if (Array.isArray(finalData.context)) {
        metadataUpdates.context = finalData.context;
    }
    if (finalData.chat_type !== undefined) {
        metadataUpdates.chat_type = finalData.chat_type || null;
    }

    if (finalData.conversation_id && Object.keys(metadataUpdates).length > 0) {
        applyConversationMetadataUpdate(finalData.conversation_id, {
            ...metadataUpdates,
        });
    }

    if (finalData.scope_locked === true && finalData.locked_contexts) {
        applyScopeLock(finalData.locked_contexts, finalData.scope_locked);
    } else if (finalData.augmented && finalData.conversation_id) {
        fetch(`/api/conversations/${finalData.conversation_id}/metadata`, { credentials: 'same-origin' })
            .then(r => r.json())
            .then(metadata => {
                if (metadata.scope_locked === true && metadata.locked_contexts) {
                    applyScopeLock(metadata.locked_contexts, metadata.scope_locked);
                }
            })
            .catch(err => console.warn('Failed to fetch scope lock metadata after streaming:', err));
    }

    if (finalData.reload_messages && finalData.conversation_id && typeof window.chatMessages?.loadMessages === 'function') {
        window.chatMessages.loadMessages(finalData.conversation_id);
    }

    if (finalData.conversation_id) {
        markConversationRead(finalData.conversation_id, { force: true, suppressErrorToast: true }).catch(error => {
            console.warn('Failed to clear unread state after live streaming completion:', error);
        });
    }
}

export function cancelStreaming() {
    if (currentStreamContext) {
        void requestStreamCancellation(currentStreamContext);
        return;
    }

    if (currentStreamController) {
        currentStreamController.abort('cancelled');
        currentStreamController = null;
        currentStreamContext = null;
        showToast('Streaming cancelled', 'info');
    }
}
