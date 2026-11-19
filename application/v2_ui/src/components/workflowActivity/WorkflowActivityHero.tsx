// WorkflowActivityHero.tsx
// The top of the Workflow Activity page: which workflow and run this is, how it stands, what can be
// done with it, and four figures.
//
// The buttons are the classic page's, in its order: Show or Hide the response preview, Open workflow,
// Cancel run (only while the run is live), and Refresh. Open run is added, as the way into the run's
// task results in the Workflows section, which is where a notice used to take a person before it
// opened this page. The response preview starts closed so the timeline keeps the height; what it
// holds -- the run's error, or else a preview of its response, and any answer checks the tasks saved
// -- is a workflow's own output and is drawn as text.

import { useEffect, useId, useLayoutEffect, useState } from 'react';
import { clsx } from 'clsx';
import { ChevronDown, ListTree, Loader2, MessageSquare, RefreshCw, X } from 'lucide-react';
import { Link } from 'react-router-dom';
import { chatHrefForConversation } from '../../lib/conversationUrl';
import type { WorkflowActivityQuery } from '../../lib/workflowActivity';
import {
    activityCancel,
    activityCaption,
    activityChecks,
    activityConversationId,
    activityResponse,
    activityRunHref,
    activityStats,
    activityTitle,
    responseToggleLabel,
    type WorkflowActivitySnapshot,
} from '../../lib/workflowActivitySnapshot';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { TaskCompletenessDetails } from '../ui/TaskCompletenessDetails';
import { ActivityStatusBadge } from './ActivityStatusBadge';
import { ACTIVITY_LINK_BUTTON_CLASS } from './WorkflowActivityLinks';

/**
 * How a button that is busy looks. These buttons are marked aria-disabled, not disabled: a disabled
 * button hands the reader's focus to the page, so a keyboard reader who pressed Refresh would be
 * back at the top of the document and would have to tab all the way down again.
 */
const BUSY_BUTTON_CLASS = 'aria-disabled:cursor-not-allowed aria-disabled:opacity-50';

function Stat({ label, value, testId }: { label: string; value: string | number; testId: string }) {
    return (
        <div className="rounded-xl border border-edge-strong bg-surface-1 px-4 py-3">
            <dt className="text-[11px] font-semibold tracking-wider text-text-3 uppercase">{label}</dt>
            <dd data-testid={testId} className="mt-1 text-lg font-semibold break-words text-text-1">
                {value}
            </dd>
        </div>
    );
}

/**
 * Cancel run. While the request is under way it stays where it is and keeps focus; once the run
 * settles it leaves the page, and focus goes to Refresh beside it rather than to the page.
 */
function CancelRunButton({
    label,
    inert,
    busy,
    refreshId,
    onCancel,
}: {
    label: string;
    /** A cancel is already under way or recorded: pressing it again asks for nothing. */
    inert: boolean;
    /** The request is under way in this window. */
    busy: boolean;
    /** The id of the Refresh button, where focus goes if this one leaves while it holds it. */
    refreshId: string;
    onCancel: () => void;
}) {
    const id = useId();

    // A layout effect's cleanup runs before the button is taken out of the page, while it still
    // holds focus; once it is out, the browser has already moved focus to the page.
    useLayoutEffect(
        () => () => {
            if (document.activeElement?.id === id) {
                document.getElementById(refreshId)?.focus();
            }
        },
        [id, refreshId],
    );

    return (
        <GlassButton
            id={id}
            type="button"
            variant="danger"
            size="sm"
            aria-disabled={inert || undefined}
            aria-busy={busy || undefined}
            data-testid="v2-workflow-activity-cancel"
            className={BUSY_BUTTON_CLASS}
            onClick={() => {
                if (!inert) {
                    onCancel();
                }
            }}
        >
            {busy ? (
                <Loader2 size={14} aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
            ) : (
                <X size={14} aria-hidden="true" />
            )}
            {label}
        </GlassButton>
    );
}

export function WorkflowActivityHero({
    snapshot,
    query,
    loading,
    cancelling,
    onRefresh,
    onCancel,
}: {
    snapshot: WorkflowActivitySnapshot;
    query: WorkflowActivityQuery;
    /** A read is under way. */
    loading: boolean;
    /** A cancel request is under way. */
    cancelling: boolean;
    onRefresh: () => void;
    onCancel: () => void;
}) {
    const responseId = useId();
    const refreshId = useId();
    const [expanded, setExpanded] = useState(false);

    const run = snapshot.run;
    const response = activityResponse(run);
    const hasResponse = response !== null;
    const checks = activityChecks(run);
    const stats = activityStats(snapshot);
    const cancel = activityCancel(snapshot, query);
    const conversationId = activityConversationId(snapshot);
    const runHref = activityRunHref(query, cancel.workflowId, cancel.runId);
    const shown = hasResponse && expanded;

    // A run with nothing to preview starts closed again if something turns up later.
    useEffect(() => {
        if (!hasResponse) {
            setExpanded(false);
        }
    }, [hasResponse]);

    return (
        <GlassPanel elevation="flat" className="p-4 sm:p-5" data-testid="v2-workflow-activity-hero">
            <div className="flex flex-col gap-4 min-[992px]:flex-row min-[992px]:items-start min-[992px]:justify-between">
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                        {/* `anywhere`, not `break-word`: only it lets a name with no spaces in it
                            shrink the title to the card instead of widening the whole page. */}
                        <h2
                            data-testid="v2-workflow-activity-title"
                            className="max-w-full min-w-0 text-2xl leading-tight font-semibold text-text-1 [overflow-wrap:anywhere]"
                        >
                            {activityTitle(snapshot)}
                        </h2>
                        <ActivityStatusBadge status={run?.status ?? ''} testId="v2-workflow-activity-status" />
                    </div>
                    <p
                        data-testid="v2-workflow-activity-caption"
                        className="mt-2 max-w-[64ch] text-sm break-words text-text-2"
                    >
                        {activityCaption(snapshot)}
                    </p>
                </div>

                <div className="flex flex-wrap items-center gap-2" data-testid="v2-workflow-activity-actions">
                    {response ? (
                        <GlassButton
                            type="button"
                            variant="subtle"
                            size="sm"
                            aria-expanded={shown}
                            aria-controls={responseId}
                            data-testid="v2-workflow-activity-response-toggle"
                            onClick={() => setExpanded((open) => !open)}
                        >
                            <ChevronDown
                                size={14}
                                aria-hidden="true"
                                className={clsx('transition-transform motion-reduce:transition-none', shown && 'rotate-180')}
                            />
                            {responseToggleLabel(shown, response.heading)}
                        </GlassButton>
                    ) : null}
                    {conversationId ? (
                        <Link
                            to={chatHrefForConversation(conversationId)}
                            data-testid="v2-workflow-activity-open-workflow"
                            className={clsx(ACTIVITY_LINK_BUTTON_CLASS, 'h-8 px-3 text-sm')}
                        >
                            <MessageSquare size={14} aria-hidden="true" />
                            Open workflow
                        </Link>
                    ) : null}
                    {runHref ? (
                        <Link
                            to={runHref}
                            title="Open this run in the workflow's run history"
                            data-testid="v2-workflow-activity-open-run"
                            className={clsx(ACTIVITY_LINK_BUTTON_CLASS, 'h-8 px-3 text-sm')}
                        >
                            <ListTree size={14} aria-hidden="true" />
                            Open run
                        </Link>
                    ) : null}
                    {cancel.visible ? (
                        <CancelRunButton
                            label={cancel.label}
                            inert={cancel.disabled || cancelling}
                            busy={cancelling}
                            refreshId={refreshId}
                            onCancel={onCancel}
                        />
                    ) : null}
                    <GlassButton
                        id={refreshId}
                        type="button"
                        variant="subtle"
                        size="sm"
                        aria-disabled={loading || undefined}
                        aria-busy={loading || undefined}
                        data-testid="v2-workflow-activity-refresh"
                        className={BUSY_BUTTON_CLASS}
                        onClick={() => {
                            if (!loading) {
                                onRefresh();
                            }
                        }}
                    >
                        <RefreshCw
                            size={14}
                            aria-hidden="true"
                            className={clsx(loading && 'animate-spin motion-reduce:animate-none')}
                        />
                        Refresh
                    </GlassButton>
                </div>
            </div>

            <dl className="mt-4 grid grid-cols-2 gap-3 min-[1200px]:grid-cols-4" data-testid="v2-workflow-activity-stats">
                <Stat label="Run" value={stats.run} testId="v2-workflow-activity-stat-run" />
                <Stat label="Activities" value={stats.activities} testId="v2-workflow-activity-stat-total" />
                <Stat label="Tool Calls" value={stats.toolCalls} testId="v2-workflow-activity-stat-tools" />
                <Stat label="Started" value={stats.started} testId="v2-workflow-activity-stat-started" />
            </dl>

            {response ? (
                <div
                    id={responseId}
                    role="region"
                    aria-label={response.heading}
                    data-testid="v2-workflow-activity-response"
                    className={clsx(
                        'mt-4 max-h-60 overflow-y-auto rounded-xl border border-edge-strong bg-surface-1 p-4',
                        !shown && 'hidden',
                    )}
                >
                    <p className="text-[11px] font-semibold tracking-wider text-text-3 uppercase">{response.heading}</p>
                    <p className="mt-2 text-sm break-words whitespace-pre-wrap text-text-1">{response.text}</p>
                    {checks.length ? (
                        <div className="mt-3 space-y-2" data-testid="v2-workflow-activity-checks">
                            {checks.map((check) => (
                                <div key={check.key}>
                                    <p className="text-xs font-medium text-text-2">{check.name}</p>
                                    <TaskCompletenessDetails value={check.completeness} />
                                </div>
                            ))}
                        </div>
                    ) : null}
                </div>
            ) : null}
        </GlassPanel>
    );
}
