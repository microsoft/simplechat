// workspace_model_endpoints.js

import { showToast } from "../chat/chat-toast.js";
import { getIconPayload, setIconPayload } from "../agents_common.js";

const enableMultiEndpointToggle = document.getElementById("enable_multi_model_endpoints");
const endpointsWrapper = document.getElementById("model-endpoints-wrapper");
const endpointsTbody = document.getElementById("model-endpoints-tbody");
const addEndpointBtn = document.getElementById("add-model-endpoint-btn");

const endpointModalEl = document.getElementById("modelEndpointModal");
const endpointModal = endpointModalEl && window.bootstrap ? bootstrap.Modal.getOrCreateInstance(endpointModalEl) : null;

const endpointIdInput = document.getElementById("model-endpoint-id");
const endpointNameInput = document.getElementById("model-endpoint-name");
const endpointProviderSelect = document.getElementById("model-endpoint-provider");
const endpointUrlInput = document.getElementById("model-endpoint-endpoint");
const endpointUrlLabel = document.getElementById("model-endpoint-endpoint-label");
const endpointUrlHelp = document.getElementById("model-endpoint-endpoint-help");
const endpointProjectGroup = document.getElementById("model-endpoint-project-group");
const endpointProjectInput = document.getElementById("model-endpoint-project-name");
const endpointProjectApiVersionGroup = document.getElementById("model-endpoint-project-api-version-group");
const endpointProjectApiVersionInput = document.getElementById("model-endpoint-project-api-version");
const endpointProjectApiVersionCustomInput = document.getElementById("model-endpoint-project-api-version-custom");
const endpointOpenAiApiVersionGroup = document.getElementById("model-endpoint-openai-api-version-group");
const endpointOpenAiApiVersionInput = document.getElementById("model-endpoint-openai-api-version");
const endpointOpenAiApiVersionCustomInput = document.getElementById("model-endpoint-openai-api-version-custom");
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

const scope = window.modelEndpointScope || "user";
const endpointsContainerId = scope === "group" ? "group-multi-endpoint-configuration" : "workspace-multi-endpoint-configuration";
const endpointsContainer = document.getElementById(endpointsContainerId);
const endpointsApi = scope === "group" ? "/api/group/model-endpoints" : "/api/user/model-endpoints";
const modelsFetchApi = scope === "group" ? "/api/group/models/fetch" : "/api/user/models/fetch";
const modelsTestApi = scope === "group" ? "/api/group/models/test-model" : "/api/user/models/test-model";

let workspaceEndpoints = Array.isArray(window.workspaceModelEndpoints) ? [...window.workspaceModelEndpoints] : [];
let modalModels = [];

const DEFAULT_AOAI_OPENAI_API_VERSION = "2024-05-01-preview";
const DEFAULT_FOUNDRY_OPENAI_API_VERSION = "v1";
const DEFAULT_FOUNDRY_PROJECT_API_VERSION = "v1";
const CUSTOM_VERSION_VALUE = "custom";
const MODEL_ICON_CLASS_PATTERN = /^bi-[a-z0-9][a-z0-9-]{0,80}$/;
const MODEL_ICON_CONTROL_CONFIG = Object.freeze({
    editor: ".model-icon-editor",
    mode: ".model-icon-mode",
    classInput: ".model-icon-class",
    imageData: ".model-icon-image-data",
    preview: ".model-icon-preview",
    typeBootstrap: ".model-icon-type-bootstrap",
    typeImage: ".model-icon-type-image",
    bootstrapControls: ".model-bootstrap-icon-controls",
    imageControls: ".model-image-icon-controls",
    pickerButton: ".model-icon-picker-button",
    pickerLabel: ".model-icon-picker-label",
    pickerSearch: ".model-icon-picker-search",
    pickerList: ".model-icon-picker-list",
    imageFile: ".model-icon-image-file",
    imageClear: ".model-icon-image-clear",
    defaultBootstrapIcon: "bi-stars"
});

function hasEndpointManagementUi() {
    return Boolean(endpointsWrapper && endpointsTbody);
}

function hideEndpointManagementUi() {
    if (endpointsContainer) {
        endpointsContainer.classList.add("d-none");
    }
}

function isEndpointsFeatureDisabled(error) {
    const message = typeof error?.message === "string" ? error.message.toLowerCase() : "";
    return message.includes("custom endpoints") && message.includes("is disabled");
}

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

function isFoundryProvider(provider) {
    return provider === "aifoundry" || provider === "new_foundry";
}

function endpointIncludesProject(endpoint) {
    return String(endpoint || "").toLowerCase().includes("/api/projects/");
}

function getProjectNameFromEndpoint(endpoint) {
    const endpointValue = String(endpoint || "").trim();
    if (!endpointValue) {
        return "";
    }

    try {
        const parsedUrl = new URL(endpointValue);
        const segments = parsedUrl.pathname.split("/").filter(Boolean);
        const projectsIndex = segments.findIndex((segment) => segment.toLowerCase() === "projects");
        if (projectsIndex >= 0 && segments[projectsIndex + 1]) {
            return decodeURIComponent(segments[projectsIndex + 1]);
        }
    } catch (error) {
        const marker = "/api/projects/";
        const lowerEndpoint = endpointValue.toLowerCase();
        const markerIndex = lowerEndpoint.indexOf(marker);
        if (markerIndex >= 0) {
            return endpointValue.slice(markerIndex + marker.length).split(/[/?#]/)[0];
        }
    }

    return "";
}

function syncProjectNameFromEndpoint() {
    if (!endpointProjectInput || !endpointUrlInput) {
        return "";
    }

    const projectName = getProjectNameFromEndpoint(endpointUrlInput.value);
    if (projectName) {
        endpointProjectInput.value = projectName;
    }
    return projectName;
}

function syncEndpointCopyForProvider() {
    const provider = endpointProviderSelect?.value || "aoai";
    if (endpointUrlLabel) {
        endpointUrlLabel.textContent = isFoundryProvider(provider)
            ? "Project Endpoint"
            : "Endpoint Fully Qualified Domain Name (FQDN)";
    }
    if (endpointUrlHelp) {
        endpointUrlHelp.textContent = isFoundryProvider(provider)
            ? "Paste the Project endpoint from Azure AI Foundry. It can include /api/projects/<project>; Claude deployments are detected from the model name."
            : "For Azure OpenAI, paste the resource endpoint.";
    }
}

function syncVersionCustomVisibility() {
    setElementVisibility(
        endpointProjectApiVersionCustomInput,
        endpointProjectApiVersionInput?.value === CUSTOM_VERSION_VALUE
    );
    setElementVisibility(
        endpointOpenAiApiVersionCustomInput,
        endpointOpenAiApiVersionInput?.value === CUSTOM_VERSION_VALUE
    );
}

function getSelectedVersionValue(versionInput, customInput, fallbackValue = "") {
    const selectedValue = String(versionInput?.value || "").trim();
    if (selectedValue === CUSTOM_VERSION_VALUE) {
        return String(customInput?.value || "").trim();
    }
    return selectedValue || fallbackValue;
}

function setSelectedVersionValue(versionInput, customInput, value, fallbackValue = "") {
    if (!versionInput) {
        return;
    }

    const normalizedValue = String(value || fallbackValue || "").trim();
    const matchingOption = Array.from(versionInput.options || []).find((option) => option.value === normalizedValue);
    if (matchingOption && normalizedValue !== CUSTOM_VERSION_VALUE) {
        versionInput.value = normalizedValue;
        if (customInput) {
            customInput.value = "";
        }
    } else {
        versionInput.value = CUSTOM_VERSION_VALUE;
        if (customInput) {
            customInput.value = normalizedValue;
        }
    }

    syncVersionCustomVisibility();
}

function getDefaultOpenAiApiVersion(provider) {
    return provider === "new_foundry" ? DEFAULT_FOUNDRY_OPENAI_API_VERSION : DEFAULT_AOAI_OPENAI_API_VERSION;
}

function syncOpenAiApiVersionForProvider() {
    if (!endpointOpenAiApiVersionInput) {
        return;
    }

    const provider = endpointProviderSelect?.value || "aoai";
    const currentValue = getSelectedVersionValue(endpointOpenAiApiVersionInput, endpointOpenAiApiVersionCustomInput, "");
    if (provider === "new_foundry") {
        if (!currentValue || currentValue === DEFAULT_AOAI_OPENAI_API_VERSION) {
            setSelectedVersionValue(
                endpointOpenAiApiVersionInput,
                endpointOpenAiApiVersionCustomInput,
                DEFAULT_FOUNDRY_OPENAI_API_VERSION
            );
        }
        return;
    }

    if (!currentValue) {
        setSelectedVersionValue(
            endpointOpenAiApiVersionInput,
            endpointOpenAiApiVersionCustomInput,
            getDefaultOpenAiApiVersion(provider)
        );
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

    if (!workspaceEndpoints.length) {
        endpointsTbody.innerHTML = `
            <tr>
                <td colspan="5" class="text-center text-muted py-3">No endpoints configured yet.</td>
            </tr>
        `;
        return;
    }

    workspaceEndpoints.forEach((endpoint) => {
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
}

function updateAuthVisibility() {
    const authType = endpointAuthTypeSelect?.value || "managed_identity";
    const provider = endpointProviderSelect?.value || "aoai";
    const isApiKey = authType === "api_key";
    const isFoundry = isFoundryProvider(provider);
    const projectNameFromEndpoint = syncProjectNameFromEndpoint();
    syncEndpointCopyForProvider();
    syncVersionCustomVisibility();
    setElementVisibility(endpointProjectGroup, isFoundry && !projectNameFromEndpoint);
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
    setSelectedVersionValue(
        endpointProjectApiVersionInput,
        endpointProjectApiVersionCustomInput,
        DEFAULT_FOUNDRY_PROJECT_API_VERSION
    );
    setSelectedVersionValue(
        endpointOpenAiApiVersionInput,
        endpointOpenAiApiVersionCustomInput,
        getDefaultOpenAiApiVersion("aoai")
    );
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
        setSelectedVersionValue(
            endpointProjectApiVersionInput,
            endpointProjectApiVersionCustomInput,
            endpoint.connection?.project_api_version || endpoint.connection?.api_version || DEFAULT_FOUNDRY_PROJECT_API_VERSION
        );
        setSelectedVersionValue(
            endpointOpenAiApiVersionInput,
            endpointOpenAiApiVersionCustomInput,
            endpoint.connection?.openai_api_version || endpoint.connection?.api_version || getDefaultOpenAiApiVersion(endpoint.provider || "aoai")
        );
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

function createElement(tagName, className = "") {
    const element = document.createElement(tagName);
    if (className) {
        element.className = className;
    }
    return element;
}

function createSmallLabel(text) {
    const label = createElement("label", "form-label small");
    label.textContent = text;
    return label;
}

function createModelTextInput(modelId, datasetKey, value, disabled = false) {
    const input = document.createElement("input");
    input.type = "text";
    input.className = "form-control form-control-sm";
    input.dataset[datasetKey] = modelId;
    input.value = value || "";
    input.disabled = disabled;
    return input;
}

function getModelIconDomId(modelId, suffix) {
    const safeModelId = String(modelId || "model").replace(/[^A-Za-z0-9_-]/g, "-");
    return `model-${safeModelId}-${suffix}`;
}

function normalizeModelBootstrapIcon(value) {
    const iconClass = String(value || "").replace(/^bi\s+/, "").trim();
    return MODEL_ICON_CLASS_PATTERN.test(iconClass) ? iconClass : "bi-stars";
}

function appendModelIconModeToggle(buttonGroup, modelId, mode, labelText) {
    const input = document.createElement("input");
    input.type = "radio";
    input.className = `btn-check model-icon-type-${mode}`;
    input.name = getModelIconDomId(modelId, "icon-type");
    input.id = getModelIconDomId(modelId, `icon-type-${mode}`);
    input.value = mode;
    input.autocomplete = "off";
    if (mode === "bootstrap") {
        input.checked = true;
    }

    const label = document.createElement("label");
    label.className = "btn btn-outline-secondary";
    label.htmlFor = input.id;
    label.textContent = labelText;

    buttonGroup.appendChild(input);
    buttonGroup.appendChild(label);
}

function createModelIconEditor(model, modelId) {
    const iconPayload = model.icon && typeof model.icon === "object" && !Array.isArray(model.icon)
        ? model.icon
        : {};
    const bootstrapIcon = normalizeModelBootstrapIcon(
        iconPayload.kind === "bootstrap" ? iconPayload.value : "bi-stars"
    );
    const editor = createElement("div", "agent-icon-editor model-icon-editor border rounded p-2");
    editor.dataset.modelEditorFor = modelId;

    const modeInput = document.createElement("input");
    modeInput.type = "hidden";
    modeInput.className = "model-icon-mode";
    modeInput.value = "bootstrap";
    const classInput = document.createElement("input");
    classInput.type = "hidden";
    classInput.className = "model-icon-class";
    classInput.setAttribute("data-icon-class-for", modelId);
    classInput.value = bootstrapIcon;
    const imageDataInput = document.createElement("input");
    imageDataInput.type = "hidden";
    imageDataInput.className = "model-icon-image-data";
    imageDataInput.value = iconPayload.kind === "image" ? iconPayload.value || "" : "";

    const topRow = createElement("div", "d-flex align-items-center gap-2 mb-2");
    const preview = createElement("div", "agent-icon-preview model-icon-preview");
    preview.setAttribute("aria-hidden", "true");
    const buttonGroup = createElement("div", "btn-group btn-group-sm");
    buttonGroup.setAttribute("role", "group");
    buttonGroup.setAttribute("aria-label", "Model icon type");
    appendModelIconModeToggle(buttonGroup, modelId, "bootstrap", "Bootstrap Icon");
    appendModelIconModeToggle(buttonGroup, modelId, "image", "Image");
    topRow.appendChild(preview);
    topRow.appendChild(buttonGroup);

    const bootstrapControls = createElement("div", "model-bootstrap-icon-controls");
    const dropdown = createElement("div", "dropdown agent-icon-picker-dropdown");
    const pickerButton = document.createElement("button");
    pickerButton.type = "button";
    pickerButton.className = "btn btn-outline-secondary btn-sm dropdown-toggle w-100 text-start model-icon-picker-button";
    pickerButton.setAttribute("data-bs-toggle", "dropdown");
    pickerButton.setAttribute("data-bs-auto-close", "outside");
    pickerButton.setAttribute("aria-expanded", "false");
    const pickerButtonIcon = document.createElement("i");
    pickerButtonIcon.className = `bi ${bootstrapIcon} me-1`;
    pickerButtonIcon.setAttribute("aria-hidden", "true");
    const pickerLabel = createElement("span", "model-icon-picker-label");
    pickerLabel.textContent = bootstrapIcon;
    pickerButton.appendChild(pickerButtonIcon);
    pickerButton.appendChild(pickerLabel);

    const menu = createElement("div", "dropdown-menu p-2 agent-icon-picker-menu");
    const search = document.createElement("input");
    search.type = "search";
    search.className = "form-control form-control-sm mb-2 model-icon-picker-search";
    search.placeholder = "Search icons";
    search.autocomplete = "off";
    const list = createElement("div", "agent-icon-picker-list model-icon-picker-list");
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", "Bootstrap icons");
    menu.appendChild(search);
    menu.appendChild(list);
    dropdown.appendChild(pickerButton);
    dropdown.appendChild(menu);
    bootstrapControls.appendChild(dropdown);

    const imageControls = createElement("div", "model-image-icon-controls d-none");
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.className = "form-control form-control-sm model-icon-image-file";
    fileInput.accept = ".png,.jpg,.jpeg,image/png,image/jpeg";
    const helpText = createElement("div", "form-text");
    helpText.textContent = "PNG or JPEG. The image is resized and saved with the model.";
    const clearButton = document.createElement("button");
    clearButton.type = "button";
    clearButton.className = "btn btn-outline-secondary btn-sm mt-2 model-icon-image-clear";
    clearButton.textContent = "Remove Image";
    imageControls.appendChild(fileInput);
    imageControls.appendChild(helpText);
    imageControls.appendChild(clearButton);

    editor.appendChild(modeInput);
    editor.appendChild(classInput);
    editor.appendChild(imageDataInput);
    editor.appendChild(topRow);
    editor.appendChild(bootstrapControls);
    editor.appendChild(imageControls);

    setIconPayload(
        editor,
        iconPayload.kind ? iconPayload : { kind: "bootstrap", value: bootstrapIcon },
        MODEL_ICON_CONTROL_CONFIG
    );
    return editor;
}

function findModelEditor(modelId) {
    return Array.from(modelsListEl?.querySelectorAll("[data-model-editor-for]") || [])
        .find((editor) => editor.dataset.modelEditorFor === String(modelId));
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
        const modelId = model.id || generateId();
        model.id = modelId;

        const checkWrapper = createElement("div", "form-check");
        const checkbox = document.createElement("input");
        checkbox.className = "form-check-input";
        checkbox.type = "checkbox";
        checkbox.dataset.modelId = modelId;
        checkbox.checked = !!model.enabled;
        const checkboxLabel = createElement("label", "form-check-label fw-semibold");
        checkboxLabel.textContent = displayName;
        checkWrapper.appendChild(checkbox);
        checkWrapper.appendChild(checkboxLabel);

        const fieldsRow = createElement("div", "row g-2 mt-2");
        const deploymentCol = createElement("div", "col-md-4");
        deploymentCol.appendChild(createSmallLabel("Deployment"));
        deploymentCol.appendChild(createModelTextInput(modelId, "deploymentNameFor", deploymentName));
        const displayCol = createElement("div", "col-md-4");
        displayCol.appendChild(createSmallLabel("Display Name"));
        displayCol.appendChild(createModelTextInput(modelId, "displayNameFor", displayName));
        const modelNameCol = createElement("div", "col-md-4");
        modelNameCol.appendChild(createSmallLabel("Model Name"));
        const modelNameInput = createModelTextInput(modelId, "modelNameFor", modelName, true);
        modelNameCol.appendChild(modelNameInput);
        fieldsRow.appendChild(deploymentCol);
        fieldsRow.appendChild(displayCol);
        fieldsRow.appendChild(modelNameCol);

        const descriptionWrapper = createElement("div", "mt-2");
        descriptionWrapper.appendChild(createSmallLabel("Description"));
        const descriptionInput = document.createElement("textarea");
        descriptionInput.className = "form-control form-control-sm";
        descriptionInput.rows = 2;
        descriptionInput.dataset.descriptionFor = modelId;
        descriptionInput.value = description;
        descriptionWrapper.appendChild(descriptionInput);

        const iconWrapper = createElement("div", "mt-2");
        iconWrapper.appendChild(createSmallLabel("Icon"));
        iconWrapper.appendChild(createModelIconEditor(model, modelId));

        wrapper.appendChild(checkWrapper);
        wrapper.appendChild(fieldsRow);
        wrapper.appendChild(descriptionWrapper);
        wrapper.appendChild(iconWrapper);

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
        const descriptionInput = modelsListEl.querySelector(`textarea[data-description-for="${model.id}"]`);
        const iconEditor = findModelEditor(model.id);
        model.enabled = checkbox ? checkbox.checked : model.enabled;
        model.deploymentName = deploymentInput ? deploymentInput.value.trim() : model.deploymentName;
        model.displayName = displayInput ? displayInput.value.trim() : model.displayName;
        model.icon = iconEditor ? getIconPayload(iconEditor, MODEL_ICON_CONTROL_CONFIG) : model.icon || {};
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
        const response = await fetch(modelsTestApi, {
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
        const response = await fetch(modelsFetchApi, {
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
    const provider = endpointProviderSelect?.value || "aoai";
    const projectNameFromEndpoint = isFoundryProvider(provider) ? syncProjectNameFromEndpoint() : "";
    const projectName = projectNameFromEndpoint || endpointProjectInput?.value.trim() || "";
    const projectApiVersion = getSelectedVersionValue(
        endpointProjectApiVersionInput,
        endpointProjectApiVersionCustomInput,
        DEFAULT_FOUNDRY_PROJECT_API_VERSION
    );
    const openAiApiVersion = getSelectedVersionValue(
        endpointOpenAiApiVersionInput,
        endpointOpenAiApiVersionCustomInput,
        getDefaultOpenAiApiVersion(provider)
    );
    const subscriptionId = endpointSubscriptionInput?.value.trim() || "";
    const resourceGroup = endpointResourceGroupInput?.value.trim() || "";
    const authType = endpointAuthTypeSelect?.value || "managed_identity";
    const existingEndpoint = workspaceEndpoints.find((savedEndpoint) => savedEndpoint.id === endpointId);

    if (!name || !endpoint || !openAiApiVersion) {
        showToast("Endpoint name, URL, and OpenAI API version are required.", "warning");
        return null;
    }

    if (isFoundryProvider(provider) && !projectApiVersion) {
        showToast("Project API version is required for Foundry project discovery.", "warning");
        return null;
    }

    if (isFoundryProvider(provider) && !endpointIncludesProject(endpoint) && !projectName) {
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

    const hasStoredApiKey = authType === "api_key" && Boolean(existingEndpoint?.has_api_key);
    const hasStoredClientSecret = authType === "service_principal" && Boolean(existingEndpoint?.has_client_secret);

    if (authType === "service_principal" && (!auth.tenant_id || !auth.client_id || (!auth.client_secret && !hasStoredClientSecret))) {
        showToast("Tenant ID, Client ID, and Client Secret are required for service principal auth.", "warning");
        return null;
    }

    if (isFoundryProvider(provider) && authType === "service_principal" && auth.management_cloud === "custom") {
        if (!auth.custom_authority) {
            showToast("Custom authority is required when Management Cloud is set to Custom.", "warning");
            return null;
        }
        if (!auth.foundry_scope) {
            showToast("Foundry scope is required when Management Cloud is set to Custom.", "warning");
            return null;
        }
    }

    if (authType === "api_key" && !auth.api_key && !hasStoredApiKey) {
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

    if (isFoundryProvider(provider)) {
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
        const existingEndpoint = workspaceEndpoints.find((endpoint) => endpoint.id === endpointId);
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

        const existingIndex = workspaceEndpoints.findIndex((endpoint) => endpoint.id === endpointId);
        if (existingIndex >= 0) {
            workspaceEndpoints[existingIndex] = endpointData;
        } else {
            workspaceEndpoints.push(endpointData);
        }

        persistEndpoints();
        renderEndpoints();
        endpointModal.hide();
        showToast("Endpoint saved successfully.", "success");
    } catch (error) {
        console.error("Error saving endpoint", error);
        showToast(error.message || "Failed to save endpoint.", "danger");
    }
}

function persistEndpoints() {
    fetch(endpointsApi, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoints: workspaceEndpoints })
    }).catch((error) => {
        console.error("Failed to save endpoints", error);
        showToast("Failed to save endpoints.", "danger");
    });
}

function toggleEndpoint(endpointId) {
    const endpoint = workspaceEndpoints.find((item) => item.id === endpointId);
    if (!endpoint) {
        return;
    }
    endpoint.enabled = !endpoint.enabled;
    persistEndpoints();
    renderEndpoints();
}

function deleteEndpoint(endpointId) {
    workspaceEndpoints = workspaceEndpoints.filter((item) => item.id !== endpointId);
    persistEndpoints();
    renderEndpoints();
}

function handleTableClick(event) {
    const target = event.target.closest("button[data-action]");
    if (!target) {
        return;
    }
    const action = target.dataset.action;
    const endpointId = target.dataset.endpointId;
    if (!endpointId) {
        return;
    }

    if (action === "edit") {
        const endpoint = workspaceEndpoints.find((item) => item.id === endpointId);
        openModalForEndpoint(endpoint);
        return;
    }
    if (action === "toggle") {
        toggleEndpoint(endpointId);
        return;
    }
    if (action === "delete") {
        deleteEndpoint(endpointId);
    }
}

function addManualModel() {
    modalModels = collectModalModels();
    modalModels.push({
        id: generateId(),
        deploymentName: "",
        modelName: "",
        displayName: "",
        icon: {},
        description: "",
        enabled: true
    });
    renderModalModels(modalModels);
}

function escapeHtml(value) {
    if (!value) return "";
    return value.replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    }[char] || char));
}

async function loadEndpoints() {
    if (!hasEndpointManagementUi()) {
        return;
    }

    try {
        const response = await fetch(endpointsApi);
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(payload.error || "Failed to load endpoints");
        }
        workspaceEndpoints = Array.isArray(payload.endpoints) ? payload.endpoints : [];
        renderEndpoints();
    } catch (error) {
        if (isEndpointsFeatureDisabled(error)) {
            console.info("[WorkspaceEndpoints] Endpoint management is disabled; skipping endpoint load.");
            workspaceEndpoints = [];
            renderEndpoints();
            hideEndpointManagementUi();
            return;
        }

        console.error("Failed to load endpoints", error);
        showToast(error.message || "Failed to load endpoints.", "danger");
    }
}

function initialize() {
    if (!hasEndpointManagementUi()) {
        return;
    }

    if (enableMultiEndpointToggle) {
        enableMultiEndpointToggle.checked = Boolean(window.enableMultiModelEndpoints);
    }
    if (endpointsWrapper) {
        endpointsWrapper.classList.toggle("d-none", !window.enableMultiModelEndpoints);
    }

    renderEndpoints();
    loadEndpoints();

    if (addEndpointBtn) {
        addEndpointBtn.addEventListener("click", () => openModalForEndpoint(null));
    }

    if (endpointsTbody) {
        endpointsTbody.addEventListener("click", handleTableClick);
    }

    if (endpointProviderSelect) {
        endpointProviderSelect.addEventListener("change", () => {
            updateAuthVisibility();
            syncOpenAiApiVersionForProvider();
        });
    }

    if (endpointUrlInput) {
        endpointUrlInput.addEventListener("input", updateAuthVisibility);
    }

    if (endpointProjectApiVersionInput) {
        endpointProjectApiVersionInput.addEventListener("change", syncVersionCustomVisibility);
    }

    if (endpointOpenAiApiVersionInput) {
        endpointOpenAiApiVersionInput.addEventListener("change", syncVersionCustomVisibility);
    }

    if (endpointAuthTypeSelect) {
        endpointAuthTypeSelect.addEventListener("change", updateAuthVisibility);
    }

    if (endpointManagementCloudSelect) {
        endpointManagementCloudSelect.addEventListener("change", updateAuthVisibility);
    }

    if (miTypeSelect) {
        miTypeSelect.addEventListener("change", updateAuthVisibility);
    }

    if (fetchBtn) {
        fetchBtn.addEventListener("click", fetchModels);
    }

    if (saveBtn) {
        saveBtn.addEventListener("click", saveEndpoint);
    }

    if (addModelBtn) {
        addModelBtn.addEventListener("click", addManualModel);
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
} else {
    initialize();
}
