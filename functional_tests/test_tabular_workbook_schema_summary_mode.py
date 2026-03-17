#!/usr/bin/env python3
# test_tabular_workbook_schema_summary_mode.py
"""
Functional test for workbook schema-summary routing fix.
Version: 0.239.115
Implemented in: 0.239.115

This test ensures workbook-structure questions use schema-summary routing,
preserve describe_tabular_file citations when appropriate, and avoid fallback
prompts that demand unavailable tool calls.
"""

import ast
import os
import sys
from types import SimpleNamespace


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'application', 'single_app'))

ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
TARGET_FUNCTIONS = {
    'get_tabular_discovery_function_names',
    'get_tabular_analysis_function_names',
    'is_tabular_schema_summary_question',
    'get_tabular_execution_mode',
    'build_tabular_fallback_system_message',
    'get_tabular_invocation_result_payload',
    'get_tabular_invocation_error_message',
    'split_tabular_analysis_invocations',
    'split_tabular_plugin_invocations',
    'filter_tabular_citation_invocations',
}


def load_tabular_route_helpers():
    """Load selected helpers from the chat route source."""
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        route_content = file_handle.read()

    parsed = ast.parse(route_content, filename=ROUTE_FILE)
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
    return namespace, route_content


def test_workbook_structure_questions_route_to_schema_summary_mode():
    """Verify workbook-summary prompts are routed to schema-summary mode."""
    print('🔍 Testing workbook schema-summary intent detection...')

    try:
        helpers, _ = load_tabular_route_helpers()
        is_schema_summary_question = helpers['is_tabular_schema_summary_question']
        get_execution_mode = helpers['get_tabular_execution_mode']

        workbook_question = (
            'Summarize this workbook for me. What worksheets does it contain, '
            'what does each worksheet represent, and how are they related?'
        )
        analytical_question = 'What was the total tax withheld in 2025?'

        assert is_schema_summary_question(workbook_question), workbook_question
        assert get_execution_mode(workbook_question) == 'schema_summary', workbook_question
        assert not is_schema_summary_question(analytical_question), analytical_question
        assert get_execution_mode(analytical_question) == 'analysis', analytical_question

        print('✅ Workbook schema-summary intent detection passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_schema_summary_fallback_prompt_does_not_require_unavailable_tools():
    """Verify the outer fallback prompt no longer requires tool calls after SK failure."""
    print('🔍 Testing workbook fallback prompt behavior...')

    try:
        helpers, route_content = load_tabular_route_helpers()
        build_fallback_prompt = helpers['build_tabular_fallback_system_message']

        schema_prompt = build_fallback_prompt(
            'irs_treasury_multi_tab_workbook.xlsx',
            execution_mode='schema_summary',
        )
        analysis_prompt = build_fallback_prompt(
            'irs_treasury_multi_tab_workbook.xlsx',
            execution_mode='analysis',
        )

        assert 'answer from the schema summary only' in schema_prompt, schema_prompt
        assert 'MUST use the tabular_processing plugin functions' not in schema_prompt, schema_prompt
        assert 'could not compute tool-backed results' in analysis_prompt, analysis_prompt
        assert 'MUST use the tabular_processing plugin functions' not in analysis_prompt, analysis_prompt
        assert 'AVAILABLE FUNCTIONS: describe_tabular_file only.' in route_content, 'Schema-summary prompt should constrain tool choice.'
        assert 'build_tabular_fallback_system_message(' in route_content, 'Workspace fallback should use the shared fallback helper.'

        print('✅ Workbook fallback prompt behavior passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_schema_summary_citations_keep_describe_calls_when_they_are_the_only_successes():
    """Verify describe_tabular_file citations are preserved when they are the only successful tool calls."""
    print('🔍 Testing schema-summary citation filtering...')

    try:
        helpers, _ = load_tabular_route_helpers()
        filter_invocations = helpers['filter_tabular_citation_invocations']

        describe_only_invocations = [
            SimpleNamespace(
                function_name='describe_tabular_file',
                error_message=None,
                result='{"sheet_count": 6}',
                success=True,
            )
        ]
        filtered_describe_only = filter_invocations(describe_only_invocations)
        assert [invocation.function_name for invocation in filtered_describe_only] == ['describe_tabular_file'], filtered_describe_only

        mixed_invocations = [
            SimpleNamespace(
                function_name='describe_tabular_file',
                error_message=None,
                result='{"sheet_count": 6}',
                success=True,
            ),
            SimpleNamespace(
                function_name='lookup_value',
                error_message=None,
                result='{"value": 42}',
                success=True,
            ),
        ]
        filtered_mixed = filter_invocations(mixed_invocations)
        assert [invocation.function_name for invocation in filtered_mixed] == ['lookup_value'], filtered_mixed

        print('✅ Schema-summary citation filtering passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_workbook_structure_questions_route_to_schema_summary_mode,
        test_schema_summary_fallback_prompt_does_not_require_unavailable_tools,
        test_schema_summary_citations_keep_describe_calls_when_they_are_the_only_successes,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)