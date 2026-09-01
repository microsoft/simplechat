// endpoints.ts
// Typed wrappers around the SimpleChat REST endpoints the V2 UI uses.
//
// Paths and payload shapes were verified against route_backend_conversations.py,
// route_backend_chats.py, route_backend_documents.py and functions_conversation_feed.py.
// Keeping them in one module means a backend path change is a one-line edit here.

import { api, apiUrl, uploadFile, ApiError, API_BASE } from './apiClient';
import type { EnhancedCitationMetadata } from './enhancedCitations';
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

/** Request body for /api/get_citation. Only citation_id is required. */
export interface CitationRequest {
    citation_id: string;
    document_id?: string;
    page_number?: string;
    chunk_id?: string;
}

export const fetchCitation = (payload: CitationRequest) =>
    api.post<Citation>('/api/get_citation', payload);

/* -------------------------------------------------------------------------- */
/* Enhanced citations                                                          */
/* -------------------------------------------------------------------------- */

/**
 * Per-document gate for enhanced rendering.
 *
 * Returns null when the document cannot be resolved. V1 treats that as "attempt enhanced
 * anyway and fall back on error" rather than as a refusal, so callers should not read a
 * null as a denial.
 */
export async function fetchEnhancedCitationMetadata(
    docId: string,
): Promise<EnhancedCitationMetadata | null> {
    try {
        return await api.get<EnhancedCitationMetadata>(
            `/api/enhanced_citations/document_metadata?doc_id=${encodeURIComponent(docId)}`,
        );
    } catch {
        return null;
    }
}

/** Direct URL for a media element's src, so the browser can issue its own requests. */
export function enhancedCitationMediaUrl(kind: 'video' | 'audio', docId: string): string {
    return apiUrl(`/api/enhanced_citations/${kind}?doc_id=${encodeURIComponent(docId)}`);
}

export function enhancedCitationImageUrl(docId: string): string {
    return apiUrl(`/api/enhanced_citations/image?doc_id=${encodeURIComponent(docId)}`);
}

export function enhancedCitationVisioUrl(docId: string, page = 1, download = false): string {
    const params = new URLSearchParams({ doc_id: docId, page: String(page) });
    if (download) {
        params.set('download', 'true');
    }
    return apiUrl(`/api/enhanced_citations/visio?${params.toString()}`);
}

export function workspaceDocumentDownloadUrl(docId: string): string {
    return apiUrl(`/api/workspace_documents/download?doc_id=${encodeURIComponent(docId)}`);
}

export function tabularWorkspaceDownloadUrl(docId: string): string {
    return apiUrl(
        `/api/enhanced_citations/tabular_workspace?doc_id=${encodeURIComponent(docId)}`,
    );
}

export interface PdfCitationResult {
    blob: Blob;
    /**
     * Which page of the returned extract corresponds to the citation.
     *
     * The server returns a narrow window around the cited page rather than the whole
     * document, so the citation is rarely on page 1 of what comes back. This comes from
     * the X-Sub-PDF-Page response header, which a JSON helper would discard.
     */
    page: number;
}

export async function fetchEnhancedCitationPdf(
    docId: string,
    page: number,
    showAll = false,
): Promise<PdfCitationResult> {
    const params = new URLSearchParams({ doc_id: docId, page: String(page) });
    if (showAll) {
        params.set('show_all', 'true');
    }

    const response = await fetch(apiUrl(`/api/enhanced_citations/pdf?${params.toString()}`), {
        credentials: API_BASE ? 'include' : 'same-origin',
    });

    if (!response.ok) {
        const payload = (await response.json().catch(() => ({}))) as { error?: string };
        throw new ApiError(
            payload.error || `Could not load the PDF (${response.status}).`,
            response.status,
            payload,
        );
    }

    const headerPage = Number.parseInt(response.headers.get('X-Sub-PDF-Page') || '1', 10);
    return {
        blob: await response.blob(),
        page: Number.isFinite(headerPage) && headerPage > 0 ? headerPage : 1,
    };
}

export interface TabularPreview {
    filename?: string;
    selected_sheet?: string | null;
    sheet_names?: string[];
    sheet_count?: number;
    total_rows?: number | null;
    total_columns?: number;
    columns?: string[];
    rows?: string[][];
    truncated?: boolean;
}

export function fetchTabularPreview(
    docId: string,
    options: { sheetName?: string; maxRows?: number } = {},
) {
    const params = new URLSearchParams({ doc_id: docId });
    if (options.sheetName) {
        params.set('sheet_name', options.sheetName);
    }
    if (options.maxRows) {
        params.set('max_rows', String(options.maxRows));
    }
    return api.get<TabularPreview>(
        `/api/enhanced_citations/tabular_preview?${params.toString()}`,
    );
}

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
