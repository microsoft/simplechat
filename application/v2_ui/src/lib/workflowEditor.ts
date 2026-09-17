// workflowEditor.ts
// Native V2 workflow editor contracts and safe client-side normalization.

import { api, ApiError } from './apiClient';
import {
    buildDocumentListParams,
    DEFAULT_DOCUMENT_QUERY,
} from './documentExplorer';
import type { DocumentListResponse, DocumentQuery, WorkspaceDocument } from './types';
import { isRecord, sameEditorValue } from './workspaceAuthoring';

export type WorkflowScope = { type: 'personal' } | { type: 'group'; groupId: string };
export type WorkflowRunnerType = 'model' | 'agent';
export type WorkflowTriggerType = 'manual' | 'interval' | 'file_sync';
export type WorkflowOutputKind = 'any' | 'text' | 'records' | 'json' | 'document_results';
export type WorkflowTaskRunnerType = 'inherit' | 'agent' | 'model';
export type WorkflowInputOutput = WorkflowOutputKind | 'authoritative' | 'documents';
export type WorkflowReferenceScope = 'personal' | 'group' | 'public';
export type WorkflowDocumentActionType = 'none' | 'search' | 'analyze' | 'comparison';
export type WorkflowRuntimeState =
    'queued' | 'running' | 'waiting_approval' | 'waiting_output' | 'waiting_recovery' |
    'paused' | 'cancelling' | 'cancelled' | 'failed' | 'invalid' | 'incomplete' |
    'completed' | 'completed_partial' | 'skipped';
export type WorkflowRuntimeGateKind = 'approval' | 'output' | 'recovery' | 'pause';
export type WorkflowRuntimeDecisionChoice = 'approve' | 'reject' | 'retry' | 'cancel' | 'resume';

export interface WorkflowAgentOption {
    id: string;
    name: string;
    display_name?: string;
    is_global?: boolean;
    is_group?: boolean;
    group_id?: string;
}

export type WorkflowAgentReference = WorkflowAgentOption;

export interface WorkflowModelOption {
    endpoint_id: string;
    model_id: string;
    label: string;
    provider: string;
}

export interface WorkflowEditorOptions {
    definition_version: 2;
    can_manage: boolean;
    max_tasks: number;
    agents: WorkflowAgentOption[];
    models: WorkflowModelOption[];
    default_model?: {
        label?: string;
        valid?: boolean;
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

export interface WorkflowTask {
    id: string;
    type: 'instructions';
    name: string;
    instructions: string;
    order: number;
    runner: WorkflowTaskRunner;
    document_action?: WorkflowDocumentAction;
    inputs?: WorkflowInputBinding[];
    reference_ids?: string[];
    output_contract?: WorkflowOutputContract;
    approval?: WorkflowTaskApproval;
    [key: string]: unknown;
}

export interface WorkflowDocumentAction {
    type: WorkflowDocumentActionType;
    doc_scope?: WorkflowReferenceScope | 'all';
    active_group_ids?: string[];
    active_public_workspace_id?: string[];
    document_ids?: string[];
    target_mode?: 'selected';
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
    [key: string]: unknown;
}

export interface WorkflowRuntimeGate {
    id: string;
    kind: WorkflowRuntimeGateKind;
    unit_id?: string;
    input_digest?: string;
    reason?: string;
    choices: string[];
}

export interface WorkflowRuntimeDecision {
    unit_id: string;
    choice: string;
    actor_user_id: string;
    decided_at?: string;
    input_digest?: string;
    attempt?: number;
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
        task_id?: string;
        run_id?: string;
        attempt?: number;
    };
    output_name?: string;
    result_ref?: WorkflowResultReference;
    output_ref?: string;
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
export const WORKFLOW_ALIAS_PATTERN = /^[A-Za-z][A-Za-z0-9_-]{0,63}$/;
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

function workflowUrl(scope: WorkflowScope, workflowId?: string, suffix = ''): string {
    const path = `${workflowRoot(scope)}${workflowId ? `/${encodeURIComponent(workflowId)}` : ''}${suffix}`;
    return withScopeQuery(path, scope);
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

function normalizeRunner(value: unknown): WorkflowTaskRunner {
    if (!isRecord(value)) {
        return { type: 'inherit' };
    }
    const type = ['inherit', 'agent', 'model'].includes(String(value.type))
        ? value.type as WorkflowTaskRunnerType
        : 'inherit';
    return {
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

function normalizeInputs(value: unknown): WorkflowInputBinding[] | undefined {
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

function normalizeTask(value: unknown, index: number): WorkflowTask {
    const record = isRecord(value) ? value : {};
    const inputs = Object.hasOwn(record, 'inputs') && record.inputs !== null
        ? normalizeInputs(record.inputs) ?? []
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
        runner: normalizeRunner(record.runner),
        document_action: isRecord(record.document_action) ? record.document_action as WorkflowDocumentAction : undefined,
        ...(inputs !== undefined ? { inputs } : {}),
        ...(referenceIds !== undefined ? { reference_ids: referenceIds } : {}),
        ...(outputContract ? { output_contract: outputContract } : {}),
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
        .map(normalizeTask)
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
        ...(Object.hasOwn(record, 'durable_execution') ? { durable_execution: record.durable_execution === true } : {}),
        ...(scope.type === 'group' ? { group_id: scope.groupId } : {}),
    };
}

export function workflowForSave(
    draft: WorkflowDefinition,
    original: WorkflowDefinition | null,
    scope: WorkflowScope,
): WorkflowDefinition {
    const base = original ? structuredClone(original) : newWorkflowDefinition(scope);
    const originalHasDurable = original ? Object.hasOwn(original, 'durable_execution') : false;
    const includeDurable = !original || originalHasDurable || draft.durable_execution === true;
    const next = {
        ...base,
        id: original?.id ?? draft.id,
        definition_version: 2,
        definition_revision: original?.definition_revision,
        name: draft.name.trim(),
        description: draft.description.trim(),
        runner_type: draft.runner_type,
        ...(draft.runner_type === 'agent' && draft.selected_agent ? { selected_agent: draft.selected_agent } : { selected_agent: undefined }),
        model_endpoint_id: draft.runner_type === 'model' ? draft.model_endpoint_id || '' : '',
        model_id: draft.runner_type === 'model' ? draft.model_id || '' : '',
        chat_capabilities_enabled: draft.chat_capabilities_enabled,
        trigger_type: draft.trigger_type,
        schedule: draft.schedule,
        is_enabled: draft.is_enabled,
        error_handling: draft.error_handling,
        tasks: draft.tasks.map((task, index) => ({ ...task, order: index + 1 })),
        task_prompt: draft.tasks[0]?.instructions.trim() || '',
        reference_inputs: draft.reference_inputs,
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
        'chat_capabilities_enabled',
        'trigger_type',
        'schedule',
        'is_enabled',
        'error_handling',
        'tasks',
        'task_prompt',
        'reference_inputs',
        'durable_execution',
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
    if (draft.definition_version > 2) {
        errors.push('This workflow was created by a newer editor and is read-only here.');
    }
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
        if (action?.type === 'analyze' && (!Array.isArray(action.document_ids) || action.document_ids.length === 0)) {
            errors.push(`${task.name || `Task ${index + 1}`} needs selected evidence for Analyze.`);
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
    return response;
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

export function fetchWorkflowRuntime(
    scope: WorkflowScope,
    workflowId: string,
    runId: string,
    signal?: AbortSignal,
) {
    return api.get<WorkflowRuntimeResponse>(
        workflowUrl(scope, workflowId, `/runs/${encodeURIComponent(runId)}/runtime`),
        signal,
    );
}

export function decideWorkflowRuntime(
    scope: WorkflowScope,
    workflowId: string,
    runId: string,
    request: WorkflowRuntimeDecisionRequest,
    signal?: AbortSignal,
) {
    return api.post<WorkflowRuntimeResponse>(
        workflowUrl(scope, workflowId, `/runs/${encodeURIComponent(runId)}/runtime/decision`),
        request,
        signal,
    );
}

export function resumeWorkflowRuntime(
    scope: WorkflowScope,
    workflowId: string,
    runId: string,
    request: WorkflowRuntimeResumeRequest,
    signal?: AbortSignal,
) {
    return api.post<WorkflowRuntimeResponse>(
        workflowUrl(scope, workflowId, `/runs/${encodeURIComponent(runId)}/runtime/resume`),
        request,
        signal,
    );
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
