// identityFields.ts
// The field rules shared by the group identity editor, kept out of the renderer so they can be
// tested without a DOM.
//
// A workspace identity is a saved credential: a name, the SimpleChat capabilities that may use it
// (file sync, actions), an authentication method, and the credential material for that method.
// The classic editor (static/js/workspace/workspace-identities.js) is the source of truth for
// which auth types each capability allows, how the "Used For" selection maps onto provider,
// source types and usage contexts, and how the write payload is shaped. This module mirrors that
// exactly so a group identity authored here is byte-compatible with one authored in classic.
//
// Secrets are never returned to the browser: the server sends password_stored / secret_stored
// booleans instead. The secret field therefore opens blank on an edit, and a blank secret on save
// means "keep the stored value" — a stored secret can be replaced or the auth type changed, but it
// cannot be blanked out through this form.

import type { WorkspaceIdentity } from './types';
import type { IdentityWrite } from './identityWorkbench';
import type { RebaseField } from './rebaseDraft';

/**
 * The editable fields the conflict rebase considers, over an {@link IdentityDraft}. `secretStored`
 * reflects the server's stored-secret flag and is adopted from the reload; the secret itself is
 * marked so a typed value is kept and a blank input adopts the reloaded stored state without the
 * value ever being compared or named.
 */
export const IDENTITY_REBASE_FIELDS: RebaseField[] = [
    { path: 'name', label: 'Name' },
    { path: 'description', label: 'Description' },
    { path: 'capabilities', label: 'Used for' },
    { path: 'credentials.authType', label: 'Authentication method' },
    { path: 'credentials.username', label: 'Username' },
    { path: 'credentials.domain', label: 'Domain' },
    { path: 'credentials.clientId', label: 'Client ID' },
    { path: 'credentials.managedIdentityClientId', label: 'Managed identity client ID' },
    { path: 'secretStored', label: 'Stored secret' },
    { path: 'credentials.secret', label: 'Secret', secret: true },
];

export interface CapabilityConfig {
    value: string;
    label: string;
    help: string;
    provider: string;
    sourceTypes: string[];
    usageContexts: string[];
    authTypes: string[];
}

/**
 * The capability configurations, mirroring `capabilityConfigs` in the classic editor. Group
 * identities support file sync and actions (§10: usage_contexts values are "file_sync" and
 * "action"); the model endpoint capability stays personal/admin, so it is not offered here.
 */
export const CAPABILITY_CONFIGS: Record<string, CapabilityConfig> = {
    file_sync: {
        value: 'file_sync',
        label: 'File Sync',
        help: 'Use this identity for File Sync sources, including SMB, Azure Files, Azure Blob Storage, and admin-approved cloud drive connectors.',
        provider: 'smb',
        sourceTypes: ['smb', 'azure_files', 'azure_blob', 'onedrive', 'google_drive', 'google_shared_drive'],
        usageContexts: ['file_sync'],
        authTypes: ['username_password', 'anonymous', 'managed_identity', 'client_secret', 'connection_string'],
    },
    action: {
        value: 'action',
        label: 'Actions',
        help: 'Use this identity for tools and plugin-style actions that agents or workflows call.',
        provider: 'action',
        sourceTypes: ['action'],
        usageContexts: ['action'],
        authTypes: ['api_key', 'bearer_token', 'client_secret', 'connection_string', 'username_password', 'managed_identity'],
    },
};

/** The capabilities offered in a group identity editor, in display order. */
export const GROUP_IDENTITY_CAPABILITIES = ['file_sync', 'action'] as const;

export const AUTH_TYPE_LABELS: Record<string, string> = {
    anonymous: 'Anonymous',
    api_key: 'API key',
    bearer_token: 'Bearer token',
    client_secret: 'Client secret',
    connection_string: 'Connection string',
    managed_identity: 'Managed identity',
    username_password: 'Username and password',
};

export function authTypeLabel(authType: unknown): string {
    const raw = String(authType ?? '').trim();
    return AUTH_TYPE_LABELS[raw] ?? (raw ? raw.replace(/[_-]+/g, ' ') : 'Unknown');
}

function capabilityConfig(value: string): CapabilityConfig {
    return CAPABILITY_CONFIGS[value] ?? CAPABILITY_CONFIGS.action;
}

/**
 * The auth types permitted by a set of capabilities, in the order they first appear across the
 * selected capabilities. Mirrors `getAllowedAuthTypes`: it falls back to username_password so a
 * form always has at least one method.
 */
export function allowedAuthTypes(capabilities: string[]): string[] {
    const authTypes: string[] = [];
    const selected = capabilities.length ? capabilities : ['action'];
    selected.forEach((capability) => {
        capabilityConfig(capability).authTypes.forEach((authType) => {
            if (!authTypes.includes(authType)) {
                authTypes.push(authType);
            }
        });
    });
    return authTypes.length ? authTypes : ['username_password'];
}

/** The provider, source types and usage contexts a capability selection maps onto. */
export function capabilityPayload(capabilities: string[]): {
    provider: string;
    sourceTypes: string[];
    usageContexts: string[];
} {
    const selected = capabilities.length ? capabilities : ['action'];
    const usageContexts: string[] = [];
    const sourceTypes: string[] = [];
    selected.forEach((capability) => {
        const config = capabilityConfig(capability);
        config.usageContexts.forEach((usage) => {
            if (!usageContexts.includes(usage)) {
                usageContexts.push(usage);
            }
        });
        config.sourceTypes.forEach((sourceType) => {
            if (!sourceTypes.includes(sourceType)) {
                sourceTypes.push(sourceType);
            }
        });
    });
    return {
        provider: sourceTypes[0] || capabilityConfig(selected[0]).provider,
        sourceTypes,
        usageContexts,
    };
}

export const authUsesUsername = (authType: string): boolean => authType === 'username_password';
export const authUsesClientId = (authType: string): boolean => authType === 'client_secret';
/** The secret field is hidden only for methods that carry no stored secret. */
export const authUsesSecret = (authType: string): boolean =>
    authType !== 'anonymous' && authType !== 'managed_identity';

/** The label the secret field carries, reflecting whether a value is already stored server-side. */
export function secretFieldLabel(authType: string, stored: boolean): string {
    if (authType === 'username_password') {
        return stored ? 'Password (stored)' : 'Password';
    }
    if (authType === 'client_secret') {
        return stored ? 'Client secret (stored)' : 'Client secret';
    }
    return stored ? 'Secret (stored)' : 'Secret';
}

export interface IdentityCredentialsDraft {
    authType: string;
    username: string;
    domain: string;
    clientId: string;
    /**
     * A managed identity's user-assigned client ID. It has no visible field in this editor, so it is
     * carried through unchanged: read from the projection and sent back for a managed_identity save so
     * an API-set user-assigned identity is not silently cleared to the system-assigned one on edit.
     */
    managedIdentityClientId: string;
    /** Blank means "keep the stored value" on an edit; a value replaces it. */
    secret: string;
}

export interface IdentityDraft {
    id: string | null;
    name: string;
    description: string;
    capabilities: string[];
    credentials: IdentityCredentialsDraft;
    /** Whether the server holds a secret for this identity, so the form can say it is preserved. */
    secretStored: boolean;
}

export function emptyIdentityDraft(): IdentityDraft {
    return {
        id: null,
        name: '',
        description: '',
        capabilities: ['action'],
        credentials: { authType: 'api_key', username: '', domain: '', clientId: '', managedIdentityClientId: '', secret: '' },
        secretStored: false,
    };
}

function readCredentials(identity: WorkspaceIdentity): Record<string, unknown> {
    const credentials = identity.credentials;
    return credentials && typeof credentials === 'object' ? credentials as Record<string, unknown> : {};
}

/** The capabilities an identity already carries, derived from its server-normalized usage contexts. */
export function identityCapabilities(identity: WorkspaceIdentity): string[] {
    const usage = Array.isArray(identity.usage_contexts) ? identity.usage_contexts : [];
    const capabilities = GROUP_IDENTITY_CAPABILITIES.filter((capability) =>
        capabilityConfig(capability).usageContexts.some((context) => usage.includes(context)),
    );
    return capabilities.length ? [...capabilities] : ['action'];
}

/** Build an editor draft from an existing identity; the secret opens blank and is never populated. */
export function draftFromIdentity(identity: WorkspaceIdentity): IdentityDraft {
    const credentials = readCredentials(identity);
    const authType = String(credentials.auth_type ?? 'api_key');
    const secretStored = Boolean(credentials.secret_stored) || Boolean(credentials.password_stored);
    return {
        id: String(identity.id ?? ''),
        name: String(identity.name ?? ''),
        description: String(identity.description ?? ''),
        capabilities: identityCapabilities(identity),
        credentials: {
            authType,
            username: String(credentials.username ?? ''),
            domain: String(credentials.domain ?? ''),
            clientId: String(credentials.identity ?? ''),
            managedIdentityClientId: String(credentials.managed_identity_client_id ?? ''),
            secret: '',
        },
        secretStored,
    };
}

function buildCredentialsWrite(credentials: IdentityCredentialsDraft): Record<string, unknown> {
    const usesClientSecret = credentials.authType === 'client_secret';
    const clientId = usesClientSecret ? credentials.clientId.trim() : '';
    const write: Record<string, unknown> = {
        auth_type: credentials.authType,
        username: credentials.username.trim(),
        domain: credentials.domain.trim(),
        identity: clientId,
        client_id: clientId,
    };
    if (credentials.authType === 'managed_identity') {
        // No visible field carries it, so round-trip the stored user-assigned client ID. The
        // normalizer reads managed_identity_client_id ahead of the blank client_id above, so a save
        // that never touched it keeps it rather than falling back to the system-assigned identity.
        write.managed_identity_client_id = credentials.managedIdentityClientId.trim();
    }
    if (credentials.authType === 'username_password') {
        write.password = credentials.secret;
    } else {
        write.secret = credentials.secret;
    }
    return write;
}

/** The strict write body the native group identity routes accept, shaped exactly as classic sends it. */
export function buildIdentityWrite(draft: IdentityDraft): IdentityWrite {
    const payload = capabilityPayload(draft.capabilities);
    return {
        name: draft.name.trim(),
        description: draft.description.trim(),
        provider: payload.provider,
        source_type: payload.provider,
        usage_contexts: payload.usageContexts,
        supported_source_types: payload.sourceTypes,
        credentials: buildCredentialsWrite(draft.credentials),
    };
}

/** A one-line description of who an identity signs in as, for a list row subtitle. */
export function identityPrincipalText(identity: WorkspaceIdentity): string {
    const credentials = readCredentials(identity);
    const username = String(credentials.username ?? '');
    if (username) {
        const domain = String(credentials.domain ?? '');
        return domain ? `${domain}\\${username}` : username;
    }
    if (credentials.auth_type === 'managed_identity') {
        return 'Managed identity';
    }
    const clientIdentity = String(credentials.identity ?? '');
    if (clientIdentity) {
        return clientIdentity;
    }
    if (credentials.secret_stored) {
        return 'Stored secret';
    }
    if (credentials.password_stored) {
        return 'Stored password';
    }
    return String(identity.description ?? '');
}

/** The capability labels an identity carries, for a list row badge. */
export function identityCapabilityLabels(identity: WorkspaceIdentity): string[] {
    return identityCapabilities(identity).map((capability) => capabilityConfig(capability).label);
}

/** The auth type an identity currently uses, for a list row badge. */
export function identityAuthType(identity: WorkspaceIdentity): string {
    const credentials = readCredentials(identity);
    return String(credentials.auth_type ?? '');
}
