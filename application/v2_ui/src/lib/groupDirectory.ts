// groupDirectory.ts
// The native group directory: finding groups, asking to join one, and creating one.
//
// This is the read/write adapter behind the V2 group directory page. It talks to the M7A
// backend family -- GET/POST /api/groups/directory and POST/DELETE
// /api/groups/<id>/join-request -- and nothing else. Every response is validated strictly:
// a malformed envelope or row is a load error, never a silently-empty list, because a
// directory that renders a shape it could not verify is worse than one that reports it
// could not read the server.
//
// The membership actions never keep optimistic state. Each write returns the server's own
// `{group}` row for the affected group, and the page replaces that one row with it, so the
// badge and the available action always tell the truth the server just committed.
//
// The list is deliberately shaped as a scope-neutral `DirectoryAdapter` so the public
// directory (M9A) can drive the same presentational list from the public routes without
// forking the layout.

import { api, ApiError, apiUrl, requestWithStatus } from './apiClient';
import { isRecord } from './workspaceAuthoring';
import { requireWorkspaceId } from './workspaceContext';

export type DirectoryView = 'all' | 'mine' | 'discover';
export type DirectoryMembership = 'member' | 'pending' | 'none';

export interface DirectoryGroup {
    id: string;
    name: string;
    description: string;
    ownerDisplayName: string;
    memberCount: number;
    heroColor: string;
    hasLogo: boolean;
    logoVersion: number;
    membership: DirectoryMembership;
    /** Present only for a member row; the caller's role in that group. */
    userRole?: string;
}

export interface DirectoryHints {
    canCreate: boolean;
    canRequestToJoin: boolean;
}

export interface DirectoryPage {
    groups: DirectoryGroup[];
    page: number;
    pageSize: number;
    totalCount: number;
    hints: DirectoryHints;
}

/** The scope-neutral surface the presentational list is driven by. */
export interface DirectoryAdapter {
    scope: 'group' | 'public';
    list: (view: DirectoryView, search: string, page: number, pageSize: number, signal?: AbortSignal) => Promise<DirectoryPage>;
    create: (name: string, description: string) => Promise<DirectoryGroup>;
    join: (id: string) => Promise<DirectoryGroup>;
    cancel: (id: string) => Promise<DirectoryGroup>;
    /** The logo URL for a row, or null when it carries no loadable logo. */
    logoUrl: (group: DirectoryGroup) => string | null;
    /** Where Open navigates for a row, by immutable id and with no activate handshake. */
    openPath: (id: string) => string;
    noun: string;
    pluralNoun: string;
}

export const DIRECTORY_PAGE_SIZE = 20;

// The server's search and page limits (`functions_group_directory`), mirrored here so the page
// never sends a request the server would answer with a 400 whose Retry could only repeat it.
export const DIRECTORY_SEARCH_MAX_LENGTH = 200;
export const DIRECTORY_MAX_PAGE = 10000;

// Count Unicode code points, matching the server's Python `len`, so an astral character such as an
// emoji counts once rather than as its two UTF-16 units. Used for the client-side length checks the
// server also enforces, so a value the server accepts is never wrongly refused or truncated.
export function codePointLength(value: string): number {
    return Array.from(value).length;
}

const MEMBERSHIPS: readonly DirectoryMembership[] = ['member', 'pending', 'none'];

function isMembership(value: unknown): value is DirectoryMembership {
    return typeof value === 'string' && (MEMBERSHIPS as readonly string[]).includes(value);
}

function isNonNegativeInteger(value: unknown): value is number {
    return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function readRow(value: unknown): DirectoryGroup {
    if (!isRecord(value)
        || typeof value.id !== 'string' || !value.id
        || typeof value.name !== 'string'
        || typeof value.description !== 'string'
        || !isRecord(value.owner) || typeof value.owner.displayName !== 'string'
        || !isNonNegativeInteger(value.member_count)
        || typeof value.heroColor !== 'string' || !value.heroColor
        || typeof value.hasLogo !== 'boolean'
        || !isNonNegativeInteger(value.logoVersion)
        || !isMembership(value.membership)
        || (value.membership === 'member' && (typeof value.userRole !== 'string' || !value.userRole))) {
        throw new Error('The group directory returned invalid data. Please retry.');
    }
    const group: DirectoryGroup = {
        id: value.id,
        name: value.name,
        description: value.description,
        ownerDisplayName: value.owner.displayName,
        memberCount: value.member_count,
        heroColor: value.heroColor,
        hasLogo: value.hasLogo,
        logoVersion: value.logoVersion,
        membership: value.membership,
    };
    if (value.membership === 'member') group.userRole = value.userRole as string;
    return group;
}

function readHints(value: unknown): DirectoryHints {
    if (!isRecord(value) || value.schema_version !== 1
        || typeof value.can_create !== 'boolean' || typeof value.can_request_to_join !== 'boolean') {
        throw new Error('The group directory returned invalid data. Please retry.');
    }
    return { canCreate: value.can_create, canRequestToJoin: value.can_request_to_join };
}

export function readDirectoryPage(response: unknown, page: number, pageSize: number): DirectoryPage {
    if (!isRecord(response) || !Array.isArray(response.groups)
        || !isNonNegativeInteger(response.total_count)
        || typeof response.page !== 'number' || !Number.isInteger(response.page) || response.page < 1
        || typeof response.page_size !== 'number' || !Number.isInteger(response.page_size) || response.page_size < 1) {
        throw new Error('The group directory could not be read. Please retry.');
    }
    const groups = response.groups.map(readRow);
    const hints = readHints(response.group_directory);
    return {
        groups,
        page: response.page ?? page,
        pageSize: response.page_size ?? pageSize,
        totalCount: response.total_count,
        hints,
    };
}

/** The server's `{group}` row is the single source of truth after a write. */
export function readDirectoryGroup(response: unknown): DirectoryGroup {
    if (!isRecord(response)) {
        throw new Error('The group directory returned invalid data. Please retry.');
    }
    return readRow(response.group);
}

/** The machine-readable `error_code` on a directory failure, when the server sent one. */
export function directoryErrorCode(error: unknown): string | null {
    if (error instanceof ApiError && isRecord(error.payload) && typeof error.payload.error_code === 'string') {
        return error.payload.error_code;
    }
    return null;
}

function listQuery(view: DirectoryView, search: string, page: number, pageSize: number): string {
    const params = new URLSearchParams({
        view,
        page: String(page),
        page_size: String(pageSize),
    });
    if (search.trim()) params.set('search', search.trim());
    return params.toString();
}

export const GROUP_DIRECTORY: DirectoryAdapter = {
    scope: 'group',
    list: async (view, search, page, pageSize, signal) => {
        const response = await api.get<unknown>(`/api/groups/directory?${listQuery(view, search, page, pageSize)}`, signal);
        return readDirectoryPage(response, page, pageSize);
    },
    create: async (name, description) => {
        // 201 on success; 403 group_creation_disabled/create_groups_role_required, 400 invalid_request.
        const { data } = await requestWithStatus<unknown>('/api/groups/directory', { method: 'POST', body: { name, description } });
        return readDirectoryGroup(data);
    },
    join: async (id) => {
        const { data } = await requestWithStatus<unknown>(`/api/groups/${encodeURIComponent(requireWorkspaceId(id))}/join-request`, { method: 'POST' });
        return readDirectoryGroup(data);
    },
    cancel: async (id) => {
        const { data } = await requestWithStatus<unknown>(`/api/groups/${encodeURIComponent(requireWorkspaceId(id))}/join-request`, { method: 'DELETE' });
        return readDirectoryGroup(data);
    },
    logoUrl: (group) => {
        // A logo is requested only when the server says one is loadable for this caller.
        if (!group.hasLogo) return null;
        return apiUrl(`/api/groups/${encodeURIComponent(requireWorkspaceId(group.id))}/logo?v=${encodeURIComponent(String(group.logoVersion))}`);
    },
    openPath: (id) => `/groups/${encodeURIComponent(requireWorkspaceId(id))}`,
    noun: 'group',
    pluralNoun: 'groups',
};
