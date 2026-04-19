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
const detailTextEl = document.getElementById("workflow-activity-detail-text");
const eventHistoryEl = document.getElementById("workflow-activity-event-history");
const statRunEl = document.getElementById("workflow-activity-stat-run");
const statTotalEl = document.getElementById("workflow-activity-stat-total");
const statToolsEl = document.getElementById("workflow-activity-stat-tools");
const statStartedEl = document.getElementById("workflow-activity-stat-started");

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

function getQueryParam(name) {
    const params = new URLSearchParams(window.location.search);
    return normalizeText(params.get(name));
}

function buildApiUrl(path) {
    const url = new URL(path, window.location.origin);
    const conversationId = getQueryParam("conversationId");
    const workflowId = getQueryParam("workflowId");
    const runId = getQueryParam("runId");

    if (conversationId) {
        url.searchParams.set("conversation_id", conversationId);
    }
    if (workflowId) {
        url.searchParams.set("workflow_id", workflowId);
    }
    if (runId) {
        url.searchParams.set("run_id", runId);
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
    const response = await fetch(buildApiUrl("/api/user/workflows/activity"), {
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

    const eventSource = new EventSource(buildApiUrl("/api/user/workflows/activity/stream"));
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
});

window.addEventListener("resize", () => {
    syncViewportHeight();
});

window.addEventListener("DOMContentLoaded", () => {
    initializePage().catch(error => {
        console.warn("Workflow activity initialization failed", error);
    });
});
