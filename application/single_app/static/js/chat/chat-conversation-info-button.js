// chat-conversation-info-button.js
/**
 * Module for handling the conversation info button in the title bar
 */

/**
 * Initialize the conversation info button functionality
 */
export function initConversationInfoButton() {
  const infoButton = document.getElementById('conversation-info-btn');
  
  if (!infoButton) {
    console.warn('Conversation info button not found');
    return;
  }

  // Add click handler to show conversation details
  infoButton.addEventListener('click', function(e) {
    e.preventDefault();
    
    // Use the global chatConversations object to get current conversation ID
    const currentConversationId = window.chatConversations?.getCurrentConversationId();
    if (currentConversationId && window.showConversationDetails) {
      window.showConversationDetails(currentConversationId);
    } else {
      console.warn('No active conversation or showConversationDetails function not available');
    }
  });
}

/**
 * Show or hide the conversation info button based on whether there's an active conversation
 * @param {boolean} hasActiveConversation - Whether there's currently an active conversation
 */
export function toggleConversationInfoButton(hasActiveConversation) {
  const infoButton = document.getElementById('conversation-info-btn');
  
  if (infoButton) {
    infoButton.classList.toggle('d-none', !hasActiveConversation);
  }
}

/**
 * Show the conversation info button
 */
export function showConversationInfoButton() {
  toggleConversationInfoButton(true);
}

/**
 * Hide the conversation info button
 */
export function hideConversationInfoButton() {
  toggleConversationInfoButton(false);
}

function buildWorkflowActivityUrl(conversationId, workflowId) {
  if (!conversationId) {
    return '';
  }

  const url = new URL('/workflow-activity', window.location.origin);
  url.searchParams.set('conversationId', conversationId);
  if (workflowId) {
    url.searchParams.set('workflowId', workflowId);
  }
  return url.toString();
}

export function updateWorkflowActivityButton(conversationId, metadata = {}) {
  const activityButton = document.getElementById('workflow-activity-btn');
  if (!activityButton) {
    return;
  }

  const workflowId = String(metadata.workflow_id || '').trim();
  const isWorkflowConversation = String(metadata.chat_type || '').trim().toLowerCase() === 'workflow' || Boolean(workflowId);
  const activityUrl = isWorkflowConversation ? buildWorkflowActivityUrl(conversationId, workflowId) : '';

  activityButton.classList.toggle('d-none', !activityUrl);
  activityButton.href = activityUrl || '#';
}

export function hideWorkflowActivityButton() {
  updateWorkflowActivityButton('', {});
}
