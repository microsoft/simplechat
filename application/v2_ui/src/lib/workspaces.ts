// workspaces.ts
// The group and public workspace lists behind the settings tabs.
//
// The two are near-identical in shape but not identical in wording: groups return a
// `groups` array and set their active one with `{ groupId }`, public workspaces return
// `workspaces` and use `{ workspaceId }`. The difference is small enough to share a
// component and too real to pretend away, so it is captured here once.
//
// Note this does NOT go through /api/user/settings. `activeGroupOid` looks like a setting
// but is popped from that payload and routed elsewhere, and never comes back from a later
// GET; the dedicated setActive routes say plainly what they do and report why they refused.

import { api } from './apiClient';
import { isRecord } from './workspaceAuthoring';

export interface WorkspaceSummary {
    id: string;
    name: string;
    description?: string;
    owner?: { displayName?: string; email?: string };
    userRole?: string;
    /** True for the one currently in use; the server resolves this, not the client. */
    isActive?: boolean;
    status?: string;
    [key: string]: unknown;
}

export interface WorkspacePage {
    items: WorkspaceSummary[];
    page: number;
    pageSize: number;
    totalCount: number;
}

interface GroupsResponse {
    groups?: WorkspaceSummary[];
    page?: number;
    page_size?: number;
    total_count?: number;
}

interface PublicWorkspacesResponse {
    workspaces?: WorkspaceSummary[];
    page?: number;
    page_size?: number;
    total_count?: number;
}

/** How the two workspace kinds differ, so one component can serve both. */
export interface WorkspaceKind {
    scope: 'group' | 'public';
    /** Fetch one page, with an optional search term applied server-side. */
    list: (page: number, pageSize: number, search: string, signal?: AbortSignal) => Promise<WorkspacePage>;
    /** Make one active. Rejects with a message the server supplied. */
    setActive: (id: string) => Promise<void>;
    /** What one of these is called, for empty states and labels. */
    noun: string;
    pluralNoun: string;
    classicHref: string;
}

function query(page: number, pageSize: number, search: string): string {
    const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
    });
    if (search.trim()) {
        params.set('search', search.trim());
    }
    return params.toString();
}

function isWorkspaceSummary(value: unknown): value is WorkspaceSummary {
    return isRecord(value) && typeof value.id === 'string' && Boolean(value.id)
        && typeof value.name === 'string';
}

function readPage(response: GroupsResponse | PublicWorkspacesResponse, key: 'groups' | 'workspaces', page: number, pageSize: number): WorkspacePage {
    if (!isRecord(response)) throw new Error('The workspace list could not be read. Please retry.');
    const items = response[key];
    const resultPage = response.page ?? page;
    const resultPageSize = response.page_size ?? pageSize;
    if (!Array.isArray(items) || !items.every(isWorkspaceSummary)
        || typeof response.total_count !== 'number' || !Number.isInteger(response.total_count) || response.total_count < 0
        || typeof resultPage !== 'number' || !Number.isInteger(resultPage) || resultPage < 1
        || typeof resultPageSize !== 'number' || !Number.isInteger(resultPageSize) || resultPageSize < 1) {
        throw new Error('The workspace list returned invalid data. Please retry.');
    }
    return {
        items,
        page: resultPage,
        pageSize: resultPageSize,
        totalCount: response.total_count,
    };
}

export const GROUP_WORKSPACES: WorkspaceKind = {
    scope: 'group',
    list: async (page, pageSize, search, signal) => {
        const response = await api.get<GroupsResponse>(
            `/api/groups?${query(page, pageSize, search)}`, signal,
        );
        return readPage(response, 'groups', page, pageSize);
    },
    setActive: async (id) => {
        // 400 missing id, 404 unknown group, 403 not a member — all surfaced as written.
        await api.patch('/api/groups/setActive', { groupId: id });
    },
    noun: 'group',
    pluralNoun: 'groups',
    classicHref: '/profile?tab=groups',
};

export const PUBLIC_WORKSPACES: WorkspaceKind = {
    scope: 'public',
    list: async (page, pageSize, search, signal) => {
        const response = await api.get<PublicWorkspacesResponse>(
            `/api/public_workspaces?${query(page, pageSize, search)}`, signal,
        );
        return readPage(response, 'workspaces', page, pageSize);
    },
    setActive: async (id) => {
        await api.patch('/api/public_workspaces/setActive', { workspaceId: id });
    },
    noun: 'public workspace',
    pluralNoun: 'public workspaces',
    classicHref: '/profile?tab=public-workspaces',
};
