#!/usr/bin/env python3
# test_tabular_multisheet_tool_start_guidance.py
"""
Functional test for multi-sheet tabular discovery iteration.
Version: 0.240.034
Implemented in: 0.240.034

This test ensures multi-sheet workbook analysis can start with generic workbook
discovery, carry discovery summaries into retries, and still require
analytical tool calls before the analysis is considered complete.
"""

import ast
import os
import sys
from types import SimpleNamespace


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
TARGET_FUNCTIONS = {
    'is_tabular_schema_summary_question',
    'is_tabular_entity_lookup_question',
    'get_tabular_execution_mode',
    'get_tabular_invocation_result_payload',
    'get_tabular_invocation_error_message',
    'summarize_tabular_discovery_invocations',
}


def load_route_helpers():
    """Load selected helpers from the chat route source without importing the full app."""
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        source = file_handle.read()

    parsed = ast.parse(source, filename=ROUTE_FILE)
    selected_nodes = []
    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {
        'json': __import__('json'),
        're': __import__('re'),
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


def test_identifier_led_return_question_routes_to_entity_lookup_mode():
    """Verify generic identifier-led workbook questions still use entity lookup mode."""
    print('🔍 Testing generic identifier-led entity lookup routing...')

    helpers, _ = load_route_helpers()
    question = 'For return RET000123, explain why the refund amount changed after withholding and estimated payments were applied.'

    assert helpers['is_tabular_entity_lookup_question'](question), question
    assert helpers['get_tabular_execution_mode'](question) == 'entity_lookup', question

    print('✅ Generic identifier-led entity lookup routing passed')
    return True


def test_discovery_summaries_are_compact_and_generic():
    """Verify discovery retry summaries stay workbook-level and avoid content targeting."""
    print('🔍 Testing compact discovery summaries...')

    helpers, _ = load_route_helpers()
    summarize_discovery = helpers['summarize_tabular_discovery_invocations']

    invocation = SimpleNamespace(
        function_name='describe_tabular_file',
        error_message=None,
        result='''{
  "filename": "irs_treasury_multi_tab_workbook.xlsx",
  "is_workbook": true,
  "sheet_count": 11,
  "sheet_names": ["Taxpayers", "TaxReturns", "W2Forms", "Form1099Income"],
  "relationship_hints": [{"from_sheet": "Taxpayers", "to_sheet": "TaxReturns"}]
}''',
    )

    summaries = summarize_discovery([invocation])

    assert summaries == [
        'irs_treasury_multi_tab_workbook.xlsx; sheet_count=11; sheets=Taxpayers, TaxReturns, W2Forms, Form1099Income; relationship_hints=1'
    ], summaries

    print('✅ Compact discovery summaries passed')
    return True


def test_route_uses_generic_multisheet_discovery_iteration_and_version_bump():
    """Verify the route uses generic discovery iteration for multi-sheet workbooks."""
    print('🔍 Testing generic multi-sheet discovery iteration guidance...')

    _, source = load_route_helpers()

    required_snippets = [
        'Workbook discovery is available through describe_tabular_file.',
        'Discovery-only results do NOT complete the analysis.',
        'call describe_tabular_file without sheet_name as an exploration step',
        'previous_discovery_feedback_messages = []',
        'Previous attempt explored workbook structure but did not execute analytical functions. Continue with analytical tool calls now.',
        'analysis_requires_immediate_tool_choice = has_multi_sheet_workbook and not schema_summary_mode',
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f'Missing route discovery-iteration snippets: {missing}'
    assert read_config_version() == '0.240.034'

    print('✅ Generic multi-sheet discovery iteration guidance passed')
    return True


if __name__ == '__main__':
    tests = [
        test_identifier_led_return_question_routes_to_entity_lookup_mode,
        test_discovery_summaries_are_compact_and_generic,
        test_route_uses_generic_multisheet_discovery_iteration_and_version_bump,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)