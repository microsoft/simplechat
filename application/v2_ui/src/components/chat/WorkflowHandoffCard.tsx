// WorkflowHandoffCard.tsx
// The one-time workflow a plan handed large work off to, under the answer that prepared it.
//
// A request too big to finish inside one plan, such as reviewing every contract in a workspace,
// makes the plan prepare a one-time workflow: a For each over the named documents or a workspace
// search, then a report. Nothing is created or run until the requester decides. The card shows
// what the workflow covers and what each task runs on, and offers only the actions the server
// allows: Accept, Edit and Decline. Once the run is queued, the card follows it through the tab's
// workflow run tracker, and 6b-1 posts its outcome back into the chat. Every state is read back
// from the server, so a reload or a second tab shows the same hand-off. Workflow names, task
// titles, agent names and workspace names render as plain text.

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { Link } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { GlassButton } from '../ui/primitives';
import { WorkflowEditorDialog } from '../workflows/WorkflowEditorDialog';
import { LiveRunRow } from './WorkflowRunCard';
import { ApiError } from '../../lib/apiClient';
import { kickWorkflowRunTracker, requestWorkflowConversationRuns } from '../../lib/useWorkflowRunTracker';
import {
    fetchWorkflowEditorOptions,
    normalizeWorkflowDefinition,
    type WorkflowDefinition,
    type WorkflowEditorOptions,
    type WorkflowScope,
} from '../../lib/workflowEditor';
import {
    acceptWorkflowHandoff,
    denyWorkflowHandoff,
    fetchWorkflowHandoffDraft,
    handoffWaitingText,
    listWorkflowHandoffs,
    workflowHandoffEdit,
    workflowHandoffErrorText,
    workflowHandoffReasonText,
    workflowHandoffRetryable,
    workflowHandoffRunStatusLabel,
    workflowHandoffTrackedRun,
    WORKFLOW_HANDOFF_LOAD_FALLBACK,
    type WorkflowHandoffAccepted,
    type WorkflowHandoffItem,
    type WorkflowHandoffState,
} from '../../lib/workflowHandoffs';
import { workflowProposalLink } from '../../lib/workflowProposals';
import { formatCheckedTime, WORKFLOW_STATUS_HALTED_TEXT } from '../../lib/workflowRunStatus';
import { workflowRunHref } from '../../lib/workflowRunLink';
import {
    useWorkflowRunTrackerStore,
    workflowRunConversationRead,
    workflowRunsCheckedAt,
} from '../../stores/workflowRunTrackerStore';

const PERSONAL_SCOPE: WorkflowScope = { type: 'personal' };
// The server holds a decision claim this long; a card still creating after it asks the reader to check.
const CREATING_POLL_MS = 3000;
const CREATING_POLL_LIMIT = 40;
const CREATING_WINDOW_MS = 120_000;
const URL_ACCESS_REFUSED = 'URL Access is not available for workflows created from chat.';
// The server refuses an edit that breaks these, so the card says so before the editor opens.
const EDIT_LIMITS = 'Edits keep the trigger manual and keep the For each over documents or a workspace search. '
    + 'Tasks can use only your own local agents, and URL Access and Run as aren\'t available.';
const NOT_SAVED = 'Not saved. Your draft has been retained.';
const DRAFT_RETAINED = 'Your draft has been retained.';
const EDITOR_FALLBACK = 'The workflow editor could not be opened. Try again.';
const STATIC_FOOTNOTE = 'Status when this message loaded. Open the run for its progress and results.';
const DELIVERY_TEXT = 'The run\'s outcome is posted in this chat when it ends.';
const LINK_CLASS = 'inline-flex h-8 items-center rounded-xl px-3 text-sm font-medium text-accent hover:bg-surface-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent';
const BUSY_CLASS = 'aria-disabled:cursor-not-allowed aria-disabled:opacity-50';

const STATE_LABELS: Record<WorkflowHandoffState, string> = {
    pending: 'Awaiting your decision',
    creating: 'Creating',
    created: 'Workflow created',
    queued: 'Run queued',
    denied: 'Declined',
    expired: 'Expired',
    unavailable: 'Unavailable',
    invalid: 'Can\'t be used',
};

const WARN_STATES: ReadonlySet<WorkflowHandoffState> = new Set(['expired', 'unavailable', 'invalid']);

interface CardError {
    text: string;
    /** Whether the same accept, tried again, can succeed. */
    retry: boolean;
}

function stateNote(item: WorkflowHandoffItem): string {
    if (item.reason === 'workflow_deleted') return workflowHandoffReasonText(item.reason);
    switch (item.state) {
        case 'pending':
            return 'Nothing runs until you choose.';
        case 'creating':
            return 'Creating the workflow.';
        case 'created':
            return 'The workflow was created, but its run has not started.';
        case 'queued':
            return 'The workflow was created and its run was queued.';
        case 'denied':
            return 'You declined this hand-off. Nothing was created.';
        case 'expired':
            return 'This hand-off expired. Ask again in chat for a new one.';
        default:
            return workflowHandoffReasonText(item.reason ?? '');
    }
}

function expiryText(value: string | null): string {
    const date = value ? new Date(value) : null;
    return date && !Number.isNaN(date.getTime()) ? `You can decide until ${date.toLocaleString()}.` : '';
}

/** The hand-off as an accept left it, until the next status read replaces it. */
function afterAccept(item: WorkflowHandoffItem, response: WorkflowHandoffAccepted): WorkflowHandoffItem {
    return {
        ...item,
        state: 'queued',
        reason: null,
        actions: [],
        workflow: response.workflow,
        run: response.run,
        chat_delivery: response.chat_delivery,
    };
}

function afterDeny(item: WorkflowHandoffItem): WorkflowHandoffItem {
    return { ...item, state: 'denied', reason: null, actions: [] };
}

/** Ask the tab's tracker to read this chat's runs now, so a queued run shows its live status. */
function followRun(conversationId: string): void {
    kickWorkflowRunTracker({ immediate: true });
    void requestWorkflowConversationRuns(conversationId, { force: true });
}

function Detail({ term, children }: { term: string; children: ReactNode }) {
    return (
        <div className="min-w-0 sm:grid sm:grid-cols-[8rem_minmax(0,1fr)] sm:gap-3">
            <dt className="font-medium text-text-2">{term}</dt>
            <dd className="break-words text-text-1">{children}</dd>
        </div>
    );
}

function HandoffDetails({ item }: { item: WorkflowHandoffItem }) {
    const { summary, disclosure } = item;
    if (!summary && !disclosure) return null;
    return (
        <>
            {summary?.description ? <p className="break-words text-text-2">{summary.description}</p> : null}
            <dl className="space-y-1.5">
                {disclosure ? <Detail term="Covers">{disclosure.text}</Detail> : null}
                {disclosure?.scope_names.length ? (
                    <Detail term="Workspaces">{disclosure.scope_names.join(', ')}</Detail>
                ) : null}
                {summary?.one_time ? <Detail term="Runs">Once, when you accept. It is not scheduled.</Detail> : null}
                {summary?.alerts_every_run ? (
                    <Detail term="Alerts">A notification after every run, severity Info.</Detail>
                ) : null}
                {summary?.durable ? (
                    <Detail term="Durable">Each run saves checkpoints and can resume after an interruption.</Detail>
                ) : null}
            </dl>
            {summary?.tasks.length ? (
                <ol aria-label="Workflow tasks" className="space-y-2">
                    {summary.tasks.map((task, index) => (
                        <li key={index} className="min-w-0 space-y-1 rounded-lg border border-edge bg-surface-1 p-2">
                            <p className="break-words font-medium text-text-1">{`${index + 1}. ${task.title || 'Untitled task'}`}</p>
                            <p className="break-words text-text-2">
                                {task.runner === 'agent'
                                    ? `Runs with the agent ${task.agent_name || 'chosen for it'}.`
                                    : 'Runs with the default model.'}
                            </p>
                        </li>
                    ))}
                </ol>
            ) : null}
        </>
    );
}

/**
 * The run a queued hand-off started. While the tab's tracker has read it, the run shows live, with
 * the same row and controls as any run a plan started; until then it shows its status from the
 * last list read and a link to the run.
 */
function HandoffRun({
    item, conversationId, name, liveRunStatus,
}: {
    item: WorkflowHandoffItem;
    conversationId: string;
    name: string;
    liveRunStatus: boolean;
}) {
    const snapshot = useWorkflowRunTrackerStore((state) => state.snapshot);
    const live = liveRunStatus && snapshot.running && !snapshot.halted;
    const available = snapshot.available === true;
    const runId = item.run?.id ?? '';
    const workflowId = item.workflow?.id ?? '';
    const tracked = liveRunStatus ? workflowHandoffTrackedRun(snapshot.runs, conversationId, item) : undefined;

    useEffect(() => {
        if (live && runId) {
            void requestWorkflowConversationRuns(conversationId);
        }
    }, [live, runId, conversationId]);

    if (!item.run) return null;
    const read = workflowRunConversationRead(snapshot, conversationId);
    const checkedTime = tracked ? formatCheckedTime(workflowRunsCheckedAt(snapshot, conversationId)) : '';
    const problem = liveRunStatus && snapshot.halted ? WORKFLOW_STATUS_HALTED_TEXT : (live ? read.error ?? '' : '');
    const checkNow = () => {
        if (read.reading) return;
        kickWorkflowRunTracker();
        void requestWorkflowConversationRuns(conversationId, { force: true });
    };

    return (
        <div className="min-w-0 space-y-2">
            {tracked && workflowId ? (
                <ul className="min-w-0 space-y-2">
                    <LiveRunRow
                        conversationId={conversationId}
                        name={name}
                        run={{ workflowId, runId }}
                        tracked={tracked}
                        live={live}
                        available={available}
                        heading="Handed-off workflow"
                        waitingText={handoffWaitingText}
                    />
                </ul>
            ) : (
                <div className="flex flex-wrap items-center gap-2">
                    <p className="break-words text-text-2">{`Run: ${workflowHandoffRunStatusLabel(item.run.status)}`}</p>
                    {workflowId ? (
                        <Link to={workflowRunHref(workflowId, runId)} aria-label={`Open run of ${name}`} className={LINK_CLASS}>
                            Open run
                        </Link>
                    ) : null}
                </div>
            )}
            {item.chat_delivery ? <p className="break-words text-text-2">{DELIVERY_TEXT}</p> : null}
            <div className="flex flex-wrap items-center gap-2">
                <p aria-live="polite" className="text-[11px] text-text-3">
                    {checkedTime ? `Checked ${checkedTime}` : STATIC_FOOTNOTE}
                </p>
                {live ? (
                    <GlassButton type="button" size="sm" variant="ghost" className={BUSY_CLASS}
                        aria-disabled={read.reading || undefined} onClick={checkNow}>
                        {read.reading ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : null}
                        Check now
                    </GlassButton>
                ) : null}
            </div>
            <p role="status" className={problem ? 'break-words text-warn' : 'sr-only'}>{problem}</p>
        </div>
    );
}

function HandoffCard({
    item, runId, conversationId, liveRunStatus, onChanged, onRefresh, onCheckAgain, pollingStopped,
}: {
    item: WorkflowHandoffItem;
    runId: string;
    conversationId: string;
    liveRunStatus: boolean;
    onChanged: (item: WorkflowHandoffItem) => void;
    onRefresh: () => void;
    onCheckAgain: () => void;
    pollingStopped: boolean;
}) {
    const headingId = useId();
    const cardRef = useRef<HTMLElement>(null);
    const [busy, setBusy] = useState<'accept' | 'deny' | 'edit' | null>(null);
    const [error, setError] = useState<CardError | null>(null);
    const [confirm, setConfirm] = useState<'accept' | 'deny' | null>(null);
    const [editor, setEditor] = useState<{
        draft: WorkflowDefinition; options: WorkflowEditorOptions; note: string;
    } | null>(null);
    // Set when a decision ends; its layout effect keeps focus in the card if the control is gone.
    const [settled, setSettled] = useState(0);
    useLayoutEffect(() => {
        if (settled && (!document.activeElement || document.activeElement === document.body)) {
            cardRef.current?.focus({ preventScroll: true });
        }
    }, [settled]);

    // An edited save waits here for the person to confirm that saving starts the run.
    const [confirmingSave, setConfirmingSave] = useState(false);
    const saveDecision = useRef<((proceed: boolean) => void) | null>(null);
    const settleSave = useCallback((proceed: boolean) => {
        const resolve = saveDecision.current;
        saveDecision.current = null;
        setConfirmingSave(false);
        resolve?.(proceed);
    }, []);
    useEffect(() => () => {
        saveDecision.current?.(false);
        saveDecision.current = null;
    }, []);

    const summary = item.summary;
    const disclosure = item.disclosure;
    // A created workflow is named as it is now: the editor or Workflows may have renamed it.
    const name = item.workflow?.name || summary?.name || 'Workflow hand-off';
    const deleted = item.reason === 'workflow_deleted';
    // Accepting a hand-off whose workflow already exists starts that workflow's run.
    const startsRun = item.state === 'created';
    const canAccept = item.actions.includes('accept');
    const canEdit = item.actions.includes('edit');
    const canDeny = item.actions.includes('deny');

    const accept = async () => {
        if (busy) return;
        setBusy('accept');
        setError(null);
        try {
            const response = await acceptWorkflowHandoff(runId, item.handoff_id, conversationId, { mode: 'as_proposed' });
            onChanged(afterAccept(item, response));
            followRun(conversationId);
        } catch (cause) {
            setError({ text: workflowHandoffErrorText(cause), retry: workflowHandoffRetryable(cause) });
        } finally {
            setBusy(null);
            setConfirm(null);
            setSettled((value) => value + 1);
            onRefresh();
        }
    };

    const deny = async () => {
        if (busy) return;
        setBusy('deny');
        setError(null);
        try {
            await denyWorkflowHandoff(runId, item.handoff_id, conversationId);
            onChanged(afterDeny(item));
        } catch (cause) {
            setError({ text: workflowHandoffErrorText(cause), retry: false });
        } finally {
            setBusy(null);
            setConfirm(null);
            setSettled((value) => value + 1);
            onRefresh();
        }
    };

    const openEditor = async () => {
        if (busy) return;
        setBusy('edit');
        setError(null);
        try {
            const [draft, options] = await Promise.all([
                fetchWorkflowHandoffDraft(runId, item.handoff_id, conversationId),
                fetchWorkflowEditorOptions(PERSONAL_SCOPE),
            ]);
            setEditor({
                draft: normalizeWorkflowDefinition(draft.workflow, PERSONAL_SCOPE), options, note: draft.url_access_note,
            });
        } catch (cause) {
            setError({ text: workflowHandoffErrorText(cause, EDITOR_FALLBACK), retry: false });
            onRefresh();
        } finally {
            setBusy(null);
        }
    };

    // Save in the editor accepts the hand-off with the edited draft; it never saves a workflow directly.
    const accepted = useRef<WorkflowHandoffAccepted | null>(null);
    const saveThroughAccept = useCallback(async (draft: WorkflowDefinition, original: WorkflowDefinition | null) => {
        const edit = workflowHandoffEdit(draft, original);
        if (!edit) {
            throw new ApiError(`${URL_ACCESS_REFUSED} ${editor?.note ?? ''}`.trim(), 400, undefined);
        }
        const proceed = await new Promise<boolean>((resolve) => {
            saveDecision.current?.(false);
            saveDecision.current = resolve;
            setConfirmingSave(true);
        });
        if (!proceed) throw new ApiError(NOT_SAVED, 400, undefined);
        try {
            const response = await acceptWorkflowHandoff(
                runId, item.handoff_id, conversationId, { mode: 'edited', workflow: edit.workflow },
            );
            accepted.current = response;
            return { workflow: { ...edit.payload, ...response.workflow } };
        } catch (cause) {
            // Signing in again is the editor's to handle. Any other refusal must keep the draft, which
            // the editor discards on a 403 or 404 and reads as a stale saved workflow on a 409.
            if (cause instanceof ApiError && cause.status === 401) throw cause;
            onRefresh();
            throw new ApiError(
                `${workflowHandoffErrorText(cause)} ${DRAFT_RETAINED}`,
                400,
                cause instanceof ApiError ? cause.payload : undefined,
            );
        }
    }, [runId, item.handoff_id, conversationId, editor?.note, onRefresh]);

    const openWorkflow = Boolean(item.workflow) && !deleted && !(item.state === 'queued' && item.run);
    const expiry = item.state === 'pending' ? expiryText(item.expires_at) : '';
    return (
        <article ref={cardRef} tabIndex={-1} aria-labelledby={headingId}
            className="min-w-0 space-y-2 rounded-xl border border-edge bg-surface-2 p-3 text-xs outline-none focus-visible:ring-2 focus-visible:ring-accent">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                    <p className="text-text-3">Workflow hand-off</p>
                    <h4 id={headingId} className="break-words text-sm font-medium text-text-1">{name}</h4>
                </div>
                <p role="status" className={clsx('rounded px-2 py-0.5 font-medium',
                    deleted || WARN_STATES.has(item.state) ? 'bg-warn-soft text-warn'
                        : item.state === 'queued' ? 'bg-ok-soft text-ok'
                        : 'bg-surface-3 text-text-2')}>
                    {deleted ? 'Workflow deleted' : STATE_LABELS[item.state]}
                </p>
            </div>
            <HandoffDetails item={item} />
            <p className="break-words text-text-2">{[stateNote(item), expiry].filter(Boolean).join(' ')}</p>
            {item.state === 'creating' && pollingStopped ? (
                <p className="break-words text-text-2">
                    This is taking longer than expected.{' '}
                    <GlassButton size="sm" variant="ghost" onClick={onCheckAgain}>Check again</GlassButton>
                </p>
            ) : null}
            {item.state === 'queued' && !deleted ? (
                <HandoffRun item={item} conversationId={conversationId} name={name} liveRunStatus={liveRunStatus} />
            ) : null}
            {error ? (
                <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg bg-danger-soft p-2 text-danger">
                    <span className="min-w-0 break-words">{error.text}</span>
                    {error.retry && (item.state === 'creating' || canAccept) ? (
                        <GlassButton size="sm" variant="ghost" disabled={Boolean(busy)} onClick={() => void accept()}>
                            Try again
                        </GlassButton>
                    ) : null}
                </div>
            ) : null}
            {canAccept || canEdit || canDeny || openWorkflow ? (
                <div className="flex flex-wrap items-center gap-2">
                    {canAccept ? (
                        <GlassButton size="sm" variant="primary" disabled={Boolean(busy)} onClick={() => setConfirm('accept')}>
                            {busy === 'accept' ? 'Starting…' : startsRun ? 'Start its run' : 'Accept'}
                        </GlassButton>
                    ) : null}
                    {canEdit ? (
                        <GlassButton size="sm" variant="ghost" disabled={Boolean(busy)} onClick={() => void openEditor()}
                            aria-label={`Edit ${name} before accepting it`}>
                            {busy === 'edit' ? 'Opening…' : 'Edit'}
                        </GlassButton>
                    ) : null}
                    {canDeny ? (
                        <GlassButton size="sm" variant="danger" disabled={Boolean(busy)} onClick={() => setConfirm('deny')}>
                            Decline
                        </GlassButton>
                    ) : null}
                    {openWorkflow && item.workflow ? (
                        <Link to={workflowProposalLink(item.workflow.id)} className={LINK_CLASS}>
                            Open workflow
                        </Link>
                    ) : null}
                </div>
            ) : null}
            {canEdit ? <p className="break-words text-text-3">{EDIT_LIMITS}</p> : null}
            {confirm === 'accept' ? (
                <ConfirmDialog
                    title={startsRun ? 'Start the run of this workflow?' : 'Accept this workflow hand-off?'}
                    description={startsRun
                        ? `SimpleChat starts the one run of ${name} now.`
                        : `SimpleChat creates ${name} and starts its one run now.`}
                    confirmLabel={startsRun ? 'Start its run' : 'Accept'}
                    tone="primary"
                    busy={busy === 'accept'}
                    onConfirm={() => void accept()}
                    onClose={() => { if (busy !== 'accept') setConfirm(null); }}>
                    {!startsRun && disclosure ? (
                        <dl className="space-y-1.5 text-xs">
                            <Detail term="Covers">{disclosure.text}</Detail>
                            {disclosure.scope_names.length ? (
                                <Detail term="Workspaces">{disclosure.scope_names.join(', ')}</Detail>
                            ) : null}
                        </dl>
                    ) : (
                        <p className="text-xs text-text-2">It runs once and is not scheduled.</p>
                    )}
                </ConfirmDialog>
            ) : null}
            {confirm === 'deny' ? (
                <ConfirmDialog
                    title="Decline this workflow hand-off?"
                    description={`SimpleChat will not create ${name}.`}
                    confirmLabel="Decline"
                    busy={busy === 'deny'}
                    onConfirm={() => void deny()}
                    onClose={() => { if (busy !== 'deny') setConfirm(null); }}>
                    <p className="text-xs text-text-2">You can ask again in chat at any time.</p>
                </ConfirmDialog>
            ) : null}
            {editor ? (
                <WorkflowEditorDialog
                    scope={PERSONAL_SCOPE}
                    workflow={null}
                    initialDraft={editor.draft}
                    options={editor.options}
                    onSaveOverride={saveThroughAccept}
                    onClose={() => {
                        setEditor(null);
                        onRefresh();
                    }}
                    onSaved={() => {
                        const response = accepted.current;
                        accepted.current = null;
                        setEditor(null);
                        if (response) {
                            onChanged(afterAccept(item, response));
                            followRun(conversationId);
                        }
                        setSettled((value) => value + 1);
                        onRefresh();
                    }}
                />
            ) : null}
            {confirmingSave ? (
                <ConfirmDialog
                    title="Save and start this workflow?"
                    description="Saving creates this workflow and starts its one run now."
                    confirmLabel="Save and start"
                    tone="primary"
                    onConfirm={() => settleSave(true)}
                    onClose={() => settleSave(false)}>
                    <p className="text-xs text-text-2">{EDIT_LIMITS}</p>
                </ConfirmDialog>
            ) : null}
        </article>
    );
}

/**
 * Every workflow hand-off a run prepared, for its requester, in a personal conversation.
 *
 * The caller mounts this only when the answer's run completed a hand-off step. The status route
 * decides what each card may show and offer; a run the reader cannot open renders nothing.
 */
export function WorkflowHandoffCards({
    conversationId, runId, liveRunStatus,
}: {
    conversationId: string;
    runId: string;
    /** The tab keeps a workflow run tracker, so a queued run can show its live status. */
    liveRunStatus: boolean;
}) {
    const [items, setItems] = useState<WorkflowHandoffItem[] | null>(null);
    const [loadError, setLoadError] = useState('');
    const [missing, setMissing] = useState(false);
    const [pollingStopped, setPollingStopped] = useState(false);
    const request = useRef<AbortController | null>(null);

    const refresh = useCallback(async () => {
        request.current?.abort();
        const controller = new AbortController();
        request.current = controller;
        try {
            const list = await listWorkflowHandoffs(runId, conversationId, controller.signal);
            if (controller.signal.aborted) return;
            setItems(list.handoffs);
            setLoadError('');
        } catch (cause) {
            if (controller.signal.aborted) return;
            if (cause instanceof ApiError && cause.status === 404) {
                setMissing(true);
                return;
            }
            setLoadError(workflowHandoffErrorText(cause, WORKFLOW_HANDOFF_LOAD_FALLBACK));
        } finally {
            if (request.current === controller) request.current = null;
        }
    }, [runId, conversationId]);

    useEffect(() => {
        void refresh();
        return () => request.current?.abort();
    }, [refresh]);

    // While a decision is being made elsewhere, check back briefly: stop when the server's claim
    // window has passed or after a fixed number of checks, and wait while the tab is hidden.
    const creating = Boolean(items?.some((item) => item.state === 'creating'));
    const [pollRound, setPollRound] = useState(0);
    useEffect(() => {
        if (!creating) {
            setPollingStopped(false);
            return undefined;
        }
        const started = Date.now();
        let polls = 0;
        let stopped = false;
        const tick = () => {
            if (stopped || document.hidden) return;
            if (polls >= CREATING_POLL_LIMIT || Date.now() - started >= CREATING_WINDOW_MS) {
                stopped = true;
                window.clearInterval(timer);
                setPollingStopped(true);
                return;
            }
            // A slow answer is left to finish rather than abandoned for the next check.
            if (request.current) return;
            polls += 1;
            void refresh();
        };
        const timer = window.setInterval(tick, CREATING_POLL_MS);
        const onVisibility = () => {
            if (!document.hidden) tick();
        };
        document.addEventListener('visibilitychange', onVisibility);
        return () => {
            stopped = true;
            window.clearInterval(timer);
            document.removeEventListener('visibilitychange', onVisibility);
        };
    }, [creating, refresh, pollRound]);

    const replace = useCallback((next: WorkflowHandoffItem) => {
        setItems((current) => current?.map((item) => (item.handoff_id === next.handoff_id ? next : item)) ?? current);
    }, []);
    const refreshNow = useCallback(() => {
        void refresh();
    }, [refresh]);
    const checkAgain = useCallback(() => {
        setPollingStopped(false);
        setPollRound((round) => round + 1);
        void refresh();
    }, [refresh]);

    if (missing || (!loadError && !items?.length)) return null;
    return (
        <section aria-label="Workflow hand-offs" className="mt-3 min-w-0 space-y-2">
            {loadError ? (
                // A refusal on load is a state of the answer, not news, so it is announced politely.
                <div role="status" className="flex flex-wrap items-center gap-2 rounded-lg bg-warn-soft p-2 text-xs text-warn">
                    <span className="break-words">{loadError}</span>
                    <GlassButton size="sm" variant="ghost" onClick={checkAgain}>Try again</GlassButton>
                </div>
            ) : null}
            {items?.map((item) => (
                <HandoffCard key={item.handoff_id} item={item} runId={runId} conversationId={conversationId}
                    liveRunStatus={liveRunStatus} onChanged={replace} onRefresh={refreshNow}
                    onCheckAgain={checkAgain} pollingStopped={pollingStopped} />
            ))}
        </section>
    );
}
