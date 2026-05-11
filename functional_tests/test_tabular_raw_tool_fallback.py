#!/usr/bin/env python3
# test_tabular_raw_tool_fallback.py
"""
Functional test for tabular raw tool fallback summaries.
Version: 0.240.048
Implemented in: 0.239.125; 0.240.013; 0.240.036; 0.240.038; 0.240.039; 0.240.040; 0.240.041; 0.240.042; 0.240.043; 0.240.048 (prompt-budgeted fallback handoff)

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


def test_raw_fallback_preserves_distinct_value_lists_when_budget_allows():
    """Verify distinct-value tool results keep full scalar lists when they fit the budget."""
    print('🔍 Testing raw fallback distinct-value preservation...')

    try:
        helpers, _ = load_fallback_helpers()
        build_fallback = helpers['build_tabular_analysis_fallback_from_invocations']

        distinct_values_payload = {
            'filename': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
            'selected_sheet': 'Legal',
            'column': 'Location',
            'filter_applied': [
                {
                    'column': 'Location',
                    'operator': 'contains',
                    'value': 'SharePoint',
                }
            ],
            'normalize_match': False,
            'distinct_count': 4,
            'returned_values': 4,
            'values_limited': False,
            'values': [
                'http://occtreasgovprod.sharepoint.com/sites/CCO',
                'http://occtreasgovprod.sharepoint.com/sites/LCFrmwrk',
                'http://occtreasgovprod.sharepoint.com/sites/PolicyOps',
                'http://occtreasgovprod.sharepoint.com/sites/RecordsMgmt',
            ],
        }

        invocations = [
            FakeInvocation(
                'get_distinct_values',
                {
                    'filename': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
                    'sheet_name': 'Legal',
                    'column': 'Location',
                    'filter_column': 'Location',
                    'filter_operator': 'contains',
                    'filter_value': 'SharePoint',
                    'normalize_match': 'false',
                },
                json.dumps(distinct_values_payload),
            ),
        ]

        fallback_summary = build_fallback(invocations)

        assert fallback_summary is not None, 'Expected raw fallback summary'
        assert '"distinct_count": 4' in fallback_summary, fallback_summary
        assert '"full_values_included": true' in fallback_summary.lower(), fallback_summary
        for expected_value in distinct_values_payload['values']:
            assert expected_value in fallback_summary, fallback_summary

        print('✅ Raw fallback distinct-value preservation passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_raw_fallback_preserves_embedded_extraction_metadata():
    """Verify embedded extraction summaries survive the raw fallback handoff."""
    print('🔍 Testing raw fallback embedded extraction metadata...')

    try:
        helpers, _ = load_fallback_helpers()
        build_fallback = helpers['build_tabular_analysis_fallback_from_invocations']

        distinct_values_payload = {
            'filename': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
            'selected_sheet': 'Legal',
            'column': 'Location',
            'filter_applied': [
                'Business Unit contains CCO',
                'Location contains sharepoint',
            ],
            'extract_mode': 'url',
            'url_path_segments': 2,
            'matched_cell_count': 4,
            'extracted_match_count': 4,
            'normalize_match': False,
            'distinct_count': 3,
            'returned_values': 3,
            'values_limited': False,
            'values': [
                'https://contoso.sharepoint.com/sites/Alpha',
                'https://contoso.sharepoint.com/sites/Beta',
                'https://contoso.sharepoint.com/sites/Delta',
            ],
        }

        invocations = [
            FakeInvocation(
                'get_distinct_values',
                {
                    'filename': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
                    'sheet_name': 'Legal',
                    'column': 'Location',
                    'filter_column': 'Business Unit',
                    'filter_operator': 'contains',
                    'filter_value': 'CCO',
                    'additional_filter_column': 'Location',
                    'additional_filter_operator': 'contains',
                    'additional_filter_value': 'sharepoint',
                    'extract_mode': 'url',
                    'url_path_segments': '2',
                    'normalize_match': 'false',
                },
                json.dumps(distinct_values_payload),
            ),
        ]

        fallback_summary = build_fallback(invocations)

        assert fallback_summary is not None, 'Expected raw fallback summary'
        assert '"extract_mode": "url"' in fallback_summary, fallback_summary
        assert '"url_path_segments": 2' in fallback_summary, fallback_summary
        assert '"matched_cell_count": 4' in fallback_summary, fallback_summary
        assert '"extracted_match_count": 4' in fallback_summary, fallback_summary

        print('✅ Raw fallback embedded extraction metadata passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_raw_fallback_preserves_complete_small_row_sets_when_budget_allows():
    """Verify small search/filter cohorts keep the full row context in the fallback handoff."""
    print('🔍 Testing raw fallback full row-context preservation...')

    try:
        helpers, _ = load_fallback_helpers()
        build_fallback = helpers['build_tabular_analysis_fallback_from_invocations']

        matching_rows_payload = {
            'filename': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
            'selected_sheet': 'Legal',
            'filter_applied': [
                'Business Unit contains CCO',
                'Location contains sharepoint',
            ],
            'total_matches': 8,
            'returned_rows': 8,
            'data': [
                {
                    'Business Unit': 'CCO Legal',
                    'Location': f'CCO Wide: DAP SharePoint site - http://share/sites/CSPA/BorderTracking/SitePages/Home.aspx; row {index}',
                    'Site': f'Site {index}',
                }
                for index in range(8)
            ],
        }

        invocations = [
            FakeInvocation(
                'filter_rows',
                {
                    'filename': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
                    'sheet_name': 'Legal',
                    'column': 'Location',
                    'operator': 'contains',
                    'value': 'sharepoint',
                    'additional_filter_column': 'Business Unit',
                    'additional_filter_operator': 'contains',
                    'additional_filter_value': 'CCO',
                    'normalize_match': 'false',
                    'max_rows': '50',
                },
                json.dumps(matching_rows_payload),
            ),
        ]

        fallback_summary = build_fallback(invocations)

        assert fallback_summary is not None, 'Expected raw fallback summary'
        assert 'http://share/sites/CSPA/BorderTracking/SitePages/Home.aspx; row 0' in fallback_summary, fallback_summary
        assert 'http://share/sites/CSPA/BorderTracking/SitePages/Home.aspx; row 7' in fallback_summary, fallback_summary
        assert '"full_rows_included": true' in fallback_summary.lower(), fallback_summary

        print('✅ Raw fallback full row-context preservation passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_raw_fallback_preserves_complete_small_search_row_sets_when_budget_allows():
    """Verify generic search_rows results keep the full small cohort in the fallback handoff."""
    print('🔍 Testing raw fallback full search-row preservation...')

    try:
        helpers, _ = load_fallback_helpers()
        build_fallback = helpers['build_tabular_analysis_fallback_from_invocations']

        matching_rows_payload = {
            'filename': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
            'selected_sheet': 'ALL (cross-sheet search)',
            'search_value': 'GRS 6.1',
            'search_operator': 'contains',
            'searched_columns': ['Business Unit', 'Location', 'Site', 'Schedule Notes'],
            'matched_columns': ['Schedule Notes'],
            'return_columns': ['Business Unit', 'Location', 'Site'],
            'total_matches': 3,
            'returned_rows': 3,
            'data': [
                {
                    'Business Unit': 'CCO - Supervision',
                    'Location': 'AIL: SharePoint - https://contoso.sharepoint.com/sites/Alpha/SitePages/Home.aspx',
                    'Site': 'Alpha',
                    '_matched_columns': ['Schedule Notes'],
                    '_matched_values': {'Schedule Notes': 'Primary schedules: GRS 6.1; GRS 2.4'},
                    '_sheet': 'File Plan Q1',
                },
                {
                    'Business Unit': 'CCO Legal',
                    'Location': 'DCCO: SharePoint - https://contoso.sharepoint.com/sites/Delta/Shared%20Documents/Forms/AllItems.aspx',
                    'Site': 'Delta',
                    '_matched_columns': ['Schedule Notes'],
                    '_matched_values': {'Schedule Notes': 'Legal schedules: GRS 6.1'},
                    '_sheet': 'File Plan Q2',
                },
                {
                    'Business Unit': 'CCO Legal',
                    'Location': 'WEDO: SharePoint - https://contoso.sharepoint.com/sites/Beta/SitePages/Home.aspx',
                    'Site': 'Beta',
                    '_matched_columns': ['Schedule Notes'],
                    '_matched_values': {'Schedule Notes': 'Duplicates: GRS 2.4; GRS 6.1'},
                    '_sheet': 'File Plan Q2',
                },
            ],
        }

        invocations = [
            FakeInvocation(
                'search_rows',
                {
                    'filename': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
                    'search_value': 'GRS 6.1',
                    'search_operator': 'contains',
                    'return_columns': 'Business Unit,Location,Site',
                    'max_rows': '10',
                },
                json.dumps(matching_rows_payload),
            ),
        ]

        fallback_summary = build_fallback(invocations)

        assert fallback_summary is not None, 'Expected raw fallback summary'
        assert '"search_value": "GRS 6.1"' in fallback_summary, fallback_summary
        assert '"full_rows_included": true' in fallback_summary.lower(), fallback_summary
        assert '"Site": "Alpha"' in fallback_summary, fallback_summary
        assert '"Site": "Beta"' in fallback_summary, fallback_summary
        assert '"Site": "Delta"' in fallback_summary, fallback_summary

        print('✅ Raw fallback full search-row preservation passed')
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
        test_raw_fallback_preserves_distinct_value_lists_when_budget_allows,
        test_raw_fallback_preserves_embedded_extraction_metadata,
        test_raw_fallback_preserves_complete_small_row_sets_when_budget_allows,
        test_raw_fallback_preserves_complete_small_search_row_sets_when_budget_allows,
        test_computed_results_system_message_truncates_large_handoffs,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)