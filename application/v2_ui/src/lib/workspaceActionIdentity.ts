// workspaceActionIdentity.ts

import { api } from './apiClient';
import { isActionIdentityAuthType, type ActionCredentialValues, type ActionIdentityAuthType } from './actionAuth';
import { isRecord } from './workspaceAuthoring';
import type { WorkspaceIdentity } from './types';

export function actionIdentityDetails(identity: WorkspaceIdentity) {
    const credentials = isRecord(identity.credentials) ? identity.credentials : {};
    const authType = identity.auth_type || credentials.auth_type;
    const usage = Array.isArray(identity.usage_contexts) ? identity.usage_contexts :
        identity.provider === 'smb' || identity.source_type === 'smb' ? ['file_sync'] : ['action'];
    return {
        authType,
        supported: isActionIdentityAuthType(authType) && usage.includes('action'),
        username: typeof credentials.username === 'string' ? credentials.username : '',
        stored: authType === 'username_password' ? credentials.password_stored === true : credentials.secret_stored === true,
    };
}

export function personalActionIdentityWrite(
    name: string, description: string, authType: ActionIdentityAuthType, values: ActionCredentialValues | undefined,
    original: WorkspaceIdentity | null,
): Record<string, unknown> {
    if (!name.trim() || name.trim().length > 120 || !isActionIdentityAuthType(authType)) throw new Error('Enter a supported identity name and credential type.');
    if (original && !actionIdentityDetails(original).supported) throw new Error('Use the classic editor for this identity type.');
    const sameType = original && actionIdentityDetails(original).authType === authType;
    const credentials = authType === 'username_password' && values && 'username' in values
        ? { auth_type: authType, username: values.username.trim(), ...(values.password ? { password: values.password } : {}) }
        : authType !== 'username_password' && values && 'secret' in values
            ? { auth_type: authType, ...(values.secret ? { secret: values.secret } : {}) }
            : null;
    if (!credentials || authType === 'username_password' && !('username' in credentials && credentials.username)) {
        throw new Error('Complete the required credential fields.');
    }
    if (!sameType || !original || !actionIdentityDetails(original).stored) {
        if (!(authType === 'username_password' ? 'password' in credentials : 'secret' in credentials)) throw new Error('A new credential is required.');
    }
    return {
        name: name.trim(), description: description.trim(), credentials,
        ...(!original ? { provider: 'generic', usage_contexts: ['action'] } : {}),
    };
}

export async function savePersonalActionIdentity(
    name: string, description: string, authType: ActionIdentityAuthType, values: ActionCredentialValues | undefined,
    original: WorkspaceIdentity | null, signal?: AbortSignal,
): Promise<WorkspaceIdentity> {
    const body = personalActionIdentityWrite(name, description, authType, values, original);
    const root = '/api/workspace-identities/personal/identities';
    const response = original
        ? await api.patch<{ identity: WorkspaceIdentity }>(`${root}/${encodeURIComponent(original.id)}`, body, signal)
        : await api.post<{ identity: WorkspaceIdentity }>(root, body, signal);
    if (!isRecord(response?.identity) || typeof response.identity.id !== 'string') throw new Error('The saved identity could not be read.');
    const credentials = isRecord(response.identity.credentials) ? response.identity.credentials : {};
    return {
        ...response.identity,
        credentials: {
            auth_type: credentials.auth_type,
            username: typeof credentials.username === 'string' ? credentials.username : '',
            password_stored: credentials.password_stored === true,
            secret_stored: credentials.secret_stored === true,
        },
    };
}
