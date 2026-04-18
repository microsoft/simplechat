// workspace_workflows.js

import { showToast } from "../chat/chat-toast.js";
import { escapeHtml, truncateDescription } from "./view-utils.js";

const workflowsTableBody = document.getElementById("workflows-table-body");
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

const workflowHistoryModalEl = document.getElementById("workflowHistoryModal");
const workflowHistoryModal = workflowHistoryModalEl && window.bootstrap ? bootstrap.Modal.getOrCreateInstance(workflowHistoryModalEl) : null;
const workflowHistoryModalLabel = document.getElementById("workflowHistoryModalLabel");
const workflowHistoryBody = document.getElementById("workflow-history-body");
const workflowHistoryConversationId = document.getElementById("workflow-history-conversation-id");
const workflowHistoryConversationLink = document.getElementById("workflow-history-open-conversation-link");

const workflowDeleteModalEl = document.getElementById("workflowDeleteModal");
const workflowDeleteModal = workflowDeleteModalEl && window.bootstrap ? bootstrap.Modal.getOrCreateInstance(workflowDeleteModalEl) : null;
const workflowDeleteName = document.getElementById("workflow-delete-name");
const workflowDeleteConfirmBtn = document.getElementById("workflow-delete-confirm-btn");

let workflows = [];
let agentOptions = [];
let agentsLoaded = false;
let workflowPendingDelete = null;
let currentHistoryWorkflowId = "";
let currentEditingWorkflow = null;

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

function buildWorkflowSearchText(workflow) {
    return [
        workflow.name,
        workflow.description,
        workflow.task_prompt,
        getWorkflowRunnerLabel(workflow),
        getWorkflowTriggerLabel(workflow),
        getWorkflowAlertLabel(workflow),
    ].map((value) => normalizeText(value).toLowerCase()).join(" ");
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
    if (!workflowsTableBody) {
        return;
    }

    workflowsTableBody.innerHTML = `
        <tr>
            <td colspan="5" class="text-center text-muted py-4">${escapeHtml(message)}</td>
        </tr>
    `;
}

function renderWorkflowTable(items) {
    if (!workflowsTableBody) {
        return;
    }

    if (!items.length) {
        renderWorkflowEmptyState(workflows.length ? "No workflows match the current search." : "No workflows created yet.");
        refreshWorkflowSummary(items);
        return;
    }

    workflowsTableBody.innerHTML = items.map((workflow) => {
        const workflowName = escapeHtml(normalizeText(workflow.name) || "Untitled Workflow");
        const description = escapeHtml(truncateDescription(normalizeText(workflow.description), 120));
        const runnerLabel = escapeHtml(getWorkflowRunnerLabel(workflow));
        const triggerLabel = escapeHtml(getWorkflowTriggerLabel(workflow));
        const lastRunStatus = workflow.last_run_status ? buildStatusBadge(workflow.last_run_status) : '<span class="text-muted small">Never run</span>';
        const lastRunAt = workflow.last_run_at
            ? `<div class="small text-muted mt-1">${escapeHtml(formatDateTime(workflow.last_run_at))}</div>`
            : "";
        const lastRunPreview = normalizeText(workflow.last_run_response_preview)
            ? `<div class="workflow-meta workflow-response-preview mt-1">${escapeHtml(truncateDescription(workflow.last_run_response_preview, 160))}</div>`
            : normalizeText(workflow.last_run_error)
                ? `<div class="workflow-meta text-danger mt-1">${escapeHtml(truncateDescription(workflow.last_run_error, 120))}</div>`
                : "";
        const nextRunMeta = workflow.trigger_type === "interval" && workflow.next_run_at
            ? `<div class="workflow-meta mt-1">Next run: ${escapeHtml(formatDateTime(workflow.next_run_at))}</div>`
            : "";
        const alertMeta = `<div class="workflow-meta mt-1">Alert: ${escapeHtml(getWorkflowAlertLabel(workflow))}</div>`;
        const conversationMeta = workflow.conversation_id
            ? '<div class="workflow-meta mt-1"><i class="bi bi-chat-left-text me-1"></i>Conversation ready</div>'
            : "";
        const disabledMeta = workflow.trigger_type === "interval" && !workflow.is_enabled
            ? '<div class="workflow-meta mt-1 text-warning">Scheduled runs are paused.</div>'
            : "";
        const runnerMeta = workflow.runner_type === "agent"
            ? '<div class="workflow-meta mt-1">Uses your selected agent configuration.</div>'
            : '<div class="workflow-meta mt-1">Uses direct model execution.</div>';
        const runDisabled = normalizeText(workflow.status).toLowerCase() === "running";

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
                    ${disabledMeta}
                    ${nextRunMeta}
                </td>
                <td>
                    <div>${lastRunStatus}</div>
                    ${lastRunAt}
                    ${lastRunPreview}
                </td>
                <td>
                    <div class="d-flex flex-wrap gap-1 justify-content-start justify-content-xl-end">
                        <button type="button" class="btn btn-sm btn-outline-primary" data-action="run" data-workflow-id="${escapeHtml(workflow.id)}" ${runDisabled ? "disabled" : ""}>${runDisabled ? "Running..." : "Run"}</button>
                        <button type="button" class="btn btn-sm btn-outline-secondary" data-action="history" data-workflow-id="${escapeHtml(workflow.id)}">History</button>
                        <button type="button" class="btn btn-sm btn-outline-dark" data-action="edit" data-workflow-id="${escapeHtml(workflow.id)}">Edit</button>
                        <button type="button" class="btn btn-sm btn-outline-danger" data-action="delete" data-workflow-id="${escapeHtml(workflow.id)}">Delete</button>
                    </div>
                </td>
            </tr>
        `;
    }).join("");

    refreshWorkflowSummary(items);
}

function filterWorkflows() {
    const searchTerm = normalizeText(workflowsSearchInput?.value).toLowerCase();
    if (!searchTerm) {
        renderWorkflowTable(workflows);
        return;
    }

    const filteredWorkflows = workflows.filter((workflow) => buildWorkflowSearchText(workflow).includes(searchTerm));
    renderWorkflowTable(filteredWorkflows);
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

    updateRunnerFields();
    updateTriggerFields();
    workflowModal.show();
}

function buildWorkflowPayload() {
    const runnerType = normalizeText(workflowRunnerTypeSelect?.value) || "model";
    const triggerType = normalizeText(workflowTriggerTypeSelect?.value) || "manual";
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
    };

    if (!payload.name) {
        throw new Error("Workflow name is required.");
    }
    if (!payload.task_prompt) {
        throw new Error("Task prompt is required.");
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
                    <a class="btn btn-sm btn-outline-primary" href="${escapeHtml(conversationUrl)}">Open workflow conversation</a>
                    <a class="btn btn-sm btn-outline-secondary" href="${escapeHtml(activityUrl)}" target="_blank" rel="noopener">Open activity view</a>
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

async function runWorkflow(workflow, button) {
    if (!workflow) {
        return;
    }

    const originalText = button?.textContent || "Run";
    if (button) {
        button.disabled = true;
        button.textContent = "Running...";
    }

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
        showToast(escapeHtml(error.message || "Workflow run failed."), "danger");
        await fetchUserWorkflows();
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText;
        }
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

function handleWorkflowTableClick(event) {
    const button = event.target.closest("button[data-action]");
    if (!button) {
        return;
    }

    const workflow = findWorkflowById(button.getAttribute("data-workflow-id"));
    if (!workflow) {
        return;
    }

    const action = button.getAttribute("data-action");
    if (action === "run") {
        runWorkflow(workflow, button);
    } else if (action === "history") {
        openHistoryModalForWorkflow(workflow);
    } else if (action === "edit") {
        openWorkflowModal(workflow);
    } else if (action === "delete") {
        promptDeleteWorkflow(workflow);
    }
}

async function fetchUserWorkflows() {
    if (!workflowsTableBody) {
        return [];
    }

    workflowsTableBody.innerHTML = `
        <tr class="table-loading-row">
            <td colspan="5">
                <div class="spinner-border spinner-border-sm me-2" role="status"><span class="visually-hidden">Loading...</span></div>
                Loading workflows...
            </td>
        </tr>
    `;

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
    workflowsTableBody.addEventListener("click", handleWorkflowTableClick);
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
    workflowModalEl?.addEventListener("hidden.bs.modal", resetWorkflowForm);
    workflowDeleteModalEl?.addEventListener("hidden.bs.modal", () => {
        workflowPendingDelete = null;
        if (workflowDeleteConfirmBtn) {
            workflowDeleteConfirmBtn.disabled = false;
            workflowDeleteConfirmBtn.textContent = "Delete Workflow";
        }
    });
}

window.fetchUserWorkflows = fetchUserWorkflows;

initializeWorkflowEvents();