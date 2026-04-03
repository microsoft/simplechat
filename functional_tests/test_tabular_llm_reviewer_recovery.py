#!/usr/bin/env python3
# test_tabular_llm_reviewer_recovery.py
"""
Functional test for multi-sheet tabular LLM reviewer recovery.
Version: 0.240.049
Implemented in: 0.240.035; 0.240.036; 0.240.037; 0.240.038; 0.240.039; 0.240.040; 0.240.041; 0.240.042; 0.240.043; 0.240.048; 0.240.049

This test ensures that stalled multi-sheet analytical runs can parse a reviewer
JSON plan, normalize the selected function, and inject the correct source
context before directly executing analytical plugin calls.
"""

import ast
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
TARGET_FUNCTIONS = {
    'build_tabular_follow_up_call_signature',
    'determine_tabular_follow_up_limit',
    'derive_tabular_follow_up_calls_from_invocations',
    'extract_json_object_from_text',
    'extract_tabular_high_signal_search_terms',
    'extract_tabular_secondary_filter_terms',
    'get_tabular_invocation_error_message',
    'get_tabular_invocation_data_rows',
    'get_tabular_invocation_result_payload',
    'get_tabular_invocation_selected_sheet',
    'infer_tabular_url_path_segments',
    'infer_tabular_url_value_column_from_rows',
    'infer_tabular_secondary_filter_from_rows',
    'is_tabular_distinct_url_question',
    'normalize_tabular_reviewer_function_name',
    'normalize_tabular_row_text',
    'parse_tabular_result_count',
    'parse_tabular_column_candidates',
    'parse_tabular_reviewer_plan',
    'question_requests_tabular_exhaustive_results',
    'question_requests_tabular_row_context',
    'resolve_tabular_reviewer_call_arguments',
    'tabular_value_looks_url_like',
    'tabular_result_payload_contains_url_like_content',
}


class FakeInvocation:
    """Simple invocation stub for follow-up derivation tests."""

    def __init__(self, function_name, parameters, result, error_message=None):
        self.function_name = function_name
        self.parameters = parameters
        self.result = result
        self.error_message = error_message


def load_route_helpers():
    """Load selected reviewer helpers from the chat route source."""
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


def test_reviewer_json_extraction_handles_markdown_wrapping():
    """Verify reviewer JSON can be extracted even when the model adds wrapper text."""
    print('🔍 Testing reviewer JSON extraction...')

    helpers, _ = load_route_helpers()
    payload = helpers['extract_json_object_from_text'](
        'Plan follows:\n```json\n{"calls":[{"function":"TabularProcessingPlugin.get_distinct_values","arguments":{"column":"Location"}}]}\n```'
    )

    assert payload['calls'][0]['function'] == 'TabularProcessingPlugin.get_distinct_values', payload

    print('✅ Reviewer JSON extraction passed')
    return True


def test_reviewer_plan_normalizes_prefixed_function_names():
    """Verify reviewer plans normalize plugin-prefixed function names."""
    print('🔍 Testing reviewer plan normalization...')

    helpers, _ = load_route_helpers()
    calls = helpers['parse_tabular_reviewer_plan'](
        '{"calls":[{"function":"tabular_processing-get_distinct_values","arguments":{"filename":"CCO-Legal File Plan 2025_Final Approved.xlsx","column":"Location","filter_column":"Location","filter_operator":"contains","filter_value":"SharePoint"}}]}'
    )

    assert calls == [{
        'function_name': 'get_distinct_values',
        'arguments': {
            'filename': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
            'column': 'Location',
            'filter_column': 'Location',
            'filter_operator': 'contains',
            'filter_value': 'SharePoint',
        },
    }], calls

    print('✅ Reviewer plan normalization passed')
    return True


def test_reviewer_call_argument_resolution_injects_group_context():
    """Verify reviewer-planned calls inherit filename and source context correctly."""
    print('🔍 Testing reviewer call argument resolution...')

    helpers, _ = load_route_helpers()
    resolve_arguments = helpers['resolve_tabular_reviewer_call_arguments']

    resolved_arguments, error_message = resolve_arguments(
        {
            'column': 'Location',
            'filter_column': 'Location',
            'filter_operator': 'contains',
            'filter_value': 'SharePoint',
        },
        [
            {
                'file_name': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
                'source_hint': 'group',
                'group_id': '93aa364a-99ee-4cfd-8e4d-f37d175f00f5',
            }
        ],
        fallback_source_hint='group',
    )

    assert error_message is None, error_message
    assert resolved_arguments['filename'] == 'CCO-Legal File Plan 2025_Final Approved.xlsx', resolved_arguments
    assert resolved_arguments['source'] == 'group', resolved_arguments
    assert resolved_arguments['group_id'] == '93aa364a-99ee-4cfd-8e4d-f37d175f00f5', resolved_arguments

    print('✅ Reviewer call argument resolution passed')
    return True


def test_reviewer_follow_up_derivation_adds_row_context_and_url_extraction():
    """Verify reviewer recovery derives a search step and URL extraction follow-up."""
    print('🔍 Testing reviewer follow-up derivation...')

    helpers, _ = load_route_helpers()
    derive_follow_ups = helpers['derive_tabular_follow_up_calls_from_invocations']

    initial_invocation = FakeInvocation(
        'get_distinct_values',
        {
            'filename': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
            'sheet_name': 'Legal',
            'column': 'Location',
            'filter_column': 'Location',
            'filter_operator': 'contains',
            'filter_value': 'CCO',
            'normalize_match': 'false',
            'source': 'group',
            'group_id': '93aa364a-99ee-4cfd-8e4d-f37d175f00f5',
        },
        '{"filename": "CCO-Legal File Plan 2025_Final Approved.xlsx", "selected_sheet": "Legal", "column": "Location", "distinct_count": 25, "returned_values": 25, "values": ["AIL: SharePoint - https://contoso.sharepoint.com/sites/Alpha/SitePages/Home.aspx", "BA: SharePoint - https://contoso.sharepoint.com/sites/Beta/Forms/AllItems.aspx", "Network Drive"]}',
    )

    follow_up_calls = derive_follow_ups(
        'How many discrete SharePoint sites appear in CCO locations?',
        [initial_invocation],
    )

    assert [call['function_name'] for call in follow_up_calls] == ['search_rows', 'get_distinct_values'], follow_up_calls

    row_context_arguments = follow_up_calls[0]['arguments']
    assert row_context_arguments['filename'] == 'CCO-Legal File Plan 2025_Final Approved.xlsx', row_context_arguments
    assert row_context_arguments['sheet_name'] == 'Legal', row_context_arguments
    assert row_context_arguments['search_value'] == 'SharePoint', row_context_arguments
    assert row_context_arguments['search_columns'] == 'Location', row_context_arguments
    assert row_context_arguments['filter_column'] == 'Location', row_context_arguments
    assert row_context_arguments['filter_value'] == 'CCO', row_context_arguments
    assert row_context_arguments['max_rows'] == '25', row_context_arguments

    extraction_arguments = follow_up_calls[1]['arguments']
    assert extraction_arguments['filename'] == 'CCO-Legal File Plan 2025_Final Approved.xlsx', extraction_arguments
    assert extraction_arguments['sheet_name'] == 'Legal', extraction_arguments
    assert extraction_arguments['column'] == 'Location', extraction_arguments
    assert extraction_arguments['filter_column'] == 'Location', extraction_arguments
    assert extraction_arguments['filter_value'] == 'CCO', extraction_arguments
    assert extraction_arguments['extract_mode'] == 'url', extraction_arguments
    assert extraction_arguments['url_path_segments'] == '2', extraction_arguments

    print('✅ Reviewer follow-up derivation passed')
    return True


def test_reviewer_follow_up_derivation_broadens_zero_match_same_column_filter():
    """Verify zero-match same-column filters trigger a broad discovery search instead of repetition."""
    print('🔍 Testing reviewer broad discovery follow-up derivation...')

    helpers, _ = load_route_helpers()
    derive_follow_ups = helpers['derive_tabular_follow_up_calls_from_invocations']

    initial_invocation = FakeInvocation(
        'get_distinct_values',
        {
            'filename': 'CCO-Licensing File Plan 2025_Final Approved.xlsx',
            'sheet_name': 'Licensing',
            'column': 'Location',
            'filter_column': 'Location',
            'filter_operator': 'contains',
            'filter_value': 'CCO',
            'normalize_match': 'false',
            'source': 'group',
            'group_id': '93aa364a-99ee-4cfd-8e4d-f37d175f00f5',
        },
        '{"filename": "CCO-Licensing File Plan 2025_Final Approved.xlsx", "selected_sheet": "Licensing", "column": "Location", "distinct_count": 0, "returned_values": 0, "values": []}',
    )

    follow_up_calls = derive_follow_ups(
        'How many discrete SharePoint sites appear in CCO locations? please list them out',
        [initial_invocation],
    )

    assert len(follow_up_calls) == 1, follow_up_calls
    assert follow_up_calls[0]['function_name'] == 'search_rows', follow_up_calls
    search_arguments = follow_up_calls[0]['arguments']
    assert search_arguments['filename'] == 'CCO-Licensing File Plan 2025_Final Approved.xlsx', search_arguments
    assert search_arguments['sheet_name'] == 'Licensing', search_arguments
    assert search_arguments['search_value'] == 'SharePoint', search_arguments
    assert search_arguments['search_columns'] == 'Location', search_arguments
    assert search_arguments['max_rows'] == '50', search_arguments
    assert 'filter_column' not in search_arguments, search_arguments
    assert 'return_columns' not in search_arguments, search_arguments

    print('✅ Reviewer broad discovery follow-up derivation passed')
    return True


def test_reviewer_follow_up_derivation_infers_cohort_column_from_row_context():
    """Verify row-context search results can infer a better cohort column for extraction."""
    print('🔍 Testing reviewer row-context cohort inference...')

    helpers, _ = load_route_helpers()
    derive_follow_ups = helpers['derive_tabular_follow_up_calls_from_invocations']

    row_context_invocation = FakeInvocation(
        'search_rows',
        {
            'filename': 'CCO-Licensing File Plan 2025_Final Approved.xlsx',
            'sheet_name': 'Licensing',
            'search_value': 'SharePoint',
            'search_columns': 'Location',
            'normalize_match': 'false',
            'source': 'group',
            'group_id': '93aa364a-99ee-4cfd-8e4d-f37d175f00f5',
            'max_rows': '50',
        },
        '{"filename": "CCO-Licensing File Plan 2025_Final Approved.xlsx", "selected_sheet": "Licensing", "search_value": "SharePoint", "searched_columns": ["Location"], "total_matches": 3, "returned_rows": 3, "data": [{"Business Unit": "CCO Licensing", "Location": "Licensing SharePoint - https://contoso.sharepoint.com/sites/Alpha/SitePages/Home.aspx", "Site": "Alpha"}, {"Business Unit": "CCO Licensing", "Location": "Licensing SharePoint - https://contoso.sharepoint.com/sites/Beta/Forms/AllItems.aspx", "Site": "Beta"}, {"Business Unit": "Finance", "Location": "Finance docs - https://contoso.sharepoint.com/sites/Gamma/SitePages/Home.aspx", "Site": "Gamma"}]}',
    )

    follow_up_calls = derive_follow_ups(
        'How many discrete SharePoint sites appear in CCO locations? please list them out',
        [row_context_invocation],
    )

    assert len(follow_up_calls) == 1, follow_up_calls
    assert follow_up_calls[0]['function_name'] == 'get_distinct_values', follow_up_calls
    extraction_arguments = follow_up_calls[0]['arguments']
    assert extraction_arguments['filename'] == 'CCO-Licensing File Plan 2025_Final Approved.xlsx', extraction_arguments
    assert extraction_arguments['sheet_name'] == 'Licensing', extraction_arguments
    assert extraction_arguments['column'] == 'Location', extraction_arguments
    assert extraction_arguments['filter_column'] == 'Business Unit', extraction_arguments
    assert extraction_arguments['filter_operator'] == 'contains', extraction_arguments
    assert extraction_arguments['filter_value'] == 'CCO', extraction_arguments
    assert extraction_arguments['extract_mode'] == 'url', extraction_arguments
    assert extraction_arguments['url_path_segments'] == '2', extraction_arguments

    print('✅ Reviewer row-context cohort inference passed')
    return True


def test_reviewer_follow_up_derivation_expands_limited_search_rows_and_extraction_values():
    """Verify exhaustive list questions can expand a partial row slice and the derived value list."""
    print('🔍 Testing reviewer exhaustive row/value expansion...')

    helpers, _ = load_route_helpers()
    derive_follow_ups = helpers['derive_tabular_follow_up_calls_from_invocations']

    row_context_invocation = FakeInvocation(
        'search_rows',
        {
            'filename': 'CCO-Licensing File Plan 2025_Final Approved.xlsx',
            'sheet_name': 'Licensing',
            'search_value': 'SharePoint',
            'search_columns': 'Location',
            'normalize_match': 'false',
            'source': 'group',
            'group_id': '93aa364a-99ee-4cfd-8e4d-f37d175f00f5',
            'max_rows': '25',
        },
        '{"filename": "CCO-Licensing File Plan 2025_Final Approved.xlsx", "selected_sheet": "Licensing", "search_value": "SharePoint", "searched_columns": ["Location"], "total_matches": 40, "returned_rows": 25, "data": [{"Business Unit": "CCO Licensing", "Location": "Licensing SharePoint - https://contoso.sharepoint.com/sites/Alpha/SitePages/Home.aspx", "Site": "Alpha"}, {"Business Unit": "CCO Licensing", "Location": "Licensing SharePoint - https://contoso.sharepoint.com/sites/Beta/Forms/AllItems.aspx", "Site": "Beta"}]}'
    )

    follow_up_calls = derive_follow_ups(
        'How many discrete SharePoint sites appear in CCO locations? please list them all out',
        [row_context_invocation],
    )

    assert [call['function_name'] for call in follow_up_calls] == ['search_rows', 'get_distinct_values'], follow_up_calls

    expanded_row_arguments = follow_up_calls[0]['arguments']
    assert expanded_row_arguments['max_rows'] == '40', expanded_row_arguments
    assert expanded_row_arguments['search_value'] == 'SharePoint', expanded_row_arguments

    extraction_arguments = follow_up_calls[1]['arguments']
    assert extraction_arguments['filter_column'] == 'Business Unit', extraction_arguments
    assert extraction_arguments['filter_value'] == 'CCO', extraction_arguments
    assert extraction_arguments['max_values'] == '40', extraction_arguments
    assert extraction_arguments['extract_mode'] == 'url', extraction_arguments

    print('✅ Reviewer exhaustive row/value expansion passed')
    return True


def test_reviewer_follow_up_derivation_expands_limited_distinct_value_lists():
    """Verify exhaustive list questions can rerun get_distinct_values with a higher max_values limit."""
    print('🔍 Testing reviewer exhaustive distinct-value expansion...')

    helpers, _ = load_route_helpers()
    derive_follow_ups = helpers['derive_tabular_follow_up_calls_from_invocations']

    initial_invocation = FakeInvocation(
        'get_distinct_values',
        {
            'filename': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
            'sheet_name': 'Legal',
            'column': 'Location',
            'filter_column': 'Location',
            'filter_operator': 'contains',
            'filter_value': 'SharePoint',
            'normalize_match': 'false',
            'max_values': '25',
            'source': 'group',
            'group_id': '93aa364a-99ee-4cfd-8e4d-f37d175f00f5',
        },
        '{"filename": "CCO-Legal File Plan 2025_Final Approved.xlsx", "selected_sheet": "Legal", "column": "Location", "distinct_count": 40, "returned_values": 25, "values_limited": true, "values": ["https://contoso.sharepoint.com/sites/Site01", "https://contoso.sharepoint.com/sites/Site02"]}'
    )

    follow_up_calls = derive_follow_ups(
        'List all SharePoint sites in the Legal worksheet',
        [initial_invocation],
    )

    assert len(follow_up_calls) == 1, follow_up_calls
    assert follow_up_calls[0]['function_name'] == 'get_distinct_values', follow_up_calls
    expanded_arguments = follow_up_calls[0]['arguments']
    assert expanded_arguments['max_values'] == '40', expanded_arguments
    assert expanded_arguments['sheet_name'] == 'Legal', expanded_arguments
    assert expanded_arguments['column'] == 'Location', expanded_arguments

    print('✅ Reviewer exhaustive distinct-value expansion passed')
    return True


def test_route_contains_llm_reviewer_recovery_and_version_bump():
    """Verify the route wires in reviewer recovery and the config version bump."""
    print('🔍 Testing reviewer recovery route wiring...')

    _, source = load_route_helpers()

    required_snippets = [
        'You are a tabular recovery planner.',
        'Return JSON only with this schema:',
        'maybe_recover_tabular_analysis_with_llm_reviewer(',
        'Reviewer recovery produced computed analytical tool results',
        'For deterministic how-many, discrete, unique, or canonical-list questions, prefer count_rows or get_distinct_values',
        'When the user is asking where a topic, phrase, code, path, identifier, or other value appears and the relevant column is unclear, prefer search_rows.',
        'When the user wants values from a subset or pattern within one column, prefer get_distinct_values with filter_column/filter_operator/filter_value',
        'When the answer depends on two literal column conditions, prefer count_rows, get_distinct_values, or filter_rows with filter_column/filter_operator/filter_value plus additional_filter_column/additional_filter_operator/additional_filter_value',
        "When the user is asking for URLs, sites, links, or regex-like identifiers embedded inside a text cell, prefer get_distinct_values with extract_mode='url' or extract_mode='regex'",
        'If whether an embedded URL or identifier counts depends on surrounding text in the original cell rather than the extracted value itself, search/filter the original text column first.',
        'If a prior tool result is limited and the user explicitly asked for the full list, rerun with a higher max_rows or max_values instead of stopping at the preview slice.',
        'Do not classify extracted URLs solely by whether the URL text itself contains the keyword when the original cell text already defines the category.',
        'For URLs, links, paths, and literal identifiers, set normalize_match=false unless normalization is clearly necessary.',
        'If a prior result reports total_matches > returned_rows or distinct_count > returned_values for a full-list question, rerun with a higher max_rows or max_values before answering.',
        'derive_tabular_follow_up_calls_from_invocations(',
        'infer_tabular_secondary_filter_from_rows(',
        'Reviewer recovery executed automatic analytical follow-up calls',
        'follow_up_round',
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f'Missing reviewer recovery snippets: {missing}'
    assert read_config_version() == '0.240.049'

    print('✅ Reviewer recovery route wiring passed')
    return True


if __name__ == '__main__':
    tests = [
        test_reviewer_json_extraction_handles_markdown_wrapping,
        test_reviewer_plan_normalizes_prefixed_function_names,
        test_reviewer_call_argument_resolution_injects_group_context,
        test_reviewer_follow_up_derivation_adds_row_context_and_url_extraction,
        test_reviewer_follow_up_derivation_broadens_zero_match_same_column_filter,
        test_reviewer_follow_up_derivation_infers_cohort_column_from_row_context,
        test_reviewer_follow_up_derivation_expands_limited_search_rows_and_extraction_values,
        test_reviewer_follow_up_derivation_expands_limited_distinct_value_lists,
        test_route_contains_llm_reviewer_recovery_and_version_bump,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)