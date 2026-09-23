// test_v2_chat_content_checks.mjs
// Version: 0.261.127
// Implemented in: 0.261.127
// Execute the real SSE readers and shared-event dispatcher against synthetic frames.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const { streamChat, resolveStreamContent, isReplyRemoved } = await import('../application/v2_ui/src/lib/sse.ts');
const { dispatchCollaborationEvent } = await import('../application/v2_ui/src/lib/collaborationEvents.ts');
const { deriveSectionStatus } = await import('../application/v2_ui/src/lib/adminSections.ts');

const originalFetch = globalThis.fetch;
const encoder = new TextEncoder();
const removed = 'This AI reply was removed because it did not meet the application content rules.';

async function readFrames(frames) {
    const snapshots = [];
    const terminal = [];
    const failures = [];
    const cancellations = [];
    globalThis.fetch = async () => new Response(new ReadableStream({
        start(controller) {
            for (const frame of frames) {
                controller.enqueue(encoder.encode(`data: ${JSON.stringify(frame)}\n\n`));
            }
            controller.close();
        },
    }), { headers: { 'Content-Type': 'text/event-stream' } });
    const result = await streamChat(
        { message: 'A synthetic request', conversation_id: 'conversation' },
        {
            onContent: (_delta, accumulated) => snapshots.push(accumulated),
            onDone: (event, accumulated) => terminal.push({ event, accumulated }),
            onError: (message) => failures.push(message),
            onCancelled: (event, accumulated) => cancellations.push({ event, accumulated }),
        },
        undefined,
        { allowRecovery: false },
    );
    return { result, snapshots, terminal, failures, cancellations };
}

try {
    const fields = [
        { key: 'enable_content_screening', type: 'switch', role: 'capability' },
        {
            key: 'enable_content_screening_workspace_uploads', type: 'switch', default: true,
            depends_on: { key: 'enable_content_screening', equals: true },
            requires: { key: 'enable_enhanced_citations', label: 'Enhanced Citations' },
        },
    ];
    assert.equal(deriveSectionStatus(fields, {
        enable_content_screening: true, enable_content_screening_workspace_uploads: false,
        enable_enhanced_citations: false,
    }, {}), 'ready');
    assert.equal(deriveSectionStatus(fields, {
        enable_content_screening: true, enable_content_screening_workspace_uploads: true,
        enable_enhanced_citations: false,
    }, {}), 'blocked');

    const live = await readFrames([
        { content: 'alice@' },
        { content: 'example.test' },
        {
            done: true, role: 'safety', blocked: true, replace_content: true,
            content: removed, full_content: removed, message_id: 'reply',
            metadata: { content_moderation: { removed: true, revision: '2' } },
        },
    ]);
    assert.equal(live.snapshots[1], 'alice@example.test');
    assert.equal(live.snapshots.at(-1), removed);
    assert.equal(live.result.accumulated, removed);
    assert.equal(live.terminal.length, 1);
    assert.equal(live.terminal[0].event.role, 'safety');
    assert.equal(live.terminal[0].accumulated, removed);
    assert.equal(live.failures.length, 0);

    const held = await readFrames([
        { done: true, full_content: 'The checked answer.', replace_content: true, role: 'assistant' },
    ]);
    assert.deepEqual(held.snapshots, ['The checked answer.']);
    assert.equal(held.result.accumulated, 'The checked answer.');

    const quiet = await readFrames([
        { content: 'An allowed answer.' },
        {
            done: true, role: 'assistant', replace_content: true, full_content: 'An allowed answer.',
            metadata: { content_moderation: { revision: '1' } },
        },
    ]);
    assert.equal(quiet.result.accumulated, 'An allowed answer.');
    assert.equal(quiet.failures.length, 0);
    assert.equal(quiet.terminal[0].event.blocked, undefined);

    const interrupted = await readFrames([
        { content: 'unclassified partial answer' },
        { error: 'The response could not be saved.', replace_content: true, full_content: '', partial_content: '' },
    ]);
    assert.equal(interrupted.result.accumulated, '');
    assert.equal(interrupted.failures.length, 1);

    const cancelledViolation = await readFrames([
        { content: 'unclassified partial answer' },
        { done: true, cancelled: true, blocked: true, role: 'safety', replace_content: true, full_content: removed },
    ]);
    assert.equal(cancelledViolation.cancellations.length, 0);
    assert.equal(cancelledViolation.terminal[0].accumulated, removed);

    assert.equal(resolveStreamContent({ full_content: '' }, 'must not survive'), '');
    assert.equal(resolveStreamContent({ replace_content: true }, 'must not survive'), '');
    assert.equal(resolveStreamContent({ partial_content: '' }, 'must not survive'), '');
    assert.equal(resolveStreamContent({}, 'legacy response'), 'legacy response');
    assert.equal(isReplyRemoved({ content_moderation: { removed: true } }), true);
    for (const metadata of [undefined, null, {}, { content_moderation: null }, { content_moderation: 'invalid' }]) {
        assert.equal(isReplyRemoved(metadata), false);
    }

    let updated;
    let created = false;
    dispatchCollaborationEvent({
        event_type: 'collaboration.message.updated',
        conversation_id: 'shared',
        payload: { message: { id: 'reply', conversation_id: 'shared', role: 'safety', content: removed } },
    }, {
        onMessageCreated: () => { created = true; },
        onMessageUpdated: (message) => { updated = message; },
    });
    assert.equal(created, false);
    assert.equal(updated.content, removed);
    assert.equal(updated.role, 'safety');
    console.log('V2 chat content replacement contracts passed.');
} finally {
    globalThis.fetch = originalFetch;
}
