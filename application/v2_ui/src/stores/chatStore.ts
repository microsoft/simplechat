// chatStore.ts
// Conversation list, message thread and live streaming state for the chat page.

import { create } from 'zustand';
import {
    addMessageBlockRevision as addMessageBlockRevisionApi,
    addMessageImageRevision as addMessageImageRevisionApi,
    assistMessageBlockRevision as assistMessageBlockRevisionApi,
    bulkHideConversations as bulkHideConversationsApi,
    bulkPinConversations as bulkPinConversationsApi,
    createConversation,
    deleteConversation as deleteConversationApi,
    deleteConversations as deleteConversationsApi,
    deleteMessage as deleteMessageApi,
    editMessage as editMessageApi,
    fetchConversationFeed,
    fetchMessages,
    forkConversation as forkConversationApi,
    generateImageFromProposal,
    markConversationRead,
    maskMessage as maskMessageApi,
    renameConversation as renameConversationApi,
    retryMessage as retryMessageApi,
    setMessageBlockRevision as setMessageBlockRevisionApi,
    setMessageImageRevision as setMessageImageRevisionApi,
    setMessageVisualStyle as setMessageVisualStyleApi,
    submitFeedback as submitFeedbackApi,
    switchAttempt as switchAttemptApi,
    toggleConversationHidden,
    toggleConversationPinned,
    type BulkConversationResult,
    type ImageRevisionEntry,
    type ImageRevisionOrigin,
    type MessageBlockRevisions,
} from '../lib/endpoints';
import {
    cancelStream,
    fetchStreamStatus,
    reattachChatStream,
    streamChat,
    type ChatStreamHandlers,
    type ChatStreamOptions,
} from '../lib/sse';
import {
    addCollaborationBlockRevision,
    addCollaborationImageRevision,
    assistCollaborationBlockRevision,
    cancelCollaborationStreamUrl,
    collaborationDeleteAction,
    deleteCollaborationMessage,
    fetchCollaborationConversation,
    fetchCollaborationMessages,
    markCollaborationConversationRead,
    maskCollaborationMessage,
    postCollaborationMessage,
    renameCollaborationConversation,
    setCollaborationBlockRevision,
    setCollaborationImageRevision,
    setCollaborationMessageVisualStyle,
    streamCollaborationUrl,
    toggleCollaborationHidden,
    toggleCollaborationPinned,
} from '../lib/collaboration';
import { subscribeToCollaborationEvents, conversationFactsOnly } from '../lib/collaborationEvents';
import {
    conversationParticipants,
    extractMentionedParticipants,
    mentionsCurrentUser,
    resolveSendTarget,
} from '../lib/mentions';
import { buildSelectionFields } from '../lib/chatRequestSelection';
import { promptSelectionMetadata } from '../lib/promptRequest';
import type { RunStreamEvent } from '../lib/orchestration';
import {
    applySelection,
    pruneSelection,
    type SelectionIntent,
    type SelectionState,
} from '../lib/listSelection';
import {
    collaborativeIdsNeedingPin,
    collaborativeRemovals,
    partialFailureMessage,
    partitionBySpecies,
    selectedConversations,
    type PinAction,
} from '../lib/conversationSelection';
import type { ModelCatalogEntry } from '../lib/models';
import { resolveDocumentScope } from '../lib/documentScope';
import {
    contextDocumentIds,
    contextFilterMode,
    contextScopes,
    contextTags,
    type ContextItem,
} from '../lib/chatContext';
import { messageThreadId } from '../lib/threads';
import { proposalSourceMessageId, type ImageProposalSpec } from '../lib/imageProposalSpec';
import { toast } from './toastStore';
import { ApiError } from '../lib/apiClient';
import { useBootstrapStore } from './bootstrapStore';
import { useCollaborationStore, participantName } from './collaborationStore';
import type { MaskAction, MaskSelection } from '../lib/masking';
import type { VisualStyle } from '../lib/visualPalettes';
import type {
    AgentOption,
    ChatMessage,
    ChatStreamRequest,
    CollaborationConversation,
    CollaborationMessage,
    Conversation,
    ConversationMetadata,
    Json,
    ThoughtEntry,
} from '../lib/types';
import { isCollaborative } from '../lib/types';
import { fetchConversationKind, fetchConversationMetadata } from '../lib/endpoints';
import type { ConversationKind } from '../lib/endpoints';

const FEED_PAGE_SIZE = 30;

/** Identifier for the optimistic assistant message shown while a stream is running. */
const STREAMING_MESSAGE_ID = '__streaming__';

/** Which mode the right-hand drawer is showing, or null when it is closed. */
export type DrawerMode = 'contents' | 'documents' | 'plan' | null;

/**
 * How an orchestration run's answer settled into the thread.
 *
 * A run is driven outside the chat stream machinery, but its answer lands in the same thread as
 * any other, so `settleOrchestrationTurn` takes one of these and folds it into the shared
 * streaming state. `completed` carries the chat-shaped terminal frame (`RunStreamEvent` extends
 * `ChatStreamEvent`) so the final message is built exactly as a chat completion's is.
 */
export type OrchestrationTurnOutcome =
    | {
          status: 'completed';
          event: RunStreamEvent;
          accumulated: string;
          /** The optimistic user bubble to reconcile with the server's id, when one is known. */
          pendingUserMessageId?: string | null;
      }
    | { status: 'cancelled'; accumulated: string }
    | { status: 'failed'; error: string }
    /** Planning produced a plan or a question: leave the thinking state without adding a message. */
    | { status: 'planned' };

/**
 * Which API family the open conversation belongs to.
 *
 * A shared conversation is stored in different Cosmos containers and served by
 * `/api/collaboration/*`; sending its id to a personal route either 404s or, in the case of
 * `/api/get_messages`, answers 200 with an empty list. Every conversation-scoped call
 * therefore branches on this rather than trying one endpoint and falling back.
 *
 * Defined with the wire types because the server reports it, and re-exported here because this
 * is where the rest of the app has always read it from.
 */
export type { ConversationKind };

/**
 * How far a stream recovery has got.
 *
 * `connecting` means the answer has stopped arriving while the reattach is negotiated.
 * `reconnected` means it is arriving again, and the interface should go back to looking
 * like an ordinary response rather than continuing to advertise the interruption.
 */
export type ReconnectPhase = 'connecting' | 'reconnected' | null;

export interface ComposerOptions {
    /**
     * The picker's selection key for the chosen model, NOT its deployment name.
     *
     * The deployment name does not identify a model on its own when several endpoints
     * offer the same one, so the full identity is resolved from the catalog at send time.
     */
    modelDeployment?: string;
    agentSelection?: string;
    promptId?: string;
    /**
     * The saved prompt behind this message, resolved and ready to send.
     *
     * Built by the composer at send time rather than looked up from the catalog here, because
     * the text that reaches the server has to be the text that was actually used: variables
     * filled in, and any wording edited for this one turn included.
     */
    promptInfo?: Json | null;
    reasoningEffort?: string;
    documentSearch: boolean;
    webSearch: boolean;
    imageGeneration: boolean;
    /** Deep research sets both source_review_enabled and deep_research_enabled. */
    deepResearch: boolean;
    urlAccess: boolean;
    /**
     * What this message is grounded in: documents, tags and workspaces chosen in the composer.
     *
     * Replaces the write-only `selectedDocumentIds` this interface shipped with, which was
     * declared, forwarded to both the chat request and the orchestration seeds, and never
     * populated by anything. The document ids are now derived from here at send time, so
     * everything downstream that already reads `selected_document_ids` is unchanged.
     */
    contextItems: ContextItem[];
}

interface ChatState {
    conversations: Conversation[];
    conversationsLoading: boolean;
    conversationsError: string | null;
    hasMore: boolean;
    nextCursor: string | null;
    searchTerm: string;

    /**
     * The rail's multi-selection.
     *
     * Selection lives here rather than in the rail because deleting or hiding a conversation
     * is a store action, and a selection kept beside the list would go stale the moment one
     * of those removed a row — acting on an id the user can no longer see.
     *
     * There is no separate "selection mode" flag: a selection either has members or it does
     * not, and a mode that could be on with nothing selected was a second source of truth
     * for the same question.
     */
    selectedConversationIds: string[];
    /**
     * Where a Shift+click range starts, or null when there is nothing to extend from.
     *
     * Held apart from the ids because a range must survive the selection being replaced —
     * that is what lets an over-long range be corrected by Shift+clicking a nearer row.
     */
    selectionAnchorId: string | null;

    activeConversationId: string | null;
    /**
     * Which API family the open conversation belongs to.
     *
     * Null only before anything is open. Resolved when the conversation is selected rather
     * than looked up per call, because a deep link may name a conversation that is not in
     * the loaded rail and answering the question costs a request.
     */
    activeConversationKind: ConversationKind | null;
    messages: ChatMessage[];
    messagesLoading: boolean;
    messagesError: string | null;

    streaming: boolean;
    streamingContent: string;
    thoughts: ThoughtEntry[];
    streamError: string | null;
    /**
     * Where a stream recovery has got to, or null when nothing is being recovered.
     *
     * Generation continues server-side after the HTTP connection drops, so a broken
     * transport is recoverable. The two phases are deliberately distinct because they mean
     * different things to someone watching: `connecting` is a response that has genuinely
     * stopped moving while the reattach is negotiated, whereas `reconnected` is a response
     * that is flowing again and should look no different from any other. Leaving the UI in
     * the first state for the whole reattached stream makes working output look stalled.
     */
    reconnectPhase: ReconnectPhase;

    /** Right-hand drawer state. Null means closed. */
    drawerMode: DrawerMode;
    metadata: ConversationMetadata | null;
    metadataLoading: boolean;
    metadataError: string | null;

    /**
     * Attempt numbers known to exist, keyed by thread id.
     *
     * `/api/get_messages` filters to the active attempt, so the loaded list can never reveal
     * how many attempts a thread has. The switch-attempt endpoint is the only thing that
     * reports the full set, so what it returns is remembered here.
     */
    attemptsByThread: Record<string, number[]>;

    loadConversations: (options?: { reset?: boolean; search?: string }) => Promise<void>;
    loadMore: () => Promise<void>;
    setSearchTerm: (term: string) => void;

    selectConversation: (
        conversationId: string | null,
        options?: {
            kind?: ConversationKind;
            /**
             * Membership already fetched for this conversation, saving a second request.
             *
             * Passed in rather than left in the store, because it is fetched before the
             * conversation is open and the store now refuses writes for anything that is
             * not.
             */
            prefetched?: CollaborationConversation;
        },
    ) => Promise<void>;
    /**
     * Open a conversation named by the URL rather than clicked in the rail.
     *
     * Kept apart from `selectConversation` because the two have different failure
     * modes. A row the user clicked is one the server just sent; a link can name a
     * conversation that has since been deleted, or that belongs to somebody else.
     */
    openLinkedConversation: (conversationId: string) => Promise<void>;
    startNewConversation: () => void;
    renameConversation: (conversationId: string, title: string) => Promise<void>;
    /**
     * Remove one conversation from the reader's view.
     *
     * `decidedAction` is how a shared conversation is to be removed, when the caller has
     * already shown the user which of the two it will be. Passing it is what guarantees the
     * confirmation and the request agree; omitting it falls back to deciding here.
     */
    removeConversation: (
        conversationId: string,
        decidedAction?: 'delete' | 'leave',
    ) => Promise<void>;
    togglePinned: (conversationId: string) => Promise<void>;
    toggleHidden: (conversationId: string) => Promise<void>;

    /**
     * Apply a click to the selection, honouring its modifier keys.
     *
     * `intent` comes from `selectionIntentFromEvent`; the ordering a range reads is the
     * rail's current list, so a range always means what the user can see. This is the only
     * way to change which rows are picked — a second "toggle this one" action would be a
     * parallel path that could drift from the modifier rules.
     */
    applyConversationSelection: (
        conversationId: string,
        intent: SelectionIntent,
    ) => void;
    selectAllConversations: () => void;
    clearConversationSelection: () => void;

    /** Delete or leave every selected conversation, whichever each one permits. */
    bulkRemoveConversations: () => Promise<void>;
    /** Set — not toggle — the pin state of every selected conversation. */
    bulkSetConversationsPinned: (action: PinAction) => Promise<void>;
    /** Hide every selected conversation, dropping them out of the feed. */
    bulkHideSelectedConversations: () => Promise<void>;

    sendMessage: (text: string, options: ComposerOptions) => Promise<void>;
    stopStreaming: () => void;

    /**
     * Fold an orchestration turn into the shared thread and streaming state.
     *
     * Orchestration plans and runs are driven by `useOrchestrationController`, not by the chat
     * stream machinery, because they speak a different transport and cancel differently. But the
     * question the user typed and the answer a run produces belong in this thread like any other,
     * so these three are the seam between the two. They are deliberately small and each guards on
     * the open conversation: a run outlives the view it started in, and writing streaming state
     * for a conversation the reader has since left would paint this answer into whatever they
     * opened instead — the same hazard `sendMessage` guards with `ownsScreen`.
     *
     * `beginOrchestrationTurn` returns the optimistic user bubble's id so the controller can hand
     * it back on completion for reconciliation with the server's persisted id. Passing
     * `addUserMessage: false` re-enters the thinking state for a re-plan without adding a second
     * bubble, because the user's question is already in the thread from the first plan.
     */
    beginOrchestrationTurn: (
        conversationId: string,
        text: string,
        addUserMessage?: boolean,
        turnId?: string,
    ) => string;
    pushOrchestrationThought: (conversationId: string, event: RunStreamEvent) => void;
    pushOrchestrationContent: (conversationId: string, accumulated: string) => void;
    settleOrchestrationTurn: (
        conversationId: string,
        outcome: OrchestrationTurnOutcome,
    ) => void;
    /**
     * Re-key an in-flight turn's optimistic bubble when the server reconciles its ids.
     *
     * A safety net for the plan seam, not a normal step. The client mints the turn id and
     * pre-creates the conversation, so the server almost always echoes both back unchanged; when it
     * does not, the plan is keyed on one value and the question bubble already on screen carries
     * another. That bubble is the anchor the plan card scrolls back to, so it is re-stamped to the
     * ids the store now keys on. A no-op when neither id actually moved, so the ordinary path — and
     * the common orchestration path — pays nothing.
     */
    reassignOrchestrationTurn: (params: {
        fromConversationId: string;
        toConversationId: string;
        fromTurnId: string;
        toTurnId: string;
    }) => void;

    setDrawerMode: (mode: DrawerMode) => void;
    loadMetadata: (conversationId: string) => Promise<void>;

    reloadMessages: () => Promise<void>;
    removeMessage: (messageId: string, deleteThread?: boolean) => Promise<void>;
    retryMessage: (messageId: string, options?: ComposerOptions) => Promise<void>;
    editMessage: (messageId: string, content: string) => Promise<void>;
    changeAttempt: (messageId: string, direction: 'prev' | 'next') => Promise<void>;
    forkFromMessage: (messageId: string) => Promise<void>;
    applyMask: (
        messageId: string,
        action: MaskAction,
        selection?: MaskSelection,
    ) => Promise<void>;
    /**
     * Save or clear the colours of one diagram or chart inside a message.
     *
     * Resolves to true when the change was stored, so the block can surface a failure next to
     * the control the reader just used rather than only as a toast.
     */
    applyVisualStyle: (
        messageId: string,
        conversationId: string,
        /**
         * Which API family that conversation belongs to, captured when the change was made.
         *
         * Passed in for the same reason `conversationId` is: a pending change is flushed when
         * the block unmounts, and by then the conversation it belongs to may no longer be the
         * open one. `null` falls back to whatever the store can still work out.
         */
        conversationKind: ConversationKind | null,
        blockKind: string,
        blockIndex: number,
        sourceHash: string,
        style: VisualStyle | null,
        /**
         * The block's stage height in pixels.
         *
         * `undefined` leaves whatever is stored alone, so a colour change does not reset a
         * size someone chose; `null` clears it back to the automatic height.
         */
        height?: number | null,
    ) => Promise<boolean>;
    sendFeedback: (
        messageId: string,
        feedbackType: 'positive' | 'negative',
        reason?: string,
    ) => Promise<void>;
    /**
     * Store an edited diagram as a new revision and make it the one that shows.
     *
     * Resolves to null on success, or to a message explaining why the change was not kept. An
     * error string rather than a thrown exception because the editor shows the reason inline
     * beside the diagram rather than as a toast over the thread.
     */
    saveBlockRevision: (request: BlockRevisionRequest & {
        source: string;
        origin: 'manual' | 'control';
        note: string;
    }) => Promise<string | null>;
    /** Show one of a diagram's stored revisions. Nothing is discarded. */
    restoreBlockRevision: (request: Omit<BlockRevisionRequest, 'originalSource'> & {
        revisionId: string;
    }) => Promise<string | null>;
    /** Ask the model to change one diagram, scoped to that diagram alone. */
    askBlockRevision: (request: BlockRevisionRequest & {
        instruction: string;
    }) => Promise<string | null>;
    /** Fold a message's updated revision map into the thread after a successful write. */
    mergeBlockRevisions: (
        messageId: string,
        blockRevisions: MessageBlockRevisions | undefined,
    ) => void;
    /**
     * Produce a new version of a generated image, scoped to that image alone.
     *
     * There is no "save what I edited" counterpart to the diagram actions, because a browser
     * cannot author an image. Every version comes from the model, so asking for one and
     * creating one are the same call.
     *
     * Resolves to null on success, or to a message worth showing beside the image.
     */
    reviseImage: (request: ImageRevisionActionRequest) => Promise<string | null>;
    /** Show one of an image's stored versions. Nothing is discarded; the pointer moves. */
    restoreImageRevision: (request: {
        messageId: string;
        conversationId: string;
        conversationKind: ConversationKind | null;
        revisionId: string;
    }) => Promise<string | null>;
    /**
     * Fold a revision response back into the thread.
     *
     * Unlike a diagram revision this also replaces the message's `content`. A diagram's stored
     * source is substituted at render time, but an image's content *is* a URL, and an edited
     * image is served from a different one — carrying the revision id so the browser does not
     * keep showing the copy it already cached.
     */
    mergeImageRevisions: (
        messageId: string,
        entry: ImageRevisionEntry | undefined,
        imageUrl?: string,
    ) => void;
    /**
     * Generate the image a `simpleimage` proposal card describes.
     *
     * The conversation is passed in rather than read from the store, because approvals are
     * queued: an "Approve all" started in one thread can still be draining when the user has
     * moved to another, and reading the active conversation at that point would generate the
     * image into whichever thread happens to be open. The server accepts that request quite
     * happily — it is a conversation the same user owns — so nothing downstream would catch
     * it.
     *
     * Resolves once the image has been stored and folded into the thread; rejects with the
     * server's own message so the card can show why it failed.
     */
    approveImageProposal: (
        conversationId: string,
        assistantMessageId: string,
        proposal: ImageProposalSpec,
    ) => Promise<void>;
}

/**
 * How a block revision request addresses one diagram.
 *
 * The conversation is passed in rather than read from the store for the same reason image
 * approvals do it: a model edit can still be in flight when the reader has moved to another
 * thread, and the edit belongs to the conversation it was started in.
 */
interface BlockRevisionRequest {
    messageId: string;
    conversationId: string;
    /**
     * Which API family that conversation belongs to, as known when the edit was made.
     *
     * Captured with the id and for the same reason: a shared conversation is written through a
     * different endpoint, and resolving the kind at write time would consult a rail row that
     * may no longer describe the conversation this edit belongs to. Null means it was not
     * known, in which case the store falls back to looking it up.
     */
    conversationKind: ConversationKind | null;
    blockKind: string;
    blockIndex: number;
    /** Fingerprint of the block's original source, which the entry is filed under. */
    sourceHash: string;
    originalSource: string;
    /**
     * How many revisions the editor was opened against.
     *
     * Sent so a second person editing the same diagram in a shared conversation gets a conflict
     * rather than silently overwriting the first. Omitted when there is no history yet.
     */
    expectedRevisionCount?: number;
}

/** Whether a block revision write belongs to the collaboration API. */
function isSharedBlockRevision(
    state: ChatState,
    conversationId: string,
    conversationKind: ConversationKind | null,
): boolean {
    return conversationKind === null
        ? isCollaborativeConversation(state, conversationId)
        : conversationKind === 'collaborative';
}

/**
 * Turn a failed diagram edit into something worth showing beside the diagram.
 *
 * A 409 is the interesting one: it is not a fault, it means someone else edited the same
 * diagram, and saying so is more useful than repeating whatever the server called it.
 */
function describeBlockRevisionError(error: unknown, fallback: string): string {
    if (error instanceof ApiError) {
        if (error.status === 403) {
            return 'You can only edit diagrams in conversations you take part in.';
        }
        if (error.status === 409) {
            return 'Someone else changed this diagram. Close and reopen it to see their version.';
        }
    }
    return error instanceof Error && error.message ? error.message : fallback;
}

/** What a caller asks for when producing a new version of an image. */
export interface ImageRevisionActionRequest {
    messageId: string;
    conversationId: string;
    conversationKind: ConversationKind | null;
    origin?: ImageRevisionOrigin;
    instruction?: string;
    prompt?: string;
    /** A PNG data URL whose transparent pixels mark the region to change. */
    mask?: string;
    maskRegions?: number;
    size?: string;
    quality?: string;
    background?: string;
    expectedRevisionCount?: number;
    expectedCurrentRevisionId?: string;
}

/**
 * Turn a failed image edit into something worth showing beside the image.
 *
 * Separate from the diagram version because the failures differ. A 502 here is ordinary rather
 * than alarming: image models refuse prompts, time out, and reject regions, and every one of
 * those costs the reader a wait, so the message has to suggest what to do next rather than
 * read as a crash.
 */
function describeImageRevisionError(error: unknown, fallback: string): string {
    if (error instanceof ApiError) {
        if (error.status === 403) {
            return 'You can only change images in conversations you take part in.';
        }
        if (error.status === 409) {
            return 'Someone else changed this image. Close and reopen it to see their version.';
        }
        if (error.status === 502 && error.message) {
            return `${error.message} Try describing the change differently.`;
        }
    }
    return error instanceof Error && error.message ? error.message : fallback;
}

/**
 * Build a conversation list row out of a metadata response.
 *
 * The two shapes differ in more than depth: metadata keys the conversation as
 * `conversation_id` where the feed uses `id`, and carries no `created_at`. The id is passed
 * in rather than read from the response so the row is guaranteed to match the conversation
 * it was fetched for, which is what the rail highlights on. Only the fields the rail and the
 * header actually read are mapped; everything else is left off rather than guessed at.
 */
function conversationFromMetadata(
    conversationId: string,
    metadata: ConversationMetadata,
): Conversation {
    return {
        id: conversationId,
        title: metadata.title || 'Untitled conversation',
        last_updated: metadata.last_updated,
        is_pinned: metadata.is_pinned ?? false,
        is_hidden: metadata.is_hidden ?? false,
        has_unread_assistant_response: metadata.has_unread_assistant_response ?? false,
        classification: metadata.classification ?? null,
        context: metadata.context,
        chat_type: metadata.chat_type ?? undefined,
    };
}

/**
 * Present a shared conversation as the metadata shape the header and drawer already read.
 *
 * The two responses overlap but are not the same: a shared conversation keys itself as `id`
 * where metadata uses `conversation_id`, and carries membership the personal shape has no
 * place for. Mapping here rather than teaching every consumer about both shapes keeps the
 * badges, classification pills, document drawer and summary working on a shared thread
 * without a single change to those components.
 *
 * The original is kept under `collaboration` so anything that genuinely needs the
 * membership can reach it without a second request.
 */
export function metadataFromCollaboration(
    conversation: CollaborationConversation,
): ConversationMetadata {
    return {
        ...conversation,
        conversation_id: String(conversation.id ?? ''),
        title: conversation.title || 'Untitled conversation',
        last_updated: conversation.updated_at ?? conversation.last_updated,
        chat_type: conversation.chat_type ?? null,
        collaboration: conversation,
    } as ConversationMetadata;
}

/** Controller for the in-flight stream, kept outside the store as it is not render state. */
let activeStreamController: AbortController | null = null;

/**
 * Conversation the in-flight stream belongs to.
 *
 * Tracked separately from `activeConversationId` because the user can switch threads while
 * a response is still generating; a cancel must address the conversation that is actually
 * streaming, not whichever one happens to be on screen.
 */
let streamingConversationId: string | null = null;

/**
 * Whether the in-flight stream belongs to a shared conversation.
 *
 * Cancelling addresses a different endpoint for each, and the answer must survive the
 * reader switching threads mid-response, so it is recorded alongside the conversation id
 * rather than re-derived from whatever is on screen when Stop is pressed.
 */
let streamingConversationKind: ConversationKind = 'personal';

/**
 * Stop reading the in-flight stream without asking the server to stop producing it.
 *
 * These are two different things and only the Stop button means the second one. Generation
 * runs in background execution and deliberately outlives the connection carrying it
 * (`build_background_stream_response`, route_backend_chats.py:14372), so dropping the reader
 * leaves the answer being written and saved; `resumeChatStream` picks it back up when the
 * conversation is opened again.
 *
 * Cancelling instead would end the generation for good. `/api/chat/stream/cancel` reaches
 * `request_cancel` (route_backend_chats.py:8382), which sets `cancel_requested`, and the
 * agent loop honours it. Worse, a cancel that lands before the first content token persists
 * no assistant message at all (`message_persisted=False`, route_backend_chats.py:15971) —
 * so leaving a thread during the thinking phase destroyed the reply outright rather than
 * merely truncating it. The classic client never does this: chat-conversations.js reattaches
 * on select and only the stop control cancels.
 */
function detachActiveStream(): void {
    if (!activeStreamController) {
        return;
    }
    activeStreamController.abort();
    activeStreamController = null;
    streamingConversationId = null;
    // Included here rather than left to callers: neither `selectConversation` nor
    // `startNewConversation` clears `streaming` itself, so dropping it would leave the
    // composer stuck showing Stop for a stream that is no longer being read.
    useChatStore.setState({ streaming: false, streamingContent: '', reconnectPhase: null });
}

/**
 * Detach from the open shared conversation's event stream, if there is one.
 *
 * Held at module scope for the same reason as the stream controller: it is a live
 * connection rather than render state, and leaving one attached after a thread switch
 * would keep feeding another conversation's messages into the list.
 */
let detachCollaborationEvents: (() => void) | null = null;

function stopCollaborationEvents(): void {
    if (detachCollaborationEvents) {
        detachCollaborationEvents();
        detachCollaborationEvents = null;
    }
}

/**
 * Merge a message that arrived from the server into the thread.
 *
 * Idempotent by message id, which it has to be: the sender of an AI request receives the
 * assistant's reply twice — once in the stream's terminal frame and once as a
 * `collaboration.message.created` event — and a posted message comes back both in the
 * POST response and over the event stream. Appending blindly shows each of those twice.
 *
 * An optimistic placeholder for the same message is replaced rather than left behind:
 * matched on the pending id when it is known, and otherwise on the reader's own unsent
 * text, which is how a message posted from another tab still lands in one place.
 */
function mergeCollaborationMessage(
    messages: ChatMessage[],
    incoming: CollaborationMessage,
    options: { pendingId?: string | null; currentUserId?: string } = {},
): ChatMessage[] {
    const existingIndex = messages.findIndex((message) => message.id === incoming.id);
    if (existingIndex !== -1) {
        const merged = [...messages];
        merged[existingIndex] = { ...merged[existingIndex], ...incoming };
        return merged;
    }

    const senderId = String(incoming.sender?.user_id ?? '').trim();
    const isOwnMessage = Boolean(
        options.currentUserId && senderId && senderId === options.currentUserId,
    );

    const placeholderIndex = messages.findIndex((message) => {
        if (options.pendingId && message.id === options.pendingId) {
            return true;
        }
        return (
            isOwnMessage &&
            typeof message.id === 'string' &&
            message.id.startsWith('pending-user-') &&
            message.content === incoming.content
        );
    });

    if (placeholderIndex !== -1) {
        const merged = [...messages];
        merged[placeholderIndex] = incoming;
        return merged;
    }

    return [...messages, incoming];
}

/** Store writer used by the stream handlers, kept narrow so they can be shared. */
type StreamStateSetter = (
    partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>),
) => void;

/**
 * Build the event handlers that fold a stream into the store.
 *
 * Shared by a fresh send and by a resume of an already-running generation, so a reattached
 * stream produces exactly the same message, thoughts and error handling as the original.
 */
function buildStreamHandlers(
    conversationId: string,
    isCurrent: () => boolean,
    set: StreamStateSetter,
    getState: () => ChatState,
    /**
     * Id of the optimistic user message this stream was started for, when there is one.
     *
     * Given the server's real id as soon as the message is persisted. Without this the
     * bubble keeps a `pending-user-…` id, and every per-message action on it — delete,
     * mask, reply — would address a message the server has never heard of. It also lets a
     * shared conversation recognise its own message when the same one arrives back over
     * the event stream.
     */
    pendingUserMessageId?: string | null,
): ChatStreamHandlers {
    return {
        onUserMessagePersisted: (event) => {
            const persistedId = String(event.user_message_id ?? event.message_id ?? '').trim();
            if (!persistedId || !pendingUserMessageId || !isCurrent()) {
                return;
            }
            set((state) => ({
                messages: state.messages.map((message) =>
                    message.id === pendingUserMessageId
                        ? { ...message, id: persistedId }
                        : message,
                ),
            }));
        },
        onContent: (_delta, accumulated) => {
            if (!isCurrent()) {
                return;
            }
            set({ streamingContent: accumulated });
        },
        onThought: (event) => {
            const content =
                typeof event.content === 'string'
                    ? event.content
                    : String(event.thought ?? '');
            if (!content || !isCurrent()) {
                return;
            }
            set((state) => ({
                thoughts: [
                    ...state.thoughts,
                    {
                        id: `${state.thoughts.length}`,
                        // The frame names the step in `step_type`; there is no `title` field.
                        // Falling straight to "Thinking" made every live step look alike and
                        // is what stopped a tabular run being recognisable while it ran.
                        title: String(event.title ?? event.step_type ?? 'Thinking'),
                        content,
                        stepType:
                            typeof event.step_type === 'string' ? event.step_type : undefined,
                        detail: typeof event.detail === 'string' ? event.detail : undefined,
                        activity: event.activity as ThoughtEntry['activity'],
                        progress: event.progress as ThoughtEntry['progress'],
                        stepIndex:
                            typeof event.step_index === 'number' ? event.step_index : undefined,
                    },
                ],
            }));
        },
        onConversationMetadata: (event) => {
            // Applied even when superseded: the title belongs to a conversation in the
            // rail, not to the message list on screen.
            const title = event.conversation_title;
            if (typeof title === 'string' && title) {
                set((state) => ({
                    conversations: state.conversations.map((item) =>
                        item.id === conversationId ? { ...item, title } : item,
                    ),
                }));
            }
        },
        onDone: (event, accumulated) => {
            if (!isCurrent()) {
                return;
            }
            const finalMessage: ChatMessage = {
                id: String(event.message_id ?? STREAMING_MESSAGE_ID),
                conversation_id: conversationId,
                role: 'assistant',
                content: accumulated,
                timestamp: new Date().toISOString(),
                model_deployment_name: event.model_deployment_name,
                agent_display_name: event.agent_display_name,
                augmented: event.augmented,
                metadata: event.metadata,
                // Carried onto the finished message so the reasoning steps stay
                // available after the stream ends instead of disappearing with the
                // streaming placeholder.
                thoughts:
                    getState().thoughts.length > 0 ? [...getState().thoughts] : undefined,
            };
            set((state) => ({
                // Appended by id rather than blindly: in a shared conversation the same
                // assistant message also arrives as a `collaboration.message.created` event,
                // and whichever of the two lands second must update the message rather than
                // add a second copy of it.
                messages: mergeCollaborationMessage(
                    state.messages,
                    finalMessage as CollaborationMessage,
                ),
                streaming: false,
                streamingContent: '',
                reconnectPhase: null,
            }));
        },
        onCancelled: (_event, accumulated) => {
            if (!isCurrent()) {
                return;
            }
            // Partial output is kept: discarding what was already generated is more
            // annoying than useful when someone stops a long answer.
            if (accumulated) {
                set((state) => ({
                    messages: [
                        ...state.messages,
                        {
                            id: `cancelled-${Date.now()}`,
                            conversation_id: conversationId,
                            role: 'assistant',
                            content: accumulated,
                            timestamp: new Date().toISOString(),
                            thoughts:
                                state.thoughts.length > 0 ? [...state.thoughts] : undefined,
                        },
                    ],
                }));
            }
            set({ streaming: false, streamingContent: '', reconnectPhase: null });
        },
        onError: (message) => {
            if (!isCurrent()) {
                return;
            }
            set({
                streaming: false,
                streamingContent: '',
                reconnectPhase: null,
                streamError: message,
            });
        },
        onReconnecting: () => {
            if (!isCurrent()) {
                return;
            }
            // Nothing is arriving yet: the status check and the reattach request are still
            // in flight, and the response on screen really has stopped moving.
            set({ reconnectPhase: 'connecting', streamError: null });
        },
        onReconnect: () => {
            if (!isCurrent()) {
                return;
            }
            // Attached, and the replay starts at the first event, so what is on screen is
            // about to be sent again and has to be cleared or it would double up.
            //
            // The phase moves to 'reconnected' rather than staying at 'connecting': from
            // here the stream behaves like any other, so the interface should too. A
            // response that is visibly working must not keep saying it is reconnecting.
            set({
                streamingContent: '',
                thoughts: [],
                reconnectPhase: 'reconnected',
                streamError: null,
            });
        },
    };
}

/**
 * Run a chat stream and fold its events into the store.
 *
 * Shared by three callers that all end in the same place: a normal send, a retry, and an
 * edit. Retry and edit do not generate anything themselves — their endpoints create the
 * next thread attempt and hand back a ready-made request body for this endpoint — so they
 * reuse this rather than duplicating the event handling.
 */
async function runChatStream(
    requestBody: ChatStreamRequest,
    conversationId: string,
    options: {
        isNewConversation?: boolean;
        reloadOnDone?: boolean;
        /** Which API family this stream belongs to, so a cancel reaches the right route. */
        kind?: ConversationKind;
        /** Endpoint and recovery overrides for a shared conversation. */
        stream?: ChatStreamOptions;
        /** Optimistic user message to reconcile with the server's id. */
        pendingUserMessageId?: string | null;
    } = {},
): Promise<void> {
    const { set, getState } = {
        set: (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) =>
            useChatStore.setState(partial as never),
        getState: () => useChatStore.getState(),
    };

    const controller = new AbortController();
    activeStreamController = controller;
    streamingConversationId = conversationId;
    streamingConversationKind = options.kind ?? 'personal';

    // Two different questions, and conflating them breaks one case each way.
    //
    // `ownsController` is about teardown: does this invocation still own the module's
    // controller, or has a newer send installed its own? Only the owner may clear it.
    //
    // `isCurrent` is about rendering: is this stream's conversation still the one on
    // screen? Switching threads mid-response clears the controller, so that alone used to
    // answer both. It does not cover a brand-new conversation, where the reader can open a
    // different thread during the round trip that creates it — before there is any
    // controller to clear — leaving the handlers free to write this answer into whatever
    // they opened.
    const ownsController = () => activeStreamController === controller;
    const isCurrent = () =>
        ownsController() && getState().activeConversationId === conversationId;

    await streamChat(
        requestBody,
        buildStreamHandlers(
            conversationId,
            isCurrent,
            set,
            getState,
            options.pendingUserMessageId,
        ),
        controller.signal,
        options.stream,
    );

    // Only tear down if this stream is still the active one; a newer send may already have
    // installed its own controller. Captured before the teardown because clearing the
    // controller makes ownsController() false for every check after it.
    const wasCurrent = isCurrent();
    if (ownsController()) {
        activeStreamController = null;
        streamingConversationId = null;
        set({ streaming: false, reconnectPhase: null });
    }

    // Retry and edit rewrite thread state server-side, so the authoritative message list
    // has to be re-read rather than patched locally. Skipped when the reader is elsewhere,
    // since reloadMessages reads whatever is on screen and would refetch a thread this
    // stream never touched.
    if (options.reloadOnDone && wasCurrent) {
        await getState().reloadMessages();
    }

    // Refresh the rail so a newly created conversation appears with its server-side
    // generated title.
    if (options.isNewConversation) {
        await getState().loadConversations({ reset: true });
    }
}

/**
 * Attach to a generation that is still running for a conversation.
 *
 * The answer is produced on the server and survives the HTTP connection, so opening a
 * conversation whose response is still being written should show it continuing rather than
 * a truncated message. chat-conversations.js:1695 does the same after selecting a thread.
 *
 * Returns false when there is nothing live to attach to, which is the ordinary case.
 */
async function resumeChatStream(conversationId: string): Promise<boolean> {
    const set = (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) =>
        useChatStore.setState(partial as never);
    const getState = () => useChatStore.getState();

    // Checked before any state is touched so opening an ordinary conversation never
    // flickers a streaming placeholder.
    const status = await fetchStreamStatus(conversationId);
    if (!status?.pending) {
        return false;
    }

    // A stream started in the meantime owns the UI; do not displace it.
    if (activeStreamController || getState().activeConversationId !== conversationId) {
        return false;
    }

    const controller = new AbortController();
    activeStreamController = controller;
    // Deliberately NOT setting streamingConversationId. That marks a stream this tab
    // started, and it is the only thing that lets Stop POST /api/chat/stream/cancel, which
    // is a real server-side cancellation. This stream belongs to whoever started it —
    // another tab, or this page before a reload — so Stop here detaches this reader instead
    // of ending a generation somebody else is still waiting on. The classic client draws the
    // same line: reattachStreamingConversation (chat-streaming.js:1157) opens its reattached
    // stream with no cancelEndpoint at all.
    const isCurrent = () => activeStreamController === controller;

    set({
        streaming: true,
        streamingContent: '',
        thoughts: [],
        streamError: null,
        reconnectPhase: 'connecting',
    });

    await reattachChatStream(
        conversationId,
        buildStreamHandlers(conversationId, isCurrent, set, getState),
        controller.signal,
    );

    if (isCurrent()) {
        activeStreamController = null;
        set({ streaming: false, reconnectPhase: null });
    }

    return true;
}

/**
 * Work out which API family a conversation belongs to by asking.
 *
 * Only reached for a conversation that is not in the loaded rail — a deep link, or one
 * opened straight after being shared.
 *
 * A single endpoint answers this. It used to be inferred by calling the personal metadata
 * endpoint and reading its 404 as "then it is a shared one", which was correct but made the
 * browser log a failed request every time somebody followed a link to a shared conversation.
 *
 * A collaboration response is handed back rather than written to a store: it is the same
 * document the participants panel and the composer need, so returning it saves a second
 * request — but stashing it somewhere for `selectConversation` to find would be a write for
 * a conversation that is not open yet, which is exactly the class of stale write the
 * collaboration store now refuses.
 *
 * With `requireExists`, a conversation the server does not recognise is a rejection rather
 * than a default, which is what lets a dead link be reported instead of opening as an empty
 * chat.
 */
async function resolveConversationKind(
    conversationId: string,
    options: { requireExists?: boolean } = {},
): Promise<{ kind: ConversationKind; conversation?: CollaborationConversation }> {
    try {
        const { kind, conversation } = await fetchConversationKind(conversationId);
        return { kind, conversation };
    } catch (error) {
        if (options.requireExists) {
            throw error;
        }
        // Not knowing is not the same as knowing it is shared, and personal is the
        // overwhelmingly common case, so an unreachable server degrades to the thread simply
        // failing to load rather than to collaboration calls that could never work.
        return { kind: 'personal' };
    }
}

/**
 * Attach to a shared conversation's event stream and fold what arrives into the stores.
 *
 * This is what makes the conversation shared rather than merely visible: without it, a
 * message written by somebody else appears only if the reader reloads.
 */
function attachCollaborationEvents(conversationId: string): void {
    const set = (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) =>
        useChatStore.setState(partial as never);
    const getState = () => useChatStore.getState();
    const collaboration = () => useCollaborationStore.getState();
    const currentUserId = () => useBootstrapStore.getState().data?.user?.id;

    /** Ignore anything that arrives after the reader has moved to another conversation. */
    const stillOpen = () => getState().activeConversationId === conversationId;

    /**
     * Re-read this reader's own membership after a change to it.
     *
     * The event's payload cannot answer the question. Every publishing route serializes the
     * conversation for the user who *caused* the event, so its `can_*` flags, role and
     * membership status are theirs — an owner's action would hand every member owner
     * permissions, and a member leaving would tell everyone else they can no longer post.
     * Only a fetch returns the flags computed for the reader.
     */
    const refreshOwnMembership = () => {
        if (stillOpen()) {
            void collaboration()
                .loadConversation(conversationId)
                .then(() => syncListedPermissions(conversationId));
        }
    };

    stopCollaborationEvents();
    detachCollaborationEvents = subscribeToCollaborationEvents(conversationId, {
        onMessageCreated: (message, conversation) => {
            if (conversation) {
                collaboration().applyBroadcast(conversation);
            }
            if (!stillOpen()) {
                return;
            }

            set((state) => ({
                messages: mergeCollaborationMessage(state.messages, message, {
                    currentUserId: currentUserId(),
                }),
            }));

            const senderId = String(message.sender?.user_id ?? '').trim();
            if (!senderId || senderId === currentUserId()) {
                return;
            }

            // Being named is the one thing in a shared conversation worth interrupting for;
            // an ordinary message is already visible in the thread.
            if (mentionsCurrentUser(message.metadata as Record<string, unknown>, currentUserId())) {
                toast.info(
                    `${participantName(message.sender)} mentioned you in this conversation.`,
                );
            }

            // Somebody else has written, so the unread marker this thread may have just
            // acquired is already satisfied by the reader looking at it.
            void markCollaborationConversationRead(conversationId).catch(() => {
                /* Read receipts are advisory. */
            });
        },

        onMessageDeleted: (messageId, deletedByUserId, conversation) => {
            if (conversation) {
                collaboration().applyBroadcast(conversation);
            }
            if (!stillOpen()) {
                return;
            }
            set((state) => ({
                messages: state.messages.filter((message) => message.id !== messageId),
            }));
            if (deletedByUserId && deletedByUserId !== currentUserId()) {
                toast.info('A message was deleted from this conversation.');
            }
        },

        onMessageMasked: (message, updatedByUserId) => {
            if (!stillOpen()) {
                return;
            }
            set((state) => ({
                messages: state.messages.map((existing) =>
                    existing.id === message.id ? { ...existing, ...message } : existing,
                ),
            }));
            if (updatedByUserId && updatedByUserId !== currentUserId()) {
                toast.info('A message in this conversation was masked.');
            }
        },

        onMessageBlockRevised: (messageId, blockRevisions, updatedByUserId) => {
            if (!stillOpen()) {
                return;
            }
            // Only the revision map is replaced. The editor reads the current version out of
            // the message's metadata, so this is enough for an open editor to follow along.
            set((state) => ({
                messages: state.messages.map((existing) =>
                    existing.id === messageId
                        ? {
                              ...existing,
                              metadata: {
                                  ...(existing.metadata as Record<string, unknown>),
                                  block_revisions: blockRevisions,
                              },
                          }
                        : existing,
                ),
            }));
            if (updatedByUserId && updatedByUserId !== currentUserId()) {
                toast.info('A diagram in this conversation was edited.');
            }
        },

        onMessageImageRevised: (messageId, imageRevisions, imageUrl, updatedByUserId) => {
            if (!stillOpen()) {
                return;
            }
            // The URL is replaced as well as the history. An edited image is served from a
            // different URL carrying its revision id, and without taking it the participant
            // would keep showing the copy already in their cache.
            set((state) => ({
                messages: state.messages.map((existing) =>
                    existing.id === messageId
                        ? {
                              ...existing,
                              content: imageUrl || existing.content,
                              metadata: {
                                  ...(existing.metadata as Record<string, unknown>),
                                  image_revisions: imageRevisions,
                              },
                          }
                        : existing,
                ),
            }));
            if (updatedByUserId && updatedByUserId !== currentUserId()) {
                toast.info('An image in this conversation was changed.');
            }
        },

        onMessageVisualStyleUpdated: (message) => {
            if (!stillOpen()) {
                return;
            }
            // Only the styles are taken, not the whole message. Everything else in the
            // broadcast is unchanged by a recolour, and replacing it wholesale would discard
            // client-side state the thread has built up around the message.
            //
            // No toast, and no interest in who did it: a colour change is cosmetic, and a drag
            // on somebody else's screen would announce itself repeatedly for something the
            // reader can already see happening.
            const styles =
                (message.metadata as Record<string, unknown> | undefined)?.visual_styles ?? {};
            set((state) => ({
                messages: state.messages.map((existing) =>
                    existing.id === message.id
                        ? {
                              ...existing,
                              metadata: {
                                  ...(existing.metadata as Record<string, unknown>),
                                  visual_styles: styles,
                              },
                          }
                        : existing,
                ),
            }));
        },

        onTyping: (user, isTyping, expiresAt) => {
            if (!stillOpen()) {
                return;
            }
            collaboration().applyTyping(user, isTyping, expiresAt, currentUserId());
        },

        onConversationUpdated: (conversation) => {
            // Only the facts every reader shares. The capability flags, role, membership
            // status and pin state in this payload are the acting user's, not this one's.
            collaboration().applyBroadcast(conversation);
            if (!conversation.id) {
                return;
            }
            const facts = conversationFactsOnly(conversation);
            // The rail row and the header read from the conversation list, so a change to
            // the title or the participant count lands there too — but the reader's own pin
            // and hide state must survive it, which is why the same stripping applies.
            set((state) => ({
                conversations: state.conversations.map((item) =>
                    item.id === conversation.id ? { ...item, ...facts } : item,
                ),
                metadata:
                    state.activeConversationId === conversation.id && state.metadata
                        ? ({ ...state.metadata, ...facts } as ConversationMetadata)
                        : state.metadata,
            }));
        },

        onMembersInvited: (participants) => {
            const names = participants
                .map((participant) => participantName(participant))
                .filter(Boolean);
            if (names.length > 0 && stillOpen()) {
                toast.info(
                    names.length === 1
                        ? `${names[0]} was invited to this conversation.`
                        : `${names.length} people were invited to this conversation.`,
                );
            }
        },

        onMemberRemoved: (participant) => {
            const removedId = String(participant?.user_id ?? '').trim();
            if (removedId && removedId === currentUserId()) {
                // The reader has lost access. Leaving the thread on screen would show a
                // conversation every subsequent request will refuse.
                toast.info('You no longer have access to this shared conversation.');
                removeConversationLocally(conversationId);
                return;
            }
            if (participant && stillOpen()) {
                toast.info(`${participantName(participant)} was removed from this conversation.`);
            }
            // Somebody leaving can promote somebody else, so the reader's own role may have
            // changed even though they were not the subject of the event.
            refreshOwnMembership();
        },

        onMemberRoleUpdated: (participant) => {
            if (participant && stillOpen()) {
                const role = String(participant.role ?? 'member');
                toast.info(`${participantName(participant)} is now ${role}.`);
            }
            refreshOwnMembership();
        },

        onInviteAnswered: (participant, accepted) => {
            if (participant && accepted && stillOpen()) {
                toast.success(`${participantName(participant)} joined the conversation.`);
            }
        },

        onConversationDeleted: () => {
            toast.info('This shared conversation was deleted.');
            removeConversationLocally(conversationId);
        },
    });
}

/**
 * Whether a conversation must be driven through the collaboration API.
 *
 * Answered from what the client already knows — the open conversation's resolved kind, or
 * the rail row's `conversation_kind` — so no request is needed to decide which endpoint an
 * action belongs to.
 */
function isCollaborativeConversation(state: ChatState, conversationId: string): boolean {
    if (state.activeConversationId === conversationId) {
        return state.activeConversationKind === 'collaborative';
    }
    const listed = state.conversations.find((item) => item.id === conversationId);
    return isCollaborative(listed);
}

/**
 * Drop a conversation from the interface without asking the server to delete it.
 *
 * Used when the server has already made it inaccessible — deleted by its owner, or the
 * reader removed from it — where the ordinary delete path would post to a conversation that
 * would rightly refuse.
 */
function removeConversationLocally(conversationId: string): void {
    const store = useChatStore.getState();
    useChatStore.setState({
        conversations: store.conversations.filter((item) => item.id !== conversationId),
        // Pruned here as well as in the ordinary removal paths. This one is driven by a
        // server event rather than by a click, so without it a row could vanish from under
        // a live selection and leave the bulk bar counting a conversation that is gone.
        selectedConversationIds: store.selectedConversationIds.filter(
            (id) => id !== conversationId,
        ),
        selectionAnchorId:
            store.selectionAnchorId === conversationId ? null : store.selectionAnchorId,
    });
    if (store.activeConversationId === conversationId) {
        store.startNewConversation();
    }
}

/**
 * Copy the reader's freshly-read permissions onto the matching rail row.
 *
 * The feed row and the loaded conversation are two copies of the same viewer-scoped flags,
 * and they are refreshed independently: a role change re-reads the membership into the
 * collaboration store but does not reload the feed. Left to drift, the rail would describe
 * a removal from the stale copy while `removeConversation` posted the action chosen from
 * the fresh one — offering to "Leave" a conversation and then deleting it for everybody.
 *
 * Syncing the flags rather than choosing a winner keeps one answer to the question.
 */
function syncListedPermissions(conversationId: string): void {
    const detail = useCollaborationStore.getState().conversation;
    if (!detail || detail.id !== conversationId) {
        return;
    }

    const store = useChatStore.getState();
    const listed = store.conversations.find((item) => item.id === conversationId);
    if (
        !listed ||
        (listed.can_delete_conversation === detail.can_delete_conversation &&
            listed.can_leave_conversation === detail.can_leave_conversation)
    ) {
        return;
    }

    useChatStore.setState({
        conversations: store.conversations.map((item) =>
            item.id === conversationId
                ? {
                      ...item,
                      can_delete_conversation: detail.can_delete_conversation,
                      can_leave_conversation: detail.can_leave_conversation,
                  }
                : item,
        ),
    });
}

export const useChatStore = create<ChatState>((set, get) => ({
    conversations: [],
    conversationsLoading: false,
    conversationsError: null,
    hasMore: false,
    nextCursor: null,
    searchTerm: '',

    selectedConversationIds: [],
    selectionAnchorId: null,

    activeConversationId: null,
    activeConversationKind: null,
    messages: [],
    messagesLoading: false,
    messagesError: null,

    streaming: false,
    streamingContent: '',
    thoughts: [],
    streamError: null,
    reconnectPhase: null,

    drawerMode: null,
    metadata: null,
    metadataLoading: false,
    metadataError: null,
    attemptsByThread: {},

    loadConversations: async (options = {}) => {
        const { reset = true, search } = options;
        const searchTerm = search ?? get().searchTerm;

        set({ conversationsLoading: true, conversationsError: null });
        try {
            const page = await fetchConversationFeed({
                search: searchTerm,
                pageSize: FEED_PAGE_SIZE,
                cursor: reset ? null : get().nextCursor,
            });

            set((state) => {
                const conversations = reset
                    ? page.conversations
                    : [...state.conversations, ...page.conversations];
                // Selected ids that are no longer on the page are dropped here. Without
                // this, a bulk delete taken after a search or a reload would act on rows
                // the user can no longer see — the one surprise a delete button must never
                // produce.
                const selection = pruneSelection(
                    {
                        ids: state.selectedConversationIds,
                        anchorId: state.selectionAnchorId,
                    },
                    conversations.map((conversation) => conversation.id),
                );
                return {
                    conversations,
                    hasMore: Boolean(page.has_more),
                    nextCursor: page.next_cursor,
                    conversationsLoading: false,
                    selectedConversationIds: selection.ids,
                    selectionAnchorId: selection.anchorId,
                };
            });
        } catch (error) {
            set({
                conversationsLoading: false,
                conversationsError:
                    error instanceof Error ? error.message : 'Failed to load conversations.',
            });
        }
    },

    loadMore: async () => {
        if (!get().hasMore || get().conversationsLoading) {
            return;
        }
        await get().loadConversations({ reset: false });
    },

    setSearchTerm: (searchTerm) => {
        set({ searchTerm });
        void get().loadConversations({ reset: true, search: searchTerm });
    },

    selectConversation: async (conversationId, options = {}) => {
        // Any stream still running belongs to the thread being left, so its reader is
        // dropped: left attached, its handlers would append the finished response into the
        // newly selected conversation's message list.
        //
        // Detached rather than cancelled. The generation carries on server-side and is
        // picked back up by `resumeChatStream` below when this thread is opened again,
        // which is what chat-conversations.js:1695 does. Cancelling here meant that simply
        // clicking another conversation ended the answer — and ended it with nothing saved
        // at all when it had not yet produced its first token.
        detachActiveStream();
        // Likewise the event stream: it is a live connection, and left attached it would
        // keep delivering the previous conversation's messages into this one.
        stopCollaborationEvents();
        useCollaborationStore.getState().reset();

        // Known from the rail row when there is one, which is the common case and costs no
        // request. A conversation opened from a link is not in the list yet, so its kind is
        // resolved below by asking the collaboration API about it.
        const listed = get().conversations.find((item) => item.id === conversationId);
        const knownKind: ConversationKind | null =
            options.kind ?? (listed ? (isCollaborative(listed) ? 'collaborative' : 'personal') : null);

        set({
            activeConversationId: conversationId,
            activeConversationKind: knownKind,
            messages: [],
            messagesError: null,
            streamingContent: '',
            thoughts: [],
            streamError: null,
            reconnectPhase: null,
            // Metadata belongs to the previous conversation; drop it so the drawer never
            // shows another thread's documents.
            metadata: null,
            metadataError: null,
            // Thread ids are per conversation, so learned attempt sets do not carry over.
            attemptsByThread: {},
        });
        // Mirrored so the collaboration store can refuse a membership write that arrives for
        // a conversation which is no longer open.
        useCollaborationStore.getState().setActiveConversation(conversationId);

        if (!conversationId) {
            return;
        }

        set({ messagesLoading: true });
        try {
            let prefetched = options.prefetched;
            let kind = knownKind;
            if (!kind) {
                const resolved = await resolveConversationKind(conversationId);
                kind = resolved.kind;
                prefetched = prefetched ?? resolved.conversation;
            }
            // Discarded if the reader moved on while the kind was being resolved; without
            // this the wrong thread's messages would be fetched and displayed.
            if (get().activeConversationId !== conversationId) {
                return;
            }
            set({ activeConversationKind: kind });

            const { messages } =
                kind === 'collaborative'
                    ? await fetchCollaborationMessages(conversationId)
                    : await fetchMessages(conversationId);

            if (get().activeConversationId !== conversationId) {
                return;
            }
            set({ messages: messages ?? [], messagesLoading: false });

            // The header badges describe what this conversation is bound to, so its
            // metadata is needed as soon as it opens rather than only when a drawer is
            // expanded. Advisory: a failure leaves the badges off, not the thread broken.
            void get().loadMetadata(conversationId);

            if (kind === 'collaborative') {
                // Membership and the capability flags that gate the composer and the
                // participants panel.
                //
                // The rail row was serialized when the feed was read, which may have been
                // long enough ago for a role change to have happened since. Opening the
                // conversation is the moment fresher flags become available, so the row is
                // brought into line rather than left describing an old permission — it is
                // what the row menu and the delete confirmation read.
                if (prefetched?.id === conversationId) {
                    useCollaborationStore.getState().setConversation(prefetched);
                    syncListedPermissions(conversationId);
                } else {
                    void useCollaborationStore
                        .getState()
                        .loadConversation(conversationId)
                        .then(() => syncListedPermissions(conversationId));
                }
                // Then the live stream that keeps the thread current while other people are
                // writing in it.
                attachCollaborationEvents(conversationId);
            } else {
                // Generation outlives the connection that started it, so a thread opened
                // while its answer is still being written picks the stream back up instead of
                // showing a message that stops mid-sentence.
                //
                // Deliberately not attempted for a shared conversation: the generation runs
                // in a hidden source conversation whose id the browser is never given, so
                // the status and reattach endpoints have nothing to address.
                void resumeChatStream(conversationId).catch(() => {
                    /* Advisory: the thread is readable whether or not a resume was possible. */
                });
            }

            // Only clear the marker when there is one. Calling unconditionally produced a
            // 404 for collaboration conversations, which are stored separately and have
            // their own endpoint.
            if (listed?.has_unread_assistant_response) {
                void markConversationRead(conversationId, kind === 'collaborative')
                    .then(() => {
                        set((state) => ({
                            conversations: state.conversations.map((item) =>
                                item.id === conversationId
                                    ? { ...item, has_unread_assistant_response: false }
                                    : item,
                            ),
                        }));
                    })
                    .catch(() => {
                        /* Read receipts are advisory; the thread still opened fine. */
                    });
            }
        } catch (error) {
            if (get().activeConversationId !== conversationId) {
                return;
            }
            set({
                messagesLoading: false,
                messagesError:
                    error instanceof Error ? error.message : 'Failed to load messages.',
            });
        }
    },

    /**
     * Open a conversation named by the URL.
     *
     * The load itself is `selectConversation`'s job; what is different here is that a link
     * can name a conversation that has been deleted, or one belonging to somebody else,
     * whereas a row in the rail is one the server has just listed.
     *
     * Existence is checked against a metadata endpoint rather than inferred from the
     * message load, because neither message endpoint is an existence check:
     * `/api/get_messages` turns a not-found conversation into `{'messages': []}` with a 200
     * (`route_backend_conversations.py`), and its collaboration counterpart answers the same
     * way for a conversation with no messages yet. A deleted conversation would otherwise
     * open as an empty chat, keep its id in the address bar, and remain the target of the
     * next message sent.
     *
     * Which endpoint answers that question is itself the thing being determined, so the
     * probe doubles as the kind resolution and its result is handed to
     * `selectConversation` rather than being asked for twice.
     */
    openLinkedConversation: async (conversationId) => {
        let resolved: { kind: ConversationKind; conversation?: CollaborationConversation };
        try {
            resolved = await resolveConversationKind(conversationId, { requireExists: true });
        } catch {
            toast.error(
                'Could not open that conversation. It may have been deleted, or you may not have access to it.',
            );
            return;
        }

        await get().selectConversation(conversationId, {
            kind: resolved.kind,
            prefetched: resolved.conversation,
        });

        // Still checked: the conversation exists, but its messages may not have loaded.
        if (get().messagesError) {
            toast.error(
                'Could not open that conversation. It may have been deleted, or you may not have access to it.',
            );
            get().startNewConversation();
        }
    },

    startNewConversation: () => {
        // Detach first: the running stream belongs to the previous thread and must not
        // deliver its response into the empty new one. Detached rather than cancelled, so
        // starting a new chat leaves the previous answer to finish and be saved rather than
        // discarding it — reopening that thread resumes or shows the completed reply.
        detachActiveStream();
        stopCollaborationEvents();
        useCollaborationStore.getState().reset();

        // The conversation row is created by the server on first send, so a new chat is
        // purely a local reset until then. This avoids leaving empty conversations behind
        // when someone clicks New Chat and navigates away.
        set({
            activeConversationId: null,
            // A new chat is always personal. Sharing is something done to a conversation
            // that already exists, so there is no way to start one shared.
            activeConversationKind: null,
            messages: [],
            messagesError: null,
            streamingContent: '',
            thoughts: [],
            streamError: null,
            reconnectPhase: null,
            metadata: null,
            metadataError: null,
            // Closed rather than left behind. The header's Contents and Documents toggles
            // are drawn only while a conversation is open, so an open drawer would survive
            // with nothing left to describe and no control to dismiss it from. The classic
            // interface closes it here too.
            drawerMode: null,
        });
        useCollaborationStore.getState().setActiveConversation(null);
    },

    renameConversation: async (conversationId, title) => {
        const previous = get().conversations;
        const collaborative = isCollaborativeConversation(get(), conversationId);
        set({
            conversations: previous.map((conversation) =>
                conversation.id === conversationId ? { ...conversation, title } : conversation,
            ),
        });
        try {
            if (collaborative) {
                await renameCollaborationConversation(conversationId, title);
            } else {
                await renameConversationApi(conversationId, title);
            }
        } catch {
            set({ conversations: previous });
        }
    },

    /**
     * Remove a conversation from the reader's view.
     *
     * For a shared conversation this is not necessarily a deletion. Only an owner may
     * destroy one for everybody; anybody else leaves it, which removes it from their rail
     * and leaves the conversation intact for the remaining participants. The server reports
     * which applies, so the right one is chosen rather than assumed — posting `delete` as a
     * member is refused, and posting `leave` as the sole owner would strand the thread.
     */
    removeConversation: async (conversationId, decidedAction) => {
        const previous = get().conversations;
        const listed = previous.find((conversation) => conversation.id === conversationId);
        const collaborative = isCollaborativeConversation(get(), conversationId);

        set({
            conversations: previous.filter((conversation) => conversation.id !== conversationId),
            selectedConversationIds: get().selectedConversationIds.filter(
                (id) => id !== conversationId,
            ),
            // A range must not be able to extend from a row that has gone.
            selectionAnchorId:
                get().selectionAnchorId === conversationId ? null : get().selectionAnchorId,
        });

        if (get().activeConversationId === conversationId) {
            get().startNewConversation();
        }

        try {
            if (collaborative) {
                // A caller that showed the user which of the two this would be passes it in,
                // so what was promised is what happens. Without that the decision would be
                // taken a second time, from a copy of the permissions that may have been
                // refreshed in between — offering to leave a conversation and then deleting
                // it for everybody.
                const detail =
                    useCollaborationStore.getState().conversation?.id === conversationId
                        ? useCollaborationStore.getState().conversation
                        : (listed as CollaborationConversation | undefined);
                const action =
                    decidedAction ?? (detail?.can_delete_conversation ? 'delete' : 'leave');
                await collaborationDeleteAction(conversationId, action);
            } else {
                await deleteConversationApi(conversationId);
            }
        } catch (error) {
            set({ conversations: previous });
            toast.error(
                error instanceof Error ? error.message : 'Could not remove that conversation.',
            );
        }
    },

    togglePinned: async (conversationId) => {
        const conversation = get().conversations.find((item) => item.id === conversationId);
        if (!conversation) {
            return;
        }
        // The server owns the toggle, so the optimistic value is only a guess at what it
        // will return; the authoritative value replaces it below.
        const optimistic = !conversation.is_pinned;
        set({
            conversations: get().conversations.map((item) =>
                item.id === conversationId ? { ...item, is_pinned: optimistic } : item,
            ),
        });
        try {
            const result = isCollaborative(conversation)
                ? await toggleCollaborationPinned(conversationId)
                : await toggleConversationPinned(conversationId);
            set({
                conversations: get().conversations.map((item) =>
                    item.id === conversationId
                        ? { ...item, is_pinned: Boolean(result.is_pinned) }
                        : item,
                ),
            });
            // Pinning changes ordering, so the feed is re-read rather than re-sorted here.
            await get().loadConversations({ reset: true });
        } catch {
            set({
                conversations: get().conversations.map((item) =>
                    item.id === conversationId ? { ...item, is_pinned: !optimistic } : item,
                ),
            });
        }
    },

    toggleHidden: async (conversationId) => {
        const conversation = get().conversations.find((item) => item.id === conversationId);
        if (!conversation) {
            return;
        }
        // Hidden conversations drop out of the default feed, so the row is removed rather
        // than re-rendered with a new flag.
        set({
            conversations: get().conversations.filter((item) => item.id !== conversationId),
            selectedConversationIds: get().selectedConversationIds.filter(
                (id) => id !== conversationId,
            ),
            selectionAnchorId:
                get().selectionAnchorId === conversationId ? null : get().selectionAnchorId,
        });
        try {
            if (isCollaborative(conversation)) {
                await toggleCollaborationHidden(conversationId);
            } else {
                await toggleConversationHidden(conversationId);
            }
        } catch {
            await get().loadConversations({ reset: true });
        }
    },

    applyConversationSelection: (conversationId, intent) => {
        const state = get();
        const current: SelectionState = {
            ids: state.selectedConversationIds,
            anchorId: state.selectionAnchorId,
        };
        // The order a range reads is the rail's list as rendered, not the order ids happen
        // to have been picked in, so a Shift+click always spans what the user can see.
        const next = applySelection(
            current,
            conversationId,
            intent,
            state.conversations.map((conversation) => conversation.id),
        );
        set({ selectedConversationIds: next.ids, selectionAnchorId: next.anchorId });
    },

    /** Selects the rows currently loaded, which is what the user can actually see. */
    selectAllConversations: () => {
        const ids = get().conversations.map((item) => item.id);
        set({ selectedConversationIds: ids, selectionAnchorId: ids[0] ?? null });
    },

    clearConversationSelection: () => {
        set({ selectedConversationIds: [], selectionAnchorId: null });
    },

    /**
     * Remove every selected conversation.
     *
     * Two things vary row by row and both decide which request is correct, so the selection
     * is split rather than posted whole. Personal conversations go to the bulk route in one
     * request. Shared ones go one at a time to the collaboration route, as a delete for an
     * owner and a leave for everybody else — the server refuses the wrong one, and a leave
     * posted as a delete would destroy a thread other people are still using.
     */
    bulkRemoveConversations: async () => {
        const previous = get().conversations;
        const targets = selectedConversations(previous, get().selectedConversationIds);
        if (targets.length === 0) {
            return;
        }

        const { personalIds } = partitionBySpecies(targets);
        const removals = collaborativeRemovals(targets);
        const removedIds = new Set(targets.map((conversation) => conversation.id));

        set({
            conversations: previous.filter(
                (conversation) => !removedIds.has(conversation.id),
            ),
            selectedConversationIds: [],
            selectionAnchorId: null,
        });

        const activeId = get().activeConversationId;
        if (activeId && removedIds.has(activeId)) {
            get().startNewConversation();
        }

        try {
            let failed = 0;

            if (personalIds.length > 0) {
                const result = await deleteConversationsApi(personalIds);
                failed += (result?.failed_ids ?? []).length;
            }

            if (removals.length > 0) {
                // Settled rather than all: one shared conversation refusing must not
                // abandon the rest of the batch half-done.
                const outcomes = await Promise.allSettled(
                    removals.map((removal) =>
                        collaborationDeleteAction(removal.id, removal.action),
                    ),
                );
                failed += outcomes.filter((outcome) => outcome.status === 'rejected').length;
            }

            const message = partialFailureMessage(targets.length, failed, 'delete', 'deleted');
            if (message) {
                toast.error(message);
                // The optimistic removal was wrong for whatever failed, so the list is
                // re-read rather than guessed at.
                await get().loadConversations({ reset: true });
            }
        } catch (error) {
            set({ conversations: previous });
            toast.error(
                error instanceof Error
                    ? error.message
                    : 'Could not remove those conversations.',
            );
        }
    },

    /**
     * Pin or unpin every selected conversation.
     *
     * The caller passes the state to reach rather than a toggle. Toggling a mixed selection
     * would leave it inverted rather than uniform, which is never what was asked for.
     */
    bulkSetConversationsPinned: async (action) => {
        const previous = get().conversations;
        const targets = selectedConversations(previous, get().selectedConversationIds);
        if (targets.length === 0) {
            return;
        }

        const pinned = action === 'pin';
        const { personalIds } = partitionBySpecies(targets);
        // The collaboration route toggles, so anything already in the target state is left
        // alone — posting to it would flip it the wrong way.
        const collaborativeIds = collaborativeIdsNeedingPin(targets, action);
        const targetIds = new Set(targets.map((conversation) => conversation.id));

        set({
            conversations: previous.map((conversation) =>
                targetIds.has(conversation.id)
                    ? { ...conversation, is_pinned: pinned }
                    : conversation,
            ),
        });

        try {
            let failed = 0;

            if (personalIds.length > 0) {
                const result: BulkConversationResult = await bulkPinConversationsApi(
                    personalIds,
                    action,
                );
                failed += (result?.failed_ids ?? []).length;
            }

            if (collaborativeIds.length > 0) {
                const outcomes = await Promise.allSettled(
                    collaborativeIds.map((id) => toggleCollaborationPinned(id)),
                );
                failed += outcomes.filter((outcome) => outcome.status === 'rejected').length;
            }

            const message = partialFailureMessage(
                targets.length,
                failed,
                action,
                pinned ? 'pinned' : 'unpinned',
            );
            if (message) {
                toast.error(message);
            }

            // Pinning changes ordering, so the feed is re-read rather than re-sorted here.
            await get().loadConversations({ reset: true });
        } catch (error) {
            set({ conversations: previous });
            toast.error(
                error instanceof Error ? error.message : 'Could not update those conversations.',
            );
        }
    },

    /**
     * Hide every selected conversation.
     *
     * One-way, matching the single-row action: hidden conversations drop out of the feed and
     * the rail has no view that lists them, so there would be nothing to unhide from.
     */
    bulkHideSelectedConversations: async () => {
        const previous = get().conversations;
        const targets = selectedConversations(previous, get().selectedConversationIds);
        if (targets.length === 0) {
            return;
        }

        const { personalIds, collaborativeIds } = partitionBySpecies(targets);
        const hiddenIds = new Set(targets.map((conversation) => conversation.id));

        set({
            conversations: previous.filter((conversation) => !hiddenIds.has(conversation.id)),
            selectedConversationIds: [],
            selectionAnchorId: null,
        });

        const activeId = get().activeConversationId;
        if (activeId && hiddenIds.has(activeId)) {
            get().startNewConversation();
        }

        try {
            let failed = 0;

            if (personalIds.length > 0) {
                const result: BulkConversationResult = await bulkHideConversationsApi(
                    personalIds,
                    'hide',
                );
                failed += (result?.failed_ids ?? []).length;
            }

            if (collaborativeIds.length > 0) {
                const outcomes = await Promise.allSettled(
                    collaborativeIds.map((id) => toggleCollaborationHidden(id)),
                );
                failed += outcomes.filter((outcome) => outcome.status === 'rejected').length;
            }

            const message = partialFailureMessage(targets.length, failed, 'hide', 'hidden');
            if (message) {
                toast.error(message);
                await get().loadConversations({ reset: true });
            }
        } catch (error) {
            set({ conversations: previous });
            toast.error(
                error instanceof Error ? error.message : 'Could not hide those conversations.',
            );
        }
    },

    sendMessage: async (text, options) => {
        const trimmed = text.trim();
        if (!trimmed || get().streaming) {
            return;
        }

        let conversationId = get().activeConversationId;
        const isNewConversation = !conversationId;
        const collaborative = Boolean(
            conversationId && isCollaborativeConversation(get(), conversationId),
        );

        // A conversation is created up front so the streaming endpoint has a stable id to
        // attach to and so a cancel request has something to address. Only ever a personal
        // one: a shared conversation always already exists, because sharing is done to a
        // conversation rather than at the moment of writing into one.
        if (!conversationId) {
            try {
                const created = await createConversation(trimmed);
                conversationId = created.conversation_id;
                // The reader can open a conversation during that round trip, and if they do
                // their click wins. The message is still sent and its answer still generated
                // and saved — it appears in the rail and is there when they come back — but
                // the interface stays where they put it instead of snapping back to a chat
                // they have already left. Claiming `activeConversationId` unconditionally
                // also let the thread they had just opened render its messages under this
                // new one, because the list is keyed on whatever is active.
                if (get().activeConversationId === null) {
                    set({ activeConversationId: conversationId, activeConversationKind: 'personal' });
                    // Mirrored like every other write to this field. Today the conversation just
                    // created can only be personal — this branch is reached only when nothing was
                    // open, which forces `collaborative` false above — so nothing would currently
                    // notice. Leaving it out would make the collaboration store's guard depend on
                    // that reasoning continuing to hold, and a shared conversation reachable here
                    // later would silently strand its composer at "checking access".
                    useCollaborationStore.getState().setActiveConversation(conversationId);
                }
            } catch (error) {
                set({
                    streamError:
                        error instanceof Error
                            ? error.message
                            : 'Could not start a new conversation.',
                });
                return;
            }
        }

        const bootstrap = useBootstrapStore.getState().data;
        const loadedCollaboration = useCollaborationStore.getState().conversation;
        // Guarded on the id: the participants panel keeps its own slot, but a stale load
        // would still resolve this message's mentions against another conversation's people.
        const collaborationConversation =
            loadedCollaboration?.id === conversationId ? loadedCollaboration : null;
        const replyTo = useCollaborationStore.getState().replyTo;

        // In a shared conversation most messages are people talking to each other, so the
        // AI is only brought in when something asks for it. `resolveSendTarget` applies the
        // classic client's rule; null means this message is for the participants alone.
        const invocationTarget = collaborative
            ? resolveSendTarget(
                  trimmed,
                  {
                      agentSelection: options.agentSelection,
                      promptId: options.promptId,
                      documentSearch: options.documentSearch,
                      webSearch: options.webSearch,
                      imageGeneration: options.imageGeneration,
                      deepResearch: options.deepResearch,
                      urlAccess: options.urlAccess,
                      modelDeployment: options.modelDeployment,
                  },
                  {
                      agents: bootstrap?.catalogs?.agents as AgentOption[] | undefined,
                      models: bootstrap?.catalogs?.models as ModelCatalogEntry[] | undefined,
                  },
              )
            : null;

        /**
         * Picker selections an explicit `@` tag replaces for this message.
         *
         * Only ever set in a shared conversation, where tagging a model or an agent is how
         * the assistant is addressed at all.
         */
        const taggedAgentSelection =
            invocationTarget?.target_type === 'agent'
                ? invocationTarget.agent_selection_key
                : undefined;
        const taggedModelSelection =
            invocationTarget?.target_type === 'model' ? invocationTarget.selection_key : undefined;

        const pendingUserMessageId = `pending-user-${Date.now()}`;
        const optimisticUserMessage: ChatMessage = {
            id: pendingUserMessageId,
            conversation_id: conversationId,
            role: 'user',
            content: trimmed,
            timestamp: new Date().toISOString(),
            // Carried locally so the bubble can draw the prompt as a collapsed block straight
            // away. Without it the message would render as one blob until the server echo
            // arrived and then silently rearrange itself.
            ...(options.promptInfo
                ? {
                      metadata: {
                          prompt_selection: promptSelectionMetadata(options.promptInfo),
                      },
                  }
                : {}),
        };

        // A shared message that is not addressed to the AI produces no stream, so the
        // interface must not sit in the streaming state waiting for one that never starts.
        const willStream = !collaborative || invocationTarget !== null;

        // Only ever false when the reader opened another conversation while this one was
        // being created. `messages`, `streaming` and the rest describe whatever is on
        // screen, so writing them then would show this question and its answer inside a
        // thread they have nothing to do with.
        const ownsScreen = get().activeConversationId === conversationId;

        if (ownsScreen) {
            set((state) => ({
                messages: [...state.messages, optimisticUserMessage],
                streaming: willStream,
                streamingContent: '',
                thoughts: [],
                streamError: null,
                reconnectPhase: null,
            }));
        }

        const mentionedParticipants = collaborative
            ? extractMentionedParticipants(
                  trimmed,
                  conversationParticipants(collaborationConversation),
              )
            : [];

        if (collaborative && !invocationTarget) {
            // Posted rather than streamed. The response carries the stored message, which
            // replaces the placeholder; the same message also arrives over the event stream,
            // and `mergeCollaborationMessage` recognises it by id rather than adding it
            // twice.
            try {
                const result = await postCollaborationMessage(conversationId, {
                    content: trimmed,
                    reply_to_message_id: replyTo?.message_id ?? null,
                    mentioned_participants: mentionedParticipants,
                });
                useCollaborationStore.getState().setReplyTo(null);
                if (result.conversation) {
                    useCollaborationStore.getState().setConversation(result.conversation);
                }
                set((state) => ({
                    messages: mergeCollaborationMessage(state.messages, result.message, {
                        pendingId: pendingUserMessageId,
                    }),
                }));
            } catch (error) {
                // The placeholder is removed rather than left as a message that was never
                // sent, and the text is reported so it can be retyped or the cause fixed.
                set((state) => ({
                    messages: state.messages.filter(
                        (message) => message.id !== pendingUserMessageId,
                    ),
                    streamError:
                        error instanceof Error ? error.message : 'Could not post that message.',
                }));
            }
            return;
        }

        // Derived once here rather than at each field: the chip row is the single source of
        // truth for what this message is pointed at, and the request is three views of it.
        const contextItems = options.contextItems ?? [];
        const contextDocuments = contextDocumentIds(contextItems);
        const contextTagNames = contextTags(contextItems);
        const contextWorkspaces = contextScopes(contextItems);
        const filterMode = contextFilterMode(contextItems);

        const scope = resolveDocumentScope({
            activeGroupId: bootstrap?.scope?.active_group_id,
            activePublicWorkspaceId: bootstrap?.scope?.active_public_workspace_id,
            contextGroupIds: contextWorkspaces.groupIds,
            contextPublicWorkspaceIds: contextWorkspaces.publicWorkspaceIds,
        });

        const requestBody: ChatStreamRequest = {
            message: trimmed,
            conversation_id: conversationId,
            // Deliberately always 'user'. The server derives scope_id/scope_type from this
            // (route_backend_chats.py:20692) and those feed fact-memory reads and writes,
            // so sending 'group' would move a personal conversation's extracted facts into
            // a shared group scope. The classic client's group branch is unreachable —
            // `window.activeChatTabType` is read in two places and assigned in none — so
            // 'user' is what it actually sends, and matching that is the real parity.
            chat_type: 'user',
            // Naming a document is itself a request to search: a chip the user added while
            // the toggle happened to be off would otherwise be collected, sent, and ignored.
            hybrid_search: options.documentSearch || contextDocuments.length > 0,
            web_search_enabled: options.webSearch,
            image_generation: options.imageGeneration,
            selected_document_ids: contextDocuments,
            // The scope and its workspace ids travel together: the server filters the ids
            // down to what the caller may see, so a scope without them covers nothing.
            // Document search is widened to the group this way, without re-scoping the
            // request itself.
            ...scope,
            // Deep research is carried by two fields: the server reads source_review_enabled
            // for the fetching machinery and deep_research_enabled for query planning.
            source_review_enabled: options.deepResearch,
            deep_research_enabled: options.deepResearch,
            url_access_enabled: options.urlAccess,
        };

        if (contextTagNames.length > 0) {
            requestBody.tags = contextTagNames;
        }
        // The ordinary chat path used to send nothing about the prompt, so a saved prompt used
        // outside orchestration left no record it had been involved: no metadata to draw the
        // sent message with, and nothing for the server to attribute the wording to.
        if (options.promptInfo) {
            requestBody.prompt_info = options.promptInfo;
        }
        // Only when both kinds are present. With one kind the mode has no effect, and an
        // unnecessary field in the request is one more thing to account for later.
        if (filterMode) {
            requestBody.document_filter_mode = filterMode;
        }

        // Model identity, agent and reasoning level are mutually exclusive halves of the same
        // decision, resolved in one place. An agent answers with its own deployment, and a
        // model identity sent alongside `agent_info` reads to the server as an override of it.
        Object.assign(
            requestBody,
            buildSelectionFields({
                agents: bootstrap?.catalogs?.agents as Record<string, unknown>[] | undefined,
                models: bootstrap?.catalogs?.models as ModelCatalogEntry[] | undefined,
                // An explicit `@agent` or `@model` tag chooses for this message alone and
                // overrides the pickers, which is the point of tagging one. A tagged *model*
                // additionally clears the agent selection: the exclusivity rule above lets an
                // agent win, so leaving a picked agent in place would silently discard the
                // model the reader just named.
                agentSelection: taggedModelSelection
                    ? undefined
                    : (taggedAgentSelection ?? options.agentSelection),
                modelDeployment: taggedModelSelection ?? options.modelDeployment,
                reasoningEffort: options.reasoningEffort,
            }),
        );

        if (collaborative) {
            // The collaboration stream reads the text as `content` and records who was
            // named and what was addressed alongside it, so the thread shows what was asked
            // rather than only that something was.
            requestBody.content = trimmed;
            requestBody.reply_to_message_id = replyTo?.message_id ?? null;
            requestBody.mentioned_participants = mentionedParticipants;
            requestBody.invocation_target = invocationTarget;
            // The server resolves the hidden source conversation itself; sending the shared
            // conversation's id here would point the bridge at the wrong thread.
            delete requestBody.conversation_id;
            useCollaborationStore.getState().setReplyTo(null);
        }

        await runChatStream(requestBody, conversationId, {
            isNewConversation,
            kind: collaborative ? 'collaborative' : 'personal',
            pendingUserMessageId,
            stream: collaborative
                ? {
                      url: streamCollaborationUrl(conversationId),
                      // No reattach endpoint exists for a shared conversation, so a dropped
                      // transport must be reported rather than retried against a route that
                      // does not know this conversation id.
                      allowRecovery: false,
                  }
                : undefined,
        });
    },

    stopStreaming: () => {
        if (!activeStreamController) {
            return;
        }
        // The one place a cancel belongs: the reader asked for the answer to stop being
        // written, not merely to stop being watched. Addresses the conversation the stream
        // actually belongs to, which may no longer be the one on screen, through whichever
        // cancel route that conversation uses.
        if (streamingConversationId) {
            void cancelStream(
                streamingConversationId,
                streamingConversationKind === 'collaborative'
                    ? cancelCollaborationStreamUrl(streamingConversationId)
                    : undefined,
            );
        }
        detachActiveStream();
    },

    setDrawerMode: (drawerMode) => {
        set({ drawerMode });
        // Documents are derived from conversation metadata, so opening that mode loads it
        // on demand rather than on every conversation switch.
        const { activeConversationId, metadata, metadataLoading } = get();
        if (
            drawerMode === 'documents' &&
            activeConversationId &&
            !metadata &&
            !metadataLoading
        ) {
            void get().loadMetadata(activeConversationId);
        }
    },

    beginOrchestrationTurn: (conversationId, text, addUserMessage = true, turnId) => {
        const trimmed = text.trim();
        const pendingUserMessageId = addUserMessage ? `pending-user-${Date.now()}` : '';
        // Guarded on the open conversation, exactly like sendMessage's optimistic write: a run
        // started here keeps going after the reader opens another thread, and its question must
        // not appear inside that other thread.
        if (get().activeConversationId === conversationId) {
            set((state) => ({
                messages: addUserMessage
                    ? [
                          ...state.messages,
                          {
                              id: pendingUserMessageId,
                              conversation_id: conversationId,
                              role: 'user',
                              content: trimmed,
                              timestamp: new Date().toISOString(),
                              // Stamp the turn so the plan map can scroll back to the question a
                              // run belongs to; it survives the id reconciliation on completion,
                              // which only swaps the id and keeps every other field.
                              metadata: turnId ? { orchestration_turn_id: turnId } : undefined,
                          },
                      ]
                    : state.messages,
                streaming: true,
                streamingContent: '',
                thoughts: [],
                streamError: null,
                reconnectPhase: null,
            }));
        }
        return pendingUserMessageId;
    },

    pushOrchestrationThought: (conversationId, event) => {
        if (get().activeConversationId !== conversationId) {
            return;
        }
        const content =
            typeof event.content === 'string' ? event.content : String(event.thought ?? '');
        if (!content) {
            return;
        }
        // Built exactly like buildStreamHandlers.onThought so a planner reasoning step feeds the
        // same activity lane a chat run's thoughts do — the orchestration lane keys on the
        // `orchestration_*` step types these carry.
        set((state) => ({
            thoughts: [
                ...state.thoughts,
                {
                    id: `${state.thoughts.length}`,
                    title: String(event.title ?? event.step_type ?? 'Planning'),
                    content,
                    stepType: typeof event.step_type === 'string' ? event.step_type : undefined,
                    detail: typeof event.detail === 'string' ? event.detail : undefined,
                    activity: event.activity as ThoughtEntry['activity'],
                    progress: event.progress as ThoughtEntry['progress'],
                    stepIndex:
                        typeof event.step_index === 'number' ? event.step_index : undefined,
                },
            ],
        }));
    },

    pushOrchestrationContent: (conversationId, accumulated) => {
        if (get().activeConversationId !== conversationId) {
            return;
        }
        set({ streamingContent: accumulated });
    },

    settleOrchestrationTurn: (conversationId, outcome) => {
        // The reader is elsewhere: there is no streaming surface of this conversation's to
        // resolve, and the run's own record in the orchestration store is what remembers it ran.
        if (get().activeConversationId !== conversationId) {
            return;
        }

        if (outcome.status === 'planned') {
            // Planning is over and the card takes the stage; leave the thinking state without
            // adding a message. Thoughts are cleared because the planning reasoning is ephemeral —
            // the plan is the artifact worth keeping, and stale thoughts would otherwise flash in
            // the next turn's streaming bubble.
            set({
                streaming: false,
                streamingContent: '',
                thoughts: [],
                reconnectPhase: null,
            });
            return;
        }

        if (outcome.status === 'failed') {
            set({
                streaming: false,
                streamingContent: '',
                reconnectPhase: null,
                streamError: outcome.error,
            });
            return;
        }

        if (outcome.status === 'cancelled') {
            // Partial output is kept, matching a cancelled chat stream: discarding a long answer
            // someone stopped is more annoying than useful.
            const { accumulated } = outcome;
            set((state) => ({
                messages: accumulated
                    ? [
                          ...state.messages,
                          {
                              id: `cancelled-${Date.now()}`,
                              conversation_id: conversationId,
                              role: 'assistant',
                              content: accumulated,
                              timestamp: new Date().toISOString(),
                              thoughts:
                                  state.thoughts.length > 0 ? [...state.thoughts] : undefined,
                          },
                      ]
                    : state.messages,
                streaming: false,
                streamingContent: '',
                reconnectPhase: null,
            }));
            return;
        }

        // Completed: the terminal frame is chat-shaped, so the assistant message is built exactly
        // as buildStreamHandlers.onDone builds it, and merged by id for the same reason — a shared
        // conversation echoes the same message over its event stream and the second copy must
        // update the first rather than double it.
        const { event, accumulated, pendingUserMessageId } = outcome;
        const persistedUserId = String(event.user_message_id ?? '').trim();
        const finalMessage: ChatMessage = {
            id: String(event.message_id ?? STREAMING_MESSAGE_ID),
            conversation_id: conversationId,
            role: 'assistant',
            content: accumulated,
            timestamp: new Date().toISOString(),
            model_deployment_name: event.model_deployment_name,
            agent_display_name: event.agent_display_name,
            augmented: event.augmented,
            // Carried through so an orchestrated answer shows its sources exactly as a
            // chat answer does. Dropping these left the reply citing documents in its prose
            // with no citation chips under it and nothing in the Documents drawer.
            hybrid_citations: event.hybrid_citations as ChatMessage['hybrid_citations'],
            web_search_citations:
                event.web_search_citations as ChatMessage['web_search_citations'],
            metadata: event.metadata,
            thoughts: get().thoughts.length > 0 ? [...get().thoughts] : undefined,
        };
        set((state) => {
            // Reconcile the optimistic user bubble with the server id when the run reports one, so
            // per-message actions address a message the server knows. Matched on the exact pending
            // id rather than any `pending-user-` bubble, so an earlier cancelled turn's unresolved
            // bubble is left alone.
            const messages =
                persistedUserId && pendingUserMessageId
                    ? state.messages.map((message) =>
                          message.id === pendingUserMessageId
                              ? { ...message, id: persistedUserId }
                              : message,
                      )
                    : state.messages;
            return {
                messages: mergeCollaborationMessage(
                    messages,
                    finalMessage as CollaborationMessage,
                ),
                streaming: false,
                streamingContent: '',
                reconnectPhase: null,
            };
        });

        // The Documents drawer reads the conversation's used-document list rather than the
        // message's citations, and the server only extends that list once the run finishes.
        // Without this refetch the drawer keeps reporting the state it was fetched in --
        // "No documents used yet" under an answer that plainly used one.
        if (event.augmented) {
            void get().loadMetadata(conversationId);
        }
    },

    reassignOrchestrationTurn: ({
        fromConversationId,
        toConversationId,
        fromTurnId,
        toTurnId,
    }) => {
        const conversationChanged =
            Boolean(toConversationId) && toConversationId !== fromConversationId;
        const turnChanged = Boolean(toTurnId) && toTurnId !== fromTurnId;
        if (!conversationChanged && !turnChanged) {
            return;
        }
        set((state) => {
            const messages = state.messages.map((message) => {
                if (message.conversation_id !== fromConversationId) {
                    return message;
                }
                // The turn stamp is what tells this turn's bubble apart from an earlier turn's in
                // the same thread, so the turn id is rewritten only on the bubble carrying the old
                // one. The conversation id moves with any bubble of a just-created conversation,
                // which holds nothing but this turn.
                const stamp = (
                    message.metadata as { orchestration_turn_id?: string } | undefined
                )?.orchestration_turn_id;
                const metadata =
                    turnChanged && stamp === fromTurnId
                        ? ({
                              ...(message.metadata as Record<string, unknown>),
                              orchestration_turn_id: toTurnId,
                          } as ChatMessage['metadata'])
                        : message.metadata;
                return {
                    ...message,
                    conversation_id: conversationChanged
                        ? toConversationId
                        : message.conversation_id,
                    metadata,
                };
            });
            // The optimistic write guarded on the open conversation, so a reader looking at the old
            // id is looking at this turn; keep them attached to it under the real id.
            const activeConversationId =
                conversationChanged && state.activeConversationId === fromConversationId
                    ? toConversationId
                    : state.activeConversationId;
            return { messages, activeConversationId };
        });
    },

    loadMetadata: async (conversationId) => {
        set({ metadataLoading: true, metadataError: null });
        const collaborative = isCollaborativeConversation(get(), conversationId);
        try {
            // A shared conversation has no entry in the personal metadata route, and its own
            // detail response carries everything that one does plus the membership. It is
            // mapped onto the metadata shape so the badges, classification pills, document
            // drawer and summary all keep working untouched.
            const metadata = collaborative
                ? await fetchCollaborationConversation(conversationId).then((result) => {
                      useCollaborationStore.getState().setConversation(result.conversation);
                      return metadataFromCollaboration(result.conversation);
                  })
                : await fetchConversationMetadata(conversationId);
            // Discard if the user moved on while this was in flight.
            if (get().activeConversationId !== conversationId) {
                set({ metadataLoading: false });
                return;
            }
            set((state) => ({
                metadata,
                metadataLoading: false,
                // A conversation reached by a link can be older than the first page of the
                // feed, or hidden, in which case the list has no row for it: the rail
                // highlights nothing and the header falls back to "New chat" for a thread
                // that is plainly open. Metadata is already being fetched here, so the row
                // is built from it rather than costing another request. It goes to the top
                // because the list is cursor-paged — there is no correct place to insert an
                // older conversation into a page that has not been loaded.
                conversations: state.conversations.some((item) => item.id === conversationId)
                    ? state.conversations
                    : [
                          {
                              ...conversationFromMetadata(conversationId, metadata),
                              // Carried so the row's own actions keep routing to the right
                              // API family after a reload that does not go through the feed.
                              conversation_kind: collaborative ? 'collaborative' : undefined,
                          },
                          ...state.conversations,
                      ],
            }));
        } catch (error) {
            set({
                metadataLoading: false,
                metadataError:
                    error instanceof Error ? error.message : 'Failed to load conversation details.',
            });
        }
    },

    reloadMessages: async () => {
        const conversationId = get().activeConversationId;
        if (!conversationId) {
            return;
        }
        try {
            const { messages } =
                get().activeConversationKind === 'collaborative'
                    ? await fetchCollaborationMessages(conversationId)
                    : await fetchMessages(conversationId);
            if (get().activeConversationId !== conversationId) {
                return;
            }
            set({ messages: messages ?? [] });
            // Attempt switches and deletions change which documents the conversation
            // cites, so cached metadata is no longer trustworthy.
            set({ metadata: null });
        } catch (error) {
            set({
                messagesError:
                    error instanceof Error ? error.message : 'Failed to reload messages.',
            });
        }
    },

    removeMessage: async (messageId, deleteThread = false) => {
        const previous = get().messages;
        const conversationId = get().activeConversationId;
        const collaborative = get().activeConversationKind === 'collaborative';
        set({ messages: previous.filter((message) => message.id !== messageId) });
        try {
            if (collaborative && conversationId) {
                // A shared conversation deletes one message at a time and has no thread
                // model, so `deleteThread` has nothing to address there.
                await deleteCollaborationMessage(conversationId, messageId);
            } else {
                await deleteMessageApi(messageId, deleteThread);
            }
            // Deletion is soft when archiving is enabled: the server masks the message
            // rather than removing it, so the authoritative list is re-read instead of
            // trusting the optimistic removal.
            await get().reloadMessages();
        } catch (error) {
            set({
                messages: previous,
                streamError:
                    error instanceof Error ? error.message : 'Could not delete the message.',
            });
        }
    },

    retryMessage: async (messageId, options) => {
        if (get().streaming) {
            return;
        }
        set({
            streaming: true,
            streamingContent: '',
            thoughts: [],
            streamError: null,
            reconnectPhase: null,
        });
        try {
            const bootstrap = useBootstrapStore.getState().data;
            // Same exclusive rule as a fresh send, so a retry cannot reintroduce the
            // combination the server reads as a model override of the agent. The retry
            // endpoint takes a flat deployment name, which `buildSelectionFields` has already
            // resolved from the catalog — the option value is a selection key, not a name.
            const selection = buildSelectionFields({
                agents: bootstrap?.catalogs?.agents as Record<string, unknown>[] | undefined,
                models: bootstrap?.catalogs?.models as ModelCatalogEntry[] | undefined,
                agentSelection: options?.agentSelection,
                modelDeployment: options?.modelDeployment,
                reasoningEffort: options?.reasoningEffort,
            });
            const result = await retryMessageApi(messageId, {
                model: selection.model_deployment,
                reasoning_effort: selection.reasoning_effort,
                agent_info: selection.agent_info,
            });
            if (!result?.chat_request) {
                throw new Error('The server did not return a retry request.');
            }
            // The retry endpoint only creates the next attempt; this second call is what
            // actually generates the response.
            await runChatStream(
                result.chat_request,
                result.chat_request.conversation_id,
                { reloadOnDone: true },
            );
        } catch (error) {
            set({
                streaming: false,
                streamError: error instanceof Error ? error.message : 'Retry failed.',
            });
        }
    },

    editMessage: async (messageId, content) => {
        const trimmed = content.trim();
        if (!trimmed || get().streaming) {
            return;
        }
        set({
            streaming: true,
            streamingContent: '',
            thoughts: [],
            streamError: null,
            reconnectPhase: null,
        });
        try {
            const result = await editMessageApi(messageId, trimmed);
            if (!result?.chat_request) {
                throw new Error('The server did not return an edit request.');
            }
            await runChatStream(
                result.chat_request,
                result.chat_request.conversation_id,
                { reloadOnDone: true },
            );
        } catch (error) {
            set({
                streaming: false,
                streamError: error instanceof Error ? error.message : 'Edit failed.',
            });
        }
    },

    changeAttempt: async (messageId, direction) => {
        try {
            const result = await switchAttemptApi(messageId, direction);

            // The only place the server reports the full attempt set, so it is remembered
            // against the thread rather than discarded.
            const threadId = messageThreadId(
                get().messages.find((message) => message.id === messageId),
            );
            if (threadId && Array.isArray(result?.available_attempts)) {
                set((state) => ({
                    attemptsByThread: {
                        ...state.attemptsByThread,
                        [threadId]: result.available_attempts,
                    },
                }));
            }

            // The server flips active_thread in storage and /api/get_messages filters on
            // it, so the list must be re-read rather than reordered locally.
            await get().reloadMessages();
        } catch (error) {
            set({
                streamError:
                    error instanceof Error ? error.message : 'Could not switch attempt.',
            });
        }
    },

    applyMask: async (messageId, action, selection) => {
        const conversationId = get().activeConversationId;
        if (!conversationId) {
            return;
        }

        try {
            const result =
                get().activeConversationKind === 'collaborative'
                    ? await maskCollaborationMessage(conversationId, messageId, {
                          action,
                          selection,
                      })
                    : await maskMessageApi(messageId, {
                          action,
                          conversation_id: conversationId,
                          selection,
                      });

            // The response carries the authoritative mask state, including ranges the
            // server merged or re-placed, so it replaces the local copy rather than being
            // assumed to match what was sent.
            //
            // It does NOT return the whole-message attribution fields
            // (route_backend_chats.py returns only `masked` and `masked_ranges`), so they
            // are filled in from the acting user -- who, for a mask just applied, is
            // exactly who applied it. A reload replaces them with the stored values.
            const actor = useBootstrapStore.getState().data?.user;
            const attribution =
                action === 'mask_all'
                    ? {
                          masked_by_display_name: actor?.display_name || actor?.email || undefined,
                          masked_by_user_id: actor?.id,
                          masked_timestamp: new Date().toISOString(),
                      }
                    : {
                          masked_by_display_name: undefined,
                          masked_by_user_id: undefined,
                          masked_timestamp: undefined,
                      };

            set((state) => ({
                messages: state.messages.map((message) =>
                    message.id === messageId
                        ? {
                              ...message,
                              metadata: {
                                  ...(message.metadata as Record<string, unknown>),
                                  ...attribution,
                                  masked: result.masked,
                                  masked_ranges: result.masked_ranges ?? [],
                              },
                          }
                        : message,
                ),
            }));

            toast.success(
                action === 'mask_all'
                    ? 'Message masked. It will not be sent to the model.'
                    : action === 'mask_selection'
                      ? 'Selection masked.'
                      : 'Mask removed.',
            );
        } catch (error) {
            // A selection the server cannot place in the stored content is rejected, and
            // saying so is more useful than a generic failure.
            const message =
                error instanceof ApiError && error.status === 400
                    ? 'That selection could not be matched to the stored message. Try selecting a distinct phrase.'
                    : error instanceof ApiError && error.status === 403
                      ? 'You can only mask your own messages.'
                      : error instanceof Error
                        ? error.message
                        : 'The mask could not be updated.';
            toast.error(message);
        }
    },

    /**
     * Save or clear the colours of one block, then reflect the result on the message.
     *
     * The conversation is passed in rather than read from `activeConversationId`. A pending
     * change is flushed when the block unmounts, and switching conversations is one of the ways
     * a block unmounts — by which point the active conversation is already the new one, and the
     * write would be addressed to a conversation the message is not in.
     *
     * A shared conversation has its own endpoint. Its messages are in a different Cosmos
     * container, so the personal route cannot even find the conversation to authorize the
     * write and answers 404 — which is what made recolouring a chart in a shared thread report
     * that the change could not be saved.
     *
     * The server returns the whole stored map rather than just the entry that changed, so the
     * local copy is replaced by it: a block whose entry the server dropped as stale should stop
     * showing its old colours here too.
     */
    applyVisualStyle: async (
        messageId,
        conversationId,
        conversationKind,
        blockKind,
        blockIndex,
        sourceHash,
        style,
        height,
    ) => {
        if (!conversationId) {
            return false;
        }

        // The kind recorded when the change was made is authoritative. Falling back to the
        // store only covers the case where it was not yet known, and the rail row it consults
        // may be gone by the time a flushed change is written.
        const collaborative =
            conversationKind === null
                ? isCollaborativeConversation(get(), conversationId)
                : conversationKind === 'collaborative';
        const payloadStyle = style
            ? {
                  palette: style.palette,
                  background: style.background,
                  colors: style.colors,
              }
            : null;
        // Spread rather than always sent: the server distinguishes an absent key, which keeps
        // the stored height, from an explicit null, which clears it.
        const heightFields = height === undefined ? {} : { height };

        try {
            const result = collaborative
                ? await setCollaborationMessageVisualStyle(conversationId, messageId, {
                      block_kind: blockKind,
                      block_index: blockIndex,
                      source_hash: sourceHash,
                      style: payloadStyle,
                      ...heightFields,
                  })
                : await setMessageVisualStyleApi(messageId, {
                      conversation_id: conversationId,
                      block_kind: blockKind,
                      block_index: blockIndex,
                      source_hash: sourceHash,
                      style: payloadStyle,
                      ...heightFields,
                  });

            set((state) => ({
                messages: state.messages.map((message) =>
                    message.id === messageId
                        ? {
                              ...message,
                              metadata: {
                                  ...(message.metadata as Record<string, unknown>),
                                  visual_styles: result.visual_styles ?? {},
                              },
                          }
                        : message,
                ),
            }));

            return true;
        } catch (error) {
            toast.error(
                error instanceof ApiError && error.status === 403
                    ? collaborative
                        ? 'You need write access to this shared conversation to restyle its blocks.'
                        : 'You can only restyle blocks in your own conversations.'
                    : error instanceof Error
                      ? error.message
                      : 'Those colours could not be saved.',
            );
            return false;
        }
    },

    saveBlockRevision: async ({
        messageId,
        conversationId,
        conversationKind,
        blockKind,
        blockIndex,
        sourceHash,
        source,
        originalSource,
        origin,
        note,
        expectedRevisionCount,
    }) => {
        // A shared conversation's messages live in different Cosmos containers behind
        // `/api/collaboration/*`. Sending its id to the personal route 404s as
        // "Conversation not found", so the endpoint is chosen from the conversation's kind
        // exactly as every other conversation-scoped action here does.
        const shared = isSharedBlockRevision(get(), conversationId, conversationKind);
        const body = {
            block_kind: blockKind,
            block_index: blockIndex,
            source_hash: sourceHash,
            source,
            original_source: originalSource,
            origin,
            note,
            ...(expectedRevisionCount === undefined
                ? {}
                : { expected_revision_count: expectedRevisionCount }),
        };

        try {
            const result = shared
                ? await addCollaborationBlockRevision(conversationId, messageId, body)
                : await addMessageBlockRevisionApi(messageId, {
                      conversation_id: conversationId,
                      ...body,
                  });
            get().mergeBlockRevisions(messageId, result.block_revisions);
            return null;
        } catch (error) {
            return describeBlockRevisionError(error, 'That change could not be saved.');
        }
    },

    restoreBlockRevision: async ({
        messageId,
        conversationId,
        conversationKind,
        blockKind,
        blockIndex,
        sourceHash,
        revisionId,
    }) => {
        const shared = isSharedBlockRevision(get(), conversationId, conversationKind);
        const body = {
            block_kind: blockKind,
            block_index: blockIndex,
            source_hash: sourceHash,
            revision_id: revisionId,
        };

        try {
            const result = shared
                ? await setCollaborationBlockRevision(conversationId, messageId, body)
                : await setMessageBlockRevisionApi(messageId, {
                      conversation_id: conversationId,
                      ...body,
                  });
            get().mergeBlockRevisions(messageId, result.block_revisions);
            return null;
        } catch (error) {
            return describeBlockRevisionError(error, 'That version could not be restored.');
        }
    },

    askBlockRevision: async ({
        messageId,
        conversationId,
        conversationKind,
        blockKind,
        blockIndex,
        sourceHash,
        instruction,
        originalSource,
        expectedRevisionCount,
    }) => {
        const shared = isSharedBlockRevision(get(), conversationId, conversationKind);
        const body = {
            block_kind: blockKind,
            block_index: blockIndex,
            source_hash: sourceHash,
            instruction,
            original_source: originalSource,
            ...(expectedRevisionCount === undefined
                ? {}
                : { expected_revision_count: expectedRevisionCount }),
        };

        try {
            const result = shared
                ? await assistCollaborationBlockRevision(conversationId, messageId, body)
                : await assistMessageBlockRevisionApi(messageId, {
                      conversation_id: conversationId,
                      ...body,
                  });
            get().mergeBlockRevisions(messageId, result.block_revisions);
            return null;
        } catch (error) {
            return describeBlockRevisionError(error, 'The diagram could not be updated.');
        }
    },

    mergeBlockRevisions: (messageId, blockRevisions) => {
        set((state) => ({
            messages: state.messages.map((message) =>
                message.id === messageId
                    ? {
                          ...message,
                          metadata: {
                              ...(message.metadata as Record<string, unknown>),
                              block_revisions: blockRevisions ?? {},
                          },
                      }
                    : message,
            ),
        }));
    },

    mergeImageRevisions: (messageId, entry, imageUrl) => {
        set((state) => ({
            messages: state.messages.map((message) =>
                message.id === messageId
                    ? {
                          ...message,
                          // The URL carries the revision, so replacing it is what actually makes
                          // the new image appear: the old one is still in the browser's cache
                          // under the URL it was fetched with.
                          content: imageUrl || message.content,
                          metadata: {
                              ...(message.metadata as Record<string, unknown>),
                              image_revisions: entry ?? {},
                          },
                      }
                    : message,
            ),
        }));
    },

    reviseImage: async ({
        messageId,
        conversationId,
        conversationKind,
        origin,
        instruction,
        prompt,
        mask,
        maskRegions,
        size,
        quality,
        background,
        expectedRevisionCount,
        expectedCurrentRevisionId,
    }) => {
        // A shared conversation's messages live in different Cosmos containers behind
        // `/api/collaboration/*`, so the endpoint is chosen from the conversation's kind rather
        // than tried and fallen back from, exactly as the diagram actions do.
        const shared = isSharedBlockRevision(get(), conversationId, conversationKind);
        const body = {
            conversation_id: conversationId,
            ...(origin ? { origin } : {}),
            ...(instruction ? { instruction } : {}),
            ...(prompt ? { prompt } : {}),
            ...(mask ? { mask } : {}),
            ...(maskRegions ? { mask_regions: maskRegions } : {}),
            ...(size ? { size } : {}),
            ...(quality ? { quality } : {}),
            ...(background ? { background } : {}),
            ...(expectedRevisionCount === undefined
                ? {}
                : { expected_revision_count: expectedRevisionCount }),
            ...(expectedCurrentRevisionId
                ? { expected_current_revision_id: expectedCurrentRevisionId }
                : {}),
        };

        try {
            const result = shared
                ? await addCollaborationImageRevision(conversationId, messageId, body)
                : await addMessageImageRevisionApi(messageId, body);
            get().mergeImageRevisions(messageId, result.image_revisions, result.image_url);
            return null;
        } catch (error) {
            return describeImageRevisionError(error, 'That image could not be changed.');
        }
    },

    restoreImageRevision: async ({
        messageId,
        conversationId,
        conversationKind,
        revisionId,
    }) => {
        const shared = isSharedBlockRevision(get(), conversationId, conversationKind);
        const body = { conversation_id: conversationId, revision_id: revisionId };

        try {
            const result = shared
                ? await setCollaborationImageRevision(conversationId, messageId, body)
                : await setMessageImageRevisionApi(messageId, body);
            get().mergeImageRevisions(messageId, result.image_revisions, result.image_url);
            return null;
        } catch (error) {
            return describeImageRevisionError(error, 'That version could not be restored.');
        }
    },

    forkFromMessage: async (messageId) => {
        const conversationId = get().activeConversationId;
        if (!conversationId) {
            return;
        }

        try {
            const result = await forkConversationApi(conversationId, messageId);
            const forkedId = result?.conversation_id;
            if (!forkedId) {
                throw new Error('The server did not return the forked conversation.');
            }
            // Refresh the rail first so the new conversation exists in it before it is
            // selected, otherwise the header has no title to show.
            await get().loadConversations({ reset: true });
            await get().selectConversation(forkedId);
        } catch (error) {
            set({
                streamError:
                    error instanceof Error ? error.message : 'Could not fork the conversation.',
            });
        }
    },

    sendFeedback: async (messageId, feedbackType, reason = '') => {
        const conversationId = get().activeConversationId;
        if (!conversationId) {
            return;
        }
        // Recorded locally first so the control reflects the choice immediately; feedback
        // is advisory and a failure should not disrupt the conversation.
        set((state) => ({
            messages: state.messages.map((message) =>
                message.id === messageId ? { ...message, feedbackType } : message,
            ),
        }));
        try {
            await submitFeedbackApi(messageId, conversationId, feedbackType, reason);
        } catch {
            set((state) => ({
                messages: state.messages.map((message) =>
                    message.id === messageId ? { ...message, feedbackType: undefined } : message,
                ),
            }));
        }
    },

    approveImageProposal: async (conversationId, assistantMessageId, proposal) => {
        if (!conversationId) {
            throw new Error('Open a conversation before generating the image.');
        }

        const result = await generateImageFromProposal({
            conversation_id: conversationId,
            assistant_message_id: assistantMessageId,
            proposal: { ...proposal },
        });

        const imageMessage = result?.image_message;
        if (!imageMessage?.id || !imageMessage.content) {
            throw new Error('The server did not return the generated image.');
        }

        // Approval is slow, so the thread may have been switched or reloaded underneath it.
        // Dropping the message into a conversation it does not belong to would show someone
        // else's image, so it is discarded instead — it is stored server-side either way and
        // appears the next time this conversation is opened.
        if (get().activeConversationId !== conversationId) {
            return;
        }

        // Appended to the thread rather than held beside it. MessageList folds any image
        // carrying a source assistant message id into that message's proposal card, so this
        // one path serves both a fresh approval and a reloaded conversation, and there is no
        // second copy of the result to keep in step.
        set((state) => {
            if (state.messages.some((message) => message.id === imageMessage.id)) {
                return {};
            }
            return {
                messages: [
                    ...state.messages,
                    { ...imageMessage, conversation_id: conversationId } as ChatMessage,
                ],
            };
        });

        if (!proposalSourceMessageId(imageMessage)) {
            // Without the metadata the image cannot be placed under its card, so it lands in
            // the thread as an ordinary image. Re-reading gives the server the last word on
            // where it belongs.
            void get().reloadMessages();
        }
    },
}));
