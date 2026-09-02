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
    /** Fetch one page, with an optional search term applied server-side. */
    list: (page: number, pageSize: number, search: string) => Promise<WorkspacePage>;
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

export const GROUP_WORKSPACES: WorkspaceKind = {
    list: async (page, pageSize, search) => {
        const response = await api.get<GroupsResponse>(
            `/api/groups?${query(page, pageSize, search)}`,
        );
        return {
            items: response?.groups ?? [],
            page: response?.page ?? page,
            pageSize: response?.page_size ?? pageSize,
            totalCount: response?.total_count ?? 0,
        };
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
    list: async (page, pageSize, search) => {
        const response = await api.get<PublicWorkspacesResponse>(
            `/api/public_workspaces?${query(page, pageSize, search)}`,
        );
        return {
            items: response?.workspaces ?? [],
            page: response?.page ?? page,
            pageSize: response?.page_size ?? pageSize,
            totalCount: response?.total_count ?? 0,
        };
    },
    setActive: async (id) => {
        await api.patch('/api/public_workspaces/setActive', { workspaceId: id });
    },
    noun: 'public workspace',
    pluralNoun: 'public workspaces',
    classicHref: '/profile?tab=public-workspaces',
};
