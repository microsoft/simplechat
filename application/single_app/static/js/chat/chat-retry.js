// chat-retry.js
// Handles message retry/regenerate functionality

import { showToast } from './chat-toast.js';
import { showLoadingIndicatorInChatbox, hideLoadingIndicatorInChatbox } from './chat-loading-indicator.js';

/**
 * Populate retry agent dropdown with available agents
 */
async function populateRetryAgentDropdown() {
    const retryAgentSelect = document.getElementById('retry-agent-select');
    if (!retryAgentSelect) return;
    
    try {
        // Import agent functions dynamically
        const agentsModule = await import('../agents_common.js');
        const { fetchUserAgents, fetchGroupAgentsForActiveGroup, fetchSelectedAgent, populateAgentSelect } = agentsModule;
        
        // Fetch available agents
        const [userAgents, selectedAgent] = await Promise.all([
            fetchUserAgents(),
            fetchSelectedAgent()
        ]);
        const groupAgents = await fetchGroupAgentsForActiveGroup();
        
        // Combine and order agents
        const combinedAgents = [...userAgents, ...groupAgents];
        const personalAgents = combinedAgents.filter(agent => !agent.is_global && !agent.is_group);
        const activeGroupAgents = combinedAgents.filter(agent => agent.is_group);
        const globalAgents = combinedAgents.filter(agent => agent.is_global);
        const orderedAgents = [...personalAgents, ...activeGroupAgents, ...globalAgents];
        
        // Populate retry agent select using shared function
        populateAgentSelect(retryAgentSelect, orderedAgents, selectedAgent);
        
        console.log(`✅ Populated retry agent dropdown with ${orderedAgents.length} agents`);
    } catch (error) {
        console.error('❌ Error populating retry agent dropdown:', error);
    }
}

/**
 * Handle retry button click - opens retry modal
 */
export async function handleRetryButtonClick(messageDiv, messageId, messageType) {
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
    
    // Populate retry modal with agent options (always load fresh from API)
    const retryAgentSelect = document.getElementById('retry-agent-select');
    if (retryAgentSelect) {
        await populateRetryAgentDropdown();
    }
    
    // Determine if original message used agents or models
    const enableAgentsBtn = document.getElementById('enable-agents-btn');
    const agentSelectContainer = document.getElementById('agent-select-container');
    const isAgentMode = enableAgentsBtn && enableAgentsBtn.classList.contains('active') && 
                       agentSelectContainer && agentSelectContainer.style.display !== 'none';
    
    // Set retry mode based on current state
    const retryModeModel = document.getElementById('retry-mode-model');
    const retryModeAgent = document.getElementById('retry-mode-agent');
    const retryModelContainer = document.getElementById('retry-model-container');
    const retryAgentContainer = document.getElementById('retry-agent-container');
    
    if (isAgentMode && retryModeAgent) {
        retryModeAgent.checked = true;
        if (retryModelContainer) retryModelContainer.style.display = 'none';
        if (retryAgentContainer) retryAgentContainer.style.display = 'block';
    } else if (retryModeModel) {
        retryModeModel.checked = true;
        if (retryModelContainer) retryModelContainer.style.display = 'block';
        if (retryAgentContainer) retryAgentContainer.style.display = 'none';
    }
    
    // Add event listeners for mode toggle
    if (retryModeModel) {
        retryModeModel.addEventListener('change', function() {
            if (this.checked) {
                if (retryModelContainer) retryModelContainer.style.display = 'block';
                if (retryAgentContainer) retryAgentContainer.style.display = 'none';
                updateReasoningVisibility();
            }
        });
    }
    
    if (retryModeAgent) {
        retryModeAgent.addEventListener('change', function() {
            if (this.checked) {
                if (retryModelContainer) retryModelContainer.style.display = 'none';
                if (retryAgentContainer) retryAgentContainer.style.display = 'block';
                updateReasoningVisibility();
            }
        });
    }
    
    // Function to update reasoning visibility based on selected model or agent
    function updateReasoningVisibility() {
        const retryReasoningContainer = document.getElementById('retry-reasoning-container');
        const retryReasoningLevels = document.getElementById('retry-reasoning-levels');
        
        let showReasoning = false;
        
        if (retryModeModel && retryModeModel.checked) {
            const selectedModel = retryModelSelect ? retryModelSelect.value : null;
            showReasoning = selectedModel && selectedModel.includes('o1');
        } else if (retryModeAgent && retryModeAgent.checked) {
            // Check if agent uses o1 model (you could enhance this by checking agent config)
            const selectedAgent = retryAgentSelect ? retryAgentSelect.value : null;
            // For now, we'll show reasoning for agents too if they use o1 models
            // This could be enhanced by fetching agent model info
            showReasoning = false; // Default to false for agents unless we can determine model
        }
        
        if (retryReasoningContainer) {
            retryReasoningContainer.style.display = showReasoning ? 'block' : 'none';
            
            // Populate reasoning levels if empty and showing
            if (showReasoning && retryReasoningLevels && !retryReasoningLevels.hasChildNodes()) {
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
    }
    
    // Initial reasoning visibility
    updateReasoningVisibility();
    
    // Update reasoning visibility when model changes in retry modal
    if (retryModelSelect) {
        retryModelSelect.addEventListener('change', updateReasoningVisibility);
    }
    
    // Update reasoning visibility when agent changes in retry modal
    if (retryAgentSelect) {
        retryAgentSelect.addEventListener('change', updateReasoningVisibility);
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
    
    // Determine retry mode (model or agent)
    const retryModeModel = document.getElementById('retry-mode-model');
    const retryModeAgent = document.getElementById('retry-mode-agent');
    const isAgentMode = retryModeAgent && retryModeAgent.checked;
    
    // Prepare retry request body
    const requestBody = {};
    
    if (isAgentMode) {
        // Agent mode - get agent info
        const retryAgentSelect = document.getElementById('retry-agent-select');
        if (retryAgentSelect) {
            const selectedOption = retryAgentSelect.options[retryAgentSelect.selectedIndex];
            if (selectedOption) {
                requestBody.agent_info = {
                    id: selectedOption.dataset.agentId || null,
                    name: selectedOption.dataset.name || '',
                    display_name: selectedOption.dataset.displayName || selectedOption.textContent || '',
                    is_global: selectedOption.dataset.isGlobal === 'true',
                    is_group: selectedOption.dataset.isGroup === 'true',
                    group_id: selectedOption.dataset.groupId || null,
                    group_name: selectedOption.dataset.groupName || null
                };
                console.log(`🤖 Retry with agent:`, requestBody.agent_info);
            }
        }
    } else {
        // Model mode - get model and reasoning effort
        const retryModelSelect = document.getElementById('retry-model-select');
        const selectedModel = retryModelSelect ? retryModelSelect.value : null;
        requestBody.model = selectedModel;
        
        let reasoningEffort = null;
        const retryReasoningContainer = document.getElementById('retry-reasoning-container');
        if (retryReasoningContainer && retryReasoningContainer.style.display !== 'none') {
            const selectedReasoning = document.querySelector('input[name="retry-reasoning-effort"]:checked');
            reasoningEffort = selectedReasoning ? selectedReasoning.value : null;
        }
        requestBody.reasoning_effort = reasoningEffort;
        
        console.log(`🧠 Retry with model: ${selectedModel}, Reasoning: ${reasoningEffort}`);
    }
    
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
        body: JSON.stringify(requestBody)
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
