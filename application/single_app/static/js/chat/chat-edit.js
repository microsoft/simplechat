// chat-edit.js
// Handles message edit functionality

import { showToast } from './chat-toast.js';
import { showLoadingIndicatorInChatbox, hideLoadingIndicatorInChatbox } from './chat-loading-indicator.js';
import { sendMessageWithStreaming } from './chat-streaming.js';
import { handleActionAuthRequired, prepareActionAuthExecution } from './chat-action-auth.js';

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
window.executeMessageEdit = async function() {
    const pendingEdit = window.pendingMessageEdit;
    if (!pendingEdit || pendingEdit.actionAuthPending) {
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

    const conversationId = window.chatConversations?.getCurrentConversationId?.() || window.currentConversationId;
    const isCurrent = () => window.pendingMessageEdit === pendingEdit
        && window.currentConversationId === conversationId
        && editTextarea?.value.trim() === editedContent;
    const actionAuthPayload = { conversation_id: conversationId };
    pendingEdit.actionAuthPending = true;
    try {
        let metadata = pendingEdit.metadata;
        if (!metadata) {
            const response = await fetch(`/api/message/${encodeURIComponent(messageId)}/metadata`, { credentials: 'same-origin' });
            if (!response.ok) throw new Error('Message metadata is unavailable.');
            metadata = await response.json();
        }
        const selection = metadata?.agent_selection;
        if (selection?.selected_agent || selection?.selected_agent_id || selection?.agent_id) {
            actionAuthPayload.agent_info = {
                id: selection.selected_agent_id || selection.agent_id || null,
                name: selection.selected_agent || '',
                is_global: selection.is_global === true,
                is_group: selection.is_group === true,
                group_id: selection.group_id || null,
            };
        }
        if (!isCurrent() || !await prepareActionAuthExecution(actionAuthPayload, { conversationId, isCurrent })) {
            pendingEdit.actionAuthPending = false;
            return;
        }
    } catch {
        pendingEdit.actionAuthPending = false;
        showToast('The original action settings could not be checked. Your edit has not been submitted.', 'warning');
        return;
    }
    
    // Wait a bit for modal to close, then show loading indicator
    setTimeout(() => {
        if (!isCurrent()) {
            pendingEdit.actionAuthPending = false;
            return;
        }
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
                content: editedContent,
                ...(actionAuthPayload.action_auth_request_id
                    ? { action_auth_request_id: actionAuthPayload.action_auth_request_id } : {}),
            })
        })
        .then(async response => {
            const data = await response.json();
            if (handleActionAuthRequired(data, {
                payload: actionAuthPayload, conversationId,
                isCurrent: () => window.currentConversationId === conversationId,
            })) {
                hideLoadingIndicatorInChatbox();
                return null;
            }
            if (!response.ok) throw new Error(data.error || 'Edit failed');
            return data;
        })
        .then(data => {
            if (!data) return null;
            console.log('✅ Edit API response:', data);
            
            if (data.success && data.chat_request) {
                if (actionAuthPayload.action_auth_request_id) {
                    data.chat_request.action_auth_request_id = actionAuthPayload.action_auth_request_id;
                }
                console.log('🔄 Edit initiated, calling chat API with:');
                console.log('   edited_user_message_id:', data.chat_request.edited_user_message_id);
                console.log('   retry_thread_id:', data.chat_request.retry_thread_id);
                console.log('   retry_thread_attempt:', data.chat_request.retry_thread_attempt);
                console.log('   Full chat_request:', data.chat_request);
                window.dispatchEvent(new CustomEvent(
                    'chat:conversation-documents-refresh',
                    {
                        detail: {
                            conversationId: data.chat_request.conversation_id,
                            autoOpen: false,
                        },
                    }
                ));

                sendMessageWithStreaming(
                    data.chat_request,
                    null,
                    data.chat_request.conversation_id,
                    {
                        actionAuthPrepared: Boolean(actionAuthPayload.agent_info),
                        onDone: () => {
                            const conversationId = window.chatConversations?.getCurrentConversationId() || data.chat_request.conversation_id;
                            if (conversationId) {
                                import('./chat-messages.js').then(module => {
                                    module.loadMessages(conversationId);
                                }).catch(err => {
                                    console.error('❌ Error loading chat-messages module:', err);
                                    showToast('Failed to reload messages', 'error');
                                });
                            }
                        },
                        onError: (errorMessage) => {
                            showToast(`Edit failed: ${errorMessage}`, 'error');
                        },
                        onFinally: () => {
                            hideLoadingIndicatorInChatbox();
                        }
                    }
                );

                return null;
            } else {
                throw new Error('Edit response missing chat_request');
            }
        })
        .catch(error => {
            console.error('❌ Edit error:', error);
            
            // Hide typing indicator on error
            hideLoadingIndicatorInChatbox();
            
            showToast(`Edit failed: ${error.message}`, 'error');
        })
        .finally(() => {
            // Clean up pending edit
            if (window.pendingMessageEdit === pendingEdit) window.pendingMessageEdit = null;
        });
        
    }, 300); // End of setTimeout - wait 300ms for modal to close
};

// Make functions available globally for event handlers
window.handleEditButtonClick = handleEditButtonClick;
