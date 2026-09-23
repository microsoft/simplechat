// documentCollaboration.ts

import { ApiError, requestWithStatus } from './apiClient';
import { documentId, generatedArtifactRestriction } from './documentExplorer';
import { isScreeningAvailable } from './contentScreening';
import type { DocumentReadScope } from './documentReadAdapter';
import { isRecord } from './workspaceAuthoring';
import { requireWorkspaceId } from './workspaceContext';
import type { WorkspaceDocument } from './types';

export const DOCUMENT_COLLABORATION_OPERATIONS = [
    'inspect', 'share', 'unshare', 'approve_share', 'remove_share',
    'approve_artifact', 'reject_artifact', 'cancel_artifact',
] as const;
export type DocumentCollaborationOperation = typeof DOCUMENT_COLLABORATION_OPERATIONS[number];
export type CollaborationMutation = Exclude<DocumentCollaborationOperation, 'inspect'>;
export type GroupDocumentScope = Extract<DocumentReadScope, { kind: 'group' }>;
export type PublicDocumentScope = Extract<DocumentReadScope, { kind: 'public' }>;
// Both native workspace kinds share one collaboration adapter shape. Public advertises only the
// publication (generated-artifact) decisions; cross-workspace sharing stays out of scope until M3D.
export type NativeCollaborationScope = GroupDocumentScope | PublicDocumentScope;
export type DocumentRelationship = 'owner' | 'not_approved' | 'approved' | 'removed' | 'denied';

export interface CollaborationGroup {
    id: string;
    name: string;
    description: string;
}

export interface CollaborationRecipient extends CollaborationGroup {
    approval_status: 'not_approved' | 'approved';
}

export interface DocumentPublicationReview {
    status: string;
    is_requester: boolean;
    requested_by_user_id: string | null;
    requested_by_display_name: string | null;
    requested_at: string | null;
    actions: DocumentCollaborationOperation[];
}

export interface DocumentCollaborationState {
    schema_version: 1;
    group_id: string;
    document_id: string;
    document_version: number;
    etag: string;
    owner_group: { id: string; name: string };
    relationship: DocumentRelationship;
    actions: DocumentCollaborationOperation[];
    recipients: CollaborationRecipient[];
    publication: DocumentPublicationReview | null;
}

export interface CollaborationError {
    stage: string;
    code: string;
    message: string;
}

export interface CollaborationReceipt {
    schema_version: 1;
    group_id: string;
    document_id: string;
    action: CollaborationMutation;
    target_group_id?: string;
    status: 'applied' | 'unchanged' | 'queued' | 'partial';
    state: string;
    errors: CollaborationError[];
}

export interface CollaborationTargets {
    groups: CollaborationGroup[];
    page: number;
    page_size: number;
    total_count: number;
}

export interface DocumentCollaborationAdapter {
    scope: NativeCollaborationScope;
    supported: ReadonlySet<DocumentCollaborationOperation>;
    allows: (operation: DocumentCollaborationOperation, document: WorkspaceDocument | null, state?: DocumentCollaborationState) => boolean;
    read: (document: WorkspaceDocument, signal?: AbortSignal) => Promise<DocumentCollaborationState>;
    readRepair: (documentId: string, signal?: AbortSignal) => Promise<DocumentCollaborationState>;
    targets: (document: WorkspaceDocument, state: DocumentCollaborationState, query: { search: string; page: number; pageSize: number }, signal?: AbortSignal) => Promise<CollaborationTargets>;
    mutate: (document: WorkspaceDocument | null, state: DocumentCollaborationState, operation: CollaborationMutation, targetGroupId?: string, repairReceipt?: CollaborationReceipt) => Promise<CollaborationReceipt>;
}

function operationList(value: unknown): DocumentCollaborationOperation[] | null {
    if (!Array.isArray(value) || !value.every((operation) => typeof operation === 'string')) return null;
    return DOCUMENT_COLLABORATION_OPERATIONS.filter((operation) => value.includes(operation));
}

export function advertisedDocumentCollaboration(value: unknown): ReadonlySet<DocumentCollaborationOperation> {
    if (!isRecord(value) || value.schema_version !== 1) return new Set();
    return new Set(operationList(value.operations) ?? []);
}

function isNullableString(value: unknown): value is string | null {
    return value === null || typeof value === 'string';
}

function isGroup(value: unknown): value is CollaborationGroup {
    return isRecord(value) && typeof value.id === 'string' && Boolean(value.id)
        && typeof value.name === 'string' && typeof value.description === 'string';
}

const PUBLICATION_STATUSES = [
    'pending_approval', 'approved', 'approval_failed', 'rejected', 'cancelled', 'unavailable',
] as const;

function parsePublication(raw: unknown): DocumentPublicationReview {
    if (!isRecord(raw) || typeof raw.status !== 'string'
        || !(PUBLICATION_STATUSES as readonly string[]).includes(raw.status)
        || typeof raw.is_requester !== 'boolean' || !isNullableString(raw.requested_by_user_id)
        || !isNullableString(raw.requested_by_display_name) || !isNullableString(raw.requested_at)) {
        throw new Error('The publication request could not be verified. Use classic review or refresh.');
    }
    const publicationActions = operationList(raw.actions);
    if (!publicationActions) throw new Error('The publication permissions could not be verified.');
    if (raw.status === 'unavailable' && publicationActions.some((action) => action !== 'inspect')) {
        throw new Error('An unavailable publication cannot grant a decision.');
    }
    return {
        status: raw.status, is_requester: raw.is_requester,
        requested_by_user_id: raw.requested_by_user_id, requested_by_display_name: raw.requested_by_display_name,
        requested_at: raw.requested_at, actions: publicationActions,
    };
}

export function parseDocumentCollaborationState(
    value: unknown, groupId: string, id: string,
): DocumentCollaborationState {
    if (!isRecord(value) || value.schema_version !== 1 || value.group_id !== groupId || value.document_id !== id
        || typeof value.document_version !== 'number' || !Number.isInteger(value.document_version) || value.document_version < 1
        || typeof value.etag !== 'string' || !value.etag.trim()
        || !isRecord(value.owner_group) || typeof value.owner_group.id !== 'string' || !value.owner_group.id
        || typeof value.owner_group.name !== 'string'
        || typeof value.relationship !== 'string'
        || !['owner', 'not_approved', 'approved', 'removed', 'denied'].includes(value.relationship)
        || !Array.isArray(value.recipients)) {
        throw new Error('The sharing details do not identify this group and document. Refresh before making a decision.');
    }
    const actions = operationList(value.actions);
    if (!actions || ((value.relationship === 'owner') !== (value.owner_group.id === groupId))) {
        throw new Error('The sharing relationship could not be verified. Refresh before making a decision.');
    }
    const repair = value.relationship === 'removed' || value.relationship === 'denied';
    if (repair && (actions.some((action) => action !== 'inspect' && action !== 'remove_share')
        || value.recipients.length !== 0 || value.publication !== null)) {
        throw new Error('A removed relationship cannot grant ordinary access or publication actions.');
    }
    const recipients: CollaborationRecipient[] = [];
    for (const recipient of value.recipients) {
        if (!isGroup(recipient) || !isRecord(recipient) || recipient.id === value.owner_group.id
            || (recipient.approval_status !== 'approved' && recipient.approval_status !== 'not_approved')
            || recipients.some((entry) => entry.id === recipient.id)
            || (value.relationship !== 'owner' && recipient.id !== groupId)) {
            throw new Error('The recipient list could not be verified. Refresh before making a decision.');
        }
        requireWorkspaceId(recipient.id);
        recipients.push({
            id: recipient.id, name: recipient.name, description: recipient.description,
            approval_status: recipient.approval_status,
        });
    }
    const publication = value.publication === null ? null : parsePublication(value.publication);
    requireWorkspaceId(value.owner_group.id);
    return {
        schema_version: 1, group_id: groupId, document_id: id, document_version: value.document_version,
        etag: value.etag, owner_group: { id: value.owner_group.id, name: value.owner_group.name },
        relationship: value.relationship === 'owner' ? 'owner' : value.relationship === 'approved' ? 'approved'
            : value.relationship === 'removed' ? 'removed' : value.relationship === 'denied' ? 'denied' : 'not_approved',
        actions, recipients, publication,
    };
}

export function isCollaborationRepair(state: DocumentCollaborationState): boolean {
    return state.relationship === 'removed' || state.relationship === 'denied';
}

const RESULT_STATES: Record<CollaborationMutation, readonly string[]> = {
    share: ['not_approved', 'approved'],
    unshare: ['removed'],
    approve_share: ['approved'],
    remove_share: ['denied', 'removed'],
    approve_artifact: ['approved', 'approval_failed'],
    reject_artifact: ['rejected'],
    cancel_artifact: ['cancelled'],
};

export function parseCollaborationReceipt(
    value: unknown, httpStatus: number, scope: NativeCollaborationScope, id: string,
    operation: CollaborationMutation, targetGroupId?: string,
): CollaborationReceipt {
    const workspaceId = requireWorkspaceId(scope.id);
    const identityKey = scope.kind === 'public' ? 'public_workspace_id' : 'group_id';
    if (!isRecord(value) || value.schema_version !== 1 || value[identityKey] !== workspaceId || value.document_id !== id
        || value.action !== operation || typeof value.state !== 'string' || !RESULT_STATES[operation].includes(value.state)
        || (targetGroupId ? value.target_group_id !== targetGroupId : Object.hasOwn(value, 'target_group_id'))
        || !Array.isArray(value.errors)) {
        throw new Error('The server did not confirm this exact sharing or publication decision. Refresh before retrying.');
    }
    const status = value.status;
    const validStatus = ((status === 'applied' || status === 'unchanged') && httpStatus === 200 && value.errors.length === 0)
        || (status === 'queued' && httpStatus === 202 && operation === 'approve_artifact' && value.state === 'approved' && value.errors.length === 0)
        || (status === 'partial' && httpStatus === 207 && value.errors.length > 0);
    if (!validStatus || (value.state === 'approval_failed' && status !== 'partial')) {
        throw new Error('The decision outcome is incomplete or ambiguous. Refresh its status; do not repeat it blindly.');
    }
    const errors: CollaborationError[] = value.errors.map((error) => {
        if (!isRecord(error) || typeof error.stage !== 'string' || !error.stage
            || typeof error.code !== 'string' || !error.code || typeof error.message !== 'string' || !error.message) {
            throw new Error('The decision returned invalid repair details. Refresh before retrying.');
        }
        return { stage: error.stage, code: error.code, message: error.message };
    });
    return {
        schema_version: 1, group_id: workspaceId, document_id: id, action: operation,
        ...(targetGroupId ? { target_group_id: targetGroupId } : {}),
        status: status === 'partial' ? 'partial' : status === 'queued' ? 'queued' : status === 'unchanged' ? 'unchanged' : 'applied',
        state: value.state, errors,
    };
}

export function createDocumentCollaboration(
    scope: GroupDocumentScope, capability: unknown,
): DocumentCollaborationAdapter {
    if (scope.kind !== 'group') throw new Error('Group collaboration requires an explicit group.');
    const groupId = requireWorkspaceId(scope.id);
    const supported = advertisedDocumentCollaboration(capability);
    const documentPath = (id: string) =>
        `/api/groups/${encodeURIComponent(groupId)}/documents/${encodeURIComponent(requireWorkspaceId(id))}`;
    const allows = (operation: DocumentCollaborationOperation, document: WorkspaceDocument | null, state?: DocumentCollaborationState) => {
        if (!document) {
            return Boolean(state && state.group_id === groupId && state.document_id && state.etag.trim()
                && isCollaborationRepair(state) && supported.has(operation) && state.actions.includes(operation)
                && (operation === 'inspect' || operation === 'remove_share'));
        }
        const id = documentId(document);
        if (!id || !supported.has(operation) || !Array.isArray(document.document_collaboration_actions)
            || !document.document_collaboration_actions.includes(operation)
            || (document.group_id !== groupId && document.shared_group_active_id !== groupId)) return false;
        if (!state) return operation === 'inspect';
        if (state.group_id !== groupId || state.document_id !== id || !state.etag.trim() || !state.actions.includes(operation)) return false;
        if (isCollaborationRepair(state)) return operation === 'inspect' || operation === 'remove_share';
        if ((operation === 'share' || operation === 'approve_share')
            && (document.is_current_version === false || !isScreeningAvailable(document) || generatedArtifactRestriction(document))) return false;
        if (operation === 'share' || operation === 'unshare') {
            return state.relationship === 'owner' && (operation !== 'share' || document.is_current_version !== false);
        }
        if (operation === 'approve_share' || operation === 'remove_share') return state.relationship !== 'owner';
        if (operation.endsWith('_artifact')) {
            return Boolean(state.relationship === 'owner' && state.publication?.actions.includes(operation)
                && (operation !== 'approve_artifact' || document.is_current_version !== false)
                && (operation !== 'cancel_artifact' || state.publication.is_requester));
        }
        return true;
    };
    const requireAllowed = (operation: DocumentCollaborationOperation, document: WorkspaceDocument | null, state?: DocumentCollaborationState) => {
        if (!allows(operation, document, state)) throw new Error('This collaboration action is not currently permitted for this group and document.');
    };
    return {
        scope: { ...scope, id: groupId }, supported, allows,
        read: async (document, signal) => {
            requireAllowed('inspect', document);
            const id = documentId(document);
            const response = await requestWithStatus<unknown>(`${documentPath(id)}/sharing`, { signal });
            if (response.status !== 200) throw new Error('Sharing details are not available. Refresh or use classic review.');
            return parseDocumentCollaborationState(response.data, groupId, id);
        },
        readRepair: async (id, signal) => {
            if (!supported.has('inspect')) throw new Error('Sharing inspection is not supported by this workspace.');
            const response = await requestWithStatus<unknown>(`${documentPath(id)}/sharing`, { signal });
            if (response.status !== 200) throw new Error('The previous sharing request could not be verified.');
            const state = parseDocumentCollaborationState(response.data, groupId, id);
            if (!isCollaborationRepair(state)) throw new Error('No verified access-removal repair is available for this document.');
            return state;
        },
        targets: async (document, state, query, signal) => {
            requireAllowed('share', document, state);
            if (!Number.isInteger(query.page) || query.page < 1 || !Number.isInteger(query.pageSize) || query.pageSize < 1) {
                throw new Error('Choose a valid recipient page.');
            }
            const params = new URLSearchParams({ page: String(query.page), page_size: String(query.pageSize) });
            if (query.search.trim()) params.set('search', query.search.trim());
            const response = await requestWithStatus<unknown>(`${documentPath(documentId(document))}/sharing/targets?${params}`, { signal });
            const value = response.data;
            if (response.status !== 200 || !isRecord(value) || !Array.isArray(value.groups)
                || value.page !== query.page || value.page_size !== query.pageSize
                || typeof value.total_count !== 'number' || !Number.isInteger(value.total_count) || value.total_count < 0) {
                throw new Error('The recipient search returned an invalid page. Retry the search.');
            }
            const groups: CollaborationGroup[] = [];
            for (const group of value.groups) {
                if (!isGroup(group) || group.id === groupId || groups.some((entry) => entry.id === group.id)) {
                    throw new Error('The recipient search returned an invalid target. Retry the search.');
                }
                requireWorkspaceId(group.id);
                groups.push({ id: group.id, name: group.name, description: group.description });
            }
            return { groups, page: query.page, page_size: query.pageSize, total_count: value.total_count };
        },
        mutate: async (document, state, operation, targetGroupId, repairReceipt) => {
            requireAllowed(operation, document, state);
            const hasTarget = operation === 'share' || operation === 'unshare';
            if (hasTarget) {
                if (!targetGroupId || requireWorkspaceId(targetGroupId) === groupId) throw new Error('Choose a different recipient group.');
                const confirmedRepair = repairReceipt?.schema_version === 1 && repairReceipt.group_id === groupId
                    && repairReceipt.document_id === state.document_id && repairReceipt.action === 'unshare'
                    && repairReceipt.target_group_id === targetGroupId && repairReceipt.status === 'partial'
                    && repairReceipt.state === 'removed' && repairReceipt.errors.length > 0;
                if (repairReceipt && (!confirmedRepair || state.recipients.some((recipient) => recipient.id === targetGroupId))) {
                    throw new Error('The previous cleanup no longer matches the current relationship. Review the new state instead.');
                }
                if (operation === 'unshare' && !state.recipients.some((recipient) => recipient.id === targetGroupId) && !confirmedRepair) {
                    throw new Error('That recipient is no longer in the reviewed sharing state. Refresh before revoking access.');
                }
            } else if (targetGroupId !== undefined) throw new Error('This decision does not accept a recipient override.');
            if (repairReceipt && operation !== 'unshare') throw new Error('This decision does not accept an owner-revocation repair receipt.');
            const id = document ? documentId(document) : state.document_id;
            const base = documentPath(id);
            const paths: Record<CollaborationMutation, string> = {
                share: `${base}/share`,
                unshare: `${base}/share/${encodeURIComponent(targetGroupId ?? '')}`,
                approve_share: `${base}/approve-share`,
                remove_share: `${base}/received-share`,
                approve_artifact: `${base}/artifact/approve`,
                reject_artifact: `${base}/artifact/reject`,
                cancel_artifact: `${base}/artifact/cancel`,
            };
            const response = await requestWithStatus<unknown>(paths[operation], {
                method: operation === 'unshare' || operation === 'remove_share' ? 'DELETE' : 'POST',
                body: { expected_etag: state.etag, ...(operation === 'share' ? { target_group_id: targetGroupId } : {}) },
            });
            const confirmed = parseCollaborationReceipt(response.data, response.status, scope, id, operation, targetGroupId);
            if (operation === 'share' && state.recipients.some((recipient) =>
                recipient.id === targetGroupId && recipient.approval_status === 'approved') && confirmed.state !== 'approved') {
                throw new Error('The receipt would reset an existing approval. Refresh sharing state before continuing.');
            }
            if (operation === 'remove_share') {
                const expected = state.relationship === 'not_approved' || state.relationship === 'denied' ? 'denied' : 'removed';
                if (confirmed.state !== expected) throw new Error('The removal receipt does not match the reviewed relationship. Refresh before retrying.');
            }
            return confirmed;
        },
    };
}

/**
 * Parse the slim public /publication state into the shared collaboration shape. Public workspaces
 * expose only the generated-artifact decision, so the sharing-specific fields are synthesized as an
 * owned, recipient-free relationship. The immutable-target identity check mirrors the group reader:
 * a payload that does not carry the requested public_workspace_id and document id is refused.
 */
export function parsePublicPublicationState(
    value: unknown, workspaceId: string, id: string, workspaceName: string,
): DocumentCollaborationState {
    if (!isRecord(value) || value.schema_version !== 1 || value.public_workspace_id !== workspaceId || value.document_id !== id
        || typeof value.document_version !== 'number' || !Number.isInteger(value.document_version) || value.document_version < 1
        || typeof value.etag !== 'string' || !value.etag.trim()) {
        throw new Error('The publication details do not identify this workspace and document. Refresh before making a decision.');
    }
    const publication = value.publication === null || value.publication === undefined
        ? null : parsePublication(value.publication);
    const artifactActions = publication
        ? publication.actions.filter((action) => action.endsWith('_artifact'))
        : [];
    requireWorkspaceId(workspaceId);
    return {
        schema_version: 1, group_id: workspaceId, document_id: id, document_version: value.document_version,
        etag: value.etag, owner_group: { id: workspaceId, name: workspaceName },
        relationship: 'owner', actions: ['inspect', ...artifactActions],
        recipients: [], publication,
    };
}

/**
 * Public collaboration adapter: publication (generated-artifact) decisions only. Cross-workspace
 * sharing is deliberately unsupported here (M3D), so the sharing operations always deny and the
 * repair/targets paths raise. Every decision is immutable-target against the workspace in the path.
 */
export function createPublicDocumentCollaboration(
    scope: PublicDocumentScope, capability: unknown,
): DocumentCollaborationAdapter {
    if (scope.kind !== 'public') throw new Error('Public collaboration requires an explicit public workspace.');
    const workspaceId = requireWorkspaceId(scope.id);
    const supported = advertisedDocumentCollaboration(capability);
    const documentPath = (id: string) =>
        `/api/public-workspaces/${encodeURIComponent(workspaceId)}/documents/${encodeURIComponent(requireWorkspaceId(id))}`;
    const allows = (operation: DocumentCollaborationOperation, document: WorkspaceDocument | null, state?: DocumentCollaborationState) => {
        if (!document) return false;
        const id = documentId(document);
        if (!id || !supported.has(operation) || !Array.isArray(document.document_collaboration_actions)
            || !document.document_collaboration_actions.includes(operation)
            || document.public_workspace_id !== workspaceId) return false;
        if (operation === 'share' || operation === 'unshare' || operation === 'approve_share' || operation === 'remove_share') return false;
        if (!state) return operation === 'inspect';
        if (state.group_id !== workspaceId || state.document_id !== id || !state.etag.trim() || !state.actions.includes(operation)) return false;
        if (operation === 'inspect') return true;
        if (operation.endsWith('_artifact')) {
            return Boolean(state.publication?.actions.includes(operation)
                && (operation !== 'approve_artifact' || document.is_current_version !== false)
                && (operation !== 'cancel_artifact' || state.publication.is_requester));
        }
        return false;
    };
    const requireAllowed = (operation: DocumentCollaborationOperation, document: WorkspaceDocument | null, state?: DocumentCollaborationState) => {
        if (!allows(operation, document, state)) throw new Error('This publication action is not currently permitted for this workspace and document.');
    };
    return {
        scope: { ...scope, id: workspaceId }, supported, allows,
        read: async (document, signal) => {
            requireAllowed('inspect', document);
            const id = documentId(document);
            const response = await requestWithStatus<unknown>(`${documentPath(id)}/publication`, { signal });
            if (response.status !== 200) throw new Error('Publication details are not available. Refresh or use classic review.');
            return parsePublicPublicationState(response.data, workspaceId, id, scope.name);
        },
        readRepair: async () => {
            throw new Error('Public workspaces have no access-removal cleanup to repair.');
        },
        targets: async () => {
            throw new Error('Public workspaces do not share revisions with recipient workspaces.');
        },
        mutate: async (document, state, operation, targetGroupId, repairReceipt) => {
            requireAllowed(operation, document, state);
            if (targetGroupId !== undefined) throw new Error('Public publication decisions do not accept a recipient override.');
            if (repairReceipt) throw new Error('Public publication decisions do not accept a repair receipt.');
            if (!operation.endsWith('_artifact')) throw new Error('Public workspaces support only publication decisions.');
            const id = document ? documentId(document) : state.document_id;
            const base = documentPath(id);
            const paths: Partial<Record<CollaborationMutation, string>> = {
                approve_artifact: `${base}/artifact/approve`,
                reject_artifact: `${base}/artifact/reject`,
                cancel_artifact: `${base}/artifact/cancel`,
            };
            const response = await requestWithStatus<unknown>(paths[operation]!, {
                method: 'POST', body: { expected_etag: state.etag },
            });
            return parseCollaborationReceipt(response.data, response.status, scope, id, operation);
        },
    };
}

export function collaborationFailure(cause: unknown, scopeKind: 'group' | 'public' = 'group'): string {
    const place = scopeKind === 'public' ? 'workspace' : 'group';
    if (cause instanceof ApiError && (cause.status === 409 || cause.status === 412)) {
        return 'The document or decision changed. Your input is kept. Refresh review details before deciding again.';
    }
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
        return `This document or review is no longer available to you in this ${place}. Refresh to confirm its status.`;
    }
    return cause instanceof Error ? cause.message : 'The decision was not confirmed. Refresh its status before retrying.';
}
