// chat-conversation-contents.js

import {
    extractPageNumbers,
    fetchConversationMetadata,
    getConversationDocumentTags,
} from "./chat-conversation-details.js";
import { isColorLight } from "./chat-utils.js";

const CONTENTS_LABEL_MAX_LENGTH = 72;
const DESKTOP_MEDIA_QUERY = "(min-width: 1200px)";
const TEMP_MESSAGE_PREFIX = "temp_user_";
const DRAWER_MODE_CONTENTS = "contents";
const DRAWER_MODE_DOCUMENTS = "documents";

const chatContainer = document.querySelector(".chat-container");
const chatbox = document.getElementById("chatbox");
const scrollContainer = document.getElementById("chat-messages-container");
const drawer = document.getElementById("conversation-contents-drawer");
const drawerTitle = document.getElementById("conversation-contents-title");
const drawerSubtitle = document.getElementById("conversation-contents-subtitle");
const contentsPanel = document.getElementById("conversation-contents-panel");
const list = document.getElementById("conversation-contents-list");
const emptyState = document.getElementById("conversation-contents-empty");
const contentsToggleButton = document.getElementById("conversation-contents-toggle");
const documentsToggleButton = document.getElementById("conversation-documents-toggle");
const closeButton = document.getElementById("conversation-contents-close");
const contentsModeButton = document.getElementById("conversation-contents-mode-contents");
const documentsModeButton = document.getElementById("conversation-contents-mode-documents");
const documentsPanel = document.getElementById("conversation-documents-panel");
const documentsList = document.getElementById("conversation-documents-list");
const documentsEmptyState = document.getElementById("conversation-documents-empty");
const documentsStatus = document.getElementById("conversation-documents-status");
const documentsCountBadge = document.getElementById("conversation-documents-count");
const desktopMediaQuery = window.matchMedia(DESKTOP_MEDIA_QUERY);

let contentsEntries = [];
let documentEntries = [];
let activeMessageId = "";
let drawerOpen = false;
let drawerMode = DRAWER_MODE_CONTENTS;
let rebuildScheduled = false;
let scrollUpdateScheduled = false;
let offcanvasInstance = null;
let highlightTimeout = null;
let restoreFocusAfterClose = true;
let metadataRequestToken = 0;
let documentLoadState = "idle";
let activeDocumentConversationId = "";
const autoOpenedDocumentConversationIds = new Set();

export function normalizeConversationContentsLabel(value, fallbackLabel = "User message") {
    const source = String(value || "").replace(/\r\n?/g, "\n");
    const firstMeaningfulLine = source
        .split("\n")
        .map(line => line
            .replace(/<[^>]*>/g, " ")
            .replace(/!\[[^\]]*]\([^)]*\)/g, " ")
            .replace(/\[([^\]]+)]\([^)]*\)/g, "$1")
            .replace(/^\s*\d+[.)]\s+/, "")
            .replace(/^[\s>*#`~\-+_]+/, "")
            .replace(/[*_`~]/g, "")
            .replace(/\s+/g, " ")
            .trim())
        .find(Boolean);
    const normalizedLabel = firstMeaningfulLine || fallbackLabel;

    if (normalizedLabel.length <= CONTENTS_LABEL_MAX_LENGTH) {
        return normalizedLabel;
    }

    return `${normalizedLabel.slice(0, CONTENTS_LABEL_MAX_LENGTH - 1).trimEnd()}…`;
}

function isPersistedUserMessage(messageElement) {
    const messageId = String(messageElement.dataset.messageId || "").trim();
    return (
        messageElement.dataset.conversationContentsRole === "user"
        && Boolean(messageId)
        && !messageId.startsWith(TEMP_MESSAGE_PREFIX)
    );
}

function getMessageLabel(messageElement, index) {
    const sourceText = messageElement.conversationContentsText;
    const messageText = messageElement.querySelector(".message-text");
    const firstTextBlock = messageText?.querySelector(
        "p, h1, h2, h3, h4, h5, h6, li, pre, blockquote"
    );
    const renderedText = firstTextBlock?.textContent || messageText?.textContent || "";
    return normalizeConversationContentsLabel(
        renderedText || sourceText,
        `User message ${index + 1}`
    );
}

function getCurrentConversationId() {
    const conversationId = window.chatConversations?.getCurrentConversationId?.()
        || window.currentConversationId
        || "";
    return String(conversationId || "").trim();
}

function setActiveEntry(messageId) {
    if (activeMessageId === messageId) {
        return;
    }

    activeMessageId = messageId;
    contentsEntries.forEach(entry => {
        if (entry.messageId === messageId) {
            entry.button.setAttribute("aria-current", "location");
        } else {
            entry.button.removeAttribute("aria-current");
        }
    });
}

function findNearestEntry() {
    if (!scrollContainer || contentsEntries.length === 0) {
        return null;
    }

    const targetOffset = scrollContainer.scrollTop + 24;
    let low = 0;
    let high = contentsEntries.length - 1;

    while (low < high) {
        const middle = Math.ceil((low + high) / 2);
        if (contentsEntries[middle].message.offsetTop <= targetOffset) {
            low = middle;
        } else {
            high = middle - 1;
        }
    }

    return contentsEntries[low];
}

function updateActiveEntry() {
    scrollUpdateScheduled = false;
    const nearestEntry = findNearestEntry();
    setActiveEntry(nearestEntry?.messageId || "");
}

function scheduleActiveEntryUpdate() {
    if (scrollUpdateScheduled) {
        return;
    }

    scrollUpdateScheduled = true;
    window.requestAnimationFrame(updateActiveEntry);
}

function getDrawerTriggerButton(mode = drawerMode) {
    return mode === DRAWER_MODE_DOCUMENTS ? documentsToggleButton : contentsToggleButton;
}

function syncDrawerModeControls() {
    const documentsAvailable = documentEntries.length > 0;
    const contentsActive = drawerMode === DRAWER_MODE_CONTENTS;
    const documentsActive = drawerMode === DRAWER_MODE_DOCUMENTS;

    contentsModeButton?.classList.toggle("active", contentsActive);
    contentsModeButton?.setAttribute("aria-pressed", String(contentsActive));
    documentsModeButton?.classList.toggle("active", documentsActive);
    documentsModeButton?.setAttribute("aria-pressed", String(documentsActive));
    if (documentsModeButton) {
        documentsModeButton.disabled = !documentsAvailable && documentLoadState !== "loading";
    }

    contentsToggleButton?.classList.toggle("active", drawerOpen && contentsActive);
    documentsToggleButton?.classList.toggle("active", drawerOpen && documentsActive);
    contentsToggleButton?.setAttribute("aria-expanded", String(drawerOpen && contentsActive));
    documentsToggleButton?.setAttribute("aria-expanded", String(drawerOpen && documentsActive));

    if (drawerTitle) {
        drawerTitle.textContent = contentsActive ? "Conversation contents" : "Used documents";
    }
    if (drawerSubtitle) {
        drawerSubtitle.textContent = contentsActive
            ? "Jump to a user message"
            : "Documents cited in this conversation";
    }

    contentsPanel?.classList.toggle("d-none", !contentsActive);
    documentsPanel?.classList.toggle("d-none", !documentsActive);
}

function setDrawerMode(mode) {
    const requestedMode = mode === DRAWER_MODE_DOCUMENTS ? DRAWER_MODE_DOCUMENTS : DRAWER_MODE_CONTENTS;
    if (requestedMode === DRAWER_MODE_DOCUMENTS && documentEntries.length === 0 && documentLoadState !== "loading") {
        drawerMode = contentsEntries.length > 0 ? DRAWER_MODE_CONTENTS : DRAWER_MODE_DOCUMENTS;
    } else if (requestedMode === DRAWER_MODE_CONTENTS && contentsEntries.length === 0 && documentEntries.length > 0) {
        drawerMode = DRAWER_MODE_DOCUMENTS;
    } else {
        drawerMode = requestedMode;
    }
    syncDrawerModeControls();
}

function updateDrawerTriggers() {
    const hasContents = contentsEntries.length > 0;
    const hasDocuments = documentEntries.length > 0;

    if (contentsToggleButton) {
        contentsToggleButton.classList.toggle("d-none", !hasContents);
        contentsToggleButton.disabled = !hasContents;
    }
    if (documentsToggleButton) {
        documentsToggleButton.classList.toggle("d-none", !hasDocuments);
        documentsToggleButton.disabled = !hasDocuments;
    }

    if (documentsCountBadge) {
        documentsCountBadge.textContent = String(documentEntries.length);
        documentsCountBadge.classList.toggle("d-none", !hasDocuments);
    }

    if (drawerMode === DRAWER_MODE_CONTENTS && !hasContents && hasDocuments) {
        setDrawerMode(DRAWER_MODE_DOCUMENTS);
    } else if (drawerMode === DRAWER_MODE_DOCUMENTS && !hasDocuments && hasContents) {
        setDrawerMode(DRAWER_MODE_CONTENTS);
    } else {
        syncDrawerModeControls();
    }

    if (!hasContents && !hasDocuments) {
        closeDrawer({ restoreFocus: false });
    }
}

function closeDrawer({ restoreFocus = true } = {}) {
    if (!drawerOpen) {
        return;
    }

    if (desktopMediaQuery.matches) {
        drawerOpen = false;
        chatContainer?.classList.remove("conversation-contents-open");
        drawer?.setAttribute("aria-hidden", "true");
        syncDrawerModeControls();
        if (restoreFocus) {
            getDrawerTriggerButton()?.focus();
        }
        return;
    }

    restoreFocusAfterClose = restoreFocus;
    offcanvasInstance?.hide();
}

function focusActiveDrawerContent() {
    if (drawerMode === DRAWER_MODE_CONTENTS) {
        list?.querySelector("button")?.focus();
        return;
    }

    documentsList?.querySelector(".conversation-documents-entry")?.focus();
}

function openDrawer(mode = drawerMode) {
    const requestedMode = mode === DRAWER_MODE_DOCUMENTS ? DRAWER_MODE_DOCUMENTS : DRAWER_MODE_CONTENTS;
    const hasRequestedEntries = requestedMode === DRAWER_MODE_DOCUMENTS
        ? documentEntries.length > 0
        : contentsEntries.length > 0;
    const hasFallbackEntries = requestedMode === DRAWER_MODE_DOCUMENTS
        ? contentsEntries.length > 0
        : documentEntries.length > 0;

    if (!drawer || (!hasRequestedEntries && !hasFallbackEntries)) {
        return;
    }

    setDrawerMode(hasRequestedEntries ? requestedMode : (
        requestedMode === DRAWER_MODE_DOCUMENTS ? DRAWER_MODE_CONTENTS : DRAWER_MODE_DOCUMENTS
    ));
    drawerOpen = true;
    syncDrawerModeControls();

    if (desktopMediaQuery.matches) {
        chatContainer?.classList.add("conversation-contents-open");
        drawer.setAttribute("aria-hidden", "false");
        focusActiveDrawerContent();
        return;
    }

    offcanvasInstance?.show();
}

function toggleDrawer(mode = drawerMode) {
    const requestedMode = mode === DRAWER_MODE_DOCUMENTS ? DRAWER_MODE_DOCUMENTS : DRAWER_MODE_CONTENTS;
    if (drawerOpen && drawerMode === requestedMode) {
        closeDrawer();
    } else {
        openDrawer(requestedMode);
    }
}

function navigateToMessage(entry) {
    const messageElement = entry.message;
    messageElement.scrollIntoView({ behavior: "smooth", block: "start" });
    messageElement.tabIndex = -1;
    messageElement.focus({ preventScroll: true });
    messageElement.classList.remove("conversation-contents-destination");
    window.requestAnimationFrame(() => {
        messageElement.classList.add("conversation-contents-destination");
    });

    window.clearTimeout(highlightTimeout);
    highlightTimeout = window.setTimeout(() => {
        messageElement.classList.remove("conversation-contents-destination");
    }, 1800);
    setActiveEntry(entry.messageId);

    if (!desktopMediaQuery.matches) {
        closeDrawer({ restoreFocus: false });
    }
}

function createEntry(messageElement, index) {
    const messageId = String(messageElement.dataset.messageId || "");
    const listItem = document.createElement("li");
    const button = document.createElement("button");

    button.type = "button";
    button.className = "btn btn-link text-decoration-none conversation-contents-entry";
    button.textContent = getMessageLabel(messageElement, index);
    button.title = button.textContent;
    button.dataset.messageId = messageId;
    button.addEventListener("click", () => navigateToMessage({
        button,
        message: messageElement,
        messageId
    }));
    listItem.appendChild(button);

    return {
        button,
        listItem,
        message: messageElement,
        messageId
    };
}

export function rebuildConversationContents() {
    rebuildScheduled = false;
    if (!chatbox || !list || !emptyState || !contentsToggleButton) {
        return;
    }

    const messages = Array.from(
        chatbox.querySelectorAll('.message[data-conversation-contents-role="user"]')
    ).filter(isPersistedUserMessage);

    const previousActiveMessageId = activeMessageId;
    const focusedMessageId = list.contains(document.activeElement)
        ? String(document.activeElement.dataset.messageId || "")
        : "";
    list.replaceChildren();
    contentsEntries = messages.map(createEntry);
    contentsEntries.forEach(entry => list.appendChild(entry.listItem));
    activeMessageId = "";
    if (contentsEntries.some(entry => entry.messageId === previousActiveMessageId)) {
        setActiveEntry(previousActiveMessageId);
    }
    if (focusedMessageId) {
        contentsEntries
            .find(entry => entry.messageId === focusedMessageId)
            ?.button.focus({ preventScroll: true });
    }

    const hasEntries = contentsEntries.length > 0;
    emptyState.classList.toggle("d-none", hasEntries);

    if (!hasEntries) {
        setActiveEntry("");
        updateDrawerTriggers();
        return;
    }

    updateDrawerTriggers();
    scheduleActiveEntryUpdate();
}

function getScopeIcon(scope) {
    switch (scope) {
        case "personal": return "person";
        case "group": return "people";
        case "public": return "globe";
        default: return "question-circle";
    }
}

function createClassificationBadge(classification) {
    const label = String(classification || "None");
    const badge = document.createElement("span");
    badge.className = "badge conversation-documents-classification";
    badge.textContent = label;

    const allCategories = window.classification_categories || [];
    const category = allCategories.find(cat => cat.label === label);
    if (category?.color) {
        badge.style.backgroundColor = category.color;
        badge.classList.add(isColorLight(category.color) ? "text-dark" : "text-white");
    } else {
        badge.classList.add("bg-warning", "text-dark");
        badge.title = `Definition for "${label}" not found`;
    }

    return badge;
}

function createDocumentMetaLine(iconName, text) {
    const line = document.createElement("div");
    line.className = "small text-muted conversation-documents-meta-line";

    const icon = document.createElement("i");
    icon.className = `bi bi-${iconName} me-1`;
    icon.setAttribute("aria-hidden", "true");

    const textNode = document.createElement("span");
    textNode.textContent = text;

    line.append(icon, textNode);
    return line;
}

function createDocumentEntry(doc) {
    const chunkIds = Array.isArray(doc?.chunk_ids) ? doc.chunk_ids : [];
    const chunkPages = extractPageNumbers(chunkIds);
    const chunkCount = chunkIds.length;
    const documentId = String(doc?.document_id || "Unknown Document");
    const documentTitle = String(doc?.title || documentId);
    const scopeType = String(doc?.scope?.type || "Unknown");
    const scopeName = String(doc?.scope?.name || doc?.scope?.id || "Unknown");

    const listItem = document.createElement("li");
    const entry = document.createElement("article");
    entry.className = "conversation-documents-entry border rounded";
    entry.tabIndex = -1;

    const header = document.createElement("div");
    header.className = "d-flex justify-content-between align-items-start gap-2 mb-2";

    const title = document.createElement("div");
    title.className = "fw-semibold text-truncate conversation-documents-title";
    title.title = documentTitle;
    title.textContent = documentTitle;

    header.append(title, createClassificationBadge(doc?.classification));
    entry.appendChild(header);
    entry.appendChild(createDocumentMetaLine(
        "file-earmark",
        `${chunkCount} chunk${chunkCount !== 1 ? "s" : ""}${chunkPages.length > 0 ? ` (Pages: ${chunkPages.join(", ")})` : ""}`
    ));
    entry.appendChild(createDocumentMetaLine(
        getScopeIcon(scopeType),
        `${scopeType} scope: ${scopeName}`
    ));

    if (doc?.title && doc.title !== doc.document_id) {
        entry.appendChild(createDocumentMetaLine("hash", `ID: ${documentId}`));
    }

    listItem.appendChild(entry);
    return {
        listItem,
        documentId,
    };
}

function setDocumentsStatus(message, isError = false) {
    if (!documentsStatus) {
        return;
    }

    documentsStatus.textContent = message;
    documentsStatus.classList.toggle("d-none", !message);
    documentsStatus.classList.toggle("text-danger", Boolean(isError));
    documentsStatus.classList.toggle("text-muted", !isError);
}

function renderConversationDocuments(documents) {
    if (!documentsList || !documentsEmptyState) {
        return;
    }

    documentsList.replaceChildren();
    documentEntries = documents.map(createDocumentEntry);
    documentEntries.forEach(entry => documentsList.appendChild(entry.listItem));

    const hasDocuments = documentEntries.length > 0;
    documentsEmptyState.classList.toggle("d-none", hasDocuments || documentLoadState === "loading");
    setDocumentsStatus("");
    updateDrawerTriggers();
}

async function refreshConversationDocuments(options = {}) {
    const conversationId = String(options.conversationId || getCurrentConversationId()).trim();
    const requestToken = ++metadataRequestToken;
    const autoOpen = Boolean(options.autoOpen);
    const conversationChanged = conversationId !== activeDocumentConversationId;

    activeDocumentConversationId = conversationId;
    if (!conversationId) {
        documentLoadState = "idle";
        renderConversationDocuments([]);
        return;
    }

    documentLoadState = "loading";
    if (conversationChanged) {
        documentEntries = [];
        documentsList?.replaceChildren();
        setDocumentsStatus("");
        updateDrawerTriggers();
    }
    documentsEmptyState?.classList.add("d-none");
    if (drawerMode === DRAWER_MODE_DOCUMENTS) {
        setDocumentsStatus("Loading used documents...");
    }

    try {
        const metadata = await fetchConversationMetadata(conversationId);
        if (requestToken !== metadataRequestToken || conversationId !== activeDocumentConversationId) {
            return;
        }

        documentLoadState = "ready";
        const documents = getConversationDocumentTags(metadata);
        renderConversationDocuments(documents);

        if (
            autoOpen
            && documents.length > 0
            && conversationId === getCurrentConversationId()
            && !autoOpenedDocumentConversationIds.has(conversationId)
        ) {
            autoOpenedDocumentConversationIds.add(conversationId);
            openDrawer(DRAWER_MODE_DOCUMENTS);
        }
    } catch (error) {
        if (requestToken !== metadataRequestToken || conversationId !== activeDocumentConversationId) {
            return;
        }

        documentLoadState = "error";
        documentEntries = [];
        documentsList?.replaceChildren();
        documentsEmptyState?.classList.add("d-none");
        setDocumentsStatus("Unable to load used documents.", true);
        console.warn("Failed to load conversation documents:", error);
        updateDrawerTriggers();
    }
}

function scheduleRebuild() {
    if (rebuildScheduled) {
        return;
    }

    rebuildScheduled = true;
    window.requestAnimationFrame(rebuildConversationContents);
}

function handleViewportChange() {
    if (drawer?.classList.contains("show")) {
        offcanvasInstance?.hide();
    }
    chatContainer?.classList.remove("conversation-contents-open");
    drawerOpen = false;
    drawer?.setAttribute("aria-hidden", "true");
    syncDrawerModeControls();
}

function mutationAffectsContents(mutations) {
    return mutations.some(mutation => {
        if (mutation.type === "attributes") {
            return mutation.target?.dataset?.conversationContentsRole === "user";
        }

        const targetElement = mutation.target.nodeType === Node.ELEMENT_NODE
            ? mutation.target
            : mutation.target.parentElement;
        if (targetElement?.closest?.('.message[data-conversation-contents-role="user"]')) {
            return true;
        }

        return [...mutation.addedNodes, ...mutation.removedNodes].some(node => (
            node.nodeType === Node.ELEMENT_NODE
            && (
                node.matches?.('.message[data-conversation-contents-role="user"]')
                || node.querySelector?.('.message[data-conversation-contents-role="user"]')
            )
        ));
    });
}

function handleMessageMutations(mutations) {
    if (mutationAffectsContents(mutations)) {
        scheduleRebuild();
    }
}

function initializeConversationContents() {
    if (!chatbox || !drawer || !list || !contentsToggleButton || !closeButton) {
        return;
    }

    if (typeof bootstrap !== "undefined") {
        offcanvasInstance = bootstrap.Offcanvas.getOrCreateInstance(drawer, {
            backdrop: true,
            keyboard: true,
            scroll: false
        });
        drawer.addEventListener("shown.bs.offcanvas", () => {
            drawerOpen = true;
            drawer.setAttribute("aria-hidden", "false");
            syncDrawerModeControls();
        });
        drawer.addEventListener("hidden.bs.offcanvas", () => {
            drawerOpen = false;
            drawer.setAttribute("aria-hidden", "true");
            syncDrawerModeControls();
            if (restoreFocusAfterClose) {
                getDrawerTriggerButton()?.focus();
            }
            restoreFocusAfterClose = true;
        });
    }

    contentsToggleButton.addEventListener("click", () => toggleDrawer(DRAWER_MODE_CONTENTS));
    documentsToggleButton?.addEventListener("click", () => toggleDrawer(DRAWER_MODE_DOCUMENTS));
    contentsModeButton?.addEventListener("click", () => {
        setDrawerMode(DRAWER_MODE_CONTENTS);
    });
    documentsModeButton?.addEventListener("click", () => {
        if (documentEntries.length > 0 || documentLoadState === "loading") {
            setDrawerMode(DRAWER_MODE_DOCUMENTS);
        }
    });
    closeButton.addEventListener("click", () => closeDrawer());
    scrollContainer?.addEventListener("scroll", scheduleActiveEntryUpdate, { passive: true });
    desktopMediaQuery.addEventListener("change", handleViewportChange);
    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && drawerOpen && desktopMediaQuery.matches) {
            event.preventDefault();
            closeDrawer();
        }
    });
    window.addEventListener("chat:conversation-context-changed", event => {
        void refreshConversationDocuments({
            conversationId: event.detail?.conversationId || "",
            autoOpen: false,
        });
    });
    window.addEventListener("chat:conversation-documents-refresh", event => {
        const conversationId = String(event.detail?.conversationId || getCurrentConversationId()).trim();
        if (!conversationId || conversationId !== getCurrentConversationId()) {
            return;
        }
        void refreshConversationDocuments({
            conversationId,
            autoOpen: Boolean(event.detail?.autoOpen),
        });
    });

    const messageObserver = new MutationObserver(handleMessageMutations);
    messageObserver.observe(chatbox, {
        attributes: true,
        attributeFilter: ["data-message-id"],
        characterData: true,
        childList: true,
        subtree: true
    });

    rebuildConversationContents();
    void refreshConversationDocuments();
}

initializeConversationContents();
