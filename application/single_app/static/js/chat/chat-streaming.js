// chat-streaming.js
import { appendMessage, updateUserMessageId } from './chat-messages.js';
import { applyConversationMetadataUpdate, markConversationRead } from './chat-conversations.js';
import { hideLoadingIndicatorInChatbox, showLoadingIndicatorInChatbox } from './chat-loading-indicator.js';
import { showToast } from './chat-toast.js';
import { updateSidebarConversationTitle } from './chat-sidebar-conversations.js';
import { applyScopeLock } from './chat-documents.js';
import { beginStreamingThoughtSession, clearStreamingThoughtSession, handleStreamingThought, markStreamingThoughtContentStarted, stopThoughtPolling } from './chat-thoughts.js';

let currentStreamController = null;

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

function createStreamingPlaceholder(statusLabel = 'Streaming...') {
    const tempAiMessageId = `temp_ai_${Date.now()}_${Math.floor(Math.random() * 10000)}`;
    appendMessage('AI', `<span class="text-muted"><i class="bi bi-three-dots-vertical"></i> ${statusLabel}</span>`, null, tempAiMessageId);
    beginStreamingThoughtSession(tempAiMessageId);
    return tempAiMessageId;
}

function clearCurrentStreamController(controller) {
    if (currentStreamController === controller) {
        currentStreamController = null;
    }
}

function removeStreamingPlaceholder(messageId) {
    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (messageElement) {
        messageElement.remove();
    }
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
            return false;
        }

        clearStreamingThoughtSession(failedMessageId);
        removeStreamingPlaceholder(failedMessageId);

        const reconnectMessageId = createStreamingPlaceholder(reconnectStatusLabel);
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
        reconnectStatusLabel = 'Reconnecting...',
    } = options;

    if (currentStreamController) {
        currentStreamController.abort('replaced');
    }

    const abortController = new AbortController();
    currentStreamController = abortController;
    let accumulatedContent = '';
    let hasStreamedContent = false;
    let streamError = false;
    let streamCompleted = false;

    requestFactory(abortController.signal).then(response => {
        if (!response.ok) {
            if (response.status === 404) {
                throw new Error('No active stream is available for this conversation.');
            }
            return response.json().then(errData => {
                throw new Error(errData.error || `HTTP error! status: ${response.status}`);
            });
        }

        if (!response.body) {
            throw new Error('Streaming response body is unavailable.');
        }
        
        // Read the streaming response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let sseBuffer = '';

        function processStreamData(data) {
            if (data.error) {
                stopThoughtPolling();
                streamError = true;
                clearStreamingThoughtSession(tempAiMessageId);
                handleStreamError(tempAiMessageId, data.partial_content || accumulatedContent, data.error);
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

            if (data.content) {
                accumulatedContent += data.content;
                hasStreamedContent = true;
                updateStreamingMessage(tempAiMessageId, accumulatedContent);
            }

            if (data.done) {
                stopThoughtPolling();
                streamCompleted = true;
                clearStreamingThoughtSession(tempAiMessageId);

                finalizeStreamingMessage(
                    tempAiMessageId,
                    tempUserMessageId,
                    data
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

                    sseBuffer += decoder.decode();
                    const processedFinalEvent = processSseBuffer(true);

                    if (!processedFinalEvent && !streamCompleted && !streamError) {
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
                
                sseBuffer += decoder.decode(value, { stream: true }).replace(/\r/g, '');

                if (processSseBuffer() || streamCompleted || streamError) {
                    return;
                }
                
                readStream(); // Continue reading
            }).catch(async err => {
                if (abortController.signal.aborted) {
                    clearStreamingThoughtSession(tempAiMessageId);
                    clearCurrentStreamController(abortController);
                    if (typeof onFinally === 'function') {
                        onFinally();
                    }
                    return;
                }

                stopThoughtPolling();
                console.error('Stream reading error:', err);

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
                handleStreamError(tempAiMessageId, accumulatedContent, err.message);
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
            clearStreamingThoughtSession(tempAiMessageId);
            clearCurrentStreamController(abortController);
            if (typeof onFinally === 'function') {
                onFinally();
            }
            return;
        }

        stopThoughtPolling();
        console.error('Streaming request error:', error);

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

        showToast(`Error: ${error.message}`, 'error');
        clearStreamingThoughtSession(tempAiMessageId);
        
        // Remove placeholder message
        removeStreamingPlaceholder(tempAiMessageId);

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
    const tempAiMessageId = createStreamingPlaceholder('Streaming...');
    const recoveryConversationId = currentConversationId || messageData?.conversation_id || window.currentConversationId || null;

    return consumeStreamingResponse(
        signal => fetch('/api/chat/stream', {
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

function updateStreamingMessage(messageId, content) {
    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageElement) return;

    markStreamingThoughtContentStarted(messageId);
    
    const contentElement = messageElement.querySelector('.message-text');
    if (contentElement) {
        // Render markdown during streaming for proper formatting
        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            const renderedContent = DOMPurify.sanitize(marked.parse(content));
            contentElement.innerHTML = renderedContent;
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

function handleStreamError(messageId, partialContent, errorMessage) {
    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageElement) return;
    
    const contentElement = messageElement.querySelector('.message-text');
    if (contentElement) {
        // Remove streaming cursor
        const cursor = contentElement.querySelector('.streaming-cursor');
        if (cursor) cursor.remove();
        
        // Show partial content with error banner
        let finalContent = partialContent || 'Stream interrupted before any content was received.';
        
        // Parse markdown for partial content
        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            finalContent = DOMPurify.sanitize(marked.parse(finalContent));
        }
        
        contentElement.innerHTML = finalContent;
        
        // Add error banner
        const errorBanner = document.createElement('div');
        errorBanner.className = 'alert alert-warning mt-2 mb-0';
        errorBanner.innerHTML = `
            <i class="bi bi-exclamation-triangle me-2"></i>
            <strong>Stream interrupted:</strong> ${errorMessage}
            <br>
            <small>Response may be incomplete. The partial content above has been saved.</small>
        `;
        contentElement.appendChild(errorBanner);
    }
    
    showToast(`Stream error: ${errorMessage}`, 'error');
}

function finalizeStreamingMessage(messageId, userMessageId, finalData) {
    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageElement) return;
    
    // Update user message ID first
    if (finalData.user_message_id && userMessageId) {
        updateUserMessageId(userMessageId, finalData.user_message_id);
    }
    
    // Remove the temporary streaming message
    messageElement.remove();

    if (finalData.kernel_fallback_notice) {
        showToast(finalData.kernel_fallback_notice, 'warning');
    }

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
            null,
            true
        );

        if (finalData.reload_messages && finalData.conversation_id && typeof window.chatMessages?.loadMessages === 'function') {
            window.chatMessages.loadMessages(finalData.conversation_id);
        }
        return;
    }
    
    // Create proper message with all metadata using appendMessage
    appendMessage(
        'AI',
        finalData.full_content || '',
        finalData.model_deployment_name,
        finalData.message_id,
        finalData.augmented,
        finalData.hybrid_citations || [],
        finalData.web_search_citations || [],
        finalData.agent_citations || [],
        finalData.agent_display_name || null,
        finalData.agent_name || null,
        null,
        true // isNewMessage - trigger autoplay for new streaming responses
    );
    
    // Update conversation if needed
    if (finalData.conversation_id && window.currentConversationId !== finalData.conversation_id) {
        window.currentConversationId = finalData.conversation_id;
    }
    
    if (finalData.conversation_title) {
        applyConversationMetadataUpdate(finalData.conversation_id, {
            title: finalData.conversation_title,
            classification: finalData.classification || [],
            context: finalData.context || [],
            chat_type: finalData.chat_type || null,
        });

        // Update sidebar conversation title in real-time
        updateSidebarConversationTitle(finalData.conversation_id, finalData.conversation_title);
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
    if (currentStreamController) {
        currentStreamController.abort('cancelled');
        currentStreamController = null;
        showToast('Streaming cancelled', 'info');
    }
}
