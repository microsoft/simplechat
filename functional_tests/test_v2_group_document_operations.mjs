// test_v2_group_document_operations.mjs
// Version: 0.261.129
// Implemented in: 0.261.129
// Executes immutable operation paths, capability gates and complete outcome receipts.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const {
    DOCUMENT_OPERATIONS, PERSONAL_DOCUMENT_OPERATIONS, advertisedDocumentOperations,
    changedDocumentMetadata, createGroupDocumentOperations, inspectDocumentBatch,
    normalizeTagColor,
} = await import('../application/v2_ui/src/lib/documentOperations.ts');
const { documentSelectionReason } = await import('../application/v2_ui/src/lib/documentReadAdapter.ts');
const { documentStatus } = await import('../application/v2_ui/src/lib/documentExplorer.ts');
const { resolveContextHandoff } = await import('../application/v2_ui/src/lib/chatContextHandoff.ts');
const { GROUP_WORKSPACE_SECTION_IDS } = await import('../application/v2_ui/src/lib/workspaceContext.ts');
const { api, requestWithStatus, uploadFile, uploadFileWithStatus } = await import('../application/v2_ui/src/lib/apiClient.ts');

const originalFetch = globalThis.fetch;
const scope = { kind: 'group', id: 'group-a', name: 'Research group' };
const support = { schema_version: 1, operations: [...DOCUMENT_OPERATIONS] };
const adapter = createGroupDocumentOperations(scope, support);
let calls = [];
let handler;
let checks = 0;

function document(id = 'doc-1', changes = {}) {
    return {
        id, group_id: 'group-a', shared_approval_status: 'owner',
        file_name: `${id}.pdf`, title: 'Original title', abstract: 'Original abstract',
        authors: ['First', 'Second'], keywords: ['review'], publication_date: '2024-01-02',
        document_classification: 'Internal', is_current_version: true,
        document_actions: [...DOCUMENT_OPERATIONS], ...changes,
    };
}

function json(data, status = 200) {
    return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
}

function receipt(ids, key, errors = []) {
    return {
        [key]: ids.map((document_id) => ({ document_id })),
        errors,
        ...(key === 'deleted' ? { deleted_count: ids.length, error_count: errors.length } : {}),
    };
}

function context() {
    return {
        schema_version: 1, enabled: true, viewer_id: 'viewer',
        scope: { kind: 'group', id: 'group-a' },
        workspace: {
            name: 'Research group', description: 'Shared files', hero_color: '#0078d4',
            owner: { display_name: 'Owner', email: 'owner@example.test' }, logo_url: null,
        },
        role: 'Owner', status: 'active', can_manage_workspace: true,
        sections: Object.fromEntries(GROUP_WORKSPACE_SECTION_IDS.map((id) => [
            id, { enabled: true, can_manage: true, group: 'knowledge', reason: null },
        ])),
        document_permissions: { can_view: true, can_chat: true, can_upload: true, can_edit: true, can_delete: true, can_download: true },
        document_queries: { sort_fields: ['_ts'], places: true, facets: true },
        document_management: support,
    };
}

function defaultResponse(call) {
    const parts = call.path.split('/').map(decodeURIComponent);
    const groupId = parts[3];
    if (call.path.startsWith('/api/v2/workspaces/')) return json(context());
    if (call.path === '/api/group_documents/doc-1') return json(document());
    if (call.path.endsWith('/upload')) {
        const files = call.form.getAll('file');
        return json({ document_ids: files.map((_, index) => `upload-${index}`), processed_filenames: files.map((file) => file.name), errors: [] }, 202);
    }
    if (call.path.endsWith('/download')) {
        return new Response('ORIGIN source bytes', {
            headers: { 'Content-Type': 'application/octet-stream', 'Content-Disposition': 'attachment; filename="source.pdf"' },
        });
    }
    if (call.path.endsWith('/bulk-delete')) return json(receipt(call.body.document_ids, 'deleted'));
    if (call.path.endsWith('/bulk-tag')) return json(receipt(call.body.document_ids, 'success'));
    if (call.path.endsWith('/extract_metadata') || call.path.endsWith('/reprocess_extraction')) return json(receipt(call.body.document_ids, 'queued'), 202);
    if (call.path.endsWith('/tags') && call.method === 'POST') return json({ message: 'Created', tag: { name: call.body.tag_name, color: call.body.color ?? '#0078d4' } }, 201);
    if (call.path.includes('/tags/') && ['PATCH', 'DELETE'].includes(call.method)) {
        return json({
            message: 'Updated', documents_updated: 0, success: [], errors: [], vocabulary_retained: false,
            ...(call.method === 'PATCH' ? { tag: { name: call.body.new_name ?? parts.at(-1), color: call.body.color ?? '#0078d4' } } : {}),
        });
    }
    if (call.method === 'PATCH') return json({
        message: 'Saved', document_id: parts.at(-1), group_id: groupId,
        updated_fields: Object.keys(call.body), status: 'updated',
    });
    if (call.method === 'DELETE') return json({
        ...receipt([parts.at(-1)], 'deleted'), message: 'Deleted', deleted_mode: call.params.get('delete_mode'),
        deleted_document_ids: call.params.get('delete_mode') === 'all_versions' ? [parts.at(-1), 'older-revision'] : [parts.at(-1)],
        promoted_document_id: null,
    });
    throw new Error(`Unexpected request ${call.method} ${call.path}`);
}

globalThis.fetch = async (path, options = {}) => {
    const url = new URL(String(path), 'http://fixture.test');
    const call = {
        path: url.pathname, params: url.searchParams, method: options.method ?? 'GET',
        body: typeof options.body === 'string' ? JSON.parse(options.body) : null,
        form: options.body instanceof FormData ? options.body : null,
        signal: options.signal, credentials: options.credentials,
    };
    calls.push(call);
    return handler(call);
};

async function run(name, check) {
    calls = [];
    handler = defaultResponse;
    await check();
    checks += 1;
    console.log(`ok ${name}`);
}

try {
    await run('missing, malformed and future management handshakes never grant operations', async () => {
        for (const capability of [undefined, null, {}, { schema_version: 2, operations: DOCUMENT_OPERATIONS }, { schema_version: 1, operations: ['upload', 1] }]) {
            const unsupported = createGroupDocumentOperations(scope, capability);
            assert.equal(unsupported.supported.size, 0);
            await assert.rejects(unsupported.upload([new File(['text'], 'file.txt')]), /not available/);
        }
        assert.deepEqual([...advertisedDocumentOperations({ schema_version: 1, operations: ['future', 'download'] })], ['download']);
        assert.throws(() => createGroupDocumentOperations({ kind: 'personal', id: 'viewer' }, support), /explicit group/);
        assert.throws(() => createGroupDocumentOperations({ ...scope, id: '' }, support), /Invalid/);
        assert.equal(calls.length, 0);
    });
    await run('workspace and per-record grants intersect instead of inferring them from ownership', async () => {
        const owned = document();
        const unadvertised = document('unadvertised', { document_actions: undefined });
        const incoming = document('shared', { group_id: 'origin', shared_group_active_id: 'group-a', shared_approval_status: 'approved', document_actions: ['download'] });
        assert.equal(adapter.allows('edit_metadata', [owned]), true);
        assert.equal(adapter.allows('edit_metadata', [unadvertised]), false);
        assert.equal(adapter.allows('download', [owned, incoming]), true);
        for (const operation of ['edit_metadata', 'tag_documents', 'delete', 'extract_metadata', 'reprocess']) {
            assert.equal(adapter.allows(operation, [owned, incoming]), false);
        }
        const locked = createGroupDocumentOperations(scope, { schema_version: 1, operations: ['download'] });
        assert.equal(locked.allows('download', [owned]), true);
        assert.equal(locked.allows('delete', [owned]), false);
        const uploadDisabled = createGroupDocumentOperations(scope, { schema_version: 1, operations: ['download', 'delete', 'reprocess'] });
        assert.equal(uploadDisabled.allows('reprocess', [owned]), true);
        assert.equal(uploadDisabled.allows('upload'), false);
        assert.equal(uploadDisabled.allows('edit_metadata', [owned]), false);
    });
    await run('restricted cleanup eligibility does not become chat, download or ordinary mutation permission', async () => {
        const held = document('held', { content_screening: { state: 'pending_review', available: false, finding_count: 1 }, document_actions: ['delete'] });
        assert.equal(adapter.allows('delete', [held]), true);
        for (const operation of ['download', 'tag_documents', 'edit_metadata', 'extract_metadata', 'reprocess']) assert.equal(adapter.allows(operation, [held]), false);
        assert.match(documentSelectionReason(held, scope), /Held/);
        const pendingShare = document('pending', { group_id: 'origin', shared_group_active_id: 'group-a', shared_approval_status: 'not_approved' });
        for (const operation of ['download', 'delete', 'tag_documents', 'edit_metadata']) assert.equal(adapter.allows(operation, [pendingShare]), false);
    });
    await run('historical revisions cannot inherit current-only edit permissions', async () => {
        const historical = document('old', { is_current_version: false });
        for (const operation of ['edit_metadata', 'tag_documents', 'extract_metadata', 'reprocess']) assert.equal(adapter.allows(operation, [historical]), false);
        assert.equal(adapter.allows('download', [historical]), true);
        assert.equal(adapter.allows('delete', [historical]), true);
        assert.equal(adapter.allows('edit_metadata', [document('legacy', { is_current_version: undefined, document_actions: [] })]), false);
    });
    await run('generated pending artifacts are blocked even before any screening marker exists', async () => {
        for (const changes of [
            { generated_artifact_promotion_status: 'pending_approval', status: 'Pending approval' },
            { status: 'Pending approval' },
            { generated_artifact_promotion_status: 'approval_failed', status: 'Pending approval' },
        ]) {
            const pending = document('doc-1', changes);
            assert.ok(!Object.hasOwn(pending, 'content_screening'));
            assert.match(documentSelectionReason(pending, scope), /approval/);
            assert.notEqual(documentStatus(pending).state, 'ready');
            for (const operation of ['edit_metadata', 'tag_documents', 'delete', 'download', 'extract_metadata', 'reprocess']) assert.equal(adapter.allows(operation, [pending]), false);
            handler = (call) => call.path === '/api/group_documents/doc-1' ? json(pending) : defaultResponse(call);
            await assert.rejects(resolveContextHandoff({
                docScope: 'group', groupId: 'group-a', workspaceId: '', documentIds: ['doc-1'], tags: [],
            }, { viewerId: 'viewer' }), /approval/);
        }
        const reconciliation = document('doc-1', { generated_artifact_promotion_status: 'approval_failed' });
        assert.equal(documentStatus(reconciliation).label, 'Publication handoff failed');
        assert.match(documentSelectionReason(reconciliation, scope), /approval was recorded/);
    });
    await run('all operations bind the immutable path group, never an active preference or personal URL', async () => {
        const original = { kind: 'group', id: 'team & plus', name: 'Team' };
        const bound = createGroupDocumentOperations(original, support);
        original.id = 'different-active-group';
        const target = document('doc-1', { group_id: 'team & plus' });
        await bound.upload([new File(['first'], 'one.txt'), new File(['second'], 'two.txt')]);
        await bound.editMetadata(target, { title: 'Changed' });
        await bound.tagDocuments([target], 'add_tags', ['Finance']);
        await bound.extractMetadata([target]);
        await bound.reprocess([target], 'layout');
        await bound.download([target]);
        await bound.deleteDocuments([target], { deleteMode: 'current_only', fileSyncDeleteAction: 'delete_only' });
        await bound.createTag('new-tag', '#AbC');
        await bound.updateTag('legacy/path', { color: '#0078d4' });
        await bound.deleteTag('legacy/path');
        assert.deepEqual(calls[0].form.getAll('file').map((file) => file.name), ['one.txt', 'two.txt']);
        assert.ok(calls.every((call) => call.path.startsWith('/api/groups/team%20%26%20plus/documents/')));
        assert.ok(calls.every((call) => call.signal === undefined));
        assert.ok(calls.every((call) => !call.params.has('group_id') && !call.params.has('group_ids') && !call.body?.group_id));
        assert.ok(calls.some((call) => call.path.endsWith('/tags/legacy%2Fpath')));
        assert.deepEqual(calls[1].body, { title: 'Changed' });
        assert.deepEqual(calls[2].body, { document_ids: ['doc-1'], action: 'add_tags', tags: ['finance'] });
    });
    await run('mixed or wrong-group records are rejected before any mutation request', async () => {
        const shared = document('shared', { group_id: 'origin', shared_group_active_id: 'group-a', shared_approval_status: 'approved' });
        await assert.rejects(adapter.tagDocuments([document(), shared], 'add_tags', ['tag']), /not available/);
        await assert.rejects(adapter.deleteDocuments([document('foreign', { group_id: 'group-b' })], { deleteMode: 'all_versions' }), /not available/);
        await assert.rejects(adapter.editMetadata(document('missing', { document_actions: [] }), { title: 'Bad' }), /not available/);
        assert.equal(calls.length, 0);
    });
    await run('metadata diffs preserve omitted fields and reject identity/config edits', async () => {
        const target = document();
        const changed = changedDocumentMetadata(target, {
            title: 'Changed title', abstract: 'Original abstract', authors: 'First, Second',
            keywords: 'review', publication_date: '2024-01-02', document_classification: 'Internal',
        });
        assert.deepEqual(changed, { title: 'Changed title' });
        await adapter.editMetadata(target, changed);
        assert.deepEqual(calls[0].body, changed);
        for (const invalid of [{}, { group_id: 'elsewhere' }, { owner_id: 'elsewhere' }, { authors: [1] }, { title: false }]) {
            await assert.rejects(adapter.editMetadata(target, invalid), /changed document metadata/);
        }
        assert.equal(calls.length, 1);
    });
    await run('metadata acknowledges exact fields, document, group and updated/queued HTTP status', async () => {
        handler = () => json({ message: 'Saved for screening', document_id: 'doc-1', group_id: 'group-a', updated_fields: ['title'], status: 'queued' }, 202);
        const result = await adapter.editMetadata(document(), { title: 'New' });
        assert.equal(result, 'queued');
        const valid = { message: 'Saved', document_id: 'doc-1', group_id: 'group-a', updated_fields: ['title'], status: 'updated' };
        for (const [payload, status] of [
            [{ message: 'Maybe saved' }, 200], [{ ...valid, document_id: 'other' }, 200],
            [{ ...valid, group_id: 'other' }, 200], [{ ...valid, updated_fields: [] }, 200],
            [{ ...valid, updated_fields: ['title', 'authors'] }, 200], [{ ...valid, status: 'queued' }, 200],
            [valid, 207], [{ ...valid, errors: [{ document_id: 'doc-1', error: 'partial' }] }, 200],
        ]) {
            handler = () => json(payload, status);
            await assert.rejects(adapter.editMetadata(document(), { title: 'New' }), /did not confirm/);
        }
        handler = () => new Response('<html>Sign in</html>', { headers: { 'Content-Type': 'text/html' } });
        await assert.rejects(adapter.editMetadata(document(), { title: 'New' }), /did not confirm/);
    });
    await run('207 batch outcomes retain every failure instead of claiming all succeeded', async () => {
        const targets = [document(), document('doc-2')];
        const errors = [{ document_id: 'doc-2', error: 'propagation_failed', message: 'Search update failed.' }];
        handler = () => json(receipt(['doc-1'], 'success', errors), 207);
        const tagged = await adapter.tagDocuments(targets, 'add_tags', ['tag']);
        assert.deepEqual(tagged, { succeeded: ['doc-1'], errors });
        handler = () => json(receipt(['doc-1'], 'queued', errors), 207);
        const extracted = await adapter.extractMetadata(targets);
        const reprocessed = await adapter.reprocess(targets, 'read');
        assert.deepEqual(extracted, { succeeded: ['doc-1'], errors });
        assert.deepEqual(reprocessed, extracted);
        handler = () => json(receipt(['doc-1'], 'deleted', errors), 207);
        const deleted = await adapter.deleteDocuments(targets, { deleteMode: 'all_versions' });
        assert.deepEqual(deleted, extracted);
        assert.equal(calls.at(-1).path, '/api/groups/group-a/documents/bulk-delete');
    });
    await run('missing, conflicting, foreign or contradictory successful receipts are unconfirmed', async () => {
        const incomplete = inspectDocumentBatch(['doc-1', 'doc-2'], receipt(['doc-1'], 'queued'), 'queued', true);
        assert.equal(incomplete.errors[0].document_id, 'doc-2');
        assert.equal(incomplete.errors[0].error, 'outcome_unconfirmed');
        for (const payload of [
            { message: 'Deleted' }, { deleted: [], errors: [] },
            { ...receipt(['doc-1'], 'deleted'), deleted_count: 2 },
            receipt(['different'], 'deleted'), receipt(['doc-1'], 'deleted', [{ document_id: 'doc-1', error: 'partial' }]),
        ]) {
            handler = () => json(payload);
            await assert.rejects(adapter.deleteDocuments([document()], { deleteMode: 'all_versions' }), /receipt|outcomes|counts|confirm/);
        }
        handler = () => json(receipt(['doc-1', 'doc-2'], 'queued'), 207);
        await assert.rejects(adapter.extractMetadata([document(), document('doc-2')]), /receipt/);
        handler = () => json({ queued: ['doc-1'], errors: [] }, 202);
        await assert.rejects(adapter.reprocess([document()], 'read'), /receipt/);
    });
    await run('deletion carries only explicit revision intent and actual guard choices', async () => {
        handler = () => json({
            error: 'synced_document_delete_requires_action', message: 'Choose a source action.', needs_confirmation: true,
            file_sync: { source_id: 'source', source_name: 'Source', relative_path: 'file.pdf' },
            options: [{ action: 'delete_only', label: 'Delete only' }, { action: 'ignore_remote', label: 'Ignore remote' }],
        }, 409);
        const blocked = await adapter.deleteDocuments([document()], { deleteMode: 'current_only' });
        assert.equal(blocked.succeeded.length, 0);
        assert.equal(blocked.errors[0].document_id, 'doc-1');
        assert.equal(blocked.errors[0].needs_confirmation, true);
        handler = defaultResponse;
        await adapter.deleteDocuments([document()], {
            deleteMode: 'current_only', fileSyncDeleteAction: 'ignore_remote', conversationLinkedDeleteConfirmed: true,
        });
        assert.deepEqual(Object.fromEntries(calls.at(-1).params), {
            delete_mode: 'current_only', file_sync_delete_action: 'ignore_remote', conversation_linked_delete_confirmed: 'true',
        });
        const count = calls.length;
        await assert.rejects(adapter.deleteDocuments([document()], { deleteMode: 'all_versions', fileSyncDeleteAction: 'keep_source' }), /explicit revision/);
        assert.equal(calls.length, count);
    });
    await run('uploads preserve accepted filenames, queued IDs and all rejected-file messages', async () => {
        handler = () => json({ document_ids: ['accepted'], processed_filenames: ['accepted.txt'], errors: ['rejected.exe: unsupported type'] }, 207);
        const result = await adapter.upload([new File(['ok'], 'accepted.txt'), new File(['no'], 'rejected.exe')]);
        assert.deepEqual(result, { document_ids: ['accepted'], processed_filenames: ['accepted.txt'], errors: ['rejected.exe: unsupported type'] });
        handler = () => json({ document_ids: ['accepted'], processed_filenames: ['accepted.txt'], errors: [] }, 207);
        await assert.rejects(adapter.upload([new File(['ok'], 'accepted.txt')]), /confirm/);
    });
    await run('download errors, redirects and partial JSON never become Blob files', async () => {
        const incoming = document('shared', { group_id: 'origin', shared_group_active_id: 'group-a', shared_approval_status: 'approved', document_actions: ['download'] });
        const blob = await adapter.download([incoming]);
        assert.equal(await blob.text(), 'ORIGIN source bytes');
        assert.equal(calls[0].path, '/api/groups/group-a/documents/shared/download');
        await adapter.download([document(), incoming]);
        assert.deepEqual(calls.at(-1).body, { document_ids: ['doc-1', 'shared'] });
        for (const failure of [
            () => json({ error: 'Denied' }, 403),
            () => json({ errors: [{ document_id: 'shared', error: 'denied' }] }, 207),
            () => new Response('<html>Sign in</html>', { headers: { 'Content-Type': 'text/html' } }),
            () => { const response = defaultResponse({ path: '/download' }); Object.defineProperty(response, 'redirected', { value: true }); return response; },
        ]) {
            handler = failure;
            await assert.rejects(adapter.download([incoming]), /No file was saved/);
        }
    });
    await run('tag creation requires a real canonical acknowledgement and safe colour', async () => {
        const created = await adapter.createTag(' New-Tag ', '#AbC');
        assert.equal(created.tag.name, 'new-tag');
        assert.equal(created.tag.color, '#aabbcc');
        assert.equal(normalizeTagColor('abc'), '#aabbcc');
        for (const payload of [
            { message: 'Created' }, { tag: {} }, { tag: { name: '', color: '#fff' } },
            { tag: { name: 'new-tag', color: 'url(https://invalid.test)' } },
            { tag: { name: 'different', color: '#fff' } },
        ]) {
            handler = () => json(payload, 201);
            await assert.rejects(adapter.createTag('new-tag', '#abc'));
        }
        const before = calls.length;
        await assert.rejects(async () => adapter.createTag('', '#abc'), /tag name/);
        await assert.rejects(async () => adapter.createTag('valid', 'javascript:bad'), /hex colour/);
        assert.equal(calls.length, before);
    });
    await run('partial vocabulary propagation retains old names and explicit per-document failures', async () => {
        const partial = {
            message: 'Partial rename', documents_updated: 1, success: [{ document_id: 'doc-1', tags: ['new'] }],
            errors: [{ document_id: 'doc-2', error: 'index_failed', message: 'Index propagation failed.' }],
            vocabulary_retained: true, tag: { name: 'new', color: '#0078d4' },
        };
        handler = () => json(partial, 207);
        const renamed = await adapter.updateTag('legacy/path', { new_name: 'new' });
        assert.equal(renamed.vocabularyRetained, true);
        assert.equal(renamed.errors[0].document_id, 'doc-2');
        assert.equal(calls[0].path, '/api/groups/group-a/documents/tags/legacy%2Fpath');
        const removed = await adapter.deleteTag('legacy/path');
        assert.equal(removed.vocabularyRetained, true);
        handler = () => json({ message: 'Maybe removed' });
        await assert.rejects(adapter.deleteTag('legacy/path'), /confirm/);
    });
    await run('tag-only vocabulary CAS errors preserve successful documents and exact workspace identity', async () => {
        const failure = { stage: 'vocabulary', group_id: 'group-a', error: 'concurrent_update', message: 'Refresh the tag definitions before retrying.' };
        const result = {
            message: 'Definition update conflicted', documents_updated: 2,
            success: [{ document_id: 'doc-1', tags: ['new'] }, { document_id: 'doc-2', tags: ['new'] }],
            errors: [failure], vocabulary_retained: true, tag: { name: 'new', color: '#0078d4' },
        };
        handler = () => json(result, 207);
        const outcome = await adapter.updateTag('old', { new_name: 'new' });
        assert.deepEqual(outcome.success, result.success);
        assert.deepEqual(outcome.errors, [failure]);
        assert.equal(outcome.vocabularyRetained, true);
        assert.equal(calls.length, 1, 'A CAS conflict must not automatically replay successful writes.');
        for (const error of [
            { ...failure, group_id: 'group-b' }, { ...failure, stage: 'unknown' },
            { stage: 'vocabulary', error: 'concurrent_update' },
        ]) {
            handler = () => json({ ...result, errors: [error] }, 207);
            await assert.rejects(adapter.updateTag('old', { new_name: 'new' }), /workspace|invalid/);
        }
        assert.throws(() => inspectDocumentBatch(['doc-1'], {
            ...receipt([], 'deleted'), errors: [failure], error_count: 1,
        }, 'deleted', true), /invalid operation result/);
    });
    await run('personal legacy endpoints, tag case and keep_source confirmation remain independent', async () => {
        const target = document('personal', { group_id: undefined, user_id: 'viewer' });
        await PERSONAL_DOCUMENT_OPERATIONS.tagDocuments([target], 'add_tags', ['Finance']);
        assert.equal(calls[0].path, '/api/documents/bulk-tag');
        assert.deepEqual(calls[0].body.tags, ['Finance']);
        await PERSONAL_DOCUMENT_OPERATIONS.deleteDocuments([target], { deleteMode: 'current_only', fileSyncDeleteAction: 'keep_source' });
        assert.equal(calls.at(-1).path, '/api/documents/bulk-delete');
        assert.equal(calls.at(-1).body.file_sync_delete_action, 'keep_source');
        handler = () => json({ message: 'Saved' });
        const status = await PERSONAL_DOCUMENT_OPERATIONS.editMetadata(target, { title: 'Changed' });
        assert.equal(status, 'updated');
        assert.equal(calls.at(-1).path, '/api/documents/personal');
    });
    await run('status-bearing helpers preserve body-only contracts for existing API and upload callers', async () => {
        handler = () => json({ message: 'Accepted' }, 202);
        const ordinary = await api.post('/fixture', {});
        const withStatus = await requestWithStatus('/fixture', { method: 'POST', body: {} });
        const form = new FormData();
        form.append('file', new File(['file'], 'file.txt'));
        const upload = await uploadFile('/fixture', form);
        const uploadStatus = await uploadFileWithStatus('/fixture', form);
        assert.deepEqual(ordinary, { message: 'Accepted' });
        assert.deepEqual(withStatus, { data: ordinary, status: 202 });
        assert.deepEqual(upload, ordinary);
        assert.deepEqual(uploadStatus, withStatus);
    });
    console.log(`${checks} scoped document operation checks passed.`);
} finally {
    globalThis.fetch = originalFetch;
}
