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
//   whenever another reply arrives, which is when an agent can have created another document,
//   and only for a conversation that can hold one at all.

import { useEffect, useMemo } from 'react';
import { create } from 'zustand';
import { ApiError } from '../lib/apiClient';
import {
    collectConversationGeneratedFiles,
    mayHaveGeneratedDocuments,
    type ConversationGeneratedFile,
} from '../lib/conversationGeneratedFiles';
import type { ConversationKind } from '../lib/endpoints';
import { fetchGeneratedDocuments, type GeneratedDocument } from '../lib/generatedDocuments';
import { useChatStore } from './chatStore';
import { useGeneratedExportRunStore } from './generatedExportRunStore';
import { useOrchestrationStore } from './orchestrationStore';

const EMPTY_DOCUMENTS: GeneratedDocument[] = [];

interface GeneratedDocumentsState {
    /** The request the list answers or is waiting on: conversation, kind and reply count. */
    requestKey: string | null;
    conversationId: string | null;
    documents: GeneratedDocument[];
    error: string | null;
    load: (conversationId: string, kind: ConversationKind, replyCount: number) => void;
}

let inFlight: AbortController | null = null;

export const useGeneratedDocumentsStore = create<GeneratedDocumentsState>((set, get) => ({
    requestKey: null,
    conversationId: null,
    documents: [],
    error: null,
    load: (conversationId, kind, replyCount) => {
        const requestKey = JSON.stringify([conversationId, kind, replyCount]);
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
                // Refused or gone, as for an invitation not yet accepted: there is nothing to list.
                const refused = cause instanceof ApiError && (cause.status === 403 || cause.status === 404);
                set((state) => ({
                    // Cleared so the next reader to mount, such as the drawer being reopened, tries again.
                    requestKey: refused ? requestKey : null,
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
}));

/** The documents agents created in the open conversation, kept current as replies arrive. */
export function useConversationGeneratedDocuments(): { documents: GeneratedDocument[]; error: string | null } {
    const conversationId = useChatStore((state) => state.activeConversationId);
    const kind = useChatStore((state) => state.activeConversationKind);
    const messages = useChatStore((state) => state.messages);
    const replyCount = useMemo(
        () => messages.filter((message) => message.role !== 'user').length,
        [messages],
    );
    const wanted = useMemo(() => mayHaveGeneratedDocuments(messages), [messages]);
    const loadedFor = useGeneratedDocumentsStore((state) => state.conversationId);
    const documents = useGeneratedDocumentsStore((state) => state.documents);
    const error = useGeneratedDocumentsStore((state) => state.error);

    useEffect(() => {
        if (conversationId && kind && wanted) {
            useGeneratedDocumentsStore.getState().load(conversationId, kind, replyCount);
        }
    }, [conversationId, kind, wanted, replyCount]);

    const current = Boolean(conversationId && wanted && loadedFor === conversationId);
    return {
        documents: current ? documents : EMPTY_DOCUMENTS,
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
