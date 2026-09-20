// WorkflowFlowAuthoring.tsx
// Canonical draft editing is separate from saved and frozen-run inspection.

import {
    useEffect, useMemo, useRef, useState, type Dispatch, type ReactNode, type SetStateAction,
} from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import {
    indexWorkflowDraft, workflowDraftBindings, workflowDraftStructure,
    type WorkflowAuthoringTarget, type WorkflowEditCommand, type WorkflowEditResult,
} from '../../lib/workflowAuthoring';
import {
    flowRegions, flowTaskIds, isFlowRegion, supportsWorkflowRepeat,
    type WorkflowFlowNode, type WorkflowTaskNode,
} from '../../lib/workflowFlow';
import { fetchWorkflowFlowProjection, type WorkflowFlowProjection } from '../../lib/workflowInspection';
import type { WorkflowExecutionRecord } from '../../lib/workflowExecutionHistory';
import {
    workflowErrorMessage, workflowScopeKey,
    type WorkflowDefinition, type WorkflowEditorOptions, type WorkflowScope, type WorkflowTask,
} from '../../lib/workflowEditor';
import { GlassButton } from '../ui/primitives';
import { WorkflowFlowCanvas } from './WorkflowFlowCanvas';
import {
    WorkflowJoinFields, WorkflowRegionOutputFields, WorkflowStructuredNodeFields, WorkflowStructuredOutputFields,
} from './WorkflowStructuredFields';

const inputClass = 'mt-1 w-full min-w-0 rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none';
const noExecutions = new Map<string, WorkflowExecutionRecord>();
const blockKinds: { kind: WorkflowFlowNode['kind']; label: string }[] = [
    { kind: 'task', label: 'Task' }, { kind: 'if', label: 'If / else' },
    { kind: 'route', label: 'Forward route' }, { kind: 'for_each', label: 'For each' },
    { kind: 'repeat_until', label: 'Repeat until' }, { kind: 'collect', label: 'Collect' },
];

export interface WorkflowAuthoringFocus {
    id: string;
    sequence: number;
    fields?: boolean;
}

interface Placement {
    action: 'add' | 'move';
    nodeId: string | null;
    regionId: string;
    beforeId: string;
    kind: WorkflowFlowNode['kind'];
}

export function WorkflowFlowAuthoring({
    workflow, options, scope, previewDefinition, selectedId, onSelect, onEdit, renderTask,
    positions, setPositions, collapsed, setCollapsed, focusRequest, disabled, onAccessLost,
}: {
    workflow: WorkflowDefinition;
    options: WorkflowEditorOptions;
    scope: WorkflowScope;
    previewDefinition: WorkflowDefinition | null;
    selectedId: string | null;
    onSelect: (id: string) => void;
    onEdit: (command: WorkflowEditCommand) => WorkflowEditResult['status'];
    renderTask: (task: WorkflowTask, node: WorkflowTaskNode, onNodeChange: (node: WorkflowTaskNode) => void) => ReactNode;
    positions: Map<string, { x: number; y: number }>;
    setPositions: Dispatch<SetStateAction<Map<string, { x: number; y: number }>>>;
    collapsed: Set<string>;
    setCollapsed: Dispatch<SetStateAction<Set<string>>>;
    focusRequest: WorkflowAuthoringFocus | null;
    disabled: boolean;
    onAccessLost: (status: number) => void;
}) {
    const model = useMemo(() => {
        try {
            return { structure: workflowDraftStructure(workflow), targets: indexWorkflowDraft(workflow), error: '' };
        } catch (cause: unknown) {
            return { structure: null, targets: new Map<string, WorkflowAuthoringTarget>(),
                error: workflowErrorMessage(cause, 'This draft structure cannot be displayed safely. Its fields have not been changed.') };
        }
    }, [workflow]);
    const [loaded, setLoaded] = useState<{ key: string; projection: WorkflowFlowProjection } | null>(null);
    const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
    const [refresh, setRefresh] = useState(0);
    const [placement, setPlacement] = useState<Placement | null>(null);
    const [canvasFocus, setCanvasFocus] = useState<{ id: string; sequence: number } | null>(null);
    const configurationRef = useRef<HTMLElement>(null);
    const placementRef = useRef<HTMLFieldSetElement>(null);
    const generation = useRef(0);
    const scopeKey = workflowScopeKey(scope);
    const candidateKey = useMemo(() => JSON.stringify(previewDefinition), [previewDefinition]);
    const candidate = useMemo(() => previewDefinition, [candidateKey]);
    const requestKey = JSON.stringify([scopeKey, candidateKey, refresh]);
    const currentRequest = useRef(requestKey);
    currentRequest.current = requestKey;
    const compiled = loaded?.key === requestKey ? loaded.projection : null;
    const previewError = failure?.key === requestKey ? failure.message : '';
    const targets = model.targets;
    const rootId = model.structure?.root_region_id ?? '';
    const selected = targets.get(selectedId ?? rootId) ?? targets.get(rootId);
    const selection = selected?.id ?? null;
    const status = compiled ? 'Compiler-validated draft' : !candidate || previewError ? 'Unvalidated draft' : 'Validating draft';
    const statuses = useMemo(() => new Map([...targets.keys()].map((id) => [id, status])), [targets, status]);
    const bindings = useMemo(() => model.structure && selection ? workflowDraftBindings(workflow, selection) : [],
        [workflow, model.structure, selection]);

    useEffect(() => {
        const controller = new AbortController();
        const token = ++generation.current;
        setLoaded(null);
        setFailure(null);
        if (!candidate) return () => controller.abort();
        const timer = window.setTimeout(() => {
            void fetchWorkflowFlowProjection(scope, { kind: 'draft', definition: candidate }, controller.signal)
                .then((projection) => {
                    if (controller.signal.aborted || token !== generation.current || currentRequest.current !== requestKey) return;
                    setLoaded({ key: requestKey, projection });
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted || token !== generation.current || currentRequest.current !== requestKey) return;
                    setLoaded(null);
                    setFailure({ key: requestKey, message: workflowErrorMessage(cause, 'The compiler preview is unavailable. Your draft has been retained.') });
                    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) onAccessLost(cause.status);
                });
        }, 250);
        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [scopeKey, candidate, requestKey, onAccessLost]);

    useEffect(() => {
        if (!selected) return;
        const parents = new Set<string>();
        let target = selected;
        while (true) {
            const parentId = target.kind === 'region' ? target.owner?.id : target.regionId;
            if (!parentId) break;
            parents.add(parentId);
            const parent = targets.get(parentId);
            if (!parent) break;
            target = parent;
        }
        setCollapsed((current) => [...current].some((id) => parents.has(id))
            ? new Set([...current].filter((id) => !parents.has(id))) : current);
    }, [selection, targets, setCollapsed]);

    useEffect(() => {
        if (!focusRequest || !targets.has(focusRequest.id)) return;
        if (focusRequest.fields) {
            const control = configurationRef.current?.querySelector<HTMLElement>('input:not(:disabled), textarea:not(:disabled), select:not(:disabled)');
            (control ?? configurationRef.current)?.focus();
        } else setCanvasFocus({ id: focusRequest.id, sequence: focusRequest.sequence });
    }, [focusRequest]);

    useEffect(() => {
        if (placement) placementRef.current?.querySelector<HTMLElement>('select')?.focus();
    }, [placement?.action, placement?.nodeId]);

    if (!model.structure || !selected) return <p role="alert" className="text-sm text-danger">{model.error || 'The draft has no selectable structure.'}</p>;
    const regions = isFlowRegion(workflow.flow) ? flowRegions(workflow.flow) : [];
    const placedRegion = placement ? targets.get(placement.regionId) : undefined;
    const placementNodes = placedRegion?.kind === 'region' ? placedRegion.region.nodes : [];
    const moveTarget = placement?.nodeId ? targets.get(placement.nodeId) : undefined;
    const allowedRegions = regions.filter((region) => {
        if (placement?.action !== 'move' || !moveTarget) return true;
        let target = targets.get(region.id);
        while (target) {
            if (target.id === moveTarget.id) return false;
            target = target.kind === 'region' ? target.owner ? targets.get(target.owner.id) : undefined
                : targets.get(target.regionId);
        }
        return true;
    });
    const openPlacement = (action: Placement['action']) => {
        const region = selected.region;
        const anchor = selected.kind === 'region' ? undefined
            : region.nodes[region.nodes.findIndex((node) => node.id === selected.node.id) + 1]?.id;
        setPlacement({ action, nodeId: action === 'move' && selected.kind === 'node' ? selected.id : null,
            regionId: region.id, beforeId: anchor ?? '', kind: 'task' });
    };
    const inspect = () => {
        const control = configurationRef.current?.querySelector<HTMLElement>('input:not(:disabled), textarea:not(:disabled), select:not(:disabled)');
        (control ?? configurationRef.current)?.focus();
        configurationRef.current?.scrollIntoView({ block: 'nearest' });
    };
    const collapse = (id: string) => {
        const next = new Set(collapsed);
        if (next.has(id)) next.delete(id);
        else {
            next.add(id);
            onSelect(id);
        }
        setCollapsed(next);
    };
    const selectedRegion = targets.get(selected.regionId);
    const inBranch = selectedRegion?.kind === 'region' && selectedRegion.owner?.kind === 'if';

    return <section className="min-w-0 space-y-4" aria-label="Workflow Flow authoring">
        <p role="status" className={`rounded-lg p-3 text-sm ${compiled ? 'bg-surface-sunken text-text-2' : 'bg-warn-soft text-text-1'}`}>
            <strong>{status}.</strong> {compiled ? 'Arrows come from the compiler for this exact draft. Nothing has been saved or executed.'
                : 'Blocks show the current authored structure, not validated execution paths. Complete the fields and resolve errors before saving.'}
        </p>
        {previewError ? <div role="alert" className="space-y-2 rounded-lg bg-danger-soft p-3 text-sm text-danger">
            <p>{previewError}</p>
            <GlassButton size="sm" onClick={() => setRefresh((value) => value + 1)}>Retry compiler preview</GlassButton>
        </div> : null}
        <div className="flex flex-wrap gap-2" role="group" aria-label="Flow editing controls">
            <GlassButton size="sm" disabled={disabled} onClick={() => openPlacement('add')}><Plus size={14} /> Add block in Flow</GlassButton>
            <GlassButton size="sm" disabled={disabled || selected.kind !== 'node'} onClick={() => openPlacement('move')}>
                Move selected block
            </GlassButton>
            <GlassButton size="sm" variant="danger"
                disabled={disabled || selected.kind !== 'node' || workflow.tasks.length - flowTaskIds(selected.node).length < 1}
                onClick={() => onEdit({ type: 'remove', nodeId: selected.id })}><Trash2 size={14} /> Remove selected block</GlassButton>
        </div>
        {placement ? <fieldset ref={placementRef} disabled={disabled} className="space-y-3 rounded-xl border border-edge p-3"
            aria-label={placement.action === 'add' ? 'Add workflow block' : 'Move workflow block'}>
            <legend className="px-1 text-sm font-semibold text-text-1">
                {placement.action === 'add' ? 'Add a block at an explicit location' : 'Move block in execution order'}
            </legend>
            {placement.action === 'move' ? <p className="break-all text-xs text-text-2">
                Moving: {moveTarget?.label ?? 'Unavailable block'} ({placement.nodeId}).
            </p> : null}
            <div className="grid min-w-0 gap-3 sm:grid-cols-3">
                {placement.action === 'add' ? <label className="text-xs text-text-2">
                    Block kind
                    <select className={inputClass} aria-label="Block kind" value={placement.kind}
                        onChange={(event) => {
                            const kind = blockKinds.find((item) => item.kind === event.target.value)?.kind;
                            if (kind) setPlacement({ ...placement, kind });
                        }}>
                        {blockKinds.filter(({ kind }) => kind === 'repeat_until' ? supportsWorkflowRepeat(options)
                            : ['task', 'if', 'route'].includes(kind) || options.supported_node_kinds?.includes(kind)).map(({ kind, label }) =>
                            <option key={kind} value={kind}>{label}</option>)}
                    </select>
                </label> : null}
                <label className="text-xs text-text-2">
                    Destination region
                    <select className={inputClass} aria-label="Destination region" value={placement.regionId}
                        onChange={(event) => setPlacement({ ...placement, regionId: event.target.value, beforeId: '' })}>
                        {allowedRegions.map((region) => <option key={region.id} value={region.id}>{region.label}</option>)}
                    </select>
                </label>
                <label className="text-xs text-text-2">
                    Insert before
                    <select className={inputClass} aria-label="Insert before" value={placement.beforeId}
                        onChange={(event) => setPlacement({ ...placement, beforeId: event.target.value })}>
                        <option value="">End of region</option>
                        {placementNodes.filter((node) => node.id !== placement.nodeId).map((node) =>
                            <option key={node.id} value={node.id}>{targets.get(node.id)?.label || node.id} ({node.id})</option>)}
                    </select>
                </label>
            </div>
            <div className="flex flex-wrap gap-2">
                <GlassButton size="sm" variant="primary" disabled={placement.action === 'move' && moveTarget?.kind !== 'node'} onClick={() => {
                    const beforeId = placement.beforeId || undefined;
                    const command: WorkflowEditCommand | null = placement.action === 'add'
                        ? { type: 'add', regionId: placement.regionId, kind: placement.kind, beforeId }
                        : placement.nodeId ? { type: 'move', nodeId: placement.nodeId, targetRegionId: placement.regionId, beforeId } : null;
                    if (command && onEdit(command) !== 'rejected') setPlacement(null);
                }}>{placement.action === 'add' ? 'Add block' : 'Apply block move'}</GlassButton>
                <GlassButton size="sm" onClick={() => setPlacement(null)}>Cancel block placement</GlassButton>
            </div>
        </fieldset> : null}
        <div className="grid min-w-0 gap-4 xl:grid-cols-2">
            <WorkflowFlowCanvas projection={compiled ?? model.structure} sourceKind="draft"
                diagramLabel="Editable workflow draft diagram" inspectLabel="Configure selected block"
                selectedId={selection} collapsed={collapsed} statuses={statuses} observations={noExecutions} details={null}
                bindingRelationships={bindings} positions={positions} setPositions={setPositions} focusRequest={canvasFocus}
                onSelect={onSelect} onCollapse={collapse} onInspect={inspect}
                helpText="Arrow keys navigate; Enter selects a block. Configure selected block moves focus to its fields. Solid execution arrows appear only for the current compiler-validated draft. Dashed lines are declared relationships, not execution paths. Add, move, remove, and binding controls change the draft; dragging and view buttons change layout only. Touch scrolling and browser zoom remain available." />
            <section ref={configurationRef} tabIndex={-1} className="min-w-0 space-y-3 rounded-xl border border-edge p-3"
                aria-label="Selected block configuration">
                <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                        <h4 className="text-sm font-semibold text-text-1">{selected.label}</h4>
                        <p className="break-all text-xs text-text-3">Canonical ID: {selected.id}</p>
                    </div>
                    <GlassButton size="sm" onClick={() => setCanvasFocus((current) => ({
                        id: selected.id, sequence: (current?.sequence ?? 0) + 1,
                    }))}>Return to selected block</GlassButton>
                </div>
                <fieldset disabled={disabled} className="min-w-0 space-y-3">
                    {selected.kind === 'region' ? <WorkflowRegionOutputFields workflow={workflow} region={selected.region}
                        owner={selected.owner} onEdit={onEdit} />
                        : selected.kind === 'join' ? <WorkflowJoinFields workflow={workflow} node={selected.node}
                            onChange={(value) => onEdit({ type: 'join', nodeId: selected.node.id, value: value.join })} />
                            : <>
                                <WorkflowStructuredNodeFields node={selected.node} region={selected.region} workflow={workflow}
                                    options={options} scope={scope} onEdit={onEdit} renderTask={renderTask}
                                    branch={inBranch} />
                                <WorkflowStructuredOutputFields node={selected.node} workflow={workflow} onEdit={onEdit} />
                            </>}
                </fieldset>
                {bindings.length ? <section aria-label="Declared draft relationships" className="min-w-0 space-y-2 border-t border-edge pt-3">
                    <h5 className="text-xs font-semibold text-text-2">Declared relationships</h5>
                    <p className="text-xs text-text-3">These are authored selectors, not runtime evidence. Unresolved selectors remain visible in the configuration fields.</p>
                    <ul className="space-y-1 text-xs text-text-3">
                        {bindings.map((binding, index) => <li key={index} className="break-all">{binding.label}</li>)}
                    </ul>
                </section> : null}
            </section>
        </div>
    </section>;
}
