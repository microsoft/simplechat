// workflowFlow.ts
// Structured workflow definitions and side-effect-free List editing helpers.

import type {
    WorkflowDefinition,
    WorkflowInputBinding,
    WorkflowOutputKind,
    WorkflowDocumentAction,
    WorkflowOutputContract,
    WorkflowEditorOptions,
    WorkflowReferenceScope,
} from './workflowEditor';
import { isRecord, sameEditorValue } from './workspaceAuthoring';

export type WorkflowScalar = string | number | boolean | null;
export type WorkflowComparison = 'eq' | 'ne' | 'lt' | 'lte' | 'gt' | 'gte';
export type WorkflowOperand = { input: string; path: string } | { literal: WorkflowScalar };
export type WorkflowPredicate =
    | { op: WorkflowComparison; left: WorkflowOperand; right: WorkflowOperand }
    | { op: 'exists'; value: WorkflowOperand }
    | { op: 'all' | 'any'; conditions: WorkflowPredicate[] }
    | { op: 'not'; condition: WorkflowPredicate };

export interface WorkflowNodeOutputSource {
    kind: 'node_output';
    node_id: string;
    output: string;
    scope: 'current';
}

export interface WorkflowLoopItemSource {
    kind: 'loop_item';
    loop_id: string;
    scope: 'current';
}

export interface WorkflowRepeatStateSource {
    kind: 'repeat_state';
    loop_id: string;
    state_name: string;
    scope: 'current';
}

export type WorkflowFlowSource = WorkflowNodeOutputSource | WorkflowLoopItemSource | WorkflowRepeatStateSource;
export type WorkflowRepeatStateKind = Exclude<WorkflowOutputKind, 'any'>;
export type WorkflowRepeatStateContract = Omit<WorkflowOutputContract, 'kind' | 'allow_partial' | 'require_complete_coverage'> & {
    kind: WorkflowRepeatStateKind;
    allow_partial?: boolean;
    require_complete_coverage?: boolean;
};

export interface WorkflowRepeatState {
    name: string;
    initial: WorkflowNodeOutputSource | WorkflowRepeatStateSource;
    next: string;
    output_contract: WorkflowRepeatStateContract;
}

export interface WorkflowFlowBinding {
    name: string;
    source: WorkflowFlowSource;
    required: boolean;
    expected_kind: WorkflowOutputKind;
    allow_partial: boolean;
}

export interface WorkflowJoinSource {
    node_id: string;
    output: string;
}

export interface WorkflowJoinExport {
    name: string;
    expected_kind: WorkflowOutputKind;
    required: boolean;
    then: WorkflowJoinSource;
    else: WorkflowJoinSource;
}

export interface WorkflowTaskNode {
    id: string;
    kind: 'task';
    task_id: string;
    run_when?: WorkflowPredicate;
}

export interface WorkflowIfNode {
    id: string;
    kind: 'if';
    inputs: WorkflowFlowBinding[];
    condition: WorkflowPredicate;
    then: WorkflowFlowRegion;
    else: WorkflowFlowRegion;
    join: { id: string; exports: WorkflowJoinExport[] };
}

export interface WorkflowRouteNode {
    id: string;
    kind: 'route';
    inputs: WorkflowFlowBinding[];
    condition: WorkflowPredicate;
    target: { node_id: string } | { exit_region_id: string };
}

export interface WorkflowLoopScope {
    scope_type: WorkflowReferenceScope;
    scope_id?: string;
}

export interface WorkflowLoopDocument extends WorkflowLoopScope {
    document_id: string;
}

export interface WorkflowQueryIterable {
    kind: 'workspace_query';
    scopes: WorkflowLoopScope[];
    filters: {
        search?: string;
        classification?: string;
        author?: string;
        keywords?: string;
        abstract?: string;
        tags?: string[];
    };
    content?: { mode: 'keyword' | 'hybrid'; query: string };
    selection: { mode: 'all_matches' } | { mode: 'best_n'; count: number };
}

export type WorkflowLoopIterable =
    | { kind: 'input'; name: string }
    | { kind: 'documents'; documents: WorkflowLoopDocument[] }
    | WorkflowQueryIterable;

export interface WorkflowForEachNode {
    id: string;
    kind: 'for_each';
    inputs: WorkflowFlowBinding[];
    iterable: WorkflowLoopIterable;
    item_key: 'source_identity';
    max_items: number;
    body: WorkflowFlowRegion & { outputs: WorkflowFlowBinding[] };
}

export interface WorkflowCollectNode {
    id: string;
    kind: 'collect';
    source: { loop_id: string; output: string };
    output_contract: WorkflowOutputContract & { kind: 'records' | 'document_results' };
}

export interface WorkflowRepeatUntilNode {
    id: string;
    kind: 'repeat_until';
    max_iterations: number;
    state: WorkflowRepeatState[];
    body: WorkflowFlowRegion & { outputs: WorkflowFlowBinding[] };
    until: WorkflowPredicate;
    exports: { name: string; output: string }[];
}

export type WorkflowLoopControl = WorkflowForEachNode | WorkflowRepeatUntilNode;
export type WorkflowFlowNode = WorkflowTaskNode | WorkflowIfNode | WorkflowRouteNode | WorkflowLoopControl | WorkflowCollectNode;

export interface WorkflowFlowRegion {
    id: string;
    nodes: WorkflowFlowNode[];
    outputs?: WorkflowFlowBinding[];
}

export interface WorkflowFlowLimits {
    max_executions: number;
    deadline_seconds: number;
}

export const DEFAULT_FLOW_LIMITS: WorkflowFlowLimits = {
    max_executions: 5000,
    deadline_seconds: 86400,
};
export const FLOW_MAX_NODES = 256;
export const FLOW_MAX_DEPTH = 4;
export const DEFAULT_LOOP_MAX_ITEMS = 500;
export const MAX_LOOP_ITEMS = 5000;
export const MAX_REPEAT_ITERATIONS = 1000;
export const REPEAT_STATE_KINDS: WorkflowRepeatStateKind[] = ['text', 'json', 'records', 'document_results'];
export const FLOW_MAX_PREDICATE_DEPTH = 8;
export const FLOW_MAX_PREDICATE_NODES = 100;
export const FLOW_ALIAS_PATTERN = /^[A-Za-z][A-Za-z0-9_-]{0,63}$/;
export const FLOW_OUTPUT_KINDS: WorkflowOutputKind[] = ['any', 'text', 'records', 'json', 'document_results'];
export const FLOW_FINAL_OUTPUTS = ['authoritative', 'text', 'records', 'json', 'documents'] as const;
export const FLOW_COMPARISONS: WorkflowComparison[] = ['eq', 'ne', 'lt', 'lte', 'gt', 'gte'];

export function isFlowBinding(value: unknown): value is WorkflowFlowBinding {
    if (!isRecord(value) || !isRecord(value.source) || value.source.scope !== 'current') return false;
    const source = value.source;
    return typeof value.name === 'string' &&
        (source.kind === 'node_output' && typeof source.node_id === 'string' && typeof source.output === 'string' ||
            source.kind === 'loop_item' && typeof source.loop_id === 'string' && ['json', 'any'].includes(String(value.expected_kind)) ||
            source.kind === 'repeat_state' && typeof source.loop_id === 'string' && typeof source.state_name === 'string') &&
        typeof value.required === 'boolean' && typeof value.allow_partial === 'boolean' &&
        FLOW_OUTPUT_KINDS.some((kind) => kind === value.expected_kind);
}

function isRepeatState(value: unknown): value is WorkflowRepeatState {
    if (!isRecord(value) || typeof value.name !== 'string' || typeof value.next !== 'string' ||
        !isRecord(value.initial) || value.initial.scope !== 'current' || !isRecord(value.output_contract)) return false;
    const source = value.initial;
    const contract = value.output_contract;
    return (source.kind === 'node_output' && typeof source.node_id === 'string' && typeof source.output === 'string' ||
        source.kind === 'repeat_state' && typeof source.loop_id === 'string' && typeof source.state_name === 'string') &&
        REPEAT_STATE_KINDS.some((kind) => kind === contract.kind) &&
        (contract.allow_partial === undefined || typeof contract.allow_partial === 'boolean') &&
        (contract.require_complete_coverage === undefined || typeof contract.require_complete_coverage === 'boolean') &&
        (contract.schema === undefined || isRecord(contract.schema)) &&
        (contract.expected_count === undefined || typeof contract.expected_count === 'number') &&
        (contract.identity_field === undefined || typeof contract.identity_field === 'string');
}

function isLoopScope(value: unknown): value is WorkflowLoopScope {
    return isRecord(value) && ['personal', 'group', 'public'].includes(String(value.scope_type)) &&
        (value.scope_id === undefined || typeof value.scope_id === 'string');
}

export function isLoopIterable(value: unknown): value is WorkflowLoopIterable {
    if (!isRecord(value)) return false;
    if (value.kind === 'input') return typeof value.name === 'string';
    if (value.kind === 'documents') {
        return Array.isArray(value.documents) && value.documents.every((item) =>
            isLoopScope(item) && isRecord(item) && typeof item.document_id === 'string');
    }
    return value.kind === 'workspace_query' && Array.isArray(value.scopes) && value.scopes.every(isLoopScope) &&
        isRecord(value.filters) && Object.entries(value.filters).every(([key, filter]) =>
            key === 'tags' ? Array.isArray(filter) && filter.every((tag) => typeof tag === 'string') : typeof filter === 'string') &&
        (value.content === undefined || isRecord(value.content) && ['keyword', 'hybrid'].includes(String(value.content.mode)) &&
            typeof value.content.query === 'string') &&
        isRecord(value.selection) && (value.selection.mode === 'all_matches' ||
            value.selection.mode === 'best_n' && typeof value.selection.count === 'number');
}

function isCollectContract(value: unknown): value is WorkflowCollectNode['output_contract'] {
    return isRecord(value) && ['records', 'document_results'].includes(String(value.kind)) &&
        typeof value.require_complete_coverage === 'boolean' && typeof value.allow_partial === 'boolean' &&
        (value.schema === undefined || isRecord(value.schema)) &&
        (value.expected_count === undefined || typeof value.expected_count === 'number') &&
        (value.identity_field === undefined || typeof value.identity_field === 'string');
}

export function isLegacyWorkflowBinding(
    value: WorkflowInputBinding | WorkflowFlowBinding,
): value is WorkflowInputBinding {
    return 'task_id' in value;
}

function isOperand(value: unknown): value is WorkflowOperand {
    if (!isRecord(value)) return false;
    if ('literal' in value) {
        return value.literal === null || ['string', 'number', 'boolean'].includes(typeof value.literal);
    }
    return typeof value.input === 'string' && typeof value.path === 'string';
}

export function isFlowPredicate(value: unknown, depth = 0): value is WorkflowPredicate {
    if (!isRecord(value) || depth > 32) return false;
    if (value.op === 'exists') return isOperand(value.value);
    if (value.op === 'not') return isFlowPredicate(value.condition, depth + 1);
    if (value.op === 'all' || value.op === 'any') {
        return Array.isArray(value.conditions) && value.conditions.every((item) => isFlowPredicate(item, depth + 1));
    }
    return FLOW_COMPARISONS.some((op) => op === value.op) && isOperand(value.left) && isOperand(value.right);
}

function isJoinSource(value: unknown): value is WorkflowJoinSource {
    return isRecord(value) && typeof value.node_id === 'string' && typeof value.output === 'string';
}

function isJoinExport(value: unknown): value is WorkflowJoinExport {
    return isRecord(value) && typeof value.name === 'string' && typeof value.required === 'boolean' &&
        FLOW_OUTPUT_KINDS.some((kind) => kind === value.expected_kind) &&
        isJoinSource(value.then) && isJoinSource(value.else);
}

export function isFlowRegion(value: unknown, depth = 0): value is WorkflowFlowRegion {
    if (!isRecord(value) || typeof value.id !== 'string' || !Array.isArray(value.nodes) ||
        value.nodes.length > FLOW_MAX_NODES || depth > 16) return false;
    if (value.outputs !== undefined && (!Array.isArray(value.outputs) || !value.outputs.every(isFlowBinding))) return false;
    return value.nodes.every((node) => {
        if (!isRecord(node) || typeof node.id !== 'string') return false;
        if (node.kind === 'task') {
            return typeof node.task_id === 'string' && (node.run_when === undefined || isFlowPredicate(node.run_when));
        }
        if (node.kind === 'collect') {
            return isRecord(node.source) && typeof node.source.loop_id === 'string' &&
                typeof node.source.output === 'string' && isCollectContract(node.output_contract);
        }
        if (node.kind === 'for_each') {
            return Array.isArray(node.inputs) && node.inputs.every(isFlowBinding) &&
                isLoopIterable(node.iterable) && node.item_key === 'source_identity' &&
                typeof node.max_items === 'number' && isFlowRegion(node.body, depth + 1) &&
                Array.isArray(node.body.outputs);
        }
        if (node.kind === 'repeat_until') {
            return typeof node.max_iterations === 'number' && Array.isArray(node.state) && node.state.every(isRepeatState) &&
                isFlowRegion(node.body, depth + 1) && Array.isArray(node.body.outputs) && isFlowPredicate(node.until) &&
                Array.isArray(node.exports) && node.exports.every((output) =>
                    isRecord(output) && typeof output.name === 'string' && typeof output.output === 'string');
        }
        if (!Array.isArray(node.inputs) || !node.inputs.every(isFlowBinding) || !isFlowPredicate(node.condition)) return false;
        if (node.kind === 'route') {
            return isRecord(node.target) &&
                (typeof node.target.node_id === 'string' || typeof node.target.exit_region_id === 'string');
        }
        return node.kind === 'if' && isFlowRegion(node.then, depth + 1) && isFlowRegion(node.else, depth + 1) &&
            isRecord(node.join) && typeof node.join.id === 'string' &&
            Array.isArray(node.join.exports) && node.join.exports.every(isJoinExport);
    });
}

export function defaultFlowPredicate(input = ''): WorkflowPredicate {
    return { op: 'eq', left: { input, path: '' }, right: { literal: true } };
}

export function flowBinding(name: string, nodeId: string, output = 'authoritative'): WorkflowFlowBinding {
    return {
        name,
        source: { kind: 'node_output', node_id: nodeId, output, scope: 'current' },
        required: true,
        expected_kind: 'any',
        allow_partial: false,
    };
}

export function loopItemBinding(name: string, loopId: string): WorkflowFlowBinding {
    return {
        name, source: { kind: 'loop_item', loop_id: loopId, scope: 'current' },
        expected_kind: 'json', required: true, allow_partial: false,
    };
}

export function repeatStateBinding(name: string, loopId: string, slot: WorkflowRepeatState): WorkflowFlowBinding {
    return {
        name, source: { kind: 'repeat_state', loop_id: loopId, state_name: slot.name, scope: 'current' },
        expected_kind: slot.output_contract.kind, required: true, allow_partial: false,
    };
}

export function repeatUntilBindings(node: WorkflowRepeatUntilNode): WorkflowFlowBinding[] {
    return node.state.map((slot) => repeatStateBinding(slot.name, node.id, slot));
}

export interface FlowProducer {
    id: string;
    label: string;
    outputs: { name: string; kind: WorkflowOutputKind; kinds?: WorkflowOutputKind[]; required: boolean; schema?: Record<string, unknown> }[];
}

export function isRecordsFlowOutput(output: FlowProducer['outputs'][number]): boolean {
    return output.kind === 'records' && (output.kinds ?? [output.kind]).every((kind) => kind === 'records');
}

export function flowProducers(workflow: WorkflowDefinition): FlowProducer[] {
    if (!isFlowRegion(workflow.flow)) return [];
    const tasks = new Map(workflow.tasks.map((task) => [task.id, task]));
    const repeats = new Map(flowRepeats(workflow).map(({ node }) => [node.id, node]));
    const result: FlowProducer[] = [];
    const resolveOutput = (source: WorkflowFlowSource): FlowProducer['outputs'][number] | undefined => {
        if (source.kind === 'node_output') return result.find((producer) => producer.id === source.node_id)?.outputs
            .find((output) => output.name === source.output);
        if (source.kind === 'repeat_state') {
            const slot = repeats.get(source.loop_id)?.state.find((item) => item.name === source.state_name);
            return slot ? {
                name: slot.name, kind: slot.output_contract.kind, required: true,
                schema: slot.output_contract.schema ?? (slot.output_contract.kind === 'text' ? { type: 'string' } : undefined),
            } : undefined;
        }
        return undefined;
    };
    const walk = (region: WorkflowFlowRegion) => region.nodes.forEach((node) => {
        if (node.kind === 'task') {
            const task = tasks.get(node.task_id);
            if (!task) return;
            const kind = task.output_contract?.kind ?? 'any';
            const outputs: FlowProducer['outputs'] = [{
                name: 'authoritative', kind, required: node.run_when === undefined,
                schema: task.output_contract?.schema,
            }, {
                name: 'text', kind: 'text', required: node.run_when === undefined,
                schema: kind === 'text' ? task.output_contract?.schema : undefined,
            }];
            if (kind === 'json' || kind === 'records' || kind === 'document_results') {
                outputs.push({
                    name: kind === 'document_results' ? 'documents' : kind, kind,
                    required: node.run_when === undefined, schema: task.output_contract?.schema,
                });
            }
            result.push({ id: node.id, label: task.name || node.id, outputs });
        } else if (node.kind === 'for_each') {
            walk(node.body);
        } else if (node.kind === 'repeat_until') {
            walk(node.body);
            result.push({
                id: node.id, label: `Repeat ${node.id}`,
                outputs: node.exports.map((item) => {
                    const binding = node.body.outputs.find((output) => output.name === item.output);
                    const output = binding && resolveOutput(binding.source);
                    return {
                        name: item.name, kind: output?.kind ?? binding?.expected_kind ?? 'any',
                        required: binding?.required === true,
                        ...(output?.kinds ? { kinds: output.kinds } : {}),
                        ...(output?.schema ? { schema: output.schema } : {}),
                    };
                }),
            });
        } else if (node.kind === 'collect') {
            result.push({
                id: node.id,
                label: `Collect ${node.source.output || node.id}`,
                outputs: ['authoritative', node.output_contract.kind === 'document_results' ? 'documents' : 'records'].map((name) => ({
                    name, kind: node.output_contract.kind, required: true, schema: node.output_contract.schema,
                })),
            });
        } else if (node.kind === 'if') {
            walk(node.then);
            walk(node.else);
            result.push({
                id: node.join.id,
                label: `Join ${node.id}`,
                outputs: node.join.exports.map((item) => {
                    const thenOutput = result.find((producer) => producer.id === item.then.node_id)?.outputs
                        .find((output) => output.name === item.then.output);
                    const elseOutput = result.find((producer) => producer.id === item.else.node_id)?.outputs
                        .find((output) => output.name === item.else.output);
                    const thenSchema = thenOutput?.schema;
                    const elseSchema = elseOutput?.schema;
                    return {
                        name: item.name, kind: thenOutput?.kind === elseOutput?.kind ? thenOutput?.kind ?? item.expected_kind : item.expected_kind,
                        kinds: [...new Set([
                            ...(thenOutput?.kinds ?? [thenOutput?.kind ?? 'any']),
                            ...(elseOutput?.kinds ?? [elseOutput?.kind ?? 'any']),
                        ])],
                        required: item.required,
                        ...(thenSchema && sameEditorValue(thenSchema, elseSchema) ? { schema: thenSchema } : {}),
                    };
                }),
            });
        }
    });
    walk(workflow.flow);
    return result;
}

export function flowRegions(flow: WorkflowFlowRegion): { id: string; label: string; depth: number }[] {
    const regions: { id: string; label: string; depth: number }[] = [];
    const walk = (region: WorkflowFlowRegion, label: string, depth: number) => {
        regions.push({ id: region.id, label, depth });
        region.nodes.forEach((node) => {
            if (node.kind === 'if') {
                walk(node.then, `${label} / ${node.id} / Then`, depth + 1);
                walk(node.else, `${label} / ${node.id} / Else`, depth + 1);
            } else if (node.kind === 'for_each' || node.kind === 'repeat_until') {
                walk(node.body, `${label} / ${node.id} / Body`, depth + 1);
            }
        });
    };
    walk(flow, 'Main', 0);
    return regions;
}

export function updateFlowRegion(
    flow: WorkflowFlowRegion,
    regionId: string,
    update: (region: WorkflowFlowRegion) => WorkflowFlowRegion,
): WorkflowFlowRegion {
    if (flow.id === regionId) return update(flow);
    return {
        ...flow,
        nodes: flow.nodes.map((node) => {
            if (node.kind === 'if') return {
                ...node,
                then: updateFlowRegion(node.then, regionId, update),
                else: updateFlowRegion(node.else, regionId, update),
            };
            if (node.kind === 'for_each' || node.kind === 'repeat_until') {
                const body = updateFlowRegion(node.body, regionId, update);
                return { ...node, body: { ...body, outputs: body.outputs ?? [] } };
            }
            return node;
        }),
    };
}

export function flowTaskIds(node: WorkflowFlowNode): string[] {
    if (node.kind === 'task') return [node.task_id];
    if (node.kind === 'route' || node.kind === 'collect') return [];
    if (node.kind === 'for_each' || node.kind === 'repeat_until') return node.body.nodes.flatMap(flowTaskIds);
    return [...node.then.nodes, ...node.else.nodes].flatMap(flowTaskIds);
}

export function flowTaskNodeId(workflow: WorkflowDefinition, taskId: string): string {
    if (!isFlowRegion(workflow.flow)) return '';
    const walk = (region: WorkflowFlowRegion): string => {
        for (const node of region.nodes) {
            if (node.kind === 'task' && node.task_id === taskId) return node.id;
            const id = node.kind === 'for_each' || node.kind === 'repeat_until' ? walk(node.body)
                : node.kind === 'if' ? walk(node.then) || walk(node.else) : '';
            if (id) return id;
        }
        return '';
    };
    return walk(workflow.flow);
}

export function flowLoopControls(workflow: WorkflowDefinition): { node: WorkflowLoopControl; regionId: string }[] {
    const loops: { node: WorkflowLoopControl; regionId: string }[] = [];
    if (!isFlowRegion(workflow.flow)) return loops;
    const walk = (region: WorkflowFlowRegion) => region.nodes.forEach((node) => {
        if (node.kind === 'for_each' || node.kind === 'repeat_until') {
            loops.push({ node, regionId: region.id });
            walk(node.body);
        } else if (node.kind === 'if') {
            walk(node.then);
            walk(node.else);
        }
    });
    walk(workflow.flow);
    return loops;
}

export function flowLoops(workflow: WorkflowDefinition): { node: WorkflowForEachNode; regionId: string }[] {
    return flowLoopControls(workflow).flatMap((loop) => loop.node.kind === 'for_each' ? [{ ...loop, node: loop.node }] : []);
}

export function flowRepeats(workflow: WorkflowDefinition): { node: WorkflowRepeatUntilNode; regionId: string }[] {
    return flowLoopControls(workflow).flatMap((loop) => loop.node.kind === 'repeat_until' ? [{ ...loop, node: loop.node }] : []);
}

export function enclosingFlowLoopControls(workflow: WorkflowDefinition, targetId: string): WorkflowLoopControl[] {
    if (!isFlowRegion(workflow.flow)) return [];
    const walk = (region: WorkflowFlowRegion, parents: WorkflowLoopControl[]): WorkflowLoopControl[] | undefined => {
        if (region.id === targetId) return parents;
        for (const node of region.nodes) {
            if (node.id === targetId || node.kind === 'if' && node.join.id === targetId) return parents;
            const found = node.kind === 'for_each' || node.kind === 'repeat_until' ? walk(node.body, [...parents, node])
                : node.kind === 'if' ? walk(node.then, parents) ?? walk(node.else, parents) : undefined;
            if (found) return found;
        }
        return undefined;
    };
    return walk(workflow.flow, []) ?? [];
}

export function enclosingFlowLoops(workflow: WorkflowDefinition, targetId: string): WorkflowForEachNode[] {
    return enclosingFlowLoopControls(workflow, targetId).filter((node): node is WorkflowForEachNode => node.kind === 'for_each');
}

export function enclosingFlowRepeats(workflow: WorkflowDefinition, targetId: string): WorkflowRepeatUntilNode[] {
    return enclosingFlowLoopControls(workflow, targetId).filter((node): node is WorkflowRepeatUntilNode => node.kind === 'repeat_until');
}

export function flowSourceOutput(workflow: WorkflowDefinition, source: WorkflowFlowSource): FlowProducer['outputs'][number] | undefined {
    if (source.kind === 'node_output') return flowProducers(workflow).find((item) => item.id === source.node_id)?.outputs
        .find((item) => item.name === source.output);
    if (source.kind === 'repeat_state') {
        const slot = flowRepeats(workflow).find(({ node }) => node.id === source.loop_id)?.node.state
            .find((item) => item.name === source.state_name);
        return slot ? {
            name: slot.name, kind: slot.output_contract.kind, required: true,
            schema: slot.output_contract.schema ?? (slot.output_contract.kind === 'text' ? { type: 'string' } : undefined),
        } : undefined;
    }
    return undefined;
}

export function flowBindingSchema(workflow: WorkflowDefinition, binding?: WorkflowFlowBinding): Record<string, unknown> | undefined {
    if (!binding) return undefined;
    const source = binding.source;
    if (source.kind !== 'loop_item') {
        return flowSourceOutput(workflow, source)?.schema;
    }
    const loop = flowLoops(workflow).find((item) => item.node.id === source.loop_id)?.node;
    let value: Record<string, unknown> = {};
    if (loop?.iterable.kind === 'input') {
        const name = loop.iterable.name;
        const input = loop.inputs.find((item) => item.name === name)?.source;
        if (input) {
            const schema = flowSourceOutput(workflow, input)?.schema;
            if (isRecord(schema?.items)) value = schema.items;
        }
    } else if (loop) {
        value = { type: 'object', properties: {
            document_id: { type: 'string' }, scope_type: { type: 'string' }, scope_id: { type: 'string' },
        } };
    }
    return { type: 'object', properties: { value, key: { type: 'string' }, index: { type: 'integer' } }, required: ['value', 'key', 'index'] };
}

export function workflowLoopLimit(options: WorkflowEditorOptions): number {
    const limit = options.flow_limits?.max_loop_items;
    return Number.isInteger(limit) && Number(limit) >= 1 && Number(limit) <= MAX_LOOP_ITEMS
        ? Number(limit) : DEFAULT_LOOP_MAX_ITEMS;
}

export function workflowRepeatLimit(options: WorkflowEditorOptions): number | undefined {
    const limit = options.flow_limits?.max_repeat_iterations;
    return options.flow_limits?.hard_repeat_iterations === MAX_REPEAT_ITERATIONS &&
        typeof limit === 'number' && Number.isInteger(limit) && limit >= 1 && limit <= MAX_REPEAT_ITERATIONS ? limit : undefined;
}

export function supportsWorkflowRepeat(options: WorkflowEditorOptions): boolean {
    return options.supported_node_kinds?.includes('repeat_until') === true &&
        options.supported_binding_sources?.includes('repeat_state') === true && workflowRepeatLimit(options) !== undefined;
}

export function repeatIterationErrors(node: WorkflowRepeatUntilNode, ceiling = MAX_REPEAT_ITERATIONS): string[] {
    if (!Number.isInteger(node.max_iterations) || node.max_iterations < 1 || node.max_iterations > MAX_REPEAT_ITERATIONS) {
        return ['Choose an explicit maximum rounds before manual continuation: a whole number from 1 to 1,000.'];
    }
    return node.max_iterations > ceiling
        ? [`Maximum rounds ${node.max_iterations} exceeds the current administrator ceiling of ${ceiling} for new runs. The authored value is preserved; choose an allowed maximum before starting a new run.`]
        : [];
}

export function loopSelectionErrors(node: WorkflowForEachNode, ceiling = MAX_LOOP_ITEMS): string[] {
    const errors: string[] = [];
    const limit = Math.min(node.max_items, ceiling);
    if (!Number.isInteger(node.max_items) || node.max_items < 1 || node.max_items > MAX_LOOP_ITEMS) {
        errors.push('Loop maximum must be a whole number from 1 to 5,000.');
    }
    const iterable = node.iterable;
    const scopes = iterable.kind === 'workspace_query' ? iterable.scopes : iterable.kind === 'documents' ? iterable.documents : [];
    scopes.forEach((scope) => {
        if (scope.scope_type !== 'personal' && !scope.scope_id?.trim()) errors.push('Group and public loop sources require an explicit workspace ID.');
        if (scope.scope_type === 'personal' && scope.scope_id !== undefined) errors.push('Personal loop ownership is server-derived; omit the scope ID.');
    });
    if (iterable.kind === 'documents') {
        if (iterable.documents.some((document) => !document.document_id.trim())) errors.push('Select an identified document for every loop item.');
        const identities = iterable.documents.map((document) => `${document.scope_type}:${document.scope_id ?? ''}:${document.document_id}`);
        if (new Set(identities).size !== identities.length) errors.push('Each selected document must appear only once in this loop.');
        if (iterable.documents.length > limit) {
            errors.push(`This selection has ${iterable.documents.length} documents. This loop allows ${limit} items. Select ${limit} or fewer documents before starting a new run.`);
        }
    } else if (iterable.kind === 'workspace_query') {
        if (!iterable.scopes.length || iterable.scopes.length > 100) errors.push('Choose between 1 and 100 authorized workspaces for the query.');
        if (new Set(iterable.scopes.map((scope) => `${scope.scope_type}:${scope.scope_id ?? ''}`)).size !== iterable.scopes.length) {
            errors.push('Query workspaces must be unique.');
        }
        Object.entries(iterable.filters).forEach(([name, value]) => {
            if (name !== 'tags' && (typeof value !== 'string' || !value.trim() || value.length > 1000)) {
                errors.push('Query metadata filters must contain 1 to 1,000 characters; clear unused filters.');
            }
        });
        const tags = iterable.filters.tags ?? [];
        if (tags.length > 100 || new Set(tags).size !== tags.length || tags.some((tag) => !tag.trim() || tag.length > 256)) {
            errors.push('Use at most 100 unique query tags, each with 1 to 256 characters.');
        }
        if (iterable.content && !iterable.content.query.trim()) errors.push('Enter a content query or choose metadata only.');
        if (iterable.content && iterable.content.query.length > 4000) errors.push('Content queries must be 4,000 characters or fewer.');
        if (iterable.content?.mode === 'hybrid' && iterable.selection.mode !== 'best_n') {
            errors.push('Semantic / hybrid queries require Best N; they cannot promise exhaustive All matches.');
        }
        if (iterable.selection.mode === 'best_n' &&
            (!Number.isInteger(iterable.selection.count) || iterable.selection.count < 1 || iterable.selection.count > limit)) {
            errors.push(`Best N must be a whole number from 1 to the effective limit of ${limit} items.`);
        }
        if (iterable.selection.mode === 'best_n' && !iterable.content) errors.push('Best N needs an explicit keyword or semantic / hybrid content query.');
    }
    return errors;
}

export function convertToStructuredWorkflow(workflow: WorkflowDefinition, rootId: string): WorkflowDefinition {
    if (workflow.definition_version > 2) throw new Error('Only legacy workflow definitions can be converted.');
    if (workflow.error_handling.strategy === 'continue' && workflow.tasks.some((task, index) => index > 0 && task.inputs == null)) {
        throw new Error('Choose explicit task inputs before converting a continue-on-error workflow. Automatic previous-successful bindings cannot be converted without changing their meaning.');
    }
    const converted = structuredClone(workflow);
    let inheritedAction: WorkflowDocumentAction | undefined;
    if (isRecord(converted.document_action)) {
        const type = converted.document_action.type;
        if (type !== 'none' && type !== 'search' && type !== 'analyze' && type !== 'comparison') {
            throw new Error('Choose an explicit supported document action before converting this workflow.');
        }
        inheritedAction = { ...structuredClone(converted.document_action), type };
    }
    converted.tasks = converted.tasks.map((task, index) => {
        const previous = converted.tasks[index - 1];
        const bindings = task.inputs ?? (previous ? [{
            name: 'previous', task_id: previous.id, output: 'authoritative' as const,
            required: true, expected_kind: 'any' as const,
        }] : []);
        return {
            ...task,
            inputs: bindings.map((binding) => isFlowBinding(binding) ? binding : {
                ...flowBinding(binding.name, binding.task_id, binding.output),
                required: binding.required,
                expected_kind: binding.expected_kind,
                allow_partial: converted.tasks.find((producer) => producer.id === binding.task_id)?.output_contract?.allow_partial === true,
            }),
            reference_ids: task.reference_ids ?? converted.reference_inputs.map((reference) => reference.id),
            document_action: task.document_action ?? (index === 0 ? inheritedAction : undefined) ?? { type: 'none' },
        };
    });
    converted.definition_version = 3;
    converted.durable_execution = true;
    converted.limits = { ...DEFAULT_FLOW_LIMITS };
    converted.flow = {
        id: rootId,
        nodes: converted.tasks.map((task) => ({ id: task.id, kind: 'task', task_id: task.id })),
        outputs: [],
    };
    return converted;
}

function onlyFields(value: object, fields: string[], errors: string[], label: string) {
    if (Object.keys(value).some((field) => !fields.includes(field))) errors.push(`${label} contains unsupported executable fields.`);
}

export function flowUnsupportedReason(workflow: WorkflowDefinition, options?: WorkflowEditorOptions): string {
    if (workflow.editor_readonly_reason) return workflow.editor_readonly_reason;
    for (const task of workflow.tasks) {
        const publication = task.publication;
        if (publication === undefined) continue;
        if (!isRecord(publication) || Object.keys(publication).some((key) => ![
            'source_kind', 'artifact_format', 'workspace_scope', 'group_id', 'public_workspace_id', 'completion_policy',
        ].includes(key))) {
            return 'This publication contains unsupported fields. Its original configuration is preserved and read-only.';
        }
        if (Object.hasOwn(publication, 'source_kind') &&
            publication.source_kind !== 'native_analysis' && publication.source_kind !== 'saved_output') {
            return 'This publication contains an unsupported source kind. Its original configuration is preserved and read-only.';
        }
        const savedOutput = publication.source_kind === 'saved_output';
        if (savedOutput && (workflow.definition_version !== 3 || workflow.durable_execution !== true)) {
            return 'Saved workflow output publication requires a durable definition-v3 workflow. The saved definition is preserved and read-only.';
        }
        if (savedOutput ? publication.artifact_format !== 'json'
            : !['md', 'csv', 'json'].includes(publication.artifact_format)) {
            return 'This publication contains an unsupported source/format combination. Its original configuration is preserved and read-only.';
        }
        if (savedOutput && options && !options.publication_source_capabilities?.some((capability) =>
            capability.source_kind === 'saved_output' && capability.output_kinds.includes('records') &&
            capability.artifact_formats.includes('json'))) {
            return 'This server does not support the saved workflow output publication source/format. Its original configuration is preserved and read-only.';
        }
        if (!Object.hasOwn(publication, 'completion_policy')) continue;
        const policy = publication.completion_policy;
        if (typeof policy !== 'string' || !['submitted', 'approved', 'indexed_ready'].includes(policy)) {
            return 'This publication contains an unsupported completion policy. Its original configuration is preserved and read-only.';
        }
        if (workflow.definition_version !== 3 || workflow.durable_execution !== true) {
            return 'Publication completion policies require a durable definition-v3 workflow. The saved definition is preserved and read-only.';
        }
        if (options && !options.supported_publication_completion_policies?.includes(policy)) {
            return 'This server does not support the saved publication completion policy. Its original configuration is preserved and read-only.';
        }
    }
    if (workflow.definition_version !== 3) return '';
    if (!isFlowRegion(workflow.flow)) return 'This structured definition contains an unsupported or malformed region, node, binding, or condition.';
    if (!Array.isArray(workflow.flow.outputs)) return 'This structured definition must explicitly declare root outputs, including an empty list. Its saved definition is preserved.';
    const errors: string[] = [];
    const operand = (value: WorkflowOperand) =>
        onlyFields(value, 'literal' in value ? ['literal'] : ['input', 'path'], errors, 'Condition operand');
    const predicate = (value: WorkflowPredicate) => {
        if (value.op === 'all' || value.op === 'any') {
            onlyFields(value, ['op', 'conditions'], errors, 'Condition');
            value.conditions.forEach(predicate);
        } else if (value.op === 'not') {
            onlyFields(value, ['op', 'condition'], errors, 'Condition');
            predicate(value.condition);
        } else if (value.op === 'exists') {
            onlyFields(value, ['op', 'value'], errors, 'Condition');
            operand(value.value);
        } else if ('left' in value) {
            onlyFields(value, ['op', 'left', 'right'], errors, 'Condition');
            operand(value.left);
            operand(value.right);
        }
    };
    const bindings = (values: (WorkflowFlowBinding | WorkflowInputBinding)[]) => values.forEach((binding) => {
        if (!isFlowBinding(binding)) {
            errors.push('Structured task inputs require supported explicit bindings.');
            return;
        }
        onlyFields(binding, ['name', 'source', 'required', 'expected_kind', 'allow_partial'], errors, 'Input');
        onlyFields(binding.source, binding.source.kind === 'loop_item' ? ['kind', 'loop_id', 'scope']
            : binding.source.kind === 'repeat_state' ? ['kind', 'loop_id', 'state_name', 'scope']
                : ['kind', 'node_id', 'output', 'scope'], errors, 'Input source');
        if (options && binding.source.kind !== 'node_output' && !options.supported_binding_sources?.includes(binding.source.kind)) {
            errors.push('This server does not support the saved current loop item or Repeat state binding. The saved definition is preserved.');
        }
    });
    const outputContract = (contract: WorkflowOutputContract | WorkflowRepeatStateContract) =>
        onlyFields(contract, ['kind', 'schema', 'expected_count', 'identity_field', 'require_complete_coverage', 'allow_partial'], errors, 'Output contract');
    const walk = (region: WorkflowFlowRegion, exports = false) => {
        onlyFields(region, exports ? ['id', 'nodes', 'outputs'] : ['id', 'nodes'], errors, 'Region');
        bindings(region.outputs ?? []);
        region.nodes.forEach((node) => {
            if (options && ['for_each', 'collect', 'repeat_until'].includes(node.kind) && !options.supported_node_kinds?.includes(node.kind)) {
                errors.push(`This server does not support ${node.kind} nodes. The saved definition is preserved.`);
            }
            if (node.kind === 'task') {
                onlyFields(node, ['id', 'kind', 'task_id', 'run_when'], errors, 'Task node');
                if (node.run_when) predicate(node.run_when);
            } else if (node.kind === 'collect') {
                onlyFields(node, ['id', 'kind', 'source', 'output_contract'], errors, 'Collect');
                onlyFields(node.source, ['loop_id', 'output'], errors, 'Collect source');
                outputContract(node.output_contract);
            } else if (node.kind === 'repeat_until') {
                onlyFields(node, ['id', 'kind', 'max_iterations', 'state', 'body', 'until', 'exports'], errors, 'Repeat until');
                if (options && !supportsWorkflowRepeat(options)) errors.push('This server does not expose supported Repeat state and iteration policy capabilities. The saved definition is preserved.');
                node.state.forEach((slot) => {
                    onlyFields(slot, ['name', 'initial', 'next', 'output_contract'], errors, 'Repeat state');
                    bindings([{ name: slot.name, source: slot.initial, required: true,
                        expected_kind: slot.output_contract.kind, allow_partial: slot.output_contract.allow_partial === true }]);
                    outputContract(slot.output_contract);
                });
                node.exports.forEach((item) => onlyFields(item, ['name', 'output'], errors, 'Repeat export'));
                predicate(node.until);
                walk(node.body, true);
            } else if (node.kind === 'for_each') {
                onlyFields(node, ['id', 'kind', 'inputs', 'iterable', 'item_key', 'max_items', 'body'], errors, 'For each');
                bindings(node.inputs);
                const iterable = node.iterable;
                if (options && !options.supported_iterable_kinds?.includes(iterable.kind)) {
                    errors.push('This server does not support this loop source. The saved definition is preserved.');
                }
                if (iterable.kind === 'input') onlyFields(iterable, ['kind', 'name'], errors, 'Saved collection');
                else if (iterable.kind === 'documents') {
                    onlyFields(iterable, ['kind', 'documents'], errors, 'Selected documents');
                    iterable.documents.forEach((document) =>
                        onlyFields(document, ['document_id', 'scope_type', 'scope_id'], errors, 'Loop document'));
                } else {
                    onlyFields(iterable, ['kind', 'scopes', 'filters', 'content', 'selection'], errors, 'Workspace query');
                    iterable.scopes.forEach((scope) => onlyFields(scope, ['scope_type', 'scope_id'], errors, 'Query scope'));
                    onlyFields(iterable.filters, ['search', 'classification', 'author', 'keywords', 'abstract', 'tags'], errors, 'Query filters');
                    if (iterable.content) onlyFields(iterable.content, ['mode', 'query'], errors, 'Query content');
                    onlyFields(iterable.selection, iterable.selection.mode === 'best_n' ? ['mode', 'count'] : ['mode'], errors, 'Query selection');
                    if (options && !options.supported_query_modes?.includes(iterable.selection.mode)) {
                        errors.push('This server does not support this query selection. The saved definition is preserved.');
                    }
                }
                walk(node.body, true);
            } else {
                bindings(node.inputs);
                predicate(node.condition);
                if (node.kind === 'route') {
                    onlyFields(node, ['id', 'kind', 'inputs', 'condition', 'target'], errors, 'Route');
                    onlyFields(node.target, 'node_id' in node.target ? ['node_id'] : ['exit_region_id'], errors, 'Route target');
                } else {
                    onlyFields(node, ['id', 'kind', 'inputs', 'condition', 'then', 'else', 'join'], errors, 'If/else');
                    onlyFields(node.join, ['id', 'exports'], errors, 'Join');
                    node.join.exports.forEach((item) => {
                        onlyFields(item, ['name', 'expected_kind', 'required', 'then', 'else'], errors, 'Join output');
                        onlyFields(item.then, ['node_id', 'output'], errors, 'Join source');
                        onlyFields(item.else, ['node_id', 'output'], errors, 'Join source');
                    });
                    walk(node.then);
                    walk(node.else);
                }
            }
        });
    };
    walk(workflow.flow, true);
    workflow.tasks.forEach((task) => {
        onlyFields(task, [
            'id', 'type', 'name', 'instructions', 'order', 'runner', 'document_action', 'inputs',
            'reference_ids', 'output_contract', 'approval', 'publication', 'input_processing',
        ], errors, 'Task configuration');
        if (task.input_processing !== undefined && !['full', 'saved_record_report'].includes(task.input_processing)) {
            errors.push('This task contains an unsupported large-input processing mode. Its original configuration is preserved.');
        }
        if (options && task.input_processing !== undefined && !options.supported_input_processing_modes?.includes(task.input_processing)) {
            errors.push('This server does not support this task input-processing mode. The saved definition is preserved.');
        }
        onlyFields(task.runner, ['type', 'selected_agent', 'model_endpoint_id', 'model_id', 'model_provider', 'model_binding_summary'], errors, 'Task runner');
        bindings(task.inputs ?? []);
        if (task.output_contract) outputContract(task.output_contract);
        if (task.document_action?.target_mode === 'current_item') {
            onlyFields(task.document_action, ['type', 'target_mode', 'loop_id', 'analysis_mode'], errors, 'Current document Analyze');
            if (task.document_action.type !== 'analyze' || task.document_action.analysis_mode !== 'combined' ||
                typeof task.document_action.loop_id !== 'string') {
                errors.push('This current-document action is not supported by the editor.');
            }
        }
    });
    if (isRecord(workflow.limits)) onlyFields(workflow.limits, ['max_executions', 'deadline_seconds'], errors, 'Run limits');
    return errors[0] ?? '';
}

interface Availability {
    possible: Set<string>;
    definite: Set<string>;
}

function combineAvailability(paths: Availability[]): Availability {
    const possible = new Set(paths.flatMap((path) => [...path.possible]));
    const definite = new Set(paths[0]?.definite ?? []);
    paths.forEach((path) => definite.forEach((id) => { if (!path.definite.has(id)) definite.delete(id); }));
    return { possible, definite };
}

function withProducer(available: Availability, id: string, definite: boolean): Availability {
    return {
        possible: new Set([...available.possible, id]),
        definite: new Set([...available.definite, ...(definite ? [id] : [])]),
    };
}

export interface WorkflowFlowAnalysis {
    errors: string[];
    available: Map<string, Set<string>>;
    branchEnds: Map<string, Set<string>>;
}

export function analyzeWorkflowFlow(workflow: WorkflowDefinition): WorkflowFlowAnalysis {
    const errors: string[] = [];
    const available = new Map<string, Set<string>>();
    const branchEnds = new Map<string, Set<string>>();
    const result = { errors, available, branchEnds };
    if (workflow.definition_version !== 3) return result;
    const unsupported = flowUnsupportedReason(workflow);
    if (unsupported || !isFlowRegion(workflow.flow)) {
        errors.push(unsupported || 'Structured control flow is required.');
        return result;
    }
    if (workflow.durable_execution !== true) errors.push('Structured control flow requires durable execution.');
    const producers = new Map(flowProducers(workflow).map((producer) => [producer.id, producer]));
    const tasks = new Map(workflow.tasks.map((task) => [task.id, task]));
    const loops = new Map(flowLoops(workflow).map((loop) => [loop.node.id, loop]));
    const usedTasks = new Set<string>();
    const ids = new Set<string>();
    const root = workflow.flow;
    const register = (id: string) => {
        if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(id)) errors.push('Flow IDs must use letters, digits, dots, colons, underscores or hyphens, up to 128 characters.');
        if (ids.has(id)) errors.push(`Flow ID ${id} is duplicated.`);
        ids.add(id);
    };
    const shape = (region: WorkflowFlowRegion, depth: number) => {
        register(region.id);
        if (depth > FLOW_MAX_DEPTH) errors.push(`Structured flow supports at most ${FLOW_MAX_DEPTH} nested regions.`);
        region.nodes.forEach((node) => {
            register(node.id);
            if (node.kind === 'task') {
                if (!tasks.has(node.task_id)) errors.push(`Node ${node.id} references a missing task.`);
                if (usedTasks.has(node.task_id)) errors.push('Each task configuration must appear exactly once in the flow.');
                usedTasks.add(node.task_id);
            } else if (node.kind === 'if') {
                register(node.join.id);
                shape(node.then, depth + 1);
                shape(node.else, depth + 1);
            } else if (node.kind === 'for_each' || node.kind === 'repeat_until') {
                shape(node.body, depth + 1);
                errors.push(...(node.kind === 'for_each' ? loopSelectionErrors(node) : repeatIterationErrors(node))
                    .map((error) => `${node.id}: ${error}`));
            }
        });
    };
    shape(root, 1);
    if (ids.size > FLOW_MAX_NODES) errors.push(`Structured flow supports at most ${FLOW_MAX_NODES} IDs.`);
    if (workflow.tasks.some((task) => !usedTasks.has(task.id))) errors.push('Every task configuration must be placed in the flow.');
    const checkSource = (source: WorkflowJoinSource, required: boolean, state: Availability, label: string, expected: WorkflowOutputKind) => {
        const producer = producers.get(source.node_id);
        const output = producer?.outputs.find((item) => item.name === source.output);
        if (!producer || !output) {
            errors.push(`${label} selects a missing producer or undeclared output.`);
            return;
        }
        if (!state.possible.has(source.node_id)) errors.push(`${label} must select an earlier, reachable producer in this scope.`);
        if (required && (!state.definite.has(source.node_id) || !output.required)) {
            errors.push(`${label} requires an output that can be skipped. Use an optional input or a required branch-join output.`);
        }
        if (expected !== 'any' && output.kind !== 'any' && output.kind !== expected &&
            !(expected === 'json' && ['records', 'document_results'].includes(output.kind))) {
            errors.push(`${label} has an expected kind that disagrees with its producer.`);
        }
    };
    const checkBindings = (bindings: WorkflowFlowBinding[], state: Availability, label: string, parents: WorkflowLoopControl[]) => {
        const names = new Set<string>();
        bindings.forEach((binding) => {
            if (!FLOW_ALIAS_PATTERN.test(binding.name)) errors.push(`${label} needs valid input aliases (letter first, up to 64 letters, digits, underscores or dashes).`);
            if (names.has(binding.name)) errors.push(`${label} has duplicate input aliases.`);
            names.add(binding.name);
            if (binding.source.kind === 'loop_item') {
                const loopId = binding.source.loop_id;
                if (!parents.some((node) => node.kind === 'for_each' && node.id === loopId)) errors.push(`${label}: ${binding.name} must select a current item from an enclosing For each.`);
                if (!['json', 'any'].includes(binding.expected_kind) || binding.allow_partial) errors.push(`${label}: current items are complete JSON values, not partial outputs.`);
            } else if (binding.source.kind === 'repeat_state') {
                const source = binding.source;
                const repeat = parents.find((node): node is WorkflowRepeatUntilNode => node.kind === 'repeat_until' && node.id === source.loop_id);
                const slot = repeat?.state.find((item) => item.name === source.state_name);
                if (!slot) errors.push(`${label}: ${binding.name} must select a named current state slot from an enclosing Repeat.`);
                else if (binding.expected_kind !== 'any' && binding.expected_kind !== slot.output_contract.kind) {
                    errors.push(`${label}: ${binding.name} must retain its Repeat state's declared kind.`);
                }
            } else checkSource(binding.source, binding.required, state, `${label}: ${binding.name || 'input'}`, binding.expected_kind);
        });
    };
    const checkPredicate = (condition: WorkflowPredicate, bindings: WorkflowFlowBinding[], label: string) => {
        let count = 0;
        const operand = (value: WorkflowOperand, scalar = true): string[] => {
            if ('literal' in value) {
                if (typeof value.literal === 'number' && !Number.isFinite(value.literal)) errors.push(`${label} requires finite numeric values.`);
                return [value.literal === null ? 'null' : typeof value.literal];
            }
            const binding = bindings.find((input) => input.name === value.input);
            if (!binding) errors.push(`${label} references an input that has not been bound.`);
            if (value.path !== '' && (!value.path.startsWith('/') || /~(?:[^01]|$)/.test(value.path))) {
                errors.push(`${label} needs a valid JSON pointer for its field.`);
            }
            if (binding) {
                const schema = flowBindingSchema(workflow, binding);
                if (!schema) errors.push(`${label} must select a schema-validated producer field.`);
                else {
                    const field = workflowSchemaAtPointer(schema, value.path);
                    if (!field) errors.push(`${label} references a field that is not declared in its producer's schema.`);
                    const types = field && (Array.isArray(field.type) ? field.type : [field.type]);
                    if (types?.every((type): type is string => typeof type === 'string')) {
                        if (scalar && types.some((type) => !['string', 'number', 'integer', 'boolean', 'null'].includes(type))) {
                            errors.push(`${label} must compare scalar fields, not whole objects or collections.`);
                        }
                        return types;
                    }
                }
            }
            return [];
        };
        const walk = (predicate: WorkflowPredicate, depth: number) => {
            count++;
            if (depth > FLOW_MAX_PREDICATE_DEPTH) {
                errors.push(`${label} exceeds the condition nesting limit.`);
                return;
            }
            if (predicate.op === 'all' || predicate.op === 'any') {
                if (!predicate.conditions.length) errors.push(`${label} needs at least one condition.`);
                predicate.conditions.forEach((child) => walk(child, depth + 1));
            } else if (predicate.op === 'not') {
                walk(predicate.condition, depth + 1);
            } else if (predicate.op === 'exists') {
                count++;
                if (!('input' in predicate.value)) errors.push(`${label} existence checks require an input field.`);
                operand(predicate.value, false);
            } else if ('left' in predicate) {
                count += 2;
                const leftTypes = operand(predicate.left);
                const rightTypes = operand(predicate.right);
                if (['lt', 'lte', 'gt', 'gte'].includes(predicate.op) &&
                    [leftTypes, rightTypes].some((types) => types.length && !types.some((type) => type === 'number' || type === 'integer'))) {
                    errors.push(`${label} numeric comparisons require numeric fields and values.`);
                }
            }
        };
        walk(condition, 1);
        if (count > FLOW_MAX_PREDICATE_NODES || JSON.stringify(condition).length > 16384) errors.push(`${label} exceeds the condition size limit.`);
    };
    const walk = (region: WorkflowFlowRegion, incoming: Availability, parents: WorkflowLoopControl[] = [], branch = false): Availability => {
        if (parents.length > 3) errors.push('At most three enclosing For each or Repeat frames are supported.');
        const inputs = new Map<number, Availability[]>();
        const exits: Availability[] = [];
        let current = incoming;
        region.nodes.forEach((node, index) => {
            current = combineAvailability([current, ...(inputs.get(index) ?? [])]);
            available.set(node.id, new Set(current.possible));
            if (node.kind === 'task') {
                const task = tasks.get(node.task_id);
                if (!task) return;
                const bindings = (task.inputs ?? []).filter(isFlowBinding);
                checkBindings(bindings, current, task.name || node.id, parents);
                if (task.document_action?.target_mode === 'current_item') {
                    const loop = parents.find((item): item is WorkflowForEachNode => item.kind === 'for_each' && item.id === task.document_action?.loop_id);
                    if (!loop || loop.iterable.kind === 'input') {
                        errors.push(`${task.name}: current-document Analyze requires an enclosing document selection or workspace query, not a saved record containing a document ID.`);
                    }
                }
                if (task.publication) {
                    const savedOutput = task.publication.source_kind === 'saved_output';
                    if (savedOutput) {
                        const binding = bindings[0];
                        const source = binding?.source;
                        const output = source?.kind === 'node_output'
                            ? producers.get(source.node_id)?.outputs.find((item) => item.name === source.output) : undefined;
                        if (bindings.length !== 1 || !binding.required || binding.expected_kind !== 'records' ||
                            source?.kind !== 'node_output' || !output || !isRecordsFlowOutput(output)) {
                            errors.push(`${task.name} publication requires exactly one required saved records node output from a task, Collect, or explicit join. Text, scalar JSON, document results, and current loop items cannot be exported.`);
                        }
                    } else if (bindings.length !== 1) {
                        errors.push(`${task.name} publication requires exactly one explicit native Analyze input.`);
                    }
                    if (!['md', 'csv', 'json'].includes(task.publication.artifact_format) ||
                        !['personal', 'group', 'public'].includes(task.publication.workspace_scope)) {
                        errors.push(`${task.name} publication needs a supported format and explicit destination.`);
                    }
                    if (task.publication.workspace_scope === 'group' && !task.publication.group_id?.trim() ||
                        task.publication.workspace_scope === 'public' && !task.publication.public_workspace_id?.trim()) {
                        errors.push(`${task.name} publication needs the destination workspace ID.`);
                    }
                    if (task.runner.type !== 'inherit' || task.document_action && task.document_action.type !== 'none') {
                        errors.push(`${task.name} publication cannot invoke a model, agent, or document action.`);
                    }
                }
                if (node.run_when) checkPredicate(node.run_when, bindings, `Run when for ${task.name || node.id}`);
                current = withProducer(current, node.id, node.run_when === undefined);
            } else if (node.kind === 'for_each') {
                checkBindings(node.inputs, current, node.id, parents);
                if (node.iterable.kind === 'input') {
                    const name = node.iterable.name;
                    const binding = node.inputs.find((item) => item.name === name);
                    const source = binding?.source;
                    const output = source && flowSourceOutput(workflow, source);
                    if (!binding || !binding.required || binding.allow_partial ||
                        source?.kind !== 'node_output' && source?.kind !== 'repeat_state' ||
                        !output || !['records', 'document_results'].includes(output.kind)) {
                        errors.push(`${node.id}: choose a required, complete saved records or document-results producer or current Repeat state.`);
                    }
                }
                const bodyEnd = walk(node.body, current, [...parents, node]);
                node.body.outputs.forEach((binding) => {
                    if (binding.source.kind !== 'node_output' ||
                        !sameEditorValue(enclosingFlowLoopControls(workflow, binding.source.node_id).map((loop) => loop.id), [...parents, node].map((loop) => loop.id))) {
                        errors.push(`Body outputs for ${node.id} must select an exact producer in this loop's body scope.`);
                    }
                });
                checkBindings(node.body.outputs, bodyEnd, `Body outputs for ${node.id}`, [...parents, node]);
                current = withProducer(current, node.id, true);
            } else if (node.kind === 'repeat_until') {
                if (!node.state.length || node.state.length > 100) errors.push(`${node.id}: declare between 1 and 100 named state slots.`);
                checkBindings(node.state.map((slot) => ({
                    name: slot.name, source: slot.initial, required: true, expected_kind: slot.output_contract.kind,
                    allow_partial: slot.output_contract.allow_partial === true,
                })), current, `Initial state for ${node.id}`, parents);
                const bodyParents = [...parents, node];
                const bodyEnd = walk(node.body, current, bodyParents);
                checkBindings(node.body.outputs, bodyEnd, `Body outputs for ${node.id}`, bodyParents);
                node.body.outputs.forEach((binding) => {
                    if (binding.source.kind === 'loop_item' ||
                        binding.source.kind === 'node_output' && !sameEditorValue(
                            enclosingFlowLoopControls(workflow, binding.source.node_id).map((loop) => loop.id),
                            bodyParents.map((loop) => loop.id))) {
                        errors.push(`Body outputs for ${node.id} must select a producer in this body scope or explicitly pass current Repeat state unchanged.`);
                    }
                });
                node.state.forEach((slot) => {
                    const next = node.body.outputs.find((binding) => binding.name === slot.next);
                    if (!next || !next.required) errors.push(`${node.id}: state ${slot.name} needs a required, declared next body output.`);
                    const initialOutput = flowSourceOutput(workflow, slot.initial);
                    const nextOutput = next && flowSourceOutput(workflow, next.source);
                    for (const [phase, output] of [['Initial', initialOutput], ['Next', nextOutput]] as const) {
                        if (output && (output.kinds ?? [output.kind]).some((kind) => kind !== slot.output_contract.kind)) {
                            errors.push(`${node.id}: ${phase} state ${slot.name} must have exactly kind ${slot.output_contract.kind}; kinds are never coerced.`);
                        }
                    }
                    if (slot.output_contract.kind === 'json' && !slot.output_contract.schema) {
                        errors.push(`${node.id}: JSON state ${slot.name} needs an explicit supported schema.`);
                    }
                });
                checkPredicate(node.until, repeatUntilBindings(node), `Stop after a round for ${node.id}`);
                const names = new Set<string>();
                node.exports.forEach((item) => {
                    if (!FLOW_ALIAS_PATTERN.test(item.name) || names.has(item.name)) errors.push(`${node.id}: final exports need unique, valid names.`);
                    names.add(item.name);
                    if (!node.body.outputs.some((binding) => binding.name === item.output)) errors.push(`${node.id}: final export ${item.name} selects a missing body output.`);
                });
                current = withProducer(current, node.id, true);
            } else if (node.kind === 'collect') {
                const source = loops.get(node.source.loop_id);
                const output = source?.node.body.outputs.find((item) => item.name === node.source.output);
                if (!source || !output) errors.push(`${node.id}: select an existing loop and declared body output for Collect.`);
                else {
                    if (!sameEditorValue(enclosingFlowLoopControls(workflow, source.node.id).map((loop) => loop.id), parents.map((loop) => loop.id)) ||
                        !current.definite.has(source.node.id)) {
                        errors.push(`${node.id}: Collect must follow its loop in that loop's enclosing scope on every reaching path.`);
                    }
                    const representation = output.source.kind === 'node_output' ? producers.get(output.source.node_id)?.outputs
                        .find((item) => output.source.kind === 'node_output' && item.name === output.source.output) : undefined;
                    if (!representation || !['records', 'document_results'].includes(representation.kind) ||
                        representation.kind !== node.output_contract.kind) {
                        errors.push(`${node.id}: Collect must preserve a records or document-results body output's kind.`);
                    }
                    if ((!output.required || output.allow_partial) &&
                        (!node.output_contract.allow_partial || node.output_contract.require_complete_coverage)) {
                        errors.push(`${node.id}: optional or partial body outputs need explicit partial acceptance without requiring complete coverage.`);
                    }
                }
                current = withProducer(current, node.id, true);
            } else {
                checkBindings(node.inputs, current, node.id, parents);
                checkPredicate(node.condition, node.inputs, `Condition for ${node.id}`);
                if (node.kind === 'route') {
                    if ('exit_region_id' in node.target) {
                        if (!branch || node.target.exit_region_id !== region.id) {
                            errors.push(`Route ${node.id} can exit only its current branch region.`);
                        } else exits.push(current);
                    } else {
                        const targetId = node.target.node_id;
                        const target = region.nodes.findIndex((item) => item.id === targetId);
                        if (target <= index) errors.push(`Route ${node.id} must target a later sibling; branch entry and backward routes are not allowed.`);
                        else inputs.set(target, [...(inputs.get(target) ?? []), current]);
                    }
                } else {
                    const thenEnd = walk(node.then, current, parents, true);
                    const elseEnd = walk(node.else, current, parents, true);
                    const names = new Set<string>();
                    node.join.exports.forEach((item) => {
                        if (!FLOW_ALIAS_PATTERN.test(item.name) || names.has(item.name)) errors.push(`Join ${node.join.id} needs unique, valid output names.`);
                        names.add(item.name);
                        checkSource(item.then, item.required, thenEnd, `Then output ${item.name}`, item.expected_kind);
                        checkSource(item.else, item.required, elseEnd, `Else output ${item.name}`, item.expected_kind);
                    });
                    current = withProducer(current, node.join.id, true);
                }
            }
        });
        const end = combineAvailability([current, ...exits]);
        branchEnds.set(region.id, end.possible);
        available.set(region.id, end.possible);
        return end;
    };
    const end = walk(root, { possible: new Set(), definite: new Set() });
    available.set(root.id, end.possible);
    checkBindings(root.outputs ?? [], end, 'Final outputs', []);
    const limits = workflow.limits;
    if (!isRecord(limits) || !Number.isInteger(limits.max_executions) ||
        Number(limits.max_executions) < 1 || Number(limits.max_executions) > DEFAULT_FLOW_LIMITS.max_executions) {
        errors.push('Execution limit must be a whole number from 1 to 5,000.');
    }
    if (!isRecord(limits) || !Number.isInteger(limits.deadline_seconds) ||
        Number(limits.deadline_seconds) < 1 || Number(limits.deadline_seconds) > DEFAULT_FLOW_LIMITS.deadline_seconds) {
        errors.push('Elapsed deadline must be a whole number from 1 to 86,400 seconds, including waits.');
    }
    result.errors = [...new Set(errors)];
    return result;
}

export function predicateSummary(condition: WorkflowPredicate): string {
    const operand = (value: WorkflowOperand) =>
        'literal' in value ? JSON.stringify(value.literal) : `${value.input || 'Choose input'}${value.path.replaceAll('/', '.')}`;
    if (condition.op === 'all' || condition.op === 'any') {
        return condition.conditions.map(predicateSummary).join(condition.op === 'all' ? ' AND ' : ' OR ');
    }
    if (condition.op === 'not') return `NOT (${predicateSummary(condition.condition)})`;
    if (condition.op === 'exists') return `${operand(condition.value)} exists`;
    if ('left' in condition) {
        const labels: Record<WorkflowComparison, string> = { eq: 'equals', ne: 'does not equal', lt: '<', lte: '<=', gt: '>', gte: '>=' };
        return `${operand(condition.left)} ${labels[condition.op]} ${operand(condition.right)}`;
    }
    return '';
}

export function scalarSchemaFields(schema?: Record<string, unknown>): { path: string; type: string; values?: WorkflowScalar[] }[] {
    const fields: { path: string; type: string; values?: WorkflowScalar[] }[] = [];
    const walk = (value: Record<string, unknown>, path: string, depth: number) => {
        if (depth > 12) return;
        const types = Array.isArray(value.type) ? value.type : [value.type];
        if (types.length && types.every((type) => ['boolean', 'number', 'integer', 'string', 'null'].includes(String(type)))) {
            fields.push({
                path, type: types.join(' | '),
                ...(Array.isArray(value.enum) ? {
                    values: value.enum.filter((item): item is WorkflowScalar =>
                        item === null || typeof item === 'string' || typeof item === 'boolean' ||
                        (typeof item === 'number' && Number.isFinite(item))),
                } : {}),
            });
        }
        if (isRecord(value.properties)) Object.entries(value.properties).forEach(([name, child]) => {
            if (isRecord(child)) walk(child, `${path}/${name.replaceAll('~', '~0').replaceAll('/', '~1')}`, depth + 1);
        });
    };
    if (schema) walk(schema, '', 0);
    return fields;
}

function workflowSchemaAtPointer(schema: Record<string, unknown>, pointer: string): Record<string, unknown> | undefined {
    if (pointer === '') return schema;
    if (!pointer.startsWith('/') || /~(?:[^01]|$)/.test(pointer)) return undefined;
    let current = schema;
    for (const part of pointer.slice(1).split('/').map((value) => value.replaceAll('~1', '/').replaceAll('~0', '~'))) {
        const next = current.type === 'array' && /^(0|[1-9]\d*)$/.test(part)
            ? current.items : isRecord(current.properties) ? current.properties[part] : undefined;
        if (!isRecord(next)) return undefined;
        current = next;
    }
    return current;
}
