// test_classic_action_auth.mjs
/**
 * Functional regressions for private classic action authentication.
 * Version: 0.261.107
 * Implemented in: 0.261.107
 *
 * Run: node --test functional_tests\test_classic_action_auth.mjs
 * Uses the real local modules and Node's built-in test runner; no test dependencies.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import {
    ActionAuthController, actionAuthProfiles, buildActionAuthContext, cancelActionAuthRequest,
    getGlobalActionAuthReference, isActionCredentialsRequired, validateActionAuthRequirement,
} from '../application/single_app/static/js/chat/chat-action-auth.js';

test('failed server cancellation is reported without exposing response details', async context => {
    const warning = context.mock.method(console, 'warn', () => {});
    assert.equal(await cancelActionAuthRequest('request', async () => ({ ok: false, status: 503 })), false);
    assert.equal(warning.mock.callCount(), 1);
    assert.match(warning.mock.calls[0].arguments[0], /will expire/);
    assert.equal(await cancelActionAuthRequest('request', async () => ({ ok: false, status: 410 })), true);
    assert.equal(warning.mock.callCount(), 1);
});

class Element {
    constructor(tag, ownerDocument) {
        this.tagName = tag.toUpperCase();
        this.ownerDocument = ownerDocument;
        this.children = [];
        this.parentElement = null;
        this.attributes = {};
        this.listeners = {};
        this.dataset = {};
        this.className = '';
        this.style = {};
        this.checked = false;
        this.disabled = false;
        this.required = false;
        this._value = undefined;
        this._text = '';
        this.classList = {
            contains: name => this.className.split(' ').includes(name),
            add: (...names) => { this.className = [...new Set([...this.className.split(' ').filter(Boolean), ...names])].join(' '); },
            remove: (...names) => { this.className = this.className.split(' ').filter(name => !names.includes(name)).join(' '); },
            toggle: (name, force) => {
                const enabled = force ?? !this.classList.contains(name);
                this.classList[enabled ? 'add' : 'remove'](name);
                return enabled;
            },
        };
    }
    get value() { return this._value ?? (this.tagName === 'SELECT' ? this.children[0]?.value || '' : ''); }
    set value(value) { this._value = String(value); }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
    set textContent(value) { this._text = String(value); this.replaceChildren(); }
    set innerHTML(_value) { throw new Error('An unsafe HTML sink was used.'); }
    get isConnected() { return this.ownerDocument.body.contains(this); }
    setAttribute(name, value) {
        this.attributes[name] = String(value);
        if (name === 'id') this.id = value;
    }
    removeAttribute(name) { delete this.attributes[name]; }
    append(...children) {
        children.forEach(child => {
            child.parentElement = this;
            this.children.push(child);
        });
    }
    appendChild(child) { this.append(child); return child; }
    replaceChildren(...children) {
        this.children.forEach(child => { child.parentElement = null; });
        this.children = [];
        this.append(...children);
    }
    remove() {
        if (this.parentElement) {
            this.parentElement.children = this.parentElement.children.filter(child => child !== this);
            this.parentElement = null;
        }
    }
    contains(element) { return element === this || this.children.some(child => child.contains(element)); }
    querySelectorAll(selector) {
        const matches = element => selector.startsWith('[')
            ? Object.hasOwn(element.attributes, selector.slice(1, -1))
            : selector.startsWith('#') ? element.id === selector.slice(1)
                : element.tagName.toLowerCase() === selector;
        return this.children.flatMap(child => [...(matches(child) ? [child] : []), ...child.querySelectorAll(selector)]);
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
    removeEventListener(name, callback) { this.listeners[name] = (this.listeners[name] || []).filter(listener => listener !== callback); }
    async fire(name) {
        const event = { target: this, preventDefault() {} };
        await Promise.all((this.listeners[name] || []).map(callback => callback(event)));
    }
    focus() { this.ownerDocument.activeElement = this; }
    reportValidity() {
        if (this.disabled) return true;
        if (this.required && !(this.type === 'checkbox' ? this.checked : this.value)) return false;
        return this.children.every(child => child.reportValidity());
    }
}

class Document {
    constructor() {
        this.body = new Element('body', this);
        this.listeners = {};
    }
    createElement(tag) { return new Element(tag, this); }
    getElementById(id) { return this.body.querySelector(`#${id}`); }
    querySelectorAll(selector) { return this.body.querySelectorAll(selector); }
    addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
    removeEventListener(name, callback) { this.listeners[name] = (this.listeners[name] || []).filter(listener => listener !== callback); }
    field(id, value = '', tag = 'input') {
        const element = this.createElement(tag);
        element.id = id;
        element.value = value;
        this.body.appendChild(element);
        return element;
    }
}

function environment() {
    const document = new Document();
    const listeners = {};
    const window = {
        location: new URL('https://simplechat.test/chats'),
        currentConversationId: 'conversation',
        addEventListener: (name, callback) => { (listeners[name] ||= []).push(callback); },
        removeEventListener: (name, callback) => { listeners[name] = (listeners[name] || []).filter(listener => listener !== callback); },
        fire: name => (listeners[name] || []).forEach(callback => callback()),
        dispatchEvent() {},
    };
    const storage = new Proxy({}, { get() { throw new Error('Private authentication accessed browser storage.'); } });
    window.localStorage = storage;
    window.sessionStorage = storage;
    globalThis.window = window;
    globalThis.document = document;
    globalThis.localStorage = storage;
    globalThis.sessionStorage = storage;
    const root = document.field('chat-action-auth-root', '', 'div');
    root.classList.add('d-none');
    root.dataset.identitySetupUrl = '/workspace?tab=identities';
    const composer = document.field('user-input', 'Unsent request', 'textarea');
    composer.focus();
    const chatbox = document.field('chatbox', '', 'div');
    return { document, window, root, composer, chatbox };
}

function requirement(profile = 'yamcs_login', overrides = {}) {
    const authType = actionAuthProfiles[profile]?.authType || 'unknown';
    return {
        id: 'requirement-1', action_id: 'global-yamcs', action_name: 'Mission telemetry',
        identity_name: 'Yamcs', profile, auth_type: authType, destination: 'https://yamcs.example.test/api',
        reason: 'missing', identities: [],
        fields: authType === 'username_password'
            ? [{ name: 'username', label: 'Username', type: 'text', required: true }, { name: 'password', label: 'Password', type: 'password', required: true }]
            : [{ name: 'secret', label: 'Token', type: 'password', required: true }],
        ...overrides,
    };
}

const missing = (requirements = [requirement()], shared = false) => ({
    status: 'credentials_required', request_id: 'private-request', requirements,
    uses_personal_credentials: true, shared_conversation: shared,
});
const ready = (shared = false) => ({ ...missing([], shared), status: 'ready' });
const tick = () => new Promise(resolve => setImmediate(resolve));
const response = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => structuredClone(data) });

function setup(initial = missing(), saveResult = ready()) {
    const env = environment();
    const requests = [];
    const controller = new ActionAuthController({
        root: env.root, ownerDocument: env.document,
        fetchImpl: async (url, options) => {
            requests.push({ url, options: { ...options, signal: undefined }, body: options.body ? JSON.parse(options.body) : null });
            if (url.endsWith('/credentials')) return response(saveResult);
            if (url.endsWith('/cancel')) return response({ status: 'cancelled' });
            return response(url.endsWith('/preflight') ? initial : ready(initial.shared_conversation));
        },
    });
    return { ...env, requests, controller };
}

test('preflight contains selection metadata, never draft, actor overrides, files, or credentials', () => {
    environment();
    const context = buildActionAuthContext({
        message: 'private draft', credentials: { password: 'sentinel' }, user_id: 'someone-else',
        agent_info: { id: 'agent', name: 'Agent', is_global: true, password: 'sentinel', user_id: 'other' },
        conversation_id: 'shared', conversation_kind: 'collaboration', history: ['private draft'],
    });
    assert.deepEqual(context, {
        conversation_id: 'shared', conversation_kind: 'collaboration',
        agent_info: { id: 'agent', name: 'Agent', is_global: true },
    });
    const actionRef = getGlobalActionAuthReference({ id: 'global-yamcs' });
    assert.equal(actionRef, 'action:v1:global:Z2xvYmFs:Z2xvYmFsLXlhbWNz');
    const unicodeId = 'télémétrie-🛰️';
    assert.equal(getGlobalActionAuthReference({ id: unicodeId, name: 'not-an-identity' }),
        `action:v1:global:Z2xvYmFs:${Buffer.from(unicodeId, 'utf8').toString('base64url')}`);
    assert.equal(getGlobalActionAuthReference({ name: 'action-name-without-stable-id' }), null);
    assert.equal(buildActionAuthContext({ action_ref: actionRef }).action_ref, actionRef);
    assert.equal(buildActionAuthContext({ run_id: 'executable-run', answers: { password: 'sentinel' } }).run_id, 'executable-run');
});

test('all registered profiles are bounded and unsupported fields fail closed', () => {
    for (const profile of Object.keys(actionAuthProfiles)) {
        assert.equal(validateActionAuthRequirement(requirement(profile)).profile, actionAuthProfiles[profile]);
    }
    assert.throws(() => validateActionAuthRequirement(requirement('yamcs_login', {
        fields: [...requirement().fields, { name: 'model_defined', type: 'text', required: true }],
    })), /unsupported credential fields/);
    for (const destination of ['http://yamcs.test', 'https://user:pass@yamcs.test', 'https://yamcs.test/?credential=x', 'javascript:alert(1)']) {
        assert.throws(() => validateActionAuthRequirement(requirement('api_key', { destination })));
    }
});

test('private DOM saves once despite double submit and secrets go only to the dedicated endpoint', async () => {
    const env = setup();
    let executions = 0;
    const pending = env.controller.authorize({ agent_info: { id: 'agent' }, message: env.composer.value })
        .then(receipt => { if (receipt) executions += 1; return receipt; });
    await tick();
    assert.equal(env.chatbox.children.length, 0);
    assert.match(env.root.textContent, /Private to you/);
    const username = env.document.getElementById('action-auth-username');
    const password = env.document.getElementById('action-auth-password');
    username.value = 'synthetic-operator';
    password.value = 'SYNTHETIC-PRIVATE-PASSWORD';
    assert.equal(password.type, 'password');
    assert.equal(password.attributes.value, undefined);
    env.document.getElementById('action-auth-destination').checked = true;
    const form = env.root.querySelector('form');
    await Promise.all([form.fire('submit'), form.fire('submit')]);
    assert.equal((await pending).action_auth_request_id, 'private-request');
    assert.equal(executions, 1);
    assert.equal(password.value, '');
    assert.equal(username.value, '');
    assert.equal(env.composer.value, 'Unsent request');
    assert.equal(env.chatbox.children.length, 0);
    const saves = env.requests.filter(request => request.url.endsWith('/credentials'));
    assert.equal(saves.length, 1);
    assert.deepEqual(saves[0].body, {
        requirement_id: 'requirement-1', confirm_destination: true,
        credentials: { username: 'synthetic-operator', password: 'SYNTHETIC-PRIVATE-PASSWORD' },
    });
    assert.equal(JSON.stringify(env.requests.filter(request => !request.url.endsWith('/credentials'))).includes('SYNTHETIC-PRIVATE'), false);
    env.controller.destroy();
});

test('cancel and navigation wipe form values, preserve the unsent draft, and cannot resume old work', async () => {
    for (const navigation of [false, true]) {
        const env = setup();
        const pending = env.controller.authorize({ agent_info: { id: 'agent' } });
        await tick();
        const input = env.document.getElementById('action-auth-password');
        input.value = 'SYNTHETIC-CANCELLED';
        if (navigation) env.window.fire('pagehide'); else env.controller.cancel();
        assert.equal(await pending, null);
        assert.equal(input.value, '');
        assert.equal(env.composer.value, 'Unsent request');
        assert.equal(env.root.children.length, 0);
        assert.equal(env.requests.filter(request => request.url.endsWith('/credentials')).length, 0);
        assert.equal(env.requests.filter(request => request.url.endsWith('/cancel')).length, 1);
        env.controller.destroy();
    }
});

test('existing owned identity requires explicit selection and destination consent without sending stored secrets', async () => {
    const env = setup(missing([requirement('http_basic', {
        reason: 'ambiguous', identities: [
            { id: 'owned-1', name: 'My gateway account', auth_type: 'username_password' },
            { id: 'owned-2', name: 'Other account', auth_type: 'username_password' },
        ],
    })]));
    const pending = env.controller.authorize({ agent_info: { name: 'agent' } });
    await tick();
    const selector = env.document.getElementById('action-auth-identity');
    assert.equal(selector.value, '');
    assert.match(env.root.textContent, /Gateway HTTP Basic \(not Yamcs login\)/);
    selector.value = 'owned-1';
    await selector.fire('change');
    const form = env.root.querySelector('form');
    await form.fire('submit');
    assert.equal(env.requests.length, 1);
    env.document.getElementById('action-auth-destination').checked = true;
    await form.fire('submit');
    await pending;
    assert.deepEqual(env.requests[1].body, { requirement_id: 'requirement-1', identity_id: 'owned-1', confirm_destination: true });
    env.controller.destroy();
});

test('ready shared credentials still require the posting-data notice before execution', async () => {
    const env = setup(ready(true));
    let resumed = false;
    const pending = env.controller.authorize({ agent_info: { id: 'agent' }, conversation_kind: 'collaboration' })
        .then(receipt => { resumed = Boolean(receipt); });
    await tick();
    assert.equal(resumed, false);
    assert.match(env.root.textContent, /message and returned data will be visible/);
    const button = env.root.querySelectorAll('button').find(element => element.textContent === 'Continue with my account');
    await button.fire('click');
    assert.equal(resumed, false);
    env.document.getElementById('action-auth-sharing').checked = true;
    await button.fire('click');
    await pending;
    assert.equal(resumed, true);
    env.controller.destroy();
});

test('runtime repair never continues or replays a started turn', async () => {
    for (const executionStarted of [true, false]) {
        const env = setup();
        const pending = env.controller.repair({
            error_code: 'action_credentials_required', request_id: 'private-request', execution_started: executionStarted,
        });
        await tick();
        assert.match(env.root.textContent, /no turn has been replayed/);
        assert.equal(env.root.textContent.includes('earlier tool work may already have run'), executionStarted);
        assert.equal(env.requests[0].options.method, 'GET');
        await env.root.querySelectorAll('button').find(button => button.textContent === 'Done').fire('click');
        assert.equal(await pending, null);
        env.controller.destroy();
    }
    assert.equal(isActionCredentialsRequired({ streamErrorData: { error_code: 'action_credentials_required' } }), true);
    assert.equal(isActionCredentialsRequired({ type: 'action_credentials_required', execution_started: true }), true);
    assert.equal(isActionCredentialsRequired({ auth_required: true, auth_url: '/foundry' }), false);
});

test('runtime repair uses the failed action instead of a consumed executable plan', async () => {
    const env = setup(ready());
    const actionRef = 'action:v1:global:Z2xvYmFs:eWFtY3M';
    const pending = env.controller.repair({
        error_code: 'action_credentials_required', request_id: 'consumed-request',
        execution_started: true, action_ref: actionRef,
    }, {
        payload: { run_id: 'started-run', agent_info: { id: 'root-agent' }, conversation_id: 'conversation' },
    });
    await tick();
    assert.equal(env.requests[0].url, '/api/action-auth/preflight');
    assert.equal(env.requests[0].body.action_ref, actionRef);
    assert.equal('run_id' in env.requests[0].body, false);
    assert.equal('agent_info' in env.requests[0].body, false);
    await env.root.querySelectorAll('button').find(button => button.textContent === 'Done').fire('click');
    assert.equal(await pending, null);
    env.controller.destroy();
});

test('confirmed authentication rejection requires replacement credentials and never replays a begun turn', async () => {
    const rejected = missing([requirement('http_basic', {
        reason: 'authentication_rejected',
        identities: [{ id: 'rejected-owned-identity', name: 'My gateway identity', auth_type: 'username_password' }],
    })]);
    const env = setup(rejected);
    const requests = [];
    env.controller.fetchImpl = async (url, options) => {
        requests.push({ url, body: options.body ? JSON.parse(options.body) : null });
        return response(url.endsWith('/credentials') ? ready() : rejected);
    };
    const pending = env.controller.repair({
        type: 'action_credentials_required', request_id: 'private-request', execution_started: true,
    });
    await tick();
    assert.match(env.root.textContent, /Yamcs rejected the saved credentials/);
    const selector = env.document.getElementById('action-auth-identity');
    assert.equal(selector.value, '');
    selector.value = 'rejected-owned-identity';
    await selector.fire('change');
    const replace = env.document.getElementById('action-auth-replace');
    assert.equal(replace.checked, true);
    assert.equal(replace.disabled, true);
    assert.equal(env.document.getElementById('action-auth-password').disabled, false);
    env.document.getElementById('action-auth-destination').checked = true;
    const form = env.root.querySelector('form');
    await form.fire('submit');
    assert.equal(requests.length, 1);
    env.document.getElementById('action-auth-username').value = 'replacement-user';
    env.document.getElementById('action-auth-password').value = 'SYNTHETIC-REPLACEMENT';
    await form.fire('submit');
    assert.equal(requests.length, 2);
    assert.deepEqual(requests[1].body, {
        requirement_id: 'requirement-1', identity_id: 'rejected-owned-identity', confirm_destination: true,
        credentials: { username: 'replacement-user', password: 'SYNTHETIC-REPLACEMENT' },
    });
    assert.match(env.root.textContent, /Use Retry or submit your draft/);
    assert.equal(env.composer.value, 'Unsent request');
    assert.equal(env.chatbox.children.length, 0);
    await env.root.querySelectorAll('button').find(button => button.textContent === 'Done').fire('click');
    assert.equal(await pending, null);
    env.controller.destroy();
});

test('global save awaits the admin list refresh to obtain server-assigned action and requirement IDs', async () => {
    const source = readFileSync(new URL('../application/single_app/static/js/admin/admin_plugins.js', import.meta.url), 'utf8');
    const body = source.slice(source.indexOf('function setupSaveHandler('), source.indexOf('\nasync function savePlugin('));
    const draft = {
        name: 'mission', type: 'yamcs', auth: { type: 'username_password' },
        credential_requirement: { source: 'current_user', identity_name: 'Yamcs', profile: 'yamcs_login' },
    };
    const events = [];
    let listener;
    let saved;
    let cached;
    let finishRefresh;
    const boundSave = {
        disabled: false, textContent: 'Save Action',
        addEventListener: (_name, handler) => { listener = handler; },
        replaceChildren() {},
    };
    const scope = {
        console,
        document: {
            getElementById: id => id === 'save-plugin-btn' ? { cloneNode: () => boundSave, replaceWith() {} } : null,
            createElement: () => ({ setAttribute() {} }),
            createTextNode: value => value,
        },
        window: { pluginModalStepper: { getFormData: () => structuredClone(draft), showError: message => assert.fail(message) } },
        sharedValidatePluginManifest: async () => ({ valid: true }),
        savePlugin: async data => {
            events.push('save');
            assert.equal(data.credential_requirement.id, undefined);
            saved = { ...data, id: 'saved-action-id', credential_requirement: { ...data.credential_requirement, id: 'saved-requirement-id' } };
            return { success: true };
        },
        loadPlugins: () => new Promise(resolve => {
            events.push('refresh');
            finishRefresh = () => { cached = saved; events.push('refreshed'); resolve(); };
        }),
        showToast: () => events.push('success'),
    };
    vm.createContext(scope);
    vm.runInContext(`${body}\nglobalThis.bind = setupSaveHandler;`, scope);
    scope.bind(null, { hide: () => events.push('hide') });
    let complete = false;
    const pending = listener({ preventDefault() {} }).then(() => { complete = true; });
    await tick();
    assert.equal(complete, false);
    assert.deepEqual(events, ['save', 'hide', 'refresh']);
    finishRefresh();
    await pending;
    assert.equal(cached.id, 'saved-action-id');
    assert.equal(cached.credential_requirement.id, 'saved-requirement-id');
    assert.deepEqual(events, ['save', 'hide', 'refresh', 'refreshed', 'success']);
});

test('stale selection and late responses cannot resume or cancel a newer draft', async () => {
    const env = setup();
    let current = true;
    const pending = env.controller.authorize({ agent_info: { id: 'agent' } }, { isCurrent: () => current });
    await tick();
    const old = env.controller.active;
    current = false;
    env.controller.acceptState(old, ready());
    assert.equal(await pending, null);
    const fresh = env.controller.authorize({ agent_info: { id: 'different-agent' } });
    await tick();
    env.controller.acceptState(old, ready());
    assert.notEqual(env.controller.active, null);
    env.controller.cancel();
    assert.equal(await fresh, null);
    env.controller.destroy();
});

test('model-only sends do not call preflight and no workspace link appears when disabled', async () => {
    const env = setup();
    assert.deepEqual(await env.controller.authorize({ message: 'ordinary chat' }), {});
    assert.equal(env.requests.length, 0);
    delete env.root.dataset.identitySetupUrl;
    const pending = env.controller.authorize({ agent_info: { id: 'agent' } });
    await tick();
    assert.equal(env.root.querySelectorAll('a').length, 0);
    env.controller.cancel();
    await pending;
    env.controller.destroy();
});

function editor() {
    const env = environment();
    const file = new URL('../application/single_app/static/js/plugin_modal_stepper.js', import.meta.url);
    const source = readFileSync(file, 'utf8').replace(/^import .*;\r?\n/gm, '').replace('export class PluginModalStepper', 'class PluginModalStepper');
    const scope = {
        document: env.document, window: env.window, console, URL, actionAuthProfiles,
        ActionAuthController, getGlobalActionAuthReference, isActionCredentialsRequired,
    };
    const Stepper = vm.runInNewContext(`${source}\nPluginModalStepper;`, scope);
    const stepper = Object.create(Stepper.prototype);
    Object.assign(stepper, {
        selectedType: 'yamcs', actionIdentityScope: { scope: 'global', allowCurrentUser: true },
        actionIdentities: [], isEditMode: false, originalPlugin: null,
    });
    const values = {
        'yamcs-server-url': 'https://yamcs.example.test', 'yamcs-instance': 'simulator',
        'yamcs-processor': 'realtime', 'yamcs-max-rows': '500', 'yamcs-timeout': '30',
        'yamcs-credential-source': 'current_user', 'yamcs-identity-name': 'Yamcs',
        'yamcs-auth-profile': 'yamcs_login', 'yamcs-auth-method': 'username_password',
        'yamcs-username': '', 'yamcs-password': '', 'yamcs-api-key': '', 'yamcs-bearer-token': '',
        'yamcs-identity-select': '', 'yamcs-tls-verify': '', 'yamcs-enable-archive-sql': '',
        'plugin-name': 'mission', 'plugin-display-name': 'Mission', 'plugin-description': 'Read telemetry', 'plugin-metadata': '{}',
    };
    for (const [id, value] of Object.entries(values)) env.document.field(id, value);
    env.document.getElementById('yamcs-tls-verify').checked = true;
    for (const kind of ['openapi', 'sql', 'cosmos', 'rocksdb', 'document-search', 'blob-storage', 'databricks', 'snowflake', 'tableau', 'yamcs', 'mcp', 'azure-maps', 'log-analytics']) {
        const section = env.document.field(`${kind}-config-section`, '', 'section');
        if (kind !== 'yamcs') section.classList.add('d-none');
    }
    return { ...env, stepper };
}

test('global authoring round trips all protocols without credential values or user-specific references', () => {
    const env = editor();
    for (const [profile, definition] of Object.entries(actionAuthProfiles)) {
        env.document.getElementById('yamcs-auth-profile').value = profile;
        const data = env.stepper.getFormData();
        assert.equal(data.auth.type, definition.nativeType);
        assert.equal(data.additionalFields.auth_method, definition.method);
        assert.equal(data.credential_requirement.profile, profile);
        assert.equal(data.credential_requirement.source, 'current_user');
        assert.equal('id' in data.credential_requirement, false);
        assert.equal('identity_id' in data, false);
        assert.deepEqual(Object.keys(data.auth), ['type']);
    }
});

test('label edits retain server IDs, source switches clear inline values, and personal/group remain legacy', () => {
    const env = editor();
    env.stepper.originalPlugin = {
        credential_requirement: { id: 'server-stable-id', source: 'current_user', identity_name: 'Yamcs', profile: 'yamcs_login' },
        additionalFields: { hidden_setting: 'retained', username: 'STALE-USER', password: 'STALE-SECRET', identity_id: 'stale-global-reference' },
    };
    env.stepper.isEditMode = true;
    env.document.getElementById('yamcs-identity-name').value = 'Mission account';
    env.document.getElementById('yamcs-password').value = 'STALE-INLINE';
    env.document.getElementById('yamcs-identity-select').value = 'stale-global-reference';
    env.stepper.handleYamcsCredentialSourceChange();
    const data = env.stepper.getFormData();
    assert.equal(data.credential_requirement.id, 'server-stable-id');
    assert.equal(data.credential_requirement.identity_name, 'Mission account');
    assert.equal(data.additionalFields.hidden_setting, 'retained');
    assert.equal(JSON.stringify(data).includes('STALE'), false);
    assert.equal(env.document.getElementById('yamcs-password').value, '');
    for (const scope of ['personal', 'group']) {
        env.stepper.actionIdentityScope = { scope };
        assert.equal(env.stepper.canConfigureYamcsCurrentUser(), false);
        assert.equal(env.stepper.getYamcsCredentialRequirement(), null);
    }
});

test('actual send, voice, and collaboration defer all optimistic changes until preflight and clear only on acceptance', async () => {
    const source = readFileSync(new URL('../application/single_app/static/js/chat/chat-messages.js', import.meta.url), 'utf8');
    const body = source.slice(source.indexOf('export async function actuallySendMessage('), source.indexOf('\nfunction attachCodeBlockCopyButtons('))
        .replace('export async function', 'async function');
    for (const shared of [false, true]) {
        const env = environment();
        const sent = [];
        const appended = [];
        let approve;
        const payload = () => ({ message: 'Unsent request', conversation_id: 'conversation', agent_info: { id: 'mission-agent' } });
        const scope = {
            ...env, console, currentConversationId: 'conversation', userInput: env.composer, promptSelect: { selectedIndex: 0 },
            actionAuthSendPending: false, actionAuthSendSequence: 0, DOCUMENT_ACTION_NONE: 'none', DOCUMENT_ACTION_ANALYZE: 'analyze', DOCUMENT_ACTION_COMPARISON: 'comparison',
            buildChatRequestPayload: payload,
            buildCollaborativeSendContext: () => ({ messageData: payload(), invocationTarget: { target_type: 'agent' }, displayMessageText: 'Unsent request' }),
            buildVoiceResponseCompletionHandler: () => () => {},
            prepareActionAuthExecution: data => new Promise(resolve => {
                approve = () => { data.action_auth_request_id = 'private-request'; resolve(true); };
            }),
            appendMessage: (...args) => appended.push(args),
            sendMessageWithStreaming: (data, _temp, _id, options) => { sent.push({ data, options }); return true; },
            shouldUseCollaborativeAiWorkflow: () => true, updateSendButtonVisibility() {}, showToast() {},
            getConversationTaskDocumentSummary: () => ({ readyCount: 0, totalCount: 0 }),
            getDocumentActionMaxDocuments: () => 10,
        };
        env.window.chatCollaboration = {
            isCollaborationConversation: () => shared,
            getPendingMessageContext: () => ({}),
            sendCollaborativeAiMessage: (_text, _temp, data, _context, options) => { sent.push({ data, options }); return true; },
        };
        vm.createContext(scope);
        vm.runInContext(`${body}\nglobalThis.send = actuallySendMessage;`, scope);
        const pending = scope.send('Unsent request', { inputModality: 'voice', responseModality: 'voice' });
        await tick();
        assert.equal(appended.length, 0);
        assert.equal(sent.length, 0);
        assert.equal(env.composer.value, 'Unsent request');
        assert.equal(await scope.send('Unsent request'), false);
        approve();
        assert.equal(await pending, true);
        assert.equal(sent.length, 1);
        assert.equal(sent[0].data.action_auth_request_id, 'private-request');
        assert.equal(sent[0].data.input_modality, 'voice');
        assert.equal(env.composer.value, 'Unsent request');
        sent[0].options.onAccepted();
        assert.equal(env.composer.value, '');
        env.composer.value = 'Next draft';
        sent[0].options.onDone({});
        assert.equal(env.composer.value, 'Next draft');
    }
});

test('a new conversation receives a fresh scoped receipt after private setup, before any message append', async () => {
    const source = readFileSync(new URL('../application/single_app/static/js/chat/chat-messages.js', import.meta.url), 'utf8');
    const body = source.slice(source.indexOf('export async function actuallySendMessage('), source.indexOf('\nfunction attachCodeBlockCopyButtons('))
        .replace('export async function', 'async function');
    const env = environment();
    env.window.currentConversationId = null;
    const operations = [];
    const scope = {
        ...env, console, currentConversationId: null, userInput: env.composer, promptSelect: { selectedIndex: 0 },
        actionAuthSendPending: false, actionAuthSendSequence: 0,
        DOCUMENT_ACTION_NONE: 'none', DOCUMENT_ACTION_ANALYZE: 'analyze', DOCUMENT_ACTION_COMPARISON: 'comparison',
        buildChatRequestPayload: () => ({ message: 'Unsent request', conversation_id: scope.currentConversationId, agent_info: { id: 'agent' } }),
        buildVoiceResponseCompletionHandler: () => null,
        prepareActionAuthExecution: async payload => {
            operations.push(['preflight', payload.conversation_id]);
            payload.action_auth_request_id = payload.conversation_id ? 'scoped-request' : 'draft-request';
            return true;
        },
        createNewConversation: async () => {
            operations.push(['create']);
            scope.currentConversationId = 'new-conversation';
            env.window.currentConversationId = 'new-conversation';
            return { conversation_id: 'new-conversation' };
        },
        cancelActionAuthRequest: requestId => cancelActionAuthRequest(requestId, scope.fetch),
        fetch: async url => { operations.push(['cancel', url]); return response({}); },
        appendMessage: () => operations.push(['append']),
        sendMessageWithStreaming: payload => { operations.push(['send', payload.action_auth_request_id, payload.conversation_id]); },
        updateSendButtonVisibility() {}, showToast() {},
        getConversationTaskDocumentSummary: () => ({ readyCount: 0 }),
        getDocumentActionMaxDocuments: () => 10,
    };
    vm.createContext(scope);
    vm.runInContext(`${body}\nglobalThis.send = actuallySendMessage;`, scope);
    assert.equal(await scope.send('Unsent request'), true);
    assert.deepEqual(operations, [
        ['preflight', null], ['create'], ['cancel', '/api/action-auth/requests/draft-request/cancel'],
        ['preflight', 'new-conversation'], ['append'], ['send', 'scoped-request', 'new-conversation'],
    ]);
});

test('multiple requirements are collected one at a time without premature execution', async () => {
    const env = setup(missing([requirement('api_key'), requirement('bearer_token', { id: 'second', action_name: 'Second action' })]));
    let saves = 0;
    const originalFetch = env.controller.fetchImpl;
    env.controller.fetchImpl = async (url, options) => {
        if (url.endsWith('/credentials')) {
            saves += 1;
            return response(saves === 1
                ? missing([requirement('bearer_token', { id: 'second', action_name: 'Second action' })])
                : ready());
        }
        return originalFetch(url, options);
    };
    let executed = false;
    const pending = env.controller.authorize({ agent_info: { id: 'agent' } }).then(value => { executed = Boolean(value); });
    await tick();
    assert.equal(env.root.textContent.includes('Second action'), false);
    env.document.getElementById('action-auth-secret').value = 'SYNTHETIC-API-KEY';
    env.document.getElementById('action-auth-destination').checked = true;
    await env.root.querySelector('form').fire('submit');
    assert.equal(executed, false);
    assert.match(env.root.textContent, /Second action/);
    env.document.getElementById('action-auth-secret').value = 'SYNTHETIC-TOKEN';
    env.document.getElementById('action-auth-destination').checked = true;
    await env.root.querySelector('form').fire('submit');
    await pending;
    assert.equal(executed, true);
    assert.equal(saves, 2);
    env.controller.destroy();
});

test('retry and edit preflight before their mutating preparation routes and forward only the opaque receipt', async () => {
    for (const operation of ['retry', 'edit']) {
        const env = environment();
        const requests = [];
        const sends = [];
        let approve;
        const agent = env.document.field('retry-agent-select', 'mission-agent', 'select');
        agent.options = [{ dataset: { agentId: 'mission-agent', name: 'mission', isGlobal: 'true' } }];
        agent.selectedIndex = 0;
        env.document.field('retry-mode-agent').checked = true;
        env.document.field('edit-message-content', 'Edited draft', 'textarea');
        const pending = {
            messageId: 'original-message', messageType: 'user', messageDiv: {},
            metadata: { agent_selection: { selected_agent: 'mission', selected_agent_id: 'mission-agent', is_global: true } },
        };
        env.window.pendingMessageRetry = pending;
        env.window.pendingMessageEdit = pending;
        env.window.chatConversations = { getCurrentConversationId: () => 'conversation' };
        const scope = {
            ...env, console: { log() {}, error() {} },
            showToast: message => assert.fail(message), showLoadingIndicatorInChatbox() {}, hideLoadingIndicatorInChatbox() {},
            CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
            setTimeout: callback => queueMicrotask(callback),
            prepareActionAuthExecution: payload => new Promise(resolve => {
                approve = () => { payload.action_auth_request_id = 'private-retry'; resolve(true); };
            }),
            handleActionAuthRequired: () => false,
            sendMessageWithStreaming: (payload, _temp, _id, options) => sends.push({ payload, options }),
            fetch: async (url, options) => {
                requests.push({ url, body: JSON.parse(options.body) });
                return response({ success: true, chat_request: { conversation_id: 'conversation', agent_info: { id: 'mission-agent' } } });
            },
        };
        const filename = operation === 'retry' ? 'chat-retry.js' : 'chat-edit.js';
        const source = readFileSync(new URL(`../application/single_app/static/js/chat/${filename}`, import.meta.url), 'utf8');
        const start = source.indexOf(`window.executeMessage${operation === 'retry' ? 'Retry' : 'Edit'} =`);
        const end = source.indexOf('\n};', start) + 3;
        vm.createContext(scope);
        vm.runInContext(source.slice(start, end), scope);
        const execute = env.window[operation === 'retry' ? 'executeMessageRetry' : 'executeMessageEdit'];
        const result = execute();
        await tick();
        await execute();
        assert.equal(requests.length, 0);
        assert.equal(sends.length, 0);
        approve();
        await result;
        await tick();
        assert.equal(requests.length, 1);
        assert.equal(sends.length, 1);
        assert.equal(requests[0].body.action_auth_request_id, 'private-retry');
        assert.equal(sends[0].payload.action_auth_request_id, 'private-retry');
        assert.equal(sends[0].options.actionAuthPrepared, true);
        assert.equal(Object.hasOwn(requests[0].body, 'credentials'), false);
    }
});

test('typed SSE and HTTP action-auth controls bypass assistant errors, OAuth, telemetry, and automatic recovery', async () => {
    const source = readFileSync(new URL('../application/single_app/static/js/chat/chat-streaming.js', import.meta.url), 'utf8');
    const body = source.slice(source.indexOf('function consumeStreamingResponse('), source.indexOf('\nexport async function sendMessageWithStreaming('));
    for (const transport of ['sse', 'sse-type', 'sse-partial', 'http', 'http-type']) {
        const env = environment();
        const events = [];
        const repairs = [];
        const nodes = new Map([
            ['temp-ai', env.document.field('temp-ai', '', 'div')],
            ['temp-user', env.document.field('temp-user', '', 'div')],
        ]);
        let streamingCursor = false;
        nodes.get('temp-ai').querySelector = selector => selector === '.streaming-cursor'
            ? { remove: () => { streamingCursor = false; } } : null;
        const control = {
            ...missing(), [transport.endsWith('-type') ? 'type' : 'error_code']: 'action_credentials_required',
            execution_started: true, error: 'PRIVATE-CONTROL-NOT-AN-ASSISTANT-ERROR',
        };
        const scope = {
            ...env, console: { error: (...values) => assert.fail(`Unexpected log: ${values}`) },
            AbortController, TextDecoder, currentStreamController: null, currentStreamContext: null,
            isActionCredentialsRequired, USER_MESSAGE_PERSISTED_EVENT_TYPE: 'user_message_persisted',
            resolveCancelEndpoint: () => null, attachStreamingStopButton() {}, removeStreamingStopButton() {},
            stopThoughtPolling() {}, clearStreamingThoughtSession() {}, clearCurrentStreamController() {},
            setUserMessageStreamingActionsDisabled() {}, getStreamingMessageElement: id => nodes.get(id),
            updateStreamingMessage: (_id, content) => {
                nodes.get('temp-ai').textContent = content;
                streamingCursor = true;
            },
            reportClientStreamEvent: (name, data) => { events.push({ name, data }); },
            handleActionAuthRequired: (data, options) => repairs.push({ data, options }),
            normalizeLegacyEscapedSseDelimiters: value => value,
            parseSseEventPayload: block => block.replace(/^data: /, ''),
            buildStreamingRequestError: data => Object.assign(new Error('Private connection required'), { streamErrorData: data }),
            handleStreamError: () => assert.fail('Private control became an assistant message.'),
            attemptStreamingRecovery: () => assert.fail('A failed turn was recovered automatically.'),
            markUserMessageMetadataUnconfirmed() {},
        };
        vm.createContext(scope);
        vm.runInContext(`${body}\nglobalThis.consume = consumeStreamingResponse;`, scope);
        let terminal = 0;
        const requestFactory = async () => transport.startsWith('http') ? response(control, 409) : {
            ok: true,
            body: { getReader: () => ({
                read: async () => ({
                    done: false,
                    value: new TextEncoder().encode(`${transport === 'sse-partial' ? 'data: {"content":"Earlier output"}\n\n' : ''}data: ${JSON.stringify(control)}\n\n`),
                }),
            }) },
        };
        scope.consume(requestFactory, 'temp-ai', 'temp-user', {
            recoveryConversationId: 'conversation', onFinally: () => { terminal += 1; },
        });
        await tick();
        await tick();
        assert.equal(repairs.length, 1);
        assert.equal(terminal, 1);
        assert.equal(nodes.get('temp-ai').isConnected, transport === 'sse-partial');
        assert.equal(streamingCursor, false);
        if (transport === 'sse-partial') assert.equal(nodes.get('temp-ai').textContent, 'Earlier output');
        assert.equal(nodes.get('temp-user').isConnected, false);
        assert.equal(JSON.stringify(events).includes('PRIVATE-CONTROL'), false);
        assert.equal(env.chatbox.children.length, 0);
    }
});
