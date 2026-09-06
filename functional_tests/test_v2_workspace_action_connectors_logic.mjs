// test_v2_workspace_action_connectors_logic.mjs
// Version: 0.261.096
// Implemented in: 0.261.096
// Executes the real OpenAPI/MCP connector parsing, draft, credential, and API helpers.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const {
    allowedMcpAuthMethods, allowedMcpTransports, applyMcpPreconfiguration, applyMcpPreset,
    applyOpenApiSpecification, availableConnectorIdentities, buildConnectorSupportPayload,
    changeConnectorAuthMethod, changeOpenApiBasicCredential, connectorAuthMethod, connectorFeedback,
    connectorIdentityOptions, connectorLines, connectorSecretField, connectorUrlError,
    discoverMcpAction, fetchMcpPreconfigurations, fetchMcpPresets, MCP_GENERIC_PRESET, OPENAPI_SOURCE_OPTIONS,
    mcpHeaderNameError, mcpImplementationFields, mcpToolChoices, mergeMcpTools,
    openApiBasicCredentials, openApiInformation, openApiSourceDraft, parseMcpCatalogue,
    parseMcpTools, processOpenApiText, renameMcpHeader, selectConnectorIdentity,
    setMcpToolSelection, STORED_CONNECTOR_SECRET, testApiConnector, updateConnectorFields,
    updateOpenApiSourceDraft, uploadOpenApiSpecification, validateApiConnector,
    validateConnectorAuthentication, validateConnectorConfiguration,
} = await import('../application/v2_ui/src/lib/workspaceActionConnectors.ts');
const { buildEditorWrite, EDITOR_SECRET_MASK } = await import('../application/v2_ui/src/lib/workspaceAuthoring.ts');
const { ApiError } = await import('../application/v2_ui/src/lib/apiClient.ts');

let checks = 0;
function check(label, run) {
    run();
    checks += 1;
    console.log(`ok ${label}`);
}
async function asyncCheck(label, run) {
    await run();
    checks += 1;
    console.log(`ok ${label}`);
}

const specification = {
    openapi: '3.0.3',
    info: { title: '<img src=x onerror=alert(1)>', version: '1', description: 'Synthetic API' },
    servers: [
        { url: 'https://{region}.example.test/v1', variables: { region: { default: 'api' } } },
    ],
    components: {
        parameters: { itemId: { name: 'id', in: 'path', required: true, schema: { type: 'string' } } },
        securitySchemes: {
            queryKey: { type: 'apiKey', in: 'query', name: 'api-key' },
            headerKey: { type: 'apiKey', in: 'header', name: 'X-API-Key' },
            cookieKey: { type: 'apiKey', in: 'cookie', name: 'session' },
            token: { type: 'http', scheme: 'bearer' },
            login: { type: 'http', scheme: 'basic' },
            oauth: { type: 'oauth2', flows: { clientCredentials: { scopes: { read: 'Read data' } } } },
            external: { $ref: 'https://untrusted.example.test/scheme.json' },
        },
    },
    security: [{ queryKey: [] }],
    paths: {
        '/items/{id}': {
            parameters: [{ $ref: '#/components/parameters/itemId' }],
            'x-description': { not: 'an operation' },
            get: {
                operationId: 'read_item', summary: 'Read an item', tags: ['items'],
                parameters: [{ name: 'id', in: 'path', required: true, schema: { type: 'integer' } }],
                responses: { 200: { description: 'OK' } },
            },
            patch: {
                operationId: 'update_item', deprecated: true, security: [],
                requestBody: { required: true, content: { 'application/json': { schema: { type: 'object' } } } },
                responses: { 204: { description: 'Updated' } },
            },
        },
        '/remote': { $ref: 'https://untrusted.example.test/path.json' },
    },
};

function action(type = 'openapi') {
    return {
        id: 'action-owned', name: 'saved-machine-name', displayName: 'Synthetic action',
        description: 'Connector regression fixture', type, endpoint: 'https://api.example.test',
        auth: { type: type === 'mcp' ? 'NoAuth' : 'key', key: '', customAuthFlag: false },
        additionalFields: type === 'mcp' ? {
            server_profile: 'generic', transport: 'streamable_http', auth_method: 'none',
            request_timeout: 30, connect_timeout: 10, sse_read_timeout: 300,
            retry_count: 0, retry_backoff_seconds: 1, load_tools: true, load_prompts: false,
            custom_headers: {}, allowed_tool_names: [], mcp_tools: [],
            custom: { keep: 0 },
        } : {
            openapi_spec_content: structuredClone(specification), openapi_source_type: 'content',
            base_url: 'https://api.example.test', auth_method: 'none', custom: { keep: 0 },
        },
        metadata: { custom: { enabled: false } },
    };
}
function resource(record, secret_paths = []) {
    return { record: structuredClone(record), revision: 'opaque-revision', secret_paths, read_only: false };
}
function catalogEntry(overrides = {}) {
    return {
        ...structuredClone(MCP_GENERIC_PRESET), ...overrides,
        defaults: { ...MCP_GENERIC_PRESET.defaults, ...overrides.defaults },
    };
}

check('OpenAPI information is readable and only HTTP operations are enumerated', () => {
    const info = openApiInformation(specification);
    assert.equal(info.title, specification.info.title);
    assert.equal(info.operations.length, 2);
    assert.equal(info.servers[0].url, 'https://api.example.test/v1');
    assert.equal(info.operations[0].parameters.length, 1);
    assert.equal(info.operations[0].parameters[0].type, 'integer');
    assert.deepEqual(info.operations[0].security, ['queryKey']);
    assert.deepEqual(info.operations[1].security, []);
    assert.equal(info.operations[1].bodyRequired, true);
    assert.deepEqual(info.operations[1].contentTypes, ['application/json']);
    assert.equal(info.operations[1].deprecated, true);
    assert.equal(info.securitySchemes.find(({ id }) => id === 'cookieKey').supported, false);
    assert.equal(info.securitySchemes.find(({ id }) => id === 'external').supported, false);
    assert.deepEqual(info.securitySchemes.find(({ id }) => id === 'oauth').scopes, ['read']);
});
check('local OpenAPI reference cycles stop without remote fetching or evaluation', () => {
    const info = openApiInformation({
        ...specification,
        paths: { '/cycle': { $ref: '#/paths/~1cycle' } },
    });
    assert.deepEqual(info.operations, []);
    assert.deepEqual(openApiInformation(null).operations, []);
});
check('import applies V1 content fields and preserves unrelated nested values', () => {
    const before = action();
    const next = applyOpenApiSpecification(before, { success: true, spec_content: specification, original_filename: 'source.yaml', file_id: 'f1' });
    assert.equal(next.additionalFields.openapi_source_type, 'content');
    assert.equal(next.additionalFields.base_url, before.endpoint);
    assert.deepEqual(next.additionalFields.custom, { keep: 0 });
    assert.deepEqual(next.auth, before.auth);
    assert.deepEqual(next.metadata, before.metadata);
    assert.equal(openApiSourceDraft(next).filename, 'source.yaml');
    assert.equal(before._openApiSourceDraft, undefined);
    assert.throws(() => applyOpenApiSpecification(before, { success: false, spec_content: specification }), /validated/);
    before.endpoint = '';
    delete before.additionalFields.base_url;
    assert.equal(applyOpenApiSpecification(before, { success: true, spec_content: specification }).endpoint, 'https://api.example.test/v1');
});
check('manual YAML stays in the in-memory draft and cannot bypass processing', () => {
    const before = action();
    const yaml = 'openapi: 3.0.3\ninfo:\n  title: Example\n  version: "1"\npaths: {}';
    const next = updateOpenApiSourceDraft(before, { mode: 'manual', format: 'yaml', text: yaml, pending: true });
    assert.equal(openApiSourceDraft(next).text, yaml);
    assert.deepEqual(next.additionalFields.openapi_spec_content, before.additionalFields.openapi_spec_content);
    assert.throws(() => buildConnectorSupportPayload(next, resource(before), 'openapi'), /Process the edited specification/);
    assert.ok(!('_openApiSourceDraft' in buildEditorWrite(next, resource(before)).updates));
    const processed = applyOpenApiSpecification(next, { success: true, spec_content: specification });
    assert.equal(openApiSourceDraft(processed).pending, false);
    assert.ok(!('_openApiSourceDraft' in buildConnectorSupportPayload(processed, resource(before), 'openapi')));
});
check('OpenAPI source choices stay upload/content-only and stale URL drafts cannot bypass processing', () => {
    assert.deepEqual(OPENAPI_SOURCE_OPTIONS.map(({ value }) => value), ['file', 'manual']);
    const before = action();
    const pending = {
        ...before,
        _openApiSourceDraft: { mode: 'url', url: 'https://specification.example.test/openapi.yaml', pending: true },
    };
    assert.equal(openApiSourceDraft(pending).mode, 'file');
    assert.deepEqual(pending.additionalFields.openapi_spec_content, before.additionalFields.openapi_spec_content);
    assert.throws(() => buildConnectorSupportPayload(pending, resource(before), 'openapi'), /Process the edited specification/);
    const imported = applyOpenApiSpecification(pending, { success: true, spec_content: specification });
    assert.equal(imported.additionalFields.openapi_source_type, 'content');
    assert.equal(openApiSourceDraft(imported).pending, false);
    assert.ok(!JSON.stringify(buildEditorWrite(imported, resource(before)).updates).includes('specification.example.test'));
});
check('auth method changes use V1 mappings without deleting hidden properties', () => {
    let draft = action();
    draft.auth.key = EDITOR_SECRET_MASK;
    draft.auth.hiddenCredential = 'retained';
    draft.additionalFields.future = { enabled: false, count: 0 };
    for (const method of ['api_key', 'bearer', 'basic', 'oauth2']) {
        const changed = changeConnectorAuthMethod(draft, 'openapi', method);
        assert.equal(changed.auth.type, 'key');
        assert.equal(changed.auth.key, EDITOR_SECRET_MASK);
        assert.equal(changed.additionalFields.auth_method, method);
        assert.equal(changed.auth.hiddenCredential, 'retained');
        assert.deepEqual(changed.additionalFields.future, { enabled: false, count: 0 });
    }
    draft = changeConnectorAuthMethod(draft, 'openapi', 'none');
    assert.equal(draft.auth.key, '');
    assert.equal(draft.auth.hiddenCredential, 'retained');
    assert.throws(() => changeConnectorAuthMethod(draft, 'mcp', 'oauth2'), /Unsupported/);
    assert.equal(changeConnectorAuthMethod(action('mcp'), 'mcp', 'none').auth.type, 'NoAuth');
});
check('legacy auth storage is recognized without rewriting old masks', () => {
    const draft = action();
    delete draft.additionalFields.auth_method;
    draft.auth = { type: 'api_key', value: EDITOR_SECRET_MASK, name: 'X-Test', location: 'query' };
    assert.equal(connectorAuthMethod(draft, 'openapi'), 'api_key');
    assert.equal(connectorSecretField(draft, 'openapi'), 'value');
    draft.auth = { type: 'bearer', token: EDITOR_SECRET_MASK };
    assert.equal(connectorSecretField(draft, 'openapi'), 'token');
    assert.equal(connectorAuthMethod(draft, 'openapi'), 'bearer');
    const anonymous = changeConnectorAuthMethod(draft, 'openapi', 'none');
    assert.equal(anonymous.auth.token, '');
    assert.equal(anonymous.auth.key, '');
    draft.auth = { type: 'api_key', value: EDITOR_SECRET_MASK, customFlag: 'retained' };
    const anonymousKey = changeConnectorAuthMethod(draft, 'openapi', 'none');
    assert.equal(anonymousKey.auth.value, '');
    assert.equal(anonymousKey.auth.customFlag, 'retained');
});
check('basic credentials preserve colons in passwords and require full replacement of a masked pair', () => {
    let draft = changeConnectorAuthMethod(action(), 'openapi', 'basic');
    draft.auth.key = 'synthetic-user:synthetic:password';
    assert.deepEqual(openApiBasicCredentials(draft), { username: 'synthetic-user', password: 'synthetic:password', stored: false });
    draft.auth.key = EDITOR_SECRET_MASK;
    const original = resource(draft, ['/auth/key']);
    assert.deepEqual(validateConnectorAuthentication(draft, 'openapi', original), {});
    let next = changeOpenApiBasicCredential(draft, 'username', 'replacement-user');
    assert.equal(next.auth.key, 'replacement-user:');
    assert.ok(validateConnectorAuthentication(next, 'openapi', original)['auth.key']);
    next = changeOpenApiBasicCredential(next, 'password', 'replacement:password');
    assert.equal(next.auth.key, 'replacement-user:replacement:password');
    assert.deepEqual(validateConnectorAuthentication(next, 'openapi', original), {});
    const passwordFirst = changeOpenApiBasicCredential(draft, 'password', 'replacement');
    assert.ok(validateConnectorAuthentication(passwordFirst, 'openapi', original)['auth.basic_username']);
    assert.equal(changeOpenApiBasicCredential(next, 'password', '').auth.key, '');
    assert.equal(changeOpenApiBasicCredential(next, 'password', EDITOR_SECRET_MASK).auth.key, EDITOR_SECRET_MASK);
});
check('reusable identities are filtered by capability and selected only by stable ID', () => {
    const identities = [
        { id: 'a', name: 'Same name', auth_type: 'api_key', credentials: { key: 'not-for-copying' } },
        { id: 'b', name: 'Same name', auth_type: 'bearer_token' },
        { id: 'c', name: 'Managed', auth_type: 'managed_identity' },
        { id: 'd', name: 'Unsupported', auth_type: 'client_secret' },
    ];
    assert.deepEqual(availableConnectorIdentities(identities, 'openapi').map(({ id }) => id), ['a', 'b']);
    assert.deepEqual(availableConnectorIdentities(identities, 'mcp').map(({ id }) => id), ['a', 'b', 'c']);
    const draft = action();
    draft.auth.key = EDITOR_SECRET_MASK;
    const next = selectConnectorIdentity(draft, 'openapi', identities[1]);
    assert.equal(next.identity_id, 'b');
    assert.equal(next.auth.identity, 'b');
    assert.equal(next.auth.type, 'identity');
    assert.equal(next.auth.key, EDITOR_SECRET_MASK);
    assert.equal(next.additionalFields.identity_auth_type, 'bearer_token');
    assert.ok(!JSON.stringify(next).includes('not-for-copying'));
    assert.equal(connectorIdentityOptions(identities, 'openapi', 'missing-id').unavailable, true);
    assert.equal(connectorIdentityOptions(identities, 'openapi', 'c').unavailable, true);
    assert.throws(() => selectConnectorIdentity(draft, 'openapi', identities[2]), /cannot authenticate/);
    const cleared = selectConnectorIdentity(next, 'openapi', null);
    assert.equal(cleared.identity_id, '');
    assert.equal(cleared.additionalFields.auth_method, 'none');
    assert.equal(cleared.additionalFields.identity_auth_type, undefined);
    assert.deepEqual(cleared.additionalFields.custom, { keep: 0 });
    const mcp = selectConnectorIdentity(action('mcp'), 'mcp', identities[0]);
    mcp.additionalFields.api_key_header_name = '';
    assert.ok(validateConnectorAuthentication(mcp, 'mcp', null)['additionalFields.api_key_header_name']);
});
check('clearing key names and unsupported URL schemes produce real validation errors', () => {
    for (const url of ['javascript:alert(1)', 'https://user:password@example.test', '/relative', 'https://example.test/#fragment']) {
        assert.ok(connectorUrlError(url));
    }
    assert.equal(connectorUrlError('https://example.test/mcp'), null);
    assert.equal(connectorUrlError('wss://example.test/mcp', true), null);
    assert.ok(connectorUrlError('https://example.test/mcp', true));
    const draft = changeConnectorAuthMethod(action(), 'openapi', 'api_key');
    draft.auth.key = 'synthetic-key';
    draft.additionalFields.api_key_name = '';
    assert.ok(validateConnectorAuthentication(draft, 'openapi', null)['additionalFields.api_key_name']);
});
check('catalogue wrappers are parsed while failures and duplicate IDs are not empty success', () => {
    const entry = catalogEntry();
    for (const payload of [[entry], { presets: [entry] }, { data: { presets: [entry] } }, { data: [entry] }]) {
        assert.equal(parseMcpCatalogue(payload, 'presets')[0].id, 'generic');
    }
    assert.equal(parseMcpCatalogue({ preconfigurations: [] }, 'preconfigurations').length, 0);
    assert.throws(() => parseMcpCatalogue({ error: 'denied' }, 'presets'), /invalid/);
    assert.throws(() => parseMcpCatalogue({ presets: [{ label: 'Missing ID' }] }, 'presets'), /invalid entry/);
    assert.throws(() => parseMcpCatalogue({ presets: [entry, entry] }, 'presets'), /duplicate/);
});
check('personal transport choices never include stdio even if a preset permits it', () => {
    assert.deepEqual(allowedMcpTransports().map(({ value }) => value), ['streamable_http', 'sse', 'websocket']);
    assert.deepEqual(allowedMcpTransports(catalogEntry({ constraints: { allowedTransports: ['stdio', 'sse'] } })).map(({ value }) => value), ['sse']);
    assert.deepEqual(allowedMcpTransports(catalogEntry({ constraints: { allowedTransports: ['stdio'] } })), []);
    assert.equal(applyMcpPreset(action('mcp'), catalogEntry({ defaults: { transport: 'stdio' } })).additionalFields.transport, 'streamable_http');
    assert.throws(() => applyMcpPreset(action('mcp'), catalogEntry({ constraints: { allowedTransports: ['stdio'] } })), /no transport/);
    assert.throws(() => applyMcpPreconfiguration(action('mcp'), catalogEntry({ transport: 'stdio' })), /cannot use stdio/);
    assert.throws(() => applyMcpPreconfiguration(action('mcp'), catalogEntry({ scopeEligibility: ['global'] })), /not available/);
    assert.deepEqual(allowedMcpAuthMethods('websocket').map(({ value }) => value), ['none']);
});
check('preset application preserves false, zero, secret masks and unknown tool selections', () => {
    const draft = action('mcp');
    draft.additionalFields.allowed_tool_names = ['unavailable-tool'];
    draft.additionalFields.custom_headers = { 'X-Stored': EDITOR_SECRET_MASK };
    const next = applyMcpPreset(draft, catalogEntry({
        id: 'custom',
        defaults: {
            load_tools: false, load_prompts: false, retry_count: 0, validate_tool_arguments: false,
            custom_headers: { 'X-Stored': 'never-overwrite-a-mask' }, allowed_tool_names: ['new-tool'],
        },
    }));
    assert.equal(next.additionalFields.load_tools, false);
    assert.equal(next.additionalFields.retry_count, 0);
    assert.equal(next.additionalFields.custom_headers['X-Stored'], EDITOR_SECRET_MASK);
    assert.deepEqual(next.additionalFields.allowed_tool_names, ['unavailable-tool', 'new-tool']);
    assert.deepEqual(next.additionalFields.custom, { keep: 0 });
    assert.equal(draft.additionalFields.server_profile, 'generic');
});
check('preconfiguration settings apply explicitly without copying identity secrets or erasing unknown settings', () => {
    const draft = selectConnectorIdentity(action('mcp'), 'mcp', { id: 'identity-a', name: 'A', auth_type: 'managed_identity' });
    draft.additionalFields.implementation = { id: 'generic', schemaVersion: '1.0.0', customVersionNote: 'keep' };
    draft.additionalFields.additionalSettings = { compatibilityProfile: 'standards_compliant', customSetting: { enabled: false } };
    draft.additionalFields.allowed_tool_names = ['unknown-old-tool'];
    const next = applyMcpPreconfiguration(draft, catalogEntry({
        id: 'azure_mcp_server', presetId: 'generic', transport: 'streamable_http',
        endpoint: 'https://azure.example.test/mcp',
        implementation: { id: 'azure_mcp_server', schemaVersion: '1.0.0' },
        additionalSettings: {
            defaultAccessMode: 'read_only', localCommandExecution: false,
            organizationHostedRemoteRequired: true, serviceNamespaces: ['Azure.ResourceGroups'],
        },
        defaults: { load_tools: false, retry_count: 0, auth_method: 'identity' },
    }));
    assert.equal(next.endpoint, 'https://azure.example.test/mcp');
    assert.equal(next.identity_id, 'identity-a');
    assert.equal(next.additionalFields.identity_auth_type, 'managed_identity');
    assert.equal(next.additionalFields.auth_method, 'identity');
    assert.equal(next.additionalFields.additionalSettings.localCommandExecution, false);
    assert.deepEqual(next.additionalFields.additionalSettings.customSetting, { enabled: false });
    assert.equal(next.additionalFields.additionalSettings.compatibilityProfile, undefined);
    assert.equal(next.additionalFields.implementation.customVersionNote, 'keep');
    assert.deepEqual(next.additionalFields.allowed_tool_names, ['unknown-old-tool']);
    assert.equal(next.additionalFields.load_tools, false);
    assert.deepEqual(validateConnectorConfiguration(next, 'mcp'), {});
});
check('implementation safety constants and selected references are validated without deleting them', () => {
    const draft = action('mcp');
    draft.additionalFields.implementation = { id: 'azure_mcp_server', schemaVersion: '1.0.0' };
    draft.additionalFields.additionalSettings = {
        defaultAccessMode: 'read_only', localCommandExecution: true,
        organizationHostedRemoteRequired: true, serviceNamespaces: ['invalid namespace'],
    };
    const errors = validateConnectorConfiguration(draft, 'mcp');
    assert.ok(errors['additionalFields.additionalSettings.localCommandExecution']);
    assert.ok(errors['additionalFields.additionalSettings.serviceNamespaces']);
    assert.equal(draft.additionalFields.additionalSettings.localCommandExecution, true);
    assert.deepEqual(mcpImplementationFields('constructor'), []);
    assert.deepEqual(mcpImplementationFields('__proto__'), []);
});
check('MCP native limits distinguish zero, false, invalid strings, and deliberate empty collections', () => {
    const draft = action('mcp');
    draft.additionalFields.load_tools = false;
    assert.deepEqual(validateConnectorConfiguration(draft, 'mcp'), {});
    draft.additionalFields.request_timeout = 0;
    draft.additionalFields.retry_count = 0.5;
    draft.additionalFields.load_prompts = 'false';
    draft.additionalFields.allowed_tool_names = [1];
    draft.additionalFields.mcp_tools = {};
    const errors = validateConnectorConfiguration(draft, 'mcp');
    for (const field of ['request_timeout', 'retry_count', 'load_prompts', 'allowed_tool_names', 'mcp_tools']) {
        assert.ok(errors[`additionalFields.${field}`], field);
    }
});
check('custom header controls reject reserved names, duplicates, line breaks and masked renames', () => {
    for (const name of ['Host', 'Cookie', 'Connection', 'Content-Length', 'Bad Name', '']) assert.ok(mcpHeaderNameError(name));
    assert.ok(mcpHeaderNameError('x-test', { 'X-Test': '' }));
    assert.equal(mcpHeaderNameError('X-Custom'), null);
    const draft = action('mcp');
    draft.additionalFields.custom_headers = { 'X-Stored': EDITOR_SECRET_MASK, 'X-Plain': 'synthetic' };
    assert.throws(() => renameMcpHeader(draft, 'X-Stored', 'X-Renamed'), /Replace the stored/);
    const renamed = renameMcpHeader(draft, 'X-Plain', 'X-Renamed');
    assert.equal(renamed.additionalFields.custom_headers['X-Renamed'], 'synthetic');
    assert.equal(renamed.additionalFields.custom_headers['X-Stored'], EDITOR_SECRET_MASK);
    draft.additionalFields.custom_headers['X-Plain'] = 'line\r\nbreak';
    assert.ok(validateConnectorConfiguration(draft, 'mcp')['additionalFields.custom_headers.X-Plain']);
    draft.additionalFields.transport = 'websocket';
    draft.endpoint = 'wss://example.test/mcp';
    assert.ok(validateConnectorConfiguration(draft, 'mcp')['additionalFields.custom_headers']);
});
check('discovery merges tool metadata while retaining unavailable selected tool names', () => {
    const old = [
        { original_name: 'known', function_name: 'oldKnown', description: 'Old', customMetadata: { keep: true } },
        { original_name: 'missing', function_name: 'missing', description: 'Stored missing tool' },
        { original_name: 'unselected-old', function_name: 'old' },
    ];
    const discovered = [{ original_name: 'known', function_name: 'known', description: 'Updated', input_schema: { type: 'object' } }];
    const merged = mergeMcpTools(old, discovered, ['known', 'missing', 'no-metadata']);
    assert.equal(merged.length, 2);
    assert.equal(merged[0].description, 'Updated');
    assert.deepEqual(merged[0].customMetadata, { keep: true });
    const choices = mcpToolChoices(merged, ['known', 'missing', 'no-metadata'], ['known']);
    assert.equal(choices.find(({ name }) => name === 'missing').unavailable, true);
    assert.equal(choices.find(({ name }) => name === 'no-metadata').selected, true);
    let draft = action('mcp');
    draft.additionalFields.allowed_tool_names = ['missing', 'no-metadata'];
    draft = setMcpToolSelection(draft, 'known', true);
    assert.deepEqual(draft.additionalFields.allowed_tool_names, ['missing', 'no-metadata', 'known']);
    draft = setMcpToolSelection(draft, 'missing', false);
    assert.deepEqual(draft.additionalFields.allowed_tool_names, ['no-metadata', 'known']);
    assert.deepEqual(connectorLines('one\r\ntwo\none\n\n'), ['one', 'two']);
    assert.equal(parseMcpTools([{ name: 'legacy', inputSchema: { type: 'object' } }])[0].original_name, 'legacy');
});
check('support payloads bind stored credentials to original user scope and stable identity', () => {
    const draft = changeConnectorAuthMethod(action(), 'openapi', 'bearer');
    draft.auth.key = EDITOR_SECRET_MASK;
    draft.auth.tenantId = EDITOR_SECRET_MASK;
    draft.additionalFields.customSecret = EDITOR_SECRET_MASK;
    const original = resource(draft, ['/auth/key', '/auth/tenantId', '/additionalFields/customSecret']);
    draft.id = 'unsaved-id';
    draft.name = 'renamed-machine-name';
    draft.auth.tenantId = '';
    const payload = buildConnectorSupportPayload(draft, original, 'openapi');
    assert.deepEqual(payload.plugin_context, { scope: 'personal', id: 'action-owned', name: 'saved-machine-name' });
    assert.equal(payload.action_scope, 'personal');
    assert.equal(payload.auth.key, STORED_CONNECTOR_SECRET);
    assert.equal(payload.auth.tenantId, undefined);
    assert.equal(payload.additionalFields.customSecret, STORED_CONNECTOR_SECRET);
    assert.ok(payload.clear_secret_paths.includes('/auth/tenantId'));
    assert.equal(original.record.auth.key, EDITOR_SECRET_MASK);
    assert.ok(!JSON.stringify(payload).includes(EDITOR_SECRET_MASK));
});
check('API-key identities retain native header/query placement and do not test inactive credentials', () => {
    const before = action();
    before.auth.key = EDITOR_SECRET_MASK;
    const original = resource(before, ['/auth/key']);
    const identity = { id: 'identity-key', name: 'API identity', auth_type: 'api_key' };
    let selected = selectConnectorIdentity(before, 'openapi', identity);
    assert.equal(selected.additionalFields.api_key_location, 'header');
    assert.equal(selected.additionalFields.api_key_name, 'X-API-Key');
    selected = updateConnectorFields(selected, { api_key_location: 'query', api_key_name: 'subscription-key' });
    assert.deepEqual(validateConnectorAuthentication(selected, 'openapi', original), {});
    const payload = buildConnectorSupportPayload(selected, original, 'openapi');
    assert.deepEqual(payload.auth, { type: 'identity', identity: identity.id });
    assert.equal(payload.additionalFields.api_key_location, 'query');
    assert.equal(payload.additionalFields.api_key_name, 'subscription-key');
    assert.equal(selected.auth.key, EDITOR_SECRET_MASK);
    assert.ok(validateConnectorAuthentication(updateConnectorFields(selected, { api_key_name: '' }), 'openapi', original)['additionalFields.api_key_name']);
    assert.ok(validateConnectorAuthentication(updateConnectorFields(selected, { api_key_location: 'cookie' }), 'openapi', original)['additionalFields.api_key_location']);
    assert.equal(selectConnectorIdentity(selected, 'openapi', identity).additionalFields.api_key_name, 'subscription-key');
});
check('literal masks in ordinary text are not secret references and nested secret pointers are supported', () => {
    const draft = action('mcp');
    draft.description = EDITOR_SECRET_MASK;
    draft.additionalFields.custom_headers = { 'X-Scoped': EDITOR_SECRET_MASK };
    draft.additionalFields.items = [{ 'a/b~token': EDITOR_SECRET_MASK }];
    const original = resource(draft, ['/additionalFields/custom_headers/X-Scoped', '/additionalFields/items/0/a~1b~0token']);
    const payload = buildConnectorSupportPayload(draft, original, 'mcp', 'discover');
    assert.equal(payload.description, EDITOR_SECRET_MASK);
    assert.equal(payload.additionalFields.items[0]['a/b~token'], STORED_CONNECTOR_SECRET);
    assert.equal(payload.additionalFields.custom_headers['X-Scoped'], STORED_CONNECTOR_SECRET);
});
check('intentional auth clears never fall back to stored credentials for tests', () => {
    let draft = changeConnectorAuthMethod(action(), 'openapi', 'bearer');
    draft.auth.key = EDITOR_SECRET_MASK;
    const original = resource(draft, ['/auth/key']);
    draft.auth.key = '';
    assert.throws(() => buildConnectorSupportPayload(draft, original, 'openapi'), /Cleared credentials/);
    draft = changeConnectorAuthMethod(draft, 'openapi', 'none');
    const payload = buildConnectorSupportPayload(draft, original, 'openapi');
    assert.deepEqual(payload.auth, { type: 'key', key: '' });
    assert.ok(payload.clear_secret_paths.includes('/auth/key'));
    assert.ok(!JSON.stringify(payload).includes(STORED_CONNECTOR_SECRET));
});
check('cleared and removed custom headers are omitted rather than rehydrated', () => {
    const draft = action('mcp');
    draft.additionalFields.custom_headers = { 'X-Keep': EDITOR_SECRET_MASK, 'X-Clear': EDITOR_SECRET_MASK, 'X-Remove': EDITOR_SECRET_MASK };
    const original = resource(draft, Object.keys(draft.additionalFields.custom_headers).map((name) => `/additionalFields/custom_headers/${name}`));
    draft.additionalFields.custom_headers['X-Clear'] = '';
    delete draft.additionalFields.custom_headers['X-Remove'];
    draft.additionalFields.custom_headers['X-New-Empty'] = '';
    const payload = buildConnectorSupportPayload(draft, original, 'mcp', 'discover');
    assert.deepEqual(payload.additionalFields.custom_headers, { 'X-Keep': STORED_CONNECTOR_SECRET });
    assert.ok(payload.clear_secret_paths.includes('/additionalFields/custom_headers/X-Clear'));
    assert.ok(payload.clear_secret_paths.includes('/additionalFields/custom_headers/X-Remove'));
    assert.equal(draft.additionalFields.custom_headers['X-Clear'], '');
});
check('new or foreign masks and read-only resources cannot be used to run a connector', () => {
    const draft = changeConnectorAuthMethod(action(), 'openapi', 'bearer');
    draft.auth.key = EDITOR_SECRET_MASK;
    assert.throws(() => buildConnectorSupportPayload(draft, null, 'openapi'), /credential/);
    const original = resource(draft, ['/auth/key']);
    original.read_only = true;
    assert.throws(() => buildConnectorSupportPayload(draft, original, 'openapi'), /read-only/);
    const mcp = action('mcp');
    mcp.additionalFields.custom_headers = { 'X-Foreign': EDITOR_SECRET_MASK };
    assert.throws(() => buildConnectorSupportPayload(mcp, null, 'mcp'), /owned record/);
    mcp.additionalFields.custom_headers = {};
    mcp.additionalFields.futureSecret = EDITOR_SECRET_MASK;
    assert.throws(() => buildConnectorSupportPayload(mcp, null, 'mcp'), /owned record/);
});
check('legacy Stored_In_KeyVault markers remain bound to an owned stored path', () => {
    const draft = changeConnectorAuthMethod(action(), 'openapi', 'bearer');
    draft.auth.key = STORED_CONNECTOR_SECRET;
    const original = resource(draft, ['/auth/key']);
    assert.equal(buildConnectorSupportPayload(draft, original, 'openapi').auth.key, STORED_CONNECTOR_SECRET);
    assert.throws(() => buildConnectorSupportPayload(draft, null, 'openapi'), /credential/);
});
check('failure feedback retains server warnings, field errors, and false/zero details', () => {
    const feedback = connectorFeedback(new ApiError('Denied', 403, {
        error: 'Governance denied the destination', errors: ['Review allowlist'], warnings: ['Tools remain disabled'],
        details: { retry_count: 0, active: false },
    }));
    assert.equal(feedback.success, false);
    assert.deepEqual(feedback.errors, ['Review allowlist']);
    assert.deepEqual(feedback.warnings, ['Tools remain disabled']);
    assert.deepEqual(feedback.details, { retry_count: 0, active: false });
});

const actualFetch = globalThis.fetch;
const requests = [];
let responseBody = { success: true };
let responseStatus = 200;
globalThis.fetch = async (url, init = {}) => {
    requests.push({
        url, ...init,
        body: typeof init.body === 'string' ? JSON.parse(init.body) : init.body,
    });
    if (init.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    return new Response(JSON.stringify(responseBody), {
        status: responseStatus, headers: { 'Content-Type': 'application/json' },
    });
};
try {
    await asyncCheck('configuration, identity, preset and tool selection never execute a connector', async () => {
        const count = requests.length;
        applyMcpPreset(action('mcp'), catalogEntry());
        selectConnectorIdentity(action(), 'openapi', { id: 'a', name: 'A', auth_type: 'api_key' });
        changeConnectorAuthMethod(action(), 'openapi', 'api_key');
        setMcpToolSelection(action('mcp'), 'known-tool', true);
        assert.equal(requests.length, count);
    });
    await asyncCheck('catalogue reads use the existing personal endpoints and pass abort signals', async () => {
        const controller = new AbortController();
        responseBody = { presets: [catalogEntry()] };
        assert.equal((await fetchMcpPresets(controller.signal)).length, 1);
        assert.equal(requests.at(-1).url, '/api/plugins/mcp/presets');
        assert.equal(requests.at(-1).signal, controller.signal);
        responseBody = { scope: 'personal', preconfigurations: [] };
        assert.deepEqual(await fetchMcpPreconfigurations(controller.signal), []);
        assert.equal(requests.at(-1).url, '/api/plugins/mcp/preconfigurations?scope=personal');
        assert.equal(requests.at(-1).credentials, 'same-origin');
    });
    await asyncCheck('file and manual YAML imports go through authenticated multipart canonical upload', async () => {
        responseBody = { success: true, file_id: 'file-1', original_filename: 'input.json', spec_content: specification };
        const controller = new AbortController();
        await uploadOpenApiSpecification(new File([JSON.stringify(specification)], 'input.json'), undefined, controller.signal);
        let call = requests.at(-1);
        assert.equal(call.url, '/api/openapi/upload');
        assert.equal(call.method, 'POST');
        assert.equal(call.credentials, 'same-origin');
        assert.equal(call.signal, controller.signal);
        assert.ok(call.body instanceof FormData);
        assert.equal(call.body.get('file').name, 'input.json');
        assert.deepEqual(JSON.parse(await call.body.get('file').text()), specification);
        const yaml = 'openapi: 3.0.3\ninfo: { title: Example, version: "1" }\npaths: {}';
        await processOpenApiText(yaml, 'yaml');
        call = requests.at(-1);
        assert.equal(call.url, '/api/openapi/upload');
        assert.equal(call.body.get('file').name, 'openapi.yaml');
        assert.equal(await call.body.get('file').text(), yaml);
        assert.ok(requests.every(({ url }) => url.startsWith('/api/')));
    });
    await asyncCheck('invalid uploads fail without additional requests or changing existing content', async () => {
        const count = requests.length;
        await assert.rejects(uploadOpenApiSpecification(new File(['no'], 'bad.exe')), /Choose a/);
        await assert.rejects(uploadOpenApiSpecification(new File([], 'empty.json')), /empty/);
        await assert.rejects(uploadOpenApiSpecification(new Blob([new Uint8Array(5 * 1024 * 1024 + 1)]), 'large.json'), /5 MB/);
        assert.equal(requests.length, count);
        responseBody = { success: false, error: 'Validation rejected this specification' };
        await assert.rejects(processOpenApiText('invalid: yaml', 'yaml'), /Validation rejected/);
        responseBody = { success: true, spec_content: 'not an object' };
        await assert.rejects(processOpenApiText('{}', 'json'), /validated OpenAPI/);
    });
    await asyncCheck('manual JSON processing uses multipart content, never a remote-specification request', async () => {
        responseBody = { success: true, file_id: 'manual-file', original_filename: 'openapi.json', spec_content: specification };
        const signal = new AbortController().signal;
        const count = requests.length;
        const result = await processOpenApiText(JSON.stringify(specification), 'json', signal);
        const call = requests.at(-1);
        assert.equal(call.url, '/api/openapi/upload');
        assert.equal(call.method, 'POST');
        assert.equal(call.signal, signal);
        assert.ok(call.body instanceof FormData);
        assert.equal(call.body.has('url'), false);
        assert.equal(call.body.get('file').name, 'openapi.json');
        assert.deepEqual(JSON.parse(await call.body.get('file').text()), specification);
        assert.deepEqual(result.spec_content, specification);
        assert.equal(requests.length, count + 1);
        assert.ok(requests.every(({ url }) => String(url).startsWith('/api/')));
    });
    await asyncCheck('OpenAPI testing sends the full edited manifest and the original owned context', async () => {
        const draft = changeConnectorAuthMethod(action(), 'openapi', 'bearer');
        draft.auth.key = EDITOR_SECRET_MASK;
        const original = resource(draft, ['/auth/key']);
        draft.name = 'new-name';
        responseBody = { success: true, message: 'Probe succeeded', details: { operation_count: 2 } };
        const controller = new AbortController();
        await testApiConnector(draft, original, 'openapi', controller.signal);
        const call = requests.at(-1);
        assert.equal(call.url, '/api/plugins/test-openapi-connection');
        assert.deepEqual(call.body.plugin_context, { scope: 'personal', id: 'action-owned', name: 'saved-machine-name' });
        assert.equal(call.body.auth.key, STORED_CONNECTOR_SECRET);
        assert.equal(call.body.action_scope, 'personal');
        assert.equal(call.signal, controller.signal);
        assert.deepEqual(call.body.additionalFields.custom, { keep: 0 });
        const count = requests.length;
        draft.auth.key = '';
        await assert.rejects(async () => testApiConnector(draft, original, 'openapi'), /Cleared credentials/);
        assert.equal(requests.length, count);
    });
    await asyncCheck('MCP discovery and testing are separate explicit requests with edit-time credentials', async () => {
        const draft = changeConnectorAuthMethod(action('mcp'), 'mcp', 'basic');
        draft.auth.key = EDITOR_SECRET_MASK;
        draft.auth.identity = EDITOR_SECRET_MASK;
        const original = resource(draft, ['/auth/key', '/auth/identity']);
        responseBody = {
            success: true, tools: [{ original_name: 'known', function_name: 'known' }],
            capabilities: { tools: true, prompts_requested: false }, warnings: ['Review mutating tools', { untrusted: 'not a string' }],
        };
        const result = await discoverMcpAction(draft, original);
        let call = requests.at(-1);
        assert.equal(call.url, '/api/plugins/mcp/discover');
        assert.equal(call.body.auth.key, STORED_CONNECTOR_SECRET);
        assert.equal(call.body.auth.identity, STORED_CONNECTOR_SECRET);
        assert.equal(call.body.action_scope, 'personal');
        assert.equal(call.body.plugin_context.scope, 'personal');
        assert.deepEqual(result.warnings, ['Review mutating tools']);
        responseBody = { success: true, message: 'Connected' };
        await testApiConnector(draft, original, 'mcp');
        call = requests.at(-1);
        assert.equal(call.url, '/api/plugins/test-mcp-connection');
        assert.equal(call.body.auth.identity, STORED_CONNECTOR_SECRET);
        const count = requests.length;
        original.read_only = true;
        await assert.rejects(async () => discoverMcpAction(draft, original), /read-only/);
        assert.equal(requests.length, count);
    });
    await asyncCheck('canonical validation never calls a test endpoint and retains server errors', async () => {
        responseBody = { valid: false, errors: ['Canonical schema validation error'], warnings: [] };
        const result = await validateApiConnector(action(), null, 'openapi');
        const call = requests.at(-1);
        assert.equal(call.url, '/api/plugins/validate');
        assert.equal(call.body.type, 'openapi');
        assert.equal(call.body.plugin_context, undefined);
        assert.equal(connectorFeedback(result).success, false);
        assert.deepEqual(connectorFeedback(result).errors, ['Canonical schema validation error']);
    });
    await asyncCheck('failed or malformed discovery remains a failure, and abort signals are forwarded', async () => {
        responseStatus = 403;
        responseBody = { error: 'Destination denied', warnings: ['Check governance'] };
        await assert.rejects(discoverMcpAction(action('mcp'), null), (error) => {
            assert.equal(connectorFeedback(error).message, 'Destination denied');
            assert.deepEqual(connectorFeedback(error).warnings, ['Check governance']);
            return true;
        });
        responseStatus = 200;
        responseBody = { success: true };
        await assert.rejects(discoverMcpAction(action('mcp'), null), /invalid MCP tool catalogue/);
        responseBody = { success: true, tools: [{ invalid: 'tool metadata' }] };
        await assert.rejects(discoverMcpAction(action('mcp'), null), /invalid MCP tool catalogue/);
        const controller = new AbortController();
        controller.abort();
        await assert.rejects(fetchMcpPresets(controller.signal), { name: 'AbortError' });
    });
} finally {
    globalThis.fetch = actualFetch;
}

console.log(`${checks} OpenAPI/MCP connector logic checks passed.`);
