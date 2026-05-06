#!/usr/bin/env python3
# test_workspace_tabular_trigger_and_thoughts.py
"""
Functional test for workspace-selected tabular trigger and live tabular progress thoughts.
Version: 0.241.136
Implemented in: 0.241.136

This test ensures that explicitly selected workspace tabular files still trigger
SK mini-agent analysis even when retrieval context is sparse, and that
processing thoughts show individual tabular tool calls and live progress
activity instead of only generic wrapper messages, and that long-running
analysis retries keep a visible lifecycle heartbeat instead of falsely
appearing complete.
"""

import ast
import os
import sys
from types import SimpleNamespace

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(ROOT_DIR, 'application', 'single_app'))
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')


def read_route_backend_chats():
    """Read the chat route implementation for structural verification."""
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def load_tabular_thought_helpers():
    """Load selected tabular thought helpers from the route source."""
    parsed = ast.parse(read_route_backend_chats(), filename=ROUTE_FILE)
    selected_nodes = []

    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in {
            'get_tabular_thought_excluded_parameter_names',
            'get_tabular_invocation_result_payload',
            'get_tabular_invocation_error_message',
            'format_tabular_thought_parameter_value',
            'get_tabular_tool_thought_payloads',
        }:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {'json': __import__('json')}
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace


def load_tabular_live_callback_helpers():
    """Load the tabular live callback helpers needed for progress tests."""
    parsed = ast.parse(read_route_backend_chats(), filename=ROUTE_FILE)
    selected_nodes = []

    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in {
            'get_tabular_thought_excluded_parameter_names',
            'get_tabular_invocation_result_payload',
            'get_tabular_invocation_error_message',
            'format_tabular_thought_parameter_value',
            'get_tabular_tool_thought_payloads',
            'build_tabular_activity_payload',
            'format_live_tabular_invocation_start_thought',
            'format_live_tabular_invocation_thought',
            'register_tabular_invocation_thought_callback',
        }:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {'json': __import__('json')}
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace


def test_workspace_selected_tabular_trigger():
    """Verify explicitly selected workspace tabular files participate in trigger detection."""
    print("🔍 Testing workspace-selected tabular trigger detection...")

    try:
        content = read_route_backend_chats()

        checks = {
            'selected workspace helper exists': 'def collect_workspace_tabular_file_contexts(' in content,
            'combined workspace helper exists': 'def collect_workspace_tabular_filenames(' in content,
            'workspace trigger uses selected ids': 'selected_document_ids=selected_document_ids' in content,
            'workspace trigger uses selected id': 'selected_document_id=selected_document_id' in content,
            'workspace-specific fallback prompt': 'IMPORTANT: The selected workspace tabular file(s) are' in content,
            'workspace trigger gated by document search': 'if (hybrid_search_enabled or history_grounded_search_used) and workspace_tabular_files and is_tabular_processing_enabled(settings):' in content,
        }

        failed_checks = [name for name, passed in checks.items() if not passed]
        assert not failed_checks, f"Missing expected workspace trigger elements: {failed_checks}"

        print("✅ Workspace-selected tabular trigger checks passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_tabular_analysis_thoughts_are_recorded():
    """Verify processing thoughts now expose individual tabular tool calls."""
    print("🔍 Testing tabular analysis thoughts instrumentation...")

    try:
        content = read_route_backend_chats()

        checks = {
            'tool thought payload helper exists': 'def get_tabular_tool_thought_payloads(' in content,
            'non-streaming tool thought loop': 'for thought_content, thought_detail in tabular_thought_payloads:' in content,
            'streaming tool thought loop': "yield emit_thought('tabular_analysis', thought_content, thought_detail)" in content,
            'generic workspace wrapper thought removed': 'Running tabular analysis on {len(workspace_tabular_files)} workspace file(s)' not in content,
            'generic completion wrapper thought removed': 'Tabular analysis completed using {len(tabular_sk_citations)} tool call(s)' not in content,
            'failure thought remains': 'Tabular analysis could not compute results; using schema context instead' in content,
        }

        failed_checks = [name for name, passed in checks.items() if not passed]
        assert not failed_checks, f"Missing expected tabular thought instrumentation: {failed_checks}"

        print("✅ Tabular analysis thoughts checks passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_tabular_tool_thought_payload_formatting():
    """Verify individual tabular tool calls produce readable thought payloads."""
    print("🔍 Testing tabular tool thought payload formatting...")

    try:
        helpers = load_tabular_thought_helpers()
        payload_builder = helpers['get_tabular_tool_thought_payloads']

        invocations = [
            SimpleNamespace(
                function_name='group_by_datetime_component',
                duration_ms=42.8,
                success=True,
                parameters={
                    'user_id': 'test-user',
                    'conversation_id': 'test-conversation',
                    'filename': 'faa.csv',
                    'datetime_component': 'hour',
                    'operation': 'mean',
                },
                error_message=None,
            )
        ]

        thought_payloads = payload_builder(invocations)
        assert len(thought_payloads) == 1, f"Expected one thought payload, got {len(thought_payloads)}"

        thought_content, thought_detail = thought_payloads[0]
        assert thought_content == 'Tabular tool group_by_datetime_component on faa.csv (42ms)', thought_content
        assert 'datetime_component=hour' in thought_detail, thought_detail
        assert 'operation=mean' in thought_detail, thought_detail
        assert 'user_id=' not in thought_detail, thought_detail
        assert 'conversation_id=' not in thought_detail, thought_detail

        print("✅ Tabular tool thought payload formatting passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_tabular_live_callbacks_follow_logger_dispatch_key():
    """Verify live tabular callbacks register on the shared logger dispatch key."""
    print("🔍 Testing tabular live callback dispatch contract...")

    try:
        helpers = load_tabular_live_callback_helpers()
        register_callback = helpers['register_tabular_invocation_thought_callback']

        class FakePluginLogger:
            def __init__(self):
                self.start_callbacks = {}
                self.callbacks = {}

            def register_start_callback(self, key, callback):
                self.start_callbacks.setdefault(key, []).append(callback)

            def register_callback(self, key, callback):
                self.callbacks.setdefault(key, []).append(callback)

            def emit_start(self, invocation_start):
                key = f"{invocation_start.user_id}:{invocation_start.conversation_id}"
                for callback in self.start_callbacks.get(key, []):
                    callback(invocation_start)

            def emit_completion(self, invocation):
                key = f"{invocation.user_id}:{invocation.conversation_id}"
                for callback in self.callbacks.get(key, []):
                    callback(invocation)

        class FakeThoughtTracker:
            def __init__(self):
                self.message_id = 'assistant-message-1'
                self.current_index = 0
                self.thoughts = []

            def add_thought(self, step_type, content, detail=None, activity=None):
                self.thoughts.append({
                    'step_type': step_type,
                    'content': content,
                    'detail': detail,
                    'activity': activity,
                })
                self.current_index += 1

        plugin_logger = FakePluginLogger()
        thought_tracker = FakeThoughtTracker()
        live_payloads = []

        callback_key = register_callback(
            plugin_logger,
            thought_tracker,
            user_id='user-123',
            conversation_id='conversation-456',
            live_thought_callback=live_payloads.append,
        )

        assert callback_key == 'user-123:conversation-456', callback_key

        invocation_start = SimpleNamespace(
            user_id='user-123',
            conversation_id='conversation-456',
            plugin_name='TabularProcessingPlugin',
            function_name='query_tabular_data',
            parameters={
                'filename': 'faa.csv',
                'sheet_name': 'Sheet1',
                'operation': 'sum',
            },
        )
        invocation = SimpleNamespace(
            user_id='user-123',
            conversation_id='conversation-456',
            plugin_name='TabularProcessingPlugin',
            function_name='query_tabular_data',
            duration_ms=121.7,
            success=True,
            parameters={
                'filename': 'faa.csv',
                'sheet_name': 'Sheet1',
                'operation': 'sum',
            },
            error_message=None,
        )

        plugin_logger.emit_start(invocation_start)
        plugin_logger.emit_completion(invocation)

        assert len(thought_tracker.thoughts) == 2, thought_tracker.thoughts
        assert len(live_payloads) == 2, live_payloads
        assert thought_tracker.thoughts[0]['activity']['status'] == 'running', thought_tracker.thoughts
        assert thought_tracker.thoughts[1]['activity']['status'] == 'completed', thought_tracker.thoughts
        assert live_payloads[0]['step_index'] == 0, live_payloads
        assert live_payloads[1]['step_index'] == 1, live_payloads
        assert live_payloads[0]['content'] == 'Starting tabular tool query_tabular_data on faa.csv [Sheet1]', live_payloads
        assert live_payloads[1]['content'] == 'Tabular tool query_tabular_data on faa.csv [Sheet1] (121ms)', live_payloads

        print("✅ Tabular live callback dispatch checks passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_tabular_generated_output_progress_hooks_exist():
    """Verify the generated-output path now exposes progress hooks for post-processing."""
    print("🔍 Testing tabular generated-output progress instrumentation...")

    try:
        content = read_route_backend_chats()

        checks = {
            'post-processing activity helper exists': 'def build_tabular_post_processing_activity_payload(' in content,
            'post-processing emitter exists': 'async def emit_tabular_post_processing_thought(' in content,
            'structured output accepts callback': 'async def _generate_tabular_structured_output_entries(' in content and 'thought_callback=None' in content,
            'generated output accepts callback': 'async def maybe_create_tabular_generated_output(' in content and 'thought_callback=None' in content,
            'non-streaming generated output callback wired': 'thought_callback=record_tabular_post_processing_thought' in content,
            'streaming generated output callback wired': 'thought_callback=record_and_publish_streaming_thought' in content,
            'structured batch progress thought': 'Building structured ' in content and 'export batch {batch_number} of {total_batches}' in content,
            'upload progress thought': 'Uploading generated {output_format_label} export to this chat' in content,
        }

        failed_checks = [name for name, passed in checks.items() if not passed]
        assert not failed_checks, f"Missing expected generated-output progress instrumentation: {failed_checks}"

        print("✅ Tabular generated-output progress instrumentation checks passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_tabular_analysis_lifecycle_progress_hooks_exist():
    """Verify long-running tabular analysis emits lifecycle heartbeats between tool phases."""
    print("🔍 Testing tabular analysis lifecycle heartbeat instrumentation...")

    try:
        content = read_route_backend_chats()

        checks = {
            'analysis lifecycle activity helper exists': 'def build_tabular_analysis_lifecycle_activity_payload(' in content,
            'analysis lifecycle emitter exists': 'async def emit_tabular_analysis_lifecycle_thought(' in content,
            'multi-file tabular analysis accepts callback': 'async def run_tabular_analysis_with_multi_file_support(' in content and 'thought_callback=None' in content,
            'sk tabular analysis accepts callback': 'async def run_tabular_sk_analysis(' in content and 'thought_callback=None' in content,
            'wrapper wires lifecycle callback': 'thought_callback=tabular_progress_callback' in content,
            'retry heartbeat exists': 'Retrying workbook analysis (attempt {attempt_number} of 3)' in content,
            'handoff heartbeat exists': 'Tabular analysis complete; preparing final response' in content,
        }

        failed_checks = [name for name, passed in checks.items() if not passed]
        assert not failed_checks, f"Missing expected tabular lifecycle heartbeat instrumentation: {failed_checks}"

        print("✅ Tabular lifecycle heartbeat instrumentation checks passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_tabular_sk_prompt_requires_tool_use():
    """Verify the mini-agent retries when it answers without using tabular tools."""
    print("🔍 Testing mandatory tabular tool-use prompt hardening...")

    try:
        content = read_route_backend_chats()

        checks = {
            'mandatory tool-use prompt': (
                'You MUST use one or more ' in content
                and 'tabular_processing plugin functions before answering.' in content
            ),
            'retry mode prompt': 'RETRY MODE: Your previous attempt did not execute a usable analytical tool call.' in content,
            'retry logging': 'returned narrative without tool use; retrying' in content,
            'required retry mode': 'FunctionChoiceBehavior.Required(' in content,
            'three-pass retry loop': 'for attempt_number in range(1, 4):' in content,
        }

        failed_checks = [name for name, passed in checks.items() if not passed]
        assert not failed_checks, f"Missing expected tabular SK prompt hardening: {failed_checks}"

        print("✅ Tabular SK prompt hardening checks passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_workspace_selected_tabular_trigger,
        test_tabular_analysis_thoughts_are_recorded,
        test_tabular_tool_thought_payload_formatting,
        test_tabular_live_callbacks_follow_logger_dispatch_key,
        test_tabular_generated_output_progress_hooks_exist,
        test_tabular_analysis_lifecycle_progress_hooks_exist,
        test_tabular_sk_prompt_requires_tool_use,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
