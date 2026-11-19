// WorkflowActivityTimeline.tsx
// One run's activities as a timeline: a card for each, indented by the lane it belongs to.
//
// Every card is a button that selects the activity for the detail panel beside it. While the run is
// live and the reader has not scrolled away from the bottom, the viewport follows the newest card;
// a reader who has scrolled up to read is left where they are, and the timeline picks the newest
// card up again once they come back within a few pixels of the bottom. A finished run opens at its
// top, as the classic page opens it.
//
// Lanes are the branches a run fans out into -- the workflow itself, each tool it called, Microsoft
// Graph. Each one sits further to the right on a wide screen, joined back to the main line, and on
// a phone every card has the same indent, because there is no room to spend on it.

import { useCallback, useEffect, useRef, type CSSProperties } from 'react';
import { clsx } from 'clsx';
import { Clock, GitBranch, History, Timer } from 'lucide-react';
import { EmptyState } from '../ui/primitives';
import {
    formatActivityDateTime,
    formatActivityDuration,
    isScrolledNearBottom,
    type WorkflowActivityRecord,
} from '../../lib/workflowActivitySnapshot';
import { ActivityStatusBadge } from './ActivityStatusBadge';

/** How far each lane sits right of the one before it. */
const laneOffset = (base: string) => `calc(${base} + var(--lane-index) * var(--lane-step))`;

const NODE_CLASS: Record<string, string> = {
    running: 'bg-accent',
    cancelling: 'bg-warn',
    cancelled: 'bg-text-3',
    completed: 'bg-ok',
    failed: 'bg-danger',
};

function ActivityCard({
    activity,
    selected,
    onSelect,
}: {
    activity: WorkflowActivityRecord;
    selected: boolean;
    onSelect: (id: string) => void;
}) {
    const duration = formatActivityDuration(activity.durationMs);
    return (
        <button
            type="button"
            aria-current={selected ? 'true' : undefined}
            onClick={() => onSelect(activity.id)}
            data-testid="v2-workflow-activity-card"
            data-activity-id={activity.id}
            data-status={activity.status}
            data-selected={selected ? 'true' : 'false'}
            className={clsx(
                'w-full rounded-2xl border border-edge-strong bg-surface-2 p-3.5 text-left transition-colors',
                'hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
                selected && 'ring-2 ring-accent',
            )}
        >
            <span className="flex items-start justify-between gap-3">
                <span className="min-w-0">
                    <span className="block text-sm font-semibold break-words text-text-1">
                        {activity.title || 'Workflow activity'}
                    </span>
                    <span className="mt-1 block text-sm break-words text-text-2">
                        {activity.summary || 'No summary available.'}
                    </span>
                </span>
                <ActivityStatusBadge status={activity.status || 'completed'} className="shrink-0" />
            </span>
            <span className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-3">
                {activity.laneLabel ? (
                    <span className="inline-flex max-w-full min-w-0 items-start gap-1">
                        <GitBranch size={12} aria-hidden="true" className="mt-0.5 shrink-0" />
                        <span className="min-w-0 [overflow-wrap:anywhere]">{activity.laneLabel}</span>
                    </span>
                ) : null}
                {activity.startedAt ? (
                    <span className="inline-flex items-center gap-1">
                        <Clock size={12} aria-hidden="true" />
                        {formatActivityDateTime(activity.startedAt)}
                    </span>
                ) : null}
                {duration ? (
                    <span className="inline-flex items-center gap-1">
                        <Timer size={12} aria-hidden="true" />
                        {duration}
                    </span>
                ) : null}
            </span>
        </button>
    );
}

export function WorkflowActivityTimeline({
    activities,
    selectedId,
    onSelect,
    live,
    applied,
    refreshes,
}: {
    activities: readonly WorkflowActivityRecord[];
    selectedId: string;
    onSelect: (id: string) => void;
    live: boolean;
    /** Counts every snapshot applied, including one equal to the last. */
    applied: number;
    /** Counts every Refresh, which puts the timeline back on its newest card. */
    refreshes: number;
}) {
    const viewport = useRef<HTMLDivElement>(null);
    const pinned = useRef(true);

    useEffect(() => {
        pinned.current = true;
    }, [refreshes]);

    const followNewest = useCallback(() => {
        const element = viewport.current;
        if (element) {
            // Not smooth: a smooth scroll sends scroll events from the middle of its own journey,
            // each of which would look like the reader leaving the bottom.
            element.scrollTo({ top: element.scrollHeight, behavior: 'instant' });
        }
    }, []);

    useEffect(() => {
        if (pinned.current && live) {
            followNewest();
        }
    }, [applied, live, followNewest]);

    return (
        <section
            aria-labelledby="workflow-activity-timeline-heading"
            data-testid="v2-workflow-activity-timeline-panel"
            className="glass-flat flex min-h-0 flex-col rounded-2xl"
        >
            <div className="px-4 pt-4 sm:px-5 sm:pt-5">
                <h2 id="workflow-activity-timeline-heading" className="text-base font-semibold text-text-1">
                    Timeline
                </h2>
                <p className="mt-0.5 text-xs text-text-3">Live events roll in here while a workflow run is active.</p>
            </div>
            <div
                ref={viewport}
                data-testid="v2-workflow-activity-timeline-viewport"
                onScroll={(event) => {
                    pinned.current = isScrolledNearBottom(event.currentTarget);
                }}
                className="min-h-0 flex-1 overflow-y-auto px-4 pt-3 pb-4 max-[991px]:max-h-[50vh] sm:px-5"
            >
                {activities.length ? (
                    <div className="relative">
                        <span aria-hidden="true" className="absolute top-3 bottom-3 left-5 w-0.5 rounded bg-edge-strong" />
                        <ol
                            aria-label="Workflow activity timeline"
                            data-testid="v2-workflow-activity-timeline"
                            className="relative flex flex-col gap-4 [--lane-step:0rem] md:[--lane-step:2.5rem]"
                        >
                            {activities.map((activity, index) => (
                                <li
                                    key={activity.id}
                                    className="relative min-h-[5.5rem]"
                                    style={
                                        {
                                            '--lane-index': activity.laneIndex,
                                            paddingLeft: laneOffset('3rem'),
                                        } as CSSProperties
                                    }
                                >
                                    <span
                                        aria-hidden="true"
                                        className="absolute top-[0.95rem] w-0.5 bg-accent/25"
                                        style={{
                                            left: laneOffset('1.25rem'),
                                            bottom: index === activities.length - 1 ? '2rem' : '-1rem',
                                        }}
                                    />
                                    <span
                                        aria-hidden="true"
                                        className="absolute top-7 left-5 h-0.5 bg-accent/25"
                                        style={{ width: 'calc(var(--lane-index) * var(--lane-step))' }}
                                    />
                                    <span
                                        aria-hidden="true"
                                        className={clsx(
                                            'absolute top-[1.35rem] h-3 w-3 rounded-full border-2 border-surface-solid ring-4 ring-accent/15',
                                            NODE_CLASS[activity.status] ?? 'bg-text-3',
                                        )}
                                        style={{ left: laneOffset('0.9rem') }}
                                    />
                                    <ActivityCard
                                        activity={activity}
                                        selected={activity.id === selectedId}
                                        onSelect={onSelect}
                                    />
                                </li>
                            ))}
                        </ol>
                    </div>
                ) : (
                    <EmptyState
                        icon={<History size={28} aria-hidden="true" />}
                        title="No activity yet"
                        description="This conversation does not have a captured workflow run yet, or the run completed before activity tracking was available."
                    />
                )}
            </div>
        </section>
    );
}
