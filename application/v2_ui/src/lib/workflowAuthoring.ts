// workflowAuthoring.ts
// Shared draft edits and display structure; execution meaning belongs to the compiler.

import {
    createWorkflowTask,
    type WorkflowDefinition,
    type WorkflowEditorOptions,
    type WorkflowTask,
} from './workflowEditor';
import {
    analyzeWorkflowFlow, defaultFlowPredicate, flowProducers, flowTaskIds, flowUnsupportedReason,
    FLOW_MAX_DEPTH, FLOW_MAX_NODES, isFlowRegion, supportsWorkflowRepeat, updateFlowRegion, workflowLoopLimit,
    type WorkflowFlowBinding, type WorkflowFlowLimits, type WorkflowFlowNode, type WorkflowFlowRegion,
    type WorkflowFlowSource, type WorkflowIfNode, type WorkflowPredicate,
} from './workflowFlow';
import type { WorkflowFlowStructure } from './workflowFlowLayout';
import type { WorkflowInspectionNode } from './workflowInspection';
import { sameEditorValue } from './workspaceAuthoring';

interface TargetLocation {
    id: string;
    label: string;
    regionId: string;
    loopIds: string[];
    depth: number;
}

export type WorkflowAuthoringTarget =
    | TargetLocation & { kind: 'region'; region: WorkflowFlowRegion; owner: WorkflowFlowNode | null }
    | TargetLocation & { kind: 'node'; node: WorkflowFlowNode; region: WorkflowFlowRegion }
    | TargetLocation & { kind: 'join'; node: WorkflowIfNode; region: WorkflowFlowRegion };

export type WorkflowEditCommand =
    | { type: 'add'; regionId: string; kind: WorkflowFlowNode['kind']; beforeId?: string }
    | { type: 'move'; nodeId: string; targetRegionId: string; beforeId?: string }
    | { type: 'remove'; nodeId: string }
    | { type: 'node'; nodeId: string; value: WorkflowFlowNode; expected?: WorkflowFlowNode }
    | { type: 'task'; taskId: string; value: WorkflowTask; expected?: WorkflowTask }
    | { type: 'outputs'; regionId: string; value: WorkflowFlowBinding[] }
    | { type: 'join'; nodeId: string; value: WorkflowIfNode['join'] }
    | { type: 'limits'; value: WorkflowFlowLimits };

export interface WorkflowEditImpact {
    nodeId: string;
    field: string;
    message: string;
}

export type WorkflowEditResult =
    | { status: 'applied'; workflow: WorkflowDefinition; selectedId: string; impact: WorkflowEditImpact[] }
    | { status: 'confirmation_required'; message: string; impact: WorkflowEditImpact[] }
    | { status: 'rejected'; message: string };

const labels: Record<WorkflowFlowNode['kind'], string> = {
    task: 'Task', if: 'If / else', route: 'Forward route', for_each: 'For each',
    repeat_until: 'Repeat until', collect: 'Collect',
};

export function indexWorkflowDraft(workflow: WorkflowDefinition): Map<string, WorkflowAuthoringTarget> {
    if (!isFlowRegion(workflow.flow)) throw new Error('This draft has no supported structured flow.');
    const targets = new Map<string, WorkflowAuthoringTarget>();
    const tasks = new Map(workflow.tasks.map((task) => [task.id, task]));
    const add = (target: WorkflowAuthoringTarget) => {
        if (targets.has(target.id)) throw new Error(`The draft contains a duplicate structural ID: ${target.id}.`);
        targets.set(target.id, target);
    };
    const walk = (region: WorkflowFlowRegion, label: string, depth: number, loopIds: string[], owner: WorkflowFlowNode | null) => {
        add({ kind: 'region', id: region.id, label, region, regionId: region.id, depth, loopIds, owner });
        for (const node of region.nodes) {
            add({
                kind: 'node', id: node.id, node, region, regionId: region.id, depth, loopIds,
                label: node.kind === 'task' ? tasks.get(node.task_id)?.name || labels.task : labels[node.kind],
            });
            if (node.kind === 'if') {
                add({ kind: 'join', id: node.join.id, node, region, regionId: region.id, label: 'Join', depth, loopIds });
                walk(node.then, 'Then', depth + 1, loopIds, node);
                walk(node.else, 'Else', depth + 1, loopIds, node);
            } else if (node.kind === 'for_each' || node.kind === 'repeat_until') {
                walk(node.body, node.kind === 'for_each' ? 'For each body' : 'Repeat body',
                    depth + 1, [...loopIds, node.id], node);
            }
        }
    };
    walk(workflow.flow, 'Workflow', 1, [], null);
    return targets;
}

export function workflowDraftStructure(workflow: WorkflowDefinition): WorkflowFlowStructure {
    if (!isFlowRegion(workflow.flow)) throw new Error('This draft has no supported structured flow.');
    const targets = indexWorkflowDraft(workflow);
    const tasks = new Map(workflow.tasks.map((task) => [task.id, task]));
    const nodes: WorkflowInspectionNode[] = [];
    for (const target of targets.values()) {
        const parent = target.kind === 'region' ? target.owner?.id ?? null : target.regionId;
        const region = target.region;
        const siblings = target.kind === 'region' ? [] : region.nodes;
        const node = target.kind === 'region' ? null : target.node;
        let order = 0;
        if (target.kind === 'region') {
            order = target.owner?.kind === 'if' && target.owner.else.id === target.id ? 1 : 0;
        } else {
            for (const sibling of siblings) {
                if (sibling.id === node?.id) break;
                order += sibling.kind === 'if' ? 2 : 1;
            }
            if (target.kind === 'join') order++;
        }
        nodes.push({
            id: target.id, kind: target.kind === 'region' ? 'region' : target.kind === 'join' ? 'join' : target.node.kind,
            label: target.label, parent_id: parent, region_id: target.regionId, order,
            loop_ids: target.loopIds,
            child_region_ids: target.kind !== 'node' ? [] : target.node.kind === 'if' ? [target.node.then.id, target.node.else.id]
                : target.node.kind === 'for_each' || target.node.kind === 'repeat_until' ? [target.node.body.id] : [],
            inputs_count: target.kind === 'join' ? 0 : node?.kind === 'task' ? tasks.get(node.task_id)?.inputs?.length ?? 0
                : node && 'inputs' in node ? node.inputs.length : 0,
            outputs_count: target.kind === 'region' ? region.outputs?.length ?? 0
                : target.kind === 'join' ? target.node.join.exports.length
                    : node?.kind === 'repeat_until' ? node.exports.length : 0,
            has_condition: target.kind === 'node' && Boolean(node && ('condition' in node || 'run_when' in node || 'until' in node)),
            ...(node?.kind === 'task' ? { task_id: node.task_id } : {}),
            ...(node?.kind === 'for_each' && Number.isFinite(node.max_items) ? { max_items: node.max_items } : {}),
            ...(node?.kind === 'repeat_until' && Number.isFinite(node.max_iterations) ? { max_iterations: node.max_iterations } : {}),
        });
    }
    return { root_region_id: workflow.flow.id, nodes, edges: [] };
}

interface DraftReference {
    nodeId: string;
    field: string;
    sourceId: string;
    output: string;
    contextId: string;
    kind: 'node_output' | 'loop_item' | 'repeat_state' | 'route' | 'exit' | 'collect' | 'body_output' | 'alias' | 'current_item';
}

function draftReferences(workflow: WorkflowDefinition): DraftReference[] {
    const targets = indexWorkflowDraft(workflow);
    const references: DraftReference[] = [];
    const source = (nodeId: string, field: string, value: WorkflowFlowSource, contextId = nodeId) => references.push({
        nodeId, field, contextId, kind: value.kind,
        sourceId: value.kind === 'node_output' ? value.node_id : value.loop_id,
        output: value.kind === 'node_output' ? value.output : value.kind === 'repeat_state' ? value.state_name : '',
    });
    const bindings = (nodeId: string, values: WorkflowFlowBinding[], field: string) =>
        values.forEach((binding, index) => source(nodeId, `${field}[${index}] (${binding.name || 'unnamed'})`, binding.source));
    const predicate = (nodeId: string, value: WorkflowPredicate, field: string, inputs: WorkflowFlowBinding[]) => {
        if (value.op === 'all' || value.op === 'any') value.conditions.forEach((child, index) =>
            predicate(nodeId, child, `${field}.conditions[${index}]`, inputs));
        else if (value.op === 'not') predicate(nodeId, value.condition, `${field}.condition`, inputs);
        else {
            const operands = value.op === 'exists' ? [value.value] : 'left' in value ? [value.left, value.right] : [];
            operands.forEach((operand, index) => {
                if (!('input' in operand)) return;
                const binding = inputs.find((item) => item.name === operand.input);
                if (binding) source(nodeId, `${field}.operand[${index}] (${operand.input}${operand.path})`, binding.source);
                else references.push({ nodeId, field, contextId: nodeId, sourceId: nodeId,
                    output: operand.input, kind: 'alias' });
            });
        }
    };
    for (const target of targets.values()) {
        if (target.kind === 'region') {
            bindings(target.id, target.region.outputs ?? [], 'outputs');
            continue;
        }
        if (target.kind !== 'node') continue;
        const node = target.node;
        if (node.kind === 'task') {
            const task = workflow.tasks.find((item) => item.id === node.task_id);
            const inputs = (task?.inputs ?? []).filter((item): item is WorkflowFlowBinding => 'source' in item);
            bindings(node.id, inputs, 'inputs');
            if (node.run_when) predicate(node.id, node.run_when, 'run_when', inputs);
            if (task?.document_action?.target_mode === 'current_item') references.push({
                nodeId: node.id, field: 'document_action.loop_id', sourceId: task.document_action.loop_id ?? '',
                contextId: node.id, output: '', kind: 'current_item',
            });
        } else if (node.kind === 'collect') {
            references.push({ nodeId: node.id, field: 'source', sourceId: node.source.loop_id,
                output: node.source.output, contextId: node.id, kind: 'collect' });
        } else if (node.kind === 'repeat_until') {
            node.state.forEach((slot, index) => {
                source(node.id, `state[${index}] (${slot.name}).initial`, slot.initial);
                references.push({ nodeId: node.id, field: `state[${index}] (${slot.name}).next`,
                    sourceId: node.body.id, output: slot.next, contextId: node.body.id, kind: 'body_output' });
            });
            node.exports.forEach((output, index) => references.push({
                nodeId: node.id, field: `exports[${index}] (${output.name})`, sourceId: node.body.id,
                output: output.output, contextId: node.body.id, kind: 'body_output',
            }));
            predicate(node.id, node.until, 'until', node.state.map((slot) => ({
                name: slot.name, source: { kind: 'repeat_state', loop_id: node.id, state_name: slot.name, scope: 'current' },
                required: true, expected_kind: slot.output_contract.kind, allow_partial: false,
            })));
        } else {
            bindings(node.id, node.inputs, 'inputs');
            if (node.kind === 'for_each') {
                if (node.iterable.kind === 'input') {
                    const name = node.iterable.name;
                    const input = node.inputs.find((binding) => binding.name === name);
                    if (input) source(node.id, `iterable.input (${name})`, input.source);
                }
            } else {
                predicate(node.id, node.condition, 'condition', node.inputs);
                if (node.kind === 'route') references.push({
                    nodeId: node.id, field: 'target', contextId: node.id, output: '',
                    sourceId: 'node_id' in node.target ? node.target.node_id : node.target.exit_region_id,
                    kind: 'node_id' in node.target ? 'route' : 'exit',
                });
                else node.join.exports.forEach((output, index) => {
                    for (const branch of ['then', 'else'] as const) source(node.join.id,
                        `exports[${index}] (${output.name}).${branch}`,
                        { kind: 'node_output', ...output[branch], scope: 'current' }, node[branch].id);
                });
            }
        }
    }
    return references;
}

export function workflowDraftBindings(workflow: WorkflowDefinition, nodeId: string): { sourceId: string; label: string }[] {
    const targets = indexWorkflowDraft(workflow);
    return draftReferences(workflow).filter((reference) => reference.nodeId === nodeId &&
        !['route', 'exit', 'alias'].includes(reference.kind) && reference.sourceId !== nodeId && targets.has(reference.sourceId))
        .map((reference) => ({ sourceId: reference.sourceId,
            label: `${reference.field}: ${reference.sourceId}${reference.output ? ` / ${reference.output}` : ''}` }));
}

function referenceObservations(workflow: WorkflowDefinition): Map<string, string> {
    const targets = indexWorkflowDraft(workflow);
    const analysis = analyzeWorkflowFlow(workflow);
    const producers = new Map(flowProducers(workflow).map((producer) => [producer.id, producer]));
    return new Map(draftReferences(workflow).map((reference) => {
        const consumer = targets.get(reference.contextId);
        const producer = targets.get(reference.sourceId);
        const key = JSON.stringify([reference.nodeId, reference.field]);
        const output = producers.get(reference.sourceId)?.outputs.find((item) => item.name === reference.output);
        let detail: unknown = output;
        if (reference.kind === 'route') detail = consumer?.kind === 'node' && producer?.kind === 'node' &&
            consumer.regionId === producer.regionId &&
            consumer.region.nodes.indexOf(producer.node) > consumer.region.nodes.indexOf(consumer.node);
        else if (reference.kind === 'exit') detail = consumer?.regionId === reference.sourceId;
        else if (reference.kind === 'body_output') detail = producer?.kind === 'region'
            ? producer.region.outputs?.find((item) => item.name === reference.output) : undefined;
        else if (reference.kind === 'collect') detail = producer?.kind === 'node' && producer.node.kind === 'for_each'
            ? producer.node.body.outputs.find((item) => item.name === reference.output) : undefined;
        else if (reference.kind === 'repeat_state') detail = producer?.kind === 'node' && producer.node.kind === 'repeat_until'
            ? producer.node.state.find((slot) => slot.name === reference.output)?.output_contract : undefined;
        return [key, JSON.stringify([
            Boolean(producer), consumer?.loopIds, producer?.loopIds,
            analysis.available.get(reference.contextId)?.has(reference.sourceId) ?? false,
            analysis.definite.get(reference.contextId)?.has(reference.sourceId) ?? false, detail,
        ])];
    }));
}

export function workflowEditImpact(before: WorkflowDefinition, after: WorkflowDefinition): WorkflowEditImpact[] {
    const previous = referenceObservations(before);
    const current = referenceObservations(after);
    const impact = draftReferences(after).filter((reference) => {
        const key = JSON.stringify([reference.nodeId, reference.field]);
        return previous.has(key) && previous.get(key) !== current.get(key);
    }).map((reference) => ({
        nodeId: reference.nodeId, field: reference.field,
        message: `${reference.field} keeps its selector ${reference.sourceId}${reference.output ? ` / ${reference.output}` : ''}; its scope, availability, or declared output changes.`,
    }));
    const previousErrors = new Set(analyzeWorkflowFlow(before).errors);
    for (const message of analyzeWorkflowFlow(after).errors) {
        if (!previousErrors.has(message)) impact.push({ nodeId: '', field: 'validation', message });
    }
    return impact;
}

function structuralError(workflow: WorkflowDefinition, options: WorkflowEditorOptions): string {
    if (!isFlowRegion(workflow.flow)) return 'The edit would produce an unsupported flow structure.';
    if (!Number.isSafeInteger(options.max_tasks) || options.max_tasks < 1) return 'The workspace task limit is unavailable.';
    if (workflow.tasks.length < 1) return 'Keep at least one task in the workflow.';
    if (workflow.tasks.length > Math.min(100, options.max_tasks)) return 'The edit exceeds the workspace task limit.';
    if (new Set(workflow.tasks.map((task) => task.id)).size !== workflow.tasks.length) return 'Task IDs must remain unique.';
    const ids = new Set<string>();
    let error = '';
    const register = (id: string) => {
        if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(id)) error ||= 'Structural IDs must use the supported identifier format.';
        if (ids.has(id)) error ||= `The edit duplicates structural ID ${id}.`;
        ids.add(id);
    };
    const walk = (region: WorkflowFlowRegion, depth: number, frames: number) => {
        register(region.id);
        if (depth > FLOW_MAX_DEPTH) error ||= 'Flow regions are limited to depth four, including the root.';
        if (frames > 3) error ||= 'At most three mixed For-each and Repeat frames are supported.';
        for (const node of region.nodes) {
            register(node.id);
            if (node.kind === 'if') {
                register(node.join.id);
                walk(node.then, depth + 1, frames);
                walk(node.else, depth + 1, frames);
            } else if (node.kind === 'for_each' || node.kind === 'repeat_until') walk(node.body, depth + 1, frames + 1);
        }
    };
    walk(workflow.flow, 1, 0);
    if (ids.size > FLOW_MAX_NODES) error ||= 'At most 256 structural IDs, including regions and joins, are supported.';
    return error;
}

function sameNodeStructure(left: WorkflowFlowNode, right: WorkflowFlowNode): boolean {
    if (left.id !== right.id || left.kind !== right.kind) return false;
    if (left.kind === 'task') return right.kind === 'task' && left.task_id === right.task_id;
    if (left.kind === 'if') return right.kind === 'if' && left.join.id === right.join.id &&
        sameEditorValue(left.then, right.then) && sameEditorValue(left.else, right.else);
    if (left.kind === 'for_each' || left.kind === 'repeat_until') {
        return (right.kind === 'for_each' || right.kind === 'repeat_until') &&
            left.body.id === right.body.id && sameEditorValue(left.body.nodes, right.body.nodes);
    }
    return true;
}

export function workflowAuthoringEligibility(workflow: WorkflowDefinition, options: WorkflowEditorOptions): string {
    if (options.can_manage !== true) return 'You do not have permission to edit workflows in this scope.';
    if (options.scope.type === 'group' && (!options.scope.id || workflow.group_id !== options.scope.id) ||
        options.scope.type === 'personal' && Boolean(workflow.group_id)) {
        return 'The editor options do not belong to this workflow scope. Reopen the workflow in its authorized workspace.';
    }
    if (!Number.isSafeInteger(options.max_tasks) || options.max_tasks < 1) return 'The workspace task limit is unavailable.';
    if (workflow.active_run_id) return 'Wait for the active run to finish or cancel it before editing.';
    if (workflow.definition_version !== 3 || !(options.supported_definition_versions ?? [1, 2]).includes(3)) {
        return 'Flow authoring requires an explicitly enabled, supported definition-v3 draft.';
    }
    return flowUnsupportedReason(workflow, options) ||
        structuralError(workflow, { ...options, max_tasks: Math.max(options.max_tasks, workflow.tasks.length) });
}

export function workflowCandidateEligibility(
    current: WorkflowDefinition,
    candidate: WorkflowDefinition,
    options: WorkflowEditorOptions,
): string {
    const eligibility = workflowAuthoringEligibility(current, options);
    if (eligibility) return eligibility;
    for (const key of ['id', 'definition_version', 'definition_revision', 'group_id', 'user_id', 'active_run_id']) {
        if (!sameEditorValue(current[key], candidate[key])) return 'Workflow edits cannot change identity, scope, saved revision, or runtime state.';
    }
    const invalid = structuralError(candidate, { ...options, max_tasks: Math.max(options.max_tasks, current.tasks.length) }) ||
        flowUnsupportedReason(candidate, options);
    if (invalid) return invalid;
    if (!isFlowRegion(current.flow) || !isFlowRegion(candidate.flow) || current.flow.id !== candidate.flow.id) {
        return 'Workflow edits must retain the workflow root identity.';
    }
    return '';
}

export function evaluateWorkflowRestore(
    current: WorkflowDefinition,
    candidate: WorkflowDefinition,
    options: WorkflowEditorOptions,
    confirmed = false,
): WorkflowEditResult {
    const invalid = workflowCandidateEligibility(current, candidate, options);
    if (invalid) return { status: 'rejected', message: invalid };
    if (!isFlowRegion(candidate.flow)) return { status: 'rejected', message: 'This draft has no supported flow.' };
    const after = indexWorkflowDraft(candidate);
    const removesBlock = [...indexWorkflowDraft(current).keys()].some((id) => !after.has(id));
    const impact = workflowEditImpact(current, candidate);
    if (!confirmed && (removesBlock || impact.length)) return {
        status: 'confirmation_required', impact,
        message: removesBlock
            ? 'This history step removes blocks from the unsaved draft. Existing references keep their exact selectors.'
            : 'This history step changes reference availability or declared outputs. Resolve resulting errors before saving.',
    };
    return { status: 'applied', workflow: candidate, selectedId: candidate.flow.id, impact };
}

export function applyWorkflowEdit(
    workflow: WorkflowDefinition,
    command: WorkflowEditCommand,
    options: WorkflowEditorOptions,
    confirmed = false,
): WorkflowEditResult {
    const reject = (message: string): WorkflowEditResult => ({ status: 'rejected', message });
    const eligibility = workflowAuthoringEligibility(workflow, options);
    if (eligibility) return reject(eligibility);
    // A lowered workspace ceiling must still allow an author to remove excess tasks.
    const mutationOptions = { ...options, max_tasks: Math.max(options.max_tasks, workflow.tasks.length) };
    if (!isFlowRegion(workflow.flow)) return reject('This draft has no supported flow.');
    const targets = indexWorkflowDraft(workflow);
    const flow = workflow.flow;
    let next = workflow;
    let selectedId = flow.id;
    const replaceNode = (target: WorkflowAuthoringTarget & { kind: 'node' }, value: WorkflowFlowNode) => ({
        ...workflow, flow: updateFlowRegion(flow, target.regionId, (region) => ({
            ...region, nodes: region.nodes.map((node) => node.id === target.id ? value : node),
        })),
    });

    if (command.type === 'add') {
        if (!Object.hasOwn(labels, command.kind)) return reject('Choose a supported block kind.');
        const destination = targets.get(command.regionId);
        if (destination?.kind !== 'region') return reject('Choose an existing destination region.');
        if (command.beforeId !== undefined && !destination.region.nodes.some((node) => node.id === command.beforeId)) {
            return reject('The insertion target is no longer in the selected region.');
        }
        if (options.supported_node_kinds && !options.supported_node_kinds.includes(command.kind) ||
            ['for_each', 'collect'].includes(command.kind) && !options.supported_node_kinds?.includes(command.kind) ||
            command.kind === 'repeat_until' && !supportsWorkflowRepeat(options)) {
            return reject('This server does not support that block kind.');
        }
        const task = { ...createWorkflowTask(workflow.tasks.length), inputs: [],
            reference_ids: workflow.reference_inputs.map((reference) => reference.id) };
        const id = command.kind === 'task' ? task.id : `${command.kind}-${task.id}`;
        let node: WorkflowFlowNode;
        if (command.kind === 'task') node = { id, kind: 'task', task_id: task.id };
        else if (command.kind === 'if') node = {
            id, kind: 'if', inputs: [], condition: defaultFlowPredicate(),
            then: { id: `then-${task.id}`, nodes: [] }, else: { id: `else-${task.id}`, nodes: [] },
            join: { id: `join-${task.id}`, exports: [] },
        };
        else if (command.kind === 'route') node = { id, kind: 'route', inputs: [], condition: defaultFlowPredicate(), target: { node_id: '' } };
        else if (command.kind === 'for_each') node = {
            id, kind: 'for_each', inputs: [], iterable: { kind: 'documents', documents: [] },
            item_key: 'source_identity', max_items: workflowLoopLimit(options),
            body: { id: `body-${task.id}`, nodes: [], outputs: [] },
        };
        else if (command.kind === 'repeat_until') node = {
            id, kind: 'repeat_until', max_iterations: Number.NaN, state: [],
            body: { id: `body-${task.id}`, nodes: [], outputs: [] }, until: defaultFlowPredicate(), exports: [],
        };
        else node = { id, kind: 'collect', source: { loop_id: '', output: '' },
            output_contract: { kind: 'records', require_complete_coverage: true, allow_partial: false } };
        next = { ...workflow,
            tasks: command.kind === 'task' ? [...workflow.tasks, task] : workflow.tasks,
            flow: updateFlowRegion(flow, command.regionId, (region) => {
                const nodes = [...region.nodes];
                nodes.splice(command.beforeId === undefined ? nodes.length : nodes.findIndex((item) => item.id === command.beforeId), 0, node);
                return { ...region, nodes };
            }),
        };
        selectedId = id;
    } else if (command.type === 'task') {
        const task = workflow.tasks.find((item) => item.id === command.taskId);
        if (!task || command.value.id !== task.id || command.value.type !== task.type) return reject('The task identity cannot be replaced.');
        if (command.expected && !sameEditorValue(command.expected, task)) return reject('The task changed before this edit could be applied. Review its current fields.');
        next = { ...workflow, tasks: workflow.tasks.map((item) => item.id === task.id ? command.value : item) };
        selectedId = [...targets.values()].find((target) => target.kind === 'node' &&
            target.node.kind === 'task' && target.node.task_id === task.id)?.id ?? flow.id;
    } else if (command.type === 'outputs') {
        const target = targets.get(command.regionId);
        if (target?.kind !== 'region' || target.owner?.kind === 'if') return reject('Only root and loop-body regions declare outputs.');
        next = { ...workflow, flow: updateFlowRegion(flow, target.id, (region) => ({ ...region, outputs: command.value })) };
        selectedId = target.id;
    } else if (command.type === 'limits') {
        next = { ...workflow, limits: command.value };
    } else {
        const target = targets.get(command.nodeId);
        if (target?.kind !== 'node') return reject('Choose an existing executable block; regions and joins cannot be moved or removed independently.');
        selectedId = target.id;
        if (command.type === 'node') {
            if (!sameNodeStructure(target.node, command.value)) return reject('Use structural commands to change block identities, regions, or execution order.');
            if (command.expected && !sameEditorValue(command.expected, target.node)) return reject('The block changed before this edit could be applied. Review its current fields.');
            next = replaceNode(target, command.value);
        } else if (command.type === 'join') {
            if (target.node.kind !== 'if' || target.node.join.id !== command.value.id) return reject('The join must retain its owning If and canonical ID.');
            next = replaceNode(target, { ...target.node, join: command.value });
            selectedId = target.node.join.id;
        } else if (command.type === 'remove') {
            const taskIds = new Set(flowTaskIds(target.node));
            const remaining = target.region.nodes.filter((node) => node.id !== target.id);
            const position = target.region.nodes.findIndex((node) => node.id === target.id);
            selectedId = remaining[Math.min(position, remaining.length - 1)]?.id ?? target.regionId;
            next = { ...workflow, tasks: workflow.tasks.filter((task) => !taskIds.has(task.id)),
                flow: updateFlowRegion(flow, target.regionId, (region) => ({ ...region, nodes: remaining })) };
        } else {
            const destination = targets.get(command.targetRegionId);
            if (destination?.kind !== 'region') return reject('Choose an existing destination region.');
            if (command.beforeId === target.id && target.regionId === destination.id) {
                return { status: 'applied', workflow, selectedId, impact: [] };
            }
            let ancestor: WorkflowAuthoringTarget | undefined = destination;
            while (ancestor) {
                if (ancestor.id === target.id) return reject('A block cannot be moved inside itself or one of its descendants.');
                ancestor = ancestor.kind === 'region' ? ancestor.owner ? targets.get(ancestor.owner.id) : undefined
                    : targets.get(ancestor.regionId);
            }
            if (command.beforeId !== undefined && !destination.region.nodes.some((node) => node.id === command.beforeId)) {
                return reject('The move target is no longer in the selected region.');
            }
            const removed = updateFlowRegion(flow, target.regionId, (region) => ({
                ...region, nodes: region.nodes.filter((node) => node.id !== target.id),
            }));
            next = { ...workflow, flow: updateFlowRegion(removed, destination.id, (region) => {
                const nodes = [...region.nodes];
                nodes.splice(command.beforeId === undefined ? nodes.length : nodes.findIndex((node) => node.id === command.beforeId), 0, target.node);
                return { ...region, nodes };
            }) };
        }
    }
    const invalid = structuralError(next, mutationOptions) || flowUnsupportedReason(next, options);
    if (invalid) return reject(invalid);
    const impact = command.type === 'remove' || command.type === 'move' ? workflowEditImpact(workflow, next) : [];
    if (!confirmed && (command.type === 'remove' || command.type === 'move' && impact.length)) {
        return { status: 'confirmation_required', impact, message: command.type === 'remove'
            ? 'This removes the block and its contained tasks. Consumers retain their exact references; resolve resulting errors before saving.'
            : 'This changes reference scope or availability. Selectors are not retargeted; resolve resulting errors before saving.' };
    }
    return { status: 'applied', workflow: sameEditorValue(workflow, next) ? workflow : next, selectedId, impact };
}
