// test_v2_orchestration_workflow_run_floor.mjs
// Version: 0.261.211
// Implemented in: 0.261.211
// Executes the shared V2 plan normalization for plans that start a saved workflow: the approval
// floor survives only as `{mode: 'manual'}`, the workflows the approval card names are parsed as
// plain data (the server bounds their length), and the browser's own floor guard holds even when
// the marker is missing.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

globalThis.fetch = () => {
    throw new Error('Plan display helpers must not make network requests.');
};

// The repository resolver must be registered before extensionless TypeScript imports load.
const {
    APPROVAL_FLOOR_CAPABILITIES,
    normalizePlan,
    planHasApprovalFloor,
    planRequiresApproval,
    planWorkflowRuns,
} = await import('../application/v2_ui/src/lib/orchestrationPlan.ts');

const HOSTILE_NAME = '<img src=x onerror="alert(1)"> Digest & {{7*7}}';

function runStep(stepId, handle, { enabled = true } = {}) {
    return {
        step_id: stepId, capability_id: 'workflow_run', role: 'gather', title: 'Start the workflow',
        arguments: { workflow: handle }, enabled,
        outputs: [{ name: 'run', kind: 'structured-v1' }],
    };
}

function answerStep() {
    return {
        step_id: 'answer', capability_id: 'compose', role: 'reason', title: 'Answer',
        outputs: [{ name: 'answer', kind: 'markdown-v1' }],
    };
}

function rawPlan({ approval = { mode: 'manual', state: 'pending' }, steps = [answerStep()], inputs } = {}) {
    const plan = { planner_contract_version: 2, approval, steps, status: 'awaiting_approval' };
    if (inputs !== undefined) {
        plan.inputs = inputs;
    }
    return plan;
}

test('the browser floor list mirrors the registry and names only workflow_run', () => {
    assert.deepEqual([...APPROVAL_FLOOR_CAPABILITIES], ['workflow_run']);
});

test('a manual approval floor survives normalization with its reason', () => {
    const plan = normalizePlan(rawPlan({
        approval: { mode: 'manual', state: 'pending', floor: { mode: 'manual', reason: 'workflow_run' } },
    }));
    assert.deepEqual(plan.approval.floor, { mode: 'manual', reason: 'workflow_run' });
    assert.equal(plan.approval.mode, 'manual');
    assert.equal(planRequiresApproval(plan), true);
});

test('a floor that is not manual, or not an object, is dropped', () => {
    for (const floor of [{ mode: 'auto' }, { mode: 'timed' }, { mode: 'MANUAL' }, 'manual', ['manual'], null, 1, {}]) {
        const plan = normalizePlan(rawPlan({ approval: { mode: 'manual', state: 'pending', floor } }));
        assert.equal('floor' in plan.approval, false, `floor ${JSON.stringify(floor)} should be dropped`);
    }
});

test('a floor with a missing or non-string reason keeps an empty reason', () => {
    for (const reason of [undefined, 7, null, { x: 1 }]) {
        const plan = normalizePlan(rawPlan({ approval: { mode: 'manual', floor: { mode: 'manual', reason } } }));
        assert.deepEqual(plan.approval.floor, { mode: 'manual', reason: '' });
    }
});

test('workflows on the approval card are parsed as trimmed plain data, and a blank handle is dropped', () => {
    const plan = normalizePlan(rawPlan({
        inputs: {
            workflows: [
                { handle: '  wf_1 ', name: '  Weekly digest ', trigger_summary: ' Every Monday at 9:00 ', paused: true },
                { handle: 'wf_2', name: '   ', trigger_summary: 3, paused: 'yes' },
                { handle: 'wf_3', name: HOSTILE_NAME },
                { handle: '   ', name: 'No handle' },
                { handle: 12, name: 'Numeric handle' },
                { name: 'Missing handle' },
                'wf_4',
                null,
            ],
        },
    }));
    assert.deepEqual(plan.inputs.workflows, [
        { handle: 'wf_1', name: 'Weekly digest', trigger_summary: 'Every Monday at 9:00', paused: true },
        { handle: 'wf_2', name: 'Workflow', trigger_summary: '', paused: false },
        { handle: 'wf_3', name: HOSTILE_NAME, trigger_summary: '', paused: false },
    ]);
});

test('a plan without workflows has no workflows key, and a non-list reads as none', () => {
    const without = normalizePlan(rawPlan({ inputs: { documents: [] } }));
    assert.equal('workflows' in without.inputs, false);
    const notList = normalizePlan(rawPlan({ inputs: { workflows: { handle: 'wf_1' } } }));
    assert.equal('workflows' in notList.inputs, false);
    const empty = normalizePlan(rawPlan({ inputs: { workflows: [] } }));
    assert.deepEqual(empty.inputs.workflows, []);
});

test('the floor holds for a marker alone, and for an enabled run step without one', () => {
    const markerOnly = normalizePlan(rawPlan({
        approval: { mode: 'manual', floor: { mode: 'manual', reason: 'workflow_run' } },
    }));
    assert.equal(planHasApprovalFloor(markerOnly), true);

    for (const mode of ['auto', 'timed', 'manual']) {
        const stepOnly = normalizePlan(rawPlan({
            approval: { mode, state: 'pending' }, steps: [runStep('run', 'wf_1'), answerStep()],
        }));
        assert.equal('floor' in stepOnly.approval, false);
        assert.equal(planHasApprovalFloor(stepOnly), true, `an enabled run step holds a ${mode} plan`);
    }
});

test('a switched-off run step, or no run step, sets no floor', () => {
    const disabled = normalizePlan(rawPlan({
        approval: { mode: 'timed', state: 'pending' },
        steps: [runStep('run', 'wf_1', { enabled: false }), answerStep()],
    }));
    assert.equal(planHasApprovalFloor(disabled), false);

    const none = normalizePlan(rawPlan({ approval: { mode: 'auto', state: 'approved' } }));
    assert.equal(planHasApprovalFloor(none), false);

    const proposal = normalizePlan(rawPlan({
        steps: [{ ...runStep('propose', 'wf_1'), capability_id: 'workflow_propose' }, answerStep()],
    }));
    assert.equal(planHasApprovalFloor(proposal), false);
});

test('planWorkflowRuns counts enabled run steps and names each known workflow once in step order', () => {
    const plan = normalizePlan(rawPlan({
        steps: [
            runStep('run_b', 'wf_2'),
            runStep('run_a', 'wf_1'),
            runStep('run_off', 'wf_3', { enabled: false }),
            runStep('run_unknown', 'wf_9'),
            runStep('run_again', 'wf_2'),
            answerStep(),
        ],
        inputs: {
            workflows: [
                { handle: 'wf_1', name: 'Weekly digest', trigger_summary: 'Every Monday', paused: true },
                { handle: 'wf_2', name: 'Contract watcher', trigger_summary: 'Manual', paused: false },
                { handle: 'wf_3', name: 'Switched off', trigger_summary: '', paused: false },
            ],
        },
    }));
    const { count, workflows } = planWorkflowRuns(plan);
    assert.equal(count, 4);
    assert.deepEqual(workflows.map((workflow) => workflow.handle), ['wf_2', 'wf_1']);
    assert.equal(workflows[1].paused, true);
});

test('planWorkflowRuns still counts a run step when the plan names no workflows', () => {
    const plan = normalizePlan(rawPlan({ steps: [runStep('run', 'wf_1'), answerStep()] }));
    assert.deepEqual(planWorkflowRuns(plan), { count: 1, workflows: [] });
    const withoutInputs = { steps: plan.steps };
    assert.deepEqual(planWorkflowRuns(withoutInputs), { count: 1, workflows: [] });
});

test('a hostile workflow name stays a literal string for the card to render as text', () => {
    const plan = normalizePlan(rawPlan({
        steps: [runStep('run', 'wf_1'), answerStep()],
        inputs: { workflows: [{ handle: 'wf_1', name: HOSTILE_NAME, trigger_summary: '<b>bold</b>' }] },
    }));
    const [workflow] = planWorkflowRuns(plan).workflows;
    assert.equal(workflow.name, HOSTILE_NAME);
    assert.equal(workflow.trigger_summary, '<b>bold</b>');
});
