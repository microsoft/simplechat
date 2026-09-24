// test_v2_api_error_message_logic.mjs
// Version: 0.261.163
// Implemented in: 0.261.163
// Executes the real V2 API client (lib/apiClient.ts) against controlled HTTP and pins the message
// an ApiError carries. A coded failure -- a bare lowercase machine code in `error` with a sentence
// in `message` -- surfaces the sentence, and its payload keeps the code for callers. Every other
// body keeps its existing precedence: `error`, then `message`, then the status.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const { ApiError, requestWithStatus, uploadFileWithStatus } = await import('../application/v2_ui/src/lib/apiClient.ts');

const PROPAGATION = 'The operation changed stored data, but required cleanup or propagation is incomplete. Refresh before retrying.';
const originalFetch = globalThis.fetch;
let answer = () => new Response(null, { status: 204 });
let checks = 0;

globalThis.fetch = async () => answer();

function json(body, status) {
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

async function failure(send) {
    try {
        await send();
    } catch (error) {
        assert.ok(error instanceof ApiError, `Expected an ApiError, got ${error}`);
        return error;
    }
    assert.fail('The request unexpectedly succeeded.');
}

async function check(name, run) {
    await run();
    checks += 1;
    console.log(`ok ${name}`);
}

async function messageFor(body, status = 500) {
    answer = () => json(body, status);
    return (await failure(() => requestWithStatus('/api/fixture', { method: 'PATCH', body: {} }))).message;
}

try {
    await check('a coded failure shows its sentence and keeps its code in the payload', async () => {
        const body = {
            error: 'document_propagation_incomplete', message: PROPAGATION, repair_required: true,
            document_id: 'same-document', group_id: 'group-a',
        };
        answer = () => json(body, 500);
        const error = await failure(() => requestWithStatus('/api/fixture', { method: 'PATCH', body: {} }));
        assert.equal(error.message, PROPAGATION);
        assert.equal(error.status, 500);
        assert.deepEqual(error.payload, body);
    });

    await check('every lowercase single-token code counts, with or without underscores and digits', async () => {
        assert.equal(await messageFor({ error: 'state_conflict', message: 'The document state changed.' }, 409), 'The document state changed.');
        assert.equal(await messageFor({ error: 'unauthorized', message: 'Sign in again.' }, 401), 'Sign in again.');
        assert.equal(await messageFor({ error: 'm365_consent2', message: 'Reconnect Microsoft 365.' }, 403), 'Reconnect Microsoft 365.');
    });

    await check('a sentence in `error` is still shown, even beside a message', async () => {
        assert.equal(await messageFor({ error: 'Document not found or access denied.' }, 404), 'Document not found or access denied.');
        assert.equal(
            await messageFor({ error: 'You do not have access to the selected group.', message: 'Other text.' }, 403),
            'You do not have access to the selected group.',
        );
        assert.equal(
            await messageFor({ error: 'The group changed while your request was being saved. Try again.', error_code: 'group_write_conflict' }, 409),
            'The group changed while your request was being saved. Try again.',
        );
    });

    await check('only a bare lowercase token is a code: other shapes keep `error`', async () => {
        for (const error of ['Invalid_etag', 'invalid-etag', 'INVALID_ETAG', '_leading', '1st_code', 'two words', 'code.']) {
            assert.equal(await messageFor({ error, message: 'A sentence.' }), error, error);
        }
    });

    await check('a code without a usable sentence is shown as it is', async () => {
        assert.equal(await messageFor({ error: 'state_conflict' }, 409), 'state_conflict');
        assert.equal(await messageFor({ error: 'state_conflict', message: '' }, 409), 'state_conflict');
        assert.equal(await messageFor({ error: 'state_conflict', message: '   ' }, 409), 'state_conflict');
        assert.equal(await messageFor({ error: 'state_conflict', message: 42 }, 409), 'state_conflict');
    });

    await check('a message alone, and a body with neither, keep their existing text', async () => {
        assert.equal(await messageFor({ message: 'Only a message.' }, 400), 'Only a message.');
        assert.equal(await messageFor({ error: '', message: 'Only a message.' }, 400), 'Only a message.');
        assert.equal(await messageFor({}, 502), 'Request failed with status 502');
        assert.equal(await messageFor([], 502), 'Request failed with status 502');
        assert.equal(await messageFor(null, 503), 'Request failed with status 503');
    });

    await check('a text body keeps its text and its payload', async () => {
        answer = () => new Response('<html>Sign in</html>', { status: 401, headers: { 'Content-Type': 'text/html' } });
        const error = await failure(() => requestWithStatus('/api/fixture'));
        assert.equal(error.message, '<html>Sign in</html>');
        assert.equal(error.payload, '<html>Sign in</html>');
    });

    await check('uploads read their refusals the same way', async () => {
        const form = new FormData();
        form.append('file', new File(['bytes'], 'notes.txt'));
        answer = () => json({ error: 'document_propagation_incomplete', message: PROPAGATION }, 500);
        assert.equal((await failure(() => uploadFileWithStatus('/api/fixture/upload', form))).message, PROPAGATION);
        answer = () => json({ error: 'This file type is not allowed.' }, 400);
        assert.equal((await failure(() => uploadFileWithStatus('/api/fixture/upload', form))).message, 'This file type is not allowed.');
    });

    console.log(`${checks} API error message checks passed.`);
} finally {
    globalThis.fetch = originalFetch;
}
