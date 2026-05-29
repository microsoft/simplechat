#!/usr/bin/env python3
# test_chat_capability_usage_metadata.py
"""
Functional test for chat capability usage metadata.
Version: 0.241.123
Implemented in: 0.241.123

This test ensures chat user and assistant message metadata explicitly track
workspace search, Analyze, Compare, Web Search, and Deep Research usage.
"""

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_BACKEND_CHATS = REPO_ROOT / 'application' / 'single_app' / 'route_backend_chats.py'
CHAT_MESSAGES_JS = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-messages.js'
CONFIG_FILE = REPO_ROOT / 'application' / 'single_app' / 'config.py'

HELPER_FUNCTIONS = {
    '_metadata_item_count',
    '_safe_metadata_int',
    '_normalize_capability_action',
    '_source_review_metadata_used',
    '_deep_research_query_count',
    '_build_capability_usage_metadata',
}


def read_text(path):
    return path.read_text(encoding='utf-8')


def load_capability_helpers():
    route_source = read_text(ROUTE_BACKEND_CHATS)
    parsed = ast.parse(route_source, filename=str(ROUTE_BACKEND_CHATS))
    selected_nodes = [
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in HELPER_FUNCTIONS
    ]
    assert len(selected_nodes) == len(HELPER_FUNCTIONS), (
        f'Expected helper functions {sorted(HELPER_FUNCTIONS)} to be present.'
    )

    module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        'DOCUMENT_ACTION_TYPE_NONE': 'none',
        'DOCUMENT_ACTION_TYPE_ANALYZE': 'analyze',
        'DOCUMENT_ACTION_TYPE_COMPARISON': 'comparison',
        'ASSIGNED_KNOWLEDGE_USER_ACTION_SEARCH': 'search',
        'ASSIGNED_KNOWLEDGE_USER_ACTION_ANALYZE': 'analyze',
        'ASSIGNED_KNOWLEDGE_USER_ACTION_COMPARE': 'compare',
    }
    exec(compile(module, str(ROUTE_BACKEND_CHATS), 'exec'), namespace)
    return namespace, route_source


def test_capability_usage_helper_tracks_search_and_research():
    helpers, _ = load_capability_helpers()
    build_metadata = helpers['_build_capability_usage_metadata']

    metadata = build_metadata(
        workspace_search_enabled=True,
        workspace_search_used=True,
        workspace_search_result_count=7,
        document_scope='group',
        selected_document_ids=['doc-1', 'doc-2'],
        active_group_ids=['group-1'],
        web_search_enabled=True,
        web_search_used=True,
        web_search_citation_count=4,
        web_search_run_count=3,
        url_access_enabled=True,
        source_review_enabled=True,
        source_review_used=True,
        deep_research_enabled=True,
        deep_research_used=True,
        deep_research_query_count=3,
    )

    assert metadata['actions'] == {
        'search': True,
        'analyze': False,
        'compare': False,
    }
    assert metadata['workspace']['action'] == 'search'
    assert metadata['workspace']['used'] is True
    assert metadata['workspace']['result_count'] == 7
    assert metadata['web_search']['enabled'] is True
    assert metadata['web_search']['used'] is True
    assert metadata['web_search']['citation_count'] == 4
    assert metadata['deep_research']['enabled'] is True
    assert metadata['deep_research']['used'] is True
    assert metadata['deep_research']['query_count'] == 3


def test_capability_usage_helper_tracks_analyze_and_compare():
    helpers, _ = load_capability_helpers()
    build_metadata = helpers['_build_capability_usage_metadata']

    analyze_metadata = build_metadata(
        document_action_type='analyze',
        document_scope='personal',
        selected_document_ids=['doc-1'],
    )
    assert analyze_metadata['actions']['analyze'] is True
    assert analyze_metadata['actions']['compare'] is False
    assert analyze_metadata['workspace']['action'] == 'analyze'
    assert analyze_metadata['workspace']['used'] is True

    compare_metadata = build_metadata(
        document_action_type='comparison',
        document_scope='public',
        selected_document_ids=['left-doc', 'right-doc'],
        active_public_workspace_ids=['public-1'],
    )
    assert compare_metadata['actions']['compare'] is True
    assert compare_metadata['actions']['analyze'] is False
    assert compare_metadata['workspace']['action'] == 'compare'
    assert compare_metadata['workspace']['selected_document_count'] == 2
    assert compare_metadata['workspace']['active_public_workspace_count'] == 1


def test_capability_usage_is_wired_to_chat_paths_and_drawer():
    _, route_source = load_capability_helpers()
    chat_messages_source = read_text(CHAT_MESSAGES_JS)
    config_source = read_text(CONFIG_FILE)

    assert 'VERSION = "0.241.123"' in config_source
    assert "user_metadata['capability_usage'] = _build_capability_usage_metadata(" in route_source
    assert "'capability_usage': assistant_capability_usage," in route_source
    assert "'capability_usage': document_action_capability_usage," in route_source
    assert "'capability_usage': build_streaming_capability_usage()," in route_source
    assert "'compare': {" in route_source
    assert "'deep_research': {" in route_source

    expected_drawer_labels = [
        'Capability Usage',
        'Search Used:',
        'Analyze Used:',
        'Compare Used:',
        'Web Search Enabled:',
        'Web Search Used:',
        'Deep Research Enabled:',
        'Deep Research Used:',
    ]
    missing_labels = [label for label in expected_drawer_labels if label not in chat_messages_source]
    assert not missing_labels, f'Missing metadata drawer labels: {missing_labels}'


if __name__ == '__main__':
    tests = [
        test_capability_usage_helper_tracks_search_and_research,
        test_capability_usage_helper_tracks_analyze_and_compare,
        test_capability_usage_is_wired_to_chat_paths_and_drawer,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            print('Passed')
            results.append(True)
        except Exception as exc:
            print(f'Failed: {exc}')
            results.append(False)

    passed = sum(results)
    total = len(results)
    print(f'\nResults: {passed}/{total} tests passed')
    sys.exit(0 if all(results) else 1)