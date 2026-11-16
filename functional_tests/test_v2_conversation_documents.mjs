// test_v2_conversation_documents.mjs
// Version: 0.261.327
// Implemented in: 0.261.327
// Validates readable drawer metadata, complementary records and workspace names without I/O.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const { conversationDocuments, conversationDocumentName, conversationDocumentSource } =
    await import('../application/v2_ui/src/lib/conversationDocuments.ts');

const id = 'a064bcf3-4386-497d-afa1-0054fbb59c9f';
const metadata = {
    used_documents: [{
        document_id: id, title: id, scope: { type: 'group', id: 'group-1' },
        citation_ids: ['chunk-1'], page_numbers: [0],
    }],
    legacy_used_documents: [{
        document_id: id, title: 'Aircraft registration', file_name: 'Elliott Hendricks.pdf',
        scope: { type: 'group', id: 'group-1', name: 'Aircraft records' },
    }],
    linked_workspace_documents: [{ document_id: id, file_type: 'pdf' }],
    tags: [{ category: 'document', document_id: 'unrelated' }],
};
const before = JSON.stringify(metadata);
const documents = conversationDocuments(metadata);
assert.equal(documents.length, 1);
assert.deepEqual(documents[0].citation_ids, ['chunk-1']);
assert.deepEqual(documents[0].page_numbers, [0]);
assert.equal(documents[0].file_type, 'pdf');
assert.equal(JSON.stringify(metadata), before);
assert.deepEqual(conversationDocumentName(documents[0]), {
    title: 'Aircraft registration', filename: 'Elliott Hendricks.pdf',
});
assert.equal(conversationDocumentSource(documents[0], [], []), 'Aircraft records');
assert.equal(conversationDocumentSource({ scope: { type: 'personal', name: 'Pat Reader' } }, [], []), 'Personal workspace');
for (const [type, catalog, fallback] of [
    ['group', 'Engineering', 'Group workspace'], ['public', 'Published research', 'Public workspace'],
]) {
    const document = { scope: { type, id, name: id } };
    const entries = [{ id, name: catalog }, { id: 'active-workspace', name: 'Wrong workspace' }];
    assert.equal(conversationDocumentSource(document, type === 'group' ? entries : [], type === 'public' ? entries : []), catalog);
    assert.equal(conversationDocumentSource(document, [], []), fallback);
}
assert.deepEqual(conversationDocumentName({ document_id: id, title: id }), {
    title: 'Untitled document', filename: '',
});
assert.deepEqual(conversationDocumentName({ document_id: id, title: 'Unknown Document', file_name: 'report.pdf' }), {
    title: 'report.pdf', filename: '',
});
assert.deepEqual(conversationDocumentName({ document_id: id, title: ' report.pdf ', file_name: 'report.pdf' }), {
    title: 'report.pdf', filename: '',
});
const incompatible = conversationDocuments({
    used_documents: [{ document_id: id, scope: { type: 'group', id: 'group-1' } }],
    legacy_used_documents: [{ document_id: id, scope: { type: 'group', id: 'group-2', name: 'Wrong group' } }],
});
assert.equal(incompatible[0].scope.name, undefined);
assert.deepEqual(conversationDocuments(null), []);
console.log('Conversation document presentation checks passed.');
