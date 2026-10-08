// workflowPlanReplay.ts
// Client contract for saving a completed chat orchestration plan as a read-only replay workflow.

import { ApiError, api, requestWithStatus } from './apiClient';
import type { WorkflowDefinition } from './workflowEditor';

export const PLAN_REPLAY_INVALID_RESPONSE = 'The saved chat plan returned an invalid response.';
export const PLAN_REPLAY_GENERIC_ERROR = 'The saved chat plan could not be updated. Reload the chat and try again.';
export const PLAN_REPLAY_RESULT_CONTRACT = 'plan-replay-result-v1';
// The server saves every replay workflow with one editable alert rule under this name.
export const PLAN_REPLAY_ALERT_RULE_NAME = 'Run failed';
export const PLAN_REPLAY_ALERT_NOTICE =
    `If a run fails, you'll get a '${PLAN_REPLAY_ALERT_RULE_NAME}' notification in the bell. You can change this in the workflow's alerts.`;

const HASH = /^[a-f0-9]{64}$/;
const SERVER_TEXT_CODES = new Set(['cadence_below_minimum', 'invalid_workflow_settings', 'invalid_workflow_alerts']);

export const PLAN_REPLAY_CAPABILITY_LABELS: Readonly<Record<string, string>> = {
    document_search: 'Search documents',
    document_analyze: 'Analyse documents',
    document_compare: 'Compare documents',
    document_merge: 'Merge documents',
    tabular_inspect: 'Inspect spreadsheets',
    compose: 'Prepare content',
    generate_image: 'Generate image',
};

export const ERROR_TEXT: Readonly<Record<string, string>> = {
    replay_disabled: 'Repeating chat plans is turned off. Ask an admin to turn it on, then run the workflow again.',
    orchestration_disabled: 'Chat orchestration is turned off, so this saved plan can\'t run.',
    personal_workflows_disabled: 'Personal workflows are turned off, so this saved plan can\'t run.',
    group_not_supported: 'Only personal workflows can repeat a chat plan.',
    creator_mismatch: 'This saved plan can only run as the person who created it.',
    plan_hash_mismatch: 'This saved plan changed after it was approved. Create it again from chat.',
    allowlist_version_unsupported: 'This saved plan was made with rules this version doesn\'t support. Create it again from chat.',
    capability_not_replayable: 'A step in this plan can\'t be repeated by a saved workflow.',
    capability_unavailable: 'A step in this plan is turned off or no longer available.',
    role_required: 'A step in this plan needs your signed-in session, which a repeated run doesn\'t have.',
    elicitation_not_replayable: 'This plan asked you a question before it ran. Repeated runs can\'t stop to ask.',
    source_unavailable: 'A document, group or public workspace this plan reads is no longer available to you.',
    source_run_not_eligible: 'Only a completed plan that you approved can be saved as a workflow.',
    shared_conversation_not_allowed: 'Plans from shared conversations can\'t be saved as a workflow.',
    conversation_context_not_replayable: 'This plan relies on earlier messages in the chat, so it can\'t be repeated on its own.',
    replay_wait_unsupported: 'A step in this plan waits for a file or result to finish, which a repeated run can\'t do yet.',
    replay_budget_exceeded: 'The repeated plan took longer than its time limit and was stopped.',
    replay_execution_failed: 'The repeated plan could not finish. Open the run for details.',
    plan_replay_read_only: 'A saved plan can\'t be edited. Create it again from chat.',
    workflow_replay_run_managed: 'This plan runs as part of a saved workflow. Open the workflow to run or cancel it.',
    model_unavailable: 'The model this plan used is no longer available. Create it again from chat.',
    quota_exceeded: 'You already have the most saved chat-plan workflows allowed. Delete one before adding another.',
    workflow_conflict: 'This workflow is being changed or deleted. Reload and try again.',
    workflow_unavailable: 'This workflow was deleted or is being deleted, so the saved plan didn\'t run.',
    run_not_found: 'That plan could not be found.',
    invalid_request: 'The request was not valid. Reload the plan and try again.',
    service_unavailable: 'The plan could not be saved as a workflow right now. Try again.',
};

export interface PlanReplayRefusal {
    code: string;
    step_number: number;
    step_id: string;
    capability_id: string;
    message: string;
}

export interface PlanReplayPreviewStep {
    number: number;
    step_id: string;
    title: string;
    capability_id: string;
    capability_label: string;
    enabled: true;
}

export interface PlanReplayPreview {
    eligible: boolean;
    request: string;
    steps: PlanReplayPreviewStep[];
    refusals: PlanReplayRefusal[];
    plan_sha256: string;
    time_handling: 'frozen_with_run_time_line';
    time_zone: string;
    min_interval_seconds: number;
    allowlist_version: 'plan-replay-allowlist-v1';
    max_steps: number;
}

export interface SavePlanReplayBody {
    conversation_id: string;
    plan_sha256: string;
    name?: string;
    description?: string;
    trigger_type?: 'manual' | 'interval';
    schedule?: unknown;
    enabled?: boolean;
}

export interface SavePlanReplayResponse {
    workflow: WorkflowDefinition;
    created: boolean;
}

export interface PlanReplayResultStep {
    step_id: string;
    capability_id: string;
    label: string;
    status: string;
}

export interface PlanReplayResult {
    contract: typeof PLAN_REPLAY_RESULT_CONTRACT;
    orchestration_run_id: string;
    conversation_id: string;
    plan_sha256: string;
    status: string;
    outcome: string;
    steps: PlanReplayResultStep[];
    final_response: {
        message_id: string;
        text: string;
        truncated?: boolean;
    };
    artifacts: Array<{
        id: string;
        kind: 'image' | 'file';
        message_id?: string;
    }>;
}

export interface PlanReplaySummaryStep {
    number: number;
    title: string;
    capability_id: string;
    label: string;
}

export interface PlanReplaySummary {
    request: string;
    steps: PlanReplaySummaryStep[];
    frozen_at: string;
    allowlist_version: string;
    time_handling: string;
    time_zone: string;
}

export class WorkflowPlanReplayError extends Error {
    readonly code: string;
    readonly status: number;
    readonly text: string;
    readonly refusals: PlanReplayRefusal[];

    constructor(code: string, status: number, text: string, refusals: PlanReplayRefusal[]) {
        super(text);
        this.name = 'WorkflowPlanReplayError';
        this.code = code;
        this.status = status;
        this.text = text;
        this.refusals = refusals;
    }
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function invalid(): never {
    throw new Error(PLAN_REPLAY_INVALID_RESPONSE);
}

function text(value: unknown): string {
    return typeof value === 'string' ? value : invalid();
}

function optionalText(value: unknown): string {
    return value === null || value === undefined ? '' : text(value);
}

function whole(value: unknown, min = 0): number {
    return typeof value === 'number' && Number.isInteger(value) && value >= min ? value : invalid();
}

function parseRefusals(value: unknown): PlanReplayRefusal[] {
    if (!Array.isArray(value)) return invalid();
    return value.map((entry) => {
        if (!isRecord(entry)) invalid();
        return {
            code: text(entry.code),
            step_number: whole(entry.step_number, 0),
            step_id: optionalText(entry.step_id),
            capability_id: optionalText(entry.capability_id),
            message: text(entry.message),
        };
    });
}

function previewStep(value: unknown): PlanReplayPreviewStep {
    if (!isRecord(value)) invalid();
    return {
        number: whole(value.number, 1),
        step_id: text(value.step_id),
        title: text(value.title),
        capability_id: text(value.capability_id),
        capability_label: text(value.capability_label),
        enabled: value.enabled === true ? true : invalid(),
    };
}

function parsePreview(value: unknown): PlanReplayPreview {
    if (!isRecord(value)) invalid();
    const planHash = text(value.plan_sha256);
    if (!HASH.test(planHash)) invalid();
    if (!Array.isArray(value.steps)) invalid();
    return {
        eligible: typeof value.eligible === 'boolean' ? value.eligible : invalid(),
        request: text(value.request),
        steps: value.steps.map(previewStep),
        refusals: parseRefusals(value.refusals),
        plan_sha256: planHash,
        time_handling: value.time_handling === 'frozen_with_run_time_line' ? value.time_handling : invalid(),
        time_zone: optionalText(value.time_zone),
        min_interval_seconds: whole(value.min_interval_seconds, 1),
        allowlist_version: value.allowlist_version === 'plan-replay-allowlist-v1' ? value.allowlist_version : invalid(),
        max_steps: whole(value.max_steps, 1),
    };
}

function planReplayPath(runId: string, conversationId: string): string {
    const query = new URLSearchParams({ conversation_id: conversationId });
    return `/api/v2/orchestration/runs/${encodeURIComponent(runId)}/plan-replay?${query.toString()}`;
}

export async function fetchPlanReplayPreview(
    runId: string,
    conversationId: string,
    signal?: AbortSignal,
): Promise<PlanReplayPreview> {
    try {
        return parsePreview(await api.get<unknown>(planReplayPath(runId, conversationId), signal));
    } catch (cause) {
        throw planReplayError(cause);
    }
}

export async function savePlanReplayWorkflow(runId: string, body: SavePlanReplayBody): Promise<SavePlanReplayResponse> {
    try {
        const { data, status } = await requestWithStatus<unknown>(
            planReplayPath(runId, body.conversation_id),
            { method: 'POST', body },
        );
        if (!isRecord(data) || data.ok !== true || !isRecord(data.workflow)) invalid();
        const created = typeof data.created === 'boolean' ? data.created : invalid();
        if (created !== (status === 201)) invalid();
        return { workflow: data.workflow as unknown as WorkflowDefinition, created };
    } catch (cause) {
        throw planReplayError(cause);
    }
}

function errorTextFor(code: string, status: number, serverText: string): string {
    if (SERVER_TEXT_CODES.has(code) && serverText) return serverText;
    if (Object.prototype.hasOwnProperty.call(ERROR_TEXT, code)) return ERROR_TEXT[code];
    if (status === 401) return 'Sign in again to continue.';
    if (status === 403) return 'You do not have access to save this chat plan as a workflow.';
    return PLAN_REPLAY_GENERIC_ERROR;
}

export function planReplayError(cause: unknown): WorkflowPlanReplayError {
    if (cause instanceof WorkflowPlanReplayError) return cause;
    if (cause instanceof ApiError) {
        const payload = isRecord(cause.payload) ? cause.payload : {};
        const code = typeof payload.code === 'string' ? payload.code : '';
        const serverText = typeof payload.error === 'string' ? payload.error : cause.message;
        const refusals = Array.isArray(payload.refusals) ? parseRefusals(payload.refusals) : [];
        return new WorkflowPlanReplayError(code, cause.status, errorTextFor(code, cause.status, serverText), refusals);
    }
    if (cause instanceof TypeError) {
        return new WorkflowPlanReplayError('', 0, 'SimpleChat could not be reached. Check your connection and try again.', []);
    }
    if (cause instanceof Error && cause.message === PLAN_REPLAY_INVALID_RESPONSE) {
        return new WorkflowPlanReplayError('', 0, PLAN_REPLAY_INVALID_RESPONSE, []);
    }
    return new WorkflowPlanReplayError('', 0, PLAN_REPLAY_GENERIC_ERROR, []);
}

export function readPlanReplayResult(value: unknown): PlanReplayResult | null {
    if (!isRecord(value) || value.contract !== PLAN_REPLAY_RESULT_CONTRACT) return null;
    const finalResponse = isRecord(value.final_response) ? value.final_response : {};
    if (typeof value.orchestration_run_id !== 'string' || typeof value.conversation_id !== 'string' ||
        typeof value.plan_sha256 !== 'string' || !HASH.test(value.plan_sha256) ||
        typeof value.status !== 'string' || typeof value.outcome !== 'string' ||
        typeof finalResponse.message_id !== 'string' || typeof finalResponse.text !== 'string' ||
        !Array.isArray(value.steps) || !Array.isArray(value.artifacts)) return null;
    const steps: PlanReplayResultStep[] = [];
    for (const step of value.steps) {
        if (!isRecord(step) || typeof step.step_id !== 'string' || typeof step.capability_id !== 'string' ||
            typeof step.label !== 'string' || typeof step.status !== 'string') return null;
        steps.push({ step_id: step.step_id, capability_id: step.capability_id, label: step.label, status: step.status });
    }
    const artifacts: PlanReplayResult['artifacts'] = [];
    for (const artifact of value.artifacts) {
        if (!isRecord(artifact) || typeof artifact.id !== 'string' ||
            (artifact.kind !== 'image' && artifact.kind !== 'file')) return null;
        artifacts.push({
            id: artifact.id,
            kind: artifact.kind,
            ...(typeof artifact.message_id === 'string' ? { message_id: artifact.message_id } : {}),
        });
    }
    return {
        contract: PLAN_REPLAY_RESULT_CONTRACT,
        orchestration_run_id: value.orchestration_run_id,
        conversation_id: value.conversation_id,
        plan_sha256: value.plan_sha256,
        status: value.status,
        outcome: value.outcome,
        steps,
        final_response: {
            message_id: finalResponse.message_id,
            text: finalResponse.text,
            ...(finalResponse.truncated === true ? { truncated: true } : {}),
        },
        artifacts,
    };
}

export function planReplaySummary(task: unknown): PlanReplaySummary | null {
    const record = isRecord(task) ? task : {};
    const replay = isRecord(record.plan_replay) ? record.plan_replay : null;
    if (!replay) return null;
    const frozenPlan = isRecord(replay.frozen_plan) ? replay.frozen_plan : {};
    const provenance = isRecord(replay.provenance) ? replay.provenance : {};
    const stepsValue = Array.isArray(frozenPlan.steps) ? frozenPlan.steps : [];
    return {
        request: typeof replay.request === 'string' ? replay.request : '',
        steps: stepsValue.filter(isRecord).map((step, index) => {
            const capabilityId = typeof step.capability_id === 'string' ? step.capability_id : '';
            return {
                number: index + 1,
                title: typeof step.title === 'string' ? step.title : `Step ${index + 1}`,
                capability_id: capabilityId,
                label: PLAN_REPLAY_CAPABILITY_LABELS[capabilityId] ?? 'Unknown step',
            };
        }),
        frozen_at: typeof provenance.frozen_at === 'string' ? provenance.frozen_at : '',
        allowlist_version: typeof replay.allowlist_version === 'string' ? replay.allowlist_version : '',
        time_handling: typeof provenance.time_handling === 'string' ? provenance.time_handling : '',
        time_zone: typeof provenance.time_zone === 'string' ? provenance.time_zone : '',
    };
}

export function planReplayRunTimeZone(schedule: unknown, frozenTimeZone: string): string {
    // Mirrors the server: the schedule's own zone, then the zone the plan was frozen in, then UTC.
    const scheduleZone = isRecord(schedule) && typeof schedule.timezone === 'string' ? schedule.timezone.trim() : '';
    return scheduleZone || frozenTimeZone.trim() || 'UTC';
}

export function describePlanReplayTimeHandling(timeZone: string): string {
    const zone = timeZone.trim() || 'UTC';
    return `Dates written in the saved plan stay as written. Each run is also told the current date and time in ${zone}.`;
}
