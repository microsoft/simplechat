// endpoints.ts
// Typed wrappers around the SimpleChat REST endpoints the V2 UI uses.
//
// Paths and payload shapes were verified against route_backend_conversations.py,
// route_backend_chats.py, route_backend_documents.py and functions_conversation_feed.py.
// Keeping them in one module means a backend path change is a one-line edit here.

import { api, apiUrl, uploadFile, ApiError, API_BASE, CREDENTIALS_MODE } from './apiClient';
import { buildDocumentListParams } from './documentExplorer';
import { artifactDownloadPath } from './generatedArtifacts';
import type { EnhancedCitationMetadata } from './enhancedCitations';
import type { ExportVisualAsset } from './exportVisuals';
import type { GeneratedArtifact, GeneratedRunStatus } from './generatedArtifacts';
import type { MaskAction, MaskedRange, MaskSelection } from './masking';
import type {
    AiNoticeFrequency,
    BootstrapPayload,
    ChatMessage,
    ChatStreamRequest,
    Citation,
    CollaborationConversation,
    ConversationFeedPage,
    ConversationMetadata,
    ConversationSummary,
    DocumentFacets,
    DocumentListResponse,
    DocumentQuery,
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

/** Which family of endpoints a conversation belongs to. */
export type ConversationKind = 'personal' | 'collaborative';

/** Response of GET /api/conversations/<id>/kind. */
export interface ConversationKindResponse {
    conversation_id: string;
    kind: ConversationKind;
    /** Present only for a shared conversation, so opening one costs a single request. */
    conversation?: CollaborationConversation;
}

/**
 * Resolve whether a conversation is personal or shared, and confirm it exists.
 *
 * Needed for a conversation reached from a link, which is not in the loaded rail and so has no
 * row to read a kind from. Neither message endpoint can stand in for this: both answer 200 with
 * an empty list for a conversation that is not there, so a deleted one would otherwise open as
 * an empty chat and stay in the address bar.
 *
 * A 404 covers "no such conversation" and "not yours" alike; the server does not distinguish
 * them, and neither should a caller.
 */
export const fetchConversationKind = (conversationId: string, signal?: AbortSignal) =>
    api.get<ConversationKindResponse>(
        `/api/conversations/${encodeURIComponent(conversationId)}/kind`,
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
/* Message block revisions                                                     */
/* -------------------------------------------------------------------------- */

/** How a stored revision came about, which the history list shows. */
export type BlockRevisionOrigin = 'original' | 'manual' | 'control' | 'ai';

/** One stored version of a diagram's source. */
export interface BlockRevision {
    id: string;
    source: string;
    origin: BlockRevisionOrigin;
    author_id?: string;
    author_name?: string;
    /** A short label for the change, which for an AI edit is the instruction that caused it. */
    note?: string;
    timestamp?: string;
}

/** One turn of the sub-conversation attached to a diagram. */
export interface BlockRevisionChatTurn {
    role: 'user' | 'assistant';
    content: string;
    timestamp?: string;
}

/**
 * Everything stored against one edited block.
 *
 * `current` indexes `revisions`, where zero is always the original: it is pinned and never
 * pruned, so the meaning of zero does not drift as older edits are dropped.
 */
export interface BlockRevisionEntry {
    source_hash?: string;
    current?: number;
    revisions?: BlockRevision[];
    chat?: BlockRevisionChatTurn[];
}

/** Every edited block in a message, keyed by fence language then by block index. */
export type MessageBlockRevisions = Record<string, Record<string, BlockRevisionEntry>>;

export interface BlockRevisionResponse {
    success: boolean;
    message_id: string;
    block_revisions: MessageBlockRevisions;
}

/** Response of the assist endpoint, which also returns the source it produced. */
export interface BlockRevisionAssistResponse extends BlockRevisionResponse {
    source: string;
}

/** Fields shared by every block revision request, which together address one diagram. */
interface BlockRevisionTarget {
    conversation_id: string;
    block_kind: string;
    block_index: number;
    /** Fingerprint of the block's *original* source, which is what the entry is filed under. */
    source_hash: string;
}

/**
 * Record a new version of one diagram and make it current.
 *
 * `original_source` seeds the history the first time a block is edited, so the version the
 * model produced stays recoverable however many edits follow. The server verifies it against
 * `source_hash` rather than trusting it.
 *
 * `expected_revision_count` is optional and only matters in a shared conversation: sending the
 * count the editor was opened against turns a silent overwrite of someone else's edit into a
 * 409 the caller can report.
 */
export const addMessageBlockRevision = (
    messageId: string,
    body: BlockRevisionTarget & {
        source: string;
        original_source: string;
        origin?: 'manual' | 'control';
        note?: string;
        expected_revision_count?: number;
    },
) =>
    api.post<BlockRevisionResponse>(
        `/api/message/${encodeURIComponent(messageId)}/block-revision`,
        body,
    );

/**
 * Point a diagram at one of its stored versions.
 *
 * Undo, redo and "restore the original" are all this one call: nothing is deleted, the pointer
 * moves. Addressed by revision id because positions shift once the oldest edits are pruned.
 */
export const setMessageBlockRevision = (
    messageId: string,
    body: BlockRevisionTarget & { revision_id: string },
) =>
    api.post<BlockRevisionResponse>(
        `/api/message/${encodeURIComponent(messageId)}/block-revision/current`,
        body,
    );

/**
 * Ask the model to change one diagram.
 *
 * The request carries only this diagram — its current source, its own sub-conversation and the
 * request that produced it. The conversation is not sent, and the reply does not join it.
 */
export const assistMessageBlockRevision = (
    messageId: string,
    body: BlockRevisionTarget & {
        instruction: string;
        original_source: string;
        expected_revision_count?: number;
    },
) =>
    api.post<BlockRevisionAssistResponse>(
        `/api/message/${encodeURIComponent(messageId)}/block-revision/assist`,
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

/**
 * One already-generated proposal image, identified but not carried.
 *
 * Deliberately not a `ChatMessage`: this is what `/api/chat/image-proposals/status` returns,
 * and the whole point of that route is that it never sends image bytes. The fields are exactly
 * the ones `findResultForSpec` matches on, so a caller can tell whether the image it is
 * waiting for exists without downloading it.
 */
export interface ImageProposalStatusResult {
    message_id: string;
    created_at?: string;
    source_assistant_message_id: string;
    visual_id: string;
    title: string;
    prompt: string;
}

export interface ImageProposalStatusResponse {
    conversation_id: string;
    results: ImageProposalStatusResult[];
}

/**
 * Ask which of a conversation's image proposals already have an image.
 *
 * Used to recover from a page reload during an approval. The approval request is gone with the
 * page that made it, but the server finished the work regardless, so the only question left is
 * whether the image has landed — and this answers it in about a kilobyte, where re-reading the
 * thread would mean re-downloading every inlined image in it.
 *
 * `since` narrows the answer to images written at or after the moment the caller started
 * waiting, which is both cheaper and the only correct window: an image generated earlier
 * cannot be the one an approval started afterwards is waiting for.
 */
export const fetchImageProposalStatus = (
    conversationId: string,
    since?: string,
    signal?: AbortSignal,
) =>
    api.get<ImageProposalStatusResponse>(
        `/api/chat/image-proposals/status/${encodeURIComponent(conversationId)}` +
            (since ? `?since=${encodeURIComponent(since)}` : ''),
        signal,
    );

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
/* Conversation export                                                         */
/* -------------------------------------------------------------------------- */

/**
 * Whole-conversation export, as opposed to the per-message exports above.
 *
 * One endpoint covers every combination: any number of conversations, three formats, and
 * either one file or a ZIP of one file per conversation. It streams the file itself rather
 * than a link to it, so the response is read as a blob.
 */
export type ConversationExportFormat = 'json' | 'markdown' | 'pdf';
export type ConversationExportPackaging = 'single' | 'zip';

export const CONVERSATION_EXPORT_PATH = '/api/conversations/export';

/** Extension per format, used only when the server does not name the download itself. */
const CONVERSATION_EXPORT_EXTENSIONS: Record<ConversationExportFormat, string> = {
    json: 'json',
    markdown: 'md',
    pdf: 'pdf',
};

export interface ConversationExportRequest {
    conversation_ids: string[];
    format: ConversationExportFormat;
    packaging: ConversationExportPackaging;
    include_summary_intro: boolean;
    /**
     * A model is identified by four fields together, not by its deployment name alone — see
     * `lib/models.ts`. They are sent only when an intro summary was actually asked for.
     */
    summary_model_deployment?: string | null;
    summary_model_endpoint_id?: string | null;
    summary_model_id?: string | null;
    summary_model_provider?: string | null;
    visual_assets?: ExportVisualAsset[];
}

/** The extension a finished export will carry, which the summary step shows the user. */
export function conversationExportExtension(
    format: ConversationExportFormat,
    packaging: ConversationExportPackaging,
): string {
    return packaging === 'zip' ? '.zip' : `.${CONVERSATION_EXPORT_EXTENSIONS[format]}`;
}

/**
 * Read the download name out of a `Content-Disposition` header.
 *
 * The server already names the file, including its timestamp, so honouring the header keeps
 * a V2 export indistinguishable from a classic one. Both a quoted and a bare filename are
 * accepted because the header is not written by us.
 */
export function filenameFromContentDisposition(header: string | null): string | null {
    if (!header) {
        return null;
    }
    const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
    const filename = match?.[1]?.trim();
    if (!filename) {
        return null;
    }
    try {
        return decodeURIComponent(filename);
    } catch {
        // A stray `%` that is not an escape sequence throws. The name is still perfectly
        // usable as-is, and the alternative — letting this propagate — would fail a download
        // whose file the server has already built.
        return filename;
    }
}

/** Download one or more conversations as a single file or a ZIP. */
export async function downloadConversationExport(
    body: ConversationExportRequest,
): Promise<void> {
    const response = await fetch(apiUrl(CONVERSATION_EXPORT_PATH), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', Accept: '*/*' },
        body: JSON.stringify(body),
    });

    if (!response.ok) {
        throw await exportError(response);
    }

    const fallback = `conversations_export_${exportTimestamp()}${conversationExportExtension(
        body.format,
        body.packaging,
    )}`;

    saveBlob(
        await response.blob(),
        filenameFromContentDisposition(response.headers.get('Content-Disposition')) || fallback,
    );
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

/**
 * The original of a spreadsheet uploaded straight into a conversation.
 *
 * A chat upload is not a workspace document, so it has no `doc_id` to download by; it is
 * addressed by the conversation it was attached to and the file id within it.
 */
export function chatUploadTabularDownloadUrl(conversationId: string, fileId: string): string {
    return apiUrl(
        `/api/enhanced_citations/tabular?conversation_id=${encodeURIComponent(
            conversationId,
        )}&file_id=${encodeURIComponent(fileId)}`,
    );
}

/* -------------------------------------------------------------------------- */
/* Chat file uploads                                                           */
/* -------------------------------------------------------------------------- */

/** What `/api/get_file_content` returns for a file uploaded straight into a conversation. */
export interface ChatFileContent {
    file_content?: string;
    filename?: string;
    /** True when the content is CSV that should be drawn as a table. */
    is_table?: boolean;
    /**
     * Where the content came from. `blob` means the original file is still in storage and
     * can be downloaded; anything else means only the extracted text survives.
     */
    file_content_source?: string;
    error?: string;
}

export function fetchChatFileContent(conversationId: string, fileId: string) {
    return api.post<ChatFileContent>('/api/get_file_content', {
        conversation_id: conversationId,
        file_id: fileId,
    });
}

/* -------------------------------------------------------------------------- */
/* Generated artifacts                                                         */
/* -------------------------------------------------------------------------- */

/**
 * Absolute download URL for a generated artifact.
 *
 * `artifactDownloadPath` picks the target and this applies the API base, so the choice
 * between the conversation copy and the workspace copy stays testable without a Vite build.
 * Returns an empty string when the artifact names no downloadable target.
 */
export function generatedArtifactDownloadUrl(
    artifact: GeneratedArtifact,
    fallbackConversationId = '',
): string {
    const path = artifactDownloadPath(artifact, fallbackConversationId);
    return path ? apiUrl(path) : '';
}

export interface GeneratedOutputRunResponse {
    success?: boolean;
    message?: string;
    run?: GeneratedRunStatus;
}

export function fetchGeneratedOutputRun(runId: string, signal?: AbortSignal) {
    return api.get<GeneratedOutputRunResponse>(
        `/api/tabular/generated-output/runs/${encodeURIComponent(runId)}`,
        signal,
    );
}

/** Requeue a durable run the worker stopped short of finishing. */
export function resumeGeneratedOutputRun(runId: string) {
    return api.post<GeneratedOutputRunResponse>(
        `/api/tabular/generated-output/runs/${encodeURIComponent(runId)}/resume`,
    );
}

export function cancelGeneratedOutputRun(runId: string) {
    return api.post<GeneratedOutputRunResponse>(
        `/api/tabular/generated-output/runs/${encodeURIComponent(runId)}/cancel`,
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

/**
 * List workspace documents.
 *
 * Paged, filtered and sorted server-side. `total_count` describes the whole filtered set,
 * so the pager counts against it rather than against the returned array.
 */
export function fetchPersonalDocuments(
    query: Partial<DocumentQuery> = {},
    signal?: AbortSignal,
) {
    return api.get<DocumentListResponse>(
        `/api/documents?${buildDocumentListParams(query)}`,
        signal,
    );
}

/** Counts for the explorer rail, over the whole workspace rather than the current page. */
export const fetchPersonalDocumentFacets = (signal?: AbortSignal) =>
    api.get<DocumentFacets>('/api/documents/facets', signal);

export const fetchPersonalDocument = (documentId: string, signal?: AbortSignal) =>
    api.get<WorkspaceDocument>(`/api/documents/${encodeURIComponent(documentId)}`, signal);

export const fetchPersonalDocumentVersions = (documentId: string, signal?: AbortSignal) =>
    api.get<{ document_id?: string; revision_family_id?: string; versions?: WorkspaceDocument[] }>(
        `/api/documents/${encodeURIComponent(documentId)}/versions`,
        signal,
    );

export type DocumentDeleteMode = 'all_versions' | 'current_only';

export function deletePersonalDocument(
    documentId: string,
    options: {
        deleteMode?: DocumentDeleteMode;
        conversationLinkedDeleteConfirmed?: boolean;
        fileSyncDeleteAction?: string | null;
    } = {},
) {
    const params = new URLSearchParams();
    params.set('delete_mode', options.deleteMode ?? 'all_versions');
    if (options.conversationLinkedDeleteConfirmed) {
        params.set('conversation_linked_delete_confirmed', 'true');
    }
    if (options.fileSyncDeleteAction) {
        params.set('file_sync_delete_action', options.fileSyncDeleteAction);
    }
    return api.delete<Json>(
        `/api/documents/${encodeURIComponent(documentId)}?${params.toString()}`,
    );
}

/** One entry per document the batch could not delete. */
export interface BulkDeleteError {
    document_id: string;
    error?: string;
    message?: string;
    /** True when the caller may retry with the matching confirmation set. */
    needs_confirmation?: boolean;
    conversation?: { id?: string; title?: string; url?: string };
    [key: string]: unknown;
}

export interface BulkDeleteResponse {
    message?: string;
    deleted?: { document_id: string }[];
    errors?: BulkDeleteError[];
    deleted_count?: number;
    error_count?: number;
}

/**
 * Delete several documents in one request.
 *
 * Reports per document rather than failing the batch, because a document uploaded through
 * chat or managed by file sync is guarded individually and would otherwise block the
 * deletion of everything selected with it.
 */
export function bulkDeletePersonalDocuments(
    documentIds: string[],
    options: {
        deleteMode?: DocumentDeleteMode;
        conversationLinkedDeleteConfirmed?: boolean;
        fileSyncDeleteAction?: string | null;
    } = {},
) {
    return api.post<BulkDeleteResponse>('/api/documents/bulk-delete', {
        document_ids: documentIds,
        delete_mode: options.deleteMode ?? 'all_versions',
        conversation_linked_delete_confirmed: Boolean(
            options.conversationLinkedDeleteConfirmed,
        ),
        file_sync_delete_action: options.fileSyncDeleteAction ?? null,
    });
}

/** Editable metadata. Only the supplied fields are written. */
export interface DocumentMetadataUpdate {
    title?: string;
    abstract?: string;
    keywords?: string[];
    publication_date?: string;
    document_classification?: string;
    authors?: string[];
    tags?: string[];
}

export const updatePersonalDocumentMetadata = (
    documentId: string,
    metadata: DocumentMetadataUpdate,
) =>
    api.patch<Json>(
        `/api/documents/${encodeURIComponent(documentId)}`,
        metadata as unknown as Json,
    );

export const extractPersonalDocumentMetadata = (documentIds: string[]) =>
    api.post<{ message?: string; queued?: string[]; errors?: unknown[] }>(
        '/api/documents/extract_metadata',
        { document_ids: documentIds },
    );

/** `read` is the standard extraction, `layout` the enhanced one. */
export type ExtractionMode = 'read' | 'layout';

export const reprocessPersonalDocumentExtraction = (
    documentIds: string[],
    extractionMode: ExtractionMode,
) =>
    api.post<{ message?: string; queued?: string[]; errors?: unknown[] }>(
        '/api/documents/reprocess_extraction',
        { document_ids: documentIds, extraction_mode: extractionMode },
    );

/* --- Tags ---------------------------------------------------------------- */

export const fetchPersonalDocumentTags = (signal?: AbortSignal) =>
    api.get<{ tags?: WorkspaceTag[] }>('/api/documents/tags', signal);

export const createPersonalDocumentTag = (name: string, color?: string | null) =>
    api.post<{ message?: string; tag?: WorkspaceTag }>('/api/documents/tags', {
        tag_name: name,
        ...(color ? { color } : {}),
    });

/**
 * Rename or recolour a tag.
 *
 * A rename cascades to every document carrying the tag server-side, which is what makes
 * renaming safe: the alternative would leave documents filed under a name that no longer
 * exists in the vocabulary.
 */
export const updatePersonalDocumentTag = (
    tagName: string,
    changes: { new_name?: string; color?: string | null },
) =>
    api.patch<{ message?: string; documents_updated?: number; tag?: WorkspaceTag }>(
        `/api/documents/tags/${encodeURIComponent(tagName)}`,
        changes as unknown as Json,
    );

export const deletePersonalDocumentTag = (tagName: string) =>
    api.delete<Json>(`/api/documents/tags/${encodeURIComponent(tagName)}`);

export type BulkTagAction = 'add_tags' | 'remove_tags' | 'set_tags';

export const bulkTagPersonalDocuments = (
    documentIds: string[],
    action: BulkTagAction,
    tags: string[],
) =>
    api.post<{ success?: string[]; errors?: unknown[] }>('/api/documents/bulk-tag', {
        document_ids: documentIds,
        action,
        tags,
    });

/* --- Sharing -------------------------------------------------------------- */

export interface SharedDocumentUser {
    id: string;
    approval_status?: string;
    displayName?: string;
    email?: string;
}

export const fetchPersonalDocumentSharedUsers = (
    documentId: string,
    signal?: AbortSignal,
) =>
    api.get<{ shared_users?: SharedDocumentUser[] }>(
        `/api/documents/${encodeURIComponent(documentId)}/shared-users`,
        signal,
    );

export const sharePersonalDocument = (documentId: string, userId: string) =>
    api.post<Json>(`/api/documents/${encodeURIComponent(documentId)}/share`, {
        user_id: userId,
    });

export const unsharePersonalDocument = (documentId: string, userId: string) =>
    api.delete<Json>(`/api/documents/${encodeURIComponent(documentId)}/unshare`, {
        user_id: userId,
    });

export const approvePersonalDocumentShare = (documentId: string) =>
    api.post<Json>(`/api/documents/${encodeURIComponent(documentId)}/approve-share`);

export const removeSelfFromPersonalDocument = (documentId: string) =>
    api.delete<Json>(`/api/documents/${encodeURIComponent(documentId)}/remove-self`);

export const searchShareableUsers = (query: string, signal?: AbortSignal) =>
    api.get<SharedDocumentUser[]>(
        `/api/userSearch?query=${encodeURIComponent(query)}`,
        signal,
    );

/* --- Files ---------------------------------------------------------------- */

/**
 * Download a document's original file.
 *
 * Fetched rather than linked so an expired session surfaces as an error the page can report,
 * instead of navigating the tab to a sign-in redirect and losing the explorer's state.
 */
export async function downloadPersonalDocument(documentId: string): Promise<Blob> {
    const response = await fetch(
        apiUrl(`/api/documents/${encodeURIComponent(documentId)}/download`),
        { credentials: CREDENTIALS_MODE },
    );
    if (!response.ok) {
        throw new ApiError(
            `Download failed with status ${response.status}`,
            response.status,
            null,
        );
    }
    return response.blob();
}

/** Download several documents. The server returns a single file, or a ZIP for a batch. */
export async function downloadPersonalDocuments(documentIds: string[]): Promise<Blob> {
    const response = await fetch(apiUrl('/api/documents/download'), {
        method: 'POST',
        credentials: CREDENTIALS_MODE,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ document_ids: documentIds }),
    });
    if (!response.ok) {
        throw new ApiError(
            `Download failed with status ${response.status}`,
            response.status,
            null,
        );
    }
    return response.blob();
}

/**
 * Upload files to the personal workspace.
 *
 * The route accepts several files under a single `file` field and answers 207 for a partial
 * success, so the caller has to read `errors` even when the request itself succeeded.
 */
export function uploadPersonalDocuments(files: File[], signal?: AbortSignal) {
    const formData = new FormData();
    for (const file of files) {
        formData.append('file', file);
    }
    return uploadFile<{
        message?: string;
        document_ids?: string[];
        processed_filenames?: string[];
        errors?: string[];
    }>('/api/documents/upload', formData, signal);
}

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
