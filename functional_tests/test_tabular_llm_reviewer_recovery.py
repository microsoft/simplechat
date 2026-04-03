#!/usr/bin/env python3
# test_tabular_llm_reviewer_recovery.py
"""
Functional test for multi-sheet tabular LLM reviewer recovery.
Version: 0.240.041
Implemented in: 0.240.035; 0.240.036; 0.240.037; 0.240.038; 0.240.039; 0.240.040; 0.240.041

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
    'extract_json_object_from_text',
    'normalize_tabular_reviewer_function_name',
    'parse_tabular_reviewer_plan',
    'resolve_tabular_reviewer_call_arguments',
}


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
        'Do not classify extracted URLs solely by whether the URL text itself contains the keyword when the original cell text already defines the category.',
        'For URLs, links, paths, and literal identifiers, set normalize_match=false unless normalization is clearly necessary.',
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f'Missing reviewer recovery snippets: {missing}'
    assert read_config_version() == '0.240.041'

    print('✅ Reviewer recovery route wiring passed')
    return True


if __name__ == '__main__':
    tests = [
        test_reviewer_json_extraction_handles_markdown_wrapping,
        test_reviewer_plan_normalizes_prefixed_function_names,
        test_reviewer_call_argument_resolution_injects_group_context,
        test_route_contains_llm_reviewer_recovery_and_version_bump,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)