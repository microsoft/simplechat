// test_v2_orchestration_merge_arguments.mjs
// Version: 0.261.219
// Implemented in: 0.261.219
// Executes how the V2 plan card states the settings of a spreadsheet merge or inspection step:
// every policy, alias, sheet, duplicate and sort setting is put in words, defaults are not
// restated, document selections are left to the chips, column and sheet names stay plain data,
// values the server would refuse are not put in words, and other capabilities are untouched.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

globalThis.fetch = () => {
    throw new Error('Merge argument helpers must not make network requests.');
};

// The repository resolver must be registered before extensionless TypeScript imports load.
const {
    TABULAR_INSPECT_CAPABILITY,
    TABULAR_MERGE_CAPABILITY,
    tabularArgumentEntries,
} = await import('../application/v2_ui/src/lib/orchestrationMerge.ts');

const HOSTILE = '<img src=x onerror="alert(1)"> {{7*7}} [link](https://evil.example/)';

test('the capabilities match the server registry', () => {
    assert.equal(TABULAR_MERGE_CAPABILITY, 'tabular_merge');
    assert.equal(TABULAR_INSPECT_CAPABILITY, 'tabular_inspect');
});

test('a default merge states only how columns are matched', () => {
    assert.deepEqual(tabularArgumentEntries('tabular_merge', {
        document_ids: ['a', 'b'], doc_scope: 'all', schema_policy: 'by_name',
        include_source_column: true, source_column_name: 'Source File',
    }), [['columns', 'Same columns, in any order']]);
});

test('every reconciliation setting is put in words', () => {
    assert.deepEqual(tabularArgumentEntries('tabular_merge', {
        document_ids: ['a', 'b'],
        doc_scope: 'group',
        schema_policy: 'mapped',
        columns: ['Customer ID', 'Amount'],
        column_aliases: { 'Customer ID': ['cust_id', 'CustomerID'], Amount: ['Total'] },
        sheets: 'all',
        header_row: 3,
        include_source_column: true,
        source_column_name: 'File',
        on_incompatible: 'exclude',
        dedupe: 'key_columns',
        dedupe_columns: ['Customer ID'],
        dedupe_keep: 'last',
        sort_by: [{ column: 'Amount', value_type: 'number', descending: true }, { column: 'Customer ID' }],
    }), [
        ['columns', 'Only the listed columns'],
        ['keep', 'Customer ID, Amount'],
        ['same column as', 'Customer ID \u2190 cust_id, CustomerID; Amount \u2190 Total'],
        ['workspace', 'Group workspaces'],
        ['sheets', 'Every visible sheet'],
        ['header row', 'Row 3'],
        ['file name column', 'File'],
        ['files that don\u2019t fit', 'Left out and reported'],
        ['duplicates', 'Remove rows with the same Customer ID, keeping the last'],
        ['sort by', 'Amount (number, descending), Customer ID'],
    ]);
    assert.deepEqual(tabularArgumentEntries('tabular_merge', {
        schema_policy: 'union', include_source_column: false, dedupe: 'exact_rows', sheet: 'Data',
    }), [
        ['columns', 'Keep every column from every file'],
        ['sheet', 'Data'],
        ['file name column', 'Off'],
        ['duplicates', 'Remove identical rows, keeping the first'],
    ]);
});

test('names stay plain data', () => {
    assert.deepEqual(tabularArgumentEntries('tabular_merge', { columns: [HOSTILE], sheet: HOSTILE }), [
        ['keep', HOSTILE],
        ['sheet', HOSTILE],
    ]);
});

test('values the server would refuse are not put in words', () => {
    assert.deepEqual(tabularArgumentEntries('tabular_merge', {
        schema_policy: 'toString',
        doc_scope: '__proto__',
        header_row: 0,
        dedupe: 'key_columns',
        dedupe_columns: [],
        sort_by: [{ column: 'Amount', value_type: 'money' }],
        column_aliases: ['not', 'an', 'object'],
    }), []);
    assert.deepEqual(tabularArgumentEntries('tabular_merge', null), []);
    assert.deepEqual(tabularArgumentEntries('tabular_merge', { sort_by: [{ column: '  ' }] }), []);
});

test('inspection states its sheets, header row and sample size', () => {
    assert.deepEqual(tabularArgumentEntries('tabular_inspect', {
        document_ids: ['a'], doc_scope: 'all', sheets: 'all', header_row: 2, sample_rows: 5,
    }), [['sheets', 'Every visible sheet'], ['header row', 'Row 2'], ['sample rows', '5']]);
    assert.deepEqual(tabularArgumentEntries('tabular_inspect', { sample_rows: 50 }), []);
});

test('other capabilities keep the generic argument list', () => {
    assert.equal(tabularArgumentEntries('document_analyze', { analysis_prompt: 'x' }), null);
    assert.equal(tabularArgumentEntries('tabular_analyze', {}), null);
});
