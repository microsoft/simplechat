// reasoning.ts
// Policy comes from the authorized server catalog; preference keys remain shared with classic.

export type ReasoningEffort = 'none' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh';
export type ReasoningEffortSettings = Record<string, string>;

export interface ReasoningCapabilities {
    status: 'supported' | 'unsupported' | 'unknown';
    efforts: ReasoningEffort[];
    default_effort: ReasoningEffort | null;
}

export interface ReasoningResolution {
    requested_effort: string | null;
    effective_effort: string | null;
    mode: 'explicit' | 'model_default';
    adjustment_reason: string | null;
    stage?: 'planner' | 'answer';
    model_name?: string;
}

export const ALL_REASONING_LEVELS: ReasoningEffort[] = [
    'none', 'minimal', 'low', 'medium', 'high', 'xhigh',
];

export const REASONING_LABELS: Record<ReasoningEffort, string> = {
    none: 'None',
    minimal: 'Minimal',
    low: 'Low',
    medium: 'Medium',
    high: 'High',
    xhigh: 'XHigh',
};

export function getModelSupportedLevels(policy?: ReasoningCapabilities): ReasoningEffort[] {
    return policy?.status === 'supported' && Array.isArray(policy.efforts)
        ? policy.efforts.filter((level) => ALL_REASONING_LEVELS.includes(level))
        : [];
}

export function supportsReasoning(policy?: ReasoningCapabilities): boolean {
    return getModelSupportedLevels(policy).length > 0;
}

export function reasoningModelKey(
    model: { model_id?: unknown; deployment_name?: unknown } | undefined,
    fallback?: string,
): string {
    const modelId = typeof model?.model_id === 'string' ? model.model_id.trim() : '';
    const deployment =
        typeof model?.deployment_name === 'string' ? model.deployment_name.trim() : '';
    return modelId || deployment || (fallback ?? '').trim();
}

export function resolveReasoningSelection(
    modelKey: string | undefined,
    saved?: ReasoningEffortSettings,
    policy?: ReasoningCapabilities,
): ReasoningResolution {
    const requested = modelKey ? saved?.[modelKey] || null : null;
    const levels = getModelSupportedLevels(policy);
    const fallback = levels.includes('low')
        ? 'low'
        : levels.includes(policy?.default_effort as ReasoningEffort)
          ? policy!.default_effort
          : null;
    const effective = levels.includes(requested as ReasoningEffort) ? requested : fallback;
    return {
        requested_effort: requested,
        effective_effort: effective,
        mode: effective === null ? 'model_default' : 'explicit',
        adjustment_reason: requested && requested !== effective ? 'unsupported_effort' : null,
    };
}

export function resolveReasoningEffort(
    modelKey: string | undefined,
    saved?: ReasoningEffortSettings,
    policy?: ReasoningCapabilities,
): ReasoningEffort | undefined {
    const effective = resolveReasoningSelection(modelKey, saved, policy).effective_effort;
    return effective === null ? undefined : effective as ReasoningEffort;
}

/** Omitted and explicitly supported None are different provider requests. */
export function requestReasoningEffort(
    level: string | undefined,
    policy?: ReasoningCapabilities,
): string | undefined {
    return getModelSupportedLevels(policy).includes(level as ReasoningEffort) ? level : undefined;
}

export function normalizeReasoningAdjustments(
    value: unknown, previous: ReasoningResolution[] = [],
): ReasoningResolution[] {
    const entries = [...previous, ...(Array.isArray(value) ? value : [])];
    const resolutions = entries.filter((item): item is ReasoningResolution =>
        item !== null && typeof item === 'object' &&
        (item.adjustment_reason === null || typeof item.adjustment_reason === 'string') &&
        (item.mode === 'explicit' || item.mode === 'model_default') &&
        (item.requested_effort === null || typeof item.requested_effort === 'string') &&
        (item.effective_effort === null || typeof item.effective_effort === 'string'),
    );
    const latest = new Map<string, ReasoningResolution>();
    for (const resolution of resolutions) {
        const stage = resolution.stage === 'planner' || resolution.stage === 'answer' ? resolution.stage : '';
        const modelName = typeof resolution.model_name === 'string' ? resolution.model_name : '';
        latest.set(JSON.stringify([stage, modelName]), resolution);
    }
    return [...latest.values()].filter((resolution) => Boolean(resolution.adjustment_reason));
}

/** Merge only the public reasoning projection, preserving other message metadata. */
export function reasoningMetadataForEvent(event: {
    metadata?: Record<string, unknown>;
    reasoning_effort?: string | null;
    requested_reasoning_effort?: string | null;
    reasoning_mode?: 'explicit' | 'model_default';
    reasoning_adjustments?: ReasoningResolution[];
}, previousAdjustments: ReasoningResolution[] = []): Record<string, unknown> | undefined {
    if (event.reasoning_effort === undefined && event.requested_reasoning_effort === undefined &&
        event.reasoning_mode === undefined && event.reasoning_adjustments === undefined &&
        previousAdjustments.length === 0) {
        return event.metadata;
    }
    return {
        ...event.metadata,
        ...(event.reasoning_effort !== undefined ? { reasoning_effort: event.reasoning_effort } : {}),
        ...(event.requested_reasoning_effort !== undefined
            ? { requested_reasoning_effort: event.requested_reasoning_effort } : {}),
        ...(event.reasoning_mode !== undefined ? { reasoning_mode: event.reasoning_mode } : {}),
        ...(event.reasoning_adjustments !== undefined || previousAdjustments.length > 0
            ? { reasoning_adjustments: normalizeReasoningAdjustments(
                event.reasoning_adjustments ?? event.metadata?.reasoning_adjustments,
                previousAdjustments,
            ) } : {}),
    };
}

function effortLabel(effort: string | null): string {
    return REASONING_LABELS[effort as ReasoningEffort] ?? (effort ? 'Saved effort' : 'Model default');
}

/** Never display provider errors or adjustment_reason text supplied in an event. */
export function reasoningAdjustmentMessage(resolution: ReasoningResolution, modelName?: string): string {
    const stage = resolution.stage === 'planner' ? 'Planner: ' : resolution.stage === 'answer' ? 'Answer: ' : '';
    const effective = resolution.mode === 'model_default' ? 'Model default' : effortLabel(resolution.effective_effort);
    return `${stage}${effortLabel(resolution.requested_effort)} could not be used${modelName ? ` for ${modelName}` : ''}; using ${effective}.`;
}
