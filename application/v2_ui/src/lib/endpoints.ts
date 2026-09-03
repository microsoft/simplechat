// endpoints.ts
// Typed wrappers around the SimpleChat REST endpoints the V2 UI uses.
//
// Paths and payload shapes were verified against route_backend_conversations.py,
// route_backend_chats.py, route_backend_documents.py and functions_conversation_feed.py.
// Keeping them in one module means a backend path change is a one-line edit here.

import { api, apiUrl, uploadFile, ApiError, API_BASE } from './apiClient';
import type { EnhancedCitationMetadata } from './enhancedCitations';
import type { ExportVisualAsset } from './exportVisuals';
import type { MaskAction, MaskedRange, MaskSelection } from './masking';
import type {
    AiNoticeFrequency,
    BootstrapPayload,
    ChatMessage,
    ChatStreamRequest,
    Citation,
    ConversationFeedPage,
    ConversationMetadata,
    ConversationSummary,
    Json,
    PersistedThought,
    WorkspaceDocument,
    WorkspaceTag,
} from './types';

/* -------------------------------------------------------------------------- */
/* Bootstrap                                                                   */
/* -------------------------------------------------------------------------- */

export const fetchBootstrap = (signal?: AbortSignal) =>
    api.get<BootstrapPayload>('/api/v2/bootstrap', signal);

/**
 * Record that the caller has dismissed the AI notice.
 *
 * Deliberately a direct write rather than one routed through `userSettingsStore`. That
 * store debounces, and rolls a failure back silently into a preference cache -- but the
 * route replaces the posted value with its own server-timestamped record, so the cached
 * value would never match what was stored. The button also needs a definite success or
 * failure to decide whether the notice may disappear, which a fire-and-forget write cannot
 * give it.
 *
 * Only `daily` and `once` reach here; `every_session` is a browser-session fact and is kept
 * in sessionStorage, and `non_dismissible` has no dismiss control at all.
 */
export const dismissAiNotice = (hash: string, frequency: AiNoticeFrequency) =>
    api.post<{ message?: string }>('/api/user/settings', {
        settings: { aiNoticeDismissal: { hash, frequency } },
    });

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

/* -------------------------------------------------------------------------- */
/* Conversation summary                                                        */
/* -------------------------------------------------------------------------- */

/**
 * Generate (or regenerate) a conversation summary.
 *
 * The summary is produced on demand and persisted, so it is also returned by the metadata
 * endpoint afterwards. Its body is under `content`, not `text`.
 */
export const generateConversationSummary = (
    conversationId: string,
    body: { model_deployment?: string } = {},
) =>
    api.post<{ success: boolean; summary: ConversationSummary }>(
        `/api/conversations/${encodeURIComponent(conversationId)}/summary`,
        body,
    );

/* -------------------------------------------------------------------------- */
/* Message masking                                                             */
/* -------------------------------------------------------------------------- */

/** Response of POST /api/message/<id>/mask. */
export interface MaskResponse {
    success: boolean;
    message_id: string;
    masked: boolean;
    masked_ranges: MaskedRange[];
}

/**
 * Add or remove a mask on a message.
 *
 * `conversation_id` is optional to the server but lets it read the message by partition key
 * instead of running a cross-partition query, so it is always sent.
 *
 * A `mask_selection` whose text can no longer be located in the stored content is rejected
 * with a 400: the server resolves the selection against the message rather than trusting the
 * offsets, and a selection spanning rendered elements may not correspond to any single span
 * of the original.
 */
export const maskMessage = (
    messageId: string,
    body: {
        action: MaskAction;
        conversation_id: string;
        selection?: MaskSelection;
    },
) => api.post<MaskResponse>(`/api/message/${encodeURIComponent(messageId)}/mask`, body);

/* -------------------------------------------------------------------------- */
/* Message visual styles                                                       */
/* -------------------------------------------------------------------------- */

/** Colours and size saved against one diagram or chart inside a message. */
export interface VisualStyleEntry {
    palette?: string;
    background?: string;
    colors?: Record<string, string>;
    source_hash?: string;
    /** Stage height in pixels, set by dragging the block's resize handle. */
    height?: number;
}

/** Every saved entry for a message, keyed by fence language then by block index. */
export type MessageVisualStyles = Record<string, Record<string, VisualStyleEntry>>;

/** Response of POST /api/message/<id>/visual-style. */
export interface VisualStyleResponse {
    success: boolean;
    message_id: string;
    visual_styles: MessageVisualStyles;
}

/**
 * Save, or clear, the colours and size for one block of one message.
 *
 * A null `style` removes the colours so the block follows the reader's own default again,
 * which is a different outcome from saving a style that happens to equal that default: the
 * default can change later.
 *
 * `height` is deliberately optional rather than nullable-by-default. Omitting the key leaves
 * whatever size is stored alone, so changing colours never resets a diagram someone resized;
 * sending null is what clears it.
 *
 * `conversation_id` lets the server read the message by partition key rather than running a
 * cross-partition query, exactly as the mask endpoint does.
 */
export const setMessageVisualStyle = (
    messageId: string,
    body: {
        conversation_id: string;
        block_kind: string;
        block_index: number;
        source_hash: string;
        style: { palette: string; background: string; colors: Record<string, string> } | null;
        height?: number | null;
    },
) =>
    api.post<VisualStyleResponse>(
        `/api/message/${encodeURIComponent(messageId)}/visual-style`,
        body,
    );

/* -------------------------------------------------------------------------- */
/* Message inspection                                                          */
/* -------------------------------------------------------------------------- */

/**
 * Per-message diagnostics.
 *
 * The response shape depends on the message's role (route_frontend_conversations.py):
 * a **user** message returns its nested `metadata` object alone, while assistant, image and
 * file messages return the **whole document**, with `role`, `model_deployment_name`,
 * citations and so on at the top level and `metadata` nested inside it. Callers must handle
 * both rather than assuming one.
 */
export const fetchMessageMetadata = (messageId: string, signal?: AbortSignal) =>
    api.get<Json>(`/api/message/${encodeURIComponent(messageId)}/metadata`, signal);

/** Response of the persisted-thoughts endpoint. */
export interface MessageThoughtsResponse {
    thoughts: PersistedThought[];
    /** False when `enable_thoughts` is off; the empty list then means "disabled". */
    enabled: boolean;
}

/**
 * Reasoning steps recorded while a message was generated.
 *
 * Thoughts are stored separately from the message, so a historical message carries none of
 * this in its own payload and it has to be fetched per message.
 */
export const fetchMessageThoughts = (
    conversationId: string,
    messageId: string,
    signal?: AbortSignal,
) =>
    api.get<MessageThoughtsResponse>(
        `/api/conversations/${encodeURIComponent(conversationId)}` +
            `/messages/${encodeURIComponent(messageId)}/thoughts`,
        signal,
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

/* -------------------------------------------------------------------------- */
/* Inline image proposals                                                      */
/* -------------------------------------------------------------------------- */

/**
 * Response of POST /api/chat/image-proposals/generate.
 *
 * `image_message` is the stored image, shaped like any other message in the thread, so it can
 * be dropped straight into the message list rather than being held somewhere separate. Its
 * `metadata.image_proposal` carries `source_assistant_message_id`, which is what lets it be
 * shown under the assistant message that proposed it.
 */
export interface ImageProposalResult {
    image_url?: string;
    message_id?: string;
    model_deployment_name?: string;
    conversation_title?: string;
    image_message?: ChatMessage;
}

export interface ImageProposalRequest {
    conversation_id: string;
    assistant_message_id?: string;
    proposal: Json;
}

/**
 * Approve a model-authored image proposal and generate the image.
 *
 * The server re-normalises the proposal and re-checks that the conversation belongs to the
 * caller, so nothing here is a security boundary. Note that the route authorises **personal**
 * conversations only, so approving inside a collaborative conversation returns 403 — a
 * pre-existing limitation of the route, surfaced to the user rather than hidden.
 */
export const generateImageFromProposal = (body: ImageProposalRequest) =>
    api.post<ImageProposalResult>('/api/chat/image-proposals/generate', body);

/* -------------------------------------------------------------------------- */
/* Message export                                                              */
/* -------------------------------------------------------------------------- */

/**
 * Exports rendered by the server.
 *
 * Markdown is produced client-side; no endpoint exists for it.
 *
 * All three endpoints read their parameters with `request.get_json()` and reject a request
 * with no JSON body (`route_backend_conversation_export.py`), so they must be called with
 * `Content-Type: application/json`. A form submission is silently rejected with a 400.
 */
export type MessageExportFormat = 'word' | 'powerpoint' | 'email-draft';

const EXPORT_PATHS: Record<MessageExportFormat, string> = {
    word: '/api/message/export-word',
    powerpoint: '/api/message/export-powerpoint',
    'email-draft': '/api/message/export-email-draft',
};

export const exportMessagePath = (format: MessageExportFormat) => EXPORT_PATHS[format];

/** File extension the server names each download with. */
const EXPORT_EXTENSIONS: Record<'word' | 'powerpoint', string> = {
    word: 'docx',
    powerpoint: 'pptx',
};

interface MessageExportRequest {
    message_id: string;
    conversation_id: string;
    /**
     * Pictures of the diagrams already drawn on screen.
     *
     * The server renders any diagram this does not cover, so sending them is an optimisation
     * and a fidelity choice rather than a requirement: it skips a headless browser launch and
     * keeps whatever colours the reader picked.
     */
    visual_assets?: ExportVisualAsset[];
}

/** `YYYYMMDD_HHMMSS`, matching the server's own download naming. */
function exportTimestamp(): string {
    const now = new Date();
    const pad = (value: number) => String(value).padStart(2, '0');
    return (
        `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}` +
        `_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
    );
}

/** Hand a blob to the browser's download machinery. */
export function saveBlob(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

/** Read an error out of a non-OK export response, whatever its content type. */
async function exportError(response: Response): Promise<ApiError> {
    let message = `Export failed (${response.status})`;
    try {
        const payload = (await response.json()) as { error?: string } | null;
        if (payload?.error) {
            message = payload.error;
        }
    } catch {
        /* A non-JSON error body leaves the status-based message in place. */
    }
    return new ApiError(message, response.status, null);
}

/**
 * Download a message as a Word or PowerPoint file.
 *
 * Both endpoints stream the document itself rather than a link to it, so the response is
 * read as a blob and saved locally.
 */
export async function downloadMessageExport(
    format: 'word' | 'powerpoint',
    body: MessageExportRequest,
): Promise<void> {
    const response = await fetch(apiUrl(EXPORT_PATHS[format]), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', Accept: '*/*' },
        body: JSON.stringify(body),
    });

    if (!response.ok) {
        throw await exportError(response);
    }

    saveBlob(await response.blob(), `message_export_${exportTimestamp()}.${EXPORT_EXTENSIONS[format]}`);
}

/** One image the server extracted from the message for the user to attach by hand. */
export interface EmailDraftAttachment {
    data_uri?: string;
    filename?: string;
    content_type?: string;
}

/** Response of POST /api/message/export-email-draft. */
export interface EmailDraft {
    subject?: string;
    subject_source?: string;
    body?: string;
    attachments?: EmailDraftAttachment[];
}

export async function fetchMessageEmailDraft(body: MessageExportRequest): Promise<EmailDraft> {
    return api.post<EmailDraft>(EXPORT_PATHS['email-draft'], body);
}

/**
 * Save any charts or images the email draft carried.
 *
 * A `mailto:` URL cannot carry attachments, so the server returns the images separately and
 * the user attaches them to the draft themselves. Returns how many were saved so the caller
 * can tell them what to expect.
 */
export function saveEmailDraftAttachments(attachments: EmailDraftAttachment[] | undefined): number {
    if (!Array.isArray(attachments) || attachments.length === 0) {
        return 0;
    }

    let saved = 0;
    attachments.forEach((attachment, index) => {
        const dataUri = String(attachment?.data_uri || '').trim();
        if (!dataUri.startsWith('data:image/')) {
            return;
        }

        const [header, base64] = dataUri.split(',', 2);
        if (!base64) {
            return;
        }

        try {
            const binary = atob(base64);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i += 1) {
                bytes[i] = binary.charCodeAt(i);
            }
            const type =
                attachment.content_type || header.slice(5).split(';')[0] || 'image/png';
            saveBlob(new Blob([bytes], { type }), attachment.filename || `message_chart_${index + 1}.png`);
            saved += 1;
        } catch {
            /* A malformed data URI is skipped rather than failing the whole draft. */
        }
    });

    return saved;
}

/**
 * `mailto:` has no formal length limit but user agents and mail clients impose their own,
 * and an over-long URL is silently dropped by some of them. The body is trimmed to stay
 * inside the most restrictive common ceiling.
 */
const MAILTO_BODY_LIMIT = 1800;

/** Build the `mailto:` URL for a draft, trimming an over-long body. */
export function emailDraftMailtoUrl(draft: EmailDraft): string {
    const subject = draft.subject || 'Shared chat message';
    let body = draft.body || '';

    if (body.length > MAILTO_BODY_LIMIT) {
        body = `${body.slice(0, MAILTO_BODY_LIMIT)}\n\n[Message truncated — see SimpleChat for the full response.]`;
    }

    return `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

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
