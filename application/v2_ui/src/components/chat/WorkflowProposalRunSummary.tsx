// WorkflowProposalRunSummary.tsx
// When a workflow a chat plan created runs next, and how its last run went (phase 6b).
//
// Shown on a created proposal card. It reads the workflow and its recent runs once, when the
// card opens, through the same clients the Workflows page uses, and never polls. Every value is
// checked as it is read; anything missing or malformed is left out rather than guessed. The
// card's own When line already names the schedule and its time zone, so this adds only the next
// and last runs.

import { useEffect, useState, type ReactNode } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { MessageSquare } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import {
    fetchScopedWorkflowRuns,
    fetchScopedWorkflows,
    type WorkflowDefinition,
    type WorkflowRunSummary,
    type WorkflowScope,
} from '../../lib/workflowEditor';
import {
    canAskAboutWorkflowRun,
    formatWorkflowRunTime,
    isWorkflowResultIdentifier,
    isWorkflowResultReadableStatus,
    workflowRunChatId,
} from '../../lib/workflowResults';
import { followUpWorkflowResult } from '../../lib/workflowResultFollowUp';
import { workflowRunHref } from '../../lib/workflowRunLink';
import { WORKFLOW_RUN_STATUS_UNAVAILABLE } from '../../lib/workflowRunStatus';

const PERSONAL_SCOPE: WorkflowScope = { type: 'personal' };
const ISO_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;
const LINK_CLASS = 'inline-flex h-8 items-center rounded-xl px-3 text-sm font-medium text-accent '
    + 'hover:bg-surface-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent';

export const WORKFLOW_PROPOSAL_RUNS_UNAVAILABLE_TEXT = 'Run details aren\'t available right now.';
export const WORKFLOW_PROPOSAL_NO_RUNS_TEXT = 'No runs yet';
export const WORKFLOW_PROPOSAL_DUE_NOW_TEXT = 'Due now';

// The states a workflow's run history stores. Anything else reads as unavailable rather than
// being guessed at.
const LAST_RUN_LABELS: Readonly<Record<string, string>> = {
    queued: 'Queued',
    running: 'Running',
    cancelling: 'Cancelling',
    waiting_recovery: 'Recovering',
    waiting_approval: 'Waiting for approval',
    waiting_output: 'Waiting for output review',
    paused: 'Paused',
    awaiting_approval: 'Waiting for a Microsoft 365 approval',
    awaiting_sharing_approval: 'Waiting for a Microsoft 365 approval',
    awaiting_analysis_approval: 'Waiting for a Microsoft 365 approval',
    awaiting_run_as_approval: 'Waiting for a Microsoft 365 approval',
    awaiting_sign_in: 'Waiting for Microsoft 365 sign-in',
    completed: 'Completed',
    completed_partial: 'Partly completed',
    failed: 'Failed',
    invalid: 'Failed',
    incomplete: 'Incomplete',
    skipped: 'Skipped',
    cancelled: 'Cancelled',
    canceled: 'Cancelled',
};

interface ProposalRunSummary {
    /** The next scheduled run as the reader would say it, or '' when none is scheduled. */
    nextRun: string;
    /** "Completed · Mon, Jan 5, 9:00 AM PST", or '' when the workflow has never run. */
    lastRun: string;
    /** The newest finished run whose results can be opened. */
    latestResultRunId: string | null;
    /** The newest run chat can answer from, and its time for the button's name. */
    followUp: { runId: string; time: string } | null;
}

type SummaryState =
    | { kind: 'loading' }
    | { kind: 'ready'; summary: ProposalRunSummary }
    | { kind: 'unavailable' };

function timestamp(value: unknown): Date | null {
    if (typeof value !== 'string' || !ISO_TIMESTAMP.test(value)) {
        return null;
    }
    const parsed = new Date(value);
    return Number.isNaN(parsed.valueOf()) ? null : parsed;
}

/** A time with its zone, so a schedule kept in another time zone still reads correctly. */
function formatSummaryTime(value: Date): string {
    try {
        return new Intl.DateTimeFormat(undefined, {
            weekday: 'short',
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
            timeZoneName: 'short',
        }).format(value);
    } catch {
        return '';
    }
}

function nextRunText(workflow: WorkflowDefinition, now: number): string {
    // A paused workflow has no next run, whatever an older record still holds.
    if (workflow.is_enabled !== true) {
        return '';
    }
    const next = timestamp(workflow.next_run_at);
    if (!next) {
        return '';
    }
    return next.valueOf() <= now ? WORKFLOW_PROPOSAL_DUE_NOW_TEXT : formatSummaryTime(next);
}

function lastRunText(status: unknown, at: unknown): string {
    const label = (typeof status === 'string' && Object.prototype.hasOwnProperty.call(LAST_RUN_LABELS, status)
        ? LAST_RUN_LABELS[status] : '') || WORKFLOW_RUN_STATUS_UNAVAILABLE;
    const when = timestamp(at);
    const time = when ? formatSummaryTime(when) : '';
    return time ? `${label} · ${time}` : label;
}

function runTime(run: WorkflowRunSummary): string | null {
    if (timestamp(run.completed_at)) {
        return run.completed_at as string;
    }
    return timestamp(run.started_at) ? run.started_at as string : null;
}

/** The two lines and two buttons, from the workflow record and its runs (newest first). */
function summarizeProposalRuns(
    workflow: WorkflowDefinition,
    runs: WorkflowRunSummary[],
    resultsInChat: boolean,
    now: number,
): ProposalRunSummary {
    const newest = runs[0];
    let lastRun = '';
    if (newest) {
        lastRun = lastRunText(newest.status, runTime(newest));
    } else if (typeof workflow.last_run_status === 'string' && workflow.last_run_status) {
        lastRun = lastRunText(workflow.last_run_status, workflow.last_run_at);
    }
    const finished = runs.find((run) => isWorkflowResultReadableStatus(run.status) && workflowRunChatId(run));
    const askable = runs.find((run) => canAskAboutWorkflowRun(PERSONAL_SCOPE, run, resultsInChat));
    const askableId = askable ? workflowRunChatId(askable) : null;
    return {
        nextRun: nextRunText(workflow, now),
        lastRun,
        latestResultRunId: finished ? workflowRunChatId(finished) : null,
        followUp: askable && askableId
            ? { runId: askableId, time: formatWorkflowRunTime(runTime(askable)) }
            : null,
    };
}

function Line({ term, children }: { term: string; children: ReactNode }) {
    return (
        <div className="min-w-0 sm:grid sm:grid-cols-[8rem_minmax(0,1fr)] sm:gap-3">
            <dt className="font-medium text-text-2">{term}</dt>
            <dd className="break-words text-text-1">{children}</dd>
        </div>
    );
}

/**
 * The next run, the last run and links to its results, for a workflow the reader can use.
 *
 * Nothing is read or drawn unless the reader may use workflows: the workflow routes would
 * refuse anyway. Follow up opens a new chat about the newest finished run, as Ask in chat does.
 * The workflow name is user-authored and only ever rendered as text.
 */
export function WorkflowProposalRunSummary({ workflowId, workflowName }: { workflowId: string; workflowName: string }) {
    const workflowsAllowed = useBootstrapStore((state) => state.data?.features?.allow_user_workflows === true);
    const resultsInChat = useBootstrapStore((state) =>
        state.data?.features?.enable_chat_workflow_results === true);
    const navigate = useNavigate();
    const { pathname } = useLocation();
    const usable = workflowsAllowed && isWorkflowResultIdentifier(workflowId);
    const [state, setState] = useState<SummaryState>({ kind: 'loading' });

    useEffect(() => {
        if (!usable) {
            return undefined;
        }
        const controller = new AbortController();
        setState({ kind: 'loading' });
        Promise.all([
            fetchScopedWorkflows(PERSONAL_SCOPE, controller.signal),
            fetchScopedWorkflowRuns(PERSONAL_SCOPE, workflowId, controller.signal),
        ]).then(([workflows, runs]) => {
            if (controller.signal.aborted) {
                return;
            }
            const workflow = workflows.find((entry) => entry.id === workflowId);
            setState(workflow
                ? { kind: 'ready', summary: summarizeProposalRuns(workflow, runs, resultsInChat, Date.now()) }
                : { kind: 'unavailable' });
        }, () => {
            if (!controller.signal.aborted) {
                setState({ kind: 'unavailable' });
            }
        });
        return () => controller.abort();
    }, [usable, workflowId, resultsInChat]);

    if (!usable || state.kind === 'loading') {
        return null;
    }
    if (state.kind === 'unavailable') {
        return (
            <p data-workflow-proposal-runs="unavailable" className="break-words text-text-3">
                {WORKFLOW_PROPOSAL_RUNS_UNAVAILABLE_TEXT}
            </p>
        );
    }
    const { nextRun, lastRun, latestResultRunId, followUp } = state.summary;
    const name = workflowName || 'this workflow';
    return (
        <div data-workflow-proposal-runs="" className="min-w-0 space-y-2">
            <dl className="space-y-1.5">
                {nextRun ? <Line term="Next run">{nextRun}</Line> : null}
                <Line term="Last run">{lastRun || WORKFLOW_PROPOSAL_NO_RUNS_TEXT}</Line>
            </dl>
            {latestResultRunId || followUp ? (
                <div className="flex flex-wrap items-center gap-2">
                    {latestResultRunId ? (
                        <Link to={workflowRunHref(workflowId, latestResultRunId)}
                            aria-label={`Open latest results of ${name}`}
                            className={LINK_CLASS}>
                            Open latest results
                        </Link>
                    ) : null}
                    {followUp ? (
                        <GlassButton
                            type="button"
                            size="sm"
                            variant="subtle"
                            aria-label={followUp.time
                                ? `Follow up on the ${name} run of ${followUp.time} in a new chat`
                                : `Follow up on the latest ${name} results in a new chat`}
                            onClick={() => followUpWorkflowResult(
                                { workflow_id: workflowId, run_id: followUp.runId },
                                { navigate, pathname },
                            )}
                        >
                            <MessageSquare size={13} aria-hidden="true" />
                            Follow up
                        </GlassButton>
                    ) : null}
                </div>
            ) : null}
        </div>
    );
}
