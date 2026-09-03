// test_mcp_stdio_removal_ui.js
// Version: 0.261.029
// Implemented in: 0.261.029
// Offline behavioral tests of the real modal, table/card, and personal bulk-save modules.
// Run: node --experimental-vm-modules --test functional_tests\test_mcp_stdio_removal_ui.js

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const appDir = path.resolve(__dirname, '..', 'application', 'single_app');
const scriptDir = path.join(appDir, 'static', 'js');
const modalSource = fs.readFileSync(path.join(appDir, 'templates', '_plugin_modal.html'), 'utf8');
const preset = JSON.parse(fs.readFileSync(path.join(appDir, 'mcp_presets', 'definitions', 'generic.json'), 'utf8'));
const retirementMessage = 'This action uses stdio, which is no longer supported. Reconfigure it to use a supported remote MCP server, or delete it.';

function decodeText(value) {
    return value.replace(/&(?:lt|gt|quot|apos|amp);|&#(?:x[0-9a-f]+|\d+);/gi, entity => {
        const names = { '&lt;': '<', '&gt;': '>', '&quot;': '"', '&apos;': "'", '&amp;': '&' };
        if (Object.hasOwn(names, entity)) return names[entity];
        return String.fromCodePoint(entity.startsWith('&#x') ? parseInt(entity.slice(3), 16) : parseInt(entity.slice(2), 10));
    });
}

class TextNode {
    constructor(text) {
        this.textContent = text;
        this.parentNode = null;
    }

    cloneNode() {
        return new TextNode(this.textContent);
    }
}

class Element {
    constructor(tagName, document) {
        this.tagName = tagName.toLowerCase();
        this.ownerDocument = document;
        this.childNodes = [];
        this.attributes = {};
        this.dataset = {};
        this.style = {
            removeProperty(name) {
                const previous = this[name] || '';
                delete this[name];
                return previous;
            }
        };
        this.listeners = {};
        this.disabled = false;
        this.checked = false;
        this._value = undefined;
        this.classList = {
            contains: value => this.className.split(/\s+/).includes(value),
            add: (...values) => { this.className = [...new Set([...this.className.split(/\s+/).filter(Boolean), ...values])].join(' '); },
            remove: (...values) => { this.className = this.className.split(/\s+/).filter(value => !values.includes(value)).join(' '); },
            toggle: (value, force) => {
                const enabled = force === undefined ? !this.classList.contains(value) : force;
                this.classList[enabled ? 'add' : 'remove'](value);
                return enabled;
            }
        };
    }

    get children() { return this.childNodes.filter(node => node instanceof Element); }
    get firstChild() { return this.childNodes[0] || null; }
    get className() { return this.attributes.class || ''; }
    set className(value) { this.attributes.class = value; }
    get id() { return this.attributes.id || ''; }
    set id(value) { this.attributes.id = value; }
    get textContent() { return this.childNodes.map(node => node.textContent).join(''); }
    set textContent(value) { this.replaceChildren(new TextNode(String(value ?? ''))); }
    get options() { return this.querySelectorAll('option'); }
    get selectedOptions() { return this.options.filter(option => option.value === this.value); }
    get value() {
        if (this._value !== undefined) return this._value;
        if (this.tagName === 'select') {
            return (this.options.find(option => option.attributes.selected !== undefined)
                || this.options.find(option => !option.disabled))?.value || '';
        }
        return this.tagName === 'textarea' ? this.textContent : (this.attributes.value || '');
    }
    set value(value) {
        const text = String(value);
        this._value = this.tagName === 'select' && !this.options.some(option => option.value === text) ? '' : text;
    }
    get innerHTML() {
        return this.childNodes.map(node => {
            if (node instanceof TextNode) {
                return node.textContent.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
            }
            const attributes = Object.entries(node.attributes).map(([key, value]) => ` ${key}="${value}"`).join('');
            return `<${node.tagName}${attributes}>${node.innerHTML}</${node.tagName}>`;
        }).join('');
    }
    set innerHTML(value) {
        this.replaceChildren();
        parseMarkup(String(value), this);
    }

    appendChild(node) {
        node.parentNode = this;
        this.childNodes.push(node);
        return node;
    }

    append(...nodes) { nodes.forEach(node => this.appendChild(node)); }
    replaceChildren(...nodes) {
        this.childNodes.forEach(node => { node.parentNode = null; });
        this.childNodes = [];
        this.append(...nodes);
    }
    prepend(node) {
        node.parentNode = this;
        this.childNodes.unshift(node);
    }
    before(node) {
        node.parentNode = this.parentNode;
        this.parentNode.childNodes.splice(this.parentNode.childNodes.indexOf(this), 0, node);
    }
    removeChild(node) {
        this.childNodes.splice(this.childNodes.indexOf(node), 1);
        node.parentNode = null;
        return node;
    }
    remove() { this.parentNode?.removeChild(this); }
    setAttribute(name, value) {
        this.attributes[name] = String(value);
        if (name === 'checked') this.checked = true;
        if (name === 'disabled') this.disabled = true;
        if (name.startsWith('data-')) {
            this.dataset[name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = String(value);
        }
    }
    getAttribute(name) { return this.attributes[name] ?? null; }
    removeAttribute(name) { delete this.attributes[name]; }
    addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
    dispatchEvent(event) {
        this.fire(event.type);
        return true;
    }
    async fire(type, event = null) {
        event ||= { type, target: this, preventDefault() {}, stopPropagation() { this.stopped = true; } };
        if (this[`on${type}`]) await this[`on${type}`](event);
        for (const listener of this.listeners[type] || []) await listener(event);
        if (!event.stopped && this.parentNode instanceof Element) await this.parentNode.fire(type, event);
    }
    matches(selector) {
        if (selector.includes(':checked') && !this.checked) return false;
        const attributes = [...selector.matchAll(/\[([\w-]+)(?:=["']?([^"'\]]*)["']?)?\]/g)];
        if (!attributes.every(([, name, value]) => value === undefined ? this.getAttribute(name) !== null : this.getAttribute(name) === value)) return false;
        const simple = selector.replace(/\[[^\]]*\]/g, '').replace(/:checked/g, '');
        const tag = simple.match(/^[a-z][\w-]*/i)?.[0];
        if (tag && tag.toLowerCase() !== this.tagName) return false;
        const id = simple.match(/#([\w-]+)/)?.[1];
        if (id && id !== this.id) return false;
        return [...simple.matchAll(/\.([\w-]+)/g)].every(([, value]) => this.classList.contains(value));
    }
    closest(selector) { return this.matches(selector) ? this : this.parentNode?.closest?.(selector) || null; }
    querySelectorAll(selector) {
        const matches = [];
        const parts = selector.split(/\s+(?![^[]*\])/);
        const leaf = parts.pop();
        const visit = node => {
            for (const child of node.children) {
                if (child.matches(leaf) && (!parts.length || child.parentNode.closest(parts.join(' ')))) matches.push(child);
                visit(child);
            }
        };
        visit(this);
        return matches;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    cloneNode(deep = false) {
        const node = new Element(this.tagName, this.ownerDocument);
        Object.entries(this.attributes).forEach(([key, value]) => node.setAttribute(key, value));
        node._value = this._value;
        if (deep) this.childNodes.forEach(child => node.appendChild(child.cloneNode(true)));
        return node;
    }
}

function parseMarkup(markup, root) {
    const stack = [root];
    const voidTags = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'wbr']);
    for (const token of markup.match(/<!--[\s\S]*?-->|<[^>]+>|[^<]+/g) || []) {
        if (token.startsWith('<!--') || token.startsWith('<!')) continue;
        if (token.startsWith('</')) {
            const tag = token.slice(2, -1).trim().toLowerCase();
            const index = stack.findLastIndex(element => element.tagName === tag);
            if (index > 0) stack.splice(index);
        } else if (token.startsWith('<')) {
            const match = token.match(/^<([\w-]+)([\s\S]*?)\/?>$/);
            if (!match) continue;
            const element = root.ownerDocument.createElement(match[1]);
            for (const attribute of match[2].matchAll(/([\w:-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g)) {
                element.setAttribute(attribute[1], decodeText(attribute[2] ?? attribute[3] ?? attribute[4] ?? ''));
            }
            stack.at(-1).appendChild(element);
            if (!voidTags.has(element.tagName) && !token.endsWith('/>')) stack.push(element);
        } else {
            stack.at(-1).appendChild(new TextNode(decodeText(token)));
        }
    }
}

class Document extends Element {
    constructor() {
        super('document', null);
        this.ownerDocument = this;
        this.readyState = 'loading';
        this.body = this;
    }
    createElement(tag) { return new Element(tag, this); }
    createTextNode(text) { return new TextNode(text); }
    getElementById(id) { return this.querySelector(`#${id}`); }
}

function retiredAction(overrides = {}) {
    return {
        id: 'legacy-source-1',
        name: 'retired_action',
        displayName: 'Retired Action',
        type: 'mcp',
        endpoint: 'stdio://local',
        is_enabled: true,
        auth: { type: 'NoAuth' },
        metadata: {},
        additionalFields: {
            transport: ' StDiO ',
            command: 'DO_NOT_DISPLAY_PROCESS',
            args: ['DO_NOT_DISPLAY_ARGS'],
            env: { PRIVATE_VALUE: 'DO_NOT_DISPLAY_ENV' },
            mcp_tools: [{ original_name: 'tool', function_name: 'tool', input_schema: { properties: { command: { type: 'string' }, args: { type: 'array' }, env: { type: 'object' } } } }]
        },
        ...overrides
    };
}

async function environment(scope = 'personal') {
    const document = new Document();
    document.innerHTML = modalSource;
    const requests = [];
    const notices = [];
    const modalInstances = new Map();
    class Modal {
        constructor(element) { this.element = element; modalInstances.set(element, this); }
        show() { this.element.classList.add('show'); }
        hide() { this.element.classList.remove('show'); }
        static getInstance(element) { return modalInstances.get(element); }
    }
    const window = {
        location: { pathname: scope === 'global' ? '/admin/actions' : '/workspace' },
        addEventListener() {},
        groupWorkspaceContext: { activeGroupId: 'group-1', userRole: 'Owner' }
    };
    const result = { document, window, requests, notices, plugins: [], writes: [], deleted: [], migrationStatus: {}, migrationResult: {} };
    const fetch = async (url, options = {}) => {
        const method = options.method || 'GET';
        const body = options.body ? JSON.parse(options.body) : null;
        requests.push({ url, method, body });
        let payload;
        if (url.startsWith('/static/json/')) {
            payload = JSON.parse(fs.readFileSync(path.join(appDir, ...url.slice(1).split('/')), 'utf8'));
        } else if (url === '/api/plugins/mcp/presets') {
            payload = { defaultPreset: 'generic', presets: [preset] };
        } else if (url.startsWith('/api/plugins/mcp/preconfigurations')) {
            payload = { preconfigurations: [] };
        } else if (url.endsWith('/types')) {
            payload = [{ type: 'mcp', displayName: 'Model Context Protocol server' }];
        } else if (url.endsWith('/auth-types')) {
            payload = { allowedAuthTypes: ['NoAuth', 'key', 'identity'] };
        } else if (url.startsWith('/api/workspace-identities/')) {
            payload = [];
        } else if (url === '/api/plugins/validate') {
            payload = { valid: true, errors: [], warnings: [] };
        } else if (url === '/api/user/plugins') {
            if (method === 'POST') result.writes.push(body);
            payload = method === 'GET' ? structuredClone(result.plugins) : { success: true };
        } else if (url.startsWith('/api/user/plugins/') && method === 'DELETE') {
            result.deleted.push(url);
            payload = { success: true };
        } else if (url === '/api/group/plugins') {
            payload = { actions: structuredClone(result.plugins) };
        } else if (url === '/api/migrate/status') {
            payload = structuredClone(result.migrationStatus);
        } else if (url === '/api/migrate/all' && method === 'POST') {
            payload = structuredClone(result.migrationResult);
        } else if (url === '/api/plugins/mcp/discover') {
            payload = { success: true, tools: [], warnings: [] };
        } else if (url === '/api/plugins/test-mcp-connection') {
            payload = { success: true, message: 'Connected.', warnings: [] };
        } else {
            throw new Error(`Unexpected offline request: ${method} ${url}`);
        }
        return { ok: true, status: 200, json: async () => payload, text: async () => JSON.stringify(payload) };
    };
    const context = vm.createContext({
        window, document, fetch, bootstrap: { Modal }, URL,
        Event: class { constructor(type) { this.type = type; } },
        console: { log() {}, warn() {}, error() {} },
        localStorage: { getItem() { return null; }, setItem() {} },
        setTimeout, clearTimeout, confirm: () => true
    });
    const modules = new Map();
    async function loadModule(filePath) {
        if (modules.has(filePath)) return modules.get(filePath);
        const module = filePath.endsWith(`${path.sep}chat-toast.js`)
            ? new vm.SyntheticModule(['showToast'], function () { this.setExport('showToast', (...args) => notices.push(args)); }, { context, identifier: filePath })
            : new vm.SourceTextModule(fs.readFileSync(filePath, 'utf8'), { context, identifier: filePath });
        modules.set(filePath, module);
        await module.link((specifier, referringModule) => loadModule(path.resolve(path.dirname(referringModule.identifier), specifier)));
        await module.evaluate();
        return module;
    }
    result.load = async relativePath => (await loadModule(path.join(scriptDir, relativePath))).namespace;
    result.utils = await result.load(path.join('workspace', 'view-utils.js'));
    await result.load('plugin_modal_stepper.js');
    result.stepper = window.pluginModalStepper;
    result.stepper.setActionScope({ scope, apiBase: `/api/workspace-identities/${scope}` });
    window.pluginModalStepper = result.stepper;
    await new Promise(resolve => setImmediate(resolve));
    return result;
}

function addWorkspaceFixture(document, group = false) {
    const prefix = group ? 'group-' : '';
    const root = document.createElement('div');
    root.id = `${prefix}workspace-plugins-root`;
    if (group) root.id = 'group-plugins-root';
    document.appendChild(root);
    const template = document.createElement('template');
    template.id = `${prefix}plugins-table-template`;
    template.content = document.createElement('div');
    template.content.innerHTML = `<table id="plugins-table"><tbody id="${prefix}plugins-table-body"></tbody></table><div id="${prefix}plugins-grid-view"></div>`;
    document.appendChild(template);
    return root;
}

function addMigrationFixture(env) {
    const root = env.document.createElement('div');
    root.innerHTML = '<div id="migration-banner" class="alert alert-info d-none"><small></small><button id="migrate-all-btn">Migrate Now</button></div><div id="migration-progress" class="d-none"><div class="progress-bar"></div><span id="migration-status-text"></span></div><button id="migration-active-tab" class="nav-link" data-bs-target="#plugins-tab"></button>';
    env.document.appendChild(root);
    env.document.querySelectorAll('.nav-link.active').forEach(element => element.classList.remove('active'));
    env.document.getElementById('migration-active-tab').classList.add('active');
    env.document.getElementById('migration-banner').style.display = 'none';
    env.document.getElementById('migration-progress').style.display = 'none';
    env.migrationStatus = {
        migration_needed: true,
        legacy_data: { agents_count: 0, actions_pending_count: 2, actions_failed_count: 0, actions_retained_count: 2 }
    };
}

test('modal initialization binds real controls without stdio options or dangling process inputs', async () => {
    const { document, stepper } = await environment();
    const values = document.getElementById('mcp-transport').options.map(option => option.value);
    assert.deepEqual(values, ['', 'streamable_http', 'sse', 'websocket']);
    for (const id of ['mcp-command', 'mcp-args', 'mcp-env', 'mcp-stdio-group']) {
        assert.equal(document.getElementById(id), null);
        assert.equal(fs.readFileSync(path.join(scriptDir, 'plugin_modal_stepper.js'), 'utf8').includes(`'${id}'`), false);
    }
    for (const value of ['sse', 'SSE', 'server-sent-events', 'eventsource']) {
        const first = stepper.normalizeMcpTransportForForm(value);
        const second = stepper.normalizeMcpTransportForForm(first);
        assert.equal(first, 'sse');
        assert.equal(second, 'sse');
    }
    assert.equal(stepper.normalizeMcpTransportForForm('not-a-transport'), '');
});

test('retired records stay untouched and unselected in personal, group, and Admin modals', async () => {
    for (const scope of ['personal', 'group', 'global']) {
        const env = await environment(scope);
        const variants = [
            retiredAction(),
            retiredAction({ type: '', metadata: { type: 'Model_Context_Protocol' }, additionalFields: {}, endpoint: ' STDIO://legacy ' }),
            retiredAction({ endpoint: '', additionalFields: {}, execution_status: { state: 'unsupported', code: 'mcp_stdio_removed', message: '<img src=x onerror=unsafe()>' } })
        ];
        for (const action of variants) {
            const before = JSON.stringify(action);
            const modal = await env.stepper.showModal(action);
            env.stepper.goToStep(3);
            env.stepper.applyMcpServerProfile();
            assert.equal(env.document.getElementById('mcp-transport').value, '', scope);
            assert.equal(env.document.getElementById('mcp-endpoint').value, '', scope);
            assert.equal(env.document.getElementById('mcp-retirement-notice').textContent, retirementMessage);
            assert.throws(() => env.stepper.getFormData(), /supported remote MCP transport/);
            const requestCount = env.requests.length;
            await env.stepper.runActionConnectionTest('mcp');
            await env.stepper.discoverMcpTools();
            assert.equal(env.requests.length, requestCount, 'Test/Discover must not issue a request before explicit reconfiguration.');
            modal.hide();
            assert.equal(JSON.stringify(action), before);
            assert.equal(JSON.stringify(env.stepper.originalPlugin), before);
            assert.equal(env.document.getElementById('plugin-additional-fields')?.value || '{}', '{}');
        }
    }
});

test('explicit remote reconfiguration validates endpoint and emits no process settings or authority flags', async () => {
    for (const transport of ['streamable_http', 'sse', 'websocket']) {
        const env = await environment();
        const action = retiredAction();
        const before = JSON.stringify(action);
        await env.stepper.showModal(action);
        env.stepper.goToStep(3);
        env.document.getElementById('mcp-transport').value = transport;
        for (const endpoint of ['', 'stdio://local', 'file:///process', '/relative', 'https://user:password@example.invalid/mcp']) {
            env.document.getElementById('mcp-endpoint').value = endpoint;
            assert.throws(() => env.stepper.getFormData(), /endpoint|URL/i);
            assert.throws(() => env.stepper.buildActionConnectionTestPayload('mcp'), /endpoint|URL/i);
            const requestCount = env.requests.length;
            await env.stepper.discoverMcpTools();
            assert.equal(env.requests.length, requestCount);
        }
        const endpoint = transport === 'websocket' ? 'wss://example.invalid/mcp' : 'https://example.invalid/mcp';
        env.document.getElementById('mcp-endpoint').value = endpoint;
        env.stepper.goToStep(2);
        env.stepper.goToStep(3);
        assert.equal(env.document.getElementById('mcp-transport').value, transport);
        const manifest = env.stepper.getFormData();
        assert.equal(manifest.type, 'mcp');
        assert.equal(manifest.endpoint, endpoint);
        assert.equal(manifest.additionalFields.transport, transport);
        for (const field of ['command', 'args', 'env', 'cwd', 'env_file', 'encoding']) {
            assert.equal(Object.hasOwn(manifest.additionalFields, field), false);
        }
        for (const field of ['execution_status', 'allow_stdio', 'runtime_user_id', 'action_origin']) {
            assert.equal(Object.hasOwn(manifest, field), false);
        }
        assert.equal(JSON.stringify(manifest.additionalFields.mcp_tools), JSON.stringify(action.additionalFields.mcp_tools));
        const changes = env.stepper.detectChanges();
        assert.doesNotMatch(JSON.stringify(changes), /DO_NOT_DISPLAY/);
        await env.stepper.runActionConnectionTest('mcp');
        await env.stepper.discoverMcpTools();
        const connections = env.requests.filter(request => ['/api/plugins/test-mcp-connection', '/api/plugins/mcp/discover'].includes(request.url));
        assert.equal(connections.length, 2);
        assert.equal(connections[0].body.additionalFields.transport, transport);
        assert.equal(JSON.stringify(action), before);
    }
});

test('preset and preconfiguration callbacks cannot select a transport for a retired action', async () => {
    const { stepper, document } = await environment('global');
    await stepper.showModal(retiredAction());
    stepper.setMcpServerPreconfigurations([{
        id: 'remote', presetId: 'generic', displayName: 'Remote Server',
        transport: 'streamable_http', endpoint: 'https://example.invalid/mcp', defaults: {}
    }]);
    document.getElementById('mcp-preconfiguration').value = 'remote';
    await document.getElementById('mcp-preconfiguration').fire('change');
    assert.equal(document.getElementById('mcp-transport').value, '');
    assert.equal(document.getElementById('mcp-endpoint').value, 'https://example.invalid/mcp');
    assert.throws(() => stepper.getFormData(), /supported remote MCP transport/);
    await document.getElementById('mcp-server-profile').fire('change');
    assert.equal(document.getElementById('mcp-transport').value, '');
});

test('legacy remote forms preserve supported transport, headers, and tool argument fields', async () => {
    const { stepper, document } = await environment();
    const remote = retiredAction({
        endpoint: 'https://example.invalid/events',
        auth: { type: 'key', key: 'offline-current-action-value' },
        additionalFields: {
            transport: 'server-sent-events', auth_method: 'api_key', api_key_header_name: 'X-Remote-Key',
            custom_headers: { 'X-Remote-Route': 'fixture' }, request_timeout: 45,
            command: 'DO_NOT_DISPLAY_PROCESS', args: ['DO_NOT_DISPLAY_ARGS'], env: { name: 'DO_NOT_DISPLAY_ENV' },
            mcp_tools: retiredAction().additionalFields.mcp_tools
        }
    });
    const before = JSON.stringify(remote);
    await stepper.showModal(remote);
    stepper.goToStep(3);
    const config = stepper.getMcpConfiguration();
    assert.equal(config.additionalFields.transport, 'sse');
    assert.equal(config.additionalFields.request_timeout, 45);
    assert.equal(config.additionalFields.api_key_header_name, 'X-Remote-Key');
    assert.equal(config.additionalFields.custom_headers['X-Remote-Route'], 'fixture');
    assert.equal(config.auth.key, 'offline-current-action-value');
    assert.equal(JSON.stringify(config.additionalFields.mcp_tools), JSON.stringify(remote.additionalFields.mcp_tools));
    assert.equal(Object.hasOwn(config.additionalFields, 'command'), false);
    assert.equal(Object.hasOwn(config.additionalFields, 'args'), false);
    assert.equal(Object.hasOwn(config.additionalFields, 'env'), false);
    assert.equal(JSON.stringify(remote), before);
    await stepper.showModal(retiredAction());
    assert.equal(document.getElementById('mcp-api-key-value').value, '');
});

test('remote preset callbacks and new-action defaults still work after cancelling a retired action', async () => {
    const { stepper, document } = await environment();
    const oldAction = retiredAction();
    const modal = await stepper.showModal(oldAction);
    modal.hide();
    await stepper.showModal();
    stepper.selectedType = 'mcp';
    stepper.goToStep(3);
    assert.equal(document.getElementById('mcp-transport').value, 'streamable_http');
    assert.equal(document.getElementById('mcp-retirement-notice').classList.contains('d-none'), true);
    stepper.setMcpServerPreconfigurations([{
        id: 'remote_sse', presetId: 'generic', displayName: 'Remote SSE',
        transport: 'sse', endpoint: 'https://example.invalid/events',
        defaults: { auth_method: 'bearer', request_timeout: 45 },
        implementation: { id: 'provider', schemaVersion: '1.0.0' },
        additionalSettings: { toolArguments: { command: 'remote-argument', args: ['value'], env: { name: 'value' } } }
    }]);
    document.getElementById('mcp-preconfiguration').value = 'remote_sse';
    await document.getElementById('mcp-preconfiguration').fire('change');
    document.getElementById('mcp-bearer-token').value = 'offline-test-value';
    assert.equal(document.getElementById('mcp-transport').value, 'sse');
    assert.equal(document.getElementById('mcp-endpoint').value, 'https://example.invalid/events');
    assert.equal(document.getElementById('mcp-auth-method').value, 'bearer');
    const config = stepper.getMcpConfiguration();
    assert.equal(config.additionalFields.additionalSettings.toolArguments.command, 'remote-argument');
    assert.equal(config.additionalFields.request_timeout, 45);
    stepper.goToStep(2);
    stepper.goToStep(3);
    assert.equal(document.getElementById('mcp-transport').value, 'sse');
});

test('personal/Admin tables, cards, and detail views explain unsupported status safely', async () => {
    const env = await environment();
    const common = await env.load('plugin_common.js');
    const tbody = env.document.createElement('tbody');
    tbody.id = 'status-test-body';
    env.document.appendChild(tbody);
    const action = retiredAction({
        execution_status: { state: 'unsupported', code: 'mcp_stdio_removed', message: '<img src=x onerror=unsafe()>' }
    });
    for (const isAdmin of [false, true]) {
        common.renderPluginsTable({
            plugins: [action], tbodySelector: '#status-test-body', ensureTable: false, isAdmin,
            onToggleEnabled() {}, onDuplicate() {}
        });
        assert.match(tbody.textContent, /Unsupported/);
        assert.match(tbody.textContent, /Reconfigure it/);
        assert.doesNotMatch(tbody.textContent, /Enabled|DO_NOT_DISPLAY|onerror/);
        assert.equal(tbody.querySelector('.toggle-plugin-btn'), null);
        assert.equal(tbody.querySelector('.duplicate-plugin-btn'), null);
        assert.equal(tbody.querySelector('.edit-plugin-btn').title, 'Reconfigure action');
        assert.ok(tbody.querySelector('.delete-plugin-btn'));
        const card = env.utils.createActionCard(action, { isAdmin });
        assert.match(card.textContent, /Unsupported/);
        assert.match(card.textContent, /Reconfigure it/);
        assert.equal(card.querySelector('.mcp-retirement-notice').querySelector('img'), null);
    }
    const details = env.document.createElement('div');
    details.id = 'item-view-modal';
    details.innerHTML = '<div class="modal-dialog"><h5 class="modal-title"></h5><div class="modal-body"></div><div class="modal-footer"></div></div>';
    env.document.appendChild(details);
    env.utils.openViewModal(action, 'action', { onEdit() {}, onDelete() {} });
    assert.match(details.textContent, /Reconfigure it/);
    assert.equal(details.querySelector('.modal-footer').children[0].textContent, 'Reconfigure');
    const precedenceStatus = env.utils.getMcpRetirementStatus({ type: 'sql_query', metadata: { type: 'mcp' }, endpoint: 'stdio://local' });
    assert.equal(precedenceStatus, null);
});

test('group tables and cards retain retired actions and cleanup controls', async () => {
    const env = await environment('group');
    addWorkspaceFixture(env.document, true);
    env.plugins = [retiredAction({ is_group: true })];
    await env.load(path.join('workspace', 'group_plugins.js'));
    await env.window.fetchGroupPlugins();
    const tbody = env.document.getElementById('group-plugins-table-body');
    assert.match(tbody.textContent, /Unsupported/);
    assert.match(tbody.textContent, /Reconfigure it/);
    assert.ok(tbody.querySelector('.delete-group-plugin-btn'));
    assert.equal(tbody.querySelector('.edit-group-plugin-btn').title, 'Reconfigure action');
    assert.match(env.document.getElementById('group-plugins-grid-view').textContent, /Unsupported/);
});

test('personal bulk edits preserve unchanged retired duplicates and delete via their explicit locator', async () => {
    const env = await environment();
    addWorkspaceFixture(env.document);
    const retired = retiredAction({ name: 'shared_name', id: 'legacy-source-1' });
    const otherRetired = retiredAction({ name: 'shared_name', id: 'legacy-source-2' });
    const remote = {
        id: 'remote-id', name: 'shared_name', displayName: 'Remote Action', type: 'mcp',
        endpoint: 'https://example.invalid/mcp', additionalFields: { transport: 'sse' }
    };
    env.plugins = [retired, otherRetired, remote];
    const before = JSON.stringify(env.plugins);
    let editing;
    const updated = { ...remote, description: 'Changed remote action only.' };
    let editedManifest = updated;
    env.window.pluginModalStepper = {
        setActionScope() {},
        async showModal(action) { editing = action; return { hide() {} }; },
        getFormData() { return editedManifest; },
        showError(message) { throw new Error(message); }
    };
    await env.load(path.join('workspace', 'workspace_plugins.js'));
    await env.window.fetchPlugins();
    const tbody = env.document.getElementById('plugins-table-body');
    await tbody.children[2].querySelector('.edit-plugin-btn').fire('click');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(editing.id, remote.id);
    await env.document.getElementById('save-plugin-btn').onclick({ preventDefault() {} });
    assert.equal(env.writes.length, 1);
    assert.equal(JSON.stringify(env.writes[0][0]), JSON.stringify(retired));
    assert.equal(JSON.stringify(env.writes[0][1]), JSON.stringify(otherRetired));
    assert.equal(env.writes[0][2].id, remote.id);
    assert.equal(env.writes[0][2].description, updated.description);
    assert.equal(JSON.stringify(env.plugins), before);
    await new Promise(resolve => setImmediate(resolve));
    editedManifest = {
        name: 'reconfigured_action', displayName: 'Reconfigured Action', type: 'mcp',
        endpoint: 'https://example.invalid/events', auth: { type: 'NoAuth' }, metadata: {},
        additionalFields: { transport: 'sse' }
    };
    await env.document.getElementById('plugins-table-body').children[0].querySelector('.edit-plugin-btn').fire('click');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(editing.id, retired.id);
    await env.document.getElementById('save-plugin-btn').onclick({ preventDefault() {} });
    assert.equal(env.writes.length, 2);
    assert.equal(env.writes[1][0].id, retired.id);
    assert.equal(env.writes[1][0].additionalFields.transport, 'sse');
    assert.equal(Object.hasOwn(env.writes[1][0], 'execution_status'), false);
    assert.equal(JSON.stringify(env.writes[1][1]), JSON.stringify(otherRetired));
    assert.equal(JSON.stringify(env.plugins), before);
    await new Promise(resolve => setImmediate(resolve));
    await env.document.getElementById('plugins-table-body').children[1].querySelector('.delete-plugin-btn').fire('click');
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(env.deleted, ['/api/user/plugins/legacy-source-2']);
    assert.equal(env.writes.length, 2, 'Deleting retired actions must not use a bulk omission.');
});

test('personal DELETE uses IDs for retained remote and duplicate-name stored actions', async () => {
    const env = await environment();
    addWorkspaceFixture(env.document);
    const remote = {
        name: 'shared_remote_name', displayName: 'Remote Action', type: 'mcp',
        endpoint: 'https://example.invalid/mcp', auth: { type: 'NoAuth' },
        additionalFields: { transport: 'streamable_http' }
    };
    env.plugins = [
        {
            ...remote, id: 'legacy-action-remote-snapshot', legacy_locator: 'legacy-action-remote-snapshot',
            is_legacy: true, legacy_source: 'settings.plugins'
        },
        { ...remote, id: 'personal-remote-one' },
        { ...remote, id: 'personal-remote-two' },
        { ...remote, name: 'idless_remote' }
    ];
    await env.load(path.join('workspace', 'workspace_plugins.js'));
    await env.window.fetchPlugins();
    const expectedLocators = ['legacy-action-remote-snapshot', 'personal-remote-one', 'personal-remote-two', 'idless_remote'];
    for (const [index, locator] of expectedLocators.entries()) {
        const readsBeforeDelete = env.requests.filter(request => request.url === '/api/user/plugins' && request.method === 'GET').length;
        const row = env.document.getElementById('plugins-table-body').children[index];
        await row.querySelector('.delete-plugin-btn').fire('click');
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(env.deleted.at(-1), `/api/user/plugins/${encodeURIComponent(locator)}`);
        const readsAfterDelete = env.requests.filter(request => request.url === '/api/user/plugins' && request.method === 'GET').length;
        assert.equal(readsAfterDelete, readsBeforeDelete + 1, 'Every deletion must refresh the authoritative locators.');
    }
    assert.equal(env.writes.length, 0);
});

test('retained-only migration outcomes show manual cleanup guidance without a Migrate Now retry loop', async () => {
    const env = await environment();
    addMigrationFixture(env);
    let refreshCount = 0;
    env.window.fetchPlugins = () => { refreshCount += 1; };
    const migration = await env.load(path.join('workspace', 'workspace-migration.js'));
    migration.initializeMigration();
    await new Promise(resolve => setImmediate(resolve));
    const banner = env.document.getElementById('migration-banner');
    const button = env.document.getElementById('migrate-all-btn');
    assert.equal(banner.classList.contains('d-none'), false);
    assert.equal(banner.style.display, undefined, 'Legacy inline hiding must not override Bootstrap visibility.');
    env.migrationResult = { action_migration: { migrated_count: 2, retained_count: 2, failed_count: 0, complete: true } };
    env.migrationStatus = {
        migration_needed: false,
        legacy_data: { agents_count: 0, actions_pending_count: 0, actions_failed_count: 0, actions_retained_count: 2 }
    };
    await button.fire('click');
    assert.equal(refreshCount, 1);
    assert.equal(banner.classList.contains('d-none'), true);
    assert.equal(env.document.getElementById('migration-progress').classList.contains('d-none'), true);
    assert.equal(button.disabled, false);
    assert.equal(env.notices.at(-1)[1], 'warning');
    assert.match(env.notices.at(-1)[0], /2 legacy actions were kept for manual reconfiguration or deletion/);
    assert.match(env.notices.at(-1)[0], /Stdio actions cannot run/);
    assert.doesNotMatch(env.notices.at(-1)[0], /completed successfully/);
    await migration.checkMigrationStatus();
    await migration.checkMigrationStatus();
    assert.equal(banner.classList.contains('d-none'), true);
    assert.equal(env.requests.filter(request => request.url === '/api/migrate/all').length, 1);
});

test('mixed migration failures preserve an actionable retry notice and never report blanket success', async () => {
    const env = await environment();
    addMigrationFixture(env);
    const migration = await env.load(path.join('workspace', 'workspace-migration.js'));
    migration.initializeMigration();
    await new Promise(resolve => setImmediate(resolve));
    env.migrationResult = { action_migration: { migrated_count: 1, retained_count: 2, failed_count: 1, complete: false } };
    env.migrationStatus = {
        migration_needed: true,
        legacy_data: { agents_count: 0, actions_pending_count: 0, actions_failed_count: 1, actions_retained_count: 2 }
    };
    await env.document.getElementById('migrate-all-btn').fire('click');
    const banner = env.document.getElementById('migration-banner');
    assert.equal(banner.classList.contains('d-none'), false);
    assert.match(banner.textContent, /1 action ready to migrate or retry/);
    assert.match(banner.textContent, /2 other legacy actions need manual reconfiguration or deletion/);
    assert.equal(env.document.getElementById('migrate-all-btn').disabled, false);
    assert.equal(env.document.getElementById('migration-progress').classList.contains('d-none'), true);
    assert.equal(env.notices.at(-1)[1], 'warning');
    assert.match(env.notices.at(-1)[0], /Migration is incomplete/);
    assert.doesNotMatch(env.notices.at(-1)[0], /completed successfully/);
    await migration.checkMigrationStatus();
    assert.equal(env.requests.filter(request => request.url === '/api/migrate/all').length, 1);
});
