# test_chat_citation_page_sort_fix.py
"""
Functional test for mixed citation page sorting.
Version: 0.240.055
Implemented in: 0.240.055

This test ensures hybrid citations with numeric pages and text labels such as
Metadata or AI Vision sort deterministically in both standard and streaming
chat paths without raising mixed-type comparison errors.
"""

import ast
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
FIX_DOC = os.path.join(
    ROOT_DIR,
    'docs',
    'explanation',
    'fixes',
    'CHAT_CITATION_PAGE_SORT_FIX.md',
)
TARGET_FUNCTIONS = {
    '_coerce_citation_sort_number',
    '_build_hybrid_citation_sort_key',
}


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def load_sort_helpers():
    source = read_file_text(ROUTE_FILE)
    parsed = ast.parse(source, filename=ROUTE_FILE)
    selected_nodes = [
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS
    ]
    assert len(selected_nodes) == len(TARGET_FUNCTIONS), (
        f'Expected helpers {sorted(TARGET_FUNCTIONS)}, '
        f'found {[node.name for node in selected_nodes]}'
    )

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {}
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, source


def test_citation_sort_number_parsing():
    """Verify page and chunk sort values normalize safely."""
    print('🔍 Testing citation sort number parsing...')

    namespace, _ = load_sort_helpers()
    coerce_sort_number = namespace['_coerce_citation_sort_number']

    assert coerce_sort_number(12) == 12.0
    assert coerce_sort_number('7') == 7.0
    assert coerce_sort_number(' 3.5 ') == 3.5
    assert coerce_sort_number('Metadata') is None
    assert coerce_sort_number('AI Vision') is None
    assert coerce_sort_number('') is None
    assert coerce_sort_number(None) is None

    print('✅ Citation sort number parsing passed')
    return True


def test_mixed_page_and_metadata_citations_sort_stably():
    """Verify mixed numeric and text page labels sort without type errors."""
    print('🔍 Testing mixed citation sort order...')

    namespace, _ = load_sort_helpers()
    build_sort_key = namespace['_build_hybrid_citation_sort_key']

    citations = [
        {'file_name': 'Policy.pdf', 'page_number': 2, 'chunk_sequence': 2},
        {'file_name': 'Policy.pdf', 'page_number': 'Metadata', 'chunk_sequence': 9999, 'metadata_type': 'keywords'},
        {'file_name': 'Policy.pdf', 'page_number': 'AI Vision', 'chunk_sequence': 9997, 'metadata_type': 'vision'},
        {'file_name': 'Policy.pdf', 'page_number': '12', 'chunk_sequence': 12},
        {'file_name': 'Policy.pdf', 'page_number': 7, 'chunk_sequence': 7},
        {'file_name': 'Policy.pdf', 'page_number': None, 'chunk_sequence': None},
    ]

    sorted_citations = sorted(citations, key=build_sort_key, reverse=True)

    assert [citation.get('page_number') for citation in sorted_citations] == [
        '12',
        7,
        2,
        'Metadata',
        'AI Vision',
        None,
    ], sorted_citations

    print('✅ Mixed citation sort order passed')
    return True


def test_route_uses_shared_sort_helper_for_standard_and_streaming_paths():
    """Verify both retrieval paths use the shared mixed-page citation sort helper."""
    print('🔍 Testing shared citation sort helper wiring...')

    _, route_source = load_sort_helpers()

    assert route_source.count('hybrid_citations_list.sort(key=_build_hybrid_citation_sort_key, reverse=True)') == 2
    assert "lambda x: x.get('page_number', 0)" not in route_source
    assert 'def _build_hybrid_citation_sort_key(citation):' in route_source

    print('✅ Shared citation sort helper wiring passed')
    return True


def test_version_and_fix_documentation_alignment():
    """Verify version bump and fix documentation stay aligned."""
    print('🔍 Testing version and fix documentation alignment...')

    fix_doc_content = read_file_text(FIX_DOC)

    assert read_config_version() == '0.240.055'
    assert 'Fixed/Implemented in version: **0.240.055**' in fix_doc_content
    assert 'mixed numeric and text page labels' in fix_doc_content.lower()
    assert 'application/single_app/route_backend_chats.py' in fix_doc_content

    print('✅ Version and fix documentation alignment passed')
    return True


if __name__ == '__main__':
    tests = [
        test_citation_sort_number_parsing,
        test_mixed_page_and_metadata_citations_sort_stably,
        test_route_uses_shared_sort_helper_for_standard_and_streaming_paths,
        test_version_and_fix_documentation_alignment,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)