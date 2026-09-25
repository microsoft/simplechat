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
//
// Four more fields shape what a sync brings in and what it does with it, as in the classic editor:
// the folders and files to sync under the source root (`connection.selected_paths`), the tags every
// synced file gets (`filters.fixed_tags`), the tags taken from each file's folders
// (`filters.folder_tag_mode`), and what happens to the SimpleChat copy when its source file is
// deleted (`remote_delete_policy`). An edit opens them from the stored source and saves them back,
// so a save that changes something else leaves them exactly as they were. Their normalizers mirror
// `_normalize_selected_path` and `_safe_tag_from_text` in functions_file_sync.py, so the editor shows
// the value the server will store rather than one it would rewrite or refuse.

import type { FileSourceOptions, WorkspaceIdentity, WorkspaceSyncSource } from './types';
import type { FileSourceWrite } from './fileSourceWorkbench';
import type { RebaseField } from './rebaseDraft';
import { pyStrip } from './workflowAlerts';

/**
 * The editable fields the conflict rebase considers, over a {@link FileSourceDraft}. The connection
 * sub-fields are listed individually so a conflict names the exact input; unused ones stay blank on
 * both sides and never collide. `secretStored` is adopted from the reload, and the secret itself is
 * marked so a typed value is kept and a blank input adopts the reloaded stored state.
 */
export const FILE_SOURCE_REBASE_FIELDS: RebaseField[] = [
    { path: 'name', label: 'Name' },
    { path: 'sourceType', label: 'Type' },
    { path: 'enabled', label: 'Enabled' },
    { path: 'recursive', label: 'Include subfolders' },
    { path: 'connection.uncPath', label: 'Network path' },
    { path: 'connection.accountUrl', label: 'Service URL' },
    { path: 'connection.shareName', label: 'Share name' },
    { path: 'connection.directoryPath', label: 'Directory' },
    { path: 'connection.containerName', label: 'Container' },
    { path: 'connection.blobPrefix', label: 'Prefix' },
    { path: 'includePatterns', label: 'Include patterns' },
    { path: 'excludePatterns', label: 'Exclude patterns' },
    { path: 'allowedExtensions', label: 'Allowed extensions' },
    { path: 'selectedPaths', label: 'Selected folders and files' },
    { path: 'fixedTags', label: 'Fixed tags' },
    { path: 'folderTagMode', label: 'Folder tags' },
    { path: 'remoteDeletePolicy', label: 'When a source file is deleted' },
    { path: 'scheduleEnabled', label: 'Schedule' },
    { path: 'intervalMinutes', label: 'Sync interval' },
    { path: 'credentialMode', label: 'Credential source' },
    { path: 'identityId', label: 'Identity' },
    { path: 'credentials.authType', label: 'Authentication method' },
    { path: 'credentials.username', label: 'Username' },
    { path: 'credentials.domain', label: 'Domain' },
    { path: 'credentials.clientId', label: 'Client ID' },
    { path: 'credentials.tenantId', label: 'Tenant ID' },
    { path: 'secretStored', label: 'Stored secret' },
    { path: 'credentials.secret', label: 'Secret', secret: true },
];

export const FILE_SOURCE_TYPE_SMB = 'smb';
export const FILE_SOURCE_TYPE_AZURE_FILES = 'azure_files';
export const FILE_SOURCE_TYPE_AZURE_BLOB = 'azure_blob';

/**
 * How synced files are tagged from their folders, as `FILE_SYNC_FOLDER_TAG_MODES` defines them. The
 * server stores `parent` for a missing or unrecognised mode, so an editor opening either shows that.
 */
export const FOLDER_TAG_MODES = [
    { value: 'none', label: 'None' },
    { value: 'parent', label: 'The file\u2019s folder' },
    { value: 'full_path', label: 'Every folder in its path' },
] as const;
export const DEFAULT_FOLDER_TAG_MODE = 'parent';

/**
 * What a sync does with the SimpleChat copy when its source file is deleted, as
 * `FILE_SYNC_REMOTE_DELETE_POLICIES` defines it. The server stores `ignore` for a missing or
 * unrecognised policy, and it is the deployment's default for a new source.
 */
export const REMOTE_DELETE_POLICIES = [
    { value: 'ignore', label: 'Keep the SimpleChat copy' },
    { value: 'hard_delete', label: 'Delete the SimpleChat copy' },
] as const;
export const DEFAULT_REMOTE_DELETE_POLICY = 'ignore';

/** `_safe_tag_from_text` cuts a tag to this many characters, the limit `validate_tags` enforces. */
export const FIXED_TAG_MAX_LENGTH = 50;
/** `_normalize_selected_path` reads at most this many characters of a path. */
export const SELECTED_PATH_MAX_LENGTH = 2048;

export const SELECTED_PATH_INVALID =
    'A path can\u2019t have an empty, \u201c.\u201d or \u201c..\u201d folder name. Enter a folder or file under the source root.';
export const FIXED_TAG_INVALID = 'A tag needs at least one letter or number.';

/** One connection input rendered for a source type. */
export interface ConnectionField {
    key: keyof FileSourceConnectionDraft;
    label: string;
    placeholder: string;
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
            { key: 'uncPath', label: 'Network path', placeholder: '\\\\server\\share\\folder' },
        ],
        authTypes: ['username_password', 'anonymous'],
    },
    [FILE_SOURCE_TYPE_AZURE_FILES]: {
        fields: [
            { key: 'accountUrl', label: 'File service URL', placeholder: 'https://account.file.core.windows.net' },
            { key: 'shareName', label: 'Share name', placeholder: 'share' },
            { key: 'directoryPath', label: 'Directory', placeholder: 'reports/2024' },
        ],
        authTypes: ['managed_identity', 'client_secret', 'connection_string'],
    },
    [FILE_SOURCE_TYPE_AZURE_BLOB]: {
        fields: [
            { key: 'accountUrl', label: 'Blob service URL', placeholder: 'https://account.blob.core.windows.net' },
            { key: 'containerName', label: 'Container', placeholder: 'container' },
            { key: 'blobPrefix', label: 'Prefix', placeholder: 'reports/2024' },
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
    /** Folders and files under the source root to sync, in stored order; empty syncs the whole root. */
    selectedPaths: string[];
    includePatterns: string;
    excludePatterns: string;
    allowedExtensions: string;
    /** Tags every synced file gets, already normalized as the server stores them. */
    fixedTags: string[];
    folderTagMode: string;
    remoteDeletePolicy: string;
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
        selectedPaths: [],
        includePatterns: '',
        excludePatterns: '',
        allowedExtensions: '',
        fixedTags: [],
        folderTagMode: DEFAULT_FOLDER_TAG_MODE,
        remoteDeletePolicy: DEFAULT_REMOTE_DELETE_POLICY,
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

/** A stored list kept exactly as stored, so an untouched value is sent back unchanged. */
function storedList(value: unknown): string[] {
    return Array.isArray(value) ? value.map((entry) => String(entry)) : [];
}

/**
 * A stored choice, read the way the server normalizes one before storing it: trimmed and lowered,
 * with a missing or unrecognised value taking the server's fallback. The editor therefore shows the
 * value any save will store.
 */
function storedChoice(value: unknown, choices: readonly { value: string }[], fallback: string): string {
    const normalized = pyStrip(typeof value === 'string' ? value : '').toLowerCase();
    return choices.some((choice) => choice.value === normalized) ? normalized : fallback;
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
        selectedPaths: storedList(connection.selected_paths),
        includePatterns: joinList(filters.include_patterns),
        excludePatterns: joinList(filters.exclude_patterns),
        allowedExtensions: joinList(filters.allowed_extensions),
        fixedTags: storedList(filters.fixed_tags),
        folderTagMode: storedChoice(filters.folder_tag_mode, FOLDER_TAG_MODES, DEFAULT_FOLDER_TAG_MODE),
        remoteDeletePolicy: storedChoice(source.remote_delete_policy, REMOTE_DELETE_POLICIES, DEFAULT_REMOTE_DELETE_POLICY),
        scheduleEnabled: Boolean((schedule as Record<string, unknown>).enabled),
        intervalMinutes: Number((schedule as Record<string, unknown>).interval_minutes ?? minInterval) || minInterval || 60,
        credentialMode: identityId ? 'identity' : 'inline',
        identityId,
        credentials: {
            authType: String(credentials.auth_type ?? connectionDescriptor(sourceType).authTypes[0] ?? 'username_password'),
            username: String(credentials.username ?? ''),
            domain: String(credentials.domain ?? ''),
            // A managed identity keeps its client ID in managed_identity_client_id, a service
            // principal in identity; the classic editor reads them the same way.
            clientId: String(credentials.identity || credentials.managed_identity_client_id || ''),
            tenantId: String(credentials.tenant_id ?? ''),
            secret: '',
        },
        secretStored,
    };
}

/**
 * The per-type connection object the write carries, keyed as the backend normalizer expects. Every
 * type carries its selected paths beside its root fields, as the classic editor sends them.
 */
function buildConnection(draft: FileSourceDraft): Record<string, unknown> {
    const connection = draft.connection;
    const selectedPaths = [...draft.selectedPaths];
    if (draft.sourceType === FILE_SOURCE_TYPE_AZURE_FILES) {
        return {
            account_url: connection.accountUrl.trim(),
            share_name: connection.shareName.trim(),
            directory_path: connection.directoryPath.trim(),
            selected_paths: selectedPaths,
        };
    }
    if (draft.sourceType === FILE_SOURCE_TYPE_AZURE_BLOB) {
        return {
            account_url: connection.accountUrl.trim(),
            container_name: connection.containerName.trim(),
            blob_prefix: connection.blobPrefix.trim(),
            selected_paths: selectedPaths,
        };
    }
    return { unc_path: connection.uncPath.trim(), selected_paths: selectedPaths };
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
            fixed_tags: [...draft.fixedTags],
            folder_tag_mode: draft.folderTagMode,
        },
        schedule: { enabled: draft.scheduleEnabled, interval_minutes: draft.intervalMinutes },
        remote_delete_policy: draft.remoteDeletePolicy,
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

/**
 * A typed or browsed path under the source root, normalized exactly as `_normalize_selected_path`
 * does: at most 2,048 characters, backslashes read as slashes, outer slashes and each folder name
 * trimmed. An empty, `.` or `..` folder name is refused rather than dropped, because the server
 * refuses the whole save for one, with a message that can't say which path was wrong.
 */
export function normalizeSelectedPath(value: string): { path: string } | { error: string } {
    const text = Array.from(pyStrip(String(value ?? ''))).slice(0, SELECTED_PATH_MAX_LENGTH).join('');
    const joined = text.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
    if (!joined) {
        return { path: '' };
    }
    const parts = joined.split('/').map((part) => pyStrip(part));
    if (parts.some((part) => !part || part === '.' || part === '..')) {
        return { error: SELECTED_PATH_INVALID };
    }
    return { path: parts.join('/') };
}

/** Whether a path is already selected. The server dedupes selected paths ignoring case. */
export function isPathSelected(paths: readonly string[], path: string): boolean {
    const key = path.toLowerCase();
    return paths.some((selected) => selected.toLowerCase() === key);
}

/** Add one path to the selection, keeping stored order; a path already selected is a no-op. */
export function withSelectedPath(
    paths: readonly string[], value: string,
): { paths: string[]; path: string } | { error: string } {
    const result = normalizeSelectedPath(value);
    if ('error' in result) {
        return result;
    }
    if (!result.path) {
        return { error: 'Enter a folder or file under the source root.' };
    }
    return {
        paths: isPathSelected(paths, result.path) ? [...paths] : [...paths, result.path],
        path: result.path,
    };
}

/** Remove a path from the selection, matching it as the server matches duplicates (ignoring case). */
export function withoutSelectedPath(paths: readonly string[], path: string): string[] {
    const key = path.toLowerCase();
    return paths.filter((selected) => selected.toLowerCase() !== key);
}

/** The folder above a browsed path, or the source root ('') for a top-level one. */
export function parentBrowsePath(path: string): string {
    const parts = path.split('/').filter(Boolean);
    parts.pop();
    return parts.join('/');
}

/**
 * One fixed tag, normalized exactly as `_safe_tag_from_text` does: trimmed and lowered, every run of
 * characters outside a-z, 0-9, `_` and `-` replaced by a hyphen, outer hyphens removed, then cut to
 * 50 characters. What the chip shows is what the server stores.
 */
export function normalizeFixedTag(value: string): string {
    return pyStrip(String(value ?? '')).toLowerCase()
        .replace(/[^a-z0-9_-]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, FIXED_TAG_MAX_LENGTH);
}

/** Add one fixed tag; the server keeps the first of any duplicates, so a repeat is a no-op. */
export function withFixedTag(
    tags: readonly string[], value: string,
): { tags: string[]; tag: string } | { error: string } {
    const tag = normalizeFixedTag(value);
    if (!tag) {
        return { error: FIXED_TAG_INVALID };
    }
    return { tags: tags.includes(tag) ? [...tags] : [...tags, tag], tag };
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
