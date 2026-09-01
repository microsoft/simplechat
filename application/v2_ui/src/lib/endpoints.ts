// endpoints.ts
// Typed wrappers around the SimpleChat REST endpoints the V2 UI uses.
//
// Paths and payload shapes were verified against route_backend_conversations.py,
// route_backend_chats.py, route_backend_documents.py and functions_conversation_feed.py.
// Keeping them in one module means a backend path change is a one-line edit here.

import { api, uploadFile } from './apiClient';
import type {
    BootstrapPayload,
    ChatMessage,
    Citation,
    ConversationFeedPage,
    ConversationMetadata,
    Json,
    WorkspaceDocument,
    WorkspaceTag,
} from './types';

/* -------------------------------------------------------------------------- */
/* Bootstrap                                                                   */
/* -------------------------------------------------------------------------- */

export const fetchBootstrap = (signal?: AbortSignal) =>
    api.get<BootstrapPayload>('/api/v2/bootstrap', signal);

/* -------------------------------------------------------------------------- */
/* Conversations                                                               */
/* -------------------------------------------------------------------------- */

export interface ConversationFeedQuery {
    search?: string;
    includeHidden?: boolean;
    pageSize?: number;
    cursor?: string | null;
}

export function fetchConversationFeed(
    query: ConversationFeedQuery = {},
    signal?: AbortSignal,
): Promise<ConversationFeedPage> {
    const params = new URLSearchParams();
    if (query.search) {
        params.set('search', query.search);
    }
    if (query.includeHidden) {
        params.set('include_hidden', 'true');
    }
    if (query.pageSize) {
        params.set('page_size', String(query.pageSize));
    }
    if (query.cursor) {
        params.set('cursor', query.cursor);
    }
    const qs = params.toString();
    return api.get<ConversationFeedPage>(
        `/api/conversations/feed${qs ? `?${qs}` : ''}`,
        signal,
    );
}

export const createConversation = (initialMessage?: string) =>
    api.post<{ conversation_id: string; title: string }>('/api/create_conversation', {
        initial_message: initialMessage ?? '',
    });

export const renameConversation = (conversationId: string, title: string) =>
    api.put<Json>(`/api/conversations/${encodeURIComponent(conversationId)}`, { title });

export const deleteConversation = (conversationId: string) =>
    api.delete<Json>(`/api/conversations/${encodeURIComponent(conversationId)}`);

export const deleteConversations = (conversationIds: string[]) =>
    api.post<Json>('/api/delete_multiple_conversations', {
        conversation_ids: conversationIds,
    });

/**
 * Toggle the pinned state.
 *
 * The server toggles and returns the new value; it does not accept a desired state, so
 * no body is sent.
 */
export const toggleConversationPinned = (conversationId: string) =>
    api.post<{ success: boolean; is_pinned: boolean }>(
        `/api/conversations/${encodeURIComponent(conversationId)}/pin`,
    );

/** Toggle the hidden state. Also a server-side toggle with no request body. */
export const toggleConversationHidden = (conversationId: string) =>
    api.post<{ success: boolean; is_hidden: boolean }>(
        `/api/conversations/${encodeURIComponent(conversationId)}/hide`,
    );

/**
 * Clear the unread marker.
 *
 * Collaboration conversations are stored separately and 404 on the personal endpoint, so
 * they are routed to their own. Callers should only invoke this when the conversation is
 * actually unread.
 */
export const markConversationRead = (conversationId: string, isCollaborative = false) =>
    api.post<Json>(
        isCollaborative
            ? `/api/collaboration/conversations/${encodeURIComponent(conversationId)}/mark-read`
            : `/api/conversations/${encodeURIComponent(conversationId)}/mark-read`,
    );

export const fetchConversationMetadata = (conversationId: string, signal?: AbortSignal) =>
    api.get<ConversationMetadata>(
        `/api/conversations/${encodeURIComponent(conversationId)}/metadata`,
        signal,
    );

/* -------------------------------------------------------------------------- */
/* Messages                                                                    */
/* -------------------------------------------------------------------------- */

export const fetchMessages = (conversationId: string, signal?: AbortSignal) =>
    api.get<{ messages: ChatMessage[] }>(
        `/api/get_messages?conversation_id=${encodeURIComponent(conversationId)}`,
        signal,
    );

/* -------------------------------------------------------------------------- */
/* Citations                                                                   */
/* -------------------------------------------------------------------------- */

export const fetchCitation = (citationId: string) =>
    api.post<Citation>('/api/get_citation', { citation_id: citationId });

/* -------------------------------------------------------------------------- */
/* Documents                                                                   */
/* -------------------------------------------------------------------------- */

export function fetchPersonalDocuments(pageSize = 1000, signal?: AbortSignal) {
    return api.get<{ documents?: WorkspaceDocument[]; items?: WorkspaceDocument[] }>(
        `/api/documents?page_size=${pageSize}`,
        signal,
    );
}

export const fetchPersonalDocumentTags = (signal?: AbortSignal) =>
    api.get<{ tags?: WorkspaceTag[] }>('/api/documents/tags', signal);

export const deletePersonalDocument = (documentId: string) =>
    api.delete<Json>(`/api/documents/${encodeURIComponent(documentId)}`);

/**
 * Upload a file. When `conversationId` is supplied the file is attached to that
 * conversation; otherwise it lands in the user's personal workspace.
 */
export function uploadDocument(
    file: File,
    conversationId?: string | null,
    signal?: AbortSignal,
) {
    const formData = new FormData();
    formData.append('file', file);
    if (conversationId) {
        formData.append('conversation_id', conversationId);
    }
    return uploadFile<{
        success?: boolean;
        conversation_id?: string;
        document_id?: string;
        error?: string;
    }>('/upload', formData, signal);
}

/* -------------------------------------------------------------------------- */
/* Admin settings                                                              */
/* -------------------------------------------------------------------------- */

export const fetchAdminSettings = (signal?: AbortSignal) =>
    api.get<Json>('/api/admin/settings', signal);

export const saveAdminSettings = (settings: Json) =>
    api.post<Json>('/api/admin/settings', settings);
