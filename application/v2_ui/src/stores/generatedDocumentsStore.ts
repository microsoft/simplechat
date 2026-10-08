// generatedDocumentsStore.ts
// What the open conversation produced, shared by the Documents drawer and the header.
//
// The Generated section of the Documents drawer lists these and the badge on the drawer's button
// counts them, and both are on screen while a conversation is open. Two kinds are gathered:
//
// - Files the replies produced: plan outputs, exports and analysis files. They are read off the
//   loaded messages and the live run state, with no request of their own.
// - Documents agents created with the SimpleChat upload actions, which the server lists. One copy
//   of that list is kept here, so opening the drawer never repeats a request the badge already
//   made, and the two cannot disagree about what the conversation produced. It is read again
//   whenever the replies the thread shows change, which is when an agent can have created another
//   document or one stopped being shown, and only for a conversation that can hold one at all.
//   A shared conversation's list is only read once the reader has joined it, because the server
//   refuses an invitation that has not been accepted; joining reads it straight away.

import { useEffect, useMemo } from 'react';
import { create } from 'zustand';
import { ApiError } from '../lib/apiClient';
import {
    collectConversationGeneratedFiles,
    generatedDocumentsThreadKey,
    mayHaveGeneratedDocuments,
    visibleGeneratedDocuments,
    type ConversationGeneratedFile,
} from '../lib/conversationGeneratedFiles';
import type { ConversationKind } from '../lib/endpoints';
import { fetchGeneratedDocuments, type GeneratedDocument } from '../lib/generatedDocuments';
import { useChatStore } from './chatStore';
import { useCollaborationStore } from './collaborationStore';
import { useGeneratedExportRunStore } from './generatedExportRunStore';
import { useOrchestrationStore } from './orchestrationStore';

const EMPTY_DOCUMENTS: GeneratedDocument[] = [];

interface GeneratedDocumentsState {
    /**
     * The request the list answers or is waiting on: the conversation, its kind, and what of it the
     * server's answer depends on. Null after a failure, so the next reader to mount tries again.
     */
    requestKey: string | null;
    conversationId: string | null;
    documents: GeneratedDocument[];
    error: string | null;
    load: (conversationId: string, kind: ConversationKind, threadKey: string) => void;
    /** Forget the list, so the conversation is read afresh the next time it needs one. */
    clear: () => void;
}

let inFlight: AbortController | null = null;

export const useGeneratedDocumentsStore = create<GeneratedDocumentsState>((set, get) => ({
    requestKey: null,
    conversationId: null,
    documents: [],
    error: null,
    load: (conversationId, kind, threadKey) => {
        const requestKey = JSON.stringify([conversationId, kind, threadKey]);
        if (get().requestKey === requestKey) {
            return;
        }
        inFlight?.abort();
        const controller = new AbortController();
        inFlight = controller;
        // Keyed by conversation, so another conversation's list is never shown while this one loads.
        set((state) => (state.conversationId === conversationId
            ? { requestKey }
            : { requestKey, conversationId, documents: [], error: null }));

        fetchGeneratedDocuments(conversationId, kind, controller.signal)
            .then((result) => {
                if (get().requestKey === requestKey) {
                    set({ documents: Array.isArray(result?.documents) ? result.documents : [], error: null });
                }
            })
            .catch((cause: unknown) => {
                if (controller.signal.aborted || get().requestKey !== requestKey) {
                    return;
                }
                // Refused or gone: there is nothing to list. Neither answer is kept as final, so a
                // reader who mounts later, such as the drawer being reopened, asks again.
                const refused = cause instanceof ApiError && (cause.status === 403 || cause.status === 404);
                set((state) => ({
                    requestKey: null,
                    documents: refused ? [] : state.documents,
                    error: refused
                        ? null
                        : cause instanceof Error ? cause.message : 'Could not list generated documents.',
                }));
            })
            .finally(() => {
                if (inFlight === controller) {
                    inFlight = null;
                }
            });
    },
    clear: () => {
        const state = get();
        if (state.requestKey === null && state.conversationId === null) {
            return;
        }
        inFlight?.abort();
        inFlight = null;
        set({ requestKey: null, conversationId: null, documents: [], error: null });
    },
}));

/**
 * The documents agents created in the open conversation and the thread still shows, kept current
 * as replies arrive, attempts change or replies are masked.
 */
export function useConversationGeneratedDocuments(): { documents: GeneratedDocument[]; error: string | null } {
    const conversationId = useChatStore((state) => state.activeConversationId);
    const kind = useChatStore((state) => state.activeConversationKind);
    const messages = useChatStore((state) => state.messages);
    // Who the reader is in a shared conversation, once that has loaded. Null while it has not, and
    // while an invitation can still be accepted, because the server refuses the list until then.
    const access = useCollaborationStore((state) => {
        if (kind !== 'collaborative') {
            return 'personal';
        }
        const conversation = state.conversation;
        if (!conversation || conversation.id !== conversationId || conversation.can_accept_invite) {
            return null;
        }
        return String(conversation.membership_status ?? 'member');
    });
    const threadKey = useMemo(() => generatedDocumentsThreadKey(messages), [messages]);
    const wanted = useMemo(() => mayHaveGeneratedDocuments(messages), [messages]) && access !== null;
    const loadedFor = useGeneratedDocumentsStore((state) => state.conversationId);
    const documents = useGeneratedDocumentsStore((state) => state.documents);
    const error = useGeneratedDocumentsStore((state) => state.error);
    const visible = useMemo(() => visibleGeneratedDocuments(documents, messages), [documents, messages]);

    useEffect(() => {
        const store = useGeneratedDocumentsStore.getState();
        if (conversationId && kind && wanted) {
            store.load(conversationId, kind, `${access}:${threadKey}`);
        } else {
            // Nothing to list here. Forgetting the last list means a conversation opened again
            // later is read afresh, rather than shown as it was when it was left.
            store.clear();
        }
    }, [conversationId, kind, wanted, access, threadKey]);

    const current = Boolean(conversationId && wanted && loadedFor === conversationId);
    return {
        documents: current ? visible : EMPTY_DOCUMENTS,
        error: current ? error : null,
    };
}

/**
 * Every file the open conversation's replies produced, as the thread currently shows them.
 *
 * Follows the live plan runs and background exports too, so a file that finishes while the
 * conversation is open changes state here as its card in the thread does.
 */
export function useConversationGeneratedFiles(): ConversationGeneratedFile[] {
    const messages = useChatStore((state) => state.messages);
    const runs = useOrchestrationStore((state) => state.runRecovery);
    const exportRuns = useGeneratedExportRunStore((state) => state.runs);
    return useMemo(
        () => collectConversationGeneratedFiles(messages, { runs, exportRuns }),
        [messages, runs, exportRuns],
    );
}
