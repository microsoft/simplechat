// documentAccessCopy.ts
// What a shared workspace's document explorer tells a viewer who can't change its documents: who
// can, or why no one can right now. Every operation is the server's decision (the
// document_management hint, from functions_group_document_policy.py and
// functions_public_document_policy.py, where only the Owner, Admin and DocumentManager roles manage
// documents, and only an active workspace takes uploads); this only words it for each scope.

import type { GroupWorkspaceStatus } from './workspaceContext';

export type SharedDocumentScope = 'group' | 'public';

export interface SharedDocumentAccess {
    /** The workspace's status, as its context reports it; absent when the host passes none. */
    status?: GroupWorkspaceStatus;
    /** Whether the server's document_management hint was recognized. */
    advertised: boolean;
}

type EmptyReason = 'managers' | 'uploads_disabled' | 'locked' | 'unavailable' | 'unconfirmed';
type RefusalReason = 'managers' | 'locked' | 'unavailable' | 'unconfirmed';

// Complete sentences for each scope, so each reads (and translates) whole. The explorer's heading
// already says there are no documents yet; these say who can add them, or why no one can.
const EMPTY_DESCRIPTIONS: Record<SharedDocumentScope, Record<EmptyReason, string>> = {
    group: {
        managers: "This group's owner, admins and document managers can add documents.",
        uploads_disabled: 'Document uploads are disabled for this group.',
        locked: "This group is locked (read-only), so documents can't be added.",
        unavailable: "Documents can't be added to this group in its current status.",
        unconfirmed: "This group's document permissions couldn't be confirmed. Refresh this workspace to check whether you can add documents.",
    },
    public: {
        managers: "This public workspace's owner, admins and document managers can add documents.",
        uploads_disabled: 'Document uploads are disabled for this public workspace.',
        locked: "This public workspace is locked (read-only), so documents can't be added.",
        unavailable: "Documents can't be added to this public workspace in its current status.",
        unconfirmed: "This public workspace's document permissions couldn't be confirmed. Refresh this workspace to check whether you can add documents.",
    },
};

const MANAGEMENT_REFUSALS: Record<SharedDocumentScope, Record<RefusalReason, string>> = {
    group: {
        managers: "Only this group's owner, admins and document managers can manage its documents.",
        locked: "This group is locked (read-only), so its documents can't be changed.",
        unavailable: "This group's documents can't be changed in its current status.",
        unconfirmed: "This group's document permissions couldn't be confirmed. Refresh this workspace before managing documents.",
    },
    public: {
        managers: "Only this public workspace's owner, admins and document managers can manage its documents.",
        locked: "This public workspace is locked (read-only), so its documents can't be changed.",
        unavailable: "This public workspace's documents can't be changed in its current status.",
        unconfirmed: "This public workspace's document permissions couldn't be confirmed. Refresh this workspace before managing documents.",
    },
};

/** The description an empty explorer shows a viewer who can't upload to it. */
export function emptyDocumentsDescription(scope: SharedDocumentScope, access: SharedDocumentAccess): string {
    const reason: EmptyReason = !access.advertised ? 'unconfirmed'
        : access.status === 'upload_disabled' ? 'uploads_disabled'
            : access.status === 'locked' ? 'locked'
                : access.status === 'inactive' || access.status === 'unknown' ? 'unavailable'
                    : 'managers';
    return EMPTY_DESCRIPTIONS[scope][reason];
}

/** Why a viewer the server grants no document operation at all can't make the change they tried. */
export function documentManagementRefusal(scope: SharedDocumentScope, access: SharedDocumentAccess): string {
    const reason: RefusalReason = !access.advertised ? 'unconfirmed'
        : access.status === 'locked' ? 'locked'
            : access.status === 'inactive' || access.status === 'unknown' ? 'unavailable'
                : 'managers';
    return MANAGEMENT_REFUSALS[scope][reason];
}
