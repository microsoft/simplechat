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
    markConversationRead,
    renameConversation as renameConversationApi,
    retryMessage as retryMessageApi,
    submitFeedback as submitFeedbackApi,
    switchAttempt as switchAttemptApi,
    toggleConversationHidden,
    toggleConversationPinned,
} from '../lib/endpoints';
import { cancelStream, streamChat } from '../lib/sse';
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

export interface ComposerOptions {
    modelDeployment?: string;
    modelEndpointId?: string;
    agentSelection?: string;
    promptId?: string;
    reasoningEffort?: string;
    documentSearch: boolean;
    webSearch: boolean;
    imageGeneration: boolean;
    selectedDocumentIds: string[];
    docScope: string;
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

    /** Right-hand drawer state. Null means closed. */
    drawerMode: DrawerMode;
    metadata: ConversationMetadata | null;
    metadataLoading: boolean;
    metadataError: string | null;

    loadConversations: (options?: { reset?: boolean; search?: string }) => Promise<void>;
    loadMore: () => Promise<void>;
    setSearchTerm: (term: string) => void;

    selectConversation: (conversationId: string | null) => Promise<void>;
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
    sendFeedback: (
        messageId: string,
        feedbackType: 'positive' | 'negative',
        reason?: string,
    ) => Promise<void>;
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
        {
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
                set({ streaming: false, streamingContent: '' });
            },
            onError: (message) => {
                if (!isCurrent()) {
                    return;
                }
                set({ streaming: false, streamingContent: '', streamError: message });
            },
        },
        controller.signal,
    );

    // Only tear down if this stream is still the active one; a newer send may already have
    // installed its own controller. Captured before the teardown because clearing the
    // controller makes isCurrent() false for every check after it.
    const wasCurrent = isCurrent();
    if (wasCurrent) {
        activeStreamController = null;
        streamingConversationId = null;
        set({ streaming: false });
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

    drawerMode: null,
    metadata: null,
    metadataLoading: false,
    metadataError: null,

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
            // Metadata belongs to the previous conversation; drop it so the drawer never
            // shows another thread's documents.
            metadata: null,
            metadataError: null,
        });

        if (!conversationId) {
            return;
        }

        set({ messagesLoading: true });
        try {
            const { messages } = await fetchMessages(conversationId);
            set({ messages: messages ?? [], messagesLoading: false });

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
        }));

        const requestBody: ChatStreamRequest = {
            message: trimmed,
            conversation_id: conversationId,
            chat_type: 'user',
            hybrid_search: options.documentSearch,
            web_search_enabled: options.webSearch,
            image_generation: options.imageGeneration,
            doc_scope: options.docScope,
            selected_document_ids: options.selectedDocumentIds,
        };

        if (options.modelDeployment) {
            requestBody.model_deployment = options.modelDeployment;
        }
        if (options.modelEndpointId) {
            requestBody.model_endpoint_id = options.modelEndpointId;
        }
        if (options.agentSelection) {
            requestBody.agent_selection = options.agentSelection;
        }
        if (options.reasoningEffort) {
            requestBody.reasoning_effort = options.reasoningEffort;
        }

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
        set({ streaming: false, streamingContent: '' });
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
            set({ metadata, metadataLoading: false });
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
        set({ streaming: true, streamingContent: '', thoughts: [], streamError: null });
        try {
            const result = await retryMessageApi(messageId, {
                model: options?.modelDeployment,
                reasoning_effort: options?.reasoningEffort,
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
        set({ streaming: true, streamingContent: '', thoughts: [], streamError: null });
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
            await switchAttemptApi(messageId, direction);
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
}));
