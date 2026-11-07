// imageProposalResume.ts
// Keeps image approvals that outlive the view they were started from visible and settled.
//
// Two things happen to an approval once the user stops looking at it, and they need different
// answers.
//
// Leaving the conversation only unmounts the cards. The request is still running and its
// promise still reports into `imageProposalStore`, so nothing has to be recovered — but the
// user is now somewhere with no card to look at, which is what the away notice is for.
//
// Reloading the page destroys the request. The server does not care: the approval is a blocking
// call it finishes and stores regardless of who is still connected, so the image arrives whether
// or not anything is waiting for it. What is lost is only the knowledge that it is coming. The
// records are restored from storage and the status route is polled until each one's image shows
// up, at which point the conversation is re-read through the ordinary path so the image lands in
// its card exactly as it would have done.
//
// Polling is the honest mechanism here. There is no stream to reattach to: image approval is a
// plain POST, not an SSE generation like `/api/chat/stream`, so there is no server-side session
// to pick back up.

import { fetchImageProposalStatus } from './endpoints';
import {
    earliestStart,
    hasExpired,
    matchesTrackedApproval,
    type TrackedApproval,
} from './imageProposalTracking';
import {
    resumedApprovalEntries,
    restorePersistedApprovals,
    useImageProposalStore,
} from '../stores/imageProposalStore';
import { useChatStore } from '../stores/chatStore';
import { toast } from '../stores/toastStore';

/** First poll, soon enough that an approval which finished while away resolves immediately. */
const FIRST_POLL_MS = 1_500;
/** Growth factor and ceiling, so a long generation does not keep asking every second. */
const POLL_BACKOFF = 1.5;
const MAX_POLL_MS = 15_000;

let pollTimer: number | null = null;
let pollDelay = FIRST_POLL_MS;
let started = false;

/* -------------------------------------------------------------------------- */
/* Polling                                                                     */
/* -------------------------------------------------------------------------- */

/** Group the restored records by the conversation whose status has to be asked about. */
function resumedByConversation(): Map<string, { id: string; record: TrackedApproval }[]> {
    const grouped = new Map<string, { id: string; record: TrackedApproval }[]>();
    for (const entry of resumedApprovalEntries()) {
        const existing = grouped.get(entry.record.conversationId);
        if (existing) {
            existing.push(entry);
        } else {
            grouped.set(entry.record.conversationId, [entry]);
        }
    }
    return grouped;
}

/** Report a restored approval as arrived. The image itself comes back through the thread. */
function settleArrived(id: string, record: TrackedApproval): void {
    const store = useImageProposalStore.getState();
    store.endApproval(id, 'generated');
    store.updateCardState(record.conversationId, record.assistantMessageId, record.cardKey, {
        status: 'generated',
        resumed: false,
        failure: '',
    });
}

/** Report a restored approval as lost, with something the user can act on. */
function settleLost(id: string, record: TrackedApproval): void {
    const store = useImageProposalStore.getState();
    store.endApproval(id, 'failed');
    store.updateCardState(record.conversationId, record.assistantMessageId, record.cardKey, {
        status: 'error',
        resumed: false,
        failure:
            'The page reloaded while this image was being generated and it has not appeared. ' +
            'Reopen the conversation to check, or approve it again.',
    });
}

/**
 * Ask one conversation which of its restored approvals have landed.
 *
 * Returns true when at least one did, which resets the backoff: images approved together tend
 * to arrive together, so the next one is likely to be close behind.
 */
async function pollConversation(
    conversationId: string,
    entries: { id: string; record: TrackedApproval }[],
): Promise<boolean> {
    const now = Date.now();

    const live = entries.filter(({ id, record }) => {
        if (hasExpired(record, now)) {
            settleLost(id, record);
            return false;
        }
        return true;
    });
    if (live.length === 0) {
        return false;
    }

    const response = await fetchImageProposalStatus(
        conversationId,
        earliestStart(live.map((entry) => entry.record)),
    );
    const candidates = response?.results ?? [];
    if (candidates.length === 0) {
        return false;
    }

    let arrived = false;
    for (const { id, record } of live) {
        const match = candidates.find((candidate) => matchesTrackedApproval(record, candidate));
        if (match) {
            settleArrived(id, record);
            arrived = true;
        }
    }

    // One re-read covers however many images arrived in this poll, and only when the reader is
    // actually looking at the conversation they landed in. Anywhere else, opening the
    // conversation reads it anyway.
    if (arrived && useChatStore.getState().activeConversationId === conversationId) {
        void useChatStore.getState().reloadMessages();
    }

    return arrived;
}

async function runPoll(): Promise<void> {
    const grouped = resumedByConversation();
    if (grouped.size === 0) {
        return;
    }

    let arrived = false;
    for (const [conversationId, entries] of grouped) {
        try {
            if (await pollConversation(conversationId, entries)) {
                arrived = true;
            }
        } catch {
            // A failed poll is not a failed approval. The next one asks again, and the record
            // is written off on its own deadline rather than on one bad response.
        }
    }

    pollDelay = arrived ? FIRST_POLL_MS : Math.min(pollDelay * POLL_BACKOFF, MAX_POLL_MS);
}

/**
 * Keep polling while there is anything to poll for.
 *
 * Suspended while the tab is hidden, because a background tab cannot be told anything and the
 * work continues server-side regardless; `visibilitychange` starts it again.
 */
function schedulePoll(): void {
    if (pollTimer !== null) {
        return;
    }
    if (resumedApprovalEntries().length === 0) {
        return;
    }
    if (typeof document !== 'undefined' && document.hidden) {
        return;
    }

    pollTimer = window.setTimeout(() => {
        pollTimer = null;
        void runPoll().finally(schedulePoll);
    }, pollDelay);
}

/* -------------------------------------------------------------------------- */
/* The away notice                                                             */
/* -------------------------------------------------------------------------- */

let noticeId: number | null = null;

/** Approvals running for a conversation whose cards are not on screen. */
function awayCount(): number {
    const { inFlight, visibleConversationId } = useImageProposalStore.getState();
    let count = 0;
    for (const record of Object.values(inFlight)) {
        if (record.conversationId !== visibleConversationId) {
            count += 1;
        }
    }
    return count;
}

function describeBatch(generated: number, failed: number): string {
    const parts: string[] = [];
    if (generated > 0) {
        parts.push(`${generated} image${generated === 1 ? '' : 's'} generated`);
    }
    if (failed > 0) {
        parts.push(`${failed} could not be generated`);
    }
    return parts.length > 0 ? `${parts.join(', ')}.` : 'Image generation finished.';
}

/**
 * Say that images are still being generated somewhere the user cannot see them.
 *
 * Only while they are elsewhere: over the conversation that owns the cards this would repeat
 * what every one of those cards is already showing, which is noise rather than information.
 */
function refreshNotice(): void {
    const count = awayCount();

    if (count > 0) {
        const message = `Generating ${count} image${count === 1 ? '' : 's'} elsewhere…`;
        if (noticeId === null) {
            noticeId = toast.pending(message);
        } else {
            toast.update(noticeId, message);
        }
        return;
    }

    const { settledGenerated, settledFailed, clearSettled } = useImageProposalStore.getState();
    if (noticeId !== null) {
        toast.settle(
            noticeId,
            settledFailed > 0 ? 'error' : 'success',
            describeBatch(settledGenerated, settledFailed),
        );
        noticeId = null;
    }

    // Nothing is running out of sight, so whatever these counted has either been reported by
    // the notice just settled or happened in front of the user on the cards themselves. Either
    // way it has been seen, and carrying it into the next batch would double-count it.
    clearSettled();
}

/* -------------------------------------------------------------------------- */
/* Lifecycle                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * Adopt anything the previous page left running, and keep it reported until it settles.
 *
 * Called once, from the app shell, so it covers a reload that lands anywhere — the chat page
 * is not required to be mounted for an approval to be recovered or for the notice to appear.
 */
export function startImageApprovalTracking(): void {
    if (started) {
        return;
    }
    started = true;

    restorePersistedApprovals();

    // Both subscriptions are filtered rather than run on every store change. The chat store
    // updates on every streamed token, and the proposal store updates on every queue position
    // report, and neither of those can change what the notice says or what has to be polled.
    useImageProposalStore.subscribe((state, previous) => {
        if (state.visibleConversationId !== previous.visibleConversationId) {
            refreshNotice();
        }
        if (state.inFlight === previous.inFlight) {
            return;
        }
        refreshNotice();
        schedulePoll();
    });
    useChatStore.subscribe((state, previous) => {
        if (state.activeConversationId !== previous.activeConversationId) {
            // Card state is kept per conversation and nothing else clears it, so a long
            // session that visited many threads would hold an entry for every proposal it had
            // ever shown. A conversation with an approval running is never pruned.
            useImageProposalStore.getState().pruneSettled(state.activeConversationId);
        }
    });

    if (typeof document !== 'undefined') {
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                // Back on screen: ask straight away rather than waiting out a backoff that grew
                // while nobody was watching.
                pollDelay = FIRST_POLL_MS;
                schedulePoll();
            }
        });
    }

    refreshNotice();
    schedulePoll();
}
