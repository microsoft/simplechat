// documentAccessCopy.ts
// What a shared workspace's document explorer tells a viewer who can't change its documents: who
// can, or why no one can right now. Every operation is the server's decision (the
// document_management hint, from functions_group_document_policy.py and
// functions_public_document_policy.py, where only the Owner, Admin and DocumentManager roles manage
// documents, and only an active workspace takes uploads); this only words it for each scope.

import type { DocumentOperation } from './documentOperations';
import type { GroupWorkspaceStatus } from './workspaceContext';

export type SharedDocumentScope = 'group' | 'public';

export interface SharedDocumentAccess {
    /** The workspace's status, as its context reports it; absent when the host passes none. */
    status?: GroupWorkspaceStatus;
    /** Whether the server's document_management hint was recognized. */
    advertised: boolean;
}

type UploadReason = 'managers' | 'uploads_disabled' | 'locked' | 'unavailable' | 'unconfirmed';
type ManagementReason = 'managers' | 'locked' | 'unavailable' | 'unconfirmed';

// Complete sentences for each scope, so each reads (and translates) whole. The empty explorer's
// heading already says there are no documents yet; these say who can add them, or why no one can.
const UPLOAD_UNAVAILABLE: Record<SharedDocumentScope, Record<UploadReason, string>> = {
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

const MANAGEMENT_REFUSALS: Record<SharedDocumentScope, Record<ManagementReason, string>> = {
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

function uploadReason(access: SharedDocumentAccess): UploadReason {
    if (!access.advertised) return 'unconfirmed';
    if (access.status === 'upload_disabled') return 'uploads_disabled';
    if (access.status === 'locked') return 'locked';
    if (access.status === 'inactive' || access.status === 'unknown') return 'unavailable';
    return 'managers';
}

function managementReason(access: SharedDocumentAccess): ManagementReason {
    if (!access.advertised) return 'unconfirmed';
    if (access.status === 'locked') return 'locked';
    if (access.status === 'inactive' || access.status === 'unknown') return 'unavailable';
    return 'managers';
}

/**
 * Why a viewer can't add documents to this workspace: the description an empty explorer shows them,
 * and the answer to an upload they try while holding other document operations.
 */
export function documentUploadUnavailable(scope: SharedDocumentScope, access: SharedDocumentAccess): string {
    return UPLOAD_UNAVAILABLE[scope][uploadReason(access)];
}

/** Why a viewer the server grants no document operation at all can't make the change they tried. */
export function documentManagementRefusal(scope: SharedDocumentScope, access: SharedDocumentAccess): string {
    return MANAGEMENT_REFUSALS[scope][managementReason(access)];
}

/**
 * What a shared explorer tells a viewer whose operation it refused: why they can't manage its
 * documents at all, or, for an upload from a viewer who holds other operations, why no upload can
 * happen. Null leaves the explorer's generic answer, because any other refusal is a per-document
 * decision.
 */
export function sharedOperationRefusal(
    scope: SharedDocumentScope, operation: DocumentOperation, supported: ReadonlySet<DocumentOperation>,
    access: SharedDocumentAccess,
): string | null {
    if (supported.size === 0) return documentManagementRefusal(scope, access);
    if (operation === 'upload' && !supported.has('upload')) return documentUploadUnavailable(scope, access);
    return null;
}
