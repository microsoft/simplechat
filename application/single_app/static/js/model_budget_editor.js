// model_budget_editor.js

const capacityFields = Object.freeze([
    {
        key: "contextWindow",
        label: "Context Window (tokens)",
        help: "Verified shared total for input and generation together."
    },
    {
        key: "inputTokenLimit",
        label: "Input Token Limit (tokens)",
        help: "Verified independent input ceiling, not the shared context window."
    },
    {
        key: "outputTokenLimit",
        label: "Output Token Limit (tokens)",
        help: "Hard provider output ceiling, not the requested Response Length."
    }
]);
const identityFields = Object.freeze([
    {
        key: "catalogModelId",
        label: "Catalog Model ID",
        help: "Actual published model ID for this deployment, not its display name or arbitrary deployment alias."
    },
    {
        key: "modelVersion",
        label: "Model Version",
        help: "Exact deployed model version or snapshot, not the endpoint API version."
    }
]);
const providerOptions = Object.freeze([
    ["", "Auto / inherit"],
    ["azure", "Azure"],
    ["openai", "OpenAI"],
    ["anthropic", "Anthropic"],
    ["google", "Google"],
    ["vertex", "Vertex AI"],
    ["xai", "xAI"],
    ["publisher", "Publisher"],
    ["custom", "Custom"]
]);
const accountingOptions = Object.freeze([
    ["", "Inherit"],
    ["total_generation", "Total generation (including reasoning)"],
    ["visible_only", "Visible output only"],
    ["unknown", "Unknown"]
]);
const selectFields = Object.freeze([
    {
        key: "tokenLimitProvider",
        label: "Token Limit Provider",
        help: "Hosting provider whose documented limits apply. Auto inherits the selected endpoint/provider; it does not change the request route.",
        options: providerOptions
    },
    {
        key: "outputTokenAccounting",
        label: "Output Token Accounting",
        help: "Whether the output allowance includes reasoning and other generated tokens. Choose total generation only when verified for this provider and API; visible-only or unknown may not provide a safe generation budget.",
        options: accountingOptions
    }
]);

export class ModelBudgetValidationError extends Error {
    constructor(message) {
        super(message);
        this.name = "ModelBudgetValidationError";
    }
}

export function normalizeTokenCapacity(value, label = "Token capacity") {
    if (value === null || value === undefined) {
        return null;
    }
    if (typeof value === "string") {
        const text = value.trim();
        if (!text) {
            return null;
        }
        if (/^[0-9]+$/.test(text)) {
            const parsed = Number(text);
            if (Number.isSafeInteger(parsed) && parsed > 0) {
                return parsed;
            }
        }
    } else if (typeof value === "number" && Number.isSafeInteger(value) && value > 0) {
        return value;
    }
    throw new ModelBudgetValidationError(
        `${label} must be a positive whole number no greater than 9007199254740991, or blank to inherit.`
    );
}

function normalizeBudgetText(value, field) {
    const text = value.trim();
    if (!text) {
        return null;
    }
    if (text.length > 256 || /[\u0000-\u001f]/.test(text)) {
        throw new ModelBudgetValidationError(`${field.label} must be at most 256 characters without control characters.`);
    }
    if (field.options && !field.options.some(([option]) => option === text)) {
        throw new ModelBudgetValidationError(`Choose a supported ${field.label.toLowerCase()}.`);
    }
    return text;
}

function clearFieldError(control, feedback) {
    control.setCustomValidity("");
    control.classList.remove("is-invalid");
    control.removeAttribute("aria-invalid");
    feedback.textContent = "";
}

function createBudgetField(field, record, idPrefix, isCapacity) {
    const column = document.createElement("div");
    column.className = isCapacity ? "col-12 col-md-4" : "col-12 col-md-6";
    const label = document.createElement("label");
    label.className = "form-label small";
    label.textContent = field.label;

    const control = document.createElement(field.options ? "select" : "input");
    control.className = field.options ? "form-select form-select-sm" : "form-control form-control-sm";
    control.id = `${idPrefix}-${field.key}`;
    control.dataset.budgetField = field.key;
    label.htmlFor = control.id;
    const value = record[field.key] === null || record[field.key] === undefined ? "" : String(record[field.key]);
    if (field.options) {
        field.options.forEach(([optionValue, optionLabel]) => {
            const option = document.createElement("option");
            option.value = optionValue;
            option.textContent = optionLabel;
            control.appendChild(option);
        });
        if (value && !field.options.some(([option]) => option === value.trim())) {
            const unknownOption = document.createElement("option");
            unknownOption.value = value.trim();
            unknownOption.textContent = "Invalid saved value - choose a supported option";
            control.appendChild(unknownOption);
        }
        control.value = value.trim();
    } else {
        // Number inputs accept exponential notation and can erase malformed text.
        control.type = "text";
        control.inputMode = isCapacity ? "numeric" : "text";
        control.autocomplete = "off";
        control.placeholder = "Inherit";
        if (isCapacity) {
            control.pattern = "[0-9]*";
        } else {
            control.maxLength = 256;
        }
        control.value = value;
    }

    const help = document.createElement("div");
    help.className = "form-text";
    help.id = `${control.id}-help`;
    help.textContent = field.help;
    const feedback = document.createElement("div");
    feedback.className = "invalid-feedback";
    feedback.id = `${control.id}-error`;
    feedback.dataset.budgetErrorFor = field.key;
    feedback.setAttribute("role", "alert");
    control.setAttribute("aria-describedby", `${help.id} ${feedback.id}`);
    control.addEventListener("input", () => clearFieldError(control, feedback));
    control.addEventListener("change", () => clearFieldError(control, feedback));
    column.append(label, control, help, feedback);
    return column;
}

export function createModelBudgetEditor(record = {}, { scope = "model", idPrefix = "model-budget" } = {}) {
    const editor = document.createElement("details");
    editor.className = "border rounded p-3 mt-3";
    editor.dataset.modelBudgetEditor = scope;
    editor.dataset.testid = `${scope}-budget-editor`;

    const summary = document.createElement("summary");
    summary.className = "fw-semibold";
    summary.textContent = scope === "endpoint" ? "Advanced endpoint capacity" : "Advanced model capacity";
    const description = document.createElement("p");
    description.className = "small text-muted mt-2 mb-2";
    description.textContent = scope === "endpoint"
        ? "Defaults for models on this endpoint. Blank values inherit the exact catalog model's limits; a model override takes precedence. Only enter verified specifications for the deployed provider and version."
        : "Each blank value inherits independently: model override -> endpoint override -> exact catalog model. Use verified deployment specifications, not a guessed capacity based on a deployment name.";
    const allowanceHelp = document.createElement("p");
    allowanceHelp.className = "small text-muted mb-3";
    allowanceHelp.textContent = "Response Length is a per-request generation allowance, not model capacity. Independent input and output maxima do not have to fit simultaneously within the context window.";
    const row = document.createElement("div");
    row.className = "row g-3";
    if (scope === "model") {
        identityFields.forEach((field) => row.appendChild(createBudgetField(field, record, idPrefix, false)));
    }
    capacityFields.forEach((field) => row.appendChild(createBudgetField(field, record, idPrefix, true)));
    selectFields.forEach((field) => row.appendChild(createBudgetField(field, record, idPrefix, false)));
    editor.append(summary, description, allowanceHelp, row);
    return editor;
}

export function collectModelBudgetOverrides(editor, record = {}) {
    const overrides = {};
    if (!editor) {
        return overrides;
    }
    const fields = [...capacityFields, ...identityFields, ...selectFields];
    for (const control of editor.querySelectorAll("[data-budget-field]")) {
        const field = fields.find((candidate) => candidate.key === control.dataset.budgetField);
        if (!field) {
            continue;
        }
        const feedback = document.getElementById(`${control.id}-error`);
        clearFieldError(control, feedback);
        try {
            const value = capacityFields.includes(field)
                ? normalizeTokenCapacity(control.value, field.label)
                : normalizeBudgetText(control.value, field);
            if (value !== null || Object.prototype.hasOwnProperty.call(record, field.key)) {
                overrides[field.key] = value;
            }
        } catch (error) {
            if (!(error instanceof ModelBudgetValidationError)) {
                throw error;
            }
            editor.open = true;
            control.setCustomValidity(error.message);
            control.classList.add("is-invalid");
            control.setAttribute("aria-invalid", "true");
            feedback.textContent = error.message;
            control.focus();
            throw error;
        }
    }
    return overrides;
}
