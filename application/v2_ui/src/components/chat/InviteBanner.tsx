// InviteBanner.tsx
// The accept/decline prompt shown above a shared conversation the reader has been invited
// to but has not answered yet.
//
// An invited conversation is readable before it is accepted — the server allows a pending
// member to view it (`allow_pending=True`) so the invitation can be judged on its contents
// rather than blind — but not writable. Without something saying so, the thread would look
// like an ordinary conversation whose composer had inexplicably stopped working.

import { useState } from 'react';
import { Check, UserPlus, X } from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import { useCollaborationStore } from '../../stores/collaborationStore';
import { GlassButton } from '../ui/primitives';

export function InviteBanner() {
    const conversation = useCollaborationStore((state) => state.conversation);
    const respondToInvite = useCollaborationStore((state) => state.respondToInvite);
    const activeConversationId = useChatStore((state) => state.activeConversationId);    const loadConversations = useChatStore((state) => state.loadConversations);
    const selectConversation = useChatStore((state) => state.selectConversation);
    const [busy, setBusy] = useState(false);

    // `can_accept_invite` is the server's own answer, computed from the membership record;
    // it is not inferred here from the status string.
    if (
        !conversation?.can_accept_invite ||
        !activeConversationId ||
        conversation.id !== activeConversationId
    ) {
        return null;
    }

    const respond = async (action: 'accept' | 'decline') => {
        setBusy(true);
        const done = await respondToInvite(action);
        setBusy(false);
        if (!done) {
            return;
        }
        await loadConversations({ reset: true });
        if (action === 'decline') {
            // Declining removes it from the reader's list, so leaving it open would show a
            // conversation every subsequent request refuses.
            await selectConversation(null);
        }
    };

    return (
        <div className="glass-flat mx-4 mt-4 flex flex-wrap items-center gap-3 rounded-xl px-4 py-3">
            <UserPlus size={16} className="shrink-0 text-accent" />
            <p className="min-w-0 flex-1 text-sm text-text-1">
                You have been invited to this shared conversation. You can read it now, and
                reply once you join.
            </p>
            <div className="flex shrink-0 items-center gap-2">
                <GlassButton
                    size="sm"
                    variant="primary"
                    disabled={busy}
                    onClick={() => void respond('accept')}
                >
                    <Check size={14} /> Join
                </GlassButton>
                <GlassButton size="sm" disabled={busy} onClick={() => void respond('decline')}>
                    <X size={14} /> Decline
                </GlassButton>
            </div>
        </div>
    );
}
