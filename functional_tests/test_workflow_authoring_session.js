// test_workflow_authoring_session.js
/*
Atomic authoring-session, buffer, replay, and Save payload contracts.
Version: 0.261.123
Implemented in: 0.261.123

Executes the production TypeScript session and field store, without a browser,
Azure, workflow admission or publication. --emit-history-payloads exposes only
valid replay-produced Save/preview payloads to the companion Python compiler test.
*/

const assert = require('node:assert/strict');
const fs = require('node:fs');
const { registerHooks } = require('node:module');
const path = require('node:path');
const { before, test } = require('node:test');
const { pathToFileURL } = require('node:url');

const root = path.resolve(__dirname, '..');
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'workflow_flow_authoring.json'), 'utf8'));
const ts = require(path.join(root, 'application', 'v2_ui', 'node_modules', 'typescript'));
let WorkflowAuthoringSession;
let authoring;
let editor;

async function loadModules() {
    await import(pathToFileURL(path.join(__dirname, 'test_support', 'tsResolve.mjs')));
    const sources = new Map(['WorkflowAuthoringHistory.tsx', 'WorkflowFieldDrafts.tsx'].map((name) => {
        const filename = path.join(root, 'application', 'v2_ui', 'src', 'components', 'workflows', name);
        return [pathToFileURL(filename).href, filename];
    }));
    const hook = registerHooks({
        load(url, context, nextLoad) {
            const filename = sources.get(url);
            if (!filename) return nextLoad(url, context);
            return {
                format: 'module', shortCircuit: true,
                source: ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
                    fileName: filename,
                    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX },
                }).outputText,
            };
        },
    });
    try {
        ({ WorkflowAuthoringSession } = await import([...sources.keys()][0]));
    } finally {
        hook.deregister();
    }
    const moduleUrl = (name) => pathToFileURL(path.join(root, 'application', 'v2_ui', 'src', 'lib', `${name}.ts`));
    [authoring, editor] = await Promise.all([import(moduleUrl('workflowAuthoring')), import(moduleUrl('workflowEditor'))]);
}

function setup(change = () => {}) {
    const original = structuredClone(fixture.initial);
    change(original);
    const session = new WorkflowAuthoringSession(original);
    const errors = [];
    const recoveries = [];
    const rollbacks = [];
    const context = {
        options: structuredClone(fixture.options), readOnly: false, saving: false, commandPending: false,
        selectionId: 'seed-node',
        onError: (message) => errors.push(message),
        onRestore: (...values) => recoveries.push(values),
        onRollback: (...values) => rollbacks.push(values),
    };
    session.configure(context);
    return { session, original, context, errors, recoveries, rollbacks };
}

function command(state, value, confirmed = false) {
    const result = authoring.applyWorkflowEdit(state.session.draft, value, state.context.options, confirmed);
    if (result.status === 'applied') {
        state.session.changeDraft(result.workflow, {
            label: value.type, targetId: value.nodeId ?? result.selectedId,
        });
    } else state.session.reject();
    return result;
}

function replay(state, direction) {
    state.session.request(direction);
    if (state.session.getSnapshot().pending) state.session.confirm();
    assert.equal(state.session.getSnapshot().pending, null);
}

function historyPayloads() {
    const state = setup();
    for (const item of fixture.commands) assert.equal(command(state, structuredClone(item), true).status, 'applied');
    const scope = { type: 'personal' };
    const payload = () => editor.workflowForSave(state.session.draft, state.original, scope);
    const initial = editor.workflowForSave(state.original, state.original, scope);
    const edited = payload();
    while (state.session.getSnapshot().undoLabel) replay(state, 'undo');
    const undone = payload();
    assert.deepEqual(undone, initial);
    while (state.session.getSnapshot().redoLabel) replay(state, 'redo');
    const redone = payload();
    assert.deepEqual(redone, edited);
    return { initial, edited, undone, redone, preview: editor.workflowForFlowPreview(redone) };
}

if (process.argv.includes('--emit-history-payloads')) {
    loadModules().then(() => process.stdout.write(JSON.stringify(historyPayloads()))).catch((error) => {
        console.error(error);
        process.exitCode = 1;
    });
} else {
    before(loadModules);

    test('common fields coalesce, redo invalidates only after a real edit, and authority stays original', () => {
        const state = setup();
        const { session, original } = state;
        for (const name of ['first', 'second', 'third']) session.edit({ label: 'Workflow name', group: 'workflow.name' },
            () => session.changeDraft((current) => ({ ...current, name })));
        session.closeGroup();
        replay(state, 'undo');
        assert.deepEqual(session.draft, original);
        assert.equal(session.getSnapshot().undoLabel, '');
        assert.equal(session.getSnapshot().redoLabel, 'Workflow name');
        session.changeDraft((current) => current);
        assert.equal(session.getSnapshot().redoLabel, 'Workflow name');
        replay(state, 'redo');
        assert.equal(session.draft.name, 'third');
        replay(state, 'undo');
        session.changeDraft((current) => ({ ...current, description: 'different branch' }));
        assert.equal(session.getSnapshot().redoLabel, '');
        assert.equal(session.draft.definition_revision, original.definition_revision);
        assert.deepEqual(session.draft.future_envelope, original.future_envelope);
    });

    test('canonical schema and raw text publish and replay as one complete transaction', () => {
        const state = setup();
        const { session } = state;
        const task = session.draft.tasks.find((item) => item.id === 'seed-task');
        const initialText = JSON.stringify(task.output_contract.schema, null, 2);
        const raw = ' { "type": "object", "properties": {"ready":{"type":"boolean"}}, "required":["ready"] } ';
        const observed = [];
        const observe = () => observed.push({
            raw: session.fields.field(['task', task.id], ['output', 'schema'], initialText).value,
            schema: session.getSnapshot().draft.tasks.find((item) => item.id === task.id).output_contract.schema,
        });
        session.subscribe(observe);
        session.fields.subscribe(observe);
        session.edit({ label: 'Output schema', group: 'schema', targetId: 'seed-node' }, () => {
            session.fields.field(['task', task.id], ['output', 'schema'], initialText).setValue(raw);
            assert.equal(command(state, { type: 'task', taskId: task.id,
                value: { ...task, output_contract: { ...task.output_contract, schema: JSON.parse(raw) } } }).status, 'applied');
        });
        assert.ok(observed.length);
        assert.ok(observed.every((item) => item.raw === raw && item.schema.type === 'object'));
        replay(state, 'undo');
        assert.equal(session.fields.field(['task', task.id], ['output', 'schema'], initialText).value, initialText);
        assert.equal(session.getSnapshot().undoLabel, '');
        replay(state, 'redo');
        assert.equal(session.fields.field(['task', task.id], ['output', 'schema'], '').value, raw);
    });

    test('native capture survives the microtask checkpoint before React bubble handlers', async () => {
        const state = setup();
        const event = new Event('click');
        state.session.beginEvent({ label: 'Compound native action' }, event);
        await Promise.resolve();
        state.session.fields.field(['task', 'seed-task'], ['output', 'schema'], '{}').setValue('{', 'Invalid JSON');
        state.session.changeDraft((draft) => ({ ...draft, name: 'atomic native action' }));
        state.session.finish();
        assert.equal(state.session.getSnapshot().undoLabel, 'Compound native action');
        replay(state, 'undo');
        assert.deepEqual(state.session.draft, state.original);
        assert.equal(state.session.fields.capture().fields.size, 0);
        assert.equal(state.session.getSnapshot().undoLabel, '');
    });

    test('a stopped bubble still commits one whole originating event', async () => {
        const state = setup();
        state.session.beginEvent({ label: 'Stopped propagation' }, new Event('click'));
        state.session.fields.field(['task', 'seed-task'], ['output', 'schema'], '{}').setValue('{', 'Invalid JSON');
        state.session.changeDraft((draft) => ({ ...draft, name: 'stopped event' }));
        await new Promise((resolve) => setTimeout(resolve, 0));
        assert.equal(state.session.getSnapshot().undoLabel, 'Stopped propagation');
        replay(state, 'undo');
        assert.deepEqual(state.session.draft, state.original);
        assert.equal(state.session.fields.capture().fields.size, 0);
        assert.equal(state.session.getSnapshot().undoLabel, '');
    });

    test('raw invalid schema, builder drafts and errors survive owner pruning and restore', () => {
        const state = setup();
        const owner = ['task', 'seed-task'];
        const field = state.session.fields.field(owner, ['output', 'schema'], '{}');
        state.session.edit({ label: 'Raw schema' }, () => field.setValue('{', 'Invalid JSON'));
        state.session.fields.field(owner, ['output', 'decision', 'name'], '').setValue(' unfinished ');
        const before = state.session.fields.capture();
        assert.equal(command(state, { type: 'remove', nodeId: 'seed-node' }, true).status, 'applied');
        assert.equal(state.session.fields.field(owner, ['output', 'schema'], '').value, '');
        replay(state, 'undo');
        assert.deepEqual(state.session.fields.capture(), before);
        assert.equal(state.session.fields.field(owner, ['output', 'schema'], '').error, 'Invalid JSON');
        assert.equal(state.session.draft.tasks.find((task) => task.id === owner[1]).id, owner[1]);
    });

    test('a rejected compound action rolls back its raw buffer writes and retains Redo', () => {
        const state = setup();
        state.session.changeDraft((draft) => ({ ...draft, name: 'new name' }));
        replay(state, 'undo');
        const before = state.session.fields.capture();
        state.session.edit({ label: 'Rejected action' }, () => {
            state.session.fields.field(['task', 'seed-task'], ['output', 'schema'], '{}').setValue('{', 'Invalid JSON');
            assert.equal(command(state, { type: 'remove', nodeId: 'missing-node' }).status, 'rejected');
        });
        assert.deepEqual(state.session.draft, state.original);
        assert.deepEqual(state.session.fields.capture(), before);
        assert.ok(state.session.getSnapshot().redoLabel);
    });

    test('a recording failure retains canonical state, field buffers and both history directions', () => {
        const state = setup();
        state.session.changeDraft((draft) => ({ ...draft, name: 'first' }));
        state.session.changeDraft((draft) => ({ ...draft, description: 'second' }));
        replay(state, 'undo');
        const view = state.session.getSnapshot();
        const fields = state.session.fields.capture();
        const record = state.session.history.record;
        state.session.history.record = () => { throw new Error('Fictional history failure'); };
        const accepted = state.session.edit({ label: 'Fail atomically' }, () => {
            state.session.fields.field(['task', 'seed-task'], ['output', 'schema'], '{}').setValue('{', 'Invalid JSON');
            state.session.changeDraft((draft) => ({ ...draft, name: 'must not survive' }));
        });
        state.session.history.record = record;
        assert.equal(accepted, false);
        assert.equal(state.session.draft, view.draft);
        assert.deepEqual(state.session.fields.capture(), fields);
        assert.equal(state.session.getSnapshot().undoLabel, view.undoLabel);
        assert.equal(state.session.getSnapshot().redoLabel, view.redoLabel);
        assert.match(state.errors.at(-1), /could not be recorded/);
        replay(state, 'redo');
        assert.equal(state.session.draft.description, 'second');
    });

    test('candidate identity, envelope, root, version and structure changes reject atomically', () => {
        for (const update of [
            (draft) => ({ ...draft, id: 'other' }),
            (draft) => ({ ...draft, definition_revision: 'new-cas' }),
            (draft) => ({ ...draft, definition_version: 2 }),
            (draft) => ({ ...draft, group_id: 'other-group' }),
            (draft) => ({ ...draft, active_run_id: 'runtime' }),
            (draft) => ({ ...draft, future_envelope: { changed: true } }),
            (draft) => ({ ...draft, flow: { ...draft.flow, id: 'other-root' } }),
            (draft) => ({ ...draft, tasks: [...draft.tasks, draft.tasks[0]] }),
        ]) {
            const state = setup();
            state.session.edit({ label: 'Invalid candidate' }, () => {
                state.session.fields.field(['task', 'seed-task'], ['output', 'schema'], '{}').setValue('{', 'Invalid JSON');
                state.session.changeDraft(update);
            });
            assert.equal(state.session.draft, state.original);
            assert.equal(state.session.fields.capture().fields.size, 0);
            assert.equal(state.session.getSnapshot().undoLabel, '');
            assert.ok(state.errors.some(Boolean));
        }
    });

    test('oversized removal proposals retain complete buffers and the pre-action selection on cancel', () => {
        const state = setup();
        const owner = ['task', 'seed-task'];
        const text = '{' + 'x'.repeat(16 * 1024 * 1024);
        state.session.fields.field(owner, ['output', 'schema'], '{}').setValue(text, 'Invalid JSON');
        assert.equal(state.session.getSnapshot().pending.kind, 'overflow');
        state.session.confirm();
        assert.equal(state.session.fields.field(owner, ['output', 'schema'], '').value, text);
        state.session.beginEvent({ label: 'Remove oversized owner' }, new Event('click'));
        assert.equal(command(state, { type: 'remove', nodeId: 'seed-node' }, true).status, 'applied');
        state.context.selectionId = 'other-selection';
        state.session.finish();
        assert.equal(state.session.getSnapshot().pending.kind, 'overflow');
        assert.equal(state.rollbacks.at(-1)[2], 'seed-node');
        state.session.cancel();
        assert.equal(state.session.draft, state.original);
        assert.equal(state.session.fields.field(owner, ['output', 'schema'], '').value, text);
        assert.equal(state.session.getSnapshot().undoLabel, '');
        assert.equal(state.session.getSnapshot().redoLabel, '');
    });

    test('lowered task ceilings block task restoration without consuming history', () => {
        const state = setup();
        command(state, { type: 'add', kind: 'task', regionId: 'root' });
        replay(state, 'undo');
        state.context.options = { ...state.context.options, max_tasks: state.original.tasks.length };
        state.session.configure(state.context);
        state.session.request('redo');
        assert.equal(state.session.draft.tasks.length, state.original.tasks.length);
        assert.match(state.errors.at(-1), /task limit/);
        assert.ok(state.session.getSnapshot().redoLabel);
        state.context.options = structuredClone(fixture.options);
        state.session.configure(state.context);
        replay(state, 'redo');
        assert.equal(state.session.draft.tasks.length, state.original.tasks.length + 1);
    });

    test('v2 conversion is an empty v3 history boundary, not a reversible history action', () => {
        const state = setup((draft) => { draft.definition_version = 2; });
        state.session.changeDraft((draft) => ({ ...draft, name: 'Before conversion' }));
        assert.equal(state.session.getSnapshot().undoLabel, '');
        state.session.changeDraft((draft) => ({ ...draft, definition_version: 3 }));
        assert.equal(state.session.getSnapshot().undoLabel, '');
        state.session.changeDraft((draft) => ({ ...draft, name: 'After conversion' }));
        replay(state, 'undo');
        assert.equal(state.session.draft.definition_version, 3);
        assert.equal(state.session.draft.name, 'Before conversion');
        assert.equal(state.session.getSnapshot().undoLabel, '');
    });

    test('replay confirmation cancellation and capability changes never advance the cursor', () => {
        const state = setup();
        assert.equal(command(state, { type: 'add', kind: 'if', regionId: 'root' }).status, 'applied');
        const added = state.session.draft;
        state.session.request('undo');
        assert.equal(state.session.getSnapshot().pending.kind, 'replay');
        state.session.cancel();
        assert.equal(state.session.draft, added);
        assert.equal(state.session.getSnapshot().redoLabel, '');
        state.session.request('undo');
        state.context.options = { ...state.context.options, max_tasks: state.context.options.max_tasks + 1 };
        state.session.configure(state.context);
        state.session.confirm();
        assert.match(state.session.getSnapshot().pending.message, /capabilities changed/i);
        assert.equal(state.session.draft, added);
        state.session.confirm();
        assert.deepEqual(state.session.draft, state.original);
        replay(state, 'redo');
        assert.deepEqual(state.session.draft, added);
    });

    test('redo restores the same newly allocated block identities and NaN maximum', () => {
        const state = setup();
        assert.equal(command(state, { type: 'add', kind: 'repeat_until', regionId: 'root' }).status, 'applied');
        const added = state.session.draft.flow.nodes.at(-1);
        assert.ok(Number.isNaN(added.max_iterations));
        replay(state, 'undo');
        replay(state, 'redo');
        assert.deepEqual(state.session.draft.flow.nodes.at(-1), added);
        assert.ok(Number.isNaN(state.session.draft.flow.nodes.at(-1).max_iterations));
    });

    for (const restriction of ['saving', 'readOnly', 'permission', 'scope', 'active']) {
        test(`${restriction} blocks direct replay and buffer/definition mutation`, () => {
            const state = setup(restriction === 'active' ? (draft) => { draft.active_run_id = 'active-run'; } : undefined);
            if (restriction === 'saving') state.context.saving = true;
            if (restriction === 'readOnly') state.context.readOnly = true;
            if (restriction === 'permission') state.context.options.can_manage = false;
            if (restriction === 'scope') state.context.options.scope = { type: 'group', id: 'different-group' };
            state.session.configure(state.context);
            state.session.changeDraft((draft) => ({ ...draft, name: 'blocked' }));
            state.session.fields.field(['task', 'seed-task'], ['output', 'schema'], '{}').setValue('{', 'Invalid JSON');
            state.session.request('undo');
            assert.deepEqual(state.session.draft, state.original);
            assert.equal(state.session.fields.capture().fields.size, 0);
            assert.equal(state.session.getSnapshot().undoLabel, '');
            assert.ok(state.errors.some(Boolean));
        });
    }

    test('confirmed access loss clears both stacks, buffers and pending proposals permanently', () => {
        const state = setup();
        state.session.fields.field(['task', 'seed-task'], ['output', 'schema'], '{}').setValue('{', 'Invalid JSON');
        command(state, { type: 'add', kind: 'if', regionId: 'root' });
        state.session.request('undo');
        assert.ok(state.session.getSnapshot().pending);
        state.session.invalidate();
        assert.equal(state.session.getSnapshot().pending, null);
        assert.equal(state.session.getSnapshot().undoLabel, '');
        assert.equal(state.session.getSnapshot().redoLabel, '');
        assert.equal(state.session.fields.capture().fields.size, 0);
        assert.equal(state.session.fields.capture().repeatRows.size, 0);
        const retained = state.session.draft;
        state.session.confirm();
        state.session.request('redo');
        state.session.changeDraft((draft) => ({ ...draft, name: 'must not revive' }));
        assert.equal(state.session.draft, retained);
    });

    test('a successful Save clears history without recording a server revision as an edit', () => {
        const state = setup();
        state.session.changeDraft((draft) => ({ ...draft, name: 'saved name' }));
        const saved = { ...state.session.draft, definition_revision: 'new-server-revision' };
        state.session.saved(saved);
        assert.equal(state.session.getSnapshot().undoLabel, '');
        assert.equal(state.session.getSnapshot().redoLabel, '');
        state.session.request('undo');
        assert.equal(state.session.draft.definition_revision, 'new-server-revision');
    });

    test('a Strict Mode release/reattach does not dispose a live editor', async () => {
        const state = setup();
        const release = state.session.retain();
        release();
        const releaseAgain = state.session.retain();
        await Promise.resolve();
        assert.equal(state.session.active, true);
        state.session.changeDraft((draft) => ({ ...draft, name: 'still active' }));
        assert.equal(state.session.draft.name, 'still active');
        releaseAgain();
        await Promise.resolve();
        assert.equal(state.session.active, false);
    });

    test('actual replay Save and preview payloads preserve meaning and exclude editor metadata', () => {
        const payloads = historyPayloads();
        assert.deepEqual(payloads.undone, payloads.initial);
        assert.deepEqual(payloads.redone, payloads.edited);
        assert.equal(payloads.redone.definition_revision, fixture.initial.definition_revision);
        for (const value of Object.values(payloads)) {
            for (const key of ['history', 'fields', 'repeatRows', 'positions', 'selectedId']) assert.equal(Object.hasOwn(value, key), false);
        }
    });
}
