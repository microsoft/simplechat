// scopeLockStore.ts
// The scope lock dialog and the change it is making, shared by every control that opens it.
//
// Three controls open the same dialog: the lock beside the chat title, a row in the conversation
// details and a note in the Documents picker. None of them can own it. The picker closes itself
// when the reader clicks anywhere outside it, which would take a dialog it hosted away halfway
// through a sentence, and two dialogs open at once would answer one press twice. So the dialog is
// hosted once, beside the header's lock, and the controls only ask for it here.
//
// The change itself runs through `changeScopeLock`, which is pure; this file wires its effects to
// the chat store (the loaded metadata every badge and row reads) and to the server.

import { useMemo } from 'react';
import { create } from 'zustand';
import { setConversationScopeLock } from '../lib/endpoints';
import {
    changeScopeLock,
    resolveScopeLockView,
    scopeLockEnforced,
    withScopeLockFields,
    type ScopeLockEffects,
    type ScopeLockView,
} from '../lib/scopeLock';
import { useBootstrapStore } from './bootstrapStore';
import { useChatStore } from './chatStore';
import { toast } from './toastStore';

interface ScopeLockUiState {
    open: boolean;
    /** True from the press until the server has answered. One change at a time. */
    pending: boolean;
    /** Why the last change failed, shown in the dialog that made it. */
    error: string | null;
    openDialog: () => void;
    closeDialog: () => void;
    change: (conversationId: string, locked: boolean) => Promise<boolean>;
}

/**
 * The chat store as the lock's effects see it, for one conversation.
 *
 * Every read and write checks that the loaded metadata still belongs to `conversationId`. The
 * reader can open another conversation while a change is in flight, and the answer must not be
 * written onto it.
 */
function chatEffects(conversationId: string): ScopeLockEffects {
    return {
        read: () => {
            const metadata = useChatStore.getState().metadata;
            return metadata?.conversation_id === conversationId
                ? { scope_locked: metadata.scope_locked ?? null, locked_contexts: metadata.locked_contexts }
                : null;
        },
        write: (fields) =>
            useChatStore.setState((state) =>
                state.metadata?.conversation_id === conversationId
                    ? { metadata: withScopeLockFields(state.metadata, fields) }
                    : state,
            ),
        send: (locked) => setConversationScopeLock(conversationId, locked),
        refresh: () => {
            void useChatStore.getState().loadMetadata(conversationId);
        },
    };
}

export const useScopeLockStore = create<ScopeLockUiState>((set, get) => ({
    open: false,
    pending: false,
    error: null,

    openDialog: () => set({ open: true, error: null }),

    closeDialog: () => {
        // A change that is running keeps its dialog: closing it would leave the outcome, and a
        // refusal in particular, with nowhere to be said.
        if (!get().pending) {
            set({ open: false, error: null });
        }
    },

    change: async (conversationId, locked) => {
        if (get().pending) {
            return false;
        }
        set({ pending: true, error: null });
        const result = await changeScopeLock(locked, chatEffects(conversationId));
        if (result.ok) {
            set({ pending: false, open: false, error: null });
            toast.success(locked ? 'Workspace scope locked.' : 'Workspace scope unlocked.');
            return true;
        }
        if (get().open) {
            set({ pending: false, error: result.message });
        } else {
            // The dialog was dismissed while the request ran, so there is nothing left to hold the
            // message. A refusal that nobody sees would read as a lock that quietly did not change.
            set({ pending: false });
            toast.error(result.message);
        }
        return false;
    },
}));

/**
 * The open conversation's lock, as this reader may act on it.
 *
 * `hidden` until the metadata has loaded and the conversation has a lock state at all, so a
 * control can render from this alone.
 */
export function useScopeLockView(): ScopeLockView {
    const metadata = useChatStore((state) => state.metadata);
    const settings = useBootstrapStore((state) => state.data?.settings);
    const viewerId = useBootstrapStore((state) => state.data?.user?.id);
    const groups = useBootstrapStore((state) => state.data?.scope?.groups);
    const publicWorkspaces = useBootstrapStore((state) => state.data?.scope?.public_workspaces);

    return useMemo(
        () =>
            resolveScopeLockView(metadata, {
                enforced: scopeLockEnforced(settings),
                viewerId,
                directory: { groups: groups ?? [], publicWorkspaces: publicWorkspaces ?? [] },
            }),
        [metadata, settings, viewerId, groups, publicWorkspaces],
    );
}
