// reasoning.ts
// Which reasoning effort levels a model accepts.
//
// Mirrors getModelSupportedLevels in static/js/chat/chat-reasoning.js. Offering a level a
// model rejects produces a request the endpoint has to strip, and hiding a level a model
// does support silently removes a capability, so the mapping is kept in step with the
// existing client rather than guessed.

export type ReasoningEffort = 'none' | 'minimal' | 'low' | 'medium' | 'high';

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
