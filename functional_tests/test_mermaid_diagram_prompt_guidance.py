#!/usr/bin/env python3
"""
Functional test for Mermaid diagram prompt guidance.
Version: 0.261.028
Implemented in: 0.261.028

SimpleChat renders ```mermaid fences as diagrams, but nothing told the model that, so a
request like "turn this into a diagram" came back as ASCII box art in a ```text fence that
renders as a plain code block. This test ensures diagram requests are detected, that the
guidance names the fence the client actually renders and rules out ASCII art, that the
guidance reaches every generation path, and that the chart guidance no longer contradicts it.
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
    'build_diagram_system_message',
    'insert_system_message_after_existing_system_messages',
    'maybe_append_diagram_system_message',
}

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def load_prompt_helpers():
    """Load only the diagram prompt helpers from the chat route source.

    route_backend_chats.py cannot be imported directly in a test environment, so the
    relevant functions are lifted out of its AST and executed against a small namespace.
    This mirrors test_chart_tool_prompt_handoff.py.
    """
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        route_content = file_handle.read()

    parsed = ast.parse(route_content, filename=ROUTE_FILE)
    selected_nodes = [
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS
    ]

    missing_functions = TARGET_FUNCTIONS - {node.name for node in selected_nodes}
    assert not missing_functions, missing_functions

    module = ast.Module(body=selected_nodes, type_ignores=[])
    from functions_diagram_operations import (  # pylint: disable=import-error,import-outside-toplevel
        build_diagram_guidance_message,
        user_requested_diagram,
    )

    namespace = {
        're': re,
        'build_diagram_guidance_message': build_diagram_guidance_message,
        'user_requested_diagram': user_requested_diagram,
    }
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)  # pylint: disable=exec-used
    return namespace, route_content


def test_app_version_covers_the_fix():
    """The application version must be at least the version this landed in."""
    print('Testing application version...')

    assert_app_version_at_least(
        '0.261.028',
        reason='Mermaid diagram guidance and classic-UI inline rendering landed in 0.261.028.',
    )

    print('PASS: application version')


def test_diagram_request_detection_targets_structural_requests():
    """Diagram detection must catch structural asks and leave data-chart asks alone."""
    print('Testing diagram request detection...')

    from functions_diagram_operations import user_requested_diagram  # pylint: disable=import-error

    # The request that produced ASCII art before this fix.
    assert user_requested_diagram('turn this into a diagram for me') is True
    assert user_requested_diagram('Show me a flowchart of the login process') is True
    assert user_requested_diagram('sequence diagram of the auth handshake') is True
    assert user_requested_diagram('map out the architecture') is True
    assert user_requested_diagram('draw the request flow') is True
    assert user_requested_diagram('Give me an ERD for the orders table') is True
    assert user_requested_diagram('Sketch the deployment topology') is True

    # Chart requests must stay with the chart guidance.
    assert user_requested_diagram('Create a bar chart of revenue by month') is False
    assert user_requested_diagram('Visualize revenue by month') is False
    assert user_requested_diagram('Plot the sales trend') is False
    assert user_requested_diagram('Summarize this document') is False
    assert user_requested_diagram('') is False
    assert user_requested_diagram(None) is False

    # "erd" is matched on a word boundary, not as a substring.
    assert user_requested_diagram('We moved the herd to the north field') is False

    print('PASS: diagram request detection')


def test_diagram_guidance_names_the_mermaid_fence_and_bans_ascii_art():
    """The guidance must point at the renderable fence and rule out the failure mode."""
    print('Testing diagram guidance content...')

    from functions_diagram_operations import (  # pylint: disable=import-error
        DIAGRAM_GUIDANCE_MARKER,
        build_diagram_guidance_message,
    )

    guidance = build_diagram_guidance_message()

    assert guidance.startswith(DIAGRAM_GUIDANCE_MARKER), guidance[:80]
    assert '```mermaid```' in guidance
    assert 'ASCII art' in guidance
    assert '```text```' in guidance
    assert 'box-drawing' in guidance

    # The diagram types the client can actually render.
    for diagram_type in ('flowchart TD', 'sequenceDiagram', 'stateDiagram-v2', 'erDiagram'):
        assert diagram_type in guidance, diagram_type

    # Guardrails that keep generated diagrams parseable and safe.
    assert 'click' in guidance
    assert 'never invent components' in guidance

    print('PASS: diagram guidance content')


def test_append_diagram_guidance_is_idempotent():
    """Appending guidance twice must not duplicate it."""
    print('Testing diagram guidance append...')

    from functions_diagram_operations import (  # pylint: disable=import-error
        DIAGRAM_GUIDANCE_MARKER,
        append_diagram_guidance,
    )

    prompt = 'Draw the request flow through the gateway.'
    appended_once = append_diagram_guidance(prompt)
    appended_twice = append_diagram_guidance(appended_once)

    assert appended_once.count(DIAGRAM_GUIDANCE_MARKER) == 1
    assert appended_twice == appended_once

    # A chart request must be left untouched unless forced.
    assert append_diagram_guidance('Plot the sales trend') == 'Plot the sales trend'
    assert DIAGRAM_GUIDANCE_MARKER in append_diagram_guidance('Plot the sales trend', force=True)

    print('PASS: diagram guidance append')


def test_diagram_guidance_is_inserted_once_in_the_system_prefix():
    """Guidance is inserted after existing system messages and never duplicated."""
    print('Testing diagram guidance insertion...')

    helpers, _ = load_prompt_helpers()
    maybe_append = helpers['maybe_append_diagram_system_message']
    build_message = helpers['build_diagram_system_message']

    history = [
        {'role': 'system', 'content': 'Existing system guidance'},
        {'role': 'user', 'content': 'turn this into a diagram for me'},
    ]

    updated_history = maybe_append(history, history[-1]['content'], object())
    expected_message = build_message()

    assert len(updated_history) == 3, updated_history
    assert updated_history[0]['role'] == 'system'
    assert updated_history[1] == {'role': 'system', 'content': expected_message}
    assert updated_history[2]['role'] == 'user'

    # A second pass must not add it again.
    updated_again = maybe_append(updated_history, history[-1]['content'], object())
    assert len(updated_again) == 3, updated_again

    # A non-diagram request leaves the history alone.
    chart_history = [{'role': 'user', 'content': 'Plot the sales trend'}]
    assert maybe_append(chart_history, chart_history[0]['content'], None) == chart_history

    print('PASS: diagram guidance insertion')


def test_diagram_guidance_is_wired_into_every_generation_path():
    """Every path that appends chart guidance must also append diagram guidance."""
    print('Testing diagram guidance wiring...')

    _, route_content = load_prompt_helpers()

    chart_call_count = route_content.count('conversation_history_for_api = maybe_append_chart_tool_system_message(')
    diagram_call_count = route_content.count('conversation_history_for_api = maybe_append_diagram_system_message(')

    assert chart_call_count >= 3, chart_call_count
    assert diagram_call_count == chart_call_count, (diagram_call_count, chart_call_count)

    print('PASS: diagram guidance wiring')


def test_chart_guidance_no_longer_bans_structural_mermaid_diagrams():
    """Chart guidance must not steer the model away from diagrams it should be drawing."""
    print('Testing chart guidance compatibility...')

    from functions_chart_operations import (  # pylint: disable=import-error
        build_proactive_chart_guidance_message,
    )

    chart_guidance = build_proactive_chart_guidance_message()

    # The old wording flatly banned Mermaid, which fought the diagram guidance.
    assert 'Do not output Mermaid, matplotlib/Python, Vega' not in chart_guidance
    assert 'Mermaid is not a substitute for a data chart' in chart_guidance
    assert '```mermaid```' in chart_guidance

    print('PASS: chart guidance compatibility')


if __name__ == '__main__':
    tests = [
        test_app_version_covers_the_fix,
        test_diagram_request_detection_targets_structural_requests,
        test_diagram_guidance_names_the_mermaid_fence_and_bans_ascii_art,
        test_append_diagram_guidance_is_idempotent,
        test_diagram_guidance_is_inserted_once_in_the_system_prefix,
        test_diagram_guidance_is_wired_into_every_generation_path,
        test_chart_guidance_no_longer_bans_structural_mermaid_diagrams,
    ]

    results = []
    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:  # pylint: disable=broad-except
            print(f'Test failed: {exc}')
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if all(results) else 1)
