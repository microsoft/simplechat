// OrchestrationMapView.tsx
// The conversation as a column of runs, one collapsed row each, newest first.
//
// Where the Run view is one run in full, the map is every run the conversation has produced: the
// ledger you scan to find the turn a particular answer came from. A row carries only what a scan
// needs -- what was asked, how many steps, how it ended -- and expands to its step titles for a
// closer look. Selecting a row is the deliberate, non-silent way to move the Run view onto an older
// run: it pins the Run view and scrolls the thread to the question that started it, so browsing the
// past is always something the user did, never something that happened to them.
//
// The rows come from two places. A run this page watched is in the store already. Every other run
// the conversation ever produced is fetched from the server here, once per conversation, which is
// what makes the map survive a reload, a second tab, or a different device -- runs have always been
// persisted and the planner has always read them back, but until this fetch existed nothing drew
// them, so a conversation opened anywhere else showed an empty panel for work that plainly happened.

import { useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, ChevronRight, Loader2 } from 'lucide-react';
import {
    selectHistory,
    selectHydrationStatus,
    useOrchestrationStore,
    type RunDisplayStatus,
    type RunHistoryEntry,
    type TrackedRun,
} from '../../stores/orchestrationStore';
import { orderStepsForDisplay } from '../../lib/orchestrationPlan';
import { fetchConversationRuns, fetchRunSteps } from '../../lib/orchestration';
import type { OrchestrationPlan, PersistedRunStep } from '../../lib/orchestration';

/** Mirror of the store's private scope key; the NUL separator must match `orchestrationStore`. */
function scopeKey(conversationId: string, turnId: string): string {
    return `${conversationId}\u0000${turnId}`;
}

/** How many runs the map asks the server for. Matches the store's per-conversation history cap. */
const RUN_FETCH_LIMIT = 25;

interface MapRow {
    runId: string;
    turnId: string;
    intentSummary: string;
    status: 'running' | RunDisplayStatus;
    live: boolean;
    /** Step count when the row has no plan in memory to count from. */
    stepCount: number;
    artifactCount: number;
}

const statusDot: Record<'running' | RunDisplayStatus, string> = {
    running: 'bg-accent',
    completed: 'bg-ok',
    failed: 'bg-danger',
    cancelled: 'bg-text-3',
    interrupted: 'bg-warn',
};

const statusLabel: Record<'running' | RunDisplayStatus, string> = {
    running: 'Running',
    completed: 'Done',
    failed: 'Failed',
    cancelled: 'Stopped',
    interrupted: 'Interrupted',
};

export function OrchestrationMapView({
    conversationId,
    shownTurnId,
    onSelectRun,
}: {
    conversationId: string;
    shownTurnId: string | null;
    onSelectRun: (turnId: string, runId: string, live: boolean) => void;
}) {
    const history = useOrchestrationStore((state) => selectHistory(state, conversationId));
    const inFlightMap = useOrchestrationStore((state) => state.inFlight);
    const plansMap = useOrchestrationStore((state) => state.plans);
    const hydrationStatus = useOrchestrationStore((state) =>
        selectHydrationStatus(state, conversationId),
    );
    const hydrateConversationRuns = useOrchestrationStore(
        (state) => state.hydrateConversationRuns,
    );
    const setHydrationStatus = useOrchestrationStore((state) => state.setHydrationStatus);

    const [expanded, setExpanded] = useState<Set<string>>(new Set());
    /** Steps fetched for rows whose plan is not in memory, by run id. */
    const [fetchedSteps, setFetchedSteps] = useState<Record<string, PersistedRunStep[]>>({});
    const [loadingSteps, setLoadingSteps] = useState<Set<string>>(new Set());
    /** Bumped by Retry so a failed hydration can be attempted again. */
    const [retryToken, setRetryToken] = useState(0);

    // Steps are fetched per row and the rows outlive the fetch, so the results are written
    // through a ref-guarded setState rather than assumed to land on a mounted component.
    const mountedRef = useRef(true);
    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
        };
    }, []);

    // Hydrate once per conversation. The status lives in the store rather than in this component
    // because the panel unmounts every time the drawer closes, and re-fetching the same runs each
    // time the user glanced at the panel would be a request per glance.
    //
    // The status is read through `getState` instead of being a dependency on purpose: the effect
    // writes that same status, so depending on it would re-run the effect mid-flight. The fetch is
    // deliberately not aborted on cleanup either -- the result lands in a global store, so a panel
    // that closed before the response arrived still leaves the history cached for the next open.
    useEffect(() => {
        if (!conversationId) {
            return;
        }
        const status = useOrchestrationStore.getState().hydration[conversationId] ?? 'idle';
        if (status === 'loading' || status === 'loaded') {
            return;
        }
        setHydrationStatus(conversationId, 'loading');

        fetchConversationRuns(conversationId, { limit: RUN_FETCH_LIMIT })
            .then((runs) => {
                hydrateConversationRuns(conversationId, runs);
            })
            .catch(() => {
                // A conversation with no stored runs is not an error, but a failed fetch is:
                // the panel says so rather than silently claiming there is no history.
                setHydrationStatus(conversationId, 'error');
            });
    }, [conversationId, retryToken, hydrateConversationRuns, setHydrationStatus]);

    // Reset the per-row step cache when the conversation changes; run ids do not collide, but the
    // expansion state would otherwise carry across conversations.
    useEffect(() => {
        setExpanded(new Set());
        setFetchedSteps({});
        setLoadingSteps(new Set());
        setRetryToken(0);
    }, [conversationId]);

    const rows = useMemo<MapRow[]>(() => {
        const seen = new Set<string>();
        const live: MapRow[] = Object.values(inFlightMap)
            .filter((run): run is TrackedRun => run.conversationId === conversationId)
            .sort((a, b) => b.startedAt - a.startedAt)
            .map((run) => {
                seen.add(run.runId);
                const plan = plansMap[scopeKey(conversationId, run.turnId)];
                return {
                    runId: run.runId,
                    turnId: run.turnId,
                    intentSummary: plan?.intent.summary || 'Planning…',
                    status: 'running' as const,
                    live: true,
                    stepCount: plan?.steps.length ?? 0,
                    artifactCount: plan?.outputs?.length ?? 0,
                };
            });
        const settled: MapRow[] = (history as RunHistoryEntry[])
            .filter((entry) => !seen.has(entry.runId))
            .map((entry) => ({
                runId: entry.runId,
                turnId: entry.turnId,
                intentSummary: entry.intentSummary || 'Untitled run',
                status: entry.status,
                live: false,
                stepCount: entry.stepCount ?? 0,
                artifactCount: entry.artifactCount ?? 0,
            }));
        return [...live, ...settled];
    }, [inFlightMap, history, plansMap, conversationId]);

    const toggleExpanded = (runId: string, hasPlan: boolean) => {
        const willExpand = !expanded.has(runId);
        setExpanded((previous) => {
            const next = new Set(previous);
            if (next.has(runId)) {
                next.delete(runId);
            } else {
                next.add(runId);
            }
            return next;
        });

        // Only a row with no plan in memory needs a fetch, and only the first time it opens. A
        // live run's steps are already streaming into the store.
        if (!willExpand || hasPlan || fetchedSteps[runId] || loadingSteps.has(runId)) {
            return;
        }

        setLoadingSteps((previous) => new Set(previous).add(runId));
        fetchRunSteps(runId, { conversationId })
            .then((steps) => {
                if (mountedRef.current) {
                    setFetchedSteps((previous) => ({ ...previous, [runId]: steps }));
                }
            })
            .catch(() => {
                if (mountedRef.current) {
                    setFetchedSteps((previous) => ({ ...previous, [runId]: [] }));
                }
            })
            .finally(() => {
                if (mountedRef.current) {
                    setLoadingSteps((previous) => {
                        const next = new Set(previous);
                        next.delete(runId);
                        return next;
                    });
                }
            });
    };

    if (rows.length === 0) {
        if (hydrationStatus === 'loading') {
            return (
                <p className="flex items-center gap-2 p-4 text-sm text-text-3">
                    <Loader2 size={14} className="animate-spin" />
                    Loading this conversation&rsquo;s runs&hellip;
                </p>
            );
        }
        if (hydrationStatus === 'error') {
            return (
                <div className="p-4 text-sm text-text-3">
                    <p className="flex items-center gap-2 text-danger">
                        <AlertCircle size={14} />
                        The run history could not be loaded.
                    </p>
                    <button
                        type="button"
                        onClick={() => setRetryToken((token) => token + 1)}
                        className="mt-2 rounded-lg border border-edge px-2 py-1 text-xs text-text-2 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        Try again
                    </button>
                </div>
            );
        }
        return (
            <p className="p-4 text-sm text-text-3">
                Runs for this conversation will be listed here as they happen.
            </p>
        );
    }

    return (
        <ol className="space-y-1.5 p-3">
            {rows.map((row) => {
                const isExpanded = expanded.has(row.runId);
                const isShown = row.turnId === shownTurnId;
                const plan: OrchestrationPlan | undefined =
                    plansMap[scopeKey(conversationId, row.turnId)];
                const planSteps = plan ? orderStepsForDisplay(plan.steps) : [];
                // A plan in memory is authoritative; otherwise the stored step records stand in,
                // which is what lets a row from another device expand to real titles.
                const stepTitles: string[] = plan
                    ? planSteps.map((step) => step.title)
                    : (fetchedSteps[row.runId] ?? [])
                          .slice()
                          .sort((a, b) => (a.step_index ?? 0) - (b.step_index ?? 0))
                          .map((step, index) => step.title || `Step ${index + 1}`);
                const stepCount = plan ? planSteps.length : row.stepCount || stepTitles.length;
                const artifactCount = plan ? (plan.outputs?.length ?? 0) : row.artifactCount;
                const stepsLoading = loadingSteps.has(row.runId);

                return (
                    <li
                        key={row.runId}
                        className={clsx(
                            'rounded-xl border transition-colors',
                            isShown ? 'border-accent bg-accent-soft' : 'border-edge bg-surface-2',
                        )}
                    >
                        <div className="flex items-center gap-1 p-2">
                            <button
                                type="button"
                                onClick={() => toggleExpanded(row.runId, Boolean(plan))}
                                aria-expanded={isExpanded}
                                aria-label={isExpanded ? 'Collapse steps' : 'Expand steps'}
                                className="shrink-0 rounded-md p-1 text-text-3 hover:bg-surface-3 hover:text-text-1"
                            >
                                <ChevronRight
                                    size={14}
                                    className={clsx('transition-transform', isExpanded && 'rotate-90')}
                                />
                            </button>
                            <button
                                type="button"
                                onClick={() => onSelectRun(row.turnId, row.runId, row.live)}
                                className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-0.5 text-left"
                                aria-current={isShown}
                            >
                                <span
                                    className={clsx(
                                        'relative flex h-2 w-2 shrink-0 rounded-full',
                                        statusDot[row.status],
                                    )}
                                >
                                    {row.live ? (
                                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-75" />
                                    ) : null}
                                </span>
                                <span className="min-w-0 flex-1 truncate text-sm text-text-1" title={row.intentSummary}>
                                    {row.intentSummary}
                                </span>
                                {row.live ? (
                                    <Loader2 size={13} className="shrink-0 animate-spin text-accent" />
                                ) : null}
                            </button>
                        </div>

                        <div className="flex items-center gap-2 px-3 pb-2 pl-9 text-[11px] text-text-3">
                            <span>
                                {stepCount > 0
                                    ? `${stepCount} ${stepCount === 1 ? 'step' : 'steps'}`
                                    : '—'}
                            </span>
                            <span aria-hidden="true">·</span>
                            <span>{statusLabel[row.status]}</span>
                            {artifactCount > 0 ? (
                                <>
                                    <span aria-hidden="true">·</span>
                                    <span>
                                        {artifactCount} {artifactCount === 1 ? 'artifact' : 'artifacts'}
                                    </span>
                                </>
                            ) : null}
                        </div>

                        {isExpanded ? (
                            stepsLoading ? (
                                <p className="flex items-center gap-1.5 px-3 pb-2 pl-9 text-xs text-text-3">
                                    <Loader2 size={12} className="animate-spin" />
                                    Loading steps&hellip;
                                </p>
                            ) : stepTitles.length > 0 ? (
                                <ol className="space-y-0.5 px-3 pb-2 pl-9">
                                    {stepTitles.map((title, index) => (
                                        <li
                                            key={`${row.runId}:${index}`}
                                            className="flex items-baseline gap-1.5 text-xs text-text-2"
                                        >
                                            <span className="shrink-0 font-mono text-text-3">
                                                {index + 1}
                                            </span>
                                            <span className="min-w-0 truncate" title={title}>
                                                {title}
                                            </span>
                                        </li>
                                    ))}
                                </ol>
                            ) : (
                                <p className="px-3 pb-2 pl-9 text-xs text-text-3">
                                    No steps were recorded for this run.
                                </p>
                            )
                        ) : null}
                    </li>
                );
            })}
        </ol>
    );
}
