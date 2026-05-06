#!/usr/bin/env python3
# test_tabular_exhaustive_result_synthesis_fix.py
"""
Functional test for tabular exhaustive-result synthesis retry.
Version: 0.241.125
Implemented in: 0.241.125

This test ensures exhaustive tabular requests retry when successful analytical
tool calls already returned the full matching result set or only a partial row
or distinct-value slice, but the synthesis response still behaves as though
only schema samples are available. It also verifies that structured one-object-
per-row JSON prompts are treated as exhaustive requests so partial row slices
are expanded before export, including CSV/table export prompts that preserve
one output row per source row.
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
    'question_requests_tabular_exhaustive_results',
    'parse_tabular_result_count',
    'get_tabular_invocation_result_payload',
    'is_tabular_access_limited_analysis',
    'get_tabular_result_coverage_summary',
    'build_tabular_success_execution_gap_messages',
}


def load_helpers():
    """Load the targeted tabular retry helpers from the route source."""
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        route_content = file_handle.read()

    parsed = ast.parse(route_content, filename=ROUTE_FILE)
    selected_nodes = []
    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {
        'json': json,
        're': __import__('re'),
    }
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, route_content


def test_exhaustive_tabular_retry_detects_full_result_access_gap():
    """Verify full-result tool coverage forces a retry when synthesis claims sample-only access."""
    print('🔍 Testing exhaustive tabular retry for full-result access gaps...')

    try:
        helpers, route_content = load_helpers()
        wants_exhaustive_results = helpers['question_requests_tabular_exhaustive_results']
        is_access_limited_analysis = helpers['is_tabular_access_limited_analysis']
        get_tabular_result_coverage_summary = helpers['get_tabular_result_coverage_summary']
        build_execution_gap_messages = helpers['build_tabular_success_execution_gap_messages']

        user_question = 'list out all of the security controls'
        access_limited_analysis = (
            'The workbook contains 1,189 controls and control enhancements in NIST SP 800-53 Rev. 5, '
            'but the data provided here does not include the full 1,189-item list, only sample rows '
            'and workbook metadata. So I cannot accurately list all of them from the current evidence.'
        )
        invocations = [
            SimpleNamespace(
                function_name='query_tabular_data',
                parameters={
                    'filename': 'sp800-53r5-control-catalog.xlsx',
                    'max_rows': '1189',
                    'query_expression': '`Control Identifier` == `Control Identifier`',
                },
                result=json.dumps({
                    'filename': 'sp800-53r5-control-catalog.xlsx',
                    'selected_sheet': 'SP 800-53 Revision 5',
                    'total_matches': 1189,
                    'returned_rows': 1189,
                    'data': [
                        {
                            'Control Identifier': 'AC-1',
                            'Control (or Control Enhancement) Name': 'Policy and Procedures',
                        },
                        {
                            'Control Identifier': 'AC-2',
                            'Control (or Control Enhancement) Name': 'Account Management',
                        },
                    ],
                }),
                error_message=None,
            )
        ]

        coverage_summary = get_tabular_result_coverage_summary(invocations)
        execution_gap_messages = build_execution_gap_messages(
            user_question,
            access_limited_analysis,
            invocations,
        )

        assert wants_exhaustive_results(user_question), user_question
        assert is_access_limited_analysis(access_limited_analysis), access_limited_analysis
        assert coverage_summary['has_full_result_coverage'] is True, coverage_summary
        assert coverage_summary['has_partial_result_coverage'] is False, coverage_summary
        assert any('full matching result set' in message for message in execution_gap_messages), execution_gap_messages
        assert any('list the full results the user asked for' in message for message in execution_gap_messages), execution_gap_messages
        assert 'Do not claim that only sample rows or workbook metadata are available in that case.' in route_content, route_content

        print('✅ Exhaustive tabular retry for full-result access gaps passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_exhaustive_tabular_retry_detects_partial_result_slice():
    """Verify exhaustive requests trigger a rerun when analytical tools only returned a partial slice."""
    print('🔍 Testing exhaustive tabular retry for partial result slices...')

    try:
        helpers, _ = load_helpers()
        get_tabular_result_coverage_summary = helpers['get_tabular_result_coverage_summary']
        build_execution_gap_messages = helpers['build_tabular_success_execution_gap_messages']

        user_question = 'show me all of the matching security controls'
        invocations = [
            SimpleNamespace(
                function_name='query_tabular_data',
                parameters={
                    'filename': 'sp800-53r5-control-catalog.xlsx',
                    'max_rows': '100',
                    'query_expression': '`Control Identifier` == `Control Identifier`',
                },
                result=json.dumps({
                    'filename': 'sp800-53r5-control-catalog.xlsx',
                    'selected_sheet': 'SP 800-53 Revision 5',
                    'total_matches': 1189,
                    'returned_rows': 100,
                    'data': [
                        {
                            'Control Identifier': 'AC-1',
                            'Control (or Control Enhancement) Name': 'Policy and Procedures',
                        }
                    ],
                }),
                error_message=None,
            )
        ]

        coverage_summary = get_tabular_result_coverage_summary(invocations)
        execution_gap_messages = build_execution_gap_messages(
            user_question,
            'Here is a representative sample of the matching controls.',
            invocations,
        )

        assert coverage_summary['has_full_result_coverage'] is False, coverage_summary
        assert coverage_summary['has_partial_result_coverage'] is True, coverage_summary
        assert any('higher max_rows or max_values' in message for message in execution_gap_messages), execution_gap_messages

        print('✅ Exhaustive tabular retry for partial result slices passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_structured_row_json_prompt_triggers_exhaustive_follow_up():
    """Verify one-object-per-row JSON prompts trigger exhaustive-result recovery."""
    print('🔍 Testing structured row JSON prompt exhaustive follow-up...')

    try:
        helpers, _ = load_helpers()
        wants_exhaustive_results = helpers['question_requests_tabular_exhaustive_results']
        get_tabular_result_coverage_summary = helpers['get_tabular_result_coverage_summary']
        build_execution_gap_messages = helpers['build_tabular_success_execution_gap_messages']

        user_question = (
            'Return one JSON array containing one object per comment row across all files. '
            'Each object must contain exactly these fields: comment_id, classification, themes, '
            'attachment_priority_review, response_treatment, campaign_candidate, campaign_signals, '
            'substantive_score, confidence, reason. Return only valid JSON in a code block.'
        )
        invocations = [
            SimpleNamespace(
                function_name='query_tabular_data',
                parameters={
                    'filename': 'comments.xlsx',
                    'max_rows': '56',
                    'query_expression': '`comment_id` == `comment_id`',
                },
                result=json.dumps({
                    'filename': 'comments.xlsx',
                    'selected_sheet': 'Comments',
                    'total_matches': 1500,
                    'returned_rows': 56,
                    'data': [
                        {
                            'comment_id': '1001',
                            'body_text': 'Please see attached.',
                        }
                    ],
                }),
                error_message=None,
            )
        ]

        coverage_summary = get_tabular_result_coverage_summary(invocations)
        execution_gap_messages = build_execution_gap_messages(
            user_question,
            'Prepared a structured JSON export from the available rows.',
            invocations,
        )

        assert wants_exhaustive_results(user_question), user_question
        assert coverage_summary['has_full_result_coverage'] is False, coverage_summary
        assert coverage_summary['has_partial_result_coverage'] is True, coverage_summary
        assert any('higher max_rows or max_values' in message for message in execution_gap_messages), execution_gap_messages

        print('✅ Structured row JSON prompt exhaustive follow-up passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_structured_row_csv_prompt_triggers_exhaustive_follow_up():
    """Verify one-row-per-comment CSV prompts trigger exhaustive-result recovery."""
    print('🔍 Testing structured row CSV prompt exhaustive follow-up...')

    try:
        helpers, _ = load_helpers()
        wants_exhaustive_results = helpers['question_requests_tabular_exhaustive_results']
        get_tabular_result_coverage_summary = helpers['get_tabular_result_coverage_summary']
        build_execution_gap_messages = helpers['build_tabular_success_execution_gap_messages']

        user_question = (
            'Create a CSV file with one row per comment row across all files. '
            'Each row must contain comment_id, classification, themes, '
            'attachment_priority_review, response_treatment, campaign_candidate, '
            'campaign_signals, substantive_score_total, confidence, reason. '
            'Save the csv to this chat.'
        )
        invocations = [
            SimpleNamespace(
                function_name='query_tabular_data',
                parameters={
                    'filename': 'comments.xlsx',
                    'max_rows': '56',
                    'query_expression': '`comment_id` == `comment_id`',
                },
                result=json.dumps({
                    'filename': 'comments.xlsx',
                    'selected_sheet': 'Comments',
                    'total_matches': 1500,
                    'returned_rows': 56,
                    'data': [
                        {
                            'comment_id': '1001',
                            'body_text': 'Please see attached.',
                        }
                    ],
                }),
                error_message=None,
            )
        ]

        coverage_summary = get_tabular_result_coverage_summary(invocations)
        execution_gap_messages = build_execution_gap_messages(
            user_question,
            'Prepared a CSV export from the available rows.',
            invocations,
        )

        assert wants_exhaustive_results(user_question), user_question
        assert coverage_summary['has_full_result_coverage'] is False, coverage_summary
        assert coverage_summary['has_partial_result_coverage'] is True, coverage_summary
        assert any('higher max_rows or max_values' in message for message in execution_gap_messages), execution_gap_messages

        print('✅ Structured row CSV prompt exhaustive follow-up passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_result_coverage_summary_marks_partial_distinct_value_slices():
    """Verify distinct-value counts below the available total mark partial coverage."""
    print('🔍 Testing tabular result coverage summary for partial distinct-value slices...')

    try:
        helpers, _ = load_helpers()
        get_tabular_result_coverage_summary = helpers['get_tabular_result_coverage_summary']

        invocations = [
            SimpleNamespace(
                function_name='get_distinct_tabular_values',
                parameters={
                    'filename': 'sp800-53r5-control-catalog.xlsx',
                    'column': 'Control Identifier',
                    'max_values': '25',
                },
                result=json.dumps({
                    'filename': 'sp800-53r5-control-catalog.xlsx',
                    'selected_sheet': 'SP 800-53 Revision 5',
                    'column': 'Control Identifier',
                    'distinct_count': 1189,
                    'returned_values': 25,
                    'values': ['AC-1', 'AC-2'],
                }),
                error_message=None,
            )
        ]

        coverage_summary = get_tabular_result_coverage_summary(invocations)

        assert coverage_summary['has_full_result_coverage'] is False, coverage_summary
        assert coverage_summary['has_partial_result_coverage'] is True, coverage_summary

        print('✅ Tabular result coverage summary marks partial distinct-value slices')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_exhaustive_tabular_retry_detects_full_result_access_gap,
        test_exhaustive_tabular_retry_detects_partial_result_slice,
        test_structured_row_json_prompt_triggers_exhaustive_follow_up,
        test_structured_row_csv_prompt_triggers_exhaustive_follow_up,
        test_result_coverage_summary_marks_partial_distinct_value_slices,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)