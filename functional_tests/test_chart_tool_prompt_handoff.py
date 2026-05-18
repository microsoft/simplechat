#!/usr/bin/env python3
"""
Functional test for chart-tool prompt handoff.
Version: 0.241.033
Implemented in: 0.241.031; proactive chart guidance updated in 0.241.033

This test ensures chart requests sent to a selected agent are nudged toward the
inline chart action instead of ASCII pseudo-charts. It also verifies the shared
proactive chart guidance helper can be used by the isolated route helper tests.
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
    'user_requested_chart_visualization',
    'build_chart_tool_usage_system_message',
    'insert_system_message_after_existing_system_messages',
    'maybe_append_chart_tool_system_message',
}


def load_prompt_helpers():
    """Load only the chart prompt helpers from the chat route source."""
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        route_content = file_handle.read()

    parsed = ast.parse(route_content, filename=ROUTE_FILE)
    selected_nodes = []
    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    from functions_chart_operations import (  # pylint: disable=import-error,import-outside-toplevel
        build_proactive_chart_guidance_message,
        user_request_supports_proactive_charts,
    )

    namespace = {
        're': re,
        'build_proactive_chart_guidance_message': build_proactive_chart_guidance_message,
        'user_request_supports_proactive_charts': user_request_supports_proactive_charts,
    }
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, route_content


def test_chart_request_detection_distinguishes_visual_requests():
    """Verify chart detection catches visualization asks without matching common non-visual phrases."""
    print('Testing chart request detection...')

    helpers, _ = load_prompt_helpers()
    detect_chart_request = helpers['user_requested_chart_visualization']

    assert detect_chart_request('Which airlines have the shortest gate turnaround times? Include table and chart') is True
    assert detect_chart_request('Show a bar chart of monthly revenue and a table') is True
    assert detect_chart_request('Plot the latency trend by region') is True
    assert detect_chart_request('Show me the chart of accounts for this tenant') is False
    assert detect_chart_request('Can you chart out a migration plan?') is False

    print('PASS: chart request detection')


def test_chart_handoff_message_is_inserted_once_before_user_messages():
    """Verify chart-tool guidance is inserted once and stays in the system-message prefix."""
    print('Testing chart handoff insertion...')

    helpers, _ = load_prompt_helpers()
    maybe_append = helpers['maybe_append_chart_tool_system_message']
    build_message = helpers['build_chart_tool_usage_system_message']

    history = [
        {'role': 'system', 'content': 'Existing system guidance'},
        {'role': 'user', 'content': 'Which airlines have the shortest gate turnaround times? Include table and chart'},
    ]

    updated_history = maybe_append(history, history[-1]['content'], object())
    expected_message = build_message()

    assert len(updated_history) == 3, updated_history
    assert updated_history[0]['role'] == 'system', updated_history
    assert updated_history[1]['role'] == 'system', updated_history
    assert updated_history[1]['content'] == expected_message, updated_history
    assert updated_history[2]['role'] == 'user', updated_history

    maybe_append(updated_history, history[-1]['content'], object())
    assert len(updated_history) == 3, updated_history

    print('PASS: chart handoff insertion')


def test_route_uses_chart_handoff_helper_in_agent_paths():
    """Verify both non-streaming and streaming agent paths call the shared helper."""
    print('Testing route helper usage...')

    _, route_content = load_prompt_helpers()
    helper_call_count = route_content.count('maybe_append_chart_tool_system_message(')

    assert helper_call_count >= 2, helper_call_count

    print('PASS: route helper usage')


if __name__ == '__main__':
    tests = [
        test_chart_request_detection_distinguishes_visual_requests,
        test_chart_handoff_message_is_inserted_once_before_user_messages,
        test_route_uses_chart_handoff_helper_in_agent_paths,
    ]

    results = []
    for test in tests:
        print(f'Running {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'FAIL: {exc}')
            results.append(False)

    sys.exit(0 if all(results) else 1)