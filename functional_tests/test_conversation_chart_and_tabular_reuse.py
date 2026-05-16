#!/usr/bin/env python3
# test_conversation_chart_and_tabular_reuse.py
"""
Functional test for conversation chart abilities and reusable tabular analysis.
Version: 0.241.031
Implemented in: 0.241.031

This test ensures the built-in chart plugin is loaded as a conversation-level
Semantic Kernel ability and workflow tabular analysis imports a reusable helper
surface instead of depending directly on the chat route.
"""

import ast
import os
import re
import sys
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
CONFIG_FILE = APP_ROOT / "config.py"
CHART_OPERATIONS_FILE = APP_ROOT / "functions_chart_operations.py"
TABULAR_ANALYSIS_FILE = APP_ROOT / "functions_tabular_analysis.py"
SEMANTIC_KERNEL_LOADER_FILE = APP_ROOT / "semantic_kernel_loader.py"
CHAT_ROUTE_FILE = APP_ROOT / "route_backend_chats.py"
WORKFLOW_RUNNER_FILE = APP_ROOT / "functions_workflow_runner.py"
EXPECTED_VERSION = "0.241.031"

TARGET_CHART_HELPERS = {
    "user_requested_chart_visualization",
    "build_chart_tool_usage_system_message",
    "insert_system_message_after_existing_system_messages",
    "maybe_append_chart_tool_system_message",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_current_version() -> str:
    for line in read_text(CONFIG_FILE).splitlines():
        stripped_line = line.strip()
        if stripped_line.startswith('VERSION = '):
            return stripped_line.split('"')[1]
    raise AssertionError("Expected config.py to define VERSION")


def load_chart_helpers():
    route_content = read_text(CHAT_ROUTE_FILE)
    parsed = ast.parse(route_content, filename=str(CHAT_ROUTE_FILE))
    selected_nodes = [
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_CHART_HELPERS
    ]
    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {"re": re}
    exec(compile(module, str(CHAT_ROUTE_FILE), "exec"), namespace)
    return namespace


def test_version_bumped_for_feature() -> None:
    print("Testing version bump...")
    assert read_current_version() == EXPECTED_VERSION
    print("PASS: version bump")


def test_chart_plugin_is_core_conversation_ability() -> None:
    print("Testing core chart plugin loader wiring...")

    chart_operations_content = read_text(CHART_OPERATIONS_FILE)
    loader_content = read_text(SEMANTIC_KERNEL_LOADER_FILE)

    assert "CORE_CHART_PLUGIN_NAME = 'conversation_charts'" in chart_operations_content, (
        "Expected a dedicated core chart plugin name that does not collide with assigned chart actions."
    )
    assert "from semantic_kernel_plugins.chart_plugin import ChartPlugin" in loader_content, (
        "Expected semantic_kernel_loader.py to import ChartPlugin."
    )
    assert "def load_chart_plugin(kernel: Kernel):" in loader_content, (
        "Expected semantic_kernel_loader.py to expose a reusable chart plugin loader."
    )
    assert "ChartPlugin()" in loader_content, (
        "Expected load_chart_plugin() to register the built-in ChartPlugin."
    )
    assert loader_content.count("load_chart_plugin(kernel)") >= 3, (
        "Expected model-only, global, and per-user kernel paths to load conversation charts."
    )
    assert "Conversation Charts plugin" in loader_content, (
        "Expected loader logs to identify the conversation chart ability."
    )

    print("PASS: core chart plugin loader wiring")


def test_chart_handoff_applies_without_selected_agent() -> None:
    print("Testing chart handoff without selected agent...")

    helpers = load_chart_helpers()
    maybe_append = helpers["maybe_append_chart_tool_system_message"]
    build_message = helpers["build_chart_tool_usage_system_message"]

    history = [
        {"role": "system", "content": "Existing system guidance"},
        {"role": "user", "content": "Make a bar chart of revenue by month."},
    ]
    updated_history = maybe_append(history, history[-1]["content"], None)

    assert len(updated_history) == 3, updated_history
    assert updated_history[1]["role"] == "system", updated_history
    assert updated_history[1]["content"] == build_message(), updated_history

    print("PASS: chart handoff without selected agent")


def test_kernel_fallback_allows_core_tool_invocation() -> None:
    print("Testing kernel fallback function choice behavior...")

    route_content = read_text(CHAT_ROUTE_FILE)

    assert "from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior" in route_content, (
        "Expected route_backend_chats.py to import FunctionChoiceBehavior for kernel fallback tools."
    )
    assert "settings_obj.function_choice_behavior = FunctionChoiceBehavior.Auto(maximum_auto_invoke_attempts=20)" in route_content, (
        "Expected model-only kernel fallback to allow auto tool invocation for core conversation abilities."
    )

    print("PASS: kernel fallback function choice behavior")


def test_workflows_use_tabular_analysis_import_surface() -> None:
    print("Testing workflow tabular import surface...")

    workflow_content = read_text(WORKFLOW_RUNNER_FILE)
    tabular_analysis_content = read_text(TABULAR_ANALYSIS_FILE)

    assert "# functions_tabular_analysis.py" in tabular_analysis_content, (
        "Expected the reusable tabular analysis module to follow Python file-header convention."
    )
    assert "from functions_tabular_analysis import (" in workflow_content, (
        "Expected workflow tabular helper to import from the reusable tabular analysis module."
    )
    assert "from functions_tabular_analysis import build_tabular_computed_results_system_message" in workflow_content, (
        "Expected workflow synthesis prompts to use the reusable tabular analysis module."
    )
    assert "from route_backend_chats import (\n        augment_tabular_invocations_with_related_document_evidence" not in workflow_content, (
        "Workflow tabular execution should not import the chat route directly for reusable helpers."
    )
    assert "from route_backend_chats import build_tabular_computed_results_system_message" not in workflow_content, (
        "Workflow tabular prompt building should not import the chat route directly."
    )
    for helper_name in [
        "augment_tabular_invocations_with_related_document_evidence",
        "build_tabular_computed_results_system_message",
        "build_tabular_related_document_evidence_summary",
        "get_new_plugin_invocations",
        "maybe_create_tabular_generated_output",
        "run_tabular_analysis_with_thought_tracking",
    ]:
        assert helper_name in tabular_analysis_content, (
            f"Expected functions_tabular_analysis.py to expose {helper_name}."
        )

    print("PASS: workflow tabular import surface")


def run_tests() -> bool:
    tests = [
        test_version_bumped_for_feature,
        test_chart_plugin_is_core_conversation_ability,
        test_chart_handoff_applies_without_selected_agent,
        test_kernel_fallback_allows_core_tool_invocation,
        test_workflows_use_tabular_analysis_import_surface,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
