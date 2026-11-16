// test_v2_orchestration_phase_groups.mjs
// Version: 0.261.139
// Implemented in: 0.261.139
// Executes the shared plan normalization/grouping used by the real run view.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

const originalFetch = globalThis.fetch;
globalThis.fetch = () => {
    throw new Error('Role grouping must not make network requests.');
};

// The repository resolver must be registered before extensionless TypeScript imports load.
const { ApiError } = await import('../application/v2_ui/src/lib/apiClient.ts');
const { isLegacyPlanError, LEGACY_PLAN_ERROR_CODE } = await import(
    '../application/v2_ui/src/lib/orchestrationErrors.ts'
);
const { groupStepsForDisplay, normalizePlan } = await import(
    '../application/v2_ui/src/lib/orchestrationPlan.ts'
);

function step(stepId, role, fields = {}) {
    return { step_id: stepId, capability_id: stepId, title: stepId, role, ...fields };
}

function normalize(steps) {
    const plan = normalizePlan({ planner_contract_version: 2, steps });
    assert.ok(plan, 'The fixture must normalize to a usable plan.');
    return plan;
}

function stepIds(groups) {
    return groups.flatMap((group) => group.steps.map(({ step: value }) => value.step_id));
}

test('missing or non-2 plan versions are not renderable', () => {
    assert.equal(normalizePlan({ steps: [step('gather', 'gather')] }), null);
    assert.equal(normalizePlan({ planner_contract_version: 1, steps: [step('gather', 'gather')] }), null);
    assert.equal(normalizePlan({ planner_contract_version: 3, steps: [step('gather', 'gather')] }), null);
});

test('legacy_plan ApiError is identified by status and payload code', () => {
    const error = new ApiError('server message', 409, {
        code: LEGACY_PLAN_ERROR_CODE,
        error: "This plan was created by an earlier orchestration version and can't be opened or rerun. Start a new request.",
    });
    assert.equal(isLegacyPlanError(error), true);
    assert.equal(isLegacyPlanError(new ApiError('already run', 409, { code: 'already_run' })), false);
});

test('role groups only consecutive roles without globally regrouping the saved execution order', () => {
    const plan = normalize([
        step('gather-first', 'gather'),
        step('prepare-first', 'reason', { depends_on: ['gather-first'] }),
        step('gather-followup', 'gather', { depends_on: ['prepare-first'] }),
        step('prepare-answer', 'reason', { depends_on: ['gather-followup'] }),
        step('prepare-notes', 'reason'),
        step('render-file', 'render', { depends_on: ['prepare-answer'] }),
    ]);
    const before = structuredClone(plan);
    const groups = groupStepsForDisplay(plan);
    assert.deepEqual(groups.map((group) => group.label), ['Gather', 'Reason', 'Gather', 'Reason', 'Render']);
    assert.deepEqual(stepIds(groups), plan.steps.map((value) => value.step_id));
    assert.deepEqual(groups[3].steps.map(({ step: value }) => value.step_id), ['prepare-answer', 'prepare-notes']);
    assert.deepEqual(groups.flatMap((group) => group.steps.map(({ number }) => number)), [1, 2, 3, 4, 5, 6]);
    assert.deepEqual(plan, before);
});

test('unknown roles stay in sequence under an unlabeled group', () => {
    const plan = normalize([
        step('gather', 'gather'),
        step('custom-one', 'custom-role'),
        step('custom-two', 'custom-role'),
        step('render', 'render'),
    ]);
    const groups = groupStepsForDisplay(plan);
    assert.deepEqual(groups.map((group) => group.label), ['Gather', null, 'Render']);
    assert.deepEqual(stepIds(groups), ['gather', 'custom-one', 'custom-two', 'render']);
    assert.equal(groups[1].key, 'custom-role-1');
});

test.after(() => {
    globalThis.fetch = originalFetch;
});
