// publicDirectory.ts
// The native public directory: discovering public workspaces read-only.
//
// This is the read adapter behind the V2 public directory page. It talks to the M9A directory
// route, GET /api/public_workspaces/directory, and the M10A request routes,
// POST and DELETE /api/public-workspaces/<id>/membership/requests, and nothing else. The
// directory never discloses what a reader must not see -- no owner email or id, no
// manager-only fields -- so its row is deliberately narrower than the classic
// GET /api/public_workspaces list, which the V2 client no longer calls.
//
// Every response is validated strictly: a malformed envelope or row is a load error, never
// a silently-empty list, because a directory that renders a shape it could not verify is
// worse than one that reports it could not read the server. The membership actions never keep
// optimistic state: each write returns the server's own `{workspace}` row, and the client
// gates the "Ask to manage documents" and "Cancel request" affordances on that server-computed
// membership, never a client role check.
//
// The page and search limits mirror the server (`functions_public_directory`), reusing the
// shared directory constants so the page never sends a request the server would answer with
// a 400 whose Retry could only repeat it.

import { api, ApiError, apiUrl, requestWithStatus } from './apiClient';
import { isRecord } from './workspaceAuthoring';
import { requireWorkspaceId } from './workspaceContext';
import {
    DIRECTORY_PAGE_SIZE,
    DIRECTORY_MAX_PAGE,
    DIRECTORY_SEARCH_MAX_LENGTH,
    codePointLength,
} from './groupDirectory';

export type PublicDirectoryView = 'all' | 'mine';
export type PublicDirectoryMembership = 'member' | 'pending' | 'none';

export interface PublicDirectoryWorkspace {
    id: string;
    name: string;
    description: string;
    heroColor: string;
    hasLogo: boolean;
    logoVersion: number;
    /** The caller's own role in this workspace; every reader is at least a User. */
    userRole: string;
    /**
     * `member` when the caller holds a stored role, `pending` when the caller has their own
     * outstanding request to manage this workspace's documents, `none` otherwise. The pending
     * flag is the caller's own and never discloses anyone else's request.
     */
    membership: PublicDirectoryMembership;
    /** The workspace status, or `unknown` for a value the reader vocabulary omits. */
    status: string;
}

export interface PublicDirectoryHints {
    schemaVersion: number;
    /** Whether this caller may create a public workspace, mirroring the classic create gate. */
    canCreate: boolean;
}

/** The classic ``POST /api/public_workspaces`` reply the Create affordance opens on. */
export interface PublicWorkspaceCreated {
    id: string;
    name: string;
}

/**
 * A workspace reduced to what a whole-directory bulk action needs: its immutable id and its
 * status. The status lets the caller tell an *available* workspace (one a reader may chat) from
 * an unavailable one, so a bulk "show" can skip the unavailable rather than claim them for chat.
 */
export interface PublicDirectoryWorkspaceRef {
    id: string;
    status: string;
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

// The bulk visibility controls (All visible, All hidden, Show all and chat, Save list) act on
// every workspace in the directory, not the one page on screen. The directory is server-paged,
// so covering "all" means walking the pages, which is bounded so a very large collection can
// never turn one click into an unbounded fan-out of requests or a settings blob that will not
// save. Past the bound the control refuses with the count rather than writing part of the set
// and implying the whole -- the plan rule that a bulk action never claims more than it wrote.
export const DIRECTORY_BULK_PAGE_SIZE = 100; // the server's PUBLIC_DIRECTORY_MAX_PAGE_SIZE
export const DIRECTORY_BULK_MAX_WORKSPACES = 1000;

/** Raised when the directory is larger than a single bulk action may cover. */
export class DirectoryBulkTooLargeError extends Error {
    readonly count: number;
    constructor(count: number) {
        super(
            `There are ${count} public workspaces, too many to change all at once. `
            + 'Show or hide them individually, or use a saved list.',
        );
        this.name = 'DirectoryBulkTooLargeError';
        this.count = count;
    }
}

const MEMBERSHIPS: readonly PublicDirectoryMembership[] = ['member', 'pending', 'none'];

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
    if (!isRecord(value) || value.schema_version !== 1 || typeof value.can_create !== 'boolean') {
        throw new Error('The public directory returned invalid data. Please retry.');
    }
    return { schemaVersion: value.schema_version, canCreate: value.can_create };
}

function readCreatedWorkspace(value: unknown): PublicWorkspaceCreated {
    // The classic route replies { id, name }; anything else means the workspace exists but the
    // directory cannot open it by id, so the caller is told to refresh rather than navigate blind.
    if (!isRecord(value) || typeof value.id !== 'string' || !value.id || typeof value.name !== 'string') {
        throw new Error('The public workspace was created but could not be opened. Please refresh the directory.');
    }
    return { id: value.id, name: value.name };
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

/** The server's `{workspace}` row is the single source of truth after a request or cancel. */
export function readPublicDirectoryWorkspace(response: unknown): PublicDirectoryWorkspace {
    if (!isRecord(response)) {
        throw new Error('The public directory returned invalid data. Please retry.');
    }
    return readRow(response.workspace);
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

/**
 * Walk the whole directory once, bounded, returning each workspace's id and status.
 *
 * Walks the `all` view with no search at the server's largest page. The first page carries
 * total_count, so a directory past the bound is refused before any further request. Ids are
 * deduplicated by first appearance -- a workspace can shift pages if the collection changes
 * mid-walk -- and each id keeps the status it was first seen with. This is the single source the
 * id-only and id-plus-status bulk callers both read, so they can never diverge on what "all" means.
 */
async function walkAllWorkspaces(signal?: AbortSignal): Promise<PublicDirectoryWorkspaceRef[]> {
    const query = (page: number) => `/api/public_workspaces/directory?${listQuery('all', '', page, DIRECTORY_BULK_PAGE_SIZE)}`;
    const first = readPublicDirectoryPage(await api.get<unknown>(query(1), signal), 1, DIRECTORY_BULK_PAGE_SIZE);
    if (first.totalCount > DIRECTORY_BULK_MAX_WORKSPACES) {
        throw new DirectoryBulkTooLargeError(first.totalCount);
    }
    const seen = new Map<string, string>();
    const record = (workspace: PublicDirectoryWorkspace) => {
        if (!seen.has(workspace.id)) seen.set(workspace.id, workspace.status);
    };
    first.workspaces.forEach(record);
    const pages = Math.max(1, Math.ceil(first.totalCount / DIRECTORY_BULK_PAGE_SIZE));
    for (let page = 2; page <= pages; page += 1) {
        const next = readPublicDirectoryPage(await api.get<unknown>(query(page), signal), page, DIRECTORY_BULK_PAGE_SIZE);
        next.workspaces.forEach(record);
    }
    return [...seen].map(([id, status]) => ({ id, status }));
}

export interface PublicDirectoryAdapter {
    scope: 'public';
    list: (view: PublicDirectoryView, search: string, page: number, pageSize: number, signal?: AbortSignal) => Promise<PublicDirectoryPage>;
    /** Create a public workspace via the classic route the directory reuses unchanged. */
    create: (name: string, description: string) => Promise<PublicWorkspaceCreated>;
    /** Ask to manage a workspace's documents; returns the server's fresh row. */
    requestAccess: (id: string) => Promise<PublicDirectoryWorkspace>;
    /** Cancel the caller's own pending request; returns the server's fresh row. */
    cancelRequest: (id: string) => Promise<PublicDirectoryWorkspace>;
    /**
     * Every discoverable workspace's id, walked across the server's pages so a bulk action
     * covers the whole directory rather than the page on screen. Throws
     * {@link DirectoryBulkTooLargeError} when the directory is larger than the bound, so the
     * caller refuses rather than writing a partial set.
     */
    listAllWorkspaceIds: (signal?: AbortSignal) => Promise<string[]>;
    /**
     * Every discoverable workspace's id *and status*, walked across the server's pages under the
     * same bound as {@link listAllWorkspaceIds}. A bulk "show" reads the status so it can skip a
     * workspace a reader cannot chat rather than claim it for chat, and a saved list leaves an
     * unavailable member hidden.
     */
    listAllWorkspaces: (signal?: AbortSignal) => Promise<PublicDirectoryWorkspaceRef[]>;
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
    create: async (name, description) => {
        // Reuses the classic POST /api/public_workspaces unchanged: 201 { id, name } on success;
        // 400 "Enable Public Workspaces is disabled." when the feature is off; 403 { error, message }
        // when the CreatePublicWorkspaces role is required. None of those carry an error_code.
        const { data } = await requestWithStatus<unknown>('/api/public_workspaces', { method: 'POST', body: { name, description } });
        return readCreatedWorkspace(data);
    },
    requestAccess: async (id) => {
        // POST /api/public-workspaces/<id>/membership/requests: 201 { workspace } on success;
        // 409 already_member / request_pending; 409 public_workspace_write_conflict on a race.
        const { data } = await requestWithStatus<unknown>(
            `/api/public-workspaces/${encodeURIComponent(requireWorkspaceId(id))}/membership/requests`,
            { method: 'POST' },
        );
        return readPublicDirectoryWorkspace(data);
    },
    cancelRequest: async (id) => {
        // DELETE /api/public-workspaces/<id>/membership/requests: 200 { workspace } on success;
        // 409 no_pending_request when there is nothing to cancel.
        const { data } = await requestWithStatus<unknown>(
            `/api/public-workspaces/${encodeURIComponent(requireWorkspaceId(id))}/membership/requests`,
            { method: 'DELETE' },
        );
        return readPublicDirectoryWorkspace(data);
    },
    listAllWorkspaceIds: async (signal) => (await walkAllWorkspaces(signal)).map((workspace) => workspace.id),
    listAllWorkspaces: async (signal) => walkAllWorkspaces(signal),
    logoUrl: (workspace) => {
        // A logo is requested only when the server says one is stored for this workspace.
        if (!workspace.hasLogo) return null;
        return apiUrl(`/api/public_workspaces/${encodeURIComponent(requireWorkspaceId(workspace.id))}/logo?v=${encodeURIComponent(String(workspace.logoVersion))}`);
    },
    openPath: (id) => `/public/${encodeURIComponent(requireWorkspaceId(id))}`,
    noun: 'public workspace',
    pluralNoun: 'public workspaces',
};
