#!/usr/bin/env python3
# test_tabular_tool_error_retry_and_thoughts.py
"""
Functional test for tabular tool-error retry and thought visibility fix.
Version: 0.239.114
Implemented in: 0.239.037

This test ensures that analytical tabular tool calls returning JSON error
payloads are treated as failed attempts, are retried instead of being accepted
as completed analysis, and surface clearer thought details for recovery.
"""

import ast
import json
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
    'get_tabular_thought_excluded_parameter_names',
    'get_tabular_invocation_result_payload',
    'get_tabular_invocation_error_message',
    'split_tabular_analysis_invocations',
    'summarize_tabular_invocation_errors',
    'filter_tabular_citation_invocations',
    'format_tabular_thought_parameter_value',
    'get_tabular_tool_thought_payloads',
    'get_tabular_status_thought_payloads',
}


def load_tabular_route_helpers():
    """Load selected helper functions from the chat route source."""
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        route_content = file_handle.read()

    parsed = ast.parse(route_content, filename=ROUTE_FILE)
    selected_nodes = []

    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {'json': json}
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, route_content


def test_tool_error_payload_is_classified_as_failed_analysis():
    """Verify JSON error payloads are treated as failed analytical tool calls."""
    print("🔍 Testing tabular tool error classification...")

    try:
        helpers, _ = load_tabular_route_helpers()
        get_error_message = helpers['get_tabular_invocation_error_message']
        split_analysis_invocations = helpers['split_tabular_analysis_invocations']
        filter_citations = helpers['filter_tabular_citation_invocations']
        failed_result_payload = json.dumps({
            'error': "aggregate_column is required unless operation='count'."
        })

        failed_invocation = SimpleNamespace(
            function_name='group_by_datetime_component',
            result=failed_result_payload,
            error_message=None,
        )

        assert get_error_message(failed_invocation) == "aggregate_column is required unless operation='count'."

        successful_invocations, failed_invocations = split_analysis_invocations([failed_invocation])
        assert len(successful_invocations) == 0, 'Did not expect a successful analytical invocation.'
        assert len(failed_invocations) == 1, 'Expected the analytical invocation to be classified as failed.'
        assert filter_citations([failed_invocation]) == [], 'Failed analytical invocations should not become citations.'

        print("✅ Tabular tool error classification passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_failed_tool_thoughts_and_recovery_status_are_rendered():
    """Verify failed analytical calls produce failed tool thoughts and recovery status thoughts."""
    print("🔍 Testing tabular failure thought payloads...")

    try:
        helpers, _ = load_tabular_route_helpers()
        get_tool_payloads = helpers['get_tabular_tool_thought_payloads']
        get_status_payloads = helpers['get_tabular_status_thought_payloads']
        failed_result_payload = json.dumps({
            'error': "aggregate_column is required unless operation='count'."
        })

        failed_invocation = SimpleNamespace(
            function_name='group_by_datetime_component',
            duration_ms=168.5,
            success=True,
            parameters={
                'filename': 'faa_flight_operations_dataset.csv',
                'datetime_component': 'hour',
                'source': 'workspace',
            },
            result=failed_result_payload,
            error_message=None,
        )

        tool_payloads = get_tool_payloads([failed_invocation])
        status_payloads = get_status_payloads([failed_invocation], analysis_succeeded=True)

        assert tool_payloads[0][0] == 'Tabular tool group_by_datetime_component on faa_flight_operations_dataset.csv (168ms) failed'
        assert "error=aggregate_column is required unless operation='count'." in tool_payloads[0][1]
        assert 'success=False' in tool_payloads[0][1]
        assert status_payloads == [(
            'Tabular analysis recovered via internal fallback after tool errors',
            "aggregate_column is required unless operation='count'."
        )], status_payloads

        print("✅ Tabular failure thought payloads passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_route_contains_retry_feedback_for_tool_errors():
    """Verify the route feeds previous tool errors back into retry attempts."""
    print("🔍 Testing route retry feedback for tool errors...")

    try:
        _, route_content = load_tabular_route_helpers()

        checks = {
            'tool error prompt feedback': 'PREVIOUS TOOL ERRORS:' in route_content,
            'tool error retry logging': 'used analytical tool(s) but all returned errors; retrying' in route_content,
            'fallback recovery thought': 'Tabular analysis recovered via internal fallback after tool errors' in route_content,
        }

        failed_checks = [name for name, passed in checks.items() if not passed]
        assert not failed_checks, f"Missing expected tool-error retry behavior: {failed_checks}"

        print("✅ Route retry feedback for tool errors passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_tool_error_payload_is_classified_as_failed_analysis,
        test_failed_tool_thoughts_and_recovery_status_are_rendered,
        test_route_contains_retry_feedback_for_tool_errors,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
