// orchestrationResume.ts
// Reading a conversation's stored runs back into the page when it opens.
//
// Two things happen here, and they share a fetch because they need the same answer.
//
// The first is history: every run a conversation has produced is loaded so the plan drawer has
// something to show. Runs have always been written to Cosmos and the planner has always read them
// back, but nothing in the browser ever asked for them, so a conversation opened after a reload --
// or in a second tab, or on a different machine -- showed an empty panel for work that plainly
// happened. Hydrating on open rather than when the drawer opens means the panel is populated the
// moment it is unfolded, and the drawer's own fetch becomes a fallback for conversations reached
// some other way.
//
// The second is the unfinished business. A plan that was proposed and never answered is stored as
// `awaiting_approval`, and until now the only device that could act on it was the one that closed
// the tab. Restoring the card lets the approval be picked up wherever the user actually is. The
// server is what makes that safe: the run endpoint reads the plan from the stored record rather
// than the request, and refuses a run whose plan has already run, so the worst case of two devices
// holding the same card is that the slower one is told so and re-reads the conversation.

import { useChatStore } from '../stores/chatStore';
import {
    isResumablePlanStatus,
    selectActiveTurn,
    selectPlan,
    useOrchestrationStore,
} from '../stores/orchestrationStore';
import { fetchConversationRuns, fetchOrchestrationRun, fetchRunSteps } from './orchestration';
import { refreshOrchestrationPlanEditor } from './orchestrationController';
import type { Json } from './orchestration';

/** How many runs to ask for. Matches the store's per-conversation history cap. */
const RUN_FETCH_LIMIT = 25;

/**
 * Conversations already considered, so opening one twice does not re-fetch or re-offer.
 *
 * Deliberately not cleared when a conversation closes: within one page life, a conversation's
 * stored runs are read once. Anything that happens afterwards happened in this tab, and the store
 * already knows about it.
 */
const consideredConversations = new Set<string>();

/** Forget what has been considered. Exists for tests and for a signed-out reset. */
export function resetOrchestrationResume(): void {
    consideredConversations.clear();
}

/**
 * Load a conversation's stored runs, and restore an unanswered plan if there is one.
 *
 * Safe to call on every render pass for a conversation: the work is done once, and a conversation
 * whose runs are already loaded skips straight to the resume check.
 */
export async function resumeOrchestrationForConversation(
    conversationId: string,
): Promise<void> {
    if (!conversationId || consideredConversations.has(conversationId)) {
        return;
    }
    consideredConversations.add(conversationId);

    const store = useOrchestrationStore.getState();
    const status = store.hydration[conversationId] ?? 'idle';
    if (status === 'idle' || status === 'error') {
        store.setHydrationStatus(conversationId, 'loading');
        try {
            const runs = await fetchConversationRuns(conversationId, { limit: RUN_FETCH_LIMIT });
            useOrchestrationStore.getState().hydrateConversationRuns(conversationId, runs);
        } catch {
            useOrchestrationStore.getState().setHydrationStatus(conversationId, 'error');
            // The drawer offers a retry; a conversation whose history could not be read has no
            // pending approval to restore either, because the record that would say so is what
            // failed to arrive.
            consideredConversations.delete(conversationId);
            return;
        }
    } else if (status === 'loading') {
        // The drawer got there first. It will finish the hydration; the resume check is dropped
        // rather than racing it, and the conversation is left unconsidered so a later pass retries.
        consideredConversations.delete(conversationId);
        return;
    }

    await restorePendingApproval(conversationId);
}

/**
 * Put an unanswered plan's card back, if the conversation's newest run is genuinely unanswered.
 *
 * Three things have to hold, and each rules out a way of resurrecting something misleading:
 * the run must be the newest one, so an old abandoned proposal cannot jump in front of later work;
 * this page must not already have a card up, so a live turn is never displaced; and no assistant
 * message may follow the run's question, because one means the turn was answered -- by the other
 * device, or by a plain chat reply after the proposal was dismissed.
 */
async function restorePendingApproval(conversationId: string): Promise<void> {
    const store = useOrchestrationStore.getState();
    if (selectActiveTurn(store, conversationId)) {
        return;
    }

    const newest = (store.hydratedHistory[conversationId] ?? [])[0];
    if (!newest || !isResumablePlanStatus(newest.planStatus)) {
        return;
    }
    if (!newest.userMessageId) {
        // Nothing to anchor the card to in the thread. A plan whose question cannot be found is
        // left alone rather than floated at the bottom of an unrelated conversation.
        return;
    }
    if (conversationHasReplyAfter(conversationId, newest.userMessageId)) {
        return;
    }

    let plan: Json | null = null;
    let steps: Awaited<ReturnType<typeof fetchRunSteps>> = [];
    try {
        const [record, stepRecords] = await Promise.all([
            fetchOrchestrationRun(newest.runId, { conversationId }),
            fetchRunSteps(newest.runId, { conversationId }),
        ]);
        plan = record?.plan ?? null;
        steps = stepRecords;
    } catch {
        return;
    }
    if (!plan) {
        return;
    }

    // Everything is re-checked after the await: the fetch is not instant, and the user may have
    // asked something new in the meantime, which would have put a card of its own up.
    const current = useOrchestrationStore.getState();
    if (selectActiveTurn(current, conversationId)) {
        return;
    }
    if (useChatStore.getState().activeConversationId !== conversationId) {
        consideredConversations.delete(conversationId);
        return;
    }

    current.adoptPersistedPlan(
        conversationId,
        newest.turnId,
        neutralizeTimedApproval(plan),
        steps,
        { readOnly: false },
    );
    useOrchestrationStore.getState().setActiveTurn(conversationId, newest.turnId);
    const restored = selectPlan(useOrchestrationStore.getState(), conversationId, newest.turnId);
    if (restored?.edit_version) {
        await refreshOrchestrationPlanEditor({ conversationId, turnId: newest.turnId }, newest.runId);
    }
}

/**
 * Whether an assistant reply follows a message in the loaded thread.
 *
 * A run's own question is the anchor. Anything the assistant said after it means the turn reached
 * an answer, whatever produced it.
 */
function conversationHasReplyAfter(conversationId: string, userMessageId: string): boolean {
    const chat = useChatStore.getState();
    if (chat.activeConversationId !== conversationId) {
        // The thread on screen is a different conversation, so it cannot be used to judge this
        // one. Treated as answered, which errs towards showing nothing.
        return true;
    }
    const index = chat.messages.findIndex((message) => message.id === userMessageId);
    if (index < 0) {
        // The question is not in the loaded thread. Same reasoning: no anchor, no card.
        return true;
    }
    return chat.messages
        .slice(index + 1)
        .some((message) => message.role === 'assistant');
}

/**
 * Turn a restored timed approval into a manual one.
 *
 * A timed plan's contract is "this runs unless you stop it in the next N seconds", and that
 * bargain was offered to whoever was watching at the time. Restoring it verbatim would restart the
 * clock on a device that was not there, and run real work -- searches, documents, model calls --
 * because someone opened a laptop. The plan is restored as an ordinary approval instead: the same
 * steps, the same everything else, but it waits to be asked for.
 */
function neutralizeTimedApproval(plan: Json): Json {
    if (!plan || typeof plan !== 'object' || Array.isArray(plan)) {
        return plan;
    }
    const record = plan as Record<string, unknown>;
    const approval = record.approval;
    if (!approval || typeof approval !== 'object' || Array.isArray(approval)) {
        return plan;
    }
    const approvalRecord = approval as Record<string, unknown>;
    if (approvalRecord.mode !== 'timed') {
        return plan;
    }
    return {
        ...record,
        approval: { ...approvalRecord, mode: 'manual', timeout_seconds: 0 },
    } as Json;
}
