// test_v2_group_documents_logic.mjs
// Version: 0.261.128
// Implemented in: 0.261.128
// Executes the shipped document adapters, selection rules and chat handoff against closed HTTP responses.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const {
    createGroupDocumentReader, documentExplorerScopeKey, documentSelectionReason,
    fetchScopedGroupDocument, groupDocumentOrigin, PERSONAL_DOCUMENT_READER, supportedDocumentQuery,
} = await import('../application/v2_ui/src/lib/documentReadAdapter.ts');
const {
    applySelection, DEFAULT_DOCUMENT_QUERY, DOCUMENT_PLACES, DOCUMENT_SORT_FIELDS,
    EMPTY_SELECTION, moveSelection, pruneSelection, toggleSelectAll,
} = await import('../application/v2_ui/src/lib/documentExplorer.ts');
const {
    buildContextHandoffParams, readContextHandoff, resolveContextHandoff,
} = await import('../application/v2_ui/src/lib/chatContextHandoff.ts');
const { contextScopes, contextDocumentIds, contextTags } = await import('../application/v2_ui/src/lib/chatContext.ts');
const { resolveDocumentScope } = await import('../application/v2_ui/src/lib/documentScope.ts');
const { GROUP_WORKSPACE_SECTION_IDS } = await import('../application/v2_ui/src/lib/workspaceContext.ts');

const originalFetch = globalThis.fetch;
const capabilities = { sort_fields: [...DOCUMENT_SORT_FIELDS], facets: true, places: true };
const facets = {
    total: 125, untagged: 23, processing: 4, errors: 2, recent: 30, shared_with_me: 12,
    by_tag: { Finance: 52, Team: 84 }, by_classification: { Internal: 70 },
};
let calls = [];
let handler;
let checks = 0;

function document(groupId = 'group-a', overrides = {}) {
    return {
        id: 'document-1', file_name: 'team.pdf', title: 'Team report', version: 3,
        group_id: groupId, shared_approval_status: 'owner', tags: ['Finance', 'Team'],
        percentage_complete: 100, ...overrides,
    };
}

function context(id) {
    return {
        schema_version: 1, enabled: true, viewer_id: 'viewer', scope: { kind: 'group', id },
        workspace: {
            name: `Workspace ${id}`, description: 'Team knowledge.',
            owner: { display_name: 'Owner', email: 'owner@example.test' }, hero_color: '#0078d4', logo_url: null,
        },
        role: 'Owner', status: 'active', can_manage_workspace: true,
        sections: Object.fromEntries(GROUP_WORKSPACE_SECTION_IDS.map((section) => [
            section, { enabled: true, can_manage: true, reason: null, group: 'knowledge' },
        ])),
        document_permissions: {
            can_view: true, can_chat: true, can_upload: true,
            can_edit: true, can_delete: true, can_download: true,
        },
        document_queries: capabilities,
    };
}

function json(body, status = 200) {
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function defaultResponse(call) {
    if (call.path.startsWith('/api/v2/workspaces/group/')) return json(context(call.path.split('/').at(-1)));
    const groupId = call.params.get('group_id') ?? 'personal';
    if (call.path.endsWith('/facets')) return json(facets);
    if (call.path.endsWith('/tags')) return json({ tags: [{ name: 'Finance', count: 52, color: '#0078d4' }] });
    if (call.path.endsWith('/versions')) {
        return json({ document_id: 'document-1', group_id: groupId, revision_family_id: 'family', versions: [document(groupId)] });
    }
    if (call.path.endsWith('/document-1')) return json(document(groupId));
    if (['/api/group_documents', '/api/documents'].includes(call.path)) {
        return json({
            documents: [document(groupId)], total_count: 125,
            page: Number(call.params.get('page')), page_size: Number(call.params.get('page_size')),
        });
    }
    throw new Error(`Unexpected fixture request: ${call.method} ${call.path}`);
}

async function run(name, check) {
    calls = [];
    handler = defaultResponse;
    await check();
    checks += 1;
    console.log(`ok ${name}`);
}

globalThis.fetch = async (path, options = {}) => {
    const url = new URL(String(path), 'http://fixture.test');
    const call = { path: url.pathname, params: url.searchParams, method: options.method ?? 'GET', signal: options.signal };
    calls.push(call);
    return handler(call);
};

try {
    await run('viewer, workspace kind and ID isolate document state, including identical resource IDs', async () => {
        const personal = documentExplorerScopeKey('viewer', { kind: 'personal' });
        const group = documentExplorerScopeKey('viewer', { kind: 'group', id: 'viewer', name: 'Team' });
        const otherViewer = documentExplorerScopeKey('other', { kind: 'group', id: 'viewer', name: 'Team' });
        const otherGroup = documentExplorerScopeKey('viewer', { kind: 'group', id: 'group-b', name: 'Team' });
        assert.equal(new Set([personal, group, otherViewer, otherGroup]).size, 4);
        assert.equal(group, documentExplorerScopeKey('viewer', { kind: 'group', id: 'viewer', name: 'Renamed' }));
    });
    await run('every group read names exactly one encoded group and never sends group_ids', async () => {
        const reader = createGroupDocumentReader('group &+ A', 'Team', capabilities);
        const controller = new AbortController();
        const page = await reader.list(DEFAULT_DOCUMENT_QUERY, controller.signal);
        const tags = await reader.tags(controller.signal);
        const counts = await reader.facets(controller.signal);
        const detail = await reader.detail('document-1', controller.signal);
        const versions = await reader.versions('document-1', controller.signal);
        assert.equal(page.total_count, 125);
        assert.equal(tags.tags[0].count, 52);
        assert.deepEqual(counts, facets);
        assert.equal(detail.group_id, 'group &+ A');
        assert.equal(versions.group_id, 'group &+ A');
        assert.deepEqual(calls.map((call) => call.path), [
            '/api/group_documents', '/api/group_documents/tags', '/api/group_documents/facets',
            '/api/group_documents/document-1', '/api/group_documents/document-1/versions',
        ]);
        for (const call of calls) {
            assert.equal(call.method, 'GET');
            assert.deepEqual(call.params.getAll('group_id'), ['group &+ A']);
            assert.equal(call.params.has('group_ids'), false);
            assert.equal(call.signal, controller.signal);
        }
    });
    await run('all supported filters, sorts, directions and pages go to the server unchanged', async () => {
        const reader = createGroupDocumentReader('group-a', 'Team', capabilities);
        for (const sortBy of DOCUMENT_SORT_FIELDS) {
            for (const sortOrder of ['asc', 'desc']) {
                for (const place of DOCUMENT_PLACES) {
                    await reader.list({
                        ...DEFAULT_DOCUMENT_QUERY, place, sortBy, sortOrder,
                        page: 3, pageSize: 25, search: '  Team report  ', tags: ['Finance', 'Team'],
                        classification: 'Internal',
                    });
                    const params = calls.at(-1).params;
                    assert.equal(params.get('page'), '3');
                    assert.equal(params.get('page_size'), '25');
                    assert.equal(params.get('search'), 'Team report');
                    assert.equal(params.get('tags'), 'Finance,Team');
                    assert.equal(params.get('classification'), 'Internal');
                    assert.equal(params.get('place'), place === 'all' ? null : place);
                    assert.equal(params.get('sort_by'), sortBy);
                    assert.equal(params.get('sort_order'), sortOrder);
                }
            }
        }
    });
    await run('unadvertised places, facets and sort fields are not offered or requested', async () => {
        const reader = createGroupDocumentReader('group-a', 'Team', {
            sort_fields: ['file_name', 'unsupported'], facets: false, places: false,
        });
        const query = supportedDocumentQuery({ ...DEFAULT_DOCUMENT_QUERY, place: 'recent', sortBy: 'file_size' }, reader);
        assert.equal(query.place, 'all');
        assert.equal(query.sortBy, 'file_name');
        assert.deepEqual(reader.queries.sortFields, ['file_name']);
        await reader.list({ ...DEFAULT_DOCUMENT_QUERY, place: 'recent', sortBy: 'file_size' });
        assert.equal(calls[0].params.has('place'), false);
        assert.equal(calls[0].params.get('sort_by'), 'file_name');
        await assert.rejects(reader.facets(), /not supported/);
        const noSort = createGroupDocumentReader('group-a', 'Team', { sort_fields: [], facets: false, places: false });
        await noSort.list(DEFAULT_DOCUMENT_QUERY);
        assert.equal(calls.at(-1).params.has('sort_by'), false);
        assert.equal(calls.at(-1).params.has('sort_order'), false);
    });
    await run('invalid scope identifiers cannot fall back to an active or personal workspace', async () => {
        for (const id of ['', ' leading', 'trailing ', '.', '..', 'a/b', 'a\\b', 'a?b', 'a#b']) {
            assert.throws(() => createGroupDocumentReader(id, 'Team', capabilities), /Invalid/);
        }
        const pending = fetchScopedGroupDocument('', 'document-1');
        await assert.rejects(pending, /Invalid/);
        assert.equal(calls.length, 0);
    });
    await run('wrong-resource, wrong-group and malformed page responses remain errors', async () => {
        const reader = createGroupDocumentReader('group-a', 'Team', capabilities);
        handler = () => json(document('group-b'));
        await assert.rejects(reader.detail('document-1'), /does not match/);
        handler = () => json(document('group-a', { id: 'foreign' }));
        await assert.rejects(reader.detail('document-1'), /does not match/);
        handler = () => json({ documents: [], total_count: '125', page: 1, page_size: 50 });
        await assert.rejects(reader.list(DEFAULT_DOCUMENT_QUERY), /invalid document page/);
        handler = () => json({ tags: ['Finance'] });
        await assert.rejects(reader.tags(), /invalid document tags/);
        handler = () => json({ ...facets, by_tag: { Finance: -1 } });
        await assert.rejects(reader.facets(), /invalid document counts/);
        handler = () => json({ error: 'Access denied.' }, 403);
        await assert.rejects(reader.list(DEFAULT_DOCUMENT_QUERY), (error) => error.status === 403);
        assert.ok(calls.every((call) => call.path.startsWith('/api/group_documents')));
    });
    await run('version envelopes and every revision retain exact authorized group relationships', async () => {
        const reader = createGroupDocumentReader('group-a', 'Team', capabilities);
        handler = () => json({
            document_id: 'document-1', group_id: 'group-a', revision_family_id: 'family',
            versions: [document('origin', { shared_group_active_id: 'group-a', shared_approval_status: 'not_approved' })],
        });
        const result = await reader.versions('document-1');
        assert.equal(result.versions[0].shared_approval_status, 'not_approved');
        handler = () => json({ document_id: 'document-1', group_id: 'group-a', versions: [document('group-b')] });
        await assert.rejects(reader.versions('document-1'), /does not match/);
        handler = () => json({ document_id: 'document-1', group_id: 'group-b', versions: [] });
        await assert.rejects(reader.versions('document-1'), /does not match/);
    });
    await run('ownership and projected approval, never personal identity or raw share lists, govern selection', async () => {
        const scope = { kind: 'group', id: 'group-a', name: 'Team' };
        const owned = document();
        const shared = document('origin', { shared_group_active_id: 'group-a', shared_approval_status: 'approved', owner_group_name: 'Origin team' });
        assert.equal(documentSelectionReason(owned, scope), null);
        assert.equal(documentSelectionReason(shared, scope), null);
        assert.equal(groupDocumentOrigin(shared, 'group-a'), 'Shared by Origin team');
        for (const blocked of [
            document('group-a', { shared_approval_status: undefined }),
            { ...shared, shared_approval_status: 'not_approved' },
            { ...shared, shared_approval_status: 'none', user_id: 'viewer', shared_group_ids: ['group-a'] },
            { ...shared, shared_group_active_id: 'group-b' },
            { ...shared, group_id: undefined },
            document('group-a', { content_screening: null }),
            document('group-a', { content_screening: { state: 'pending_review', available: false, finding_count: 1 } }),
            document('group-a', { content_screening: { state: 'rejected', available: true, finding_count: 1 } }),
        ]) assert.ok(documentSelectionReason(blocked, scope));
        assert.match(documentSelectionReason(owned, scope, false), /not currently available/);
        assert.equal(documentSelectionReason(document('group-a', {
            content_screening: { state: 'approved_with_flags', available: true, finding_count: 1 },
        }), scope), null);
    });
    await run('select-all, ranges, arrows and pruning use the same eligible source set', async () => {
        const scope = { kind: 'group', id: 'group-a', name: 'Team' };
        const rows = [
            document('group-a', { id: 'first' }),
            document('origin', { id: 'pending', shared_group_active_id: 'group-a', shared_approval_status: 'not_approved' }),
            document('group-a', { id: 'held', content_screening: null }),
            document('origin', { id: 'last', shared_group_active_id: 'group-a', shared_approval_status: 'approved' }),
        ];
        const ids = rows.filter((row) => !documentSelectionReason(row, scope)).map((row) => row.id);
        const all = toggleSelectAll(EMPTY_SELECTION, ids);
        const start = applySelection(EMPTY_SELECTION, 'first', 'replace', ids);
        const range = applySelection(start, 'last', 'range', ids);
        const arrow = moveSelection(start, ids, 1, false);
        const pruned = pruneSelection({ ids: ['first', 'pending', 'held'], anchorId: 'pending' }, ids);
        assert.deepEqual(all.ids, ['first', 'last']);
        assert.deepEqual(range.ids, all.ids);
        assert.deepEqual(arrow.ids, ['last']);
        assert.deepEqual(pruned.ids, ['first']);
    });
    await run('a group handoff revalidates access and carries exact documents and tag scope', async () => {
        const params = buildContextHandoffParams({ documentIds: ['document-1'], tags: ['Finance', 'Team'], docScope: 'group', groupId: 'group-a' });
        const handoff = readContextHandoff(new URLSearchParams(params));
        const items = await resolveContextHandoff(handoff, { viewerId: 'viewer' });
        assert.deepEqual(contextScopes(items), { includesPersonal: false, groupIds: ['group-a'], publicWorkspaceIds: [] });
        assert.deepEqual(contextDocumentIds(items), ['document-1']);
        assert.deepEqual(contextTags(items), ['Finance', 'Team']);
        assert.equal(calls[0].path, '/api/v2/workspaces/group/group-a');
        assert.deepEqual(calls[1].params.getAll('group_id'), ['group-a']);
        assert.ok(calls.every((call) => call.method === 'GET'));
        const ordinaryChatScope = resolveDocumentScope({
            activeGroupId: 'group-b', contextGroupIds: contextScopes(items).groupIds,
        });
        assert.deepEqual(ordinaryChatScope.active_group_ids, ['group-b', 'group-a']);
        assert.equal(ordinaryChatScope.doc_scope, 'all', 'A group handoff must not rewrite ordinary chat aggregation.');
    });
    await run('group router state cannot bypass fresh screening or approval checks', async () => {
        const handoff = readContextHandoff(new URLSearchParams('doc_scope=group&group_id=group-a&document_ids=document-1'));
        const options = { viewerId: 'viewer', state: {
            contextDocuments: [{ document: document(), scope: { kind: 'group', id: 'group-a', name: 'Team' } }],
        } };
        handler = (call) => call.path.includes('/group_documents/') ? json(document('group-a', { content_screening: null })) : defaultResponse(call);
        await assert.rejects(resolveContextHandoff(handoff, options), /Held/);
        handler = (call) => call.path.includes('/group_documents/') ? json(document('origin', {
            shared_group_active_id: 'group-a', shared_approval_status: 'not_approved',
        })) : defaultResponse(call);
        await assert.rejects(resolveContextHandoff(handoff, options), /awaiting approval/);
    });
    await run('lifecycle denial and malformed group handoffs never adopt personal context', async () => {
        const handoff = readContextHandoff(new URLSearchParams('doc_scope=group&group_id=group-a&tags=Finance'));
        handler = (call) => {
            if (call.path.startsWith('/api/v2/workspaces/group/')) {
                const denied = context('group-a');
                denied.document_permissions.can_chat = false;
                return json(denied);
            }
            return defaultResponse(call);
        };
        await assert.rejects(resolveContextHandoff(handoff, { viewerId: 'viewer' }), /not available/);
        await assert.rejects(resolveContextHandoff({ ...handoff, groupId: '' }, { viewerId: 'viewer' }), /explicit group/);
        await assert.rejects(resolveContextHandoff(handoff), /authenticated viewer/);
        assert.equal(calls.length, 1);
    });
    await run('personal reads, settings-independent defaults and router-state handoff remain personal', async () => {
        await PERSONAL_DOCUMENT_READER.list(DEFAULT_DOCUMENT_QUERY);
        await PERSONAL_DOCUMENT_READER.tags();
        await PERSONAL_DOCUMENT_READER.facets();
        await PERSONAL_DOCUMENT_READER.detail('document-1');
        await PERSONAL_DOCUMENT_READER.versions('document-1');
        assert.ok(calls.every((call) => call.path.startsWith('/api/documents') && !call.params.has('group_id')));
        const before = calls.length;
        const handoff = readContextHandoff(new URLSearchParams('doc_scope=personal&document_ids=document-1'));
        const items = await resolveContextHandoff(handoff, { state: { contextDocuments: [
            { document: document('personal'), scope: { kind: 'personal', id: null, name: 'My workspace' } },
        ] } });
        assert.equal(calls.length, before);
        assert.deepEqual(contextScopes(items), { includesPersonal: true, groupIds: [], publicWorkspaceIds: [] });
    });
    console.log(`${checks} group document adapter and selection checks passed.`);
} finally {
    globalThis.fetch = originalFetch;
}
