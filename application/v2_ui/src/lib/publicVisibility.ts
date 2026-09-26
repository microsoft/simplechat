// publicVisibility.ts
// The per-user "visible for chat" map for public workspaces.
//
// The map is `publicDirectorySettings`, `{ workspaceId: boolean }`, shared verbatim with the
// classic interface so both read each other's writes. The aggregate public chat route reads
// it server-side (`get_user_visible_public_workspace_ids_from_settings`): when a non-empty map
// exists, only the ids set to `true` are visible; when there is no map, the server falls back
// through the older list to **every** public workspace. The helpers below mirror that exact
// fallback so the directory shows the truth the chat route would act on, and honours the R2
// ruling that a toggle is additive -- it writes only the one workspace's entry.
//
// "Available" is separate from "visible": a workspace whose status a reader cannot chat
// (inactive, or a status outside the reader vocabulary) is shown as unavailable, but its map
// entry can still be turned off, and doing so never errors.

export type ChatVisibilityMap = Record<string, boolean>;

/** Statuses a reader may still chat; anything else is treated as unavailable. */
const CHATTABLE_STATUSES: readonly string[] = ['active', 'locked', 'upload_disabled'];

/** True once the user has customised visibility at all, which switches chat to the explicit list. */
export function hasCustomVisibility(map: ChatVisibilityMap | undefined): boolean {
    return Boolean(map) && Object.keys(map as ChatVisibilityMap).length > 0;
}

/**
 * Whether a workspace is visible for chat, mirroring the server's fallback.
 *
 * With no custom map every workspace is visible; with a custom map only the ids explicitly set
 * to `true` are.
 */
export function isVisibleForChat(map: ChatVisibilityMap | undefined, id: string): boolean {
    if (!hasCustomVisibility(map)) return true;
    return (map as ChatVisibilityMap)[id] === true;
}

/**
 * Return a new map with one workspace's visibility set, writing only that entry.
 *
 * Additive by the R2 ruling: the other entries are copied through unchanged, so opening a
 * workspace or toggling one never rewrites another.
 */
export function setChatVisibility(map: ChatVisibilityMap | undefined, id: string, visible: boolean): ChatVisibilityMap {
    return { ...(map ?? {}), [id]: visible };
}

/** Whether a workspace's status lets a reader chat it at all. */
export function isChattableStatus(status: string): boolean {
    return CHATTABLE_STATUSES.includes(status);
}

/**
 * The ids visible for chat right now, across the whole directory.
 *
 * `allIds` is every workspace the directory holds, so the empty-map fallback resolves to the
 * real collection rather than the page on screen. With a custom map only the ids set to `true`
 * that still exist are returned, which mirrors the classic snapshot dropping stale entries.
 */
export function visibleIdsFromMap(map: ChatVisibilityMap | undefined, allIds: readonly string[]): string[] {
    if (!hasCustomVisibility(map)) return [...allIds];
    const custom = map as ChatVisibilityMap;
    return allIds.filter((id) => custom[id] === true);
}

/**
 * A new map that marks every given id visible or hidden, merged onto the current map.
 *
 * Additive by the R2 ruling: entries for ids not in the set are copied through unchanged, so a
 * bulk action never silently drops a workspace it did not name.
 */
export function markEvery(map: ChatVisibilityMap | undefined, ids: readonly string[], visible: boolean): ChatVisibilityMap {
    const next: ChatVisibilityMap = { ...(map ?? {}) };
    for (const id of ids) next[id] = visible;
    return next;
}

/**
 * The custom map that makes exactly a saved list's workspaces visible for chat and nothing else.
 *
 * A non-empty list becomes a custom map of just those ids set to `true`; because any custom map
 * hides everything absent, the rest are hidden without enumerating them. An empty list cannot be
 * expressed this way (an empty map means "all visible"), so the caller hides all ids explicitly.
 */
export function mapForSavedList(listIds: readonly string[]): ChatVisibilityMap {
    const next: ChatVisibilityMap = {};
    for (const id of listIds) next[id] = true;
    return next;
}
