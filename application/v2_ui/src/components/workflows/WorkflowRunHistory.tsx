// WorkflowRunHistory.tsx
// Workflow run history and task-result inspection for V2 workflows.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, FileJson, Loader2 } from 'lucide-react';
import { WorkflowExecutionHistory } from './WorkflowExecutionHistory';
import { WorkflowRuntimePanel } from './WorkflowRuntimePanel';
import { WorkflowFlowView } from './WorkflowFlowView';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { Pill, RowAction } from '../workspace/primitives';
import { useSectionResource } from '../workspace/useSectionResource';
import {
    fetchScopedWorkflowRunItems,
    fetchScopedWorkflowRuns,
    fetchWorkflowTaskResult,
    workflowScopeKey,
    type WorkflowInputOutput,
    type WorkflowRunItem,
    type WorkflowRunResultPage,
    type WorkflowRunSummary,
    type WorkflowRuntimeProjection,
    type WorkflowScope,
} from '../../lib/workflowEditor';

function statusTone(status: unknown): 'ok' | 'warn' | 'danger' | 'neutral' {
    const value = String(status ?? '').toLowerCase();
    if (['completed', 'succeeded', 'success', 'finished'].includes(value)) {
        return 'ok';
    }
    if (['running', 'queued', 'pending', 'in_progress', 'started', 'completed_partial', 'waiting_approval', 'waiting_output', 'waiting_recovery', 'paused', 'cancelling'].includes(value)) {
        return 'warn';
    }
    if (['failed', 'error', 'cancelled', 'canceled', 'incomplete', 'invalid'].includes(value)) {
        return 'danger';
    }
    return 'neutral';
}

function isTerminalStatus(status: unknown): boolean {
    const value = String(status ?? '').toLowerCase();
    return ['completed', 'succeeded', 'success', 'finished', 'failed', 'error', 'cancelled', 'canceled', 'incomplete', 'invalid', 'completed_partial'].includes(value);
}

function formatTimestamp(value: unknown): string {
    const raw = String(value ?? '');
    if (!raw) {
        return '';
    }
    const parsed = new Date(raw);
    return Number.isNaN(parsed.valueOf()) ? raw : parsed.toLocaleString();
}

function stringify(value: unknown): string {
    if (typeof value === 'string') {
        return value;
    }
    if (value === undefined || value === null) {
        return '';
    }
    try {
        return JSON.stringify(value, null, 2);
    } catch {
        return String(value);
    }
}

const VALIDATION_STATUSES = new Set(['valid', 'invalid', 'incomplete', 'accepted_partial', 'not_requested']);

function validationSummary(value: unknown): string {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return '';
    }
    const validation = value as Record<string, unknown>;
    if (validation.version !== 1 || !VALIDATION_STATUSES.has(String(validation.status))) {
        return '';
    }
    const reasonCodes = Array.isArray(validation.reason_codes)
        ? validation.reason_codes.filter((code): code is string => typeof code === 'string')
        : [];
    const counts = validation.counts && typeof validation.counts === 'object' && !Array.isArray(validation.counts)
        ? stringify(validation.counts)
        : '';
    return [String(validation.status), ...reasonCodes, counts].filter(Boolean).join(' · ');
}

function validationTone(value: unknown): 'ok' | 'warn' | 'danger' | 'neutral' {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return 'neutral';
    }
    const status = String((value as Record<string, unknown>).status ?? '');
    if (status === 'valid') {
        return 'ok';
    }
    if (status === 'invalid' || status === 'incomplete') {
        return 'danger';
    }
    if (status === 'accepted_partial') {
        return 'warn';
    }
    return 'neutral';
}

function ResultExcerpt({
    scope,
    workflowId,
    runId,
    item,
}: {
    scope: WorkflowScope;
    workflowId: string;
    runId: string;
    item: WorkflowRunItem;
}) {
    const taskId = String(item.task_id ?? item.id ?? '');
    const [output, setOutput] = useState<WorkflowInputOutput>('authoritative');
    const [page, setPage] = useState<WorkflowRunResultPage | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [requested, setRequested] = useState(false);
    const abortRef = useRef<AbortController | null>(null);
    const canLoad = Boolean(taskId);

    const load = (nextOffset = 0) => {
        if (!canLoad) {
            return;
        }
        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;
        setLoading(true);
        setError('');
        setRequested(true);
        void fetchWorkflowTaskResult(scope, workflowId, runId, taskId, output, nextOffset, 2000, controller.signal)
            .then((result) => {
                if (!controller.signal.aborted) {
                    setPage(result);
                }
            })
            .catch((cause: unknown) => {
                if (!controller.signal.aborted) {
                    setError(cause instanceof Error ? cause.message : 'Could not load the result excerpt.');
                }
            })
            .finally(() => {
                if (!controller.signal.aborted) {
                    setLoading(false);
                }
            });
    };

    useEffect(() => () => abortRef.current?.abort(), []);

    return (
        <div className="space-y-2 rounded-xl border border-edge p-3">
            <div className="flex flex-wrap items-end gap-2">
                <label className="text-xs text-text-2">
                    Result output
                    <select
                        className="mt-1 rounded-lg border border-edge bg-surface-1 px-2 py-1 text-xs text-text-1"
                        value={output}
                        onChange={(event) => {
                            abortRef.current?.abort();
                            setOutput(event.target.value as WorkflowInputOutput);
                            setPage(null);
                            setRequested(false);
                            setLoading(false);
                            setError('');
                        }}
                    >
                        <option value="authoritative">Authoritative</option>
                        <option value="text">Text</option>
                        <option value="records">Records</option>
                        <option value="json">JSON</option>
                        <option value="documents">Documents</option>
                    </select>
                </label>
                <GlassButton size="sm" disabled={loading || !canLoad} onClick={() => load()}>
                    {loading ? <Loader2 size={14} className="animate-spin" /> : <FileJson size={14} />}
                    {requested ? 'Reload excerpt' : 'Load result excerpt'}
                </GlassButton>
                {page?.next_offset !== null && page?.next_offset !== undefined ? (
                    <GlassButton size="sm" disabled={loading} onClick={() => load(Number(page.next_offset))}>
                        Next result page
                    </GlassButton>
                ) : null}
            </div>
            <p className="text-xs text-text-3">
                Result content is a transport excerpt. Large outputs are loaded only when
                requested and paged by byte offset.
            </p>
            {error ? <p role="alert" className="text-xs text-danger">{error}</p> : null}
            {page ? (
                <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-xl bg-surface-sunken p-3 text-xs text-text-2">
                    {page.content}
                </pre>
            ) : null}
            {page ? (
                <p className="text-[11px] text-text-3">
                    Output {page.output_name || output} · offset {page.offset ?? 0}
                    {page.total_bytes !== undefined ? ` of ${page.total_bytes} bytes` : ''}
                    {page.sha256 ? ` · sha256 ${page.sha256}` : ''}
                    {page.integrity ? ` · ${stringify(page.integrity)}` : ''}
                </p>
            ) : null}
        </div>
    );
}

function RunItems({
    scope,
    workflowId,
    runId,
}: {
    scope: WorkflowScope;
    workflowId: string;
    runId: string;
}) {
    const [items, setItems] = useState<WorkflowRunItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError('');
        void fetchScopedWorkflowRunItems(scope, workflowId, runId, controller.signal)
            .then((next) => {
                if (!controller.signal.aborted) {
                    setItems(next);
                }
            })
            .catch((cause: unknown) => {
                if (!controller.signal.aborted) {
                    setError(cause instanceof Error ? cause.message : 'Failed to load run tasks.');
                }
            })
            .finally(() => {
                if (!controller.signal.aborted) {
                    setLoading(false);
                }
            });
        return () => controller.abort();
    }, [runId, scope, workflowId]);

    if (loading) {
        return <p role="status" className="px-3 pb-3 text-xs text-text-3">Loading task results…</p>;
    }
    if (error) {
        return <p role="alert" className="px-3 pb-3 text-xs text-danger">{error}</p>;
    }
    const hasTypedItems = items.some((item) => typeof item.item_type === 'string');
    const taskItems = hasTypedItems ? items.filter((item) => item.item_type === 'task') : items;
    if (!taskItems.length) {
        return <p className="px-3 pb-3 text-xs text-text-3">No task results were recorded for this run.</p>;
    }

    return (
        <ul className="space-y-2 px-3 pb-3" aria-label="Workflow run task results">
            {taskItems.map((item, index) => {
                const status = String(item.status ?? 'unknown');
                const resultRef = item.workflow_result?.result_ref;
                const outputs = item.workflow_result?.outputs;
                const authoritative = item.workflow_result?.authoritative_output;
                const consumedInputs = item.consumed_inputs ?? item.workflow_result?.consumed_inputs ?? [];
                const producerSummary = consumedInputs
                    .map((input) => input.input_name || input.producer?.task_id || input.output_ref || input.output_name)
                    .filter(Boolean)
                    .join(', ');
                const audit = item.context_budget ? stringify(item.context_budget) : '';
                const validation = validationSummary(item.workflow_validation);
                return (
                    <li key={String(item.id ?? item.task_id ?? index)}>
                        <GlassPanel elevation="flat" className="space-y-2 p-3">
                            <div className="flex flex-wrap items-center gap-2">
                                <Pill tone={statusTone(status)}>{status}</Pill>
                                <span className="text-sm font-medium text-text-1">
                                    {String(item.label ?? item.task_name ?? item.task_id ?? `Task ${index + 1}`)}
                                </span>
                            </div>
                            {validation ? <p className="flex flex-wrap items-center gap-1.5 text-xs text-text-3">
                                <span>Validation:</span>
                                <Pill tone={validationTone(item.workflow_validation)}>{validation}</Pill>
                            </p> : null}
                            {producerSummary ? <p className="text-xs text-text-3">Consumed inputs: {producerSummary}</p> : null}
                            {resultRef ? <p className="text-xs text-text-3">Result ref: {stringify(resultRef)}</p> : null}
                            {outputs ? <p className="text-xs text-text-3">Outputs: {Object.keys(outputs).join(', ')}</p> : null}
                            {authoritative ? <p className="text-xs text-text-3">Authoritative output: {authoritative}</p> : null}
                            {audit ? <p className="text-xs text-text-3">Context budget: {audit}</p> : null}
                            <ResultExcerpt scope={scope} workflowId={workflowId} runId={runId} item={item} />
                        </GlassPanel>
                    </li>
                );
            })}
        </ul>
    );
}

export function WorkflowRunHistory({
    scope,
    workflowId,
    refreshToken = 0,
    onWorkflowRefresh,
}: {
    scope: WorkflowScope;
    workflowId: string;
    refreshToken?: number;
    onWorkflowRefresh?: () => void;
}) {
    const { items, loading, error, refresh } = useSectionResource<WorkflowRunSummary>(
        (signal) => fetchScopedWorkflowRuns(scope, workflowId, signal),
        'Failed to load run history.',
    );
    const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
    const [showFlow, setShowFlow] = useState(false);
    const [runtimeSnapshot, setRuntimeSnapshot] = useState<{ runId: string; runtime: WorkflowRuntimeProjection | null } | null>(null);
    const onRuntimeSnapshot = useCallback((runId: string, runtime: WorkflowRuntimeProjection | null) => {
        setRuntimeSnapshot((current) => current?.runId === runId && current.runtime === runtime ? current : { runId, runtime });
    }, []);
    const [unavailableRun, setUnavailableRun] = useState<{ id: string | null; status: number } | null>(null);
    const onAccessLost = useCallback((status: number) => {
        setUnavailableRun({ id: expandedRunId, status });
        setRuntimeSnapshot(null);
    }, [expandedRunId]);
    const shown = useMemo(() => items.slice(0, 10), [items]);

    useEffect(() => {
        if (refreshToken > 0) {
            void refresh();
        }
    }, [refresh, refreshToken]);

    useEffect(() => {
        const shouldPoll = shown.some((run) => run.durable_execution === true && !isTerminalStatus(run.status));
        if (!shouldPoll) {
            return undefined;
        }
        const timer = window.setTimeout(() => void refresh(), 2500);
        return () => window.clearTimeout(timer);
    }, [refresh, shown]);

    if (loading && !shown.length) {
        return <p role="status" className="px-3 pb-3 text-xs text-text-3">Loading runs…</p>;
    }
    if (error) {
        return <p role="alert" className="px-3 pb-3 text-xs text-danger">{error}</p>;
    }
    if (!shown.length) {
        return <p className="px-3 pb-3 text-xs text-text-3">This workflow has not run yet.</p>;
    }

    return (
        <ul className="space-y-2 px-3 pb-3" aria-label="Workflow run history">
            {shown.map((run, index) => {
                const runId = String(run.id ?? run.run_id ?? index);
                const expanded = expandedRunId === runId;
                const status = String(run.status ?? 'unknown');
                const validation = validationSummary(run.workflow_validation);
                const definitionVersion = run.definition_version;
                const isStructuredRun = definitionVersion === 3;
                const unsupportedDefinitionVersion = definitionVersion !== undefined && ![1, 2, 3].includes(definitionVersion);
                return (
                    <li key={runId} className="rounded-xl border border-edge">
                        <div className="flex items-center gap-2 p-2 text-xs text-text-3">
                            <RowAction
                                icon={expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                                label={expanded ? 'Hide run task results' : 'Show run task results'}
                                onClick={() => {
                                    setExpandedRunId(expanded ? null : runId);
                                    setUnavailableRun(null);
                                    setShowFlow(false);
                                    setRuntimeSnapshot(null);
                                }}
                            />
                            <Pill tone={statusTone(status)}>{status}</Pill>
                            <span className="min-w-0 flex-1 truncate">
                                {formatTimestamp(run.started_at) || 'Not started'}
                                {run.completed_at ? ` → ${formatTimestamp(run.completed_at)}` : ''}
                            </span>
                        </div>
                        {validation ? <p className="flex flex-wrap items-center gap-1.5 px-3 pb-2 text-xs text-text-3">
                            <span>Validation:</span>
                            <Pill tone={validationTone(run.workflow_validation)}>{validation}</Pill>
                        </p> : null}
                        {expanded ? (
                            unavailableRun?.id === runId ? (
                                <p role="alert" className="px-3 pb-3 text-xs text-danger">
                                    {unavailableRun.status === 403
                                        ? 'You no longer have access to this workflow run.'
                                        : 'This workflow run history is no longer available.'}
                                    {' '}Cached run details were removed. Reopen this run to check access again.
                                </p>
                            ) : unsupportedDefinitionVersion ? (
                                <p role="alert" className="px-3 pb-3 text-xs text-warn">
                                    This run uses workflow definition v{String(definitionVersion)}, which this inspector does not support yet.
                                </p>
                            ) : (
                                <>
                                    <WorkflowRuntimePanel
                                        key={`${workflowScopeKey(scope)}:${workflowId}:${runId}`}
                                        scope={scope}
                                        workflowId={workflowId}
                                        runId={runId}
                                        durable={run.durable_execution === true}
                                        structuredRun={isStructuredRun}
                                        onAccessLost={isStructuredRun ? onAccessLost : undefined}
                                        onRuntimeSnapshot={isStructuredRun ? onRuntimeSnapshot : undefined}
                                        onRuntimeChanged={() => {
                                            void refresh();
                                            onWorkflowRefresh?.();
                                        }}
                                    />
                                    {isStructuredRun ? <div className="px-3 pb-3">
                                        <GlassButton size="sm" aria-expanded={showFlow} onClick={() => setShowFlow((value) => !value)}>
                                            {showFlow ? 'Hide Flow for this run' : 'Show Flow for this run'}
                                        </GlassButton>
                                    </div> : null}
                                    {isStructuredRun ? (
                                        showFlow ? <div className="min-w-0 px-3 pb-3">
                                            <WorkflowFlowView key={`${workflowScopeKey(scope)}:${workflowId}:${runId}`}
                                                scope={scope} target={{ kind: 'run', workflowId, runId }}
                                                runtime={runtimeSnapshot?.runId === runId ? runtimeSnapshot.runtime : null}
                                                onAccessLost={onAccessLost} />
                                        </div> :
                                        <WorkflowExecutionHistory key={`${workflowScopeKey(scope)}:${workflowId}:${runId}`}
                                            scope={scope} workflowId={workflowId} runId={runId} onAccessLost={onAccessLost} />
                                    ) : (
                                        <RunItems scope={scope} workflowId={workflowId} runId={runId} />
                                    )}
                                </>
                            )
                        ) : null}
                    </li>
                );
            })}
        </ul>
    );
}
