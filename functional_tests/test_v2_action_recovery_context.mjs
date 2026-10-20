// test_v2_action_recovery_context.mjs
// Version: 0.261.355
// Implemented in: 0.261.355
// Exercises the real recovery owner without React scheduling or external I/O.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const recovery = await import('../application/v2_ui/src/lib/actionRecovery.ts');
const initial = { actorId: 'actor-1', conversationId: null, agentSelection: 'agent-1' };
const originalFetch = globalThis.fetch;

try {
    const oldObserver = Symbol('old-view');
    const observer = Symbol('current-view');
    recovery.observeActionRecoveryContext(oldObserver, initial);
    recovery.observeActionRecoveryContext(observer, initial);
    const adopted = recovery.synchronizeActionRecoveryContext({ ...initial, conversationId: 'created' });
    const revision = recovery.getActionRecoveryRevision();
    recovery.releaseActionRecoveryContext(oldObserver);
    assert.equal(recovery.getActionRecoveryRevision(), revision);
    const observed = recovery.synchronizeActionRecoveryContext({ ...initial, conversationId: 'created' });
    assert.equal(observed, adopted);
    assert.equal(recovery.getActionRecoveryRevision(), revision);

    let resolveContext;
    globalThis.fetch = () => new Promise((resolve) => { resolveContext = resolve; });
    const pending = recovery.actionRecoveryHeaders();
    recovery.synchronizeActionRecoveryContext({ ...initial, conversationId: 'created' });
    resolveContext(new Response(JSON.stringify({ csrf_token: 'fixture-csrf' })));
    const headers = await pending;
    assert.deepEqual(headers, { 'X-CSRFToken': 'fixture-csrf' });

    for (const changed of [
        { ...initial, conversationId: 'unrelated' },
        { ...initial, actorId: 'actor-2' },
        { ...initial, agentSelection: 'agent-2' },
    ]) {
        recovery.synchronizeActionRecoveryContext(initial);
        const request = recovery.actionRecoveryHeaders();
        recovery.synchronizeActionRecoveryContext(changed);
        resolveContext(new Response(JSON.stringify({ csrf_token: 'stale-csrf' })));
        await assert.rejects(request, /selected chat context changed/);
        assert.deepEqual(recovery.currentActionRecoveryHeaders(), {});
    }
    recovery.clearActionRecovery();
    recovery.synchronizeActionRecoveryContext(initial);
    const beforeUnmount = recovery.getActionRecoveryRevision();
    recovery.releaseActionRecoveryContext(observer);
    assert.equal(recovery.getActionRecoveryRevision(), beforeUnmount + 1);
} finally {
    recovery.clearActionRecovery();
    globalThis.fetch = originalFetch;
}
console.log('Action recovery context ownership contracts passed.');
