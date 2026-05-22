#!/usr/bin/env python3
# test_advanced_conversation_search_matching_fix.py
"""
Functional test for the advanced conversation search matching fix.
Version: 0.241.097
Implemented in: 0.241.097

This test ensures that advanced conversation search uses partial matching by
default, supports explicit match modes, normalizes chat type aliases, searches
collaborative conversations, and keeps the fix documentation/version aligned.
"""

import ast
import os
import re
import sys
import traceback


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')
ROUTE_FILE = os.path.join(APP_ROOT, 'route_backend_conversations.py')
CONFIG_FILE = os.path.join(APP_ROOT, 'config.py')
FIX_DOC_FILE = os.path.join(
    REPO_ROOT,
    'docs',
    'explanation',
    'fixes',
    'ADVANCED_CONVERSATION_SEARCH_FIX.md',
)
EXPECTED_VERSION = '0.241.097'


def _read(path):
    with open(path, encoding='utf-8') as file_handle:
        return file_handle.read()


def _read_version():
    config_source = _read(CONFIG_FILE)
    version_match = re.search(r'VERSION = "([0-9.]+)"', config_source)
    if not version_match:
        raise AssertionError('VERSION assignment not found in config.py')
    return version_match.group(1)


def _load_search_helpers():
    route_source = _read(ROUTE_FILE)
    route_tree = ast.parse(route_source)
    helper_names = {
        '_build_message_search_query',
        '_conversation_matches_selected_chat_types',
        '_expand_search_chat_type_filters',
        '_get_message_query_terms',
        '_get_search_conversation_chat_type',
        '_matches_search_text',
        '_normalize_search_chat_type_value',
        '_normalize_search_match_mode',
        '_tokenize_search_terms',
    }
    constant_names = {
        'SEARCH_CHAT_TYPE_ALIASES',
        'SEARCH_MATCH_ALL_WORDS',
        'SEARCH_MATCH_ANY_WORD',
        'SEARCH_MATCH_CONTAINS',
        'SEARCH_MATCH_MODES',
        'SEARCH_MATCH_WHOLE_WORD',
    }

    selected_nodes = []
    for node in route_tree.body:
        if isinstance(node, ast.Assign):
            target_names = {
                target.id for target in node.targets
                if isinstance(target, ast.Name)
            }
            if target_names & constant_names:
                selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in helper_names:
            selected_nodes.append(node)

    loaded_functions = {
        node.name for node in selected_nodes
        if isinstance(node, ast.FunctionDef)
    }
    missing_helpers = helper_names - loaded_functions
    if missing_helpers:
        raise AssertionError(f'Missing search helpers: {sorted(missing_helpers)}')

    helper_module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(helper_module)
    namespace = {
        'GROUP_MULTI_USER_CHAT_TYPE': 'group_multi_user',
        'PERSONAL_MULTI_USER_CHAT_TYPE': 'personal_multi_user',
        're': re,
    }
    exec(compile(helper_module, ROUTE_FILE, 'exec'), namespace)
    return namespace


def test_partial_matching_and_modes():
    """Default matching should find text inside larger tokens."""
    print('Testing advanced search match modes...')
    helpers = _load_search_helpers()
    matches_search_text = helpers['_matches_search_text']

    if not matches_search_text('JPMorganChase earnings review', 'Chase', 'contains'):
        raise AssertionError('Contains mode should match Chase inside JPMorganChase')

    if matches_search_text('JPMorganChase earnings review', 'Chase', 'whole_word'):
        raise AssertionError('Whole-word mode should not match Chase inside JPMorganChase')

    if not matches_search_text('JP Morgan annual update for Chase', 'JP Chase', 'all_words'):
        raise AssertionError('All-words mode should match separated JP and Chase terms')

    if matches_search_text('JP Morgan annual update', 'JP Chase', 'all_words'):
        raise AssertionError('All-words mode should require every term')

    if not matches_search_text('Morgan banking update', 'JP Morgan Chase', 'any_word'):
        raise AssertionError('Any-word mode should match at least one term')

    print('  Match mode checks passed.')
    return True


def test_chat_type_alias_normalization():
    """Modal filter values must map to stored chat type values."""
    print('Testing advanced search chat type aliases...')
    helpers = _load_search_helpers()
    expand_filters = helpers['_expand_search_chat_type_filters']
    conversation_matches = helpers['_conversation_matches_selected_chat_types']

    selected_filters = expand_filters(['personal', 'group-multi-user'])
    expected_filters = {'personal_single_user', 'personal_multi_user', 'group_multi_user'}
    if not expected_filters.issubset(selected_filters):
        raise AssertionError(f'Expected aliases missing from filters: {selected_filters}')

    if not conversation_matches({'chat_type': 'personal_single_user'}, selected_filters):
        raise AssertionError('Personal filter should include personal_single_user conversations')

    if not conversation_matches({'chat_type': 'personal_multi_user'}, selected_filters):
        raise AssertionError('Personal filter should include personal_multi_user conversations')

    if not conversation_matches({'chat_type': 'group_multi_user'}, selected_filters):
        raise AssertionError('Group multi-user filter should include group_multi_user conversations')

    print('  Chat type alias checks passed.')
    return True


def test_parameterized_message_search_query():
    """Cosmos text search should use parameters instead of string interpolation."""
    print('Testing parameterized message search query...')
    helpers = _load_search_helpers()
    build_query = helpers['_build_message_search_query']

    query, parameters = build_query('Chase', 'contains')
    if 'CONTAINS(m.content, @term0, true)' not in query:
        raise AssertionError(f'Expected parameterized CONTAINS call, found: {query}')
    if 'Chase' in query:
        raise AssertionError('Search term should not be interpolated into the Cosmos query text')
    if parameters != [{'name': '@term0', 'value': 'Chase'}]:
        raise AssertionError(f'Unexpected query parameters: {parameters}')

    print('  Parameterized query checks passed.')
    return True


def test_route_contract_includes_collaboration_and_titles():
    """The advanced route must search collaboration stores and title matches."""
    print('Testing route collaboration/title search contract...')
    route_source = _read(ROUTE_FILE)

    required_fragments = [
        '_load_accessible_collaboration_search_conversations(user_id)',
        'cosmos_collaboration_messages_container',
        "'title_match': title_match",
        'match_mode = _normalize_search_match_mode',
    ]
    missing_fragments = [fragment for fragment in required_fragments if fragment not in route_source]
    if missing_fragments:
        raise AssertionError(f'Missing advanced search route fragments: {missing_fragments}')

    unsafe_fragment = "CONTAINS(m.content, '{search_term}'"
    if unsafe_fragment in route_source:
        raise AssertionError('Route still contains interpolated Cosmos search text')

    print('  Route contract checks passed.')
    return True


def test_version_and_fix_documentation_alignment():
    """Config version and fix documentation must stay aligned."""
    print('Testing version and fix documentation alignment...')
    version = _read_version()
    fix_doc_source = _read(FIX_DOC_FILE)

    if version != EXPECTED_VERSION:
        raise AssertionError(f'Expected config VERSION to be {EXPECTED_VERSION}, found {version}')
    if f'Fixed/Implemented in version: **{EXPECTED_VERSION}**' not in fix_doc_source:
        raise AssertionError('Fix documentation is missing the implemented version section')
    if 'config.py' not in fix_doc_source:
        raise AssertionError('Fix documentation must reference the config.py version update')

    print('  Version and documentation checks passed.')
    return True


if __name__ == '__main__':
    tests = [
        test_partial_matching_and_modes,
        test_chat_type_alias_normalization,
        test_parameterized_message_search_query,
        test_route_contract_includes_collaboration_and_titles,
        test_version_and_fix_documentation_alignment,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            results.append(test())
        except Exception as exc:
            print(f'  FAILED: {exc}')
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    total = len(results)
    print(f'\nResults: {passed}/{total} tests passed')
    sys.exit(0 if all(results) else 1)