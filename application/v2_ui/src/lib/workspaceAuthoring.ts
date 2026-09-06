// workspaceAuthoring.ts
// Editor contracts are separate from persisted manifests and their secret values.

import type { WorkspaceAction, WorkspaceAgent, WorkspaceModelEndpoint } from './types';

export const EDITOR_SECRET_MASK = '***REDACTED***';
export type WorkspaceAgentType = 'local' | 'aifoundry' | 'new_foundry' | 'foundry_workflow';

export interface AgentConfiguration extends WorkspaceAgent {
    name: string;
    display_name: string;
    description: string;
    instructions: string;
    agent_type: WorkspaceAgentType;
    actions_to_load: string[];
    other_settings: Record<string, unknown>;
    max_completion_tokens: number;
    icon?: { kind: 'bootstrap' | 'image'; value: string; mime_type?: string };
    model_endpoint_id?: string;
    model_id?: string;
    model_provider?: string;
    reasoning_effort?: string;
    azure_openai_gpt_endpoint?: string;
    azure_openai_gpt_key?: string;
    azure_openai_gpt_deployment?: string;
    azure_openai_gpt_api_version?: string;
    enable_agent_gpt_apim?: boolean;
    azure_agent_apim_gpt_endpoint?: string;
    azure_agent_apim_gpt_subscription_key?: string;
    azure_agent_apim_gpt_deployment?: string;
    azure_agent_apim_gpt_api_version?: string;
}

export interface ActionConfiguration extends WorkspaceAction {
    name: string;
    displayName: string;
    description: string;
    type: string;
    endpoint: string;
    auth: {
        type: string;
        key?: string;
        identity?: string;
        tenantId?: string;
        [key: string]: unknown;
    };
    identity_id?: string;
    additionalFields: Record<string, unknown>;
    metadata: Record<string, unknown>;
    is_enabled?: boolean;
}

export interface AuthoringResource<T> {
    record: T;
    revision: string;
    secret_paths: string[];
    read_only: boolean;
}

export interface EditorWrite {
    updates: Record<string, unknown>;
    expected_revision?: string;
    clear_secret_paths: string[];
    removed_paths: string[];
}

export interface EditorSchema {
    type?: string | string[];
    title?: string;
    description?: string;
    format?: string;
    default?: unknown;
    enum?: unknown[];
    const?: unknown;
    properties?: Record<string, EditorSchema>;
    required?: string[];
    items?: EditorSchema;
    additionalProperties?: boolean | EditorSchema;
    minimum?: number;
    maximum?: number;
    minLength?: number;
    maxLength?: number;
    minItems?: number;
    maxItems?: number;
    pattern?: string;
    definitions?: Record<string, EditorSchema>;
    $ref?: string;
    allOf?: EditorSchema[];
    anyOf?: EditorSchema[];
    oneOf?: EditorSchema[];
}

export interface ActionTypeDefinition {
    type: string;
    display: string;
    description: string;
    allowed_auth_types: string[];
    additional_fields_schema: EditorSchema;
    metadata_schema: EditorSchema;
}

export interface AgentEditorOptions {
    agent_types: {
        value: WorkspaceAgentType;
        label: string;
        enabled: boolean;
        reason?: string;
    }[];
    settings: Record<string, unknown>;
    model_endpoints: WorkspaceModelEndpoint[];
    builtin_actions: { id: string; label: string; description?: string }[];
}

export function isRecord(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export function editorName(displayName: string, fallback = 'agent'): string {
    return displayName.trim().replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || fallback;
}

export function pointerPart(value: string): string {
    return value.replace(/~/g, '~0').replace(/\//g, '~1');
}

export function editorValueAt(record: unknown, path: string): unknown {
    if (!path.startsWith('/')) return undefined;
    return path.slice(1).split('/').reduce<unknown>((value, part) => {
        const key = part.replace(/~1/g, '/').replace(/~0/g, '~');
        if (Array.isArray(value)) {
            return /^(0|[1-9]\d*)$/.test(key) && Object.hasOwn(value, key) ? value[Number(key)] : undefined;
        }
        return isRecord(value) && Object.hasOwn(value, key) ? value[key] : undefined;
    }, record);
}

export function sameEditorValue(left: unknown, right: unknown): boolean {
    if (Object.is(left, right)) return true;
    if (Array.isArray(left) && Array.isArray(right)) {
        return left.length === right.length && left.every((item, index) => sameEditorValue(item, right[index]));
    }
    if (!isRecord(left) || !isRecord(right)) return false;
    const keys = Object.keys(left);
    return keys.length === Object.keys(right).length &&
        keys.every((key) => Object.hasOwn(right, key) && sameEditorValue(left[key], right[key]));
}

const MANAGED_FIELDS = new Set(['user_id', 'last_updated', 'modified_at', 'modified_by', 'created_at', 'created_by', 'is_global', 'is_group', 'group_id']);

/** Array changes replace the array; object changes name only changed leaves. */
export function buildEditorWrite<T extends Record<string, unknown>>(
    draft: T,
    original: AuthoringResource<T> | null,
): EditorWrite {
    const clearSecretPaths = new Set<string>();
    const removedPaths: string[] = [];
    const secretPaths = new Set(original?.secret_paths ?? []);
    const previous = original?.record ?? {};
    // Arrays are replacements, so their removed/cleared credentials need separate intent.
    for (const path of secretPaths) {
        const value = editorValueAt(draft, path);
        if (value === undefined || value === null || value === '') clearSecretPaths.add(path);
    }
    const diff = (before: Record<string, unknown>, after: Record<string, unknown>, parent = '') => {
        const updates: [string, unknown][] = [];
        for (const key of Object.keys(after)) {
            if (!parent && (key.startsWith('_') || MANAGED_FIELDS.has(key) || (original && key === 'id'))) continue;
            const path = `${parent}/${pointerPart(key)}`;
            const value = after[key];
            if (value === undefined || (secretPaths.has(path) && value === EDITOR_SECRET_MASK)) continue;
            if (secretPaths.has(path) && (value === '' || value === null)) {
                clearSecretPaths.add(path);
                continue;
            }
            if (isRecord(value)) {
                const nested = diff(isRecord(before[key]) ? before[key] : {}, value, path);
                if (Object.keys(nested).length || !Object.hasOwn(before, key)) updates.push([key, nested]);
            } else if (!sameEditorValue(before[key], value)) {
                updates.push([key, value]);
            }
        }
        for (const key of Object.keys(before)) {
            if (!parent && (key.startsWith('_') || MANAGED_FIELDS.has(key) || key === 'id')) continue;
            if (!Object.hasOwn(after, key)) {
                const path = `${parent}/${pointerPart(key)}`;
                if (secretPaths.has(path)) clearSecretPaths.add(path);
                else removedPaths.push(path);
            }
        }
        // Additional JSON property names, including __proto__, remain ordinary data.
        return Object.fromEntries(updates);
    };
    return {
        updates: diff(previous, draft),
        ...(original ? { expected_revision: original.revision } : {}),
        clear_secret_paths: [...clearSecretPaths],
        removed_paths: removedPaths,
    };
}

/** Only a known agent editor can receive a just-created action. */
export function agentEditorReturnPath(value: string | null): string | null {
    const match = value?.match(/^\/workspace\/agents\/([^/?#]+)$/);
    if (!match) return null;
    let identifier: string;
    try {
        identifier = decodeURIComponent(match[1]);
    } catch (error) {
        if (error instanceof URIError) return null;
        throw error;
    }
    return identifier.trim() && !['.', '..'].includes(identifier) &&
        !/[/\\\u0000-\u001f\u007f]/.test(identifier) ? value : null;
}
