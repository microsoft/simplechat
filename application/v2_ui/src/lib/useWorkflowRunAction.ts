// useWorkflowRunAction.ts
// Cancel or Retry one run a chat started, from its row on the run card or its delivered note.
//
// A run has one action under way at most, wherever it was asked for: while the card's Cancel is
// waiting on the server, the note's Retry for the same run waits too. After every outcome the
// tracker is told the run may have changed and the chat's runs are read again, so what shows next
// comes from the server, never from the click. The outcome's sentence stays until the run's status
// changes, so "Retry requested." gives way once the run has moved on.

import { useCallback, useEffect, useRef, useState } from 'react';
import { create } from 'zustand';
import {
    cancelWorkflowRun,
    retryWorkflowRun,
    WORKFLOW_CANCEL_FAILED_TEXT,
    WORKFLOW_RETRY_FAILED_TEXT,
} from './workflowRunActions';
import { kickWorkflowRunTracker, requestWorkflowConversationRuns } from './useWorkflowRunTracker';
import type { TrackedWorkflowRun } from './workflowRunTracker';
import { useWorkflowRunTrackerStore } from '../stores/workflowRunTrackerStore';

export type WorkflowRunActionKind = 'cancel' | 'retry';

interface PendingRunActions {
    /** The action under way for each run, by run id. */
    pending: Readonly<Record<string, WorkflowRunActionKind>>;
}

const usePendingRunActions = create<PendingRunActions>(() => ({ pending: {} }));

function claimRun(runId: string, kind: WorkflowRunActionKind): boolean {
    const { pending } = usePendingRunActions.getState();
    if (pending[runId]) {
        return false;
    }
    usePendingRunActions.setState({ pending: { ...pending, [runId]: kind } });
    return true;
}

function releaseRun(runId: string): void {
    const { pending } = usePendingRunActions.getState();
    if (!pending[runId]) {
        return;
    }
    const next = { ...pending };
    delete next[runId];
    usePendingRunActions.setState({ pending: next });
}

/** What the tracker last said about a run, reduced to whether its status has changed. */
function runStatusKey(tracked: TrackedWorkflowRun | undefined): string {
    if (!tracked) return 'none';
    if (tracked.retired) return 'retired';
    return tracked.row.kind === 'status' ? tracked.row.status : 'unavailable';
}

export interface WorkflowRunActionState {
    /** The action under way for this run, from here or anywhere else, or null. */
    pending: WorkflowRunActionKind | null;
    /** The sentence the last outcome asked for here, or empty. */
    outcome: string;
    run: (kind: WorkflowRunActionKind) => Promise<void>;
}

export function useWorkflowRunAction(conversationId: string, workflowId: string, runId: string): WorkflowRunActionState {
    const pending = usePendingRunActions((state) => state.pending[runId] ?? null);
    const statusKey = useWorkflowRunTrackerStore((state) => runStatusKey(state.snapshot.runs[runId]));
    // The status the run had when the outcome was set, so the outcome clears once it changes.
    const [outcome, setOutcome] = useState<{ text: string; statusKey: string } | null>(null);
    const mounted = useRef(true);

    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
        };
    }, []);

    useEffect(() => {
        setOutcome((previous) => (previous && previous.statusKey !== statusKey ? null : previous));
    }, [statusKey]);

    const run = useCallback(async (kind: WorkflowRunActionKind) => {
        if (!claimRun(runId, kind)) {
            return;
        }
        setOutcome(null);
        let text: string;
        try {
            const target = { workflowId, runId };
            text = (kind === 'cancel' ? await cancelWorkflowRun(target) : await retryWorkflowRun(target)).text;
        } catch {
            text = kind === 'cancel' ? WORKFLOW_CANCEL_FAILED_TEXT : WORKFLOW_RETRY_FAILED_TEXT;
        }
        try {
            kickWorkflowRunTracker();
            await requestWorkflowConversationRuns(conversationId, { force: true });
        } catch {
            /* A failed read shows on the card; the outcome stands either way. */
        } finally {
            releaseRun(runId);
        }
        if (mounted.current) {
            setOutcome({
                text,
                statusKey: runStatusKey(useWorkflowRunTrackerStore.getState().snapshot.runs[runId]),
            });
        }
    }, [conversationId, workflowId, runId]);

    return { pending, outcome: outcome?.text ?? '', run };
}
