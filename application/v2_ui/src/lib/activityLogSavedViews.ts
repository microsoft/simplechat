// activityLogSavedViews.ts
// Named Activity Logs investigations, stored on the administrator's account.
//
// Saved views used to live in this browser's localStorage. They now live in user settings
// (`v2ActivityLogSavedViews`) so they follow the administrator to any browser, following the
// documents explorer's saved views. A view stores the canonical filter query, so a relative
// range such as "last 7 days" stays relative when it is reopened.

import type { ActivityLogSavedView } from './activityLogs';

export const MAX_ACTIVITY_SAVED_VIEWS = 30;
export const MAX_ACTIVITY_VIEW_NAME_LENGTH = 60;
export const MAX_ACTIVITY_VIEW_QUERY_LENGTH = 4096;

/** The localStorage key the browser-only views used, per signed-in user. */
export function legacyActivityViewsKey(userId: string): string {
    return `simplechat.activity-views.${userId}`;
}

function newViewId(): string {
    const cryptoRef = typeof globalThis !== 'undefined' ? globalThis.crypto : undefined;
    if (cryptoRef && typeof cryptoRef.randomUUID === 'function') return cryptoRef.randomUUID();
    return `view-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Coerce stored or imported values into usable views, dropping malformed entries. */
export function parseActivitySavedViews(value: unknown): ActivityLogSavedView[] {
    if (!Array.isArray(value)) return [];
    const views: ActivityLogSavedView[] = [];
    const names = new Set<string>();
    const ids = new Set<string>();
    for (const entry of value) {
        if (!entry || typeof entry !== 'object') continue;
        const record = entry as Record<string, unknown>;
        const name = typeof record.name === 'string' ? record.name.trim().slice(0, MAX_ACTIVITY_VIEW_NAME_LENGTH) : '';
        const query = typeof record.query === 'string' ? record.query.replace(/^\?/, '') : '';
        if (!name || query.length > MAX_ACTIVITY_VIEW_QUERY_LENGTH || names.has(name.toLowerCase())) continue;
        let id = typeof record.id === 'string' && record.id.trim() ? record.id.trim() : newViewId();
        if (ids.has(id)) id = newViewId();
        names.add(name.toLowerCase());
        ids.add(id);
        views.push({ id, name, query });
        if (views.length >= MAX_ACTIVITY_SAVED_VIEWS) break;
    }
    return views;
}

/** Add a view, replacing one with the same name, within the cap. */
export function upsertActivitySavedView(
    views: readonly ActivityLogSavedView[],
    name: string,
    query: string,
): ActivityLogSavedView[] {
    const trimmed = name.trim().slice(0, MAX_ACTIVITY_VIEW_NAME_LENGTH);
    if (!trimmed || query.length > MAX_ACTIVITY_VIEW_QUERY_LENGTH) return [...views];
    const index = views.findIndex((view) => view.name.toLowerCase() === trimmed.toLowerCase());
    if (index !== -1) {
        const next = [...views];
        next[index] = { ...views[index], name: trimmed, query };
        return next;
    }
    return [...views, { id: newViewId(), name: trimmed, query }].slice(-MAX_ACTIVITY_SAVED_VIEWS);
}

export function removeActivitySavedView(views: readonly ActivityLogSavedView[], id: string): ActivityLogSavedView[] {
    return views.filter((view) => view.id !== id);
}

/** Rename a view; a blank name or one another view already uses leaves the list unchanged. */
export function renameActivitySavedView(
    views: readonly ActivityLogSavedView[],
    id: string,
    name: string,
): ActivityLogSavedView[] {
    const trimmed = name.trim().slice(0, MAX_ACTIVITY_VIEW_NAME_LENGTH);
    const clash = views.some((view) => view.id !== id && view.name.toLowerCase() === trimmed.toLowerCase());
    if (!trimmed || clash) return [...views];
    return views.map((view) => (view.id === id ? { ...view, name: trimmed } : view));
}

/** Merge browser-only views into the account's; an account view wins a name clash. */
export function mergeImportedActivityViews(
    account: readonly ActivityLogSavedView[],
    imported: readonly ActivityLogSavedView[],
): ActivityLogSavedView[] {
    const names = new Set(account.map((view) => view.name.toLowerCase()));
    const additions = imported.filter((view) => !names.has(view.name.toLowerCase()));
    return parseActivitySavedViews([...account, ...additions]);
}

/** Views saved by the browser-only version for this user, or [] when there are none. */
export function readLegacyActivityViews(storage: Pick<Storage, 'getItem'>, userId: string): ActivityLogSavedView[] {
    try {
        const raw = storage.getItem(legacyActivityViewsKey(userId));
        return raw ? parseActivitySavedViews(JSON.parse(raw)) : [];
    } catch {
        return [];
    }
}
