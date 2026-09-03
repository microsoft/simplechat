// chatStore.ts
// Conversation list, message thread and live streaming state for the chat page.

import { create } from 'zustand';
import {
    addMessageBlockRevision as addMessageBlockRevisionApi,
    assistMessageBlockRevision as assistMessageBlockRevisionApi,
    createConversation,
    deleteConversation as deleteConversationApi,
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
    setMessageVisualStyle as setMessageVisualStyleApi,
    submitFeedback as submitFeedbackApi,
    switchAttempt as switchAttemptApi,
    toggleConversationHidden,
    toggleConversationPinned,
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
import type { ModelCatalogEntry } from '../lib/models';
import { resolveDocumentScope } from '../lib/documentScope';
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
    ThoughtEntry,
} from '../lib/types';
import { isCollaborative } from '../lib/types';
import { fetchConversationKind, fetchConversationMetadata } from '../lib/endpoints';
import type { ConversationKind } from '../lib/endpoints';

const FEED_PAGE_SIZE = 30;

/** Identifier for the optimistic assistant message shown while a stream is running. */
const STREAMING_MESSAGE_ID = '__streaming__';

/** Which mode the right-hand drawer is showing, or null when it is closed. */
export type DrawerMode = 'contents' | 'documents' | null;

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
    reasoningEffort?: string;
    documentSearch: boolean;
    webSearch: boolean;
    imageGeneration: boolean;
    /** Deep research sets both source_review_enabled and deep_research_enabled. */
    deepResearch: boolean;
    urlAccess: boolean;
    selectedDocumentIds: string[];
}

interface ChatState {
    conversations: Conversation[];
    conversationsLoading: boolean;
    conversationsError: string | null;
    hasMore: boolean;
    nextCursor: string | null;
    searchTerm: string;

    /**
     * Whether the rail is picking conversations rather than opening them.
     *
     * Selection lives here rather than in the rail because deleting or hiding a conversation
     * is a store action, and a selection kept beside the list would go stale the moment one
     * of those removed a row — exporting an id the user can no longer see.
     */
    selectionMode: boolean;
    selectedConversationIds: string[];

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
    removeConversation: (conversationId: string) => Promise<void>;
    togglePinned: (conversationId: string) => Promise<void>;
    toggleHidden: (conversationId: string) => Promise<void>;

    setSelectionMode: (enabled: boolean) => void;
    toggleConversationSelected: (conversationId: string) => void;
    selectAllConversations: () => void;
    clearConversationSelection: () => void;

    sendMessage: (text: string, options: ComposerOptions) => Promise<void>;
    stopStreaming: () => void;

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
                        title: String(event.title ?? 'Thinking'),
                        content,
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
            void collaboration().loadConversation(conversationId);
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
    });
    if (store.activeConversationId === conversationId) {
        store.startNewConversation();
    }
}

export const useChatStore = create<ChatState>((set, get) => ({
    conversations: [],
    conversationsLoading: false,
    conversationsError: null,
    hasMore: false,
    nextCursor: null,
    searchTerm: '',

    selectionMode: false,
    selectedConversationIds: [],

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

            set((state) => ({
                conversations: reset
                    ? page.conversations
                    : [...state.conversations, ...page.conversations],
                hasMore: Boolean(page.has_more),
                nextCursor: page.next_cursor,
                conversationsLoading: false,
            }));
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
                if (prefetched?.id === conversationId) {
                    useCollaborationStore.getState().setConversation(prefetched);
                } else {
                    void useCollaborationStore.getState().loadConversation(conversationId);
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
    removeConversation: async (conversationId) => {
        const previous = get().conversations;
        const listed = previous.find((conversation) => conversation.id === conversationId);
        const collaborative = isCollaborativeConversation(get(), conversationId);

        set({
            conversations: previous.filter((conversation) => conversation.id !== conversationId),
            selectedConversationIds: get().selectedConversationIds.filter(
                (id) => id !== conversationId,
            ),
        });

        if (get().activeConversationId === conversationId) {
            get().startNewConversation();
        }

        try {
            if (collaborative) {
                const detail =
                    useCollaborationStore.getState().conversation?.id === conversationId
                        ? useCollaborationStore.getState().conversation
                        : (listed as CollaborationConversation | undefined);
                const action = detail?.can_delete_conversation ? 'delete' : 'leave';
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

    setSelectionMode: (enabled) => {
        // Leaving selection mode discards the selection: the checkboxes are gone, so a
        // selection that survived would act on rows the user can no longer see or change.
        set({ selectionMode: enabled, selectedConversationIds: enabled ? get().selectedConversationIds : [] });
    },

    toggleConversationSelected: (conversationId) => {
        const selected = get().selectedConversationIds;
        set({
            selectedConversationIds: selected.includes(conversationId)
                ? selected.filter((id) => id !== conversationId)
                : [...selected, conversationId],
        });
    },

    /** Selects the rows currently loaded, which is what the user can actually see. */
    selectAllConversations: () => {
        set({ selectedConversationIds: get().conversations.map((item) => item.id) });
    },

    clearConversationSelection: () => {
        set({ selectedConversationIds: [] });
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

        const scope = resolveDocumentScope({
            activeGroupId: bootstrap?.scope?.active_group_id,
            activePublicWorkspaceId: bootstrap?.scope?.active_public_workspace_id,
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
            hybrid_search: options.documentSearch,
            web_search_enabled: options.webSearch,
            image_generation: options.imageGeneration,
            selected_document_ids: options.selectedDocumentIds,
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
