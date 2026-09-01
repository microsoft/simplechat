// chatStore.ts
// Conversation list, message thread and live streaming state for the chat page.

import { create } from 'zustand';
import {
    createConversation,
    deleteConversation as deleteConversationApi,
    fetchConversationFeed,
    fetchMessages,
    markConversationRead,
    renameConversation as renameConversationApi,
    setConversationHidden,
    setConversationPinned,
} from '../lib/endpoints';
import { cancelStream, streamChat } from '../lib/sse';
import type {
    ChatMessage,
    ChatStreamRequest,
    Conversation,
    ThoughtEntry,
} from '../lib/types';

const FEED_PAGE_SIZE = 30;

/** Identifier for the optimistic assistant message shown while a stream is running. */
const STREAMING_MESSAGE_ID = '__streaming__';

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
        });

        if (!conversationId) {
            return;
        }

        set({ messagesLoading: true });
        try {
            const { messages } = await fetchMessages(conversationId);
            set({ messages: messages ?? [], messagesLoading: false });
            void markConversationRead(conversationId).catch(() => {
                /* Read receipts are advisory. */
            });
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
        const pinned = !conversation.pinned;
        set({
            conversations: get().conversations.map((item) =>
                item.id === conversationId ? { ...item, pinned } : item,
            ),
        });
        try {
            await setConversationPinned(conversationId, pinned);
            // Pinning changes ordering, so the feed is re-read rather than re-sorted here.
            await get().loadConversations({ reset: true });
        } catch {
            set({
                conversations: get().conversations.map((item) =>
                    item.id === conversationId ? { ...item, pinned: !pinned } : item,
                ),
            });
        }
    },

    toggleHidden: async (conversationId) => {
        const conversation = get().conversations.find((item) => item.id === conversationId);
        if (!conversation) {
            return;
        }
        const hidden = !conversation.hidden;
        set({
            conversations: get().conversations.filter((item) => item.id !== conversationId),
        });
        try {
            await setConversationHidden(conversationId, hidden);
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

        const controller = new AbortController();
        activeStreamController = controller;
        streamingConversationId = conversationId;

        // A stream is "current" only while it is still the active one. If the user
        // switches threads or starts a new chat mid-response, this goes false and the
        // remaining handlers stop writing into what is now a different conversation's
        // message list.
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
                    // Applied even when superseded: the title belongs to a conversation in
                    // the rail, not to the message list on screen.
                    const title = event.conversation_title;
                    if (typeof title === 'string' && title && conversationId) {
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
                        conversation_id: conversationId as string,
                        role: 'assistant',
                        content: accumulated,
                        timestamp: new Date().toISOString(),
                        model_deployment_name: event.model_deployment_name,
                        agent_display_name: event.agent_display_name,
                        augmented: event.augmented,
                        metadata: event.metadata,
                        // Carried onto the finished message so the reasoning steps stay
                        // available after the stream ends instead of disappearing with
                        // the streaming placeholder.
                        thoughts: get().thoughts.length > 0 ? [...get().thoughts] : undefined,
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
                    // Partial output is kept: discarding what was already generated is
                    // more annoying than useful when someone stops a long answer.
                    if (accumulated) {
                        set((state) => ({
                            messages: [
                                ...state.messages,
                                {
                                    id: `cancelled-${Date.now()}`,
                                    conversation_id: conversationId as string,
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

        // Only tear down if this stream is still the active one; a newer send may already
        // have installed its own controller.
        if (isCurrent()) {
            activeStreamController = null;
            streamingConversationId = null;
            set({ streaming: false });
        }

        // Refresh the rail so a newly created conversation appears with its server-side
        // generated title.
        if (isNewConversation) {
            await get().loadConversations({ reset: true });
        }
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
}));
