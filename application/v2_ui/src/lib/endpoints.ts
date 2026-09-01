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
    ChatStreamRequest,
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
/* Message actions                                                             */
/* -------------------------------------------------------------------------- */

export const deleteMessage = (messageId: string, deleteThread = false) =>
    api.delete<Json>(`/api/message/${encodeURIComponent(messageId)}`, {
        delete_thread: deleteThread,
    });

/**
 * Response of the retry and edit endpoints.
 *
 * Neither generates a reply on its own: they create the next thread attempt and hand back
 * a ready-made body to POST to /api/chat/stream, which is what actually produces the
 * response. Skipping that second call leaves the new attempt permanently empty.
 */
export interface AttemptChatRequest {
    success: boolean;
    new_attempt?: number;
    user_message_id?: string;
    chat_request: ChatStreamRequest & { conversation_id: string };
}

export const retryMessage = (
    messageId: string,
    options: { model?: string; reasoning_effort?: string; agent_info?: unknown } = {},
) => api.post<AttemptChatRequest>(`/api/message/${encodeURIComponent(messageId)}/retry`, options);

export const editMessage = (messageId: string, content: string) =>
    api.post<AttemptChatRequest>(`/api/message/${encodeURIComponent(messageId)}/edit`, {
        content,
    });

export const switchAttempt = (messageId: string, direction: 'prev' | 'next') =>
    api.post<{ success: boolean; target_attempt: number; available_attempts: number[] }>(
        `/api/message/${encodeURIComponent(messageId)}/switch-attempt`,
        { direction },
    );

export const submitFeedback = (
    messageId: string,
    conversationId: string,
    feedbackType: 'positive' | 'negative',
    reason = '',
) =>
    api.post<{ success: boolean }>('/feedback/submit', {
        messageId,
        conversationId,
        feedbackType,
        reason,
    });

export const forkConversation = (conversationId: string, messageId: string) =>
    api.post<{ conversation_id?: string }>(
        `/api/conversations/${encodeURIComponent(conversationId)}/fork`,
        { message_id: messageId },
    );

/** Server-rendered exports. Markdown is produced client-side; no endpoint exists for it. */
export type MessageExportFormat = 'word' | 'powerpoint' | 'email-draft';

const EXPORT_PATHS: Record<MessageExportFormat, string> = {
    word: '/api/message/export-word',
    powerpoint: '/api/message/export-powerpoint',
    'email-draft': '/api/message/export-email-draft',
};

export const exportMessagePath = (format: MessageExportFormat) => EXPORT_PATHS[format];

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
