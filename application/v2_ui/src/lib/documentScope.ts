// documentScope.ts
// Which workspaces a document search should cover.
//
// The scope is not a constant. The classic client computes it from the workspaces currently
// in play (`chat-messages.js`), and sends the matching workspace ids alongside it:
//
//     personal only                -> 'personal'
//     group only                   -> 'group'
//     public only                  -> 'public'
//     more than one kind           -> 'all'
//
// Sending 'all' with no ids is not the same as 'personal'. The server filters the requested
// ids down to what the caller may actually see (`_get_authorized_chat_scope_context`), so an
// 'all' search with no ids silently covers nothing but personal documents — and a user whose
// documents live in a group gets no results with no explanation.

export interface ScopeState {
    /** The group the user is currently working in, if any. */
    activeGroupId?: string | null;
    /** The public workspace the user is currently working in, if any. */
    activePublicWorkspaceId?: string | null;
    /**
     * Groups named by the composer's context chips.
     *
     * Without these a chip pointing at a group document is unreachable: the server filters the
     * requested ids down to what the caller may see, and a group whose id was never sent is not
     * in that set. The document would simply be missing from the answer, with nothing to say
     * why -- which is the same failure this file was written about, arriving by a new route.
     */
    contextGroupIds?: readonly string[];
    /** Public workspaces named by the composer's context chips, for the same reason. */
    contextPublicWorkspaceIds?: readonly string[];
}

export interface DocumentScopeRequest {
    doc_scope: string;
    active_group_ids: string[];
    active_group_id: string | null;
    active_public_workspace_ids: string[];
    active_public_workspace_id: string | null;
}

function id(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

/** Union of the workspace currently in play and any the chips name, in that order. */
function mergeIds(active: unknown, fromContext: readonly string[] | undefined): string[] {
    const merged: string[] = [];
    const seen = new Set<string>();

    for (const candidate of [id(active), ...(fromContext ?? [])]) {
        const value = id(candidate);
        if (value && !seen.has(value)) {
            seen.add(value);
            merged.push(value);
        }
    }
    return merged;
}

/**
 * Resolve the scope for a document search.
 *
 * Personal documents are always in scope. That was originally because the interface had no
 * control for excluding them, and it stays true now that the chip row does: narrowing the
 * scope to the kinds the chips happen to mention would drop personal results that the caller
 * never asked to exclude, and a search that silently covers less is the harder failure to
 * notice. The real narrowing is done by `selected_document_ids` and `tags_filter`, which
 * constrain the result set directly rather than by omission.
 */
export function resolveDocumentScope(scope: ScopeState | undefined): DocumentScopeRequest {
    const groupIds = mergeIds(scope?.activeGroupId, scope?.contextGroupIds);
    const publicIds = mergeIds(
        scope?.activePublicWorkspaceId,
        scope?.contextPublicWorkspaceIds,
    );

    // Personal is always in play, so any additional workspace widens the search to 'all'
    // rather than replacing it.
    const docScope = groupIds.length > 0 || publicIds.length > 0 ? 'all' : 'personal';

    return {
        doc_scope: docScope,
        active_group_ids: groupIds,
        active_group_id: groupIds[0] ?? null,
        active_public_workspace_ids: publicIds,
        active_public_workspace_id: publicIds[0] ?? null,
    };
}
