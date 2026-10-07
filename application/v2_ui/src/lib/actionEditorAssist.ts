// actionEditorAssist.ts
// How the action editor describes its draft to Ask AI, and how it applies Ask AI's changes.
//
// The view describes the fields a person can set in the editor for each action type. The action
// type is a variant: choosing another type brings in that type's fields. Credentials, secret
// values, identities and raw JSON are never described, so Ask AI can't read or set them. Applying
// a patch goes through the editor's own helpers (type switch, field mirrors, authentication
// method), so a change from Ask AI is the same change the person could have made by hand.

import type {
    EditorAssistField, EditorAssistFieldKind, EditorAssistSection, EditorAssistValues, EditorAssistView,
} from './editorAssist';
import {
    EDITOR_SECRET_MASK, isRecord, pointerPart, type ActionConfiguration, type ActionTypeDefinition, type EditorSchema,
} from './workspaceAuthoring';
import {
    actionAuthMethod, actionAuthModes, actionText, actionTypeLabel, actionValueAt, changeActionAuth,
    changeActionDisplayName, changeActionField, changeActionType, displayedActionValue, resolveActionSchema,
} from './workspaceActionLogic';
import { nativeActionDefinition } from './workspaceActionRegistry';
import type { ActionFieldDescriptor } from './workspaceActionTypes';

/** The editor's sections, in the order the editor shows them. */
export const ACTION_ASSIST_SECTIONS: readonly EditorAssistSection[] = [
    { id: 'identity', label: 'Identity and type' },
    { id: 'configuration', label: 'Configuration' },
    { id: 'authentication', label: 'Authentication' },
    { id: 'advanced', label: 'Advanced' },
];

/** Paths the server accepts for an action; anything else would refuse the whole request. */
const ACTION_PATH = /^\/(displayName|description|type|endpoint|deployment|api_version|auth\/type|additionalFields\/[A-Za-z0-9_]{1,80}|metadata\/[A-Za-z0-9_]{1,80})$/;
const SECRET_KEY = /secret|password|credential|connection|private|sas_url|cookie|bearer|token|api_key|^key$/i;
const DESCRIPTION_LIMIT = 2000;
const DISPLAY_NAME_LIMIT = 100;
const MAX_SCHEMA_OPTIONS = 200;

export interface ActionAssistContext {
    /** The action types this workspace may use. */
    readonly catalogue: readonly ActionTypeDefinition[];
    readonly isNew: boolean;
    /** Paths the saved action stores as secrets; never described. */
    readonly secretPaths?: readonly string[];
}

/** How a described field is read and written. */
type FieldSource =
    | { readonly kind: 'native'; readonly descriptor: ActionFieldDescriptor }
    | { readonly kind: 'capabilities'; readonly path: string }
    | { readonly kind: 'auth' }
    | { readonly kind: 'mcp'; readonly key: string; readonly fallback: unknown }
    | { readonly kind: 'endpoint' }
    | { readonly kind: 'schema'; readonly schema: EditorSchema };

interface DescribedField {
    readonly field: EditorAssistField;
    readonly source: FieldSource;
}

function definitionFor(type: string, context: ActionAssistContext): ActionTypeDefinition | undefined {
    return context.catalogue.find((definition) => definition.type === type);
}

function fallbackDefinition(draft: ActionConfiguration): ActionTypeDefinition {
    return {
        type: draft.type, display: actionTypeLabel(draft.type), description: '',
        allowed_auth_types: draft.auth.type ? [draft.auth.type] : [],
        additional_fields_schema: {}, metadata_schema: {},
    };
}

function isSecret(draft: ActionConfiguration, path: string, context: ActionAssistContext): boolean {
    if (context.secretPaths?.includes(path) || actionValueAt(draft, path) === EDITOR_SECRET_MASK) return true;
    const key = path.split('/').at(-1) ?? '';
    return key.endsWith('__Secret') || SECRET_KEY.test(key);
}

function nativeKind(descriptor: ActionFieldDescriptor): EditorAssistFieldKind | null {
    switch (descriptor.kind ?? 'text') {
        case 'text': return 'text';
        case 'textarea': return 'textarea';
        case 'number': return 'number';
        case 'boolean': return 'boolean';
        case 'select': return 'select';
        case 'lines': return 'lines';
        default: return null;
    }
}

function schemaField(key: string, schema: EditorSchema, root: EditorSchema, required: boolean): Omit<EditorAssistField, 'path' | 'section'> | null {
    const resolved = resolveActionSchema(schema, root);
    const types = (Array.isArray(resolved.type) ? resolved.type : [resolved.type]).filter((type) => type && type !== 'null');
    const label = resolved.title || key.replace(/([a-z])([A-Z])/g, '$1 $2').replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase());
    const help = resolved.description;
    const values = resolved.enum;
    if (Object.hasOwn(resolved, 'const')) return null;
    if (values) {
        if (!values.every((item) => typeof item === 'string') || values.length > MAX_SCHEMA_OPTIONS) return null;
        // A blank enum entry means "not set", which Ask AI expresses as null.
        const options = (values as string[]).filter(Boolean).map((value) => ({ value }));
        return options.length ? { label, help, required, kind: 'select', options } : null;
    }
    const type = types[0] ?? (resolved.properties ? 'object' : 'string');
    if (type === 'string') return { label, help, required, kind: 'text', max_length: resolved.maxLength };
    if (type === 'number' || type === 'integer') {
        return { label, help, required, kind: 'number', min: resolved.minimum, max: resolved.maximum, integer: type === 'integer' };
    }
    if (type === 'boolean') return { label, help, required, kind: 'boolean' };
    if (type === 'array') {
        const items = resolveActionSchema(resolved.items ?? {}, root);
        const itemTypes = Array.isArray(items.type) ? items.type : [items.type];
        if (itemTypes.includes('string') && !items.enum) return { label, help, required, kind: 'lines', max_items: resolved.maxItems };
    }
    return null;
}

/** The covered paths the editor renders itself, so schema properties don't repeat them. */
function coveredPaths(draft: ActionConfiguration): string[] {
    const native = nativeActionDefinition(draft.type);
    const sql = ['sql_query', 'sql_schema'].includes(draft.type);
    return [
        ...native.fields.map(({ path }) => path),
        '/additionalFields/identity_auth_type',
        ...(sql ? ['/additionalFields/auth_type', '/additionalFields/username', '/additionalFields/password', '/additionalFields/identity_uses_connection_string'] : []),
        ...(['databricks', 'databricks_table', 'snowflake', 'tableau', 'yamcs'].includes(draft.type) ? ['/additionalFields/auth_method'] : []),
        ...(['databricks', 'databricks_table'].includes(draft.type) ? ['/additionalFields/workspace_url'] : []),
        ...(['tableau', 'yamcs'].includes(draft.type) ? ['/additionalFields/server_url'] : []),
        ...(draft.type === 'tableau' ? ['/additionalFields/pat_name'] : []),
        ...(draft.type === 'rocksdb' ? ['/additionalFields/auth_scheme', '/additionalFields/api_key_header', '/additionalFields/base_url'] : []),
        ...(native.capabilities ? [native.capabilities.path] : []),
    ];
}

const MCP_FIELDS: readonly { key: string; field: Omit<EditorAssistField, 'path' | 'section'>; fallback: unknown }[] = [
    { key: 'load_tools', fallback: true, field: { label: 'Load tools', kind: 'boolean', help: 'Expose tools from this MCP server to agents using this action.' } },
    { key: 'load_prompts', fallback: false, field: { label: 'Load prompts', kind: 'boolean', help: 'Load MCP server prompts in addition to any enabled tools.' } },
    { key: 'validate_tool_arguments', fallback: false, field: { label: 'Validate tool arguments', kind: 'boolean', help: 'Check arguments against cached tool input schemas before invocation.' } },
    {
        key: 'tool_result_policy', fallback: 'truncate', field: {
            label: 'Large-result policy', kind: 'select', options: [
                { value: 'truncate', label: 'Truncate results above the configured size limit' },
                { value: 'error_on_limit', label: 'Report an error instead of truncating' },
            ],
        },
    },
    {
        key: 'allowed_tool_names', fallback: [], field: {
            label: 'Allowed tool names', kind: 'lines', max_items: 500,
            help: 'Original MCP tool names. An empty allowlist allows all server tools. Only add names the person gave or that discovery found.',
        },
    },
];

/** Every field Ask AI may read or set for the draft's current type. */
function describeType(draft: ActionConfiguration, definition: ActionTypeDefinition, context: ActionAssistContext): DescribedField[] {
    const described: DescribedField[] = [];
    const seen = new Set<string>(['/displayName', '/description', '/type']);
    const add = (field: EditorAssistField, source: FieldSource) => {
        if (seen.has(field.path) || !ACTION_PATH.test(field.path)) return;
        seen.add(field.path);
        described.push({ field, source });
    };
    if (!draft.type || draft.type === 'agent') return described;
    if (draft.type === 'openapi') {
        add({
            path: '/endpoint', label: 'Base URL', section: 'configuration', kind: 'text',
            help: 'The API base URL. The OpenAPI specification itself is uploaded or fetched by the person in the editor.',
        }, { kind: 'endpoint' });
        return described;
    }
    if (draft.type === 'mcp') {
        add({
            path: '/endpoint', label: 'MCP server endpoint', section: 'configuration', kind: 'text', required: true,
            help: 'A remote MCP server URL the person named, such as https://example.com/mcp.',
        }, { kind: 'endpoint' });
        for (const item of MCP_FIELDS) {
            add({ ...item.field, path: `/additionalFields/${item.key}`, section: 'configuration' },
                { kind: 'mcp', key: item.key, fallback: item.fallback });
        }
        return described;
    }
    const native = nativeActionDefinition(draft.type);
    for (const descriptor of native.fields) {
        if (descriptor.visible && !descriptor.visible(draft)) continue;
        const kind = nativeKind(descriptor);
        if (!kind || isSecret(draft, descriptor.path, context)) continue;
        add({
            path: descriptor.path, label: descriptor.label, section: 'configuration', kind,
            help: descriptor.help, required: descriptor.required,
            min: descriptor.min, max: descriptor.max, integer: descriptor.step === 1 || undefined,
            options: kind === 'select' ? descriptor.options?.filter(({ value }) => value).map(({ value, label }) => ({ value, label })) : undefined,
            read_only: descriptor.readOnly || undefined,
        }, { kind: 'native', descriptor });
    }
    if (native.capabilities) {
        add({
            path: native.capabilities.path, label: 'Allowed capabilities', section: 'configuration', kind: 'choices',
            max_items: native.capabilities.options.length,
            options: native.capabilities.options.map(({ key, label, description }) => ({ value: key, label, description })),
            help: 'What an agent can do through this action. Every capability not chosen is turned off.',
        }, { kind: 'capabilities', path: native.capabilities.path });
    }
    const schema = definition.additional_fields_schema;
    const resolved = resolveActionSchema(schema, schema);
    const covered = coveredPaths(draft);
    for (const [key, property] of Object.entries(resolved.properties ?? {})) {
        const path = `/additionalFields/${pointerPart(key)}`;
        if (covered.some((known) => path === known || path.startsWith(`${known}/`)) || isSecret(draft, path, context)) continue;
        const field = schemaField(key, property, schema, resolved.required?.includes(key) === true);
        if (field) add({ ...field, path, section: 'configuration' }, { kind: 'schema', schema: property });
    }
    const modes = actionAuthModes(draft.type, definition.allowed_auth_types);
    if (modes.length > 1) {
        add({
            path: '/auth/type', label: 'Authentication method', section: 'authentication', kind: 'select',
            options: modes.map(({ value, label }) => ({ value, label })),
            read_only: Boolean(draft.identity_id) || undefined,
            help: draft.identity_id
                ? 'A reusable identity signs this action in, so the method follows the identity.'
                : 'How the action signs in. The person enters any credentials the method needs.',
        }, { kind: 'auth' });
    }
    return described;
}

function stringList(value: unknown): string[] {
    if (Array.isArray(value)) return value.filter((item): item is string => typeof item === 'string');
    if (typeof value === 'string') return value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    return [];
}

function capabilityValues(draft: ActionConfiguration, path: string): string[] {
    const native = nativeActionDefinition(draft.type);
    const raw = actionValueAt(draft, path);
    const stored = isRecord(raw) ? raw : {};
    return (native.capabilities?.options ?? []).filter((capability) => {
        if (typeof stored[capability.key] === 'boolean') return stored[capability.key] === true;
        // Older SimpleChat actions stored one upload switch for every document format.
        if (draft.type === 'simplechat' && ['upload_word_document', 'upload_powerpoint_document'].includes(capability.key) &&
            typeof stored.upload_markdown_document === 'boolean') return stored.upload_markdown_document === true;
        return capability.defaultEnabled !== false;
    }).map(({ key }) => key);
}

function readValue(draft: ActionConfiguration, item: DescribedField): unknown {
    const { field, source } = item;
    switch (source.kind) {
        case 'capabilities':
            return capabilityValues(draft, source.path);
        case 'auth':
            return actionAuthMethod(draft) || null;
        case 'mcp': {
            const value = draft.additionalFields[source.key];
            if (field.kind === 'lines') return stringList(value);
            if (field.kind === 'boolean') return typeof value === 'boolean' ? value : source.fallback;
            return actionText(value) || source.fallback;
        }
        case 'endpoint':
            return actionText(draft.endpoint);
        default:
            break;
    }
    const value = displayedActionValue(draft, field.path);
    switch (field.kind) {
        case 'boolean': {
            if (typeof value === 'boolean') return value;
            const defaults = actionValueAt(nativeActionDefinition(draft.type).defaults, field.path);
            if (source.kind === 'schema') return resolveActionSchema(source.schema).default === true;
            return defaults === true;
        }
        case 'number':
            return typeof value === 'number' && Number.isFinite(value) ? value : null;
        case 'select':
            return value === undefined || value === null || value === '' ? null : String(value);
        case 'lines':
            return stringList(value);
        default:
            return typeof value === 'string' ? value : value === undefined || value === null ? '' : String(value);
    }
}

function typeFields(draft: ActionConfiguration, context: ActionAssistContext): DescribedField[] {
    if (!draft.type) return [];
    return describeType(draft, definitionFor(draft.type, context) ?? fallbackDefinition(draft), context);
}

/** Every value the assistant may read, keyed by path. */
export function actionAssistValues(draft: ActionConfiguration, context: ActionAssistContext): EditorAssistValues {
    const values: Record<string, unknown> = {
        '/displayName': draft.displayName ?? draft.name ?? '',
        '/description': draft.description ?? '',
        '/type': draft.type || null,
    };
    for (const item of typeFields(draft, context)) values[item.field.path] = readValue(draft, item);
    return values;
}

/** The draft as Ask AI sees it. */
export function buildActionAssistView(draft: ActionConfiguration, context: ActionAssistContext): EditorAssistView {
    const types = [...context.catalogue];
    const typeOptions = types.map((definition) => ({
        value: definition.type, label: definition.display,
        description: definition.description ? definition.description.slice(0, 900) : undefined,
    }));
    if (draft.type && !definitionFor(draft.type, context)) {
        typeOptions.push({ value: draft.type, label: `${actionTypeLabel(draft.type)} (existing)`, description: undefined });
    }
    const fields: EditorAssistField[] = [
        {
            path: '/displayName', label: 'Action name', section: 'identity', kind: 'text', required: true,
            max_length: DISPLAY_NAME_LIMIT, help: 'The name agents and people see for this action.',
        },
        {
            path: '/description', label: 'Description', section: 'identity', kind: 'textarea',
            max_length: DESCRIPTION_LIMIT, help: 'What this action does and when an agent should use it.',
        },
        {
            path: '/type', label: 'Action type', section: 'identity', kind: 'select', required: true, options: typeOptions,
            help: 'The kind of connector. Changing it switches configuration and authentication to that type; the previous type is kept in the draft if the person switches back.',
        },
    ];
    const variants: Record<string, readonly EditorAssistField[]> = {};
    for (const definition of types) {
        // Each type is described as it would look after switching to it, so visibility rules hold.
        const simulated = definition.type === draft.type ? draft : changeActionType(draft, definition);
        variants[definition.type] = describeType(simulated, definition, context).map(({ field }) => field);
    }
    if (draft.type && !Object.hasOwn(variants, draft.type)) {
        variants[draft.type] = typeFields(draft, context).map(({ field }) => field);
    }
    const notes = [
        'Keys, passwords, tokens, connection strings and reusable identities are never shared with Ask AI. The person enters them in Authentication.',
        'Connection tests, tool discovery and OpenAPI specification uploads are commands the person runs in the editor.',
    ];
    if (!types.length) notes.push('No action types are available to this workspace, so the type cannot change.');
    if (draft.type && !definitionFor(draft.type, context)) {
        notes.push("This action's type is no longer offered to this workspace. Choose a permitted type before saving.");
    }
    if (draft.type === 'agent') notes.push('A Call agent action picks its target agent in the editor; only its name and description can change here.');
    return {
        sections: ACTION_ASSIST_SECTIONS,
        fields,
        values: actionAssistValues(draft, context),
        variant: { path: '/type', fields: variants },
        notes,
    };
}

function writeValue(draft: ActionConfiguration, item: DescribedField, value: unknown): ActionConfiguration | null {
    const { field, source } = item;
    if (field.read_only) return null;
    switch (source.kind) {
        case 'capabilities': {
            if (!Array.isArray(value)) return null;
            const chosen = new Set(stringList(value));
            const options = nativeActionDefinition(draft.type).capabilities?.options ?? [];
            if ([...chosen].some((key) => !options.some((option) => option.key === key))) return null;
            const raw = actionValueAt(draft, source.path);
            const next = { ...(isRecord(raw) ? raw : {}) };
            for (const option of options) next[option.key] = chosen.has(option.key);
            return changeActionField(draft, source.path, next);
        }
        case 'auth':
            // Applied by applyActionAssistPatch, which knows the type's allowed methods.
            return null;
        case 'mcp': {
            const next = field.kind === 'lines' ? [...new Set(stringList(value))]
                : field.kind === 'boolean' ? value
                    : value === null ? source.fallback : value;
            if (field.kind === 'boolean' && typeof next !== 'boolean') return null;
            if (field.kind === 'select' && !field.options?.some((option) => option.value === next)) return null;
            return { ...draft, additionalFields: { ...draft.additionalFields, [source.key]: next } };
        }
        case 'endpoint':
            return changeActionField(draft, '/endpoint', typeof value === 'string' ? value.trim() : '');
        default:
            break;
    }
    switch (field.kind) {
        case 'boolean':
            return typeof value === 'boolean' ? changeActionField(draft, field.path, value) : null;
        case 'number':
            if (value === null) return changeActionField(draft, field.path, undefined);
            if (typeof value !== 'number' || !Number.isFinite(value) || (field.integer && !Number.isInteger(value))) return null;
            return changeActionField(draft, field.path, value);
        case 'select':
            if (value === null || value === '') return changeActionField(draft, field.path, undefined);
            if (typeof value !== 'string' || !field.options?.some((option) => option.value === value)) return null;
            return changeActionField(draft, field.path, value);
        case 'lines':
            if (value === null) return changeActionField(draft, field.path, []);
            if (!Array.isArray(value)) return null;
            return changeActionField(draft, field.path, [...new Set(stringList(value))]);
        default:
            if (value === null) return changeActionField(draft, field.path, field.path.startsWith('/additionalFields/') ? undefined : '');
            return typeof value === 'string' ? changeActionField(draft, field.path, value) : null;
    }
}

function sameValue(current: unknown, value: unknown, kind: EditorAssistFieldKind): boolean {
    if (kind === 'choices' && Array.isArray(current) && Array.isArray(value)) {
        return JSON.stringify([...current].sort()) === JSON.stringify([...value].sort());
    }
    return JSON.stringify(current ?? null) === JSON.stringify(value ?? null);
}

/** The draft with no type, keeping the current type's configuration for a later switch back. */
function clearActionType(draft: ActionConfiguration): ActionConfiguration {
    const previous = isRecord(draft._actionTypeConfigurations) ? draft._actionTypeConfigurations : {};
    return {
        ...draft,
        type: '', endpoint: '', auth: { type: 'NoAuth' }, identity_id: '', additionalFields: {},
        _openApiSourceDraft: undefined, _sqlConnectionMethod: undefined,
        _actionTypeConfigurations: {
            ...previous,
            [draft.type]: {
                endpoint: draft.endpoint, auth: draft.auth, identity_id: draft.identity_id ?? '',
                additionalFields: draft.additionalFields,
                ...(draft._openApiSourceDraft ? { _openApiSourceDraft: draft._openApiSourceDraft } : {}),
                ...(draft._sqlConnectionMethod ? { _sqlConnectionMethod: draft._sqlConnectionMethod } : {}),
            },
        },
    };
}

/**
 * The draft with a patch applied, or null when the patch can't be applied, such as a type that
 * is no longer offered or a field the current type doesn't have. The variant path comes first in
 * a patch, so a type change is applied before that type's fields.
 */
export function applyActionAssistPatch(
    draft: ActionConfiguration,
    patch: Readonly<Record<string, unknown>>,
    context: ActionAssistContext,
): ActionConfiguration | null {
    let next = draft;
    const entries = Object.entries(patch);
    // Apply the type first even if the patch lists it later.
    entries.sort(([left], [right]) => Number(right === '/type') - Number(left === '/type'));
    for (const [path, value] of entries) {
        switch (path) {
            case '/displayName':
                if (typeof value !== 'string') return null;
                next = changeActionDisplayName(next, value, context.isNew);
                continue;
            case '/description':
                if (value !== null && typeof value !== 'string') return null;
                next = { ...next, description: actionText(value) };
                continue;
            case '/type': {
                if (value === next.type || ((value === null || value === '') && !next.type)) continue;
                if (value === null || value === '') {
                    // Only undo sends this: a new draft goes back to having no type.
                    next = clearActionType(next);
                    continue;
                }
                const definition = typeof value === 'string' ? definitionFor(value, context) : undefined;
                if (!definition) return null;
                next = changeActionType(next, definition);
                continue;
            }
            default:
                break;
        }
        const item = typeFields(next, context).find(({ field }) => field.path === path);
        // Undo clears fields the turn added under another type; on this type they don't exist.
        if (!item && value === null) continue;
        if (!item) return null;
        // An unchanged value is a no-op, so undo can restore read-only or legacy values.
        if (sameValue(readValue(next, item), value, item.field.kind)) continue;
        if (item.source.kind === 'auth') {
            const definition = definitionFor(next.type, context) ?? fallbackDefinition(next);
            const choice = actionAuthModes(next.type, definition.allowed_auth_types).find((mode) => mode.value === value);
            if (!choice || item.field.read_only) return null;
            next = changeActionAuth(next, choice);
            continue;
        }
        const updated = writeValue(next, item, value);
        if (!updated) return null;
        next = updated;
    }
    return next;
}
