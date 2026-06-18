#!/usr/bin/env python3
# test_tabular_large_result_pagination.py
"""
Functional test for tabular SK large-result pagination and output trimming.
Version: 0.242.068
Implemented in: 0.242.067

This test ensures row-returning tabular processing tools support start_row/max_rows
pagination, avoid skipped rows after auto-trimming oversized output, honor
return_columns projection, and preserve hidden attachment references used by
row-linked document evidence enrichment.
"""

import asyncio
import importlib.util
import json
import os
import sys

import pandas as pd


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'application', 'single_app'))

PLUGIN_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'semantic_kernel_plugins',
    'tabular_processing_plugin.py',
)

PLUGIN_SPEC = importlib.util.spec_from_file_location('tabular_processing_plugin', PLUGIN_FILE)
PLUGIN_MODULE = importlib.util.module_from_spec(PLUGIN_SPEC)
PLUGIN_SPEC.loader.exec_module(PLUGIN_MODULE)
TabularProcessingPlugin = PLUGIN_MODULE.TabularProcessingPlugin


def build_workbook_plugin(workbook_frames):
    """Create a TabularProcessingPlugin backed by in-memory workbook frames."""
    plugin = TabularProcessingPlugin()
    container_name = 'mock-container'
    blob_name = 'large-results.xlsx'
    sheet_names = list(workbook_frames.keys())
    workbook_metadata = {
        'is_workbook': True,
        'sheet_names': sheet_names,
        'sheet_count': len(sheet_names),
        'default_sheet': sheet_names[0],
    }

    plugin._resolve_blob_location_with_fallback = lambda *args, **kwargs: (container_name, blob_name)
    plugin._get_workbook_metadata = lambda *args, **kwargs: workbook_metadata.copy()

    def read_dataframe(container, blob, sheet_name=None, sheet_index=None, require_explicit_sheet=False):
        selected_sheet, _ = plugin._resolve_sheet_selection(
            container,
            blob,
            sheet_name=sheet_name,
            sheet_index=sheet_index,
            require_explicit_sheet=require_explicit_sheet,
        )
        return workbook_frames[selected_sheet].copy()

    plugin._read_tabular_blob_to_dataframe = read_dataframe
    return plugin


def test_filter_rows_paginates_without_skipping_after_row_trim():
    """Verify oversized one-column pages advance by returned rows, not requested rows."""
    print('🔍 Testing row-trim pagination cursor...')

    try:
        long_text = 'match ' + ('x' * 25000)
        plugin = build_workbook_plugin({
            'Data': pd.DataFrame([
                {'Notes': f'{long_text} {row_index}'}
                for row_index in range(8)
            ]),
        })

        payload = json.loads(asyncio.run(plugin.filter_rows(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='large-results.xlsx',
            sheet_name='Data',
            column='Notes',
            operator='contains',
            value='match',
            source='workspace',
            max_rows='8',
        )))

        assert payload['total_matches'] == 8, payload
        assert payload['output_trimmed'] is True, payload
        assert payload['returned_rows'] < payload['page_size'], payload
        assert payload['has_more'] is True, payload
        assert payload['next_start_row'] == payload['returned_rows'], payload

        print('✅ Row-trim pagination cursor passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_filter_rows_auto_excludes_heavy_columns_and_return_columns_skips_trim():
    """Verify heavy columns are excluded unless the caller explicitly projects columns."""
    print('🔍 Testing auto-trim and return_columns projection...')

    try:
        plugin = build_workbook_plugin({
            'Data': pd.DataFrame([
                {
                    'ID': row_index,
                    'Status': 'Open',
                    'LargeNarrative': 'details ' + ('z' * 9000),
                }
                for row_index in range(12)
            ]),
        })

        trimmed_payload = json.loads(asyncio.run(plugin.filter_rows(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='large-results.xlsx',
            sheet_name='Data',
            column='Status',
            operator='equals',
            value='Open',
            source='workspace',
            max_rows='10',
        )))

        assert trimmed_payload['total_matches'] == 12, trimmed_payload
        assert trimmed_payload['returned_rows'] == 10, trimmed_payload
        assert trimmed_payload['has_more'] is True, trimmed_payload
        assert trimmed_payload['next_start_row'] == 10, trimmed_payload
        assert 'LargeNarrative' in trimmed_payload['auto_excluded_columns'], trimmed_payload
        assert 'LargeNarrative' not in trimmed_payload['data'][0], trimmed_payload

        projected_payload = json.loads(asyncio.run(plugin.filter_rows(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='large-results.xlsx',
            sheet_name='Data',
            column='Status',
            operator='equals',
            value='Open',
            source='workspace',
            return_columns='ID,Status',
            max_rows='5',
        )))

        assert projected_payload['return_columns'] == ['ID', 'Status'], projected_payload
        assert 'auto_excluded_columns' not in projected_payload, projected_payload
        assert projected_payload['data'][0] == {'ID': 0, 'Status': 'Open'}, projected_payload
        assert projected_payload['has_more'] is True, projected_payload
        assert projected_payload['next_start_row'] == 5, projected_payload

        print('✅ Auto-trim and return_columns projection passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_cross_sheet_filter_rows_paginates_across_sheet_boundary():
    """Verify cross-sheet pagination continues without losing boundary rows."""
    print('🔍 Testing cross-sheet pagination...')

    try:
        plugin = build_workbook_plugin({
            'SheetA': pd.DataFrame([
                {'ID': f'A-{row_index}', 'Status': 'Open'}
                for row_index in range(3)
            ]),
            'SheetB': pd.DataFrame([
                {'ID': f'B-{row_index}', 'Status': 'Open'}
                for row_index in range(3)
            ]),
        })

        first_page = json.loads(asyncio.run(plugin.filter_rows(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='large-results.xlsx',
            column='Status',
            operator='equals',
            value='Open',
            source='workspace',
            max_rows='4',
        )))

        second_page = json.loads(asyncio.run(plugin.filter_rows(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='large-results.xlsx',
            column='Status',
            operator='equals',
            value='Open',
            source='workspace',
            start_row=str(first_page['next_start_row']),
            max_rows='4',
        )))

        assert first_page['selected_sheet'] == 'ALL (cross-sheet search)', first_page
        assert first_page['total_matches'] == 6, first_page
        assert [row['ID'] for row in first_page['data']] == ['A-0', 'A-1', 'A-2', 'B-0'], first_page
        assert first_page['next_start_row'] == 4, first_page
        assert [row['ID'] for row in second_page['data']] == ['B-1', 'B-2'], second_page
        assert second_page['has_more'] is False, second_page

        print('✅ Cross-sheet pagination passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_search_rows_preserves_attachment_references_with_return_columns():
    """Verify projected search results keep hidden attachment columns for enrichment."""
    print('🔍 Testing attachment reference preservation with projection...')

    try:
        plugin = build_workbook_plugin({
            'Data': pd.DataFrame([
                {
                    'Summary': 'urgent review needed',
                    'AttachmentFile': 'case-notes.pdf',
                    'Owner': 'Analyst',
                },
            ]),
        })

        payload = json.loads(asyncio.run(plugin.search_rows(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='large-results.xlsx',
            sheet_name='Data',
            search_value='urgent',
            return_columns='Summary',
            source='workspace',
            max_rows='5',
        )))

        assert payload['returned_rows'] == 1, payload
        row = payload['data'][0]
        assert row['Summary'] == 'urgent review needed', payload
        assert 'AttachmentFile' not in row, payload
        assert row['_related_document_reference_values']['AttachmentFile'] == 'case-notes.pdf', payload
        assert row['_matched_columns'] == ['Summary'], payload

        print('✅ Attachment reference preservation passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_query_tabular_data_supports_return_columns_and_pagination():
    """Verify query results support explicit projection and continuation metadata."""
    print('🔍 Testing query pagination with return_columns...')

    try:
        plugin = build_workbook_plugin({
            'Data': pd.DataFrame([
                {'ID': row_index, 'Status': 'Open', 'Payload': 'large ' + ('q' * 1000)}
                for row_index in range(6)
            ]),
        })

        payload = json.loads(asyncio.run(plugin.query_tabular_data(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='large-results.xlsx',
            sheet_name='Data',
            query_expression='Status == "Open"',
            return_columns='ID,Status',
            start_row='2',
            max_rows='3',
            source='workspace',
        )))

        assert payload['total_matches'] == 6, payload
        assert payload['start_row'] == 2, payload
        assert payload['returned_rows'] == 3, payload
        assert payload['has_more'] is True, payload
        assert payload['next_start_row'] == 5, payload
        assert payload['return_columns'] == ['ID', 'Status'], payload
        assert [row['ID'] for row in payload['data']] == [2, 3, 4], payload
        assert 'Payload' not in payload['data'][0], payload

        print('✅ Query pagination with return_columns passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_filter_rows_paginates_without_skipping_after_row_trim,
        test_filter_rows_auto_excludes_heavy_columns_and_return_columns_skips_trim,
        test_cross_sheet_filter_rows_paginates_across_sheet_boundary,
        test_search_rows_preserves_attachment_references_with_return_columns,
        test_query_tabular_data_supports_return_columns_and_pagination,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)