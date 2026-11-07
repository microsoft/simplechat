// documentTitles.ts
// Turning document ids into something a reader recognises.
//
// The orchestration plan names its documents by id, because that is what the planner works in
// and what `apply_plan_edits` matches on. Shown to a person unchanged, a step reads:
//
//     document_ids: 8f14e45f-ceea-467a-9f47-2c7a1d0b3e55
//
// which tells them nothing about whether the planner picked the right contract -- and deciding
// exactly that is the entire purpose of showing them the plan before it runs.
//
// Resolution is best-effort and cached, including its failures. A document may have been
// deleted, or belong to a workspace the caller can no longer read; re-asking for it on every
// render would turn one unresolvable id into a stream of requests.

import { useEffect, useState } from 'react';
import {
    fetchGroupDocument,
    fetchPersonalDocument,
    fetchPublicWorkspaceDocuments,
} from './endpoints';
import { documentDisplayName, documentId as readDocumentId } from './documentExplorer';

/** id -> title, or null for "asked, and it could not be resolved". */
const titles = new Map<string, string | null>();
/** In-flight lookups, so ten chips for one id make one request. */
const pending = new Map<string, Promise<string | null>>();

let publicIndex: Map<string, string> | null = null;
let publicIndexLoading: Promise<void> | null = null;

/**
 * Index the public workspace documents once.
 *
 * There is no single-document route for these -- only `/versions` -- so the visible list is
 * the only way to name one. It is bounded by what the user has surfaced in their directory.
 */
async function ensurePublicIndex(signal?: AbortSignal): Promise<void> {
    if (publicIndex || publicIndexLoading) {
        await publicIndexLoading;
        return;
    }

    publicIndexLoading = (async () => {
        try {
            const listed = await fetchPublicWorkspaceDocuments({ page: 1, pageSize: 250 }, signal);
            publicIndex = new Map(
                (listed.documents ?? []).map((document) => [
                    readDocumentId(document),
                    documentDisplayName(document).primary,
                ]),
            );
        } catch {
            // An abort is not an answer. Caching an empty index for one would leave every
            // public document shown by id for the rest of the session, and StrictMode aborts
            // the first run of every effect on mount.
            if (!signal?.aborted) {
                publicIndex = new Map();
            }
        } finally {
            publicIndexLoading = null;
        }
    })();

    await publicIndexLoading;
}

async function lookup(id: string, signal?: AbortSignal): Promise<string | null> {
    // Personal first: it is both the most common case and the only one with a cheap exact
    // route. Group second. Public last, because it costs a list.
    try {
        return documentDisplayName(await fetchPersonalDocument(id, signal)).primary;
    } catch {
        // Not personal, or not readable as personal. Fall through.
    }

    try {
        return documentDisplayName(await fetchGroupDocument(id, signal)).primary;
    } catch {
        // Not a group document either.
    }

    try {
        await ensurePublicIndex(signal);
        return publicIndex?.get(id) ?? null;
    } catch {
        return null;
    }
}

/** Resolve ids, reusing anything already known or already being fetched. */
export async function resolveDocumentTitles(
    ids: readonly string[],
    signal?: AbortSignal,
): Promise<Map<string, string>> {
    await Promise.all(
        ids
            .filter((id) => id && !titles.has(id))
            .map((id) => {
                const existing = pending.get(id);
                if (existing) {
                    return existing;
                }
                const work = lookup(id, signal)
                    .then((title) => {
                        // A cancelled lookup has not established that the document is
                        // unnameable, so it must not be remembered as one -- `titles.has(id)`
                        // would then skip it forever and the chip would show a bare uuid for
                        // the rest of the session. StrictMode aborts the first run of every
                        // effect on mount, so this is the ordinary path, not the rare one.
                        if (!signal?.aborted) {
                            titles.set(id, title);
                        }
                        return title;
                    })
                    .finally(() => pending.delete(id));
                pending.set(id, work);
                return work;
            }),
    );

    const resolved = new Map<string, string>();
    for (const id of ids) {
        const title = titles.get(id);
        if (title) {
            resolved.set(id, title);
        }
    }
    return resolved;
}

/**
 * Titles for a set of ids, filled in as they arrive.
 *
 * Returns a map rather than a list so a caller can render the id immediately and swap in the
 * name when it lands, instead of holding the whole plan back on a lookup.
 */
export function useDocumentTitles(ids: readonly string[]): Map<string, string> {
    const key = ids.join(',');
    const [resolved, setResolved] = useState<Map<string, string>>(() => {
        const known = new Map<string, string>();
        for (const id of ids) {
            const title = titles.get(id);
            if (title) {
                known.set(id, title);
            }
        }
        return known;
    });

    useEffect(() => {
        if (ids.length === 0) {
            return;
        }
        const controller = new AbortController();
        let cancelled = false;

        void resolveDocumentTitles(ids, controller.signal).then((found) => {
            if (!cancelled) {
                setResolved(found);
            }
        });

        return () => {
            cancelled = true;
            controller.abort();
        };
        // Keyed on the joined ids: the array is rebuilt on every render, and depending on its
        // identity would restart the lookup forever.
    }, [key]);

    return resolved;
}
