#!/usr/bin/env python3
# test_tabular_computed_results_prompt_priority.py
"""
Functional test for tabular computed-results prompt priority.
Version: 0.239.118
Implemented in: 0.239.118

This test ensures retrieval augmentation prompts do not override successful
tabular tool results and that tool-backed tabular results are marked as
authoritative when they are handed to the outer GPT response.
"""

import ast
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'application', 'single_app'))

ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
TARGET_FUNCTIONS = {
    'build_search_augmentation_system_prompt',
    'build_tabular_computed_results_system_message',
}


def load_prompt_helpers():
    """Load prompt helper functions from the chat route source."""
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        route_content = file_handle.read()

    parsed = ast.parse(route_content, filename=ROUTE_FILE)
    selected_nodes = []
    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {}
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, route_content


def test_search_prompt_allows_computed_tool_results():
    """Verify the search augmentation prompt no longer blocks later tool results."""
    print('🔍 Testing search prompt compatibility with computed tool results...')

    try:
        helpers, _ = load_prompt_helpers()
        build_search_prompt = helpers['build_search_augmentation_system_prompt']
        prompt = build_search_prompt('Excerpt A')

        assert 'computed tool-backed results included elsewhere in this conversation context' in prompt, prompt
        assert 'Do not say that you lack direct access to the data' in prompt, prompt
        assert "If the answer isn't in the excerpts, say so." not in prompt, prompt

        print('✅ Search prompt compatibility passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_tabular_results_prompt_marks_results_authoritative():
    """Verify successful tabular analysis is handed off as authoritative evidence."""
    print('🔍 Testing authoritative tabular handoff prompt...')

    try:
        helpers, _ = load_prompt_helpers()
        build_tabular_prompt = helpers['build_tabular_computed_results_system_message']
        analysis = 'ReturnID=RET000123; TaxLiability=4200; CreditsClaimed=300; RefundAmount=1350'
        prompt = build_tabular_prompt(
            'the file(s) irs_treasury_multi_tab_workbook.xlsx',
            analysis,
        )

        assert analysis in prompt, prompt
        assert 'These are tool-backed results derived from the full underlying tabular data' in prompt, prompt
        assert 'Treat them as authoritative for row-level facts, calculations, and numeric conclusions' in prompt, prompt

        print('✅ Authoritative tabular handoff prompt passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_route_uses_shared_prompt_helpers_for_tabular_handoff():
    """Verify the route uses shared helpers instead of the old excerpt-only prompt."""
    print('🔍 Testing route prompt helper usage...')

    try:
        _, route_content = load_prompt_helpers()

        checks = {
            'shared search prompt helper': 'build_search_augmentation_system_prompt(retrieved_content)' in route_content,
            'shared tabular handoff helper': 'build_tabular_computed_results_system_message(' in route_content,
            'old excerpt-only prompt removed': "If the answer isn't in the excerpts, say so." not in route_content,
        }

        failed_checks = [name for name, passed in checks.items() if not passed]
        assert not failed_checks, f'Missing expected prompt handoff behavior: {failed_checks}'

        print('✅ Route prompt helper usage passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_search_prompt_allows_computed_tool_results,
        test_tabular_results_prompt_marks_results_authoritative,
        test_route_uses_shared_prompt_helpers_for_tabular_handoff,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)