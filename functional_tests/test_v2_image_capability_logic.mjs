// test_v2_image_capability_logic.mjs
// Version: 0.261.107
// Implemented in: 0.261.107
// Execute server-profile normalization, image operation validation and both revision transports.
// React/store imports are blocked only for the pure helper tests; the browser suite exercises
// the actual hooks, state and components. No provider or application server is contacted.

import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import './test_support/tsResolve.mjs';

const revisionsUrl = new URL('../application/v2_ui/src/lib/imageRevisions.ts', import.meta.url);
const unusedDependency = `
    function unused() { throw new Error('A pure image helper accessed a React/store dependency.'); }
    export { unused as useCallback, unused as useMemo, unused as useState,
        unused as useChatStore, unused as useBootstrapStore };
`;
const boundary = registerHooks({
    resolve(specifier, context, nextResolve) {
        if (context.parentURL === revisionsUrl.href
            && ['react', '../stores/chatStore', '../stores/bootstrapStore'].includes(specifier)) {
            return {
                shortCircuit: true,
                url: `data:text/javascript,${encodeURIComponent(unusedDependency)}`,
            };
        }
        return nextResolve(specifier, context);
    },
});
const {
    describeImageRevisionProblem,
    describeInstructionProblem,
    describePromptProblem,
    imageOptionsForCapability,
    imageRevisionOperation,
    toImageEditCapability,
} = await import(revisionsUrl);
boundary.deregister();

const {
    canGenerateImage,
    capabilityDescription,
    toCapabilityModelsResponse,
} = await import('../application/v2_ui/src/lib/capabilityModels.ts');
const { choiceToSelection, groupChoicesByConnection } = await import(
    '../application/v2_ui/src/lib/modelConnections.ts'
);
const { addMessageImageRevision } = await import('../application/v2_ui/src/lib/endpoints.ts');
const { addCollaborationImageRevision } = await import('../application/v2_ui/src/lib/collaboration.ts');
const { ApiError } = await import('../application/v2_ui/src/lib/apiClient.ts');

function profile(overrides = {}) {
    return {
        enabled: true,
        mode: 'masked',
        model_name: 'image-model',
        provider_label: 'Configured provider',
        cloud_label: 'Configured endpoint cloud',
        availability: 'documented',
        availability_reason: '',
        reason: '',
        editing: true,
        masking: true,
        sizes: ['1024x1024', '1536x1024', '1024x1536'],
        qualities: ['low', 'medium', 'high'],
        backgrounds: ['opaque', 'transparent'],
        ...overrides,
    };
}

function support(overrides = {}) {
    const { enabled, ...metadata } = profile();
    assert.equal(enabled, true);
    return {
        supported: true, source: 'catalog', api: 'images',
        lifecycle: 'preview', publisher: 'Publisher',
        ...metadata, ...overrides,
    };
}

function modelResponse(status, overrides = {}) {
    return {
        capability: 'image_generation',
        enabled: true,
        selection: { endpoint_id: 'saved:connection', model_id: 'saved:model', provider: 'custom' },
        choices: [{
            endpoint_id: 'saved:connection', model_id: 'saved:model', provider: 'custom',
            connection_name: 'Images', label: 'Saved image', deployment_name: 'deployment',
            capability: status,
        }],
        ...overrides,
    };
}

const checks = [];
const check = (name, run) => checks.push([name, run]);
const masked = toImageEditCapability(profile());
const reference = toImageEditCapability(profile({
    mode: 'edit', masking: false, model_name: 'MAI-Image-2.6',
    sizes: ['1024x1024', '1024x768', '768x1024'], qualities: [], backgrounds: [],
}));
const regenerate = toImageEditCapability(profile({
    mode: 'regenerate', editing: false, masking: false, model_name: 'FLUX-1.1-pro',
}));

check('unresolved and malformed profiles fail closed, not to regeneration', () => {
    for (const value of [undefined, null, [], 'masked', {}, { mode: 'regenerate' }]) {
        const capability = toImageEditCapability(value);
        assert.equal(capability.enabled, false);
        assert.equal(capability.mode, 'unavailable');
        assert.deepEqual(capability.sizes, []);
        assert.match(describeImageRevisionProblem(capability, { origin: 'ai' }), /unavailable/);
    }
});

check('explicit readiness and consistent operation flags are required', () => {
    for (const override of [
        { enabled: false }, { enabled: 'true' }, { mode: 'future' }, { masking: false },
        { editing: false }, { editing: undefined }, { masking: undefined },
        { mode: 'regenerate' }, { availability: 'unavailable' },
    ]) {
        const capability = toImageEditCapability(profile(override));
        assert.equal(capability.enabled, false, JSON.stringify(override));
        assert.equal(capability.mode, 'unavailable');
    }
    assert.equal(reference.enabled, true);
    assert.equal(regenerate.enabled, true);
});

check('unknown availability warns but does not invent a cloud ban or support', () => {
    const capability = toImageEditCapability(profile({
        model_name: 'new-private-model',
        availability: 'unknown',
        provider_label: 'Custom OpenAI',
        cloud_label: 'Government endpoint',
        availability_reason: 'This endpoint cloud has no published availability evidence.',
    }));
    assert.equal(capability.enabled, true);
    assert.equal(capability.availability, 'unknown');
    assert.equal(capability.mode, 'masked');
    assert.equal(capability.cloud_label, 'Government endpoint');
    assert.equal(capability.provider_label, 'Custom OpenAI');
    assert.match(capability.availability_reason, /published availability/);
});

check('safe projection keeps supplied labels but no credentials or endpoint URLs', () => {
    const capability = toImageEditCapability(profile({
        endpoint: 'https://private.example.test', api_key: 'not-a-key',
        model_name: '<img src=x onerror="window.injected=true">',
    }));
    assert.equal('endpoint' in capability, false);
    assert.equal('api_key' in capability, false);
    assert.equal(capability.model_name, '<img src=x onerror="window.injected=true">');
});

check('profile options are sanitized without adding GPT-only presets', () => {
    assert.deepEqual(reference.sizes, ['1024x1024', '1024x768', '768x1024']);
    assert.deepEqual(reference.qualities, []);
    assert.deepEqual(reference.backgrounds, []);
    const normalized = toImageEditCapability(profile({
        sizes: [' 1024x768 ', null, '1024x768', {}, '', 1024],
        qualities: undefined,
        backgrounds: 'transparent',
    }));
    assert.deepEqual(normalized.sizes, ['1024x768']);
    assert.deepEqual(normalized.qualities, []);
    assert.deepEqual(normalized.backgrounds, []);
});

check('unsupported local option selections are dropped after a profile change', () => {
    assert.deepEqual(imageOptionsForCapability(reference, {
        size: '1536x1024', quality: 'high', background: 'transparent',
    }), {});
    assert.deepEqual(imageOptionsForCapability(reference, {
        size: '1024x768', quality: 'high',
    }), { size: '1024x768' });
    assert.deepEqual(imageOptionsForCapability(masked, {
        size: '1024x1024', quality: 'medium', background: 'opaque',
    }), { size: '1024x1024', quality: 'medium', background: 'opaque' });
});

check('Ask AI edits sources only when the operation profile supports it', () => {
    assert.equal(imageRevisionOperation(masked, {}), 'edit');
    assert.equal(imageRevisionOperation(reference, { origin: 'ai' }), 'edit');
    assert.equal(imageRevisionOperation(regenerate, { origin: 'ai' }), 'regenerate');
    assert.equal(describeImageRevisionProblem(reference, { operation: 'edit' }), null);
    assert.match(describeImageRevisionProblem(regenerate, { operation: 'edit' }), /cannot edit a source image/);
    assert.match(describeImageRevisionProblem(masked, { operation: 'future' }), /operation is unavailable/);
});

check('prompt and control changes explicitly regenerate even on edit-capable models', () => {
    for (const capability of [masked, reference, regenerate]) {
        for (const origin of ['prompt', 'control']) {
            assert.equal(imageRevisionOperation(capability, { origin }), 'regenerate');
            assert.equal(describeImageRevisionProblem(capability, {
                origin, operation: 'regenerate',
            }), null);
        }
    }
    assert.equal(imageRevisionOperation(masked, { origin: 'ai', operation: 'regenerate' }), 'regenerate');
});

check('a stale mask is an error, never silently discarded for a different operation', () => {
    const request = { operation: 'edit', mask: 'data:image/png;base64,mask', maskRegions: 1 };
    assert.equal(describeImageRevisionProblem(masked, request), null);
    assert.match(describeImageRevisionProblem(reference, request), /cannot use a region mask/);
    assert.match(describeImageRevisionProblem(masked, { ...request, operation: 'regenerate' }), /cannot use a region mask/);
    assert.match(describeImageRevisionProblem(regenerate, {
        maskRegions: 1, operation: 'regenerate',
    }), /cannot use a region mask/);
});

check('stale sizes, quality and background fail before an inference request', () => {
    for (const options of [
        { size: '1536x1024' }, { quality: 'high' }, { background: 'transparent' },
    ]) {
        assert.match(describeImageRevisionProblem(reference, {
            origin: 'control', operation: 'regenerate', ...options,
        }), /does not support/);
    }
    assert.equal(describeImageRevisionProblem(reference, {
        origin: 'control', operation: 'regenerate', size: '1024x768',
    }), null);
});

check('feature-off inference stays disabled independently of stored history', () => {
    const disabled = toImageEditCapability(profile({ enabled: false, reason: 'Images are turned off.' }));
    for (const origin of ['ai', 'prompt', 'control']) {
        assert.equal(describeImageRevisionProblem(disabled, { origin }), 'Images are turned off.');
    }
    assert.match(describeInstructionProblem(''), /Describe/);
    assert.match(describePromptProblem(''), /empty/);
    assert.equal(describePromptProblem('A mountain.'), null);
});

check('MAI and FLUX are always labeled as image output, never text', () => {
    for (const api of ['images', 'responses', 'mai', 'flux']) {
        const description = capabilityDescription(support({ api }));
        assert.match(description, /image/i);
        assert.doesNotMatch(description, /Text output/);
    }
    assert.equal(capabilityDescription({ supported: true, source: 'catalog', api: 'chat' }), 'Text output · catalog');
    assert.match(capabilityDescription(support({ api: 'future-api' })), /Unrecognized/);
    assert.doesNotMatch(capabilityDescription(support({ api: '' })), /Text output/);
});

check('admin choices retain safe image profile metadata and registry identity', () => {
    const payload = modelResponse(support({
        api: 'mai', mode: 'edit', masking: false,
        sizes: reference.sizes, qualities: [], backgrounds: [],
        model_name: 'MAI-Image-2.6', endpoint: 'https://private.example.test', api_key: 'not-a-key',
    }));
    const parsed = toCapabilityModelsResponse(payload, 'image_generation');
    const choice = parsed.choices[0];
    assert.deepEqual(choiceToSelection(choice), payload.selection);
    assert.equal(choice.modelId, 'saved:model');
    assert.equal(choice.deploymentName, 'deployment');
    assert.equal(choice.capability.model_name, 'MAI-Image-2.6');
    assert.equal(choice.capability.publisher, 'Publisher');
    assert.equal(choice.capability.lifecycle, 'preview');
    assert.deepEqual(choice.capability.sizes, reference.sizes);
    assert.deepEqual(choice.capability.qualities, []);
    assert.equal('endpoint' in choice.capability, false);
    assert.equal('api_key' in choice.capability, false);
    assert.equal(canGenerateImage(choice.capability), true);
});

check('unavailable or unresolved admin image metadata cannot enable testing', () => {
    for (const override of [
        { api: 'future-api' }, { mode: 'unavailable' }, { mode: undefined },
        { availability: 'unavailable' }, { masking: false }, { editing: undefined },
        { mode: 'regenerate', editing: undefined, masking: undefined },
    ]) {
        const parsed = toCapabilityModelsResponse(modelResponse(support(override)), 'image_generation');
        assert.equal(canGenerateImage(parsed.choices[0].capability), false, JSON.stringify(override));
    }
    assert.equal(canGenerateImage(support({ availability: 'unknown' })), true);
    assert.equal(canGenerateImage(undefined), false);
});

check('disabled/dangling selections and duplicate labels do not silently change defaults', () => {
    const payload = modelResponse(support(), { enabled: false, reason: 'Saved model is unavailable.' });
    const second = { ...payload.choices[0], endpoint_id: 'other:connection' };
    const parsed = toCapabilityModelsResponse({
        ...payload, choices: [payload.choices[0], second],
    }, 'image_generation');
    assert.equal(parsed.enabled, false);
    assert.deepEqual(parsed.selection, payload.selection);
    assert.equal(groupChoicesByConnection(parsed.choices).length, 2);
    const dangling = toCapabilityModelsResponse({
        ...payload, choices: [{ ...payload.choices[0], capability: { supported: false } }],
    }, 'image_generation');
    assert.equal(dangling.choices.length, 0);
    assert.deepEqual(dangling.selection, payload.selection);
    assert.equal(dangling.reason, payload.reason);
});

check('personal and shared transports retain operation, origins and concurrency expectations', async () => {
    const originalFetch = globalThis.fetch;
    const calls = [];
    globalThis.fetch = async (url, init) => {
        calls.push({ url, method: init.method, body: JSON.parse(init.body) });
        return new Response(JSON.stringify({ success: true }), {
            status: 200, headers: { 'Content-Type': 'application/json' },
        });
    };
    try {
        for (const operation of ['edit', 'regenerate']) {
            const body = {
                conversation_id: 'conversation:1', origin: operation === 'edit' ? 'ai' : 'prompt',
                operation, instruction: 'Change the sky', prompt: 'A mountain',
                expected_revision_count: 2, expected_current_revision_id: 'revision:1',
                ...(operation === 'edit' ? { mask: 'data:image/png;base64,mask', mask_regions: 1 } : {}),
            };
            await addMessageImageRevision('image:1', body);
            await addCollaborationImageRevision('conversation:1', 'image:1', body);
            assert.deepEqual(calls.at(-2).body, body);
            assert.deepEqual(calls.at(-1).body, body);
            assert.equal(calls.at(-2).url, '/api/message/image%3A1/image-revision');
            assert.equal(calls.at(-1).url, '/api/collaboration/conversations/conversation%3A1/messages/image%3A1/image-revision');
        }
        assert.equal(calls.length, 4);
        globalThis.fetch = async () => new Response(JSON.stringify({ error: 'The model changed. Reopen the editor.' }), {
            status: 409, headers: { 'Content-Type': 'application/json' },
        });
        await assert.rejects(
            addMessageImageRevision('image:1', { conversation_id: 'conversation:1', operation: 'edit' }),
            (error) => error instanceof ApiError && error.status === 409,
        );
    } finally {
        globalThis.fetch = originalFetch;
    }
});

let failures = 0;
for (const [name, run] of checks) {
    try {
        await run();
        console.log(`  ok  ${name}`);
    } catch (error) {
        failures += 1;
        console.error(`  FAIL  ${name}`, error);
    }
}
console.log(`${checks.length - failures}/${checks.length} image capability checks passed.`);
process.exitCode = failures ? 1 : 0;
