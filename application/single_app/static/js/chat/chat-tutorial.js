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
let baseOffset = { top: 0, left: 0, width: window.innerWidth, height: window.innerHeight };
let currentPhase = "nav";

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
            selector: "#conversations-list",
            title: "Conversation list",
            body: "Switch between existing chats. Hover to reveal actions or multi-select to bulk pin, hide, or delete.",
            phase: "nav"
        },
        {
            id: "conversation-actions",
            selector: ".sidebar-conversation-item .conversation-dropdown button",
            title: "Conversation actions",
            body: "Use the three-dot menu to view details, pin, hide, rename, or delete a conversation.",
            phase: "nav"
        },
        {
            id: "conversation-info",
            selector: "#conversation-info-btn",
            title: "Conversation details",
            body: "View metadata, shared files, and classifications for the current chat.",
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
            body: "Pick a saved prompt or template to shape the assistant's response.",
            phase: "chat"
        },
        {
            id: "agents",
            selector: "#enable-agents-btn",
            title: "Agents and model toggle",
            body: "Enable agents to route tasks or use skills. The toggle selects whether the agent/model dropdown shows agents or models.",
            phase: "chat"
        },
        {
            id: "agent-model-select",
            selectorList: ["#agent-select", "#model-select"],
            title: "Agents or models",
            body: "Pick the agent or model to run, based on the toggle to the left. Agent and model options are determined by the conversation's workspace scope (personal, group, or public).",
            phase: "chat"
        },
        {
            id: "tts",
            selector: "#tts-autoplay-toggle-btn",
            title: "Voice replies",
            body: "Have responses read aloud automatically when enabled.",
            phase: "chat"
        },
        {
            id: "streaming",
            selector: "#streaming-toggle-btn",
            title: "Streaming",
            body: "Choose live streaming or full replies after processing.",
            phase: "chat"
        },
        {
            id: "reasoning",
            selector: "#reasoning-toggle-btn",
            title: "Reasoning effort",
            body: "Adjust reasoning depth and cost for more or less thorough answers.",
            phase: "chat"
        },
        {
            id: "chat-input",
            selector: "#user-input",
            title: "Type or dictate",
            body: "Enter your question, paste snippets, or use speech input when enabled.",
            phase: "chat"
        }
    ];
}

function getTarget(step) {
    const selectors = step?.selectorList || (step?.selector ? [step.selector] : []);
    let el = null;
    for (const sel of selectors) {
        el = document.querySelector(sel);
        if (el) {
            break;
        }
    }
    if (!el) {
        console.warn("chat-tutorial: selector not found", selectors);
        return null;
    }
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) {
        console.warn("chat-tutorial: selector zero-size", selectors);
        return null;
    }
    return el;
}

function ensureTargetIsReady(step, target) {
    if (!target) {
        return;
    }

    if (typeof target.scrollIntoView === "function") {
        target.scrollIntoView({ block: "center", inline: "center", behavior: "instant" });
    }

    if (step.id === "conversation-actions") {
        const dropdown = target.closest(".conversation-dropdown");
        if (dropdown) {
            dropdown.classList.add("tutorial-force-visible");
            forcedVisibleTarget = dropdown;
        }
    } else if (forcedVisibleTarget) {
        forcedVisibleTarget.classList.remove("tutorial-force-visible");
        forcedVisibleTarget = null;
    }
}

function filterVisibleSteps(allSteps) {
    const filtered = allSteps.filter((step) => getTarget(step));
    console.log("chat-tutorial: filterVisibleSteps", { requested: allSteps.length, filtered: filtered.length, steps: filtered.map((s) => s.id) });
    return filtered;
}

function findNextStepIndex(startIndex, direction) {
    let idx = startIndex;
    while (idx >= 0 && idx < tutorialSteps.length) {
        const candidate = tutorialSteps[idx];
        if (getTarget(candidate)) {
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
    const top = Math.max(rect.top - HIGHLIGHT_PADDING - baseOffset.top, EDGE_PADDING);
    const left = Math.max(rect.left - HIGHLIGHT_PADDING - baseOffset.left, EDGE_PADDING);
    const width = Math.min(rect.width + HIGHLIGHT_PADDING * 2, baseOffset.width - EDGE_PADDING * 2);
    const height = Math.min(rect.height + HIGHLIGHT_PADDING * 2, baseOffset.height - EDGE_PADDING * 2);

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
    const viewportWidth = baseOffset.width;
    const viewportHeight = baseOffset.height;

    cardEl.style.top = `${EDGE_PADDING}px`;
    cardEl.style.left = `${EDGE_PADDING}px`;

    const cardRect = cardEl.getBoundingClientRect();
    let top = targetRect.bottom - baseOffset.top + gap;

    if (top + cardRect.height > viewportHeight - EDGE_PADDING) {
        top = targetRect.top - baseOffset.top - cardRect.height - gap;
    }
    if (top < EDGE_PADDING) {
        top = Math.min(viewportHeight / 2 - cardRect.height / 2, viewportHeight - cardRect.height - EDGE_PADDING);
    }

    let left = targetRect.left - baseOffset.left + targetRect.width / 2 - cardRect.width / 2;
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

    if (forcedVisibleTarget) {
        forcedVisibleTarget.classList.remove("tutorial-force-visible");
        forcedVisibleTarget = null;
    }
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

    const candidateIndex = findNextStepIndex(nextIndex, direction > 0 ? 1 : -1);
    if (candidateIndex === null) {
        console.warn("chat-tutorial: no next step found", { nextIndex, direction });
        endTutorial(true);
        return;
    }

    currentStepIndex = candidateIndex;
    activeTarget = getTarget(tutorialSteps[currentStepIndex]);

    if (!activeTarget) {
        console.warn("chat-tutorial: target not found for step", tutorialSteps[currentStepIndex]);
        endTutorial(true);
        return;
    }

    const step = tutorialSteps[currentStepIndex];
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
    tutorialSteps = filterVisibleSteps(buildSteps());

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

    if (!launchBtn) {
        return;
    }

    launchBtn.addEventListener("click", () => startTutorial(true));

    if (!localStorage.getItem(STORAGE_KEY)) {
        setTimeout(() => startTutorial(false), 800);
    }
}
