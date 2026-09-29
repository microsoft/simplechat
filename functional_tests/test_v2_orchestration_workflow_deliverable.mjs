// test_v2_orchestration_workflow_deliverable.mjs
// Version: 0.261.206
// Implemented in: 0.261.206
// Executes the shared V2 plan normalization for the orchestration `workflow` deliverable: a plan
// that proposes a workflow keeps the deliverable, labels it as a proposal, and never reports a
// prepared proposal as "Delivered", because nothing exists until the user approves its card.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

globalThis.fetch = () => {
    throw new Error('Plan display helpers must not make network requests.');
};

// The repository resolver must be registered before extensionless TypeScript imports load.
const { deliverableKindLabel, deliverableRows, normalizeDeliverables, normalizePlan } = await import(
    '../application/v2_ui/src/lib/orchestrationPlan.ts'
);

function mondayPlan({ proposalEnabled = true, workflowStatus = 'planned' } = {}) {
    const workflow = {
        id: 'weekly_review', kind: 'workflow', requested: 'explicit', status: workflowStatus,
        description: 'A workflow that reviews email every Monday',
    };
    if (workflowStatus === 'unavailable') {
        workflow.unavailable_reason = 'workflow_shared_conversation';
        workflow.unavailable_message = 'Workflows can be proposed only in your own conversations, not in shared ones.';
    }
    const steps = [
        { step_id: 'answer', capability_id: 'compose', role: 'reason', title: 'Plan this week',
          outputs: [{ name: 'answer', kind: 'markdown-v1' }], delivers: ['answer'] },
    ];
    if (workflowStatus === 'planned') {
        steps.push({
            step_id: 'propose', capability_id: 'workflow_propose', role: 'reason', title: 'Propose the workflow',
            enabled: proposalEnabled, outputs: [{ name: 'proposal', kind: 'structured-v1' }],
            delivers: ['weekly_review'],
        });
    }
    return normalizePlan({
        planner_contract_version: 2,
        deliverables: [
            { id: 'answer', kind: 'answer', requested: 'explicit', status: 'planned', description: 'This week' },
            workflow,
        ],
        steps,
    });
}

function rowFor(plan, statuses) {
    const rows = deliverableRows(plan, (stepId) => statuses[stepId]);
    return rows.find((row) => row.deliverable.id === 'weekly_review');
}

test('a workflow deliverable survives normalization and is labelled as a proposal', () => {
    const [workflow] = normalizeDeliverables([
        { id: 'weekly_review', kind: 'workflow', requested: 'explicit', status: 'planned',
          description: 'A workflow that reviews email every Monday' },
    ]);
    assert.deepEqual(workflow, {
        id: 'weekly_review', kind: 'workflow', requested: 'explicit', status: 'planned',
        description: 'A workflow that reviews email every Monday',
    });
    assert.equal(deliverableKindLabel(workflow), 'Workflow proposal');
    assert.deepEqual(mondayPlan().steps[1].delivers, ['weekly_review']);
});

test('a prepared proposal reads as proposed, never as delivered', () => {
    const plan = mondayPlan();
    assert.equal(rowFor(plan, {}).stateLabel, 'Planned');
    assert.equal(rowFor(plan, { propose: 'running' }).stateLabel, 'In progress');

    const prepared = rowFor(plan, { answer: 'completed', propose: 'completed' });
    assert.equal(prepared.state, 'delivered');
    assert.equal(prepared.stateLabel, 'Proposed');
    assert.equal(prepared.label, 'Workflow proposal');

    const failed = rowFor(plan, { answer: 'completed', propose: 'failed' });
    assert.equal(failed.state, 'not_delivered');
    assert.equal(failed.stateLabel, 'Not delivered');

    // Other kinds keep their usual label.
    const answer = deliverableRows(plan, () => 'completed').find((row) => row.deliverable.id === 'answer');
    assert.equal(answer.stateLabel, 'Delivered');
});

test('a turned-off or unavailable proposal keeps the usual states and the server reason', () => {
    const off = rowFor(mondayPlan({ proposalEnabled: false }), { answer: 'completed' });
    assert.equal(off.state, 'turned_off');
    assert.equal(off.stateLabel, 'Turned off');

    const unavailable = rowFor(mondayPlan({ workflowStatus: 'unavailable' }), { answer: 'completed' });
    assert.equal(unavailable.state, 'unavailable');
    assert.equal(unavailable.stateLabel, 'Not available');
    assert.equal(unavailable.reason, 'Workflows can be proposed only in your own conversations, not in shared ones.');
});
