// test_v2_orchestration_model_routing_logic.mjs
// Version: 0.261.137
// Implemented in: 0.261.137
// Executes the real Orchestrate model resolver: Auto by default where it can work, a saved pin
// only while its model exists and the picker is reachable, and the picker value round trip.

import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';

registerHooks({
    resolve(specifier, context, nextResolve) {
        if (specifier.startsWith('.') && !/\.[cm]?[jt]sx?$/.test(specifier)) {
            return nextResolve(`${specifier}.ts`, context);
        }
        return nextResolve(specifier, context);
    },
});

const {
    AUTO_MODEL_VALUE,
    autoRoutingAvailable,
    isOrchestrationModelRouting,
    orchestrationModelUpdate,
    orchestrationModelValue,
    resolveOrchestrationModel,
} = await import('../application/v2_ui/src/lib/orchestrationModelRouting.ts');

const eligible = {
    selection_key: 'global::east:writer', display_name: 'Writer',
    profile: { id: 'gpt-5-mini', archived: false, tasks: { general: 'suitable' } },
    capabilities: { generatesText: true }, auto_routing_available: true,
};
const plain = { selection_key: 'global::west:plain', display_name: 'Plain' };

function resolve(overrides) {
    return resolveOrchestrationModel({
        models: [eligible, plain], pickerReachable: true, savedRouting: undefined,
        savedModelId: undefined, fallbackModel: 'global::west:plain', ...overrides,
    });
}

function testAvailability() {
    assert.equal(autoRoutingAvailable([eligible]), true);
    assert.equal(autoRoutingAvailable([{ ...eligible, profile: { ...eligible.profile, tasks: { general: 'strong' } } }]), true);
    assert.equal(autoRoutingAvailable([plain]), false, 'a model with no catalog profile cannot be routed');
    assert.equal(autoRoutingAvailable([{ ...eligible, profile: { archived: true, tasks: { general: 'suitable' } } }]), false);
    assert.equal(autoRoutingAvailable([{ ...eligible, profile: { archived: false } }]), false,
        'without a general rating, steps no model is rated for could not be routed');
    for (const rating of ['unknown', 'unsuitable', '', null]) {
        assert.equal(autoRoutingAvailable([{
            ...eligible, profile: { archived: false, tasks: { general: rating, summarization: 'strong' } },
        }]), false, `general rated ${String(rating)}`);
    }
    assert.equal(autoRoutingAvailable([{ ...eligible, capabilities: { generatesText: false } }]), false);
    assert.equal(autoRoutingAvailable([{ ...eligible, capabilities: {} }]), false);
    assert.equal(autoRoutingAvailable([{ ...eligible, auto_routing_available: false }]), false);
    assert.equal(autoRoutingAvailable([{ ...eligible, profile: null }]), false);
    assert.equal(autoRoutingAvailable([]), false);
    assert.equal(autoRoutingAvailable(undefined), false);
}

function testDefaults() {
    assert.deepEqual(resolve({}), { routing: 'auto', model: undefined, autoAvailable: true });
    for (const saved of ['auto', 'bogus', 7, null, {}]) {
        assert.deepEqual(resolve({ savedRouting: saved }).routing, 'auto', `saved ${String(saved)}`);
    }
    assert.deepEqual(resolve({ models: [plain] }), {
        routing: 'manual', model: 'global::west:plain', autoAvailable: false,
    }, 'without an eligible model the ordinary chat model applies');
}

function testPins() {
    assert.deepEqual(resolve({ savedRouting: 'manual', savedModelId: 'global::east:writer' }), {
        routing: 'manual', model: 'global::east:writer', autoAvailable: true,
    });
    assert.deepEqual(resolve({ savedRouting: 'manual', savedModelId: '  global::east:writer  ' }).model,
        'global::east:writer');
    assert.equal(resolve({ savedRouting: 'manual', savedModelId: 'global::gone:model' }).routing, 'auto',
        'a pin whose model is gone falls back to the default, not to the normal chat model');
    assert.equal(resolve({ savedRouting: 'manual', savedModelId: '' }).routing, 'auto');
    assert.equal(resolve({ savedRouting: 'manual', savedModelId: 42 }).routing, 'auto');
    assert.equal(resolve({ savedRouting: 'auto', savedModelId: 'global::east:writer' }).routing, 'auto',
        'Auto keeps an earlier pin without using it');
    assert.deepEqual(resolve({
        models: [plain], savedRouting: 'manual', savedModelId: 'global::gone:model',
    }), { routing: 'manual', model: 'global::west:plain', autoAvailable: false });
}

function testHiddenPicker() {
    assert.deepEqual(resolve({
        pickerReachable: false, savedRouting: 'manual', savedModelId: 'global::east:writer',
    }), { routing: 'auto', model: undefined, autoAvailable: true },
    'a pin the user cannot see or change never decides their requests');
    assert.deepEqual(resolve({
        models: [plain], pickerReachable: false, savedRouting: 'manual', savedModelId: 'global::west:plain',
    }).model, 'global::west:plain');
}

function testPickerValues() {
    assert.equal(orchestrationModelValue(resolve({})), AUTO_MODEL_VALUE);
    assert.equal(orchestrationModelValue(resolve({
        savedRouting: 'manual', savedModelId: 'global::east:writer',
    })), 'global::east:writer');
    assert.deepEqual(orchestrationModelUpdate(AUTO_MODEL_VALUE), { orchestrationModelRouting: 'auto' });
    assert.deepEqual(orchestrationModelUpdate('global::east:writer'), {
        orchestrationModelRouting: 'manual', orchestrationPreferredModelId: 'global::east:writer',
    });
    assert.equal(isOrchestrationModelRouting('auto'), true);
    assert.equal(isOrchestrationModelRouting('manual'), true);
    assert.equal(isOrchestrationModelRouting('Auto'), false);
    assert.equal(isOrchestrationModelRouting(undefined), false);
}

for (const test of [testAvailability, testDefaults, testPins, testHiddenPicker, testPickerValues]) {
    test();
    console.log(`ok ${test.name}`);
}
