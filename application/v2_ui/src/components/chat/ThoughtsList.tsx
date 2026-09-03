// ThoughtsList.tsx
// The one way reasoning steps are drawn, whether they arrived on a live stream or were read
// back from storage afterwards.
//
// Historical reasoning deliberately looks identical to reasoning being generated. A separate
// "timeline" treatment for the stored version would make the same information feel like a
// different feature depending on when you looked at it.
//
// Steps that describe staged work additionally get a progress card above the list. A tabular
// analysis reports one workbook tool call at a time and can run for minutes; as a flat list
// that is a growing wall of sentences with no indication of how far along it is, which reads
// the same whether the run is working or wedged. Which kinds of work qualify is decided by
// `lib/activityLanes.ts`, not here.

import { useMemo } from 'react';
import { clsx } from 'clsx';
import { CircleCheck, TriangleAlert } from 'lucide-react';
import { buildLaneProgress, type LaneProgress } from '../../lib/activityLanes';
import type { PersistedThought, ThoughtEntry } from '../../lib/types';

/**
 * Normalise a stored reasoning step into the shape the live stream produces.
 *
 * The two are not the same record: a stream frame carries `title` and `content`, while
 * `route_backend_thoughts.py` returns `step_type`, `content`, `detail`, `activity` and
 * timing. Mapping them here is what lets a single renderer serve both.
 */
export function normalizePersistedThought(
    thought: PersistedThought,
    index: number,
): ThoughtEntry & { duration?: string } {
    const stepType = String(thought.step_type ?? '').trim();
    const title = stepType || `Step ${index + 1}`;

    const content = String(thought.content ?? '').trim();
    const detail = String(thought.detail ?? '').trim();

    return {
        id: String(thought.id ?? `${thought.message_id ?? 'thought'}-${index}`),
        title,
        // `detail` elaborates on `content` when they differ; showing both without repeating
        // the same sentence twice.
        content: detail && detail !== content ? `${content}\n${detail}`.trim() : content,
        stepType: stepType || undefined,
        detail: detail || undefined,
        activity: thought.activity,
        progress: thought.progress,
        stepIndex: thought.step_index,
        duration:
            typeof thought.duration_ms === 'number' && thought.duration_ms > 0
                ? `${(thought.duration_ms / 1000).toFixed(1)}s`
                : undefined,
    };
}

function ProgressCard({ progress, live }: { progress: LaneProgress; live: boolean }) {
    const failed = progress.failedCount > 0;

    return (
        <div className="glass-flat mb-2 rounded-xl p-3">
            <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-start gap-2">
                    {progress.completed ? (
                        failed ? (
                            <TriangleAlert size={14} className="mt-0.5 shrink-0 text-warn" />
                        ) : (
                            <CircleCheck size={14} className="mt-0.5 shrink-0 text-ok" />
                        )
                    ) : (
                        <span
                            aria-hidden="true"
                            className="mt-1 h-2 w-2 shrink-0 animate-pulse rounded-full bg-accent"
                        />
                    )}
                    <div className="min-w-0">
                        <p className="text-xs font-semibold text-text-1">
                            {progress.completed
                                ? `${progress.lane.title} complete`
                                : progress.lane.title}
                        </p>
                        <p className="text-xs text-text-3">{progress.currentStep}</p>
                    </div>
                </div>
                <span
                    className={clsx(
                        'shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium tabular-nums',
                        progress.completed
                            ? failed
                                ? 'bg-warn-soft text-warn'
                                : 'bg-ok-soft text-ok'
                            : 'bg-surface-2 text-text-2',
                    )}
                >
                    {progress.completed
                        ? failed
                            ? 'Completed with issues'
                            : 'Completed'
                        : `${progress.percent}%`}
                </span>
            </div>

            <p className="mt-2 text-xs text-text-3">{progress.summary}</p>

            {/* The bar is dropped once the run is finished: a full bar next to a "Completed"
                badge says nothing the badge has not already said. */}
            {!progress.completed && (
                <div
                    role="progressbar"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={progress.percent}
                    aria-label={`${progress.lane.title} progress`}
                    className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-sunken"
                >
                    <div
                        className={clsx(
                            'h-full rounded-full transition-[width] duration-500',
                            failed ? 'bg-warn' : 'bg-accent',
                        )}
                        style={{ width: `${progress.percent}%` }}
                    />
                </div>
            )}

            {live && progress.latestContent && (
                <p className="mt-2 text-xs text-text-2">{progress.latestContent}</p>
            )}
        </div>
    );
}

export function ThoughtsList({
    thoughts,
}: {
    thoughts: Array<ThoughtEntry & { duration?: string }>;
}) {
    return (
        <ol className="space-y-1.5 border-l border-edge-strong pl-3">
            {thoughts.map((thought) => (
                <li key={thought.id} className="text-xs text-text-3">
                    <span className="font-medium text-text-2">{thought.title}</span>
                    {thought.duration && (
                        <span className="ml-2 font-mono text-[10px] text-text-3">
                            {thought.duration}
                        </span>
                    )}
                    {thought.content && (
                        <p className="mt-0.5 whitespace-pre-wrap">{thought.content}</p>
                    )}
                </li>
            ))}
        </ol>
    );
}

/**
 * The progress card for these steps, or nothing when they do not describe staged work.
 *
 * Separate from the list so the caller can place it outside the collapsed section. A run in
 * flight needs its progress visible without anyone expanding anything — that is the whole
 * point — while a finished one can stay tucked away with the steps it summarises.
 */
export function ThoughtsProgressCard({
    thoughts,
    live = false,
}: {
    thoughts: Array<ThoughtEntry & { duration?: string }>;
    live?: boolean;
}) {
    const progress = useMemo(
        () =>
            buildLaneProgress(
                thoughts.map((thought) => ({
                    step_type: thought.stepType,
                    content: thought.content,
                    detail: thought.detail,
                    activity: thought.activity,
                    step_index: thought.stepIndex,
                })),
                { live },
            ),
        [thoughts, live],
    );

    if (!progress) {
        return null;
    }

    return <ProgressCard progress={progress} live={live} />;
}
