// orchestrationPlannerModel.ts
// Chooses the orchestration planner model from the configured models instead of typed identifiers.
//
// The planner reads four settings together -- deployment, model id, endpoint id and provider --
// the same way `_resolve_planner_binding` in functions_orchestration_models.py does:
//
//   - A connection model is identified by its endpoint and model id. The deployment is left blank,
//     so the runtime derives the request model from the connection instead of trusting a copy of
//     it that could drift out of step.
//   - A classic deployment (single endpoint or APIM) is identified by its name alone.
//   - Four blank values mean "plan with the answer model", which is the default.
//
// A saved value that names no listed model is kept, not cleared: silently clearing it would
// switch planning to the answer model without anyone having chosen that.

import type { DefaultModelChoice } from './modelConnections';

export const PLANNER_MODEL_KEYS = {
    deployment: 'chat_orchestration_planner_deployment',
    modelId: 'chat_orchestration_planner_model_id',
    endpointId: 'chat_orchestration_planner_model_endpoint_id',
    provider: 'chat_orchestration_planner_model_provider',
} as const;

/** The option for four blank values: plan with whichever model answers. */
export const ANSWER_MODEL_VALUE = '';
/** The option standing for a saved value that is not in the current list. */
export const SAVED_VALUE = '__saved__';

export interface PlannerModelSelection {
    deployment: string;
    modelId: string;
    endpointId: string;
    provider: string;
}

export interface PlannerModelChoice {
    value: string;
    label: string;
    /** The connection a model belongs to; classic deployments have none. */
    group?: string;
    selection: PlannerModelSelection;
}

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

function record(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : {};
}

/** Models published by saved AI Connections, as listed for the default chat model. */
export function connectionPlannerChoices(choices: DefaultModelChoice[]): PlannerModelChoice[] {
    return choices
        .filter((choice) => choice.endpointId && choice.modelId)
        .map((choice) => ({
            value: `connection:${JSON.stringify([choice.endpointId, choice.modelId])}`,
            label: choice.deploymentName && choice.deploymentName !== choice.modelLabel
                ? `${choice.modelLabel} (${choice.deploymentName})`
                : choice.modelLabel,
            group: choice.connectionName,
            selection: {
                deployment: '', modelId: choice.modelId,
                endpointId: choice.endpointId, provider: choice.provider,
            },
        }));
}

/** Classic single-endpoint or APIM deployments, read from the admin settings being edited. */
export function classicPlannerChoices(read: (key: string) => unknown): PlannerModelChoice[] {
    const deployments: Array<{ deployment: string; modelName: string }> = [];
    if (read('enable_gpt_apim') === true) {
        for (const name of text(read('azure_apim_gpt_deployment')).split(',')) {
            if (name.trim()) {
                deployments.push({ deployment: name.trim(), modelName: '' });
            }
        }
    } else {
        const selected = record(read('gpt_model')).selected;
        for (const item of Array.isArray(selected) ? selected : []) {
            const model = record(item);
            const deployment = text(model.deploymentName);
            if (deployment) {
                deployments.push({ deployment, modelName: text(model.modelName) });
            }
        }
    }
    const unique = new Map<string, string>();
    for (const { deployment, modelName } of deployments) {
        if (!unique.has(deployment)) {
            unique.set(deployment, modelName);
        }
    }
    return [...unique].map(([deployment, modelName]) => ({
        value: `classic:${deployment}`,
        label: modelName && modelName !== deployment ? `${deployment} (${modelName})` : deployment,
        selection: { deployment, modelId: '', endpointId: '', provider: '' },
    }));
}

export function readPlannerSelection(read: (key: string) => unknown): PlannerModelSelection {
    return {
        deployment: text(read(PLANNER_MODEL_KEYS.deployment)),
        modelId: text(read(PLANNER_MODEL_KEYS.modelId)),
        endpointId: text(read(PLANNER_MODEL_KEYS.endpointId)),
        provider: text(read(PLANNER_MODEL_KEYS.provider)),
    };
}

/** The option that represents the saved selection. */
export function plannerSelectionValue(
    selection: PlannerModelSelection,
    choices: PlannerModelChoice[],
): string {
    const { deployment, modelId, endpointId, provider } = selection;
    if (!deployment && !modelId && !endpointId && !provider) {
        return ANSWER_MODEL_VALUE;
    }
    const match = choices.find(({ selection: choice }) => {
        if (endpointId || modelId) {
            return choice.endpointId === endpointId && Boolean(choice.modelId) && choice.modelId === modelId;
        }
        return !choice.endpointId && choice.deployment === deployment
            && (!provider || provider.toLowerCase() === 'aoai');
    });
    return match ? match.value : SAVED_VALUE;
}

/** How a saved selection that is not listed reads in the menu. */
export function describePlannerSelection(selection: PlannerModelSelection): string {
    if (selection.endpointId || selection.modelId) {
        const model = selection.modelId || selection.deployment || 'model';
        return selection.endpointId ? `${model} on ${selection.endpointId}` : model;
    }
    return selection.deployment || selection.provider || 'Saved planner model';
}

/** The four settings to write for an option, or null when the option changes nothing. */
export function plannerSelectionUpdates(
    value: string,
    choices: PlannerModelChoice[],
): Record<string, string> | null {
    if (value === SAVED_VALUE) {
        return null;
    }
    const selection = value === ANSWER_MODEL_VALUE
        ? { deployment: '', modelId: '', endpointId: '', provider: '' }
        : choices.find((choice) => choice.value === value)?.selection;
    if (!selection) {
        return null;
    }
    return {
        [PLANNER_MODEL_KEYS.deployment]: selection.deployment,
        [PLANNER_MODEL_KEYS.modelId]: selection.modelId,
        [PLANNER_MODEL_KEYS.endpointId]: selection.endpointId,
        [PLANNER_MODEL_KEYS.provider]: selection.provider,
    };
}
