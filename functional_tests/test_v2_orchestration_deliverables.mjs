// test_v2_orchestration_deliverables.mjs
// Version: 0.261.135
// Implemented in: 0.261.135
// Executes the shared plan normalization for deliverables: what a plan says the user asked
// for, how each deliverable's state follows its producing steps, and the image helpers.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

const originalFetch = globalThis.fetch;
globalThis.fetch = () => {
    throw new Error('Plan display helpers must not make network requests.');
};

// The repository resolver must be registered before extensionless TypeScript imports load.
const {
    bindsGeneratedImage, deliverableKindLabel, deliverableRows, hasGeneratedImages,
    normalizeDeliverables, normalizePlan,
} = await import('../application/v2_ui/src/lib/orchestrationPlan.ts');

function binding(stepId, outputName) {
    return { version: 'orchestration-input-binding-v1', step_id: stepId, output_name: outputName, existing_result: null };
}

function presidentsPlan() {
    return normalizePlan({
        planner_contract_version: 2,
        deliverables: [
            { id: 'report', kind: 'answer', requested: 'explicit', status: 'planned', description: 'A report' },
            { id: 'word_file', kind: 'file', format: 'docx', requested: 'explicit', status: 'planned',
              description: 'The report as a Word file' },
            { id: 'portraits', kind: 'image', quantity: 3, requested: 'explicit', status: 'planned',
              description: 'An image of each president' },
            { id: 'slides', kind: 'file', format: 'pptx', requested: 'explicit', status: 'unavailable',
              unavailable_reason: 'format_not_admitted',
              unavailable_message: 'This file format is not available for this plan.', description: 'Slides' },
            { id: 'timeline', kind: 'diagram', requested: 'suggested', status: 'planned', description: 'A timeline' },
        ],
        steps: [
            { step_id: 'washington', capability_id: 'generate_image', role: 'reason', title: 'Illustrate Washington',
              outputs: [{ name: 'image', kind: 'image-asset-v1' }], delivers: ['portraits'] },
            { step_id: 'adams', capability_id: 'generate_image', role: 'reason', title: 'Illustrate Adams',
              outputs: [{ name: 'image', kind: 'image-asset-v1' }], delivers: ['portraits'] },
            { step_id: 'report', capability_id: 'compose', role: 'reason', title: 'Write the report',
              inputs: { washington: { binding: binding('washington', 'image'), optional: true } },
              outputs: [{ name: 'report', kind: 'markdown-v1' }], delivers: ['report', 'timeline'] },
            { step_id: 'word', capability_id: 'render_file', role: 'render', title: 'Save the Word file',
              outputs: [], delivers: ['word_file'] },
        ],
    });
}

test('deliverables and step delivers survive normalization; malformed entries are dropped', () => {
    const plan = presidentsPlan();
    assert.equal(plan.deliverables.length, 5);
    assert.deepEqual(plan.deliverables[2], {
        id: 'portraits', kind: 'image', description: 'An image of each president',
        requested: 'explicit', status: 'planned', quantity: 3,
    });
    assert.deepEqual(plan.steps[2].delivers, ['report', 'timeline']);
    assert.deepEqual(normalizeDeliverables([
        { id: '', kind: 'file', description: 'No id' },
        { id: 'x', kind: 'video', description: 'Unknown kind' },
        { id: 'y', kind: 'chart', description: '' },
        { id: 'z', kind: 'chart', description: 'A chart', quantity: -1, requested: 'other', status: 'weird' },
    ]), [{ id: 'z', kind: 'chart', description: 'A chart', requested: 'explicit', status: 'planned' }]);
    assert.equal(normalizeDeliverables(undefined), undefined);
    // Legacy plans carry no deliverables, and steps without the field keep their old shape.
    const legacy = normalizePlan({ deliverables: [{ id: 'a', kind: 'answer', description: 'An answer' }], steps: [{}] });
    assert.equal(legacy.deliverables, undefined);
    const bare = normalizePlan({ planner_contract_version: 2, steps: [{ step_id: 'a', capability_id: 'compose' }] });
    assert.equal(Object.hasOwn(bare.steps[0], 'delivers'), false);
});

test('each deliverable follows the state of the steps that produce it', () => {
    const plan = presidentsPlan();
    const planned = deliverableRows(plan, () => undefined);
    assert.deepEqual(planned.map((row) => [row.deliverable.id, row.state]), [
        ['report', 'planned'], ['word_file', 'planned'], ['portraits', 'planned'],
        ['slides', 'unavailable'], ['timeline', 'planned'],
    ]);
    assert.equal(planned[3].reason, 'This file format is not available for this plan.');
    assert.deepEqual(planned[2].steps, ['Illustrate Washington', 'Illustrate Adams']);

    const statuses = { washington: 'completed', adams: 'failed', report: 'completed', word: 'running' };
    const running = deliverableRows(plan, (stepId) => statuses[stepId]);
    assert.deepEqual(running.map((row) => row.state), ['delivered', 'running', 'not_delivered', 'unavailable', 'delivered']);
    assert.equal(running[2].stateLabel, 'Not delivered');

    const edits = { disabled_step_ids: ['word'], removed_document_ids: {} };
    assert.equal(deliverableRows(plan, () => undefined, edits)[1].state, 'turned_off');
});

test('the implicit answer of plans that declared nothing is not listed', () => {
    const plan = normalizePlan({
        planner_contract_version: 2,
        deliverables: [{ id: 'answer', kind: 'answer', requested: 'explicit', status: 'planned',
                         description: 'An answer to your request.', implicit: true }],
        steps: [{ step_id: 'prepare', capability_id: 'compose' }],
    });
    assert.equal(plan.deliverables[0].implicit, true);
    assert.deepEqual(deliverableRows(plan, () => undefined), []);
});

test('labels name formats and quantities in plain words', () => {
    assert.equal(deliverableKindLabel({ kind: 'file', format: 'docx' }), 'Word document');
    assert.equal(deliverableKindLabel({ kind: 'file', format: 'csv' }), 'CSV file');
    assert.equal(deliverableKindLabel({ kind: 'file', format: 'mp4' }), 'MP4 file');
    assert.equal(deliverableKindLabel({ kind: 'file', format: 'xlsx', quantity: 2 }), '2 × Excel workbook');
    assert.equal(deliverableKindLabel({ kind: 'image', quantity: 3 }), '3 images');
    assert.equal(deliverableKindLabel({ kind: 'image' }), 'Image');
    assert.equal(deliverableKindLabel({ kind: 'diagram' }), 'Diagram');
});

test('generated image inputs and answers are recognised from structured fields only', () => {
    const plan = presidentsPlan();
    assert.equal(bindsGeneratedImage(plan, binding('washington', 'image')), true);
    assert.equal(bindsGeneratedImage(plan, binding('report', 'report')), false);
    assert.equal(bindsGeneratedImage(plan, null), false);
    assert.equal(hasGeneratedImages({ generated_images: [{ visual_id: 'a', message_id: 'm-1' }] }), true);
    assert.equal(hasGeneratedImages({ generated_images: [] }), false);
    assert.equal(hasGeneratedImages({ generated_images: [{ visual_id: 'a' }] }), false);
    assert.equal(hasGeneratedImages(undefined), false);
});

test.after(() => {
    globalThis.fetch = originalFetch;
});
