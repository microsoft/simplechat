#!/usr/bin/env python3
"""
Functional test for enhanced-citation tabular schema summary fallback fix.
Version: 0.240.023
Implemented in: 0.240.023

This test ensures enhanced-citation tabular uploads stay in schema-summary mode,
use bounded summaries, and do not silently fall back to legacy row chunking.
"""

import ast
import os
import sys
import tempfile

import pandas


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'application', 'single_app'))

FUNCTIONS_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'functions_documents.py')
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
TARGET_FUNCTIONS = {
    '_compact_tabular_schema_value',
    '_compact_tabular_columns',
    '_build_compact_tabular_preview',
    '_build_minimal_tabular_summary',
    '_build_tabular_schema_summary',
}
TARGET_ASSIGNMENTS = {
    'TABULAR_SCHEMA_SUMMARY_MAX_SHEETS',
    'TABULAR_SCHEMA_SUMMARY_MAX_COLUMNS',
    'TABULAR_SCHEMA_SUMMARY_MAX_PREVIEW_ROWS',
    'TABULAR_SCHEMA_SUMMARY_MAX_CELL_CHARS',
}


def load_tabular_schema_helpers():
    """Load schema-summary helpers from the source file without importing the full app."""
    with open(FUNCTIONS_FILE, 'r', encoding='utf-8') as file_handle:
        source = file_handle.read()

    parsed = ast.parse(source, filename=FUNCTIONS_FILE)
    selected_nodes = []

    for node in parsed.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in TARGET_ASSIGNMENTS:
                    selected_nodes.append(node)
                    break
        elif isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {
        'os': os,
        'pandas': pandas,
    }
    exec(compile(module, FUNCTIONS_FILE, 'exec'), namespace)
    return namespace, source


def read_config_version():
    """Extract the current application version from config.py."""
    with open(CONFIG_FILE, 'r', encoding='utf-8') as file_handle:
        for line in file_handle:
            if line.startswith('VERSION = '):
                return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def test_bounded_csv_schema_summary():
    """Verify large tabular previews are compacted into a bounded schema summary."""
    print('🔍 Testing bounded CSV schema summary generation...')

    try:
        helpers, _ = load_tabular_schema_helpers()
        build_schema_summary = helpers['_build_tabular_schema_summary']

        dataframe = pandas.DataFrame({
            f'column_{index}': [f'value_{index}_' + ('x' * 180) for _ in range(3)]
            for index in range(30)
        })

        with tempfile.NamedTemporaryFile(delete=False, suffix='.csv') as temp_file:
            temp_path = temp_file.name

        try:
            dataframe.to_csv(temp_path, index=False)
            summary = build_schema_summary(temp_path, 'wide-tabular.csv', '.csv')
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        assert 'Tabular data file: wide-tabular.csv' in summary, summary
        assert 'This file is available for detailed analysis via the Tabular Processing plugin.' in summary, summary
        assert '... +' in summary and 'more columns' in summary, summary
        assert len(summary) < 6000, len(summary)

        print('✅ Bounded CSV schema summary generation passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_enhanced_citations_tabular_no_longer_falls_back_to_row_chunking():
    """Verify enhanced citations tabular uploads no longer revert to legacy row chunking."""
    print('🔍 Testing enhanced citations tabular fallback guard...')

    try:
        _, source = load_tabular_schema_helpers()

        assert 'if total_chunks_saved == 0 and not enable_enhanced_citations:' in source, source
        assert 'falling back to row-by-row' not in source, source
        assert 'Failed indexing enhanced tabular summary' in source, source

        print('✅ Enhanced citations tabular fallback guard passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_version_bump_applied():
    """Verify the current config version matches the implemented fix version."""
    print('🔍 Testing config version bump...')

    try:
        version = read_config_version()
        assert version == '0.240.023', version

        print('✅ Config version bump passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_bounded_csv_schema_summary,
        test_enhanced_citations_tabular_no_longer_falls_back_to_row_chunking,
        test_version_bump_applied,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)