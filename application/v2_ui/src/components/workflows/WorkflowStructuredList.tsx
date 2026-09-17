// WorkflowStructuredList.tsx
// List authoring over the canonical structured flow, without a second graph model.

import { useState, type ReactNode } from 'react';
import { ArrowDown, ArrowUp, GitBranch, Plus, Trash2 } from 'lucide-react';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { GlassButton } from '../ui/primitives';
import { WorkflowConditionEditor, WorkflowFlowInputs } from './WorkflowConditionEditor';
import {
    analyzeWorkflowFlow,
    DEFAULT_FLOW_LIMITS,
    defaultFlowPredicate,
    flowProducers,
    flowRegions,
    flowTaskIds,
    FLOW_MAX_DEPTH,
    FLOW_OUTPUT_KINDS,
    isFlowRegion,
    updateFlowRegion,
    type FlowProducer,
    type WorkflowFlowNode,
    type WorkflowFlowRegion,
    type WorkflowIfNode,
    type WorkflowJoinSource,
    type WorkflowTaskNode,
} from '../../lib/workflowFlow';
import { createWorkflowTask, type WorkflowDefinition, type WorkflowEditorOptions, type WorkflowOutputKind, type WorkflowTask } from '../../lib/workflowEditor';
import { isRecord } from '../../lib/workspaceAuthoring';

const inputClass = 'mt-1 w-full min-w-0 rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none';

function JoinSourcePicker({
    value, producers, label, onChange,
}: {
    value: WorkflowJoinSource;
    producers: FlowProducer[];
    label: string;
    onChange: (source: WorkflowJoinSource) => void;
}) {
    const producer = producers.find((item) => item.id === value.node_id);
    return (
        <fieldset className="min-w-0 space-y-2 rounded-lg border border-edge p-3">
            <legend className="px-1 text-xs font-medium text-text-2">{label}</legend>
            <label className="block text-xs text-text-2">
                Producer
                <select className={inputClass} aria-label={`${label} producer`} value={value.node_id}
                    onChange={(event) => {
                        const selected = producers.find((item) => item.id === event.target.value);
                        onChange({ node_id: event.target.value, output: selected?.outputs[0]?.name ?? '' });
                    }}>
                    {!producer ? <option value={value.node_id}>{value.node_id ? 'Unavailable producer' : 'Choose producer'}</option> : null}
                    {producers.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                </select>
            </label>
            <label className="block text-xs text-text-2">
                Final output
                <select className={inputClass} aria-label={`${label} output`} value={value.output}
                    onChange={(event) => onChange({ ...value, output: event.target.value })}>
                    {!producer?.outputs.some((item) => item.name === value.output) ? <option value={value.output}>Choose output</option> : null}
                    {producer?.outputs.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
                </select>
            </label>
        </fieldset>
    );
}

function JoinEditor({
    node, workflow, onChange,
}: {
    node: WorkflowIfNode;
    workflow: WorkflowDefinition;
    onChange: (node: WorkflowIfNode) => void;
}) {
    const analysis = analyzeWorkflowFlow(workflow);
    const producers = flowProducers(workflow);
    const thenSources = producers.filter((item) => analysis.branchEnds.get(node.then.id)?.has(item.id));
    const elseSources = producers.filter((item) => analysis.branchEnds.get(node.else.id)?.has(item.id));
    const update = (index: number, patch: Partial<WorkflowIfNode['join']['exports'][number]>) =>
        onChange({ ...node, join: { ...node.join, exports: node.join.exports.map((item, position) => position === index ? { ...item, ...patch } : item) } });
    return (
        <fieldset className="min-w-0 space-y-3 rounded-xl border border-edge p-3">
            <legend className="px-1 text-sm font-semibold text-text-1">Join outputs</legend>
            <p className="text-xs text-text-3">
                Both paths rejoin here. Select each path's exact output to give later tasks one named input.
                Unselected paths do not produce data.
            </p>
            {node.join.exports.map((item, index) => (
                <div key={index} className="min-w-0 space-y-3 rounded-xl bg-surface-sunken p-3">
                    <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                        <label className="text-xs text-text-2">
                            Joined output name
                            <input className={inputClass} aria-label={`Join output ${index + 1} name`} value={item.name} maxLength={64}
                                onChange={(event) => update(index, { name: event.target.value })} />
                        </label>
                        <label className="text-xs text-text-2">
                            Expected kind
                            <select className={inputClass} aria-label={`Join output ${index + 1} kind`} value={item.expected_kind}
                                onChange={(event) => update(index, { expected_kind: event.target.value as WorkflowOutputKind })}>
                                {FLOW_OUTPUT_KINDS.map((kind) => <option key={kind} value={kind}>{kind.replaceAll('_', ' ')}</option>)}
                            </select>
                        </label>
                        <JoinSourcePicker value={item.then} producers={thenSources} label={`Join output ${index + 1} Then`}
                            onChange={(source) => update(index, { then: source })} />
                        <JoinSourcePicker value={item.else} producers={elseSources} label={`Join output ${index + 1} Else`}
                            onChange={(source) => update(index, { else: source })} />
                    </div>
                    <label className="flex items-center gap-2 text-xs text-text-2">
                        <input type="checkbox" checked={item.required} aria-label={`Join output ${index + 1} required`}
                            onChange={(event) => update(index, { required: event.target.checked })} />
                        Require this output on either selected path
                    </label>
                    <GlassButton size="sm" variant="danger" aria-label={`Remove join output ${index + 1}`}
                        onClick={() => onChange({ ...node, join: { ...node.join, exports: node.join.exports.filter((_, position) => position !== index) } })}>
                        <Trash2 size={14} /> Remove output
                    </GlassButton>
                </div>
            ))}
            <GlassButton size="sm" disabled={node.join.exports.length >= 100} onClick={() => {
                let name = 'report';
                let number = 2;
                while (node.join.exports.some((item) => item.name === name)) name = `report${number++}`;
                onChange({ ...node, join: { ...node.join, exports: [...node.join.exports, {
                    name, expected_kind: 'any', required: true,
                    then: { node_id: '', output: '' }, else: { node_id: '', output: '' },
                }] } });
            }}><Plus size={14} /> Add joined output</GlassButton>
        </fieldset>
    );
}

export function WorkflowStructuredList({
    workflow, options, onChange, renderTask,
}: {
    workflow: WorkflowDefinition;
    options: WorkflowEditorOptions;
    onChange: (workflow: WorkflowDefinition) => void;
    renderTask: (task: WorkflowTask, node: WorkflowTaskNode, onNodeChange: (node: WorkflowTaskNode) => void) => ReactNode;
}) {
    const [removing, setRemoving] = useState<{ regionId: string; node: WorkflowFlowNode } | null>(null);
    if (!isFlowRegion(workflow.flow)) {
        return <p role="alert" className="text-sm text-danger">This flow cannot be edited by this version of the List editor.</p>;
    }
    const flow = workflow.flow;
    const regions = flowRegions(flow);
    const limits = isRecord(workflow.limits) ? workflow.limits : DEFAULT_FLOW_LIMITS;
    const setFlow = (next: WorkflowFlowRegion, tasks = workflow.tasks) => onChange({ ...workflow, flow: next, tasks });
    const setNode = (regionId: string, next: WorkflowFlowNode) =>
        setFlow(updateFlowRegion(flow, regionId, (region) => ({
            ...region, nodes: region.nodes.map((node) => node.id === next.id ? next : node),
        })));
    const add = (regionId: string, kind: WorkflowFlowNode['kind']) => {
        const task = { ...createWorkflowTask(workflow.tasks.length), inputs: [], reference_ids: workflow.reference_inputs.map((reference) => reference.id) };
        const id = kind === 'task' ? task.id : `${kind}-${task.id}`;
        let node: WorkflowFlowNode;
        if (kind === 'task') node = { id, kind, task_id: task.id };
        else if (kind === 'route') node = { id, kind, inputs: [], condition: defaultFlowPredicate(), target: { node_id: '' } };
        else node = {
            id, kind, inputs: [], condition: defaultFlowPredicate(),
            then: { id: `then-${task.id}`, nodes: [] }, else: { id: `else-${task.id}`, nodes: [] },
            join: { id: `join-${task.id}`, exports: [] },
        };
        setFlow(updateFlowRegion(flow, regionId, (region) => ({ ...region, nodes: [...region.nodes, node] })),
            kind === 'task' ? [...workflow.tasks, task] : workflow.tasks);
    };
    const move = (regionId: string, nodeId: string, direction: -1 | 1) =>
        setFlow(updateFlowRegion(flow, regionId, (region) => {
            const index = region.nodes.findIndex((node) => node.id === nodeId);
            const nodes = [...region.nodes];
            [nodes[index], nodes[index + direction]] = [nodes[index + direction], nodes[index]];
            return { ...region, nodes };
        }));
    const moveToRegion = (regionId: string, targetId: string, node: WorkflowFlowNode) => {
        const removed = updateFlowRegion(flow, regionId, (region) => ({ ...region, nodes: region.nodes.filter((item) => item.id !== node.id) }));
        setFlow(updateFlowRegion(removed, targetId, (region) => ({ ...region, nodes: [...region.nodes, node] })));
    };
    const renderRegion = (region: WorkflowFlowRegion, label: string, depth: number): ReactNode => (
        <fieldset className={`min-w-0 space-y-3 ${depth ? 'rounded-xl border-l-2 border-edge p-2 sm:p-3' : ''}`} key={region.id} aria-label={`${label} region`}>
            <legend className="px-1 text-sm font-semibold text-text-1">{label}</legend>
            {region.nodes.map((node, index) => {
                const descendants = node.kind === 'if' ? new Set([
                    ...flowRegions(node.then).map((item) => item.id), ...flowRegions(node.else).map((item) => item.id),
                ]) : new Set<string>();
                const destinations = regions.filter((item) => item.id !== region.id && !descendants.has(item.id));
                const task = node.kind === 'task' ? workflow.tasks.find((item) => item.id === node.task_id) : undefined;
                const title = node.kind === 'task' ? task?.name || 'Task' : node.kind === 'if' ? 'If / else' : 'Forward route';
                const routeTargetId = node.kind === 'route' && 'node_id' in node.target ? node.target.node_id : undefined;
                return (
                    <section key={node.id} className="min-w-0 space-y-3 rounded-xl border border-edge bg-surface-1 p-3" aria-label={`${title} block`}>
                        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                            <div className="min-w-0">
                                <p className="text-sm font-semibold text-text-1">{index + 1}. {title}</p>
                                <p className="max-w-full break-all text-[10px] text-text-3">Node: {node.id}</p>
                            </div>
                            <div className="flex flex-wrap gap-1">
                                <GlassButton size="sm" disabled={index === 0} aria-label={`Move ${title} up`} onClick={() => move(region.id, node.id, -1)}><ArrowUp size={14} /> Up</GlassButton>
                                <GlassButton size="sm" disabled={index === region.nodes.length - 1} aria-label={`Move ${title} down`} onClick={() => move(region.id, node.id, 1)}><ArrowDown size={14} /> Down</GlassButton>
                                <GlassButton size="sm" variant="danger" disabled={workflow.tasks.length - flowTaskIds(node).length < 1}
                                    aria-label={`Remove ${title} block`} onClick={() => setRemoving({ regionId: region.id, node })}><Trash2 size={14} /> Remove</GlassButton>
                            </div>
                        </div>
                        {destinations.length ? (
                            <label className="block text-xs text-text-2">
                                Move block to a region
                                <select className={inputClass} value="" aria-label={`Move ${title} to region`}
                                    onChange={(event) => moveToRegion(region.id, event.target.value, node)}>
                                    <option value="" disabled>Choose destination</option>
                                    {destinations.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                                </select>
                            </label>
                        ) : null}
                        {node.kind === 'task' ? (
                            task ? renderTask(task, node, (next) => setNode(region.id, next)) : <p role="alert" className="text-xs text-danger">The referenced task is missing.</p>
                        ) : (
                            <>
                                <WorkflowFlowInputs workflow={workflow} nodeId={node.id} bindings={node.inputs} label={`${title} inputs`}
                                    onChange={(inputs) => setNode(region.id, { ...node, inputs })} />
                                <WorkflowConditionEditor workflow={workflow} bindings={node.inputs} value={node.condition} label={`${title} condition`}
                                    onChange={(condition) => setNode(region.id, { ...node, condition })} />
                                {node.kind === 'if' ? (
                                    <>
                                        <p className="text-xs text-text-3">True selects Then; false selects Else. The choice is saved before either path starts.</p>
                                        {renderRegion(node.then, 'Then', depth + 1)}
                                        {renderRegion(node.else, 'Else', depth + 1)}
                                        <JoinEditor node={node} workflow={workflow} onChange={(next) => setNode(region.id, next)} />
                                    </>
                                ) : (
                                    <label className="block text-xs text-text-2">
                                        Route when true
                                        <select className={inputClass} aria-label="Forward route target"
                                            value={'node_id' in node.target ? `node:${node.target.node_id}` : `exit:${node.target.exit_region_id}`}
                                            onChange={(event) => {
                                                const value = event.target.value;
                                                setNode(region.id, { ...node, target: value.startsWith('exit:')
                                                    ? { exit_region_id: value.slice(5) } : { node_id: value.slice(5) } });
                                            }}>
                                            <option value={routeTargetId !== undefined && !region.nodes.slice(index + 1).some((item) => item.id === routeTargetId) ? `node:${routeTargetId}` : ''} disabled>Choose a later sibling or branch exit</option>
                                            {region.nodes.slice(index + 1).map((item) => <option key={item.id} value={`node:${item.id}`}>
                                                {item.kind === 'task' ? workflow.tasks.find((task) => task.id === item.task_id)?.name || item.id : `${item.kind} (${item.id})`}
                                            </option>)}
                                            {depth > 0 ? <option value={`exit:${region.id}`}>Exit this branch to its join</option> : null}
                                        </select>
                                        <span className="mt-1 block text-xs text-text-3">False continues to the next node. Routing cannot bypass required inputs.</span>
                                    </label>
                                )}
                            </>
                        )}
                    </section>
                );
            })}
            {!region.nodes.length ? <p className="text-xs text-text-3">This path is empty and rejoins without producing an output.</p> : null}
            <div className="flex flex-wrap gap-2">
                <GlassButton size="sm" disabled={workflow.tasks.length >= options.max_tasks} onClick={() => add(region.id, 'task')}
                    aria-label={`Add task to ${label}`}><Plus size={14} /> Add task</GlassButton>
                <GlassButton size="sm" disabled={depth + 1 >= FLOW_MAX_DEPTH} onClick={() => add(region.id, 'if')}
                    aria-label={`Add If/else to ${label}`}><GitBranch size={14} /> Add If/else</GlassButton>
                <GlassButton size="sm" onClick={() => add(region.id, 'route')}
                    aria-label={`Add forward route to ${label}`}><Plus size={14} /> Add forward route</GlassButton>
            </div>
        </fieldset>
    );
    return (
        <div className="min-w-0 space-y-4">
            <p className="text-xs text-text-3">List order inside each region is the executable flow. Reordering never retargets a saved input.</p>
            <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-xs text-text-2">
                    Maximum execution admissions
                    <input className={inputClass} type="number" min={1} max={DEFAULT_FLOW_LIMITS.max_executions}
                        aria-label="Maximum execution admissions" value={Number.isFinite(Number(limits.max_executions)) ? Number(limits.max_executions) : ''}
                        onChange={(event) => onChange({ ...workflow, limits: { ...limits, max_executions: event.currentTarget.valueAsNumber } })} />
                </label>
                <label className="text-xs text-text-2">
                    Elapsed deadline (seconds, including waits)
                    <input className={inputClass} type="number" min={1} max={DEFAULT_FLOW_LIMITS.deadline_seconds}
                        aria-label="Workflow elapsed deadline" value={Number.isFinite(Number(limits.deadline_seconds)) ? Number(limits.deadline_seconds) : ''}
                        onChange={(event) => onChange({ ...workflow, limits: { ...limits, deadline_seconds: event.currentTarget.valueAsNumber } })} />
                </label>
            </div>
            {renderRegion(flow, 'Main', 0)}
            <WorkflowFlowInputs workflow={workflow} nodeId={flow.id} bindings={flow.outputs ?? []} label="Final outputs"
                onChange={(outputs) => setFlow({ ...flow, outputs })} />
            <p className="text-xs text-text-3">Required final outputs must exist on every selected path. Leave this list empty only when the workflow does not promise a final deliverable.</p>
            {removing ? (
                <ConfirmDialog title="Remove this flow block?" description="Tasks inside the block will be removed. Existing consumers keep their bindings and will show any resulting dependency errors."
                    confirmLabel="Remove block" cancelLabel="Keep block" onClose={() => setRemoving(null)}
                    onConfirm={() => {
                        const taskIds = new Set(flowTaskIds(removing.node));
                        setFlow(updateFlowRegion(flow, removing.regionId, (region) => ({
                            ...region, nodes: region.nodes.filter((node) => node.id !== removing.node.id),
                        })), workflow.tasks.filter((task) => !taskIds.has(task.id)));
                        setRemoving(null);
                    }} />
            ) : null}
        </div>
    );
}
