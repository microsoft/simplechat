// chatStore.ts
// Conversation list, message thread and live streaming state for the chat page.

import { create } from 'zustand';
import {
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
    setMessageVisualStyle as setMessageVisualStyleApi,
    submitFeedback as submitFeedbackApi,
    switchAttempt as switchAttemptApi,
    toggleConversationHidden,
    toggleConversationPinned,
} from '../lib/endpoints';
import {
    cancelStream,
    fetchStreamStatus,
    reattachChatStream,
    streamChat,
    type ChatStreamHandlers,
} from '../lib/sse';
import { buildSelectionFields } from '../lib/chatRequestSelection';
import type { ModelCatalogEntry } from '../lib/models';
import { resolveDocumentScope } from '../lib/documentScope';
import { messageThreadId } from '../lib/threads';
import { proposalSourceMessageId, type ImageProposalSpec } from '../lib/imageProposalSpec';
import { toast } from './toastStore';
import { ApiError } from '../lib/apiClient';
import { useBootstrapStore } from './bootstrapStore';
import type { MaskAction, MaskSelection } from '../lib/masking';
import type { VisualStyle } from '../lib/visualPalettes';
import type {
    ChatMessage,
    ChatStreamRequest,
    Conversation,
    ConversationMetadata,
    ThoughtEntry,
} from '../lib/types';
import { fetchConversationMetadata } from '../lib/endpoints';

const FEED_PAGE_SIZE = 30;

/** Identifier for the optimistic assistant message shown while a stream is running. */
const STREAMING_MESSAGE_ID = '__streaming__';

/** Which mode the right-hand drawer is showing, or null when it is closed. */
export type DrawerMode = 'contents' | 'documents' | null;

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

    activeConversationId: string | null;
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

    selectConversation: (conversationId: string | null) => Promise<void>;
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
        blockKind: string,
        blockIndex: number,
        sourceHash: string,
        style: VisualStyle | null,
    ) => Promise<boolean>;
    sendFeedback: (
        messageId: string,
        feedbackType: 'positive' | 'negative',
        reason?: string,
    ) => Promise<void>;
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
): ChatStreamHandlers {
    return {
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
                messages: [...state.messages, finalMessage],
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
    options: { isNewConversation?: boolean; reloadOnDone?: boolean } = {},
): Promise<void> {
    const { set, getState } = {
        set: (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) =>
            useChatStore.setState(partial as never),
        getState: () => useChatStore.getState(),
    };

    const controller = new AbortController();
    activeStreamController = controller;
    streamingConversationId = conversationId;

    // A stream is "current" only while it is still the active one. If the user switches
    // threads or starts a new chat mid-response, this goes false and the remaining
    // handlers stop writing into what is now a different conversation's message list.
    const isCurrent = () => activeStreamController === controller;

    await streamChat(
        requestBody,
        buildStreamHandlers(conversationId, isCurrent, set, getState),
        controller.signal,
    );

    // Only tear down if this stream is still the active one; a newer send may already have
    // installed its own controller. Captured before the teardown because clearing the
    // controller makes isCurrent() false for every check after it.
    const wasCurrent = isCurrent();
    if (wasCurrent) {
        activeStreamController = null;
        streamingConversationId = null;
        set({ streaming: false, reconnectPhase: null });
    }

    // Retry and edit rewrite thread state server-side, so the authoritative message list
    // has to be re-read rather than patched locally.
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
    // started, and stopStreaming uses it to POST /api/chat/stream/cancel, which is a real
    // server-side cancellation. This stream belongs to whoever started it — possibly
    // another tab, or this page before a reload — so leaving the conversation must detach
    // locally without killing the generation. The classic client does the same: a thread
    // switch only aborts its own reader, and cancel is reached solely from the Stop button.
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

export const useChatStore = create<ChatState>((set, get) => ({
    conversations: [],
    conversationsLoading: false,
    conversationsError: null,
    hasMore: false,
    nextCursor: null,
    searchTerm: '',

    activeConversationId: null,
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

    selectConversation: async (conversationId) => {
        // Any stream still running belongs to the thread being left. Without this its
        // handlers would append the finished response into the newly selected
        // conversation's message list.
        get().stopStreaming();

        set({
            activeConversationId: conversationId,
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

        if (!conversationId) {
            return;
        }

        set({ messagesLoading: true });
        try {
            const { messages } = await fetchMessages(conversationId);
            set({ messages: messages ?? [], messagesLoading: false });

            // The header badges describe what this conversation is bound to, so its
            // metadata is needed as soon as it opens rather than only when a drawer is
            // expanded. Advisory: a failure leaves the badges off, not the thread broken.
            void get().loadMetadata(conversationId);

            // Generation outlives the connection that started it, so a thread opened while
            // its answer is still being written picks the stream back up instead of showing
            // a message that stops mid-sentence.
            void resumeChatStream(conversationId).catch(() => {
                /* Advisory: the thread is readable whether or not a resume was possible. */
            });

            // Only clear the marker when there is one. Calling unconditionally produced a
            // 404 for collaboration conversations, which are stored separately and have
            // their own endpoint.
            const conversation = get().conversations.find((item) => item.id === conversationId);
            if (conversation?.has_unread_assistant_response) {
                void markConversationRead(
                    conversationId,
                    conversation.conversation_kind === 'collaborative',
                )
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
     * Existence is checked against the metadata endpoint rather than inferred from the
     * message load, because `/api/get_messages` is not an existence check: it turns a
     * not-found conversation into `{'messages': []}` with a 200
     * (`route_backend_conversations.py`), so a deleted conversation would open as an empty
     * chat, keep its id in the address bar, and remain the target of the next message sent.
     * The metadata endpoint answers 404 when the conversation is gone and 403 when it is
     * someone else's, which is the question actually being asked. It costs one request on
     * a path that runs once per page load.
     */
    openLinkedConversation: async (conversationId) => {
        try {
            await fetchConversationMetadata(conversationId);
        } catch {
            toast.error(
                'Could not open that conversation. It may have been deleted, or you may not have access to it.',
            );
            return;
        }

        await get().selectConversation(conversationId);

        // Still checked: the conversation exists, but its messages may not have loaded.
        if (get().messagesError) {
            toast.error(
                'Could not open that conversation. It may have been deleted, or you may not have access to it.',
            );
            get().startNewConversation();
        }
    },

    startNewConversation: () => {
        // Stop first: the running stream belongs to the previous thread and must not
        // deliver its response into the empty new one.
        get().stopStreaming();

        // The conversation row is created by the server on first send, so a new chat is
        // purely a local reset until then. This avoids leaving empty conversations behind
        // when someone clicks New Chat and navigates away.
        set({
            activeConversationId: null,
            messages: [],
            messagesError: null,
            streamingContent: '',
            thoughts: [],
            streamError: null,
            reconnectPhase: null,
            metadata: null,
            metadataError: null,
        });
    },

    renameConversation: async (conversationId, title) => {
        const previous = get().conversations;
        set({
            conversations: previous.map((conversation) =>
                conversation.id === conversationId ? { ...conversation, title } : conversation,
            ),
        });
        try {
            await renameConversationApi(conversationId, title);
        } catch {
            set({ conversations: previous });
        }
    },

    removeConversation: async (conversationId) => {
        const previous = get().conversations;
        set({
            conversations: previous.filter((conversation) => conversation.id !== conversationId),
        });

        if (get().activeConversationId === conversationId) {
            get().startNewConversation();
        }

        try {
            await deleteConversationApi(conversationId);
        } catch {
            set({ conversations: previous });
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
            const result = await toggleConversationPinned(conversationId);
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
        });
        try {
            await toggleConversationHidden(conversationId);
        } catch {
            await get().loadConversations({ reset: true });
        }
    },

    sendMessage: async (text, options) => {
        const trimmed = text.trim();
        if (!trimmed || get().streaming) {
            return;
        }

        let conversationId = get().activeConversationId;
        const isNewConversation = !conversationId;

        // A conversation is created up front so the streaming endpoint has a stable id to
        // attach to and so a cancel request has something to address.
        if (!conversationId) {
            try {
                const created = await createConversation(trimmed);
                conversationId = created.conversation_id;
                set({ activeConversationId: conversationId });
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

        const optimisticUserMessage: ChatMessage = {
            id: `pending-user-${Date.now()}`,
            conversation_id: conversationId,
            role: 'user',
            content: trimmed,
            timestamp: new Date().toISOString(),
        };

        set((state) => ({
            messages: [...state.messages, optimisticUserMessage],
            streaming: true,
            streamingContent: '',
            thoughts: [],
            streamError: null,
            reconnectPhase: null,
        }));

        const bootstrap = useBootstrapStore.getState().data;
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
                agentSelection: options.agentSelection,
                modelDeployment: options.modelDeployment,
                reasoningEffort: options.reasoningEffort,
            }),
        );

        await runChatStream(requestBody, conversationId, { isNewConversation });
    },


    stopStreaming: () => {
        if (!activeStreamController) {
            return;
        }
        // Addresses the conversation the stream actually belongs to, which may no longer
        // be the one on screen.
        if (streamingConversationId) {
            void cancelStream(streamingConversationId);
        }
        activeStreamController.abort();
        activeStreamController = null;
        streamingConversationId = null;
        set({ streaming: false, streamingContent: '', reconnectPhase: null });
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
        try {
            const metadata = await fetchConversationMetadata(conversationId);
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
                    : [conversationFromMetadata(conversationId, metadata), ...state.conversations],
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
            const { messages } = await fetchMessages(conversationId);
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
        set({ messages: previous.filter((message) => message.id !== messageId) });
        try {
            await deleteMessageApi(messageId, deleteThread);
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
            const result = await maskMessageApi(messageId, {
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
     * The server returns the whole stored map rather than just the entry that changed, so the
     * local copy is replaced by it: a block whose entry the server dropped as stale should stop
     * showing its old colours here too.
     */
    applyVisualStyle: async (
        messageId,
        conversationId,
        blockKind,
        blockIndex,
        sourceHash,
        style,
    ) => {
        if (!conversationId) {
            return false;
        }

        try {
            const result = await setMessageVisualStyleApi(messageId, {
                conversation_id: conversationId,
                block_kind: blockKind,
                block_index: blockIndex,
                source_hash: sourceHash,
                style: style
                    ? {
                          palette: style.palette,
                          background: style.background,
                          colors: style.colors,
                      }
                    : null,
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
                    ? 'You can only restyle blocks in your own conversations.'
                    : error instanceof Error
                      ? error.message
                      : 'Those colours could not be saved.',
            );
            return false;
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
