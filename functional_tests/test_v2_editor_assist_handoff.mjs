// test_v2_editor_assist_handoff.mjs
// Version: 0.261.334
// Implemented in: 0.261.333
// Tests explicit, bounded, owner/workspace-scoped in-memory editor-session handoffs.

import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import './test_support/tsResolve.mjs';

const { makeSubmissionId } = await import('../application/v2_ui/src/lib/assistThread.ts');
const {
    MAX_AGENT_ASSIST_HANDOFFS, suspendAgentAssist, readAgentAssist, resumeAgentAssist,
    pruneAgentAssistHandoffs, clearAgentAssistHandoffs,
} = await import('../application/v2_ui/src/lib/editorAssistHandoff.ts');
const { useAssistThreadStore, newThread } = await import('../application/v2_ui/src/stores/assistThreadStore.ts');
const { useEditorAssistStore } = await import('../application/v2_ui/src/stores/editorAssistStore.ts');

const personal = { kind: 'personal' };
const group = { kind: 'group', id: 'group-a' };
const global = { kind: 'global' };

function session(visit = 'visit') {
    return { visit, open: true, stash: new Map(), scrollTop: 123, focusReference: 'new-action-test' };
}

function seedThread(key) {
    useAssistThreadStore.getState().updateThread(key, 'agent-editor', (record) => ({
        ...record, draft: { ...record.draft, text: 'unsent follow-up' },
    }));
    useEditorAssistStore.getState().record(key, {
        threadKey: key, instruction: 'help', reply: 'drafted', outcome: 'explained',
        entries: [], before: {}, changes: [], newItems: [], warnings: [], undoSequence: 0,
    });
}

try {
    const cryptoDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
    try {
        Object.defineProperty(globalThis, 'crypto', { configurable: true, value: webcrypto });
        const uuid = makeSubmissionId();
        assert.match(uuid, /^[0-9a-f-]{36}$/);
        Object.defineProperty(globalThis, 'crypto', {
            configurable: true,
            value: { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) },
        });
        const ids = Array.from({ length: 50 }, () => makeSubmissionId());
        assert.equal(new Set(ids).size, ids.length);
        for (const id of ids) assert.match(id, /^assist-[0-9a-f]{32}$/);
        Object.defineProperty(globalThis, 'crypto', { configurable: true, value: undefined });
        assert.throws(() => makeSubmissionId(), /Secure randomness is unavailable/);
    } finally {
        if (cryptoDescriptor) Object.defineProperty(globalThis, 'crypto', cryptoDescriptor);
        else delete globalThis.crypto;
    }

    for (const [scope, path, actionPath] of [
        [personal, '/workspace/agents/new', '/workspace/actions/new'],
        [group, '/groups/group-a/agents/new', '/groups/group-a/actions/new'],
        [global, '/admin/agents/new', '/admin/actions/new'],
    ]) {
        const current = session(path);
        seedThread(path);
        suspendAgentAssist('owner', path, scope, current, path);
        const first = readAgentAssist('owner', path, scope);
        const repeated = readAgentAssist('owner', path, scope);
        assert.equal(first, current);
        assert.equal(repeated, current, 'Repeated render initializers must not consume the handoff.');
        assert.equal(readAgentAssist('other-user', path, scope), null);
        assert.equal(readAgentAssist('owner', path, { kind: 'group', id: 'group-b' }), null);
        assert.equal(readAgentAssist('owner', path, scope)?.scrollTop, 123);
        pruneAgentAssistHandoffs('owner', actionPath, `?returnTo=${encodeURIComponent(path)}`);
        assert.equal(readAgentAssist('owner', path, scope), current);

        // A suspended editor's thread is protected even when another editor fills the store.
        for (let index = 0; index < 60; index += 1) {
            useAssistThreadStore.getState().updateThread(`unrelated-${index}`, 'other', () => newThread('other', index));
        }
        const thread = useAssistThreadStore.getState().threads[path];
        assert.equal(thread?.draft.text, 'unsent follow-up');
        assert.ok(useEditorAssistStore.getState().turns[path]);
        pruneAgentAssistHandoffs('owner', path, '');
        resumeAgentAssist('owner', path, scope, current);
        resumeAgentAssist('owner', path, scope, current);
        assert.equal(readAgentAssist('owner', path, scope), null);
        assert.ok(useAssistThreadStore.getState().threads[path], 'Resume releases the extra hold, not the transcript.');
    }

    assert.throws(() => suspendAgentAssist('owner', 'https://untrusted.test/', personal, session(), null), /Invalid/);
    assert.throws(() => suspendAgentAssist('owner', '/groups/group-b/agents/new', group, session(), null), /Invalid/);
    assert.throws(() => suspendAgentAssist('owner', '/workspace/agents/new', global, session(), null), /Invalid/);

    for (const destination of [
        ['owner', '/workspace/actions', ''],
        ['other-user', '/workspace/actions/new', '?returnTo=%2Fworkspace%2Fagents%2Fnew'],
        ['owner', '/groups/group-b/actions/new', '?returnTo=%2Fworkspace%2Fagents%2Fnew'],
    ]) {
        seedThread('abandoned');
        suspendAgentAssist('owner', '/workspace/agents/new', personal, session(), 'abandoned');
        pruneAgentAssistHandoffs(...destination);
        assert.equal(readAgentAssist('owner', '/workspace/agents/new', personal), null);
        assert.equal(useAssistThreadStore.getState().threads.abandoned, undefined);
        assert.equal(useEditorAssistStore.getState().turns.abandoned, undefined);
    }

    for (let index = 0; index <= MAX_AGENT_ASSIST_HANDOFFS; index += 1) {
        seedThread(`bounded-${index}`);
        suspendAgentAssist('owner', `/workspace/agents/agent-${index}`, personal, session(), `bounded-${index}`);
    }
    assert.equal(readAgentAssist('owner', '/workspace/agents/agent-0', personal), null);
    assert.equal(useAssistThreadStore.getState().threads['bounded-0'], undefined);
    clearAgentAssistHandoffs();
    assert.equal(readAgentAssist('owner', '/workspace/agents/agent-1', personal), null);
    assert.equal(useEditorAssistStore.getState().turns['bounded-1'], undefined);
    console.log('Editor assist handoff lifecycle and isolation passed.');
} finally {
    clearAgentAssistHandoffs();
    useAssistThreadStore.getState().resetThreads();
    useEditorAssistStore.getState().reset();
}
