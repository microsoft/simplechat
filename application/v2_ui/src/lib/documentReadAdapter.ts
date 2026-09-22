// documentReadAdapter.ts

import { api } from './apiClient';
import { isScreeningAvailable } from './contentScreening';
import {
    buildDocumentListParams, DEFAULT_DOCUMENT_QUERY, DOCUMENT_SORT_FIELDS, documentId,
    generatedArtifactRestriction,
} from './documentExplorer';
import {
    fetchPersonalDocument, fetchPersonalDocumentFacets, fetchPersonalDocuments,
    fetchPersonalDocumentTags, fetchPersonalDocumentVersions,
} from './endpoints';
import { requireWorkspaceId, workspaceScopeKey, type GroupWorkspaceContext, type PublicWorkspaceContext } from './workspaceContext';
import { isRecord } from './workspaceAuthoring';
import type {
    DocumentFacets, DocumentListResponse, DocumentQuery, DocumentSortField,
    DocumentVersionsResponse, WorkspaceDocument, WorkspaceTag,
} from './types';

export type DocumentReadScope =
    | { kind: 'personal' }
    | { kind: 'group'; id: string; name: string }
    | { kind: 'public'; id: string; name: string };

export interface DocumentReadAdapter {
    scope: DocumentReadScope;
    queries: {
        sortFields: readonly DocumentSortField[];
        facets: boolean;
        places: boolean;
    };
    list: (query: Partial<DocumentQuery>, signal?: AbortSignal) => Promise<DocumentListResponse>;
    tags: (signal?: AbortSignal) => Promise<{ tags?: WorkspaceTag[] }>;
    facets: (signal?: AbortSignal) => Promise<DocumentFacets>;
    detail: (id: string, signal?: AbortSignal) => Promise<WorkspaceDocument>;
    versions: (id: string, signal?: AbortSignal) => Promise<DocumentVersionsResponse>;
}

export const PERSONAL_DOCUMENT_READER: DocumentReadAdapter = {
    scope: { kind: 'personal' },
    queries: { sortFields: DOCUMENT_SORT_FIELDS, facets: true, places: true },
    list: fetchPersonalDocuments,
    tags: fetchPersonalDocumentTags,
    facets: fetchPersonalDocumentFacets,
    detail: fetchPersonalDocument,
    versions: fetchPersonalDocumentVersions,
};

export function documentExplorerScopeKey(viewerId: string, scope: DocumentReadScope): string {
    return workspaceScopeKey(viewerId, {
        kind: scope.kind,
        id: scope.kind === 'personal' ? viewerId : scope.id,
    });
}

function groupReadUrl(groupId: string, suffix = '', params = new URLSearchParams()): string {
    params.set('group_id', requireWorkspaceId(groupId));
    return `/api/group_documents${suffix}?${params}`;
}

function assertGroupDocumentScope(document: WorkspaceDocument, groupId: string, id?: string) {
    if (!document || !documentId(document) || typeof document.group_id !== 'string' || !document.group_id
        || (id && documentId(document) !== id)
        || (document.group_id !== groupId && document.shared_group_active_id !== groupId)) {
        throw new Error('The document response does not match this group. Refresh and try again.');
    }
}

/** Explicit single-group reads never use active preferences or the chat aggregate. */
export async function fetchScopedGroupDocument(
    groupId: string, id: string, signal?: AbortSignal,
): Promise<WorkspaceDocument> {
    const response = await api.get<WorkspaceDocument>(
        groupReadUrl(groupId, `/${encodeURIComponent(requireWorkspaceId(id))}`), signal,
    );
    assertGroupDocumentScope(response, groupId, id);
    return response;
}

export async function fetchScopedGroupDocumentTags(groupId: string, signal?: AbortSignal) {
    const response = await api.get<{ tags?: WorkspaceTag[] }>(groupReadUrl(groupId, '/tags'), signal);
    if (!Array.isArray(response?.tags) || response.tags.some((tag) =>
        !tag || typeof tag.name !== 'string' || !tag.name.trim()
        || !Number.isInteger(tag.count) || Number(tag.count) < 0)) {
        throw new Error('The group returned invalid document tags. Refresh and try again.');
    }
    return response;
}

export function createGroupDocumentReader(
    groupId: string,
    name: string,
    capabilities: GroupWorkspaceContext['document_queries'],
): DocumentReadAdapter {
    requireWorkspaceId(groupId);
    const sortFields = DOCUMENT_SORT_FIELDS.filter((field) => capabilities.sort_fields.includes(field));
    return {
        scope: { kind: 'group', id: groupId, name },
        queries: { sortFields, facets: capabilities.facets, places: capabilities.places },
        list: async (query, signal) => {
            const supported = {
                ...query,
                place: capabilities.places ? query.place ?? 'all' : 'all',
                sortBy: sortFields.includes(query.sortBy ?? '_ts') ? query.sortBy : sortFields[0],
            };
            const params = new URLSearchParams(buildDocumentListParams(supported));
            if (sortFields.length === 0) {
                params.delete('sort_by');
                params.delete('sort_order');
            }
            const response = await api.get<DocumentListResponse>(groupReadUrl(groupId, '', params), signal);
            if (!Array.isArray(response.documents) || !Number.isInteger(response.total_count)
                || Number(response.total_count) < 0 || !Number.isInteger(response.page)
                || Number(response.page) < 1 || !Number.isInteger(response.page_size)
                || Number(response.page_size) < 1) {
                throw new Error('The group returned an invalid document page. Refresh and try again.');
            }
            response.documents.forEach((document) => assertGroupDocumentScope(document, groupId));
            return response;
        },
        tags: (signal) => fetchScopedGroupDocumentTags(groupId, signal),
        facets: async (signal) => {
            if (!capabilities.facets) {
                throw new Error('Document counts are not supported by this workspace.');
            }
            const response = await api.get<DocumentFacets>(groupReadUrl(groupId, '/facets'), signal);
            if (!response || !isRecord(response.by_tag) || !isRecord(response.by_classification)
                || [
                    response.total, response.untagged, response.processing, response.errors,
                    response.recent, response.shared_with_me,
                    ...Object.values(response.by_tag), ...Object.values(response.by_classification),
                ].some((count) => typeof count !== 'number' || !Number.isInteger(count) || count < 0)) {
                throw new Error('The group returned invalid document counts. Refresh and try again.');
            }
            return response;
        },
        detail: (id, signal) => fetchScopedGroupDocument(groupId, id, signal),
        versions: async (id, signal) => {
            const response = await api.get<DocumentVersionsResponse>(
                groupReadUrl(groupId, `/${encodeURIComponent(requireWorkspaceId(id))}/versions`), signal,
            );
            if (response.document_id !== id || response.group_id !== groupId || !Array.isArray(response.versions)) {
                throw new Error('The version history does not match this group document. Refresh and try again.');
            }
            response.versions.forEach((document) => assertGroupDocumentScope(document, groupId));
            return response;
        },
    };
}

function publicReadUrl(workspaceId: string, suffix = '', params = new URLSearchParams()): string {
    const id = encodeURIComponent(requireWorkspaceId(workspaceId));
    const query = params.toString();
    return `/api/public-workspaces/${id}/documents${suffix}${query ? `?${query}` : ''}`;
}

function assertPublicDocumentScope(document: WorkspaceDocument, workspaceId: string, id?: string) {
    if (!document || !documentId(document) || typeof document.public_workspace_id !== 'string'
        || !document.public_workspace_id
        || (id && documentId(document) !== id)
        || document.public_workspace_id !== workspaceId) {
        throw new Error('The document response does not match this public workspace. Refresh and try again.');
    }
}

/** Explicit single-workspace public reads never use active preferences or the chat aggregate. */
export async function fetchScopedPublicDocument(
    workspaceId: string, id: string, signal?: AbortSignal,
): Promise<WorkspaceDocument> {
    const response = await api.get<WorkspaceDocument>(
        publicReadUrl(workspaceId, `/${encodeURIComponent(requireWorkspaceId(id))}`), signal,
    );
    assertPublicDocumentScope(response, workspaceId, id);
    return response;
}

export async function fetchScopedPublicDocumentTags(workspaceId: string, signal?: AbortSignal) {
    const response = await api.get<{ tags?: WorkspaceTag[] }>(publicReadUrl(workspaceId, '/tags'), signal);
    if (!Array.isArray(response?.tags) || response.tags.some((tag) =>
        !tag || typeof tag.name !== 'string' || !tag.name.trim()
        || !Number.isInteger(tag.count) || Number(tag.count) < 0)) {
        throw new Error('The public workspace returned invalid document tags. Refresh and try again.');
    }
    return response;
}

export function createPublicDocumentReader(
    workspaceId: string,
    name: string,
    capabilities: PublicWorkspaceContext['document_queries'],
): DocumentReadAdapter {
    requireWorkspaceId(workspaceId);
    const sortFields = DOCUMENT_SORT_FIELDS.filter((field) => capabilities.sort_fields.includes(field));
    return {
        scope: { kind: 'public', id: workspaceId, name },
        queries: { sortFields, facets: capabilities.facets, places: capabilities.places },
        list: async (query, signal) => {
            const supported = {
                ...query,
                place: capabilities.places ? query.place ?? 'all' : 'all',
                sortBy: sortFields.includes(query.sortBy ?? '_ts') ? query.sortBy : sortFields[0],
            };
            const params = new URLSearchParams(buildDocumentListParams(supported));
            if (sortFields.length === 0) {
                params.delete('sort_by');
                params.delete('sort_order');
            }
            const response = await api.get<DocumentListResponse>(publicReadUrl(workspaceId, '', params), signal);
            if (!Array.isArray(response.documents) || !Number.isInteger(response.total_count)
                || Number(response.total_count) < 0 || !Number.isInteger(response.page)
                || Number(response.page) < 1 || !Number.isInteger(response.page_size)
                || Number(response.page_size) < 1) {
                throw new Error('The public workspace returned an invalid document page. Refresh and try again.');
            }
            response.documents.forEach((document) => assertPublicDocumentScope(document, workspaceId));
            return response;
        },
        tags: (signal) => fetchScopedPublicDocumentTags(workspaceId, signal),
        facets: async (signal) => {
            if (!capabilities.facets) {
                throw new Error('Document counts are not supported by this workspace.');
            }
            // Public facets deliberately omit `shared_with_me`; validating it would reject the
            // contracted response and, absent, visiblePlaces() never offers a Shared place.
            const response = await api.get<DocumentFacets>(publicReadUrl(workspaceId, '/facets'), signal);
            if (!response || !isRecord(response.by_tag) || !isRecord(response.by_classification)
                || [
                    response.total, response.untagged, response.processing, response.errors, response.recent,
                    ...Object.values(response.by_tag), ...Object.values(response.by_classification),
                ].some((count) => typeof count !== 'number' || !Number.isInteger(count) || count < 0)) {
                throw new Error('The public workspace returned invalid document counts. Refresh and try again.');
            }
            return response;
        },
        detail: (id, signal) => fetchScopedPublicDocument(workspaceId, id, signal),
        versions: async (id, signal) => {
            const response = await api.get<DocumentVersionsResponse>(
                publicReadUrl(workspaceId, `/${encodeURIComponent(requireWorkspaceId(id))}/versions`), signal,
            );
            if (response.document_id !== id || response.public_workspace_id !== workspaceId
                || !Array.isArray(response.versions)) {
                throw new Error('The version history does not match this public document. Refresh and try again.');
            }
            response.versions.forEach((document) => assertPublicDocumentScope(document, workspaceId));
            return response;
        },
    };
}

export function supportedDocumentQuery(query: DocumentQuery, reader: DocumentReadAdapter): DocumentQuery {
    return {
        ...query,
        place: reader.queries.places ? query.place : 'all',
        sortBy: reader.queries.sortFields.includes(query.sortBy)
            ? query.sortBy : reader.queries.sortFields[0] ?? DEFAULT_DOCUMENT_QUERY.sortBy,
    };
}

export function documentSelectionReason(
    document: WorkspaceDocument, scope: DocumentReadScope, canChat = true,
): string | null {
    const publicationRestriction = generatedArtifactRestriction(document);
    if (publicationRestriction) return publicationRestriction;
    if (!isScreeningAvailable(document)) {
        return 'Held sources cannot be selected for chat. An authorized reviewer must resolve the hold in Content review.';
    }
    if (scope.kind === 'group') {
        const owned = document.group_id === scope.id && document.shared_approval_status === 'owner';
        const shared = Boolean(document.group_id) && document.group_id !== scope.id && document.shared_group_active_id === scope.id
            && document.shared_approval_status === 'approved';
        if (!owned && !shared) {
            return document.shared_approval_status === 'not_approved'
                ? 'This shared document is awaiting approval and cannot be selected for chat.'
                : 'This document is not approved for chat in this group.';
        }
        if (!canChat) return 'Chat is not currently available for this group.';
    }
    if (scope.kind === 'public') {
        if (document.public_workspace_id !== scope.id) {
            return 'This document is not part of this public workspace.';
        }
        if (!canChat) return 'Chat is not currently available for this public workspace.';
    }
    return null;
}

export function groupDocumentOrigin(document: WorkspaceDocument, groupId: string): string {
    if (document.group_id === groupId) return 'Owned by this group';
    const owner = document.owner_group_name || 'another group';
    if (document.shared_approval_status === 'not_approved') return `Shared by ${owner} (pending approval)`;
    return document.shared_approval_status === 'approved' && document.shared_group_active_id === groupId
        ? `Shared by ${owner}` : 'Sharing not confirmed for this group';
}
