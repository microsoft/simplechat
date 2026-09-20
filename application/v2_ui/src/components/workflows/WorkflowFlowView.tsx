// WorkflowFlowView.tsx
// Source-isolated saved, draft, and frozen-run inspection over one compiled definition.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError } from '../../lib/apiClient';
import {
    fetchWorkflowFlowProjection, inspectionNodeHasExecution, inspectionNodeMatchesPath, inspectionNodePath, inspectionSourceKey,
    type WorkflowFlowProjection, type WorkflowInspectionDetails, type WorkflowInspectionTarget,
} from '../../lib/workflowInspection';
import { layoutWorkflowFlow, visibleWorkflowNode } from '../../lib/workflowFlowLayout';
import {
    fetchWorkflowExecutionForNode, fetchWorkflowExecutionsPage,
    type WorkflowExecutionPage, type WorkflowExecutionRecord,
} from '../../lib/workflowExecutionHistory';
import {
    formatWorkflowIterationPath, workflowErrorMessage, workflowScopeKey,
    type WorkflowIterationFrame, type WorkflowRuntimeProjection, type WorkflowScope,
} from '../../lib/workflowEditor';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { WorkflowDefinitionInspector } from './WorkflowDefinitionInspector';
import { WorkflowExecutionInspector } from './WorkflowExecutionInspector';
import { WorkflowFlowCanvas } from './WorkflowFlowCanvas';
import { WorkflowRepeatProgress } from './WorkflowRepeatProgress';

const sourceLabels = { saved: 'Saved definition', draft: 'Unsaved draft', run: "Run's frozen definition" };

function SelectedExecution({
    scope, workflowId, runId, nodeId, path, runtimeVersion, onUnavailable, onSelectIteration, onObserved,
}: {
    scope: WorkflowScope;
    workflowId: string;
    runId: string;
    nodeId: string;
    path: WorkflowIterationFrame[];
    runtimeVersion?: number;
    onUnavailable: (status: number) => void;
    onSelectIteration: (path: WorkflowIterationFrame[]) => void;
    onObserved: (record: WorkflowExecutionRecord | null, loaded: boolean) => void;
}) {
    const [execution, setExecution] = useState<WorkflowExecutionRecord | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [refresh, setRefresh] = useState(0);
    const pathKey = JSON.stringify(path);
    const scopeKey = workflowScopeKey(scope);
    useEffect(() => {
        const controller = new AbortController();
        setExecution(null);
        onObserved(null, false);
        setLoading(true);
        setError('');
        void fetchWorkflowExecutionForNode(scope, workflowId, runId, nodeId, path, controller.signal)
            .then((record) => {
                if (controller.signal.aborted) return;
                setExecution(record);
                onObserved(record, true);
                setLoading(false);
            })
            .catch((cause: unknown) => {
                if (controller.signal.aborted) return;
                setExecution(null);
                onObserved(null, false);
                setError(workflowErrorMessage(cause, 'Could not read the selected execution.'));
                setLoading(false);
                if (cause instanceof ApiError && [401, 403, 404, 409].includes(cause.status)) onUnavailable(cause.status);
            });
        return () => controller.abort();
    }, [scopeKey, workflowId, runId, nodeId, pathKey, runtimeVersion, refresh, onUnavailable, onObserved]);
    return <section className="min-w-0 space-y-3 border-t border-edge pt-3" aria-label="Exact selected execution">
        <h4 className="text-sm font-semibold text-text-1">Run evidence</h4>
        <p className="break-all text-xs text-text-3">Instance: {formatWorkflowIterationPath(path) || 'Root scope'}.</p>
        <GlassButton size="sm" disabled={loading} onClick={() => setRefresh((value) => value + 1)}>Refresh selected execution</GlassButton>
        {loading ? <p role="status" className="text-sm text-text-3">Reading exact execution...</p> : null}
        {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
        {!loading && !error && !execution ? <p className="text-sm text-text-3">
            No execution recorded for this node in the selected instance. This is not a successful or empty result.
        </p> : null}
        {execution ? <WorkflowExecutionInspector key={execution.execution_id}
            scope={scope} workflowId={workflowId} runId={runId} execution={execution}
            onAccessLost={onUnavailable} onSelectIteration={onSelectIteration} /> : null}
    </section>;
}

export function WorkflowFlowView({
    scope, target, runtime, onAccessLost,
}: {
    scope: WorkflowScope;
    target: WorkflowInspectionTarget;
    runtime?: WorkflowRuntimeProjection | null;
    onAccessLost?: (status: number) => void;
}) {
    const targetKey = useMemo(() => JSON.stringify(target), [target]);
    const stableTarget = useMemo(() => target, [targetKey]);
    const scopeKey = workflowScopeKey(scope);
    const [loadedProjection, setLoadedProjection] = useState<{ key: string; value: WorkflowFlowProjection } | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [refresh, setRefresh] = useState(0);
    const requestKey = useMemo(() => JSON.stringify([scopeKey, targetKey, refresh]), [scopeKey, targetKey, refresh]);
    const projection = loadedProjection?.key === requestKey ? loadedProjection.value : null;
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
    const [path, setPath] = useState<WorkflowIterationFrame[]>([]);
    const [bindingDetails, setBindingDetails] = useState<WorkflowInspectionDetails | null>(null);
    const [observedExecution, setObservedExecution] = useState<{
        key: string; value: WorkflowExecutionRecord | null; loaded: boolean;
    } | null>(null);
    const [positions, setPositions] = useState(() => new Map<string, { x: number; y: number }>());
    const [view, setView] = useState<'list' | 'flow'>(() => window.matchMedia('(max-width: 639px)').matches ? 'list' : 'flow');
    const [focusRequest, setFocusRequest] = useState<{ id: string; sequence: number } | null>(null);
    const inspectorRef = useRef<HTMLElement>(null);
    const structureRef = useRef<HTMLUListElement>(null);
    const generationRef = useRef(0);
    const sourceRef = useRef<string | null>(null);
    const knownNodes = useRef(new Set<string>());
    const [loadedOverlay, setLoadedOverlay] = useState<{ key: string; value: WorkflowExecutionPage<WorkflowExecutionRecord> } | null>(null);
    const [overlayCursor, setOverlayCursor] = useState<string | null>(null);
    const [overlayPrevious, setOverlayPrevious] = useState<(string | null)[]>([]);
    const [overlayLoading, setOverlayLoading] = useState(false);
    const [overlayError, setOverlayError] = useState('');

    const unavailable = useCallback((status: number) => {
        generationRef.current += 1;
        setLoadedProjection(null);
        setLoadedOverlay(null);
        setObservedExecution(null);
        setBindingDetails(null);
        setSelectedId(null);
        setPath([]);
        setPositions(new Map());
        setCollapsed(new Set());
        setFocusRequest(null);
        setOverlayCursor(null);
        setOverlayPrevious([]);
        knownNodes.current = new Set();
        sourceRef.current = null;
        setLoading(false);
        setError(status === 401 || status === 403 ? 'Current access to this workflow or its contributing sources could not be confirmed. Cached Flow details were removed.'
            : status === 404 ? 'This workflow inspection is no longer available. Cached Flow details were removed.'
                : 'The definition or frozen inspection source changed. Refresh Flow before inspecting it again.');
        if (status === 401 || status === 403 || status === 404) onAccessLost?.(status);
    }, [onAccessLost]);

    useEffect(() => {
        const controller = new AbortController();
        const generation = ++generationRef.current;
        setLoadedProjection(null);
        setLoadedOverlay(null);
        setObservedExecution(null);
        setBindingDetails(null);
        setLoading(true);
        setError('');
        const timer = window.setTimeout(() => {
            void fetchWorkflowFlowProjection(scope, stableTarget, controller.signal)
                .then((next) => {
                    if (controller.signal.aborted || generation !== generationRef.current) return;
                    const identity = JSON.stringify([scopeKey, next.source.scope_id, next.source.kind,
                        next.source.workflow_id, next.source.run_id, next.source.snapshot_sha256,
                        next.source.kind === 'draft' ? null : next.source.definition_revision]);
                    const ids = new Set(next.nodes.map((node) => node.id));
                    const initialCollapsed = next.nodes.filter((node) => ['for_each', 'repeat_until'].includes(node.kind)).map((node) => node.id);
                    if (sourceRef.current !== identity) {
                        setCollapsed(new Set(initialCollapsed));
                        setSelectedId(null);
                        setPath([]);
                        setPositions(new Map());
                        setFocusRequest(null);
                        setOverlayCursor(null);
                        setOverlayPrevious([]);
                    } else {
                        setCollapsed((current) => new Set([
                            ...[...current].filter((id) => ids.has(id)),
                            ...initialCollapsed.filter((id) => !knownNodes.current.has(id)),
                        ]));
                        setSelectedId((current) => current && ids.has(current) ? current : null);
                    }
                    sourceRef.current = identity;
                    knownNodes.current = ids;
                    setLoadedProjection({ key: requestKey, value: next });
                    setLoading(false);
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted || generation !== generationRef.current) return;
                    setLoadedProjection(null);
                    setLoading(false);
                    setError(workflowErrorMessage(cause, 'Could not load this Flow definition.'));
                    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) unavailable(cause.status);
                });
        }, stableTarget.kind === 'draft' ? 250 : 0);
        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [scopeKey, stableTarget, requestKey, unavailable]);

    const sourceKey = projection ? inspectionSourceKey(projection.source) : '';
    const overlayKey = useMemo(() => JSON.stringify([requestKey, sourceKey, overlayCursor, runtime?.version]),
        [requestKey, sourceKey, overlayCursor, runtime?.version]);
    const overlay = loadedOverlay?.key === overlayKey ? loadedOverlay.value : null;
    useEffect(() => {
        if (!projection || stableTarget.kind !== 'run') return;
        const controller = new AbortController();
        const generation = generationRef.current;
        setLoadedOverlay(null);
        setOverlayLoading(true);
        setOverlayError('');
        void fetchWorkflowExecutionsPage(scope, stableTarget.workflowId, stableTarget.runId, overlayCursor, 50, controller.signal)
            .then((page) => {
                if (controller.signal.aborted || generation !== generationRef.current) return;
                setLoadedOverlay({ key: overlayKey, value: page });
                setOverlayLoading(false);
            })
            .catch((cause: unknown) => {
                if (controller.signal.aborted || generation !== generationRef.current) return;
                setLoadedOverlay(null);
                setOverlayLoading(false);
                setOverlayError(workflowErrorMessage(cause, 'Could not load this execution overlay page.'));
                if (cause instanceof ApiError && [401, 403, 404, 409].includes(cause.status)) unavailable(cause.status);
            });
        return () => controller.abort();
    }, [scopeKey, stableTarget, overlayKey, unavailable]);

    const nodes = useMemo(() => new Map(projection?.nodes.map((node) => [node.id, node]) ?? []), [projection]);
    const selected = selectedId ? nodes.get(selectedId) : undefined;
    const selectedPath = selected ? inspectionNodePath(selected, path) : null;
    const executionKey = JSON.stringify([sourceKey, selectedId, selectedPath, runtime?.version]);
    const selectedExecution = observedExecution?.key === executionKey ? observedExecution.value : null;
    const onObserved = useCallback((record: WorkflowExecutionRecord | null, loaded: boolean) => {
        setObservedExecution({ key: executionKey, value: record, loaded });
    }, [executionKey]);
    const observations = useMemo(() => {
        const matching = new Map<string, WorkflowExecutionRecord>();
        for (const record of [...(overlay?.items ?? []), ...(selectedExecution ? [selectedExecution] : [])]) {
            const node = nodes.get(record.node_id);
            if (node && projection && inspectionNodeHasExecution(node, projection.root_region_id) &&
                inspectionNodeMatchesPath(node, path, record.iteration_path)) {
                matching.set(node.id, record);
            }
        }
        if (selectedId && observedExecution?.key === executionKey && observedExecution.loaded && !observedExecution.value) {
            matching.delete(selectedId);
        }
        return matching;
    }, [overlay, selectedExecution, observedExecution, executionKey, selectedId, projection, nodes, path]);
    const statuses = useMemo(() => {
        const status = new Map<string, string>();
        if (projection && stableTarget.kind === 'run') {
            for (const node of nodes.values()) {
                if (!inspectionNodeHasExecution(node, projection.root_region_id)) {
                    status.set(node.id, 'Region grouping; no separate execution');
                }
            }
        }
        for (const record of observations.values()) {
            const validation = record.workflow_validation?.status;
            status.set(record.node_id, `${record.state.replaceAll('_', ' ')}; attempt ${record.attempt}` +
                (record.workflow_validation ? `; validation ${typeof validation === 'string' ? validation.replaceAll('_', ' ') : 'unavailable'}` : ''));
        }
        if (selected && observedExecution?.key === executionKey && observedExecution.loaded && !observedExecution.value) {
            status.set(selected.id, 'No execution recorded');
        }
        const gateNode = runtime?.gate?.node_id ? nodes.get(runtime.gate.node_id) : undefined;
        if (runtime?.gate && gateNode && inspectionNodeMatchesPath(gateNode, path, runtime.gate.iteration_path)) {
            status.set(gateNode.id, `${runtime.state.replaceAll('_', ' ')}: ${runtime.gate.reason_code || runtime.gate.kind}`);
        }
        return status;
    }, [observations, observedExecution, executionKey, selected, projection, stableTarget.kind, nodes, path, runtime]);

    const selectNode = useCallback((id: string) => {
        const node = nodes.get(id);
        if (!node) {
            setBindingDetails(null);
            setError('That relationship is not part of this definition. Refresh Flow to inspect it.');
            return;
        }
        const parents: string[] = [];
        let parent = node.parent_id;
        while (parent) {
            parents.push(parent);
            parent = nodes.get(parent)?.parent_id ?? null;
        }
        setCollapsed((current) => new Set([...current].filter((value) => !parents.includes(value))));
        if (id !== selectedId) {
            setSelectedId(id);
            setObservedExecution(null);
            setBindingDetails(null);
        }
    }, [nodes, selectedId]);

    const toggleCollapse = useCallback((id: string) => {
        const next = new Set(collapsed);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        setCollapsed(next);
        if (selectedId && visibleWorkflowNode(selectedId, nodes, next) !== selectedId) {
            setSelectedId(id);
            setBindingDetails(null);
            setObservedExecution(null);
            setFocusRequest((request) => ({ id, sequence: (request?.sequence ?? 0) + 1 }));
        }
    }, [nodes, selectedId, collapsed]);

    const selectIteration = useCallback((nextPath: WorkflowIterationFrame[]) => {
        setPath(nextPath.map((frame) => ({ ...frame })));
        setObservedExecution(null);
        const loopId = nextPath.at(-1)?.loop_id;
        if (!loopId) return;
        setCollapsed((current) => new Set([...current].filter((id) => !nextPath.some((frame) => frame.loop_id === id))));
        const body = projection?.nodes.find((node) => node.kind === 'region' && node.parent_id === loopId);
        const first = body && projection?.nodes.find((node) => node.parent_id === body.id);
        if (first || body) setSelectedId((first ?? body)?.id ?? null);
        setBindingDetails(null);
    }, [projection]);

    const visibleBoxes = useMemo(() => projection ? layoutWorkflowFlow(projection, collapsed) : [], [projection, collapsed]);
    const returnToNode = useCallback(() => {
        if (!selectedId) return;
        setFocusRequest((request) => ({ id: selectedId, sequence: (request?.sequence ?? 0) + 1 }));
    }, [selectedId]);
    useEffect(() => {
        if (view !== 'list' || !focusRequest) return;
        const buttons = structureRef.current?.querySelectorAll<HTMLElement>('[data-workflow-node-id]');
        Array.from(buttons ?? []).find((button) => button.dataset.workflowNodeId === focusRequest.id)?.focus();
    }, [focusRequest, view]);
    const cancelOnly = runtime?.gate?.choices.length === 1 && runtime.gate.choices[0] === 'cancel';

    return <section className="min-w-0 space-y-4" aria-label="Workflow Flow">
        <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
                <h3 className="text-base font-semibold text-text-1">Read-only Flow</h3>
                <p aria-label="Flow source" className="text-sm text-text-2">{sourceLabels[stableTarget.kind]}</p>
            </div>
            <GlassButton size="sm" disabled={loading} onClick={() => setRefresh((value) => value + 1)}>Refresh Flow</GlassButton>
        </div>
        <p className="text-xs text-text-3">
            Edit executable steps in List. Moving, expanding, or viewing boxes does not save, run, approve, or publish anything.
            {stableTarget.kind === 'draft' ? ' This preview updates as you edit; it is not a saved definition or an execution check.' : ''}
        </p>
        {loading ? <p role="status" className="text-sm text-text-3">
            {stableTarget.kind === 'draft' ? 'Checking the current List draft...' : 'Loading authorized Flow definition...'}
        </p> : null}
        {error ? <p role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">{error}</p> : null}
        {projection ? <>
            <p className="break-all text-xs text-text-3">
                {projection.name}; definition v3; {stableTarget.kind === 'draft' ? 'preview digest' : 'revision'} {projection.source.definition_revision}.
                {projection.source.run_id ? ` Run ${projection.source.run_id}.` : ''}
            </p>
            {stableTarget.kind === 'run' ? <div className="space-y-2 rounded-lg border border-edge p-3">
                <p className="break-all text-xs text-text-2">Selected instance: {formatWorkflowIterationPath(path) || 'Root scope'}.</p>
                {path.length ? <GlassButton size="sm" onClick={() => setPath([])}>Return to root instance</GlassButton> : null}
                {runtime?.gate ? <p className={`text-xs ${cancelOnly ? 'text-danger' : 'text-warn'}`}>
                    Current run gate: {runtime.gate.reason_code || runtime.gate.kind}.
                    {cancelOnly ? ' Cancel only. Retained Repeat progress does not permit another batch.' : ' Decisions remain in the separate runtime panel.'}
                </p> : null}
                <WorkflowRepeatProgress summary={runtime?.repeat_progress} label="Run-wide retained Repeat observation" />
                {runtime?.repeat_progress ? <p className="text-xs text-text-3">
                    This retained observation belongs to the displayed Repeat execution, not every instance of that template.
                    Inspect a selected instance below for its own saved round and state.
                </p> : null}
                <p className="text-xs text-text-3">One execution page is loaded. Unrequested nodes say Not loaded; a partial page is not a whole-run summary.
                    Execution status is not output validation. Submission, approval, and indexed readiness are separate saved observations.</p>
                <div className="flex flex-wrap gap-2">
                    <GlassButton size="sm" disabled={overlayLoading || !overlayPrevious.length} onClick={() => {
                        setOverlayCursor(overlayPrevious.at(-1) ?? null);
                        setOverlayPrevious((pages) => pages.slice(0, -1));
                    }}>Previous execution overlay page</GlassButton>
                    <GlassButton size="sm" disabled={overlayLoading || !overlay?.next_cursor} onClick={() => {
                        if (overlay?.next_cursor) {
                            setOverlayPrevious((pages) => [...pages, overlayCursor]);
                            setOverlayCursor(overlay.next_cursor);
                        }
                    }}>Next execution overlay page</GlassButton>
                </div>
                {overlayLoading ? <p role="status" className="text-xs text-text-3">Loading bounded execution overlay...</p> : null}
                {overlayError ? <p role="alert" className="text-xs text-danger">{overlayError}</p> : null}
            </div> : null}
            <div role="group" aria-label="Read-only structure display" className="flex flex-wrap gap-2">
                <GlassButton size="sm" aria-pressed={view === 'list'} onClick={() => setView('list')}>Structure list</GlassButton>
                <GlassButton size="sm" aria-pressed={view === 'flow'} onClick={() => setView('flow')}>Flow diagram</GlassButton>
            </div>
            {view === 'flow' ? <WorkflowFlowCanvas
                key={projection.source.kind === 'draft' ? 'draft-layout' : sourceKey}
                projection={projection} sourceKind={projection.source.kind}
                collapsed={collapsed} selectedId={selectedId} statuses={statuses} observations={observations}
                positions={positions} setPositions={setPositions}
                details={bindingDetails} focusRequest={focusRequest} onSelect={selectNode} onCollapse={toggleCollapse}
                onInspect={() => inspectorRef.current?.focus()} /> : <div className="space-y-2">
                    <p className="text-xs text-text-3">This is the same read-only structure, not a second editable workflow.</p>
                    <ul ref={structureRef} aria-label="Read-only workflow structure" className="space-y-2">
                        {visibleBoxes.map((box) => {
                            const node = nodes.get(box.id);
                            if (!node) return null;
                            return <li key={node.id} className="min-w-0 rounded-lg border border-edge p-2">
                                <div className="flex flex-wrap items-center gap-2">
                                    <GlassButton size="sm" aria-pressed={selectedId === node.id} data-workflow-node-id={node.id}
                                        onClick={() => selectNode(node.id)}>{node.label} ({node.kind.replaceAll('_', ' ')})</GlassButton>
                                    <span className="break-all text-xs text-text-3">{statuses.get(node.id) ?? (stableTarget.kind === 'run' ? 'Not loaded' : 'Definition')}</span>
                                    {node.child_region_ids.length ? <GlassButton size="sm"
                                        aria-label={`${collapsed.has(node.id) ? 'Expand' : 'Collapse'} ${node.label}`}
                                        aria-expanded={!collapsed.has(node.id)} onClick={() => toggleCollapse(node.id)}>
                                        {collapsed.has(node.id) ? 'Expand' : 'Collapse'}
                                    </GlassButton> : null}
                                </div>
                                {node.parent_id ? <p className="break-words text-xs text-text-3">Within {nodes.get(node.parent_id)?.label}.</p> : null}
                            </li>;
                        })}
                    </ul>
                    <GlassButton size="sm" disabled={!selectedId} onClick={() => inspectorRef.current?.focus()}>Inspect selected node</GlassButton>
                </div>}
            {selected ? <section ref={inspectorRef} tabIndex={-1} aria-label="Flow node inspection"
                className="min-w-0 space-y-3 rounded-xl border border-edge p-3 focus:outline-accent">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="break-words text-base font-semibold text-text-1">{selected.label}</h3>
                    <GlassButton size="sm" onClick={returnToNode}>Return to selected node</GlassButton>
                </div>
                <p role="status" className="text-sm text-text-2">
                    {statuses.get(selected.id) ?? (stableTarget.kind === 'run' ? 'Not loaded' : 'Definition only; no run overlay')}
                </p>
                <WorkflowDefinitionInspector key={`${sourceKey}:${selected.id}`} scope={scope} target={stableTarget}
                    projection={projection} node={selected} onSelectNode={selectNode}
                    onDetailsChange={setBindingDetails} onUnavailable={unavailable} />
                {stableTarget.kind === 'run' ? !inspectionNodeHasExecution(selected, projection.root_region_id) ? <div className="space-y-2 border-t border-edge pt-3">
                    <p className="text-sm text-text-2">This region groups nodes; it has no separate execution record.
                        Inspect its enclosing control or a contained node for run evidence.</p>
                    {selected.parent_id ? <GlassButton size="sm" onClick={() => {
                        if (selected.parent_id) selectNode(selected.parent_id);
                    }}>
                        Inspect enclosing control {nodes.get(selected.parent_id)?.label}
                    </GlassButton> : null}
                </div> : selectedPath !== null ? <SelectedExecution
                    key={`${sourceKey}:${selected.id}:${JSON.stringify(selectedPath)}`}
                    scope={scope} workflowId={stableTarget.workflowId} runId={stableTarget.runId}
                    nodeId={selected.id} path={selectedPath} runtimeVersion={runtime?.version}
                    onUnavailable={unavailable} onSelectIteration={selectIteration} onObserved={onObserved} />
                    : <GlassPanel elevation="flat" className="space-y-2 p-3">
                        <p className="text-sm text-text-2">Choose an exact frozen item or Repeat round before inspecting this template node's run evidence.</p>
                        {selected.loop_ids.map((id) => <GlassButton key={id} size="sm" onClick={() => selectNode(id)}>Inspect enclosing loop {nodes.get(id)?.label ?? id}</GlassButton>)}
                    </GlassPanel> : null}
            </section> : <p className="text-sm text-text-3">Select a node to load its configuration and exact run evidence. Results and loop contents are not loaded to draw the diagram.</p>}
        </> : null}
    </section>;
}
