// useEditorAssist.ts
// The agent and action editors' Ask AI panel: its thread, the requests it sends to
// POST /api/agents/assist or /api/actions/assist, and what it does with each answer.
//
// The thread is the shared assist thread in local mode, so the conversation lasts only while the
// editor is open. Each editor describes its draft through `buildView` and changes it through
// `apply`; this hook never touches the draft itself. Before anything is applied, the answer is
// checked against the draft it was sent with, and the patch is computed here rather than trusting
// the change list that came with it. Nothing is saved: the person reviews and saves the draft.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    cancelAssistExchange, makeSubmissionId, useAssistThread,
    type AssistExchange, type AssistSendRequest, type AssistSendResult, type AssistThreadController,
} from '../../lib/assistThread';
import {
    EDITOR_ASSIST_INSTRUCTION_LIMIT, EDITOR_ASSIST_STALE_MESSAGE, EditorAssistRequestError, buildEditorAssistRequest,
    editorAssistConversation, editorAssistKey, editorAssistPatch, editorAssistTurnChanges, editorAssistUndoPlan,
    postEditorAssist, sameEditorAssistValue,
    type EditorAssistKind, type EditorAssistNewItem, type EditorAssistReplayTurn, type EditorAssistRequest,
    type EditorAssistScope, type EditorAssistTurnState, type EditorAssistValues, type EditorAssistView,
} from '../../lib/editorAssist';
import { selectAssistThread, useAssistThreadStore } from '../../stores/assistThreadStore';
import { useEditorAssistStore, type EditorAssistTurnRecord } from '../../stores/editorAssistStore';

const UNAVAILABLE_MESSAGE = "Ask AI isn't available for this editor.";
const NOT_APPLIED_MESSAGE = "Ask AI's changes couldn't be applied to this draft. Nothing was changed.";
const ABORTED: AssistSendResult = { ok: false, error: '', aborted: true };

/** The editor's conversation id for the shared thread store. Each kind shares one. */
export const EDITOR_ASSIST_CONVERSATIONS: Readonly<Record<EditorAssistKind, string>> = {
    agent: 'agent-editor',
    action: 'action-editor',
};

export interface UseEditorAssistOptions {
    readonly kind: EditorAssistKind;
    /** Ask AI is offered: the setting is on and this person can edit this record. */
    readonly available: boolean;
    readonly scope: EditorAssistScope;
    /** The record being edited, such as its id, or a stable value for a new draft. */
    readonly recordKey: string;
    /** The editor cannot take a change now, such as while it saves. */
    readonly blocked: boolean;
    /** The draft as the assistant sees it, read from the editor's latest state. */
    readonly buildView: () => EditorAssistView;
    /**
     * Apply a patch of path to value, creating `newItems` first. Returns the values of every
     * path afterwards, or null when the draft can't take the patch.
     */
    readonly apply: (patch: Readonly<Record<string, unknown>>, newItems: readonly EditorAssistNewItem[]) => EditorAssistValues | null;
    /** Show a section of the editor. */
    readonly onJump: (section: string) => void;
}

export interface EditorAssist {
    readonly kind: EditorAssistKind;
    readonly available: boolean;
    readonly thread: AssistThreadController;
    /** The turn that is running. The editor is locked until it ends. */
    readonly pending: AssistExchange | null;
    /** Nothing new can be sent right now. */
    readonly busy: boolean;
    /** Seconds before the assistant takes another request, after a 429 or a throttled 503. */
    readonly waitSeconds: number;
    readonly turns: Readonly<Record<string, EditorAssistTurnRecord>>;
    /** Sections holding a change from a turn that is still applied. */
    readonly changedSections: ReadonlySet<string>;
    readonly quickAction: (text: string) => boolean;
    readonly undo: (turnId: string) => void;
    readonly jump: (section: string | null) => void;
    readonly cancel: () => void;
}

/** What became of a turn's changes. */
export function editorAssistTurnState(record: EditorAssistTurnRecord): EditorAssistTurnState {
    if (record.outcome !== 'changed' || !record.changes.length) return 'none';
    const reverted = record.undo?.reverted.length ?? 0;
    if (!reverted) return 'applied';
    return reverted >= record.changes.length ? 'undone' : 'partly_undone';
}

function replayTurns(
    exchanges: readonly AssistExchange[],
    records: Readonly<Record<string, EditorAssistTurnRecord>>,
    excludeId: string,
): EditorAssistReplayTurn[] {
    const turns: EditorAssistReplayTurn[] = [];
    for (const exchange of exchanges) {
        if (exchange.status !== 'done' || exchange.id === excludeId) continue;
        const record = records[exchange.id];
        const state = record ? editorAssistTurnState(record) : 'none';
        turns.push({
            instruction: record?.instruction ?? exchange.text,
            reply: record?.reply ?? exchange.reply ?? '',
            state,
            changes: state === 'none' || !record ? [] : record.changes.map((change) => change.label),
        });
    }
    return turns;
}

interface LiveState {
    available: boolean;
    key: string | null;
    scope: EditorAssistScope;
    kind: EditorAssistKind;
    buildView: UseEditorAssistOptions['buildView'];
    apply: UseEditorAssistOptions['apply'];
    onJump: UseEditorAssistOptions['onJump'];
}

export function useEditorAssist({
    kind, available, scope, recordKey, blocked, buildView, apply, onJump,
}: UseEditorAssistOptions): EditorAssist {
    // One thread per editor visit: a reopened editor starts a fresh conversation, so an old turn's
    // Undo can never reach a draft it didn't change.
    const [visit] = useState(() => makeSubmissionId());
    const key = available ? `${kind}:${scope.kind}:${scope.id ?? ''}:${recordKey}:${visit}` : null;
    const turns = useEditorAssistStore((state) => state.turns);
    const retryUntil = useEditorAssistStore((state) => state.retryUntil);
    const [waitSeconds, setWaitSeconds] = useState(0);

    const live = useRef<LiveState>({ available, key, scope, kind, buildView, apply, onJump });
    live.current = { available, key, scope, kind, buildView, apply, onJump };

    const send = useCallback(async (request: AssistSendRequest): Promise<AssistSendResult> => {
        const sent = live.current;
        if (!sent.available || !sent.key) return { ok: false, error: UNAVAILABLE_MESSAGE };
        const view = sent.buildView();
        const records = useEditorAssistStore.getState().turns;
        const thread = selectAssistThread(useAssistThreadStore.getState(), sent.key);
        let body: EditorAssistRequest;
        try {
            body = buildEditorAssistRequest({
                scope: sent.scope,
                submissionId: request.submissionId,
                instruction: request.text,
                view,
                conversation: editorAssistConversation(replayTurns(thread?.exchanges ?? [], records, request.submissionId)),
            });
        } catch (problem) {
            if (problem instanceof EditorAssistRequestError) return { ok: false, error: problem.message };
            throw problem;
        }

        const result = await postEditorAssist(sent.kind, body, request.signal);
        if (request.signal.aborted) return ABORTED;
        if (!result.ok) {
            if (result.aborted) return ABORTED;
            const { failure } = result;
            if (failure.retryAfterSeconds) {
                useEditorAssistStore.getState().waitUntil(Date.now() + failure.retryAfterSeconds * 1000);
            }
            return { ok: false, error: failure.message };
        }

        // The editor is locked while a turn runs, but the answer is still checked against the
        // draft it was sent with: an answer about another draft is never applied.
        const now = live.current;
        if (!now.available || now.key !== sent.key) return { ok: false, error: EDITOR_ASSIST_STALE_MESSAGE };
        const currentView = now.buildView();
        if (editorAssistKey(currentView.values) !== editorAssistKey(view.values)) {
            return { ok: false, error: EDITOR_ASSIST_STALE_MESSAGE };
        }

        const { response } = result;
        const store = useEditorAssistStore.getState();
        const base = {
            threadKey: sent.key,
            instruction: body.instruction,
            reply: response.reply,
            before: currentView.values,
            undoSequence: 0,
        };
        const explained: EditorAssistTurnRecord = {
            ...base, outcome: 'explained', changes: [], entries: [], newItems: [], warnings: [],
        };
        if (response.outcome !== 'changed' || !response.candidate) {
            store.record(request.submissionId, explained);
            return { ok: true, reply: response.reply };
        }
        const patch = editorAssistPatch(currentView, currentView.values, response.candidate.values);
        const newItems = response.candidate.newItems;
        if (!Object.keys(patch).length && !newItems.length) {
            store.record(request.submissionId, explained);
            return { ok: true, reply: response.reply };
        }
        const after = now.apply(patch, newItems);
        if (!after) return { ok: false, error: NOT_APPLIED_MESSAGE };
        const paths = new Set([...Object.keys(patch), ...Object.keys(currentView.values), ...Object.keys(after)]);
        const entries = [...paths]
            .map((path) => ({ path, before: currentView.values[path], after: after[path] }))
            .filter((entry) => !sameEditorAssistValue(entry.before, entry.after));
        // Labelled against the values after the change, so a new type's fields are known.
        const changes = editorAssistTurnChanges({ ...currentView, values: after }, entries);
        store.record(request.submissionId, {
            ...base,
            outcome: changes.length ? 'changed' : 'explained',
            changes,
            entries,
            newItems,
            warnings: changes.length ? response.warnings : [],
        });
        return { ok: true, reply: response.reply };
    }, []);

    // Closing the editor, or losing Ask AI, stops waiting for its answer. The server writes
    // nothing, so nothing is left half done. Declared before the thread, so this cleanup runs
    // while the thread is still held.
    useEffect(() => {
        if (!key) return undefined;
        return () => {
            const running = selectAssistThread(useAssistThreadStore.getState(), key)?.exchanges
                .find((exchange) => exchange.status === 'pending');
            if (running) cancelAssistExchange(key, running.id);
        };
    }, [key]);

    const thread = useAssistThread({
        key,
        conversationId: EDITOR_ASSIST_CONVERSATIONS[kind],
        mode: 'local',
        maxLength: EDITOR_ASSIST_INSTRUCTION_LIMIT,
        send,
        countCodePoints: true,
        retain: true,
    });
    const pending = thread.pending;

    // The wait the assistant asked for, in whole seconds, ticking down.
    useEffect(() => {
        let timer = 0;
        const tick = () => {
            const left = retryUntil - Date.now();
            setWaitSeconds(left > 0 ? Math.ceil(left / 1000) : 0);
            if (left > 0) timer = window.setTimeout(tick, left % 1000 || 1000);
        };
        tick();
        return () => window.clearTimeout(timer);
    }, [retryUntil]);

    const busy = !available || blocked || waitSeconds > 0;

    const changedSections = useMemo(() => {
        const sections = new Set<string>();
        if (!key) return sections;
        for (const record of Object.values(turns)) {
            if (record.threadKey !== key) continue;
            const reverted = new Set(record.undo?.reverted ?? []);
            for (const change of record.changes) {
                if (change.section && !reverted.has(change.path)) sections.add(change.section);
            }
        }
        return sections;
    }, [turns, key]);

    const quickAction = (text: string) => !busy && !pending && thread.sendText(text);

    const undo = useCallback((turnId: string) => {
        const current = live.current;
        if (!current.key) return;
        if (selectAssistThread(useAssistThreadStore.getState(), current.key)?.exchanges
            .some((exchange) => exchange.status === 'pending')) return;
        const record = useEditorAssistStore.getState().turns[turnId];
        if (!record || record.threadKey !== current.key || record.undo) return;
        const view = current.buildView();
        const plan = editorAssistUndoPlan(record.entries, record.before, view.values, view.variant?.path);
        if (Object.keys(plan.patch).length && !current.apply(plan.patch, [])) return;
        // A path already back at its old value counts as reverted: the turn has nothing left there.
        const skipped = new Set(plan.skipped);
        const reverted = record.changes.map((change) => change.path).filter((path) => !skipped.has(path));
        useEditorAssistStore.getState().update(turnId, (item) => ({
            ...item,
            undo: { reverted, skipped: plan.skipped },
            undoSequence: item.undoSequence + 1,
        }));
    }, []);

    const jump = useCallback((section: string | null) => {
        if (section) live.current.onJump(section);
    }, []);

    const cancel = () => {
        if (pending) thread.cancel(pending.id);
    };

    return {
        kind,
        available,
        thread,
        pending,
        busy,
        waitSeconds,
        turns,
        changedSections,
        quickAction,
        undo,
        jump,
        cancel,
    };
}
