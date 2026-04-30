#!/usr/bin/env python3
# test_tabular_group_blob_context_and_sheet_whitespace.py
"""
Functional test for tabular group blob context and sheet whitespace handling.
Version: 0.240.031
Implemented in: 0.240.031

This test ensures workbook tabs with trailing whitespace still resolve
correctly and that tabular analysis can reuse pre-resolved group blob
locations even when later tool calls omit group_id.
"""

import asyncio
import importlib.util
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
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')

PLUGIN_SPEC = importlib.util.spec_from_file_location('tabular_processing_plugin', PLUGIN_FILE)
PLUGIN_MODULE = importlib.util.module_from_spec(PLUGIN_SPEC)
PLUGIN_SPEC.loader.exec_module(PLUGIN_MODULE)
TabularProcessingPlugin = PLUGIN_MODULE.TabularProcessingPlugin


def build_mock_whitespace_workbook_plugin():
    """Create a plugin backed by an in-memory workbook with a trailing-space sheet name."""
    plugin = TabularProcessingPlugin()
    container_name = 'mock-group-container'
    blob_name = 'group-123/CCO-Legal File Plan 2025_Final Approved.xlsx'
    workbook_frames = {
        'Legal': pd.DataFrame({
            'Records Schedule Item': ['GRS 5.1, item 010', 'GRS 2.3, item 050'],
            'File Type (Description)': ['Travel', 'Administrative Inquiries'],
        }),
        'CUI ': pd.DataFrame({
            'Records Schedule Item': ['CUI 1.0'],
            'File Type (Description)': ['Controlled Unclassified Information'],
        }),
        'GRS': pd.DataFrame({
            'Schedule': ['GRS 5.1', 'GRS 2.3'],
            'Title': ['Administrative Records', 'Transitory Records'],
        }),
    }
    workbook_metadata = {
        'is_workbook': True,
        'sheet_names': ['Legal', 'CUI ', 'GRS'],
        'sheet_count': 3,
        'default_sheet': 'Legal',
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
    return plugin, container_name, blob_name


def test_workbook_schema_summary_handles_trailing_space_sheet_names():
    """Verify workbook-level schema preload succeeds when sheet names include trailing spaces."""
    print('Testing workbook schema summary with trailing-space sheet names...')

    try:
        plugin, container_name, blob_name = build_mock_whitespace_workbook_plugin()
        summary = plugin._build_workbook_schema_summary(
            container_name,
            blob_name,
            'CCO-Legal File Plan 2025_Final Approved.xlsx',
            preview_rows=2,
        )

        assert summary['sheet_names'] == ['Legal', 'CUI ', 'GRS'], summary
        assert 'CUI ' in summary['per_sheet_schemas'], summary
        assert summary['per_sheet_schemas']['CUI ']['row_count'] == 1, summary

        print('PASS workbook schema summary with trailing-space sheets')
        return True
    except Exception as exc:
        print(f'FAIL test: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_sheet_selection_matches_trimmed_sheet_request():
    """Verify callers can request a tab without reproducing trailing whitespace exactly."""
    print('Testing trimmed sheet selection against trailing-space tab names...')

    try:
        plugin, _, _ = build_mock_whitespace_workbook_plugin()
        payload = asyncio.run(plugin.get_distinct_values(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='CCO-Legal File Plan 2025_Final Approved.xlsx',
            sheet_name='CUI',
            column='Records Schedule Item',
            source='group',
            max_values='10',
        ))

        assert '"selected_sheet": "CUI "' in payload, payload
        assert '"values": [' in payload, payload
        assert 'CUI 1.0' in payload, payload

        print('PASS trimmed sheet selection against trailing-space tab names')
        return True
    except Exception as exc:
        print(f'FAIL test: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_resolved_group_blob_override_survives_missing_group_id():
    """Verify a pre-resolved group blob location can be reused without group_id on later tool calls."""
    print('Testing resolved group blob location override...')

    try:
        plugin = TabularProcessingPlugin()
        plugin.remember_resolved_blob_location(
            'group',
            'CCO-Legal File Plan 2025_Final Approved.xlsx',
            'group-documents',
            'group-123/CCO-Legal File Plan 2025_Final Approved.xlsx',
        )

        resolved_container, resolved_blob = plugin._resolve_blob_location_with_fallback(
            'test-user',
            'test-conversation',
            'CCO-Legal File Plan 2025_Final Approved.xlsx',
            'group',
        )

        assert resolved_container == 'group-documents', (resolved_container, resolved_blob)
        assert resolved_blob == 'group-123/CCO-Legal File Plan 2025_Final Approved.xlsx', (resolved_container, resolved_blob)

        print('PASS resolved group blob location override')
        return True
    except Exception as exc:
        print(f'FAIL test: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_route_registers_resolved_blob_locations_for_tabular_analysis():
    """Verify the chat route registers pre-resolved blob locations for later tool calls."""
    print('Testing route registration of resolved blob locations...')

    try:
        with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
            route_content = file_handle.read()

        assert 'tabular_plugin.remember_resolved_blob_location(' in route_content, route_content

        print('PASS route registration of resolved blob locations')
        return True
    except Exception as exc:
        print(f'FAIL test: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_workbook_schema_summary_handles_trailing_space_sheet_names,
        test_sheet_selection_matches_trimmed_sheet_request,
        test_resolved_group_blob_override_survives_missing_group_id,
        test_route_registers_resolved_blob_locations_for_tabular_analysis,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)