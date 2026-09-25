// publicDirectory.ts
// The native public directory: discovering public workspaces read-only.
//
// This is the read adapter behind the V2 public directory page. It talks to one route,
// GET /api/public_workspaces/directory (the M9A backend family), and nothing else. The
// directory never discloses what a reader must not see -- no owner email or id, no
// manager-only fields -- so its row is deliberately narrower than the classic
// GET /api/public_workspaces list, which the V2 client no longer calls.
//
// Every response is validated strictly: a malformed envelope or row is a load error, never
// a silently-empty list, because a directory that renders a shape it could not verify is
// worse than one that reports it could not read the server. The route is read-only: there
// is no create, join or cancel, so the adapter is a pure list plus the row's logo and open
// target.
//
// The page and search limits mirror the server (`functions_public_directory`), reusing the
// shared directory constants so the page never sends a request the server would answer with
// a 400 whose Retry could only repeat it.

import { api, ApiError, apiUrl } from './apiClient';
import { isRecord } from './workspaceAuthoring';
import { requireWorkspaceId } from './workspaceContext';
import {
    DIRECTORY_PAGE_SIZE,
    DIRECTORY_MAX_PAGE,
    DIRECTORY_SEARCH_MAX_LENGTH,
    codePointLength,
} from './groupDirectory';

export type PublicDirectoryView = 'all' | 'mine';
export type PublicDirectoryMembership = 'member' | 'none';

export interface PublicDirectoryWorkspace {
    id: string;
    name: string;
    description: string;
    heroColor: string;
    hasLogo: boolean;
    logoVersion: number;
    /** The caller's own role in this workspace; every reader is at least a User. */
    userRole: string;
    /** `member` when the caller holds a stored role, `none` otherwise. */
    membership: PublicDirectoryMembership;
    /** The workspace status, or `unknown` for a value the reader vocabulary omits. */
    status: string;
}

export interface PublicDirectoryHints {
    schemaVersion: number;
}

export interface PublicDirectoryPage {
    workspaces: PublicDirectoryWorkspace[];
    page: number;
    pageSize: number;
    totalCount: number;
    hints: PublicDirectoryHints;
}

/** Re-exported so the page shares one source of truth with the group directory limits. */
export {
    DIRECTORY_PAGE_SIZE,
    DIRECTORY_MAX_PAGE,
    DIRECTORY_SEARCH_MAX_LENGTH,
    codePointLength,
};

const MEMBERSHIPS: readonly PublicDirectoryMembership[] = ['member', 'none'];

function isMembership(value: unknown): value is PublicDirectoryMembership {
    return typeof value === 'string' && (MEMBERSHIPS as readonly string[]).includes(value);
}

function isNonNegativeInteger(value: unknown): value is number {
    return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function readRow(value: unknown): PublicDirectoryWorkspace {
    if (!isRecord(value)
        || typeof value.id !== 'string' || !value.id
        || typeof value.name !== 'string'
        || typeof value.description !== 'string'
        || typeof value.heroColor !== 'string' || !value.heroColor
        || typeof value.hasLogo !== 'boolean'
        || !isNonNegativeInteger(value.logoVersion)
        || typeof value.userRole !== 'string' || !value.userRole
        || !isMembership(value.membership)
        || typeof value.status !== 'string' || !value.status) {
        throw new Error('The public directory returned invalid data. Please retry.');
    }
    return {
        id: value.id,
        name: value.name,
        description: value.description,
        heroColor: value.heroColor,
        hasLogo: value.hasLogo,
        logoVersion: value.logoVersion,
        userRole: value.userRole,
        membership: value.membership,
        status: value.status,
    };
}

function readHints(value: unknown): PublicDirectoryHints {
    if (!isRecord(value) || value.schema_version !== 1) {
        throw new Error('The public directory returned invalid data. Please retry.');
    }
    return { schemaVersion: value.schema_version };
}

export function readPublicDirectoryPage(response: unknown, page: number, pageSize: number): PublicDirectoryPage {
    if (!isRecord(response) || !Array.isArray(response.workspaces)
        || !isNonNegativeInteger(response.total_count)
        || typeof response.page !== 'number' || !Number.isInteger(response.page) || response.page < 1
        || typeof response.page_size !== 'number' || !Number.isInteger(response.page_size) || response.page_size < 1) {
        throw new Error('The public directory could not be read. Please retry.');
    }
    const workspaces = response.workspaces.map(readRow);
    const hints = readHints(response.public_directory);
    return {
        workspaces,
        page: response.page ?? page,
        pageSize: response.page_size ?? pageSize,
        totalCount: response.total_count,
        hints,
    };
}

/** The machine-readable `error_code` on a directory failure, when the server sent one. */
export function publicDirectoryErrorCode(error: unknown): string | null {
    if (error instanceof ApiError && isRecord(error.payload) && typeof error.payload.error_code === 'string') {
        return error.payload.error_code;
    }
    return null;
}

function listQuery(view: PublicDirectoryView, search: string, page: number, pageSize: number): string {
    const params = new URLSearchParams({
        view,
        page: String(page),
        page_size: String(pageSize),
    });
    if (search.trim()) params.set('search', search.trim());
    return params.toString();
}

export interface PublicDirectoryAdapter {
    scope: 'public';
    list: (view: PublicDirectoryView, search: string, page: number, pageSize: number, signal?: AbortSignal) => Promise<PublicDirectoryPage>;
    /** The logo URL for a row, or null when it carries no loadable logo. */
    logoUrl: (workspace: PublicDirectoryWorkspace) => string | null;
    /** Where Open navigates for a row, by immutable id and with no activate handshake. */
    openPath: (id: string) => string;
    noun: string;
    pluralNoun: string;
}

export const PUBLIC_DIRECTORY: PublicDirectoryAdapter = {
    scope: 'public',
    list: async (view, search, page, pageSize, signal) => {
        const response = await api.get<unknown>(`/api/public_workspaces/directory?${listQuery(view, search, page, pageSize)}`, signal);
        return readPublicDirectoryPage(response, page, pageSize);
    },
    logoUrl: (workspace) => {
        // A logo is requested only when the server says one is stored for this workspace.
        if (!workspace.hasLogo) return null;
        return apiUrl(`/api/public_workspaces/${encodeURIComponent(requireWorkspaceId(workspace.id))}/logo?v=${encodeURIComponent(String(workspace.logoVersion))}`);
    },
    openPath: (id) => `/public/${encodeURIComponent(requireWorkspaceId(id))}`,
    noun: 'public workspace',
    pluralNoun: 'public workspaces',
};
