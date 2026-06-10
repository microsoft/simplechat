// workflow-activity.js

const pageState = {
    snapshot: null,
    selectedActivityId: "",
    eventSource: null,
    followLatest: true,
    timelinePinnedToLatest: true,
    responseExpanded: false,
};

const BOTTOM_SCROLL_THRESHOLD = 24;
const MICROSOFT_365_CONSENT_MESSAGE = "User consent is required to access Microsoft 365 resources like Outlook email, Calendar, OneDrive, or SharePoint.";
const MICROSOFT_365_ACCESS_PENDING_MESSAGE = "Microsoft 365 access is not available yet. Grant access in the popup, then test access again.";

const mainContentEl = document.getElementById("main-content");
const pageEl = document.querySelector(".workflow-activity-page");
const titleEl = document.getElementById("workflow-activity-title");
const statusEl = document.getElementById("workflow-activity-status");
const captionEl = document.getElementById("workflow-activity-caption");
const conversationLinkEl = document.getElementById("workflow-activity-conversation-link");
const responseToggleBtn = document.getElementById("workflow-activity-response-toggle");
const responseToggleLabelEl = document.getElementById("workflow-activity-response-toggle-label");
const refreshBtn = document.getElementById("workflow-activity-refresh-btn");
const responseEl = document.getElementById("workflow-activity-response");
const emptyEl = document.getElementById("workflow-activity-empty");
const timelineViewportEl = document.getElementById("workflow-activity-timeline-viewport");
const timelineEl = document.getElementById("workflow-activity-timeline");
const detailTitleEl = document.getElementById("workflow-activity-detail-title");
const detailMetaEl = document.getElementById("workflow-activity-detail-meta");
const detailSummaryEl = document.getElementById("workflow-activity-detail-summary");
const pendingActionControlsEl = document.getElementById("workflow-activity-pending-action-controls");
const detailTextEl = document.getElementById("workflow-activity-detail-text");
const eventHistoryEl = document.getElementById("workflow-activity-event-history");
const statRunEl = document.getElementById("workflow-activity-stat-run");
const statTotalEl = document.getElementById("workflow-activity-stat-total");
const statToolsEl = document.getElementById("workflow-activity-stat-tools");
const statStartedEl = document.getElementById("workflow-activity-stat-started");
const workflowPendingActionTimers = new Map();

function normalizeText(value) {
    return String(value || "").trim();
}

function escapeHtml(value) {
    return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function formatDateTime(value) {
    if (!value) {
        return "--";
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return value;
    }

    return new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
    }).format(date);
}

function formatDuration(value) {
    const numericValue = Number(value || 0);
    if (!Number.isFinite(numericValue) || numericValue <= 0) {
        return "";
    }

    if (numericValue < 1000) {
        return `${Math.round(numericValue)} ms`;
    }

    const seconds = numericValue / 1000;
    if (seconds < 60) {
        return `${seconds.toFixed(seconds >= 10 ? 0 : 1)} s`;
    }

    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.round(seconds % 60);
    return `${minutes}m ${remainingSeconds}s`;
}

function calculatePendingActionSeconds(action) {
    const dueAt = normalizeText(action?.auto_send_at_utc);
    if (!dueAt) {
        return null;
    }
    const dueDate = new Date(dueAt);
    if (Number.isNaN(dueDate.getTime())) {
        return null;
    }
    return Math.max(0, Math.ceil((dueDate.getTime() - Date.now()) / 1000));
}

function formatPendingActionCountdown(seconds) {
    if (seconds === null || seconds === undefined) {
        return "";
    }
    const minutes = Math.floor(seconds / 60);
    const remainderSeconds = seconds % 60;
    return `${String(minutes).padStart(2, "0")}:${String(remainderSeconds).padStart(2, "0")}`;
}

function clearWorkflowPendingActionTimers() {
    workflowPendingActionTimers.forEach(timerId => window.clearInterval(timerId));
    workflowPendingActionTimers.clear();
}

function createPendingActionButton(label, iconClass, buttonClass) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = buttonClass;

    const icon = document.createElement("i");
    icon.className = iconClass;
    icon.setAttribute("aria-hidden", "true");
    button.appendChild(icon);

    const labelEl = document.createElement("span");
    labelEl.textContent = label;
    button.appendChild(labelEl);
    return button;
}

function setPendingActionInlineMessage(container, message, tone = "muted") {
    const messageEl = container.querySelector(".workflow-pending-action-message");
    if (!messageEl) {
        return;
    }
    messageEl.className = `workflow-pending-action-message small text-${tone}`;
    messageEl.textContent = message || "";
}

function getWorkflowMsGraphConsentUrl(payload) {
    const consentUrl = normalizeText(payload?.consent_url || payload?.auth_url);
    if (!consentUrl) {
        return "";
    }
    try {
        const parsedUrl = new URL(consentUrl, window.location.origin);
        return parsedUrl.protocol === "https:" ? parsedUrl.href : "";
    } catch (error) {
        return "";
    }
}

function openWorkflowMsGraphConsentPopup(consentUrl) {
    const normalizedUrl = getWorkflowMsGraphConsentUrl({ consent_url: consentUrl });
    if (!normalizedUrl) {
        return;
    }
    const popup = window.open(
        normalizedUrl,
        "simplechat-msgraph-consent",
        "popup,width=720,height=780,resizable=yes,scrollbars=yes"
    );
    if (popup) {
        popup.focus();
        return;
    }
    window.location.assign(normalizedUrl);
}

async function testWorkflowMsGraphAccess(scopes = []) {
    const response = await fetch("/api/msgraph/test-access", {
        method: "POST",
        credentials: "same-origin",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ scopes }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.access_granted !== true) {
        const error = new Error(payload.message || payload.error || MICROSOFT_365_ACCESS_PENDING_MESSAGE);
        error.payload = payload;
        throw error;
    }
    return payload;
}

async function testWorkflowMsGraphConsentAccess(container, prompt, scopes, messageEl) {
    if (!container || !prompt) {
        return;
    }
    const buttons = Array.from(prompt.querySelectorAll("button"));
    buttons.forEach(button => {
        button.disabled = true;
    });
    if (messageEl) {
        messageEl.textContent = "Checking Microsoft 365 access...";
    }

    try {
        await testWorkflowMsGraphAccess(scopes);
        prompt.remove();
        setPendingActionInlineMessage(container, "Microsoft 365 access verified. You can send or cancel now.", "success");
        container.querySelectorAll("button").forEach(button => {
            button.disabled = false;
        });
    } catch (error) {
        const payload = error.payload || {};
        if (messageEl) {
            messageEl.textContent = payload.message || error.message || MICROSOFT_365_ACCESS_PENDING_MESSAGE;
        }
        buttons.forEach(button => {
            button.disabled = false;
        });
    }
}

function renderWorkflowMsGraphConsentPrompt(container, payload) {
    const consentUrl = getWorkflowMsGraphConsentUrl(payload);
    if (!container || !consentUrl) {
        return false;
    }

    const existingPrompt = container.querySelector(".workflow-pending-action-consent");
    if (existingPrompt) {
        existingPrompt.remove();
    }

    const prompt = document.createElement("div");
    prompt.className = "workflow-pending-action-consent";

    const message = document.createElement("div");
    message.className = "small text-muted";
    message.textContent = MICROSOFT_365_CONSENT_MESSAGE;
    prompt.appendChild(message);

    const grantButton = createPendingActionButton("Grant access", "bi bi-shield-lock me-1", "btn btn-sm btn-outline-primary");
    grantButton.addEventListener("click", () => {
        openWorkflowMsGraphConsentPopup(consentUrl);
    });
    prompt.appendChild(grantButton);

    const testAccessButton = createPendingActionButton("Test access", "bi bi-check-circle me-1", "btn btn-sm btn-outline-primary");
    testAccessButton.addEventListener("click", () => {
        const scopes = Array.isArray(payload?.scopes) ? payload.scopes : [];
        void testWorkflowMsGraphConsentAccess(container, prompt, scopes, message);
    });
    prompt.appendChild(testAccessButton);

    const hint = document.createElement("div");
    hint.className = "small text-muted";
    hint.textContent = "After granting access, select Test access. When it succeeds, select Send again.";
    prompt.appendChild(hint);

    container.appendChild(prompt);
    return true;
}

async function submitWorkflowPendingAction(actionId, routeAction, container) {
    const normalizedActionId = normalizeText(actionId);
    if (!normalizedActionId) {
        setPendingActionInlineMessage(container, "Missing Microsoft 365 action metadata.", "danger");
        return;
    }

    container.querySelectorAll("button").forEach(button => {
        button.disabled = true;
    });
    setPendingActionInlineMessage(container, "Updating Microsoft 365 action...", "muted");

    try {
        const response = await fetch(`/api/msgraph/pending-actions/${encodeURIComponent(normalizedActionId)}/${routeAction}`, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({}),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            renderWorkflowMsGraphConsentPrompt(container, payload);
            throw new Error(payload.message || payload.error || "Unable to update the Microsoft 365 action.");
        }
        await loadSnapshot();
    } catch (error) {
        setPendingActionInlineMessage(container, error.message || "Unable to update the Microsoft 365 action.", "danger");
        container.querySelectorAll("button").forEach(button => {
            button.disabled = false;
        });
    }
}

function renderPendingActionControls(activity) {
    if (!pendingActionControlsEl) {
        return;
    }

    clearWorkflowPendingActionTimers();
    pendingActionControlsEl.replaceChildren();
    const action = activity?.pending_action;
    if (!action || action.type !== "msgraph_pending_action") {
        pendingActionControlsEl.classList.add("d-none");
        return;
    }

    pendingActionControlsEl.classList.remove("d-none");
    const status = normalizeText(action.status).toLowerCase();
    const terminal = ["sent", "cancelled", "canceled", "failed"].includes(status);
    const isDelayed = normalizeText(action.action_mode).toLowerCase() === "delayed";

    const heading = document.createElement("div");
    heading.className = "workflow-pending-action-heading";
    heading.textContent = isDelayed ? "Delayed Microsoft 365 action" : "Microsoft 365 action awaiting review";
    pendingActionControlsEl.appendChild(heading);

    const detail = document.createElement("div");
    detail.className = "workflow-pending-action-detail text-muted";
    if (terminal) {
        detail.textContent = status === "sent" ? "This action has been sent." : `This action is ${status}.`;
    } else if (isDelayed) {
        detail.textContent = `This action will send at ${formatDateTime(action.auto_send_at_utc)} unless it is sent now or cancelled.`;
    } else {
        detail.textContent = "Workflow execution is waiting for this action to be sent or cancelled.";
    }
    pendingActionControlsEl.appendChild(detail);

    const controls = document.createElement("div");
    controls.className = "workflow-pending-action-buttons";
    pendingActionControlsEl.appendChild(controls);

    const countdownEl = document.createElement("span");
    countdownEl.className = "workflow-pending-action-countdown d-none";
    controls.appendChild(countdownEl);

    if (!terminal) {
        const sendButton = createPendingActionButton(isDelayed ? "Send now" : "Send", "bi bi-send me-1", "btn btn-sm btn-primary");
        sendButton.addEventListener("click", () => {
            void submitWorkflowPendingAction(action.id, "send-now", pendingActionControlsEl);
        });
        controls.appendChild(sendButton);

        const cancelButton = createPendingActionButton("Cancel", "bi bi-x-circle me-1", "btn btn-sm btn-outline-secondary");
        cancelButton.addEventListener("click", () => {
            void submitWorkflowPendingAction(action.id, "cancel", pendingActionControlsEl);
        });
        controls.appendChild(cancelButton);
    }

    const messageEl = document.createElement("div");
    messageEl.className = "workflow-pending-action-message small text-muted";
    pendingActionControlsEl.appendChild(messageEl);

    if (isDelayed && !terminal) {
        const updateCountdown = () => {
            const secondsRemaining = calculatePendingActionSeconds(action);
            countdownEl.classList.remove("d-none");
            countdownEl.textContent = formatPendingActionCountdown(secondsRemaining);
            if (secondsRemaining !== null && secondsRemaining <= 0) {
                clearWorkflowPendingActionTimers();
                void submitWorkflowPendingAction(action.id, "send-now", pendingActionControlsEl);
            }
        };
        updateCountdown();
        workflowPendingActionTimers.set(action.id, window.setInterval(updateCountdown, 1000));
    }
}

function getQueryParam(name) {
    const params = new URLSearchParams(window.location.search);
    return normalizeText(params.get(name));
}

function getActivityScope() {
    return normalizeText(getQueryParam("scope")).toLowerCase() === "group" ? "group" : "personal";
}

function buildActivityApiPath(suffix = "") {
    const basePath = getActivityScope() === "group" ? "/api/group/workflows/activity" : "/api/user/workflows/activity";
    return `${basePath}${suffix}`;
}

function buildApiUrl(path) {
    const url = new URL(path, window.location.origin);
    const conversationId = getQueryParam("conversationId");
    const workflowId = getQueryParam("workflowId");
    const runId = getQueryParam("runId");
    const groupId = getQueryParam("groupId");

    if (conversationId) {
        url.searchParams.set("conversation_id", conversationId);
    }
    if (workflowId) {
        url.searchParams.set("workflow_id", workflowId);
    }
    if (runId) {
        url.searchParams.set("run_id", runId);
    }
    if (getActivityScope() === "group" && groupId) {
        url.searchParams.set("group_id", groupId);
    }

    return url.toString();
}

function buildConversationUrl(conversationId) {
    const normalizedConversationId = normalizeText(conversationId);
    if (!normalizedConversationId) {
        return "";
    }

    return `/chats?conversationId=${encodeURIComponent(normalizedConversationId)}`;
}

function enableWorkflowActivityLayoutMode() {
    if (mainContentEl) {
        mainContentEl.classList.add("workflow-activity-main-content");
    }
}

function disableWorkflowActivityLayoutMode() {
    if (mainContentEl) {
        mainContentEl.classList.remove("workflow-activity-main-content");
    }
}

function buildResponseToggleLabel(heading) {
    const normalizedHeading = normalizeText(heading).toLowerCase() || "response preview";
    return `${pageState.responseExpanded ? "Hide" : "Show"} ${normalizedHeading}`;
}

function syncResponseBlockVisibility() {
    if (!responseEl) {
        return;
    }

    const hasContent = responseEl.dataset.hasContent === "true";
    const responseHeading = responseEl.dataset.heading || "Response Preview";

    responseEl.classList.toggle("d-none", !hasContent || !pageState.responseExpanded);

    if (responseToggleBtn) {
        responseToggleBtn.classList.toggle("d-none", !hasContent);
        responseToggleBtn.setAttribute("aria-expanded", hasContent && pageState.responseExpanded ? "true" : "false");
    }

    if (responseToggleLabelEl) {
        responseToggleLabelEl.textContent = buildResponseToggleLabel(responseHeading);
    }

    syncViewportHeight();
}

function syncViewportHeight() {
    if (!pageEl || window.innerWidth <= 991) {
        if (pageEl) {
            pageEl.style.removeProperty("--workflow-activity-viewport-height");
        }
        return;
    }

    const topOffset = Math.max(pageEl.getBoundingClientRect().top, 0);
    const viewportHeight = Math.max(560, Math.floor(window.innerHeight - topOffset - 16));
    pageEl.style.setProperty("--workflow-activity-viewport-height", `${viewportHeight}px`);

    if (pageState.timelinePinnedToLatest) {
        scrollTimelineToNewest();
    }
}

function buildStatusBadge(status) {
    const normalizedStatus = normalizeText(status).toLowerCase() || "idle";
    const label = normalizedStatus === "running"
        ? "Running"
        : normalizedStatus === "failed"
            ? "Failed"
            : normalizedStatus === "completed"
                ? "Completed"
                : normalizedStatus;
    const className = normalizedStatus === "running"
        ? "text-bg-primary"
        : normalizedStatus === "failed"
            ? "text-bg-danger"
            : normalizedStatus === "completed"
                ? "text-bg-success"
                : "text-bg-secondary";
    return `<span class="badge ${className}">${escapeHtml(label)}</span>`;
}

function applyStatusBadge(element, status) {
    if (!element) {
        return;
    }

    const normalizedStatus = normalizeText(status).toLowerCase() || "idle";
    const className = normalizedStatus === "running"
        ? "text-bg-primary"
        : normalizedStatus === "failed"
            ? "text-bg-danger"
            : normalizedStatus === "completed"
                ? "text-bg-success"
                : "text-bg-secondary";
    const label = normalizedStatus === "running"
        ? "Running"
        : normalizedStatus === "failed"
            ? "Failed"
            : normalizedStatus === "completed"
                ? "Completed"
                : normalizedStatus;

    element.className = `badge ${className}`;
    element.textContent = label;
}

function updateResponseBlock(run) {
    const errorText = normalizeText(run?.error);
    const previewText = normalizeText(run?.response_preview);
    if (!responseEl) {
        return;
    }

    if (!errorText && !previewText) {
        pageState.responseExpanded = false;
        responseEl.dataset.hasContent = "false";
        responseEl.dataset.heading = "Response Preview";
        responseEl.innerHTML = "";
        syncResponseBlockVisibility();
        return;
    }

    const heading = errorText ? "Run Error" : "Response Preview";
    responseEl.dataset.hasContent = "true";
    responseEl.dataset.heading = heading;
    responseEl.innerHTML = `
        <div class="workflow-activity-response-title">${escapeHtml(heading)}</div>
        <p class="workflow-activity-response-text mb-0">${escapeHtml(errorText || previewText)}</p>
    `;
    syncResponseBlockVisibility();
}

function renderHeader(snapshot) {
    const workflow = snapshot.workflow || {};
    const conversation = snapshot.conversation || {};
    const run = snapshot.run || null;
    const workflowName = normalizeText(workflow.name) || normalizeText(conversation.title) || "Workflow activity";
    const runStatus = normalizeText(run?.status).toLowerCase();
    const runCaption = run
        ? `${normalizeText(run.trigger_source) || "manual"} run ${runStatus || "captured"}`
        : "Waiting for a captured workflow run.";

    if (titleEl) {
        titleEl.textContent = workflowName;
    }
    if (statusEl) {
        applyStatusBadge(statusEl, runStatus || "idle");
    }
    if (captionEl) {
        const modelOrAgent = normalizeText(run?.agent_display_name || run?.agent_name || run?.model_deployment_name);
        captionEl.textContent = modelOrAgent ? `${runCaption} using ${modelOrAgent}.` : `${runCaption}.`;
    }

    const conversationUrl = buildConversationUrl(conversation.id || run?.conversation_id);
    if (conversationLinkEl) {
        conversationLinkEl.classList.toggle("d-none", !conversationUrl);
        conversationLinkEl.href = conversationUrl || "#";
    }

    if (statRunEl) {
        statRunEl.textContent = run ? normalizeText(run.id).slice(0, 8) || "Captured" : "Pending";
    }
    if (statTotalEl) {
        statTotalEl.textContent = String(Array.isArray(snapshot.activities) ? snapshot.activities.length : 0);
    }
    if (statToolsEl) {
        const toolCount = Array.isArray(snapshot.activities)
            ? snapshot.activities.filter(activity => normalizeText(activity.kind) === "tool_invocation").length
            : 0;
        statToolsEl.textContent = String(toolCount);
    }
    if (statStartedEl) {
        statStartedEl.textContent = formatDateTime(run?.started_at);
    }

    updateResponseBlock(run);
}

function buildActivityMeta(activity) {
    const parts = [];
    if (normalizeText(activity.lane_label)) {
        parts.push(`<span><i class="bi bi-bezier"></i>${escapeHtml(activity.lane_label)}</span>`);
    }
    if (normalizeText(activity.started_at)) {
        parts.push(`<span><i class="bi bi-clock"></i>${escapeHtml(formatDateTime(activity.started_at))}</span>`);
    }
    const durationLabel = formatDuration(activity.duration_ms);
    if (durationLabel) {
        parts.push(`<span><i class="bi bi-stopwatch"></i>${escapeHtml(durationLabel)}</span>`);
    }
    return parts.join("");
}

function renderTimeline(snapshot) {
    const activities = Array.isArray(snapshot.activities) ? snapshot.activities : [];
    if (!timelineEl || !emptyEl) {
        return;
    }

    const showEmptyState = !activities.length;
    emptyEl.classList.toggle("d-none", !showEmptyState);
    timelineEl.classList.toggle("d-none", showEmptyState);

    if (showEmptyState) {
        timelineEl.innerHTML = "";
        return;
    }

    timelineEl.innerHTML = activities.map(activity => {
        const activityId = normalizeText(activity.id);
        const selectedClass = pageState.selectedActivityId === activityId ? "is-selected" : "";
        const laneIndex = Number(activity.lane_index || 0);
        const summary = normalizeText(activity.summary);
        const metaHtml = buildActivityMeta(activity);
        return `
            <div class="workflow-activity-row" style="--lane-index:${laneIndex};">
                <div class="workflow-activity-node" data-status="${escapeHtml(normalizeText(activity.status).toLowerCase())}"></div>
                <button
                    type="button"
                    class="workflow-activity-card ${selectedClass}"
                    data-status="${escapeHtml(normalizeText(activity.status).toLowerCase())}"
                    data-activity-id="${escapeHtml(activityId)}"
                >
                    <div class="workflow-activity-card-header">
                        <div>
                            <h3 class="workflow-activity-card-title">${escapeHtml(normalizeText(activity.title) || "Workflow activity")}</h3>
                            <p class="workflow-activity-card-summary">${escapeHtml(summary || "No summary available.")}</p>
                        </div>
                        <span class="workflow-activity-badge" data-status="${escapeHtml(normalizeText(activity.status).toLowerCase())}">${escapeHtml(normalizeText(activity.status) || "completed")}</span>
                    </div>
                    <div class="workflow-activity-card-meta">${metaHtml}</div>
                </button>
            </div>
        `;
    }).join("");

    timelineEl.querySelectorAll("[data-activity-id]").forEach(button => {
        button.addEventListener("click", () => {
            selectActivity(button.getAttribute("data-activity-id"));
        });
    });
}

function scrollTimelineToNewest() {
    if (!timelineViewportEl) {
        return;
    }

    window.requestAnimationFrame(() => {
        const lastTimelineRow = timelineEl?.lastElementChild || null;
        if (lastTimelineRow) {
            lastTimelineRow.scrollIntoView({
                behavior: "smooth",
                block: "end",
            });
            return;
        }

        timelineViewportEl.scrollTop = timelineViewportEl.scrollHeight;
    });
}

function isTimelineNearBottom() {
    if (!timelineViewportEl) {
        return true;
    }

    const remainingDistance = timelineViewportEl.scrollHeight - timelineViewportEl.scrollTop - timelineViewportEl.clientHeight;
    return remainingDistance <= BOTTOM_SCROLL_THRESHOLD;
}

function renderDetailMeta(activity) {
    if (!detailMetaEl) {
        return;
    }

    const parts = [];
    parts.push(buildStatusBadge(activity.status || "completed"));
    if (normalizeText(activity.lane_label)) {
        parts.push(`<span>${escapeHtml(activity.lane_label)}</span>`);
    }
    if (normalizeText(activity.started_at)) {
        parts.push(`<span>${escapeHtml(formatDateTime(activity.started_at))}</span>`);
    }
    const durationLabel = formatDuration(activity.duration_ms);
    if (durationLabel) {
        parts.push(`<span>${escapeHtml(durationLabel)}</span>`);
    }
    detailMetaEl.innerHTML = parts.join("");
}

function renderEventHistory(activity) {
    if (!eventHistoryEl) {
        return;
    }

    const events = Array.isArray(activity.events) ? activity.events : [];
    if (!events.length) {
        eventHistoryEl.innerHTML = "No event history is available for this activity.";
        return;
    }

    eventHistoryEl.innerHTML = events.map(event => `
        <div class="workflow-activity-event-item">
            <div class="workflow-activity-event-item-header">
                <div class="workflow-activity-event-item-title">${escapeHtml(normalizeText(event.content) || normalizeText(activity.title) || "Activity event")}</div>
                <div class="workflow-activity-event-item-time">${escapeHtml(formatDateTime(event.timestamp))}</div>
            </div>
            <div class="workflow-activity-event-item-detail">${escapeHtml(normalizeText(event.detail) || "No additional technical detail recorded.")}</div>
        </div>
    `).join("");
}

function renderSelectedActivity(activity) {
    if (!activity) {
        if (detailTitleEl) {
            detailTitleEl.textContent = "Select an activity";
        }
        if (detailSummaryEl) {
            detailSummaryEl.textContent = "Choose a card on the timeline to inspect the event stream, timing, and captured technical detail.";
        }
        if (detailTextEl) {
            detailTextEl.textContent = "No activity selected.";
        }
        if (detailMetaEl) {
            detailMetaEl.innerHTML = "";
        }
        if (eventHistoryEl) {
            eventHistoryEl.innerHTML = "Select an activity to inspect its event history.";
        }
        renderPendingActionControls(null);
        return;
    }

    if (detailTitleEl) {
        detailTitleEl.textContent = normalizeText(activity.title) || "Workflow activity";
    }
    if (detailSummaryEl) {
        detailSummaryEl.textContent = normalizeText(activity.summary) || "No summary available.";
    }
    if (detailTextEl) {
        detailTextEl.textContent = normalizeText(activity.detail) || "No additional technical detail recorded.";
    }
    renderPendingActionControls(activity);
    renderDetailMeta(activity);
    renderEventHistory(activity);
}

function getSelectedActivity(snapshot) {
    const activities = Array.isArray(snapshot.activities) ? snapshot.activities : [];
    if (!activities.length) {
        return null;
    }

    if (pageState.followLatest) {
        const latestActivity = activities[activities.length - 1];
        pageState.selectedActivityId = normalizeText(latestActivity.id);
        return latestActivity;
    }

    const selectedActivity = activities.find(activity => normalizeText(activity.id) === pageState.selectedActivityId);
    if (selectedActivity) {
        return selectedActivity;
    }

    const runningActivity = activities.find(activity => normalizeText(activity.status).toLowerCase() === "running");
    if (runningActivity) {
        pageState.selectedActivityId = normalizeText(runningActivity.id);
        return runningActivity;
    }

    const fallbackActivity = activities[activities.length - 1];
    pageState.selectedActivityId = normalizeText(fallbackActivity.id);
    return fallbackActivity;
}

function applySnapshot(snapshot) {
    pageState.snapshot = snapshot || {};
    renderHeader(pageState.snapshot);
    renderTimeline(pageState.snapshot);
    renderSelectedActivity(getSelectedActivity(pageState.snapshot));
    if (pageState.timelinePinnedToLatest && pageState.snapshot?.live !== false) {
        scrollTimelineToNewest();
    }
    toggleEventStream();
}

function selectActivity(activityId) {
    pageState.selectedActivityId = normalizeText(activityId);
    if (!pageState.snapshot) {
        return;
    }

    const activities = Array.isArray(pageState.snapshot.activities) ? pageState.snapshot.activities : [];
    const latestActivityId = activities.length ? normalizeText(activities[activities.length - 1].id) : "";
    pageState.followLatest = pageState.selectedActivityId === latestActivityId;

    renderTimeline(pageState.snapshot);
    renderSelectedActivity(getSelectedActivity(pageState.snapshot));
}

async function loadSnapshot() {
    const response = await fetch(buildApiUrl(buildActivityApiPath()), {
        credentials: "same-origin",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(payload.error || "Unable to load workflow activity.");
    }

    applySnapshot(payload);
}

function shouldListenForUpdates(snapshot) {
    const hasAnyIdentifier = Boolean(getQueryParam("conversationId") || getQueryParam("workflowId") || getQueryParam("runId"));
    if (!hasAnyIdentifier || typeof EventSource === "undefined") {
        return false;
    }

    const run = snapshot?.run || null;
    if (!run) {
        return true;
    }

    return Boolean(snapshot?.live) || normalizeText(run.status).toLowerCase() === "running";
}

function stopEventStream() {
    if (pageState.eventSource) {
        pageState.eventSource.close();
        pageState.eventSource = null;
    }
}

function startEventStream() {
    if (pageState.eventSource || !shouldListenForUpdates(pageState.snapshot)) {
        return;
    }

    const eventSource = new EventSource(buildApiUrl(buildActivityApiPath("/stream")));
    eventSource.onmessage = event => {
        if (!event?.data) {
            return;
        }

        try {
            const payload = JSON.parse(event.data);
            applySnapshot(payload);
        } catch (error) {
            console.warn("Failed to parse workflow activity event", error);
        }
    };
    eventSource.onerror = () => {
        const runStatus = normalizeText(pageState.snapshot?.run?.status).toLowerCase();
        if (runStatus && runStatus !== "running") {
            stopEventStream();
        }
    };

    pageState.eventSource = eventSource;
}

function toggleEventStream() {
    if (shouldListenForUpdates(pageState.snapshot)) {
        startEventStream();
    } else {
        stopEventStream();
    }
}

async function initializePage() {
    syncViewportHeight();
    const hasAnyIdentifier = Boolean(getQueryParam("conversationId") || getQueryParam("workflowId") || getQueryParam("runId"));
    if (!hasAnyIdentifier) {
        applySnapshot({
            workflow: null,
            conversation: null,
            run: null,
            activities: [],
            lane_count: 1,
            live: false,
        });
        if (captionEl) {
            captionEl.textContent = "Open this page from a workflow conversation or a workflow run history entry.";
        }
        return;
    }

    try {
        await loadSnapshot();
    } catch (error) {
        console.error("Failed to load workflow activity", error);
        applySnapshot({
            workflow: null,
            conversation: null,
            run: null,
            activities: [],
            lane_count: 1,
            live: false,
        });
        if (titleEl) {
            titleEl.textContent = "Workflow activity unavailable";
        }
        if (statusEl) {
            applyStatusBadge(statusEl, "failed");
        }
        if (captionEl) {
            captionEl.textContent = error.message || "Unable to load workflow activity.";
        }
    }
}

if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
        pageState.followLatest = true;
        pageState.timelinePinnedToLatest = true;
        initializePage().catch(error => {
            console.warn("Workflow activity refresh failed", error);
        });
    });
}

if (responseToggleBtn) {
    responseToggleBtn.addEventListener("click", () => {
        pageState.responseExpanded = !pageState.responseExpanded;
        syncResponseBlockVisibility();
    });
}

if (timelineViewportEl) {
    timelineViewportEl.addEventListener("scroll", () => {
        pageState.timelinePinnedToLatest = isTimelineNearBottom();
    }, { passive: true });
}

window.addEventListener("beforeunload", () => {
    stopEventStream();
    disableWorkflowActivityLayoutMode();
});

window.addEventListener("resize", () => {
    syncViewportHeight();
});

window.addEventListener("DOMContentLoaded", () => {
    enableWorkflowActivityLayoutMode();
    initializePage().catch(error => {
        console.warn("Workflow activity initialization failed", error);
    });
});
