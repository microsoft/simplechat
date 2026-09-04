// chatContext.ts
// What the composer is pointed at: the documents, tags and workspaces a message is grounded in.
//
// V2 shipped the Documents button as a bare on/off mapped to `hybrid_search`, with
// `selectedDocumentIds` present in `ComposerOptions`, forwarded to both the chat request and
// the orchestration seeds, and never populated by anything. This module is the missing middle:
// one list of context items that the `#` menu, the picker popover, the workspace hand-off and
// the orchestration planner all write into, and that the request builders read out of.
//
// Three kinds share the list because they answer the same question -- "what should this look
// at?" -- and the server already takes all three in one request:
//
//   document  -> selected_document_ids
//   tag       -> tags        (becomes tags_filter)
//   scope     -> doc_scope + active_group_ids / active_public_workspace_ids
//
// Identity is the `key`, not the label. Two documents may share a title, and a tag name may
// exist in more than one workspace, so nothing here de-duplicates on what the user sees.

import { documentDisplayName, documentId, normalizeStringList } from './documentExplorer';
import {
    buildContextToken,
    sanitizeContextLabel,
    uniqueContextLabel,
} from './chatContextTokens';
import type { WorkspaceDocument, WorkspaceRef } from './types';

export type ContextKind = 'document' | 'tag' | 'scope';

/**
 * Where an item came from.
 *
 * Only `planner` changes behaviour -- those chips are drawn differently and their removal is
 * recorded as a plan edit rather than a plain deselection -- but knowing that a chip arrived
 * from the workspace hand-off rather than being chosen in the composer is worth keeping for
 * the same reason: it is the difference between something the user did and something that was
 * done for them.
 */
export type ContextOrigin = 'user' | 'handoff' | 'planner';

export type ContextScopeKind = 'personal' | 'group' | 'public';

export interface ContextScopeRef {
    kind: ContextScopeKind;
    /** Null for personal, which has no workspace id: the server derives it from the caller. */
    id: string | null;
    name: string;
}

export interface ContextItem {
    /** Dedupe identity. Never the label. */
    key: string;
    kind: ContextKind;
    /** Document id, tag name, or workspace id. */
    id: string;
    /** The full display name. May be longer than the token's label. */
    label: string;
    /** The literal `#[…]` text this item owns in the message. */
    token: string;
    scope: ContextScopeRef;
    origin: ContextOrigin;
    meta?: {
        fileName?: string;
        classification?: string;
        version?: number;
        tags?: string[];
        /** Set on planner items so a removal can be attributed to the step that asked for it. */
        stepId?: string;
    };
}

export const PERSONAL_SCOPE: ContextScopeRef = {
    kind: 'personal',
    id: null,
    name: 'My workspace',
};

export function groupScope(ref: WorkspaceRef): ContextScopeRef {
    return { kind: 'group', id: String(ref.id ?? ''), name: String(ref.name ?? 'Group') };
}

export function publicScope(ref: WorkspaceRef): ContextScopeRef {
    return {
        kind: 'public',
        id: String(ref.id ?? ''),
        name: String(ref.name ?? 'Public workspace'),
    };
}

/** Stable identity for a scope, used in keys and to group the chip row. */
export function scopeKey(scope: ContextScopeRef): string {
    return `${scope.kind}:${scope.id ?? ''}`;
}

export function contextKey(kind: ContextKind, id: string, scope: ContextScopeRef): string {
    // Documents carry globally unique ids, so their scope is display information rather than
    // part of their identity. Tags and scopes are only unique within a workspace.
    if (kind === 'document') {
        return `document:${id}`;
    }
    return `${kind}:${scopeKey(scope)}:${id.toLowerCase()}`;
}

/** The labels currently spoken for, so a new token can avoid colliding with them. */
function takenLabels(items: readonly ContextItem[]): string[] {
    return items.map((item) => item.token.slice(2, -1));
}

function finish(
    partial: Omit<ContextItem, 'token'>,
    existing: readonly ContextItem[],
): ContextItem {
    const label = uniqueContextLabel(partial.label, takenLabels(existing));
    return { ...partial, token: buildContextToken(label) };
}

/**
 * Turn a workspace document into a context item.
 *
 * The token uses the display title, which is what the reader recognises; the id travels
 * separately in `id`. `documentDisplayName` already decides between an extracted title and a
 * file name, so a document whose title is `MSA_v2_FINAL(3).docx` reads the same here as it
 * does in the explorer.
 */
export function documentContextItem(
    document: WorkspaceDocument,
    scope: ContextScopeRef,
    existing: readonly ContextItem[] = [],
    origin: ContextOrigin = 'user',
): ContextItem {
    const id = documentId(document);
    const { primary, secondary } = documentDisplayName(document);
    const classification = String(document.document_classification ?? '').trim();

    return finish(
        {
            key: contextKey('document', id, scope),
            kind: 'document',
            id,
            label: primary,
            scope,
            origin,
            meta: {
                fileName: secondary ?? (String(document.file_name ?? '').trim() || undefined),
                classification: classification || undefined,
                version:
                    typeof document.version === 'number' ? document.version : undefined,
                tags: normalizeStringList(document.tags),
            },
        },
        existing,
    );
}

export function tagContextItem(
    name: string,
    scope: ContextScopeRef,
    existing: readonly ContextItem[] = [],
    origin: ContextOrigin = 'user',
): ContextItem {
    const tag = String(name ?? '').trim();
    return finish(
        {
            key: contextKey('tag', tag, scope),
            kind: 'tag',
            id: tag,
            label: tag,
            scope,
            origin,
        },
        existing,
    );
}

/**
 * A whole workspace as context.
 *
 * Selecting one does not enumerate its documents -- that would pin a snapshot of the workspace
 * as it was when the chip was added. It widens `doc_scope` instead, so the search covers
 * whatever the workspace holds at the time the message is sent.
 */
export function scopeContextItem(
    scope: ContextScopeRef,
    existing: readonly ContextItem[] = [],
    origin: ContextOrigin = 'user',
): ContextItem {
    return finish(
        {
            key: contextKey('scope', scope.id ?? 'personal', scope),
            kind: 'scope',
            id: scope.id ?? '',
            label: scope.name,
            scope,
            origin,
        },
        existing,
    );
}

/** Add an item unless its key is already present. */
export function addContextItem(
    items: readonly ContextItem[],
    item: ContextItem,
): ContextItem[] {
    if (items.some((entry) => entry.key === item.key)) {
        return items.slice();
    }
    return [...items, item];
}

export function removeContextItem(
    items: readonly ContextItem[],
    key: string,
): ContextItem[] {
    return items.filter((entry) => entry.key !== key);
}

export function hasContextItem(items: readonly ContextItem[], key: string): boolean {
    return items.some((entry) => entry.key === key);
}

/* -------------------------------------------------------------------------- */
/* Derived request fields                                                      */
/* -------------------------------------------------------------------------- */

export function contextDocumentIds(items: readonly ContextItem[]): string[] {
    return items.filter((item) => item.kind === 'document').map((item) => item.id);
}

/**
 * The tag names to filter on.
 *
 * De-duplicated case-insensitively: the same tag picked from two workspaces is one filter, and
 * `build_tags_filter` in functions_search.py joins these with `and`, so sending it twice would
 * narrow the search rather than widen it.
 */
export function contextTags(items: readonly ContextItem[]): string[] {
    const seen = new Set<string>();
    const tags: string[] = [];
    for (const item of items) {
        if (item.kind !== 'tag') {
            continue;
        }
        const key = item.id.toLowerCase();
        if (!seen.has(key)) {
            seen.add(key);
            tags.push(item.id);
        }
    }
    return tags;
}

/**
 * Whether documents and tags should be additive.
 *
 * `_build_document_content_filter` in functions_search.py defaults to `intersection`, which
 * emits `doc_ids and tags` -- so a picked document that does not carry a picked tag matches
 * nothing, and a chip row holding one of each returns no results at all. Assigned Knowledge
 * already passes `union` for this reason (functions_search.py:418).
 *
 * Only sent when both kinds are present, because with one kind the mode has no effect and a
 * needless field in the request is one more thing to explain.
 */
export function contextFilterMode(
    items: readonly ContextItem[],
): 'union' | undefined {
    const hasDocuments = items.some((item) => item.kind === 'document');
    const hasTags = items.some((item) => item.kind === 'tag');
    return hasDocuments && hasTags ? 'union' : undefined;
}

/** The workspaces the chips imply, for `resolveDocumentScope`. */
export function contextScopes(items: readonly ContextItem[]): {
    includesPersonal: boolean;
    groupIds: string[];
    publicWorkspaceIds: string[];
} {
    const groupIds = new Set<string>();
    const publicWorkspaceIds = new Set<string>();
    let includesPersonal = false;

    for (const item of items) {
        if (item.scope.kind === 'personal') {
            includesPersonal = true;
        } else if (item.scope.kind === 'group' && item.scope.id) {
            groupIds.add(item.scope.id);
        } else if (item.scope.kind === 'public' && item.scope.id) {
            publicWorkspaceIds.add(item.scope.id);
        }
    }

    return {
        includesPersonal,
        groupIds: [...groupIds],
        publicWorkspaceIds: [...publicWorkspaceIds],
    };
}

/* -------------------------------------------------------------------------- */
/* Presentation                                                                */
/* -------------------------------------------------------------------------- */

export interface ContextGroup {
    scope: ContextScopeRef;
    key: string;
    items: ContextItem[];
}

const SCOPE_ORDER: Record<ContextScopeKind, number> = {
    personal: 0,
    group: 1,
    public: 2,
};

/**
 * The chip row's grouping.
 *
 * Personal first, then groups, then public workspaces, each holding its items in the order
 * they were added. Ordering is fixed rather than by size so a chip does not migrate across
 * the row when another one is added beside it.
 */
export function groupContextItems(items: readonly ContextItem[]): ContextGroup[] {
    const groups = new Map<string, ContextGroup>();

    for (const item of items) {
        const key = scopeKey(item.scope);
        const existing = groups.get(key);
        if (existing) {
            existing.items.push(item);
        } else {
            groups.set(key, { scope: item.scope, key, items: [item] });
        }
    }

    return [...groups.values()].sort((left, right) => {
        const order = SCOPE_ORDER[left.scope.kind] - SCOPE_ORDER[right.scope.kind];
        return order !== 0 ? order : left.scope.name.localeCompare(right.scope.name);
    });
}

/** `3 documents and 1 tag`, for a collapsed group's summary chip. */
export function describeContextGroup(items: readonly ContextItem[]): string {
    const counts: Array<[number, string, string]> = [
        [items.filter((item) => item.kind === 'document').length, 'document', 'documents'],
        [items.filter((item) => item.kind === 'tag').length, 'tag', 'tags'],
        [items.filter((item) => item.kind === 'scope').length, 'workspace', 'workspaces'],
    ];

    const parts = counts
        .filter(([count]) => count > 0)
        .map(([count, one, many]) => `${count} ${count === 1 ? one : many}`);

    if (parts.length === 0) {
        return 'Nothing selected';
    }
    if (parts.length === 1) {
        return parts[0];
    }
    return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
}

/** A one-line explanation for a chip's tooltip. */
export function describeContextItem(item: ContextItem): string {
    const lines: string[] = [sanitizeContextLabel(item.label) || item.label];

    if (item.kind === 'tag') {
        lines.push(`Tag in ${item.scope.name}`);
    } else if (item.kind === 'scope') {
        lines.push('Every document in this workspace');
    } else {
        lines.push(item.scope.name);
        if (item.meta?.fileName) {
            lines.push(item.meta.fileName);
        }
        if (item.meta?.classification) {
            lines.push(item.meta.classification);
        }
    }

    if (item.origin === 'planner') {
        lines.push('Chosen by the planner');
    }

    return lines.join(' · ');
}
