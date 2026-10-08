// workflowHandoffs.ts
// The one-time workflows a plan handed large work off to, and the requester's decisions on them.
//
// A request too big to finish inside one plan, such as reviewing every contract in a workspace,
// makes the plan prepare a one-time workflow instead. Nothing runs until its requester accepts the
// hand-off: the hand-off card reads each hand-off from the status route and records Accept, an
// edited Accept or Decline through the decision routes. Every response is checked before anything
// is shown, so a response of the wrong shape fails closed rather than showing half a hand-off.
// Workflow names, task titles, agent names and workspace names are written by the planner or the
// user, so they are only ever rendered as text.

import { ApiError, api, requestWithStatus } from './apiClient';
import { workflowForSave, type WorkflowDefinition } from './workflowEditor';
import { WORKFLOW_RUN_STATUS_UNAVAILABLE, workflowWaitingText, type WorkflowWaitingReason } from './workflowRunStatus';
import type { TrackedWorkflowRun } from './workflowRunTracker';

/** The orchestration capability whose completed step leaves a hand-off card on its answer. */
export const WORKFLOW_HANDOFF_CAPABILITY = 'workflow_handoff';

export const WORKFLOW_HANDOFF_INVALID_RESPONSE = 'The workflow hand-off returned an invalid response.';

export const WORKFLOW_HANDOFF_STATES = [
    'pending', 'creating', 'created', 'queued', 'denied', 'expired', 'unavailable', 'invalid',
] as const;
export type WorkflowHandoffState = typeof WORKFLOW_HANDOFF_STATES[number];

export const WORKFLOW_HANDOFF_ACTIONS = ['accept', 'edit', 'deny'] as const;
export type WorkflowHandoffAction = typeof WORKFLOW_HANDOFF_ACTIONS[number];

const DISCLOSURE_KINDS = ['documents', 'workspace_query'] as const;
const LIMIT_BEHAVIORS = ['exact', 'best_n', 'pause'] as const;
// The server derives every hand-off id with uuid5, so its canonical lowercase form is the only one.
const HANDOFF_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export interface WorkflowHandoffTask {
    title: string;
    runner: 'agent' | 'model';
    /** The agent's display name, or empty when the task runs on the default model. */
    agent_name: string;
}

export interface WorkflowHandoffSummary {
    name: string;
    description: string;
    tasks: WorkflowHandoffTask[];
    /** The workflow sends a notification after every run, at severity Info. */
    alerts_every_run: boolean;
    /** Each run saves checkpoints and can resume after an interruption. */
    durable: boolean;
    /** The workflow runs once, when its hand-off is accepted, and is never scheduled. */
    one_time: boolean;
}

export interface WorkflowHandoffDisclosure {
    kind: typeof DISCLOSURE_KINDS[number];
    /** The server's own sentence for what the workflow covers, shown verbatim. */
    text: string;
    /** How many documents were named, for a hand-off over named documents. */
    count: number | null;
    /** The most documents a workspace query reviews. */
    limit: number | null;
    limit_behavior: typeof LIMIT_BEHAVIORS[number];
    /** The workspaces a query searches. Empty for named documents. */
    scope_names: string[];
}

export interface WorkflowHandoffWorkflow {
    id: string;
    name: string;
    is_enabled: boolean;
}

export interface WorkflowHandoffRun {
    id: string;
    /** The run's lowercased status, or null when its record could not be read. */
    status: string | null;
}

export interface WorkflowHandoffItem {
    handoff_id: string;
    step_id: string;
    state: WorkflowHandoffState;
    reason: string | null;
    created_at: string | null;
    expires_at: string | null;
    /** What the card offers now. Only the server decides these; the card never adds one. */
    actions: WorkflowHandoffAction[];
    summary: WorkflowHandoffSummary | null;
    disclosure: WorkflowHandoffDisclosure | null;
    /** Present once the workflow exists. */
    workflow: WorkflowHandoffWorkflow | null;
    /** Present once the hand-off's run was queued. */
    run: WorkflowHandoffRun | null;
    /** True when the queued run will post its result back into this chat. */
    chat_delivery: boolean;
}

export interface WorkflowHandoffList {
    run_id: string;
    handoffs: WorkflowHandoffItem[];
}

export type WorkflowHandoffChoice =
    | { mode: 'as_proposed' }
    | { mode: 'edited'; workflow: Record<string, unknown> };

export interface WorkflowHandoffAccepted {
    handoff_id: string;
    state: 'queued';
    /** True when this accept created the workflow; false when it started one that existed. */
    created: boolean;
    workflow: WorkflowHandoffWorkflow;
    run: WorkflowHandoffRun;
    chat_delivery: boolean;
}

export interface WorkflowHandoffDraft {
    handoff_id: string;
    workflow: Record<string, unknown>;
    url_access_note: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function invalid(): never {
    throw new Error(WORKFLOW_HANDOFF_INVALID_RESPONSE);
}

function oneOf<T extends string>(values: readonly T[], value: unknown): T {
    return typeof value === 'string' && (values as readonly string[]).includes(value) ? value as T : invalid();
}

function textOf(value: unknown): string {
    return typeof value === 'string' ? value : invalid();
}

function optionalText(value: unknown): string | null {
    return value === null || value === undefined ? null : textOf(value);
}

function idOf(value: unknown): string {
    const id = textOf(value);
    return id.trim() ? id : invalid();
}

function flagOf(value: unknown): boolean {
    return typeof value === 'boolean' ? value : invalid();
}

function textsOf(value: unknown): string[] {
    return Array.isArray(value) ? value.map(textOf) : invalid();
}

function countOf(value: unknown): number | null {
    if (value === null || value === undefined) return null;
    return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : invalid();
}

function own(table: Readonly<Record<string, string>>, key: string): boolean {
    return Object.prototype.hasOwnProperty.call(table, key);
}

function taskOf(value: unknown): WorkflowHandoffTask {
    if (!isRecord(value)) invalid();
    return {
        title: textOf(value.title),
        runner: oneOf(['agent', 'model'] as const, value.runner),
        agent_name: textOf(value.agent_name),
    };
}

function summaryOf(value: unknown): WorkflowHandoffSummary | null {
    if (value === null || value === undefined) return null;
    if (!isRecord(value) || !Array.isArray(value.tasks)) invalid();
    const alerts = value.alerts;
    return {
        name: textOf(value.name),
        description: textOf(value.description),
        tasks: value.tasks.map(taskOf),
        // The card states only what the server said, so anything else leaves its line off.
        alerts_every_run: isRecord(alerts) && alerts.mode === 'every_run' && alerts.severity === 'info',
        durable: value.durable === true,
        one_time: value.one_time === true,
    };
}

function disclosureOf(value: unknown): WorkflowHandoffDisclosure | null {
    if (value === null || value === undefined) return null;
    if (!isRecord(value)) invalid();
    const kind = oneOf(DISCLOSURE_KINDS, value.kind);
    const behavior = oneOf(LIMIT_BEHAVIORS, value.limit_behavior);
    const documents = kind === 'documents';
    // Named documents give their exact count; a workspace query gives the most it reviews.
    const count = documents ? countOf(value.count) : null;
    const limit = documents ? null : countOf(value.limit);
    if ((documents ? count : limit) === null || documents !== (behavior === 'exact')) invalid();
    return {
        kind,
        text: idOf(value.text),
        count,
        limit,
        limit_behavior: behavior,
        scope_names: textsOf(value.scope_names),
    };
}

function workflowOf(value: unknown): WorkflowHandoffWorkflow {
    if (!isRecord(value)) invalid();
    return { id: idOf(value.id), name: textOf(value.name), is_enabled: flagOf(value.is_enabled) };
}

function runOf(value: unknown): WorkflowHandoffRun {
    if (!isRecord(value)) invalid();
    return { id: idOf(value.id), status: optionalText(value.status) };
}

function actionsOf(value: unknown): WorkflowHandoffAction[] {
    if (!Array.isArray(value)) return [];
    const actions: WorkflowHandoffAction[] = [];
    for (const action of value) {
        const known = WORKFLOW_HANDOFF_ACTIONS.find((candidate) => candidate === action);
        if (known && !actions.includes(known)) actions.push(known);
    }
    return actions;
}

function handoffOf(value: unknown): WorkflowHandoffItem {
    if (!isRecord(value)) invalid();
    const handoffId = typeof value.handoff_id === 'string' && HANDOFF_ID.test(value.handoff_id)
        ? value.handoff_id
        : invalid();
    return {
        handoff_id: handoffId,
        step_id: idOf(value.step_id),
        state: oneOf(WORKFLOW_HANDOFF_STATES, value.state),
        reason: optionalText(value.reason),
        created_at: optionalText(value.created_at),
        expires_at: optionalText(value.expires_at),
        actions: actionsOf(value.actions),
        summary: summaryOf(value.summary),
        disclosure: disclosureOf(value.disclosure),
        workflow: value.workflow === undefined || value.workflow === null ? null : workflowOf(value.workflow),
        run: value.run === undefined || value.run === null ? null : runOf(value.run),
        chat_delivery: value.chat_delivery === undefined ? false : flagOf(value.chat_delivery),
    };
}

/**
 * Check a status response. A list for another run is refused whole; one malformed hand-off is
 * left off the card. Exported so a test can hold the checks against real responses.
 */
export function parseWorkflowHandoffList(value: unknown, runId: string): WorkflowHandoffList {
    if (!isRecord(value) || value.run_id !== runId || !Array.isArray(value.handoffs)) invalid();
    const handoffs: WorkflowHandoffItem[] = [];
    for (const entry of value.handoffs) {
        let item: WorkflowHandoffItem;
        try {
            item = handoffOf(entry);
        } catch {
            continue;
        }
        if (!handoffs.some((known) => known.handoff_id === item.handoff_id)) handoffs.push(item);
    }
    return { run_id: runId, handoffs };
}

function handoffsPath(runId: string, suffix = ''): string {
    return `/api/v2/orchestration/runs/${encodeURIComponent(runId)}/workflow-handoffs${suffix}`;
}

function handoffPath(runId: string, handoffId: string, action: string): string {
    return handoffsPath(runId, `/${encodeURIComponent(handoffId)}/${action}`);
}

/** The hand-offs a run shows its requester, each with the actions its card offers now. */
export async function listWorkflowHandoffs(
    runId: string,
    conversationId: string,
    signal?: AbortSignal,
): Promise<WorkflowHandoffList> {
    const query = new URLSearchParams({ conversation_id: conversationId });
    return parseWorkflowHandoffList(await api.get<unknown>(`${handoffsPath(runId)}?${query}`, signal), runId);
}

/** Create the hand-off's workflow, as prepared or as edited, and queue its one run. */
export async function acceptWorkflowHandoff(
    runId: string,
    handoffId: string,
    conversationId: string,
    choice: WorkflowHandoffChoice,
): Promise<WorkflowHandoffAccepted> {
    const body = choice.mode === 'edited'
        ? { conversation_id: conversationId, mode: choice.mode, workflow: choice.workflow }
        : { conversation_id: conversationId, mode: choice.mode };
    const { data, status } = await requestWithStatus<unknown>(
        handoffPath(runId, handoffId, 'accept'), { method: 'POST', body },
    );
    if (!isRecord(data) || data.handoff_id !== handoffId || data.state !== 'queued') invalid();
    const created = flagOf(data.created);
    // The server answers 201 exactly when this accept created the workflow.
    if (created !== (status === 201)) invalid();
    return {
        handoff_id: handoffId,
        state: 'queued',
        created,
        workflow: workflowOf(data.workflow),
        run: runOf(data.run),
        chat_delivery: flagOf(data.chat_delivery),
    };
}

export async function denyWorkflowHandoff(runId: string, handoffId: string, conversationId: string): Promise<void> {
    const response = await api.post<unknown>(
        handoffPath(runId, handoffId, 'deny'), { conversation_id: conversationId },
    );
    if (!isRecord(response) || response.handoff_id !== handoffId || response.state !== 'denied') invalid();
}

export interface WorkflowHandoffEdit {
    /** The editor's save payload, which the editor keeps as its saved baseline. */
    payload: WorkflowDefinition;
    /** What an edited accept sends: the payload without the id the server derives from the hand-off. */
    workflow: Record<string, unknown>;
}

/**
 * The workflow an edited accept sends for the editor's draft, or null when the draft turns URL
 * Access on, which a hand-off refuses. A new workflow's save payload drops that flag, so the
 * draft's own flag is checked as well.
 *
 * A version 3 workflow's task prompt is left for the server to set from the workflow's name, as it
 * did for the prepared workflow. The editor's own, the first task's instructions, would make an
 * untouched save count as an edit.
 */
export function workflowHandoffEdit(draft: WorkflowDefinition, original: WorkflowDefinition | null): WorkflowHandoffEdit | null {
    const payload = workflowForSave(draft, original, { type: 'personal' });
    if (draft.url_access_enabled === true || payload.url_access_enabled === true) return null;
    const workflow: Record<string, unknown> = { ...payload };
    delete workflow.id;
    if (payload.definition_version === 3) delete workflow.task_prompt;
    return { payload, workflow };
}

/** A pending hand-off as an unsaved workflow editor draft. */
export async function fetchWorkflowHandoffDraft(
    runId: string,
    handoffId: string,
    conversationId: string,
    signal?: AbortSignal,
): Promise<WorkflowHandoffDraft> {
    const query = new URLSearchParams({ conversation_id: conversationId });
    const response = await api.get<unknown>(`${handoffPath(runId, handoffId, 'draft')}?${query}`, signal);
    if (!isRecord(response) || response.handoff_id !== handoffId || !isRecord(response.workflow)) invalid();
    return { handoff_id: handoffId, workflow: response.workflow, url_access_note: textOf(response.url_access_note) };
}

/** Whether an answer's orchestration metadata says a hand-off step completed in its run. */
export function orchestrationHandedOffWorkflow(metadata: unknown): boolean {
    if (!isRecord(metadata)) return false;
    const summary = metadata.plan_summary;
    return isRecord(summary) && Array.isArray(summary.capabilities_used)
        && summary.capabilities_used.includes(WORKFLOW_HANDOFF_CAPABILITY);
}

// The server's sentence for each refusal code, kept in V2 so a changed or unknown server string
// is never shown.
const ERROR_TEXT: Readonly<Record<string, string>> = {
    invalid_request: 'The request is not valid.',
    handoff_edit_invalid: 'The edited workflow is not valid. Review the task, runner and document inputs.',
    workflow_handoff_disabled: 'Workflow hand-off is not available here.',
    workflow_role_required: 'You need the workflow role to hand work off to a workflow.',
    workflow_shared_conversation: 'Workflow hand-off is available only in your own private chats.',
    handoff_results_off: 'Workflow hand-off needs workflow results in chat, which is turned off.',
    handoff_access_lost: 'You no longer have access to a document, workspace or agent this workflow uses.',
    run_not_found: 'Run not found.',
    handoff_not_found: 'Workflow hand-off not found.',
    handoff_unavailable: 'This workflow hand-off is no longer available.',
    handoff_expired: 'This workflow hand-off expired. Ask again to get a new one.',
    handoff_denied: 'This workflow hand-off was declined.',
    handoff_accepted: 'This workflow hand-off was already accepted.',
    handoff_busy: 'This workflow hand-off is being accepted. Try again in a moment.',
    handoff_kind_mismatch: 'This is not a workflow hand-off.',
    handoff_run_conflict: 'The workflow was created, but its run could not be started.',
    workflow_deleted: 'The workflow this hand-off created was deleted.',
    handoff_limit_changed: 'The document limit changed since this hand-off was prepared. Ask again to get a new one.',
    handoff_invalid: 'This workflow hand-off is not valid. Ask again to get a new one.',
    handoff_agent_unsupported: 'A hand-off workflow can use only your own agents.',
    handoff_daily_limit: 'You reached the daily limit for workflow hand-offs. Try again later.',
    handoff_queue_failed: 'The workflow was created, but its run could not be queued. Try again.',
    service_unavailable: 'The service is temporarily unavailable. Try again.',
    legacy_plan: 'This plan was created by an earlier orchestration version and can\'t be opened or rerun. Start a new request.',
};

// Why a hand-off's run could not be started, carried as `reason` on handoff_run_conflict.
const RUN_CONFLICT_TEXT: Readonly<Record<string, string>> = {
    workflow_unavailable: 'The workflow can\'t be started from chat. It may have been deleted, or it can\'t run as saved. Open it in Workflows to check it.',
    workflow_already_running: 'The workflow is already running. You can follow that run in Workflows and start the workflow again once it finishes.',
    workflow_definition_changed: 'The workflow changed while it was being started. Ask again in a new message to start its current version.',
    workflow_run_tombstoned: 'The workflow couldn\'t be started. Ask again in a new message.',
    workflow_run_not_started: 'The workflow couldn\'t be started. Open it in Workflows to run it.',
};

const RUN_CONFLICT_DEFAULT = 'workflow_run_not_started';

// Why a listed hand-off cannot be used. The hand-off reasons are the server's own text; the
// server has no text for a closed gate, content review or a deleted workflow, so those are V2's.
const REASON_TEXT: Readonly<Record<string, string>> = {
    workflow_handoff_invalid: 'The hand-off was planned in a way SimpleChat can\'t run. Ask again, naming the documents or the workspace to review.',
    workflow_context_unavailable: 'Your documents and workspaces could not be checked for this request. Ask again in a new message.',
    handoff_loop_limit: 'The request covers more documents than one hand-off can review. Ask again with a narrower request.',
    handoff_agent_unsupported: 'A hand-off runs its tasks on the default model or on a local agent. Ask again without naming that agent.',
    handoff_unavailable: 'Handing work off to a workflow isn\'t available with this deployment\'s workflow settings.',
    handoff_sources_unavailable: 'A document, workspace or agent the hand-off named is no longer available to you. Ask again in a new message.',
    handoff_prepare_failed: 'The hand-off couldn\'t be prepared. Ask again in a new message.',
    workflow_handoff_disabled: 'Handing work off to a workflow is turned off, so this hand-off is not available.',
    workflow_results_disabled: 'Workflow results in chat are turned off, so this hand-off is not available.',
    workflow_role_required: 'You need workflow access to use this hand-off.',
    workflow_shared_conversation: 'Workflow hand-offs are available only in your own conversations.',
    content_review: 'This response is in content review, so its hand-off cannot be used.',
    workflow_deleted: 'The workflow this hand-off created was deleted.',
};

export const WORKFLOW_HANDOFF_REASON_FALLBACK = 'This hand-off is not available.';
export const WORKFLOW_HANDOFF_ERROR_FALLBACK = 'The hand-off could not be updated. Try again.';
export const WORKFLOW_HANDOFF_LOAD_FALLBACK = 'The hand-off could not be loaded. Try again.';

const SIGN_IN_TEXT = 'Sign in again to continue.';
const WORKFLOWS_OFF_TEXT = 'Personal workflows are turned off in SimpleChat right now.';
const WORKFLOW_ACCESS_TEXT = 'You need workflow access to use this hand-off. Ask your administrator.';
const UNREACHABLE_TEXT = 'SimpleChat could not be reached. Check your connection and try again.';
const ERROR_DETAIL_LIMIT = 3;
const ERROR_DETAIL_MAX_LENGTH = 240;

function sentenceOf(value: string): string {
    const text = value.slice(0, ERROR_DETAIL_MAX_LENGTH).trim();
    return !text || /[.!?]$/.test(text) ? text : `${text}.`;
}

/** Up to three of the refusal's own error messages, as plain sentences that don't repeat `main`. */
function errorDetails(payload: Record<string, unknown>, main: string): string[] {
    const details: string[] = [];
    if (!Array.isArray(payload.errors)) return details;
    for (const entry of payload.errors) {
        if (details.length >= ERROR_DETAIL_LIMIT) break;
        if (!isRecord(entry) || typeof entry.message !== 'string') continue;
        const text = sentenceOf(entry.message);
        if (text && text !== main && !details.includes(text)) details.push(text);
    }
    return details;
}

/**
 * The sentence a person reads for a failed hand-off request. A coded refusal reads V2's copy of
 * the server's sentence, never the response's own `error`; a refusal without a code comes from
 * the route's access checks, whose bare words such as "Forbidden" are never shown.
 */
export function workflowHandoffErrorText(error: unknown, fallback = WORKFLOW_HANDOFF_ERROR_FALLBACK): string {
    if (error instanceof ApiError) {
        if (error.status === 401) return SIGN_IN_TEXT;
        const payload = isRecord(error.payload) ? error.payload : {};
        const code = typeof payload.code === 'string' ? payload.code : '';
        if (code) {
            let text = own(ERROR_TEXT, code) ? ERROR_TEXT[code] : fallback;
            if (code === 'handoff_run_conflict') {
                const reason = typeof payload.reason === 'string' && own(RUN_CONFLICT_TEXT, payload.reason)
                    ? payload.reason
                    : RUN_CONFLICT_DEFAULT;
                text = `${text} ${RUN_CONFLICT_TEXT[reason]}`;
            }
            return [text, ...errorDetails(payload, text)].join(' ');
        }
        if (error.status === 400) return WORKFLOWS_OFF_TEXT;
        if (error.status === 403) return WORKFLOW_ACCESS_TEXT;
        return fallback;
    }
    if (error instanceof TypeError) return UNREACHABLE_TEXT;
    if (error instanceof Error && error.message === WORKFLOW_HANDOFF_INVALID_RESPONSE) {
        return WORKFLOW_HANDOFF_INVALID_RESPONSE;
    }
    return fallback;
}

/**
 * Whether trying the same accept again can succeed. A busy hand-off frees up, and a run that
 * could not be queued after its workflow was created is queued by a retry, which reuses the same
 * run request.
 */
export function workflowHandoffRetryable(error: unknown): boolean {
    if (!(error instanceof ApiError) || !isRecord(error.payload)) return false;
    const { code, state } = error.payload;
    if (code === 'handoff_busy') return true;
    if (state !== 'created') return false;
    return (code === 'handoff_queue_failed' && error.status === 503)
        || (code === 'handoff_run_conflict' && error.status === 409);
}

export function workflowHandoffReasonText(reason: string): string {
    return own(REASON_TEXT, reason) ? REASON_TEXT[reason] : WORKFLOW_HANDOFF_REASON_FALLBACK;
}

// Each runtime status reads as the status route's row for it would, so the card says the same
// before and after the live tracker reads the run.
const RUN_STATUS_LABELS: Readonly<Record<string, string>> = {
    queued: 'Queued',
    running: 'Running',
    ready_to_resume: 'Running',
    resuming: 'Running',
    waiting_recovery: 'Running',
    cancelling: 'Running',
    waiting_approval: 'Needs you',
    waiting_output: 'Needs you',
    paused: 'Needs you',
    awaiting_approval: 'Needs you',
    awaiting_sharing_approval: 'Needs you',
    awaiting_analysis_approval: 'Needs you',
    awaiting_run_as_approval: 'Needs you',
    awaiting_sign_in: 'Needs you',
    completed: 'Completed',
    completed_partial: 'Partly completed',
    failed: 'Failed',
    invalid: 'Failed',
    incomplete: 'Failed',
    skipped: 'Failed',
    cancelled: 'Cancelled',
    canceled: 'Cancelled',
};

/** A label for the run status the hand-off list reported, for when the live tracker has no row. */
export function workflowHandoffRunStatusLabel(status: string | null): string {
    return status !== null && own(RUN_STATUS_LABELS, status) ? RUN_STATUS_LABELS[status] : WORKFLOW_RUN_STATUS_UNAVAILABLE;
}

/**
 * The tracked run a queued hand-off started. The row must be the hand-off's own run in this
 * conversation, from this step and workflow. Its orchestration run is not compared, because the
 * run that produced the hand-off can be an earlier attempt than the one its answer shows.
 */
export function workflowHandoffTrackedRun(
    runs: Readonly<Record<string, TrackedWorkflowRun>>,
    conversationId: string,
    item: WorkflowHandoffItem,
): TrackedWorkflowRun | undefined {
    const runId = item.run?.id;
    const workflowId = item.workflow?.id;
    if (!conversationId || !runId || !workflowId || !Object.prototype.hasOwnProperty.call(runs, runId)) {
        return undefined;
    }
    const tracked = runs[runId];
    const row = tracked?.row;
    if (
        !row || row.run_id !== runId || row.conversation_id !== conversationId
        || row.step_id !== item.step_id || row.workflow_id !== workflowId
    ) {
        return undefined;
    }
    return tracked;
}

/** A hand-off run pauses before reviewing anything when more documents match than it may review. */
export const WORKFLOW_HANDOFF_PAUSED_TEXT = 'Paused before reviewing any documents because more matched than one hand-off can review. Cancel it, then ask again with a narrower request.';

export function handoffWaitingText(reason: WorkflowWaitingReason): string {
    return reason === 'paused' ? WORKFLOW_HANDOFF_PAUSED_TEXT : workflowWaitingText(reason);
}

function countText(count: number, one: string, many: string): string {
    return count === 1 ? `1 ${one}` : `${count.toLocaleString('en-US')} ${many}`;
}

/**
 * A hand-off step's blueprint in words: its name, what it reviews and its task titles. Its
 * instructions, document and workspace handles, content filter and tags are never returned.
 */
export function describeHandoffBlueprint(args: unknown): Array<[string, string]> {
    const blueprint = isRecord(args) ? args.blueprint : undefined;
    if (!isRecord(blueprint)) return [];
    const entries: Array<[string, string]> = [];
    if (typeof blueprint.name === 'string' && blueprint.name.trim()) {
        entries.push(['workflow', blueprint.name]);
    }
    const loop = blueprint.loop;
    if (isRecord(loop) && loop.source === 'documents' && Array.isArray(loop.documents)) {
        entries.push(['documents', countText(loop.documents.length, 'named document', 'named documents')]);
    } else if (isRecord(loop) && loop.source === 'workspace_query' && Array.isArray(loop.scopes)) {
        const search = `a search of ${countText(loop.scopes.length, 'workspace', 'workspaces')}`;
        const count = loop.count;
        if (loop.selection === 'all_matches') {
            entries.push(['documents', `${search}, all matches`]);
        } else if (loop.selection === 'best_n') {
            const best = typeof count === 'number' && Number.isInteger(count) && count > 0
                ? (count === 1 ? 'the best match' : `the ${count.toLocaleString('en-US')} best matches`)
                : 'the best matches';
            entries.push(['documents', `${search}, ${best}`]);
        } else {
            entries.push(['documents', search]);
        }
    }
    if (Array.isArray(blueprint.tasks)) {
        const titles = blueprint.tasks
            .map((task) => (isRecord(task) && typeof task.title === 'string' ? task.title.trim() : ''))
            .filter(Boolean);
        if (titles.length) entries.push(['tasks', titles.join(', ')]);
    }
    return entries;
}
