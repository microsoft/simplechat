// test_v2_action_auth_execution.mjs
// Version: 0.261.107
// Implemented in: 0.261.107
// Real chat/orchestration stores and transports, with only HTTP and browser storage replaced.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

const stored = new Map();
const storage = {
    getItem: (key) => stored.get(key) ?? null,
    setItem: (key, value) => stored.set(key, String(value)),
    removeItem: (key) => stored.delete(key),
};
globalThis.window = {
    sessionStorage: storage, localStorage: storage,
    addEventListener() {}, removeEventListener() {}, setTimeout, clearTimeout, setInterval, clearInterval,
};
const { useChatStore } = await import('../application/v2_ui/src/stores/chatStore.ts');
const { useBootstrapStore } = await import('../application/v2_ui/src/stores/bootstrapStore.ts');
const { useCollaborationStore } = await import('../application/v2_ui/src/stores/collaborationStore.ts');
const { useOrchestrationStore, selectHasPlanHold } = await import('../application/v2_ui/src/stores/orchestrationStore.ts');
const { approveAndRunPlan, startOrchestrationPlan } = await import('../application/v2_ui/src/lib/orchestrationController.ts');
const { actionAuthController } = await import('../application/v2_ui/src/lib/actionAuthController.ts');
const { saveActionAuthCredentials } = await import('../application/v2_ui/src/lib/actionAuth.ts');
const { streamChat } = await import('../application/v2_ui/src/lib/sse.ts');

const options = {
    agentSelection: 'mission-agent', documentSearch: true, webSearch: false,
    imageGeneration: false, deepResearch: false, urlAccess: false,
    contextItems: [{ kind: 'document', id: 'document-1', label: 'Telemetry notes', scope: { kind: 'personal', id: null } }],
    promptInfo: { id: 'prompt-1', name: 'Inspect telemetry', content: 'Original context' },
};
function required(shared = false) {
    return {
        status: 'credentials_required', request_id: 'private-request', uses_personal_credentials: true,
        shared_conversation: shared, sharing_notice: null,
        requirements: [{
            id: 'required-yamcs', action_id: 'global-yamcs', action_name: 'Mission Yamcs',
            identity_name: 'Yamcs', auth_type: 'username_password', profile: 'yamcs_login',
            destination: 'https://yamcs.example.test/', reason: 'missing', identities: [],
        }],
    };
}
const ready = (shared = false) => ({ ...required(shared), status: 'ready', requirements: [] });
const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const sse = (frames) => new Response(frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join(''),
    { headers: { 'Content-Type': 'text/event-stream' } });
const calls = [];
const affectedActionRef = `action:v1:global:Z2xvYmFs:${Buffer.from('global-yamcs', 'utf8').toString('base64url')}`;
let preflightResult;
let streamControl = false;
let controlDiscriminator = 'error_code';
let executionStarted = true;
let shared = false;
let consumedRootReceipt = false;

function reset({ newChat = false, collaboration = false, readyIdentity = false } = {}) {
    actionAuthController.cancel();
    stored.clear();
    calls.length = 0;
    streamControl = false;
    controlDiscriminator = 'error_code';
    executionStarted = true;
    consumedRootReceipt = false;
    shared = collaboration;
    preflightResult = readyIdentity ? ready(shared) : required(shared);
    useChatStore.setState(useChatStore.getInitialState(), true);
    useOrchestrationStore.setState(useOrchestrationStore.getInitialState(), true);
    useCollaborationStore.setState(useCollaborationStore.getInitialState(), true);
    useBootstrapStore.setState({
        data: {
            user: { id: 'submitting-participant', display_name: 'Submitting participant' },
            catalogs: { agents: [{ id: 'mission-agent', name: 'mission', display_name: 'Mission', is_global: true }], models: [] },
            scope: {}, features: {},
        },
    });
    useChatStore.setState({
        activeConversationId: newChat ? null : 'visible-conversation',
        activeConversationKind: shared ? 'collaborative' : 'personal',
        conversations: [{ id: 'visible-conversation', title: 'Shared telemetry', user_id: 'different-owner', conversation_type: shared ? 'collaborative' : 'personal' }],
        messages: [], streaming: false,
    });
    useCollaborationStore.setState({
        conversation: shared ? { id: 'visible-conversation', can_post_messages: true, participants: [] } : null,
    });
    globalThis.fetch = async (url, init = {}) => {
        const body = init.body ? JSON.parse(init.body) : undefined;
        const path = String(url).split('?')[0];
        calls.push({ path, body, method: init.method ?? 'GET' });
        if (path === '/api/action-auth/preflight') {
            if (body.action_ref) return json({ ...preflightResult, request_id: 'private-action-repair' });
            if (consumedRootReceipt) return json({ error: 'The root plan is already finished.' }, 409);
            return json(preflightResult);
        }
        if (path.endsWith('/credentials')) {
            preflightResult = ready(shared);
            return json({ ...preflightResult, request_id: path.split('/').at(-2) });
        }
        if (path.startsWith('/api/action-auth/requests/')) {
            if (consumedRootReceipt && path.endsWith('/private-request')) return json({ error: 'This receipt was consumed.' }, 409);
            return json({ ...required(shared), request_id: path.split('/').at(-1) });
        }
        if (path === '/api/create_conversation') return json({ conversation_id: 'created-conversation' });
        if (path.endsWith('/retry') || path.endsWith('/edit')) return json({
            chat_request: { message: 'Original retry prompt', conversation_id: 'visible-conversation',
                agent_info: { id: 'mission-agent', name: 'mission', is_global: true }, action_auth_request_id: 'stale-receipt-must-not-survive' },
        });
        if (path === '/api/chat/stream' || path.endsWith('/stream') || path === '/api/v2/orchestration/run') {
            if (streamControl) {
                preflightResult = required(shared);
                consumedRootReceipt = executionStarted;
                return sse([{
                    [controlDiscriminator]: 'action_credentials_required', request_id: 'private-request',
                    action_ref: affectedActionRef, execution_started: executionStarted,
                    content: 'CONTROL-MUST-NOT-BECOME-ASSISTANT', auth_required: true, done: true,
                }]);
            }
            return sse([{ content: 'Telemetry result' }, {
                done: true, status: 'completed', message_id: 'answer-1', user_message_id: 'user-1',
                conversation_id: useChatStore.getState().activeConversationId,
            }]);
        }
        if (path === '/api/conversations/feed') return json({ conversations: [], has_more: false });
        if (path === '/api/get_messages') return json({ messages: [] });
        return json({ success: true, pending: false });
    };
}
async function waitFor(predicate) {
    for (let attempt = 0; attempt < 60; attempt += 1) {
        if (predicate()) return;
        await new Promise((resolve) => setImmediate(resolve));
    }
    throw new Error('Expected authentication state did not arrive.');
}
const requests = (path) => calls.filter((entry) => entry.path === path);
async function savePrivateCredential() {
    const submission = actionAuthController.startSubmission();
    assert.ok(submission);
    const state = await saveActionAuthCredentials(submission.requestId, 'required-yamcs', undefined, {
        username: 'synthetic-yamcs-user', password: 'synthetic-action-auth-password',
    }, submission.signal);
    actionAuthController.completeSubmission(submission, state);
}
function noSecretState() {
    for (const serialized of [
        JSON.stringify(useChatStore.getState()), JSON.stringify(useOrchestrationStore.getState()),
        JSON.stringify(actionAuthController.getSnapshot()), JSON.stringify([...stored]),
    ]) {
        assert.equal(serialized.includes('synthetic-action-auth-password'), false);
        assert.equal(serialized.includes('synthetic-yamcs-user'), false);
    }
    for (const call of calls.filter((entry) => !entry.path.endsWith('/credentials'))) {
        assert.equal(JSON.stringify(call).includes('synthetic-action-auth-password'), false);
    }
}

test('chat preflight precedes creation/optimistic messages and retains original context until one accepted send', async () => {
    reset({ newChat: true });
    let accepted = 0;
    const pending = useChatStore.getState().sendMessage('Original unsent prompt', options, {
        isCurrent: () => true, onAccepted: () => { accepted += 1; },
    });
    await waitFor(() => actionAuthController.getSnapshot()?.phase === 'waiting');
    assert.equal(useChatStore.getState().messages.length, 0);
    assert.equal(requests('/api/create_conversation').length, 0);
    assert.equal(accepted, 0);
    assert.equal(requests('/api/action-auth/preflight')[0].body.conversation_id, null);
    assert.equal(JSON.stringify(requests('/api/action-auth/preflight')).includes('Original unsent prompt'), false);
    await useChatStore.getState().sendMessage('Duplicate click', options);
    assert.equal(requests('/api/action-auth/preflight').length, 1);
    await savePrivateCredential();
    await pending;
    assert.equal(accepted, 1);
    assert.equal(requests('/api/create_conversation').length, 1);
    assert.equal(requests('/api/action-auth/preflight').length, 2);
    assert.equal(requests('/api/action-auth/preflight')[1].body.conversation_id, 'created-conversation');
    assert.equal(requests('/api/action-auth/requests/private-request/cancel').length, 1);
    const sent = requests('/api/chat/stream');
    assert.equal(sent.length, 1);
    assert.equal(sent[0].body.message, 'Original unsent prompt');
    assert.equal(sent[0].body.action_auth_request_id, 'private-request');
    assert.deepEqual(sent[0].body.selected_document_ids, ['document-1']);
    assert.deepEqual(sent[0].body.prompt_info, options.promptInfo);
    noSecretState();
});

test('cancel and conversation navigation never submit or clear the original draft', async () => {
    reset();
    let accepted = false;
    const pending = useChatStore.getState().sendMessage('Keep this draft', options, { isCurrent: () => true, onAccepted: () => { accepted = true; } });
    await waitFor(() => actionAuthController.getSnapshot()?.state);
    useChatStore.getState().startNewConversation();
    await pending;
    assert.equal(actionAuthController.getSnapshot(), null);
    assert.equal(accepted, false);
    assert.equal(requests('/api/chat/stream').length, 0);
    assert.equal(requests('/api/action-auth/requests/private-request/cancel').length, 1);
});

test('shared ready credentials still show a notice and execution uses visible conversation, never its owner', async () => {
    reset({ collaboration: true, readyIdentity: true });
    const pending = useChatStore.getState().sendMessage('Read live telemetry', options);
    await waitFor(() => actionAuthController.getSnapshot()?.state?.status === 'ready');
    assert.equal(useChatStore.getState().messages.length, 0);
    const preflight = requests('/api/action-auth/preflight')[0].body;
    assert.equal(preflight.conversation_kind, 'collaboration');
    assert.equal(preflight.conversation_id, 'visible-conversation');
    assert.equal(JSON.stringify(preflight).includes('different-owner'), false);
    actionAuthController.acknowledgeSharing(true);
    actionAuthController.continue();
    await pending;
    const sent = requests('/api/collaboration/conversations/visible-conversation/stream');
    assert.equal(sent.length, 1);
    assert.equal(sent[0].body.conversation_id, undefined);
    assert.equal(sent[0].body.action_auth_request_id, 'private-request');
    noSecretState();
});

test('retry and edit preflight original agent before mutating attempts and replace stale receipts', async () => {
    for (const method of ['retryMessage', 'editMessage']) {
        reset();
        useChatStore.setState({ messages: [{
            id: 'old-user-message', conversation_id: 'visible-conversation', role: 'user', content: 'Original retry prompt',
            metadata: { agent_selection: { agent_id: 'mission-agent', selected_agent: 'mission', is_global: true }, user_id: 'original-author-not-actor' },
        }] });
        const pending = useChatStore.getState()[method]('old-user-message', method === 'editMessage' ? 'Edited prompt' : undefined);
        await waitFor(() => actionAuthController.getSnapshot()?.state);
        assert.equal(calls.some((entry) => entry.path.endsWith('/retry') || entry.path.endsWith('/edit')), false);
        assert.equal(requests('/api/action-auth/preflight')[0].body.agent_info.id, 'mission-agent');
        await savePrivateCredential();
        await pending;
        assert.equal(requests('/api/chat/stream')[0].body.action_auth_request_id, 'private-request');
        assert.equal(JSON.stringify(requests('/api/action-auth/preflight')).includes('original-author-not-actor'), false);
        noSecretState();
    }
});

function setPlan() {
    useOrchestrationStore.getState().setPlan('visible-conversation', 'turn-1', {
        plan_id: 'plan-1', run_id: 'run-1', conversation_id: 'visible-conversation', turn_id: 'turn-1', revision: 1,
        user_id: 'plan-creator-not-actor', status: 'awaiting_approval',
        approval: { mode: 'manual', state: 'pending', timeout_seconds: 0 },
        intent: { summary: 'Read Yamcs', complexity: 'simple' },
        steps: [{ step_id: 'read', capability_id: 'action', title: 'Read telemetry', arguments: {} },
            { step_id: 'respond', capability_id: 'respond', title: 'Respond', arguments: {}, depends_on: ['read'] }],
    });
}

test('orchestration gates the executable run before persistent beginRun, and cancelled approval never auto-replays', async () => {
    reset();
    setPlan();
    const pending = approveAndRunPlan({ conversationId: 'visible-conversation', turnId: 'turn-1' });
    await waitFor(() => actionAuthController.getSnapshot()?.state);
    assert.equal(requests('/api/action-auth/preflight')[0].body.run_id, 'run-1');
    assert.deepEqual(useOrchestrationStore.getState().inFlight, {});
    assert.equal([...stored.values()].some((value) => value.includes('private-request')), false);
    actionAuthController.cancel();
    await pending;
    assert.equal(requests('/api/v2/orchestration/run').length, 0);
    assert.equal(selectHasPlanHold(useOrchestrationStore.getState(), 'visible-conversation', 'turn-1'), true);
    await approveAndRunPlan({ conversationId: 'visible-conversation', turnId: 'turn-1', automatic: true });
    assert.equal(requests('/api/action-auth/preflight').length, 1);
    const deliberatelyApproved = approveAndRunPlan({ conversationId: 'visible-conversation', turnId: 'turn-1' });
    await waitFor(() => actionAuthController.getSnapshot()?.state);
    await savePrivateCredential();
    await deliberatelyApproved;
    assert.equal(requests('/api/v2/orchestration/run').length, 1);
    assert.equal(requests('/api/v2/orchestration/run')[0].body.action_auth_request_id, 'private-request');
    noSecretState();
});

test('editing a plan while authenticating invalidates the request instead of running stale choices', async () => {
    reset();
    setPlan();
    const pending = approveAndRunPlan({ conversationId: 'visible-conversation', turnId: 'turn-1' });
    await waitFor(() => actionAuthController.getSnapshot()?.state);
    useOrchestrationStore.getState().disableStep('visible-conversation', 'turn-1', { step_id: 'read', capability_id: 'action' });
    await pending;
    assert.equal(actionAuthController.getSnapshot(), null);
    assert.equal(requests('/api/v2/orchestration/run').length, 0);
});

test('typed chat and orchestration runtime controls remain private and do not reconnect or replay', async () => {
    for (const [run, discriminator] of ['chat', 'orchestration'].flatMap((run) => ['type', 'error_code'].map((type) => [run, type]))) {
        reset({ readyIdentity: true });
        streamControl = true;
        controlDiscriminator = discriminator;
        if (run === 'chat') await useChatStore.getState().sendMessage('Read telemetry', options);
        else {
            setPlan();
            await approveAndRunPlan({ conversationId: 'visible-conversation', turnId: 'turn-1' });
        }
        await waitFor(() => actionAuthController.getSnapshot()?.state);
        assert.equal(actionAuthController.getSnapshot().executionStarted, true);
        assert.deepEqual(requests('/api/action-auth/preflight').at(-1).body, {
            action_ref: affectedActionRef, conversation_id: 'visible-conversation', conversation_kind: 'personal',
        });
        assert.equal(actionAuthController.getSnapshot().state.request_id, 'private-action-repair');
        assert.equal(requests('/api/action-auth/requests/private-request').length, 0);
        if (run === 'chat') assert.equal(useChatStore.getState().messages.filter((message) => message.role === 'user').length, 1);
        assert.equal(useChatStore.getState().streamError, null);
        assert.equal(useChatStore.getState().streamAuthUrl, null);
        assert.equal(JSON.stringify(useChatStore.getState().messages).includes('CONTROL-MUST-NOT-BECOME-ASSISTANT'), false);
        assert.equal(calls.some((call) => /reattach|stream\/status/.test(call.path)), false);
        await savePrivateCredential();
        assert.equal(actionAuthController.getSnapshot().repair, true);
        const executionCount = calls.filter((call) => call.path === '/api/chat/stream' || call.path === '/api/v2/orchestration/run').length;
        actionAuthController.continue();
        assert.equal(executionCount, 1);
        assert.equal(calls.filter((call) => call.path === '/api/chat/stream' || call.path === '/api/v2/orchestration/run').length, 1);
        noSecretState();
    }
});

test('an HTTP 200 control before execution does not accept or clear an unsent draft', async () => {
    reset({ readyIdentity: true });
    streamControl = true;
    controlDiscriminator = 'type';
    executionStarted = false;
    let accepted = 0;
    await useChatStore.getState().sendMessage('Retain this pre-execution draft', options, {
        isCurrent: () => true, onAccepted: () => { accepted += 1; },
    });
    await waitFor(() => actionAuthController.getSnapshot()?.state);
    assert.equal(accepted, 0);
    assert.equal(actionAuthController.getSnapshot().executionStarted, false);
    assert.deepEqual(useChatStore.getState().messages, []);
    await savePrivateCredential();
    actionAuthController.continue();
    assert.equal(requests('/api/chat/stream').length, 1);
    assert.equal(accepted, 0);
    noSecretState();
});

test('a planning control is private, not a clarification answer or generic assistant failure', async () => {
    reset();
    const previousFetch = globalThis.fetch;
    globalThis.fetch = async (url, init) => String(url).endsWith('/api/v2/orchestration/plan')
        ? sse([{
            type: 'action_credentials_required', request_id: 'private-request', execution_started: false,
            content: 'CONTROL-MUST-NOT-BECOME-ASSISTANT',
        }]) : previousFetch(url, init);
    await startOrchestrationPlan({
        conversationId: 'visible-conversation', message: 'Plan a telemetry review',
        approvalMode: 'manual', seeds: { agent_info: { id: 'mission-agent', name: 'mission', is_global: true } },
    });
    await waitFor(() => actionAuthController.getSnapshot()?.state);
    assert.equal(actionAuthController.getSnapshot().executionStarted, false);
    assert.equal(useChatStore.getState().streamError, null);
    assert.equal(useChatStore.getState().messages.some((message) => message.role === 'assistant'), false);
    assert.deepEqual(useOrchestrationStore.getState().elicitations, {});
    actionAuthController.cancel();
});

test('HTTP credential-required errors are not Foundry OAuth or stream-recovery requests', async () => {
    reset();
    let handoff;
    globalThis.fetch = async () => json({ error_code: 'action_credentials_required', request_id: 'private-request' }, 409);
    const result = await streamChat({ message: 'Example', conversation_id: 'visible-conversation' }, {
        onError: (_message, event) => { handoff = event; },
        onContent: () => assert.fail('A control was rendered as message content.'),
    });
    assert.equal(result.errored, true);
    assert.equal(handoff.error_code, 'action_credentials_required');
});
