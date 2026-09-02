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

/**
 * Resolve the scope for a document search.
 *
 * Personal documents are always in scope: the interface has no control for excluding them,
 * so treating them as always selected matches what the user sees.
 */
export function resolveDocumentScope(scope: ScopeState | undefined): DocumentScopeRequest {
    const groupId = id(scope?.activeGroupId);
    const publicId = id(scope?.activePublicWorkspaceId);

    const groupIds = groupId ? [groupId] : [];
    const publicIds = publicId ? [publicId] : [];

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
