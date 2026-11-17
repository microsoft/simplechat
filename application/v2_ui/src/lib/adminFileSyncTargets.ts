// adminFileSyncTargets.ts
// Managing another workspace's file sources as an administrator.
//
// File Sync sources normally belong to whoever owns the workspace. An administrator who has to
// set one up for someone else -- a user who cannot reach their file share from their own
// machine, a group whose owner has left -- used to do it from the classic File Sync card: search
// for a user, a group or a public workspace, then open a manager for that target's sources.
// This is the V2 side of that. It finds the target, and it presents the target's sources
// through the same workbench a workspace's own manager uses, over the administrator routes that
// act on a named target (/api/admin/file-sync/<scope>/<id>/...).
//
// The administrator routes differ from the workspace ones in ways the adapter absorbs:
// - Lists and single records are wrapped as `sources` and `source`, not `file_sources` and
//   `file_source`, and carry no per-row operation hints, so every row is offered every
//   operation and the server's own refusal is what the administrator reads.
// - Writes are unconditional: there is no config revision to send or to conflict on.
// - There is no single-source read, no ignore-a-path route and no tag read for a target, so a
//   row is re-read from the list and those two controls are left out.
//
// Existing sources are changed, synced and deleted under the workspace role checks the server
// applies to every File Sync write, so those succeed where the administrator also manages the
// workspace; creating a source and listing a target's sources do not need that. The server's
// message is shown as it is when it refuses.

import { ApiError, api } from './apiClient';
import {
    FILE_SOURCE_OPERATIONS,
    browseFromResponse,
    conditionalGroupUpdate,
    connectionFromResponse,
    deleteGroupSource,
    groupWriteBody,
    identitiesFromResponse,
    optionsFromResponse,
    runsFromResponse,
    type FileSourceScope,
    type FileSourceWorkbenchAdapter,
} from './fileSourceWorkbench';
import type { WorkspaceSyncRun, WorkspaceSyncSource } from './types';
import { isRecord } from './workspaceAuthoring';
import { requireWorkspaceId } from './workspaceContext';

export type AdminFileSyncScope = 'personal' | 'group' | 'public';

/** Who the administrator is managing sources for. */
export interface AdminFileSyncTarget {
    scope: AdminFileSyncScope;
    id: string;
    /** What the administrator picked, for the dialog's heading. */
    label: string;
}

/** One search result: the target's id, what to call it, and a second line to tell two apart. */
export interface FileSyncTargetCandidate {
    id: string;
    title: string;
    subtitle: string;
}

/** The saved switches that decide which targets the server accepts. */
export interface FileSyncAvailability {
    fileSync: boolean;
    /** The server treats File Sync as off while Redis Cache is, so a source cannot be managed either. */
    redis: boolean;
    personal: boolean;
    group: boolean;
    public: boolean;
}

export interface AdminFileSyncScopeInfo {
    scope: AdminFileSyncScope;
    /** What the target is called: "user", "group", "public workspace". */
    noun: string;
    heading: string;
    searchLabel: string;
    searchPlaceholder: string;
    idLabel: string;
    searchEndpoint: string;
    /** The key the search response holds its list under. */
    resultsKey: 'users' | 'groups' | 'workspaces';
    /** The switch that turns this kind of workspace on for File Sync, as the card labels it. */
    switchLabel: string;
    /** The noun the shared sources section uses in its copy. */
    sectionNoun: string;
}

export const ADMIN_FILE_SYNC_SCOPES: readonly AdminFileSyncScopeInfo[] = [
    {
        scope: 'personal',
        noun: 'user',
        heading: 'User sources',
        searchLabel: 'Search users',
        searchPlaceholder: 'Name or email',
        idLabel: 'User ID',
        searchEndpoint: '/api/admin/file-sync/users/search',
        resultsKey: 'users',
        switchLabel: 'Personal workspaces',
        sectionNoun: 'user',
    },
    {
        scope: 'group',
        noun: 'group',
        heading: 'Group sources',
        searchLabel: 'Search groups',
        searchPlaceholder: 'Group name',
        idLabel: 'Group ID',
        searchEndpoint: '/api/admin/file-sync/groups/search',
        resultsKey: 'groups',
        switchLabel: 'Group workspaces',
        sectionNoun: 'group',
    },
    {
        scope: 'public',
        noun: 'public workspace',
        heading: 'Public workspace sources',
        searchLabel: 'Search public workspaces',
        searchPlaceholder: 'Workspace name',
        idLabel: 'Public workspace ID',
        searchEndpoint: '/api/admin/file-sync/public-workspaces/search',
        resultsKey: 'workspaces',
        switchLabel: 'Public workspaces',
        sectionNoun: 'workspace',
    },
];

/** The server answers a shorter search with nothing, so it is not asked. */
export const TARGET_SEARCH_MIN_LENGTH = 2;

export function scopeInfo(scope: AdminFileSyncScope): AdminFileSyncScopeInfo {
    const info = ADMIN_FILE_SYNC_SCOPES.find((entry) => entry.scope === scope);
    if (!info) {
        throw new Error('Unsupported File Sync scope.');
    }
    return info;
}

/** Why a kind of target cannot be managed yet, or null when it can. */
export function unavailableReason(scope: AdminFileSyncScope, availability: FileSyncAvailability): string | null {
    if (!availability.fileSync) {
        return 'File Sync is not on in the saved settings. Turn on Enable File Sync and save to manage sources here.';
    }
    if (!availability.redis) {
        return 'Redis Cache is off in the saved settings, and the server treats File Sync as off without it. '
            + 'Turn it on, finish its connection and save to manage sources here.';
    }
    if (!availability[scope]) {
        const info = scopeInfo(scope);
        return `${info.switchLabel} is off in the saved settings. Turn it on and save to manage ${info.noun} sources here.`;
    }
    return null;
}

/** The query to search for, or why it is not worth sending. */
export function targetSearchQuery(raw: string): { query: string } | { error: string } {
    const query = raw.trim();
    if (query.length < TARGET_SEARCH_MIN_LENGTH) {
        return { error: `Type at least ${TARGET_SEARCH_MIN_LENGTH} characters to search.` };
    }
    return { query };
}

export function targetSearchUrl(scope: AdminFileSyncScope, query: string): string {
    return `${scopeInfo(scope).searchEndpoint}?q=${encodeURIComponent(query)}`;
}

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

/**
 * The matches of a target search.
 *
 * An entry without an id cannot be managed -- the id is what names the target in every route
 * after it -- so it is dropped rather than offered. A response that is not the expected shape
 * throws, so a changed server reads as a failure and not as "no matches".
 */
export function parseTargetCandidates(scope: AdminFileSyncScope, payload: unknown): FileSyncTargetCandidate[] {
    const info = scopeInfo(scope);
    const entries = isRecord(payload) ? payload[info.resultsKey] : undefined;
    if (!Array.isArray(entries)) {
        throw new Error('The search response was malformed. Try again.');
    }
    const candidates: FileSyncTargetCandidate[] = [];
    for (const entry of entries) {
        if (!isRecord(entry)) {
            continue;
        }
        const id = text(entry.id);
        if (!id) {
            continue;
        }
        if (scope === 'personal') {
            candidates.push({ id, title: text(entry.displayName) || text(entry.email) || id, subtitle: text(entry.email) });
        } else {
            candidates.push({ id, title: text(entry.name) || id, subtitle: text(entry.description) });
        }
    }
    return candidates;
}

/** How a picked target is named in the dialog heading and the selection line. */
export function describeCandidate(candidate: FileSyncTargetCandidate): string {
    return candidate.subtitle && candidate.subtitle !== candidate.title
        ? `${candidate.title} (${candidate.subtitle})`
        : candidate.title;
}

/** A pasted id, checked the way every workspace route checks one. */
export function targetIdFrom(raw: string): { id: string } | { error: string } {
    const id = raw.trim();
    if (!id) {
        return { error: 'Choose a search result or enter an ID.' };
    }
    try {
        return { id: requireWorkspaceId(id) };
    } catch {
        return { error: 'That ID is not valid. It cannot contain slashes, question marks or control characters.' };
    }
}

/** Every operation is offered on a row; the server's role checks decide which succeed. */
const ADMIN_SOURCE_ACTIONS: readonly string[] = ['edit', 'delete', 'sync', 'test'];

function adminSource(value: unknown): WorkspaceSyncSource {
    if (!isRecord(value) || typeof value.id !== 'string' || !value.id) {
        throw new Error('The file source response was malformed. Refresh and try again.');
    }
    return { ...(value as unknown as WorkspaceSyncSource), source_actions: [...ADMIN_SOURCE_ACTIONS] };
}

/** The list route wraps the collection as `sources`; a malformed envelope throws. */
export function adminSourcesFromResponse(value: unknown): WorkspaceSyncSource[] {
    if (!isRecord(value) || !Array.isArray(value.sources)) {
        throw new Error('The file sources response was malformed. Refresh and try again.');
    }
    return value.sources.map(adminSource);
}

/** The create and update routes wrap the record as `source`. */
export function adminSourceFromResponse(value: unknown): WorkspaceSyncSource {
    if (!isRecord(value)) {
        throw new Error('The file source response was malformed. Refresh and try again.');
    }
    return adminSource(value.source);
}

function targetScope(target: AdminFileSyncTarget, id: string): FileSourceScope {
    return target.scope === 'personal' ? { kind: 'personal' } : { kind: target.scope, id, name: target.label };
}

const NO_TAGS: string[] = [];

/** The file sources workbench for a target an administrator manages on its behalf. */
export function createAdminFileSourceWorkbench(target: AdminFileSyncTarget): FileSourceWorkbenchAdapter {
    const targetId = requireWorkspaceId(target.id);
    const base = `/api/admin/file-sync/${target.scope}/${encodeURIComponent(targetId)}`;
    const identitiesUrl = `/api/admin/workspace-identities/${target.scope}/${encodeURIComponent(targetId)}/identities`;
    const sourcesUrl = (sourceId?: string, suffix?: string): string => {
        const root = `${base}/sources`;
        const path = sourceId ? `${root}/${encodeURIComponent(requireWorkspaceId(sourceId))}` : root;
        return suffix ? `${path}/${suffix}` : path;
    };

    const list = async (signal?: AbortSignal): Promise<WorkspaceSyncSource[]> =>
        adminSourcesFromResponse(await api.get<unknown>(sourcesUrl(), signal));

    return {
        scope: targetScope(target, targetId),
        manageable: true,
        supported: new Set(FILE_SOURCE_OPERATIONS),
        allows: () => true,
        list,
        read: async (source, signal) => {
            const found = (await list(signal)).find((item) => item.id === source.id);
            if (!found) {
                throw new ApiError('This file source no longer exists.', 404, null);
            }
            return found;
        },
        create: async (write) => adminSourceFromResponse(await api.post<unknown>(sourcesUrl(), groupWriteBody(write))),
        update: async (source, write) =>
            adminSourceFromResponse(await conditionalGroupUpdate(sourcesUrl(source.id), groupWriteBody(write))),
        remove: (source, deleteAssociatedFiles) =>
            deleteGroupSource(sourcesUrl(source.id), { delete_associated_files: deleteAssociatedFiles }),
        options: async (signal) => optionsFromResponse(await api.get<unknown>(`${base}/source-options`, signal)),
        identities: async (signal) => identitiesFromResponse(await api.get<unknown>(identitiesUrl, signal)),
        tags: async () => NO_TAGS,
        runs: async (sourceId, signal): Promise<WorkspaceSyncRun[]> =>
            runsFromResponse(await api.get<unknown>(sourcesUrl(sourceId, 'runs'), signal)),
        sync: async (sourceId) => {
            const response = await api.post<unknown>(sourcesUrl(sourceId, 'sync'));
            return isRecord(response) && isRecord(response.run) ? (response.run as unknown as WorkspaceSyncRun) : null;
        },
        testConnection: async (source, write) => {
            const response = await api.post<unknown>(
                sourcesUrl(source?.id, 'test-connection'),
                write ? groupWriteBody(write) : undefined,
            );
            return connectionFromResponse(response);
        },
        browse: async (source, write, browsePath) => {
            const response = await api.post<unknown>(
                sourcesUrl(source?.id, 'browse'),
                { ...(write ? groupWriteBody(write) : {}), browse_path: browsePath },
            );
            return browseFromResponse(response);
        },
        ignorePath: async () => {
            throw new Error('Ignoring a path is not available when managing another workspace\u2019s sources.');
        },
    };
}

/** A target search, for the pickers: the matches, or the server's message when it refuses. */
export async function searchTargets(
    scope: AdminFileSyncScope,
    query: string,
    signal?: AbortSignal,
): Promise<FileSyncTargetCandidate[]> {
    return parseTargetCandidates(scope, await api.get<unknown>(targetSearchUrl(scope, query), signal));
}
