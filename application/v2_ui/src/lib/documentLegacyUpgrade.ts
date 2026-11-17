// documentLegacyUpgrade.ts
// What the "update older documents" notice needs apart from React.
//
// A document stored before progress tracking has no `percentage_complete`, and every document
// list says so with one boolean, `needs_legacy_update_check`: the personal list over the user's
// documents, the group list over the group's own current documents, and the public list over the
// workspace's. The three upgrade routes are not alike. The personal route acts on the caller's own
// documents. The classic group and public routes act on the *saved* active workspace, which a V2
// page never relies on (its page names the workspace in every path), and the public one cannot
// write a public document at all, so a V2 group or public workspace calls a route of its own that
// names the workspace and authorizes the caller as a manager of an active one.

import type { DocumentOperation } from './documentOperations';
import type { DocumentReadScope } from './documentReadAdapter';
import type { DocumentListResponse } from './types';
import { isRecord } from './workspaceAuthoring';
import { requireWorkspaceId } from './workspaceContext';

/**
 * Whether a document list says some documents predate progress tracking. Only the boolean the
 * server writes counts: a missing flag, which an older server sends, says nothing is legacy.
 */
export function legacyUpdateNeeded(
    response: Pick<DocumentListResponse, 'needs_legacy_update_check'> | null | undefined,
): boolean {
    return response?.needs_legacy_update_check === true;
}

/**
 * The management operation the group and public upgrade routes authorize as. The upgrade rewrites
 * documents' stored fields, so it is a metadata edit: it is offered to the managers of an active
 * workspace and to nobody else, which is exactly who the server's own hint lists it for.
 */
export const LEGACY_UPGRADE_OPERATION: DocumentOperation = 'edit_metadata';

/** Whether a workspace's operations include the one the upgrade route authorizes as. */
export function canUpgradeLegacyDocuments(supported: ReadonlySet<DocumentOperation>): boolean {
    return supported.has(LEGACY_UPGRADE_OPERATION);
}

export function legacyUpgradePath(scope: DocumentReadScope): string {
    if (scope.kind === 'group') {
        return `/api/groups/${encodeURIComponent(requireWorkspaceId(scope.id))}/documents/upgrade_legacy`;
    }
    if (scope.kind === 'public') {
        return `/api/public-workspaces/${encodeURIComponent(requireWorkspaceId(scope.id))}/documents/upgrade_legacy`;
    }
    return '/api/documents/upgrade_legacy';
}

/** A document the server could not bring up to date, named for the person to find it. */
export interface LegacyUpgradeFailure {
    document_id: string;
    file_name: string | null;
    message: string;
}

export interface LegacyUpgradeOutcome {
    /** The server's own sentence for what happened. */
    message: string;
    /** How many documents the route confirmed upgraded; the personal route reports none. */
    upgraded: number | null;
    /** Whether the route stopped at its per-request limit with older documents still to do. */
    remaining: boolean;
    failures: LegacyUpgradeFailure[];
}

const UNCONFIRMED = 'The server did not confirm the update. Refresh before retrying.';

function readFailures(value: unknown): LegacyUpgradeFailure[] {
    if (!Array.isArray(value)) throw new Error(UNCONFIRMED);
    return value.map((entry) => {
        if (!isRecord(entry) || typeof entry.document_id !== 'string' || !entry.document_id) {
            throw new Error(UNCONFIRMED);
        }
        return {
            document_id: entry.document_id,
            file_name: typeof entry.file_name === 'string' && entry.file_name.trim() ? entry.file_name : null,
            message: typeof entry.message === 'string' && entry.message.trim()
                ? entry.message : 'This document could not be updated.',
        };
    });
}

/**
 * Read an upgrade receipt, refusing one that does not describe this workspace.
 *
 * The personal route answers only a sentence. A group or public route also names its workspace,
 * counts what it upgraded, says whether older documents remain, and lists each document it could
 * not update, so a receipt for another workspace, or one that cannot add up, is never shown as a
 * result for this one.
 */
export function inspectLegacyUpgrade(response: unknown, scope: DocumentReadScope): LegacyUpgradeOutcome {
    if (!isRecord(response) || typeof response.message !== 'string' || !response.message.trim()) {
        throw new Error(UNCONFIRMED);
    }
    if (scope.kind === 'personal') {
        return { message: response.message, upgraded: null, remaining: false, failures: [] };
    }
    const scopeField = scope.kind === 'public' ? 'public_workspace_id' : 'group_id';
    if (response[scopeField] !== scope.id) {
        throw new Error('The update receipt does not match this workspace. Refresh before retrying.');
    }
    if (!Number.isInteger(response.upgraded_count) || Number(response.upgraded_count) < 0
        || typeof response.remaining !== 'boolean') {
        throw new Error(UNCONFIRMED);
    }
    return {
        message: response.message,
        upgraded: Number(response.upgraded_count),
        remaining: response.remaining,
        failures: readFailures(response.errors),
    };
}

export interface LegacyUpgradeCopy {
    heading: string;
    body: string;
}

/**
 * The notice's words, kept with the classic interface's: what is old, and what updating restores.
 * Public workspaces had no classic notice, so theirs follows the group's.
 */
export function legacyUpgradeCopy(scope: DocumentReadScope): LegacyUpgradeCopy {
    if (scope.kind === 'group') {
        return {
            heading: 'Update older group documents',
            body: 'Some documents in this group were uploaded with an older version. Updating them now restores '
                + 'full compatibility, including metadata display and search.',
        };
    }
    if (scope.kind === 'public') {
        return {
            heading: 'Update older public workspace documents',
            body: 'Some documents in this public workspace were uploaded with an older version. Updating them now '
                + 'restores full compatibility, including metadata display and search.',
        };
    }
    return {
        heading: 'Update older documents',
        body: 'Some of your documents were uploaded with an older version. Updating them now restores full '
            + 'compatibility, including metadata display and search.',
    };
}
