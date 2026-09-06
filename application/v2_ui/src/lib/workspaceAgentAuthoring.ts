// workspaceAgentAuthoring.ts
// Agent-only draft rules, shared by the routed editor and executable functional tests.

import type { WorkspaceModelEndpoint } from './types';
import {
    EDITOR_SECRET_MASK,
    editorName,
    editorValueAt,
    isRecord,
    pointerPart,
    sameEditorValue,
    type AgentConfiguration,
    type AgentEditorOptions,
    type AuthoringResource,
    type WorkspaceAgentType,
} from './workspaceAuthoring';

export const AGENT_TYPE_LABELS: Record<WorkspaceAgentType, string> = {
    local: 'Local',
    aifoundry: 'Azure AI Foundry',
    new_foundry: 'New Foundry',
    foundry_workflow: 'Foundry Workflow',
};

export const FOUNDRY_SETTINGS_KEYS = {
    aifoundry: 'azure_ai_foundry',
    new_foundry: 'new_foundry',
    foundry_workflow: 'foundry_workflow',
} as const;

export const AGENT_INPUT_CLASS = 'w-full min-w-0 rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none disabled:opacity-60';

export function agentText(value: unknown): string {
    return typeof value === 'string' ? value : '';
}

export function agentStrings(value: unknown): string[] {
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

export function agentObject(value: unknown): Record<string, unknown> {
    return isRecord(value) ? value : {};
}

export function isAgentEditorEnvelope(value: unknown): boolean {
    if (!isRecord(value) || !isRecord(value.record) || !Array.isArray(value.secret_paths) ||
        !value.secret_paths.every((path) => typeof path === 'string')) return false;
    return value.read_only === true || (typeof value.revision === 'string' && value.revision.trim().length > 0);
}

export function newAgentDraft(): AgentConfiguration {
    return {
        id: '',
        name: '',
        display_name: '',
        description: '',
        instructions: '',
        agent_type: 'local',
        is_global: false,
        is_group: false,
        tags: [],
        actions_to_load: [],
        other_settings: {},
        max_completion_tokens: -1,
    };
}

export function clearAgentDraftFields(draft: AgentConfiguration, ...keys: string[]): AgentConfiguration {
    const next = { ...draft };
    for (const key of keys) delete next[key];
    return next;
}

function containsAgentSecretMask(value: unknown): boolean {
    if (value === EDITOR_SECRET_MASK) return true;
    if (Array.isArray(value)) return value.some(containsAgentSecretMask);
    return isRecord(value) && Object.values(value).some(containsAgentSecretMask);
}

/** A kept array credential identifies a saved position, not a row name or ID. */
export function agentStoredArrayEditError(
    draft: AgentConfiguration, original: AuthoringResource<AgentConfiguration> | null,
): string | null {
    if (!original) return null;
    const secrets = new Set(original.secret_paths);
    const arrays = new Set<string>();
    for (const secret of secrets) {
        const parts = secret.slice(1).split('/');
        for (let length = 1; length < parts.length; length += 1) {
            const path = `/${parts.slice(0, length).join('/')}`;
            if (Array.isArray(editorValueAt(original.record, path)) || Array.isArray(editorValueAt(draft, path))) arrays.add(path);
        }
    }
    const sameKeptEntries = (before: unknown, after: unknown, path: string): boolean => {
        if (secrets.has(path)) return true;
        if (arrays.has(path)) {
            if (!containsAgentSecretMask(after)) return true;
            if (!Array.isArray(before) || !Array.isArray(after) || after.length > before.length) return false;
            // Trimming a suffix is safe when every kept credential still has its unchanged entry.
            return after.every((entry, index) => !containsAgentSecretMask(entry) ||
                sameKeptEntries(before[index], entry, `${path}/${index}`));
        }
        if (isRecord(before) && isRecord(after)) {
            return [...new Set([...Object.keys(before), ...Object.keys(after)])].every((key) =>
                sameKeptEntries(
                    Object.hasOwn(before, key) ? before[key] : undefined,
                    Object.hasOwn(after, key) ? after[key] : undefined,
                    `${path}/${pointerPart(key)}`,
                ));
        }
        return sameEditorValue(before, after);
    };
    for (const path of arrays) {
        if (!sameKeptEntries(editorValueAt(original.record, path), editorValueAt(draft, path), path)) {
            return `Stored credentials in ${path} belong to their saved array positions, not entry names or IDs. Keep those entries unchanged, or replace/clear their credentials before editing entries or changing the array structure.`;
        }
    }
    return null;
}

export function applySafeAgentDraft(
    current: AgentConfiguration, next: AgentConfiguration, original: AuthoringResource<AgentConfiguration> | null,
): AgentConfiguration {
    const error = agentStoredArrayEditError(next, original);
    if (!error) return clearAgentDraftFields(next, '_editor_array_secret_error');
    return {
        ...current,
        ...(typeof next._editor_settings_text === 'string' ? { _editor_settings_text: next._editor_settings_text } : {}),
        _editor_array_secret_error: error,
    };
}

export function renameAgentDraft(draft: AgentConfiguration, displayName: string, isNew: boolean): AgentConfiguration {
    const wasDerived = !draft.name || draft.name === editorName(draft.display_name);
    return {
        ...draft,
        display_name: displayName,
        ...(isNew && wasDerived ? { name: editorName(displayName) } : {}),
    };
}

export function updateAgentSetting(
    draft: AgentConfiguration,
    key: string,
    changes: Record<string, unknown>,
): AgentConfiguration {
    const settings = {
        ...draft.other_settings,
        [key]: { ...agentObject(draft.other_settings[key]), ...changes },
    };
    return clearAgentDraftFields({ ...draft, other_settings: settings }, '_editor_settings_text');
}

function mergeSettings(before: Record<string, unknown>, after: Record<string, unknown>): Record<string, unknown> {
    return Object.fromEntries([...new Set([...Object.keys(before), ...Object.keys(after)])].map((key) => {
        if (!Object.hasOwn(after, key)) return [key, before[key]];
        return [key, isRecord(before[key]) && isRecord(after[key])
            ? mergeSettings(before[key], after[key])
            : after[key]];
    }));
}

/** Managed sections cannot be erased by pasting an unrelated advanced-settings object. */
export function parseAgentSettings(text: string, current: Record<string, unknown>): Record<string, unknown> {
    const parsed: unknown = JSON.parse(text || '{}');
    if (!isRecord(parsed)) throw new Error('Additional settings must be a JSON object, not an array or scalar.');
    const managed = ['action_capabilities', 'assigned_knowledge', ...Object.values(FOUNDRY_SETTINGS_KEYS)];
    const result = { ...parsed };
    for (const key of managed) {
        if (Object.hasOwn(current, key)) {
            if (!Object.hasOwn(parsed, key)) result[key] = current[key];
            else if (isRecord(current[key]) && isRecord(parsed[key])) result[key] = mergeSettings(current[key], parsed[key]);
        }
    }
    const knowledge = agentObject(result.assigned_knowledge);
    const incomingKnowledge = agentObject(parsed.assigned_knowledge);
    const previousKnowledge = agentObject(current.assigned_knowledge);
    if (Object.hasOwn(incomingKnowledge, 'document_ids') && !sameEditorValue(incomingKnowledge.document_ids, previousKnowledge.document_ids)) {
        delete knowledge.selected_document_ids;
    }
    const incomingScopes = agentObject(incomingKnowledge.scopes);
    const previousScopes = agentObject(previousKnowledge.scopes);
    for (const [field, scope] of [['personal', 'personal'], ['group_ids', 'group'], ['public_workspace_ids', 'public']]) {
        if (Object.hasOwn(incomingScopes, field) && !sameEditorValue(incomingScopes[field], previousScopes[field])) {
            delete knowledge[field];
            if (Array.isArray(knowledge.sources)) knowledge.sources = knowledge.sources.filter((source) => agentObject(source).scope !== scope);
        }
    }
    if (Array.isArray(incomingKnowledge.web_sources) && !sameEditorValue(incomingKnowledge.web_sources, previousKnowledge.web_sources)) {
        knowledge.web_sources = incomingKnowledge.web_sources.map((source) => {
            if (!isRecord(source) || typeof source.mode !== 'string') return source;
            const normalized = { ...source };
            delete normalized.deep_research;
            return normalized;
        });
    }
    return result;
}

export function foundrySettings(draft: AgentConfiguration): Record<string, unknown> {
    return draft.agent_type === 'local' ? {} : agentObject(draft.other_settings[FOUNDRY_SETTINGS_KEYS[draft.agent_type]]);
}

/** Type selection never prunes actions, provider settings, credentials, or knowledge. */
export function changeAgentType(draft: AgentConfiguration, type: WorkspaceAgentType): AgentConfiguration {
    return { ...draft, agent_type: type };
}

export interface AgentModelChoice {
    key: string;
    id: string;
    endpointId: string;
    provider: string;
    deployment: string;
    modelName: string;
    label: string;
    apim: boolean;
}

export function agentModelChoices(options: AgentEditorOptions): AgentModelChoice[] {
    const choices: AgentModelChoice[] = [];
    for (const endpoint of options.model_endpoints) {
        if (endpoint.enabled === false) continue;
        for (const model of endpoint.models ?? []) {
            if (model.enabled === false) continue;
            const id = agentText(model.id || model.deploymentName || model.deployment || model.modelName || model.name);
            if (!id) continue;
            const deployment = agentText(model.deploymentName || model.deployment || model.modelName || model.name || id);
            choices.push({
                key: JSON.stringify([endpoint.id, id]),
                id,
                endpointId: endpoint.id,
                provider: agentText(endpoint.provider) || 'aoai',
                deployment,
                modelName: agentText(model.modelName || model.name || id),
                label: `${agentText(model.displayName) || deployment} · ${endpoint.name || endpoint.id}`,
                apim: false,
            });
        }
    }
    if (options.model_endpoints.length) return choices;
    const settings = options.settings;
    if (settings.enable_gpt_apim === true) {
        return agentText(settings.azure_apim_gpt_deployment).split(',').map((item) => item.trim()).filter(Boolean).map((id) => ({
            key: JSON.stringify(['apim', id]), id, endpointId: '', provider: '',
            deployment: id, modelName: id, label: id, apim: true,
        }));
    }
    const selected = agentObject(settings.gpt_model).selected;
    for (const item of Array.isArray(selected) ? selected : []) {
        const model = agentObject(item);
        const id = agentText(model.id || model.deploymentName || model.deployment || model.modelName || model.name);
        if (!id) continue;
        choices.push({
            key: JSON.stringify(['legacy', id]), id, endpointId: '', provider: '',
            deployment: agentText(model.deploymentName || model.deployment || id),
            modelName: agentText(model.modelName || model.name || id),
            label: agentText(model.display_name || model.displayName || model.deploymentName || model.deployment || id),
            apim: false,
        });
    }
    return choices;
}

export function selectedAgentModel(draft: AgentConfiguration, choices: AgentModelChoice[]): AgentModelChoice | undefined {
    if (draft.model_endpoint_id) {
        return choices.find((choice) => choice.endpointId === draft.model_endpoint_id && choice.id === draft.model_id);
    }
    const deployment = draft.enable_agent_gpt_apim ? draft.azure_agent_apim_gpt_deployment : draft.azure_openai_gpt_deployment;
    return choices.find((choice) => !choice.endpointId && choice.deployment === deployment);
}

export function selectAgentModel(draft: AgentConfiguration, choice: AgentModelChoice): AgentConfiguration {
    return {
        ...draft,
        model_endpoint_id: choice.endpointId,
        model_id: choice.endpointId ? choice.id : '',
        model_provider: choice.provider,
        enable_agent_gpt_apim: choice.apim,
        ...(choice.apim
            ? { azure_agent_apim_gpt_deployment: choice.deployment }
            : { azure_openai_gpt_deployment: choice.deployment }),
    };
}

export function foundryEndpointMatches(type: WorkspaceAgentType, endpoint: WorkspaceModelEndpoint): boolean {
    if (endpoint.enabled === false) return false;
    return type === 'foundry_workflow'
        ? ['foundry_workflow', 'new_foundry', 'aifoundry'].includes(agentText(endpoint.provider))
        : endpoint.provider === type;
}

export function selectFoundryEndpoint(draft: AgentConfiguration, endpoint: WorkspaceModelEndpoint): AgentConfiguration {
    if (draft.agent_type === 'local') return draft;
    const connection = agentObject(endpoint.connection);
    const current = foundrySettings(draft);
    const projectVersion = agentText(connection.project_api_version || connection.api_version) || 'v1';
    const responseVersion = agentText(connection.openai_api_version || connection.api_version);
    const version = draft.agent_type === 'aifoundry' ? projectVersion : responseVersion || agentText(current.responses_api_version);
    return updateAgentSetting({
        ...draft,
        model_endpoint_id: endpoint.id,
        model_provider: draft.agent_type === 'foundry_workflow' ? agentText(endpoint.provider) : draft.agent_type,
        azure_openai_gpt_endpoint: agentText(connection.endpoint),
        azure_openai_gpt_deployment: agentText(connection.project_name),
        azure_openai_gpt_api_version: version,
    }, FOUNDRY_SETTINGS_KEYS[draft.agent_type], {
        endpoint_id: endpoint.id,
        endpoint: agentText(connection.endpoint),
        project_name: agentText(connection.project_name),
        authentication_type: 'delegated_user',
        ...(draft.agent_type !== 'aifoundry' && version ? { responses_api_version: version } : {}),
    });
}

export interface FoundryDiscoveryRecord {
    id?: string;
    name?: string;
    display_name?: string;
    description?: string;
    application_id?: string;
    application_name?: string;
    application_version?: string;
    workflow_name?: string;
    workflow_agent_id?: string;
    responses_api_version?: string;
    agent_reference?: Record<string, unknown>;
    [key: string]: unknown;
}

export function applyFoundryDiscovery(draft: AgentConfiguration, selected: FoundryDiscoveryRecord): AgentConfiguration {
    if (draft.agent_type === 'local') return draft;
    const changes: Record<string, unknown> = {};
    if (draft.agent_type === 'aifoundry') changes.agent_id = selected.id ?? '';
    if (draft.agent_type === 'new_foundry') {
        Object.assign(changes, {
            application_id: selected.application_id || selected.id || '',
            application_name: selected.application_name || selected.name || '',
            application_version: selected.application_version || '',
        });
    }
    if (draft.agent_type === 'foundry_workflow') {
        const reference = agentObject(selected.agent_reference);
        const name = selected.workflow_name || selected.application_name || selected.name || '';
        const id = selected.workflow_agent_id || agentText(reference.id) || selected.id;
        Object.assign(changes, {
            workflow_name: name,
            ...(id ? { workflow_agent_id: id } : {}),
            ...(selected.application_id ? { application_id: selected.application_id } : {}),
            ...(selected.application_version ? { application_version: selected.application_version } : {}),
            agent_reference: {
                ...reference,
                type: agentText(reference.type) || 'agent_reference',
                name,
                ...(id ? { id } : {}),
                ...(selected.application_id ? { application_id: selected.application_id } : {}),
                ...(selected.application_version ? { application_version: selected.application_version } : {}),
            },
        });
    }
    if (selected.responses_api_version) changes.responses_api_version = selected.responses_api_version;
    return updateAgentSetting({
        ...draft,
        ...(selected.responses_api_version ? { azure_openai_gpt_api_version: selected.responses_api_version } : {}),
    }, FOUNDRY_SETTINGS_KEYS[draft.agent_type], changes);
}

export function agentValidationErrors(draft: AgentConfiguration, options: AgentEditorOptions): string[] {
    const errors: string[] = [];
    if (!draft.display_name.trim()) errors.push('Display name is required.');
    if (!/^[A-Za-z0-9_-]+$/.test(draft.name)) errors.push('Internal name must contain only letters, digits, underscores, and dashes.');
    if (!draft.description.trim()) errors.push('Description is required.');
    if (!options.agent_types.some((type) => type.value === draft.agent_type && type.enabled)) errors.push('This agent type is not available for your workspace.');
    if (!Number.isInteger(draft.max_completion_tokens) || draft.max_completion_tokens < -1 || draft.max_completion_tokens > 512000) {
        errors.push('Completion token limit must be an integer between -1 and 512000.');
    }
    if ((draft.tags ?? []).length > 20 || (draft.tags ?? []).some((tag) => tag.length > 40)) errors.push('Use at most 20 tags, each at most 40 characters.');
    if (draft.agent_type === 'local') {
        if (!draft.instructions.trim()) errors.push('Instructions are required for a local agent.');
    } else {
        const settings = foundrySettings(draft);
        if (draft.actions_to_load.length) errors.push('Foundry manages its own tools. Explicitly detach local actions before saving this type.');
        if (draft.enable_agent_gpt_apim) errors.push('Disable the local APIM connection before saving a Foundry agent.');
        const selectedEndpoint = options.model_endpoints.find((endpoint) => endpoint.id === draft.model_endpoint_id);
        if (selectedEndpoint && !foundryEndpointMatches(draft.agent_type, selectedEndpoint)) errors.push('Choose a compatible Foundry connection or select manual connection before saving this type.');
        if (!agentText(draft.azure_openai_gpt_endpoint || settings.endpoint).trim()) errors.push('A Foundry project endpoint is required.');
        const version = draft.agent_type === 'aifoundry' ? draft.azure_openai_gpt_api_version : settings.responses_api_version || draft.azure_openai_gpt_api_version;
        if (!agentText(version).trim()) errors.push('A Foundry API version is required.');
        if (draft.agent_type === 'aifoundry' && !agentText(settings.agent_id).trim()) errors.push('Foundry agent ID is required.');
        if (draft.agent_type === 'new_foundry' && !agentText(settings.application_id || settings.application_name).trim()) errors.push('Foundry application ID or name is required.');
        if (draft.agent_type === 'foundry_workflow' && !agentText(settings.workflow_name).trim()) errors.push('Foundry workflow name is required.');
    }
    return errors;
}

export const secretValueAt = editorValueAt;

export function setAgentSecret(draft: AgentConfiguration, path: string, value: string): AgentConfiguration {
    const parts = path.slice(1).split('/').map((part) => part.replace(/~1/g, '/').replace(/~0/g, '~'));
    const set = (record: unknown, index: number): unknown => {
        if (Array.isArray(record)) {
            const at = Number(parts[index]);
            if (!/^(0|[1-9]\d*)$/.test(parts[index]) || at >= record.length) throw new Error('The secret array entry is no longer available.');
            return record.map((entry, position) => position !== at ? entry
                : index === parts.length - 1 ? value : set(entry, index + 1));
        }
        const object = agentObject(record);
        return { ...object, [parts[index]]: index === parts.length - 1 ? value : set(object[parts[index]], index + 1) };
    };
    return clearAgentDraftFields({ ...draft, ...agentObject(set(draft, 0)) }, '_editor_settings_text');
}

export function isAgentIconImage(value: unknown): value is string {
    return typeof value === 'string' && value.length <= 350000 &&
        /^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(value);
}

/** An explicit save may fill Foundry's canonical placeholder, never replace a prompt. */
export function agentForSave(draft: AgentConfiguration): AgentConfiguration {
    return {
        ...draft,
        display_name: draft.display_name.trim(),
        name: draft.name.trim(),
        ...(draft.agent_type !== 'local' && !draft.instructions.trim()
            ? { instructions: 'Placeholder instructions: Azure AI Foundry agent manages its own prompt.' }
            : {}),
    };
}

export function secretIntent(value: unknown, original: unknown): 'keep' | 'replace' | 'clear' {
    if (value === EDITOR_SECRET_MASK || (value === undefined && original === undefined)) return 'keep';
    return (value === '' || value === undefined || value === null) && original === EDITOR_SECRET_MASK ? 'clear' : 'replace';
}
