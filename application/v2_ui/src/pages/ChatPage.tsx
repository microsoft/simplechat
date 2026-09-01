// ChatPage.tsx
// Chat surface: header, message thread, composer, and the right-hand drawer.

import { useState } from 'react';
import { clsx } from 'clsx';
import { Files, Info, ListOrdered } from 'lucide-react';
import { useChatStore } from '../stores/chatStore';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { MessageList } from '../components/chat/MessageList';
import { Composer } from '../components/chat/Composer';
import { ConversationDrawer } from '../components/chat/ConversationDrawer';
import { ConversationDetails } from '../components/chat/ConversationDetails';
import { ConversationBadges } from '../components/chat/ConversationBadges';

function ChatHeader({ onOpenDetails }: { onOpenDetails: () => void }) {
    const { activeConversationId, conversations, drawerMode, setDrawerMode, metadata } =
        useChatStore();
    const contentsEnabled = useBootstrapStore((state) =>
        Boolean(state.data?.features?.enable_conversation_contents_drawer),
    );

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
