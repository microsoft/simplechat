#!/usr/bin/env python3
# test_tabular_raw_tool_fallback.py
"""
Functional test for tabular raw tool fallback summaries.
Version: 0.240.013
Implemented in: 0.239.125; 0.240.013 (prompt-budgeted fallback handoff)

This test ensures successful tabular tool calls are not discarded when the
inner tabular synthesis step fails, and that the analysis prompt now prefers
combined conjunctive queries with conservative row limits.
"""

import ast
import json
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'application', 'single_app'))

ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
TARGET_FUNCTIONS = {
    'build_tabular_computed_results_system_message',
    'get_tabular_invocation_result_payload',
    'get_tabular_invocation_error_message',
    'get_tabular_invocation_selected_sheet',
    'get_tabular_invocation_data_rows',
    'normalize_tabular_overlap_value',
    'get_tabular_overlap_identifier_column',
    'describe_tabular_invocation_conditions',
    'compact_tabular_fallback_value',
    'get_tabular_query_overlap_summary',
    'get_tabular_invocation_compact_payload',
    'build_tabular_analysis_fallback_from_invocations',
}


class FakeInvocation:
    """Small stand-in for plugin invocation objects used by route helpers."""

    def __init__(self, function_name, parameters, result, error_message=None):
        self.function_name = function_name
        self.parameters = parameters
        self.result = result
        self.error_message = error_message


def load_fallback_helpers():
    """Load the raw fallback helper functions from the chat route source."""
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


def test_raw_fallback_builds_overlap_summary_from_successful_queries():
    """Verify successful query results can still produce a compact overlap summary."""
    print('🔍 Testing raw fallback overlap summary...')

    try:
        helpers, _ = load_fallback_helpers()
        build_fallback = helpers['build_tabular_analysis_fallback_from_invocations']

        congestion_rows = {
            'filename': 'faa_flight_operations_dataset.csv',
            'selected_sheet': None,
            'total_matches': 3,
            'returned_rows': 3,
            'data': [
                {
                    'FlightID': 101,
                    'Callsign': 'FL101',
                    'OriginAirport': 'DFW',
                    'DestinationAirport': 'ORD',
                    'DepartureQueueLength': 12,
                    'ArrivalQueueLength': 6,
                    'VisibilityMiles': 8,
                    'Precipitation': 'None',
                    'DelayCategory': 'Congestion',
                },
                {
                    'FlightID': 102,
                    'Callsign': 'FL102',
                    'OriginAirport': 'JFK',
                    'DestinationAirport': 'BOS',
                    'DepartureQueueLength': 13,
                    'ArrivalQueueLength': 11,
                    'VisibilityMiles': 2,
                    'Precipitation': 'Snow',
                    'DelayCategory': 'Weather',
                },
                {
                    'FlightID': 103,
                    'Callsign': 'FL103',
                    'OriginAirport': 'SEA',
                    'DestinationAirport': 'SFO',
                    'DepartureQueueLength': 10,
                    'ArrivalQueueLength': 12,
                    'VisibilityMiles': 3,
                    'Precipitation': 'Rain',
                    'DelayCategory': 'Weather',
                },
            ],
        }
        weather_rows = {
            'filename': 'faa_flight_operations_dataset.csv',
            'selected_sheet': None,
            'total_matches': 3,
            'returned_rows': 3,
            'data': [
                {
                    'FlightID': 102,
                    'Callsign': 'FL102',
                    'OriginAirport': 'JFK',
                    'DestinationAirport': 'BOS',
                    'DepartureQueueLength': 13,
                    'ArrivalQueueLength': 11,
                    'VisibilityMiles': 2,
                    'Precipitation': 'Snow',
                    'DelayCategory': 'Weather',
                },
                {
                    'FlightID': 103,
                    'Callsign': 'FL103',
                    'OriginAirport': 'SEA',
                    'DestinationAirport': 'SFO',
                    'DepartureQueueLength': 10,
                    'ArrivalQueueLength': 12,
                    'VisibilityMiles': 3,
                    'Precipitation': 'Rain',
                    'DelayCategory': 'Weather',
                },
                {
                    'FlightID': 104,
                    'Callsign': 'FL104',
                    'OriginAirport': 'DEN',
                    'DestinationAirport': 'MIA',
                    'DepartureQueueLength': 4,
                    'ArrivalQueueLength': 3,
                    'VisibilityMiles': 1,
                    'Precipitation': 'Thunderstorm',
                    'DelayCategory': 'Weather',
                },
            ],
        }

        invocations = [
            FakeInvocation(
                'query_tabular_data',
                {
                    'filename': 'faa_flight_operations_dataset.csv',
                    'query_expression': 'DepartureQueueLength >= 10 or ArrivalQueueLength >= 10',
                },
                json.dumps(congestion_rows),
            ),
            FakeInvocation(
                'query_tabular_data',
                {
                    'filename': 'faa_flight_operations_dataset.csv',
                    'query_expression': "VisibilityMiles <= 3 or Precipitation != 'None' or DelayCategory == 'Weather'",
                },
                json.dumps(weather_rows),
            ),
        ]

        fallback_summary = build_fallback(invocations)

        assert fallback_summary is not None, 'Expected raw fallback summary'
        assert 'OVERLAP SUMMARY:' in fallback_summary, fallback_summary
        assert 'FlightID' in fallback_summary, fallback_summary
        assert '"overlap_count": 2' in fallback_summary, fallback_summary
        assert 'FL102' in fallback_summary, fallback_summary
        assert 'FL103' in fallback_summary, fallback_summary
        assert 'DepartureQueueLength >= 10 or ArrivalQueueLength >= 10' in fallback_summary, fallback_summary

        print('✅ Raw fallback overlap summary passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_raw_fallback_preserves_aggregate_and_group_summaries():
    """Verify aggregate and grouped results survive the raw fallback handoff."""
    print('🔍 Testing raw fallback aggregate/group summaries...')

    try:
        helpers, _ = load_fallback_helpers()
        build_fallback = helpers['build_tabular_analysis_fallback_from_invocations']

        invocations = [
            FakeInvocation(
                'aggregate_column',
                {
                    'filename': 'Sample - Superstore (1).xlsx',
                    'column': 'Sales',
                    'operation': 'sum',
                },
                json.dumps({
                    'filename': 'Sample - Superstore (1).xlsx',
                    'selected_sheet': 'Orders',
                    'column': 'Sales',
                    'operation': 'sum',
                    'result': 2326534.3543,
                }),
            ),
            FakeInvocation(
                'group_by_aggregate',
                {
                    'filename': 'Sample - Superstore (1).xlsx',
                    'group_by_column': 'Category',
                    'aggregate_column': 'Profit',
                    'operation': 'sum',
                },
                json.dumps({
                    'filename': 'Sample - Superstore (1).xlsx',
                    'selected_sheet': 'Orders',
                    'group_by': 'Category',
                    'aggregate_column': 'Profit',
                    'operation': 'sum',
                    'groups': 3,
                    'highest_group': 'Technology',
                    'highest_value': 146543.3756,
                    'lowest_group': 'Furniture',
                    'lowest_value': 19729.9956,
                    'top_results': {
                        'Technology': 146543.3756,
                        'Office Supplies': 126023.4434,
                        'Furniture': 19729.9956,
                    },
                }),
            ),
        ]

        fallback_summary = build_fallback(invocations)

        assert fallback_summary is not None, 'Expected raw fallback summary'
        assert 'TOOL RESULT SUMMARIES:' in fallback_summary, fallback_summary
        assert '2326534.3543' in fallback_summary, fallback_summary
        assert 'Technology' in fallback_summary, fallback_summary
        assert '146543.3756' in fallback_summary, fallback_summary

        print('✅ Raw fallback aggregate/group summaries passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_route_prompt_prefers_combined_queries_and_raw_fallback_helper():
    """Verify the route now discourages oversized broad intersections."""
    print('🔍 Testing route prompt guidance for combined queries...')

    try:
        _, route_content = load_fallback_helpers()

        checks = {
            'combined query guidance present': 'prefer one combined query_expression using and/or' in route_content,
            'broad query intersection warning present': 'instead of separate broad queries that you plan to intersect later' in route_content,
            'conservative max_rows guidance present': 'Keep max_rows as small as possible.' in route_content,
            'raw fallback helper used after synthesis error': 'build_tabular_analysis_fallback_from_invocations(' in route_content,
        }

        failed_checks = [name for name, passed in checks.items() if not passed]
        assert not failed_checks, f'Missing expected prompt/fallback behavior: {failed_checks}'

        print('✅ Route prompt guidance passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_raw_fallback_stays_within_prompt_budget_for_large_rows():
    """Verify oversized fallback payloads are reduced to a bounded handoff."""
    print('🔍 Testing raw fallback prompt budget...')

    try:
        helpers, _ = load_fallback_helpers()
        build_fallback = helpers['build_tabular_analysis_fallback_from_invocations']

        large_cell = 'X' * 5000
        large_rows = {
            'filename': 'large_workbook.xlsx',
            'selected_sheet': 'Notices',
            'total_matches': 12,
            'returned_rows': 12,
            'data': [
                {
                    'TaxpayerID': f'TP{index:06d}',
                    'Narrative': large_cell,
                    'NoticeAmount': 1000 + index,
                }
                for index in range(12)
            ],
        }

        invocations = [
            FakeInvocation(
                'filter_rows',
                {
                    'filename': 'large_workbook.xlsx',
                    'column': 'TaxpayerID',
                    'operator': 'contains',
                    'value': 'TP',
                },
                json.dumps(large_rows),
            )
            for _ in range(4)
        ]

        fallback_summary = build_fallback(invocations)

        assert fallback_summary is not None, 'Expected raw fallback summary'
        assert len(fallback_summary) <= 26000, len(fallback_summary)
        assert 'RESULT COVERAGE NOTE:' in fallback_summary or 'result_summary_truncated' in fallback_summary, fallback_summary

        print('✅ Raw fallback prompt budget passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_computed_results_system_message_truncates_large_handoffs():
    """Verify computed-results handoffs are capped before the outer model call."""
    print('🔍 Testing computed-results handoff truncation...')

    try:
        helpers, _ = load_fallback_helpers()
        build_system_message = helpers['build_tabular_computed_results_system_message']

        message = build_system_message('the file workbook.xlsx', 'A' * 30000)

        assert len(message) <= 25000, len(message)
        assert '[Computed results handoff truncated for prompt budget.]' in message, message

        print('✅ Computed-results handoff truncation passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_raw_fallback_builds_overlap_summary_from_successful_queries,
        test_raw_fallback_preserves_aggregate_and_group_summaries,
        test_route_prompt_prefers_combined_queries_and_raw_fallback_helper,
        test_raw_fallback_stays_within_prompt_budget_for_large_rows,
        test_computed_results_system_message_truncates_large_handoffs,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)