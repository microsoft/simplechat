// chat-conversations.js

import { showToast } from "./chat-toast.js";
import { loadMessages } from "./chat-messages.js";
import { isColorLight } from "./chat-utils.js"; // Assuming you move isColorLight here

const newConversationBtn = document.getElementById("new-conversation-btn");
const conversationsList = document.getElementById("conversations-list");
const currentConversationTitleEl = document.getElementById("current-conversation-title");
const currentConversationClassificationsEl = document.getElementById("current-conversation-classifications");
const chatbox = document.getElementById("chatbox");

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
      // Optionally, select the first conversation or highlight the active one if ID is known
    })
    .catch(error => {
      console.error("Error loading conversations:", error);
      conversationsList.innerHTML = `<div class="text-center p-3 text-danger">Error loading conversations: ${error.error || 'Unknown error'}</div>`;
    });
}

export function createConversationItem(convo) {
  const convoItem = document.createElement("a"); // Use <a> for better semantics if appropriate
  convoItem.href = "#"; // Prevent default link behavior later
  convoItem.classList.add("list-group-item", "list-group-item-action", "conversation-item"); // Use action class
  convoItem.setAttribute("data-conversation-id", convo.id);
  convoItem.setAttribute("data-conversation-title", convo.title); // Store title too

  // *** Store classification data as stringified JSON ***
  convoItem.dataset.classifications = JSON.stringify(convo.classification || []);

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

  dropdownMenu.appendChild(editLi);
  dropdownMenu.appendChild(deleteLi);
  rightDiv.appendChild(dropdownBtn);
  rightDiv.appendChild(dropdownMenu);

  // Combine left + right in a wrapper
  const wrapper = document.createElement("div");
  wrapper.classList.add("d-flex", "justify-content-between", "align-items-center", "w-100");
  wrapper.appendChild(leftDiv);
  wrapper.appendChild(rightDiv);
  convoItem.appendChild(wrapper);

  // Event Listeners
  convoItem.addEventListener("click", (event) => {
    event.preventDefault(); // Prevent default <a> behavior
    if (event.target.closest(".dropdown, .dropdown-menu")) {
      return; // Don't select if click is on dropdown elements
    }
    // Don't select if editing this item
    if(convoItem.classList.contains('editing')) return;

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

      // *** Update local classification data if returned from API ***
      if (updatedConvoData.classification) {
          convoItem.dataset.classifications = JSON.stringify(updatedConvoData.classification);
      }

      exitEditMode(convoItem, convo, dropdownBtn, rightDiv, dateSpan, saveBtn, cancelBtn);

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
}

// Select a conversation, load messages, update UI
export function selectConversation(conversationId) {
  currentConversationId = conversationId;

  const convoItem = document.querySelector(`.conversation-item[data-conversation-id="${conversationId}"]`);
  if (!convoItem) {
      console.warn(`Conversation item not found for ID: ${conversationId}`);
      // Handle case where item might have been deleted or list not fully loaded
      if (currentConversationTitleEl) currentConversationTitleEl.textContent = "Conversation not found";
      if (currentConversationClassificationsEl) currentConversationClassificationsEl.innerHTML = "";
      if (chatbox) chatbox.innerHTML = '<div class="text-center p-5 text-muted">Conversation not found.</div>';
      highlightSelectedConversation(null); // Deselect all visually
      return;
  }

  const conversationTitle = convoItem.getAttribute("data-conversation-title") || "Conversation"; // Use stored title

  // Update Header Title
  if (currentConversationTitleEl) {
    currentConversationTitleEl.textContent = conversationTitle;
  }

  // Update Header Classifications
  if (currentConversationClassificationsEl) {
    currentConversationClassificationsEl.innerHTML = ""; // Clear previous
    if (window.enable_document_classification) {
      try {
        const classificationLabels = JSON.parse(convoItem.dataset.classifications || '[]');
        if (Array.isArray(classificationLabels) && classificationLabels.length > 0) {
           const allCategories = window.classification_categories || [];

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
  }

  loadMessages(conversationId);
  highlightSelectedConversation(conversationId);

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
      headers: { "Content-Type": "application/json" },
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


// --- Event Listener ---
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