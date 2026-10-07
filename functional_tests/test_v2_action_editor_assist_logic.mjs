// test_v2_action_editor_assist_logic.mjs
// Version: 0.261.280
// Implemented in: 0.261.280
// Executes the action editor's Ask AI view and patch rules: the per-type fields Ask AI may read
// and set, which paths it never sees, and how a type change and its undo go through the editor's
// own helpers.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import './test_support/tsResolve.mjs';

const { actionAuthMethod, actionTypeLabel, changeActionType, createActionDraft } = await import('../application/v2_ui/src/lib/workspaceActionLogic.ts');
const { EDITOR_SECRET_MASK } = await import('../application/v2_ui/src/lib/workspaceAuthoring.ts');
const { editorAssistPatch, editorAssistUndoPlan } = await import('../application/v2_ui/src/lib/editorAssist.ts');
const {
    ACTION_ASSIST_SECTIONS, actionAssistValues, applyActionAssistPatch, buildActionAssistView,
} = await import('../application/v2_ui/src/lib/actionEditorAssist.ts');

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const schemas = path.join(root, 'application', 'single_app', 'static', 'json', 'schemas');
const readSchema = (name) => {
    const location = path.join(schemas, name);
    return fs.existsSync(location) ? JSON.parse(fs.readFileSync(location, 'utf8')) : {};
};
const baseAuth = readSchema('plugin.schema.json').definitions.AuthType.enum;
function definition(type) {
    return {
        type, display: actionTypeLabel(type), description: `Fixture for ${type}`,
        allowed_auth_types: readSchema(`${type}.definition.json`).allowedAuthTypes || baseAuth,
        additional_fields_schema: readSchema(`${type}_plugin.additional_settings.schema.json`),
        metadata_schema: readSchema(`${type}_plugin.metadata.schema.json`),
    };
}
const catalogue = ['openapi', 'mcp', 'sql_query', 'simplechat', 'blob_storage', 'msgraph'].map(definition);
const context = { catalogue, isNew: true, secretPaths: [] };
const ACTION_PATH = /^\/(displayName|description|type|endpoint|deployment|api_version|auth\/type|additionalFields\/[A-Za-z0-9_]{1,80}|metadata\/[A-Za-z0-9_]{1,80})$/;

function typed(type) {
    return { ...changeActionType(createActionDraft(), definition(type)), displayName: 'Orders', description: 'Reads orders.' };
}

function allPaths(view) {
    return [...view.fields, ...Object.values(view.variant?.fields ?? {}).flat()].map((field) => field.path);
}

function testViewShape() {
    const view = buildActionAssistView(createActionDraft(), context);
    assert.deepEqual(view.sections.map((section) => section.id), ACTION_ASSIST_SECTIONS.map((section) => section.id));
    assert.deepEqual(view.fields.map((field) => field.path), ['/displayName', '/description', '/type']);
    assert.equal(view.variant.path, '/type');
    assert.deepEqual(Object.keys(view.variant.fields).sort(), catalogue.map((item) => item.type).sort());
    assert.ok(view.variant.fields.mcp.some((field) => field.path === '/additionalFields/allowed_tool_names' && field.kind === 'lines'));
    assert.ok(view.variant.fields.simplechat.some((field) => field.path === '/additionalFields/simplechat_capabilities' && field.kind === 'choices'));
    assert.ok(view.variant.fields.sql_query.some((field) => field.path === '/auth/type' && field.kind === 'select'));
    for (const item of allPaths(view)) assert.match(item, ACTION_PATH, `${item} would be refused by the server`);
    for (const fields of Object.values(view.variant.fields)) {
        const paths = fields.map((field) => field.path);
        assert.equal(new Set(paths).size, paths.length);
    }
    assert.deepEqual(view.values, { '/displayName': '', '/description': '', '/type': null });
}

function testSecretsHidden() {
    const draft = typed('sql_query');
    draft.additionalFields = { ...draft.additionalFields, password: EDITOR_SECRET_MASK, server: 'db.example' };
    const view = buildActionAssistView(draft, { ...context, isNew: false, secretPaths: ['/additionalFields/server'] });
    const paths = allPaths(view);
    assert.ok(!paths.includes('/additionalFields/server'));
    assert.ok(!paths.some((item) => /password|secret|connection_string|key$/i.test(item)));
    assert.ok(!Object.values(view.values).includes(EDITOR_SECRET_MASK));
}

function testTypeChangeAndUndo() {
    const start = typed('sql_query');
    const filled = applyActionAssistPatch(start, { '/additionalFields/server': 'db.example', '/additionalFields/database': 'orders' }, context);
    assert.equal(filled.additionalFields.server, 'db.example');
    const before = actionAssistValues(filled, context);
    const patch = editorAssistPatch(buildActionAssistView(filled, context), before, {
        ...before, '/type': 'openapi', '/endpoint': 'https://api.example/openapi.json',
    });
    assert.equal(Object.keys(patch)[0], '/type');
    const changed = applyActionAssistPatch(filled, patch, context);
    assert.equal(changed.type, 'openapi');
    assert.equal(changed.endpoint, 'https://api.example/openapi.json');
    const after = actionAssistValues(changed, context);
    const entries = Object.keys(patch).map((key) => ({ path: key, before: before[key] ?? null, after: after[key] }));
    const plan = editorAssistUndoPlan(entries, before, after, '/type');
    const undone = applyActionAssistPatch(changed, plan.patch, context);
    assert.ok(undone, 'undo is applied');
    assert.equal(undone.type, 'sql_query');
    assert.equal(undone.additionalFields.server, 'db.example');
    assert.equal(undone.additionalFields.database, 'orders');
}

function testUndoToNoType() {
    const empty = { ...createActionDraft(), displayName: 'Orders' };
    const before = actionAssistValues(empty, context);
    const changed = applyActionAssistPatch(empty, { '/type': 'mcp', '/endpoint': 'https://mcp.example/sse' }, context);
    assert.equal(changed.type, 'mcp');
    const after = actionAssistValues(changed, context);
    const entries = [{ path: '/type', before: null, after: 'mcp' }, { path: '/endpoint', before: null, after: after['/endpoint'] }];
    const plan = editorAssistUndoPlan(entries, before, after, '/type');
    const undone = applyActionAssistPatch(changed, plan.patch, context);
    assert.ok(undone, 'undo back to no type is applied');
    assert.equal(undone.type, '');
    assert.equal(undone.endpoint, '');
    assert.equal(undone._actionTypeConfigurations.mcp.endpoint, 'https://mcp.example/sse');
}

function testFieldKinds() {
    const mcp = applyActionAssistPatch(typed('mcp'), {
        '/additionalFields/allowed_tool_names': ['search', 'lookup'],
        '/additionalFields/load_prompts': true,
        '/additionalFields/tool_result_policy': 'truncate',
    }, context);
    assert.deepEqual(mcp.additionalFields.allowed_tool_names, ['search', 'lookup']);
    assert.equal(mcp.additionalFields.load_prompts, true);
    assert.equal(applyActionAssistPatch(typed('mcp'), { '/additionalFields/tool_result_policy': 'shout' }, context), null);

    const view = buildActionAssistView(typed('simplechat'), context);
    const capability = view.variant.fields.simplechat.find((field) => field.path === '/additionalFields/simplechat_capabilities');
    const first = capability.options[0].value;
    const chosen = applyActionAssistPatch(typed('simplechat'), { '/additionalFields/simplechat_capabilities': [first] }, context);
    assert.deepEqual(actionAssistValues(chosen, context)['/additionalFields/simplechat_capabilities'], [first]);

    const sqlView = buildActionAssistView(typed('sql_query'), context);
    const auth = sqlView.variant.fields.sql_query.find((field) => field.path === '/auth/type');
    const other = auth.options.map((option) => option.value).find((value) => value !== actionAuthMethod(typed('sql_query')));
    if (other) assert.equal(actionAuthMethod(applyActionAssistPatch(typed('sql_query'), { '/auth/type': other }, context)), other);
}

function testRefusals() {
    const draft = typed('openapi');
    assert.equal(applyActionAssistPatch(draft, { '/type': 'not_a_type' }, context), null);
    assert.equal(applyActionAssistPatch(draft, { '/additionalFields/server': 'x' }, context), null);
    assert.equal(applyActionAssistPatch(draft, { '/auth/key': 'x' }, context), null);
    const unchanged = applyActionAssistPatch(draft, { '/displayName': 'Orders' }, context);
    assert.equal(unchanged.displayName, 'Orders');
}

function testEveryTypeMeetsServerRules() {
    const types = fs.readdirSync(schemas).filter((name) => name.endsWith('.definition.json')).map((name) => name.replace('.definition.json', ''));
    const every = [...new Set([...types, 'openapi', 'mcp'])].map(definition);
    const view = buildActionAssistView(typed('openapi'), { ...context, catalogue: every });
    for (const field of [...view.fields, ...Object.values(view.variant.fields).flat()]) {
        assert.match(field.path, ACTION_PATH, `${field.path} would be refused by the server`);
        for (const option of field.options ?? []) {
            assert.ok(typeof option.value === 'string' && option.value && option.value.length <= 512, `${field.path} has a blank option`);
        }
        if (field.kind === 'select' || field.kind === 'choices') assert.ok(field.options?.length, `${field.path} lists no options`);
    }
}

const tests = [testViewShape, testSecretsHidden, testTypeChangeAndUndo, testUndoToNoType, testFieldKinds, testRefusals, testEveryTypeMeetsServerRules];
for (const test of tests) {
    test();
    console.log(`✅ ${test.name}`);
}
console.log(`📊 ${tests.length}/${tests.length} action editor Ask AI checks passed`);
