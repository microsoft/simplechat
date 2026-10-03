// workflowChangeTracking.ts
// Stable-ID change tracking for the workflow editor: diff, attribution, and revert candidates.
//
// Follows the semantics of Score's assisted editing. Every change is keyed by a stable ID
// (a workflow field, task, flow node, region, or reference), never by an array position, so a
// reorder reads as one order change. Attribution is derived from the history entries that made
// each change, and reverts are built as ordinary candidates that the authoring session records
// as new, undoable history entries. Nothing in this module mutates its inputs.

import { WORKFLOW_ALERT_FIELDS } from './workflowAlerts';
import type { WorkflowHistoryOrigin } from './workflowAuthoringHistory';
import type { WorkflowDefinition } from './workflowEditor';
import { isFlowPredicate, predicateSummary } from './workflowFlow';
import { isWorkflowRunAsFingerprintField } from './workflowRunAsFingerprint';
import { workflowScheduleLabel } from './workflowSettings';
import { isRecord, sameEditorValue } from './workspaceAuthoring';

// ---------------------------------------------------------------------------------------------
// Authors and stamps
// ---------------------------------------------------------------------------------------------

export type WorkflowChangeAuthor = 'user' | 'ai';

/** Who last changed a key. Restores keep the author of the version they bring back. */
export interface WorkflowChangeStamp {
    readonly author: WorkflowChangeAuthor;
    readonly origin: WorkflowHistoryOrigin;
    readonly turnId?: string;
}

/** Change key to its last author. Instances are never mutated once published. */
export type WorkflowAttribution = ReadonlyMap<string, WorkflowChangeStamp>;

export const EMPTY_WORKFLOW_ATTRIBUTION: WorkflowAttribution = new Map<string, WorkflowChangeStamp>();

const USER_STAMP: WorkflowChangeStamp = Object.freeze({ author: 'user', origin: 'user' });
const RESTORE_STAMP: WorkflowChangeStamp = Object.freeze({ author: 'user', origin: 'restore' });

/** The stamp a new history entry gives the keys it changes. Only assist entries are AI-authored. */
export function workflowChangeStamp(origin: WorkflowHistoryOrigin = 'user', turnId?: string): WorkflowChangeStamp {
    if (!turnId && origin === 'user') return USER_STAMP;
    if (!turnId && origin === 'restore') return RESTORE_STAMP;
    const author: WorkflowChangeAuthor = origin === 'ai' ? 'ai' : 'user';
    return Object.freeze(turnId ? { author, origin, turnId } : { author, origin });
}

/** Stamps for a restore: each key keeps its author in the restored version, or becomes the user's. */
export function workflowRestoreStamper(source: WorkflowAttribution): (key: string) => WorkflowChangeStamp {
    return (key) => source.get(key) ?? RESTORE_STAMP;
}

// ---------------------------------------------------------------------------------------------
// Change keys
// ---------------------------------------------------------------------------------------------

export const WORKFLOW_TASK_ORDER_KEY = 'tasks:order';
export const WORKFLOW_REFERENCE_ORDER_KEY = 'references:order';

type ItemScope = 'task' | 'node' | 'reference';
type KeyScope = ItemScope | 'region';

const KEY_SCOPES = new Set<string>(['task', 'node', 'reference', 'region']);

// IDs are escaped so a colon inside an ID can never be read as a key separator.
function encodeSegment(id: string): string {
    return id.replace(/%/g, '%25').replace(/:/g, '%3A');
}

function decodeSegment(segment: string): string {
    return segment.replace(/%(25|3A)/g, (_match, code: string) => code === '25' ? '%' : ':');
}

function scopedKey(scope: KeyScope, id: string, field?: string): string {
    const key = `${scope}:${encodeSegment(id)}`;
    return field ? `${key}:${field}` : key;
}

export function workflowTaskKey(taskId: string, field?: string): string {
    return scopedKey('task', taskId, field);
}

export function workflowNodeKey(nodeId: string, field?: string): string {
    return scopedKey('node', nodeId, field);
}

export function workflowReferenceKey(referenceId: string, field?: string): string {
    return scopedKey('reference', referenceId, field);
}

export function workflowRegionKey(regionId: string, field: 'order' | 'outputs'): string {
    return scopedKey('region', regionId, field);
}

export type WorkflowChangeKeyInfo =
    | { scope: 'workflow'; field: string }
    | { scope: 'order'; list: 'tasks' | 'references' }
    | { scope: KeyScope; id: string; field?: string };

export function parseWorkflowChangeKey(key: string): WorkflowChangeKeyInfo {
    if (key === WORKFLOW_TASK_ORDER_KEY) return { scope: 'order', list: 'tasks' };
    if (key === WORKFLOW_REFERENCE_ORDER_KEY) return { scope: 'order', list: 'references' };
    const parts = key.split(':');
    if (parts.length >= 2 && KEY_SCOPES.has(parts[0])) {
        const field = parts.slice(2).join(':');
        return { scope: parts[0] as KeyScope, id: decodeSegment(parts[1]), ...(field ? { field } : {}) };
    }
    return { scope: 'workflow', field: key };
}

/** The item key (`task:<id>`, `node:<id>`, `reference:<id>`) a key belongs to, or null. */
export function workflowChangeItemKey(key: string): string | null {
    const parts = key.split(':');
    return parts.length >= 2 && (parts[0] === 'task' || parts[0] === 'node' || parts[0] === 'reference')
        ? `${parts[0]}:${parts[1]}` : null;
}

function isOrderKey(key: string): boolean {
    return key === WORKFLOW_TASK_ORDER_KEY || key === WORKFLOW_REFERENCE_ORDER_KEY ||
        key.startsWith('region:') && key.endsWith(':order');
}

// ---------------------------------------------------------------------------------------------
// Workflow-level keys
// ---------------------------------------------------------------------------------------------

interface WorkflowKeySpec {
    readonly key: string;
    readonly label: string;
    readonly fields: readonly string[];
    readonly revertable: boolean;
}

function keySpec(key: string, label: string, fields: readonly string[] = [key], revertable = true): WorkflowKeySpec {
    return { key, label, fields, revertable };
}

const WORKFLOW_KEY_SPECS: readonly WorkflowKeySpec[] = [
    keySpec('name', 'Workflow name'),
    keySpec('description', 'Description'),
    keySpec('runner_type', 'Runner type'),
    keySpec('selected_agent', 'Agent'),
    keySpec('model', 'Model', ['model_endpoint_id', 'model_id']),
    keySpec('m365_run_as_user_id', 'Microsoft 365 Run as'),
    keySpec('schedule', 'Trigger and schedule', ['trigger_type', 'schedule']),
    keySpec('error_handling', 'Error handling'),
    keySpec('is_enabled', 'Workflow enabled'),
    keySpec('chat_capabilities_enabled', 'Chat capabilities'),
    keySpec('durable_execution', 'Durable execution'),
    keySpec('file_sync', 'File Sync'),
    keySpec('limits', 'Flow limits'),
    keySpec('alerts', 'Alerts', WORKFLOW_ALERT_FIELDS),
    keySpec('definition_version', 'Workflow format', ['definition_version'], false),
];

const WORKFLOW_KEY_SPEC_MAP = new Map(WORKFLOW_KEY_SPECS.map((item) => [item.key, item]));

// Alerts and the format sort after the tasks and flow in the change list.
const TRAILING_WORKFLOW_KEYS = new Set(['alerts', 'definition_version']);

/** The definition fields a key covers; the Run as consequence checks them against the fingerprint. */
export function workflowChangeFields(key: string): readonly string[] {
    const info = parseWorkflowChangeKey(key);
    if (info.scope === 'workflow') return WORKFLOW_KEY_SPEC_MAP.get(info.field)?.fields ?? [info.field];
    if (info.scope === 'order') return info.list === 'tasks' ? ['tasks'] : ['reference_inputs'];
    if (info.scope === 'reference') return ['reference_inputs'];
    if (info.scope === 'task') return info.field === 'run_when' || info.field === 'placement' ? ['flow'] : ['tasks'];
    return ['flow'];
}

// ---------------------------------------------------------------------------------------------
// Indexes. Cached by object identity, so unchanged tasks, flows, and references are never re-read.
// ---------------------------------------------------------------------------------------------

/** A key whose field or item does not exist. Distinct from undefined, like Object.hasOwn. */
export const WORKFLOW_ABSENT: unique symbol = Symbol('absent');

type Row = Record<string, unknown> & { id: string };
type RegionRow = Record<string, unknown> & { id: string; nodes: unknown[] };
type NodeRow = Row & { kind: string };
type Branch = 'then' | 'else' | 'body';

interface ListEntry {
    readonly item: Row;
    readonly index: number;
}

interface ListIndex {
    readonly byId: ReadonlyMap<string, ListEntry>;
    readonly ids: readonly string[];
}

interface FlowNodeEntry {
    readonly node: NodeRow;
    readonly id: string;
    readonly kind: string;
    readonly regionId: string;
    readonly taskId?: string;
}

interface FlowRegionEntry {
    readonly region: RegionRow;
    readonly id: string;
    readonly nodeIds: readonly string[];
    readonly ownerNodeId?: string;
    readonly branch?: Branch;
}

interface FlowIndex {
    readonly rootId: string;
    readonly nodes: ReadonlyMap<string, FlowNodeEntry>;
    readonly regions: ReadonlyMap<string, FlowRegionEntry>;
    readonly taskNodes: ReadonlyMap<string, string>;
    /** Node IDs in pre-order: each block, then the blocks inside it. */
    readonly order: readonly string[];
}

interface DefinitionIndex {
    readonly structured: boolean;
    readonly tasks: ListIndex;
    readonly references: ListIndex;
    readonly flow: FlowIndex | null;
}

const FLOW_WALK_DEPTH = 32;
const REGION_BRANCHES = new Map<string, readonly Branch[]>([
    ['if', ['then', 'else']], ['for_each', ['body']], ['repeat_until', ['body']],
]);
const EMPTY_LIST: ListIndex = { byId: new Map(), ids: [] };
const listIndexes = new WeakMap<readonly unknown[], ListIndex>();
const flowIndexes = new WeakMap<RegionRow, FlowIndex>();
const definitionIndexes = new WeakMap<WorkflowDefinition, DefinitionIndex>();

function isRow(value: unknown): value is Row {
    return isRecord(value) && typeof value.id === 'string';
}

function isRegionRow(value: unknown): value is RegionRow {
    return isRow(value) && Array.isArray(value.nodes);
}

function isNodeRow(value: unknown): value is NodeRow {
    return isRow(value) && typeof value.kind === 'string';
}

function indexList(value: unknown): ListIndex {
    if (!Array.isArray(value)) return EMPTY_LIST;
    const cached = listIndexes.get(value);
    if (cached) return cached;
    const byId = new Map<string, ListEntry>();
    const ids: string[] = [];
    value.forEach((item, index) => {
        if (!isRow(item) || byId.has(item.id)) return;
        byId.set(item.id, { item, index });
        ids.push(item.id);
    });
    const result = { byId, ids };
    listIndexes.set(value, result);
    return result;
}

function indexFlow(flow: RegionRow): FlowIndex {
    const cached = flowIndexes.get(flow);
    if (cached) return cached;
    const nodes = new Map<string, FlowNodeEntry>();
    const regions = new Map<string, FlowRegionEntry>();
    const taskNodes = new Map<string, string>();
    const order: string[] = [];
    // Tolerant walk: malformed or duplicate entries are skipped (the first ID wins).
    const walk = (region: RegionRow, depth: number, ownerNodeId?: string, branch?: Branch) => {
        if (regions.has(region.id)) return;
        const nodeIds: string[] = [];
        regions.set(region.id, { region, id: region.id, nodeIds, ...(ownerNodeId ? { ownerNodeId, branch } : {}) });
        for (const node of region.nodes) {
            if (!isNodeRow(node) || nodes.has(node.id)) continue;
            const taskId = node.kind === 'task' && typeof node.task_id === 'string' ? node.task_id : undefined;
            nodes.set(node.id, { node, id: node.id, kind: node.kind, regionId: region.id, ...(taskId !== undefined ? { taskId } : {}) });
            nodeIds.push(node.id);
            order.push(node.id);
            if (taskId !== undefined && !taskNodes.has(taskId)) taskNodes.set(taskId, node.id);
            if (depth >= FLOW_WALK_DEPTH) continue;
            for (const key of REGION_BRANCHES.get(node.kind) ?? []) {
                const child = node[key];
                if (isRegionRow(child)) walk(child, depth + 1, node.id, key);
            }
        }
    };
    walk(flow, 0);
    const result = { rootId: flow.id, nodes, regions, taskNodes, order };
    flowIndexes.set(flow, result);
    return result;
}

function indexDefinition(definition: WorkflowDefinition): DefinitionIndex {
    let result = definitionIndexes.get(definition);
    if (!result) {
        const flow = isRegionRow(definition.flow) ? indexFlow(definition.flow) : null;
        result = {
            structured: definition.definition_version === 3 && flow !== null,
            tasks: indexList(definition.tasks),
            references: indexList(definition.reference_inputs),
            flow,
        };
        definitionIndexes.set(definition, result);
    }
    return result;
}

function taskNodeEntry(index: DefinitionIndex, taskId: string): FlowNodeEntry | undefined {
    const nodeId = index.flow?.taskNodes.get(taskId);
    return nodeId === undefined ? undefined : index.flow?.nodes.get(nodeId);
}

function controlNodeEntry(index: DefinitionIndex, nodeId: string): FlowNodeEntry | undefined {
    const entry = index.flow?.nodes.get(nodeId);
    return entry && entry.kind !== 'task' ? entry : undefined;
}

function itemExists(index: DefinitionIndex, scope: ItemScope, id: string): boolean {
    if (scope === 'task') return index.tasks.byId.has(id);
    if (scope === 'reference') return index.references.byId.has(id);
    return controlNodeEntry(index, id) !== undefined;
}

function ownedRegionIds(entry: FlowNodeEntry): string[] {
    return (REGION_BRANCHES.get(entry.kind) ?? []).flatMap((branch) => {
        const child = entry.node[branch];
        return isRegionRow(child) ? [child.id] : [];
    });
}

/** Owner block IDs from the innermost outward. */
function ancestorNodeIds(flow: FlowIndex | null, nodeId: string): string[] {
    const result: string[] = [];
    let regionId = flow?.nodes.get(nodeId)?.regionId;
    while (flow && regionId !== undefined && result.length <= FLOW_WALK_DEPTH) {
        const owner = flow.regions.get(regionId)?.ownerNodeId;
        if (owner === undefined) break;
        result.push(owner);
        regionId = flow.nodes.get(owner)?.regionId;
    }
    return result;
}

/** Every node ID inside a block, in pre-order, excluding the block itself. */
function subtreeNodeIds(flow: FlowIndex, nodeId: string): string[] {
    const entry = flow.nodes.get(nodeId);
    if (!entry) return [];
    const result: string[] = [];
    const visit = (regionId: string, depth: number) => {
        for (const id of flow.regions.get(regionId)?.nodeIds ?? []) {
            result.push(id);
            const child = flow.nodes.get(id);
            if (child && depth < FLOW_WALK_DEPTH) ownedRegionIds(child).forEach((region) => visit(region, depth + 1));
        }
    };
    ownedRegionIds(entry).forEach((region) => visit(region, 0));
    return result;
}

// ---------------------------------------------------------------------------------------------
// Key values
// ---------------------------------------------------------------------------------------------

function ownValue(record: unknown, field: string): unknown {
    return isRecord(record) && Object.hasOwn(record, field) ? record[field] : WORKFLOW_ABSENT;
}

function sameOwn(left: Record<string, unknown>, right: Record<string, unknown>, field: string): boolean {
    const has = Object.hasOwn(left, field);
    return has === Object.hasOwn(right, field) && (!has || sameEditorValue(left[field], right[field]));
}

function groupValue(definition: WorkflowDefinition, fields: readonly string[]): Record<string, unknown> {
    const result: Record<string, unknown> = {};
    for (const field of fields) if (Object.hasOwn(definition, field)) result[field] = definition[field];
    return result;
}

function referenceDocument(reference: Row): Record<string, unknown> {
    const result: Record<string, unknown> = {};
    for (const [field, value] of Object.entries(reference)) if (field !== 'id' && field !== 'name') result[field] = value;
    return result;
}

/** The value a change key reads from a definition, or WORKFLOW_ABSENT. */
export function workflowKeyValue(definition: WorkflowDefinition, key: string): unknown {
    const info = parseWorkflowChangeKey(key);
    const index = indexDefinition(definition);
    if (info.scope === 'workflow') {
        const item = WORKFLOW_KEY_SPEC_MAP.get(info.field);
        if (!item) return ownValue(definition, info.field);
        return item.fields.length === 1 ? ownValue(definition, item.fields[0]) : groupValue(definition, item.fields);
    }
    if (info.scope === 'order') return info.list === 'tasks' ? index.tasks.ids : index.references.ids;
    if (info.scope === 'region') {
        const region = index.flow?.regions.get(info.id);
        if (!region) return WORKFLOW_ABSENT;
        return info.field === 'order' ? region.nodeIds : ownValue(region.region, 'outputs');
    }
    if (info.scope === 'reference') {
        const entry = index.references.byId.get(info.id);
        if (!entry || !info.field) return entry?.item ?? WORKFLOW_ABSENT;
        return info.field === 'document' ? referenceDocument(entry.item) : ownValue(entry.item, info.field);
    }
    if (info.scope === 'node') {
        const entry = controlNodeEntry(index, info.id);
        if (!entry || !info.field) return entry?.node ?? WORKFLOW_ABSENT;
        return info.field === 'placement' ? entry.regionId : ownValue(entry.node, info.field);
    }
    const entry = index.tasks.byId.get(info.id);
    if (!entry || !info.field) return entry?.item ?? WORKFLOW_ABSENT;
    if (info.field !== 'run_when' && info.field !== 'placement') return ownValue(entry.item, info.field);
    const node = taskNodeEntry(index, info.id);
    if (!node) return WORKFLOW_ABSENT;
    return info.field === 'placement' ? node.regionId : ownValue(node.node, 'run_when');
}

function sameIds(left: readonly string[], right: readonly string[]): boolean {
    return left === right || left.length === right.length && left.every((id, index) => id === right[index]);
}

/** Whether the IDs both lists contain keep the same relative order. Additions and removals are not reorders. */
function sameRelativeOrder(left: readonly string[], right: readonly string[]): boolean {
    if (sameIds(left, right)) return true;
    const inLeft = new Set(left);
    const inRight = new Set(right);
    return sameIds(left.filter((id) => inRight.has(id)), right.filter((id) => inLeft.has(id)));
}

/** Value equality for a key; order keys compare the relative order of the items both sides share. */
export function sameWorkflowKeyValue(key: string, left: unknown, right: unknown): boolean {
    if (isOrderKey(key) && Array.isArray(left) && Array.isArray(right)) return sameRelativeOrder(left, right);
    return sameEditorValue(left, right);
}

// ---------------------------------------------------------------------------------------------
// Changed keys between two definitions
// ---------------------------------------------------------------------------------------------

interface KeyDelta {
    /** Keys whose value differs; order keys only when the shared items' relative order changed. */
    readonly changed: ReadonlySet<string>;
    /** Order keys whose ID list changed at all, including additions and removals. */
    readonly orderAffected: ReadonlySet<string>;
}

const EMPTY_DELTA: KeyDelta = { changed: new Set(), orderAffected: new Set() };
const deltaCache = new WeakMap<WorkflowDefinition, WeakMap<WorkflowDefinition, KeyDelta>>();
const TASK_SKIPPED_FIELDS = new Set(['id', 'order']);
const NODE_SKIPPED_FIELDS = new Set(['id', 'then', 'else', 'body']);
const REFERENCE_FIELDS = ['name', 'document'] as const;
const EMPTY_NODES: ReadonlyMap<string, FlowNodeEntry> = new Map();

function fieldNames(left: Record<string, unknown> | null, right: Record<string, unknown> | null, skipped: ReadonlySet<string>): string[] {
    const names = new Set<string>();
    for (const record of [left, right]) {
        if (record) for (const name of Object.keys(record)) if (!skipped.has(name)) names.add(name);
    }
    return [...names];
}

function diffOrder(key: string, left: readonly string[], right: readonly string[], changed: Set<string>, orderAffected: Set<string>) {
    if (sameIds(left, right)) return;
    orderAffected.add(key);
    if (!sameRelativeOrder(left, right)) changed.add(key);
}

function diffTasks(a: DefinitionIndex, b: DefinitionIndex, changed: Set<string>, orderAffected: Set<string>) {
    const tasksChanged = a.tasks !== b.tasks;
    const flowChanged = a.flow !== b.flow;
    if (tasksChanged) {
        for (const id of a.tasks.ids) if (!b.tasks.byId.has(id)) changed.add(workflowTaskKey(id));
    }
    for (const [id, entry] of b.tasks.byId) {
        const previous = tasksChanged ? a.tasks.byId.get(id) : entry;
        if (!previous) {
            changed.add(workflowTaskKey(id));
            for (const field of fieldNames(entry.item, null, TASK_SKIPPED_FIELDS)) changed.add(workflowTaskKey(id, field));
            const node = taskNodeEntry(b, id);
            if (node) changed.add(workflowTaskKey(id, 'placement'));
            if (node && Object.hasOwn(node.node, 'run_when')) changed.add(workflowTaskKey(id, 'run_when'));
            continue;
        }
        if (previous.item !== entry.item) {
            for (const field of fieldNames(previous.item, entry.item, TASK_SKIPPED_FIELDS)) {
                if (!sameOwn(previous.item, entry.item, field)) changed.add(workflowTaskKey(id, field));
            }
        }
        if (!flowChanged) continue;
        const before = taskNodeEntry(a, id);
        const after = taskNodeEntry(b, id);
        if (before?.regionId !== after?.regionId) changed.add(workflowTaskKey(id, 'placement'));
        if (before?.node !== after?.node && !sameEditorValue(ownValue(before?.node, 'run_when'), ownValue(after?.node, 'run_when'))) {
            changed.add(workflowTaskKey(id, 'run_when'));
        }
    }
    // Structured flows own execution order, so the task array order only matters for classic tasks.
    if (tasksChanged && !b.structured) diffOrder(WORKFLOW_TASK_ORDER_KEY, a.tasks.ids, b.tasks.ids, changed, orderAffected);
}

function diffFlow(a: FlowIndex | null, b: FlowIndex | null, changed: Set<string>, orderAffected: Set<string>) {
    const before = a?.nodes ?? EMPTY_NODES;
    const after = b?.nodes ?? EMPTY_NODES;
    for (const [id, entry] of before) {
        const next = after.get(id);
        if (entry.kind !== 'task' && (!next || next.kind === 'task')) changed.add(workflowNodeKey(id));
    }
    for (const [id, entry] of after) {
        if (entry.kind === 'task') continue;
        const previous = before.get(id);
        if (!previous || previous.kind === 'task') {
            changed.add(workflowNodeKey(id));
            changed.add(workflowNodeKey(id, 'placement'));
            for (const field of fieldNames(entry.node, null, NODE_SKIPPED_FIELDS)) changed.add(workflowNodeKey(id, field));
            continue;
        }
        if (previous.regionId !== entry.regionId) changed.add(workflowNodeKey(id, 'placement'));
        if (previous.node === entry.node) continue;
        for (const field of fieldNames(previous.node, entry.node, NODE_SKIPPED_FIELDS)) {
            if (!sameOwn(previous.node, entry.node, field)) changed.add(workflowNodeKey(id, field));
        }
    }
    if (!a || !b) return;
    for (const [id, region] of a.regions) {
        const next = b.regions.get(id);
        if (!next || next.region === region.region) continue;
        diffOrder(workflowRegionKey(id, 'order'), region.nodeIds, next.nodeIds, changed, orderAffected);
        if (!sameOwn(region.region, next.region, 'outputs')) changed.add(workflowRegionKey(id, 'outputs'));
    }
}

function diffReferences(a: DefinitionIndex, b: DefinitionIndex, changed: Set<string>, orderAffected: Set<string>) {
    for (const id of a.references.ids) if (!b.references.byId.has(id)) changed.add(workflowReferenceKey(id));
    for (const [id, entry] of b.references.byId) {
        const previous = a.references.byId.get(id);
        if (!previous) {
            changed.add(workflowReferenceKey(id));
            for (const field of REFERENCE_FIELDS) changed.add(workflowReferenceKey(id, field));
            continue;
        }
        if (previous.item === entry.item) continue;
        if (!sameOwn(previous.item, entry.item, 'name')) changed.add(workflowReferenceKey(id, 'name'));
        if (!sameEditorValue(referenceDocument(previous.item), referenceDocument(entry.item))) {
            changed.add(workflowReferenceKey(id, 'document'));
        }
    }
    diffOrder(WORKFLOW_REFERENCE_ORDER_KEY, a.references.ids, b.references.ids, changed, orderAffected);
}

function keyDelta(from: WorkflowDefinition, to: WorkflowDefinition): KeyDelta {
    if (from === to) return EMPTY_DELTA;
    let byTarget = deltaCache.get(from);
    const cached = byTarget?.get(to);
    if (cached) return cached;
    const changed = new Set<string>();
    const orderAffected = new Set<string>();
    for (const item of WORKFLOW_KEY_SPECS) {
        if (item.fields.some((field) => !sameOwn(from, to, field))) changed.add(item.key);
    }
    const a = indexDefinition(from);
    const b = indexDefinition(to);
    if (a.tasks !== b.tasks || a.flow !== b.flow) diffTasks(a, b, changed, orderAffected);
    if (a.flow !== b.flow) diffFlow(a.flow, b.flow, changed, orderAffected);
    if (a.references !== b.references) diffReferences(a, b, changed, orderAffected);
    const result = { changed, orderAffected };
    if (!byTarget) deltaCache.set(from, byTarget = new WeakMap());
    byTarget.set(to, result);
    return result;
}

/** Stable-ID keys whose values differ between two definitions. */
export function workflowChangedKeys(from: WorkflowDefinition, to: WorkflowDefinition): ReadonlySet<string> {
    return keyDelta(from, to).changed;
}

// ---------------------------------------------------------------------------------------------
// Attribution
// ---------------------------------------------------------------------------------------------

/**
 * The attribution after an edit from `from` to `to`. Each key that now differs from the opened
 * baseline takes the edit's stamp; keys back at their baseline value lose their author. Returns
 * `base` itself when nothing changed, so checkpoints share maps.
 */
export function nextWorkflowAttribution(
    base: WorkflowAttribution,
    from: WorkflowDefinition,
    to: WorkflowDefinition,
    baseline: WorkflowDefinition,
    stamp: (key: string) => WorkflowChangeStamp,
): WorkflowAttribution {
    const { changed, orderAffected } = keyDelta(from, to);
    if (!changed.size && !orderAffected.size) return base;
    let next: Map<string, WorkflowChangeStamp> | null = null;
    const current = (): WorkflowAttribution => next ?? base;
    const put = (key: string) => {
        const value = stamp(key);
        if (current().get(key) !== value) (next ??= new Map(base)).set(key, value);
    };
    const drop = (key: string) => {
        if (current().has(key)) (next ??= new Map(base)).delete(key);
    };
    const dropPrefix = (prefix: string) => {
        for (const key of [...current().keys()]) if (key.startsWith(prefix)) drop(key);
    };
    const fromIndex = indexDefinition(from);
    const toIndex = indexDefinition(to);
    const baselineIndex = indexDefinition(baseline);
    const differs = (key: string) => !sameWorkflowKeyValue(key, workflowKeyValue(to, key), workflowKeyValue(baseline, key));
    const regionShared = (id: string) => Boolean(toIndex.flow?.regions.has(id) && baselineIndex.flow?.regions.has(id));

    for (const key of changed) {
        const info = parseWorkflowChangeKey(key);
        if (info.scope === 'task' || info.scope === 'node' || info.scope === 'reference') {
            const present = itemExists(toIndex, info.scope, info.id);
            if (info.field) {
                if (present && differs(key)) put(key);
                else drop(key);
                continue;
            }
            const inBaseline = itemExists(baselineIndex, info.scope, info.id);
            if (!present) {
                dropPrefix(`${key}:`);
                const entry = info.scope === 'node' ? controlNodeEntry(fromIndex, info.id) : undefined;
                for (const regionId of entry ? ownedRegionIds(entry) : []) {
                    drop(workflowRegionKey(regionId, 'order'));
                    drop(workflowRegionKey(regionId, 'outputs'));
                }
            }
            // A removed baseline item is a change; an added item is one; a restored one is not.
            if (present !== inBaseline) put(key);
            else drop(key);
            continue;
        }
        if (info.scope === 'region' && !regionShared(info.id)) drop(key);
        else if (differs(key)) put(key);
        else drop(key);
    }
    for (const key of orderAffected) {
        if (changed.has(key)) continue;
        const info = parseWorkflowChangeKey(key);
        if (info.scope === 'region' && !regionShared(info.id) || !differs(key)) drop(key);
        else if (!current().has(key)) put(key);
    }
    return next ?? base;
}

// ---------------------------------------------------------------------------------------------
// Labels and plain-text summaries. Summaries render only as text nodes.
// ---------------------------------------------------------------------------------------------

const SUMMARY_LIMIT = 10_000;
const NOT_SET = '(not set)';

// Maps, not object literals: field names come from stored data and may shadow prototype keys.
const TASK_FIELD_LABELS = new Map<string, string>([
    ['name', 'Task name'], ['instructions', 'Instructions'], ['runner', 'Task runner'],
    ['document_action', 'Document action'], ['reference_ids', 'Task references'], ['inputs', 'Inputs'],
    ['input_processing', 'Input processing'], ['output_contract', 'Output contract'], ['approval', 'Approval'],
    ['publication', 'Publication'], ['run_when', 'Run when'], ['placement', 'Position in flow'],
]);
const NODE_FIELD_LABELS = new Map<string, string>([
    ['placement', 'Position in flow'], ['kind', 'Block type'], ['condition', 'Condition'], ['inputs', 'Inputs'],
    ['iterable', 'Items to loop over'], ['item_key', 'Item key'], ['max_items', 'Maximum items'],
    ['max_iterations', 'Maximum rounds'], ['state', 'Repeat state'], ['until', 'Stop condition'],
    ['exports', 'Exports'], ['join', 'Join exports'], ['target', 'Route target'], ['source', 'Collect source'],
    ['output_contract', 'Output contract'],
]);
const NODE_KIND_LABELS = new Map<string, string>([
    ['task', 'Task'], ['if', 'If / else'], ['route', 'Forward route'], ['for_each', 'For each'],
    ['repeat_until', 'Repeat until'], ['collect', 'Collect'],
]);
const REFERENCE_FIELD_LABELS = new Map<string, string>([['name', 'Reference name'], ['document', 'Document']]);
const BRANCH_LABELS = new Map<string, string>([['then', 'Then'], ['else', 'Else'], ['body', 'Body']]);

function humanize(name: string): string {
    const text = name.replace(/_/g, ' ').trim();
    return text ? `${text[0].toUpperCase()}${text.slice(1)}` : name;
}

function clip(text: string): string {
    if (text.length <= SUMMARY_LIMIT) return text;
    const cut = text.slice(0, SUMMARY_LIMIT);
    return `${/[\uD800-\uDBFF]$/.test(cut) ? cut.slice(0, -1) : cut}…`;
}

function readable(value: unknown): string {
    try {
        return String(value);
    } catch {
        return '(unreadable)';
    }
}

function compactJson(value: unknown): string {
    try {
        return JSON.stringify(value) ?? readable(value);
    } catch {
        return readable(value);
    }
}

function textOf(value: unknown): string {
    return typeof value === 'string' && value.trim() ? value : '';
}

function plainSummary(value: unknown): string {
    if (value === WORKFLOW_ABSENT || value === null || value === undefined) return NOT_SET;
    if (typeof value === 'string') return value.trim() ? value : '(empty)';
    if (typeof value === 'boolean') return value ? 'On' : 'Off';
    if (typeof value === 'number') return Number.isFinite(value) ? String(value) : NOT_SET;
    if (Array.isArray(value) && !value.length) return 'None';
    return compactJson(value);
}

function listSummary(value: unknown, noun: string): string {
    if (!Array.isArray(value)) return plainSummary(value);
    if (!value.length) return 'None';
    const names = value.map((item) => isRecord(item) ? textOf(item.name) || textOf(item.id) : '').filter(Boolean);
    const count = `${value.length} ${noun}${value.length === 1 ? '' : 's'}`;
    return names.length ? `${count}: ${names.join(', ')}` : count;
}

function predicateText(value: unknown): string {
    return isFlowPredicate(value) ? predicateSummary(value) : plainSummary(value);
}

function agentName(value: unknown): string {
    if (!isRecord(value)) return plainSummary(value);
    return textOf(value.display_name) || textOf(value.name) || textOf(value.id) || NOT_SET;
}

function outputContractSummary(value: unknown): string {
    if (!isRecord(value) || !textOf(value.kind)) return plainSummary(value);
    return `${humanize(value.kind as string)}${isRecord(value.schema) ? ' with schema' : ''}`;
}

function kindLabel(kind: string): string {
    return NODE_KIND_LABELS.get(kind) ?? humanize(kind);
}

function taskLabel(item: Row | undefined): string {
    return textOf(item?.name) || 'Untitled task';
}

function referenceLabel(item: Row | undefined): string {
    return textOf(item?.name) || 'Untitled reference';
}

function nodeLabel(index: DefinitionIndex, entry: FlowNodeEntry): string {
    if (entry.kind === 'task') return taskLabel(entry.taskId === undefined ? undefined : index.tasks.byId.get(entry.taskId)?.item);
    return `${kindLabel(entry.kind)} (${entry.id})`;
}

function regionLabel(index: DefinitionIndex, regionId: string): string {
    const region = index.flow?.regions.get(regionId);
    if (!region) return regionId || NOT_SET;
    if (!region.ownerNodeId) return 'Main';
    const owner = index.flow?.nodes.get(region.ownerNodeId);
    const branch = region.branch ? BRANCH_LABELS.get(region.branch) ?? humanize(region.branch) : '';
    return `${owner ? nodeLabel(index, owner) : region.ownerNodeId} › ${branch}`;
}

function orderSummary(value: unknown, label: (id: string) => string): string {
    if (!Array.isArray(value)) return plainSummary(value);
    return value.map((id) => typeof id === 'string' ? label(id) : compactJson(id)).join(' → ') || 'None';
}

function summarizeWorkflowKey(field: string, value: unknown): string {
    if (value === WORKFLOW_ABSENT) return NOT_SET;
    if (field === 'runner_type') return value === 'agent' ? 'Agent' : value === 'model' ? 'Model' : plainSummary(value);
    if (field === 'selected_agent') return agentName(value);
    if (field === 'model') return (isRecord(value) ? textOf(value.model_id) : '') || '(default model)';
    if (field === 'm365_run_as_user_id') return textOf(value) || NOT_SET;
    if (field === 'definition_version') {
        return value === 3 ? 'Structured flow (version 3)' : `Classic tasks (version ${plainSummary(value)})`;
    }
    if (!isRecord(value)) return plainSummary(value);
    if (field === 'schedule') {
        const label = workflowScheduleLabel(value.trigger_type, value.schedule);
        if (label) return label;
        if (value.trigger_type === undefined || value.trigger_type === 'manual') return 'Manual';
        return `${humanize(readable(value.trigger_type))}: ${compactJson(value.schedule ?? null)}`;
    }
    if (field === 'error_handling') {
        const strategy = value.strategy === 'continue' ? 'Continue on error' : 'Halt on error';
        const retries = typeof value.retry_count === 'number' && value.retry_count > 0 ? value.retry_count : 0;
        return retries ? `${strategy}, ${retries} ${retries === 1 ? 'retry' : 'retries'}` : strategy;
    }
    if (field === 'file_sync') {
        const sources = Array.isArray(value.sources) ? value.sources.length : 0;
        return `${value.enabled ? 'On' : 'Off'}, ${sources} ${sources === 1 ? 'source' : 'sources'}`;
    }
    if (field === 'limits') {
        return Object.entries(value).map(([name, item]) => `${humanize(name)} ${plainSummary(item)}`).join(', ') || NOT_SET;
    }
    if (field === 'alerts') {
        const parts: string[] = [];
        if (textOf(value.alert_mode)) parts.push(`Mode ${humanize(value.alert_mode as string)}`);
        if (Array.isArray(value.alert_rules)) parts.push(listSummary(value.alert_rules, 'rule'));
        if (value.alert_priority !== undefined && value.alert_priority !== null) parts.push(`Priority ${plainSummary(value.alert_priority)}`);
        return parts.join(', ') || NOT_SET;
    }
    return plainSummary(value);
}

function summarizeTaskField(field: string, value: unknown, index: DefinitionIndex): string {
    if (field === 'approval') {
        if (!isRecord(value) || value.required !== true) return 'Not required';
        return textOf(value.message) ? `Required: ${value.message as string}` : 'Required';
    }
    if (value === WORKFLOW_ABSENT) return NOT_SET;
    if (field === 'runner') {
        if (!isRecord(value)) return plainSummary(value);
        if (value.type === 'agent') return `Agent ${agentName(value.selected_agent)}`;
        if (value.type === 'model') return `Model ${textOf(value.model_id) || '(default model)'}`;
        return 'Workflow runner';
    }
    if (field === 'document_action') return isRecord(value) && textOf(value.type) ? humanize(value.type as string) : plainSummary(value);
    if (field === 'reference_ids') {
        return orderSummary(value, (id) => referenceLabel(index.references.byId.get(id)?.item)).replace(/ → /g, ', ');
    }
    if (field === 'inputs') return listSummary(value, 'input');
    if (field === 'output_contract') return outputContractSummary(value);
    if (field === 'run_when') return predicateText(value);
    if (field === 'placement') return typeof value === 'string' ? regionLabel(index, value) : plainSummary(value);
    return plainSummary(value);
}

function summarizeNodeField(field: string, value: unknown, index: DefinitionIndex): string {
    if (value === WORKFLOW_ABSENT) return NOT_SET;
    if (field === 'placement') return typeof value === 'string' ? regionLabel(index, value) : plainSummary(value);
    if (field === 'kind') return typeof value === 'string' ? kindLabel(value) : plainSummary(value);
    if (field === 'condition' || field === 'until') return predicateText(value);
    if (field === 'inputs') return listSummary(value, 'input');
    if (field === 'state') return listSummary(value, 'state value');
    if (field === 'exports') return listSummary(value, 'export');
    if (field === 'output_contract') return outputContractSummary(value);
    if (!isRecord(value)) return plainSummary(value);
    if (field === 'join') return listSummary(value.exports, 'export');
    if (field === 'source') return `${textOf(value.loop_id) || '?'}.${textOf(value.output) || '?'}`;
    if (field === 'iterable' && textOf(value.kind)) {
        return `${humanize(value.kind as string)}${Array.isArray(value.documents) ? ` (${value.documents.length})` : ''}`;
    }
    if (field === 'target') {
        if (typeof value.node_id === 'string') {
            const target = index.flow?.nodes.get(value.node_id);
            return value.node_id ? `Block ${target ? nodeLabel(index, target) : value.node_id}` : NOT_SET;
        }
        if (typeof value.exit_region_id === 'string') return `Exit ${regionLabel(index, value.exit_region_id)}`;
    }
    return plainSummary(value);
}

function summarizeKey(info: WorkflowChangeKeyInfo, value: unknown, index: DefinitionIndex): string {
    if (info.scope === 'workflow') return clip(summarizeWorkflowKey(info.field, value));
    if (info.scope === 'order') {
        return clip(orderSummary(value, (id) => info.list === 'tasks'
            ? taskLabel(index.tasks.byId.get(id)?.item) : referenceLabel(index.references.byId.get(id)?.item)));
    }
    if (info.scope === 'region') {
        if (info.field === 'outputs') return clip(listSummary(value, 'output'));
        return clip(orderSummary(value, (id) => {
            const entry = index.flow?.nodes.get(id);
            return entry ? nodeLabel(index, entry) : id;
        }));
    }
    const field = info.field ?? '';
    if (info.scope === 'task') return clip(summarizeTaskField(field, value, index));
    if (info.scope === 'node') return clip(summarizeNodeField(field, value, index));
    if (field === 'document' && isRecord(value)) {
        const scope = textOf(value.scope_type);
        return clip(`${textOf(value.document_id) || NOT_SET}${scope ? ` (${scope})` : ''}`);
    }
    return clip(plainSummary(value));
}

// ---------------------------------------------------------------------------------------------
// Unsaved changes against the opened baseline
// ---------------------------------------------------------------------------------------------

export type WorkflowChangeKind = 'field' | 'added' | 'removed' | 'order' | 'placement' | 'version';

export interface WorkflowChangeOwner {
    readonly kind: 'workflow' | ItemScope | 'region';
    readonly id?: string;
}

/** Where a removed item was, for its Removed · Restore row. */
export interface WorkflowChangeAnchor {
    /** The flow region it was in; '' for the classic task list and the reference list. */
    readonly regionId: string;
    /** The nearest earlier sibling that still exists in the draft, or null for the start. */
    readonly afterId: string | null;
    readonly regionPresent: boolean;
}

/** Where Jump goes: the element carrying `data-workflow-change-key`, and the flow node to select. */
export interface WorkflowChangeTarget {
    readonly focusKey: string;
    readonly nodeId?: string;
}

export interface WorkflowChange {
    readonly key: string;
    readonly kind: WorkflowChangeKind;
    readonly label: string;
    readonly ownerLabel: string;
    readonly owner: WorkflowChangeOwner;
    /** Items added or removed inside this one; reverting this change reverts them too. */
    readonly descendantKeys?: readonly string[];
    readonly before: string;
    readonly after: string;
    readonly revertable: boolean;
    readonly anchor?: WorkflowChangeAnchor;
    readonly target: WorkflowChangeTarget;
}

export interface WorkflowChangeSet {
    readonly changes: readonly WorkflowChange[];
    readonly byKey: ReadonlyMap<string, WorkflowChange>;
    /** Every added item key, mapped to the outermost added change that contains it. */
    readonly added: ReadonlyMap<string, string>;
    /** Every removed item key, mapped to the outermost removed change that contains it. */
    readonly removed: ReadonlyMap<string, string>;
    /** The draft changed format, so its changes can only be discarded together. */
    readonly converted: boolean;
}

export const EMPTY_WORKFLOW_CHANGE_SET: WorkflowChangeSet = Object.freeze({
    changes: [], byKey: new Map(), added: new Map(), removed: new Map(), converted: false,
});

const ITEM_NOUNS = new Map<string, string>([['task', 'task'], ['node', 'block'], ['reference', 'reference']]);
const TASK_FIELD_RANK = new Map([...TASK_FIELD_LABELS.keys()].map((field, rank) => [field, rank]));
const NODE_FIELD_RANK = new Map([...NODE_FIELD_LABELS.keys()].map((field, rank) => [field, rank]));
const REFERENCE_FIELD_RANK = new Map([...REFERENCE_FIELD_LABELS.keys()].map((field, rank) => [field, rank]));
const changeSetCache = new WeakMap<WorkflowDefinition, WeakMap<WorkflowDefinition, WorkflowChangeSet>>();

function listAnchor(ids: readonly string[], present: (id: string) => boolean, id: string): WorkflowChangeAnchor {
    for (let position = ids.indexOf(id) - 1; position >= 0; position -= 1) {
        if (present(ids[position])) return { regionId: '', afterId: ids[position], regionPresent: true };
    }
    return { regionId: '', afterId: null, regionPresent: true };
}

function itemLabel(index: DefinitionIndex, scope: string, id: string): string {
    if (scope === 'task') return taskLabel(index.tasks.byId.get(id)?.item);
    if (scope === 'reference') return referenceLabel(index.references.byId.get(id)?.item);
    const entry = index.flow?.nodes.get(id);
    return entry ? nodeLabel(index, entry) : `Block (${id})`;
}

function nodeItemKey(entry: FlowNodeEntry): string | null {
    if (entry.kind !== 'task') return workflowNodeKey(entry.id);
    return entry.taskId === undefined ? null : workflowTaskKey(entry.taskId);
}

/** The outermost node of the unbroken chain of member ancestors above a member node. */
function groupRoot(flow: FlowIndex, entry: FlowNodeEntry, member: (entry: FlowNodeEntry) => boolean): FlowNodeEntry {
    let root = entry;
    for (const id of ancestorNodeIds(flow, entry.id)) {
        const ancestor = flow.nodes.get(id);
        if (!ancestor || !member(ancestor)) break;
        root = ancestor;
    }
    return root;
}

/** Item keys of the member nodes directly connected below a group root. */
function groupMembers(flow: FlowIndex, root: FlowNodeEntry, member: (entry: FlowNodeEntry) => boolean): string[] {
    const result: string[] = [];
    const visit = (entry: FlowNodeEntry, depth: number) => {
        for (const regionId of ownedRegionIds(entry)) {
            for (const id of flow.regions.get(regionId)?.nodeIds ?? []) {
                const child = flow.nodes.get(id);
                if (!child || !member(child)) continue;
                const key = nodeItemKey(child);
                if (key) result.push(key);
                if (depth < FLOW_WALK_DEPTH) visit(child, depth + 1);
            }
        }
    };
    visit(root, 0);
    return result;
}

/**
 * Every unsaved change between the opened baseline and the draft, in reading order, with
 * plain-text before and after summaries. Cached per (baseline, draft) pair.
 */
export function diffWorkflowChanges(baseline: WorkflowDefinition, draft: WorkflowDefinition): WorkflowChangeSet {
    if (baseline === draft) return EMPTY_WORKFLOW_CHANGE_SET;
    let byDraft = changeSetCache.get(baseline);
    const cached = byDraft?.get(draft);
    if (cached) return cached;
    const result = buildChangeSet(baseline, draft);
    if (!byDraft) changeSetCache.set(baseline, byDraft = new WeakMap());
    byDraft.set(draft, result);
    return result;
}

function buildChangeSet(baseline: WorkflowDefinition, draft: WorkflowDefinition): WorkflowChangeSet {
    const { changed } = keyDelta(baseline, draft);
    if (!changed.size) return EMPTY_WORKFLOW_CHANGE_SET;
    const base = indexDefinition(baseline);
    const next = indexDefinition(draft);
    const converted = baseline.definition_version !== draft.definition_version;
    const changes: WorkflowChange[] = [];
    const emitted = new Set<string>();
    const added = new Map<string, string>();
    const removed = new Map<string, string>();
    const fieldsByItem = new Map<string, string[]>();
    for (const key of changed) {
        const itemKey = workflowChangeItemKey(key);
        if (!itemKey || itemKey === key) continue;
        const keys = fieldsByItem.get(itemKey);
        if (keys) keys.push(key);
        else fieldsByItem.set(itemKey, [key]);
    }
    const push = (change: WorkflowChange) => {
        if (emitted.has(change.key)) return;
        emitted.add(change.key);
        changes.push(change);
    };

    const describe = (key: string, info: WorkflowChangeKeyInfo) => {
        if (info.scope === 'workflow') {
            const item = WORKFLOW_KEY_SPEC_MAP.get(info.field);
            return { label: item?.label ?? humanize(info.field), ownerLabel: 'Workflow', owner: { kind: 'workflow' as const },
                kind: info.field === 'definition_version' ? 'version' as const : 'field' as const,
                revertable: item?.revertable ?? true, target: { focusKey: key } };
        }
        if (info.scope === 'order') {
            return { label: info.list === 'tasks' ? 'Task order' : 'Reference order', ownerLabel: 'Workflow',
                owner: { kind: 'workflow' as const }, kind: 'order' as const, revertable: true, target: { focusKey: key } };
        }
        const owner = { kind: info.scope, id: info.id };
        const placement = info.field === 'placement';
        if (info.scope === 'region') {
            const region = next.flow?.regions.get(info.id);
            const nodeId = region?.ownerNodeId;
            return { label: info.field === 'order' ? 'Block order' : region && !nodeId ? 'Final outputs' : 'Outputs',
                ownerLabel: regionLabel(next, info.id), owner, kind: info.field === 'order' ? 'order' as const : 'field' as const,
                revertable: true, target: { focusKey: key, ...(nodeId ? { nodeId } : {}) } };
        }
        const field = info.field ?? '';
        const kind = placement ? 'placement' as const : 'field' as const;
        if (info.scope === 'task') {
            const nodeId = next.flow?.taskNodes.get(info.id);
            return { label: TASK_FIELD_LABELS.get(field) ?? humanize(field),
                ownerLabel: taskLabel((next.tasks.byId.get(info.id) ?? base.tasks.byId.get(info.id))?.item),
                owner, kind, revertable: true, target: { focusKey: key, ...(nodeId !== undefined ? { nodeId } : {}) } };
        }
        if (info.scope === 'node') {
            return { label: NODE_FIELD_LABELS.get(field) ?? humanize(field), ownerLabel: itemLabel(next, 'node', info.id),
                owner, kind, revertable: field !== 'kind', target: { focusKey: key, nodeId: info.id } };
        }
        return { label: REFERENCE_FIELD_LABELS.get(field) ?? humanize(field),
            ownerLabel: referenceLabel((next.references.byId.get(info.id) ?? base.references.byId.get(info.id))?.item),
            owner, kind, revertable: true, target: { focusKey: key } };
    };

    const emitKey = (key: string) => {
        if (!changed.has(key) || emitted.has(key)) return;
        const info = parseWorkflowChangeKey(key);
        // A converted draft places every task in the new flow; that is the format change, not N moves.
        if (converted && info.scope === 'task' && info.field === 'placement') return;
        const beforeValue = workflowKeyValue(baseline, key);
        const afterValue = workflowKeyValue(draft, key);
        let before = summarizeKey(info, beforeValue, base);
        let after = summarizeKey(info, afterValue, next);
        if (before === after) {
            before = clip(compactJson(beforeValue === WORKFLOW_ABSENT ? null : beforeValue));
            after = clip(compactJson(afterValue === WORKFLOW_ABSENT ? null : afterValue));
        }
        const { revertable, ...description } = describe(key, info);
        push({ key, ...description, before, after, revertable: revertable && !converted });
    };

    const emitFields = (itemKey: string, rank: ReadonlyMap<string, number>) => {
        const keys = fieldsByItem.get(itemKey);
        if (!keys) return;
        const fieldOf = (key: string) => key.slice(itemKey.length + 1);
        const position = (key: string) => rank.get(fieldOf(key)) ?? rank.size;
        [...keys].sort((left, right) => position(left) - position(right) || (fieldOf(left) < fieldOf(right) ? -1 : 1))
            .forEach(emitKey);
    };

    const itemChange = (key: string, kind: 'added' | 'removed', descendants: readonly string[], anchor?: WorkflowChangeAnchor) => {
        const info = parseWorkflowChangeKey(key) as { scope: ItemScope; id: string };
        const label = itemLabel(kind === 'added' ? next : base, info.scope, info.id);
        const noun = ITEM_NOUNS.get(info.scope) ?? 'item';
        const nodeId = kind === 'removed' ? undefined : info.scope === 'task' ? next.flow?.taskNodes.get(info.id) : info.scope === 'node' ? info.id : undefined;
        push({
            key, kind, label: `${kind === 'added' ? 'Added' : 'Removed'} ${noun}`, ownerLabel: label,
            owner: { kind: info.scope, id: info.id },
            ...(descendants.length ? { descendantKeys: descendants } : {}),
            before: kind === 'added' ? '(none)' : label,
            after: kind === 'added' ? label : '(removed)',
            revertable: !converted,
            ...(anchor ? { anchor } : {}),
            target: { focusKey: key, ...(nodeId !== undefined ? { nodeId } : {}) },
        });
    };

    const emitTask = (id: string) => {
        const key = workflowTaskKey(id);
        if (base.tasks.byId.has(id)) {
            emitFields(key, TASK_FIELD_RANK);
            return;
        }
        added.set(key, key);
        itemChange(key, 'added', []);
    };

    for (const item of WORKFLOW_KEY_SPECS) if (!TRAILING_WORKFLOW_KEYS.has(item.key)) emitKey(item.key);

    emitKey(WORKFLOW_REFERENCE_ORDER_KEY);
    for (const id of next.references.ids) {
        const key = workflowReferenceKey(id);
        if (base.references.byId.has(id)) {
            emitFields(key, REFERENCE_FIELD_RANK);
            continue;
        }
        added.set(key, key);
        itemChange(key, 'added', []);
    }
    for (const id of base.references.ids) {
        if (next.references.byId.has(id)) continue;
        const key = workflowReferenceKey(id);
        removed.set(key, key);
        itemChange(key, 'removed', [], listAnchor(base.references.ids, (other) => next.references.byId.has(other), id));
    }

    const isAdded = (entry: FlowNodeEntry) => entry.kind === 'task'
        ? entry.taskId !== undefined && next.tasks.byId.has(entry.taskId) && !base.tasks.byId.has(entry.taskId)
        : !controlNodeEntry(base, entry.id);
    const isRemoved = (entry: FlowNodeEntry) => entry.kind === 'task'
        ? entry.taskId !== undefined && base.tasks.byId.has(entry.taskId) && !next.tasks.byId.has(entry.taskId)
        : !controlNodeEntry(next, entry.id);

    if (next.structured && next.flow) {
        const flow = next.flow;
        const emitRegion = (regionId: string) => {
            emitKey(workflowRegionKey(regionId, 'order'));
            emitKey(workflowRegionKey(regionId, 'outputs'));
        };
        emitRegion(flow.rootId);
        for (const id of flow.order) {
            const entry = flow.nodes.get(id);
            const key = entry ? nodeItemKey(entry) : null;
            if (!entry || !key) continue;
            if (isAdded(entry)) {
                const root = groupRoot(flow, entry, isAdded);
                added.set(key, nodeItemKey(root) ?? key);
                if (root === entry) itemChange(key, 'added', groupMembers(flow, entry, isAdded));
            } else if (entry.kind === 'task') {
                emitFields(key, TASK_FIELD_RANK);
            } else {
                emitFields(key, NODE_FIELD_RANK);
                ownedRegionIds(entry).forEach(emitRegion);
            }
        }
        for (const id of next.tasks.ids) if (!flow.taskNodes.has(id)) emitTask(id);
    } else {
        emitKey(WORKFLOW_TASK_ORDER_KEY);
        next.tasks.ids.forEach(emitTask);
    }

    if (base.structured && base.flow) {
        const flow = base.flow;
        for (const id of flow.order) {
            const entry = flow.nodes.get(id);
            const key = entry ? nodeItemKey(entry) : null;
            if (!entry || !key || !isRemoved(entry)) continue;
            const root = groupRoot(flow, entry, isRemoved);
            removed.set(key, nodeItemKey(root) ?? key);
            if (root !== entry) continue;
            const siblings = flow.regions.get(entry.regionId)?.nodeIds ?? [];
            const anchor = listAnchor(siblings, (other) => Boolean(next.flow?.nodes.has(other)), entry.id);
            itemChange(key, 'removed', groupMembers(flow, entry, isRemoved),
                { ...anchor, regionId: entry.regionId, regionPresent: Boolean(next.flow?.regions.has(entry.regionId)) });
        }
    }
    for (const id of base.tasks.ids) {
        const key = workflowTaskKey(id);
        if (next.tasks.byId.has(id) || removed.has(key)) continue;
        removed.set(key, key);
        itemChange(key, 'removed', [], listAnchor(base.tasks.ids, (other) => next.tasks.byId.has(other), id));
    }

    for (const key of TRAILING_WORKFLOW_KEYS) emitKey(key);
    // Field keys the reading-order walk did not reach, such as blocks nested past the walk depth.
    for (const key of changed) {
        const itemKey = workflowChangeItemKey(key);
        if (itemKey !== key && !(itemKey && (added.has(itemKey) || removed.has(itemKey)))) emitKey(key);
    }
    return { changes, byKey: new Map(changes.map((change) => [change.key, change])), added, removed, converted };
}

// ---------------------------------------------------------------------------------------------
// Authors, save confirmation, and the Run as consequence
// ---------------------------------------------------------------------------------------------

/** The last author of a change key; an unattributed change is the user's own. */
export function workflowChangeAuthor(key: string, attribution: WorkflowAttribution): WorkflowChangeStamp {
    return attribution.get(key) ?? USER_STAMP;
}

/**
 * Every distinct author behind a change, AI first. An added or removed item includes the authors
 * of the fields and items inside it, so an assist edit inside a block the user added still shows.
 */
export function workflowChangeAuthors(change: WorkflowChange, attribution: WorkflowAttribution): WorkflowChangeStamp[] {
    const stamps = new Map<string, WorkflowChangeStamp>();
    const add = (stamp: WorkflowChangeStamp | undefined) => {
        if (stamp) stamps.set(`${stamp.author}\u0000${stamp.turnId ?? ''}`, stamp);
    };
    add(attribution.get(change.key));
    if (change.kind === 'added' || change.kind === 'removed') {
        const items = [change.key, ...change.descendantKeys ?? []];
        const prefixes = items.map((key) => `${key}:`);
        items.forEach((key) => add(attribution.get(key)));
        for (const [key, stamp] of attribution) if (prefixes.some((prefix) => key.startsWith(prefix))) add(stamp);
    }
    if (!stamps.size) return [USER_STAMP];
    return [...stamps.values()].sort((left, right) => left.author === right.author ? 0 : left.author === 'ai' ? -1 : 1);
}

/** Saving needs the Confirm and save step when any unsaved change has an AI author. */
export function workflowSaveNeedsConfirmation(changes: readonly WorkflowChange[], attribution: WorkflowAttribution): boolean {
    if (!attribution.size) return false;
    return changes.some((change) => workflowChangeAuthors(change, attribution).some((stamp) => stamp.author === 'ai'));
}

/**
 * Whether saving changes the Microsoft 365 execution fingerprint of a workflow that runs as an
 * account, so the account holder has to approve Run as again. Mirrors the server's fingerprint keys.
 * A save by the Run as account itself is that person's own revision, so it asks nothing; pass the
 * signed-in user as `currentUserId`.
 */
export function workflowRunAsConsequence(
    baseline: WorkflowDefinition,
    draft: WorkflowDefinition,
    changes: readonly WorkflowChange[],
    currentUserId?: string | null,
): boolean {
    const runAs = textOf(draft.m365_run_as_user_id).trim();
    if (!textOf(baseline.m365_run_as_user_id) || !runAs) return false;
    if (currentUserId && runAs === currentUserId.trim()) return false;
    return changes.some((change) => workflowChangeFields(change.key).some((field) => isWorkflowRunAsFingerprintField(field)));
}

/** A readable name for a change key, such as "Draft summary · Instructions". */
export function workflowChangeKeyLabel(key: string, ...definitions: WorkflowDefinition[]): string {
    const info = parseWorkflowChangeKey(key);
    if (info.scope === 'workflow') return WORKFLOW_KEY_SPEC_MAP.get(info.field)?.label ?? humanize(info.field);
    if (info.scope === 'order') return info.list === 'tasks' ? 'Task order' : 'Reference order';
    const index = definitions.map(indexDefinition).find((item) => info.scope === 'region'
        ? item.flow?.regions.has(info.id) : itemExists(item, info.scope, info.id)) ?? (definitions[0] ? indexDefinition(definitions[0]) : null);
    if (!index) return key;
    const field = info.field ?? '';
    if (info.scope === 'region') return `${regionLabel(index, info.id)} · ${field === 'order' ? 'Block order' : 'Outputs'}`;
    const owner = itemLabel(index, info.scope, info.id);
    if (!field) return owner;
    const labels = info.scope === 'task' ? TASK_FIELD_LABELS : info.scope === 'node' ? NODE_FIELD_LABELS : REFERENCE_FIELD_LABELS;
    return `${owner} · ${labels.get(field) ?? humanize(field)}`;
}

// ---------------------------------------------------------------------------------------------
// Revert candidates: immutable helpers
// ---------------------------------------------------------------------------------------------

type Definition = WorkflowDefinition;

function withField<T extends Record<string, unknown>>(record: T, field: string, value: unknown): T {
    if (Object.hasOwn(record, field) && sameEditorValue(record[field], value)) return record;
    const copy: Record<string, unknown> = { ...record };
    Object.defineProperty(copy, field, { value, enumerable: true, writable: true, configurable: true });
    return copy as T;
}

function withoutField<T extends Record<string, unknown>>(record: T, field: string): T {
    if (!Object.hasOwn(record, field)) return record;
    const copy: Record<string, unknown> = { ...record };
    delete copy[field];
    return copy as T;
}

/** Give `record` the source's own value for `field`, or remove it when the source has none. */
function copyField<T extends Record<string, unknown>>(record: T, source: Record<string, unknown>, field: string): T {
    return Object.hasOwn(source, field) ? withField(record, field, source[field]) : withoutField(record, field);
}

function flowRoot(definition: Definition): RegionRow | null {
    return isRegionRow(definition.flow) ? definition.flow : null;
}

/** Copy only the path from the root to one region, so every other region keeps its identity. */
function mapRegion(region: RegionRow, regionId: string, update: (region: RegionRow) => RegionRow, depth = 0): RegionRow {
    if (region.id === regionId) return update(region);
    if (depth >= FLOW_WALK_DEPTH) return region;
    let nodes: unknown[] | null = null;
    region.nodes.forEach((node, position) => {
        if (!isNodeRow(node)) return;
        let next: NodeRow = node;
        for (const branch of REGION_BRANCHES.get(node.kind) ?? []) {
            const child = next[branch];
            if (!isRegionRow(child)) continue;
            const updated = mapRegion(child, regionId, update, depth + 1);
            if (updated !== child) next = { ...next, [branch]: updated };
        }
        if (next !== node) (nodes ??= [...region.nodes])[position] = next;
    });
    return nodes ? { ...region, nodes } : region;
}

function withRegionNodes(definition: Definition, regionId: string, update: (nodes: unknown[]) => readonly unknown[]): Definition {
    const root = flowRoot(definition);
    if (!root) return definition;
    const flow = mapRegion(root, regionId, (region) => {
        const nodes = update(region.nodes);
        return nodes === region.nodes ? region : { ...region, nodes: [...nodes] };
    });
    return flow === root ? definition : { ...definition, flow };
}

function withList(definition: Definition, field: 'tasks' | 'reference_inputs', list: readonly unknown[]): Definition {
    return list === definition[field] ? definition : { ...definition, [field]: list } as Definition;
}

function rowId(value: unknown): string | undefined {
    return isRow(value) ? value.id : undefined;
}

/** Insert after the nearest earlier source sibling that the list still has, or at the start. */
function insertAfterSibling(list: readonly unknown[], item: unknown, sourceIds: readonly string[], id: string): unknown[] {
    const positions = new Map<string, number>();
    list.forEach((entry, position) => {
        const entryId = rowId(entry);
        if (entryId !== undefined && !positions.has(entryId)) positions.set(entryId, position);
    });
    let insertAt = 0;
    for (let position = sourceIds.indexOf(id) - 1; position >= 0; position -= 1) {
        const found = positions.get(sourceIds[position]);
        if (found !== undefined) {
            insertAt = found + 1;
            break;
        }
    }
    const next = [...list];
    next.splice(insertAt, 0, item);
    return next;
}

/** The items both lists share take the source's relative order; every other item keeps its slot. */
function reorderLike(list: readonly unknown[], sourceIds: readonly string[]): readonly unknown[] {
    const rank = new Map<string, number>();
    sourceIds.forEach((id, position) => {
        if (!rank.has(id)) rank.set(id, position);
    });
    const slots: number[] = [];
    const shared: { item: unknown; rank: number }[] = [];
    list.forEach((item, position) => {
        const id = rowId(item);
        const itemRank = id === undefined ? undefined : rank.get(id);
        if (itemRank === undefined) return;
        slots.push(position);
        shared.push({ item, rank: itemRank });
    });
    shared.sort((left, right) => left.rank - right.rank);
    if (shared.every((entry, position) => list[slots[position]] === entry.item)) return list;
    const next = [...list];
    slots.forEach((slot, position) => {
        next[slot] = shared[position].item;
    });
    return next;
}

/**
 * Number tasks by their array position, copying only the tasks whose `order` changes, so an
 * unchanged task keeps its identity and change tracking can skip it without a deep comparison.
 */
export function workflowTasksInOrder<T extends { order: number }>(tasks: readonly T[]): T[] {
    let numbered: T[] | null = null;
    tasks.forEach((task, position) => {
        if (task.order !== position + 1) (numbered ??= [...tasks])[position] = { ...task, order: position + 1 };
    });
    return numbered ?? [...tasks];
}

/** Classic tasks run in array order; renumber `order` without copying tasks that already match. */
function renumberTasks(definition: Definition): Definition {
    let tasks: unknown[] | null = null;
    definition.tasks.forEach((task, position) => {
        if (isRecord(task) && task.order !== position + 1) (tasks ??= [...definition.tasks])[position] = { ...task, order: position + 1 };
    });
    return tasks ? withList(definition, 'tasks', tasks) : definition;
}

// ---------------------------------------------------------------------------------------------
// Revert candidates
// ---------------------------------------------------------------------------------------------

export interface WorkflowRevertResult {
    readonly candidate: WorkflowDefinition;
    /** Keys that could not be reverted, with the reason. The candidate leaves them as they are. */
    readonly failed: ReadonlyMap<string, string>;
}

const RESTORE_ENCLOSING = 'Restore the block that contained it first.';
const REVERT_ENCLOSING = 'Move the block that now contains its old position back first.';
const REVERT_INSIDE = 'Move the existing blocks inside it back out first.';
const ID_IN_USE = 'Another block now uses its ID.';
const FORMAT_ONLY = 'The workflow format can only be discarded with the whole draft.';

interface RevertOp {
    readonly key: string;
    readonly info: WorkflowChangeKeyInfo;
    readonly source: Definition;
}

function sourceDepth(index: DefinitionIndex, scope: ItemScope, id: string): number {
    if (scope === 'reference') return 0;
    const nodeId = scope === 'task' ? index.flow?.taskNodes.get(id) : id;
    return nodeId === undefined ? 0 : ancestorNodeIds(index.flow, nodeId).length;
}

/** The field keys that make up an item, used when an item key is reverted while it still exists. */
function itemFieldKeys(scope: ItemScope, id: string, source: DefinitionIndex, current: DefinitionIndex): string[] {
    if (scope === 'reference') return REFERENCE_FIELDS.map((field) => workflowReferenceKey(id, field));
    if (scope === 'task') {
        const names = fieldNames(source.tasks.byId.get(id)?.item ?? null, current.tasks.byId.get(id)?.item ?? null, TASK_SKIPPED_FIELDS);
        return [...names, 'placement', 'run_when'].map((field) => workflowTaskKey(id, field));
    }
    const names = fieldNames(controlNodeEntry(source, id)?.node ?? null, controlNodeEntry(current, id)?.node ?? null, NODE_SKIPPED_FIELDS);
    return [...names.filter((field) => field !== 'kind'), 'placement'].map((field) => workflowNodeKey(id, field));
}

function nodeEntryFor(index: DefinitionIndex, scope: ItemScope, id: string): FlowNodeEntry | undefined {
    return scope === 'task' ? taskNodeEntry(index, id) : scope === 'node' ? controlNodeEntry(index, id) : undefined;
}

function restoreItem(definition: Definition, op: RevertOp, scope: ItemScope, id: string): Definition | string {
    const index = indexDefinition(definition);
    // Items restored with their enclosing block are already back.
    if (itemExists(index, scope, id)) return definition;
    const source = indexDefinition(op.source);
    if (scope === 'reference') {
        const item = source.references.byId.get(id)?.item;
        return item ? withList(definition, 'reference_inputs', insertAfterSibling(definition.reference_inputs, item, source.references.ids, id)) : definition;
    }
    if (scope === 'task') {
        const item = source.tasks.byId.get(id)?.item;
        if (!item) return definition;
        let next = definition;
        const node = taskNodeEntry(source, id);
        if (node && index.structured && index.flow && !index.flow.taskNodes.has(id)) {
            if (!index.flow.regions.has(node.regionId)) return RESTORE_ENCLOSING;
            if (index.flow.nodes.has(node.id)) return ID_IN_USE;
            const siblings = source.flow?.regions.get(node.regionId)?.nodeIds ?? [];
            next = withRegionNodes(next, node.regionId, (nodes) => insertAfterSibling(nodes, node.node, siblings, node.id));
        }
        return withList(next, 'tasks', insertAfterSibling(next.tasks, item, source.tasks.ids, id));
    }
    const entry = controlNodeEntry(source, id);
    const flow = index.flow;
    if (!entry) return definition;
    if (!index.structured || !flow || !flow.regions.has(entry.regionId)) return RESTORE_ENCLOSING;
    if (flow.nodes.has(id)) return ID_IN_USE;
    const missingTasks: string[] = [];
    // Blocks and tasks that now live elsewhere stay where they are; everything else comes back.
    const keep = (nested: unknown): boolean => {
        if (!isNodeRow(nested)) return true;
        if (flow.nodes.has(nested.id)) return false;
        if (nested.kind !== 'task' || typeof nested.task_id !== 'string') return true;
        if (flow.taskNodes.has(nested.task_id)) return false;
        if (!index.tasks.byId.has(nested.task_id) && source.tasks.byId.has(nested.task_id)) missingTasks.push(nested.task_id);
        return true;
    };
    const prune = (node: NodeRow, depth: number): NodeRow => {
        let next = node;
        for (const branch of REGION_BRANCHES.get(node.kind) ?? []) {
            const child = node[branch];
            if (!isRegionRow(child)) continue;
            const nodes = child.nodes.filter(keep).map((nested) =>
                isNodeRow(nested) && nested.kind !== 'task' && depth < FLOW_WALK_DEPTH ? prune(nested, depth + 1) : nested);
            if (nodes.length !== child.nodes.length || nodes.some((nested, position) => nested !== child.nodes[position])) {
                next = { ...next, [branch]: { ...child, nodes } };
            }
        }
        return next;
    };
    const restored = prune(entry.node, 0);
    const siblings = source.flow?.regions.get(entry.regionId)?.nodeIds ?? [];
    const next = withRegionNodes(definition, entry.regionId, (nodes) => insertAfterSibling(nodes, restored, siblings, id));
    let tasks: readonly unknown[] = next.tasks;
    for (const taskId of missingTasks) {
        const item = source.tasks.byId.get(taskId)?.item;
        if (item) tasks = insertAfterSibling(tasks, item, source.tasks.ids, taskId);
    }
    return withList(next, 'tasks', tasks);
}

function revertPlacement(definition: Definition, op: RevertOp, scope: ItemScope, id: string): Definition | string {
    const index = indexDefinition(definition);
    const source = indexDefinition(op.source);
    const current = nodeEntryFor(index, scope, id);
    const origin = nodeEntryFor(source, scope, id);
    if (!index.flow || !current || !origin || current.regionId === origin.regionId) return definition;
    const target = index.flow.regions.get(origin.regionId);
    if (!target) return RESTORE_ENCLOSING;
    const owners = target.ownerNodeId === undefined ? [] : [target.ownerNodeId, ...ancestorNodeIds(index.flow, target.ownerNodeId)];
    if (owners.includes(current.id)) return REVERT_ENCLOSING;
    const siblings = source.flow?.regions.get(target.id)?.nodeIds ?? [];
    const removed = withRegionNodes(definition, current.regionId, (nodes) => nodes.filter((node) => node !== current.node));
    return withRegionNodes(removed, target.id, (nodes) => insertAfterSibling(nodes, current.node, siblings, current.id));
}

function replaceListItem(definition: Definition, field: 'tasks' | 'reference_inputs', entry: ListEntry, item: Row): Definition {
    if (item === entry.item) return definition;
    const list = [...definition[field]];
    list[entry.index] = item as never;
    return withList(definition, field, list);
}

function revertField(definition: Definition, op: RevertOp): Definition {
    const info = op.info;
    if (info.scope === 'workflow' || info.scope === 'order') return definition;
    const index = indexDefinition(definition);
    const source = indexDefinition(op.source);
    const field = info.field ?? '';
    if (info.scope === 'region') {
        const origin = source.flow?.regions.get(info.id);
        if (!origin || !index.flow?.regions.has(info.id)) return definition;
        const root = flowRoot(definition);
        const flow = root ? mapRegion(root, info.id, (region) => copyField(region, origin.region, field)) : root;
        return flow && flow !== root ? { ...definition, flow } : definition;
    }
    if (info.scope === 'reference') {
        const entry = index.references.byId.get(info.id);
        const origin = source.references.byId.get(info.id);
        if (!entry || !origin) return definition;
        const names = field === 'document' ? fieldNames(entry.item, origin.item, new Set(['id', 'name'])) : [field];
        return replaceListItem(definition, 'reference_inputs', entry, names.reduce((item, name) => copyField(item, origin.item, name), entry.item));
    }
    if (info.scope === 'task' && field !== 'run_when') {
        const entry = index.tasks.byId.get(info.id);
        const origin = source.tasks.byId.get(info.id);
        return entry && origin ? replaceListItem(definition, 'tasks', entry, copyField(entry.item, origin.item, field)) : definition;
    }
    const scope = info.scope === 'task' ? 'task' : 'node';
    const entry = nodeEntryFor(index, scope, info.id);
    const origin = nodeEntryFor(source, scope, info.id);
    if (!entry || !origin || field === 'kind') return definition;
    const node = copyField(entry.node, origin.node, field);
    return node === entry.node ? definition : withRegionNodes(definition, entry.regionId, (nodes) => nodes.map((item) => item === entry.node ? node : item));
}

function removeItem(definition: Definition, op: RevertOp, scope: ItemScope, id: string): Definition | string {
    const index = indexDefinition(definition);
    if (!itemExists(index, scope, id)) return definition;
    if (scope === 'reference') return withList(definition, 'reference_inputs', definition.reference_inputs.filter((item) => rowId(item) !== id));
    if (scope === 'task') {
        const node = taskNodeEntry(index, id);
        const next = node ? withRegionNodes(definition, node.regionId, (nodes) => nodes.filter((item) => item !== node.node)) : definition;
        return withList(next, 'tasks', next.tasks.filter((item) => rowId(item) !== id));
    }
    const entry = controlNodeEntry(index, id);
    const flow = index.flow;
    if (!entry || !flow) return definition;
    const source = indexDefinition(op.source);
    const taskIds = new Set<string>();
    // Removing an added block must never delete a block or task that existed before it.
    for (const nestedId of subtreeNodeIds(flow, id)) {
        const nested = flow.nodes.get(nestedId);
        if (!nested) continue;
        if (nested.kind !== 'task' && controlNodeEntry(source, nestedId)) return REVERT_INSIDE;
        if (nested.taskId === undefined) continue;
        if (source.tasks.byId.has(nested.taskId)) return REVERT_INSIDE;
        taskIds.add(nested.taskId);
    }
    const next = withRegionNodes(definition, entry.regionId, (nodes) => nodes.filter((item) => item !== entry.node));
    if (!taskIds.size) return next;
    return withList(next, 'tasks', next.tasks.filter((item) => {
        const taskId = rowId(item);
        return taskId === undefined || !taskIds.has(taskId);
    }));
}

function revertOrder(definition: Definition, op: RevertOp): Definition {
    const info = op.info;
    const source = indexDefinition(op.source);
    if (info.scope === 'order') {
        return info.list === 'tasks'
            ? withList(definition, 'tasks', reorderLike(definition.tasks, source.tasks.ids))
            : withList(definition, 'reference_inputs', reorderLike(definition.reference_inputs, source.references.ids));
    }
    if (info.scope !== 'region') return definition;
    const origin = source.flow?.regions.get(info.id);
    return origin ? withRegionNodes(definition, info.id, (nodes) => reorderLike(nodes, origin.nodeIds)) : definition;
}

function revertWorkflowField(definition: Definition, op: RevertOp): Definition | string {
    if (op.info.scope !== 'workflow') return definition;
    const item = WORKFLOW_KEY_SPEC_MAP.get(op.info.field);
    if (!item) return definition;
    if (!item.revertable) return FORMAT_ONLY;
    return item.fields.reduce((next, field) => copyField(next, op.source, field), definition);
}

/**
 * A candidate that takes each key back to its value in the source (the opened baseline, or the
 * version before an assist turn), leaving every other key as it is. Removed items come back
 * where they were, and added items are removed. Keys that cannot be reverted are reported.
 */
export function buildWorkflowKeyRevert(
    current: WorkflowDefinition,
    source: WorkflowDefinition | ((key: string) => WorkflowDefinition),
    keys: Iterable<string>,
): WorkflowRevertResult {
    const sourceOf = typeof source === 'function' ? source : () => source;
    const currentIndex = indexDefinition(current);
    const restores: (RevertOp & { depth: number })[] = [];
    const placements: RevertOp[] = [];
    const fields: RevertOp[] = [];
    const removals: RevertOp[] = [];
    const orders: RevertOp[] = [];
    const workflowFields: RevertOp[] = [];
    const seen = new Set<string>();
    const classify = (key: string, from: Definition) => {
        if (seen.has(key)) return;
        seen.add(key);
        const info = parseWorkflowChangeKey(key);
        const op = { key, info, source: from };
        if (info.scope === 'workflow') workflowFields.push(op);
        else if (info.scope === 'order' || info.scope === 'region' && info.field === 'order') orders.push(op);
        else if (info.scope === 'region') fields.push(op);
        else if (info.field === 'placement' && info.scope !== 'reference') placements.push(op);
        else if (info.field) fields.push(op);
        else {
            const sourceIndex = indexDefinition(from);
            const inSource = itemExists(sourceIndex, info.scope, info.id);
            const inCurrent = itemExists(currentIndex, info.scope, info.id);
            if (inSource && !inCurrent) restores.push({ ...op, depth: sourceDepth(sourceIndex, info.scope, info.id) });
            else if (inCurrent && !inSource) removals.push(op);
            else if (inSource) itemFieldKeys(info.scope, info.id, sourceIndex, currentIndex).forEach((field) => classify(field, from));
        }
    };
    for (const key of keys) classify(key, sourceOf(key));

    const failed = new Map<string, string>();
    let working = current;
    const attempt = (op: RevertOp, apply: (definition: Definition, scope: ItemScope, id: string) => Definition | string) => {
        const info = op.info;
        const result = apply(working, info.scope === 'task' || info.scope === 'node' || info.scope === 'reference' ? info.scope : 'task',
            'id' in info ? info.id : '');
        if (typeof result === 'string') failed.set(op.key, result);
        else working = result;
    };
    restores.sort((left, right) => left.depth - right.depth);
    for (const op of restores) attempt(op, (definition, scope, id) => restoreItem(definition, op, scope, id));
    for (const op of placements) attempt(op, (definition, scope, id) => revertPlacement(definition, op, scope, id));
    for (const op of fields) attempt(op, (definition) => revertField(definition, op));
    for (const op of removals) attempt(op, (definition, scope, id) => removeItem(definition, op, scope, id));
    for (const op of orders) attempt(op, (definition) => revertOrder(definition, op));
    for (const op of workflowFields) attempt(op, (definition) => revertWorkflowField(definition, op));
    if (working.tasks !== current.tasks && !indexDefinition(working).structured) working = renumberTasks(working);
    return { candidate: working, failed };
}

// ---------------------------------------------------------------------------------------------
// Reverting an assist turn
// ---------------------------------------------------------------------------------------------

/** One history entry of a turn: the definitions before and after it. */
export interface WorkflowTurnEntry {
    readonly before: WorkflowDefinition;
    readonly after: WorkflowDefinition;
}

export interface WorkflowTurnRevertPlan {
    /** Keys that still hold the value the turn produced; these revert. */
    readonly keys: readonly string[];
    /** Keys changed again after the turn; reverting them would discard later work. */
    readonly skipped: readonly string[];
    /** The entry whose `before` holds a key's pre-turn value; sub-keys map to their item. */
    readonly entryFor: (key: string) => number;
}

// Items compare as a whole: the item, where it sits, and for a block the tasks inside it.
function turnSnapshot(definition: Definition, key: string): unknown {
    const info = parseWorkflowChangeKey(key);
    if (info.scope !== 'task' && info.scope !== 'node' || info.field) return workflowKeyValue(definition, key);
    const index = indexDefinition(definition);
    if (info.scope === 'task') {
        const node = taskNodeEntry(index, info.id);
        return [index.tasks.byId.get(info.id)?.item ?? WORKFLOW_ABSENT, node?.node ?? WORKFLOW_ABSENT, node?.regionId ?? WORKFLOW_ABSENT];
    }
    const entry = controlNodeEntry(index, info.id);
    if (!entry || !index.flow) return WORKFLOW_ABSENT;
    const flow = index.flow;
    const tasks = subtreeNodeIds(flow, info.id).map((id) => {
        const taskId = flow.nodes.get(id)?.taskId;
        return taskId === undefined ? WORKFLOW_ABSENT : index.tasks.byId.get(taskId)?.item ?? WORKFLOW_ABSENT;
    });
    return [entry.node, entry.regionId, tasks];
}

/**
 * Which keys an assist turn changed, and which of them can still be reverted. A key reverts only
 * while it holds exactly what the turn produced; a key already back at its pre-turn value is
 * ignored, and a key changed again later is skipped, so reverting never discards later work.
 * `entries` are the turn's applied history entries, oldest first.
 */
export function planWorkflowTurnRevert(current: WorkflowDefinition, entries: readonly WorkflowTurnEntry[]): WorkflowTurnRevertPlan {
    const deltas = entries.map((entry) => keyDelta(entry.before, entry.after).changed);
    // Fields of an item the turn added or removed revert with the whole item.
    const items = new Set<string>();
    for (const changed of deltas) for (const key of changed) if (workflowChangeItemKey(key) === key) items.add(key);
    const topKey = (key: string) => {
        const itemKey = workflowChangeItemKey(key);
        return itemKey && items.has(itemKey) ? itemKey : key;
    };
    const first = new Map<string, number>();
    const last = new Map<string, number>();
    deltas.forEach((changed, position) => {
        for (const key of changed) {
            const top = topKey(key);
            if (!first.has(top)) first.set(top, position);
            last.set(top, position);
        }
    });
    const keys: string[] = [];
    const skipped: string[] = [];
    for (const [key, position] of first) {
        const now = turnSnapshot(current, key);
        if (sameWorkflowKeyValue(key, now, turnSnapshot(entries[position].before, key))) continue;
        const produced = turnSnapshot(entries[last.get(key) ?? position].after, key);
        (sameWorkflowKeyValue(key, now, produced) ? keys : skipped).push(key);
    }
    return { keys, skipped, entryFor: (key) => first.get(topKey(key)) ?? first.get(key) ?? 0 };
}

// ---------------------------------------------------------------------------------------------
// Structural identity
// ---------------------------------------------------------------------------------------------

function joinId(entry: FlowNodeEntry): unknown {
    return isRecord(entry.node.join) ? entry.node.join.id : WORKFLOW_ABSENT;
}

/**
 * Why `after` gives an ID it shares with `before` a different meaning, or '' when every shared ID
 * keeps its meaning. Blocks keep their kind, task, regions, and join; tasks keep their block; and
 * regions keep their owner. Bindings select sources by these IDs, so a reused ID would silently
 * rebind them.
 */
export function workflowIdentityChange(before: WorkflowDefinition, after: WorkflowDefinition): string {
    const a = indexDefinition(before);
    const b = indexDefinition(after);
    if (a.structured !== b.structured) return 'The workflow format cannot change.';
    if (!a.flow || !b.flow) return '';
    if (a.flow.rootId !== b.flow.rootId) return 'The flow must keep its root ID.';
    for (const [id, entry] of a.flow.nodes) {
        const next = b.flow.nodes.get(id);
        if (!next) continue;
        if (next.kind !== entry.kind || next.taskId !== entry.taskId) return `Block ${id} must keep its kind and task.`;
        if (!sameIds(ownedRegionIds(entry), ownedRegionIds(next)) || joinId(entry) !== joinId(next)) {
            return `Block ${id} must keep its branch, body, and join IDs.`;
        }
    }
    for (const [taskId, nodeId] of a.flow.taskNodes) {
        const next = b.flow.taskNodes.get(taskId);
        if (next !== undefined && next !== nodeId) return `Task ${taskId} must stay in its block.`;
    }
    for (const [id, region] of a.flow.regions) {
        const next = b.flow.regions.get(id);
        if (next && (next.ownerNodeId !== region.ownerNodeId || next.branch !== region.branch)) return `Region ${id} must keep its block.`;
    }
    return '';
}
