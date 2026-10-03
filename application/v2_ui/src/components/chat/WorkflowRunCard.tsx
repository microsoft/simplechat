// WorkflowRunCard.tsx
// The live status of the saved workflows a plan started, under the answer that started them.
//
// Phase 5's WorkflowRunLinks shows each run as it stood when the answer loaded. With live status
// on, this card shows the same runs as the tab's one workflow run tracker last read them: how far a
// running run has got, what a run waiting on the reader needs, where a finished run's results went,
// and why a run stopped. The tracker owns every request. The card only asks it to read this chat's
// runs, once on mount and again from Check now, and a run it hasn't read yet keeps its static link.
//
// Every control comes from the row's server-computed actions, never from its status alone, and a
// row this client can't read says "Status unavailable" and offers only Open run. Approving never
// happens here: it opens the run, where the gate's own prompt and choices are shown. Workflow names
// and every other server string render as plain text.

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { Link } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { GlassButton } from '../ui/primitives';
import { RunLink, useWorkflowRunLinkList } from './WorkflowRunLinks';
import { M365_CONNECT_HREF } from '../../lib/m365Links';
import { workflowRunDisplayName, type WorkflowRunLinkItem } from '../../lib/orchestrationWorkflowRuns';
import { useFocusFallback } from '../../lib/useFocusFallback';
import { useWorkflowRunAction } from '../../lib/useWorkflowRunAction';
import { kickWorkflowRunTracker, requestWorkflowConversationRuns } from '../../lib/useWorkflowRunTracker';
import { workflowDeliveryFooterId } from '../../lib/workflowDelivery';
import { workflowRunHref } from '../../lib/workflowRunLink';
import {
    formatCheckedTime,
    formatWorkflowElapsed,
    workflowRetryBlockedText,
    workflowRunRowControls,
    workflowRunStatusLabel,
    workflowRunStepLabel,
    workflowRunStepText,
    workflowWaitingText,
    WORKFLOW_RESULTS_IN_HISTORY_TEXT,
    WORKFLOW_RESULTS_POSTED_ELSEWHERE_TEXT,
    WORKFLOW_RESULTS_POSTED_TEXT,
    WORKFLOW_RESULTS_POSTING_TEXT,
    WORKFLOW_RETRY_TURNED_OFF_TEXT,
    WORKFLOW_RUN_CANCELLED_TEXT,
    WORKFLOW_RUN_STATUS_UNAVAILABLE,
    WORKFLOW_STATUS_HALTED_TEXT,
    type WorkflowRunStatusRow,
} from '../../lib/workflowRunStatus';
import type { TrackedWorkflowRun } from '../../lib/workflowRunTracker';
import { useChatStore } from '../../stores/chatStore';
import {
    useWorkflowRunTrackerStore,
    workflowRunConversationRead,
    workflowRunForAnswerStep,
    workflowRunsCheckedAt,
} from '../../stores/workflowRunTrackerStore';

const STATIC_FOOTNOTE = 'Status when this message loaded. Open the run for its progress and results.';
const LINK_CLASS = 'inline-flex h-8 items-center rounded-xl px-3 text-sm font-medium text-accent hover:bg-surface-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent';
const BUSY_CLASS = 'aria-disabled:cursor-not-allowed aria-disabled:opacity-50';
const FLASH_CLASSES = ['ring-2', 'ring-accent', 'rounded-2xl'];
const FLASH_MS = 1400;

function statusTone(row: WorkflowRunStatusRow | null): string {
    switch (row?.status) {
        case 'completed':
            return 'bg-ok-soft text-ok';
        case 'failed':
        case 'expired':
        case 'cancelled':
        case 'completed_partial':
            return 'bg-warn-soft text-warn';
        case 'waiting':
            return 'bg-accent-soft text-accent';
        default:
            return 'bg-surface-3 text-text-2';
    }
}

/** Bring a delivered message into view, flash it as the drawer's jump does, and move focus to its footer. */
function showDeliveredMessage(messageId: string): void {
    const message = document.getElementById(`message-${messageId}`);
    if (!message) {
        return;
    }
    message.scrollIntoView({ behavior: 'smooth', block: 'center' });
    message.classList.add(...FLASH_CLASSES);
    window.setTimeout(() => message.classList.remove(...FLASH_CLASSES), FLASH_MS);
    document.getElementById(workflowDeliveryFooterId(messageId))?.focus({ preventScroll: true });
}

function OpenRunLink({ workflowId, runId, name }: { workflowId: string; runId: string; name: string }) {
    return (
        <Link to={workflowRunHref(workflowId, runId)} aria-label={`Open run of ${name}`} className={LINK_CLASS}>
            Open run
        </Link>
    );
}

/** What a finished run's card says about its results. */
function FinishedText({ row, conversationId }: { row: WorkflowRunStatusRow; conversationId: string }) {
    const { status, message_id: messageId } = row.delivery;
    const delivered = status === 'delivered' && messageId !== null;
    // Only a message on screen in this chat can be jumped to.
    const shown = useChatStore((state) =>
        delivered
        && state.activeConversationId === conversationId
        && state.messages.some((message) => message.id === messageId));
    if (delivered && shown) {
        return (
            <GlassButton type="button" size="sm" variant="ghost"
                aria-label={`${WORKFLOW_RESULTS_POSTED_TEXT} for ${row.workflow_name}`}
                onClick={() => showDeliveredMessage(messageId)}>
                {WORKFLOW_RESULTS_POSTED_TEXT}
            </GlassButton>
        );
    }
    let text = WORKFLOW_RESULTS_IN_HISTORY_TEXT;
    if (status === 'delivered') {
        text = WORKFLOW_RESULTS_POSTED_ELSEWHERE_TEXT;
    } else if (status === 'pending' || status === 'delivering') {
        text = WORKFLOW_RESULTS_POSTING_TEXT;
    }
    return <p className="break-words text-text-2">{text}</p>;
}

function LiveRunRow({
    conversationId,
    item,
    run,
    tracked,
    live,
    available,
}: {
    conversationId: string;
    item: WorkflowRunLinkItem;
    run: { workflowId: string; runId: string };
    tracked: TrackedWorkflowRun;
    /** The tracker is running and not halted, so the row's actions reflect a current read. */
    live: boolean;
    available: boolean;
}) {
    const name = workflowRunDisplayName(item);
    const { pending, outcome, run: act } = useWorkflowRunAction(conversationId, run.workflowId, run.runId);
    const [confirmingCancel, setConfirmingCancel] = useState(false);
    // A run that dropped out of the tracker's complete read has stopped, and how isn't known yet.
    const row = !tracked.retired && tracked.row.kind === 'status' ? tracked.row : null;
    const controls = row ? workflowRunRowControls(row, available) : null;
    const canCancel = Boolean(live && controls?.cancel);
    const canRetry = Boolean(live && controls?.retry);
    const rowRef = useRef<HTMLLIElement>(null);
    const armRetryFocus = useFocusFallback(rowRef, canRetry, pending !== null);
    const armCancelFocus = useFocusFallback(rowRef, canCancel, confirmingCancel || pending !== null);

    const details: ReactNode[] = [];
    const actions: ReactNode[] = [];
    let openRun = true;
    if (row?.phase === 'running') {
        // A queued run hasn't started a step yet.
        const elapsed = formatWorkflowElapsed(row.elapsed_seconds);
        const progress = [
            row.status === 'running' ? workflowRunStepText(row) : '',
            workflowRunStepLabel(row),
            elapsed ? `${elapsed} elapsed` : '',
        ].filter(Boolean);
        if (progress.length > 0) {
            details.push(<p key="progress" className="break-words text-text-2">{progress.join(' · ')}</p>);
        }
        if (row.waiting) {
            details.push(<p key="waiting" className="break-words text-text-2">{workflowWaitingText(row.waiting.reason)}</p>);
        }
    } else if (row?.phase === 'needs_you' && row.waiting) {
        details.push(<p key="waiting" className="break-words text-text-2">{workflowWaitingText(row.waiting.reason)}</p>);
        if (controls?.approve) {
            // The run's own page shows the gate's prompt and choices; nothing is approved from here.
            openRun = false;
            actions.push(
                <Link key="approve" to={workflowRunHref(run.workflowId, run.runId)}
                    aria-label={`Review and approve ${name}`} className={LINK_CLASS}>
                    Review and approve
                </Link>,
            );
        } else if (controls?.reconnect) {
            actions.push(
                <a key="reconnect" href={M365_CONNECT_HREF} className={LINK_CLASS}>
                    Reconnect Microsoft 365
                </a>,
            );
        }
    } else if (row?.phase === 'finished') {
        details.push(<FinishedText key="results" row={row} conversationId={conversationId} />);
    } else if (row?.phase === 'failed') {
        details.push(<p key="error" className="break-words text-text-2">{row.error}</p>);
        if (row.retry_blocked) {
            details.push(<p key="blocked" className="break-words text-text-2">{workflowRetryBlockedText(row.retry_blocked)}</p>);
        }
        if (controls?.retryTurnedOff) {
            details.push(<p key="off" className="break-words text-text-2">{WORKFLOW_RETRY_TURNED_OFF_TEXT}</p>);
        }
    } else if (row?.phase === 'cancelled') {
        details.push(
            <p key="cancelled" className="break-words text-text-2">{row.error?.trim() || WORKFLOW_RUN_CANCELLED_TEXT}</p>,
        );
    }
    if (canRetry) {
        actions.push(
            <GlassButton key="retry" type="button" size="sm" variant="ghost" className={BUSY_CLASS}
                aria-label={`Retry run of ${name}`} aria-disabled={pending !== null || undefined}
                onClick={() => {
                    if (pending !== null) return;
                    armRetryFocus();
                    void act('retry');
                }}>
                {pending === 'retry' ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : null}
                Retry
            </GlassButton>,
        );
    }
    if (canCancel) {
        actions.push(
            <GlassButton key="cancel" type="button" size="sm" variant="ghost" className={BUSY_CLASS}
                aria-label={`Cancel run of ${name}`} aria-disabled={pending !== null || undefined}
                onClick={() => {
                    if (pending !== null) return;
                    armCancelFocus();
                    setConfirmingCancel(true);
                }}>
                {pending === 'cancel' ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : null}
                Cancel run
            </GlassButton>,
        );
    }
    if (openRun) {
        actions.push(<OpenRunLink key="open" workflowId={run.workflowId} runId={run.runId} name={name} />);
    }

    return (
        <li ref={rowRef} tabIndex={-1}
            className="min-w-0 space-y-1 rounded-xl border border-edge bg-surface-2 p-3 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                    <p className="text-text-3">Started workflow</p>
                    <p className="break-words text-sm font-medium text-text-1">{name}</p>
                </div>
                <p role="status" className={clsx('rounded px-2 py-0.5 font-medium', statusTone(row))}>
                    <span className="sr-only">{name}: </span>
                    {row ? workflowRunStatusLabel(row) : WORKFLOW_RUN_STATUS_UNAVAILABLE}
                </p>
            </div>
            {details}
            <div className="flex flex-wrap items-center gap-2">{actions}</div>
            <p role="status" className={outcome ? 'break-words text-text-2' : 'sr-only'}>{outcome}</p>
            {confirmingCancel ? (
                <ConfirmDialog
                    title="Cancel this run?"
                    description={`This asks ${name} to stop. Anything it already did stays done.`}
                    confirmLabel="Cancel run"
                    cancelLabel="Keep running"
                    busy={pending === 'cancel'}
                    onConfirm={() => {
                        void act('cancel').then(() => setConfirmingCancel(false));
                    }}
                    onClose={() => {
                        if (pending !== 'cancel') setConfirmingCancel(false);
                    }}
                >
                    <p className="text-xs text-text-2">A cancelled run can&apos;t be retried.</p>
                </ConfirmDialog>
            ) : null}
        </li>
    );
}

/**
 * The saved workflow runs an answer's plan started, with their live status, for its requester in
 * a personal conversation. Mounted instead of WorkflowRunLinks while the tab keeps a tracker.
 */
export function WorkflowRunCard({ conversationId, runId }: { conversationId: string; runId: string }) {
    const { items, loadError, missing, reload } = useWorkflowRunLinkList(conversationId, runId);
    const snapshot = useWorkflowRunTrackerStore((state) => state.snapshot);
    const live = snapshot.running && !snapshot.halted;
    const available = snapshot.available === true;
    const hasRuns = Boolean(items?.some((item) => item.run));

    useEffect(() => {
        if (live && hasRuns) {
            void requestWorkflowConversationRuns(conversationId);
        }
    }, [live, hasRuns, conversationId]);

    const rows = useMemo(() => (items ?? []).map((item) => ({
        item,
        tracked: item.run
            ? workflowRunForAnswerStep(snapshot, conversationId, runId, {
                stepId: item.step_id,
                workflowId: item.run.workflowId,
                runId: item.run.runId,
            })
            : undefined,
    })), [items, snapshot, conversationId, runId]);

    if (missing || (!loadError && !items?.length)) return null;

    const read = workflowRunConversationRead(snapshot, conversationId);
    const anyJoined = rows.some((entry) => entry.tracked !== undefined);
    const checkedTime = anyJoined ? formatCheckedTime(workflowRunsCheckedAt(snapshot, conversationId)) : '';
    const problem = snapshot.halted && hasRuns ? WORKFLOW_STATUS_HALTED_TEXT : (live ? read.error ?? '' : '');

    const checkNow = () => {
        if (read.reading) return;
        kickWorkflowRunTracker();
        void requestWorkflowConversationRuns(conversationId, { force: true });
    };

    return (
        <section aria-label="Started workflows" className="mt-3 min-w-0 space-y-2">
            {loadError ? (
                <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg bg-warn-soft p-2 text-xs text-warn">
                    <span className="break-words">{loadError}</span>
                    <GlassButton type="button" size="sm" variant="ghost" onClick={() => void reload()}>Try again</GlassButton>
                </div>
            ) : null}
            {items?.length ? (
                <>
                    <ul className="min-w-0 space-y-2">
                        {rows.map(({ item, tracked }) => (item.run && tracked ? (
                            <LiveRunRow
                                key={item.step_id}
                                conversationId={conversationId}
                                item={item}
                                run={item.run}
                                tracked={tracked}
                                live={live}
                                available={available}
                            />
                        ) : (
                            <RunLink key={item.step_id} item={item} />
                        )))}
                    </ul>
                    <div className="flex flex-wrap items-center gap-2">
                        <p aria-live="polite" className="text-[11px] text-text-3">
                            {checkedTime ? `Checked ${checkedTime}` : STATIC_FOOTNOTE}
                        </p>
                        {live && hasRuns ? (
                            <GlassButton type="button" size="sm" variant="ghost" className={BUSY_CLASS}
                                aria-disabled={read.reading || undefined} onClick={checkNow}>
                                {read.reading ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : null}
                                Check now
                            </GlassButton>
                        ) : null}
                    </div>
                    <p role="status" className={problem ? 'break-words text-xs text-warn' : 'sr-only'}>{problem}</p>
                </>
            ) : null}
        </section>
    );
}
