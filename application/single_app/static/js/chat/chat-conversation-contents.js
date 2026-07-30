// chat-conversation-contents.js

const CONTENTS_LABEL_MAX_LENGTH = 72;
const DESKTOP_MEDIA_QUERY = "(min-width: 1200px)";
const TEMP_MESSAGE_PREFIX = "temp_user_";

const chatContainer = document.querySelector(".chat-container");
const chatbox = document.getElementById("chatbox");
const scrollContainer = document.getElementById("chat-messages-container");
const drawer = document.getElementById("conversation-contents-drawer");
const list = document.getElementById("conversation-contents-list");
const emptyState = document.getElementById("conversation-contents-empty");
const toggleButton = document.getElementById("conversation-contents-toggle");
const closeButton = document.getElementById("conversation-contents-close");
const desktopMediaQuery = window.matchMedia(DESKTOP_MEDIA_QUERY);

let contentsEntries = [];
let activeMessageId = "";
let drawerOpen = false;
let rebuildScheduled = false;
let scrollUpdateScheduled = false;
let offcanvasInstance = null;
let highlightTimeout = null;
let restoreFocusAfterClose = true;

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

function closeDrawer({ restoreFocus = true } = {}) {
    if (!drawerOpen) {
        return;
    }

    if (desktopMediaQuery.matches) {
        drawerOpen = false;
        chatContainer?.classList.remove("conversation-contents-open");
        drawer?.setAttribute("aria-hidden", "true");
        toggleButton?.setAttribute("aria-expanded", "false");
        if (restoreFocus) {
            toggleButton?.focus();
        }
        return;
    }

    restoreFocusAfterClose = restoreFocus;
    offcanvasInstance?.hide();
}

function openDrawer() {
    if (!drawer || contentsEntries.length === 0) {
        return;
    }

    drawerOpen = true;
    toggleButton?.setAttribute("aria-expanded", "true");

    if (desktopMediaQuery.matches) {
        chatContainer?.classList.add("conversation-contents-open");
        drawer.setAttribute("aria-hidden", "false");
        list?.querySelector("button")?.focus();
        return;
    }

    offcanvasInstance?.show();
}

function toggleDrawer() {
    if (drawerOpen) {
        closeDrawer();
    } else {
        openDrawer();
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
    if (!chatbox || !list || !emptyState || !toggleButton) {
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
    toggleButton.classList.toggle("d-none", !hasEntries);
    toggleButton.disabled = !hasEntries;
    emptyState.classList.toggle("d-none", hasEntries);

    if (!hasEntries) {
        closeDrawer({ restoreFocus: false });
        setActiveEntry("");
        return;
    }

    scheduleActiveEntryUpdate();
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
    toggleButton?.setAttribute("aria-expanded", "false");
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
    if (!chatbox || !drawer || !list || !toggleButton || !closeButton) {
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
            toggleButton.setAttribute("aria-expanded", "true");
        });
        drawer.addEventListener("hidden.bs.offcanvas", () => {
            drawerOpen = false;
            drawer.setAttribute("aria-hidden", "true");
            toggleButton.setAttribute("aria-expanded", "false");
            if (restoreFocusAfterClose) {
                toggleButton.focus();
            }
            restoreFocusAfterClose = true;
        });
    }

    toggleButton.addEventListener("click", toggleDrawer);
    closeButton.addEventListener("click", () => closeDrawer());
    scrollContainer?.addEventListener("scroll", scheduleActiveEntryUpdate, { passive: true });
    desktopMediaQuery.addEventListener("change", handleViewportChange);
    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && drawerOpen && desktopMediaQuery.matches) {
            event.preventDefault();
            closeDrawer();
        }
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
}

initializeConversationContents();
