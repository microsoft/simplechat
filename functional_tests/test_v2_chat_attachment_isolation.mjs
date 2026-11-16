// test_v2_chat_attachment_isolation.mjs
// Version: 0.261.414
// Implemented in: 0.261.414
// Executes real attachment ownership, recovery, adoption, and source-name helpers without I/O.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const { ComposerAttachmentDrafts, composerAttachmentOwner } =
    await import('../application/v2_ui/src/lib/composerAttachmentDrafts.ts');
const { createComposerDraft } = await import('../application/v2_ui/src/lib/composerDraft.ts');
const { conversationSourceDocuments, DOCUMENT_DETAILS_UNAVAILABLE, restoreDocumentSources } =
    await import('../application/v2_ui/src/lib/documentSourceSelection.ts');

const cache = new ComposerAttachmentDrafts();
const ownerA = composerAttachmentOwner('reader', 'chat-a', 'personal', 1);
const ownerB = composerAttachmentOwner('reader', 'chat-b', 'personal', 2);
const documentId = '11111111-2222-4333-8444-555555555555';
const selection = {
    version: 1, mode: 'selected',
    sources: [{ kind: 'document', id: documentId, scope: { kind: 'personal' } }],
};
const document = {
    document_id: documentId, title: documentId, file_name: 'original.png', scope: { type: 'personal' },
};
const items = restoreDocumentSources(selection, [], [document]);
assert.equal(items[0].label, 'original.png');
assert.equal(items[0].meta.fileName, 'original.png');
assert.equal(items[0].id, documentId);
const sentDraft = { ...createComposerDraft(), text: 'Read my file', contextItems: items };

cache.activate(ownerA);
cache.initialize(ownerA, items, false);
const readyRevision = cache.read(ownerA).revision;
const currentCanSubmit = cache.canSubmit(ownerA, ownerA, readyRevision);
assert.equal(currentCanSubmit, true);
cache.activate(ownerB);
cache.initialize(ownerB, [], false);
const staleCanSubmit = cache.canSubmit(ownerA, ownerB, readyRevision);
assert.equal(staleCanSubmit, false, 'a stale render cannot send A attachments into B');
assert.deepEqual(cache.read(ownerB).contextItems, []);
assert.equal(cache.read(ownerA).contextItems[0].label, 'original.png');
cache.initialize(ownerB, items, true);
assert.deepEqual(cache.read(ownerB).contextItems, [], 'an explicit empty selection is not history to refill');
assert.equal(cache.read(ownerB).documentSearch, false);

cache.update(ownerA, (current) => ({ ...current, contextItems: [], initialized: true }));
const clearedRevision = cache.read(ownerA).revision;
const recoveredOffscreen = cache.recover(ownerA, clearedRevision, sentDraft);
assert.equal(recoveredOffscreen, true);
assert.equal(cache.read(ownerA).contextItems[0].id, documentId);
assert.deepEqual(cache.read(ownerB).contextItems, [], 'failed-send recovery cannot populate the visible other chat');

const returnedA = composerAttachmentOwner('reader', 'chat-a', 'personal', 3);
cache.activate(returnedA);
const revisitedCanSubmit = cache.canSubmit(ownerA, returnedA, cache.read(returnedA).revision);
assert.equal(revisitedCanSubmit, false, 'a handler from the first A visit cannot submit after A-to-B-to-A');
const staleUpdate = cache.update(ownerA, (current) => ({ ...current, contextItems: [], documentSearch: true }));
assert.equal(staleUpdate, false, 'A-to-B-to-A invalidates the first A callback');
assert.equal(cache.read(returnedA).contextItems[0].id, documentId);
cache.update(returnedA, (current) => ({ ...current, contextItems: [] }));
const failedRevision = cache.read(returnedA).revision;
cache.update(returnedA, (current) => ({ ...current, documentSearch: true }));
const staleSelectionCanSubmit = cache.canSubmit(returnedA, returnedA, failedRevision);
assert.equal(staleSelectionCanSubmit, false, 'an edited selection cannot be sent by its previous render');
const overwrittenEdit = cache.recover(ownerA, failedRevision, sentDraft);
assert.equal(overwrittenEdit, false, 'recovery cannot undo an edit made after sending');
assert.deepEqual(cache.read(returnedA).contextItems, []);
assert.equal(cache.read(returnedA).documentSearch, true);

const firstNew = composerAttachmentOwner('reader', null, 'personal', 4);
const secondNew = composerAttachmentOwner('reader', null, 'personal', 5);
cache.activate(firstNew);
cache.initialize(firstNew, items, false);
cache.activate(secondNew);
assert.notEqual(firstNew.key, secondNew.key);
assert.deepEqual(cache.read(secondNew).contextItems, []);
cache.bindUploadConversation(firstNew, 'upload-created-chat');
const created = composerAttachmentOwner('reader', 'upload-created-chat', 'personal', 6);
cache.activate(created);
const adopted = cache.sameDraft(firstNew, created);
assert.equal(adopted, true);
assert.equal(cache.read(created).contextItems[0].id, documentId);
assert.equal(cache.read(created).uploadConversationId, 'upload-created-chat');
assert.deepEqual(cache.read(secondNew).contextItems, []);
cache.forget('reader', 'upload-created-chat');
assert.deepEqual(cache.read(firstNew).contextItems, [], 'deleting a conversation also drops its unsaved alias');
assert.deepEqual(cache.read(created).contextItems, []);

const collaborativeA = composerAttachmentOwner('reader', 'chat-a', 'collaborative', 7);
cache.activate(collaborativeA);
assert.deepEqual(cache.read(collaborativeA).contextItems, [], 'storage kinds do not share pending selections');
const otherAccount = composerAttachmentOwner('different-reader', 'chat-a', 'personal', 8);
cache.activate(otherAccount);
const staleAccountUpdate = cache.update(returnedA, (current) => ({ ...current, contextItems: items }));
const staleAccountRecovery = cache.recover(ownerA, cache.read(ownerA).revision, sentDraft);
assert.equal(staleAccountUpdate, false);
assert.equal(staleAccountRecovery, false);
assert.deepEqual(cache.read(otherAccount).contextItems, []);
assert.equal(cache.read(otherAccount).initialized, true, 'an account change cannot rehydrate the previous account message snapshot');

const originalMessages = [{
    id: 'chat-a_file_upload', conversation_id: 'chat-a', role: 'file', content: '',
    workspace_document_id: documentId, filename: 'original.png',
    metadata: { workspace_attachment: { scope: 'personal' } },
}, {
    id: 'chat-b_file_upload', conversation_id: 'chat-b', role: 'file', content: '',
    workspace_document_id: documentId, filename: 'wrong-conversation.png',
}];
const sourceDocuments = conversationSourceDocuments('chat-a', originalMessages, {
    conversation_id: 'chat-a', title: 'Original chat',
    used_documents: [{ document_id: documentId, title: documentId, scope: { type: 'personal' } }],
});
const restored = restoreDocumentSources(selection, [], sourceDocuments);
assert.equal(restored[0].label, 'original.png');
const unrelated = conversationSourceDocuments('chat-c', originalMessages, {
    conversation_id: 'chat-a', title: 'Not this conversation', linked_workspace_documents: [document],
});
assert.deepEqual(unrelated, []);
const unnamed = restoreDocumentSources(selection, [], [{ document_id: documentId, title: documentId, file_name: documentId }]);
assert.equal(unnamed[0].label, DOCUMENT_DETAILS_UNAVAILABLE);
assert.notEqual(unnamed[0].meta.fileName, documentId);

for (const kind of ['group', 'public']) {
    const scoped = {
        version: 1, mode: 'selected',
        sources: [{ kind: 'document', id: documentId, scope: { kind, id: 'workspace-a' } }],
    };
    const wrongWorkspace = restoreDocumentSources(scoped, [], [{
        ...document, scope: { type: kind, id: 'workspace-b' },
    }]);
    assert.equal(wrongWorkspace[0].label, DOCUMENT_DETAILS_UNAVAILABLE);
    const named = restoreDocumentSources(scoped, [{ kind, id: 'workspace-a', name: 'Original workspace' }], [{
        ...document, title: '<img src=x onerror=unsafe()>', scope: { type: kind, id: 'workspace-a' },
    }]);
    assert.equal(named[0].label, '<img src=x onerror=unsafe()>');
    assert.equal(named[0].scope.name, 'Original workspace');
    assert.equal(named[0].id, documentId);
}

console.log('Conversation attachment ownership, recovery, adoption, and name checks passed.');
