// workflowRunStatus.ts
// The live status of the saved workflow runs a user's chats started.
//
// One batched route reports every chat-started run: its status and phase, its steps, what it is
// waiting for, how its results are being posted back to the chat, and which actions the server
// allows on it (GET /api/v2/orchestration/workflow-runs/status). The app-shell tracker polls it;
// the run card, the chat list's running tag and the delivered-message footers only read what the
// tracker kept.
//
// Every row is checked against the closed sets the server sends. A row whose ids can't be used is
// dropped. A row that is otherwise malformed, or that carries a value this client doesn't know,
// becomes "Status unavailable" with only Open run: the card never guesses at a state, a reason or
// an action. Every string kept here is shown as text, never as markup.

import { api } from './apiClient';

export const WORKFLOW_RUN_STATUS_PATH = '/api/v2/orchestration/workflow-runs/status';
export const WORKFLOW_RUN_STATUS_INVALID_RESPONSE = 'The workflow run status returned an invalid response.';

/** The id prefix of every message a workflow run posts back to its chat. */
export const WORKFLOW_DELIVERY_MESSAGE_PREFIX = 'assistant_workflow_delivery_';

export const WORKFLOW_RUN_ROW_STATUSES = [
    'queued', 'running', 'waiting', 'completed', 'completed_partial', 'failed', 'cancelled', 'expired',
] as const;
export type WorkflowRunRowStatus = typeof WORKFLOW_RUN_ROW_STATUSES[number];

export const WORKFLOW_RUN_ROW_PHASES = ['running', 'needs_you', 'finished', 'failed', 'cancelled'] as const;
export type WorkflowRunRowPhase = typeof WORKFLOW_RUN_ROW_PHASES[number];

export const WORKFLOW_DELIVERY_ROW_STATUSES = [
    'pending', 'delivering', 'delivered', 'undeliverable', 'expired', 'not_applicable',
] as const;
export type WorkflowDeliveryRowStatus = typeof WORKFLOW_DELIVERY_ROW_STATUSES[number];

export const WORKFLOW_DELIVERY_REASONS = [
    'chat_unavailable', 'access_lost', 'workflow_deleted', 'runtime_missing', 'delivery_failed',
    'expired_before_delivery', 'content_blocked', 'results_off', 'result_unavailable', 'deadline_exceeded',
] as const;
export type WorkflowDeliveryReason = typeof WORKFLOW_DELIVERY_REASONS[number];

export const WORKFLOW_WAITING_REASONS = [
    'approval', 'microsoft_365_reconnect', 'microsoft_365_approval', 'output_review', 'recovery',
    'deadline_exceeded', 'paused',
] as const;
export type WorkflowWaitingReason = typeof WORKFLOW_WAITING_REASONS[number];

export const WORKFLOW_WAITING_ACTIONS = ['approve', 'reconnect', 'open_run'] as const;
export type WorkflowWaitingAction = typeof WORKFLOW_WAITING_ACTIONS[number];

export const WORKFLOW_RETRY_BLOCKED_CODES = [
    'retry_unavailable', 'workflow_deleted', 'not_resumable', 'deadline_exceeded',
    'workflow_definition_changed', 'workflow_already_running',
] as const;
export type WorkflowRetryBlockedCode = typeof WORKFLOW_RETRY_BLOCKED_CODES[number];

export const WORKFLOW_FAILURE_CODES = [
    'failed', 'invalid', 'incomplete', 'skipped', 'deadline_exceeded', 'execution_budget_exceeded',
    'repeat_iteration_limit', 'm365_authorization', 'authorization',
] as const;
export type WorkflowFailureCode = typeof WORKFLOW_FAILURE_CODES[number];

// The one phase the server pairs with each status. Any other pairing is a row this client
// can't read, and it is shown as unavailable rather than guessed at.
const PHASE_FOR_STATUS: Record<WorkflowRunRowStatus, WorkflowRunRowPhase> = {
    queued: 'running',
    running: 'running',
    waiting: 'needs_you',
    completed: 'finished',
    completed_partial: 'finished',
    failed: 'failed',
    expired: 'failed',
    cancelled: 'cancelled',
};

export interface WorkflowRunWaiting {
    reason: WorkflowWaitingReason;
    action: WorkflowWaitingAction;
    gate_id: string | null;
}

export interface WorkflowRunDelivery {
    status: WorkflowDeliveryRowStatus;
    generation: number | null;
    /** Only once delivered, and only an id with WORKFLOW_DELIVERY_MESSAGE_PREFIX. */
    message_id: string | null;
    delivered_at: string | null;
    reason: WorkflowDeliveryReason | null;
}

export interface WorkflowRunActions {
    cancel: boolean;
    retry: boolean;
    approve: boolean;
    open_run: boolean;
}

interface WorkflowRunRowIdentity {
    workflow_id: string;
    workflow_scope: 'personal';
    run_id: string;
    conversation_id: string;
    /** The plan run that started it. Null rows are tracked but join no answer. */
    orchestration_run_id: string | null;
    step_id: string | null;
    /** One line, at most 80 characters. */
    workflow_name: string;
    requested_at: string | null;
}

export interface WorkflowRunStatusRow extends WorkflowRunRowIdentity {
    kind: 'status';
    status: WorkflowRunRowStatus;
    phase: WorkflowRunRowPhase;
    /** The `expected_version` a resume would need when the row was read; a resume reads it fresh. */
    runtime_version: number | null;
    /** Steps finished. */
    step_index: number | null;
    step_count: number | null;
    step_label: string | null;
    started_at: string | null;
    completed_at: string | null;
    elapsed_seconds: number | null;
    waiting: WorkflowRunWaiting | null;
    delivery: WorkflowRunDelivery;
    error: string | null;
    error_code: WorkflowFailureCode | null;
    retry_blocked: WorkflowRetryBlockedCode | null;
    actions: WorkflowRunActions;
    live: boolean;
}

/** A row whose ids are good but whose status can't be read. It offers Open run and nothing else. */
export interface WorkflowRunUnavailableRow extends WorkflowRunRowIdentity {
    kind: 'unavailable';
}

export type WorkflowRunRow = WorkflowRunStatusRow | WorkflowRunUnavailableRow;

export interface WorkflowRunStatusResponse {
    /** Whether chats can start workflows now. Rows come back either way. */
    available: boolean;
    runs: WorkflowRunRow[];
    checked_at: string;
    /** More rows matched than the route returns. */
    truncated: boolean;
}

const NAME_MAX_LENGTH = 80;
const DEFAULT_NAME = 'Workflow';
const ID_MAX_LENGTH = 256;
// The server writes every time in this form, truncated to whole seconds.
const SECONDS_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
// The status route's own rule for a conversation id; anything else is refused with a 400.
const STATUS_CONVERSATION_ID = /^[A-Za-z0-9_-]{1,128}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function invalid(): never {
    throw new Error(WORKFLOW_RUN_STATUS_INVALID_RESPONSE);
}

function oneOf<T extends string>(values: readonly T[], value: unknown): value is T {
    return typeof value === 'string' && (values as readonly string[]).includes(value);
}

/**
 * An id the server would have kept: 1 to 256 characters, no surrounding space, and no control
 * characters or lone surrogates. Mirrors `_identifier` in functions_workflow_chat_delivery_status.py.
 */
export function isWorkflowRunIdentifier(value: unknown): value is string {
    if (typeof value !== 'string' || value !== value.trim()) {
        return false;
    }
    let length = 0;
    for (const character of value) {
        const code = character.codePointAt(0) ?? 0;
        if (code < 32 || (code >= 0xd800 && code <= 0xdfff)) {
            return false;
        }
        length += 1;
    }
    return length > 0 && length <= ID_MAX_LENGTH;
}

/** Whether the status route accepts this conversation id; reads for any other are never sent. */
export function isStatusConversationId(value: unknown): value is string {
    return typeof value === 'string' && STATUS_CONVERSATION_ID.test(value);
}

function isSecondsTime(value: unknown): value is string {
    return typeof value === 'string' && SECONDS_TIME.test(value) && !Number.isNaN(Date.parse(value));
}

function isCount(value: unknown): value is number {
    return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function countOrNull(value: unknown): number | null | undefined {
    if (value === null) return null;
    return isCount(value) ? value : undefined;
}

function timeOrNull(value: unknown): string | null | undefined {
    if (value === null) return null;
    return isSecondsTime(value) ? value : undefined;
}

function textOrNull(value: unknown): string | null | undefined {
    if (value === null) return null;
    return typeof value === 'string' ? value : undefined;
}

function oneLine(value: string): string {
    return value.replace(/\s+/g, ' ').trim();
}

function displayName(value: unknown): string {
    if (typeof value !== 'string') {
        return DEFAULT_NAME;
    }
    return [...oneLine(value)].slice(0, NAME_MAX_LENGTH).join('').trim() || DEFAULT_NAME;
}

function waitingOf(value: unknown): WorkflowRunWaiting | null | undefined {
    if (value === null) return null;
    if (!isRecord(value) || !oneOf(WORKFLOW_WAITING_REASONS, value.reason)
        || !oneOf(WORKFLOW_WAITING_ACTIONS, value.action)) {
        return undefined;
    }
    if (value.gate_id !== null && !isWorkflowRunIdentifier(value.gate_id)) {
        return undefined;
    }
    return { reason: value.reason, action: value.action, gate_id: value.gate_id };
}

function deliveryOf(value: unknown): WorkflowRunDelivery | undefined {
    if (!isRecord(value) || !oneOf(WORKFLOW_DELIVERY_ROW_STATUSES, value.status)) {
        return undefined;
    }
    const generation = countOrNull(value.generation);
    const deliveredAt = timeOrNull(value.delivered_at);
    const messageId = value.message_id;
    if (generation === undefined || deliveredAt === undefined) {
        return undefined;
    }
    if (messageId !== null && !(
        isWorkflowRunIdentifier(messageId) && messageId.startsWith(WORKFLOW_DELIVERY_MESSAGE_PREFIX)
    )) {
        return undefined;
    }
    if (value.reason !== null && !oneOf(WORKFLOW_DELIVERY_REASONS, value.reason)) {
        return undefined;
    }
    return {
        status: value.status,
        generation,
        message_id: messageId,
        delivered_at: deliveredAt,
        reason: value.reason,
    };
}

function actionsOf(value: unknown): WorkflowRunActions | undefined {
    if (!isRecord(value)) return undefined;
    const { cancel, retry, approve, open_run: openRun } = value;
    if (typeof cancel !== 'boolean' || typeof retry !== 'boolean' || typeof approve !== 'boolean'
        || typeof openRun !== 'boolean') {
        return undefined;
    }
    return { cancel, retry, approve, open_run: openRun };
}

/** Everything but the identity, or null when any of it can't be read. */
function statusOf(value: Record<string, unknown>): Omit<WorkflowRunStatusRow, keyof WorkflowRunRowIdentity | 'kind'> | null {
    const { status, phase } = value;
    if (!oneOf(WORKFLOW_RUN_ROW_STATUSES, status) || PHASE_FOR_STATUS[status] !== phase) {
        return null;
    }
    const runtimeVersion = countOrNull(value.runtime_version);
    const stepIndex = countOrNull(value.step_index);
    const stepCount = countOrNull(value.step_count);
    const elapsed = countOrNull(value.elapsed_seconds);
    const stepLabel = textOrNull(value.step_label);
    const startedAt = timeOrNull(value.started_at);
    const completedAt = timeOrNull(value.completed_at);
    const waiting = waitingOf(value.waiting);
    const delivery = deliveryOf(value.delivery);
    const error = textOrNull(value.error);
    const actions = actionsOf(value.actions);
    if (
        runtimeVersion === undefined || stepIndex === undefined || stepCount === undefined
        || elapsed === undefined || stepLabel === undefined || startedAt === undefined
        || completedAt === undefined || waiting === undefined || delivery === undefined
        || error === undefined || actions === undefined || typeof value.live !== 'boolean'
    ) {
        return null;
    }
    const errorCode = value.error_code;
    if (errorCode !== null && !oneOf(WORKFLOW_FAILURE_CODES, errorCode)) {
        return null;
    }
    const retryBlocked = value.retry_blocked;
    if (retryBlocked !== null && !oneOf(WORKFLOW_RETRY_BLOCKED_CODES, retryBlocked)) {
        return null;
    }
    // What the card has to say for each phase must be there to say.
    if (phase === 'needs_you' && waiting === null) {
        return null;
    }
    if (phase === 'failed' && (!error?.trim() || errorCode === null)) {
        return null;
    }
    return {
        status,
        phase: PHASE_FOR_STATUS[status],
        runtime_version: runtimeVersion,
        step_index: stepIndex,
        step_count: stepCount,
        step_label: stepLabel,
        started_at: startedAt,
        completed_at: completedAt,
        elapsed_seconds: elapsed,
        waiting,
        delivery,
        error,
        error_code: errorCode,
        retry_blocked: retryBlocked,
        actions,
        live: value.live,
    };
}

function rowOf(value: unknown): WorkflowRunRow | null {
    if (!isRecord(value)) return null;
    const { workflow_id: workflowId, run_id: runId, conversation_id: conversationId } = value;
    const orchestrationRunId = value.orchestration_run_id;
    const stepId = value.step_id;
    if (
        !isWorkflowRunIdentifier(workflowId) || !isWorkflowRunIdentifier(runId)
        || !isWorkflowRunIdentifier(conversationId)
        || (orchestrationRunId !== null && !isWorkflowRunIdentifier(orchestrationRunId))
        || (stepId !== null && !isWorkflowRunIdentifier(stepId))
        || value.workflow_scope !== 'personal'
    ) {
        return null;
    }
    const requestedAt = timeOrNull(value.requested_at);
    const identity: WorkflowRunRowIdentity = {
        workflow_id: workflowId,
        workflow_scope: 'personal',
        run_id: runId,
        conversation_id: conversationId,
        orchestration_run_id: orchestrationRunId,
        step_id: stepId,
        workflow_name: displayName(value.workflow_name),
        requested_at: requestedAt ?? null,
    };
    const status = typeof value.workflow_name === 'string' && requestedAt !== undefined ? statusOf(value) : null;
    return status ? { ...identity, kind: 'status', ...status } : { ...identity, kind: 'unavailable' };
}

/** Check a status response. Exported so a test can hold the checks against real responses. */
export function parseWorkflowRunStatusResponse(value: unknown): WorkflowRunStatusResponse {
    if (
        !isRecord(value) || typeof value.available !== 'boolean' || !Array.isArray(value.runs)
        || !isSecondsTime(value.checked_at) || typeof value.truncated !== 'boolean'
    ) {
        invalid();
    }
    const runs: WorkflowRunRow[] = [];
    const seen = new Set<string>();
    for (const item of value.runs) {
        const row = rowOf(item);
        // Newest request first, so a repeated run keeps its first row.
        if (row && !seen.has(row.run_id)) {
            seen.add(row.run_id);
            runs.push(row);
        }
    }
    return { available: value.available, runs, checked_at: value.checked_at, truncated: value.truncated };
}

/**
 * Read the status of the chat-started runs: one chat's (at most 20), or, with no conversation,
 * every run still in flight, still being posted, or posted in the last ten minutes (at most 50).
 */
export async function fetchWorkflowRunStatus(
    conversationId: string | null,
    signal?: AbortSignal,
): Promise<WorkflowRunStatusResponse> {
    const query = conversationId === null ? '' : `?${new URLSearchParams({ conversation_id: conversationId })}`;
    return parseWorkflowRunStatusResponse(await api.get<unknown>(`${WORKFLOW_RUN_STATUS_PATH}${query}`, signal));
}

const ACTIVE_STATUSES: readonly WorkflowRunRowStatus[] = ['queued', 'running', 'waiting'];
const OPEN_DELIVERIES: readonly WorkflowDeliveryRowStatus[] = ['pending', 'delivering'];

/**
 * Whether a run is still going, or its result is still on its way to the chat. The tracker polls
 * while any is; the running tag shows while one is. An unavailable row never counts.
 */
export function isWorkflowRunInFlight(row: WorkflowRunRow): boolean {
    return row.kind === 'status'
        && (ACTIVE_STATUSES.includes(row.status) || OPEN_DELIVERIES.includes(row.delivery.status));
}

/** Whether the run itself is still going, as opposed to only its result being posted. */
export function isWorkflowRunActive(row: WorkflowRunRow): boolean {
    return row.kind === 'status' && ACTIVE_STATUSES.includes(row.status);
}

/** The controls a row offers. Each comes from the server's `actions`, never from the status alone. */
export interface WorkflowRunRowControls {
    cancel: boolean;
    retry: boolean;
    /** Retry would be offered, but chats can't start workflows right now. */
    retryTurnedOff: boolean;
    approve: boolean;
    reconnect: boolean;
    openRun: true;
}

export function workflowRunRowControls(row: WorkflowRunRow, available: boolean): WorkflowRunRowControls {
    if (row.kind !== 'status') {
        return { cancel: false, retry: false, retryTurnedOff: false, approve: false, reconnect: false, openRun: true };
    }
    const retryAllowed = row.actions.retry && row.status === 'failed' && row.retry_blocked === null;
    return {
        cancel: row.actions.cancel && ACTIVE_STATUSES.includes(row.status),
        retry: retryAllowed && available,
        retryTurnedOff: retryAllowed && !available,
        approve: row.actions.approve && row.status === 'waiting' && row.waiting?.action === 'approve'
            && Boolean(row.waiting.gate_id),
        reconnect: row.status === 'waiting' && row.waiting?.action === 'reconnect',
        openRun: true,
    };
}

const STATUS_LABELS: Record<WorkflowRunRowStatus, string> = {
    queued: 'Queued',
    running: 'Running',
    waiting: 'Needs you',
    completed: 'Completed',
    completed_partial: 'Partly completed',
    failed: 'Failed',
    expired: 'Timed out',
    cancelled: 'Cancelled',
};

export const WORKFLOW_RUN_STATUS_UNAVAILABLE = 'Status unavailable';

export function workflowRunStatusLabel(row: WorkflowRunRow): string {
    return row.kind === 'status' ? STATUS_LABELS[row.status] : WORKFLOW_RUN_STATUS_UNAVAILABLE;
}

const WAITING_TEXT: Record<WorkflowWaitingReason, string> = {
    approval: 'Waiting for your approval.',
    microsoft_365_reconnect: 'Reconnect Microsoft 365 to continue.',
    microsoft_365_approval: 'Waiting for a Microsoft 365 approval.',
    output_review: 'Waiting for you to review its output.',
    recovery: 'Recovering after an interruption.',
    deadline_exceeded: 'Paused. Open the run to continue.',
    paused: 'Paused. Open the run to continue.',
};

export function workflowWaitingText(reason: WorkflowWaitingReason): string {
    return WAITING_TEXT[reason];
}

const RETRY_BLOCKED_TEXT: Record<WorkflowRetryBlockedCode, string> = {
    retry_unavailable: 'Retry isn\'t available for this run right now.',
    workflow_deleted: 'The workflow was deleted, so this run can\'t be retried.',
    not_resumable: 'This run can\'t be retried.',
    deadline_exceeded: 'This run reached its time limit, so it can\'t be retried.',
    workflow_definition_changed: 'The workflow changed after this run started. Start a new run from Workflows.',
    workflow_already_running: 'Another run of this workflow is in progress. Retry when it finishes.',
};

export function workflowRetryBlockedText(code: WorkflowRetryBlockedCode): string {
    return RETRY_BLOCKED_TEXT[code];
}

export const WORKFLOW_RETRY_TURNED_OFF_TEXT =
    'Starting workflows from chat is turned off, so Retry isn\'t available here.';
export const WORKFLOW_RUN_CANCELLED_TEXT = 'The run was cancelled.';
export const WORKFLOW_RESULTS_POSTING_TEXT = 'Posting results…';
export const WORKFLOW_RESULTS_POSTED_TEXT = 'Results posted below';
export const WORKFLOW_RESULTS_POSTED_ELSEWHERE_TEXT = 'Results were posted to this chat.';
export const WORKFLOW_RESULTS_IN_HISTORY_TEXT = 'The results are in the workflow\'s run history.';
export const WORKFLOW_STATUS_READ_ERROR_TEXT = 'Couldn\'t check the run status right now. Try again.';
export const WORKFLOW_STATUS_HALTED_TEXT = 'Live status isn\'t available right now.';

/** "Step 2 of 5", once the server has counted the steps; empty until then. */
export function workflowRunStepText(row: WorkflowRunStatusRow): string {
    if (row.step_count === null || row.step_count <= 0 || row.step_index === null) {
        return '';
    }
    return `Step ${Math.min(row.step_index + 1, row.step_count)} of ${row.step_count}`;
}

/** The step's own label, when the server sends one: one line, or empty. */
export function workflowRunStepLabel(row: WorkflowRunStatusRow): string {
    return row.step_label ? oneLine(row.step_label) : '';
}

/** "45 s", "3 min" or "1 h 5 min". */
export function formatWorkflowElapsed(seconds: number | null): string {
    if (seconds === null || !Number.isFinite(seconds) || seconds < 0) {
        return '';
    }
    const whole = Math.floor(seconds);
    if (whole < 60) {
        return `${whole} s`;
    }
    if (whole < 3600) {
        return `${Math.floor(whole / 60)} min`;
    }
    const hours = Math.floor(whole / 3600);
    const minutes = Math.floor((whole % 3600) / 60);
    return minutes > 0 ? `${hours} h ${minutes} min` : `${hours} h`;
}

/** The reader's local time of a server time, "9:07 AM", or empty for anything unreadable. */
export function formatCheckedTime(checkedAt: string | null): string {
    if (!checkedAt) return '';
    const moment = new Date(checkedAt);
    if (Number.isNaN(moment.getTime())) return '';
    return moment.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}
