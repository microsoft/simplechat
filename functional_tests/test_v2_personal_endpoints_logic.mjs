// test_v2_personal_endpoints_logic.mjs
// Version: 0.261.315
// Implemented in: 0.261.315
// Execute the production personal adapter, payload builders and metadata validation.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const {
    createPersonalModelConnectionsAdapter, createAdminModelConnectionsAdapter,
    createGroupModelConnectionsAdapter, buildPersonalConnectionPayload, toEditableConnection,
    personalTestBlockedReason, validateAdvancedConnection, emptyConnection,
} = await import('../application/v2_ui/src/lib/modelConnections.ts');
const { tokenCapacity, capacityPayload, capacityErrors, validModelIcon } =
    await import('../application/v2_ui/src/lib/connectionMetadata.ts');

const originalFetch = globalThis.fetch;
const calls = [];
let answer = {};
let status = 200;
globalThis.fetch = async (url, options) => {
    calls.push({ url, method: options.method, body: options.body ? JSON.parse(options.body) : null });
    return new Response(JSON.stringify(answer), { status, headers: { 'content-type': 'application/json' } });
};
let checks = 0;
async function check(name, fn) {
    await fn();
    checks += 1;
    console.log(`ok ${name}`);
}
function endpoint(provider = 'aoai') {
    return {
        id: 'personal id:encoded', name: 'Personal', provider, enabled: true,
        ...(provider === 'custom' ? { api_type: 'openai' } : {}),
        connection: { endpoint: 'https://personal.openai.azure.com', openai_api_version: '2024-10-21' },
        auth: { type: 'api_key' }, has_api_key: true,
        contextWindow: 128000, tokenLimitProvider: 'azure', outputTokenAccounting: 'total_generation',
        models: [{
            id: 'm', deploymentName: 'gpt-4o', modelName: 'gpt-4o', enabled: true,
            responseLength: 512, contextWindow: 64000, catalogModelId: 'gpt-4o',
            modelVersion: '2024-08-06', icon: { kind: 'bootstrap', value: 'bi-stars' },
            description: 'Description', metadata: { keep: false },
        }],
    };
}
const descriptor = {
    value: 'openai', label: 'OpenAI', protocol: 'openai', urlPolicy: 'auto',
    versionField: '', defaultVersion: '', defaultApiKeyHeader: 'Authorization',
    defaultApiKeyPrefix: 'Bearer', description: 'OpenAI API', usesModelName: true,
    requiresApiVersion: false, authTypes: ['api_key'],
};
try {
    const adapter = createPersonalModelConnectionsAdapter();
    await check('personal adapter exposes only personal editing/test affordances', () => {
        assert.equal(adapter.scope.kind, 'personal');
        assert.ok(adapter.canCreate && adapter.advancedEditing && adapter.requiresSavedConfigurationTests);
        for (const key of ['canTestConnection', 'canTestCapabilities', 'canEditNetworkPolicy', 'showMigrationNotices']) {
            assert.equal(adapter[key], false);
        }
        const admin = createAdminModelConnectionsAdapter(() => {});
        const group = createGroupModelConnectionsAdapter({ kind: 'group', id: 'g', name: 'Group' }, {});
        assert.equal(admin.advancedEditing, undefined);
        assert.equal(group.requiresSavedConfigurationTests, undefined);
    });
    await check('list/create/edit/toggle/delete use the exact personal contract', async () => {
        answer = { endpoints: [endpoint()], custom_api_types: [descriptor] };
        const list = await adapter.list();
        assert.equal(list.endpoints.length, 1);
        answer = { endpoint: endpoint() };
        await adapter.create({ name: 'New' });
        await adapter.update(endpoint(), { name: 'Edit' });
        await adapter.update(endpoint(), { enabled: false });
        answer = { success: true };
        await adapter.remove(endpoint());
        assert.deepEqual(calls.map(({ url, method }) => [method, url]), [
            ['GET', '/api/user/model-endpoints'], ['POST', '/api/user/model-endpoints'],
            ['PATCH', '/api/user/model-endpoints/personal%20id%3Aencoded'],
            ['PATCH', '/api/user/model-endpoints/personal%20id%3Aencoded'],
            ['DELETE', '/api/user/model-endpoints/personal%20id%3Aencoded'],
        ]);
        assert.deepEqual(calls[3].body, { enabled: false });
        assert.equal(calls[4].body, null);
        assert.ok(!calls.some((call) => call.body?.endpoints || call.body?.expected_revision));
    });
    await check('malformed envelopes, records and success-shaped defaults fail loudly', async () => {
        for (const malformed of [{}, { endpoints: [] }, { endpoints: [{}], custom_api_types: [] },
            { endpoints: [endpoint(), endpoint()], custom_api_types: [] },
            { endpoints: [], custom_api_types: [{}] },
            { endpoints: [{ ...endpoint(), name: {} }], custom_api_types: [] },
            { endpoints: [{ ...endpoint(), models: [null] }], custom_api_types: [] }]) {
            answer = malformed;
            await assert.rejects(adapter.list(), /malformed|duplicate/);
        }
        answer = { endpoint: {} };
        await assert.rejects(adapter.create({ name: 'New' }), /malformed/);
        answer = {};
        await assert.rejects(adapter.remove(endpoint()), /confirmed/);
        await assert.rejects(adapter.discover({}), /malformed/);
        await assert.rejects(adapter.testConnectionModel({}, 'gpt'), /successful/);
        for (const models of [[{}], [{ deploymentName: {} }], [{ deploymentName: ' ' }]]) {
            answer = { models };
            await assert.rejects(adapter.discover({}), /malformed/);
        }
        for (const id of ['../outside', 'broken?query', ' trailing ', '', '.', '..']) {
            await assert.rejects(adapter.update({ ...endpoint(), id }, {}), /identifier/);
            answer = { endpoints: [{ ...endpoint(), id }], custom_api_types: [] };
            await assert.rejects(adapter.list(), /malformed|identifier/);
        }
    });
    await check('discovery/chat tests go only to personal routes and propagate denial', async () => {
        answer = { models: [{ deploymentName: 'gpt' }] };
        await adapter.discover({ provider: 'aoai' });
        assert.equal(calls.at(-1).url, '/api/user/models/fetch');
        answer = { success: true };
        await adapter.testConnectionModel({ id: 'p' }, 'gpt');
        assert.deepEqual(calls.at(-1), {
            url: '/api/user/models/test-model', method: 'POST',
            body: { id: 'p', model: { deploymentName: 'gpt' } },
        });
        status = 403; answer = { error: 'Endpoint access denied.' };
        await assert.rejects(adapter.list(), /Endpoint access denied/);
        status = 200;
    });
    await check('capacity validation retains exact integers and rejects coercion', () => {
        for (const valid of [1, 9007199254740991, ' 0128 ']) assert.ok(tokenCapacity(valid, 'Capacity') > 0);
        for (const blank of [null, undefined, '', '  ']) assert.equal(tokenCapacity(blank, 'Capacity'), null);
        for (const invalid of [true, false, 0, -1, 1.5, NaN, Infinity, '1e3', '1.0', '9007199254740992', {}, []]) {
            assert.throws(() => tokenCapacity(invalid, 'Capacity'), /positive whole/);
        }
        assert.ok(capacityErrors({ tokenLimitProvider: 12 }).tokenLimitProvider);
        assert.ok(capacityErrors({ outputTokenAccounting: 'guessed' }).outputTokenAccounting);
        assert.ok(capacityErrors({ catalogModelId: 'x'.repeat(257) }, true).catalogModelId);
        assert.deepEqual(capacityPayload({ catalogModelId: ` \t${'x'.repeat(256)}\n ` }, true), {
            catalogModelId: 'x'.repeat(256),
        });
        assert.ok(capacityErrors({ modelVersion: 'snapshot\u0000hidden' }, true).modelVersion);
        assert.deepEqual(capacityPayload({ contextWindow: '', outputTokenAccounting: null }), {
            contextWindow: null, outputTokenAccounting: null,
        });
    });
    await check('Azure and Custom payloads preserve advanced metadata and omit blank secrets', () => {
        for (const provider of ['aoai', 'custom']) {
            const saved = endpoint(provider);
            const draft = toEditableConnection(saved);
            const payload = buildPersonalConnectionPayload(draft);
            assert.equal(payload.contextWindow, 128000);
            assert.equal(payload.models[0].contextWindow, 64000);
            assert.equal(payload.models[0].responseLength, 512);
            assert.deepEqual(payload.models[0].metadata, { keep: false });
            assert.equal(payload.auth.api_key, undefined);
            assert.equal(payload.has_api_key, undefined);
            draft.auth.api_key = 'replacement';
            draft.contextWindow = null;
            draft.models[0].responseLength = '';
            draft.models[0].catalogModelId = null;
            const edited = buildPersonalConnectionPayload(draft);
            assert.equal(edited.contextWindow, null);
            assert.equal(edited.models[0].responseLength, null);
            assert.equal(edited.models[0].catalogModelId, null);
            assert.equal(edited.auth.api_key, 'replacement');
        }
    });
    await check('changed or invalid existing drafts require saving before discovery/test', () => {
        const saved = endpoint();
        assert.equal(personalTestBlockedReason(toEditableConnection(saved), saved), null);
        for (const change of [
            (draft) => { draft.connection.endpoint = 'https://changed.test'; },
            (draft) => { draft.auth.api_key = 'rotated'; },
            (draft) => { draft.models[0].enabled = false; },
            (draft) => { draft.models.push({ deploymentName: 'new' }); },
            (draft) => { draft.models[0].responseLength = '0'; },
            (draft) => { draft.contextWindow = '12e2'; },
        ]) {
            const draft = toEditableConnection(saved);
            change(draft);
            assert.match(personalTestBlockedReason(draft, saved), /Save changes/);
        }
        assert.equal(personalTestBlockedReason(emptyConnection(), emptyConnection()), null);
    });
    await check('icon validation allows only local classes and bounded raster payloads', () => {
        for (const value of [{}, { kind: 'bootstrap', value: 'bi-stars' }, { kind: 'image', value: 'data:image/png;base64,aGVsbG8=' }]) {
            assert.ok(validModelIcon(value));
        }
        for (const value of [null, [], { kind: 'bootstrap', value: 'bi-stars onclick=x' },
            { kind: 'image', value: 'https://remote.test/icon.png' },
            { kind: 'image', value: 'data:image/svg+xml;base64,aGVsbG8=' }]) assert.equal(validModelIcon(value), false);
        const draft = endpoint();
        draft.models[0].responseLength = '1.5';
        assert.ok(validateAdvancedConnection(draft).model_0_responseLength);
    });
} finally {
    globalThis.fetch = originalFetch;
}
console.log(`${checks} personal endpoint runtime checks passed.`);
