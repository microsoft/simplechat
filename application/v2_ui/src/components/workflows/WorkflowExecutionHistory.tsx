// WorkflowExecutionHistory.tsx
// Structured V3 workflow execution, attempt, decision, and output inspection.

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ChevronDown, ChevronLeft, ChevronRight, FileJson, Loader2, RefreshCw } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import {
    fetchWorkflowExecutionAttemptResult,
    fetchWorkflowExecutionAttemptsPage,
    fetchWorkflowExecutionRecordsPage,
    fetchWorkflowExecutionProvenancePage,
    fetchWorkflowExecutionsPage,
    fetchWorkflowLoopItemsPage,
    fetchWorkflowRepeatIterationsPage,
    fetchWorkflowRepeatStatePage,
    fetchWorkflowRuntimeDecisionsPage,
    workflowReportingSummary,
    type WorkflowExecutionAttemptRecord,
    type WorkflowExecutionDecisionPreview,
    type WorkflowExecutionPage,
    type WorkflowExecutionRecord,
    type WorkflowRuntimeDecisionRecord,
    type WorkflowRepeatIterationRecord,
} from '../../lib/workflowExecutionHistory';
import {
    formatWorkflowIterationPath,
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
import { WorkflowLoopSelectionDetails } from './WorkflowLoopSelectionDetails';
import { WorkflowPublicationDetails } from './WorkflowPublicationDetails';
import { WorkflowRepeatProgress } from './WorkflowRepeatProgress';
import { isRecord } from '../../lib/workspaceAuthoring';

interface PagedState<T> {
    items: T[];
    nextCursor: string | null;
    totalCount?: number;
    loading: boolean;
    error: string;
    cursor: string | null;
    previousCursors: (string | null)[];
    metadata?: WorkflowExecutionPage<T>['metadata'];
}

function statusTone(status: unknown): 'ok' | 'warn' | 'danger' | 'neutral' | 'accent' {
    const value = String(status ?? '').toLowerCase();
    if (['completed', 'completed_empty', 'succeeded', 'success', 'finished', 'valid'].includes(value)) {
        return 'ok';
    }
    if (['running', 'queued', 'pending', 'in_progress', 'started', 'waiting_approval', 'waiting_output', 'waiting_recovery', 'paused', 'skipped', 'completed_partial', 'accepted_partial'].includes(value)) {
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
    return formatWorkflowIterationPath(path);
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
        typeof decision.condition_result === 'boolean' ? `stop condition ${decision.condition_result}` : '',
        text(decision.outcome) ? `outcome ${text(decision.outcome)}` : '',
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
    onAccessLost?: (status: number) => void,
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
                    metadata: page.metadata,
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
                    metadata: undefined,
                    loading: false,
                    error: historyErrorMessage(cause, fallbackError),
                }));
                if (cause instanceof ApiError && (cause.status === 403 || cause.status === 404)) {
                    onAccessLost?.(cause.status);
                }
            });
    }, [fallbackError, loadPage, onAccessLost]);

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

function CoverageDetails({ coverage, label = 'Collection coverage' }: { coverage?: Record<string, unknown>; label?: string }) {
    if (!coverage) return null;
    return <div aria-label={label} className="text-xs text-text-3">
        {Object.entries(coverage).filter(([key, value]) =>
            ['complete', 'status', 'total', 'completed', 'completed_empty', 'skipped', 'failed', 'pending', 'missing',
                'item_count', 'record_count', 'total_items', 'completed_items', 'skipped_items', 'failed_items',
                'expected_count', 'processed_count', 'empty_count', 'skipped_count', 'failed_count', 'partial_count'].includes(key) &&
            ['boolean', 'number', 'string'].includes(typeof value))
            .map(([key, value]) => <p key={key}>{key.replaceAll('_', ' ')}: {String(value)}</p>)}
    </div>;
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

function ReportingDiagnostics({ value }: { value: unknown }) {
    if (value === undefined) return null;
    const summary = workflowReportingSummary(value);
    if (!summary) return (
        <p role="alert" className="rounded-lg bg-warn-soft p-3 text-xs text-warn">
            These saved-record processing diagnostics are unsupported. Exact result inspection remains available.
        </p>
    );
    const counts = [
        ['Saved input objects read', summary.record_count],
        ['Model-sized record pages', summary.page_count],
        ['Qualitative reduction levels', summary.reduction_levels],
        ['New model calls (this invocation)', summary.model_calls],
        ['Reused checkpoint stages', summary.checkpoint_replays],
        ['Peak estimated request tokens', summary.peak_input_tokens],
    ] as const;
    const budget = summary.context_budget;
    const capacity = [
        ['Context window capacity', budget.context_window_tokens],
        ['Maximum input capacity', budget.max_input_tokens],
        ['Maximum output capacity', budget.max_output_tokens],
    ] as const;
    const request = [
        ['Estimated request input tokens', budget.input_tokens],
        ['Available request input budget', budget.input_budget_tokens],
        ['Reserved output tokens', budget.output_reserve_tokens],
        ['Safety reserve tokens', budget.safety_tokens],
    ] as const;
    return (
        <section aria-label="Saved-record reporting diagnostics" className="min-w-0 space-y-3 rounded-xl border border-edge p-3">
            <p className="text-sm font-medium text-text-1">Saved-record processing</p>
            <DetailLine label="Processing mode">{summary.mode === 'record_pages' ? 'Bounded record pages' : 'Complete saved input (no batching)'}</DetailLine>
            {summary.accepted_subset_only ? <p className="rounded-lg bg-warn-soft p-2 text-xs text-warn">
                Accepted subset only. This explanation does not claim coverage of unresolved or unaccepted source results.
            </p> : null}
            <div className="grid min-w-0 gap-1 sm:grid-cols-2">
                {counts.map(([label, count]) => count !== undefined ? <DetailLine key={label} label={label}>{count}</DetailLine> : null)}
            </div>
            <p className="text-xs text-text-3">
                Input counts include complete document-result objects, not their flattened findings. Saved originals remain authoritative;
                original sources were not reanalyzed. New call counts apply only to this invocation; checkpoint replays reuse completed stages.
            </p>
            <div className="space-y-1 rounded-lg bg-surface-sunken p-3">
                <p className="text-xs font-medium text-text-2">Last completed or replayed stage context</p>
                {budget.model_id ? <DetailLine label="Catalog model">{budget.model_id}</DetailLine> : null}
                <DetailLine label="Limit status">{budget.limit_status ?? 'Unavailable / unverified'}</DetailLine>
                <DetailLine label="Limit source">{budget.limit_source ?? 'Unavailable'}</DetailLine>
                {budget.token_estimator ? <DetailLine label="Token estimator">{budget.token_estimator}</DetailLine> : null}
                {request.map(([label, count]) => count !== undefined && count !== null ? <DetailLine key={label} label={label}>{count}</DetailLine> : null)}
                {capacity.map(([label, count]) => <DetailLine key={label} label={label}>{count ?? 'Unknown'}</DetailLine>)}
            </div>
            <p className="text-xs text-text-3">
                This is the last stage budget, not all stages. Token estimates describe request size, not billed usage or total-run spend.
                Unknown limits are not unlimited. There is no total-run token or spending cap.
            </p>
        </section>
    );
}

function V3ResultExcerpt({
    scope,
    workflowId,
    runId,
    executionId,
    attempt,
    output = 'authoritative',
    onAccessLost,
}: {
    scope: WorkflowScope;
    workflowId: string;
    runId: string;
    executionId: string;
    attempt: number;
    output?: string;
    onAccessLost?: (status: number) => void;
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
            output,
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
                if (cause instanceof ApiError && (cause.status === 403 || cause.status === 404)) {
                    onAccessLost?.(cause.status);
                }
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
                    {requested ? 'Reload' : 'Load'} {output} output excerpt
                </GlassButton>
                {page?.next_offset !== null && page?.next_offset !== undefined ? (
                    <GlassButton size="sm" disabled={loading} onClick={() => load(Number(page.next_offset))}>
                        Next output excerpt page
                    </GlassButton>
                ) : null}
            </div>
            <p className="text-xs text-text-3">
                V3 output inspection always reads the exact execution attempt's selected {output} output. Byte excerpts may split JSON records; use Complete records for a collection.
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
    executionId,
    onAccessLost,
    inspectBoundary = false,
}: {
    scope: WorkflowScope;
    workflowId: string;
    runId: string;
    executionId: string;
    onAccessLost?: (status: number) => void;
    inspectBoundary?: boolean;
}) {
    const [boundaryOpen, setBoundaryOpen] = useState(false);
    const loadPage = useCallback((cursor: string | null, signal: AbortSignal) =>
        fetchWorkflowExecutionAttemptsPage(scope, workflowId, runId, executionId, cursor, 50, signal),
    [executionId, runId, scope, workflowId]);
    const page = usePagedResource<WorkflowExecutionAttemptRecord>(loadPage, 'Could not load execution attempts.', onAccessLost);
    const boundary = inspectBoundary ? page.items.find((attempt) =>
        attempt.node_kind === 'repeat_until' || attempt.node_kind === 'for_each') : undefined;

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
            {boundary ? <div className="min-w-0 space-y-3">
                <GlassButton size="sm" aria-expanded={boundaryOpen}
                    aria-label={`${boundaryOpen ? 'Hide' : 'Show'} ${boundary.node_kind === 'repeat_until' ? 'Repeat rounds' : 'frozen items'} for ${executionId}`}
                    onClick={() => setBoundaryOpen(!boundaryOpen)}>
                    {boundaryOpen ? 'Close nested inspection' : boundary.node_kind === 'repeat_until' ? 'Inspect nested Repeat rounds' : 'Inspect nested For each items'}
                </GlassButton>
                {boundaryOpen && !page.loading && !page.error ? boundary.node_kind === 'repeat_until' ? <RepeatIterations
                    scope={scope} workflowId={workflowId} runId={runId} executionId={executionId}
                    finalOutputAvailable={Boolean(boundary.workflow_result?.result_ref)} onAccessLost={onAccessLost} /> : <LoopItems
                    scope={scope} workflowId={workflowId} runId={runId} executionId={executionId} onAccessLost={onAccessLost} /> : null}
            </div> : null}
            <ul className="space-y-2" aria-label={`Attempts for execution ${executionId}`}>
                {page.items.map((attempt) => {
                    const validation = validationSummary(attempt.workflow_validation);
                    const resultSummary = resultReferenceSummary(attempt.workflow_result?.result_ref);
                    const inputs = attempt.consumed_inputs ?? attempt.workflow_result?.consumed_inputs;
                    const outputs = attempt.workflow_result?.outputs ?? {};
                    const collectionOutputs = [...new Set([...Object.keys(outputs), attempt.workflow_result?.authoritative_output ?? ''])]
                        .filter((name) => ['records', 'documents'].includes(name) ||
                            isRecord(outputs[name]) && ['records', 'document_results'].includes(String(outputs[name].kind)));
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
                            {attempt.iteration_path?.length ? <DetailLine label="Iteration path">{formatIterationPath(attempt.iteration_path)}</DetailLine> : null}
                            <ConsumedInputs inputs={inputs} />
                            <WorkflowPublicationDetails publication={attempt.workflow_result?.publication}
                                label={`Publication for execution ${attempt.execution_id} attempt ${attempt.attempt}`} />
                            <ReportingDiagnostics value={attempt.workflow_result?.reporting} />
                            {attempt.workflow_result?.result_ref && collectionOutputs.length ? <CompleteRecords
                                key={`records:${attempt.execution_id}:${attempt.attempt}`} scope={scope} workflowId={workflowId}
                                runId={runId} executionId={attempt.execution_id} attempt={attempt.attempt} outputs={collectionOutputs}
                                onAccessLost={onAccessLost} /> : null}
                            {attempt.workflow_result?.result_ref ? <V3ResultExcerpt
                                key={`${workflowId}:${runId}:${attempt.execution_id}:${attempt.attempt}`}
                                scope={scope}
                                workflowId={workflowId}
                                runId={runId}
                                executionId={attempt.execution_id}
                                attempt={attempt.attempt}
                                onAccessLost={onAccessLost}
                            /> : <p className="text-xs text-text-3">No result was committed for this attempt.</p>}
                        </li>
                    );
                })}
            </ul>
        </div>
    );
}

function RecordPages({ scope, workflowId, runId, executionId, attempt, output, onAccessLost }: {
    scope: WorkflowScope; workflowId: string; runId: string; executionId: string; attempt: number; output: string;
    onAccessLost?: (status: number) => void;
}) {
    const loadPage = useCallback((cursor: string | null, signal: AbortSignal) =>
        fetchWorkflowExecutionRecordsPage(scope, workflowId, runId, executionId, attempt, output, cursor, 100, signal),
    [attempt, executionId, output, runId, scope, workflowId]);
    const page = usePagedResource(loadPage, 'Could not read the complete saved records.', onAccessLost);
    const summary = validationSummary(page.metadata?.validation);
    const coverage = page.metadata?.coverage;
    return (
        <div className="space-y-3">
            <PageControls loading={page.loading} onRefresh={page.refresh} onPrevious={page.previous} onNext={page.next}
                hasPrevious={page.previousCursors.length > 0} hasNext={Boolean(page.nextCursor)} nextLabel="records" totalCount={page.totalCount} />
            <p className="text-xs text-text-3">Complete records, at most 100 per page. Pages replace each other; they are never treated as the whole collection.</p>
            {page.loading ? <p role="status" className="text-xs text-text-3">Loading complete records...</p> : null}
            {page.error ? <p role="alert" className="text-xs text-danger">{page.error}</p> : null}
            {summary ? <DetailLine label="Collection validation">{summary}</DetailLine> : null}
            <CoverageDetails coverage={coverage} />
            {!page.loading && !page.error ? (
                <ol className="max-h-96 space-y-2 overflow-auto" aria-label="Complete saved records">
                    {page.items.map((record, index) => <li key={index} className="min-w-0">
                        <p className="text-xs text-text-3">Record {(page.metadata?.recordOffset ?? 0) + index + 1}</p>
                        <pre className="whitespace-pre-wrap break-words rounded-lg bg-surface-sunken p-3 text-xs text-text-2">{JSON.stringify(record, null, 2)}</pre>
                    </li>)}
                </ol>
            ) : null}
            {!page.loading && !page.error && page.totalCount === 0 ? <p className="text-xs text-text-3">The saved collection is empty. Check its validation and coverage; empty is not the same as missing.</p> : null}
        </div>
    );
}

function CompleteRecords({ scope, workflowId, runId, executionId, attempt, outputs, onAccessLost }: {
    scope: WorkflowScope; workflowId: string; runId: string; executionId: string; attempt: number; outputs: string[];
    onAccessLost?: (status: number) => void;
}) {
    const [output, setOutput] = useState(outputs[0]);
    const [open, setOpen] = useState(false);
    const [provenanceOpen, setProvenanceOpen] = useState(false);
    return (
        <section aria-label="Complete record inspection" className="min-w-0 space-y-3 rounded-xl border border-edge p-3">
            <label className="block text-xs text-text-2">Collection representation
                <select aria-label="Complete records output" value={output} className="mt-1 w-full rounded-lg border border-edge bg-surface-1 p-2"
                    onChange={(event) => setOutput(event.target.value)}>
                    {outputs.map((name) => <option key={name} value={name}>{name}</option>)}
                </select>
            </label>
            <GlassButton size="sm" onClick={() => setOpen(!open)}>{open ? 'Close complete records' : 'Load complete records'}</GlassButton>
            {open ? <RecordPages key={`${executionId}:${attempt}:${output}`} scope={scope} workflowId={workflowId}
                runId={runId} executionId={executionId} attempt={attempt} output={output} onAccessLost={onAccessLost} /> : null}
            <GlassButton size="sm" onClick={() => setProvenanceOpen(!provenanceOpen)}>{provenanceOpen ? 'Close contributors' : 'Inspect contributors'}</GlassButton>
            {provenanceOpen ? <ContributorPages key={`contributors:${executionId}:${attempt}`} scope={scope}
                workflowId={workflowId} runId={runId} executionId={executionId} attempt={attempt} onAccessLost={onAccessLost} /> : null}
        </section>
    );
}

function ContributorPages({ scope, workflowId, runId, executionId, attempt, onAccessLost }: {
    scope: WorkflowScope; workflowId: string; runId: string; executionId: string; attempt: number;
    onAccessLost?: (status: number) => void;
}) {
    const loadPage = useCallback((cursor: string | null, signal: AbortSignal) =>
        fetchWorkflowExecutionProvenancePage(scope, workflowId, runId, executionId, attempt, cursor, 50, signal),
    [attempt, executionId, runId, scope, workflowId]);
    const page = usePagedResource(loadPage, 'Could not read the saved contributor receipts.', onAccessLost);
    return (
        <section aria-label="Paged contributor inspection" className="space-y-3">
            <PageControls loading={page.loading} onRefresh={page.refresh} onPrevious={page.previous} onNext={page.next}
                hasPrevious={page.previousCursors.length > 0} hasNext={Boolean(page.nextCursor)} nextLabel="contributors" totalCount={page.totalCount} />
            <p className="text-xs text-text-3">Exact producer receipts and zero-based record ranges, at most 50 contributors per page. These identify original data; they are not cached access grants.</p>
            {page.loading ? <p role="status" className="text-xs text-text-3">Loading contributors...</p> : null}
            {page.error ? <p role="alert" className="text-xs text-danger">{page.error}</p> : null}
            {!page.loading && !page.error && !page.items.length ? <p className="text-xs text-text-3">No contributor receipts were recorded.</p> : null}
            {page.items.length ? <ul className="space-y-2" aria-label="Saved collection contributors">
                {page.items.map((item, index) => <li key={index} className="min-w-0 space-y-1 rounded-lg bg-surface-sunken p-3">
                    <DetailLine label="Producer receipt">{consumedInputSummary(item, index)}</DetailLine>
                    {item.item_id ? <DetailLine label="Source item">{item.item_id}{item.item_index !== undefined ? ` · index ${item.item_index}` : ''}</DetailLine> : null}
                    {item.record_offset !== undefined ? <DetailLine label="Collected record offset">{item.record_offset}</DetailLine> : null}
                    {item.record_count !== undefined ? <DetailLine label="Contributed record count">{item.record_count}</DetailLine> : null}
                    {item.producer_record_offset !== undefined ? <DetailLine label="Original record offset">{item.producer_record_offset}</DetailLine> : null}
                    {item.result_ref ? <DetailLine label="Source manifest">{resultReferenceSummary(item.result_ref)}</DetailLine> : null}
                </li>)}
            </ul> : null}
        </section>
    );
}

function IterationExecutions({ executionIds, scope, workflowId, runId, onAccessLost, iterationLabel = 'item' }: {
    executionIds?: string[]; scope: WorkflowScope; workflowId: string; runId: string;
    onAccessLost?: (status: number) => void;
    iterationLabel?: 'item' | 'round';
}) {
    const [selected, setSelected] = useState<string | null>(null);
    return (
        <>
            {executionIds?.map((id) => <GlassButton key={id} size="sm" aria-label={`Inspect ${iterationLabel} execution ${id}`}
                onClick={() => setSelected(selected === id ? null : id)}><span className="break-all">Inspect execution {id}</span></GlassButton>)}
            {selected ? <AttemptHistory key={selected} scope={scope} workflowId={workflowId} runId={runId}
                executionId={selected} onAccessLost={onAccessLost} inspectBoundary /> : null}
        </>
    );
}

function LoopItems({ scope, workflowId, runId, executionId, onAccessLost }: {
    scope: WorkflowScope; workflowId: string; runId: string; executionId: string;
    onAccessLost?: (status: number) => void;
}) {
    const loadPage = useCallback((cursor: string | null, signal: AbortSignal) =>
        fetchWorkflowLoopItemsPage(scope, workflowId, runId, executionId, cursor, 50, signal),
    [executionId, runId, scope, workflowId]);
    const page = usePagedResource(loadPage, 'Could not read the frozen loop items.', onAccessLost);
    return (
        <section className="space-y-3" aria-label="Frozen item inspection">
            <PageControls loading={page.loading} onRefresh={page.refresh} onPrevious={page.previous} onNext={page.next}
                hasPrevious={page.previousCursors.length > 0} hasNext={Boolean(page.nextCursor)} nextLabel="items" totalCount={page.totalCount} />
            <p className="text-xs text-text-3">This loop instance's immutable membership, in frozen order. At most 50 items per page; an item may contribute zero, one, or many records.</p>
            {page.metadata?.frozenAt ? <DetailLine label="Frozen at">{formatTimestamp(page.metadata.frozenAt)}</DetailLine> : null}
            {page.metadata?.admittedLimit !== undefined ? <DetailLine label="Frozen admission ceiling">{page.metadata.admittedLimit}</DetailLine> : null}
            <WorkflowLoopSelectionDetails selection={page.metadata?.selection} frozen />
            {page.loading ? <p role="status" className="text-xs text-text-3">Loading frozen items...</p> : null}
            {page.error ? <p role="alert" className="text-xs text-danger">{page.error}</p> : null}
            {!page.loading && !page.error && !page.items.length ? <p className="text-xs text-text-3">No frozen items are available for this loop instance.</p> : null}
            {page.items.length ? <ul className="space-y-3" aria-label="Frozen loop items">
                {page.items.map((item) => <li key={item.item_id} className="min-w-0 space-y-2 rounded-lg border border-edge p-3">
                    <div className="flex flex-wrap items-center gap-2"><Pill tone={statusTone(item.state)}>{item.state}</Pill>
                        <span className="break-words text-sm text-text-2">{item.index + 1}. {item.label}</span></div>
                    <DetailLine label="Item ID">{item.item_id}</DetailLine>
                    <DetailLine label="Iteration path">{formatIterationPath(item.iteration_path)}</DetailLine>
                    {item.record_count !== undefined ? <DetailLine label="Output records">{item.record_count}</DetailLine> : null}
                    <IterationExecutions executionIds={item.execution_ids} scope={scope} workflowId={workflowId} runId={runId} onAccessLost={onAccessLost} />
                </li>)}
            </ul> : null}
        </section>
    );
}

function RepeatStatePages({ scope, workflowId, runId, executionId, iteration, phase, onAccessLost }: {
    scope: WorkflowScope; workflowId: string; runId: string; executionId: string; iteration: number; phase: 'before' | 'after';
    onAccessLost?: (status: number) => void;
}) {
    const loadPage = useCallback((cursor: string | null, signal: AbortSignal) =>
        fetchWorkflowRepeatStatePage(scope, workflowId, runId, executionId, iteration, phase, cursor, 50, signal),
    [executionId, iteration, phase, runId, scope, workflowId]);
    const page = usePagedResource(loadPage, 'Could not read the saved Repeat state.', onAccessLost);
    return <section aria-label={`State ${phase} round ${iteration + 1}`} className="min-w-0 space-y-3 rounded-xl border border-edge p-3">
        <p className="text-sm font-medium text-text-1">State {phase} round {iteration + 1}</p>
        <PageControls loading={page.loading} onRefresh={page.refresh} onPrevious={page.previous} onNext={page.next}
            hasPrevious={page.previousCursors.length > 0} hasNext={Boolean(page.nextCursor)} nextLabel="state" totalCount={page.totalCount} />
        <p className="text-xs text-text-3">At most 50 slot receipts per page. Values stay at their exact saved producers; content and record pages load only when requested.</p>
        {page.loading ? <p role="status" className="text-xs text-text-3">Loading saved state metadata...</p> : null}
        {page.error ? <p role="alert" className="text-xs text-danger">{page.error}</p> : null}
        {page.metadata?.stateAvailable === false ? <p role="status" className="rounded-lg bg-warn-soft p-3 text-xs text-warn">
            State {phase} this round is not committed or available yet. This is not an empty eligible result.
        </p> : null}
        {page.metadata?.partial ? <p className="rounded-lg bg-warn-soft p-3 text-xs text-warn">
            This state retains accepted partial data. Its coverage and limitations are not cleared by a later round or manual continuation.
        </p> : null}
        {page.metadata?.sourceSnapshotChanged ? <p className="text-xs text-warn">Source snapshots have changed. These are retained saved versions, with access checked on every read.</p> : null}
        <ul className="space-y-3" aria-label={`Saved state ${phase} round ${iteration + 1}`}>
            {page.items.map((slot) => {
                const source = slot.source;
                const validation = validationSummary(slot.workflow_validation);
                return <li key={slot.name} className="min-w-0 space-y-2 rounded-lg bg-surface-sunken p-3">
                    <p className="break-words text-sm font-semibold text-text-1">{slot.name} ({slot.kind.replaceAll('_', ' ')})</p>
                    <DetailLine label="State validation"><Pill tone={validationTone(slot.workflow_validation)}>{validation}</Pill></DetailLine>
                    {slot.workflow_validation.eligible === false ? <p className="text-xs text-danger">This saved output is not eligible for consumption.</p> : null}
                    <CoverageDetails coverage={slot.coverage} label={`Coverage for state ${slot.name}`} />
                    {slot.prior_coverage ? <div className="space-y-1 rounded-lg bg-warn-soft p-2">
                        <p className="text-xs font-medium text-warn">Retained coverage from earlier rounds</p>
                        <CoverageDetails coverage={slot.prior_coverage} label={`Retained prior coverage for state ${slot.name}`} />
                    </div> : null}
                    {slot.limitations.length ? <ul aria-label={`Limitations for state ${slot.name}`} className="space-y-1 text-xs text-warn">
                        {slot.limitations.map((limitation, index) => <li key={index} className="break-words">{limitation}</li>)}
                    </ul> : null}
                    <DetailLine label="Exact producer">Node {source.node_id} · execution {source.execution_id} · attempt {source.attempt} · output {source.output_name}</DetailLine>
                    {source.iteration_path.length ? <DetailLine label="Producer path">{formatIterationPath(source.iteration_path)}</DetailLine> : null}
                    {slot.kind === 'records' || slot.kind === 'document_results' ? <CompleteRecords
                        key={`records:${source.execution_id}:${source.attempt}:${source.output_name}`}
                        scope={scope} workflowId={workflowId} runId={runId} executionId={source.execution_id} attempt={source.attempt}
                        outputs={[source.output_name]} onAccessLost={onAccessLost} /> : <V3ResultExcerpt
                        key={`state:${source.execution_id}:${source.attempt}:${source.output_name}`}
                        scope={scope} workflowId={workflowId} runId={runId} executionId={source.execution_id} attempt={source.attempt}
                        output={source.output_name} onAccessLost={onAccessLost} />}
                </li>;
            })}
        </ul>
    </section>;
}

function RepeatRound({ round, scope, workflowId, runId, executionId, onAccessLost }: {
    round: WorkflowRepeatIterationRecord; scope: WorkflowScope; workflowId: string; runId: string; executionId: string;
    onAccessLost?: (status: number) => void;
}) {
    const [phase, setPhase] = useState<'before' | 'after' | null>(null);
    return <li className="min-w-0 space-y-3 rounded-lg border border-edge p-3">
        <div className="flex flex-wrap items-center gap-2">
            <Pill tone={statusTone(round.state)}>{round.state}</Pill>
            <span className="text-sm font-semibold text-text-1">Round {round.iteration + 1}</span>
        </div>
        <DetailLine label="Lifetime identity">{formatIterationPath(round.iteration_path)}</DetailLine>
        <DetailLine label="Automatic batch">{round.batch_number + 1} · {round.batch_usage} of {round.batch_size} rounds admitted</DetailLine>
        <DetailLine label="Stop condition">{round.condition_result === null ? 'Not evaluated' : round.condition_result ? 'true (satisfied)' : 'false (unmet)'}</DetailLine>
        <p className="text-xs text-text-3">State before: {round.before_available ? 'saved' : 'unavailable'}.
            {' '}State after: {round.after_available ? 'committed' : 'not committed'}.</p>
        {round.partial ? <p className="text-xs text-warn">This round retains partial coverage.</p> : null}
        <div className="flex flex-wrap gap-2">
            {(['before', 'after'] as const).map((value) => <GlassButton key={value} size="sm" aria-pressed={phase === value}
                onClick={() => setPhase(phase === value ? null : value)}>State {value} round {round.iteration + 1}</GlassButton>)}
        </div>
        {phase ? <RepeatStatePages key={`${executionId}:${round.iteration}:${phase}`}
            scope={scope} workflowId={workflowId} runId={runId} executionId={executionId} iteration={round.iteration}
            phase={phase} onAccessLost={onAccessLost} /> : null}
        <IterationExecutions executionIds={round.execution_ids} scope={scope} workflowId={workflowId} runId={runId}
            onAccessLost={onAccessLost} iterationLabel="round" />
    </li>;
}

function RepeatIterations({ scope, workflowId, runId, executionId, finalOutputAvailable, onAccessLost }: {
    scope: WorkflowScope; workflowId: string; runId: string; executionId: string; finalOutputAvailable: boolean;
    onAccessLost?: (status: number) => void;
}) {
    const [finalOpen, setFinalOpen] = useState(false);
    const loadPage = useCallback((cursor: string | null, signal: AbortSignal) =>
        fetchWorkflowRepeatIterationsPage(scope, workflowId, runId, executionId, cursor, 50, signal),
    [executionId, runId, scope, workflowId]);
    const page = usePagedResource(loadPage, 'Could not read the saved Repeat rounds.', onAccessLost);
    return <section className="min-w-0 space-y-3" aria-label="Repeat round inspection">
        <WorkflowRepeatProgress summary={page.metadata?.repeat} label="Inspected Repeat progress" />
        <PageControls loading={page.loading} onRefresh={page.refresh} onPrevious={page.previous} onNext={page.next}
            hasPrevious={page.previousCursors.length > 0} hasNext={Boolean(page.nextCursor)} nextLabel="rounds" totalCount={page.totalCount} />
        <p className="text-xs text-text-3">Lifetime rounds never reset when a person grants another batch. At most 50 rounds per page; state and saved content are read separately.</p>
        {page.loading ? <p role="status" className="text-xs text-text-3">Loading Repeat rounds...</p> : null}
        {page.error ? <p role="alert" className="text-xs text-danger">{page.error}</p> : null}
        {page.metadata?.sourceSnapshotChanged ? <p className="text-xs text-warn">Source snapshots have changed; these retained rounds are still subject to current read authorization.</p> : null}
        {!page.loading && !page.error && !page.items.length ? <p className="text-xs text-text-3">No rounds have been admitted for this Repeat execution.</p> : null}
        <ul className="space-y-3" aria-label="Repeat rounds">
            {page.items.map((round) => <RepeatRound key={round.iteration} round={round} scope={scope} workflowId={workflowId}
                runId={runId} executionId={executionId} onAccessLost={onAccessLost} />)}
        </ul>
        {finalOutputAvailable ? <GlassButton size="sm" onClick={() => setFinalOpen(!finalOpen)}>
            {finalOpen ? 'Close Repeat final outputs' : 'Inspect Repeat final outputs'}
        </GlassButton> : <p className="text-xs text-text-3">No final Repeat result has been committed. A batch-limit pause does not expose final exports.</p>}
        {finalOpen && !page.loading && !page.error ? <AttemptHistory scope={scope} workflowId={workflowId} runId={runId}
            executionId={executionId} onAccessLost={onAccessLost} /> : null}
    </section>;
}

function DecisionHistory({
    scope,
    workflowId,
    runId,
    onAccessLost,
}: {
    scope: WorkflowScope;
    workflowId: string;
    runId: string;
    onAccessLost?: (status: number) => void;
}) {
    const loadPage = useCallback((cursor: string | null, signal: AbortSignal) =>
        fetchWorkflowRuntimeDecisionsPage(scope, workflowId, runId, cursor, 50, signal),
    [runId, scope, workflowId]);
    const page = usePagedResource<WorkflowRuntimeDecisionRecord>(loadPage, 'Could not load runtime decisions.', onAccessLost);

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
                                    {decision.iteration_path?.length ? <DetailLine label="Iteration path">{formatIterationPath(decision.iteration_path)}</DetailLine> : null}
                                    {decision.choice === 'continue_repeat' ? <>
                                        <DetailLine label="Manual continuation">Explicit grant{decision.actor_user_id ? ` by ${decision.actor_user_id}` : ''}</DetailLine>
                                        {decision.request_id ? <DetailLine label="Request">{decision.request_id}</DetailLine> : null}
                                        {decision.event_id ? <DetailLine label="Audit event">{decision.event_id}</DetailLine> : null}
                                        <WorkflowRepeatProgress summary={decision.repeat} label="Repeat state at manual grant" />
                                    </> : null}
                                    {decision.iteration !== undefined ? <DetailLine label="Lifetime round">{decision.iteration + 1}</DetailLine> : null}
                                    {decision.batch_number !== undefined ? <DetailLine label="Automatic batch">{decision.batch_number + 1}</DetailLine> : null}
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
    onAccessLost,
}: {
    scope: WorkflowScope;
    workflowId: string;
    runId: string;
    onAccessLost?: (status: number) => void;
}) {
    const [expandedExecutionId, setExpandedExecutionId] = useState<string | null>(null);
    const loadPage = useCallback((cursor: string | null, signal: AbortSignal) =>
        fetchWorkflowExecutionsPage(scope, workflowId, runId, cursor, 50, signal),
    [runId, scope, workflowId]);
    const page = usePagedResource<WorkflowExecutionRecord>(loadPage, 'Could not load workflow executions.', onAccessLost);

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
                                                label={execution.node_kind === 'for_each'
                                                    ? `${expanded ? 'Hide' : 'Show'} frozen items for ${executionId}`
                                                    : execution.node_kind === 'repeat_until'
                                                        ? `${expanded ? 'Hide' : 'Show'} Repeat rounds for ${executionId}`
                                                    : `${expanded ? 'Hide' : 'Show'} execution attempts for ${executionId}`}
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
                                        <WorkflowPublicationDetails publication={execution.workflow_result?.publication}
                                            label={`Publication for execution ${executionId}`} />
                                        {expanded ? (
                                            execution.node_kind === 'for_each' ? <LoopItems key={executionId}
                                                scope={scope} workflowId={workflowId} runId={runId} executionId={executionId}
                                                onAccessLost={onAccessLost} /> : execution.node_kind === 'repeat_until' ? <RepeatIterations
                                                    key={executionId} scope={scope} workflowId={workflowId} runId={runId} executionId={executionId}
                                                    finalOutputAvailable={Boolean(execution.workflow_result?.result_ref)} onAccessLost={onAccessLost} /> : <AttemptHistory
                                                scope={scope}
                                                workflowId={workflowId}
                                                runId={runId}
                                                executionId={executionId}
                                                onAccessLost={onAccessLost}
                                            />
                                        ) : null}
                                    </GlassPanel>
                                </li>
                            );
                        })}
                    </ul>
                ) : null}
            </GlassPanel>
            <DecisionHistory scope={scope} workflowId={workflowId} runId={runId} onAccessLost={onAccessLost} />
        </div>
    );
}
