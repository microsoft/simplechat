// test_v2_orchestration_deliverables.mjs
// Version: 0.261.139
// Implemented in: 0.261.135
// Executes the shared plan normalization for deliverables: what a plan says the user asked
// for, how each deliverable's state follows its producing steps, and the image helpers.
// Also reads a terminal frame shaped as the harness publishes it through the real run
// stream client, and groups a retry's images under every answer that lists them.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import './test_support/tsResolve.mjs';

const originalFetch = globalThis.fetch;
globalThis.fetch = () => {
    throw new Error('Plan display helpers must not make network requests.');
};

// The repository resolver must be registered before extensionless TypeScript imports load.
const {
    bindsGeneratedImage, deliverableKindLabel, deliverableRows, doneFrameHasGeneratedImages, hasGeneratedImages,
    normalizeDeliverables, normalizePlan,
} = await import('../application/v2_ui/src/lib/orchestrationPlan.ts');
const { runOrchestration } = await import('../application/v2_ui/src/lib/orchestration.ts');
const {
    answerGeneratedImages, groupProposalImages, parseImageProposal, plannedImageRef, resultForCard,
} = await import('../application/v2_ui/src/lib/imageProposalSpec.ts');

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
    // Non-current plans are not renderable, and steps without the field keep their current shape.
    const oldPlan = normalizePlan({ deliverables: [{ id: 'a', kind: 'answer', description: 'An answer' }], steps: [{}] });
    assert.equal(oldPlan, null);
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

// The terminal frame the harness publishes: the saved image messages are listed at the top
// level and in the answer's metadata (functions_orchestration_execution._finalize).
function doneFrame(extra = {}) {
    const images = [{ visual_id: 'washington', message_id: 'conversation-1_image_1' }];
    return {
        done: true, type: 'orchestration_done', conversation_id: 'conversation-1',
        message_id: 'assistant_orchestration_1', run_id: 'run-1', status: 'completed', outcome: 'completed',
        full_content: 'The report.', replace_content: true, role: 'assistant',
        generated_images: images,
        metadata: { orchestration: { run_id: 'run-1', status: 'completed', generated_images: images } },
        ...extra,
    };
}

async function readRun(frames) {
    const encoder = new TextEncoder();
    const done = [];
    const blocked = globalThis.fetch;
    globalThis.fetch = async () => new Response(new ReadableStream({
        start(controller) {
            for (const frame of frames) controller.enqueue(encoder.encode(`data: ${JSON.stringify(frame)}\n\n`));
            controller.close();
        },
    }), { headers: { 'Content-Type': 'text/event-stream' } });
    try {
        await runOrchestration({ run_id: 'run-1', plan_id: 'plan-1', conversation_id: 'conversation-1' }, {
            onDone: (event) => done.push(event),
        });
    } finally {
        globalThis.fetch = blocked;
    }
    return done;
}

test('the chat learns about generated images from the real terminal frame', async () => {
    const [event] = await readRun([
        { type: 'orchestration_step', step_id: 'washington', status: 'completed' },
        { content: 'The report.' },
        doneFrame(),
    ]);
    assert.equal(doneFrameHasGeneratedImages(event), true);
    // Either location is enough, so an older frame shape still loads the images.
    const [metadataOnly] = await readRun([doneFrame({ generated_images: undefined })]);
    assert.equal(doneFrameHasGeneratedImages(metadataOnly), true);
    const [topLevelOnly] = await readRun([doneFrame({ metadata: {} })]);
    assert.equal(doneFrameHasGeneratedImages(topLevelOnly), true);
    const [none] = await readRun([doneFrame({ generated_images: undefined, metadata: {} })]);
    assert.equal(doneFrameHasGeneratedImages(none), false);
});

test('every answer that lists an image shows it, and its card never offers approval', () => {
    const image = (id, visualId, source) => ({
        id, role: 'image', content: `/api/image/${id}`, conversation_id: 'conversation-1',
        metadata: { image_proposal: { visualId, title: visualId, source_assistant_message_id: source } },
    });
    const answer = (id, images) => ({
        id, role: 'assistant', content: 'A report.', conversation_id: 'conversation-1',
        metadata: { orchestration: { generated_images: images } },
    });
    // The retry reused Washington from the earlier attempt and generated Adams itself.
    const earlier = answer('assistant_1', [{ visual_id: 'washington', message_id: 'image_w' }]);
    const retried = answer('assistant_2', [
        { visual_id: 'washington', message_id: 'image_w' }, { visual_id: 'adams', message_id: 'image_a' },
    ]);
    const washington = image('image_w', 'washington', 'assistant_1');
    const adams = image('image_a', 'adams', 'assistant_2');
    const grouped = groupProposalImages([earlier, washington, retried, adams]);

    assert.deepEqual(grouped.get('assistant_1').map((message) => message.id), ['image_w']);
    assert.deepEqual(grouped.get('assistant_2').map((message) => message.id), ['image_a', 'image_w']);
    assert.deepEqual(answerGeneratedImages(retried), [
        { visualId: 'washington', messageId: 'image_w' }, { visualId: 'adams', messageId: 'image_a' },
    ]);
    assert.deepEqual(answerGeneratedImages({ ...retried, role: 'user' }), []);
    assert.deepEqual(answerGeneratedImages({ role: 'assistant', metadata: { orchestration: {
        generated_images: [{ visual_id: 'x' }, 'bad', { message_id: 'm' }],
    } } }), []);

    const spec = parseImageProposal(JSON.stringify({ visualId: 'washington', title: 'Washington', prompt: 'A portrait' }));
    assert.equal(spec.ok, true);
    const generated = answerGeneratedImages(retried);
    assert.deepEqual(plannedImageRef(spec.spec, generated), { visualId: 'washington', messageId: 'image_w' });
    assert.equal(resultForCard(spec.spec, grouped.get('assistant_2'), generated).id, 'image_w');
    // Before the thread has loaded the image, a planned card has nothing to show and no approval to offer.
    assert.equal(resultForCard(spec.spec, [], generated), null);
    assert.equal(plannedImageRef(spec.spec, []), null);
    // A suggested proposal still resolves by its own visual id.
    assert.equal(resultForCard(spec.spec, [washington], []).id, 'image_w');
});

/** The classic client's real grouping functions, executed without its DOM startup graph. */
function loadClassicGrouping() {
    const source = readFileSync(
        new URL('../application/single_app/static/js/chat/chat-messages.js', import.meta.url), 'utf8',
    ).replace(/\r\n/g, '\n');
    const names = [
        'getGeneratedImageProposalMetadata', 'getGeneratedImageProposalSourceMessageId',
        'groupGeneratedImageProposalMessages',
    ];
    const bodies = names.map((name) => {
        const start = source.indexOf(`export function ${name}(`);
        assert.notEqual(start, -1, `${name} is missing from chat-messages.js`);
        return source.slice(start + 'export '.length, source.indexOf('\n}\n', start) + 2);
    });
    return new Function(`${bodies.join('\n')}\nreturn { ${names.join(', ')} };`)();
}

test('the classic client also shows a reused image under both answers', () => {
    const { groupGeneratedImageProposalMessages } = loadClassicGrouping();
    const washington = {
        id: 'image_w', role: 'image',
        metadata: { image_proposal: { visualId: 'washington', source_assistant_message_id: 'assistant_1' } },
    };
    const earlier = { id: 'assistant_1', role: 'assistant', metadata: {} };
    const retried = {
        id: 'assistant_2', role: 'assistant',
        metadata: { orchestration: { generated_images: [{ visual_id: 'washington', message_id: 'image_w' }] } },
    };
    const grouped = groupGeneratedImageProposalMessages([earlier, washington, retried]);
    assert.deepEqual(grouped.get('assistant_1'), [washington]);
    assert.deepEqual(grouped.get('assistant_2'), [washington]);
    assert.equal(groupGeneratedImageProposalMessages(undefined).size, 0);
});

test.after(() => {
    globalThis.fetch = originalFetch;
});
