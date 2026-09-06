// workspaceActionServices.ts

import { api } from './apiClient';
import { fetchIdentities } from './workspaceApi';
import { fetchAgentEditorOptions } from './workspaceAuthoringApi';
import {
    buildEditorWrite, EDITOR_SECRET_MASK, isRecord, pointerPart,
    type ActionConfiguration, type ActionTypeDefinition, type AuthoringResource,
} from './workspaceAuthoring';
import {
    actionAuthMethod, actionForSave, actionText, actionValueAt, validateActionDraft,
} from './workspaceActionLogic';
import { nativeActionDefinition, sqlConnectionMethod } from './workspaceActionRegistry';
import type { ActionIdentity } from './workspaceActionTypes';

export interface ActionEditorHints {
    canAuthor: boolean;
    storageEnabled: boolean;
    remindersEnabled: boolean;
    requireExpiration: boolean;
    reminderLeadDays: number;
    reminderEmail: string;
}

export async function fetchActionEditorHints(signal?: AbortSignal): Promise<ActionEditorHints> {
    const { settings } = await fetchAgentEditorOptions(signal);
    const days = Number(settings.key_vault_secret_expiration_default_lead_days);
    return {
        canAuthor: settings.allow_user_plugins === true,
        storageEnabled: settings.enable_key_vault_secret_storage === true,
        remindersEnabled: settings.enable_key_vault_secret_expiration_reminders === true,
        requireExpiration: settings.key_vault_secret_expiration_require_expiration === true,
        reminderLeadDays: Number.isInteger(days) && days >= 1 && days <= 3650 ? days : 30,
        reminderEmail: actionText(settings.key_vault_secret_expiration_default_contact_email),
    };
}

export async function fetchActionIdentities(signal?: AbortSignal): Promise<ActionIdentity[]> {
    const identities = await fetchIdentities(signal);
    return identities.flatMap((identity) => {
        const credentials = isRecord(identity.credentials) ? identity.credentials : {};
        const id = actionText(identity.id || identity.identity_id);
        if (!id) return [];
        return [{
            id,
            name: identity.name || 'Workspace identity',
            auth_type: actionText(identity.auth_type || credentials.auth_type).toLowerCase(),
            description: identity.description,
            scope_type: identity.scope_type,
            scope_id: identity.scope_id,
        }];
    });
}

function translateActionSecrets(
    draft: ActionConfiguration, original: AuthoringResource<ActionConfiguration> | null,
): Record<string, unknown> {
    const secretPaths = new Set(original?.secret_paths ?? []);
    const clearPaths = new Set(buildEditorWrite(draft, original).clear_secret_paths);
    const transform = (value: unknown, path = ''): unknown => {
        if (value === EDITOR_SECRET_MASK && secretPaths.has(path)) {
            if (actionValueAt(original?.record, path) !== EDITOR_SECRET_MASK) throw new Error('Stored credential state is inconsistent. Reload before testing.');
            return 'Stored_In_KeyVault';
        }
        if (value === EDITOR_SECRET_MASK &&
            (/^\/auth\//.test(path) || /(?:key|secret|password|token|credential|connection_string)$/i.test(path))) {
            throw new Error('A credential mask has no owned stored value. Enter a credential before testing.');
        }
        if (Array.isArray(value)) return value.map((item, index) => transform(item, `${path}/${index}`));
        if (isRecord(value)) return Object.fromEntries(Object.entries(value)
            .filter(([key, item]) => !(!path && key.startsWith('_')) && item !== undefined && !clearPaths.has(`${path}/${pointerPart(key)}`))
            .map(([key, item]) => [key, transform(item, `${path}/${pointerPart(key)}`)]));
        return value;
    };
    const manifest = buildEditorWrite(actionForSave(draft), null).updates;
    return transform(manifest) as Record<string, unknown>;
}

export function buildActionConnectionPayload(
    draft: ActionConfiguration, original: AuthoringResource<ActionConfiguration> | null,
): Record<string, unknown> {
    if (draft.type === 'agent' || original?.read_only || draft.is_global || draft.is_group) {
        throw new Error('This action cannot be connection-tested from My Workspace.');
    }
    if (original && !actionText(original.record.id).trim()) {
        throw new Error('Reload this action before testing: its stable owned ID is missing.');
    }
    const manifest = translateActionSecrets(draft, original);
    const fields = isRecord(manifest.additionalFields) ? manifest.additionalFields : {};
    const sql = ['sql_query', 'sql_schema'].includes(draft.type);
    const connectionMethod = sqlConnectionMethod(draft);
    let sqlAuthType = actionAuthMethod(draft);
    let auth = isRecord(manifest.auth) ? manifest.auth : {};
    if (draft.identity_id) {
        auth = { type: 'identity', identity: draft.identity_id };
    } else if (sql && connectionMethod === 'connection_string') {
        // A complete connection string controls auth; do not test stale parameter credentials.
        auth = { type: 'identity', identity: '' };
        sqlAuthType = 'connection_string_only';
        delete fields.username;
        delete fields.password;
    } else if (draft.auth.type === 'NoAuth' || (draft.auth.type === 'user' && !sql)) {
        auth = { type: draft.auth.type };
    } else if (draft.auth.type === 'identity') {
        auth = { type: 'identity', identity: sql && ['integrated', 'connection_string_only'].includes(sqlAuthType) ? '' : auth.identity };
    } else if (draft.auth.type === 'key' || draft.auth.type === 'connection_string') {
        auth = {
            type: draft.auth.type,
            ...(Object.hasOwn(auth, 'key') ? { key: auth.key } : {}),
            ...(['snowflake', 'tableau'].includes(draft.type) && Object.hasOwn(auth, 'identity') ? { identity: auth.identity } : {}),
        };
    } else if (['username_password', 'basic'].includes(draft.auth.type)) {
        auth = {
            type: draft.auth.type,
            ...(Object.hasOwn(auth, 'key') ? { key: auth.key } : {}),
            ...(Object.hasOwn(auth, 'identity') ? { identity: auth.identity } : {}),
        };
    }
    if (sql && connectionMethod === 'parameters') {
        delete fields.connection_string;
        if (draft.identity_id || sqlAuthType !== 'username_password' || fields.database_type === 'sqlite') {
            delete fields.username;
            delete fields.password;
            if (!draft.identity_id && fields.database_type === 'sqlite' && draft.auth.type === 'user') auth = { type: 'user' };
        } else if (draft.auth.type === 'user') {
            if (Object.hasOwn(draft.additionalFields, 'username')) delete auth.identity;
            if (Object.hasOwn(draft.additionalFields, 'password')) delete auth.key;
            delete auth.tenantId;
        }
    }
    if (draft.type !== 'snowflake' || actionAuthMethod(draft) !== 'key_pair') delete fields.private_key_passphrase;
    if (sql) {
        // Dedicated adapters prioritize canonical fields over their flat compatibility aliases.
        fields.auth_type = sqlAuthType;
        fields.connection_method = connectionMethod;
    }
    manifest.auth = auth;
    manifest.additionalFields = fields;
    const context = original ? { scope: 'personal', id: original.record.id, name: original.record.name } : undefined;
    const contextKey = ['sql_query', 'sql_schema', 'cosmos_query', 'yamcs', 'rocksdb'].includes(draft.type)
        ? 'existing_plugin' : 'plugin_context';
    const clearPaths = buildEditorWrite(draft, original).clear_secret_paths;
    // Legacy test endpoints may keep empty credentials. Fail before testing a cleared active secret.
    for (const path of clearPaths) {
        if ((path === '/auth/key' && !draft.identity_id && !['NoAuth', 'user', 'identity'].includes(String(auth.type))) ||
            (sql && path === '/additionalFields/password' && !draft.identity_id && fields.database_type !== 'sqlite' &&
                connectionMethod === 'parameters' && sqlAuthType === 'username_password') ||
            (sql && path === '/additionalFields/connection_string' && connectionMethod === 'connection_string' && !draft.identity_id)) {
            throw new Error('A required credential is marked for clearing. Enter a replacement before testing.');
        }
    }
    const common = {
        action_scope: 'personal', identity_id: draft.identity_id ?? '', clear_secret_paths: clearPaths,
        ...(context ? { [contextKey]: context } : {}),
    };
    if (sql) return {
        ...manifest, ...fields, ...common,
        auth_type: sqlAuthType, connection_method: connectionMethod,
        client_id: auth.identity, client_secret: auth.key, tenant_id: auth.tenantId,
        timeout: Math.min(Number(fields.timeout ?? 10), 15),
    };
    if (draft.type === 'cosmos_query') return {
        ...manifest, ...common, endpoint: manifest.endpoint, database_name: fields.database_name,
        container_name: fields.container_name, auth_type: auth.type, auth_key: auth.key,
        timeout: Math.min(Number(fields.timeout ?? 10), 30),
    };
    if (draft.type === 'rocksdb') return {
        ...manifest, ...common, base_url: manifest.endpoint, auth_scheme: fields.auth_scheme ?? 'none',
        api_key_header: fields.api_key_header ?? 'X-API-Key', auth_key: auth.key,
        timeout: Math.min(Number(fields.timeout ?? 10), 30),
    };
    if (draft.type === 'yamcs') return {
        ...manifest, ...common, server_url: manifest.endpoint, instance: fields.instance,
        auth_method: fields.auth_method, username: auth.identity, auth_key: auth.key,
        tls_verify: fields.tls_verify ?? true, timeout: Math.min(Number(fields.timeout ?? 10), 30),
    };
    return { ...manifest, ...common };
}

export function testWorkspaceAction(
    draft: ActionConfiguration, original: AuthoringResource<ActionConfiguration> | null,
    definition: ActionTypeDefinition, signal?: AbortSignal,
): Promise<unknown> {
    const path = nativeActionDefinition(draft.type).testPath;
    if (!path) return Promise.reject(new Error('This connector does not expose a connection-test command.'));
    const errors = validateActionDraft(actionForSave(draft), definition, original);
    for (const field of ['/name', '/displayName', '/type']) delete errors[field];
    if (Object.keys(errors).length) return Promise.reject(new Error(Object.values(errors).join(' ')));
    return api.post(path, buildActionConnectionPayload(draft, original), signal);
}

export function validateWorkspaceAction(
    draft: ActionConfiguration, original: AuthoringResource<ActionConfiguration> | null, signal?: AbortSignal,
): Promise<unknown> {
    const manifest = translateActionSecrets(draft, original);
    return api.post('/api/plugins/validate', manifest, signal);
}
