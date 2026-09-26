// test_admin_model_endpoint_editor_integration.js
/**
 * Offline integration regressions for the combined classic AI Connections editor.
 * Version: 0.261.137
 * Implemented in: 0.261.122
 * The editor's catalog profile picker and planner model dropdown modules are linked since 0.261.137.
 *
 * Loads the real editor, shared modal markup, and capacity editor with a small DOM
 * fixture. Covers Custom auth, images, embeddings, capacity, and draft preservation.
 * All fetches are intercepted; no app, browser service, or provider runs.
 * Run: node --experimental-vm-modules --test functional_tests\test_admin_model_endpoint_editor_integration.js
 */

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const test = require("node:test");
const vm = require("node:vm");

const appDirectory = path.resolve(__dirname, "..", "application", "single_app");
const editorPath = path.join(appDirectory, "static", "js", "admin", "admin_model_endpoints.js");
const budgetPath = path.join(appDirectory, "static", "js", "model_budget_editor.js");
const plannerPath = path.join(appDirectory, "static", "js", "admin", "admin_orchestration_planner_model.js");
const modalMarkup = fs.readFileSync(path.join(appDirectory, "templates", "_multiendpoint_modal.html"), "utf8");
const paneMarkup = fs.readFileSync(path.join(appDirectory, "templates", "admin", "_panes", "model-endpoints.html"), "utf8");
const apiTypes = [
    { value: "openai", label: "OpenAI API", usesModelName: true, defaultApiKeyPrefix: "Bearer" },
    { value: "azure_openai", label: "Azure OpenAI API", usesModelName: false, requiresApiVersion: true, versionField: "api_version" },
    { value: "anthropic", label: "Anthropic", usesModelName: true, versionField: "anthropic_version", defaultVersion: "2023-06-01" },
    { value: "gemini", label: "Google Gemini (OpenAI-compatible)", usesModelName: true, defaultApiKeyPrefix: "Bearer" }
].map(descriptor => ({
    authTypes: ["api_key", "bearer", "oauth2_client_credentials"],
    description: `${descriptor.label} fixture contract`,
    ...descriptor
}));

function plain(value) {
    return JSON.parse(JSON.stringify(value));
}

function decodeText(value) {
    const entities = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
    return value.replace(/&(amp|lt|gt|quot|apos|nbsp);/g, (_, name) => entities[name]);
}

class TextNode {
    constructor(text) {
        this.textContent = String(text);
        this.parentNode = null;
    }

    cloneNode() {
        return new TextNode(this.textContent);
    }
}

class Element {
    constructor(tagName, ownerDocument) {
        this.tagName = tagName.toLowerCase();
        this.ownerDocument = ownerDocument;
        this.childNodes = [];
        this.attributes = {};
        this.dataset = {};
        this.listeners = {};
        this.checked = false;
        this.disabled = false;
        this.classList = {
            contains: name => this.className.split(/\s+/).includes(name),
            add: (...names) => { this.className = [...new Set([...this.className.split(/\s+/).filter(Boolean), ...names])].join(" "); },
            remove: (...names) => { this.className = this.className.split(/\s+/).filter(name => !names.includes(name)).join(" "); },
            toggle: (name, force) => {
                const enabled = force ?? !this.classList.contains(name);
                this.classList[enabled ? "add" : "remove"](name);
                return enabled;
            }
        };
    }

    get children() { return this.childNodes.filter(node => node instanceof Element); }
    get id() { return this.attributes.id || ""; }
    set id(value) { this.attributes.id = String(value); }
    get className() { return this.attributes.class || ""; }
    set className(value) { this.attributes.class = value; }
    get textContent() { return this.childNodes.map(node => node.textContent).join(""); }
    set textContent(value) { this.replaceChildren(new TextNode(value ?? "")); }
    get options() { return this.querySelectorAll("option"); }
    get selectedOptions() { return this.options.filter(option => option.value === this.value); }
    get value() {
        if (this.inputValue !== undefined) return this.inputValue;
        return this.tagName === "select" ? this.options[0]?.value || "" : this.attributes.value || "";
    }
    set value(value) {
        const text = String(value);
        this.inputValue = this.tagName === "select" && !this.options.some(option => option.value === text) ? "" : text;
    }
    set innerHTML(value) {
        this.replaceChildren();
        parseMarkup(String(value), this);
    }

    appendChild(node) {
        if (typeof node === "string") node = new TextNode(node);
        if (node.tagName === "fragment") {
            [...node.childNodes].forEach(child => this.appendChild(child));
            return node;
        }
        node.parentNode?.removeChild(node);
        node.parentNode = this;
        this.childNodes.push(node);
        return node;
    }
    append(...nodes) { nodes.forEach(node => this.appendChild(node)); }
    add(option) { this.appendChild(option); }
    removeChild(node) {
        this.childNodes.splice(this.childNodes.indexOf(node), 1);
        node.parentNode = null;
    }
    replaceChildren(...nodes) {
        [...this.childNodes].forEach(node => this.removeChild(node));
        this.append(...nodes);
    }
    after(node) {
        const parent = this.parentNode;
        let index = parent.childNodes.indexOf(this) + 1;
        const nodes = node.tagName === "fragment" ? [...node.childNodes] : [node];
        nodes.forEach(child => {
            child.parentNode?.removeChild(child);
            parent.childNodes.splice(index++, 0, child);
            child.parentNode = parent;
        });
    }
    setAttribute(name, value) {
        this.attributes[name] = String(value);
        if (name.startsWith("data-")) this.dataset[this.datasetKey(name)] = String(value);
        if (name === "checked" || name === "disabled") this[name] = true;
    }
    getAttribute(name) {
        if (name.startsWith("data-")) return this.dataset[this.datasetKey(name)] ?? null;
        return this.attributes[name] ?? null;
    }
    removeAttribute(name) { delete this.attributes[name]; }
    datasetKey(name) { return name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()); }
    setCustomValidity(message) { this.validationMessage = message; }
    focus() { this.ownerDocument.activeElement = this; }
    addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
    async fire(type, event = { type, target: this, preventDefault() {} }) {
        for (const listener of this.listeners[type] || []) await listener(event);
        if (this.parentNode) await this.parentNode.fire(type, event);
    }
    matches(selector) {
        const attributes = [...selector.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)];
        if (!attributes.every(([, key, value]) => value === undefined ? this.getAttribute(key) !== null : this.getAttribute(key) === value)) return false;
        const simple = selector.replace(/\[[^\]]*\]/g, "");
        const tag = simple.match(/^[a-z][\w-]*/i)?.[0];
        if (tag && this.tagName !== tag.toLowerCase()) return false;
        const id = simple.match(/#([\w-]+)/)?.[1];
        if (id && this.id !== id) return false;
        return [...simple.matchAll(/\.([\w-]+)/g)].every(([, name]) => this.classList.contains(name));
    }
    closest(selector) { return this.matches(selector) ? this : this.parentNode?.closest(selector) || null; }
    querySelectorAll(selector) {
        const result = [];
        const visit = node => node.children.forEach(child => {
            if (child.matches(selector)) result.push(child);
            visit(child);
        });
        visit(this);
        return result;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    cloneNode(deep = false) {
        const copy = new Element(this.tagName, this.ownerDocument);
        Object.entries(this.attributes).forEach(([key, value]) => copy.setAttribute(key, value));
        Object.assign(copy.dataset, this.dataset);
        copy.inputValue = this.inputValue;
        if (deep) this.childNodes.forEach(child => copy.appendChild(child.cloneNode(true)));
        return copy;
    }
}

function parseMarkup(markup, root) {
    const stack = [root];
    const voidTags = new Set(["input", "img", "br", "hr", "meta", "link"]);
    const rendered = markup.replace(/{%[\s\S]*?%}|{{[\s\S]*?}}/g, "");
    for (const token of rendered.match(/<!--[\s\S]*?-->|<[^>]+>|[^<]+/g) || []) {
        if (token.startsWith("<!")) continue;
        if (token.startsWith("</")) {
            const tagName = token.slice(2, -1).trim().toLowerCase();
            const index = stack.findLastIndex(element => element.tagName === tagName);
            if (index > 0) stack.length = index;
        } else if (token.startsWith("<")) {
            const [, tagName, attributes] = token.match(/^<([\w-]+)([\s\S]*?)\/?>$/) || [];
            if (!tagName) continue;
            const element = root.ownerDocument.createElement(tagName);
            for (const [, name, doubleValue, singleValue, bareValue] of attributes.matchAll(/([\w:-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) {
                element.setAttribute(name, decodeText(doubleValue ?? singleValue ?? bareValue ?? ""));
            }
            stack.at(-1).appendChild(element);
            if (!voidTags.has(element.tagName) && !token.endsWith("/>")) stack.push(element);
        } else {
            stack.at(-1).appendChild(new TextNode(decodeText(token)));
        }
    }
}

function endpointFixture() {
    return {
        id: "saved-endpoint", name: "Saved gateway", provider: "custom", api_type: "openai", enabled: true,
        auth: { type: "bearer" }, has_bearer_token: true,
        connection: {
            endpoint: "https://gateway.example.test/prefix", url_mode: "exact",
            api_version: "stale-azure-version", anthropic_version: "stale-anthropic-version",
            image_generation: { route: "images", futureOptions: [1, 2] }
        },
        contextWindow: 20000, tokenLimitProvider: "custom", outputTokenAccounting: "total_generation",
        operation_profiles: { image_generation: { api: "images", path: "images/generations" } },
        models: [{
            id: 'first"][data-model-row-id="other', modelName: "request-model", deploymentName: "not-the-request-model",
            displayName: '<img src="x" onerror="invalid()">', enabled: true, responseLength: 256,
            contextWindow: 16000, outputTokenLimit: 2000, catalogModelId: "published-model", modelVersion: "snapshot",
            supportsVision: true, capabilities: { processesImages: false, futureCapability: true },
            supportsChat: true, supportsImageGeneration: true, image_generation_api: "images",
            enabled_capabilities: ["chat", "image_generation", "future_task"],
            capability_status: {
                vision: { supported: true, source: "catalog" },
                chat: { supported: true, source: "declared" },
                image_generation: { supported: true, api: "images", source: "declared", editing: true }
            },
            vendorOptions: { future: [1, 2] }
        }]
    };
}

function embeddingFixture() {
    const endpoint = endpointFixture();
    endpoint.provider = "openai_compatible";
    delete endpoint.api_type;
    endpoint.auth = { type: "api_key" };
    endpoint.has_api_key = true;
    endpoint.has_bearer_token = false;
    endpoint.connection = {
        endpoint: "https://gateway.example.test/embedding/v1",
        operation_settings: {
            embeddings: { api: "openai", auth_header: "authorization", is_apim: false },
            image_generation: { api: "images", futureOptions: [1, 2] }
        }
    };
    endpoint.models = [{
        id: 'embedding"][data-model-row-id="other',
        deploymentName: "private-embedding", modelName: "private-underlying-model",
        enabled: true, enabled_capabilities: ["embeddings", "future_task"], supportsEmbeddings: true,
        contextWindow: 4096, inputTokenLimit: 2048,
        embedding_config: {
            dimensions: 768, max_input_tokens: 1024, model_revision: "revision-one",
            openai_compatible: true, max_batch_size: 8, max_batch_tokens: 8192,
            document_prefix: "passage: ", query_prefix: "query: "
        },
        embedding_policy: { dimensions: 768, default_dimensions: 768, max_input_tokens: 1024, api: "openai" },
        capability_status: { embeddings: { supported: true, source: "declared", api: "openai" } }
    }];
    return endpoint;
}

async function createHarness(endpoint = endpointFixture(), { visionLookup, operationResult } = {}) {
    const document = new Element("document");
    document.ownerDocument = document;
    document.readyState = "loading";
    document.createElement = tagName => new Element(tagName, document);
    document.createTextNode = text => new TextNode(text);
    document.createDocumentFragment = () => document.createElement("fragment");
    document.getElementById = id => document.querySelectorAll("[id]").find(element => element.id === id) || null;
    parseMarkup(modalMarkup, document);
    const addElement = (tagName, id) => {
        const element = document.createElement(tagName);
        element.id = id;
        document.appendChild(element);
        return element;
    };
    for (const [, id, markup] of paneMarkup.matchAll(/<template id="([^"]+)">([\s\S]*?)<\/template>/g)) {
        const template = addElement("template", id);
        template.content = document.createDocumentFragment();
        parseMarkup(markup, template.content);
    }
    addElement("div", "model-endpoints").dataset.customApiTypes = JSON.stringify(apiTypes);
    document.getElementById("model-endpoint-api-type").dataset.apiTypes = JSON.stringify(apiTypes.slice(0, 3));
    addElement("input", "model_endpoints_json");
    addElement("tbody", "model-endpoints-tbody");
    addElement("select", "default-model-selection");
    addElement("input", "default_model_selection_json");

    const requests = [];
    const toasts = [];
    const events = [];
    const errors = [];
    const bootstrap = { Modal: { getOrCreateInstance: element => ({
        show() { element.visible = true; },
        hide() { element.visible = false; }
    }) } };
    const window = {
        bootstrap, crypto, modelEndpoints: [plain(endpoint)], enableMultiModelEndpoints: true,
        dispatchEvent: event => events.push(event)
    };
    const context = vm.createContext({
        document, window, bootstrap, URL, setTimeout, clearTimeout,
        console: { ...console, error: (...args) => errors.push(args) },
        CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options?.detail; } },
        Option: function (label, value) {
            const option = document.createElement("option");
            option.textContent = label;
            option.value = value;
            return option;
        },
        fetch: async (url, options = {}) => {
            const body = options.body ? JSON.parse(options.body) : null;
            requests.push({ url, body });
            let data;
            if (url === "/api/models/vision-capability") {
                data = visionLookup ? await visionLookup(body) : { models: {} };
            } else if (url === "/api/models/test-model") {
                data = { resolved: { request_url: "https://gateway.example.test/prefix/v1/chat/completions" } };
            } else if (url === "/api/v2/admin/settings/test-connection") {
                data = operationResult || { success: true, dimensions: 768 };
            } else {
                throw new Error(`Unexpected offline request: ${url}`);
            }
            return { ok: true, json: async () => data };
        }
    });
    const budget = new vm.SourceTextModule(fs.readFileSync(budgetPath, "utf8"), { context, identifier: budgetPath });
    const toast = new vm.SyntheticModule(["showToast"], function () {
        this.setExport("showToast", (message, tone) => toasts.push({ message, tone }));
    }, { context });
    const icons = new vm.SyntheticModule(["getIconPayload", "setIconPayload"], function () {
        this.setExport("getIconPayload", element => element.iconPayload || {});
        this.setExport("setIconPayload", (element, payload) => { element.iconPayload = payload; });
    }, { context });
    // The catalog profile picker is exercised by its own tests; the editor only mounts it.
    const catalogUi = new vm.SyntheticModule(["mountProfilePicker"], function () {
        this.setExport("mountProfilePicker", () => undefined);
    }, { context });
    const planner = new vm.SourceTextModule(fs.readFileSync(plannerPath, "utf8"), { context, identifier: plannerPath });
    const editor = new vm.SourceTextModule(`${fs.readFileSync(editorPath, "utf8")}
        export {
            init, openModalForEndpoint, collectModalModels, buildEndpointPayload,
            saveEndpoint, testModelConnection, testSavedImageModel, testSavedOperationModel,
            cloneEndpointForDuplicate, requestModelName, validateEmbeddingModels
        };
        export const readState = () => ({
            modelEndpoints, modalModels, modelVisionCapability, connectionDraftChanged, modalDraftChanged
        });
    `, { context, identifier: editorPath });
    await editor.link(specifier => {
        if (specifier === "../model_budget_editor.js") return budget;
        if (specifier === "../chat/chat-toast.js") return toast;
        if (specifier === "../agents_common.js") return icons;
        if (specifier === "./model_catalog_ui.js") return catalogUi;
        if (specifier === "./admin_orchestration_planner_model.js") return planner;
        throw new Error(`Unexpected import: ${specifier}`);
    });
    await editor.evaluate();
    const api = editor.namespace;
    api.init();
    const get = id => {
        const element = document.getElementById(id);
        assert.ok(element, `Missing editor control: ${id}`);
        return element;
    };
    const flush = () => new Promise(resolve => setImmediate(resolve));
    return {
        api, document, window, requests, toasts, events, errors, get, flush,
        async open(value = endpoint) {
            api.openModalForEndpoint(plain(value));
            await flush();
        },
        rows: () => get("model-endpoint-models-list").querySelectorAll("[data-model-row-id]"),
        staged: () => JSON.parse(get("model_endpoints_json").value)
    };
}

test("shared controls and registry options occur once, including all Custom auth modes", async () => {
    for (const id of ["allow_private_custom_model_endpoints", "allow_insecure_custom_model_endpoints", "custom_model_endpoint_ca_bundle_path"]) {
        assert.equal([...paneMarkup.matchAll(new RegExp(`id="${id}"`, "g"))].length, 1);
    }
    const h = await createHarness();
    await h.open();
    for (const id of ["model-endpoint-api-type", "model-endpoint-anthropic-version", "model-endpoint-api-type-help", "model-endpoint-embedding-settings"]) {
        assert.equal(h.document.querySelectorAll("[id]").filter(element => element.id === id).length, 1);
    }
    assert.equal(h.get("model-endpoint-provider").options.filter(option => option.value === "custom").length, 1);
    assert.deepEqual(h.get("model-endpoint-api-type").options.map(option => option.value), apiTypes.map(option => option.value));
    assert.equal(h.get("model-endpoint-auth-type").value, "bearer");
    assert.equal(h.get("model-endpoint-auth-type").disabled, false);
    assert.deepEqual(h.get("model-endpoint-auth-type").options.filter(option => !option.disabled).map(option => option.value), ["api_key", "bearer", "oauth2_client_credentials"]);
    assert.equal(h.get("model-endpoint-url-mode").value, "exact");
    assert.equal(h.get("model-endpoint-url-mode-group").classList.contains("d-none"), true);
    assert.equal(h.get("model-endpoint-bearer-group").classList.contains("d-none"), false);
    assert.equal(h.get("model-endpoint-api-key-override-group").classList.contains("d-none"), true);
    h.get("model-endpoint-auth-type").value = "oauth2_client_credentials";
    await h.get("model-endpoint-auth-type").fire("change");
    for (const id of ["model-endpoint-client-group", "model-endpoint-secret-group", "model-endpoint-token-url-group", "model-endpoint-oauth-scope-group"]) {
        assert.equal(h.get(id).classList.contains("d-none"), false, id);
    }
    assert.deepEqual(h.errors, []);
});

test("row-scoped request names, capacity overrides, canonical vision, and hidden profiles survive save", async () => {
    const endpoint = endpointFixture();
    endpoint.models.push({
        id: "other", modelName: "second-model", enabled: true, supportsVision: false,
        capabilities: { processesImages: true }, outputTokenLimit: 5000
    });
    const h = await createHarness(endpoint);
    await h.open();
    const [first, second] = h.rows();
    assert.equal(first.querySelector("[data-supports-vision-for]").checked, false);
    assert.equal(second.querySelector("[data-supports-vision-for]").checked, true);
    assert.equal(first.querySelector("[data-model-name-for]"), null);
    first.querySelector("[data-request-model-for]").value = "edited-request-model";
    first.querySelector('[data-budget-field="outputTokenLimit"]').value = "";
    h.get("model-endpoint-budget-editor").querySelector('[data-budget-field="inputTokenLimit"]').value = "18000";
    const imageAvailability = first.querySelectorAll("[data-capability-for]").find(input => input.dataset.capability === "image_generation");
    imageAvailability.checked = false;
    h.api.saveEndpoint();
    const saved = h.staged()[0];
    assert.equal(saved.inputTokenLimit, 18000);
    assert.equal(saved.contextWindow, endpoint.contextWindow);
    assert.equal(saved.models[0].outputTokenLimit, null);
    assert.equal(saved.models[0].modelName, "edited-request-model");
    assert.equal(saved.models[0].deploymentName, undefined);
    assert.equal(saved.models[0].responseLength, 256);
    assert.equal(saved.models[0].catalogModelId, "published-model");
    assert.equal(saved.models[0].modelVersion, "snapshot");
    assert.deepEqual(saved.models[0].enabled_capabilities, ["chat", "future_task"]);
    assert.equal(saved.models[0].supportsVision, false);
    assert.equal(saved.models[0].capabilities.processesImages, false);
    assert.equal(saved.models[1].supportsVision, true);
    assert.equal(saved.models[1].outputTokenLimit, 5000);
    assert.deepEqual(saved.models[0].vendorOptions, endpoint.models[0].vendorOptions);
    assert.deepEqual(saved.operation_profiles, endpoint.operation_profiles);
    assert.deepEqual(saved.connection.image_generation, endpoint.connection.image_generation);
    assert.equal(saved.connection.api_version, undefined);
    assert.equal(saved.connection.anthropic_version, undefined);
    assert.equal(saved.has_bearer_token, true);
    assert.equal(saved.auth.bearer_token, "");
    assert.equal(h.window.hasUnsavedAIConnectionEdits(), true);
    assert.equal(h.events.at(-1).detail.saved, false);
    assert.equal(h.document.querySelectorAll('img[src="x"]').length, 0);
    assert.deepEqual(h.errors, []);
});

test("edited vision stays explicit while untouched automatic vision never becomes an override", async () => {
    const endpoint = endpointFixture();
    endpoint.models.push({ id: "automatic", modelName: "automatic-model", enabled: true });
    let resolveVision;
    const h = await createHarness(endpoint, { visionLookup: () => new Promise(resolve => { resolveVision = resolve; }) });
    await h.open();
    const firstVision = h.rows()[0].querySelector("[data-supports-vision-for]");
    firstVision.checked = true;
    await firstVision.fire("change");
    h.rows()[1].querySelector("[data-display-name-for]").value = "Unsaved label";
    resolveVision({ models: { "automatic-model": { supports_vision: true, source: "catalog" } } });
    await h.flush();
    const models = plain(h.api.collectModalModels());
    assert.equal(models[0].capabilities.processesImages, true);
    assert.equal(models[0].supportsVision, true);
    assert.equal(models[1].supportsVision, undefined);
    assert.equal(models[1].displayName, "Unsaved label");
    assert.equal(h.rows()[1].querySelector("[data-supports-vision-for]").checked, true);
    assert.equal(h.window.hasUnsavedAIConnectionEdits(), true);
});

test("deployment requests remain distinct from underlying metadata and chat tests retain diagnostics", async () => {
    for (const provider of ["custom", "aoai", "aifoundry", "new_foundry"]) {
        const endpoint = endpointFixture();
        endpoint.provider = provider;
        endpoint.api_type = "azure_openai";
        endpoint.auth = { type: "api_key" };
        endpoint.has_api_key = true;
        endpoint.models[0].deploymentName = "actual-deployment";
        endpoint.models[0].modelName = "underlying-published-model";
        endpoint.connection = {
            endpoint: "https://models.example.test/api/projects/fixture",
            api_version: "2025-04-01-preview", openai_api_version: "v1"
        };
        const h = await createHarness(endpoint);
        await h.open();
        h.rows()[0].querySelector("[data-model-name-for]").value = "updated-underlying-model";
        const model = h.api.collectModalModels()[0];
        assert.equal(h.api.requestModelName(endpoint, model), "actual-deployment");
        assert.equal(model.modelName, "updated-underlying-model");
        await h.api.testModelConnection(model);
        const request = h.requests.find(item => item.url === "/api/models/test-model");
        assert.equal(request.body.model.deploymentName, "actual-deployment");
        assert.equal(request.body.model.modelName, "updated-underlying-model");
        assert.equal(request.body.model.catalogModelId, "published-model");
        assert.match(h.toasts.at(-1).message, /Called https:\/\/gateway\.example\.test/);
        assert.match(h.toasts.at(-1).message, /Image inference was not tested/);
    }
});

test("Custom auth payloads keep blank stored credentials, header overrides, and mTLS paths", async () => {
    const h = await createHarness();
    await h.open();
    await h.api.testModelConnection(h.api.collectModalModels()[0]);
    assert.equal(h.requests.at(-1).body.model.modelName, "request-model");
    assert.equal(h.requests.at(-1).body.model.deploymentName, undefined);
    h.get("model-endpoint-auth-type").value = "api_key";
    await h.get("model-endpoint-auth-type").fire("change");
    assert.equal(h.api.buildEndpointPayload(), null);
    h.get("model-endpoint-api-key").value = "fixture-key";
    h.get("model-endpoint-api-key-header").value = "x-approved-gateway-key";
    h.get("model-endpoint-api-key-prefix").value = "";
    h.get("model-endpoint-client-cert-path").value = "mounted-cert.pem";
    h.get("model-endpoint-client-key-path").value = "mounted-key.pem";
    let payload = h.api.buildEndpointPayload();
    assert.equal(payload.auth.api_key_header, "x-approved-gateway-key");
    assert.equal(payload.auth.api_key_prefix, "");
    assert.equal(payload.connection.client_cert_path, "mounted-cert.pem");
    assert.equal(payload.connection.client_key_path, "mounted-key.pem");
    h.get("model-endpoint-auth-type").value = "oauth2_client_credentials";
    await h.get("model-endpoint-auth-type").fire("change");
    assert.equal(h.api.buildEndpointPayload(), null);
    h.get("model-endpoint-token-url").value = "https://identity.example.test/token";
    h.get("model-endpoint-client-id").value = "fixture-client";
    h.get("model-endpoint-client-secret").value = "fixture-secret";
    h.get("model-endpoint-oauth-scope").value = "inference";
    payload = h.api.buildEndpointPayload();
    assert.equal(payload.auth.type, "oauth2_client_credentials");
    assert.equal(payload.auth.scope, "inference");
    assert.equal(payload.auth.api_key, undefined);
    assert.equal(payload.auth.management_cloud, undefined);
    assert.equal(payload.auth.bearer_token, undefined);
});

test("protocol changes clear stale URL modes and versions without losing capabilities or hidden profiles", async () => {
    const h = await createHarness();
    await h.open();
    h.get("model-endpoint-api-type").value = "anthropic";
    await h.get("model-endpoint-api-type").fire("change");
    assert.equal(h.get("model-endpoint-anthropic-version-group").classList.contains("d-none"), false);
    assert.equal(h.get("model-endpoint-anthropic-version").value, "2023-06-01");
    h.get("model-endpoint-url-mode").value = "exact";
    h.get("model-endpoint-api-type").value = "gemini";
    await h.get("model-endpoint-api-type").fire("change");
    assert.equal(h.get("model-endpoint-url-mode").value, "auto");
    assert.equal(h.get("model-endpoint-url-mode-exact").checked, false);
    assert.equal(h.get("model-endpoint-anthropic-version").value, "");
    assert.equal(h.get("model-endpoint-openai-api-version-group").classList.contains("d-none"), true);
    assert.equal(h.get("model-endpoint-anthropic-version-group").classList.contains("d-none"), true);
    let payload = h.api.buildEndpointPayload();
    assert.equal(payload.api_type, "gemini");
    assert.equal(payload.connection.api_version, undefined);
    assert.equal(payload.connection.anthropic_version, undefined);
    assert.equal(payload.connection.openai_api_version, undefined);
    assert.equal(h.api.readState().modalModels[0].capability_status, undefined);
    assert.equal(h.api.readState().modalModels[0].supportsImageGeneration, true);
    h.get("model-endpoint-provider").value = "aoai";
    await h.get("model-endpoint-provider").fire("change");
    payload = h.api.buildEndpointPayload();
    assert.equal(payload.auth.type, "managed_identity");
    assert.equal(payload.connection.url_mode, undefined);
    assert.equal(payload.connection.anthropic_version, undefined);
    assert.equal(payload.connection.client_cert_path, undefined);
    h.api.saveEndpoint();
    assert.equal(h.staged()[0].api_type, undefined);
    assert.deepEqual(h.staged()[0].operation_profiles, endpointFixture().operation_profiles);
});

test("invalid capacity blocks save and protocol changes, keeping the in-progress draft", async () => {
    const h = await createHarness();
    await h.open();
    const capacity = h.rows()[0].querySelector('[data-budget-field="contextWindow"]');
    capacity.value = "1e3";
    h.get("model-endpoint-api-type").value = "gemini";
    await h.get("model-endpoint-api-type").fire("change");
    assert.equal(h.get("model-endpoint-api-type").value, "openai");
    assert.equal(capacity.value, "1e3");
    assert.equal(capacity.classList.contains("is-invalid"), true);
    assert.match(capacity.validationMessage, /positive whole number/);
    h.api.saveEndpoint();
    assert.equal(h.staged()[0].models[0].contextWindow, 16000);
    assert.equal(h.get("modelEndpointModal").visible, true);
    assert.equal(h.events.length, 0);
});

test("late vision responses cannot restore capabilities from an old protocol or erase invalid draft input", async () => {
    let resolveVision;
    const h = await createHarness(endpointFixture(), { visionLookup: () => new Promise(resolve => { resolveVision = resolve; }) });
    await h.open();
    h.get("model-endpoint-api-type").value = "gemini";
    await h.get("model-endpoint-api-type").fire("change");
    resolveVision({ models: { "request-model": { supports_vision: true, source: "catalog" } } });
    await h.flush();
    assert.deepEqual(plain(h.api.readState().modelVisionCapability), {});

    await h.open();
    const capacity = h.rows()[0].querySelector('[data-budget-field="contextWindow"]');
    capacity.value = "-10";
    resolveVision({ models: { "request-model": { supports_vision: true, source: "catalog" } } });
    await h.flush();
    assert.equal(h.rows()[0].querySelector('[data-budget-field="contextWindow"]'), capacity);
    assert.equal(capacity.value, "-10");
    assert.match(h.toasts.at(-1).message, /positive whole number/);

    const anotherEndpoint = endpointFixture();
    anotherEndpoint.id = "another-endpoint";
    anotherEndpoint.models = [{ id: "another-model", modelName: "request-model", enabled: true }];
    await h.open(anotherEndpoint);
    assert.deepEqual(plain(h.api.readState().modelVisionCapability), {});
    assert.equal(h.rows()[0].querySelector("[data-supports-vision-for]").checked, false);
    resolveVision({ models: {} });
    await h.flush();

    const mixedModelEndpoint = endpointFixture();
    mixedModelEndpoint.models[0].supportsEmbeddings = true;
    mixedModelEndpoint.models[0].embedding_config = { dimensions: 768, max_input_tokens: 1024 };
    await h.open(mixedModelEndpoint);
    const dimensions = h.rows()[0].querySelector('[data-config-key="dimensions"]');
    dimensions.value = "1e3";
    await dimensions.fire("input");
    resolveVision({ models: { "request-model": { supports_vision: true, source: "catalog" } } });
    await h.flush();
    assert.equal(h.rows()[0].querySelector('[data-config-key="dimensions"]'), dimensions);
    assert.equal(dimensions.value, "1e3");
    assert.match(h.toasts.at(-1).message, /positive whole numbers/);
});

test("image tests use only a saved binding and duplicates need new credentials", async () => {
    const h = await createHarness();
    await h.open();
    const model = h.api.collectModalModels()[0];
    await h.api.testSavedImageModel(model);
    assert.deepEqual(h.requests.at(-1).body, {
        test_type: "image",
        selection: { endpoint_id: "saved-endpoint", model_id: model.id, provider: "custom" }
    });
    const count = h.requests.length;
    h.get("model-endpoint-name").value = "Unsaved name";
    await h.get("model-endpoint-name").fire("input");
    await h.api.testSavedImageModel(model);
    assert.equal(h.requests.length, count);
    assert.match(h.toasts.at(-1).message, /Save the connection first/);

    const duplicate = h.api.cloneEndpointForDuplicate(endpointFixture());
    assert.equal(duplicate.enabled, false);
    assert.notEqual(duplicate.id, "saved-endpoint");
    assert.equal(duplicate.has_bearer_token, false);
    assert.equal(duplicate.auth.bearer_token, undefined);
    await h.open(duplicate);
    h.api.saveEndpoint();
    assert.equal(h.staged().length, 1);
    h.get("model-endpoint-bearer-token").value = "new-fixture-token";
    h.get("modelEndpointModal").dataset.duplicateDisabledDefault = "true";
    h.api.saveEndpoint();
    assert.equal(h.staged().length, 2);
    assert.equal(h.staged()[1].enabled, false);
    assert.deepEqual(h.staged()[1].operation_profiles, endpointFixture().operation_profiles);
    assert.equal(h.staged()[1].models[0].contextWindow, 16000);
});

test("embedding metadata and operation edits preserve hidden image profiles, batch policy, and capacity", async () => {
    const endpoint = embeddingFixture();
    const h = await createHarness(endpoint);
    await h.open();
    assert.equal(h.get("model-endpoint-provider").options.filter(option => option.value === "openai_compatible").length, 1);
    assert.equal(h.get("model-endpoint-auth-type").value, "api_key");
    assert.deepEqual(h.get("model-endpoint-auth-type").options.filter(option => !option.disabled).map(option => option.value), ["api_key"]);
    assert.equal(h.get("custom-model-endpoint-fields").classList.contains("d-none"), true);
    const row = h.rows()[0];
    assert.equal(row.querySelector("[data-supports-vision-for]"), null);
    assert.equal(row.querySelector('[data-action="test-model"]').classList.contains("d-none"), true);
    assert.equal(row.querySelector('[data-action="test-image"]').classList.contains("d-none"), true);
    assert.equal(row.querySelector('[data-action="test-embeddings"]').classList.contains("d-none"), false);
    row.querySelector('[data-config-key="dimensions"]').value = "1024";
    row.querySelector('[data-config-key="max_input_tokens"]').value = "1536";
    row.querySelector('[data-config-key="model_revision"]').value = "revision-two";
    h.get("model-endpoint-embedding-apim").value = "true";
    h.api.saveEndpoint();
    const saved = h.staged()[0];
    assert.equal(saved.models[0].embedding_config.dimensions, 1024);
    assert.equal(saved.models[0].embedding_config.max_input_tokens, 1536);
    assert.equal(saved.models[0].embedding_config.model_revision, "revision-two");
    assert.equal(saved.models[0].embedding_config.document_prefix, "passage: ");
    assert.equal(saved.models[0].embedding_config.query_prefix, "query: ");
    assert.equal(saved.models[0].embedding_config.max_batch_size, 8);
    assert.equal(saved.models[0].embedding_config.max_batch_tokens, 8192);
    assert.equal(saved.models[0].contextWindow, 4096);
    assert.equal(saved.models[0].inputTokenLimit, 2048);
    assert.deepEqual(saved.models[0].enabled_capabilities, ["embeddings", "future_task"]);
    assert.deepEqual(saved.operation_profiles, endpoint.operation_profiles);
    assert.deepEqual(saved.connection.operation_settings.image_generation, endpoint.connection.operation_settings.image_generation);
    assert.equal(saved.connection.operation_settings.embeddings.is_apim, true);
    assert.equal(saved.connection.operation_settings.embeddings.auth_header, "authorization");
    assert.equal(saved.has_api_key, true);
    assert.equal(saved.auth.api_key, undefined);
    assert.equal(saved.connection.openai_api_version, undefined);
    assert.equal(h.events.at(-1).detail.saved, false);
    assert.deepEqual(h.requests, []);
    assert.deepEqual(h.errors, []);
});

test("embedding-only authentication does not constrain general Custom providers", async () => {
    const h = await createHarness();
    await h.open();
    h.get("model-endpoint-provider").value = "openai_compatible";
    await h.get("model-endpoint-provider").fire("change");
    assert.equal(h.get("model-endpoint-auth-type").value, "api_key");
    assert.deepEqual(h.get("model-endpoint-auth-type").options.filter(option => !option.disabled).map(option => option.value), ["api_key"]);
    assert.equal(h.get("custom-model-endpoint-fields").classList.contains("d-none"), true);
    h.get("model-endpoint-provider").value = "custom";
    await h.get("model-endpoint-provider").fire("change");
    assert.deepEqual(h.get("model-endpoint-auth-type").options.filter(option => !option.disabled).map(option => option.value), ["api_key", "bearer", "oauth2_client_credentials"]);
    h.get("model-endpoint-auth-type").value = "bearer";
    await h.get("model-endpoint-auth-type").fire("change");
    assert.equal(h.get("model-endpoint-bearer-group").classList.contains("d-none"), false);
    h.api.saveEndpoint();
    assert.equal(h.staged()[0].auth.type, "bearer");
    assert.equal(h.staged()[0].has_bearer_token, true);
    assert.equal(h.staged()[0].models[0].modelName, "request-model");
    assert.equal(h.staged()[0].models[0].image_generation_api, "images");
    assert.deepEqual(h.staged()[0].operation_profiles, endpointFixture().operation_profiles);
    assert.deepEqual(h.errors, []);
});

test("embedding dimensions require exact positive integers and unknown models cannot invent defaults", async () => {
    const h = await createHarness(embeddingFixture());
    await h.open();
    const dimensions = h.rows()[0].querySelector('[data-config-key="dimensions"]');
    assert.equal(dimensions.type, "text");
    for (const key of ["dimensions", "max_input_tokens"]) {
        const field = h.rows()[0].querySelector(`[data-config-key="${key}"]`);
        const original = field.value;
        for (const value of ["0", "-1", "1.5", "1e3", "NaN", "9007199254740992"]) {
            field.value = value;
            assert.throws(() => h.api.collectModalModels(), /positive whole numbers/);
        }
        field.value = original;
    }
    dimensions.value = "9007199254740992";
    h.get("model-endpoint-provider").value = "aoai";
    await h.get("model-endpoint-provider").fire("change");
    assert.equal(h.get("model-endpoint-provider").value, "openai_compatible");
    assert.equal(dimensions.value, "9007199254740992");
    dimensions.value = "";
    h.api.saveEndpoint();
    assert.match(h.toasts.at(-1).message, /explicit dimensions and an input token limit/);
    assert.equal(h.staged()[0].models[0].embedding_config.dimensions, 768);
    assert.equal(h.get("modelEndpointModal").visible, true);
    assert.equal(h.events.length, 0);

    const undeclared = embeddingFixture().models[0];
    delete undeclared.supportsEmbeddings;
    assert.throws(() => h.api.validateEmbeddingModels([undeclared], h.api.buildEndpointPayload()), /explicit administrator declaration/);
    undeclared.enabled = false;
    assert.doesNotThrow(() => h.api.validateEmbeddingModels([undeclared], h.api.buildEndpointPayload()));
});

test("catalog embedding models never enter the chat default or receive invented dimension overrides", async () => {
    const endpoint = embeddingFixture();
    endpoint.provider = "aoai";
    endpoint.connection.endpoint = "https://resource.example.test";
    endpoint.connection.operation_settings.embeddings = { api: "azure_openai" };
    endpoint.models[0].catalogModelId = "text-embedding-3-small";
    endpoint.models[0].supportsChat = true;
    endpoint.models[0].supportsImageGeneration = true;
    endpoint.models[0].embedding_config = { model_revision: "verified-snapshot" };
    endpoint.models[0].capability_status.embeddings.source = "catalog";
    const h = await createHarness(endpoint);
    await h.open();
    assert.equal(h.get("default-model-selection").options.length, 1);
    assert.equal(h.rows()[0].querySelector('[data-action="test-model"]').classList.contains("d-none"), true);
    assert.equal(h.rows()[0].querySelector('[data-action="test-image"]').classList.contains("d-none"), true);
    h.api.saveEndpoint();
    const config = h.staged()[0].models[0].embedding_config;
    assert.equal(config.dimensions, undefined);
    assert.equal(config.max_input_tokens, undefined);
    assert.equal(config.model_revision, "verified-snapshot");
    assert.equal(h.staged()[0].models[0].deploymentName, "private-embedding");
    assert.deepEqual(h.errors, []);
});

test("embedding inference overrides choose their own API and never rewrite Foundry project routing", async () => {
    const endpoint = embeddingFixture();
    endpoint.provider = "aoai";
    endpoint.connection.endpoint = "https://resource.example.test";
    endpoint.connection.operation_settings.embeddings = { endpoint: "https://resource.example.test/openai/v1/" };
    const h = await createHarness(endpoint);
    await h.open();
    assert.match(h.get("model-endpoint-embedding-api").options[0].textContent, /OpenAI-compatible/);
    assert.equal(h.get("model-endpoint-embedding-version-group").classList.contains("d-none"), true);
    h.get("model-endpoint-embedding-endpoint").value = "https://resource.example.test";
    await h.get("model-endpoint-embedding-endpoint").fire("input");
    assert.match(h.get("model-endpoint-embedding-api").options[0].textContent, /Azure OpenAI versioned/);
    assert.equal(h.get("model-endpoint-embedding-version-group").classList.contains("d-none"), false);

    endpoint.provider = "new_foundry";
    endpoint.connection.endpoint = "https://project.example.test/api/projects/example";
    endpoint.connection.operation_settings.embeddings = {};
    const foundry = await createHarness(endpoint);
    await foundry.open();
    assert.throws(() => foundry.api.validateEmbeddingModels(foundry.api.collectModalModels(), foundry.api.buildEndpointPayload()), /Foundry project endpoints do not route embeddings/);
    foundry.get("model-endpoint-embedding-endpoint").value = "https://resource.example.test/openai/v1/";
    foundry.api.saveEndpoint();
    assert.equal(foundry.staged()[0].connection.endpoint, endpoint.connection.endpoint);
    assert.equal(foundry.staged()[0].connection.project_name, "example");
    assert.equal(foundry.staged()[0].connection.operation_settings.embeddings.endpoint, "https://resource.example.test/openai/v1/");
    assert.deepEqual(foundry.staged()[0].connection.operation_settings.image_generation, endpoint.connection.operation_settings.image_generation);
});

test("embedding tests require saved bindings, validate dimensions, and never change defaults", async () => {
    const h = await createHarness(embeddingFixture());
    await h.open();
    const before = h.get("default_model_selection_json").value;
    const model = h.api.collectModalModels()[0];
    await h.api.testSavedOperationModel(model, "embeddings");
    assert.deepEqual(h.requests.at(-1).body, {
        test_type: "embedding",
        selection: { endpoint_id: "saved-endpoint", model_id: model.id, provider: "openai_compatible" }
    });
    assert.match(h.toasts.at(-1).message, /768 dimensions/);
    assert.match(h.toasts.at(-1).message, /No vectors were stored and the default was not changed/);
    assert.equal(h.get("default_model_selection_json").value, before);
    assert.equal(h.window.hasUnsavedAIConnectionEdits(), false);
    assert.equal(h.events.length, 0);
    h.rows()[0].querySelector('[data-config-key="dimensions"]').value = "1024";
    await h.rows()[0].querySelector('[data-config-key="dimensions"]').fire("input");
    const count = h.requests.length;
    await h.api.testSavedOperationModel(model, "embeddings");
    assert.equal(h.requests.length, count);
    assert.match(h.toasts.at(-1).message, /Save the connection first/);

    for (const dimensions of [0, -1, 1.5, "768", null]) {
        const invalid = await createHarness(embeddingFixture(), { operationResult: { success: true, dimensions } });
        await invalid.open();
        await invalid.api.testSavedOperationModel(invalid.api.collectModalModels()[0], "embeddings");
        assert.equal(invalid.toasts.at(-1).tone, "danger");
        assert.match(invalid.toasts.at(-1).message, /valid vector dimensions/);
    }
});
