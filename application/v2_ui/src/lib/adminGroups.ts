// adminGroups.ts
// Group directory lookups for administrator assignment pickers.
//
// Several admin settings scope a capability to a list of group ids. An id is not
// something an administrator recognises, so a picker has to do two things the settings
// document cannot: resolve the ids already saved into names, and search the directory
// for more.
//
// Both go through `/api/v2/admin/groups`, which is admin-scoped. The endpoint is passed
// in from the field definition rather than hard-coded, so the same control serves every
// setting that stores a group assignment.

import { api } from './apiClient';

export interface AdminGroup {
    id: string;
    name: string;
    description: string;
    member_count: number;
}

interface AdminGroupResponse {
    groups?: unknown[];
    truncated?: boolean;
}

export interface AdminGroupPage {
    groups: AdminGroup[];
    /** True when more groups matched than the endpoint returned. */
    truncated: boolean;
}

/** Read a directory row defensively; it is database content shaped by the server. */
function toAdminGroup(value: unknown): AdminGroup | null {
    if (!value || typeof value !== 'object') {
        return null;
    }
    const row = value as Record<string, unknown>;
    const id = typeof row.id === 'string' ? row.id : '';
    if (!id) {
        return null;
    }
    return {
        id,
        name: typeof row.name === 'string' ? row.name : '',
        description: typeof row.description === 'string' ? row.description : '',
        member_count: typeof row.member_count === 'number' ? row.member_count : 0,
    };
}

function toAdminGroupPage(response: AdminGroupResponse): AdminGroupPage {
    return {
        groups: (response.groups ?? [])
            .map(toAdminGroup)
            .filter((group): group is AdminGroup => group !== null),
        truncated: Boolean(response.truncated),
    };
}

/** Search the directory. An empty term browses it. */
export async function searchAdminGroups(
    endpoint: string,
    search: string,
    signal?: AbortSignal,
): Promise<AdminGroupPage> {
    const query = new URLSearchParams();
    if (search.trim()) {
        query.set('search', search.trim());
    }
    const suffix = query.toString();
    return toAdminGroupPage(
        await api.get<AdminGroupResponse>(`${endpoint}${suffix ? `?${suffix}` : ''}`, signal),
    );
}

/**
 * Ids per resolve request.
 *
 * A group id is 36 characters, so 40 of them plus separators is roughly 1.5 KB of
 * query string. IIS on Azure App Service rejects a query string over 2048 bytes by
 * default, and an administrator with a large assignment would otherwise see every
 * chip fall back to a raw id with no obvious reason.
 */
const RESOLVE_BATCH_SIZE = 40;

/**
 * Resolve specific ids to directory rows.
 *
 * An id that no longer exists is simply absent from the result rather than being an
 * error, which is what lets the caller mark a stale assignment instead of either hiding
 * it or failing the whole lookup because of one deleted group.
 */
export async function resolveAdminGroups(
    endpoint: string,
    ids: string[],
    signal?: AbortSignal,
): Promise<AdminGroup[]> {
    if (!ids.length) {
        return [];
    }

    const batches: string[][] = [];
    for (let index = 0; index < ids.length; index += RESOLVE_BATCH_SIZE) {
        batches.push(ids.slice(index, index + RESOLVE_BATCH_SIZE));
    }

    const pages = await Promise.all(
        batches.map(async (batch) => {
            const query = new URLSearchParams({ ids: batch.join(',') });
            return toAdminGroupPage(
                await api.get<AdminGroupResponse>(`${endpoint}?${query.toString()}`, signal),
            );
        }),
    );

    return pages.flatMap((page) => page.groups);
}
