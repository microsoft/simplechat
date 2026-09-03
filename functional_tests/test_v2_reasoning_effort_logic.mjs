// test_v2_reasoning_effort_logic.mjs
//
// Runtime test for the V2 per-model reasoning effort resolution.
// Version: 0.261.036
// Implemented in: 0.261.036
//
// The companion test, test_v2_reasoning_effort_persistence.py, asserts that the composer is
// wired to the shared user setting and that the keys it writes are ones the route accepts.
// Those are source assertions: they prove the pieces are connected, not that the right level
// comes out.
//
// This file executes the resolution itself, because its failure modes are all silent. A level
// stored under the wrong key is simply never found again. A stored level that the newly
// selected model does not accept is sent and then stripped by the endpoint, so the user sees a
// control claiming an effort that was never applied. And `none` is a real choice in the picker
// but not a value the endpoint takes, so sending it looks like a working request.
//
// Run directly with `node functional_tests/test_v2_reasoning_effort_logic.mjs`. Requires Node
// 22.6 or newer, which strips the TypeScript types so the real module can be imported rather
// than a copy of it.

import assert from 'node:assert/strict';
import {
    getModelSupportedLevels,
    reasoningModelKey,
    requestReasoningEffort,
    resolveReasoningEffort,
    supportsReasoning,
} from '../application/v2_ui/src/lib/reasoning.ts';

const checks = [];
function check(name, fn) {
    checks.push([name, fn]);
}

/* --------------------------------- the key ---------------------------------- */

check('a model is keyed by its model id, not its deployment name', () => {
    // getCurrentModelName() in chat-reasoning.js reads dataset.modelId first, so a level
    // stored by either interface has to land on the same entry.
    assert.equal(
        reasoningModelKey({ model_id: 'gpt-5-mini', deployment_name: 'chat-prod' }),
        'gpt-5-mini',
    );
});

check('the deployment name is used when there is no model id', () => {
    assert.equal(reasoningModelKey({ deployment_name: 'gpt-5-mini' }), 'gpt-5-mini');
    assert.equal(reasoningModelKey({ model_id: '   ', deployment_name: 'gpt-5' }), 'gpt-5');
});

check('a missing catalog record falls back to what the picker shows', () => {
    assert.equal(reasoningModelKey(undefined, 'gpt-5-mini'), 'gpt-5-mini');
    assert.equal(reasoningModelKey(undefined, undefined), '');
});

/* ------------------------------ stored levels -------------------------------- */

check('a stored level is restored for its own model', () => {
    const saved = { 'gpt-5-mini': 'high' };
    assert.equal(resolveReasoningEffort('gpt-5-mini', saved), 'high');
});

check('a level stored for one model does not follow the user to another', () => {
    const saved = { 'gpt-5-mini': 'high' };
    // o3 has its own entry, or it has not been chosen for and takes the default.
    assert.equal(resolveReasoningEffort('o3', saved), 'low');
});

check('a stored level the model does not accept is ignored', () => {
    // The 5.1 series skips `low`, so a level carried over from an o-series model cannot be
    // honoured and must not be sent for the endpoint to strip. It falls back the way
    // getCurrentModelReasoningEffort() does: `low` when offered, otherwise the first level,
    // which for this family is `none`.
    assert.equal(resolveReasoningEffort('gpt-5.1', { 'gpt-5.1': 'low' }), 'none');
    // gpt-5 has no `none`, so a stored `none` from a 5.1 model is discarded for `low`.
    assert.equal(resolveReasoningEffort('gpt-5', { 'gpt-5': 'none' }), 'low');
});

/* --------------------------------- defaults ---------------------------------- */

check('an unset model defaults to low, as the classic client does', () => {
    assert.equal(resolveReasoningEffort('gpt-5-mini', {}), 'low');
    assert.equal(resolveReasoningEffort('gpt-5-mini', undefined), 'low');
    assert.equal(resolveReasoningEffort('o3', undefined), 'low');
});

check('a model without low takes its first supported level', () => {
    // The 5.1 series offers none, minimal, medium and high.
    assert.equal(resolveReasoningEffort('gpt-5.1', {}), 'none');
});

check('gpt-5-pro is always high, whatever was stored', () => {
    assert.equal(resolveReasoningEffort('gpt-5-pro', {}), 'high');
    assert.equal(resolveReasoningEffort('gpt-5-pro', { 'gpt-5-pro': 'minimal' }), 'high');
});

check('no model selected still resolves to a level', () => {
    assert.equal(resolveReasoningEffort(undefined, undefined), 'low');
    assert.equal(resolveReasoningEffort('', {}), 'low');
});

/* ------------------------------- what is sent -------------------------------- */

check('none is never sent to the endpoint', () => {
    // getCurrentReasoningEffort() returns null for none; the endpoint takes no such value.
    assert.equal(requestReasoningEffort('none'), undefined);
    assert.equal(requestReasoningEffort(''), undefined);
    assert.equal(requestReasoningEffort(undefined), undefined);
});

check('a real level is passed through unchanged', () => {
    assert.equal(requestReasoningEffort('minimal'), 'minimal');
    assert.equal(requestReasoningEffort('high'), 'high');
});

/* ------------------------- models with no choice ----------------------------- */

check('a model with no reasoning offers nothing to choose', () => {
    for (const model of ['gpt-4o', 'gpt-4.1-mini', 'gpt-5-chat', 'gpt-5-codex']) {
        assert.deepEqual(getModelSupportedLevels(model), ['none'], model);
        assert.equal(supportsReasoning(model), false, model);
    }
});

check('a reasoning model does offer a choice', () => {
    for (const model of ['gpt-5', 'gpt-5.1', 'gpt-5-pro', 'o3']) {
        assert.equal(supportsReasoning(model), true, model);
    }
});

/* ----------------------------------- runner ---------------------------------- */

let passed = 0;
let failed = 0;

for (const [name, fn] of checks) {
    try {
        await fn();
        console.log(`ok   ${name}`);
        passed += 1;
    } catch (error) {
        console.log(`FAIL ${name}`);
        console.log(`     ${error.message}`);
        failed += 1;
    }
}

console.log(`\n${passed}/${passed + failed} runtime checks passed`);
process.exit(failed > 0 ? 1 : 0);
