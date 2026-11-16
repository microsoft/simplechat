// test_workflow_field_drafts.js
/*
Offline regression tests for session-scoped workflow authoring field buffers.
Version: 0.261.123
Implemented in: 0.261.122
History snapshots added in: 0.261.123

Executes the exported production store using the existing TypeScript resolver
and V2 compiler dependency. No browser, API requests, or workflow execution.
*/

const assert = require('node:assert/strict');
const fs = require('node:fs');
const { registerHooks } = require('node:module');
const path = require('node:path');
const { before, test } = require('node:test');
const { pathToFileURL } = require('node:url');

const root = path.resolve(__dirname, '..');
const ts = require(path.join(root, 'application', 'v2_ui', 'node_modules', 'typescript'));
const schemaPath = ['output', 'schema'];
const decisionPath = ['output', 'decision'];
const tagsPath = ['query', 'tags'];
const initialSchema = JSON.stringify({ type: 'object' }, null, 2);
const parseError = 'JSON schema must be valid JSON.';
let WorkflowFieldDraftStore;
let workflowForSave;

before(async () => {
    await import(pathToFileURL(path.join(__dirname, 'test_support', 'tsResolve.mjs')));
    const filename = path.join(root, 'application', 'v2_ui', 'src', 'components', 'workflows', 'WorkflowFieldDrafts.tsx');
    const storeUrl = pathToFileURL(filename);
    // The shared resolver handles .ts dependencies; Node needs compilation for this .tsx entry.
    const tsxHook = registerHooks({
        load(url, context, nextLoad) {
            if (url !== storeUrl.href) return nextLoad(url, context);
            return {
                format: 'module',
                shortCircuit: true,
                source: ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
                    fileName: filename,
                    compilerOptions: {
                        target: ts.ScriptTarget.ES2022,
                        module: ts.ModuleKind.ESNext,
                        jsx: ts.JsxEmit.ReactJSX,
                    },
                }).outputText,
            };
        },
    });
    try {
        ({ WorkflowFieldDraftStore } = await import(storeUrl));
    } finally {
        tsxHook.deregister();
    }
    ({ workflowForSave } = await import(pathToFileURL(
        path.join(root, 'application', 'v2_ui', 'src', 'lib', 'workflowEditor.ts'),
    )));
});

function ownerKeys(...owners) {
    return new Set(owners.map((owner) => JSON.stringify(owner)));
}

function deepFreeze(value) {
    if (value && typeof value === 'object' && !Object.isFrozen(value)) {
        Object.values(value).forEach(deepFreeze);
        Object.freeze(value);
    }
    return value;
}

test('reading fields and allocating Repeat row identities do not create pending edits', () => {
    const store = new WorkflowFieldDraftStore();
    const task = ['task', 'task'];
    const repeat = ['node', 'repeat'];
    const owners = ownerKeys(task, repeat);

    assert.equal(store.field(task, schemaPath, initialSchema).value, initialSchema);
    assert.equal(store.field(task, schemaPath, initialSchema).error, '');
    assert.equal(store.field(task, [...decisionPath, 'name'], '').value, '');
    const rows = store.repeatStateRowIds(repeat, 3);
    assert.equal(new Set(rows).size, 3);
    assert.deepEqual(store.repeatStateRowIds(repeat, 3), rows);
    assert.equal(store.getSnapshot(), 0);
    assert.deepEqual(store.summary(owners), { pending: false, taskSchemaErrors: new Map() });
});

test('invalid schema text and its root error survive remount defaults and other owner reads', () => {
    const store = new WorkflowFieldDraftStore();
    const task = ['task', 'constructor'];
    const other = ['task', 'other'];
    const owners = ownerKeys(task, other);
    let notifications = 0;
    const unsubscribe = store.subscribe(() => notifications++);

    store.field(task, schemaPath, initialSchema).setValue('{', parseError);
    const revision = store.getSnapshot();
    assert.equal(notifications, 1);
    assert.equal(store.summary(owners).pending, true);
    assert.equal(store.summary(owners).taskSchemaErrors.get(task[1]), parseError);
    assert.equal(store.field(other, schemaPath, initialSchema).value, initialSchema);
    assert.equal(store.summary(owners).taskSchemaErrors.has(other[1]), false);

    const remounted = store.field(task, schemaPath, '{"type":"array"}');
    assert.equal(remounted.value, '{');
    assert.equal(remounted.error, parseError);
    remounted.setValue('{', parseError);
    assert.equal(store.getSnapshot(), revision);
    assert.equal(notifications, 1);
    assert.equal(store.summary(owners).taskSchemaErrors.get(task[1]), parseError);
    unsubscribe();
    store.clear(task);
    assert.equal(notifications, 1);
});

test('schema errors remain pending until cleared even when text matches its baseline', () => {
    const store = new WorkflowFieldDraftStore();
    const task = ['task', 'schema'];
    const owners = ownerKeys(task);
    const field = store.field(task, schemaPath, initialSchema);

    field.setValue('{', parseError);
    field.setValue(initialSchema, parseError);
    store.accept(task, schemaPath);
    store.acceptSavedFields();
    assert.equal(store.summary(owners).pending, true);
    assert.equal(store.summary(owners).taskSchemaErrors.get(task[1]), parseError);

    field.setValue(initialSchema);
    assert.equal(store.field(task, schemaPath, '').error, '');
    assert.deepEqual(store.summary(owners), { pending: false, taskSchemaErrors: new Map() });
});

test('schema replacement and contract removal clear only the intended owner and field prefix', () => {
    const store = new WorkflowFieldDraftStore();
    const task = ['task', 'shared-id'];
    const other = ['task', 'other'];
    const node = ['node', task[1]];
    store.field(task, schemaPath, initialSchema).setValue('{', parseError);
    store.field(task, [...decisionPath, 'name'], '').setValue('unfinished');
    store.field(task, ['output', 'schema-extra'], '').setValue('separate field');
    store.field(other, schemaPath, initialSchema).setValue('[', parseError);
    store.field(node, [...decisionPath, 'name'], '').setValue('node draft');

    store.clear(task, schemaPath);
    assert.equal(store.field(task, schemaPath, 'replacement schema').value, 'replacement schema');
    assert.equal(store.summary(ownerKeys(task)).taskSchemaErrors.size, 0);
    assert.equal(store.field(task, [...decisionPath, 'name'], '').value, 'unfinished');
    assert.equal(store.field(task, ['output', 'schema-extra'], '').value, 'separate field');
    assert.equal(store.summary(ownerKeys(task)).pending, true);

    store.clear(task, ['output']);
    assert.equal(store.summary(ownerKeys(task)).pending, false);
    assert.equal(store.field(task, [...decisionPath, 'name'], '').value, '');
    assert.equal(store.field(task, ['output', 'schema-extra'], '').value, '');
    assert.equal(store.field(other, schemaPath, '').error, parseError);
    assert.equal(store.field(node, [...decisionPath, 'name'], '').value, 'node draft');
});

test('successful-save acknowledgement retains raw text without accepting errors or unfinished builders', () => {
    const store = new WorkflowFieldDraftStore();
    const task = ['task', 'valid'];
    const invalid = ['task', 'invalid'];
    const query = ['node', 'query'];
    const rawSchema = ' { "type": "object" } \n';
    const rawTags = 'finance, quarterly, ';
    store.field(task, schemaPath, initialSchema).setValue(rawSchema);
    store.field(query, tagsPath, 'finance, quarterly').setValue(rawTags);
    store.field(invalid, schemaPath, initialSchema).setValue('{', parseError);
    store.field(task, [...decisionPath, 'name'], '').setValue('unfinished');
    store.field(task, [...decisionPath, 'type'], 'boolean').setValue('enum');
    store.field(task, [...decisionPath, 'enum'], '').setValue(' yes \n no \n');

    store.acceptSavedFields();
    assert.equal(store.field(task, schemaPath, '').value, rawSchema);
    assert.equal(store.field(query, tagsPath, '').value, rawTags);
    assert.equal(store.summary(ownerKeys(query)).pending, false);
    assert.equal(store.summary(ownerKeys(invalid)).pending, true);
    assert.equal(store.summary(ownerKeys(invalid)).taskSchemaErrors.get(invalid[1]), parseError);
    assert.equal(store.summary(ownerKeys(task)).pending, true);
    assert.equal(store.field(task, [...decisionPath, 'name'], '').value, 'unfinished');
    assert.equal(store.field(task, [...decisionPath, 'enum'], '').value, ' yes \n no \n');

    store.clear(task, decisionPath);
    assert.equal(store.summary(ownerKeys(task)).pending, false);
    store.field(task, schemaPath, '').setValue(`${rawSchema} `);
    assert.equal(store.summary(ownerKeys(task)).pending, true);
});

test('task and node owners remain isolated for prototype-like IDs and escaped path segments', () => {
    const store = new WorkflowFieldDraftStore();
    for (const id of ['constructor', '__proto__', 'toString', 'a:b', 'a","output']) {
        const task = ['task', id];
        const node = ['node', id];
        store.field(task, schemaPath, '').setValue(`task ${id}`, `task error ${id}`);
        store.field(node, schemaPath, '').setValue(`node ${id}`, `node error ${id}`);
        assert.equal(store.field(task, schemaPath, '').value, `task ${id}`);
        assert.equal(store.field(node, schemaPath, '').value, `node ${id}`);
        assert.deepEqual(store.summary(ownerKeys(task, node)).taskSchemaErrors, new Map([[id, `task error ${id}`]]));
    }
    const owner = ['node', 'paths'];
    store.field(owner, ['state', 'a:b', 'name'], '').setValue('first');
    store.field(owner, ['state:a', 'b', 'name'], '').setValue('second');
    assert.equal(store.field(owner, ['state', 'a:b', 'name'], '').value, 'first');
    assert.equal(store.field(owner, ['state:a', 'b', 'name'], '').value, 'second');
});

test('unfinished decision inputs survive remount and completing a field retains the chosen type without dirtying it', () => {
    const store = new WorkflowFieldDraftStore();
    const task = ['task', 'decision'];
    const owners = ownerKeys(task);
    const namePath = [...decisionPath, 'name'];
    const typePath = [...decisionPath, 'type'];
    const enumPath = [...decisionPath, 'enum'];
    store.field(task, typePath, 'boolean').setValue('enum');
    assert.equal(store.summary(owners).pending, true);
    store.field(task, namePath, '').setValue(' decision ');
    store.field(task, enumPath, '').setValue(' yes \n no  \n');

    assert.equal(store.field(task, namePath, '').value, ' decision ');
    assert.equal(store.field(task, typePath, 'boolean').value, 'enum');
    assert.equal(store.field(task, enumPath, '').value, ' yes \n no  \n');
    store.field(task, namePath, '').setValue('');
    store.field(task, enumPath, '').setValue('');
    store.accept(task, typePath);
    assert.equal(store.field(task, typePath, 'boolean').value, 'enum');
    assert.equal(store.summary(owners).pending, false);
    store.field(task, typePath, 'boolean').setValue('number');
    assert.equal(store.summary(owners).pending, true);
    store.field(task, typePath, 'boolean').setValue('enum');
    assert.equal(store.summary(owners).pending, false);
});

test('Repeat row identities preserve surviving drafts through slot rename, removal, and re-addition', () => {
    const store = new WorkflowFieldDraftStore();
    const owner = ['node', 'constructor'];
    let state = [{ name: 'left' }, { name: 'middle' }, { name: 'right' }];
    const ids = store.repeatStateRowIds(owner, state.length);
    const namePath = (id) => ['state', id, 'decision', 'name'];
    ids.forEach((id, index) => store.field(owner, namePath(id), '').setValue(`draft ${index}`));

    state = state.map((slot, index) => index === 1 ? { ...slot, name: 'constructor' } : slot);
    assert.equal(state[1].name, 'constructor');
    assert.deepEqual(store.repeatStateRowIds(owner, state.length), ids);
    assert.equal(store.field(owner, namePath(ids[1]), '').value, 'draft 1');

    store.removeRepeatStateRow(owner, ids[0]);
    state = state.slice(1);
    assert.deepEqual(store.repeatStateRowIds(owner, state.length), ids.slice(1));
    assert.equal(store.field(owner, namePath(ids[0]), '').value, '');
    assert.equal(store.field(owner, namePath(ids[1]), '').value, 'draft 1');
    assert.equal(store.field(owner, namePath(ids[2]), '').value, 'draft 2');
    state = state.map((slot) => ({ ...slot, name: '' }));
    assert.deepEqual(store.repeatStateRowIds(owner, state.length), ids.slice(1));

    state = [...state, { name: 'left' }];
    const added = store.repeatStateRowIds(owner, state.length);
    assert.deepEqual(added.slice(0, 2), ids.slice(1));
    assert.ok(!ids.includes(added[2]));
    assert.equal(store.field(owner, namePath(added[2]), '').value, '');
    added.reverse();
    assert.deepEqual(store.repeatStateRowIds(owner, state.length).slice(0, 2), ids.slice(1));
});

test('owner pruning removes orphan errors and Repeat metadata without touching surviving owners', () => {
    const store = new WorkflowFieldDraftStore();
    const task = ['task', 'constructor'];
    const removed = ['node', 'constructor'];
    const retained = ['node', '__proto__'];
    const removedIds = store.repeatStateRowIds(removed, 2);
    const retainedIds = store.repeatStateRowIds(retained, 2);
    const rowPath = (id) => ['state', id, 'decision', 'name'];
    store.field(task, schemaPath, initialSchema).setValue('{', parseError);
    store.field(removed, rowPath(removedIds[0]), '').setValue('removed draft');
    store.field(retained, rowPath(retainedIds[1]), '').setValue('surviving draft');
    assert.deepEqual(store.summary(new Set()), { pending: false, taskSchemaErrors: new Map() });

    store.retainOwners(ownerKeys(retained));
    assert.equal(store.field(task, schemaPath, initialSchema).error, '');
    assert.equal(store.field(task, schemaPath, initialSchema).value, initialSchema);
    assert.equal(store.field(removed, rowPath(removedIds[0]), '').value, '');
    assert.equal(store.field(retained, rowPath(retainedIds[1]), '').value, 'surviving draft');
    assert.deepEqual(store.repeatStateRowIds(retained, 2), retainedIds);
    assert.ok(store.repeatStateRowIds(removed, 2).every((id) => !removedIds.includes(id)));
    assert.equal(store.summary(ownerKeys(task, removed, retained)).taskSchemaErrors.size, 0);
    assert.equal(store.summary(ownerKeys(retained)).pending, true);

    store.retainOwners(new Set());
    assert.equal(store.summary(ownerKeys(task, removed, retained)).pending, false);
});

test('raw query-tag spacing and trailing commas persist separately from normalized tags', () => {
    const store = new WorkflowFieldDraftStore();
    const owner = ['node', 'query'];
    const tags = ['finance', 'quarterly'];
    const raw = 'finance, quarterly, ';
    const spaced = ' finance ,  quarterly ,   ';
    const initial = tags.join(', ');
    store.field(owner, tagsPath, initial).setValue(raw);
    assert.deepEqual(raw.split(',').map((tag) => tag.trim()).filter(Boolean), tags);
    assert.equal(store.field(owner, tagsPath, initial).value, raw);
    assert.equal(store.summary(ownerKeys(owner)).pending, true);
    store.field(owner, tagsPath, initial).setValue(spaced);
    assert.equal(store.field(owner, tagsPath, 'new mount fallback').value, spaced);
    assert.deepEqual(tags, ['finance', 'quarterly']);
    store.acceptSavedFields();
    assert.equal(store.field(owner, tagsPath, initial).value, spaced);
    assert.equal(store.summary(ownerKeys(owner)).pending, false);
});

test('independent editor sessions never share field buffers or errors', () => {
    const first = new WorkflowFieldDraftStore();
    const second = new WorkflowFieldDraftStore();
    const owner = ['task', 'constructor'];
    first.field(owner, schemaPath, initialSchema).setValue('{', parseError);
    first.field(owner, [...decisionPath, 'name'], '').setValue('unfinished');
    assert.equal(second.field(owner, schemaPath, initialSchema).value, initialSchema);
    assert.equal(second.field(owner, schemaPath, initialSchema).error, '');
    assert.equal(second.field(owner, [...decisionPath, 'name'], '').value, '');
    assert.deepEqual(second.summary(ownerKeys(owner)), { pending: false, taskSchemaErrors: new Map() });
});

test('field buffers and UI row IDs never enter the original definition or its save payload', () => {
    const fixture = JSON.parse(fs.readFileSync(
        path.join(__dirname, 'fixtures', 'workflow_flow_authoring.json'), 'utf8',
    ));
    const definition = deepFreeze(fixture.initial);
    const original = structuredClone(definition);
    const scope = { type: 'personal' };
    const expectedPayload = workflowForSave(definition, definition, scope);
    const task = definition.tasks.find((item) => item.id === 'seed-task');
    const repeat = definition.flow.nodes.find((node) => node.kind === 'repeat_until');
    assert.ok(task && repeat);
    const taskOwner = ['task', task.id];
    const nodeOwner = ['node', repeat.id];
    const store = new WorkflowFieldDraftStore();
    const rowIds = store.repeatStateRowIds(nodeOwner, repeat.state.length);

    store.field(taskOwner, schemaPath, JSON.stringify(task.output_contract.schema, null, 2)).setValue('{', parseError);
    store.field(taskOwner, [...decisionPath, 'name'], '').setValue('unfinished_task_field');
    store.field(nodeOwner, ['state', rowIds[0], 'decision', 'enum'], '').setValue(' yes \n no \n');
    store.acceptSavedFields();
    assert.equal(store.summary(ownerKeys(taskOwner, nodeOwner)).taskSchemaErrors.get(task.id), parseError);
    assert.deepEqual(definition, original);
    assert.deepEqual(workflowForSave(definition, definition, scope), expectedPayload);
    const serialized = JSON.stringify(definition);
    assert.ok(rowIds.every((id) => !serialized.includes(id)));
    assert.equal(serialized.includes('unfinished_task_field'), false);
});

test('capture and restore retain raw values, diagnostics and baselines independently of later writes', () => {
    const store = new WorkflowFieldDraftStore();
    const owner = ['task', 'constructor'];
    store.field(owner, schemaPath, initialSchema).setValue('{', parseError);
    store.field(owner, [...decisionPath, 'type'], 'boolean').setValue('enum');
    store.accept(owner, [...decisionPath, 'type']);
    const snapshot = store.capture();
    store.field(owner, schemaPath, initialSchema).setValue('{"type":"object"}');
    store.clear(owner, decisionPath);
    store.retainOwners(new Set());
    assert.equal(snapshot.fields.size, 2);
    store.restore(snapshot);
    assert.equal(store.field(owner, schemaPath, '').value, '{');
    assert.equal(store.field(owner, schemaPath, '').error, parseError);
    assert.equal(store.field(owner, [...decisionPath, 'type'], 'boolean').value, 'enum');
    store.clear(owner, schemaPath);
    assert.equal(store.summary(ownerKeys(owner)).pending, false);
    assert.equal(snapshot.fields.size, 2, 'Restored state must still use copy-on-write mutations.');
});

test('a batch publishes one complete buffer state and a default-only blur creates no buffer', () => {
    const store = new WorkflowFieldDraftStore();
    const owner = ['task', 'seed'];
    const observed = [];
    store.subscribe(() => observed.push(store.capture()));
    store.field(owner, schemaPath, initialSchema).setValue(initialSchema);
    assert.equal(store.capture().fields.size, 0);
    assert.equal(observed.length, 0);
    store.beginBatch();
    store.field(owner, schemaPath, initialSchema).setValue('{', parseError);
    store.field(owner, [...decisionPath, 'name'], '').setValue('pending');
    assert.equal(observed.length, 0);
    store.endBatch();
    assert.equal(observed.length, 1);
    assert.equal(observed[0].fields.size, 2);
    store.field(owner, schemaPath, initialSchema).setValue(initialSchema);
    assert.equal(store.capture().fields.size, 1, 'Returning to the original raw default removes the no-op field.');
    assert.throws(() => store.endBatch(), /No workflow field transaction/);
});

test('restoring Repeat rows never rewinds allocation or mixes surviving row buffers', () => {
    const store = new WorkflowFieldDraftStore();
    const owner = ['node', 'repeat'];
    const rows = store.repeatStateRowIds(owner, 2);
    const pathFor = (id) => ['state', id, 'decision', 'name'];
    store.field(owner, pathFor(rows[0]), '').setValue('first');
    store.field(owner, pathFor(rows[1]), '').setValue('second');
    const before = store.capture();
    store.removeRepeatStateRow(owner, rows[0]);
    const after = store.capture();
    const newRow = store.repeatStateRowIds(owner, 2)[1];
    store.restore(before);
    assert.deepEqual(store.repeatStateRowIds(owner, 2), rows);
    assert.equal(store.field(owner, pathFor(rows[0]), '').value, 'first');
    store.restore(after);
    assert.equal(store.field(owner, pathFor(rows[1]), '').value, 'second');
    assert.equal(store.field(owner, pathFor(rows[0]), '').value, '');
    const another = store.repeatStateRowIds(owner, 2)[1];
    assert.ok(![...rows, newRow].includes(another));
    assert.deepEqual(before.repeatRows.values().next().value.ids, rows);
});
