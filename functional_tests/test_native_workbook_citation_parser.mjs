// test_native_workbook_citation_parser.mjs
// Version: 0.261.417
// Implemented in: 0.261.417
// Execute the real parser against exact retained and ambiguous native evidence.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

const { parseCitations } = await import('../application/v2_ui/src/lib/citations.ts');
const id = 'workbook:native-comments:1';
const record = {
    citation_id: id, document_id: 'workbook', file_name: 'review.xlsx',
    location_label: 'Location', location_value: 'Budget!B4',
    native_evidence: { producer: { user_id: 'owner', conversation_id: 'conversation', run_id: 'run' }, manifest_sha256: 'a'.repeat(64) },
};

for (const label of ['Location', 'Worksheet cell']) {
    test(`${label} marker uses explicit retained document identity`, () => {
        const parsed = parseCitations(`Check (Source: review.xlsx, ${label}: Budget!B4) [#${id}]`, [record]);
        assert.equal(parsed.groups.length, 1);
        assert.equal(parsed.groups[0].citations[0].documentId, 'workbook');
        assert.equal(parsed.groups[0].citations[0].conversationId, 'conversation');
        assert.deepEqual(parsed.groups[0].citations[0].nativeEvidence, record.native_evidence);
        assert.equal(parsed.groups[0].citations[0].locationValue, 'Budget!B4');
    });
}

test('retained location cannot be rewritten by model prose', () => {
    const parsed = parseCitations(`(Source: review.xlsx, Location: Other!A99) [#${id}]`, [record]);
    assert.equal(parsed.groups[0].citations[0].locationValue, 'Budget!B4');
});

test('missing or conflicting retained metadata is visible as unavailable, never decoded as a document', () => {
    for (const records of [[], [{ ...record, native_evidence: undefined }],
        [{ ...record, document_id: undefined }], [{ ...record, document_id: ' ' }], [
        record, { ...record, native_evidence: { ...record.native_evidence, manifest_sha256: 'b'.repeat(64) } },
    ]]) {
        const parsed = parseCitations(`(Source: review.xlsx, Worksheet cell: Budget!B4) [#${id}]`, records);
        assert.equal(parsed.groups.length, 0);
        assert.match(parsed.text, /Source unavailable/);
        assert.doesNotMatch(parsed.text, /native-comments/);
    }
});

test('orphan native ids resolve only with authentic retained metadata', () => {
    const known = parseCitations(`Review [#${id}]`, [record]);
    assert.equal(known.groups.length, 1);
    const unknown = parseCitations(`Review [#${id}]`);
    assert.match(unknown.text, /Source unavailable/);
});

test('ordinary page sheet web and Microsoft 365 identities remain unchanged', () => {
    for (const [marker, kind, documentId] of [
        ['(Source: report.pdf, Page: 2) [#document_2]', 'document', 'document'],
        ['(Source: report.xlsx, Sheet: Budget) [#document_3]', 'document', 'document'],
        ['(Source: https://example.com/a, Location: Article) [#web_1]', 'web', 'web'],
        ['(Source: Mail, Location: Inbox) [#m365-0123456789abcdef]', 'm365', 'm365-0123456789abcdef'],
    ]) {
        const parsed = parseCitations(marker);
        assert.equal(parsed.groups[0].kind, kind);
        assert.equal(parsed.groups[0].citations[0].documentId, documentId);
    }
});
