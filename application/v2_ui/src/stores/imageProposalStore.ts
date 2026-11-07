// imageProposalStore.ts
// Every image proposal card's approval state, and every approval still running.
//
// This used to live in `ImageProposalScope`, as React state owned by the message bubble. That
// was enough to survive the markdown subtree being rebuilt, which was the bug it was written
// for, but not enough to survive the bubble itself going away — and `selectConversation`
// clears the message list, so leaving a conversation unmounts every scope in it. The approvals
// carried on regardless, because the queue and the requests are module-level and know nothing
// about what is on screen, so coming back showed a set of untouched cards inviting the user to
// pay a second time for images that were already being generated.
//
// So the state lives here instead, keyed by conversation and assistant message rather than by
// component. Nothing about a card's identity depends on it being rendered.
//
// The in-flight records are kept separately from the card states and persisted, because they
// are the part that has to survive the page itself. See `imageProposalTracking.ts`.

import { create } from 'zustand';
import {
    applyCardStatePatch,
    IDLE_CARD_STATE,
    type ProposalCardState,
    type ProposalCardStates,
} from '../lib/imageProposalCardState';
import {
    approvalRecordId,
    loadApprovals,
    saveApprovals,
    type TrackedApproval,
} from '../lib/imageProposalTracking';

/** Cards are filed per message, so one conversation's reload cannot disturb another's. */
function scopeKey(conversationId: string, assistantMessageId: string): string {
    return `${conversationId}\u0000${assistantMessageId}`;
}

const EMPTY_CARD_STATES: ProposalCardStates = {};

/** How an approval stopped being in flight. */
export type ApprovalOutcome = 'generated' | 'failed';

interface ImageProposalState {
    /** Card states, keyed by `scopeKey` then by `proposalCardKey`. */
    cards: Record<string, ProposalCardStates>;
    /** Approvals that have been started and whose image has not been seen, by record id. */
    inFlight: Record<string, TrackedApproval>;
    /**
     * The conversation whose proposal cards are actually on screen, or null.
     *
     * Not the same question as which conversation is open. The chat store keeps
     * `activeConversationId` set while the user reads their documents in My Workspace, and the
     * cards are certainly not visible there. Only the chat page knows, so the chat page says.
     */
    visibleConversationId: string | null;
    /**
     * How the approvals since the last quiet moment turned out.
     *
     * Counted here because no single place watches an approval from start to finish: one may
     * be settled by its own request, another by a poll after a reload, a third by giving up on
     * it. The notice that reports the batch reads these and then clears them.
     */
    settledGenerated: number;
    settledFailed: number;

    updateCardState: (
        conversationId: string,
        assistantMessageId: string,
        cardKey: string,
        patch: Partial<ProposalCardState>,
    ) => void;

    /**
     * Record an approval as started.
     *
     * Returns false when one is already tracked for this card, which is the guard against a
     * second request for an image that is already being paid for — reachable through "Approve
     * all" landing on a card whose own Approve was just pressed, or a restored record whose
     * card offers Approve again before the restore has been applied.
     */
    beginApproval: (record: Omit<TrackedApproval, 'resumed'>) => boolean;

    /** Forget an approval, recording how it ended. */
    endApproval: (recordId: string, outcome: ApprovalOutcome) => void;

    /** Adopt records restored from storage after a reload. */
    restoreApprovals: (records: TrackedApproval[]) => void;

    /** Clear the batch counters, once whatever reports them has done so. */
    clearSettled: () => void;

    /** Record which conversation's cards the user can currently see. */
    setVisibleConversation: (conversationId: string | null) => void;

    /**
     * Drop the card states of conversations with nothing in flight.
     *
     * Card state is cheap but unbounded, and a long session that opens many conversations would
     * otherwise accumulate one entry per proposal it ever displayed. A conversation with an
     * approval running is kept whatever else is true of it.
     */
    pruneSettled: (keepConversationId: string | null) => void;
}

export const useImageProposalStore = create<ImageProposalState>((set, get) => ({
    cards: {},
    inFlight: {},
    visibleConversationId: null,
    settledGenerated: 0,
    settledFailed: 0,

    updateCardState: (conversationId, assistantMessageId, cardKey, patch) => {
        if (!conversationId || !assistantMessageId) {
            return;
        }

        const key = scopeKey(conversationId, assistantMessageId);
        set((state) => {
            const current = state.cards[key] ?? EMPTY_CARD_STATES;
            const next = applyCardStatePatch(current, cardKey, patch);
            if (next === current) {
                return {};
            }
            return { cards: { ...state.cards, [key]: next } };
        });
    },

    beginApproval: (record) => {
        const id = approvalRecordId(
            record.conversationId,
            record.assistantMessageId,
            record.cardKey,
        );
        if (get().inFlight[id]) {
            return false;
        }

        const tracked: TrackedApproval = { ...record, resumed: false };
        const inFlight = { ...get().inFlight, [id]: tracked };
        set({ inFlight });
        saveApprovals(Object.values(inFlight));
        return true;
    },

    endApproval: (recordId, outcome) => {
        if (!get().inFlight[recordId]) {
            return;
        }

        const inFlight = { ...get().inFlight };
        delete inFlight[recordId];
        set((state) => ({
            inFlight,
            settledGenerated: state.settledGenerated + (outcome === 'generated' ? 1 : 0),
            settledFailed: state.settledFailed + (outcome === 'failed' ? 1 : 0),
        }));
        saveApprovals(Object.values(inFlight));
    },

    restoreApprovals: (records) => {
        if (records.length === 0) {
            return;
        }

        set((state) => {
            const inFlight = { ...state.inFlight };
            const cards = { ...state.cards };

            for (const record of records) {
                const id = approvalRecordId(
                    record.conversationId,
                    record.assistantMessageId,
                    record.cardKey,
                );
                // A record started by this page is authoritative; it has a request behind it.
                if (inFlight[id]) {
                    continue;
                }
                inFlight[id] = record;

                // Seed the card so it reports the approval the moment it renders, rather than
                // waiting for the first poll to come back.
                const key = scopeKey(record.conversationId, record.assistantMessageId);
                cards[key] = applyCardStatePatch(cards[key] ?? EMPTY_CARD_STATES, record.cardKey, {
                    status: 'generating',
                    resumed: true,
                    failure: '',
                    queuePosition: 0,
                });
            }

            saveApprovals(Object.values(inFlight));
            return { inFlight, cards };
        });
    },

    clearSettled: () => {
        if (get().settledGenerated === 0 && get().settledFailed === 0) {
            return;
        }
        set({ settledGenerated: 0, settledFailed: 0 });
    },

    setVisibleConversation: (conversationId) => {
        if (get().visibleConversationId === conversationId) {
            return;
        }
        set({ visibleConversationId: conversationId });
    },

    pruneSettled: (keepConversationId) => {
        const busy = new Set<string>();
        for (const record of Object.values(get().inFlight)) {
            busy.add(record.conversationId);
        }
        if (keepConversationId) {
            busy.add(keepConversationId);
        }

        set((state) => {
            const cards: Record<string, ProposalCardStates> = {};
            let removed = false;
            for (const [key, value] of Object.entries(state.cards)) {
                if (busy.has(key.split('\u0000')[0] ?? '')) {
                    cards[key] = value;
                } else {
                    removed = true;
                }
            }
            return removed ? { cards } : {};
        });
    },
}));

/* -------------------------------------------------------------------------- */
/* Reading                                                                     */
/* -------------------------------------------------------------------------- */

/** Every card state for one assistant message. Stable when there are none. */
export function selectCardStates(
    state: ImageProposalState,
    conversationId: string,
    assistantMessageId: string,
): ProposalCardStates {
    if (!conversationId || !assistantMessageId) {
        return EMPTY_CARD_STATES;
    }
    return state.cards[scopeKey(conversationId, assistantMessageId)] ?? EMPTY_CARD_STATES;
}

/** One card's state, or the shared idle state. */
export function readCardState(
    conversationId: string,
    assistantMessageId: string,
    cardKey: string,
): ProposalCardState {
    return (
        selectCardStates(useImageProposalStore.getState(), conversationId, assistantMessageId)[
            cardKey
        ] ?? IDLE_CARD_STATE
    );
}

/** How many approvals are running for a conversation. Drives the rail's row indicator. */
export function selectInFlightCount(state: ImageProposalState, conversationId: string): number {
    if (!conversationId) {
        return 0;
    }
    let count = 0;
    for (const record of Object.values(state.inFlight)) {
        if (record.conversationId === conversationId) {
            count += 1;
        }
    }
    return count;
}

/** Every approval still running, whichever conversation it belongs to. */
export function inFlightApprovals(): TrackedApproval[] {
    return Object.values(useImageProposalStore.getState().inFlight);
}

/** Record ids of approvals that were restored rather than started by this page. */
export function resumedApprovalEntries(): { id: string; record: TrackedApproval }[] {
    return Object.entries(useImageProposalStore.getState().inFlight)
        .filter(([, record]) => record.resumed)
        .map(([id, record]) => ({ id, record }));
}

/**
 * Adopt whatever the previous page left behind.
 *
 * Separate from the store's creation so it runs once, at a point where failing is survivable,
 * rather than as a side effect of the first component to import the module.
 */
export function restorePersistedApprovals(): TrackedApproval[] {
    const records = loadApprovals();
    useImageProposalStore.getState().restoreApprovals(records);
    return records;
}
