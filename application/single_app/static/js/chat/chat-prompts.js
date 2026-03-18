// chat-prompts.js

import { userInput } from "./chat-messages.js";
import { updateSendButtonVisibility } from "./chat-messages.js";
import { docScopeSelect, getEffectiveScopes } from "./chat-documents.js";
import { createSearchableSingleSelect } from "./chat-searchable-select.js";

const promptSelectionContainer = document.getElementById("prompt-selection-container");
export const promptSelect = document.getElementById("prompt-select"); // Keep export if needed elsewhere
const searchPromptsBtn = document.getElementById("search-prompts-btn");
const promptDropdown = document.getElementById("prompt-dropdown");
const promptDropdownButton = document.getElementById("prompt-dropdown-button");
const promptDropdownMenu = document.getElementById("prompt-dropdown-menu");
const promptDropdownText = promptDropdownButton
    ? promptDropdownButton.querySelector(".chat-searchable-select-text")
    : null;
const promptDropdownItems = document.getElementById("prompt-dropdown-items");
const promptSearchInput = document.getElementById("prompt-search-input");

const promptPageSize = 100;

let promptSelectorController = null;
let loadAllPromptsPromise = null;

function initializePromptSelector() {
    if (promptSelectorController || !promptSelect) {
        return promptSelectorController;
    }

    promptSelectorController = createSearchableSingleSelect({
        selectEl: promptSelect,
        dropdownEl: promptDropdown,
        buttonEl: promptDropdownButton,
        buttonTextEl: promptDropdownText,
        menuEl: promptDropdownMenu,
        searchInputEl: promptSearchInput,
        itemsContainerEl: promptDropdownItems,
        placeholderText: "Select a Prompt...",
        emptyMessage: "No prompts available",
        emptySearchMessage: "No matching prompts found",
    });

    return promptSelectorController;
}

async function fetchAllPromptPages(endpoint, emptyStatuses = []) {
    const prompts = [];
    let page = 1;
    let totalCount = null;

    while (true) {
        const params = new URLSearchParams({
            page: String(page),
            page_size: String(promptPageSize)
        });
        const response = await fetch(`${endpoint}?${params.toString()}`);

        if (!response.ok) {
            if (emptyStatuses.includes(response.status)) {
                return [];
            }

            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        const pagePrompts = Array.isArray(data.prompts) ? data.prompts : [];
        prompts.push(...pagePrompts);

        if (totalCount === null) {
            totalCount = Number(data.total_count) || pagePrompts.length;
        }

        if (!pagePrompts.length || prompts.length >= totalCount || pagePrompts.length < promptPageSize) {
            break;
        }

        page += 1;
    }

    return prompts;
}

export function loadUserPrompts() {
    return fetchAllPromptPages("/api/prompts")
        .then(prompts => {
            userPrompts = prompts;
            return prompts;
        })
        .catch(err => {
            console.error("Error loading user prompts:", err);
            userPrompts = [];
            return [];
        });
}

export function loadGroupPrompts() {
    return fetchAllPromptPages("/api/group_prompts", [400])
        .then(prompts => {
            groupPrompts = prompts;
            return prompts;
        })
        .catch(err => {
            console.error("Error loading group prompts:", err);
            groupPrompts = [];
            return [];
        });
}

export function loadPublicPrompts() {
    return fetchAllPromptPages("/api/public_prompts", [400])
        .then(prompts => {
            publicPrompts = prompts;
            return prompts;
        })
        .catch(err => {
            console.error("Error loading public prompts:", err);
            publicPrompts = [];
            return [];
        });
}

export function populatePromptSelectScope() {
    if (!promptSelect) return;

    initializePromptSelector();

    const scopes = getEffectiveScopes();
    console.log("Populating prompt dropdown with scopes:", scopes);
    console.log("User prompts:", userPrompts.length);
    console.log("Group prompts:", groupPrompts.length);
    console.log("Public prompts:", publicPrompts.length);

    const previousValue = promptSelect.value;
    promptSelect.innerHTML = "";

    const defaultOpt = document.createElement("option");
    defaultOpt.value = "";
    defaultOpt.textContent = "Select a Prompt...";
    promptSelect.appendChild(defaultOpt);

    let finalPrompts = [];

    if (scopes.personal) {
        finalPrompts = finalPrompts.concat(userPrompts.map(prompt => ({ ...prompt, scope: "Personal" })));
    }
    if (scopes.groupIds.length > 0) {
        finalPrompts = finalPrompts.concat(groupPrompts.map(prompt => ({ ...prompt, scope: "Group" })));
    }
    if (scopes.publicWorkspaceIds.length > 0) {
        finalPrompts = finalPrompts.concat(publicPrompts.map(prompt => ({ ...prompt, scope: "Public" })));
    }

    finalPrompts.forEach(promptObj => {
        const opt = document.createElement("option");
        opt.value = promptObj.id;
        opt.textContent = `[${promptObj.scope}] ${promptObj.name}`;
        opt.dataset.promptContent = promptObj.content;
        promptSelect.appendChild(opt);
    });

    if (finalPrompts.some(prompt => prompt.id === previousValue)) {
        promptSelect.value = previousValue;
    } else {
        promptSelect.value = "";
    }

    promptSelect.dispatchEvent(new Event("change", { bubbles: true }));
    promptSelectorController?.refresh();
}

// Keep the old function for backward compatibility, but have it call the scope-aware version
export function populatePromptSelect() {
  populatePromptSelectScope();
}

export function loadAllPrompts() {
  if (loadAllPromptsPromise) {
    return loadAllPromptsPromise;
  }

  loadAllPromptsPromise = Promise.all([loadUserPrompts(), loadGroupPrompts(), loadPublicPrompts()])
    .then(() => {
      console.log("All prompts loaded, populating scope-based select...");
      populatePromptSelectScope();
    })
    .catch(err => {
      console.error("Error loading all prompts:", err);
    })
    .finally(() => {
      loadAllPromptsPromise = null;
    });

  return loadAllPromptsPromise;
}

export function initializePromptInteractions() {
  console.log("Attempting to initialize prompt interactions...");

  if (searchPromptsBtn && promptSelectionContainer && userInput) {
    initializePromptSelector();
    console.log("Elements found, adding prompt button listener.");

    searchPromptsBtn.addEventListener("click", function() {
      const isActive = this.classList.toggle("active");

      if (isActive) {
        promptSelectionContainer.style.display = "block";
        loadAllPrompts();
        userInput.classList.add("with-prompt-active");
        userInput.focus();
        updateSendButtonVisibility();
      } else {
        promptSelectionContainer.style.display = "none";
        if (promptSelect) {
          promptSelect.selectedIndex = 0;
          promptSelect.dispatchEvent(new Event("change", { bubbles: true }));
        }
        userInput.classList.remove("with-prompt-active");
        userInput.focus();
        updateSendButtonVisibility();
      }
    });

    if (docScopeSelect) {
      docScopeSelect.addEventListener("change", function() {
        if (promptSelectionContainer && promptSelectionContainer.style.display === "block") {
          console.log("Scope changed, repopulating prompts...");
          populatePromptSelectScope();
        }
      });
    }
  } else {
    if (!searchPromptsBtn) console.error("Prompt Init Error: search-prompts-btn not found.");
    if (!promptSelectionContainer) console.error("Prompt Init Error: prompt-selection-container not found.");
    if (!userInput) console.error("Prompt Init Error: userInput (imported from chat-messages) is not available.");
  }
}