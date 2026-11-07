// test_v2_orchestration_approval_logic.mjs
// Version: 0.261.101
// Implemented in: 0.261.101
// Executes the real approval resolver and settings store, including overlapping saves.

import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { mock } from 'node:test';
import { setImmediate as nextTurn } from 'node:timers/promises';
import {
    isApprovalMode,
    resolveOrchestrationApproval,
} from '../application/v2_ui/src/lib/orchestrationApproval.ts';

registerHooks({
    resolve(specifier, context, nextResolve) {
        if (specifier.startsWith('.') && !/\.[cm]?[jt]sx?$/.test(specifier)) {
            return nextResolve(`${specifier}.ts`, context);
        }
        return nextResolve(specifier, context);
    },
});

let fetchImpl = () => {
    throw new Error('Unexpected request without an installed settings fixture.');
};
globalThis.fetch = (...args) => fetchImpl(...args);
const { useUserSettingsStore } = await import('../application/v2_ui/src/stores/userSettingsStore.ts');
const state = () => useUserSettingsStore.getState();
const key = 'orchestrationApprovalMode';
const modes = ['manual', 'timed', 'auto'];

function response(body, status = 200) {
    return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
    });
}

async function loadSettings(settings = { [key]: 'manual', darkModeEnabled: false }) {
    await state().flush();
    fetchImpl = async (url, init) => {
        assert.equal(url, '/api/user/settings');
        assert.equal(init.method, 'GET');
        return response({ settings });
    };
    await state().load();
    assert.equal(state().loading, false);
    assert.equal(state().error, null);
}

function holdWrites() {
    const writes = [];
    fetchImpl = (url, init) => {
        assert.equal(url, '/api/user/settings');
        assert.equal(init.method, 'POST');
        return new Promise((resolve) => {
            writes.push({
                payload: JSON.parse(init.body).settings,
                finish(status = 200) {
                    resolve(response(
                        status === 200 ? { message: 'Saved' } : { error: 'Could not save preference' },
                        status,
                    ));
                },
            });
        });
    };
    return writes;
}

function testResolution() {
    for (const defaultMode of modes) {
        const policy = { default_approval_mode: defaultMode, allow_user_approval_override: true };
        assert.deepEqual(resolveOrchestrationApproval(policy, undefined), {
            mode: defaultMode, invalidPreference: false,
        });
        for (const saved of modes) {
            assert.equal(isApprovalMode(saved), true);
            assert.deepEqual(resolveOrchestrationApproval(policy, saved), {
                mode: saved, invalidPreference: false,
            });
            assert.deepEqual(resolveOrchestrationApproval(
                { ...policy, allow_user_approval_override: false }, saved,
            ), { mode: defaultMode, invalidPreference: false });
        }
        for (const invalid of [null, '', 'Manual', 'unknown', 1, false, {}, []]) {
            assert.equal(isApprovalMode(invalid), false);
            assert.equal(resolveOrchestrationApproval(policy, invalid).invalidPreference, true);
        }
    }
    assert.deepEqual(resolveOrchestrationApproval(undefined, 'auto'), {
        mode: 'manual', invalidPreference: false,
    });
    assert.deepEqual(resolveOrchestrationApproval({
        default_approval_mode: 'unknown', allow_user_approval_override: true,
    }, undefined), { mode: 'manual', invalidPreference: false });
}

async function testDebounceAndPartialUpdates() {
    await loadSettings({ [key]: 'manual', reasoningEffortSettings: { 'gpt-5': 'high' } });
    const writes = holdWrites();
    mock.timers.enable({ apis: ['setTimeout'] });
    try {
        state().update({ [key]: 'auto' });
        state().update({ [key]: 'timed', darkModeEnabled: true });
        mock.timers.tick(399);
        await nextTurn();
        assert.equal(writes.length, 0);
        mock.timers.tick(1);
        await nextTurn();
        assert.equal(writes.length, 1);
        assert.deepEqual(writes[0].payload, { [key]: 'timed', darkModeEnabled: true });
        writes[0].finish();
        await state().flush();
        assert.equal(writes.length, 1);
        assert.deepEqual(state().settings.reasoningEffortSettings, { 'gpt-5': 'high' });
    } finally {
        mock.timers.reset();
    }
}

async function testFlushSerializesAndKeepsLatestChoice() {
    await loadSettings();
    const writes = holdWrites();
    state().update({ [key]: 'auto' });
    const first = state().flush();
    await nextTurn();
    state().update({ [key]: 'timed', darkModeEnabled: true });
    let secondFinished = false;
    const second = state().flush().then(() => { secondFinished = true; });
    await nextTurn();
    assert.equal(writes.length, 1, 'The second request must wait for the first.');
    assert.equal(state().settings[key], 'timed');
    writes[0].finish();
    await first;
    await nextTurn();
    assert.equal(writes.length, 2);
    assert.equal(secondFinished, false, 'Flush must wait for its queued write.');
    assert.deepEqual(writes[1].payload, { [key]: 'timed', darkModeEnabled: true });
    writes[1].finish();
    await second;
    assert.equal(state().settings[key], 'timed');
    assert.equal(state().settings.darkModeEnabled, true);
    assert.equal(state().saveError, null);
}

async function testOlderFailureDoesNotRevertNewerChoice() {
    await loadSettings();
    const writes = holdWrites();
    state().update({ [key]: 'auto', darkModeEnabled: true });
    const first = state().flush();
    await nextTurn();
    state().update({ [key]: 'timed' });
    const seen = [];
    const unsubscribe = useUserSettingsStore.subscribe((value) => seen.push(value.settings[key]));
    try {
        writes[0].finish(500);
        await first;
        assert.equal(state().settings[key], 'timed');
        assert.equal(state().settings.darkModeEnabled, false, 'Only unchanged failed keys roll back.');
        assert.ok(state().saveError);
        assert.ok(seen.every((mode) => mode === 'timed'));
        const second = state().flush();
        await nextTurn();
        writes[1].finish(500);
        await second;
        assert.equal(state().settings[key], 'manual', 'Both failures must restore the confirmed mode.');
        assert.ok(state().saveError);
    } finally {
        unsubscribe();
    }
}

async function testRollbackUsesLastSuccessfulWrite() {
    await loadSettings();
    const writes = holdWrites();
    state().update({ [key]: 'auto' });
    const first = state().flush();
    await nextTurn();
    state().update({ [key]: 'timed' });
    const second = state().flush();
    writes[0].finish();
    await first;
    await nextTurn();
    writes[1].finish(500);
    await second;
    assert.equal(state().settings[key], 'auto');
    assert.equal(state().saving, false);
    assert.ok(state().saveError);
}

async function testReadFailureAndRetry() {
    await loadSettings();
    fetchImpl = async () => response({ error: 'Preferences unavailable' }, 500);
    await state().load();
    assert.equal(state().loading, false);
    assert.equal(state().error, 'Preferences unavailable');
    await loadSettings({ [key]: 'timed' });
    assert.equal(state().settings[key], 'timed');
}

const tests = [
    testResolution,
    testDebounceAndPartialUpdates,
    testFlushSerializesAndKeepsLatestChoice,
    testOlderFailureDoesNotRevertNewerChoice,
    testRollbackUsesLastSuccessfulWrite,
    testReadFailureAndRetry,
];
for (const test of tests) {
    await test();
    console.log(`Passed: ${test.name}`);
}
