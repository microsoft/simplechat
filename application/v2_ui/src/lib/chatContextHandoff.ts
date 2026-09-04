// chatContextHandoff.ts
// Carrying a workspace selection into the chat composer.
//
// Selecting documents in the workspace and pressing Chat used to do this:
//
//     window.location.href = `/chats?search_documents=true&doc_scope=personal&document_ids=…`
//
// which is a full page load into the *classic* interface. A user working in V2 was quietly
// moved to V1 by the one action most likely to follow choosing a document. This module is the
// V2 replacement, and it keeps the classic query vocabulary so a link built by either
// interface is readable by both.
//
// Two routes in, by preference:
//
//   1. Router state. The page that raised the hand-off already holds the document records, so
//      passing them through avoids re-fetching what is in memory and works for every scope --
//      including public workspaces, which have no single-document endpoint to fetch from.
//   2. Query parameters. What a bookmarked, copied or hand-written link has. Ids have to be
//      resolved back into names, which is best-effort per scope.

import {
    fetchGroupDocument,
    fetchPersonalDocument,
    fetchPublicWorkspaceDocuments,
} from './endpoints';
import { documentId as readDocumentId } from './documentExplorer';
import {
    PERSONAL_SCOPE,
    documentContextItem,
    groupScope,
    publicScope,
    tagContextItem,
    type ContextItem,
    type ContextScopeRef,
} from './chatContext';
import type { WorkspaceDocument, WorkspaceRef } from './types';

/**
 * The parameters a hand-off uses, named as the classic client names them.
 *
 * Listed so the composer can strip exactly these after consuming them: leaving them behind
 * would re-apply the same selection every time the page was reloaded or the link re-shared.
 */
export const CONTEXT_HANDOFF_PARAMS = [
    'search_documents',
    'doc_scope',
    'document_id',
    'document_ids',
    'tags',
    'group_id',
    'workspace_id',
] as const;

export interface ContextHandoff {
    documentIds: string[];
    tags: string[];
    docScope: string;
    groupId: string;
    workspaceId: string;
}

/** Items passed directly through router state, skipping id resolution entirely. */
export interface ContextHandoffState {
    contextDocuments?: Array<{ document: WorkspaceDocument; scope: ContextScopeRef }>;
    contextTags?: Array<{ name: string; scope: ContextScopeRef }>;
}

function list(value: string | null): string[] {
    return String(value ?? '')
        .split(',')
        .map((entry) => entry.trim())
        .filter(Boolean);
}

/** Read a hand-off out of the URL, or null when there is not one. */
export function readContextHandoff(params: URLSearchParams): ContextHandoff | null {
    const documentIds = [...list(params.get('document_ids')), ...list(params.get('document_id'))];
    const tags = list(params.get('tags'));

    if (documentIds.length === 0 && tags.length === 0) {
        return null;
    }

    return {
        documentIds: [...new Set(documentIds)],
        tags: [...new Set(tags)],
        docScope: String(params.get('doc_scope') ?? '').trim().toLowerCase(),
        groupId: String(params.get('group_id') ?? '').trim(),
        workspaceId: String(params.get('workspace_id') ?? '').trim(),
    };
}

/** Build the query a workspace page navigates with. */
export function buildContextHandoffParams(options: {
    documentIds?: readonly string[];
    tags?: readonly string[];
    docScope?: string;
    groupId?: string;
    workspaceId?: string;
}): string {
    const params = new URLSearchParams({ search_documents: 'true' });

    if (options.docScope) {
        params.set('doc_scope', options.docScope);
    }
    if (options.documentIds?.length) {
        params.set('document_ids', options.documentIds.join(','));
    }
    if (options.tags?.length) {
        params.set('tags', options.tags.join(','));
    }
    if (options.groupId) {
        params.set('group_id', options.groupId);
    }
    if (options.workspaceId) {
        params.set('workspace_id', options.workspaceId);
    }

    return params.toString();
}

/** Which workspace a hand-off's ids belong to, from the scope it names. */
function handoffScope(
    handoff: ContextHandoff,
    groups: readonly WorkspaceRef[],
    publicWorkspaces: readonly WorkspaceRef[],
): ContextScopeRef {
    if (handoff.docScope === 'group' && handoff.groupId) {
        const match = groups.find((group) => String(group.id) === handoff.groupId);
        return groupScope(match ?? { id: handoff.groupId, name: 'Group workspace' });
    }
    if (handoff.docScope === 'public' && handoff.workspaceId) {
        const match = publicWorkspaces.find(
            (workspace) => String(workspace.id) === handoff.workspaceId,
        );
        return publicScope(match ?? { id: handoff.workspaceId, name: 'Public workspace' });
    }
    return PERSONAL_SCOPE;
}

/**
 * Look a document up so its chip can carry a name rather than an id.
 *
 * Personal and group documents have single-document endpoints. Public workspace documents do
 * not -- only `/versions` exists -- so those are found by scanning the visible list, which is
 * bounded by what the user has made visible in their directory and is therefore small. A
 * document that still cannot be resolved is skipped rather than shown as a bare id: a chip
 * reading `a3f1b2…` tells the reader nothing about what their message is pointed at.
 */
async function resolveDocument(
    id: string,
    scope: ContextScopeRef,
    publicIndex: Map<string, WorkspaceDocument> | null,
    signal?: AbortSignal,
): Promise<WorkspaceDocument | null> {
    try {
        if (scope.kind === 'group') {
            return await fetchGroupDocument(id, signal);
        }
        if (scope.kind === 'public') {
            return publicIndex?.get(id) ?? null;
        }
        return await fetchPersonalDocument(id, signal);
    } catch {
        // A document that was deleted between choosing it and arriving here, or one the
        // caller may not read. Dropping it is the honest outcome; the rest still arrive.
        return null;
    }
}

/**
 * Turn a hand-off into the chips the composer starts with.
 *
 * Router state wins when it is present, because it is both faster and more complete than
 * anything that can be recovered from ids alone.
 */
export async function resolveContextHandoff(
    handoff: ContextHandoff,
    options: {
        groups?: readonly WorkspaceRef[];
        publicWorkspaces?: readonly WorkspaceRef[];
        state?: ContextHandoffState | null;
        signal?: AbortSignal;
    } = {},
): Promise<ContextItem[]> {
    const groups = options.groups ?? [];
    const publicWorkspaces = options.publicWorkspaces ?? [];
    const items: ContextItem[] = [];

    const passed = options.state;
    if (passed?.contextDocuments?.length || passed?.contextTags?.length) {
        for (const entry of passed.contextDocuments ?? []) {
            items.push(documentContextItem(entry.document, entry.scope, items, 'handoff'));
        }
        for (const entry of passed.contextTags ?? []) {
            items.push(tagContextItem(entry.name, entry.scope, items, 'handoff'));
        }
        return items;
    }

    const scope = handoffScope(handoff, groups, publicWorkspaces);

    let publicIndex: Map<string, WorkspaceDocument> | null = null;
    if (scope.kind === 'public' && handoff.documentIds.length > 0) {
        try {
            const listed = await fetchPublicWorkspaceDocuments(
                { page: 1, pageSize: 250 },
                options.signal,
            );
            publicIndex = new Map(
                (listed.documents ?? []).map((document) => [readDocumentId(document), document]),
            );
        } catch {
            publicIndex = null;
        }
    }

    const documents = await Promise.all(
        handoff.documentIds.map((id) =>
            resolveDocument(id, scope, publicIndex, options.signal),
        ),
    );

    for (const document of documents) {
        if (document) {
            items.push(documentContextItem(document, scope, items, 'handoff'));
        }
    }
    for (const tag of handoff.tags) {
        items.push(tagContextItem(tag, scope, items, 'handoff'));
    }

    return items;
}
