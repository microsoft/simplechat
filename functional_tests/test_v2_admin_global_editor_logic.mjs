// test_v2_admin_global_editor_logic.mjs
// Version: 0.261.270
// Implemented in: 0.261.270
// Executes the real global agent and action adapters, return-path rules and connector payloads
// that let Admin Settings author global agents and actions in the V2 editors.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const {
    agentEditorReturnPath, buildEditorWrite, EDITOR_SECRET_MASK, GLOBAL_AGENT_RETURN_SCOPE,
    isActionEditorNewPath, isAgentEditorPath, withoutServerStampedFields,
} = await import('../application/v2_ui/src/lib/workspaceAuthoring.ts');
const {
    actionTestScopeName, connectorTestScope, GLOBAL_ACTION_TEST_SCOPE,
} = await import('../application/v2_ui/src/lib/workspaceActionTypes.ts');
const { buildConnectorSupportPayload, fetchMcpPreconfigurations } =
    await import('../application/v2_ui/src/lib/workspaceActionConnectors.ts');
const { buildActionConnectionPayload } = await import('../application/v2_ui/src/lib/workspaceActionServices.ts');
const { GLOBAL_ACTION_WORKBENCH, fetchGlobalActions } = await import('../application/v2_ui/src/lib/actionWorkbench.ts');
const { GLOBAL_AGENT_WORKBENCH, fetchGlobalAgentCatalog } = await import('../application/v2_ui/src/lib/agentWorkbench.ts');
const { agentTemplateSubmission } = await import('../application/v2_ui/src/lib/workspaceAgentTemplates.ts');
const { agentInstructionRequest, GLOBAL_INSTRUCTION_SCOPE } =
    await import('../application/v2_ui/src/lib/workspaceAgentCommands.ts');
const { newAgentDraft } = await import('../application/v2_ui/src/lib/workspaceAgentAuthoring.ts');

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

function globalAction(overrides = {}) {
    return {
        id: 'action-1', name: 'weather', displayName: 'Weather', description: '', type: 'openapi',
        endpoint: 'https://api.example.test', auth: { type: 'key', key: EDITOR_SECRET_MASK },
        additionalFields: { base_url: 'https://api.example.test' }, metadata: {},
        is_global: true, is_group: false, scope: 'global', scope_id: 'global', ...overrides,
    };
}

function resource(record, secretPaths = []) {
    return { record: structuredClone(record), revision: 'etag-1', secret_paths: secretPaths, read_only: false };
}

check('the global return path accepts only the Admin Settings agent editor', () => {
    assert.equal(agentEditorReturnPath('/admin/agents/new', GLOBAL_AGENT_RETURN_SCOPE), '/admin/agents/new');
    assert.equal(agentEditorReturnPath('/admin/agents/agent%201', GLOBAL_AGENT_RETURN_SCOPE), '/admin/agents/agent%201');
    for (const refused of ['/workspace/agents/a', '/groups/g/agents/a', '/admin/agents/a/b', '/admin/agents/..', '/admin/agents/']) {
        assert.equal(agentEditorReturnPath(refused, GLOBAL_AGENT_RETURN_SCOPE), null, refused);
    }
    // Neither personal nor group scope accepts an Admin Settings path.
    assert.equal(agentEditorReturnPath('/admin/agents/a'), null);
    assert.equal(agentEditorReturnPath('/admin/agents/a', 'g'), null);
    assert.equal(agentEditorReturnPath('/workspace/agents/a'), '/workspace/agents/a');
});

check('the editor frame recognises the global agent and new-action editors', () => {
    assert.equal(isAgentEditorPath('/admin/agents/new'), true);
    assert.equal(isAgentEditorPath('/admin/actions/new'), false);
    assert.equal(isActionEditorNewPath('/admin/actions/new'), true);
    assert.equal(isActionEditorNewPath('/admin/actions/action-1'), false);
    assert.equal(isActionEditorNewPath('/workspace/actions/new'), true);
});

check('connector commands run in the global scope only for a global action', () => {
    assert.equal(actionTestScopeName(GLOBAL_ACTION_TEST_SCOPE), 'global');
    assert.equal(actionTestScopeName({ id: 'g-1' }), 'group');
    assert.equal(actionTestScopeName(undefined), 'personal');
    assert.equal(connectorTestScope({ globalScope: true }), GLOBAL_ACTION_TEST_SCOPE);
    assert.deepEqual(connectorTestScope({ groupScope: { id: 'g-1' } }), { id: 'g-1' });
    assert.equal(connectorTestScope({}), undefined);

    const original = resource(globalAction({
        type: 'mcp', auth: { type: 'NoAuth' },
        additionalFields: {
            server_profile: 'generic', transport: 'streamable_http', auth_method: 'none',
            request_timeout: 30, connect_timeout: 10, sse_read_timeout: 300, retry_count: 0,
            retry_backoff_seconds: 1, load_tools: true, load_prompts: false, custom_headers: {},
            allowed_tool_names: [], mcp_tools: [],
        },
    }));
    const payload = buildConnectorSupportPayload(structuredClone(original.record), original, 'mcp', 'test', GLOBAL_ACTION_TEST_SCOPE);
    assert.equal(payload.action_scope, 'global');
    assert.deepEqual(payload.plugin_context, { scope: 'global', id: 'action-1', name: 'weather' });
    assert.equal('group_id' in payload, false);
    // A personal editor still refuses to test a global action.
    assert.throws(() => buildConnectorSupportPayload(structuredClone(original.record), original, 'mcp', 'test'), /read-only/);
});

check('native connection tests carry the global scope for a global action', () => {
    const record = globalAction({ type: 'databricks', auth: { type: 'NoAuth' }, additionalFields: {} });
    const original = resource(record);
    const payload = buildActionConnectionPayload(structuredClone(record), original, GLOBAL_ACTION_TEST_SCOPE);
    assert.equal(payload.action_scope, 'global');
    assert.deepEqual(payload.plugin_context, { scope: 'global', id: 'action-1', name: 'weather' });
    assert.throws(() => buildActionConnectionPayload(structuredClone(record), original), /cannot be connection-tested/);
});

check('stamped global fields can never be emitted as edits or removals', () => {
    const original = resource(globalAction({ updated_at: '2026-01-01' }));
    const edited = { ...structuredClone(original.record), description: 'Updated.' };
    delete edited.scope;
    delete edited.scope_id;
    delete edited.updated_at;
    const unguarded = buildEditorWrite(edited, original);
    assert.ok(unguarded.removed_paths.includes('/scope'), 'Without the guard the server would refuse this write.');
    const guarded = buildEditorWrite(
        withoutServerStampedFields(edited),
        { ...original, record: withoutServerStampedFields(original.record) },
    );
    assert.deepEqual(guarded.updates, { description: 'Updated.' });
    assert.deepEqual(guarded.removed_paths, []);
});

check('the global adapters describe the administrator scope', () => {
    assert.equal(GLOBAL_ACTION_WORKBENCH.basePath, '/admin/actions');
    assert.deepEqual(GLOBAL_ACTION_WORKBENCH.draftScope, { kind: 'global' });
    assert.equal(GLOBAL_ACTION_WORKBENCH.testScope, GLOBAL_ACTION_TEST_SCOPE);
    for (const operation of ['create', 'edit', 'delete', 'test']) assert.equal(GLOBAL_ACTION_WORKBENCH.allows(operation), true);

    assert.equal(GLOBAL_AGENT_WORKBENCH.basePath, '/admin/agents');
    assert.equal(GLOBAL_AGENT_WORKBENCH.actionsBasePath, '/admin/actions');
    assert.deepEqual(GLOBAL_AGENT_WORKBENCH.draftScope, { kind: 'global' });
    assert.deepEqual([...GLOBAL_AGENT_WORKBENCH.knowledgeScopes], ['public']);
    assert.equal(GLOBAL_AGENT_WORKBENCH.canCreateActions, true);
    assert.equal(GLOBAL_AGENT_WORKBENCH.canUseInChat({ is_enabled: true }), false);
    assert.equal(GLOBAL_AGENT_WORKBENCH.allowsCustomEndpoints({}), true);
    assert.equal(GLOBAL_AGENT_WORKBENCH.allowsTemplateSubmission({ agent_template_submission_allowed: true }), true);
    assert.equal(GLOBAL_AGENT_WORKBENCH.allowsTemplateSubmission({}), false);
});

check('global template submissions and instruction drafts speak for the organisation', () => {
    const draft = { ...newAgentDraft(), display_name: 'Research', description: 'Finds things.', instructions: 'Help.' };
    assert.equal(agentTemplateSubmission(draft, 'global').template.source_scope, 'global');
    assert.equal(agentTemplateSubmission(draft).template.source_scope, 'personal');
    const request = agentInstructionRequest(draft, [], null, GLOBAL_INSTRUCTION_SCOPE);
    assert.equal(request.agent_scope, 'global');
    assert.equal('group_id' in request, false);
});

const actualFetch = globalThis.fetch;
const requests = [];
const responses = new Map();
globalThis.fetch = async (url, init = {}) => {
    const method = init.method ?? 'GET';
    requests.push({ url, method, body: typeof init.body === 'string' ? JSON.parse(init.body) : init.body });
    const key = `${method} ${url}`;
    const body = responses.has(key) ? responses.get(key) : { success: true };
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
};
const last = () => requests.at(-1);

try {
    await asyncCheck('global actions are read from the admin route and must be global', async () => {
        responses.set('GET /api/v2/admin/actions', { actions: [globalAction()] });
        const actions = await fetchGlobalActions();
        assert.equal(actions.length, 1);
        assert.equal(last().url, '/api/v2/admin/actions');
        responses.set('GET /api/v2/admin/actions', { actions: [globalAction({ is_global: false, group_id: 'g-1' })] });
        await assert.rejects(fetchGlobalActions(), /not a global action/);
    });

    await asyncCheck('global action types, options and identities come from admin routes', async () => {
        responses.set('GET /api/v2/admin/actions/types', { types: [{ type: 'openapi' }] });
        assert.equal((await GLOBAL_ACTION_WORKBENCH.fetchTypes()).length, 1);
        responses.set('GET /api/v2/admin/action-options', { secret_reminders: {
            storage_enabled: true, reminders_enabled: false, require_expiration: false, lead_days: 45, contact_email: 'ops@example.test',
        } });
        const hints = await GLOBAL_ACTION_WORKBENCH.fetchEditorHints();
        assert.equal(hints.canAuthor, true);
        assert.equal(hints.reminderLeadDays, 45);
        responses.set('GET /api/admin/workspace-identities/global/identities', { identities: [
            { id: 'i-1', name: 'Service principal', usage_contexts: ['action'], credentials: { auth_type: 'service_principal' } },
            { id: 'i-2', name: 'File share', usage_contexts: ['file_sync'], credentials: { auth_type: 'username_password' } },
        ] });
        const identities = await GLOBAL_ACTION_WORKBENCH.listIdentities();
        assert.deepEqual(identities.map((identity) => [identity.id, identity.scope_type, identity.scope_id]), [['i-1', 'global', 'global']]);
    });

    await asyncCheck('saving a global action creates and patches through the admin route', async () => {
        const created = resource(globalAction({ id: 'action-9' }));
        responses.set('POST /api/v2/admin/actions', created);
        const draft = { ...globalAction(), id: '' };
        delete draft.scope;
        delete draft.scope_id;
        await GLOBAL_ACTION_WORKBENCH.save(draft, null);
        assert.equal(last().method, 'POST');
        assert.equal('id' in last().body.updates, false, 'The server allocates a global action id.');

        const original = resource(globalAction(), ['/auth/key']);
        responses.set('PATCH /api/v2/admin/actions/action-1', resource(globalAction({ description: 'Updated.' }), ['/auth/key']));
        await GLOBAL_ACTION_WORKBENCH.save({ ...structuredClone(original.record), description: 'Updated.' }, original);
        assert.equal(last().url, '/api/v2/admin/actions/action-1');
        assert.equal(last().body.expected_revision, 'etag-1');
        assert.deepEqual(last().body.updates, { description: 'Updated.' });

        responses.set('PATCH /api/v2/admin/actions/action-1', { ...resource(globalAction()), read_only: true });
        await assert.rejects(GLOBAL_ACTION_WORKBENCH.save(structuredClone(original.record), original), /invalid action editor resource/);
    });

    await asyncCheck('global agents are listed with the default and saved through the admin route', async () => {
        const agent = { ...newAgentDraft(), id: 'agent-1', name: 'research', display_name: 'Research', is_global: true };
        responses.set('GET /api/v2/admin/agents', { agents: [agent], selected_agent_name: 'research' });
        const catalog = await fetchGlobalAgentCatalog();
        assert.equal(catalog.selectedAgentName, 'research');
        assert.equal(catalog.agents.length, 1);

        responses.set('GET /api/agents/generate_id', { id: '6f1c8c1e-0000-4000-8000-000000000001' });
        responses.set('POST /api/v2/admin/agents', resource({ ...agent, id: '6f1c8c1e-0000-4000-8000-000000000001' }));
        await GLOBAL_AGENT_WORKBENCH.save({ ...newAgentDraft(), name: 'new', display_name: 'New' }, null);
        assert.equal(last().url, '/api/v2/admin/agents');
        assert.equal(last().body.updates.id, '6f1c8c1e-0000-4000-8000-000000000001');

        await GLOBAL_AGENT_WORKBENCH.deleteAgent(agent);
        assert.deepEqual([last().method, last().url], ['DELETE', '/api/v2/admin/agents/agent-1']);
    });

    await asyncCheck('the global agent editor reads global options, knowledge, targets and MCP catalogues', async () => {
        responses.set('GET /api/v2/admin/agent-options', { agent_types: [], model_endpoints: [], builtin_actions: [], settings: {} });
        await GLOBAL_AGENT_WORKBENCH.fetchOptions();
        assert.equal(last().url, '/api/v2/admin/agent-options');
        responses.set('GET /api/agents/assigned-knowledge/catalog?agent_scope=global', { sources: [], documents: [], tags: [] });
        await GLOBAL_AGENT_WORKBENCH.fetchKnowledge();
        assert.equal(last().url, '/api/agents/assigned-knowledge/catalog?agent_scope=global');
        responses.set('GET /api/plugins/agent-targets?scope=global', { targets: [], can_manage: true, scope_type: 'global', scope_id: 'global' });
        await GLOBAL_AGENT_WORKBENCH.fetchTargets();
        assert.equal(last().url, '/api/plugins/agent-targets?scope=global');
        responses.set('GET /api/plugins/mcp/preconfigurations?scope=global', { scope: 'global', preconfigurations: [] });
        await fetchMcpPreconfigurations(undefined, 'global');
        assert.equal(last().url, '/api/plugins/mcp/preconfigurations?scope=global');
    });
} finally {
    globalThis.fetch = actualFetch;
}

console.log(`${checks} global editor logic checks passed.`);
