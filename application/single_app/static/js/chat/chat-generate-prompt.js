// chat-generate-prompt.js
/**
 * Module for generating a reusable prompt from a conversation using AI analysis.
 * Provides a toolbar button that triggers AI analysis of the current conversation,
 * then presents a modal for the user to review, edit, and save the generated prompt.
 */

import { showToast } from "./chat-toast.js";
import { loadUserPrompts, loadGroupPrompts, loadAllPrompts } from "./chat-prompts.js";

const generatePromptBtn = document.getElementById("generate-prompt-btn");
const generatePromptModal = document.getElementById("generate-prompt-modal");
const generatePromptName = document.getElementById("generate-prompt-name");
const generatePromptContent = document.getElementById("generate-prompt-content");
const generatePromptScope = document.getElementById("generate-prompt-scope");
const generatePromptSaveBtn = document.getElementById("generate-prompt-save-btn");
const generatePromptRegenerateBtn = document.getElementById("generate-prompt-regenerate-btn");
const generatePromptLoading = document.getElementById("generate-prompt-loading");
const generatePromptForm = document.getElementById("generate-prompt-form");

let bsGeneratePromptModal = null;

/**
 * Initialize the generate prompt feature by wiring up the toolbar button.
 */
export function initializeGeneratePrompt() {
    if (!generatePromptBtn || !generatePromptModal) {
        console.log("Generate prompt elements not found, skipping initialization.");
        return;
    }

    bsGeneratePromptModal = new bootstrap.Modal(generatePromptModal);

    // Toolbar button click
    generatePromptBtn.addEventListener("click", () => {
        if (!currentConversationId) {
            showToast("Please select or start a conversation first.", "warning");
            return;
        }
        openGeneratePromptModal();
    });

    // Save button click
    if (generatePromptSaveBtn) {
        generatePromptSaveBtn.addEventListener("click", () => {
            saveGeneratedPrompt();
        });
    }

    // Regenerate button click
    if (generatePromptRegenerateBtn) {
        generatePromptRegenerateBtn.addEventListener("click", () => {
            generatePromptFromConversation();
        });
    }

    console.log("Generate prompt feature initialized.");
}

/**
 * Open the generate prompt modal and start AI analysis.
 */
function openGeneratePromptModal() {
    // Reset form state
    if (generatePromptName) generatePromptName.value = "";
    if (generatePromptContent) generatePromptContent.value = "";
    if (generatePromptScope) generatePromptScope.value = "personal";

    // Show modal
    bsGeneratePromptModal.show();

    // Start generation
    generatePromptFromConversation();
}

/**
 * Call the backend API to generate a prompt from the current conversation.
 */
async function generatePromptFromConversation() {
    if (!currentConversationId) {
        showToast("No active conversation selected.", "warning");
        return;
    }

    // Show loading state
    setLoadingState(true);

    try {
        const response = await fetch(`/api/conversations/${currentConversationId}/generate-prompt`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            }
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || `HTTP ${response.status}: ${response.statusText}`);
        }

        if (data.success) {
            if (generatePromptName) generatePromptName.value = data.name || "";
            if (generatePromptContent) generatePromptContent.value = data.content || "";
            console.log("Prompt generated successfully from conversation.");
        } else {
            throw new Error(data.error || "Unknown error generating prompt");
        }
    } catch (error) {
        console.error("Error generating prompt from conversation:", error);
        showToast(`Failed to generate prompt: ${error.message}`, "danger");
    } finally {
        setLoadingState(false);
    }
}

/**
 * Save the generated prompt to the selected scope.
 */
async function saveGeneratedPrompt() {
    const name = generatePromptName ? generatePromptName.value.trim() : "";
    const content = generatePromptContent ? generatePromptContent.value.trim() : "";
    const scope = generatePromptScope ? generatePromptScope.value : "personal";

    if (!name) {
        showToast("Please enter a prompt name.", "warning");
        if (generatePromptName) generatePromptName.focus();
        return;
    }

    if (!content) {
        showToast("Please enter prompt content.", "warning");
        if (generatePromptContent) generatePromptContent.focus();
        return;
    }

    // Determine the API endpoint based on scope
    let apiUrl;
    switch (scope) {
        case "group":
            apiUrl = "/api/group_prompts";
            break;
        case "public":
            apiUrl = "/api/public_prompts";
            break;
        case "personal":
        default:
            apiUrl = "/api/prompts";
            break;
    }

    // Disable save button during save
    if (generatePromptSaveBtn) {
        generatePromptSaveBtn.disabled = true;
        generatePromptSaveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Saving...';
    }

    try {
        const response = await fetch(apiUrl, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ name, content })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || `HTTP ${response.status}: ${response.statusText}`);
        }

        // Success
        showToast(`Prompt "${name}" saved successfully!`, "success");
        bsGeneratePromptModal.hide();

        // Refresh the prompts lists so the new prompt appears in the dropdown
        loadAllPrompts();

    } catch (error) {
        console.error("Error saving generated prompt:", error);
        showToast(`Failed to save prompt: ${error.message}`, "danger");
    } finally {
        // Re-enable save button
        if (generatePromptSaveBtn) {
            generatePromptSaveBtn.disabled = false;
            generatePromptSaveBtn.innerHTML = '<i class="bi bi-floppy me-1"></i>Save Prompt';
        }
    }
}

/**
 * Toggle loading state in the modal.
 * @param {boolean} isLoading - Whether to show loading spinner
 */
function setLoadingState(isLoading) {
    if (generatePromptLoading) {
        if (isLoading) {
            generatePromptLoading.classList.remove("d-none");
        } else {
            generatePromptLoading.classList.add("d-none");
        }
    }

    if (generatePromptForm) {
        if (isLoading) {
            generatePromptForm.classList.add("d-none");
        } else {
            generatePromptForm.classList.remove("d-none");
        }
    }

    if (generatePromptSaveBtn) {
        generatePromptSaveBtn.disabled = isLoading;
    }

    if (generatePromptRegenerateBtn) {
        generatePromptRegenerateBtn.disabled = isLoading;
    }
}
