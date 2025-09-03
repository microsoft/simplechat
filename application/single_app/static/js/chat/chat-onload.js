// chat-onload.js

import { loadConversations } from "./chat-conversations.js";
// Import handleDocumentSelectChange
import { loadAllDocs, populateDocumentSelectScope, handleDocumentSelectChange } from "./chat-documents.js";
import { getUrlParameter } from "./chat-utils.js"; // Assuming getUrlParameter is in chat-utils.js now
import { loadUserPrompts, loadGroupPrompts, initializePromptInteractions } from "./chat-prompts.js";
import { loadUserSettings } from "./chat-layout.js";
import { showToast } from "./chat-toast.js";
import { initConversationInfoButton } from "./chat-conversation-info-button.js";

window.addEventListener('DOMContentLoaded', () => {
  console.log("DOM Content Loaded. Starting initializations."); // Log start

  loadConversations(); // Load conversations immediately

  // Initialize the conversation info button
  initConversationInfoButton();

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
  Promise.all([
      loadAllDocs(),
      loadUserPrompts(),
      loadGroupPrompts(),
      loadUserSettings()
  ])
  .then(([docsResult, userPromptsResult, groupPromptsResult, userSettings]) => {
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
      const workspaceParam = getUrlParameter("workspace") || "";
      const openSearchParam = getUrlParameter("openSearch") === "1";
      const scopeParam = getUrlParameter("scope") || "";
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
                  localDocScopeSel.value = "public";
                  
                  // Populate documents for public scope
                  populateDocumentSelectScope();
                  
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
              localDocScopeSel.value = localDocScopeParam;
          }
          populateDocumentSelectScope(); // Populate based on scope (might be default or from URL)

          if (localDocumentIdParam) {
               // Wait a tiny moment for populateDocumentSelectScope potentially async operations
               // This delay is necessary to ensure the document options are fully populated
               setTimeout(() => {
                   if ([...localDocSelectEl.options].some(option => option.value === localDocumentIdParam)) {
                       localDocSelectEl.value = localDocumentIdParam;
                   } else {
                       console.warn(`Document ID "${localDocumentIdParam}" not found for scope "${localDocScopeSel.value}".`);
                   }
                   // Ensure classification updates after setting document
                   handleDocumentSelectChange();
               }, 100); // Small delay to ensure options are populated
          } else {
              // If no specific doc ID, still might need to trigger change if scope changed
               handleDocumentSelectChange();
          }
      } else if (openSearchParam && scopeParam === "public" && localSearchDocsBtn && localDocScopeSel && searchDocumentsContainer) {
          // Handle openSearch=1&scope=public from public directory chat button
          localSearchDocsBtn.classList.add("active");
          searchDocumentsContainer.style.display = "block";
          localDocScopeSel.value = "public";
          populateDocumentSelectScope();
          handleDocumentSelectChange();
      } else {
          // If not loading from URL params, maybe still populate default scope?
          populateDocumentSelectScope();
      }
      // --- End Document-related UI ---


      // --- Call the prompt initialization function HERE ---
      console.log("Calling initializePromptInteractions...");
      initializePromptInteractions();


      console.log("All initializations complete."); // Log end

  })
  .catch((err) => {
      console.error("Error during initial data loading or setup:", err);
      // Maybe try to initialize prompts even if doc loading fails? Depends on requirements.
      // console.log("Attempting to initialize prompts despite data load error...");
      // initializePromptInteractions();
  });
});
