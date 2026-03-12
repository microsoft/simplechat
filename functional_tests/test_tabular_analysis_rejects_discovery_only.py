#!/usr/bin/env python3
# test_tabular_analysis_rejects_discovery_only.py
"""
Functional test for tabular computed analysis enforcement fix.
Version: 0.239.034
Implemented in: 0.239.034

This test ensures that discovery-only tabular tool calls such as
`describe_tabular_file` are not accepted as completed analysis for analytical
questions, and that citation filtering prefers computed tabular operations.
"""

import ast
import os
import sys
from types import SimpleNamespace

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
TARGET_ASSIGNMENTS = {
    'TABULAR_DISCOVERY_FUNCTION_NAMES',
    'TABULAR_ANALYSIS_FUNCTION_NAMES',
}
TARGET_FUNCTIONS = {
    'get_new_plugin_invocations',
    'split_tabular_plugin_invocations',
    'filter_tabular_citation_invocations',
}


def load_tabular_route_helpers():
    """Load selected constants and helpers from the chat route source."""
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        route_content = file_handle.read()

    parsed = ast.parse(route_content, filename=ROUTE_FILE)
    selected_nodes = []

    for node in parsed.body:
        if isinstance(node, ast.Assign):
            target_names = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if target_names & TARGET_ASSIGNMENTS:
                selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {}
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, route_content


def test_discovery_only_calls_trigger_retry_guardrails():
    """Verify discovery-only tool use is explicitly rejected in the route logic."""
    print("🔍 Testing discovery-only retry guardrails...")

    try:
        _, route_content = load_tabular_route_helpers()

        checks = {
            'prompt rejects discovery-only calls': 'Calls to list_tabular_files or describe_tabular_file do not count as analysis and will be rejected.' in route_content,
            'retry logging mentions discovery tools': 'used only discovery tool(s)' in route_content,
            'success logging counts analytical tools': 'Analysis complete via {len(analytical_invocations)} analytical tool call(s)' in route_content,
        }

        failed_checks = [name for name, passed in checks.items() if not passed]
        assert not failed_checks, f"Missing expected discovery-only guardrails: {failed_checks}"

        print("✅ Discovery-only retry guardrails passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_citation_filter_prefers_analytical_calls():
    """Verify discovery citations are removed when analytical calls also exist."""
    print("🔍 Testing analytical citation filtering...")

    try:
        helpers, _ = load_tabular_route_helpers()
        filter_invocations = helpers['filter_tabular_citation_invocations']
        split_invocations = helpers['split_tabular_plugin_invocations']

        invocations = [
            SimpleNamespace(function_name='describe_tabular_file'),
            SimpleNamespace(function_name='group_by_datetime_component'),
            SimpleNamespace(function_name='query_tabular_data'),
        ]

        discovery_invocations, analytical_invocations, other_invocations = split_invocations(invocations)
        filtered_invocations = filter_invocations(invocations)
        filtered_function_names = [invocation.function_name for invocation in filtered_invocations]

        assert len(discovery_invocations) == 1, 'Expected one discovery invocation.'
        assert len(analytical_invocations) == 2, 'Expected two analytical invocations.'
        assert len(other_invocations) == 0, 'Did not expect other invocation types.'
        assert filtered_function_names == ['group_by_datetime_component', 'query_tabular_data'], (
            f"Expected only analytical citations, got: {filtered_function_names}"
        )

        print("✅ Analytical citation filtering passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_new_invocation_slicing_supports_attempt_retries():
    """Verify retry evaluation can isolate only the invocations from the latest attempt."""
    print("🔍 Testing new invocation slicing...")

    try:
        helpers, _ = load_tabular_route_helpers()
        get_new_invocations = helpers['get_new_plugin_invocations']

        invocations = [
            SimpleNamespace(function_name='describe_tabular_file'),
            SimpleNamespace(function_name='group_by_datetime_component'),
            SimpleNamespace(function_name='aggregate_column'),
        ]

        sliced_invocations = get_new_invocations(invocations, baseline_count=1)
        sliced_function_names = [invocation.function_name for invocation in sliced_invocations]

        assert sliced_function_names == ['group_by_datetime_component', 'aggregate_column'], (
            f"Unexpected invocation slice: {sliced_function_names}"
        )

        print("✅ New invocation slicing passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_discovery_only_calls_trigger_retry_guardrails,
        test_citation_filter_prefers_analytical_calls,
        test_new_invocation_slicing_supports_attempt_retries,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
