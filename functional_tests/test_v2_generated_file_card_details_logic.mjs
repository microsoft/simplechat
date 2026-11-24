// test_v2_generated_file_card_details_logic.mjs
// Version: 0.261.481
// Implemented in: 0.261.481
// Executes the real V2 helpers that decide which facts a generated file's card shows. A row
// count describes a file of records (CSV, Excel, JSON, XML, YAML) and nothing else: a Word
// document, PDF, deck or text file reports zero records, which used to read "0 rows" on a
// finished document. Size is shown for every format.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const hadWindow = 'window' in globalThis;
const previousWindow = globalThis.window;
globalThis.window = { location: { href: 'https://chat.example.gov/v2/chat' } };

try {
    const { orchestrationOutputHasRows, orchestrationOutputRowLabel } = await import(
        '../application/v2_ui/src/lib/orchestrationOutputs.ts'
    );
    const { generatedFileDetails } = await import('../application/v2_ui/src/lib/conversationGeneratedFiles.ts');

    for (const format of ['csv', 'xlsx', 'json', 'xml', 'yaml', 'yml', '.CSV', ' Xlsx ']) {
        assert.equal(orchestrationOutputHasRows(format), true, `${format} is a file of records`);
    }
    for (const format of ['docx', 'pdf', 'pptx', 'md', 'txt', '', 'toString', 'constructor']) {
        assert.equal(orchestrationOutputHasRows(format), false, `${format} has no rows to count`);
    }

    assert.equal(orchestrationOutputRowLabel('csv', 50), '50 rows');
    assert.equal(orchestrationOutputRowLabel('csv', 1), '1 row');
    // Zero is a real count for a file of records, never dropped as if it were missing.
    assert.equal(orchestrationOutputRowLabel('csv', 0), '0 rows');
    assert.equal(orchestrationOutputRowLabel('xlsx', 1200), `${(1200).toLocaleString()} rows`);
    assert.equal(orchestrationOutputRowLabel('csv', null), '');
    // The reported case: a finished Word document carried row_count 0.
    assert.equal(orchestrationOutputRowLabel('docx', 0), '');
    assert.equal(orchestrationOutputRowLabel('pdf', 12), '');

    const file = (format, typeLabel, rowCount, sizeBytes) => ({
        key: `artifact:${format}`, fileName: `review.${format}`, format, typeLabel, messageId: 'm1',
        status: 'ready', statusLabel: '', rowCount, sizeBytes, documentId: '', artifact: null,
    });
    assert.equal(generatedFileDetails(file('docx', 'Word document', 0, 41274)), 'Word document · 40.3 KB');
    assert.equal(generatedFileDetails(file('pptx', 'PowerPoint deck', 0, 2048)), 'PowerPoint deck · 2 KB');
    assert.equal(generatedFileDetails(file('txt', 'Text file', 0, 0)), 'Text file · 0 B');
    assert.equal(generatedFileDetails(file('csv', 'CSV file', 50, 1006)), 'CSV file · 50 rows · 1006 B');
    assert.equal(generatedFileDetails(file('csv', 'CSV file', 0, 0)), 'CSV file · 0 rows · 0 B');

    console.log('Generated file card details logic passed.');
} finally {
    if (hadWindow) {
        globalThis.window = previousWindow;
    } else {
        delete globalThis.window;
    }
}
