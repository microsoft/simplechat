// workflowAssistStore.ts
//
// What the workflow editor's Ask AI tab remembers about its answers, beside the shared assist
// thread that holds the messages: each completed turn's changes, warnings and Undo result, and
// how long the assistant asked the browser to wait before sending again.
//
// Nothing is persisted. The v1 conversation is ephemeral, so a page reload forgets it all, like
// the thread itself. Turn records are kept per submission id and capped; the wait is per user,
// because the server's limits are, so it holds across every workflow the user edits.

import { create } from 'zustand';
import type { WorkflowAssistTurnRecord } from '../lib/workflowAssist';

/** Completed turns remembered across every workflow editor on the page, oldest dropped first. */
export const MAX_WORKFLOW_ASSIST_TURNS = 200;

interface WorkflowAssistState {
    turns: Readonly<Record<string, WorkflowAssistTurnRecord>>;
    /** Submission ids, oldest first. */
    order: readonly string[];
    /** Epoch milliseconds before which the assistant asked not to be sent another request. */
    retryUntil: number;
    record: (turnId: string, record: WorkflowAssistTurnRecord) => void;
    update: (turnId: string, change: (record: WorkflowAssistTurnRecord) => WorkflowAssistTurnRecord) => void;
    waitUntil: (time: number) => void;
    /** Forget everything, for tests and sign-out. */
    reset: () => void;
}

export const useWorkflowAssistStore = create<WorkflowAssistState>((set) => ({
    turns: {},
    order: [],
    retryUntil: 0,

    record: (turnId, record) => set((state) => {
        const order = [...state.order.filter((id) => id !== turnId), turnId];
        const turns: Record<string, WorkflowAssistTurnRecord> = { ...state.turns, [turnId]: record };
        while (order.length > MAX_WORKFLOW_ASSIST_TURNS) {
            const dropped = order.shift();
            if (dropped !== undefined) delete turns[dropped];
        }
        return { turns, order };
    }),

    update: (turnId, change) => set((state) => {
        const current = state.turns[turnId];
        if (!current) return {};
        const next = change(current);
        return next === current ? {} : { turns: { ...state.turns, [turnId]: next } };
    }),

    waitUntil: (time) => set((state) => (time > state.retryUntil ? { retryUntil: time } : {})),

    reset: () => set({ turns: {}, order: [], retryUntil: 0 }),
}));
