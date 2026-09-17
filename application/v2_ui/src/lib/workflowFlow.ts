// workflowFlow.ts
// Structured workflow definitions and side-effect-free List editing helpers.

import type {
    WorkflowDefinition,
    WorkflowInputBinding,
    WorkflowOutputKind,
    WorkflowDocumentAction,
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

export interface WorkflowFlowSource {
    kind: 'node_output';
    node_id: string;
    output: string;
    scope: 'current';
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

export type WorkflowFlowNode = WorkflowTaskNode | WorkflowIfNode | WorkflowRouteNode;

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
export const FLOW_MAX_PREDICATE_DEPTH = 8;
export const FLOW_MAX_PREDICATE_NODES = 100;
export const FLOW_ALIAS_PATTERN = /^[A-Za-z][A-Za-z0-9_-]{0,63}$/;
export const FLOW_OUTPUT_KINDS: WorkflowOutputKind[] = ['any', 'text', 'records', 'json', 'document_results'];
export const FLOW_FINAL_OUTPUTS = ['authoritative', 'text', 'records', 'json', 'documents'] as const;
export const FLOW_COMPARISONS: WorkflowComparison[] = ['eq', 'ne', 'lt', 'lte', 'gt', 'gte'];

export function isFlowBinding(value: unknown): value is WorkflowFlowBinding {
    return isRecord(value) && typeof value.name === 'string' && isRecord(value.source) &&
        value.source.kind === 'node_output' && value.source.scope === 'current' &&
        typeof value.source.node_id === 'string' && typeof value.source.output === 'string' &&
        typeof value.required === 'boolean' && typeof value.allow_partial === 'boolean' &&
        FLOW_OUTPUT_KINDS.some((kind) => kind === value.expected_kind);
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

export interface FlowProducer {
    id: string;
    label: string;
    outputs: { name: string; kind: WorkflowOutputKind; required: boolean; schema?: Record<string, unknown> }[];
}

export function flowProducers(workflow: WorkflowDefinition): FlowProducer[] {
    if (!isFlowRegion(workflow.flow)) return [];
    const tasks = new Map(workflow.tasks.map((task) => [task.id, task]));
    const result: FlowProducer[] = [];
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
        } else if (node.kind === 'if') {
            walk(node.then);
            walk(node.else);
            result.push({
                id: node.join.id,
                label: `Join ${node.id}`,
                outputs: node.join.exports.map((item) => {
                    const thenSchema = result.find((producer) => producer.id === item.then.node_id)?.outputs
                        .find((output) => output.name === item.then.output)?.schema;
                    const elseSchema = result.find((producer) => producer.id === item.else.node_id)?.outputs
                        .find((output) => output.name === item.else.output)?.schema;
                    return {
                        name: item.name, kind: item.expected_kind, required: item.required,
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
        nodes: flow.nodes.map((node) => node.kind === 'if' ? {
            ...node,
            then: updateFlowRegion(node.then, regionId, update),
            else: updateFlowRegion(node.else, regionId, update),
        } : node),
    };
}

export function flowTaskIds(node: WorkflowFlowNode): string[] {
    if (node.kind === 'task') return [node.task_id];
    if (node.kind === 'route') return [];
    return [...node.then.nodes, ...node.else.nodes].flatMap(flowTaskIds);
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

export function flowUnsupportedReason(workflow: WorkflowDefinition): string {
    if (workflow.editor_readonly_reason) return workflow.editor_readonly_reason;
    if (workflow.definition_version !== 3) return '';
    if (!isFlowRegion(workflow.flow)) return 'This structured definition contains an unsupported or malformed region, node, binding, or condition.';
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
            errors.push('Structured task inputs require explicit node-output bindings.');
            return;
        }
        onlyFields(binding, ['name', 'source', 'required', 'expected_kind', 'allow_partial'], errors, 'Input');
        onlyFields(binding.source, ['kind', 'node_id', 'output', 'scope'], errors, 'Input source');
    });
    const walk = (region: WorkflowFlowRegion, root = false) => {
        onlyFields(region, root ? ['id', 'nodes', 'outputs'] : ['id', 'nodes'], errors, 'Region');
        bindings(region.outputs ?? []);
        region.nodes.forEach((node) => {
            if (node.kind === 'task') {
                onlyFields(node, ['id', 'kind', 'task_id', 'run_when'], errors, 'Task node');
                if (node.run_when) predicate(node.run_when);
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
            'reference_ids', 'output_contract', 'approval', 'publication',
        ], errors, 'Task configuration');
        onlyFields(task.runner, ['type', 'selected_agent', 'model_endpoint_id', 'model_id', 'model_provider', 'model_binding_summary'], errors, 'Task runner');
        bindings(task.inputs ?? []);
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
    const checkBindings = (bindings: WorkflowFlowBinding[], state: Availability, label: string) => {
        const names = new Set<string>();
        bindings.forEach((binding) => {
            if (!FLOW_ALIAS_PATTERN.test(binding.name)) errors.push(`${label} needs valid input aliases (letter first, up to 64 letters, digits, underscores or dashes).`);
            if (names.has(binding.name)) errors.push(`${label} has duplicate input aliases.`);
            names.add(binding.name);
            checkSource(binding.source, binding.required, state, `${label}: ${binding.name || 'input'}`, binding.expected_kind);
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
                const output = producers.get(binding.source.node_id)?.outputs.find((item) => item.name === binding.source.output);
                if (!output?.schema) errors.push(`${label} must select a schema-validated producer field.`);
                else {
                    const field = workflowSchemaAtPointer(output.schema, value.path);
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
    const walk = (region: WorkflowFlowRegion, incoming: Availability): Availability => {
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
                checkBindings(bindings, current, task.name || node.id);
                if (task.publication) {
                    if (bindings.length !== 1) errors.push(`${task.name} publication requires exactly one explicit native Analyze input.`);
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
            } else {
                checkBindings(node.inputs, current, node.id);
                checkPredicate(node.condition, node.inputs, `Condition for ${node.id}`);
                if (node.kind === 'route') {
                    if ('exit_region_id' in node.target) {
                        if (region.id === root.id || node.target.exit_region_id !== region.id) {
                            errors.push(`Route ${node.id} can exit only its current branch region.`);
                        } else exits.push(current);
                    } else {
                        const targetId = node.target.node_id;
                        const target = region.nodes.findIndex((item) => item.id === targetId);
                        if (target <= index) errors.push(`Route ${node.id} must target a later sibling; branch entry and backward routes are not allowed.`);
                        else inputs.set(target, [...(inputs.get(target) ?? []), current]);
                    }
                } else {
                    const thenEnd = walk(node.then, current);
                    const elseEnd = walk(node.else, current);
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
        return end;
    };
    const end = walk(root, { possible: new Set(), definite: new Set() });
    available.set(root.id, end.possible);
    checkBindings(root.outputs ?? [], end, 'Final outputs');
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
