// test_v2_agent_editor_assist_logic.mjs
// Version: 0.261.279
// Implemented in: 0.261.279
// Executes the agent editor's Ask AI view and patch rules: which fields Ask AI may read and set,
// which actions it may assign, and how its answer is applied through the editor's own helpers.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const { newAgentDraft } = await import('../application/v2_ui/src/lib/workspaceAgentAuthoring.ts');
const { readAgentKnowledge } = await import('../application/v2_ui/src/lib/workspaceAgentKnowledge.ts');
const {
    AGENT_ASSIST_SECTIONS, agentAssistValues, applyAgentAssistPatch, buildAgentAssistView,
} = await import('../application/v2_ui/src/lib/agentEditorAssist.ts');

const options = {
    agent_types: [{ value: 'local', label: 'Local', enabled: true }, { value: 'aifoundry', label: 'Foundry', enabled: true }],
    settings: {},
    model_endpoints: [{
        id: 'ep-1', name: 'Main', provider: 'aoai', enabled: true,
        models: [{ id: 'm-1', deploymentName: 'gpt-main', modelName: 'gpt-main', displayName: 'GPT main', enabled: true }],
    }],
    builtin_actions: [],
};
const actions = [
    { id: 'act-search', name: 'search', displayName: 'Web search', type: 'openapi', description: 'Searches the web.' },
    { id: 'act-off', name: 'disabled', displayName: 'Old action', type: 'openapi', is_enabled: false },
    { id: 'act-legacy', name: 'legacy', displayName: 'Legacy', type: 'sql_query' },
];
const knowledge = {
    sources: [
        { scope: 'personal', id: 'personal', label: 'My workspace' },
        { scope: 'group', id: 'g-1', label: 'Group one' },
        { scope: 'public', id: 'p-1', label: 'Public one' },
    ],
    documents: [{ id: 'doc-1', title: 'Handbook', file_name: 'handbook.pdf', scope: 'personal', source_id: 'personal', source_name: 'My workspace', tags: ['hr'] }],
    tags: [{ name: 'hr', count: 1 }],
};
const context = {
    options, actions, targets: null, knowledge, knowledgeScopes: ['personal', 'public'],
    reasoningLevels: ['low', 'high'], ownerId: 'owner', isNew: true,
};

function draft(overrides = {}) {
    return { ...newAgentDraft(), display_name: 'Helper', description: 'Helps.', instructions: 'Be kind.', ...overrides };
}

function fieldPaths(view) {
    return view.fields.map((field) => field.path);
}

// A local agent describes identity, model, actions, knowledge and limits, but never connections or secrets.
{
    const view = buildAgentAssistView(draft({ actions_to_load: ['legacy'] }), context);
    assert.deepEqual(view.sections, AGENT_ASSIST_SECTIONS);
    const paths = fieldPaths(view);
    for (const path of ['/display_name', '/description', '/instructions', '/agent_type', '/model', '/actions',
        '/max_completion_tokens', '/reasoning_effort', '/knowledge/enabled', '/knowledge/sources',
        '/knowledge/documents', '/knowledge/tags', '/knowledge/web_sources']) {
        assert.ok(paths.includes(path), `missing ${path}`);
    }
    assert.ok(!paths.some((path) => /key|secret|endpoint|deployment|other_settings/.test(path)), 'no connection or secret fields');
    assert.equal(view.fields.find((field) => field.path === '/agent_type').read_only, true);
    for (const field of view.fields) {
        for (const option of field.options ?? []) assert.ok(option.value, `${field.path} has an empty option value`);
    }
    const actionField = view.fields.find((field) => field.path === '/actions');
    // A disabled action can't be assigned; an assigned action keeps the reference the draft uses.
    assert.deepEqual(actionField.options.map((option) => option.value), ['act-search', 'legacy']);
    const sources = view.fields.find((field) => field.path === '/knowledge/sources');
    assert.deepEqual(sources.options.map((option) => option.value), ['personal:personal', 'public:p-1'], 'only authorized scopes');
    assert.deepEqual(view.values['/actions'], ['legacy']);
    assert.equal(view.values['/reasoning_effort'], null);
}

// A Foundry agent only offers identity and description changes.
{
    const view = buildAgentAssistView(draft({ agent_type: 'aifoundry' }), context);
    assert.deepEqual(fieldPaths(view), ['/display_name', '/description', '/agent_type', '/instructions']);
    assert.ok(view.notes.some((note) => note.includes('Foundry')));
}

// Without the knowledge catalogue, only the toggle and web pages are offered.
{
    const view = buildAgentAssistView(draft(), { ...context, knowledge: null });
    const paths = fieldPaths(view);
    assert.ok(!paths.includes('/knowledge/sources') && !paths.includes('/knowledge/documents'));
    assert.ok(paths.includes('/knowledge/web_sources'));
}

// Applying a patch goes through the editor's helpers.
{
    const start = draft();
    const modelKey = buildAgentAssistView(start, context).fields.find((field) => field.path === '/model').options[0].value;
    const next = applyAgentAssistPatch(start, {
        '/display_name': 'Research helper',
        '/model': modelKey,
        '/actions': ['act-search', 'act-search'],
        '/reasoning_effort': 'high',
        '/max_completion_tokens': 4000,
        '/knowledge/enabled': true,
        '/knowledge/sources': ['personal:personal', 'public:p-1'],
        '/knowledge/documents': ['doc-1'],
        '/knowledge/tags': ['hr'],
        '/knowledge/web_sources': [{ url: 'https://example.com/a', mode: 'deep_research' }],
    }, context);
    assert.ok(next);
    assert.equal(next.display_name, 'Research helper');
    assert.equal(next.name, 'Research-helper', 'a new agent renames with its display name');
    assert.equal(next.model_endpoint_id, 'ep-1');
    assert.equal(next.model_id, 'm-1');
    assert.deepEqual(next.actions_to_load, ['act-search']);
    assert.equal(next.reasoning_effort, 'high');
    assert.equal(next.max_completion_tokens, 4000);
    const config = readAgentKnowledge(next);
    assert.equal(config.enabled, true);
    assert.equal(config.scopes.personal, true);
    assert.deepEqual(config.scopes.public_workspace_ids, ['p-1']);
    assert.deepEqual(config.scopes.group_ids, []);
    assert.deepEqual(config.document_ids, ['doc-1']);
    assert.deepEqual(config.tags, ['hr']);
    assert.deepEqual(config.web_sources.map(({ url, mode }) => ({ url, mode })), [{ url: 'https://example.com/a', mode: 'deep_research' }]);
    const values = agentAssistValues(next, context);
    assert.equal(values['/model'], modelKey);
    assert.deepEqual(values['/knowledge/sources'], ['personal:personal', 'public:p-1']);

    // Clearing reasoning effort removes it, so the configured default applies.
    const cleared = applyAgentAssistPatch(next, { '/reasoning_effort': null }, context);
    assert.equal(Object.hasOwn(cleared, 'reasoning_effort'), false);
}

// A patch the editor can't take changes nothing.
{
    const start = draft();
    assert.equal(applyAgentAssistPatch(start, { '/model': 'not-a-model' }, context), null);
    assert.equal(applyAgentAssistPatch(start, { '/max_completion_tokens': 1.5 }, context), null);
    assert.equal(applyAgentAssistPatch(start, { '/knowledge/web_sources': [{ url: 'ftp://example.com' }] }, context), null);
    assert.equal(applyAgentAssistPatch(start, { '/azure_openai_gpt_key': 'x' }, context), null);
}

// An existing agent keeps its internal name when the display name changes.
{
    const existing = draft({ id: 'a-1', name: 'stable_name' });
    const next = applyAgentAssistPatch(existing, { '/display_name': 'New name' }, { ...context, isNew: false });
    assert.equal(next.name, 'stable_name');
}

console.log('agent editor assist logic: ok');
