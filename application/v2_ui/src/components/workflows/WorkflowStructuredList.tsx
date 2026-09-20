// WorkflowStructuredList.tsx
// List and Flow share configuration fields and canonical draft commands.

import type { FocusEvent, ReactNode } from 'react';
import { ArrowDown, ArrowUp, GitBranch, Plus, Trash2 } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import {
    WorkflowRegionOutputFields, WorkflowStructuredNodeFields, WorkflowStructuredOutputFields,
} from './WorkflowStructuredFields';
import {
    flowRegions, flowTaskIds, FLOW_MAX_DEPTH, isFlowRegion, supportsWorkflowRepeat,
    type WorkflowFlowRegion, type WorkflowTaskNode,
} from '../../lib/workflowFlow';
import type { WorkflowDefinition, WorkflowEditorOptions, WorkflowScope, WorkflowTask } from '../../lib/workflowEditor';
import type { WorkflowEditCommand } from '../../lib/workflowAuthoring';

const inputClass = 'mt-1 w-full min-w-0 rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none';

export function WorkflowStructuredList({ workflow, options, scope, onEdit, renderTask, selectedId, onSelect }: {
    workflow: WorkflowDefinition;
    options: WorkflowEditorOptions;
    scope: WorkflowScope;
    onEdit: (command: WorkflowEditCommand) => void;
    renderTask: (task: WorkflowTask, node: WorkflowTaskNode, onNodeChange: (node: WorkflowTaskNode) => void) => ReactNode;
    selectedId?: string | null;
    onSelect?: (id: string) => void;
}) {
    if (!isFlowRegion(workflow.flow)) {
        return <p role="alert" className="text-sm text-danger">This flow cannot be edited by this version of the List editor.</p>;
    }
    const flow = workflow.flow;
    const regions = flowRegions(flow);
    const selectOwner = (event: FocusEvent<HTMLElement>, id: string) => {
        if (event.target.closest('[data-workflow-authoring-id]') === event.currentTarget) onSelect?.(id);
    };
    const renderRegion = (region: WorkflowFlowRegion, label: string, depth: number, branch = false): ReactNode => (
        <fieldset className={`min-w-0 space-y-3 ${depth ? 'rounded-xl border-l-2 border-edge p-2 sm:p-3' : ''}`}
            key={region.id} aria-label={`${label} region`} data-workflow-authoring-id={region.id} tabIndex={-1}
            onFocusCapture={(event) => selectOwner(event, region.id)}>
            <legend className="px-1 text-sm font-semibold text-text-1">{label}</legend>
            {region.nodes.map((node, index) => {
                const childRegions = node.kind === 'if' ? [...flowRegions(node.then), ...flowRegions(node.else)]
                    : node.kind === 'for_each' || node.kind === 'repeat_until' ? flowRegions(node.body) : [];
                const descendants = new Set(childRegions.map((item) => item.id));
                const subtreeDepth = childRegions.length ? Math.max(...childRegions.map((item) => item.depth)) + 1 : 0;
                const destinations = regions.filter((item) => item.id !== region.id && !descendants.has(item.id) &&
                    item.depth + subtreeDepth < FLOW_MAX_DEPTH);
                const task = node.kind === 'task' ? workflow.tasks.find((item) => item.id === node.task_id) : undefined;
                const title = node.kind === 'task' ? task?.name || 'Task' : node.kind === 'if' ? 'If / else'
                    : node.kind === 'for_each' ? 'For each' : node.kind === 'repeat_until' ? 'Repeat until'
                        : node.kind === 'collect' ? 'Collect' : 'Forward route';
                const move = (beforeId?: string) => onEdit({ type: 'move', nodeId: node.id, targetRegionId: region.id, beforeId });
                return <section key={node.id} tabIndex={-1} data-workflow-authoring-id={node.id}
                    onFocusCapture={(event) => selectOwner(event, node.id)}
                    className={`min-w-0 space-y-3 rounded-xl border bg-surface-1 p-3 ${selectedId === node.id ? 'border-accent' : 'border-edge'}`}
                    aria-label={`${title} block`}>
                    <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                        <div className="min-w-0">
                            <p className="text-sm font-semibold text-text-1">{index + 1}. {title}</p>
                            <p className="max-w-full break-all text-[10px] text-text-3">Node: {node.id}</p>
                        </div>
                        <div className="flex flex-wrap gap-1">
                            <GlassButton size="sm" disabled={index === 0} aria-label={`Move ${title} up`}
                                onClick={() => move(region.nodes[index - 1]?.id)}><ArrowUp size={14} /> Up</GlassButton>
                            <GlassButton size="sm" disabled={index === region.nodes.length - 1} aria-label={`Move ${title} down`}
                                onClick={() => move(region.nodes[index + 2]?.id)}><ArrowDown size={14} /> Down</GlassButton>
                            <GlassButton size="sm" variant="danger" disabled={workflow.tasks.length - flowTaskIds(node).length < 1}
                                aria-label={`Remove ${title} block`} onClick={() => onEdit({ type: 'remove', nodeId: node.id })}>
                                <Trash2 size={14} /> Remove
                            </GlassButton>
                        </div>
                    </div>
                    {destinations.length ? <label className="block text-xs text-text-2">
                        Move block to a region
                        <select className={inputClass} value="" aria-label={`Move ${title} to region`}
                            onChange={(event) => onEdit({ type: 'move', nodeId: node.id, targetRegionId: event.target.value })}>
                            <option value="" disabled>Choose destination</option>
                            {destinations.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                        </select>
                    </label> : null}
                    <WorkflowStructuredNodeFields node={node} region={region} workflow={workflow} options={options}
                        scope={scope} onEdit={onEdit} renderTask={renderTask} branch={branch} />
                    {node.kind === 'if' ? <>
                        {renderRegion(node.then, 'Then', depth + 1, true)}
                        {renderRegion(node.else, 'Else', depth + 1, true)}
                    </> : node.kind === 'for_each' || node.kind === 'repeat_until'
                        ? renderRegion(node.body, node.kind === 'for_each' ? 'Body' : 'Repeat body', depth + 1) : null}
                    <div data-workflow-authoring-id={node.kind === 'if' ? node.join.id : node.id} tabIndex={-1}
                        onFocusCapture={(event) => selectOwner(event, node.kind === 'if' ? node.join.id : node.id)}>
                        <WorkflowStructuredOutputFields node={node} workflow={workflow} onEdit={onEdit} />
                    </div>
                </section>;
            })}
            {!region.nodes.length ? <p className="text-xs text-text-3">This region is empty and invokes no tasks.</p> : null}
            <div className="flex flex-wrap gap-2">
                <GlassButton size="sm" disabled={workflow.tasks.length >= options.max_tasks}
                    onClick={() => onEdit({ type: 'add', regionId: region.id, kind: 'task' })}
                    aria-label={`Add task to ${label}`}><Plus size={14} /> Add task</GlassButton>
                <GlassButton size="sm" disabled={depth + 1 >= FLOW_MAX_DEPTH}
                    onClick={() => onEdit({ type: 'add', regionId: region.id, kind: 'if' })}
                    aria-label={`Add If/else to ${label}`}><GitBranch size={14} /> Add If/else</GlassButton>
                <GlassButton size="sm" onClick={() => onEdit({ type: 'add', regionId: region.id, kind: 'route' })}
                    aria-label={`Add forward route to ${label}`}><Plus size={14} /> Add forward route</GlassButton>
                {options.supported_node_kinds?.includes('for_each') ? <GlassButton size="sm" disabled={depth + 1 >= FLOW_MAX_DEPTH}
                    onClick={() => onEdit({ type: 'add', regionId: region.id, kind: 'for_each' })}
                    aria-label={`Add For each to ${label}`}><Plus size={14} /> Add For each</GlassButton> : null}
                {supportsWorkflowRepeat(options) ? <GlassButton size="sm" disabled={depth + 1 >= FLOW_MAX_DEPTH}
                    onClick={() => onEdit({ type: 'add', regionId: region.id, kind: 'repeat_until' })}
                    aria-label={`Add Repeat until to ${label}`}><Plus size={14} /> Add Repeat until</GlassButton> : null}
                {options.supported_node_kinds?.includes('collect') ? <GlassButton size="sm"
                    onClick={() => onEdit({ type: 'add', regionId: region.id, kind: 'collect' })}
                    aria-label={`Add Collect to ${label}`}><Plus size={14} /> Add Collect</GlassButton> : null}
            </div>
        </fieldset>
    );
    return <div className="min-w-0 space-y-4">
        <p className="text-xs text-text-3">List order inside each region is the executable flow. Reordering never retargets a saved input.</p>
        {renderRegion(flow, 'Main', 0)}
        <div data-workflow-authoring-id={flow.id} onFocusCapture={(event) => selectOwner(event, flow.id)}>
            <WorkflowRegionOutputFields workflow={workflow} region={flow} onEdit={onEdit} />
        </div>
    </div>;
}
