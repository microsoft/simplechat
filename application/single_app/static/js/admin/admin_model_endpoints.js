// admin_model_endpoints.js

import { showToast } from "../chat/chat-toast.js";

const enableMultiEndpointToggle = document.getElementById("enable_multi_model_endpoints");
const migrationWarning = document.getElementById("multi-endpoint-warning");
const endpointsWrapper = document.getElementById("model-endpoints-wrapper");
const endpointsTbody = document.getElementById("model-endpoints-tbody");
const addEndpointBtn = document.getElementById("add-model-endpoint-btn");
const endpointsInput = document.getElementById("model_endpoints_json");
const defaultModelSelect = document.getElementById("default-model-selection");
const defaultModelInput = document.getElementById("default_model_selection_json");
const defaultModelWrapper = document.getElementById("default-model-selection-wrapper");

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

function markModified() {
    if (typeof window.markFormAsModified === "function") {
        window.markFormAsModified();
    }
}

function formatProviderLabel(provider) {
    if (provider === "aifoundry") {
        return "Azure AI Foundry";
    }
    return "Azure OpenAI";
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
}

function updateAuthVisibility() {
    const authType = endpointAuthTypeSelect?.value || "managed_identity";
    const provider = endpointProviderSelect?.value || "aoai";
    const isApiKey = authType === "api_key";
    const isFoundry = provider === "aifoundry";
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
    if (endpointOpenAiApiVersionInput) endpointOpenAiApiVersionInput.value = "2024-05-01-preview";
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
            endpointOpenAiApiVersionInput.value = endpoint.connection?.openai_api_version || endpoint.connection?.api_version || "2024-05-01-preview";
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
        if (clientSecretInput) clientSecretInput.value = endpoint.auth?.client_secret || "";
        if (apiKeyInput) apiKeyInput.value = endpoint.auth?.api_key || "";
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

    if (provider === "aifoundry" && !projectApiVersion) {
        showToast("Project API version is required for Foundry project discovery.", "warning");
        return null;
    }

    if (provider === "aifoundry" && !endpoint.includes("/api/projects/") && !projectName) {
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

    if (provider === "aifoundry" && authType === "service_principal" && auth.management_cloud === "custom") {
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

    if (provider === "aifoundry") {
        connection.project_api_version = projectApiVersion;
        if (projectName) {
            connection.project_name = projectName;
        }
    }

    return {
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

        const endpointData = {
            id: endpointId,
            name: payload.name,
            provider: payload.provider,
            enabled: true,
            auth: payload.auth,
            connection: payload.connection,
            management: payload.management,
            models
        };

        const existingIndex = modelEndpoints.findIndex((endpoint) => endpoint.id === endpointId);
        if (existingIndex >= 0) {
            modelEndpoints[existingIndex] = endpointData;
        } else {
            modelEndpoints.push(endpointData);
        }

        renderEndpoints();
        markModified();
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
        return;
    }

    if (action === "delete") {
        if (pendingDeleteEndpointId === endpointId) {
            modelEndpoints = modelEndpoints.filter((item) => item.id !== endpointId);
            renderEndpoints();
            markModified();
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

    if (enabled) {
        setElementVisibility(migrationWarning, true);
        showToast("Multi-endpoint enabled. Existing AI endpoint will be migrated when you save settings.", "warning");
    }
    markModified();
}

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value || "";
    return div.innerHTML;
}

function init() {
    if (!enableMultiEndpointToggle) {
        return;
    }

    renderEndpoints();
    updateAuthVisibility();
    setElementVisibility(endpointsWrapper, enableMultiEndpointToggle.checked);
    setElementVisibility(defaultModelWrapper, enableMultiEndpointToggle.checked);

    enableMultiEndpointToggle.addEventListener("change", handleToggleChange);

    if (endpointAuthTypeSelect) {
        endpointAuthTypeSelect.addEventListener("change", updateAuthVisibility);
    }
    if (endpointProviderSelect) {
        endpointProviderSelect.addEventListener("change", updateAuthVisibility);
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

    updateHiddenInput();
    buildDefaultModelOptions();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
} else {
    init();
}
