// ChatPage.tsx
// Chat surface: header, message thread, composer, and the right-hand drawer.

import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { clsx } from 'clsx';
import { Files, Info, ListOrdered, Maximize2, Minimize2 } from 'lucide-react';
import { useChatStore } from '../stores/chatStore';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { useUiStore } from '../stores/uiStore';
import { readConversationParam, syncedConversationParams } from '../lib/conversationUrl';
import { MessageList } from '../components/chat/MessageList';
import { Composer } from '../components/chat/Composer';
import { ConversationDrawer } from '../components/chat/ConversationDrawer';
import { ConversationDetails } from '../components/chat/ConversationDetails';
import { ConversationBadges } from '../components/chat/ConversationBadges';

/**
 * Keep the address bar and the open conversation describing each other.
 *
 * The two directions are not symmetrical, and that asymmetry is the whole design. The URL
 * is read exactly once, when the page first renders, and written on every change of the
 * open conversation after that. Reading continuously would fight the writing.
 *
 * The incoming id is captured in a lazy `useState` initialiser rather than inside an effect
 * because effect order would otherwise decide the outcome: the effect that writes the URL
 * also runs on mount, and with nothing open yet it would strip the parameter before the
 * effect that reads it ever ran. A lazy initialiser runs during the first render, before
 * any effect, so the link cannot be lost that way.
 */
function useConversationUrlSync() {
    const [searchParams, setSearchParams] = useSearchParams();
    const activeConversationId = useChatStore((state) => state.activeConversationId);
    const openLinkedConversation = useChatStore((state) => state.openLinkedConversation);

    const [linkedConversationId] = useState(() => readConversationParam(searchParams));
    // Two flags with two jobs. The ref makes opening the link happen exactly once: React's
    // StrictMode runs effects twice on mount, and a state flag is still false in the second
    // invocation's closure, so it would open the conversation — and refetch its messages —
    // twice. The state flag is what the write effect waits on, and has to be state because
    // that effect must re-run once the link has been dealt with.
    const linkConsumed = useRef(false);
    const [linkHandled, setLinkHandled] = useState(!linkedConversationId);

    useEffect(() => {
        if (linkConsumed.current || !linkedConversationId) {
            return;
        }
        linkConsumed.current = true;

        // Read from the store rather than the subscribed value: leaving the chat page and
        // coming back re-runs this with a conversation already open, and re-opening it
        // would throw away a running stream for no reason.
        if (linkedConversationId === useChatStore.getState().activeConversationId) {
            setLinkHandled(true);
            return;
        }

        // Released only once the open has settled, either way. Releasing it up front would
        // let the write effect run during the moment before the conversation is open, see
        // nothing open, and strip the very parameter that named it.
        void openLinkedConversation(linkedConversationId).finally(() => setLinkHandled(true));
    }, [linkedConversationId, openLinkedConversation]);

    useEffect(() => {
        // Held back until the link has been consumed, so the parameter survives long enough
        // to be read.
        if (!linkHandled) {
            return;
        }

        const next = syncedConversationParams(searchParams, activeConversationId);
        if (!next) {
            return;
        }

        // `replace` rather than a new entry, matching the classic interface's
        // `history.replaceState`: the address bar should describe what is open, not turn the
        // back button into a list of every conversation visited.
        setSearchParams(next, { replace: true });
    }, [activeConversationId, linkHandled, searchParams, setSearchParams]);
}

function ChatHeader({ onOpenDetails }: { onOpenDetails: () => void }) {
    const { activeConversationId, conversations, drawerMode, setDrawerMode, metadata } =
        useChatStore();
    const contentsEnabled = useBootstrapStore((state) =>
        Boolean(state.data?.features?.enable_conversation_contents_drawer),
    );
    const chatWidth = useUiStore((state) => state.chatWidth);
    const toggleChatWidth = useUiStore((state) => state.toggleChatWidth);

    const active = conversations.find(
        (conversation) => conversation.id === activeConversationId,
    );

    // Counted from loaded metadata so the badge stays honest: it shows nothing rather
    // than a guess until the real document list has arrived.
    const documentCount = metadata
        ? new Set(
              [
                  ...(metadata.used_documents ?? []),
                  ...(metadata.legacy_used_documents ?? []),
                  ...(metadata.linked_workspace_documents ?? []),
              ]
                  .map((document) => String(document?.document_id ?? '').trim())
                  .filter(Boolean),
          ).size
        : null;

    const toggle = (mode: 'contents' | 'documents') =>
        setDrawerMode(drawerMode === mode ? null : mode);

    return (
        <header className="glass glass-edge flex h-14 shrink-0 items-center gap-3 rounded-none border-t-0 border-r-0 px-5">
            <h1 className="truncate text-[15px] font-semibold text-text-1">
                {active?.title || 'New chat'}
            </h1>
            {/* Derived from this conversation's own metadata. Reading the user's active
                group here instead made every conversation show the same badge. */}
            <ConversationBadges metadata={metadata} />

            {activeConversationId && (
                <div className="ml-auto flex items-center gap-1">
                    <button
                        type="button"
                        onClick={toggleChatWidth}
                        aria-pressed={chatWidth === 'wide'}
                        title={
                            chatWidth === 'wide'
                                ? 'Use a narrower reading width'
                                : 'Use the full width of the pane'
                        }
                        aria-label="Toggle chat width"
                        className={clsx(
                            'rounded-lg p-2 transition-colors',
                            chatWidth === 'wide'
                                ? 'bg-accent-soft text-accent'
                                : 'text-text-3 hover:bg-surface-2 hover:text-text-1',
                        )}
                    >
                        {chatWidth === 'wide' ? (
                            <Minimize2 size={17} />
                        ) : (
                            <Maximize2 size={17} />
                        )}
                    </button>

                    <button
                        type="button"
                        onClick={onOpenDetails}
                        title="View conversation details"
                        aria-label="View conversation details"
                        className="rounded-lg p-2 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <Info size={17} />
                    </button>

                    {contentsEnabled && (
                        <button
                            type="button"
                            onClick={() => toggle('contents')}
                            aria-pressed={drawerMode === 'contents'}
                            title="Open conversation contents"
                            aria-label="Open conversation contents"
                            className={clsx(
                                'rounded-lg p-2 transition-colors',
                                drawerMode === 'contents'
                                    ? 'bg-accent-soft text-accent'
                                    : 'text-text-3 hover:bg-surface-2 hover:text-text-1',
                            )}
                        >
                            <ListOrdered size={17} />
                        </button>
                    )}

                    <button
                        type="button"
                        onClick={() => toggle('documents')}
                        aria-pressed={drawerMode === 'documents'}
                        title="Open used documents"
                        aria-label="Open used documents"
                        className={clsx(
                            'relative rounded-lg p-2 transition-colors',
                            drawerMode === 'documents'
                                ? 'bg-accent-soft text-accent'
                                : 'text-text-3 hover:bg-surface-2 hover:text-text-1',
                        )}
                    >
                        <Files size={17} />
                        {documentCount ? (
                            <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-on-accent">
                                {documentCount}
                            </span>
                        ) : null}
                    </button>
                </div>
            )}
        </header>
    );
}

export function ChatPage() {
    const [detailsOpen, setDetailsOpen] = useState(false);

    useConversationUrlSync();

    return (
        <div className="flex min-h-0 flex-1">
            <div className="flex min-w-0 flex-1 flex-col">
                <ChatHeader onOpenDetails={() => setDetailsOpen(true)} />
                <MessageList />
                <Composer />
            </div>
            <ConversationDrawer />
            {detailsOpen && <ConversationDetails onClose={() => setDetailsOpen(false)} />}
        </div>
    );
}
