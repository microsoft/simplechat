// model_routing_editor.js

import {
    clearModelBudgetPreviews, collectModelBudgetOverrides,
    projectModelBudgetMetadata, renderModelBudgetPreview
} from "./model_budget_editor.js";

let nextEditorId = 0;
const pendingPreviews = new WeakMap();
const validationRevisions = new WeakMap();

export class ModelRoutingValidationError extends Error {}

export function showModelRoutingError(error) {
    const alert = document.getElementById("model-endpoint-routing-error");
    alert.textContent = error.message;
    alert.classList.remove("d-none");
    alert.focus();
}

export function invalidateModelRoutingPreviews(container) {
    if (!container) {
        return;
    }
    validationRevisions.set(container, (validationRevisions.get(container) || 0) + 1);
    document.getElementById("model-endpoint-routing-error")?.classList.add("d-none");
    clearModelBudgetPreviews(container);
    for (const output of container.querySelectorAll('[data-testid="model-route-preview"]')) {
        pendingPreviews.delete(output);
        output.textContent = "";
    }
}

export async function previewModelRoute(endpoint, model, url, row) {
    const output = row?.querySelector('[data-testid="model-route-preview"]');
    const requestId = {};
    if (output) {
        pendingPreviews.set(output, requestId);
        output.textContent = "Resolving route...";
    }
    const modelFields = [
        "id", "modelName", "deploymentName", "api_type", "inference_api",
        "api_path", "api_path_order", "url_mode", "api_version",
        "anthropic_version", "responseLength"
    ];
    const payload = {
        id: endpoint.id || "", routing_schema_version: 2, preview_only: true,
        routing_path_order: endpoint.routing_path_order || "model_first",
        provider: endpoint.provider, connection: endpoint.connection,
        ...(endpoint.profile ? { profile: endpoint.profile } : {}),
        ...projectModelBudgetMetadata(endpoint),
        ...collectModelBudgetOverrides(
            document.getElementById("model-endpoint-budget-editor")?.querySelector("[data-model-budget-editor]"),
            endpoint
        ),
        model: {
            ...Object.fromEntries(modelFields.filter((field) => model[field] !== undefined).map((field) => [field, model[field]])),
            ...projectModelBudgetMetadata(model)
        }
    };
    try {
        const response = await fetch(url, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.preview_only !== true || !data.resolved?.operation_url) {
            throw new ModelRoutingValidationError(data.error || "Unable to preview this route.");
        }
        if (output && pendingPreviews.get(output) === requestId) {
            output.textContent = `${data.resolved.method} ${data.resolved.operation_url}`;
            renderModelBudgetPreview(row, data.budget);
        }
        return data.resolved;
    } catch (error) {
        const message = error instanceof ModelRoutingValidationError ? error.message : "Unable to preview this route.";
        if (output && pendingPreviews.get(output) === requestId) {
            output.textContent = message;
        }
        throw new ModelRoutingValidationError(message);
    }
}

export async function validateModelRoutes(endpoint, models, url, container) {
    if (endpoint.routing_schema_version !== 2) {
        return;
    }
    if (!models.length) {
        throw new ModelRoutingValidationError("Add at least one model before saving.");
    }
    const routes = new Set();
    const revision = validationRevisions.get(container);
    for (const model of models) {
        const row = Array.from(container.querySelectorAll("[data-model-row-id]")).find((item) => item.dataset.modelRowId === model.id);
        const route = await previewModelRoute(endpoint, model, url, row);
        if (validationRevisions.get(container) !== revision) {
            throw new ModelRoutingValidationError("The configuration changed during validation. Review it and save again.");
        }
        const key = JSON.stringify([route.request_model, route.operation_url]);
        if (routes.has(key)) {
            throw new ModelRoutingValidationError("Two models have the same request identifier and route.");
        }
        routes.add(key);
    }
}

export function createModelRoutingEditor(model, { endpoint, registry, requestInput, requestLabel, profile = "" }) {
    const editor = document.createElement("div");
    editor.className = "row g-2 mt-2";
    editor.dataset.modelRoutingEditor = "true";
    editor.dataset.apiPathOrder = endpoint.routing_path_order
        || model.api_path_order
        || "model_first";
    const custom = endpoint.provider === "custom";
    const controls = {};
    const idPrefix = `routing-${++nextEditorId}`;
    let explicitChoice = Boolean(model.api_type || model.url_mode);
    let syncType = () => {};

    function addField(field, labelText, value, options, helpText = "") {
        const column = document.createElement("div");
        column.className = "col-12 col-md-6";
        const label = document.createElement("label");
        label.className = "form-label small";
        const input = document.createElement(options ? "select" : "input");
        input.className = options ? "form-select form-select-sm" : "form-control form-control-sm";
        input.id = `${idPrefix}-${field}`;
        input.dataset.routingField = field;
        label.htmlFor = input.id;
        label.textContent = labelText;
        for (const option of options || []) {
            input.add(new Option(option.label, option.value));
        }
        input.value = value || "";
        column.append(label, input);
        if (helpText) {
            const help = document.createElement("div");
            help.className = "form-text";
            help.id = `${input.id}-help`;
            help.textContent = helpText;
            input.setAttribute("aria-describedby", help.id);
            column.append(help);
        }
        editor.append(column);
        controls[field] = input;
        return input;
    }

    let library = [];
    try {
        library = JSON.parse(document.getElementById("modelEndpointModal")?.dataset.modelLibrary || "[]");
    } catch {
        library = [];
    }
    const libraryOptions = [
        { value: "", label: "Manual entry" },
        ...library.map((entry) => ({ value: entry.id, label: `${entry.displayName} (${entry.publisher}, ${entry.lifecycle})` }))
    ];
    if (model.catalogModelId && !library.some((entry) => entry.id === model.catalogModelId)) {
        libraryOptions.push({ value: model.catalogModelId, label: model.catalogModelId });
    }
    const libraryInput = addField(
        "catalogModelId", "Model Library", model.catalogModelId, libraryOptions,
        "Optional catalog metadata for the published model and its limits. Manual entry remains available. This is not the required request identifier; enter an Azure deployment alias separately."
    );
    libraryInput.addEventListener("change", () => {
        const row = editor.closest("[data-model-row-id]");
        const entry = library.find((item) => item.id === libraryInput.value);
        if (!entry) {
            return;
        }
        if (custom && !explicitChoice) {
            controls.api_type.value = profile === "genai_mil" ? "openai" : entry.api_type;
            controls.url_mode.value = entry.url_mode;
            syncType();
        }
        if (custom && profile !== "genai_mil" && registry[controls.api_type.value]?.usesModelName && !requestInput.value.trim()) {
            requestInput.value = entry.id;
        }
        const displayInput = row?.querySelector("[data-display-name-for]");
        if (displayInput && !displayInput.value.trim()) {
            displayInput.value = entry.displayName;
        }
    });

    if (custom) {
        const options = profile === "genai_mil" ? [registry.openai] : Object.values(registry);
        if (profile === "genai_mil" && model.api_type && model.api_type !== "openai" && registry[model.api_type]) {
            options.push({ ...registry[model.api_type], label: `${registry[model.api_type].label} (not supported by GenAI.mil)` });
        }
        addField("api_type", "API Type", model.api_type || "openai", options);
        const selectedDescriptor = registry[model.api_type || "openai"];
        const inferenceApis = selectedDescriptor?.supportedInferenceApis
            || ["chat_completions"];
        if (inferenceApis.length > 1) {
            addField(
                "inference_api",
                "Chat API",
                model.inference_api || selectedDescriptor?.defaultInferenceApi
                    || "chat_completions",
                inferenceApis.map((value) => ({
                    value,
                    label: value === "responses"
                        ? "Responses"
                        : value === "messages"
                          ? "Messages"
                          : "Chat Completions",
                })),
                "Choose the operation this model implements. Saved models keep this choice even if connection defaults change."
            );
        }
        addField("url_mode", "URL Handling", model.url_mode || "auto", [
            { value: "auto", label: "Automatic (protocol default)" },
            { value: "api_base", label: "Use API base as entered" },
            { value: "full", label: "Use full request URL (advanced)" },
            { value: "exact", label: "Legacy exact API base (preserve saved route)" },
        ], "Automatic builds the supported API path. API base keeps the configured base and adds only the selected operation. Full request URL uses the exact operation path shown.");
    }
    addField(
        "api_path", "API Path", model.api_path, undefined,
        endpoint.routing_path_order === "connection_first"
            ? "Optional model-specific path appended after the shared connection path, such as team/inference."
            : "Legacy additional gateway prefix used before the saved connection path. Existing routes retain this position until reviewed."
    );
    if (custom) {
        addField("api_version", "API Version", model.api_version);
        addField("anthropic_version", "Anthropic Version", model.anthropic_version);
        requestInput.id = `${idPrefix}-request-model`;
        requestLabel.htmlFor = requestInput.id;
        const requestHelp = document.createElement("div");
        requestHelp.id = `${requestInput.id}-help`;
        requestHelp.className = "form-text";
        requestInput.setAttribute("aria-describedby", requestHelp.id);
        requestInput.parentElement.append(requestHelp);
        syncType = () => {
            const descriptor = registry[controls.api_type.value];
            editor.dataset.defaultInferenceApi =
                descriptor?.defaultInferenceApi || "chat_completions";
            requestLabel.textContent = descriptor?.usesModelName ? "Model Name" : "Deployment Name";
            requestHelp.textContent = descriptor?.usesModelName
                ? "Required: the exact model identifier accepted by this API. Catalog selection never replaces an identifier you entered."
                : "Required: your configured Azure deployment alias, not the publisher's catalog model ID.";
            for (const field of ["api_version", "anthropic_version"]) {
                const applicable = descriptor?.versionField === field;
                controls[field].parentElement.classList.toggle("d-none", !applicable);
                controls[field].required = applicable;
                if (applicable && !controls[field].value) {
                    controls[field].value = descriptor.defaultVersion || "";
                }
            }
            const inferenceControl = controls.inference_api;
            if (inferenceControl) {
                const supported = descriptor?.supportedInferenceApis
                    || ["chat_completions"];
                inferenceControl.replaceChildren(...supported.map((value) => new Option(
                    value === "responses"
                        ? "Responses"
                        : value === "messages"
                          ? "Messages"
                          : "Chat Completions",
                    value
                )));
                if (!supported.includes(inferenceControl.value)) {
                    inferenceControl.value =
                        descriptor?.defaultInferenceApi || supported[0];
                }
            }
            editor.dataset.identifierField = descriptor?.usesModelName ? "modelName" : "deploymentName";
        };
        controls.api_type.addEventListener("change", () => {
            explicitChoice = true;
            syncType();
        });
        controls.url_mode.addEventListener("change", () => { explicitChoice = true; });
        syncType();
    }
    const preview = document.createElement("div");
    preview.className = "col-12 border rounded p-2 mt-2";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-sm btn-outline-primary";
    button.dataset.action = "preview-route";
    button.dataset.modelId = model.id;
    const icon = document.createElement("i");
    icon.className = "bi bi-eye me-1";
    icon.setAttribute("aria-hidden", "true");
    button.append(icon, document.createTextNode("Preview Route"));
    const output = document.createElement("output");
    output.className = "d-block small text-break mt-2";
    output.dataset.testid = "model-route-preview";
    output.setAttribute("aria-live", "polite");
    output.setAttribute("aria-label", "Resolved request route preview");
    preview.append(button, output);
    editor.append(preview);
    return editor;
}

export function collectModelRouting(row, model) {
    const editor = row?.querySelector("[data-model-routing-editor]");
    if (!editor) {
        return;
    }
    const value = (field) => editor.querySelector(`[data-routing-field="${field}"]`)?.value.trim();
    model.api_path = value("api_path") || "";
    model.api_path_order = editor.dataset.apiPathOrder || "model_first";
    const catalogModelId = value("catalogModelId");
    if (catalogModelId || Object.prototype.hasOwnProperty.call(model, "catalogModelId")) {
        model.catalogModelId = catalogModelId || null;
    }
    const apiType = value("api_type");
    if (apiType) {
        model.api_type = apiType;
        model.url_mode = value("url_mode");
        model.inference_api = value("inference_api")
            || editor.dataset.defaultInferenceApi
            || "chat_completions";
        const requestModel = row.querySelector("input[data-request-model-for]")?.value.trim() || "";
        delete model.modelName;
        delete model.deploymentName;
        delete model.deployment;
        delete model.name;
        model[editor.dataset.identifierField] = requestModel;
        for (const field of ["api_version", "anthropic_version"]) {
            delete model[field];
            const input = editor.querySelector(`[data-routing-field="${field}"]`);
            if (input.required) {
                if (!input.value.trim()) {
                    throw new ModelRoutingValidationError("A version is required for this model's API type.");
                }
                model[field] = input.value.trim();
            }
        }
    }
}