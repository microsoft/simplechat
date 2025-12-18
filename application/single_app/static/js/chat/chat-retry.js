// chat-retry.js
// Handles message retry/regenerate functionality

import { showToast } from './chat-toast.js';
import { showLoadingIndicatorInChatbox, hideLoadingIndicatorInChatbox } from './chat-loading-indicator.js';

/**
 * Handle retry button click - opens retry modal
 */
export function handleRetryButtonClick(messageDiv, messageId, messageType) {
    console.log(`🔄 Retry button clicked for ${messageType} message: ${messageId}`);
    
    // Store message info for retry execution
    window.pendingMessageRetry = {
        messageDiv,
        messageId,
        messageType
    };
    
    // Populate retry modal with current model options
    const modelSelect = document.getElementById('model-select');
    const retryModelSelect = document.getElementById('retry-model-select');
    
    if (modelSelect && retryModelSelect) {
        // Clone model options from main select
        retryModelSelect.innerHTML = modelSelect.innerHTML;
        retryModelSelect.value = modelSelect.value; // Set to currently selected model
    }
    
    // Handle reasoning effort for o1 models
    const selectedModel = retryModelSelect ? retryModelSelect.value : null;
    const retryReasoningContainer = document.getElementById('retry-reasoning-container');
    const retryReasoningLevels = document.getElementById('retry-reasoning-levels');
    
    if (selectedModel && selectedModel.includes('o1')) {
        // Show reasoning effort for o1 models
        if (retryReasoningContainer) {
            retryReasoningContainer.style.display = 'block';
            
            // Populate reasoning levels if empty
            if (retryReasoningLevels && !retryReasoningLevels.hasChildNodes()) {
                const levels = [
                    { value: 'low', label: 'Low', description: 'Faster responses' },
                    { value: 'medium', label: 'Medium', description: 'Balanced' },
                    { value: 'high', label: 'High', description: 'More thorough reasoning' }
                ];
                
                levels.forEach(level => {
                    const div = document.createElement('div');
                    div.className = 'form-check';
                    div.innerHTML = `
                        <input class="form-check-input" type="radio" name="retry-reasoning-effort" 
                               id="retry-reasoning-${level.value}" value="${level.value}" 
                               ${level.value === 'medium' ? 'checked' : ''}>
                        <label class="form-check-label" for="retry-reasoning-${level.value}">
                            <strong>${level.label}</strong> - ${level.description}
                        </label>
                    `;
                    retryReasoningLevels.appendChild(div);
                });
            }
        }
    } else {
        // Hide reasoning effort for non-o1 models
        if (retryReasoningContainer) {
            retryReasoningContainer.style.display = 'none';
        }
    }
    
    // Update reasoning visibility when model changes in retry modal
    if (retryModelSelect) {
        retryModelSelect.addEventListener('change', function() {
            const model = this.value;
            if (retryReasoningContainer) {
                retryReasoningContainer.style.display = model && model.includes('o1') ? 'block' : 'none';
            }
        });
    }
    
    // Show the retry modal
    const retryModal = new bootstrap.Modal(document.getElementById('retry-message-modal'));
    retryModal.show();
}

/**
 * Execute message retry - called when user confirms retry in modal
 */
window.executeMessageRetry = function() {
    const pendingRetry = window.pendingMessageRetry;
    if (!pendingRetry) {
        console.error('❌ No pending retry found');
        return;
    }
    
    const { messageDiv, messageId, messageType } = pendingRetry;
    
    console.log(`🚀 Executing retry for ${messageType} message: ${messageId}`);
    
    // Get selected model and reasoning effort from retry modal
    const retryModelSelect = document.getElementById('retry-model-select');
    const selectedModel = retryModelSelect ? retryModelSelect.value : null;
    
    let reasoningEffort = null;
    const retryReasoningContainer = document.getElementById('retry-reasoning-container');
    if (retryReasoningContainer && retryReasoningContainer.style.display !== 'none') {
        const selectedReasoning = document.querySelector('input[name="retry-reasoning-effort"]:checked');
        reasoningEffort = selectedReasoning ? selectedReasoning.value : null;
    }
    
    console.log(`📊 Retry settings - Model: ${selectedModel}, Reasoning: ${reasoningEffort}`);
    
    // Close the modal explicitly
    const modalElement = document.getElementById('retry-message-modal');
    if (modalElement) {
        const modalInstance = bootstrap.Modal.getInstance(modalElement);
        if (modalInstance) {
            modalInstance.hide();
        }
    }
    
    // Wait a bit for modal to close, then show loading indicator
    setTimeout(() => {
        console.log('⏰ Modal closed, showing AI typing indicator...');
        
        // Show "AI is typing..." indicator
        showLoadingIndicatorInChatbox();
        
        // Call retry API endpoint
        console.log('📡 Calling retry API endpoint...');
        fetch(`/api/message/${messageId}/retry`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            model: selectedModel,
            reasoning_effort: reasoningEffort
        })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(data => {
                throw new Error(data.error || 'Retry failed');
            });
        }
        return response.json();
    })
    .then(data => {
        console.log('✅ Retry API response:', data);
        
        if (data.success && data.chat_request) {
            console.log('🔄 Retry initiated, calling chat API with:');
            console.log('   retry_user_message_id:', data.chat_request.retry_user_message_id);
            console.log('   retry_thread_id:', data.chat_request.retry_thread_id);
            console.log('   retry_thread_attempt:', data.chat_request.retry_thread_attempt);
            console.log('   Full chat_request:', data.chat_request);
            
            // Call chat API with the retry parameters
            return fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'same-origin',
                body: JSON.stringify(data.chat_request)
            });
        } else {
            throw new Error('Retry response missing chat_request');
        }
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(data => {
                throw new Error(data.error || 'Chat API failed');
            });
        }
        return response.json();
    })
    .then(chatData => {
        console.log('✅ Chat API response:', chatData);
        
        // Hide typing indicator
        hideLoadingIndicatorInChatbox();
        console.log('🧹 Typing indicator removed');
        
        // Get current conversation ID using the proper API
        const conversationId = window.chatConversations?.getCurrentConversationId();
        
        console.log(`🔍 Current conversation ID: ${conversationId}`);
        
        // Reload messages to show new attempt (which will automatically hide old attempts)
        if (conversationId) {
            console.log('🔄 Reloading messages for conversation:', conversationId);
            
            // Import loadMessages dynamically
            import('./chat-messages.js').then(module => {
                console.log('📦 chat-messages.js module loaded, calling loadMessages...');
                module.loadMessages(conversationId);
                // No toast - the reloaded messages are enough feedback
            }).catch(err => {
                console.error('❌ Error loading chat-messages module:', err);
                showToast('error', 'Failed to reload messages');
            });
        } else {
            console.error('❌ No currentConversationId found!');
            
            // Try to force a page refresh as fallback
            console.log('🔄 Attempting page refresh as fallback...');
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        }
    })
    .catch(error => {
        console.error('❌ Retry error:', error);
        
        // Hide typing indicator on error
        hideLoadingIndicatorInChatbox();
        
        showToast('error', `Retry failed: ${error.message}`);
    })
    .finally(() => {
        // Clean up pending retry
        window.pendingMessageRetry = null;
    });
    
    }, 300); // End of setTimeout - wait 300ms for modal to close
};

/**
 * Handle carousel navigation (switch between retry attempts)
 */
export function handleCarouselNavigation(messageDiv, messageId, direction) {
    console.log(`🎠 Carousel ${direction} clicked for message: ${messageId}`);
    
    // Call switch-attempt API endpoint
    fetch(`/api/message/${messageId}/switch-attempt`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            direction: direction // 'prev' or 'next'
        })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(data => {
                throw new Error(data.error || 'Switch attempt failed');
            });
        }
        return response.json();
    })
    .then(data => {
        console.log(`✅ Switched to attempt ${data.new_active_attempt}:`, data);
        
        // Reload messages to show new active attempt
        if (window.currentConversationId) {
            import('./chat-messages.js').then(module => {
                module.loadMessages(window.currentConversationId);
                showToast('info', `Switched to attempt ${data.new_active_attempt}`);
            });
        }
    })
    .catch(error => {
        console.error('❌ Carousel navigation error:', error);
        showToast('error', `Failed to switch attempt: ${error.message}`);
    });
}

// Make functions available globally for event handlers in chat-messages.js
window.handleRetryButtonClick = handleRetryButtonClick;
window.handleCarouselNavigation = handleCarouselNavigation;
