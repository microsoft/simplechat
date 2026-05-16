# test_document_action_token_usage_aggregation.py
"""
Functional test for document action token usage aggregation.
Version: 0.241.023
Implemented in: 0.241.116

This test ensures analysis and comparison aggregate tokens across
all internal model calls and persist the aggregate usage on assistant metadata.
"""

import ast
import os
import uuid


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_RUNNER_PATH = os.path.join(REPO_ROOT, 'application', 'single_app', 'functions_workflow_runner.py')
CHAT_ROUTE_PATH = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_backend_chats.py')
CONFIG_PATH = os.path.join(REPO_ROOT, 'application', 'single_app', 'config.py')


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f'{label}: expected {expected!r}, got {actual!r}')


def assert_in(needle, haystack, label):
    if needle not in haystack:
        raise AssertionError(f'{label}: missing {needle!r}')


def load_functions(file_path, function_names, extra_globals=None):
    with open(file_path, 'r', encoding='utf-8') as handle:
        source = handle.read()

    module_ast = ast.parse(source, filename=file_path)
    selected_nodes = [
        node for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    compiled_module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(compiled_module)

    namespace = {'__builtins__': __builtins__}
    if extra_globals:
        namespace.update(extra_globals)

    exec(compile(compiled_module, file_path, 'exec'), namespace)
    return namespace


class FakeUsage:
    def __init__(self, prompt_tokens, completion_tokens, total_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content, prompt_tokens, completion_tokens, total_tokens):
        self.usage = FakeUsage(prompt_tokens, completion_tokens, total_tokens)
        self.choices = [FakeChoice(content)]


class FakeChatCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, model, messages):
        self.calls.append({'model': model, 'messages': messages})
        if not self._responses:
            raise AssertionError('No fake responses left for completion create call')
        content, prompt_tokens, completion_tokens, total_tokens = self._responses.pop(0)
        return FakeCompletion(content, prompt_tokens, completion_tokens, total_tokens)


class FakeClient:
    def __init__(self, responses):
        self.chat = type('FakeChat', (), {'completions': FakeChatCompletions(responses)})()


class FakeContainer:
    def __init__(self):
        self.items = []

    def upsert_item(self, item):
        self.items.append(item)


def test_document_analysis_token_aggregation():
    print('Testing analysis token aggregation...')

    fake_client = FakeClient([
        ('window one', 110, 25, 135),
        ('window two', 90, 15, 105),
    ])

    namespace = load_functions(
        WORKFLOW_RUNNER_PATH,
        {
            '_coerce_token_count',
            '_extract_token_usage',
            '_create_token_usage_aggregate',
            '_accumulate_token_usage',
            '_finalize_token_usage',
            '_execute_document_analysis_workflow',
        },
        extra_globals={
            'DOCUMENT_ACTION_TYPE_ANALYZE': 'analyze',
            'DOCUMENT_ACTION_CONTEXT_WORKFLOW': 'workflow',
            'get_document_action_max_documents': lambda *args, **kwargs: 10,
            '_chain_activity_callbacks': lambda *callbacks: None,
            '_build_document_action_activity_callback': lambda *args, **kwargs: None,
            '_maybe_execute_tabular_document_action': lambda *args, **kwargs: None,
            '_maybe_create_document_analysis_generated_artifacts': lambda *args, **kwargs: {'artifacts': [], 'assistant_reply': None},
            '_resolve_model_workflow_client': lambda *args, **kwargs: (fake_client, 'gpt-5.4', 'aoai'),
            'run_document_analysis': lambda **kwargs: (
                kwargs['invoke_prompt']('analysis window 1', stage='window_analysis'),
                kwargs['invoke_prompt']('analysis window 2', stage='reduction'),
                {
                    'reply': 'Aggregated analysis answer',
                    'coverage': {
                        'processed_windows': 2,
                        'failed_windows': 0,
                    },
                }
            )[-1],
            '_resolve_document_action_reply': lambda result: result.get('reply', ''),
            '_extract_message_text': lambda content: content,
            'debug_print': lambda *args, **kwargs: None,
        },
    )

    result = namespace['_execute_document_analysis_workflow'](
        {
            'id': 'workflow-analysis-1',
            'user_id': 'user-1',
            'runner_type': 'model',
            'task_prompt': 'Analyze the selected documents',
        },
        settings={},
        conversation_id='conversation-1',
        run_id='run-analysis-1',
        action_config={
            'type': 'analyze',
            'document_ids': ['doc-1', 'doc-2'],
        },
    )

    assert_equal(
        result.get('token_usage'),
        {
            'prompt_tokens': 200,
            'completion_tokens': 40,
            'total_tokens': 240,
            'request_count': 2,
        },
        'analysis token aggregation',
    )
    print('Document analysis token aggregation passed.')
    return True


def test_document_comparison_token_aggregation():
    print('Testing document comparison token aggregation...')

    fake_client = FakeClient([
        ('summary one', 70, 10, 80),
        ('summary two', 60, 10, 70),
        ('comparison', 90, 20, 110),
    ])

    namespace = load_functions(
        WORKFLOW_RUNNER_PATH,
        {
            '_coerce_token_count',
            '_extract_token_usage',
            '_create_token_usage_aggregate',
            '_accumulate_token_usage',
            '_finalize_token_usage',
            '_execute_document_comparison_workflow',
        },
        extra_globals={
            'DOCUMENT_ACTION_TYPE_COMPARISON': 'comparison',
            '_chain_activity_callbacks': lambda *callbacks: None,
            '_build_document_action_activity_callback': lambda *args, **kwargs: None,
            '_maybe_execute_tabular_document_action': lambda *args, **kwargs: None,
            '_maybe_create_comparison_generated_artifacts': lambda *args, **kwargs: {'artifacts': [], 'assistant_reply': None},
            '_resolve_model_workflow_client': lambda *args, **kwargs: (fake_client, 'gpt-5.4', 'aoai'),
            'run_document_comparison': lambda **kwargs: (
                kwargs['invoke_prompt']('summary left', stage='summary'),
                kwargs['invoke_prompt']('summary right', stage='summary'),
                kwargs['invoke_prompt']('compare', stage='comparison'),
                {
                    'reply': 'Aggregated comparison answer',
                    'coverage': {
                        'processed_windows': 3,
                        'failed_windows': 0,
                    },
                }
            )[-1],
            '_resolve_document_action_reply': lambda result: result.get('reply', ''),
            '_extract_message_text': lambda content: content,
            'debug_print': lambda *args, **kwargs: None,
        },
    )

    result = namespace['_execute_document_comparison_workflow'](
        {
            'id': 'workflow-compare-1',
            'user_id': 'user-1',
            'runner_type': 'model',
            'task_prompt': 'Compare the selected documents',
        },
        settings={},
        conversation_id='conversation-1',
        run_id='run-compare-1',
        action_config={
            'type': 'comparison',
            'left_document_id': 'doc-left',
            'right_document_ids': ['doc-right'],
        },
    )

    assert_equal(
        result.get('token_usage'),
        {
            'prompt_tokens': 220,
            'completion_tokens': 40,
            'total_tokens': 260,
            'request_count': 3,
        },
        'document comparison token aggregation',
    )
    print('Document comparison token aggregation passed.')
    return True


def test_workflow_assistant_persists_token_usage():
    print('Testing workflow assistant token usage persistence...')

    logged_usage = []
    message_container = FakeContainer()
    conversation_container = FakeContainer()

    namespace = load_functions(
        WORKFLOW_RUNNER_PATH,
        {'_create_assistant_message'},
        extra_globals={
            '_utc_now_iso': lambda: '2025-01-01T00:00:00+00:00',
            '_get_document_action_config': lambda workflow: workflow.get('document_action', {}),
            '_persist_agent_citation_artifacts': lambda **kwargs: [],
            'cosmos_messages_container': message_container,
            'cosmos_conversations_container': conversation_container,
            'log_token_usage': lambda **kwargs: logged_usage.append(kwargs),
            'debug_print': lambda *args, **kwargs: None,
            'uuid': uuid,
        },
    )

    assistant_doc = namespace['_create_assistant_message'](
        conversation={'id': 'conversation-1', 'title': 'Workflow conversation'},
        workflow={
            'id': 'workflow-1',
            'user_id': 'user-1',
            'name': 'Document workflow',
            'runner_type': 'model',
            'selected_agent': {},
            'model_binding_summary': {},
            'analyze': {},
            'document_action': {'type': 'analyze'},
        },
        result={
            'reply': 'Done',
            'model_deployment_name': 'gpt-5.4',
            'token_usage': {
                'prompt_tokens': 200,
                'completion_tokens': 40,
                'total_tokens': 240,
                'request_count': 2,
            },
            'analysis_coverage': {'processed_windows': 2},
            'agent_citations': [],
        },
        trigger_source='manual',
        run_id='run-1',
        user_message_doc={
            'metadata': {
                'thread_info': {
                    'thread_id': 'thread-1',
                },
            },
        },
        assistant_message_id='assistant-1',
    )

    assert_equal(assistant_doc['metadata']['token_usage']['total_tokens'], 240, 'workflow assistant token total')
    assert_equal(len(message_container.items), 1, 'workflow assistant message upsert count')
    assert_equal(len(logged_usage), 1, 'workflow token usage log count')
    assert_equal(logged_usage[0]['total_tokens'], 240, 'workflow logged token total')
    print('Workflow assistant token usage persistence passed.')
    return True


def test_chat_document_action_persists_token_usage():
    print('Testing chat document action token usage persistence markers...')

    with open(CHAT_ROUTE_PATH, 'r', encoding='utf-8') as handle:
        content = handle.read()

    assert_in("'token_usage': execution_result.get('token_usage')", content, 'chat assistant token usage persistence')
    assert_in("'document_action_type': normalized_action.get('type')", content, 'chat token usage log context')
    assert_in('log_token_usage(', content, 'chat token usage activity logging')
    print('Chat document action token usage persistence markers passed.')
    return True


def test_version_update():
    print('Testing version update...')

    with open(CONFIG_PATH, 'r', encoding='utf-8') as handle:
        content = handle.read()

    assert_in('VERSION = "0.241.023"', content, 'config version update')
    print('Version update passed.')
    return True


def run_tests():
    print('Running document action token usage aggregation tests...')
    print('=' * 72)

    tests = [
        test_document_analysis_token_aggregation,
        test_document_comparison_token_aggregation,
        test_workflow_assistant_persists_token_usage,
        test_chat_document_action_persists_token_usage,
        test_version_update,
    ]

    results = []
    for test in tests:
        print(f'\n{test.__name__}:')
        try:
            results.append(test())
        except Exception as exc:
            print(f'FAILED: {exc}')
            results.append(False)

    passed = sum(bool(result) for result in results)
    print(f'\nResults: {passed}/{len(results)} tests passed')
    return passed == len(results)


if __name__ == '__main__':
    raise SystemExit(0 if run_tests() else 1)