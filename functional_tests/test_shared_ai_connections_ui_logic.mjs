// test_shared_ai_connections_ui_logic.mjs
// Version: 0.261.122
// Implemented in: 0.261.105; embeddings added in 0.261.106
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
    modelNeedsEmbeddingGateway,
    modelSupportsCapability,
    setModelCapabilityEnabled,
    setEmbeddingOperation,
    toDefaultModelSelection,
} = await import('../application/v2_ui/src/lib/modelConnections.ts');
const { isFieldVisible } = await import('../application/v2_ui/src/lib/adminFields.ts');
const {
    fetchCapabilityModels,
    saveCapabilityModel,
    testImageModel,
    testEmbeddingModel,
    capabilityDescription,
    canGenerateImage,
    embeddingPolicyDescription,
    toEmbeddingPolicy,
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
assert.deepEqual(setModelCapabilityEnabled(dual, 'chat', false).enabled_capabilities, ['image_generation', 'embeddings']);
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
assert.equal(isFieldVisible({ type: 'secret', key: 'azure_openai_embedding_key', legacy: true }, {}, {}), false);

const embeddingPolicy = {
    dimensions: 768, default_dimensions: 1536, supports_dimensions: true, request_dimensions: 768,
    max_input_tokens: 4096, max_batch_size: 8, max_batch_tokens: 8192,
    tokenizer: 'conservative',
    api: 'openai', requires_input_type: false,
};
const embedding = {
    id: 'same:model', deploymentName: 'private-model', supportsEmbeddings: true,
    embedding_config: {
        dimensions: 768, max_input_tokens: 4096, model_revision: 'revision-2',
        document_prefix: 'passage: ', query_prefix: 'query: ',
    },
    capability_status: { embeddings: supported('openai'), chat: { supported: false, source: 'model' } },
};
assert.equal(modelPublishesCapability(embedding, 'embeddings'), true);
const discoveredEmbedding = mergeDiscoveredModels([], [{
    ...embedding, embedding_policy: embeddingPolicy,
}]).models[0];
assert.equal(discoveredEmbedding.enabled, false);
assert.equal(discoveredEmbedding.supportsEmbeddings, true);
assert.deepEqual(discoveredEmbedding.embedding_policy, embeddingPolicy);
assert.deepEqual(discoveredEmbedding.embedding_config, embedding.embedding_config);
assert.equal(modelPublishesCapability(embedding, 'chat'), false);
assert.equal(modelSupportsCapability({ supportsEmbeddings: true }, 'image_generation'), false);
assert.equal(modelSupportsCapability({ supportsEmbeddings: true }, 'chat'), false);
assert.equal(modelSupportsCapability({ supportsImageGeneration: true }, 'embeddings'), false);
assert.equal(modelSupportsCapability({ deploymentName: 'custom-chat' }, 'embeddings'), false);
for (const modelName of ['text-embedding-3-small', 'text-embedding-3-large', 'text-embedding-ada-002', 'embed-v-4-0']) {
    assert.equal(modelSupportsCapability({ modelName, supportsChat: true }, 'chat'), false);
    assert.equal(modelSupportsCapability({ modelName, supportsImageGeneration: true }, 'image_generation'), false);
}
assert.equal(modelNeedsEmbeddingGateway({ modelName: 'text-embedding-3-small' }), false);
assert.equal(modelNeedsEmbeddingGateway({ modelName: 'embed-v-4-0' }), true);
assert.equal(modelNeedsEmbeddingGateway({ modelName: 'Cohere-embed-v3-english' }), true);
assert.equal(modelSupportsCapability({ modelName: 'embed-v-4-0' }, 'embeddings'), false);
assert.equal(modelSupportsCapability({ modelName: 'embed-v-4-0', embedding_config: { openai_compatible: true } }, 'embeddings'), true);
assert.equal(modelSupportsCapability({ modelName: 'unknown-model', embedding_config: { openai_compatible: true } }, 'embeddings'), false);
assert.equal(modelPublishesCapability({ ...embedding, enabled_capabilities: [] }, 'embeddings'), false);
assert.deepEqual(setModelCapabilityEnabled({ ...embedding, enabled_capabilities: [] }, 'embeddings', true).enabled_capabilities, ['embeddings']);
assert.equal(modelPublishesCapability(setModelCapabilityEnabled(dual, 'chat', false), 'embeddings'), false);
assert.deepEqual(buildDefaultModelChoices([{ ...endpoints[0], provider: 'openai_compatible' }]), []);
const embeddingResponse = {
    ...response, capability: 'embeddings', enabled: true,
    migration: { status: 'error', message: 'Embedding import needs recovery.' },
    compatibility: { status: 'compatible', message: 'Current vector space is unchanged.', dimensions: 768, profile_id: 'profile-2', api_key: 'not-returned' },
    choices: response.choices.map(item => ({
        ...item, capability: supported('openai'),
        embedding_policy: {
            ...embeddingPolicy, api_key: 'not-returned', model_revision: 'not-public',
            document_prefix: 'not-public', query_prefix: 'not-public',
        },
    })),
};
const normalizedEmbedding = toCapabilityModelsResponse(embeddingResponse, 'embeddings');
const unavailableEmbedding = toCapabilityModelsResponse({
    ...embeddingResponse, selection: {}, reason: 'The saved embedding profile is unavailable. Review the connection.',
}, 'embeddings');
assert.deepEqual(unavailableEmbedding.selection, { endpoint_id: '', model_id: '', provider: '' });
assert.equal(unavailableEmbedding.reason, 'The saved embedding profile is unavailable. Review the connection.');
assert.deepEqual(embeddingResponse.selection, response.selection);
assert.equal(toCapabilityModelsResponse({
    ...embeddingResponse,
    choices: [{ ...embeddingResponse.choices[0], capability: { ...supported('openai'), available: false } }],
}, 'embeddings').choices.length, 0);
assert.equal(normalizedEmbedding.enabled, true);
assert.equal(normalizedEmbedding.migration.message, 'Embedding import needs recovery.');
assert.deepEqual(normalizedEmbedding.choices[0].embedding_policy, embeddingPolicy);
assert.equal('api_key' in normalizedEmbedding.compatibility, false);
assert.equal(groupChoicesByConnection(normalizedEmbedding.choices).length, 2);
assert.equal(capabilityDescription(normalizedEmbedding.choices[0].capability, 'embeddings'), 'Text embeddings · catalog');
assert.match(embeddingPolicyDescription(embeddingPolicy), /768 dimensions.*4,096 input tokens/);
assert.doesNotMatch(embeddingPolicyDescription(normalizedEmbedding.choices[0].embedding_policy), /not-public|revision|prefix/);
assert.deepEqual(toEmbeddingPolicy({ dimensions: true, default_dimensions: 0, max_input_tokens: '8192', api: 'native', allowed_dimensions: [768, -1, false] }), { allowed_dimensions: [768] });
assert.equal(toEmbeddingPolicy(null), undefined);
const operations = { ...transport, embeddings: { api: 'openai', endpoint: 'https://gateway.test/api/v1', is_apim: false, auth_header: 'authorization' } };
const embeddingConnection = {
    id: 'embedding-endpoint', provider: 'openai_compatible',
    connection: { endpoint: 'https://gateway.test/api/v1', operation_settings: operations },
    auth: { type: 'api_key' }, has_api_key: true, models: [embedding],
};
const embeddingPayload = buildConnectionPayload(embeddingConnection);
assert.deepEqual(embeddingPayload.connection.operation_settings, operations);
assert.deepEqual(embeddingPayload.models[0].embedding_config, embedding.embedding_config);
assert.equal('api_key' in embeddingPayload.auth, false);
const changedOperation = setEmbeddingOperation(embeddingConnection, 'endpoint', 'https://gateway.test/other/v1');
assert.equal(changedOperation.connection.operation_settings.embeddings.endpoint, 'https://gateway.test/other/v1');
assert.equal(embeddingConnection.connection.operation_settings.embeddings.endpoint, 'https://gateway.test/api/v1');
assert.deepEqual(changedOperation.connection.operation_settings.image_generation, transport.image_generation);
assert.equal(setEmbeddingOperation(embeddingConnection, 'is_apim', false).connection.operation_settings.embeddings.is_apim, false);

const imageStatus = {
    ...supported('mai'), mode: 'edit', editing: true, masking: false,
    provider_label: 'Microsoft Foundry MAI', cloud_label: 'Commercial endpoint',
    availability: 'documented', model_name: 'MAI-Image-2.6', publisher: 'Microsoft',
    sizes: ['1024x768'], qualities: [], backgrounds: [], lifecycle: 'preview',
};
const mixedMetadata = mergeDiscoveredModels([], [{
    ...embedding,
    supportsImageGeneration: true, supportsImageEditing: true, supportsImageMasking: false,
    image_generation_api: 'mai', enabled_capabilities: ['embeddings', 'image_generation'],
    capability_status: { ...embedding.capability_status, image_generation: imageStatus },
    embedding_policy: embeddingPolicy,
}]).models[0];
const mixedPayload = buildConnectionPayload({
    ...embeddingConnection, provider: 'custom', api_type: 'openai', models: [mixedMetadata],
});
assert.equal(mixedPayload.provider, 'custom');
assert.equal(mixedPayload.models[0].supportsEmbeddings, true);
assert.equal(mixedPayload.models[0].supportsImageEditing, true);
assert.equal(mixedPayload.models[0].supportsImageMasking, false);
assert.equal(mixedPayload.models[0].image_generation_api, 'mai');
assert.deepEqual(mixedPayload.models[0].capability_status.image_generation, imageStatus);
assert.deepEqual(mixedPayload.models[0].embedding_config, embedding.embedding_config);
assert.deepEqual(mixedPayload.models[0].enabled_capabilities, ['embeddings', 'image_generation']);
assert.deepEqual(mixedPayload.connection.operation_settings, operations);
const imageMetadata = toCapabilityModelsResponse({
    ...response,
    choices: [{
        ...response.choices[0], capability: { ...imageStatus, endpoint: 'https://private.example', model_revision: 'private' },
        embedding_policy: embedding.embedding_config,
    }],
}, 'image_generation').choices[0];
assert.equal(canGenerateImage(imageMetadata.capability), true);
assert.equal(canGenerateImage({ ...imageMetadata.capability, available: false }), false);
assert.deepEqual(imageMetadata.capability.sizes, ['1024x768']);
assert.deepEqual(imageMetadata.capability.qualities, []);
assert.equal(imageMetadata.capability.masking, false);
assert.equal('endpoint' in imageMetadata.capability, false);
assert.equal('model_revision' in imageMetadata.capability, false);
assert.equal('embedding_policy' in imageMetadata, false);
const embeddingMetadata = toCapabilityModelsResponse({
    ...embeddingResponse,
    choices: [{
        ...embeddingResponse.choices[0], capability: { ...imageStatus, ...supported('openai') },
        embedding_policy: { ...embeddingPolicy, endpoint: 'https://private.example', model_revision: 'private' },
    }],
}, 'embeddings').choices[0];
assert.equal('masking' in embeddingMetadata.capability, false);
assert.equal('sizes' in embeddingMetadata.capability, false);
assert.equal('endpoint' in embeddingMetadata.embedding_policy, false);
assert.equal('model_revision' in embeddingMetadata.embedding_policy, false);
assert.doesNotMatch(embeddingPolicyDescription({ ...embeddingPolicy, requires_input_type: true }), /not supported/);
assert.match(embeddingPolicyDescription({ ...embeddingPolicy, api: 'unsupported', requires_input_type: true }), /not supported/);

const originalFetch = globalThis.fetch;
const requests = [];
globalThis.fetch = async (url, init) => {
    requests.push({ url, method: init.method, body: init.body ? JSON.parse(init.body) : null });
    return new Response(JSON.stringify(url.includes('test-connection') ? { success: true, dimensions: 768 } : url.endsWith('/embeddings') ? embeddingResponse : response), {
        status: 200, headers: { 'Content-Type': 'application/json' },
    });
};
try {
    await fetchCapabilityModels('image_generation');
    await saveCapabilityModel('image_generation', response.selection);
    await testImageModel(response.selection);
    await fetchCapabilityModels('embeddings');
    await saveCapabilityModel('embeddings', embeddingResponse.selection);
    const embeddingTest = await testEmbeddingModel(embeddingResponse.selection);
    assert.equal(requests[0].url, '/api/v2/admin/capability-models/image_generation');
    assert.deepEqual(requests[1].body, { selection: response.selection });
    assert.deepEqual(requests[2].body, { test_type: 'image', selection: response.selection });
    assert.equal(requests[2].url, '/api/v2/admin/settings/test-connection');
    assert.equal(requests[3].url, '/api/v2/admin/capability-models/embeddings');
    assert.deepEqual(requests[4].body, { selection: embeddingResponse.selection });
    assert.deepEqual(requests[5].body, { test_type: 'embedding', selection: embeddingResponse.selection });
    assert.equal(embeddingTest.dimensions, 768);
} finally {
    globalThis.fetch = originalFetch;
}
console.log('Shared AI Connections UI logic passed.');
