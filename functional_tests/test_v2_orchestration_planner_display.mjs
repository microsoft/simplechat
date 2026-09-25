// test_v2_orchestration_planner_display.mjs
// Version: 0.261.134
// Implemented in: 0.261.134
// Executes the shared plan normalization for the planner descriptor, Auto routing,
// optional named inputs, and the answer-basis and visual labels the plan panel shows.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

const originalFetch = globalThis.fetch;
globalThis.fetch = () => {
    throw new Error('Plan display helpers must not make network requests.');
};

// The repository resolver must be registered before extensionless TypeScript imports load.
const {
    KNOWLEDGE_BASIS_LABELS, VISUAL_KIND_LABELS, describePlanner, normalizePlan, normalizePlanner,
} = await import('../application/v2_ui/src/lib/orchestrationPlan.ts');

function binding(stepId, outputName) {
    return { version: 'orchestration-input-binding-v1', step_id: stepId, output_name: outputName, existing_result: null };
}

test('the planner descriptor and Auto routing survive normalization', () => {
    const plan = normalizePlan({
        planner_contract_version: 2,
        planner: { label: 'gpt-5.4', source: 'selected', reasoning_effort: 'low', endpoint: 'https://private.invalid' },
        model_routing: 'auto',
        steps: [{ step_id: 'prepare', capability_id: 'compose', role: 'reason' }],
    });
    assert.deepEqual(plan.planner, { label: 'gpt-5.4', source: 'selected', reasoning_effort: 'low' });
    assert.equal(plan.model_routing, 'auto');
    assert.equal(
        describePlanner(plan),
        'Planned by gpt-5.4 (the model you selected); each step uses its own Auto-routed model',
    );
});

test('older plans and unknown sources degrade without inventing a planner', () => {
    const legacy = normalizePlan({ steps: [] });
    assert.equal(legacy.planner, undefined);
    assert.equal(legacy.model_routing, undefined);
    assert.equal(describePlanner(legacy), null);
    assert.equal(normalizePlanner({ label: '   ' }), undefined);
    assert.deepEqual(normalizePlanner({ label: 'planner-mini', source: 'something-else' }), {
        label: 'planner-mini', source: 'default',
    });
    assert.equal(
        describePlanner({ planner: { label: 'planner-mini', source: 'planner_setting' } }),
        "Planned by planner-mini (the administrator's planning model)",
    );
});

test('optional named inputs are carried and ordinary inputs stay required', () => {
    const plan = normalizePlan({
        planner_contract_version: 2,
        steps: [{
            step_id: 'prepare', capability_id: 'compose', role: 'reason',
            inputs: {
                findings: { binding: binding('search', 'prepared'), allow_partial: false, optional: true },
                notes: { binding: binding('notes', 'answer'), allow_partial: false },
            },
        }],
    });
    assert.equal(plan.steps[0].inputs.findings.optional, true);
    assert.equal(Object.hasOwn(plan.steps[0].inputs.notes, 'optional'), false);
});

test('answer basis and visual kinds have readable labels', () => {
    assert.equal(KNOWLEDGE_BASIS_LABELS.general_knowledge, 'General knowledge');
    assert.equal(KNOWLEDGE_BASIS_LABELS.sources, 'Gathered sources only');
    assert.match(KNOWLEDGE_BASIS_LABELS.sources_and_general_knowledge, /general knowledge for stable facts/);
    assert.deepEqual(Object.keys(VISUAL_KIND_LABELS), ['chart', 'diagram', 'image_proposal']);
});

test.after(() => {
    globalThis.fetch = originalFetch;
});
