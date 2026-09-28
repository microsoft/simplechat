// assistThreadStore.ts
//
// The AI-assist threads behind the diagram, chart, image and plan editors.
//
// There is one thread per edited thing: a diagram block, a chart block, an image or a plan. A
// thread holds what the reader sent that the server has not recorded yet (the exchange in
// flight, one that failed, one they cancelled) and the text they have not sent. What the server
// did record is the editor's own stored chat. The thread only overlays that chat, and each
// exchange drops out of the overlay once the stored chat carries its submission id.
//
// The threads live here rather than in the editors so a request outlives the dialog that sent
// it. Closing an editor mid-request and reopening it shows the same pending turn, and the answer
// lands either way. Nothing is persisted: a reload drops unsent text and in-flight turns, and the
// stored chat is read back from the server.

import { create } from 'zustand';
import type { ComposerDraft } from '../lib/composerDraft';

export type AssistExchangeStatus = 'pending' | 'failed' | 'cancelled' | 'done';

/** One message the reader sent, and what became of it. */
export interface AssistExchange {
    /** The client submission id, which the server stores on both turns of the exchange. */
    id: string;
    /**
     * Every id the exchange was sent under, oldest first, once the editor chose one other than
     * `id`. The plan editor does when a retry is no longer the same request, because the server
     * holds an id to the request it first arrived with. A retry sends the last of them, and any of
     * them may be the one the server stored.
     */
    sentIds?: string[];
    text: string;
    /** What the input held when it was sent, so Edit and resend can put it back. */
    draft: ComposerDraft;
    status: AssistExchangeStatus;
    startedAt: number;
    /** Why it failed, or what cancelling it means. */
    error?: string;
    /** What the assistant said, for a thread whose turns the server does not store. */
    reply?: string;
    /** A cancel was asked for and is not confirmed yet. */
    cancelling?: boolean;
}

export interface AssistThreadRecord {
    conversationId: string | null;
    exchanges: AssistExchange[];
    draft: ComposerDraft;
    /** A one-off note above the input, such as a cancelled request having finished anyway. */
    notice: string | null;
    /**
     * Submission ids of exchanges the reader cancelled or moved on from.
     *
     * Cancelling only stops the browser waiting, so the server may still finish the change.
     * These ids let the next request recognise that as the reader's own change.
     */
    abandonedIds: string[];
    touchedAt: number;
}

/** Completed local exchanges kept per thread; stored threads keep none. */
export const MAX_DONE_EXCHANGES = 20;
/** Threads kept in memory before the least recently used idle ones are dropped. */
export const MAX_THREADS = 50;
/** Abandoned submission ids remembered per thread. */
export const MAX_ABANDONED_IDS = 10;
/** Ids remembered per exchange that was sent under more than one. */
export const MAX_SENT_IDS = 10;

/** An empty input. Built here so the store does not load the composer's dependencies. */
export function blankDraft(): ComposerDraft {
    return { text: '', contextItems: [], attachedPrompt: null, promptValues: {}, uploads: [] };
}

export function newThread(conversationId: string | null, now: number): AssistThreadRecord {
    return {
        conversationId,
        exchanges: [],
        draft: blankDraft(),
        notice: null,
        abandonedIds: [],
        touchedAt: now,
    };
}

/** Whether the input holds anything worth keeping. */
export function draftHasContent(draft: ComposerDraft): boolean {
    return Boolean(draft.text.trim()) || draft.contextItems.length > 0;
}

/** The ids the server may know an exchange by. */
export function exchangeSubmissionIds(exchange: AssistExchange): string[] {
    return exchange.sentIds?.length
        ? Array.from(new Set([exchange.id, ...exchange.sentIds]))
        : [exchange.id];
}

/** The id a retry of an exchange is sent under: the one it was last sent under. */
export function exchangeRetryId(exchange: AssistExchange): string {
    return exchange.sentIds?.[exchange.sentIds.length - 1] ?? exchange.id;
}

/** An exchange's sent ids once it has also been sent under `submissionId`. */
export function withSentId(exchange: AssistExchange, submissionId: string | undefined): string[] | undefined {
    if (!submissionId || submissionId === exchangeRetryId(exchange)) {
        return exchange.sentIds;
    }
    const sent = exchange.sentIds ?? [exchange.id];
    return [...sent.filter((value) => value !== submissionId), submissionId].slice(-MAX_SENT_IDS);
}

/** A thread with nothing in flight, nothing to act on and no unsent text. */
export function isThreadIdle(record: AssistThreadRecord): boolean {
    return !draftHasContent(record.draft)
        && !record.notice
        && record.exchanges.every((exchange) => exchange.status === 'done');
}

function hasPendingExchange(record: AssistThreadRecord): boolean {
    return record.exchanges.some((exchange) => exchange.status === 'pending');
}

/** Keep only the most recent completed exchanges, never dropping one that needs attention. */
export function capDoneExchanges(exchanges: AssistExchange[]): AssistExchange[] {
    const done = exchanges.filter((exchange) => exchange.status === 'done');
    if (done.length <= MAX_DONE_EXCHANGES) {
        return exchanges;
    }
    const dropped = new Set(done.slice(0, done.length - MAX_DONE_EXCHANGES).map((exchange) => exchange.id));
    return exchanges.filter((exchange) => !dropped.has(exchange.id));
}

export function capAbandonedIds(ids: string[]): string[] {
    const unique = Array.from(new Set(ids));
    return unique.length > MAX_ABANDONED_IDS ? unique.slice(unique.length - MAX_ABANDONED_IDS) : unique;
}

/**
 * Drop threads nobody needs, after `keepKey` was touched in `conversationId`.
 *
 * Idle threads of other conversations go first: they hold nothing but an image editor's local
 * transcript. Past the cap, the least recently touched threads with nothing in flight go too.
 * A thread with a pending request is never dropped, because its answer still has to land.
 */
export function pruneThreads(
    threads: Record<string, AssistThreadRecord>,
    keepKey: string,
    conversationId: string | null,
): Record<string, AssistThreadRecord> {
    const kept: Record<string, AssistThreadRecord> = {};
    let removed = false;
    for (const [key, record] of Object.entries(threads)) {
        if (key !== keepKey && record.conversationId !== conversationId && isThreadIdle(record)) {
            removed = true;
        } else {
            kept[key] = record;
        }
    }
    const keys = Object.keys(kept);
    if (keys.length > MAX_THREADS) {
        const evictable = keys
            .filter((key) => key !== keepKey && !hasPendingExchange(kept[key]))
            .sort((left, right) => kept[left].touchedAt - kept[right].touchedAt);
        for (const key of evictable.slice(0, keys.length - MAX_THREADS)) {
            delete kept[key];
            removed = true;
        }
    }
    return removed ? kept : threads;
}

interface AssistThreadState {
    threads: Record<string, AssistThreadRecord>;
    /**
     * Change one thread, creating it when it does not exist.
     *
     * Returning the same record leaves the store untouched, so a no-op change does not re-render
     * every editor that reads a thread.
     */
    updateThread: (
        key: string,
        conversationId: string | null,
        change: (record: AssistThreadRecord) => AssistThreadRecord,
    ) => void;
    /** Forget every thread, for tests and sign-out. */
    resetThreads: () => void;
}

export const useAssistThreadStore = create<AssistThreadState>((set) => ({
    threads: {},

    updateThread: (key, conversationId, change) => {
        set((state) => {
            const existing = state.threads[key];
            const now = Date.now();
            const current = existing ?? newThread(conversationId, now);
            const next = change(current);
            if (existing && next === existing) {
                return {};
            }
            if (!existing && next === current) {
                return {};
            }
            const touched = { ...next, touchedAt: now };
            return { threads: pruneThreads({ ...state.threads, [key]: touched }, key, touched.conversationId) };
        });
    },

    resetThreads: () => set({ threads: {} }),
}));

export function selectAssistThread(
    state: AssistThreadState,
    key: string | null,
): AssistThreadRecord | null {
    return key ? state.threads[key] ?? null : null;
}
