// workflowExecutionHistory.ts
// Paged V3 workflow execution-history API contracts and client helpers.

import { api } from './apiClient';
import { isRecord } from './workspaceAuthoring';
import {
    workflowUrl,
    workflowLoopSelection,
    validWorkflowIterationPath,
    isWorkflowPublicationStatus,
    type WorkflowConsumedInput,
    type WorkflowIterationFrame,
    type WorkflowLoopSelection,
    type WorkflowResultReference,
    type WorkflowPublicationStatus,
    type WorkflowRunResultPage,
    type WorkflowScope,
    type WorkflowValidationResult,
} from './workflowEditor';

export interface WorkflowExecutionDecisionPreview {
    choice?: string;
    selected_branch?: string;
    branch_id?: string;
    target_node_id?: string;
    route_target?: string;
    target?: { node_id?: string; exit_region_id?: string } | null;
    exit_region_id?: string;
    gate_id?: string;
    input_digest?: string;
    reason_code?: string;
    timestamp?: string;
    decided_at?: string;
    [key: string]: unknown;
}

export interface WorkflowExecutionRecord {
    execution_id: string;
    node_id: string;
    node_kind: string;
    task_id?: string;
    iteration_path?: WorkflowIterationFrame[];
    region_id?: string;
    sequence?: number;
    state: string;
    attempt: number;
    reason_code?: string;
    decision?: WorkflowExecutionDecisionPreview;
    workflow_result?: {
        result_ref?: WorkflowResultReference;
        outputs?: Record<string, unknown>;
        authoritative_output?: string;
        consumed_inputs?: WorkflowConsumedInput[];
        reporting?: unknown;
        publication?: WorkflowPublicationStatus;
    };
    workflow_validation?: WorkflowValidationResult;
    consumed_inputs?: WorkflowConsumedInput[];
    started_at?: string;
    completed_at?: string;
    [key: string]: unknown;
}

export interface WorkflowExecutionAttemptRecord {
    execution_id: string;
    node_id: string;
    task_id?: string;
    attempt: number;
    state: string;
    iteration_path?: WorkflowIterationFrame[];
    started_at?: string;
    completed_at?: string;
    workflow_result?: {
        result_ref?: WorkflowResultReference;
        outputs?: Record<string, unknown>;
        authoritative_output?: string;
        consumed_inputs?: WorkflowConsumedInput[];
        reporting?: unknown;
        publication?: WorkflowPublicationStatus;
    };
    workflow_validation?: WorkflowValidationResult;
    consumed_inputs?: WorkflowConsumedInput[];
    [key: string]: unknown;
}

export interface WorkflowRuntimeDecisionRecord {
    execution_id?: string;
    node_id?: string;
    attempt?: number;
    gate_id?: string;
    input_digest?: string;
    choice?: string;
    selected_branch?: string;
    branch_id?: string;
    target_node_id?: string;
    route_target?: string;
    target?: { node_id?: string; exit_region_id?: string } | null;
    exit_region_id?: string;
    decision?: WorkflowExecutionDecisionPreview;
    reason_code?: string;
    iteration_path?: WorkflowIterationFrame[];
    timestamp?: string;
    decided_at?: string;
    [key: string]: unknown;
}

export interface WorkflowExecutionPage<T> {
    items: T[];
    next_cursor: string | null;
    total_count?: number;
    metadata?: {
        frozenAt?: string;
        recordOffset?: number;
        outputName?: string;
        validation?: WorkflowValidationResult;
        coverage?: Record<string, unknown>;
        admittedLimit?: number;
        selection?: WorkflowLoopSelection;
    };
}

export interface WorkflowLoopItemRecord {
    item_id: string;
    index: number;
    label: string;
    state: string;
    iteration_path: WorkflowIterationFrame[];
    execution_ids?: string[];
    record_count?: number;
}

export interface WorkflowContributorRecord extends WorkflowConsumedInput {
    item_id?: string;
    item_index?: number;
    record_offset?: number;
    record_count?: number;
    producer_record_offset?: number;
}

const REPORT_COUNT_FIELDS = [
    'record_count', 'page_count', 'reduction_levels', 'model_calls', 'checkpoint_replays', 'peak_input_tokens',
] as const;
const REPORT_BUDGET_NUMBERS = [
    'input_tokens', 'input_budget_tokens', 'context_window_tokens', 'max_input_tokens',
    'max_output_tokens', 'output_reserve_tokens', 'safety_tokens',
] as const;
const REPORT_BUDGET_TEXT = ['model_id', 'limit_source', 'limit_status', 'token_estimator', 'decision'] as const;

export type WorkflowReportingBudget =
    Partial<Record<typeof REPORT_BUDGET_NUMBERS[number], number | null>> &
    Partial<Record<typeof REPORT_BUDGET_TEXT[number], string | null>>;

export type WorkflowReportingSummary = {
    mode: 'complete_input' | 'record_pages';
    original_sources_reanalyzed: false;
    accepted_subset_only: boolean;
    context_budget: WorkflowReportingBudget;
} & Partial<Record<typeof REPORT_COUNT_FIELDS[number], number>>;

export function workflowReportingSummary(value: unknown): WorkflowReportingSummary | null {
    if (!isRecord(value) || value.mode !== 'complete_input' && value.mode !== 'record_pages' ||
        value.original_sources_reanalyzed !== false || typeof value.accepted_subset_only !== 'boolean' ||
        !isRecord(value.context_budget)) return null;
    const summary: WorkflowReportingSummary = {
        mode: value.mode,
        original_sources_reanalyzed: false,
        accepted_subset_only: value.accepted_subset_only,
        context_budget: {},
    };
    for (const name of REPORT_COUNT_FIELDS) {
        if (value[name] === undefined) continue;
        if (typeof value[name] !== 'number' || !Number.isSafeInteger(value[name]) || Number(value[name]) < 0) return null;
        summary[name] = value[name] as number;
    }
    for (const name of REPORT_BUDGET_NUMBERS) {
        const number = value.context_budget[name];
        if (number === undefined) continue;
        if (number !== null && (typeof number !== 'number' || !Number.isSafeInteger(number) || number < 0)) return null;
        summary.context_budget[name] = number as number | null;
    }
    for (const name of REPORT_BUDGET_TEXT) {
        const text = value.context_budget[name];
        if (text === undefined) continue;
        if (text !== null && (typeof text !== 'string' || text.length > 128)) return null;
        summary.context_budget[name] = text as string | null;
    }
    if (summary.context_budget.decision !== undefined && summary.context_budget.decision !== null &&
        summary.context_budget.decision !== 'full_input') return null;
    return summary;
}

function boundedLimit(limit: number, maximum = 100): number {
    if (!Number.isInteger(limit) || limit < 1 || limit > maximum) {
        throw new Error('The requested workflow history page size is invalid.');
    }
    return limit;
}

function validIdentity(value: unknown): value is string {
    return typeof value === 'string' && Boolean(value.trim()) && value.length <= 256;
}

function validPath(value: unknown): value is WorkflowIterationFrame[] | undefined {
    return value === undefined || validWorkflowIterationPath(value);
}

function validInputs(value: unknown): boolean {
    return value === undefined || Array.isArray(value) && value.every((input) =>
        isRecord(input) && (input.producer === undefined || isRecord(input.producer) && validPath(input.producer.iteration_path)));
}

function validResultMetadata(value: Record<string, unknown>): boolean {
    return validInputs(value.consumed_inputs) &&
        (value.workflow_result === undefined || isRecord(value.workflow_result) &&
            validInputs(value.workflow_result.consumed_inputs) &&
            (value.workflow_result.publication === undefined || isWorkflowPublicationStatus(value.workflow_result.publication))) &&
        (value.workflow_validation === undefined || isRecord(value.workflow_validation));
}

function isExecution(value: unknown): value is WorkflowExecutionRecord {
    return isRecord(value) && validIdentity(value.execution_id) && validIdentity(value.node_id) &&
        validIdentity(value.node_kind) && validIdentity(value.state) &&
        typeof value.attempt === 'number' && Number.isInteger(value.attempt) && value.attempt >= 0 &&
        validPath(value.iteration_path) && validResultMetadata(value);
}

function isAttempt(value: unknown): value is WorkflowExecutionAttemptRecord {
    return isRecord(value) && validIdentity(value.execution_id) && validIdentity(value.node_id) &&
        validIdentity(value.state) && typeof value.attempt === 'number' &&
        Number.isInteger(value.attempt) && value.attempt >= 1 && validPath(value.iteration_path) && validResultMetadata(value);
}

function isDecision(value: unknown): value is WorkflowRuntimeDecisionRecord {
    return isRecord(value) && validPath(value.iteration_path) &&
        (value.execution_id === undefined || validIdentity(value.execution_id)) &&
        (value.node_id === undefined || validIdentity(value.node_id)) &&
        (value.attempt === undefined || typeof value.attempt === 'number' && Number.isInteger(value.attempt) && value.attempt >= 0);
}

function pageParams(cursor: string | null, limit: number): URLSearchParams {
    const params = new URLSearchParams({ limit: String(boundedLimit(limit)) });
    if (cursor) {
        params.set('cursor', cursor);
    }
    return params;
}

function pageFromResponse<T>(
    response: unknown,
    key: 'executions' | 'attempts' | 'decisions' | 'items' | 'records' | 'contributors',
    isItem: (value: unknown) => value is T,
    identity?: (value: T) => string,
    limit = 100,
): WorkflowExecutionPage<T> {
    if (!isRecord(response)) {
        throw new Error('The workflow execution history returned an unsupported response.');
    }
    const items = response[key];
    if (!Array.isArray(items) || items.length > limit || !items.every(isItem) ||
        !(response.next_cursor === null || typeof response.next_cursor === 'string' && response.next_cursor.length > 0)) {
        throw new Error('The workflow execution history returned an unsupported response.');
    }
    if (identity && new Set(items.map(identity)).size !== items.length) {
        throw new Error('The workflow execution history contains conflicting identities.');
    }
    const total = response.total_count;
    if (total !== undefined && (typeof total !== 'number' || !Number.isInteger(total) || total < 0)) {
        throw new Error('The workflow execution history returned an invalid count.');
    }
    return {
        items,
        next_cursor: response.next_cursor,
        ...(typeof total === 'number' ? { total_count: total } : {}),
    };
}

export async function fetchWorkflowExecutionsPage(
    scope: WorkflowScope,
    workflowId: string,
    runId: string,
    cursor: string | null,
    limit = 50,
    signal?: AbortSignal,
): Promise<WorkflowExecutionPage<WorkflowExecutionRecord>> {
    const response = await api.get<unknown>(
        workflowUrl(scope, workflowId, `/runs/${encodeURIComponent(runId)}/executions`, pageParams(cursor, limit)),
        signal,
    );
    return pageFromResponse(response, 'executions', isExecution, (item) => item.execution_id, limit);
}

export async function fetchWorkflowExecutionAttemptsPage(
    scope: WorkflowScope,
    workflowId: string,
    runId: string,
    executionId: string,
    cursor: string | null,
    limit = 50,
    signal?: AbortSignal,
): Promise<WorkflowExecutionPage<WorkflowExecutionAttemptRecord>> {
    const response = await api.get<unknown>(
        workflowUrl(
            scope,
            workflowId,
            `/runs/${encodeURIComponent(runId)}/executions/${encodeURIComponent(executionId)}/attempts`,
            pageParams(cursor, limit),
        ),
        signal,
    );
    return pageFromResponse(response, 'attempts',
        (value): value is WorkflowExecutionAttemptRecord => isAttempt(value) && value.execution_id === executionId,
        (item) => `${item.execution_id}:${item.attempt}`, limit);
}

export async function fetchWorkflowExecutionAttemptResult(
    scope: WorkflowScope,
    workflowId: string,
    runId: string,
    executionId: string,
    attempt: number,
    offset: number,
    limit = 2000,
    signal?: AbortSignal,
): Promise<WorkflowRunResultPage> {
    const resultLimit = boundedLimit(limit, 2000);
    if (!validIdentity(executionId) || !Number.isInteger(attempt) || attempt < 1 || !Number.isInteger(offset) || offset < 0) {
        throw new Error('The requested execution attempt or result range is invalid.');
    }
    const params = new URLSearchParams({
        output: 'authoritative',
        offset: String(offset),
        limit: String(resultLimit),
    });
    return api.get<WorkflowRunResultPage>(
        workflowUrl(
            scope,
            workflowId,
            `/runs/${encodeURIComponent(runId)}/executions/${encodeURIComponent(executionId)}/attempts/${attempt}/result`,
            params,
        ),
        signal,
    );
}

export async function fetchWorkflowRuntimeDecisionsPage(
    scope: WorkflowScope,
    workflowId: string,
    runId: string,
    cursor: string | null,
    limit = 50,
    signal?: AbortSignal,
): Promise<WorkflowExecutionPage<WorkflowRuntimeDecisionRecord>> {
    const response = await api.get<unknown>(
        workflowUrl(scope, workflowId, `/runs/${encodeURIComponent(runId)}/runtime/decisions`, pageParams(cursor, limit)),
        signal,
    );
    return pageFromResponse(response, 'decisions', isDecision, undefined, limit);
}

export async function fetchWorkflowLoopItemsPage(
    scope: WorkflowScope,
    workflowId: string,
    runId: string,
    loopExecutionId: string,
    cursor: string | null,
    limit = 50,
    signal?: AbortSignal,
): Promise<WorkflowExecutionPage<WorkflowLoopItemRecord>> {
    boundedLimit(limit, 50);
    const response = await api.get<unknown>(workflowUrl(scope, workflowId,
        `/runs/${encodeURIComponent(runId)}/executions/${encodeURIComponent(loopExecutionId)}/items`,
        pageParams(cursor, limit)), signal);
    if (!isRecord(response) || response.loop_execution_id !== loopExecutionId ||
        !Number.isInteger(response.total_count) || Number(response.total_count) < 0 ||
        typeof response.limit !== 'number' || !Number.isInteger(response.limit) || response.limit < 1 || response.limit > 5000 ||
        response.frozen_at !== null && typeof response.frozen_at !== 'string') {
        throw new Error('The frozen loop items returned an unsupported response.');
    }
    const page = pageFromResponse(response, 'items', (value): value is WorkflowLoopItemRecord => {
        if (!isRecord(value) || !validIdentity(value.item_id) || typeof value.label !== 'string' ||
            !validIdentity(value.state) || typeof value.index !== 'number' || !Number.isSafeInteger(value.index) || value.index < 0 ||
            !validWorkflowIterationPath(value.iteration_path)) return false;
        const frame = value.iteration_path.at(-1);
        return frame?.item_id === value.item_id && frame.index === value.index &&
            (value.execution_ids === undefined || Array.isArray(value.execution_ids) && value.execution_ids.length <= 256 && value.execution_ids.every(validIdentity)) &&
            (value.record_count === undefined || typeof value.record_count === 'number' && Number.isSafeInteger(value.record_count) && value.record_count >= 0);
    }, (item) => item.item_id, limit);
    return { ...page, metadata: {
        frozenAt: typeof response.frozen_at === 'string' ? response.frozen_at : undefined,
        admittedLimit: response.limit,
        selection: workflowLoopSelection(response.selection),
    } };
}

export async function fetchWorkflowExecutionRecordsPage(
    scope: WorkflowScope,
    workflowId: string,
    runId: string,
    executionId: string,
    attempt: number,
    output: string,
    cursor: string | null,
    limit = 100,
    signal?: AbortSignal,
): Promise<WorkflowExecutionPage<unknown>> {
    if (!validIdentity(executionId) || !Number.isInteger(attempt) || attempt < 1 || !['records', 'documents'].includes(output)) {
        throw new Error('The requested execution collection is invalid.');
    }
    const params = pageParams(cursor, limit);
    params.set('output', output);
    const response = await api.get<unknown>(workflowUrl(scope, workflowId,
        `/runs/${encodeURIComponent(runId)}/executions/${encodeURIComponent(executionId)}/attempts/${attempt}/records`,
        params), signal);
    if (!isRecord(response) || response.output_name !== output ||
        !Number.isSafeInteger(response.total_count) || Number(response.total_count) < 0 ||
        !Number.isSafeInteger(response.record_offset) || Number(response.record_offset) < 0 ||
        response.workflow_validation !== undefined && !isRecord(response.workflow_validation) ||
        response.coverage !== undefined && !isRecord(response.coverage)) {
        throw new Error('The complete records returned an unsupported response.');
    }
    const page = pageFromResponse(response, 'records', (value): value is unknown => value !== undefined, undefined, limit);
    if (Number(response.record_offset) + page.items.length > Number(response.total_count)) {
        throw new Error('The complete records returned an invalid ordinal range.');
    }
    return { ...page, metadata: {
        recordOffset: Number(response.record_offset), outputName: output,
        validation: response.workflow_validation as WorkflowValidationResult | undefined,
        coverage: response.coverage as Record<string, unknown> | undefined,
    } };
}

export async function fetchWorkflowExecutionProvenancePage(
    scope: WorkflowScope,
    workflowId: string,
    runId: string,
    executionId: string,
    attempt: number,
    cursor: string | null,
    limit = 50,
    signal?: AbortSignal,
): Promise<WorkflowExecutionPage<WorkflowContributorRecord>> {
    boundedLimit(limit, 50);
    if (!validIdentity(executionId) || !Number.isInteger(attempt) || attempt < 1) {
        throw new Error('The requested contributor identity is invalid.');
    }
    const response = await api.get<unknown>(workflowUrl(scope, workflowId,
        `/runs/${encodeURIComponent(runId)}/executions/${encodeURIComponent(executionId)}/attempts/${attempt}/provenance`,
        pageParams(cursor, limit)), signal);
    if (!isRecord(response) || !Number.isSafeInteger(response.total_count) || Number(response.total_count) < 0) {
        throw new Error('The contributor page returned an invalid count.');
    }
    return pageFromResponse(response, 'contributors', (value): value is WorkflowContributorRecord =>
        isRecord(value) && isRecord(value.producer) && validIdentity(value.producer.node_id) &&
        validIdentity(value.producer.execution_id) && Number.isInteger(value.producer.attempt) &&
        Number(value.producer.attempt) >= 1 && validInputs([value]) &&
        (value.item_id === undefined || validIdentity(value.item_id)) &&
        ['item_index', 'record_offset', 'record_count', 'producer_record_offset'].every((key) =>
            value[key] === undefined || typeof value[key] === 'number' && Number.isSafeInteger(value[key]) && Number(value[key]) >= 0),
    undefined, limit);
}
