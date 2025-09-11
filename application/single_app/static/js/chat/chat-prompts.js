// chat-prompts.js

import { userInput} from "./chat-messages.js";
import { updateSendButtonVisibility } from "./chat-messages.js";

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

export function populatePromptSelect() {
  if (!promptSelect) return;

  promptSelect.innerHTML = "";
  const defaultOpt = document.createElement("option");
  defaultOpt.value = "";
  defaultOpt.textContent = "Select a Prompt...";
  promptSelect.appendChild(defaultOpt);

  const combined = [...userPrompts.map(p => ({...p, scope: "User"})),
                    ...groupPrompts.map(p => ({...p, scope: "Group"}))];
  
  // combined.sort((a, b) => a.name.localeCompare(b.name)); 

  combined.forEach(promptObj => {
    const opt = document.createElement("option");
    opt.value = promptObj.id;
    opt.textContent = `[${promptObj.scope}] ${promptObj.name}`;
    opt.dataset.promptContent = promptObj.content;
    promptSelect.appendChild(opt);
  });
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
              populatePromptSelect();
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
  } else {
      // Log detailed errors if elements are missing WHEN this function runs
      if (!searchPromptsBtn) console.error("Prompt Init Error: search-prompts-btn not found.");
      if (!promptSelectionContainer) console.error("Prompt Init Error: prompt-selection-container not found.");
      // This check is crucial: is userInput null/undefined when this function executes?
      if (!userInput) console.error("Prompt Init Error: userInput (imported from chat-messages) is not available.");
  }
}