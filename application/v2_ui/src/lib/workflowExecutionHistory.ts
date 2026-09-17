// workflowExecutionHistory.ts
// Paged V3 workflow execution-history API contracts and client helpers.

import { api } from './apiClient';
import { isRecord } from './workspaceAuthoring';
import {
    workflowUrl,
    type WorkflowConsumedInput,
    type WorkflowIterationFrame,
    type WorkflowResultReference,
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
    started_at?: string;
    completed_at?: string;
    workflow_result?: {
        result_ref?: WorkflowResultReference;
        outputs?: Record<string, unknown>;
        authoritative_output?: string;
        consumed_inputs?: WorkflowConsumedInput[];
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
    return value === undefined || Array.isArray(value) && value.every((frame) =>
        isRecord(frame) && validIdentity(frame.loop_id) &&
        (frame.item_id === undefined || validIdentity(frame.item_id)) &&
        (frame.index === undefined || typeof frame.index === 'number' && Number.isInteger(frame.index) && frame.index >= 0) &&
        (frame.iteration === undefined || typeof frame.iteration === 'number' && Number.isInteger(frame.iteration) && frame.iteration >= 1));
}

function validInputs(value: unknown): boolean {
    return value === undefined || Array.isArray(value) && value.every((input) =>
        isRecord(input) && (input.producer === undefined || isRecord(input.producer) && validPath(input.producer.iteration_path)));
}

function validResultMetadata(value: Record<string, unknown>): boolean {
    return validInputs(value.consumed_inputs) &&
        (value.workflow_result === undefined || isRecord(value.workflow_result) && validInputs(value.workflow_result.consumed_inputs)) &&
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
        Number.isInteger(value.attempt) && value.attempt >= 1 && validResultMetadata(value);
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
    key: 'executions' | 'attempts' | 'decisions',
    isItem: (value: unknown) => value is T,
    identity?: (value: T) => string,
): WorkflowExecutionPage<T> {
    if (!isRecord(response)) {
        throw new Error('The workflow execution history returned an unsupported response.');
    }
    const items = response[key];
    if (!Array.isArray(items) || !items.every(isItem) ||
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
    return pageFromResponse(response, 'executions', isExecution, (item) => item.execution_id);
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
        (item) => `${item.execution_id}:${item.attempt}`);
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
    return pageFromResponse(response, 'decisions', isDecision);
}
