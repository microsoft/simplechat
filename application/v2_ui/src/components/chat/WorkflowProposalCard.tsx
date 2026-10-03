// WorkflowProposalCard.tsx
// The workflow an orchestration plan proposed, under the answer that proposed it.
//
// Nothing is created until the requester decides. The card discloses everything the workflow
// would do -- its schedule, each task's runner and full standing instructions, its Microsoft 365
// reach, its alerts -- and offers Create, Deny and Edit. After a decision it shows where the
// proposal stands, read back from the server on every load, so a reload or a second tab shows the
// same answer. All planner-written text is rendered as plain text.

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { Link } from 'react-router-dom';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { GlassButton } from '../ui/primitives';
import { WorkflowEditorDialog } from '../workflows/WorkflowEditorDialog';
import { ApiError } from '../../lib/apiClient';
import {
    fetchWorkflowEditorOptions,
    normalizeWorkflowDefinition,
    workflowForSave,
    type WorkflowDefinition,
    type WorkflowEditorOptions,
    type WorkflowScope,
} from '../../lib/workflowEditor';
import {
    acceptWorkflowProposal,
    denyWorkflowProposal,
    fetchWorkflowProposalDraft,
    fetchWorkflowProposals,
    workflowProposalLink,
    type WorkflowProposal,
    type WorkflowProposalAcceptResponse,
    type WorkflowProposalMode,
    type WorkflowProposalState,
    type WorkflowProposalSummary,
    workflowProposalMergeText as mergeTaskText,
} from '../../lib/workflowProposals';

const PERSONAL_SCOPE: WorkflowScope = { type: 'personal' };
// The server holds a decision claim this long; a card still creating after it asks the reader to check.
const CREATING_POLL_MS = 3000;
const CREATING_POLL_LIMIT = 40;
const CREATING_WINDOW_MS = 120_000;
// Classic pages: V2 has no Microsoft 365 connection or approval page of its own.
const M365_CONNECT_HREF = '/profile?tab=settings#m365-connection-status';
const M365_APPROVALS_HREF = '/approvals';
const URL_ACCESS_REFUSED = 'URL Access is not available for workflows created from chat.';

const STATE_LABELS: Record<WorkflowProposalState, string> = {
    pending: 'Awaiting your decision',
    creating: 'Creating',
    created_enabled: 'Created',
    created_paused: 'Created, paused',
    denied: 'Denied',
    deleted: 'Workflow deleted',
    expired: 'Expired',
    unavailable: 'Unavailable',
};

// Why a proposal cannot be used. Fixed text: the server sends only the closed reason.
const REASON_TEXT: Record<string, string> = {
    workflows_unavailable: 'Personal workflows are not available to you right now.',
    quota_reached: 'You have reached the limit on workflows created from chat. Delete one in Workflows to make room.',
    model_unavailable: 'The default model is not available for workflows, so this proposal cannot be created.',
    no_suitable_agent: 'None of your agents can do everything this workflow needs.',
    agent_unavailable: 'The agent this workflow uses is no longer available to you.',
    file_sync_source_unavailable: 'A File Sync source this workflow uses is no longer available to you.',
    reference_unavailable: 'A document this workflow uses is no longer available to you.',
    cadence_below_minimum: 'This schedule runs more often than workflows created from chat allow.',
    proposal_unavailable: 'This proposal cannot be created as planned.',
    content_review: 'This response is in content review, so its proposal cannot be used.',
    workflow_proposals_disabled: 'Workflow proposals are turned off.',
    workflow_role_required: 'You need workflow access to use this proposal.',
    workflow_shared_conversation: 'Workflow proposals are available only in your own conversations.',
};
const REASON_FALLBACK = 'This proposal is not available.';

const ACTION_LABELS: Record<string, string> = {
    email: 'Email',
    calendar: 'Calendar',
    onedrive: 'OneDrive',
    sharepoint: 'SharePoint',
    directory: 'Directory',
    openapi: 'API calls',
    mcp: 'MCP tools',
    other: 'Other tools',
};

const SIMILAR_LABELS: Record<string, string> = {
    same_sources: 'same sources',
    same_schedule: 'same schedule',
    similar_name: 'similar name',
};

function actionList(kinds: readonly string[]): string {
    return kinds.map((kind) => ACTION_LABELS[kind] ?? kind).join(', ');
}

function countLabel(count: number, one: string, many: string): string {
    return `${count.toLocaleString()} ${count === 1 ? one : many}`;
}

function errorText(cause: unknown, fallback: string): string {
    return cause instanceof Error && cause.message ? cause.message : fallback;
}

function whenText(summary: WorkflowProposalSummary): string {
    if (summary.trigger_type === 'manual') return 'Only when you start it from Workflows.';
    if (summary.trigger_type === 'file_sync') {
        const sources = summary.file_sync_sources.length ? summary.file_sync_sources.join(', ') : 'its File Sync source';
        return `Runs when File Sync finds changes in ${sources}.`;
    }
    return summary.schedule_label || 'On a schedule.';
}

function howOftenText(summary: WorkflowProposalSummary): string {
    const runs = summary.runs_per_month;
    if (runs.kind === 'manual') return 'Only when you start it.';
    if (runs.kind === 'on_change') {
        return runs.checks_per_month
            ? `Only when changes are found. Checks about ${countLabel(runs.checks_per_month, 'time', 'times')} a month.`
            : 'Only when changes are found.';
    }
    return runs.value ? `About ${countLabel(runs.value, 'run', 'runs')} a month.` : 'On its schedule.';
}

function alertsText(summary: WorkflowProposalSummary): string {
    const when = summary.alerts.mode === 'failures_only'
        ? 'A notification only when a run fails'
        : 'A notification after every run';
    return `${when}, severity ${summary.alerts.severity === 'low' ? 'Low' : 'Info'}. It appears in your notifications and never pops up.`;
}

function stateNote(proposal: WorkflowProposal): string {
    const trigger = proposal.summary?.trigger_type;
    switch (proposal.state) {
        case 'pending':
            return 'Nothing is created until you choose.';
        case 'creating':
            return 'Creating the workflow.';
        case 'created_enabled':
            return trigger === 'manual' ? 'Created. It runs only when you start it from Workflows.'
                : trigger === 'file_sync' ? 'Created and turned on. It runs when File Sync finds changes.'
                : 'Created and turned on.';
        case 'created_paused':
            return 'Created paused. Turn it on in Workflows when you are ready.';
        case 'denied':
            return 'You denied this proposal. Nothing was created.';
        case 'deleted':
            return proposal.actions.create_again
                ? 'You deleted the workflow this proposal created. Create again makes a new one, paused.'
                : 'You deleted the workflow this proposal created.';
        case 'expired':
            return 'This proposal expired. Ask in chat again for a new one.';
        default:
            return (proposal.reason && REASON_TEXT[proposal.reason]) || REASON_FALLBACK;
    }
}

function expiryText(value: string | null): string {
    const date = value ? new Date(value) : null;
    return date && !Number.isNaN(date.getTime()) ? `You can decide until ${date.toLocaleString()}.` : '';
}

/** The proposal as a decision left it, until the next status read replaces it. */
function afterAccept(proposal: WorkflowProposal, response: WorkflowProposalAcceptResponse): WorkflowProposal {
    return {
        ...proposal,
        state: response.state,
        reason: null,
        workflow: response.workflow,
        actions: { accept: false, edit: false, deny: false, create_again: false, open_workflow: true },
    };
}

function afterDeny(proposal: WorkflowProposal): WorkflowProposal {
    return {
        ...proposal,
        state: 'denied',
        actions: { accept: false, edit: false, deny: false, create_again: false, open_workflow: false },
    };
}

function Detail({ term, children }: { term: string; children: ReactNode }) {
    return (
        <div className="min-w-0 sm:grid sm:grid-cols-[8rem_minmax(0,1fr)] sm:gap-3">
            <dt className="font-medium text-text-2">{term}</dt>
            <dd className="break-words text-text-1">{children}</dd>
        </div>
    );
}

function Microsoft365({ proposal }: { proposal: WorkflowProposal }) {
    const m365 = proposal.m365;
    if (!m365 || (!m365.required && !m365.sources.length && !m365.can_send && m365.run_as !== 'self')) return null;
    const created = proposal.state === 'created_enabled' || proposal.state === 'created_paused';
    const runAsSelf = m365.run_as === 'self';
    return (
        <>
            {m365.sources.length || m365.can_send ? (
                <Detail term="Microsoft 365">
                    {m365.sources.length ? `Uses ${actionList(m365.sources)}.` : null}
                    {m365.can_send ? ' Can send email or calendar invitations.' : null}
                </Detail>
            ) : null}
            <Detail term="Run as">
                {runAsSelf ? 'You. Microsoft 365 steps use your account.' : 'No one. It does not use a Microsoft 365 account.'}
                {runAsSelf && m365.required ? (
                    m365.approval_state === 'approved' ? ' Run as is approved.'
                        : m365.approval_state === 'waiting' ? (
                            <> A run is waiting for your approval. <a href={M365_APPROVALS_HREF}
                                className="font-medium text-accent underline underline-offset-2">Review Run as approval</a></>
                        )
                        : created ? ' The first run will wait for you to approve Run as.'
                        : ' Before its first run, you approve Run as.'
                ) : null}
            </Detail>
            {m365.required && m365.connected === false ? (
                <p className="rounded-lg bg-warn-soft p-2 text-warn">
                    Microsoft 365 is not connected for workflows.{' '}
                    <a href={M365_CONNECT_HREF} className="font-medium underline underline-offset-2">
                        Connect Microsoft 365 for workflows
                    </a>
                </p>
            ) : null}
        </>
    );
}

function ProposalDetails({ proposal }: { proposal: WorkflowProposal }) {
    const summary = proposal.summary;
    if (!summary) return null;
    return (
        <>
            {summary.description ? <p className="break-words text-text-2">{summary.description}</p> : null}
            <dl className="space-y-1.5">
                <Detail term="When">{whenText(summary)}</Detail>
                <Detail term="How often">{howOftenText(summary)}</Detail>
                <Detail term="Alerts">{alertsText(summary)}</Detail>
                <Microsoft365 proposal={proposal} />
                {summary.durable ? (
                    <Detail term="Durable">Each run saves checkpoints and can resume after an interruption.</Detail>
                ) : null}
            </dl>
            <ol aria-label="Workflow tasks" className="space-y-2">
                {summary.tasks.map((task, index) => (
                    <li key={index} className="min-w-0 space-y-1 rounded-lg border border-edge bg-surface-1 p-2">
                        <p className="break-words font-medium text-text-1">{`${index + 1}. ${task.title || 'Untitled task'}`}</p>
                        <p className="break-words text-text-2">
                            {task.merge
                                ? mergeTaskText(task)
                                : task.runner === 'agent'
                                    ? `Runs with the agent ${task.agent_name || 'chosen for it'}.`
                                    : 'Runs with the default model.'}
                        </p>
                        {task.requested_actions.length ? (
                            <p className="break-words text-text-2">{`Needs: ${actionList(task.requested_actions)}.`}</p>
                        ) : null}
                        {task.action_kinds.length && !task.merge ? (
                            <p className="break-words text-text-2">{`The agent can use: ${actionList(task.action_kinds)}.`}</p>
                        ) : null}
                        {task.inputs.length ? (
                            <p className="break-words text-text-2">
                                {`${task.merge ? 'Files to merge, in order' : 'Reads'}: ${task.inputs.join(', ')}.`}
                            </p>
                        ) : null}
                        <details className="group">
                            <summary className="cursor-pointer rounded font-medium text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
                                Instructions
                            </summary>
                            <p className="mt-1 whitespace-pre-wrap break-words rounded bg-surface-2 p-2 text-text-1">
                                {task.instructions}
                            </p>
                        </details>
                    </li>
                ))}
            </ol>
            {proposal.similar_workflows.length ? (
                <div className="space-y-1">
                    <p className="font-medium text-text-2">You already have similar workflows:</p>
                    <ul className="list-disc space-y-0.5 pl-5">
                        {proposal.similar_workflows.map((similar) => (
                            <li key={similar.workflow_id} className="break-words">
                                <Link to={workflowProposalLink(similar.workflow_id)}
                                    className="font-medium text-accent underline underline-offset-2">
                                    {similar.name || 'Unnamed workflow'}
                                </Link>
                                {[similar.schedule_label, similar.why.map((why) => SIMILAR_LABELS[why]).join(', ')]
                                    .filter(Boolean).map((part) => ` · ${part}`).join('')}
                            </li>
                        ))}
                    </ul>
                </div>
            ) : null}
        </>
    );
}

function ProposalCard({
    proposal, runId, conversationId, onChanged, onRefresh, onCheckAgain, pollingStopped,
}: {
    proposal: WorkflowProposal;
    runId: string;
    conversationId: string;
    onChanged: (proposal: WorkflowProposal) => void;
    onRefresh: () => void;
    onCheckAgain: () => void;
    pollingStopped: boolean;
}) {
    const headingId = useId();
    const cardRef = useRef<HTMLElement>(null);
    const [busy, setBusy] = useState<'enabled' | 'paused' | 'again' | 'deny' | 'edit' | null>(null);
    const [error, setError] = useState('');
    const [confirmDeny, setConfirmDeny] = useState(false);
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

    const summary = proposal.summary;
    // A created workflow is named as it is now: the editor or Workflows may have renamed it.
    const name = proposal.workflow?.name || summary?.name || 'Proposed workflow';
    const manual = summary?.trigger_type === 'manual';
    const actions = proposal.actions;

    const accept = async (mode: WorkflowProposalMode, createAgain = false) => {
        if (busy) return;
        setBusy(createAgain ? 'again' : mode);
        setError('');
        try {
            const response = await acceptWorkflowProposal(runId, proposal.proposal_id, {
                conversation_id: conversationId, mode, ...(createAgain ? { create_again: true } : {}),
            });
            onChanged(afterAccept(proposal, response));
        } catch (cause) {
            setError(errorText(cause, 'Could not create the workflow.'));
        } finally {
            setBusy(null);
            setSettled((value) => value + 1);
            onRefresh();
        }
    };

    const deny = async () => {
        if (busy) return;
        setBusy('deny');
        setError('');
        try {
            await denyWorkflowProposal(runId, proposal.proposal_id, conversationId);
            onChanged(afterDeny(proposal));
        } catch (cause) {
            setError(errorText(cause, 'Could not deny the proposal.'));
        } finally {
            setBusy(null);
            setConfirmDeny(false);
            setSettled((value) => value + 1);
            onRefresh();
        }
    };

    const openEditor = async () => {
        if (busy) return;
        setBusy('edit');
        setError('');
        try {
            const [draft, options] = await Promise.all([
                fetchWorkflowProposalDraft(runId, proposal.proposal_id, conversationId),
                fetchWorkflowEditorOptions(PERSONAL_SCOPE),
            ]);
            setEditor({
                draft: normalizeWorkflowDefinition(draft.workflow, PERSONAL_SCOPE), options, note: draft.url_access_note,
            });
        } catch (cause) {
            setError(errorText(cause, 'Could not open the workflow editor.'));
            onRefresh();
        } finally {
            setBusy(null);
        }
    };

    // Save in the editor accepts the proposal with the edited draft; it never saves a workflow directly.
    const accepted = useRef<WorkflowProposalAcceptResponse | null>(null);
    const saveThroughAccept = useCallback(async (draft: WorkflowDefinition, original: WorkflowDefinition | null) => {
        const payload = workflowForSave(draft, original, PERSONAL_SCOPE);
        // A new workflow's save payload drops URL Access, so the draft's own flag is checked as well.
        if (draft.url_access_enabled === true || payload.url_access_enabled === true) {
            throw new Error(`${URL_ACCESS_REFUSED} ${editor?.note ?? ''}`.trim());
        }
        try {
            const response = await acceptWorkflowProposal(runId, proposal.proposal_id, {
                conversation_id: conversationId, workflow: payload,
            });
            accepted.current = response;
            return { workflow: { ...payload, ...response.workflow } };
        } catch (cause) {
            // The editor reads a 409 as a stale saved workflow; nothing is saved yet, so the draft stands.
            if (cause instanceof ApiError && cause.status === 409) {
                throw new ApiError(`${cause.message} Your draft has been retained.`, 400, cause.payload);
            }
            throw cause;
        }
    }, [runId, proposal.proposal_id, conversationId, editor?.note]);

    const isCreated = proposal.state === 'created_enabled' || proposal.state === 'created_paused';
    const expiry = proposal.state === 'pending' ? expiryText(proposal.expires_at) : '';
    return (
        <article ref={cardRef} tabIndex={-1} aria-labelledby={headingId}
            className="min-w-0 space-y-2 rounded-xl border border-edge bg-surface-2 p-3 text-xs outline-none focus-visible:ring-2 focus-visible:ring-accent">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                    <p className="text-text-3">Proposed workflow</p>
                    <h4 id={headingId} className="break-words text-sm font-medium text-text-1">{name}</h4>
                </div>
                <p role="status" className={clsx('rounded px-2 py-0.5 font-medium',
                    isCreated ? 'bg-ok-soft text-ok'
                        : proposal.state === 'unavailable' || proposal.state === 'expired' ? 'bg-warn-soft text-warn'
                        : 'bg-surface-3 text-text-2')}>
                    {STATE_LABELS[proposal.state]}
                </p>
            </div>
            <ProposalDetails proposal={proposal} />
            <p className="break-words text-text-2">{[stateNote(proposal), expiry].filter(Boolean).join(' ')}</p>
            {proposal.state === 'creating' && pollingStopped ? (
                <p className="break-words text-text-2">
                    This is taking longer than expected.{' '}
                    <GlassButton size="sm" variant="ghost" onClick={onCheckAgain}>Check again</GlassButton>
                </p>
            ) : null}
            {error ? <p role="alert" className="break-words rounded-lg bg-danger-soft p-2 text-danger">{error}</p> : null}
            <div className="flex flex-wrap items-center gap-2">
                {actions.accept ? (manual ? (
                    <GlassButton size="sm" variant="primary" disabled={Boolean(busy)} onClick={() => void accept('enabled')}>
                        {busy === 'enabled' ? 'Creating…' : 'Create'}
                    </GlassButton>
                ) : (
                    <>
                        <GlassButton size="sm" variant="primary" disabled={Boolean(busy)} onClick={() => void accept('enabled')}>
                            {busy === 'enabled' ? 'Creating…' : 'Create & start'}
                        </GlassButton>
                        <GlassButton size="sm" variant="subtle" disabled={Boolean(busy)} onClick={() => void accept('paused')}>
                            {busy === 'paused' ? 'Creating…' : 'Create paused'}
                        </GlassButton>
                    </>
                )) : null}
                {actions.edit ? (
                    <GlassButton size="sm" variant="ghost" disabled={Boolean(busy)} onClick={() => void openEditor()}
                        aria-label={`Edit ${name} before creating it`}>
                        {busy === 'edit' ? 'Opening…' : 'Edit'}
                    </GlassButton>
                ) : null}
                {actions.deny ? (
                    <GlassButton size="sm" variant="danger" disabled={Boolean(busy)} onClick={() => setConfirmDeny(true)}>
                        Deny
                    </GlassButton>
                ) : null}
                {actions.create_again ? (
                    <GlassButton size="sm" variant="subtle" disabled={Boolean(busy)} onClick={() => void accept('paused', true)}>
                        {busy === 'again' ? 'Creating…' : 'Create again'}
                    </GlassButton>
                ) : null}
                {actions.open_workflow && proposal.workflow ? (
                    <Link to={workflowProposalLink(proposal.workflow.id)}
                        className="inline-flex h-8 items-center rounded-xl px-3 text-sm font-medium text-accent hover:bg-surface-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
                        Open workflow
                    </Link>
                ) : null}
            </div>
            {actions.accept && manual ? (
                <p className="text-text-3">It runs only when you start it from Workflows.</p>
            ) : null}
            {confirmDeny ? (
                <ConfirmDialog
                    title="Deny this workflow proposal?"
                    description={`SimpleChat will not create ${name}.`}
                    confirmLabel="Deny"
                    busy={busy === 'deny'}
                    onConfirm={() => void deny()}
                    onClose={() => { if (busy !== 'deny') setConfirmDeny(false); }}>
                    <p className="text-xs text-text-2">You can ask for a new proposal in chat at any time.</p>
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
                        if (response) onChanged(afterAccept(proposal, response));
                        setSettled((value) => value + 1);
                        onRefresh();
                    }}
                />
            ) : null}
        </article>
    );
}

/**
 * Every workflow proposal a run made, for its requester, in a personal conversation.
 *
 * The caller mounts this only when the answer's run completed a proposal step. The status route
 * decides what each card may show and offer; a run the reader cannot open renders nothing.
 */
export function WorkflowProposalCards({ conversationId, runId }: { conversationId: string; runId: string }) {
    const [proposals, setProposals] = useState<WorkflowProposal[] | null>(null);
    const [loadError, setLoadError] = useState('');
    const [missing, setMissing] = useState(false);
    const [pollingStopped, setPollingStopped] = useState(false);
    const request = useRef<AbortController | null>(null);

    const refresh = useCallback(async () => {
        request.current?.abort();
        const controller = new AbortController();
        request.current = controller;
        try {
            const list = await fetchWorkflowProposals(runId, conversationId, controller.signal);
            if (controller.signal.aborted) return;
            setProposals(list.proposals);
            setLoadError('');
        } catch (cause) {
            if (controller.signal.aborted) return;
            if (cause instanceof ApiError && cause.status === 404) {
                setMissing(true);
                return;
            }
            setLoadError(errorText(cause, 'Could not load the workflow proposal.'));
        } finally {
            if (request.current === controller) request.current = null;
        }
    }, [runId, conversationId]);

    useEffect(() => {
        void refresh();
        return () => request.current?.abort();
    }, [refresh]);

    // While a decision is being created elsewhere, check back briefly: stop when the server's claim
    // window has passed or after a fixed number of checks, and wait while the tab is hidden.
    const creating = Boolean(proposals?.some((proposal) => proposal.state === 'creating'));
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

    const replace = useCallback((next: WorkflowProposal) => {
        setProposals((current) => current?.map((proposal) =>
            proposal.proposal_id === next.proposal_id ? next : proposal) ?? current);
    }, []);
    const refreshNow = useCallback(() => {
        void refresh();
    }, [refresh]);
    const checkAgain = useCallback(() => {
        setPollingStopped(false);
        setPollRound((round) => round + 1);
        void refresh();
    }, [refresh]);

    if (missing || (!loadError && !proposals?.length)) return null;
    return (
        <section aria-label="Workflow proposals" className="mt-3 min-w-0 space-y-2">
            {loadError ? (
                <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg bg-warn-soft p-2 text-xs text-warn">
                    <span className="break-words">{loadError}</span>
                    <GlassButton size="sm" variant="ghost" onClick={checkAgain}>Try again</GlassButton>
                </div>
            ) : null}
            {proposals?.map((proposal) => (
                <ProposalCard key={proposal.proposal_id} proposal={proposal} runId={runId}
                    conversationId={conversationId} onChanged={replace} onRefresh={refreshNow}
                    onCheckAgain={checkAgain} pollingStopped={pollingStopped} />
            ))}
        </section>
    );
}
