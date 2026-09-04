// OrchestrationMapView.tsx
// The conversation as a column of runs, one collapsed row each, newest first.
//
// Where the Run view is one run in full, the map is every run the conversation has produced: the
// ledger you scan to find the turn a particular answer came from. A row carries only what a scan
// needs -- what was asked, how many steps, how it ended -- and expands to its step titles for a
// closer look. Selecting a row is the deliberate, non-silent way to move the Run view onto an older
// run: it pins the Run view and scrolls the thread to the question that started it, so browsing the
// past is always something the user did, never something that happened to them.

import { useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { ChevronRight, Loader2 } from 'lucide-react';
import {
    selectHistory,
    useOrchestrationStore,
    type RunHistoryEntry,
    type RunOutcome,
    type TrackedRun,
} from '../../stores/orchestrationStore';
import { orderStepsForDisplay } from '../../lib/orchestrationPlan';
import type { OrchestrationPlan } from '../../lib/orchestration';

/** Mirror of the store's private scope key; the NUL separator must match `orchestrationStore`. */
function scopeKey(conversationId: string, turnId: string): string {
    return `${conversationId}\u0000${turnId}`;
}

interface MapRow {
    runId: string;
    turnId: string;
    intentSummary: string;
    status: 'running' | RunOutcome;
    live: boolean;
}

const statusDot: Record<'running' | RunOutcome, string> = {
    running: 'bg-accent',
    completed: 'bg-ok',
    failed: 'bg-danger',
    cancelled: 'bg-text-3',
};

const statusLabel: Record<'running' | RunOutcome, string> = {
    running: 'Running',
    completed: 'Done',
    failed: 'Failed',
    cancelled: 'Stopped',
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
    const [expanded, setExpanded] = useState<Set<string>>(new Set());

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
            }));
        return [...live, ...settled];
    }, [inFlightMap, history, plansMap, conversationId]);

    if (rows.length === 0) {
        return (
            <p className="p-4 text-sm text-text-3">
                Runs for this conversation will be listed here as they happen.
            </p>
        );
    }

    const toggleExpanded = (runId: string) => {
        setExpanded((previous) => {
            const next = new Set(previous);
            if (next.has(runId)) {
                next.delete(runId);
            } else {
                next.add(runId);
            }
            return next;
        });
    };

    return (
        <ol className="space-y-1.5 p-3">
            {rows.map((row) => {
                const isExpanded = expanded.has(row.runId);
                const isShown = row.turnId === shownTurnId;
                const plan: OrchestrationPlan | undefined =
                    plansMap[scopeKey(conversationId, row.turnId)];
                const steps = plan ? orderStepsForDisplay(plan.steps) : [];
                const artifactCount = plan?.outputs?.length ?? 0;

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
                                onClick={() => toggleExpanded(row.runId)}
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
                                {plan ? `${steps.length} ${steps.length === 1 ? 'step' : 'steps'}` : '—'}
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

                        {isExpanded && steps.length > 0 ? (
                            <ol className="space-y-0.5 px-3 pb-2 pl-9">
                                {steps.map((step, index) => (
                                    <li
                                        key={step.step_id}
                                        className="flex items-baseline gap-1.5 text-xs text-text-2"
                                    >
                                        <span className="shrink-0 font-mono text-text-3">
                                            {index + 1}
                                        </span>
                                        <span className="min-w-0 truncate" title={step.title}>
                                            {step.title}
                                        </span>
                                    </li>
                                ))}
                            </ol>
                        ) : null}
                    </li>
                );
            })}
        </ol>
    );
}
