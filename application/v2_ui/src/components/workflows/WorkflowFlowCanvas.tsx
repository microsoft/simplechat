// WorkflowFlowCanvas.tsx
// A local presentation-only renderer. Semantic edits belong to the owning editor.

import { memo, useCallback, useEffect, useId, useMemo, useRef, useState, type Dispatch, type KeyboardEvent, type SetStateAction, type TouchEvent } from 'react';
import {
    Handle, MarkerType, Position, ReactFlow,
    type Edge, type Node, type NodeChange, type NodeProps, type ReactFlowInstance,
} from '@xyflow/react';
import { GlassButton } from '../ui/primitives';
import { layoutWorkflowFlow, visibleWorkflowEdges, visibleWorkflowNode, type WorkflowFlowStructure } from '../../lib/workflowFlowLayout';
import { workflowInspectionBindings, type WorkflowInspectionDetails, type WorkflowInspectionNode } from '../../lib/workflowInspection';
import type { WorkflowExecutionRecord } from '../../lib/workflowExecutionHistory';
import '@xyflow/react/dist/style.css';
import './WorkflowFlowView.css';

const kindLabels: Record<WorkflowInspectionNode['kind'], string> = {
    region: 'Region', task: 'Task', if: 'If / else', join: 'Join', route: 'Forward route',
    for_each: 'For each', repeat_until: 'Repeat until', collect: 'Collect',
};

interface FlowNodeData extends Record<string, unknown> {
    record: WorkflowInspectionNode;
    container: boolean;
    collapsed: boolean;
    chosen: boolean;
    tabStop: boolean;
    status: string;
    onSelect: (id: string) => void;
    onFocus: (id: string, part?: 'collapse', reveal?: boolean) => void;
    onNavigate: (id: string, event: KeyboardEvent<HTMLButtonElement>) => void;
    onCollapse: (id: string) => void;
    registerButton: (id: string, button: HTMLButtonElement | null) => void;
}

type FlowNode = Node<FlowNodeData, 'workflow'>;

const DefinitionNode = memo(function DefinitionNode({ data }: NodeProps<FlowNode>) {
    const node = data.record;
    return <div className={`workflow-flow-node ${data.container ? 'workflow-flow-container' : ''} ${data.chosen ? 'workflow-flow-selected' : ''}`}>
        <Handle type="target" position={Position.Top} id="in" isConnectable={false} />
        <Handle type="target" position={Position.Right} id="return" className="workflow-flow-return-handle" isConnectable={false} />
        <Handle type="target" position={Position.Bottom} id="finish" isConnectable={false} />
        <Handle type="source" position={Position.Left} id="data-out" className="workflow-flow-data-source" isConnectable={false} />
        <Handle type="target" position={Position.Left} id="data-in" className="workflow-flow-data-target" isConnectable={false} />
        <div className="workflow-flow-node-header">
            <button type="button" className="nodrag nopan workflow-flow-node-select"
                data-workflow-node-id={node.id}
                ref={(button) => data.registerButton(node.id, button)}
                aria-label={`Select ${node.label} (${kindLabels[node.kind]})`} aria-description={`Canonical node ${node.id}`}
                aria-pressed={data.chosen} tabIndex={data.tabStop ? 0 : -1}
                onFocus={(event) => data.onFocus(node.id, undefined, event.currentTarget.matches(':focus-visible'))}
                onKeyDown={(event) => data.onNavigate(node.id, event)}
                onClick={() => data.onSelect(node.id)}>
                <span className="workflow-flow-kind">{kindLabels[node.kind]}</span>
                <span className="workflow-flow-label" title={node.label}>{node.label}</span>
                <span className="workflow-flow-status" title={data.status}>{data.status}</span>
            </button>
            {node.child_region_ids.length > 0 ? <button type="button"
                className="nodrag nopan workflow-flow-collapse" aria-expanded={!data.collapsed}
                aria-label={`${data.collapsed ? 'Expand' : 'Collapse'} ${node.label}`}
                onFocus={(event) => data.onFocus(node.id, 'collapse', event.currentTarget.matches(':focus-visible'))}
                onKeyDown={(event) => data.onNavigate(node.id, event)}
                onClick={() => data.onCollapse(node.id)}>
                {data.collapsed ? 'Expand' : 'Collapse'}
            </button> : null}
        </div>
        {!data.container ? <p className="workflow-flow-node-note">
            {node.kind === 'repeat_until' ? node.max_iterations === undefined ? 'Choose an explicit finite batch' : `Post-body Until; ${node.max_iterations} rounds per batch`
                : node.kind === 'for_each' ? node.max_items === undefined ? 'Choose an actual-input limit' : `At most ${node.max_items} actual inputs`
                    : node.has_condition ? node.kind === 'task' ? 'Run when condition' : 'Typed condition'
                        : `${node.inputs_count} inputs; ${node.outputs_count} outputs`}
        </p> : null}
        {data.container && node.kind === 'repeat_until' ? <p className="workflow-flow-boundary-note">
            {node.max_iterations === undefined ? 'Choose an explicit finite batch' : `Post-body Until; ${node.max_iterations} rounds per automatic batch`}
        </p> : null}
        <Handle type="source" position={Position.Bottom} id="out" isConnectable={false} />
        <Handle type="source" position={Position.Bottom} id="body" className="workflow-flow-body-handle" isConnectable={false} />
    </div>;
});

const nodeTypes = { workflow: DefinitionNode };

function preserveBrowserPinch(event: TouchEvent<HTMLDivElement>) {
    if (event.touches.length > 1) event.stopPropagation();
}

export function WorkflowFlowCanvas({
    projection, collapsed, selectedId, statuses, observations, details, focusRequest, positions, setPositions, onSelect, onCollapse, onInspect,
    sourceKind = 'saved', diagramLabel = 'Read-only workflow diagram', inspectLabel = 'Inspect selected node',
    bindingRelationships, helpText,
}: {
    projection: WorkflowFlowStructure;
    collapsed: ReadonlySet<string>;
    selectedId: string | null;
    statuses: ReadonlyMap<string, string>;
    observations: ReadonlyMap<string, WorkflowExecutionRecord>;
    details: WorkflowInspectionDetails | null;
    focusRequest: { id: string; sequence: number } | null;
    positions: Map<string, { x: number; y: number }>;
    setPositions: Dispatch<SetStateAction<Map<string, { x: number; y: number }>>>;
    onSelect: (id: string) => void;
    onCollapse: (id: string) => void;
    onInspect: () => void;
    sourceKind?: 'saved' | 'draft' | 'run';
    diagramLabel?: string;
    inspectLabel?: string;
    bindingRelationships?: { sourceId: string; label: string }[];
    helpText?: string;
}) {
    const instance = useRef<ReactFlowInstance<FlowNode, Edge> | null>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const buttons = useRef(new Map<string, HTMLButtonElement>());
    const helpId = useId();
    const [focusedId, setFocusedId] = useState<string | null>(null);
    const [error, setError] = useState('');
    const [dragPan, setDragPan] = useState(() => window.matchMedia('(min-width: 640px) and (pointer: fine)').matches);
    const boxes = useMemo(() => layoutWorkflowFlow(projection, collapsed), [projection, collapsed]);
    const records = useMemo(() => new Map(projection.nodes.map((node) => [node.id, node])), [projection.nodes]);
    const boxMap = useMemo(() => new Map(boxes.map((box) => [box.id, box])), [boxes]);
    useEffect(() => {
        const media = window.matchMedia('(min-width: 640px) and (pointer: fine)');
        const update = () => setDragPan(media.matches);
        media.addEventListener('change', update);
        return () => media.removeEventListener('change', update);
    }, []);
    useEffect(() => {
        setPositions((current) => [...current.keys()].every((id) => records.has(id))
            ? current : new Map([...current].filter(([id]) => records.has(id))));
    }, [records, setPositions]);
    const registerButton = useCallback((id: string, button: HTMLButtonElement | null) => {
        if (button) buttons.current.set(id, button);
        else buttons.current.delete(id);
    }, []);

    const onFocus = useCallback((id: string, part?: 'collapse', reveal = false) => {
        setFocusedId(id);
        if (!reveal) return;
        containerRef.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        const flow = instance.current;
        const box = boxMap.get(id);
        const bounds = containerRef.current?.getBoundingClientRect();
        if (!flow || !box || !bounds || !flow.viewportInitialized) return;
        let point = { ...(positions.get(id) ?? box.position) };
        let parent = box.parentId;
        while (parent) {
            const parentBox = boxMap.get(parent);
            if (!parentBox) break;
            const offset = positions.get(parent) ?? parentBox.position;
            point = { x: point.x + offset.x, y: point.y + offset.y };
            parent = parentBox.parentId;
        }
        point = { x: point.x + (part === 'collapse' ? Math.min(box.width - 32, 320) : Math.min(box.width / 2, 140)), y: point.y + 35 };
        const screen = flow.flowToScreenPosition(point);
        if (flow.getZoom() < 1 || screen.x < bounds.left + 60 || screen.x > bounds.right - 60 ||
            screen.y < bounds.top + 30 || screen.y > bounds.bottom - 30) {
            void flow.setCenter(point.x, point.y, { zoom: Math.max(1, flow.getZoom()), duration: 0 });
        }
    }, [boxMap, positions]);

    const onNavigate = useCallback((id: string, event: KeyboardEvent<HTMLButtonElement>) => {
        const index = boxes.findIndex((box) => box.id === id);
        let nextId: string | undefined;
        if (event.key === 'ArrowDown') nextId = boxes[Math.min(boxes.length - 1, index + 1)]?.id;
        else if (event.key === 'ArrowUp') nextId = boxes[Math.max(0, index - 1)]?.id;
        else if (event.key === 'Home') nextId = boxes[0]?.id;
        else if (event.key === 'End') nextId = boxes.at(-1)?.id;
        else if (event.key === 'ArrowLeft') nextId = records.get(id)?.parent_id ?? undefined;
        else if (event.key === 'ArrowRight') {
            if (collapsed.has(id)) onCollapse(id);
            else nextId = boxes.find((box) => box.parentId === id)?.id;
        } else return;
        event.preventDefault();
        event.stopPropagation();
        if (nextId) {
            buttons.current.get(nextId)?.focus({ preventScroll: true });
            onFocus(nextId, undefined, true);
        }
    }, [boxes, records, collapsed, onCollapse, onFocus]);

    useEffect(() => {
        if (focusRequest) {
            buttons.current.get(focusRequest.id)?.focus({ preventScroll: true });
            onFocus(focusRequest.id, undefined, true);
        }
    }, [focusRequest]);

    const nodes: FlowNode[] = useMemo(() => boxes.map((box) => {
        const record = records.get(box.id);
        if (!record) throw new Error('The Flow layout lost a canonical node.');
        return {
            id: box.id, type: 'workflow', parentId: box.parentId, position: positions.get(box.id) ?? box.position,
            width: box.width, height: box.height, style: { width: box.width, height: box.height },
            draggable: dragPan && !box.container && record.kind !== 'region',
            selectable: false, connectable: false, focusable: false, deletable: false,
            extent: box.parentId ? 'parent' : undefined,
            data: {
                record, container: box.container, collapsed: collapsed.has(box.id), chosen: selectedId === box.id,
                tabStop: (focusedId && boxMap.has(focusedId) ? focusedId : boxes[0]?.id) === box.id,
                status: statuses.get(box.id) ?? (sourceKind === 'run' ? 'Not loaded' : 'Definition'),
                onSelect, onFocus, onNavigate, onCollapse, registerButton,
            },
        };
    }), [boxes, records, positions, collapsed, selectedId, focusedId, boxMap, statuses, dragPan,
        sourceKind, onSelect, onFocus, onNavigate, onCollapse, registerButton]);

    const edges: Edge[] = useMemo(() => {
        const connections = new Map<string, { edge: Edge; labels: Set<string> }>();
        for (const edge of visibleWorkflowEdges(projection, collapsed)) {
            const sourceHandle = records.get(edge.target)?.parent_id === edge.source ||
                ['then', 'else', 'body'].includes(edge.kind) ? 'body' : 'out';
            const targetHandle = edge.kind === 'repeat' ? 'return'
                : edge.kind === 'complete' && records.get(edge.target)?.kind === 'region' ? 'finish' : 'in';
            const decision = observations.get(edge.source)?.decision;
            const branch = decision?.selected_branch ?? decision?.choice;
            const branchKnown = records.get(edge.source)?.kind === 'if' && typeof branch === 'string' &&
                (branch === 'then' || branch === 'else' || records.get(edge.source)?.child_region_ids.includes(branch));
            const branchEdge = branchKnown && (edge.kind === 'then' || edge.kind === 'else');
            const taken = branchEdge && (branch === edge.kind || branch === edge.target);
            const label = branchEdge ? `${edge.label} (${taken ? 'recorded path' : 'not selected'})` : edge.label;
            const key = JSON.stringify([edge.source, edge.target, sourceHandle, targetHandle]);
            const existing = connections.get(key);
            if (existing) {
                existing.labels.add(label);
                existing.edge.label = existing.labels.size === 1 ? label : `${existing.labels.size} control paths (inspect relationships)`;
            } else {
                connections.set(key, { labels: new Set([label]), edge: {
                    ...edge, label, type: 'smoothstep', sourceHandle, targetHandle,
                    markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--text-2)' },
                    focusable: false, selectable: false, deletable: false, reconnectable: false,
                    className: `workflow-flow-control-edge${taken ? ' workflow-flow-recorded-edge' : ''}`,
                } });
            }
        }
        const control = [...connections.values()].map(({ edge }) => edge);
        const selected = selectedId ? records.get(selectedId) : undefined;
        if (!selected || !details && !bindingRelationships) return control;
        const dataConnections = new Map<string, { edge: Edge; count: number }>();
        const bindings = bindingRelationships ?? (details ? workflowInspectionBindings(selected, details) : []);
        for (const [index, binding] of bindings.entries()) {
            const source = visibleWorkflowNode(binding.sourceId, records, collapsed);
            const target = visibleWorkflowNode(selected.id, records, collapsed);
            if (source === target) continue;
            const key = JSON.stringify([source, target]);
            const existing = dataConnections.get(key);
            if (existing) {
                existing.count += 1;
                existing.edge.label = bindingRelationships ? `${existing.count} declared relationships`
                    : `${existing.count} declared bindings (this page)`;
            } else {
                dataConnections.set(key, { count: 1, edge: {
                    id: `binding:${selectedId}:${index}`, source, target, type: 'smoothstep',
                    sourceHandle: 'data-out', targetHandle: 'data-in', label: binding.label,
                    className: 'workflow-flow-data-edge',
                    markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--accent)' },
                    focusable: false, selectable: false, deletable: false, reconnectable: false,
                } });
            }
        }
        return [...control, ...[...dataConnections.values()].map(({ edge }) => edge)];
    }, [projection, collapsed, records, observations, details, selectedId, bindingRelationships]);

    const changePositions = useCallback((changes: NodeChange<FlowNode>[]) => {
        const moved = changes.filter((change) => change.type === 'position' && change.position !== undefined);
        if (!moved.length) return;
        setPositions((current) => {
            const next = new Map(current);
            for (const change of moved) {
                if (change.type === 'position' && change.position && boxMap.has(change.id)) next.set(change.id, change.position);
            }
            return next;
        });
    }, [boxMap, setPositions]);

    const moveSelected = (dx: number, dy: number) => {
        const box = selectedId ? boxMap.get(selectedId) : undefined;
        if (!box || box.container || records.get(box.id)?.kind === 'region') return;
        const position = positions.get(box.id) ?? box.position;
        const parent = box.parentId ? boxMap.get(box.parentId) : undefined;
        setPositions((current) => new Map(current).set(box.id, {
            x: Math.max(0, Math.min(parent ? parent.width - box.width : Infinity, position.x + dx)),
            y: Math.max(0, Math.min(parent ? parent.height - box.height : Infinity, position.y + dy)),
        }));
    };
    const selectedBox = selectedId ? boxMap.get(selectedId) : undefined;
    const canMove = Boolean(selectedBox && !selectedBox.container && records.get(selectedBox.id)?.kind !== 'region');
    const pan = (dx: number, dy: number) => {
        const flow = instance.current;
        if (!flow) return;
        const viewport = flow.getViewport();
        void flow.setViewport({ ...viewport, x: viewport.x + dx, y: viewport.y + dy }, { duration: 0 });
    };

    return <div className="workflow-flow space-y-3">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Flow view controls">
            <GlassButton size="sm" onClick={() => void instance.current?.fitView({ padding: 0.15, maxZoom: 1, duration: 0 })}>Fit Flow</GlassButton>
            <GlassButton size="sm" onClick={() => void instance.current?.zoomIn({ duration: 0 })}>Zoom in</GlassButton>
            <GlassButton size="sm" onClick={() => void instance.current?.zoomOut({ duration: 0 })}>Zoom out</GlassButton>
            <GlassButton size="sm" onClick={() => pan(120, 0)}>Pan view left</GlassButton>
            <GlassButton size="sm" onClick={() => pan(-120, 0)}>Pan view right</GlassButton>
            <GlassButton size="sm" onClick={() => pan(0, 120)}>Pan view up</GlassButton>
            <GlassButton size="sm" onClick={() => pan(0, -120)}>Pan view down</GlassButton>
            <GlassButton size="sm" onClick={() => setPositions(new Map())}>Reset layout</GlassButton>
            <GlassButton size="sm" disabled={!selectedId} onClick={onInspect}>{inspectLabel}</GlassButton>
        </div>
        <p className="text-xs text-text-3" id={helpId}>
            {helpText ?? 'Arrow keys move focus through the structure; Enter selects a node. Left returns to its region and Right enters or expands it. Solid arrows show control flow. Dashed arrows show only the selected page of typed bindings, not additional execution paths. A recorded-path label comes only from that exact instance\'s saved branch decision. On touch screens, use the pan buttons; page scrolling and browser zoom remain available.'}
        </p>
        {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
        <div ref={containerRef} role="group" className="workflow-flow-canvas" aria-label={diagramLabel} aria-describedby={helpId}
            onWheelCapture={(event) => {
                // XYFlow cancels Ctrl+wheel before applying its disabled-zoom filter.
                if (event.ctrlKey) event.stopPropagation();
            }}
            onTouchStartCapture={preserveBrowserPinch} onTouchMoveCapture={preserveBrowserPinch}>
            <ReactFlow<FlowNode, Edge>
                id={`workflow-flow-${helpId.replaceAll(':', '')}`}
                nodes={nodes} edges={edges} nodeTypes={nodeTypes}
                onInit={(flow) => { instance.current = flow; }}
                onNodesChange={changePositions}
                onError={() => setError('Flow geometry is unavailable. Use List or reload the view.')}
                nodesConnectable={false} edgesReconnectable={false} nodesFocusable={false} edgesFocusable={false}
                elementsSelectable={false} selectNodesOnDrag={false} deleteKeyCode={null}
                selectionKeyCode={null} multiSelectionKeyCode={null}
                zoomActivationKeyCode={null} panActivationKeyCode={null}
                panOnDrag={dragPan} zoomOnScroll={false} zoomOnPinch={false} zoomOnDoubleClick={false} preventScrolling={false}
                minZoom={0.005} maxZoom={2} fitView fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
                defaultMarkerColor={null}
            />
        </div>
        {selectedBox ? <div className="flex flex-wrap items-center gap-2 text-xs text-text-3" role="group" aria-label="Temporary node position">
            <span>Move the selected box (view only):</span>
            <GlassButton size="sm" disabled={!canMove} onClick={() => moveSelected(-16, 0)}>Move box left</GlassButton>
            <GlassButton size="sm" disabled={!canMove} onClick={() => moveSelected(16, 0)}>Move box right</GlassButton>
            <GlassButton size="sm" disabled={!canMove} onClick={() => moveSelected(0, -16)}>Move box up</GlassButton>
            <GlassButton size="sm" disabled={!canMove} onClick={() => moveSelected(0, 16)}>Move box down</GlassButton>
        </div> : null}
    </div>;
}
