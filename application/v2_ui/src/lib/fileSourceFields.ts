// fileSourceFields.ts
// The field rules shared by the group file source editor, kept out of the renderer so they can be
// tested without a DOM.
//
// A file source points a workspace at somewhere its files already live: a network share, Azure
// Files, or Azure Blob Storage. The classic editor (static/js/workspace/workspace-file-sync.js) and
// functions_file_sync.py are the source of truth for which connection fields and auth methods each
// source type carries, and how the write payload is shaped. This module mirrors that so a group
// source authored here is byte-compatible with one authored in classic.
//
// Credentials come from one of two places: a saved group identity (recommended, and the only path
// the coordinator's brief emphasises) or entered directly. Secrets are never returned to the
// browser -- the server sends a placeholder and password_stored / secret_stored booleans instead --
// so a secret field opens blank on an edit and a blank secret on save keeps the stored value.

import type { FileSourceOptions, WorkspaceIdentity, WorkspaceSyncSource } from './types';
import type { FileSourceWrite } from './fileSourceWorkbench';

export const FILE_SOURCE_TYPE_SMB = 'smb';
export const FILE_SOURCE_TYPE_AZURE_FILES = 'azure_files';
export const FILE_SOURCE_TYPE_AZURE_BLOB = 'azure_blob';

/** One connection input rendered for a source type. */
export interface ConnectionField {
    key: keyof FileSourceConnectionDraft;
    label: string;
    placeholder: string;
    /** The draft key this field also serves as the browse root, when the type supports browsing. */
    browseRoot?: boolean;
}

export interface ConnectionDescriptor {
    fields: ConnectionField[];
    /** The auth methods this source type accepts for inline credentials, in display order. */
    authTypes: string[];
}

/**
 * The connection shape per source type, mirroring `_normalize_connection_payload` and
 * `FILE_SYNC_IDENTITY_AUTH_TYPES_BY_SOURCE`. Only the group-eligible storage types are modelled; a
 * type the options endpoint does not mark visible is never offered, so an unmodelled connector can
 * never be reached from here.
 */
export const CONNECTION_DESCRIPTORS: Record<string, ConnectionDescriptor> = {
    [FILE_SOURCE_TYPE_SMB]: {
        fields: [
            { key: 'uncPath', label: 'Network path', placeholder: '\\\\server\\share\\folder', browseRoot: true },
        ],
        authTypes: ['username_password', 'anonymous'],
    },
    [FILE_SOURCE_TYPE_AZURE_FILES]: {
        fields: [
            { key: 'accountUrl', label: 'File service URL', placeholder: 'https://account.file.core.windows.net' },
            { key: 'shareName', label: 'Share name', placeholder: 'share' },
            { key: 'directoryPath', label: 'Directory', placeholder: 'reports/2024', browseRoot: true },
        ],
        authTypes: ['managed_identity', 'client_secret', 'connection_string'],
    },
    [FILE_SOURCE_TYPE_AZURE_BLOB]: {
        fields: [
            { key: 'accountUrl', label: 'Blob service URL', placeholder: 'https://account.blob.core.windows.net' },
            { key: 'containerName', label: 'Container', placeholder: 'container' },
            { key: 'blobPrefix', label: 'Prefix', placeholder: 'reports/2024', browseRoot: true },
        ],
        authTypes: ['managed_identity', 'client_secret', 'connection_string'],
    },
};

export function connectionDescriptor(sourceType: string): ConnectionDescriptor {
    return CONNECTION_DESCRIPTORS[sourceType] ?? CONNECTION_DESCRIPTORS[FILE_SOURCE_TYPE_SMB];
}

export const AUTH_TYPE_LABELS: Record<string, string> = {
    anonymous: 'Anonymous',
    username_password: 'Username and password',
    managed_identity: 'Managed identity',
    client_secret: 'Service principal (client secret)',
    connection_string: 'Connection string or SAS',
};

export function authTypeLabel(authType: unknown): string {
    const raw = String(authType ?? '').trim();
    return AUTH_TYPE_LABELS[raw] ?? (raw ? raw.replace(/[_-]+/g, ' ') : 'Unknown');
}

export const authUsesUsername = (authType: string): boolean => authType === 'username_password';
export const authUsesClientId = (authType: string): boolean => authType === 'client_secret';
/** Managed identity and anonymous carry no stored secret; every other method does. */
export const authUsesSecret = (authType: string): boolean =>
    authType !== 'anonymous' && authType !== 'managed_identity';

export function secretFieldLabel(authType: string, stored: boolean): string {
    if (authType === 'username_password') {
        return stored ? 'Password (stored)' : 'Password';
    }
    if (authType === 'connection_string') {
        return stored ? 'Connection string (stored)' : 'Connection string';
    }
    return stored ? 'Client secret (stored)' : 'Client secret';
}

export interface FileSourceConnectionDraft {
    uncPath: string;
    accountUrl: string;
    shareName: string;
    directoryPath: string;
    containerName: string;
    blobPrefix: string;
}

export interface FileSourceCredentialsDraft {
    authType: string;
    username: string;
    domain: string;
    clientId: string;
    tenantId: string;
    /** Blank means "keep the stored value" on an edit; a value replaces it. */
    secret: string;
}

export type CredentialMode = 'identity' | 'inline';

export interface FileSourceDraft {
    id: string | null;
    name: string;
    sourceType: string;
    enabled: boolean;
    recursive: boolean;
    connection: FileSourceConnectionDraft;
    includePatterns: string;
    excludePatterns: string;
    allowedExtensions: string;
    scheduleEnabled: boolean;
    intervalMinutes: number;
    credentialMode: CredentialMode;
    identityId: string;
    credentials: FileSourceCredentialsDraft;
    /** Whether the server holds a secret for this source, so the form can say it is preserved. */
    secretStored: boolean;
}

function emptyConnection(): FileSourceConnectionDraft {
    return { uncPath: '', accountUrl: '', shareName: '', directoryPath: '', containerName: '', blobPrefix: '' };
}

function emptyCredentials(authType: string): FileSourceCredentialsDraft {
    return { authType, username: '', domain: '', clientId: '', tenantId: '', secret: '' };
}

/** A fresh draft for a new source of the given type, seeded with that type's first auth method. */
export function emptyFileSourceDraft(sourceType: string, minInterval: number): FileSourceDraft {
    const descriptor = connectionDescriptor(sourceType);
    return {
        id: null,
        name: '',
        sourceType,
        enabled: true,
        recursive: true,
        connection: emptyConnection(),
        includePatterns: '',
        excludePatterns: '',
        allowedExtensions: '',
        scheduleEnabled: false,
        intervalMinutes: Math.max(minInterval, 0) || 60,
        credentialMode: 'identity',
        identityId: '',
        credentials: emptyCredentials(descriptor.authTypes[0] ?? 'username_password'),
        secretStored: false,
    };
}

function readConnection(source: WorkspaceSyncSource): Record<string, unknown> {
    const connection = source.connection;
    return connection && typeof connection === 'object' ? connection as Record<string, unknown> : {};
}

function readFilters(source: WorkspaceSyncSource): Record<string, unknown> {
    const filters = source.filters;
    return filters && typeof filters === 'object' ? filters as Record<string, unknown> : {};
}

function readCredentials(source: WorkspaceSyncSource): Record<string, unknown> {
    const credentials = source.credentials;
    return credentials && typeof credentials === 'object' ? credentials as Record<string, unknown> : {};
}

function joinList(value: unknown): string {
    return Array.isArray(value) ? value.map((entry) => String(entry)).join(', ') : '';
}

/** Build an editor draft from an existing source; the secret opens blank and is never populated. */
export function draftFromSource(source: WorkspaceSyncSource, minInterval: number): FileSourceDraft {
    const sourceType = String(source.source_type ?? FILE_SOURCE_TYPE_SMB);
    const connection = readConnection(source);
    const filters = readFilters(source);
    const credentials = readCredentials(source);
    const schedule = source.schedule && typeof source.schedule === 'object' ? source.schedule : {};
    const identityId = String(source.identity_id ?? '');
    const secretStored = Boolean(credentials.secret_stored) || Boolean(credentials.password_stored);
    return {
        id: String(source.id ?? ''),
        name: String(source.name ?? ''),
        sourceType,
        enabled: source.enabled !== false,
        recursive: source.recursive !== false,
        connection: {
            uncPath: String(connection.unc_path ?? ''),
            accountUrl: String(connection.account_url ?? ''),
            shareName: String(connection.share_name ?? ''),
            directoryPath: String(connection.directory_path ?? ''),
            containerName: String(connection.container_name ?? ''),
            blobPrefix: String(connection.blob_prefix ?? ''),
        },
        includePatterns: joinList(filters.include_patterns),
        excludePatterns: joinList(filters.exclude_patterns),
        allowedExtensions: joinList(filters.allowed_extensions),
        scheduleEnabled: Boolean((schedule as Record<string, unknown>).enabled),
        intervalMinutes: Number((schedule as Record<string, unknown>).interval_minutes ?? minInterval) || minInterval || 60,
        credentialMode: identityId ? 'identity' : 'inline',
        identityId,
        credentials: {
            authType: String(credentials.auth_type ?? connectionDescriptor(sourceType).authTypes[0] ?? 'username_password'),
            username: String(credentials.username ?? ''),
            domain: String(credentials.domain ?? ''),
            clientId: String(credentials.identity ?? ''),
            tenantId: String(credentials.tenant_id ?? ''),
            secret: '',
        },
        secretStored,
    };
}

/** The per-type connection object the write carries, keyed as the backend normalizer expects. */
function buildConnection(draft: FileSourceDraft): Record<string, unknown> {
    const connection = draft.connection;
    if (draft.sourceType === FILE_SOURCE_TYPE_AZURE_FILES) {
        return {
            account_url: connection.accountUrl.trim(),
            share_name: connection.shareName.trim(),
            directory_path: connection.directoryPath.trim(),
        };
    }
    if (draft.sourceType === FILE_SOURCE_TYPE_AZURE_BLOB) {
        return {
            account_url: connection.accountUrl.trim(),
            container_name: connection.containerName.trim(),
            blob_prefix: connection.blobPrefix.trim(),
        };
    }
    return { unc_path: connection.uncPath.trim() };
}

/**
 * The credential object for inline mode, keyed as `_prepare_auth_payload` reads. A blank secret is
 * sent as-is: the backend keeps the stored value when the incoming secret is blank, so the form
 * cannot blank a stored secret, only replace it or change the auth method.
 */
function buildCredentials(credentials: FileSourceCredentialsDraft): Record<string, unknown> {
    const authType = credentials.authType;
    if (authType === 'anonymous') {
        return { auth_type: authType };
    }
    if (authType === 'managed_identity') {
        return { auth_type: authType, managed_identity_client_id: credentials.clientId.trim() };
    }
    if (authType === 'client_secret') {
        return {
            auth_type: authType,
            client_id: credentials.clientId.trim(),
            identity: credentials.clientId.trim(),
            tenant_id: credentials.tenantId.trim(),
            secret: credentials.secret,
        };
    }
    if (authType === 'connection_string') {
        return { auth_type: authType, connection_string: credentials.secret, secret: credentials.secret };
    }
    return {
        auth_type: authType,
        username: credentials.username.trim(),
        domain: credentials.domain.trim(),
        password: credentials.secret,
    };
}

/** Split a comma or newline separated field into a trimmed, non-empty list. */
export function splitList(value: string): string[] {
    return value
        .split(/[\n,]+/)
        .map((entry) => entry.trim())
        .filter((entry) => entry.length > 0);
}

/**
 * The classic source payload the native routes accept. Identity mode sends `identity_id` and no
 * inline credentials; inline mode sends `credentials` and clears any bound identity.
 */
export function buildFileSourceWrite(draft: FileSourceDraft): FileSourceWrite {
    const write: FileSourceWrite = {
        name: draft.name.trim(),
        source_type: draft.sourceType,
        enabled: draft.enabled,
        recursive: draft.recursive,
        connection: buildConnection(draft),
        filters: {
            include_patterns: splitList(draft.includePatterns),
            exclude_patterns: splitList(draft.excludePatterns),
            allowed_extensions: splitList(draft.allowedExtensions),
        },
        schedule: { enabled: draft.scheduleEnabled, interval_minutes: draft.intervalMinutes },
    };
    if (draft.credentialMode === 'identity') {
        write.identity_id = draft.identityId;
    } else {
        write.identity_id = '';
        write.credentials = buildCredentials(draft.credentials);
    }
    return write;
}

/** The remote path a source points at, for a list row subtitle. */
export function sourcePathText(source: WorkspaceSyncSource): string {
    const connection = readConnection(source);
    const sourceType = String(source.source_type ?? '');
    if (sourceType === FILE_SOURCE_TYPE_AZURE_FILES) {
        const share = String(connection.share_name ?? '');
        const directory = String(connection.directory_path ?? '');
        return [share, directory].filter(Boolean).join('/') || String(connection.account_url ?? '');
    }
    if (sourceType === FILE_SOURCE_TYPE_AZURE_BLOB) {
        const container = String(connection.container_name ?? '');
        const prefix = String(connection.blob_prefix ?? '');
        return [container, prefix].filter(Boolean).join('/') || String(connection.account_url ?? '');
    }
    return String(connection.unc_path ?? source.remote_path ?? '');
}

/** The browse root the current draft points at, used to seed a browse. */
export function draftBrowseRoot(draft: FileSourceDraft): string {
    if (draft.sourceType === FILE_SOURCE_TYPE_AZURE_FILES) {
        return draft.connection.directoryPath.trim();
    }
    if (draft.sourceType === FILE_SOURCE_TYPE_AZURE_BLOB) {
        return draft.connection.blobPrefix.trim();
    }
    return draft.connection.uncPath.trim();
}

/**
 * The group identities eligible for this source type, from the options' `eligible_identity_ids`.
 * An identity absent from the list is never offered, so the picker can never bind a credential the
 * server would reject at save.
 */
export function eligibleIdentities(
    identities: WorkspaceIdentity[], options: FileSourceOptions | null, sourceType: string,
): WorkspaceIdentity[] {
    if (!options) {
        return [];
    }
    const eligible = options.eligible_identity_ids?.[sourceType];
    if (!Array.isArray(eligible)) {
        return [];
    }
    const allowed = new Set(eligible.map((id) => String(id)));
    return identities.filter((identity) => allowed.has(String(identity.id ?? '')));
}

/** The source types offered for a new source: only those the options mark visible, in server order. */
export function visibleSourceTypes(options: FileSourceOptions | null): { value: string; label: string }[] {
    if (!options || !Array.isArray(options.source_types)) {
        return [];
    }
    return options.source_types
        .filter((type) => type && type.visible)
        .map((type) => ({ value: String(type.value), label: String(type.label ?? type.value) }));
}
