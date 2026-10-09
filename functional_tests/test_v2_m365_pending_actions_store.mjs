// test_v2_m365_pending_actions_store.mjs
// Version: 0.261.307
// Implemented in: 0.261.307
// Executes the state machine behind the Microsoft 365 outgoing-action cards against a fake server:
// how a card is found, when it may be sent or cancelled, what happens when the server disagrees
// with what the page shows, and how a late answer for a conversation the person has left is
// dropped. The store is the same one the chat view and the Approvals detail page draw from, so
// these tests cover both places a card appears.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

globalThis.fetch = () => {
    throw new Error('A test reached the network without installing its fake server first.');
};

// The repository resolver must be registered before extensionless TypeScript imports load.
const storeModule = await import('../application/v2_ui/src/stores/m365PendingActionsStore.ts');

const { LIST_FAILED_MESSAGE, LIST_PERMISSION_MESSAGE, REFERENCE_FAILED_MESSAGE, canChangeEntry, createPendingActionsStore } =
    storeModule;

const NOT_LOADED_MESSAGE = 'The outgoing action could not be loaded.';
const PERMISSION_MESSAGE = 'You do not have permission to access this action. No action was sent.';

const T1 = '2026-05-01T10:00:00Z';
const T2 = '2026-05-01T10:05:00Z';
const T3 = '2026-05-01T10:10:00Z';

const LIST_PATH = '/api/msgraph/pending-actions';
const ITEM_PATH = /^\/api\/msgraph\/pending-actions\/([^/]+)(?:\/(send-now|approve|cancel))?$/;

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

/** A chat message that carries, or points at, saved actions. */
function message(id, extra = {}) {
    return { id, role: 'assistant', content: 'I saved the email for you to review.', ...extra };
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

/** Wait, turn by turn, for work the store started without handing back a promise. */
async function settled(condition, description = 'the condition') {
    for (let turn = 0; turn < 500; turn += 1) {
        if (condition()) return;
        await new Promise((resolve) => setTimeout(resolve, 0));
    }
    throw new Error(`${description} was never met`);
}

/**
 * Stand in for the server. `handler` receives each request after the Microsoft 365 CSRF token
 * request (which is always answered and kept in `all` only) and returns a Response; returning
 * nothing marks the request as one the test did not expect.
 */
function serve(handler, { honorAbort = true } = {}) {
    const previous = globalThis.fetch;
    const calls = [];
    const all = [];
    const unexpected = [];
    globalThis.fetch = (input, init = {}) => {
        const url = new URL(typeof input === 'string' ? input : String(input?.url ?? input), 'http://localhost');
        const method = String(init.method ?? 'GET').toUpperCase();
        const matched = ITEM_PATH.exec(url.pathname);
        let kind = 'other';
        if (method === 'GET' && url.pathname === LIST_PATH) kind = 'list';
        else if (method === 'GET' && matched && !matched[2]) kind = 'get';
        else if (method === 'POST' && matched && matched[2]) kind = 'post';
        const call = {
            method,
            path: url.pathname,
            query: Object.fromEntries(url.searchParams),
            headers: new Headers(init.headers ?? {}),
            body: typeof init.body === 'string' && init.body ? JSON.parse(init.body) : null,
            kind,
            id: matched ? decodeURIComponent(matched[1]) : '',
            operation: matched?.[2] ?? '',
        };
        all.push(call);
        if (method === 'GET' && url.pathname === '/api/m365/preferences') {
            return Promise.resolve(json({ csrf_token: 'c'.repeat(40) }));
        }
        calls.push(call);
        const work = (async () => {
            const response = await handler(call);
            if (!response) {
                unexpected.push(`${method} ${url.pathname}${url.search}`);
                throw new Error(`The test did not expect ${method} ${url.pathname}${url.search}`);
            }
            return response;
        })();
        const signal = init.signal;
        if (!honorAbort || !signal) return work;
        return new Promise((resolve, reject) => {
            const abort = () => reject(new DOMException('The operation was aborted.', 'AbortError'));
            if (signal.aborted) {
                abort();
                return;
            }
            signal.addEventListener('abort', abort, { once: true });
            work.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
        });
    };
    return {
        calls,
        all,
        unexpected,
        restore() {
            globalThis.fetch = previous;
        },
    };
}

async function withServer(handler, body, options) {
    const server = serve(handler, options);
    try {
        await body(server);
    } finally {
        server.restore();
    }
    assert.deepEqual(server.unexpected, [], 'the store asked the server for something the test did not expect');
}

/** A chat-scope store for one conversation, the way the chat page uses it. */
function newStore({ conversationId = 'conv-1', onUpdated } = {}) {
    const store = createPendingActionsStore({ scope: 'chat', onUpdated });
    if (conversationId) store.getState().setConversation(conversationId);
    return store;
}

const stateOf = (store) => store.getState();
const cardOf = (store, id) => store.getState().entries[id];

/** The server holds one copy of each action and answers reads from it. */
function readsFrom(held) {
    return (call) => {
        if (call.kind !== 'get') return undefined;
        const found = held.get(call.id);
        return found ? json({ pending_action: found }) : json({ error: 'not_found', message: 'No such action.' }, 404);
    };
}

/* Remembering a card ------------------------------------------------------------------- */

test('a card is remembered once, and anything that is not a saved action is refused', () => {
    const updates = [];
    const store = newStore({ onUpdated: (saved) => updates.push(saved.id) });
    const made = stateOf(store).remember(action('act-1'), { authoritative: true, reference: { messageId: 'm-1' } });
    assert.equal(made.id, 'act-1');
    assert.equal(made.reference.messageId, 'm-1');
    assert.equal(made.fullDetailsVersion, 'v1', 'a full copy from the server counts as reviewed');
    assert.equal(made.needsRefresh, false);
    assert.equal(canChangeEntry(made), true);
    assert.deepEqual(updates, ['act-1']);

    for (const refused of [null, undefined, {}, 'text', 7, { type: 'other', id: 'x' }, { type: 'msgraph_pending_action', id: '..' }]) {
        assert.equal(stateOf(store).remember(refused), null, `${JSON.stringify(refused)} is not a saved action`);
    }
    assert.deepEqual(Object.keys(stateOf(store).entries), ['act-1']);
    assert.deepEqual(updates, ['act-1']);
});

test('a copy that did not come from the server is not treated as reviewed in full', () => {
    const store = newStore();
    const made = stateOf(store).remember(action('act-1'));
    assert.equal(made.fullDetailsVersion, '');
    const second = stateOf(store).remember(action('act-2', { review_details_required: true }), { authoritative: true });
    assert.equal(second.fullDetailsVersion, '', 'a server copy that withholds the body still needs a full review');
});

test('an older snapshot is ignored, though the place it was seen is still remembered', () => {
    const updates = [];
    const store = newStore({ onUpdated: (saved) => updates.push(saved.subject) });
    stateOf(store).remember(action('act-1', { updated_at: T2, subject: 'Newest' }), { authoritative: true });
    assert.equal(updates.length, 1);

    const before = stateOf(store);
    const kept = stateOf(store).remember(action('act-1', { updated_at: T1, subject: 'Older' }), { authoritative: true });
    assert.equal(kept.action.subject, 'Newest');
    assert.equal(stateOf(store), before, 'nothing changed, so nothing is announced to the page');
    assert.equal(updates.length, 1);

    const placed = stateOf(store).remember(action('act-1', { updated_at: T1, subject: 'Older' }), {
        reference: { messageId: 'm-9', requestId: 'req-9' },
    });
    assert.equal(placed.action.subject, 'Newest');
    assert.equal(placed.reference.messageId, 'm-9');
    assert.equal(placed.reference.requestId, 'req-9');
    assert.equal(updates.length, 1, 'a placement change alone is not an update to the action');
});

test('a stream or history copy cannot un-send an action, but the server can say what it likes', () => {
    const store = newStore();
    stateOf(store).remember(action('act-1', { status: 'sent', updated_at: T2, can_cancel: false, can_send_now: false }), {
        authoritative: true,
    });
    stateOf(store).remember(action('act-1', { status: 'pending', updated_at: T3 }));
    assert.equal(cardOf(store, 'act-1').action.status, 'sent', 'a copy of unknown age cannot make a sent action actionable again');

    stateOf(store).remember(action('act-1', { status: 'pending', updated_at: T3 }), { authoritative: true });
    assert.equal(cardOf(store, 'act-1').action.status, 'pending');
});

test('a new version of an action drops what was true of the old one', () => {
    const store = newStore();
    stateOf(store).remember(action('act-1', { auth_required: true, sources: ['email'], scopes: ['Mail.Send'] }), {
        authoritative: true,
    });
    let card = cardOf(store, 'act-1');
    assert.equal(card.fullDetailsVersion, 'v1');
    assert.deepEqual(card.auth, { auth_required: true, sources: ['email'], scopes: ['Mail.Send'] });

    stateOf(store).remember(action('act-1', { version: 'v2', updated_at: T2 }));
    card = cardOf(store, 'act-1');
    assert.equal(card.action.version, 'v2');
    assert.deepEqual(card.seenVersions, ['v1']);
    assert.equal(card.fullDetailsVersion, '', 'the earlier review was of a different version');
    assert.equal(card.auth, null);
    assert.equal(card.authAcknowledgedVersion, '');

    stateOf(store).remember(action('act-1', { version: 'v2', updated_at: T2 }), { authoritative: true });
    assert.equal(cardOf(store, 'act-1').fullDetailsVersion, 'v2');
});

test('a version the card already moved past cannot come back, even from the server', () => {
    const store = newStore();
    stateOf(store).remember(action('act-1', { version: 'v1' }), { authoritative: true });
    stateOf(store).remember(action('act-1', { version: 'v2', updated_at: T2 }), { authoritative: true });
    stateOf(store).remember(action('act-1', { version: 'v1', updated_at: T3, subject: 'Resurrected' }), { authoritative: true });
    const card = cardOf(store, 'act-1');
    assert.equal(card.action.version, 'v2');
    assert.notEqual(card.action.subject, 'Resurrected');
});

test('a stripped copy of a version reviewed in full is checked against the server again', async () => {
    await withServer(readsFrom(new Map([['act-1', action('act-1', { updated_at: T2 })]])), async (server) => {
        const store = newStore();
        stateOf(store).remember(action('act-1'), { authoritative: true });
        assert.equal(cardOf(store, 'act-1').fullDetailsVersion, 'v1');

        stateOf(store).remember(
            action('act-1', {
                updated_at: T2,
                review_details_required: true,
                summary: { subject: 'Quarterly numbers', body_preview_truncated: true },
            }),
        );
        assert.equal(cardOf(store, 'act-1').refreshing, true, 'the full content has to be fetched again');
        await stateOf(store).refresh('act-1');

        assert.equal(server.calls.length, 1);
        assert.equal(server.calls[0].query.conversation_id, 'conv-1');
        const card = cardOf(store, 'act-1');
        assert.equal(card.fullDetailsVersion, 'v1');
        assert.equal(card.action.review_details_required, false);
    });
});

/* Cards found in messages ------------------------------------------------------------- */

test('a card in a loaded message is not sendable until the server has confirmed it', async () => {
    const held = new Map([['act-1', action('act-1', { updated_at: T2, subject: 'Server copy' })]]);
    await withServer(readsFrom(held), async (server) => {
        const store = newStore();
        const first = message('m-1', { m365_pending_actions: [action('act-1')], metadata: { m365_request_id: 'req-1' } });
        stateOf(store).ingestMessages([first]);

        let card = cardOf(store, 'act-1');
        assert.equal(card.needsRefresh, true);
        assert.equal(canChangeEntry(card), false);

        await stateOf(store).refresh('act-1');
        card = cardOf(store, 'act-1');
        assert.equal(server.calls.length, 1);
        assert.equal(server.calls[0].path, `${LIST_PATH}/act-1`);
        assert.equal(server.calls[0].query.conversation_id, 'conv-1');
        assert.equal(card.action.subject, 'Server copy');
        assert.equal(card.needsRefresh, false);
        assert.equal(canChangeEntry(card), true);
        assert.equal(card.reference.messageId, 'm-1');
        assert.equal(card.reference.requestId, 'req-1');

        stateOf(store).ingestMessages([first]);
        assert.equal(server.calls.length, 1, 'the same message again changes nothing');

        held.set('act-1', action('act-1', { status: 'sent', updated_at: T3, can_cancel: false, can_send_now: false }));
        stateOf(store).ingestMessages([
            { ...first, m365_pending_actions: [action('act-1', { status: 'sent', updated_at: T3, can_cancel: false, can_send_now: false })] },
        ]);
        await stateOf(store).refresh('act-1');
        assert.equal(server.calls.length, 2, 'a card that changed is checked again');
        assert.equal(cardOf(store, 'act-1').action.status, 'sent');
    });
});

test('a card a message only points at is fetched, and a failed fetch is retried together with the list', async () => {
    const gate = deferred();
    let failing = true;
    await withServer(async (call) => {
        if (call.kind === 'get' && call.id === 'act-2') {
            if (failing) {
                await gate.promise;
                return json({ error: 'upstream_down', message: 'Down.' }, 500);
            }
            return json({ pending_action: action('act-2') });
        }
        if (call.kind === 'list') return json({ pending_actions: [action('act-2')] });
        return undefined;
    }, async (server) => {
        const store = newStore();
        stateOf(store).trackMessage(message('m-2', { metadata: { m365_pending_action_ids: ['act-2'], m365_request_id: 'req-2' } }));
        assert.equal(stateOf(store).referenceLoading, true, 'the card may yet move, so the page waits for it');
        gate.resolve();
        await settled(() => !stateOf(store).referenceLoading, 'the failed fetch');

        assert.equal(stateOf(store).referenceError, REFERENCE_FAILED_MESSAGE);
        assert.equal(cardOf(store, 'act-2'), undefined, 'nothing is shown for a card that could not be verified');
        assert.equal(server.calls[0].query.conversation_id, 'conv-1');

        failing = false;
        await stateOf(store).loadList();
        assert.deepEqual(
            server.calls.map((call) => call.kind),
            ['get', 'get', 'list'],
            'the missing card is fetched again before the list is read',
        );
        assert.equal(stateOf(store).referenceError, '');
        const card = cardOf(store, 'act-2');
        assert.equal(card.reference.messageId, 'm-2', 'the list does not forget which reply the card belongs to');
        assert.equal(card.reference.requestId, 'req-2');
    });
});

test('a message that names a card the page already holds checks that card again', async () => {
    const held = new Map([['act-1', action('act-1', { updated_at: T2 })]]);
    await withServer(readsFrom(held), async (server) => {
        const store = newStore();
        stateOf(store).remember(action('act-1'), { authoritative: true });
        stateOf(store).trackMessage(message('m-5', { metadata: { m365_pending_action_ids: ['act-1'], m365_request_id: 'req-5' } }));
        assert.equal(cardOf(store, 'act-1').needsRefresh, true);
        assert.equal(cardOf(store, 'act-1').reference.messageId, 'm-5');

        await stateOf(store).refresh('act-1');
        assert.equal(server.calls.length, 1);
        assert.equal(cardOf(store, 'act-1').needsRefresh, false);
        assert.equal(cardOf(store, 'act-1').reference.requestId, 'req-5');
    });
});

test('a card that needs its full content reviewed is not re-checked behind the reader', async () => {
    const full = action('act-3', { updated_at: T2 });
    await withServer(readsFrom(new Map([['act-3', full]])), async (server) => {
        const store = newStore();
        stateOf(store).remember(action('act-3', { review_details_required: true }));
        stateOf(store).trackMessage(message('m-3', { metadata: { m365_pending_action_ids: ['act-3'] } }));
        assert.equal(server.calls.length, 0, 'the person asks for the full content; the page does not fetch it unprompted');
        assert.equal(cardOf(store, 'act-3').needsRefresh, true);
        assert.equal(canChangeEntry(cardOf(store, 'act-3')), false);

        await stateOf(store).reviewFull('act-3');
        const card = cardOf(store, 'act-3');
        assert.equal(server.calls.length, 1);
        assert.equal(card.needsRefresh, false);
        assert.equal(card.bodyOpen, true);
        assert.equal(card.detailVersion, 'v1');
        assert.equal(card.fullDetailsVersion, 'v1');
        assert.equal(card.reviewing, false);
        assert.equal(canChangeEntry(card), true);
    });
});

/* Reading the conversation's cards ---------------------------------------------------- */

test('the list is read a page at a time and each page is requested only once', async () => {
    const pages = {
        '': { pending_actions: [action('a1'), action('a2')], continuation_token: 'tok-2' },
        'tok-2': { pending_actions: [action('a3', { updated_at: T2 })] },
    };
    await withServer((call) => (call.kind === 'list' ? json(pages[call.query.continuation_token ?? '']) : undefined), async (server) => {
        const store = newStore();
        const loading = stateOf(store).loadList();
        assert.equal(stateOf(store).listStatus, 'loading');
        await loading;

        assert.deepEqual(server.calls[0].query, { conversation_id: 'conv-1', limit: '30' });
        assert.equal(stateOf(store).listStatus, 'loaded');
        assert.equal(stateOf(store).continuationToken, 'tok-2');
        assert.deepEqual(Object.keys(stateOf(store).entries), ['a1', 'a2']);
        assert.equal(canChangeEntry(cardOf(store, 'a1')), true, 'the list is the server, so its cards are ready');

        const more = stateOf(store).loadList({ more: true });
        assert.equal(stateOf(store).loadingMore, true);
        await more;
        assert.equal(server.calls[1].query.continuation_token, 'tok-2');
        assert.equal(stateOf(store).loadingMore, false);
        assert.equal(stateOf(store).continuationToken, '');
        const orders = ['a1', 'a2', 'a3'].map((id) => cardOf(store, id).order);
        assert.deepEqual(orders, [...orders].sort((left, right) => left - right), 'cards keep the order they were found in');

        await stateOf(store).loadList({ more: true });
        assert.equal(server.calls.length, 2, 'there is nothing more to ask for');
    });
});

test('a list nobody may read says so, and nothing already on the page can be sent', async () => {
    await withServer(() => json({ error: 'forbidden', message: 'No.' }, 403), async () => {
        const store = newStore();
        stateOf(store).remember(action('a1'), { authoritative: true });
        await stateOf(store).loadList();
        assert.equal(stateOf(store).listStatus, 'error');
        assert.equal(stateOf(store).listError, LIST_PERMISSION_MESSAGE);
        const card = cardOf(store, 'a1');
        assert.equal(card.denied, true);
        assert.equal(card.needsRefresh, true);
        assert.equal(canChangeEntry(card), false);
    });
});

test('a list that failed is not mistaken for an empty one', async () => {
    await withServer(() => json({ error: 'upstream_down', message: 'Down.' }, 500), async () => {
        const store = newStore();
        stateOf(store).remember(action('a1'), { authoritative: true });
        await stateOf(store).loadList();
        assert.equal(stateOf(store).listStatus, 'error');
        assert.equal(stateOf(store).listError, LIST_FAILED_MESSAGE);
        const card = cardOf(store, 'a1');
        assert.equal(card.denied, false, 'a server error is not a refusal');
        assert.equal(card.needsRefresh, true, 'but the card can no longer be trusted until it is checked');
        assert.equal(canChangeEntry(card), false);
    });
});

test('a page with anything that is not a saved action is refused whole', async () => {
    await withServer(() => json({ pending_actions: [action('a1'), { id: 'not-an-action' }] }), async () => {
        const store = newStore();
        await stateOf(store).loadList();
        assert.equal(stateOf(store).listStatus, 'error');
        assert.equal(stateOf(store).listError, LIST_FAILED_MESSAGE);
        assert.deepEqual(Object.keys(stateOf(store).entries), [], 'no card from an unverified page is shown');
    });
});

test('callers that ask for the list together share one request, and a refresh waits for it then asks again', async () => {
    const firstPage = deferred();
    let reads = 0;
    await withServer(async (call) => {
        if (call.kind !== 'list') return undefined;
        reads += 1;
        if (reads === 1) await firstPage.promise;
        return json({ pending_actions: [action(`a${reads}`)] });
    }, async (server) => {
        const store = newStore();
        const first = stateOf(store).loadList();
        const second = stateOf(store).loadList();
        assert.equal(first, second);
        firstPage.resolve();
        await Promise.all([first, second]);
        assert.equal(server.calls.length, 1);

        const running = stateOf(store).loadList();
        const refreshed = stateOf(store).refreshList();
        await Promise.all([running, refreshed]);
        assert.equal(server.calls.length, 3, 'the refresh read the first page again so nothing newer was missed');
        assert.deepEqual(Object.keys(stateOf(store).entries).sort(), ['a1', 'a2', 'a3']);
    });
});

test('an answer for a conversation the person has already left is dropped', async () => {
    for (const honorAbort of [true, false]) {
        const held = deferred();
        await withServer(async (call) => {
            if (call.kind !== 'list') return undefined;
            await held.promise;
            return json({ pending_actions: [action('late')] });
        }, async (server) => {
            const store = newStore();
            const loading = stateOf(store).loadList();
            stateOf(store).setConversation('conv-2');
            held.resolve();
            await loading;
            await settled(() => server.calls.length === 1, 'the original request');
            assert.deepEqual(Object.keys(stateOf(store).entries), [], `the late page was ignored (aborted requests: ${honorAbort})`);
            assert.equal(stateOf(store).listStatus, 'idle');
            assert.equal(stateOf(store).conversationId, 'conv-2');
        }, { honorAbort });
    }
});

/* A card named by id ------------------------------------------------------------------ */

test('a card opened by its id is fetched, placed, and no longer reported as loading', async () => {
    await withServer(readsFrom(new Map([['act-9', action('act-9')]])), async (server) => {
        const store = newStore();
        const loading = stateOf(store).loadById('act-9', { reference: { messageId: 'm-1' } });
        assert.deepEqual(stateOf(store).detail['act-9'], { status: 'loading', message: '' });
        const loaded = await loading;

        assert.equal(loaded.id, 'act-9');
        assert.equal(server.calls[0].query.conversation_id, 'conv-1');
        assert.equal(stateOf(store).detail['act-9'], undefined);
        const card = cardOf(store, 'act-9');
        assert.equal(card.reference.messageId, 'm-1');
        assert.equal(card.fullDetailsVersion, 'v1');
        assert.equal(canChangeEntry(card), true);
    });
});

test('a card that cannot be opened says why, and never loads a path the id could escape into', async () => {
    await withServer((call) => {
        if (call.kind !== 'get') return undefined;
        if (call.id === 'gone') return json({ error: 'not_found', message: 'No such action.' }, 404);
        if (call.id === 'private') return json({ error: 'forbidden', message: 'No.' }, 403);
        return undefined;
    }, async (server) => {
        const store = newStore();
        assert.equal(await stateOf(store).loadById('gone'), null);
        assert.deepEqual(stateOf(store).detail.gone, { status: 'error', message: NOT_LOADED_MESSAGE });
        assert.equal(await stateOf(store).loadById('private'), null);
        assert.deepEqual(stateOf(store).detail.private, { status: 'error', message: PERMISSION_MESSAGE });

        const before = server.calls.length;
        for (const unsafe of ['a/b', '..', 'x?y=1', '']) {
            assert.equal(await stateOf(store).loadById(unsafe), null);
            assert.equal(stateOf(store).detail[unsafe].message, NOT_LOADED_MESSAGE);
        }
        assert.equal(server.calls.length, before, 'an unsafe id never reaches the server');
        assert.deepEqual(Object.keys(stateOf(store).entries), []);
    });
});

test('opening a card the page already holds checks it again and keeps where it was seen', async () => {
    await withServer(readsFrom(new Map([['act-1', action('act-1', { updated_at: T2 })]])), async (server) => {
        const store = newStore();
        stateOf(store).remember(action('act-1'));
        const loaded = await stateOf(store).loadById('act-1', { reference: { requestId: 'req-3' } });
        assert.equal(loaded.updated_at, T2);
        assert.equal(server.calls.length, 1);
        assert.equal(cardOf(store, 'act-1').reference.requestId, 'req-3');
    });
});

test('the Approvals page asks for an action on its own, and names the conversation only for someone else’s', async () => {
    const held = new Map([
        ['mine', action('mine')],
        ['theirs', action('theirs', { viewer_is_owner: false, conversation_id: 'conv-7' })],
    ]);
    await withServer(readsFrom(held), async (server) => {
        const store = createPendingActionsStore({ scope: 'detail' });
        await stateOf(store).loadById('mine');
        await stateOf(store).loadById('theirs');
        assert.equal(server.calls[0].path, `${LIST_PATH}/mine`);
        assert.deepEqual(server.calls[0].query, {});
        assert.deepEqual(server.calls[1].query, {});

        await stateOf(store).refresh('theirs');
        assert.equal(server.calls[2].query.conversation_id, 'conv-7');
        await stateOf(store).refresh('mine');
        assert.deepEqual(server.calls[3].query, {});
    });
});

/* Sending and cancelling -------------------------------------------------------------- */

const SENT = { status: 'sent', updated_at: T2, can_cancel: false, can_send_now: false };

/** Route reads and sends to the given responders; anything else is unexpected. */
function submitServer({ post, get } = {}) {
    return (call) => {
        if (call.kind === 'post') return post?.(call);
        if (call.kind === 'get') return get?.(call);
        return undefined;
    };
}

function readyStore(overrides = {}, id = 'act-1') {
    const store = newStore();
    stateOf(store).remember(action(id, overrides), { authoritative: true });
    return store;
}

test('Send submits the version that was reviewed, once, with the Microsoft 365 safeguards', async () => {
    await withServer(submitServer({ post: () => json({ pending_action: action('act-1', SENT) }) }), async (server) => {
        const store = readyStore();
        const sending = stateOf(store).submit('act-1', 'send-now');
        assert.equal(cardOf(store, 'act-1').busy, true);
        assert.equal(cardOf(store, 'act-1').notice.text, 'Submitting this saved action…');
        assert.equal(canChangeEntry(cardOf(store, 'act-1')), false, 'a second click cannot send it again');
        await sending;

        assert.equal(server.calls.length, 1);
        const post = server.calls[0];
        assert.equal(post.path, `${LIST_PATH}/act-1/send-now`);
        assert.deepEqual(post.body, { expected_version: 'v1' });
        assert.equal(post.headers.get('X-Requested-With'), 'XMLHttpRequest');
        assert.equal(post.headers.get('X-M365-CSRF-Token'), 'c'.repeat(40));
        const before = server.all[server.all.indexOf(post) - 1];
        assert.equal(before.path, '/api/m365/preferences', 'a fresh token is fetched right before the request');

        const card = cardOf(store, 'act-1');
        assert.equal(card.action.status, 'sent');
        assert.equal(card.busy, false);
        assert.equal(card.notice.text, 'Send request checked. Review the server status and delivery note below.');
        assert.equal(card.notice.tone, 'info');

        await stateOf(store).submit('act-1', 'send-now');
        assert.equal(server.calls.length, 1, 'an action that went out cannot be sent again');
    });
});

test('an action that needs the approve route is submitted there, and a cancel goes to its own route', async () => {
    await withServer(submitServer({ post: () => json({ pending_action: action('act-1', { status: 'cancelled', updated_at: T2, can_cancel: false }) }) }), async (server) => {
        const approve = readyStore({ can_send_now: false, can_approve: true });
        // The person's choice picks the route; the card only offers the one the server allows.
        const sending = stateOf(approve).submit('act-1', 'approve');
        assert.equal(cardOf(approve, 'act-1').busy, true);
        await sending;
        assert.equal(server.calls[0].path, `${LIST_PATH}/act-1/approve`);

        const cancel = readyStore();
        const cancelling = stateOf(cancel).submit('act-1', 'cancel');
        assert.equal(cardOf(cancel, 'act-1').notice.text, 'Cancelling this saved action…');
        await cancelling;
        assert.equal(server.calls[1].path, `${LIST_PATH}/act-1/cancel`);
        assert.deepEqual(server.calls[1].body, { expected_version: 'v1' });
        assert.equal(
            cardOf(cancel, 'act-1').notice.text,
            'Cancellation checked. The server status below is authoritative; this does not recall an already sent item.',
        );
        assert.equal(cardOf(cancel, 'act-1').action.status, 'cancelled');
    });
});

test('nothing is sent while something stands between the person and a reviewed, current copy', async () => {
    const blockedSends = [
        ['a copy the server has not confirmed', null, (store) =>
            stateOf(store).ingestMessages([
                message('m-1', { m365_pending_actions: [action('act-1', { review_details_required: true })] }),
            ])],
        ['someone else’s action', { viewer_is_owner: false }],
        ['an action with no way to send it', { can_send_now: false, can_approve: false }],
        ['an action whose full content was not reviewed', { review_details_required: true }],
        ['an action whose body is only a preview', { summary: { subject: 'S', body_preview: 'Hi', body_preview_truncated: true } }],
        ['an action waiting for sign-in', { auth_required: true, sources: ['email'] }],
        ['an action that already went out', { status: 'sent', can_send_now: false, can_cancel: false }],
        ['an action that was cancelled', { status: 'cancelled' }],
    ];
    const blockedCancels = [
        ['an action that cannot be cancelled', { can_cancel: false }],
        ['someone else’s action', { viewer_is_owner: false }],
        ['an action that was cancelled already', { status: 'cancelled' }],
    ];
    await withServer(() => undefined, async (server) => {
        for (const [name, overrides, prepare] of blockedSends) {
            const store = newStore();
            if (prepare) prepare(store);
            else stateOf(store).remember(action('act-1', overrides), { authoritative: true });
            await stateOf(store).submit('act-1', 'send-now');
            assert.equal(cardOf(store, 'act-1').busy, false, name);
        }
        for (const [name, overrides] of blockedCancels) {
            const store = readyStore(overrides);
            await stateOf(store).submit('act-1', 'cancel');
            assert.equal(cardOf(store, 'act-1').busy, false, name);
        }
        assert.equal(server.calls.length, 0, 'none of these may reach the server');
    });
});

test('cancelling stays possible when only sending is blocked', async () => {
    const blocked = {
        'waiting for sign-in': { auth_required: true, sources: ['email'] },
        'content not reviewed': { review_details_required: true },
        'no way to send it': { can_send_now: false, can_approve: false },
    };
    await withServer(submitServer({ post: () => json({ pending_action: action('act-1', { status: 'cancelled', updated_at: T2 }) }) }), async (server) => {
        for (const [name, overrides] of Object.entries(blocked)) {
            const before = server.calls.length;
            const store = readyStore(overrides);
            await stateOf(store).submit('act-1', 'cancel');
            assert.equal(server.calls.length, before + 1, name);
            assert.equal(server.calls[before].operation, 'cancel', name);
        }
    });
});

test('a second click while a send is in flight does not send twice', async () => {
    const gate = deferred();
    await withServer(submitServer({ post: async () => {
        await gate.promise;
        return json({ pending_action: action('act-1', SENT) });
    } }), async (server) => {
        const store = readyStore();
        const first = stateOf(store).submit('act-1', 'send-now');
        const second = stateOf(store).submit('act-1', 'send-now');
        const cancel = stateOf(store).submit('act-1', 'cancel');
        gate.resolve();
        await Promise.all([first, second, cancel]);
        assert.equal(server.calls.length, 1);
    });
});

test('a conflict makes the person look again; it never retries on their behalf', async () => {
    await withServer(submitServer({
        post: () => json({ error: 'conflict', message: 'Changed.' }, 409),
        get: () => json({ pending_action: action('act-1', { version: 'v2', updated_at: T2, subject: 'Edited elsewhere' }) }),
    }), async (server) => {
        const store = readyStore();
        await stateOf(store).submit('act-1', 'send-now');
        assert.deepEqual(server.calls.map((call) => call.kind), ['post', 'get']);
        const card = cardOf(store, 'act-1');
        assert.equal(card.action.version, 'v2');
        assert.equal(card.action.subject, 'Edited elsewhere');
        assert.equal(card.fullDetailsVersion, 'v2');
        assert.equal(
            card.notice.text,
            'This action changed or is already being processed. Review its current status and details before making another choice.',
        );
        assert.equal(card.busy, false);
        assert.equal(card.needsRefresh, false);
    });

    await withServer(submitServer({
        post: () =>
            json({
                error: 'conflict',
                message: 'Already being sent.',
                pending_action: action('act-1', { version: 'v2', status: 'sending', updated_at: T2, can_cancel: false, can_send_now: false }),
            }, 409),
    }), async (server) => {
        const store = readyStore();
        await stateOf(store).submit('act-1', 'send-now');
        assert.deepEqual(server.calls.map((call) => call.kind), ['post'], 'the conflict already carried the current state');
        assert.equal(cardOf(store, 'act-1').action.status, 'sending');
        assert.equal(cardOf(store, 'act-1').notice.tone, 'warn');
    });
});

test('a response nobody could confirm is never retried; the server is asked what became of it', async () => {
    const unconfirmed = {
        'a server error': () => json({ error: 'upstream_down', message: 'Down.' }, 500),
        'a refusal inside a success response': () => json({ success: false, message: 'Declined.' }),
        'a success response without the action': () => json({ ok: true }),
    };
    for (const [name, respond] of Object.entries(unconfirmed)) {
        await withServer(submitServer({
            post: respond,
            get: () => json({ pending_action: action('act-1', { updated_at: T2 }) }),
        }), async (server) => {
            const store = readyStore();
            const sending = stateOf(store).submit('act-1', 'send-now');
            await sending;
            assert.deepEqual(server.calls.map((call) => call.kind), ['post', 'get'], name);
            const card = cardOf(store, 'act-1');
            assert.equal(
                card.notice.text,
                'The response was not confirmed. Current server status has been refreshed. Review it before making another choice; no send was retried automatically.',
                name,
            );
            assert.equal(card.needsRefresh, false, name);
            assert.equal(card.busy, false, name);
        });
    }
});

test('when the status cannot be checked after an unconfirmed response the card stays blocked', async () => {
    await withServer(submitServer({
        post: () => json({ error: 'upstream_down', message: 'Down.' }, 500),
        get: () => json({ error: 'upstream_down', message: 'Still down.' }, 500),
    }), async (server) => {
        const store = readyStore();
        await stateOf(store).submit('act-1', 'send-now');
        const card = cardOf(store, 'act-1');
        assert.equal(card.needsRefresh, true);
        assert.equal(card.notice.text, 'The current action status could not be checked. Refresh status before trying again.');
        assert.equal(canChangeEntry(card), false);

        await stateOf(store).submit('act-1', 'send-now');
        await stateOf(store).submit('act-1', 'cancel');
        assert.equal(server.calls.length, 2, 'neither choice reaches the server until the status is known');
    });
});

test('a refusal blocks the card until its access has been checked again', async () => {
    let refused = true;
    await withServer(submitServer({
        post: () => json({ error: 'forbidden', message: 'No.' }, 403),
        get: () => (refused ? undefined : json({ pending_action: action('act-1', { updated_at: T2 }) })),
    }), async (server) => {
        const store = readyStore();
        await stateOf(store).submit('act-1', 'send-now');
        const card = cardOf(store, 'act-1');
        assert.equal(card.denied, true);
        assert.equal(card.notice.text, 'You do not have permission to change this action. Refresh status to check your current access.');
        assert.equal(canChangeEntry(card), false);
        assert.deepEqual(server.calls.map((call) => call.kind), ['post']);

        refused = false;
        await stateOf(store).refresh('act-1');
        assert.equal(cardOf(store, 'act-1').denied, false);
        assert.equal(canChangeEntry(cardOf(store, 'act-1')), true);
    });
});

test('a send that needs a Microsoft 365 sign-in is held until the person reconnects, but can still be cancelled', async () => {
    const needsSignIn = {
        error: 'auth_required',
        auth_required: true,
        message: 'Sign in again.',
        sources: ['email'],
        scopes: ['Mail.Send'],
    };
    let respond = () => json(needsSignIn, 401);
    await withServer(submitServer({ post: () => respond() }), async (server) => {
        const store = readyStore();
        await stateOf(store).submit('act-1', 'send-now');
        const card = cardOf(store, 'act-1');
        assert.equal(card.auth.auth_required, true);
        assert.deepEqual(card.auth.sources, ['email']);
        assert.equal(
            card.notice.text,
            'Microsoft 365 sign-in is required. Reconnect, review this same saved action, then select Send again. Signing in does not send it.',
        );
        assert.deepEqual(server.calls.map((call) => call.kind), ['post'], 'a sign-in prompt is not a failure to retry');

        await stateOf(store).submit('act-1', 'send-now');
        assert.equal(server.calls.length, 1, 'sending is blocked until the person has reconnected');

        respond = () => json({ pending_action: action('act-1', { status: 'cancelled', updated_at: T2 }) });
        await stateOf(store).submit('act-1', 'cancel');
        assert.equal(server.calls.length, 2);
        assert.equal(server.calls[1].operation, 'cancel');
        assert.equal(cardOf(store, 'act-1').auth, null, 'a cancel that went through ends the sign-in prompt');
    });
});

test('a send that needs a sharing decision is held until the server’s copy says otherwise', async () => {
    let respond = () =>
        json({ error: 'approval_required', approval_required: true, message: 'Approve sharing first.', approval_id: 'ap-1' }, 409);
    await withServer(submitServer({
        post: () => respond(),
        get: () => json({ pending_action: action('act-1', { updated_at: T2 }) }),
    }), async (server) => {
        const store = readyStore();
        await stateOf(store).submit('act-1', 'send-now');
        const card = cardOf(store, 'act-1');
        assert.equal(card.approvalRequired.approval_id, 'ap-1');
        assert.equal(
            card.notice.text,
            'Review the saved Microsoft 365 sharing decision before sending. Approving it does not send this action; return here and select Send again.',
        );
        assert.deepEqual(server.calls.map((call) => call.kind), ['post'], 'the sharing decision is made elsewhere; nothing is retried');

        await stateOf(store).submit('act-1', 'send-now');
        assert.equal(server.calls.length, 1, 'sending is blocked while the decision is outstanding');

        // Coming back from the Approvals page reads the card again; the server decides whether to send.
        await stateOf(store).refresh('act-1');
        assert.equal(cardOf(store, 'act-1').approvalRequired, null);
        respond = () => json({ pending_action: action('act-1', SENT) });
        await stateOf(store).submit('act-1', 'send-now');
        assert.equal(server.calls.filter((call) => call.kind === 'post').length, 2);
        assert.equal(cardOf(store, 'act-1').action.status, 'sent');
    });
});

test('a send does not outlive the conversation it was made in', async () => {
    const gate = deferred();
    await withServer(submitServer({ post: async () => {
        await gate.promise;
        return json({ pending_action: action('act-1', SENT) });
    } }), async (server) => {
        const store = readyStore();
        const sending = stateOf(store).submit('act-1', 'send-now');
        await settled(() => server.calls.length === 1, 'the send request');
        stateOf(store).setConversation('conv-2');
        gate.resolve();
        await sending;
        assert.deepEqual(Object.keys(stateOf(store).entries), [], 'the answer belongs to a conversation that is no longer open');
    });
});

/* Reviewing the full content -------------------------------------------------------------- */

test('opening a card’s body checks the version being read, once', async () => {
    await withServer(readsFrom(new Map([['act-1', action('act-1', { updated_at: T2 })]])), async (server) => {
        const store = readyStore();
        stateOf(store).setBodyOpen('act-1', true);
        assert.equal(cardOf(store, 'act-1').bodyOpen, true);
        assert.equal(cardOf(store, 'act-1').detailVersion, 'v1');
        await stateOf(store).refresh('act-1');
        assert.equal(server.calls.length, 1);

        stateOf(store).setBodyOpen('act-1', false);
        stateOf(store).setBodyOpen('act-1', true);
        assert.equal(server.calls.length, 1, 'the same version is not checked every time the body is opened');

        stateOf(store).remember(action('act-1', { version: 'v2', updated_at: T3 }));
        stateOf(store).setBodyOpen('act-1', false);
        stateOf(store).setBodyOpen('act-1', true);
        await stateOf(store).refresh('act-1');
        assert.equal(server.calls.length, 2, 'a new version is a new thing to read');
    });
});

test('a full review that cannot be completed leaves the card blocked and says so', async () => {
    let respond = () => json({ error: 'upstream_down', message: 'Down.' }, 500);
    await withServer(submitServer({ get: () => respond() }), async (server) => {
        const store = readyStore({ review_details_required: true });
        await stateOf(store).reviewFull('act-1');
        let card = cardOf(store, 'act-1');
        assert.equal(card.reviewing, false);
        assert.equal(card.bodyOpen, false);
        assert.equal(card.needsRefresh, true);
        assert.equal(canChangeEntry(card), false);
        assert.equal(card.notice.text, 'The current action status could not be checked. Refresh status before trying again.');

        respond = () => json({ pending_action: action('act-1', { review_details_required: true, updated_at: T2 }) });
        await stateOf(store).reviewFull('act-1');
        card = cardOf(store, 'act-1');
        assert.equal(card.reviewing, false);
        assert.equal(card.needsRefresh, true, 'a server copy that still withholds the content is not a review');
        assert.equal(card.notice.text, 'The complete saved content could not be verified. Review full details again before sending.');
        assert.equal(server.calls.length, 2);
    });
});

/* Scheduled sends --------------------------------------------------------------------- */

test('a scheduled action is checked once its time has come, not on every tick', async () => {
    const due = new Date(Date.now() - 60_000).toISOString();
    const later = new Date(Date.now() + 3_600_000).toISOString();
    const stillScheduled = action('due', { status: 'scheduled', will_auto_send: true, auto_send_at_utc: due, updated_at: T2 });
    await withServer(readsFrom(new Map([['due', stillScheduled]])), async (server) => {
        const store = newStore();
        stateOf(store).remember(action('due', { status: 'scheduled', will_auto_send: true, auto_send_at_utc: due }), { authoritative: true });
        stateOf(store).remember(action('later', { status: 'scheduled', will_auto_send: true, auto_send_at_utc: later }), { authoritative: true });

        stateOf(store).pollIfDue('later');
        stateOf(store).pollIfDue('missing');
        assert.equal(server.calls.length, 0, 'it is not time yet');

        stateOf(store).pollIfDue('due');
        stateOf(store).pollIfDue('due');
        await stateOf(store).refresh('due');
        assert.equal(server.calls.length, 1, 'one check serves every tick that arrives while it runs');
        assert.equal(cardOf(store, 'due').action.updated_at, T2, 'the answer was taken');
        assert.ok(cardOf(store, 'due').nextRefreshAt > Date.now(), 'the next check waits a while');

        stateOf(store).pollIfDue('due');
        assert.equal(server.calls.length, 1, 'the server has not sent it yet, but asking again straight away would not help');
    });
});

/* Rules about when a card can be changed -------------------------------------------- */

test('a card can be changed only when nothing is in the way', () => {
    const store = newStore();
    const base = stateOf(store).remember(action('act-1'), { authoritative: true });
    assert.equal(canChangeEntry(base), true);

    const inTheWay = {
        sending: { busy: true },
        refreshing: { refreshing: true },
        unverified: { needsRefresh: true },
        denied: { denied: true },
        'someone else’s': { action: { ...base.action, viewer_is_owner: false } },
        unversioned: { action: { ...base.action, version: '' } },
        'no version at all': { action: { ...base.action, version: undefined } },
    };
    for (const [name, patch] of Object.entries(inTheWay)) {
        assert.equal(canChangeEntry({ ...base, ...patch }), false, name);
    }
    const unknownOwner = { ...base.action };
    delete unknownOwner.viewer_is_owner;
    assert.equal(canChangeEntry({ ...base, action: unknownOwner }), true, 'an action that does not say otherwise is the viewer’s own');

    for (const status of ['pending', 'scheduled', 'review_required']) {
        assert.equal(canChangeEntry({ ...base, action: { ...base.action, status } }), true, status);
    }
    for (const status of ['sending', 'sent', 'cancelled', 'failed', 'expired', 'unknown']) {
        assert.equal(canChangeEntry({ ...base, action: { ...base.action, status } }), false, status);
    }
});

/* Focus requests from a notification -------------------------------------------------- */

test('a notification can ask for a card before its conversation has finished opening', () => {
    const store = newStore({ conversationId: '' });
    stateOf(store).requestFocus('act-1', ' conv-9 ');
    const first = stateOf(store).focusRequest;
    assert.deepEqual({ id: first.id, conversationId: first.conversationId }, { id: 'act-1', conversationId: 'conv-9' });

    stateOf(store).requestFocus('act-1', 'conv-9');
    assert.notEqual(stateOf(store).focusRequest.key, first.key, 'asking again is a new request');

    for (const unsafe of ['a/b', '..', 'x?y', '', '   ', 'a\nb']) {
        const before = stateOf(store).focusRequest;
        stateOf(store).requestFocus(unsafe, 'conv-9');
        assert.equal(stateOf(store).focusRequest, before, `${JSON.stringify(unsafe)} is not a card id`);
    }

    stateOf(store).setConversation('conv-9');
    assert.equal(stateOf(store).focusRequest.id, 'act-1', 'the request survives the switch it was waiting for');
    stateOf(store).setConversation('conv-10');
    assert.equal(stateOf(store).focusRequest, null, 'a request for another conversation is dropped');

    stateOf(store).requestFocus('act-2', 'conv-10');
    stateOf(store).clearFocus();
    assert.equal(stateOf(store).focusRequest, null);
    stateOf(store).clearFocus();
});

test('leaving a conversation forgets its cards, its place in the list and what it was waiting for', async () => {
    await withServer(() => json({ pending_actions: [action('a1')], continuation_token: 'tok' }), async () => {
        const store = newStore();
        await stateOf(store).loadList();
        stateOf(store).setLiveStream({ conversationId: 'conv-1', userMessageId: 'u-1' });
        stateOf(store).requestFocus('a1', 'conv-1');
        assert.equal(stateOf(store).continuationToken, 'tok');

        const epoch = stateOf(store).epoch;
        stateOf(store).setConversation('conv-1');
        assert.equal(stateOf(store).epoch, epoch, 'opening the conversation that is already open changes nothing');

        stateOf(store).setConversation('conv-2');
        const state = stateOf(store);
        assert.equal(state.epoch, epoch + 1);
        assert.deepEqual(
            { entries: state.entries, status: state.listStatus, token: state.continuationToken, live: state.liveStream, focus: state.focusRequest },
            { entries: {}, status: 'idle', token: '', live: null, focus: null },
        );

        stateOf(store).setConversation('conv-3');
        stateOf(store).requestFocus('a1', 'conv-3');
        stateOf(store).reset();
        assert.deepEqual(
            { conversation: stateOf(store).conversationId, focus: stateOf(store).focusRequest, epoch: stateOf(store).epoch },
            { conversation: '', focus: null, epoch: epoch + 3 },
        );
    });
});

/* Cards that arrive with a reply --------------------------------------------------------- */

test('a message with nothing to do with outgoing actions is passed over', () => {
    const store = newStore();
    stateOf(store).ingestMessages([message('m-0'), null, 'text', { content: 'no id', m365_pending_actions: [action('act-1')] }]);
    stateOf(store).trackMessage(null);
    stateOf(store).trackMessage('text');
    assert.deepEqual(Object.keys(stateOf(store).entries), []);
    assert.equal(stateOf(store).referenceLoading, false);
});

test('cards on a live stream are drawn under the turn that caused them, and move to the reply once it is saved', () => {
    const store = newStore();
    const frame = { type: 'm365_pending_action', pending_action: action('s-1') };
    stateOf(store).handleStreamPayload(frame, { conversationId: 'conv-1', userMessageId: 'u-1' });
    let card = cardOf(store, 's-1');
    assert.deepEqual(
        { ...card.reference },
        { messageId: '', userMessageId: 'u-1', fallbackMessageId: 'u-1', requestId: '' },
    );
    assert.equal(card.needsRefresh, false, 'a live frame is as fresh as the server can make it');

    stateOf(store).handleStreamPayload(
        { type: 'done', message_id: 'a-1', user_message_id: 'u-1', request_id: 'req-1', m365_pending_actions: [action('s-1')] },
        { conversationId: 'conv-1', userMessageId: 'u-1' },
    );
    card = cardOf(store, 's-1');
    assert.equal(card.reference.messageId, 'a-1');
    assert.equal(card.reference.requestId, 'req-1');
    assert.equal(card.reference.userMessageId, 'u-1');
});

test('a stream frame for another conversation, or none, is not drawn', () => {
    const none = newStore({ conversationId: '' });
    stateOf(none).handleStreamPayload({ pending_action: action('s-1') }, { conversationId: 'conv-1' });
    assert.deepEqual(Object.keys(stateOf(none).entries), []);

    const store = newStore();
    stateOf(store).handleStreamPayload({ pending_action: action('s-1') }, { conversationId: 'conv-2' });
    assert.deepEqual(Object.keys(stateOf(store).entries), []);
    stateOf(store).handleStreamPayload({ pending_action: action('s-1') });
    assert.deepEqual(Object.keys(stateOf(store).entries), ['s-1'], 'a frame that names no conversation belongs to the one open');
});

test('cards that were saved but could not be built are recovered from the list', async () => {
    await withServer((call) => (call.kind === 'list' ? json({ pending_actions: [action('saved')] }) : undefined), async (server) => {
        const store = newStore();
        stateOf(store).handleStreamPayload(
            { m365_pending_actions_error: { message: 'The cards could not be built.' } },
            { conversationId: 'conv-1' },
        );
        assert.equal(stateOf(store).referenceError, 'The cards could not be built.');
        assert.equal(stateOf(store).listStatus, 'loading', 'the list is the way back to what was saved');
        await settled(() => stateOf(store).listStatus === 'loaded', 'the list');
        assert.equal(server.calls.length, 1);
        assert.deepEqual(Object.keys(stateOf(store).entries), ['saved']);
        assert.equal(stateOf(store).referenceError, '');
    });

    await withServer(() => json({ error: 'upstream_down', message: 'Down.' }, 500), async () => {
        const store = newStore();
        stateOf(store).handleStreamPayload({ m365_pending_actions_error: { error: 'm365_pending_actions_unavailable' } }, { conversationId: 'conv-1' });
        await settled(() => stateOf(store).listStatus === 'error', 'the failed list');
        assert.equal(
            stateOf(store).referenceError,
            'Microsoft 365 actions were saved, but their cards could not be loaded. Reload the conversation to recover them. Do not repeat the request.',
            'the person is still told, since the list did not help',
        );
    });
});

test('when the saved id of the turn replaces its temporary one, its cards follow', () => {
    const store = newStore();
    stateOf(store).setLiveStream({ conversationId: 'conv-1', userMessageId: 'tmp-1' });
    stateOf(store).handleStreamPayload({ pending_action: action('mine') }, { conversationId: 'conv-1', userMessageId: 'tmp-1' });
    stateOf(store).handleStreamPayload({ pending_action: action('other') }, { conversationId: 'conv-1', userMessageId: 'tmp-0' });
    const untouched = cardOf(store, 'other');

    const same = stateOf(store);
    stateOf(store).setLiveStream({ conversationId: 'conv-1', userMessageId: 'tmp-1' });
    assert.equal(stateOf(store), same, 'announcing the same turn again changes nothing');

    stateOf(store).setLiveStream({ conversationId: 'conv-1', userMessageId: 'u-9' });
    assert.deepEqual(stateOf(store).liveStream, { conversationId: 'conv-1', userMessageId: 'u-9' });
    assert.equal(cardOf(store, 'mine').reference.userMessageId, 'u-9');
    assert.equal(cardOf(store, 'mine').reference.fallbackMessageId, 'u-9');
    assert.equal(cardOf(store, 'other'), untouched, 'another turn’s card is left as it was');

    stateOf(store).setLiveStream({ conversationId: 'conv-2', userMessageId: 'x-1' });
    assert.equal(cardOf(store, 'mine').reference.userMessageId, 'u-9', 'a different conversation renames nothing');

    stateOf(store).setLiveStream(null);
    assert.equal(stateOf(store).liveStream, null);
    const quiet = stateOf(store);
    stateOf(store).setLiveStream(null);
    assert.equal(stateOf(store), quiet);
});
