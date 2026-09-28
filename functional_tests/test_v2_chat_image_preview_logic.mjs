// test_v2_chat_image_preview_logic.mjs
// Version: 0.261.144
// Implemented in: 0.261.144
// Pure helper coverage for v2 chat upload image preview decisions and local preview storage.

import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import './test_support/tsResolve.mjs';

const chatUploadsUrl = new URL('../application/v2_ui/src/lib/chatUploads.ts', import.meta.url);
const chatPreviewUrl = new URL('../application/v2_ui/src/lib/chatImagePreview.ts', import.meta.url);

const reactStub = `
    function unused() { throw new Error('A pure chat image helper accessed React.'); }
    export { unused as useEffect, unused as useMemo, unused as useState, unused as useSyncExternalStore };
`;
const orchestrationStoreStub = `
    export const useOrchestrationStore = {
        getState() { throw new Error('A pure chat upload helper accessed the orchestration store.'); },
        subscribe() { throw new Error('A pure chat upload helper subscribed to the orchestration store.'); },
    };
`;
const boundary = registerHooks({
    resolve(specifier, context, nextResolve) {
        if ((context.parentURL === chatUploadsUrl.href || context.parentURL === chatPreviewUrl.href)
            && specifier === 'react') {
            return {
                shortCircuit: true,
                url: `data:text/javascript,${encodeURIComponent(reactStub)}`,
            };
        }
        if (context.parentURL === chatUploadsUrl.href && specifier === '../stores/orchestrationStore') {
            return {
                shortCircuit: true,
                url: `data:text/javascript,${encodeURIComponent(orchestrationStoreStub)}`,
            };
        }
        return nextResolve(specifier, context);
    },
});

const {
    addChatUploadLocalPreview,
    chatUploadLocalPreviewStore,
    clearChatUploadLocalPreviews,
    getChatUploadLocalPreview,
    isBrowserRenderableImageFileName,
    isImageFileName,
    linkChatUploadLocalPreview,
    removeChatUploadLocalPreview,
} = await import(chatUploadsUrl);
const {
    HEIC_BROWSER_PREVIEW_HINT,
    buildChatImagePreviewUrl,
    chatImagePreviewStatusForResponse,
    imagePreviewHintForFileName,
    runChatImagePreview,
    workspaceAttachmentDocumentId,
    workspaceAttachmentPollOutcome,
    workspaceAttachmentScope,
} = await import(chatPreviewUrl);
boundary.deregister();

const checks = [];
const check = (name, run) => checks.push([name, run]);

check('image filename helpers match the server upload image extension set', () => {
    for (const name of ['a.jpg', 'a.jpeg', 'a.png', 'a.bmp', 'a.tiff', 'a.tif', 'a.heic', 'a.heif']) {
        assert.equal(isImageFileName(name), true, name);
    }
    for (const name of ['a.gif', 'a.webp', 'a.pdf', 'a', 'a.png.exe']) {
        assert.equal(isImageFileName(name), false, name);
    }
    for (const name of ['a.jpg', 'a.jpeg', 'a.png', 'a.bmp']) {
        assert.equal(isBrowserRenderableImageFileName(name), true, name);
    }
    for (const name of ['a.tif', 'a.tiff', 'a.heic', 'a.heif']) {
        assert.equal(isBrowserRenderableImageFileName(name), false, name);
    }
});

check('preview URL builder encodes message ids and variants', () => {
    assert.equal(
        buildChatImagePreviewUrl('conversation file/1', 'display'),
        '/api/image/conversation%20file%2F1?variant=display',
    );
    assert.equal(
        buildChatImagePreviewUrl('message:1'),
        '/api/image/message%3A1?variant=thumbnail',
    );
});

check('HTTP status mapping separates processing from terminal fallback states', () => {
    assert.equal(chatImagePreviewStatusForResponse(200), 'ready');
    assert.equal(chatImagePreviewStatusForResponse(409, { error_code: 'document_under_review' }), 'processing');
    assert.equal(chatImagePreviewStatusForResponse(409, { error_code: 'other_conflict' }), 'unavailable');
    assert.equal(chatImagePreviewStatusForResponse(503), 'processing');
    for (const status of [403, 404, 413, 415, 500]) {
        assert.equal(chatImagePreviewStatusForResponse(status), 'unavailable');
    }
});

check('HEIC hint is selected only for HEIC and HEIF filenames', () => {
    assert.equal(imagePreviewHintForFileName('front.heic'), HEIC_BROWSER_PREVIEW_HINT);
    assert.equal(imagePreviewHintForFileName('front.HEIF'), HEIC_BROWSER_PREVIEW_HINT);
    assert.equal(imagePreviewHintForFileName('front.jpg'), null);
});

check('workspace attachment helpers normalize document identity and scope', () => {
    assert.equal(workspaceAttachmentDocumentId({ document_id: ' doc-1 ' }), 'doc-1');
    assert.deepEqual(workspaceAttachmentScope({ scope: 'personal' }), { kind: 'personal', groupId: null });
    assert.deepEqual(workspaceAttachmentScope({ scope: 'group', group_id: 'group-a' }), {
        kind: 'group',
        groupId: 'group-a',
    });
    assert.equal(workspaceAttachmentScope({ scope: 'public' }), null);
});

check('poll outcome lets screening decide before processing progress', () => {
    const screened = (state, available, percentage = 100) => ({
        percentage_complete: percentage,
        content_screening: { state, available, finding_count: 0 },
    });
    assert.equal(workspaceAttachmentPollOutcome({ percentage_complete: 100 }), 'ready');
    assert.equal(workspaceAttachmentPollOutcome({ percentage_complete: 40 }), 'pending');
    assert.equal(workspaceAttachmentPollOutcome(screened('cleared', true)), 'ready');
    assert.equal(workspaceAttachmentPollOutcome(screened('cleared', true, 99)), 'pending');
    assert.equal(workspaceAttachmentPollOutcome(screened('scanning', false)), 'pending');
    assert.equal(workspaceAttachmentPollOutcome(screened('publishing', false)), 'pending');
    assert.equal(workspaceAttachmentPollOutcome(screened('pending_review', false, 99)), 'held');
    assert.equal(workspaceAttachmentPollOutcome(screened('scan_error', false)), 'held');
    assert.equal(workspaceAttachmentPollOutcome({ percentage_complete: 100, content_screening: null }), 'held');
    assert.equal(workspaceAttachmentPollOutcome({ status: 'Error: extraction failed' }), 'unavailable');
    assert.equal(
        workspaceAttachmentPollOutcome({ percentage_complete: 100, shared_approval_status: 'not_approved' }),
        'held',
    );
});

const jsonResponse = (status, body) => new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
});
const underReview = () => jsonResponse(409, { error_code: 'document_under_review' });
const imageResponse = () => new Response(new Blob(['png-bytes'], { type: 'image/png' }), { status: 200 });

function previewHarness({ previews, documents = null, clockStepMs = 2000 }) {
    const calls = { previews: 0, documents: 0, waits: 0, objectUrls: 0 };
    const updates = [];
    let clock = 0;
    const next = (sequence, index) => sequence[Math.min(index, sequence.length - 1)];
    const deps = {
        fetchPreview: async () => {
            const response = next(previews, calls.previews);
            calls.previews += 1;
            return typeof response === 'function' ? response() : response;
        },
        fetchDocument: documents
            ? async () => {
                const document = next(documents, calls.documents);
                calls.documents += 1;
                return document;
            }
            : null,
        wait: async () => {
            calls.waits += 1;
            clock += clockStepMs;
        },
        now: () => clock,
        createObjectUrl: () => {
            calls.objectUrls += 1;
            return `blob:preview-${calls.objectUrls}`;
        },
    };
    return { deps, calls, updates, publish: (update) => updates.push(update) };
}

const lastStatus = (updates) => updates.at(-1)?.status;

check('a ready record whose preview keeps refusing settles instead of looping', async () => {
    const harness = previewHarness({ previews: [underReview], documents: [{ percentage_complete: 100 }] });
    await runChatImagePreview(harness.deps, new AbortController().signal, harness.publish);
    assert.equal(lastStatus(harness.updates), 'unavailable');
    assert.equal(harness.calls.previews, 3);
    assert.equal(harness.calls.waits, 1);
});

check('a held screened record stops polling on the first read', async () => {
    const harness = previewHarness({
        previews: [underReview],
        documents: [{ percentage_complete: 99, content_screening: { state: 'pending_review', available: false } }],
    });
    await runChatImagePreview(harness.deps, new AbortController().signal, harness.publish);
    assert.equal(lastStatus(harness.updates), 'held');
    assert.equal(harness.updates.at(-1).reason, 'Unavailable pending review.');
    assert.equal(harness.calls.documents, 1);
    assert.equal(harness.calls.previews, 1);
});

check('screening in progress keeps polling within one deadline', async () => {
    const harness = previewHarness({
        previews: [underReview],
        documents: [{ percentage_complete: 100, content_screening: { state: 'scanning', available: false } }],
    });
    await runChatImagePreview(harness.deps, new AbortController().signal, harness.publish, { deadlineMs: 10_000 });
    assert.equal(lastStatus(harness.updates), 'held');
    assert.equal(harness.calls.documents, 5);
    assert.equal(harness.calls.previews, 1);
});

check('a processing upload retries the preview once it is ready', async () => {
    const harness = previewHarness({
        previews: [underReview, imageResponse],
        documents: [{ percentage_complete: 30 }, { percentage_complete: 100 }],
    });
    await runChatImagePreview(harness.deps, new AbortController().signal, harness.publish);
    assert.deepEqual(harness.updates.map((update) => update.status), ['loading', 'processing', 'ready']);
    assert.equal(harness.updates.at(-1).url, 'blob:preview-1');
    assert.equal(harness.calls.previews, 2);
});

check('a failed image body read publishes unavailable rather than staying on loading', async () => {
    const brokenBody = {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'image/png' }),
        blob: async () => {
            throw new TypeError('The connection was reset.');
        },
    };
    const harness = previewHarness({ previews: [brokenBody] });
    await runChatImagePreview(harness.deps, new AbortController().signal, harness.publish);
    assert.deepEqual(harness.updates.map((update) => update.status), ['loading', 'unavailable']);
    assert.equal(harness.calls.objectUrls, 0);
});

check('cancelling mid-poll resolves quietly and publishes nothing more', async () => {
    const controller = new AbortController();
    const harness = previewHarness({ previews: [underReview], documents: [{ percentage_complete: 10 }] });
    harness.deps.wait = async () => {
        controller.abort();
        throw new DOMException('Image preview polling cancelled.', 'AbortError');
    };
    await runChatImagePreview(harness.deps, controller.signal, harness.publish);
    assert.deepEqual(harness.updates.map((update) => update.status), ['loading', 'processing']);
});

check('previews without a pollable document and terminal refusals settle immediately', async () => {
    const orphan = previewHarness({ previews: [underReview] });
    await runChatImagePreview(orphan.deps, new AbortController().signal, orphan.publish);
    assert.equal(lastStatus(orphan.updates), 'unavailable');
    assert.equal(orphan.calls.previews, 1);

    const heic = previewHarness({ previews: [() => new Response('unsupported', { status: 415 })] });
    await runChatImagePreview(heic.deps, new AbortController().signal, heic.publish, { fileName: 'front.heic' });
    assert.equal(lastStatus(heic.updates), 'unavailable');
    assert.equal(heic.updates.at(-1).reason, HEIC_BROWSER_PREVIEW_HINT);
});

check('local preview store adds, aliases, removes and clears object URLs', () => {
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    const revoked = [];
    let sequence = 0;
    URL.createObjectURL = () => `blob:preview-${++sequence}`;
    URL.revokeObjectURL = (url) => revoked.push(url);
    try {
        clearChatUploadLocalPreviews();
        const first = addChatUploadLocalPreview(new File(['a'], 'house.png', { type: 'image/png' }), ['local-1']);
        assert.equal(first, 'blob:preview-1');
        assert.equal(getChatUploadLocalPreview('local-1'), 'blob:preview-1');
        linkChatUploadLocalPreview('local-1', ['message-1', 'document-1']);
        assert.equal(getChatUploadLocalPreview('message-1'), 'blob:preview-1');
        assert.equal(getChatUploadLocalPreview('document-1'), 'blob:preview-1');
        assert.equal(addChatUploadLocalPreview(new File(['b'], 'scan.tiff'), ['local-tiff']), null);
        removeChatUploadLocalPreview('message-1');
        assert.equal(getChatUploadLocalPreview('local-1'), null);
        assert.deepEqual(revoked, ['blob:preview-1']);
        assert.equal(typeof chatUploadLocalPreviewStore.subscribe, 'function');
    } finally {
        clearChatUploadLocalPreviews();
        URL.createObjectURL = originalCreate;
        URL.revokeObjectURL = originalRevoke;
    }
});

check('local preview store enforces an LRU cap and revokes evicted entries', () => {
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    const revoked = [];
    let sequence = 0;
    URL.createObjectURL = () => `blob:lru-${++sequence}`;
    URL.revokeObjectURL = (url) => revoked.push(url);
    try {
        clearChatUploadLocalPreviews();
        for (let index = 0; index < 25; index += 1) {
            addChatUploadLocalPreview(new File(['x'], `image-${index}.jpg`), [`key-${index}`]);
        }
        assert.equal(getChatUploadLocalPreview('key-0'), null);
        assert.equal(getChatUploadLocalPreview('key-24'), 'blob:lru-25');
        assert.ok(revoked.includes('blob:lru-1'));
    } finally {
        clearChatUploadLocalPreviews();
        URL.createObjectURL = originalCreate;
        URL.revokeObjectURL = originalRevoke;
    }
});

let failures = 0;
for (const [name, run] of checks) {
    try {
        await run();
        console.log(`  ok  ${name}`);
    } catch (error) {
        failures += 1;
        console.error(`  FAIL  ${name}`, error);
    }
}
console.log(`${checks.length - failures}/${checks.length} chat image preview checks passed.`);
process.exitCode = failures ? 1 : 0;
