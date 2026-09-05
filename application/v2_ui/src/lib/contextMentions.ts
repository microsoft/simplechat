// contextMentions.ts
// Finding the documents, tags and workspaces the `#` menu and the picker popover offer.
//
// The composer can point at three kinds of thing living in three different places, and the
// server has no single endpoint that spans them: personal documents, group documents and
// public workspace documents are three routes with three permission models. So the search is
// a fan-out, and the rules that matter are about what happens when part of it fails.
//
// Every request is settled independently. A user who belongs to a group whose document index
// is briefly unavailable still gets their personal documents, because the alternative -- one
// rejected promise emptying the whole menu -- reads to them as "none of my documents exist".
//
// Tags are cached briefly. They are a small, slow-changing vocabulary fetched whole rather
// than searched server-side, and re-fetching three tag lists on every debounced keystroke is
// work that buys nothing.

import {
    fetchGroupDocumentTags,
    fetchGroupDocuments,
    fetchPersonalDocumentTags,
    fetchPersonalDocuments,
    fetchPublicWorkspaceDocumentTags,
    fetchPublicWorkspaceDocuments,
} from './endpoints';
import { documentId } from './documentExplorer';
import {
    PERSONAL_SCOPE,
    contextKey,
    documentContextItem,
    groupScope,
    publicScope,
    scopeContextItem,
    tagContextItem,
    type ContextAttachment,
    type ContextItem,
    type ContextKind,
    type ContextOrigin,
    type ContextScopeRef,
} from './chatContext';
import type { WorkspaceDocument, WorkspaceRef, WorkspaceTag } from './types';

/** How many rows of each kind a query offers before the menu starts to feel like a list. */
const DOCUMENTS_PER_SCOPE = 6;
const TAG_LIMIT = 5;
const SCOPE_LIMIT = 3;

/** How long a fetched tag vocabulary stays good for. */
const TAG_CACHE_MS = 60_000;

export interface ContextCandidate {
    /** Matches the `key` of the item this becomes, so membership can be tested before building. */
    key: string;
    kind: ContextKind;
    label: string;
    subtitle?: string;
    scope: ContextScopeRef;
    /** Present for documents, so the item keeps the metadata its tooltip shows. */
    document?: WorkspaceDocument;
}

export interface ContextSearchOptions {
    query: string;
    groups?: readonly WorkspaceRef[];
    publicWorkspaces?: readonly WorkspaceRef[];
    /** Whether the deployment offers these at all; both routes are `@enabled_required`. */
    groupsEnabled?: boolean;
    publicEnabled?: boolean;
    signal?: AbortSignal;
}

/** Build the item a chosen candidate becomes. */
export function candidateToContextItem(
    candidate: ContextCandidate,
    existing: readonly ContextItem[],
    origin: ContextOrigin = 'user',
    attachment: ContextAttachment = 'selection',
): ContextItem {
    if (candidate.kind === 'document' && candidate.document) {
        return documentContextItem(candidate.document, candidate.scope, existing, origin, attachment);
    }
    if (candidate.kind === 'tag') {
        return tagContextItem(candidate.label, candidate.scope, existing, origin, attachment);
    }
    return scopeContextItem(candidate.scope, existing, origin, attachment);
}

function documentCandidate(
    document: WorkspaceDocument,
    scope: ContextScopeRef,
): ContextCandidate | null {
    const id = documentId(document);
    if (!id) {
        return null;
    }

    const title = String(document.title ?? '').trim();
    const fileName = String(document.file_name ?? '').trim();

    return {
        key: contextKey('document', id, scope),
        kind: 'document',
        label: title || fileName || 'Untitled',
        // The scope leads: which workspace a document is in is the thing a reader cannot
        // infer from its name, and it is what makes two similarly named files tellable apart.
        subtitle: title && fileName && title !== fileName
            ? `${scope.name} · ${fileName}`
            : scope.name,
        scope,
        document,
    };
}

/**
 * Which workspace a returned document belongs to.
 *
 * The group and public routes can each return documents from several workspaces in one
 * response, so the scope is read off the document rather than assumed from the request.
 */
function scopeForDocument(
    document: WorkspaceDocument,
    fallback: ContextScopeRef,
    byGroupId: Map<string, ContextScopeRef>,
    byWorkspaceId: Map<string, ContextScopeRef>,
): ContextScopeRef {
    const groupId = String(document.group_id ?? '').trim();
    if (groupId) {
        return byGroupId.get(groupId) ?? fallback;
    }
    const workspaceId = String(document.public_workspace_id ?? '').trim();
    if (workspaceId) {
        return byWorkspaceId.get(workspaceId) ?? fallback;
    }
    return fallback;
}

/** Run a request that must not be able to empty the whole menu when it fails. */
async function settled<T>(work: Promise<T>, fallback: T): Promise<T> {
    try {
        return await work;
    } catch {
        // Advisory: the other scopes are unaffected, and a partial menu is more useful than
        // an empty one with no explanation.
        return fallback;
    }
}

/* -------------------------------------------------------------------------- */
/* Tag vocabulary                                                              */
/* -------------------------------------------------------------------------- */

interface ScopedTag {
    name: string;
    scope: ContextScopeRef;
}

let tagCache: { at: number; tags: ScopedTag[] } | null = null;
let tagCacheKey = '';

/** Drop the memoized tag vocabulary, for when one has just been created or renamed. */
export function clearContextTagCache(): void {
    tagCache = null;
}

function readTags(payload: { tags?: WorkspaceTag[] } | null, scope: ContextScopeRef): ScopedTag[] {
    return (payload?.tags ?? [])
        .map((tag) => String(tag?.name ?? '').trim())
        .filter(Boolean)
        .map((name) => ({ name, scope }));
}

async function loadTags(options: ContextSearchOptions): Promise<ScopedTag[]> {
    // Keyed on which scopes are in play, so enabling a group does not keep serving a
    // vocabulary gathered before it was reachable.
    const key = [
        options.groupsEnabled ? 'g' : '',
        options.publicEnabled ? 'p' : '',
        (options.groups ?? []).map((group) => group.id).join(','),
    ].join('|');

    if (tagCache && tagCacheKey === key && Date.now() - tagCache.at < TAG_CACHE_MS) {
        return tagCache.tags;
    }

    const [personal, group, publicTags] = await Promise.all([
        settled(fetchPersonalDocumentTags(options.signal), { tags: [] }),
        options.groupsEnabled
            ? settled(fetchGroupDocumentTags(options.signal), { tags: [] })
            : Promise.resolve({ tags: [] as WorkspaceTag[] }),
        options.publicEnabled
            ? settled(fetchPublicWorkspaceDocumentTags(options.signal), { tags: [] })
            : Promise.resolve({ tags: [] as WorkspaceTag[] }),
    ]);

    const firstGroup = (options.groups ?? [])[0];
    const firstPublic = (options.publicWorkspaces ?? [])[0];

    const tags = [
        ...readTags(personal, PERSONAL_SCOPE),
        // The tag routes return a vocabulary rather than per-workspace lists, so a group tag
        // is attributed to the group the user is working in. Getting this wrong only affects
        // which workspace the chip widens the search to, never whether the tag itself matches.
        ...(firstGroup ? readTags(group, groupScope(firstGroup)) : []),
        ...(firstPublic ? readTags(publicTags, publicScope(firstPublic)) : []),
    ];

    // A superseded keystroke aborts these requests, and `settled` reports an abort as an
    // empty vocabulary. Caching that would answer every `#` for the next minute with no tags
    // at all -- and typing is exactly what aborts them, so it would be the common case.
    if (!options.signal?.aborted) {
        tagCache = { at: Date.now(), tags };
        tagCacheKey = key;
    }
    return tags;
}

/* -------------------------------------------------------------------------- */
/* Search                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * The candidates a `#` query offers.
 *
 * Documents lead because they are the specific thing; tags and whole workspaces are broader
 * and sit below. An empty query is not treated as "match nothing" -- it offers the most
 * recently touched documents, which is what makes a bare `#` useful rather than a dead end.
 */
export async function searchContextCandidates(
    options: ContextSearchOptions,
): Promise<ContextCandidate[]> {
    const needle = String(options.query ?? '').trim();
    const lowered = needle.toLowerCase();

    const groups = options.groups ?? [];
    const publicWorkspaces = options.publicWorkspaces ?? [];
    const groupIds = groups.map((group) => String(group.id ?? '')).filter(Boolean);

    const byGroupId = new Map(groupIds.map((id, index) => [id, groupScope(groups[index])]));
    const byWorkspaceId = new Map(
        publicWorkspaces
            .map((workspace) => [String(workspace.id ?? ''), publicScope(workspace)] as const)
            .filter(([id]) => Boolean(id)),
    );

    const listQuery = { search: needle, page: 1, pageSize: DOCUMENTS_PER_SCOPE };

    const [personal, groupDocs, publicDocs, tags] = await Promise.all([
        settled(fetchPersonalDocuments(listQuery, options.signal), { documents: [] }),
        options.groupsEnabled && groupIds.length > 0
            ? settled(fetchGroupDocuments(groupIds, listQuery, options.signal), {
                  documents: [],
              })
            : Promise.resolve({ documents: [] as WorkspaceDocument[] }),
        options.publicEnabled
            ? settled(fetchPublicWorkspaceDocuments(listQuery, options.signal), {
                  documents: [],
              })
            : Promise.resolve({ documents: [] as WorkspaceDocument[] }),
        settled(loadTags(options), [] as ScopedTag[]),
    ]);

    const candidates: ContextCandidate[] = [];
    const seen = new Set<string>();

    const push = (candidate: ContextCandidate | null) => {
        if (candidate && !seen.has(candidate.key)) {
            seen.add(candidate.key);
            candidates.push(candidate);
        }
    };

    for (const document of personal.documents ?? []) {
        push(documentCandidate(document, PERSONAL_SCOPE));
    }

    // A response can mix workspaces, so each document names its own; these only cover the
    // case where the id is missing from the record entirely.
    const groupFallback = groups[0] ? groupScope(groups[0]) : PERSONAL_SCOPE;
    const publicFallback = publicWorkspaces[0]
        ? publicScope(publicWorkspaces[0])
        : PERSONAL_SCOPE;

    for (const document of groupDocs.documents ?? []) {
        push(
            documentCandidate(
                document,
                scopeForDocument(document, groupFallback, byGroupId, byWorkspaceId),
            ),
        );
    }
    for (const document of publicDocs.documents ?? []) {
        push(
            documentCandidate(
                document,
                scopeForDocument(document, publicFallback, byGroupId, byWorkspaceId),
            ),
        );
    }

    // Tags and workspaces are filtered here rather than server-side: both are short lists
    // already in hand, and a round trip per keystroke to narrow a dozen names is not worth it.
    const matchedTags = tags
        .filter((tag) => !lowered || tag.name.toLowerCase().includes(lowered))
        .slice(0, TAG_LIMIT);
    for (const tag of matchedTags) {
        push({
            key: contextKey('tag', tag.name, tag.scope),
            kind: 'tag',
            label: tag.name,
            subtitle: `Tag · ${tag.scope.name}`,
            scope: tag.scope,
        });
    }

    const allScopes: ContextScopeRef[] = [
        PERSONAL_SCOPE,
        ...(options.groupsEnabled ? groups.map(groupScope) : []),
        ...(options.publicEnabled ? publicWorkspaces.map(publicScope) : []),
    ];
    const matchedScopes = allScopes
        .filter((scope) => !lowered || scope.name.toLowerCase().includes(lowered))
        .slice(0, SCOPE_LIMIT);
    for (const scope of matchedScopes) {
        push({
            key: contextKey('scope', scope.id ?? 'personal', scope),
            kind: 'scope',
            label: scope.name,
            subtitle: 'Everything in this workspace',
            scope,
        });
    }

    return candidates;
}
