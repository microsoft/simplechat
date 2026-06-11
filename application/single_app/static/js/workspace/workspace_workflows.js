// workspace_workflows.js

import { showToast } from "../chat/chat-toast.js";
import {
    ensureDocumentPickerReady,
    setEffectiveScopes,
} from "../chat/chat-documents.js";
import { escapeHtml, truncateDescription, setupViewToggle, switchViewContainers } from "./view-utils.js";

const workflowWorkspaceConfig = {
    scope: "personal",
    apiBase: "/api/user/workflows",
    agentsApi: "/api/user/agents",
    documentVersionsApi: (documentId) => `/api/documents/${encodeURIComponent(documentId)}/versions`,
    activityScope: "personal",
    workspaceEndpointScope: "user",
    workspaceEndpointLabel: "Workspace",
    documentScope: "personal",
    selectedDocumentsLabel: "workspace",
    getActiveGroupId: () => "",
    getSelectedDocumentIds: () => {
        if (window.selectedDocuments instanceof Set) {
            return Array.from(window.selectedDocuments).map((value) => normalizeText(value)).filter(Boolean);
        }

        if (Array.isArray(window.selectedDocuments)) {
            return window.selectedDocuments.map((value) => normalizeText(value)).filter(Boolean);
        }

        return [];
    },
    ...(window.workflowWorkspaceConfig && typeof window.workflowWorkspaceConfig === "object" ? window.workflowWorkspaceConfig : {}),
};

function getWorkflowApiBase() {
    return normalizeText(workflowWorkspaceConfig.apiBase || "/api/user/workflows").replace(/\/+$/, "");
}

function buildWorkflowApiUrl(path = "") {
    const normalizedPath = normalizeText(path);
    return normalizedPath ? `${getWorkflowApiBase()}/${normalizedPath.replace(/^\/+/, "")}` : getWorkflowApiBase();
}

function getWorkflowActiveGroupId() {
    if (typeof workflowWorkspaceConfig.getActiveGroupId === "function") {
        return normalizeText(workflowWorkspaceConfig.getActiveGroupId());
    }
    return normalizeText(workflowWorkspaceConfig.activeGroupId);
}

function getWorkflowDocumentScope() {
    if (workflowWorkspaceConfig.scope === "group") {
        return "group";
    }
    return normalizeText(workflowWorkspaceConfig.documentScope) || "personal";
}

function getWorkflowLabel() {
    return workflowWorkspaceConfig.scope === "group" ? "Group Workflow" : "Personal Workflow";
}

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
const workflowUrlAccessEnabledToggle = document.getElementById("workflow-url-access-enabled");
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
const workflowFileSyncCard = document.getElementById("workflow-file-sync-card");
const workflowFileSyncEnabledToggle = document.getElementById("workflow-file-sync-enabled");
const workflowFileSyncSourcesSelect = document.getElementById("workflow-file-sync-sources");
const workflowFileSyncWaitModeSelect = document.getElementById("workflow-file-sync-wait-mode");
const workflowFileSyncContinueModeSelect = document.getElementById("workflow-file-sync-continue-mode");
const workflowFileSyncUseChangedDocumentsToggle = document.getElementById("workflow-file-sync-use-changed-documents");
const workflowFileSyncHelp = document.getElementById("workflow-file-sync-help");
const workflowAlertPrioritySelect = document.getElementById("workflow-alert-priority");
const DOCUMENT_ACTION_NONE = "none";
const DOCUMENT_ACTION_SEARCH = "search";
const DOCUMENT_ACTION_ANALYZE = "analyze";
const DOCUMENT_ACTION_COMPARISON = "comparison";
const DOCUMENT_ANALYSIS_MODE_COMBINED = "combined";
const DOCUMENT_ANALYSIS_MODE_PER_DOCUMENT = "per_document";
const DOCUMENT_ANALYSIS_TARGET_SELECTED = "selected";
const DOCUMENT_ANALYSIS_TARGET_RECENT = "recent";
const DEFAULT_RECENT_DOCUMENT_WINDOW_MINUTES = 10;
const DOCUMENT_ACTION_DESCRIPTIONS = {
    [DOCUMENT_ACTION_NONE]: "Find relevant information with the normal prompt flow.",
    [DOCUMENT_ACTION_SEARCH]: "Search selected or recent documents and use matching excerpts as workflow context.",
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
const workflowAnalysisTargetModeSelect = document.getElementById("workflow-analysis-target-mode");
const workflowAnalysisRecentMinutesInput = document.getElementById("workflow-analysis-recent-minutes");
const workflowAnalysisRecentWindowGroup = document.getElementById("workflow-analysis-recent-window-group");
const workflowAnalysisDocumentIdsInput = document.getElementById("workflow-analysis-document-ids");
const workflowAnalysisPerDocumentGroup = document.getElementById("workflow-analysis-per-document-group");
const workflowAnalysisPerDocumentToggle = document.getElementById("workflow-analysis-per-document");
const workflowComparisonLeftDocumentIdInput = document.getElementById("workflow-comparison-left-document-id");
const workflowComparisonRightDocumentIdsInput = document.getElementById("workflow-comparison-target-document-ids");
const workflowComparisonModalEl = document.getElementById("workflow-comparison-modal");
const workflowComparisonModal = workflowComparisonModalEl && window.bootstrap ? bootstrap.Modal.getOrCreateInstance(workflowComparisonModalEl) : null;
const workflowComparisonBoard = document.getElementById("workflow-comparison-board");
const workflowComparisonSelectionSummary = document.getElementById("workflow-comparison-selection-summary");
const workflowComparisonAvailableList = document.getElementById("workflow-comparison-available-list");
const workflowComparisonSourceDropzone = document.getElementById("workflow-comparison-source-dropzone");
const workflowComparisonSelectionList = document.getElementById("workflow-comparison-selection-list");
const workflowComparisonInlineSourceTags = document.getElementById("workflow-comparison-inline-source-tags");
const workflowComparisonInlineTargetTags = document.getElementById("workflow-comparison-inline-target-tags");
const workflowComparisonEditBtn = document.getElementById("workflow-comparison-edit-btn");
const workflowComparisonEditButtonLabel = document.getElementById("workflow-comparison-edit-btn-label");
const workflowComparisonRefreshBtn = document.getElementById("workflow-comparison-refresh-btn");
const workflowAnalysisGroupIdsInput = document.getElementById("workflow-analysis-group-ids");
const workflowAnalysisPublicWorkspaceIdsInput = document.getElementById("workflow-analysis-public-workspace-ids");
const workflowAnalysisWindowUnitSelect = document.getElementById("workflow-analysis-window-unit");
const workflowAnalysisWindowSizeInput = document.getElementById("workflow-analysis-window-size");
const workflowAnalysisWindowPercentInput = document.getElementById("workflow-analysis-window-percent");
const workflowAnalysisRetriesInput = document.getElementById("workflow-analysis-retries");
const workflowUseSelectedDocumentsBtn = document.getElementById("workflow-use-selected-documents-btn");
const workflowSelectedDocumentsSummary = document.getElementById("workflow-selected-documents-summary");
const workflowDocumentPickerCard = document.getElementById("workflow-document-picker-card");
const workflowDocumentPickerLoading = document.getElementById("workflow-document-picker-loading");
const workflowDocumentPickerError = document.getElementById("workflow-document-picker-error");
const chatDocumentActionSelect = document.getElementById("document-action-select");
const chatDocumentSelect = document.getElementById("document-select");
const WORKFLOW_URL_PATTERN = /https?:\/\/[^\s<>'"]+/gi;

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
    if ([DOCUMENT_ACTION_NONE, DOCUMENT_ACTION_SEARCH].includes(actionType)) {
        return true;
    }

    return Boolean(getDocumentActionCapability(actionType).enabled);
}

function getWorkflowDocumentActionMaxDocuments(actionType) {
    return Number.parseInt(getDocumentActionCapability(actionType).workflow_max_documents || 10, 10);
}

function getDocumentActionDisplayLabel(actionType) {
    if (actionType === DOCUMENT_ACTION_SEARCH || actionType === DOCUMENT_ACTION_NONE) {
        return "Search";
    }
    if (actionType === DOCUMENT_ACTION_COMPARISON) {
        return "Compare";
    }
    if (actionType === DOCUMENT_ACTION_ANALYZE) {
        return "Analyze";
    }
    return "Search";
}

function isWorkflowUrlAccessAvailable() {
    return Boolean(window.urlAccessSettings?.enable_url_access);
}

function getWorkflowUrlAccessMaxUrls() {
    const configuredLimit = Number.parseInt(window.urlAccessSettings?.url_access_max_workflow_urls_per_run || 50, 10);
    return Number.isFinite(configuredLimit) && configuredLimit > 0 ? configuredLimit : 50;
}

function getWorkflowPromptUrls() {
    const promptText = normalizeText(workflowTaskPromptInput?.value);
    if (!promptText) {
        return [];
    }

    const urls = [];
    const seenUrls = new Set();
    for (const match of promptText.matchAll(WORKFLOW_URL_PATTERN)) {
        const url = normalizeText(match[0]).replace(/[.,);\]}>]+$/g, "");
        if (!url || seenUrls.has(url)) {
            continue;
        }
        seenUrls.add(url);
        urls.push(url);
    }
    return urls;
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
        || getDocumentActionDescription(normalizeText(workflowDocumentActionTypeSelect.value) || DOCUMENT_ACTION_SEARCH)
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
let fileSyncSourceOptions = [];
let agentsLoaded = false;
let fileSyncSourcesLoaded = false;
let workflowPendingDelete = null;
let currentHistoryWorkflowId = "";
let currentEditingWorkflow = null;
let workflowComparisonVersionLoadToken = 0;
let workflowPickerDocumentIds = [];
let workflowSavedComparisonTargetIds = [];
let workflowSavedComparisonPreferredLeftId = "";

function normalizeText(value) {
    return String(value || "").trim();
}

function setElementVisibility(element, isVisible) {
    if (!element) {
        return;
    }
    element.classList.toggle("d-none", !isVisible);
}

function clearElementChildren(element) {
    if (!element) {
        return;
    }

    while (element.firstChild) {
        element.firstChild.remove();
    }
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
    const activityScope = normalizeText(workflowWorkspaceConfig.activityScope || workflowWorkspaceConfig.scope || "personal");
    if (activityScope && activityScope !== "personal") {
        url.searchParams.set("scope", activityScope);
    }
    const activeGroupId = getWorkflowActiveGroupId();
    if (activityScope === "group" && activeGroupId) {
        url.searchParams.set("groupId", activeGroupId);
    }

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

function normalizeWorkflowAnalysisMode(value) {
    const normalizedValue = normalizeText(value).toLowerCase().replace(/[\s-]+/g, "_");
    return normalizedValue === DOCUMENT_ANALYSIS_MODE_PER_DOCUMENT
        ? DOCUMENT_ANALYSIS_MODE_PER_DOCUMENT
        : DOCUMENT_ANALYSIS_MODE_COMBINED;
}

function updateWorkflowConversationLink(element, conversationId) {
    if (!element) {
        return;
    }

    const conversationUrl = buildWorkflowConversationUrl(conversationId);
    element.classList.toggle("d-none", !conversationUrl);
    element.href = conversationUrl || "#";
    element.target = conversationUrl ? "_blank" : "";
    element.rel = conversationUrl ? "noopener" : "";
}

function buildStatusBadge(status) {
    const normalizedStatus = normalizeText(status).toLowerCase() || "idle";
    const variant = normalizedStatus === "completed"
        ? "success"
        : normalizedStatus === "failed"
            ? "danger"
            : normalizedStatus === "skipped"
                ? "warning"
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

    if (workflow.trigger_type === "file_sync") {
        const schedule = workflow.schedule && typeof workflow.schedule === "object" ? workflow.schedule : {};
        const value = Number(schedule.value || 0);
        const unit = normalizeText(schedule.unit) || "minutes";
        return `Monitor File Sync every ${value} ${unit}`;
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

function normalizeIdList(values) {
    if (!Array.isArray(values)) {
        return [];
    }

    return Array.from(new Set(values.map((value) => normalizeText(value)).filter(Boolean)));
}

function getSelectedValues(selectElement) {
    if (!selectElement) {
        return [];
    }

    return Array.from(selectElement.selectedOptions || [])
        .map((option) => normalizeText(option.value))
        .filter(Boolean);
}

function getFileSyncSourceKey(source) {
    if (!source || typeof source !== "object") {
        return "";
    }
    return [source.scope_type, source.scope_id, source.source_id]
        .map((value) => normalizeText(value))
        .join(":");
}

function getSelectedFileSyncSources() {
    const selectedKeys = new Set(getSelectedValues(workflowFileSyncSourcesSelect));
    return fileSyncSourceOptions
        .filter((source) => selectedKeys.has(getFileSyncSourceKey(source)))
        .map((source) => ({
            scope_type: normalizeText(source.scope_type),
            scope_id: normalizeText(source.scope_id),
            source_id: normalizeText(source.source_id),
        }));
}

function populateFileSyncSourceSelect(selectedSources = []) {
    if (!workflowFileSyncSourcesSelect) {
        return;
    }

    const selectedKeys = new Set((selectedSources || []).map(getFileSyncSourceKey).filter(Boolean));
    workflowFileSyncSourcesSelect.replaceChildren();

    if (!fileSyncSourceOptions.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "No File Sync sources available";
        option.disabled = true;
        workflowFileSyncSourcesSelect.appendChild(option);
        workflowFileSyncSourcesSelect.disabled = true;
        return;
    }

    workflowFileSyncSourcesSelect.disabled = false;
    fileSyncSourceOptions.forEach((source) => {
        const option = document.createElement("option");
        const sourceKey = getFileSyncSourceKey(source);
        option.value = sourceKey;
        option.textContent = normalizeText(source.label || source.name) || "File Sync Source";
        option.selected = selectedKeys.has(sourceKey);
        workflowFileSyncSourcesSelect.appendChild(option);
    });
}

async function loadFileSyncSourceOptions(force = false) {
    if (workflowWorkspaceConfig.scope === "group" && !getWorkflowActiveGroupId()) {
        fileSyncSourceOptions = [];
        fileSyncSourcesLoaded = false;
        return fileSyncSourceOptions;
    }

    if (fileSyncSourcesLoaded && !force) {
        return fileSyncSourceOptions;
    }

    try {
        const response = await fetch(buildWorkflowApiUrl("file-sync-sources"), {
            credentials: "same-origin",
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || "Unable to load File Sync sources.");
        }
        fileSyncSourceOptions = Array.isArray(data.sources) ? data.sources : [];
        fileSyncSourcesLoaded = true;
    } catch (error) {
        fileSyncSourceOptions = [];
        fileSyncSourcesLoaded = true;
        showToast(escapeHtml(error.message || "Unable to load File Sync sources."), "warning");
    }

    return fileSyncSourceOptions;
}

function getSelectedWorkflowComparisonTargetIds() {
    return getSelectedValues(workflowComparisonRightDocumentIdsInput);
}

function getWorkflowPickerSelectedDocumentIds() {
    return normalizeIdList(workflowPickerDocumentIds);
}

function setWorkflowPickerSelectedDocumentIds(documentIds = []) {
    workflowPickerDocumentIds = normalizeIdList(documentIds);
    if (workflowAnalysisDocumentIdsInput) {
        workflowAnalysisDocumentIdsInput.value = joinCsvList(workflowPickerDocumentIds);
    }
    updateSelectedDocumentsSummary();
}

function clearWorkflowChatDocumentSelection() {
    if (chatDocumentSelect) {
        Array.from(chatDocumentSelect.options || []).forEach((option) => {
            option.selected = false;
        });
    }

    document.querySelectorAll("#document-dropdown-items .doc-checkbox").forEach((checkbox) => {
        checkbox.checked = false;
    });

    setWorkflowPickerSelectedDocumentIds([]);
}

function applyWorkflowPickerSelection(documentIds = []) {
    const normalizedDocumentIds = normalizeIdList(documentIds);
    if (chatDocumentSelect) {
        const selectedIds = new Set(normalizedDocumentIds);
        Array.from(chatDocumentSelect.options || []).forEach((option) => {
            option.selected = selectedIds.has(option.value);
        });
    }

    document.querySelectorAll("#document-dropdown-items .dropdown-item[data-document-id]").forEach((item) => {
        const documentId = normalizeText(item.getAttribute("data-document-id"));
        const checkbox = item.querySelector(".doc-checkbox");
        if (checkbox && documentId) {
            checkbox.checked = normalizedDocumentIds.includes(documentId);
        }
    });

    setWorkflowPickerSelectedDocumentIds(normalizedDocumentIds);
}

function getDefaultWorkflowPickerScopes() {
    if (workflowWorkspaceConfig.scope === "group") {
        const activeGroupId = getWorkflowActiveGroupId();
        return {
            personal: false,
            groupIds: activeGroupId ? [activeGroupId] : [],
            publicWorkspaceIds: [],
        };
    }

    return {
        personal: true,
        groupIds: (window.userGroups || []).map((group) => normalizeText(group.id)).filter(Boolean),
        publicWorkspaceIds: (window.userVisiblePublicWorkspaces || []).map((workspace) => normalizeText(workspace.id)).filter(Boolean),
    };
}

function getWorkflowPickerScopesFromAction(documentAction = {}) {
    if (workflowWorkspaceConfig.scope === "group") {
        return getDefaultWorkflowPickerScopes();
    }

    const docScope = normalizeText(documentAction.doc_scope) || getWorkflowDocumentScope();
    const groupIds = normalizeIdList(documentAction.active_group_ids);
    const publicWorkspaceIds = normalizeIdList(documentAction.active_public_workspace_id);
    const defaultScopes = getDefaultWorkflowPickerScopes();

    if (docScope === "personal") {
        return {
            personal: true,
            groupIds: [],
            publicWorkspaceIds: [],
        };
    }

    if (docScope === "group") {
        return {
            personal: false,
            groupIds: groupIds.length ? groupIds : defaultScopes.groupIds,
            publicWorkspaceIds: [],
        };
    }

    if (docScope === "public") {
        return {
            personal: false,
            groupIds: [],
            publicWorkspaceIds: publicWorkspaceIds.length ? publicWorkspaceIds : defaultScopes.publicWorkspaceIds,
        };
    }

    return {
        personal: true,
        groupIds: groupIds.length ? groupIds : defaultScopes.groupIds,
        publicWorkspaceIds: publicWorkspaceIds.length ? publicWorkspaceIds : defaultScopes.publicWorkspaceIds,
    };
}

function getWorkflowDocScopeFromPickerScopes(scopes = {}) {
    if (workflowWorkspaceConfig.scope === "group") {
        return "group";
    }

    const hasPersonal = Boolean(scopes.personal);
    const hasGroups = Array.isArray(scopes.groupIds) && scopes.groupIds.length > 0;
    const hasPublic = Array.isArray(scopes.publicWorkspaceIds) && scopes.publicWorkspaceIds.length > 0;
    const selectedScopeCount = [hasPersonal, hasGroups, hasPublic].filter(Boolean).length;

    if (selectedScopeCount > 1) {
        return "all";
    }
    if (hasGroups) {
        return "group";
    }
    if (hasPublic) {
        return "public";
    }
    return "personal";
}

function syncWorkflowScopeFieldsFromPicker(scopes = getDefaultWorkflowPickerScopes()) {
    if (workflowAnalysisDocScopeSelect) {
        workflowAnalysisDocScopeSelect.value = getWorkflowDocScopeFromPickerScopes(scopes);
    }
    if (workflowAnalysisGroupIdsInput) {
        workflowAnalysisGroupIdsInput.value = joinCsvList(scopes.groupIds || []);
    }
    if (workflowAnalysisPublicWorkspaceIdsInput) {
        workflowAnalysisPublicWorkspaceIdsInput.value = joinCsvList(scopes.publicWorkspaceIds || []);
    }
}

function syncWorkflowPickerActionType() {
    if (!chatDocumentActionSelect || !workflowDocumentActionTypeSelect) {
        return;
    }

    const actionType = normalizeText(workflowDocumentActionTypeSelect.value) || DOCUMENT_ACTION_SEARCH;
    chatDocumentActionSelect.value = actionType;
    chatDocumentActionSelect.dispatchEvent(new Event("change", { bubbles: true }));
}

function setWorkflowPickerLoadingState(isLoading) {
    if (workflowDocumentPickerLoading) {
        workflowDocumentPickerLoading.classList.toggle("d-none", !isLoading);
    }
}

function setWorkflowPickerError(message = "") {
    if (!workflowDocumentPickerError) {
        return;
    }

    workflowDocumentPickerError.textContent = message;
    workflowDocumentPickerError.classList.toggle("d-none", !message);
}

async function initializeWorkflowDocumentPicker(documentAction = {}) {
    if (!workflowDocumentPickerCard) {
        return;
    }

    setWorkflowPickerError("");
    setWorkflowPickerLoadingState(true);
    syncWorkflowPickerActionType();

    const pickerScopes = getWorkflowPickerScopesFromAction(documentAction);
    try {
        await setEffectiveScopes(pickerScopes, {
            force: workflowWorkspaceConfig.scope === "group",
            source: "workflow",
            reload: true,
        });
        await ensureDocumentPickerReady({ reload: false, showLoading: false });
        syncWorkflowScopeFieldsFromPicker(pickerScopes);
        applyWorkflowPickerSelection(
            documentAction.type === DOCUMENT_ACTION_COMPARISON
                ? []
                : documentAction.document_ids || []
        );
    } catch (error) {
        setWorkflowPickerError(error.message || "Unable to load documents for this workflow.");
    } finally {
        setWorkflowPickerLoadingState(false);
    }
}

async function refreshWorkflowComparisonTargetsFromPicker() {
    if (normalizeText(workflowDocumentActionTypeSelect?.value) !== DOCUMENT_ACTION_COMPARISON) {
        return;
    }

    const selectedDocumentIds = getWorkflowPickerSelectedDocumentIds();
    if (!selectedDocumentIds.length) {
        setWorkflowComparisonSavedTargets(workflowSavedComparisonTargetIds, workflowSavedComparisonPreferredLeftId);
        return;
    }

    await loadWorkflowComparisonVersionTargets({
        selectedWorkspaceDocumentIds: selectedDocumentIds,
        selectedTargetIds: getSelectedWorkflowComparisonTargetIds().length
            ? getSelectedWorkflowComparisonTargetIds()
            : workflowSavedComparisonTargetIds,
        preferredLeftId: normalizeText(workflowComparisonLeftDocumentIdInput?.value) || workflowSavedComparisonPreferredLeftId,
    });
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

function getWorkflowComparisonOption(versionId) {
    const normalizedVersionId = normalizeText(versionId);
    if (!normalizedVersionId || !workflowComparisonRightDocumentIdsInput) {
        return null;
    }

    return Array.from(workflowComparisonRightDocumentIdsInput.options || [])
        .find((option) => normalizeText(option.value) === normalizedVersionId) || null;
}

function getWorkflowComparisonCandidateCatalog() {
    if (!workflowComparisonRightDocumentIdsInput) {
        return [];
    }

    return Array.from(workflowComparisonRightDocumentIdsInput.options || [])
        .map((option) => {
            const id = normalizeText(option.value);
            if (!id) {
                return null;
            }

            const groupLabel = normalizeText(option.dataset.groupLabel)
                || normalizeText(option.parentElement?.label)
                || "Document";
            return {
                id,
                label: normalizeText(option.textContent) || id,
                groupLabel,
                selected: option.selected,
            };
        })
        .filter(Boolean);
}

function getWorkflowComparisonEntry(versionId) {
    const normalizedVersionId = normalizeText(versionId);
    if (!normalizedVersionId) {
        return null;
    }

    return getWorkflowComparisonCandidateCatalog()
        .find((candidate) => candidate.id === normalizedVersionId)
        || {
            id: normalizedVersionId,
            label: normalizedVersionId,
            groupLabel: "Document",
            selected: true,
        };
}

function getWorkflowComparisonSourceId() {
    return normalizeText(workflowComparisonLeftDocumentIdInput?.value);
}

function getWorkflowComparisonTargetIds() {
    const sourceId = getWorkflowComparisonSourceId();
    return getSelectedWorkflowComparisonTargetIds().filter((targetId) => targetId !== sourceId);
}

function truncateWorkflowComparisonLabel(label, maxLength = 28) {
    const normalizedLabel = normalizeText(label);
    if (normalizedLabel.length <= maxLength) {
        return normalizedLabel;
    }

    return `${normalizedLabel.slice(0, Math.max(1, maxLength - 3)).trimEnd()}...`;
}

function appendWorkflowComparisonSummaryBadge(container, entry, badgeClass, placeholderText = "Not set") {
    if (!container) {
        return;
    }

    const badge = document.createElement("span");
    badge.className = `badge rounded-pill ${badgeClass} text-truncate`;
    badge.style.maxWidth = "14rem";
    const label = entry ? normalizeText(entry.label || entry.id) : placeholderText;
    badge.title = label;
    badge.textContent = truncateWorkflowComparisonLabel(label);
    container.appendChild(badge);
}

function renderWorkflowComparisonInlineSummary() {
    const sourceEntry = getWorkflowComparisonEntry(getWorkflowComparisonSourceId());
    const targetEntries = getWorkflowComparisonTargetIds()
        .map((targetId) => getWorkflowComparisonEntry(targetId))
        .filter(Boolean);

    clearElementChildren(workflowComparisonInlineSourceTags);
    clearElementChildren(workflowComparisonInlineTargetTags);

    appendWorkflowComparisonSummaryBadge(
        workflowComparisonInlineSourceTags,
        sourceEntry,
        sourceEntry ? "text-bg-primary" : "text-bg-light border text-body-secondary",
        "Not set"
    );

    if (targetEntries.length) {
        targetEntries.forEach((targetEntry) => {
            appendWorkflowComparisonSummaryBadge(workflowComparisonInlineTargetTags, targetEntry, "text-bg-secondary", "");
        });
    } else {
        appendWorkflowComparisonSummaryBadge(workflowComparisonInlineTargetTags, null, "text-bg-light border text-body-secondary", "None selected");
    }

    if (workflowComparisonEditButtonLabel) {
        workflowComparisonEditButtonLabel.textContent = getSelectedWorkflowComparisonTargetIds().length ? "Edit Compare" : "Set Up Compare";
    }
}

function createWorkflowComparisonEmptyState(messageText) {
    const emptyState = document.createElement("div");
    emptyState.className = "text-muted small border rounded-3 p-3 bg-body";
    emptyState.textContent = messageText;
    return emptyState;
}

function renderWorkflowComparisonEmptyState(container, messageText) {
    clearElementChildren(container);
    container?.appendChild(createWorkflowComparisonEmptyState(messageText));
}

function buildWorkflowComparisonSelectionSummary() {
    const sourceEntry = getWorkflowComparisonEntry(getWorkflowComparisonSourceId());
    const targetCount = getWorkflowComparisonTargetIds().length;

    if (!sourceEntry && !targetCount) {
        return "Choose one Source and at least one Target.";
    }
    if (!sourceEntry) {
        return "Choose one Source for this comparison.";
    }
    if (!targetCount) {
        return `Choose at least one Target for ${sourceEntry.label || sourceEntry.id}.`;
    }

    return `Comparing ${sourceEntry.label || sourceEntry.id} to ${targetCount} ${targetCount === 1 ? "target" : "targets"}.`;
}

function createWorkflowComparisonButton(label, className, dataName, dataValue, disabled = false) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
    button.disabled = disabled;
    button.dataset[dataName] = dataValue;
    return button;
}

function createWorkflowComparisonCard(entry, badgeLabel, badgeClass, actions = []) {
    const card = document.createElement("div");
    card.className = "border rounded-3 p-2 bg-body d-flex flex-column gap-2";
    card.draggable = true;
    card.dataset.workflowComparisonDragId = entry.id;

    const header = document.createElement("div");
    header.className = "d-flex align-items-start justify-content-between gap-2";

    const textWrap = document.createElement("div");
    textWrap.className = "flex-grow-1";
    textWrap.style.minWidth = "0";

    const title = document.createElement("div");
    title.className = "small fw-semibold text-body";
    title.textContent = entry.label || entry.id;

    const details = document.createElement("div");
    details.className = "small text-muted";
    details.textContent = entry.groupLabel || "Ready to compare";

    const badge = document.createElement("span");
    badge.className = `badge ${badgeClass}`;
    badge.textContent = badgeLabel;

    textWrap.append(title, details);
    header.append(textWrap, badge);
    card.appendChild(header);

    if (actions.length) {
        const actionWrap = document.createElement("div");
        actionWrap.className = "d-flex flex-wrap gap-2";
        actions.forEach((action) => actionWrap.appendChild(action));
        card.appendChild(actionWrap);
    }

    return card;
}

function renderWorkflowComparisonAvailableList() {
    if (!workflowComparisonAvailableList) {
        return;
    }

    clearElementChildren(workflowComparisonAvailableList);

    const candidates = getWorkflowComparisonCandidateCatalog();
    if (!candidates.length) {
        workflowComparisonAvailableList.appendChild(createWorkflowComparisonEmptyState("No document versions available yet. Select documents in the workflow picker and refresh from the picker."));
        return;
    }

    const sourceId = getWorkflowComparisonSourceId();
    const selectedIds = getSelectedWorkflowComparisonTargetIds();
    const selectedIdSet = new Set(selectedIds);
    const groups = new Map();
    candidates.forEach((candidate) => {
        const groupLabel = candidate.groupLabel || "Document";
        if (!groups.has(groupLabel)) {
            groups.set(groupLabel, []);
        }
        groups.get(groupLabel).push(candidate);
    });

    groups.forEach((items, groupLabel) => {
        const groupWrap = document.createElement("div");
        groupWrap.className = "d-flex flex-column gap-2";

        const heading = document.createElement("div");
        heading.className = "small text-uppercase text-muted fw-semibold";
        heading.textContent = groupLabel;
        groupWrap.appendChild(heading);

        items.forEach((candidate) => {
            const isSource = candidate.id === sourceId;
            const isSelected = selectedIdSet.has(candidate.id);
            const canMoveSourceToTarget = isSource && selectedIds.length > 1;
            const badgeClass = isSource
                ? "text-bg-primary"
                : isSelected
                    ? "text-bg-info"
                    : "text-bg-light border text-body-secondary";
            const badgeLabel = isSource ? "Source" : isSelected ? "Target" : "Version";
            const sourceButton = createWorkflowComparisonButton(
                isSource ? "Source selected" : "Use as Source",
                "btn btn-outline-primary btn-sm",
                "workflowComparisonSetSourceId",
                candidate.id,
                isSource
            );
            const targetButton = createWorkflowComparisonButton(
                isSource ? (canMoveSourceToTarget ? "Move to Target" : "Source selected") : (isSelected ? "Added to Target" : "Add to Target"),
                "btn btn-outline-secondary btn-sm",
                "workflowComparisonSetTargetId",
                candidate.id,
                (isSelected && !isSource) || (isSource && !canMoveSourceToTarget)
            );
            groupWrap.appendChild(createWorkflowComparisonCard(candidate, badgeLabel, badgeClass, [sourceButton, targetButton]));
        });

        workflowComparisonAvailableList.appendChild(groupWrap);
    });
}

function renderWorkflowComparisonSelectionList() {
    const sourceEntry = getWorkflowComparisonEntry(getWorkflowComparisonSourceId());
    const targetEntries = getWorkflowComparisonTargetIds()
        .map((targetId) => getWorkflowComparisonEntry(targetId))
        .filter(Boolean);

    if (workflowComparisonSelectionSummary) {
        workflowComparisonSelectionSummary.textContent = buildWorkflowComparisonSelectionSummary();
    }

    if (sourceEntry) {
        const actions = [];
        if (targetEntries.length > 0) {
            actions.push(createWorkflowComparisonButton("Move to Target", "btn btn-outline-secondary btn-sm", "workflowComparisonSetTargetId", sourceEntry.id));
        }
        actions.push(createWorkflowComparisonButton("Remove", "btn btn-outline-danger btn-sm", "workflowComparisonRemoveId", sourceEntry.id));
        clearElementChildren(workflowComparisonSourceDropzone);
        workflowComparisonSourceDropzone?.appendChild(createWorkflowComparisonCard(sourceEntry, "Source", "text-bg-primary", actions));
    } else {
        renderWorkflowComparisonEmptyState(workflowComparisonSourceDropzone, "Drop a version here, or use Use as Source.");
    }

    clearElementChildren(workflowComparisonSelectionList);
    if (!targetEntries.length) {
        workflowComparisonSelectionList?.appendChild(createWorkflowComparisonEmptyState("Drop one or more versions here, or use Add to Target."));
        return;
    }

    targetEntries.forEach((targetEntry, index) => {
        workflowComparisonSelectionList?.appendChild(createWorkflowComparisonCard(targetEntry, `Target ${index + 1}`, "text-bg-secondary", [
            createWorkflowComparisonButton("Use as Source", "btn btn-outline-primary btn-sm", "workflowComparisonPromoteId", targetEntry.id),
            createWorkflowComparisonButton("Remove", "btn btn-outline-danger btn-sm", "workflowComparisonRemoveId", targetEntry.id),
        ]));
    });
}

function renderWorkflowComparisonUi() {
    renderWorkflowComparisonInlineSummary();
    renderWorkflowComparisonAvailableList();
    renderWorkflowComparisonSelectionList();
}

function setWorkflowComparisonLoadingState(messageText = "Loading document versions...") {
    if (workflowComparisonSelectionSummary) {
        workflowComparisonSelectionSummary.textContent = messageText;
    }
    renderWorkflowComparisonEmptyState(workflowComparisonAvailableList, messageText);
    renderWorkflowComparisonEmptyState(workflowComparisonSourceDropzone, "Source will appear here after versions load.");
    renderWorkflowComparisonEmptyState(workflowComparisonSelectionList, "Targets will appear here after versions load.");
}

function assignWorkflowComparisonSource(versionId) {
    const normalizedVersionId = normalizeText(versionId);
    const option = getWorkflowComparisonOption(normalizedVersionId);
    if (!normalizedVersionId || !option) {
        return;
    }

    option.selected = true;
    syncWorkflowComparisonLeftOptions(normalizedVersionId);
}

function assignWorkflowComparisonTarget(versionId) {
    const normalizedVersionId = normalizeText(versionId);
    const option = getWorkflowComparisonOption(normalizedVersionId);
    if (!normalizedVersionId || !option) {
        return;
    }

    const currentSourceId = getWorkflowComparisonSourceId();
    const selectedIds = getSelectedWorkflowComparisonTargetIds();
    if (currentSourceId === normalizedVersionId && selectedIds.length > 1) {
        const nextSourceId = selectedIds.find((targetId) => targetId !== normalizedVersionId) || "";
        syncWorkflowComparisonLeftOptions(nextSourceId);
        return;
    }

    if (option.selected) {
        renderWorkflowComparisonUi();
        return;
    }

    option.selected = true;
    syncWorkflowComparisonLeftOptions(currentSourceId);
}

function removeWorkflowComparisonTarget(versionId) {
    const normalizedVersionId = normalizeText(versionId);
    const option = getWorkflowComparisonOption(normalizedVersionId);
    if (!normalizedVersionId || !option) {
        return;
    }

    const currentSourceId = getWorkflowComparisonSourceId();
    option.selected = false;
    syncWorkflowComparisonLeftOptions(currentSourceId === normalizedVersionId ? "" : currentSourceId);
}

function toggleWorkflowComparisonDropzoneHighlight(dropzone, isHighlighted) {
    if (!dropzone) {
        return;
    }

    dropzone.classList.toggle("border-primary", isHighlighted);
    dropzone.classList.toggle("bg-primary-subtle", isHighlighted);
}

function handleWorkflowComparisonBoardClick(event) {
    const sourceButton = event.target.closest("[data-workflow-comparison-set-source-id]");
    if (sourceButton) {
        event.preventDefault();
        assignWorkflowComparisonSource(sourceButton.dataset.workflowComparisonSetSourceId);
        return;
    }

    const targetButton = event.target.closest("[data-workflow-comparison-set-target-id]");
    if (targetButton) {
        event.preventDefault();
        assignWorkflowComparisonTarget(targetButton.dataset.workflowComparisonSetTargetId);
        return;
    }

    const removeButton = event.target.closest("[data-workflow-comparison-remove-id]");
    if (removeButton) {
        event.preventDefault();
        removeWorkflowComparisonTarget(removeButton.dataset.workflowComparisonRemoveId);
        return;
    }

    const promoteButton = event.target.closest("[data-workflow-comparison-promote-id]");
    if (promoteButton) {
        event.preventDefault();
        assignWorkflowComparisonSource(promoteButton.dataset.workflowComparisonPromoteId);
    }
}

function handleWorkflowComparisonDragStart(event) {
    const dragCard = event.target.closest("[data-workflow-comparison-drag-id]");
    if (!dragCard || !event.dataTransfer) {
        return;
    }

    const dragId = normalizeText(dragCard.dataset.workflowComparisonDragId);
    if (!dragId) {
        return;
    }

    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", dragId);
    dragCard.setAttribute("aria-grabbed", "true");
}

function handleWorkflowComparisonDragEnd(event) {
    event.target.closest("[data-workflow-comparison-drag-id]")?.setAttribute("aria-grabbed", "false");
    toggleWorkflowComparisonDropzoneHighlight(workflowComparisonSourceDropzone, false);
    toggleWorkflowComparisonDropzoneHighlight(workflowComparisonSelectionList, false);
}

function attachWorkflowComparisonDropzoneEvents(dropzone, dropHandler) {
    if (!dropzone) {
        return;
    }

    dropzone.addEventListener("dragover", (event) => {
        event.preventDefault();
        toggleWorkflowComparisonDropzoneHighlight(dropzone, true);
    });

    dropzone.addEventListener("dragleave", (event) => {
        if (!dropzone.contains(event.relatedTarget)) {
            toggleWorkflowComparisonDropzoneHighlight(dropzone, false);
        }
    });

    dropzone.addEventListener("drop", (event) => {
        event.preventDefault();
        toggleWorkflowComparisonDropzoneHighlight(dropzone, false);
        const droppedId = normalizeText(event.dataTransfer?.getData("text/plain"));
        if (droppedId) {
            dropHandler(droppedId);
        }
    });
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
    renderWorkflowComparisonUi();
}

function setWorkflowComparisonTargetOptions(comparisonGroups = [], selectedTargetIds = [], preferredLeftId = "") {
    if (!workflowComparisonRightDocumentIdsInput) {
        return;
    }

    const normalizedSelectedTargetIds = new Set((selectedTargetIds || []).map((value) => normalizeText(value)).filter(Boolean));
    clearElementChildren(workflowComparisonRightDocumentIdsInput);

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
            option.dataset.groupLabel = normalizeText(groupLabel) || "Document";
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
    clearElementChildren(workflowComparisonRightDocumentIdsInput);

    normalizedTargetIds.forEach((targetId) => {
        const option = document.createElement("option");
        option.value = targetId;
        option.textContent = targetId;
        option.dataset.groupLabel = "Saved Versions";
        option.selected = true;
        workflowComparisonRightDocumentIdsInput.appendChild(option);
    });

    workflowComparisonRightDocumentIdsInput.disabled = normalizedTargetIds.length === 0;
    syncWorkflowComparisonLeftOptions(preferredLeftId);
}

async function fetchWorkflowDocumentVersions(documentId) {
    const documentVersionsApi = typeof workflowWorkspaceConfig.documentVersionsApi === "function"
        ? workflowWorkspaceConfig.documentVersionsApi(documentId)
        : `/api/documents/${encodeURIComponent(documentId)}/versions`;
    const response = await fetch(documentVersionsApi, {
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
    clearElementChildren(workflowComparisonRightDocumentIdsInput);
    const loadingOption = document.createElement("option");
    loadingOption.value = "";
    loadingOption.disabled = true;
    loadingOption.textContent = "Loading versions...";
    workflowComparisonRightDocumentIdsInput.appendChild(loadingOption);
    if (workflowComparisonLeftDocumentIdInput) {
        workflowComparisonLeftDocumentIdInput.disabled = true;
        clearElementChildren(workflowComparisonLeftDocumentIdInput);
    }
    setWorkflowComparisonLoadingState();

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
    if (typeof workflowWorkspaceConfig.getSelectedDocumentIds === "function") {
        return workflowWorkspaceConfig.getSelectedDocumentIds().map((value) => normalizeText(value)).filter(Boolean);
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
        analysis_mode: normalizeWorkflowAnalysisMode(actionConfig.analysis_mode || legacyAnalyzeConfig.analysis_mode),
        doc_scope: normalizeText(actionConfig.doc_scope || legacyAnalyzeConfig.doc_scope) || getWorkflowDocumentScope(),
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
        target_mode: normalizeText(actionConfig.target_mode || legacyAnalyzeConfig.target_mode) || DOCUMENT_ANALYSIS_TARGET_SELECTED,
        recent_window_minutes: actionConfig.recent_window_minutes ?? legacyAnalyzeConfig.recent_window_minutes ?? DEFAULT_RECENT_DOCUMENT_WINDOW_MINUTES,
    };
}

function getWorkflowDocumentActionSummary(workflow) {
    const config = getDocumentActionConfig(workflow);
    if (config.type === DOCUMENT_ACTION_SEARCH) {
        const documentCount = config.document_ids.length;
        if (config.target_mode === DOCUMENT_ANALYSIS_TARGET_RECENT) {
            const recentMinutes = Number.parseInt(config.recent_window_minutes || DEFAULT_RECENT_DOCUMENT_WINDOW_MINUTES, 10);
            return `Search recent documents from the last ${recentMinutes || DEFAULT_RECENT_DOCUMENT_WINDOW_MINUTES} minutes`;
        }
        if (documentCount) {
            return `Search ${documentCount} ${documentCount === 1 ? "document" : "documents"}`;
        }
        return "Search";
    }

    if (config.type === DOCUMENT_ACTION_ANALYZE) {
        const documentCount = config.document_ids.length;
        const unit = normalizeText(config.window_unit) || "pages";
        const modeSuffix = config.analysis_mode === DOCUMENT_ANALYSIS_MODE_PER_DOCUMENT ? " separately" : "";
        if (config.target_mode === DOCUMENT_ANALYSIS_TARGET_RECENT) {
            const recentMinutes = Number.parseInt(config.recent_window_minutes || DEFAULT_RECENT_DOCUMENT_WINDOW_MINUTES, 10);
            return `Analyze${modeSuffix} recent documents from the last ${recentMinutes || DEFAULT_RECENT_DOCUMENT_WINDOW_MINUTES} minutes by ${unit}`;
        }
        if (!documentCount) {
            return `Analyze${modeSuffix} by ${unit}`;
        }
        return `Analyze ${documentCount} ${documentCount === 1 ? "document" : "documents"}${modeSuffix} by ${unit}`;
    }

    if (config.type === DOCUMENT_ACTION_COMPARISON) {
        const rightCount = config.right_document_ids.length;
        if (config.target_mode === DOCUMENT_ANALYSIS_TARGET_RECENT) {
            const recentMinutes = Number.parseInt(config.recent_window_minutes || DEFAULT_RECENT_DOCUMENT_WINDOW_MINUTES, 10);
            return `Compare recent documents from the last ${recentMinutes || DEFAULT_RECENT_DOCUMENT_WINDOW_MINUTES} minutes`;
        }
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

    const selectedIds = getWorkflowPickerSelectedDocumentIds();
    const selectedLabel = normalizeText(workflowWorkspaceConfig.selectedDocumentsLabel) || "workspace";
    if (!selectedIds.length) {
        workflowSelectedDocumentsSummary.textContent = `No ${selectedLabel} documents selected in the picker.`;
        return;
    }

    workflowSelectedDocumentsSummary.textContent = `${selectedIds.length} ${selectedLabel} ${selectedIds.length === 1 ? "document is" : "documents are"} selected in the picker.`;
}

function updateWorkflowAnalysisTargetModeFields() {
    const targetMode = normalizeText(workflowAnalysisTargetModeSelect?.value) || DOCUMENT_ANALYSIS_TARGET_SELECTED;
    const isRecentMode = targetMode === DOCUMENT_ANALYSIS_TARGET_RECENT;
    setElementVisibility(workflowDocumentPickerCard, !isRecentMode);
    setElementVisibility(workflowAnalysisRecentWindowGroup, isRecentMode);
}

function updateDocumentActionFields() {
    const actionType = normalizeText(workflowDocumentActionTypeSelect?.value) || DOCUMENT_ACTION_SEARCH;
    const hasDocumentAction = actionType !== DOCUMENT_ACTION_NONE;
    const targetMode = normalizeText(workflowAnalysisTargetModeSelect?.value) || DOCUMENT_ANALYSIS_TARGET_SELECTED;
    const isRecentMode = targetMode === DOCUMENT_ANALYSIS_TARGET_RECENT;
    setElementVisibility(workflowDocumentTargetsFields, hasDocumentAction);
    setElementVisibility(workflowAnalysisTargetFields, hasDocumentAction);
    setElementVisibility(workflowAnalysisPerDocumentGroup, actionType === DOCUMENT_ACTION_ANALYZE);
    setElementVisibility(workflowComparisonTargetFields, actionType === DOCUMENT_ACTION_COMPARISON && !isRecentMode);
    syncWorkflowPickerActionType();
    syncWorkflowDocumentActionTooltip();
    updateWorkflowAnalysisTargetModeFields();

    if (workflowAnalysisPerDocumentToggle && actionType !== DOCUMENT_ACTION_ANALYZE) {
        workflowAnalysisPerDocumentToggle.checked = false;
    }

    if (workflowDocumentActionHelp) {
        workflowDocumentActionHelp.textContent = getDocumentActionDescription(actionType);
    }

    if (actionType === DOCUMENT_ACTION_COMPARISON && !isRecentMode) {
        syncWorkflowComparisonLeftOptions();
    } else {
        workflowComparisonModal?.hide();
        renderWorkflowComparisonUi();
    }

    updateSelectedDocumentsSummary();
}

async function applySelectedWorkspaceDocumentsToWorkflow() {
    const selectedIds = getWorkflowPickerSelectedDocumentIds();
    if (!selectedIds.length) {
        const selectedLabel = normalizeText(workflowWorkspaceConfig.selectedDocumentsLabel) || "workspace";
        showToast(`Select one or more ${selectedLabel} documents in the picker first.`, "warning");
        return;
    }

    const actionType = normalizeText(workflowDocumentActionTypeSelect?.value) || DOCUMENT_ACTION_SEARCH;
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
        setWorkflowPickerSelectedDocumentIds(limitedSelectedIds);
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
            scope: normalizeText(workflowWorkspaceConfig.workspaceEndpointScope) || "user",
            scopeLabel: normalizeText(workflowWorkspaceConfig.workspaceEndpointLabel) || "Workspace",
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
    const scheduledCount = workflows.filter((workflow) => ["interval", "file_sync"].includes(workflow.trigger_type)).length;
    const activeCount = workflows.filter((workflow) => ["interval", "file_sync"].includes(workflow.trigger_type) && workflow.is_enabled).length;
    const visibleCount = items.length;

    workflowsSummary.textContent = `${visibleCount} shown of ${totalCount} workflows. ${scheduledCount} scheduled or monitored, ${activeCount} active.`;
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
        const nextRunMeta = ["interval", "file_sync"].includes(workflow.trigger_type) && workflow.next_run_at
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
        const disabledMeta = ["interval", "file_sync"].includes(workflow.trigger_type) && !workflow.is_enabled
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
    if (workflowWorkspaceConfig.scope === "group" && !getWorkflowActiveGroupId()) {
        agentOptions = [];
        agentsLoaded = false;
        return agentOptions;
    }

    if (agentsLoaded && !forceRefresh) {
        return agentOptions;
    }

    try {
        const response = await fetch(normalizeText(workflowWorkspaceConfig.agentsApi) || "/api/user/agents", {
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
            ? workflowWorkspaceConfig.scope === "group"
                ? "Choose a group agent or a merged global agent."
                : "Choose a personal agent or a merged global agent."
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
    const isScheduled = triggerType === "interval" || triggerType === "file_sync";
    const isFileSyncMonitor = triggerType === "file_sync";

    setElementVisibility(workflowScheduleValueGroup, isScheduled);
    setElementVisibility(workflowScheduleUnitGroup, isScheduled);
    setElementVisibility(workflowEnabledGroup, isScheduled);

    if (workflowEnabledToggle && !isScheduled) {
        workflowEnabledToggle.checked = true;
    }

    if (isFileSyncMonitor) {
        if (workflowFileSyncEnabledToggle) {
            workflowFileSyncEnabledToggle.checked = true;
        }
        if (workflowFileSyncWaitModeSelect) {
            workflowFileSyncWaitModeSelect.value = "complete";
        }
        if (workflowFileSyncContinueModeSelect) {
            workflowFileSyncContinueModeSelect.value = "changed";
        }
    }

    if (workflowTriggerHelp) {
        workflowTriggerHelp.textContent = isFileSyncMonitor
            ? "Monitor workflows check File Sync sources on this interval and run only when files changed."
            : isScheduled
                ? "Interval workflows are picked up by the scheduler when the next run time is due."
                : "Manual workflows run only when you trigger them from the workspace.";
    }

    updateScheduleConstraints();
    updateFileSyncFields();
}

function updateFileSyncFields() {
    const triggerType = normalizeText(workflowTriggerTypeSelect?.value) || "manual";
    const isFileSyncMonitor = triggerType === "file_sync";
    const fileSyncEnabled = Boolean(workflowFileSyncEnabledToggle?.checked) || isFileSyncMonitor;

    if (workflowFileSyncEnabledToggle && isFileSyncMonitor) {
        workflowFileSyncEnabledToggle.checked = true;
    }
    if (workflowFileSyncWaitModeSelect) {
        workflowFileSyncWaitModeSelect.disabled = !fileSyncEnabled || isFileSyncMonitor;
    }
    if (workflowFileSyncContinueModeSelect) {
        workflowFileSyncContinueModeSelect.disabled = !fileSyncEnabled || isFileSyncMonitor;
    }
    if (workflowFileSyncSourcesSelect) {
        workflowFileSyncSourcesSelect.disabled = !fileSyncEnabled || fileSyncSourceOptions.length === 0;
    }
    if (workflowFileSyncUseChangedDocumentsToggle) {
        workflowFileSyncUseChangedDocumentsToggle.disabled = !fileSyncEnabled;
    }
    if (workflowFileSyncCard) {
        workflowFileSyncCard.classList.toggle("border-primary", fileSyncEnabled);
    }
    if (workflowFileSyncHelp) {
        workflowFileSyncHelp.textContent = fileSyncEnabled
            ? "Selected sources are triggered before the workflow prompt runs."
            : "Trigger selected sync sources before this workflow runs.";
    }
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
    if (workflowUrlAccessEnabledToggle) {
        workflowUrlAccessEnabledToggle.checked = false;
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
    if (workflowFileSyncEnabledToggle) {
        workflowFileSyncEnabledToggle.checked = false;
    }
    if (workflowFileSyncWaitModeSelect) {
        workflowFileSyncWaitModeSelect.value = "complete";
    }
    if (workflowFileSyncContinueModeSelect) {
        workflowFileSyncContinueModeSelect.value = "always";
    }
    if (workflowFileSyncUseChangedDocumentsToggle) {
        workflowFileSyncUseChangedDocumentsToggle.checked = true;
    }
    populateFileSyncSourceSelect([]);
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
        workflowDocumentActionTypeSelect.value = DOCUMENT_ACTION_SEARCH;
    }
    if (workflowAnalysisTargetModeSelect) {
        workflowAnalysisTargetModeSelect.value = DOCUMENT_ANALYSIS_TARGET_SELECTED;
    }
    if (workflowAnalysisRecentMinutesInput) {
        workflowAnalysisRecentMinutesInput.value = String(DEFAULT_RECENT_DOCUMENT_WINDOW_MINUTES);
    }
    if (workflowAnalysisDocScopeSelect) {
        workflowAnalysisDocScopeSelect.value = getWorkflowDocumentScope();
    }
    if (workflowAnalysisDocumentIdsInput) {
        workflowAnalysisDocumentIdsInput.value = "";
    }
    if (workflowAnalysisPerDocumentToggle) {
        workflowAnalysisPerDocumentToggle.checked = false;
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
    workflowSavedComparisonTargetIds = [];
    workflowSavedComparisonPreferredLeftId = "";
    clearWorkflowChatDocumentSelection();
    if (workflowSaveBtn) {
        workflowSaveBtn.disabled = false;
        workflowSaveBtn.textContent = `Save ${getWorkflowLabel()}`;
    }
    if (workflowModalLabel) {
        workflowModalLabel.textContent = `Create ${getWorkflowLabel()}`;
    }

    populateAgentSelect(null);
    refreshModelSourceOptions();
    populateEndpointSelect("");
    populateModelSelect(normalizeText(workflowModelEndpointSelect?.value), "");
    updateRunnerFields();
    updateTriggerFields();
    updateFileSyncFields();
    updateDocumentActionFields();
}

async function openWorkflowModal(workflow = null) {
    if (!workflowModal) {
        return;
    }
    if (workflowWorkspaceConfig.scope === "group" && !getWorkflowActiveGroupId()) {
        showToast("Select a group before managing group workflows.", "warning");
        return;
    }

    await loadAgentOptions(true);
    await loadFileSyncSourceOptions(true);
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
        if (workflowUrlAccessEnabledToggle) {
            workflowUrlAccessEnabledToggle.checked = Boolean(workflow.url_access_enabled);
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
        const fileSyncConfig = workflow.file_sync && typeof workflow.file_sync === "object" ? workflow.file_sync : {};
        if (workflowFileSyncEnabledToggle) {
            workflowFileSyncEnabledToggle.checked = Boolean(fileSyncConfig.enabled);
        }
        if (workflowFileSyncWaitModeSelect) {
            workflowFileSyncWaitModeSelect.value = normalizeText(fileSyncConfig.wait_mode) || "complete";
        }
        if (workflowFileSyncContinueModeSelect) {
            workflowFileSyncContinueModeSelect.value = normalizeText(fileSyncConfig.continue_mode) || "always";
        }
        if (workflowFileSyncUseChangedDocumentsToggle) {
            workflowFileSyncUseChangedDocumentsToggle.checked = fileSyncConfig.use_changed_documents !== false;
        }
        populateFileSyncSourceSelect(Array.isArray(fileSyncConfig.sources) ? fileSyncConfig.sources : []);
        const documentAction = getDocumentActionConfig(workflow);
        if (workflowDocumentActionTypeSelect) {
            workflowDocumentActionTypeSelect.value = documentAction.type;
        }
        if (workflowAnalysisDocScopeSelect) {
            workflowAnalysisDocScopeSelect.value = documentAction.doc_scope;
        }
        if (workflowAnalysisTargetModeSelect) {
            workflowAnalysisTargetModeSelect.value = documentAction.target_mode === DOCUMENT_ANALYSIS_TARGET_RECENT
                ? DOCUMENT_ANALYSIS_TARGET_RECENT
                : DOCUMENT_ANALYSIS_TARGET_SELECTED;
        }
        if (workflowAnalysisRecentMinutesInput) {
            workflowAnalysisRecentMinutesInput.value = String(documentAction.recent_window_minutes || DEFAULT_RECENT_DOCUMENT_WINDOW_MINUTES);
        }
        if (workflowAnalysisDocumentIdsInput) {
            workflowAnalysisDocumentIdsInput.value = joinCsvList(documentAction.document_ids);
        }
        if (workflowAnalysisPerDocumentToggle) {
            workflowAnalysisPerDocumentToggle.checked = documentAction.analysis_mode === DOCUMENT_ANALYSIS_MODE_PER_DOCUMENT;
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
            workflowModalLabel.textContent = `Edit ${getWorkflowLabel()}`;
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
        workflowSavedComparisonTargetIds = savedTargetIds;
        workflowSavedComparisonPreferredLeftId = documentAction.left_document_id;
        setWorkflowComparisonSavedTargets(savedTargetIds, documentAction.left_document_id);
    } else {
        workflowSavedComparisonTargetIds = [];
        workflowSavedComparisonPreferredLeftId = "";
        setWorkflowComparisonSavedTargets([], "");
    }

    updateRunnerFields();
    updateTriggerFields();
    updateFileSyncFields();
    updateDocumentActionFields();
    workflowModal.show();
    await initializeWorkflowDocumentPicker(documentAction || {});
}

function buildWorkflowPayload() {
    const runnerType = normalizeText(workflowRunnerTypeSelect?.value) || "model";
    const triggerType = normalizeText(workflowTriggerTypeSelect?.value) || "manual";
    const documentActionType = normalizeText(workflowDocumentActionTypeSelect?.value) || DOCUMENT_ACTION_SEARCH;
    const analysisTargetMode = normalizeText(workflowAnalysisTargetModeSelect?.value) === DOCUMENT_ANALYSIS_TARGET_RECENT
        ? DOCUMENT_ANALYSIS_TARGET_RECENT
        : DOCUMENT_ANALYSIS_TARGET_SELECTED;
    const targetDocumentIds = analysisTargetMode === DOCUMENT_ANALYSIS_TARGET_RECENT
        ? []
        : getWorkflowPickerSelectedDocumentIds();
    const comparisonLeftDocumentId = normalizeText(workflowComparisonLeftDocumentIdInput?.value);
    const comparisonTargetDocumentIds = analysisTargetMode === DOCUMENT_ANALYSIS_TARGET_RECENT
        ? []
        : getSelectedWorkflowComparisonTargetIds();
    const selectedDocumentActionIds = documentActionType === DOCUMENT_ACTION_COMPARISON
        ? comparisonTargetDocumentIds
        : targetDocumentIds;
    const comparisonRightDocumentIds = analysisTargetMode === DOCUMENT_ANALYSIS_TARGET_RECENT
        ? []
        : comparisonTargetDocumentIds.filter((documentId) => documentId !== comparisonLeftDocumentId);
    const analysisGroupIds = parseCsvList(workflowAnalysisGroupIdsInput?.value);
    const analysisPublicWorkspaceIds = parseCsvList(workflowAnalysisPublicWorkspaceIdsInput?.value);
    const rawWindowSize = normalizeText(workflowAnalysisWindowSizeInput?.value);
    const rawWindowPercent = normalizeText(workflowAnalysisWindowPercentInput?.value);
    const rawRetries = normalizeText(workflowAnalysisRetriesInput?.value) || "1";
    const rawRecentMinutes = normalizeText(workflowAnalysisRecentMinutesInput?.value) || String(DEFAULT_RECENT_DOCUMENT_WINDOW_MINUTES);
    const analysisMode = workflowAnalysisPerDocumentToggle?.checked
        ? DOCUMENT_ANALYSIS_MODE_PER_DOCUMENT
        : DOCUMENT_ANALYSIS_MODE_COMBINED;
    const fileSyncEnabled = Boolean(workflowFileSyncEnabledToggle?.checked) || triggerType === "file_sync";
    const payload = {
        id: normalizeText(workflowIdInput?.value),
        name: normalizeText(workflowNameInput?.value),
        description: normalizeText(workflowDescriptionInput?.value),
        task_prompt: normalizeText(workflowTaskPromptInput?.value),
        url_access_enabled: isWorkflowUrlAccessAvailable() ? Boolean(workflowUrlAccessEnabledToggle?.checked) : false,
        runner_type: runnerType,
        trigger_type: triggerType,
        alert_priority: normalizeText(workflowAlertPrioritySelect?.value).toLowerCase() || "none",
        is_enabled: ["interval", "file_sync"].includes(triggerType) ? Boolean(workflowEnabledToggle?.checked) : true,
        schedule: {},
        file_sync: {
            enabled: fileSyncEnabled,
            wait_mode: normalizeText(workflowFileSyncWaitModeSelect?.value) || "complete",
            continue_mode: normalizeText(workflowFileSyncContinueModeSelect?.value) || "always",
            use_changed_documents: workflowFileSyncUseChangedDocumentsToggle?.checked !== false,
            sources: fileSyncEnabled ? getSelectedFileSyncSources() : [],
        },
        selected_agent: {},
        model_endpoint_id: "",
        model_id: "",
        document_action: {
            type: documentActionType,
            document_ids: documentActionType !== DOCUMENT_ACTION_NONE ? selectedDocumentActionIds : [],
            left_document_id: documentActionType === DOCUMENT_ACTION_COMPARISON && analysisTargetMode !== DOCUMENT_ANALYSIS_TARGET_RECENT ? comparisonLeftDocumentId : "",
            right_document_ids: documentActionType === DOCUMENT_ACTION_COMPARISON ? comparisonRightDocumentIds : [],
            analysis_mode: documentActionType === DOCUMENT_ACTION_ANALYZE ? analysisMode : DOCUMENT_ANALYSIS_MODE_COMBINED,
            doc_scope: normalizeText(workflowAnalysisDocScopeSelect?.value) || getWorkflowDocumentScope(),
            active_group_ids: documentActionType !== DOCUMENT_ACTION_NONE
                ? workflowWorkspaceConfig.scope === "group" && getWorkflowActiveGroupId()
                    ? [getWorkflowActiveGroupId()]
                    : analysisGroupIds
                : [],
            active_public_workspace_id: documentActionType !== DOCUMENT_ACTION_NONE ? analysisPublicWorkspaceIds : [],
            window_unit: normalizeText(workflowAnalysisWindowUnitSelect?.value) || "pages",
            window_size: rawWindowSize ? Number(rawWindowSize) : null,
            window_percent: rawWindowPercent ? Number(rawWindowPercent) : null,
            max_retries_per_window: Number(rawRetries),
            target_mode: documentActionType !== DOCUMENT_ACTION_NONE ? analysisTargetMode : DOCUMENT_ANALYSIS_TARGET_SELECTED,
            recent_window_minutes: Number(rawRecentMinutes),
        },
        analyze: {
            enabled: documentActionType === DOCUMENT_ACTION_ANALYZE,
            document_ids: documentActionType === DOCUMENT_ACTION_ANALYZE ? targetDocumentIds : [],
            doc_scope: normalizeText(workflowAnalysisDocScopeSelect?.value) || getWorkflowDocumentScope(),
            active_group_ids: documentActionType === DOCUMENT_ACTION_ANALYZE
                ? workflowWorkspaceConfig.scope === "group" && getWorkflowActiveGroupId()
                    ? [getWorkflowActiveGroupId()]
                    : analysisGroupIds
                : [],
            active_public_workspace_id: documentActionType === DOCUMENT_ACTION_ANALYZE ? analysisPublicWorkspaceIds : [],
            analysis_mode: documentActionType === DOCUMENT_ACTION_ANALYZE ? analysisMode : DOCUMENT_ANALYSIS_MODE_COMBINED,
            window_unit: normalizeText(workflowAnalysisWindowUnitSelect?.value) || "pages",
            window_size: rawWindowSize ? Number(rawWindowSize) : null,
            window_percent: rawWindowPercent ? Number(rawWindowPercent) : null,
            max_retries_per_window: Number(rawRetries),
            target_mode: documentActionType === DOCUMENT_ACTION_ANALYZE ? analysisTargetMode : DOCUMENT_ANALYSIS_TARGET_SELECTED,
            recent_window_minutes: Number(rawRecentMinutes),
        },
    };

    if (!payload.name) {
        throw new Error("Workflow name is required.");
    }
    if (!payload.task_prompt) {
        throw new Error("Task prompt is required.");
    }
    if (payload.url_access_enabled) {
        const promptUrls = getWorkflowPromptUrls();
        const maxWorkflowUrls = getWorkflowUrlAccessMaxUrls();
        if (promptUrls.length > maxWorkflowUrls) {
            throw new Error(`URL Access workflows support up to ${maxWorkflowUrls} URLs per run.`);
        }
    }
    const usesDynamicFileSyncTargets = payload.file_sync.enabled && payload.file_sync.use_changed_documents;
    if (documentActionType === DOCUMENT_ACTION_SEARCH && analysisTargetMode === DOCUMENT_ANALYSIS_TARGET_SELECTED && !payload.document_action.document_ids.length) {
        throw new Error("Select one or more documents for search.");
    }
    if (documentActionType === DOCUMENT_ACTION_ANALYZE && analysisTargetMode === DOCUMENT_ANALYSIS_TARGET_SELECTED && !payload.document_action.document_ids.length && !usesDynamicFileSyncTargets) {
        throw new Error("Select one or more documents for analysis.");
    }
    if (documentActionType !== DOCUMENT_ACTION_NONE && analysisTargetMode === DOCUMENT_ANALYSIS_TARGET_RECENT && (!Number.isInteger(payload.document_action.recent_window_minutes) || payload.document_action.recent_window_minutes < 1 || payload.document_action.recent_window_minutes > 1440)) {
        throw new Error("Recent document window must be between 1 and 1440 minutes.");
    }
    if (documentActionType === DOCUMENT_ACTION_COMPARISON && analysisTargetMode === DOCUMENT_ANALYSIS_TARGET_SELECTED && payload.document_action.document_ids.length < 2) {
        throw new Error("Select at least two document versions for compare.");
    }
    if (documentActionType === DOCUMENT_ACTION_COMPARISON && analysisTargetMode === DOCUMENT_ANALYSIS_TARGET_SELECTED && !payload.document_action.left_document_id) {
        throw new Error("Add one Source document id for compare.");
    }
    if (documentActionType === DOCUMENT_ACTION_COMPARISON && analysisTargetMode === DOCUMENT_ANALYSIS_TARGET_SELECTED && !payload.document_action.right_document_ids.length) {
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
    if (payload.file_sync.enabled && !payload.file_sync.sources.length) {
        throw new Error("Select at least one File Sync source for this workflow.");
    }
    if (payload.file_sync.wait_mode === "queued" && payload.file_sync.continue_mode === "changed") {
        throw new Error("File Sync must wait for completion before continuing only when files changed.");
    }
    if (triggerType === "file_sync") {
        if (!payload.file_sync.enabled) {
            throw new Error("Monitor File Sync Changes requires File Sync before run.");
        }
        if (payload.file_sync.wait_mode !== "complete" || payload.file_sync.continue_mode !== "changed") {
            throw new Error("Monitor File Sync Changes must wait for completion and continue only when files changed.");
        }
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

    if (["interval", "file_sync"].includes(triggerType)) {
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

    if (workflowWorkspaceConfig.scope === "group" && !getWorkflowActiveGroupId()) {
        showToast("Select a group before saving group workflows.", "warning");
        return;
    }

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
        const response = await fetch(buildWorkflowApiUrl(), {
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
        showToast(`${getWorkflowLabel()} saved.`, "success");
        await fetchUserWorkflows();
    } catch (error) {
        showToast(escapeHtml(error.message || "Unable to save workflow right now."), "danger");
    } finally {
        workflowSaveBtn.disabled = false;
        workflowSaveBtn.textContent = `Save ${getWorkflowLabel()}`;
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
        const failedWindows = Number(run.analysis_coverage?.failed_windows || 0);
        const canResumeFailed = normalizeText(run.status).toLowerCase() === "failed" || failedWindows > 0;
        const resumeFailedButton = canResumeFailed
            ? `<button type="button" class="btn btn-sm btn-outline-warning" data-resume-run-id="${escapeHtml(normalizeText(run.id))}"><i class="bi bi-arrow-clockwise me-1"></i>Resume failed</button>`
            : "";
        const details = normalizeText(run.error)
            ? `<div class="text-danger small">${escapeHtml(run.error)}</div>`
            : normalizeText(run.response_preview)
                ? `<div class="small workflow-response-preview">${escapeHtml(run.response_preview)}</div>`
                : '<div class="text-muted small">No preview available.</div>';
        const conversationLink = conversationUrl
            ? `
                <div class="d-flex flex-wrap gap-2">
                    <a class="btn btn-sm btn-outline-primary" href="${escapeHtml(conversationUrl)}" target="_blank" rel="noopener"><i class="bi bi-chat-dots-fill me-1"></i>Open workflow conversation</a>
                    <a class="btn btn-sm btn-outline-info" href="${escapeHtml(activityUrl)}" target="_blank" rel="noopener"><i class="bi bi-activity me-1"></i>Open activity view</a>
                    ${resumeFailedButton}
                </div>
                <div class="small text-muted mt-1">${escapeHtml(conversationId)}</div>
            `
            : resumeFailedButton || '<div class="text-muted small">Not created yet.</div>';

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

async function resumeFailedWorkflowRun(runId) {
    const normalizedRunId = normalizeText(runId);
    if (!currentHistoryWorkflowId || !normalizedRunId) {
        return;
    }

    try {
        const response = await fetch(buildWorkflowApiUrl(`${encodeURIComponent(currentHistoryWorkflowId)}/runs/${encodeURIComponent(normalizedRunId)}/resume-failed`), {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            credentials: "same-origin",
            body: JSON.stringify({}),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.success === false) {
            throw new Error(data.run?.error || data.error || "Unable to resume failed workflow items.");
        }

        showToast(`Resumed ${data.resumed_item_count || 0} failed item(s).`, "success");
        window.dispatchEvent(new CustomEvent("workflow-alert-refresh-requested"));
        await fetchUserWorkflows();
        const refreshedWorkflow = workflows.find((item) => normalizeText(item.id) === currentHistoryWorkflowId);
        if (refreshedWorkflow) {
            await openHistoryModalForWorkflow(refreshedWorkflow);
        }
    } catch (error) {
        showToast(escapeHtml(error.message || "Unable to resume failed workflow items."), "danger");
    }
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
        const response = await fetch(buildWorkflowApiUrl(`${encodeURIComponent(currentHistoryWorkflowId)}/runs`), {
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

    const activityWindow = window.open("about:blank", "_blank");
    if (activityWindow) {
        activityWindow.opener = null;
        activityWindow.location.href = activityState.url;
    } else {
        showToast("Allow pop-ups to open the workflow activity view.", "warning");
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
        const response = await fetch(buildWorkflowApiUrl(`${encodeURIComponent(workflow.id)}/run`), {
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

        const runStatus = normalizeText(data.run?.status).toLowerCase();
        showToast(runStatus === "skipped" ? "Workflow skipped; no File Sync changes were found." : "Workflow run completed.", "success");
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
        const response = await fetch(buildWorkflowApiUrl(encodeURIComponent(workflowPendingDelete.id)), {
            method: "DELETE",
            credentials: "same-origin",
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || "Unable to delete workflow right now.");
        }

        workflowDeleteModal?.hide();
        showToast(`${getWorkflowLabel()} deleted.`, "success");
        workflowPendingDelete = null;
        await fetchUserWorkflows();
    } catch (error) {
        showToast(escapeHtml(error.message || "Unable to delete workflow right now."), "danger");
    } finally {
        workflowDeleteConfirmBtn.disabled = false;
        workflowDeleteConfirmBtn.textContent = `Delete ${getWorkflowLabel()}`;
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

    if (workflowWorkspaceConfig.scope === "group" && !getWorkflowActiveGroupId()) {
        workflows = [];
        renderWorkflowEmptyState("Select a group to load workflows.");
        refreshWorkflowSummary([]);
        return [];
    }

    renderWorkflowEmptyState("Loading workflows...");

    try {
        const response = await fetch(buildWorkflowApiUrl(), {
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
    workflowHistoryBody?.addEventListener("click", (event) => {
        const resumeButton = event.target.closest("button[data-resume-run-id]");
        if (!resumeButton || resumeButton.disabled) {
            return;
        }
        resumeButton.disabled = true;
        resumeFailedWorkflowRun(resumeButton.getAttribute("data-resume-run-id")).finally(() => {
            resumeButton.disabled = false;
        });
    });
    workflowRunnerTypeSelect?.addEventListener("change", updateRunnerFields);
    workflowModelSourceSelect?.addEventListener("change", updateRunnerFields);
    workflowModelEndpointSelect?.addEventListener("change", () => {
        populateModelSelect(normalizeText(workflowModelEndpointSelect.value), "");
        updateModelHelpText();
    });
    workflowModelSelect?.addEventListener("change", updateModelHelpText);
    workflowTriggerTypeSelect?.addEventListener("change", updateTriggerFields);
    workflowScheduleUnitSelect?.addEventListener("change", updateScheduleConstraints);
    workflowFileSyncEnabledToggle?.addEventListener("change", updateFileSyncFields);
    workflowFileSyncWaitModeSelect?.addEventListener("change", updateFileSyncFields);
    workflowFileSyncContinueModeSelect?.addEventListener("change", updateFileSyncFields);
    workflowDocumentActionTypeSelect?.addEventListener("change", updateDocumentActionFields);
    workflowAnalysisTargetModeSelect?.addEventListener("change", updateDocumentActionFields);
    workflowComparisonRightDocumentIdsInput?.addEventListener("change", () => {
        syncWorkflowComparisonLeftOptions();
    });
    workflowComparisonBoard?.addEventListener("click", handleWorkflowComparisonBoardClick);
    workflowComparisonBoard?.addEventListener("dragstart", handleWorkflowComparisonDragStart);
    workflowComparisonBoard?.addEventListener("dragend", handleWorkflowComparisonDragEnd);
    attachWorkflowComparisonDropzoneEvents(workflowComparisonSourceDropzone, assignWorkflowComparisonSource);
    attachWorkflowComparisonDropzoneEvents(workflowComparisonSelectionList, assignWorkflowComparisonTarget);
    workflowComparisonRefreshBtn?.addEventListener("click", () => {
        refreshWorkflowComparisonTargetsFromPicker().catch((error) => {
            showToast(escapeHtml(error.message || "Unable to load selected document versions."), "danger");
        });
    });
    workflowComparisonEditBtn?.addEventListener("click", () => {
        workflowComparisonModal?.show();
    });
    workflowComparisonModalEl?.addEventListener("show.bs.modal", () => {
        refreshWorkflowComparisonTargetsFromPicker().catch((error) => {
            showToast(escapeHtml(error.message || "Unable to load selected document versions."), "danger");
        });
    });
    workflowUseSelectedDocumentsBtn?.addEventListener("click", () => {
        applySelectedWorkspaceDocumentsToWorkflow().catch((error) => {
            showToast(escapeHtml(error.message || "Unable to apply selected documents."), "danger");
        });
    });
    workflowModalEl?.addEventListener("hidden.bs.modal", () => {
        workflowComparisonModal?.hide();
        resetWorkflowForm();
    });
    window.addEventListener("chat:document-selection-changed", (event) => {
        if (!workflowModalEl?.classList.contains("show")) {
            return;
        }
        setWorkflowPickerSelectedDocumentIds(event.detail?.documentIds || []);
        refreshWorkflowComparisonTargetsFromPicker().catch((error) => {
            showToast(escapeHtml(error.message || "Unable to load selected document versions."), "danger");
        });
    });
    window.addEventListener("chat:scope-changed", (event) => {
        if (!workflowModalEl?.classList.contains("show")) {
            return;
        }
        syncWorkflowScopeFieldsFromPicker(event.detail?.scopes || getDefaultWorkflowPickerScopes());
    });
    workflowDeleteModalEl?.addEventListener("hidden.bs.modal", () => {
        workflowPendingDelete = null;
        if (workflowDeleteConfirmBtn) {
            workflowDeleteConfirmBtn.disabled = false;
            workflowDeleteConfirmBtn.textContent = `Delete ${getWorkflowLabel()}`;
        }
    });

    setupViewToggle("workflows", "workflowsViewPreference", (mode) => {
        switchViewContainers(mode, workflowsListView, workflowsGridView);
    });

    if (workflowWorkspaceConfig.scope === "group") {
        window.addEventListener("groupWorkspace:context-changed", () => {
            agentsLoaded = false;
            fileSyncSourcesLoaded = false;
            currentHistoryWorkflowId = "";
            workflowPendingDelete = null;
            clearWorkflowChatDocumentSelection();
            void fetchUserWorkflows();
        });
    }
}

window.fetchUserWorkflows = fetchUserWorkflows;

initializeWorkflowEvents();
void fetchUserWorkflows();