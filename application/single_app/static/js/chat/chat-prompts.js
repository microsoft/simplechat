// chat-prompts.js

import { userInput} from "./chat-messages.js";
import { updateSendButtonVisibility } from "./chat-messages.js";
import { docScopeSelect } from "./chat-documents.js";

const promptSelectionContainer = document.getElementById("prompt-selection-container");
export const promptSelect = document.getElementById("prompt-select"); // Keep export if needed elsewhere
const searchPromptsBtn = document.getElementById("search-prompts-btn");

export function loadUserPrompts() {
  return fetch("/api/prompts")
    .then(r => r.json())
    .then(data => {
      if (data.prompts) {
        userPrompts = data.prompts;
      }
    })
    .catch(err => console.error("Error loading user prompts:", err));
}

export function loadGroupPrompts() {
  return fetch("/api/group_prompts")
    .then(r => {
      if (!r.ok) {
        // Handle 400 errors gracefully (e.g., no active group selected)
        if (r.status === 400) {
          console.log("No active group selected for group prompts");
          groupPrompts = [];
          return { prompts: [] }; // Return empty result to avoid further errors
        }
        throw new Error(`HTTP ${r.status}: ${r.statusText}`);
      }
      return r.json();
    })
    .then(data => {
      if (data.prompts) {
        groupPrompts = data.prompts;
      }
    })
    .catch(err => console.error("Error loading group prompts:", err));
}

export function loadPublicPrompts() {
  return fetch("/api/public_prompts")
    .then(r => {
      if (!r.ok) {
        // Handle 400 errors gracefully
        if (r.status === 400) {
          console.log("No public prompts available");
          publicPrompts = [];
          return { prompts: [] }; // Return empty result to avoid further errors
        }
        throw new Error(`HTTP ${r.status}: ${r.statusText}`);
      }
      return r.json();
    })
    .then(data => {
      if (data.prompts) {
        publicPrompts = data.prompts;
      }
    })
    .catch(err => console.error("Error loading public prompts:", err));
}

export function populatePromptSelectScope() {
  if (!promptSelect) return;

  console.log("Populating prompt dropdown with scope:", docScopeSelect?.value || "all");
  console.log("User prompts:", userPrompts.length);
  console.log("Group prompts:", groupPrompts.length);
  console.log("Public prompts:", publicPrompts.length);

  const previousValue = promptSelect.value; // Store previous selection if needed
  promptSelect.innerHTML = "";
  
  const defaultOpt = document.createElement("option");
  defaultOpt.value = "";
  defaultOpt.textContent = "Select a Prompt...";
  promptSelect.appendChild(defaultOpt);

  const scopeVal = docScopeSelect?.value || "all";
  let finalPrompts = [];

  if (scopeVal === "all") {
    const pPrompts = userPrompts.map((p) => ({...p, scope: "Personal"}));
    const gPrompts = groupPrompts.map((p) => ({...p, scope: "Group"}));
    const pubPrompts = publicPrompts.map((p) => ({...p, scope: "Public"}));
    finalPrompts = pPrompts.concat(gPrompts).concat(pubPrompts);
  } else if (scopeVal === "personal") {
    finalPrompts = userPrompts.map((p) => ({...p, scope: "Personal"}));
  } else if (scopeVal === "group") {
    finalPrompts = groupPrompts.map((p) => ({...p, scope: "Group"}));
  } else if (scopeVal === "public") {
    finalPrompts = publicPrompts.map((p) => ({...p, scope: "Public"}));
  }

  // Add prompt options
  finalPrompts.forEach((promptObj) => {
    const opt = document.createElement("option");
    opt.value = promptObj.id;
    opt.textContent = `[${promptObj.scope}] ${promptObj.name}`;
    opt.dataset.promptContent = promptObj.content;
    promptSelect.appendChild(opt);
  });

  // Try to restore previous selection if it still exists, otherwise default to "Select a Prompt..."
  if (finalPrompts.some(prompt => prompt.id === previousValue)) {
    promptSelect.value = previousValue;
  } else {
    promptSelect.value = ""; // Default to "Select a Prompt..."
  }
}

// Keep the old function for backward compatibility, but have it call the scope-aware version
export function populatePromptSelect() {
  populatePromptSelectScope();
}

export function loadAllPrompts() {
  return Promise.all([loadUserPrompts(), loadGroupPrompts(), loadPublicPrompts()])
    .then(() => {
      console.log("All prompts loaded, populating scope-based select...");
      populatePromptSelectScope();
    })
    .catch(err => console.error("Error loading all prompts:", err));
}

export function initializePromptInteractions() {
  console.log("Attempting to initialize prompt interactions..."); // Debug log
  
  // Check for elements *inside* the function that runs later
  if (searchPromptsBtn && promptSelectionContainer && userInput) {
      console.log("Elements found, adding prompt button listener."); // Debug log
      
      searchPromptsBtn.addEventListener("click", function() {
          const isActive = this.classList.toggle("active");

          if (isActive) {
              promptSelectionContainer.style.display = "block";
              // Load all prompts and populate with scope filtering
              loadAllPrompts();
              userInput.classList.add("with-prompt-active");
              userInput.focus();
              // Update send button visibility when prompts are shown
              updateSendButtonVisibility();
          } else {
              promptSelectionContainer.style.display = "none";
              if (promptSelect) {
                  promptSelect.selectedIndex = 0;
              }
              userInput.classList.remove("with-prompt-active");
              userInput.focus();
              // Update send button visibility when prompts are hidden
              updateSendButtonVisibility();
          }
      });
      
      // Add event listener for scope changes to update prompts
      if (docScopeSelect) {
          // Add event listener that will repopulate prompts when scope changes
          docScopeSelect.addEventListener("change", function() {
              // Only repopulate if prompts are currently visible
              if (promptSelectionContainer && promptSelectionContainer.style.display === "block") {
                  console.log("Scope changed, repopulating prompts...");
                  populatePromptSelectScope();
              }
          });
      }
      
  } else {
      // Log detailed errors if elements are missing WHEN this function runs
      if (!searchPromptsBtn) console.error("Prompt Init Error: search-prompts-btn not found.");
      if (!promptSelectionContainer) console.error("Prompt Init Error: prompt-selection-container not found.");
      // This check is crucial: is userInput null/undefined when this function executes?
      if (!userInput) console.error("Prompt Init Error: userInput (imported from chat-messages) is not available.");
  }
}