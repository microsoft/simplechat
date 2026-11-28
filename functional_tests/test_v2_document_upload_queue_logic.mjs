// test_v2_document_upload_queue_logic.mjs
// Version: 0.261.492
// Implemented in: 0.261.492
// Executes the real V2 workspace upload queue (lib/documentUploadQueue.ts) and the real upload
// adapter (lib/documentOperations.ts) against controlled HTTP. A large selection is sent as a
// series of small requests, in order, each within the file and byte limits; what the server says
// about each request is merged; a request refused with per-file reasons does not stop the queue;
// a request with no confirmed outcome does, and the files never sent are counted.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const { PERSONAL_DOCUMENT_OPERATIONS } = await import('../application/v2_ui/src/lib/documentOperations.ts');
const {
    UPLOAD_BATCH_MAX_BYTES, UPLOAD_BATCH_MAX_FILES, planUploadBatches, uploadInBatches,
} = await import('../application/v2_ui/src/lib/documentUploadQueue.ts');

const originalFetch = globalThis.fetch;
let checks = 0;

async function check(name, run) {
    await run();
    checks += 1;
    console.log(`ok ${name}`);
}

function sized(count, size = 1024) {
    return Array.from({ length: count }, (_, index) => ({ name: `file-${index + 1}.txt`, size }));
}

function receipt(batch) {
    return {
        document_ids: batch.map((file) => `id-${file.name}`),
        processed_filenames: batch.map((file) => file.name),
        errors: [],
    };
}

try {
    await check('250 files become ordered requests within the file limit', async () => {
        const files = sized(250);
        const batches = planUploadBatches(files);
        assert.equal(batches.length, Math.ceil(250 / UPLOAD_BATCH_MAX_FILES));
        assert.ok(batches.every((batch) => batch.length >= 1 && batch.length <= UPLOAD_BATCH_MAX_FILES));
        assert.deepEqual(batches.flat(), files);
    });

    await check('a request never exceeds the byte limit unless one file does alone', async () => {
        const megabyte = 1024 * 1024;
        const files = [
            { name: 'a', size: 30 * megabyte }, { name: 'b', size: 30 * megabyte },
            { name: 'huge', size: UPLOAD_BATCH_MAX_BYTES + 1 }, { name: 'c', size: megabyte }, { name: 'd', size: megabyte },
        ];
        const batches = planUploadBatches(files);
        assert.deepEqual(batches.map((batch) => batch.map((file) => file.name)), [['a'], ['b'], ['huge'], ['c', 'd']]);
        assert.deepEqual(planUploadBatches([]), []);
        assert.deepEqual(planUploadBatches(sized(3), { maxFiles: 0, maxBytes: 1 }).map((batch) => batch.length), [1, 1, 1]);
    });

    await check('every request is sent one after another and the answers are merged', async () => {
        const files = sized(23);
        let inFlight = 0;
        const sizes = [];
        const progress = [];
        const outcome = await uploadInBatches(files, async (batch) => {
            inFlight += 1;
            assert.equal(inFlight, 1, 'requests must not overlap');
            await new Promise((resolve) => setTimeout(resolve, 1));
            inFlight -= 1;
            sizes.push(batch.length);
            return receipt(batch);
        }, { onProgress: (state) => progress.push(state.completed) });
        assert.deepEqual(sizes, [5, 5, 5, 5, 3]);
        assert.deepEqual(progress, [5, 10, 15, 20, 23]);
        assert.deepEqual(outcome.processed_filenames, files.map((file) => file.name));
        assert.equal(outcome.document_ids.length, 23);
        assert.deepEqual([outcome.errors, outcome.unsent, outcome.stopped], [[], 0, null]);
    });

    await check('a request refused with per-file reasons does not stop the queue', async () => {
        let request = 0;
        const outcome = await uploadInBatches(sized(12), async (batch) => {
            request += 1;
            if (request === 2) return { document_ids: [], processed_filenames: [], errors: batch.map((file) => `${file.name}: refused`) };
            return receipt(batch);
        });
        assert.equal(request, 3);
        assert.equal(outcome.document_ids.length, 7);
        assert.equal(outcome.errors.length, 5);
        assert.deepEqual([outcome.unsent, outcome.stopped], [0, null]);
    });

    await check('a request with no confirmed outcome stops the queue and counts what was never sent', async () => {
        let request = 0;
        const outcome = await uploadInBatches(sized(22), async (batch) => {
            request += 1;
            if (request === 2) throw new Error('Connection lost.');
            return receipt(batch);
        });
        assert.equal(request, 2);
        assert.equal(outcome.document_ids.length, 5);
        assert.equal(outcome.unsent, 12);
        assert.equal(outcome.stopped, 'Connection lost.');
        assert.equal(outcome.errors.length, 1);
        assert.match(outcome.errors[0], /^file-6\.txt, .*file-10\.txt: Connection lost\.$/);
    });

    await check('the queue stops before a request when asked not to continue', async () => {
        let request = 0;
        const outcome = await uploadInBatches(sized(15), async (batch) => {
            request += 1;
            return receipt(batch);
        }, { shouldContinue: () => request < 1 });
        assert.equal(request, 1);
        assert.deepEqual([outcome.document_ids.length, outcome.unsent], [5, 10]);
        assert.ok(outcome.stopped);
    });

    await check('the real personal adapter carries 120 files as 24 requests of 5', async () => {
        const posts = [];
        globalThis.fetch = async (path, options = {}) => {
            const url = new URL(String(path), 'http://fixture.test');
            const names = options.body.getAll('file').map((file) => file.name);
            posts.push({ path: url.pathname, method: options.method, names });
            return new Response(JSON.stringify({
                message: 'ok', document_ids: names.map((name) => `id-${name}`), processed_filenames: names, errors: [],
            }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        };
        const files = Array.from({ length: 120 }, (_, index) => new File(['x'], `doc-${index + 1}.txt`, { type: 'text/plain' }));
        const outcome = await uploadInBatches(files, (batch) => PERSONAL_DOCUMENT_OPERATIONS.upload(batch));
        assert.equal(posts.length, 24);
        assert.ok(posts.every((post) => post.path === '/api/documents/upload' && post.method === 'POST' && post.names.length === 5));
        assert.deepEqual(posts.flatMap((post) => post.names), files.map((file) => file.name));
        assert.deepEqual([outcome.document_ids.length, outcome.errors.length, outcome.unsent], [120, 0, 0]);
    });

    console.log(`${checks} document upload queue checks passed.`);
} finally {
    globalThis.fetch = originalFetch;
}
