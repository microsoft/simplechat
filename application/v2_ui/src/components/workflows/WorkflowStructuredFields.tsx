// WorkflowStructuredFields.tsx

import type { ReactNode } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { WorkflowConditionEditor, WorkflowFlowInputs } from './WorkflowConditionEditor';
import { WorkflowCollectFields, WorkflowForEachFields } from './WorkflowLoopFields';
import { WorkflowRepeatFields, WorkflowRepeatExports } from './WorkflowRepeatFields';
import {
    analyzeWorkflowFlow, DEFAULT_FLOW_LIMITS, enclosingFlowLoopControls, flowProducers, FLOW_OUTPUT_KINDS,
    repeatUntilBindings, type FlowProducer, type WorkflowFlowNode, type WorkflowFlowRegion,
    type WorkflowIfNode, type WorkflowJoinSource, type WorkflowTaskNode,
} from '../../lib/workflowFlow';
import type {
    WorkflowDefinition, WorkflowEditorOptions, WorkflowOutputKind, WorkflowScope, WorkflowTask,
} from '../../lib/workflowEditor';
import type { WorkflowEditCommand } from '../../lib/workflowAuthoring';
import { isRecord } from '../../lib/workspaceAuthoring';

const inputClass = 'mt-1 w-full min-w-0 rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none';

function JoinSourcePicker({ value, producers, label, onChange }: {
    value: WorkflowJoinSource;
    producers: FlowProducer[];
    label: string;
    onChange: (source: WorkflowJoinSource) => void;
}) {
    const producer = producers.find((item) => item.id === value.node_id);
    return <fieldset className="min-w-0 space-y-2 rounded-lg border border-edge p-3">
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
    </fieldset>;
}

export function WorkflowJoinFields({ node, workflow, onChange }: {
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
    return <fieldset className="min-w-0 space-y-3 rounded-xl border border-edge p-3">
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
    </fieldset>;
}

export function WorkflowStructuredNodeFields({ node, region, workflow, options, scope, onEdit, renderTask, branch = false }: {
    node: WorkflowFlowNode;
    region: WorkflowFlowRegion;
    workflow: WorkflowDefinition;
    options: WorkflowEditorOptions;
    scope: WorkflowScope;
    onEdit: (command: WorkflowEditCommand) => void;
    renderTask: (task: WorkflowTask, node: WorkflowTaskNode, onNodeChange: (node: WorkflowTaskNode) => void) => ReactNode;
    branch?: boolean;
}) {
    const change = (value: WorkflowFlowNode) => onEdit({ type: 'node', nodeId: node.id, value, expected: node });
    if (node.kind === 'task') {
        const task = workflow.tasks.find((item) => item.id === node.task_id);
        return task ? renderTask(task, node, change)
            : <p role="alert" className="text-xs text-danger">The referenced task is missing.</p>;
    }
    if (node.kind === 'for_each') return <WorkflowForEachFields node={node} workflow={workflow} options={options} scope={scope} onChange={change} />;
    if (node.kind === 'repeat_until') return <WorkflowRepeatFields node={node} workflow={workflow} options={options} onChange={change} />;
    if (node.kind === 'collect') return <WorkflowCollectFields node={node} workflow={workflow} onChange={change} />;
    const title = node.kind === 'if' ? 'If / else' : 'Forward route';
    const index = region.nodes.findIndex((item) => item.id === node.id);
    const routeTargetId = node.kind === 'route' && 'node_id' in node.target ? node.target.node_id : undefined;
    return <>
        <WorkflowFlowInputs workflow={workflow} nodeId={node.id} bindings={node.inputs} label={`${title} inputs`}
            onChange={(inputs) => change({ ...node, inputs })} />
        <WorkflowConditionEditor workflow={workflow} bindings={node.inputs} value={node.condition} label={`${title} condition`}
            onChange={(condition) => change({ ...node, condition })} />
        {node.kind === 'if' ? <p className="text-xs text-text-3">True selects Then; false selects Else. The choice is saved before either path starts.</p>
            : <label className="block text-xs text-text-2">
                Route when true
                <select className={inputClass} aria-label="Forward route target"
                    value={'node_id' in node.target ? `node:${node.target.node_id}` : `exit:${node.target.exit_region_id}`}
                    onChange={(event) => {
                        const value = event.target.value;
                        change({ ...node, target: value.startsWith('exit:')
                            ? { exit_region_id: value.slice(5) } : { node_id: value.slice(5) } });
                    }}>
                    <option value={routeTargetId !== undefined && !region.nodes.slice(index + 1).some((item) => item.id === routeTargetId) ? `node:${routeTargetId}` : ''} disabled>Choose a later sibling or branch exit</option>
                    {region.nodes.slice(index + 1).map((item) => <option key={item.id} value={`node:${item.id}`}>
                        {item.kind === 'task' ? workflow.tasks.find((task) => task.id === item.task_id)?.name || item.id : `${item.kind} (${item.id})`}
                    </option>)}
                    {branch ? <option value={`exit:${region.id}`}>Exit this branch to its join</option> : null}
                </select>
                <span className="mt-1 block text-xs text-text-3">False continues to the next node. Routing cannot bypass required inputs.</span>
            </label>}
    </>;
}

export function WorkflowRegionOutputFields({ workflow, region, owner, onEdit }: {
    workflow: WorkflowDefinition;
    region: WorkflowFlowRegion;
    owner?: WorkflowFlowNode | null;
    onEdit: (command: WorkflowEditCommand) => void;
}) {
    if (owner?.kind === 'if') return <p className="text-xs text-text-3">This branch exposes named outputs through its owning Join.</p>;
    const loop = owner?.kind === 'for_each' || owner?.kind === 'repeat_until' ? owner : null;
    const label = loop?.kind === 'for_each' ? 'Body outputs' : loop ? 'Repeat body outputs' : 'Final outputs';
    return <>
        <WorkflowFlowInputs workflow={workflow} nodeId={region.id} bindings={region.outputs ?? []} label={label}
            allowLoopItems={!loop} allowRepeatState={loop?.kind !== 'for_each'}
            availableIds={loop ? new Set([...(analyzeWorkflowFlow(workflow).available.get(region.id) ?? [])].filter((id) =>
                enclosingFlowLoopControls(workflow, id).at(-1)?.id === loop.id)) : undefined}
            onChange={(outputs) => onEdit({ type: 'outputs', regionId: region.id, value: outputs })} />
        <p className="text-xs text-text-3">
            {loop?.kind === 'for_each' ? 'Body outputs are per-item receipts. Add a following Collect to expose a complete collection outside this loop.'
                : loop ? 'The stop condition reads the validated NEXT state, after every named slot is saved atomically. Body bindings always read CURRENT state.'
                    : 'Required final outputs must exist on every selected path. Leave this list empty only when the workflow does not promise a final deliverable.'}
        </p>
    </>;
}

export function WorkflowStructuredOutputFields({ node, workflow, onEdit }: {
    node: WorkflowFlowNode;
    workflow: WorkflowDefinition;
    onEdit: (command: WorkflowEditCommand) => void;
}) {
    const change = (value: WorkflowFlowNode) => onEdit({ type: 'node', nodeId: node.id, value, expected: node });
    if (node.kind === 'if') return <WorkflowJoinFields node={node} workflow={workflow} onChange={change} />;
    if (node.kind !== 'for_each' && node.kind !== 'repeat_until') return null;
    return <>
        <WorkflowRegionOutputFields workflow={workflow} region={node.body} owner={node} onEdit={onEdit} />
        {node.kind === 'repeat_until' ? <>
            <WorkflowConditionEditor workflow={workflow} bindings={repeatUntilBindings(node)} value={node.until}
                label="Stop after a round when" onChange={(until) => change({ ...node, until })} />
            <WorkflowRepeatExports node={node} onChange={change} />
        </> : null}
    </>;
}

export function WorkflowFlowLimitFields({ workflow, onEdit }: {
    workflow: WorkflowDefinition;
    onEdit: (command: WorkflowEditCommand) => void;
}) {
    const raw = isRecord(workflow.limits) ? workflow.limits : DEFAULT_FLOW_LIMITS;
    const limits = { max_executions: Number(raw.max_executions), deadline_seconds: Number(raw.deadline_seconds) };
    return <fieldset className="grid min-w-0 gap-3 rounded-xl border border-edge p-3 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-text-1">Workflow run limits</legend>
        <label className="text-xs text-text-2">
            Maximum execution admissions
            <input className={inputClass} type="number" min={1} max={DEFAULT_FLOW_LIMITS.max_executions}
                aria-label="Maximum execution admissions" value={Number.isFinite(limits.max_executions) ? limits.max_executions : ''}
                onChange={(event) => onEdit({ type: 'limits', value: { ...limits, max_executions: event.currentTarget.valueAsNumber } })} />
        </label>
        <label className="text-xs text-text-2">
            Elapsed deadline (seconds, including waits)
            <input className={inputClass} type="number" min={1} max={DEFAULT_FLOW_LIMITS.deadline_seconds}
                aria-label="Workflow elapsed deadline" value={Number.isFinite(limits.deadline_seconds) ? limits.deadline_seconds : ''}
                onChange={(event) => onEdit({ type: 'limits', value: { ...limits, deadline_seconds: event.currentTarget.valueAsNumber } })} />
        </label>
    </fieldset>;
}
