#!/usr/bin/env python3
# test_tabular_multi_file_distinct_url_union.py
"""
Functional test for deterministic multi-file tabular distinct URL unions.
Version: 0.240.052
Implemented in: 0.240.052

This test ensures multi-file SharePoint/site questions can bypass the LLM
planner, pick a URL/location-style column per workbook, and union exact
distinct values across multiple tabular files before the final model response.
"""

import ast
import json
import os
import re
import sys
from typing import Mapping


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
TARGET_FUNCTIONS = {
    'build_multi_file_tabular_distinct_value_analysis',
    'dedupe_tabular_file_contexts',
    'get_multi_file_tabular_analysis_mode',
    'is_tabular_distinct_url_question',
    'normalize_multi_file_tabular_distinct_value',
    'parse_tabular_result_count',
    'score_tabular_distinct_url_column',
    'select_tabular_distinct_url_column',
    'select_tabular_distinct_url_sheet_and_column',
}


def load_helpers():
    """Load targeted multi-file tabular helpers without importing the full app."""
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        source = file_handle.read()

    parsed = ast.parse(source, filename=ROUTE_FILE)
    selected_nodes = []
    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {
        'json': json,
        'Mapping': Mapping,
        're': re,
    }
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, source


def read_config_version():
    """Extract the current application version from config.py."""
    with open(CONFIG_FILE, 'r', encoding='utf-8') as file_handle:
        for line in file_handle:
            if line.startswith('VERSION = '):
                return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def test_multi_file_mode_only_applies_to_multi_file_analysis_questions():
    """Verify deterministic mode only activates for multi-file analysis questions."""
    print('🔍 Testing multi-file mode detection...')

    helpers, _ = load_helpers()
    get_mode = helpers['get_multi_file_tabular_analysis_mode']

    single_file_mode = get_mode(
        'How many discrete SharePoint sites appear in CCO locations?',
        execution_mode='analysis',
        analysis_file_contexts=[{'file_name': 'one.xlsx', 'source_hint': 'group'}],
    )
    schema_summary_mode = get_mode(
        'How many discrete SharePoint sites appear in CCO locations?',
        execution_mode='schema_summary',
        analysis_file_contexts=[
            {'file_name': 'one.xlsx', 'source_hint': 'group'},
            {'file_name': 'two.xlsx', 'source_hint': 'group'},
        ],
    )
    multi_file_mode = get_mode(
        'How many discrete SharePoint sites appear in CCO locations?',
        execution_mode='analysis',
        analysis_file_contexts=[
            {'file_name': 'one.xlsx', 'source_hint': 'group'},
            {'file_name': 'two.xlsx', 'source_hint': 'group'},
        ],
    )

    assert single_file_mode is None, single_file_mode
    assert schema_summary_mode is None, schema_summary_mode
    assert multi_file_mode == 'distinct_url_union', multi_file_mode

    print('✅ Multi-file mode detection passed')
    return True


def test_sheet_and_column_selection_prefers_location_like_columns():
    """Verify deterministic selection can find the right sheet even when tab names differ."""
    print('🔍 Testing deterministic sheet/column selection...')

    helpers, _ = load_helpers()
    select_sheet_and_column = helpers['select_tabular_distinct_url_sheet_and_column']

    schema_info = {
        'is_workbook': True,
        'sheet_names': ['Overview', 'Licensing'],
        'per_sheet_schemas': {
            'Overview': {
                'row_count': 42,
                'columns': ['Category', 'Owner', 'Status'],
            },
            'Licensing': {
                'row_count': 13,
                'columns': ['Business Unit', 'Location', 'Disposition'],
            },
        },
    }

    selected_sheet, selected_column = select_sheet_and_column(schema_info)

    assert selected_sheet == 'Licensing', (selected_sheet, selected_column)
    assert selected_column == 'Location', (selected_sheet, selected_column)

    print('✅ Deterministic sheet/column selection passed')
    return True


def test_multi_file_distinct_value_analysis_unions_and_dedupes_values():
    """Verify per-file results are unioned into one exact distinct value list."""
    print('🔍 Testing multi-file distinct value union...')

    helpers, _ = load_helpers()
    build_analysis = helpers['build_multi_file_tabular_distinct_value_analysis']

    analysis = json.loads(build_analysis([
        {
            'filename': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
            'selected_sheet': 'Legal',
            'column': 'Location',
            'distinct_count': 2,
            'returned_values': 2,
            'values': [
                'http://share/sites/CCO/default.aspx',
                'https://occtreasgovprod.sharepoint.com/sites/LIC',
            ],
        },
        {
            'filename': 'CCO-Licensing File Plan 2025_Final Approved.xlsx',
            'selected_sheet': 'Licensing',
            'column': 'Location',
            'distinct_count': 2,
            'returned_values': 2,
            'values': [
                'https://occtreasgovprod.sharepoint.com/sites/LIC',
                'http://share/sites/CC/LICA/default.aspx',
            ],
        },
    ]))

    assert analysis['analysis_type'] == 'multi_file_distinct_url_union', analysis
    assert analysis['files_requested'] == 2, analysis
    assert analysis['files_analyzed'] == 2, analysis
    assert analysis['distinct_count'] == 3, analysis
    assert analysis['returned_values'] == 3, analysis
    assert analysis['values'] == [
        'http://share/sites/CC/LICA/default.aspx',
        'http://share/sites/CCO/default.aspx',
        'https://occtreasgovprod.sharepoint.com/sites/LIC',
    ], analysis

    print('✅ Multi-file distinct value union passed')
    return True


def test_route_uses_multi_file_tabular_wrapper_and_version_bump():
    """Verify the route now routes tabular execution through the multi-file-aware wrapper."""
    print('🔍 Testing multi-file wrapper route wiring...')

    _, source = load_helpers()

    required_snippets = [
        'MULTI_FILE_TABULAR_DISTINCT_URL_EXTRACT_PATTERN',
        'def get_multi_file_tabular_analysis_mode(',
        'def run_multi_file_tabular_distinct_url_analysis(',
        'def run_tabular_analysis_with_multi_file_support(',
        'workspace_tabular_file_contexts = collect_workspace_tabular_file_contexts(',
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f'Missing multi-file tabular snippets: {missing}'
    assert source.count('asyncio.run(run_tabular_analysis_with_multi_file_support(') == 4, source
    assert read_config_version() == '0.240.052'

    print('✅ Multi-file wrapper route wiring passed')
    return True


if __name__ == '__main__':
    tests = [
        test_multi_file_mode_only_applies_to_multi_file_analysis_questions,
        test_sheet_and_column_selection_prefers_location_like_columns,
        test_multi_file_distinct_value_analysis_unions_and_dedupes_values,
        test_route_uses_multi_file_tabular_wrapper_and_version_bump,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)