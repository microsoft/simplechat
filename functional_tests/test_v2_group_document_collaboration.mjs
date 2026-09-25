// test_v2_group_document_collaboration.mjs
// Version: 0.261.169
// Implemented in: 0.261.130
// Executes scoped collaboration, receipt, repair and notification-link boundaries.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import './test_support/tsResolve.mjs';

const {
    DOCUMENT_COLLABORATION_OPERATIONS, advertisedDocumentCollaboration,
    createDocumentCollaboration, createPublicDocumentCollaboration, parseDocumentCollaborationState, parseCollaborationReceipt,
    collaborationFailure,
} = await import('../application/v2_ui/src/lib/documentCollaboration.ts');
const { documentSelectionReason } = await import('../application/v2_ui/src/lib/documentReadAdapter.ts');
const { createGroupDocumentOperations } = await import('../application/v2_ui/src/lib/documentOperations.ts');
const { groupWorkspaceDocumentPath, readGroupDocumentTarget } = await import('../application/v2_ui/src/lib/groupWorkspaceNavigation.ts');

const originalFetch = globalThis.fetch;
const scope = { kind: 'group', id: 'group-a', name: 'Research' };
const capability = { schema_version: 1, operations: [...DOCUMENT_COLLABORATION_OPERATIONS] };
// A receipt the parser refuses must be refused for what's wrong with the receipt, never for a bad scope.
const RECEIPT_REFUSAL = /did not confirm this exact|incomplete or ambiguous|invalid repair details/;
const adapter = createDocumentCollaboration(scope, capability);
let calls = [];
let handler;
let checks = 0;

function document(changes = {}) {
    return {
        id: 'doc-1', file_name: 'review.pdf', group_id: 'group-a', version: 3,
        is_current_version: true, shared_approval_status: 'owner',
        document_collaboration_actions: [...DOCUMENT_COLLABORATION_OPERATIONS],
        document_actions: [], ...changes,
    };
}

function state(changes = {}) {
    return {
        schema_version: 1, group_id: 'group-a', document_id: 'doc-1', document_version: 3,
        etag: '"review-etag-1"', owner_group: { id: 'group-a', name: 'Research' },
        relationship: 'owner', actions: [...DOCUMENT_COLLABORATION_OPERATIONS],
        recipients: [{ id: 'recipient', name: 'Recipient', description: 'A recipient', approval_status: 'approved' }],
        publication: null, ...changes,
    };
}

function publication(changes = {}) {
    return {
        status: 'pending_approval', is_requester: false, requested_by_user_id: 'requester',
        requested_by_display_name: 'Requester', requested_at: '2026-09-22T10:00:00Z',
        actions: ['approve_artifact', 'reject_artifact'], ...changes,
    };
}

function incoming(changes = {}) {
    return document({
        group_id: 'origin', shared_group_active_id: 'group-a',
        shared_approval_status: 'not_approved', ...changes,
    });
}

function incomingState(changes = {}) {
    return state({
        owner_group: { id: 'origin', name: 'Source group' }, relationship: 'not_approved',
        actions: ['inspect', 'approve_share', 'remove_share'], recipients: [],
        ...changes,
    });
}

function receipt(action, result, changes = {}) {
    return {
        schema_version: 1, group_id: 'group-a', document_id: 'doc-1',
        action, status: 'applied', state: result, errors: [], ...changes,
    };
}

function json(body, status = 200) {
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function defaultResponse(call) {
    if (call.path.endsWith('/sharing')) return json(state());
    if (call.path.endsWith('/sharing/targets')) return json({
        groups: [{ id: 'new-group', name: 'New group', description: 'New recipient' }],
        page: Number(call.params.get('page')), page_size: Number(call.params.get('page_size')), total_count: 123,
    });
    if (call.path.endsWith('/share') && call.method === 'POST') return json(receipt('share', 'not_approved', { target_group_id: call.body.target_group_id }));
    if (call.path.includes('/share/')) return json(receipt('unshare', 'removed', { target_group_id: decodeURIComponent(call.path.split('/').at(-1)) }));
    if (call.path.endsWith('/approve-share')) return json(receipt('approve_share', 'approved'));
    if (call.path.endsWith('/received-share')) return json(receipt('remove_share', 'denied'));
    if (call.path.endsWith('/artifact/approve')) return json(receipt('approve_artifact', 'approved', { status: 'queued' }), 202);
    if (call.path.endsWith('/artifact/reject')) return json(receipt('reject_artifact', 'rejected'));
    if (call.path.endsWith('/artifact/cancel')) return json(receipt('cancel_artifact', 'cancelled'));
    throw new Error(`Unexpected request ${call.method} ${call.path}`);
}

globalThis.fetch = async (path, options = {}) => {
    const url = new URL(String(path), 'http://fixture.test');
    const call = {
        path: url.pathname, params: url.searchParams, method: options.method ?? 'GET',
        body: options.body ? JSON.parse(options.body) : null, signal: options.signal,
    };
    calls.push(call);
    return handler(call);
};

async function run(name, test) {
    calls = [];
    handler = defaultResponse;
    await test();
    checks += 1;
    console.log(`ok ${name}`);
}

try {
    await run('old and unknown capabilities never enable review or decisions', async () => {
        for (const value of [undefined, null, {}, { schema_version: 2, operations: ['inspect'] }, { schema_version: 1, operations: ['inspect', 1] }]) {
            const old = createDocumentCollaboration(scope, value);
            assert.equal(old.allows('inspect', document()), false);
            await assert.rejects(old.read(document()), /not currently permitted/);
        }
        assert.deepEqual([...advertisedDocumentCollaboration({ schema_version: 1, operations: ['future', 'inspect'] })], ['inspect']);
        assert.equal(adapter.allows('inspect', document({ document_collaboration_actions: undefined })), false);
        assert.equal(calls.length, 0);
    });
    await run('workspace, record, relationship and publication grants remain separate', async () => {
        const doc = document();
        const own = parseDocumentCollaborationState(state(), 'group-a', 'doc-1');
        assert.equal(adapter.allows('share', doc, own), true);
        assert.equal(adapter.allows('approve_share', doc, own), false);
        const recipient = parseDocumentCollaborationState(incomingState(), 'group-a', 'doc-1');
        assert.equal(adapter.allows('approve_share', incoming(), recipient), true);
        assert.equal(adapter.allows('share', incoming(), recipient), false);
        assert.match(documentSelectionReason(incoming(), scope), /awaiting approval/);
        const management = createGroupDocumentOperations(scope, { schema_version: 1, operations: ['edit_metadata', 'delete'] });
        assert.equal(management.allows('edit_metadata', incoming()), false);
        assert.equal(management.allows('delete', incoming()), false);
    });
    await run('pending publication requester can cancel without acquiring manager or chat grants', async () => {
        const requester = createDocumentCollaboration(scope, { schema_version: 1, operations: ['inspect', 'cancel_artifact'] });
        const pending = document({ generated_artifact_promotion_status: 'pending_approval', status: 'Pending approval' });
        const review = parseDocumentCollaborationState(state({
            actions: ['inspect', 'cancel_artifact'],
            publication: publication({ is_requester: true, actions: ['cancel_artifact'] }),
        }), 'group-a', 'doc-1');
        assert.equal(requester.allows('inspect', pending), true);
        assert.equal(requester.allows('cancel_artifact', pending, review), true);
        assert.equal(requester.allows('approve_artifact', pending, review), false);
        assert.match(documentSelectionReason(pending, scope), /publication approval/);
        assert.equal(requester.allows('cancel_artifact', pending, { ...review, publication: { ...review.publication, is_requester: false } }), false);
        await requester.mutate(pending, review, 'cancel_artifact');
        assert.equal(calls[0].path, '/api/groups/group-a/documents/doc-1/artifact/cancel');
    });
    await run('positive sharing/current publication restrictions do not prevent explicitly allowed cleanup', async () => {
        const held = document({ content_screening: { state: 'pending_review', available: false, finding_count: 1 } });
        const own = parseDocumentCollaborationState(state(), 'group-a', 'doc-1');
        assert.equal(adapter.allows('share', held, own), false);
        assert.equal(adapter.allows('unshare', held, own), true);
        const historical = document({ is_current_version: false });
        const pendingPublication = parseDocumentCollaborationState(state({ publication: publication() }), 'group-a', 'doc-1');
        assert.equal(adapter.allows('approve_artifact', historical, pendingPublication), false);
        assert.equal(adapter.allows('reject_artifact', historical, pendingPublication), true);
        assert.equal(adapter.allows('share', historical, own), false);
    });
    await run('safe sharing projection drops private source/config and receipt fields', async () => {
        const result = parseDocumentCollaborationState(state({
            secret: 'private', source_blob: 'private',
            owner_group: { id: 'group-a', name: 'Research', settings: 'private' },
            publication: publication({ private_conversation_id: 'private', source_blob: 'private' }),
        }), 'group-a', 'doc-1');
        const serialized = JSON.stringify(result);
        assert.equal(serialized.includes('private'), false);
        assert.equal(result.publication.requested_by_display_name, 'Requester');
        assert.equal(result.etag, '"review-etag-1"');
    });
    await run('wrong identity, malformed state and other recipients are rejected', async () => {
        for (const value of [
            state({ schema_version: 2 }), state({ group_id: 'other' }), state({ document_id: 'other' }),
            state({ etag: '' }), state({ document_version: 0 }), state({ recipients: [{}] }),
            incomingState({ relationship: ['approved'] }),
            state({ owner_group: { id: 'other', name: 'Wrong owner' } }),
            incomingState({ recipients: [{ id: 'other-recipient', name: 'Other', description: '', approval_status: 'approved' }] }),
            state({ publication: { status: 'pending_approval', is_requester: true } }),
            state({ publication: publication({ status: 'unavailable', actions: ['approve_artifact'] }) }),
        ]) assert.throws(() => parseDocumentCollaborationState(value, 'group-a', 'doc-1'));
    });
    await run('GETs and every mutation use exact immutable group/document paths and ETag bodies', async () => {
        const source = { kind: 'group', id: 'group-a', name: 'Original group' };
        const bound = createDocumentCollaboration(source, capability);
        source.id = 'changed-active-group';
        assert.throws(() => { bound.scope.id = 'retargeted'; }, TypeError);
        const doc = document();
        const own = await bound.read(doc);
        const controller = new AbortController();
        const found = await bound.targets(doc, own, { search: '  Recipient  ', page: 3, pageSize: 25 }, controller.signal);
        assert.equal(found.total_count, 123);
        assert.deepEqual(Object.fromEntries(calls.at(-1).params), { page: '3', page_size: '25', search: 'Recipient' });
        assert.equal(calls.at(-1).signal, controller.signal);
        await bound.mutate(doc, own, 'share', 'new-group');
        await bound.mutate(doc, own, 'unshare', 'recipient');
        const recipient = parseDocumentCollaborationState(incomingState(), 'group-a', 'doc-1');
        await bound.mutate(incoming(), recipient, 'approve_share');
        await bound.mutate(incoming(), recipient, 'remove_share');
        const pub = parseDocumentCollaborationState(state({ publication: publication({ is_requester: true, actions: ['approve_artifact', 'reject_artifact', 'cancel_artifact'] }) }), 'group-a', 'doc-1');
        for (const action of ['approve_artifact', 'reject_artifact', 'cancel_artifact']) await bound.mutate(doc, pub, action);
        assert.ok(calls.every((call) => call.path.startsWith('/api/groups/group-a/documents/doc-1/')));
        assert.ok(calls.every((call) => !call.params.has('group_id') && !call.params.has('group_ids')));
        const writes = calls.filter((call) => call.method !== 'GET');
        assert.equal(writes.length, 7);
        assert.ok(writes.every((call) => call.signal === undefined));
        for (const call of writes) {
            assert.equal(call.body.expected_etag, own.etag);
            assert.deepEqual(Object.keys(call.body).sort(), call.path.endsWith('/share') ? ['expected_etag', 'target_group_id'] : ['expected_etag']);
        }
    });
    await run('public decisions stay bound to the workspace the adapter was created for', async () => {
        const source = { kind: 'public', id: 'pub-a', name: 'Original workspace' };
        const bound = createPublicDocumentCollaboration(source, capability);
        source.id = 'changed-public-workspace';
        source.name = 'Renamed later';
        const results = { approve: ['approve_artifact', 'approved', 'queued', 202], reject: ['reject_artifact', 'rejected', 'applied', 200], cancel: ['cancel_artifact', 'cancelled', 'applied', 200] };
        handler = (call) => {
            if (call.path.endsWith('/publication')) return json({
                schema_version: 1, public_workspace_id: 'pub-a', document_id: 'doc-1', document_version: 3,
                etag: '"public-etag-1"', publication: publication({ is_requester: true, actions: ['approve_artifact', 'reject_artifact', 'cancel_artifact'] }),
            });
            const [action, result, status, code] = results[call.path.split('/').at(-1)];
            return json({ schema_version: 1, public_workspace_id: 'pub-a', document_id: 'doc-1', action, status, state: result, errors: [] }, code);
        };
        const doc = document({ group_id: undefined, public_workspace_id: 'pub-a' });
        const review = await bound.read(doc);
        assert.equal(review.owner_group.name, 'Original workspace');
        for (const action of ['approve_artifact', 'reject_artifact', 'cancel_artifact']) await bound.mutate(doc, review, action);
        assert.ok(calls.every((call) => call.path.startsWith('/api/public-workspaces/pub-a/documents/doc-1/')));
        assert.equal(calls.filter((call) => call.method === 'POST').length, 3);
        assert.equal(bound.scope.id, 'pub-a');
        assert.throws(() => { bound.scope.id = 'retargeted'; }, TypeError);
    });
    await run('self targets, recipient overrides and forged document/state pairs never issue a request', async () => {
        const own = parseDocumentCollaborationState(state(), 'group-a', 'doc-1');
        await assert.rejects(adapter.mutate(document(), own, 'share', 'group-a'), /different recipient/);
        await assert.rejects(adapter.mutate(incoming(), incomingState(), 'approve_share', 'recipient'), /override/);
        await assert.rejects(adapter.mutate(document({ id: 'other' }), own, 'share', 'recipient'), /not currently permitted/);
        await assert.rejects(adapter.read(document({ group_id: 'other' })), /not currently permitted/);
        assert.equal(calls.length, 0);
    });
    await run('recipient discovery never substitutes self, another page or unbounded browser filtering', async () => {
        const own = parseDocumentCollaborationState(state(), 'group-a', 'doc-1');
        for (const payload of [
            { groups: [], page: 1, page_size: 25, total_count: '100' },
            { groups: [], page: 2, page_size: 25, total_count: 100 },
            { groups: [{ id: 'group-a', name: 'Self', description: '' }], page: 1, page_size: 25, total_count: 1 },
        ]) {
            handler = () => json(payload);
            await assert.rejects(adapter.targets(document(), own, { search: '', page: 1, pageSize: 25 }), /invalid/);
        }
    });
    await run('exact receipt status/action/target binding rejects ambiguous successful responses', async () => {
        const good = receipt('share', 'not_approved', { target_group_id: 'recipient' });
        for (const [value, status] of [
            [{ message: 'Done' }, 200], ['<html>Done</html>', 200],
            [{ ...good, document_id: 'other' }, 200], [{ ...good, group_id: 'other' }, 200],
            [{ ...good, action: 'unshare' }, 200], [{ ...good, target_group_id: 'wrong' }, 200],
            [{ ...good, status: 'queued' }, 202], [{ ...good, status: 'partial' }, 207],
            [good, 201], [{ ...good, errors: [{ stage: 'notice', code: 'failed', message: 'Failed' }] }, 200],
            [{ ...good, state: 'owner' }, 200],
        ]) assert.throws(() => parseCollaborationReceipt(value, status, scope, 'doc-1', 'share', 'recipient'), RECEIPT_REFUSAL);
        assert.throws(() => parseCollaborationReceipt(receipt('approve_share', 'approved', { target_group_id: 'recipient' }), 200, scope, 'doc-1', 'approve_share'), /did not confirm this exact/);
    });
    await run('partial stage errors remain partial without automatic replay', async () => {
        const own = parseDocumentCollaborationState(state(), 'group-a', 'doc-1');
        handler = () => json(receipt('unshare', 'removed', {
            target_group_id: 'recipient', status: 'partial',
            errors: [{ stage: 'notifications', code: 'delivery_failed', message: 'Notification delivery was not confirmed.' }],
        }), 207);
        const result = await adapter.mutate(document(), own, 'unshare', 'recipient');
        assert.equal(result.status, 'partial');
        assert.equal(result.state, 'removed');
        assert.equal(result.errors[0].stage, 'notifications');
        assert.equal(calls.length, 1);
    });
    await run('owner revocation repair retains the exact removed target without inventing a recipient', async () => {
        const prior = parseCollaborationReceipt(receipt('unshare', 'removed', {
            target_group_id: 'recipient', status: 'partial',
            errors: [{ stage: 'cache', code: 'cleanup_failed', message: 'Access is removed; cache cleanup remains.' }],
        }), 207, scope, 'doc-1', 'unshare', 'recipient');
        const refreshed = parseDocumentCollaborationState(state({
            etag: '"fresh-owner-state"', recipients: [], actions: ['inspect', 'share', 'unshare'],
        }), 'group-a', 'doc-1');
        await assert.rejects(adapter.mutate(document(), refreshed, 'unshare', 'recipient'), /no longer/);
        assert.equal(calls.length, 0);
        const repaired = await adapter.mutate(document(), refreshed, 'unshare', 'recipient', prior);
        assert.equal(repaired.state, 'removed');
        assert.equal(calls[0].body.expected_etag, refreshed.etag);
        await assert.rejects(adapter.mutate(document(), refreshed, 'unshare', 'different', prior), /no longer matches/);
        await assert.rejects(adapter.mutate(document(), state(), 'unshare', 'recipient', prior), /no longer matches/);
        assert.equal(calls.length, 1);
    });
    await run('stale ETag stays a conflict and refreshed repeats preserve recorded approval', async () => {
        const own = parseDocumentCollaborationState(state(), 'group-a', 'doc-1');
        handler = () => json({ error: 'etag_conflict', message: 'State changed.' }, 409);
        let conflict;
        try { await adapter.mutate(document(), own, 'share', 'recipient'); } catch (cause) { conflict = cause; }
        assert.match(collaborationFailure(conflict), /input is kept.*Refresh/);
        assert.equal(calls.length, 1);
        handler = () => json(receipt('share', 'approved', { target_group_id: 'recipient', status: 'unchanged' }));
        const repeated = await adapter.mutate(document(), { ...own, etag: '"fresh"' }, 'share', 'recipient');
        assert.equal(repeated.state, 'approved');
        assert.equal(calls.at(-1).body.expected_etag, '"fresh"');
    });
    await run('publication queues and failed handoffs cannot be relabeled as ordinary availability', async () => {
        const pending = document({ generated_artifact_promotion_status: 'pending_approval' });
        const pub = parseDocumentCollaborationState(state({ publication: publication() }), 'group-a', 'doc-1');
        const queued = await adapter.mutate(pending, pub, 'approve_artifact');
        assert.equal(queued.status, 'queued');
        assert.match(documentSelectionReason(pending, scope), /approval/);
        const failed = parseCollaborationReceipt(receipt('approve_artifact', 'approval_failed', {
            status: 'partial', errors: [{ stage: 'queue', code: 'handoff_failed', message: 'Approval is recorded; processing needs reconciliation.' }],
        }), 207, scope, 'doc-1', 'approve_artifact');
        assert.equal(failed.state, 'approval_failed');
        assert.throws(() => parseCollaborationReceipt(receipt('approve_artifact', 'approval_failed'), 200, scope, 'doc-1', 'approve_artifact'), /incomplete or ambiguous/);
    });
    await run('repair-only removed/denied state never fabricates an ordinary document grant', async () => {
        const raw = incomingState({ relationship: 'removed', actions: ['inspect', 'remove_share'] });
        handler = () => json(raw);
        const repair = await adapter.readRepair('doc-1');
        assert.equal(adapter.allows('remove_share', null, repair), true);
        for (const action of ['share', 'unshare', 'approve_share', 'approve_artifact', 'reject_artifact', 'cancel_artifact']) {
            assert.equal(adapter.allows(action, null, repair), false);
        }
        for (const changes of [
            { actions: ['inspect', 'approve_share'] }, { group_id: 'other' },
            { publication: publication() },
            { recipients: [{ id: 'other', name: 'Other', description: '', approval_status: 'approved' }] },
        ]) assert.throws(() => parseDocumentCollaborationState({ ...raw, ...changes }, 'group-a', 'doc-1'));
        handler = () => json(receipt('remove_share', 'removed'));
        const cleaned = await adapter.mutate(null, repair, 'remove_share');
        assert.equal(cleaned.state, 'removed');
        assert.deepEqual(calls.at(-1).body, { expected_etag: raw.etag });
        handler = () => json({ error: 'Gone' }, 404);
        await assert.rejects(adapter.readRepair('doc-1'), (cause) => cause.status === 404);
        assert.equal(cleaned.status, 'applied', 'A subsequent404 cannot rewrite an already validated decision receipt.');
    });
    await run('document deep links are explicit, singular and inert', async () => {
        assert.equal(groupWorkspaceDocumentPath('group a', 'doc one'), '/groups/group%20a/documents?document_id=doc+one');
        assert.deepEqual(readGroupDocumentTarget('?document_id=doc-1&action=approve'), { id: 'doc-1', error: null });
        for (const query of ['?document_id=', '?document_id=a&document_id=b', '?document_id=..', '?document_id=a%2Fb', '?document_id=a&group_id=other']) {
            assert.ok(readGroupDocumentTarget(query).error);
        }
        assert.deepEqual(readGroupDocumentTarget(''), { id: null, error: null });
    });

    const navigationCalls = [];
    const alerts = [];
    const nodes = new Map();
    const fakeDocument = {
        readyState: 'loading',
        getElementById: (id) => nodes.get(id) ?? null,
        addEventListener() {},
        body: { prepend: (node) => { nodes.set(node.id, node); alerts.push(node); } },
        createElement: () => ({ setAttribute() {}, textContent: '' }),
    };
    const fakeWindow = {
        location: { origin: 'http://simplechat.test', pathname: '/notifications', href: '' },
        addEventListener() {},
    };
    const sandbox = vm.createContext({
        window: fakeWindow, document: fakeDocument, URL, URLSearchParams, console,
        setTimeout, clearTimeout,
        fetch: async (path, options = {}) => { navigationCalls.push({ path, options }); return json({ success: true }); },
    });
    vm.runInContext(readFileSync(new URL('../application/single_app/static/js/notifications.js', import.meta.url), 'utf8'), sandbox);
    const notifications = fakeWindow.simpleChatNotifications;
    await run('native notifications validate link context and skip legacy active preference mutation', async () => {
        const notice = {
            is_read: true, link_url: '/v2/groups/group-a/documents?document_id=doc-1&action=approve',
            link_context: { workspace_type: 'group', group_id: 'group-a', document_id: 'doc-1' },
        };
        const target = notifications.resolveNavigationTarget(notice);
        assert.equal(target.nativeGroupDocument, true);
        assert.equal(target.href, '/v2/groups/group-a/documents?document_id=doc-1');
        await notifications.openNotification(notice);
        assert.equal(fakeWindow.location.href, target.href);
        assert.equal(navigationCalls.length, 0);
        for (const changed of [
            { link_context: { ...notice.link_context, group_id: 'other' } },
            { link_context: { ...notice.link_context, document_id: 'other' } },
            { link_url: 'https://other.test/v2/groups/group-a/documents?document_id=doc-1' },
            { link_url: '/v2/groups/group-a/documents?document_id=doc-1&document_id=other' },
            { link_url: '/v2/groups//documents?document_id=doc-1' },
            { link_url: '/v2/groups/group-a//documents?document_id=doc-1' },
            { link_url: '/v2//groups/group-a/documents?document_id=doc-1' },
            { link_url: '/v2/groups/documents?document_id=doc-1' },
            { link_url: '/v2/groups/group-a/document?document_id=doc-1' },
            { link_url: '/v2/groups/group-a/documents/other?document_id=doc-1' },
            { link_url: '/v2/GROUPS/group-a/documents?document_id=doc-1' },
            { link_url: 'javascript:alert(1)' },
        ]) {
            assert.throws(() => notifications.resolveNavigationTarget({ ...notice, ...changed }));
            await notifications.openNotification({ ...notice, ...changed });
        }
        assert.ok(alerts.length);
        assert.equal(navigationCalls.length, 0);
        await notifications.openNotification({ ...notice, id: 'notice', is_read: false });
        assert.equal(navigationCalls.length, 1);
        assert.equal(navigationCalls[0].path, '/api/notifications/notice/read');
    });
    await run('legacy notification and workflow links keep their existing group activation route', async () => {
        navigationCalls.length = 0;
        await notifications.openNotification({
            is_read: true, link_url: '/group_workspaces', link_context: { group_id: 'group-a' },
        });
        assert.equal(navigationCalls.length, 1);
        assert.equal(navigationCalls[0].path, '/api/groups/setActive');
        assert.deepEqual(JSON.parse(navigationCalls[0].options.body), { groupId: 'group-a' });
        assert.equal(fakeWindow.location.href, '/group_workspaces');
        const workflow = notifications.resolveNavigationTarget({
            link_url: '/v2/groups/group-a/workflows?workflow_id=one&document_id=source', link_context: { group_id: 'group-a', document_id: 'source' },
        });
        assert.equal(workflow.nativeGroupDocument, false);
    });
    console.log(`${checks} collaboration, repair and notification checks passed.`);
} finally {
    globalThis.fetch = originalFetch;
}
