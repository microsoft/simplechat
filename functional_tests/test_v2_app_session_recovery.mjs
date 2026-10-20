// test_v2_app_session_recovery.mjs
// Version: 0.261.351
// Implemented in: 0.261.338
// Multipart response negotiation fixed in: 0.261.351
// Executes real request, bootstrap, replay and pending-action modules with only HTTP replaced.

import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import './test_support/tsResolve.mjs';

const { api, isAppSessionError, isAppSessionRequired, verifyAppSession, uploadFile } =
    await import('../application/v2_ui/src/lib/apiClient.ts');
const { SESSION_REQUIRED_MESSAGE, useAppSessionStore } =
    await import('../application/v2_ui/src/stores/appSessionStore.ts');
const { useBootstrapStore } = await import('../application/v2_ui/src/stores/bootstrapStore.ts');
const { fetchPlanReplayPreview } = await import('../application/v2_ui/src/lib/workflowPlanReplay.ts');
const { createPendingActionsStore, canChangeEntry, LIST_FAILED_MESSAGE } =
    await import('../application/v2_ui/src/stores/m365PendingActionsStore.ts');

const originalFetch = globalThis.fetch;
const originalNow = Date.now;
let clock = originalNow();
let requests;
let handler;
const json = (body, status = 200) => new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
});
const expired = () => json({ error: 'Session expired', requires_reauth: true }, 401);
const bootstrap = (id = 'owner') => ({ user: { id }, features: {} });
const pendingAction = () => ({
    id: 'draft', type: 'msgraph_pending_action', conversation_id: 'chat', version: 'v1',
    status: 'pending', operation: 'send_mail', can_send_now: true, can_cancel: true,
    viewer_is_owner: true,
});

beforeEach(() => {
    clock += 20_000;
    Date.now = () => clock;
    useAppSessionStore.setState({ status: 'ready', viewerId: 'owner', revision: 0 });
    useBootstrapStore.setState({ data: bootstrap(), loading: false, error: null, authExpired: false });
    requests = [];
    handler = () => { throw new Error('Install an HTTP response for this test.'); };
    globalThis.fetch = async (path, init = {}) => {
        requests.push({ path, ...init });
        return handler(String(path), init);
    };
});

afterEach(() => {
    globalThis.fetch = originalFetch;
    Date.now = originalNow;
    useAppSessionStore.setState({ status: 'ready', viewerId: '', revision: 0 });
});

test('only explicit app-session failures require app sign-in', () => {
    for (const [status, body, expected] of [
        [401, { requires_reauth: true }, true],
        [401, { error: 'Unauthorized', message: 'Authentication required' }, true],
        [401, { error: 'not_logged_in' }, true],
        [403, { requires_reauth: true }, true],
        [403, { error: 'forbidden' }, false],
        [403, { error: 'Forbidden', message: 'Insufficient permissions' }, false],
        [401, { error: 'm365_reconnect_required', auth_required: true }, false],
        [401, { error: 'consent_required' }, false],
        [500, { requires_reauth: true }, false],
        [401, null, false],
    ]) {
        assert.equal(isAppSessionRequired(status, body), expected, JSON.stringify(body));
    }
});

test('concurrent M365 and schedule failures produce one session state, never M365 permission copy', async () => {
    handler = () => expired();
    const store = createPendingActionsStore();
    store.getState().setConversation('chat');
    const outcomes = await Promise.allSettled([
        store.getState().loadList(), fetchPlanReplayPreview('run', 'chat'),
    ]);
    assert.equal(useAppSessionStore.getState().status, 'required');
    assert.equal(useAppSessionStore.getState().revision, 1);
    assert.equal(store.getState().listStatus, 'error');
    assert.equal(store.getState().listError, SESSION_REQUIRED_MESSAGE);
    assert.equal(outcomes[1].reason.code, 'app_session_required');
    assert.equal(outcomes[1].reason.text, SESSION_REQUIRED_MESSAGE);
    assert.equal(requests.length, 2);
    assert.ok(requests.every((request) => !request.method || request.method === 'GET'));
});

test('a rejected fetch checks the session once without replaying even a POST', async () => {
    handler = (path) => path === '/api/v2/bootstrap' ? expired() : Promise.reject(new TypeError('Failed to fetch'));
    const result = await Promise.allSettled([api.post('/save', { value: 'reviewed' }), api.get('/preview')]);
    assert.ok(result.every((item) => item.status === 'rejected' && isAppSessionError(item.reason)));
    assert.equal(requests.filter((item) => item.path === '/api/v2/bootstrap').length, 1);
    assert.equal(requests.filter((item) => item.method === 'POST').length, 1);
    assert.equal(useAppSessionStore.getState().status, 'required');
});

test('offline failures remain connection failures and do not recursively probe', async () => {
    handler = () => Promise.reject(new TypeError('offline'));
    await assert.rejects(api.get('/preview'), TypeError);
    assert.deepEqual(requests.map((item) => item.path), ['/preview', '/api/v2/bootstrap']);
    assert.equal(useAppSessionStore.getState().status, 'ready');
    await assert.rejects(api.get('/another-preview'), TypeError);
    assert.equal(requests.length, 3, 'verification is rate limited');
});

for (const path of [
    '/api/v2/bootstrap',
    '/api/v2/bootstrap?refresh=1',
    '/api/approvals?request_id=caller-selected',
    '/api/user/agents/caller-selected',
]) {
    test(`a request URL cannot bypass session verification: ${path}`, async () => {
        let first = true;
        handler = (url) => {
            if (first) {
                first = false;
                return Promise.reject(new TypeError('Failed to fetch'));
            }
            assert.equal(url, '/api/v2/bootstrap', 'verification always uses the fixed app endpoint');
            return expired();
        };
        await assert.rejects(api.get(path), isAppSessionError);
        assert.deepEqual(requests.map((item) => item.path), [path, '/api/v2/bootstrap']);
        assert.equal(useAppSessionStore.getState().status, 'required');
    });
}

test('a rejected bootstrap request has one direct probe, never recursive verification', async () => {
    handler = () => Promise.reject(new TypeError('offline'));
    await assert.rejects(api.get('/api/v2/bootstrap'), TypeError);
    assert.deepEqual(requests.map((item) => item.path), ['/api/v2/bootstrap', '/api/v2/bootstrap']);
    assert.equal(useAppSessionStore.getState().status, 'ready');
});

test('provider reconnect and object-level denial never mark the app session expired', async () => {
    for (const [status, body] of [
        [401, { error: 'm365_reconnect_required', auth_required: true }],
        [403, { error: 'forbidden' }],
        [500, { error: 'service_unavailable' }],
    ]) {
        handler = () => json(body, status);
        await assert.rejects(api.get('/api/msgraph/pending-actions/draft'),
            (error) => error.status === status && !isAppSessionError(error));
        assert.equal(useAppSessionStore.getState().status, 'ready');
    }
    assert.equal(requests.length, 3);
});

test('an app-wide role denial is not described as a Microsoft 365 conversation permission error', async () => {
    handler = () => json({ error: 'Forbidden', message: 'Insufficient permissions (User/Admin role required)' }, 403);
    const store = createPendingActionsStore();
    store.getState().setConversation('chat');
    store.getState().remember(pendingAction(), { authoritative: true });
    await store.getState().loadList();
    assert.equal(store.getState().listStatus, 'error');
    assert.equal(store.getState().listError, LIST_FAILED_MESSAGE);
    assert.equal(canChangeEntry(store.getState().entries.draft), false);
    assert.equal(useAppSessionStore.getState().status, 'ready');
});

test('a known sign-in redirect is not parsed as a successful API response', async () => {
    handler = () => {
        const response = new Response('<html>Sign in</html>');
        Object.defineProperties(response, {
            redirected: { value: true }, url: { value: 'https://simplechat.example/login' },
        });
        return response;
    };
    await assert.rejects(api.get('/preview'), isAppSessionError);
    assert.equal(useAppSessionStore.getState().status, 'required');
});

test('a session check is bounded and an abort remains unconfirmed, not expired', async () => {
    handler = (_path, init) => {
        assert.ok(init.signal);
        assert.equal(init.cache, 'no-store');
        return Promise.reject(new DOMException('Check aborted', 'AbortError'));
    };
    const confirmed = await verifyAppSession(true);
    assert.equal(confirmed, false);
    assert.equal(useAppSessionStore.getState().status, 'ready');
    assert.equal(requests.length, 1);
});

test('verification actually aborts after five seconds, not before', async (context) => {
    context.mock.timers.enable({ apis: ['setTimeout'] });
    handler = (_path, init) => new Promise((_resolve, reject) => {
        init.signal.addEventListener('abort', () => reject(new DOMException('Timed out', 'AbortError')));
    });
    let settled = false;
    const checking = verifyAppSession(true).then((result) => {
        settled = true;
        return result;
    });
    context.mock.timers.tick(4999);
    await Promise.resolve();
    assert.equal(settled, false);
    context.mock.timers.tick(1);
    const confirmed = await checking;
    assert.equal(confirmed, false);
    assert.equal(useAppSessionStore.getState().status, 'ready');
});

test('automatic verification becomes available again only after the fifteen-second cooldown', async () => {
    handler = () => Promise.reject(new TypeError('offline'));
    await assert.rejects(api.get('/preview'), TypeError);
    clock += 14_999;
    await assert.rejects(api.get('/preview'), TypeError);
    assert.equal(requests.filter((item) => item.path === '/api/v2/bootstrap').length, 1);
    clock += 1;
    await assert.rejects(api.get('/preview'), TypeError);
    assert.equal(requests.filter((item) => item.path === '/api/v2/bootstrap').length, 2);
});

test('successful same-user verification clears the notice but not an operation or draft', async () => {
    useAppSessionStore.getState().requireSignIn(0);
    handler = () => json(bootstrap());
    const confirmed = await verifyAppSession(true);
    assert.equal(confirmed, true);
    assert.equal(useAppSessionStore.getState().status, 'ready');
    assert.deepEqual(requests.map((item) => item.path), ['/api/v2/bootstrap']);
});

test('a bootstrap read started before expiry cannot clear it', async () => {
    let finish;
    handler = () => new Promise((resolve) => { finish = resolve; });
    const reading = useBootstrapStore.getState().refresh();
    useAppSessionStore.getState().requireSignIn(0);
    finish(json(bootstrap()));
    await reading;
    assert.equal(useAppSessionStore.getState().status, 'required');
    assert.equal(useBootstrapStore.getState().loading, false);
    assert.equal(useBootstrapStore.getState().error, null);
    assert.equal(useBootstrapStore.getState().authExpired, false);
});

test('an old request failure cannot expire a newly verified session', async () => {
    let finish;
    handler = () => new Promise((resolve) => { finish = resolve; });
    const stale = api.get('/old-preview');
    useAppSessionStore.getState().requireSignIn(0);
    handler = () => json(bootstrap());
    const confirmed = await verifyAppSession(true);
    assert.equal(confirmed, true);
    finish(expired());
    await assert.rejects(stale, isAppSessionError);
    assert.equal(useAppSessionStore.getState().status, 'ready');
});

test('an aborted protected request does not run a session probe', async () => {
    const controller = new AbortController();
    controller.abort();
    handler = () => Promise.reject(new TypeError('aborted'));
    await assert.rejects(api.get('/preview', controller.signal), TypeError);
    assert.equal(requests.length, 1);
    assert.equal(useAppSessionStore.getState().status, 'ready');
});

test('an account switch cannot install another identity over the old chat', async () => {
    const previous = useBootstrapStore.getState().data;
    handler = () => json(bootstrap('someone-else'));
    await useBootstrapStore.getState().refresh();
    assert.equal(useAppSessionStore.getState().status, 'changed');
    assert.equal(useBootstrapStore.getState().data, previous);
});

test('app-session expiry on a saved draft does not offer a Microsoft 365 reconnect', async () => {
    const store = createPendingActionsStore();
    store.getState().setConversation('chat');
    store.getState().remember(pendingAction(), { authoritative: true });
    handler = () => expired();
    await store.getState().refresh('draft');
    const entry = store.getState().entries.draft;
    assert.equal(entry.auth, null);
    assert.equal(entry.notice.text, SESSION_REQUIRED_MESSAGE);
    assert.equal(canChangeEntry(entry), false);
});

test('upload session failures use the same app notice without retrying multipart data', async () => {
    handler = () => expired();
    await assert.rejects(uploadFile('/upload', new FormData()), isAppSessionError);
    assert.equal(useAppSessionStore.getState().status, 'required');
    assert.equal(requests.length, 1);
});

for (const path of ['/upload', '/api/documents/upload']) {
    test(`multipart requests negotiate JSON without changing the upload: ${path}`, async () => {
        const controller = new AbortController();
        const formData = new FormData();
        formData.append('file', new File(['program,amount\nA,10\n'], 'ledger.csv', { type: 'text/csv' }));
        formData.append('conversation_id', 'chat');
        handler = (_path, init) => {
            const headers = new Headers(init.headers);
            assert.equal(headers.get('Accept'), 'application/json');
            assert.equal(headers.has('Content-Type'), false, 'the browser owns the multipart boundary');
            assert.equal(init.body, formData);
            assert.equal(init.signal, controller.signal);
            assert.equal(init.credentials, 'same-origin');
            assert.equal(init.method, 'POST');
            return json({ success: true });
        };
        const result = await uploadFile(path, formData, controller.signal);
        assert.deepEqual(result, { success: true });
        assert.equal(requests.length, 1);
        assert.equal(useAppSessionStore.getState().status, 'ready');
    });

    test(`negotiated upload auth errors never redirect or replay: ${path}`, async () => {
        handler = (_path, init) => {
            assert.equal(new Headers(init.headers).get('Accept'), 'application/json');
            return json({ error: 'Unauthorized', message: 'Authentication required' }, 401);
        };
        await assert.rejects(uploadFile(path, new FormData()), isAppSessionError);
        assert.equal(requests.length, 1);
        assert.equal(useAppSessionStore.getState().status, 'required');
    });
}

test('upload permission failures and cancellations do not expire the app session', async () => {
    handler = () => json({ error: 'Forbidden', message: 'You cannot upload to this conversation.' }, 403);
    await assert.rejects(uploadFile('/upload', new FormData()),
        (error) => error.status === 403 && !isAppSessionError(error));
    assert.equal(useAppSessionStore.getState().status, 'ready');
    const controller = new AbortController();
    controller.abort();
    handler = () => Promise.reject(new DOMException('Cancelled', 'AbortError'));
    await assert.rejects(uploadFile('/upload', new FormData(), controller.signal),
        (error) => error.name === 'AbortError');
    assert.equal(requests.length, 2, 'neither denial nor cancellation starts a probe or replay');
    assert.equal(useAppSessionStore.getState().status, 'ready');
});

test('known expiry or an account switch blocks new writes until explicit recovery', async () => {
    useAppSessionStore.getState().requireSignIn(0);
    await assert.rejects(api.post('/save', {}), isAppSessionError);
    await assert.rejects(uploadFile('/upload', new FormData()), isAppSessionError);
    useAppSessionStore.setState({ status: 'changed' });
    await assert.rejects(api.post('/save', {}), (error) => error.payload.error === 'app_account_changed');
    assert.equal(requests.length, 0);
});

test('ambiguous upload failures share read-only verification without resending the file', async () => {
    handler = (path) => path === '/api/v2/bootstrap' ? expired() : Promise.reject(new TypeError('Failed to fetch'));
    await assert.rejects(uploadFile('/upload', new FormData()), isAppSessionError);
    assert.deepEqual(requests.map((item) => item.path), ['/upload', '/api/v2/bootstrap']);
});
