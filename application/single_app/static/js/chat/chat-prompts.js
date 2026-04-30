// chat-prompts.js

import { userInput } from "./chat-messages.js";
import { updateSendButtonVisibility } from "./chat-messages.js";
import { getEffectiveScopes } from "./chat-documents.js";
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

let promptSelectorController = null;
let loadAllPromptsPromise = null;
let scopeChangeListenerInitialized = false;
let userPrompts = [];
let groupPrompts = [];
let publicPrompts = [];

function getPreloadedPromptOptions() {
  return Array.isArray(window.chatPromptOptions) ? window.chatPromptOptions : [];
}

function getPromptLabel(prompt) {
  return (prompt.name || "Untitled Prompt").trim() || "Untitled Prompt";
}

function comparePromptNames(leftPrompt, rightPrompt) {
  return getPromptLabel(leftPrompt).localeCompare(getPromptLabel(rightPrompt), undefined, {
    sensitivity: "base",
  });
}

function getSortedSelectedGroups(groupIds) {
  const selectedGroupIdSet = new Set((groupIds || []).map(String));
  return (window.userGroups || [])
    .filter(group => selectedGroupIdSet.has(String(group.id)))
    .sort((leftGroup, rightGroup) => (leftGroup.name || "").localeCompare(rightGroup.name || "", undefined, {
      sensitivity: "base",
    }));
}

function getSortedSelectedPublicWorkspaces(workspaceIds) {
  const selectedWorkspaceIdSet = new Set((workspaceIds || []).map(String));
  return (window.userVisiblePublicWorkspaces || [])
    .filter(workspace => selectedWorkspaceIdSet.has(String(workspace.id)))
    .sort((leftWorkspace, rightWorkspace) => (leftWorkspace.name || "").localeCompare(rightWorkspace.name || "", undefined, {
      sensitivity: "base",
    }));
}

function appendPromptOption(container, prompt) {
  const option = document.createElement("option");
  const promptName = getPromptLabel(prompt);
  const scopeLabel = prompt.scope_type === "group"
    ? `[Group] ${prompt.scope_name || "Unknown Group"}`
    : prompt.scope_type === "public"
      ? `[Public] ${prompt.scope_name || "Unknown Workspace"}`
      : "Personal";

  option.value = prompt.id || "";
  option.textContent = promptName;
  option.dataset.promptContent = prompt.content || "";
  option.dataset.scopeType = prompt.scope_type || "";
  option.dataset.scopeId = prompt.scope_id || "";
  option.dataset.scopeName = prompt.scope_name || "";
  option.dataset.searchText = `${promptName} ${scopeLabel}`.trim();
  container.appendChild(option);
}

function buildPromptSections(scopes) {
  const sections = [];

  if (scopes.personal) {
    const personalSectionPrompts = userPrompts.slice().sort(comparePromptNames);
    if (personalSectionPrompts.length > 0) {
      sections.push({
        label: "Personal",
        prompts: personalSectionPrompts,
      });
    }
  }

  getSortedSelectedGroups(scopes.groupIds).forEach(group => {
    const sectionPrompts = groupPrompts
      .filter(prompt => String(prompt.scope_id || "") === String(group.id))
      .slice()
      .sort(comparePromptNames);

    if (sectionPrompts.length > 0) {
      sections.push({
        label: `[Group] ${group.name || "Unnamed Group"}`,
        prompts: sectionPrompts,
      });
    }
  });

  getSortedSelectedPublicWorkspaces(scopes.publicWorkspaceIds).forEach(workspace => {
    const sectionPrompts = publicPrompts
      .filter(prompt => String(prompt.scope_id || "") === String(workspace.id))
      .slice()
      .sort(comparePromptNames);

    if (sectionPrompts.length > 0) {
      sections.push({
        label: `[Public] ${workspace.name || "Unnamed Workspace"}`,
        prompts: sectionPrompts,
      });
    }
  });

  return sections;
}

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
        getOptionSearchText: option => option.dataset.searchText || option.textContent.trim(),
    });

    return promptSelectorController;
}

export function loadUserPrompts() {
      userPrompts = getPreloadedPromptOptions().filter(prompt => prompt.scope_type === "personal");
      return Promise.resolve(userPrompts);
}

export function loadGroupPrompts() {
      groupPrompts = getPreloadedPromptOptions().filter(prompt => prompt.scope_type === "group");
      return Promise.resolve(groupPrompts);
}

export function loadPublicPrompts() {
      publicPrompts = getPreloadedPromptOptions().filter(prompt => prompt.scope_type === "public");
      return Promise.resolve(publicPrompts);
}

export function populatePromptSelectScope() {
    if (!promptSelect) return;

    initializePromptSelector();

    const scopes = getEffectiveScopes();
    const previousValue = promptSelect.value;
    promptSelect.innerHTML = "";

    const defaultOpt = document.createElement("option");
    defaultOpt.value = "";
    defaultOpt.textContent = "Select a Prompt...";
    promptSelect.appendChild(defaultOpt);

      buildPromptSections(scopes).forEach(section => {
        const optGroup = document.createElement("optgroup");
        optGroup.label = section.label;

        section.prompts.forEach(prompt => {
          appendPromptOption(optGroup, prompt);
        });

        promptSelect.appendChild(optGroup);
    });

      const availableOptions = Array.from(promptSelect.options);
      if (availableOptions.some(option => option.value === previousValue)) {
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

function initializeScopeChangeListener() {
    if (scopeChangeListenerInitialized) {
        return;
    }

    window.addEventListener("chat:scope-changed", () => {
        if (!promptSelectionContainer || promptSelectionContainer.style.display !== "block") {
            return;
        }

        populatePromptSelectScope();
    });

    scopeChangeListenerInitialized = true;
}

export function initializePromptInteractions() {
    if (searchPromptsBtn && promptSelectionContainer && userInput) {
        initializePromptSelector();
        initializeScopeChangeListener();

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
    } else {
        if (!searchPromptsBtn) console.error("Prompt Init Error: search-prompts-btn not found.");
        if (!promptSelectionContainer) console.error("Prompt Init Error: prompt-selection-container not found.");
        if (!userInput) console.error("Prompt Init Error: userInput (imported from chat-messages) is not available.");
    }
}