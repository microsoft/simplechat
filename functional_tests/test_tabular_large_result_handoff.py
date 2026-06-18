#!/usr/bin/env python3
# test_tabular_large_result_handoff.py
"""
Functional test for tabular computed-results handoff size handling.
Version: 0.242.071
Implemented in: 0.242.067

This test ensures the tabular SK analysis handoff preserves computed results
above the previous 24K limit while still truncating pathological payloads at
the 100K handoff guardrail.
"""

import ast
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')

TARGET_ASSIGNMENTS = {
    'TABULAR_COMPUTED_RESULTS_HANDOFF_MAX_CHARS',
}
TARGET_FUNCTIONS = {
    'build_tabular_computed_results_system_message',
}


def load_handoff_helper():
    """Load the handoff helper and constants without importing the full route module."""
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        route_content = file_handle.read()

    parsed = ast.parse(route_content, filename=ROUTE_FILE)
    selected_nodes = []
    for node in parsed.body:
        if isinstance(node, ast.Assign):
            target_names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if any(target_name in TARGET_ASSIGNMENTS for target_name in target_names):
                selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS:
            selected_nodes.append(node)

    namespace = {
        'log_event': lambda *args, **kwargs: None,
        'logging': type('LoggingStub', (), {'WARNING': 'WARNING'}),
    }
    module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace


def test_tabular_handoff_preserves_results_above_previous_limit():
    """Verify analysis larger than 24K but under 100K is not truncated."""
    print('🔍 Testing tabular handoff above previous limit...')

    try:
        helpers = load_handoff_helper()
        build_handoff = helpers['build_tabular_computed_results_system_message']
        analysis = 'A' * 50000
        message = build_handoff('test workbook', analysis)

        assert 'A' * 50000 in message, 'Expected the 50K analysis payload to remain intact.'
        assert '[Computed results handoff truncated for prompt budget.]' not in message, message[-200:]
        print('✅ Tabular handoff above previous limit passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_tabular_handoff_truncates_at_100k_guardrail():
    """Verify pathological computed-result payloads still get bounded."""
    print('🔍 Testing tabular handoff 100K guardrail...')

    try:
        helpers = load_handoff_helper()
        build_handoff = helpers['build_tabular_computed_results_system_message']
        limit = helpers['TABULAR_COMPUTED_RESULTS_HANDOFF_MAX_CHARS']
        message = build_handoff('test workbook', 'B' * (limit + 5000))

        assert limit == 100000, limit
        assert '[Computed results handoff truncated for prompt budget.]' in message, message[-200:]
        assert 'B' * 1000 in message, 'Expected truncated payload prefix to remain present.'
        assert len(message) < limit + 1000, len(message)
        print('✅ Tabular handoff 100K guardrail passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_tabular_handoff_preserves_results_above_previous_limit,
        test_tabular_handoff_truncates_at_100k_guardrail,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)