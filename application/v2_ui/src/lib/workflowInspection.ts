// workflowInspection.ts
// Authorized read-only projections are separate from editable workflow definitions.

import { api } from './apiClient';
import {
    DEFAULT_FLOW_LIMITS, FLOW_MAX_NODES, MAX_LOOP_ITEMS, MAX_REPEAT_ITERATIONS,
    isFlowBinding, isJoinExport, isRepeatState,
} from './workflowFlow';
import { workflowUrl, type WorkflowDefinition, type WorkflowIterationFrame, type WorkflowScope } from './workflowEditor';
import { isRecord, sameEditorValue } from './workspaceAuthoring';

export type WorkflowInspectionTarget =
    | { kind: 'saved'; workflowId: string }
    | { kind: 'draft'; definition: WorkflowDefinition }
    | { kind: 'run'; workflowId: string; runId: string };

export interface WorkflowInspectionSource {
    kind: WorkflowInspectionTarget['kind'];
    scope_type: 'personal' | 'group';
    scope_id: string;
    workflow_id: string | null;
    run_id: string | null;
    definition_revision: string;
    snapshot_sha256?: string;
}

export const INSPECTION_NODE_KINDS = ['region', 'task', 'if', 'join', 'route', 'for_each', 'repeat_until', 'collect'] as const;
export const INSPECTION_EDGE_KINDS = ['sequence', 'then', 'else', 'join', 'route', 'exit', 'body', 'repeat', 'complete'] as const;
export const INSPECTION_SECTIONS = ['configuration', 'inputs', 'condition', 'outputs', 'state', 'selection'] as const;
export type WorkflowInspectionSection = typeof INSPECTION_SECTIONS[number];
export type InspectionJson = string | number | boolean | null | InspectionJson[] | { [key: string]: InspectionJson };

export interface WorkflowInspectionNode {
    id: string;
    kind: typeof INSPECTION_NODE_KINDS[number];
    label: string;
    parent_id: string | null;
    region_id: string | null;
    order: number;
    loop_ids: string[];
    child_region_ids: string[];
    inputs_count: number;
    outputs_count: number;
    has_condition: boolean;
    task_id?: string;
    max_items?: number;
    max_iterations?: number;
}

export interface WorkflowInspectionEdge {
    id: string;
    source: string;
    target: string;
    kind: typeof INSPECTION_EDGE_KINDS[number];
    label: string;
}

export interface WorkflowFlowProjection {
    projection_version: 1;
    definition_version: 3;
    source: WorkflowInspectionSource;
    name: string;
    root_region_id: string;
    nodes: WorkflowInspectionNode[];
    edges: WorkflowInspectionEdge[];
    limits: { max_executions: number; deadline_seconds: number };
}

export interface WorkflowInspectionDetails {
    projection_version: 1;
    source: WorkflowInspectionSource;
    node_id: string;
    section: WorkflowInspectionSection;
    items: { label: string; value: InspectionJson }[];
    total_count: number;
    next_cursor: string | null;
}

const logicalId = (value: unknown): value is string =>
    typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value);
const digest = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const identifier = (value: unknown): value is string =>
    typeof value === 'string' && value.trim() === value && value.length > 0 && value.length <= 256;
const boundedText = (value: unknown, maximum = 1024): value is string => typeof value === 'string' && value.length <= maximum;
const integer = (value: unknown, maximum: number, minimum = 0): value is number =>
    typeof value === 'number' && Number.isSafeInteger(value) && value >= minimum && value <= maximum;
const onlyKeys = (value: Record<string, unknown>, keys: readonly string[]) => Object.keys(value).every((key) => keys.includes(key));

function isSource(value: unknown): value is WorkflowInspectionSource {
    return isRecord(value) && onlyKeys(value, [
        'kind', 'scope_type', 'scope_id', 'workflow_id', 'run_id', 'definition_revision', 'snapshot_sha256',
    ]) && (value.kind === 'saved' || value.kind === 'draft' || value.kind === 'run') &&
        (value.scope_type === 'personal' || value.scope_type === 'group') && identifier(value.scope_id) &&
        (value.workflow_id === null || identifier(value.workflow_id)) &&
        (value.run_id === null || identifier(value.run_id)) &&
        (value.kind === 'draft' ? typeof value.definition_revision === 'string' &&
            /^DRAFT:[a-f0-9]{64}$/.test(value.definition_revision) : digest(value.definition_revision)) &&
        (value.snapshot_sha256 === undefined || digest(value.snapshot_sha256)) &&
        (value.kind === 'run' ? identifier(value.run_id) && identifier(value.workflow_id) : value.run_id === null) &&
        (value.kind !== 'saved' || identifier(value.workflow_id));
}

function sourceMatchesTarget(source: WorkflowInspectionSource, scope: WorkflowScope, target: WorkflowInspectionTarget): boolean {
    return source.kind === target.kind && source.scope_type === scope.type &&
        (scope.type !== 'group' || source.scope_id === scope.groupId) &&
        source.workflow_id === (target.kind === 'draft' ? target.definition.id ?? null : target.workflowId) &&
        source.run_id === (target.kind === 'run' ? target.runId : null);
}

export function inspectionSourceKey(source: WorkflowInspectionSource): string {
    return JSON.stringify([source.kind, source.scope_type, source.scope_id, source.workflow_id,
        source.run_id, source.definition_revision, source.snapshot_sha256 ?? null]);
}

function isInspectionNode(value: unknown): value is WorkflowInspectionNode {
    return isRecord(value) && onlyKeys(value, [
        'id', 'kind', 'label', 'parent_id', 'region_id', 'order', 'loop_ids', 'child_region_ids',
        'inputs_count', 'outputs_count', 'has_condition', 'task_id', 'max_items', 'max_iterations',
    ]) && logicalId(value.id) && INSPECTION_NODE_KINDS.some((kind) => kind === value.kind) && boundedText(value.label) &&
        (value.parent_id === null || logicalId(value.parent_id)) && (value.region_id === null || logicalId(value.region_id)) &&
        integer(value.order, FLOW_MAX_NODES * 2) &&
        Array.isArray(value.loop_ids) && value.loop_ids.length <= 3 && value.loop_ids.every(logicalId) &&
        new Set(value.loop_ids).size === value.loop_ids.length &&
        Array.isArray(value.child_region_ids) && value.child_region_ids.length <= 2 && value.child_region_ids.every(logicalId) &&
        new Set(value.child_region_ids).size === value.child_region_ids.length &&
        integer(value.inputs_count, 100) && integer(value.outputs_count, 100) && typeof value.has_condition === 'boolean' &&
        (value.kind === 'task' ? logicalId(value.task_id) : value.task_id === undefined) &&
        (value.kind === 'for_each' ? integer(value.max_items, MAX_LOOP_ITEMS, 1) : value.max_items === undefined) &&
        (value.kind === 'repeat_until' ? integer(value.max_iterations, MAX_REPEAT_ITERATIONS, 1) : value.max_iterations === undefined);
}

function isInspectionEdge(value: unknown): value is WorkflowInspectionEdge {
    return isRecord(value) && onlyKeys(value, ['id', 'source', 'target', 'kind', 'label']) &&
        boundedText(value.id) && value.id.length > 0 && logicalId(value.source) && logicalId(value.target) &&
        INSPECTION_EDGE_KINDS.some((kind) => kind === value.kind) && boundedText(value.label);
}

export function parseWorkflowFlowProjection(
    value: unknown,
    scope: WorkflowScope,
    target: WorkflowInspectionTarget,
): WorkflowFlowProjection {
    const invalid = () => new Error('The Flow projection returned unsupported or mismatched definition data.');
    if (!isRecord(value) || !onlyKeys(value, [
        'projection_version', 'definition_version', 'source', 'name', 'root_region_id', 'nodes', 'edges', 'limits',
    ]) || value.projection_version !== 1 || value.definition_version !== 3 ||
        !isSource(value.source) || !sourceMatchesTarget(value.source, scope, target) ||
        !boundedText(value.name) || !logicalId(value.root_region_id) ||
        !Array.isArray(value.nodes) || value.nodes.length < 1 || value.nodes.length > FLOW_MAX_NODES ||
        !value.nodes.every(isInspectionNode) ||
        !Array.isArray(value.edges) || value.edges.length > FLOW_MAX_NODES * 8 || !value.edges.every(isInspectionEdge) ||
        !isRecord(value.limits) || !onlyKeys(value.limits, ['max_executions', 'deadline_seconds']) ||
        !integer(value.limits.max_executions, DEFAULT_FLOW_LIMITS.max_executions, 1) ||
        !integer(value.limits.deadline_seconds, DEFAULT_FLOW_LIMITS.deadline_seconds, 1)) {
        throw invalid();
    }
    const nodes = new Map(value.nodes.map((node) => [node.id, node]));
    const root = nodes.get(value.root_region_id);
    if (nodes.size !== value.nodes.length || new Set(value.edges.map((edge) => edge.id)).size !== value.edges.length ||
        root?.kind !== 'region' || root.parent_id !== null ||
        value.edges.some((edge) => !nodes.has(edge.source) || !nodes.has(edge.target))) throw invalid();

    for (const node of value.nodes) {
        if (node.id !== root.id && node.parent_id === null ||
            node.region_id !== null && nodes.get(node.region_id)?.kind !== 'region' ||
            node.child_region_ids.some((id) => nodes.get(id)?.kind !== 'region' || nodes.get(id)?.parent_id !== node.id)) throw invalid();
        const ancestors: WorkflowInspectionNode[] = [];
        let parent = node.parent_id;
        while (parent !== null) {
            const ancestor = nodes.get(parent);
            if (!ancestor || ancestor.id === node.id || ancestors.some((item) => item.id === parent) || ancestors.length >= 8) throw invalid();
            ancestors.push(ancestor);
            parent = ancestor.parent_id;
        }
        if (node.id !== root.id && ancestors.at(-1)?.id !== root.id) throw invalid();
        const loops = ancestors.filter((ancestor) => ['for_each', 'repeat_until'].includes(ancestor.kind)).reverse().map((item) => item.id);
        if (JSON.stringify(loops) !== JSON.stringify(node.loop_ids)) throw invalid();
    }
    return {
        projection_version: 1, definition_version: 3, source: value.source, name: value.name,
        root_region_id: value.root_region_id, nodes: value.nodes, edges: value.edges,
        limits: { max_executions: value.limits.max_executions, deadline_seconds: value.limits.deadline_seconds },
    };
}

function isInspectionJson(value: unknown, depth = 0): value is InspectionJson {
    if (depth > 64) return false;
    if (value === null || typeof value === 'boolean' || typeof value === 'string') return true;
    if (typeof value === 'number') return Number.isFinite(value);
    if (Array.isArray(value)) return value.every((item) => isInspectionJson(item, depth + 1));
    return isRecord(value) && Object.values(value).every((item) => isInspectionJson(item, depth + 1));
}

export function parseWorkflowInspectionDetails(
    value: unknown,
    source: WorkflowInspectionSource,
    nodeId: string,
    section: WorkflowInspectionSection,
): WorkflowInspectionDetails {
    if (!isRecord(value) || !onlyKeys(value, [
        'projection_version', 'source', 'node_id', 'section', 'items', 'total_count', 'next_cursor',
    ]) || value.projection_version !== 1 || !isSource(value.source) ||
        inspectionSourceKey(value.source) !== inspectionSourceKey(source) || value.node_id !== nodeId || value.section !== section ||
        !integer(value.total_count, Number.MAX_SAFE_INTEGER) ||
        !(value.next_cursor === null || boundedText(value.next_cursor, 4096) && value.next_cursor.length > 0) ||
        !Array.isArray(value.items) || value.items.length > 50 || value.items.length > value.total_count ||
        new TextEncoder().encode(JSON.stringify(value.items)).byteLength > 256 * 1024) {
        throw new Error('The selected Flow details returned unsupported or mismatched data.');
    }
    const items: WorkflowInspectionDetails['items'] = [];
    for (const item of value.items) {
        if (!isRecord(item) || !onlyKeys(item, ['label', 'value']) ||
            !boundedText(item.label) || !isInspectionJson(item.value)) {
            throw new Error('The selected Flow details contained an unsupported field.');
        }
        items.push({ label: item.label, value: item.value });
    }
    return {
        projection_version: 1, source: value.source, node_id: nodeId, section,
        items, total_count: value.total_count, next_cursor: value.next_cursor,
    };
}

async function requestInspection(
    scope: WorkflowScope,
    target: WorkflowInspectionTarget,
    params: Record<string, string>,
    signal?: AbortSignal,
): Promise<unknown> {
    if (target.kind === 'draft') {
        return api.post(workflowUrl(scope, undefined, '/flow-preview'), {
            definition: target.definition, ...params,
            ...(params.limit !== undefined ? { limit: Number(params.limit) } : {}),
        }, signal);
    }
    const suffix = target.kind === 'run' ? `/runs/${encodeURIComponent(target.runId)}/flow` : '/flow';
    return api.get(workflowUrl(scope, target.workflowId, suffix, new URLSearchParams(params)), signal);
}

export async function fetchWorkflowFlowProjection(
    scope: WorkflowScope,
    target: WorkflowInspectionTarget,
    signal?: AbortSignal,
): Promise<WorkflowFlowProjection> {
    return parseWorkflowFlowProjection(await requestInspection(scope, target, {}, signal), scope, target);
}

export async function fetchWorkflowInspectionDetails(
    scope: WorkflowScope,
    target: WorkflowInspectionTarget,
    source: WorkflowInspectionSource,
    nodeId: string,
    section: WorkflowInspectionSection,
    cursor: string | null,
    signal?: AbortSignal,
): Promise<WorkflowInspectionDetails> {
    const params: Record<string, string> = { node_id: nodeId, section, revision: source.definition_revision, limit: '50' };
    if (cursor) params.cursor = cursor;
    return parseWorkflowInspectionDetails(await requestInspection(scope, target, params, signal), source, nodeId, section);
}

export function inspectionNodePath(
    node: WorkflowInspectionNode,
    selectedPath: WorkflowIterationFrame[],
): WorkflowIterationFrame[] | null {
    if (node.loop_ids.some((loopId, index) => selectedPath[index]?.loop_id !== loopId)) return null;
    return selectedPath.slice(0, node.loop_ids.length);
}

export function inspectionNodeHasExecution(node: WorkflowInspectionNode, rootRegionId: string): boolean {
    return node.kind !== 'region' || node.id === rootRegionId;
}

export function inspectionNodeMatchesPath(
    node: WorkflowInspectionNode,
    selectedPath: WorkflowIterationFrame[],
    executionPath?: WorkflowIterationFrame[],
): boolean {
    const path = inspectionNodePath(node, selectedPath);
    return path !== null && sameEditorValue(path, executionPath ?? []);
}

export function workflowInspectionBindings(
    node: WorkflowInspectionNode,
    details: WorkflowInspectionDetails | null,
): { sourceId: string; label: string }[] {
    if (!details || details.node_id !== node.id) return [];
    return details.items.flatMap(({ value }) => {
        if (['inputs', 'outputs'].includes(details.section) && isFlowBinding(value)) {
            return [{
                sourceId: value.source.kind === 'node_output' ? value.source.node_id : value.source.loop_id,
                label: `${value.name}: ${value.expected_kind}`,
            }];
        }
        if (node.kind === 'join' && details.section === 'outputs' && isJoinExport(value)) {
            return [
                { sourceId: value.then.node_id, label: `${value.name} (Then): ${value.expected_kind}` },
                { sourceId: value.else.node_id, label: `${value.name} (Else): ${value.expected_kind}` },
            ];
        }
        if (node.kind === 'repeat_until' && details.section === 'state' && isRepeatState(value)) {
            const body = node.child_region_ids[0];
            return [
                { sourceId: value.initial.kind === 'node_output' ? value.initial.node_id : value.initial.loop_id,
                    label: `${value.name} initial: ${value.output_contract.kind}` },
                ...(body ? [{ sourceId: body, label: `${value.name} next: body export ${value.next}` }] : []),
            ];
        }
        if (node.kind === 'collect' && details.section === 'configuration' && isRecord(value) &&
            onlyKeys(value, ['loop_id', 'output']) && logicalId(value.loop_id) && typeof value.output === 'string') {
            return [{ sourceId: value.loop_id, label: `Every frozen item: ${value.output}` }];
        }
        return [];
    });
}
