// test_v2_workflow_flow_node_reuse_logic.mjs
// Version: 0.261.207
// Implemented in: 0.261.207
// Executes the node-reuse rule the workflow Flow canvas uses to keep React Flow node objects
// stable across renders that do not change the diagram (#1573).
//
// React Flow discards the measured handle positions of any node object it has not seen before,
// and every edge to that node disappears until it is measured again. The canvas therefore keeps
// the previous object for each node a rebuild did not change, and the previous array when no
// node changed. Run with: node --test functional_tests/test_v2_workflow_flow_node_reuse_logic.mjs

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

// The repository resolver must be registered before TypeScript imports load.
const { reuseUnchangedFlowNodes, sameFlowNode } = await import(
    '../application/v2_ui/src/lib/workflowFlowNodeReuse.ts'
);

const record = { id: 'evaluate', kind: 'task', label: 'Evaluate', child_region_ids: [] };
const onSelect = () => {};
const registerButton = () => {};

function flowNode(id, fields = {}, data = {}) {
    return {
        id, type: 'workflow', parentId: undefined, position: { x: 10, y: 20 },
        width: 280, height: 96, style: { width: 280, height: 96 },
        draggable: true, extent: undefined,
        data: { record, chosen: false, status: 'Definition', onSelect, registerButton, ...data },
        ...fields,
    };
}

test('a node rebuilt with the same values equals the previous node', () => {
    assert.equal(sameFlowNode(flowNode('evaluate'), flowNode('evaluate')), true);
    const node = flowNode('evaluate');
    assert.equal(sameFlowNode(node, node), true);
});

test('a changed value, field or key makes the node different', () => {
    const previous = flowNode('evaluate');
    assert.equal(sameFlowNode(previous, flowNode('evaluate', {}, { chosen: true })), false);
    assert.equal(sameFlowNode(previous, flowNode('evaluate', { position: { x: 11, y: 20 } })), false);
    assert.equal(sameFlowNode(previous, flowNode('evaluate', { style: { width: 300, height: 96 } })), false);
    assert.equal(sameFlowNode(previous, flowNode('evaluate', { draggable: false })), false);
    assert.equal(sameFlowNode(previous, flowNode('evaluate', { hidden: true })), false);
    const { draggable, ...withoutDraggable } = previous;
    assert.equal(draggable, true);
    assert.equal(sameFlowNode(previous, withoutDraggable), false);
    assert.equal(sameFlowNode(withoutDraggable, previous), false);
});

test('values below the first level and callbacks are compared by identity', () => {
    const previous = flowNode('evaluate');
    assert.equal(sameFlowNode(previous, flowNode('evaluate', {}, { record: { ...record } })), false);
    assert.equal(sameFlowNode(previous, flowNode('evaluate', {}, { onSelect: () => {} })), false);
    assert.equal(sameFlowNode(flowNode('evaluate', {}, { tags: ['a'] }), flowNode('evaluate', {}, { tags: ['a'] })), false);
    const tags = ['a'];
    assert.equal(sameFlowNode(flowNode('evaluate', {}, { tags }), flowNode('evaluate', {}, { tags })), true);
});

test('ignored fields never make two nodes different', () => {
    const previous = flowNode('evaluate');
    const measured = flowNode('evaluate', { measured: { width: 280, height: 96 } });
    assert.equal(sameFlowNode(previous, measured), false);
    assert.equal(sameFlowNode(previous, measured, ['measured']), true);
    assert.equal(sameFlowNode(measured, previous, ['measured']), true);
    assert.equal(sameFlowNode(measured, flowNode('evaluate', { measured: { width: 300, height: 96 } }), ['measured']), true);
    assert.equal(sameFlowNode(previous, flowNode('evaluate', { measured: { width: 280, height: 96 } }, { chosen: true }),
        ['measured']), false);
});

test('an unchanged rebuild returns the previous array itself', () => {
    const previous = [flowNode('root'), flowNode('evaluate'), flowNode('finish')];
    const next = [flowNode('root'), flowNode('evaluate'), flowNode('finish')];
    assert.equal(reuseUnchangedFlowNodes(previous, next), previous);
    assert.equal(reuseUnchangedFlowNodes([], []).length, 0);
});

test('only changed nodes receive new objects', () => {
    const previous = [flowNode('root'), flowNode('evaluate'), flowNode('finish')];
    const next = [flowNode('root'), flowNode('evaluate', {}, { chosen: true }), flowNode('finish')];
    const nodes = reuseUnchangedFlowNodes(previous, next);
    assert.notEqual(nodes, previous);
    assert.equal(nodes[0], previous[0]);
    assert.equal(nodes[1], next[1]);
    assert.equal(nodes[2], previous[2]);
});

test('a reorder keeps every object but returns a new array', () => {
    const previous = [flowNode('root'), flowNode('evaluate'), flowNode('finish')];
    const nodes = reuseUnchangedFlowNodes(previous, [flowNode('finish'), flowNode('root'), flowNode('evaluate')]);
    assert.notEqual(nodes, previous);
    assert.deepEqual(nodes.map((node) => node.id), ['finish', 'root', 'evaluate']);
    assert.equal(nodes[0], previous[2]);
    assert.equal(nodes[1], previous[0]);
    assert.equal(nodes[2], previous[1]);
});

test('added nodes are new and removed nodes are dropped', () => {
    const previous = [flowNode('root'), flowNode('evaluate'), flowNode('finish')];
    const added = flowNode('review');
    const grown = reuseUnchangedFlowNodes(previous, [flowNode('root'), flowNode('evaluate'), added, flowNode('finish')]);
    assert.deepEqual(grown.map((node) => node.id), ['root', 'evaluate', 'review', 'finish']);
    assert.equal(grown[0], previous[0]);
    assert.equal(grown[2], added);
    assert.equal(grown[3], previous[2]);
    const shrunk = reuseUnchangedFlowNodes(previous, [flowNode('root'), flowNode('finish')]);
    assert.notEqual(shrunk, previous);
    assert.deepEqual(shrunk, [previous[0], previous[2]]);
    const prefix = reuseUnchangedFlowNodes(previous, [flowNode('root'), flowNode('evaluate')]);
    assert.notEqual(prefix, previous);
    assert.deepEqual(prefix, [previous[0], previous[1]]);
});

test('a newly measured node still reuses the previous object', () => {
    const previous = [flowNode('root'), flowNode('evaluate')];
    const next = [flowNode('root', { measured: { width: 280, height: 96 } }), flowNode('evaluate')];
    assert.equal(reuseUnchangedFlowNodes(previous, next, ['measured']), previous);
    assert.notEqual(reuseUnchangedFlowNodes(previous, next), previous);
});

test('the inputs are never modified', () => {
    const previous = [flowNode('root'), flowNode('evaluate')];
    const next = [flowNode('evaluate', {}, { chosen: true }), flowNode('root')];
    const before = [previous.slice(), next.slice()];
    reuseUnchangedFlowNodes(previous, next);
    assert.deepEqual([previous, next], before);
    assert.equal(previous[0], before[0][0]);
    assert.equal(next[0], before[1][0]);
});
