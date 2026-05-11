// admin_model_endpoints.js

import { showToast } from "../chat/chat-toast.js";

const enableMultiEndpointToggle = document.getElementById("enable_multi_model_endpoints");
const endpointsWrapper = document.getElementById("model-endpoints-wrapper");
const endpointsTbody = document.getElementById("model-endpoints-tbody");
const addEndpointBtn = document.getElementById("add-model-endpoint-btn");
const endpointsInput = document.getElementById("model_endpoints_json");
const defaultModelSelect = document.getElementById("default-model-selection");
const defaultModelInput = document.getElementById("default_model_selection_json");
const defaultModelWrapper = document.getElementById("default-model-selection-wrapper");
const migrationPanel = document.getElementById("agent-default-model-migration-panel");
const migrationStatus = document.getElementById("agent-default-model-migration-status");
const migrationCallout = document.getElementById("agent-default-model-migration-callout");
const migrationResults = document.getElementById("agent-default-model-migration-results");
const previewMigrationBtn = document.getElementById("preview-agent-default-model-migration-btn");
const runMigrationBtn = document.getElementById("run-agent-default-model-migration-btn");
const migrationReadyCount = document.getElementById("agent-default-model-ready-count");
const migrationNeedsDefaultCount = document.getElementById("agent-default-model-needs-default-count");
const migrationManualCount = document.getElementById("agent-default-model-manual-count");
const migrationMigratedCount = document.getElementById("agent-default-model-migrated-count");
const migrationCurrentLabel = document.getElementById("agent-default-model-current-label");
const migrationSelectionSummary = document.getElementById("agent-default-model-migration-selection-summary");
const migrationTableBody = document.getElementById("agent-default-model-migration-tbody");
const migrationSearchInput = document.getElementById("agent-default-model-migration-search");
const migrationFilterSelect = document.getElementById("agent-default-model-migration-filter");
const selectReadyMigrationBtn = document.getElementById("select-ready-agent-default-model-migration-btn");
const selectManualMigrationBtn = document.getElementById("select-manual-agent-default-model-migration-btn");
const clearMigrationSelectionBtn = document.getElementById("clear-agent-default-model-migration-selection-btn");

const migrationModalEl = document.getElementById("agentDefaultModelMigrationModal");
const migrationModal = migrationModalEl && window.bootstrap ? bootstrap.Modal.getOrCreateInstance(migrationModalEl) : null;

const endpointModalEl = document.getElementById("modelEndpointModal");
const endpointModal = endpointModalEl && window.bootstrap ? bootstrap.Modal.getOrCreateInstance(endpointModalEl) : null;

const endpointIdInput = document.getElementById("model-endpoint-id");
const endpointNameInput = document.getElementById("model-endpoint-name");
const endpointProviderSelect = document.getElementById("model-endpoint-provider");
const endpointUrlInput = document.getElementById("model-endpoint-endpoint");
const endpointProjectGroup = document.getElementById("model-endpoint-project-group");
const endpointProjectInput = document.getElementById("model-endpoint-project-name");
const endpointProjectApiVersionGroup = document.getElementById("model-endpoint-project-api-version-group");
const endpointProjectApiVersionInput = document.getElementById("model-endpoint-project-api-version");
const endpointOpenAiApiVersionGroup = document.getElementById("model-endpoint-openai-api-version-group");
const endpointOpenAiApiVersionInput = document.getElementById("model-endpoint-openai-api-version");
const endpointSubscriptionGroup = document.getElementById("model-endpoint-subscription-group");
const endpointResourceGroup = document.getElementById("model-endpoint-resource-group-group");
const endpointSubscriptionInput = document.getElementById("model-endpoint-subscription-id");
const endpointResourceGroupInput = document.getElementById("model-endpoint-resource-group");
const endpointAuthTypeSelect = document.getElementById("model-endpoint-auth-type");
const endpointManagementCloudGroup = document.getElementById("model-endpoint-management-cloud-group");
const endpointManagementCloudSelect = document.getElementById("model-endpoint-management-cloud");
const endpointCustomAuthorityGroup = document.getElementById("model-endpoint-custom-authority-group");
const endpointCustomAuthorityInput = document.getElementById("model-endpoint-custom-authority");
const endpointFoundryScopeGroup = document.getElementById("model-endpoint-foundry-scope-group");
const endpointFoundryScopeInput = document.getElementById("model-endpoint-foundry-scope");
const apiKeyNote = document.getElementById("model-endpoint-api-key-note");

const miTypeGroup = document.getElementById("model-endpoint-mi-type-group");
const miClientGroup = document.getElementById("model-endpoint-mi-client-group");
const tenantGroup = document.getElementById("model-endpoint-tenant-group");
const clientGroup = document.getElementById("model-endpoint-client-group");
const secretGroup = document.getElementById("model-endpoint-secret-group");
const apiKeyGroup = document.getElementById("model-endpoint-key-group");

const miTypeSelect = document.getElementById("model-endpoint-mi-type");
const miClientIdInput = document.getElementById("model-endpoint-mi-client-id");
const tenantIdInput = document.getElementById("model-endpoint-tenant-id");
const clientIdInput = document.getElementById("model-endpoint-client-id");
const clientSecretInput = document.getElementById("model-endpoint-client-secret");
const apiKeyInput = document.getElementById("model-endpoint-api-key");

const fetchBtn = document.getElementById("model-endpoint-fetch-btn");
const saveBtn = document.getElementById("model-endpoint-save-btn");
const modelsListEl = document.getElementById("model-endpoint-models-list");
const addModelBtn = document.getElementById("model-endpoint-add-model-btn");

let modelEndpoints = Array.isArray(window.modelEndpoints) ? [...window.modelEndpoints] : [];
let modalModels = [];
let pendingDeleteEndpointId = null;
let pendingDeleteTimeout = null;
let defaultModelSelection = window.defaultModelSelection && typeof window.defaultModelSelection === "object"
    ? { ...window.defaultModelSelection }
    : {};
let migrationPreviewState = null;
let migrationSelectedKeys = new Set();

const DEFAULT_AOAI_OPENAI_API_VERSION = "2024-05-01-preview";

function generateId() {
    if (window.crypto && window.crypto.randomUUID) {
        return window.crypto.randomUUID();
    }
    return `id_${Math.random().toString(36).slice(2)}_${Date.now()}`;
}

function setElementVisibility(element, isVisible) {
    if (!element) {
        return;
    }
    element.classList.toggle("d-none", !isVisible);
}

function updateHiddenInput() {
    if (!endpointsInput) {
        return;
    }
    endpointsInput.value = JSON.stringify(modelEndpoints || []);
}

function normalizeDefaultModelSelection(selection) {
    if (!selection || typeof selection !== "object") {
        return {
            endpoint_id: "",
            model_id: "",
            provider: ""
        };
    }
    return {
        endpoint_id: String(selection.endpoint_id || "").trim(),
        model_id: String(selection.model_id || "").trim(),
        provider: String(selection.provider || "").trim().toLowerCase()
    };
}

function updateDefaultModelInput() {
    if (!defaultModelInput) {
        return;
    }
    defaultModelInput.value = JSON.stringify(defaultModelSelection || {});
}

function isAdminSettingsFormModified() {
    return typeof window.isAdminSettingsFormModified === "function" && window.isAdminSettingsFormModified();
}

function setMigrationStatus(message, tone = "muted") {
    if (!migrationStatus) {
        return;
    }

    migrationStatus.textContent = message || "";
    migrationStatus.classList.remove("text-muted", "text-success", "text-warning", "text-danger");
    const className = {
        success: "text-success",
        warning: "text-warning",
        danger: "text-danger"
    }[tone] || "text-muted";
    migrationStatus.classList.add(className);
}

function setMigrationCallout(message = "", tone = "info") {
    if (!migrationCallout) {
        return;
    }

    migrationCallout.classList.remove("alert-info", "alert-warning", "alert-success", "alert-danger");
    if (!message) {
        migrationCallout.textContent = "";
        migrationCallout.classList.add("d-none", "alert-info");
        return;
    }

    migrationCallout.textContent = message;
    migrationCallout.classList.remove("d-none");
    migrationCallout.classList.add(`alert-${tone}`);
}

function updateMigrationButtonAvailability() {
    const selectedCount = migrationSelectedKeys.size;
    const hasValidDefault = Boolean(migrationPreviewState?.default_model?.valid);
    const formModified = isAdminSettingsFormModified();
    const multiEndpointEnabled = enableMultiEndpointToggle ? enableMultiEndpointToggle.checked : true;

    if (previewMigrationBtn) {
        previewMigrationBtn.disabled = !multiEndpointEnabled;
    }
    if (runMigrationBtn) {
        runMigrationBtn.disabled = !multiEndpointEnabled || formModified || !hasValidDefault || selectedCount === 0;
        runMigrationBtn.textContent = selectedCount > 0
            ? `Apply Saved Default To Selected (${selectedCount})`
            : "Apply Saved Default To Selected";
    }
}

function handleMigrationConfigurationChange() {
    migrationPreviewState = null;
    migrationSelectedKeys = new Set();
    setElementVisibility(migrationResults, false);
    if (migrationPanel && !migrationPanel.classList.contains("d-none")) {
        const multiEndpointEnabled = enableMultiEndpointToggle ? enableMultiEndpointToggle.checked : true;
        if (!multiEndpointEnabled) {
            setMigrationStatus("Enable multi-endpoint model management to review and rebind agents to a saved default model.", "warning");
            setMigrationCallout("Once multi-endpoint is enabled and saved, admins can use this review workflow to move inherited agents to the saved default model and intentionally override selected explicit agent model choices.", "info");
        } else {
            setMigrationStatus("Save your AI model settings before reviewing or migrating agents.", "warning");
            setMigrationCallout("Migration preview uses the saved model endpoints and saved default model. Save settings first.", "warning");
        }
    } else {
        setMigrationCallout("");
    }
    renderMigrationTable();
    updateMigrationSelectionSummary();
    updateMigrationButtonAvailability();
}

function markModified() {
    if (typeof window.markFormAsModified === "function") {
        window.markFormAsModified();
    }
}

function formatProviderLabel(provider) {
    if (provider === "aifoundry") {
        return "Foundry (classic)";
    }
    if (provider === "new_foundry") {
        return "New Foundry";
    }
    return "Azure OpenAI";
}

function getDefaultOpenAiApiVersion(provider) {
    return provider === "new_foundry" ? "" : DEFAULT_AOAI_OPENAI_API_VERSION;
}

function syncOpenAiApiVersionForProvider() {
    if (!endpointOpenAiApiVersionInput) {
        return;
    }

    const provider = endpointProviderSelect?.value || "aoai";
    const currentValue = endpointOpenAiApiVersionInput.value.trim();
    if (provider === "new_foundry") {
        if (!currentValue || currentValue === DEFAULT_AOAI_OPENAI_API_VERSION) {
            endpointOpenAiApiVersionInput.value = "";
        }
        return;
    }

    if (!currentValue) {
        endpointOpenAiApiVersionInput.value = getDefaultOpenAiApiVersion(provider);
    }
}

function collectSelectedModels(endpoint) {
    const models = endpoint?.models || [];
    const selected = models.filter((model) => model?.enabled);
    if (!selected.length) {
        return "No models selected";
    }
    const names = selected.map((model) => model.displayName || model.deploymentName || model.modelName || "Unnamed");
    return names.join(", ");
}

function renderEndpoints() {
    if (!endpointsTbody) {
        return;
    }

    endpointsTbody.innerHTML = "";

    if (!modelEndpoints.length) {
        endpointsTbody.innerHTML = `
            <tr>
                <td colspan="5" class="text-center text-muted py-3">No endpoints configured yet.</td>
            </tr>
        `;
        updateHiddenInput();
        buildDefaultModelOptions();
        return;
    }

    modelEndpoints.forEach((endpoint) => {
        const row = document.createElement("tr");
        const selectedModels = collectSelectedModels(endpoint);
        const statusLabel = endpoint.enabled ? "Enabled" : "Disabled";
        const statusClass = endpoint.enabled ? "success" : "secondary";
        const toggleLabel = endpoint.enabled ? "Disable" : "Enable";

        row.innerHTML = `
            <td>
                <div class="fw-semibold">${escapeHtml(endpoint.name || "Unnamed Endpoint")}</div>
                <div class="text-muted small">${escapeHtml(endpoint.connection?.endpoint || "")}</div>
            </td>
            <td>${escapeHtml(formatProviderLabel(endpoint.provider))}</td>
            <td>
                <span title="${escapeHtml(selectedModels)}">${escapeHtml(selectedModels)}</span>
            </td>
            <td><span class="badge bg-${statusClass}">${statusLabel}</span></td>
            <td class="text-end">
                <div class="btn-group btn-group-sm" role="group">
                    <button type="button" class="btn btn-outline-primary" data-action="edit" data-endpoint-id="${endpoint.id}">Edit</button>
                    <button type="button" class="btn btn-outline-${endpoint.enabled ? "warning" : "success"}" data-action="toggle" data-endpoint-id="${endpoint.id}">${toggleLabel}</button>
                    <button type="button" class="btn btn-outline-danger" data-action="delete" data-endpoint-id="${endpoint.id}">Delete</button>
                </div>
            </td>
        `;

        endpointsTbody.appendChild(row);
    });

    updateHiddenInput();
    buildDefaultModelOptions();
}

function buildDefaultModelOptions() {
    if (!defaultModelSelect) {
        return;
    }

    defaultModelSelect.innerHTML = "";

    const emptyOption = document.createElement("option");
    emptyOption.value = "";
    emptyOption.textContent = "No default model selected";
    defaultModelSelect.appendChild(emptyOption);

    modelEndpoints.forEach((endpoint) => {
        const models = Array.isArray(endpoint.models) ? endpoint.models : [];
        const endpointLabel = endpoint.name || endpoint.connection?.endpoint || "Endpoint";
        const provider = (endpoint.provider || "aoai").toLowerCase();
        const providerLabel = formatProviderLabel(provider);
        const endpointEnabled = endpoint.enabled !== false;

        models.forEach((model) => {
            const modelId = model.id
                || model.deploymentName
                || model.deployment
                || model.modelName
                || model.name
                || generateId();
            if (!model.id) {
                model.id = modelId;
            }
            const modelEnabled = model.enabled !== false;
            const modelLabel = model.displayName || model.deploymentName || model.modelName || "Unnamed model";
            const option = document.createElement("option");
            option.value = `${endpoint.id}:${modelId}`;
            option.dataset.endpointId = endpoint.id || "";
            option.dataset.modelId = modelId || "";
            option.dataset.provider = provider;
            option.disabled = !(endpointEnabled && modelEnabled);
            option.textContent = `${endpointLabel} — ${modelLabel} (${providerLabel})`;
            if (option.disabled) {
                option.textContent += " (disabled)";
            }
            defaultModelSelect.appendChild(option);
        });
    });

    applyDefaultModelSelection(defaultModelSelection);
}

function applyDefaultModelSelection(selection) {
    if (!defaultModelSelect) {
        return;
    }

    defaultModelSelection = normalizeDefaultModelSelection(selection);

    const hasSelection = defaultModelSelection.endpoint_id && defaultModelSelection.model_id;
    const matchingOption = Array.from(defaultModelSelect.options).find((option) => {
        return option.dataset.endpointId === defaultModelSelection.endpoint_id
            && option.dataset.modelId === defaultModelSelection.model_id;
    });

    if (!hasSelection) {
        defaultModelSelect.value = "";
        updateDefaultModelInput();
        return;
    }

    if (!matchingOption || matchingOption.disabled) {
        showToast("Default model selection is no longer available. Please choose a new default.", "warning");
        defaultModelSelection = {
            endpoint_id: "",
            model_id: "",
            provider: ""
        };
        defaultModelSelect.value = "";
        updateDefaultModelInput();
        return;
    }

    defaultModelSelect.value = matchingOption.value;
    updateDefaultModelInput();
}

function handleDefaultModelChange() {
    if (!defaultModelSelect) {
        return;
    }

    const selectedOption = defaultModelSelect.selectedOptions[0];
    if (!selectedOption || !selectedOption.value) {
        defaultModelSelection = {
            endpoint_id: "",
            model_id: "",
            provider: ""
        };
    } else {
        defaultModelSelection = {
            endpoint_id: selectedOption.dataset.endpointId || "",
            model_id: selectedOption.dataset.modelId || "",
            provider: selectedOption.dataset.provider || ""
        };
    }
    updateDefaultModelInput();
    markModified();
    handleMigrationConfigurationChange();
}

function updateAuthVisibility() {
    const authType = endpointAuthTypeSelect?.value || "managed_identity";
    const provider = endpointProviderSelect?.value || "aoai";
    const isApiKey = authType === "api_key";
    const isFoundry = provider === "aifoundry" || provider === "new_foundry";
    setElementVisibility(endpointProjectGroup, isFoundry);
    setElementVisibility(endpointProjectApiVersionGroup, isFoundry);
    setElementVisibility(endpointOpenAiApiVersionGroup, true);
    setElementVisibility(endpointSubscriptionGroup, provider === "aoai" && !isApiKey);
    setElementVisibility(endpointResourceGroup, provider === "aoai" && !isApiKey);
    setElementVisibility(miTypeGroup, authType === "managed_identity");
    setElementVisibility(miClientGroup, authType === "managed_identity" && (miTypeSelect?.value === "user_assigned"));
    setElementVisibility(tenantGroup, authType === "service_principal");
    setElementVisibility(clientGroup, authType === "service_principal");
    setElementVisibility(secretGroup, authType === "service_principal");
    setElementVisibility(apiKeyGroup, authType === "api_key");
    setElementVisibility(endpointManagementCloudGroup, authType === "service_principal" && isFoundry);
    setElementVisibility(endpointCustomAuthorityGroup, authType === "service_principal" && isFoundry && endpointManagementCloudSelect?.value === "custom");
    setElementVisibility(endpointFoundryScopeGroup, authType === "service_principal" && isFoundry && endpointManagementCloudSelect?.value === "custom");
    setElementVisibility(apiKeyNote, authType === "api_key");
    setElementVisibility(addModelBtn, authType === "api_key");
    setElementVisibility(fetchBtn, authType !== "api_key");
}

function resetModal() {
    if (endpointIdInput) endpointIdInput.value = "";
    if (endpointNameInput) endpointNameInput.value = "";
    if (endpointProviderSelect) endpointProviderSelect.value = "aoai";
    if (endpointUrlInput) endpointUrlInput.value = "";
    if (endpointProjectInput) endpointProjectInput.value = "";
    if (endpointProjectApiVersionInput) endpointProjectApiVersionInput.value = "v1";
    if (endpointOpenAiApiVersionInput) endpointOpenAiApiVersionInput.value = getDefaultOpenAiApiVersion("aoai");
    if (endpointSubscriptionInput) endpointSubscriptionInput.value = "";
    if (endpointResourceGroupInput) endpointResourceGroupInput.value = "";
    if (endpointAuthTypeSelect) endpointAuthTypeSelect.value = "managed_identity";
    if (endpointManagementCloudSelect) endpointManagementCloudSelect.value = "public";
    if (endpointCustomAuthorityInput) endpointCustomAuthorityInput.value = "";
    if (endpointFoundryScopeInput) endpointFoundryScopeInput.value = "";
    if (miTypeSelect) miTypeSelect.value = "system_assigned";
    if (miClientIdInput) miClientIdInput.value = "";
    if (tenantIdInput) tenantIdInput.value = "";
    if (clientIdInput) clientIdInput.value = "";
    if (clientSecretInput) clientSecretInput.value = "";
    if (apiKeyInput) apiKeyInput.value = "";
    if (clientSecretInput) clientSecretInput.placeholder = "";
    if (apiKeyInput) apiKeyInput.placeholder = "";

    modalModels = [];
    if (modelsListEl) modelsListEl.innerHTML = "<p class=\"text-muted\">Fetch models to begin selection.</p>";

    updateAuthVisibility();
}

function openModalForEndpoint(endpoint) {
    if (!endpointModal) {
        return;
    }

    resetModal();

    if (endpoint) {
        if (endpointIdInput) endpointIdInput.value = endpoint.id || "";
        if (endpointNameInput) endpointNameInput.value = endpoint.name || "";
        if (endpointProviderSelect) endpointProviderSelect.value = endpoint.provider || "aoai";
        if (endpointUrlInput) endpointUrlInput.value = endpoint.connection?.endpoint || "";
        if (endpointProjectInput) endpointProjectInput.value = endpoint.connection?.project_name || "";
        if (endpointProjectApiVersionInput) {
            endpointProjectApiVersionInput.value = endpoint.connection?.project_api_version || endpoint.connection?.api_version || "v1";
        }
        if (endpointOpenAiApiVersionInput) {
            endpointOpenAiApiVersionInput.value = endpoint.connection?.openai_api_version || endpoint.connection?.api_version || getDefaultOpenAiApiVersion(endpoint.provider || "aoai");
        }
        if (endpointSubscriptionInput) endpointSubscriptionInput.value = endpoint.management?.subscription_id || "";
        if (endpointResourceGroupInput) endpointResourceGroupInput.value = endpoint.management?.resource_group || "";
        if (endpointAuthTypeSelect) endpointAuthTypeSelect.value = endpoint.auth?.type || "managed_identity";
        if (endpointManagementCloudSelect) endpointManagementCloudSelect.value = endpoint.auth?.management_cloud || "public";
        if (endpointCustomAuthorityInput) endpointCustomAuthorityInput.value = endpoint.auth?.custom_authority || "";
        if (endpointFoundryScopeInput) endpointFoundryScopeInput.value = endpoint.auth?.foundry_scope || "";
        if (miTypeSelect) miTypeSelect.value = endpoint.auth?.managed_identity_type || "system_assigned";
        if (miClientIdInput) miClientIdInput.value = endpoint.auth?.managed_identity_client_id || "";
        if (tenantIdInput) tenantIdInput.value = endpoint.auth?.tenant_id || "";
        if (clientIdInput) clientIdInput.value = endpoint.auth?.client_id || "";
        if (clientSecretInput) {
            clientSecretInput.value = endpoint.auth?.client_secret || "";
            if (!clientSecretInput.value && endpoint.has_client_secret) {
                clientSecretInput.placeholder = "Stored";
            }
        }
        if (apiKeyInput) {
            apiKeyInput.value = endpoint.auth?.api_key || "";
            if (!apiKeyInput.value && endpoint.has_api_key) {
                apiKeyInput.placeholder = "Stored";
            }
        }
        modalModels = Array.isArray(endpoint.models) ? [...endpoint.models] : [];
        renderModalModels(modalModels);
    }

    updateAuthVisibility();
    endpointModal.show();
}

function renderModalModels(models) {
    if (!modelsListEl) {
        return;
    }

    if (!models || !models.length) {
        modelsListEl.innerHTML = "<p class=\"text-muted\">No models loaded yet.</p>";
        return;
    }

    const fragment = document.createDocumentFragment();
    models.forEach((model) => {
        const wrapper = document.createElement("div");
        wrapper.className = "border rounded p-2 mb-2";
        const deploymentName = model.deploymentName || "";
        const modelName = model.modelName || "";
        const displayName = model.displayName || deploymentName;
        const description = model.description || "";
        const deploymentReadonly = model.isDiscovered ? "readonly" : "";
        const modelId = model.id || generateId();
        model.id = modelId;

        wrapper.innerHTML = `
            <div class="form-check mb-2">
                <input class="form-check-input" type="checkbox" data-model-id="${modelId}" ${model.enabled ? "checked" : ""}>
                <label class="form-check-label">
                    ${escapeHtml(deploymentName)} ${modelName ? `<span class=\"text-muted\">(${escapeHtml(modelName)})</span>` : ""}
                </label>
            </div>
            <div class="row g-2">
                <div class="col-md-4">
                    <label class="form-label small">Deployment Name</label>
                    <input type="text" class="form-control form-control-sm" data-deployment-name-for="${modelId}" value="${escapeHtml(deploymentName)}" ${deploymentReadonly}>
                </div>
                <div class="col-md-6">
                    <label class="form-label small">Display Name</label>
                    <input type="text" class="form-control form-control-sm" data-display-name-for="${modelId}" value="${escapeHtml(displayName)}">
                </div>
                <div class="col-md-6">
                    <label class="form-label small">Description (optional)</label>
                    <input type="text" class="form-control form-control-sm" data-description-for="${modelId}" value="${escapeHtml(description)}">
                </div>
            </div>
            <div class="d-flex gap-2 mt-2">
                <button type="button" class="btn btn-sm btn-outline-secondary" data-action="test-model" data-model-id="${modelId}">Test Connection</button>
                <button type="button" class="btn btn-sm btn-outline-danger" data-action="remove-model" data-model-id="${modelId}">Remove</button>
            </div>
        `;
        fragment.appendChild(wrapper);
    });

    modelsListEl.innerHTML = "";
    modelsListEl.appendChild(fragment);
}

function collectModalModels() {
    if (!modelsListEl) {
        return [];
    }

    const updated = modalModels.map((model) => ({ ...model }));
    updated.forEach((model) => {
        const checkbox = modelsListEl.querySelector(`input[data-model-id="${model.id}"]`);
        const deploymentInput = modelsListEl.querySelector(`input[data-deployment-name-for="${model.id}"]`);
        const displayInput = modelsListEl.querySelector(`input[data-display-name-for="${model.id}"]`);
        const descriptionInput = modelsListEl.querySelector(`input[data-description-for="${model.id}"]`);
        model.enabled = checkbox ? checkbox.checked : model.enabled;
        model.deploymentName = deploymentInput ? deploymentInput.value.trim() : model.deploymentName;
        model.displayName = displayInput ? displayInput.value.trim() : model.displayName;
        model.description = descriptionInput ? descriptionInput.value.trim() : model.description;
    });
    return updated;
}

async function testModelConnection(model) {
    const payload = buildEndpointPayload();
    if (!payload || !model?.deploymentName) {
        showToast("Model deployment name is required for testing.", "warning");
        return;
    }

    const requestBody = {
        ...payload,
        model: {
            deploymentName: model.deploymentName
        }
    };

    try {
        const response = await fetch("/api/models/test-model", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(requestBody)
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || "Connection test failed.");
        }
        showToast("Model connection successful.", "success");
    } catch (error) {
        console.error("Model connection failed", error);
        showToast(error.message || "Model connection failed.", "danger");
    }
}

async function fetchModels() {
    const payload = buildEndpointPayload();
    if (!payload) {
        return;
    }

    modalModels = collectModalModels();

    try {
        const response = await fetch("/api/models/fetch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || "Failed to fetch models.");
        }

        const models = Array.isArray(data.models) ? data.models : [];
        const existingMap = new Map();
        modalModels.forEach((model) => {
            const key = (model.deploymentName || "").trim().toLowerCase();
            if (key) {
                existingMap.set(key, model);
            }
        });

        let addedCount = 0;
        models.forEach((model) => {
            const deploymentName = (model.deploymentName || model.deployment || "").trim();
            if (!deploymentName) {
                return;
            }
            const key = deploymentName.toLowerCase();
            if (existingMap.has(key)) {
                return;
            }
            modalModels.push({
                id: generateId(),
                deploymentName,
                modelName: model.modelName || model.name || "",
                displayName: deploymentName,
                description: "",
                enabled: false,
                isDiscovered: true
            });
            existingMap.set(key, true);
            addedCount += 1;
        });
        renderModalModels(modalModels);
        showToast(`Fetched ${models.length} models. Added ${addedCount} new.`, "success");
    } catch (error) {
        console.error("Model fetch failed", error);
        showToast(error.message || "Failed to fetch models.", "danger");
    }
}

function buildEndpointPayload() {
    if (!endpointNameInput || !endpointUrlInput || !endpointOpenAiApiVersionInput) {
        return null;
    }
    const endpointId = endpointIdInput?.value.trim() || "";
    const name = endpointNameInput.value.trim();
    const endpoint = endpointUrlInput.value.trim();
    const projectName = endpointProjectInput?.value.trim() || "";
    const projectApiVersion = endpointProjectApiVersionInput?.value.trim() || "v1";
    const openAiApiVersion = endpointOpenAiApiVersionInput.value.trim();
    const provider = endpointProviderSelect?.value || "aoai";
    const subscriptionId = endpointSubscriptionInput?.value.trim() || "";
    const resourceGroup = endpointResourceGroupInput?.value.trim() || "";
    const authType = endpointAuthTypeSelect?.value || "managed_identity";

    if (!name || !endpoint || !openAiApiVersion) {
        showToast("Endpoint name, URL, and OpenAI API version are required.", "warning");
        return null;
    }

    if ((provider === "aifoundry" || provider === "new_foundry") && !projectApiVersion) {
        showToast("Project API version is required for Foundry project discovery.", "warning");
        return null;
    }

    if ((provider === "aifoundry" || provider === "new_foundry") && !endpoint.includes("/api/projects/") && !projectName) {
        showToast("Foundry project name is required when the endpoint does not include /api/projects/.", "warning");
        return null;
    }

    if (provider === "aoai" && authType !== "api_key" && (!subscriptionId || !resourceGroup)) {
        showToast("Subscription ID and resource group are required for Azure OpenAI model discovery.", "warning");
        return null;
    }

    const auth = {
        type: authType,
        managed_identity_type: miTypeSelect?.value || "system_assigned",
        managed_identity_client_id: miClientIdInput?.value.trim() || "",
        tenant_id: tenantIdInput?.value.trim() || "",
        client_id: clientIdInput?.value.trim() || "",
        client_secret: clientSecretInput?.value.trim() || "",
        api_key: apiKeyInput?.value.trim() || "",
        management_cloud: endpointManagementCloudSelect?.value || "public",
        custom_authority: endpointCustomAuthorityInput?.value.trim() || "",
        foundry_scope: endpointFoundryScopeInput?.value.trim() || ""
    };

    if (authType === "service_principal" && (!auth.tenant_id || !auth.client_id || !auth.client_secret)) {
        showToast("Tenant ID, Client ID, and Client Secret are required for service principal auth.", "warning");
        return null;
    }

    if ((provider === "aifoundry" || provider === "new_foundry") && authType === "service_principal" && auth.management_cloud === "custom") {
        if (!auth.custom_authority) {
            showToast("Custom authority is required when Management Cloud is set to Custom.", "warning");
            return null;
        }
        if (!auth.foundry_scope) {
            showToast("Foundry scope is required when Management Cloud is set to Custom.", "warning");
            return null;
        }
    }

    if (authType === "api_key" && !auth.api_key) {
        showToast("API key is required for API key authentication.", "warning");
        return null;
    }

    const management = provider === "aoai" ? {
        subscription_id: subscriptionId,
        resource_group: resourceGroup
    } : {};

    const connection = {
        endpoint,
        openai_api_version: openAiApiVersion
    };

    if (provider === "aifoundry" || provider === "new_foundry") {
        connection.project_api_version = projectApiVersion;
        if (projectName) {
            connection.project_name = projectName;
        }
    }

    return {
        id: endpointId,
        provider,
        name,
        connection,
        management,
        auth
    };
}

function saveEndpoint() {
    try {
        const payload = buildEndpointPayload();
        if (!payload) {
            return;
        }

        const models = collectModalModels();
        const endpointId = endpointIdInput?.value || generateId();
        const existingEndpoint = modelEndpoints.find((endpoint) => endpoint.id === endpointId);
        const authType = payload.auth?.type || "managed_identity";
        const hasApiKey = authType === "api_key" && (Boolean(payload.auth?.api_key) || Boolean(existingEndpoint?.has_api_key));
        const hasClientSecret = authType === "service_principal" && (Boolean(payload.auth?.client_secret) || Boolean(existingEndpoint?.has_client_secret));

        const endpointData = {
            id: endpointId,
            name: payload.name,
            provider: payload.provider,
            enabled: true,
            auth: payload.auth,
            connection: payload.connection,
            management: payload.management,
            models,
            has_api_key: hasApiKey,
            has_client_secret: hasClientSecret
        };

        const existingIndex = modelEndpoints.findIndex((endpoint) => endpoint.id === endpointId);
        if (existingIndex >= 0) {
            modelEndpoints[existingIndex] = endpointData;
        } else {
            modelEndpoints.push(endpointData);
        }

        renderEndpoints();
        markModified();
        handleMigrationConfigurationChange();
        endpointModal?.hide();
        showToast("Please save your settings to persist changes.", "warning");
    } catch (error) {
        console.error("Failed to save endpoint", error);
        showToast(error?.message || "Failed to save endpoint.", "danger");
    }
}

function addManualModel() {
    modalModels.push({
        id: generateId(),
        deploymentName: "",
        modelName: "",
        displayName: "",
        description: "",
        enabled: true,
        isDiscovered: false
    });
    renderModalModels(modalModels);
}

function handleModelListClick(event) {
    const button = event.target.closest("button[data-action]");
    if (!button) {
        return;
    }
    const action = button.dataset.action;
    const modelId = button.dataset.modelId;
    modalModels = collectModalModels();
    const model = modalModels.find((item) => item.id === modelId);
    if (!model) {
        return;
    }

    if (action === "remove-model") {
        modalModels = modalModels.filter((item) => item.id !== modelId);
        renderModalModels(modalModels);
        return;
    }

    if (action === "test-model") {
        testModelConnection(model);
    }
}

function handleTableClick(event) {
    const button = event.target.closest("button[data-action]");
    if (!button) {
        return;
    }
    const action = button.dataset.action;
    const endpointId = button.dataset.endpointId;
    const endpoint = modelEndpoints.find((item) => item.id === endpointId);
    if (!endpoint) {
        return;
    }

    if (action === "edit") {
        openModalForEndpoint(endpoint);
        return;
    }

    if (action === "toggle") {
        endpoint.enabled = !endpoint.enabled;
        renderEndpoints();
        markModified();
        handleMigrationConfigurationChange();
        return;
    }

    if (action === "delete") {
        if (pendingDeleteEndpointId === endpointId) {
            modelEndpoints = modelEndpoints.filter((item) => item.id !== endpointId);
            renderEndpoints();
            markModified();
            handleMigrationConfigurationChange();
            pendingDeleteEndpointId = null;
            if (pendingDeleteTimeout) {
                clearTimeout(pendingDeleteTimeout);
                pendingDeleteTimeout = null;
            }
            showToast("Endpoint deleted.", "success");
            return;
        }
        pendingDeleteEndpointId = endpointId;
        showToast("Click delete again to confirm removal.", "warning");
        if (pendingDeleteTimeout) {
            clearTimeout(pendingDeleteTimeout);
        }
        pendingDeleteTimeout = setTimeout(() => {
            pendingDeleteEndpointId = null;
            pendingDeleteTimeout = null;
        }, 5000);
    }
}

function handleToggleChange() {
    const enabled = !!enableMultiEndpointToggle?.checked;
    // setElementVisibility(endpointsWrapper, enabled);
    setElementVisibility(defaultModelWrapper, enabled);
    if (!enabled) {
        setElementVisibility(migrationResults, false);
    }
    markModified();
    handleMigrationConfigurationChange();
}

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value || "";
    return div.innerHTML;
}

function formatMigrationStatus(status) {
    if (status === "ready_to_migrate") {
        return { label: "Ready", className: "text-bg-primary" };
    }
    if (status === "needs_default_model") {
        return { label: "Needs Default", className: "text-bg-warning" };
    }
    if (status === "manual_review") {
        return { label: "Review", className: "text-bg-secondary" };
    }
    return { label: "On Default", className: "text-bg-success" };
}

function getMigrationAgents() {
    return Array.isArray(migrationPreviewState?.agents) ? migrationPreviewState.agents : [];
}

function resetMigrationSelection(preview) {
    const nextSelection = new Set();
    const agents = Array.isArray(preview?.agents) ? preview.agents : [];
    agents.forEach((agent) => {
        if (agent?.selected_by_default && agent?.selection_key) {
            nextSelection.add(agent.selection_key);
        }
    });
    migrationSelectedKeys = nextSelection;
}

function getFilteredMigrationAgents() {
    const query = (migrationSearchInput?.value || "").trim().toLowerCase();
    const filterValue = migrationFilterSelect?.value || "all";

    return getMigrationAgents().filter((agent) => {
        if (filterValue === "selected" && !migrationSelectedKeys.has(agent.selection_key)) {
            return false;
        }
        if (filterValue !== "all" && filterValue !== "selected" && agent.migration_status !== filterValue) {
            return false;
        }
        if (!query) {
            return true;
        }

        const haystack = [
            agent.scope,
            agent.scope_label,
            agent.agent_display_name,
            agent.agent_name,
            agent.current_binding_label,
            agent.reason
        ].join(" ").toLowerCase();
        return haystack.includes(query);
    });
}

function updateMigrationSelectionSummary() {
    if (!migrationSelectionSummary) {
        return;
    }

    const selectedAgents = getMigrationAgents().filter((agent) => migrationSelectedKeys.has(agent.selection_key));
    const selectedCount = selectedAgents.length;
    const recommendedCount = selectedAgents.filter((agent) => agent.migration_status === "ready_to_migrate").length;
    const overrideCount = selectedAgents.filter((agent) => agent.can_force_migrate).length;

    if (!selectedCount) {
        migrationSelectionSummary.textContent = "No agents selected. Recommended rows are preselected after each review refresh.";
        return;
    }

    migrationSelectionSummary.textContent = `Selected ${selectedCount} agents: ${recommendedCount} recommended and ${overrideCount} explicit overrides.`;
}

function renderMigrationTable() {
    if (!migrationTableBody) {
        return;
    }

    if (!migrationPreviewState) {
        migrationTableBody.innerHTML = `
            <tr>
                <td colspan="6" class="text-center text-muted py-3">Review agents to load migration candidates.</td>
            </tr>
        `;
        return;
    }

    const agents = getFilteredMigrationAgents();
    if (!agents.length) {
        migrationTableBody.innerHTML = `
            <tr>
                <td colspan="6" class="text-center text-muted py-3">No agents match the current filter.</td>
            </tr>
        `;
        return;
    }

    migrationTableBody.innerHTML = agents.map((agent) => {
        const status = formatMigrationStatus(agent.migration_status);
        const agentLabel = agent.agent_display_name || agent.agent_name || "Unnamed agent";
        const secondaryLabel = agent.agent_display_name && agent.agent_name && agent.agent_display_name !== agent.agent_name
            ? `<div class="text-muted small">${escapeHtml(agent.agent_name)}</div>`
            : "";
        const scopeSuffix = agent.scope !== "global" && agent.scope_label
            ? `<div class="text-muted small">${escapeHtml(agent.scope_label)}</div>`
            : "";
        const isSelected = migrationSelectedKeys.has(agent.selection_key);
        const selectControl = agent.can_select
            ? `
                <div class="form-check m-0">
                    <input class="form-check-input" type="checkbox" data-selection-key="${escapeHtml(agent.selection_key)}" ${isSelected ? "checked" : ""} aria-label="Select ${escapeHtml(agentLabel)}" />
                </div>
                <div class="text-muted small mt-1">${agent.selected_by_default ? "Recommended" : "Override"}</div>
            `
            : '<span class="text-muted small">Locked</span>';

        return `
            <tr>
                <td>${selectControl}</td>
                <td>
                    <div class="fw-semibold text-capitalize">${escapeHtml(agent.scope)}</div>
                    ${scopeSuffix}
                </td>
                <td>
                    <div class="fw-semibold">${escapeHtml(agentLabel)}</div>
                    ${secondaryLabel}
                </td>
                <td><span class="badge ${status.className}">${status.label}</span></td>
                <td>${escapeHtml(agent.current_binding_label || "Not set")}</td>
                <td>${escapeHtml(agent.reason || "")}</td>
            </tr>
        `;
    }).join("");
}

function selectRecommendedMigrationAgents() {
    const nextSelection = new Set();
    getMigrationAgents().forEach((agent) => {
        if (agent?.selected_by_default && agent?.selection_key) {
            nextSelection.add(agent.selection_key);
        }
    });
    migrationSelectedKeys = nextSelection;
    renderMigrationTable();
    updateMigrationSelectionSummary();
    updateMigrationButtonAvailability();
}

function addManualOverrideMigrationAgents() {
    getMigrationAgents().forEach((agent) => {
        if (agent?.can_force_migrate && agent?.selection_key) {
            migrationSelectedKeys.add(agent.selection_key);
        }
    });
    renderMigrationTable();
    updateMigrationSelectionSummary();
    updateMigrationButtonAvailability();
}

function clearMigrationSelection() {
    migrationSelectedKeys = new Set();
    renderMigrationTable();
    updateMigrationSelectionSummary();
    updateMigrationButtonAvailability();
}

function handleMigrationTableSelectionChange(event) {
    const checkbox = event.target.closest('input[data-selection-key]');
    if (!checkbox) {
        return;
    }

    const selectionKey = checkbox.dataset.selectionKey || "";
    if (!selectionKey) {
        return;
    }

    if (checkbox.checked) {
        migrationSelectedKeys.add(selectionKey);
    } else {
        migrationSelectedKeys.delete(selectionKey);
    }

    updateMigrationSelectionSummary();
    updateMigrationButtonAvailability();
}

async function openMigrationReviewModal() {
    await loadAgentMigrationPreview({ openModal: true, showToastOnSuccess: false });
}

function renderMigrationPreview(preview) {
    migrationPreviewState = preview || null;

    if (!preview || !migrationResults || !migrationTableBody) {
        migrationSelectedKeys = new Set();
        renderMigrationTable();
        updateMigrationSelectionSummary();
        updateMigrationButtonAvailability();
        return;
    }

    resetMigrationSelection(preview);

    const summary = preview.summary || {};
    const defaultModel = preview.default_model || {};

    if (migrationReadyCount) {
        migrationReadyCount.textContent = `Ready: ${summary.ready_to_migrate || 0}`;
    }
    if (migrationNeedsDefaultCount) {
        migrationNeedsDefaultCount.textContent = `Needs Default: ${summary.needs_default_model || 0}`;
    }
    if (migrationManualCount) {
        migrationManualCount.textContent = `Manual Review: ${summary.manual_review || 0}`;
    }
    if (migrationMigratedCount) {
        migrationMigratedCount.textContent = `On Default: ${summary.already_migrated || 0}`;
    }
    if (migrationCurrentLabel) {
        migrationCurrentLabel.textContent = defaultModel.valid
            ? `Saved default model: ${defaultModel.label}`
            : "Saved default model: none selected or no longer available";
    }

    if (!defaultModel.valid && (summary.needs_default_model || 0) > 0) {
        setMigrationStatus("Save a valid default model before migrating inherited agents.", "warning");
        setMigrationCallout("Select and save a valid default model first, then rerun the review or migration.", "warning");
    } else if ((summary.ready_to_migrate || 0) > 0 || (summary.selectable_override || 0) > 0) {
        setMigrationStatus(
            `Found ${summary.ready_to_migrate || 0} recommended agents and ${summary.selectable_override || 0} explicit override candidates for the saved default model.`,
            "warning"
        );
        setMigrationCallout("Use the review modal to confirm the recommended agents and add only the explicit overrides you intentionally want to rebind to the saved default model.", "info");
    } else if ((summary.manual_review || 0) > 0) {
        setMigrationStatus("Only manual-review agents remain, and some may require separate handling.", "warning");
        setMigrationCallout("Foundry-managed agents stay locked here. Other manual-review rows can be selected only when a saved default model is available.", "info");
    } else {
        setMigrationStatus("All reviewable agents are already aligned with the saved default model.", "success");
        setMigrationCallout("Use this review workflow again whenever you want to evaluate agents against a new saved default model for cost or lifecycle changes.", "success");
    }

    renderMigrationTable();
    updateMigrationSelectionSummary();
    setElementVisibility(migrationResults, true);
    updateMigrationButtonAvailability();
}

async function loadAgentMigrationPreview({ showToastOnSuccess = false, openModal = false } = {}) {
    if (isAdminSettingsFormModified()) {
        setMigrationStatus("Save your AI model settings before reviewing agents.", "warning");
        setMigrationCallout("The migration preview uses the saved default model and saved endpoint catalog. Save settings first.", "warning");
        showToast("Save your AI model settings before reviewing agents.", "warning");
        updateMigrationButtonAvailability();
        return null;
    }

    if (previewMigrationBtn) {
        previewMigrationBtn.disabled = true;
    }

    try {
        const response = await fetch("/api/admin/agents/default-model-migration/preview", {
            headers: { "Content-Type": "application/json" }
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || "Failed to review agent migration state.");
        }

        renderMigrationPreview(data);
        if (openModal && migrationModal) {
            migrationModal.show();
        }
        if (showToastOnSuccess) {
            showToast("Agent migration review updated.", "success");
        }
        return data;
    } catch (error) {
        console.error("Agent migration preview failed", error);
        setMigrationStatus("Unable to load the agent migration review.", "danger");
        setMigrationCallout(error.message || "Failed to load the agent migration review.", "danger");
        showToast(error.message || "Failed to load the agent migration review.", "danger");
        return null;
    } finally {
        if (previewMigrationBtn) {
            previewMigrationBtn.disabled = false;
        }
        updateMigrationButtonAvailability();
    }
}

async function runDefaultModelAgentMigration() {
    if (isAdminSettingsFormModified()) {
        setMigrationStatus("Save your AI model settings before running migration.", "warning");
        setMigrationCallout("The migration run uses the saved default model and saved endpoint catalog. Save settings first.", "warning");
        showToast("Save your AI model settings before running migration.", "warning");
        updateMigrationButtonAvailability();
        return;
    }

    if (!migrationPreviewState) {
        const preview = await loadAgentMigrationPreview();
        if (!preview) {
            return;
        }
    }

    if (!migrationPreviewState?.default_model?.valid) {
        setMigrationStatus("A valid saved default model is required before migration.", "warning");
        setMigrationCallout("Select and save a valid default model before migrating inherited agents.", "warning");
        showToast("Select and save a valid default model before migrating agents.", "warning");
        updateMigrationButtonAvailability();
        return;
    }

    if (!migrationSelectedKeys.size) {
        showToast("Select at least one agent in the review modal before migrating.", "warning");
        updateMigrationButtonAvailability();
        return;
    }

    if (runMigrationBtn) {
        runMigrationBtn.disabled = true;
    }

    try {
        const response = await fetch("/api/admin/agents/default-model-migration/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                selected_agent_keys: Array.from(migrationSelectedKeys)
            })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || "Failed to migrate agents to the saved default model.");
        }

        renderMigrationPreview(data.preview || null);

        if (Array.isArray(data.failed) && data.failed.length) {
            setMigrationCallout(`Migrated ${data.migrated_count || 0} agents, but ${data.failed.length} updates failed. Review server logs for details.`, "warning");
            showToast(`Migrated ${data.migrated_count || 0} agents with ${data.failed.length} failures.`, "warning");
        } else {
            showToast(`Applied the saved default model to ${data.migrated_count || 0} selected agents.`, "success");
        }
    } catch (error) {
        console.error("Agent migration failed", error);
        setMigrationStatus("Agent migration failed.", "danger");
        setMigrationCallout(error.message || "Failed to migrate agents to the saved default model.", "danger");
        showToast(error.message || "Failed to migrate agents to the saved default model.", "danger");
    } finally {
        updateMigrationButtonAvailability();
    }
}

function init() {
    const isMultiEndpointEnabled = enableMultiEndpointToggle ? enableMultiEndpointToggle.checked : true;

    renderEndpoints();
    updateAuthVisibility();
    setElementVisibility(endpointsWrapper, isMultiEndpointEnabled);
    setElementVisibility(defaultModelWrapper, isMultiEndpointEnabled);

    if (enableMultiEndpointToggle) {
        enableMultiEndpointToggle.addEventListener("change", handleToggleChange);
    }

    if (endpointAuthTypeSelect) {
        endpointAuthTypeSelect.addEventListener("change", updateAuthVisibility);
    }
    if (endpointProviderSelect) {
        endpointProviderSelect.addEventListener("change", () => {
            updateAuthVisibility();
            syncOpenAiApiVersionForProvider();
        });
    }
    if (miTypeSelect) {
        miTypeSelect.addEventListener("change", updateAuthVisibility);
    }
    if (endpointManagementCloudSelect) {
        endpointManagementCloudSelect.addEventListener("change", updateAuthVisibility);
    }

    if (addEndpointBtn) {
        addEndpointBtn.addEventListener("click", () => openModalForEndpoint(null));
    }

    if (addModelBtn) {
        addModelBtn.addEventListener("click", addManualModel);
    }

    if (endpointsTbody) {
        endpointsTbody.addEventListener("click", handleTableClick);
    }

    if (modelsListEl) {
        modelsListEl.addEventListener("click", handleModelListClick);
    }

    if (fetchBtn) {
        fetchBtn.addEventListener("click", fetchModels);
    }
    if (saveBtn) {
        saveBtn.addEventListener("click", (event) => {
            event.preventDefault();
            saveEndpoint();
        });
    }

    if (defaultModelSelect) {
        defaultModelSelect.addEventListener("change", handleDefaultModelChange);
    }

    if (previewMigrationBtn) {
        previewMigrationBtn.addEventListener("click", () => {
            openMigrationReviewModal();
        });
    }

    if (runMigrationBtn) {
        runMigrationBtn.addEventListener("click", () => {
            runDefaultModelAgentMigration();
        });
    }

    if (migrationTableBody) {
        migrationTableBody.addEventListener("change", handleMigrationTableSelectionChange);
    }

    if (migrationSearchInput) {
        migrationSearchInput.addEventListener("input", renderMigrationTable);
    }

    if (migrationFilterSelect) {
        migrationFilterSelect.addEventListener("change", renderMigrationTable);
    }

    if (selectReadyMigrationBtn) {
        selectReadyMigrationBtn.addEventListener("click", selectRecommendedMigrationAgents);
    }

    if (selectManualMigrationBtn) {
        selectManualMigrationBtn.addEventListener("click", addManualOverrideMigrationAgents);
    }

    if (clearMigrationSelectionBtn) {
        clearMigrationSelectionBtn.addEventListener("click", clearMigrationSelection);
    }

    updateHiddenInput();
    buildDefaultModelOptions();
    updateMigrationButtonAvailability();

    if (migrationPanel && isMultiEndpointEnabled) {
        setMigrationStatus("Review inherited agents and migrate them to the saved default model when ready.", "muted");
        loadAgentMigrationPreview();
    } else if (migrationPanel) {
        handleMigrationConfigurationChange();
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
} else {
    init();
}
