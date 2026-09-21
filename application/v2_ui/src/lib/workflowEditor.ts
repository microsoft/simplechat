// workflowEditor.ts
// Native V2 workflow editor contracts and safe client-side normalization.

import { api, ApiError } from './apiClient';
import {
    buildDocumentListParams,
    DEFAULT_DOCUMENT_QUERY,
} from './documentExplorer';
import type { DocumentListResponse, DocumentQuery, WorkspaceDocument } from './types';
import { isRecord, sameEditorValue } from './workspaceAuthoring';
import {
    analyzeWorkflowFlow,
    DEFAULT_FLOW_LIMITS,
    enclosingFlowLoopControls,
    flowLoops,
    flowRepeats,
    flowSourceOutput,
    flowTaskNodeId,
    flowUnsupportedReason,
    FLOW_ALIAS_PATTERN,
    FLOW_MAX_DEPTH,
    MAX_LOOP_ITEMS,
    MAX_REPEAT_ITERATIONS,
    isFlowBinding,
    isFlowRegion,
    isLegacyWorkflowBinding,
    loopSelectionErrors,
    repeatIterationErrors,
    workflowLoopLimit,
    workflowRepeatLimit,
    type WorkflowFlowBinding,
    type WorkflowLoopIterable,
} from './workflowFlow';

export type WorkflowScope = { type: 'personal' } | { type: 'group'; groupId: string };
export type WorkflowRunnerType = 'model' | 'agent';
export type WorkflowTriggerType = 'manual' | 'interval' | 'file_sync';
export type WorkflowOutputKind = 'any' | 'text' | 'records' | 'json' | 'document_results';
export type WorkflowTaskRunnerType = 'inherit' | 'agent' | 'model';
export type WorkflowInputProcessing = 'full' | 'saved_record_report';
export type WorkflowInputOutput = WorkflowOutputKind | 'authoritative' | 'documents';
export type WorkflowReferenceScope = 'personal' | 'group' | 'public';
export type WorkflowDocumentActionType = 'none' | 'search' | 'analyze' | 'comparison';
export type WorkflowRuntimeState =
    'queued' | 'running' | 'waiting_approval' | 'waiting_output' | 'waiting_recovery' |
    'awaiting_approval' | 'awaiting_sharing_approval' | 'awaiting_analysis_approval' |
    'awaiting_run_as_approval' | 'awaiting_sign_in' |
    'paused' | 'cancelling' | 'cancelled' | 'failed' | 'invalid' | 'incomplete' |
    'completed' | 'completed_partial' | 'skipped';
export type WorkflowRuntimeGateKind = 'approval' | 'output' | 'recovery' | 'pause';
export type WorkflowRuntimeDecisionChoice = 'approve' | 'reject' | 'retry' | 'cancel' | 'resume' | 'continue_repeat';

export interface WorkflowAgentOption {
    id: string;
    name: string;
    display_name?: string;
    is_global?: boolean;
    is_group?: boolean;
    group_id?: string;
    loop_eligible?: boolean;
}

export type WorkflowAgentReference = WorkflowAgentOption;

export interface WorkflowModelOption {
    endpoint_id: string;
    model_id: string;
    label: string;
    provider: string;
    loop_eligible?: boolean;
}

export interface WorkflowEditorOptions {
    definition_version: 2;
    supported_definition_versions?: number[];
    supported_node_kinds?: string[];
    supported_iterable_kinds?: string[];
    supported_query_modes?: string[];
    supported_binding_sources?: string[];
    supported_input_processing_modes?: string[];
    supported_publication_completion_policies?: string[];
    publication_source_capabilities?: WorkflowPublicationSourceCapability[];
    flow_limits?: {
        max_nodes: number;
        max_depth: number;
        max_predicate_nodes: number;
        max_predicate_depth: number;
        max_executions: number;
        deadline_seconds: number;
        max_loop_items?: number;
        max_repeat_iterations?: number;
        hard_repeat_iterations?: number;
    };
    can_manage: boolean;
    max_tasks: number;
    agents: WorkflowAgentOption[];
    models: WorkflowModelOption[];
    default_model?: {
        label?: string;
        valid?: boolean;
        loop_eligible?: boolean;
    };
    scope: { type: 'personal' | 'group'; id?: string };
}

export interface WorkflowSchedule {
    unit: 'seconds' | 'minutes' | 'hours';
    value: number;
}

export interface WorkflowInputBinding {
    name: string;
    task_id: string;
    output: WorkflowInputOutput;
    required: boolean;
    expected_kind: WorkflowOutputKind;
}

export interface WorkflowOutputContract {
    kind: WorkflowOutputKind;
    schema?: Record<string, unknown>;
    expected_count?: number;
    identity_field?: string;
    require_complete_coverage: boolean;
    allow_partial: boolean;
}

export interface WorkflowTaskRunner {
    type: WorkflowTaskRunnerType;
    selected_agent?: WorkflowAgentReference;
    model_endpoint_id?: string;
    model_id?: string;
}

export interface WorkflowTaskApproval {
    required: boolean;
    message?: string;
}

export type WorkflowPublicationSourceKind = 'native_analysis' | 'saved_output';

export interface WorkflowPublicationSourceCapability {
    source_kind: string;
    output_kinds: string[];
    artifact_formats: string[];
}

export interface WorkflowPublication {
    source_kind?: WorkflowPublicationSourceKind;
    artifact_format: 'md' | 'csv' | 'json';
    workspace_scope: 'personal' | 'group' | 'public';
    group_id?: string;
    public_workspace_id?: string;
    completion_policy?: WorkflowPublicationCompletionPolicy;
}

export function isWorkflowPublicationSourceKind(value: unknown): value is WorkflowPublicationSourceKind {
    return value === 'native_analysis' || value === 'saved_output';
}

export function savedOutputPublicationFormats(options: WorkflowEditorOptions): 'json'[] {
    const capability = options.publication_source_capabilities?.find((item) => item.source_kind === 'saved_output');
    return capability?.output_kinds.includes('records')
        ? [...new Set(capability.artifact_formats.filter((format): format is 'json' => format === 'json'))]
        : [];
}

export const WORKFLOW_PUBLICATION_COMPLETION_LABELS = {
    submitted: 'Submitted',
    approved: 'Approved',
    indexed_ready: 'Indexed and ready',
} as const;

export type WorkflowPublicationCompletionPolicy = keyof typeof WORKFLOW_PUBLICATION_COMPLETION_LABELS;

export function isWorkflowPublicationCompletionPolicy(value: unknown): value is WorkflowPublicationCompletionPolicy {
    return typeof value === 'string' && Object.hasOwn(WORKFLOW_PUBLICATION_COMPLETION_LABELS, value);
}

const PUBLICATION_FACT_VALUES = {
    state: [
        'submitted', 'approved', 'indexed_ready', 'waiting_approval', 'waiting_processing',
        'waiting_screening', 'waiting_index', 'uncertain', 'rejected', 'cancelled',
        'approval_failed', 'processing_failed', 'unavailable', 'content_changed',
    ],
    submission: ['pending', 'confirmed', 'uncertain'],
    approval: ['not_required', 'pending', 'approved', 'rejected', 'cancelled', 'failed'],
    processing: ['not_started', 'queued', 'running', 'complete', 'failed', 'unavailable'],
    screening: ['not_required', 'pending', 'held', 'available', 'rejected', 'changed', 'unavailable'],
    index: ['pending', 'ready', 'unavailable'],
} as const;

export interface WorkflowPublicationStatus {
    version: 1;
    id: string;
    document_id: string;
    document_version: number | null;
    destination: {
        workspace_scope: WorkflowReferenceScope;
        group_id?: string;
        public_workspace_id?: string;
    };
    completion_policy: WorkflowPublicationCompletionPolicy;
    policy_satisfied: boolean;
    state: typeof PUBLICATION_FACT_VALUES.state[number];
    submission: typeof PUBLICATION_FACT_VALUES.submission[number];
    approval: typeof PUBLICATION_FACT_VALUES.approval[number];
    processing: typeof PUBLICATION_FACT_VALUES.processing[number];
    screening: typeof PUBLICATION_FACT_VALUES.screening[number];
    index: typeof PUBLICATION_FACT_VALUES.index[number];
    reason_code: string;
    retryable: boolean;
    unresolved_stages: string[];
}

export function isWorkflowPublicationStatus(value: unknown): value is WorkflowPublicationStatus {
    const identity = (item: unknown): item is string =>
        typeof item === 'string' && item.length > 0 && item.length <= 256 && item === item.trim();
    const code = (item: unknown): item is string =>
        typeof item === 'string' && /^[a-z][a-z0-9_]{0,127}$/.test(item);
    if (!isRecord(value) || value.version !== 1 ||
        Object.keys(value).some((key) => ![
            'version', 'id', 'document_id', 'document_version', 'destination', 'completion_policy',
            'policy_satisfied', 'state', 'submission', 'approval', 'processing', 'screening',
            'index', 'reason_code', 'retryable', 'unresolved_stages',
        ].includes(key)) ||
        typeof value.id !== 'string' || !/^[a-f0-9]{64}$/.test(value.id) ||
        !identity(value.document_id) ||
        value.document_version !== null && (typeof value.document_version !== 'number' ||
            !Number.isSafeInteger(value.document_version) || value.document_version < 1) ||
        !isWorkflowPublicationCompletionPolicy(value.completion_policy) ||
        typeof value.policy_satisfied !== 'boolean' || typeof value.retryable !== 'boolean' ||
        value.reason_code !== '' && !code(value.reason_code) ||
        !Array.isArray(value.unresolved_stages) || value.unresolved_stages.length > 32 ||
        !value.unresolved_stages.every(code) ||
        Object.entries(PUBLICATION_FACT_VALUES).some(([key, allowed]) => {
            const fact = value[key];
            return typeof fact !== 'string' || !(allowed as readonly string[]).includes(fact);
        }) ||
        !isRecord(value.destination)) return false;
    const destination = value.destination;
    const scope = destination.workspace_scope;
    return (scope === 'personal' || scope === 'group' || scope === 'public') &&
        Object.keys(destination).every((key) =>
            key === 'workspace_scope' || scope === 'group' && key === 'group_id' ||
            scope === 'public' && key === 'public_workspace_id') &&
        (scope !== 'group' || identity(destination.group_id)) &&
        (scope !== 'public' || identity(destination.public_workspace_id));
}

export interface WorkflowTask {
    id: string;
    type: 'instructions';
    name: string;
    instructions: string;
    order: number;
    runner: WorkflowTaskRunner;
    document_action?: WorkflowDocumentAction;
    inputs?: (WorkflowInputBinding | WorkflowFlowBinding)[];
    input_processing?: WorkflowInputProcessing;
    reference_ids?: string[];
    output_contract?: WorkflowOutputContract;
    approval?: WorkflowTaskApproval;
    publication?: WorkflowPublication;
    [key: string]: unknown;
}

export interface WorkflowDocumentAction {
    type: WorkflowDocumentActionType;
    doc_scope?: WorkflowReferenceScope | 'all';
    active_group_ids?: string[];
    active_public_workspace_id?: string[];
    document_ids?: string[];
    target_mode?: 'selected' | 'current_item';
    loop_id?: string;
    analysis_mode?: 'combined' | 'per_document';
    left_document_id?: string;
    right_document_ids?: string[];
    [key: string]: unknown;
}

export interface WorkflowReferenceInput {
    id: string;
    name: string;
    document_id: string;
    scope_type: WorkflowReferenceScope;
    scope_id: string;
}

export interface WorkflowDefinition {
    id?: string;
    definition_version: number;
    definition_revision?: string;
    name: string;
    description: string;
    runner_type: WorkflowRunnerType;
    selected_agent?: WorkflowAgentReference;
    model_endpoint_id?: string;
    model_id?: string;
    m365_run_as_user_id?: string;
    chat_capabilities_enabled: boolean;
    trigger_type: WorkflowTriggerType;
    schedule: WorkflowSchedule;
    is_enabled: boolean;
    error_handling: {
        strategy: 'halt' | 'continue';
        retry_count: number;
    };
    tasks: WorkflowTask[];
    reference_inputs: WorkflowReferenceInput[];
    durable_execution?: boolean;
    editor_readonly_reason?: string;
    [key: string]: unknown;
}

export interface WorkflowRuntimeGate {
    id: string;
    kind: WorkflowRuntimeGateKind;
    unit_id?: string;
    input_digest?: string;
    reason?: string;
    reason_code?: string;
    choices: string[];
    execution_id?: string;
    node_id?: string;
    attempt?: number;
    iteration_path?: WorkflowIterationFrame[];
    publication?: WorkflowPublicationStatus;
    repeat?: WorkflowRepeatProgress;
}

export interface WorkflowForEachFrame {
    loop_id: string;
    item_id: string;
    index: number;
}

export interface WorkflowRepeatFrame {
    loop_id: string;
    iteration: number;
}

export type WorkflowIterationFrame = WorkflowForEachFrame | WorkflowRepeatFrame;

export function validWorkflowIterationPath(value: unknown): value is WorkflowIterationFrame[] {
    return Array.isArray(value) && value.length < FLOW_MAX_DEPTH && value.every((frame) =>
        isRecord(frame) &&
        typeof frame.loop_id === 'string' && frame.loop_id === frame.loop_id.trim() &&
        /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(frame.loop_id) &&
        ('iteration' in frame
            ? Object.keys(frame).length === 2 && typeof frame.iteration === 'number' &&
                Number.isSafeInteger(frame.iteration) && frame.iteration >= 0 && frame.iteration < DEFAULT_FLOW_LIMITS.max_executions
            : Object.keys(frame).every((key) => ['loop_id', 'item_id', 'index'].includes(key)) &&
                typeof frame.item_id === 'string' && /^[a-f0-9]{64}$/.test(frame.item_id) &&
                typeof frame.index === 'number' && Number.isSafeInteger(frame.index) && frame.index >= 0 && frame.index < MAX_LOOP_ITEMS)) &&
        new Set(value.map((frame) => frame.loop_id)).size === value.length;
}

export function formatWorkflowIterationPath(path?: WorkflowIterationFrame[]): string {
    return (path ?? []).map((frame) => 'iteration' in frame
        ? `${frame.loop_id} (round ${frame.iteration + 1})`
        : `${frame.loop_id} (item ${frame.item_id}, index ${frame.index})`).join(' / ');
}

export interface WorkflowRepeatProgress {
    execution_id: string;
    node_id: string;
    completed_iteration: number;
    next_iteration: number;
    batch_number: number;
    batch_size: number;
    batch_usage: number;
    completed_count: number;
    exhaustion_count: number;
    continuation_count: number;
    state: 'running' | 'waiting_manual_continue' | 'completed' | 'cancelled';
    partial: boolean;
}

export function isWorkflowRepeatProgress(value: unknown): value is WorkflowRepeatProgress {
    const counts = ['next_iteration', 'batch_number', 'batch_size', 'batch_usage', 'completed_count',
        'exhaustion_count', 'continuation_count'];
    if (!isRecord(value) || Object.keys(value).some((key) => ![
        'execution_id', 'node_id', 'completed_iteration', 'state', 'partial', ...counts,
    ].includes(key)) || typeof value.execution_id !== 'string' || !value.execution_id.trim() || value.execution_id.length > 256 ||
        typeof value.node_id !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value.node_id) ||
        !['running', 'waiting_manual_continue', 'completed', 'cancelled'].includes(String(value.state)) ||
        typeof value.partial !== 'boolean' || counts.some((key) =>
            typeof value[key] !== 'number' || !Number.isSafeInteger(value[key]) || Number(value[key]) < 0 ||
            Number(value[key]) > DEFAULT_FLOW_LIMITS.max_executions) ||
        typeof value.completed_iteration !== 'number' || !Number.isSafeInteger(value.completed_iteration)) return false;
    const admittedRounds = Number(value.batch_number) * Number(value.batch_size) + Number(value.batch_usage);
    const completedRounds = Number(value.completed_count);
    return Number(value.batch_size) >= 1 && Number(value.batch_size) <= MAX_REPEAT_ITERATIONS &&
        Number(value.batch_usage) <= Number(value.batch_size) &&
        admittedRounds >= completedRounds && admittedRounds <= completedRounds + 1 &&
        (!['completed', 'waiting_manual_continue'].includes(String(value.state)) || admittedRounds === completedRounds) &&
        value.next_iteration === value.completed_count && value.completed_iteration === Number(value.completed_count) - 1 &&
        value.batch_number === value.continuation_count &&
        (value.state !== 'waiting_manual_continue' || value.batch_usage === value.batch_size && Number(value.completed_count) > 0);
}

export interface WorkflowLoopProgress {
    loop_id: string;
    loop_execution_id: string;
    total: number;
    current_index: number | null;
    completed: number;
    completed_empty?: number;
    skipped: number;
    failed: number;
    pending: number;
    limit: number;
}

export interface WorkflowRuntimeDecision {
    unit_id: string;
    choice: string;
    actor_user_id: string;
    decided_at?: string;
    input_digest?: string;
    attempt?: number;
    execution_id?: string;
    node_id?: string;
    iteration_path?: WorkflowIterationFrame[];
}

export interface WorkflowRuntimeUnitMemory {
    unit_id: string;
    state: string;
    attempt: number;
    replay_safe?: boolean;
    output_available?: boolean;
}

export interface WorkflowRuntimeMemory {
    decisions?: WorkflowRuntimeDecision[];
    units?: WorkflowRuntimeUnitMemory[];
    [key: string]: unknown;
}

export interface WorkflowRuntimeProjection {
    schema_version?: number;
    version: number;
    state: WorkflowRuntimeState;
    phase?: string;
    progress?: {
        completed: number;
        total: number;
    };
    gate?: WorkflowRuntimeGate;
    memory?: WorkflowRuntimeMemory;
    can_resume?: boolean;
    loop_progress?: WorkflowLoopProgress;
    repeat_progress?: WorkflowRepeatProgress;
    repeat_counts?: { exhaustion_count?: number; continuation_count?: number };
    limits?: {
        max_executions: number;
        admitted_count: number;
        deadline_at: string;
        deadline_seconds: number;
        waits_count: boolean;
        max_loop_items?: number;
        max_repeat_iterations?: number;
    };
}

export interface WorkflowRuntimeResponse {
    runtime: WorkflowRuntimeProjection;
    can_decide: boolean;
}

export interface WorkflowRuntimeDecisionRequest {
    expected_version: number;
    gate_id: string;
    choice: WorkflowRuntimeDecisionChoice;
    request_id: string;
}

export interface WorkflowRuntimeResumeRequest {
    expected_version: number;
    request_id: string;
}

export interface WorkflowRunSummary {
    id?: string;
    run_id?: string;
    workflow_id?: string;
    definition_version?: number;
    status?: string;
    durable_execution?: boolean;
    started_at?: string;
    completed_at?: string;
    workflow_validation?: WorkflowValidationResult;
    [key: string]: unknown;
}

export interface WorkflowRunStartResponse {
    success?: boolean;
    run?: WorkflowRunSummary;
    workflow?: WorkflowDefinition;
    runtime?: WorkflowRuntimeProjection;
    id?: string;
    workflow_id?: string;
    status?: string;
    durable_execution?: boolean;
}

export interface WorkflowRunItem {
    id?: string;
    item_type?: string;
    task_id?: string;
    label?: string;
    task_name?: string;
    status?: string;
    workflow_validation?: WorkflowValidationResult;
    workflow_result?: {
        result_ref?: WorkflowResultReference;
        outputs?: Record<string, unknown>;
        authoritative_output?: string;
        consumed_inputs?: WorkflowConsumedInput[];
    };
    consumed_inputs?: WorkflowConsumedInput[];
    context_budget?: Record<string, unknown>;
    started_at?: string;
    completed_at?: string;
    [key: string]: unknown;
}

export interface WorkflowResultReference {
    storage?: string;
    schema_version?: number;
    sha256?: string;
    size_bytes?: number;
    chunk_count?: number;
}

export interface WorkflowConsumedInput {
    producer?: {
        workflow_id?: string;
        node_id?: string;
        execution_id?: string;
        iteration_path?: WorkflowIterationFrame[];
        task_id?: string;
        run_id?: string;
        attempt?: number;
    };
    output_name?: string;
    result_ref?: WorkflowResultReference;
    output_ref?: WorkflowResultReference | string;
    input_name?: string;
}

export interface WorkflowValidationResult {
    version: 1;
    status: 'valid' | 'invalid' | 'incomplete' | 'accepted_partial' | 'not_requested';
    eligible?: boolean;
    reason_codes?: string[];
    counts?: Record<string, number>;
}

export interface WorkflowRunResultPage {
    content: string;
    output_name?: string;
    offset?: number;
    next_offset?: number | null;
    total_bytes?: number;
    complete?: boolean;
    sha256?: string;
    integrity?: {
        full_sha256_verified: boolean;
        chunk_sha256_verified: boolean;
        page_sha256: string;
    };
    [key: string]: unknown;
}

export const WORKFLOW_TASK_INSTRUCTIONS_LIMIT = 12000;
export const WORKFLOW_SCHEMA_LIMIT = 32768;
export const WORKFLOW_ALIAS_PATTERN = FLOW_ALIAS_PATTERN;
export const WORKFLOW_SCHEMA_ALLOWED_KEYS = new Set([
    'type',
    'properties',
    'required',
    'additionalProperties',
    'items',
    'minItems',
    'maxItems',
    'minLength',
    'maxLength',
    'minimum',
    'maximum',
    'enum',
    'title',
    'description',
]);
export const WORKFLOW_COUNT_KINDS = new Set<WorkflowOutputKind>(['records', 'json', 'document_results']);
export const DEFAULT_WORKFLOW_SCOPE: WorkflowScope = { type: 'personal' };
export const WORKFLOW_OUTPUT_KINDS: WorkflowOutputKind[] = [
    'any',
    'text',
    'records',
    'json',
    'document_results',
];
export const WORKFLOW_INPUT_OUTPUTS: WorkflowInputOutput[] = [
    'authoritative',
    'text',
    'records',
    'json',
    'documents',
];
export const WORKFLOW_APPROVAL_MESSAGE_LIMIT = 1000;
export const WORKFLOW_RUNTIME_TERMINAL_STATES = new Set<WorkflowRuntimeState>([
    'cancelled',
    'failed',
    'invalid',
    'incomplete',
    'completed',
    'completed_partial',
    'skipped',
]);

export function workflowRuntimeGateAllowsDecision(
    gate: WorkflowRuntimeGate | undefined,
    choice: WorkflowRuntimeDecisionChoice,
): boolean {
    return Boolean(gate?.choices.includes(choice) &&
        (gate.reason_code !== 'm365_authorization' || choice === 'cancel') &&
        (gate.reason_code !== 'repeat_iteration_limit' || choice === 'continue_repeat' || choice === 'cancel') &&
        (!gate.publication || !['approve', 'reject', 'retry'].includes(choice)));
}

export function workflowRuntimeCanResume(runtime: WorkflowRuntimeProjection | null): boolean {
    return Boolean(runtime?.can_resume === true &&
        ['failed', 'incomplete', 'invalid'].includes(runtime.state) &&
        !['m365_authorization', 'repeat_iteration_limit'].includes(runtime.gate?.reason_code ?? ''));
}

export function workflowRuntimeGateNotice(gate: WorkflowRuntimeGate): string {
    if (gate.reason_code === 'm365_authorization') {
        return 'Cancel only. Complete Microsoft 365 authorization through Approvals or Microsoft 365 connection settings, not workflow Resume or Approve task.';
    }
    return gate.choices.length === 1 && gate.choices[0] === 'cancel'
        ? 'Cancel only. Retained Repeat progress does not permit another batch.'
        : 'Decisions remain in the separate runtime panel.';
}

function outputKindMatches(actual: WorkflowOutputKind, expected: WorkflowOutputKind): boolean {
    return expected === 'any' || actual === expected ||
        (expected === 'json' && (actual === 'records' || actual === 'document_results'));
}

export function workflowScopeKey(scope: WorkflowScope): string {
    return scope.type === 'group' ? `group:${scope.groupId}` : 'personal';
}

function workflowRoot(scope: WorkflowScope): string {
    return scope.type === 'group' ? '/api/group/workflows' : '/api/user/workflows';
}

function scopeQuery(scope: WorkflowScope): string {
    if (scope.type !== 'group') {
        return '';
    }
    return new URLSearchParams({ group_id: scope.groupId }).toString();
}

function withScopeQuery(path: string, scope: WorkflowScope, extra?: URLSearchParams): string {
    const params = new URLSearchParams(scopeQuery(scope));
    extra?.forEach((value, key) => params.append(key, value));
    const query = params.toString();
    return query ? `${path}?${query}` : path;
}

export function workflowUrl(scope: WorkflowScope, workflowId?: string, suffix = '', extra?: URLSearchParams): string {
    const path = `${workflowRoot(scope)}${workflowId ? `/${encodeURIComponent(workflowId)}` : ''}${suffix}`;
    return withScopeQuery(path, scope, extra);
}

function asArray<T>(value: unknown, key?: string): T[] {
    if (Array.isArray(value)) {
        return value as T[];
    }
    if (key && isRecord(value)) {
        const nested = value[key];
        if (Array.isArray(nested)) {
            return nested as T[];
        }
    }
    return [];
}

function text(value: unknown): string {
    return typeof value === 'string' ? value : '';
}

function numberInRange(value: unknown, fallback: number, min: number, max: number): number {
    const parsed = Math.trunc(Number(value));
    if (!Number.isFinite(parsed)) {
        return fallback;
    }
    return Math.min(max, Math.max(min, parsed));
}

function outputKind(value: unknown, fallback: WorkflowOutputKind): WorkflowOutputKind {
    return WORKFLOW_OUTPUT_KINDS.includes(value as WorkflowOutputKind)
        ? value as WorkflowOutputKind
        : fallback;
}

function agentReference(value: unknown): WorkflowAgentReference | undefined {
    if (!isRecord(value) || typeof value.id !== 'string' || !value.id) {
        return undefined;
    }
    return {
        id: value.id,
        name: text(value.name),
        display_name: text(value.display_name) || undefined,
        is_global: value.is_global === true,
        is_group: value.is_group === true,
        group_id: text(value.group_id) || undefined,
    };
}

export function workflowAgentKey(value: WorkflowAgentReference | undefined): string {
    if (!value) {
        return '';
    }
    return JSON.stringify([
        value.id,
        value.is_global === true,
        value.is_group === true,
        value.group_id ?? '',
    ]);
}

export function findWorkflowAgent(
    options: WorkflowEditorOptions,
    key: string,
): WorkflowAgentReference | undefined {
    return options.agents.find((agent) => workflowAgentKey(agent) === key);
}

export function safeWorkflowAlias(value: unknown, fallback = 'input'): string {
    const cleaned = text(value)
        .trim()
        .replace(/^[^A-Za-z]+/, '')
        .replace(/[^A-Za-z0-9_-]+/g, '_')
        .slice(0, 64);
    if (WORKFLOW_ALIAS_PATTERN.test(cleaned)) {
        return cleaned;
    }
    const fallbackCleaned = fallback
        .replace(/^[^A-Za-z]+/, '')
        .replace(/[^A-Za-z0-9_-]+/g, '_')
        .slice(0, 64);
    return WORKFLOW_ALIAS_PATTERN.test(fallbackCleaned) ? fallbackCleaned : 'input';
}

function taskIdFallback(): string {
    const cryptoApi = globalThis.crypto;
    if (cryptoApi?.randomUUID) {
        return cryptoApi.randomUUID();
    }
    if (!cryptoApi?.getRandomValues) {
        throw new Error('Secure random values are required to create workflow task IDs.');
    }
    const bytes = new Uint8Array(16);
    cryptoApi.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, '0'));
    return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10).join('')}`;
}

export function createWorkflowTask(index: number): WorkflowTask {
    return {
        id: taskIdFallback(),
        type: 'instructions',
        name: `Task ${index + 1}`,
        instructions: '',
        order: index + 1,
        runner: { type: 'inherit' },
    };
}

export function newWorkflowDefinition(scope: WorkflowScope): WorkflowDefinition {
    return {
        definition_version: 2,
        durable_execution: true,
        name: '',
        description: '',
        runner_type: 'model',
        model_endpoint_id: '',
        model_id: '',
        m365_run_as_user_id: '',
        chat_capabilities_enabled: false,
        trigger_type: 'manual',
        schedule: { unit: 'minutes', value: 15 },
        is_enabled: true,
        error_handling: { strategy: 'halt', retry_count: 0 },
        tasks: [createWorkflowTask(0)],
        reference_inputs: [],
        ...(scope.type === 'group' ? { group_id: scope.groupId } : {}),
    };
}

function normalizeRunner(value: unknown, structured = false): WorkflowTaskRunner {
    if (!isRecord(value)) {
        return { type: 'inherit' };
    }
    const type = ['inherit', 'agent', 'model'].includes(String(value.type))
        ? value.type as WorkflowTaskRunnerType
        : 'inherit';
    return {
        ...(structured ? value : {}),
        type,
        selected_agent: agentReference(value.selected_agent),
        model_endpoint_id: text(value.model_endpoint_id),
        model_id: text(value.model_id),
    };
}

function normalizeOutputContract(value: unknown): WorkflowOutputContract | undefined {
    if (value === null || value === undefined || !isRecord(value)) {
        return undefined;
    }
    const record = value;
    const schema = isRecord(record.schema) ? record.schema : undefined;
    const expected = record.expected_count === null || record.expected_count === undefined || record.expected_count === ''
        ? undefined : Number(record.expected_count);
    const identityField = text(record.identity_field).trim();
    return {
        kind: outputKind(record.kind, 'any'),
        ...(schema ? { schema } : {}),
        ...(expected !== undefined ? { expected_count: expected } : {}),
        ...(identityField ? { identity_field: identityField } : {}),
        require_complete_coverage: record.require_complete_coverage === true,
        allow_partial: record.allow_partial === true,
    };
}

function normalizeInputs(value: unknown, structured = false): (WorkflowInputBinding | WorkflowFlowBinding)[] | undefined {
    if (structured) {
        if (value === undefined) return [];
        if (!Array.isArray(value) || !value.every(isFlowBinding)) {
            throw new Error('This structured workflow contains unsupported input bindings. Its saved definition was not changed.');
        }
        return structuredClone(value);
    }
    if (value === null || value === undefined) {
        return undefined;
    }
    if (!Array.isArray(value)) {
        return undefined;
    }
    return value.filter(isRecord).map((entry) => ({
        name: safeWorkflowAlias(entry.name, 'input'),
        task_id: text(entry.task_id),
        output: WORKFLOW_INPUT_OUTPUTS.includes(entry.output as WorkflowInputOutput)
            ? entry.output as WorkflowInputOutput
            : 'text',
        required: entry.required !== false,
        expected_kind: outputKind(entry.expected_kind, 'any'),
    }));
}

function normalizeApproval(value: unknown): WorkflowTaskApproval | undefined {
    if (value === null || value === undefined || !isRecord(value)) {
        return undefined;
    }
    const message = text(value.message);
    return {
        required: value.required === true,
        ...(message ? { message } : {}),
    };
}

function normalizeTask(value: unknown, index: number, structured = false): WorkflowTask {
    const record = isRecord(value) ? value : {};
    const unsupportedInputs = structured && record.inputs !== undefined &&
        (!Array.isArray(record.inputs) || !record.inputs.every(isFlowBinding));
    const unsupportedConfiguration = structured && (
        record.type !== undefined && record.type !== 'instructions' ||
        record.runner !== undefined && (!isRecord(record.runner) || !['inherit', 'model', 'agent'].includes(String(record.runner.type))) ||
        record.output_contract !== undefined && record.output_contract !== null &&
            (!isRecord(record.output_contract) || !WORKFLOW_OUTPUT_KINDS.includes(record.output_contract.kind as WorkflowOutputKind))
    );
    const inputs = structured || (Object.hasOwn(record, 'inputs') && record.inputs !== null)
        ? unsupportedInputs ? [] : normalizeInputs(record.inputs, structured) ?? []
        : undefined;
    const referenceIds = Array.isArray(record.reference_ids)
        ? record.reference_ids.filter((item): item is string => typeof item === 'string')
        : undefined;
    const outputContract = normalizeOutputContract(record.output_contract);
    const approval = Object.hasOwn(record, 'approval') ? normalizeApproval(record.approval) : undefined;
    return {
        ...record,
        id: text(record.id) || taskIdFallback(),
        type: 'instructions',
        name: text(record.name) || `Task ${index + 1}`,
        instructions: text(record.instructions),
        order: index + 1,
        runner: normalizeRunner(record.runner, structured),
        ...(unsupportedInputs ? { unrecognized_inputs: structuredClone(record.inputs) } : {}),
        ...(unsupportedConfiguration ? { unrecognized_configuration: structuredClone(record) } : {}),
        document_action: isRecord(record.document_action) ? record.document_action as WorkflowDocumentAction : undefined,
        ...(inputs !== undefined ? { inputs } : {}),
        ...(referenceIds !== undefined ? { reference_ids: referenceIds } : {}),
        ...(outputContract ? { output_contract: structured && isRecord(record.output_contract)
            ? { ...record.output_contract, ...outputContract } : outputContract } : {}),
        ...(approval ? { approval } : {}),
    };
}

function legacyWorkflowTask(record: Record<string, unknown>): WorkflowTask | null {
    const prompt = text(record.task_prompt);
    if (!prompt) {
        return null;
    }
    return {
        id: text(record.task_id) || taskIdFallback(),
        type: 'instructions',
        name: text(record.task_name) || 'Task 1',
        instructions: prompt,
        order: 1,
        runner: { type: 'inherit' },
        ...(isRecord(record.document_action) ? { document_action: record.document_action as WorkflowDocumentAction } : {}),
    };
}

export function documentActionFromSelection(
    type: Exclude<WorkflowDocumentActionType, 'none' | 'comparison'>,
    documents: WorkflowReferenceInput[],
    options: { mode?: 'selected' | 'relevance'; analysisMode?: 'combined' | 'per_document' } = {},
): WorkflowDocumentAction {
    if (type === 'search' && options.mode === 'relevance') {
        return {
            type: 'search',
            doc_scope: 'all',
            active_group_ids: [],
            active_public_workspace_id: [],
            document_ids: [],
            target_mode: 'selected',
            analysis_mode: options.analysisMode ?? 'combined',
        };
    }
    const scope = documentActionScope(documents);
    return {
        type,
        doc_scope: scope.docScope,
        active_group_ids: scope.groupIds,
        active_public_workspace_id: scope.publicWorkspaceIds,
        document_ids: documents.map((document) => document.document_id),
        target_mode: 'selected',
        analysis_mode: options.analysisMode ?? 'combined',
    };
}

export function comparisonActionFromSelection(
    left: WorkflowReferenceInput | null,
    right: WorkflowReferenceInput[],
): WorkflowDocumentAction {
    const documents = [...(left ? [left] : []), ...right];
    const scope = documentActionScope(documents);
    return {
        type: 'comparison',
        doc_scope: scope.docScope,
        active_group_ids: scope.groupIds,
        active_public_workspace_id: scope.publicWorkspaceIds,
        document_ids: documents.map((document) => document.document_id),
        target_mode: 'selected',
        analysis_mode: 'combined',
        left_document_id: left?.document_id ?? '',
        right_document_ids: right.map((document) => document.document_id),
    };
}

function documentActionScope(documents: WorkflowReferenceInput[]): {
    docScope: WorkflowReferenceScope | 'all';
    groupIds: string[];
    publicWorkspaceIds: string[];
} {
    const scopeTypes = new Set(documents.map((document) => document.scope_type));
    const groupIds = [...new Set(documents.filter((document) => document.scope_type === 'group').map((document) => document.scope_id).filter(Boolean))];
    const publicWorkspaceIds = [...new Set(documents.filter((document) => document.scope_type === 'public').map((document) => document.scope_id).filter(Boolean))];
    return {
        docScope: scopeTypes.size === 1 ? documents[0]?.scope_type ?? 'all' : 'all',
        groupIds,
        publicWorkspaceIds,
    };
}

export function normalizeWorkflowDefinition(
    value: unknown,
    scope: WorkflowScope = DEFAULT_WORKFLOW_SCOPE,
): WorkflowDefinition {
    const record = isRecord(value) ? value : {};
    const revision = text(record.definition_revision);
    const schedule = isRecord(record.schedule) ? record.schedule : {};
    const errorHandling = isRecord(record.error_handling) ? record.error_handling : {};
    const trigger = ['manual', 'interval', 'file_sync'].includes(String(record.trigger_type))
        ? record.trigger_type as WorkflowTriggerType
        : 'manual';
    const normalizedTasks = Array.isArray(record.tasks) ? record.tasks : [];
    const tasks = normalizedTasks
        .map((task, index) => normalizeTask(task, index, record.definition_version === 3))
        .sort((left, right) => left.order - right.order)
        .map((task, index) => ({ ...task, order: index + 1 }));
    const references = (Array.isArray(record.reference_inputs) ? record.reference_inputs : [])
        .filter(isRecord)
        .map((entry) => ({
            id: text(entry.id) || taskIdFallback(),
            name: safeWorkflowAlias(entry.name, `ref_${text(entry.document_id) || 'document'}`),
            document_id: text(entry.document_id),
            scope_type: ['personal', 'group', 'public'].includes(String(entry.scope_type))
                ? entry.scope_type as WorkflowReferenceScope
                : scope.type,
            scope_id: text(entry.scope_id) || (scope.type === 'group' && entry.scope_type === 'group' ? scope.groupId : ''),
        }))
        .filter((entry) => entry.document_id);
    return {
        ...record,
        definition_version: numberInRange(record.definition_version, 2, 1, 999),
        ...(revision ? { definition_revision: revision } : {}),
        id: text(record.id) || undefined,
        name: text(record.name),
        description: text(record.description),
        runner_type: record.runner_type === 'agent' ? 'agent' : 'model',
        selected_agent: agentReference(record.selected_agent),
        model_endpoint_id: text(record.model_endpoint_id),
        model_id: text(record.model_id),
        m365_run_as_user_id: text(record.m365_run_as_user_id),
        chat_capabilities_enabled: record.chat_capabilities_enabled === true,
        trigger_type: trigger,
        schedule: {
            unit: ['seconds', 'minutes', 'hours'].includes(String(schedule.unit))
                ? schedule.unit as WorkflowSchedule['unit']
                : 'minutes',
            value: numberInRange(schedule.value, 15, 1, 999999),
        },
        is_enabled: record.is_enabled !== false,
        error_handling: {
            strategy: errorHandling.strategy === 'continue' ? 'continue' : 'halt',
            retry_count: numberInRange(errorHandling.retry_count, 0, 0, 5),
        },
        tasks: tasks.length ? tasks : [legacyWorkflowTask(record) ?? createWorkflowTask(0)],
        reference_inputs: references,
        ...(record.definition_version === 3 && tasks.some((task) =>
            Object.hasOwn(task, 'unrecognized_inputs') || Object.hasOwn(task, 'unrecognized_configuration')) ? {
            editor_readonly_reason: 'This workflow contains task configuration or bindings from an unsupported schema. Its original configuration has been retained and editing is disabled.',
        } : {}),
        ...(Object.hasOwn(record, 'durable_execution') ? { durable_execution: record.durable_execution === true } : {}),
        ...(scope.type === 'group' ? { group_id: scope.groupId } : {}),
    };
}

export function workflowForSave(
    draft: WorkflowDefinition,
    original: WorkflowDefinition | null,
    scope: WorkflowScope,
): WorkflowDefinition {
    if (draft.editor_readonly_reason || flowUnsupportedReason(draft)) {
        throw new Error('This workflow contains unsupported executable fields and cannot be saved by this editor.');
    }
    if (original && original.definition_version >= 3 && draft.definition_version < original.definition_version) {
        throw new Error('This workflow cannot be downgraded without losing executable fields.');
    }
    const base = original ? structuredClone(original) : newWorkflowDefinition(scope);
    const originalHasDurable = original ? Object.hasOwn(original, 'durable_execution') : false;
    const includeDurable = !original || originalHasDurable || draft.durable_execution === true;
    const next = {
        ...base,
        id: original?.id ?? draft.id,
        definition_version: draft.definition_version === 3 ? 3 : 2,
        definition_revision: original?.definition_revision,
        name: draft.name.trim(),
        description: draft.description.trim(),
        runner_type: draft.runner_type,
        ...(draft.runner_type === 'agent' && draft.selected_agent ? { selected_agent: draft.selected_agent } : { selected_agent: undefined }),
        model_endpoint_id: draft.runner_type === 'model' ? draft.model_endpoint_id || '' : '',
        model_id: draft.runner_type === 'model' ? draft.model_id || '' : '',
        m365_run_as_user_id: text(draft.m365_run_as_user_id ?? original?.m365_run_as_user_id),
        chat_capabilities_enabled: draft.chat_capabilities_enabled,
        trigger_type: draft.trigger_type,
        schedule: draft.schedule,
        is_enabled: draft.is_enabled,
        error_handling: draft.error_handling,
        tasks: draft.tasks.map((task, index) => ({ ...task, order: index + 1 })),
        task_prompt: draft.tasks[0]?.instructions.trim() || '',
        reference_inputs: draft.reference_inputs,
        ...(draft.definition_version === 3 ? { flow: structuredClone(draft.flow), limits: structuredClone(draft.limits) } : {}),
        ...(includeDurable ? { durable_execution: draft.durable_execution === true } : {}),
        ...(scope.type === 'group' ? { group_id: scope.groupId } : {}),
    };
    if (!includeDurable) {
        delete next.durable_execution;
    }
    return normalizeWorkflowDefinition(next, scope);
}

export function preservedWorkflowFieldLabels(original: WorkflowDefinition | null): string[] {
    if (!original) {
        return [];
    }
    const edited = new Set([
        'definition_version',
        'definition_revision',
        'id',
        'name',
        'description',
        'runner_type',
        'selected_agent',
        'model_endpoint_id',
        'model_id',
        'm365_run_as_user_id',
        'chat_capabilities_enabled',
        'trigger_type',
        'schedule',
        'is_enabled',
        'error_handling',
        'tasks',
        'task_prompt',
        'reference_inputs',
        'durable_execution',
        'flow',
        'limits',
        'group_id',
    ]);
    const labels: Record<string, string> = {
        file_sync: 'file sync settings',
        alerts: 'alert settings',
        alert_settings: 'alert settings',
        document_actions: 'document action settings',
        publication: 'publication settings',
        publication_options: 'publication options',
        metadata: 'metadata',
    };
    return Object.keys(original)
        .filter((key) => !edited.has(key))
        .map((key) => labels[key] ?? key.replace(/_/g, ' '))
        .sort((left, right) => left.localeCompare(right));
}

export function workflowTaskHasLocalRunner(
    workflow: WorkflowDefinition,
    task: WorkflowTask,
    options: WorkflowEditorOptions,
): boolean {
    const runner = task.runner.type === 'inherit' ? {
        type: workflow.runner_type, selected_agent: workflow.selected_agent,
        model_endpoint_id: workflow.model_endpoint_id, model_id: workflow.model_id,
    } : task.runner;
    if (runner.type === 'agent') {
        return options.agents.find((agent) => workflowAgentKey(agent) === workflowAgentKey(runner.selected_agent))?.loop_eligible === true;
    }
    const eligible = runner.model_endpoint_id || runner.model_id
        ? options.models.find((model) => model.endpoint_id === runner.model_endpoint_id && model.model_id === runner.model_id)?.loop_eligible
        : options.default_model?.loop_eligible;
    return eligible !== false;
}

export function workflowInputProcessingErrors(
    workflow: WorkflowDefinition,
    task: WorkflowTask,
    options: WorkflowEditorOptions,
): string[] {
    const mode = task.input_processing;
    if (mode === undefined) return [];
    const label = task.name || 'Task';
    if (!['full', 'saved_record_report'].includes(mode)) return [`${label}: this large-input processing mode is not supported.`];
    const errors: string[] = [];
    if (workflow.definition_version !== 3) errors.push(`${label}: large saved input processing choices require structured definition v3.`);
    if (!options.supported_input_processing_modes?.includes(mode)) errors.push(`${label}: this server does not support the selected large-input processing mode.`);
    if (mode === 'full') return errors;
    if (task.document_action?.type !== 'none') errors.push(`${label}: saved-record reports require No document action; they explain saved data rather than reanalyzing sources.`);
    if (task.publication) errors.push(`${label}: saved-record reports cannot publish artifacts. Use a separate publication task.`);
    if (task.output_contract?.kind !== 'text') errors.push(`${label}: saved-record reports require a text output contract.`);
    const hasCollection = (task.inputs ?? []).some((binding) => {
        if (!isFlowBinding(binding)) return false;
        const output = flowSourceOutput(workflow, binding.source);
        return output && (output.kinds ?? [output.kind]).every((kind) => ['records', 'document_results'].includes(kind));
    });
    if (!hasCollection) errors.push(`${label}: saved-record reports require at least one saved records or document-results node-output input or current Repeat state.`);
    if (!workflowTaskHasLocalRunner(workflow, task, options)) {
        errors.push(`${label}: saved-record reports require a locally metered model or local agent; hosted runners are not supported.`);
    }
    return errors;
}

export function workflowValidationErrors(
    draft: WorkflowDefinition,
    options: WorkflowEditorOptions,
): string[] {
    const errors: string[] = [];
    if (!draft.name.trim()) {
        errors.push('Workflow name is required.');
    }
    if (!options.can_manage) {
        errors.push('You do not have permission to save workflows in this scope.');
    }
    if (!(options.supported_definition_versions ?? [1, 2]).includes(draft.definition_version)) {
        errors.push('This workflow was created by a newer editor and is read-only here.');
    }
    if (draft.definition_version === 3) {
        errors.push(...analyzeWorkflowFlow(draft).errors);
        flowLoops(draft).forEach(({ node }) => {
            errors.push(...loopSelectionErrors(node, workflowLoopLimit(options)));
            const sources = node.iterable.kind === 'documents' ? node.iterable.documents
                : node.iterable.kind === 'workspace_query' ? node.iterable.scopes : [];
            if (options.scope.type === 'group' && sources.some((source) =>
                source.scope_type !== 'group' || source.scope_id !== options.scope.id)) {
                errors.push('Group workflow loops can select only documents in this explicit group workspace.');
            }
        });
        flowRepeats(draft).forEach(({ node }) => {
            errors.push(...repeatIterationErrors(node, workflowRepeatLimit(options)));
            node.state.forEach((slot) => {
                const contract = slot.output_contract;
                if (contract.schema) errors.push(...workflowSchemaErrors(contract.schema).map((error) =>
                    `Repeat ${node.id} state ${slot.name}: ${error}`));
                if (contract.expected_count !== undefined &&
                    (!Number.isSafeInteger(contract.expected_count) || contract.expected_count < 0 || contract.kind === 'text')) {
                    errors.push(`Repeat ${node.id} state ${slot.name}: expected count needs a nonnegative whole number for structured data.`);
                }
                if (contract.identity_field && contract.kind !== 'records') {
                    errors.push(`Repeat ${node.id} state ${slot.name}: identity fields apply only to records.`);
                }
            });
        });
        const checkCollects = (region: typeof draft.flow) => {
            if (!isFlowRegion(region)) return;
            region.nodes.forEach((node) => {
                if (node.kind === 'collect') {
                    const contract = node.output_contract;
                    if (contract.schema) errors.push(...workflowSchemaErrors(contract.schema).map((error) => `Collect ${node.id}: ${error}`));
                    if (contract.expected_count !== undefined && (!Number.isSafeInteger(contract.expected_count) || contract.expected_count < 0)) {
                        errors.push('Collect expected count must be a nonnegative whole number.');
                    }
                    if (contract.identity_field && contract.kind !== 'records') errors.push('Collect business-key uniqueness is available only for records.');
                } else if (node.kind === 'for_each' || node.kind === 'repeat_until') checkCollects(node.body);
                else if (node.kind === 'if') {
                    checkCollects(node.then);
                    checkCollects(node.else);
                }
            });
        };
        checkCollects(draft.flow);
    }
    const unsupported = flowUnsupportedReason(draft, options);
    if (unsupported) errors.push(unsupported);
    if (draft.trigger_type === 'interval' && draft.schedule.value < 1) {
        errors.push('Interval workflows need a positive schedule value.');
    }
    if (draft.runner_type === 'agent' && !draft.selected_agent) {
        errors.push('Choose an agent or switch the workflow runner to model.');
    }
    if (draft.runner_type === 'agent' && draft.selected_agent &&
        !options.agents.some((agent) => workflowAgentKey(agent) === workflowAgentKey(draft.selected_agent))) {
        errors.push('Choose an authorized agent for this workflow scope.');
    }
    if (draft.runner_type === 'model' && options.models.length > 0 &&
        (draft.model_endpoint_id || draft.model_id) &&
        !options.models.some((model) => model.endpoint_id === draft.model_endpoint_id && model.model_id === draft.model_id)) {
        errors.push('Choose an authorized model option, or leave the model blank to use the app default.');
    }
    if (draft.runner_type === 'model' && !draft.model_endpoint_id && !draft.model_id &&
        options.default_model?.valid === false) {
        errors.push('Choose an explicit model because the app default model is not valid for this workflow scope.');
    }
    if (draft.tasks.length > options.max_tasks) {
        errors.push(`This workspace allows at most ${options.max_tasks} tasks per workflow.`);
    }
    if (draft.tasks.some((task) => task.approval?.required === true) && draft.durable_execution !== true) {
        errors.push('Enable durable execution before requiring task approval.');
    }
    const taskIds = new Map(draft.tasks.map((task, index) => [task.id, index]));
    draft.tasks.forEach((task, index) => {
        errors.push(...workflowInputProcessingErrors(draft, task, options));
        if (!task.name.trim()) {
            errors.push(`Task ${index + 1} needs a name.`);
        }
        if (!task.instructions.trim()) {
            errors.push(`${task.name || `Task ${index + 1}`} needs instructions.`);
        }
        if (task.instructions.length > WORKFLOW_TASK_INSTRUCTIONS_LIMIT) {
            errors.push(`${task.name || `Task ${index + 1}`} exceeds the ${WORKFLOW_TASK_INSTRUCTIONS_LIMIT.toLocaleString()} character instruction limit.`);
        }
        if (task.approval?.message && task.approval.message.length > WORKFLOW_APPROVAL_MESSAGE_LIMIT) {
            errors.push(`${task.name || `Task ${index + 1}`} approval message must be ${WORKFLOW_APPROVAL_MESSAGE_LIMIT.toLocaleString()} characters or fewer.`);
        }
        if (task.runner.type === 'agent' && !task.runner.selected_agent) {
            errors.push(`${task.name || `Task ${index + 1}`} uses an agent runner but no agent is selected.`);
        }
        if (task.runner.type === 'agent' && task.runner.selected_agent &&
            !options.agents.some((agent) => workflowAgentKey(agent) === workflowAgentKey(task.runner.selected_agent))) {
            errors.push(`${task.name || `Task ${index + 1}`} uses an agent that is not available in this scope.`);
        }
        const contract = task.output_contract;
        if (contract?.expected_count !== undefined &&
            (!Number.isInteger(contract.expected_count) || contract.expected_count < 0)) {
            errors.push(`${task.name || `Task ${index + 1}`} needs a nonnegative whole-number expected count.`);
        }
        const action = task.document_action;
        if (action && !['none', 'search', 'analyze', 'comparison'].includes(String(action.type))) {
            errors.push(`${task.name || `Task ${index + 1}`} has an unsupported document action type.`);
        }
        if (action?.type === 'analyze' && action.target_mode !== 'current_item' && (!Array.isArray(action.document_ids) || action.document_ids.length === 0)) {
            errors.push(`${task.name || `Task ${index + 1}`} needs selected evidence for Analyze.`);
        }
        if (action?.target_mode === 'current_item' && draft.definition_version !== 3) {
            errors.push('Current-document Analyze requires structured control flow.');
        }
        if (draft.definition_version === 3 && enclosingFlowLoopControls(draft, flowTaskNodeId(draft, task.id)).length && !task.publication) {
            if (!workflowTaskHasLocalRunner(draft, task, options)) {
                errors.push(`${task.name}: choose a loop-eligible local agent or model. Hosted runners are not supported inside For each or Repeat.`);
            }
        }
        if (action?.type === 'search' && action.doc_scope !== 'all' &&
            (!Array.isArray(action.document_ids) || action.document_ids.length === 0)) {
            errors.push(`${task.name || `Task ${index + 1}`} needs selected evidence for selected Search.`);
        }
        if (action?.type === 'comparison' &&
            (!action.left_document_id || !Array.isArray(action.right_document_ids) || action.right_document_ids.length === 0)) {
            errors.push(`${task.name || `Task ${index + 1}`} needs one source and at least one target document for comparison.`);
        }
        if (contract?.expected_count !== undefined && !WORKFLOW_COUNT_KINDS.has(contract.kind)) {
            errors.push(`${task.name || `Task ${index + 1}`} can set expected count only for records, JSON, or document results.`);
        }
        if (contract?.identity_field && contract.kind !== 'records') {
            errors.push(`${task.name || `Task ${index + 1}`} can set an identity field only for records output.`);
        }
        if (contract?.schema) {
            errors.push(...workflowSchemaErrors(contract.schema).map((message) =>
                `${task.name || `Task ${index + 1}`} output schema: ${message}`));
        }
        if (task.runner.type === 'model' && options.models.length > 0 &&
            (task.runner.model_endpoint_id || task.runner.model_id) &&
            !options.models.some((model) => model.endpoint_id === task.runner.model_endpoint_id && model.model_id === task.runner.model_id)) {
            errors.push(`${task.name || `Task ${index + 1}`} uses a model that is not available in this scope.`);
        }
        if (task.runner.type === 'model' && !task.runner.model_endpoint_id && !task.runner.model_id &&
            options.default_model?.valid === false) {
            errors.push(`${task.name || `Task ${index + 1}`} must choose an explicit model because the app default model is not valid for this workflow scope.`);
        }
        for (const input of task.inputs ?? []) {
            if (draft.definition_version === 3) continue;
            if (!isLegacyWorkflowBinding(input)) {
                errors.push('Structured input bindings require definition version 3.');
                continue;
            }
            if (!WORKFLOW_ALIAS_PATTERN.test(input.name)) {
                errors.push(`${task.name || `Task ${index + 1}`} has an input alias that must start with a letter and use only letters, numbers, underscores, or dashes, up to 64 characters.`);
            }
            const producerIndex = taskIds.get(input.task_id);
            if (producerIndex === undefined) {
                errors.push(`${task.name || `Task ${index + 1}`} has an input named ${input.name || 'Input'} that points to a missing task.`);
            } else if (producerIndex >= index) {
                errors.push(`${task.name || `Task ${index + 1}`} has an input named ${input.name || 'Input'} that points to a later task. Reorder the producer above it or change the binding.`);
            } else if (input.output === 'authoritative') {
                const producer = draft.tasks[producerIndex];
                const producerKind = producer.output_contract?.kind ?? 'any';
                if (producerKind !== 'any' && !outputKindMatches(producerKind, input.expected_kind)) {
                    errors.push(`${task.name || `Task ${index + 1}`} has an authoritative input whose expected kind does not match ${producer.name || 'the producer'}’s declared output kind.`);
                }
            }
        }
        for (const referenceId of task.reference_ids ?? []) {
            if (!draft.reference_inputs.some((reference) => reference.id === referenceId)) {
                errors.push(`${task.name || `Task ${index + 1}`} references a removed shared document.`);
            }
        }
    });
    draft.reference_inputs.forEach((reference) => {
        if (!WORKFLOW_ALIAS_PATTERN.test(reference.name)) {
            errors.push(`Shared reference ${reference.document_id} has an alias that must start with a letter and use only letters, numbers, underscores, or dashes, up to 64 characters.`);
        }
    });
    return [...new Set(errors)];
}

export function workflowSchemaErrors(schema: unknown): string[] {
    if (!isRecord(schema)) {
        return ['schema must be a JSON object.'];
    }
    const serialized = JSON.stringify(schema);
    if (serialized.length > WORKFLOW_SCHEMA_LIMIT) {
        return [`schema must be ${WORKFLOW_SCHEMA_LIMIT / 1024} KiB or smaller.`];
    }
    const errors: string[] = [];
    const walk = (value: unknown, path: string) => {
        if (Array.isArray(value)) {
            value.forEach((item, index) => walk(item, `${path}[${index}]`));
            return;
        }
        if (!isRecord(value)) {
            return;
        }
        for (const [key, nested] of Object.entries(value)) {
            if (!WORKFLOW_SCHEMA_ALLOWED_KEYS.has(key)) {
                errors.push(`${path || 'schema'} uses unsupported keyword ${key}.`);
                continue;
            }
            if (key === 'properties' && isRecord(nested)) {
                Object.entries(nested).forEach(([property, propertySchema]) =>
                    walk(propertySchema, `${path || 'schema'}.properties.${property}`));
            } else if (key === 'items') {
                walk(nested, `${path || 'schema'}.items`);
            }
        }
    };
    walk(schema, 'schema');
    return errors.slice(0, 8);
}

export function sameWorkflowDefinition(
    left: WorkflowDefinition,
    right: WorkflowDefinition,
): boolean {
    return sameEditorValue(left, right);
}

export function workflowErrorMessage(cause: unknown, fallback: string): string {
    if (cause instanceof ApiError && cause.status === 409) {
        return `${cause.message || 'This workflow could not be updated.'} Your draft has been retained; reload the saved workflow before retrying.`;
    }
    return cause instanceof Error ? cause.message : fallback;
}

export interface WorkflowM365RunAsUser {
    id: string;
    display_name: string;
}

export async function fetchWorkflowM365RunAsUsers(
    scope: WorkflowScope,
    signal?: AbortSignal,
): Promise<WorkflowM365RunAsUser[]> {
    const path = withScopeQuery(
        '/api/workflows/m365-run-as-users',
        scope,
        new URLSearchParams({ scope: scope.type }),
    );
    const response = await api.get<unknown>(path, signal);
    if (!isRecord(response) || !Array.isArray(response.users)) {
        throw new Error('The Microsoft 365 account list returned an invalid response.');
    }
    const users = new Map<string, WorkflowM365RunAsUser>();
    for (const entry of response.users) {
        if (!isRecord(entry) || typeof entry.id !== 'string' || !entry.id.trim() ||
            entry.display_name !== undefined && typeof entry.display_name !== 'string') {
            throw new Error('The Microsoft 365 account list returned an invalid response.');
        }
        users.set(entry.id, {
            id: entry.id,
            display_name: typeof entry.display_name === 'string' && entry.display_name.trim()
                ? entry.display_name
                : entry.id,
        });
    }
    return [...users.values()];
}

export async function fetchWorkflowEditorOptions(
    scope: WorkflowScope,
    signal?: AbortSignal,
): Promise<WorkflowEditorOptions> {
    const path = scope.type === 'group'
        ? withScopeQuery('/api/group/workflows/editor-options', scope)
        : '/api/user/workflows/editor-options';
    const response = await api.get<WorkflowEditorOptions>(path, signal);
    if (response?.definition_version !== 2 || typeof response.can_manage !== 'boolean' ||
        !Array.isArray(response.agents) || !Array.isArray(response.models) ||
        !response.scope || !['personal', 'group'].includes(String(response.scope.type))) {
        throw new Error('The workflow editor options returned an invalid response.');
    }
    const ceiling = response.flow_limits?.max_loop_items;
    const repeatCeiling = response.flow_limits?.max_repeat_iterations;
    const repeatHardCeiling = response.flow_limits?.hard_repeat_iterations;
    if (ceiling !== undefined && (!Number.isInteger(ceiling) || ceiling < 1 || ceiling > 5000) ||
        repeatCeiling !== undefined && (!Number.isInteger(repeatCeiling) || repeatCeiling < 1 || repeatCeiling > MAX_REPEAT_ITERATIONS) ||
        repeatHardCeiling !== undefined && repeatHardCeiling !== MAX_REPEAT_ITERATIONS ||
        [response.supported_node_kinds, response.supported_iterable_kinds, response.supported_query_modes, response.supported_binding_sources,
            response.supported_input_processing_modes, response.supported_publication_completion_policies]
            .some((values) => values !== undefined && (!Array.isArray(values) || values.some((value) => typeof value !== 'string'))) ||
        [...response.agents, ...response.models, response.default_model ?? {}]
            .some((runner) => !isRecord(runner) || runner.loop_eligible !== undefined && typeof runner.loop_eligible !== 'boolean')) {
        throw new Error('The workflow editor returned invalid loop capabilities or limits.');
    }
    const publicationSources = response.publication_source_capabilities;
    if (publicationSources !== undefined && (
        !Array.isArray(publicationSources) || publicationSources.some((capability) =>
            !isRecord(capability) || typeof capability.source_kind !== 'string' || !capability.source_kind.trim() ||
            !Array.isArray(capability.output_kinds) || capability.output_kinds.some((kind) => typeof kind !== 'string') ||
            !Array.isArray(capability.artifact_formats) || capability.artifact_formats.some((format) => typeof format !== 'string')) ||
        new Set(publicationSources.map((capability) => capability.source_kind)).size !== publicationSources.length
    )) {
        throw new Error('The workflow editor returned invalid publication source capabilities.');
    }
    return response;
}

export interface WorkflowLoopSelection {
    query_mode?: string;
    exhaustive?: boolean;
    ranking?: string;
    candidate_limitations?: string[];
    candidate_window?: number;
    semantic_rerank_window?: number;
    candidate_expansion?: string;
    candidate_expansion_rounds?: number;
}

export function workflowLoopSelection(value: unknown): WorkflowLoopSelection | undefined {
    if (value === undefined || value === null) return undefined;
    if (!isRecord(value)) throw new Error('The loop selection details returned an unsupported response.');
    const selection: WorkflowLoopSelection = {};
    for (const name of ['query_mode', 'ranking', 'candidate_expansion'] as const) {
        if (value[name] === undefined) continue;
        if (typeof value[name] !== 'string' || !value[name].trim() || value[name].length > 128) {
            throw new Error('The loop selection details returned an unsupported response.');
        }
        selection[name] = value[name] as string;
    }
    for (const name of ['candidate_window', 'semantic_rerank_window', 'candidate_expansion_rounds'] as const) {
        if (value[name] === undefined) continue;
        if (typeof value[name] !== 'number' || !Number.isSafeInteger(value[name]) || Number(value[name]) < 0) {
            throw new Error('The loop selection details returned an unsupported response.');
        }
        selection[name] = value[name] as number;
    }
    if (value.exhaustive !== undefined) {
        if (typeof value.exhaustive !== 'boolean') throw new Error('The loop selection details returned an unsupported response.');
        selection.exhaustive = value.exhaustive;
    }
    if (value.candidate_limitations !== undefined) {
        if (!Array.isArray(value.candidate_limitations) || value.candidate_limitations.length > 100 ||
            !value.candidate_limitations.every((item) => typeof item === 'string' && item.length <= 2000)) {
            throw new Error('The loop selection details returned unsupported candidate limitations.');
        }
        selection.candidate_limitations = value.candidate_limitations as string[];
    }
    return selection;
}

export interface WorkflowLoopPreview {
    count: number;
    count_exact: boolean;
    limit: number;
    within_limit: boolean;
    items: Record<string, unknown>[];
    error_message?: string;
    error_code?: string;
    selection?: WorkflowLoopSelection;
}

function isWorkflowLoopPreview(response: unknown, maxItems: number): response is WorkflowLoopPreview {
    return isRecord(response) && typeof response.count === 'number' && Number.isSafeInteger(response.count) && response.count >= 0 &&
        typeof response.limit === 'number' && Number.isInteger(response.limit) && response.limit >= 1 && response.limit <= MAX_LOOP_ITEMS &&
        response.limit <= maxItems && typeof response.count_exact === 'boolean' && typeof response.within_limit === 'boolean' &&
        (!response.within_limit || response.count_exact && response.count <= response.limit) &&
        (!response.count_exact || response.within_limit === (response.count <= response.limit)) &&
        Array.isArray(response.items) && response.items.length <= 50 && response.items.every(isRecord);
}

export async function previewWorkflowLoopInput(
    scope: WorkflowScope,
    iterable: WorkflowLoopIterable,
    maxItems: number,
    signal?: AbortSignal,
): Promise<WorkflowLoopPreview> {
    if (iterable.kind === 'input') throw new Error('Saved collection counts are known only when the loop starts.');
    try {
        const response = await api.post<unknown>(workflowUrl(scope, undefined, '/loop-inputs/preview'), {
            iterable, max_items: maxItems,
        }, signal);
        if (!isWorkflowLoopPreview(response, maxItems)) {
            throw new Error('The loop preview returned an invalid count or item page. No items have been admitted.');
        }
        return {
            count: response.count, count_exact: response.count_exact, limit: response.limit,
            within_limit: response.within_limit, items: response.items,
            selection: workflowLoopSelection(response.selection),
        };
    } catch (cause: unknown) {
        if (cause instanceof ApiError && cause.status === 422 && isRecord(cause.payload)) {
            const payload = cause.payload;
            const rejected = {
                count: payload.count, count_exact: payload.count_exact, limit: payload.limit,
                within_limit: payload.within_limit, items: [],
            };
            if (isWorkflowLoopPreview(rejected, maxItems) && !rejected.within_limit && rejected.count > rejected.limit) {
                return {
                    ...rejected, error_message: cause.message,
                    ...(typeof payload.code === 'string' ? { error_code: payload.code } : {}),
                    selection: workflowLoopSelection(payload.selection),
                };
            }
        }
        throw cause;
    }
}

export async function fetchScopedWorkflows(
    scope: WorkflowScope,
    signal?: AbortSignal,
): Promise<WorkflowDefinition[]> {
    const response = await api.get<unknown>(workflowUrl(scope), signal);
    return asArray<unknown>(response, 'workflows')
        .map((workflow) => normalizeWorkflowDefinition(workflow, scope));
}

export function saveWorkflowDefinition(
    scope: WorkflowScope,
    draft: WorkflowDefinition,
    original: WorkflowDefinition | null,
) {
    const payload = workflowForSave(draft, original, scope);
    return api.post<{ success?: boolean; workflow?: WorkflowDefinition }>(
        workflowUrl(scope),
        payload,
    );
}

export const startScopedWorkflowRun = (scope: WorkflowScope, workflowId: string) =>
    api.post<WorkflowRunStartResponse>(workflowUrl(scope, workflowId, '/run'));

export const cancelScopedWorkflow = (scope: WorkflowScope, workflowId: string) =>
    api.post<unknown>(workflowUrl(scope, workflowId, '/cancel'));

export const deleteScopedWorkflow = (scope: WorkflowScope, workflowId: string) =>
    api.delete<{ success?: boolean }>(workflowUrl(scope, workflowId));

export async function fetchScopedWorkflowRuns(
    scope: WorkflowScope,
    workflowId: string,
    signal?: AbortSignal,
) {
    const response = await api.get<unknown>(workflowUrl(scope, workflowId, '/runs'), signal);
    return asArray<WorkflowRunSummary>(response, 'runs');
}

export async function fetchScopedWorkflowRunItems(
    scope: WorkflowScope,
    workflowId: string,
    runId: string,
    signal?: AbortSignal,
): Promise<WorkflowRunItem[]> {
    const response = await api.get<unknown>(
        workflowUrl(scope, workflowId, `/runs/${encodeURIComponent(runId)}/items`),
        signal,
    );
    return asArray<WorkflowRunItem>(response, 'items');
}

export function fetchWorkflowTaskResult(
    scope: WorkflowScope,
    workflowId: string,
    runId: string,
    taskId: string,
    output: WorkflowInputOutput,
    offset: number,
    limit: number,
    signal?: AbortSignal,
) {
    const params = new URLSearchParams({
        output,
        offset: String(offset),
        limit: String(limit),
    });
    const path = `${workflowRoot(scope)}/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(taskId)}/result`;
    return api.get<WorkflowRunResultPage>(withScopeQuery(path, scope, params), signal);
}

function checkedRuntimeResponse(response: WorkflowRuntimeResponse): WorkflowRuntimeResponse {
    const paths = [
        response?.runtime?.gate?.iteration_path,
        ...(response?.runtime?.memory?.decisions ?? []).map((decision) => decision.iteration_path),
    ];
    if (!response?.runtime || paths.some((path) => path !== undefined && !validWorkflowIterationPath(path))) {
        throw new Error('The workflow runtime contains an unsupported iteration identity. Reload before making a decision.');
    }
    const publication = response.runtime.gate?.publication;
    if (publication !== undefined && !isWorkflowPublicationStatus(publication)) {
        throw new Error('The workflow runtime returned an unsupported publication status. Reload before making a decision.');
    }
    const gate = response.runtime.gate;
    const repeat = response.runtime.repeat_progress;
    const repeatGate = gate?.reason_code === 'repeat_iteration_limit';
    if (repeat !== undefined && !isWorkflowRepeatProgress(repeat) ||
        gate?.repeat !== undefined && (!repeatGate || !isWorkflowRepeatProgress(gate.repeat)) ||
        repeatGate && (response.runtime.state !== 'paused' || gate?.kind !== 'pause' ||
            typeof gate.id !== 'string' || !gate.id.trim() || gate.id.length > 256 ||
            !Number.isSafeInteger(gate.attempt) || Number(gate.attempt) < 1 ||
            !validWorkflowIterationPath(gate.iteration_path) ||
            !gate.repeat || gate.repeat.state !== 'waiting_manual_continue' ||
            gate.execution_id !== gate.repeat.execution_id || gate.node_id !== gate.repeat.node_id ||
            !sameEditorValue(gate.choices, ['continue_repeat', 'cancel'])) ||
        !repeatGate && gate?.choices.includes('continue_repeat')) {
        throw new Error('The workflow runtime returned an unsupported Repeat continuation gate or progress. Reload before making a decision.');
    }
    if (repeat !== undefined || repeatGate) {
        const limits = response.runtime.limits;
        if (!Number.isSafeInteger(response.runtime.version) || response.runtime.version < 0 ||
            !limits || !Number.isSafeInteger(limits.max_executions) || limits.max_executions < 1 ||
            limits.max_executions > DEFAULT_FLOW_LIMITS.max_executions ||
            !Number.isSafeInteger(limits.admitted_count) || limits.admitted_count < 0 ||
            !Number.isSafeInteger(limits.deadline_seconds) || limits.deadline_seconds < 1 ||
            limits.deadline_seconds > DEFAULT_FLOW_LIMITS.deadline_seconds || limits.waits_count !== true ||
            typeof limits.deadline_at !== 'string' || !Number.isFinite(Date.parse(limits.deadline_at)) ||
            typeof limits.max_repeat_iterations !== 'number' || !Number.isInteger(limits.max_repeat_iterations) ||
            limits.max_repeat_iterations < 1 || limits.max_repeat_iterations > MAX_REPEAT_ITERATIONS ||
            repeat && repeat.batch_size > limits.max_repeat_iterations ||
            gate?.repeat && gate.repeat.batch_size > limits.max_repeat_iterations) {
            throw new Error('The workflow runtime returned invalid frozen Repeat limits. Reload before making a decision.');
        }
    }
    const repeatCounts = response.runtime.repeat_counts;
    if (repeatCounts !== undefined && (!isRecord(repeatCounts) || Object.entries(repeatCounts).some(([key, value]) =>
        !['exhaustion_count', 'continuation_count'].includes(key) || typeof value !== 'number' ||
        !Number.isSafeInteger(value) || value < 0 || value > DEFAULT_FLOW_LIMITS.max_executions))) {
        throw new Error('The workflow runtime returned invalid Repeat audit counters.');
    }
    const progress = response.runtime.loop_progress;
    if (progress && (
        typeof progress.loop_id !== 'string' || !progress.loop_id.trim() ||
        typeof progress.loop_execution_id !== 'string' || !progress.loop_execution_id.trim() ||
        ['total', 'completed', 'skipped', 'failed', 'pending', 'limit',
            ...(progress.completed_empty !== undefined ? ['completed_empty'] : [])].some((key) => {
            const value = progress[key as keyof WorkflowLoopProgress];
            return typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0;
        }) || progress.limit < 1 || progress.limit > 5000 ||
        progress.current_index !== null && (!Number.isSafeInteger(progress.current_index) || progress.current_index < 0))) {
        throw new Error('The workflow runtime returned invalid frozen loop progress.');
    }
    return response;
}

export async function fetchWorkflowRuntime(
    scope: WorkflowScope,
    workflowId: string,
    runId: string,
    signal?: AbortSignal,
) {
    return checkedRuntimeResponse(await api.get<WorkflowRuntimeResponse>(
        workflowUrl(scope, workflowId, `/runs/${encodeURIComponent(runId)}/runtime`),
        signal,
    ));
}

export async function decideWorkflowRuntime(
    scope: WorkflowScope,
    workflowId: string,
    runId: string,
    request: WorkflowRuntimeDecisionRequest,
    signal?: AbortSignal,
) {
    return checkedRuntimeResponse(await api.post<WorkflowRuntimeResponse>(
        workflowUrl(scope, workflowId, `/runs/${encodeURIComponent(runId)}/runtime/decision`),
        request,
        signal,
    ));
}

export async function resumeWorkflowRuntime(
    scope: WorkflowScope,
    workflowId: string,
    runId: string,
    request: WorkflowRuntimeResumeRequest,
    signal?: AbortSignal,
) {
    return checkedRuntimeResponse(await api.post<WorkflowRuntimeResponse>(
        workflowUrl(scope, workflowId, `/runs/${encodeURIComponent(runId)}/runtime/resume`),
        request,
        signal,
    ));
}

export function documentId(document: WorkspaceDocument): string {
    return text(document.document_id) || text(document.id);
}

export function documentTitle(document: WorkspaceDocument): string {
    return text(document.title) || text(document.file_name) || documentId(document) || 'Untitled document';
}

export function workflowDocumentScopeId(
    document: WorkspaceDocument,
    scopeType: WorkflowReferenceScope,
    fallback: string,
): string {
    const keys = scopeType === 'group'
        ? ['scope_id', 'group_id']
        : scopeType === 'public'
            ? ['scope_id', 'public_workspace_id', 'workspace_id']
            : ['scope_id', 'user_id', 'owner_id'];
    for (const key of keys) {
        const value = document[key];
        if (typeof value === 'string' && value) {
            return value;
        }
    }
    return fallback;
}

export function normalizeDocumentPage(response: DocumentListResponse): {
    documents: WorkspaceDocument[];
    totalCount: number;
} {
    return {
        documents: response.documents ?? response.items ?? [],
        totalCount: response.total_count ?? (response.documents ?? response.items ?? []).length,
    };
}

export function scopedDocumentQuery(query: string, page: number): Partial<DocumentQuery> {
    return {
        ...DEFAULT_DOCUMENT_QUERY,
        search: query,
        page,
        pageSize: 10,
    };
}

export function documentQueryString(query: string, page: number): string {
    return buildDocumentListParams(scopedDocumentQuery(query, page));
}
