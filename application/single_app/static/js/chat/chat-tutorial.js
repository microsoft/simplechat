// chat-tutorial.js

const STORAGE_KEY = "chatTutorialDismissed";
const EDGE_PADDING = 12;
const HIGHLIGHT_PADDING = 10;
let tutorialSteps = [];
let layerEl = null;
let highlightEl = null;
let cardEl = null;
let currentStepIndex = -1;
let activeTarget = null;
let forcedVisibleTarget = null;
let highlightedPopupTarget = null;
let temporaryStateRestorers = [];
let sidebarStateRestorer = null;
let tutorialConversationId = null;
let tutorialPopupEl = null;
let tutorialMessagePopupEl = null;
let tutorialMessageExamplesEl = null;
let tutorialAdvancedSearchEl = null;
let popupRefreshToken = 0;
let baseOffset = { top: 0, left: 0, width: window.innerWidth, height: window.innerHeight };
let currentPhase = "nav";

const CONVERSATION_POPUP_STEP_IDS = ["conversation-action-menu", "conversation-pin-action", "conversation-hide-action", "conversation-select-action", "conversation-export-action"];
const CONVERSATION_POPUP_ITEM_STEP_IDS = ["conversation-pin-action", "conversation-hide-action", "conversation-select-action", "conversation-export-action"];
const USER_MESSAGE_POPUP_STEP_IDS = ["user-message-edit-action"];
const AI_MESSAGE_POPUP_STEP_IDS = ["ai-message-retry-action", "ai-message-feedback-action", "ai-message-export-md", "ai-message-export-word", "ai-message-use-prompt", "ai-message-open-email"];
const MESSAGE_POPUP_STEP_IDS = [...USER_MESSAGE_POPUP_STEP_IDS, ...AI_MESSAGE_POPUP_STEP_IDS];
const MESSAGE_POPUP_ITEM_STEP_IDS = [...MESSAGE_POPUP_STEP_IDS];
const MESSAGE_STEP_IDS = [
    "message-metadata",
    "message-copy",
    "message-mask",
    "user-message-actions",
    "user-message-edit-action",
    "ai-message-actions",
    "ai-message-retry-action",
    "ai-message-feedback-action",
    "ai-message-export-md",
    "ai-message-export-word",
    "ai-message-use-prompt",
    "ai-message-open-email",
    "ai-message-thoughts",
    "ai-message-citations"
];

function forceModalBackdropAboveTutorial() {
    const backdropEl = Array.from(document.querySelectorAll(".modal-backdrop.show")).pop();
    if (!backdropEl) {
        return;
    }

    backdropEl.classList.add("tutorial-force-backdrop");
    registerTemporaryStateRestorer(() => {
        backdropEl.classList.remove("tutorial-force-backdrop");
    });
}

function updateTutorialLaunchVisibility(forceReady = false) {
    const launchContainer = document.getElementById("chat-tutorial-launch");
    const sidebarList = document.getElementById("sidebar-conversations-list");
    if (!launchContainer) {
        return;
    }

    const sidebarLoaded = forceReady || !sidebarList || !/Loading conversations/i.test(sidebarList.textContent || "");
    launchContainer.classList.toggle("is-ready", sidebarLoaded);
}

function isTutorialLaunchReady() {
    return document.getElementById("chat-tutorial-launch")?.classList.contains("is-ready");
}

function buildSteps() {
    return [
        {
            id: "new-chat",
            selectorList: ["#sidebar-new-chat-btn","#new-conversation-btn"],
            title: "Start a new chat",
            body: "Create a fresh conversation; each chat keeps its own history and files.",
            phase: "nav"
        },
        {
            id: "conversation-list",
            selectorList: ["#sidebar-conversations-list", "#conversations-list"],
            title: "Conversation list",
            body: "Switch between existing chats. Hover to reveal actions or multi-select to bulk pin, hide, or delete.",
            phase: "nav"
        },
        {
            id: "conversation-actions",
            selector: ".sidebar-conversation-item .conversation-dropdown button",
            title: "Conversation actions",
            body: "Use the three-dot menu to open the per-conversation actions for the chat under your pointer.",
            phase: "nav"
        },
        {
            id: "conversation-action-menu",
            selector: ".sidebar-conversation-item .dropdown-menu .details-btn",
            title: "Conversation menu",
            body: "From here you can inspect details, keep an important chat pinned near the top, hide it from everyday view, export it, rename it, or delete it.",
            phase: "nav"
        },
        {
            id: "conversation-pin-action",
            selector: ".sidebar-conversation-item .dropdown-menu .pin-btn",
            title: "Pin important chats",
            body: "Pin keeps a conversation easy to reach. It is useful for active workstreams, handoffs, and long-running investigations you revisit often.",
            phase: "nav"
        },
        {
            id: "conversation-hide-action",
            selector: ".sidebar-conversation-item .dropdown-menu .hide-btn",
            title: "Hide without deleting",
            body: "Hide removes a chat from the main list without throwing it away, which is useful for decluttering while keeping the record available later.",
            phase: "nav"
        },
        {
            id: "conversation-select-action",
            selector: ".sidebar-conversation-item .dropdown-menu .select-btn",
            title: "Select for bulk actions",
            body: "Use Select to enter selection mode and start building a set of conversations for bulk pin, hide, delete, or export.",
            phase: "nav"
        },
        {
            id: "conversation-bulk-actions",
            selectorList: ["#sidebar-export-selected-btn", "#sidebar-pin-selected-btn", "#sidebar-hide-selected-btn", "#sidebar-delete-selected-btn", "#export-selected-btn", "#pin-selected-btn", "#hide-selected-btn", "#delete-selected-btn"],
            title: "Bulk actions",
            body: "Once selection mode is active, the bulk action buttons appear so you can manage several conversations at once.",
            phase: "nav"
        },
        {
            id: "conversation-search",
            selector: "#sidebar-search-btn",
            title: "Find conversations",
            body: "Open quick search to filter conversations by title; advanced search is available from the expand icon.",
            phase: "nav"
        },
        {
            id: "conversation-search-input",
            selector: "#sidebar-search-input",
            title: "Quick title search",
            body: "This quick search filters the conversation list by title as you type. Use the clear button to reset it quickly.",
            phase: "nav"
        },
        {
            id: "conversation-advanced-search",
            selector: "#sidebar-search-expand",
            title: "Advanced search",
            body: "Use the expand button to search message content, date ranges, chat type, classifications, files, and generated images.",
            phase: "nav"
        },
        {
            id: "conversation-advanced-search-modal",
            selector: "#searchMessageInput",
            title: "Advanced search filters",
            body: "The advanced search dialog searches message content and gives you richer filters than the quick title search above.",
            phase: "nav"
        },
        {
            id: "conversation-export-action",
            selector: ".sidebar-conversation-item .dropdown-menu .export-btn",
            title: "Single conversation export",
            body: "Use Export on one conversation when you want a focused download without entering multi-select mode.",
            phase: "nav"
        },
        {
            id: "conversation-export-wizard",
            selector: ".action-type-card[data-format='json']",
            title: "Export wizard",
            body: "The export wizard lets you choose the format, packaging, summary options, and final download flow for the selected conversation.",
            phase: "nav"
        },
        {
            id: "conversation-hidden-toggle",
            selector: "#sidebar-conversations-settings-btn",
            title: "Show hidden conversations",
            body: "Toggle visibility of hidden chats so you can unhide or manage them.",
            phase: "nav"
        },
        {
            id: "conversation-info",
            selector: "#conversation-info-btn",
            title: "Conversation details",
            body: "Press the i button to open the conversation details drawer, where you can review metadata, shared files, and classifications for the current chat.",
            phase: "chat"
        },
        {
            id: "image-generation",
            selector: "#image-generate-btn",
            title: "Generate images",
            body: "Switch from text chat to image generation when you want the model to create visuals instead of a written reply.",
            phase: "chat"
        },
        {
            id: "workspace-search",
            selector: "#search-documents-btn",
            title: "Workspace search",
            body: "Search personal, group, or public workspaces to ground answers with approved documents.",
            phase: "chat"
        },
        {
            id: "workspace-scope",
            selector: "#scope-dropdown-button",
            title: "Workspace scope",
            body: "Pick which workspaces to search. You can combine personal, group, and public sources in the same conversation.",
            phase: "chat"
        },
        {
            id: "workspace-tags",
            selector: "#tags-dropdown-button",
            title: "Tag filters",
            body: "Narrow the workspace search to documents with matching tags before you ask your next question.",
            phase: "chat"
        },
        {
            id: "workspace-document",
            selector: "#document-dropdown-button",
            title: "Document picker",
            body: "Choose a specific document to ground responses or leave on All Documents to search everything in scope.",
            phase: "chat"
        },
        {
            id: "workspace-lock",
            selectorList: ["#scope-lock-indicator", "#header-scope-lock-btn"],
            title: "Scope lock",
            body: "When a conversation is locked to specific workspaces, this lock shows you the restriction and lets you manage it.",
            phase: "chat"
        },
        {
            id: "file-upload",
            selector: "#choose-file-btn",
            title: "Attach files",
            body: "Upload a document; it persists only in this conversation and can be cited in responses.",
            phase: "chat"
        },
        {
            id: "web-search",
            selector: "#search-web-btn",
            title: "Web search",
            body: "Toggle Bing search when you need fresh, public information.",
            phase: "chat"
        },
        {
            id: "prompt-library",
            selector: "#search-prompts-btn",
            title: "Prompt library",
            body: "Open the saved prompt library to preload a reusable instruction or template into your next message.",
            phase: "chat"
        },
        {
            id: "prompt-select",
            selector: "#prompt-dropdown-button",
            title: "Prompt picker",
            body: "Browse or search the currently available prompts for the selected workspace scope.",
            phase: "chat"
        },
        {
            id: "assistant-selector",
            selectorList: ["#model-dropdown-button", "#agent-dropdown-button"],
            title: "Model or agent picker",
            body: "This selector shows the currently active model or, if agents are enabled, the active agent for the conversation.",
            phase: "chat"
        },
        {
            id: "agents",
            selector: "#enable-agents-btn",
            title: "Agents toggle",
            body: "Switch between direct model chat and agent-driven workflows when agent features are enabled.",
            phase: "chat"
        },
        {
            id: "reasoning",
            selector: "#reasoning-toggle-btn",
            title: "Reasoning effort",
            body: "Adjust reasoning depth and cost for more or less thorough answers on models that support it.",
            phase: "chat"
        },
        {
            id: "tts",
            selector: "#tts-autoplay-toggle-btn",
            title: "Voice replies",
            body: "Have responses read aloud automatically when voice playback is enabled.",
            phase: "chat"
        },
        {
            id: "chat-input",
            selector: "#user-input",
            title: "Type your message",
            body: "Enter your question, paste snippets, or draft a prompt before sending it to the assistant.",
            phase: "chat"
        },
        {
            id: "speech-input",
            selector: "#speech-input-btn",
            title: "Voice input",
            body: "Use your microphone to dictate a message instead of typing when speech input is enabled.",
            phase: "chat"
        },
        {
            id: "send-message",
            selector: "#send-btn",
            title: "Send message",
            body: "Use the send button when your draft is ready. The same conversation keeps your context, files, and workspace selections together.",
            phase: "chat"
        },
        {
            id: "message-metadata",
            selectorList: [".tutorial-ai-message .metadata-container", ".ai-message .metadata-container"],
            title: "Message metadata",
            body: "Press the i button on a message to open its metadata drawer. This is where you confirm model details, timing, source context, and other audit clues that help with troubleshooting and validation.",
            phase: "chat"
        },
        {
            id: "message-copy",
            selectorList: [".tutorial-ai-message .copy-btn", ".ai-message .copy-btn"],
            title: "Copy an answer",
            body: "Copy the AI response as Markdown when you want to paste it into email, docs, tickets, or another chat without losing structure.",
            phase: "chat"
        },
        {
            id: "message-mask",
            selectorList: [".tutorial-ai-message .mask-btn", ".ai-message .mask-btn"],
            title: "Mask sensitive content",
            body: "Masking lets you hide an entire message or only the sensitive part of it. That is useful when a chat contains information, data, or text you do not want reused by later responses.",
            phase: "chat"
        },
        {
            id: "user-message-actions",
            selectorList: [".tutorial-user-message .dropdown > button", ".user-message .message-footer .dropdown > button"],
            title: "Your message actions",
            body: "Your sent messages have their own action menu so you can correct, retry, export, or reuse what you asked without typing it again.",
            phase: "chat"
        },
        {
            id: "user-message-edit-action",
            selectorList: [".tutorial-user-message .dropdown-menu .dropdown-edit-btn", ".user-message .dropdown-menu .dropdown-edit-btn"],
            title: "Edit a sent prompt",
            body: "Use Edit when you want to refine the original request and rerun it, instead of starting over from scratch.",
            phase: "chat"
        },
        {
            id: "ai-message-actions",
            selectorList: [".tutorial-ai-message .dropdown > button", ".ai-message .message-actions .dropdown > button"],
            title: "AI response actions",
            body: "The AI response menu collects the follow-up tools for retrying, rating, exporting, and reusing a reply.",
            phase: "chat"
        },
        {
            id: "ai-message-retry-action",
            selectorList: [".tutorial-ai-message .dropdown-menu .dropdown-retry-btn", ".ai-message .dropdown-menu .dropdown-retry-btn"],
            title: "Retry a response",
            body: "Retry asks the system to generate another attempt for the same point in the conversation, which is useful when you want a better answer without rewriting your prompt.",
            phase: "chat"
        },
        {
            id: "ai-message-feedback-action",
            selectorList: [".tutorial-ai-message .dropdown-menu .feedback-btn", ".ai-message .dropdown-menu .feedback-btn"],
            title: "Thumbs up and down",
            body: "Use thumbs up or thumbs down to rate the response quality. That feedback helps you capture what was useful and flag answers that need correction.",
            phase: "chat"
        },
        {
            id: "ai-message-export-md",
            selectorList: [".tutorial-ai-message .dropdown-menu .dropdown-export-md-btn", ".ai-message .dropdown-menu .dropdown-export-md-btn"],
            title: "Export to Markdown",
            body: "Markdown export is useful when you want a portable copy that preserves headings, lists, tables, and code blocks.",
            phase: "chat"
        },
        {
            id: "ai-message-export-word",
            selectorList: [".tutorial-ai-message .dropdown-menu .dropdown-export-word-btn", ".ai-message .dropdown-menu .dropdown-export-word-btn"],
            title: "Export to Word",
            body: "Word export is helpful when the next stop is a polished document, a handoff packet, or something nontechnical collaborators will review.",
            phase: "chat"
        },
        {
            id: "ai-message-use-prompt",
            selectorList: [".tutorial-ai-message .dropdown-menu .dropdown-copy-prompt-btn", ".ai-message .dropdown-menu .dropdown-copy-prompt-btn"],
            title: "Use as prompt",
            body: "Use as Prompt turns a good response into a starting point for the next request, which is useful for iterative drafting and workflow chaining.",
            phase: "chat"
        },
        {
            id: "ai-message-open-email",
            selectorList: [".tutorial-ai-message .dropdown-menu .dropdown-open-email-btn", ".ai-message .dropdown-menu .dropdown-open-email-btn"],
            title: "Open in email",
            body: "Open in Email is a fast handoff path when the response is ready to share with a teammate or stakeholder.",
            phase: "chat"
        },
        {
            id: "ai-message-thoughts",
            selectorList: [".tutorial-ai-message .thoughts-container", ".ai-message .thoughts-container"],
            title: "Processing thoughts",
            body: "Press the thoughts button to open the processing drawer when it is available. It shows the high-level reasoning steps the system recorded so you can see how the answer was assembled and where time was spent.",
            phase: "chat"
        },
        {
            id: "ai-message-citations",
            selectorList: [".tutorial-ai-message .citations-container", ".ai-message .citations-container"],
            title: "Sources and citations",
            body: "Press the sources button to open the citations drawer and inspect the files, web pages, or agent sources behind the answer. This is how you verify evidence and open the supporting material directly.",
            phase: "chat"
        }
    ];
}

function registerTemporaryStateRestorer(restorer) {
    if (typeof restorer === "function") {
        temporaryStateRestorers.push(restorer);
    }
}

function restoreTemporaryState() {
    while (temporaryStateRestorers.length) {
        const restore = temporaryStateRestorers.pop();
        try {
            restore();
        } catch (error) {
            console.warn("chat-tutorial: failed to restore temporary state", error);
        }
    }

    if (forcedVisibleTarget) {
        forcedVisibleTarget.classList.remove("tutorial-force-visible");
        forcedVisibleTarget = null;
    }

    if (highlightedPopupTarget) {
        highlightedPopupTarget.classList.remove("tutorial-popup-target-highlight");
        highlightedPopupTarget = null;
    }

    if (tutorialPopupEl) {
        tutorialPopupEl.remove();
        tutorialPopupEl = null;
    }

    if (tutorialMessagePopupEl) {
        tutorialMessagePopupEl.remove();
        tutorialMessagePopupEl = null;
    }

    if (tutorialMessageExamplesEl) {
        tutorialMessageExamplesEl.remove();
        tutorialMessageExamplesEl = null;
    }

    if (tutorialAdvancedSearchEl) {
        tutorialAdvancedSearchEl.remove();
        tutorialAdvancedSearchEl = null;
    }
}

function showElementForTutorial(el, displayValue = "block") {
    if (!el) {
        return;
    }

    const computedDisplay = window.getComputedStyle(el).display;
    if (computedDisplay !== "none" && el.style.display !== "none") {
        return;
    }

    const previousDisplay = el.style.display;
    el.style.display = displayValue;
    registerTemporaryStateRestorer(() => {
        if (el.style.display === displayValue) {
            el.style.display = previousDisplay;
        }
    });
}

function ensureDocumentsPanelVisible() {
    const docContainer = document.getElementById("search-documents-container");
    const docBtn = document.getElementById("search-documents-btn");
    if (!docContainer) {
        return;
    }

    if (docContainer.style.display === "none") {
        if (docBtn && !docBtn.classList.contains("active")) {
            docBtn.click();
            registerTemporaryStateRestorer(() => {
                if (docBtn.classList.contains("active")) {
                    docBtn.click();
                }
            });
            return;
        }

        showElementForTutorial(docContainer, "block");
    }
}

function ensurePromptPanelVisible() {
    const promptContainer = document.getElementById("prompt-selection-container");
    const promptBtn = document.getElementById("search-prompts-btn");
    if (!promptContainer) {
        return;
    }

    if (promptContainer.style.display === "none") {
        if (promptBtn && !promptBtn.classList.contains("active")) {
            promptBtn.click();
            registerTemporaryStateRestorer(() => {
                if (promptBtn.classList.contains("active")) {
                    promptBtn.click();
                }
            });
            return;
        }

        showElementForTutorial(promptContainer, "block");
    }
}

function isSidebarCollapsed() {
    const sidebar = document.getElementById("sidebar-nav");
    return Boolean(
        document.body?.classList.contains("sidebar-collapsed") ||
        sidebar?.classList.contains("sidebar-collapsed") ||
        (sidebar && !sidebar.classList.contains("sidebar-expanded"))
    );
}

function toggleSidebarForTutorial() {
    const wasCollapsed = isSidebarCollapsed();
    const floatingExpandBtn = document.getElementById("floating-expand-btn");
    const sidebarToggleBtn = document.getElementById("sidebar-toggle-btn");

    if (wasCollapsed && floatingExpandBtn) {
        floatingExpandBtn.click();
        return wasCollapsed !== isSidebarCollapsed();
    }

    if (typeof window.toggleSidebar === "function") {
        window.toggleSidebar();
        return wasCollapsed !== isSidebarCollapsed();
    }

    if (sidebarToggleBtn) {
        sidebarToggleBtn.click();
        return wasCollapsed !== isSidebarCollapsed();
    }

    return false;
}

function ensureSidebarExpandedForTutorial() {
    if (!isSidebarCollapsed()) {
        return;
    }

    const changedState = toggleSidebarForTutorial();
    if (!changedState || sidebarStateRestorer) {
        return;
    }

    sidebarStateRestorer = () => {
        if (!isSidebarCollapsed()) {
            toggleSidebarForTutorial();
        }
    };
}

function restoreSidebarState() {
    if (!sidebarStateRestorer) {
        return;
    }

    const restore = sidebarStateRestorer;
    sidebarStateRestorer = null;

    try {
        restore();
    } catch (error) {
        console.warn("chat-tutorial: failed to restore sidebar state", error);
    }
}

function getStepSelectors(step) {
    return step?.selectorList || (step?.selector ? [step.selector] : []);
}

function findStepTarget(step, requireVisible = true) {
    const selectors = getStepSelectors(step);

    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (!el) {
            continue;
        }

        if (!requireVisible) {
            return el;
        }

        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
            return el;
        }
    }

    return null;
}

function prepareStepTarget(step) {
    if (!step) {
        return;
    }

    if (isMessageTutorialStep(step.id)) {
        ensureTutorialMessageExamples(step);
    }

    if (step.phase === "nav") {
        ensureSidebarExpandedForTutorial();
    }

    if (["workspace-scope", "workspace-tags", "workspace-document", "workspace-lock"].includes(step.id)) {
        ensureDocumentsPanelVisible();
    }

    if (CONVERSATION_POPUP_STEP_IDS.includes(step.id)) {
        ensureSidebarConversationDropdownVisible();
    }

    if (["conversation-search-input", "conversation-advanced-search"].includes(step.id)) {
        ensureQuickSearchVisible();
    }

    if (step.id === "conversation-hidden-toggle") {
        ensureSidebarHeaderControlsVisible();
    }

    if (step.id === "conversation-bulk-actions") {
        ensureSelectionModeVisible();
    }

    if (step.id === "conversation-info") {
        ensureConversationInfoVisible();
    }

    if (step.id === "conversation-advanced-search-modal") {
        ensureTutorialAdvancedSearchPopup();
    }

    if (step.id === "conversation-export-wizard") {
        ensureSingleConversationExportWizardVisible();
    }

    if (step.id === "prompt-select") {
        ensurePromptPanelVisible();
    }

    if (step.id === "send-message") {
        ensureSendButtonVisible();
    }

    if (step.id === "message-metadata") {
        ensureMessageMetadataVisible();
    }

    if (step.id === "ai-message-thoughts") {
        ensureMessageThoughtsVisible();
    }

    if (step.id === "ai-message-citations") {
        ensureMessageCitationsVisible();
    }
}

function getFirstSidebarConversationItem() {
    return document.querySelector(".sidebar-conversation-item");
}

function getTutorialConversationItem() {
    if (tutorialConversationId) {
        const existingItem = document.querySelector(`.sidebar-conversation-item[data-conversation-id="${tutorialConversationId}"]`);
        if (existingItem) {
            return existingItem;
        }
    }

    const activeItem = document.querySelector(".sidebar-conversation-item.active");
    const conversationItem = activeItem || getFirstSidebarConversationItem();

    tutorialConversationId = conversationItem?.getAttribute("data-conversation-id") || null;
    return conversationItem;
}

function getSidebarConversationDropdownToggle(conversationItem = getTutorialConversationItem()) {
    return conversationItem?.querySelector(".conversation-dropdown button[data-bs-toggle='dropdown']") || null;
}

function getConversationStepTarget(step, requireVisible = true) {
    if (step.id === "conversation-advanced-search-modal" && tutorialAdvancedSearchEl) {
        const advancedSearchTarget = tutorialAdvancedSearchEl.querySelector(".modal-content") || tutorialAdvancedSearchEl;
        if (!requireVisible) {
            return advancedSearchTarget;
        }

        const advancedSearchRect = advancedSearchTarget.getBoundingClientRect();
        if (advancedSearchRect.width > 0 && advancedSearchRect.height > 0) {
            return advancedSearchTarget;
        }
    }

    if (CONVERSATION_POPUP_STEP_IDS.includes(step.id) && tutorialPopupEl) {
        let tutorialPopupTarget = null;

        if (step.id === "conversation-action-menu") {
            tutorialPopupTarget = tutorialPopupEl;
        } else if (step.id === "conversation-pin-action") {
            tutorialPopupTarget = tutorialPopupEl.querySelector(".pin-btn");
        } else if (step.id === "conversation-hide-action") {
            tutorialPopupTarget = tutorialPopupEl.querySelector(".hide-btn");
        } else if (step.id === "conversation-select-action") {
            tutorialPopupTarget = tutorialPopupEl.querySelector(".select-btn");
        } else if (step.id === "conversation-export-action") {
            tutorialPopupTarget = tutorialPopupEl.querySelector(".export-btn");
        }

        if (tutorialPopupTarget) {
            if (!requireVisible) {
                return tutorialPopupTarget;
            }

            const popupRect = tutorialPopupTarget.getBoundingClientRect();
            if (popupRect.width > 0 && popupRect.height > 0) {
                return tutorialPopupTarget;
            }
        }
    }

    const conversationItem = getTutorialConversationItem();
    if (!conversationItem) {
        return null;
    }

    let target = null;

    if (step.id === "conversation-actions") {
        target = getSidebarConversationDropdownToggle(conversationItem);
    } else if (step.id === "conversation-action-menu") {
        target = conversationItem.querySelector(".dropdown-menu");
    } else if (step.id === "conversation-pin-action") {
        target = conversationItem.querySelector(".dropdown-menu .pin-btn");
    } else if (step.id === "conversation-hide-action") {
        target = conversationItem.querySelector(".dropdown-menu .hide-btn");
    } else if (step.id === "conversation-select-action") {
        target = conversationItem.querySelector(".dropdown-menu .select-btn");
    } else if (step.id === "conversation-export-action") {
        target = conversationItem.querySelector(".dropdown-menu .export-btn");
    }

    if (!target) {
        return null;
    }

    if (!requireVisible) {
        return target;
    }

    const rect = target.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 ? target : null;
}

function ensureSidebarConversationDropdownVisible() {
    const conversationItem = getTutorialConversationItem();
    const dropdownToggle = getSidebarConversationDropdownToggle(conversationItem);
    if (!conversationItem || !dropdownToggle) {
        return;
    }

    const dropdown = dropdownToggle.closest(".conversation-dropdown");
    if (dropdown) {
        dropdown.classList.add("tutorial-force-visible");
        forcedVisibleTarget = dropdown;
    }

    const menu = conversationItem.querySelector(".dropdown-menu");
    if (menu && menu.classList.contains("show")) {
        return;
    }

    try {
        const dropdownInstance = bootstrap.Dropdown.getOrCreateInstance(dropdownToggle, {
            popperConfig(defaultConfig) {
                const existingModifiers = Array.isArray(defaultConfig?.modifiers) ? defaultConfig.modifiers : [];
                const hasFlipModifier = existingModifiers.some((modifier) => modifier?.name === "flip");

                return {
                    ...defaultConfig,
                    strategy: "fixed",
                    modifiers: hasFlipModifier
                        ? existingModifiers
                        : [
                            ...existingModifiers,
                            {
                                name: "flip",
                                options: {
                                    fallbackPlacements: ["top-end", "bottom-end"]
                                }
                            }
                        ]
                };
            }
        });
        dropdownInstance.show();
        registerTemporaryStateRestorer(() => {
            dropdownInstance.hide();
        });
    } catch (error) {
        dropdownToggle.click();
        registerTemporaryStateRestorer(() => {
            if (menu && menu.classList.contains("show")) {
                dropdownToggle.click();
            }
        });
    }
}

function ensureTutorialConversationMenuPopup(step) {
    if (!step || !CONVERSATION_POPUP_STEP_IDS.includes(step.id)) {
        return;
    }

    if (tutorialPopupEl) {
        return;
    }

    const conversationItem = getTutorialConversationItem();
    const dropdownToggle = getSidebarConversationDropdownToggle(conversationItem);
    const sourceMenu = conversationItem?.querySelector(".dropdown-menu");
    if (!conversationItem || !dropdownToggle || !sourceMenu) {
        return;
    }

    const toggleRect = dropdownToggle.getBoundingClientRect();
    const popup = sourceMenu.cloneNode(true);
    popup.classList.add("show", "tutorial-conversation-popup", "tutorial-force-popup");
    popup.style.position = "fixed";
    popup.style.display = "block";
    popup.style.left = `${Math.max(12, toggleRect.right - 220)}px`;
    popup.style.top = `${Math.max(12, toggleRect.bottom + 8)}px`;

    document.body.appendChild(popup);
    tutorialPopupEl = popup;

    requestAnimationFrame(() => {
        if (!tutorialPopupEl) {
            return;
        }

        const popupRect = tutorialPopupEl.getBoundingClientRect();
        const adjustedLeft = Math.min(
            Math.max(12, toggleRect.right - popupRect.width),
            window.innerWidth - popupRect.width - 12
        );
        const adjustedTop = Math.min(toggleRect.bottom + 8, window.innerHeight - popupRect.height - 12);

        tutorialPopupEl.style.left = `${Math.max(12, adjustedLeft)}px`;
        tutorialPopupEl.style.top = `${Math.max(12, adjustedTop)}px`;
    });

    registerTemporaryStateRestorer(() => {
        if (tutorialPopupEl) {
            tutorialPopupEl.remove();
            tutorialPopupEl = null;
        }
    });
}

function isMessageTutorialStep(stepId) {
    return MESSAGE_STEP_IDS.includes(stepId);
}

function isFeedbackTutorialStep(stepId) {
    return stepId === "ai-message-feedback-action";
}

function isThoughtsTutorialStep(stepId) {
    return stepId === "ai-message-thoughts";
}

function shouldIncludeMessageTutorialStep(step) {
    if (!step || !isMessageTutorialStep(step.id)) {
        return false;
    }

    if (isFeedbackTutorialStep(step.id)) {
        return Boolean(window.enableUserFeedback || document.querySelector(".feedback-btn"));
    }

    if (isThoughtsTutorialStep(step.id)) {
        return Boolean(window.appSettings?.enable_thoughts || document.querySelector(".thoughts-toggle-btn"));
    }

    return true;
}

function getNonTutorialMatches(selector) {
    return Array.from(document.querySelectorAll(selector)).filter((el) => !el.closest(".tutorial-message-examples"));
}

function getMessageStepConfig(stepId) {
    const userConfig = {
        actionToggleSelector: ".message-footer .dropdown button[data-bs-toggle='dropdown']",
        menuSelector: ".message-footer .dropdown-menu"
    };
    const aiConfig = {
        actionToggleSelector: ".message-actions .dropdown button[data-bs-toggle='dropdown']",
        menuSelector: ".message-actions .dropdown-menu"
    };

    const configs = {
        "message-metadata": { type: "ai", selector: ".metadata-container" },
        "message-copy": { type: "ai", selector: ".copy-btn" },
        "message-mask": { type: "ai", selector: ".mask-btn" },
        "user-message-actions": { type: "user", selector: userConfig.actionToggleSelector },
        "user-message-edit-action": { type: "user", selector: ".dropdown-edit-btn", popupSelector: ".dropdown-edit-btn" },
        "ai-message-actions": { type: "ai", selector: aiConfig.actionToggleSelector },
        "ai-message-retry-action": { type: "ai", selector: ".dropdown-retry-btn", popupSelector: ".dropdown-retry-btn" },
        "ai-message-feedback-action": { type: "ai", selector: ".feedback-btn[data-feedback-type='positive'], .feedback-btn", popupSelector: ".feedback-btn[data-feedback-type='positive'], .feedback-btn" },
        "ai-message-export-md": { type: "ai", selector: ".dropdown-export-md-btn", popupSelector: ".dropdown-export-md-btn" },
        "ai-message-export-word": { type: "ai", selector: ".dropdown-export-word-btn", popupSelector: ".dropdown-export-word-btn" },
        "ai-message-use-prompt": { type: "ai", selector: ".dropdown-copy-prompt-btn", popupSelector: ".dropdown-copy-prompt-btn" },
        "ai-message-open-email": { type: "ai", selector: ".dropdown-open-email-btn", popupSelector: ".dropdown-open-email-btn" },
        "ai-message-thoughts": { type: "ai", selector: ".thoughts-container" },
        "ai-message-citations": { type: "ai", selector: ".citations-container" }
    };

    return configs[stepId] || null;
}

function getLiveMessageRoot(type) {
    const selector = type === "user" ? ".message.user-message" : ".message.ai-message";
    const matches = getNonTutorialMatches(selector);
    return matches.length ? matches[matches.length - 1] : null;
}

function getExampleMessageRoot(type) {
    if (!tutorialMessageExamplesEl) {
        return null;
    }

    return tutorialMessageExamplesEl.querySelector(type === "user" ? ".tutorial-user-message" : ".tutorial-ai-message");
}

function getMessageStepElement(root, selector, requireVisible = true) {
    if (!root || !selector) {
        return null;
    }

    const target = root.querySelector(selector);
    if (!target) {
        return null;
    }

    if (!requireVisible) {
        return target;
    }

    const rect = target.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 ? target : null;
}

function getLiveMessageStepTarget(step, requireVisible = true) {
    const config = getMessageStepConfig(step?.id);
    if (!config) {
        return null;
    }

    const root = getLiveMessageRoot(config.type);
    return getMessageStepElement(root, config.selector, requireVisible);
}

function buildTutorialMessageExamplesMarkup() {
    const feedbackItems = Boolean(window.enableUserFeedback)
        ? `
                <li><hr class="dropdown-divider"></li>
                <li><a class="dropdown-item feedback-btn" href="#" data-feedback-type="positive"><i class="bi bi-hand-thumbs-up me-2"></i>Thumbs Up</a></li>
                <li><a class="dropdown-item feedback-btn" href="#" data-feedback-type="negative"><i class="bi bi-hand-thumbs-down me-2"></i>Thumbs Down</a></li>`
        : "";
    const thoughtsToggleHtml = window.appSettings?.enable_thoughts
        ? '<button class="btn btn-sm btn-link text-muted thoughts-toggle-btn" title="Show processing thoughts" aria-expanded="false" aria-controls="tutorial-thoughts-ai"><i class="bi bi-stars"></i></button>'
        : "";
    const thoughtsContainerHtml = window.appSettings?.enable_thoughts
        ? `
            <div id="tutorial-thoughts-ai" class="thoughts-container d-none mt-2 pt-2 border-top">
                <div class="thoughts-list">
                    <div class="thought-step small py-1"><i class="bi bi-search me-2 text-muted"></i><span>Checked the selected workspace for the latest onboarding notes.</span></div>
                    <div class="thought-step small py-1"><i class="bi bi-lightning me-2 text-muted"></i><span>Drafted a concise response with next steps and owner context.</span></div>
                </div>
            </div>`
        : "";

    return `
        <div class="tutorial-example-caption small text-muted mb-3">Tutorial examples appear only while the walkthrough is active.</div>
        <div class="message user-message tutorial-user-message mb-3" data-message-id="tutorial-user-message">
            <div class="message-content">
                <img src="/static/images/user-avatar.png" alt="User Avatar" class="avatar">
                <div class="message-bubble">
                    <div class="message-sender">You</div>
                    <div class="message-text"><p>Summarize the latest onboarding updates and draft a short reply I can send to the team.</p></div>
                    <div class="metadata-container mt-2 pt-2 border-top" id="tutorial-metadata-user" style="display: none;">
                        <div class="small text-muted">Prompt metadata shows exactly what was sent, which helps when you need to audit or reproduce a request.</div>
                    </div>
                    <div class="message-footer d-flex justify-content-between align-items-center mt-2">
                        <div class="d-flex align-items-center gap-2">
                            <div class="dropdown">
                                <button class="btn btn-sm btn-link text-muted" type="button" data-bs-toggle="dropdown" aria-expanded="false" title="More actions">
                                    <i class="bi bi-three-dots"></i>
                                </button>
                                <ul class="dropdown-menu dropdown-menu-start">
                                    <li><a class="dropdown-item dropdown-edit-btn" href="#"><i class="bi bi-pencil me-2"></i>Edit</a></li>
                                    <li><a class="dropdown-item dropdown-delete-btn" href="#"><i class="bi bi-trash me-2"></i>Delete</a></li>
                                    <li><a class="dropdown-item dropdown-retry-btn" href="#"><i class="bi bi-arrow-clockwise me-2"></i>Retry</a></li>
                                    <li><hr class="dropdown-divider"></li>
                                    <li><a class="dropdown-item dropdown-export-md-btn" href="#"><i class="bi bi-markdown me-2"></i>Export to Markdown</a></li>
                                    <li><a class="dropdown-item dropdown-export-word-btn" href="#"><i class="bi bi-file-earmark-word me-2"></i>Export to Word</a></li>
                                    <li><a class="dropdown-item dropdown-copy-prompt-btn" href="#"><i class="bi bi-clipboard-plus me-2"></i>Use as Prompt</a></li>
                                    <li><a class="dropdown-item dropdown-open-email-btn" href="#"><i class="bi bi-envelope me-2"></i>Open in Email</a></li>
                                </ul>
                            </div>
                            <button class="btn btn-sm btn-link text-muted copy-user-btn" title="Copy message"><i class="bi bi-copy"></i></button>
                            <button class="btn btn-sm btn-link text-muted mask-btn" title="Mask entire message"><i class="bi bi-back"></i></button>
                        </div>
                        <div class="d-flex align-items-center">
                            <button class="btn btn-sm btn-link text-muted metadata-toggle-btn" title="Show metadata" aria-expanded="false" aria-controls="tutorial-metadata-user"><i class="bi bi-info-circle"></i></button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        <div class="message ai-message tutorial-ai-message" data-message-id="tutorial-ai-message">
            <div class="message-content">
                <img src="/static/images/ai-avatar.png" alt="AI Avatar" class="avatar">
                <div class="message-bubble">
                    <div class="message-sender">AI <span style="color: #6c757d; font-size: 0.8em;">(tutorial example)</span></div>
                    <div class="message-text"><p>Here is a concise summary you can share, plus a short reply draft for your team.</p></div>
                    <div id="tutorial-citations-ai" style="display: none;">
                        <div class="citations-container" data-message-id="tutorial-ai-message">
                            <button class="btn btn-sm btn-outline-secondary me-2 mb-2">Employee Onboarding FAQ.pdf</button>
                            <button class="btn btn-sm btn-outline-secondary mb-2">Release Notes - March</button>
                        </div>
                    </div>
                    ${thoughtsContainerHtml}
                    <div class="metadata-container mt-2 pt-2 border-top" id="tutorial-metadata-ai" style="display: none;">
                        <div class="small text-muted">Metadata can show model context, timing, and grounding clues so you can validate where the answer came from and troubleshoot odd behavior.</div>
                    </div>
                    <div class="message-footer d-flex justify-content-between align-items-center mt-2">
                        <div class="d-flex align-items-center">
                            <div class="message-actions d-flex align-items-center gap-2">
                                <div class="dropdown">
                                    <button class="btn btn-sm btn-link text-muted" type="button" data-bs-toggle="dropdown" aria-expanded="false" title="More actions">
                                        <i class="bi bi-three-dots"></i>
                                    </button>
                                    <ul class="dropdown-menu dropdown-menu-start">
                                        <li><a class="dropdown-item dropdown-delete-btn" href="#"><i class="bi bi-trash me-2"></i>Delete</a></li>
                                        <li><a class="dropdown-item dropdown-retry-btn" href="#"><i class="bi bi-arrow-clockwise me-2"></i>Retry</a></li>
                                        ${feedbackItems}
                                        <li><hr class="dropdown-divider"></li>
                                        <li><a class="dropdown-item dropdown-export-md-btn" href="#"><i class="bi bi-markdown me-2"></i>Export to Markdown</a></li>
                                        <li><a class="dropdown-item dropdown-export-word-btn" href="#"><i class="bi bi-file-earmark-word me-2"></i>Export to Word</a></li>
                                        <li><a class="dropdown-item dropdown-copy-prompt-btn" href="#"><i class="bi bi-clipboard-plus me-2"></i>Use as Prompt</a></li>
                                        <li><a class="dropdown-item dropdown-open-email-btn" href="#"><i class="bi bi-envelope me-2"></i>Open in Email</a></li>
                                    </ul>
                                </div>
                                <button class="copy-btn btn btn-sm btn-link text-muted" title="Copy AI response as Markdown"><i class="bi bi-copy"></i></button>
                                <button class="mask-btn btn btn-sm btn-link text-muted" title="Mask entire message"><i class="bi bi-back"></i></button>
                            </div>
                        </div>
                        <div class="d-flex align-items-center gap-2">
                            ${thoughtsToggleHtml}
                            <button class="btn btn-sm btn-link text-muted citation-toggle-btn" title="Show sources" aria-expanded="false" aria-controls="tutorial-citations-ai"><i class="bi bi-journal-text"></i></button>
                            <button class="btn btn-sm btn-link text-muted metadata-info-btn" title="Show metadata" aria-expanded="false" aria-controls="tutorial-metadata-ai"><i class="bi bi-info-circle"></i></button>
                        </div>
                    </div>
                </div>
            </div>
        </div>`;
}

function ensureTutorialMessageExamples(step) {
    if (!shouldIncludeMessageTutorialStep(step)) {
        return;
    }

    if (tutorialMessageExamplesEl || getLiveMessageStepTarget(step, false)) {
        return;
    }

    const chatboxEl = document.getElementById("chatbox");
    if (!chatboxEl) {
        return;
    }

    const wrapper = document.createElement("div");
    wrapper.className = "tutorial-message-examples";
    wrapper.innerHTML = buildTutorialMessageExamplesMarkup();
    chatboxEl.appendChild(wrapper);
    tutorialMessageExamplesEl = wrapper;
}

function getExampleMessageStepTarget(step, requireVisible = true) {
    const config = getMessageStepConfig(step?.id);
    if (!config) {
        return null;
    }

    const root = getExampleMessageRoot(config.type);
    return getMessageStepElement(root, config.selector, requireVisible);
}

function getMessagePopupTarget(step, requireVisible = true) {
    if (!tutorialMessagePopupEl) {
        return null;
    }

    const config = getMessageStepConfig(step?.id);
    const target = config?.popupSelector
        ? tutorialMessagePopupEl.querySelector(config.popupSelector)
        : tutorialMessagePopupEl;

    if (!target) {
        return null;
    }

    if (!requireVisible) {
        return target;
    }

    const rect = target.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 ? target : null;
}

function getMessageStepTarget(step, requireVisible = true) {
    if (!isMessageTutorialStep(step?.id)) {
        return null;
    }

    if (MESSAGE_POPUP_STEP_IDS.includes(step.id)) {
        const popupTarget = getMessagePopupTarget(step, requireVisible);
        if (popupTarget) {
            return popupTarget;
        }
    }

    const liveTarget = getLiveMessageStepTarget(step, requireVisible);
    if (liveTarget) {
        return liveTarget;
    }

    return getExampleMessageStepTarget(step, requireVisible);
}

function getMessageRootForStep(step) {
    const config = getMessageStepConfig(step?.id);
    if (!config) {
        return null;
    }

    return getLiveMessageRoot(config.type) || getExampleMessageRoot(config.type);
}

function ensureMessageMetadataVisible() {
    const root = getMessageRootForStep({ id: "message-metadata" });
    const metadataContainer = root?.querySelector(".metadata-container");
    const metadataBtn = root?.querySelector(".metadata-info-btn, .metadata-toggle-btn");
    if (!metadataContainer) {
        return;
    }

    if (root.closest(".tutorial-message-examples")) {
        metadataContainer.style.display = "block";
        if (metadataBtn) {
            metadataBtn.setAttribute("aria-expanded", "true");
            metadataBtn.title = "Hide metadata";
            metadataBtn.innerHTML = '<i class="bi bi-chevron-up"></i>';
        }
        return;
    }

    if (metadataContainer.style.display === "none" && metadataBtn) {
        metadataBtn.click();
        registerTemporaryStateRestorer(() => {
            if (metadataContainer.style.display !== "none") {
                metadataBtn.click();
            }
        });
    }
}

function ensureMessageThoughtsVisible() {
    const root = getMessageRootForStep({ id: "ai-message-thoughts" });
    const thoughtsContainer = root?.querySelector(".thoughts-container");
    const thoughtsBtn = root?.querySelector(".thoughts-toggle-btn");
    if (!thoughtsContainer) {
        return;
    }

    if (root.closest(".tutorial-message-examples")) {
        thoughtsContainer.classList.remove("d-none");
        if (thoughtsBtn) {
            thoughtsBtn.setAttribute("aria-expanded", "true");
            thoughtsBtn.title = "Hide processing thoughts";
            thoughtsBtn.innerHTML = '<i class="bi bi-chevron-up"></i>';
        }
        return;
    }

    if (thoughtsContainer.classList.contains("d-none") && thoughtsBtn) {
        thoughtsBtn.click();
        registerTemporaryStateRestorer(() => {
            if (!thoughtsContainer.classList.contains("d-none")) {
                thoughtsBtn.click();
            }
        });
    }
}

function ensureMessageCitationsVisible() {
    const root = getMessageRootForStep({ id: "ai-message-citations" });
    const citationWrapper = root?.querySelector("[id^='tutorial-citations-'], [id^='citations-']");
    const citationsContainer = root?.querySelector(".citations-container");
    const citationBtn = root?.querySelector(".citation-toggle-btn");
    if (!citationWrapper || !citationsContainer) {
        return;
    }

    if (root.closest(".tutorial-message-examples")) {
        citationWrapper.style.display = "block";
        if (citationBtn) {
            citationBtn.setAttribute("aria-expanded", "true");
            citationBtn.title = "Hide sources";
            citationBtn.innerHTML = '<i class="bi bi-chevron-up"></i>';
        }
        return;
    }

    if (citationWrapper.style.display === "none" && citationBtn) {
        citationBtn.click();
        registerTemporaryStateRestorer(() => {
            if (citationWrapper.style.display !== "none") {
                citationBtn.click();
            }
        });
    }
}

function ensureTutorialMessageMenuPopup(step) {
    if (!step || !MESSAGE_POPUP_STEP_IDS.includes(step.id)) {
        return;
    }

    if (tutorialMessagePopupEl) {
        return;
    }

    const root = getMessageRootForStep(step);
    const toggle = root?.querySelector(".dropdown button[data-bs-toggle='dropdown']");
    const sourceMenu = root?.querySelector(".dropdown-menu");
    if (!root || !toggle || !sourceMenu) {
        return;
    }

    const toggleRect = toggle.getBoundingClientRect();
    const popup = sourceMenu.cloneNode(true);
    popup.classList.add("show", "tutorial-message-popup", "tutorial-force-popup");
    popup.style.position = "fixed";
    popup.style.display = "block";
    popup.style.left = `${Math.max(12, toggleRect.left)}px`;
    popup.style.top = `${Math.max(12, toggleRect.bottom + 8)}px`;

    document.body.appendChild(popup);
    tutorialMessagePopupEl = popup;

    requestAnimationFrame(() => {
        if (!tutorialMessagePopupEl) {
            return;
        }

        const popupRect = tutorialMessagePopupEl.getBoundingClientRect();
        const adjustedLeft = Math.min(
            Math.max(12, toggleRect.left),
            window.innerWidth - popupRect.width - 12
        );
        const adjustedTop = Math.min(toggleRect.bottom + 8, window.innerHeight - popupRect.height - 12);

        tutorialMessagePopupEl.style.left = `${Math.max(12, adjustedLeft)}px`;
        tutorialMessagePopupEl.style.top = `${Math.max(12, adjustedTop)}px`;
    });

    registerTemporaryStateRestorer(() => {
        if (tutorialMessagePopupEl) {
            tutorialMessagePopupEl.remove();
            tutorialMessagePopupEl = null;
        }
    });
}

function ensureQuickSearchVisible() {
    const searchContainer = document.getElementById("sidebar-search-container");
    const searchBtn = document.getElementById("sidebar-search-btn");
    if (!searchContainer) {
        return;
    }

    if (searchContainer.style.display === "none") {
        if (searchBtn) {
            searchBtn.click();
            registerTemporaryStateRestorer(() => {
                if (searchContainer.style.display !== "none") {
                    searchBtn.click();
                }
            });
        } else {
            showElementForTutorial(searchContainer, "block");
        }
    }
}

function ensureSidebarHeaderControlsVisible() {
    const chatConversations = window.chatConversations;
    const chatSidebarConversations = window.chatSidebarConversations;
    const settingsBtn = document.getElementById("sidebar-conversations-settings-btn");
    const searchBtn = document.getElementById("sidebar-search-btn");
    const actionsContainer = document.getElementById("conversations-actions");

    if (chatConversations && typeof chatConversations.isSelectionModeActive === "function" && chatConversations.isSelectionModeActive()) {
        if (typeof chatConversations.exitSelectionMode === "function") {
            chatConversations.exitSelectionMode();
        }
    }

    if (chatSidebarConversations && typeof chatSidebarConversations.setSidebarSelectionMode === "function") {
        chatSidebarConversations.setSidebarSelectionMode(false);
    }

    if (actionsContainer && window.getComputedStyle(actionsContainer).display !== "none") {
        const previousDisplay = actionsContainer.style.display;
        actionsContainer.style.display = "none";
        registerTemporaryStateRestorer(() => {
            actionsContainer.style.display = previousDisplay;
        });
    }

    showElementForTutorial(settingsBtn, "inline-flex");
    showElementForTutorial(searchBtn, "inline-flex");
}

function ensureConversationInfoVisible() {
    const chatConversations = window.chatConversations;
    const currentConversationId = chatConversations && typeof chatConversations.getCurrentConversationId === "function"
        ? chatConversations.getCurrentConversationId()
        : null;
    const sidebarConversationId = getTutorialConversationItem()?.getAttribute("data-conversation-id");
    const infoButton = document.getElementById("conversation-info-btn");

    if (!currentConversationId && sidebarConversationId && chatConversations && typeof chatConversations.selectConversation === "function") {
        Promise.resolve(chatConversations.selectConversation(sidebarConversationId)).catch((error) => {
            console.warn("chat-tutorial: failed to select tutorial conversation for info step", error);
        });
    }

    showElementForTutorial(infoButton, "inline-block");
}

function ensureSelectionModeVisible() {
    const chatConversations = window.chatConversations;
    const chatSidebarConversations = window.chatSidebarConversations;
    const firstSidebarConversation = getTutorialConversationItem();
    const conversationId = firstSidebarConversation?.getAttribute("data-conversation-id");
    if (!chatConversations || typeof chatConversations.isSelectionModeActive !== "function" || !conversationId) {
        return;
    }

    if (!chatConversations.isSelectionModeActive()) {
        chatConversations.toggleConversationSelection(conversationId);
        registerTemporaryStateRestorer(() => {
            if (typeof chatConversations.exitSelectionMode === "function") {
                chatConversations.exitSelectionMode();
            }
        });
    }

    const forcedBulkButtons = [
        document.getElementById("sidebar-export-selected-btn"),
        document.getElementById("sidebar-pin-selected-btn"),
        document.getElementById("sidebar-hide-selected-btn"),
        document.getElementById("sidebar-delete-selected-btn")
    ].filter(Boolean);

    const applyTutorialSelectionMode = () => {
        if (chatSidebarConversations && typeof chatSidebarConversations.setSidebarSelectionMode === "function") {
            chatSidebarConversations.setSidebarSelectionMode(true);
        }

        if (chatSidebarConversations && typeof chatSidebarConversations.updateSidebarConversationSelection === "function") {
            chatSidebarConversations.updateSidebarConversationSelection(conversationId, true);
        }

        if (chatSidebarConversations && typeof chatSidebarConversations.updateSidebarDeleteButton === "function") {
            chatSidebarConversations.updateSidebarDeleteButton(1);
        }

        forcedBulkButtons.forEach((button) => {
            if (button.style.display === "none" || !button.style.display) {
                button.style.display = "inline-flex";
            }
        });
    };

    applyTutorialSelectionMode();

    if (forcedBulkButtons.length) {
        const previousDisplays = forcedBulkButtons.map((button) => ({ button, display: button.style.display }));
        const selectionKeepAlive = window.setInterval(() => {
            if (currentStepIndex < 0 || tutorialSteps[currentStepIndex]?.id !== "conversation-bulk-actions") {
                return;
            }

            applyTutorialSelectionMode();
        }, 500);

        registerTemporaryStateRestorer(() => {
            window.clearInterval(selectionKeepAlive);
            previousDisplays.forEach(({ button, display }) => {
                button.style.display = display;
            });
        });
    }
}

function ensureAdvancedSearchVisible() {
    ensureQuickSearchVisible();

    const modalEl = document.getElementById("advancedSearchModal");
    if (!modalEl) {
        return;
    }

    if (!modalEl.classList.contains("show")) {
        if (window.chatSearchModal && typeof window.chatSearchModal.openAdvancedSearchModal === "function") {
            window.chatSearchModal.openAdvancedSearchModal();
        } else {
            const modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
            modalInstance.show();
        }

        modalEl.classList.add("tutorial-force-popup");
        window.setTimeout(() => {
            modalEl.classList.add("tutorial-force-popup");
            forceModalBackdropAboveTutorial();
        }, 0);

        registerTemporaryStateRestorer(() => {
            modalEl.classList.remove("tutorial-force-popup");
            const modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
            modalInstance.hide();
        });
    }
}

function ensureTutorialAdvancedSearchPopup() {
    if (tutorialAdvancedSearchEl) {
        return;
    }

    const modalDialog = document.querySelector("#advancedSearchModal .modal-dialog");
    if (!modalDialog) {
        return;
    }

    const popup = document.createElement("div");
    popup.className = "tutorial-advanced-search-popup tutorial-force-popup";
    popup.appendChild(modalDialog.cloneNode(true));

    document.body.appendChild(popup);
    tutorialAdvancedSearchEl = popup;

    registerTemporaryStateRestorer(() => {
        if (tutorialAdvancedSearchEl) {
            tutorialAdvancedSearchEl.remove();
            tutorialAdvancedSearchEl = null;
        }
    });
}

function ensureSingleConversationExportWizardVisible() {
    ensureSidebarConversationDropdownVisible();

    const firstSidebarConversation = getTutorialConversationItem();
    const conversationId = firstSidebarConversation?.getAttribute("data-conversation-id");
    const modalEl = document.getElementById("export-wizard-modal");
    if (!conversationId || !modalEl || !window.chatExport || typeof window.chatExport.openExportWizard !== "function") {
        return;
    }

    if (!modalEl.classList.contains("show")) {
        window.chatExport.openExportWizard([conversationId], true);
        modalEl.classList.add("tutorial-force-popup");
        window.setTimeout(() => {
            modalEl.classList.add("tutorial-force-popup");
            forceModalBackdropAboveTutorial();
        }, 0);
        registerTemporaryStateRestorer(() => {
            modalEl.classList.remove("tutorial-force-popup");
            const modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
            modalInstance.hide();
        });
    }
}

function isPopupStep(stepId) {
    return [...CONVERSATION_POPUP_STEP_IDS, ...MESSAGE_POPUP_STEP_IDS, "conversation-advanced-search-modal", "conversation-export-wizard"].includes(stepId);
}

function isDeferredPopupStep(stepId) {
    return ["conversation-export-wizard"].includes(stepId);
}

function forcePopupAboveTutorial(target) {
    const popupEl = target?.closest?.(".dropdown-menu, .modal") || target;
    if (!popupEl) {
        return;
    }

    popupEl.classList.add("tutorial-force-popup");
    if (popupEl.classList.contains("modal")) {
        forceModalBackdropAboveTutorial();
    }
    registerTemporaryStateRestorer(() => {
        popupEl.classList.remove("tutorial-force-popup");
    });
}

function hideTutorialHighlight() {
    if (highlightEl) {
        highlightEl.style.opacity = "0";
    }
}

function showTutorialHighlight() {
    if (highlightEl) {
        highlightEl.style.opacity = "1";
    }
}

function syncPopupTargetHighlight(step, target) {
    if (highlightedPopupTarget) {
        highlightedPopupTarget.classList.remove("tutorial-popup-target-highlight");
        highlightedPopupTarget = null;
    }

    if (![...CONVERSATION_POPUP_ITEM_STEP_IDS, ...MESSAGE_POPUP_ITEM_STEP_IDS].includes(step?.id) || !target) {
        showTutorialHighlight();
        return;
    }

    const popupTarget = target.closest(".dropdown-item") || target;
    popupTarget.classList.add("tutorial-popup-target-highlight");
    highlightedPopupTarget = popupTarget;
    hideTutorialHighlight();
}

function schedulePopupTargetRefresh(step, attemptsRemaining = 6) {
    if (!step) {
        return;
    }

    const refreshToken = popupRefreshToken;

    hideTutorialHighlight();

    window.setTimeout(() => {
        if (refreshToken !== popupRefreshToken) {
            return;
        }

        prepareStepTarget(step);

        const refreshedTarget = getTarget(step, { prepare: false, logMissing: false });
        const rect = refreshedTarget?.getBoundingClientRect?.();
        const isUnpositionedPopup = Boolean(rect && rect.width > 0 && rect.height > 0 && rect.top <= 1 && rect.left <= 1);

        if ((!refreshedTarget || isUnpositionedPopup) && attemptsRemaining > 0) {
            schedulePopupTargetRefresh(step, attemptsRemaining - 1);
            return;
        }

        if (refreshedTarget) {
            activeTarget = refreshedTarget;
            forcePopupAboveTutorial(refreshedTarget);
            syncPopupTargetHighlight(step, refreshedTarget);
            positionElements();
            return;
        }

        showTutorialHighlight();
        positionElements();
    }, 50);
}

function ensureSendButtonVisible() {
    const sendBtn = document.getElementById("send-btn");
    const input = document.getElementById("user-input");

    if (!sendBtn) {
        return;
    }

    if (!sendBtn.classList.contains("show")) {
        const hadHasContent = input ? input.classList.contains("has-content") : false;
        const previousPadding = input ? input.style.paddingRight : "";

        sendBtn.classList.add("show");
        if (input) {
            input.classList.add("has-content");
            input.style.paddingRight = "50px";
        }

        registerTemporaryStateRestorer(() => {
            sendBtn.classList.remove("show");
            if (input) {
                if (!hadHasContent) {
                    input.classList.remove("has-content");
                }
                input.style.paddingRight = previousPadding;
            }
        });
    }
}

function getTarget(step, options = {}) {
    const { prepare = true, requireVisible = true, logMissing = requireVisible } = options;
    if (!step) {
        return null;
    }

    if (prepare) {
        prepareStepTarget(step);
    }

    const conversationStepTarget = getConversationStepTarget(step, requireVisible);
    const messageStepTarget = getMessageStepTarget(step, requireVisible);
    const el = conversationStepTarget || messageStepTarget || findStepTarget(step, requireVisible);
    if (!el) {
        if (logMissing) {
            console.warn("chat-tutorial: selector not found", getStepSelectors(step));
        }
        return null;
    }

    if (requireVisible) {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) {
            if (logMissing) {
                console.warn("chat-tutorial: selector zero-size", getStepSelectors(step));
            }
            return null;
        }
    }

    return el;
}

function getStepScrollAnchor(step, target) {
    if (!step) {
        return target;
    }

    if (["conversation-actions", ...CONVERSATION_POPUP_STEP_IDS].includes(step.id)) {
        return getTutorialConversationItem() || getSidebarConversationDropdownToggle() || target;
    }

    if (["user-message-actions", ...USER_MESSAGE_POPUP_STEP_IDS].includes(step.id)) {
        return getMessageRootForStep({ id: "user-message-actions" }) || target;
    }

    if (["message-metadata", "message-copy", "message-mask", "ai-message-actions", ...AI_MESSAGE_POPUP_STEP_IDS, "ai-message-thoughts", "ai-message-citations"].includes(step.id)) {
        return getMessageRootForStep({ id: "ai-message-actions" }) || getMessageRootForStep(step) || target;
    }

    if (["conversation-advanced-search-modal", "conversation-export-wizard"].includes(step.id)) {
        return null;
    }

    return target;
}

function ensureTargetIsReady(step, target) {
    if (!target) {
        return;
    }

    if (!["conversation-actions", ...CONVERSATION_POPUP_STEP_IDS, "conversation-search-input", "conversation-advanced-search", "conversation-advanced-search-modal", "conversation-bulk-actions", "conversation-export-wizard", "user-message-actions", ...MESSAGE_POPUP_STEP_IDS].includes(step.id)) {
        restoreTemporaryState();

        if (["workspace-scope", "workspace-tags", "workspace-document", "workspace-lock"].includes(step.id)) {
            ensureDocumentsPanelVisible();
            target = getTarget(step, { prepare: false });
        }

        if (CONVERSATION_POPUP_STEP_IDS.includes(step.id)) {
            ensureSidebarConversationDropdownVisible();
            target = getTarget(step, { prepare: false });
        }

        if (["conversation-search-input", "conversation-advanced-search"].includes(step.id)) {
            ensureQuickSearchVisible();
            target = getTarget(step, { prepare: false });
        }

        if (step.id === "conversation-hidden-toggle") {
            ensureSidebarHeaderControlsVisible();
            target = getTarget(step, { prepare: false });
        }

        if (step.id === "conversation-bulk-actions") {
            ensureSelectionModeVisible();
            target = getTarget(step, { prepare: false });
        }

        if (step.id === "conversation-info") {
            ensureConversationInfoVisible();
            target = getTarget(step, { prepare: false });
        }

        if (step.id === "conversation-advanced-search-modal") {
            ensureTutorialAdvancedSearchPopup();
            target = getTarget(step, { prepare: false });
        }

        if (step.id === "conversation-export-wizard") {
            ensureSingleConversationExportWizardVisible();
            target = getTarget(step, { prepare: false });
        }

        if (step.id === "prompt-select") {
            ensurePromptPanelVisible();
            target = getTarget(step, { prepare: false });
        }

        if (step.id === "send-message") {
            ensureSendButtonVisible();
            target = getTarget(step, { prepare: false });
        }

        if (step.id === "message-metadata") {
            ensureMessageMetadataVisible();
            target = getTarget(step, { prepare: false });
        }

        if (step.id === "ai-message-thoughts") {
            ensureMessageThoughtsVisible();
            target = getTarget(step, { prepare: false });
        }

        if (step.id === "ai-message-citations") {
            ensureMessageCitationsVisible();
            target = getTarget(step, { prepare: false });
        }
    }

    const scrollAnchor = getStepScrollAnchor(step, target);
    if (scrollAnchor && typeof scrollAnchor.scrollIntoView === "function") {
        scrollAnchor.scrollIntoView({ block: "center", inline: "center", behavior: "instant" });
    }

    if (isDeferredPopupStep(step.id)) {
        schedulePopupTargetRefresh(step);
        return;
    }

    if (step.id === "conversation-search") {
        const searchBtn = document.getElementById("sidebar-search-btn");
        if (searchBtn) {
            searchBtn.click();
        }
    }

    if (CONVERSATION_POPUP_STEP_IDS.includes(step.id)) {
        ensureTutorialConversationMenuPopup(step);
        target = getTarget(step, { prepare: false, logMissing: false }) || target;
        activeTarget = target;
        forcePopupAboveTutorial(target);
        syncPopupTargetHighlight(step, target);
        schedulePopupTargetRefresh(step);
        return;
    }

    if (MESSAGE_POPUP_STEP_IDS.includes(step.id)) {
        ensureTutorialMessageMenuPopup(step);
        target = getTarget(step, { prepare: false, logMissing: false }) || target;
        activeTarget = target;
        forcePopupAboveTutorial(target);
        syncPopupTargetHighlight(step, target);
        schedulePopupTargetRefresh(step);
        return;
    }

    syncPopupTargetHighlight(step, null);

    if (["conversation-search-input", "conversation-advanced-search"].includes(step.id)) {
        ensureQuickSearchVisible();
    }

    if (step.id === "conversation-bulk-actions") {
        ensureSelectionModeVisible();
    }

    if (step.id === "message-metadata") {
        ensureMessageMetadataVisible();
    }

    if (step.id === "ai-message-thoughts") {
        ensureMessageThoughtsVisible();
    }

    if (step.id === "ai-message-citations") {
        ensureMessageCitationsVisible();
    }

    if (step.id === "conversation-advanced-search-modal") {
        ensureTutorialAdvancedSearchPopup();
        target = getTarget(step, { prepare: false, logMissing: false }) || target;
        activeTarget = target;
        forcePopupAboveTutorial(target);
    }

    if (step.id === "conversation-export-wizard") {
        ensureSingleConversationExportWizardVisible();
    }

    if (["workspace-scope", "workspace-tags", "workspace-document", "workspace-lock"].includes(step.id)) {
        ensureDocumentsPanelVisible();
    }

    if (step.id === "prompt-select") {
        ensurePromptPanelVisible();
    }

    if (step.id === "send-message") {
        ensureSendButtonVisible();
    }

    if (["conversation-actions", ...CONVERSATION_POPUP_STEP_IDS].includes(step.id)) {
        const dropdown = target.closest(".conversation-dropdown");
        if (dropdown) {
            dropdown.classList.add("tutorial-force-visible");
            forcedVisibleTarget = dropdown;
        }
    }
}

function filterVisibleSteps(allSteps) {
    const filtered = allSteps.filter((step) => getTarget(step, { prepare: false, requireVisible: false, logMissing: false }) || shouldIncludeMessageTutorialStep(step));
    console.log("chat-tutorial: filterVisibleSteps", { requested: allSteps.length, filtered: filtered.length, steps: filtered.map((s) => s.id) });
    return filtered;
}

function findNextStepIndex(startIndex, direction) {
    let idx = startIndex;
    while (idx >= 0 && idx < tutorialSteps.length) {
        const candidate = tutorialSteps[idx];
        if (getTarget(candidate, { prepare: false, requireVisible: false, logMissing: false }) || shouldIncludeMessageTutorialStep(candidate)) {
            return idx;
        }
        idx += direction;
    }
    return null;
}

function positionElements() {
    if (!activeTarget || !highlightEl || !cardEl) {
        return;
    }
    const rect = activeTarget.getBoundingClientRect();
    const viewportWidth = Math.max(baseOffset.width, window.innerWidth - baseOffset.left - EDGE_PADDING);
    const viewportHeight = Math.max(baseOffset.height, window.innerHeight - baseOffset.top - EDGE_PADDING);
    const top = Math.max(rect.top - HIGHLIGHT_PADDING - baseOffset.top, EDGE_PADDING);
    const left = Math.max(rect.left - HIGHLIGHT_PADDING - baseOffset.left, EDGE_PADDING);
    const width = Math.min(rect.width + HIGHLIGHT_PADDING * 2, viewportWidth - EDGE_PADDING * 2);
    const height = Math.min(rect.height + HIGHLIGHT_PADDING * 2, viewportHeight - EDGE_PADDING * 2);

    console.log("chat-tutorial: positionElements", {
        targetRect: rect.toJSON ? rect.toJSON() : rect,
        baseOffset,
        highlight: { top, left, width, height }
    });

    highlightEl.style.top = `${top}px`;
    highlightEl.style.left = `${left}px`;
    highlightEl.style.width = `${width}px`;
    highlightEl.style.height = `${height}px`;

    requestAnimationFrame(() => positionCard(rect));
}

function positionCard(targetRect) {
    const gap = 12;
    const viewportWidth = Math.max(baseOffset.width, window.innerWidth - baseOffset.left - EDGE_PADDING);
    const viewportHeight = Math.max(baseOffset.height, window.innerHeight - baseOffset.top - EDGE_PADDING);
    const step = tutorialSteps[currentStepIndex];

    cardEl.style.top = `${EDGE_PADDING}px`;
    cardEl.style.left = `${EDGE_PADDING}px`;

    const cardRect = cardEl.getBoundingClientRect();
    let top = targetRect.bottom - baseOffset.top + gap;
    let left = targetRect.left - baseOffset.left + targetRect.width / 2 - cardRect.width / 2;

    if (step && isPopupStep(step.id)) {
        const rightPlacementLeft = targetRect.right - baseOffset.left + gap;
        const leftPlacementLeft = targetRect.left - baseOffset.left - cardRect.width - gap;
        const centeredTop = targetRect.top - baseOffset.top + (targetRect.height / 2) - (cardRect.height / 2);

        if (rightPlacementLeft + cardRect.width <= viewportWidth - EDGE_PADDING) {
            left = rightPlacementLeft;
            top = centeredTop;
        } else if (leftPlacementLeft >= EDGE_PADDING) {
            left = leftPlacementLeft;
            top = centeredTop;
        }
    }

    if (top + cardRect.height > viewportHeight - EDGE_PADDING) {
        top = targetRect.top - baseOffset.top - cardRect.height - gap;
    }
    if (top < EDGE_PADDING) {
        top = Math.min(viewportHeight / 2 - cardRect.height / 2, viewportHeight - cardRect.height - EDGE_PADDING);
    }

    left = Math.max(EDGE_PADDING, Math.min(left, viewportWidth - cardRect.width - EDGE_PADDING));

    cardEl.style.top = `${top}px`;
    cardEl.style.left = `${left}px`;
}

function handleKeydown(event) {
    if (!layerEl) {
        return;
    }
    if (event.key === "Escape") {
        endTutorial(true);
    }
    if (event.key === "ArrowRight" || event.key === "Enter") {
        event.preventDefault();
        goToStep(currentStepIndex + 1);
    }
    if (event.key === "ArrowLeft") {
        event.preventDefault();
        goToStep(currentStepIndex - 1, -1);
    }
}

function endTutorial(storeDismissal) {
    if (storeDismissal) {
        localStorage.setItem(STORAGE_KEY, "dismissed");
    }

    popupRefreshToken += 1;

    document.removeEventListener("keydown", handleKeydown);
    window.removeEventListener("resize", positionElements, true);
    window.removeEventListener("scroll", positionElements, true);

    if (layerEl) {
        layerEl.remove();
    }

    layerEl = null;
    highlightEl = null;
    cardEl = null;
    currentStepIndex = -1;
    activeTarget = null;
    currentPhase = "nav";
    tutorialConversationId = null;

    restoreTemporaryState();
    restoreSidebarState();
}

function handleAction(action) {
    if (action === "skip") {
        endTutorial(true);
        return;
    }
    if (action === "back") {
        goToStep(currentStepIndex - 1, -1);
        return;
    }
    if (action === "next") {
        const nextIndex = currentStepIndex + 1;
        if (nextIndex >= tutorialSteps.length) {
            endTutorial(true);
            return;
        }
        goToStep(nextIndex);
    }
}

function renderCard(step) {
    const total = tutorialSteps.length;
    const isLast = currentStepIndex === total - 1;

    cardEl.className = "chat-tutorial-card card shadow";
    cardEl.innerHTML = `
        <div class="card-body p-3">
            <div class="d-flex justify-content-between align-items-center mb-2">
                <span class="badge bg-secondary badge-step">${currentStepIndex + 1}/${total}</span>
                <button type="button" class="btn-close" aria-label="Close tutorial"></button>
            </div>
            <h6 class="fw-semibold mb-1">${step.title}</h6>
            <p class="mb-3 small text-muted">${step.body}</p>
            <div class="tutorial-actions d-flex justify-content-between align-items-center gap-2">
                <div class="d-flex gap-2">
                    <button type="button" class="btn btn-outline-secondary btn-sm" data-action="back" ${currentStepIndex === 0 ? "disabled" : ""}>Back</button>
                    <button type="button" class="btn btn-primary btn-sm" data-action="next">${isLast ? "Finish" : "Next"}</button>
                </div>
                <button type="button" class="btn btn-link btn-sm" data-action="skip">Skip</button>
            </div>
        </div>
    `;

    const closeBtn = cardEl.querySelector(".btn-close");
    if (closeBtn) {
        closeBtn.addEventListener("click", () => endTutorial(true));
    }

    cardEl.querySelectorAll("[data-action]").forEach((btn) => {
        btn.addEventListener("click", (evt) => {
            evt.preventDefault();
            const action = evt.currentTarget.getAttribute("data-action");
            handleAction(action);
        });
    });
}

function goToStep(nextIndex, direction = 1) {
    if (!tutorialSteps.length) {
        console.warn("chat-tutorial: no steps loaded when attempting goToStep");
        return;
    }

    popupRefreshToken += 1;
    restoreTemporaryState();

    const candidateIndex = findNextStepIndex(nextIndex, direction > 0 ? 1 : -1);
    if (candidateIndex === null) {
        console.warn("chat-tutorial: no next step found", { nextIndex, direction });
        endTutorial(true);
        return;
    }

    currentStepIndex = candidateIndex;
    const step = tutorialSteps[currentStepIndex];
    activeTarget = isPopupStep(step.id)
        ? getTarget(step, { prepare: true, requireVisible: false, logMissing: false })
        : getTarget(step);

    if (!activeTarget) {
        console.warn("chat-tutorial: target not found for step", tutorialSteps[currentStepIndex]);
        endTutorial(true);
        return;
    }

    console.log("chat-tutorial: showing step", {
        index: currentStepIndex,
        id: step.id,
        phase: step.phase,
        selector: step.selector,
        selectorList: step.selectorList,
        targetRect: activeTarget?.getBoundingClientRect ? activeTarget.getBoundingClientRect().toJSON?.() || activeTarget.getBoundingClientRect() : null
    });
    ensureLayerForPhase(step.phase || "chat");

    ensureTargetIsReady(step, activeTarget);
    renderCard(step);
    positionElements();
}

function createLayer(boundsRect) {
    layerEl = document.createElement("div");
    layerEl.className = "chat-tutorial-layer";
    layerEl.style.top = `${boundsRect.top}px`;
    layerEl.style.left = `${boundsRect.left}px`;
    layerEl.style.width = `${boundsRect.width}px`;
    layerEl.style.height = `${boundsRect.height}px`;

    layerEl.style.right = "auto";
    layerEl.style.bottom = "auto";

    console.log("chat-tutorial: createLayer", { boundsRect });

    highlightEl = document.createElement("div");
    highlightEl.className = "chat-tutorial-highlight";
    highlightEl.setAttribute("aria-hidden", "true");

    cardEl = document.createElement("div");
    cardEl.className = "chat-tutorial-card card shadow";
    cardEl.setAttribute("role", "dialog");
    cardEl.setAttribute("aria-live", "polite");

    layerEl.appendChild(highlightEl);
    layerEl.appendChild(cardEl);

    document.body.appendChild(layerEl);

    document.addEventListener("keydown", handleKeydown);
    window.addEventListener("resize", positionElements, true);
    window.addEventListener("scroll", positionElements, true);
}

function ensureLayerForPhase(phase) {
    const targetPhase = phase || "chat";

    if (targetPhase === "nav") {
        ensureSidebarExpandedForTutorial();
    } else {
        restoreSidebarState();
    }

    if (layerEl && targetPhase === currentPhase) {
        console.log("chat-tutorial: reusing layer for phase", targetPhase);
        return;
    }

    const hostCandidates = targetPhase === "nav"
        ? [document.getElementById("left-pane"), document.querySelector("#sidebar-nav"), document.body]
        : [document.querySelector(".chat-container"), document.getElementById("right-pane"), document.getElementById("split-container"), document.body];

    let host = hostCandidates.find((el) => el && el.getBoundingClientRect().width > 20 && el.getBoundingClientRect().height > 20) || document.body;
    let boundsRect = host.getBoundingClientRect();

    if (boundsRect.width < 20 || boundsRect.height < 20) {
        boundsRect = new DOMRect(0, 0, window.innerWidth, window.innerHeight);
        host = document.documentElement || document.body;
        console.warn("chat-tutorial: host too small; falling back to viewport", { phase: targetPhase, host, boundsRect });
    }

    console.log("chat-tutorial: ensureLayerForPhase", { phase: targetPhase, host, boundsRect });
    baseOffset = {
        top: boundsRect.top,
        left: boundsRect.left,
        width: boundsRect.width,
        height: boundsRect.height
    };

    if (layerEl) {
        layerEl.remove();
    }
    createLayer(boundsRect);
    currentPhase = targetPhase;
}

function startTutorial(force) {
    console.log("Starting chat tutorial, force:", force);
    restoreTemporaryState();
    tutorialSteps = filterVisibleSteps(buildSteps());
    restoreTemporaryState();
    restoreSidebarState();

    if (!force && localStorage.getItem(STORAGE_KEY) === "dismissed") {
        console.log("Chat tutorial previously dismissed, skipping.");
        return;
    }
    if (!tutorialSteps.length) {
        console.warn("chat-tutorial: no steps available to show");
        return;
    }
    if (layerEl) {
        endTutorial(false);
    }

    ensureLayerForPhase(tutorialSteps[0]?.phase || "nav");

    const firstIndex = findNextStepIndex(0, 1);
    if (firstIndex === null) {
        console.warn("chat-tutorial: could not find first step");
        endTutorial(false);
        return;
    }

    console.log("chat-tutorial: launching first step", { firstIndex, id: tutorialSteps[firstIndex]?.id });
    goToStep(firstIndex);
}

export function initChatTutorial() {
    tutorialSteps = buildSteps();
    const launchBtn = document.getElementById("chat-tutorial-btn");
    const handleSidebarConversationsLoaded = () => updateTutorialLaunchVisibility(true);
    const startTutorialWhenReady = () => {
        if (isTutorialLaunchReady()) {
            startTutorial(false);
            return;
        }

        document.addEventListener("chat:sidebar-conversations-loaded", () => {
            startTutorial(false);
        }, { once: true });
    };

    if (!launchBtn) {
        return;
    }

    updateTutorialLaunchVisibility(false);
    document.addEventListener("chat:sidebar-conversations-loaded", handleSidebarConversationsLoaded, { once: true });

    const launchTooltip = bootstrap.Tooltip.getOrCreateInstance(launchBtn, {
        trigger: "hover",
        customClass: "chat-tutorial-tooltip",
        offset: [0, 132]
    });

    launchBtn.addEventListener("click", () => {
        launchTooltip.hide();
        launchBtn.blur();
        startTutorial(true);
    });

    if (!localStorage.getItem(STORAGE_KEY)) {
        setTimeout(startTutorialWhenReady, 800);
    }
}
