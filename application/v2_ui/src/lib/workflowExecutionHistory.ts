// workflowExecutionHistory.ts
// Paged V3 workflow execution-history API contracts and client helpers.

import { api } from './apiClient';
import { isRecord } from './workspaceAuthoring';
import {
    workflowUrl,
    workflowLoopSelection,
    validWorkflowIterationPath,
    isWorkflowPublicationStatus,
    isWorkflowRepeatProgress,
    type WorkflowConsumedInput,
    type WorkflowIterationFrame,
    type WorkflowLoopSelection,
    type WorkflowResultReference,
    type WorkflowPublicationStatus,
    type WorkflowRepeatProgress,
    type WorkflowRunResultPage,
    type WorkflowScope,
    type WorkflowValidationResult,
} from './workflowEditor';
import { DEFAULT_FLOW_LIMITS, FLOW_ALIAS_PATTERN, MAX_REPEAT_ITERATIONS, REPEAT_STATE_KINDS, type WorkflowRepeatStateKind } from './workflowFlow';

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
    actor_user_id?: string;
    request_id?: string;
    event_id?: string;
    repeat?: WorkflowRepeatProgress;
    iteration?: number;
    batch_number?: number;
    batch_size?: number;
    batch_usage?: number;
    condition_result?: boolean;
    outcome?: string;
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
    node_kind?: string;
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

export interface WorkflowRuntimeDecisionRecord extends WorkflowExecutionDecisionPreview {
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
        repeat?: WorkflowRepeatProgress;
        stateAvailable?: boolean;
        partial?: boolean;
        sourceSnapshotChanged?: boolean;
    };
}

export interface WorkflowRepeatIterationRecord {
    iteration: number;
    iteration_path: WorkflowIterationFrame[];
    batch_number: number;
    batch_size: number;
    batch_usage: number;
    state: 'running' | 'completed' | 'completed_partial' | 'cancelled';
    condition_result: boolean | null;
    execution_ids: string[];
    before_available: true;
    after_available: boolean;
    partial: boolean;
}

export interface WorkflowRepeatStateRecord {
    name: string;
    kind: WorkflowRepeatStateKind;
    source: {
        node_id: string;
        execution_id: string;
        task_id?: string;
        iteration_path: WorkflowIterationFrame[];
        attempt: number;
        output_name: string;
    };
    workflow_validation: WorkflowValidationResult;
    coverage: Record<string, string | number | boolean | null>;
    prior_coverage?: Record<string, string | number | boolean | null>;
    limitations: string[];
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
        (value.node_kind === undefined || validIdentity(value.node_kind)) &&
        validIdentity(value.state) && typeof value.attempt === 'number' &&
        Number.isInteger(value.attempt) && value.attempt >= 1 && validPath(value.iteration_path) && validResultMetadata(value);
}

function isDecision(value: unknown): value is WorkflowRuntimeDecisionRecord {
    return isRecord(value) && validPath(value.iteration_path) &&
        (value.execution_id === undefined || validIdentity(value.execution_id)) &&
        (value.node_id === undefined || validIdentity(value.node_id)) &&
        (value.attempt === undefined || typeof value.attempt === 'number' && Number.isInteger(value.attempt) && value.attempt >= 0) &&
        (value.repeat === undefined || isWorkflowRepeatProgress(value.repeat)) &&
        (value.condition_result === undefined || typeof value.condition_result === 'boolean') &&
        ['iteration', 'batch_number', 'batch_size', 'batch_usage'].every((key) =>
            value[key] === undefined || typeof value[key] === 'number' && Number.isSafeInteger(value[key]) &&
            Number(value[key]) >= 0 && Number(value[key]) <= DEFAULT_FLOW_LIMITS.max_executions);
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
    key: 'executions' | 'attempts' | 'decisions' | 'items' | 'records' | 'contributors' | 'iterations' | 'states',
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
    output = 'authoritative',
): Promise<WorkflowRunResultPage> {
    const resultLimit = boundedLimit(limit, 2000);
    if (!validIdentity(executionId) || !Number.isInteger(attempt) || attempt < 1 ||
        !Number.isInteger(offset) || offset < 0 || !FLOW_ALIAS_PATTERN.test(output)) {
        throw new Error('The requested execution attempt or result range is invalid.');
    }
    const params = new URLSearchParams({
        output,
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
        return frame !== undefined && 'item_id' in frame && frame.item_id === value.item_id && frame.index === value.index &&
            (value.execution_ids === undefined || Array.isArray(value.execution_ids) && value.execution_ids.length <= 256 && value.execution_ids.every(validIdentity)) &&
            (value.record_count === undefined || typeof value.record_count === 'number' && Number.isSafeInteger(value.record_count) && value.record_count >= 0);
    }, (item) => item.item_id, limit);
    return { ...page, metadata: {
        frozenAt: typeof response.frozen_at === 'string' ? response.frozen_at : undefined,
        admittedLimit: response.limit,
        selection: workflowLoopSelection(response.selection),
    } };
}

export async function fetchWorkflowRepeatIterationsPage(
    scope: WorkflowScope,
    workflowId: string,
    runId: string,
    executionId: string,
    cursor: string | null,
    limit = 50,
    signal?: AbortSignal,
): Promise<WorkflowExecutionPage<WorkflowRepeatIterationRecord>> {
    const response = await api.get<unknown>(workflowUrl(scope, workflowId,
        `/runs/${encodeURIComponent(runId)}/executions/${encodeURIComponent(executionId)}/iterations`,
        pageParams(cursor, limit)), signal);
    if (!isRecord(response) || response.repeat_execution_id !== executionId ||
        !isWorkflowRepeatProgress(response.repeat) || response.repeat.execution_id !== executionId ||
        !Number.isSafeInteger(response.total_count) || Number(response.total_count) < 0 ||
        Number(response.total_count) > DEFAULT_FLOW_LIMITS.max_executions ||
        typeof response.source_snapshot_changed !== 'boolean') {
        throw new Error('The Repeat rounds returned an unsupported response.');
    }
    const repeat = response.repeat;
    const page = pageFromResponse(response, 'iterations', (value): value is WorkflowRepeatIterationRecord => {
        if (!isRecord(value) || Object.keys(value).some((key) => ![
            'iteration', 'iteration_path', 'batch_number', 'batch_size', 'batch_usage', 'state', 'condition_result',
            'execution_ids', 'before_available', 'after_available', 'partial',
        ].includes(key)) || !validWorkflowIterationPath(value.iteration_path) ||
            typeof value.state !== 'string' || !['running', 'completed', 'completed_partial', 'cancelled'].includes(value.state) ||
            typeof value.partial !== 'boolean' || value.before_available !== true ||
            typeof value.after_available !== 'boolean' ||
            value.condition_result !== null && typeof value.condition_result !== 'boolean' ||
            !value.after_available && value.condition_result !== null ||
            !Array.isArray(value.execution_ids) || value.execution_ids.length > 256 || !value.execution_ids.every(validIdentity) ||
            ['iteration', 'batch_number', 'batch_size', 'batch_usage'].some((key) =>
                typeof value[key] !== 'number' || !Number.isSafeInteger(value[key]) || Number(value[key]) < 0)) return false;
        const frame = value.iteration_path.at(-1);
        return frame !== undefined && 'iteration' in frame && frame.iteration === value.iteration && frame.loop_id === repeat.node_id &&
            value.batch_size === repeat.batch_size && Number(value.batch_size) <= MAX_REPEAT_ITERATIONS &&
            Number(value.batch_usage) >= 1 && Number(value.batch_usage) <= Number(value.batch_size) &&
            Number(value.batch_number) * Number(value.batch_size) + Number(value.batch_usage) - 1 === value.iteration;
    }, (item) => String(item.iteration), limit);
    if (page.items.some((item, index) => item.iteration >= Number(response.total_count) ||
        index > 0 && item.iteration <= page.items[index - 1].iteration)) {
        throw new Error('The Repeat round page contains conflicting lifetime identities.');
    }
    return { ...page, metadata: { repeat, sourceSnapshotChanged: response.source_snapshot_changed === true } };
}

function isRepeatValidation(value: unknown): value is WorkflowValidationResult {
    return isRecord(value) && value.version === 1 &&
        ['valid', 'invalid', 'incomplete', 'accepted_partial', 'not_requested'].includes(String(value.status)) &&
        (value.eligible === undefined || typeof value.eligible === 'boolean') &&
        (value.reason_codes === undefined || Array.isArray(value.reason_codes) && value.reason_codes.length <= 100 &&
            value.reason_codes.every((code) => typeof code === 'string' && code.length <= 256)) &&
        (value.counts === undefined || isRecord(value.counts) && Object.values(value.counts).every((count) =>
            typeof count === 'number' && Number.isFinite(count) && count >= 0));
}

function isRepeatCoverage(value: unknown): value is WorkflowRepeatStateRecord['coverage'] {
    return isRecord(value) && Object.values(value).every((item) =>
        item === null || typeof item === 'string' || typeof item === 'boolean' ||
        typeof item === 'number' && Number.isFinite(item));
}

function isRepeatStateRecord(value: unknown): value is WorkflowRepeatStateRecord {
    if (!isRecord(value) || Object.keys(value).some((key) =>
        !['name', 'kind', 'source', 'workflow_validation', 'coverage', 'prior_coverage', 'limitations'].includes(key)) ||
        typeof value.name !== 'string' || !FLOW_ALIAS_PATTERN.test(value.name) ||
        !REPEAT_STATE_KINDS.some((kind) => kind === value.kind) || !isRecord(value.source) ||
        !isRepeatValidation(value.workflow_validation) || !isRepeatCoverage(value.coverage) ||
        value.prior_coverage !== undefined && !isRepeatCoverage(value.prior_coverage) ||
        !Array.isArray(value.limitations) || !value.limitations.every((item) => typeof item === 'string')) return false;
    const source = value.source;
    return Object.keys(source).every((key) => ['node_id', 'execution_id', 'task_id', 'iteration_path', 'attempt', 'output_name'].includes(key)) &&
        validIdentity(source.node_id) && validIdentity(source.execution_id) &&
        (source.task_id === undefined || validIdentity(source.task_id)) &&
        typeof source.attempt === 'number' && Number.isSafeInteger(source.attempt) && source.attempt >= 1 &&
        validWorkflowIterationPath(source.iteration_path) &&
        typeof source.output_name === 'string' && FLOW_ALIAS_PATTERN.test(source.output_name);
}

export async function fetchWorkflowRepeatStatePage(
    scope: WorkflowScope,
    workflowId: string,
    runId: string,
    executionId: string,
    iteration: number,
    phase: 'before' | 'after',
    cursor: string | null,
    limit = 50,
    signal?: AbortSignal,
): Promise<WorkflowExecutionPage<WorkflowRepeatStateRecord>> {
    if (!Number.isSafeInteger(iteration) || iteration < 0 || iteration >= DEFAULT_FLOW_LIMITS.max_executions ||
        !['before', 'after'].includes(phase)) {
        throw new Error('Select an exact admitted Repeat round and before or after state.');
    }
    const params = pageParams(cursor, limit);
    params.set('phase', phase);
    const response = await api.get<unknown>(workflowUrl(scope, workflowId,
        `/runs/${encodeURIComponent(runId)}/executions/${encodeURIComponent(executionId)}/iterations/${iteration}/state`, params), signal);
    if (!isRecord(response) || response.repeat_execution_id !== executionId || response.iteration !== iteration ||
        response.phase !== phase || typeof response.available !== 'boolean' ||
        !Number.isSafeInteger(response.total_count) || Number(response.total_count) < 0 || Number(response.total_count) > 100 ||
        response.available && (typeof response.partial !== 'boolean' || typeof response.source_snapshot_changed !== 'boolean') ||
        !response.available && (phase !== 'after' || response.partial !== undefined || response.source_snapshot_changed !== undefined)) {
        throw new Error('The Repeat state returned an unsupported response.');
    }
    const page = pageFromResponse(response, 'states', isRepeatStateRecord, (item) => item.name, limit);
    if (!response.available && (page.items.length || response.total_count !== 0 || page.next_cursor !== null) ||
        response.available && (Number(response.total_count) < 1 || page.items.length > Number(response.total_count))) {
        throw new Error('The Repeat state page has an invalid availability or count.');
    }
    return { ...page, metadata: {
        stateAvailable: response.available, partial: response.partial === true,
        sourceSnapshotChanged: response.source_snapshot_changed === true,
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
    if (!validIdentity(executionId) || !Number.isInteger(attempt) || attempt < 1 || !FLOW_ALIAS_PATTERN.test(output)) {
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
