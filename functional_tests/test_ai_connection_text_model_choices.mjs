// test_ai_connection_text_model_choices.mjs
// Version: 0.261.102
// Implemented in: 0.261.102
// Execute Classic agent and workflow projections without a browser or network.

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import {
    getAvailableModels,
    fetchAndGetAvailableModels,
    isChatModelAvailable,
} from '../application/single_app/static/js/agents_common.js';

const endpoints = [
    {
        id: 'mixed', provider: 'new_foundry', enabled: true, models: [
            { id: 'chat', deploymentName: 'shared-name', capability_status: { chat: { available: true } } },
            { id: 'legacy-chat', deploymentName: 'unrecognized-legacy-alias' },
            { id: 'image', capability_status: { chat: { available: false } } },
            { id: 'imported-image', enabled_capabilities: ['image_generation'] },
            { id: 'off', enabled: false },
            { id: 'unpublished', supportsChat: false },
        ],
    },
    {
        id: 'second', provider: 'aoai',
        models: [{ id: 'chat', deploymentName: 'shared-name', capability_status: { chat: { available: true } } }],
    },
    { id: 'disabled', enabled: false, models: [{ id: 'hidden' }] },
    { id: 'project-only', provider: 'new_foundry', models: [] },
];
const original = structuredClone(endpoints);
const choices = getAvailableModels({
    settings: { enable_multi_model_endpoints: true, model_endpoints: endpoints }, agent: { agent_type: 'local' },
});
assert.deepEqual(choices.models.map((item) => [item.endpoint_id, item.id]), [
    ['mixed', 'chat'], ['mixed', 'legacy-chat'], ['second', 'chat'],
]);
assert.deepEqual(endpoints, original);

const legacySettings = {
    enable_multi_model_endpoints: false,
    model_endpoints: [
        { id: 'images', models: [{ id: 'images', capability_status: { chat: { available: false } } }] },
        { id: 'foundry-project', provider: 'new_foundry', models: [] },
    ],
    gpt_model: { selected: [{ deploymentName: 'legacy-text' }] },
};
assert.equal(getAvailableModels({ settings: legacySettings, agent: {} }).models[0].deployment, 'legacy-text');
assert.deepEqual(getAvailableModels({
    settings: { ...legacySettings, enable_multi_model_endpoints: true }, agent: {},
}).models, []);
assert.deepEqual(getAvailableModels({
    settings: { ...legacySettings, enable_multi_model_endpoints: true, model_endpoints: [] }, agent: {},
}).models, []);

const previousFetch = globalThis.fetch;
try {
    globalThis.fetch = async () => ({ ok: true, json: async () => structuredClone(legacySettings) });
    const fetched = await fetchAndGetAvailableModels('/api/agents/settings', {});
    assert.equal(fetched.enableMultiModelEndpoints, false);
    assert.equal(fetched.models[0].deployment, 'legacy-text');
} finally {
    globalThis.fetch = previousFetch;
}

const workflowSource = await readFile(
    new URL('../application/single_app/static/js/workspace/workspace_workflows.js', import.meta.url), 'utf8',
);
const projectionSource = workflowSource.match(/function getCustomEndpointOptions\(\) \{[\s\S]*?\n\}/)?.[0];
assert.ok(projectionSource, 'Expected the shared workflow/task endpoint projection.');
const windowState = {
    globalModelEndpoints: endpoints,
    workspaceModelEndpoints: [{
        id: 'group', models: [
            { id: 'group-chat', capability_status: { chat: { available: true } } },
            { id: 'group-image', capability_status: { chat: { available: false } } },
        ],
    }],
};
const originalWindowState = structuredClone(windowState);
const getCustomEndpointOptions = vm.runInNewContext(`(${projectionSource})`, {
    window: windowState,
    workflowWorkspaceConfig: { workspaceEndpointScope: 'group', workspaceEndpointLabel: 'Group' },
    normalizeText: (value) => String(value || '').trim(),
    isChatModelAvailable,
});
const workflowChoices = getCustomEndpointOptions();
assert.deepEqual(Array.from(workflowChoices, (item) => [item.id, item.models.map((entry) => entry.id)]), [
    ['mixed', ['chat', 'legacy-chat']], ['second', ['chat']], ['group', ['group-chat']],
]);
assert.equal(workflowChoices[2].scope, 'group');
assert.deepEqual(windowState, originalWindowState);
assert.notEqual(workflowChoices[0].models, endpoints[0].models);
console.log('PASS: Classic agent/workflow capability projections, scoped identities, and legacy chat mode.');
