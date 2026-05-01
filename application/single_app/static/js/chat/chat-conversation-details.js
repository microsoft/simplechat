// chat-conversation-details.js
/**
 * Module for handling conversation details modal
 */

import { isColorLight } from "./chat-utils.js";

function getConversationDetailsModalElements() {
  return {
    modal: document.getElementById('conversation-details-modal'),
    modalTitle: document.getElementById('conversationDetailsModalLabel'),
    content: document.getElementById('conversation-details-content'),
    actionContainer: document.getElementById('conversation-details-actions'),
  };
}

function cleanupConversationDetailsModalState() {
  const anyVisibleModal = document.querySelector('.modal.show');
  if (anyVisibleModal) {
    return;
  }

  document.querySelectorAll('.modal-backdrop').forEach(backdrop => backdrop.remove());
  document.body.classList.remove('modal-open');
  document.body.style.removeProperty('padding-right');
}

function getConversationDetailsModalInstance() {
  const { modal } = getConversationDetailsModalElements();
  if (!modal || !window.bootstrap?.Modal) {
    return null;
  }
  return bootstrap.Modal.getOrCreateInstance(modal);
}

export function hideConversationDetails() {
  const { modal } = getConversationDetailsModalElements();
  const modalInstance = getConversationDetailsModalInstance();
  if (!modal || !modalInstance) {
    cleanupConversationDetailsModalState();
    return;
  }

  if (modal.classList.contains('show')) {
    modalInstance.hide();
    window.setTimeout(cleanupConversationDetailsModalState, 200);
    return;
  }

  cleanupConversationDetailsModalState();
}

function renderConversationDetailsActions(metadata, conversationId) {
  const { actionContainer } = getConversationDetailsModalElements();
  if (!actionContainer) {
    return;
  }

  if (!metadata || !conversationId) {
    actionContainer.innerHTML = '';
    return;
  }

  const actionButtons = [];

  if (window.chatExport?.openExportWizard) {
    actionButtons.push(`
      <button type="button" class="btn btn-outline-primary btn-sm" data-conversation-action="export" data-conversation-id="${conversationId}">
        <i class="bi bi-download me-1"></i>Export
      </button>
    `);
  }

  const isCollaborativeConversation = metadata.conversation_kind === 'collaborative';
  const canShowDeleteAction = isCollaborativeConversation
    ? Boolean(metadata.can_delete_conversation || metadata.can_leave_conversation)
    : true;

  if (canShowDeleteAction) {
    const deleteLabel = isCollaborativeConversation
      ? (metadata.can_delete_conversation ? 'Delete / Leave' : 'Leave')
      : 'Delete';
    actionButtons.push(`
      <button type="button" class="btn btn-outline-danger btn-sm" data-conversation-action="delete" data-conversation-id="${conversationId}">
        <i class="bi bi-trash me-1"></i>${deleteLabel}
      </button>
    `);
  }

  actionContainer.innerHTML = actionButtons.join('');
}

/**
 * Show conversation details in a modal
 * @param {string} conversationId - The conversation ID to show details for
 */
export async function showConversationDetails(conversationId) {
  const { modal, modalTitle, content } = getConversationDetailsModalElements();
  
  if (!modal || !content) {
    console.error('Conversation details modal not found');
    return;
  }

  renderConversationDetailsActions(null, null);

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
  const bsModal = getConversationDetailsModalInstance();
  if (bsModal && !modal.classList.contains('show')) {
    bsModal.show();
  }

  try {
    const conversationItem = document.querySelector(`.conversation-item[data-conversation-id="${conversationId}"]`)
      || document.querySelector(`.sidebar-conversation-item[data-conversation-id="${conversationId}"]`);
    const isCollaborativeConversation = conversationItem?.dataset?.conversationKind === 'collaborative';
    let metadata = null;

    if (isCollaborativeConversation && window.chatCollaboration?.fetchConversationMetadata) {
      metadata = await window.chatCollaboration.fetchConversationMetadata(conversationId);
    } else {
      const response = await fetch(`/api/conversations/${conversationId}/metadata`);
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      metadata = await response.json();
    }
    
    // Update modal title with conversation title, pin icon, and hidden icon
    const pinIcon = metadata.is_pinned ? '<i class="bi bi-pin-angle me-2" title="Pinned"></i>' : '';
    const hiddenIcon = metadata.is_hidden ? '<i class="bi bi-eye-slash me-2 text-muted" title="Hidden"></i>' : '';
    modalTitle.innerHTML = `
      ${pinIcon}${hiddenIcon}<i class="bi bi-info-circle me-2"></i>
      ${metadata.title || 'Conversation Details'}
    `;
    
    // Render the metadata
    content.innerHTML = renderConversationMetadata(metadata, conversationId);
    renderConversationDetailsActions(metadata, conversationId);
    attachConversationDetailActions(metadata, conversationId);
    
  } catch (error) {
    console.error('Error fetching conversation details:', error);
    renderConversationDetailsActions(null, null);
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
  const {
    context = [],
    tags = [],
    strict = false,
    classification = [],
    last_updated,
    updated_at,
    chat_type = 'personal',
    is_pinned = false,
    is_hidden = false,
    scope_locked,
    locked_contexts = [],
    summary = null,
    conversation_kind = null,
    participants = [],
    membership_status = null,
    can_manage_members = false,
    can_manage_roles = false,
    can_accept_invite = false,
    can_post_messages = true,
    can_delete_conversation = false,
    can_leave_conversation = false,
    current_user_role = '',
    pending_invite_count = 0,
  } = metadata;
  const resolvedLastUpdated = last_updated || updated_at;
  
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

  const participantRecords = Array.isArray(participants) && participants.length > 0
    ? participants
    : tagsByCategory.participant;
  const collaborationStatusHtml = conversation_kind === 'collaborative'
    ? renderCollaborationMembershipStatus(membership_status, can_post_messages, pending_invite_count)
    : `${is_pinned ? '<span class="badge bg-primary"><i class="bi bi-pin-angle me-1"></i>Pinned</span>' : ''} ${is_hidden ? '<span class="badge bg-secondary ms-1"><i class="bi bi-eye-slash me-1"></i>Hidden</span>' : ''}${!is_pinned && !is_hidden ? '<span class="text-muted">Normal</span>' : ''}`;

  // Build HTML sections
  let html = `
    <div class="row g-3">
      <!-- Summary Section -->
      <div class="col-12">
        <div class="card">
          <div class="card-header bg-primary bg-opacity-75 text-white d-flex justify-content-between align-items-center">
            <h6 class="mb-0"><i class="bi bi-blockquote-left me-2"></i>Summary</h6>
            ${summary ? `<small class="opacity-75">Generated ${formatDate(summary.generated_at)}${summary.model_deployment ? ` · ${summary.model_deployment}` : ''}</small>` : ''}
          </div>
          <div class="card-body" id="summary-card-body">
            ${renderSummaryContent(summary, conversationId)}
          </div>
        </div>
      </div>
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
                <strong>Last Updated:</strong> ${formatDate(resolvedLastUpdated)}
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
              <div class="col-sm-6">
                <strong>Status:</strong> ${collaborationStatusHtml}
              </div>
              <div class="col-sm-6">
                <strong>Scope Lock:</strong> ${formatScopeLockStatus(scope_locked, locked_contexts)}
              </div>
              ${conversation_kind === 'collaborative' ? `
              <div class="col-sm-6">
                <strong>Your Role:</strong> ${formatCollaborationRole(current_user_role, can_delete_conversation, can_leave_conversation)}
              </div>
              ` : ''}
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
  if (participantRecords.length > 0 || can_manage_members || can_accept_invite) {
    html += `
      <div class="col-md-6">
        <div class="card h-100">
          <div class="card-header bg-success text-white d-flex justify-content-between align-items-center gap-2 flex-wrap">
            <h6 class="mb-0"><i class="bi bi-people me-2"></i>Participants</h6>
            ${renderCollaborationActionButtons(conversationId, metadata)}
          </div>
          <div class="card-body">
            ${renderParticipantsSection(participantRecords, {
              canManageMembers: can_manage_members,
              canManageRoles: can_manage_roles,
              conversationKind: conversation_kind,
            })}
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

function renderCollaborationMembershipStatus(membershipStatus, canPostMessages, pendingInviteCount) {
  if (!membershipStatus) {
    return '<span class="text-muted">Normal</span>';
  }

  const badges = [];
  if (membershipStatus === 'accepted' || membershipStatus === 'group_member') {
    badges.push('<span class="badge bg-success">Active member</span>');
  }
  if (membershipStatus === 'pending') {
    badges.push('<span class="badge bg-warning text-dark">Invite pending</span>');
  }
  if (!canPostMessages) {
    badges.push('<span class="badge bg-secondary">Read-only</span>');
  }
  if (pendingInviteCount > 0) {
    badges.push(`<span class="badge bg-light text-dark">${pendingInviteCount} pending</span>`);
  }

  return badges.join(' ') || '<span class="text-muted">Normal</span>';
}

function formatCollaborationRole(currentUserRole, canDeleteConversation, canLeaveConversation) {
  if (!currentUserRole) {
    return '<span class="text-muted">Participant</span>';
  }

  if (currentUserRole === 'owner') {
    return `<span class="badge bg-primary">Owner</span>${canDeleteConversation ? ' <small class="text-muted">Can delete for everyone</small>' : ''}`;
  }
  if (currentUserRole === 'admin') {
    return '<span class="badge bg-info text-dark">Admin</span> <small class="text-muted">Can invite members</small>';
  }
  if (canLeaveConversation) {
    return '<span class="badge bg-secondary">Member</span>';
  }
  return '<span class="text-muted">Participant</span>';
}

function renderCollaborationActionButtons(conversationId, metadata) {
  if (metadata.can_accept_invite) {
    return `
      <div class="d-flex gap-2">
        <button type="button" class="btn btn-light btn-sm" data-collaboration-action="accept-invite" data-conversation-id="${conversationId}">
          <i class="bi bi-check-circle me-1"></i>Accept
        </button>
        <button type="button" class="btn btn-outline-light btn-sm" data-collaboration-action="decline-invite" data-conversation-id="${conversationId}">
          <i class="bi bi-x-circle me-1"></i>Decline
        </button>
      </div>
    `;
  }

  if (metadata.can_manage_members) {
    return `
      <button type="button" class="btn btn-light btn-sm" data-collaboration-action="add-participant" data-conversation-id="${conversationId}">
        <i class="bi bi-person-plus me-1"></i>Add participant
      </button>
    `;
  }

  return '';
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
    const groupContextBadge = primary.scope === 'group' ? '<span class="badge bg-secondary me-2">group</span>' : '';
    
    html += `
      <div class="mb-3">
        <strong class="text-primary">Primary Context:</strong>
        <div class="ms-3 mt-1">
          <div class="d-flex align-items-center mb-2">
            <span class="badge bg-primary me-2">${primary.scope}</span>
            ${groupContextBadge}
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
function renderParticipantsSection(participants, options = {}) {
  let html = '';
  
  participants.forEach(participant => {
    const displayName = participant.display_name || participant.name || 'Unknown User';
    const participantStatus = participant.status || null;
    const participantRole = participant.role || null;
    const initials = displayName.slice(0, 2).toUpperCase();
    const avatarId = `participant-avatar-${participant.user_id}`;
    const canRemoveParticipant = Boolean(options.canManageMembers)
      && options.conversationKind === 'collaborative'
      && participantRole !== 'owner';
    const canToggleAdmin = Boolean(options.canManageRoles)
      && options.conversationKind === 'collaborative'
      && participantRole !== 'owner'
      && participantStatus === 'accepted';

    let statusBadgesHtml = '';
    if (participantRole === 'owner') {
      statusBadgesHtml += '<span class="badge bg-primary-subtle text-primary-emphasis ms-2">Owner</span>';
    }
    if (participantRole === 'admin') {
      statusBadgesHtml += '<span class="badge bg-info-subtle text-info-emphasis ms-2">Admin</span>';
    }
    if (participantStatus === 'pending') {
      statusBadgesHtml += '<span class="badge bg-warning text-dark ms-2">Pending</span>';
    }
    if (participantStatus === 'removed') {
      statusBadgesHtml += '<span class="badge bg-secondary ms-2">Removed</span>';
    }
    if (participantStatus === 'declined') {
      statusBadgesHtml += '<span class="badge bg-light text-dark ms-2">Declined</span>';
    }

    const participantActions = [];
    if (canToggleAdmin) {
      const nextRole = participantRole === 'admin' ? 'member' : 'admin';
      const roleActionLabel = participantRole === 'admin' ? 'Remove admin' : 'Make admin';
      participantActions.push(`
        <button type="button" class="btn btn-outline-primary btn-sm" data-collaboration-action="toggle-participant-role" data-member-user-id="${participant.user_id}" data-next-role="${nextRole}">
          <i class="bi bi-shield-lock me-1"></i>${roleActionLabel}
        </button>
      `);
    }
    if (canRemoveParticipant) {
      participantActions.push(`
        <button type="button" class="btn btn-outline-danger btn-sm" data-collaboration-action="remove-participant" data-member-user-id="${participant.user_id}">
          <i class="bi bi-person-dash"></i>
        </button>
      `);
    }
    
    html += `
      <div class="d-flex align-items-center justify-content-between mb-2 gap-3">
        <div id="${avatarId}" class="rounded-circle bg-primary text-white d-flex align-items-center justify-content-center me-3" style="width: 32px; height: 32px; font-size: 0.9rem;">
          ${initials}
        </div>
        <div class="flex-grow-1 overflow-hidden">
          <div class="fw-semibold text-truncate">${displayName}${statusBadgesHtml}</div>
          <small class="text-muted">${participant.email || ''}</small>
        </div>
        ${participantActions.length > 0 ? `<div class="d-flex flex-wrap justify-content-end gap-2">${participantActions.join('')}</div>` : ''}
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

function attachConversationDetailActions(metadata, conversationId) {
  const addParticipantBtn = document.querySelector('[data-collaboration-action="add-participant"]');
  const acceptInviteBtn = document.querySelector('[data-collaboration-action="accept-invite"]');
  const declineInviteBtn = document.querySelector('[data-collaboration-action="decline-invite"]');
  const removeParticipantButtons = document.querySelectorAll('[data-collaboration-action="remove-participant"]');
  const roleButtons = document.querySelectorAll('[data-collaboration-action="toggle-participant-role"]');
  const exportConversationBtn = document.querySelector('[data-conversation-action="export"]');
  const deleteConversationBtn = document.querySelector('[data-conversation-action="delete"]');

  if (addParticipantBtn) {
    addParticipantBtn.addEventListener('click', () => {
      window.chatCollaboration?.openParticipantPicker?.({ conversationId });
    });
  }

  if (acceptInviteBtn) {
    acceptInviteBtn.addEventListener('click', () => {
      window.chatCollaboration?.respondToInvite?.(conversationId, 'accept');
    });
  }

  if (declineInviteBtn) {
    declineInviteBtn.addEventListener('click', () => {
      window.chatCollaboration?.respondToInvite?.(conversationId, 'decline');
    });
  }

  removeParticipantButtons.forEach(button => {
    button.addEventListener('click', () => {
      const memberUserId = button.getAttribute('data-member-user-id');
      if (!memberUserId) {
        return;
      }
      window.chatCollaboration?.removeParticipant?.(conversationId, memberUserId);
    });
  });

  roleButtons.forEach(button => {
    button.addEventListener('click', () => {
      const memberUserId = button.getAttribute('data-member-user-id');
      const nextRole = button.getAttribute('data-next-role');
      if (!memberUserId || !nextRole) {
        return;
      }
      window.chatCollaboration?.updateParticipantRole?.(conversationId, memberUserId, nextRole);
    });
  });

  if (exportConversationBtn) {
    exportConversationBtn.addEventListener('click', () => {
      window.chatExport?.openExportWizard?.([conversationId], true);
    });
  }

  if (deleteConversationBtn) {
    deleteConversationBtn.addEventListener('click', () => {
      window.chatConversations?.deleteConversation?.(conversationId);
    });
  }
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

function formatScopeLockStatus(scopeLocked, lockedContexts) {
  if (scopeLocked === null || scopeLocked === undefined) {
    return '<span class="badge bg-secondary">N/A</span>';
  }
  if (scopeLocked === true) {
    const groups = window.userGroups || [];
    const publicWorkspaces = window.userVisiblePublicWorkspaces || [];
    const groupMap = {};
    groups.forEach(g => { groupMap[g.id] = g.name; });
    const pubMap = {};
    publicWorkspaces.forEach(ws => { pubMap[ws.id] = ws.name; });

    const names = (lockedContexts || []).map(ctx => {
      if (ctx.scope === 'personal') return 'Personal';
      if (ctx.scope === 'group') return groupMap[ctx.id] || ctx.id;
      if (ctx.scope === 'public') return pubMap[ctx.id] || ctx.id;
      return ctx.scope;
    });
    return '<span class="badge bg-success"><i class="bi bi-lock-fill me-1"></i>Locked</span>' +
      (names.length > 0 ? '<br><small class="text-muted">' + names.join(', ') + '</small>' : '');
  }
  // false — unlocked
  return '<span class="badge bg-warning text-dark"><i class="bi bi-unlock me-1"></i>Unlocked</span>';
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
  if (chatType === 'personal' || chatType === 'personal_single_user') {
    return '<span class="text-muted">personal</span>';
  } else if (chatType === 'new') {
    return '<span class="badge bg-secondary">new</span>';
  } else if (chatType === 'group' || chatType.startsWith('group')) {
    // For group chats, try to find the group name from context
    const primaryContext = context.find(c => c.type === 'primary' && c.scope === 'group');
    const groupName = primaryContext ? primaryContext.name || 'Group' : 'Group';

    return `<span class="badge bg-info" title="${escapeHtml(groupName)}">${escapeHtml(groupName)}</span>`;
  } else if (chatType && chatType.startsWith('public')) {
    return '<span class="badge bg-success">public</span>';
  } else {
    // Fallback for unknown types
    return `<span class="text-muted">${escapeHtml(chatType)}</span>`;
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

/**
 * Render the summary card body content
 * @param {Object|null} summary - Existing summary data or null
 * @param {string} conversationId - The conversation ID
 * @returns {string} HTML string
 */
function renderSummaryContent(summary, conversationId) {
  if (summary && summary.content) {
    return `
      <p class="mb-2">${escapeHtml(summary.content)}</p>
      <div class="d-flex justify-content-end">
        <button class="btn btn-sm btn-outline-secondary" id="regenerate-summary-btn"
                data-conversation-id="${conversationId}">
          <i class="bi bi-arrow-clockwise me-1"></i>Regenerate
        </button>
      </div>
    `;
  }

  // Build model options from the global model-select dropdown
  const modelOptions = getAvailableModelOptions();
  return `
    <p class="text-muted mb-3">No summary has been generated for this conversation yet.</p>
    <div class="d-flex align-items-center gap-2">
      <select class="form-select form-select-sm" id="summary-model-select" style="max-width: 260px;">
        ${modelOptions}
      </select>
      <button class="btn btn-sm btn-primary" id="generate-summary-btn"
              data-conversation-id="${conversationId}">
        <i class="bi bi-blockquote-left me-1"></i>Generate Summary
      </button>
    </div>
  `;
}

/**
 * Get available model options from the global #model-select dropdown
 * @returns {string} HTML option elements
 */
function getAvailableModelOptions() {
  const globalSelect = document.getElementById('model-select');
  if (!globalSelect) {
    return '<option value="">Default</option>';
  }
  let options = '';
  for (const opt of globalSelect.options) {
    options += `<option value="${escapeHtml(opt.value)}"${opt.selected ? ' selected' : ''}>${escapeHtml(opt.text)}</option>`;
  }
  return options || '<option value="">Default</option>';
}

/**
 * Handle summary generation (generate or regenerate)
 * @param {string} conversationId - The conversation ID
 * @param {string} modelDeployment - Selected model deployment
 */
async function handleGenerateSummary(conversationId, modelDeployment) {
  const cardBody = document.getElementById('summary-card-body');
  if (!cardBody) {
    return;
  }

  cardBody.innerHTML = `
    <div class="d-flex align-items-center gap-2">
      <div class="spinner-border spinner-border-sm text-primary" role="status">
        <span class="visually-hidden">Generating...</span>
      </div>
      <span class="text-muted">Generating summary...</span>
    </div>
  `;

  try {
    const response = await fetch(`/api/conversations/${conversationId}/summary`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_deployment: modelDeployment })
    });

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${response.status}`);
    }

    const data = await response.json();
    const summary = data.summary;
    cardBody.innerHTML = renderSummaryContent(summary, conversationId);

    // Update card header with generation info
    const cardHeader = cardBody.closest('.card').querySelector('.card-header');
    if (cardHeader && summary) {
      const smallEl = cardHeader.querySelector('small');
      const infoText = `Generated ${formatDate(summary.generated_at)}${summary.model_deployment ? ` · ${summary.model_deployment}` : ''}`;
      if (smallEl) {
        smallEl.textContent = infoText;
      } else {
        const small = document.createElement('small');
        small.className = 'opacity-75';
        small.textContent = infoText;
        cardHeader.appendChild(small);
      }
    }

  } catch (error) {
    console.error('Error generating summary:', error);
    cardBody.innerHTML = `
      <div class="text-danger mb-2">
        <i class="bi bi-exclamation-triangle me-1"></i>
        Failed to generate summary: ${escapeHtml(error.message)}
      </div>
      ${renderSummaryContent(null, conversationId)}
    `;
  }
}

/**
 * Simple HTML escapefor display
 * @param {string} str - String to escape
 * @returns {string} Escaped string
 */
function escapeHtml(str) {
  if (!str) {
    return '';
  }
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// Event listeners for details buttons
document.addEventListener('click', function(e) {
  // Generate summary button
  if (e.target.closest('#generate-summary-btn')) {
    e.preventDefault();
    const btn = e.target.closest('#generate-summary-btn');
    const cid = btn.getAttribute('data-conversation-id');
    const modelSelect = document.getElementById('summary-model-select');
    const selectedOption = modelSelect ? modelSelect.options[modelSelect.selectedIndex] : null;
    const model = selectedOption?.dataset?.deploymentName || (modelSelect ? modelSelect.value : '');
    handleGenerateSummary(cid, model);
    return;
  }

  // Regenerate summary button
  if (e.target.closest('#regenerate-summary-btn')) {
    e.preventDefault();
    const btn = e.target.closest('#regenerate-summary-btn');
    const cid = btn.getAttribute('data-conversation-id');
    // Use the currently selected global model for regeneration
    const globalSelect = document.getElementById('model-select');
    const selectedOption = globalSelect ? globalSelect.options[globalSelect.selectedIndex] : null;
    const model = selectedOption?.dataset?.deploymentName || (globalSelect ? globalSelect.value : '');
    handleGenerateSummary(cid, model);
    return;
  }

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
window.hideConversationDetails = hideConversationDetails;

function initializeConversationDetailsModal() {
  const { modal } = getConversationDetailsModalElements();
  if (!modal || modal.dataset.initialized === 'true') {
    return;
  }

  modal.dataset.initialized = 'true';
  modal.addEventListener('hidden.bs.modal', cleanupConversationDetailsModalState);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeConversationDetailsModal);
} else {
  initializeConversationDetailsModal();
}
