// test_workflow_authoring_history.js
/*
Offline contracts for bounded, immutable workflow authoring history.
Version: 0.261.123
Implemented in: 0.261.123

Loads the production TypeScript model through the existing Node resolver.
Exercises exact checkpoint restoration, Map-shaped field buffers, grouping,
transactional overflow, the actual 100-action/32-MiB limits, and weak retention.
No browser, workflow execution, service connection, or dependency installation.
*/

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const { before, test } = require('node:test');
const { pathToFileURL } = require('node:url');
const { isDeepStrictEqual } = require('node:util');

const root = path.resolve(__dirname, '..');
let historyApi;

async function loadProductionModule() {
    // Register the repository resolver before importing the real production module.
    await import(pathToFileURL(path.join(__dirname, 'test_support', 'tsResolve.mjs')));
    historyApi = await import(pathToFileURL(path.join(
        root, 'application', 'v2_ui', 'src', 'lib', 'workflowAuthoringHistory.ts',
    )));
}

function freezeData(rootValue) {
    const pending = [rootValue];
    const visited = new Set();
    while (pending.length) {
        const value = pending.pop();
        if (!value || typeof value !== 'object' || visited.has(value)) continue;
        visited.add(value);
        if (value instanceof Map) {
            for (const [key, child] of value) pending.push(key, child);
        }
        for (const descriptor of Object.values(Object.getOwnPropertyDescriptors(value))) {
            if ('value' in descriptor) pending.push(descriptor.value);
        }
        Object.freeze(value);
    }
    return rootValue;
}

function state(value) {
    return Object.freeze({ value });
}

function createHistory(baseline, limits) {
    return new historyApi.WorkflowAuthoringHistory(baseline, isDeepStrictEqual, limits);
}

function entry(id, beforeValue, afterValue, action = { label: 'edit' }) {
    return { id, before: beforeValue, after: afterValue, action };
}

function applied(history, beforeValue, afterValue, action = { label: 'edit' }, evicted = 0) {
    assert.deepEqual(history.record(beforeValue, afterValue, action), { status: 'applied', evicted });
    return history.peek('undo');
}

function replay(history, direction) {
    const next = history.peek(direction);
    assert.ok(next, `Expected an available ${direction} entry.`);
    return history.replay(direction, next.id);
}

function inspect(history) {
    return {
        count: history.entryCount,
        bytes: history.retainedBytes,
        undo: history.peek('undo'),
        redo: history.peek('redo'),
    };
}

function assertUnchanged(history, previous) {
    assert.equal(history.entryCount, previous.count);
    assert.equal(history.retainedBytes, previous.bytes);
    assert.strictEqual(history.peek('undo'), previous.undo);
    assert.strictEqual(history.peek('redo'), previous.redo);
}

function registerTests() {
    test('approved limits and an empty history retain no checkpoint bytes', () => {
        assert.equal(historyApi.WORKFLOW_HISTORY_MAX_ENTRIES, 100);
        assert.equal(historyApi.WORKFLOW_HISTORY_MAX_BYTES, 33_554_432);
        const baseline = state(0);
        const history = createHistory(baseline);
        assert.deepEqual(inspect(history), { count: 0, bytes: 0, undo: null, redo: null });
        assert.equal(history.replay('undo', 1), undefined);
        assert.equal(history.replay('redo', 1), undefined);
        assert.equal(historyApi.workflowHistoryRetainedBytes(baseline, []), 0);
        history.closeGroup();
        history.clear();
        assert.equal(history.retainedBytes, 0);
    });

    test('discrete edits retain exact immutable checkpoint identities and copied metadata', () => {
        const baseline = state(0);
        const second = state(1);
        const third = state(2);
        const history = createHistory(baseline);
        const action = { label: 'Add task', targetId: 'constructor' };
        const first = applied(history, baseline, second, action);
        action.label = 'Changed outside history';
        action.targetId = 'another-node';
        assert.deepEqual(first.action, { label: 'Add task', targetId: 'constructor' });
        assert.equal(Object.isFrozen(action), false, 'Do not freeze caller-owned action objects.');
        assert.equal(Object.isFrozen(first), true);
        assert.equal(Object.isFrozen(first.action), true);
        assert.strictEqual(first.before, baseline);
        assert.strictEqual(first.after, second);
        const next = applied(history, second, third, { label: 'Move task', targetId: 'node-2' });
        assert.notEqual(first.id, next.id);
        assert.equal(history.entryCount, 2);
        const bytes = history.retainedBytes;
        assert.strictEqual(replay(history, 'undo'), second);
        assert.strictEqual(replay(history, 'undo'), baseline);
        assert.equal(history.peek('undo'), null);
        assert.strictEqual(replay(history, 'redo'), second);
        assert.strictEqual(replay(history, 'redo'), third);
        assert.equal(history.peek('redo'), null);
        assert.equal(history.retainedBytes, bytes);
    });

    test('consecutive field edits coalesce from their first before with a stable entry ID', () => {
        const values = ['a', 'ab', 'abc', 'abcd'].map(state);
        const history = createHistory(values[0]);
        const first = applied(history, values[0], values[1], {
            label: 'Edit name', group: 'workflow:name', targetId: 'workflow',
        });
        applied(history, values[1], values[2], {
            label: 'Edit workflow name', group: 'workflow:name', targetId: 'workflow',
        });
        const last = applied(history, values[2], values[3], {
            label: 'Finish name', group: 'workflow:name', targetId: 'workflow',
        });
        assert.equal(history.entryCount, 1);
        assert.equal(last.id, first.id);
        assert.strictEqual(last.before, values[0]);
        assert.strictEqual(last.after, values[3]);
        assert.equal(last.action.label, 'Finish name');
        assert.strictEqual(first.after, values[1], 'An earlier peek result must never be mutated.');
        assert.strictEqual(replay(history, 'undo'), values[0]);
        assert.strictEqual(replay(history, 'redo'), values[3]);
        assert.equal(history.retainedBytes, historyApi.workflowHistoryRetainedBytes(values[0], [last]));
    });

    test('explicit closure, different fields, discrete actions, and empty groups split visits', () => {
        const values = Array.from({ length: 9 }, (_, index) => state(index));
        const history = createHistory(values[0]);
        const field = { label: 'Edit name', group: 'workflow:name' };
        applied(history, values[0], values[1], field);
        history.closeGroup();
        applied(history, values[1], values[2], field);
        applied(history, values[2], values[3], { label: 'Description', group: 'workflow:description' });
        applied(history, values[3], values[4], field);
        applied(history, values[4], values[5], { label: 'Check enabled' });
        applied(history, values[5], values[6], field);
        applied(history, values[6], values[7], { label: 'Choice', group: '' });
        applied(history, values[7], values[8], { label: 'Choice', group: '' });
        assert.equal(history.entryCount, 8);
        for (let index = 7; index >= 0; index--) {
            assert.strictEqual(replay(history, 'undo'), values[index]);
        }
    });

    test('successful replay ends grouping, while stale replay leaves the active group intact', () => {
        const values = Array.from({ length: 5 }, (_, index) => state(index));
        const history = createHistory(values[0]);
        const action = { label: 'Type', group: 'name' };
        const first = applied(history, values[0], values[1], action);
        const snapshot = inspect(history);
        assert.equal(history.replay('undo', first.id + 100), undefined);
        assertUnchanged(history, snapshot);
        assert.equal(applied(history, values[1], values[2], action).id, first.id);
        assert.strictEqual(replay(history, 'undo'), values[0]);
        assert.strictEqual(replay(history, 'redo'), values[2]);
        const next = applied(history, values[2], values[3], action);
        assert.notEqual(next.id, first.id);
        assert.equal(history.entryCount, 2);
        assert.strictEqual(replay(history, 'undo'), values[2]);
        const branch = applied(history, values[2], values[4], action);
        assert.notEqual(branch.id, first.id);
        assert.notEqual(branch.id, next.id);
        assert.equal(history.entryCount, 2);
        assert.equal(history.peek('redo'), null);
    });

    test('an immediate semantic no-op leaves even an active group and its metadata unchanged', () => {
        const baseline = state(0);
        const second = state(1);
        const third = state(2);
        const history = createHistory(baseline);
        const action = { label: 'Type', group: 'name' };
        const first = applied(history, baseline, second, action);
        const snapshot = inspect(history);
        for (const noopAction of [{ label: 'Discrete no-op' }, { label: 'Other field', group: 'other' }]) {
            assert.deepEqual(history.record(second, state(1), noopAction), { status: 'noop', evicted: 0 });
            assertUnchanged(history, snapshot);
        }
        const last = applied(history, second, third, action);
        assert.equal(last.id, first.id);
        assert.equal(history.entryCount, 1);
    });

    test('returning a group to its semantic origin commits the edit but removes its empty undo step', () => {
        const values = [state(0), state(1), state(2), state(1), state(3)];
        const history = createHistory(values[0]);
        const action = { label: 'Type', group: 'name' };
        const earlier = applied(history, values[0], values[1], action);
        history.closeGroup();
        const typing = applied(history, values[1], values[2], action);
        assert.deepEqual(history.record(values[2], values[3], action), { status: 'applied', evicted: 0 });
        assert.equal(history.entryCount, 1);
        assert.strictEqual(history.peek('undo'), earlier);
        assert.equal(history.peek('redo'), null);
        assert.equal(history.retainedBytes, historyApi.workflowHistoryRetainedBytes(values[0], [earlier]));
        const next = applied(history, values[3], values[4], action);
        assert.notEqual(next.id, earlier.id);
        assert.notEqual(next.id, typing.id);
        assert.strictEqual(next.before, values[3]);

        const empty = createHistory(values[0]);
        applied(empty, values[0], values[1], action);
        assert.deepEqual(empty.record(values[1], state(0), action), { status: 'applied', evicted: 0 });
        assert.deepEqual(inspect(empty), { count: 0, bytes: 0, undo: null, redo: null });
    });

    test('NaN, undefined, missing properties, false, zero, Unicode, raw text, and row IDs restore exactly', () => {
        const shared = { binding: { node_id: 'constructor', output: 'json', path: '/😀' } };
        const sparse = [];
        sparse.length = 3;
        sparse[1] = undefined;
        sparse[2] = Number.NaN;
        const baseline = freezeData({
            draft: {
                name: 'Cafe\u0301 — 日本語 😀',
                max_iterations: Number.NaN,
                explicit: undefined,
                enabled: false,
                count: 0,
                negativeZero: -0,
                nullable: null,
                flow: { id: 'constructor', nodes: [{ id: 'node-α', task_id: 'catalogue-α' }] },
                shared,
                alias: shared,
                sparse,
            },
            fields: new Map([
                ['task:schema', {
                    owner: 'catalogue-α', path: 'output_contract.schema',
                    value: '  {"unfinished":\n', baseline: undefined, error: 'Unexpected end of JSON input',
                }],
                ['loop:tags', { value: ' alpha, βeta,  ', baseline: ['alpha'], error: null }],
                ['decision:draft', { value: { label: 'Still typing', condition: undefined }, baseline: {} }],
            ]),
            rows: new Map([['repeat:state', [{ id: 'row-19', name: 'review' }, { id: 'row-27', name: '' }]]]),
        });
        const afterValue = freezeData({
            draft: { name: 'Replaced', max_iterations: 4, enabled: true, count: 1, shared },
            fields: new Map(),
            rows: new Map([['repeat:state', [{ id: 'row-31', name: 'replacement' }]]]),
        });
        const history = createHistory(baseline);
        applied(history, baseline, afterValue, { label: 'Replace contract and remove Repeat row', targetId: 'constructor' });
        const restored = replay(history, 'undo');
        assert.strictEqual(restored, baseline);
        assert.ok(Number.isNaN(restored.draft.max_iterations));
        assert.equal(Object.hasOwn(restored.draft, 'explicit'), true);
        assert.equal(restored.draft.explicit, undefined);
        assert.equal(Object.hasOwn(restored.draft, 'missing'), false);
        assert.equal(restored.draft.enabled, false);
        assert.ok(Object.is(restored.draft.count, 0));
        assert.ok(Object.is(restored.draft.negativeZero, -0));
        assert.equal(restored.draft.nullable, null);
        assert.equal(restored.draft.name, 'Cafe\u0301 — 日本語 😀');
        assert.equal(Object.hasOwn(restored.draft.sparse, 0), false);
        assert.equal(Object.hasOwn(restored.draft.sparse, 1), true);
        assert.ok(Number.isNaN(restored.draft.sparse[2]));
        assert.strictEqual(restored.draft.shared, restored.draft.alias);
        assert.strictEqual(restored.draft.shared, afterValue.draft.shared);
        assert.strictEqual(restored.fields, baseline.fields);
        assert.equal(restored.fields.get('task:schema').value, '  {"unfinished":\n');
        assert.equal(restored.fields.get('task:schema').error, 'Unexpected end of JSON input');
        assert.equal(restored.fields.get('loop:tags').value, ' alpha, βeta,  ');
        assert.deepEqual(restored.rows.get('repeat:state').map((row) => row.id), ['row-19', 'row-27']);
        assert.strictEqual(replay(history, 'redo'), afterValue);
        assert.equal(afterValue.fields.size, 0);
        assert.equal(baseline.fields.size, 3);
        assert.equal(afterValue.rows.get('repeat:state')[0].id, 'row-31');
    });

    test('Map buffer content uses caller equality instead of treating every Map as an empty object', () => {
        const draft = freezeData({ name: 'Unchanged definition' });
        const initialBuffer = freezeData({ value: '{"bad":', error: 'Incomplete', baseline: undefined });
        const nextBuffer = freezeData({ value: '{"worse": ', error: 'Still incomplete', baseline: undefined });
        const baseline = freezeData({ draft, fields: new Map([['schema', initialBuffer]]) });
        const second = freezeData({ draft, fields: new Map([['schema', nextBuffer]]) });
        const equalSecond = freezeData({ draft, fields: new Map([['schema', { ...nextBuffer }]]) });
        const history = createHistory(baseline);
        applied(history, baseline, second, { label: 'Raw schema', group: 'schema' });
        const snapshot = inspect(history);
        assert.deepEqual(history.record(second, equalSecond, { label: 'Mount field' }), { status: 'noop', evicted: 0 });
        assertUnchanged(history, snapshot);
        assert.strictEqual(replay(history, 'undo').fields.get('schema'), initialBuffer);
        assert.strictEqual(replay(history, 'redo').fields.get('schema'), nextBuffer);
        applied(history, second, { draft, fields: new Map() }, { label: 'Remove buffer' });
        assert.strictEqual(replay(history, 'undo'), second);
    });

    test('caller objects are neither cloned, normalized, mutated, nor frozen by the history model', () => {
        const shared = { id: 'stable-node', unsupportedButAuthoredField: undefined };
        const baseline = { shared, list: [shared], fields: new Map([['same', shared]]) };
        const afterValue = { shared, list: [shared, shared], fields: new Map(baseline.fields) };
        const history = createHistory(baseline);
        applied(history, baseline, afterValue);
        for (const value of [baseline, afterValue, shared, baseline.list, afterValue.fields]) {
            assert.equal(Object.isFrozen(value), false);
        }
        assert.strictEqual(replay(history, 'undo'), baseline);
        assert.strictEqual(replay(history, 'redo'), afterValue);
        assert.strictEqual(afterValue.list[0], afterValue.list[1]);
        assert.strictEqual(afterValue.fields.get('same'), shared);
        assert.equal(baseline.list.length, 1);
        assert.equal(baseline.fields.size, 1);
        assert.equal(Object.hasOwn(shared, 'unsupportedButAuthoredField'), true);
    });

    test('the equality callback controls no-op detection, including primitive checkpoints', () => {
        const history = new historyApi.WorkflowAuthoringHistory(Number.NaN, Object.is);
        assert.deepEqual(history.record(Number.NaN, Number.NaN, { label: 'NaN no-op' }), { status: 'noop', evicted: 0 });
        applied(history, Number.NaN, undefined);
        applied(history, undefined, false);
        applied(history, false, 0);
        applied(history, 0, -0);
        assert.ok(Object.is(replay(history, 'undo'), 0));
        assert.equal(replay(history, 'undo'), false);
        const undefinedEntry = history.peek('undo');
        assert.equal(history.replay('undo', undefinedEntry.id), undefined);
        assert.strictEqual(history.peek('redo'), undefinedEntry, 'A successful undefined restore still moves the cursor.');
        assert.ok(Number.isNaN(replay(history, 'undo')));
        assert.equal(history.peek('undo'), null);
        assert.equal(replay(history, 'redo'), undefined);
        assert.equal(replay(history, 'redo'), false);
        assert.equal(replay(history, 'redo'), 0);
        assert.ok(Object.is(replay(history, 'redo'), -0));
    });

    test('absence, explicit undefined, NaN, false, zero, and null are distinct semantic checkpoints', () => {
        const values = [
            {}, { value: undefined }, { value: Number.NaN }, { value: false },
            { value: 0 }, { value: -0 }, { value: null }, { value: '' },
        ].map((value) => Object.freeze(value));
        const history = createHistory(values[0]);
        for (let index = 1; index < values.length; index++) applied(history, values[index - 1], values[index]);
        assert.equal(history.entryCount, values.length - 1);
        for (let index = values.length - 2; index >= 0; index--) {
            assert.strictEqual(replay(history, 'undo'), values[index]);
        }
        for (let index = 1; index < values.length; index++) {
            assert.strictEqual(replay(history, 'redo'), values[index]);
        }
    });

    test('only a committed semantic edit invalidates Redo', () => {
        const values = [state(0), state(1), state(2), state(3)];
        const history = createHistory(values[0], { maxBytes: 2_000 });
        applied(history, values[0], values[1]);
        applied(history, values[1], values[2]);
        assert.strictEqual(replay(history, 'undo'), values[1]);
        const snapshot = inspect(history);
        assert.deepEqual(history.record(values[1], state(1), { label: 'No change' }), { status: 'noop', evicted: 0 });
        assertUnchanged(history, snapshot);
        assert.deepEqual(history.record(values[1], state('x'.repeat(4_000)), { label: 'Oversized paste' }),
            { status: 'overflow', evicted: 0 });
        assertUnchanged(history, snapshot);
        assert.throws(() => history.record(values[1], { value: () => {} }, { label: 'Not data' }), TypeError);
        assertUnchanged(history, snapshot);
        assert.equal(history.replay('redo', snapshot.redo.id + 1), undefined);
        assertUnchanged(history, snapshot);
        history.closeGroup();
        assertUnchanged(history, snapshot);
        applied(history, values[1], values[3], { label: 'Branch' });
        assert.equal(history.peek('redo'), null);
        assert.equal(history.entryCount, 2);
        assert.strictEqual(replay(history, 'undo'), values[1]);
        assert.strictEqual(replay(history, 'undo'), values[0]);
    });

    test('stale replay IDs never jump over an intervening entry or a clear boundary', () => {
        const values = [state(0), state(1), state(2), state(3)];
        const history = createHistory(values[0]);
        const first = applied(history, values[0], values[1]);
        const second = applied(history, values[1], values[2]);
        const snapshot = inspect(history);
        assert.equal(history.replay('undo', first.id), undefined);
        assertUnchanged(history, snapshot);
        assert.strictEqual(history.replay('undo', second.id), values[1]);
        const undone = inspect(history);
        assert.equal(history.replay('undo', second.id), undefined);
        assert.equal(history.replay('redo', first.id), undefined);
        assertUnchanged(history, undone);
        history.clear();
        const replacement = applied(history, values[2], values[3]);
        assert.ok(replacement.id > second.id, 'IDs must not be reused by clear().');
        const reset = inspect(history);
        assert.equal(history.replay('undo', second.id), undefined);
        assertUnchanged(history, reset);
    });

    test('the real 100-entry limit covers Undo and Redo together and evicts only the 101st oldest action', () => {
        const values = Array.from({ length: 102 }, (_, index) => state(index));
        const history = createHistory(values[0]);
        const ids = [];
        for (let index = 1; index <= 100; index++) {
            ids.push(applied(history, values[index - 1], values[index]).id);
        }
        assert.equal(history.entryCount, 100);
        const bytes = history.retainedBytes;
        for (let index = 99; index >= 50; index--) {
            assert.strictEqual(replay(history, 'undo'), values[index]);
            assert.equal(history.entryCount, 100);
            assert.equal(history.retainedBytes, bytes);
        }
        for (let index = 51; index <= 100; index++) {
            assert.strictEqual(replay(history, 'redo'), values[index]);
            assert.equal(history.entryCount, 100);
            assert.equal(history.retainedBytes, bytes);
        }
        applied(history, values[100], values[101], { label: 'edit' }, 1);
        assert.equal(history.entryCount, 100);
        const evictedBytes = history.retainedBytes;
        const retainedIds = [];
        for (let index = 100; index >= 1; index--) {
            retainedIds.push(history.peek('undo').id);
            assert.strictEqual(replay(history, 'undo'), values[index]);
            assert.equal(history.retainedBytes, evictedBytes);
        }
        assert.equal(history.peek('undo'), null);
        assert.equal(retainedIds.includes(ids[0]), false);
        assert.equal(retainedIds.includes(ids[1]), true);
        for (let index = 2; index <= 101; index++) assert.strictEqual(replay(history, 'redo'), values[index]);
        assert.equal(history.retainedBytes, evictedBytes);
    });

    test('accounting charges UTF-16 strings, slots, keys, Map entries, and shared objects deterministically', () => {
        const baseline = {};
        const measured = (afterValue, action) => historyApi.workflowHistoryRetainedBytes(
            baseline, [entry(1, baseline, afterValue, action)],
        );
        // 64 list + 8 slot + 238 entry record + 130 action record ("edit").
        const metadata = 440;
        assert.equal(measured({}), metadata + 64);
        assert.equal(measured({ x: '😀' }), metadata + 64 + 18 + 16 + 20);
        assert.equal(measured([1, undefined]), metadata + 64 + 16 + 8 + 4);
        const sparse = Array(2);
        sparse[1] = undefined;
        assert.equal(measured(sparse), metadata + 64 + 16 + 4);
        assert.equal(measured(new Map([['a', 1], ['b', undefined]])), metadata + 64 + 96 + 18 + 8 + 18 + 4);
        const shared = { n: 0 };
        assert.equal(measured({ a: shared, b: shared }), metadata + 132 + 106);
        assert.equal(measured({ a: { n: 0 }, b: { n: 0 } }), metadata + 132 + 212);
        assert.equal(measured(new Map([[shared, shared], ['ref', shared]])), metadata + 64 + 96 + 22 + 106);
        assert.equal(measured({}, { label: 'edit', group: 'g', targetId: '😀' }), metadata + 64 + 60 + 68);
        const nullPrototype = Object.create(null);
        Object.defineProperty(nullPrototype, 'x', { value: undefined, enumerable: false });
        assert.equal(measured(nullPrototype), metadata + 64 + 18 + 16 + 4);
        const decorated = [0];
        decorated.extra = false;
        assert.equal(measured(decorated), metadata + 64 + 8 + 8 + 26 + 16 + 4);
        const decoratedMap = new Map();
        decoratedMap.extra = null;
        assert.equal(measured(decoratedMap), metadata + 64 + 26 + 16 + 4);
    });

    test('the exact 32-MiB boundary is accepted and the next UTF-16 code unit overflows atomically', () => {
        const baseline = freezeData({ text: '' });
        const action = { label: 'edit' };
        const overhead = historyApi.workflowHistoryRetainedBytes(baseline, [
            entry(1, baseline, { text: '' }, action),
        ]);
        assert.equal(overhead, 560, 'Independent fixed-cost arithmetic must agree with the production accountant.');
        const length = (33_554_432 - overhead) / 2;
        assert.equal(Number.isInteger(length), true);
        const exact = Object.freeze({ text: 'x'.repeat(length) });
        const history = createHistory(baseline);
        applied(history, baseline, exact, action);
        assert.equal(history.retainedBytes, 33_554_432);
        assert.strictEqual(replay(history, 'undo'), baseline);
        assert.equal(history.retainedBytes, 33_554_432);
        assert.strictEqual(replay(history, 'redo'), exact);
        assert.equal(history.retainedBytes, 33_554_432);

        const below = createHistory(baseline);
        applied(below, baseline, { text: 'x'.repeat(length - 1) }, action);
        assert.equal(below.retainedBytes, 33_554_430);
        const over = createHistory(baseline);
        const tooLarge = { text: 'x'.repeat(length + 1) };
        assert.equal(historyApi.workflowHistoryRetainedBytes(baseline, [entry(1, baseline, tooLarge)]), 33_554_434);
        assert.deepEqual(over.record(baseline, tooLarge, action), { status: 'overflow', evicted: 0 });
        assert.deepEqual(inspect(over), { count: 0, bytes: 0, undo: null, redo: null });
    });

    test('a coalesced group at exactly 32 MiB survives overflow and can still shrink within the same visit', () => {
        const baseline = freezeData({ text: '' });
        const action = { label: 'edit', group: 'schema' };
        const overhead = historyApi.workflowHistoryRetainedBytes(baseline, [
            entry(1, baseline, { text: '' }, action),
        ]);
        assert.equal(overhead, 630);
        const length = (33_554_432 - overhead) / 2;
        const exact = Object.freeze({ text: 'x'.repeat(length) });
        const history = createHistory(baseline);
        const first = applied(history, baseline, exact, action);
        assert.equal(history.retainedBytes, 33_554_432);
        const snapshot = inspect(history);
        assert.deepEqual(history.record(exact, { text: 'x'.repeat(length + 1) }, action),
            { status: 'overflow', evicted: 0 });
        assertUnchanged(history, snapshot);
        const smaller = Object.freeze({ text: 'x'.repeat(length - 1) });
        assert.equal(applied(history, exact, smaller, action).id, first.id);
        assert.equal(history.entryCount, 1);
        assert.equal(history.retainedBytes, 33_554_430);
        assert.strictEqual(replay(history, 'undo'), baseline);
        assert.strictEqual(replay(history, 'redo'), smaller);
    });

    test('an oversized open coalesced action preserves its ID, grouping, and complete previous checkpoint', () => {
        const baseline = state('');
        const second = state('a');
        const third = state('ab');
        const history = createHistory(baseline, { maxBytes: 2_048 });
        const action = { label: 'Type schema', group: 'schema', targetId: 'task-1' };
        const first = applied(history, baseline, second, action);
        const snapshot = inspect(history);
        assert.deepEqual(history.record(second, state('x'.repeat(2_000)), action), { status: 'overflow', evicted: 0 });
        assertUnchanged(history, snapshot);
        assert.deepEqual(history.record(second, state('y'.repeat(2_000)), { label: 'Discrete paste' }),
            { status: 'overflow', evicted: 0 });
        assertUnchanged(history, snapshot);
        const last = applied(history, second, third, action);
        assert.equal(last.id, first.id);
        assert.equal(history.entryCount, 1);
        assert.strictEqual(last.before, baseline);
        assert.strictEqual(last.after, third);
        assert.strictEqual(replay(history, 'undo'), baseline);
        assert.strictEqual(replay(history, 'redo'), third);
        const next = applied(history, third, state('abc'));
        assert.equal(next.id, first.id + 1, 'Overflow must not consume an entry ID.');
    });

    test('the whole coalesced group, not only its latest small increment, must fit the byte limit', () => {
        const baseline = freezeData({ blob: null, value: 0 });
        const blob = freezeData({ text: 'x'.repeat(800) });
        const second = freezeData({ blob, value: 1 });
        const third = freezeData({ blob, value: 2, extra: 'one more field' });
        const action = { label: 'Type', group: 'field' };
        const budget = historyApi.workflowHistoryRetainedBytes(baseline, [entry(1, baseline, second, action)]);
        assert.ok(historyApi.workflowHistoryRetainedBytes(baseline, [entry(1, second, third, action)]) < budget);
        assert.ok(historyApi.workflowHistoryRetainedBytes(baseline, [entry(1, baseline, third, action)]) > budget);
        const history = createHistory(baseline, { maxBytes: budget });
        applied(history, baseline, second, action);
        const snapshot = inspect(history);
        assert.deepEqual(history.record(second, third, action), { status: 'overflow', evicted: 0 });
        assertUnchanged(history, snapshot);
        history.closeGroup();
        const committed = applied(history, second, third, action, 1);
        assert.strictEqual(committed.before, second);
        assert.strictEqual(committed.after, third);
    });

    test('byte pressure evicts the minimum whole oldest entries, preserving exact Undo and Redo', () => {
        const values = ['', 'a', 'b', 'c'].map((text) => Object.freeze({ text: text.repeat(120) }));
        const entries = values.slice(1).map((value, index) => entry(index + 1, values[index], value));
        const budget = historyApi.workflowHistoryRetainedBytes(values[0], entries.slice(1));
        const history = createHistory(values[0], { maxBytes: budget });
        applied(history, values[0], values[1]);
        applied(history, values[1], values[2]);
        const last = applied(history, values[2], values[3], { label: 'edit' }, 1);
        assert.equal(history.entryCount, 2);
        assert.equal(history.retainedBytes, budget);
        assert.strictEqual(last.after, values[3]);
        for (let cycle = 0; cycle < 20; cycle++) {
            assert.strictEqual(replay(history, 'undo'), values[2]);
            assert.strictEqual(replay(history, 'undo'), values[1]);
            assert.equal(history.peek('undo'), null);
            assert.equal(history.retainedBytes, budget);
            assert.strictEqual(replay(history, 'redo'), values[2]);
            assert.strictEqual(replay(history, 'redo'), values[3]);
            assert.equal(history.retainedBytes, budget);
        }
    });

    test('one accepted action may evict several old actions, without silently dropping the new one', () => {
        const values = Array.from({ length: 8 }, (_, index) => state(index));
        const initialEntries = values.slice(1).map((value, index) => entry(index + 1, values[index], value));
        const budget = historyApi.workflowHistoryRetainedBytes(values[0], initialEntries);
        const history = createHistory(values[0], { maxBytes: budget });
        for (let index = 1; index < values.length; index++) applied(history, values[index - 1], values[index]);
        const large = state('x'.repeat(Math.floor((budget - 1_000) / 2)));
        const proposed = entry(8, values[7], large);
        const candidates = [...initialEntries, proposed];
        let expectedEvictions = 0;
        while (historyApi.workflowHistoryRetainedBytes(values[0], candidates.slice(expectedEvictions)) > budget) {
            expectedEvictions++;
        }
        assert.ok(expectedEvictions > 1 && expectedEvictions < candidates.length);
        const latest = applied(history, values[7], large, { label: 'edit' }, expectedEvictions);
        assert.strictEqual(latest.after, large);
        assert.equal(history.entryCount, candidates.length - expectedEvictions);
        assert.equal(history.retainedBytes,
            historyApi.workflowHistoryRetainedBytes(values[0], candidates.slice(expectedEvictions)));
        assert.strictEqual(replay(history, 'undo'), values[7]);
        assert.strictEqual(replay(history, 'redo'), large);
    });

    test('branch commits drop Redo before sizing, and discarded Redo actions are not eviction notices', () => {
        const values = Array.from({ length: 8 }, (_, index) => state(index));
        const history = createHistory(values[0], { maxEntries: 3 });
        for (let index = 1; index <= 3; index++) applied(history, values[index - 1], values[index]);
        assert.strictEqual(replay(history, 'undo'), values[2]);
        assert.strictEqual(replay(history, 'undo'), values[1]);
        const formerRedoId = history.peek('redo').id;
        applied(history, values[1], values[4]);
        assert.equal(history.entryCount, 2);
        assert.equal(history.peek('redo'), null);
        applied(history, values[4], values[5]);
        applied(history, values[5], values[6], { label: 'edit' }, 1);
        assert.equal(history.entryCount, 3);
        assert.equal(history.replay('redo', formerRedoId), undefined);
        assert.strictEqual(replay(history, 'undo'), values[5]);
        assert.strictEqual(replay(history, 'undo'), values[4]);
        assert.strictEqual(replay(history, 'undo'), values[1]);
        assert.equal(history.peek('undo'), null);
    });

    test('an individually oversized edit does not evict any existing entries to make room', () => {
        const values = [state(0), state(1), state(2)];
        const history = createHistory(values[0], { maxEntries: 2, maxBytes: 2_000 });
        applied(history, values[0], values[1], { label: 'Type', group: 'name' });
        history.closeGroup();
        applied(history, values[1], values[2], { label: 'Type', group: 'name' });
        const snapshot = inspect(history);
        assert.deepEqual(history.record(values[2], state('x'.repeat(8_000)), { label: 'Paste' }),
            { status: 'overflow', evicted: 0 });
        assertUnchanged(history, snapshot);
        assert.equal(applied(history, values[2], state(3), { label: 'Type', group: 'name' }).id, snapshot.undo.id);
        assert.equal(history.entryCount, 2);
    });

    test('large action labels and focus/group metadata are budgeted, not treated as free strings', () => {
        const baseline = state(0);
        for (const field of ['label', 'group', 'targetId']) {
            const history = createHistory(baseline, { maxBytes: 1_024 });
            assert.deepEqual(history.record(baseline, state(1), { label: 'edit', [field]: 'x'.repeat(1_024) }),
                { status: 'overflow', evicted: 0 });
            assert.equal(history.entryCount, 0);
            assert.equal(history.retainedBytes, 0);
        }
    });

    test('small edits to a very large opening immutable draft do not charge unchanged shared subgraphs', () => {
        const shared = freezeData({
            schema: 'x'.repeat(historyApi.WORKFLOW_HISTORY_MAX_BYTES),
            task: { id: 'task-1', inputs: [{ source: { node_id: 'constructor', output: 'json' } }] },
        });
        const baseline = freezeData({ shared, name: '0' });
        const history = createHistory(baseline);
        let current = baseline;
        for (let index = 1; index <= 100; index++) {
            const next = freezeData({ shared, name: String(index) });
            applied(history, current, next, { label: 'Rename workflow' });
            current = next;
        }
        assert.equal(history.entryCount, 100);
        assert.ok(history.retainedBytes < 100_000);
        for (let index = 0; index < 100; index++) assert.strictEqual(replay(history, 'undo').shared, shared);
        assert.equal(history.peek('undo'), null);
        assert.strictEqual(replay(history, 'redo').shared, shared);
    });

    test('all reachable live states, not just the current one, determine large-addition retention', () => {
        const baseline = state('');
        const introduced = state('x'.repeat(600));
        const afterValue = state('y');
        const first = entry(1, baseline, introduced);
        const second = entry(2, introduced, afterValue);
        const firstBytes = historyApi.workflowHistoryRetainedBytes(baseline, [first]);
        const bothBytes = historyApi.workflowHistoryRetainedBytes(baseline, [first, second]);
        assert.ok(firstBytes > 1_200, 'The newly live large value is not a free live-state exemption.');
        assert.ok(bothBytes > firstBytes);
        const history = createHistory(baseline, { maxBytes: bothBytes });
        applied(history, baseline, introduced);
        applied(history, introduced, afterValue);
        for (let cycle = 0; cycle < 10; cycle++) {
            assert.strictEqual(replay(history, 'undo'), introduced);
            assert.equal(history.retainedBytes, bothBytes);
            assert.strictEqual(replay(history, 'undo'), baseline);
            assert.equal(history.retainedBytes, bothBytes);
            assert.strictEqual(replay(history, 'redo'), introduced);
            assert.strictEqual(replay(history, 'redo'), afterValue);
            assert.equal(history.retainedBytes, bothBytes);
        }
    });

    test('a shared post-clear live graph is credited, but a large deletion cannot exploit that credit', () => {
        const baseline = state(0);
        const history = createHistory(baseline);
        applied(history, baseline, state(1));
        history.clear();
        const shared = freezeData({ text: 'x'.repeat(historyApi.WORKFLOW_HISTORY_MAX_BYTES) });
        const current = freezeData({ shared, value: 1 });
        const next = freezeData({ shared, value: 2 });
        const action = { label: 'Small field edit', group: 'name' };
        applied(history, current, next, action);
        assert.ok(history.retainedBytes < 1_000);
        const snapshot = inspect(history);
        const removed = state(3);
        assert.ok(historyApi.workflowHistoryRetainedBytes(baseline, [entry(2, next, removed)])
            > historyApi.WORKFLOW_HISTORY_MAX_BYTES);
        assert.deepEqual(history.record(next, removed, { label: 'Delete large authored data' }),
            { status: 'overflow', evicted: 0 });
        assertUnchanged(history, snapshot);
        const small = freezeData({ shared, value: 3 });
        assert.equal(applied(history, next, small, action).id, snapshot.undo.id);
        assert.strictEqual(replay(history, 'undo'), current);
        assert.strictEqual(replay(history, 'redo'), small);
        history.clear();
        assert.equal(history.retainedBytes, 0);
        assert.equal(history.entryCount, 0);
    });

    test('clear drops both directions and groups without installing a new permanent baseline', () => {
        const baseline = state(0);
        const second = state(1);
        const third = state(2);
        const history = createHistory(baseline, { maxBytes: 2_048 });
        const action = { label: 'Type', group: 'name' };
        const first = applied(history, baseline, second, action);
        history.closeGroup();
        applied(history, second, third, action);
        replay(history, 'undo');
        history.clear();
        assert.deepEqual(inspect(history), { count: 0, bytes: 0, undo: null, redo: null });
        const large = freezeData({ payload: { text: 'x'.repeat(4_096) } });
        assert.deepEqual(history.record(large, state(3), { label: 'Delete after reset' }), { status: 'overflow', evicted: 0 });
        assert.equal(history.entryCount, 0);
        const next = applied(history, third, state(4), action);
        assert.ok(next.id > first.id);
        assert.strictEqual(next.before, third);
        history.clear();
        history.clear();
        assert.equal(history.retainedBytes, 0);
    });

    test('repeated eviction and replay have stable accounted bytes and no accumulating hidden history', () => {
        const baseline = state(-1);
        const history = createHistory(baseline, { maxEntries: 5 });
        let current = baseline;
        let steadyBytes;
        for (let index = 0; index < 250; index++) {
            const next = state(index);
            applied(history, current, next, { label: 'edit' }, index >= 5 ? 1 : 0);
            current = next;
            if (index < 5) continue;
            if (steadyBytes === undefined) steadyBytes = history.retainedBytes;
            assert.equal(history.retainedBytes, steadyBytes);
            const beforeReplay = inspect(history);
            const previous = replay(history, 'undo');
            assert.equal(previous.value, index - 1);
            assert.strictEqual(replay(history, 'redo'), current);
            assertUnchanged(history, beforeReplay);
        }
        history.clear();
        assert.equal(history.retainedBytes, 0);
    });

    test('data-only validation rejects unsupported values without getters, mutation, or lost grouping', () => {
        class NonDataCheckpoint {}
        class NonDataMap extends Map {}
        let getterCalls = 0;
        const getter = {};
        Object.defineProperty(getter, 'value', { get() { getterCalls++; return 1; } });
        const symbolProperty = { [Symbol('private')]: 1 };
        const unsupported = [
            () => {}, Symbol('value'), 1n, new Date(0), /pattern/, new Set([1]),
            new WeakMap(), Promise.resolve(1), new Uint8Array(1), new NonDataCheckpoint(),
            new NonDataMap(), getter, symbolProperty, { child: { callback() {} } },
        ];
        const baseline = state(0);
        const second = state(1);
        const history = createHistory(baseline);
        const action = { label: 'Type', group: 'field' };
        const first = applied(history, baseline, second, action);
        const snapshot = inspect(history);
        for (const value of unsupported) {
            assert.throws(() => createHistory(value), TypeError);
            assert.throws(() => history.record(second, value, action), TypeError);
            assertUnchanged(history, snapshot);
        }
        assert.equal(getterCalls, 0);
        assert.equal(applied(history, second, state(2), action).id, first.id);
        assert.equal(history.entryCount, 1);
    });

    test('cycles in records, arrays, Map keys, and Map values are explicitly rejected; shared DAGs are valid', () => {
        const objectCycle = {};
        objectCycle.self = objectCycle;
        const arrayCycle = [];
        arrayCycle.push(arrayCycle);
        const mapKeyCycle = new Map();
        mapKeyCycle.set(mapKeyCycle, 1);
        const mapValueCycle = new Map();
        mapValueCycle.set('self', mapValueCycle);
        const baseline = state(0);
        const history = createHistory(baseline);
        for (const value of [objectCycle, arrayCycle, mapKeyCycle, mapValueCycle]) {
            assert.throws(() => createHistory(value), /must not contain cycles/);
            assert.throws(() => history.record(baseline, value, { label: 'Cycle' }), /must not contain cycles/);
            assert.equal(history.entryCount, 0);
        }
        const shared = freezeData({ value: 1 });
        const graph = freezeData({ a: shared, b: [shared], c: new Map([[shared, shared]]) });
        const recorded = applied(history, baseline, graph);
        assert.equal(history.replay('redo', recorded.id), undefined);
        assert.strictEqual(replay(history, 'undo'), baseline);
        assert.strictEqual(replay(history, 'redo'), graph);
    });

    test('deep acyclic data is validated and counted without recursive JavaScript stack growth', () => {
        const baseline = {};
        let deep = { leaf: true };
        for (let index = 0; index < 12_000; index++) deep = { child: deep };
        const history = createHistory(baseline);
        applied(history, baseline, deep);
        assert.ok(history.retainedBytes > 1_000_000);
        assert.ok(history.retainedBytes < historyApi.WORKFLOW_HISTORY_MAX_BYTES);
        assert.strictEqual(replay(history, 'undo'), baseline);
        assert.strictEqual(replay(history, 'redo'), deep);
    });

    test('invalid metadata, limits, and directions fail explicitly without silently choosing defaults', () => {
        const baseline = state(0);
        for (const name of ['maxEntries', 'maxBytes']) {
            for (const value of [-1, 1.5, Infinity, Number.NaN, '100', null]) {
                assert.throws(() => createHistory(baseline, { [name]: value }), RangeError);
            }
        }
        for (const limits of [{ maxEntries: 0 }, { maxBytes: 0 }]) {
            const history = createHistory(baseline, limits);
            assert.deepEqual(history.record(baseline, state(1), { label: 'edit' }), { status: 'overflow', evicted: 0 });
            assert.equal(history.entryCount, 0);
        }
        const history = createHistory(baseline);
        let calls = 0;
        const accessor = { get label() { calls++; return 'Not evaluated'; } };
        for (const action of [{}, { label: 1 }, { label: 'edit', group: false }, { label: 'edit', targetId: {} }, accessor]) {
            assert.throws(() => history.record(baseline, state(1), action), TypeError);
            assert.equal(history.entryCount, 0);
        }
        assert.equal(calls, 0);
        assert.throws(() => history.peek('backward'), TypeError);
        assert.throws(() => history.replay('forward', 1), TypeError);
    });

    test('weak caches release evicted, coalesced, abandoned Redo, overflow, and cleared checkpoints', () => {
        const result = spawnSync(process.execPath, ['--expose-gc', __filename, '--history-gc-probe'], {
            cwd: root,
            encoding: 'utf8',
            timeout: 30_000,
            maxBuffer: 1024 * 1024,
        });
        assert.equal(result.error, undefined, result.error?.stack);
        assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
        assert.match(result.stdout, /History checkpoint release verified/);
    });
}

async function verifyCheckpointRelease() {
    await loadProductionModule();
    assert.equal(typeof global.gc, 'function');
    const baseline = state(0);
    const history = createHistory(baseline, { maxEntries: 1, maxBytes: 4_096 });
    const stage = () => {
        const first = { value: 1, unique: { marker: 'evicted child' } };
        const second = state(2);
        const third = state(3);
        applied(history, baseline, first);
        applied(history, first, second, { label: 'edit' }, 1);
        applied(history, second, third, { label: 'edit' }, 1);
        const typed = state(4);
        const latest = state(5);
        const action = { label: 'Type', group: 'field' };
        applied(history, third, typed, action, 1);
        applied(history, typed, latest, action);
        replay(history, 'undo');
        const branch = state(6);
        applied(history, third, branch);
        const oversized = { value: 'x'.repeat(8_192), unique: { marker: 'overflow child' } };
        assert.deepEqual(history.record(branch, oversized, { label: 'Paste' }), { status: 'overflow', evicted: 0 });
        const references = [
            ['evicted', new WeakRef(first)], ['evicted descendant', new WeakRef(first.unique)],
            ['coalesced', new WeakRef(typed)], ['abandoned Redo', new WeakRef(latest)],
            ['overflow', new WeakRef(oversized)], ['overflow descendant', new WeakRef(oversized.unique)],
        ];
        return { references, cleared: [['cleared', new WeakRef(branch)], ['cleared before', new WeakRef(third)]] };
    };
    const assertReleased = async (references) => {
        for (let attempt = 0; attempt < 20; attempt++) {
            await new Promise((resolve) => setImmediate(resolve));
            global.gc();
            if (references.every(([, reference]) => reference.deref() === undefined)) return;
        }
        assert.fail(`Retained checkpoints: ${references.filter(([, reference]) => reference.deref() !== undefined)
            .map(([name]) => name).join(', ')}`);
    };
    const { references, cleared } = stage();
    await assertReleased(references);
    assert.equal(history.entryCount, 1, 'Evicted states must be collectible while later history remains live.');
    history.clear();
    await assertReleased(cleared);
    const afterReset = () => {
        const shared = { text: 'x'.repeat(8_192) };
        const current = { shared, value: 1 };
        const next = { shared, value: 2 };
        applied(history, current, next);
        const resetReferences = [
            ['reset before', new WeakRef(current)], ['reset after', new WeakRef(next)],
            ['reset shared data', new WeakRef(shared)],
        ];
        history.clear();
        return resetReferences;
    };
    await assertReleased(afterReset());
    assert.equal(history.retainedBytes, 0);
    process.stdout.write('History checkpoint release verified.\n');
}

if (process.argv.includes('--history-gc-probe')) {
    verifyCheckpointRelease().catch((error) => {
        process.stderr.write(`${error.stack || error}\n`);
        process.exitCode = 1;
    });
} else {
    before(loadProductionModule);
    registerTests();
}
