// chat-conversations.js

import { showToast } from "./chat-toast.js";
import { loadMessages } from "./chat-messages.js";
import { isColorLight, toBoolean } from "./chat-utils.js";
import { loadSidebarConversations, setActiveConversation as setSidebarActiveConversation } from "./chat-sidebar-conversations.js";
import { toggleConversationInfoButton } from "./chat-conversation-info-button.js";

const newConversationBtn = document.getElementById("new-conversation-btn");
const deleteSelectedBtn = document.getElementById("delete-selected-btn");
const conversationsList = document.getElementById("conversations-list");
const currentConversationTitleEl = document.getElementById("current-conversation-title");
const currentConversationClassificationsEl = document.getElementById("current-conversation-classifications");
const chatbox = document.getElementById("chatbox");

// Track selected conversations
let selectedConversations = new Set();

let currentlyEditingId = null; // Track which item is being edited
let selectionModeActive = false; // Track if selection mode is active
let selectionModeTimer = null; // Timer for auto-hiding checkboxes

// Clear selected conversations when loading the page
document.addEventListener('DOMContentLoaded', () => {
  selectedConversations.clear();
  if (deleteSelectedBtn) {
    deleteSelectedBtn.style.display = "none";
  }
});

// Function to enter selection mode
function enterSelectionMode() {
  selectionModeActive = true;
  if (conversationsList) {
    conversationsList.classList.add('selection-mode');
  }
  
  // Show delete button
  if (deleteSelectedBtn) {
    deleteSelectedBtn.style.display = "block";
  }
  
  // Update sidebar to show selection mode hints
  if (window.chatSidebarConversations && window.chatSidebarConversations.setSidebarSelectionMode) {
    window.chatSidebarConversations.setSidebarSelectionMode(true);
  }
  
  // Start timer to exit selection mode if no selections are made
  resetSelectionModeTimer();
}

// Function to exit selection mode
function exitSelectionMode() {
  selectionModeActive = false;
  if (conversationsList) {
    conversationsList.classList.remove('selection-mode');
  }
  
  // Hide delete button
  if (deleteSelectedBtn) {
    deleteSelectedBtn.style.display = "none";
  }
  
  // Clear any selections
  selectedConversations.clear();
  
  // Update checkbox states
  const checkboxes = document.querySelectorAll('.conversation-checkbox');
  checkboxes.forEach(checkbox => {
    checkbox.checked = false;
  });
  
  // Clear sidebar selections if available
  if (window.chatSidebarConversations && window.chatSidebarConversations.clearSidebarSelections) {
    window.chatSidebarConversations.clearSidebarSelections();
  }
  
  // Update sidebar to remove selection mode hints
  if (window.chatSidebarConversations && window.chatSidebarConversations.setSidebarSelectionMode) {
    window.chatSidebarConversations.setSidebarSelectionMode(false);
  }
  
  // Update sidebar delete button
  if (window.chatSidebarConversations && window.chatSidebarConversations.updateSidebarDeleteButton) {
    window.chatSidebarConversations.updateSidebarDeleteButton(0);
  }
  
  // Clear timer
  if (selectionModeTimer) {
    clearTimeout(selectionModeTimer);
    selectionModeTimer = null;
  }
}

// Function to reset the selection mode timer
function resetSelectionModeTimer() {
  // Clear existing timer
  if (selectionModeTimer) {
    clearTimeout(selectionModeTimer);
  }
  
  // Set new timer - exit selection mode after 5 seconds if no selections
  selectionModeTimer = setTimeout(() => {
    if (selectedConversations.size === 0) {
      exitSelectionMode();
    }
  }, 5000);
}

export function loadConversations() {
  if (!conversationsList) return;
  conversationsList.innerHTML = '<div class="text-center p-3 text-muted">Loading conversations...</div>'; // Loading state

  fetch("/api/get_conversations")
    .then(response => response.ok ? response.json() : response.json().then(err => Promise.reject(err)))
    .then(data => {
      conversationsList.innerHTML = ""; // Clear loading state
      if (!data.conversations || data.conversations.length === 0) {
          conversationsList.innerHTML = '<div class="text-center p-3 text-muted">No conversations yet.</div>';
          return;
      }
      data.conversations.forEach(convo => {
        conversationsList.appendChild(createConversationItem(convo));
      });
      
      // Also load sidebar conversations if the sidebar exists
      if (window.chatSidebarConversations && window.chatSidebarConversations.loadSidebarConversations) {
        window.chatSidebarConversations.loadSidebarConversations();
      }
      
      // Optionally, select the first conversation or highlight the active one if ID is known
    })
    .catch(error => {
      console.error("Error loading conversations:", error);
      conversationsList.innerHTML = `<div class="text-center p-3 text-danger">Error loading conversations: ${error.error || 'Unknown error'}</div>`;
    });
}

export function createConversationItem(convo) {
  const convoItem = document.createElement("div"); // Changed from <a> to <div> for better semantics with checkboxes
  convoItem.classList.add("list-group-item", "list-group-item-action", "conversation-item", "d-flex", "align-items-center"); // Use action class
  convoItem.setAttribute("data-conversation-id", convo.id);
  convoItem.setAttribute("data-conversation-title", convo.title); // Store title too

  // *** Store classification data as stringified JSON ***
  convoItem.dataset.classifications = JSON.stringify(convo.classification || []);
  
  // *** Store chat type and group information based on primary context ***
  // Use the actual chat_type from conversation metadata if available
  console.log(`createConversationItem: Processing conversation ${convo.id}, chat_type="${convo.chat_type}"`);
  
  if (convo.chat_type) {
    convoItem.setAttribute("data-chat-type", convo.chat_type);
    console.log(`createConversationItem: Set data-chat-type to "${convo.chat_type}"`);
    
    // For group chats, try to find group name from context
    if (convo.chat_type.startsWith('group') && convo.context && convo.context.length > 0) {
      const primaryContext = convo.context.find(c => c.type === 'primary' && c.scope === 'group');
      if (primaryContext) {
        convoItem.setAttribute("data-group-name", primaryContext.name || 'Group');
        console.log(`createConversationItem: Set data-group-name to "${primaryContext.name || 'Group'}"`);
      }
    } else if (convo.chat_type.startsWith('public') && convo.context && convo.context.length > 0) {
      const primaryContext = convo.context.find(c => c.type === 'primary' && c.scope === 'public');
      if (primaryContext) {
        convoItem.setAttribute("data-group-name", primaryContext.name || 'Workspace');
        console.log(`createConversationItem: Set data-group-name to "${primaryContext.name || 'Workspace'}"`);
      }
    }
  } else {
    console.log(`createConversationItem: No chat_type found, determining from context`);
    // Determine chat type based on primary context
    if (convo.context && convo.context.length > 0) {
      const primaryContext = convo.context.find(c => c.type === 'primary');
      if (primaryContext) {
        // Primary context exists - documents were used
        if (primaryContext.scope === 'group') {
          convoItem.setAttribute("data-group-name", primaryContext.name || 'Group');
          convoItem.setAttribute("data-chat-type", "group-single-user"); // Default to single-user for now
          console.log(`createConversationItem: Set to group-single-user with name "${primaryContext.name || 'Group'}"`);
        } else if (primaryContext.scope === 'public') {
          convoItem.setAttribute("data-group-name", primaryContext.name || 'Workspace');
          convoItem.setAttribute("data-chat-type", "public");
          console.log(`createConversationItem: Set to public with name "${primaryContext.name || 'Workspace'}"`);
        } else if (primaryContext.scope === 'personal') {
          convoItem.setAttribute("data-chat-type", "personal");
          console.log(`createConversationItem: Set to personal`);
        }
      } else {
        // No primary context - this is a model-only conversation
        // Don't set data-chat-type so no badges will be shown
        console.log(`createConversationItem: No primary context - model-only conversation (no badges)`);
      }
    } else {
      // No context at all - model-only conversation
      console.log(`createConversationItem: No context - model-only conversation (no badges)`);
    }
  }

  // Add checkbox for multi-select
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.classList.add("form-check-input", "me-2", "conversation-checkbox");
  checkbox.setAttribute("data-conversation-id", convo.id);
  
  // Prevent checkbox clicks from triggering conversation selection
  checkbox.addEventListener("click", (event) => {
    event.stopPropagation();
    updateSelectedConversations(convo.id, checkbox.checked);
  });

  const leftDiv = document.createElement("div");
  leftDiv.classList.add("d-flex", "flex-column", "flex-grow-1", "pe-2"); // flex-grow and padding-end
  leftDiv.style.overflow = "hidden"; // Prevent overflow issues

  const titleSpan = document.createElement("span");
  titleSpan.classList.add("conversation-title", "text-truncate"); // Bold and truncate
  titleSpan.textContent = convo.title;
  titleSpan.title = convo.title; // Tooltip for full title

  const dateSpan = document.createElement("small");
  dateSpan.classList.add("text-muted");
  const date = new Date(convo.last_updated);
  dateSpan.textContent = date.toLocaleString([], { dateStyle: 'short', timeStyle: 'short' }); // Shorter format

  leftDiv.appendChild(titleSpan);
  leftDiv.appendChild(dateSpan);

  // Right part: three dots dropdown
  const rightDiv = document.createElement("div");
  rightDiv.classList.add("dropdown");

  const dropdownBtn = document.createElement("button");
  dropdownBtn.classList.add("btn", "btn-light", "btn-sm"); // Keep btn-sm
  dropdownBtn.type = "button";
  dropdownBtn.setAttribute("data-bs-toggle", "dropdown");
  dropdownBtn.setAttribute("data-bs-display", "static");
  dropdownBtn.setAttribute("aria-expanded", "false");
  dropdownBtn.innerHTML = `<i class="bi bi-three-dots-vertical"></i>`; // Vertical dots maybe?
  dropdownBtn.title = "Conversation options";

  const dropdownMenu = document.createElement("ul");
  dropdownMenu.classList.add("dropdown-menu", "dropdown-menu-end");

  // Add Details option
  const detailsLi = document.createElement("li");
  const detailsA = document.createElement("a");
  detailsA.classList.add("dropdown-item", "details-btn");
  detailsA.href = "#";
  detailsA.innerHTML = '<i class="bi bi-info-circle me-2"></i>Details';
  detailsLi.appendChild(detailsA);

  // Add Select option
  const selectLi = document.createElement("li");
  const selectA = document.createElement("a");
  selectA.classList.add("dropdown-item", "select-btn");
  selectA.href = "#";
  selectA.innerHTML = '<i class="bi bi-check-square me-2"></i>Select';
  selectLi.appendChild(selectA);

  const editLi = document.createElement("li");
  const editA = document.createElement("a");
  editA.classList.add("dropdown-item", "edit-btn");
  editA.href = "#";
  editA.innerHTML = '<i class="bi bi-pencil-fill me-2"></i>Edit title';
  editLi.appendChild(editA);

  const deleteLi = document.createElement("li");
  const deleteA = document.createElement("a");
  deleteA.classList.add("dropdown-item", "delete-btn", "text-danger");
  deleteA.href = "#";
  deleteA.innerHTML = '<i class="bi bi-trash-fill me-2"></i>Delete';
  deleteLi.appendChild(deleteA);

  dropdownMenu.appendChild(detailsLi);
  dropdownMenu.appendChild(selectLi);
  dropdownMenu.appendChild(editLi);
  dropdownMenu.appendChild(deleteLi);
  rightDiv.appendChild(dropdownBtn);
  rightDiv.appendChild(dropdownMenu);

  // Combine left + right in a wrapper
  const wrapper = document.createElement("div");
  wrapper.classList.add("d-flex", "justify-content-between", "align-items-center", "w-100");
  wrapper.appendChild(leftDiv);
  wrapper.appendChild(rightDiv);
  
  // Add checkbox first, then the wrapper
  convoItem.appendChild(checkbox);
  convoItem.appendChild(wrapper);

  // Event Listeners
  convoItem.addEventListener("click", (event) => {
    // Don't select if click is on checkbox, dropdown elements, or if editing
    if (event.target.closest(".dropdown, .dropdown-menu") ||
        event.target.type === "checkbox" ||
        convoItem.classList.contains('editing')) {
      return;
    }
    
    selectConversation(convo.id);
  });

  editA.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    closeDropdownMenu(dropdownBtn);
    enterEditMode(convoItem, convo, dropdownBtn, rightDiv); // Pass rightDiv
  });

  deleteA.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    closeDropdownMenu(dropdownBtn);
    deleteConversation(convo.id);
  });
  
  // Add event listener for the Select button
  selectA.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    closeDropdownMenu(dropdownBtn);
    enterSelectionMode();
  });

  return convoItem;
}

function closeDropdownMenu(dropdownBtn) {
  const dropdownInstance = bootstrap.Dropdown.getInstance(dropdownBtn);
  if (dropdownInstance) {
    dropdownInstance.hide();
  }
}

export function enterEditMode(convoItem, convo, dropdownBtn, rightDiv) {
  if (currentlyEditingId && currentlyEditingId !== convo.id) {
    showToast("Finish editing the other conversation first.", "warning");
    return;
  }
  if(convoItem.classList.contains('editing')) return; // Already editing

  currentlyEditingId = convo.id;
  convoItem.classList.add('editing'); // Add class to prevent selection

  dropdownBtn.style.display = "none"; // Hide dots button

  const titleSpan = convoItem.querySelector(".conversation-title");
  const dateSpan = convoItem.querySelector("small"); // Get date span too

  const input = document.createElement("input");
  input.type = "text";
  input.value = convo.title;
  input.classList.add("form-control", "form-control-sm", "me-1"); // Add margin
  input.style.flexGrow = '1'; // Allow input to grow

  // Create Save button
  const saveBtn = document.createElement("button");
  saveBtn.classList.add("btn", "btn-success", "btn-sm"); // Success color
  saveBtn.innerHTML = '<i class="bi bi-check-lg"></i>'; // Check icon
  saveBtn.title = "Save title";

   // Create Cancel button
  const cancelBtn = document.createElement("button");
  cancelBtn.classList.add("btn", "btn-secondary", "btn-sm", "ms-1"); // Secondary color, margin
  cancelBtn.innerHTML = '<i class="bi bi-x-lg"></i>'; // X icon
  cancelBtn.title = "Cancel edit";

  // Replace title span with input
  titleSpan.replaceWith(input);
  if (dateSpan) dateSpan.style.display = 'none'; // Hide date while editing

  // Add Save and Cancel buttons to the right div
  rightDiv.appendChild(saveBtn);
  rightDiv.appendChild(cancelBtn);

  input.focus(); // Focus the input
  input.select(); // Select existing text

  // Save handler
  saveBtn.addEventListener("click", async (e) => {
    e.stopPropagation(); // Prevent convo selection
    const newTitle = input.value.trim();
    if (!newTitle) {
      showToast("Title cannot be empty.", "warning");
      return;
    }
    saveBtn.disabled = true; // Disable while saving
    cancelBtn.disabled = true;
    saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>'; // Loading spinner

    try {
      // *** Call update API and get potentially updated convo data (including classification) ***
      const updatedConvoData = await updateConversationTitle(convo.id, newTitle);
      convo.title = updatedConvoData.title || newTitle; // Update local title
      convoItem.setAttribute('data-conversation-title', convo.title);
      // *** Update local classification data if returned from API ***
      if (updatedConvoData.classification) {
          convoItem.dataset.classifications = JSON.stringify(updatedConvoData.classification);
      }
      // *** Update chat type and group information if available ***
      if (updatedConvoData.context && updatedConvoData.context.length > 0) {
        const primaryContext = updatedConvoData.context.find(c => c.type === 'primary');
        if (primaryContext && primaryContext.scope === 'group') {
          convoItem.setAttribute("data-group-name", primaryContext.name || 'Group');
          convoItem.setAttribute("data-chat-type", "group-single-user");
        } else {
          convoItem.setAttribute("data-chat-type", "personal");
        }
      }

      exitEditMode(convoItem, convo, dropdownBtn, rightDiv, dateSpan, saveBtn, cancelBtn);

      // *** Update sidebar conversation title if sidebar is available ***
      if (window.chatSidebarConversations && window.chatSidebarConversations.updateSidebarConversationTitle) {
        window.chatSidebarConversations.updateSidebarConversationTitle(convo.id, convo.title);
      }

      // *** If this is the currently selected convo, refresh the header ***
      if (currentConversationId === convo.id) {
          selectConversation(convo.id); // Re-run selection logic to update header
      }
    } catch (err) {
      console.error(err);
      showToast("Failed to update title.", "danger");
       saveBtn.disabled = false; // Re-enable buttons on error
       cancelBtn.disabled = false;
       saveBtn.innerHTML = '<i class="bi bi-check-lg"></i>'; // Restore icon
    }
  });

   // Cancel handler
  cancelBtn.addEventListener("click", (e) => {
     e.stopPropagation(); // Prevent convo selection
     exitEditMode(convoItem, convo, dropdownBtn, rightDiv, dateSpan, saveBtn, cancelBtn);
  });

  // Also handle Enter key in input for saving
  input.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
          e.preventDefault();
          saveBtn.click(); // Trigger save button click
      }
  });
   // Handle Escape key for canceling
  input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
          cancelBtn.click(); // Trigger cancel button click
      }
  });
}

export function exitEditMode(convoItem, convo, dropdownBtn, rightDiv, dateSpan, saveBtn, cancelBtn) {
  currentlyEditingId = null;
  convoItem.classList.remove('editing');

  const input = convoItem.querySelector("input.form-control");
  if (!input) return;

  const newSpan = document.createElement("span");
  newSpan.classList.add("conversation-title", "text-truncate");
  newSpan.textContent = convo.title;
  newSpan.title = convo.title; // Add tooltip back

  input.replaceWith(newSpan); // Replace input with updated span
  if (dateSpan) dateSpan.style.display = ''; // Show date again

  if (saveBtn) saveBtn.remove(); // Remove Save button
  if (cancelBtn) cancelBtn.remove(); // Remove Cancel button

  dropdownBtn.style.display = ""; // Show dots button again
}

export async function updateConversationTitle(conversationId, newTitle) {
  const response = await fetch(`/api/conversations/${conversationId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: newTitle }),
  });
  if (!response.ok) {
    const errData = await response.json().catch(() => ({}));
    throw new Error(errData.error || "Failed to update conversation");
  }
  // *** Return the full updated conversation object if the API provides it ***
  return response.json();
}

// Add a new conversation item to the top of the list
export function addConversationToList(conversationId, title = null, classifications = []) {
  if (!conversationsList) return;

  // Deselect any currently active item visually
  const currentActive = conversationsList.querySelector(".conversation-item.active");
  if (currentActive) {
    currentActive.classList.remove("active");
  }

  // Create the new conversation object
  const convo = {
    id: conversationId,
    title: title || "New Conversation", // Default title
    last_updated: new Date().toISOString(),
    classification: classifications // Include classifications
  };

  const convoItem = createConversationItem(convo);
  convoItem.classList.add("active"); // Mark the new one as active
  conversationsList.prepend(convoItem); // Add to the top
  
  // Also reload sidebar conversations if the sidebar exists
  if (document.getElementById("sidebar-conversations-list")) {
    loadSidebarConversations();
  }
}

// Select a conversation, load messages, update UI
export async function selectConversation(conversationId) {
  currentConversationId = conversationId;

  const convoItem = document.querySelector(`.conversation-item[data-conversation-id="${conversationId}"]`);
  if (!convoItem) {
      console.warn(`Conversation item not found for ID: ${conversationId}`);
      // Handle case where item might have been deleted or list not fully loaded
      if (currentConversationTitleEl) currentConversationTitleEl.textContent = "Conversation not found";
      if (currentConversationClassificationsEl) currentConversationClassificationsEl.innerHTML = "";
      if (chatbox) chatbox.innerHTML = '<div class="text-center p-5 text-muted">Conversation not found.</div>';
      highlightSelectedConversation(null); // Deselect all visually
      toggleConversationInfoButton(false); // Hide the info button
      return;
  }

  const conversationTitle = convoItem.getAttribute("data-conversation-title") || "Conversation"; // Use stored title

  // Update Header Title
  if (currentConversationTitleEl) {
    currentConversationTitleEl.textContent = conversationTitle;
  }

  // Fetch the latest conversation metadata to get accurate chat_type
  try {
    const response = await fetch(`/api/conversations/${conversationId}/metadata`);
    if (response.ok) {
      const metadata = await response.json();
      
      console.log(`selectConversation: Fetched metadata for ${conversationId}:`, metadata);
      
      // Update conversation item with accurate chat_type from metadata
      if (metadata.chat_type) {
        convoItem.setAttribute("data-chat-type", metadata.chat_type);
        console.log(`selectConversation: Updated data-chat-type to "${metadata.chat_type}"`);
        
        // Clear any existing group name first
        convoItem.removeAttribute("data-group-name");
        
        // If it's a group chat, also update group name
        if (metadata.chat_type.startsWith('group') && metadata.context && metadata.context.length > 0) {
          const primaryContext = metadata.context.find(c => c.type === 'primary' && c.scope === 'group');
          if (primaryContext) {
            convoItem.setAttribute("data-group-name", primaryContext.name || 'Group');
            console.log(`selectConversation: Set data-group-name to "${primaryContext.name || 'Group'}"`);
          }
        } else if (metadata.chat_type.startsWith('public') && metadata.context && metadata.context.length > 0) {
          const primaryContext = metadata.context.find(c => c.type === 'primary' && c.scope === 'public');
          if (primaryContext) {
            convoItem.setAttribute("data-group-name", primaryContext.name || 'Workspace');
            console.log(`selectConversation: Set data-group-name to "${primaryContext.name || 'Workspace'}"`);
          }
        } else {
          console.log(`selectConversation: Personal conversation - cleared group name`);
        }
      } else {
        // No chat_type - determine from context
        console.log(`selectConversation: No chat_type found, determining from context`);
        // Clear any existing attributes first
        convoItem.removeAttribute("data-chat-type");
        convoItem.removeAttribute("data-group-name");
        
        if (metadata.context && metadata.context.length > 0) {
          const primaryContext = metadata.context.find(c => c.type === 'primary');
          if (primaryContext) {
            // Primary context exists - documents were used
            if (primaryContext.scope === 'group') {
              convoItem.setAttribute("data-group-name", primaryContext.name || 'Group');
              convoItem.setAttribute("data-chat-type", "group-single-user"); // Default to single-user for now
              console.log(`selectConversation: Set to group-single-user with name "${primaryContext.name || 'Group'}"`);
            } else if (primaryContext.scope === 'public') {
              convoItem.setAttribute("data-group-name", primaryContext.name || 'Workspace');
              convoItem.setAttribute("data-chat-type", "public");
              console.log(`selectConversation: Set to public with name "${primaryContext.name || 'Workspace'}"`);
            } else if (primaryContext.scope === 'personal') {
              convoItem.setAttribute("data-chat-type", "personal");
              console.log(`selectConversation: Set to personal`);
            }
          } else {
            // No primary context - this is a model-only conversation
            // Don't set data-chat-type so no badges will be shown
            console.log(`selectConversation: No primary context - model-only conversation (no badges)`);
          }
        } else {
          // No context at all - model-only conversation
          console.log(`selectConversation: No context - model-only conversation (no badges)`);
        }
      }
    }
  } catch (error) {
    console.warn('Failed to fetch conversation metadata:', error);
    // Continue with existing data
  }

  // Update Header Classifications
  if (currentConversationClassificationsEl) {
    currentConversationClassificationsEl.innerHTML = ""; // Clear previous
    
    // Use the toBoolean helper for consistent checking
    const isFeatureEnabled = toBoolean(window.enable_document_classification);
    
    // Debug line to help troubleshoot
    console.log("Classification feature enabled:", isFeatureEnabled, 
                "Raw value:", window.enable_document_classification,
                "Type:", typeof window.enable_document_classification);
                            
    if (isFeatureEnabled) {
      try {
        const classifications = convoItem.dataset.classifications || '[]';
        console.log("Raw classifications:", classifications);
        const classificationLabels = JSON.parse(classifications);
        console.log("Parsed classification labels:", classificationLabels);
        
        if (Array.isArray(classificationLabels) && classificationLabels.length > 0) {
           const allCategories = window.classification_categories || [];
           console.log("Available categories:", allCategories);

           classificationLabels.forEach(label => {
            const category = allCategories.find(cat => cat.label === label);
            const pill = document.createElement("span");
            pill.classList.add("chat-classification-badge"); // Use specific class
            pill.textContent = label; // Display the label

            if (category) {
                // Found category definition, apply color
                pill.style.backgroundColor = category.color;
                if (isColorLight(category.color)) {
                    pill.classList.add("text-dark"); // Add dark text for light backgrounds
                }
            } else {
                // Label exists but no definition found (maybe deleted in admin)
                pill.classList.add("bg-warning", "text-dark"); // Use warning style
                pill.title = `Definition for "${label}" not found`;
            }
            currentConversationClassificationsEl.appendChild(pill);
          });
        } else {
             // Optionally display "None" if no classifications
             // currentConversationClassificationsEl.innerHTML = '<span class="badge bg-secondary">None</span>';
        }
      } catch (e) {
        console.error("Error parsing classification data:", e);
        // Handle error, maybe display an error message
      }
    }
    
    // Add chat type information (now with updated data)
    addChatTypeBadges(convoItem, currentConversationClassificationsEl);
  }

  loadMessages(conversationId);
  highlightSelectedConversation(conversationId);
  
  // Show the conversation info button since we have an active conversation
  toggleConversationInfoButton(true);
  
  // Update sidebar active conversation if sidebar exists
  if (setSidebarActiveConversation) {
    setSidebarActiveConversation(conversationId);
  }

  // Clear any "edit mode" state if switching conversations
  if (currentlyEditingId && currentlyEditingId !== conversationId) {
      const editingItem = document.querySelector(`.conversation-item[data-conversation-id="${currentlyEditingId}"]`);
      if(editingItem && editingItem.classList.contains('editing')) {
          // Need original convo object and button references to properly exit edit mode
          // This might require fetching the convo data again or storing references differently
          console.warn("Need to implement cancel/exit edit mode when switching conversations.");
          // Simple visual reset for now:
          loadConversations(); // Less ideal, reloads the whole list
      }
  }
}

// Visually highlight the selected conversation in the list
export function highlightSelectedConversation(conversationId) {
  const items = document.querySelectorAll(".conversation-item");
  items.forEach(item => {
    if (item.getAttribute("data-conversation-id") === conversationId) {
      item.classList.add("active");
    } else {
      item.classList.remove("active");
    }
  });
}

// Delete a conversation
export function deleteConversation(conversationId) {
  if (!confirm("Are you sure you want to delete this conversation? This action cannot be undone.")) {
    return;
  }

  // Optionally show loading state on the item being deleted

  fetch(`/api/conversations/${conversationId}`, { method: "DELETE" })
    .then(response => {
      if (response.ok) {
        const convoItem = document.querySelector(`.conversation-item[data-conversation-id="${conversationId}"]`);
        if (convoItem) convoItem.remove();

        // If the deleted conversation was the current one, reset the chat view
        if (currentConversationId === conversationId) {
          currentConversationId = null;
          if (currentConversationTitleEl) currentConversationTitleEl.textContent = "Select or start a conversation";
          if (currentConversationClassificationsEl) currentConversationClassificationsEl.innerHTML = ""; // Clear classifications
          if (chatbox) chatbox.innerHTML = '<div class="text-center p-5 text-muted">Select a conversation to view messages.</div>'; // Reset chatbox
          highlightSelectedConversation(null); // Deselect all
          toggleConversationInfoButton(false); // Hide the info button
        }
        
        // Also reload sidebar conversations if the sidebar exists
        if (window.chatSidebarConversations && window.chatSidebarConversations.loadSidebarConversations) {
          window.chatSidebarConversations.loadSidebarConversations();
        }
        
         showToast("Conversation deleted.", "success");
      } else {
         return response.json().then(err => Promise.reject(err)); // Pass error details
      }
    })
    .catch(error => {
      console.error("Error deleting conversation:", error);
      showToast(`Error deleting conversation: ${error.error || 'Unknown error'}`, "danger");
      // Re-enable button if loading state was shown
    });
}

// Create a new conversation via API
export async function createNewConversation(callback) {
    // Disable new button? Show loading?
    if (newConversationBtn) newConversationBtn.disabled = true;
  try {
    const response = await fetch("/api/create_conversation", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      credentials: "same-origin",
    });
    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.error || "Failed to create conversation");
    }
    const data = await response.json();
    if (!data.conversation_id) {
      throw new Error("No conversation_id returned from server.");
    }

    currentConversationId = data.conversation_id;
    // Add to list (pass empty classifications for new convo)
    addConversationToList(data.conversation_id, data.title /* Use title from API if provided */, []);
    // Select the new conversation to update header and chatbox
    selectConversation(data.conversation_id);

    // Execute callback if provided (e.g., to send the first message)
    if (typeof callback === "function") {
      callback();
    }

  } catch (error) {
    console.error("Error creating conversation:", error);
    showToast(`Failed to create a new conversation: ${error.message}`, "danger");
  } finally {
      if (newConversationBtn) newConversationBtn.disabled = false;
  }
}

// Function to update the selected conversations set
function updateSelectedConversations(conversationId, isSelected) {
  if (isSelected) {
    selectedConversations.add(conversationId);
    // If at least one item is selected, clear the auto-hide timer
    if (selectionModeTimer) {
      clearTimeout(selectionModeTimer);
      selectionModeTimer = null;
    }
  } else {
    selectedConversations.delete(conversationId);
    
    // If no items are selected, start the timer to exit selection mode
    if (selectedConversations.size === 0) {
      resetSelectionModeTimer();
    }
  }
  
  // Update sidebar selection state if available
  if (window.chatSidebarConversations && window.chatSidebarConversations.updateSidebarConversationSelection) {
    window.chatSidebarConversations.updateSidebarConversationSelection(conversationId, isSelected);
  }
  
  // Update sidebar delete button if available
  if (window.chatSidebarConversations && window.chatSidebarConversations.updateSidebarDeleteButton) {
    window.chatSidebarConversations.updateSidebarDeleteButton(selectedConversations.size);
  }
  
  // Show/hide the delete button based on selection
  if (selectedConversations.size > 0) {
    deleteSelectedBtn.style.display = "block";
  } else {
    deleteSelectedBtn.style.display = "none";
  }
}

// Function to delete multiple conversations
async function deleteSelectedConversations() {
  if (selectedConversations.size === 0) return;
  
  if (!confirm(`Are you sure you want to delete ${selectedConversations.size} conversation(s)? This action cannot be undone.`)) {
    return;
  }
  
  const conversationIds = Array.from(selectedConversations);
  
  try {
    const response = await fetch('/api/delete_multiple_conversations', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ conversation_ids: conversationIds })
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Failed to delete conversations');
    }
    
    // Remove deleted conversations from the UI
    conversationIds.forEach(id => {
      const convoItem = document.querySelector(`.conversation-item[data-conversation-id="${id}"]`);
      if (convoItem) convoItem.remove();
      
      // If the deleted conversation was the current one, reset the chat view
      if (currentConversationId === id) {
        currentConversationId = null;
        if (currentConversationTitleEl) currentConversationTitleEl.textContent = "Select or start a conversation";
        if (currentConversationClassificationsEl) currentConversationClassificationsEl.innerHTML = "";
        if (chatbox) chatbox.innerHTML = '<div class="text-center p-5 text-muted">Select a conversation to view messages.</div>';
        highlightSelectedConversation(null);
        toggleConversationInfoButton(false); // Hide the info button
      }
    });
    
    // Clear the selected conversations set and exit selection mode
    selectedConversations.clear();
    deleteSelectedBtn.style.display = "none";
    exitSelectionMode();
    
    // Also reload sidebar conversations if the sidebar exists
    if (window.chatSidebarConversations && window.chatSidebarConversations.loadSidebarConversations) {
      window.chatSidebarConversations.loadSidebarConversations();
    }
    
    showToast(`${conversationIds.length} conversation(s) deleted.`, "success");
  } catch (error) {
    console.error("Error deleting conversations:", error);
    showToast(`Error deleting conversations: ${error.message}`, "danger");
  }
}

// --- Event Listeners ---
if (newConversationBtn) {
  newConversationBtn.addEventListener("click", () => {
    // If already editing, ask to finish first
    if(currentlyEditingId) {
        showToast("Please save or cancel the title edit first.", "warning");
        return;
    }
    createNewConversation();
  });
}

if (deleteSelectedBtn) {
  deleteSelectedBtn.addEventListener("click", deleteSelectedConversations);
}

// Expose functions globally for sidebar integration
window.chatConversations = {
  selectConversation,
  loadConversations,
  highlightSelectedConversation,
  addConversationToList,
  deleteConversation,
  toggleConversationSelection,
  deleteSelectedConversations,
  exitSelectionMode,
  isSelectionModeActive: () => selectionModeActive,
  getSelectedConversations: () => Array.from(selectedConversations),
  getCurrentConversationId: () => currentConversationId,
  updateConversationHeader: (conversationId, newTitle) => {
    // Update header if this is the currently active conversation
    if (currentConversationId === conversationId) {
      if (currentConversationTitleEl) {
        currentConversationTitleEl.textContent = newTitle;
      }
    }
  },
  editConversationTitle: (conversationId, currentTitle) => {
    // First try to find the conversation in the main list
    const convoItem = document.querySelector(`.conversation-item[data-conversation-id="${conversationId}"]`);
    if (convoItem) {
      const convo = { id: conversationId, title: currentTitle };
      const dropdownBtn = convoItem.querySelector('.btn[data-bs-toggle="dropdown"]');
      const rightDiv = convoItem.querySelector('.dropdown').parentElement;
      enterEditMode(convoItem, convo, dropdownBtn, rightDiv);
    } else {
      // If not found in main list, handle it as a simple title edit via API
      editConversationTitleSimple(conversationId, currentTitle);
    }
  }
};

// Simple edit function for conversations not in the main list (e.g., from sidebar)
async function editConversationTitleSimple(conversationId, currentTitle) {
  const newTitle = prompt("Enter new conversation title:", currentTitle);
  if (newTitle === null || newTitle.trim() === "") {
    return; // User cancelled or entered empty title
  }
  
  if (newTitle.trim() === currentTitle.trim()) {
    return; // No change
  }
  
  try {
    const updatedConvoData = await updateConversationTitle(conversationId, newTitle.trim());
    
    // Update the sidebar conversations list
    if (window.chatSidebarConversations && window.chatSidebarConversations.loadSidebarConversations) {
      window.chatSidebarConversations.loadSidebarConversations();
    }
    
    // Update the main conversations list if it exists
    if (conversationsList) {
      loadConversations();
    }
    
    // If this is the currently selected conversation, update the header
    if (currentConversationId === conversationId) {
      selectConversation(conversationId);
    }
    
    showToast("Conversation title updated.", "success");
  } catch (error) {
    console.error("Error updating conversation title:", error);
    showToast(`Failed to update title: ${error.message}`, "danger");
  }
}

// Function to toggle conversation selection (called from sidebar)
export function toggleConversationSelection(conversationId) {
  enterSelectionMode();
  
  // Find the checkbox for this conversation and toggle it
  const checkbox = document.querySelector(`.conversation-checkbox[data-conversation-id="${conversationId}"]`);
  if (checkbox) {
    checkbox.checked = !checkbox.checked;
    updateSelectedConversations(conversationId, checkbox.checked);
  }
}

/**
 * Add chat type badges based on the primary context
 * Only shows badges when there's a primary context (documents were used)
 * Does not show badges for Model-only conversations
 * @param {HTMLElement} convoItem - The conversation list item element
 * @param {HTMLElement} classificationsEl - The classifications container element
 */
function addChatTypeBadges(convoItem, classificationsEl) {
  // Get chat type and group information from data attributes
  const chatType = convoItem.getAttribute("data-chat-type");
  const groupName = convoItem.getAttribute("data-group-name");
  
  // Debug logging
  console.log(`addChatTypeBadges: chatType="${chatType}", groupName="${groupName}"`);
  
  // Only show badges if there's a valid chat type (meaning documents were used for primary context)
  // Don't show badges for Model-only conversations
  if (chatType === 'personal') {
    // Personal workspace was used
    const personalBadge = document.createElement("span");
    personalBadge.classList.add("badge", "bg-primary");
    personalBadge.textContent = "personal";
    
    // Add some spacing between classification badges and chat type badges
    if (classificationsEl.children.length > 0) {
      const spacer = document.createElement("span");
      spacer.innerHTML = "&nbsp;&nbsp;";
      classificationsEl.appendChild(spacer);
    }
    
    classificationsEl.appendChild(personalBadge);
  } else if (chatType && chatType.startsWith('group')) {
    // Group workspace was used
    const groupBadge = document.createElement("span");
    groupBadge.classList.add("badge", "bg-info", "me-1");
    groupBadge.textContent = groupName ? `group - ${groupName}` : 'group';
    
    const userTypeBadge = document.createElement("span");
    userTypeBadge.classList.add("badge", "bg-secondary");
    userTypeBadge.textContent = chatType.includes('multi-user') ? 'multi-user' : 'single-user';
    
    // Add some spacing between classification badges and chat type badges
    if (classificationsEl.children.length > 0) {
      const spacer = document.createElement("span");
      spacer.innerHTML = "&nbsp;&nbsp;";
      classificationsEl.appendChild(spacer);
    }
    
    classificationsEl.appendChild(groupBadge);
    classificationsEl.appendChild(userTypeBadge);
  } else if (chatType && chatType.startsWith('public')) {
    // Public workspace was used
    const publicBadge = document.createElement("span");
    publicBadge.classList.add("badge", "bg-success");
    publicBadge.textContent = groupName ? `public - ${groupName}` : 'public';
    
    // Add some spacing between classification badges and chat type badges
    if (classificationsEl.children.length > 0) {
      const spacer = document.createElement("span");
      spacer.innerHTML = "&nbsp;&nbsp;";
      classificationsEl.appendChild(spacer);
    }
    
    classificationsEl.appendChild(publicBadge);
  } else {
    // If chatType is unknown/null or model-only, don't add any workspace badges
    console.log(`addChatTypeBadges: No badges added for chatType="${chatType}" (likely model-only conversation)`);
  }
}