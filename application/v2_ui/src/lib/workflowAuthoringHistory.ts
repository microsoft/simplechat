// workflowAuthoringHistory.ts
// Session-local history for caller-owned immutable, data-only authoring checkpoints.

export const WORKFLOW_HISTORY_MAX_ENTRIES = 100;
export const WORKFLOW_HISTORY_MAX_BYTES = 32 * 1024 * 1024;

export type WorkflowHistoryDirection = 'undo' | 'redo';

export interface WorkflowHistoryAction {
    label: string;
    group?: string;
    targetId?: string;
}

export interface WorkflowHistoryEntry<T> {
    readonly id: number;
    readonly before: T;
    readonly after: T;
    readonly action: WorkflowHistoryAction;
}

export type WorkflowHistoryRecordResult = {
    status: 'applied' | 'noop' | 'overflow';
    evicted: number;
};

interface HistoryObject {
    bytes: number;
    children: readonly object[];
}

const CONTAINER_BYTES = 64;
const ARRAY_SLOT_BYTES = 8;
const MAP_ENTRY_BYTES = 48;

function isContainer(value: unknown): value is object {
    return value !== null && typeof value === 'object';
}

function primitiveBytes(value: unknown): number {
    if (typeof value === 'string') return 16 + 2 * value.length;
    if (typeof value === 'number') return 8;
    if (value === null || value === undefined || typeof value === 'boolean') return 4;
    throw new TypeError('Workflow history accepts only data values, not functions, symbols, or bigints.');
}

function propertyBytes(key: string): number {
    return primitiveBytes(key) + 16;
}

function copyAction(action: WorkflowHistoryAction): WorkflowHistoryAction {
    if (!isContainer(action) || ![Object.prototype, null].includes(Object.getPrototypeOf(action))) {
        throw new TypeError('Workflow history actions must be plain data objects.');
    }
    const field = (key: keyof WorkflowHistoryAction): unknown => {
        const descriptor = Object.getOwnPropertyDescriptor(action, key);
        if (descriptor && !('value' in descriptor)) {
            throw new TypeError('Workflow history actions cannot contain accessor properties.');
        }
        return descriptor?.value;
    };
    const label = field('label');
    const group = field('group');
    const targetId = field('targetId');
    if (typeof label !== 'string' || (group !== undefined && typeof group !== 'string')
        || (targetId !== undefined && typeof targetId !== 'string')) {
        throw new TypeError('Workflow history action labels, groups, and targets must be strings.');
    }
    return Object.freeze({
        label,
        ...(group === undefined ? {} : { group }),
        ...(targetId === undefined ? {} : { targetId }),
    });
}

function entryMetadataBytes<T>(entry: WorkflowHistoryEntry<T>): number {
    const action = copyAction(entry.action);
    let bytes = CONTAINER_BYTES + propertyBytes('id') + 8
        + propertyBytes('before') + propertyBytes('after') + propertyBytes('action')
        + CONTAINER_BYTES + propertyBytes('label') + primitiveBytes(action.label);
    if (action.group !== undefined) bytes += propertyBytes('group') + primitiveBytes(action.group);
    if (action.targetId !== undefined) bytes += propertyBytes('targetId') + primitiveBytes(action.targetId);
    return bytes;
}

/**
 * Primitive leaves belong to their container; shared object graphs are charged once.
 * Root primitives belong to each entry's before/after slot (a conservative charge).
 * Only weak caches survive an accounting pass, so evicted/proposed states are not pinned.
 *
 * Accept acyclic plain objects (including null prototypes), arrays, and Maps, with
 * string-keyed data properties. Accessors, symbols, functions, bigints, and other
 * prototypes are rejected rather than evaluated, serialized, or silently omitted.
 */
class HistoryAccounting {
    private readonly descriptions = new WeakMap<object, HistoryObject>();
    private readonly validated = new WeakSet<object>();
    private readonly baselineObjects = new WeakSet<object>();
    private readonly primitiveBaseline: { value: unknown } | null;

    constructor(baseline: unknown) {
        this.validate(baseline);
        this.primitiveBaseline = isContainer(baseline) ? null : { value: baseline };
        if (isContainer(baseline)) {
            const pending = [baseline];
            while (pending.length) {
                const value = pending.pop()!;
                if (this.baselineObjects.has(value)) continue;
                this.baselineObjects.add(value);
                for (const child of this.describe(value).children) pending.push(child);
            }
        }
    }

    private describe(value: object): HistoryObject {
        const cached = this.descriptions.get(value);
        if (cached) return cached;
        const prototype = Object.getPrototypeOf(value);
        const array = Array.isArray(value);
        if (array ? prototype !== Array.prototype
            : prototype !== Map.prototype && prototype !== Object.prototype && prototype !== null) {
            throw new TypeError('Workflow history checkpoints must use plain objects, arrays, or Maps.');
        }
        let bytes = CONTAINER_BYTES;
        const children: object[] = [];
        const addValue = (child: unknown) => {
            if (isContainer(child)) children.push(child);
            else bytes += primitiveBytes(child);
        };
        if (array) bytes += value.length * ARRAY_SLOT_BYTES;
        if (prototype === Map.prototype) {
            const entries = Map.prototype.entries.call(value) as Iterable<[unknown, unknown]>;
            for (const [key, child] of entries) {
                bytes += MAP_ENTRY_BYTES;
                addValue(key);
                addValue(child);
            }
        }
        for (const key of Reflect.ownKeys(value)) {
            if (typeof key !== 'string') {
                throw new TypeError('Workflow history checkpoints cannot contain symbol properties.');
            }
            if (array && key === 'length') continue;
            const descriptor = Object.getOwnPropertyDescriptor(value, key);
            if (!descriptor || !('value' in descriptor)) {
                throw new TypeError('Workflow history checkpoints cannot contain accessor properties.');
            }
            const index = Number(key);
            const arraySlot = array && Number.isInteger(index) && index >= 0
                && index < value.length && String(index) === key;
            if (!arraySlot) bytes += propertyBytes(key);
            addValue(descriptor.value);
        }
        const description = { bytes, children };
        this.descriptions.set(value, description);
        return description;
    }

    validate(root: unknown): void {
        if (!isContainer(root)) {
            primitiveBytes(root);
            return;
        }
        if (this.validated.has(root)) return;
        const pending = [{ value: root, exiting: false }];
        const active = new Set<object>();
        const visited = new Set<object>();
        while (pending.length) {
            const { value, exiting } = pending.pop()!;
            if (exiting) {
                active.delete(value);
                continue;
            }
            if (this.validated.has(value)) continue;
            if (active.has(value)) throw new TypeError('Workflow history checkpoints must not contain cycles.');
            if (visited.has(value)) continue;
            visited.add(value);
            active.add(value);
            pending.push({ value, exiting: true });
            for (const child of this.describe(value).children) pending.push({ value: child, exiting: false });
        }
        for (const value of visited) this.validated.add(value);
    }

    measure<T>(entries: readonly WorkflowHistoryEntry<T>[]): number {
        if (!entries.length) return 0;
        const union = new Set<object>();
        const states = new WeakMap<object, number>();
        let unionBytes = 0;
        let minimumLiveBytes = Infinity;
        let metadataBytes = CONTAINER_BYTES + entries.length * ARRAY_SLOT_BYTES;
        const stateBytes = (root: unknown): number => {
            this.validate(root);
            if (!isContainer(root)) {
                const bytes = this.primitiveBaseline && Object.is(root, this.primitiveBaseline.value)
                    ? 0 : primitiveBytes(root);
                unionBytes += bytes;
                return bytes;
            }
            const cached = states.get(root);
            if (cached !== undefined) return cached;
            let bytes = 0;
            const visited = new Set<object>();
            const pending = [root];
            while (pending.length) {
                const value = pending.pop()!;
                if (this.baselineObjects.has(value) || visited.has(value)) continue;
                visited.add(value);
                const description = this.describe(value);
                bytes += description.bytes;
                if (!union.has(value)) {
                    union.add(value);
                    unionBytes += description.bytes;
                }
                for (const child of description.children) pending.push(child);
            }
            states.set(root, bytes);
            return bytes;
        };
        for (const entry of entries) {
            minimumLiveBytes = Math.min(minimumLiveBytes, stateBytes(entry.before), stateBytes(entry.after));
            metadataBytes += entryMetadataBytes(entry);
        }
        // The smallest reachable live graph gives the largest extra retention.
        // Crediting only today's live state would undercount large additions/deletions.
        return unionBytes - minimumLiveBytes + metadataBytes;
    }
}

/**
 * Deterministic additional retention, not a measurement of the JavaScript heap.
 * Excludes fixed opening-baseline objects and one live state at EVERY reachable
 * cursor, then includes the entry array, entry records, and copied action metadata.
 */
export function workflowHistoryRetainedBytes<T>(
    baseline: T,
    entries: readonly WorkflowHistoryEntry<T>[],
): number {
    return new HistoryAccounting(baseline).measure(entries);
}

function historyLimit(value: number, name: string): number {
    if (!Number.isSafeInteger(value) || value < 0) {
        throw new RangeError(`Workflow history ${name} must be a nonnegative safe integer.`);
    }
    return value;
}

export class WorkflowAuthoringHistory<T> {
    private readonly equals: (left: T, right: T) => boolean;
    private readonly maxEntries: number;
    private readonly maxBytes: number;
    private readonly accounting: HistoryAccounting;
    private entries: WorkflowHistoryEntry<T>[] = [];
    private cursor = 0;
    private bytes = 0;
    private nextId = 1;
    private openEntryId: number | null = null;

    constructor(
        baseline: T,
        equals: (left: T, right: T) => boolean,
        limits: { maxEntries?: number; maxBytes?: number } = {},
    ) {
        this.equals = equals;
        this.maxEntries = historyLimit(
            limits.maxEntries === undefined ? WORKFLOW_HISTORY_MAX_ENTRIES : limits.maxEntries, 'maxEntries',
        );
        this.maxBytes = historyLimit(
            limits.maxBytes === undefined ? WORKFLOW_HISTORY_MAX_BYTES : limits.maxBytes, 'maxBytes',
        );
        this.accounting = new HistoryAccounting(baseline);
    }

    get entryCount(): number {
        return this.entries.length;
    }

    get retainedBytes(): number {
        return this.bytes;
    }

    peek(direction: WorkflowHistoryDirection): WorkflowHistoryEntry<T> | null {
        if (direction === 'undo') return this.entries[this.cursor - 1] ?? null;
        if (direction === 'redo') return this.entries[this.cursor] ?? null;
        throw new TypeError('Workflow history direction must be undo or redo.');
    }

    record(before: T, after: T, action: WorkflowHistoryAction): WorkflowHistoryRecordResult {
        this.accounting.validate(before);
        this.accounting.validate(after);
        const metadata = copyAction(action);
        if (this.equals(before, after)) return { status: 'noop', evicted: 0 };
        const previous = this.peek('undo');
        const coalescing = Boolean(metadata.group) && this.cursor === this.entries.length
            && previous !== null && previous.id === this.openEntryId && previous.action.group === metadata.group;
        const originalBefore = coalescing ? previous!.before : before;
        const prefix = this.entries.slice(0, this.cursor - (coalescing ? 1 : 0));
        if (coalescing && this.equals(originalBefore, after)) {
            // The latest edit still commits; only the now-net-empty undo step vanishes.
            this.bytes = this.accounting.measure(prefix);
            this.entries = prefix;
            this.cursor = prefix.length;
            this.closeGroup();
            return { status: 'applied', evicted: 0 };
        }
        const proposed: WorkflowHistoryEntry<T> = Object.freeze({
            id: coalescing ? previous!.id : this.nextId,
            before: originalBefore,
            after,
            action: metadata,
        });
        if (this.accounting.measure([proposed]) > this.maxBytes || this.maxEntries === 0) {
            return { status: 'overflow', evicted: 0 };
        }
        const candidates = [...prefix, proposed];
        let evicted = Math.max(0, candidates.length - this.maxEntries);
        let bytes = this.accounting.measure(candidates.slice(evicted));
        if (bytes > this.maxBytes) {
            // Dropping a prefix only shrinks the union and raises its minimum live
            // credit. Find the smallest whole-entry eviction without quadratic scans.
            let low = evicted + 1;
            let high = candidates.length - 1;
            while (low < high) {
                const middle = Math.floor((low + high) / 2);
                if (this.accounting.measure(candidates.slice(middle)) <= this.maxBytes) high = middle;
                else low = middle + 1;
            }
            evicted = low;
            bytes = this.accounting.measure(candidates.slice(evicted));
        }
        this.entries = candidates.slice(evicted);
        this.cursor = this.entries.length;
        this.bytes = bytes;
        if (!coalescing) this.nextId++;
        this.openEntryId = metadata.group ? proposed.id : null;
        return { status: 'applied', evicted };
    }

    replay(direction: WorkflowHistoryDirection, expectedEntryId: number): T | undefined {
        const entry = this.peek(direction);
        if (!entry || entry.id !== expectedEntryId) return undefined;
        this.cursor += direction === 'undo' ? -1 : 1;
        this.closeGroup();
        return direction === 'undo' ? entry.before : entry.after;
    }

    closeGroup(): void {
        this.openEntryId = null;
    }

    clear(): void {
        this.entries = [];
        this.cursor = 0;
        this.bytes = 0;
        this.closeGroup();
    }
}
