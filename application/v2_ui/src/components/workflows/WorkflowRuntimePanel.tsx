// WorkflowRuntimePanel.tsx
// Durable workflow runtime state, gates and run memory for V2 workflows.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Ban, Check, Loader2, RotateCcw, X } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import {
    cancelScopedWorkflow,
    decideWorkflowRuntime,
    fetchWorkflowRuntime,
    resumeWorkflowRuntime,
    workflowErrorMessage,
    workflowScopeKey,
    WORKFLOW_RUNTIME_TERMINAL_STATES,
    type WorkflowRuntimeDecisionChoice,
    type WorkflowRuntimeGate,
    type WorkflowRuntimeMemory,
    type WorkflowRuntimeProjection,
    type WorkflowScope,
} from '../../lib/workflowEditor';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { Pill } from '../workspace/primitives';
import { WorkflowPublicationDetails } from './WorkflowPublicationDetails';

function runtimeTone(state: string): 'ok' | 'warn' | 'danger' | 'neutral' | 'accent' {
    if (state === 'completed') {
        return 'ok';
    }
    if (state === 'completed_partial' || state.startsWith('waiting_') || state === 'paused') {
        return 'warn';
    }
    if (['failed', 'invalid', 'incomplete', 'cancelled', 'cancelling'].includes(state)) {
        return 'danger';
    }
    if (state === 'queued' || state === 'running') {
        return 'accent';
    }
    return 'neutral';
}

function runtimeIsTerminal(runtime: WorkflowRuntimeProjection | null): boolean {
    return runtime ? WORKFLOW_RUNTIME_TERMINAL_STATES.has(runtime.state) : true;
}

function safeUuid(): string {
    const cryptoApi = globalThis.crypto;
    if (cryptoApi?.randomUUID) {
        return cryptoApi.randomUUID();
    }
    if (!cryptoApi?.getRandomValues) {
        throw new Error('Secure random values are required for runtime decisions.');
    }
    const bytes = new Uint8Array(16);
    cryptoApi.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, '0'));
    return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10).join('')}`;
}

function formatTimestamp(value: unknown): string {
    const raw = String(value ?? '');
    if (!raw) {
        return '';
    }
    const parsed = new Date(raw);
    return Number.isNaN(parsed.valueOf()) ? raw : parsed.toLocaleString();
}

function safeJson(value: unknown): string {
    return JSON.stringify(value, null, 2) ?? 'null';
}

function formatIterationPath(path: WorkflowRuntimeGate['iteration_path']): string {
    if (!Array.isArray(path) || !path.length) {
        return '';
    }
    return path.map((frame, index) => {
        const loop = String(frame.loop_id || `region ${index + 1}`);
        const labels = [
            frame.item_id ? `item ${frame.item_id}` : '',
            frame.index !== undefined ? `index ${frame.index}` : '',
        ].filter(Boolean);
        return labels.length ? `${loop} (${labels.join(', ')})` : loop;
    }).join(' / ');
}

function gateReference(gate: WorkflowRuntimeGate | undefined): string {
    if (!gate) {
        return '';
    }
    const path = formatIterationPath(gate.iteration_path);
    const parts = [
        gate.execution_id ? `Execution ${gate.execution_id}` : '',
        gate.node_id ? `Node ${gate.node_id}` : '',
        gate.attempt !== undefined ? `Attempt ${gate.attempt}` : '',
        path ? `Path ${path}` : '',
    ].filter(Boolean);
    return parts.join(' · ');
}

function RuntimeMemoryDetails({
    memory,
    schemaVersion,
    structuredRun = false,
}: {
    memory?: WorkflowRuntimeMemory;
    schemaVersion?: number;
    structuredRun?: boolean;
}) {
    if (schemaVersion !== undefined && ![1, 2].includes(schemaVersion)) {
        return (
            <p role="alert" className="rounded-xl bg-warn-soft p-3 text-xs text-warn">
                This runtime memory schema is not supported by this inspector yet.
            </p>
        );
    }
    if (structuredRun) {
        const counters = [
            ['unit_count', 'Checkpoint units'],
            ['completed_unit_count', 'Completed checkpoint units'],
            ['execution_count', 'Execution admissions'],
            ['decision_count', 'Saved decisions'],
        ].flatMap(([key, label]) => {
            const value = memory?.[key];
            return typeof value === 'number' && Number.isFinite(value) ? [{ label, value }] : [];
        });
        return (
            <details className="rounded-xl border border-edge p-3">
                <summary className="cursor-pointer text-sm font-medium text-text-1">Runtime memory summary</summary>
                <div className="mt-3 space-y-2 text-xs text-text-3">
                    <p>Exact execution, attempt, and decision histories use the paged views below. Run memory is not approval authority.</p>
                    {counters.map((item) => <p key={item.label}>{item.label}: {item.value}</p>)}
                </div>
            </details>
        );
    }
    const decisions = memory?.decisions ?? [];
    const units = memory?.units ?? [];
    const includeOtherKeys = !structuredRun && (schemaVersion === undefined || schemaVersion === 1);
    const otherKeys = includeOtherKeys
        ? Object.keys(memory ?? {}).filter((key) => !['decisions', 'units'].includes(key))
        : [];

    if (!memory || (!decisions.length && !units.length && !otherKeys.length)) {
        return <p className="text-xs text-text-3">No run memory has been recorded yet.</p>;
    }

    return (
        <details className="rounded-xl border border-edge p-3">
            <summary className="cursor-pointer text-sm font-medium text-text-1">
                {structuredRun ? 'Runtime memory summary' : 'Run memory'}
            </summary>
            <div className="mt-3 space-y-3">
                {structuredRun ? (
                    <p className="text-xs text-text-3">
                        Detailed V3 execution, attempt, and decision histories load from the paged run-inspection APIs below.
                    </p>
                ) : null}
                <div>
                    <p className="text-xs font-medium text-text-2">Checkpoint units and attempts</p>
                    {units.length ? (
                        <ul className="mt-1 space-y-1 text-xs text-text-3">
                            {units.map((unit) => (
                                <li key={`${unit.unit_id}:${unit.attempt}`} className="rounded-lg bg-surface-sunken p-2">
                                    <span className="font-medium text-text-2">{unit.unit_id}</span>
                                    {' '}· {unit.state} · attempt {unit.attempt}
                                    {unit.replay_safe !== undefined ? ` · replay safe: ${unit.replay_safe ? 'yes' : 'no'}` : ''}
                                    {unit.output_available !== undefined ? ` · output: ${unit.output_available ? 'available' : 'not ready'}` : ''}
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p className="mt-1 text-xs text-text-3">No unit attempts are available.</p>
                    )}
                </div>
                <div>
                    <p className="text-xs font-medium text-text-2">Decision history</p>
                    {decisions.length ? (
                        <ul className="mt-1 space-y-1 text-xs text-text-3">
                            {decisions.map((decision, index) => (
                                <li key={`${decision.unit_id}:${decision.choice}:${decision.decided_at ?? index}`} className="rounded-lg bg-surface-sunken p-2">
                                    <span className="font-medium text-text-2">{decision.unit_id}</span>
                                    {' '}· {decision.choice} by {decision.actor_user_id}
                                    {decision.decided_at ? ` · ${formatTimestamp(decision.decided_at)}` : ''}
                                    {decision.attempt !== undefined ? ` · attempt ${decision.attempt}` : ''}
                                    {decision.input_digest ? ` · input ${decision.input_digest}` : ''}
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p className="mt-1 text-xs text-text-3">No decisions have been recorded.</p>
                    )}
                </div>
                {otherKeys.length ? (
                    <div>
                        <p className="text-xs font-medium text-text-2">Safe runtime references</p>
                        <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-surface-sunken p-2 text-xs text-text-3">
                            {safeJson(Object.fromEntries(otherKeys.map((key) => [key, memory[key]])))}
                        </pre>
                    </div>
                ) : null}
            </div>
        </details>
    );
}

export function WorkflowRuntimePanel({
    scope,
    workflowId,
    runId,
    durable,
    structuredRun = false,
    onRuntimeChanged,
    onAccessLost,
}: {
    scope: WorkflowScope;
    workflowId: string;
    runId: string;
    durable: boolean;
    structuredRun?: boolean;
    onRuntimeChanged?: () => void;
    onAccessLost?: (status: number) => void;
}) {
    const scopeKey = workflowScopeKey(scope);
    const [enabled, setEnabled] = useState(durable);
    const [runtime, setRuntime] = useState<WorkflowRuntimeProjection | null>(null);
    const [canDecide, setCanDecide] = useState(false);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [action, setAction] = useState<string | null>(null);
    const [confirmRetry, setConfirmRetry] = useState(false);
    const [retryTarget, setRetryTarget] = useState<{ key: string; gate: WorkflowRuntimeGate } | null>(null);
    const [pollReadToken, setPollReadToken] = useState(0);
    const abortRef = useRef<AbortController | null>(null);
    const requestToken = useRef(0);
    const retryRequest = useRef<{ key: string; requestId: string } | null>(null);

    useEffect(() => {
        setEnabled(durable);
        setRuntime(null);
        setError('');
        setCanDecide(false);
        setConfirmRetry(false);
        setRetryTarget(null);
        retryRequest.current = null;
    }, [durable, runId, scopeKey, workflowId]);

    const loadRuntime = useCallback(async (showSpinner = false) => {
        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;
        requestToken.current += 1;
        const token = requestToken.current;
        if (showSpinner) {
            setLoading(true);
        }
        setError('');
        try {
            const response = await fetchWorkflowRuntime(scope, workflowId, runId, controller.signal);
            if (controller.signal.aborted || token !== requestToken.current) {
                return;
            }
            setRuntime(response.runtime);
            setCanDecide(response.can_decide === true);
        } catch (cause: unknown) {
            if (controller.signal.aborted || token !== requestToken.current) {
                return;
            }
            setCanDecide(false);
            setRuntime((current) => current?.gate?.publication ? null : current);
            if (cause instanceof ApiError && (cause.status === 403 || cause.status === 404)) {
                setRuntime(null);
                setConfirmRetry(false);
                setRetryTarget(null);
                retryRequest.current = null;
                onAccessLost?.(cause.status);
            }
            if (cause instanceof ApiError && cause.status === 404) {
                setError('No durable runtime record is available for this run.');
            } else if (cause instanceof ApiError && cause.status === 403) {
                setError('You no longer have access to this workflow runtime. Reload or ask an owner to restore access.');
            } else {
                setError(workflowErrorMessage(cause, 'Could not load workflow runtime.'));
            }
        } finally {
            if (token === requestToken.current) {
                setLoading(false);
                setPollReadToken((value) => value + 1);
            }
        }
    }, [onAccessLost, runId, scope, scopeKey, workflowId]);

    useEffect(() => {
        if (!enabled) {
            return undefined;
        }
        void loadRuntime(true);
        return () => abortRef.current?.abort();
    }, [enabled, loadRuntime]);

    useEffect(() => {
        if (!enabled || action || !runtime || runtimeIsTerminal(runtime)) {
            return undefined;
        }
        const timer = window.setTimeout(() => void loadRuntime(false), 2000);
        return () => window.clearTimeout(timer);
    }, [action, enabled, loadRuntime, pollReadToken, runtime?.state, runtime?.version]);

    const requestIdFor = (key: string) => {
        if (retryRequest.current?.key === key) {
            return retryRequest.current.requestId;
        }
        const requestId = safeUuid();
        retryRequest.current = { key, requestId };
        return requestId;
    };

    const recoveryKey = (record: WorkflowRuntimeProjection) => JSON.stringify([
        scopeKey, workflowId, runId, record.version, record.gate?.id,
        record.gate?.execution_id, record.gate?.node_id, record.gate?.attempt,
        record.gate?.input_digest,
        record.gate?.iteration_path,
    ]);

    const applyRuntimeResponse = (nextRuntime: WorkflowRuntimeProjection, nextCanDecide: boolean) => {
        setRuntime(nextRuntime);
        setCanDecide(nextCanDecide);
        retryRequest.current = null;
        onRuntimeChanged?.();
    };

    const clearRuntimeAfterPermissionLoss = (status = 403) => {
        retryRequest.current = null;
        setRuntime(null);
        setCanDecide(false);
        setConfirmRetry(false);
        setRetryTarget(null);
        setError(status === 404 ? 'No durable runtime record is available for this run.'
            : 'You no longer have access to this workflow runtime. Reload or ask an owner to restore access.');
        onAccessLost?.(status);
    };

    const decide = async (choice: WorkflowRuntimeDecisionChoice) => {
        if (action) return;
        if (choice === 'retry' && (!runtime?.gate || !retryTarget || retryTarget.key !== recoveryKey(runtime) || runtime.gate.kind !== 'recovery' || !canDecide)) {
            setConfirmRetry(false);
            setRetryTarget(null);
            setError('The recovery gate changed while you were reviewing it. Review the current execution and attempt before retrying.');
            return;
        }
        if (!runtime?.gate || !canDecide || !runtime.gate.choices.includes(choice) ||
            runtime.gate.publication && ['approve', 'reject', 'retry'].includes(choice)) {
            setError('The gate is no longer available. Reload this run before making another decision.');
            return;
        }
        abortRef.current?.abort();
        const gate = runtime.gate;
        const requestKey = JSON.stringify([
            'decision',
            runId,
            runtime.version,
            gate.id,
            gate.execution_id ?? '',
            gate.node_id ?? '',
            gate.attempt ?? '',
            gate.iteration_path ?? [],
            gate.input_digest ?? '',
            choice,
        ]);
        const requestId = requestIdFor(requestKey);
        setAction(choice);
        setError('');
        try {
            const response = await decideWorkflowRuntime(scope, workflowId, runId, {
                expected_version: runtime.version,
                gate_id: gate.id,
                choice,
                request_id: requestId,
            });
            applyRuntimeResponse(response.runtime, response.can_decide === true);
        } catch (cause: unknown) {
            if (cause instanceof ApiError && cause.status === 409) {
                retryRequest.current = null;
                await loadRuntime(true);
                setError('Runtime changed before your decision was applied. Review the current gate and click again.');
            } else if (cause instanceof ApiError && (cause.status === 403 || cause.status === 404)) {
                clearRuntimeAfterPermissionLoss(cause.status);
            } else {
                const message = cause instanceof Error && cause.message
                    ? cause.message
                    : 'Could not send the runtime decision.';
                setError(`${message} Retry uses the same request id for this gate.`);
            }
        } finally {
            setAction(null);
            setConfirmRetry(false);
            setRetryTarget(null);
        }
    };

    const resume = async () => {
        if (!runtime || action) {
            return;
        }
        abortRef.current?.abort();
        const requestKey = `resume:${runId}:${runtime.version}`;
        const requestId = requestIdFor(requestKey);
        setAction('resume');
        setError('');
        try {
            const response = await resumeWorkflowRuntime(scope, workflowId, runId, {
                expected_version: runtime.version,
                request_id: requestId,
            });
            applyRuntimeResponse(response.runtime, response.can_decide === true);
        } catch (cause: unknown) {
            if (cause instanceof ApiError && cause.status === 409) {
                retryRequest.current = null;
                await loadRuntime(true);
                setError('Runtime changed before your resume request was applied. Review the current runtime and click again.');
            } else if (cause instanceof ApiError && (cause.status === 403 || cause.status === 404)) {
                clearRuntimeAfterPermissionLoss(cause.status);
            } else {
                const message = cause instanceof Error && cause.message
                    ? cause.message
                    : 'Could not resume this workflow run.';
                setError(`${message} Retry uses the same request id.`);
            }
        } finally {
            setAction(null);
        }
    };

    const cancel = async () => {
        if (action) {
            return;
        }
        abortRef.current?.abort();
        setAction('cancel');
        setError('');
        try {
            await cancelScopedWorkflow(scope, workflowId);
            await loadRuntime(true);
            onRuntimeChanged?.();
        } catch (cause: unknown) {
            if (cause instanceof ApiError && (cause.status === 403 || cause.status === 404)) {
                clearRuntimeAfterPermissionLoss(cause.status);
            } else setError(workflowErrorMessage(cause, 'Could not cancel this workflow run.'));
        } finally {
            setAction(null);
        }
    };

    const gate = runtime?.gate;
    const unsupportedRuntimeSchema = Boolean(runtime && runtime.schema_version !== undefined && ![1, 2].includes(runtime.schema_version));
    const gateAllows = (choice: WorkflowRuntimeDecisionChoice) =>
        Boolean(gate?.choices.includes(choice) &&
            (!gate.publication || !['approve', 'reject', 'retry'].includes(choice)));
    const progressLabel = useMemo(() => {
        if (!runtime?.progress) {
            return '';
        }
        return `${runtime.progress.completed} of ${runtime.progress.total} units complete`;
    }, [runtime?.progress]);
    const canMutate = canDecide && Boolean(runtime) && !loading && !unsupportedRuntimeSchema;
    const canResume = canMutate && runtime?.can_resume === true &&
        ['failed', 'incomplete', 'invalid'].includes(runtime.state);
    const canCancel = canMutate && runtime && !gateAllows('cancel') ? !runtimeIsTerminal(runtime) : false;

    if (!enabled) {
        return (
            <div className="px-3 pb-3">
                <GlassButton size="sm" onClick={() => setEnabled(true)}>Show runtime</GlassButton>
            </div>
        );
    }

    return (
        <div className="px-3 pb-3">
            <GlassPanel elevation="flat" className="space-y-3 p-3">
                <div className="flex flex-wrap items-center gap-2">
                    <Pill tone={runtimeTone(runtime?.state ?? 'loading')}>
                        {runtime?.state ?? 'runtime'}
                    </Pill>
                    {runtime?.phase ? <span className="text-xs text-text-3">Phase: {runtime.phase}</span> : null}
                    {runtime ? <span className="text-xs text-text-3">Version {runtime.version}</span> : null}
                    {loading ? <Loader2 size={14} className="animate-spin text-text-3" /> : null}
                </div>
                {progressLabel ? <p className="text-xs text-text-3">{progressLabel}</p> : null}
                {runtime?.loop_progress ? (
                    <section aria-label="Frozen loop progress" className="space-y-1 rounded-lg border border-edge p-3 text-xs text-text-3">
                        <p className="break-words font-medium text-text-2">For each {runtime.loop_progress.loop_id}</p>
                        <p className="break-all">Loop execution: {runtime.loop_progress.loop_execution_id}</p>
                        <p>Frozen selected count: {runtime.loop_progress.total} · admitted limit: {runtime.loop_progress.limit}
                            {runtime.loop_progress.current_index !== null ? ` · current item index: ${runtime.loop_progress.current_index}` : ''}</p>
                        <p>Completed: {runtime.loop_progress.completed}
                            {runtime.loop_progress.completed_empty !== undefined ? ` · completed empty: ${runtime.loop_progress.completed_empty}` : ''}
                            {' '}· skipped: {runtime.loop_progress.skipped} · failed: {runtime.loop_progress.failed} · pending: {runtime.loop_progress.pending}</p>
                        <p>These are this run's frozen policy and item outcomes, not current workspace search counts. Later admin changes do not rewrite them.</p>
                    </section>
                ) : null}
                {structuredRun && runtime?.limits ? (
                    <p className="text-xs text-text-3">
                        {runtime.limits.admitted_count} of {runtime.limits.max_executions} execution admissions used.
                        {' '}Deadline: {formatTimestamp(runtime.limits.deadline_at)} (including waits).
                    </p>
                ) : null}
                {error ? <p role="alert" className="rounded-xl bg-danger-soft p-3 text-xs text-danger">{error}</p> : null}
                {runtime && !canDecide ? (
                    <p className="rounded-xl bg-warn-soft p-3 text-xs text-warn">
                        You can view this runtime, but you do not have permission to approve, reject, retry, resume or cancel it.
                    </p>
                ) : null}
                {unsupportedRuntimeSchema ? (
                    <p role="alert" className="rounded-xl bg-warn-soft p-3 text-xs text-warn">
                        This runtime schema is not supported by this inspector yet.
                    </p>
                ) : null}
                {gate && !unsupportedRuntimeSchema ? (
                    <div className="space-y-2 rounded-xl border border-edge p-3">
                        <div className="flex flex-wrap items-center gap-2">
                            <Pill tone={gate.kind === 'output' ? 'warn' : 'accent'}>{gate.kind}</Pill>
                            <span className="text-sm font-medium text-text-1">Blocked on {gate.unit_id || 'runtime gate'}</span>
                        </div>
                        {gateReference(gate) ? <p className="break-words text-xs text-text-3">{gateReference(gate)}</p> : null}
                        {gate.reason ? <p className="text-xs text-text-2">{gate.reason}</p> : null}
                        <WorkflowPublicationDetails publication={gate.publication} />
                        {gate.input_digest && !gate.publication ? <p className="text-xs text-text-3">Input digest: {gate.input_digest}</p> : null}
                        {gate.kind === 'output' ? (
                            <p className="rounded-xl bg-warn-soft p-3 text-xs text-warn">
                                {gate.publication ? 'Waiting for the requested publication completion level.' : 'Waiting for required output.'}
                                {' '}Approval and retry are not available for this gate.
                            </p>
                        ) : null}
                        {canMutate && gate.kind === 'approval' ? (
                            <div className="flex flex-wrap gap-2">
                                {gateAllows('approve') ? (
                                    <GlassButton size="sm" variant="primary" disabled={Boolean(action)} onClick={() => void decide('approve')}>
                                        {action === 'approve' ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                                        Approve task
                                    </GlassButton>
                                ) : null}
                                {gateAllows('reject') ? (
                                    <GlassButton size="sm" variant="danger" disabled={Boolean(action)} onClick={() => void decide('reject')}>
                                        {action === 'reject' ? <Loader2 size={14} className="animate-spin" /> : <X size={14} />}
                                        Reject task
                                    </GlassButton>
                                ) : null}
                            </div>
                        ) : null}
                        {canMutate && gate.kind === 'recovery' ? (
                            <div className="flex flex-wrap gap-2">
                                {gateAllows('retry') ? (
                                    <GlassButton size="sm" variant="primary" disabled={Boolean(action)} onClick={() => {
                                        if (runtime) {
                                            setRetryTarget({ key: recoveryKey(runtime), gate: structuredClone(gate) });
                                            setConfirmRetry(true);
                                        }
                                    }}>
                                        {action === 'retry' ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
                                        Retry task
                                    </GlassButton>
                                ) : null}
                                {gateAllows('cancel') ? (
                                    <GlassButton size="sm" variant="danger" disabled={Boolean(action)} onClick={() => void decide('cancel')}>
                                        {action === 'cancel' ? <Loader2 size={14} className="animate-spin" /> : <Ban size={14} />}
                                        Cancel run
                                    </GlassButton>
                                ) : null}
                            </div>
                        ) : null}
                        {canMutate && gate.kind === 'pause' ? (
                            <div className="flex flex-wrap gap-2">
                                {gateAllows('resume') ? (
                                    <GlassButton size="sm" variant="primary" disabled={Boolean(action)} onClick={() => void decide('resume')}>
                                        {action === 'resume' ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                                        {gate.publication ? 'Resume / check again' : 'Resume run'}
                                    </GlassButton>
                                ) : null}
                                {gateAllows('cancel') ? (
                                    <GlassButton size="sm" variant="danger" disabled={Boolean(action)} onClick={() => void decide('cancel')}>
                                        {action === 'cancel' ? <Loader2 size={14} className="animate-spin" /> : <Ban size={14} />}
                                        Cancel run
                                    </GlassButton>
                                ) : null}
                            </div>
                        ) : null}
                    </div>
                ) : null}
                <div className="flex flex-wrap gap-2">
                    {canResume ? (
                        <GlassButton size="sm" variant="primary" disabled={Boolean(action)} onClick={() => void resume()}>
                            {action === 'resume' ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
                            Resume run
                        </GlassButton>
                    ) : null}
                    {canCancel ? (
                        <GlassButton size="sm" variant="danger" disabled={Boolean(action)} onClick={() => void cancel()}>
                            {action === 'cancel' ? <Loader2 size={14} className="animate-spin" /> : <Ban size={14} />}
                            Cancel run
                        </GlassButton>
                    ) : null}
                </div>
                <RuntimeMemoryDetails
                    memory={runtime?.memory}
                    schemaVersion={runtime?.schema_version}
                    structuredRun={structuredRun}
                />
            </GlassPanel>
            {confirmRetry ? (
                <ConfirmDialog
                    title="Retry task?"
                    description="External effects may have occurred before this checkpoint. Retry only if repeating the task is acceptable."
                    confirmLabel="Retry task"
                    confirmIcon={<AlertTriangle size={14} />}
                    cancelLabel="Keep waiting"
                    busy={action === 'retry'}
                    tone="primary"
                    onClose={() => {
                        setConfirmRetry(false);
                        setRetryTarget(null);
                    }}
                    onConfirm={() => void decide('retry')}
                >
                    <p className="text-xs text-text-2">
                        The runtime will keep the same run id and bind this decision to the recovery gate you opened.
                    </p>
                    {retryTarget && gateReference(retryTarget.gate) ? (
                        <p className="break-words text-xs text-text-2">{gateReference(retryTarget.gate)}</p>
                    ) : null}
                </ConfirmDialog>
            ) : null}
        </div>
    );
}
