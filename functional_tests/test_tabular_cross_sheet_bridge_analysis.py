#!/usr/bin/env python3
# test_tabular_cross_sheet_bridge_analysis.py
"""
Functional test for cross-sheet bridge analysis guidance.
Version: 0.239.140
Implemented in: 0.239.140

This test ensures grouped workbook questions that need one worksheet for
canonical entities and another for fact rows stay in analysis mode, derive a
reference-to-fact bridge plan from workbook structure, and keep prompt
guardrails that discourage grouping boolean or membership-flag columns when the
user asked for results per entity.
"""

import ast
import os
import re
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'application', 'single_app'))

ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
TARGET_FUNCTIONS = {
    'is_tabular_schema_summary_question',
    'is_tabular_entity_lookup_question',
    'is_tabular_cross_sheet_bridge_question',
    'get_tabular_execution_mode',
    '_normalize_tabular_sheet_token',
    '_tokenize_tabular_sheet_text',
    '_score_tabular_sheet_match',
    '_select_relevant_workbook_sheets',
    '_build_tabular_cross_sheet_bridge_plan',
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
        're': re,
    }
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, route_content


def test_cross_sheet_bridge_questions_stay_in_analysis_mode():
    """Verify grouped cross-sheet questions stay analytical, not entity-lookup."""
    print('🔍 Testing cross-sheet bridge intent detection...')

    try:
        helpers, _ = load_tabular_route_helpers()
        is_bridge_question = helpers['is_tabular_cross_sheet_bridge_question']
        is_entity_lookup_question = helpers['is_tabular_entity_lookup_question']
        get_execution_mode = helpers['get_tabular_execution_mode']

        bridge_question = 'How many milestones does each solution engineer have?'

        assert is_bridge_question(bridge_question), bridge_question
        assert not is_entity_lookup_question(bridge_question), bridge_question
        assert get_execution_mode(bridge_question) == 'analysis', bridge_question

        print('✅ Cross-sheet bridge intent detection passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_bridge_plan_identifies_reference_and_fact_sheets():
    """Verify the bridge helper prefers a smaller entity sheet and larger fact sheet."""
    print('🔍 Testing cross-sheet bridge plan inference...')

    try:
        helpers, _ = load_tabular_route_helpers()
        build_bridge_plan = helpers['_build_tabular_cross_sheet_bridge_plan']

        per_sheet = {
            'milestones': {
                'columns': ['id', 'Owner', 'StartDate', 'Status', 'owned_by_se'],
                'row_count': 8201,
            },
            'solution_engineers': {
                'columns': ['se', 'manager', 'exist_in_opp_owners'],
                'row_count': 29,
            },
            'metadata': {
                'columns': ['refresh_date', 'source'],
                'row_count': 1,
            },
        }

        plan = build_bridge_plan(
            ['milestones', 'solution_engineers', 'metadata'],
            'Show me how many milestones are assigned to each solution engineer.',
            per_sheet=per_sheet,
        )

        assert plan is not None, plan
        assert plan['reference_sheet'] == 'solution_engineers', plan
        assert plan['fact_sheet'] == 'milestones', plan
        assert plan['reference_row_count'] == 29, plan
        assert plan['fact_row_count'] == 8201, plan
        assert plan['relevant_sheets'][:2] == ['solution_engineers', 'milestones'], plan

        print('✅ Cross-sheet bridge plan inference passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_route_prompt_contains_cross_sheet_bridge_guardrails():
    """Verify the analysis prompt includes bridge guidance and flag-column guardrails."""
    print('🔍 Testing cross-sheet bridge prompt guardrails...')

    try:
        _, route_content = load_tabular_route_helpers()

        checks = {
            'bridge plan block exists': 'CROSS-SHEET BRIDGE PLAN:' in route_content,
            'bridge prompt prefers reference then fact': 'first use the reference worksheet to identify canonical entity or category names, then compute the requested metric from the fact worksheet' in route_content,
            'flag-column guardrail exists': "Do not answer 'each X' by grouping a yes/no, boolean, or membership-flag column" in route_content,
            'default-sheet guardrail exists': 'If a CROSS-SHEET BRIDGE PLAN is provided, query the listed worksheets explicitly and do not rely on a default sheet.' in route_content,
        }

        failed_checks = [name for name, passed in checks.items() if not passed]
        assert not failed_checks, f'Missing expected cross-sheet bridge guardrails: {failed_checks}'

        print('✅ Cross-sheet bridge prompt guardrails passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_cross_sheet_bridge_questions_stay_in_analysis_mode,
        test_bridge_plan_identifies_reference_and_fact_sheets,
        test_route_prompt_contains_cross_sheet_bridge_guardrails,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)