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
    type WorkflowRuntimeMemory,
    type WorkflowRuntimeProjection,
    type WorkflowScope,
} from '../../lib/workflowEditor';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { Pill } from '../workspace/primitives';

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

function RuntimeMemoryDetails({ memory }: { memory?: WorkflowRuntimeMemory }) {
    const decisions = memory?.decisions ?? [];
    const units = memory?.units ?? [];
    const otherKeys = Object.keys(memory ?? {}).filter((key) => !['decisions', 'units'].includes(key));

    if (!memory || (!decisions.length && !units.length && !otherKeys.length)) {
        return <p className="text-xs text-text-3">No run memory has been recorded yet.</p>;
    }

    return (
        <details className="rounded-xl border border-edge p-3">
            <summary className="cursor-pointer text-sm font-medium text-text-1">Run memory</summary>
            <div className="mt-3 space-y-3">
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
    onRuntimeChanged,
}: {
    scope: WorkflowScope;
    workflowId: string;
    runId: string;
    durable: boolean;
    onRuntimeChanged?: () => void;
}) {
    const scopeKey = workflowScopeKey(scope);
    const [enabled, setEnabled] = useState(durable);
    const [runtime, setRuntime] = useState<WorkflowRuntimeProjection | null>(null);
    const [canDecide, setCanDecide] = useState(false);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [action, setAction] = useState<string | null>(null);
    const [confirmRetry, setConfirmRetry] = useState(false);
    const [pollReadToken, setPollReadToken] = useState(0);
    const abortRef = useRef<AbortController | null>(null);
    const requestToken = useRef(0);
    const retryRequest = useRef<{ key: string; requestId: string } | null>(null);

    useEffect(() => {
        setEnabled(durable);
        setRuntime(null);
        setError('');
        setCanDecide(false);
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
            if (cause instanceof ApiError && (cause.status === 403 || cause.status === 404)) {
                setRuntime(null);
                setCanDecide(false);
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
    }, [runId, scope, scopeKey, workflowId]);

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

    const applyRuntimeResponse = (nextRuntime: WorkflowRuntimeProjection, nextCanDecide: boolean) => {
        setRuntime(nextRuntime);
        setCanDecide(nextCanDecide);
        retryRequest.current = null;
        onRuntimeChanged?.();
    };

    const clearRuntimeAfterPermissionLoss = () => {
        retryRequest.current = null;
        setRuntime(null);
        setCanDecide(false);
        setError('You no longer have access to this workflow runtime. Reload or ask an owner to restore access.');
    };

    const decide = async (choice: WorkflowRuntimeDecisionChoice) => {
        if (!runtime?.gate || action) {
            return;
        }
        abortRef.current?.abort();
        const gate = runtime.gate;
        const requestKey = `decision:${runId}:${runtime.version}:${gate.id}:${choice}`;
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
            } else if (cause instanceof ApiError && cause.status === 403) {
                clearRuntimeAfterPermissionLoss();
            } else {
                const message = cause instanceof Error && cause.message
                    ? cause.message
                    : 'Could not send the runtime decision.';
                setError(`${message} Retry uses the same request id for this gate.`);
            }
        } finally {
            setAction(null);
            setConfirmRetry(false);
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
            } else if (cause instanceof ApiError && cause.status === 403) {
                clearRuntimeAfterPermissionLoss();
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
            setError(workflowErrorMessage(cause, 'Could not cancel this workflow run.'));
        } finally {
            setAction(null);
        }
    };

    const gate = runtime?.gate;
    const gateAllows = (choice: WorkflowRuntimeDecisionChoice) =>
        Boolean(gate?.choices.includes(choice));
    const progressLabel = useMemo(() => {
        if (!runtime?.progress) {
            return '';
        }
        return `${runtime.progress.completed} of ${runtime.progress.total} units complete`;
    }, [runtime?.progress]);
    const canMutate = canDecide && Boolean(runtime) && !loading;
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
                {error ? <p role="alert" className="rounded-xl bg-danger-soft p-3 text-xs text-danger">{error}</p> : null}
                {runtime && !canDecide ? (
                    <p className="rounded-xl bg-warn-soft p-3 text-xs text-warn">
                        You can view this runtime, but you do not have permission to approve, reject, retry, resume or cancel it.
                    </p>
                ) : null}
                {gate ? (
                    <div className="space-y-2 rounded-xl border border-edge p-3">
                        <div className="flex flex-wrap items-center gap-2">
                            <Pill tone={gate.kind === 'output' ? 'warn' : 'accent'}>{gate.kind}</Pill>
                            <span className="text-sm font-medium text-text-1">Blocked on {gate.unit_id || 'runtime gate'}</span>
                        </div>
                        {gate.reason ? <p className="text-xs text-text-2">{gate.reason}</p> : null}
                        {gate.input_digest ? <p className="text-xs text-text-3">Input digest: {gate.input_digest}</p> : null}
                        {gate.kind === 'output' ? (
                            <p className="rounded-xl bg-warn-soft p-3 text-xs text-warn">Waiting for required output. Approval and retry are not available for this gate.</p>
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
                                    <GlassButton size="sm" variant="primary" disabled={Boolean(action)} onClick={() => setConfirmRetry(true)}>
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
                                        Resume run
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
                <RuntimeMemoryDetails memory={runtime?.memory} />
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
                    onClose={() => setConfirmRetry(false)}
                    onConfirm={() => void decide('retry')}
                >
                    <p className="text-xs text-text-2">
                        The runtime will keep the same run id and record this decision against the current recovery gate.
                    </p>
                </ConfirmDialog>
            ) : null}
        </div>
    );
}
