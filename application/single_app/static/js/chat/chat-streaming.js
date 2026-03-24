// chat-streaming.js
import { appendMessage, updateUserMessageId } from './chat-messages.js';
import { markConversationRead } from './chat-conversations.js';
import { hideLoadingIndicatorInChatbox, showLoadingIndicatorInChatbox } from './chat-loading-indicator.js';
import { showToast } from './chat-toast.js';
import { updateSidebarConversationTitle } from './chat-sidebar-conversations.js';
import { applyScopeLock } from './chat-documents.js';
import { handleStreamingThought } from './chat-thoughts.js';

let currentEventSource = null;

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

export function sendMessageWithStreaming(messageData, tempUserMessageId, currentConversationId, options = {}) {
    const {
        onDone = null,
        onError = null,
        onFinally = null,
    } = options;
    
    // Close any existing connection
    if (currentEventSource) {
        currentEventSource.close();
        currentEventSource = null;
    }
    
    // Create a unique message ID for the AI response
    const tempAiMessageId = `temp_ai_${Date.now()}`;
    let accumulatedContent = '';
    let hasStreamedContent = false;
    let streamError = false;
    let streamErrorMessage = '';
    let streamCompleted = false;
    
    // Create placeholder message with streaming indicator
    appendMessage('AI', '<span class="text-muted"><i class="bi bi-three-dots-vertical"></i> Streaming...</span>', null, tempAiMessageId);
    
    // Create timeout (5 minutes)
    const streamTimeout = setTimeout(() => {
        if (currentEventSource) {
            currentEventSource.close();
            currentEventSource = null;
            streamError = true;
            streamErrorMessage = 'Stream timeout (5 minutes exceeded)';
            handleStreamError(tempAiMessageId, accumulatedContent, streamErrorMessage);
        }
    }, 5 * 60 * 1000); // 5 minutes
    
    // Use fetch to POST, then read the streaming response
    fetch('/api/chat/stream', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify(messageData)
    }).then(response => {
        if (!response.ok) {
            return response.json().then(errData => {
                throw new Error(errData.error || `HTTP error! status: ${response.status}`);
            });
        }
        
        // Read the streaming response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let sseBuffer = '';

        function processStreamData(data) {
            if (data.error) {
                clearTimeout(streamTimeout);
                streamError = true;
                streamErrorMessage = data.error;
                handleStreamError(tempAiMessageId, data.partial_content || accumulatedContent, data.error);
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
                    handleStreamingThought(data);
                }
                return false;
            }

            if (data.content) {
                accumulatedContent += data.content;
                hasStreamedContent = true;
                updateStreamingMessage(tempAiMessageId, accumulatedContent);
            }

            if (data.done) {
                clearTimeout(streamTimeout);
                streamCompleted = true;

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

                currentEventSource = null;
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
            reader.read().then(({ done, value }) => {
                if (done) {
                    clearTimeout(streamTimeout);

                    sseBuffer += decoder.decode();
                    const processedFinalEvent = processSseBuffer(true);

                    if (!processedFinalEvent && !streamCompleted && !streamError) {
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
            }).catch(err => {
                clearTimeout(streamTimeout);
                console.error('Stream reading error:', err);
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
        
    }).catch(error => {
        clearTimeout(streamTimeout);
        console.error('Streaming request error:', error);
        showToast(`Error: ${error.message}`, 'error');
        
        // Remove placeholder message
        const msgElement = document.querySelector(`[data-message-id="${tempAiMessageId}"]`);
        if (msgElement) {
            msgElement.remove();
        }

        if (typeof onError === 'function') {
            onError(error.message, error);
        }

        if (typeof onFinally === 'function') {
            onFinally();
        }
    });
    
    return true; // Indicates streaming was initiated
}

function updateStreamingMessage(messageId, content) {
    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageElement) return;

    messageElement.dataset.streamingHasContent = 'true';
    
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
        const titleElement = document.getElementById('current-conversation-title');
        if (titleElement && titleElement.textContent === 'New Conversation') {
            titleElement.textContent = finalData.conversation_title;
        }
        
        // Update sidebar conversation title in real-time
        updateSidebarConversationTitle(finalData.conversation_id, finalData.conversation_title);
    }

    // Apply scope lock if document search was used
    if (finalData.augmented && finalData.conversation_id) {
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
    if (currentEventSource) {
        currentEventSource.close();
        currentEventSource = null;
        showToast('Streaming cancelled', 'info');
    }
}
