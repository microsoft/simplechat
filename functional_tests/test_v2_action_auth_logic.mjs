// test_v2_action_auth_logic.mjs
// Version: 0.261.107
// Implemented in: 0.261.107
// Executes the real v2 manifest, identity, API, and private non-persisted controller logic.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

const {
    ACTION_AUTH_PROFILES, actionAuthPreflightBody, actionAuthAgentFromMetadata, normalizeActionAuthState,
    saveActionAuthCredentials, actionAuthErrorMessage, isActionCredentialsRequired, normalizeActionCredentialsControl,
} = await import('../application/v2_ui/src/lib/actionAuth.ts');
const { ActionAuthController } = await import('../application/v2_ui/src/lib/actionAuthController.ts');
const {
    changeActionType, createActionDraft, changeActionCredentialSource, changeActionCredentialProfile,
    actionForSave, validateActionDraft, canAuthorPersonalActionCredentials,
} = await import('../application/v2_ui/src/lib/workspaceActionLogic.ts');
const { EDITOR_SECRET_MASK, buildEditorWrite } = await import('../application/v2_ui/src/lib/workspaceAuthoring.ts');
const {
    adminYamcsResource, buildAdminYamcsPayload, fetchAdminYamcsType, globalYamcsActionReference, testAdminYamcsAction,
} = await import('../application/v2_ui/src/lib/adminYamcsActions.ts');
const { buildActionConnectionPayload } = await import('../application/v2_ui/src/lib/workspaceActionServices.ts');
const { saveActionConfiguration } = await import('../application/v2_ui/src/lib/workspaceAuthoringApi.ts');
const { personalActionIdentityWrite, actionIdentityDetails } = await import('../application/v2_ui/src/lib/workspaceActionIdentity.ts');
const { ApiError } = await import('../application/v2_ui/src/lib/apiClient.ts');

const definition = {
    type: 'yamcs', display: 'Yamcs', allowed_auth_types: ['username_password', 'basic', 'key', 'NoAuth', 'identity'],
    additional_fields_schema: {}, metadata_schema: {},
};
const identity = {
    id: 'owned-identity', name: 'Yamcs', usage_contexts: ['action'], metadata: { keep: true },
    credentials: { auth_type: 'username_password', username: 'synthetic-user', password_stored: true, password: 'Stored_In_KeyVault' },
};
function draft() {
    const value = changeActionType(createActionDraft(), definition);
    return {
        ...value, id: 'global-yamcs-id', name: 'yamcs', displayName: 'Yamcs telemetry',
        endpoint: 'https://yamcs.example.test/mission',
        auth: { type: 'username_password', identity: 'old-username', key: 'old-action-secret' },
        additionalFields: { ...value.additionalFields, instance: 'simulator', future_config: { enabled: false, limit: 0 } },
        metadata: { future: ['retained'] },
    };
}
function requirement(extra = {}) {
    return {
        id: 'requirement-1', action_id: 'global-yamcs-id', action_name: 'Mission telemetry',
        identity_name: 'Yamcs', profile: 'yamcs_login', auth_type: 'username_password',
        destination: 'https://yamcs.example.test/mission', reason: 'missing', identities: [],
        ...extra,
    };
}
function required(extra = {}) {
    return {
        status: 'credentials_required', request_id: 'request-1', uses_personal_credentials: true,
        shared_conversation: false, sharing_notice: null, requirements: [requirement()], ...extra,
    };
}
function ready(extra = {}) {
    return { ...required(), status: 'ready', requirements: [], ...extra };
}
const actionRef = globalYamcsActionReference(draft());
const input = {
    agent_info: { id: 'agent-1', name: 'mission', display_name: 'Mission', is_global: true },
    conversation_id: 'visible-conversation', conversation_kind: 'personal',
};
const nextTick = () => new Promise((resolve) => setImmediate(resolve));

test('only explicit global Yamcs authoring may opt into personal credentials', () => {
    for (const scope of ['personal', 'group']) {
        assert.equal(canAuthorPersonalActionCredentials({ ...draft(), is_global: true }, scope), false);
        assert.throws(() => changeActionCredentialSource(draft(), 'current_user', scope), /global Yamcs/);
    }
    assert.throws(() => changeActionCredentialSource({ ...draft(), type: 'openapi' }, 'current_user', 'global'), /global Yamcs/);
    const perUser = changeActionCredentialSource(draft(), 'current_user', 'global');
    assert.ok(validateActionDraft(perUser, definition)['/credential_requirement']);
    assert.deepEqual(validateActionDraft(perUser, definition, null, 'global'), {});
    assert.throws(() => saveActionConfiguration(perUser, null), /global Yamcs/);
    assert.throws(() => buildActionConnectionPayload(perUser, null), /My Workspace/);
});

test('profiles map native protocol separately from identity type and erase contradictory sources', () => {
    for (const [profile, adapter] of Object.entries(ACTION_AUTH_PROFILES)) {
        let value = {
            ...draft(), identity_id: 'old-global-identity',
            additionalFields: { ...draft().additionalFields, identity_auth_type: 'username_password', username: 'stale', password: 'stale' },
        };
        value = changeActionCredentialProfile(changeActionCredentialSource(value, 'current_user', 'global'), profile, 'global');
        assert.deepEqual(value.auth, { type: adapter.nativeAuthType });
        assert.equal(value.additionalFields.auth_method, adapter.authMethod);
        assert.equal(value.identity_id, undefined);
        assert.equal(value.additionalFields.username, undefined);
        assert.equal(value.additionalFields.password, undefined);
        assert.deepEqual(value.additionalFields.future_config, { enabled: false, limit: 0 });
        assert.deepEqual(validateActionDraft(value, definition, null, 'global'), {});
        assert.equal(JSON.stringify(value).includes('old-action-secret'), false);
        assert.equal(JSON.stringify(value).includes('old-username'), false);
        const configured = changeActionCredentialSource(value, 'configured', 'global');
        assert.equal(configured.credential_requirement, undefined);
        assert.equal(configured.auth.key, undefined);
        assert.ok(validateActionDraft(configured, definition, null, 'global')['/auth/key']);
    }
    assert.equal(ACTION_AUTH_PROFILES.http_basic.authType, ACTION_AUTH_PROFILES.yamcs_login.authType);
    assert.notEqual(ACTION_AUTH_PROFILES.http_basic.nativeAuthType, ACTION_AUTH_PROFILES.yamcs_login.nativeAuthType);
});

test('renaming a requirement preserves its stable id in global and read-only catalog round trips', () => {
    const value = changeActionCredentialSource(draft(), 'current_user', 'global');
    value.credential_requirement.id = 'server-stable-requirement';
    const original = { record: structuredClone(value), revision: '', read_only: true, secret_paths: [] };
    const edited = { ...value, credential_requirement: { ...value.credential_requirement, identity_name: 'Mission control' } };
    const write = buildEditorWrite(actionForSave(edited), original);
    assert.deepEqual(write.updates, { credential_requirement: { identity_name: 'Mission control' } });
    assert.deepEqual(write.removed_paths, []);
    assert.equal(edited.credential_requirement.id, 'server-stable-requirement');
    assert.equal(buildAdminYamcsPayload(edited, { ...original, read_only: false }).credential_requirement.id, 'server-stable-requirement');
    assert.throws(() => saveActionConfiguration(edited, original), /read-only/);
});

test('personal mode validates HTTPS, certificate verification, and secret-free metadata', () => {
    const value = changeActionCredentialSource(draft(), 'current_user', 'global');
    for (const endpoint of ['http://yamcs.example.test', 'https://user:pass@yamcs.example.test', 'https://yamcs.example.test?token=x']) {
        assert.ok(validateActionDraft({ ...value, endpoint }, definition, null, 'global')['/endpoint']);
    }
    assert.ok(validateActionDraft({ ...value, additionalFields: { ...value.additionalFields, tls_verify: false } }, definition, null, 'global')['/additionalFields/tls_verify']);
    assert.ok(validateActionDraft({ ...value, credential_requirement: { ...value.credential_requirement, username: 'not-allowed' } }, definition, null, 'global')['/credential_requirement']);
    assert.ok(validateActionDraft({ ...value, auth: { type: 'basic' } }, definition, null, 'global')['/auth/type']);
});

test('admin legacy edits keep every hidden setting and send only owned stored-secret markers', () => {
    const raw = draft();
    raw.auth.type = 'basic';
    raw.additionalFields.auth_method = 'http_basic';
    raw.auth.key = 'Stored_In_KeyVault';
    raw.additionalFields.hidden_secret = 'Stored_In_KeyVault';
    raw.future_root = { enabled: false };
    const original = adminYamcsResource(raw);
    assert.equal(original.record.auth.key, EDITOR_SECRET_MASK);
    const payload = buildAdminYamcsPayload({ ...original.record, description: 'Renamed safely' }, original);
    assert.equal(payload.auth.key, 'Stored_In_KeyVault');
    assert.equal(payload.auth.type, 'basic');
    assert.equal(payload.additionalFields.auth_method, 'http_basic');
    assert.equal(payload.additionalFields.hidden_secret, 'Stored_In_KeyVault');
    assert.deepEqual(payload.metadata, raw.metadata);
    assert.deepEqual(payload.future_root, raw.future_root);
    assert.throws(() => buildAdminYamcsPayload({ ...draft(), auth: { type: 'key', key: EDITOR_SECRET_MASK } }, null), /stored value/);
});

test('manual identity setup works without personal action-authoring permission and never echoes a mask', () => {
    const values = { username: 'synthetic-user', password: 'synthetic-private-password' };
    assert.deepEqual(personalActionIdentityWrite(' Yamcs ', '', 'username_password', values, null), {
        name: 'Yamcs', description: '', credentials: { auth_type: 'username_password', ...values },
        provider: 'generic', usage_contexts: ['action'],
    });
    const kept = personalActionIdentityWrite('Renamed', '', 'username_password', { username: 'synthetic-user', password: '' }, identity);
    assert.deepEqual(kept.credentials, { auth_type: 'username_password', username: 'synthetic-user' });
    assert.equal(Object.hasOwn(kept, 'metadata'), false);
    assert.equal(Object.hasOwn(kept, 'usage_contexts'), false);
    assert.equal(actionIdentityDetails({ ...identity, usage_contexts: ['file_sync'] }).supported, false);
    assert.equal(actionIdentityDetails({ ...identity, provider: 'generic', usage_contexts: undefined }).supported, true);
    assert.throws(() => personalActionIdentityWrite('Yamcs', '', 'bearer_token', { secret: '' }, identity), /new credential/);
});

test('state and preflight are allowlisted, with no model-defined fields or conversation text', () => {
    const body = actionAuthPreflightBody({ ...input, message: 'NEVER-SEND-PROMPT', credentials: { secret: 'NEVER-SEND-SECRET' }, user_id: 'other-user',
        agent_info: { ...input.agent_info, username: 'not-a-selection', instructions: 'not-in-preflight' } });
    assert.deepEqual(Object.keys(body).sort(), ['agent_info', 'conversation_id', 'conversation_kind']);
    assert.equal(JSON.stringify(body).includes('NEVER-SEND'), false);
    assert.equal(JSON.stringify(body).includes('not-in-preflight'), false);
    const state = normalizeActionAuthState(required({
        username: 'NEVER-STORE', credentials: { secret: 'NEVER-STORE' }, original_message: 'NEVER-STORE',
        requirements: [requirement({
            fields: [{ name: 'model_requested_password', type: 'javascript' }], secret: 'NEVER-STORE',
            identities: [{ id: 'own-id', name: 'Yamcs', auth_type: 'username_password', password: 'NEVER-STORE' }],
        })],
    }));
    assert.equal(JSON.stringify(state).includes('NEVER-STORE'), false);
    assert.equal(Object.hasOwn(state.requirements[0], 'fields'), false);
    assert.throws(() => normalizeActionAuthState(required({ requirements: [requirement({ profile: 'model_defined' })] })));
    assert.throws(() => normalizeActionAuthState(required({ requirements: [requirement({ auth_type: 'api_key' })] })));
    assert.throws(() => normalizeActionAuthState(ready({ request_id: null })));
    assert.throws(() => normalizeActionAuthState(ready({ requirements: [requirement()] })));
    assert.deepEqual(actionAuthAgentFromMetadata({ agent_selection: { selected_agent: 'mission', agent_id: 'a1', is_global: true, user_id: 'owner-not-actor' } }),
        { id: 'a1', name: 'mission', display_name: 'mission', is_global: true, is_group: false, group_id: null, group_name: null });
});

test('both control discriminators preserve only the explicit execution flag and safe identifiers', () => {
    for (const discriminator of ['type', 'error_code']) {
        for (const started of [true, false]) {
            const payload = {
                [discriminator]: 'action_credentials_required', request_id: 'control-request', execution_started: started,
                action_ref: actionRef,
                username: 'NEVER-STORE', content: 'NEVER-STORE', auth_url: '/login',
            };
            assert.equal(isActionCredentialsRequired(payload), true);
            assert.deepEqual(normalizeActionCredentialsControl(payload), {
                type: 'action_credentials_required', error_code: 'action_credentials_required',
                request_id: 'control-request', action_ref: actionRef, execution_started: started,
            });
        }
    }
    assert.equal(isActionCredentialsRequired({ type: 'thought' }), false);
    assert.equal(normalizeActionCredentialsControl({
        type: 'action_credentials_required', execution_started: 'false',
    }).execution_started, undefined);
    assert.equal(normalizeActionCredentialsControl({
        type: 'action_credentials_required', action_ref: 'https://unapproved.example.test',
    }).action_ref, undefined);
});

test('missing requirements defer, duplicate requests cannot replace continuations, and cancellation is final', async () => {
    const cancellations = [];
    const controller = new ActionAuthController({
        preflight: async () => required(), read: async () => ready(),
        cancel: async (id) => { cancellations.push(id); },
    });
    let continued = 0;
    const first = controller.request(input, { surface: 'chat', isCurrent: () => true }).then((receipt) => { if (receipt) continued += 1; return receipt; });
    await nextTick();
    assert.equal(controller.getSnapshot().state.status, 'credentials_required');
    assert.equal(continued, 0);
    assert.equal(await controller.request(input, { surface: 'chat', isCurrent: () => true }), null);
    const submission = controller.startSubmission();
    assert.ok(submission);
    assert.equal(controller.startSubmission(), null);
    controller.cancel();
    controller.completeSubmission(submission, ready());
    assert.equal(await first, null);
    assert.equal(controller.getSnapshot(), null);
    assert.equal(continued, 0);
    assert.deepEqual(cancellations, ['request-1']);
});

test('shared ready identity still requires a private explicit notice before any continuation', async () => {
    const controller = new ActionAuthController({
        preflight: async () => ready({ shared_conversation: true }),
        read: async () => ready({ shared_conversation: true }), cancel: async () => {},
    });
    let sent = false;
    const pending = controller.request({ ...input, conversation_kind: 'collaboration' }, { surface: 'chat', isCurrent: () => true }).then((receipt) => { sent = Boolean(receipt); });
    await nextTick();
    assert.equal(sent, false);
    assert.match(controller.getSnapshot().state.sharing_notice, /message and returned data/);
    controller.continue();
    assert.equal(sent, false);
    controller.acknowledgeSharing(true);
    controller.continue();
    controller.continue();
    await pending;
    assert.equal(sent, true);
    assert.equal(controller.getSnapshot(), null);
});

test('save failures retain private nonsecret request state and collect multiple requirements once', async () => {
    const controller = new ActionAuthController({ preflight: async () => required(), read: async () => required(), cancel: async () => {} });
    const pending = controller.request(input, { surface: 'chat', isCurrent: () => true });
    await nextTick();
    let token = controller.startSubmission();
    controller.failSubmission(token, new ApiError('NEVER-RENDER-SECRET', 403, { error_code: 'action_auth_rejected', error: 'NEVER-RENDER-SECRET' }));
    assert.match(controller.getSnapshot().error, /rejected/);
    assert.equal(JSON.stringify(controller.getSnapshot()).includes('NEVER-RENDER-SECRET'), false);
    token = controller.startSubmission();
    controller.completeSubmission(token, required({ requirements: [requirement({ id: 'requirement-2' })] }));
    assert.equal(controller.getSnapshot().state.requirements[0].id, 'requirement-2');
    controller.completeSubmission(controller.startSubmission(), ready());
    assert.deepEqual(await pending, { requestId: 'request-1' });
});

test('navigation/actor changes and stale async preflight never resume an old draft', async () => {
    let complete;
    let currentActor = 'alice';
    const controller = new ActionAuthController({
        preflight: () => new Promise((resolve) => { complete = resolve; }), read: async () => ready(), cancel: async () => {},
    });
    const pending = controller.request(input, { surface: 'chat', isCurrent: () => currentActor === 'alice' });
    currentActor = 'bob';
    complete(ready());
    assert.equal(await pending, null);
    assert.equal(controller.getSnapshot(), null);
    const reloaded = new ActionAuthController();
    assert.equal(reloaded.getSnapshot(), null);
});

test('started-plan repair preflights only the affected action and discards the consumed receipt', async () => {
    const preflights = [];
    const reads = [];
    const cancelled = [];
    const repairState = required({ request_id: 'fresh-repair-request', shared_conversation: true });
    const controller = new ActionAuthController({
        preflight: async (payload) => { preflights.push(payload); return repairState; },
        read: async (requestId) => {
            reads.push(requestId);
            assert.equal(requestId, 'fresh-repair-request', 'A consumed execution receipt must not be read.');
            return repairState;
        },
        cancel: async (requestId) => { cancelled.push(requestId); },
    });
    controller.repair({
        error_code: 'action_credentials_required', request_id: 'consumed-root-receipt',
        action_ref: actionRef, execution_started: true,
    }, { ...input, run_id: 'finished-plan', conversation_kind: 'collaboration' }, { surface: 'chat', isCurrent: () => true });
    await nextTick();
    assert.deepEqual(preflights, [{
        action_ref: actionRef, conversation_id: 'visible-conversation', conversation_kind: 'collaboration',
    }]);
    assert.deepEqual(reads, []);
    assert.deepEqual(cancelled, []);
    assert.equal(controller.getSnapshot().state.request_id, 'fresh-repair-request');
    await controller.checkAgain();
    assert.deepEqual(reads, ['fresh-repair-request']);
    controller.acknowledgeSharing(true);
    controller.completeSubmission(controller.startSubmission(), ready({ request_id: 'fresh-repair-request', shared_conversation: true }));
    assert.equal(controller.getSnapshot().repair, true);
    assert.equal(controller.getSnapshot().executionStarted, true);
    assert.equal(controller.getSnapshot().state.status, 'ready');
    assert.equal(preflights.length, 1);
    controller.continue();
    assert.equal(controller.getSnapshot(), null);
});

test('started repair without a safe affected-action reference never falls back to the root selection', async () => {
    const calls = [];
    const controller = new ActionAuthController({
        preflight: async (payload) => { calls.push(payload); return ready(); },
        read: async (requestId) => { calls.push(requestId); return required(); },
        cancel: async (requestId) => { calls.push(requestId); },
    });
    controller.repair({
        type: 'action_credentials_required', request_id: 'consumed-root-receipt', execution_started: true,
    }, { ...input, run_id: 'finished-plan' }, { surface: 'chat', isCurrent: () => true });
    await controller.checkAgain();
    assert.equal(controller.getSnapshot().repairTargetUnavailable, true);
    assert.match(controller.getSnapshot().error, /affected action could not be identified/);
    controller.cancel();
    assert.deepEqual(calls, []);
});

test('not-started and unconfirmed repairs remain explicit rather than auto-sending', async () => {
    for (const started of [false, undefined]) {
        const controller = new ActionAuthController({
            preflight: async () => ready(), read: async () => required(), cancel: async () => {},
        });
        controller.repair({
            type: 'action_credentials_required', request_id: 'request-1', execution_started: started,
        }, input, { surface: 'chat', isCurrent: () => true });
        await nextTick();
        controller.completeSubmission(controller.startSubmission(), ready());
        assert.equal(controller.getSnapshot().executionStarted, started ?? null);
        assert.equal(controller.getSnapshot().repair, true);
        controller.continue();
        assert.equal(controller.getSnapshot(), null);
    }
});

test('check-again requests are serialized and retain distinct safe network and storage failures', async () => {
    let completeRead;
    let reads = 0;
    const controller = new ActionAuthController({
        preflight: async () => required(),
        read: () => { reads += 1; return new Promise((resolve) => { completeRead = resolve; }); },
        cancel: async () => {},
    });
    const pending = controller.request(input, { surface: 'chat', isCurrent: () => true });
    await nextTick();
    const checking = controller.checkAgain();
    await controller.checkAgain();
    assert.equal(reads, 1);
    completeRead(ready());
    await checking;
    assert.deepEqual(await pending, { requestId: 'request-1' });
    assert.match(actionAuthErrorMessage(new ApiError('unsafe', 502, { error_code: 'action_auth_connection_failed' })), /could not be reached/);
    assert.match(actionAuthErrorMessage(new ApiError('unsafe', 503, { error_code: 'action_auth_storage_unavailable' })), /could not be stored/);
});

test('only the private credential endpoint receives credential values; Test as me sends a saved action reference', async () => {
    const previousFetch = globalThis.fetch;
    const calls = [];
    globalThis.fetch = async (url, init = {}) => {
        const body = init.body ? JSON.parse(init.body) : null;
        calls.push({ url, body, signal: init.signal });
        const payload = String(url).endsWith('/types') ? [{ type: 'yamcs', display: 'Yamcs' }]
            : String(url).endsWith('/credentials') ? ready() : { success: true };
        return new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } });
    };
    try {
        await saveActionAuthCredentials('req/1', 'requirement-1', undefined, { username: 'synthetic-user', password: 'synthetic-private-password' });
        await saveActionAuthCredentials('req/1', 'requirement-1', 'owned-id', undefined);
        const value = changeActionCredentialSource(draft(), 'current_user', 'global');
        const resource = adminYamcsResource(value);
        const signal = new AbortController().signal;
        await testAdminYamcsAction(resource, signal);
        const types = await fetchAdminYamcsType();
        assert.ok(types.allowed_auth_types.includes('basic'));
        assert.equal(calls[0].url, '/api/action-auth/requests/req%2F1/credentials');
        assert.deepEqual(calls[1].body, { requirement_id: 'requirement-1', identity_id: 'owned-id', confirm_destination: true });
        assert.deepEqual(calls[2].body, { action_ref: globalYamcsActionReference(value) });
        assert.equal(calls[2].signal, signal);
        assert.equal(Buffer.from(globalYamcsActionReference(value).split(':').at(-1), 'base64url').toString(), value.id);
        assert.equal(globalYamcsActionReference({ ...value, name: 'renamed-action', displayName: 'Renamed action' }), calls[2].body.action_ref);
        const unicodeId = 'global-地上局';
        assert.equal(Buffer.from(globalYamcsActionReference({ ...value, id: unicodeId }).split(':').at(-1), 'base64url').toString('utf8'), unicodeId);
        const legacy = adminYamcsResource(draft());
        await testAdminYamcsAction(legacy, signal);
        const legacyPayload = calls.at(-1).body;
        assert.deepEqual(legacyPayload.existing_plugin, { scope: 'global', id: legacy.record.id, name: legacy.record.name });
        assert.equal(legacyPayload.auth_key, 'Stored_In_KeyVault');
        assert.equal(legacyPayload.server_url, legacy.record.endpoint);
        assert.equal(calls.slice(1).some((call) => JSON.stringify(call).includes('synthetic-private-password')), false);
        assert.match(actionAuthErrorMessage(new ApiError('unsafe', 409, {})), /changed or expired/);
    } finally { globalThis.fetch = previousFetch; }
});
