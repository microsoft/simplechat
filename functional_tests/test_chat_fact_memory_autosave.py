#!/usr/bin/env python3
# test_chat_fact_memory_autosave.py
"""
Functional test for agent-free fact memory writes in standard chat.
Version: 0.261.001
Implemented in: 0.261.001

Memory recall already worked without agents, but creating, updating, and deleting memories
required the Semantic Kernel agent path. This test covers the replacement: an intent
pre-filter that keeps ordinary turns free of an extra model call, and a mini-SK pass that
carries only the fact-memory plugin.

The module under test imports Cosmos-backed configuration at import time, so the functions
are loaded from source with stubbed dependencies rather than imported directly. Refs #1352.
"""

import ast
import asyncio
import logging
import os
import re
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, 'application', 'single_app')
AUTOSAVE_MODULE = os.path.join(APP_DIR, 'functions_fact_memory_autosave.py')
CHAT_ROUTE = os.path.join(APP_DIR, 'route_backend_chats.py')


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


class FakeInvocation:
    """Stand-in for PluginInvocation entries recorded by the plugin logger."""

    def __init__(self, function_name, parameters=None, success=True, error_message=None):
        self.function_name = function_name
        self.parameters = parameters or {}
        self.success = success
        self.error_message = error_message


class FakePluginLogger:
    def __init__(self, invocations=None):
        self.invocations = list(invocations or [])

    def get_invocations_for_conversation(self, user_id, conversation_id, limit=None):
        return list(self.invocations)


class FakeKernel:
    def __init__(self):
        self.plugins = {}
        self.services = []

    def add_plugin(self, plugin, plugin_name=None):
        self.plugins[plugin_name] = plugin

    def add_service(self, service):
        self.services.append(service)


class FakeChatHistory:
    def __init__(self):
        self.messages = []

    def add_system_message(self, content):
        self.messages.append(('system', content))

    def add_user_message(self, content):
        self.messages.append(('user', content))


class FakeFunctionChoiceBehavior:
    @staticmethod
    def Auto(**kwargs):  # noqa: N802 - mirrors the Semantic Kernel API surface
        return {'behavior': 'auto', **kwargs}


class FakeExecutionSettings:
    def __init__(self, service_id=None, function_choice_behavior=None):
        self.service_id = service_id
        self.function_choice_behavior = function_choice_behavior


def load_autosave_namespace(chat_service=None, plugin_logger=None, service_factory=None):
    """Execute the autosave module body with stubbed dependencies.

    Import statements are dropped so the Cosmos-backed configuration chain never runs;
    every name the module needs is supplied through the namespace instead.
    """
    module_source = read_file_text(AUTOSAVE_MODULE)
    parsed = ast.parse(module_source, filename=AUTOSAVE_MODULE)
    parsed.body = [
        node for node in parsed.body
        if not isinstance(node, (ast.Import, ast.ImportFrom))
    ]

    recorded = {'services': [], 'log_events': []}

    def fake_log_event(message, extra=None, level=None, exceptionTraceback=False):
        recorded['log_events'].append((message, level))

    def default_service_factory(gpt_model, settings, service_id=None, model_context=None):
        recorded['services'].append({
            'gpt_model': gpt_model,
            'service_id': service_id,
            'model_context': model_context,
        })
        return chat_service, 'azure_openai'

    namespace = {
        're': re,
        'logging': logging,
        'log_event': fake_log_event,
        'build_semantic_kernel_chat_service_for_model': service_factory or default_service_factory,
        'Kernel': FakeKernel,
        'FunctionChoiceBehavior': FakeFunctionChoiceBehavior,
        'AzureChatPromptExecutionSettings': FakeExecutionSettings,
        'ChatHistory': FakeChatHistory,
        'FactMemoryPlugin': lambda: 'fact-memory-plugin-instance',
        'get_plugin_logger': lambda: plugin_logger or FakePluginLogger(),
    }

    exec(compile(parsed, AUTOSAVE_MODULE, 'exec'), namespace)
    namespace['_recorded'] = recorded
    return namespace


def test_intent_filter_detects_memory_requests():
    """Explicit save, change, and forget requests must trigger the pass."""
    print("🔍 Testing memory-intent detection (positives)...")

    try:
        namespace = load_autosave_namespace()
        user_requested_memory_update = namespace['user_requested_memory_update']

        positives = [
            'Remember that I prefer bullet points',
            'Please remember my team is called Platform Engineering',
            "Don't forget I work in the Central time zone",
            'From now on, answer in British English',
            'Going forward, keep responses under 200 words',
            'Stop calling me Paul, my name is Paul Lizer',
            'You should always include a summary at the top',
            'Please never mention pricing in your answers',
            'Forget that I said I was on the finance team',
            'Delete my memory about the Contoso project',
            'Call me PL',
            'I prefer tables over prose',
            "I don't like long introductions",
            'Make a note that our fiscal year starts in July',
            'I no longer work on the billing service',
            'I want you to always start with the conclusion',
        ]

        failures = [message for message in positives if not user_requested_memory_update(message)]
        assert not failures, f'Expected memory intent for: {failures}'

        print("✅ Memory-intent positives passed!")
        return True
    except Exception as e:
        print(f"❌ Memory-intent positives failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_intent_filter_skips_ordinary_turns():
    """Ordinary questions and recall questions must not pay for an extra model call."""
    print("🔍 Testing memory-intent detection (negatives)...")

    try:
        namespace = load_autosave_namespace()
        user_requested_memory_update = namespace['user_requested_memory_update']

        negatives = [
            '',
            None,
            '   ',
            'Summarize the attached quarterly report',
            'What is the capital of France?',
            'Do you remember what we discussed yesterday?',
            'What do you remember about me?',
            'Can you recall the figures from the last document?',
            'How many rows are in this spreadsheet?',
            'Write a Python function that parses CSV files',
            'Explain how the retention policy works',
        ]

        failures = [message for message in negatives if user_requested_memory_update(message)]
        assert not failures, f'Did not expect memory intent for: {failures}'

        print("✅ Memory-intent negatives passed!")
        return True
    except Exception as e:
        print(f"❌ Memory-intent negatives failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_pass_gating_respects_admin_toggle_and_agents():
    """The pass runs only when enabled, agent-free, and the user asked for a change."""
    print("🔍 Testing autosave gating...")

    try:
        namespace = load_autosave_namespace()
        should_run = namespace['should_run_fact_memory_autosave']

        assert should_run('Remember that I prefer bullets', True, None) is True, \
            'Expected the pass to run for an enabled, agent-free memory request'
        assert should_run('Remember that I prefer bullets', False, None) is False, \
            'The admin toggle must gate the pass'
        assert should_run('Remember that I prefer bullets', True, object()) is False, \
            'An agent run already had the tool inline; the pass must not run again'
        assert should_run('Summarize this document', True, None) is False, \
            'Ordinary turns must not trigger the pass'

        print("✅ Autosave gating passed!")
        return True
    except Exception as e:
        print(f"❌ Autosave gating failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_pass_registers_only_the_fact_memory_plugin():
    """The mini kernel must expose fact memory and nothing else."""
    print("🔍 Testing mini-SK kernel composition...")

    try:
        captured = {}

        class RecordingChatService:
            async def get_chat_message_contents(self, chat_history, execution_settings, kernel=None):
                captured['chat_history'] = chat_history
                captured['execution_settings'] = execution_settings
                captured['kernel'] = kernel
                return []

        namespace = load_autosave_namespace(
            chat_service=RecordingChatService(),
            plugin_logger=FakePluginLogger(),
        )
        run_fact_memory_autosave = namespace['run_fact_memory_autosave']

        payload = asyncio.run(run_fact_memory_autosave(
            user_message='Remember that I prefer bullet points',
            assistant_message='Understood.',
            settings={'enable_fact_memory_plugin': True},
            gpt_model='gpt-4o',
            scope_id='user-123',
            scope_type='user',
            conversation_id='conversation-456',
            user_id='user-123',
            model_context={'provider': 'aoai'},
        ))

        assert payload['error'] is None, f"Unexpected error: {payload['error']}"

        kernel = captured['kernel']
        assert list(kernel.plugins.keys()) == ['fact_memory'], \
            f'Expected only the fact_memory plugin, found {list(kernel.plugins.keys())}'
        assert len(kernel.services) == 1, 'Expected exactly one chat service on the mini kernel'

        behavior = captured['execution_settings'].function_choice_behavior
        assert behavior['filters'] == {'included_plugins': ['fact_memory']}, \
            f'Tool calling must be filtered to fact_memory, found {behavior.get("filters")}'
        assert behavior['maximum_auto_invoke_attempts'] >= 2, \
            'The pass needs enough attempts to look up a fact id before changing it'

        history_text = ' '.join(content for _role, content in captured['chat_history'].messages)
        assert 'NO_MEMORY_CHANGE' in history_text, \
            'The prompt must give the model an explicit no-op answer'
        assert "scope_type='user'" in history_text and "scope_id='user-123'" in history_text, \
            'The prompt must supply the authorized scope arguments for tool calls'
        assert 'Remember that I prefer bullet points' in history_text, \
            'The evaluated exchange must include the user message'

        service_call = namespace['_recorded']['services'][0]
        assert service_call['service_id'] == 'fact-memory-autosave', \
            'The pass should use its own service id so it never collides with chat'
        assert service_call['model_context'] == {'provider': 'aoai'}, \
            'The pass must reuse the resolved chat model endpoint context'

        print("✅ Mini-SK kernel composition passed!")
        return True
    except Exception as e:
        print(f"❌ Mini-SK kernel composition failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_pass_reports_memory_changes_as_thoughts():
    """Writes performed during the pass surface as chat thoughts."""
    print("🔍 Testing memory change reporting...")

    try:
        plugin_logger = FakePluginLogger()

        class WritingChatService:
            async def get_chat_message_contents(self, chat_history, execution_settings, kernel=None):
                plugin_logger.invocations.extend([
                    FakeInvocation('get_facts', {'scope_type': 'user', 'scope_id': 'user-123'}),
                    FakeInvocation('set_fact', {
                        'value': 'Prefers bullet points in responses',
                        'memory_type': 'instruction',
                    }),
                    FakeInvocation('delete_fact', {'fact_id': 'fact-9'}),
                ])
                return []

        namespace = load_autosave_namespace(
            chat_service=WritingChatService(),
            plugin_logger=plugin_logger,
        )

        payload = asyncio.run(namespace['run_fact_memory_autosave'](
            user_message='Remember that I prefer bullet points and forget the Contoso note',
            assistant_message='Done.',
            settings={},
            gpt_model='gpt-4o',
            scope_id='user-123',
            scope_type='user',
            conversation_id='conversation-456',
            user_id='user-123',
        ))

        assert payload['error'] is None, f"Unexpected error: {payload['error']}"
        assert len(payload['changes']) == 2, \
            f"Only write calls should be reported, found {payload['changes']}"

        contents = [thought['content'] for thought in payload['thoughts']]
        assert contents == ['Saved a new instruction memory', 'Removed a saved memory'], \
            f'Unexpected thought contents: {contents}'
        assert all(thought['step_type'] == 'fact_memory' for thought in payload['thoughts']), \
            'Memory thoughts must use the fact_memory step type'
        assert payload['thoughts'][0]['detail'] == 'Prefers bullet points in responses', \
            'The saved value should be shown as thought detail'

        print("✅ Memory change reporting passed!")
        return True
    except Exception as e:
        print(f"❌ Memory change reporting failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_pass_degrades_without_breaking_chat():
    """A memory failure must never propagate into the chat response."""
    print("🔍 Testing graceful degradation...")

    try:
        def exploding_service_factory(gpt_model, settings, service_id=None, model_context=None):
            raise RuntimeError('model endpoint unavailable')

        namespace = load_autosave_namespace(service_factory=exploding_service_factory)

        payload = asyncio.run(namespace['run_fact_memory_autosave'](
            user_message='Remember that I prefer bullet points',
            assistant_message='Understood.',
            settings={},
            gpt_model='gpt-4o',
            scope_id='user-123',
            scope_type='user',
            conversation_id='conversation-456',
            user_id='user-123',
        ))

        assert payload['error'] == 'model endpoint unavailable', \
            f"Expected the failure to be captured, found {payload['error']}"
        assert payload['changes'] == [] and payload['thoughts'] == [], \
            'A failed pass must report no changes'

        logged = ' '.join(message for message, _level in namespace['_recorded']['log_events'])
        assert 'FACT_MEMORY_AUTOSAVE' in logged, 'The failure should be logged for operators'

        print("✅ Graceful degradation passed!")
        return True
    except Exception as e:
        print(f"❌ Graceful degradation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_chat_routes_wire_the_pass_into_both_paths():
    """Standard and streaming chat must both run the pass consistently."""
    print("🔍 Testing chat route wiring...")

    try:
        route_source = read_file_text(CHAT_ROUTE)

        assert 'from functions_fact_memory_autosave import (' in route_source, \
            'route_backend_chats.py must import the autosave helpers'
        assert route_source.count('should_run_fact_memory_autosave(user_message, fact_memory_enabled, selected_agent)') == 2, \
            'Both the standard and streaming paths must gate the pass identically'
        assert route_source.count('asyncio.run(run_fact_memory_autosave(') == 2, \
            'Both chat paths must run the memory pass'
        assert 'assistant_message=ai_message' in route_source, \
            'The standard path must pass the finalized assistant message'
        assert 'assistant_message=accumulated_content' in route_source, \
            'The streaming path must pass the accumulated assistant message'
        assert "thought_tracker.add_thought(\n                        thought.get('step_type') or 'fact_memory'" in route_source, \
            'The standard path must record memory thoughts'
        assert "yield emit_thought(\n                                thought.get('step_type') or 'fact_memory'" in route_source, \
            'The streaming path must emit memory thoughts'

        assert_app_version_at_least('0.261.001')

        print("✅ Chat route wiring passed!")
        return True
    except Exception as e:
        print(f"❌ Chat route wiring failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_intent_filter_detects_memory_requests,
        test_intent_filter_skips_ordinary_turns,
        test_pass_gating_respects_admin_toggle_and_agents,
        test_pass_registers_only_the_fact_memory_plugin,
        test_pass_reports_memory_changes_as_thoughts,
        test_pass_degrades_without_breaking_chat,
        test_chat_routes_wire_the_pass_into_both_paths,
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
