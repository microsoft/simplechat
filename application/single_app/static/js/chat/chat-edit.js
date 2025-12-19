// chat-edit.js
// Handles message edit functionality

import { showToast } from './chat-toast.js';
import { showLoadingIndicatorInChatbox, hideLoadingIndicatorInChatbox } from './chat-loading-indicator.js';

/**
 * Handle edit button click - opens edit modal
 */
export function handleEditButtonClick(messageDiv, messageId, messageType) {
    console.log(`✏️ Edit button clicked for ${messageType} message: ${messageId}`);
    
    // Store message info for edit execution
    window.pendingMessageEdit = {
        messageDiv,
        messageId,
        messageType
    };
    
    // Get the current message content
    const messageTextDiv = messageDiv.querySelector('.message-text');
    const currentContent = messageTextDiv ? messageTextDiv.textContent : '';
    
    // Populate edit modal with current content
    const editTextarea = document.getElementById('edit-message-content');
    if (editTextarea) {
        editTextarea.value = currentContent;
    }
    
    // Get original message metadata to display settings info
    fetch(`/api/message/${messageId}/metadata`)
        .then(response => response.json())
        .then(metadata => {
            console.log('📊 Original message metadata:', metadata);
            
            // Store metadata for later use in executeMessageEdit
            window.pendingMessageEdit.metadata = metadata;
            
            // Display original settings in modal
            const settingsInfoDiv = document.getElementById('edit-original-settings-info');
            if (settingsInfoDiv) {
                const agentSelection = metadata?.agent_selection;
                const modelName = metadata?.model_selection?.selected_model;
                const reasoningEffort = metadata?.reasoning_effort;
                const docSearchEnabled = metadata?.document_search?.enabled || false;
                
                let settingsHtml = '<small class="text-muted">Original settings: ';
                
                // Show agent if used, otherwise show model
                if (agentSelection && (agentSelection.agent_display_name || agentSelection.selected_agent)) {
                    const agentName = agentSelection.agent_display_name || agentSelection.selected_agent;
                    settingsHtml += `<strong>🤖 ${agentName}</strong>`;
                } else if (modelName) {
                    settingsHtml += `<strong>${modelName}</strong>`;
                } else {
                    settingsHtml += '<strong>Default model</strong>';
                }
                
                if (reasoningEffort) {
                    settingsHtml += `, Reasoning: <strong>${reasoningEffort}</strong>`;
                }
                
                if (docSearchEnabled) {
                    settingsHtml += `, <strong>Document search enabled</strong>`;
                }
                
                settingsHtml += '</small>';
                settingsInfoDiv.innerHTML = settingsHtml;
            }
        })
        .catch(error => {
            console.error('❌ Error fetching message metadata:', error);
        });
    
    // Show the edit modal
    const editModal = new bootstrap.Modal(document.getElementById('edit-message-modal'));
    editModal.show();
}

/**
 * Execute message edit - called when user confirms edit in modal
 */
window.executeMessageEdit = function() {
    const pendingEdit = window.pendingMessageEdit;
    if (!pendingEdit) {
        console.error('❌ No pending edit found');
        return;
    }
    
    const { messageDiv, messageId, messageType } = pendingEdit;
    
    console.log(`🚀 Executing edit for ${messageType} message: ${messageId}`);
    
    // Get edited content from textarea
    const editTextarea = document.getElementById('edit-message-content');
    const editedContent = editTextarea ? editTextarea.value.trim() : '';
    
    if (!editedContent) {
        showToast('error', 'Message content cannot be empty');
        return;
    }
    
    console.log(`📝 Edited content length: ${editedContent.length} characters`);
    
    // Close the modal explicitly
    const modalElement = document.getElementById('edit-message-modal');
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
        
        // Call edit API endpoint
        console.log('📡 Calling edit API endpoint...');
        fetch(`/api/message/${messageId}/edit`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                content: editedContent
            })
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(data.error || 'Edit failed');
                });
            }
            return response.json();
        })
        .then(data => {
            console.log('✅ Edit API response:', data);
            
            if (data.success && data.chat_request) {
                console.log('🔄 Edit initiated, calling chat API with:');
                console.log('   edited_user_message_id:', data.chat_request.edited_user_message_id);
                console.log('   retry_thread_id:', data.chat_request.retry_thread_id);
                console.log('   retry_thread_attempt:', data.chat_request.retry_thread_attempt);
                console.log('   Full chat_request:', data.chat_request);
                
                // Call chat API with the edit parameters
                return fetch('/api/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    credentials: 'same-origin',
                    body: JSON.stringify(data.chat_request)
                });
            } else {
                throw new Error('Edit response missing chat_request');
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
            
            // Reload messages to show edited message and new response
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
            console.error('❌ Edit error:', error);
            
            // Hide typing indicator on error
            hideLoadingIndicatorInChatbox();
            
            showToast('error', `Edit failed: ${error.message}`);
        })
        .finally(() => {
            // Clean up pending edit
            window.pendingMessageEdit = null;
        });
        
    }, 300); // End of setTimeout - wait 300ms for modal to close
};

// Make functions available globally for event handlers
window.handleEditButtonClick = handleEditButtonClick;
