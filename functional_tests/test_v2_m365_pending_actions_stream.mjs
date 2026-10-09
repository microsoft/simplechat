// test_v2_m365_pending_actions_stream.mjs
// Version: 0.261.307
// Implemented in: 0.261.307
// Executes the live paths that put a Microsoft 365 outgoing-action card in front of someone in V2
// chat: the notification hand-off that asks the page to bring a card into view, the SSE reader that
// gives saved actions to the chat store ahead of the answer text, a real send whose stream is held
// open and fed server-shaped frames so the card's position can be read at every step (under the
// turn while the reply streams, under the reply once it exists), and the shared-conversation events
// that tell every participant to read the list again. Only HTTP and EventSource are simulated; the
// chat store, the pending-action store and the stream and event readers are the real ones.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

// The repository resolver must be registered before extensionless TypeScript imports load.
const { useChatStore } = await import('../application/v2_ui/src/stores/chatStore.ts');
const { chatPendingActionsStore } = await import('../application/v2_ui/src/stores/m365PendingActionsStore.ts');
const { carriesPendingActions, streamChat } = await import('../application/v2_ui/src/lib/sse.ts');
const { dispatchCollaborationEvent, subscribeToCollaborationEvents } = await import(
    '../application/v2_ui/src/lib/collaborationEvents.ts'
);
const { openConversationFromNotification, openNotificationTarget } = await import(
    '../application/v2_ui/src/lib/notificationNavigation.ts'
);
const { chatHrefForConversation, chatHrefForPendingAction } = await import(
    '../application/v2_ui/src/lib/conversationUrl.ts'
);
const { normalizeNotification } = await import('../application/v2_ui/src/lib/notifications.ts');
const { resolveNotificationLink } = await import('../application/v2_ui/src/lib/notificationLinks.ts');
const {
    ORPHAN_ANCHOR,
    PENDING_ACTIONS_UNAVAILABLE_MESSAGE,
    STREAMING_ANCHOR,
    lastMessageByRequestId,
    resolveAnchor,
} = await import('../application/v2_ui/src/lib/m365PendingActions.ts');

const ORIGIN = 'https://simplechat.test';
const STREAM_PATH = '/api/chat/stream';
const LIST_PATH = '/api/msgraph/pending-actions';
const T1 = '2026-05-01T10:00:00Z';
const T2 = '2026-05-01T10:05:00Z';

const chat = () => useChatStore.getState();
const store = () => chatPendingActionsStore.getState();

/** A saved outgoing action as the server serializes it. */
function action(id = 'act-1', overrides = {}) {
    return {
        type: 'msgraph_pending_action',
        id,
        version: 'v1',
        status: 'pending',
        operation: 'send_mail',
        graph_resource_type: 'mail',
        subject: 'Quarterly numbers',
        summary: { subject: 'Quarterly numbers', body_preview: 'Hello', body_preview_truncated: false },
        can_cancel: true,
        can_send_now: true,
        viewer_is_owner: true,
        review_details_required: false,
        updated_at: T1,
        ...overrides,
    };
}

function json(body, status = 200) {
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((res, rej) => {
        resolve = res;
        reject = rej;
    });
    return { promise, resolve, reject };
}

/** Wait, a turn of the event loop at a time, until the store has caught up with what was fed to it. */
async function settled(condition, description = 'the condition') {
    for (let turn = 0; turn < 500; turn += 1) {
        if (condition()) return;
        await new Promise((resolve) => setTimeout(resolve, 0));
    }
    throw new Error(`${description} was never met`);
}

const requestUrl = (input) =>
    new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost');

function resetStores() {
    useChatStore.setState({ ...useChatStore.getInitialState() }, true);
    store().reset();
}

/**
 * Open a conversation the way the chat page does.
 *
 * Both stores are reset first and the conversation is set on a clean state, because the chat
 * store only tells the pending-action store about a conversation when its id changes: reopening
 * the id a previous test left behind would leave the pending-action store with no conversation
 * and every frame for it would be dropped.
 */
function openConversation(conversationId, extra = {}) {
    resetStores();
    useChatStore.setState(
        {
            ...useChatStore.getInitialState(),
            activeConversationId: conversationId,
            activeConversationKind: 'personal',
            conversations: [{ id: conversationId, title: 'Quarterly comparison' }],
            ...extra,
        },
        true,
    );
}

/** Where the thread draws a saved action: the same question the chat page asks for every card. */
function anchorOf(id) {
    const pending = store();
    const entry = pending.entries[id];
    assert.ok(entry, `${id} is not a card in the store`);
    const anchorable = chat().messages.filter((message) => !['image', 'file', 'safety'].includes(message.role));
    const live = pending.liveStream;
    return resolveAnchor(entry.reference, entry.action, {
        visibleMessageIds: new Set(anchorable.map((message) => message.id)),
        lastMessageByRequestId: lastMessageByRequestId(anchorable),
        streamingUserMessageId: live && live.conversationId === pending.conversationId ? live.userMessageId : '',
    });
}

/**
 * Replace fetch with streams the test feeds by hand.
 *
 * Every request opens a held stream keyed by its path, so each intermediate state can be read
 * before the next frame lands. A path the test never feeds simply stays pending. A path listed
 * in `answers` gets that JSON at once instead, for the requests a stream makes on the side.
 * Every request is recorded, in order, in `requests`. As with a real fetch, aborting a request
 * fails the body its reader is still waiting on, so a reply the reader stops stops being read.
 */
function holdStreams(answers = {}) {
    const encoder = new TextEncoder();
    const streams = new Map();
    const waiters = new Map();
    const requests = [];
    const original = globalThis.fetch;
    globalThis.fetch = async (input, init = {}) => {
        const url = requestUrl(input);
        const path = url.pathname;
        requests.push({ method: init.method ?? 'GET', path, query: Object.fromEntries(url.searchParams) });
        if (Object.hasOwn(answers, path)) return json(answers[path]);
        const body = new ReadableStream({
            start(controller) {
                streams.set(path, controller);
                init.signal?.addEventListener(
                    'abort',
                    () => {
                        try {
                            controller.error(new DOMException('The operation was aborted.', 'AbortError'));
                        } catch {
                            // The stream had already ended.
                        }
                    },
                    { once: true },
                );
            },
        });
        const waiter = waiters.get(path);
        if (waiter) {
            waiters.delete(path);
            waiter(typeof init.body === 'string' ? JSON.parse(init.body) : null);
        }
        return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
    };
    return {
        requests,
        listRequests: () => requests.filter((request) => request.path === LIST_PATH),
        opened(path) {
            return new Promise((resolve) => waiters.set(path, resolve));
        },
        emit(path, event) {
            streams.get(path).enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
        },
        end(path) {
            try {
                streams.get(path)?.close();
            } catch {
                // The reader already stopped at the terminal frame.
            }
        },
        restore() {
            globalThis.fetch = original;
        },
    };
}

/** Run a test against a real send in `conversationId` whose reply stream the test controls. */
async function withLiveReply(conversationId, run, { answers = {}, text = 'Email Dana the numbers' } = {}) {
    openConversation(conversationId);
    const streams = holdStreams(answers);
    try {
        const opened = streams.opened(STREAM_PATH);
        void chat().sendMessage(text, {});
        const body = await opened;
        await run({ streams, body, userMessageId: store().liveStream?.userMessageId ?? '' });
    } finally {
        streams.end(STREAM_PATH);
        streams.restore();
        resetStores();
    }
}

const creationFrame = (id = 'act-1', overrides = {}) => ({
    type: 'm365_pending_action',
    pending_action: action(id),
    conversation_id: 'conv-1',
    request_id: 'req-1',
    ...overrides,
});

const replyFinished = () => chat().streaming === false && store().liveStream === null;

/** The body of a finished SSE response, as the server frames it. */
function sseResponse(frames) {
    const encoder = new TextEncoder();
    return new Response(
        new ReadableStream({
            start(controller) {
                for (const frame of frames) controller.enqueue(encoder.encode(`data: ${JSON.stringify(frame)}\n\n`));
                controller.close();
            },
        }),
        { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
    );
}

async function withFetch(fake, run) {
    const original = globalThis.fetch;
    globalThis.fetch = fake;
    try {
        return await run();
    } finally {
        globalThis.fetch = original;
    }
}

/* Following a notice about a saved action ---------------------------------------------- */

function navigation(pathname) {
    const visited = [];
    return { visited, context: { navigate: (path) => visited.push(path), pathname } };
}

/** Stand in for opening a conversation, noting what had been asked for at the moment it was opened. */
function spyOnOpen() {
    const opened = [];
    useChatStore.setState({
        openLinkedConversation: async (conversationId) => {
            const focus = store().focusRequest;
            opened.push({
                conversationId,
                focus: focus ? { id: focus.id, conversationId: focus.conversationId } : null,
            });
        },
    });
    return opened;
}

function notice(link) {
    return normalizeNotification({
        id: 'n-1',
        notification_type: 'system_announcement',
        title: 'A Microsoft 365 action needs your attention',
        message: 'An email is waiting to be sent.',
        created_at: '2026-05-01T09:05:00Z',
        is_read: false,
        link_url: link,
        link_context: {},
        metadata: { m365_pending_action_id: 'act-1' },
        type_config: { icon: 'bi-envelope', color: 'info' },
    });
}

test('on the chat page the card is asked for before the conversation is opened', async () => {
    openConversation('conv-1');
    const opened = spyOnOpen();
    const { visited, context } = navigation('/chat');
    openConversationFromNotification('conv-2', context, 'act-9');
    assert.deepEqual(opened, [{ conversationId: 'conv-2', focus: { id: 'act-9', conversationId: 'conv-2' } }]);
    assert.deepEqual(visited, [], 'the chat page opens the conversation itself rather than navigating');
});

test('a conversation that is already open is not opened again, but the card is still asked for', () => {
    openConversation('conv-2');
    const opened = spyOnOpen();
    const { visited, context } = navigation('/chat');
    openConversationFromNotification('conv-2', context, 'act-9');
    assert.deepEqual(opened, []);
    assert.deepEqual(visited, []);
    assert.equal(store().focusRequest.id, 'act-9');
    assert.equal(store().focusRequest.conversationId, 'conv-2');
});

test('a notice with no saved action opens the conversation without asking for a card', () => {
    openConversation('conv-1');
    const opened = spyOnOpen();
    openConversationFromNotification('conv-2', navigation('/chat').context);
    assert.deepEqual(opened, [{ conversationId: 'conv-2', focus: null }]);
    assert.equal(store().focusRequest, null);
});

test('a saved-action id that must not be carried opens the conversation without a focus request', () => {
    for (const unsafe of ['act/../1', 'act?1', 'act#1', '..', 'x'.repeat(201)]) {
        openConversation('conv-1');
        const opened = spyOnOpen();
        openConversationFromNotification('conv-2', navigation('/chat').context, unsafe);
        assert.deepEqual(opened, [{ conversationId: 'conv-2', focus: null }], unsafe);
        assert.equal(store().focusRequest, null, unsafe);
    }
});

test('away from the chat page the address carries the card instead of a focus request', () => {
    openConversation('conv-1');
    const { visited, context } = navigation('/approvals');
    openConversationFromNotification('conv-2', context, 'act-1');
    openConversationFromNotification('conv-2', context);
    assert.deepEqual(visited, [
        '/chat?conversationId=conv-2&m365_pending_action=act-1',
        '/chat?conversationId=conv-2',
    ]);
    assert.equal(visited[0], chatHrefForPendingAction('conv-2', 'act-1'));
    assert.equal(visited[1], chatHrefForConversation('conv-2'));
    assert.equal(store().focusRequest, null);
});

test('a conversation target follows the same hand-off and a route target is simply followed', async () => {
    openConversation('conv-1');
    const opened = spyOnOpen();
    const onChat = navigation('/chat');
    await openNotificationTarget(
        { kind: 'conversation', conversationId: 'conv-2', pendingActionId: 'act-1' },
        onChat.context,
    );
    await openNotificationTarget({ kind: 'route', path: '/approvals?status=pending' }, onChat.context);
    assert.deepEqual(opened, [{ conversationId: 'conv-2', focus: { id: 'act-1', conversationId: 'conv-2' } }]);
    assert.deepEqual(onChat.visited, ['/approvals?status=pending']);
});

test('a notice about a saved action, followed from any page, reaches the V2 chat with the card named', async () => {
    const link = '/chats?conversationId=conv-2&m365_pending_action=act-1';
    const { target, error } = resolveNotificationLink(notice(link), ORIGIN);
    assert.equal(error, null);

    openConversation('conv-1');
    const opened = spyOnOpen();
    const onChat = navigation('/chat');
    await openNotificationTarget(target, onChat.context);
    assert.deepEqual(opened, [{ conversationId: 'conv-2', focus: { id: 'act-1', conversationId: 'conv-2' } }]);
    assert.deepEqual(onChat.visited, []);

    const elsewhere = navigation('/approvals');
    await openNotificationTarget(target, elsewhere.context);
    assert.deepEqual(elsewhere.visited, ['/chat?conversationId=conv-2&m365_pending_action=act-1']);
    resetStores();
});

test('the request for a card survives the switch to its conversation and no other', () => {
    openConversation('conv-1');
    store().requestFocus('act-1', 'conv-2');
    useChatStore.setState({ activeConversationId: 'conv-2' });
    assert.equal(store().focusRequest?.id, 'act-1');
    assert.equal(store().conversationId, 'conv-2');

    store().requestFocus('act-1', 'conv-3');
    useChatStore.setState({ activeConversationId: 'conv-4' });
    assert.equal(store().focusRequest, null, 'a request for another conversation is dropped');
    resetStores();
});

/* Saved actions in the chat stream ----------------------------------------------------- */

function recordHandlers() {
    const log = [];
    return {
        log,
        names: () => log.map(([name]) => name),
        handlers: {
            onM365PendingActions: (event) => log.push(['actions', event]),
            onContent: (delta, accumulated) => log.push(['content', delta, accumulated]),
            onDone: (event, accumulated) => log.push(['done', event, accumulated]),
            onError: (message, event) => log.push(['error', message, event]),
        },
    };
}

const readStream = (fake, handlers) =>
    withFetch(fake, () =>
        streamChat({ message: 'Email Dana', conversation_id: 'conv-1' }, handlers, undefined, { allowRecovery: false }),
    );

test('only a frame that reports saved actions is handed to the pending-action handler', () => {
    assert.equal(carriesPendingActions(creationFrame()), true);
    assert.equal(carriesPendingActions({ done: true, m365_pending_actions: [] }), true);
    assert.equal(carriesPendingActions({ error: 'Failed', m365_pending_actions_error: { message: 'Not listed' } }), true);
    for (const frame of [null, undefined, {}, { content: 'x' }, { done: true }, { type: 'thought' }]) {
        assert.equal(carriesPendingActions(frame), false, JSON.stringify(frame));
    }
});

test('a saved action reported mid-stream reaches the handler before the answer text', async () => {
    const { log, names, handlers } = recordHandlers();
    const result = await readStream(
        async () => sseResponse([creationFrame(), { content: 'Hello ' }, { content: 'world' }, { done: true, message_id: 'a-1' }]),
        handlers,
    );
    assert.deepEqual(names(), ['actions', 'content', 'content', 'done']);
    assert.equal(log[0][1].pending_action.id, 'act-1');
    assert.equal(result.accumulated, 'Hello world');
    assert.equal(result.completed, true);
    assert.equal(result.errored, false);
});

test('a reply that carries its actions on the finishing frame reports them before it finishes', async () => {
    const { log, names, handlers } = recordHandlers();
    await readStream(
        async () =>
            sseResponse([
                { content: 'Saved.' },
                { done: true, message_id: 'a-1', m365_pending_actions: [action('act-1', { status: 'completed' })] },
            ]),
        handlers,
    );
    assert.deepEqual(names(), ['content', 'actions', 'done']);
    assert.equal(log[1][1].m365_pending_actions[0].status, 'completed');
});

test('a reply that fails after saving an action reports the action before the error', async () => {
    const { log, names, handlers } = recordHandlers();
    const result = await readStream(
        async () => sseResponse([{ error: 'Model failed', m365_pending_actions: [action('act-2')] }]),
        handlers,
    );
    assert.deepEqual(names(), ['actions', 'error']);
    assert.equal(log[0][1].m365_pending_actions[0].id, 'act-2');
    assert.equal(log[1][1], 'Model failed');
    assert.equal(result.errored, true);
});

test('a refused request that could not list its actions still says so before the error', async () => {
    const { log, names, handlers } = recordHandlers();
    const result = await readStream(
        async () =>
            json(
                { error: 'Chat is unavailable', m365_pending_actions_error: { message: 'Outgoing actions could not be verified.' } },
                500,
            ),
        handlers,
    );
    assert.deepEqual(names(), ['actions', 'error']);
    assert.equal(log[0][1].m365_pending_actions_error.message, 'Outgoing actions could not be verified.');
    assert.equal(log[1][1], 'Chat is unavailable');
    assert.equal(result.errored, true);
});

test('a refused request with nothing to say about actions reports only the error', async () => {
    const { names, handlers } = recordHandlers();
    await readStream(async () => json({ error: 'Chat is unavailable' }, 500), handlers);
    assert.deepEqual(names(), ['error']);
});

test('a stream that saves nothing never reaches the pending-action handler', async () => {
    const { names, handlers } = recordHandlers();
    await readStream(async () => sseResponse([{ content: 'Hi' }, { done: true, message_id: 'a-1' }]), handlers);
    assert.deepEqual(names(), ['content', 'done']);
});

/* A real send: where the card is drawn while the reply streams ------------------------- */

test('a saved action follows its reply from the streaming turn to the finished message', async () => {
    await withLiveReply('conv-1', async ({ streams, body, userMessageId }) => {
        assert.equal(body.conversation_id, 'conv-1');
        assert.match(userMessageId, /^pending-user-/);
        assert.equal(store().liveStream.conversationId, 'conv-1');
        assert.ok(chat().messages.some((message) => message.id === userMessageId));

        streams.emit(STREAM_PATH, creationFrame('act-1'));
        await settled(() => store().entries['act-1'], 'the saved action to be reported');
        let reference = store().entries['act-1'].reference;
        assert.equal(reference.userMessageId, userMessageId);
        assert.equal(reference.requestId, 'req-1');
        assert.equal(anchorOf('act-1'), STREAMING_ANCHOR, 'drawn under the streaming reply while it is generated');

        streams.emit(STREAM_PATH, { type: 'user_message_persisted', user_message_id: 'u-real-1' });
        await settled(() => store().liveStream?.userMessageId === 'u-real-1', 'the persisted turn to be adopted');
        reference = store().entries['act-1'].reference;
        assert.equal(reference.userMessageId, 'u-real-1');
        assert.equal(reference.fallbackMessageId, 'u-real-1');
        assert.ok(chat().messages.some((message) => message.id === 'u-real-1'));
        assert.equal(anchorOf('act-1'), STREAMING_ANCHOR, 'the card stays where it was when the turn gets its real id');

        streams.emit(STREAM_PATH, { content: 'I saved the email. ' });
        streams.emit(STREAM_PATH, {
            done: true,
            message_id: 'a-real-1',
            chat_type: 'group',
            full_content: 'I saved the email. Review it below.',
            m365_pending_actions: [action('act-1', { version: 'v2', updated_at: T2 })],
        });
        streams.end(STREAM_PATH);
        await settled(replyFinished, 'the reply to finish');

        const finished = store().entries['act-1'];
        assert.equal(finished.reference.messageId, 'a-real-1');
        assert.equal(finished.reference.requestId, 'req-1', 'the request that saved the action is not forgotten');
        assert.equal(finished.action.version, 'v2');
        assert.ok(chat().messages.some((message) => message.id === 'a-real-1'));
        assert.equal(anchorOf('act-1'), 'a-real-1', 'drawn under the finished reply');
        assert.equal(Object.keys(store().entries).length, 1, 'one card, not one per frame');
    });
});

test('a frame that names the hidden source conversation still lands in the conversation on screen', async () => {
    await withLiveReply('conv-1', async ({ streams, userMessageId }) => {
        streams.emit(STREAM_PATH, creationFrame('act-1', { conversation_id: 'hidden-source-1' }));
        await settled(() => store().entries['act-1'], 'the saved action to be reported');
        assert.equal(store().conversationId, 'conv-1');
        assert.equal(store().entries['act-1'].reference.userMessageId, userMessageId);
        assert.equal(anchorOf('act-1'), STREAMING_ANCHOR);
        streams.emit(STREAM_PATH, { done: true, message_id: 'a-real-1', chat_type: 'group' });
        streams.end(STREAM_PATH);
        await settled(replyFinished, 'the reply to finish');
    });
});

test('a frame that arrives after the reader opened another conversation is dropped', async () => {
    await withLiveReply('conv-1', async ({ streams }) => {
        useChatStore.setState({ activeConversationId: 'conv-2' });
        assert.equal(store().conversationId, 'conv-2');
        streams.emit(STREAM_PATH, creationFrame('act-1'));
        streams.emit(STREAM_PATH, { done: true, message_id: 'a-real-1', chat_type: 'group' });
        streams.end(STREAM_PATH);
        await settled(() => chat().streaming === false, 'the stream to be read to its end');
        assert.deepEqual(Object.keys(store().entries), [], 'the other conversation shows nothing it did not save');
    });
});

test('a reply that fails after saving an action still shows the saved action under the turn', async () => {
    await withLiveReply(
        'conv-1',
        async ({ streams, userMessageId }) => {
            streams.emit(STREAM_PATH, { error: 'Model failed', request_id: 'req-2', m365_pending_actions: [action('act-2')] });
            streams.end(STREAM_PATH);
            await settled(() => chat().streamError && replyFinished(), 'the failed reply to settle');

            assert.equal(chat().streamError, 'Model failed');
            const entry = store().entries['act-2'];
            assert.ok(entry, 'the action the failed reply saved is still shown');
            assert.equal(entry.reference.requestId, 'req-2');
            assert.equal(anchorOf('act-2'), userMessageId, 'with no reply to hold it, the card stays under the turn');
        },
        { answers: { '/api/chat/stream/status/conv-1': { pending: false } } },
    );
});

test('a card with no reply and no turn on screen is drawn in the conversation section', async () => {
    openConversation('conv-1');
    store().handleStreamPayload(creationFrame('act-1'), {
        conversationId: 'conv-1',
        messageId: '',
        userMessageId: 'u-gone',
        requestId: '',
    });
    assert.equal(anchorOf('act-1'), ORPHAN_ANCHOR);
    resetStores();
});

/* After a reply ends: the conversation's saved actions are read again ------------------ */

/** What the list route answers for a conversation holding `items`. */
const listOf = (...items) => ({ success: true, pending_actions: items, continuation_token: '' });

test('a finished reply reads the conversation\'s saved actions again, once, after it ends', async () => {
    await withLiveReply(
        'conv-1',
        async ({ streams }) => {
            streams.emit(STREAM_PATH, { content: 'I saved the email. ' });
            await new Promise((resolve) => setTimeout(resolve, 20));
            assert.equal(streams.listRequests().length, 0, 'nothing is read while the reply is still being written');

            streams.emit(STREAM_PATH, {
                done: true,
                message_id: 'a-real-1',
                chat_type: 'group',
                full_content: 'I saved the email. Review it below.',
            });
            streams.end(STREAM_PATH);
            await settled(replyFinished, 'the reply to finish');
            await settled(() => store().entries['act-late'], 'the saved action to be listed');

            const reads = streams.listRequests();
            assert.equal(reads.length, 1, 'one read, not one per frame');
            assert.equal(reads[0].method, 'GET');
            assert.equal(reads[0].query.conversation_id, 'conv-1');
            assert.equal(reads[0].query.limit, '30');
            assert.equal(anchorOf('act-late'), ORPHAN_ANCHOR, 'an action the stream never described is drawn in the conversation section');
        },
        { answers: { [LIST_PATH]: listOf(action('act-late')) } },
    );
});

test('a reply that fails reads the saved actions again, because it may have saved one the stream never described', async () => {
    await withLiveReply(
        'conv-1',
        async ({ streams }) => {
            streams.emit(STREAM_PATH, { error: 'Model failed', request_id: 'req-3' });
            streams.end(STREAM_PATH);
            await settled(() => chat().streamError && replyFinished(), 'the failed reply to settle');
            await settled(() => store().entries['act-late'], 'the saved action to be listed');

            assert.equal(chat().streamError, 'Model failed');
            assert.equal(streams.listRequests().length, 1);
        },
        { answers: { '/api/chat/stream/status/conv-1': { pending: false }, [LIST_PATH]: listOf(action('act-late')) } },
    );
});

test('a reply the reader stops reads the saved actions again once the server has the stop request', async () => {
    await withLiveReply(
        'conv-1',
        async ({ streams }) => {
            assert.equal(streams.listRequests().length, 0);
            chat().stopStreaming();
            await settled(() => store().entries['act-late'], 'the saved action to be listed');

            const stops = streams.requests.filter((request) => request.path === '/api/chat/stream/cancel/conv-1');
            const reads = streams.listRequests();
            assert.equal(stops.length, 1);
            assert.equal(reads.length, 1);
            assert.ok(
                streams.requests.indexOf(stops[0]) < streams.requests.indexOf(reads[0]),
                'the list is read after the stop was sent, so it cannot miss what the stop was too late to prevent',
            );
        },
        { answers: { '/api/chat/stream/cancel/conv-1': { success: true }, [LIST_PATH]: listOf(action('act-late')) } },
    );
});

test('a reply that ends after the reader opened another conversation does not read the list of the one on screen', async () => {
    await withLiveReply(
        'conv-1',
        async ({ streams }) => {
            useChatStore.setState({ activeConversationId: 'conv-2' });
            streams.emit(STREAM_PATH, { done: true, message_id: 'a-real-1', chat_type: 'group' });
            streams.end(STREAM_PATH);
            await settled(() => chat().streaming === false, 'the stream to be read to its end');
            await new Promise((resolve) => setTimeout(resolve, 20));
            assert.deepEqual(streams.listRequests(), []);
            assert.deepEqual(Object.keys(store().entries), []);
        },
        { answers: { [LIST_PATH]: listOf(action('act-late')) } },
    );
});

/** A server for a conversation whose reply is still being written when the reader opens it. */
function serveRunningReply(conversationId) {
    const encoder = new TextEncoder();
    const requests = [];
    const original = globalThis.fetch;
    let reattached = null;
    globalThis.fetch = async (input, init = {}) => {
        const url = requestUrl(input);
        requests.push({ method: init.method ?? 'GET', path: url.pathname, query: Object.fromEntries(url.searchParams) });
        if (url.pathname === '/api/get_messages') return json({ messages: [] });
        if (url.pathname === `/api/chat/stream/status/${conversationId}`) return json({ pending: true });
        if (url.pathname === `/api/chat/stream/reattach/${conversationId}`) {
            return new Response(
                new ReadableStream({
                    start(controller) {
                        reattached = controller;
                    },
                }),
                { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
            );
        }
        if (url.pathname === LIST_PATH) return json(listOf(action('act-late')));
        return json({ error: 'Not found' }, 404);
    };
    return {
        listRequests: () => requests.filter((request) => request.path === LIST_PATH),
        attached: () => reattached !== null,
        emit(event) {
            reattached.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
        },
        end() {
            try {
                reattached?.close();
            } catch {
                // The reader already stopped at the terminal frame.
            }
        },
        restore() {
            globalThis.fetch = original;
        },
    };
}

test('a reply picked up again after the reader was away reads the saved actions when it ends', async () => {
    resetStores();
    const server = serveRunningReply('conv-away');
    try {
        await chat().selectConversation('conv-away', { kind: 'personal' });
        await settled(() => server.attached() && chat().streaming === true, 'the running reply to be picked up');
        assert.equal(store().conversationId, 'conv-away');
        assert.equal(server.listRequests().length, 0, 'nothing is read while the reply is still being written');

        server.emit({ content: 'Still writing. ' });
        server.emit({ done: true, message_id: 'a-away-1', chat_type: 'group', full_content: 'Still writing. Done.' });
        server.end();
        await settled(() => chat().streaming === false, 'the picked-up reply to end');
        await settled(() => store().entries['act-late'], 'the saved action to be listed');
        assert.equal(server.listRequests().length, 1);
        assert.equal(server.listRequests()[0].query.conversation_id, 'conv-away');
    } finally {
        server.end();
        server.restore();
        resetStores();
    }
});

/* Stopping a reply: its saved actions stay under the turn that asked for them ---------- */

test('a reply the reader stops leaves its saved action under the turn that asked for it', async () => {
    await withLiveReply(
        'conv-1',
        async ({ streams, userMessageId }) => {
            streams.emit(STREAM_PATH, creationFrame('act-1'));
            await settled(() => store().entries['act-1'], 'the saved action to be reported');
            assert.equal(anchorOf('act-1'), STREAMING_ANCHOR, 'drawn under the streaming reply while it is generated');

            chat().stopStreaming();
            assert.equal(store().liveStream, null, 'a reply nobody is reading is not a streaming reply');
            assert.equal(anchorOf('act-1'), userMessageId, 'the card leaves the streaming slot, which nothing will fill again');
            await settled(() => streams.listRequests().length === 1, 'the list to be read after the stop');
            assert.equal(anchorOf('act-1'), userMessageId, 'reading the list again does not move it');
        },
        { answers: { '/api/chat/stream/cancel/conv-1': { success: true }, [LIST_PATH]: listOf() } },
    );
});

test('a message sent after a stopped reply does not take the stopped reply\'s saved action with it', async () => {
    await withLiveReply(
        'conv-1',
        async ({ streams, userMessageId }) => {
            streams.emit(STREAM_PATH, creationFrame('act-1'));
            await settled(() => store().entries['act-1'], 'the saved action to be reported');
            chat().stopStreaming();
            await settled(() => streams.listRequests().length === 1, 'the list to be read after the stop');

            const opened = streams.opened(STREAM_PATH);
            void chat().sendMessage('And one more', {});
            await opened;
            const nextUserMessageId = store().liveStream?.userMessageId ?? '';
            assert.match(nextUserMessageId, /^pending-user-/);
            assert.notEqual(nextUserMessageId, userMessageId, 'the new message is a new turn');

            assert.equal(store().entries['act-1'].reference.userMessageId, userMessageId, 'the card still belongs to the turn that saved it');
            assert.equal(anchorOf('act-1'), userMessageId, 'and is drawn under it, not under the new reply');
        },
        { answers: { '/api/chat/stream/cancel/conv-1': { success: true }, [LIST_PATH]: listOf() } },
    );
});

/* Shared conversations: every participant is told to read the list again --------------- */

function pendingActionEvent(conversationId, payload = {}, occurredAt = new Date().toISOString()) {
    return {
        conversation_id: conversationId,
        event_type: 'collaboration.m365.pending_action',
        occurred_at: occurredAt,
        payload: { m365_pending_action_ids: ['act-7'], request_id: 'req-7', ...payload },
    };
}

/** Every handler the event could reach, recorded by name, so nothing but the intended one can slip by. */
function recordingHandlers() {
    const calls = [];
    const handlers = new Proxy(
        {},
        {
            get:
                (_target, name) =>
                (...args) => {
                    calls.push([String(name), ...args]);
                },
        },
    );
    return { calls, handlers };
}

function installFakeEventSource() {
    const sources = [];
    class FakeEventSource {
        constructor(url, init) {
            this.url = url;
            this.init = init;
            this.closed = false;
            this.onmessage = null;
            this.onerror = null;
            sources.push(this);
        }

        close() {
            this.closed = true;
        }

        deliver(data) {
            this.onmessage?.({ data: typeof data === 'string' ? data : JSON.stringify(data) });
        }
    }
    globalThis.EventSource = FakeEventSource;
    return {
        sources,
        restore() {
            delete globalThis.EventSource;
        },
    };
}

test('a pending-action event gives the actions it names, the request that saved them and whether they could be listed', () => {
    const { calls, handlers } = recordingHandlers();

    dispatchCollaborationEvent(
        pendingActionEvent('conv-shared', { m365_pending_action_ids: ['act-1', '', 7, null, 'act-2'], request_id: 'req-1' }),
        handlers,
    );
    dispatchCollaborationEvent(
        pendingActionEvent('conv-shared', { m365_pending_action_ids: 'act-1', request_id: 42 }),
        handlers,
    );
    dispatchCollaborationEvent(
        pendingActionEvent('conv-shared', { m365_pending_action_ids: [], error: 'm365_pending_actions_unavailable' }),
        handlers,
    );
    dispatchCollaborationEvent(
        pendingActionEvent('conv-shared', { m365_pending_action_ids: [], error: 'something_else' }),
        handlers,
    );

    assert.deepEqual(calls, [
        ['onM365PendingActions', { actionIds: ['act-1', 'act-2'], requestId: 'req-1', unavailable: false }],
        ['onM365PendingActions', { actionIds: [], requestId: '', unavailable: false }],
        ['onM365PendingActions', { actionIds: [], requestId: 'req-7', unavailable: true }],
        ['onM365PendingActions', { actionIds: [], requestId: 'req-7', unavailable: false }],
    ]);
});

test('the event subscription opens the conversation stream and closes it when detached', () => {
    const events = installFakeEventSource();
    try {
        const { calls, handlers } = recordingHandlers();
        const detach = subscribeToCollaborationEvents('conv-shared', handlers);
        assert.equal(events.sources.length, 1);
        assert.equal(events.sources[0].url, '/api/collaboration/conversations/conv-shared/events');
        const when = new Date().toISOString();

        events.sources[0].deliver(pendingActionEvent('conv-shared', {}, when));
        events.sources[0].deliver(pendingActionEvent('conv-shared', {}, when));
        events.sources[0].deliver(pendingActionEvent('conv-shared', { m365_pending_action_ids: ['act-8'] }, when));
        events.sources[0].deliver(pendingActionEvent('conv-shared', { request_id: 'req-8' }, when));
        assert.deepEqual(
            calls.map(([name, change]) => [name, change.actionIds, change.requestId]),
            [
                ['onM365PendingActions', ['act-7'], 'req-7'],
                ['onM365PendingActions', ['act-8'], 'req-7'],
                ['onM365PendingActions', ['act-7'], 'req-8'],
            ],
            'an exact repeat is dropped, an event for other actions or another request is not',
        );

        detach();
        assert.equal(events.sources[0].closed, true);
    } finally {
        events.restore();
    }
});

test('history replayed on connect and frames that cannot be read do not touch the list', () => {
    const events = installFakeEventSource();
    try {
        const { calls, handlers } = recordingHandlers();
        subscribeToCollaborationEvents('conv-shared', handlers);
        const [source] = events.sources;

        source.deliver(pendingActionEvent('conv-shared', {}, '2020-01-01T00:00:00Z'));
        source.deliver('');
        source.deliver('{not json');
        assert.deepEqual(calls, []);

        source.deliver(pendingActionEvent('conv-shared'));
        assert.equal(calls.length, 1, 'a live event still gets through after them');
    } finally {
        events.restore();
    }
});

test('without an EventSource, or a conversation, there is nothing to subscribe to', () => {
    assert.equal(typeof globalThis.EventSource, 'undefined');
    const { handlers } = recordingHandlers();
    const detach = subscribeToCollaborationEvents('conv-shared', handlers);
    assert.equal(typeof detach, 'function');
    detach();

    const events = installFakeEventSource();
    try {
        subscribeToCollaborationEvents('', handlers)();
        assert.equal(events.sources.length, 0);
    } finally {
        events.restore();
    }
});

/** A server for a shared conversation: its thread is empty and its saved actions are `listing()`. */
function serveSharedConversation(listing = () => json({ pending_actions: [action('act-7')], continuation_token: '' })) {
    const requests = [];
    const original = globalThis.fetch;
    globalThis.fetch = async (input, init = {}) => {
        const url = requestUrl(input);
        requests.push({ method: init.method ?? 'GET', path: url.pathname, query: Object.fromEntries(url.searchParams) });
        if (url.pathname === '/api/collaboration/conversations/conv-shared/messages') return json({ messages: [] });
        if (url.pathname === LIST_PATH) return listing();
        return json({ error: 'Not found' }, 404);
    };
    return {
        requests,
        listRequests: () => requests.filter((request) => request.path === LIST_PATH),
        restore() {
            globalThis.fetch = original;
        },
    };
}

async function withSharedConversation(run, listing) {
    resetStores();
    const events = installFakeEventSource();
    const server = serveSharedConversation(listing);
    try {
        await chat().selectConversation('conv-shared', { kind: 'collaborative' });
        assert.equal(chat().activeConversationId, 'conv-shared');
        assert.equal(store().conversationId, 'conv-shared');
        assert.equal(events.sources.length, 1, 'the open conversation is subscribed to');
        await run({ source: events.sources[0], server });
    } finally {
        server.restore();
        events.restore();
        resetStores();
    }
}

test('a shared conversation reads its saved actions again when the server announces one', async () => {
    await withSharedConversation(async ({ source, server }) => {
        assert.equal(server.listRequests().length, 0, 'nothing is listed until something is announced');

        source.deliver(pendingActionEvent('conv-shared'));
        await settled(() => store().entries['act-7'], 'the announced action to be listed');

        const [listing] = server.listRequests();
        assert.equal(listing.method, 'GET');
        assert.equal(listing.query.conversation_id, 'conv-shared');
        assert.equal(listing.query.limit, '30');
        assert.equal(anchorOf('act-7'), ORPHAN_ANCHOR, 'a card with no place in the thread is drawn in the conversation section');
    });
});

test('a shared conversation says its saved actions could not be listed until the list is read again', async () => {
    const listing = deferred();
    await withSharedConversation(
        async ({ source, server }) => {
            source.deliver(pendingActionEvent('conv-shared', { m365_pending_action_ids: [], error: 'm365_pending_actions_unavailable' }));
            await settled(() => store().referenceError === PENDING_ACTIONS_UNAVAILABLE_MESSAGE, 'the unavailable notice');
            await settled(() => server.listRequests().length === 1, 'the list to be read again');

            listing.resolve();
            await settled(() => store().listStatus === 'loaded', 'the list to be read');
            assert.equal(store().referenceError, '', 'the notice is withdrawn once the list is verified');
            assert.ok(store().entries['act-7']);
        },
        () => listing.promise.then(() => json({ pending_actions: [action('act-7')], continuation_token: '' })),
    );
});

test('an event for a conversation the reader has left does not read any list', async () => {
    await withSharedConversation(async ({ source, server }) => {
        useChatStore.setState({ activeConversationId: 'conv-other' });
        source.deliver(pendingActionEvent('conv-shared'));
        await new Promise((resolve) => setTimeout(resolve, 20));
        assert.equal(server.listRequests().length, 0);
        assert.deepEqual(Object.keys(store().entries), []);
    });
});
