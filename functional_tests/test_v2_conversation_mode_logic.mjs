// test_v2_conversation_mode_logic.mjs
// Version: 0.261.341
// Implemented in: 0.261.341
// Exercise the real account/conversation memory, draft adoption and storage failure boundaries.

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

const { ConversationModeMemory, CONVERSATION_MODE_PREFIX } =
    await import('../application/v2_ui/src/lib/conversationMode.ts');

function fixture() {
    const entries = new Map();
    let fail = '';
    const storage = {
        getItem: (key) => {
            if (fail === 'read') throw new Error('blocked');
            return entries.get(key) ?? null;
        },
        setItem: (key, value) => {
            if (fail === 'write') throw new Error('quota');
            entries.set(key, value);
        },
        removeItem: (key) => {
            if (fail === 'remove') throw new Error('blocked');
            entries.delete(key);
        },
        get length() { return entries.size; },
        key: (index) => [...entries.keys()][index] ?? null,
    };
    return { entries, storage, memory: new ConversationModeMemory(() => storage), fail: (value) => { fail = value; } };
}

function testExplicitChoicesOnly() {
    const { memory, entries, storage } = fixture();
    const absent = memory.read('alice', 'a');
    assert.equal(absent.choice, undefined);
    assert.equal(absent.storageFailed, false);
    assert.equal(entries.size, 0, 'reading a default never materializes it');
    const saved = memory.choose('alice', 'a', false);
    assert.equal(saved, true);
    assert.equal(memory.read('alice', 'a').choice, false);
    assert.equal(memory.read('alice', 'b').choice, undefined);
    assert.equal(memory.read('bob', 'a').choice, undefined);
    const reload = new ConversationModeMemory(() => storage);
    assert.equal(reload.read('alice', 'a').choice, false, 'off survives a new runtime');
    reload.choose('alice', 'b', true);
    assert.equal(reload.read('alice', 'b').choice, true);
    assert.equal(reload.read('alice', 'a').choice, false);
    memory.choose('a:b', 'c', false);
    memory.choose('a', 'b:c', true);
    assert.equal(memory.read('a:b', 'c').choice, false, 'key separators cannot collide');
    assert.equal(memory.read('a', 'b:c').choice, true);
}

function testDraftMigrationAndNavigationRace() {
    const { memory, entries } = fixture();
    memory.choose('alice', null, false);
    const first = memory.captureDraft('alice');
    assert.equal(entries.size, 0, 'a draft is not an account-wide default');
    memory.resetDraft();
    memory.choose('alice', null, true);
    const second = memory.captureDraft('alice');
    const adopted = memory.adoptDraft(first, 'created-offscreen');
    assert.equal(adopted, true);
    assert.equal(memory.read('alice', 'created-offscreen').choice, false);
    assert.equal(memory.read('alice', null).choice, true, 'an old response cannot consume a newer draft');
    memory.adoptDraft(second, 'created-current');
    assert.equal(memory.read('alice', 'created-current').choice, true);
    assert.equal(memory.read('alice', null).choice, undefined, 'the next new chat returns to the default');
    const noChoice = memory.captureDraft('alice');
    memory.adoptDraft(noChoice, 'default-chat');
    assert.equal(memory.read('alice', 'default-chat').choice, undefined);
}

function testResetLogoutAndPruning() {
    const { memory, storage, entries } = fixture();
    memory.choose('alice', 'a', false);
    memory.choose('bob', 'a', true);
    memory.choose('alice', null, false);
    const late = memory.captureDraft('alice');
    const cleared = memory.forgetAccount('alice');
    assert.equal(cleared, true);
    memory.adoptDraft(late, 'late-after-logout');
    assert.equal(memory.read('alice', 'late-after-logout').choice, undefined);
    assert.equal(memory.read('alice', null).choice, undefined);
    assert.equal(entries.size, 1, 'logout removes only this account');
    const reload = new ConversationModeMemory(() => storage);
    assert.equal(reload.read('alice', 'a').choice, undefined);
    assert.equal(reload.read('bob', 'a').choice, true);
    const removed = reload.forget('bob', 'a');
    assert.equal(removed, true);
    assert.equal(entries.size, 0);
    memory.choose('alice', null, false);
    const beforeReset = memory.captureDraft('alice');
    memory.reset();
    memory.adoptDraft(beforeReset, 'after-reset');
    assert.equal(memory.read('alice', 'after-reset').choice, undefined);
}

function testStorageFailureAndInvalidData() {
    const { memory, storage, entries, fail } = fixture();
    entries.set(`${CONVERSATION_MODE_PREFIX}alice:invalid`, '{"choice":false}');
    assert.equal(memory.read('alice', 'invalid').choice, undefined, 'only known scalar values are accepted');
    fail('read');
    const unavailable = memory.read('alice', 'blocked');
    assert.equal(unavailable.storageFailed, true);
    assert.equal(unavailable.choice, undefined);
    fail('write');
    const saved = memory.choose('alice', 'blocked', false);
    assert.equal(saved, false);
    assert.equal(memory.read('alice', 'blocked').choice, false, 'failed persistence keeps the current choice usable');
    const reload = new ConversationModeMemory(() => storage);
    assert.equal(reload.read('alice', 'blocked').choice, undefined);
    memory.choose('alice', null, false);
    const adopted = memory.adoptDraft(memory.captureDraft('alice'), 'new');
    assert.equal(adopted, false, 'draft adoption reports persistence failure too');
    assert.equal(memory.read('alice', 'new').choice, false);
    fail('remove');
    const removed = memory.forget('alice', 'new');
    assert.equal(removed, false);
    assert.equal(memory.read('alice', 'new').choice, undefined);
    const inaccessible = new ConversationModeMemory(() => { throw new Error('SecurityError'); });
    assert.equal(inaccessible.read('alice', 'a').storageFailed, true);
    const inaccessibleWrite = inaccessible.choose('alice', 'a', false);
    assert.equal(inaccessibleWrite, false);
    memory.choose('', 'a', false);
    assert.equal(memory.read('', 'a').choice, false, 'unidentified input is memory-only');
    assert.equal(entries.has(`${CONVERSATION_MODE_PREFIX}:a`), false);
    assert.equal(memory.read('alice', 'a').choice, undefined);
}

function testSubscriptions() {
    const { memory } = fixture();
    let notified = 0;
    const initial = memory.getRevision();
    const unsubscribe = memory.subscribe(() => { notified += 1; });
    memory.choose('alice', 'a', false);
    assert.equal(notified, 1);
    assert.ok(memory.getRevision() > initial);
    unsubscribe();
    memory.reset();
    assert.equal(notified, 1);
}

for (const test of [
    testExplicitChoicesOnly, testDraftMigrationAndNavigationRace, testResetLogoutAndPruning,
    testStorageFailureAndInvalidData, testSubscriptions,
]) {
    test();
    console.log(`PASS ${test.name}`);
}
