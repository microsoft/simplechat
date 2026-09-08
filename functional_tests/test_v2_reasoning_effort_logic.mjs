// test_v2_reasoning_effort_logic.mjs
// Version: 0.261.104
// Implemented in: 0.261.104
// Execute real frontend resolution against the canonical Python policy, not a second family table.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import {
    getModelSupportedLevels, reasoningModelKey, requestReasoningEffort,
    resolveReasoningEffort, resolveReasoningSelection, supportsReasoning,
    normalizeReasoningAdjustments, reasoningAdjustmentMessage,
    reasoningMetadataForEvent,
} from '../application/v2_ui/src/lib/reasoning.ts';

const root = fileURLToPath(new URL('../', import.meta.url));
const policies = JSON.parse(execFileSync('python', ['-c', `
import json, sys
sys.path.insert(0, r'application\\single_app')
from functions_model_capabilities import resolve_model_reasoning_policy
print(json.dumps({name: resolve_model_reasoning_policy(name) for name in
    ['gpt-5.6-luna', 'gpt-5', 'gpt-5.1', 'gpt-5-pro', 'o3', 'gpt-4o', 'unknown-private-model']}))
`], { cwd: root, encoding: 'utf8' }));
const luna = policies['gpt-5.6-luna'];
const checks = [];
const check = (name, run) => checks.push([name, run]);

check('storage keys stay id-first, independently of canonical identity', () => {
    assert.equal(reasoningModelKey({ model_id: 'opaque-uuid', deployment_name: 'chat-prod' }), 'opaque-uuid');
    assert.equal(reasoningModelKey({ deployment_name: 'chat-prod' }), 'chat-prod');
    assert.equal(reasoningModelKey(undefined, 'old-key'), 'old-key');
    assert.equal(reasoningModelKey(undefined), '');
});
check('Luna accepts exactly the observed endpoint levels', () => {
    assert.deepEqual(getModelSupportedLevels(luna), ['none', 'low', 'medium', 'high', 'xhigh']);
    assert.equal(getModelSupportedLevels(policies['gpt-5']).includes('minimal'), true);
    assert.equal(getModelSupportedLevels(policies['gpt-5.1']).includes('low'), true);
});
check('stale Minimal resolves to Low without mutating unrelated preferences', () => {
    const saved = { 'opaque-uuid': 'minimal', other: 'high' };
    assert.deepEqual(resolveReasoningSelection('opaque-uuid', saved, luna), {
        requested_effort: 'minimal', effective_effort: 'low',
        mode: 'explicit', adjustment_reason: 'unsupported_effort',
    });
    assert.deepEqual(saved, { 'opaque-uuid': 'minimal', other: 'high' });
    assert.equal(resolveReasoningEffort('other', saved, luna), 'high');
    assert.equal(resolveReasoningEffort('new-model', saved, luna), 'low');
});
check('every catalog-supported choice survives unchanged, including None', () => {
    for (const policy of Object.values(policies)) {
        for (const level of getModelSupportedLevels(policy)) {
            assert.equal(resolveReasoningEffort('id', { id: level }, policy), level);
            assert.equal(requestReasoningEffort(level, policy), level);
        }
    }
    assert.equal(requestReasoningEffort('none', luna), 'none');
    assert.equal(requestReasoningEffort(undefined, luna), undefined);
    assert.equal(requestReasoningEffort('minimal', luna), undefined);
});
check('unknown and unsupported policies never invent supported levels', () => {
    for (const policy of [undefined, policies['gpt-4o'], policies['unknown-private-model']]) {
        assert.deepEqual(getModelSupportedLevels(policy), []);
        assert.equal(supportsReasoning(policy), false);
        assert.equal(resolveReasoningEffort('id', { id: 'high' }, policy), undefined);
        assert.equal(requestReasoningEffort('none', policy), undefined);
    }
});
check('a single-level policy uses its supported fallback', () => {
    assert.equal(resolveReasoningEffort('pro', { pro: 'low' }, policies['gpt-5-pro']), 'high');
});
check('safe notices describe omission as Model default and ignore provider error prose', () => {
    const adjustment = {
        requested_effort: 'minimal', effective_effort: null, mode: 'model_default',
        adjustment_reason: '<script>provider secrets</script>', stage: 'answer',
    };
    assert.equal(normalizeReasoningAdjustments([null, {}, adjustment]).length, 1);
    assert.equal(reasoningAdjustmentMessage(adjustment), 'Answer: Minimal could not be used; using Model default.');
});
check('latest stage/model correction wins without merging planner and answer notices', () => {
    const first = {
        requested_effort: 'minimal', effective_effort: 'low', mode: 'explicit',
        adjustment_reason: 'unsupported_effort', stage: 'answer', model_name: 'gpt-5.6-luna',
    };
    const planner = { ...first, stage: 'planner' };
    const latest = { ...first, effective_effort: null, mode: 'model_default', adjustment_reason: 'provider_rejected' };
    assert.deepEqual(normalizeReasoningAdjustments([first, planner, latest]), [latest, planner]);
    assert.deepEqual(normalizeReasoningAdjustments([first, { ...latest, adjustment_reason: null }]), []);
    const cleared = { ...first, requested_effort: 'low', adjustment_reason: null };
    assert.deepEqual(normalizeReasoningAdjustments([cleared], [latest, planner]), [planner]);
    assert.deepEqual(normalizeReasoningAdjustments(undefined, [latest, planner]), [latest, planner]);
    assert.deepEqual(reasoningMetadataForEvent({
        reasoning_adjustments: [cleared],
    }, [latest, planner]), { reasoning_adjustments: [planner] });
    assert.deepEqual(reasoningMetadataForEvent({
        metadata: { unrelated: 'keep', reasoning_adjustments: [cleared] },
    }, [latest, planner]), { unrelated: 'keep', reasoning_adjustments: [planner] });
});
check('terminal public reasoning fields override stale metadata without losing other fields', () => {
    assert.deepEqual(reasoningMetadataForEvent({
        metadata: { reasoning_effort: 'minimal', unrelated: 'keep' },
        reasoning_effort: null,
        requested_reasoning_effort: 'minimal',
        reasoning_mode: 'model_default',
        reasoning_adjustments: [],
    }), {
        unrelated: 'keep', reasoning_effort: null, requested_reasoning_effort: 'minimal',
        reasoning_mode: 'model_default', reasoning_adjustments: [],
    });
});
check('classic and V2 agree for the same projected policy and stored preference', () => {
    const option = { dataset: {
        modelId: 'opaque-uuid', modelName: 'gpt-5.6-luna', deploymentName: 'prod',
        reasoningCapabilities: JSON.stringify(luna),
    } };
    const modelSelect = { value: 'prod', selectedIndex: 0, options: [option] };
    const source = readFileSync(new URL('../application/single_app/static/js/chat/chat-reasoning.js', import.meta.url), 'utf8')
        .replace(/^import .*;$/gm, '').replace(/^export /gm, '');
    const context = vm.createContext({
        document: { getElementById: (id) => id === 'model-select' ? modelSelect : null },
        console,
    });
    vm.runInContext(source, context);
    for (const level of ['minimal', ...luna.efforts]) {
        vm.runInContext(`reasoningEffortSettings = { 'opaque-uuid': '${level}' };`, context);
        assert.equal(
            vm.runInContext('getCurrentReasoningEffort()', context),
            resolveReasoningEffort('opaque-uuid', { 'opaque-uuid': level }, luna),
        );
    }
    option.dataset.reasoningCapabilities = JSON.stringify(policies['unknown-private-model']);
    assert.equal(vm.runInContext('getCurrentReasoningEffort()', context), null);
});

for (const [name, run] of checks) {
    await run();
    console.log(`ok ${name}`);
}
console.log(`${checks.length}/${checks.length} reasoning behavior checks passed`);
