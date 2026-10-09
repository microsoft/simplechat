// connectionMetadata.ts

import { isResourceIconImage } from './resourceIcons';
import type { ResourceIcon } from './resourceIcons';

export interface ConnectionCapacity {
    contextWindow?: number | string | null;
    inputTokenLimit?: number | string | null;
    outputTokenLimit?: number | string | null;
    catalogModelId?: string | null;
    modelVersion?: string | null;
    tokenLimitProvider?: string | null;
    outputTokenAccounting?: string | null;
}

export const CAPACITY_FIELDS = [
    { key: 'contextWindow', label: 'Context window (tokens)', help: 'Verified shared total for input and generation together.' },
    { key: 'inputTokenLimit', label: 'Input token limit (tokens)', help: 'An independent input ceiling, not the shared context window.' },
    { key: 'outputTokenLimit', label: 'Output token limit (tokens)', help: 'The hard provider output ceiling, not the requested response length.' },
] as const;

export const CAPACITY_IDENTITY_FIELDS = [
    { key: 'catalogModelId', label: 'Catalog model ID', help: 'The published model ID, not a display name or deployment alias.' },
    { key: 'modelVersion', label: 'Model version', help: 'The exact deployed snapshot, not the endpoint API version.' },
] as const;

export const TOKEN_PROVIDER_OPTIONS = ['', 'azure', 'openai', 'anthropic', 'google', 'vertex', 'xai', 'publisher', 'custom'] as const;
export const TOKEN_ACCOUNTING_OPTIONS = ['', 'total_generation', 'visible_only', 'unknown'] as const;

export function tokenCapacity(value: unknown, label: string): number | null {
    if (value === null || value === undefined || (typeof value === 'string' && !value.trim())) return null;
    const normalized = typeof value === 'string' && /^[0-9]+$/.test(value.trim()) ? Number(value.trim()) : value;
    if (typeof normalized !== 'number' || !Number.isSafeInteger(normalized) || normalized <= 0) {
        throw new Error(`${label} must be a positive whole number no greater than 9007199254740991, or blank to inherit.`);
    }
    return normalized;
}

export function capacityErrors(record: ConnectionCapacity, model = false): Record<string, string> {
    const errors: Record<string, string> = {};
    for (const { key, label } of CAPACITY_FIELDS) {
        try { tokenCapacity(record[key], label); } catch (cause) {
            if (!(cause instanceof Error)) throw cause;
            errors[key] = cause.message;
        }
    }
    const fields = [...(model ? CAPACITY_IDENTITY_FIELDS : []),
        { key: 'tokenLimitProvider', label: 'Token limit provider' },
        { key: 'outputTokenAccounting', label: 'Output token accounting' }] as const;
    for (const { key, label } of fields) {
        const value = record[key];
        if (value !== null && value !== undefined && (typeof value !== 'string'
            || value.trim().length > 256 || /[\u0000-\u001f]/.test(value.trim()))) {
            errors[key] = `${label} must be text of at most 256 characters without control characters.`;
        }
    }
    const provider = typeof record.tokenLimitProvider === 'string' ? record.tokenLimitProvider.trim() : record.tokenLimitProvider ?? '';
    const accounting = typeof record.outputTokenAccounting === 'string' ? record.outputTokenAccounting.trim() : record.outputTokenAccounting ?? '';
    if (!TOKEN_PROVIDER_OPTIONS.some((value) => value === provider)) {
        errors.tokenLimitProvider = 'Choose a supported token-limit provider.';
    }
    if (!TOKEN_ACCOUNTING_OPTIONS.some((value) => value === accounting)) {
        errors.outputTokenAccounting = 'Choose a supported output-token accounting mode.';
    }
    return errors;
}

export function capacityPayload(record: ConnectionCapacity, model = false): Record<string, unknown> {
    const errors = capacityErrors(record, model);
    if (Object.keys(errors).length) throw new Error(Object.values(errors)[0]);
    const payload: Record<string, unknown> = {};
    for (const { key, label } of CAPACITY_FIELDS) {
        if (key in record) payload[key] = tokenCapacity(record[key], label);
    }
    const fields = [...(model ? CAPACITY_IDENTITY_FIELDS : []),
        { key: 'tokenLimitProvider' }, { key: 'outputTokenAccounting' }] as const;
    for (const { key } of fields) {
        if (key in record) payload[key] = record[key]?.trim() || null;
    }
    return payload;
}

export function validModelIcon(icon: unknown): icon is ResourceIcon | Record<string, never> {
    if (typeof icon !== 'object' || icon === null || Array.isArray(icon)) return false;
    if (!Object.keys(icon).length) return true;
    if (!('kind' in icon) || !('value' in icon) || typeof icon.value !== 'string') return false;
    return icon.kind === 'image' ? isResourceIconImage(icon.value)
        : icon.kind === 'bootstrap' && /^bi-[a-z0-9][a-z0-9-]{0,80}$/.test(icon.value);
}
