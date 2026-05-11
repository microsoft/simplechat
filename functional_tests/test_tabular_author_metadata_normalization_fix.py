# test_tabular_author_metadata_normalization_fix.py
"""
Functional test for tabular author metadata normalization.
Version: 0.240.028
Implemented in: 0.240.028

This test ensures tabular schema-summary indexing normalizes author metadata
before Azure AI Search upload so null or blank author entries do not break
enhanced citation processing.
"""

import ast
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNCTIONS_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'functions_documents.py')
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
TARGET_FUNCTIONS = {
    'ensure_list',
}


def load_helpers():
    """Load targeted helpers from functions_documents.py without importing the full app."""
    with open(FUNCTIONS_FILE, 'r', encoding='utf-8') as file_handle:
        source = file_handle.read()

    parsed = ast.parse(source, filename=FUNCTIONS_FILE)
    selected_nodes = []
    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {
        're': __import__('re'),
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


def test_ensure_list_filters_null_and_blank_author_values():
    """Verify ensure_list removes invalid author entries that would break search indexing."""
    print('🔍 Testing author list normalization...')

    try:
        helpers, _ = load_helpers()
        ensure_list = helpers['ensure_list']

        normalized = ensure_list([None, '  Alice  ', '', 'Bob', '   '])
        assert normalized == ['Alice', 'Bob'], normalized

        normalized_scalar = ensure_list('Alice; ; Bob,  ')
        assert normalized_scalar == ['Alice', 'Bob'], normalized_scalar

        print('✅ Author list normalization passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_tabular_chunk_indexing_uses_normalized_authors_everywhere():
    """Verify author normalization is applied to carried metadata and chunk uploads."""
    print('🔍 Testing tabular author normalization integration points...')

    try:
        _, source = load_helpers()

        required_snippets = [
            '"authors": ensure_list(document_item.get("authors"))',
            "'authors': []",
            '"authors": ensure_list(carried_forward.get("authors"))',
            "author = ensure_list(metadata.get('authors')) if metadata else []",
            "chunk_updates['author'] = ensure_list(existing_document.get('authors'))",
            "chunk_item[field] = ensure_list(kwargs[field])",
        ]

        missing = [snippet for snippet in required_snippets if snippet not in source]
        assert not missing, f'Missing normalization snippets: {missing}'

        print('✅ Tabular author normalization integration passed')
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
        assert version == '0.240.028', version

        print('✅ Config version bump passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_ensure_list_filters_null_and_blank_author_values,
        test_tabular_chunk_indexing_uses_normalized_authors_everywhere,
        test_version_bump_applied,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)