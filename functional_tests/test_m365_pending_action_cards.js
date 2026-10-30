// test_m365_pending_action_cards.js
// Version: 0.261.055
// Implemented in: 0.261.055
// Offline behavioral checks of the real shared renderer and M365 CSRF helper.
// Run: node --test functional_tests\test_m365_pending_action_cards.js

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const scriptRoot = path.resolve(__dirname, '..', 'application', 'single_app', 'static', 'js');
const csrfToken = 'test-only-anti-forgery-token-not-a-credential';

class Element {
    constructor(tagName, document) {
        this.tagName = tagName;
        this.ownerDocument = document;
        this.children = [];
        this.attributes = {};
        this.dataset = {};
        this.style = {};
        this.className = '';
        this.listeners = {};
        this.disabled = false;
        this.classList = {
            contains: name => this.className.split(/\s+/).includes(name),
            add: (...names) => { this.className = [...new Set([...this.className.split(/\s+/), ...names])].join(' ').trim(); },
            remove: (...names) => { this.className = this.className.split(/\s+/).filter(name => !names.includes(name)).join(' '); },
            toggle: (name, force) => {
                const add = force === undefined ? !this.classList.contains(name) : force;
                this.classList[add ? 'add' : 'remove'](name);
            },
        };
    }

    get textContent() { return (this.content || '') + this.children.map(node => node.textContent).join(''); }
    set textContent(value) { this.replaceChildren(); this.content = String(value); }
    set innerHTML(value) { throw new Error(`Unexpected HTML sink: ${value}`); }
    get isConnected() { return this === this.ownerDocument.body || Boolean(this.parentElement?.isConnected); }
    appendChild(node) {
        node.remove();
        node.parentElement = this;
        this.children.push(node);
        return node;
    }
    append(...nodes) { nodes.forEach(node => this.appendChild(node)); }
    replaceChildren(...nodes) {
        this.children.forEach(node => { node.parentElement = null; });
        this.children = [];
        this.content = '';
        this.append(...nodes);
    }
    remove() {
        if (this.parentElement) {
            this.parentElement.children = this.parentElement.children.filter(node => node !== this);
            this.parentElement = null;
        }
    }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) {
        if (name.startsWith('data-')) {
            return this.dataset[name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] ?? null;
        }
        return this.attributes[name] ?? null;
    }
    contains(node) { return node === this || this.children.some(child => child.contains(node)); }
    addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
    click() {
        if (!this.disabled) {
            this.listeners.click?.forEach(handler => handler({ target: this }));
        }
    }
    focus() { this.ownerDocument.activeElement = this; }
    matches(selector) {
        if (selector.startsWith('.')) {
            return this.classList.contains(selector.slice(1));
        }
        if (selector.startsWith('[')) {
            const match = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
            return match && (match[2] === undefined ? this.getAttribute(match[1]) !== null : this.getAttribute(match[1]) === match[2]);
        }
        return this.tagName === selector;
    }
    querySelectorAll(selector) {
        return this.children.flatMap(child => [
            ...(child.matches(selector) ? [child] : []),
            ...child.querySelectorAll(selector),
        ]);
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

function action(overrides = {}) {
    return {
        id: 'action-one', type: 'msgraph_pending_action', version: 'opaque-v1',
        operation: 'create_calendar_invite', graph_resource_type: 'calendar',
        viewer_is_owner: true, auth_required: false,
        status: 'pending', action_mode: 'manual', subject: 'Reviewed subject',
        summary: { attendee_recipients: ['person@example.test'], body_preview: '<b>Reviewed text</b>', content_type: 'html' },
        updated_at: '2026-09-19T20:00:00Z',
        can_send_now: true, can_approve: true, can_cancel: true, will_auto_send: false,
        ...overrides,
    };
}

function harness(initial = action()) {
    const document = {
        readyState: 'complete',
        createElement(tag) { return new Element(tag, this); },
        getElementById() { return null; },
    };
    document.body = document.createElement('body');
    const timers = new Map();
    const listeners = new Map();
    const calls = [];
    const server = { action: structuredClone(initial), mutationError: null, readError: null, networkFailure: false };
    const window = {
        location: { origin: 'https://simplechat.test' },
        setInterval(handler) { const id = Symbol('interval'); timers.set(id, handler); return id; },
        clearInterval(id) { timers.delete(id); },
        addEventListener(name, handler) {
            const handlers = listeners.get(name) || [];
            handlers.push(handler);
            listeners.set(name, handlers);
        },
        dispatchEvent(event) { listeners.get(event.type)?.forEach(handler => handler(event)); },
    };
    function response(payload, status = 200) {
        return {
            ok: status >= 200 && status < 300, status,
            headers: { get: () => 'application/json' },
            json: async () => structuredClone(payload),
        };
    }
    async function fetch(url, options = {}) {
        const method = options.method || 'GET';
        const body = options.body ? JSON.parse(options.body) : undefined;
        calls.push({ url, method, body, headers: options.headers });
        if (url === '/api/m365/preferences') {
            return response({ csrf_token: csrfToken });
        }
        if (method === 'GET') {
            if (server.readWait) {
                await server.readWait;
            }
            return server.readError ? response(server.readError.payload, server.readError.status)
                : response({ success: true, pending_action: server.action });
        }
        if (server.networkFailure) {
            throw new TypeError('Connection lost after request submission');
        }
        if (server.mutationError) {
            return response(server.mutationError.payload, server.mutationError.status);
        }
        server.action = {
            ...server.action, version: 'opaque-v2',
            status: url.endsWith('/cancel') ? 'cancelled' : 'sent',
            can_send_now: false, can_approve: false, can_cancel: false, will_auto_send: false,
            updated_at: '2026-09-19T20:01:00Z',
        };
        return response({ success: true, pending_action: server.action });
    }
    const context = vm.createContext({
        window, document, fetch, URL, URLSearchParams, AbortController, Date,
        CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    });
    for (const file of [path.join('chat', 'chat-m365-approvals.js'), 'm365-pending-actions.js']) {
        vm.runInContext(fs.readFileSync(path.join(scriptRoot, file), 'utf8'), context, { filename: file });
    }
    function mount(dto = initial, options = {}) {
        const root = document.createElement('section');
        document.body.appendChild(root);
        return window.SimpleChatM365PendingActions.mount(root, structuredClone(dto), options);
    }
    return { document, window, server, calls, timers, mount };
}

function button(view, label) {
    return view.card.querySelectorAll('button').find(node => node.textContent === label);
}

async function settle() {
    await new Promise(resolve => setImmediate(resolve));
    await new Promise(resolve => setImmediate(resolve));
}

test('rendering two instances sends nothing; one explicit versioned send updates both', async () => {
    const fixture = harness();
    const first = fixture.mount();
    const second = fixture.mount();
    assert.equal(fixture.calls.length, 0);
    button(first, 'Send').focus();
    button(first, 'Send').click();
    button(second, 'Send').click();
    await settle();
    const posts = fixture.calls.filter(call => call.method === 'POST');
    assert.equal(posts.length, 1);
    assert.equal(posts[0].url, '/api/msgraph/pending-actions/action-one/send-now');
    assert.deepEqual(posts[0].body, { expected_version: 'opaque-v1' });
    assert.equal(posts[0].headers['X-M365-CSRF-Token'], csrfToken);
    assert.match(first.card.textContent, /Sent — calendar invitation created/);
    assert.match(second.card.textContent, /Sent — calendar invitation created/);
    assert.equal(first.card.contains(fixture.document.activeElement), true);
    assert.equal(button(first, 'Send'), undefined);
    first.update(action());
    assert.equal(button(first, 'Send'), undefined, 'A replayed pre-send snapshot must not restore Send');
});

test('cancel uses the reviewed version and updates every rendered instance', async () => {
    const fixture = harness();
    const first = fixture.mount();
    const second = fixture.mount();
    button(first, 'Cancel').click();
    await settle();
    assert.match(first.card.textContent, /Cancelled/);
    assert.match(second.card.textContent, /Cancelled/);
    assert.deepEqual(fixture.calls.find(call => call.method === 'POST').body, { expected_version: 'opaque-v1' });
});

test('mail success reports acceptance, not recipient delivery, and retains the server draft note', async () => {
    const note = 'The frozen reviewed message was accepted for sending. The original Outlook draft was retained.';
    const fixture = harness(action({
        graph_resource_type: 'mail', operation: 'send_mail', delivery_note: note,
    }));
    const view = fixture.mount();
    button(view, 'Send').click();
    await settle();
    assert.match(view.card.textContent, /Accepted for sending — recipient delivery is not confirmed/);
    assert.ok(view.card.textContent.includes(note));
    assert.doesNotMatch(view.card.textContent, /delivery completed/);
    assert.equal(button(view, 'Send'), undefined);
    assert.equal(fixture.calls.filter(call => call.method === 'POST').length, 1);
});

test('delivery notes and errors both remain visible as text', () => {
    const note = 'The Outlook draft was not deleted. <img src=x onerror="globalThis.injected=true">';
    const fixture = harness(action({
        status: 'failed', error: 'Review the recorded outcome before retrying.', delivery_note: note,
    }));
    const view = fixture.mount();
    assert.ok(view.card.textContent.includes(note));
    assert.match(view.card.textContent, /Review the recorded outcome before retrying/);
    assert.equal(view.card.querySelectorAll('img').length, 0);
    assert.equal(button(view, 'Send'), undefined);
    assert.equal(fixture.calls.length, 0);
});

test('explicit full review GET updates every instance without a POST or invented version', async () => {
    const preview = action({
        review_details_required: true, can_send_now: false, can_approve: false,
        summary: { body_preview: 'Short preview', body_preview_truncated: true, body_length: 6000 },
    });
    const fixture = harness(preview);
    fixture.server.action = action({
        review_details_required: false,
        summary: { body_preview: 'Full reviewed material <b>as text</b>', body_preview_truncated: false, body_length: 6000 },
    });
    const first = fixture.mount();
    const second = fixture.mount();
    assert.equal(button(first, 'Send'), undefined);
    assert.equal(fixture.calls.length, 0);
    button(first, 'Review full invitation').click();
    await settle();
    assert.equal(fixture.calls.length, 1);
    assert.equal(fixture.calls[0].method, 'GET');
    assert.equal(fixture.calls[0].url, '/api/msgraph/pending-actions/action-one');
    for (const view of [first, second]) {
        assert.match(view.card.textContent, /Full reviewed material <b>as text<\/b>/);
        assert.equal(view.card.querySelector('details').open, true);
        assert.equal(button(view, 'Send').disabled, false);
        assert.equal(button(view, 'Review full invitation'), undefined);
    }
    button(first, 'Send').click();
    await settle();
    assert.deepEqual(fixture.calls.find(call => call.method === 'POST').body, { expected_version: 'opaque-v1' });
});

test('a same-version short projection rechecks full details without replaying a send', async () => {
    const preview = action({
        review_details_required: true, can_send_now: false, can_approve: false,
        summary: { body_preview: 'Short preview', body_preview_truncated: true },
    });
    const fixture = harness(preview);
    fixture.server.action = action({
        review_details_required: false,
        summary: { body_preview: 'Complete reviewed content', body_preview_truncated: false },
    });
    const view = fixture.mount();
    button(view, 'Review full invitation').click();
    await settle();
    view.update(preview);
    await settle();
    assert.match(view.card.textContent, /Complete reviewed content/);
    assert.equal(button(view, 'Send').disabled, false);
    assert.equal(fixture.calls.filter(call => call.method === 'POST').length, 0);
    const changed = {
        ...preview, version: 'opaque-v2', updated_at: '2026-09-19T20:01:00Z',
    };
    const reads = fixture.calls.length;
    view.update(changed);
    await settle();
    assert.equal(button(view, 'Send'), undefined);
    assert.equal(button(view, 'Review full invitation').disabled, false);
    assert.equal(fixture.calls.length, reads, 'Changed material needs a new explicit full review');
});

test('review flags fail closed even if a stale DTO also carries true send flags', () => {
    const fixture = harness(action({ review_details_required: true }));
    const view = fixture.mount();
    assert.equal(button(view, 'Send'), undefined);
    assert.equal(button(view, 'Review full invitation').disabled, false);
    assert.equal(button(view, 'Cancel').disabled, false);
    assert.equal(fixture.calls.length, 0);
});

test('full details never invent permissions missing from the fresh DTO', async () => {
    const fixture = harness(action({ review_details_required: true, can_send_now: false, can_approve: false }));
    const view = fixture.mount();
    fixture.server.action = action({
        review_details_required: false, can_send_now: false, can_approve: false, can_cancel: false,
    });
    button(view, 'Review full invitation').click();
    await settle();
    assert.equal(button(view, 'Send'), undefined);
    assert.equal(button(view, 'Cancel'), undefined);
    assert.equal(fixture.calls.filter(call => call.method === 'POST').length, 0);
});

test('a sharing-required Send uses refresh-only approval and requires a new click', async () => {
    const fixture = harness();
    const view = fixture.mount();
    fixture.server.mutationError = {
        status: 403, payload: { success: false, approval_required: true, approvals: [{ id: 'sharing' }] },
    };
    let reviews = 0;
    fixture.window.SimpleChatM365Approvals = {
        ...fixture.window.SimpleChatM365Approvals,
        async openApprovals(payload, options) {
            reviews += 1;
            assert.equal(payload.approvals[0].id, 'sharing');
            assert.equal(options.refreshOnly, true);
            assert.equal(options.onResume, undefined);
            await options.onRefresh();
            return { status: 'decided' };
        },
    };
    button(view, 'Send').click();
    await settle();
    assert.equal(reviews, 1);
    assert.equal(fixture.calls.filter(call => call.method === 'POST').length, 1);
    assert.match(view.card.textContent, /Sharing decisions saved/);
    assert.equal(button(view, 'Send').disabled, false);
    fixture.server.mutationError = null;
    button(view, 'Send').click();
    await settle();
    assert.equal(fixture.calls.filter(call => call.method === 'POST').length, 2);
});

test('shared viewers use conversation-authorized detail GETs and never gain owner controls', async () => {
    const fixture = harness(action({
        viewer_is_owner: false, conversation_id: 'shared conversation/?&', auth_required: true,
    }));
    const view = fixture.mount();
    assert.equal(button(view, 'Send'), undefined);
    assert.equal(button(view, 'Cancel'), undefined);
    assert.equal(button(view, 'Reconnect Microsoft 365'), undefined);
    button(view, 'Refresh status').click();
    await settle();
    assert.equal(fixture.calls.length, 1);
    const url = new URL(fixture.calls[0].url, fixture.window.location.origin);
    assert.equal(url.searchParams.get('conversation_id'), 'shared conversation/?&');
    assert.equal(fixture.calls[0].method, 'GET');
});

test('owner workflow detail GETs do not require access to their hidden output conversation', async () => {
    const fixture = harness(action({
        viewer_is_owner: true, workflow_id: 'workflow', conversation_id: 'hidden-output',
    }));
    const view = fixture.mount();
    button(view, 'Refresh status').click();
    await settle();
    assert.equal(fixture.calls[0].url, '/api/msgraph/pending-actions/action-one');
});

test('stored auth-required DTOs reconnect without a failed Send and ignore acknowledged revision echoes', async () => {
    const stored = action({ auth_required: true, sources: ['calendar'] });
    const fixture = harness(stored);
    let connections = 0;
    fixture.window.SimpleChatM365Connect = {
        async reconnectPendingAction() { connections += 1; },
    };
    const view = fixture.mount();
    assert.equal(button(view, 'Send').disabled, true);
    button(view, 'Reconnect Microsoft 365').click();
    await settle();
    assert.equal(connections, 1);
    assert.equal(button(view, 'Send').disabled, false);
    view.update(stored);
    assert.equal(button(view, 'Send').disabled, false);
    assert.equal(button(view, 'Reconnect Microsoft 365'), undefined);
    assert.equal(fixture.calls.filter(call => call.method === 'POST').length, 0);
    view.update({ ...stored, version: 'opaque-v2', updated_at: '2026-09-19T20:01:00Z' });
    assert.equal(button(view, 'Send').disabled, true);
    assert.equal(button(view, 'Reconnect Microsoft 365').disabled, false);
});

test('fresh auth failures invalidate a same-revision reconnect acknowledgement', async () => {
    const fixture = harness(action({ auth_required: true, sources: ['calendar'] }));
    fixture.window.SimpleChatM365Connect = { async reconnectPendingAction() {} };
    const view = fixture.mount();
    button(view, 'Reconnect Microsoft 365').click();
    await settle();
    fixture.server.mutationError = {
        status: 401, payload: { success: false, auth_required: true, sources: ['calendar'] },
    };
    button(view, 'Send').click();
    await settle();
    view.update(structuredClone(fixture.server.action));
    assert.equal(button(view, 'Send').disabled, true);
    assert.equal(button(view, 'Reconnect Microsoft 365').disabled, false);
    assert.equal(fixture.calls.filter(call => call.method === 'POST').length, 1);
});

test('a pending status read cannot swallow explicit reconnect completion', async () => {
    const fixture = harness(action({ auth_required: true, sources: ['calendar'] }));
    fixture.window.SimpleChatM365Connect = { async reconnectPendingAction() {} };
    const view = fixture.mount(undefined, { refreshOnFocus: true });
    let release;
    fixture.server.readWait = new Promise(resolve => { release = resolve; });
    fixture.window.dispatchEvent({ type: 'focus' });
    button(view, 'Reconnect Microsoft 365').click();
    await settle();
    release();
    await settle();
    assert.equal(button(view, 'Send').disabled, false);
    assert.equal(button(view, 'Reconnect Microsoft 365'), undefined);
    assert.equal(fixture.calls.filter(call => call.method === 'POST').length, 0);
});

for (const status of ['sending', 'sent', 'cancelled', 'failed', 'recovery_required', 'unexpected', '__proto__']) {
    test(`${status} cannot be made actionable by stale true flags`, () => {
        const fixture = harness(action({ status }));
        const view = fixture.mount();
        assert.equal(button(view, 'Send'), undefined);
        assert.equal(button(view, 'Cancel'), undefined);
        assert.equal(fixture.calls.length, 0);
        view.destroy();
        assert.equal(fixture.timers.size, 0);
    });
}

test('absent or nonboolean permission flags do not create controls', () => {
    const fixture = harness(action({ can_send_now: 'true', can_approve: undefined, can_cancel: 1 }));
    const view = fixture.mount();
    assert.equal(button(view, 'Send'), undefined);
    assert.equal(button(view, 'Cancel'), undefined);
    assert.match(view.card.textContent, /read-only/);
});

test('conversation startup action recovery stays in the background', () => {
    const source = fs.readFileSync(path.join(scriptRoot, 'm365-pending-actions.js'), 'utf8');
    assert.match(source, /async function load\(token = '', \{ background = false \} = \{\}\)/);
    assert.match(source, /void chat\.collection\.load\('', \{ background: true \}\);/);
    assert.match(source, /window\.addEventListener\('focus', \(\) => \{ void load\('', \{ background: true \}\); \}, \{ signal: lifecycle\.signal \}\)/);
    assert.match(source, /if \(!background && \(error\.status === 403 \|\| !chatView \|\| hasKnownActionState\)\)/);
});

test('legacy recreation never offers Send but preserves authorized cancellation', () => {
    const fixture = harness(action({ requires_recreation: true, requires_review: true }));
    const view = fixture.mount();
    assert.equal(button(view, 'Send'), undefined);
    assert.equal(button(view, 'Cancel').disabled, false);
    assert.match(view.card.textContent, /cannot be safely sent/);
});

test('missing record versions disable writes instead of inventing a version', () => {
    const fixture = harness(action({ version: undefined }));
    const view = fixture.mount();
    assert.equal(button(view, 'Send').disabled, true);
    assert.equal(button(view, 'Cancel').disabled, true);
});

test('network failures fetch current state and never replay a send', async () => {
    const fixture = harness();
    const view = fixture.mount();
    fixture.server.networkFailure = true;
    fixture.server.action = action({ status: 'recovery_required', version: 'opaque-v2' });
    button(view, 'Send').click();
    await settle();
    assert.equal(fixture.calls.filter(call => call.method === 'POST').length, 1);
    assert.equal(fixture.calls.filter(call => call.url === '/api/msgraph/pending-actions/action-one').length, 1);
    assert.match(view.card.textContent, /Delivery outcome needs recovery/);
    assert.equal(button(view, 'Send'), undefined);
});

test('failure to recover state keeps Send and Cancel disabled until an explicit refresh', async () => {
    const fixture = harness();
    const view = fixture.mount();
    fixture.server.networkFailure = true;
    fixture.server.readError = { status: 503, payload: { success: false, error: 'storage_unavailable' } };
    button(view, 'Send').click();
    await settle();
    assert.equal(button(view, 'Send').disabled, true);
    assert.equal(button(view, 'Cancel').disabled, true);
    fixture.server.readError = null;
    button(view, 'Refresh status').click();
    await settle();
    assert.equal(button(view, 'Send').disabled, false);
    assert.equal(fixture.calls.filter(call => call.method === 'POST').length, 1);
});

test('stale conflicts display fresh data and require another user click', async () => {
    const fixture = harness();
    const view = fixture.mount();
    fixture.server.mutationError = {
        status: 409,
        payload: { success: false, error: 'pending_action_changed', pending_action: action({ version: 'opaque-v2', subject: 'Changed subject' }) },
    };
    button(view, 'Send').click();
    await settle();
    assert.match(view.card.textContent, /Changed subject/);
    assert.match(view.card.textContent, /This action changed/);
    assert.equal(button(view, 'Send').disabled, false);
    assert.equal(fixture.calls.filter(call => call.method === 'POST').length, 1);
});

test('expired Graph auth does not prevent an explicitly authorized cancel', async () => {
    const fixture = harness();
    const view = fixture.mount();
    fixture.server.mutationError = { status: 401, payload: { success: false, auth_required: true, sources: ['calendar'] } };
    button(view, 'Send').click();
    await settle();
    assert.equal(button(view, 'Send').disabled, true);
    assert.equal(button(view, 'Cancel').disabled, false);
    fixture.server.mutationError = null;
    button(view, 'Cancel').click();
    await settle();
    assert.match(view.card.textContent, /Cancelled/);
    assert.equal(fixture.calls.filter(call => call.method === 'POST').length, 2);
});

test('an overdue countdown refreshes only and its timer is removed on teardown', async () => {
    const fixture = harness(action({
        status: 'scheduled', action_mode: 'delayed', will_auto_send: true,
        auto_send_at_utc: '2020-01-01T00:00:00Z',
    }));
    const view = fixture.mount();
    assert.equal(fixture.calls.length, 0);
    Array.from(fixture.timers.values()).forEach(tick => tick());
    await settle();
    assert.equal(fixture.calls.length, 1);
    assert.equal(fixture.calls[0].method, 'GET');
    assert.match(view.card.textContent, /Scheduled time reached/);
    view.destroy();
    assert.equal(fixture.timers.size, 0);
});

test('untrusted values remain text and only credential-free HTTPS links are clickable', () => {
    const attack = '<img src=x onerror="globalThis.injected=true">';
    const fixture = harness(action({
        subject: attack,
        web_link: 'javascript:globalThis.injected=true', // xss-check: ignore - Negative fixture; no link may be rendered.
        error: attack,
    }));
    const view = fixture.mount();
    assert.match(view.card.textContent, /<img src=x onerror=/);
    assert.equal(view.card.querySelectorAll('img').length, 0);
    assert.equal(view.card.querySelectorAll('a').length, 0);
    view.update(action({ web_link: 'https://user:password@example.test/action' }));
    assert.equal(view.card.querySelectorAll('a').length, 0);
    view.update(action({ web_link: 'https://outlook.office365.us/calendar/item' }));
    const link = view.card.querySelector('a');
    assert.equal(link.href, 'https://outlook.office365.us/calendar/item');
    assert.equal(link.rel, 'noopener noreferrer');
});

test('the shared CSRF helper permits only the specific same-origin pending-action API extension', async () => {
    const fixture = harness();
    const api = fixture.window.SimpleChatM365Approvals;
    await assert.rejects(api.requestJson('https://another.example/api/msgraph/pending-actions'), /local authenticated API/);
    await assert.rejects(api.requestJson('/api/msgraph/test-access', { method: 'POST', body: {} }), /local authenticated API/);
    assert.equal(fixture.calls.length, 0);
    await api.requestJson('/api/msgraph/pending-actions/action-one');
    assert.equal(fixture.calls.length, 1);
});
