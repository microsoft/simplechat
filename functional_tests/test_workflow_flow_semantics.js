// test_workflow_flow_semantics.js
/*
Functional tests for read-only Flow semantic presentation.
Version: 0.261.121
Implemented in: 0.261.121

Executes the real TypeScript helpers without a browser or backend.
*/

const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { before, test } = require('node:test');

const root = path.resolve(__dirname, '..');
let flow;
let inspection;

before(async () => {
    // Register the existing TypeScript loader before importing production ES modules.
    await import(pathToFileURL(path.join(__dirname, 'test_support', 'tsResolve.mjs')));
    const moduleUrl = (name) => pathToFileURL(path.join(root, 'application', 'v2_ui', 'src', 'lib', `${name}.ts`));
    flow = await import(moduleUrl('workflowFlow'));
    inspection = await import(moduleUrl('workflowInspection'));
});

function node(id, kind, loopIds = []) {
    return {
        id, kind, label: id, parent_id: id === 'root' ? null : 'root', region_id: 'root',
        order: 0, loop_ids: loopIds, child_region_ids: [], inputs_count: 0, outputs_count: 0,
        has_condition: false,
    };
}

test('only real nodes and the root expose execution lookup, not grouping regions', () => {
    assert.equal(inspection.inspectionNodeHasExecution(node('root', 'region'), 'root'), true);
    for (const id of ['then', 'else', 'body', 'constructor']) {
        assert.equal(inspection.inspectionNodeHasExecution(node(id, 'region'), 'root'), false);
    }
    for (const kind of ['task', 'if', 'join', 'route', 'for_each', 'repeat_until', 'collect']) {
        assert.equal(inspection.inspectionNodeHasExecution(node('operation', kind), 'root'), true);
    }
});

test('mixed overlay and gate paths compare values, not JSON property insertion order', () => {
    const selected = [
        { loop_id: 'outer', item_id: 'frozen-item', index: 4999 },
        { loop_id: 'repeat', iteration: 1000 },
        { loop_id: 'inner', item_id: 'nested-item', index: 0 },
    ];
    const reordered = [
        { index: 4999, item_id: 'frozen-item', loop_id: 'outer' },
        { iteration: 1000, loop_id: 'repeat' },
        { item_id: 'nested-item', index: 0, loop_id: 'inner' },
    ];
    const body = node('work', 'task', ['outer', 'repeat', 'inner']);
    assert.equal(inspection.inspectionNodeMatchesPath(body, selected, reordered), true);
    assert.equal(inspection.inspectionNodeMatchesPath(body, selected, [
        { ...reordered[0], item_id: 'another-item' }, ...reordered.slice(1),
    ]), false);
    assert.equal(inspection.inspectionNodeMatchesPath(body, selected, [
        reordered[0], { ...reordered[1], iteration: 999 }, reordered[2],
    ]), false);
    assert.equal(inspection.inspectionNodeMatchesPath(body, [], reordered), false);
    assert.equal(inspection.inspectionNodeMatchesPath(body, selected), false);
    assert.equal(inspection.inspectionNodeMatchesPath(node('outside', 'task'), selected, []), true);
    assert.equal(inspection.inspectionNodeMatchesPath(node('outer-work', 'task', ['outer']), selected, reordered.slice(0, 1)), true);
});

test('condition summaries preserve nested AND/OR grouping without changing predicates', () => {
    const comparison = (field, literal) => ({
        op: 'eq', left: { input: 'review', path: `/${field}` }, right: { literal },
    });
    const condition = {
        op: 'all',
        conditions: [
            comparison('ready', true),
            { op: 'any', conditions: [comparison('score', 0), comparison('reason', null)] },
        ],
    };
    const original = structuredClone(condition);
    assert.equal(flow.isFlowPredicate(condition), true);
    assert.equal(flow.predicateSummary(condition),
        'review.ready equals true AND (review.score equals 0 OR review.reason equals null)');
    assert.equal(flow.predicateSummary({ op: 'not', condition }),
        'NOT (review.ready equals true AND (review.score equals 0 OR review.reason equals null))');
    assert.deepEqual(condition, original);
});
