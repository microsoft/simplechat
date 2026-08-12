#!/usr/bin/env python3
# test_tabular_large_result_pagination.py
"""
Functional test for tabular SK large-result pagination and output trimming.
Version: 0.250.155
Implemented in: 0.242.067; bounded CSV query path in 0.250.060; source descriptor generalization in 0.250.127; serialized row-size estimation in 0.250.152; contains replay semantics in 0.250.155

This test ensures row-returning tabular processing tools support start_row/max_rows
pagination, avoid skipped rows after auto-trimming oversized output, honor
return_columns projection, and preserve hidden attachment references used by
row-linked document evidence enrichment.
"""

import asyncio
import importlib.util
import io
import json
import os
import sys
import types

import pandas as pd


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'application', 'single_app'))
sys.modules.setdefault('olefile', types.SimpleNamespace())

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


class MockCsvBlobClient:
    """Minimal blob client for bounded CSV query tests."""

    def __init__(self, content):
        self.content = content

    def download_blob(self, etag=None, match_condition=None):
        assert etag == 'etag-csv-300'
        assert match_condition is not None
        content = self.content

        class Downloader:
            def readinto(self, stream):
                return stream.write(content)

        return Downloader()

    def get_blob_properties(self):
        return {'etag': 'etag-csv-300', 'size': len(self.content)}


class MockCsvBlobServiceClient:
    def __init__(self, content):
        self.blob_client = MockCsvBlobClient(content)

    def get_blob_client(self, container, blob):
        assert container == 'mock-container'
        assert blob == 'nested/version-7/large-results.csv'
        return self.blob_client


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
    plugin._blob_version_cache[(container_name, blob_name)] = {
        'blob_etag': 'etag-workbook-test',
        'blob_size': 0,
    }

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


def test_query_tabular_csv_uses_bounded_shared_engine_and_exact_descriptor():
    """Verify CSV queries bypass whole-DataFrame loading and pin the exact analyzed blob."""
    print('🔍 Testing bounded CSV query pagination and source identity...')

    try:
        csv_content = ('Case ID,Score,Payload\n' + ''.join(
            f'SC-{2001 + row_index},{row_index},payload-{row_index}\n'
            for row_index in range(300)
        )).encode('utf-8')
        plugin = TabularProcessingPlugin()
        plugin._resolve_blob_location_with_fallback = lambda *args, **kwargs: (
            'mock-container',
            'nested/version-7/large-results.csv',
        )
        plugin._get_blob_service_client = lambda: MockCsvBlobServiceClient(csv_content)
        plugin._read_tabular_blob_to_dataframe = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError('CSV query must not use the whole-DataFrame reader')
        )

        result = asyncio.run(plugin.query_tabular_data(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='large-results.csv',
            query_expression='Score >= 0',
            return_columns='Case ID,Score',
            source='chat',
            start_row='94',
            max_rows='95',
        ))
        payload = json.loads(result)
        descriptor = result.internal_metadata['tabular_generated_export_source']

        assert payload['total_matches'] == 300, payload
        assert payload['returned_rows'] == 95, payload
        assert payload['data'][0]['Case ID'] == 'SC-2095', payload
        assert payload['data'][-1]['Case ID'] == 'SC-2189', payload
        assert descriptor['container'] == 'mock-container', descriptor
        assert descriptor['blob_path'] == 'nested/version-7/large-results.csv', descriptor
        assert descriptor['blob_etag'] == 'etag-csv-300', descriptor
        assert descriptor['expected_row_count'] == 300, descriptor
        assert descriptor['estimated_serialized_row_chars'] > 0, descriptor

        print('✅ Bounded CSV query pagination and source identity passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_filter_rows_csv_attaches_replayable_descriptor_for_full_cohort():
    """Verify a trimmed filter_rows page can replay all matching CSV rows durably."""
    print('🔍 Testing filter_rows durable replay descriptor...')

    try:
        source_rows = [
            {
                'transaction_id': f'BT-{row_index + 1:04d}',
                'status': 'Open' if row_index % 2 == 0 else 'Closed',
            }
            for row_index in range(3000)
        ]
        source_frame = pd.DataFrame(source_rows)
        csv_content = source_frame.to_csv(index=False).encode('utf-8')
        plugin = TabularProcessingPlugin()
        plugin._resolve_blob_location_with_fallback = lambda *args, **kwargs: (
            'mock-container',
            'nested/version-7/large-results.csv',
        )
        plugin._get_blob_service_client = lambda: MockCsvBlobServiceClient(csv_content)
        plugin._read_tabular_blob_to_dataframe = lambda *args, **kwargs: source_frame.copy()

        result = asyncio.run(plugin.filter_rows(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='large-results.csv',
            column='transaction_id',
            operator='contains',
            value='BT-',
            source='chat',
            return_columns='transaction_id,status',
            max_rows='3000',
        ))
        payload = json.loads(result)
        descriptor = result.internal_metadata['tabular_generated_export_source']
        replayed_rows = list(PLUGIN_MODULE.iter_tabular_csv_query_rows(
            csv_stream=io.BytesIO(csv_content),
            query_expression=descriptor['query_expression'],
            return_columns=descriptor['return_columns'],
            source_chunk_rows=137,
            tabular_plugin=plugin,
        ))

        assert payload['total_matches'] == 3000, payload
        assert payload['returned_rows'] < payload['total_matches'], payload
        assert descriptor['source_function'] == 'filter_rows', descriptor
        assert descriptor['expected_row_count'] == 3000, descriptor
        assert len(replayed_rows) == 3000, len(replayed_rows)
        assert replayed_rows[0][1]['transaction_id'] == 'BT-0001', replayed_rows[0]
        assert replayed_rows[-1][1]['transaction_id'] == 'BT-3000', replayed_rows[-1]

        print('✅ filter_rows durable replay descriptor passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_filter_rows_csv_contains_replay_uses_literal_semantics():
    """Verify contains filters use literal semantics in foreground and durable replay."""
    print('🔍 Testing filter_rows contains replay literal semantics...')

    try:
        source_frame = pd.DataFrame([
            {'transaction_id': 'A.*', 'status': 'Open'},
            {'transaction_id': 'ABCD', 'status': 'Open'},
            {'transaction_id': 'a.*', 'status': 'Closed'},
            {'transaction_id': 'B-100', 'status': 'Closed'},
        ])
        csv_content = source_frame.to_csv(index=False).encode('utf-8')
        plugin = TabularProcessingPlugin()
        plugin._resolve_blob_location_with_fallback = lambda *args, **kwargs: (
            'mock-container',
            'nested/version-7/large-results.csv',
        )
        plugin._get_blob_service_client = lambda: MockCsvBlobServiceClient(csv_content)
        plugin._read_tabular_blob_to_dataframe = lambda *args, **kwargs: source_frame.copy()

        result = asyncio.run(plugin.filter_rows(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='large-results.csv',
            column='transaction_id',
            operator='contains',
            value='A.*',
            source='chat',
            return_columns='transaction_id,status',
            max_rows='100',
        ))
        payload = json.loads(result)
        descriptor = result.internal_metadata['tabular_generated_export_source']
        replayed_rows = list(PLUGIN_MODULE.iter_tabular_csv_query_rows(
            csv_stream=io.BytesIO(csv_content),
            query_expression=descriptor['query_expression'],
            return_columns=descriptor['return_columns'],
            source_chunk_rows=2,
            tabular_plugin=plugin,
        ))

        assert payload['total_matches'] == 2, payload
        assert descriptor['expected_row_count'] == 2, descriptor
        assert 'regex=False' in descriptor['query_expression'], descriptor
        assert [row['transaction_id'] for _, row in replayed_rows] == ['A.*', 'a.*'], replayed_rows

        print('✅ filter_rows contains replay literal semantics passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_filter_rows_csv_rejects_non_replayable_normalized_matching():
    """Verify normalized matching fails closed instead of advertising partial replay."""
    print('🔍 Testing normalized filter_rows replay rejection...')

    try:
        source_frame = pd.DataFrame([
            {'Owner': 'Contoso, Inc.'},
            {'Owner': 'CONTOSO INC'},
        ])
        csv_content = source_frame.to_csv(index=False).encode('utf-8')
        plugin = TabularProcessingPlugin()
        plugin._resolve_blob_location_with_fallback = lambda *args, **kwargs: (
            'mock-container',
            'nested/version-7/large-results.csv',
        )
        plugin._get_blob_service_client = lambda: MockCsvBlobServiceClient(csv_content)
        plugin._read_tabular_blob_to_dataframe = lambda *args, **kwargs: source_frame.copy()

        result = asyncio.run(plugin.filter_rows(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='large-results.csv',
            column='Owner',
            operator='equals',
            value='Contoso Inc',
            normalize_match='true',
            source='chat',
        ))
        payload = json.loads(result)
        metadata = result.internal_metadata

        assert payload['total_matches'] == 2, payload
        assert 'tabular_generated_export_source' not in metadata, metadata
        assert 'normalize_match=true' in metadata['tabular_generated_export_source_error'], metadata

        print('✅ Normalized filter_rows replay rejection passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_search_rows_csv_attaches_replayable_multi_column_descriptor():
    """Verify filtered multi-column searches replay the same complete CSV cohort."""
    print('🔍 Testing search_rows durable replay descriptor...')

    try:
        source_rows = [
            {
                'transaction_id': f'BT-{row_index + 1:04d}',
                'status': 'Open' if row_index % 2 == 0 else 'Closed',
                'notes': 'Risk review' if row_index % 3 == 0 else 'Routine',
            }
            for row_index in range(300)
        ]
        source_frame = pd.DataFrame(source_rows)
        csv_content = source_frame.to_csv(index=False).encode('utf-8')
        plugin = TabularProcessingPlugin()
        plugin._resolve_blob_location_with_fallback = lambda *args, **kwargs: (
            'mock-container',
            'nested/version-7/large-results.csv',
        )
        plugin._get_blob_service_client = lambda: MockCsvBlobServiceClient(csv_content)
        plugin._read_tabular_blob_to_dataframe = lambda *args, **kwargs: source_frame.copy()

        result = asyncio.run(plugin.search_rows(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='large-results.csv',
            search_value='risk',
            search_columns='transaction_id,notes',
            filter_column='status',
            filter_operator='equals',
            filter_value='Open',
            return_columns='transaction_id,status,notes',
            source='chat',
            max_rows='10',
        ))
        payload = json.loads(result)
        descriptor = result.internal_metadata['tabular_generated_export_source']
        replayed_rows = list(PLUGIN_MODULE.iter_tabular_csv_query_rows(
            csv_stream=io.BytesIO(csv_content),
            query_expression=descriptor['query_expression'],
            return_columns=descriptor['return_columns'],
            source_chunk_rows=41,
            tabular_plugin=plugin,
        ))

        assert payload['total_matches'] == 50, payload
        assert payload['returned_rows'] == 10, payload
        assert descriptor['source_function'] == 'search_rows', descriptor
        assert descriptor['expected_row_count'] == 50, descriptor
        assert len(replayed_rows) == payload['total_matches'], replayed_rows
        assert all(row['status'] == 'Open' for _, row in replayed_rows), replayed_rows[:3]
        assert all('risk' in row['notes'].lower() for _, row in replayed_rows), replayed_rows[:3]

        print('✅ search_rows durable replay descriptor passed')
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
        test_query_tabular_csv_uses_bounded_shared_engine_and_exact_descriptor,
        test_filter_rows_csv_attaches_replayable_descriptor_for_full_cohort,
        test_filter_rows_csv_contains_replay_uses_literal_semantics,
        test_filter_rows_csv_rejects_non_replayable_normalized_matching,
        test_search_rows_csv_attaches_replayable_multi_column_descriptor,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)