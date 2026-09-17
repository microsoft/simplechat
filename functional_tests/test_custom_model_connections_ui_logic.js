// test_custom_model_connections_ui_logic.js
/*
Functional tests for Custom connection form logic.
Version: 0.261.108
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

const embeddingModel = {
    id: 'embedding-stable-id', modelName: 'private-embedding', deploymentName: 'saved-wire-alias',
    supportsEmbeddings: true, enabled_capabilities: ['embeddings'],
    embedding_config: {
        dimensions: 768, max_input_tokens: 2048, model_revision: 'retained-revision',
        document_prefix: 'passage: ', query_prefix: 'query: ',
    },
    vendorOptions: { future: [1, 2] },
};
for (const apiType of ['openai', 'azure_openai']) {
    for (const authType of ['api_key', 'bearer']) {
        const candidate = structuredClone(source);
        candidate.api_type = apiType;
        candidate.models = [structuredClone(embeddingModel)];
        candidate.auth = { type: authType };
        candidate.has_api_key = authType === 'api_key';
        candidate.has_bearer_token = authType === 'bearer';
        if (apiType === 'azure_openai') candidate.connection.api_version = '2025-04-01-preview';
        candidate.connection.operation_settings = {
            embeddings: { api: apiType, endpoint: 'https://gateway.example.test/embedding/base' },
            image_generation: { api: 'responses', api_version: '2025-04-01-preview' },
        };
        const draft = connections.toEditableConnection(candidate);
        assert.equal(connections.embeddingConnectionUnavailableReason(draft), null);
        assert.equal(connections.defaultEmbeddingApi(draft), apiType);
        assert.equal(Object.keys(connections.validateConnection(draft)).length, 0);
        const payload = connections.buildConnectionPayload(draft);
        assert.equal(payload.provider, 'custom');
        assert.equal(payload.api_type, apiType);
        assert.equal(payload.models[0].id, 'embedding-stable-id');
        assert.equal(payload.models[0].modelName, 'private-embedding');
        assert.equal(payload.models[0].deploymentName, 'saved-wire-alias');
        assert.equal(custom.connectionRequestModel(draft, draft.models[0]), apiType === 'azure_openai' ? 'saved-wire-alias' : 'private-embedding');
        assert.deepEqual(JSON.parse(JSON.stringify(payload.models[0].embedding_config)), embeddingModel.embedding_config);
        assert.deepEqual(JSON.parse(JSON.stringify(payload.connection.operation_settings)), candidate.connection.operation_settings);
        assert.equal(payload.auth.api_key, undefined);
        assert.equal(payload.auth.bearer_token, undefined);
        assert.equal(connections.visibleFields(draft).discovery, false);
        const incomplete = structuredClone(candidate);
        delete incomplete.models[0].embedding_config.dimensions;
        assert.ok(connections.validateConnection(incomplete).model_0_dimensions);
        const mismatched = structuredClone(candidate);
        mismatched.connection.operation_settings.embeddings.api = apiType === 'openai' ? 'azure_openai' : 'openai';
        assert.match(connections.validateConnection(mismatched).embedding_api, /must match/);
    }
}

for (const [apiType, authType] of [
    ['anthropic', 'api_key'], ['gemini', 'api_key'],
    ['openai', 'oauth2_client_credentials'], ['azure_openai', 'oauth2_client_credentials'],
]) {
    const candidate = structuredClone(source);
    candidate.api_type = apiType;
    candidate.auth = {
        type: authType, token_url: 'https://identity.example.test/token', client_id: 'fixture-client',
    };
    candidate.has_api_key = true;
    candidate.has_client_secret = true;
    if (apiType === 'azure_openai') candidate.connection.api_version = '2025-04-01-preview';
    assert.equal(Object.keys(connections.validateConnection(candidate)).length, 0, 'Existing Custom chat remains valid.');
    assert.equal(connections.buildDefaultModelChoices([candidate]).length, 1);
    candidate.models = [structuredClone(embeddingModel)];
    assert.match(connections.embeddingConnectionUnavailableReason(candidate), /API key or bearer/);
    assert.match(connections.validateConnection(candidate).model_0_supportsEmbeddings, /API key or bearer/);
}

const alias = structuredClone(source);
alias.provider = 'openai_compatible';
delete alias.api_type;
alias.auth = { type: 'api_key' };
alias.has_api_key = true;
alias.models = [structuredClone(embeddingModel)];
const aliasDraft = connections.toEditableConnection(alias);
const aliasPayload = connections.buildConnectionPayload(aliasDraft);
assert.equal(Object.keys(connections.validateConnection(aliasDraft)).length, 0);
assert.equal(aliasDraft.provider, 'openai_compatible');
assert.equal(aliasPayload.provider, 'openai_compatible');
assert.equal(aliasPayload.api_type, undefined);
assert.equal(aliasPayload.connection.endpoint, source.connection.endpoint);
assert.equal(aliasPayload.connection.openai_api_version, undefined);
assert.equal(aliasPayload.models[0].deploymentName, 'saved-wire-alias');
assert.equal(aliasPayload.models[0].modelName, 'private-embedding');
assert.equal(custom.connectionRequestModel(aliasDraft, aliasDraft.models[0]), 'saved-wire-alias');
assert.equal(connections.buildDefaultModelChoices([{ ...alias, models: [{ ...embeddingModel, supportsChat: true }] }]).length, 0);
assert.equal(connections.PROVIDER_OPTIONS.filter(option => ['custom', 'openai_compatible'].includes(option.value)).length, 2);
console.log('Custom model connection UI logic passed.');
