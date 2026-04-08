#!/usr/bin/env python3
# test_tabular_preview_json_sanitization_fix.py
"""
Functional test for tabular preview JSON sanitization.
Version: 0.240.030
Implemented in: 0.240.030

This test ensures the enhanced citation tabular preview converts pandas null-like
values into JSON-safe strings so browser preview loading does not fail on NaN.
"""

import ast
import math
import os
import sys

import pandas as pd


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'route_enhanced_citations.py',
)
CONFIG_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'config.py',
)
TARGET_FUNCTIONS = {
    '_sanitize_tabular_preview_value',
    '_serialize_tabular_preview_table',
}


def load_preview_helpers():
    """Load tabular preview helpers from the route source without importing the app."""
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        source = file_handle.read()

    parsed = ast.parse(source, filename=ROUTE_FILE)
    selected_nodes = []
    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {
        'pandas': pd,
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


def test_preview_value_sanitizer_returns_json_safe_strings():
    """Verify null-like and datetime preview values become safe display strings."""
    print('🔍 Testing tabular preview value sanitizer...')

    try:
        helpers, _ = load_preview_helpers()
        sanitize_value = helpers['_sanitize_tabular_preview_value']

        assert sanitize_value(float('nan')) == ''
        assert sanitize_value(pd.NA) == ''
        assert sanitize_value(pd.NaT) == ''
        assert sanitize_value(pd.Timestamp('2025-01-02 03:04:05')) == '2025-01-02T03:04:05'
        assert sanitize_value(42) == '42'

        print('✅ Tabular preview value sanitizer passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_preview_table_serializer_replaces_blank_headers_and_nan_cells():
    """Verify serialized preview output contains JSON-safe strings only."""
    print('🔍 Testing tabular preview table serializer...')

    try:
        helpers, _ = load_preview_helpers()
        serialize_table = helpers['_serialize_tabular_preview_table']

        preview_df = pd.DataFrame(
            [
                ['Status', float('nan')],
                [pd.Timestamp('2024-02-03 04:05:06'), 5],
            ],
            columns=['Column A', math.nan],
        )

        columns, rows = serialize_table(preview_df)

        assert columns == ['Column A', ''], columns
        assert rows == [
            ['Status', ''],
            ['2024-02-03T04:05:06', '5.0'],
        ], rows

        print('✅ Tabular preview table serializer passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_route_uses_serialized_preview_output_and_version_bump():
    """Verify the preview endpoint uses the sanitizer helpers and version bump."""
    print('🔍 Testing route integration and version bump...')

    try:
        _, source = load_preview_helpers()

        required_snippets = [
            'columns, rows = _serialize_tabular_preview_table(preview)',
            '"columns": columns,',
            '"rows": rows,',
        ]
        missing = [snippet for snippet in required_snippets if snippet not in source]
        assert not missing, f'Missing route integration snippets: {missing}'

        assert read_config_version() == '0.240.030'

        print('✅ Route integration and version bump passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_preview_value_sanitizer_returns_json_safe_strings,
        test_preview_table_serializer_replaces_blank_headers_and_nan_cells,
        test_route_uses_serialized_preview_output_and_version_bump,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)