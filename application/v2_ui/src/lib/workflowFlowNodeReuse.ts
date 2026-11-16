// workflowFlowNodeReuse.ts
// Keeps a React Flow node object when a rebuild produced an equal node.
//
// React Flow treats a node object it has not seen before as a new node: it throws away the
// handle positions it measured, and every edge to that node disappears until it is measured
// again. Rebuilding the node list therefore returns the previous object for each node that did
// not change, and the previous list itself when no node changed, so React Flow has nothing to
// adopt again.

type PlainRecord = Record<string, unknown>;

function isPlainRecord(value: unknown): value is PlainRecord {
    if (value === null || typeof value !== 'object') return false;
    const prototype = Object.getPrototypeOf(value);
    return prototype === Object.prototype || prototype === null;
}

function hasKey(record: PlainRecord, key: string) {
    return Object.prototype.hasOwnProperty.call(record, key);
}

function sameEntries(left: PlainRecord, right: PlainRecord, same: (a: unknown, b: unknown) => boolean,
    ignored: readonly string[] = []): boolean {
    const keys = Object.keys(left).filter((key) => !ignored.includes(key));
    return keys.length === Object.keys(right).filter((key) => !ignored.includes(key)).length &&
        keys.every((key) => hasKey(right, key) && same(left[key], right[key]));
}

function sameValue(left: unknown, right: unknown) {
    if (Object.is(left, right)) return true;
    return isPlainRecord(left) && isPlainRecord(right) && sameEntries(left, right, Object.is);
}

/**
 * Two nodes are equal when they have the same fields with identical values. A plain-object field,
 * such as data, style or position, is compared one level down, so a literal rebuilt with the same
 * values is still equal. Arrays, maps and deeper objects are compared by identity. Ignored fields
 * never make two nodes different.
 */
export function sameFlowNode(previous: object, next: object, ignored: readonly string[] = []): boolean {
    return previous === next || sameEntries(previous as PlainRecord, next as PlainRecord, sameValue, ignored);
}

/**
 * Returns the rebuilt nodes with every node that equals the previous node of the same ID replaced
 * by that previous object. When every node is kept in the same order, returns the previous array.
 */
export function reuseUnchangedFlowNodes<T extends { id: string }>(previous: T[], next: T[],
    ignored: readonly string[] = []): T[] {
    const byId = new Map(previous.map((node) => [node.id, node]));
    let unchanged = previous.length === next.length;
    const nodes = next.map((node, index) => {
        const prior = byId.get(node.id);
        const kept = prior !== undefined && sameFlowNode(prior, node, ignored) ? prior : node;
        if (kept !== previous[index]) unchanged = false;
        return kept;
    });
    return unchanged ? previous : nodes;
}
