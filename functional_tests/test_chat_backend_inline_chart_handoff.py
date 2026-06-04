#!/usr/bin/env python3
# test_chat_backend_inline_chart_handoff.py
"""
Functional test for chat backend inline chart handoff.
Version: 0.241.134
Implemented in: 0.241.124

This test ensures normal chat requests can receive inline chart guidance, explicit
chart requests can use the core conversation chart plugin without selecting an
agent, and backend-appended chart blocks can stream before final message save.
"""

import ast
import re
import sys
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / 'application' / 'single_app'
ROUTE_FILE = APP_ROOT / 'route_backend_chats.py'
CONFIG_FILE = APP_ROOT / 'config.py'
EXPECTED_VERSION = '0.241.134'

TARGET_FUNCTIONS = {
    '_append_inline_chart_blocks_to_message',
    '_collect_inline_chart_blocks',
    '_get_appended_inline_chart_content_delta',
    '_normalize_inline_chart_markdown',
    'build_chart_tool_usage_system_message',
    'insert_system_message_after_existing_system_messages',
    'maybe_append_chart_tool_system_message',
    'user_requested_chart_visualization',
}


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


def load_route_chart_helpers():
    """Load only the chart helper functions from route_backend_chats.py."""
    route_content = read_text(ROUTE_FILE)
    parsed = ast.parse(route_content, filename=str(ROUTE_FILE))
    selected_nodes = [
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS
    ]

    if str(APP_ROOT) not in sys.path:
        sys.path.insert(0, str(APP_ROOT))

    from functions_chart_operations import (  # pylint: disable=import-error,import-outside-toplevel
        INLINE_CHART_BLOCK_LANGUAGE,
        build_proactive_chart_guidance_message,
        user_request_supports_proactive_charts,
    )

    namespace = {
        'INLINE_CHART_BLOCK_LANGUAGE': INLINE_CHART_BLOCK_LANGUAGE,
        'INLINE_CHART_ID_PATTERN_TEMPLATE': '"chartId":"{}"',
        'build_proactive_chart_guidance_message': build_proactive_chart_guidance_message,
        're': re,
        'user_request_supports_proactive_charts': user_request_supports_proactive_charts,
    }
    exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), str(ROUTE_FILE), 'exec'), namespace)
    return namespace, route_content


def test_version_matches_feature_header():
    """Validate the feature test header tracks the current app version."""
    print('Testing version header...')
    assert read_current_version() == EXPECTED_VERSION
    print('PASS: version header')


def test_standard_chat_fallback_receives_chart_guidance():
    """Validate chart guidance is applied before raw GPT fallback for normal chat."""
    print('Testing standard chat chart guidance fallback...')
    _, route_content = load_route_chart_helpers()

    expected_block = (
        'conversation_history_for_api = maybe_append_chart_tool_system_message(\n'
        '                conversation_history_for_api,\n'
        '                user_message,\n'
        '                selected_agent,\n'
        '            )\n\n'
        '            thought_tracker.add_thought(\'generation\''
    )
    assert expected_block in route_content
    print('PASS: standard chat chart guidance fallback')


def test_explicit_chart_request_can_use_kernel_without_agent():
    """Validate explicit chart asks are allowed to use kernel chart tools without agents."""
    print('Testing model-only kernel chart fallback...')
    _, route_content = load_route_chart_helpers()

    assert 'explicit_chart_request = user_requested_chart_visualization(user_message)' in route_content
    assert 'if kernel and (selected_agent or explicit_chart_request):' in route_content
    assert 'settings_obj.function_choice_behavior = FunctionChoiceBehavior.Auto(maximum_auto_invoke_attempts=20)' in route_content
    assert '_append_new_plugin_invocation_citations(' in route_content
    print('PASS: model-only kernel chart fallback')


def test_backend_appends_chart_blocks_and_streams_delta():
    """Validate chart markdown from tool results can be appended and streamed as a delta."""
    print('Testing backend chart block append and stream delta...')
    helpers, route_content = load_route_chart_helpers()
    append_charts = helpers['_append_inline_chart_blocks_to_message']
    get_delta = helpers['_get_appended_inline_chart_content_delta']

    chart_markdown = (
        '```simplechart\n'
        '{"version":1,"kind":"bar","chartType":"bar","chartId":"normal-chat-chart",'
        '"title":"Revenue","data":{"labels":["Jan"],"datasets":[{"label":"Revenue","data":[12]}]}}\n'
        '```'
    )
    original_content = 'Revenue increased in January.'
    citation_payload = [{
        'function_result': {
            'chart_payload': {'chartId': 'normal-chat-chart'},
            'chart_markdown': chart_markdown,
        },
    }]

    updated_content = append_charts(original_content, citation_payload)
    assert chart_markdown in updated_content
    assert append_charts(updated_content, citation_payload) == updated_content

    appended_delta = get_delta(original_content, updated_content)
    assert chart_markdown in appended_delta
    assert "yield f\"data: {json.dumps({'content': appended_chart_content})}\\n\\n\"" in route_content
    print('PASS: backend chart block append and stream delta')


def run_tests():
    """Run functional tests."""
    tests = [
        test_version_matches_feature_header,
        test_standard_chat_fallback_receives_chart_guidance,
        test_explicit_chart_request_can_use_kernel_without_agent,
        test_backend_appends_chart_blocks_and_streams_delta,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'FAIL: {exc}')
            traceback.print_exc()
            results.append(False)

    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    return all(results)


if __name__ == '__main__':
    sys.exit(0 if run_tests() else 1)