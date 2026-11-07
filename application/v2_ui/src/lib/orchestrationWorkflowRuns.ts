// orchestrationWorkflowRuns.ts
// The saved workflows an orchestration plan started, for the run links under its answer.
//
// A plan's workflow_run step starts one of the requester's saved workflows and links to the run.
// The links read each run's status from the server when the answer loads. Nothing polls: a
// reload reads the status again. Every response is checked before anything is shown, so a
// response of the wrong shape fails closed rather than linking to the wrong run.

import { api } from './apiClient';

/** The orchestration capability whose completed step leaves a run link on its answer. */
export const WORKFLOW_RUN_CAPABILITY = 'workflow_run';

export const WORKFLOW_RUN_LINKS_INVALID_RESPONSE = 'The workflow run links returned an invalid response.';

export const WORKFLOW_RUN_LINK_STATES = [
    'queued', 'running', 'waiting', 'completed', 'completed_partial', 'failed', 'cancelled', 'skipped', 'unavailable',
] as const;
export type WorkflowRunLinkState = typeof WORKFLOW_RUN_LINK_STATES[number];

/** The saved workflow and run a link opens, with `workflowRunHref`. */
export interface WorkflowRunTarget {
    workflowId: string;
    runId: string;
}

export interface WorkflowRunLinkItem {
    step_id: string;
    /** The workflow's name, as plain text. Empty when the link cannot be used here. */
    name: string;
    state: WorkflowRunLinkState;
    /** Why the run cannot be opened; only for an unavailable link. */
    reason: string | null;
    /** The run the link opens in Workflows; null for an unavailable link. */
    run: WorkflowRunTarget | null;
}

export interface WorkflowRunLinkList {
    run_id: string;
    workflow_runs: WorkflowRunLinkItem[];
}

const STATE_LABELS: Record<WorkflowRunLinkState, string> = {
    queued: 'Queued',
    running: 'Running',
    waiting: 'Waiting',
    completed: 'Completed',
    completed_partial: 'Partly completed',
    failed: 'Failed',
    cancelled: 'Cancelled',
    skipped: 'Skipped',
    unavailable: 'Unavailable',
};

// Why a run cannot be opened. Fixed text: the server sends only the closed reason.
const REASON_TEXT: Record<string, string> = {
    workflow_deleted: 'This workflow was deleted, so its run cannot be opened.',
    workflow_run_missing: 'This run is no longer in the workflow\'s run history.',
    workflow_runs_disabled: 'Starting saved workflows from chat is turned off, so this link is not available.',
    workflow_role_required: 'You no longer have access to personal workflows.',
    workflow_shared_conversation: 'Links to workflow runs appear only in your own conversations.',
    content_review: 'This response is in content review, so its workflow link is not available.',
};
const REASON_FALLBACK = 'This workflow run is not available.';
const DEFAULT_NAME = 'Saved workflow';

export function workflowRunStateLabel(state: WorkflowRunLinkState): string {
    return STATE_LABELS[state];
}

export function workflowRunReasonText(reason: string | null): string {
    return (reason && Object.prototype.hasOwnProperty.call(REASON_TEXT, reason) ? REASON_TEXT[reason] : '')
        || REASON_FALLBACK;
}

/** The name a link shows: the workflow's own name, or a neutral label when the server sent none. */
export function workflowRunDisplayName(item: Pick<WorkflowRunLinkItem, 'name'>): string {
    return item.name.trim() || DEFAULT_NAME;
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function invalid(): never {
    throw new Error(WORKFLOW_RUN_LINKS_INVALID_RESPONSE);
}

function textOf(value: unknown): string {
    return typeof value === 'string' ? value : invalid();
}

function idOf(value: unknown): string {
    const id = textOf(value);
    return id.trim() ? id : invalid();
}

function stateOf(value: unknown): WorkflowRunLinkState {
    return typeof value === 'string' && (WORKFLOW_RUN_LINK_STATES as readonly string[]).includes(value)
        ? value as WorkflowRunLinkState
        : invalid();
}

function itemOf(value: unknown): WorkflowRunLinkItem {
    if (!isRecord(value)) invalid();
    const state = stateOf(value.state);
    const base = { step_id: idOf(value.step_id), name: textOf(value.name), state };
    if (state === 'unavailable') {
        // An unavailable run is never linked, and it always says why.
        if (value.workflow_id !== null || value.workflow_run_id !== null) invalid();
        return { ...base, reason: idOf(value.reason), run: null };
    }
    if (value.reason !== null) invalid();
    return { ...base, reason: null, run: { workflowId: idOf(value.workflow_id), runId: idOf(value.workflow_run_id) } };
}

/** Check a link response. Exported so a test can hold the checks against real responses. */
export function parseWorkflowRunLinkList(value: unknown, runId: string): WorkflowRunLinkList {
    if (!isRecord(value) || value.run_id !== runId || !Array.isArray(value.workflow_runs)) invalid();
    const items = value.workflow_runs.map(itemOf);
    if (new Set(items.map((item) => item.step_id)).size !== items.length) invalid();
    return { run_id: runId, workflow_runs: items };
}

function linksPath(runId: string): string {
    return `/api/v2/orchestration/runs/${encodeURIComponent(runId)}/workflow-runs`;
}

/** The saved workflow runs a plan started, each with its status when read, for its requester. */
export async function fetchWorkflowRunLinks(
    runId: string,
    conversationId: string,
    signal?: AbortSignal,
): Promise<WorkflowRunLinkList> {
    const query = new URLSearchParams({ conversation_id: conversationId });
    return parseWorkflowRunLinkList(await api.get<unknown>(`${linksPath(runId)}?${query}`, signal), runId);
}

/** Whether an answer's orchestration metadata says a workflow_run step completed in its run. */
export function orchestrationStartedWorkflow(metadata: unknown): boolean {
    if (!isRecord(metadata)) return false;
    const summary = metadata.plan_summary;
    return isRecord(summary) && Array.isArray(summary.capabilities_used)
        && summary.capabilities_used.includes(WORKFLOW_RUN_CAPABILITY);
}
