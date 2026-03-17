#!/usr/bin/env python3
# test_tabular_multisheet_workbook_support.py
"""
Functional test for multi-sheet workbook analytical orchestration fix.
Version: 0.239.114
Implemented in: 0.239.111

This test ensures that multi-sheet workbook analysis can select the likely
worksheet, use lookup_value for row-and-column retrieval, and constrain the
tabular SK pass to analytical tools.
"""

import ast
import asyncio
import importlib.util
import json
import os
import re
import sys

import pandas as pd


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'application', 'single_app'))

ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
PLUGIN_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'semantic_kernel_plugins',
    'tabular_processing_plugin.py',
)

TARGET_ASSIGNMENTS = {
}
TARGET_FUNCTIONS = {
    'get_tabular_analysis_function_names',
    '_normalize_tabular_sheet_token',
    '_tokenize_tabular_sheet_text',
    '_select_likely_workbook_sheet',
}


def load_tabular_route_helpers():
    """Load selected constants and helpers from the chat route source."""
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        route_content = file_handle.read()

    parsed = ast.parse(route_content, filename=ROUTE_FILE)
    selected_nodes = []

    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {'re': re}
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, route_content


PLUGIN_SPEC = importlib.util.spec_from_file_location('tabular_processing_plugin', PLUGIN_FILE)
PLUGIN_MODULE = importlib.util.module_from_spec(PLUGIN_SPEC)
PLUGIN_SPEC.loader.exec_module(PLUGIN_MODULE)
TabularProcessingPlugin = PLUGIN_MODULE.TabularProcessingPlugin


def build_mock_workbook_plugin():
    """Create a plugin backed by in-memory workbook frames."""
    plugin = TabularProcessingPlugin()
    container_name = 'mock-container'
    blob_name = 'Family Finances.xlsx'
    workbook_frames = {
        'Balance': pd.DataFrame({
            'Accounts': ['Cash', 'Total Monthly Expenses'],
            'Nov-25': ['2500.00', '7400.12'],
        }),
        'Assets': pd.DataFrame({
            'Accounts': ['Checking', 'Total Assets'],
            'Nov-25': ['1500.00', '481225.18'],
        }),
    }
    workbook_metadata = {
        'is_workbook': True,
        'sheet_names': ['Balance', 'Assets'],
        'sheet_count': 2,
        'default_sheet': 'Balance',
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


def test_lookup_value_returns_target_value_from_assets_sheet():
    """Verify lookup_value returns the requested period value from the selected sheet."""
    print('Testing lookup_value on explicit worksheet...')

    try:
        plugin, _, _ = build_mock_workbook_plugin()
        result_json = asyncio.run(plugin.lookup_value(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='Family Finances.xlsx',
            lookup_column='Accounts',
            lookup_value='Total Assets',
            target_column='Nov-25',
            sheet_name='Assets',
            source='workspace',
        ))
        payload = json.loads(result_json)

        assert 'error' not in payload, f"Unexpected error payload: {payload}"
        assert payload['selected_sheet'] == 'Assets', payload
        assert payload['value'] == 481225.18, payload
        assert payload['total_matches'] == 1, payload

        print('PASS lookup_value explicit worksheet')
        return True

    except Exception as exc:
        print(f'FAIL test: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_default_sheet_override_allows_lookup_without_sheet_argument():
    """Verify a likely-sheet override satisfies analytical calls that omit sheet_name."""
    print('Testing lookup_value default-sheet override...')

    try:
        plugin, container_name, blob_name = build_mock_workbook_plugin()

        initial_payload = json.loads(asyncio.run(plugin.lookup_value(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='Family Finances.xlsx',
            lookup_column='Accounts',
            lookup_value='Total Assets',
            target_column='Nov-25',
            source='workspace',
        )))
        assert 'Specify sheet_name or sheet_index on analytical calls.' in initial_payload.get('error', ''), initial_payload

        plugin.set_default_sheet(container_name, blob_name, 'Assets')
        override_payload = json.loads(asyncio.run(plugin.lookup_value(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='Family Finances.xlsx',
            lookup_column='Accounts',
            lookup_value='Total Assets',
            target_column='Nov-25',
            source='workspace',
        )))

        assert 'error' not in override_payload, override_payload
        assert override_payload['selected_sheet'] == 'Assets', override_payload
        assert override_payload['value'] == 481225.18, override_payload

        print('PASS lookup_value default-sheet override')
        return True

    except Exception as exc:
        print(f'FAIL test: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_likely_sheet_helper_handles_pluralized_question_text():
    """Verify likely-sheet selection matches singular question terms to plural sheet names."""
    print('Testing likely-sheet helper...')

    try:
        helpers, _ = load_tabular_route_helpers()
        select_likely_sheet = helpers['_select_likely_workbook_sheet']
        analytical_functions = helpers['get_tabular_analysis_function_names']()

        likely_sheet = select_likely_sheet(
            ['Balance', 'Budget', 'Assets', 'Liabilities'],
            'what were our asset values for nov 2025?',
        )

        assert 'lookup_value' in analytical_functions, analytical_functions
        assert likely_sheet == 'Assets', likely_sheet

        print('PASS likely-sheet helper')
        return True

    except Exception as exc:
        print(f'FAIL test: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_route_uses_analytical_filters_and_lookup_guidance():
    """Verify the route prompt and execution settings match the analytical-only design."""
    print('Testing route analytical-only orchestration text...')

    try:
        _, route_content = load_tabular_route_helpers()

        checks = {
            'lookup_value is advertised first': 'AVAILABLE FUNCTIONS: lookup_value' in route_content,
            'discovery tools are disabled for analysis': 'Discovery functions are not available in this analysis run because schema context is already pre-loaded.' in route_content,
            'prompt includes likely worksheet hints': 'LIKELY WORKSHEET HINTS:' in route_content,
            'analysis function filters are configured': 'included_functions' in route_content,
            'retry attempts require analytical function use': 'FunctionChoiceBehavior.Required(' in route_content,
            'likely sheet override is applied': 'tabular_plugin.set_default_sheet(container, blob_path, likely_sheet)' in route_content,
        }

        failed_checks = [name for name, passed in checks.items() if not passed]
        assert not failed_checks, f"Missing expected orchestration behavior: {failed_checks}"

        print('PASS route analytical-only orchestration text')
        return True

    except Exception as exc:
        print(f'FAIL test: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_lookup_value_returns_target_value_from_assets_sheet,
        test_default_sheet_override_allows_lookup_without_sheet_argument,
        test_likely_sheet_helper_handles_pluralized_question_text,
        test_route_uses_analytical_filters_and_lookup_guidance,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)