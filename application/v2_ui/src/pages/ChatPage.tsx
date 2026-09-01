// ChatPage.tsx
// Chat surface: a thin header, the message thread, and the composer.

import { useChatStore } from '../stores/chatStore';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { MessageList } from '../components/chat/MessageList';
import { Composer } from '../components/chat/Composer';

function ChatHeader() {
    const { activeConversationId, conversations } = useChatStore();
    const scope = useBootstrapStore((state) => state.data?.scope);

    const active = conversations.find(
        (conversation) => conversation.id === activeConversationId,
    );

    return (
        <header className="glass glass-edge flex h-14 shrink-0 items-center gap-3 rounded-none border-t-0 border-r-0 px-5">
            <h1 className="truncate text-[15px] font-semibold text-text-1">
                {active?.title || 'New chat'}
            </h1>
            {scope?.active_group_name && (
                <span className="rounded-full border border-edge bg-surface-2 px-2 py-0.5 text-xs text-text-2">
                    {scope.active_group_name}
                </span>
            )}
        </header>
    );
}

export function ChatPage() {
    return (
        <>
            <ChatHeader />
            <MessageList />
            <Composer />
        </>
    );
}
