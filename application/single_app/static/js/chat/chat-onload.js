// chat-onload.js

import { loadConversations, selectConversation, ensureConversationPresent } from "./chat-conversations.js";
// Import handleDocumentSelectChange
import { loadAllDocs, populateDocumentSelectScope, handleDocumentSelectChange, loadTagsForScope, filterDocumentsBySelectedTags, setScopeFromUrlParam } from "./chat-documents.js";
import { getUrlParameter } from "./chat-utils.js"; // Assuming getUrlParameter is in chat-utils.js now
import { loadUserPrompts, loadGroupPrompts, initializePromptInteractions } from "./chat-prompts.js";
import { loadUserSettings } from "./chat-layout.js";
import { showToast } from "./chat-toast.js";
import { initConversationInfoButton } from "./chat-conversation-info-button.js";
import { initializeStreamingToggle } from "./chat-streaming.js";
import { initializeReasoningToggle } from "./chat-reasoning.js";
import { initializeSpeechInput } from "./chat-speech-input.js";

window.addEventListener('DOMContentLoaded', async () => {
  console.log("DOM Content Loaded. Starting initializations."); // Log start

    // Load conversations immediately (awaitable so deep-link can run after)
    await loadConversations();

  // Initialize the conversation info button
  initConversationInfoButton();
  
  // Initialize streaming toggle
  initializeStreamingToggle();
  
  // Initialize reasoning toggle
  initializeReasoningToggle();
  
  // Initialize speech input
  try {
    initializeSpeechInput();
  } catch (error) {
    console.warn('Speech input initialization failed:', error);
  }

  // Grab references to the relevant elements
  const userInput = document.getElementById("user-input");
  const newConversationBtn = document.getElementById("new-conversation-btn");
  const promptsBtn = document.getElementById("search-prompts-btn");
  const fileBtn = document.getElementById("choose-file-btn");

  // 1) Message Input Focus => Create conversation if none
  if (userInput && newConversationBtn) {
    userInput.addEventListener("focus", () => {
      if (!currentConversationId) {
        newConversationBtn.click();
      }
    });
  }

  // 2) Prompts Button Click => Create conversation if none
  if (promptsBtn && newConversationBtn) {
    promptsBtn.addEventListener("click", (event) => {
      if (!currentConversationId) {
        // Optionally prevent the default action if it does something immediately
        // event.preventDefault(); 
        newConversationBtn.click();

        // (Optional) If you need the prompt UI to appear *after* the conversation is created,
        // you can open the prompt UI programmatically in a small setTimeout or callback.
        // setTimeout(() => openPromptUI(), 100);
      }
    });
  }

  // 3) File Upload Button Click => Create conversation if none
  if (fileBtn && newConversationBtn) {
    fileBtn.addEventListener("click", (event) => {
      if (!currentConversationId) {
        // event.preventDefault(); // If file dialog should only open once conversation is created
        newConversationBtn.click();

        // (Optional) If you want the file dialog to appear *after* the conversation is created,
        // do it in a short setTimeout or callback:
        // setTimeout(() => fileBtn.click(), 100);
      }
    });
  }

  // Load documents, prompts, and user settings
  try {
      const [docsResult, userPromptsResult, groupPromptsResult, userSettings] = await Promise.all([
          loadAllDocs(),
          loadUserPrompts(),
          loadGroupPrompts(),
          loadUserSettings()
      ]);
      console.log("Initial data (Docs, Prompts, Settings) loaded successfully."); // Log success
      
      // Set the preferred model if available
      if (userSettings && userSettings.preferredModelDeployment) {
          const modelSelect = document.getElementById("model-select");
          if (modelSelect) {
              console.log(`Setting preferred model: ${userSettings.preferredModelDeployment}`);
              modelSelect.value = userSettings.preferredModelDeployment;
          }
      }

      // --- Initialize Document-related UI ---
      // This part handles URL params for documents - KEEP IT
      const localSearchDocsParam = getUrlParameter("search_documents") === "true";
      const localDocScopeParam = getUrlParameter("doc_scope") || "";
      const localDocumentIdParam = getUrlParameter("document_id") || "";
      const localDocumentIdsParam = getUrlParameter("document_ids") || "";
      const tagsParam = getUrlParameter("tags") || "";
      const workspaceParam = getUrlParameter("workspace") || "";
      const openSearchParam = getUrlParameter("openSearch") === "1";
      const scopeParam = getUrlParameter("scope") || "";
      const groupIdParam = getUrlParameter("group_id") || "";
      const workspaceIdParam = getUrlParameter("workspace_id") || "";
      const localSearchDocsBtn = document.getElementById("search-documents-btn");
      const localDocScopeSel = document.getElementById("doc-scope-select");
      const localDocSelectEl = document.getElementById("document-select");
      const searchDocumentsContainer = document.getElementById("search-documents-container");

      // Handle workspace parameter from public directory
      if (workspaceParam && localSearchDocsBtn && localDocScopeSel && localDocSelectEl && searchDocumentsContainer) {
          console.log(`Handling workspace parameter: ${workspaceParam}`);
          
          // Set the active public workspace
          fetch('/api/public_workspaces/setActive', {
              method: 'PATCH',
              headers: {
                  'Content-Type': 'application/json',
              },
              body: JSON.stringify({
                  workspaceId: workspaceParam
              })
          })
          .then(response => response.json())
          .then(data => {
              if (data.message) {
                  console.log('Active public workspace set successfully');
                  
                  // Auto-open search documents section
                  localSearchDocsBtn.classList.add("active");
                  searchDocumentsContainer.style.display = "block";
                  
                  // Set scope to public
                  setScopeFromUrlParam("public", { workspaceId: workspaceParam });

                  // Populate documents for public scope
                  populateDocumentSelectScope();
                  loadTagsForScope();

                  // Trigger change to update UI
                  handleDocumentSelectChange();
                  
                  showToast('Public workspace activated for chat', 'success');
              } else {
                  console.error('Failed to set active public workspace:', data.error || data.message);
                  showToast('Failed to activate public workspace', 'error');
                  // Fall back to normal document handling
                  populateDocumentSelectScope();
              }
          })
          .catch(error => {
              console.error('Error setting active public workspace:', error);
              showToast('Error activating public workspace', 'error');
              // Fall back to normal document handling
              populateDocumentSelectScope();
          });
      } else if (localSearchDocsParam && localSearchDocsBtn && localDocScopeSel && localDocSelectEl && searchDocumentsContainer) {
          console.log("Handling document URL parameters."); // Log
          localSearchDocsBtn.classList.add("active");
          searchDocumentsContainer.style.display = "block";
          if (localDocScopeParam) {
              setScopeFromUrlParam(localDocScopeParam, { groupId: groupIdParam, workspaceId: workspaceIdParam });
          }
          populateDocumentSelectScope(); // Populate based on scope (might be default or from URL)

          // Pre-select tags from URL parameter
          if (tagsParam) {
              await loadTagsForScope();
              const chatTagsFilter = document.getElementById("chat-tags-filter");
              const tagsDropdownItems = document.getElementById("tags-dropdown-items");
              const tagsDropdownButton = document.getElementById("tags-dropdown-button");
              if (chatTagsFilter) {
                  const tagValues = tagsParam.split(",").map(t => t.trim());
                  // Select matching options in hidden select
                  Array.from(chatTagsFilter.options).forEach(opt => {
                      if (tagValues.includes(opt.value)) {
                          opt.selected = true;
                      }
                  });
                  // Also check matching checkboxes in custom dropdown
                  if (tagsDropdownItems) {
                      tagsDropdownItems.querySelectorAll('.dropdown-item').forEach(item => {
                          const tagVal = item.getAttribute('data-tag-value');
                          const cb = item.querySelector('.tag-checkbox');
                          if (cb && tagVal && tagValues.includes(tagVal)) {
                              cb.checked = true;
                          }
                      });
                  }
                  // Update button text
                  if (tagsDropdownButton) {
                      const textEl = tagsDropdownButton.querySelector('.selected-tags-text');
                      if (textEl) {
                          if (tagValues.length === 1) {
                              textEl.textContent = tagValues[0];
                          } else {
                              textEl.textContent = `${tagValues.length} tags selected`;
                          }
                      }
                  }
                  filterDocumentsBySelectedTags();
              }
          } else {
              // Load tags for current scope even without URL tag param
              await loadTagsForScope();
          }

          // Pre-select documents from URL parameters
          const docIdsToSelect = localDocumentIdsParam
              ? localDocumentIdsParam.split(",").map(id => id.trim()).filter(Boolean)
              : localDocumentIdParam
                  ? [localDocumentIdParam]
                  : [];

          if (docIdsToSelect.length > 0) {
               // Small delay to ensure document options are fully populated
               setTimeout(() => {
                   const docDropdownItems = document.getElementById("document-dropdown-items");
                   const docDropdownButton = document.getElementById("document-dropdown-button");

                   // Check matching checkboxes in custom dropdown
                   if (docDropdownItems) {
                       docDropdownItems.querySelectorAll('.dropdown-item').forEach(item => {
                           const docId = item.getAttribute('data-document-id');
                           const cb = item.querySelector('.doc-checkbox');
                           if (cb && docId && docIdsToSelect.includes(docId)) {
                               cb.checked = true;
                           }
                       });
                   }

                   // Select matching options in hidden select
                   Array.from(localDocSelectEl.options).forEach(opt => {
                       if (docIdsToSelect.includes(opt.value)) {
                           opt.selected = true;
                       }
                   });

                   // Update dropdown button text
                   if (docDropdownButton) {
                       const textEl = docDropdownButton.querySelector('.selected-document-text');
                       if (textEl) {
                           if (docIdsToSelect.length === 1) {
                               // Find the label from the dropdown item
                               const matchItem = docDropdownItems
                                   ? docDropdownItems.querySelector(`.dropdown-item[data-document-id="${docIdsToSelect[0]}"] span`)
                                   : null;
                               textEl.textContent = matchItem ? matchItem.textContent : "1 document selected";
                           } else {
                               textEl.textContent = `${docIdsToSelect.length} documents selected`;
                           }
                       }
                   }

                   handleDocumentSelectChange();
               }, 100);
          } else {
              // If no specific doc IDs, still might need to trigger change if scope changed
               handleDocumentSelectChange();
          }
      } else if (openSearchParam && scopeParam === "public" && localSearchDocsBtn && localDocScopeSel && searchDocumentsContainer) {
          // Handle openSearch=1&scope=public from public directory chat button
          localSearchDocsBtn.classList.add("active");
          searchDocumentsContainer.style.display = "block";
          setScopeFromUrlParam("public");
          populateDocumentSelectScope();
          loadTagsForScope();
          handleDocumentSelectChange();
      } else {
          // If not loading from URL params, maybe still populate default scope?
          populateDocumentSelectScope();
      }
      // --- End Document-related UI ---


      // --- Call the prompt initialization function HERE ---
      console.log("Calling initializePromptInteractions...");
      initializePromptInteractions();


      // Deep-link: conversationId query param
      const conversationId = getUrlParameter("conversationId") || getUrlParameter("conversation_id");
      if (conversationId) {
          try {
              await ensureConversationPresent(conversationId);
              await selectConversation(conversationId);
          } catch (err) {
              console.error('Failed to load conversation from URL param:', err);
              showToast('Could not open that conversation.', 'danger');
          }
      }

      console.log("All initializations complete."); // Log end

  } catch (err) {
      console.error("Error during initial data loading or setup:", err);
      // Maybe try to initialize prompts even if doc loading fails? Depends on requirements.
      // console.log("Attempting to initialize prompts despite data load error...");
      // initializePromptInteractions();
  }
});
