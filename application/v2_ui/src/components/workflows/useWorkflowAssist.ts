// useWorkflowAssist.ts
// The workflow editor's Ask AI tab: its thread, the requests it sends to
// POST /api/user/workflows/assist, and what it does with each answer.
//
// The thread is the shared assist thread in local mode, so the conversation lasts only as long as
// the page. Before anything is applied, an answer is checked against the draft it was sent with,
// and the candidate is diffed here rather than trusting the change list that came with it. The
// change then goes through the authoring session's applyAssist, so it is highlighted, undoable and
// reviewed before saving like every AI change.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    cancelAssistExchange, makeSubmissionId, useAssistThread,
    type AssistExchange, type AssistSendRequest, type AssistSendResult, type AssistThreadController,
} from '../../lib/assistThread';
import {
    STALE_DRAFT_MESSAGE, WORKFLOW_ASSIST_INSTRUCTION_LIMIT, WorkflowAssistRequestError, assistDraftUnchanged,
    browserTimeZone, buildWorkflowAssistRequest, postWorkflowAssist, rebaseAssistCandidate, requestDraftInstructions,
    verifyAssistChanges, withDraftedInstructions, workflowAssistReplay, workflowAssistTurnLabel, workflowFlowNodeIds,
    type WorkflowAssistApply, type WorkflowAssistHistoryView, type WorkflowAssistRequest, type WorkflowAssistTurnRecord,
} from '../../lib/workflowAssist';
import { workflowTaskKey, type WorkflowChange } from '../../lib/workflowChangeTracking';
import { workflowScheduleTimezones, type WorkflowDefinition, type WorkflowEditorOptions } from '../../lib/workflowEditor';
import { flowTaskNodeId } from '../../lib/workflowFlow';
import { selectAssistThread, useAssistThreadStore } from '../../stores/assistThreadStore';
import { useWorkflowAssistStore } from '../../stores/workflowAssistStore';
import type { WorkflowAuthoringSession, useWorkflowAuthoringHistory } from './WorkflowAuthoringHistory';
import type { WorkflowTaskDraftWithAi } from './WorkflowTaskFields';

/** The thread's conversation. The editor has no chat of its own, so every workflow thread shares this one. */
export const WORKFLOW_ASSIST_CONVERSATION = 'workflow-editor';

const UNAVAILABLE_MESSAGE = "Ask AI isn't available for this workflow.";
const EDITOR_CHANGED_MESSAGE = 'Nothing was added because the editor changed while drafting.';
const TASK_CHANGED_MESSAGE = 'The task changed while drafting, so nothing was added.';
const NEEDS_NAME_MESSAGE = 'Name the workflow or this task first, so the assistant knows what to draft.';
const ABORTED: AssistSendResult = { ok: false, error: '', aborted: true };

type AuthoringHistory = ReturnType<typeof useWorkflowAuthoringHistory>;

const epochs = new WeakMap<object, string>();

/**
 * The editing session a turn belongs to: one for each version the editor opened. A turn from an
 * earlier session can no longer be undone, because its history went with that session.
 */
export function workflowAssistEpoch(baseline: WorkflowDefinition): string {
    let epoch = epochs.get(baseline);
    if (!epoch) {
        epoch = makeSubmissionId();
        epochs.set(baseline, epoch);
    }
    return epoch;
}

/** The one task a turn is about. */
export interface WorkflowAssistFocus {
    readonly taskId: string;
    /** What the request sends: the task, or its flow block in a structured draft. */
    readonly value: string;
    readonly label: string;
}

export interface UseWorkflowAssistOptions {
    /** Ask AI is offered: the setting is on for this user, the workflow is personal, and the editor can write. */
    readonly available: boolean;
    readonly history: AuthoringHistory;
    readonly options: WorkflowEditorOptions;
    /** The saved workflow the editor opened, or null for a new or proposal draft. */
    readonly workflowId: string | null;
    /** The editor cannot take a change now: it is saving, or a confirmation or flow command is pending. */
    readonly blocked: boolean;
    /** Show a change in the editor. */
    readonly onJump: (change: Pick<WorkflowChange, 'key' | 'target'>) => void;
}

export interface WorkflowAssist {
    readonly available: boolean;
    readonly thread: AssistThreadController;
    /** The turn that is running. The editor is locked until it ends. */
    readonly pending: AssistExchange | null;
    /** Nothing new can be sent right now. */
    readonly busy: boolean;
    /** Seconds before the assistant takes another request, after a 429 or a throttled 503. */
    readonly waitSeconds: number;
    readonly epoch: string;
    readonly turns: Readonly<Record<string, WorkflowAssistTurnRecord>>;
    readonly historyView: WorkflowAssistHistoryView;
    readonly focus: WorkflowAssistFocus | null;
    readonly setFocusTask: (taskId: string | null) => void;
    /** The saved workflow changed after the editor opened; reloading it lets Ask AI work again. */
    readonly reloadOffered: boolean;
    readonly quickAction: (text: string) => boolean;
    readonly undo: (turnId: string) => void;
    /** Show a change or warning target in the editor. A flow block is used only while it exists. */
    readonly jump: (target: WorkflowAssistJumpTarget) => void;
    readonly cancel: () => void;
    readonly draftWithAi: (taskId: string) => WorkflowTaskDraftWithAi;
}

/** Where Jump to goes: an editor change key, the field to focus, and the flow block holding it. */
export interface WorkflowAssistJumpTarget {
    readonly key: string;
    readonly focusKey: string;
    readonly nodeId?: string;
}

interface LiveState {
    session: WorkflowAuthoringSession;
    available: boolean;
    options: WorkflowEditorOptions;
    key: string | null;
    focus: string | null;
    onJump: UseWorkflowAssistOptions['onJump'];
}

function applyStatus(status: string): WorkflowAssistApply {
    return status === 'applied' ? 'applied' : status === 'confirmation_required' ? 'pending'
        : status === 'noop' ? 'noop' : 'rejected';
}

export function useWorkflowAssist({
    available, history, options, workflowId, blocked, onJump,
}: UseWorkflowAssistOptions): WorkflowAssist {
    const { session, draft } = history;
    const [newDraftKey] = useState(() => `workflow:new:${makeSubmissionId()}`);
    const key = available ? (workflowId ? `workflow:personal:${workflowId}` : newDraftKey) : null;
    const epoch = workflowAssistEpoch(history.baseline);
    const turns = useWorkflowAssistStore((state) => state.turns);
    const retryUntil = useWorkflowAssistStore((state) => state.retryUntil);
    const [waitSeconds, setWaitSeconds] = useState(0);
    const [focusTaskId, setFocusTaskId] = useState<string | null>(null);
    const [reloadOffered, setReloadOffered] = useState(false);
    const [drafting, setDrafting] = useState<string | null>(null);
    const [draftMessages, setDraftMessages] = useState<Readonly<Record<string, string>>>({});
    const draftController = useRef<AbortController | null>(null);

    const focusIndex = focusTaskId ? draft.tasks.findIndex((task) => task.id === focusTaskId) : -1;
    const focusTask = focusIndex >= 0 ? draft.tasks[focusIndex] : null;
    const focus = useMemo<WorkflowAssistFocus | null>(() => focusTask ? {
        taskId: focusTask.id,
        value: draft.definition_version === 3 ? flowTaskNodeId(draft, focusTask.id) || focusTask.id : focusTask.id,
        label: focusTask.name.trim() || `Task ${focusIndex + 1}`,
    } : null, [focusTask, focusIndex, draft]);

    // A removed task takes its focus with it.
    useEffect(() => {
        if (focusTaskId && !focusTask) setFocusTaskId(null);
    }, [focusTaskId, focusTask]);

    const live = useRef<LiveState>({ session, available, options, key, focus: focus?.value ?? null, onJump });
    live.current = { session, available, options, key, focus: focus?.value ?? null, onJump };

    const send = useCallback(async (request: AssistSendRequest): Promise<AssistSendResult> => {
        const sent = live.current;
        const sentSession = sent.session;
        if (!sent.available || !sent.key || !sentSession.active) return { ok: false, error: UNAVAILABLE_MESSAGE };
        sentSession.closeGroup();
        const view = sentSession.getSnapshot();
        const sentDraft = sentSession.draft;
        const sentBaseline = view.baseline;
        const records = useWorkflowAssistStore.getState().turns;
        const thread = selectAssistThread(useAssistThreadStore.getState(), sent.key);
        let body: WorkflowAssistRequest;
        try {
            body = buildWorkflowAssistRequest({
                submissionId: request.submissionId,
                instruction: request.text,
                baseline: sentBaseline,
                draft: sentDraft,
                contextItems: request.draft.contextItems,
                conversation: workflowAssistReplay(thread?.exchanges ?? [], (id) => records[id], view,
                    workflowAssistEpoch(sentBaseline), request.submissionId),
                focus: sent.focus,
                timeZone: browserTimeZone(),
                timeZones: workflowScheduleTimezones(sent.options),
            });
        } catch (problem) {
            if (problem instanceof WorkflowAssistRequestError) return { ok: false, error: problem.message };
            throw problem;
        }

        const result = await postWorkflowAssist(body, request.signal);
        if (request.signal.aborted) return ABORTED;
        if (!result.ok) {
            if (result.aborted) return ABORTED;
            const { failure } = result;
            if (failure.retryAfterSeconds) {
                useWorkflowAssistStore.getState().waitUntil(Date.now() + failure.retryAfterSeconds * 1000);
            }
            if (failure.reload) setReloadOffered(true);
            return { ok: false, error: failure.message };
        }

        // The editor is locked while a turn runs, but the answer is still checked against the draft
        // it was sent with: an answer about another draft is never applied.
        const now = live.current;
        if (now.session !== sentSession || !sentSession.active || !now.available || now.key !== sent.key
            || sentSession.getSnapshot().baseline !== sentBaseline) {
            return { ok: false, error: STALE_DRAFT_MESSAGE };
        }
        sentSession.closeGroup();
        const current = sentSession.draft;
        if (!assistDraftUnchanged(sentDraft, current)) return { ok: false, error: STALE_DRAFT_MESSAGE };

        const { response } = result;
        const store = useWorkflowAssistStore.getState();
        const turnId = request.submissionId;
        const record = {
            threadKey: sent.key,
            epoch: workflowAssistEpoch(sentBaseline),
            instruction: body.instruction,
            reply: response.reply,
            warnings: response.warnings,
            contextDocuments: response.contextDocuments,
            undoSequence: 0,
        };
        if (response.outcome !== 'changed' || !response.candidate) {
            store.record(turnId, { ...record, outcome: response.outcome, changes: [], apply: 'none' });
            return { ok: true, reply: response.reply };
        }
        const rebased = rebaseAssistCandidate(current, response.candidate);
        const verified = verifyAssistChanges(current, rebased, response.changes);
        if (!verified.changes.length) {
            store.record(turnId, { ...record, outcome: 'explained', changes: [], apply: 'noop' });
            return { ok: true, reply: response.reply };
        }
        const applied = sentSession.applyAssist(rebased, {
            turnId, label: workflowAssistTurnLabel('Ask AI', body.instruction),
        });
        const apply = applyStatus(applied.status);
        store.record(turnId, {
            ...record,
            outcome: apply === 'noop' ? 'explained' : 'changed',
            changes: apply === 'noop' ? [] : verified.changes,
            apply,
            ...(applied.status === 'rejected' ? { applyMessage: applied.message } : {}),
        });
        return { ok: true, reply: response.reply };
    }, []);

    const thread = useAssistThread({
        key,
        conversationId: WORKFLOW_ASSIST_CONVERSATION,
        mode: 'local',
        maxLength: WORKFLOW_ASSIST_INSTRUCTION_LIMIT,
        send,
        countCodePoints: true,
        retain: true,
    });
    const pending = thread.pending;

    // Closing the editor, or losing Ask AI, stops waiting for its answer. The server writes nothing,
    // so nothing is left half done.
    useEffect(() => {
        if (!key) return undefined;
        return () => {
            const running = selectAssistThread(useAssistThreadStore.getState(), key)?.exchanges
                .find((exchange) => exchange.status === 'pending');
            if (running) cancelAssistExchange(key, running.id);
        };
    }, [key]);

    useEffect(() => () => draftController.current?.abort(), []);

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

    const busy = !available || blocked || waitSeconds > 0 || drafting !== null;
    const historyView = useMemo<WorkflowAssistHistoryView>(() => ({
        steps: history.steps, attribution: history.attribution, pending: history.pending,
    }), [history.steps, history.attribution, history.pending]);

    const setDraftMessage = useCallback((taskId: string, message: string) => {
        setDraftMessages((current) => {
            if ((current[taskId] ?? '') === message) return current;
            const next = { ...current };
            if (message) next[taskId] = message;
            else delete next[taskId];
            return next;
        });
    }, []);

    const draftInstructions = useCallback(async (taskId: string) => {
        const start = live.current;
        if (!start.available || draftController.current || !start.session.active) return;
        const workflow = start.session.draft;
        const index = workflow.tasks.findIndex((task) => task.id === taskId);
        const task = workflow.tasks[index];
        if (!task || task.instructions.trim()) return;
        const name = task.name.trim();
        const label = name || `Task ${index + 1}`;
        if (!workflow.name.trim() && !workflow.description.trim() && (!name || /^Task \d+$/.test(name))) {
            setDraftMessage(taskId, NEEDS_NAME_MESSAGE);
            return;
        }
        const controller = new AbortController();
        draftController.current = controller;
        setDrafting(taskId);
        setDraftMessage(taskId, '');
        let refocus = true;
        try {
            const instructions = await requestDraftInstructions(workflow, name, controller.signal);
            if (controller.signal.aborted) return;
            const now = live.current;
            if (now.session !== start.session || !now.session.active || !now.available) {
                setDraftMessage(taskId, EDITOR_CHANGED_MESSAGE);
                return;
            }
            now.session.closeGroup();
            const candidate = withDraftedInstructions(now.session.draft, taskId, instructions);
            if (!candidate) {
                setDraftMessage(taskId, TASK_CHANGED_MESSAGE);
                return;
            }
            const result = now.session.applyAssist(candidate, {
                turnId: makeSubmissionId(), label: workflowAssistTurnLabel('Draft with AI', label),
            });
            if (result.status === 'applied') {
                refocus = false;
                const focusKey = workflowTaskKey(taskId, 'instructions');
                const nodeId = candidate.definition_version === 3 ? flowTaskNodeId(candidate, taskId) : '';
                now.onJump({ key: focusKey, target: { focusKey, ...(nodeId ? { nodeId } : {}) } });
            } else if (result.status === 'confirmation_required') {
                refocus = false;
                setDraftMessage(taskId, 'Confirm to add the drafted instructions.');
            } else if (result.status === 'rejected') {
                setDraftMessage(taskId, `Nothing was added: ${result.message}`);
            }
        } catch (problem) {
            if (controller.signal.aborted) return;
            setDraftMessage(taskId, problem instanceof Error && problem.message ? problem.message
                : "Couldn't draft instructions. Try again.");
        } finally {
            if (draftController.current === controller) {
                draftController.current = null;
                setDrafting(null);
                // The button was disabled while it waited, which drops focus; put it back.
                if (refocus && !controller.signal.aborted) {
                    requestAnimationFrame(() => {
                        if (document.activeElement && document.activeElement !== document.body) return;
                        document.querySelector<HTMLElement>(`[data-workflow-draft-ai="${CSS.escape(taskId)}"]`)?.focus();
                    });
                }
            }
        }
    }, [setDraftMessage]);

    const draftWithAi = (taskId: string): WorkflowTaskDraftWithAi => ({
        onDraft: () => { void draftInstructions(taskId); },
        pending: drafting === taskId,
        disabled: !available || blocked || drafting !== null || Boolean(pending),
        message: draftMessages[taskId] || undefined,
    });

    const quickAction = (text: string) => !busy && !pending && thread.sendText(text);

    const undo = useCallback((turnId: string) => {
        const { session: current, key: threadKey } = live.current;
        // The editor is locked while a turn runs; its answer is checked against the draft it was sent with.
        if (threadKey && selectAssistThread(useAssistThreadStore.getState(), threadKey)?.exchanges
            .some((exchange) => exchange.status === 'pending')) return;
        const result = current.revertTurn(turnId);
        useWorkflowAssistStore.getState().update(turnId, (record) => ({
            ...record, undo: result, undoSequence: record.undoSequence + 1,
        }));
    }, []);

    const jump = useCallback(({ key: changeKey, focusKey, nodeId }: WorkflowAssistJumpTarget) => {
        const { session: current, onJump: show } = live.current;
        const node = nodeId && workflowFlowNodeIds(current.draft).has(nodeId) ? nodeId : undefined;
        show({ key: changeKey, target: { focusKey, ...(node ? { nodeId: node } : {}) } });
    }, []);

    const cancel = () => {
        if (pending) thread.cancel(pending.id);
    };

    return {
        available,
        thread,
        pending,
        busy,
        waitSeconds,
        epoch,
        turns,
        historyView,
        focus,
        setFocusTask: setFocusTaskId,
        reloadOffered,
        quickAction,
        undo,
        jump,
        cancel,
        draftWithAi,
    };
}
