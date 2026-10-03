// workflowProposals.ts
// The workflows an orchestration plan proposed, and the requester's decisions on them.
//
// A plan that sets up recurring work proposes a personal workflow instead of creating one. The
// proposal card reads each proposal from the status route and records Create, Deny or an edited
// Create through the decision routes. Every response is checked before anything is shown: the
// card renders planner-written text and standing instructions, so a response of the wrong shape
// fails closed rather than showing half a proposal.

import { api } from './apiClient';
import { WORKFLOW_LINK_PARAM } from './workflowRunLink';

/** The orchestration capability whose completed step leaves a proposal on its answer. */
export const WORKFLOW_PROPOSE_CAPABILITY = 'workflow_propose';

export const WORKFLOW_PROPOSAL_INVALID_RESPONSE = 'The workflow proposal returned an invalid response.';

export const WORKFLOW_PROPOSAL_STATES = [
    'pending', 'creating', 'created_enabled', 'created_paused', 'denied', 'deleted', 'expired', 'unavailable',
] as const;
export type WorkflowProposalState = typeof WORKFLOW_PROPOSAL_STATES[number];

const TRIGGER_TYPES = ['manual', 'calendar', 'interval', 'file_sync'] as const;
const RUNS_KINDS = ['manual', 'count', 'on_change'] as const;
const ALERT_MODES = ['every_run', 'failures_only'] as const;
const ALERT_SEVERITIES = ['info', 'low'] as const;
const SIMILAR_REASONS = ['same_sources', 'same_schedule', 'similar_name'] as const;
const APPROVAL_STATES = ['waiting', 'approved'] as const;

export type WorkflowProposalTriggerType = typeof TRIGGER_TYPES[number];

export interface WorkflowProposalTask {
    title: string;
    runner: 'agent' | 'model';
    agent_name: string;
    /** What the task's agent can do, as closed action kinds. */
    action_kinds: string[];
    /** What the plan said the task needs to do. */
    requested_actions: string[];
    /** The names of the documents the task reads. */
    inputs: string[];
    /** The task's full standing instructions, shown as plain text. */
    instructions: string;
    /** Present when the task merges files with code instead of running a model or agent. */
    merge?: WorkflowProposalMerge;
}

export const MERGE_FILES = ['inputs', 'changed', 'all', 'recent'] as const;
export const MERGE_OUTPUT_FORMATS = ['csv', 'xlsx', 'pdf', 'docx', 'pptx'] as const;
export const MERGE_KINDS = ['tabular', 'workbook', 'pdf', 'docx', 'pptx'] as const;

export interface WorkflowProposalMerge {
    /** Older proposals were all row merges, so a missing kind reads as tabular. */
    kind: typeof MERGE_KINDS[number];
    files: typeof MERGE_FILES[number];
    output_format: typeof MERGE_OUTPUT_FORMATS[number];
}

const MERGE_FILE_NOUNS: Record<WorkflowProposalMerge['kind'], [string, string]> = {
    tabular: ['CSV and Excel file', 'CSV and Excel files'],
    workbook: ['CSV and Excel file', 'CSV and Excel files'],
    pdf: ['PDF', 'PDFs'],
    docx: ['Word document', 'Word documents'],
    pptx: ['PowerPoint deck', 'PowerPoint decks'],
};

/** How a proposed merge task runs: code merges files into one file, with no model or agent. */
export function workflowProposalMergeText(task: Pick<WorkflowProposalTask, 'merge'>): string {
    const merge = task.merge;
    if (!merge) return '';
    const [one, many] = MERGE_FILE_NOUNS[merge.kind];
    const files = {
        inputs: 'the input files below, in order,',
        changed: 'the files each sync adds or changes',
        all: `every ${one} in your personal workspace`,
        recent: `the ${many} added or changed recently in your personal workspace`,
    }[merge.files];
    const output = merge.kind === 'workbook' ? 'one Excel workbook, a sheet per file,'
        : merge.kind === 'pdf' ? 'one PDF'
            : merge.kind === 'docx' ? 'one Word document'
                : merge.kind === 'pptx' ? 'one PowerPoint deck'
                    : `one ${merge.output_format === 'xlsx' ? 'Excel' : 'CSV'} file`;
    return `Merges ${files} into ${output} with code. No model runs.`;
}

export interface WorkflowProposalSummary {
    name: string;
    description: string;
    trigger_type: WorkflowProposalTriggerType;
    schedule_label: string;
    time_zone: string;
    runs_per_month: {
        kind: typeof RUNS_KINDS[number];
        value: number | null;
        checks_per_month: number | null;
    };
    tasks: WorkflowProposalTask[];
    file_sync_sources: string[];
    alerts: { mode: typeof ALERT_MODES[number]; severity: typeof ALERT_SEVERITIES[number] };
    durable: boolean;
}

export interface WorkflowProposalM365 {
    required: boolean;
    can_send: boolean;
    run_as: 'self' | 'none';
    sources: string[];
    /** From the stored connection record only; null when it was not needed or could not be read. */
    connected: boolean | null;
    approval_state: typeof APPROVAL_STATES[number] | null;
}

export interface WorkflowProposalSimilar {
    workflow_id: string;
    name: string;
    schedule_label: string;
    why: typeof SIMILAR_REASONS[number][];
}

export interface WorkflowProposalWorkflow {
    id: string;
    name: string;
    is_enabled: boolean;
}

export interface WorkflowProposalActions {
    accept: boolean;
    edit: boolean;
    deny: boolean;
    create_again: boolean;
    open_workflow: boolean;
}

export interface WorkflowProposal {
    proposal_id: string;
    step_id: string;
    state: WorkflowProposalState;
    reason: string | null;
    created_at: string | null;
    expires_at: string | null;
    actions: WorkflowProposalActions;
    /** Null unless the requester may act on proposals here. */
    summary: WorkflowProposalSummary | null;
    similar_workflows: WorkflowProposalSimilar[];
    m365: WorkflowProposalM365 | null;
    workflow: WorkflowProposalWorkflow | null;
}

export interface WorkflowProposalList {
    run_id: string;
    proposals: WorkflowProposal[];
}

export type WorkflowProposalMode = 'paused' | 'enabled';

export interface WorkflowProposalAcceptRequest {
    conversation_id: string;
    mode?: WorkflowProposalMode;
    /** Create the workflow again after the one this proposal created was deleted. */
    create_again?: boolean;
    /** The workflow editor's draft, for a proposal changed before it was accepted. */
    workflow?: Record<string, unknown>;
}

export interface WorkflowProposalAcceptResponse {
    proposal_id: string;
    created: boolean;
    state: 'created_enabled' | 'created_paused';
    workflow: WorkflowProposalWorkflow;
}

export interface WorkflowProposalDraft {
    proposal_id: string;
    workflow: Record<string, unknown>;
    url_access_note: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function invalid(): never {
    throw new Error(WORKFLOW_PROPOSAL_INVALID_RESPONSE);
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

function taskOf(value: unknown): WorkflowProposalTask {
    if (!isRecord(value)) invalid();
    const merge = value.merge;
    if (merge !== undefined && !isRecord(merge)) invalid();
    return {
        title: textOf(value.title),
        runner: oneOf(['agent', 'model'] as const, value.runner),
        agent_name: textOf(value.agent_name),
        action_kinds: textsOf(value.action_kinds),
        requested_actions: textsOf(value.requested_actions),
        inputs: textsOf(value.inputs),
        instructions: textOf(value.instructions),
        ...(isRecord(merge) ? {
            merge: {
                kind: merge.kind === undefined ? 'tabular' : oneOf(MERGE_KINDS, merge.kind),
                files: oneOf(MERGE_FILES, merge.files),
                output_format: oneOf(MERGE_OUTPUT_FORMATS, merge.output_format),
            },
        } : {}),
    };
}

function summaryOf(value: unknown): WorkflowProposalSummary | null {
    if (value === null) return null;
    if (!isRecord(value) || !isRecord(value.runs_per_month) || !isRecord(value.alerts) || !Array.isArray(value.tasks)) {
        invalid();
    }
    const runs = value.runs_per_month;
    return {
        name: textOf(value.name),
        description: textOf(value.description),
        trigger_type: oneOf(TRIGGER_TYPES, value.trigger_type),
        schedule_label: textOf(value.schedule_label),
        time_zone: textOf(value.time_zone),
        runs_per_month: {
            kind: oneOf(RUNS_KINDS, runs.kind),
            value: countOf(runs.value),
            checks_per_month: countOf(runs.checks_per_month),
        },
        tasks: value.tasks.map(taskOf),
        file_sync_sources: textsOf(value.file_sync_sources),
        alerts: {
            mode: oneOf(ALERT_MODES, value.alerts.mode),
            severity: oneOf(ALERT_SEVERITIES, value.alerts.severity),
        },
        durable: flagOf(value.durable),
    };
}

function m365Of(value: unknown): WorkflowProposalM365 | null {
    if (value === null) return null;
    if (!isRecord(value)) invalid();
    return {
        required: flagOf(value.required),
        can_send: flagOf(value.can_send),
        run_as: oneOf(['self', 'none'] as const, value.run_as),
        sources: textsOf(value.sources),
        connected: value.connected === null ? null : flagOf(value.connected),
        approval_state: value.approval_state === null ? null : oneOf(APPROVAL_STATES, value.approval_state),
    };
}

function similarOf(value: unknown): WorkflowProposalSimilar {
    if (!isRecord(value) || !Array.isArray(value.why)) invalid();
    return {
        workflow_id: idOf(value.workflow_id),
        name: textOf(value.name),
        schedule_label: textOf(value.schedule_label),
        why: value.why.map((reason) => oneOf(SIMILAR_REASONS, reason)),
    };
}

function workflowOf(value: unknown): WorkflowProposalWorkflow {
    if (!isRecord(value)) invalid();
    return { id: idOf(value.id), name: textOf(value.name), is_enabled: flagOf(value.is_enabled) };
}

function actionsOf(value: unknown): WorkflowProposalActions {
    if (!isRecord(value)) invalid();
    return {
        accept: flagOf(value.accept),
        edit: flagOf(value.edit),
        deny: flagOf(value.deny),
        create_again: flagOf(value.create_again),
        open_workflow: flagOf(value.open_workflow),
    };
}

function proposalOf(value: unknown): WorkflowProposal {
    if (!isRecord(value) || !Array.isArray(value.similar_workflows)) invalid();
    const state = oneOf(WORKFLOW_PROPOSAL_STATES, value.state);
    const created = state === 'created_enabled' || state === 'created_paused';
    const workflow = value.workflow === null ? null : workflowOf(value.workflow);
    // A created proposal always names its workflow, and nothing else does.
    if (created !== (workflow !== null)) invalid();
    return {
        proposal_id: idOf(value.proposal_id),
        step_id: textOf(value.step_id),
        state,
        reason: optionalText(value.reason),
        created_at: optionalText(value.created_at),
        expires_at: optionalText(value.expires_at),
        actions: actionsOf(value.actions),
        summary: summaryOf(value.summary),
        similar_workflows: value.similar_workflows.map(similarOf),
        m365: m365Of(value.m365),
        workflow,
    };
}

/** Check a status response. Exported so a test can hold the checks against real responses. */
export function parseWorkflowProposalList(value: unknown, runId: string): WorkflowProposalList {
    if (!isRecord(value) || value.run_id !== runId || !Array.isArray(value.proposals)) invalid();
    return { run_id: runId, proposals: value.proposals.map(proposalOf) };
}

function proposalsPath(runId: string, suffix = ''): string {
    return `/api/v2/orchestration/runs/${encodeURIComponent(runId)}/workflow-proposals${suffix}`;
}

function proposalPath(runId: string, proposalId: string, action: string): string {
    return proposalsPath(runId, `/${encodeURIComponent(proposalId)}/${action}`);
}

/** The proposals a run shows its requester, each with the actions its card offers now. */
export async function fetchWorkflowProposals(
    runId: string,
    conversationId: string,
    signal?: AbortSignal,
): Promise<WorkflowProposalList> {
    const query = new URLSearchParams({ conversation_id: conversationId });
    return parseWorkflowProposalList(await api.get<unknown>(`${proposalsPath(runId)}?${query}`, signal), runId);
}

export async function acceptWorkflowProposal(
    runId: string,
    proposalId: string,
    body: WorkflowProposalAcceptRequest,
): Promise<WorkflowProposalAcceptResponse> {
    const response = await api.post<unknown>(proposalPath(runId, proposalId, 'accept'), body);
    if (!isRecord(response) || response.proposal_id !== proposalId) invalid();
    return {
        proposal_id: proposalId,
        created: flagOf(response.created),
        state: oneOf(['created_enabled', 'created_paused'] as const, response.state),
        workflow: workflowOf(response.workflow),
    };
}

export async function denyWorkflowProposal(
    runId: string,
    proposalId: string,
    conversationId: string,
): Promise<void> {
    const response = await api.post<unknown>(
        proposalPath(runId, proposalId, 'deny'), { conversation_id: conversationId },
    );
    if (!isRecord(response) || response.proposal_id !== proposalId || response.state !== 'denied') invalid();
}

/** A pending proposal as an unsaved workflow editor draft. */
export async function fetchWorkflowProposalDraft(
    runId: string,
    proposalId: string,
    conversationId: string,
    signal?: AbortSignal,
): Promise<WorkflowProposalDraft> {
    const query = new URLSearchParams({ conversation_id: conversationId });
    const response = await api.get<unknown>(`${proposalPath(runId, proposalId, 'draft')}?${query}`, signal);
    if (!isRecord(response) || response.proposal_id !== proposalId || !isRecord(response.workflow)) invalid();
    return { proposal_id: proposalId, workflow: response.workflow, url_access_note: textOf(response.url_access_note) };
}

/** The V2 Workflows page with one workflow opened, the link format Workflows already reads. */
export function workflowProposalLink(workflowId: string): string {
    return `/workspace/workflows?${new URLSearchParams({ [WORKFLOW_LINK_PARAM]: workflowId })}`;
}

/** Whether an answer's orchestration metadata says a proposal step completed in its run. */
export function orchestrationProposedWorkflow(metadata: unknown): boolean {
    if (!isRecord(metadata)) return false;
    const summary = metadata.plan_summary;
    return isRecord(summary) && Array.isArray(summary.capabilities_used)
        && summary.capabilities_used.includes(WORKFLOW_PROPOSE_CAPABILITY);
}
