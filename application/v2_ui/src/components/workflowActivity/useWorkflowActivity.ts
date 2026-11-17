// useWorkflowActivity.ts
// The Workflow Activity page's state: read the snapshot, hold the stream open while the run is
// live, and cancel the run.
//
// One snapshot object comes from `GET .../workflows/activity` and the same object comes again, whole,
// on every frame of the stream, so every source goes through one `apply`. A response or a frame that
// arrives for an address the page has since left is dropped, and a read that fails after one has
// succeeded keeps what was on screen and says so, where the classic page replaced the whole view
// with its "unavailable" state.
//
// Everything below that runs later than the render that made it -- a cancel's answer, a card's
// update, the stream's frames -- holds the address it was made for and checks it is still the page's
// before it does anything. That includes the readers: `load` and `refresh` do nothing for an address
// the page has left, because starting a read first stops the one in flight, and the one in flight
// would by then be the new address's.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../../lib/apiClient';
import { subscribeToWorkflowActivity } from '../../lib/workflowActivityStream';
import {
    describeWorkflowActivityFailure,
    hasWorkflowActivityIdentifier,
    workflowActivityApiUrl,
    workflowActivityQueryKey,
    workflowActivityScope,
    type WorkflowActivityQuery,
    type WorkflowActivityQueryRead,
} from '../../lib/workflowActivity';
import {
    activityCancel,
    INITIAL_ACTIVITY_SELECTION,
    normalizeWorkflowActivitySnapshot,
    pendingActionMoved,
    pickActivity,
    resolveActivitySelection,
    shouldListenForUpdates,
    type ActivitySelection,
    type WorkflowActivitySnapshot,
} from '../../lib/workflowActivitySnapshot';
import { cancelScopedWorkflowRun } from '../../lib/workflowEditor';
import type { PendingAction } from '../../lib/approvalsApi';

export const WORKFLOW_ACTIVITY_CANCEL_FAILED = 'Unable to cancel the workflow run.';

export type WorkflowActivityPhase = 'invalid' | 'empty' | 'loading' | 'ready' | 'error';

export interface WorkflowActivityState {
    phase: WorkflowActivityPhase;
    query: WorkflowActivityQuery | null;
    snapshot: WorkflowActivitySnapshot | null;
    /** Why the page cannot be shown: a refused link, or a read that failed with nothing to fall back on. */
    error: string;
    /** A problem with something the page did after it was showing: a refresh, a cancel, the stream. */
    notice: string;
    selection: ActivitySelection;
    /** Counts each snapshot applied, so the timeline can follow a new one even if it equals the last. */
    applied: number;
    /** Counts each Refresh, which also puts the timeline back on its newest card. */
    refreshes: number;
    loading: boolean;
    cancelling: boolean;
    refresh: () => void;
    reload: () => Promise<void>;
    cancel: () => Promise<void>;
    selectActivity: (id: string) => void;
    /** The saved Microsoft 365 action a card shows changed: read the snapshot again if the page is behind it. */
    pendingActionChanged: (action: PendingAction) => void;
}

export function useWorkflowActivity(read: WorkflowActivityQueryRead): WorkflowActivityState {
    const query = read.ok ? read.query : null;
    const refused = read.ok ? '' : read.reason;
    const key = query ? workflowActivityQueryKey(query) : '';
    const named = query ? hasWorkflowActivityIdentifier(query) : false;

    const [loaded, setLoaded] = useState<{ key: string; snapshot: WorkflowActivitySnapshot } | null>(null);
    const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
    const [problem, setProblem] = useState<{ key: string; message: string } | null>(null);
    const [selection, setSelection] = useState<ActivitySelection>(INITIAL_ACTIVITY_SELECTION);
    const [applied, setApplied] = useState(0);
    const [refreshes, setRefreshes] = useState(0);
    const [loading, setLoading] = useState(false);
    // The address whose cancel request is under way. Keyed like everything else, so an answer that
    // comes back after the reader moved on cannot clear the busy state of the address they are on.
    const [cancellingKey, setCancellingKey] = useState('');
    // The same fact for the handler, which must not wait for a render to see it.
    const cancelRequest = useRef('');
    // The address whose stream the server closed with a refusal.
    const [streamRefused, setStreamRefused] = useState('');

    const keyRef = useRef(key);
    keyRef.current = key;
    const request = useRef<AbortController | null>(null);
    const snapshot = loaded && loaded.key === key ? loaded.snapshot : null;
    const snapshotRef = useRef(snapshot);
    snapshotRef.current = snapshot;

    const apply = useCallback((next: WorkflowActivitySnapshot, forKey: string) => {
        if (keyRef.current !== forKey) {
            return;
        }
        setLoaded({ key: forKey, snapshot: next });
        setFailure(null);
        setSelection((current) => resolveActivitySelection(current, next.activities));
        setApplied((count) => count + 1);
    }, []);

    const load = useCallback(async (): Promise<void> => {
        // A closure made for an address the page has left must not start a read: starting one stops
        // the one in flight, and that one is the address the page is on now. Left stopped, it would
        // leave that address on its skeleton with nothing to say why.
        if (!query || keyRef.current !== key) {
            return;
        }
        request.current?.abort();
        const controller = new AbortController();
        request.current = controller;
        setLoading(true);
        try {
            const payload = await api.get<unknown>(workflowActivityApiUrl(query), controller.signal);
            if (!controller.signal.aborted) {
                apply(normalizeWorkflowActivitySnapshot(payload), key);
            }
        } catch (error) {
            if (!controller.signal.aborted) {
                setFailure({ key, message: describeWorkflowActivityFailure(error) });
            }
        } finally {
            if (request.current === controller) {
                request.current = null;
                setLoading(false);
            }
        }
    }, [apply, key, query]);

    // A new address starts a new page: nothing read for the last one is shown for this one.
    useEffect(() => {
        setSelection(INITIAL_ACTIVITY_SELECTION);
        setProblem(null);
        if (!named) {
            setLoading(false);
            return undefined;
        }
        void load();
        return () => {
            request.current?.abort();
            request.current = null;
        };
    }, [load, named]);

    const listening = query !== null && shouldListenForUpdates(query, snapshot) && streamRefused !== key;
    useEffect(() => {
        if (!query || !listening) {
            return undefined;
        }
        return subscribeToWorkflowActivity(query, {
            onSnapshot: (frame) => apply(normalizeWorkflowActivitySnapshot(frame), key),
            onUnavailable: (message) => {
                if (keyRef.current === key) {
                    // The server closed this stream: it is not knocked on again until the reader asks.
                    setStreamRefused(key);
                    setProblem({ key, message });
                }
            },
        });
    }, [apply, key, listening, query]);

    const refresh = useCallback(() => {
        if (keyRef.current !== key) {
            return;
        }
        // Reading again is also asking to be shown what is newest, as it is on the classic page,
        // and to listen again if the server had closed the stream.
        setSelection((current) => ({ ...current, followLatest: true }));
        setRefreshes((count) => count + 1);
        setStreamRefused('');
        setProblem(null);
        void load();
    }, [key, load]);

    const cancel = useCallback(async () => {
        const current = snapshotRef.current;
        if (!query || !current || keyRef.current !== key || cancelRequest.current === key) {
            return;
        }
        const target = activityCancel(current, query);
        if (!target.visible || target.disabled) {
            return;
        }
        cancelRequest.current = key;
        setCancellingKey(key);
        setProblem(null);
        try {
            const response = await cancelScopedWorkflowRun(workflowActivityScope(query), target.workflowId, target.runId);
            if (keyRef.current !== key) {
                // The reader followed a link to another run while this was under way. The request
                // was made and the server has it; what this address shows is read again when they
                // come back to it, and what they are on now is not this request's to touch.
                return;
            }
            const refusal = (response as { success?: unknown; error?: unknown } | null) ?? {};
            if (refusal.success === false) {
                const sentence = typeof refusal.error === 'string' ? refusal.error.trim() : '';
                setProblem({ key, message: sentence || WORKFLOW_ACTIVITY_CANCEL_FAILED });
                return;
            }
            await load();
        } catch (error) {
            if (keyRef.current === key) {
                setProblem({ key, message: describeWorkflowActivityFailure(error, WORKFLOW_ACTIVITY_CANCEL_FAILED) });
            }
        } finally {
            if (cancelRequest.current === key) {
                cancelRequest.current = '';
                setCancellingKey('');
            }
        }
    }, [key, load, query]);

    const selectActivity = useCallback((id: string) => {
        setSelection(pickActivity(snapshotRef.current?.activities ?? [], id));
    }, []);

    const pendingActionChanged = useCallback(
        (action: PendingAction) => {
            // The card that calls this keeps the newest function it was given, and a card that has
            // gone with its address can still hear back from a request it made.
            if (keyRef.current !== key) {
                return;
            }
            const held = snapshotRef.current?.activities.find((activity) => activity.pendingAction?.id === action.id)?.pendingAction;
            if (pendingActionMoved(held, action)) {
                void load();
            }
        },
        [key, load],
    );

    const cancelling = cancellingKey !== '' && cancellingKey === key;

    return useMemo(
        () => ({
            phase: !read.ok ? 'invalid' : !named ? 'empty' : snapshot ? 'ready' : failure && failure.key === key ? 'error' : 'loading',
            query,
            snapshot,
            error: !read.ok ? refused : failure && failure.key === key ? failure.message : '',
            notice: problem && problem.key === key ? problem.message : snapshot && failure && failure.key === key ? failure.message : '',
            selection,
            applied,
            refreshes,
            loading,
            cancelling,
            refresh,
            reload: load,
            cancel,
            selectActivity,
            pendingActionChanged,
        }),
        [
            applied, cancel, cancelling, failure, key, load, loading, named, pendingActionChanged, problem, query, read.ok,
            refresh, refreshes, refused, selectActivity, selection, snapshot,
        ],
    );
}
