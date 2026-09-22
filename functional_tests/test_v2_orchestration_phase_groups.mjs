// test_v2_orchestration_phase_groups.mjs
// Version: 0.261.127
// Implemented in: 0.261.127
// Executes the shared plan normalization/grouping used by the real run view.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

const originalFetch = globalThis.fetch;
globalThis.fetch = () => {
    throw new Error('Phase grouping must not make network requests.');
};

// The repository resolver must be registered before extensionless TypeScript imports load.
const { groupStepsForDisplay, normalizePlan } = await import(
    '../application/v2_ui/src/lib/orchestrationPlan.ts'
);

function step(stepId, phase, fields = {}) {
    return { step_id: stepId, capability_id: stepId, title: stepId, phase, ...fields };
}

function normalize(steps, version) {
    const raw = { steps };
    if (version !== undefined) raw.planner_contract_version = version;
    const plan = normalizePlan(raw);
    assert.ok(plan, 'The fixture must normalize to a usable plan.');
    return plan;
}

function stepIds(groups) {
    return groups.flatMap((group) => group.steps.map(({ step: value }) => value.step_id));
}

test('legacy server phases survive normalization and override current catalog classifications', () => {
    for (const version of [undefined, 1]) {
        const plan = normalize([
            step('file', 'output'),
            step('knowledge-a', 'knowledge', { role: 'reason' }),
            step('answer', 'reasoning'),
            step('knowledge-b', 'knowledge'),
        ], version);
        const before = structuredClone(plan);
        const groups = groupStepsForDisplay(plan, [
            { id: 'knowledge-a', phase: 'output', role: 'reason' },
            { id: 'knowledge-b', phase: 'reasoning' },
            { id: 'answer', phase: 'knowledge' },
        ]);
        const withoutCatalog = groupStepsForDisplay(plan, []);
        assert.equal(plan.planner_contract_version, 1);
        assert.deepEqual(plan.steps.map((value) => value.phase), ['output', 'knowledge', 'reasoning', 'knowledge']);
        assert.equal(Object.hasOwn(plan.steps[1], 'role'), false);
        assert.deepEqual(groups.map((group) => group.key), ['knowledge', 'reasoning', 'output']);
        assert.deepEqual(groups.map((group) => group.label), ['Gathering knowledge', 'Reasoning', 'Creating']);
        assert.deepEqual(stepIds(groups), ['knowledge-a', 'knowledge-b', 'answer', 'file']);
        assert.deepEqual(groups.flatMap((group) => group.steps.map(({ number }) => number)), [1, 2, 3, 4]);
        assert.deepEqual(withoutCatalog, groups);
        assert.deepEqual(plan, before);
    }
});

test('missing legacy phases can use the catalog but unknown server phases are never discarded or replaced', () => {
    const plan = normalize([
        step('missing', undefined, { capability_id: 'unregistered' }),
        step('unknown', 'future-phase', { capability_id: 'reclassified' }),
        step('catalog-fallback', undefined, { capability_id: 'historic-capability' }),
    ], 1);
    const groups = groupStepsForDisplay(plan, [
        { id: 'reclassified', phase: 'reasoning' },
        { id: 'historic-capability', phase: 'knowledge' },
    ]);
    assert.deepEqual(groups.map((group) => group.key), ['knowledge', 'unclassified']);
    assert.deepEqual(stepIds(groups), ['catalog-fallback', 'missing', 'unknown']);
    assert.equal(groups[1].label, null);
    assert.equal(groups[1].steps[1].step.phase, 'future-phase');
    assert.equal(groups.reduce((count, group) => count + group.steps.length, 0), plan.steps.length);
});

test('legacy dependency order and stable ordering within a phase are preserved', () => {
    const plan = normalize([
        step('dependent', 'knowledge', { depends_on: ['source'] }),
        step('source', 'knowledge'),
        step('independent', 'knowledge'),
        step('answer', 'reasoning', { depends_on: ['dependent', 'independent'] }),
    ], 1);
    const groups = groupStepsForDisplay(plan);
    assert.deepEqual(stepIds(groups), ['source', 'dependent', 'independent', 'answer']);
    assert.deepEqual(groups[0].steps.map(({ number }) => number), [1, 2, 3]);
});

test('v2 groups only consecutive roles without globally regrouping the saved execution order', () => {
    const plan = normalize([
        step('gather-first', undefined, { role: 'gather' }),
        step('prepare-first', undefined, { role: 'reason', depends_on: ['gather-first'] }),
        step('gather-followup', undefined, { role: 'gather', depends_on: ['prepare-first'] }),
        step('prepare-answer', undefined, { role: 'reason', depends_on: ['gather-followup'] }),
        step('prepare-notes', undefined, { role: 'reason' }),
        step('render-file', undefined, { role: 'render', depends_on: ['prepare-answer'] }),
    ], 2);
    const before = structuredClone(plan);
    const groups = groupStepsForDisplay(plan);
    assert.deepEqual(groups.map((group) => group.label), ['Gather', 'Reason', 'Gather', 'Reason', 'Render']);
    assert.deepEqual(stepIds(groups), plan.steps.map((value) => value.step_id));
    assert.deepEqual(groups[3].steps.map(({ step: value }) => value.step_id), ['prepare-answer', 'prepare-notes']);
    assert.deepEqual(groups.flatMap((group) => group.steps.map(({ number }) => number)), [1, 2, 3, 4, 5, 6]);
    assert.deepEqual(plan, before);
});

test.after(() => {
    globalThis.fetch = originalFetch;
});
