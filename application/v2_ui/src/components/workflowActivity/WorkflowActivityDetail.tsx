// WorkflowActivityDetail.tsx
// The activity the reader picked on the timeline: what it did, when, and every event it recorded.
//
// What is shown is a workflow's own output -- a model's sentences, a tool's arguments and results --
// so all of it is drawn as plain text, never parsed as markup. An activity that stands for a saved
// Microsoft 365 email or invitation also shows the action's card here, which is where it can be
// sent or cancelled.

import type { ReactNode } from 'react';
import type { PendingAction } from '../../lib/approvalsApi';
import {
    formatActivityDateTime,
    formatActivityDuration,
    type WorkflowActivityRecord,
} from '../../lib/workflowActivitySnapshot';
import { ActivityPendingAction } from './ActivityPendingAction';
import { ActivityStatusBadge } from './ActivityStatusBadge';

function Block({ label, children }: { label: string; children: ReactNode }) {
    return (
        <section className="mt-4 rounded-xl border border-edge-strong bg-surface-1 p-3.5">
            <h3 className="text-[11px] font-semibold tracking-wider text-text-3 uppercase">{label}</h3>
            <div className="mt-2">{children}</div>
        </section>
    );
}

export function WorkflowActivityDetail({
    activity,
    onPendingActionChanged,
}: {
    activity: WorkflowActivityRecord | null;
    onPendingActionChanged: (action: PendingAction) => void;
}) {
    const duration = activity ? formatActivityDuration(activity.durationMs) : '';
    return (
        <aside
            aria-label="Activity details"
            data-testid="v2-workflow-activity-detail"
            className="glass-flat rounded-2xl p-4 min-[992px]:min-h-0 min-[992px]:overflow-y-auto sm:p-5"
        >
            <p className="text-[11px] font-semibold tracking-[0.16em] text-accent uppercase">Details</p>
            <h2 data-testid="v2-workflow-activity-detail-title" className="mt-1 text-lg font-semibold break-words text-text-1">
                {activity ? activity.title || 'Workflow activity' : 'Select an activity'}
            </h2>
            {activity ? (
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-text-3">
                    <ActivityStatusBadge status={activity.status || 'completed'} />
                    {activity.laneLabel ? (
                        <span className="max-w-full min-w-0 [overflow-wrap:anywhere]">{activity.laneLabel}</span>
                    ) : null}
                    {activity.startedAt ? <span>{formatActivityDateTime(activity.startedAt)}</span> : null}
                    {duration ? <span>{duration}</span> : null}
                </div>
            ) : null}
            <p className="mt-3 text-sm break-words text-text-2" data-testid="v2-workflow-activity-detail-summary">
                {activity
                    ? activity.summary || 'No summary available.'
                    : 'Choose a card on the timeline to inspect the event stream, timing, and captured technical detail.'}
            </p>

            {activity?.pendingAction ? (
                <div className="mt-4" data-testid="v2-workflow-activity-pending-action">
                    <ActivityPendingAction
                        key={activity.pendingAction.id}
                        action={activity.pendingAction}
                        onChanged={onPendingActionChanged}
                    />
                </div>
            ) : null}

            <Block label="Technical Detail">
                <pre
                    data-testid="v2-workflow-activity-detail-text"
                    className="font-sans text-sm break-words whitespace-pre-wrap text-text-1"
                >
                    {activity ? activity.detail || 'No additional technical detail recorded.' : 'No activity selected.'}
                </pre>
            </Block>

            <Block label="Event History">
                {!activity ? (
                    <p className="text-sm text-text-3">Select an activity to inspect its event history.</p>
                ) : activity.events.length ? (
                    <ol className="space-y-2.5" data-testid="v2-workflow-activity-events">
                        {activity.events.map((event, index) => (
                            <li key={`${index}-${event.timestamp}`} className="rounded-xl border border-edge bg-surface-2 p-3">
                                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                                    <p className="min-w-0 text-sm font-semibold break-words text-text-1">
                                        {event.content || activity.title || 'Activity event'}
                                    </p>
                                    <p className="text-xs text-text-3">{formatActivityDateTime(event.timestamp)}</p>
                                </div>
                                <p className="mt-1 text-sm break-words whitespace-pre-wrap text-text-2">
                                    {event.detail || 'No additional technical detail recorded.'}
                                </p>
                            </li>
                        ))}
                    </ol>
                ) : (
                    <p className="text-sm text-text-3">No event history is available for this activity.</p>
                )}
            </Block>
        </aside>
    );
}
