// WorkflowExecutionHistory.tsx
// Structured V3 workflow execution, attempt, decision, and output inspection.

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ChevronDown, ChevronLeft, ChevronRight, FileJson, Loader2, RefreshCw } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import {
    fetchWorkflowExecutionAttemptResult,
    fetchWorkflowExecutionAttemptsPage,
    fetchWorkflowExecutionsPage,
    fetchWorkflowRuntimeDecisionsPage,
    type WorkflowExecutionAttemptRecord,
    type WorkflowExecutionDecisionPreview,
    type WorkflowExecutionPage,
    type WorkflowExecutionRecord,
    type WorkflowRuntimeDecisionRecord,
} from '../../lib/workflowExecutionHistory';
import {
    workflowErrorMessage,
    type WorkflowConsumedInput,
    type WorkflowIterationFrame,
    type WorkflowResultReference,
    type WorkflowRunResultPage,
    type WorkflowScope,
    type WorkflowValidationResult,
} from '../../lib/workflowEditor';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { Pill, RowAction } from '../workspace/primitives';

interface PagedState<T> {
    items: T[];
    nextCursor: string | null;
    totalCount?: number;
    loading: boolean;
    error: string;
    cursor: string | null;
    previousCursors: (string | null)[];
}

function statusTone(status: unknown): 'ok' | 'warn' | 'danger' | 'neutral' | 'accent' {
    const value = String(status ?? '').toLowerCase();
    if (['completed', 'succeeded', 'success', 'finished', 'valid'].includes(value)) {
        return 'ok';
    }
    if (['running', 'queued', 'pending', 'in_progress', 'started', 'waiting_approval', 'waiting_output', 'waiting_recovery', 'paused', 'skipped'].includes(value)) {
        return 'warn';
    }
    if (['failed', 'error', 'cancelled', 'canceled', 'incomplete', 'invalid'].includes(value)) {
        return 'danger';
    }
    return 'neutral';
}

const VALIDATION_STATUSES = new Set(['valid', 'invalid', 'incomplete', 'accepted_partial', 'not_requested']);

function text(value: unknown): string {
    return typeof value === 'string' ? value : '';
}

function formatTimestamp(value: unknown): string {
    const raw = String(value ?? '');
    if (!raw) {
        return '';
    }
    const parsed = new Date(raw);
    return Number.isNaN(parsed.valueOf()) ? raw : parsed.toLocaleString();
}

function validationSummary(value: WorkflowValidationResult | undefined): string {
    if (!value || value.version !== 1 || !VALIDATION_STATUSES.has(String(value.status))) {
        return '';
    }
    const reasonCodes = Array.isArray(value.reason_codes)
        ? value.reason_codes.filter((code): code is string => typeof code === 'string')
        : [];
    const counts = value.counts && typeof value.counts === 'object'
        ? Object.entries(value.counts).map(([key, count]) => `${key}: ${count}`).join(', ')
        : '';
    return [String(value.status), ...reasonCodes, counts].filter(Boolean).join(' · ');
}

function validationTone(value: WorkflowValidationResult | undefined): 'ok' | 'warn' | 'danger' | 'neutral' {
    if (value?.status === 'valid') {
        return 'ok';
    }
    if (value?.status === 'invalid' || value?.status === 'incomplete') {
        return 'danger';
    }
    if (value?.status === 'accepted_partial') {
        return 'warn';
    }
    return 'neutral';
}

function formatIterationPath(path: WorkflowIterationFrame[] | undefined): string {
    if (!Array.isArray(path) || !path.length) {
        return '';
    }
    return path.map((frame, index) => {
        const loop = text(frame.loop_id) || `region ${index + 1}`;
        const labels = [
            text(frame.item_id) ? `item ${text(frame.item_id)}` : '',
            Number.isFinite(Number(frame.index)) ? `index ${Number(frame.index)}` : '',
            Number.isFinite(Number(frame.iteration)) ? `iteration ${Number(frame.iteration)}` : '',
        ].filter(Boolean);
        return labels.length ? `${loop} (${labels.join(', ')})` : loop;
    }).join(' / ');
}

function resultReferenceSummary(reference: WorkflowResultReference | undefined): string {
    if (!reference) {
        return '';
    }
    const parts = [
        text(reference.storage),
        Number.isFinite(Number(reference.size_bytes)) ? `${Number(reference.size_bytes)} bytes` : '',
        Number.isFinite(Number(reference.chunk_count)) ? `${Number(reference.chunk_count)} chunks` : '',
        text(reference.sha256) ? `sha256 ${text(reference.sha256)}` : '',
    ].filter(Boolean);
    return parts.join(' · ');
}

function consumedInputSummary(input: WorkflowConsumedInput, index: number): string {
    const producer = input.producer;
    const path = formatIterationPath(producer?.iteration_path);
    const refs = [
        text(producer?.workflow_id) ? `workflow ${text(producer?.workflow_id)}` : '',
        text(producer?.run_id) ? `run ${text(producer?.run_id)}` : '',
        text(producer?.node_id) ? `node ${text(producer?.node_id)}` : '',
        text(producer?.execution_id) ? `execution ${text(producer?.execution_id)}` : '',
        text(producer?.task_id) ? `task ${text(producer?.task_id)}` : '',
        Number.isFinite(Number(producer?.attempt)) ? `attempt ${Number(producer?.attempt)}` : '',
        path ? `path ${path}` : '',
    ].filter(Boolean);
    const inputName = text(input.input_name) || `input ${index + 1}`;
    const outputName = text(input.output_name) || 'authoritative';
    return `${inputName} from ${outputName}${refs.length ? ` · ${refs.join(' · ')}` : ''}`;
}

function decisionSummary(decision: WorkflowExecutionDecisionPreview | WorkflowRuntimeDecisionRecord | undefined): string {
    if (!decision || typeof decision !== 'object' || Array.isArray(decision)) {
        return '';
    }
    const parts = [
        text(decision.choice) ? `choice ${text(decision.choice)}` : '',
        text(decision.selected_branch) ? `branch ${text(decision.selected_branch)}` : '',
        text(decision.branch_id) ? `branch ${text(decision.branch_id)}` : '',
        text(decision.target_node_id) ? `target ${text(decision.target_node_id)}` : '',
        text(decision.route_target) ? `target ${text(decision.route_target)}` : '',
        text(decision.target?.node_id) ? `target ${text(decision.target?.node_id)}` : '',
        text(decision.target?.exit_region_id) ? `exit ${text(decision.target?.exit_region_id)}` : '',
        text(decision.exit_region_id) ? `exit ${text(decision.exit_region_id)}` : '',
        text(decision.reason_code) ? `reason ${text(decision.reason_code)}` : '',
    ].filter(Boolean);
    return parts.join(' · ');
}

function historyErrorMessage(cause: unknown, fallback: string): string {
    if (cause instanceof ApiError && cause.status === 403) {
        return 'You no longer have access to this workflow run. Reload or ask an owner to restore access.';
    }
    if (cause instanceof ApiError && cause.status === 404) {
        return 'This workflow run history is no longer available.';
    }
    return workflowErrorMessage(cause, fallback);
}

function usePagedResource<T>(
    loadPage: (cursor: string | null, signal: AbortSignal) => Promise<WorkflowExecutionPage<T>>,
    fallbackError: string,
) {
    const [state, setState] = useState<PagedState<T>>({
        items: [],
        nextCursor: null,
        loading: true,
        error: '',
        cursor: null,
        previousCursors: [],
    });
    const abortRef = useRef<AbortController | null>(null);
    const tokenRef = useRef(0);

    const load = useCallback((cursor: string | null, previousCursors: (string | null)[]) => {
        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;
        tokenRef.current += 1;
        const token = tokenRef.current;
        setState({
            items: [],
            nextCursor: null,
            loading: true,
            error: '',
            cursor,
            previousCursors,
        });
        void loadPage(cursor, controller.signal)
            .then((page) => {
                if (controller.signal.aborted || token !== tokenRef.current) {
                    return;
                }
                setState({
                    items: page.items,
                    nextCursor: page.next_cursor,
                    totalCount: page.total_count,
                    loading: false,
                    error: '',
                    cursor,
                    previousCursors,
                });
            })
            .catch((cause: unknown) => {
                if (controller.signal.aborted || token !== tokenRef.current) {
                    return;
                }
                setState((current) => ({
                    ...current,
                    items: [],
                    nextCursor: null,
                    loading: false,
                    error: historyErrorMessage(cause, fallbackError),
                }));
            });
    }, [fallbackError, loadPage]);

    useEffect(() => {
        load(null, []);
        return () => abortRef.current?.abort();
    }, [load]);

    const refresh = useCallback(() => {
        load(null, []);
    }, [load]);

    const next = useCallback(() => {
        if (state.nextCursor) {
            load(state.nextCursor, [...state.previousCursors, state.cursor]);
        }
    }, [load, state.cursor, state.nextCursor, state.previousCursors]);

    const previous = useCallback(() => {
        if (!state.previousCursors.length) {
            return;
        }
        const nextPrevious = state.previousCursors.slice(0, -1);
        load(state.previousCursors[state.previousCursors.length - 1] ?? null, nextPrevious);
    }, [load, state.previousCursors]);

    return { ...state, refresh, next, previous };
}

function PageControls({
    loading,
    onRefresh,
    onPrevious,
    onNext,
    hasPrevious,
    hasNext,
    nextLabel,
    totalCount,
}: {
    loading: boolean;
    onRefresh: () => void;
    onPrevious: () => void;
    onNext: () => void;
    hasPrevious: boolean;
    hasNext: boolean;
    nextLabel: string;
    totalCount?: number;
}) {
    return (
        <div className="flex flex-wrap items-center gap-2">
            <GlassButton size="sm" disabled={loading} onClick={onRefresh}>
                {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                Refresh
            </GlassButton>
            <GlassButton size="sm" disabled={loading || !hasPrevious} onClick={onPrevious}>
                <ChevronLeft size={14} />
                Previous page
            </GlassButton>
            <GlassButton size="sm" disabled={loading || !hasNext} onClick={onNext}>
                Next {nextLabel} page
                <ChevronRight size={14} />
            </GlassButton>
            {totalCount !== undefined ? (
                <span className="text-xs text-text-3">{totalCount} total</span>
            ) : null}
        </div>
    );
}

function DetailLine({ label, children }: { label: string; children: ReactNode }) {
    return (
        <p className="min-w-0 break-words text-xs text-text-3">
            <span className="font-medium text-text-2">{label}:</span> {children}
        </p>
    );
}

function ConsumedInputs({ inputs }: { inputs?: WorkflowConsumedInput[] }) {
    if (!inputs?.length) {
        return null;
    }
    return (
        <div className="space-y-1">
            <p className="text-xs font-medium text-text-2">Consumed producer refs</p>
            <ul className="space-y-1" aria-label="Consumed producer references">
                {inputs.map((input, index) => (
                    <li key={`${text(input.input_name)}:${index}`} className="min-w-0 break-words rounded-lg bg-surface-sunken p-2 text-xs text-text-3">
                        {consumedInputSummary(input, index)}
                        {input.result_ref ? <DetailLine label="Consumed manifest ref">{resultReferenceSummary(input.result_ref)}</DetailLine> : null}
                        {input.output_ref ? <DetailLine label="Consumed output ref">
                            {typeof input.output_ref === 'string' ? input.output_ref : resultReferenceSummary(input.output_ref)}
                        </DetailLine> : null}
                    </li>
                ))}
            </ul>
        </div>
    );
}

function V3ResultExcerpt({
    scope,
    workflowId,
    runId,
    executionId,
    attempt,
}: {
    scope: WorkflowScope;
    workflowId: string;
    runId: string;
    executionId: string;
    attempt: number;
}) {
    const [page, setPage] = useState<WorkflowRunResultPage | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [requested, setRequested] = useState(false);
    const abortRef = useRef<AbortController | null>(null);
    const tokenRef = useRef(0);

    const load = (nextOffset = 0) => {
        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;
        tokenRef.current += 1;
        const token = tokenRef.current;
        setLoading(true);
        setPage(null);
        setError('');
        setRequested(true);
        void fetchWorkflowExecutionAttemptResult(
            scope,
            workflowId,
            runId,
            executionId,
            attempt,
            nextOffset,
            2000,
            controller.signal,
        )
            .then((result) => {
                if (controller.signal.aborted || token !== tokenRef.current) {
                    return;
                }
                setPage(result);
            })
            .catch((cause: unknown) => {
                if (controller.signal.aborted || token !== tokenRef.current) {
                    return;
                }
                setError(historyErrorMessage(cause, 'Could not load the execution result excerpt.'));
                setPage(null);
            })
            .finally(() => {
                if (controller.signal.aborted || token !== tokenRef.current) {
                    return;
                }
                setLoading(false);
            });
    };

    useEffect(() => () => abortRef.current?.abort(), []);

    return (
        <div className="space-y-2 rounded-xl border border-edge p-3">
            <div className="flex flex-wrap items-center gap-2">
                <GlassButton size="sm" disabled={loading} onClick={() => load()}>
                    {loading ? <Loader2 size={14} className="animate-spin" /> : <FileJson size={14} />}
                    {requested ? 'Reload authoritative output excerpt' : 'Load authoritative output excerpt'}
                </GlassButton>
                {page?.next_offset !== null && page?.next_offset !== undefined ? (
                    <GlassButton size="sm" disabled={loading} onClick={() => load(Number(page.next_offset))}>
                        Next output excerpt page
                    </GlassButton>
                ) : null}
            </div>
            <p className="text-xs text-text-3">
                V3 output inspection always reads the exact execution attempt's authoritative output.
            </p>
            {error ? <p role="alert" className="text-xs text-danger">{error}</p> : null}
            {page ? (
                <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-surface-sunken p-3 text-xs text-text-2">
                    {page.content}
                </pre>
            ) : null}
            {page ? (
                <p className="break-words text-[11px] text-text-3">
                    Offset {page.offset ?? 0}
                    {page.total_bytes !== undefined ? ` of ${page.total_bytes} bytes` : ''}
                    {page.sha256 ? ` · sha256 ${page.sha256}` : ''}
                </p>
            ) : null}
        </div>
    );
}

function AttemptHistory({
    scope,
    workflowId,
    runId,
    execution,
}: {
    scope: WorkflowScope;
    workflowId: string;
    runId: string;
    execution: WorkflowExecutionRecord;
}) {
    const loadPage = useCallback((cursor: string | null, signal: AbortSignal) =>
        fetchWorkflowExecutionAttemptsPage(scope, workflowId, runId, execution.execution_id, cursor, 50, signal),
    [execution.execution_id, runId, scope, workflowId]);
    const page = usePagedResource<WorkflowExecutionAttemptRecord>(loadPage, 'Could not load execution attempts.');

    return (
        <div className="space-y-3">
            <PageControls
                loading={page.loading}
                onRefresh={page.refresh}
                onPrevious={page.previous}
                onNext={page.next}
                hasPrevious={page.previousCursors.length > 0}
                hasNext={Boolean(page.nextCursor)}
                nextLabel="attempt"
                totalCount={page.totalCount}
            />
            {page.loading ? <p role="status" className="text-xs text-text-3">Loading execution attempts...</p> : null}
            {page.error ? <p role="alert" className="rounded-xl bg-danger-soft p-3 text-xs text-danger">{page.error}</p> : null}
            {!page.loading && !page.error && !page.items.length ? <p className="text-xs text-text-3">No attempts were recorded for this execution.</p> : null}
            <ul className="space-y-2" aria-label={`Attempts for execution ${execution.execution_id}`}>
                {page.items.map((attempt) => {
                    const validation = validationSummary(attempt.workflow_validation);
                    const resultSummary = resultReferenceSummary(attempt.workflow_result?.result_ref);
                    const inputs = attempt.consumed_inputs ?? attempt.workflow_result?.consumed_inputs;
                    return (
                        <li key={`${attempt.execution_id}:${attempt.attempt}`} className="space-y-2 rounded-xl border border-edge p-3">
                            <div className="flex flex-wrap items-center gap-2">
                                <Pill tone={statusTone(attempt.state)}>{attempt.state || 'unknown'}</Pill>
                                <span className="text-sm font-medium text-text-1">Attempt {attempt.attempt}</span>
                                {attempt.started_at ? <span className="text-xs text-text-3">{formatTimestamp(attempt.started_at)}</span> : null}
                                {attempt.completed_at ? <span className="text-xs text-text-3">→ {formatTimestamp(attempt.completed_at)}</span> : null}
                            </div>
                            {validation ? <DetailLine label="Validation"><Pill tone={validationTone(attempt.workflow_validation)}>{validation}</Pill></DetailLine> : null}
                            {resultSummary ? <DetailLine label="Result ref">{resultSummary}</DetailLine> : null}
                            <ConsumedInputs inputs={inputs} />
                            {attempt.workflow_result?.result_ref ? <V3ResultExcerpt
                                key={`${workflowId}:${runId}:${attempt.execution_id}:${attempt.attempt}`}
                                scope={scope}
                                workflowId={workflowId}
                                runId={runId}
                                executionId={attempt.execution_id}
                                attempt={attempt.attempt}
                            /> : <p className="text-xs text-text-3">No result was committed for this attempt.</p>}
                        </li>
                    );
                })}
            </ul>
        </div>
    );
}

function DecisionHistory({
    scope,
    workflowId,
    runId,
}: {
    scope: WorkflowScope;
    workflowId: string;
    runId: string;
}) {
    const loadPage = useCallback((cursor: string | null, signal: AbortSignal) =>
        fetchWorkflowRuntimeDecisionsPage(scope, workflowId, runId, cursor, 50, signal),
    [runId, scope, workflowId]);
    const page = usePagedResource<WorkflowRuntimeDecisionRecord>(loadPage, 'Could not load runtime decisions.');

    return (
        <details className="rounded-xl border border-edge p-3" open>
            <summary className="cursor-pointer text-sm font-medium text-text-1">Runtime decision history</summary>
            <div className="mt-3 space-y-3">
                <PageControls
                    loading={page.loading}
                    onRefresh={page.refresh}
                    onPrevious={page.previous}
                    onNext={page.next}
                    hasPrevious={page.previousCursors.length > 0}
                    hasNext={Boolean(page.nextCursor)}
                    nextLabel="decision"
                    totalCount={page.totalCount}
                />
                {page.error ? <p role="alert" className="rounded-xl bg-danger-soft p-3 text-xs text-danger">{page.error}</p> : null}
                {page.loading && !page.items.length ? <p role="status" className="text-xs text-text-3">Loading runtime decisions…</p> : null}
                {!page.loading && !page.error && !page.items.length ? (
                    <p className="text-xs text-text-3">No runtime decisions were recorded for this run.</p>
                ) : null}
                {page.items.length ? (
                    <ul className="space-y-2" aria-label="Runtime decisions">
                        {page.items.map((decision, index) => {
                            const summary = decisionSummary(decision) || 'unsupported safe decision schema';
                            const timestamp = formatTimestamp(decision.timestamp ?? decision.decided_at);
                            return (
                                <li key={`${text(decision.execution_id)}:${text(decision.gate_id)}:${index}`} className="space-y-1 rounded-lg bg-surface-sunken p-2 text-xs text-text-3">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <Pill tone="accent">{text(decision.choice) || 'decision'}</Pill>
                                        {timestamp ? <span>{timestamp}</span> : null}
                                    </div>
                                    <DetailLine label="Decision">{summary}</DetailLine>
                                    {text(decision.gate_id) ? <DetailLine label="Gate">{text(decision.gate_id)}</DetailLine> : null}
                                    {text(decision.execution_id) || text(decision.node_id) || Number.isFinite(Number(decision.attempt)) ? (
                                        <DetailLine label="Applies to">
                                            {[
                                                text(decision.execution_id) ? `execution ${text(decision.execution_id)}` : '',
                                                text(decision.node_id) ? `node ${text(decision.node_id)}` : '',
                                                Number.isFinite(Number(decision.attempt)) ? `attempt ${Number(decision.attempt)}` : '',
                                            ].filter(Boolean).join(' · ')}
                                        </DetailLine>
                                    ) : null}
                                    {text(decision.input_digest) ? <DetailLine label="Input digest">{text(decision.input_digest)}</DetailLine> : null}
                                </li>
                            );
                        })}
                    </ul>
                ) : null}
            </div>
        </details>
    );
}

export function WorkflowExecutionHistory({
    scope,
    workflowId,
    runId,
}: {
    scope: WorkflowScope;
    workflowId: string;
    runId: string;
}) {
    const [expandedExecutionId, setExpandedExecutionId] = useState<string | null>(null);
    const loadPage = useCallback((cursor: string | null, signal: AbortSignal) =>
        fetchWorkflowExecutionsPage(scope, workflowId, runId, cursor, 50, signal),
    [runId, scope, workflowId]);
    const page = usePagedResource<WorkflowExecutionRecord>(loadPage, 'Could not load workflow executions.');

    return (
        <div className="space-y-3 px-3 pb-3">
            <GlassPanel elevation="flat" className="space-y-3 p-3">
                <div className="flex flex-wrap items-center gap-2">
                    <Pill tone="accent">definition v3</Pill>
                    <span className="text-sm font-medium text-text-1">Workflow execution history</span>
                </div>
                <p className="text-xs text-text-3">
                    Structured runs use node, execution, and attempt identities. Output excerpts are loaded per attempt so large results are not rendered automatically.
                </p>
                <PageControls
                    loading={page.loading}
                    onRefresh={page.refresh}
                    onPrevious={page.previous}
                    onNext={page.next}
                    hasPrevious={page.previousCursors.length > 0}
                    hasNext={Boolean(page.nextCursor)}
                    nextLabel="executions"
                    totalCount={page.totalCount}
                />
                {page.loading ? <p role="status" className="text-xs text-text-3">Loading execution history...</p> : null}
                {page.error ? <p role="alert" className="rounded-xl bg-danger-soft p-3 text-xs text-danger">{page.error}</p> : null}
                {!page.loading && !page.error && !page.items.length ? (
                    <p className="text-xs text-text-3">No node executions were recorded for this run.</p>
                ) : null}
                {page.items.length ? (
                    <ul className="space-y-2" aria-label="Workflow node executions">
                        {page.items.map((execution) => {
                            const executionId = execution.execution_id;
                            const expanded = expandedExecutionId === executionId;
                            const validation = validationSummary(execution.workflow_validation);
                            const resultSummary = resultReferenceSummary(execution.workflow_result?.result_ref);
                            const inputs = execution.consumed_inputs ?? execution.workflow_result?.consumed_inputs;
                            const iterationPath = formatIterationPath(execution.iteration_path);
                            const decision = decisionSummary(execution.decision);
                            return (
                                <li key={executionId}>
                                    <GlassPanel elevation="flat" className="space-y-3 p-3">
                                        <div className="flex flex-wrap items-center gap-2">
                                            <RowAction
                                                icon={expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                                                label={expanded ? `Hide execution attempts for ${executionId}` : `Show execution attempts for ${executionId}`}
                                                onClick={() => setExpandedExecutionId(expanded ? null : executionId)}
                                            />
                                            <Pill tone={statusTone(execution.state)}>{execution.state || 'unknown'}</Pill>
                                            <span className="min-w-0 break-words text-sm font-medium text-text-1">
                                                {text(execution.node_id) || 'Unsupported node'} · {text(execution.node_kind) || 'unsupported kind'}
                                            </span>
                                        </div>
                                        <div className="grid gap-1 sm:grid-cols-2">
                                            <DetailLine label="Execution">{executionId}</DetailLine>
                                            <DetailLine label="Attempt">{Number.isFinite(Number(execution.attempt)) ? Number(execution.attempt) : 'unknown'}</DetailLine>
                                            {text(execution.task_id) ? <DetailLine label="Task">{text(execution.task_id)}</DetailLine> : null}
                                            {Number.isFinite(Number(execution.sequence)) ? <DetailLine label="Sequence">{Number(execution.sequence)}</DetailLine> : null}
                                            {text(execution.region_id) ? <DetailLine label="Region">{text(execution.region_id)}</DetailLine> : null}
                                            {iterationPath ? <DetailLine label="Iteration path">{iterationPath}</DetailLine> : null}
                                            {text(execution.reason_code) ? <DetailLine label="Reason code">{text(execution.reason_code)}</DetailLine> : null}
                                            {decision ? <DetailLine label="Selected branch or route">{decision}</DetailLine> : null}
                                            {validation ? <DetailLine label="Validation"><Pill tone={validationTone(execution.workflow_validation)}>{validation}</Pill></DetailLine> : null}
                                            {resultSummary ? <DetailLine label="Result ref">{resultSummary}</DetailLine> : null}
                                        </div>
                                        <ConsumedInputs inputs={inputs} />
                                        {expanded ? (
                                            <AttemptHistory
                                                scope={scope}
                                                workflowId={workflowId}
                                                runId={runId}
                                                execution={execution}
                                            />
                                        ) : null}
                                    </GlassPanel>
                                </li>
                            );
                        })}
                    </ul>
                ) : null}
            </GlassPanel>
            <DecisionHistory scope={scope} workflowId={workflowId} runId={runId} />
        </div>
    );
}
