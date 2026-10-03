// test_v2_workflow_merge_task.mjs
// Version: 0.261.221
// Implemented in: 0.261.220
// Exercises the V2 workflow editor's pure merge-task helpers: action construction, option cleanup,
// alias parsing, and client-side validation for the backend merge document_action contract.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

globalThis.fetch = () => {
    throw new Error('Workflow merge task helpers must not make network requests.');
};

const {
    cleanupWorkflowMergeOptions,
    formatWorkflowMergeColumnAliases,
    parseWorkflowMergeColumnAliases,
    workflowMergeActionFromSelection,
    workflowMergeDocumentLimit,
    workflowMergeEnabled,
    workflowMergeValidationErrors,
} = await import('../application/v2_ui/src/lib/workflowEditor.ts');

const documents = [
    { id: 'personal::customers', name: 'Customers.csv', document_id: 'customers', scope_type: 'personal', scope_id: 'owner-1' },
    { id: 'personal::orders', name: 'Orders.csv', document_id: 'orders', scope_type: 'personal', scope_id: 'owner-1' },
    { id: 'personal::refunds', name: 'Refunds.csv', document_id: 'refunds', scope_type: 'personal', scope_id: 'owner-1' },
];

test('builds a valid tabular selected merge action and preserves selected order', () => {
    const action = workflowMergeActionFromSelection(documents, {
        mergeKind: 'tabular',
        outputFormat: 'xlsx',
        outputFileName: 'monthly_merge',
    });
    assert.deepEqual(action, {
        type: 'merge',
        merge_kind: 'tabular',
        target_mode: 'selected',
        doc_scope: 'personal',
        active_group_ids: [],
        active_public_workspace_id: [],
        document_ids: ['customers', 'orders', 'refunds'],
        output_format: 'xlsx',
        output_file_name: 'monthly_merge',
    });
    assert.deepEqual(workflowMergeValidationErrors(action), []);
});

test('selected mode requires at least two files and honors a server merge limit when present', () => {
    const oneFile = workflowMergeActionFromSelection(documents.slice(0, 1));
    assert.match(workflowMergeValidationErrors(oneFile).join('\n'), /at least 2 selected files/);
    const tooMany = workflowMergeActionFromSelection(documents);
    assert.match(workflowMergeValidationErrors(tooMany, { maxSelectedDocuments: 2 }).join('\n'), /at most 2 selected files/);
});

test('mapped schema policy requires output columns', () => {
    const action = workflowMergeActionFromSelection(documents, {
        mergeOptions: { schema_policy: 'mapped' },
    });
    assert.match(workflowMergeValidationErrors(action).join('\n'), /Mapped columns needs at least 1 item/);
});

test('tabular and workbook options reject named sheet plus every sheet', () => {
    const tabular = {
        ...workflowMergeActionFromSelection(documents),
        merge_options: { sheet: 'Data', sheets: 'all' },
    };
    assert.match(workflowMergeValidationErrors(tabular).join('\n'), /either one named sheet or every sheet/);
    const workbook = {
        ...workflowMergeActionFromSelection(documents, { mergeKind: 'workbook' }),
        merge_options: { sheet: 'Data', sheets: 'all' },
    };
    assert.match(workflowMergeValidationErrors(workbook, { availableKinds: ['tabular', 'workbook'] }).join('\n'), /either one named sheet or every sheet/);
});

test('key-column dedupe requires key columns', () => {
    const action = workflowMergeActionFromSelection(documents, {
        mergeOptions: { dedupe: 'key_columns' },
    });
    assert.match(workflowMergeValidationErrors(action).join('\n'), /Duplicate key columns needs at least 1 item/);
});

test('alias parse and format round trip and parse errors are explicit', () => {
    const parsed = parseWorkflowMergeColumnAliases('Customer ID = cust_id, CustomerID\nOrder Date = order_date');
    assert.deepEqual(parsed, {
        aliases: {
            'Customer ID': ['cust_id', 'CustomerID'],
            'Order Date': ['order_date'],
        },
        errors: [],
    });
    assert.equal(formatWorkflowMergeColumnAliases(parsed.aliases), 'Customer ID = cust_id, CustomerID\nOrder Date = order_date');
    const broken = parseWorkflowMergeColumnAliases('Customer ID cust_id\n= missing\nEmpty =');
    assert.deepEqual(broken.aliases, {});
    assert.equal(broken.errors.length, 3);
});

test('unavailable loaded kinds are preserved but fail validation', () => {
    // Word arrives in Phase 5; PDF and workbook merges are available from 0.261.221.
    const action = workflowMergeActionFromSelection(documents, { mergeKind: 'docx' });
    assert.equal(action.merge_kind, 'docx');
    assert.equal(action.output_format, 'docx');
    assert.match(workflowMergeValidationErrors(action).join('\n'), /not enabled/);
    const pdf = workflowMergeActionFromSelection(documents, { mergeKind: 'pdf' });
    assert.equal(pdf.output_format, 'pdf');
    assert.doesNotMatch(workflowMergeValidationErrors(pdf).join('\n'), /not enabled/);
});

test('changed targets are only valid for File Sync workflows', () => {
    const action = workflowMergeActionFromSelection([], { targetMode: 'changed' });
    assert.deepEqual(action.document_ids, []);
    assert.match(workflowMergeValidationErrors(action).join('\n'), /File Sync workflows/);
    assert.deepEqual(workflowMergeValidationErrors(action, { isFileSyncWorkflow: true }), []);
});

test('non-tabular merge kinds force their implied output format', () => {
    const cases = [
        ['workbook', 'xlsx'],
        ['pdf', 'pdf'],
        ['docx', 'docx'],
        ['pptx', 'pptx'],
    ];
    for (const [mergeKind, outputFormat] of cases) {
        const action = workflowMergeActionFromSelection(documents, { mergeKind, outputFormat: 'csv' });
        assert.equal(action.output_format, outputFormat, mergeKind);
    }
});

test('cleanup omits merge option defaults and keeps only meaningful overrides', () => {
    assert.equal(cleanupWorkflowMergeOptions('tabular', {
        schema_policy: 'by_name',
        include_source_column: true,
        source_column_name: 'Source File',
        on_incompatible: 'fail',
        dedupe: 'none',
        dedupe_keep: 'first',
        sheets: 'first',
    }), undefined);
    assert.deepEqual(cleanupWorkflowMergeOptions('tabular', {
        schema_policy: 'union',
        include_source_column: false,
        source_column_name: 'Origin',
        on_incompatible: 'exclude',
        dedupe: 'key_columns',
        dedupe_columns: ['Customer ID'],
        dedupe_keep: 'last',
        sort_by: [{ column: 'Customer ID', descending: true, value_type: 'number' }],
    }), {
        schema_policy: 'union',
        include_source_column: false,
        source_column_name: 'Origin',
        on_incompatible: 'exclude',
        dedupe: 'key_columns',
        dedupe_columns: ['Customer ID'],
        dedupe_keep: 'last',
        sort_by: [{ column: 'Customer ID', descending: true, value_type: 'number' }],
    });
    assert.equal(workflowMergeActionFromSelection(documents, {
        mergeOptions: { schema_policy: 'by_name', include_source_column: true },
    }).merge_options, undefined);
    // Settings that only one policy uses are dropped under any other, as the server requires.
    assert.deepEqual(cleanupWorkflowMergeOptions('tabular', {
        schema_policy: 'union', columns: ['Customer ID'], dedupe: 'exact_rows', dedupe_columns: ['Customer ID'],
    }), { schema_policy: 'union', dedupe: 'exact_rows' });
    assert.equal(cleanupWorkflowMergeOptions('tabular', { dedupe_keep: 'last', dedupe_columns: ['ID'] }), undefined);
    assert.deepEqual(cleanupWorkflowMergeOptions('tabular', { schema_policy: 'mapped', columns: ['A', 'A', 'B'] }), {
        schema_policy: 'mapped', columns: ['A', 'B'],
    });
});

test('editor options say whether merging is on and how many files a run may merge', () => {
    // The server sends both; an older server sends neither, and Merge stays offered.
    const options = { document_actions: { merge: { enabled: false, workflow_max_documents: 250 } } };
    assert.equal(workflowMergeEnabled(options), false);
    assert.equal(workflowMergeDocumentLimit(options), 250);
    assert.equal(workflowMergeEnabled({}), true);
    assert.equal(workflowMergeDocumentLimit({}), undefined);
    assert.equal(workflowMergeEnabled({ document_actions: { merge: { enabled: true, workflow_max_documents: 100 } } }), true);
    assert.equal(workflowMergeDocumentLimit({ document_actions: { merge: { workflow_max_documents: 5000 } } }), undefined);
});
