// workflowRunTrackerStore.ts
// What the tab's one workflow run tracker knows, for the components that show it.
//
// The engine in lib/workflowRunTracker.ts owns the requests and the state; this store mirrors its
// snapshot so components re-render when it changes. Nothing here sends a request. The run card and
// the delivered-message footers ask for a chat's runs through useWorkflowRunTracker, and the chat
// list's running tag reads only what is already here.
//
// The selectors are plain functions of a snapshot, so they can be tested without React. Components
// select the snapshot itself and derive arrays from it with `useMemo`, so a selector that builds a
// new array never makes the store hook re-render on its own.

import { create } from 'zustand';
import {
    isTrackedRunInFlight,
    type TrackedWorkflowRun,
    type WorkflowRunConversationRead,
    type WorkflowRunTrackerSnapshot,
} from '../lib/workflowRunTracker';

export const EMPTY_WORKFLOW_RUN_TRACKER_SNAPSHOT: WorkflowRunTrackerSnapshot = Object.freeze({
    running: false,
    halted: false,
    available: null,
    runs: Object.freeze({}),
    globalCheckedAt: null,
    globalError: false,
    conversations: Object.freeze({}),
});

const NO_CONVERSATION_READ: WorkflowRunConversationRead = Object.freeze({ checkedAt: null, reading: false, error: null });

interface WorkflowRunTrackerState {
    snapshot: WorkflowRunTrackerSnapshot;
    /** Replace the mirror with the engine's newest snapshot. */
    publish: (snapshot: WorkflowRunTrackerSnapshot) => void;
    /** Forget everything, for tests. */
    reset: () => void;
}

export const useWorkflowRunTrackerStore = create<WorkflowRunTrackerState>((set) => ({
    snapshot: EMPTY_WORKFLOW_RUN_TRACKER_SNAPSHOT,
    publish: (snapshot) => set({ snapshot }),
    reset: () => set({ snapshot: EMPTY_WORKFLOW_RUN_TRACKER_SNAPSHOT }),
}));

function byRequestedAt(left: TrackedWorkflowRun, right: TrackedWorkflowRun): number {
    const a = left.row.requested_at ?? '';
    const b = right.row.requested_at ?? '';
    if (a !== b) {
        return a < b ? -1 : 1;
    }
    return left.row.run_id < right.row.run_id ? -1 : left.row.run_id > right.row.run_id ? 1 : 0;
}

/** A chat's runs that are still going or still being posted, oldest request first. */
export function workflowRunsInFlight(
    snapshot: WorkflowRunTrackerSnapshot,
    conversationId: string | null | undefined,
): TrackedWorkflowRun[] {
    if (!conversationId) {
        return [];
    }
    return Object.values(snapshot.runs)
        .filter((tracked) => tracked.row.conversation_id === conversationId && isTrackedRunInFlight(tracked))
        .sort(byRequestedAt);
}

/**
 * The chat list's running tag: "Running Weekly digest", "Running 2 workflows", or empty while
 * nothing the chat started is in flight. The name is user-authored and only ever rendered as text.
 */
export function workflowRunningLabel(
    snapshot: WorkflowRunTrackerSnapshot,
    conversationId: string | null | undefined,
): string {
    const runs = workflowRunsInFlight(snapshot, conversationId);
    if (runs.length === 0) {
        return '';
    }
    return runs.length === 1 ? `Running ${runs[0].row.workflow_name}` : `Running ${runs.length} workflows`;
}

/**
 * The chat list tag's label: the running label while the tracker is reading, and empty once it has
 * stopped or halted, when what it last knew may no longer be true.
 */
export function workflowRunningTagLabel(
    snapshot: WorkflowRunTrackerSnapshot,
    conversationId: string | null | undefined,
): string {
    return snapshot.running && !snapshot.halted ? workflowRunningLabel(snapshot, conversationId) : '';
}

/** The runs one plan answer started, oldest request first. */
export function workflowRunsForAnswer(
    snapshot: WorkflowRunTrackerSnapshot,
    conversationId: string | null | undefined,
    orchestrationRunId: string | null | undefined,
): TrackedWorkflowRun[] {
    if (!conversationId || !orchestrationRunId) {
        return [];
    }
    return Object.values(snapshot.runs)
        .filter((tracked) =>
            tracked.row.conversation_id === conversationId && tracked.row.orchestration_run_id === orchestrationRunId)
        .sort(byRequestedAt);
}

/** The run one step of a plan answer started, as the plan's own run list names it. */
export interface WorkflowRunAnswerStep {
    stepId: string;
    workflowId: string;
    runId: string;
}

/**
 * The tracker's row for the run one step of a plan answer started: the same run, in the same chat,
 * started by the same plan run and step, of the same workflow. Undefined when the tracker hasn't
 * read it or anything disagrees, so the card keeps the step's static link instead of guessing.
 */
export function workflowRunForAnswerStep(
    snapshot: WorkflowRunTrackerSnapshot,
    conversationId: string | null | undefined,
    orchestrationRunId: string | null | undefined,
    step: WorkflowRunAnswerStep,
): TrackedWorkflowRun | undefined {
    if (!conversationId || !orchestrationRunId) {
        return undefined;
    }
    const tracked = snapshot.runs[step.runId];
    if (
        !tracked
        || tracked.row.run_id !== step.runId
        || tracked.row.conversation_id !== conversationId
        || tracked.row.orchestration_run_id !== orchestrationRunId
        || tracked.row.step_id !== step.stepId
        || tracked.row.workflow_id !== step.workflowId
    ) {
        return undefined;
    }
    return tracked;
}

/** What the tracker last knew about one run, or undefined. */
export function trackedWorkflowRun(
    snapshot: WorkflowRunTrackerSnapshot,
    runId: string | null | undefined,
): TrackedWorkflowRun | undefined {
    return runId ? snapshot.runs[runId] : undefined;
}

/** The state of a chat's own reads. */
export function workflowRunConversationRead(
    snapshot: WorkflowRunTrackerSnapshot,
    conversationId: string | null | undefined,
): WorkflowRunConversationRead {
    return (conversationId && snapshot.conversations[conversationId]) || NO_CONVERSATION_READ;
}

/**
 * When a chat's runs were last read: the newer of its own read and a complete read of every chat's
 * runs, which lists each run still in flight. Null until either has succeeded.
 */
export function workflowRunsCheckedAt(
    snapshot: WorkflowRunTrackerSnapshot,
    conversationId: string | null | undefined,
): string | null {
    const own = workflowRunConversationRead(snapshot, conversationId).checkedAt;
    const global = snapshot.globalCheckedAt;
    if (own === null) {
        return global;
    }
    if (global === null) {
        return own;
    }
    return own > global ? own : global;
}
