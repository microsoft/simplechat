// chat-sidebar-conversations.js
// Handles conversations list in the sidebar when on the chats page

import { showToast } from "./chat-toast.js";

const sidebarConversationsList = document.getElementById("sidebar-conversations-list");
const sidebarNewChatBtn = document.getElementById("sidebar-new-chat-btn");

let currentActiveConversationId = null;
let sidebarShowHiddenConversations = false; // Track if hidden conversations should be shown in sidebar
let isLoadingSidebarConversations = false; // Prevent concurrent sidebar loads

// Load conversations for the sidebar
export function loadSidebarConversations() {
  if (!sidebarConversationsList) return;
  
  // Prevent concurrent loads
  if (isLoadingSidebarConversations) {
    console.log('Sidebar load already in progress, skipping...');
    return;
  }
  
  isLoadingSidebarConversations = true;
  sidebarConversationsList.innerHTML = '<div class="text-center p-2 text-muted small">Loading conversations...</div>';

  fetch("/api/get_conversations")
    .then(response => response.ok ? response.json() : response.json().then(err => Promise.reject(err)))
    .then(data => {
      sidebarConversationsList.innerHTML = "";
      if (!data.conversations || data.conversations.length === 0) {
        sidebarConversationsList.innerHTML = '<div class="text-center p-2 text-muted small">No conversations yet.</div>';
        return;
      }
      
      // Sort conversations: pinned first (by last_updated), then unpinned (by last_updated)
      const sortedConversations = [...data.conversations].sort((a, b) => {
        const aPinned = a.is_pinned || false;
        const bPinned = b.is_pinned || false;
        
        // If pin status differs, pinned comes first
        if (aPinned !== bPinned) {
          return bPinned ? 1 : -1;
        }
        
        // If same pin status, sort by last_updated (most recent first)
        const aDate = new Date(a.last_updated);
        const bDate = new Date(b.last_updated);
        return bDate - aDate;
      });
      
      // Filter conversations based on show/hide hidden setting
      let visibleConversations = sortedConversations.filter(convo => {
        const isHidden = convo.is_hidden || false;
        // Show hidden conversations if toggle is on OR if we're in selection mode
        const isSelectionMode = window.chatConversations && window.chatConversations.isSelectionModeActive && window.chatConversations.isSelectionModeActive();
        return !isHidden || sidebarShowHiddenConversations || isSelectionMode;
      });
      
      // Apply quick search filter if active
      if (window.chatConversations && window.chatConversations.getQuickSearchTerm) {
        const searchTerm = window.chatConversations.getQuickSearchTerm();
        if (searchTerm && searchTerm.trim() !== '') {
          const searchLower = searchTerm.toLowerCase().trim();
          visibleConversations = visibleConversations.filter(convo => {
            const titleLower = (convo.title || '').toLowerCase();
            return titleLower.includes(searchLower);
          });
        }
      }
      
      visibleConversations.forEach(convo => {
        sidebarConversationsList.appendChild(createSidebarConversationItem(convo));
      });
      
      // Restore selection mode hints if selection mode is active
      if (window.chatConversations && window.chatConversations.isSelectionModeActive && window.chatConversations.isSelectionModeActive()) {
        setSidebarSelectionMode(true);
        
        // Restore individual conversation selections
        if (window.chatConversations.getSelectedConversations) {
          const selectedIds = window.chatConversations.getSelectedConversations();
          selectedIds.forEach(id => {
            updateSidebarConversationSelection(id, true);
          });
        }
      }
      
      // Reset loading flag
      isLoadingSidebarConversations = false;
    })
    .catch(error => {
      console.error("Error loading sidebar conversations:", error);
      sidebarConversationsList.innerHTML = `<div class="text-center p-2 text-danger small">Error loading conversations: ${error.error || 'Unknown error'}</div>`;
      isLoadingSidebarConversations = false; // Reset flag on error too
    });
}

// Create a conversation item for the sidebar
function createSidebarConversationItem(convo) {
  const convoItem = document.createElement("div");
  convoItem.classList.add("sidebar-conversation-item");
  convoItem.setAttribute("data-conversation-id", convo.id);
  if (convo.chat_type) {
    convoItem.setAttribute("data-chat-type", convo.chat_type);
  }
  let groupName = null;
  if (Array.isArray(convo.context)) {
    const primaryGroupContext = convo.context.find(ctx => ctx.type === "primary" && ctx.scope === "group");
    if (primaryGroupContext) {
      groupName = primaryGroupContext.name || null;
    }
  }
  if (groupName) {
    convoItem.setAttribute("data-group-name", groupName);
  }
  
  const isPinned = convo.is_pinned || false;
  const isHidden = convo.is_hidden || false;
  const pinIcon = isPinned ? '<i class="bi bi-pin-angle me-1"></i>' : '';
  const hiddenIcon = isHidden ? '<i class="bi bi-eye-slash me-1 text-muted"></i>' : '';
  
  convoItem.innerHTML = `
    <div class="d-flex justify-content-between align-items-center">
      <div class="sidebar-conversation-title flex-grow-1" title="${convo.title} (Double-click to edit)">${pinIcon}${hiddenIcon}${convo.title}</div>
      <div class="dropdown conversation-dropdown" style="opacity: 0; transition: opacity 0.2s;">
        <button class="btn btn-light btn-sm" type="button" data-bs-toggle="dropdown" data-bs-display="static" aria-expanded="false" title="Conversation options">
          <i class="bi bi-three-dots-vertical"></i>
        </button>
        <ul class="dropdown-menu dropdown-menu-end">
          <li><a class="dropdown-item details-btn" href="#"><i class="bi bi-info-circle me-2"></i>Details</a></li>
          <li><a class="dropdown-item pin-btn" href="#"><i class="bi bi-pin-angle me-2"></i>${isPinned ? 'Unpin' : 'Pin'}</a></li>
          <li><a class="dropdown-item hide-btn" href="#"><i class="bi bi-${isHidden ? 'eye' : 'eye-slash'} me-2"></i>${isHidden ? 'Unhide' : 'Hide'}</a></li>
          <li><a class="dropdown-item select-btn" href="#"><i class="bi bi-check-square me-2"></i>Select</a></li>
          <li><a class="dropdown-item edit-btn" href="#"><i class="bi bi-pencil-fill me-2"></i>Edit title</a></li>
          <li><a class="dropdown-item delete-btn text-danger" href="#"><i class="bi bi-trash-fill me-2"></i>Delete</a></li>
        </ul>
      </div>
    </div>
  `;

  const headerRow = convoItem.querySelector(".d-flex.justify-content-between.align-items-center");
  const dropdownElement = headerRow ? headerRow.querySelector('.conversation-dropdown') : null;
  const originalTitleElement = headerRow ? headerRow.querySelector('.sidebar-conversation-title') : null;

  if (headerRow && dropdownElement && originalTitleElement) {
    const titleWrapper = document.createElement('div');
    titleWrapper.classList.add('sidebar-conversation-header', 'd-flex', 'align-items-center', 'flex-grow-1', 'overflow-hidden', 'gap-2');

    // Ensure the title can truncate correctly within the new wrapper
    originalTitleElement.classList.add('flex-grow-1', 'text-truncate');
    originalTitleElement.style.minWidth = '0';

    titleWrapper.appendChild(originalTitleElement);

    const isGroupConversation = (convo.chat_type && convo.chat_type.startsWith('group')) || groupName;
    if (isGroupConversation) {
      const badge = document.createElement('span');
      badge.classList.add('badge', 'bg-info', 'sidebar-conversation-group-badge');
      badge.textContent = 'group';
      badge.title = groupName ? `Group conversation: ${groupName}` : 'Group conversation';
      titleWrapper.appendChild(badge);
    }

    headerRow.insertBefore(titleWrapper, dropdownElement);
  }
  
  // Add double-click editing to title
  const titleElement = convoItem.querySelector('.sidebar-conversation-title');
  if (titleElement) {
    titleElement.addEventListener('dblclick', (e) => {
      e.preventDefault();
      e.stopPropagation();
      enableSidebarTitleEdit(convo.id);
    });
  }
  
  // Add hover effect to show/hide dropdown
  convoItem.addEventListener("mouseenter", () => {
    const dropdown = convoItem.querySelector('.conversation-dropdown');
    if (dropdown) {
      dropdown.style.opacity = '1';
    }
  });
  
  convoItem.addEventListener("mouseleave", () => {
    const dropdown = convoItem.querySelector('.conversation-dropdown');
    // Only hide if dropdown is not open
    const dropdownMenu = dropdown.querySelector('.dropdown-menu');
    if (dropdown && !dropdownMenu.classList.contains('show')) {
      dropdown.style.opacity = '0';
    }
  });
  
  // Add click handler to select conversation (but prevent when clicking dropdown)
  convoItem.addEventListener("click", (e) => {
    // Don't trigger conversation selection if clicking on dropdown or its children
    if (e.target.closest('.conversation-dropdown')) {
      return;
    }
    
    // Check if selection mode is active in the main conversation module
    if (window.chatConversations && window.chatConversations.isSelectionModeActive && window.chatConversations.isSelectionModeActive()) {
      // In selection mode, toggle the selection of this conversation
      if (window.chatConversations.toggleConversationSelection) {
        window.chatConversations.toggleConversationSelection(convo.id);
      }
      return;
    }
    
    // If this conversation is hidden, ensure the main conversation list also shows hidden conversations
    if (convo.is_hidden && window.chatConversations && window.chatConversations.setShowHiddenConversations) {
      window.chatConversations.setShowHiddenConversations(true);
      
      // Wait a moment for the DOM to update before selecting
      setTimeout(() => {
        setActiveConversation(convo.id);
        if (window.chatConversations && window.chatConversations.selectConversation) {
          window.chatConversations.selectConversation(convo.id);
        }
      }, 50);
    } else {
      // Normal mode: select the conversation immediately
      setActiveConversation(convo.id);
      // Call selectConversation from chat-conversations.js through global reference
      if (window.chatConversations && window.chatConversations.selectConversation) {
        window.chatConversations.selectConversation(convo.id);
      }
    }
  });
  
  // Add dropdown menu event handlers
  const detailsBtn = convoItem.querySelector('.details-btn');
  const pinBtn = convoItem.querySelector('.pin-btn');
  const hideBtn = convoItem.querySelector('.hide-btn');
  const selectBtn = convoItem.querySelector('.select-btn');
  const editBtn = convoItem.querySelector('.edit-btn');
  const deleteBtn = convoItem.querySelector('.delete-btn');
  
  if (detailsBtn) {
    detailsBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      // Close dropdown after action
      const dropdownBtn = convoItem.querySelector('[data-bs-toggle="dropdown"]');
      if (dropdownBtn) {
        const dropdownInstance = bootstrap.Dropdown.getInstance(dropdownBtn);
        if (dropdownInstance) {
          dropdownInstance.hide();
        }
      }
      // Show conversation details
      if (window.showConversationDetails) {
        window.showConversationDetails(convo.id);
      }
    });
  }
  
  if (pinBtn) {
    pinBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();
      // Close dropdown after action
      const dropdownBtn = convoItem.querySelector('[data-bs-toggle="dropdown"]');
      if (dropdownBtn) {
        const dropdownInstance = bootstrap.Dropdown.getInstance(dropdownBtn);
        if (dropdownInstance) {
          dropdownInstance.hide();
        }
      }
      // Toggle pin status
      try {
        const response = await fetch(`/api/conversations/${convo.id}/pin`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' }
        });
        if (response.ok) {
          const data = await response.json();
          loadSidebarConversations();
          if (window.chatConversations && window.chatConversations.loadConversations) {
            window.chatConversations.loadConversations();
          }
          if (window.showToast) {
            showToast(data.is_pinned ? "Conversation pinned." : "Conversation unpinned.", "success");
          }
        }
      } catch (error) {
        console.error("Error toggling pin:", error);
        if (window.showToast) {
          showToast("Error toggling pin status.", "danger");
        }
      }
    });
  }
  
  if (hideBtn) {
    hideBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();
      // Close dropdown after action
      const dropdownBtn = convoItem.querySelector('[data-bs-toggle="dropdown"]');
      if (dropdownBtn) {
        const dropdownInstance = bootstrap.Dropdown.getInstance(dropdownBtn);
        if (dropdownInstance) {
          dropdownInstance.hide();
        }
      }
      // Toggle hide status
      try {
        const response = await fetch(`/api/conversations/${convo.id}/hide`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' }
        });
        if (response.ok) {
          const data = await response.json();
          loadSidebarConversations();
          if (window.chatConversations && window.chatConversations.loadConversations) {
            window.chatConversations.loadConversations();
          }
          if (window.showToast) {
            showToast(data.is_hidden ? "Conversation hidden." : "Conversation unhidden.", "success");
          }
        }
      } catch (error) {
        console.error("Error toggling hide:", error);
        if (window.showToast) {
          showToast("Error toggling hide status.", "danger");
        }
      }
    });
  }
  
  if (selectBtn) {
    selectBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      // Close dropdown after action
      const dropdownBtn = convoItem.querySelector('[data-bs-toggle="dropdown"]');
      if (dropdownBtn) {
        const dropdownInstance = bootstrap.Dropdown.getInstance(dropdownBtn);
        if (dropdownInstance) {
          dropdownInstance.hide();
        }
      }
      // Toggle selection mode
      if (window.chatConversations && window.chatConversations.toggleConversationSelection) {
        window.chatConversations.toggleConversationSelection(convo.id);
      }
    });
  }
  
  if (editBtn) {
    editBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      // Close dropdown after action
      const dropdownBtn = convoItem.querySelector('[data-bs-toggle="dropdown"]');
      if (dropdownBtn) {
        const dropdownInstance = bootstrap.Dropdown.getInstance(dropdownBtn);
        if (dropdownInstance) {
          dropdownInstance.hide();
        }
      }
      // Enable inline editing for this conversation
      enableSidebarTitleEdit(convo.id);
    });
  }
  
  if (deleteBtn) {
    deleteBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      // Close dropdown after action
      const dropdownBtn = convoItem.querySelector('[data-bs-toggle="dropdown"]');
      if (dropdownBtn) {
        const dropdownInstance = bootstrap.Dropdown.getInstance(dropdownBtn);
        if (dropdownInstance) {
          dropdownInstance.hide();
        }
      }
      // Delete conversation
      if (window.chatConversations && window.chatConversations.deleteConversation) {
        window.chatConversations.deleteConversation(convo.id);
      }
    });
  }
  
  // Handle dropdown show/hide events for opacity
  const dropdownBtn = convoItem.querySelector('[data-bs-toggle="dropdown"]');
  if (dropdownBtn) {
    dropdownBtn.addEventListener('shown.bs.dropdown', () => {
      const dropdown = convoItem.querySelector('.conversation-dropdown');
      if (dropdown) {
        dropdown.style.opacity = '1';
      }
    });
    
    dropdownBtn.addEventListener('hidden.bs.dropdown', () => {
      const dropdown = convoItem.querySelector('.conversation-dropdown');
      if (dropdown && !convoItem.matches(':hover')) {
        dropdown.style.opacity = '0';
      }
    });
  }
  
  return convoItem;
}

// Set the active conversation in the sidebar
export function setActiveConversation(conversationId) {
  // Remove active class from all conversation items
  document.querySelectorAll('.sidebar-conversation-item').forEach(item => {
    item.classList.remove('active');
  });
  
  // Add active class to the selected conversation
  if (conversationId) {
    const activeItem = document.querySelector(`.sidebar-conversation-item[data-conversation-id="${conversationId}"]`);
    if (activeItem) {
      activeItem.classList.add('active');
    }
  }
  
  currentActiveConversationId = conversationId;
}

// Get the currently active conversation ID
export function getActiveConversationId() {
  return currentActiveConversationId;
}

// Update sidebar conversation selection state (called from main conversation module)
export function updateSidebarConversationSelection(conversationId, isSelected) {
  const sidebarItem = document.querySelector(`.sidebar-conversation-item[data-conversation-id="${conversationId}"]`);
  if (sidebarItem) {
    if (isSelected) {
      sidebarItem.classList.add('selected');
    } else {
      sidebarItem.classList.remove('selected');
    }
  }
}

// Clear all selections in sidebar
export function clearSidebarSelections() {
  document.querySelectorAll('.sidebar-conversation-item.selected').forEach(item => {
    item.classList.remove('selected');
  });
}

// Update sidebar to show selection mode visual hints
export function setSidebarSelectionMode(isActive) {
  const sidebarItems = document.querySelectorAll('.sidebar-conversation-item');
  const conversationsToggle = document.getElementById('conversations-toggle');
  const conversationsActions = document.getElementById('conversations-actions');
  const sidebarDeleteBtn = document.getElementById('sidebar-delete-selected-btn');
  const sidebarPinBtn = document.getElementById('sidebar-pin-selected-btn');
  const sidebarHideBtn = document.getElementById('sidebar-hide-selected-btn');
  const sidebarSettingsBtn = document.getElementById('sidebar-conversations-settings-btn');
  const sidebarSearchBtn = document.getElementById('sidebar-search-btn');
  
  sidebarItems.forEach(item => {
    if (isActive) {
      item.classList.add('selection-mode-hint');
    } else {
      item.classList.remove('selection-mode-hint');
    }
  });
  
  // Update the conversations header to show selection mode
  if (conversationsToggle && conversationsActions) {
    if (isActive) {
      conversationsToggle.style.color = '#856404';
      conversationsToggle.style.fontWeight = '600';
      conversationsActions.style.display = 'flex !important';
      conversationsActions.style.setProperty('display', 'flex', 'important');
      // Hide the search and eye buttons in selection mode
      if (sidebarSettingsBtn) {
        sidebarSettingsBtn.style.display = 'none';
      }
      if (sidebarSearchBtn) {
        sidebarSearchBtn.style.display = 'none';
      }
      // Add a selection indicator button
      let indicator = conversationsToggle.querySelector('.selection-indicator');
      if (!indicator) {
        indicator = document.createElement('button');
        indicator.className = 'selection-indicator btn btn-sm ms-1';
        indicator.style.cssText = 'background: none; border: none; padding: 2px 4px; border-radius: 4px; color: #ffc107; transition: background-color 0.2s ease;';
        indicator.innerHTML = '<i class="bi bi-check-square" style="font-size: 0.8em;"></i>';
        indicator.title = 'Exit selection mode';
        indicator.setAttribute('aria-label', 'Exit selection mode');
        
        // Add click handler to exit selection mode
        indicator.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          if (window.chatConversations && window.chatConversations.exitSelectionMode) {
            window.chatConversations.exitSelectionMode();
          }
        });
        
        // Add hover effect
        indicator.addEventListener('mouseenter', () => {
          indicator.style.backgroundColor = 'rgba(255, 193, 7, 0.2)';
        });
        indicator.addEventListener('mouseleave', () => {
          indicator.style.backgroundColor = 'transparent';
        });
        
        conversationsToggle.querySelector('.d-flex.align-items-center').appendChild(indicator);
      }
    } else {
      conversationsToggle.style.color = '';
      conversationsToggle.style.fontWeight = '';
      conversationsActions.style.display = 'none !important';
      conversationsActions.style.setProperty('display', 'none', 'important');
      if (sidebarDeleteBtn) {
        sidebarDeleteBtn.style.display = 'none';
      }
      if (sidebarPinBtn) {
        sidebarPinBtn.style.display = 'none';
      }
      if (sidebarHideBtn) {
        sidebarHideBtn.style.display = 'none';
      }
      // Show the search and eye buttons again when exiting selection mode
      if (sidebarSettingsBtn) {
        sidebarSettingsBtn.style.display = 'inline-block';
      }
      if (sidebarSearchBtn) {
        sidebarSearchBtn.style.display = 'inline-block';
      }
      // Remove selection indicator
      const indicator = conversationsToggle.querySelector('.selection-indicator');
      if (indicator) {
        indicator.remove();
      }
    }
  }
}

// Update sidebar action buttons visibility based on selection count
export function updateSidebarDeleteButton(selectedCount) {
  const sidebarDeleteBtn = document.getElementById('sidebar-delete-selected-btn');
  const sidebarPinBtn = document.getElementById('sidebar-pin-selected-btn');
  const sidebarHideBtn = document.getElementById('sidebar-hide-selected-btn');
  
  if (selectedCount > 0) {
    if (sidebarDeleteBtn) {
      sidebarDeleteBtn.style.display = 'inline-flex';
      sidebarDeleteBtn.title = `Delete ${selectedCount} selected conversation${selectedCount > 1 ? 's' : ''}`;
    }
    if (sidebarPinBtn) {
      sidebarPinBtn.style.display = 'inline-flex';
      sidebarPinBtn.title = `Pin ${selectedCount} selected conversation${selectedCount > 1 ? 's' : ''}`;
    }
    if (sidebarHideBtn) {
      sidebarHideBtn.style.display = 'inline-flex';
      sidebarHideBtn.title = `Hide ${selectedCount} selected conversation${selectedCount > 1 ? 's' : ''}`;
    }
  } else {
    if (sidebarDeleteBtn) {
      sidebarDeleteBtn.style.display = 'none';
    }
    if (sidebarPinBtn) {
      sidebarPinBtn.style.display = 'none';
    }
    if (sidebarHideBtn) {
      sidebarHideBtn.style.display = 'none';
    }
  }
}

// Update sidebar conversation title after edit
export function updateSidebarConversationTitle(conversationId, newTitle) {
  const sidebarItem = document.querySelector(`.sidebar-conversation-item[data-conversation-id="${conversationId}"]`);
  if (sidebarItem) {
    const titleElement = sidebarItem.querySelector('.sidebar-conversation-title');
    if (titleElement) {
      titleElement.textContent = newTitle;
      titleElement.title = `${newTitle} (Double-click to edit)`;
    }
  }
  
  // Update conversation header in right pane if this is the currently active conversation
  if (window.chatConversations && window.chatConversations.updateConversationHeader) {
    window.chatConversations.updateConversationHeader(conversationId, newTitle);
  }
}

// Enable inline editing for a conversation title in the sidebar
export function enableSidebarTitleEdit(conversationId) {
  const sidebarItem = document.querySelector(`.sidebar-conversation-item[data-conversation-id="${conversationId}"]`);
  if (!sidebarItem) return;
  
  const titleElement = sidebarItem.querySelector('.sidebar-conversation-title');
  if (!titleElement) return;
  
  const currentTitle = titleElement.textContent;
  const originalTitle = currentTitle;
  
  // Create input element
  const input = document.createElement('input');
  input.type = 'text';
  input.value = currentTitle;
  input.className = 'form-control form-control-sm';
  input.style.cssText = 'font-size: 0.875rem; height: auto; padding: 2px 6px; border-radius: 4px;';
  
  // Replace title with input
  titleElement.style.display = 'none';
  titleElement.parentNode.insertBefore(input, titleElement.nextSibling);
  
  // Focus and select all text
  input.focus();
  input.select();
  
  // Flag to prevent multiple save calls
  let isSaving = false;
  let isComplete = false;
  
  // Function to save changes
  const saveChanges = async () => {
    if (isSaving || isComplete) return;
    isSaving = true;
    
    const newTitle = input.value.trim();
    
    if (newTitle === '' || newTitle === originalTitle) {
      // Restore original title
      titleElement.style.display = '';
      input.remove();
      isComplete = true;
      return;
    }
    
    try {
      // Call the update function from main module
      const response = await fetch(`/api/conversations/${conversationId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          title: newTitle
        })
      });
      
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to update title');
      }
      
      // Update the title element
      titleElement.textContent = newTitle;
      titleElement.title = `${newTitle} (Double-click to edit)`;
      titleElement.style.display = '';
      input.remove();
      isComplete = true;
      
      // Show success toast
      showToast('Conversation title updated.', 'success');
      
      // Update conversation header in right pane if this is the currently active conversation
      if (window.chatConversations && window.chatConversations.updateConversationHeader) {
        window.chatConversations.updateConversationHeader(conversationId, newTitle);
      }
      
    } catch (error) {
      console.error('Error updating conversation title:', error);
      showToast(`Failed to update title: ${error.message}`, 'danger');
      
      // Restore original title
      titleElement.style.display = '';
      input.remove();
      isComplete = true;
    }
    
    isSaving = false;
  };
  
  // Function to cancel editing
  const cancelEdit = () => {
    if (isComplete) return;
    titleElement.style.display = '';
    input.remove();
    isComplete = true;
  };
  
  // Handle Enter key to save
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      saveChanges();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelEdit();
    }
  });
  
  // Handle blur (clicking outside) to save
  input.addEventListener('blur', () => {
    // Small delay to allow Enter key handler to complete first
    setTimeout(() => {
      if (!isComplete) {
        saveChanges();
      }
    }, 10);
  });
  
  // Prevent conversation selection when clicking on the input
  input.addEventListener('click', (e) => {
    e.stopPropagation();
  });
}

// Initialize sidebar conversations functionality
document.addEventListener('DOMContentLoaded', () => {
  // Only initialize if we're on the chats page and elements exist
  if (sidebarConversationsList) {
    loadSidebarConversations();
    
    // Handle new chat button click
    if (sidebarNewChatBtn) {
      sidebarNewChatBtn.addEventListener('click', () => {
        // Trigger the main new conversation button
        const mainNewConversationBtn = document.getElementById('new-conversation-btn');
        if (mainNewConversationBtn) {
          mainNewConversationBtn.click();
        }
      });
    }
    
    // Handle sidebar pin selected button click
    const sidebarPinBtn = document.getElementById('sidebar-pin-selected-btn');
    if (sidebarPinBtn) {
      sidebarPinBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        // Trigger the main pin selected functionality
        if (window.chatConversations && window.chatConversations.bulkPinConversations) {
          window.chatConversations.bulkPinConversations();
        }
      });
    }
    
    // Handle sidebar hide selected button click
    const sidebarHideBtn = document.getElementById('sidebar-hide-selected-btn');
    if (sidebarHideBtn) {
      sidebarHideBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        // Trigger the main hide selected functionality
        if (window.chatConversations && window.chatConversations.bulkHideConversations) {
          window.chatConversations.bulkHideConversations();
        }
      });
    }
    
    // Handle sidebar delete selected button click
    const sidebarDeleteBtn = document.getElementById('sidebar-delete-selected-btn');
    if (sidebarDeleteBtn) {
      sidebarDeleteBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        // Trigger the main delete selected functionality
        if (window.chatConversations && window.chatConversations.deleteSelectedConversations) {
          window.chatConversations.deleteSelectedConversations();
        }
      });
    }
    
    // Handle sidebar settings button click (toggle show/hide hidden conversations)
    const sidebarSettingsBtn = document.getElementById('sidebar-conversations-settings-btn');
    if (sidebarSettingsBtn) {
      sidebarSettingsBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        
        // Toggle show hidden conversations
        sidebarShowHiddenConversations = !sidebarShowHiddenConversations;
        
        // Update button appearance based on state
        const icon = sidebarSettingsBtn.querySelector('i');
        if (icon) {
          if (sidebarShowHiddenConversations) {
            icon.classList.remove('bi-eye');
            icon.classList.add('bi-eye-fill');
            sidebarSettingsBtn.classList.remove('text-muted');
            sidebarSettingsBtn.classList.add('text-primary');
            sidebarSettingsBtn.title = 'Showing hidden conversations (click to hide)';
          } else {
            icon.classList.remove('bi-eye-fill');
            icon.classList.add('bi-eye');
            sidebarSettingsBtn.classList.remove('text-primary');
            sidebarSettingsBtn.classList.add('text-muted');
            sidebarSettingsBtn.title = 'Show/Hide hidden conversations';
          }
        }
        
        // Reload conversations to apply filter
        loadSidebarConversations();
      });
    }
  }
});

// Expose functions globally for main conversation module integration
window.chatSidebarConversations = {
  updateSidebarConversationSelection,
  clearSidebarSelections,
  setSidebarSelectionMode,
  updateSidebarDeleteButton,
  updateSidebarConversationTitle,
  enableSidebarTitleEdit,
  loadSidebarConversations,
  setActiveConversation
};
