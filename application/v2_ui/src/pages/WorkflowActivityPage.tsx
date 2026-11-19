// WorkflowActivityPage.tsx
// One workflow run as a timeline: what it did, in order, and where it is now.
//
// The V2 counterpart of the classic `/workflow-activity` page, behind the same gates and opened by
// the same links. It takes the query string the classic page takes (`conversationId`, `workflowId`,
// `runId`, `scope`, `groupId`; lib/workflowActivity.ts), reads the snapshot from
// `GET /api/{user|group}/workflows/activity`, and keeps reading it over the activity stream for as
// long as the run is live. What the server refuses -- workflows or group workflows switched off, a
// missing workflow role, a group the reader is not in, a run that is not there -- is said in the
// server's own words, because those words are what tell a person what to ask their administrator for.
//
// Beside the Workflows section's run inspector, which shows what each task and execution did, this
// page shows the thought and tool-call stream a run recorded, and the one place a run's pending
// Microsoft 365 email or invitation can be reviewed beside the run that saved it. The two link to
// each other.

import { useMemo, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Activity, Link2Off, RotateCcw, TriangleAlert } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { useWorkflowActivity } from '../components/workflowActivity/useWorkflowActivity';
import { WorkflowActivityDetail } from '../components/workflowActivity/WorkflowActivityDetail';
import { WorkflowActivityHero } from '../components/workflowActivity/WorkflowActivityHero';
import { WorkflowActivityTimeline } from '../components/workflowActivity/WorkflowActivityTimeline';
import { EmptyState, GlassButton, GlassPanel, Skeleton } from '../components/ui/primitives';
import { readWorkflowActivityQuery } from '../lib/workflowActivity';
import {
    activityStats,
    activityStatusView,
    resolveActivitySelection,
    selectedActivity,
    type WorkflowActivitySnapshot,
} from '../lib/workflowActivitySnapshot';

function liveSummary(snapshot: WorkflowActivitySnapshot): string {
    const stats = activityStats(snapshot);
    const status = activityStatusView(snapshot.run?.status ?? '').label;
    return `${stats.activities} ${stats.activities === 1 ? 'activity' : 'activities'}, ${stats.toolCalls} tool ${stats.toolCalls === 1 ? 'call' : 'calls'}. Run status: ${status}.`;
}

function Loading() {
    return (
        <div role="status" aria-label="Loading workflow activity" aria-busy="true" className="space-y-4">
            <Skeleton className="h-44 w-full" />
            <div className="grid gap-4 min-[992px]:grid-cols-2">
                <Skeleton className="h-72 w-full" />
                <Skeleton className="h-72 w-full" />
            </div>
        </div>
    );
}

function Problem({ title, message, action }: { title: string; message: string; action?: ReactNode }) {
    return (
        <GlassPanel elevation="flat" role="alert" data-testid="v2-workflow-activity-problem" className="mx-auto max-w-2xl">
            <EmptyState
                icon={<Link2Off size={28} aria-hidden="true" />}
                title={title}
                description={message}
                action={action}
            />
        </GlassPanel>
    );
}

export function WorkflowActivityPage() {
    const [params] = useSearchParams();
    const search = params.toString();
    const read = useMemo(() => readWorkflowActivityQuery(search), [search]);
    const activity = useWorkflowActivity(read);
    const { snapshot, query } = activity;

    const resolved = useMemo(
        () => (snapshot ? resolveActivitySelection(activity.selection, snapshot.activities) : activity.selection),
        [snapshot, activity.selection],
    );
    const selected = snapshot ? selectedActivity(resolved, snapshot.activities) : null;

    let body: ReactNode;
    if (activity.phase === 'empty') {
        body = (
            <GlassPanel elevation="flat" data-testid="v2-workflow-activity-empty" className="mx-auto max-w-2xl">
                <EmptyState
                    icon={<Activity size={28} aria-hidden="true" />}
                    title="Open a workflow run to see its activity"
                    description="Open this page from a workflow conversation or a workflow run history entry."
                />
            </GlassPanel>
        );
    } else if (activity.phase === 'invalid') {
        body = <Problem title="This link cannot be opened" message={activity.error} />;
    } else if (activity.phase === 'error') {
        body = (
            <Problem
                title="Workflow activity unavailable"
                message={activity.error}
                action={
                    <GlassButton type="button" variant="subtle" size="sm" onClick={activity.refresh}>
                        <RotateCcw size={14} aria-hidden="true" />
                        Try again
                    </GlassButton>
                }
            />
        );
    } else if (activity.phase === 'ready' && snapshot && query) {
        body = (
            <div className="flex flex-col gap-4 min-[992px]:h-full min-[992px]:min-h-[34rem]">
                {activity.notice ? (
                    <p
                        role="alert"
                        data-testid="v2-workflow-activity-notice"
                        className="flex items-start gap-2 rounded-xl bg-danger-soft p-3 text-sm text-text-1"
                    >
                        <TriangleAlert size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-danger" />
                        <span className="min-w-0 break-words">{activity.notice}</span>
                    </p>
                ) : null}
                <p role="status" className="sr-only">
                    {liveSummary(snapshot)}
                </p>
                <WorkflowActivityHero
                    snapshot={snapshot}
                    query={query}
                    loading={activity.loading}
                    cancelling={activity.cancelling}
                    onRefresh={activity.refresh}
                    onCancel={() => void activity.cancel()}
                />
                <div className="grid grid-cols-[minmax(0,1fr)] gap-4 min-[992px]:min-h-0 min-[992px]:flex-1 min-[992px]:grid-cols-[minmax(0,1.35fr)_minmax(20rem,0.85fr)] min-[992px]:grid-rows-[minmax(0,1fr)]">
                    <WorkflowActivityTimeline
                        activities={snapshot.activities}
                        selectedId={resolved.selectedId}
                        onSelect={activity.selectActivity}
                        live={snapshot.live}
                        applied={activity.applied}
                        refreshes={activity.refreshes}
                    />
                    <WorkflowActivityDetail activity={selected} onPendingActionChanged={activity.pendingActionChanged} />
                </div>
            </div>
        );
    } else {
        body = <Loading />;
    }

    return (
        <div className="flex h-full min-h-0 flex-col" data-testid="v2-workflow-activity-page">
            <PageHeader
                title="Workflow activity"
                description="What one workflow run did, in order, updated live while it runs."
            />
            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 lg:px-6">{body}</div>
        </div>
    );
}
