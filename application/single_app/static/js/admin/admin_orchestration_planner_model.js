// admin_orchestration_planner_model.js
// Chooses the orchestration planner model on the classic Admin Settings page.
//
// The planner reads four settings together -- deployment, model id, endpoint id and provider --
// which used to be typed by hand. This builds one dropdown from the models already configured and
// writes the four hidden form fields the page submits, so the settings route is unchanged. It
// follows the same rules as application/v2_ui/src/lib/orchestrationPlannerModel.ts:
//
//   - a connection model is saved as its endpoint, model id and provider, with the deployment left
//     blank so the runtime derives the request model from the connection;
//   - a classic deployment (single endpoint or APIM) is saved by name alone;
//   - four blank values plan with the answer model, which is the default;
//   - a saved value that names no listed model is kept and shown, never silently cleared.

export const ANSWER_MODEL_VALUE = "";
export const SAVED_VALUE = "__saved__";
export const PLANNER_FIELD_IDS = {
    deployment: "chat_orchestration_planner_deployment",
    modelId: "chat_orchestration_planner_model_id",
    endpointId: "chat_orchestration_planner_model_endpoint_id",
    provider: "chat_orchestration_planner_model_provider",
};

const EMPTY_SELECTION = { deployment: "", modelId: "", endpointId: "", provider: "" };

function text(value) {
    return typeof value === "string" ? value.trim() : "";
}

/** Chat models published by enabled AI Connections, as the default chat model lists them. */
export function connectionChoices(endpoints, publishesChat) {
    const choices = [];
    (Array.isArray(endpoints) ? endpoints : []).forEach((endpoint) => {
        const endpointId = text(endpoint?.id);
        if (!endpointId || endpoint.enabled === false || endpoint.provider === "openai_compatible") {
            return;
        }
        (Array.isArray(endpoint.models) ? endpoint.models : []).forEach((model) => {
            const modelId = text(model?.id) || text(model?.deploymentName);
            if (!modelId || !publishesChat(model)) {
                return;
            }
            choices.push({
                value: `connection:${JSON.stringify([endpointId, modelId])}`,
                label: text(model.displayName) || text(model.deploymentName) || text(model.modelName) || modelId,
                group: text(endpoint.name) || text(endpoint.connection?.endpoint) || "Connection",
                selection: {
                    deployment: "", modelId, endpointId, provider: text(endpoint.provider) || "aoai",
                },
            });
        });
    });
    return choices;
}

/** Classic single-endpoint or APIM deployments. */
export function classicChoices({ apimEnabled, apimDeployments, legacyModels }) {
    const deployments = new Map();
    if (apimEnabled) {
        String(apimDeployments || "").split(",").map((name) => name.trim()).filter(Boolean)
            .forEach((name) => {
                if (!deployments.has(name)) {
                    deployments.set(name, "");
                }
            });
    } else {
        (Array.isArray(legacyModels) ? legacyModels : []).forEach((model) => {
            const deployment = text(model?.deploymentName);
            if (deployment && !deployments.has(deployment)) {
                deployments.set(deployment, text(model.modelName));
            }
        });
    }
    return [...deployments].map(([deployment, modelName]) => ({
        value: `classic:${deployment}`,
        label: modelName && modelName !== deployment ? `${deployment} (${modelName})` : deployment,
        selection: { ...EMPTY_SELECTION, deployment },
    }));
}

export function readSelection(inputs) {
    return {
        deployment: text(inputs.deployment.value),
        modelId: text(inputs.modelId.value),
        endpointId: text(inputs.endpointId.value),
        provider: text(inputs.provider.value),
    };
}

/** The option that represents a selection. */
export function selectionValue(selection, choices) {
    const { deployment, modelId, endpointId, provider } = selection;
    if (!deployment && !modelId && !endpointId && !provider) {
        return ANSWER_MODEL_VALUE;
    }
    const match = choices.find(({ selection: choice }) => {
        if (endpointId || modelId) {
            return choice.endpointId === endpointId && Boolean(choice.modelId) && choice.modelId === modelId;
        }
        return !choice.endpointId && choice.deployment === deployment
            && (!provider || provider.toLowerCase() === "aoai");
    });
    return match ? match.value : SAVED_VALUE;
}

export function describeSelection(selection) {
    if (selection.endpointId || selection.modelId) {
        const model = selection.modelId || selection.deployment || "model";
        return selection.endpointId ? `${model} on ${selection.endpointId}` : model;
    }
    return selection.deployment || selection.provider || "Saved planner model";
}

/** The selection an option stands for, or null when choosing it changes nothing. */
export function selectionForValue(value, choices) {
    if (value === SAVED_VALUE) {
        return null;
    }
    if (value === ANSWER_MODEL_VALUE) {
        return { ...EMPTY_SELECTION };
    }
    const choice = choices.find((item) => item.value === value);
    return choice ? { ...choice.selection } : null;
}

/** Rebuild the dropdown for the current choices. Labels are set as text, never markup. */
export function renderPlannerModelSelect(select, choices, selection, savedNote) {
    const value = selectionValue(selection, choices);
    select.replaceChildren(new Option("Use the answer model (default)", ANSWER_MODEL_VALUE));
    if (value === SAVED_VALUE) {
        select.appendChild(new Option(
            `${describeSelection(selection)} — not in the current model list`, SAVED_VALUE,
        ));
    }
    const groups = new Map();
    choices.forEach((choice) => {
        const group = choice.group || "";
        if (!groups.has(group)) {
            groups.set(group, []);
        }
        groups.get(group).push(choice);
    });
    groups.forEach((items, group) => {
        let parent = select;
        if (group) {
            parent = document.createElement("optgroup");
            parent.label = group;
            select.appendChild(parent);
        }
        items.forEach((choice) => parent.appendChild(new Option(choice.label, choice.value)));
    });
    select.value = value;
    if (savedNote) {
        savedNote.classList.toggle("d-none", value !== SAVED_VALUE);
    }
    return value;
}

/**
 * Wire the pane's dropdown to its four hidden inputs.
 *
 * `getChoices()` is asked for the current models on every refresh, so connections added or
 * removed on the same page, or the classic deployment list, are reflected before saving.
 * Returns `{ refresh }`, or null when the pane is not on the page.
 */
export function mountPlannerModelPicker({ getChoices, onChange, root = document }) {
    const select = root.getElementById("chat_orchestration_planner_model");
    const savedNote = root.getElementById("chat-orchestration-planner-model-saved-note");
    const inputs = Object.fromEntries(
        Object.entries(PLANNER_FIELD_IDS).map(([name, id]) => [name, root.getElementById(id)]),
    );
    if (!select || Object.values(inputs).some((input) => !input)) {
        return null;
    }
    let choices = [];
    const refresh = () => {
        choices = getChoices();
        renderPlannerModelSelect(select, choices, readSelection(inputs), savedNote);
    };
    select.addEventListener("change", () => {
        const selection = selectionForValue(select.value, choices);
        if (!selection) {
            return;
        }
        Object.entries(selection).forEach(([name, value]) => {
            inputs[name].value = value;
        });
        renderPlannerModelSelect(select, choices, selection, savedNote);
        if (typeof onChange === "function") {
            onChange(selection);
        }
    });
    refresh();
    return { refresh };
}
