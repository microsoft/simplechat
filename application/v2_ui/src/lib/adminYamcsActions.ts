// adminYamcsActions.ts
// Admin resources use the existing global API, never the personal editor's write/test APIs.

import { api } from './apiClient';
import {
    EDITOR_SECRET_MASK, buildEditorWrite, isRecord, pointerPart, sameEditorValue,
    type ActionConfiguration, type ActionTypeDefinition, type AuthoringResource,
} from './workspaceAuthoring';
import { actionForSave, actionText, actionValueAt, validateActionDraft } from './workspaceActionLogic';
import type { ActionIdentity } from './workspaceActionTypes';

export const ADMIN_YAMCS_SCOPE = 'global' as const;
export const LEGACY_ACTION_SECRET_MASK = 'Stored_In_KeyVault';
const root = '/api/admin/plugins';

export function adminYamcsResource(value: unknown): AuthoringResource<ActionConfiguration> {
    if (!isRecord(value) || value.type !== 'yamcs' || !actionText(value.name)) throw new Error('A saved global Yamcs action is required.');
    const secretPaths: string[] = [];
    const mask = (item: unknown, path = ''): unknown => {
        if (typeof item === 'string' && item && (item === LEGACY_ACTION_SECRET_MASK || item === EDITOR_SECRET_MASK ||
            path === '/auth/key' || /(?:password|secret|token|api_key|auth_key|__Secret)$/i.test(path))) {
            secretPaths.push(path);
            return EDITOR_SECRET_MASK;
        }
        if (Array.isArray(item)) return item.map((entry, index) => mask(entry, `${path}/${index}`));
        if (isRecord(item)) return Object.fromEntries(Object.entries(item)
            .filter(([key]) => !key.startsWith('_'))
            .map(([key, entry]) => [key, mask(entry, `${path}/${pointerPart(key)}`)]));
        return item;
    };
    const record = mask(value) as ActionConfiguration;
    record.id = actionText(record.id);
    record.name = actionText(record.name);
    record.displayName = actionText(record.displayName) || record.name;
    record.description = actionText(record.description) || actionText(isRecord(record.metadata) ? record.metadata.description : '');
    record.endpoint = actionText(record.endpoint) || actionText(isRecord(record.additionalFields) ? record.additionalFields.server_url : '');
    record.auth = isRecord(record.auth) ? { ...record.auth, type: actionText(record.auth.type) || 'NoAuth' } : { type: 'NoAuth' };
    record.additionalFields = isRecord(record.additionalFields) ? record.additionalFields : {};
    record.metadata = isRecord(record.metadata) ? record.metadata : {};
    return { record, revision: actionText(value._etag || value.last_updated), secret_paths: secretPaths, read_only: false };
}

export async function fetchAdminYamcsActions(signal?: AbortSignal): Promise<AuthoringResource<ActionConfiguration>[]> {
    const response = await api.get<unknown>(root, signal);
    if (!Array.isArray(response)) throw new Error('The global action list could not be read.');
    return response.filter((entry) => isRecord(entry) && entry.type === 'yamcs').map(adminYamcsResource);
}

export async function fetchAdminYamcsType(signal?: AbortSignal): Promise<ActionTypeDefinition> {
    const response = await api.get<unknown>(`${root}/types`, signal);
    const definition = Array.isArray(response) ? response.find((entry) => isRecord(entry) && entry.type === 'yamcs') : null;
    if (!isRecord(definition)) throw new Error('Yamcs is not available in the installed global action catalogue.');
    return {
        type: 'yamcs', display: actionText(definition.display) || 'Yamcs',
        description: actionText(definition.description),
        allowed_auth_types: Array.isArray(definition.allowed_auth_types)
            ? definition.allowed_auth_types.filter((entry): entry is string => typeof entry === 'string')
            : ['username_password', 'basic', 'key', 'NoAuth', 'identity'],
        additional_fields_schema: isRecord(definition.additional_fields_schema) ? definition.additional_fields_schema : {},
        metadata_schema: isRecord(definition.metadata_schema) ? definition.metadata_schema : {},
    };
}

export async function fetchAdminActionIdentities(signal?: AbortSignal): Promise<ActionIdentity[]> {
    const response = await api.get<{ identities?: unknown[] }>('/api/admin/workspace-identities/global/identities', signal);
    return (response.identities ?? []).flatMap((entry) => {
        if (!isRecord(entry) || !actionText(entry.id)) return [];
        const credentials = isRecord(entry.credentials) ? entry.credentials : {};
        return [{
            id: actionText(entry.id), name: actionText(entry.name),
            auth_type: actionText(entry.auth_type || credentials.auth_type),
            scope_type: 'global', scope_id: 'global',
        }];
    });
}

export function buildAdminYamcsPayload(
    draft: ActionConfiguration, original: AuthoringResource<ActionConfiguration> | null,
): Record<string, unknown> {
    if (draft.type !== 'yamcs' || draft.is_group || original && original.record.type !== 'yamcs') {
        throw new Error('This editor manages global Yamcs actions only.');
    }
    const manifest = buildEditorWrite(actionForSave(draft), null).updates;
    if (!original) delete manifest.id;
    const translate = (value: unknown, path = ''): unknown => {
        if (value === EDITOR_SECRET_MASK) {
            if (!original?.secret_paths.includes(path) || actionValueAt(original.record, path) !== EDITOR_SECRET_MASK) {
                throw new Error('A credential mask has no stored value. Reload the action or enter a replacement.');
            }
            return LEGACY_ACTION_SECRET_MASK;
        }
        if (Array.isArray(value)) return value.map((item, index) => translate(item, `${path}/${index}`));
        if (isRecord(value)) return Object.fromEntries(Object.entries(value).map(([key, item]) =>
            [key, translate(item, `${path}/${pointerPart(key)}`)]));
        return value;
    };
    return translate(manifest) as Record<string, unknown>;
}

export class SavedYamcsReloadError extends Error {}

export async function saveAdminYamcsAction(
    draft: ActionConfiguration, original: AuthoringResource<ActionConfiguration> | null,
    definition: ActionTypeDefinition, signal?: AbortSignal,
): Promise<AuthoringResource<ActionConfiguration>> {
    const errors = validateActionDraft(actionForSave(draft), definition, original, ADMIN_YAMCS_SCOPE);
    if (Object.keys(errors).length) throw new Error(Object.values(errors).join(' '));
    if (original) {
        const latest = (await fetchAdminYamcsActions(signal)).find((entry) => entry.record.id === original.record.id);
        if (!latest || !sameEditorValue(latest.record, original.record) ||
            original.revision && latest.revision && latest.revision !== original.revision) {
            throw new Error('This action changed since it was loaded. Reload its saved configuration before applying your changes.');
        }
    }
    const payload = buildAdminYamcsPayload(draft, original);
    if (original) await api.put(`${root}/${encodeURIComponent(original.record.name)}`, payload, signal);
    else await api.post(root, payload, signal);
    try {
        const actions = await fetchAdminYamcsActions(signal);
        const saved = actions.find((entry) => original
            ? entry.record.id === original.record.id : entry.record.name === draft.name);
        if (saved) return saved;
    } catch {
        // A failed reload must not turn an acknowledged create into another POST.
    }
    throw new SavedYamcsReloadError('The action was saved, but its current record could not be reloaded. Reload the list before editing or testing it.');
}

export const setAdminYamcsEnabled = (action: ActionConfiguration, enabled: boolean, signal?: AbortSignal) =>
    api.patch(`${root}/${encodeURIComponent(action.name)}/enabled`, { is_enabled: enabled }, signal);

export function globalYamcsActionReference(action: ActionConfiguration): string {
    if (action.type !== 'yamcs' || !action.id) throw new Error('Save this global Yamcs action before testing it.');
    const supplied = actionText(action.action_ref || action.ref);
    if (supplied.startsWith('action:v1:global:')) return supplied;
    // This is the catalog's v1 encoding of stable scope/id, never an action display name.
    const encoded = btoa(Array.from(new TextEncoder().encode(action.id), (byte) => String.fromCharCode(byte)).join(''))
        .replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
    return `action:v1:global:Z2xvYmFs:${encoded}`;
}

export async function testAdminYamcsAction(
    resource: AuthoringResource<ActionConfiguration>, signal?: AbortSignal,
): Promise<void> {
    const action = resource.record;
    if (action.type !== 'yamcs' || !action.id || action.is_enabled === false) throw new Error('Save and enable this global Yamcs action before testing.');
    const fields = action.additionalFields;
    // A saved-action connection test resolves the personal binding without claiming execution.
    const payload = action.credential_requirement
        ? { action_ref: globalYamcsActionReference(action) }
        : {
            ...buildAdminYamcsPayload(action, resource), action_scope: 'global',
            existing_plugin: { scope: 'global', id: action.id, name: action.name },
            server_url: action.endpoint, instance: fields.instance, auth_method: fields.auth_method,
            username: action.auth.identity,
            auth_key: action.auth.key === EDITOR_SECRET_MASK ? LEGACY_ACTION_SECRET_MASK : action.auth.key,
            tls_verify: fields.tls_verify ?? true, timeout: Math.min(Number(fields.timeout ?? 10), 30),
        };
    const result = await api.post<{ success?: boolean }>('/api/plugins/test-yamcs-connection', payload, signal);
    if (result.success !== true) throw new Error('The saved Yamcs connection could not be verified.');
}
