// orchestrationModelRouting.ts
// Which model an orchestrated request uses: Auto, a model chosen for each step, or one pinned model.
//
// The choice is remembered on the account, the same way the approval mode is, so it survives
// leaving the chat, a reload, and another device. It is deliberately separate from the ordinary
// chat model: pinning a model for orchestration does not change what a normal chat uses, and
// normal chat never sends Auto, because only orchestration can choose a model per step.

import { findModel, type ModelCatalogEntry } from './models';

/** The picker value for Auto. Never sent as a deployment. */
export const AUTO_MODEL_VALUE = '__auto__';

export type OrchestrationModelRouting = 'auto' | 'manual';

export function isOrchestrationModelRouting(value: unknown): value is OrchestrationModelRouting {
    return value === 'auto' || value === 'manual';
}

/** The ratings that count as evidence a model can do the work, as the server ranks them. */
const POSITIVE_RATINGS = new Set(['suitable', 'strong']);

/**
 * Whether Auto can route an orchestrated request with the models in the catalog.
 *
 * Mirrors the server's `authorized_routing_candidates` -- an unarchived catalog profile, text
 * generation, and an API Auto supports -- and also requires a model rated for general
 * answering. When no connected model is rated for a step's task, the server uses the model
 * best rated for general answering, so such a model is what lets every step be routed.
 * Offering Auto without one would make orchestrated requests fail when they are planned.
 */
export function autoRoutingAvailable(models: ModelCatalogEntry[] | undefined): boolean {
    return (models ?? []).some((model) => {
        const profile = model.profile as
            | { archived?: unknown; tasks?: Record<string, unknown> | null }
            | null
            | undefined;
        const capabilities = model.capabilities as { generatesText?: unknown } | null | undefined;
        return Boolean(profile) && !profile?.archived
            && POSITIVE_RATINGS.has(String(profile?.tasks?.general ?? ''))
            && capabilities?.generatesText === true
            && model.auto_routing_available !== false;
    });
}

export interface OrchestrationModelInput {
    models: ModelCatalogEntry[] | undefined;
    /** Whether the administrator leaves the model picker reachable under Manual controls. */
    pickerReachable: boolean;
    /** `orchestrationModelRouting` as stored; anything but a valid value is ignored. */
    savedRouting: unknown;
    /** `orchestrationPreferredModelId` as stored, a catalog selection key. */
    savedModelId: unknown;
    /** The ordinary chat model, used when a specific model applies but none is pinned. */
    fallbackModel: string | undefined;
}

export interface OrchestrationModelChoice {
    routing: OrchestrationModelRouting;
    /** The model a pinned request sends; undefined under Auto. */
    model: string | undefined;
    /** Whether Auto may be offered at all. */
    autoAvailable: boolean;
}

/**
 * Resolve the model an orchestrated request uses.
 *
 * Auto is the default wherever it can work. Only a saved pin that still names a model in the
 * catalog changes that. A pin whose model is gone falls back to the default rather than to the
 * normal chat model, because the explicit choice no longer exists. When the administrator hides
 * Manual controls, saved pins are ignored: a model the user can neither see nor change must not
 * quietly decide their requests.
 */
export function resolveOrchestrationModel(input: OrchestrationModelInput): OrchestrationModelChoice {
    const autoAvailable = autoRoutingAvailable(input.models);
    const defaultChoice: OrchestrationModelChoice = autoAvailable
        ? { routing: 'auto', model: undefined, autoAvailable }
        : { routing: 'manual', model: input.fallbackModel, autoAvailable };
    if (!input.pickerReachable || input.savedRouting !== 'manual') {
        return defaultChoice;
    }
    const pinned = typeof input.savedModelId === 'string' ? input.savedModelId.trim() : '';
    if (pinned && findModel(input.models, pinned)) {
        return { routing: 'manual', model: pinned, autoAvailable };
    }
    return defaultChoice;
}

/** The picker value for a resolved choice. */
export function orchestrationModelValue(choice: OrchestrationModelChoice): string | undefined {
    return choice.routing === 'auto' ? AUTO_MODEL_VALUE : choice.model;
}

/** The preference update for a picker value. Choosing Auto keeps the last pin for next time. */
export function orchestrationModelUpdate(value: string): {
    orchestrationModelRouting: OrchestrationModelRouting;
    orchestrationPreferredModelId?: string;
} {
    return value === AUTO_MODEL_VALUE
        ? { orchestrationModelRouting: 'auto' }
        : { orchestrationModelRouting: 'manual', orchestrationPreferredModelId: value };
}
