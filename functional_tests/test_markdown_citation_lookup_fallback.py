# test_markdown_citation_lookup_fallback.py
#!/usr/bin/env python3
"""
Functional test for markdown citation lookup fallback.
Version: 0.241.021
Implemented in: 0.241.021

This test ensures markdown/text citation lookups can recover the indexed
chunk when a rendered citation id is stale or incomplete but document and
chunk context is available.
"""

import ast
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_ROOT = os.path.join(ROOT_DIR, 'application', 'single_app')
ROUTE_FILE = os.path.join(SINGLE_APP_ROOT, 'route_backend_documents.py')
CHAT_CITATIONS_JS = os.path.join(SINGLE_APP_ROOT, 'static', 'js', 'chat', 'chat-citations.js')
CHAT_ENHANCED_CITATIONS_JS = os.path.join(SINGLE_APP_ROOT, 'static', 'js', 'chat', 'chat-enhanced-citations.js')
CHAT_MESSAGES_JS = os.path.join(SINGLE_APP_ROOT, 'static', 'js', 'chat', 'chat-messages.js')
CONFIG_FILE = os.path.join(SINGLE_APP_ROOT, 'config.py')
FIX_DOC = os.path.join(
    ROOT_DIR,
    'docs',
    'explanation',
    'fixes',
    'v0.241.021',
    'MARKDOWN_CITATION_LOOKUP_FIX.md',
)
TARGET_FUNCTIONS = {
    '_normalize_citation_lookup_value',
    '_append_unique_lookup_value',
    '_get_citation_id_suffix',
    '_build_citation_locator_values',
    '_build_citation_key_candidates',
    '_escape_citation_odata_literal',
    '_parse_citation_integer',
    '_build_citation_metadata_filter',
    '_as_citation_chunk_dict',
    '_first_citation_search_result',
    '_find_citation_chunk_by_metadata',
    '_resolve_citation_chunk',
}


class FakeResourceNotFoundError(Exception):
    """Test replacement for Azure ResourceNotFoundError."""


class FakeSearchClient:
    def __init__(self, documents):
        self.documents = documents
        self.get_calls = []
        self.search_calls = []

    def get_document(self, key):
        self.get_calls.append(key)
        if key not in self.documents:
            raise FakeResourceNotFoundError(key)
        return self.documents[key]

    def search(self, search_text, filter, top):
        self.search_calls.append({
            'search_text': search_text,
            'filter': filter,
            'top': top,
        })

        for document in self.documents.values():
            if document.get('document_id') not in filter:
                continue

            chunk_id = str(document.get('chunk_id'))
            page_number = str(document.get('page_number'))
            chunk_sequence = str(document.get('chunk_sequence'))

            if (
                f"chunk_id eq '{chunk_id}'" in filter
                or f'page_number eq {page_number}' in filter
                or f'chunk_sequence eq {chunk_sequence}' in filter
            ):
                return [document]

        return []


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.strip().startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def load_citation_helpers():
    source = read_file_text(ROUTE_FILE)
    parsed = ast.parse(source, filename=ROUTE_FILE)
    selected_nodes = [
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS
    ]

    found_names = {node.name for node in selected_nodes}
    missing_names = TARGET_FUNCTIONS - found_names
    assert not missing_names, f'Missing citation helper functions: {sorted(missing_names)}'

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {'ResourceNotFoundError': FakeResourceNotFoundError}
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace


def test_citation_key_candidates_use_document_context():
    """Verify malformed citation ids can be rebuilt from document context."""
    print('🔍 Testing citation key candidate recovery...')

    namespace = load_citation_helpers()
    build_candidates = namespace['_build_citation_key_candidates']

    candidates = build_candidates(
        '1_1',
        document_id='doc-md-123',
        page_number='1',
        chunk_id='1',
    )

    assert candidates[0] == '1_1'
    assert 'doc-md-123_1' in candidates
    assert candidates.count('doc-md-123_1') == 1

    print('✅ Citation key candidate recovery passed')


def test_resolve_citation_chunk_recovers_markdown_chunk_from_document_context():
    """Verify a stale rendered id falls back to the markdown chunk key."""
    print('🔍 Testing markdown chunk lookup by reconstructed key...')

    namespace = load_citation_helpers()
    resolve_chunk = namespace['_resolve_citation_chunk']
    expected_chunk = {
        'id': 'doc-md-123_1',
        'document_id': 'doc-md-123',
        'chunk_id': '1',
        'page_number': 1,
        'chunk_sequence': 1,
        'chunk_text': '# Release notes\nMarkdown content',
        'file_name': 'release-notes.md',
    }
    search_client = FakeSearchClient({'doc-md-123_1': expected_chunk})

    resolved_chunk = resolve_chunk(
        search_client,
        '1_1',
        document_id='doc-md-123',
        page_number='1',
        chunk_id='1',
    )

    assert resolved_chunk == expected_chunk
    assert search_client.get_calls == ['1_1', 'doc-md-123_1']
    assert search_client.search_calls == []

    print('✅ Markdown chunk lookup by reconstructed key passed')


def test_resolve_citation_chunk_queries_metadata_when_keys_miss():
    """Verify metadata lookup handles legacy chunk keys that do not match document_page."""
    print('🔍 Testing markdown chunk metadata query fallback...')

    namespace = load_citation_helpers()
    resolve_chunk = namespace['_resolve_citation_chunk']
    expected_chunk = {
        'id': 'legacy-md-alpha',
        'document_id': 'doc-md-456',
        'chunk_id': '2',
        'page_number': 2,
        'chunk_sequence': 2,
        'chunk_text': 'Legacy markdown chunk',
        'file_name': 'guide.md',
    }
    search_client = FakeSearchClient({'legacy-md-alpha': expected_chunk})

    resolved_chunk = resolve_chunk(
        search_client,
        'wrong_2',
        document_id='doc-md-456',
        page_number='2',
        chunk_id='2',
    )

    assert resolved_chunk == expected_chunk
    assert search_client.search_calls, 'Expected metadata search fallback to run'
    filter_expression = search_client.search_calls[0]['filter']
    assert "document_id eq 'doc-md-456'" in filter_expression
    assert "chunk_id eq '2'" in filter_expression
    assert 'page_number eq 2' in filter_expression
    assert 'chunk_sequence eq 2' in filter_expression

    print('✅ Markdown chunk metadata query fallback passed')


def test_browser_sends_citation_context_to_backend():
    """Verify citation buttons preserve enough context for markdown lookup recovery."""
    print('🔍 Testing browser citation context payload wiring...')

    chat_citations_source = read_file_text(CHAT_CITATIONS_JS)
    chat_enhanced_source = read_file_text(CHAT_ENHANCED_CITATIONS_JS)
    chat_messages_source = read_file_text(CHAT_MESSAGES_JS)

    required_snippets = [
        'export function fetchCitedText(citationId, citationContext = {})',
        'requestPayload.document_id = documentId;',
        'requestPayload.page_number = pageNumber;',
        'requestPayload.chunk_id = chunkId;',
        'const citationContext = {',
        'fetchCitedText(citationId, citationContext);',
        'module.fetchCitedText(citationId, {',
        'function resolveHybridCitationId(cite, index)',
        'return `${documentId}_${chunkLocator}`;',
        'data-chunk-id=',
        'data-page-number=',
    ]
    combined_source = '\n'.join([
        chat_citations_source,
        chat_enhanced_source,
        chat_messages_source,
    ])
    missing = [snippet for snippet in required_snippets if snippet not in combined_source]
    assert not missing, f'Missing browser citation context snippets: {missing}'

    print('✅ Browser citation context payload wiring passed')


def test_version_and_fix_documentation_alignment():
    """Verify version and documentation are aligned with this fix."""
    print('🔍 Testing version and fix documentation alignment...')

    fix_doc_content = read_file_text(FIX_DOC)

    assert read_config_version() == '0.241.021'
    assert 'Fixed/Implemented in version: **0.241.021**' in fix_doc_content
    assert 'markdown citation' in fix_doc_content.lower()
    assert 'application/single_app/route_backend_documents.py' in fix_doc_content

    print('✅ Version and fix documentation alignment passed')


if __name__ == '__main__':
    tests = [
        test_citation_key_candidates_use_document_context,
        test_resolve_citation_chunk_recovers_markdown_chunk_from_document_context,
        test_resolve_citation_chunk_queries_metadata_when_keys_miss,
        test_browser_sends_citation_context_to_backend,
        test_version_and_fix_documentation_alignment,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'❌ Test failed: {exc}')
            results.append(False)

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)