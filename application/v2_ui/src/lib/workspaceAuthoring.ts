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

/**
 * Fields the server stamps on a stored record and never accepts back, in `updates` or
 * `removed_paths`. Global records carry the ones the classic global saves write. The global editor
 * adapters strip them from both sides of the diff, so no editor change can emit them.
 */
const SERVER_STAMPED_FIELDS = ['scope', 'scope_id', 'scope_type', 'updated_at', 'updated_by', 'owner_id', 'owner_user_id'];

export function withoutServerStampedFields<T extends object>(record: T): T {
    const clone = { ...(record as Record<string, unknown>) };
    for (const field of SERVER_STAMPED_FIELDS) delete clone[field];
    return clone as T;
}

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

/** A path segment that names a real, safe resource id, not a traversal or control sequence. */
function validPathIdentifier(segment: string): boolean {
    let identifier: string;
    try {
        identifier = decodeURIComponent(segment);
    } catch (error) {
        if (error instanceof URIError) return false;
        throw error;
    }
    return Boolean(identifier.trim()) && !['.', '..'].includes(identifier) &&
        !/[/\\\u0000-\u001f\u007f]/.test(identifier);
}

/** The return-path scope for global agents edited from Admin Settings. */
export const GLOBAL_AGENT_RETURN_SCOPE = { kind: 'global' } as const;

/** A group id, or the global scope; absent means personal. */
export type AgentEditorReturnScope = string | typeof GLOBAL_AGENT_RETURN_SCOPE;

/** The SPA routes the administrator's global agent and action editors live under. */
export const GLOBAL_AGENTS_BASE_PATH = '/admin/agents';
export const GLOBAL_ACTIONS_BASE_PATH = '/admin/actions';

/**
 * Only a known agent editor can receive a just-created action.
 *
 * Personal scope, the default, matches `/workspace/agents/<id>` exactly as before, so personal
 * callers and links are byte-identical. A group caller passes its group id, and only that group's
 * `/groups/<id>/agents/<id>` path is accepted -- an action created for group A can never hand back
 * into group B, and a personal path is refused in group scope and the reverse. The group id is
 * matched by its encoded spelling, the same spelling `workspaceBasePath` writes into the URL. The
 * global scope accepts only the Admin Settings agent editor, `/admin/agents/<id>`.
 */
export function agentEditorReturnPath(value: string | null, scope?: AgentEditorReturnScope): string | null {
    if (!value) return null;
    let identifierSegment: string | undefined;
    if (typeof scope === 'string') {
        const prefix = `/groups/${encodeURIComponent(scope)}/agents/`;
        if (!value.startsWith(prefix)) return null;
        const rest = value.slice(prefix.length);
        identifierSegment = /^[^/?#]+$/.test(rest) ? rest : undefined;
    } else if (scope?.kind === 'global') {
        identifierSegment = value.match(/^\/admin\/agents\/([^/?#]+)$/)?.[1];
    } else {
        identifierSegment = value.match(/^\/workspace\/agents\/([^/?#]+)$/)?.[1];
    }
    return identifierSegment && validPathIdentifier(identifierSegment) ? value : null;
}

/**
 * Whether a path is any agent editor, personal, group or global. Used only by the editor frame's
 * navigation blocker, which recognises the agent<->action handoff without knowing the group id --
 * the returnTo linkage the blocker also checks ties the two halves together. Stricter callers pass
 * an explicit scope to `agentEditorReturnPath` instead.
 */
export function isAgentEditorPath(value: string | null): boolean {
    if (agentEditorReturnPath(value) || agentEditorReturnPath(value, GLOBAL_AGENT_RETURN_SCOPE)) return true;
    const identifierSegment = value?.match(/^\/groups\/[^/?#]+\/agents\/([^/?#]+)$/)?.[1];
    return Boolean(identifierSegment && validPathIdentifier(identifierSegment));
}

/** Whether a path is a new-action editor, personal, group or global. Used by the editor frame blocker. */
export function isActionEditorNewPath(value: string): boolean {
    return value === '/workspace/actions/new' || value === `${GLOBAL_ACTIONS_BASE_PATH}/new`
        || /^\/groups\/[^/?#]+\/actions\/new$/.test(value);
}
