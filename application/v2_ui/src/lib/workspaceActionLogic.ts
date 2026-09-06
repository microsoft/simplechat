// workspaceActionLogic.ts

import {
    EDITOR_SECRET_MASK, editorName, isRecord, pointerPart, sameEditorValue,
    type ActionConfiguration, type ActionTypeDefinition, type AuthoringResource, type EditorSchema,
} from './workspaceAuthoring';
import { nativeActionDefinition, sqlConnectionMethod, usesDirectBlobConnectionString } from './workspaceActionRegistry';
import type { ActionIdentity } from './workspaceActionTypes';

export const ACTION_AUTHORING_UNAVAILABLE =
    'Creating and editing actions is not enabled for your account. You can still view available actions and delete your own where permitted.';

export function actionText(value: unknown): string {
    return typeof value === 'string' ? value : '';
}

export function actionTypeLabel(type: unknown): string {
    const raw = String(type ?? '').trim();
    if (!raw) return 'Unknown';
    if (raw === 'agent') return 'Call agent';
    const spaced = raw.replace(/[_-]+/g, ' ');
    return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function actionScope(action: ActionConfiguration): 'provided' | 'personal' {
    return action.is_global || action.read_only === true ? 'provided' : 'personal';
}

export function actionCanEdit(action: ActionConfiguration, canAuthor: boolean): boolean {
    return canAuthor && actionScope(action) === 'personal';
}

export function hasUsableActionRevision(resource: AuthoringResource<ActionConfiguration>, scope = 'personal'): boolean {
    const readOnly = scope === 'global' || resource.read_only || Boolean(resource.record.is_global);
    return typeof resource.revision === 'string' && (readOnly || resource.revision.trim().length > 0);
}

export function actionResourceKey(action: ActionConfiguration): string {
    return JSON.stringify([actionScope(action), action.id]);
}

export function actionDetailPath(action: ActionConfiguration): string {
    return `/workspace/actions/${encodeURIComponent(action.id)}${actionScope(action) === 'provided' ? '?scope=global' : ''}`;
}

export function filterAuthoringActions(
    actions: ActionConfiguration[],
    query: string,
    type: string,
    scope: string,
    catalogue: ActionTypeDefinition[] = [],
): ActionConfiguration[] {
    const labels = new Map(catalogue.map((definition) => [definition.type, definition.display]));
    const needle = query.trim().toLowerCase();
    return actions.filter((action) =>
        (!type || action.type === type) &&
        (!scope || actionScope(action) === scope) &&
        `${action.displayName} ${action.name} ${action.description} ${action.type} ${labels.get(action.type) || actionTypeLabel(action.type)}`
            .toLowerCase().includes(needle));
}

export function actionValueAt(value: unknown, pointer: string): unknown {
    if (!pointer) return value;
    return pointer.slice(1).split('/').reduce<unknown>((current, encoded) => {
        const key = encoded.replace(/~1/g, '/').replace(/~0/g, '~');
        if (Array.isArray(current)) return /^\d+$/.test(key) ? current[Number(key)] : undefined;
        return isRecord(current) && Object.hasOwn(current, key) ? current[key] : undefined;
    }, value);
}

export function actionArrayRemovalError(
    draft: ActionConfiguration, original: AuthoringResource<ActionConfiguration> | null, path: string, index: number,
): string | null {
    const items = actionValueAt(draft, path);
    if (!Array.isArray(items) || !Number.isInteger(index) || index < 0 || index >= items.length) {
        return 'This list entry is no longer available. Reload the configuration.';
    }
    const prefix = `${path}/`;
    const shiftsMaskedSecret = original?.secret_paths.some((secretPath) => {
        if (!secretPath.startsWith(prefix) || actionValueAt(draft, secretPath) !== EDITOR_SECRET_MASK) return false;
        const itemIndex = secretPath.slice(prefix.length).split('/')[0];
        return /^\d+$/.test(itemIndex) && Number(itemIndex) > index;
    });
    return shiftsMaskedSecret
        ? 'This removal would move stored credentials to different positions. Replace or clear stored secrets in later entries first.'
        : null;
}

export function actionHasStoredArraySecrets(
    draft: ActionConfiguration, original: AuthoringResource<ActionConfiguration> | null, rootPath: string,
): boolean {
    return original?.secret_paths.some((secretPath) => {
        if (actionValueAt(draft, secretPath) !== EDITOR_SECRET_MASK) return false;
        const parts = secretPath.slice(1).split('/');
        for (let length = 1; length < parts.length; length += 1) {
            const ancestor = `/${parts.slice(0, length).join('/')}`;
            if ((!rootPath || ancestor === rootPath || ancestor.startsWith(`${rootPath}/`)) &&
                Array.isArray(actionValueAt(draft, ancestor))) return true;
        }
        return false;
    }) ?? false;
}

export function displayedActionValue(draft: ActionConfiguration, pointer: string): unknown {
    const value = actionValueAt(draft, pointer);
    if (value !== undefined && value !== null && value !== '') return value;
    if (pointer === '/additionalFields/user' && draft.type === 'snowflake' && !draft.identity_id) return draft.auth.identity ?? value;
    if (pointer === '/additionalFields/schema' && ['databricks', 'databricks_table'].includes(draft.type)) {
        return draft.additionalFields.database ?? value;
    }
    if (draft.type === 'msgraph' && pointer.startsWith('/additionalFields/msgraph_')) {
        const key = pointer.slice('/additionalFields/msgraph_'.length);
        return draft.additionalFields[key] ?? actionValueAt(nativeActionDefinition(draft.type).defaults, pointer) ?? value;
    }
    if (pointer === '/endpoint') {
        const mirrors: Record<string, string> = {
            openapi: 'base_url', rocksdb: 'base_url', databricks: 'workspace_url',
            databricks_table: 'workspace_url', tableau: 'server_url', yamcs: 'server_url',
        };
        const alias = Object.hasOwn(mirrors, draft.type) ? mirrors[draft.type] : undefined;
        if (alias) return draft.additionalFields[alias] ?? value;
    }
    return value;
}

/** JSON pointers keep custom names containing dots, slashes, or prototype keys as data. */
export function withActionValue<T>(value: T, pointer: string, nextValue: unknown): T {
    const parts = pointer.slice(1).split('/').map((part) => part.replace(/~1/g, '/').replace(/~0/g, '~'));
    const update = (current: unknown, index: number): unknown => {
        if (index === parts.length) return nextValue;
        const key = parts[index];
        if (Array.isArray(current)) {
            if (!/^\d+$/.test(key)) throw new Error('An array field needs an index.');
            const next = current.slice();
            if (index === parts.length - 1 && nextValue === undefined) next.splice(Number(key), 1);
            else next[Number(key)] = update(current[Number(key)], index + 1);
            return next;
        }
        const record = isRecord(current) ? current : {};
        const entries = Object.entries(record).filter(([name]) => name !== key);
        const replacement = update(Object.hasOwn(record, key) ? record[key] : undefined, index + 1);
        if (replacement !== undefined) entries.push([key, replacement]);
        return Object.fromEntries(entries);
    };
    return update(value, 0) as T;
}

export function actionFieldError(errors: Record<string, string>, pointer: string): string | undefined {
    const dotted = pointer.slice(1).split('/').map((part) => part.replace(/~1/g, '/').replace(/~0/g, '~')).join('.');
    return errors[pointer] || errors[dotted];
}

export function expandActionFieldErrors(errors: Record<string, string>): Record<string, string> {
    const expanded = { ...errors };
    for (const [path, message] of Object.entries(errors)) {
        if (path.startsWith('/')) {
            expanded[path.slice(1).split('/').map((part) => part.replace(/~1/g, '/').replace(/~0/g, '~')).join('.')] = message;
        }
    }
    return expanded;
}

export function resolveActionSchema(schema: EditorSchema, root: EditorSchema = schema, depth = 0): EditorSchema {
    if (depth > 12) return schema;
    let resolved = schema;
    if (schema.$ref?.startsWith('#/')) {
        const target = actionValueAt(root, schema.$ref.slice(1));
        if (isRecord(target)) resolved = { ...resolveActionSchema(target as EditorSchema, root, depth + 1), ...schema, $ref: undefined };
    }
    if (resolved.allOf) {
        for (const part of resolved.allOf) {
            const sub = resolveActionSchema(part, root, depth + 1);
            // Conditional branches are left to the canonical server validator.
            if (sub.properties) resolved = { ...resolved, properties: { ...resolved.properties, ...sub.properties } };
            if (sub.required) resolved = { ...resolved, required: [...new Set([...(resolved.required ?? []), ...sub.required])] };
        }
    }
    return resolved;
}

export function validateActionSchema(
    value: unknown, schema: EditorSchema, path = '', root = schema, depth = 0,
): Record<string, string> {
    if (depth > 16 || value === EDITOR_SECRET_MASK) return {};
    const resolved = resolveActionSchema(schema, root);
    const errors: Record<string, string> = {};
    const label = resolved.title || path.split('/').at(-1)?.replaceAll('_', ' ') || 'Value';
    if (resolved.enum && !resolved.enum.some((item) => sameEditorValue(item, value))) {
        errors[path] = `${label}: choose one of the supported values.`;
    }
    if (Object.hasOwn(resolved, 'const') && !sameEditorValue(resolved.const, value)) {
        errors[path] = `${label}: must be ${String(resolved.const)}.`;
    }
    const types = Array.isArray(resolved.type) ? resolved.type : resolved.type ? [resolved.type] : [];
    const matches = (type: string) => type === 'object' ? isRecord(value) :
        type === 'array' ? Array.isArray(value) : type === 'null' ? value === null :
            type === 'integer' ? typeof value === 'number' && Number.isInteger(value) :
                type === 'number' ? typeof value === 'number' && Number.isFinite(value) : typeof value === type;
    if (value !== undefined && types.length && !types.some(matches)) {
        errors[path] = `${label}: enter ${types.join(' or ')}.`;
        return errors;
    }
    if (isRecord(value)) {
        for (const key of resolved.required ?? []) {
            if (!Object.hasOwn(value, key) || value[key] === undefined) {
                errors[`${path}/${pointerPart(key)}`] = `${resolved.properties?.[key]?.title || key.replaceAll('_', ' ')} is required.`;
            }
        }
        for (const [key, sub] of Object.entries(resolved.properties ?? {})) {
            if (Object.hasOwn(value, key) && value[key] !== undefined) {
                Object.assign(errors, validateActionSchema(value[key], sub, `${path}/${pointerPart(key)}`, root, depth + 1));
            }
        }
    } else if (Array.isArray(value)) {
        if (resolved.minItems !== undefined && value.length < resolved.minItems) errors[path] = `${label}: at least ${resolved.minItems} entries are required.`;
        if (resolved.maxItems !== undefined && value.length > resolved.maxItems) errors[path] = `${label}: no more than ${resolved.maxItems} entries are allowed.`;
        if (resolved.items) value.forEach((item, index) => Object.assign(errors, validateActionSchema(item, resolved.items!, `${path}/${index}`, root, depth + 1)));
    } else if (typeof value === 'string') {
        if (resolved.minLength !== undefined && value.length < resolved.minLength) errors[path] = `${label}: use at least ${resolved.minLength} characters.`;
        if (resolved.maxLength !== undefined && value.length > resolved.maxLength) errors[path] = `${label}: use no more than ${resolved.maxLength} characters.`;
        if (resolved.pattern && value) {
            try {
                if (!new RegExp(resolved.pattern).test(value)) errors[path] = `${label}: the value does not match the required format.`;
            } catch {
                // A server-specific pattern remains subject to server validation.
            }
        }
        if (resolved.format === 'email' && value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) errors[path] = `${label}: enter an email address.`;
    } else if (typeof value === 'number') {
        if (resolved.minimum !== undefined && value < resolved.minimum) errors[path] = `${label}: enter at least ${resolved.minimum}.`;
        if (resolved.maximum !== undefined && value > resolved.maximum) errors[path] = `${label}: enter no more than ${resolved.maximum}.`;
    }
    const conditional = resolved as EditorSchema & { if?: EditorSchema; then?: EditorSchema; else?: EditorSchema; not?: EditorSchema };
    for (const part of resolved.allOf ?? []) {
        Object.assign(errors, validateActionSchema(value, part, path, root, depth + 1));
    }
    const matchesSchema = (candidate: EditorSchema) => Object.keys(validateActionSchema(value, candidate, path, root, depth + 1)).length === 0;
    if (resolved.anyOf && !resolved.anyOf.some(matchesSchema)) errors[path] = `${label}: the value does not match a supported configuration.`;
    if (resolved.oneOf && resolved.oneOf.filter(matchesSchema).length !== 1) errors[path] = `${label}: choose exactly one supported configuration.`;
    if (conditional.not && matchesSchema(conditional.not)) errors[path] = `${label}: this combination of settings is not allowed.`;
    if (conditional.if) {
        const branch = matchesSchema(conditional.if) ? conditional.then : conditional.else;
        if (branch) Object.assign(errors, validateActionSchema(value, branch, path, root, depth + 1));
    }
    return errors;
}

/** Only explicit, type-correct defaults are values; descriptions and enum help never are. */
export function actionSchemaDefaults(schema: EditorSchema, root = schema, depth = 0): unknown {
    if (depth > 12) return undefined;
    const resolved = resolveActionSchema(schema, root);
    const defaultObjectAllowed = !isRecord(resolved.default) || resolved.additionalProperties !== false ||
        Object.keys(resolved.default).every((key) => Object.hasOwn(resolved.properties ?? {}, key));
    if (Object.hasOwn(resolved, 'default') && defaultObjectAllowed &&
        Object.keys(validateActionSchema(resolved.default, resolved, '', root)).length === 0) {
        return structuredClone(resolved.default);
    }
    if (resolved.properties) {
        const entries = Object.entries(resolved.properties).flatMap(([key, sub]) => {
            const value = actionSchemaDefaults(sub, root, depth + 1);
            return value === undefined ? [] : [[key, value] as const];
        });
        if (!entries.length) return undefined;
        const defaults = Object.fromEntries(entries);
        const applyConstraints = (constraint: EditorSchema, constraintDepth = 0) => {
            if (constraintDepth > 12) return;
            const conditional = constraint as EditorSchema & { if?: EditorSchema; then?: EditorSchema; else?: EditorSchema; not?: EditorSchema };
            for (const part of constraint.allOf ?? []) applyConstraints(part, constraintDepth + 1);
            if (conditional.if) {
                const conditionMatches = Object.keys(validateActionSchema(defaults, conditional.if, '', root)).length === 0;
                const branch = conditionMatches ? conditional.then : conditional.else;
                if (branch) applyConstraints(branch, constraintDepth + 1);
            }
            // Some installed schemas prohibit inactive option groups via `not.required`.
            // Do not materialize optional defaults that make that group active.
            if (conditional.not?.required && conditional.not.required.every((key) => Object.hasOwn(defaults, key))) {
                for (const key of conditional.not.required) {
                    if (!resolved.required?.includes(key)) delete defaults[key];
                }
            }
        };
        applyConstraints(resolved);
        return Object.keys(defaults).length ? defaults : undefined;
    }
    return undefined;
}

export function createActionDraft(): ActionConfiguration {
    return {
        id: '', name: '', displayName: '', description: '', type: '', endpoint: '',
        auth: { type: 'NoAuth' }, metadata: {}, additionalFields: {}, is_enabled: true,
    };
}

function configurationForType(definition: ActionTypeDefinition): Partial<ActionConfiguration> {
    const native = nativeActionDefinition(definition.type);
    const fields = actionSchemaDefaults(definition.additional_fields_schema);
    const metadata = actionSchemaDefaults(definition.metadata_schema);
    const auth = structuredClone(native.defaults?.auth ?? { type: definition.allowed_auth_types[0] || 'NoAuth' });
    if (definition.allowed_auth_types.length && !definition.allowed_auth_types.includes(auth.type)) {
        auth.type = definition.allowed_auth_types[0];
    }
    const capabilities = native.capabilities
        ? Object.fromEntries(native.capabilities.options.map(({ key, defaultEnabled }) => [key, defaultEnabled !== false]))
        : undefined;
    let initial = {
        ...structuredClone(native.defaults ?? {}),
        auth,
        additionalFields: { ...structuredClone(native.defaults?.additionalFields ?? {}), ...(isRecord(fields) ? fields : {}) },
        metadata: { ...structuredClone(native.defaults?.metadata ?? {}), ...(isRecord(metadata) ? metadata : {}) },
    };
    if (native.capabilities && capabilities) initial = withActionValue(initial, native.capabilities.path, capabilities);
    return initial;
}

export function changeActionType(draft: ActionConfiguration, definition: ActionTypeDefinition): ActionConfiguration {
    if (draft.type === definition.type) return draft;
    const previous = isRecord(draft._actionTypeConfigurations) ? draft._actionTypeConfigurations : {};
    const configurations = {
        ...previous,
        ...(draft.type ? { [draft.type]: {
            endpoint: draft.endpoint, auth: draft.auth, identity_id: draft.identity_id ?? '',
            additionalFields: draft.additionalFields,
            ...(draft._openApiSourceDraft ? { _openApiSourceDraft: draft._openApiSourceDraft } : {}),
            ...(draft._sqlConnectionMethod ? { _sqlConnectionMethod: draft._sqlConnectionMethod } : {}),
        } } : {}),
    };
    const existing = Object.hasOwn(configurations, definition.type) ? configurations[definition.type] : undefined;
    const initial = configurationForType(definition);
    const configuration = isRecord(existing) ? existing : initial;
    return {
        ...draft,
        ...configuration,
        type: definition.type,
        endpoint: actionText(configuration.endpoint),
        auth: isRecord(configuration.auth) ? configuration.auth as ActionConfiguration['auth'] : { type: 'NoAuth' },
        identity_id: actionText(configuration.identity_id),
        additionalFields: isRecord(configuration.additionalFields) ? structuredClone(configuration.additionalFields) : {},
        metadata: { ...(initial.metadata ?? {}), ...draft.metadata },
        _openApiSourceDraft: configuration._openApiSourceDraft,
        _sqlConnectionMethod: configuration._sqlConnectionMethod,
        _actionTypeConfigurations: configurations,
    };
}

export function changeActionDisplayName(draft: ActionConfiguration, value: string, isNew: boolean): ActionConfiguration {
    const derived = editorName(actionText(draft.displayName), 'action');
    return {
        ...draft, displayName: value,
        ...(isNew && (!draft.name || draft.name === derived) ? { name: value.trim() ? editorName(value, 'action') : '' } : {}),
    };
}

export function changeActionField(draft: ActionConfiguration, path: string, value: unknown): ActionConfiguration {
    let next = withActionValue(draft, path, value);
    const endpointMirrors: Record<string, string> = {
        openapi: 'base_url', rocksdb: 'base_url', databricks: 'workspace_url',
        databricks_table: 'workspace_url', tableau: 'server_url', yamcs: 'server_url',
    };
    if (path === '/endpoint' && Object.hasOwn(endpointMirrors, draft.type)) {
        next = withActionValue(next, `/additionalFields/${endpointMirrors[draft.type]}`, value);
    }
    if (path === '/additionalFields/user' && draft.type === 'snowflake' && !draft.identity_id) {
        next = withActionValue(next, '/auth/identity', value);
    }
    if (path === '/additionalFields/cloud' && draft.type === 'log_analytics' && value !== 'custom') {
        // This explicit cloud change removes incompatible custom overrides, not unrelated fields.
        next = withActionValue(next, '/additionalFields/authorityHost', undefined);
        next = withActionValue(next, '/additionalFields/endpointOverride', undefined);
        next.endpoint = value === 'usgovernment' ? 'https://api.loganalytics.us' : 'https://api.loganalytics.io';
    }
    if (path === '/auth/identity' && draft.type === 'tableau' && draft.additionalFields.auth_method === 'personal_access_token') {
        next = withActionValue(next, '/additionalFields/pat_name', value);
    }
    return next;
}

export function changeSqlConnectionMethod(draft: ActionConfiguration, method: 'parameters' | 'connection_string'): ActionConfiguration {
    const next = { ...draft, _sqlConnectionMethod: method };
    return method === 'parameters'
        ? withActionValue(next, '/additionalFields/connection_string', undefined)
        : next;
}

export interface ActionAuthMode { value: string; label: string; authType: string }
const mode = (value: string, label: string, authType = value): ActionAuthMode => ({ value, label, authType });
const AUTH_LABELS: Record<string, string> = {
    NoAuth: 'No authentication', key: 'API key', identity: 'Managed identity',
    user: 'Signed-in user', servicePrincipal: 'Service principal', connection_string: 'Connection string',
    username_password: 'Username and password', basic: 'Basic authentication',
};

export function actionAuthModes(type: string, allowed: string[]): ActionAuthMode[] {
    const sql = [
        mode('username_password', 'Username and password', 'user'),
        mode('managed_identity', 'Managed identity', 'identity'),
        mode('service_principal', 'Service principal', 'servicePrincipal'),
        mode('integrated', 'Integrated / Windows authentication', 'identity'),
        mode('connection_string_only', 'Credentials in connection string', 'identity'),
    ];
    const definitions: Record<string, ActionAuthMode[]> = {
        sql_query: sql, sql_schema: sql,
        databricks: [
            mode('pat', 'Personal access token', 'key'), mode('bearer', 'Bearer token', 'key'),
            mode('service_principal', 'Service principal', 'servicePrincipal'), mode('managed_identity', 'Managed identity', 'identity'),
        ],
        snowflake: [mode('password', 'Password', 'username_password'), mode('key_pair', 'PEM key pair', 'key'), mode('oauth', 'OAuth token', 'key')],
        tableau: [mode('personal_access_token', 'Personal access token', 'key'), mode('username_password', 'Username and password')],
        yamcs: [mode('username_password', 'Username and password'), mode('api_key', 'API key', 'key'), mode('bearer_token', 'Bearer token', 'key'), mode('none', 'No authentication', 'NoAuth')],
        rocksdb: [mode('none', 'No authentication', 'NoAuth'), mode('bearer', 'Bearer token', 'key'), mode('api_key', 'API key header', 'key')],
    };
    const nativeType = type === 'databricks_table' ? 'databricks' : type;
    const choices = Object.hasOwn(definitions, nativeType) ? definitions[nativeType] :
        (allowed.length ? allowed : ['NoAuth']).map((value) => mode(value, Object.hasOwn(AUTH_LABELS, value) ? AUTH_LABELS[value] : actionTypeLabel(value)));
    return choices.filter((choice) => !allowed.length || allowed.includes(choice.authType));
}

export function actionAuthMethod(draft: ActionConfiguration): string {
    if (draft.type === 'sql_query' || draft.type === 'sql_schema') {
        return actionText(draft.additionalFields.auth_type) ||
            (draft.auth.type === 'servicePrincipal' ? 'service_principal' : draft.auth.type === 'identity' ? 'managed_identity' : 'username_password');
    }
    if (draft.type === 'rocksdb') return actionText(draft.additionalFields.auth_scheme) || (draft.auth.type === 'key' ? 'bearer' : 'none');
    if (['databricks', 'databricks_table', 'snowflake', 'tableau', 'yamcs'].includes(draft.type)) {
        if (draft.additionalFields.auth_method) return actionText(draft.additionalFields.auth_method);
        if (draft.type === 'snowflake') return draft.auth.type === 'username_password' ? 'password' : 'key_pair';
        if (draft.type === 'tableau') return draft.auth.type === 'username_password' ? 'username_password' : 'personal_access_token';
        if (draft.type === 'yamcs') return draft.auth.type === 'NoAuth' ? 'none' : draft.auth.type === 'key' ? 'api_key' : 'username_password';
        return draft.auth.type === 'servicePrincipal' ? 'service_principal' : draft.auth.type === 'identity' ? 'managed_identity' : 'pat';
    }
    return draft.auth.type;
}

export function changeActionAuth(draft: ActionConfiguration, choice: ActionAuthMode): ActionConfiguration {
    const additionalFields = { ...draft.additionalFields };
    const sql = ['sql_query', 'sql_schema'].includes(draft.type);
    if (sql) additionalFields.auth_type = choice.value;
    else if (draft.type === 'rocksdb') additionalFields.auth_scheme = choice.value;
    else if (['databricks', 'databricks_table', 'snowflake', 'tableau', 'yamcs'].includes(draft.type)) additionalFields.auth_method = choice.value;
    const auth = { ...draft.auth, type: choice.authType };
    if (choice.authType === 'identity' && !draft.identity_id) {
        auth.identity = sql && choice.value !== 'managed_identity' ? '' : 'managed_identity';
    }
    return {
        ...draft, auth, additionalFields,
        ...(sql && choice.value === 'connection_string_only' ? { _sqlConnectionMethod: 'connection_string' } : {}),
    };
}

export function selectActionIdentity(draft: ActionConfiguration, identity: ActionIdentity | null): ActionConfiguration {
    const additionalFields = { ...draft.additionalFields };
    if (!identity) {
        delete additionalFields.identity_auth_type;
        delete additionalFields.identity_uses_connection_string;
        return { ...draft, identity_id: '', auth: { ...draft.auth, identity: '', type: 'NoAuth' }, additionalFields };
    }
    const allowed = nativeActionDefinition(draft.type).identityTypes;
    if (allowed && !allowed.includes(identity.auth_type)) throw new Error('This identity is not compatible with the action type.');
    additionalFields.identity_auth_type = identity.auth_type;
    if (['sql_query', 'sql_schema'].includes(draft.type)) {
        additionalFields.auth_type = identity.auth_type === 'connection_string' ? 'connection_string_only' : identity.auth_type;
        additionalFields.identity_uses_connection_string = identity.auth_type === 'connection_string';
    } else if (['databricks', 'databricks_table'].includes(draft.type)) {
        additionalFields.auth_method = identity.auth_type === 'managed_identity' ? 'managed_identity' : identity.auth_type === 'bearer_token' ? 'bearer' : 'pat';
    } else if (draft.type === 'snowflake') {
        additionalFields.auth_method = identity.auth_type === 'api_key' ? 'key_pair' : identity.auth_type === 'bearer_token' ? 'oauth' : 'password';
    } else if (draft.type === 'tableau') {
        additionalFields.auth_method = identity.auth_type === 'api_key' ? 'personal_access_token' : 'username_password';
    } else if (draft.type === 'yamcs') {
        additionalFields.auth_method = identity.auth_type;
    }
    return { ...draft, identity_id: identity.id, auth: { ...draft.auth, type: 'identity', identity: identity.id }, additionalFields };
}

export function deriveBlobEndpoint(connectionString: string): string {
    if (!connectionString || connectionString === EDITOR_SECRET_MASK) return '';
    const parts = Object.fromEntries(connectionString.split(';').flatMap((segment) => {
        const index = segment.indexOf('=');
        return index < 0 ? [] : [[segment.slice(0, index).trim().toLowerCase(), segment.slice(index + 1).trim()]];
    }));
    if (parts.blobendpoint) return parts.blobendpoint.replace(/\/+$/, '');
    if (!parts.accountname) return '';
    return `${parts.defaultendpointsprotocol || 'https'}://${parts.accountname}.blob.${parts.endpointsuffix || 'core.windows.net'}`;
}

export function actionForSave(draft: ActionConfiguration): ActionConfiguration {
    let next = { ...draft, displayName: actionText(draft.displayName ?? draft.name).trim(), name: actionText(draft.name).trim() };
    if (!next.endpoint) next.endpoint = actionText(displayedActionValue(draft, '/endpoint'));
    if (draft.type === 'agent') next = { ...next, endpoint: 'internal://agent', auth: { type: 'user' } };
    if (draft.type === 'snowflake' && !draft.identity_id && !draft.auth.identity && draft.additionalFields.user) {
        next.auth = { ...draft.auth, identity: actionText(draft.additionalFields.user) };
    }
    if (usesDirectBlobConnectionString(draft)) {
        const derived = deriveBlobEndpoint(actionText(draft.auth.key));
        if (derived) next.endpoint = derived;
    }
    return next;
}

export function validateActionDraft(
    draft: ActionConfiguration, definition?: ActionTypeDefinition, original?: AuthoringResource<ActionConfiguration> | null,
): Record<string, string> {
    const errors: Record<string, string> = {};
    if (!actionText(draft.displayName ?? draft.name).trim()) errors['/displayName'] = 'Action name is required.';
    if (!/^[A-Za-z0-9_-]+$/.test(actionText(draft.name))) errors['/name'] = 'Machine name must contain only letters, numbers, underscores, or dashes.';
    if (!definition) errors['/type'] = 'Choose an action type available in this workspace.';
    if (definition && !draft.identity_id && definition.allowed_auth_types.length &&
        !definition.allowed_auth_types.includes(draft.auth.type)) {
        errors['/auth/type'] = 'Choose an authentication method supported by this action type.';
    }
    const native = nativeActionDefinition(draft.type);
    for (const descriptor of native.fields) {
        if (descriptor.visible && !descriptor.visible(draft)) continue;
        const value = actionValueAt(draft, descriptor.path);
        if (descriptor.required && (value === undefined || value === null || value === '')) errors[descriptor.path] = `${descriptor.label} is required.`;
        if (typeof value === 'number') {
            if (!Number.isFinite(value) || (descriptor.step === 1 && !Number.isInteger(value))) errors[descriptor.path] = `${descriptor.label}: enter a whole number.`;
            if (descriptor.min !== undefined && value < descriptor.min) errors[descriptor.path] = `${descriptor.label}: enter at least ${descriptor.min}.`;
            if (descriptor.max !== undefined && value > descriptor.max) errors[descriptor.path] = `${descriptor.label}: enter no more than ${descriptor.max}.`;
        }
        if (descriptor.kind === 'select' && value !== undefined && value !== '' && !descriptor.options?.some((item) => item.value === value)) {
            errors[descriptor.path] = `${descriptor.label}: choose a supported value.`;
        }
    }
    if (definition) {
        Object.assign(errors, validateActionSchema(draft.additionalFields, definition.additional_fields_schema, '/additionalFields'));
        Object.assign(errors, validateActionSchema(draft.metadata, definition.metadata_schema, '/metadata'));
    }
    const requireField = (path: string, label: string) => {
        const value = actionValueAt(draft, path);
        if (typeof value !== 'string' || !value.trim()) errors[path] = `${label} is required.`;
        if (value === EDITOR_SECRET_MASK && !original?.secret_paths.includes(path)) errors[path] = `${label} has no stored value to keep. Enter a value.`;
    };
    if (draft.type === 'agent') {
        const target = draft.additionalFields.target_agent;
        if (!isRecord(target) || !actionText(target.id) || !actionText(target.scope_id) || !['personal', 'group', 'global'].includes(actionText(target.scope_type))) {
            errors['/additionalFields/target_agent'] = 'Select an authorized target agent.';
        }
    } else if (!['openapi', 'mcp'].includes(draft.type) && !native.internal && !draft.identity_id) {
        const sql = ['sql_query', 'sql_schema'].includes(draft.type);
        const method = actionAuthMethod(draft);
        if (sql && method === 'connection_string_only' && sqlConnectionMethod(draft) !== 'connection_string') {
            errors['/auth/type'] = 'Credentials in a connection string require Connection string mode.';
        }
        if (sql && sqlConnectionMethod(draft) === 'connection_string') requireField('/additionalFields/connection_string', 'Connection string');
        else if (sql && method === 'username_password' && draft.additionalFields.database_type !== 'sqlite') {
            requireField('/additionalFields/username', 'Database username');
            requireField('/additionalFields/password', 'Database password');
        }
        if (draft.auth.type === 'servicePrincipal') {
            requireField('/auth/identity', 'Client ID'); requireField('/auth/tenantId', 'Tenant ID'); requireField('/auth/key', 'Client secret');
        } else if (['key', 'connection_string', 'username_password', 'basic'].includes(draft.auth.type)) {
            requireField('/auth/key', 'Credential');
            if (['username_password', 'basic'].includes(draft.auth.type)) requireField('/auth/identity', 'Username');
        }
        if (draft.type === 'tableau' && method === 'personal_access_token') requireField('/auth/identity', 'Personal access token name');
        if (draft.auth.type === 'identity' && !sql) requireField('/auth/identity', 'Managed identity');
    }
    if (draft.type === 'tableau' && draft.identity_id && draft.additionalFields.auth_method === 'personal_access_token') {
        requireField('/additionalFields/pat_name', 'Personal access token name');
    }
    if (draft.type === 'snowflake' && ['key_pair', 'oauth'].includes(actionAuthMethod(draft)) &&
        (!draft.auth.identity || draft.identity_id) && !draft.additionalFields.user) {
        errors['/additionalFields/user'] = 'Snowflake user is required for key-pair or OAuth authentication.';
    }
    if (native.capabilities) {
        const capabilities = actionValueAt(draft, native.capabilities.path);
        if (isRecord(capabilities) && native.capabilities.options.every((entry) => capabilities[entry.key] === false)) {
            errors[native.capabilities.path] = 'Allow at least one capability.';
        }
        if (draft.type === 'blob_storage') {
            const capabilities = isRecord(draft.additionalFields.blob_storage_capabilities) ? draft.additionalFields.blob_storage_capabilities : {};
            for (const [capability, field, defaultEnabled] of [
                ['read_file_content', 'blob_storage_read_file_types', true],
                ['upload_file_to_container', 'blob_storage_upload_file_types', false],
            ] as const) {
                const fileTypes = draft.additionalFields[field];
                if ((capabilities[capability] ?? defaultEnabled) && isRecord(fileTypes) && fileTypes.markdown === false) {
                    errors[`/additionalFields/${field}/markdown`] = 'Enable a supported file type or disable this capability.';
                }
            }
        }
    }
    const reminder = actionValueAt(draft, '/metadata/key_vault_secret_reminders/__all__');
    if (isRecord(reminder) && reminder.enabled) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(actionText(reminder.expires_on ?? reminder.expiration_date).slice(0, 10))) errors['/metadata/key_vault_secret_reminders/__all__/expires_on'] = 'Choose an expiration date.';
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(actionText(reminder.contact_email ?? reminder.reminder_email))) errors['/metadata/key_vault_secret_reminders/__all__/contact_email'] = 'Enter a valid reminder email.';
        if (!Number.isInteger(reminder.lead_days) || Number(reminder.lead_days) < 1 || Number(reminder.lead_days) > 3650) errors['/metadata/key_vault_secret_reminders/__all__/lead_days'] = 'Lead days must be between 1 and 3650.';
    }
    return errors;
}

export function actionApiErrors(payload: unknown): Record<string, string> {
    if (!isRecord(payload)) return {};
    const raw = payload.errors ?? payload.validation_errors ?? payload.field_errors;
    if (isRecord(raw)) return Object.fromEntries(Object.entries(raw).map(([key, value]) =>
        [key, Array.isArray(value) ? value.map(String).join(' ') : String(value)]));
    if (!Array.isArray(raw)) return {};
    return Object.fromEntries(raw.map((error, index) => {
        if (typeof error === 'string') {
            const match = error.match(/^([A-Za-z_][\w.[\]/~-]*)\s*:\s*(.*)$/s);
            return match ? [match[1], match[2]] : [`$${index}`, error];
        }
        if (isRecord(error)) {
            const path = Array.isArray(error.path) ? `/${error.path.map((part) => pointerPart(String(part))).join('/')}` : actionText(error.path ?? error.field);
            return [path || `$${index}`, actionText(error.message ?? error.error) || 'Invalid configuration.'];
        }
        return [`$${index}`, String(error)];
    }));
}
