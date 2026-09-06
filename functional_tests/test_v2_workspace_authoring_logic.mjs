// test_v2_workspace_authoring_logic.mjs
// Version: 0.261.096
// Implemented in: 0.261.096
// Executes the real draft-diff, scoped chat launch, and one-shot URL helpers.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const { buildEditorWrite, sameEditorValue, editorName, agentEditorReturnPath, EDITOR_SECRET_MASK } =
    await import('../application/v2_ui/src/lib/workspaceAuthoring.ts');
const { readWorkspaceAgentLaunch, workspaceAgentForLaunch } =
    await import('../application/v2_ui/src/lib/workspaceAgentLaunch.ts');
const { syncedConversationParams } = await import('../application/v2_ui/src/lib/conversationUrl.ts');
const { agentSelectionKey, findAgent, buildAgentInfo } = await import('../application/v2_ui/src/lib/agents.ts');
const {
    fetchAuthoringActions, fetchActionEditor, saveActionConfiguration, saveAgentConfiguration,
} = await import('../application/v2_ui/src/lib/workspaceAuthoringApi.ts');

const original = {
    record: {
        id: 'agent-1', name: 'original-name', display_name: 'Original',
        is_global: false, user_id: 'owner', max_completion_tokens: -1,
        actions_to_load: ['ordinary', 'legacy-reference'],
        auth: { type: 'key', key: EDITOR_SECRET_MASK, identity: 'unchanged' },
        other_settings: { custom: { retained: 42 }, action_capabilities: { ordinary: ['read', 'write'] } },
        additionalFields: { 'a/b~c__Secret': EDITOR_SECRET_MASK },
    },
    revision: 'revision-1',
    secret_paths: ['/auth/key', '/additionalFields/a~1b~0c__Secret'],
    read_only: false,
};
let checks = 0;
function check(label, run) {
    run();
    checks += 1;
    console.log(`ok ${label}`);
}

check('unchanged drafts carry only revision and no modifications', () => {
    assert.deepEqual(buildEditorWrite(structuredClone(original.record), original), {
        updates: {}, expected_revision: 'revision-1', clear_secret_paths: [], removed_paths: [],
    });
});
check('nested changes preserve unknown siblings and arrays replace intentionally', () => {
    const draft = structuredClone(original.record);
    draft.other_settings.action_capabilities.ordinary = ['read'];
    draft.actions_to_load.push('agent-action');
    assert.deepEqual(buildEditorWrite(draft, original).updates, {
        actions_to_load: ['ordinary', 'legacy-reference', 'agent-action'],
        other_settings: { action_capabilities: { ordinary: ['read'] } },
    });
    assert.equal(original.record.other_settings.custom.retained, 42);
});
check('clear and replace never submit the saved secret mask', () => {
    const draft = structuredClone(original.record);
    draft.auth.key = '';
    draft.additionalFields['a/b~c__Secret'] = 'synthetic-replacement';
    const write = buildEditorWrite(draft, original);
    assert.deepEqual(write.clear_secret_paths, ['/auth/key']);
    assert.deepEqual(write.updates, { additionalFields: { 'a/b~c__Secret': 'synthetic-replacement' } });
    assert.ok(!JSON.stringify(write).includes(EDITOR_SECRET_MASK));
});
check('advanced deletion uses escaped pointers without deleting siblings', () => {
    const draft = structuredClone(original.record);
    delete draft.other_settings.custom.retained;
    delete draft.additionalFields['a/b~c__Secret'];
    const write = buildEditorWrite(draft, original);
    assert.deepEqual(write.removed_paths, ['/other_settings/custom/retained']);
    assert.deepEqual(write.clear_secret_paths, ['/additionalFields/a~1b~0c__Secret']);
});
const arrayOriginal = {
    record: {
        id: 'action-array',
        additionalFields: {
            credentials: [
                { name: 'first', 'token/__Secret': EDITOR_SECRET_MASK, keep: true },
                { name: 'second', 'token/__Secret': EDITOR_SECRET_MASK },
            ],
        },
    },
    revision: 'array-revision',
    secret_paths: [
        '/additionalFields/credentials/0/token~1__Secret',
        '/additionalFields/credentials/1/token~1__Secret',
    ],
    read_only: false,
};
check('array secret clears are explicit for blank null missing and truncated entries', () => {
    for (const value of ['', null, undefined]) {
        const draft = structuredClone(arrayOriginal.record);
        if (value === undefined) delete draft.additionalFields.credentials[0]['token/__Secret'];
        else draft.additionalFields.credentials[0]['token/__Secret'] = value;
        const write = buildEditorWrite(draft, arrayOriginal);
        assert.deepEqual(write.clear_secret_paths, [arrayOriginal.secret_paths[0]]);
        assert.equal(write.updates.additionalFields.credentials[1]['token/__Secret'], EDITOR_SECRET_MASK);
    }
    const truncated = structuredClone(arrayOriginal.record);
    truncated.additionalFields.credentials.length = 1;
    assert.deepEqual(buildEditorWrite(truncated, arrayOriginal).clear_secret_paths, [arrayOriginal.secret_paths[1]]);
});
check('removing a parent emits each nested credential clear exactly once', () => {
    const draft = structuredClone(arrayOriginal.record);
    delete draft.additionalFields.credentials;
    const write = buildEditorWrite(draft, arrayOriginal);
    assert.deepEqual(write.clear_secret_paths, arrayOriginal.secret_paths);
    assert.deepEqual(write.removed_paths, ['/additionalFields/credentials']);
});
check('changed array masks stay positional and new masks are not guessed from names', () => {
    const draft = structuredClone(arrayOriginal.record);
    draft.additionalFields.credentials[0].name = 'second';
    draft.additionalFields.credentials[1].name = 'first';
    draft.additionalFields.credentials.push({ name: 'first', 'token/__Secret': EDITOR_SECRET_MASK });
    const write = buildEditorWrite(draft, arrayOriginal);
    assert.deepEqual(write.clear_secret_paths, []);
    assert.deepEqual(write.updates.additionalFields.credentials, draft.additionalFields.credentials);
});
check('false zero and empty collections are real updates', () => {
    const draft = { ...original.record, is_enabled: false, max_completion_tokens: 0, actions_to_load: [] };
    assert.deepEqual(buildEditorWrite(draft, original).updates, {
        max_completion_tokens: 0, actions_to_load: [], is_enabled: false,
    });
});
check('identifiers and ownership never travel as editable configuration', () => {
    const draft = { ...original.record, id: 'different-id', is_global: true, user_id: 'different-owner', last_updated: 'forged' };
    assert.deepEqual(buildEditorWrite(draft, original).updates, {});
});
check('a literal mask in ordinary text is not silently discarded', () => {
    assert.equal(buildEditorWrite({ description: EDITOR_SECRET_MASK }, null).updates.description, EDITOR_SECRET_MASK);
});
check('object key ordering alone is not a change', () => {
    assert.ok(sameEditorValue({ a: 1, b: [false, 0] }, { b: [false, 0], a: 1 }));
    assert.ok(!sameEditorValue({ a: null }, {}));
    assert.equal(editorName(' Contract reviewer '), 'Contract-reviewer');
});
check('advanced JSON property names cannot change object prototypes', () => {
    const other_settings = JSON.parse('{"__proto__":{"polluted":true},"constructor":"annotation"}');
    const write = buildEditorWrite({ other_settings }, null);
    assert.ok(Object.hasOwn(write.updates.other_settings, '__proto__'));
    assert.equal(Object.getPrototypeOf(write.updates.other_settings), Object.prototype);
    assert.equal(write.updates.other_settings.__proto__.polluted, true);
    assert.equal({}.polluted, undefined);
});
check('only known agent editor destinations can receive an action', () => {
    for (const path of ['/workspace/agents/new', '/workspace/agents/agent-1', '/workspace/agents/agent%3A1']) assert.equal(agentEditorReturnPath(path), path);
    for (const path of [null, 'https://example.com', '//example.com', '/workspace/actions/new', '/workspace/agents/../actions', '/workspace/agents/a?redirect=x', '/workspace/agents/%2e%2e', '/workspace/agents/a%2fb', '/workspace/agents/%bad']) {
        assert.equal(agentEditorReturnPath(path), null);
    }
});
check('agent launch requires explicit new-chat intent and respects conversation links', () => {
    assert.deepEqual(readWorkspaceAgentLaunch(new URLSearchParams('agent_id=a&new=1')), { id: 'a', scope: 'personal' });
    assert.equal(readWorkspaceAgentLaunch(new URLSearchParams('agent_id=a')), null);
    assert.equal(readWorkspaceAgentLaunch(new URLSearchParams('agent_id=a&new=1&agent_scope=group')), null);
    assert.equal(readWorkspaceAgentLaunch(new URLSearchParams('agent_id=a&new=1&conversationId=existing')), null);
});
check('launch resolves id and scope, never display name or disabled agents', () => {
    const personal = { id: 'same-id', name: 'Same', scope_type: 'personal', catalog_key: 'personal:same-id' };
    const global = { id: 'same-id', name: 'Same', scope_type: 'global', catalog_key: 'global:same-id' };
    const catalogue = [personal, global, { id: 'off', scope_type: 'personal', is_enabled: false }];
    assert.equal(workspaceAgentForLaunch(catalogue, { id: 'same-id', scope: 'global' }), global);
    assert.equal(workspaceAgentForLaunch(catalogue, { id: 'Same', scope: 'global' }), undefined);
    assert.equal(workspaceAgentForLaunch(catalogue, { id: 'off', scope: 'personal' }), undefined);
    assert.equal(findAgent(catalogue, agentSelectionKey(global)), global);
    assert.equal(buildAgentInfo(findAgent(catalogue, agentSelectionKey(global))).is_global, true);
    assert.equal(findAgent(catalogue, 'same-id'), personal);
});
check('consumed launch parameters do not start new chats on reload', () => {
    const params = new URLSearchParams('agent_id=a&agent_scope=personal&new=1&keep=value');
    assert.equal(syncedConversationParams(params, null).toString(), 'keep=value');
    assert.equal(syncedConversationParams(params, 'conversation-1').toString(), 'keep=value&conversationId=conversation-1');
    assert.equal(syncedConversationParams(new URLSearchParams('conversationId=conversation-1'), 'conversation-1'), null);
});

const actualFetch = globalThis.fetch;
const requests = [];
let responseBody = [];
let responseStatus = 200;
globalThis.fetch = async (url, init = {}) => {
    requests.push({ url, ...init, body: init.body ? JSON.parse(init.body) : undefined });
    const payload = url === '/api/agents/generate_id' ? { id: 'reserved-agent-id' } : responseBody;
    return new Response(JSON.stringify(payload), {
        status: responseStatus, headers: { 'Content-Type': 'application/json' },
    });
};
async function asyncCheck(label, run) {
    await run();
    checks += 1;
    console.log(`ok ${label}`);
}
try {
    await asyncCheck('authoring collections use safe views and reject malformed lists', async () => {
        responseBody = [{ id: 'a', type: 'agent' }, { id: 'b', type: 'openapi' }];
        assert.deepEqual(await fetchAuthoringActions(), responseBody);
        assert.equal(requests.at(-1).url, '/api/user/plugins?view=editor');
        assert.equal(requests.at(-1).credentials, 'same-origin');
        responseBody = { wrong_key: [] };
        await assert.rejects(fetchAuthoringActions(), /invalid resource list/);
    });
    await asyncCheck('provided details use an explicit read-only scope query', async () => {
        responseBody = { record: { id: 'provided' }, revision: '', secret_paths: [], read_only: true };
        const detail = await fetchActionEditor('provided', 'global');
        assert.equal(requests.at(-1).url, '/api/user/plugins/provided?view=editor&scope=global');
        const before = requests.length;
        assert.throws(() => saveActionConfiguration(detail.record, detail), /read-only/);
        assert.equal(requests.length, before);
        delete responseBody.revision;
        assert.equal((await fetchActionEditor('provided', 'global')).revision, '');
        responseBody.revision = null;
        assert.equal((await fetchActionEditor('provided', 'global')).revision, '');
    });
    await asyncCheck('invalid editor envelopes are errors rather than editable empty records', async () => {
        for (const invalid of [
            { success: true },
            { record: 'not a record', revision: 'v1', read_only: false, secret_paths: [] },
            { record: { id: 'a' }, revision: '', read_only: false, secret_paths: [] },
            { record: { id: 'a' }, revision: 'v1', read_only: false, secret_paths: ['auth.key'] },
        ]) {
            responseBody = invalid;
            await assert.rejects(fetchActionEditor('a'), /invalid editor resource/);
        }
    });
    await asyncCheck('normal action creation is one record, never a collection replacement', async () => {
        const draft = {
            id: '', name: 'utility', displayName: 'Utility', type: 'text', description: 'Format text',
            endpoint: '', auth: { type: 'NoAuth' }, metadata: {}, additionalFields: {},
        };
        responseBody = { record: { ...draft, id: 'created-action' }, revision: 'new', secret_paths: [], read_only: false };
        assert.equal((await saveActionConfiguration(draft, null)).record.id, 'created-action');
        const call = requests.at(-1);
        assert.equal(call.method, 'POST');
        assert.equal(call.url, '/api/user/plugins?view=editor');
        assert.ok(!Array.isArray(call.body));
        assert.ok(!('id' in call.body.updates));
        assert.equal(call.body.updates.type, 'text');
    });
    await asyncCheck('agent creation reserves a server identifier before posting its manifest', async () => {
        const draft = {
            id: '', name: 'new-agent', display_name: 'New agent', description: '', instructions: 'Help.',
            agent_type: 'local', actions_to_load: [], other_settings: {}, max_completion_tokens: -1,
        };
        const before = requests.length;
        responseBody = { record: { ...draft, id: 'reserved-agent-id' }, revision: 'new', secret_paths: [], read_only: false };
        await saveAgentConfiguration(draft, null);
        assert.deepEqual(requests.slice(before).map((item) => item.url), [
            '/api/agents/generate_id', '/api/user/agents?view=editor',
        ]);
        assert.equal(requests.at(-1).body.updates.id, 'reserved-agent-id');
    });
    await asyncCheck('edit transport carries revision and only intended fields', async () => {
        responseBody = original;
        await saveAgentConfiguration({ ...original.record, display_name: 'Renamed' }, original);
        const call = requests.at(-1);
        assert.equal(call.url, '/api/user/agents/agent-1?view=editor');
        assert.equal(call.method, 'PATCH');
        assert.deepEqual(call.body.updates, { display_name: 'Renamed' });
        assert.equal(call.body.expected_revision, 'revision-1');
        responseStatus = 409;
        responseBody = { error: 'Changed in another editor.' };
        await assert.rejects(saveAgentConfiguration(original.record, original), /Changed in another editor/);
        assert.equal(original.revision, 'revision-1');
    });
} finally {
    globalThis.fetch = actualFetch;
}

await asyncCheck('editor draft callbacks retain React setter identity across renders', async () => {
    const { createRequire } = await import('node:module');
    const require = createRequire(new URL('../application/v2_ui/package.json', import.meta.url));
    const React = require('react');
    const { renderToString } = require('react-dom/server');
    const { useWorkspaceEditorDraft, clearWorkspaceEditorDrafts } =
        await import('../application/v2_ui/src/lib/workspaceEditorDrafts.ts');
    let renders = 0;
    function Probe() {
        const draft = useWorkspaceEditorDraft('agents', 'callback-probe', () => structuredClone(original.record));
        const first = React.useRef(null);
        const [again, setAgain] = React.useState(false);
        renders += 1;
        if (!first.current) first.current = { setDraft: draft.setDraft, load: draft.load, clear: draft.clear };
        if (!again) setAgain(true);
        else {
            assert.equal(draft.setDraft, first.current.setDraft);
            assert.equal(draft.load, first.current.load);
            assert.equal(draft.clear, first.current.clear);
        }
        return React.createElement('span', null, 'Stable callbacks');
    }
    try {
        assert.ok(renderToString(React.createElement(Probe)).includes('Stable callbacks'));
        assert.equal(renders, 2);
    } finally {
        clearWorkspaceEditorDrafts();
    }
});

console.log(`${checks} workspace authoring logic checks passed.`);
