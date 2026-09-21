// test_workflow_flow_authoring_commands.js
/*
Offline contracts for shared List/Flow draft commands.
Version: 0.261.122
Implemented in: 0.261.122

Executes the production TypeScript helper with the repository's Node loader.
The canonical JSON is also compiled by test_workflow_flow_authoring.py.
Use --emit-canonical-payload or --emit-canonical-preview to send actual
command-produced payloads to Python without an intermediate file or workflow run.
*/

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { before, test } = require('node:test');

const root = path.resolve(__dirname, '..');
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'workflow_flow_authoring.json'), 'utf8'));
const supportedKinds = ['task', 'if', 'route', 'for_each', 'repeat_until', 'collect'];
const personalScope = { type: 'personal' };
let authoring;
let editor;
let flow;

async function loadProductionModules() {
    // Register the existing resolver before importing real production ES modules.
    await import(pathToFileURL(path.join(__dirname, 'test_support', 'tsResolve.mjs')));
    const moduleUrl = (name) => pathToFileURL(path.join(root, 'application', 'v2_ui', 'src', 'lib', `${name}.ts`));
    [authoring, editor, flow] = await Promise.all([
        import(moduleUrl('workflowAuthoring')), import(moduleUrl('workflowEditor')), import(moduleUrl('workflowFlow')),
    ]);
}

function clone(value) {
    return structuredClone(value);
}

function deepFreeze(value) {
    if (value && typeof value === 'object' && !Object.isFrozen(value)) {
        Object.values(value).forEach(deepFreeze);
        Object.freeze(value);
    }
    return value;
}

function initialDefinition() {
    return clone(fixture.initial);
}

function expectedDefinition() {
    return { ...initialDefinition(), ...clone(fixture.expected) };
}

function targets(workflow) {
    const result = new Map();
    const walk = (region) => {
        result.set(region.id, region);
        for (const node of region.nodes) {
            result.set(node.id, node);
            if (node.kind === 'if') {
                result.set(node.join.id, node.join);
                walk(node.then);
                walk(node.else);
            } else if (node.kind === 'for_each' || node.kind === 'repeat_until') {
                walk(node.body);
            }
        }
    };
    walk(workflow.flow);
    return result;
}

function node(workflow, id) {
    const value = targets(workflow).get(id);
    assert.ok(value, `Fixture target ${id} must exist.`);
    return value;
}

function task(workflow, id) {
    const value = workflow.tasks.find((entry) => entry.id === id);
    assert.ok(value, `Fixture task ${id} must exist.`);
    return value;
}

function invoke(workflow, command, options = fixture.options, confirmed = false) {
    const beforeValues = [clone(workflow), clone(command), clone(options)];
    const result = authoring.applyWorkflowEdit(deepFreeze(workflow), deepFreeze(command), deepFreeze(options), confirmed);
    assert.deepEqual(workflow, beforeValues[0], 'A command must never mutate its input draft.');
    assert.deepEqual(command, beforeValues[1], 'A command must never mutate the caller-owned field value.');
    assert.deepEqual(options, beforeValues[2], 'A command must never mutate editor capabilities.');
    assert.ok(['applied', 'rejected', 'confirmation_required'].includes(result.status));
    if (result.status === 'applied') {
        assert.equal(typeof result.selectedId, 'string');
        assert.ok(targets(result.workflow).has(result.selectedId), 'Selection must resolve to a surviving canonical target.');
    } else {
        assert.equal(typeof result.message, 'string');
        assert.ok(result.message.length);
        assert.equal(Object.hasOwn(result, 'workflow'), false, 'Rejected/pending edits cannot publish a candidate draft.');
    }
    if (result.status !== 'rejected') {
        assert.ok(Array.isArray(result.impact));
        for (const impact of result.impact) {
            assert.equal(typeof impact.nodeId, 'string');
            assert.equal(typeof impact.field, 'string');
            assert.equal(typeof impact.message, 'string');
            assert.ok(impact.field.length && impact.message.length);
        }
    }
    return result;
}

function applied(workflow, command, options = fixture.options, confirmed = false) {
    const result = invoke(workflow, command, options, confirmed);
    assert.equal(result.status, 'applied', JSON.stringify(result));
    return result.workflow;
}

function rejected(workflow, command, options = fixture.options, confirmed = false) {
    const result = invoke(workflow, command, options, confirmed);
    assert.equal(result.status, 'rejected', JSON.stringify(result));
    return result;
}

function runCanonicalCommands() {
    let workflow = initialDefinition();
    for (const command of fixture.commands) {
        workflow = applied(workflow, clone(command));
    }
    assert.deepEqual(workflow, expectedDefinition());
    return workflow;
}

function canonicalPayload() {
    return editor.workflowForSave(runCanonicalCommands(), initialDefinition(), personalScope);
}

function literalCondition() {
    return { op: 'eq', left: { literal: true }, right: { literal: true } };
}

function simpleDefinition(count = 1) {
    const workflow = initialDefinition();
    const template = task(workflow, 'spare-task');
    workflow.tasks = Array.from({ length: count }, (_, index) => ({
        ...clone(template), id: `catalogue-${index}`, name: `Task ${index}`, order: index + 1,
    }));
    workflow.flow = {
        id: 'root',
        nodes: workflow.tasks.map((entry, index) => ({ id: `node-${index}`, kind: 'task', task_id: entry.id })),
        outputs: [],
    };
    return workflow;
}

function emptyIf(id) {
    return {
        id, kind: 'if', inputs: [], condition: literalCondition(),
        then: { id: `${id}-then`, nodes: [] }, else: { id: `${id}-else`, nodes: [] },
        join: { id: `${id}-join`, exports: [] },
    };
}

function nestedRegions(depth) {
    const workflow = simpleDefinition();
    let region = workflow.flow;
    const leaf = region.nodes.pop();
    for (let index = 1; index < depth; index++) {
        const choice = emptyIf(`depth-${index}`);
        region.nodes.push(choice);
        region = choice.then;
    }
    region.nodes.push(leaf);
    return { workflow, regionId: region.id };
}

function mixedFrames(kinds) {
    const workflow = simpleDefinition(2);
    const contract = clone(task(initialDefinition(), 'seed-task').output_contract);
    workflow.tasks[0].output_contract = contract;
    let region = workflow.flow;
    const leaf = region.nodes.pop();
    kinds.forEach((kind, index) => {
        const id = `frame-${index}`;
        const body = { id: `${id}-body`, nodes: [], outputs: [] };
        let current;
        if (kind === 'for_each') {
            current = {
                id, kind, inputs: [],
                iterable: { kind: 'documents', documents: [{ document_id: 'fictional-document', scope_type: 'personal' }] },
                item_key: 'source_identity', max_items: 1, body,
            };
        } else {
            current = {
                id, kind, max_iterations: 1,
                state: [{
                    name: 'review', initial: { kind: 'node_output', node_id: 'node-0', output: 'json', scope: 'current' },
                    next: 'retained', output_contract: clone(contract),
                }],
                body,
                until: { op: 'eq', left: { input: 'review', path: '/ready' }, right: { literal: true } },
                exports: [],
            };
            body.outputs = [{
                name: 'retained',
                source: { kind: 'repeat_state', loop_id: id, state_name: 'review', scope: 'current' },
                required: true, expected_kind: 'json', allow_partial: false,
            }];
        }
        region.nodes.push(current);
        region = body;
    });
    region.nodes.push(leaf);
    return { workflow, regionId: region.id };
}

function impacted(result, nodeId, fieldPattern) {
    assert.ok(result.impact.some((entry) => entry.nodeId === nodeId && fieldPattern.test(entry.field)),
        `Expected a concrete ${nodeId} reference impact: ${JSON.stringify(result.impact)}`);
}

function fixtureCommands(workflow) {
    return [
        { type: 'add', regionId: 'root', kind: 'task' },
        { type: 'move', nodeId: 'constructor', targetRegionId: 'then-region' },
        { type: 'remove', nodeId: 'constructor' },
        { type: 'node', nodeId: 'route-node', value: clone(node(workflow, 'route-node')) },
        { type: 'task', taskId: 'report-task', value: clone(task(workflow, 'report-task')) },
        { type: 'outputs', regionId: 'root', value: [] },
        { type: 'join', nodeId: 'choice', value: clone(node(workflow, 'choice').join) },
        { type: 'limits', value: { max_executions: 10, deadline_seconds: 60 } },
    ];
}

function registerTests() {
    test('compiler preview omits only the non-authored envelope without changing the saved draft', () => {
        const saved = canonicalPayload();
        saved.active_run_id = 'runtime-metadata';
        const before = clone(saved);
        const preview = editor.workflowForFlowPreview(deepFreeze(saved));
        assert.deepEqual(saved, before);
        assert.equal(preview.id, saved.id);
        assert.equal(preview.definition_revision, saved.definition_revision);
        assert.equal(Object.hasOwn(preview, 'future_envelope'), false);
        assert.equal(Object.hasOwn(preview, 'metadata'), false);
        assert.equal(Object.hasOwn(preview, 'active_run_id'), false);
        for (const field of editor.WORKFLOW_DEFINITION_FIELDS) {
            assert.deepEqual(preview[field], saved[field], field);
        }
        assert.deepEqual(preview.tasks, saved.tasks);
        assert.deepEqual(preview.flow, saved.flow);
        assert.deepEqual(canonicalPayload().future_envelope, fixture.initial.future_envelope);
    });

    test('compiler preview keeps every authored field and scope identity, including legacy authored settings', () => {
        const saved = canonicalPayload();
        for (const field of editor.WORKFLOW_DEFINITION_FIELDS) {
            if (!Object.hasOwn(saved, field)) saved[field] = { retained: field };
        }
        saved.user_id = 'fictional-owner';
        saved.group_id = 'fictional-group';
        const preview = editor.workflowForFlowPreview(deepFreeze(saved));
        assert.deepEqual(Object.keys(preview).sort(), Object.keys(saved)
            .filter((key) => editor.WORKFLOW_DEFINITION_FIELDS.includes(key) ||
                ['id', 'definition_revision', 'user_id', 'group_id'].includes(key)).sort());
        for (const [key, value] of Object.entries(preview)) assert.deepEqual(value, saved[key]);
    });

    test('compiler preview never hides unsupported nested executable fields', () => {
        const saved = canonicalPayload();
        saved.flow.nodes[0].future_control = { execute_in_parallel: true };
        saved.tasks[0].future_runner = { enabled: true };
        const preview = editor.workflowForFlowPreview(deepFreeze(saved));
        assert.deepEqual(preview.flow, saved.flow);
        assert.deepEqual(preview.tasks, saved.tasks);
        assert.match(flow.flowUnsupportedReason(preview), /unsupported|newer|unknown/i);
    });

    test('canonical commands preserve immutability, IDs, catalogue order, CAS, and the unknown envelope', () => {
        const original = initialDefinition();
        const workflow = runCanonicalCommands();
        assert.notEqual(workflow, original);
        assert.deepEqual([...targets(workflow).keys()].sort(), [...targets(original).keys()].sort());
        assert.deepEqual(workflow.tasks.map((entry) => entry.id), original.tasks.map((entry) => entry.id));
        assert.equal(node(workflow, 'constructor').task_id, 'spare-task');
        assert.equal(workflow.tasks[0].id, 'report-task');
        assert.equal(workflow.flow.nodes[0].id, 'seed-node');
        assert.equal(workflow.definition_revision, original.definition_revision);
        assert.deepEqual(workflow.metadata, original.metadata);
        assert.deepEqual(workflow.future_envelope, original.future_envelope);
        assert.deepEqual(flow.analyzeWorkflowFlow(workflow).errors, []);
        assert.deepEqual(editor.workflowValidationErrors(workflow, fixture.options), []);
        assert.deepEqual(canonicalPayload(), editor.workflowForSave(expectedDefinition(), original, personalScope));
    });

    test('save keeps the original revision and excludes geometry, buffers, selection, and preview state', () => {
        const original = initialDefinition();
        const draft = runCanonicalCommands();
        draft.definition_revision = 'preview-must-not-replace-the-saved-cas-token';
        draft.positions = new Map([['constructor', { x: 123, y: 456 }]]);
        draft.viewport = { x: 10, y: 20, zoom: 1.5 };
        draft.selectedId = 'constructor';
        draft.fieldBuffers = { 'seed-task.schema': '{ unfinished' };
        draft.compilerPreview = { nodes: [{ id: 'not-an-executable-node' }], edges: [] };
        const payload = editor.workflowForSave(draft, original, personalScope);
        assert.deepEqual(payload, editor.workflowForSave(expectedDefinition(), original, personalScope));
        assert.equal(payload.definition_revision, original.definition_revision);
        for (const field of ['positions', 'viewport', 'selectedId', 'fieldBuffers', 'compilerPreview']) {
            assert.equal(Object.hasOwn(payload, field), false);
        }
    });

    for (const kind of supportedKinds) {
        test(`add ${kind} inserts at the explicit anchor with fresh structural IDs only`, () => {
            const workflow = simpleDefinition(2);
            const previousIds = new Set(targets(workflow).keys());
            const result = invoke(workflow, { type: 'add', regionId: 'root', kind, beforeId: 'node-1' });
            assert.equal(result.status, 'applied', JSON.stringify(result));
            const next = result.workflow;
            const added = next.flow.nodes[1];
            assert.equal(added.id, result.selectedId);
            assert.equal(added.kind, kind);
            assert.equal(next.flow.nodes[0].id, 'node-0');
            assert.equal(next.flow.nodes[2].id, 'node-1');
            assert.equal(previousIds.has(added.id), false);
            const cost = kind === 'if' ? 4 : ['for_each', 'repeat_until'].includes(kind) ? 2 : 1;
            assert.equal(targets(next).size, previousIds.size + cost);
            for (const id of targets(next).keys()) assert.match(id, /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/);
            assert.equal(next.tasks.length, workflow.tasks.length + (kind === 'task' ? 1 : 0));
            if (kind === 'task') {
                assert.equal(task(next, added.task_id).instructions, '');
                assert.deepEqual(task(next, added.task_id).inputs, []);
            }
            for (const current of workflow.flow.nodes) assert.deepEqual(node(next, current.id), current);
            assert.equal(next.definition_revision, workflow.definition_revision);
        });
    }

    test('add without an anchor appends and cannot turn an unknown advertised kind into a supported one', () => {
        const next = applied(simpleDefinition(), { type: 'add', regionId: 'root', kind: 'task' });
        assert.equal(next.flow.nodes[0].id, 'node-0');
        assert.equal(next.flow.nodes.length, 2);
        const options = clone(fixture.options);
        options.supported_node_kinds.push('future_control');
        rejected(simpleDefinition(), { type: 'add', regionId: 'root', kind: 'future_control' }, options);
    });

    test('new Repeat keeps its explicit maximum unset through further edits instead of applying an admin default', () => {
        const result = invoke(simpleDefinition(), { type: 'add', regionId: 'root', kind: 'repeat_until' });
        assert.equal(result.status, 'applied', JSON.stringify(result));
        const repeatId = result.selectedId;
        assert.ok(Number.isNaN(node(result.workflow, repeatId).max_iterations));
        assert.ok(editor.workflowValidationErrors(result.workflow, fixture.options).some((message) => /explicit maximum/i.test(message)));
        const next = applied(result.workflow, { type: 'limits', value: { max_executions: Number.NaN, deadline_seconds: 60 } });
        assert.ok(Number.isNaN(node(next, repeatId).max_iterations));
        assert.ok(Number.isNaN(next.limits.max_executions));
        assert.deepEqual(node(next, repeatId).state, []);
        assert.deepEqual(node(next, repeatId).body.outputs, []);
        const structure = authoring.workflowDraftStructure(next);
        assert.deepEqual(structure.edges, []);
        assert.equal(Object.hasOwn(structure.nodes.find((entry) => entry.id === repeatId), 'max_iterations'), false);
        assert.deepEqual(structure.nodes.map((entry) => entry.id).sort(), [...targets(next).keys()].sort());
        assert.ok(Number.isNaN(node(next, repeatId).max_iterations));
        for (const field of ['source', 'revision', 'definition_revision']) {
            assert.equal(Object.hasOwn(structure, field), false);
        }
    });

    test('draft display structure retains canonical raw IDs without fabricating inspection or execution metadata', () => {
        const workflow = deepFreeze(expectedDefinition());
        const before = clone(workflow);
        const structure = authoring.workflowDraftStructure(workflow);
        assert.deepEqual(workflow, before);
        assert.equal(structure.root_region_id, workflow.flow.id);
        assert.deepEqual(structure.nodes.map((entry) => entry.id).sort(), [...targets(workflow).keys()].sort());
        assert.equal(structure.nodes.find((entry) => entry.id === 'constructor').task_id, 'spare-task');
        assert.deepEqual(structure.edges, []);
        for (const value of [structure, ...structure.nodes]) {
            for (const field of ['source', 'revision', 'definition_revision', 'execution_id', 'run_id']) {
                assert.equal(Object.hasOwn(value, field), false);
            }
        }
    });

    test('non-JSON unfinished envelope values survive edits without a JSON cloning round trip', () => {
        const workflow = simpleDefinition();
        workflow.future_envelope = { pending: Number.NaN, explicitlyUnset: undefined, values: [false, 0, null] };
        const next = applied(workflow, { type: 'add', regionId: 'root', kind: 'task' });
        assert.ok(Number.isNaN(next.future_envelope.pending));
        assert.equal(Object.hasOwn(next.future_envelope, 'explicitlyUnset'), true);
        assert.deepEqual(next.future_envelope.values, [false, 0, null]);
    });

    test('task maximum is configurable, capped at 100, and does not prevent adding a control', () => {
        const limited = { ...clone(fixture.options), max_tasks: 2 };
        const atLimit = applied(simpleDefinition(), { type: 'add', regionId: 'root', kind: 'task' }, limited);
        assert.equal(atLimit.tasks.length, 2);
        rejected(atLimit, { type: 'add', regionId: 'root', kind: 'task' }, limited);
        assert.equal(applied(atLimit, { type: 'add', regionId: 'root', kind: 'if' }, limited).tasks.length, 2);
        const inflated = { ...clone(fixture.options), max_tasks: 999 };
        const hardLimit = applied(simpleDefinition(99), { type: 'add', regionId: 'root', kind: 'task' }, inflated);
        assert.equal(hardLimit.tasks.length, 100);
        rejected(hardLimit, { type: 'add', regionId: 'root', kind: 'task' }, inflated);
    });

    test('a lowered workspace task ceiling permits repair but never admits more tasks or bypasses save validation', () => {
        const original = simpleDefinition(4);
        const options = { ...clone(fixture.options), max_tasks: 2 };
        const hasTaskLimitError = (workflow) => editor.workflowValidationErrors(workflow, options)
            .some((message) => /at most 2 tasks/.test(message));
        assert.equal(hasTaskLimitError(original), true);
        rejected(original, { type: 'add', regionId: 'root', kind: 'task' }, options);
        assert.equal(applied(original, { type: 'add', regionId: 'root', kind: 'if' }, options).tasks.length, 4);
        const updatedTask = { ...clone(task(original, 'catalogue-0')), instructions: 'Repair the existing saved task.' };
        let current = applied(original, { type: 'task', taskId: updatedTask.id, value: updatedTask }, options);
        current = applied(current, { type: 'move', nodeId: 'node-3', targetRegionId: 'root', beforeId: 'node-0' }, options);
        assert.equal(current.tasks.length, 4);
        assert.equal(hasTaskLimitError(current), true);
        const removal = { type: 'remove', nodeId: 'node-1' };
        assert.equal(invoke(current, removal, options).status, 'confirmation_required');
        current = applied(current, removal, options, true);
        assert.equal(current.tasks.length, 3);
        assert.equal(hasTaskLimitError(current), true);
        rejected(current, { type: 'add', regionId: 'root', kind: 'task' }, options);
        current = applied(current, { type: 'remove', nodeId: 'node-2' }, options, true);
        assert.equal(current.tasks.length, 2);
        assert.deepEqual(editor.workflowValidationErrors(current, options), []);
        assert.deepEqual(task(current, updatedTask.id), updatedTask);
        assert.equal(editor.workflowForSave(current, original, personalScope).definition_revision, original.definition_revision);
        rejected(current, { type: 'add', regionId: 'root', kind: 'task' }, options);
        const oneTask = applied(current, { type: 'remove', nodeId: 'node-3' }, options, true);
        const backAtLimit = applied(oneTask, { type: 'add', regionId: 'root', kind: 'task' }, options);
        assert.equal(backAtLimit.tasks.length, 2);
        assert.equal(hasTaskLimitError(backAtLimit), false);
        assert.equal(options.max_tasks, 2);
    });

    test('the 256 structural-ID ceiling includes root, both branch regions, and every join', () => {
        const workflow = simpleDefinition(3);
        workflow.flow.nodes.push(...Array.from({ length: 62 }, (_, index) => emptyIf(`if-${index}`)));
        assert.equal(targets(workflow).size, 252);
        const boundary = applied(workflow, { type: 'add', regionId: 'root', kind: 'if' });
        assert.equal(targets(boundary).size, 256);
        for (const kind of supportedKinds) rejected(boundary, { type: 'add', regionId: 'root', kind });
        const oneOver = simpleDefinition(4);
        oneOver.flow.nodes.push(...Array.from({ length: 62 }, (_, index) => emptyIf(`if-${index}`)));
        assert.equal(targets(oneOver).size, 253);
        rejected(oneOver, { type: 'add', regionId: 'root', kind: 'if' });
    });

    test('root is depth one: depth-four tasks are legal but another child region is not', () => {
        const { workflow, regionId } = nestedRegions(3);
        const next = applied(workflow, { type: 'add', regionId, kind: 'if' });
        const added = node(next, regionId).nodes.at(-1);
        const depthFour = applied(next, { type: 'add', regionId: added.then.id, kind: 'task' });
        assert.equal(authoring.indexWorkflowDraft(depthFour).get(added.then.id).depth, 4);
        for (const kind of ['if', 'for_each', 'repeat_until']) {
            rejected(depthFour, { type: 'add', regionId: added.then.id, kind });
        }
        rejected(depthFour, { type: 'move', nodeId: 'depth-2', targetRegionId: added.then.id });
    });

    for (const kinds of [
        ['for_each', 'repeat_until', 'for_each'],
        ['repeat_until', 'for_each', 'repeat_until'],
    ]) {
        test(`at most three mixed frames: ${kinds.join(' / ')}`, () => {
            const { workflow, regionId } = mixedFrames(kinds);
            assert.deepEqual(editor.workflowValidationErrors(workflow, fixture.options), []);
            const next = applied(workflow, { type: 'add', regionId, kind: 'task' });
            assert.equal(authoring.indexWorkflowDraft(next).get(regionId).loopIds.length, 3);
            for (const kind of ['for_each', 'repeat_until']) {
                rejected(next, { type: 'add', regionId, kind });
            }
        });
    }

    test('same-region moves respect before/end positions without reordering the catalogue', () => {
        const workflow = simpleDefinition(3);
        const originalTasks = clone(workflow.tasks);
        const first = applied(workflow, { type: 'move', nodeId: 'node-2', targetRegionId: 'root', beforeId: 'node-0' });
        assert.deepEqual(first.flow.nodes.map((entry) => entry.id), ['node-2', 'node-0', 'node-1']);
        const last = applied(first, { type: 'move', nodeId: 'node-0', targetRegionId: 'root' });
        assert.deepEqual(last.flow.nodes.map((entry) => entry.id), ['node-2', 'node-1', 'node-0']);
        assert.deepEqual(last.tasks, originalTasks);
        const unchanged = invoke(last, { type: 'move', nodeId: 'node-0', targetRegionId: 'root', beforeId: 'node-0' });
        assert.equal(unchanged.status, 'applied');
        assert.equal(unchanged.workflow, last);
        assert.deepEqual(unchanged.impact, []);
    });

    test('cross-region before/end moves preserve legal constructor identity and subtree order', () => {
        const original = initialDefinition();
        const thenDraft = applied(original, { type: 'move', nodeId: 'constructor', targetRegionId: 'then-region', beforeId: 'yes-node' });
        assert.deepEqual(node(thenDraft, 'then-region').nodes.map((entry) => entry.id), ['constructor', 'yes-node']);
        const elseDraft = applied(thenDraft, { type: 'move', nodeId: 'constructor', targetRegionId: 'else-region' });
        assert.deepEqual(node(elseDraft, 'else-region').nodes.map((entry) => entry.id), ['no-node', 'constructor']);
        assert.equal(authoring.indexWorkflowDraft(elseDraft).get('constructor').node.task_id, 'spare-task');
        assert.deepEqual([...targets(elseDraft).keys()].sort(), [...targets(original).keys()].sort());
        assert.deepEqual(elseDraft.tasks, original.tasks);
    });

    test('a confirmed cross-region block move retains every descendant identity and its exact outside consumers', () => {
        const workflow = expectedDefinition();
        const command = { type: 'move', nodeId: 'each-node', targetRegionId: 'then-region', beforeId: 'yes-node' };
        const pending = invoke(workflow, command);
        assert.equal(pending.status, 'confirmation_required');
        impacted(pending, 'collect-node', /source/);
        const next = applied(workflow, command, fixture.options, true);
        assert.deepEqual(node(next, 'each-node'), node(workflow, 'each-node'));
        assert.deepEqual(node(next, 'collect-node'), node(workflow, 'collect-node'));
        assert.deepEqual(next.tasks, workflow.tasks);
        assert.deepEqual([...targets(next).keys()].sort(), [...targets(workflow).keys()].sort());
        assert.deepEqual(node(next, 'then-region').nodes.map((entry) => entry.id), ['constructor', 'each-node', 'yes-node']);
        assert.ok(editor.workflowValidationErrors(next, fixture.options).length);
    });

    test('self/descendant reparenting and independent region/join moves or removals are rejected', () => {
        const workflow = initialDefinition();
        for (const command of [
            { type: 'move', nodeId: 'choice', targetRegionId: 'then-region' },
            { type: 'move', nodeId: 'each-node', targetRegionId: 'each-body' },
            { type: 'move', nodeId: 'repeat-node', targetRegionId: 'repeat-body' },
            ...['root', 'then-region', 'each-body', 'choice-join'].flatMap((nodeId) => [
                { type: 'move', nodeId, targetRegionId: 'root' }, { type: 'remove', nodeId },
            ]),
        ]) rejected(workflow, command, fixture.options, true);
    });

    test('missing targets and anchors, including anchors in another region, are atomic rejections', () => {
        const workflow = initialDefinition();
        for (const command of [
            { type: 'add', regionId: 'gone', kind: 'task' },
            { type: 'add', regionId: 'root', kind: 'task', beforeId: 'gone' },
            { type: 'add', regionId: 'root', kind: 'task', beforeId: 'yes-node' },
            { type: 'move', nodeId: 'gone', targetRegionId: 'root' },
            { type: 'move', nodeId: 'constructor', targetRegionId: 'gone' },
            { type: 'move', nodeId: 'constructor', targetRegionId: 'root', beforeId: 'gone' },
            { type: 'move', nodeId: 'constructor', targetRegionId: 'root', beforeId: 'yes-node' },
            { type: 'remove', nodeId: 'gone' },
            { type: 'outputs', regionId: 'gone', value: [] },
            { type: 'outputs', regionId: 'then-region', value: [] },
            { type: 'task', taskId: 'gone', value: clone(workflow.tasks[0]) },
            { type: 'node', nodeId: 'gone', value: clone(node(workflow, 'route-node')) },
            { type: 'join', nodeId: 'gone', value: clone(node(workflow, 'choice').join) },
        ]) rejected(workflow, command);
    });

    test('reference-breaking move requires confirmation and never silently retargets consumers', () => {
        const workflow = expectedDefinition();
        const command = { type: 'move', nodeId: 'seed-node', targetRegionId: 'root' };
        const pending = invoke(workflow, command);
        assert.equal(pending.status, 'confirmation_required');
        impacted(pending, 'choice', /inputs/);
        impacted(pending, 'choice', /condition/);
        impacted(pending, 'route-node', /inputs/);
        impacted(pending, 'repeat-node', /initial/);
        const confirmed = invoke(workflow, command, fixture.options, true);
        assert.equal(confirmed.status, 'applied');
        assert.deepEqual(confirmed.impact, pending.impact);
        assert.equal(confirmed.workflow.flow.nodes.at(-1).id, 'seed-node');
        assert.deepEqual(confirmed.workflow.tasks, workflow.tasks);
        for (const id of ['choice', 'route-node', 'repeat-node']) {
            assert.deepEqual(node(confirmed.workflow, id), node(workflow, id));
        }
        assert.ok(editor.workflowValidationErrors(confirmed.workflow, fixture.options).length);
    });

    test('removing a subtree is cancelable and removes only its own task-catalogue entries on confirmation', () => {
        const workflow = expectedDefinition();
        const command = { type: 'remove', nodeId: 'choice' };
        const pending = invoke(workflow, command);
        assert.equal(pending.status, 'confirmation_required');
        impacted(pending, 'report-node', /inputs/);
        assert.deepEqual(workflow, expectedDefinition(), 'Dismissing confirmation means dispatching no second command.');
        const confirmed = invoke(workflow, command, fixture.options, true);
        assert.equal(confirmed.status, 'applied');
        assert.equal(confirmed.selectedId, 'each-node');
        assert.deepEqual(confirmed.workflow.tasks.map((entry) => entry.id), ['report-task', 'each-task', 'seed-task', 'repeat-task']);
        assert.deepEqual(task(confirmed.workflow, 'report-task').inputs, task(workflow, 'report-task').inputs);
        assert.deepEqual(confirmed.workflow.flow.outputs, workflow.flow.outputs);
        for (const id of ['choice', 'choice-join', 'then-region', 'else-region', 'constructor', 'yes-node', 'no-node']) {
            assert.equal(targets(confirmed.workflow).has(id), false);
        }
        assert.ok(editor.workflowValidationErrors(confirmed.workflow, fixture.options).length);
    });

    test('removing a producer reports Collect, body/root outputs, join exports, and Run-when consumers', () => {
        const workflow = expectedDefinition();
        const withoutLoop = invoke(workflow, { type: 'remove', nodeId: 'each-node' });
        assert.equal(withoutLoop.status, 'confirmation_required');
        impacted(withoutLoop, 'collect-node', /source/);
        const withoutBodyTask = invoke(workflow, { type: 'remove', nodeId: 'each-task-node' });
        impacted(withoutBodyTask, 'each-body', /outputs/);
        const withoutBranchTask = invoke(workflow, { type: 'remove', nodeId: 'yes-node' });
        impacted(withoutBranchTask, 'choice-join', /exports.*then/);
        const withoutReport = invoke(workflow, { type: 'remove', nodeId: 'report-node' });
        impacted(withoutReport, 'root', /outputs/);
        impacted(withoutReport, 'route-node', /target/);
        const conditional = clone(workflow);
        node(conditional, 'report-node').run_when = {
            op: 'eq', left: { input: 'decision', path: '/ready' }, right: { literal: true },
        };
        impacted(invoke(conditional, { type: 'remove', nodeId: 'repeat-node' }), 'report-node', /run_when/);
    });

    test('moving a current-document task outside its loop retains exact item and Analyze selectors', () => {
        const workflow = expectedDefinition();
        const command = { type: 'move', nodeId: 'each-task-node', targetRegionId: 'root', beforeId: 'report-node' };
        const pending = invoke(workflow, command);
        assert.equal(pending.status, 'confirmation_required');
        impacted(pending, 'each-task-node', /inputs/);
        impacted(pending, 'each-task-node', /document_action/);
        impacted(pending, 'each-body', /outputs/);
        const next = applied(workflow, command, fixture.options, true);
        assert.deepEqual(task(next, 'each-task'), task(workflow, 'each-task'));
        assert.deepEqual(node(next, 'each-body').outputs, node(workflow, 'each-body').outputs);
        assert.ok(editor.workflowValidationErrors(next, fixture.options).some((message) => /enclosing|body scope/i.test(message)));
    });

    test('a moved branch-exit route keeps the original exit target and reports its now-invalid scope', () => {
        const workflow = simpleDefinition();
        const choice = emptyIf('exit-owner');
        const route = {
            id: 'branch-exit', kind: 'route', inputs: [], condition: literalCondition(),
            target: { exit_region_id: choice.then.id },
        };
        choice.then.nodes.push(route);
        workflow.flow.nodes.push(choice);
        const command = { type: 'move', nodeId: route.id, targetRegionId: choice.else.id };
        const pending = invoke(workflow, command);
        assert.equal(pending.status, 'confirmation_required');
        impacted(pending, route.id, /target/);
        const next = applied(workflow, command, fixture.options, true);
        assert.deepEqual(node(next, route.id).target, { exit_region_id: choice.then.id });
        assert.ok(editor.workflowValidationErrors(next, fixture.options).some((message) => /exit.*branch/i.test(message)));
    });

    test('removing a saved collection reports both the For-each binding and its iterable input alias', () => {
        const workflow = expectedDefinition();
        const sourceTask = clone(task(workflow, 'each-task'));
        sourceTask.id = 'rows-source-task';
        sourceTask.order = workflow.tasks.length + 1;
        sourceTask.inputs = [];
        sourceTask.document_action = { type: 'none' };
        workflow.tasks.push(sourceTask);
        workflow.flow.nodes.unshift({ id: 'rows-source-node', kind: 'task', task_id: sourceTask.id });
        const loop = node(workflow, 'each-node');
        loop.inputs = [{
            name: 'saved_rows', source: { kind: 'node_output', node_id: 'rows-source-node', output: 'records', scope: 'current' },
            required: true, expected_kind: 'records', allow_partial: false,
        }];
        loop.iterable = { kind: 'input', name: 'saved_rows' };
        task(workflow, 'each-task').document_action = { type: 'none' };
        assert.deepEqual(editor.workflowValidationErrors(workflow, fixture.options), []);
        const command = { type: 'remove', nodeId: 'rows-source-node' };
        const pending = invoke(workflow, command);
        assert.equal(pending.status, 'confirmation_required');
        impacted(pending, loop.id, /inputs/);
        impacted(pending, loop.id, /iterable/);
        const next = applied(workflow, command, fixture.options, true);
        assert.deepEqual(node(next, loop.id).inputs, loop.inputs);
        assert.deepEqual(node(next, loop.id).iterable, loop.iterable);
    });

    test('a pending removal is recomputed against the current draft and revoked capability is not bypassed', () => {
        const workflow = expectedDefinition();
        const command = { type: 'remove', nodeId: 'choice' };
        assert.equal(invoke(workflow, command).status, 'confirmation_required');
        const report = clone(task(workflow, 'report-task'));
        report.inputs.push({ ...clone(report.inputs[0]), name: 'new_consumer' });
        const current = applied(workflow, { type: 'task', taskId: report.id, value: report });
        const next = invoke(current, command, fixture.options, true);
        assert.equal(next.status, 'applied');
        impacted(next, 'report-node', /new_consumer/);
        assert.deepEqual(task(next.workflow, 'report-task').inputs, report.inputs);
        rejected(current, command, { ...clone(fixture.options), can_manage: false }, true);
        rejected(next.workflow, command, fixture.options, true);
    });

    test('even an unreferenced removal requires confirmation and selection falls back to its region', () => {
        const workflow = simpleDefinition(2);
        const choice = emptyIf('empty');
        workflow.flow.nodes.push(choice);
        const pending = invoke(workflow, { type: 'remove', nodeId: 'node-1' });
        assert.equal(pending.status, 'confirmation_required');
        const moved = applied(workflow, { type: 'move', nodeId: 'node-1', targetRegionId: choice.then.id });
        const result = invoke(moved, { type: 'remove', nodeId: 'node-1' }, fixture.options, true);
        assert.equal(result.status, 'applied');
        assert.equal(result.selectedId, choice.then.id);
    });

    test('the last task is protected directly and when it is inside a removed subtree', () => {
        rejected(simpleDefinition(), { type: 'remove', nodeId: 'node-0' }, fixture.options, true);
        const workflow = simpleDefinition();
        const choice = emptyIf('only-container');
        choice.then.nodes = workflow.flow.nodes;
        workflow.flow.nodes = [choice];
        rejected(workflow, { type: 'remove', nodeId: choice.id }, fixture.options, true);
    });

    for (const guard of ['permission', 'readonly', 'active-run', 'legacy', 'unadvertised-version']) {
        test(`${guard} rejects every command, including explicitly confirmed edits`, () => {
            const workflow = initialDefinition();
            const options = clone(fixture.options);
            if (guard === 'permission') options.can_manage = false;
            if (guard === 'readonly') workflow.editor_readonly_reason = 'Preserved unsupported definition.';
            if (guard === 'active-run') workflow.active_run_id = 'active-run-not-to-be-executed';
            if (guard === 'legacy') workflow.definition_version = 2;
            if (guard === 'unadvertised-version') options.supported_definition_versions = [1, 2];
            for (const command of fixtureCommands(workflow)) rejected(workflow, command, options, true);
        });
    }

    for (const [label, groupId, scope] of [
        ['personal options for a group workflow', 'group-alpha', { type: 'personal' }],
        ['group options for a personal workflow', undefined, { type: 'group', id: 'group-alpha' }],
        ['options for a different group', 'group-alpha', { type: 'group', id: 'group-beta' }],
        ['group options without an explicit group ID', 'group-alpha', { type: 'group' }],
    ]) {
        test(`${label} reject every command even after confirmation`, () => {
            const workflow = initialDefinition();
            if (groupId !== undefined) workflow.group_id = groupId;
            const options = { ...clone(fixture.options), scope };
            for (const command of fixtureCommands(workflow)) {
                assert.match(rejected(workflow, command, options, true).message, /scope|workspace/i);
            }
        });
    }

    test('matching explicitly scoped group options allow edits while preserving group identity and original CAS', () => {
        const workflow = simpleDefinition(2);
        workflow.group_id = 'group-alpha';
        const options = { ...clone(fixture.options), scope: { type: 'group', id: workflow.group_id } };
        const updated = { ...clone(task(workflow, 'catalogue-0')), instructions: 'Edit only this authorized group draft.' };
        const next = applied(workflow, { type: 'task', taskId: updated.id, value: updated }, options);
        assert.deepEqual(editor.workflowValidationErrors(next, options), []);
        const payload = editor.workflowForSave(next, workflow, { type: 'group', groupId: workflow.group_id });
        assert.equal(payload.group_id, 'group-alpha');
        assert.equal(payload.definition_revision, workflow.definition_revision);
        assert.equal(payload.tasks[0].instructions, updated.instructions);
        assert.deepEqual(payload.flow, workflow.flow);
    });

    test('configure guards task/node identity, owned regions, subtree order, and the owning join', () => {
        const workflow = expectedDefinition();
        const originalTask = clone(task(workflow, 'report-task'));
        for (const value of [{ ...originalTask, id: 'replacement' }, { ...originalTask, type: 'future_task' }]) {
            rejected(workflow, { type: 'task', taskId: originalTask.id, value });
        }
        const taskNode = node(workflow, 'seed-node');
        for (const value of [
            { ...taskNode, id: 'replacement' }, { ...taskNode, task_id: 'report-task' },
            { ...clone(node(workflow, 'route-node')), id: taskNode.id },
        ]) rejected(workflow, { type: 'node', nodeId: taskNode.id, value });
        const choice = node(workflow, 'choice');
        const reordered = clone(choice);
        reordered.then.nodes.reverse();
        for (const value of [
            { ...clone(choice), then: { ...clone(choice.then), id: 'replacement-region' } },
            { ...clone(choice), join: { ...clone(choice.join), id: 'replacement-join' } },
            reordered,
        ]) rejected(workflow, { type: 'node', nodeId: choice.id, value });
        const loop = clone(node(workflow, 'each-node'));
        loop.body.nodes = [];
        rejected(workflow, { type: 'node', nodeId: loop.id, value: loop });
        rejected(workflow, { type: 'join', nodeId: choice.id, value: { ...clone(choice.join), id: 'other' } });
        rejected(workflow, { type: 'join', nodeId: choice.join.id, value: clone(choice.join) });
    });

    test('configure resolves the latest node/task and rejects an explicitly stale expected snapshot', () => {
        const workflow = expectedDefinition();
        const originalTask = clone(task(workflow, 'report-task'));
        const currentTask = { ...clone(originalTask), instructions: 'The latest edit must remain.' };
        const first = applied(workflow, { type: 'task', taskId: originalTask.id, value: currentTask, expected: originalTask });
        rejected(first, { type: 'task', taskId: originalTask.id, value: originalTask, expected: originalTask });
        const originalNode = clone(node(first, 'route-node'));
        const currentNode = { ...clone(originalNode), condition: literalCondition() };
        const second = applied(first, { type: 'node', nodeId: originalNode.id, value: currentNode, expected: originalNode });
        rejected(second, { type: 'node', nodeId: originalNode.id, value: originalNode, expected: originalNode });
        assert.deepEqual(task(second, originalTask.id), currentTask);
        assert.deepEqual(node(second, originalNode.id), currentNode);
    });

    test('binding and output renames retain dependent selectors as repairable validation errors', () => {
        const workflow = expectedDefinition();
        const bodyOutputs = clone(node(workflow, 'each-body').outputs);
        bodyOutputs[0].name = 'renamed_rows';
        const next = applied(workflow, { type: 'outputs', regionId: 'each-body', value: bodyOutputs });
        assert.equal(node(next, 'collect-node').source.output, 'rows');
        assert.ok(editor.workflowValidationErrors(next, fixture.options).some((message) => /Collect/.test(message)));
        const repeatOutputs = clone(node(next, 'repeat-body').outputs);
        repeatOutputs[0].name = 'renamed_decision';
        const repeated = applied(next, { type: 'outputs', regionId: 'repeat-body', value: repeatOutputs });
        assert.equal(node(repeated, 'repeat-node').state[0].next, 'decision_after');
        assert.equal(node(repeated, 'repeat-node').exports[0].output, 'decision_after');
        const repeat = clone(node(repeated, 'repeat-node'));
        repeat.state[0].name = 'renamed_state';
        const renamedState = applied(repeated, { type: 'node', nodeId: repeat.id, value: repeat });
        assert.equal(node(renamedState, repeat.id).until.left.input, 'review');
        assert.equal(task(renamedState, 'repeat-task').inputs[0].source.state_name, 'review');
        const route = clone(node(renamedState, 'route-node'));
        route.inputs[0].name = 'renamed_input';
        const routed = applied(renamedState, { type: 'node', nodeId: route.id, value: route });
        assert.equal(node(routed, 'route-node').condition.condition.left.input, 'decision');
        assert.ok(editor.workflowValidationErrors(routed, fixture.options).some((message) => /not been bound/.test(message)));
        const join = clone(node(routed, 'choice').join);
        join.exports[0].name = 'renamed_verdict';
        const joined = applied(routed, { type: 'join', nodeId: 'choice', value: join });
        assert.equal(task(joined, 'report-task').inputs[0].source.output, 'verdict');
        assert.ok(editor.workflowValidationErrors(joined, fixture.options).length);
    });

    test('supported schema/typed-input errors stay editable without normalizing their authored values', () => {
        const workflow = expectedDefinition();
        const seed = clone(task(workflow, 'seed-task'));
        seed.output_contract.schema.properties.ready.unfinished_keyword = true;
        const schemaDraft = applied(workflow, { type: 'task', taskId: seed.id, value: seed });
        assert.deepEqual(task(schemaDraft, seed.id).output_contract.schema, seed.output_contract.schema);
        assert.ok(editor.workflowValidationErrors(schemaDraft, fixture.options).some((message) => /schema/i.test(message)));
        const report = clone(task(schemaDraft, 'report-task'));
        report.inputs[0].expected_kind = 'records';
        const typedDraft = applied(schemaDraft, { type: 'task', taskId: report.id, value: report });
        assert.equal(task(typedDraft, report.id).inputs[0].expected_kind, 'records');
        assert.deepEqual(task(typedDraft, report.id).inputs[0].source, task(workflow, report.id).inputs[0].source);
        assert.ok(editor.workflowValidationErrors(typedDraft, fixture.options).some((message) => /kind.*disagrees/.test(message)));
    });

    test('native Analyze and publication configuration are data-only and preserve exact identities', (context) => {
        const network = context.mock.method(globalThis, 'fetch', () => {
            throw new Error('Draft authoring must never invoke an API or workflow.');
        });
        const workflow = expectedDefinition();
        const report = clone(task(workflow, 'report-task'));
        report.inputs = [clone(report.inputs[1])];
        report.publication = {
            source_kind: 'saved_output', artifact_format: 'json', workspace_scope: 'personal',
            completion_policy: 'indexed_ready',
        };
        const next = applied(workflow, { type: 'task', taskId: report.id, value: report });
        assert.deepEqual(editor.workflowValidationErrors(next, fixture.options), []);
        assert.deepEqual(task(next, 'each-task').document_action, task(workflow, 'each-task').document_action);
        assert.deepEqual(task(next, report.id).publication, report.publication);
        assert.equal(node(next, 'report-node').task_id, 'report-task');
        assert.equal(network.mock.callCount(), 0);
    });

    for (const [label, mutate] of [
        ['node geometry', (workflow) => { node(workflow, 'seed-node').position = { x: 1, y: 2 }; }],
        ['region geometry', (workflow) => { node(workflow, 'each-body').viewport = { zoom: 2 }; }],
        ['join behavior', (workflow) => { node(workflow, 'choice').join.future_behavior = true; }],
        ['task behavior', (workflow) => { task(workflow, 'report-task').future_behavior = true; }],
        ['binding scope', (workflow) => { task(workflow, 'report-task').inputs[0].source.future_scope = true; }],
        ['Repeat exhaustion', (workflow) => { node(workflow, 'repeat-node').exhaustion = 'complete'; }],
        ['run limit', (workflow) => { workflow.limits.future_budget = 10; }],
    ]) {
        test(`unknown executable ${label} remains read-only rather than being dropped`, () => {
            const workflow = expectedDefinition();
            mutate(workflow);
            rejected(workflow, { type: 'limits', value: { max_executions: 10, deadline_seconds: 60 } });
            assert.throws(() => editor.workflowForSave(workflow, clone(workflow), personalScope), /unsupported/i);
        });
    }

    test('duplicate structural and catalogue IDs reject atomically instead of overwriting Map entries', () => {
        for (const mutate of [
            (workflow) => { node(workflow, 'choice').join.id = 'root'; },
            (workflow) => { node(workflow, 'choice').else.id = 'then-region'; },
            (workflow) => { node(workflow, 'constructor').id = 'seed-node'; },
            (workflow) => { workflow.tasks[1].id = workflow.tasks[0].id; },
        ]) {
            const workflow = initialDefinition();
            mutate(workflow);
            rejected(workflow, { type: 'add', regionId: 'root', kind: 'task' });
        }
    });

    test('capabilities refuse unadvertised controls and malformed task policy without guessing defaults', () => {
        for (const kind of supportedKinds) {
            const options = clone(fixture.options);
            options.supported_node_kinds = supportedKinds.filter((candidate) => candidate !== kind);
            rejected(simpleDefinition(), { type: 'add', regionId: 'root', kind }, options);
        }
        const noState = clone(fixture.options);
        noState.supported_binding_sources = ['node_output', 'loop_item'];
        rejected(simpleDefinition(), { type: 'add', regionId: 'root', kind: 'repeat_until' }, noState);
        for (const maxTasks of [0, Number.NaN, undefined, 1.5]) {
            rejected(simpleDefinition(), { type: 'add', regionId: 'root', kind: 'task' },
                { ...clone(fixture.options), max_tasks: maxTasks });
        }
    });
}

if (process.argv.includes('--emit-canonical-payload') || process.argv.includes('--emit-canonical-preview')) {
    loadProductionModules().then(() => {
        const payload = canonicalPayload();
        process.stdout.write(JSON.stringify(process.argv.includes('--emit-canonical-preview') ? {
            fields: editor.WORKFLOW_DEFINITION_FIELDS,
            payload,
            preview: editor.workflowForFlowPreview(payload),
        } : payload));
    }).catch((error) => {
        process.stderr.write(`${error.stack || error}\n`);
        process.exitCode = 1;
    });
} else {
    before(loadProductionModules);
    registerTests();
}
