// reasoning.ts
// Which reasoning effort levels a model accepts, and which one is in effect.
//
// Mirrors getModelSupportedLevels and getCurrentModelReasoningEffort in
// static/js/chat/chat-reasoning.js. Offering a level a model rejects produces a request the
// endpoint has to strip, and hiding a level a model does support silently removes a
// capability, so the mapping is kept in step with the existing client rather than guessed.
//
// The chosen level is stored per model in the `reasoningEffortSettings` user setting, which
// the classic interface already owns. Sharing the setting means sharing how a model is keyed
// in it, so both interfaces have to agree on the fallback order below.

export type ReasoningEffort = 'none' | 'minimal' | 'low' | 'medium' | 'high';

/**
 * The stored per-model map, `{ 'gpt-5-mini': 'medium' }`.
 *
 * Values are read back as plain strings because the map is shared with another client and
 * with whatever an older release wrote; an unrecognised level is discarded on resolution
 * rather than trusted.
 */
export type ReasoningEffortSettings = Record<string, string>;

export const ALL_REASONING_LEVELS: ReasoningEffort[] = [
    'none',
    'minimal',
    'low',
    'medium',
    'high',
];

export function getModelSupportedLevels(modelName?: string): ReasoningEffort[] {
    if (!modelName) {
        return ALL_REASONING_LEVELS;
    }

    const name = modelName.toLowerCase();

    // Models with no reasoning support at all.
    if (
        name.includes('gpt-4o') ||
        name.includes('gpt-4.1') ||
        name.includes('gpt-5-chat') ||
        name.includes('gpt-5-codex')
    ) {
        return ['none'];
    }

    if (name.includes('gpt-5-pro')) {
        return ['high'];
    }

    // The 5.1 series skips 'low'.
    if (name.includes('gpt-5.1')) {
        return ['none', 'minimal', 'medium', 'high'];
    }

    if (name.includes('gpt-5')) {
        return ['minimal', 'low', 'medium', 'high'];
    }

    // o-series reasoning models.
    if (/\bo[0-9]/.test(name)) {
        return ['low', 'medium', 'high'];
    }

    return ALL_REASONING_LEVELS;
}

/** True when the model offers a real choice worth surfacing a control for. */
export function supportsReasoning(modelName?: string): boolean {
    const levels = getModelSupportedLevels(modelName);
    return levels.length > 1 || (levels.length === 1 && levels[0] !== 'none');
}

export const REASONING_LABELS: Record<ReasoningEffort, string> = {
    none: 'None',
    minimal: 'Minimal',
    low: 'Low',
    medium: 'Medium',
    high: 'High',
};

/**
 * How a model is identified in the stored map.
 *
 * `model_id` first, then the deployment name, matching `getCurrentModelName()` in
 * chat-reasoning.js. The order matters twice over. It decides the key a level is stored
 * under, so a level chosen in one interface is found again by the other. It also decides
 * which name the level set is derived from, and a deployment an administrator named
 * `chat-prod` says nothing about reasoning support where its model id `gpt-5-mini` does.
 */
export function reasoningModelKey(
    model: { model_id?: unknown; deployment_name?: unknown } | undefined,
    fallback?: string,
): string {
    const modelId = typeof model?.model_id === 'string' ? model.model_id.trim() : '';
    const deployment =
        typeof model?.deployment_name === 'string' ? model.deployment_name.trim() : '';
    return modelId || deployment || (fallback ?? '').trim();
}

/**
 * The level in effect for a model, given what has been stored for it.
 *
 * Mirrors `getCurrentModelReasoningEffort()`: a model always has an effective level, so the
 * control shows a real value rather than an empty placeholder, and a stored level that the
 * current model does not accept is ignored instead of being sent and stripped.
 */
export function resolveReasoningEffort(
    modelName: string | undefined,
    saved?: ReasoningEffortSettings,
): ReasoningEffort {
    const levels = getModelSupportedLevels(modelName);

    // gpt-5-pro takes `high` and nothing else, so a stored value cannot override it.
    if (modelName && modelName.toLowerCase().includes('gpt-5-pro')) {
        return 'high';
    }

    const stored = modelName ? saved?.[modelName] : undefined;
    if (stored && levels.includes(stored as ReasoningEffort)) {
        return stored as ReasoningEffort;
    }

    return levels.includes('low') ? 'low' : levels[0];
}

/**
 * The value to send with a request, or undefined when nothing should be sent.
 *
 * Mirrors `getCurrentReasoningEffort()`, which returns null for `none`: the level is a real
 * choice in the picker but not a parameter the endpoint takes.
 */
export function requestReasoningEffort(level: string | undefined): string | undefined {
    return !level || level === 'none' ? undefined : level;
}
