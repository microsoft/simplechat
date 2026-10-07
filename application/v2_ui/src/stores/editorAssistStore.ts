// editorAssistStore.ts
//
// What the agent and action editors' Ask AI panel remembers about its answers, beside the shared
// assist thread that holds the messages: each completed turn's changes, warnings and Undo result,
// and how long the assistant asked the browser to wait before sending again.
//
// Nothing is persisted. Turn records are kept per submission id and capped; the wait is per user,
// because the server's limits are, so it holds across every editor the user opens.

import { create } from 'zustand';
import type {
    EditorAssistEntry, EditorAssistNewItem, EditorAssistTurnChange, EditorAssistValues, EditorAssistWarning,
} from '../lib/editorAssist';

/** Completed turns remembered across every agent and action editor on the page, oldest dropped first. */
export const MAX_EDITOR_ASSIST_TURNS = 200;

export interface EditorAssistUndoResult {
    readonly reverted: readonly string[];
    readonly skipped: readonly string[];
}

export interface EditorAssistTurnRecord {
    readonly threadKey: string;
    readonly instruction: string;
    readonly reply: string;
    readonly outcome: 'changed' | 'explained';
    readonly changes: readonly EditorAssistTurnChange[];
    /** Per path: the value before the turn and the value it left, for Undo. */
    readonly entries: readonly EditorAssistEntry[];
    /** Every value the turn was sent with, so undoing a type change restores the old type's fields. */
    readonly before: EditorAssistValues;
    readonly newItems: readonly EditorAssistNewItem[];
    readonly warnings: readonly EditorAssistWarning[];
    readonly undo?: EditorAssistUndoResult;
    readonly undoSequence: number;
}

interface EditorAssistState {
    turns: Readonly<Record<string, EditorAssistTurnRecord>>;
    /** Submission ids, oldest first. */
    order: readonly string[];
    /** Epoch milliseconds before which the assistant asked not to be sent another request. */
    retryUntil: number;
    record: (turnId: string, record: EditorAssistTurnRecord) => void;
    update: (turnId: string, change: (record: EditorAssistTurnRecord) => EditorAssistTurnRecord) => void;
    waitUntil: (time: number) => void;
    /** Forget everything, for tests and sign-out. */
    reset: () => void;
}

export const useEditorAssistStore = create<EditorAssistState>((set) => ({
    turns: {},
    order: [],
    retryUntil: 0,

    record: (turnId, record) => set((state) => {
        const order = [...state.order.filter((id) => id !== turnId), turnId];
        const turns: Record<string, EditorAssistTurnRecord> = { ...state.turns, [turnId]: record };
        while (order.length > MAX_EDITOR_ASSIST_TURNS) {
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
