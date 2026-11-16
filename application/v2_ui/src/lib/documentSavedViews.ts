// documentSavedViews.ts
// Named filter combinations pinned in the documents explorer rail.
//
// A saved view is the honest answer to "where are my folders?" in a workspace that files by
// tag. A folder is a place a document sits in; a saved view is a question the workspace
// answers, which is what a flat, multi-tagged store can actually offer. Windows calls these
// saved searches and macOS calls them smart folders, and both sit in the sidebar next to
// real folders precisely because they are used the same way.
//
// They live in user settings rather than in Cosmos because they describe how one person
// prefers to look at their own documents, which is the same class of thing as the view mode
// and the page size stored alongside them.

import type { DocumentPlace, DocumentQuery, DocumentSavedView } from './types';
import { DOCUMENT_PLACES, normalizeTagList } from './documentExplorer';

export const MAX_SAVED_VIEWS = 30;
export const MAX_SAVED_VIEW_NAME_LENGTH = 60;

/** The part of a query a saved view captures: what is shown, not how it is presented. */
export type SavedViewQuery = DocumentSavedView['query'];

/**
 * Reduce a live query to the part worth saving.
 *
 * Sort order, page and page size are deliberately excluded. They describe how the user is
 * reading the list at this moment rather than which documents the view is about, and baking
 * a page number into a saved view would make it land somewhere arbitrary later.
 */
export function savedViewQueryFromQuery(query: DocumentQuery): SavedViewQuery {
    return {
        place: query.place,
        search: query.search.trim(),
        tags: normalizeTagList(query.tags),
        classification: query.classification,
    };
}

/** True when the query narrows anything, and so is worth offering to save. */
export function isSaveableQuery(query: DocumentQuery): boolean {
    const saved = savedViewQueryFromQuery(query);
    return Boolean(
        (saved.place && saved.place !== 'all') ||
            saved.search ||
            saved.tags.length > 0 ||
            saved.classification,
    );
}

/** True when the live query is showing exactly what this saved view describes. */
export function matchesSavedView(query: DocumentQuery, view: DocumentSavedView): boolean {
    const current = savedViewQueryFromQuery(query);
    return (
        current.place === view.query.place &&
        current.search === view.query.search &&
        (current.classification ?? null) === (view.query.classification ?? null) &&
        current.tags.length === view.query.tags.length &&
        current.tags.every((tag, index) => tag === view.query.tags[index])
    );
}

/** Apply a saved view to the live query, returning to page one. */
export function applySavedView(query: DocumentQuery, view: DocumentSavedView): DocumentQuery {
    return {
        ...query,
        place: view.query.place,
        search: view.query.search,
        tags: [...view.query.tags],
        classification: view.query.classification ?? null,
        page: 1,
    };
}

function newSavedViewId(): string {
    // `crypto.randomUUID` is unavailable over plain HTTP on some hosts and in the test
    // runner, and an id that fails to generate would take the whole save with it.
    const cryptoRef = typeof globalThis !== 'undefined' ? globalThis.crypto : undefined;
    if (cryptoRef && typeof cryptoRef.randomUUID === 'function') {
        return cryptoRef.randomUUID();
    }
    return `view-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function createSavedView(name: string, query: DocumentQuery): DocumentSavedView {
    return {
        id: newSavedViewId(),
        name: name.trim().slice(0, MAX_SAVED_VIEW_NAME_LENGTH),
        query: savedViewQueryFromQuery(query),
    };
}

function sanitizePlace(value: unknown): DocumentPlace {
    return DOCUMENT_PLACES.includes(value as DocumentPlace) ? (value as DocumentPlace) : 'all';
}

/**
 * Coerce whatever came back from user settings into usable saved views.
 *
 * Settings are stored as free-form JSON and are writable by an older or newer build, so the
 * stored value is treated as untrusted input. A malformed entry is dropped rather than
 * allowed to reach the rail, where it would render as a view that filters to nothing.
 */
export function parseSavedViews(value: unknown): DocumentSavedView[] {
    if (!Array.isArray(value)) {
        return [];
    }

    const views: DocumentSavedView[] = [];
    const seenIds = new Set<string>();

    for (const entry of value) {
        if (!entry || typeof entry !== 'object') {
            continue;
        }
        const record = entry as Record<string, unknown>;
        const name = String(record.name ?? '').trim();
        if (!name) {
            continue;
        }

        const id = String(record.id ?? '').trim() || newSavedViewId();
        if (seenIds.has(id)) {
            continue;
        }
        seenIds.add(id);

        const rawQuery = (record.query ?? {}) as Record<string, unknown>;
        const classification = rawQuery.classification;

        views.push({
            id,
            name: name.slice(0, MAX_SAVED_VIEW_NAME_LENGTH),
            query: {
                place: sanitizePlace(rawQuery.place),
                search: String(rawQuery.search ?? '').trim(),
                tags: normalizeTagList(
                    Array.isArray(rawQuery.tags) ? rawQuery.tags : [],
                ),
                classification:
                    typeof classification === 'string' && classification.trim()
                        ? classification.trim()
                        : null,
            },
        });

        if (views.length >= MAX_SAVED_VIEWS) {
            break;
        }
    }

    return views;
}

/** Add a view, or replace one that has the same name, keeping the list within its cap. */
export function upsertSavedView(
    views: readonly DocumentSavedView[],
    view: DocumentSavedView,
): DocumentSavedView[] {
    const existingIndex = views.findIndex(
        (candidate) =>
            candidate.id === view.id ||
            candidate.name.toLowerCase() === view.name.toLowerCase(),
    );

    if (existingIndex !== -1) {
        const next = [...views];
        next[existingIndex] = { ...view, id: views[existingIndex].id };
        return next;
    }

    return [...views, view].slice(0, MAX_SAVED_VIEWS);
}

export function removeSavedView(
    views: readonly DocumentSavedView[],
    viewId: string,
): DocumentSavedView[] {
    return views.filter((view) => view.id !== viewId);
}

export function renameSavedView(
    views: readonly DocumentSavedView[],
    viewId: string,
    name: string,
): DocumentSavedView[] {
    const trimmed = name.trim().slice(0, MAX_SAVED_VIEW_NAME_LENGTH);
    if (!trimmed) {
        return [...views];
    }
    return views.map((view) => (view.id === viewId ? { ...view, name: trimmed } : view));
}
