# test_tabular_tool_error_retry_and_thoughts.py
#!/usr/bin/env python3
"""
Functional test for tabular tool-error retry and thought visibility fix.
Version: 0.261.057
Implemented in: 0.239.037
Updated in: 0.261.057 (required-tool continuation fix; version bump deferred)

This test ensures that analytical tabular tool calls returning JSON error
payloads are treated as failed attempts, are retried instead of being accepted
as completed analysis, and surface clearer thought details for recovery.
"""

import ast
import asyncio
import json
import os
import sys
from types import SimpleNamespace

import httpx
from openai import AsyncAzureOpenAI
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion, AzureChatPromptExecutionSettings
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.filters import FilterTypes
from semantic_kernel.functions import kernel_function

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'application', 'single_app'))

ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
PLUGIN_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'semantic_kernel_plugins',
    'tabular_processing_plugin.py',
)
TARGET_FUNCTIONS = {
    'allow_tabular_completion_after_initial_tools',
    'get_tabular_discovery_function_names',
    'get_tabular_analysis_function_names',
    'get_tabular_thought_excluded_parameter_names',
    'get_tabular_invocation_result_payload',
    'get_tabular_invocation_error_message',
    'split_tabular_analysis_invocations',
    'summarize_tabular_invocation_errors',
    'filter_tabular_citation_invocations',
    'format_tabular_thought_parameter_value',
    'get_tabular_tool_thought_payloads',
    'get_tabular_status_thought_payloads',
}


def load_tabular_plugin_constants():
    """Extract TabularProcessingPlugin tuple constants from AST without booting config.py."""
    with open(PLUGIN_FILE, 'r', encoding='utf-8') as file_handle:
        plugin_content = file_handle.read()

    parsed = ast.parse(plugin_content, filename=PLUGIN_FILE)
    constants = {}
    target_names = {
        'DISCOVERY_FUNCTION_NAMES',
        'ANALYSIS_FUNCTION_NAMES',
        'THOUGHT_EXCLUDED_PARAMETER_NAMES',
    }
    for node in parsed.body:
        if isinstance(node, ast.ClassDef) and node.name == 'TabularProcessingPlugin':
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id in target_names:
                            constants[target.id] = list(ast.literal_eval(item.value))
    return constants


def load_tabular_route_helpers():
    """Load selected helper functions from the chat route source."""
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        route_content = file_handle.read()

    parsed = ast.parse(route_content, filename=ROUTE_FILE)
    selected_nodes = []

    for node in parsed.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in TARGET_FUNCTIONS:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {'json': json}
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    plugin_constants = load_tabular_plugin_constants()
    namespace['get_tabular_discovery_function_names'] = lambda: list(plugin_constants['DISCOVERY_FUNCTION_NAMES'])
    namespace['get_tabular_analysis_function_names'] = lambda: list(plugin_constants['ANALYSIS_FUNCTION_NAMES'])
    namespace['get_tabular_thought_excluded_parameter_names'] = lambda: list(plugin_constants['THOUGHT_EXCLUDED_PARAMETER_NAMES'])
    return namespace, route_content


def test_tool_error_payload_is_classified_as_failed_analysis():
    """Verify JSON error payloads are treated as failed analytical tool calls."""
    print("🔍 Testing tabular tool error classification...")

    try:
        helpers, _ = load_tabular_route_helpers()
        get_error_message = helpers['get_tabular_invocation_error_message']
        split_analysis_invocations = helpers['split_tabular_analysis_invocations']
        filter_citations = helpers['filter_tabular_citation_invocations']
        failed_result_payload = json.dumps({
            'error': "aggregate_column is required unless operation='count'."
        })

        failed_invocation = SimpleNamespace(
            function_name='group_by_datetime_component',
            result=failed_result_payload,
            error_message=None,
        )

        assert get_error_message(failed_invocation) == "aggregate_column is required unless operation='count'."

        successful_invocations, failed_invocations = split_analysis_invocations([failed_invocation])
        assert len(successful_invocations) == 0, 'Did not expect a successful analytical invocation.'
        assert len(failed_invocations) == 1, 'Expected the analytical invocation to be classified as failed.'
        assert filter_citations([failed_invocation]) == [], 'Failed analytical invocations should not become citations.'

        print("✅ Tabular tool error classification passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_failed_tool_thoughts_and_recovery_status_are_rendered():
    """Verify failed analytical calls produce failed tool thoughts and recovery status thoughts."""
    print("🔍 Testing tabular failure thought payloads...")

    try:
        helpers, _ = load_tabular_route_helpers()
        get_tool_payloads = helpers['get_tabular_tool_thought_payloads']
        get_status_payloads = helpers['get_tabular_status_thought_payloads']
        failed_result_payload = json.dumps({
            'error': "aggregate_column is required unless operation='count'."
        })

        failed_invocation = SimpleNamespace(
            function_name='group_by_datetime_component',
            duration_ms=168.5,
            success=True,
            parameters={
                'filename': 'faa_flight_operations_dataset.csv',
                'datetime_component': 'hour',
                'source': 'workspace',
            },
            result=failed_result_payload,
            error_message=None,
        )

        tool_payloads = get_tool_payloads([failed_invocation])
        status_payloads = get_status_payloads([failed_invocation], analysis_succeeded=True)

        assert tool_payloads[0][0] == 'Tabular tool group_by_datetime_component on faa_flight_operations_dataset.csv (168ms) failed'
        assert "error=aggregate_column is required unless operation='count'." in tool_payloads[0][1]
        assert 'success=False' in tool_payloads[0][1]
        assert status_payloads == [(
            'Tabular analysis recovered via internal fallback after tool errors',
            "aggregate_column is required unless operation='count'."
        )], status_payloads

        print("✅ Tabular failure thought payloads passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_route_contains_retry_feedback_for_tool_errors():
    """Verify the route feeds previous tool errors back into retry attempts."""
    print("🔍 Testing route retry feedback for tool errors...")

    try:
        _, route_content = load_tabular_route_helpers()

        checks = {
            'tool error prompt feedback': 'PREVIOUS TOOL ERRORS:' in route_content,
            'tool error retry logging': 'used analytical tool(s) but all returned errors; retrying' in route_content,
            'fallback recovery thought': 'Tabular analysis recovered via internal fallback after tool errors' in route_content,
        }

        failed_checks = [name for name, passed in checks.items() if not passed]
        assert not failed_checks, f"Missing expected tool-error retry behavior: {failed_checks}"

        print("✅ Route retry feedback for tool errors passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


async def run_tool_choice_probe(*, required=True, tool_rounds=1, parallel_calls=1, tool_error=False):
    """Exercise the shipped filter through a real SK loop with mocked model HTTP."""
    helpers, route_content = load_tabular_route_helpers()
    requests = []
    tool_calls = []

    class ProbePlugin:
        @kernel_function(name='inspect_table', description='Inspect a synthetic table')
        def inspect_table(self) -> str:
            tool_calls.append('inspect_table')
            return json.dumps({'error': 'synthetic tool error'} if tool_error else {'row_count': 15})

        @kernel_function(name='excluded_tool', description='A tool outside this run allowlist')
        def excluded_tool(self) -> str:
            raise AssertionError('Excluded tool must not execute')

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        request_number = len(requests)
        if request_number <= tool_rounds:
            message = {
                'role': 'assistant', 'content': None,
                'tool_calls': [
                    {'id': f'call_{request_number}_{call_index}', 'type': 'function',
                     'function': {'name': 'tabular-inspect_table', 'arguments': '{}'}}
                    for call_index in range(parallel_calls)
                ],
            }
            finish_reason = 'tool_calls'
        else:
            message = {'role': 'assistant', 'content': 'Synthetic answer'}
            finish_reason = 'stop'
        return httpx.Response(200, json={
            'id': f'completion_{request_number}', 'object': 'chat.completion', 'created': 1,
            'model': 'probe-model',
            'choices': [{'index': 0, 'message': message, 'finish_reason': finish_reason}],
        })

    async with AsyncAzureOpenAI(
        api_key='synthetic-key', azure_endpoint='https://example.invalid', api_version='2024-10-21',
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)), max_retries=0,
    ) as client:
        service = AzureChatCompletion(service_id='probe', deployment_name='probe-model', async_client=client)
        kernel = Kernel()
        kernel.add_plugin(ProbePlugin(), plugin_name='tabular')
        kernel.add_filter(FilterTypes.AUTO_FUNCTION_INVOCATION, helpers['allow_tabular_completion_after_initial_tools'])
        history = ChatHistory()
        history.add_user_message('Describe this synthetic table')
        behavior_factory = FunctionChoiceBehavior.Required if required else FunctionChoiceBehavior.Auto
        settings = AzureChatPromptExecutionSettings(function_choice_behavior=behavior_factory(
            maximum_auto_invoke_attempts=20,
            filters={'included_functions': ['tabular-inspect_table']},
        ))
        result = await service.get_chat_message_contents(history, settings, kernel=kernel)

    assert result[0].content == 'Synthetic answer'
    assert len(tool_calls) == tool_rounds * parallel_calls
    assert requests[0]['tool_choice'] == ('required' if required else 'auto')
    assert all(request['tool_choice'] == 'auto' for request in requests[1:])
    for request in requests:
        advertised_tools = [tool['function']['name'] for tool in request['tools']]
        assert advertised_tools == ['tabular-inspect_table']
    assert settings.function_choice_behavior.maximum_auto_invoke_attempts == 20
    assert settings.function_choice_behavior.filters == {'included_functions': ['tabular-inspect_table']}
    assert 'kernel.add_filter(FilterTypes.AUTO_FUNCTION_INVOCATION, allow_tabular_completion_after_initial_tools)' in route_content
    return requests


def test_required_tool_choice_allows_final_answer_after_initial_tools():
    requests = asyncio.run(run_tool_choice_probe())
    assert len(requests) == 2
    return True


def test_required_tool_choice_preserves_dependent_tool_rounds():
    requests = asyncio.run(run_tool_choice_probe(tool_rounds=2))
    assert len(requests) == 3
    return True


def test_required_tool_choice_handles_parallel_initial_tools():
    requests = asyncio.run(run_tool_choice_probe(parallel_calls=3))
    assert len(requests) == 2
    tool_results = [message for message in requests[-1]['messages'] if message['role'] == 'tool']
    assert len(tool_results) == 3
    return True


def test_auto_tool_choice_is_unchanged():
    requests = asyncio.run(run_tool_choice_probe(required=False))
    assert len(requests) == 2
    return True


def test_tool_error_can_be_followed_by_another_tool_round():
    requests = asyncio.run(run_tool_choice_probe(tool_rounds=2, tool_error=True))
    assert len(requests) == 3
    return True


if __name__ == '__main__':
    tests = [
        test_tool_error_payload_is_classified_as_failed_analysis,
        test_failed_tool_thoughts_and_recovery_status_are_rendered,
        test_route_contains_retry_feedback_for_tool_errors,
        test_required_tool_choice_allows_final_answer_after_initial_tools,
        test_required_tool_choice_preserves_dependent_tool_rounds,
        test_required_tool_choice_handles_parallel_initial_tools,
        test_auto_tool_choice_is_unchanged,
        test_tool_error_can_be_followed_by_another_tool_round,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
