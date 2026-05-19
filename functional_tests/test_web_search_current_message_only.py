# test_web_search_current_message_only.py
"""
Functional test for current-message-only web search egress.
Version: 0.241.046
Implemented in: 0.241.008

This test ensures external web search uses only the current user message,
keeps history-derived internal search rewrites out of the outbound web-search
boundary, and does not send the previous Foundry identifier metadata blob.
"""

import ast
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def extract_function_source(source_text, function_name):
    parsed = ast.parse(source_text, filename=ROUTE_FILE)
    for node in ast.walk(parsed):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source_text, node)
    raise AssertionError(f'Function {function_name} not found in route_backend_chats.py')


def load_helper(function_name):
    source = read_file_text(ROUTE_FILE)
    parsed = ast.parse(source, filename=ROUTE_FILE)
    selected_nodes = [
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    ]
    assert len(selected_nodes) == 1, f'Expected helper {function_name} to exist exactly once'

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {}
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace[function_name]


def test_web_search_query_helper_uses_only_current_message():
    """Verify the outbound web-search helper only normalizes the current turn."""
    print('🔍 Testing outbound web-search query helper...')

    helper = load_helper('build_web_search_query_text')
    assert helper('  current turn only  ') == 'current turn only'
    assert helper('') == ''
    assert helper(None) == ''

    print('✅ Outbound web-search query helper passed')


def test_perform_web_search_uses_explicit_outbound_query_and_empty_metadata():
    """Verify the web-search boundary uses the explicit outbound query and no metadata blob."""
    print('🔍 Testing perform_web_search outbound boundary...')

    source = read_file_text(ROUTE_FILE)
    perform_source = extract_function_source(source, 'perform_web_search')

    assert 'web_search_query_text,' in perform_source
    assert 'query_text = (web_search_query_text or user_message or "").strip()' in perform_source
    assert 'foundry_metadata = {}' in perform_source

    metadata_block = perform_source.split('foundry_metadata = {}', 1)[1].split(
        'debug_print("[WebSearch] Foundry metadata prepared: {}")', 1
    )[0]

    forbidden_snippets = [
        '"conversation_id": conversation_id',
        '"user_id": user_id',
        '"message_id": user_message_id',
        '"chat_type": chat_type',
        '"document_scope": document_scope',
        '"group_id": active_group_id if chat_type == "group" else None',
        '"public_workspace_id": active_public_workspace_id',
        '"search_query": query_text',
    ]
    for snippet in forbidden_snippets:
        assert snippet not in metadata_block, f'Unexpected outbound metadata snippet present: {snippet}'

    print('✅ perform_web_search outbound boundary passed')


def test_chat_routes_pass_explicit_outbound_web_query():
    """Verify both chat handlers pass the dedicated outbound web-search query."""
    print('🔍 Testing chat route web-search call-site separation...')

    source = read_file_text(ROUTE_FILE)

    assert source.count('web_search_query_text = build_web_search_query_text(user_message)') >= 2
    assert source.count('web_search_query_text=web_search_query_text') >= 2
    assert 'search_query=search_query' not in source

    # Internal workspace-search rewrites still exist, but they should no longer
    # be able to flow into the outbound web-search boundary.
    assert 'search_query = rewritten_search_query' in source
    assert "Based on the recent conversation about:" in source

    print('✅ Chat route web-search call-site separation passed')


def test_search_summary_filters_out_system_messages():
    """Verify the optional search-summary branch excludes persisted system augmentation content."""
    print('🔍 Testing search-summary role filtering...')

    source = read_file_text(ROUTE_FILE)
    assert "if role not in ('user', 'assistant'):" in source
    assert "content = build_assistant_history_content_with_citations(msg, content)" in source

    print('✅ Search-summary role filtering passed')


def test_web_search_adds_foundry_citations_to_source_review_seeds():
    """Verify raw Foundry citations can seed Source Review, not only answer-text links."""
    print('🔍 Testing Foundry citation seeding for Source Review...')

    source = read_file_text(ROUTE_FILE)
    perform_source = extract_function_source(source, 'perform_web_search')
    helper_source = extract_function_source(source, '_append_source_review_web_citation')

    assert '_append_source_review_web_citation(' in perform_source
    assert "source_label='foundry_citation'" in perform_source
    assert 'normalize_review_url' in helper_source
    assert "source_label='web_search_message'" in perform_source

    print('✅ Foundry citation seeding for Source Review passed')


if __name__ == '__main__':
    tests = [
        test_web_search_query_helper_uses_only_current_message,
        test_perform_web_search_uses_explicit_outbound_query_and_empty_metadata,
        test_chat_routes_pass_explicit_outbound_web_query,
        test_search_summary_filters_out_system_messages,
        test_web_search_adds_foundry_citations_to_source_review_seeds,
    ]

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        test()

    print(f'\n📊 Results: {len(tests)}/{len(tests)} tests passed')
    sys.exit(0)