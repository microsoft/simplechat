// model_routing_editor.js

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
    const modelFields = ["id", "modelName", "deploymentName", "api_type", "api_path", "url_mode", "api_version", "anthropic_version"];
    const payload = {
        id: endpoint.id || "", routing_schema_version: 2, preview_only: true,
        provider: endpoint.provider, connection: endpoint.connection,
        model: Object.fromEntries(modelFields.filter((field) => model[field] !== undefined).map((field) => [field, model[field]]))
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

export function createModelRoutingEditor(model, { endpoint, registry, requestInput, requestLabel }) {
    const editor = document.createElement("div");
    editor.className = "row g-2 mt-2";
    editor.dataset.modelRoutingEditor = "true";
    const custom = endpoint.provider === "custom";
    const controls = {};
    const idPrefix = `routing-${++nextEditorId}`;
    let explicitChoice = Boolean(model.api_type || model.url_mode);
    let syncType = () => {};

    function addField(field, labelText, value, options) {
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
    const libraryInput = addField("catalogModelId", "Model Library", model.catalogModelId, libraryOptions);
    libraryInput.addEventListener("change", () => {
        const row = editor.closest("[data-model-row-id]");
        const catalogInput = row?.querySelector('[data-budget-field="catalogModelId"]');
        if (catalogInput) {
            catalogInput.value = libraryInput.value;
            catalogInput.dispatchEvent(new Event("input", { bubbles: true }));
        }
        const entry = library.find((item) => item.id === libraryInput.value);
        if (!entry) {
            return;
        }
        if (custom && !explicitChoice) {
            controls.api_type.value = entry.api_type;
            controls.url_mode.value = entry.url_mode;
            syncType();
        }
        if (custom && !requestInput.value.trim()) {
            requestInput.value = entry.id;
        }
        const displayInput = row?.querySelector("[data-display-name-for]");
        if (displayInput && !displayInput.value.trim()) {
            displayInput.value = entry.displayName;
        }
    });

    if (custom) {
        addField("api_type", "API Type", model.api_type || "openai", Object.values(registry));
        addField("url_mode", "URL Handling", model.url_mode || "auto", [
            { value: "auto", label: "Auto" }, { value: "exact", label: "Exact API base" }
        ]);
    }
    addField("api_path", "API Path", model.api_path);
    if (custom) {
        addField("api_version", "API Version", model.api_version);
        addField("anthropic_version", "Anthropic Version", model.anthropic_version);
        requestInput.id = `${idPrefix}-request-model`;
        requestLabel.htmlFor = requestInput.id;
        syncType = () => {
            const descriptor = registry[controls.api_type.value];
            requestLabel.textContent = descriptor?.usesModelName ? "Model Name" : "Deployment Name";
            for (const field of ["api_version", "anthropic_version"]) {
                const applicable = descriptor?.versionField === field;
                controls[field].parentElement.classList.toggle("d-none", !applicable);
                controls[field].required = applicable;
                if (applicable && !controls[field].value) {
                    controls[field].value = descriptor.defaultVersion || "";
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
    preview.className = "col-12";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-sm btn-outline-secondary";
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
    const apiType = value("api_type");
    if (apiType) {
        model.api_type = apiType;
        model.url_mode = value("url_mode");
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