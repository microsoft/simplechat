// workspace_workflows.js

import { showToast } from "../chat/chat-toast.js";
import { escapeHtml, truncateDescription, setupViewToggle, switchViewContainers } from "./view-utils.js";

const workflowsTableBody = document.getElementById("workflows-table-body");
const workflowsListView = document.getElementById("workflows-list-view");
const workflowsGridView = document.getElementById("workflows-grid-view");
const workflowsSearchInput = document.getElementById("workflows-search");
const workflowsSummary = document.getElementById("workflows-summary");
const createWorkflowBtn = document.getElementById("create-workflow-btn");

const workflowModalEl = document.getElementById("workflowModal");
const workflowModal = workflowModalEl && window.bootstrap ? bootstrap.Modal.getOrCreateInstance(workflowModalEl) : null;
const workflowForm = document.getElementById("workflow-form");
const workflowModalLabel = document.getElementById("workflowModalLabel");
const workflowSaveBtn = document.getElementById("workflow-save-btn");

const workflowIdInput = document.getElementById("workflow-id");
const workflowNameInput = document.getElementById("workflow-name");
const workflowDescriptionInput = document.getElementById("workflow-description");
const workflowTaskPromptInput = document.getElementById("workflow-task-prompt");
const workflowRunnerTypeSelect = document.getElementById("workflow-runner-type");
const workflowAgentFields = document.getElementById("workflow-agent-fields");
const workflowAgentSelect = document.getElementById("workflow-agent-select");
const workflowAgentHelp = document.getElementById("workflow-agent-help");
const workflowModelFields = document.getElementById("workflow-model-fields");
const workflowModelSourceSelect = document.getElementById("workflow-model-source");
const workflowModelEndpointGroup = document.getElementById("workflow-model-endpoint-group");
const workflowModelEndpointSelect = document.getElementById("workflow-model-endpoint-select");
const workflowModelGroup = document.getElementById("workflow-model-group");
const workflowModelSelect = document.getElementById("workflow-model-select");
const workflowModelHelp = document.getElementById("workflow-model-help");
const workflowTriggerTypeSelect = document.getElementById("workflow-trigger-type");
const workflowScheduleValueGroup = document.getElementById("workflow-schedule-value-group");
const workflowScheduleUnitGroup = document.getElementById("workflow-schedule-unit-group");
const workflowScheduleValueInput = document.getElementById("workflow-schedule-value");
const workflowScheduleUnitSelect = document.getElementById("workflow-schedule-unit");
const workflowEnabledGroup = document.getElementById("workflow-enabled-group");
const workflowEnabledToggle = document.getElementById("workflow-enabled");
const workflowTriggerHelp = document.getElementById("workflow-trigger-help");
const workflowAlertPrioritySelect = document.getElementById("workflow-alert-priority");
const DOCUMENT_ACTION_NONE = "none";
const DOCUMENT_ACTION_ANALYZE = "analyze";
const DOCUMENT_ACTION_COMPARISON = "comparison";
const DOCUMENT_ACTION_DESCRIPTIONS = {
    [DOCUMENT_ACTION_NONE]: "Find relevant information with the normal prompt flow instead of binding the workflow to fixed document targets.",
    [DOCUMENT_ACTION_ANALYZE]: "Perform an in-depth analysis across all selected documents based on your request.",
    [DOCUMENT_ACTION_COMPARISON]: "Compare one source document against the selected target documents to explain differences, relationships, or downstream impact.",
};
const DEFAULT_DOCUMENT_ACTION_CAPABILITIES = {
    [DOCUMENT_ACTION_ANALYZE]: {
        enabled: true,
        chat_max_documents: 3,
        workflow_max_documents: 10,
    },
    [DOCUMENT_ACTION_COMPARISON]: {
        enabled: true,
        chat_max_documents: 3,
        workflow_max_documents: 10,
    },
};
const workflowDocumentActionTypeSelect = document.getElementById("workflow-document-action-type");
const workflowDocumentActionHelp = document.getElementById("workflow-document-action-help");
const workflowDocumentTargetsFields = document.getElementById("workflow-document-targets-fields");
const workflowAnalysisTargetFields = document.getElementById("workflow-analysis-target-fields");
const workflowComparisonTargetFields = document.getElementById("workflow-comparison-target-fields");
const workflowAnalysisDocScopeSelect = document.getElementById("workflow-analysis-doc-scope");
const workflowAnalysisDocumentIdsInput = document.getElementById("workflow-analysis-document-ids");
const workflowComparisonLeftDocumentIdInput = document.getElementById("workflow-comparison-left-document-id");
const workflowComparisonRightDocumentIdsInput = document.getElementById("workflow-comparison-target-document-ids");
const workflowAnalysisGroupIdsInput = document.getElementById("workflow-analysis-group-ids");
const workflowAnalysisPublicWorkspaceIdsInput = document.getElementById("workflow-analysis-public-workspace-ids");
const workflowAnalysisWindowUnitSelect = document.getElementById("workflow-analysis-window-unit");
const workflowAnalysisWindowSizeInput = document.getElementById("workflow-analysis-window-size");
const workflowAnalysisWindowPercentInput = document.getElementById("workflow-analysis-window-percent");
const workflowAnalysisRetriesInput = document.getElementById("workflow-analysis-retries");
const workflowUseSelectedDocumentsBtn = document.getElementById("workflow-use-selected-documents-btn");
const workflowSelectedDocumentsSummary = document.getElementById("workflow-selected-documents-summary");

const workflowHistoryModalEl = document.getElementById("workflowHistoryModal");
const workflowHistoryModal = workflowHistoryModalEl && window.bootstrap ? bootstrap.Modal.getOrCreateInstance(workflowHistoryModalEl) : null;
const workflowHistoryModalLabel = document.getElementById("workflowHistoryModalLabel");
const workflowHistoryBody = document.getElementById("workflow-history-body");
const workflowHistoryConversationId = document.getElementById("workflow-history-conversation-id");
const workflowHistoryConversationLink = document.getElementById("workflow-history-open-conversation-link");

function getDocumentActionCapability(actionType) {
    const defaultCapability = DEFAULT_DOCUMENT_ACTION_CAPABILITIES[actionType] || {
        enabled: false,
        chat_max_documents: 3,
        workflow_max_documents: 10,
    };
    const configuredCapability = window.documentActionCapabilities?.[actionType] || {};
    return {
        ...defaultCapability,
        ...configuredCapability,
    };
}

function isDocumentActionEnabled(actionType) {
    if (actionType === DOCUMENT_ACTION_NONE) {
        return true;
    }

    return Boolean(getDocumentActionCapability(actionType).enabled);
}

function getWorkflowDocumentActionMaxDocuments(actionType) {
    return Number.parseInt(getDocumentActionCapability(actionType).workflow_max_documents || 10, 10);
}

function getDocumentActionDisplayLabel(actionType) {
    if (actionType === DOCUMENT_ACTION_COMPARISON) {
        return "Compare";
    }
    if (actionType === DOCUMENT_ACTION_ANALYZE) {
        return "Analyze";
    }
    return "Search";
}

function getDocumentActionDescription(actionType) {
    return DOCUMENT_ACTION_DESCRIPTIONS[actionType] || DOCUMENT_ACTION_DESCRIPTIONS[DOCUMENT_ACTION_NONE];
}

function syncWorkflowDocumentActionTooltip() {
    if (!workflowDocumentActionTypeSelect) {
        return;
    }

    const selectedOption = workflowDocumentActionTypeSelect.selectedOptions?.[0] || null;
    const description = normalizeText(
        selectedOption?.dataset.actionDescription
        || selectedOption?.getAttribute("title")
        || getDocumentActionDescription(normalizeText(workflowDocumentActionTypeSelect.value) || DOCUMENT_ACTION_NONE)
    );

    workflowDocumentActionTypeSelect.title = description;
    workflowDocumentActionTypeSelect.setAttribute("aria-description", description);
}

const workflowDeleteModalEl = document.getElementById("workflowDeleteModal");
const workflowDeleteModal = workflowDeleteModalEl && window.bootstrap ? bootstrap.Modal.getOrCreateInstance(workflowDeleteModalEl) : null;
const workflowDeleteName = document.getElementById("workflow-delete-name");
const workflowDeleteConfirmBtn = document.getElementById("workflow-delete-confirm-btn");

let workflows = [];
let filteredWorkflows = [];
let agentOptions = [];
let agentsLoaded = false;
let workflowPendingDelete = null;
let currentHistoryWorkflowId = "";
let currentEditingWorkflow = null;
let workflowComparisonVersionLoadToken = 0;

function normalizeText(value) {
    return String(value || "").trim();
}

function setElementVisibility(element, isVisible) {
    if (!element) {
        return;
    }
    element.classList.toggle("d-none", !isVisible);
}

function formatDateTime(value) {
    if (!value) {
        return "";
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

function buildWorkflowConversationUrl(conversationId) {
    const normalizedConversationId = normalizeText(conversationId);
    if (!normalizedConversationId) {
        return "";
    }

    return `/chats?conversationId=${encodeURIComponent(normalizedConversationId)}`;
}

function buildWorkflowActivityUrl(conversationId, runId = "", workflowId = "") {
    const normalizedConversationId = normalizeText(conversationId);
    if (!normalizedConversationId) {
        return "";
    }

    const url = new URL("/workflow-activity", window.location.origin);
    url.searchParams.set("conversationId", normalizedConversationId);

    const normalizedRunId = normalizeText(runId);
    if (normalizedRunId) {
        url.searchParams.set("runId", normalizedRunId);
    }

    const normalizedWorkflowId = normalizeText(workflowId);
    if (normalizedWorkflowId) {
        url.searchParams.set("workflowId", normalizedWorkflowId);
    }

    return url.toString();
}

function updateWorkflowConversationLink(element, conversationId) {
    if (!element) {
        return;
    }

    const conversationUrl = buildWorkflowConversationUrl(conversationId);
    element.classList.toggle("d-none", !conversationUrl);
    element.href = conversationUrl || "#";
}

function buildStatusBadge(status) {
    const normalizedStatus = normalizeText(status).toLowerCase() || "idle";
    const variant = normalizedStatus === "completed"
        ? "success"
        : normalizedStatus === "failed"
            ? "danger"
            : normalizedStatus === "running"
                ? "primary"
                : "secondary";
    const label = normalizedStatus.charAt(0).toUpperCase() + normalizedStatus.slice(1);
    return `<span class="badge bg-${variant}">${escapeHtml(label)}</span>`;
}

function getWorkflowRunnerLabel(workflow) {
    if (!workflow || typeof workflow !== "object") {
        return "";
    }

    if (workflow.runner_type === "agent") {
        const selectedAgent = workflow.selected_agent && typeof workflow.selected_agent === "object"
            ? workflow.selected_agent
            : {};
        const label = normalizeText(selectedAgent.display_name || selectedAgent.name) || "Selected agent";
        return selectedAgent.is_global ? `${label} (Global Agent)` : `${label} (Personal Agent)`;
    }

    const modelBindingSummary = workflow.model_binding_summary && typeof workflow.model_binding_summary === "object"
        ? workflow.model_binding_summary
        : {};
    return normalizeText(modelBindingSummary.label) || "Default app model";
}

function getWorkflowTriggerLabel(workflow) {
    if (!workflow || typeof workflow !== "object") {
        return "Manual";
    }

    if (workflow.trigger_type !== "interval") {
        return "Manual";
    }

    const schedule = workflow.schedule && typeof workflow.schedule === "object" ? workflow.schedule : {};
    const value = Number(schedule.value || 0);
    const unit = normalizeText(schedule.unit) || "minutes";
    return `Every ${value} ${unit}`;
}

function getWorkflowAlertLabel(workflow) {
    const priority = normalizeText(workflow?.alert_priority).toLowerCase();
    if (!priority || priority === "none") {
        return "Off";
    }

    return `${priority.charAt(0).toUpperCase()}${priority.slice(1)} priority`;
}

function parseCsvList(value) {
    return normalizeText(value)
        .split(",")
        .map((item) => normalizeText(item))
        .filter(Boolean);
}

function joinCsvList(values) {
    if (!Array.isArray(values)) {
        return "";
    }

    return values.map((value) => normalizeText(value)).filter(Boolean).join(", ");
}

function getSelectedValues(selectElement) {
    if (!selectElement) {
        return [];
    }

    return Array.from(selectElement.selectedOptions || [])
        .map((option) => normalizeText(option.value))
        .filter(Boolean);
}

function getSelectedWorkflowComparisonTargetIds() {
    return getSelectedValues(workflowComparisonRightDocumentIdsInput);
}

function formatWorkflowVersionDate(uploadDate) {
    const parsedTime = Date.parse(normalizeText(uploadDate));
    if (Number.isNaN(parsedTime)) {
        return "";
    }

    return new Date(parsedTime).toLocaleDateString();
}

function buildWorkflowVersionLabel(version, fallbackName) {
    const baseName = normalizeText(version?.title)
        || normalizeText(version?.file_name)
        || normalizeText(fallbackName)
        || normalizeText(version?.id)
        || "Document version";
    const versionNumber = Number.parseInt(version?.version, 10);
    const detailParts = [];

    if (Number.isFinite(versionNumber)) {
        detailParts.push(`v${versionNumber}`);
    }
    if (version?.is_current_version) {
        detailParts.push("current");
    }

    const formattedDate = formatWorkflowVersionDate(version?.upload_date);
    if (formattedDate) {
        detailParts.push(formattedDate);
    }

    return detailParts.length ? `${baseName} (${detailParts.join(" | ")})` : baseName;
}

function buildWorkflowComparisonFallbackVersion(documentId) {
    return [{
        id: documentId,
        title: "",
        file_name: documentId,
        version: null,
        upload_date: null,
        is_current_version: true,
    }];
}

function syncWorkflowComparisonLeftOptions(preferredLeftId = "") {
    if (!workflowComparisonLeftDocumentIdInput || !workflowComparisonRightDocumentIdsInput) {
        return;
    }

    const selectedTargetOptions = Array.from(workflowComparisonRightDocumentIdsInput.selectedOptions || []);
    const previousSelection = normalizeText(preferredLeftId) || normalizeText(workflowComparisonLeftDocumentIdInput.value);
    workflowComparisonLeftDocumentIdInput.innerHTML = "";

    selectedTargetOptions.forEach((targetOption, index) => {
        const option = document.createElement("option");
        option.value = targetOption.value;
        option.textContent = targetOption.textContent;
        if ((previousSelection && previousSelection === targetOption.value) || (!previousSelection && index === 0)) {
            option.selected = true;
        }
        workflowComparisonLeftDocumentIdInput.appendChild(option);
    });

    workflowComparisonLeftDocumentIdInput.disabled = selectedTargetOptions.length === 0;
}

function setWorkflowComparisonTargetOptions(comparisonGroups = [], selectedTargetIds = [], preferredLeftId = "") {
    if (!workflowComparisonRightDocumentIdsInput) {
        return;
    }

    const normalizedSelectedTargetIds = new Set((selectedTargetIds || []).map((value) => normalizeText(value)).filter(Boolean));
    workflowComparisonRightDocumentIdsInput.innerHTML = "";

    comparisonGroups.forEach(({ groupLabel, versions }) => {
        const selectedIdsForGroup = versions
            .filter((version) => normalizedSelectedTargetIds.has(normalizeText(version.id)))
            .map((version) => normalizeText(version.id));
        const defaultSelectedIds = selectedIdsForGroup.length > 0
            ? new Set(selectedIdsForGroup)
            : new Set([
                normalizeText(versions.find((version) => version.is_current_version)?.id)
                || normalizeText(versions[0]?.id),
            ].filter(Boolean));
        const optionGroup = document.createElement("optgroup");
        optionGroup.label = normalizeText(groupLabel) || "Document";

        versions.forEach((version) => {
            const option = document.createElement("option");
            option.value = normalizeText(version.id);
            option.textContent = buildWorkflowVersionLabel(version, groupLabel);
            option.selected = defaultSelectedIds.has(normalizeText(version.id));
            optionGroup.appendChild(option);
        });

        workflowComparisonRightDocumentIdsInput.appendChild(optionGroup);
    });

    workflowComparisonRightDocumentIdsInput.disabled = workflowComparisonRightDocumentIdsInput.options.length === 0;
    syncWorkflowComparisonLeftOptions(preferredLeftId);
}

function setWorkflowComparisonSavedTargets(targetIds = [], preferredLeftId = "") {
    if (!workflowComparisonRightDocumentIdsInput) {
        return;
    }

    const normalizedTargetIds = Array.from(new Set((targetIds || []).map((value) => normalizeText(value)).filter(Boolean)));
    workflowComparisonRightDocumentIdsInput.innerHTML = "";

    normalizedTargetIds.forEach((targetId) => {
        const option = document.createElement("option");
        option.value = targetId;
        option.textContent = targetId;
        option.selected = true;
        workflowComparisonRightDocumentIdsInput.appendChild(option);
    });

    workflowComparisonRightDocumentIdsInput.disabled = normalizedTargetIds.length === 0;
    syncWorkflowComparisonLeftOptions(preferredLeftId);
}

async function fetchWorkflowDocumentVersions(documentId) {
    const response = await fetch(`/api/documents/${encodeURIComponent(documentId)}/versions`, {
        credentials: "same-origin",
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(data.error || "Unable to load document versions.");
    }

    return Array.isArray(data.versions) ? data.versions : [];
}

async function loadWorkflowComparisonVersionTargets({
    selectedWorkspaceDocumentIds = [],
    selectedTargetIds = [],
    preferredLeftId = "",
} = {}) {
    if (!workflowComparisonRightDocumentIdsInput) {
        return;
    }

    const normalizedDocumentIds = (selectedWorkspaceDocumentIds || []).map((value) => normalizeText(value)).filter(Boolean);
    if (!normalizedDocumentIds.length) {
        setWorkflowComparisonSavedTargets(selectedTargetIds, preferredLeftId);
        return;
    }

    const requestToken = ++workflowComparisonVersionLoadToken;
    workflowComparisonRightDocumentIdsInput.disabled = true;
    workflowComparisonRightDocumentIdsInput.innerHTML = '<option value="" disabled>Loading versions...</option>';
    if (workflowComparisonLeftDocumentIdInput) {
        workflowComparisonLeftDocumentIdInput.disabled = true;
        workflowComparisonLeftDocumentIdInput.innerHTML = "";
    }

    const comparisonGroups = await Promise.all(normalizedDocumentIds.map(async (documentId) => {
        let versions = [];
        try {
            versions = await fetchWorkflowDocumentVersions(documentId);
        } catch (error) {
            console.warn("Unable to load workflow comparison versions for document:", documentId, error);
        }

        if (!Array.isArray(versions) || versions.length === 0) {
            versions = buildWorkflowComparisonFallbackVersion(documentId);
        }

        return {
            groupLabel: normalizeText(versions[0]?.title) || normalizeText(versions[0]?.file_name) || documentId,
            versions,
        };
    }));

    if (requestToken !== workflowComparisonVersionLoadToken) {
        return;
    }

    setWorkflowComparisonTargetOptions(comparisonGroups, selectedTargetIds, preferredLeftId);
}

function getSelectedWorkspaceDocumentIds() {
    if (window.selectedDocuments instanceof Set) {
        return Array.from(window.selectedDocuments).map((value) => normalizeText(value)).filter(Boolean);
    }

    if (Array.isArray(window.selectedDocuments)) {
        return window.selectedDocuments.map((value) => normalizeText(value)).filter(Boolean);
    }

    return [];
}

function getDocumentActionConfig(workflow) {
    const actionConfig = workflow?.document_action && typeof workflow.document_action === "object"
        ? workflow.document_action
        : {};
    const legacyAnalyzeConfig = workflow?.analyze && typeof workflow.analyze === "object"
        ? workflow.analyze
        : {};
    const actionType = normalizeText(actionConfig.type)
        || (legacyAnalyzeConfig.enabled ? DOCUMENT_ACTION_ANALYZE : DOCUMENT_ACTION_NONE);

    return {
        type: actionType,
        document_ids: Array.isArray(actionConfig.document_ids)
            ? actionConfig.document_ids
            : Array.isArray(legacyAnalyzeConfig.document_ids)
                ? legacyAnalyzeConfig.document_ids
                : [],
        left_document_id: normalizeText(actionConfig.left_document_id),
        right_document_ids: Array.isArray(actionConfig.right_document_ids) ? actionConfig.right_document_ids : [],
        doc_scope: normalizeText(actionConfig.doc_scope || legacyAnalyzeConfig.doc_scope) || "personal",
        active_group_ids: Array.isArray(actionConfig.active_group_ids)
            ? actionConfig.active_group_ids
            : Array.isArray(legacyAnalyzeConfig.active_group_ids)
                ? legacyAnalyzeConfig.active_group_ids
                : [],
        active_public_workspace_id: Array.isArray(actionConfig.active_public_workspace_id)
            ? actionConfig.active_public_workspace_id
            : Array.isArray(legacyAnalyzeConfig.active_public_workspace_id)
                ? legacyAnalyzeConfig.active_public_workspace_id
                : [],
        window_unit: normalizeText(actionConfig.window_unit || legacyAnalyzeConfig.window_unit) || "pages",
        window_size: actionConfig.window_size ?? legacyAnalyzeConfig.window_size ?? "",
        window_percent: actionConfig.window_percent ?? legacyAnalyzeConfig.window_percent ?? "",
        max_retries_per_window: actionConfig.max_retries_per_window ?? legacyAnalyzeConfig.max_retries_per_window ?? 1,
    };
}

function getWorkflowDocumentActionSummary(workflow) {
    const config = getDocumentActionConfig(workflow);
    if (config.type === DOCUMENT_ACTION_ANALYZE) {
        const documentCount = config.document_ids.length;
        const unit = normalizeText(config.window_unit) || "pages";
        if (!documentCount) {
            return `Analyze by ${unit}`;
        }
        return `Analyze ${documentCount} ${documentCount === 1 ? "document" : "documents"} by ${unit}`;
    }

    if (config.type === DOCUMENT_ACTION_COMPARISON) {
        const rightCount = config.right_document_ids.length;
        if (!config.left_document_id) {
            return "Compare";
        }
        return `Compare one source to ${rightCount || 0} ${rightCount === 1 ? "target" : "targets"}`;
    }

    return "Search";
}

function updateSelectedDocumentsSummary() {
    if (!workflowSelectedDocumentsSummary) {
        return;
    }

    const selectedIds = getSelectedWorkspaceDocumentIds();
    if (!selectedIds.length) {
        workflowSelectedDocumentsSummary.textContent = "No workspace documents selected right now.";
        return;
    }

    workflowSelectedDocumentsSummary.textContent = `${selectedIds.length} workspace ${selectedIds.length === 1 ? "document is" : "documents are"} currently selected.`;
}

function updateDocumentActionFields() {
    const actionType = normalizeText(workflowDocumentActionTypeSelect?.value) || DOCUMENT_ACTION_NONE;
    const hasDocumentAction = actionType !== DOCUMENT_ACTION_NONE;
    setElementVisibility(workflowDocumentTargetsFields, hasDocumentAction);
    setElementVisibility(workflowAnalysisTargetFields, actionType === DOCUMENT_ACTION_ANALYZE);
    setElementVisibility(workflowComparisonTargetFields, actionType === DOCUMENT_ACTION_COMPARISON);
    syncWorkflowDocumentActionTooltip();

    if (workflowDocumentActionHelp) {
        workflowDocumentActionHelp.textContent = getDocumentActionDescription(actionType);
    }

    if (actionType === DOCUMENT_ACTION_COMPARISON) {
        syncWorkflowComparisonLeftOptions();
    }

    updateSelectedDocumentsSummary();
}

async function applySelectedWorkspaceDocumentsToWorkflow() {
    const selectedIds = getSelectedWorkspaceDocumentIds();
    if (!selectedIds.length) {
        showToast("Select one or more documents in the workspace first.", "warning");
        return;
    }

    const actionType = normalizeText(workflowDocumentActionTypeSelect?.value) || DOCUMENT_ACTION_NONE;
    const workflowMaxDocuments = getWorkflowDocumentActionMaxDocuments(actionType);

    const limitedSelectedIds = selectedIds.slice(0, workflowMaxDocuments);
    if (selectedIds.length > workflowMaxDocuments) {
        showToast(
            `${getDocumentActionDisplayLabel(actionType)} workflows currently support up to ${workflowMaxDocuments} documents. Applied the first ${workflowMaxDocuments} selected documents.`,
            "warning"
        );
    }
    if (actionType === DOCUMENT_ACTION_COMPARISON) {
        if (!workflowComparisonLeftDocumentIdInput || !workflowComparisonRightDocumentIdsInput) {
            return;
        }
        await loadWorkflowComparisonVersionTargets({
            selectedWorkspaceDocumentIds: limitedSelectedIds,
            selectedTargetIds: getSelectedWorkflowComparisonTargetIds(),
            preferredLeftId: normalizeText(workflowComparisonLeftDocumentIdInput.value),
        });
    } else if (workflowAnalysisDocumentIdsInput) {
        workflowAnalysisDocumentIdsInput.value = limitedSelectedIds.join(", ");
    }
    if (workflowAnalysisDocScopeSelect) {
        workflowAnalysisDocScopeSelect.value = "personal";
    }
}

function buildWorkflowSearchText(workflow) {
    return [
        workflow.name,
        workflow.description,
        workflow.task_prompt,
        getWorkflowRunnerLabel(workflow),
        getWorkflowTriggerLabel(workflow),
        getWorkflowAlertLabel(workflow),
        getWorkflowDocumentActionSummary(workflow),
    ].map((value) => normalizeText(value).toLowerCase()).join(" ");
}

function getWorkflowDisplayStatus(workflow) {
    const runtimeStatus = normalizeText(workflow?.status).toLowerCase();
    if (runtimeStatus === "running") {
        return "running";
    }

    return normalizeText(workflow?.last_run_status).toLowerCase();
}

function getWorkflowActivityState(workflow) {
    const conversationId = normalizeText(workflow?.conversation_id);
    const displayStatus = getWorkflowDisplayStatus(workflow);
    const hasRecordedRun = Boolean(normalizeText(workflow?.last_run_status) || normalizeText(workflow?.last_run_at));
    return {
        isAvailable: Boolean(conversationId && (displayStatus === "running" || hasRecordedRun)),
        url: buildWorkflowActivityUrl(conversationId, "", normalizeText(workflow?.id)),
    };
}

function getWorkflowRunTimestamp(workflow) {
    return getWorkflowDisplayStatus(workflow) === "running"
        ? normalizeText(workflow?.last_run_started_at || workflow?.last_run_at)
        : normalizeText(workflow?.last_run_at);
}

function buildWorkflowActionButtons(workflow) {
    const workflowId = escapeHtml(normalizeText(workflow.id));
    const isRunning = getWorkflowDisplayStatus(workflow) === "running";
    const activityState = getWorkflowActivityState(workflow);
    const buttons = [
        `<button type="button" class="btn btn-sm btn-primary" data-action="run" data-workflow-id="${workflowId}" ${isRunning ? "disabled" : ""} title="Run workflow">${isRunning ? '<i class="bi bi-hourglass-split me-1"></i>Running' : '<i class="bi bi-play-fill me-1"></i>Run'}</button>`,
    ];

    if (activityState.isAvailable) {
        buttons.push(`<button type="button" class="btn btn-sm btn-outline-info" data-action="activity" data-workflow-id="${workflowId}" title="Open activity view"><i class="bi bi-activity me-1"></i>Activity</button>`);
    }

    buttons.push(`<button type="button" class="btn btn-sm btn-outline-secondary" data-action="history" data-workflow-id="${workflowId}" title="View run history"><i class="bi bi-clock-history me-1"></i>History</button>`);
    buttons.push(`<button type="button" class="btn btn-sm btn-outline-secondary" data-action="edit" data-workflow-id="${workflowId}" title="Edit workflow"><i class="bi bi-pencil"></i></button>`);
    buttons.push(`<button type="button" class="btn btn-sm btn-outline-danger" data-action="delete" data-workflow-id="${workflowId}" title="Delete workflow"><i class="bi bi-trash"></i></button>`);

    return `<div class="workflow-action-buttons d-flex flex-wrap gap-1 justify-content-start justify-content-xl-end">${buttons.join("")}</div>`;
}

function buildWorkflowRunButton(workflow, includeLabel = true) {
    const workflowId = escapeHtml(normalizeText(workflow.id));
    const isRunning = getWorkflowDisplayStatus(workflow) === "running";
    const label = isRunning ? "Running" : "Run";
    const iconClass = isRunning ? "bi bi-hourglass-split" : "bi bi-play-fill";
    const iconSpacing = includeLabel ? " me-1" : "";
    return `<button type="button" class="btn btn-sm btn-primary" data-action="run" data-workflow-id="${workflowId}" ${isRunning ? "disabled" : ""} title="Run workflow" aria-label="Run workflow"><i class="${iconClass}${iconSpacing}"></i>${includeLabel ? label : ""}</button>`;
}

function buildWorkflowActivityButton(workflow, includeLabel = true) {
    const workflowId = escapeHtml(normalizeText(workflow.id));
    const activityState = getWorkflowActivityState(workflow);
    const iconSpacing = includeLabel ? " me-1" : "";
    return `<button type="button" class="btn btn-sm btn-outline-info" data-action="activity" data-workflow-id="${workflowId}" ${activityState.isAvailable ? "" : "disabled"} title="Open activity view" aria-label="Open activity view"><i class="bi bi-activity${iconSpacing}"></i>${includeLabel ? "Activity" : ""}</button>`;
}

function buildWorkflowCardMenu(workflow) {
    const workflowId = escapeHtml(normalizeText(workflow.id));
    const isRunning = getWorkflowDisplayStatus(workflow) === "running";
    const activityState = getWorkflowActivityState(workflow);
    const runDisabled = isRunning ? "disabled" : "";
    const activityDisabled = activityState.isAvailable ? "" : "disabled";

    return `
        <div class="dropdown workflow-card-menu">
            <button class="btn btn-sm btn-outline-secondary" type="button" data-bs-toggle="dropdown" aria-expanded="false" title="Workflow actions" aria-label="Workflow actions">
                <i class="bi bi-three-dots"></i>
            </button>
            <ul class="dropdown-menu dropdown-menu-end">
                <li><button type="button" class="dropdown-item" data-action="run" data-workflow-id="${workflowId}" ${runDisabled}><i class="bi bi-play-fill me-2"></i>Run</button></li>
                <li><button type="button" class="dropdown-item" data-action="activity" data-workflow-id="${workflowId}" ${activityDisabled}><i class="bi bi-activity me-2"></i>Activity</button></li>
                <li><button type="button" class="dropdown-item" data-action="history" data-workflow-id="${workflowId}"><i class="bi bi-clock-history me-2"></i>History</button></li>
                <li><button type="button" class="dropdown-item" data-action="edit" data-workflow-id="${workflowId}"><i class="bi bi-pencil me-2"></i>Edit</button></li>
                <li><hr class="dropdown-divider"></li>
                <li><button type="button" class="dropdown-item text-danger" data-action="delete" data-workflow-id="${workflowId}"><i class="bi bi-trash me-2"></i>Delete</button></li>
            </ul>
        </div>
    `;
}

function buildWorkflowCardActions(workflow) {
    return `
        <div class="workflow-card-primary-actions d-flex flex-wrap gap-1">
            ${buildWorkflowRunButton(workflow, true)}
            ${buildWorkflowActivityButton(workflow, true)}
        </div>
        ${buildWorkflowCardMenu(workflow)}
    `;
}

function getCustomEndpointOptions() {
    const endpointGroups = [
        {
            endpoints: Array.isArray(window.globalModelEndpoints) ? window.globalModelEndpoints : [],
            scope: "global",
            scopeLabel: "Global",
        },
        {
            endpoints: Array.isArray(window.workspaceModelEndpoints) ? window.workspaceModelEndpoints : [],
            scope: "user",
            scopeLabel: "Workspace",
        },
    ];

    const options = [];

    endpointGroups.forEach((group) => {
        group.endpoints.forEach((endpoint) => {
            if (!endpoint || endpoint.enabled === false) {
                return;
            }

            const enabledModels = Array.isArray(endpoint.models)
                ? endpoint.models.filter((model) => model && model.enabled !== false)
                : [];

            if (!enabledModels.length) {
                return;
            }

            options.push({
                ...endpoint,
                models: enabledModels,
                scope: group.scope,
                scopeLabel: group.scopeLabel,
            });
        });
    });

    return options;
}

function getEndpointDisplayName(endpoint) {
    const endpointName = normalizeText(endpoint?.name) || "Unnamed Endpoint";
    const scopeLabel = normalizeText(endpoint?.scopeLabel) || "Global";
    return `${scopeLabel}: ${endpointName}`;
}

function getModelDisplayName(model) {
    return normalizeText(model?.displayName || model?.deploymentName || model?.modelName || model?.name || model?.id) || "Unnamed Model";
}

function getAgentOptionKey(agent) {
    const scope = agent?.is_global ? "global" : "personal";
    return `${scope}:${normalizeText(agent?.id || agent?.name)}`;
}

function getSelectedAgentOption() {
    const selectedKey = normalizeText(workflowAgentSelect?.value);
    return agentOptions.find((agent) => getAgentOptionKey(agent) === selectedKey) || null;
}

function getSelectedEndpointOption() {
    const endpointId = normalizeText(workflowModelEndpointSelect?.value);
    return getCustomEndpointOptions().find((endpoint) => normalizeText(endpoint.id) === endpointId) || null;
}

function refreshWorkflowSummary(items) {
    if (!workflowsSummary) {
        return;
    }

    const totalCount = workflows.length;
    const scheduledCount = workflows.filter((workflow) => workflow.trigger_type === "interval").length;
    const activeCount = workflows.filter((workflow) => workflow.trigger_type === "interval" && workflow.is_enabled).length;
    const visibleCount = items.length;

    workflowsSummary.textContent = `${visibleCount} shown of ${totalCount} workflows. ${scheduledCount} scheduled, ${activeCount} active.`;
}

function renderWorkflowEmptyState(message) {
    if (workflowsTableBody) {
        workflowsTableBody.innerHTML = `
            <tr>
                <td colspan="5" class="text-center text-muted py-4">${escapeHtml(message)}</td>
            </tr>
        `;
    }

    if (workflowsGridView) {
        workflowsGridView.innerHTML = `<div class="col-12 text-center text-muted py-4">${escapeHtml(message)}</div>`;
    }
}

function renderWorkflowTable(items) {
    if (!workflowsTableBody) {
        return;
    }

    if (!items.length) {
        workflowsTableBody.innerHTML = `
            <tr>
                <td colspan="5" class="text-center text-muted py-4">${escapeHtml(workflows.length ? "No workflows match the current search." : "No workflows created yet.")}</td>
            </tr>
        `;
        return;
    }

    workflowsTableBody.innerHTML = items.map((workflow) => {
        const workflowName = escapeHtml(normalizeText(workflow.name) || "Untitled Workflow");
        const description = escapeHtml(truncateDescription(normalizeText(workflow.description), 120));
        const runnerLabel = escapeHtml(getWorkflowRunnerLabel(workflow));
        const triggerLabel = escapeHtml(getWorkflowTriggerLabel(workflow));
        const displayStatus = getWorkflowDisplayStatus(workflow);
        const lastRunStatus = displayStatus ? buildStatusBadge(displayStatus) : '<span class="text-muted small">Never run</span>';
        const runTimestamp = getWorkflowRunTimestamp(workflow);
        const lastRunAt = runTimestamp
            ? `<div class="small text-muted mt-1">${escapeHtml(formatDateTime(runTimestamp))}</div>`
            : "";
        const lastRunPreview = displayStatus === "running"
            ? '<div class="workflow-meta text-primary mt-1">Run in progress. Open Activity to follow the live timeline.</div>'
            : normalizeText(workflow.last_run_response_preview)
            ? `<div class="workflow-meta workflow-response-preview mt-1">${escapeHtml(truncateDescription(workflow.last_run_response_preview, 160))}</div>`
            : normalizeText(workflow.last_run_error)
                ? `<div class="workflow-meta text-danger mt-1">${escapeHtml(truncateDescription(workflow.last_run_error, 120))}</div>`
                : "";
        const nextRunMeta = workflow.trigger_type === "interval" && workflow.next_run_at
            ? `<div class="workflow-meta mt-1">Next run: ${escapeHtml(formatDateTime(workflow.next_run_at))}</div>`
            : "";
        const alertMeta = `<div class="workflow-meta mt-1">Alert: ${escapeHtml(getWorkflowAlertLabel(workflow))}</div>`;
        const actionConfig = getDocumentActionConfig(workflow);
        const reviewMeta = actionConfig.type !== DOCUMENT_ACTION_NONE
            ? `<div class="workflow-meta mt-1 text-info">${escapeHtml(getWorkflowDocumentActionSummary(workflow))}</div>`
            : "";
        const conversationMeta = workflow.conversation_id
            ? '<div class="workflow-meta mt-1"><i class="bi bi-chat-left-text me-1"></i>Conversation ready</div>'
            : "";
        const disabledMeta = workflow.trigger_type === "interval" && !workflow.is_enabled
            ? '<div class="workflow-meta mt-1 text-warning">Scheduled runs are paused.</div>'
            : "";
        const runnerMeta = workflow.runner_type === "agent"
            ? '<div class="workflow-meta mt-1">Uses your selected agent configuration.</div>'
            : '<div class="workflow-meta mt-1">Uses direct model execution.</div>';
        return `
            <tr>
                <td>
                    <div class="fw-semibold">${workflowName}</div>
                    ${description ? `<div class="workflow-meta mt-1">${description}</div>` : ""}
                    ${conversationMeta}
                </td>
                <td>
                    <div>${runnerLabel}</div>
                    ${runnerMeta}
                </td>
                <td>
                    <div>${escapeHtml(triggerLabel)}</div>
                    ${alertMeta}
                    ${reviewMeta}
                    ${disabledMeta}
                    ${nextRunMeta}
                </td>
                <td>
                    <div>${lastRunStatus}</div>
                    ${lastRunAt}
                    ${lastRunPreview}
                </td>
                <td>
                    ${buildWorkflowActionButtons(workflow)}
                </td>
            </tr>
        `;
    }).join("");
}

function renderWorkflowGrid(items) {
    if (!workflowsGridView) {
        return;
    }

    if (!items.length) {
        workflowsGridView.innerHTML = `<div class="col-12 text-center text-muted py-4">${escapeHtml(workflows.length ? "No workflows match the current search." : "No workflows created yet.")}</div>`;
        return;
    }

    workflowsGridView.innerHTML = items.map((workflow) => {
        const workflowId = escapeHtml(normalizeText(workflow.id));
        const workflowName = escapeHtml(normalizeText(workflow.name) || "Untitled Workflow");
        const description = escapeHtml(truncateDescription(normalizeText(workflow.description) || "No description available.", 180));
        const displayStatus = getWorkflowDisplayStatus(workflow);
        const statusBadge = displayStatus ? buildStatusBadge(displayStatus) : '<span class="text-muted small">Never run</span>';
        const runTimestamp = getWorkflowRunTimestamp(workflow);
        const previewText = displayStatus === "running"
            ? "Run in progress. Open Activity to follow the live timeline."
            : normalizeText(workflow.last_run_response_preview) || normalizeText(workflow.last_run_error) || "No recent response preview available.";
        const runnerLabel = escapeHtml(getWorkflowRunnerLabel(workflow));
        const triggerLabel = escapeHtml(getWorkflowTriggerLabel(workflow));
        const alertLabel = escapeHtml(getWorkflowAlertLabel(workflow));
        const reviewLabel = escapeHtml(getWorkflowDocumentActionSummary(workflow));

        return `
            <div class="col-12 col-md-6 col-xl-4">
                <div class="card item-card workflow-item-card h-100" data-workflow-id="${workflowId}" tabindex="0" aria-label="Edit workflow ${workflowName}">
                    <div class="card-body d-flex flex-column">
                        <div class="d-flex justify-content-between align-items-start gap-2 mb-2">
                            <div class="item-card-icon mb-0"><i class="bi bi-diagram-3"></i></div>
                            ${statusBadge}
                        </div>
                        <h6 class="card-title mb-2">${workflowName}</h6>
                        <p class="card-text small text-muted mb-3">${description}</p>
                        <div class="workflow-grid-meta mb-3">
                            <div class="workflow-grid-meta-row"><span>Runner</span><span>${runnerLabel}</span></div>
                            <div class="workflow-grid-meta-row"><span>Trigger</span><span>${triggerLabel}</span></div>
                            <div class="workflow-grid-meta-row"><span>Alert</span><span>${alertLabel}</span></div>
                            <div class="workflow-grid-meta-row"><span>Action</span><span>${reviewLabel}</span></div>
                            <div class="workflow-grid-meta-row"><span>Last Run</span><span>${runTimestamp ? escapeHtml(formatDateTime(runTimestamp)) : "Never run"}</span></div>
                        </div>
                        <div class="workflow-grid-preview small text-muted mb-3">${escapeHtml(truncateDescription(previewText, 170))}</div>
                        <div class="workflow-grid-actions mt-auto">
                            ${buildWorkflowCardActions(workflow)}
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join("");
}

function renderWorkflowViews(items) {
    if (!items.length) {
        renderWorkflowEmptyState(workflows.length ? "No workflows match the current search." : "No workflows created yet.");
    } else {
        renderWorkflowTable(items);
        renderWorkflowGrid(items);
    }

    refreshWorkflowSummary(items);
}

function filterWorkflows() {
    const searchTerm = normalizeText(workflowsSearchInput?.value).toLowerCase();
    if (!searchTerm) {
        filteredWorkflows = [...workflows];
        renderWorkflowViews(filteredWorkflows);
        return;
    }

    filteredWorkflows = workflows.filter((workflow) => buildWorkflowSearchText(workflow).includes(searchTerm));
    renderWorkflowViews(filteredWorkflows);
}

async function loadAgentOptions(forceRefresh = false) {
    if (agentsLoaded && !forceRefresh) {
        return agentOptions;
    }

    try {
        const response = await fetch("/api/user/agents", {
            credentials: "same-origin",
        });
        const data = await response.json().catch(() => null);

        if (!response.ok) {
            throw new Error((data && typeof data === "object" && !Array.isArray(data) ? data.error : "") || "Unable to load agents right now.");
        }

        agentOptions = Array.isArray(data)
            ? data
            : Array.isArray(data?.agents)
                ? data.agents
                : [];
        agentsLoaded = true;
    } catch (error) {
        agentOptions = [];
        agentsLoaded = false;
        console.error("Failed to load workflow agents", error);
    }

    return agentOptions;
}

function populateAgentSelect(selectedAgent = null) {
    if (!workflowAgentSelect) {
        return;
    }

    const selectedAgentKey = selectedAgent ? getAgentOptionKey(selectedAgent) : "";
    const options = [...agentOptions].sort((left, right) => {
        const leftLabel = normalizeText(left.display_name || left.name).toLowerCase();
        const rightLabel = normalizeText(right.display_name || right.name).toLowerCase();
        return leftLabel.localeCompare(rightLabel);
    });

    workflowAgentSelect.innerHTML = "";

    if (!options.length && !selectedAgent) {
        workflowAgentSelect.innerHTML = '<option value="">No agents available</option>';
        workflowAgentSelect.disabled = true;
        if (workflowAgentHelp) {
            workflowAgentHelp.textContent = "No agents are currently available for workflow selection.";
        }
        return;
    }

    options.forEach((agent) => {
        const option = document.createElement("option");
        option.value = getAgentOptionKey(agent);
        option.textContent = `${normalizeText(agent.display_name || agent.name) || "Unnamed Agent"}${agent.is_global ? " (Global)" : ""}`;
        if (option.value === selectedAgentKey) {
            option.selected = true;
        }
        workflowAgentSelect.appendChild(option);
    });

    if (selectedAgent && !options.some((agent) => getAgentOptionKey(agent) === selectedAgentKey)) {
        const fallbackOption = document.createElement("option");
        fallbackOption.value = selectedAgentKey;
        fallbackOption.textContent = `${normalizeText(selectedAgent.display_name || selectedAgent.name) || "Current Agent"} (Unavailable)`;
        fallbackOption.selected = true;
        workflowAgentSelect.appendChild(fallbackOption);
    }

    workflowAgentSelect.disabled = false;
    if (workflowAgentHelp) {
        workflowAgentHelp.textContent = options.length
            ? "Choose a personal agent or a merged global agent."
            : "This workflow references an agent that is no longer available.";
    }
}

function refreshModelSourceOptions() {
    if (!workflowModelSourceSelect) {
        return;
    }

    const hasCustomEndpoints = getCustomEndpointOptions().length > 0;
    const customOption = Array.from(workflowModelSourceSelect.options).find((option) => option.value === "custom");
    if (customOption) {
        customOption.disabled = !hasCustomEndpoints;
    }

    if (!hasCustomEndpoints && workflowModelSourceSelect.value === "custom") {
        workflowModelSourceSelect.value = "default";
    }
}

function populateEndpointSelect(selectedEndpointId = "") {
    if (!workflowModelEndpointSelect) {
        return;
    }

    const endpoints = getCustomEndpointOptions();
    workflowModelEndpointSelect.innerHTML = "";

    if (!endpoints.length) {
        workflowModelEndpointSelect.innerHTML = '<option value="">No endpoints available</option>';
        workflowModelEndpointSelect.disabled = true;
        return;
    }

    endpoints.forEach((endpoint, index) => {
        const option = document.createElement("option");
        option.value = normalizeText(endpoint.id);
        option.textContent = getEndpointDisplayName(endpoint);
        if ((selectedEndpointId && option.value === selectedEndpointId) || (!selectedEndpointId && index === 0)) {
            option.selected = true;
        }
        workflowModelEndpointSelect.appendChild(option);
    });

    workflowModelEndpointSelect.disabled = false;
}

function populateModelSelect(selectedEndpointId = "", selectedModelId = "") {
    if (!workflowModelSelect) {
        return;
    }

    const endpoint = getCustomEndpointOptions().find((item) => normalizeText(item.id) === selectedEndpointId) || getSelectedEndpointOption();
    workflowModelSelect.innerHTML = "";

    if (!endpoint) {
        workflowModelSelect.innerHTML = '<option value="">No models available</option>';
        workflowModelSelect.disabled = true;
        return;
    }

    endpoint.models.forEach((model, index) => {
        const modelId = normalizeText(model.id);
        const option = document.createElement("option");
        option.value = modelId;
        option.textContent = getModelDisplayName(model);
        if ((selectedModelId && modelId === selectedModelId) || (!selectedModelId && index === 0)) {
            option.selected = true;
        }
        workflowModelSelect.appendChild(option);
    });

    workflowModelSelect.disabled = false;
}

function updateModelHelpText() {
    if (!workflowModelHelp) {
        return;
    }

    const source = normalizeText(workflowModelSourceSelect?.value) || "default";
    if (source === "default") {
        const currentLabel = normalizeText(currentEditingWorkflow?.model_binding_summary?.label);
        workflowModelHelp.textContent = currentLabel || "The default app model follows your admin-configured default selection or legacy GPT settings.";
        return;
    }

    const endpoint = getSelectedEndpointOption();
    const modelId = normalizeText(workflowModelSelect?.value);
    const model = endpoint?.models?.find((candidate) => normalizeText(candidate.id) === modelId);

    if (!endpoint || !model) {
        workflowModelHelp.textContent = "Choose an enabled endpoint and model for this workflow.";
        return;
    }

    workflowModelHelp.textContent = `${getEndpointDisplayName(endpoint)} / ${getModelDisplayName(model)}`;
}

function updateRunnerFields() {
    const runnerType = normalizeText(workflowRunnerTypeSelect?.value) || "model";
    const useAgent = runnerType === "agent";
    const useCustomModel = normalizeText(workflowModelSourceSelect?.value) === "custom";

    setElementVisibility(workflowAgentFields, useAgent);
    setElementVisibility(workflowModelFields, !useAgent);
    setElementVisibility(workflowModelEndpointGroup, !useAgent && useCustomModel);
    setElementVisibility(workflowModelGroup, !useAgent && useCustomModel);

    if (useAgent) {
        populateAgentSelect(currentEditingWorkflow?.selected_agent || null);
    } else {
        refreshModelSourceOptions();
        populateEndpointSelect(normalizeText(currentEditingWorkflow?.model_endpoint_id));
        populateModelSelect(normalizeText(workflowModelEndpointSelect?.value), normalizeText(currentEditingWorkflow?.model_id));
        updateModelHelpText();
    }
}

function updateScheduleConstraints() {
    if (!workflowScheduleValueInput || !workflowScheduleUnitSelect) {
        return;
    }

    const unit = normalizeText(workflowScheduleUnitSelect.value) || "seconds";
    const maxValue = unit === "hours" ? 24 : 59;
    workflowScheduleValueInput.max = String(maxValue);

    const currentValue = Number(workflowScheduleValueInput.value || 0);
    if (currentValue > maxValue) {
        workflowScheduleValueInput.value = String(maxValue);
    }
}

function updateTriggerFields() {
    const triggerType = normalizeText(workflowTriggerTypeSelect?.value) || "manual";
    const isInterval = triggerType === "interval";

    setElementVisibility(workflowScheduleValueGroup, isInterval);
    setElementVisibility(workflowScheduleUnitGroup, isInterval);
    setElementVisibility(workflowEnabledGroup, isInterval);

    if (workflowEnabledToggle && !isInterval) {
        workflowEnabledToggle.checked = true;
    }

    if (workflowTriggerHelp) {
        workflowTriggerHelp.textContent = isInterval
            ? "Interval workflows are picked up by the scheduler when the next run time is due."
            : "Manual workflows run only when you trigger them from the workspace.";
    }

    updateScheduleConstraints();
}

function resetWorkflowForm() {
    currentEditingWorkflow = null;

    if (workflowForm) {
        workflowForm.reset();
    }
    if (workflowIdInput) {
        workflowIdInput.value = "";
    }
    if (workflowNameInput) {
        workflowNameInput.value = "";
    }
    if (workflowDescriptionInput) {
        workflowDescriptionInput.value = "";
    }
    if (workflowTaskPromptInput) {
        workflowTaskPromptInput.value = "";
    }
    if (workflowRunnerTypeSelect) {
        workflowRunnerTypeSelect.value = "model";
    }
    if (workflowModelSourceSelect) {
        workflowModelSourceSelect.value = "default";
    }
    if (workflowTriggerTypeSelect) {
        workflowTriggerTypeSelect.value = "manual";
    }
    if (workflowScheduleValueInput) {
        workflowScheduleValueInput.value = "10";
    }
    if (workflowScheduleUnitSelect) {
        workflowScheduleUnitSelect.value = "seconds";
    }
    if (workflowEnabledToggle) {
        workflowEnabledToggle.checked = true;
    }
    if (workflowAlertPrioritySelect) {
        workflowAlertPrioritySelect.value = "none";
    }
    if (workflowDocumentActionTypeSelect) {
        workflowDocumentActionTypeSelect.value = DOCUMENT_ACTION_NONE;
    }
    if (workflowAnalysisDocScopeSelect) {
        workflowAnalysisDocScopeSelect.value = "personal";
    }
    if (workflowAnalysisDocumentIdsInput) {
        workflowAnalysisDocumentIdsInput.value = "";
    }
    if (workflowComparisonLeftDocumentIdInput) {
        workflowComparisonLeftDocumentIdInput.innerHTML = "";
        workflowComparisonLeftDocumentIdInput.disabled = true;
    }
    if (workflowComparisonRightDocumentIdsInput) {
        workflowComparisonRightDocumentIdsInput.innerHTML = "";
        workflowComparisonRightDocumentIdsInput.disabled = true;
    }
    if (workflowAnalysisGroupIdsInput) {
        workflowAnalysisGroupIdsInput.value = "";
    }
    if (workflowAnalysisPublicWorkspaceIdsInput) {
        workflowAnalysisPublicWorkspaceIdsInput.value = "";
    }
    if (workflowAnalysisWindowUnitSelect) {
        workflowAnalysisWindowUnitSelect.value = "pages";
    }
    if (workflowAnalysisWindowSizeInput) {
        workflowAnalysisWindowSizeInput.value = "";
    }
    if (workflowAnalysisWindowPercentInput) {
        workflowAnalysisWindowPercentInput.value = "";
    }
    if (workflowAnalysisRetriesInput) {
        workflowAnalysisRetriesInput.value = "1";
    }
    if (workflowSaveBtn) {
        workflowSaveBtn.disabled = false;
        workflowSaveBtn.textContent = "Save Workflow";
    }
    if (workflowModalLabel) {
        workflowModalLabel.textContent = "Create Workflow";
    }

    populateAgentSelect(null);
    refreshModelSourceOptions();
    populateEndpointSelect("");
    populateModelSelect(normalizeText(workflowModelEndpointSelect?.value), "");
    updateRunnerFields();
    updateTriggerFields();
    updateDocumentActionFields();
}

async function openWorkflowModal(workflow = null) {
    if (!workflowModal) {
        return;
    }

    await loadAgentOptions(true);
    resetWorkflowForm();
    currentEditingWorkflow = workflow;

    if (workflow) {
        if (workflowIdInput) {
            workflowIdInput.value = normalizeText(workflow.id);
        }
        if (workflowNameInput) {
            workflowNameInput.value = normalizeText(workflow.name);
        }
        if (workflowDescriptionInput) {
            workflowDescriptionInput.value = normalizeText(workflow.description);
        }
        if (workflowTaskPromptInput) {
            workflowTaskPromptInput.value = normalizeText(workflow.task_prompt);
        }
        if (workflowRunnerTypeSelect) {
            workflowRunnerTypeSelect.value = normalizeText(workflow.runner_type) || "model";
        }
        if (workflowTriggerTypeSelect) {
            workflowTriggerTypeSelect.value = normalizeText(workflow.trigger_type) || "manual";
        }
        if (workflowEnabledToggle) {
            workflowEnabledToggle.checked = workflow.is_enabled !== false;
        }
        if (workflowAlertPrioritySelect) {
            workflowAlertPrioritySelect.value = normalizeText(workflow.alert_priority).toLowerCase() || "none";
        }
        const documentAction = getDocumentActionConfig(workflow);
        if (workflowDocumentActionTypeSelect) {
            workflowDocumentActionTypeSelect.value = documentAction.type;
        }
        if (workflowAnalysisDocScopeSelect) {
            workflowAnalysisDocScopeSelect.value = documentAction.doc_scope;
        }
        if (workflowAnalysisDocumentIdsInput) {
            workflowAnalysisDocumentIdsInput.value = joinCsvList(documentAction.document_ids);
        }
        if (workflowAnalysisGroupIdsInput) {
            workflowAnalysisGroupIdsInput.value = joinCsvList(documentAction.active_group_ids);
        }
        if (workflowAnalysisPublicWorkspaceIdsInput) {
            workflowAnalysisPublicWorkspaceIdsInput.value = joinCsvList(documentAction.active_public_workspace_id);
        }
        if (workflowAnalysisWindowUnitSelect) {
            workflowAnalysisWindowUnitSelect.value = documentAction.window_unit;
        }
        if (workflowAnalysisWindowSizeInput) {
            workflowAnalysisWindowSizeInput.value = documentAction.window_size;
        }
        if (workflowAnalysisWindowPercentInput) {
            workflowAnalysisWindowPercentInput.value = documentAction.window_percent;
        }
        if (workflowAnalysisRetriesInput) {
            workflowAnalysisRetriesInput.value = String(documentAction.max_retries_per_window);
        }
        if (workflowScheduleValueInput) {
            workflowScheduleValueInput.value = String(workflow.schedule?.value || 10);
        }
        if (workflowScheduleUnitSelect) {
            workflowScheduleUnitSelect.value = normalizeText(workflow.schedule?.unit) || "seconds";
        }
        if (workflowModalLabel) {
            workflowModalLabel.textContent = "Edit Workflow";
        }

        if (workflow.runner_type === "agent") {
            populateAgentSelect(workflow.selected_agent || null);
        } else {
            const useCustomModel = Boolean(normalizeText(workflow.model_endpoint_id) && normalizeText(workflow.model_id));
            if (workflowModelSourceSelect) {
                workflowModelSourceSelect.value = useCustomModel ? "custom" : "default";
            }
            refreshModelSourceOptions();
            populateEndpointSelect(normalizeText(workflow.model_endpoint_id));
            populateModelSelect(normalizeText(workflow.model_endpoint_id || workflowModelEndpointSelect?.value), normalizeText(workflow.model_id));
        }
    }

    const documentAction = workflow ? getDocumentActionConfig(workflow) : null;
    if (documentAction?.type === DOCUMENT_ACTION_COMPARISON) {
        const savedTargetIds = [documentAction.left_document_id, ...documentAction.right_document_ids].filter(Boolean);
        setWorkflowComparisonSavedTargets(savedTargetIds, documentAction.left_document_id);
    } else {
        setWorkflowComparisonSavedTargets([], "");
    }

    updateRunnerFields();
    updateTriggerFields();
    updateDocumentActionFields();
    workflowModal.show();
}

function buildWorkflowPayload() {
    const runnerType = normalizeText(workflowRunnerTypeSelect?.value) || "model";
    const triggerType = normalizeText(workflowTriggerTypeSelect?.value) || "manual";
    const documentActionType = normalizeText(workflowDocumentActionTypeSelect?.value) || DOCUMENT_ACTION_NONE;
    const analysisDocumentIds = parseCsvList(workflowAnalysisDocumentIdsInput?.value);
    const comparisonLeftDocumentId = normalizeText(workflowComparisonLeftDocumentIdInput?.value);
    const comparisonTargetDocumentIds = getSelectedWorkflowComparisonTargetIds();
    const comparisonRightDocumentIds = comparisonTargetDocumentIds.filter((documentId) => documentId !== comparisonLeftDocumentId);
    const analysisGroupIds = parseCsvList(workflowAnalysisGroupIdsInput?.value);
    const analysisPublicWorkspaceIds = parseCsvList(workflowAnalysisPublicWorkspaceIdsInput?.value);
    const rawWindowSize = normalizeText(workflowAnalysisWindowSizeInput?.value);
    const rawWindowPercent = normalizeText(workflowAnalysisWindowPercentInput?.value);
    const rawRetries = normalizeText(workflowAnalysisRetriesInput?.value) || "1";
    const payload = {
        id: normalizeText(workflowIdInput?.value),
        name: normalizeText(workflowNameInput?.value),
        description: normalizeText(workflowDescriptionInput?.value),
        task_prompt: normalizeText(workflowTaskPromptInput?.value),
        runner_type: runnerType,
        trigger_type: triggerType,
        alert_priority: normalizeText(workflowAlertPrioritySelect?.value).toLowerCase() || "none",
        is_enabled: triggerType === "interval" ? Boolean(workflowEnabledToggle?.checked) : true,
        schedule: {},
        selected_agent: {},
        model_endpoint_id: "",
        model_id: "",
        document_action: {
            type: documentActionType,
            document_ids: documentActionType === DOCUMENT_ACTION_ANALYZE
                ? analysisDocumentIds
                : comparisonTargetDocumentIds,
            left_document_id: documentActionType === DOCUMENT_ACTION_COMPARISON ? comparisonLeftDocumentId : "",
            right_document_ids: documentActionType === DOCUMENT_ACTION_COMPARISON ? comparisonRightDocumentIds : [],
            doc_scope: normalizeText(workflowAnalysisDocScopeSelect?.value) || "personal",
            active_group_ids: documentActionType !== DOCUMENT_ACTION_NONE ? analysisGroupIds : [],
            active_public_workspace_id: documentActionType !== DOCUMENT_ACTION_NONE ? analysisPublicWorkspaceIds : [],
            window_unit: normalizeText(workflowAnalysisWindowUnitSelect?.value) || "pages",
            window_size: rawWindowSize ? Number(rawWindowSize) : null,
            window_percent: rawWindowPercent ? Number(rawWindowPercent) : null,
            max_retries_per_window: Number(rawRetries),
        },
        analyze: {
            enabled: documentActionType === DOCUMENT_ACTION_ANALYZE,
            document_ids: documentActionType === DOCUMENT_ACTION_ANALYZE ? analysisDocumentIds : [],
            doc_scope: normalizeText(workflowAnalysisDocScopeSelect?.value) || "personal",
            active_group_ids: documentActionType === DOCUMENT_ACTION_ANALYZE ? analysisGroupIds : [],
            active_public_workspace_id: documentActionType === DOCUMENT_ACTION_ANALYZE ? analysisPublicWorkspaceIds : [],
            window_unit: normalizeText(workflowAnalysisWindowUnitSelect?.value) || "pages",
            window_size: rawWindowSize ? Number(rawWindowSize) : null,
            window_percent: rawWindowPercent ? Number(rawWindowPercent) : null,
            max_retries_per_window: Number(rawRetries),
        },
    };

    if (!payload.name) {
        throw new Error("Workflow name is required.");
    }
    if (!payload.task_prompt) {
        throw new Error("Task prompt is required.");
    }
    if (documentActionType === DOCUMENT_ACTION_ANALYZE && !payload.document_action.document_ids.length) {
        throw new Error("Add one or more document ids for analysis.");
    }
    if (documentActionType === DOCUMENT_ACTION_COMPARISON && payload.document_action.document_ids.length < 2) {
        throw new Error("Select at least two document versions for compare.");
    }
    if (documentActionType === DOCUMENT_ACTION_COMPARISON && !payload.document_action.left_document_id) {
        throw new Error("Add one Source document id for compare.");
    }
    if (documentActionType === DOCUMENT_ACTION_COMPARISON && !payload.document_action.right_document_ids.length) {
        throw new Error("Add one or more Target document ids for compare.");
    }
    if (documentActionType !== DOCUMENT_ACTION_NONE && !isDocumentActionEnabled(documentActionType)) {
        throw new Error(`${getDocumentActionDisplayLabel(documentActionType)} is currently disabled by an administrator.`);
    }
    const documentActionCount = documentActionType === DOCUMENT_ACTION_COMPARISON
        ? 1 + payload.document_action.right_document_ids.length
        : payload.document_action.document_ids.length;
    const workflowMaxDocuments = getWorkflowDocumentActionMaxDocuments(documentActionType);
    if (documentActionCount > workflowMaxDocuments) {
        throw new Error(`${getDocumentActionDisplayLabel(documentActionType)} workflows support up to ${workflowMaxDocuments} documents per run.`);
    }
    if (documentActionType !== DOCUMENT_ACTION_NONE && rawWindowSize && (!Number.isInteger(payload.document_action.window_size) || payload.document_action.window_size < 1)) {
        throw new Error("Window size must be a whole number greater than zero.");
    }
    if (documentActionType !== DOCUMENT_ACTION_NONE && rawWindowPercent && (!Number.isInteger(payload.document_action.window_percent) || payload.document_action.window_percent < 1 || payload.document_action.window_percent > 100)) {
        throw new Error("Window percent must be a whole number between 1 and 100.");
    }
    if (documentActionType !== DOCUMENT_ACTION_NONE && rawWindowSize && rawWindowPercent) {
        throw new Error("Choose either a fixed window size or a window percent, not both.");
    }
    if (documentActionType !== DOCUMENT_ACTION_NONE && (!Number.isInteger(payload.document_action.max_retries_per_window) || payload.document_action.max_retries_per_window < 0 || payload.document_action.max_retries_per_window > 5)) {
        throw new Error("Retries per window must be between 0 and 5.");
    }

    if (runnerType === "agent") {
        const selectedAgent = getSelectedAgentOption();
        if (!selectedAgent) {
            throw new Error("Select an agent for this workflow.");
        }
        payload.selected_agent = {
            id: normalizeText(selectedAgent.id),
            name: normalizeText(selectedAgent.name),
            is_global: Boolean(selectedAgent.is_global),
        };
    } else if (normalizeText(workflowModelSourceSelect?.value) === "custom") {
        const endpointId = normalizeText(workflowModelEndpointSelect?.value);
        const modelId = normalizeText(workflowModelSelect?.value);
        if (!endpointId || !modelId) {
            throw new Error("Select both an endpoint and a model for this workflow.");
        }
        payload.model_endpoint_id = endpointId;
        payload.model_id = modelId;
    }

    if (triggerType === "interval") {
        const scheduleValue = Number(workflowScheduleValueInput?.value || 0);
        const scheduleUnit = normalizeText(workflowScheduleUnitSelect?.value) || "seconds";
        if (!Number.isInteger(scheduleValue) || scheduleValue < 1) {
            throw new Error("Schedule value must be at least 1.");
        }
        payload.schedule = {
            value: scheduleValue,
            unit: scheduleUnit,
        };
    }

    return payload;
}

async function saveWorkflow(event) {
    event.preventDefault();

    if (!workflowSaveBtn) {
        return;
    }

    let payload;
    try {
        payload = buildWorkflowPayload();
    } catch (error) {
        showToast(escapeHtml(error.message || "Unable to save workflow."), "danger");
        return;
    }

    workflowSaveBtn.disabled = true;
    workflowSaveBtn.textContent = "Saving...";

    try {
        const response = await fetch("/api/user/workflows", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            credentials: "same-origin",
            body: JSON.stringify(payload),
        });

        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || "Unable to save workflow right now.");
        }

        workflowModal?.hide();
        showToast("Workflow saved.", "success");
        await fetchUserWorkflows();
    } catch (error) {
        showToast(escapeHtml(error.message || "Unable to save workflow right now."), "danger");
    } finally {
        workflowSaveBtn.disabled = false;
        workflowSaveBtn.textContent = "Save Workflow";
    }
}

function renderHistoryLoading() {
    if (!workflowHistoryBody) {
        return;
    }

    workflowHistoryBody.innerHTML = `
        <tr class="table-loading-row">
            <td colspan="5">
                <div class="spinner-border spinner-border-sm me-2" role="status"><span class="visually-hidden">Loading...</span></div>
                Loading run history...
            </td>
        </tr>
    `;
}

function renderRunHistory(runs) {
    if (!workflowHistoryBody) {
        return;
    }

    if (!Array.isArray(runs) || !runs.length) {
        workflowHistoryBody.innerHTML = `
            <tr>
                <td colspan="5" class="text-center text-muted py-3">No workflow runs yet.</td>
            </tr>
        `;
        return;
    }

    workflowHistoryBody.innerHTML = runs.map((run) => {
        const conversationId = normalizeText(run.conversation_id);
        const conversationUrl = buildWorkflowConversationUrl(conversationId);
        const activityUrl = buildWorkflowActivityUrl(conversationId, normalizeText(run.id), currentHistoryWorkflowId);
        const details = normalizeText(run.error)
            ? `<div class="text-danger small">${escapeHtml(run.error)}</div>`
            : normalizeText(run.response_preview)
                ? `<div class="small workflow-response-preview">${escapeHtml(run.response_preview)}</div>`
                : '<div class="text-muted small">No preview available.</div>';
        const conversationLink = conversationUrl
            ? `
                <div class="d-flex flex-wrap gap-2">
                    <a class="btn btn-sm btn-outline-primary" href="${escapeHtml(conversationUrl)}"><i class="bi bi-chat-dots-fill me-1"></i>Open workflow</a>
                    <a class="btn btn-sm btn-outline-info" href="${escapeHtml(activityUrl)}" target="_blank" rel="noopener"><i class="bi bi-activity me-1"></i>Open activity view</a>
                </div>
                <div class="small text-muted mt-1">${escapeHtml(conversationId)}</div>
            `
            : '<div class="text-muted small">Not created yet.</div>';

        return `
            <tr>
                <td>${buildStatusBadge(run.status)}</td>
                <td>
                    <div>${escapeHtml(formatDateTime(run.started_at) || "-")}</div>
                    ${run.completed_at ? `<div class="small text-muted">Completed ${escapeHtml(formatDateTime(run.completed_at))}</div>` : ""}
                </td>
                <td>${escapeHtml(normalizeText(run.trigger_source) || "manual")}</td>
                <td>${details}</td>
                <td>${conversationLink}</td>
            </tr>
        `;
    }).join("");
}

async function openHistoryModalForWorkflow(workflow) {
    if (!workflow || !workflowHistoryModal) {
        return;
    }

    currentHistoryWorkflowId = normalizeText(workflow.id);
    if (workflowHistoryModalLabel) {
        workflowHistoryModalLabel.textContent = `${normalizeText(workflow.name) || "Workflow"} Run History`;
    }
    if (workflowHistoryConversationId) {
        workflowHistoryConversationId.textContent = normalizeText(workflow.conversation_id) || "Not created yet.";
    }
    updateWorkflowConversationLink(workflowHistoryConversationLink, workflow.conversation_id);
    renderHistoryLoading();
    workflowHistoryModal.show();

    try {
        const response = await fetch(`/api/user/workflows/${encodeURIComponent(currentHistoryWorkflowId)}/runs`, {
            credentials: "same-origin",
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || "Unable to load workflow history.");
        }
        renderRunHistory(data.runs || []);
    } catch (error) {
        workflowHistoryBody.innerHTML = `
            <tr>
                <td colspan="5" class="text-center text-danger py-3">${escapeHtml(error.message || "Unable to load workflow history.")}</td>
            </tr>
        `;
    }
}

function openWorkflowActivity(workflow) {
    const activityState = getWorkflowActivityState(workflow);
    if (!activityState.isAvailable || !activityState.url) {
        return;
    }

    const activityWindow = window.open(activityState.url, "_blank", "noopener");
    if (!activityWindow) {
        window.location.href = activityState.url;
    }
}

async function runWorkflow(workflow) {
    if (!workflow) {
        return;
    }

    const previousRuntimeFields = {
        status: workflow.status,
        last_run_status: workflow.last_run_status,
        last_run_started_at: workflow.last_run_started_at,
    };

    workflow.status = "running";
    workflow.last_run_status = "running";
    workflow.last_run_started_at = new Date().toISOString();
    filterWorkflows();

    try {
        const response = await fetch(`/api/user/workflows/${encodeURIComponent(workflow.id)}/run`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            credentials: "same-origin",
        });
        const data = await response.json().catch(() => ({}));

        if (!response.ok || data.success === false) {
            throw new Error(data.run?.error || data.error || "Workflow run failed.");
        }

        showToast("Workflow run completed.", "success");
        window.dispatchEvent(new CustomEvent("workflow-alert-refresh-requested"));
        await fetchUserWorkflows();

        if (currentHistoryWorkflowId && currentHistoryWorkflowId === normalizeText(workflow.id)) {
            const refreshedWorkflow = workflows.find((item) => normalizeText(item.id) === currentHistoryWorkflowId) || workflow;
            await openHistoryModalForWorkflow(refreshedWorkflow);
        }
    } catch (error) {
        workflow.status = previousRuntimeFields.status;
        workflow.last_run_status = previousRuntimeFields.last_run_status;
        workflow.last_run_started_at = previousRuntimeFields.last_run_started_at;
        filterWorkflows();
        showToast(escapeHtml(error.message || "Workflow run failed."), "danger");
        await fetchUserWorkflows();
    }
}

function promptDeleteWorkflow(workflow) {
    if (!workflow || !workflowDeleteModal) {
        return;
    }

    workflowPendingDelete = workflow;
    if (workflowDeleteName) {
        workflowDeleteName.textContent = normalizeText(workflow.name) || "this workflow";
    }
    workflowDeleteModal.show();
}

async function deleteWorkflow() {
    if (!workflowPendingDelete || !workflowDeleteConfirmBtn) {
        return;
    }

    workflowDeleteConfirmBtn.disabled = true;
    workflowDeleteConfirmBtn.textContent = "Deleting...";

    try {
        const response = await fetch(`/api/user/workflows/${encodeURIComponent(workflowPendingDelete.id)}`, {
            method: "DELETE",
            credentials: "same-origin",
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || "Unable to delete workflow right now.");
        }

        workflowDeleteModal?.hide();
        showToast("Workflow deleted.", "success");
        workflowPendingDelete = null;
        await fetchUserWorkflows();
    } catch (error) {
        showToast(escapeHtml(error.message || "Unable to delete workflow right now."), "danger");
    } finally {
        workflowDeleteConfirmBtn.disabled = false;
        workflowDeleteConfirmBtn.textContent = "Delete Workflow";
    }
}

function findWorkflowById(workflowId) {
    return workflows.find((workflow) => normalizeText(workflow.id) === normalizeText(workflowId)) || null;
}

function isWorkflowCardActionTarget(target) {
    return Boolean(target.closest('a, button, input, label, select, textarea, .dropdown-menu'));
}

function handleWorkflowActionClick(event) {
    const button = event.target.closest("button[data-action]");
    if (!button || button.disabled) {
        return;
    }

    event.preventDefault();
    event.stopPropagation();

    const workflow = findWorkflowById(button.getAttribute("data-workflow-id"));
    if (!workflow) {
        return;
    }

    const action = button.getAttribute("data-action");
    if (action === "run") {
        runWorkflow(workflow);
    } else if (action === "activity") {
        openWorkflowActivity(workflow);
    } else if (action === "history") {
        openHistoryModalForWorkflow(workflow);
    } else if (action === "edit") {
        openWorkflowModal(workflow);
    } else if (action === "delete") {
        promptDeleteWorkflow(workflow);
    }
}

function handleWorkflowGridClick(event) {
    if (event.target.closest("button[data-action]")) {
        handleWorkflowActionClick(event);
        return;
    }

    if (isWorkflowCardActionTarget(event.target)) {
        return;
    }

    const card = event.target.closest(".workflow-item-card[data-workflow-id]");
    if (!card) {
        return;
    }

    const workflow = findWorkflowById(card.getAttribute("data-workflow-id"));
    if (workflow) {
        openWorkflowModal(workflow);
    }
}

function handleWorkflowGridKeydown(event) {
    if (isWorkflowCardActionTarget(event.target) || (event.key !== "Enter" && event.key !== " ")) {
        return;
    }

    const card = event.target.closest(".workflow-item-card[data-workflow-id]");
    if (!card) {
        return;
    }

    const workflow = findWorkflowById(card.getAttribute("data-workflow-id"));
    if (workflow) {
        event.preventDefault();
        openWorkflowModal(workflow);
    }
}

async function fetchUserWorkflows() {
    if (!workflowsTableBody) {
        return [];
    }

    renderWorkflowEmptyState("Loading workflows...");

    try {
        const response = await fetch("/api/user/workflows", {
            credentials: "same-origin",
        });
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(data.error || "Unable to load workflows right now.");
        }

        workflows = Array.isArray(data.workflows) ? data.workflows : [];
        filterWorkflows();
        return workflows;
    } catch (error) {
        workflows = [];
        renderWorkflowEmptyState(error.message || "Unable to load workflows right now.");
        refreshWorkflowSummary([]);
        return [];
    }
}

function initializeWorkflowEvents() {
    if (!workflowsTableBody) {
        return;
    }

    createWorkflowBtn?.addEventListener("click", () => {
        openWorkflowModal();
    });
    workflowsSearchInput?.addEventListener("input", filterWorkflows);
    workflowsTableBody.addEventListener("click", handleWorkflowActionClick);
    workflowsGridView?.addEventListener("click", handleWorkflowGridClick);
    workflowsGridView?.addEventListener("keydown", handleWorkflowGridKeydown);
    workflowForm?.addEventListener("submit", saveWorkflow);
    workflowDeleteConfirmBtn?.addEventListener("click", deleteWorkflow);
    workflowRunnerTypeSelect?.addEventListener("change", updateRunnerFields);
    workflowModelSourceSelect?.addEventListener("change", updateRunnerFields);
    workflowModelEndpointSelect?.addEventListener("change", () => {
        populateModelSelect(normalizeText(workflowModelEndpointSelect.value), "");
        updateModelHelpText();
    });
    workflowModelSelect?.addEventListener("change", updateModelHelpText);
    workflowTriggerTypeSelect?.addEventListener("change", updateTriggerFields);
    workflowScheduleUnitSelect?.addEventListener("change", updateScheduleConstraints);
    workflowDocumentActionTypeSelect?.addEventListener("change", updateDocumentActionFields);
    workflowComparisonRightDocumentIdsInput?.addEventListener("change", () => {
        syncWorkflowComparisonLeftOptions();
    });
    workflowUseSelectedDocumentsBtn?.addEventListener("click", () => {
        applySelectedWorkspaceDocumentsToWorkflow().catch((error) => {
            showToast(escapeHtml(error.message || "Unable to apply selected documents."), "danger");
        });
    });
    workflowModalEl?.addEventListener("hidden.bs.modal", resetWorkflowForm);
    workflowDeleteModalEl?.addEventListener("hidden.bs.modal", () => {
        workflowPendingDelete = null;
        if (workflowDeleteConfirmBtn) {
            workflowDeleteConfirmBtn.disabled = false;
            workflowDeleteConfirmBtn.textContent = "Delete Workflow";
        }
    });

    setupViewToggle("workflows", "workflowsViewPreference", (mode) => {
        switchViewContainers(mode, workflowsListView, workflowsGridView);
    });
}

window.fetchUserWorkflows = fetchUserWorkflows;

initializeWorkflowEvents();