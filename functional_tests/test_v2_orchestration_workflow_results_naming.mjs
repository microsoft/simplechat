// test_v2_orchestration_workflow_results_naming.mjs
// Version: 0.261.217
// Implemented in: 0.261.217
// Executes how the V2 plan card names a workflow_results step: the workflow's own name comes from
// the plan inputs, the run it reads is put in words from the step's static arguments, a value the
// server would refuse is never put in words, the step's raw arguments (including its request-local
// handle) are never listed, and the plan inputs keep only each workflow's handle and name.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

globalThis.fetch = () => {
    throw new Error('Workflow results naming helpers must not make network requests.');
};

// The repository resolver must be registered before extensionless TypeScript imports load.
const {
    WORKFLOW_RESULTS_ARGUMENT_KEYS,
    WORKFLOW_RESULTS_CAPABILITY,
    workflowResultsDisplayName,
    workflowResultsSelection,
} = await import('../application/v2_ui/src/lib/orchestrationWorkflowResults.ts');
const { normalizePlan } = await import('../application/v2_ui/src/lib/orchestrationPlan.ts');

const UNKNOWN = 'Run details unavailable';
const HOSTILE_NAME = '<img src=x onerror="alert(1)"> Digest & {{7*7}} [link](https://evil.example/)';

test('the capability and the arguments shown in words match the server contract', () => {
    assert.equal(WORKFLOW_RESULTS_CAPABILITY, 'workflow_results');
    assert.deepEqual([...WORKFLOW_RESULTS_ARGUMENT_KEYS].sort(), ['completed_on', 'selector', 'status', 'workflow']);
});

test('every selector and status the server accepts is put in words', () => {
    const cases = [
        [{ workflow: 'wf_1', selector: 'latest' }, 'Latest run'],
        [{ workflow: 'wf_1', selector: 'latest', status: 'completed' }, 'Latest completed run'],
        [{ workflow: 'wf_1', selector: 'latest', status: 'failed' }, 'Latest failed run'],
        [{ workflow: 'wf_1', selector: 'latest', status: 'cancelled' }, 'Latest cancelled run'],
        [{ workflow: 'wf_1', selector: 'completed_on', completed_on: '2025-01-06' }, 'Run finished on 2025-01-06'],
        [
            { workflow: 'wf_1', selector: 'completed_on', completed_on: '2025-01-06', status: 'completed' },
            'Completed run finished on 2025-01-06',
        ],
        [
            { workflow: 'wf_1', selector: 'completed_on', completed_on: '2025-01-06', status: 'failed' },
            'Failed run finished on 2025-01-06',
        ],
    ];
    for (const [args, expected] of cases) {
        assert.equal(workflowResultsSelection(args), expected, JSON.stringify(args));
    }
});

test('a selector, day or status the server would refuse is never put in words', () => {
    for (const args of [
        undefined, null, 'latest', [], {},
        { selector: 'earliest' },
        { selector: 'latest', status: 'running' },
        { selector: 'latest', status: '__proto__' },
        { selector: 'latest', status: 'toString' },
        { selector: 'latest', status: null },
        { selector: 'completed_on' },
        { selector: 'completed_on', completed_on: 'yesterday' },
        { selector: 'completed_on', completed_on: '2025-1-6' },
        { selector: 'completed_on', completed_on: '2025-01-06T00:00:00Z' },
        { selector: 'completed_on', completed_on: 20250106 },
        { selector: 'completed_on', completed_on: `2025-01-06 ${HOSTILE_NAME}` },
    ]) {
        assert.equal(workflowResultsSelection(args), UNKNOWN, JSON.stringify(args));
    }
});

test('a workflow name is kept as data, and a missing one reads as unavailable', () => {
    assert.equal(workflowResultsDisplayName({ name: HOSTILE_NAME }), HOSTILE_NAME);
    assert.equal(workflowResultsDisplayName({ name: '   ' }), 'Workflow details unavailable');
    assert.equal(workflowResultsDisplayName(undefined), 'Workflow details unavailable');
});

test('the plan inputs keep only each read workflow\'s handle and name', () => {
    const plan = normalizePlan({
        plan_id: 'plan-1',
        planner_contract_version: 2,
        steps: [],
        inputs: {
            documents: [],
            web: false,
            workflow_results: [
                { handle: 'wf_1', name: `  ${HOSTILE_NAME}  `, workflow_id: 'secret-id', run_id: 'secret-run' },
                { handle: 'wf_2', name: '' },
                { handle: '   ', name: 'No handle' },
                'not an entry',
            ],
        },
    });
    assert.deepEqual(plan.inputs.workflow_results, [
        { handle: 'wf_1', name: HOSTILE_NAME },
        { handle: 'wf_2', name: 'Workflow' },
    ]);
    const without = normalizePlan({
        plan_id: 'plan-2',
        planner_contract_version: 2,
        steps: [],
        inputs: { documents: [], web: false },
    });
    assert.equal(Object.prototype.hasOwnProperty.call(without.inputs, 'workflow_results'), false);
});
