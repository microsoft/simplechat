#!/usr/bin/env python3
# test_tabular_inline_chart_handoff.py
"""
Functional test for tabular inline chart handoff.
Version: 0.241.166
Implemented in: 0.241.166

This test ensures grouped tabular analysis results can be converted into
SimpleChat inline chart citations so chart requests render with simplechart
instead of returning unsupported chart code blocks such as Mermaid.
"""

import ast
import json
import logging
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / 'application' / 'single_app'
ROUTE_FILE = APP_ROOT / 'route_backend_chats.py'
CONFIG_FILE = APP_ROOT / 'config.py'
CHART_OPERATIONS_FILE = APP_ROOT / 'functions_chart_operations.py'
EXPECTED_VERSION = '0.241.166'

TARGET_FUNCTIONS = {
    '_build_tabular_inline_chart_subtitle',
    '_build_tabular_inline_chart_title',
    '_coerce_tabular_chart_number',
    '_get_requested_tabular_chart_kind',
    '_get_tabular_inline_chart_result_items',
    '_humanize_tabular_chart_label',
    '_select_tabular_inline_chart_kind',
    'build_tabular_inline_chart_citations',
    'get_tabular_invocation_error_message',
    'get_tabular_invocation_result_payload',
    'user_requested_chart_visualization',
}


class FakeChartPlugin:
    """Stand-in chart plugin that returns SimpleChat chart markdown."""

    def create_chart(
        self,
        chart_type,
        chart_data_json,
        title='',
        subtitle='',
        description='',
        x_axis_label='',
        y_axis_label='',
        options_json='',
    ):
        chart_data = json.loads(chart_data_json)
        options = json.loads(options_json) if options_json else {}
        chart_payload = {
            'version': 1,
            'kind': chart_type,
            'chartType': chart_type,
            'chartId': 'tabular-inline-chart-test',
            'title': title,
            'subtitle': subtitle,
            'description': description,
            'xAxisLabel': x_axis_label,
            'yAxisLabel': y_axis_label,
            'data': chart_data,
            'options': options,
        }
        return {
            'success': True,
            'chart_payload': chart_payload,
            'chart_markdown': '```simplechart\n' + json.dumps(chart_payload, separators=(',', ':')) + '\n```',
        }


class FakeInvocation:
    """Small stand-in for plugin invocation objects used by route helpers."""

    def __init__(self, function_name, result, error_message=None):
        self.function_name = function_name
        self.result = result
        self.error_message = error_message
        self.user_id = 'test-user-12345'


def read_text(path):
    """Read a UTF-8 source file."""
    return path.read_text(encoding='utf-8')


def read_current_version():
    """Return the current app version from config.py."""
    for line in read_text(CONFIG_FILE).splitlines():
        stripped_line = line.strip()
        if stripped_line.startswith('VERSION = '):
            return stripped_line.split('"')[1]
    raise AssertionError('Expected config.py to define VERSION')


def load_tabular_chart_helpers():
    """Load selected tabular chart helpers from route_backend_chats.py."""
    route_content = read_text(ROUTE_FILE)
    parsed = ast.parse(route_content, filename=str(ROUTE_FILE))
    selected_nodes = [
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS
    ]

    namespace = {
        'CORE_CHART_PLUGIN_NAME': 'conversation_charts',
        'ChartPlugin': FakeChartPlugin,
        'TABULAR_INLINE_CHART_MAX_POINTS': 12,
        'TABULAR_INLINE_CHART_MAX_CHARTS': 2,
        'TABULAR_INLINE_CHARTABLE_FUNCTIONS': {'group_by_aggregate', 'group_by_datetime_component'},
        'TABULAR_INLINE_CHART_SUPPORTED_GROUP_KINDS': {
            'bar',
            'line',
            'pie',
            'doughnut',
            'area',
            'radar',
            'stacked_bar',
            'stacked_line',
        },
        'datetime': datetime,
        'json': json,
        'logging': logging,
        'log_event': lambda *args, **kwargs: None,
        'make_json_serializable': lambda value: value,
        'normalize_chart_kind': lambda chart_kind: {'donut': 'doughnut'}.get(chart_kind, chart_kind),
        're': re,
        'user_request_supports_proactive_charts': lambda user_message: False,
    }
    exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), str(ROUTE_FILE), 'exec'), namespace)
    return namespace, route_content


def test_version_matches_feature_header():
    """Validate the feature test header tracks the current app version."""
    print('Testing version header...')
    assert read_current_version() == EXPECTED_VERSION
    print('PASS: version header')


def test_group_by_totals_create_simplechart_pie_citation():
    """Validate grouped totals can become a SimpleChat pie chart citation."""
    print('Testing grouped totals chart citation...')
    helpers, _ = load_tabular_chart_helpers()
    build_citations = helpers['build_tabular_inline_chart_citations']
    result_payload = {
        'filename': 'Sample - Superstore.xlsx',
        'selected_sheet': 'Orders',
        'group_by': 'Category',
        'aggregate_column': 'Sales',
        'operation': 'sum',
        'groups': 3,
        'top_results': {
            'Technology': 839893.279,
            'Furniture': 754747.7613,
            'Office Supplies': 731893.314,
        },
        'result': {
            'Furniture': 754747.7613,
            'Office Supplies': 731893.314,
            'Technology': 839893.279,
        },
    }
    invocations = [FakeInvocation('group_by_aggregate', json.dumps(result_payload))]

    citations = build_citations(
        'Can you get totals for each possible value in Category and generate a pie chart?',
        invocations,
    )

    assert len(citations) == 1
    citation = citations[0]
    assert citation['plugin_name'] == 'conversation_charts'
    assert citation['function_name'] == 'create_chart'
    assert citation['function_arguments']['chart_type'] == 'pie'
    chart_markdown = citation['function_result']['chart_markdown']
    assert chart_markdown.startswith('```simplechart\n'), chart_markdown
    assert 'pie showData' not in chart_markdown
    assert 'mermaid' not in chart_markdown.lower()
    assert 'Technology' in chart_markdown
    assert 'Office Supplies' in chart_markdown
    print('PASS: grouped totals chart citation')


def test_route_wires_tabular_chart_citations_into_all_success_paths():
    """Validate workspace and chat-upload tabular paths call the chart helper."""
    print('Testing route tabular chart handoff wiring...')
    _, route_content = load_tabular_chart_helpers()
    assert route_content.count('= build_tabular_inline_chart_citations(user_message,') == 4
    assert 'tabular_chart_citations = build_tabular_inline_chart_citations(user_message, tabular_invocations)' in route_content
    assert 'chat_tabular_chart_citations = build_tabular_inline_chart_citations(user_message, chat_tabular_invocations)' in route_content
    assert '_append_inline_chart_blocks_to_message(accumulated_content, agent_citations_list)' in route_content
    print('PASS: route tabular chart handoff wiring')


def test_chart_guidance_rejects_mermaid_as_visual_response():
    """Validate reusable chart guidance steers model output to SimpleChat charts."""
    print('Testing reusable chart guidance wording...')
    chart_operations_source = read_text(CHART_OPERATIONS_FILE)
    assert 'Use SimpleChat inline chart blocks only' in chart_operations_source
    assert 'Do not output Mermaid' in chart_operations_source
    print('PASS: reusable chart guidance wording')


def run_tests():
    """Run functional tests."""
    tests = [
        test_version_matches_feature_header,
        test_group_by_totals_create_simplechart_pie_citation,
        test_route_wires_tabular_chart_citations_into_all_success_paths,
        test_chart_guidance_rejects_mermaid_as_visual_response,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'FAIL: {test.__name__}: {exc}')
            traceback.print_exc()
            results.append(False)

    passed = sum(results)
    total = len(results)
    print(f'\nResults: {passed}/{total} tests passed')
    return passed == total


if __name__ == '__main__':
    sys.exit(0 if run_tests() else 1)