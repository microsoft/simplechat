// test_v2_action_personal_credentials.mjs
// Version: 0.261.348
// Implemented in: 0.261.333
// Continuation recovery regressions added in: 0.261.343
// Exercises real authoring, safe DTO projection, credential transport, and stream waiting.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import './test_support/tsResolve.mjs';

const {
    actionAuthModes, actionForSave, changeActionAuth, changeActionCredentialSource,
    changeActionField, changeActionType, createActionDraft, validateActionDraft,
} = await import('../application/v2_ui/src/lib/workspaceActionLogic.ts');
const { buildEditorWrite, EDITOR_SECRET_MASK } = await import('../application/v2_ui/src/lib/workspaceAuthoring.ts');
const { buildActionConnectionPayload } = await import('../application/v2_ui/src/lib/workspaceActionServices.ts');
const { readCredentialRequest, ACTION_CREDENTIAL_EVENT } = await import('../application/v2_ui/src/lib/actionCredentialEvents.ts');
const { consumeCredentialChatResponse } = await import('../application/v2_ui/src/lib/sse.ts');
const { saveActionCredentials, openCredentialContinuation, fetchActionCredentialRequest } = await import('../application/v2_ui/src/lib/actionCredentials.ts');
const { runOrchestration } = await import('../application/v2_ui/src/lib/orchestration.ts');
const read = (name) => JSON.parse(fs.readFileSync(new URL(
    `../application/single_app/static/json/schemas/${name}`, import.meta.url,
), 'utf8'));
const definition = {
    type: 'yamcs', display: 'Yamcs',
    allowed_auth_types: read('yamcs.definition.json').allowedAuthTypes,
    additional_fields_schema: read('yamcs_plugin.additional_settings.schema.json'),
    metadata_schema: {},
};
function draft() {
    const initial = changeActionType(createActionDraft(), definition);
    return {
        ...initial,
        id: 'global-yamcs', name: 'shared_yamcs', displayName: 'Shared Yamcs',
        description: 'Mission telemetry', endpoint: 'https://mission.example.test', is_global: true,
        additionalFields: { ...initial.additionalFields, server_url: 'https://mission.example.test', instance: 'simulator' },
    };
}
function method(action, value) {
    return changeActionAuth(action, actionAuthModes(action.type, definition.allowed_auth_types).find((mode) => mode.value === value));
}
const original = draft();
original.auth = { type: 'username_password', identity: 'shared-principal', key: EDITOR_SECRET_MASK };
original.additionalFields.auth_method = 'username_password';
const resource = { record: structuredClone(original), revision: 'v1', secret_paths: ['/auth/key'], read_only: false };
let personal = changeActionCredentialSource(original, 'service', true);
assert.equal(personal.auth.identity, '');
assert.equal(personal.auth.key, '');
assert.equal(original.auth.key, EDITOR_SECRET_MASK, 'source switching must not mutate the loaded record');
assert.deepEqual(personal.credential_requirements.slots.service, { source: 'personal', auth_type: 'username_password' });
let write = buildEditorWrite(actionForSave(personal), resource);
assert.ok(write.clear_secret_paths.includes('/auth/key'), 'personal source explicitly clears the old shared secret');
assert.deepEqual(validateActionDraft(personal, definition, resource), {});
personal = method(personal, 'bearer_token');
assert.equal(personal.credential_requirements.slots.service.auth_type, 'bearer_token');
personal = method(personal, 'none');
assert.equal(personal.credential_requirements, undefined);
personal = changeActionField(personal, '/additionalFields/enable_basic_auth', true);
personal = changeActionCredentialSource(personal, 'proxy', true);
assert.equal(personal.additionalFields.basic_auth_username, '');
assert.deepEqual(validateActionDraft(personal, definition), {});
personal = method(personal, 'api_key');
personal = changeActionCredentialSource(personal, 'service', true);
assert.equal(Object.keys(personal.credential_requirements.slots).length, 2);
assert.deepEqual(validateActionDraft(personal, definition), {});
assert.throws(() => buildActionConnectionPayload(personal, null, { global: true }), /use it in chat/);
assert.ok(validateActionDraft(method(personal, 'username_password'), definition)['/additionalFields/enable_basic_auth']);
const shared = changeActionCredentialSource(changeActionCredentialSource(personal, 'service', false), 'proxy', false);
write = buildEditorWrite(actionForSave(shared), {
    record: personal, revision: 'v2', secret_paths: [], read_only: false,
});
assert.ok(write.removed_paths.includes('/credential_requirements'));
const changedType = changeActionType(personal, {
    type: 'math', display: 'Math', allowed_auth_types: ['NoAuth'], additional_fields_schema: {}, metadata_schema: {},
});
assert.equal(Object.hasOwn(changedType, 'credential_requirements'), false);

const request = {
    id: 'request-1', etag: 'etag-1', conversation_id: 'conversation-1',
    action_name: '<script>not markup</script>', destination_label: 'Mission server',
    status: 'pending', reason: 'missing',
    requirements: [{ slot: 'proxy', auth_type: 'username_password', label: 'Proxy sign-in' }],
    identities: [{ id: 'identity-1', name: 'My proxy', auth_type: 'username_password', password: 'never-store' }],
    credentials: { secret: 'never-store' }, username: 'never-store',
};
const safe = readCredentialRequest(request);
assert.equal(JSON.stringify(safe).includes('never-store'), false);
assert.equal(readCredentialRequest({ ...request, conversation_kind: 'collaborative' }).conversation_kind, 'collaborative');
assert.throws(() => readCredentialRequest({ ...request, conversation_kind: 'source' }), /unsupported/);
assert.throws(() => readCredentialRequest({ ...request, requirements: [{ slot: 'unknown', auth_type: 'api_key' }] }), /unsupported/);
const windowBefore = globalThis.window;
const fetchBefore = globalThis.fetch;
try {
    globalThis.window = new EventTarget();
    let published;
    window.addEventListener(ACTION_CREDENTIAL_EVENT, (event) => { published = event.detail; });
    let done = 0;
    let streamErrors = 0;
    const response = new Response(`event: action_credentials_required\ndata: ${JSON.stringify({ credential_request: request })}\n\n`, {
        headers: { 'Content-Type': 'text/event-stream' },
    });
    const result = await consumeCredentialChatResponse(response, {
        onDone: () => { done += 1; }, onError: () => { streamErrors += 1; },
    });
    assert.equal(result.credentialWaiting, true);
    assert.equal(result.errored, false);
    assert.equal(done, 0, 'waiting must never manufacture a completed assistant message');
    assert.equal(streamErrors, 0);
    assert.deepEqual(published, safe);
    const calls = [];
    globalThis.fetch = async (url, options) => {
        calls.push({ url, options });
        return new Response(JSON.stringify({ csrf_token: 'fixture-csrf-token', credential_request: { ...safe, status: 'ready', etag: 'etag-2' } }), {
            headers: { 'Content-Type': 'application/json' },
        });
    };
    const ready = await saveActionCredentials(safe, [{
        slot: 'proxy', name: 'Private proxy', credentials: { auth_type: 'username_password', username: 'private-user', password: 'private-password' },
    }]);
    assert.equal(ready.status, 'ready');
    const submitted = calls.find((call) => call.url.endsWith('/submit'));
    assert.ok(submitted);
    assert.equal(submitted.options.headers['X-CSRFToken'], 'fixture-csrf-token');
    await openCredentialContinuation(ready);
    const continued = calls.find((call) => call.url.endsWith('/continue'));
    assert.deepEqual(JSON.parse(continued.options.body), { expected_etag: 'etag-2' });
    assert.equal(continued.options.headers['X-CSRFToken'], 'fixture-csrf-token');
    assert.equal(continued.options.body.includes('private'), false, 'continuation sends only its fence, never secrets or a new question');
    const refreshed = await fetchActionCredentialRequest(safe);
    assert.equal(refreshed.etag, 'etag-2');
    assert.equal(calls.at(-1).options.cache, 'no-store');
    assert.equal(calls.at(-1).options.method, 'GET', 'refresh must read the server, not submit credentials');
    for (const change of [{ id: 'foreign' }, { conversation_id: 'foreign' }, { conversation_kind: 'collaborative' },
        { run_id: 'foreign' }, { turn_id: 'foreign' }]) {
        globalThis.fetch = async () => new Response(JSON.stringify({
            credential_request: { ...safe, ...change }, csrf_token: 'wrong-work',
        }), { headers: { 'Content-Type': 'application/json' } });
        await assert.rejects(fetchActionCredentialRequest(safe), /no longer belongs/);
    }
    let waiting = 0;
    let runDone = 0;
    const runRequest = { ...safe, run_id: 'run-1', turn_id: 'turn-1', status: 'ready' };
    globalThis.fetch = async (url, options) => {
        calls.push({ url, options });
        return new Response(`data: ${JSON.stringify({
            type: 'action_credentials_required', run_id: 'run-1', conversation_id: safe.conversation_id,
            credential_request: runRequest,
        })}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } });
    };
    const runResult = await runOrchestration({
        run_id: 'run-1', plan_id: 'plan-1', conversation_id: safe.conversation_id,
    }, { onWaiting: () => { waiting += 1; }, onDone: () => { runDone += 1; } }, undefined, runRequest);
    assert.equal(runResult.waiting, true);
    assert.equal(runResult.transportUnknown, undefined);
    assert.equal(waiting, 1);
    assert.equal(runDone, 0);
    assert.ok(calls.at(-1).url.endsWith('/request-1/continue'));
    assert.deepEqual(JSON.parse(calls.at(-1).options.body), { expected_etag: safe.etag });
} finally {
    globalThis.window = windowBefore;
    globalThis.fetch = fetchBefore;
}
console.log('Personal credential authoring, projection, transport, and stream checks passed.');
