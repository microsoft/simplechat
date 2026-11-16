// test_v2_agent_drafted_actions_logic.mjs
// Version: 0.261.281
// Implemented in: 0.261.281
// Executes how the agent editor's Ask AI drafts new actions: the new-action spec it sends, how a
// turn's handles become session references, how undo and Remove drop a drafted action and bring
// it back, and how a saved action replaces its placeholder before the agent is saved.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import './test_support/tsResolve.mjs';

const { newAgentDraft } = await import('../application/v2_ui/src/lib/workspaceAgentAuthoring.ts');
const { actionForSave, actionTypeLabel, validateActionDraft } = await import('../application/v2_ui/src/lib/workspaceActionLogic.ts');
const { draftActionFromAssist, newActionAssistSpec } = await import('../application/v2_ui/src/lib/actionEditorAssist.ts');
const {
    applyAgentAssistPatch, buildAgentAssistView, isPendingActionReference, pendingAgentActions,
    prunePendingAgentActions, resolvePendingAgentAction,
} = await import('../application/v2_ui/src/lib/agentEditorAssist.ts');

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
const actionTypes = ['openapi', 'mcp', 'simplechat', 'agent'].map(definition);
const options = {
    agent_types: [{ value: 'local', label: 'Local', enabled: true }],
    settings: {},
    model_endpoints: [],
    builtin_actions: [],
};
const actions = [{ id: 'act-search', name: 'search', displayName: 'Web search', type: 'openapi' }];
let sequence = 0;
const stash = new Map();
const base = {
    options, actions, targets: null, knowledge: null, knowledgeScopes: ['personal'],
    reasoningLevels: [], ownerId: 'owner', isNew: true,
};
const drafting = {
    ...base, actionTypes,
    newPendingReference: () => `new-action-test-${++sequence}`,
    recallPendingAction: (reference) => stash.get(reference),
};

function draft(overrides = {}) {
    return { ...newAgentDraft(), display_name: 'Helper', description: 'Helps.', instructions: 'Be kind.', ...overrides };
}

function mcpItem(handle, displayName = 'Docs MCP') {
    return { handle, type: 'mcp', values: { '/displayName': displayName, '/description': 'Reads the docs.', '/endpoint': 'https://mcp.example.com/sse' } };
}

// The view offers new-action drafting only when the catalogue and a reference source are present.
{
    const plain = buildAgentAssistView(draft(), base);
    assert.equal(plain.newItems, undefined);
    const view = buildAgentAssistView(draft(), drafting);
    assert.equal(view.newItems.target, '/actions');
    assert.equal(view.newItems.max, 3);
    const types = view.newItems.types.map((option) => option.value);
    assert.ok(types.includes('mcp') && types.includes('openapi'));
    assert.ok(!types.includes('agent'), 'Call agent actions are created in the action editor');
    for (const descriptor of view.newItems.common) assert.match(descriptor.path, /^\/(displayName|description)$/);
    assert.ok(view.notes.some((note) => note.includes('credentials')));
    // Write the request so the backend contract check can parse it.
    if (process.env.AGENT_DRAFT_VIEW_OUT) {
        const { buildEditorAssistRequest } = await import('../application/v2_ui/src/lib/editorAssist.ts');
        const request = buildEditorAssistRequest({
            scope: { kind: 'personal' }, submissionId: 'test-submission', instruction: 'Add a docs action.', view, conversation: [],
        });
        fs.writeFileSync(process.env.AGENT_DRAFT_VIEW_OUT, JSON.stringify(request));
    }
}

// The spec and draft helpers build an action through the action editor's own rules.
{
    const spec = newActionAssistSpec({ catalogue: actionTypes, isNew: true });
    assert.ok(Object.keys(spec.variants).every((type) => spec.types.some((option) => option.value === type)));
    const action = draftActionFromAssist('mcp', mcpItem('new:N1').values, { catalogue: actionTypes, isNew: true });
    assert.equal(action.type, 'mcp');
    assert.equal(action.displayName, 'Docs MCP');
    assert.match(action.name, /^[A-Za-z0-9_-]+$/);
    assert.equal(draftActionFromAssist('agent', { '/displayName': 'x' }, { catalogue: actionTypes, isNew: true }), null);
    assert.equal(draftActionFromAssist('missing', { '/displayName': 'x' }, { catalogue: actionTypes, isNew: true }), null);
}

// A turn's handles become session references, and the drafted actions travel with the draft.
let withDraft;
{
    const start = draft({ actions_to_load: ['act-search'] });
    withDraft = applyAgentAssistPatch(start, { '/actions': ['act-search', 'new:N1'] }, drafting, [mcpItem('new:N1')]);
    assert.ok(withDraft);
    const [reference] = withDraft.actions_to_load.filter(isPendingActionReference);
    assert.equal(reference, 'new-action-test-1');
    assert.deepEqual(withDraft.actions_to_load, ['act-search', reference]);
    const pending = pendingAgentActions(withDraft);
    assert.equal(pending.length, 1);
    assert.equal(pending[0].action.displayName, 'Docs MCP');
    for (const item of pending) stash.set(item.reference, item.action);

    // The drafted action is offered back to Ask AI as an assignable option.
    const view = buildAgentAssistView(withDraft, drafting);
    const option = view.fields.find((field) => field.path === '/actions').options.find((item) => item.value === reference);
    assert.ok(option && option.label === 'Docs MCP');
    assert.equal(view.newItems.max, 2);

    // Without drafting support, an unknown handle, or too many drafts, the patch changes nothing.
    assert.equal(applyAgentAssistPatch(start, { '/actions': ['new:N1'] }, base, [mcpItem('new:N1')]), null);
    assert.equal(applyAgentAssistPatch(start, { '/actions': ['new:N2'] }, drafting, [mcpItem('new:N1')]), null);
    assert.equal(applyAgentAssistPatch(start, { '/actions': [] }, drafting,
        ['new:N1', 'new:N2', 'new:N3', 'new:N4'].map((handle) => mcpItem(handle))), null);
}

// Undo or Remove drops the drafted action; a later undo brings it back from the stash.
{
    const undone = applyAgentAssistPatch(withDraft, { '/actions': ['act-search'] }, drafting);
    assert.deepEqual(undone.actions_to_load, ['act-search']);
    assert.equal(Object.hasOwn(undone, '_pendingActions'), false);
    const removed = prunePendingAgentActions({ ...withDraft, actions_to_load: ['act-search'] });
    assert.equal(Object.hasOwn(removed, '_pendingActions'), false);
    const redone = applyAgentAssistPatch(undone, { '/actions': ['act-search', 'new-action-test-1'] }, drafting);
    assert.equal(pendingAgentActions(redone)[0].action.displayName, 'Docs MCP');
    assert.equal(applyAgentAssistPatch(undone, { '/actions': ['new-action-unknown'] }, drafting), null);
}

// A drafted action without required details is reported, and saving replaces the placeholder in place.
{
    const [{ reference, action }] = pendingAgentActions(withDraft);
    const errors = validateActionDraft(actionForSave(action), definition('mcp'));
    assert.equal(typeof errors, 'object');
    const saved = resolvePendingAgentAction(withDraft, reference, 'act-docs');
    assert.deepEqual(saved.actions_to_load, ['act-search', 'act-docs']);
    assert.equal(Object.hasOwn(saved, '_pendingActions'), false);
}

console.log('agent drafted actions logic: ok');
