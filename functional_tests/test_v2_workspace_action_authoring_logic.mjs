// test_v2_workspace_action_authoring_logic.mjs
// Version: 0.261.096
// Implemented in: 0.261.096
// Executes the real native registry, schema/defaults, draft, identity, and connector API logic.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import ts from '../application/v2_ui/node_modules/typescript/lib/typescript.js';
import './test_support/tsResolve.mjs';

const {
    actionApiErrors, actionArrayRemovalError, actionAuthMethod, actionAuthModes, actionCanEdit, actionDetailPath,
    actionFieldError, actionForSave, actionHasStoredArraySecrets,
    actionResourceKey, actionSchemaDefaults, actionScope, actionTypeLabel, actionValueAt,
    changeActionAuth, changeActionDisplayName, changeActionField, changeActionType,
    changeSqlConnectionMethod, createActionDraft, deriveBlobEndpoint, displayedActionValue, expandActionFieldErrors, filterAuthoringActions,
    hasUsableActionRevision, resolveActionSchema, selectActionIdentity, validateActionDraft, validateActionSchema, withActionValue,
} = await import('../application/v2_ui/src/lib/workspaceActionLogic.ts');
const {
    BLOB_ACTION_CAPABILITIES, NATIVE_ACTION_TYPES, nativeActionDefinition, sqlConnectionMethod, usesDirectBlobConnectionString,
} = await import('../application/v2_ui/src/lib/workspaceActionRegistry.ts');
const {
    buildActionConnectionPayload, fetchActionEditorHints, fetchActionIdentities, testWorkspaceAction, validateWorkspaceAction,
} = await import('../application/v2_ui/src/lib/workspaceActionServices.ts');
const {
    buildEditorWrite, EDITOR_SECRET_MASK,
} = await import('../application/v2_ui/src/lib/workspaceAuthoring.ts');
const { ApiError } = await import('../application/v2_ui/src/lib/apiClient.ts');
const { fetchActionEditor, fetchAuthoringActions } = await import('../application/v2_ui/src/lib/workspaceAuthoringApi.ts');
const {
    applyOpenApiSpecification, validateConnectorAuthentication, validateConnectorConfiguration,
} = await import('../application/v2_ui/src/lib/workspaceActionConnectors.ts');

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const schemas = path.join(root, 'application', 'single_app', 'static', 'json', 'schemas');
const baseAuth = JSON.parse(fs.readFileSync(path.join(schemas, 'plugin.schema.json'), 'utf8')).definitions.AuthType.enum;
const readSchema = (name) => {
    const location = path.join(schemas, name);
    return fs.existsSync(location) ? JSON.parse(fs.readFileSync(location, 'utf8')) : {};
};
function definition(type, extra = {}) {
    const normalized = type.replace(/[^a-zA-Z0-9_]/g, '_').toLowerCase();
    return {
        type, display: actionTypeLabel(type), description: `Fixture for ${type}`,
        allowed_auth_types: readSchema(`${normalized}.definition.json`).allowedAuthTypes || baseAuth,
        additional_fields_schema: readSchema(`${normalized}_plugin.additional_settings.schema.json`),
        metadata_schema: readSchema(`${normalized}_plugin.metadata.schema.json`),
        ...extra,
    };
}
function action(type = 'sql_query') {
    let result = changeActionType(createActionDraft(), definition(type));
    result = { ...result, id: `owned-${type}`, name: `test_${type}`, displayName: `Test ${type}`, description: 'A synthetic action.' };
    for (const descriptor of nativeActionDefinition(type).fields) {
        if (!descriptor.required || descriptor.visible && !descriptor.visible(result)) continue;
        const existing = actionValueAt(result, descriptor.path);
        if (existing !== undefined && existing !== '') continue;
        const value = descriptor.kind === 'select' ? descriptor.options[0].value :
            descriptor.kind === 'number' ? descriptor.min ?? 1 :
                descriptor.path === '/endpoint' ? 'https://connector.example.test' :
                    descriptor.path.endsWith('partition_key_path') ? '/tenantId' : 'fixture';
        result = changeActionField(result, descriptor.path, value);
    }
    if (type === 'agent') result.additionalFields.target_agent = { id: 'target-1', scope_type: 'personal', scope_id: 'user-fixture' };
    if (type === 'sql_query' || type === 'sql_schema') {
        result.additionalFields.username = 'fixture-user';
        result.additionalFields.password = 'fixture-password';
    }
    if (['key', 'connection_string', 'username_password', 'servicePrincipal', 'basic'].includes(result.auth.type)) result.auth.key = 'fixture-secret';
    if (['username_password', 'servicePrincipal', 'basic'].includes(result.auth.type)) result.auth.identity = 'fixture-user';
    if (result.auth.type === 'servicePrincipal') result.auth.tenantId = 'fixture-tenant';
    if (type === 'tableau') {
        result.auth.identity = 'fixture-token-name';
        result.additionalFields.pat_name = 'fixture-token-name';
    }
    if (type === 'snowflake') result.additionalFields.user = result.auth.identity;
    if (type === 'blob_storage') {
        result.auth.key = 'AccountName=fixtureaccount;AccountKey=fixture-key;EndpointSuffix=core.windows.net';
        result.endpoint = deriveBlobEndpoint(result.auth.key);
    }
    if (type === 'ui_test') {
        result.additionalFields.string = 'fixture';
        result.additionalFields.string__Secret = 'fixture-secret';
        result.additionalFields.enum = 'bob';
    }
    return result;
}
function resource(record, secret_paths = []) {
    return { record: structuredClone(record), revision: 'opaque-fixture-revision', secret_paths, read_only: false };
}
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

check('native registry covers every shipped action module, not a small creation whitelist', () => {
    const pluginDirectory = path.join(root, 'application', 'single_app', 'semantic_kernel_plugins');
    const shipped = fs.readdirSync(pluginDirectory).filter((name) => name.endsWith('_plugin.py') && name !== 'base_plugin.py');
    for (const filename of shipped) assert.ok(NATIVE_ACTION_TYPES[filename.replace('_plugin.py', '')], filename);
    assert.ok(shipped.length >= 29);
});

check('all current native types support an immutable edit round trip without losing unknown fields', () => {
    for (const type of Object.keys(NATIVE_ACTION_TYPES)) {
        const original = action(type);
        original.additionalFields.future_settings = { enabled: false, retries: 0, list: [] };
        original.metadata.future_metadata = { enabled: false, value: '' };
        original.future_root = { preserved: true };
        const before = resource(original);
        const edited = { ...structuredClone(original), description: 'Updated description.' };
        const write = buildEditorWrite(actionForSave(edited), before);
        assert.deepEqual(write.updates, { description: 'Updated description.' }, `${type}: unexpected unrelated edits`);
        assert.deepEqual(write.clear_secret_paths, []);
        assert.deepEqual(write.removed_paths, []);
        assert.deepEqual(before.record, original, `${type}: original mutated`);
    }
});

check('every native descriptor family produces a valid configured draft using the canonical schemas', () => {
    for (const type of Object.keys(NATIVE_ACTION_TYPES)) {
        if (['openapi', 'mcp'].includes(type)) continue;
        const configured = action(type);
        const errors = validateActionDraft(configured, definition(type));
        assert.deepEqual(errors, {}, `${type}: ${JSON.stringify(errors)}`);
    }
});
check('internal utilities have usable manifest markers without requiring a pretend remote endpoint', () => {
    for (const type of ['smart_http', 'http', 'text', 'math', 'time', 'wait', 'fact_memory', 'tabular_processing']) {
        const draft = changeActionDisplayName(changeActionType(createActionDraft(), definition(type)), `Fixture ${type}`, true);
        assert.equal(draft.endpoint, `internal://${type}`);
        assert.equal(draft.auth.type, 'NoAuth');
        assert.deepEqual(validateActionDraft(draft, definition(type)), {});
        assert.equal(nativeActionDefinition(type).testPath, undefined);
    }
});

check('schema defaults retain false zero empty arrays and empty strings but never help text', () => {
    const schema = { type: 'object', properties: {
        enabled: { type: 'boolean', default: false },
        attempts: { type: 'integer', default: 0 },
        label: { type: 'string', default: '' },
        names: { type: 'array', default: [] },
        note: { type: 'string', description: 'Put your API key here.' },
        mode: { type: 'string', enum: ['a', 'b'], description: 'a | b' },
        wrongMode: { type: 'string', enum: ['a', 'b'], default: 'a | b' },
        wrongType: { type: 'integer', default: '20' },
        fractional: { type: 'integer', default: 1.5 },
        nested: { type: 'object', properties: { zero: { type: 'number', default: 0 } } },
    } };
    assert.deepEqual(actionSchemaDefaults(schema), { enabled: false, attempts: 0, label: '', names: [], nested: { zero: 0 } });
});

check('new custom types use their governed catalogue and nested native schema fields', () => {
    const custom = definition('installed_connector', {
        allowed_auth_types: ['username_password'],
        additional_fields_schema: { type: 'object', properties: {
            mode: { type: 'string', enum: ['safe', 'fast'], default: 'safe' },
            configured: { type: 'boolean', default: false },
            retry: { type: 'integer', default: 0 },
        } },
        metadata_schema: { type: 'object', properties: { source: { type: 'string', default: 'custom' } } },
    });
    check('prototype-like installed type names still use the generic native editor', () => {
        for (const type of ['constructor', '__proto__', 'toString']) {
            const custom = definition(type, { allowed_auth_types: ['NoAuth'] });
            const draft = changeActionType(createActionDraft(), custom);
            assert.ok(nativeActionDefinition(type).fields.some((field) => field.path === '/endpoint'));
            assert.equal(changeActionField(draft, '/endpoint', 'https://fixture.example.test').additionalFields['[object Object]'], undefined);
            assert.deepEqual(actionAuthModes(type, ['NoAuth']), [{ value: 'NoAuth', label: 'No authentication', authType: 'NoAuth' }]);
        }
    });
    const draft = changeActionType(createActionDraft(), custom);
    assert.equal(draft.type, 'installed_connector');
    assert.equal(draft.auth.type, 'username_password');
    assert.deepEqual(draft.additionalFields, { mode: 'safe', configured: false, retry: 0 });
    assert.equal(draft.metadata.source, 'custom');
    assert.ok(nativeActionDefinition(custom.type).fields.some((field) => field.path === '/endpoint'));
});

check('local schema references and composed property defaults are resolved without network calls', () => {
    const schema = {
        $ref: '#/definitions/config',
        definitions: { config: { type: 'object', allOf: [
            { properties: { one: { type: 'integer', default: 1 } }, required: ['one'] },
            { properties: { two: { type: 'boolean', default: false } } },
        ] } },
    };
    assert.deepEqual(actionSchemaDefaults(schema), { one: 1, two: false });
    assert.equal(resolveActionSchema(schema).type, 'object');
    assert.ok(validateActionSchema({}, schema)['/one']);
});

check('typed validation rejects pipe enums numeric strings fractional integers and limits', () => {
    const invalid = { type: 'object', required: ['required'], properties: {
        mode: { enum: ['a', 'b'] }, limit: { type: 'integer', minimum: 1, maximum: 5 },
        number: { type: 'number' }, items: { type: 'array', minItems: 1, items: { type: 'boolean' } },
    } };
    const errors = validateActionSchema({ mode: 'a|b', limit: 1.25, number: '0', items: [] }, invalid, '/additionalFields');
    for (const key of ['required', 'mode', 'limit', 'number', 'items']) assert.ok(errors[`/additionalFields/${key}`], key);
    assert.deepEqual(validateActionSchema({ number: 0, enabled: false, custom: 1 }, { type: 'object', properties: {
        number: { type: 'number' }, enabled: { type: 'boolean' },
    }, additionalProperties: false }), {}, 'unknown persisted values remain for authoritative server validation');
});
check('conditional schemas do not initialize forbidden inactive defaults and still validate branches', () => {
    const schema = readSchema('ui_test_plugin.additional_settings.schema.json');
    const defaults = actionSchemaDefaults(schema);
    assert.equal(defaults.boolean, false);
    assert.equal(defaults.number, undefined);
    assert.equal(defaults.integer, undefined);
    const valid = { ...defaults, string: 'fixture', string__Secret: 'fixture-secret', enum: 'bob' };
    assert.deepEqual(validateActionSchema(valid, schema), {});
    assert.ok(validateActionSchema({ ...valid, boolean: true }, schema)['/number']);
    assert.ok(validateActionSchema({ ...valid, number: 10, integer: 5 }, schema)['']);
    assert.ok(validateActionSchema('c', { anyOf: [{ const: 'a' }, { const: 'b' }] })['']);
});

check('JSON-pointer field editing preserves escaped names arrays and prototype-like data', () => {
    const original = JSON.parse('{"additionalFields":{"__proto__":{"safe":1},"a/b~c":{"nested.value":0},"items":[{"keep":false}]},"metadata":{"keep":true}}');
    const edited = withActionValue(original, '/additionalFields/a~1b~0c/nested.value', false);
    const prototype = withActionValue(edited, '/additionalFields/__proto__/new', 'data');
    assert.equal(actionValueAt(prototype, '/additionalFields/a~1b~0c/nested.value'), false);
    assert.equal(actionValueAt(prototype, '/additionalFields/__proto__/safe'), 1);
    assert.equal(Object.getPrototypeOf(prototype.additionalFields), Object.prototype);
    assert.equal(Object.prototype.new, undefined);
    assert.equal(original.additionalFields['a/b~c']['nested.value'], 0);
    const removed = withActionValue(prototype, '/additionalFields/items/0', undefined);
    assert.deepEqual(removed.additionalFields.items, []);
    assert.deepEqual(removed.metadata, { keep: true });
});
check('array removals never shift later masked credentials to another stored position', () => {
    const draft = action('databricks');
    draft.additionalFields['accounts/list'] = [
        { label: 'First', password: EDITOR_SECRET_MASK },
        { label: 'Second', nested: [{ token: EDITOR_SECRET_MASK, unknown: 0 }] },
    ];
    const original = resource(draft, [
        '/additionalFields/accounts~1list/0/password',
        '/additionalFields/accounts~1list/1/nested/0/token',
    ]);
    assert.match(actionArrayRemovalError(draft, original, '/additionalFields/accounts~1list', 0), /different positions/);
    assert.equal(actionArrayRemovalError(draft, original, '/additionalFields/accounts~1list', 1), null);
    const replaced = withActionValue(draft, '/additionalFields/accounts~1list/1/nested/0/token', 'replacement-fixture');
    assert.equal(actionArrayRemovalError(replaced, original, '/additionalFields/accounts~1list', 0), null);
    const cleared = withActionValue(draft, '/additionalFields/accounts~1list/1/nested/0/token', '');
    assert.equal(actionArrayRemovalError(cleared, original, '/additionalFields/accounts~1list', 0), null);
    assert.match(actionArrayRemovalError(draft, original, '/additionalFields/accounts~1list', 3), /no longer available/);
    assert.equal(original.record.additionalFields['accounts/list'][1].nested[0].unknown, 0);
    assert.equal(draft.additionalFields['accounts/list'][1].nested[0].token, EDITOR_SECRET_MASK);
});
check('bulk JSON protection is scoped to arrays containing actual owned stored credentials', () => {
    const draft = action('databricks');
    draft.additionalFields.connections = [{ nested: [{ token: EDITOR_SECRET_MASK }] }];
    draft.metadata.example_strings = [EDITOR_SECRET_MASK];
    const secretPath = '/additionalFields/connections/0/nested/0/token';
    const original = resource(draft, [secretPath]);
    assert.equal(actionHasStoredArraySecrets(draft, original, '/additionalFields'), true);
    assert.equal(actionHasStoredArraySecrets(draft, original, '/additionalFields/connections'), true);
    assert.equal(actionHasStoredArraySecrets(draft, original, '/additionalFields/connections/0'), true);
    assert.equal(actionHasStoredArraySecrets(draft, original, '/additionalFields/connections/0/nested/0'), false);
    assert.equal(actionHasStoredArraySecrets(draft, original, '/metadata'), false, 'ordinary literal masks are not credential bindings');
    assert.equal(actionHasStoredArraySecrets(draft, null, '/additionalFields'), false);
    assert.equal(actionHasStoredArraySecrets(withActionValue(draft, secretPath, 'replacement'), original, '/additionalFields'), false);
    assert.equal(actionHasStoredArraySecrets(withActionValue(draft, secretPath, null), original, '/additionalFields'), false);
});
check('action array edits emit explicit positional clears through the updated shared serializer', () => {
    const draft = action('databricks');
    draft.additionalFields['credentials/list~typed'] = [
        { credential__Secret: EDITOR_SECRET_MASK, keep: 0, enabled: false, labels: [] },
        { token: EDITOR_SECRET_MASK },
    ];
    const arrayPath = '/additionalFields/credentials~1list~0typed';
    const firstPath = `${arrayPath}/0/credential__Secret`;
    const secondPath = `${arrayPath}/1/token`;
    const original = resource(draft, [firstPath, secondPath, firstPath]);
    for (const value of ['', null, undefined]) {
        const changed = withActionValue(draft, firstPath, value);
        const write = buildEditorWrite(changed, original);
        assert.deepEqual(write.clear_secret_paths, [firstPath]);
        assert.equal(write.updates.additionalFields['credentials/list~typed'][0].keep, 0);
        assert.equal(write.updates.additionalFields['credentials/list~typed'][0].enabled, false);
        assert.deepEqual(write.updates.additionalFields['credentials/list~typed'][0].labels, []);
        assert.equal(write.updates.additionalFields['credentials/list~typed'][1].token, EDITOR_SECRET_MASK);
    }
    const removeLast = withActionValue(draft, `${arrayPath}/1`, undefined);
    assert.equal(actionArrayRemovalError(draft, original, arrayPath, 1), null);
    assert.deepEqual(buildEditorWrite(removeLast, original).clear_secret_paths, [secondPath]);
    const removeParent = withActionValue(draft, arrayPath, undefined);
    const parentWrite = buildEditorWrite(removeParent, original);
    assert.deepEqual(new Set(parentWrite.clear_secret_paths), new Set([firstPath, secondPath]));
    assert.ok(parentWrite.removed_paths.includes(arrayPath));
    assert.deepEqual(buildEditorWrite(draft, original).clear_secret_paths, []);
    assert.deepEqual(buildEditorWrite(withActionValue(draft, firstPath, 'replacement-fixture'), original).clear_secret_paths, []);
    assert.equal(draft.additionalFields['credentials/list~typed'][0].credential__Secret, EDITOR_SECRET_MASK);
});

check('switching type retains per-type drafts but does not pass foreign credentials into Call agent', () => {
    const original = action('cosmos_query');
    original.auth = { type: 'key', key: EDITOR_SECRET_MASK };
    original.additionalFields.custom_secret__Secret = EDITOR_SECRET_MASK;
    original.metadata.keep = { value: false };
    const agent = changeActionType(original, definition('agent'));
    assert.deepEqual(agent.auth, { type: 'user' });
    assert.deepEqual(agent.additionalFields, {});
    assert.equal(agent.endpoint, 'internal://agent');
    assert.equal(agent.identity_id, '');
    assert.deepEqual(agent.metadata.keep, { value: false });
    const returned = changeActionType(agent, definition('cosmos_query'));
    assert.deepEqual(returned.additionalFields, original.additionalFields);
    assert.deepEqual(returned.auth, original.auth);
    assert.equal(returned.id, original.id);
    const write = buildEditorWrite(agent, resource(original, ['/auth/key', '/additionalFields/custom_secret__Secret']));
    assert.ok(!JSON.stringify(write).includes('_actionTypeConfigurations'));
    assert.ok(!JSON.stringify(write.updates).includes(EDITOR_SECRET_MASK));
});

check('display-name changes derive new machine names without rewriting explicitly chosen or saved names', () => {
    let draft = changeActionDisplayName(createActionDraft(), 'Action One', true);
    assert.equal(draft.name, 'Action-One');
    draft = changeActionDisplayName(draft, 'Action Two', true);
    assert.equal(draft.name, 'Action-Two');
    assert.equal(changeActionDisplayName({ ...draft, name: 'explicit' }, 'Three', true).name, 'explicit');
    assert.equal(changeActionDisplayName(draft, 'Renamed later', false).name, 'Action-Two');
});
check('raw legacy records without optional displayName remain editable without renaming their machine identity', () => {
    const legacy = action('databricks');
    delete legacy.displayName;
    const original = resource(legacy);
    const prepared = actionForSave({ ...legacy, description: 'Edited legacy description.' });
    assert.equal(prepared.displayName, legacy.name);
    assert.equal(prepared.name, legacy.name);
    assert.equal(prepared.id, legacy.id);
    assert.deepEqual(validateActionDraft(prepared, definition(legacy.type), original), {});
    assert.deepEqual(buildEditorWrite(prepared, original).updates, {
        description: 'Edited legacy description.', displayName: legacy.name,
    });
    assert.equal(changeActionDisplayName(legacy, 'Readable label', false).name, legacy.name);
    assert.ok(validateActionDraft({ ...legacy, displayName: '' }, definition(legacy.type))['/displayName']);
    assert.ok(validateActionDraft({ ...legacy, name: undefined }, definition(legacy.type))['/name']);
});

check('native authentication methods are constrained by backend definitions and preserve hidden siblings', () => {
    for (const type of Object.keys(NATIVE_ACTION_TYPES)) {
        const allowed = definition(type).allowed_auth_types;
        const choices = actionAuthModes(type, allowed);
        for (const choice of choices) {
            assert.ok(allowed.includes(choice.authType), `${type}/${choice.value}`);
            const original = action(type);
            original.auth.hidden = { keep: 0 };
            original.additionalFields.hidden = { keep: false };
            const next = changeActionAuth(original, choice);
            assert.equal(next.auth.type, choice.authType);
            assert.deepEqual(next.auth.hidden, { keep: 0 });
            assert.deepEqual(next.additionalFields.hidden, { keep: false });
        }
    }
    assert.equal(actionAuthMethod(changeActionAuth(action('rocksdb'), { value: 'api_key', label: 'API key', authType: 'key' })), 'api_key');
});

check('reusable identities keep stable IDs and do not copy credential-bearing data', () => {
    const original = action('snowflake');
    original.additionalFields.unknown = { keep: false };
    const selected = selectActionIdentity(original, {
        id: 'identity-2', name: 'Duplicate display name', auth_type: 'api_key', credentials: { key: 'must-not-copy' },
    });
    assert.equal(selected.identity_id, 'identity-2');
    assert.equal(selected.auth.identity, 'identity-2');
    assert.equal(selected.additionalFields.auth_method, 'key_pair');
    assert.equal(selected.additionalFields.identity_auth_type, 'api_key');
    assert.deepEqual(selected.additionalFields.unknown, { keep: false });
    assert.ok(!JSON.stringify(selected).includes('must-not-copy'));
    assert.throws(() => selectActionIdentity(action('cosmos_query'), { id: 'x', name: 'x', auth_type: 'api_key' }));
    const unavailable = { ...original, identity_id: 'revoked-id' };
    assert.equal(changeActionField(unavailable, '/description', 'Only changed description').identity_id, 'revoked-id');
});

check('SQL modes explicitly clear only the connection string while preserving parameters and nested values', () => {
    const original = action('sql_query');
    original.additionalFields.connection_string = EDITOR_SECRET_MASK;
    original.additionalFields.server = 'database.example.test';
    original.additionalFields.custom = { keep: 0 };
    assert.equal(sqlConnectionMethod(original), 'connection_string');
    const changed = changeSqlConnectionMethod(original, 'parameters');
    assert.equal(sqlConnectionMethod(changed), 'parameters');
    assert.equal(changed.additionalFields.connection_string, undefined);
    assert.equal(changed.additionalFields.server, 'database.example.test');
    assert.deepEqual(changed.additionalFields.custom, { keep: 0 });
    assert.deepEqual(buildEditorWrite(changed, resource(original, ['/additionalFields/connection_string'])).clear_secret_paths, ['/additionalFields/connection_string']);
    const identity = selectActionIdentity(changed, { id: 'db-identity', name: 'Database', auth_type: 'connection_string' });
    assert.equal(sqlConnectionMethod(identity), 'connection_string');
    assert.equal(identity.additionalFields.identity_uses_connection_string, true);
});

check('endpoint changes synchronize only the connector aliases that runtime reads', () => {
    for (const [type, alias] of Object.entries({ databricks: 'workspace_url', databricks_table: 'workspace_url', tableau: 'server_url', yamcs: 'server_url', rocksdb: 'base_url', openapi: 'base_url' })) {
        const original = action(type);
        original.additionalFields.keep = { enabled: false };
        const changed = changeActionField(original, '/endpoint', 'https://new.example.test');
        assert.equal(changed.additionalFields[alias], changed.endpoint);
        assert.deepEqual(changed.additionalFields.keep, { enabled: false });
    }
    const log = action('log_analytics');
    log.additionalFields.authorityHost = 'https://old.example.test';
    log.additionalFields.endpointOverride = 'https://old-api.example.test';
    log.additionalFields.query_history = [{ query: 'SyntheticTable | take 1' }];
    const government = changeActionField(log, '/additionalFields/cloud', 'usgovernment');
    assert.equal(government.endpoint, 'https://api.loganalytics.us');
    assert.equal(government.additionalFields.authorityHost, undefined);
    assert.deepEqual(government.additionalFields.query_history, log.additionalFields.query_history);
});
check('legacy endpoint schema and username aliases display without rewriting unrelated fields', () => {
    const databricks = action('databricks');
    databricks.endpoint = '';
    databricks.additionalFields.workspace_url = 'https://legacy.example.test';
    databricks.additionalFields.database = 'legacy-schema';
    delete databricks.additionalFields.schema;
    assert.equal(displayedActionValue(databricks, '/endpoint'), 'https://legacy.example.test');
    assert.equal(displayedActionValue(databricks, '/additionalFields/schema'), 'legacy-schema');
    assert.equal(actionForSave(databricks).endpoint, 'https://legacy.example.test');
    const snowflake = action('snowflake');
    delete snowflake.additionalFields.user;
    assert.equal(displayedActionValue(snowflake, '/additionalFields/user'), snowflake.auth.identity);
    assert.equal(snowflake.additionalFields.user, undefined);
});

check('Blob defaults deny upload and endpoint derivation does not expose account keys', () => {
    const draft = changeActionType(createActionDraft(), definition('blob_storage'));
    assert.equal(draft.additionalFields.blob_storage_capabilities.upload_file_to_container, false);
    assert.equal(BLOB_ACTION_CAPABILITIES.find(({ key }) => key === 'upload_file_to_container').defaultEnabled, false);
    assert.equal(deriveBlobEndpoint('DefaultEndpointsProtocol=https;AccountName=fixtureaccount;AccountKey=synthetic;EndpointSuffix=core.usgovcloudapi.net'), 'https://fixtureaccount.blob.core.usgovcloudapi.net');
    assert.equal(deriveBlobEndpoint('BlobEndpoint=https://fixtureaccount.blob.core.windows.net/;AccountKey=synthetic'), 'https://fixtureaccount.blob.core.windows.net');
    assert.equal(deriveBlobEndpoint(EDITOR_SECRET_MASK), '');
    assert.equal(deriveBlobEndpoint('AccountKey=synthetic'), '');
});
check('Blob connection-string authoring derives the endpoint without a redundant required input', () => {
    const draft = action('blob_storage');
    draft.endpoint = '';
    const descriptor = nativeActionDefinition('blob_storage').fields.find(({ path }) => path === '/endpoint');
    assert.equal(usesDirectBlobConnectionString(draft), true);
    assert.equal(descriptor.visible(draft), false);
    const prepared = actionForSave(draft);
    assert.equal(prepared.endpoint, 'https://fixtureaccount.blob.core.windows.net');
    assert.deepEqual(validateActionDraft(prepared, definition('blob_storage')), {});
    assert.equal(draft.endpoint, '');
    const storedWithoutEndpoint = { ...draft, auth: { type: 'connection_string', key: EDITOR_SECRET_MASK } };
    assert.equal(descriptor.visible(storedWithoutEndpoint), true, 'legacy stored strings can supply a missing endpoint explicitly');
    const identity = selectActionIdentity(draft, { id: 'storage-identity', name: 'Storage', auth_type: 'connection_string' });
    assert.equal(usesDirectBlobConnectionString(identity), false);
    assert.equal(descriptor.visible(identity), true, 'a reusable identity never exposes its connection string to derive an endpoint');
});
check('embedding identities are limited to API keys supported by the real runtime', () => {
    assert.deepEqual(nativeActionDefinition('embedding_model').identityTypes, ['api_key']);
    const draft = action('embedding_model');
    assert.throws(() => selectActionIdentity(draft, { id: 'managed', name: 'Managed', auth_type: 'managed_identity' }), /not compatible/);
    const selected = selectActionIdentity(draft, { id: 'api-key', name: 'Key', auth_type: 'api_key' });
    assert.equal(selected.identity_id, 'api-key');
    assert.equal(selected.additionalFields.identity_auth_type, 'api_key');
});

check('Call agent submission keeps fixed internal authentication and complete target identity', () => {
    const draft = action('agent');
    draft.endpoint = 'https://must-not-be-used.example.test';
    draft.auth = { type: 'key', key: 'not-a-call-agent-credential' };
    const submitted = actionForSave(draft);
    assert.equal(submitted.endpoint, 'internal://agent');
    assert.deepEqual(submitted.auth, { type: 'user' });
    assert.deepEqual(submitted.additionalFields.target_agent, { id: 'target-1', scope_type: 'personal', scope_id: 'user-fixture' });
    assert.throws(() => buildActionConnectionPayload(submitted, null), /cannot be connection-tested/);
});

check('one collection searches descriptions and types and distinguishes provided same-name IDs', () => {
    const api = action('openapi');
    api.description = 'Financial retrieval';
    const agent = action('agent');
    agent.id = api.id;
    agent.displayName = api.displayName;
    agent.is_global = true;
    assert.equal(filterAuthoringActions([api, agent], '', '', '').length, 2);
    assert.deepEqual(filterAuthoringActions([api, agent], 'financial', '', ''), [api]);
    assert.deepEqual(filterAuthoringActions([api, agent], 'call agent', '', ''), [agent]);
    assert.deepEqual(filterAuthoringActions([api, agent], '', 'agent', 'provided'), [agent]);
    assert.notEqual(actionResourceKey(api), actionResourceKey(agent));
    assert.equal(actionScope(agent), 'provided');
    assert.ok(actionDetailPath(agent).endsWith('?scope=global'));
    assert.equal(actionTypeLabel('agent'), 'Call agent');
    assert.equal(actionTypeLabel('document_search'), 'Document search');
});
check('read-only action details accept empty revisions while writable records require usable revisions', () => {
    const owned = resource(action('databricks'));
    assert.equal(hasUsableActionRevision(owned), true);
    assert.equal(hasUsableActionRevision({ ...owned, revision: '' }), false);
    assert.equal(hasUsableActionRevision({ ...owned, revision: '   ' }), false);
    assert.equal(hasUsableActionRevision({ ...owned, revision: '', read_only: true }), true);
    assert.equal(hasUsableActionRevision({ ...owned, revision: '', record: { ...owned.record, is_global: true } }), true);
    assert.equal(hasUsableActionRevision({ ...owned, revision: '' }, 'global'), true);
    assert.equal(hasUsableActionRevision({ ...owned, revision: undefined, read_only: true }), false);
    assert.equal(hasUsableActionRevision({ ...owned, revision: null }), false);
});
check('disabled authoring does not hide readable actions or misclassify personal ownership', () => {
    const owned = action('databricks');
    const provided = { ...action('agent'), is_global: true };
    assert.equal(actionCanEdit(owned, true), true);
    assert.equal(actionCanEdit(owned, false), false);
    assert.equal(actionCanEdit(provided, true), false);
    assert.equal(actionScope(owned), 'personal');
    assert.equal(actionDetailPath(owned).includes('scope=global'), false);
    assert.deepEqual(filterAuthoringActions([owned, provided], '', '', ''), [owned, provided]);
});

check('stored credentials use keep replace and explicit clear intent with opaque revision', () => {
    const original = action('sql_query');
    original.auth = { type: 'servicePrincipal', key: EDITOR_SECRET_MASK, identity: 'client-fixture', tenantId: 'tenant-fixture' };
    original.additionalFields.password = EDITOR_SECRET_MASK;
    const before = resource(original, ['/auth/key', '/additionalFields/password']);
    const unchanged = buildEditorWrite(original, before);
    assert.deepEqual(unchanged.updates, {});
    const changed = changeActionField(changeActionField(original, '/auth/key', 'new-fixture-secret'), '/additionalFields/password', '');
    const write = buildEditorWrite(changed, before);
    assert.deepEqual(write.updates, { auth: { key: 'new-fixture-secret' } });
    assert.deepEqual(write.clear_secret_paths, ['/additionalFields/password']);
    assert.equal(write.expected_revision, before.revision);
});

check('connector test payloads use explicit owned contexts and resolve masks without changing drafts', () => {
    for (const type of ['sql_query', 'cosmos_query', 'rocksdb', 'yamcs', 'databricks', 'snowflake', 'tableau', 'blob_storage', 'log_analytics', 'azure_maps_openlayers']) {
        const draft = action(type);
        draft.auth.key = EDITOR_SECRET_MASK;
        if (['NoAuth', 'identity'].includes(draft.auth.type)) draft.auth.type = 'key';
        draft.additionalFields.password = EDITOR_SECRET_MASK;
        const before = resource(draft, ['/auth/key', '/additionalFields/password']);
        const payload = buildActionConnectionPayload(draft, before);
        const contextKey = ['sql_query', 'sql_schema', 'cosmos_query', 'yamcs', 'rocksdb'].includes(type)
            ? 'existing_plugin' : 'plugin_context';
        assert.deepEqual(payload[contextKey], { scope: 'personal', id: draft.id, name: draft.name });
        assert.equal(payload[contextKey === 'existing_plugin' ? 'plugin_context' : 'existing_plugin'], undefined);
        assert.equal(payload.action_scope, 'personal');
        if (type === 'sql_query') {
            assert.equal(payload.password, 'Stored_In_KeyVault');
            assert.equal(payload.auth.key, undefined, 'parameter credentials must not resolve an inactive root key');
        } else {
            assert.equal(payload.auth.key, 'Stored_In_KeyVault');
        }
        assert.ok(!JSON.stringify(payload).includes('_actionTypeConfigurations'));
        assert.equal(draft.auth.key, EDITOR_SECRET_MASK);
    }
});
check('SQL test authentication follows the selected connection mode without stale managed-identity fallbacks', () => {
    let draft = action('sql_query');
    const choices = actionAuthModes('sql_query', definition('sql_query').allowed_auth_types);
    draft.auth.key = EDITOR_SECRET_MASK;
    draft.additionalFields.password = EDITOR_SECRET_MASK;
    draft = changeActionAuth(draft, choices.find(({ value }) => value === 'integrated'));
    assert.equal(draft.auth.identity, '');
    draft.auth.identity = 'managed_identity';
    const original = resource(draft, ['/auth/key', '/additionalFields/password']);
    const integrated = buildActionConnectionPayload(draft, original);
    assert.equal(integrated.auth_type, 'integrated');
    assert.deepEqual(integrated.auth, { type: 'identity', identity: '' });
    assert.equal(integrated.password, undefined);
    assert.equal(integrated.additionalFields.password, undefined);
    assert.equal(draft.auth.identity, 'managed_identity');
    assert.equal(draft.additionalFields.password, EDITOR_SECRET_MASK);

    const connection = changeActionAuth(draft, choices.find(({ value }) => value === 'connection_string_only'));
    assert.equal(sqlConnectionMethod(connection), 'connection_string');
    connection.additionalFields.connection_string = EDITOR_SECRET_MASK;
    connection.additionalFields.auth_type = 'username_password';
    connection.auth.type = 'user';
    const stored = resource(connection, ['/auth/key', '/additionalFields/password', '/additionalFields/connection_string']);
    const payload = buildActionConnectionPayload(connection, stored);
    assert.equal(payload.auth_type, 'connection_string_only');
    assert.equal(payload.connection_method, 'connection_string');
    assert.equal(payload.additionalFields.auth_type, payload.auth_type);
    assert.equal(payload.additionalFields.connection_method, payload.connection_method);
    assert.equal(payload.connection_string, 'Stored_In_KeyVault');
    assert.equal(payload.password, undefined);
    assert.equal(payload.auth.key, undefined);
    assert.equal(connection.additionalFields.auth_type, 'username_password', 'transient normalization must not rewrite the saved draft');
    assert.deepEqual(payload.clear_secret_paths, []);
});
check('connection tests omit inactive stored credentials without clearing the saved configuration', () => {
    const managed = action('databricks');
    managed.auth = { type: 'identity', identity: 'managed_identity', key: EDITOR_SECRET_MASK, tenantId: EDITOR_SECRET_MASK };
    managed.additionalFields.auth_method = 'managed_identity';
    managed.additionalFields.private_key_passphrase = EDITOR_SECRET_MASK;
    const original = resource(managed, ['/auth/key', '/auth/tenantId', '/additionalFields/private_key_passphrase']);
    const payload = buildActionConnectionPayload(managed, original);
    assert.deepEqual(payload.auth, { type: 'identity', identity: 'managed_identity' });
    assert.equal(payload.additionalFields.private_key_passphrase, undefined);
    assert.deepEqual(payload.clear_secret_paths, []);
    assert.deepEqual(managed, original.record);

    const log = action('log_analytics');
    log.auth = { type: 'user', key: EDITOR_SECRET_MASK, identity: EDITOR_SECRET_MASK, tenantId: EDITOR_SECRET_MASK };
    const logPayload = buildActionConnectionPayload(log, resource(log, ['/auth/key', '/auth/identity', '/auth/tenantId']));
    assert.deepEqual(logPayload.auth, { type: 'user' });
    assert.deepEqual(logPayload.clear_secret_paths, []);
});

check('cleared required test credentials fail closed and optional passphrases are not rehydrated', () => {
    const draft = action('snowflake');
    draft.auth.type = 'key'; draft.additionalFields.auth_method = 'key_pair';
    draft.auth.key = EDITOR_SECRET_MASK;
    draft.additionalFields.private_key_passphrase = EDITOR_SECRET_MASK;
    const before = resource(draft, ['/auth/key', '/additionalFields/private_key_passphrase']);
    assert.throws(() => buildActionConnectionPayload({ ...draft, auth: { ...draft.auth, key: '' } }, before), /clearing/);
    const clearedPassphrase = changeActionField(draft, '/additionalFields/private_key_passphrase', '');
    const payload = buildActionConnectionPayload(clearedPassphrase, before);
    assert.equal(Object.hasOwn(payload.additionalFields, 'private_key_passphrase'), false);
    assert.deepEqual(payload.clear_secret_paths, ['/additionalFields/private_key_passphrase']);
    assert.throws(() => buildActionConnectionPayload(draft, null), /no owned stored value/);
    assert.throws(() => buildActionConnectionPayload(draft, { ...before, read_only: true }), /cannot be connection-tested/);
    assert.throws(() => buildActionConnectionPayload(draft, { ...before, record: { ...before.record, id: '' } }), /stable owned ID/);
});

check('identity tests do not carry inactive credentials and retain false or zero fields', () => {
    const original = action('yamcs');
    original.auth.key = EDITOR_SECRET_MASK;
    const selected = selectActionIdentity(original, { id: 'identity-fixture', name: 'Same name', auth_type: 'api_key' });
    selected.additionalFields.tls_verify = false;
    selected.additionalFields.custom = { zero: 0, values: [] };
    const payload = buildActionConnectionPayload(selected, resource(original, ['/auth/key']));
    assert.equal(payload.identity_id, 'identity-fixture');
    assert.deepEqual(payload.auth, { type: 'identity', identity: 'identity-fixture' });
    assert.equal(payload.auth_key, undefined);
    assert.equal(payload.tls_verify, false);
    assert.deepEqual(payload.additionalFields.custom, { zero: 0, values: [] });
});

check('reminder validation and updates preserve per-field configuration and zero-like settings', () => {
    const draft = action('databricks');
    draft.metadata.key_vault_secret_reminders = {
        'auth.key': { enabled: true, contact_email: 'specific@example.test', lead_days: 10 },
        __all__: { enabled: true, expires_on: '2030-01-01', contact_email: 'owner@example.test', lead_days: 30, custom: false },
    };
    assert.deepEqual(validateActionDraft(draft, definition(draft.type)), {});
    const changed = changeActionField(draft, '/metadata/key_vault_secret_reminders/__all__/enabled', false);
    assert.deepEqual(changed.metadata.key_vault_secret_reminders['auth.key'], draft.metadata.key_vault_secret_reminders['auth.key']);
    assert.equal(changed.metadata.key_vault_secret_reminders.__all__.custom, false);
    assert.equal(changed.metadata.key_vault_secret_reminders.__all__.expires_on, '2030-01-01');
    const bad = changeActionField(draft, '/metadata/key_vault_secret_reminders/__all__/lead_days', 0);
    assert.ok(validateActionDraft(bad, definition(bad.type))['/metadata/key_vault_secret_reminders/__all__/lead_days']);
});

check('field and global API errors preserve structured paths and escaped field names', () => {
    const errors = actionApiErrors({ errors: [
        { path: ['additionalFields', 'a/b'], message: 'Invalid value' },
        { field: 'auth.key', error: 'Credential required' },
        'endpoint: Use an allowed endpoint',
        'A global validation error',
    ] });
    assert.equal(actionFieldError(errors, '/additionalFields/a~1b'), 'Invalid value');
    assert.equal(actionFieldError(errors, '/auth/key'), 'Credential required');
    assert.equal(actionFieldError(errors, '/endpoint'), 'Use an allowed endpoint');
    assert.equal(errors.$3, 'A global validation error');
    assert.equal(expandActionFieldErrors(errors)['additionalFields.a/b'], 'Invalid value');
});

function actionPageHandler(page, variableName, context) {
    const filename = path.join(root, 'application', 'v2_ui', 'src', 'pages', 'workspace', `${page}.tsx`);
    const source = ts.createSourceFile(filename, fs.readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    let handler;
    const visit = (node) => {
        if (ts.isVariableDeclaration(node) && node.name.getText(source) === variableName && node.initializer && ts.isArrowFunction(node.initializer)) {
            handler = node.initializer;
        }
        ts.forEachChild(node, visit);
    };
    visit(source);
    assert.ok(handler, `The real ${page} ${variableName} handler must be present.`);
    const compiled = ts.transpileModule(`const pageHandler = ${handler.getText(source)};`, {
        compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
    }).outputText;
    return vm.runInNewContext(`${compiled}\npageHandler;`, context);
}

const actionEditorSaveHandler = (context) => actionPageHandler('ActionEditorPage', 'save', context);

await asyncCheck('the real save path rejects unprocessed specification edits without relying on component effects', async () => {
    const processedSpec = { openapi: '3.0.3', info: { title: 'Processed API', version: '1' }, paths: {} };
    const editedSpec = { ...processedSpec, info: { title: 'Edited API', version: '2' } };
    const saved = action('openapi');
    saved.endpoint = 'https://api.example.test';
    saved.additionalFields.openapi_spec_content = processedSpec;
    const pending = {
        ...saved,
        _openApiSourceDraft: { mode: 'manual', format: 'json', text: JSON.stringify(editedSpec), pending: true },
    };
    const original = resource(saved);
    let message;
    let fieldErrors;
    let writes = 0;
    let cleared = false;
    let navigated = false;
    const context = {
        draft: pending, original, definition: definition('openapi'),
        actionForSave, validateActionDraft, validateConnectorConfiguration, validateConnectorAuthentication,
        validity: {}, // Child effects have not published validity yet.
        setFieldErrors: (value) => { fieldErrors = value; },
        setError: (value) => { message = value; },
    };
    const validateLocally = actionPageHandler('ActionEditorPage', 'validateLocally', context);
    const save = actionEditorSaveHandler({
        ...context,
        saving: false, readOnly: false, canAuthor: true, loadError: null, catalogueLoading: false, catalogueError: null,
        validateLocally, validationController: { current: null }, mounted: { current: true },
        setSaving: () => {}, setValidationFeedback: () => {},
        saveActionConfiguration: async () => { writes += 1; return original; },
        returnTo: null, refreshBootstrap: async () => {}, load: () => {},
        clear: () => { cleared = true; }, navigate: () => { navigated = true; },
        ApiError, actionApiErrors, errorMessage: (cause) => cause.message,
    });
    await save();
    assert.match(message, /Process the edited specification/);
    assert.ok(fieldErrors['openapi-source']);
    assert.equal(writes, 0);
    assert.equal(cleared, false);
    assert.equal(navigated, false);
    assert.equal(pending._openApiSourceDraft.text, JSON.stringify(editedSpec));
    assert.deepEqual(pending.additionalFields.openapi_spec_content, processedSpec);
    assert.equal(original.revision, 'opaque-fixture-revision');

    const imported = applyOpenApiSpecification(pending, { success: true, spec_content: editedSpec });
    const validateProcessed = actionPageHandler('ActionEditorPage', 'validateLocally', { ...context, draft: imported });
    assert.equal(validateProcessed(), true);
    assert.deepEqual(imported.additionalFields.openapi_spec_content, editedSpec);
});

await asyncCheck('the real editor hydrates saved revision and masks before clearing and returning to an agent', async () => {
    const initial = action('databricks');
    const saved = resource({ ...initial, auth: { ...initial.auth, key: EDITOR_SECRET_MASK } }, ['/auth/key']);
    saved.revision = 'saved-revision';
    const events = [];
    let baseline = initial;
    let visible = { ...initial, description: 'Unsaved text' };
    let revision = 'previous-revision';
    let destination;
    const handler = actionEditorSaveHandler({
        saving: false, readOnly: false, canAuthor: true, loadError: null, catalogueLoading: false, catalogueError: null,
        validateLocally: () => true, validationController: { current: null }, mounted: { current: true },
        draft: visible, original: resource(initial), actionForSave, ApiError, actionApiErrors,
        saveActionConfiguration: async () => saved,
        returnTo: '/workspace/agents/new',
        location: { key: 'current-editor' },
        queueCreatedWorkspaceAction: (returnTo, record) => {
            assert.equal(returnTo, '/workspace/agents/new');
            assert.equal(record, saved.record);
            events.push('queue');
        },
        load: (resource) => {
            events.push('load');
            baseline = resource.record;
            revision = resource.revision;
        },
        clear: () => { events.push('clear'); visible = baseline; },
        refreshBootstrap: () => Promise.resolve(),
        navigate: (to, options) => { events.push('navigate'); destination = { to, options }; },
        setSaving: () => {}, setError: () => {}, setValidationFeedback: () => {}, setFieldErrors: () => {},
        errorMessage: (cause) => cause.message,
    });
    await handler();
    assert.deepEqual(events, ['queue', 'load', 'clear', 'navigate']);
    assert.equal(revision, 'saved-revision');
    assert.equal(visible.auth.key, EDITOR_SECRET_MASK);
    assert.equal(destination.to, '/workspace/agents/new');
    assert.equal(destination.options.state.workspaceEditorSaved, true);
    assert.equal(destination.options.state.preserveWorkspaceDraft, true);
    assert.equal(destination.options.state.workspaceEditorFrom, 'current-editor');
});

await asyncCheck('the real editor keeps the draft and revision on a failed save', async () => {
    let message;
    let hydrated = false;
    let cleared = false;
    let navigated = false;
    const handler = actionEditorSaveHandler({
        saving: false, readOnly: false, canAuthor: true, loadError: null, catalogueLoading: false, catalogueError: null,
        validateLocally: () => true, validationController: { current: null }, mounted: { current: true },
        draft: action('databricks'), original: resource(action('databricks')), actionForSave, ApiError, actionApiErrors,
        saveActionConfiguration: async () => { throw new ApiError('Conflict', 409, { errors: [] }); },
        returnTo: null, queueCreatedWorkspaceAction: () => { throw new Error('Must not queue a failed save.'); },
        load: () => { hydrated = true; }, clear: () => { cleared = true; },
        refreshBootstrap: () => Promise.resolve(), navigate: () => { navigated = true; },
        setSaving: () => {}, setError: (value) => { message = value; }, setValidationFeedback: () => {}, setFieldErrors: () => {},
        errorMessage: (cause) => cause.message,
    });
    await handler();
    assert.match(message, /changed in another session/);
    assert.equal(hydrated, false);
    assert.equal(cleared, false);
    assert.equal(navigated, false);
});
await asyncCheck('the real editor blocks creation-disabled writes while retaining the loaded draft', async () => {
    const draft = action('databricks');
    let writes = 0;
    let cleared = false;
    const save = actionEditorSaveHandler({
        saving: false, readOnly: false, canAuthor: false, loadError: null, catalogueLoading: false, catalogueError: null,
        draft, original: resource(draft),
        validateLocally: () => { throw new Error('Disabled authoring must stop before submit validation.'); },
        saveActionConfiguration: () => { writes += 1; },
        clear: () => { cleared = true; },
    });
    await save();
    assert.equal(writes, 0);
    assert.equal(cleared, false);
    assert.equal(draft.id, 'owned-databricks');
});
await asyncCheck('the real collection retains owned deletion when creation is disabled', async () => {
    const draft = action('databricks');
    const deleted = [];
    let refreshed = false;
    const remove = actionPageHandler('ActionsSection', 'remove', {
        canAuthor: false, actionScope, actionResourceKey,
        owner: 'fixture-user', loadedOwner: { current: 'fixture-user' },
        setBusyId: () => {}, setError: () => {}, errorMessage: (cause) => cause.message,
        deleteAuthoringAction: async (id) => { deleted.push(id); },
        refresh: async () => { refreshed = true; }, refreshBootstrap: async () => {},
    });
    await remove(draft);
    assert.deepEqual(deleted, [draft.id]);
    assert.equal(refreshed, true);
    await remove({ ...draft, is_global: true });
    assert.equal(deleted.length, 1);
});

await asyncCheck('overlapping collection deletes cannot restore an already deleted action on failure', async () => {
    for (const failure of ['delete', 'refresh']) {
        const first = action('databricks');
        const second = action('tableau');
        const initial = [first, second];
        let serverItems = initial.slice();
        let visibleItems = initial.slice();
        let refreshes = 0;
        const errors = [];
        let finishFirst;
        let finishSecond;
        let rejectSecond;
        const firstRequest = new Promise((resolve) => { finishFirst = resolve; });
        const secondRequest = new Promise((resolve, reject) => { finishSecond = resolve; rejectSecond = reject; });
        const remove = actionPageHandler('ActionsSection', 'remove', {
            actionScope, actionResourceKey, owner: 'fixture-user', loadedOwner: { current: 'fixture-user' },
            items: initial,
            setItems: (items) => { visibleItems = items; },
            setBusyId: () => {}, setError: (message) => { if (message) errors.push(message); },
            errorMessage: (cause) => cause.message,
            deleteAuthoringAction: (id) => id === first.id ? firstRequest : secondRequest,
            refresh: async () => {
                refreshes += 1;
                if (failure === 'refresh' && refreshes === 2) {
                    errors.push('Collection refresh failed');
                    return;
                }
                visibleItems = serverItems.slice();
            },
            refreshBootstrap: () => Promise.resolve(),
        });
        const pendingFirst = remove(first);
        const pendingSecond = remove(second);
        serverItems = serverItems.filter((item) => item.id !== first.id);
        finishFirst();
        await pendingFirst;
        assert.equal(visibleItems.some((item) => item.id === first.id), false);
        if (failure === 'delete') rejectSecond(new Error('Second deletion failed'));
        else {
            serverItems = serverItems.filter((item) => item.id !== second.id);
            finishSecond();
        }
        await pendingSecond;
        assert.equal(visibleItems.some((item) => item.id === first.id), false, `${failure} failure restored the first action`);
        assert.equal(errors.length, 1);
    }
});

const originalFetch = globalThis.fetch;
const requests = [];
let response = {};
globalThis.fetch = async (url, options = {}) => {
    requests.push({ url: String(url), options, body: options.body ? JSON.parse(options.body) : undefined });
    return new Response(JSON.stringify(response), { status: 200, headers: { 'Content-Type': 'application/json' } });
};
try {
    check('selecting a type identity or native field never calls a connector', () => {
        const draft = action('databricks');
        changeActionField(draft, '/endpoint', 'https://other.example.test');
        changeActionAuth(draft, actionAuthModes(draft.type, definition(draft.type).allowed_auth_types)[0]);
        selectActionIdentity(draft, { id: 'identity', name: 'Identity', auth_type: 'api_key' });
        assert.equal(requests.length, 0);
    });
    await asyncCheck('identity catalogue projection retains only authoring-safe identity details', async () => {
        response = { identities: [{ id: 'id-1', name: 'Reusable', credentials: { auth_type: 'api_key', key: 'must-not-copy' }, internal: 'hidden' }] };
        const identities = await fetchActionIdentities();
        assert.equal(requests.at(-1).url, '/api/workspace-identities/personal/identities');
        assert.equal(identities[0].auth_type, 'api_key');
        assert.equal(identities[0].id, 'id-1');
        assert.equal(Object.hasOwn(identities[0], 'credentials'), false);
        assert.equal(Object.hasOwn(identities[0], 'internal'), false);
    });
    await asyncCheck('safe reminder defaults use the opt-in editor options and retain false values', async () => {
        response = { settings: {
            allow_user_plugins: false,
            enable_key_vault_secret_storage: false, enable_key_vault_secret_expiration_reminders: false,
            key_vault_secret_expiration_default_lead_days: 7,
            key_vault_secret_expiration_default_contact_email: 'owner@example.test',
            key_vault_secret_expiration_require_expiration: true,
        } };
        const hints = await fetchActionEditorHints();
        assert.ok(requests.at(-1).url.endsWith('/api/user/agent/settings?view=editor'));
        assert.deepEqual(hints, {
            canAuthor: false,
            storageEnabled: false, remindersEnabled: false, requireExpiration: true,
            reminderLeadDays: 7, reminderEmail: 'owner@example.test',
        });
        response.settings.allow_user_plugins = true;
        assert.equal((await fetchActionEditorHints()).canAuthor, true);
        delete response.settings.allow_user_plugins;
        assert.equal((await fetchActionEditorHints()).canAuthor, false, 'unknown authoring capability must fail closed');
    });
    await asyncCheck('provided empty or omitted revisions survive API normalization and the page read guard', async () => {
        const provided = { ...action('agent'), is_global: true };
        for (const revision of ['', undefined]) {
            response = { record: provided, read_only: true, secret_paths: [], ...(revision === undefined ? {} : { revision }) };
            const result = await fetchActionEditor(provided.id, 'global');
            assert.equal(result.revision, '');
            assert.equal(hasUsableActionRevision(result, 'global'), true);
        }
        response = { record: action('agent'), read_only: false, secret_paths: [], revision: '' };
        await assert.rejects(fetchActionEditor('owned-agent'), /invalid editor resource/);
        response = [action('databricks'), provided];
        assert.equal((await fetchAuthoringActions()).length, 2);
    });
    await asyncCheck('explicit testing uses existing connector routes and abort signals', async () => {
        response = { success: true, message: 'Synthetic test only' };
        const draft = action('databricks');
        const signal = new AbortController().signal;
        await testWorkspaceAction(draft, resource(draft), definition(draft.type), signal);
        assert.equal(requests.at(-1).url, '/api/plugins/test-databricks-connection');
        assert.equal(requests.at(-1).options.signal, signal);
        assert.equal(requests.at(-1).body.plugin_context.id, draft.id);
        const count = requests.length;
        await assert.rejects(() => testWorkspaceAction(action('agent'), null, definition('agent')), /does not expose/);
        assert.equal(requests.length, count);
    });
    await asyncCheck('explicit validation calls canonical validation without executing the action', async () => {
        response = { valid: false, errors: ['endpoint: Synthetic validation failure'] };
        const draft = action('databricks');
        const result = await validateWorkspaceAction(draft, null);
        assert.equal(requests.at(-1).url, '/api/plugins/validate');
        assert.equal(result.valid, false);
        assert.equal(requests.at(-1).body.type, draft.type);
        assert.equal(Object.hasOwn(requests.at(-1).body, 'plugin_context'), false);
        assert.equal(Object.hasOwn(requests.at(-1).body, '_actionTypeConfigurations'), false);
    });
} finally {
    globalThis.fetch = originalFetch;
}

console.log(`${checks} workspace action authoring logic checks passed.`);
