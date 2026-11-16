// contentScreeningPolicy.ts

import type { AdminModelCatalogEntry } from './adminFields';
import {
    buildDefaultModelChoices,
    findChoiceIndex,
    type DefaultModelChoice,
    type DefaultModelSelection,
    type ModelConnection,
} from './modelConnections';
import type { ModelCatalogEntry } from './models';

export type ScreeningModelSelection = Pick<DefaultModelSelection, 'endpoint_id' | 'model_id'>;

export interface ScreeningRule {
    id: string;
    name: string;
    type: 'pii' | 'regex' | 'literal';
    enabled: boolean;
    severity: string;
    category: string;
    pii_type?: string;
    pattern?: string;
    values?: string[];
    case_sensitive?: boolean;
    whole_word?: boolean;
}

export interface ScreeningAiPolicy {
    enabled: boolean;
    model_selection: ScreeningModelSelection | null;
    instructions: string;
    severity: string;
    category: string;
    window_unit: 'pages' | 'chunks';
    window_size: number;
    max_characters: number;
    overlap_characters: number;
}

export interface ScreeningPolicy {
    schema_version?: number;
    fingerprint?: string;
    enabled: boolean;
    rules: ScreeningRule[];
    ai: ScreeningAiPolicy;
    allowed_models?: ScreeningModelSelection[];
    limits: Record<string, number>;
}

export interface ScreeningBaselineSummary {
    schema_version: number;
    enabled: boolean;
    rule_count: number;
    ai_check_count: number;
    rule_types: string[];
    pii_types: string[];
    severities: string[];
    fingerprint: string;
}

/** UI-normalized templates; the controller obtains every default from the server. */
export interface ScreeningPolicyTemplates {
    rules: ScreeningRule[];
    packs: Array<{ id: string; name: string; rules: ScreeningRule[] }>;
    ai: Array<{ id: string; name: string; instructions: string }>;
    severities: string[];
    piiTypes: Array<{ value: string; label: string }>;
}

export interface ScreeningTemplateCatalog {
    rules: Record<string, ScreeningRule>;
    packs: Record<string, string[]>;
    ai: Record<string, string | { name: string; instructions: string }>;
}

export function newScreeningRule(template: ScreeningRule): ScreeningRule {
    // Unlike randomUUID, getRandomValues is available on HTTP development hosts.
    const id = Array.from(
        crypto.getRandomValues(new Uint8Array(16)),
        (value) => value.toString(16).padStart(2, '0'),
    ).join('');
    return { ...structuredClone(template), id };
}

export function newCustomScreeningRule(
    type: ScreeningRule['type'], templates: ScreeningPolicyTemplates,
): ScreeningRule {
    const defaults = templates.rules.find((rule) => rule.type === type);
    if (!defaults) throw new Error('Rule definitions are unavailable. Reload the policy.');
    return newScreeningRule({
        id: '', name: '', type, enabled: defaults.enabled,
        category: defaults.category, severity: defaults.severity,
        ...(type === 'pii' ? { pii_type: '' } : {
            case_sensitive: false, whole_word: false,
            ...(type === 'regex' ? { pattern: '' } : { values: [] }),
        }),
    });
}

export function addScreeningStarterPack(policy: ScreeningPolicy, rules: ScreeningRule[]): ScreeningPolicy {
    const ids = new Set(policy.rules.map((rule) => rule.id));
    return {
        ...policy,
        rules: [...policy.rules, ...rules.filter((rule) => !ids.has(rule.id)).map((rule) => structuredClone(rule))],
    };
}

export function isScreeningPolicyInitialization(previous: ScreeningPolicy, next: ScreeningPolicy): boolean {
    if (previous.enabled || !next.enabled || previous.rules.length || next.rules.length
        || previous.ai.enabled || next.ai.enabled) return false;
    const configuration = (policy: ScreeningPolicy) => JSON.stringify([
        policy.schema_version,
        Object.entries(policy.ai).filter(([key]) => key !== 'model_selection').sort(([left], [right]) => left.localeCompare(right)),
        policy.ai.model_selection?.endpoint_id ?? '',
        policy.ai.model_selection?.model_id ?? '',
        policy.allowed_models ?? [],
        Object.entries(policy.limits).sort(([left], [right]) => left.localeCompare(right)),
    ]);
    return configuration(previous) === configuration(next);
}

export function screeningPolicySummary(
    policy: ScreeningPolicy, baseline: boolean, inherited?: ScreeningBaselineSummary | null,
): { label: string; detail: string } {
    if (!baseline && !inherited) {
        return { label: 'Required baseline unavailable', detail: 'Reload the policy before interpreting its effective checks.' };
    }
    if (!(baseline ? policy.enabled : inherited?.enabled)) {
        return {
            label: baseline ? 'Policy disabled' : 'Administrator baseline disabled',
            detail: 'Saved rules and model selections are inactive until the required baseline is enabled.',
        };
    }
    const requiredRules = baseline ? 0 : inherited?.rule_count ?? 0;
    const requiredAi = baseline ? 0 : inherited?.ai_check_count ?? 0;
    const rules = requiredRules + (policy.enabled ? policy.rules.filter((rule) => rule.enabled).length : 0);
    const ai = requiredAi + (policy.enabled && policy.ai.enabled ? 1 : 0);
    if (!rules && !ai) {
        return {
            label: 'No active checks configured',
            detail: baseline
                ? 'This policy can stay enabled and empty. New uploads use normal processing unless their workspace adds checks. Existing holds are unchanged.'
                : 'New uploads use normal processing until checks are added. Existing holds are unchanged.',
        };
    }
    return {
        label: `${rules} deterministic check${rules === 1 ? '' : 's'} | ${ai ? `${ai} AI check${ai === 1 ? '' : 's'}` : 'AI screening off'}`,
        detail: requiredAi
            ? `Includes ${requiredAi} required administrator AI check${requiredAi === 1 ? '' : 's'}. Disabling workspace AI additions does not disable required checks.`
            : 'Deterministic checks do not call a model. Model permission selections do not run checks.',
    };
}

export function screeningPolicyTemplates(catalog: ScreeningTemplateCatalog): ScreeningPolicyTemplates {
    const rules = Object.values(catalog.rules).map((rule) => structuredClone(rule));
    return {
        rules,
        packs: Object.entries(catalog.packs).map(([id, keys]) => ({
            id, name: id.replaceAll('_', ' '),
            rules: keys.map((key) => structuredClone(catalog.rules[key])),
        })),
        ai: Object.entries(catalog.ai).map(([id, value]) => ({
            id,
            name: typeof value === 'string' ? id.replaceAll('_', ' ') : value.name,
            instructions: typeof value === 'string' ? value : value.instructions,
        })),
        severities: ['low', 'medium', 'high', 'critical'],
        piiTypes: rules.filter((rule) => rule.type === 'pii' && rule.pii_type).map((rule) => ({
            value: rule.pii_type ?? '',
            label: rule.name,
        })),
    };
}

export function screeningModelIndex(
    models: DefaultModelChoice[],
    selection: ScreeningModelSelection | null,
): string {
    if (!selection || (!selection.endpoint_id && !selection.model_id)) {
        return '';
    }
    const index = findChoiceIndex(models, { ...selection, provider: '' });
    return index < 0 ? 'unavailable' : String(index);
}

export function screeningCatalogChoices(catalog: readonly ModelCatalogEntry[]): DefaultModelChoice[] {
    const connections = new Map<string, ModelConnection>();
    for (const model of catalog) {
        if (!model.selection_key?.startsWith('global:') || !model.endpoint_id || !model.model_id) {
            continue;
        }
        const label = model.display_name || model.model_name || model.deployment_name || model.model_id;
        const connection = connections.get(model.endpoint_id) ?? {
            id: model.endpoint_id,
            name: /https?:\/\//i.test(model.endpoint_id) ? 'Configured connection' : `Connection ${model.endpoint_id}`,
            provider: model.provider,
            enabled: true,
            models: [],
        };
        if (!connection.models?.some((item) => item.id === model.model_id)) {
            connection.models?.push({
                id: model.model_id,
                displayName: /https?:\/\//i.test(label) ? 'Configured model' : label,
                deploymentName: model.deployment_name,
                modelName: model.model_name,
                enabled: true,
                enabled_capabilities: ['chat'],
                capability_status: { chat: { supported: true, available: true, source: 'catalog' } },
            });
        }
        connections.set(model.endpoint_id, connection);
    }
    return buildDefaultModelChoices([...connections.values()]);
}

export function approvedScreeningChoices(
    models: DefaultModelChoice[], allowed: readonly ScreeningModelSelection[],
): DefaultModelChoice[] {
    return models.filter((model) => allowed.some(
        (reference) => reference.endpoint_id === model.endpointId && reference.model_id === model.modelId,
    ));
}

export function editableScreeningPolicy(policy: ScreeningPolicy, global: boolean): ScreeningPolicy {
    const copy = structuredClone(policy);
    copy.ai.model_selection ??= { endpoint_id: '', model_id: '' };
    if (!global) {
        delete copy.allowed_models;
    }
    return copy;
}

export function screeningModelCatalog(models: DefaultModelChoice[]): AdminModelCatalogEntry[] {
    return models.map((model, index) => ({
        deployment: String(index),
        label: model.modelLabel,
        endpoint: /https?:\/\//i.test(model.connectionName) ? 'Configured connection' : model.connectionName,
        endpoint_id: model.endpointId,
        model_name: model.modelId,
        supports_vision: false,
        supports_chat: true,
        vision_source: 'declared',
    }));
}

export function validateScreeningPolicy(policy: ScreeningPolicy, models: DefaultModelChoice[]): string[] {
    const errors: string[] = [];
    const ids = new Set<string>();
    for (const rule of policy.rules) {
        if (!rule.id || ids.has(rule.id)) {
            errors.push('Every rule must have a distinct ID. Refresh the policy before saving.');
        }
        ids.add(rule.id);
        if (!rule.name.trim()) {
            errors.push('Give each rule a name.');
        }
        if (rule.enabled && rule.type === 'regex' && !rule.pattern?.trim()) {
            errors.push(`${rule.name || 'Regex rule'} needs a pattern.`);
        }
        if (rule.enabled && rule.type === 'literal' && !rule.values?.some((value) => value.length > 0)) {
            errors.push(`${rule.name || 'Literal rule'} needs at least one value.`);
        }
        if (rule.enabled && rule.type === 'pii' && !rule.pii_type) {
            errors.push(`${rule.name || 'PII rule'} needs a built-in detector.`);
        }
    }
    if (policy.ai.enabled) {
        const selection = screeningModelIndex(models, policy.ai.model_selection);
        if (!selection || selection === 'unavailable') {
            errors.push('Select an approved, available scanner model.');
        }
        if (!policy.ai.instructions.trim()) {
            errors.push('Provide criteria for the model scanner.');
        }
    }
    if (!Number.isInteger(policy.ai.window_size) || policy.ai.window_size < 1 || policy.ai.window_size > 20) {
        errors.push('The scan window must contain between 1 and 20 pages or chunks.');
    }
    if (!Number.isInteger(policy.ai.max_characters) || policy.ai.max_characters < 256 || policy.ai.max_characters > 64000 ||
        !Number.isInteger(policy.ai.overlap_characters) || policy.ai.overlap_characters < 0 ||
        policy.ai.overlap_characters > 16000 || policy.ai.overlap_characters >= policy.ai.max_characters) {
        errors.push('Use 256-64000 characters per window and overlap from 0-16000, smaller than the window.');
    }
    if (Object.values(policy.limits).some((value) => !Number.isFinite(value) || value < 0)) {
        errors.push('Execution limits must be finite, nonnegative numbers.');
    }
    return [...new Set(errors)];
}
