// documentOperations.ts

import { ApiError, apiUrl, CREDENTIALS_MODE, requestWithStatus, uploadFileWithStatus } from './apiClient';
import { isScreeningAvailable } from './contentScreening';
import { readConversationParam } from './conversationUrl';
import { documentId, generatedArtifactRestriction, normalizeStringList, supportsExtractionModeChange } from './documentExplorer';
import type { DocumentReadScope } from './documentReadAdapter';
import {
    bulkDeletePersonalDocuments, bulkTagPersonalDocuments, createPersonalDocumentTag,
    deletePersonalDocumentTag, downloadPersonalDocument, downloadPersonalDocuments,
    extractPersonalDocumentMetadata, filenameFromContentDisposition, reprocessPersonalDocumentExtraction,
    updatePersonalDocumentMetadata, updatePersonalDocumentTag, uploadPersonalDocuments, type BulkTagAction,
    type DocumentMetadataUpdate,
} from './endpoints';
import { isRecord } from './workspaceAuthoring';
import { requireWorkspaceId } from './workspaceContext';
import type { WorkspaceDocument, WorkspaceTag } from './types';

export const DOCUMENT_OPERATIONS = [
    'upload', 'edit_metadata', 'tag_documents', 'manage_tags', 'delete',
    'download', 'extract_metadata', 'reprocess',
] as const;
export type DocumentOperation = typeof DOCUMENT_OPERATIONS[number];
export type SyncedDeleteAction = 'delete_only' | 'ignore_remote';

export interface DocumentDeleteOptions {
    deleteMode: 'current_only' | 'all_versions';
    conversationLinkedDeleteConfirmed?: boolean;
    fileSyncDeleteAction?: SyncedDeleteAction | 'keep_source' | null;
}

export interface DocumentOperationError {
    document_id: string;
    error?: string;
    message?: string;
    needs_confirmation?: boolean;
    file_sync?: { source_id?: string; source_name?: string; remote_path?: string; relative_path?: string };
    options?: Array<{ action: string; label: string }>;
    conversation?: { id?: string; title?: string; url?: string };
}

export interface DocumentBatchOutcome {
    succeeded: string[];
    errors: DocumentOperationError[];
}

export interface DocumentUploadOutcome {
    document_ids: string[];
    processed_filenames: string[];
    errors: string[];
}

/** A downloaded file, with the attachment name the server gave it, or null when it named none. */
export interface DocumentDownload {
    blob: Blob;
    fileName: string | null;
}

export interface TagVocabularyError {
    stage: 'vocabulary';
    /** Group-scoped vocabulary failures carry group_id; public-scoped ones carry public_workspace_id. */
    group_id?: string;
    public_workspace_id?: string;
    error: string;
    message?: string;
}

export type TagOperationError = DocumentOperationError | TagVocabularyError;

export interface TagMutationOutcome {
    tag?: WorkspaceTag;
    documentsUpdated: number;
    success: Array<{ document_id: string; tags: string[] }>;
    errors: TagOperationError[];
    vocabularyRetained: boolean;
}

export interface DocumentOperationAdapter {
    scope: DocumentReadScope;
    supported: ReadonlySet<DocumentOperation>;
    allows: (operation: DocumentOperation, documents?: readonly WorkspaceDocument[]) => boolean;
    upload: (files: File[]) => Promise<DocumentUploadOutcome>;
    editMetadata: (document: WorkspaceDocument, changes: DocumentMetadataUpdate) => Promise<'updated' | 'queued'>;
    tagDocuments: (documents: WorkspaceDocument[], action: BulkTagAction, tags: string[]) => Promise<DocumentBatchOutcome>;
    deleteDocuments: (documents: WorkspaceDocument[], options: DocumentDeleteOptions) => Promise<DocumentBatchOutcome>;
    download: (documents: WorkspaceDocument[]) => Promise<DocumentDownload>;
    extractMetadata: (documents: WorkspaceDocument[]) => Promise<DocumentBatchOutcome>;
    reprocess: (documents: WorkspaceDocument[], mode: 'read' | 'layout') => Promise<DocumentBatchOutcome>;
    createTag: (name: string, color?: string) => Promise<TagMutationOutcome>;
    updateTag: (name: string, changes: { new_name?: string; color?: string }) => Promise<TagMutationOutcome>;
    deleteTag: (name: string) => Promise<TagMutationOutcome>;
}

export function advertisedDocumentOperations(value: unknown): ReadonlySet<DocumentOperation> {
    if (!isRecord(value) || value.schema_version !== 1 || !Array.isArray(value.operations)
        || !value.operations.every((operation) => typeof operation === 'string')) return new Set();
    const offered = value.operations;
    return new Set(DOCUMENT_OPERATIONS.filter((operation) => offered.includes(operation)));
}

export function documentOperationAllowed(
    scope: DocumentReadScope,
    supported: ReadonlySet<DocumentOperation>,
    operation: DocumentOperation,
    documents: readonly WorkspaceDocument[] = [],
): boolean {
    if (!supported.has(operation)) return false;
    if (operation === 'upload' || operation === 'manage_tags') return true;
    if (!documents.length) return false;
    return documents.every((document) => {
        if (!documentId(document) || generatedArtifactRestriction(document)) return false;
        if (scope.kind === 'personal') return isScreeningAvailable(document);
        if (!Array.isArray(document.document_actions) || !document.document_actions.includes(operation)) return false;
        const owned = scope.kind === 'public'
            ? document.public_workspace_id === scope.id
            : document.group_id === scope.id && document.shared_approval_status === 'owner';
        const incoming = scope.kind === 'public'
            ? false
            : Boolean(document.group_id) && document.group_id !== scope.id
                && document.shared_group_active_id === scope.id && document.shared_approval_status === 'approved';
        if (operation === 'delete') return owned;
        if (!isScreeningAvailable(document)) return false;
        if (operation === 'download') return owned || incoming;
        if (document.is_current_version === false) return false;
        if (operation === 'reprocess' && !supportsExtractionModeChange(document)) return false;
        return owned;
    });
}

function operationErrors(value: unknown): DocumentOperationError[] {
    if (value === undefined) return [];
    if (!Array.isArray(value) || value.some((error) =>
        !isRecord(error) || typeof error.document_id !== 'string'
        || (!error.message && !error.error))) {
        throw new Error('The server returned an invalid operation result. Refresh before retrying.');
    }
    return value.map((error) => ({
        ...error,
        document_id: error.document_id,
        error: typeof error.error === 'string' ? error.error : undefined,
        message: typeof error.message === 'string' ? error.message : undefined,
    }));
}

/**
 * A same-origin relative path, normalized: it starts with a single `/`, has no scheme, and
 * resolves against this page's origin to that origin. A protocol-relative URL, a backslash (which
 * a browser may read as a slash), and any whitespace or control character make it none at all.
 */
export function sameOriginRelativePath(value: unknown): string | null {
    if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')
        || /[\\\s\u0000-\u001f\u007f]/.test(value)) {
        return null;
    }
    try {
        const origin = window.location.origin;
        const url = new URL(value, origin);
        return url.origin === origin ? `${url.pathname}${url.search}${url.hash}` : null;
    } catch {
        return null;
    }
}

/**
 * The conversation a conversation-linked delete guard names, for its confirmation to show: the
 * title as text, and the conversation to open natively. Its id is the guard's own conversation id
 * or, without one, the conversation its url names -- read only from a same-origin relative url.
 * The url itself, which points at the classic chat page, is never followed.
 */
export function deleteGuardConversation(
    error: DocumentOperationError,
): { title: string; conversationId: string | null } | null {
    const conversation: unknown = error.conversation;
    if (!isRecord(conversation) || typeof conversation.title !== 'string' || !conversation.title.trim()) return null;
    let conversationId = typeof conversation.id === 'string' ? conversation.id.trim() : '';
    if (!conversationId) {
        const path = sameOriginRelativePath(conversation.url);
        conversationId = path ? readConversationParam(new URL(path, window.location.origin).searchParams) ?? '' : '';
    }
    return { title: conversation.title.trim(), conversationId: conversationId || null };
}

/**
 * The name a download response gives its file, from its Content-Disposition (`filename*` first,
 * then `filename`), reduced to a bare file name: any path and control character is dropped, and a
 * name that is empty or only dots is none at all.
 */
export function attachmentFileName(header: string | null): string | null {
    const named = filenameFromContentDisposition(header);
    if (!named) return null;
    const bare = (named.split(/[\\/]/).pop() ?? '').replace(/[\u0000-\u001f\u007f]/g, '').trim();
    return bare && !/^\.+$/.test(bare) ? bare : null;
}

/**
 * What the explorer saves a download as. A single document keeps its own file name: the name a
 * server gives one file is a lossy `secure_filename` of it (`报告.pdf` arrives as `pdf`). Several
 * are saved under the archive name the server gives, or documents.zip without one. A personal
 * download never carries the server's name, so it is named as it always has been.
 */
export function documentDownloadName(download: DocumentDownload, documents: readonly WorkspaceDocument[]): string {
    if (documents.length === 1) return String(documents[0].file_name ?? 'document');
    return download.fileName ?? 'documents.zip';
}

export function inspectDocumentBatch(
    ids: readonly string[], response: unknown, key: 'success' | 'deleted' | 'queued', strict = false,
): DocumentBatchOutcome {
    if (!isRecord(response) || !Array.isArray(response[key])) {
        throw new Error('The server did not confirm the document outcomes. Refresh before retrying.');
    }
    if (strict && (!Array.isArray(response.errors) || response[key].some((record) =>
        !isRecord(record) || typeof record.document_id !== 'string' || !record.document_id))) {
        throw new Error('The server returned an invalid document receipt. Refresh before retrying.');
    }
    const errors = operationErrors(response.errors);
    const succeeded = response[key].map((record) => typeof record === 'string'
        ? record : isRecord(record) && typeof record.document_id === 'string' ? record.document_id : '');
    if (succeeded.some((id) => !ids.includes(id)) || errors.some((error) => !ids.includes(error.document_id))
        || new Set(succeeded).size !== succeeded.length
        || succeeded.some((id) => errors.some((error) => error.document_id === id))) {
        throw new Error('The server returned conflicting document outcomes. Refresh before retrying.');
    }
    if (key === 'deleted' && (strict || response.deleted_count !== undefined || response.error_count !== undefined)
        && (response.deleted_count !== succeeded.length || response.error_count !== errors.length)) {
        throw new Error('The deletion receipt counts do not match its outcomes. Refresh before retrying.');
    }
    for (const id of ids) {
        if (!succeeded.includes(id) && !errors.some((error) => error.document_id === id)) {
            errors.push({ document_id: id, error: 'outcome_unconfirmed', message: 'The server did not confirm this item. Refresh before retrying.' });
        }
    }
    return { succeeded, errors };
}

async function batchOutcome(
    ids: string[], key: 'success' | 'deleted' | 'queued', request: () => Promise<unknown>, strict = false,
): Promise<DocumentBatchOutcome> {
    try {
        return inspectDocumentBatch(ids, await request(), key, strict);
    } catch (cause) {
        if (cause instanceof ApiError && isRecord(cause.payload)
            && Array.isArray(cause.payload[key]) && Array.isArray(cause.payload.errors)) {
            return inspectDocumentBatch(ids, cause.payload, key, strict);
        }
        throw cause;
    }
}

export function validateTagName(name: string): string {
    if (typeof name !== 'string' || !name.trim() || name.trim().length > 50) {
        throw new Error('Enter a tag name of 1 to 50 characters.');
    }
    // Do not narrow legacy vocabulary to fit a URL; the server owns character policy.
    return name.trim().toLowerCase();
}

function tagTargetName(name: string): string {
    if (typeof name !== 'string' || !name.trim()) throw new Error('Choose an existing tag.');
    return name.trim().toLowerCase();
}

export function normalizeTagColor(color: string): string {
    if (typeof color !== 'string' || !/^#?(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(color.trim())) {
        throw new Error('Choose a valid 3- or 6-digit hex colour.');
    }
    const hex = color.trim().replace(/^#/, '').toLowerCase();
    return `#${hex.length === 3 ? [...hex].map((part) => part + part).join('') : hex}`;
}

function inspectTagMutation(response: unknown, scope: DocumentReadScope, creating = false, expectedName?: string): TagMutationOutcome {
    const native = scope.kind !== 'personal';
    if (!isRecord(response) || (native && creating && (!isRecord(response.tag)
        || typeof response.tag.name !== 'string' || !response.tag.name.trim() || typeof response.tag.color !== 'string'))
        || (native && !creating && (!Array.isArray(response.success) || !Array.isArray(response.errors)
            || typeof response.vocabulary_retained !== 'boolean' || !Number.isInteger(response.documents_updated)
            || Number(response.documents_updated) < 0))) {
        throw new Error('The server did not confirm the tag change. Refresh before retrying.');
    }
    const tag = isRecord(response.tag) && typeof response.tag.name === 'string'
        ? { name: response.tag.name, color: typeof response.tag.color === 'string' ? normalizeTagColor(response.tag.color) : undefined }
        : undefined;
    if (native && expectedName && (!tag || tag.name !== expectedName)) {
        throw new Error('The tag acknowledgement does not match the requested name. Refresh before retrying.');
    }
    const errors: TagOperationError[] = [];
    for (const error of Array.isArray(response.errors) ? response.errors : []) {
        if (isRecord(error) && error.stage === 'vocabulary') {
            const vocabIdentity = scope.kind === 'public' ? error.public_workspace_id : error.group_id;
            if (scope.kind === 'personal' || vocabIdentity !== scope.id || 'document_id' in error
                || typeof error.error !== 'string' || !error.error
                || (error.message !== undefined && typeof error.message !== 'string')) {
                throw new Error('The tag vocabulary error does not match this workspace. Refresh before retrying.');
            }
            errors.push(scope.kind === 'public'
                ? { stage: 'vocabulary', public_workspace_id: scope.id, error: error.error, message: error.message }
                : { stage: 'vocabulary', group_id: scope.id, error: error.error, message: error.message });
        } else errors.push(...operationErrors([error]));
    }
    const success: Array<{ document_id: string; tags: string[] }> = [];
    for (const record of Array.isArray(response.success) ? response.success : []) {
        if (!isRecord(record) || typeof record.document_id !== 'string' || !record.document_id
            || !Array.isArray(record.tags) || !record.tags.every((name) => typeof name === 'string')) {
            throw new Error('The tag propagation receipt is invalid. Refresh before retrying.');
        }
        success.push({ document_id: record.document_id, tags: record.tags });
    }
    return {
        tag, documentsUpdated: typeof response.documents_updated === 'number' ? response.documents_updated : 0,
        success, errors, vocabularyRetained: response.vocabulary_retained === true,
    };
}

export function changedDocumentMetadata(
    document: WorkspaceDocument,
    draft: { title: string; abstract: string; publication_date: string; document_classification: string; authors: string; keywords: string },
): DocumentMetadataUpdate {
    const changes: DocumentMetadataUpdate = {};
    for (const field of ['title', 'abstract', 'publication_date', 'document_classification'] as const) {
        if (draft[field] !== String(document[field] ?? '')) changes[field] = draft[field];
    }
    for (const field of ['authors', 'keywords'] as const) {
        const next = normalizeStringList(draft[field]);
        if (JSON.stringify(next) !== JSON.stringify(normalizeStringList(document[field]))) changes[field] = next;
    }
    return changes;
}

function validateMetadata(changes: DocumentMetadataUpdate) {
    const fields = new Set(['title', 'abstract', 'publication_date', 'document_classification', 'authors', 'keywords', 'tags']);
    if (!isRecord(changes) || !Object.keys(changes).length || Object.entries(changes).some(([field, value]) =>
        !fields.has(field) || (['authors', 'keywords', 'tags'].includes(field)
            ? !Array.isArray(value) || !value.every((item) => typeof item === 'string')
            : typeof value !== 'string'))) {
        throw new Error('Supply only changed document metadata fields with valid values.');
    }
}

function deletePayload(options: DocumentDeleteOptions) {
    if (!['current_only', 'all_versions'].includes(options.deleteMode)
        || (options.fileSyncDeleteAction && !['delete_only', 'ignore_remote'].includes(options.fileSyncDeleteAction))) {
        throw new Error('Choose an explicit revision and file-sync deletion option.');
    }
    return {
        delete_mode: options.deleteMode,
        conversation_linked_delete_confirmed: options.conversationLinkedDeleteConfirmed === true,
        ...(options.fileSyncDeleteAction ? { file_sync_delete_action: options.fileSyncDeleteAction } : {}),
    };
}

function createOperations(scope: DocumentReadScope, supported: ReadonlySet<DocumentOperation>): DocumentOperationAdapter {
    const native = scope.kind !== 'personal';
    const scopeField = scope.kind === 'public' ? 'public_workspace_id' : 'group_id';
    const base = scope.kind === 'group'
        ? `/api/groups/${encodeURIComponent(requireWorkspaceId(scope.id))}/documents`
        : scope.kind === 'public'
            ? `/api/public-workspaces/${encodeURIComponent(requireWorkspaceId(scope.id))}/documents`
            : '/api/documents';
    const allows = (operation: DocumentOperation, documents?: readonly WorkspaceDocument[]) =>
        documentOperationAllowed(scope, supported, operation, documents);
    const requireOperation = (operation: DocumentOperation, documents?: readonly WorkspaceDocument[]) => {
        if (!allows(operation, documents)) throw new Error('This operation is not available for the selected workspace or every selected document.');
    };
    const idsFor = (operation: DocumentOperation, documents: WorkspaceDocument[]) => {
        requireOperation(operation, documents);
        return [...new Set(documents.map(documentId))];
    };
    const nativeRequest = async (method: string, path: string, body?: unknown, statuses = [200, 207]) => {
        const response = await requestWithStatus<unknown>(path, { method, body });
        if (!statuses.includes(response.status) || !isRecord(response.data) || response.data.error
            || (response.status === 207 && (!Array.isArray(response.data.errors) || response.data.errors.length === 0))) {
            throw new Error('The server did not return a complete operation receipt. Refresh before retrying.');
        }
        return response.data;
    };
    const tagMutation = async (request: () => Promise<unknown>, creating = false, expectedName?: string) => {
        requireOperation('manage_tags');
        try {
            return inspectTagMutation(await request(), scope, creating, expectedName);
        } catch (cause) {
            if (cause instanceof ApiError && isRecord(cause.payload) && Array.isArray(cause.payload.errors)
                && typeof cause.payload.vocabulary_retained === 'boolean') return inspectTagMutation(cause.payload, scope, creating, expectedName);
            throw cause;
        }
    };
    return {
        scope, supported, allows,
        upload: async (files) => {
            requireOperation('upload');
            if (!files.length) throw new Error('Choose at least one file to upload.');
            const data = new FormData();
            files.forEach((file) => data.append('file', file));
            let result: unknown;
            try {
                if (native) {
                    const response = await uploadFileWithStatus<unknown>(`${base}/upload`, data);
                    if (![200, 201, 202, 207].includes(response.status) || !isRecord(response.data)
                        || !Array.isArray(response.data.errors)
                        || (response.status === 207 && response.data.errors.length === 0)) {
                        throw new Error('The server did not confirm the upload outcomes. Refresh before retrying.');
                    }
                    result = response.data;
                } else result = await uploadPersonalDocuments(files);
            } catch (cause) {
                if (!(cause instanceof ApiError) || !isRecord(cause.payload) || !Array.isArray(cause.payload.errors)) throw cause;
                result = cause.payload;
            }
            if (!isRecord(result) || !Array.isArray(result.document_ids) || !Array.isArray(result.processed_filenames)
                || !result.document_ids.every((id) => typeof id === 'string' && id)
                || !result.processed_filenames.every((name) => typeof name === 'string')
                || (result.errors !== undefined && (!Array.isArray(result.errors) || !result.errors.every((error) => typeof error === 'string')))) {
                throw new Error('The server did not confirm upload results. Refresh before retrying.');
            }
            return { document_ids: result.document_ids, processed_filenames: result.processed_filenames, errors: result.errors ?? [] };
        },
        editMetadata: async (document, changes) => {
            requireOperation('edit_metadata', [document]);
            validateMetadata(changes);
            if (native) {
                const response = await requestWithStatus<unknown>(`${base}/${encodeURIComponent(documentId(document))}`, { method: 'PATCH', body: changes });
                const result = response.data;
                const fields = Object.keys(changes);
                if (!isRecord(result) || result.document_id !== documentId(document) || result[scopeField] !== scope.id
                    || typeof result.message !== 'string' || result.error
                    || !Array.isArray(result.updated_fields) || result.updated_fields.length !== fields.length
                    || !fields.every((field) => Array.isArray(result.updated_fields) && result.updated_fields.includes(field))
                    || (result.status === 'updated' ? response.status !== 200 : result.status === 'queued' ? response.status !== 202 : true)
                    || (result.errors !== undefined && (!Array.isArray(result.errors) || result.errors.length > 0))) {
                    throw new Error('The server did not confirm the metadata change for this document. Your draft is kept; refresh before retrying.');
                }
                return result.status === 'queued' ? 'queued' : 'updated';
            }
            const result = await updatePersonalDocumentMetadata(documentId(document), changes);
            if (isRecord(result) && (result.success === false || (Array.isArray(result.errors) && result.errors.length))) {
                throw new Error('Metadata was not fully saved. Your draft has been kept; refresh before retrying.');
            }
            return 'updated';
        },
        tagDocuments: async (documents, action, tags) => {
            const ids = idsFor('tag_documents', documents);
            if (!['add_tags', 'remove_tags', 'set_tags'].includes(action)) throw new Error('Choose a supported tag operation.');
            const normalized = [...new Set(tags.map(validateTagName))];
            if (!normalized.length && action !== 'set_tags') throw new Error('Choose at least one tag.');
            return batchOutcome(ids, 'success', () => native
                ? nativeRequest('POST', `${base}/bulk-tag`, { document_ids: ids, action, tags: normalized })
                : bulkTagPersonalDocuments(ids, action, tags), native);
        },
        deleteDocuments: async (documents, options) => {
            const ids = idsFor('delete', documents);
            if (!native) {
                return batchOutcome(ids, 'deleted', () => bulkDeletePersonalDocuments(ids, options));
            }
            const payload = deletePayload(options);
            if (ids.length === 1) {
                const params = new URLSearchParams({ delete_mode: payload.delete_mode });
                if (payload.conversation_linked_delete_confirmed) params.set('conversation_linked_delete_confirmed', 'true');
                if (payload.file_sync_delete_action) params.set('file_sync_delete_action', payload.file_sync_delete_action);
                try {
                    const result = await nativeRequest('DELETE', `${base}/${encodeURIComponent(ids[0])}?${params}`, undefined, [200]);
                    if (typeof result.message !== 'string' || result.deleted_mode !== options.deleteMode
                        || !Array.isArray(result.deleted_document_ids)
                        || !result.deleted_document_ids.every((id) => typeof id === 'string' && id)
                        || !result.deleted_document_ids.includes(ids[0])
                        || (options.deleteMode === 'current_only' && result.deleted_document_ids.length !== 1)
                        || !(result.promoted_document_id === null || typeof result.promoted_document_id === 'string')) {
                        throw new Error('The server did not confirm the requested revision deletion. Refresh before retrying.');
                    }
                    return inspectDocumentBatch(ids, result, 'deleted', true);
                } catch (cause) {
                    if (cause instanceof ApiError && isRecord(cause.payload) && typeof cause.payload.error === 'string') {
                        return { succeeded: [], errors: operationErrors([{ ...cause.payload, document_id: ids[0] }]) };
                    }
                    throw cause;
                }
            }
            return batchOutcome(ids, 'deleted', () => nativeRequest('POST', `${base}/bulk-delete`, { document_ids: ids, ...payload }), true);
        },
        download: async (documents) => {
            const ids = idsFor('download', documents);
            // The personal routes' own names are not read, so a personal download is named as it
            // always has been.
            if (!native) {
                return {
                    blob: await (ids.length === 1 ? downloadPersonalDocument(ids[0]) : downloadPersonalDocuments(ids)),
                    fileName: null,
                };
            }
            const response = await fetch(apiUrl(ids.length === 1
                ? `${base}/${encodeURIComponent(ids[0])}/download` : `${base}/download`), {
                method: ids.length === 1 ? 'GET' : 'POST', credentials: CREDENTIALS_MODE,
                ...(ids.length > 1 ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ document_ids: ids }) } : {}),
            });
            if (response.status !== 200 || response.redirected || !/^attachment(?:;|$)/i.test(response.headers.get('Content-Disposition') ?? '')) {
                throw new ApiError('The download was not authorized or did not return a complete file. No file was saved.', response.status, null);
            }
            return { blob: await response.blob(), fileName: attachmentFileName(response.headers.get('Content-Disposition')) };
        },
        extractMetadata: async (documents) => {
            const ids = idsFor('extract_metadata', documents);
            return batchOutcome(ids, 'queued', () => native
                ? nativeRequest('POST', `${base}/extract_metadata`, { document_ids: ids }, [200, 202, 207]) : extractPersonalDocumentMetadata(ids), native);
        },
        reprocess: async (documents, mode) => {
            const ids = idsFor('reprocess', documents);
            if (!['read', 'layout'].includes(mode)) throw new Error('Choose a supported extraction mode.');
            return batchOutcome(ids, 'queued', () => native
                ? nativeRequest('POST', `${base}/reprocess_extraction`, { document_ids: ids, extraction_mode: mode }, [200, 202, 207])
                : reprocessPersonalDocumentExtraction(ids, mode), native);
        },
        createTag: (name, color) => {
            const tagName = validateTagName(name);
            const normalizedColor = color === undefined ? undefined : normalizeTagColor(color);
            return tagMutation(() => native
                ? nativeRequest('POST', `${base}/tags`, { tag_name: tagName, ...(normalizedColor ? { color: normalizedColor } : {}) }, [201])
                : createPersonalDocumentTag(name, normalizedColor), true, native ? tagName : undefined);
        },
        updateTag: (name, changes) => {
            const tagName = tagTargetName(name);
            const body = {
                ...(changes.new_name !== undefined ? { new_name: validateTagName(changes.new_name) } : {}),
                ...(changes.color !== undefined ? { color: normalizeTagColor(changes.color) } : {}),
            };
            if (!Object.keys(body).length) throw new Error('Change the tag name or colour before saving.');
            return tagMutation(() => native
                ? nativeRequest('PATCH', `${base}/tags/${encodeURIComponent(tagName)}`, body) : updatePersonalDocumentTag(name, body),
            false, native ? body.new_name ?? tagName : undefined);
        },
        deleteTag: (name) => {
            const tagName = tagTargetName(name);
            return tagMutation(() => native
                ? nativeRequest('DELETE', `${base}/tags/${encodeURIComponent(tagName)}`) : deletePersonalDocumentTag(name));
        },
    };
}

export const PERSONAL_DOCUMENT_OPERATIONS = createOperations(
    { kind: 'personal' }, new Set(DOCUMENT_OPERATIONS),
);

export function createGroupDocumentOperations(
    scope: Extract<DocumentReadScope, { kind: 'group' }>, management: unknown,
): DocumentOperationAdapter {
    if (scope.kind !== 'group') throw new Error('Group operations require an explicit group scope.');
    return createOperations({ ...scope, id: requireWorkspaceId(scope.id) }, advertisedDocumentOperations(management));
}

/**
 * Public workspace document operations (M3B). The management block is a server hint that names
 * the operations the viewer may attempt; the empty set (read-only, or an unrecognised block)
 * leaves every mutation gate refusing so no write endpoint is reached. Absence never falls back
 * to personal or group behaviour -- the scope is always public, so every URL and receipt check
 * targets the immutable /api/public-workspaces/<id>/documents family.
 */
export function createPublicDocumentOperations(
    scope: Extract<DocumentReadScope, { kind: 'public' }>, management: unknown,
): DocumentOperationAdapter {
    if (scope.kind !== 'public') throw new Error('Public operations require an explicit public workspace scope.');
    return createOperations({ ...scope, id: requireWorkspaceId(scope.id) }, advertisedDocumentOperations(management));
}
