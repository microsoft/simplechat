#!/usr/bin/env python3
# test_workspace_tabular_trigger_and_thoughts.py
"""
Functional test for workspace-selected tabular trigger and per-tool thoughts fix.
Version: 0.239.035
Implemented in: 0.239.035

This test ensures that explicitly selected workspace tabular files still trigger
SK mini-agent analysis even when retrieval context is sparse, and that
processing thoughts show individual tabular tool calls instead of only generic
wrapper messages.
"""

import ast
import os
import sys
from types import SimpleNamespace

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
        if isinstance(node, ast.Assign):
            target_names = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if 'TABULAR_THOUGHT_EXCLUDED_PARAMETER_NAMES' in target_names:
                selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {
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


def test_workspace_selected_tabular_trigger():
    """Verify explicitly selected workspace tabular files participate in trigger detection."""
    print("🔍 Testing workspace-selected tabular trigger detection...")

    try:
        content = read_route_backend_chats()

        checks = {
            'selected workspace helper exists': 'def get_selected_workspace_tabular_filenames(' in content,
            'combined workspace helper exists': 'def collect_workspace_tabular_filenames(' in content,
            'workspace trigger uses selected ids': 'selected_document_ids=selected_document_ids' in content,
            'workspace trigger uses selected id': 'selected_document_id=selected_document_id' in content,
            'workspace-specific fallback prompt': 'IMPORTANT: The selected workspace tabular file(s) are' in content,
            'workspace trigger gated by document search': 'if hybrid_search_enabled and workspace_tabular_files' in content,
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
            'retry mode prompt': 'RETRY MODE: Your previous attempt did not execute the data-analysis tools.' in content,
            'retry logging': 'returned narrative without tool use; retrying' in content,
            'strict retry attempts': 'maximum_auto_invoke_attempts=10 if force_tool_use else 7' in content,
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
        test_tabular_sk_prompt_requires_tool_use,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
