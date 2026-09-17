// test_custom_model_connections_ui_logic.js
/*
Functional tests for Custom connection form logic.
Version: 0.261.107
Implemented in: 0.261.107
Uses the existing TypeScript dependency and Node runner without a browser or service.
*/

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const ts = require(path.join(root, 'application', 'v2_ui', 'node_modules', 'typescript'));
const cache = new Map();

function loadModule(name) {
    if (name === './apiClient') return { api: {} };
    if (cache.has(name)) return cache.get(name);
    const filename = path.join(root, 'application', 'v2_ui', 'src', 'lib', `${name.replace('./', '')}.ts`);
    const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
        compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
    }).outputText;
    const module = { exports: {} };
    cache.set(name, module.exports);
    vm.runInNewContext(code, { module, exports: module.exports, require: loadModule, URL, console }, { filename });
    return module.exports;
}

const custom = loadModule('./customModelConnections');
const connections = loadModule('./modelConnections');
const source = {
    id: 'stable-endpoint', name: 'Gateway', provider: 'custom', api_type: 'openai',
    auth: { type: 'bearer' }, has_bearer_token: true,
    connection: { endpoint: 'https://gateway.example.test/prefix', url_mode: 'exact', vendorExtension: 'retained' },
    models: [{
        id: 'stable-model', modelName: 'private-model', deploymentName: 'not-the-wire-name',
        enabled: true, vendorOptions: { future: [1, 2] },
    }],
};

for (const apiType of ['openai', 'gemini', 'anthropic', 'azure_openai']) {
    const candidate = structuredClone(source);
    candidate.api_type = apiType;
    if (apiType === 'azure_openai') candidate.connection.api_version = '2025-04-01-preview';
    const draft = connections.toEditableConnection(candidate);
    assert.equal(Object.keys(connections.validateConnection(draft)).length, 0);
    const payload = connections.buildConnectionPayload(draft);
    assert.equal(payload.api_type, apiType);
    assert.equal(payload.id, 'stable-endpoint');
    assert.equal(payload.models[0].id, 'stable-model');
    assert.deepEqual(JSON.parse(JSON.stringify(payload.models[0].vendorOptions)), { future: [1, 2] });
    assert.equal(payload.connection.vendorExtension, 'retained');
    assert.equal(payload.connection.openai_api_version, undefined);
    assert.equal(payload.auth.bearer_token, undefined);
    assert.equal(payload.auth.management_cloud, undefined);
    assert.equal(custom.connectionRequestModel(draft, draft.models[0]), apiType === 'azure_openai' ? 'not-the-wire-name' : 'private-model');
    assert.equal(connections.modelSupportsCapability(draft.models[0], 'image_generation'), false);
}

const oauth = structuredClone(source);
oauth.auth = { type: 'oauth2_client_credentials', token_url: 'https://identity.example.test/token', client_id: 'client' };
assert.ok(connections.validateConnection(oauth).client_secret);
oauth.has_client_secret = true;
assert.equal(Object.keys(connections.validateConnection(oauth)).length, 0);
assert.equal(connections.buildConnectionPayload(oauth).auth.client_secret, undefined);
oauth.models.push({ id: 'another-id', modelName: 'PRIVATE-MODEL' });
assert.ok(connections.validateConnection(oauth).models);

const key = structuredClone(source);
key.auth = { type: 'api_key', api_key: 'fixture-key', api_key_header: 'x-gateway-key', api_key_prefix: '' };
assert.equal(connections.buildConnectionPayload(key).auth.api_key_prefix, '');
assert.equal(connections.visibleFields(key).managementCloud, false);
assert.equal(connections.visibleFields(key).managedIdentity, false);
const choices = connections.buildDefaultModelChoices([source]);
assert.equal(choices[0].modelId, 'stable-model');
assert.equal(choices[0].deploymentName, 'private-model');
console.log('Custom model connection UI logic passed.');
