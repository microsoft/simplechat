// chat-conversation-details.js
/**
 * Module for handling conversation details modal
 */

import { isColorLight } from "./chat-utils.js";

/**
 * Show conversation details in a modal
 * @param {string} conversationId - The conversation ID to show details for
 */
export async function showConversationDetails(conversationId) {
  const modal = document.getElementById('conversation-details-modal');
  const modalTitle = document.getElementById('conversationDetailsModalLabel');
  const content = document.getElementById('conversation-details-content');
  
  if (!modal || !content) {
    console.error('Conversation details modal not found');
    return;
  }

  // Show loading state
  content.innerHTML = `
    <div class="text-center p-4">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
      <p class="mt-2 text-muted">Loading conversation details...</p>
    </div>
  `;

  // Show the modal
  const bsModal = new bootstrap.Modal(modal);
  bsModal.show();

  try {
    // Fetch conversation metadata
    const response = await fetch(`/api/conversations/${conversationId}/metadata`);
    
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    const metadata = await response.json();
    
    // Update modal title with conversation title
    modalTitle.innerHTML = `
      <i class="bi bi-info-circle me-2"></i>
      ${metadata.title || 'Conversation Details'}
    `;
    
    // Render the metadata
    content.innerHTML = renderConversationMetadata(metadata, conversationId);
    
  } catch (error) {
    console.error('Error fetching conversation details:', error);
    content.innerHTML = `
      <div class="text-center p-4">
        <div class="text-danger">
          <i class="bi bi-exclamation-triangle-fill me-2"></i>
          <strong>Error loading conversation details</strong>
        </div>
        <p class="text-muted mt-2">${error.message}</p>
      </div>
    `;
  }
}

/**
 * Render conversation metadata as HTML
 * @param {Object} metadata - The conversation metadata object
 * @param {string} conversationId - The conversation ID
 * @returns {string} HTML string
 */
function renderConversationMetadata(metadata, conversationId) {
  const { context = [], tags = [], strict = false, classification = [], last_updated, chat_type = 'personal' } = metadata;
  
  // Organize tags by category
  const tagsByCategory = {
    participant: [],
    document: [],
    model: [],
    agent: [],
    semantic: [],
    web: []
  };
  
  tags.forEach(tag => {
    const category = tag.category;
    if (tagsByCategory[category]) {
      tagsByCategory[category].push(tag);
    }
  });

  // Build HTML sections
  let html = `
    <div class="row g-3">
      <!-- Basic Info -->
      <div class="col-12">
        <div class="card">
          <div class="card-header bg-primary text-white">
            <h6 class="mb-0"><i class="bi bi-info-circle me-2"></i>Basic Information</h6>
          </div>
          <div class="card-body">
            <div class="row g-2">
              <div class="col-sm-6">
                <strong>Conversation ID:</strong> <code class="text-muted">${conversationId}</code>
              </div>
              <div class="col-sm-6">
                <strong>Last Updated:</strong> ${formatDate(last_updated)}
              </div>
              <div class="col-sm-6">
                <strong>Strict Mode:</strong> ${strict ? '<span class="badge bg-warning">Enabled</span>' : '<span class="badge bg-success">Disabled</span>'}
              </div>
              <div class="col-sm-6">
                <strong>Chat Type:</strong> ${formatChatType(chat_type, context)}
              </div>
              <div class="col-sm-6">
                <strong>Classifications:</strong> ${formatClassifications(classification)}
              </div>
            </div>
          </div>
        </div>
      </div>
  `;

  // Context Section
  if (context.length > 0) {
    html += `
      <div class="col-md-6">
        <div class="card h-100">
          <div class="card-header bg-info text-white">
            <h6 class="mb-0"><i class="bi bi-diagram-3 me-2"></i>Context & Scopes</h6>
          </div>
          <div class="card-body">
            ${renderContextSection(context)}
          </div>
        </div>
      </div>
    `;
  }

  // Participants Section
  if (tagsByCategory.participant.length > 0) {
    html += `
      <div class="col-md-6">
        <div class="card h-100">
          <div class="card-header bg-success text-white">
            <h6 class="mb-0"><i class="bi bi-people me-2"></i>Participants</h6>
          </div>
          <div class="card-body">
            ${renderParticipantsSection(tagsByCategory.participant)}
          </div>
        </div>
      </div>
    `;
  }

  // Models & Agents Section
  if (tagsByCategory.model.length > 0 || tagsByCategory.agent.length > 0) {
    html += `
      <div class="col-md-6">
        <div class="card h-100">
          <div class="card-header bg-warning text-white">
            <h6 class="mb-0"><i class="bi bi-cpu me-2"></i>Models & Agents</h6>
          </div>
          <div class="card-body">
            ${renderModelsAndAgentsSection(tagsByCategory.model, tagsByCategory.agent)}
          </div>
        </div>
      </div>
    `;
  }

  // Documents Section
  if (tagsByCategory.document.length > 0) {
    html += `
      <div class="col-md-6">
        <div class="card h-100">
          <div class="card-header bg-secondary text-white">
            <h6 class="mb-0"><i class="bi bi-file-earmark-text me-2"></i>Documents</h6>
          </div>
          <div class="card-body">
            ${renderDocumentsSection(tagsByCategory.document)}
          </div>
        </div>
      </div>
    `;
  }

  // Semantic Tags Section
  if (tagsByCategory.semantic.length > 0) {
    html += `
      <div class="col-12">
        <div class="card">
          <div class="card-header bg-dark text-white">
            <h6 class="mb-0"><i class="bi bi-tags me-2"></i>Semantic Tags</h6>
          </div>
          <div class="card-body">
            ${renderSemanticTagsSection(tagsByCategory.semantic)}
          </div>
        </div>
      </div>
    `;
  }

  // Web Sources Section
  if (tagsByCategory.web.length > 0) {
    html += `
      <div class="col-12">
        <div class="card">
          <div class="card-header bg-info text-white">
            <h6 class="mb-0"><i class="bi bi-globe me-2"></i>Web Sources</h6>
          </div>
          <div class="card-body">
            ${renderWebSourcesSection(tagsByCategory.web)}
          </div>
        </div>
      </div>
    `;
  }

  html += `</div>`;
  return html;
}

/**
 * Render context section
 */
function renderContextSection(context) {
  let html = '';
  
  const primary = context.find(c => c.type === 'primary');
  const secondary = context.filter(c => c.type === 'secondary');
  
  if (primary) {
    const displayName = primary.name || primary.id;
    const isGroupChat = primary.scope === 'group';
    
    html += `
      <div class="mb-3">
        <strong class="text-primary">Primary Context:</strong>
        <div class="ms-3 mt-1">
          <div class="d-flex align-items-center mb-2">
            <span class="badge bg-primary me-2">${primary.scope}</span>
            ${isGroupChat ? '<span class="badge bg-secondary me-2">single-user</span>' : ''}
            <span class="fw-bold">${displayName}</span>
          </div>
          ${primary.name ? `<div class="small text-muted">ID: ${primary.id}</div>` : ''}
        </div>
      </div>
    `;
  }
  
  if (secondary.length > 0) {
    html += `
      <div>
        <strong class="text-secondary">Secondary Contexts:</strong>
        <div class="ms-3 mt-1">
    `;
    
    secondary.forEach(ctx => {
      const displayName = ctx.name || ctx.id;
      html += `
        <div class="mb-2">
          <span class="badge bg-secondary me-2">${ctx.scope}</span>
          <span class="fw-bold">${displayName}</span>
          ${ctx.name ? `<div class="small text-muted">ID: ${ctx.id}</div>` : ''}
        </div>
      `;
    });
    
    html += `</div></div>`;
  }
  
  return html;
}

/**
 * Render participants section
 */
function renderParticipantsSection(participants) {
  let html = '';
  
  participants.forEach(participant => {
    const initials = (participant.name || 'U').slice(0, 2).toUpperCase();
    const avatarId = `participant-avatar-${participant.user_id}`;
    
    html += `
      <div class="d-flex align-items-center mb-2">
        <div id="${avatarId}" class="rounded-circle bg-primary text-white d-flex align-items-center justify-content-center me-3" style="width: 32px; height: 32px; font-size: 0.9rem;">
          ${initials}
        </div>
        <div>
          <div class="fw-semibold">${participant.name || 'Unknown User'}</div>
          <small class="text-muted">${participant.email || ''}</small>
        </div>
      </div>
    `;
  });
  
  // After rendering, try to load profile images for each participant
  setTimeout(() => {
    participants.forEach(participant => {
      loadParticipantProfileImage(participant.user_id);
    });
  }, 100);
  
  return html;
}

/**
 * Load profile image for a participant
 */
async function loadParticipantProfileImage(userId) {
  const avatarElement = document.getElementById(`participant-avatar-${userId}`);
  if (!avatarElement) return;
  
  try {
    const response = await fetch(`/api/user/profile-image/${userId}`);
    if (!response.ok) throw new Error('Failed to load user profile image');
    
    const userData = await response.json();
    const profileImage = userData.profile_image;
    
    if (profileImage && profileImage.trim()) {
      // Create image element
      const img = document.createElement('img');
      img.src = profileImage;
      img.className = 'rounded-circle';
      img.style.width = '32px';
      img.style.height = '32px';
      img.style.objectFit = 'cover';
      img.alt = 'Profile';
      
      // Replace avatar content with image when it loads successfully
      img.onload = () => {
        avatarElement.innerHTML = '';
        avatarElement.appendChild(img);
        avatarElement.classList.remove('bg-primary', 'text-white');
      };
      
      // If image fails to load, keep the initials
      img.onerror = () => {
        // Image failed to load, keep initials (no action needed)
      };
    }
  } catch (error) {
    // Failed to load user profile image or no profile image, keep initials (no action needed)
    console.debug('Could not load profile image for user:', userId);
  }
}

/**
 * Render models and agents section
 */
function renderModelsAndAgentsSection(models, agents) {
  let html = '';
  
  if (models.length > 0) {
    html += '<div class="mb-3"><strong>Models:</strong><div class="mt-1">';
    models.forEach(model => {
      html += `<span class="badge bg-warning text-dark me-1 mb-1">${model.value}</span>`;
    });
    html += '</div></div>';
  }
  
  if (agents.length > 0) {
    html += '<div><strong>Agents:</strong><div class="mt-1">';
    agents.forEach(agent => {
      html += `<span class="badge bg-info me-1 mb-1">${agent.value}</span>`;
    });
    html += '</div></div>';
  }
  
  return html;
}

/**
 * Render documents section
 */
function renderDocumentsSection(documents) {
  let html = '';
  
  documents.forEach(doc => {
    const chunkPages = extractPageNumbers(doc.chunk_ids || []);
    const chunkCount = doc.chunk_ids ? doc.chunk_ids.length : 0;
    const documentTitle = doc.title || doc.document_id;
    const scopeName = doc.scope?.name || doc.scope?.id || 'Unknown';
    
    // Format document classification with custom colors
    const allCategories = window.classification_categories || [];
    const category = allCategories.find(cat => cat.label === doc.classification);
    let classificationHtml;
    
    if (category) {
      const textClass = isColorLight(category.color) ? 'text-dark' : 'text-white';
      classificationHtml = `<span class="badge ${textClass}" style="background-color: ${category.color}">${doc.classification}</span>`;
    } else {
      classificationHtml = `<span class="badge bg-warning text-dark" title="Definition for '${doc.classification}' not found">${doc.classification}</span>`;
    }
    
    html += `
      <div class="mb-3 p-2 border rounded">
        <div class="d-flex justify-content-between align-items-start mb-2">
          <div class="fw-semibold text-truncate me-2" title="${documentTitle}">${documentTitle}</div>
          ${classificationHtml}
        </div>
        <div class="small text-muted mb-1">
          <i class="bi bi-file-earmark me-1"></i>
          ${chunkCount} chunk${chunkCount !== 1 ? 's' : ''}
          ${chunkPages.length > 0 ? ` (Pages: ${chunkPages.join(', ')})` : ''}
        </div>
        <div class="small text-muted mb-1">
          <i class="bi bi-${getScopeIcon(doc.scope?.type)} me-1"></i>
          ${doc.scope?.type} scope: <strong>${scopeName}</strong>
        </div>
        ${doc.title && doc.title !== doc.document_id ? `
        <div class="small text-muted">
          <i class="bi bi-hash me-1"></i>
          ID: <code>${doc.document_id}</code>
        </div>
        ` : ''}
      </div>
    `;
  });
  
  return html;
}

/**
 * Render semantic tags section
 */
function renderSemanticTagsSection(semanticTags) {
  let html = '<div class="d-flex flex-wrap gap-1">';
  
  semanticTags.forEach(tag => {
    html += `<span class="badge bg-dark">${tag.value}</span>`;
  });
  
  html += '</div>';
  return html;
}

/**
 * Render web sources section
 */
function renderWebSourcesSection(webSources) {
  let html = '';
  
  webSources.forEach(source => {
    html += `
      <div class="mb-2">
        <a href="${source.value}" target="_blank" rel="noopener noreferrer" class="text-decoration-none">
          <i class="bi bi-link-45deg me-2"></i>${source.value}
          <i class="bi bi-box-arrow-up-right ms-1 small"></i>
        </a>
      </div>
    `;
  });
  
  return html;
}

/**
 * Helper functions
 */
function formatDate(dateString) {
  if (!dateString) return 'Unknown';
  const date = new Date(dateString);
  return date.toLocaleString();
}

function formatClassifications(classifications) {
  if (!classifications || classifications.length === 0) {
    return '<span class="badge bg-light text-dark">None</span>';
  }
  
  const allCategories = window.classification_categories || [];
  
  return classifications.map(label => {
    const category = allCategories.find(cat => cat.label === label);
    
    if (category) {
      // Found category definition, apply custom color
      const textClass = isColorLight(category.color) ? 'text-dark' : 'text-white';
      return `<span class="badge ${textClass}" style="background-color: ${category.color}">${label}</span>`;
    } else {
      // Label exists but no definition found (maybe deleted in admin)
      return `<span class="badge bg-warning text-dark" title="Definition for '${label}' not found">${label}</span>`;
    }
  }).join(' ');
}

function formatChatType(chatType, context = []) {
  // Use the actual chat_type value from the metadata
  if (chatType === 'personal') {
    return '<span class="badge bg-primary">personal</span>';
  } else if (chatType === 'group' || chatType.startsWith('group')) {
    // For group chats, try to find the group name from context
    const primaryContext = context.find(c => c.type === 'primary' && c.scope === 'group');
    const groupName = primaryContext ? primaryContext.name || 'Group' : 'Group';
    
    // Determine if single-user or multi-user based on chat_type
    const userType = chatType.includes('multi-user') ? 'multi-user' : 'single-user';
    
    return `
      <span class="badge bg-info me-1">group - ${groupName}</span>
      <span class="badge bg-secondary">${userType}</span>
    `;
  } else {
    // Fallback for unknown types
    return `<span class="badge bg-secondary">${chatType}</span>`;
  }
}

function getScopeIcon(scope) {
  switch (scope) {
    case 'personal': return 'person';
    case 'group': return 'people';
    case 'public': return 'globe';
    default: return 'question-circle';
  }
}

function extractPageNumbers(chunkIds) {
  const pages = [];
  chunkIds.forEach(chunkId => {
    const parts = chunkId.split('_');
    if (parts.length > 1) {
      const pageNum = parts[parts.length - 1];
      if (!isNaN(pageNum) && !pages.includes(pageNum)) {
        pages.push(pageNum);
      }
    }
  });
  return pages.sort((a, b) => parseInt(a) - parseInt(b));
}

// Event listeners for details buttons
document.addEventListener('click', function(e) {
  if (e.target.closest('.details-btn')) {
    e.preventDefault();
    
    // Find the conversation ID from the closest conversation item
    const conversationItem = e.target.closest('.conversation-item, .sidebar-conversation-item');
    if (conversationItem) {
      const conversationId = conversationItem.getAttribute('data-conversation-id');
      if (conversationId) {
        showConversationDetails(conversationId);
      }
    }
  }
});

// Export functions for external use
window.showConversationDetails = showConversationDetails;
