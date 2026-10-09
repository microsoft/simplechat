// test_v2_shared_workspace_counts.mjs
// Version: 0.261.310
// Implemented in: 0.261.310
// Executes the real scoped readers, pagination totals, partial failures and cancellation.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const { createSharedWorkspaceCountLoaders, loadWorkspaceCounts, validWorkspaceCount } =
    await import('../application/v2_ui/src/lib/sharedWorkspaceCounts.ts');

const originalFetch = globalThis.fetch;
let calls = [];
let responder;
globalThis.fetch = async (url) => {
    const parsed = new URL(url, 'http://simplechat.test');
    calls.push(parsed);
    const payload = await responder(parsed);
    return new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } });
};

function context(kind, id = 'workspace-a', facets = true) {
    return {
        scope: { kind, id }, viewer_id: 'viewer', role: 'Owner', workspace: { name: id },
        sections: { actions: { enabled: true } },
        document_queries: { facets, places: true, sort_fields: ['_ts'] },
    };
}

function payload(url) {
    const { pathname: path } = url;
    const publicScope = path.includes('/public-workspaces/');
    const id = path.startsWith('/api/group/') || path.startsWith('/api/group_documents')
        ? url.searchParams.get('group_id') : path.split('/')[3];
    const row = { id: 'item', group_id: id, public_workspace_id: id };
    if (path.endsWith('/facets')) return {
        total: 1700, untagged: 0, processing: 0, errors: 0, recent: 0,
        shared_with_me: 0, by_tag: {}, by_classification: {},
    };
    if (path.endsWith('/tags')) return { tags: [{ name: 'team', count: 1700 }] };
    if (path === '/api/group_documents' || path.endsWith('/documents')) return {
        documents: [], total_count: 1700, page: 1, page_size: 1,
    };
    if (path.endsWith('/prompts')) return {
        prompts: [{ ...row, public_id: id }], total_count: 1001, page: 1, page_size: 1,
    };
    if (path.endsWith('/membership/members')) return {
        members: [], total_count: 1201, page: 1, page_size: 1,
        membership_management: { schema_version: 1, operations: [] },
    };
    if (path.endsWith('/agents')) return { agents: [row, { ...row, id: 'second' }] };
    if (path.endsWith('/actions')) return { actions: [row, { ...row, id: 'second' }, { ...row, id: 'third' }] };
    if (path.endsWith('/plugins')) return { actions: [
        { ...row, type: 'agent' }, { ...row, id: 'second', type: 'agent' },
        { ...row, id: 'third', type: 'openapi' },
    ] };
    if (path.endsWith('/identities')) return { identities: [row] };
    if (path.endsWith('/file-sources')) return {
        file_sources: [{ ...row, config_revision: 'revision', source_actions: [] }],
    };
    if (path.endsWith('/workflows')) return { workflows: [row] };
    if (path.endsWith('/model-endpoints')) return {
        endpoints: [{ ...row, revision: 'revision', endpoint_actions: [] }],
    };
    throw new Error(`Unexpected ${publicScope ? 'public' : 'group'} read: ${url}`);
}

async function readCounts(ctx, ids) {
    calls = [];
    const results = {};
    await loadWorkspaceCounts(createSharedWorkspaceCountLoaders(ctx), ids,
        new AbortController().signal, (id, result) => { results[id] = result; });
    return results;
}

try {
    responder = payload;
    const groupIds = ['documents', 'tags', 'prompts', 'sync', 'agents', 'actions', 'workflows', 'identities', 'endpoints', 'members'];
    const group = await readCounts(context('group'), groupIds);
    for (const id of groupIds) assert.equal(group[id].failed, false, `${id} must load`);
    assert.equal(group.documents.count, 1700);
    assert.equal(group.prompts.count, 1001);
    assert.equal(group.members.count, 1201);
    assert.equal(group.agents.count, 2);
    assert.equal(group.actions.count, 3);
    for (const url of calls) {
        assert.ok(!url.pathname.includes('/api/user/') && !url.pathname.includes('/api/v2/admin/'));
        assert.ok(url.pathname.includes('/workspace-a/') || url.searchParams.get('group_id') === 'workspace-a');
        if (url.pathname.endsWith('/prompts') || url.pathname.endsWith('/members')) {
            assert.equal(url.searchParams.get('page_size'), '1');
        }
    }

    const publicIds = ['documents', 'tags', 'prompts', 'sync', 'identities', 'members'];
    const publicCounts = await readCounts(context('public'), [...publicIds, 'agents', 'settings', 'statistics']);
    assert.deepEqual(Object.keys(publicCounts).sort(), publicIds.sort());
    for (const result of Object.values(publicCounts)) assert.equal(result.failed, false);
    for (const url of calls) assert.ok(url.pathname.startsWith('/api/public-workspaces/workspace-a/'));
    const publicReader = { ...context('public'), role: 'User' };
    const readerCounts = await readCounts(publicReader, ['documents', 'members']);
    assert.deepEqual(Object.keys(readerCounts), ['documents']);
    assert.ok(!calls.some((url) => url.pathname.endsWith('/members')));

    const fallback = await readCounts(context('group', 'workspace-a', false), ['documents']);
    assert.equal(fallback.documents.count, 1700);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].searchParams.get('page_size'), '1');
    const delegationContext = context('group');
    delegationContext.sections.actions.enabled = false;
    const delegation = await readCounts(delegationContext, ['actions']);
    assert.equal(delegation.actions.count, 2);
    assert.equal(calls[0].pathname, '/api/group/plugins');

    for (const bad of [null, {}, { prompts: [], total_count: -1 }, { prompts: [], total_count: '42' },
        { prompts: [], total_count: 0.5 }, { prompts: [{ id: 'wrong', group_id: 'other' }], total_count: 1 }]) {
        responder = (url) => url.pathname.endsWith('/prompts') ? bad : payload(url);
        const partial = await readCounts(context('group'), ['prompts', 'tags']);
        assert.deepEqual(partial.prompts, { failed: true });
        assert.equal(partial.tags.count, 1);
    }
    for (const id of ['identities', 'workflows', 'actions', 'agents', 'sync', 'endpoints', 'members']) {
        responder = () => ({});
        const malformed = await readCounts(context('group'), [id]);
        assert.deepEqual(malformed[id], { failed: true }, `${id} cannot turn a malformed response into zero`);
    }
    responder = (url) => url.pathname.endsWith('/prompts')
        ? { prompts: [], total_count: 0 } : payload(url);
    const empty = await readCounts(context('group'), ['prompts']);
    assert.deepEqual(empty.prompts, { count: 0, failed: false });
    for (const bad of [undefined, null, -1, 1.5, '0', NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
        assert.throws(() => validWorkspaceCount(bad));
    }

    let finish;
    const gate = new Promise((resolve) => { finish = resolve; });
    const controller = new AbortController();
    const seen = [];
    const pending = loadWorkspaceCounts({
        documents: async () => gate,
        tags: async () => 0,
    }, ['documents', 'tags', 'locked'], controller.signal, (id, result) => seen.push([id, result]));
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(seen, [['tags', { count: 0, failed: false }]]);
    controller.abort();
    finish(99);
    await pending;
    assert.equal(seen.length, 1, 'An obsolete response must never publish a count');
    let invoked = false;
    await loadWorkspaceCounts({ documents: async () => { invoked = true; return 1; } },
        ['documents'], controller.signal, () => assert.fail('Aborted loads cannot publish'));
    assert.equal(invoked, false);
    console.log('Shared workspace count contracts passed.');
} finally {
    globalThis.fetch = originalFetch;
}
