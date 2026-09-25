// fileSourceWorkbench.ts
// Scope-aware file source reads and writes for the workspace "Sync" (file sources) section.
//
// The file sources section shipped personal-only: it called the /api/file-sync/personal
// functions in workspaceApi.ts directly, and stayed list-and-delete. This module is the seam that
// lets the section serve a group workspace natively, the way identityWorkbench.ts did for
// identities. A FileSourceScope selects which URLs are used and which per-operation gates apply.
// The personal adapter is a thin pass-through so its behaviour stays byte-identical in effect:
// same list URL, same runs/sync/delete URLs.
//
// The group path never falls back to personal behaviour. An absent or unrecognised
// file_source_management hint yields an empty operation set, which leaves every write gate refusing
// -- a missing server hint must not become a silent authorization bypass on the client. Editing,
// deleting, syncing and testing a specific source additionally require it to carry the operation in
// its own source_actions, exactly as the group identity gate does. There is no per-item group ID to
// check (§9), so the envelope is validated strictly instead: a malformed response throws rather
// than rendering as empty.
//
// Group scope carries a conditional write over config_revision, not an etag: PATCH and DELETE send
// expected_config_revision (missing is 400, stale is 409). A 409 becomes a typed error the section
// turns into "your draft is kept, reload and retry". Delete is richer: the associated documents may
// already be gone when the removal is refused, so a refusal carrying partial:true reports the
// documents WERE deleted, and a delete_incomplete keeps the source but reports the counts.

import { ApiError, api, requestWithStatus } from './apiClient';
import { fetchScopedGroupDocumentTags } from './documentReadAdapter';
import { isRecord } from './workspaceAuthoring';
import { requireWorkspaceId } from './workspaceContext';
import {
    deleteSyncSource as deletePersonalSyncSource,
    fetchSyncRuns as fetchPersonalSyncRuns,
    fetchSyncSources as fetchPersonalSyncSources,
    startSyncRun as startPersonalSyncRun,
} from './workspaceApi';
import type {
    FileSourceBrowseEntry,
    FileSourceIgnoreItem,
    FileSourceOptions,
    WorkspaceIdentity,
    WorkspaceSyncRun,
    WorkspaceSyncSource,
} from './types';

export type FileSourceScope =
    | { kind: 'personal' }
    | { kind: 'group'; id: string; name: string };

export const FILE_SOURCE_OPERATIONS = ['create', 'edit', 'delete', 'sync', 'test'] as const;
export type FileSourceOperation = typeof FILE_SOURCE_OPERATIONS[number];

/** The classic source payload the create and update routes accept, shaped by the editor. */
export interface FileSourceWrite {
    name?: string;
    source_type?: string;
    enabled?: boolean;
    recursive?: boolean;
    connection?: Record<string, unknown>;
    filters?: Record<string, unknown>;
    schedule?: { enabled?: boolean; interval_minutes?: number };
    remote_delete_policy?: string;
    identity_id?: string;
    credentials?: Record<string, unknown>;
}

/** The counts a native delete reports, whether it succeeded or was refused after some removal. */
export interface FileSourceDeleteOutcome {
    associated_files_requested: boolean;
    documents_deleted: number;
    documents_skipped: number;
    documents_failed: number;
}

/**
 * A successful connection test. The server returns `success: true` plus the counts it saw; a failed
 * test is not `{success: false}` but an HTTP 400 the caller catches and shows verbatim, so this type
 * models only the success payload the routes return under `connection`.
 */
export interface FileSourceConnectionResult {
    success: boolean;
    source_type?: string;
    recursive?: boolean;
    entries_checked?: number;
    files_seen?: number;
    folders_seen?: number;
    [key: string]: unknown;
}

export interface FileSourceBrowseResult {
    path: string;
    entries: FileSourceBrowseEntry[];
}

/**
 * A conditional-write conflict where the config revision moved (409 config_conflict, no documents
 * removed). The section catches this specifically: a stale config revision must keep the editor and
 * its draft open and offer a reload, not discard the edit.
 */
export class FileSourceConflictError extends Error {
    constructor(message = 'This file source changed while it was being saved. Reload it and try again.') {
        super(message);
        this.name = 'FileSourceConflictError';
    }
}

/**
 * A bare etag conflict where the config revision is unchanged (409 write_conflict). Nothing about
 * the source the editor is looking at moved, so the draft stays and a plain retry is enough -- no
 * reload is offered, unlike {@link FileSourceConflictError}.
 */
export class FileSourceWriteConflictError extends Error {
    constructor(message = 'This file source was just updated elsewhere. Try saving again.') {
        super(message);
        this.name = 'FileSourceWriteConflictError';
    }
}

/** A delete or sync refused because a sync is already running (409 source_busy, no removal). */
export class FileSourceBusyError extends Error {
    constructor(message = 'Wait for the running sync to finish, then delete the source.') {
        super(message);
        this.name = 'FileSourceBusyError';
    }
}

/**
 * A delete kept the source but could not remove all of its documents (409 delete_incomplete). The
 * source is still present; the counts say what happened so the section can show them and retry.
 */
export class FileSourceDeleteIncompleteError extends Error {
    readonly result: FileSourceDeleteOutcome;
    constructor(result: FileSourceDeleteOutcome, message = 'Some of the source\u2019s documents could not be deleted.') {
        super(message);
        this.name = 'FileSourceDeleteIncompleteError';
        this.result = result;
    }
}

/**
 * A delete that removed the documents but was then refused before removing the source (partial:true
 * with delete_result). The documents WERE deleted; the section must say so and reload, never claim
 * nothing changed.
 */
export class FileSourcePartialDeleteError extends Error {
    readonly result: FileSourceDeleteOutcome;
    constructor(result: FileSourceDeleteOutcome, message: string) {
        super(message);
        this.name = 'FileSourcePartialDeleteError';
        this.result = result;
    }
}

export interface FileSourceWorkbenchAdapter {
    scope: FileSourceScope;
    /** Whether the workspace advertises source creation, so the section shows a New control. */
    manageable: boolean;
    supported: ReadonlySet<FileSourceOperation>;
    allows: (operation: FileSourceOperation, source?: WorkspaceSyncSource) => boolean;
    list: (signal?: AbortSignal) => Promise<WorkspaceSyncSource[]>;
    read: (source: WorkspaceSyncSource, signal?: AbortSignal) => Promise<WorkspaceSyncSource>;
    create: (write: FileSourceWrite) => Promise<WorkspaceSyncSource>;
    update: (source: WorkspaceSyncSource, write: FileSourceWrite) => Promise<WorkspaceSyncSource>;
    remove: (source: WorkspaceSyncSource, deleteAssociatedFiles: boolean) => Promise<FileSourceDeleteOutcome>;
    /** The server-decided editor options; null when the scope has none (personal). */
    options: (signal?: AbortSignal) => Promise<FileSourceOptions | null>;
    /** The group identities that back the credential picker; empty for personal. */
    identities: (signal?: AbortSignal) => Promise<WorkspaceIdentity[]>;
    /**
     * The workspace's existing tag names, offered as fixed-tag suggestions, most used first; empty
     * for personal. A failed read only costs the suggestions, so the section treats it as optional.
     */
    tags: (signal?: AbortSignal) => Promise<string[]>;
    runs: (sourceId: string, signal?: AbortSignal) => Promise<WorkspaceSyncRun[]>;
    sync: (sourceId: string) => Promise<WorkspaceSyncRun | null>;
    testConnection: (source: WorkspaceSyncSource | null, write: FileSourceWrite | null) => Promise<FileSourceConnectionResult>;
    browse: (source: WorkspaceSyncSource | null, write: FileSourceWrite | null, browsePath: string) => Promise<FileSourceBrowseResult>;
    ignorePath: (sourceId: string, remotePath: string, ignored: boolean) => Promise<FileSourceIgnoreItem>;
    /** Where "adding one is still done in the classic workspace" points, for personal scope. */
    classicPath: string;
}

/**
 * The operations a `file_source_management` hint offers.
 *
 * Mirrors `advertisedIdentityOperations`: an unrecognised block (missing, wrong schema, or a
 * non-string entry) yields the empty set rather than a guess, so a malformed hint disables writing
 * rather than enabling it.
 */
export function advertisedFileSourceOperations(value: unknown): ReadonlySet<FileSourceOperation> {
    if (!isRecord(value) || value.schema_version !== 1 || !Array.isArray(value.operations)
        || !value.operations.every((operation) => typeof operation === 'string')) {
        return new Set();
    }
    const offered = value.operations;
    return new Set(FILE_SOURCE_OPERATIONS.filter((operation) => offered.includes(operation)));
}

/**
 * Whether an operation is allowed in a scope.
 *
 * Personal scope allows everything the personal section can do. Group scope requires the
 * workspace-level `file_source_management` hint to offer the operation, and edit/delete/sync/test
 * additionally require the specific source to carry the operation in its own `source_actions`.
 * There is deliberately no fallback that enables an action when the hint is empty or absent.
 */
export function fileSourceOperationAllowed(
    scope: FileSourceScope,
    supported: ReadonlySet<FileSourceOperation>,
    operation: FileSourceOperation,
    source?: WorkspaceSyncSource,
): boolean {
    if (scope.kind === 'personal') {
        return true;
    }
    if (!supported.has(operation)) {
        return false;
    }
    if (operation === 'create') {
        return true;
    }
    if (!source) {
        return false;
    }
    return Array.isArray(source.source_actions) && source.source_actions.includes(operation);
}

const NOT_IN_PERSONAL = 'This action is only available in a group workspace.';

export const PERSONAL_FILE_SOURCE_WORKBENCH: FileSourceWorkbenchAdapter = {
    scope: { kind: 'personal' },
    manageable: false,
    supported: new Set(),
    allows: () => true,
    list: (signal) => fetchPersonalSyncSources(signal),
    read: async (source) => source,
    create: () => {
        throw new Error('Adding a file source is done in the classic workspace.');
    },
    update: () => {
        throw new Error('Editing a file source is done in the classic workspace.');
    },
    remove: async (source, deleteAssociatedFiles) => {
        await deletePersonalSyncSource(source.id, deleteAssociatedFiles);
        return {
            associated_files_requested: deleteAssociatedFiles,
            documents_deleted: 0,
            documents_skipped: 0,
            documents_failed: 0,
        };
    },
    options: async () => null,
    identities: async () => [],
    tags: async () => [],
    runs: (sourceId, signal) => fetchPersonalSyncRuns(sourceId, signal),
    sync: async (sourceId) => {
        const response = await startPersonalSyncRun(sourceId);
        return response.run ?? null;
    },
    testConnection: () => {
        throw new Error(NOT_IN_PERSONAL);
    },
    browse: () => {
        throw new Error(NOT_IN_PERSONAL);
    },
    ignorePath: () => {
        throw new Error(NOT_IN_PERSONAL);
    },
    classicPath: '/workspace',
};

function groupFileSourcesUrl(groupId: string, sourceId?: string, suffix?: string): string {
    const base = `/api/groups/${encodeURIComponent(requireWorkspaceId(groupId))}/file-sources`;
    const path = sourceId ? `${base}/${encodeURIComponent(requireWorkspaceId(sourceId))}` : base;
    return suffix ? `${path}/${suffix}` : path;
}

/**
 * The list route wraps the collection under `file_sources`; a malformed envelope throws (§9). Each
 * item must carry the conditional-write token `config_revision` (a string) and its `source_actions`
 * array; a row missing either is malformed, so the strict envelope catches a server or fixture that
 * drifted from the real projection.
 */
function sourcesFromResponse(value: unknown): WorkspaceSyncSource[] {
    if (!isRecord(value) || !Array.isArray(value.file_sources)) {
        throw new Error('The file sources response was malformed. Refresh and try again.');
    }
    const sources = value.file_sources;
    const valid = sources.every((source) =>
        isRecord(source)
        && typeof source.id === 'string' && source.id
        && typeof source.config_revision === 'string' && source.config_revision
        && Array.isArray(source.source_actions));
    if (!valid) {
        throw new Error('The file sources response was malformed. Refresh and try again.');
    }
    return sources as WorkspaceSyncSource[];
}

/** The read, create and update routes wrap the record under `file_source`. */
function sourceFromResponse(value: unknown): WorkspaceSyncSource {
    if (isRecord(value) && isRecord(value.file_source) && typeof value.file_source.id === 'string'
        && value.file_source.id) {
        return value.file_source as WorkspaceSyncSource;
    }
    throw new Error('The file source response was malformed. Refresh and try again.');
}

function optionsFromResponse(value: unknown): FileSourceOptions {
    if (!isRecord(value) || !Array.isArray(value.source_types) || !isRecord(value.eligible_identity_ids)
        || !isRecord(value.schedule) || !isRecord(value.limits)) {
        throw new Error('The file source options response was malformed. Refresh and try again.');
    }
    return value as unknown as FileSourceOptions;
}

/** The identities picker source; the group route wraps the collection under `identities`. */
function identitiesFromResponse(value: unknown): WorkspaceIdentity[] {
    if (!isRecord(value) || !Array.isArray(value.identities)) {
        throw new Error('The identities response was malformed. Refresh and try again.');
    }
    return value.identities as WorkspaceIdentity[];
}

function runsFromResponse(value: unknown): WorkspaceSyncRun[] {
    if (isRecord(value) && Array.isArray(value.runs)) {
        return value.runs as WorkspaceSyncRun[];
    }
    throw new Error('The sync history response was malformed. Refresh and try again.');
}

function connectionFromResponse(value: unknown): FileSourceConnectionResult {
    if (isRecord(value) && isRecord(value.connection)) {
        return value.connection as FileSourceConnectionResult;
    }
    throw new Error('The connection test response was malformed. Try again.');
}

function browseFromResponse(value: unknown): FileSourceBrowseResult {
    if (isRecord(value) && isRecord(value.browse) && Array.isArray(value.browse.entries)) {
        return {
            path: String(value.browse.path ?? ''),
            entries: value.browse.entries as FileSourceBrowseEntry[],
        };
    }
    throw new Error('The browse response was malformed. Try again.');
}

function ignoreItemFromResponse(value: unknown): FileSourceIgnoreItem {
    if (isRecord(value) && isRecord(value.item)) {
        return value.item as FileSourceIgnoreItem;
    }
    throw new Error('The ignore-path response was malformed. Try again.');
}

/** The config revision rides on the current source; a missing one is a client-side guard. */
function requiredConfigRevision(source: WorkspaceSyncSource): string {
    const revision = typeof source.config_revision === 'string' ? source.config_revision.trim() : '';
    if (!revision) {
        throw new Error('This file source is missing its version marker. Refresh and try again.');
    }
    return revision;
}

/** Strip anything the strict native routes reject; send only the documented write fields. */
function groupWriteBody(write: FileSourceWrite): Record<string, unknown> {
    const body: Record<string, unknown> = {};
    if (write.name !== undefined) body.name = write.name;
    if (write.source_type !== undefined) body.source_type = write.source_type;
    if (write.enabled !== undefined) body.enabled = write.enabled;
    if (write.recursive !== undefined) body.recursive = write.recursive;
    if (write.connection !== undefined) body.connection = write.connection;
    if (write.filters !== undefined) body.filters = write.filters;
    if (write.schedule !== undefined) body.schedule = write.schedule;
    if (write.remote_delete_policy !== undefined) body.remote_delete_policy = write.remote_delete_policy;
    if (write.identity_id !== undefined) body.identity_id = write.identity_id;
    if (write.credentials !== undefined) body.credentials = write.credentials;
    return body;
}

function deleteOutcome(value: unknown): FileSourceDeleteOutcome {
    const result = isRecord(value) ? value : {};
    return {
        associated_files_requested: Boolean(result.associated_files_requested),
        documents_deleted: Number(result.documents_deleted ?? 0),
        documents_skipped: Number(result.documents_skipped ?? 0),
        documents_failed: Number(result.documents_failed ?? 0),
    };
}

async function conditionalGroupUpdate(url: string, body: Record<string, unknown>): Promise<unknown> {
    try {
        const response = await requestWithStatus<unknown>(url, { method: 'PATCH', body });
        return response.data;
    } catch (cause) {
        if (cause instanceof ApiError && cause.status === 409) {
            const payload = cause.payload;
            const errorCode = isRecord(payload) ? String(payload.error_code ?? '') : '';
            const message = isRecord(payload) && typeof payload.error === 'string' ? payload.error : undefined;
            // A bare etag race whose config revision is unchanged is a plain retry; a moved config
            // revision must keep the draft and offer a reload.
            if (errorCode === 'write_conflict') {
                throw new FileSourceWriteConflictError(message);
            }
            throw new FileSourceConflictError(message);
        }
        throw cause;
    }
}

async function deleteGroupSource(url: string, body: Record<string, unknown>): Promise<FileSourceDeleteOutcome> {
    try {
        const response = await requestWithStatus<unknown>(url, { method: 'DELETE', body });
        const data = response.data;
        return deleteOutcome(isRecord(data) ? data.delete_result : undefined);
    } catch (cause) {
        if (cause instanceof ApiError) {
            const payload = cause.payload;
            const errorCode = isRecord(payload) ? String(payload.error_code ?? '') : '';
            const message = isRecord(payload) && typeof payload.error === 'string' ? payload.error : cause.message;
            const partial = isRecord(payload) && payload.partial === true;
            const result = isRecord(payload) ? payload.delete_result : undefined;
            if (errorCode === 'delete_incomplete') {
                throw new FileSourceDeleteIncompleteError(deleteOutcome(result), message);
            }
            if (partial && isRecord(result)) {
                // The documents were removed; only the final source removal was refused.
                throw new FileSourcePartialDeleteError(deleteOutcome(result), message);
            }
            if (errorCode === 'source_busy') {
                throw new FileSourceBusyError(message);
            }
            if (errorCode === 'write_conflict') {
                throw new FileSourceWriteConflictError(message);
            }
            if (errorCode === 'config_conflict') {
                throw new FileSourceConflictError(message);
            }
        }
        throw cause;
    }
}

export function createGroupFileSourceWorkbench(
    scope: Extract<FileSourceScope, { kind: 'group' }>, management: unknown,
): FileSourceWorkbenchAdapter {
    if (scope.kind !== 'group') {
        throw new Error('Group file sources require an explicit group scope.');
    }
    const groupId = requireWorkspaceId(scope.id);
    const supported = advertisedFileSourceOperations(management);
    const allows = (operation: FileSourceOperation, source?: WorkspaceSyncSource) =>
        fileSourceOperationAllowed(scope, supported, operation, source);
    const identitiesUrl = `/api/groups/${encodeURIComponent(groupId)}/identities`;
    const optionsUrl = `/api/groups/${encodeURIComponent(groupId)}/file-source-options`;
    return {
        scope,
        manageable: supported.has('create'),
        supported,
        allows,
        list: async (signal) => {
            const response = await api.get<unknown>(groupFileSourcesUrl(groupId), signal);
            return sourcesFromResponse(response);
        },
        read: async (source, signal) => {
            const response = await api.get<unknown>(groupFileSourcesUrl(groupId, source.id), signal);
            return sourceFromResponse(response);
        },
        create: async (write) => {
            if (!allows('create')) {
                throw new Error('Creating file sources is not available in this group.');
            }
            const response = await api.post<unknown>(groupFileSourcesUrl(groupId), groupWriteBody(write));
            return sourceFromResponse(response);
        },
        update: async (source, write) => {
            if (!allows('edit', source)) {
                throw new Error('Editing this file source is not available.');
            }
            const updated = await conditionalGroupUpdate(groupFileSourcesUrl(groupId, source.id), {
                ...groupWriteBody(write), expected_config_revision: requiredConfigRevision(source),
            });
            return sourceFromResponse(updated);
        },
        remove: async (source, deleteAssociatedFiles) => {
            if (!allows('delete', source)) {
                throw new Error('Deleting this file source is not available.');
            }
            return deleteGroupSource(groupFileSourcesUrl(groupId, source.id), {
                expected_config_revision: requiredConfigRevision(source),
                delete_associated_files: deleteAssociatedFiles,
            });
        },
        options: async (signal) => {
            const response = await api.get<unknown>(optionsUrl, signal);
            return optionsFromResponse(response);
        },
        identities: async (signal) => {
            const response = await api.get<unknown>(identitiesUrl, signal);
            return identitiesFromResponse(response);
        },
        tags: async (signal) => {
            // The explicit-group tag read the Documents and Tags sections use, never the active group.
            const response = await fetchScopedGroupDocumentTags(groupId, signal);
            return [...response.tags ?? []]
                .sort((left, right) => (Number(right.count) - Number(left.count)) || left.name.localeCompare(right.name))
                .map((tag) => tag.name);
        },
        runs: async (sourceId, signal) => {
            const response = await api.get<unknown>(groupFileSourcesUrl(groupId, sourceId, 'runs'), signal);
            return runsFromResponse(response);
        },
        sync: async (sourceId) => {
            const response = await api.post<unknown>(groupFileSourcesUrl(groupId, sourceId, 'sync'));
            return isRecord(response) && isRecord(response.run) ? (response.run as WorkspaceSyncRun) : null;
        },
        testConnection: async (source, write) => {
            const url = source
                ? groupFileSourcesUrl(groupId, source.id, 'test-connection')
                : groupFileSourcesUrl(groupId, undefined, 'test-connection');
            const body = write ? groupWriteBody(write) : undefined;
            const response = await api.post<unknown>(url, body);
            return connectionFromResponse(response);
        },
        browse: async (source, write, browsePath) => {
            const url = source
                ? groupFileSourcesUrl(groupId, source.id, 'browse')
                : groupFileSourcesUrl(groupId, undefined, 'browse');
            const body: Record<string, unknown> = write ? groupWriteBody(write) : {};
            body.browse_path = browsePath;
            const response = await api.post<unknown>(url, body);
            return browseFromResponse(response);
        },
        ignorePath: async (sourceId, remotePath, ignored) => {
            const response = await api.post<unknown>(
                groupFileSourcesUrl(groupId, sourceId, 'ignore-path'),
                { remote_path: remotePath, ignored },
            );
            return ignoreItemFromResponse(response);
        },
        classicPath: '/group_workspaces',
    };
}
