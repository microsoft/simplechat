// chat-streaming.js
import { appendMessage, updateUserMessageId } from './chat-messages.js';
import { hideLoadingIndicatorInChatbox, showLoadingIndicatorInChatbox } from './chat-loading-indicator.js';
import { loadUserSettings, saveUserSetting } from './chat-layout.js';
import { showToast } from './chat-toast.js';
import { updateSidebarConversationTitle } from './chat-sidebar-conversations.js';

let streamingEnabled = false;
let currentEventSource = null;

export function initializeStreamingToggle() {
    const streamingToggleBtn = document.getElementById('streaming-toggle-btn');
    if (!streamingToggleBtn) {
        console.warn('Streaming toggle button not found');
        return;
    }
    
    console.log('Initializing streaming toggle...');
    
    // Load initial state from user settings
    loadUserSettings().then(settings => {
        console.log('Loaded user settings:', settings);
        streamingEnabled = settings.streamingEnabled === true;
        console.log('Streaming enabled:', streamingEnabled);
        updateStreamingButtonState();
        updateStreamingButtonVisibility();
    }).catch(error => {
        console.error('Error loading streaming settings:', error);
    });
    
    // Handle toggle click
    streamingToggleBtn.addEventListener('click', () => {
        streamingEnabled = !streamingEnabled;
        console.log('Streaming toggled to:', streamingEnabled);
        
        // Save the setting
        console.log('Saving streaming setting...');
        saveUserSetting({ streamingEnabled });
        
        updateStreamingButtonState();
        
        const message = streamingEnabled 
            ? 'Streaming enabled - responses will appear in real-time' 
            : 'Streaming disabled - responses will appear when complete';
        showToast(message, 'info');
    });
    
    // Listen for agents toggle - hide streaming button when agents are active
    const enableAgentsBtn = document.getElementById('enable-agents-btn');
    if (enableAgentsBtn) {
        const observer = new MutationObserver(() => {
            updateStreamingButtonVisibility();
        });
        observer.observe(enableAgentsBtn, { attributes: true, attributeFilter: ['class'] });
    }
    
    updateStreamingButtonVisibility();
}

function updateStreamingButtonState() {
    const streamingToggleBtn = document.getElementById('streaming-toggle-btn');
    if (!streamingToggleBtn) return;
    
    // Check if TTS autoplay is enabled
    let ttsAutoplayEnabled = false;
    if (typeof window.appSettings !== 'undefined' && window.appSettings.enable_text_to_speech) {
        const cachedSettings = JSON.parse(localStorage.getItem('userSettings') || '{}');
        ttsAutoplayEnabled = cachedSettings.settings?.ttsAutoplay === true;
    }
    
    if (ttsAutoplayEnabled) {
        // Disable streaming button when TTS autoplay is on
        streamingToggleBtn.classList.remove('btn-primary');
        streamingToggleBtn.classList.add('btn-outline-secondary', 'disabled');
        streamingToggleBtn.disabled = true;
        streamingToggleBtn.title = 'Streaming disabled - TTS autoplay is enabled. Disable TTS autoplay in your profile to enable streaming.';
    } else if (streamingEnabled) {
        streamingToggleBtn.classList.remove('btn-outline-secondary', 'disabled');
        streamingToggleBtn.classList.add('btn-primary');
        streamingToggleBtn.disabled = false;
        streamingToggleBtn.title = 'Streaming enabled - click to disable';
    } else {
        streamingToggleBtn.classList.remove('btn-primary', 'disabled');
        streamingToggleBtn.classList.add('btn-outline-secondary');
        streamingToggleBtn.disabled = false;
        streamingToggleBtn.title = 'Streaming disabled - click to enable';
    }
}

/**
 * Update streaming button visibility based on agent state
 */
function updateStreamingButtonVisibility() {
    const streamingToggleBtn = document.getElementById('streaming-toggle-btn');
    const enableAgentsBtn = document.getElementById('enable-agents-btn');
    
    if (!streamingToggleBtn) return;
    
    // Show streaming button even when agents are active (agents now support streaming)
    streamingToggleBtn.style.display = 'flex';
}

export function isStreamingEnabled() {
    // Check if TTS autoplay is enabled - streaming is incompatible with TTS autoplay
    if (typeof window.appSettings !== 'undefined' && window.appSettings.enable_text_to_speech) {
        // Dynamically check TTS settings
        loadUserSettings().then(settings => {
            if (settings.ttsAutoplay === true) {
                console.log('TTS autoplay enabled - streaming disabled');
            }
        }).catch(error => {
            console.error('Error checking TTS settings:', error);
        });
        
        // Synchronous check using cached value if available
        const cachedSettings = JSON.parse(localStorage.getItem('userSettings') || '{}');
        if (cachedSettings.settings?.ttsAutoplay === true) {
            return false; // Disable streaming when TTS autoplay is active
        }
    }
    
    // Check if image generation is active - streaming is incompatible with image gen
    const imageGenBtn = document.getElementById('image-generate-btn');
    if (imageGenBtn && imageGenBtn.classList.contains('active')) {
        return false; // Disable streaming when image generation is active
    }
    return streamingEnabled;
}

export function sendMessageWithStreaming(messageData, tempUserMessageId, currentConversationId) {
    if (!streamingEnabled) {
        return null; // Caller should use regular fetch
    }
    
    // Double-check: never stream if image generation is active
    const imageGenBtn = document.getElementById('image-generate-btn');
    if (imageGenBtn && imageGenBtn.classList.contains('active')) {
        return null; // Force regular fetch for image generation
    }
    
    // Close any existing connection
    if (currentEventSource) {
        currentEventSource.close();
        currentEventSource = null;
    }
    
    // Create a unique message ID for the AI response
    const tempAiMessageId = `temp_ai_${Date.now()}`;
    let accumulatedContent = '';
    let streamError = false;
    let streamErrorMessage = '';
    
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
        
        function readStream() {
            reader.read().then(({ done, value }) => {
                if (done) {
                    clearTimeout(streamTimeout);
                    return;
                }
                
                const chunk = decoder.decode(value, { stream: true });
                const lines = chunk.split('\n');
                
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const jsonStr = line.substring(6); // Remove 'data: '
                            const data = JSON.parse(jsonStr);
                            
                            if (data.error) {
                                clearTimeout(streamTimeout);
                                streamError = true;
                                streamErrorMessage = data.error;
                                handleStreamError(tempAiMessageId, data.partial_content || accumulatedContent, data.error);
                                return;
                            }
                            
                            if (data.content) {
                                // Append chunk to accumulated content
                                accumulatedContent += data.content;
                                updateStreamingMessage(tempAiMessageId, accumulatedContent);
                            }
                            
                            if (data.done) {
                                clearTimeout(streamTimeout);
                                
                                // Update with final metadata
                                finalizeStreamingMessage(
                                    tempAiMessageId,
                                    tempUserMessageId,
                                    data
                                );
                                
                                currentEventSource = null;
                                return;
                            }
                        } catch (e) {
                            console.error('Error parsing SSE data:', e);
                        }
                    }
                }
                
                readStream(); // Continue reading
            }).catch(err => {
                clearTimeout(streamTimeout);
                console.error('Stream reading error:', err);
                handleStreamError(tempAiMessageId, accumulatedContent, err.message);
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
    });
    
    return true; // Indicates streaming was initiated
}

function updateStreamingMessage(messageId, content) {
    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageElement) return;
    
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
    
    // Create proper message with all metadata using appendMessage
    appendMessage(
        'AI',
        finalData.full_content || '',
        finalData.model_deployment_name,
        finalData.message_id,
        finalData.augmented,
        finalData.hybrid_citations || [],
        [],
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
}

export function cancelStreaming() {
    if (currentEventSource) {
        currentEventSource.close();
        currentEventSource = null;
        showToast('Streaming cancelled', 'info');
    }
}
