// test_v2_chat_context_request.ts
//
// Runtime test for how the V2 composer's context chips become a chat request.
// Version: 0.261.096
// Implemented in: 0.261.089
// Independent context selection implemented in: 0.261.094
// Shared editor implemented in: 0.261.096
//
// These are the decisions that turn "the user picked a document" into fields the server acts
// on, and each one fails as a wrong answer rather than an error:
//
//   - `_build_document_content_filter` defaults to `intersection`, so a picked document AND a
//     picked tag must both match. A chip row holding one of each would return nothing at all
//     unless the composer asks for `union`.
//   - `hybrid_search` off while documents are named collects a selection, sends it, and has
//     the server ignore it.
//   - A group document whose group id is not in `active_group_ids` is filtered out server-side
//     by `_get_authorized_chat_scope_context`. The document is simply absent from the answer,
//     with nothing to say why.
//   - `build_tags_filter` joins tags with `and`, so sending one twice narrows the search.
//
// Run by test_v2_chat_context_picker.py, which bundles this with the esbuild Vite already
// brings in and executes it under node, skipping when the front-end toolchain is absent.
// Bundling rather than running directly is what resolves the extensionless imports between
// chatContext, chatContextTokens and documentExplorer.

import assert from 'node:assert/strict';
import {
    PERSONAL_SCOPE,
    addContextItem,
    contextDocumentIds,
    contextFilterMode,
    contextScopes,
    contextTags,
    describeContextGroup,
    documentContextItem,
    groupContextItems,
    groupScope,
    publicScope,
    removeContextItem,
    scopeContextItem,
    tagContextItem,
    type ContextItem,
} from '../application/v2_ui/src/lib/chatContext';
import { reconcileContextItems } from '../application/v2_ui/src/lib/chatContextTokens';
import { resolveDocumentScope } from '../application/v2_ui/src/lib/documentScope';
import {
    composerDraftContextItems,
    composerDraftHasContent,
    composerDraftHasPendingUploads,
    composerDraftReferences,
    createComposerDraft,
    interruptComposerDraftUploads,
} from '../application/v2_ui/src/lib/composerDraft';
import {
    chatUploadDocumentStatus,
    chatUploadTargets,
    chatUploadValidationError,
    conversationAttachmentReferences,
    normalizeChatUpload,
    pollChatUpload,
} from '../application/v2_ui/src/lib/chatUploads';
import { ApiError } from '../application/v2_ui/src/lib/apiClient';
import { uploadDocument } from '../application/v2_ui/src/lib/endpoints';

const MARKETING = groupScope({ id: 'grp-1', name: 'Marketing' });
const LEGAL = groupScope({ id: 'grp-2', name: 'Legal' });
const HANDBOOK = publicScope({ id: 'pub-1', name: 'Handbook' });

const checks: Array<[string, () => void | Promise<void>]> = [];
function check(name: string, run: () => void | Promise<void>) {
    checks.push([name, run]);
}

function doc(id: string, title: string, scope = PERSONAL_SCOPE, existing: never[] | ReturnType<typeof documentContextItem>[] = []) {
    return documentContextItem({ id, title, file_name: `${title}.pdf` }, scope, existing);
}

/* -------------------------------------------------------------------------- */
/* Identity                                                                    */
/* -------------------------------------------------------------------------- */

check('a document is identified by its id, not its title', () => {
    // Two files can share a title. Keying on the label would silently collapse them into one.
    const first = doc('a', 'Contract');
    const second = doc('b', 'Contract', PERSONAL_SCOPE, [first]);

    assert.notEqual(first.key, second.key);
    assert.notEqual(first.token, second.token);

    const items = addContextItem(addContextItem([], first), second);
    assert.deepEqual(contextDocumentIds(items), ['a', 'b']);
});

check('the same document is not added twice', () => {
    const item = doc('a', 'Contract');
    const items = addContextItem(addContextItem([], item), item);
    assert.equal(items.length, 1);
});

check('selection and mention merge without replacing identity, token, or metadata', () => {
    const selected = documentContextItem(
        { id: 'a', title: 'Contract', file_name: 'Contract.pdf' },
        PERSONAL_SCOPE,
        [],
        'handoff',
    );
    const mentioned = documentContextItem(
        { id: 'a', title: 'Contract' },
        PERSONAL_SCOPE,
        [selected],
        'user',
        'mention',
    );
    const merged = addContextItem([selected], mentioned);

    assert.equal(merged.length, 1);
    assert.deepEqual(merged[0], { ...selected, attachment: 'both' });
    assert.equal(merged[0].meta, selected.meta);
    assert.equal(selected.attachment, 'selection');
    assert.deepEqual(contextDocumentIds(merged), ['a']);
    assert.deepEqual(reconcileContextItems('Summarize this', merged), [selected]);
});

check('a later independent selection preserves an existing mention', () => {
    const selected = doc('a', 'Contract');
    const mentioned: ContextItem = { ...selected, attachment: 'mention' };
    const merged = addContextItem([mentioned], selected);

    assert.equal(merged[0].attachment, 'both');
    assert.deepEqual(contextDocumentIds(reconcileContextItems('', merged)), ['a']);
    assert.equal(addContextItem(merged, mentioned)[0], merged[0]);
    assert.equal(addContextItem(merged, selected)[0], merged[0]);
});

check('a delayed selection cannot reserve another item\'s token', () => {
    const first = doc('a', 'Contract');
    const second = doc('b', 'Contract');
    const merged = addContextItem([first], second);
    assert.notEqual(merged[0].token, merged[1].token);
    assert.deepEqual(contextDocumentIds(merged), ['a', 'b']);
});

check('the same tag in two workspaces is two chips but one filter', () => {
    // Each chip widens the scope to its own workspace, but `build_tags_filter` joins names
    // with `and`, so sending "urgent" twice would require a document to carry it twice.
    const personal = tagContextItem('urgent', PERSONAL_SCOPE);
    const marketing = tagContextItem('urgent', MARKETING, [personal]);
    const items = [personal, marketing];

    assert.equal(items.length, 2);
    assert.deepEqual(contextTags(items), ['urgent']);
    assert.deepEqual(contextScopes(items).groupIds, ['grp-1']);
});

check('tag de-duplication ignores case', () => {
    const items = [tagContextItem('Urgent', PERSONAL_SCOPE), tagContextItem('urgent', MARKETING)];
    assert.deepEqual(contextTags(items), ['Urgent']);
});

check('removing a chip removes only that one', () => {
    const first = doc('a', 'A');
    const second = doc('b', 'B', PERSONAL_SCOPE, [first]);
    assert.deepEqual(
        contextDocumentIds(removeContextItem([first, second], first.key)),
        ['b'],
    );
});

/* -------------------------------------------------------------------------- */
/* Filter mode                                                                 */
/* -------------------------------------------------------------------------- */

check('documents and tags together are sent as additive', () => {
    // Without this the server ANDs them and a document that does not carry the tag is
    // excluded -- so the row shows two chips and the search returns nothing.
    const items = [doc('a', 'Contract'), tagContextItem('urgent', PERSONAL_SCOPE)];
    assert.equal(contextFilterMode(items), 'union');
});

check('one kind alone sends no mode at all', () => {
    // With a single kind the mode has no effect, and an unnecessary field is one more thing
    // to account for later.
    assert.equal(contextFilterMode([doc('a', 'A')]), undefined);
    assert.equal(contextFilterMode([tagContextItem('urgent', PERSONAL_SCOPE)]), undefined);
    assert.equal(contextFilterMode([]), undefined);
});

check('pill-only and inline attachments carry identical request context', () => {
    const selected = [
        doc('a', 'Contract', MARKETING),
        tagContextItem('urgent', PERSONAL_SCOPE),
        scopeContextItem(HANDBOOK),
    ];
    const mentioned: ContextItem[] = selected.map((item) => ({ ...item, attachment: 'mention' }));
    const combined: ContextItem[] = selected.map((item) => ({ ...item, attachment: 'both' }));
    const requestContext = (items: ContextItem[]) => ({
        ids: contextDocumentIds(items),
        tags: contextTags(items),
        scopes: contextScopes(items),
        filterMode: contextFilterMode(items),
    });

    assert.deepEqual(requestContext(mentioned), requestContext(selected));
    assert.deepEqual(requestContext(combined), requestContext(selected));
    assert.deepEqual(requestContext(reconcileContextItems('', combined)), requestContext(selected));
});

/* -------------------------------------------------------------------------- */
/* Scope                                                                       */
/* -------------------------------------------------------------------------- */

check('no chips leaves the deployment scope untouched', () => {
    assert.deepEqual(resolveDocumentScope(undefined), {
        doc_scope: 'personal',
        active_group_ids: [],
        active_group_id: null,
        active_public_workspace_ids: [],
        active_public_workspace_id: null,
    });
});

check('a group chip makes its group reachable', () => {
    // The whole point: without the id in active_group_ids the server filters the document out
    // and the answer is missing it with no explanation.
    const items = [doc('a', 'Brief', MARKETING)];
    const scope = resolveDocumentScope({
        contextGroupIds: contextScopes(items).groupIds,
    });

    assert.equal(scope.doc_scope, 'all');
    assert.deepEqual(scope.active_group_ids, ['grp-1']);
    assert.equal(scope.active_group_id, 'grp-1');
});

check('chips from several workspaces all travel', () => {
    const items = [
        doc('a', 'Brief', MARKETING),
        doc('b', 'Policy', LEGAL),
        doc('c', 'Handbook', HANDBOOK),
        doc('d', 'Notes'),
    ];
    const workspaces = contextScopes(items);
    const scope = resolveDocumentScope({
        contextGroupIds: workspaces.groupIds,
        contextPublicWorkspaceIds: workspaces.publicWorkspaceIds,
    });

    assert.equal(workspaces.includesPersonal, true);
    assert.deepEqual(scope.active_group_ids, ['grp-1', 'grp-2']);
    assert.deepEqual(scope.active_public_workspace_ids, ['pub-1']);
    assert.equal(scope.doc_scope, 'all');
});

check('the active workspace is kept alongside the chips', () => {
    // Someone working inside a group who pins a personal document must not lose the group.
    const scope = resolveDocumentScope({
        activeGroupId: 'grp-active',
        contextGroupIds: ['grp-1'],
    });
    assert.deepEqual(scope.active_group_ids, ['grp-active', 'grp-1']);
});

check('a workspace named twice is sent once', () => {
    const scope = resolveDocumentScope({
        activeGroupId: 'grp-1',
        contextGroupIds: ['grp-1', 'grp-1'],
    });
    assert.deepEqual(scope.active_group_ids, ['grp-1']);
});

check('a whole-workspace chip widens the scope without pinning documents', () => {
    // Enumerating the workspace here would freeze it as it was when the chip was added.
    const items = [scopeContextItem(MARKETING)];
    assert.deepEqual(contextDocumentIds(items), []);
    assert.deepEqual(contextScopes(items).groupIds, ['grp-1']);
});

/* -------------------------------------------------------------------------- */
/* Presentation                                                                */
/* -------------------------------------------------------------------------- */

check('chips group by workspace, personal first', () => {
    const items = [
        doc('a', 'Brief', HANDBOOK),
        doc('b', 'Policy', MARKETING),
        doc('c', 'Notes'),
    ];
    assert.deepEqual(
        groupContextItems(items).map((group) => group.scope.name),
        ['My workspace', 'Marketing', 'Handbook'],
    );
});

check('a collapsed group counts each kind', () => {
    const items = [
        doc('a', 'A', MARKETING),
        doc('b', 'B', MARKETING),
        tagContextItem('urgent', MARKETING),
    ];
    assert.equal(describeContextGroup(items), '2 documents and 1 tag');
    assert.equal(describeContextGroup([items[2]]), '1 tag');
});

check('a document with no extracted title falls back to its file name', () => {
    const item = documentContextItem(
        { id: 'a', file_name: 'MSA_v2_FINAL(3).docx' },
        PERSONAL_SCOPE,
    );
    assert.equal(item.label, 'MSA_v2_FINAL(3).docx');
    assert.equal(item.token, '#[MSA_v2_FINAL(3).docx]');
});

check('only selected context and ready real uploads become references', () => {
    const draft = createComposerDraft();
    draft.contextItems = [doc('existing', 'Brief'), tagContextItem('urgent', MARKETING)];
    draft.uploads = [
        { id: 'duplicate', fileName: 'brief.pdf', state: 'ready', reference: {
            kind: 'document', id: 'existing', scope: { kind: 'personal', id: null },
        } },
        { id: 'processing', fileName: 'queued.pdf', state: 'processing', reference: {
            kind: 'document', id: 'queued', scope: { kind: 'personal', id: null },
        } },
        { id: 'failed', fileName: 'failed.pdf', state: 'failed' },
        { id: 'legacy', fileName: 'notes.txt', state: 'ready', reference: {
            kind: 'chat_attachment', id: 'chat-file-message', scope: { kind: 'chat', id: 'conversation-a' },
        } },
    ];
    assert.equal(composerDraftHasPendingUploads(draft), true);
    assert.deepEqual(composerDraftReferences(draft).map((reference) => reference.id),
        ['existing', 'urgent', 'chat-file-message']);
    assert.deepEqual(contextDocumentIds(composerDraftContextItems(draft)), ['existing']);
    assert.equal(composerDraftHasContent(draft), true);
    const pendingOnly = { ...createComposerDraft(), uploads: [draft.uploads[1]] };
    assert.equal(composerDraftHasContent(pendingOnly), false);
    const detached = composerDraftReferences(draft);
    detached[2].scope.id = 'different-conversation';
    assert.equal(draft.uploads[3].reference?.scope.id, 'conversation-a');
});

check('unmount interrupts only owned pending uploads without stranding or losing draft data', () => {
    const draft = createComposerDraft();
    draft.text = 'Keep this answer.';
    draft.promptValues = { topic: 'contracts', intentionally_cleared: '' };
    draft.uploads = [
        { id: 'transfer', fileName: 'notes.txt', state: 'uploading', conversationId: 'conversation-a' },
        { id: 'processing', fileName: 'report.pdf', state: 'processing', progress: 35, reference: {
            kind: 'document', id: 'workspace-document', scope: { kind: 'personal', id: null },
        } },
        { id: 'ready', fileName: 'ready.txt', state: 'ready', reference: {
            kind: 'chat_attachment', id: 'file-message', scope: { kind: 'chat', id: 'conversation-a' },
        } },
    ];
    const interrupted = interruptComposerDraftUploads(draft, new Set(['transfer', 'processing', 'ready']));
    assert.equal(composerDraftHasPendingUploads(interrupted), false);
    assert.equal(interrupted.uploads[0].state, 'failed');
    assert.equal(interrupted.uploads[0].interrupted, 'uploading');
    assert.match(interrupted.uploads[0].error!, /Retry/);
    assert.equal(interrupted.uploads[1].state, 'failed');
    assert.equal(interrupted.uploads[1].interrupted, 'processing');
    assert.equal(interrupted.uploads[1].reference, draft.uploads[1].reference);
    assert.equal(interrupted.uploads[1].progress, 35);
    assert.equal(interrupted.uploads[2], draft.uploads[2]);
    assert.equal(interrupted.promptValues, draft.promptValues);
    assert.equal(interrupted.text, draft.text);
    assert.equal(draft.uploads[0].state, 'uploading');
    assert.equal(draft.uploads[1].state, 'processing');
    assert.deepEqual(composerDraftReferences(interrupted).map((reference) => reference.id), ['file-message']);
    assert.equal(interruptComposerDraftUploads(interrupted, new Set(['transfer'])), interrupted);
    assert.equal(interruptComposerDraftUploads(draft, new Set(['another-editor-upload'])), draft);
});

check('workspace uploads use their workspace identity and real processing status', () => {
    const normalized = normalizeChatUpload({
        conversation_id: 'chat-a',
        file_message_id: 'chat-a_file_1',
        workspace_document_id: 'workspace-id',
        workspace_scope: 'group',
        workspace_document: { document_id: 'workspace-id', file_name: 'report.pdf', group_id: 'grp-1',
            status: 'Queued for processing', percentage_complete: 0 },
        group_upload_target: { id: 'grp-1', name: 'Marketing', can_upload: true },
    }, 'report.pdf');
    assert.equal(normalized.reference?.id, 'workspace-id');
    assert.equal(normalized.reference?.kind, 'document');
    assert.equal(normalized.reference?.scope.id, 'grp-1');
    assert.equal(normalized.state, 'processing');
    assert.equal(normalized.progress, 0);
    assert.equal(chatUploadDocumentStatus({ status: 'Queued for processing' }).state, 'processing');
    assert.equal(chatUploadDocumentStatus({ status: 'completed' }).state, 'ready');
    assert.equal(chatUploadDocumentStatus({ percentage_complete: 100 }).state, 'ready');
    assert.equal(chatUploadDocumentStatus({ status: 'Error processing', percentage_complete: 100 }).state, 'failed');
    assert.equal(chatUploadDocumentStatus({ percentage_complete: NaN }).state, 'processing');
});

check('legacy uploads require actual conversation and file-message identities', () => {
    const normalized = normalizeChatUpload({
        conversation_id: 'chat-a', file_message_id: 'chat-a_file_1',
    }, 'notes.txt');
    assert.equal(normalized.state, 'ready');
    assert.deepEqual(normalized.reference, {
        kind: 'chat_attachment', id: 'chat-a_file_1', label: 'notes.txt',
        scope: { kind: 'chat', id: 'chat-a', name: 'This conversation' },
    });
    assert.throws(() => normalizeChatUpload({ conversation_id: 'chat-a' }, 'notes.txt'), /identity/);
    assert.throws(() => normalizeChatUpload({ file_message_id: 'file-id' }, 'notes.txt'), /identity/);
    assert.throws(() => normalizeChatUpload({ workspace_document_id: 'real-id' }, 'notes.txt'), /destination/);
    assert.throws(() => normalizeChatUpload({
        workspace_document_id: 'real-id', workspace_scope: 'group',
    }, 'notes.txt'), /group workspace/);
});

check('upload validation preserves chat format, account and size gates', () => {
    const text = new File(['source'], 'notes.txt');
    assert.equal(chatUploadValidationError(text, true, 10), null);
    assert.match(chatUploadValidationError(text, false, 10)!, /account/);
    assert.match(chatUploadValidationError(new File(['x'], 'code.exe'), true, 10)!, /file type/);
    assert.match(chatUploadValidationError(new File(['x'.repeat(1025)], 'brief.pdf'), true, 0.0009)!, /limit/);
    assert.equal(chatUploadValidationError(new File(['data'], 'REPORT.XLSX'), true, 10), null);
});

check('group target errors retain eligible and ineligible destinations', () => {
    const targets = [
        { id: 'a', name: 'Marketing', can_upload: true },
        { id: 'b', name: 'Legal', can_upload: false, reason: 'Your role cannot upload' },
    ];
    assert.deepEqual(chatUploadTargets(new ApiError('Choose a group', 400, {
        requires_group_upload_target: true, group_upload_targets: targets,
    })), targets);
    assert.equal(chatUploadTargets(new ApiError('Forbidden', 403, { error: 'Forbidden' })), null);
});

check('conversation attachment lookup never picks another conversation or workspace surrogate', () => {
    const references = conversationAttachmentReferences([
        { id: 'a_file_1', conversation_id: 'a', role: 'file', filename: 'notes.txt', content: 'source' },
        { id: 'b_file_1', conversation_id: 'b', role: 'file', filename: 'other.txt', content: 'private' },
        { id: 'a_file_2', conversation_id: 'a', role: 'file', filename: 'workspace.pdf',
            workspace_document_id: 'workspace-id', content: '' },
        { id: 'assistant-1', conversation_id: 'a', role: 'assistant', content: 'Use fake.pdf' },
    ], 'a');
    assert.deepEqual(references.map((reference) => reference.id), ['a_file_1']);
    assert.equal(references[0].scope.id, 'a');
});

check('multipart upload passes captured group destination and cancellation signal', async () => {
    const originalFetch = globalThis.fetch;
    const controller = new AbortController();
    globalThis.fetch = async (url, init) => {
        assert.equal(String(url), '/upload');
        assert.equal(init?.signal, controller.signal);
        const form = init!.body as FormData;
        assert.equal(form.get('conversation_id'), 'conversation-a');
        assert.equal(form.get('group_upload_target_id'), 'grp-1');
        assert.deepEqual(form.getAll('upload_scope_group_ids'), ['grp-1', 'grp-2']);
        return new Response(JSON.stringify({ conversation_id: 'conversation-a', file_message_id: 'file-message' }), {
            headers: { 'Content-Type': 'application/json' },
        });
    };
    try {
        const uploaded = await uploadDocument(new File(['source'], 'notes.txt'), 'conversation-a',
            controller.signal, { groupUploadTargetId: 'grp-1', uploadScopeGroupIds: ['grp-1', 'grp-2'] });
        assert.equal(uploaded.file_message_id, 'file-message');
    } finally {
        globalThis.fetch = originalFetch;
    }
});

check('processing polls the authorized document endpoint until ready and honors cancellation', async () => {
    const originalFetch = globalThis.fetch;
    let calls = 0;
    globalThis.fetch = async (url) => {
        assert.equal(String(url), '/api/group_documents/workspace-id');
        calls += 1;
        return new Response(JSON.stringify({ status: calls === 1 ? 'Processing' : 'Complete',
            percentage_complete: calls === 1 ? 20 : 100 }), { headers: { 'Content-Type': 'application/json' } });
    };
    const reference = { kind: 'document' as const, id: 'workspace-id',
        scope: { kind: 'group' as const, id: 'grp-1' } };
    try {
        const states: string[] = [];
        await pollChatUpload(reference, new AbortController().signal, (status) => states.push(status.state));
        assert.deepEqual(states, ['processing', 'ready']);
        calls = 0;
        const controller = new AbortController();
        await assert.rejects(pollChatUpload(reference, controller.signal, () => controller.abort()),
            (error: Error) => error.name === 'AbortError');
        assert.equal(calls, 1);
    } finally {
        globalThis.fetch = originalFetch;
    }
});

/* -------------------------------------------------------------------------- */

let failed = 0;
for (const [name, run] of checks) {
    try {
        await run();
        console.log(`  ok  ${name}`);
    } catch (error) {
        failed += 1;
        console.error(`  FAIL  ${name}`);
        console.error(`        ${(error as Error).message}`);
    }
}

console.log(`\n${checks.length - failed}/${checks.length} checks passed`);
process.exit(failed === 0 ? 0 : 1);
