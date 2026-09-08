// test_shared_ai_connections_ui_logic.mjs
// Version: 0.261.105
// Implemented in: 0.261.105
// Shared selection identity, technical metadata, publication policy and safe transport.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const {
    buildConnectionPayload,
    buildDefaultModelChoices,
    choiceToSelection,
    groupChoicesByConnection,
    mergeDiscoveredModels,
    modelPublishesCapability,
    modelSupportsCapability,
    setModelCapabilityEnabled,
    toDefaultModelSelection,
} = await import('../application/v2_ui/src/lib/modelConnections.ts');
const { isFieldVisible } = await import('../application/v2_ui/src/lib/adminFields.ts');
const {
    fetchCapabilityModels,
    saveCapabilityModel,
    testImageModel,
    toCapabilityModelsResponse,
} = await import('../application/v2_ui/src/lib/capabilityModels.ts');

const supported = (api) => ({ supported: true, available: true, source: 'catalog', api });
const dual = {
    id: 'same:model',
    deploymentName: 'same-deployment',
    capability_status: { chat: supported('chat'), image_generation: supported('responses') },
};
const imported = { ...dual, enabled_capabilities: ['image_generation'] };
const direct = {
    id: 'direct',
    deploymentName: 'custom-name',
    capability_status: {
        chat: { supported: false, source: 'model' },
        image_generation: supported('images'),
    },
};
const endpoints = [
    { id: 'one:resource', name: 'Same connection name', provider: 'aoai', models: [dual, direct] },
    { id: 'two', name: 'Same connection name', provider: 'aoai', models: [imported] },
];

assert.equal(modelSupportsCapability(imported, 'chat'), true);
assert.equal(modelPublishesCapability(imported, 'chat'), false);
assert.equal(modelPublishesCapability(imported, 'image_generation'), true);
assert.equal(modelPublishesCapability({ ...dual, enabled: false }, 'chat'), false);
assert.equal(modelSupportsCapability({ deploymentName: 'gpt-5.6', supportsVision: true }, 'image_generation'), false);
assert.equal(modelSupportsCapability({ deploymentName: 'legacy-custom' }, 'chat'), true);
assert.equal(modelSupportsCapability({ supportsChat: false }, 'chat'), false);
assert.equal(modelSupportsCapability({ supportsImageGeneration: true }, 'image_generation'), true);
assert.deepEqual(setModelCapabilityEnabled(dual, 'chat', false).enabled_capabilities, ['image_generation']);
assert.equal(modelSupportsCapability(setModelCapabilityEnabled(dual, 'chat', false), 'chat'), true);
assert.deepEqual(buildDefaultModelChoices(endpoints).map(choiceToSelection), [{
    endpoint_id: 'one:resource', model_id: 'same:model', provider: 'aoai',
}]);

const choice = (endpoint_id, model_id) => ({
    endpoint_id, model_id, provider: 'aoai', connection_name: 'Same connection name',
    label: 'Same deployment', deployment_name: 'same-deployment', capability: supported('responses'),
});
const response = {
    capability: 'image_generation', enabled: true,
    selection: { endpoint_id: 'two', model_id: 'same:model', provider: 'aoai' },
    choices: [choice('one:resource', 'same:model'), choice('two', 'same:model')],
    reason: null, migration: { status: 'complete', message: 'Imported.', imported_connections: 1 },
};
const normalized = toCapabilityModelsResponse(response, 'image_generation');
assert.equal(groupChoicesByConnection(normalized.choices).length, 2);
assert.deepEqual(choiceToSelection(normalized.choices[1]), response.selection);
assert.equal(normalized.migration.imported_connections, 1);
assert.deepEqual(toDefaultModelSelection(['not', 'a', 'selection']), { endpoint_id: '', model_id: '', provider: '' });
assert.throws(() => toCapabilityModelsResponse({ choices: [] }, 'image_generation'));
assert.equal(toCapabilityModelsResponse({ ...response, choices: [null, {}, { ...choice('e', 'm'), capability: { supported: false } }] }, 'image_generation').choices.length, 0);

const discovered = mergeDiscoveredModels([], [{
    deploymentName: 'custom', supportsChat: false, supportsImageGeneration: true,
    capability_status: direct.capability_status,
}]).models[0];
assert.equal(discovered.enabled, false);
assert.equal(discovered.supportsChat, false);
assert.equal(discovered.capability_status.image_generation.api, 'images');
const transport = { image_generation: { api_version: '2025-04-01-preview', transport: 'apim' } };
assert.deepEqual(buildConnectionPayload({
    id: 'one', connection: { endpoint: 'https://example.test/gateway', operation_settings: transport },
}).connection.operation_settings, transport);
assert.equal(isFieldVisible({ type: 'secret', key: 'azure_openai_image_gen_key', legacy: true }, {}, {}), false);

const originalFetch = globalThis.fetch;
const requests = [];
globalThis.fetch = async (url, init) => {
    requests.push({ url, method: init.method, body: init.body ? JSON.parse(init.body) : null });
    return new Response(JSON.stringify(url.includes('test-connection') ? { success: true } : response), {
        status: 200, headers: { 'Content-Type': 'application/json' },
    });
};
try {
    await fetchCapabilityModels('image_generation');
    await saveCapabilityModel('image_generation', response.selection);
    await testImageModel(response.selection);
    assert.equal(requests[0].url, '/api/v2/admin/capability-models/image_generation');
    assert.deepEqual(requests[1].body, { selection: response.selection });
    assert.deepEqual(requests[2].body, { test_type: 'image', selection: response.selection });
    assert.equal(requests[2].url, '/api/v2/admin/settings/test-connection');
} finally {
    globalThis.fetch = originalFetch;
}
console.log('Shared AI Connections UI logic passed.');
