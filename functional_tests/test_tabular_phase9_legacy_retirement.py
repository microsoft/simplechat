#!/usr/bin/env python3
# test_tabular_phase9_legacy_retirement.py
"""
Functional test for Phase 9 tabular legacy fallback retirement controls.
Version: 0.250.166
Implemented in: 0.250.165

This test ensures the shared planner records safe legacy post-tool fallback
retirement decisions, active shared durable acceptance suppresses duplicate
legacy fallback evidence, and observe mode prevents post-tool fallback side
effects while emitting safe telemetry.
"""

import ast
import asyncio
import sys
import types
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
CHAT_ROUTE = APP_ROOT / "route_backend_chats.py"
IMPLEMENTED_VERSION = "0.250.165"
sys.path.insert(0, str(APP_ROOT))


def install_lightweight_planner_dependency_stubs():
    assistant_exports_module = types.ModuleType("functions_assistant_table_exports")
    assistant_exports_module.assistant_table_export_requested = (
        lambda prompt: "csv" in str(prompt or "").lower()
    )
    generated_exports_module = types.ModuleType("functions_generated_file_exports")

    def get_requested_structured_artifact_format(prompt):
        normalized_prompt = str(prompt or "").lower()
        for output_format in ("json", "xml", "csv"):
            if output_format in normalized_prompt:
                return output_format
        return None

    generated_exports_module.get_requested_structured_artifact_format = (
        get_requested_structured_artifact_format
    )
    sys.modules.setdefault("functions_assistant_table_exports", assistant_exports_module)
    sys.modules.setdefault("functions_generated_file_exports", generated_exports_module)


install_lightweight_planner_dependency_stubs()

from functions_tabular_orchestration import (  # noqa: E402
    build_tabular_legacy_post_tool_fallback_decision,
    orchestrate_tabular_request,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"Expected truthy value for {label}")


def assert_false(value, label):
    if value:
        raise AssertionError(f"Expected falsy value for {label}")


def build_context():
    return {
        "document_id": "table-1",
        "file_name": "survey.csv",
        "source_hint": "workspace",
        "source_version": "etag-table-1",
        "storage_locator": {
            "container": "documents",
            "blob_path": "user-1/survey.csv",
        },
    }


def test_decision_modes_and_shared_acceptance_suppression():
    """Legacy fallback decisions must be deterministic and telemetry-safe."""
    print("Testing Phase 9 legacy fallback decision modes...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    enabled_decision = build_tabular_legacy_post_tool_fallback_decision(
        settings={"tabular_legacy_post_tool_fallback_mode": "enabled"},
    )
    observe_decision = build_tabular_legacy_post_tool_fallback_decision(
        settings={"tabular_legacy_post_tool_fallback_mode": "observe"},
    )
    disabled_decision = build_tabular_legacy_post_tool_fallback_decision(
        settings={"tabular_legacy_post_tool_fallback_mode": "disabled"},
    )
    accepted_decision = build_tabular_legacy_post_tool_fallback_decision(
        settings={"tabular_legacy_post_tool_fallback_mode": "enabled"},
        planner_result={
            "planner_contract_version": "tabular-orchestration-v1",
            "execution_contract": "combined",
            "execution_state": "queued",
            "generated_output_metadata": {"export_run_id": "run-123", "status": "queued"},
        },
    )

    assert_true(enabled_decision["should_invoke"], "enabled fallback invocation")
    assert_equal(enabled_decision["action"], "invoke", "enabled action")
    assert_false(observe_decision["should_invoke"], "observe fallback invocation")
    assert_equal(observe_decision["action"], "observe", "observe action")
    assert_equal(observe_decision["reason_code"], "observe_only", "observe reason")
    assert_false(disabled_decision["should_invoke"], "disabled fallback invocation")
    assert_equal(disabled_decision["reason_code"], "mode_disabled", "disabled reason")
    assert_false(accepted_decision["should_invoke"], "accepted durable fallback invocation")
    assert_equal(accepted_decision["action"], "suppress", "accepted durable action")
    assert_equal(
        accepted_decision["reason_code"],
        "shared_durable_metadata_present",
        "accepted durable reason",
    )

    serialized_decision = str(accepted_decision)
    assert_false("survey.csv" in serialized_decision, "no file names in decision")
    assert_false("blob_path" in serialized_decision, "no blob paths in decision")


def test_active_shared_orchestrator_records_suppressed_fallback_decision():
    """Accepted shared durable work must record duplicate fallback suppression."""
    print("Testing active shared durable acceptance fallback suppression...")
    calls = []

    def fake_durable_executor(plan, **execution_context):
        calls.append({"plan": plan, "execution_context": execution_context})
        return {
            "export_run_id": "run-123",
            "status": "queued",
            "task_type": plan["durable_task_type"],
        }

    result = orchestrate_tabular_request(
        "Analyze every row and create a CSV file with one output row per source row.",
        [build_context()],
        action_mode="analyze",
        caller="analyze",
        settings={
            "enable_tabular_hierarchical_analysis": True,
            "tabular_legacy_post_tool_fallback_mode": "enabled",
        },
        planner_mode="active",
        durable_execution_callback=fake_durable_executor,
    )

    decision = result["legacy_post_tool_fallback_decision"]
    assert_equal(len(calls), 1, "durable executor calls")
    assert_equal(result["execution_state"], "queued", "execution state")
    assert_equal(decision["contract_version"], "tabular-legacy-fallback-retirement-v1", "decision contract")
    assert_equal(decision["fallback_source"], "shared_preflight", "decision source")
    assert_false(decision["should_invoke"], "shared accepted fallback invocation")
    assert_equal(decision["reason_code"], "shared_durable_metadata_present", "shared accepted reason")


def load_post_tool_namespace():
    """Load only the post-tool fallback helper with lightweight stubs."""
    source = CHAT_ROUTE.read_text(encoding="utf-8")
    module_tree = ast.parse(source, filename=str(CHAT_ROUTE))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "maybe_create_tabular_generated_output"
    ]
    assert_equal(len(selected_nodes), 1, "loaded post-tool helper")

    parity_events = []
    log_events = []

    def fake_emit_tabular_parity_event(settings, event_name, mode, **kwargs):
        parity_events.append({
            "settings": settings,
            "event_name": event_name,
            "mode": mode,
            "kwargs": kwargs,
        })

    namespace = {
        "TABULAR_RUN_TASK_COMBINED": "combined",
        "TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS": "hierarchical_analysis",
        "_get_tabular_generated_output_task_type": lambda generated, hierarchical, settings: "structured_export",
        "_shared_build_tabular_legacy_post_tool_fallback_decision": build_tabular_legacy_post_tool_fallback_decision,
        "classify_tabular_parity_request": lambda prompt: {"execution_contract": "structured_export"},
        "emit_tabular_parity_event": fake_emit_tabular_parity_event,
        "log_event": lambda *args, **kwargs: log_events.append({"args": args, "kwargs": kwargs}),
        "question_requests_tabular_generated_output": lambda prompt: True,
        "question_requests_tabular_hierarchical_analysis": lambda prompt: False,
        "raise_if_mixed_source_cancelled": lambda *args, **kwargs: None,
    }
    exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), str(CHAT_ROUTE), "exec"), namespace)
    namespace.update({
        "parity_events": parity_events,
        "log_events": log_events,
    })
    return namespace


def test_observe_mode_suppresses_post_tool_side_effects_before_source_selection():
    """Observe mode must not create legacy fallback work from tool invocations."""
    print("Testing observe-only post-tool fallback suppression...")
    namespace = load_post_tool_namespace()

    result = asyncio.run(namespace["maybe_create_tabular_generated_output"](
        user_question="Export every row as CSV.",
        invocations=[object()],
        gpt_model="gpt-4o",
        settings={"tabular_legacy_post_tool_fallback_mode": "observe"},
        conversation_id="conversation-1",
        user_id="user-1",
    ))

    event_names = [event["event_name"] for event in namespace["parity_events"]]
    suppressed_events = [
        event for event in namespace["parity_events"]
        if event["event_name"] == "post_tool_generated_output_fallback_suppressed"
    ]
    assert_equal(result, None, "observe mode result")
    assert_true("classification_started" in event_names, "classification started event")
    assert_true("classification_completed" in event_names, "classification completed event")
    assert_true(suppressed_events, "suppressed fallback event")
    assert_false("post_tool_generated_output_fallback_attempted" in event_names, "attempted fallback event")

    dimensions = suppressed_events[0]["kwargs"].get("dimensions") or {}
    assert_equal(dimensions["legacy_post_tool_fallback_mode"], "observe", "fallback mode dimension")
    assert_equal(dimensions["legacy_post_tool_fallback_action"], "observe", "fallback action dimension")
    assert_equal(dimensions["legacy_post_tool_fallback_reason"], "observe_only", "fallback reason dimension")
    assert_equal(dimensions["legacy_post_tool_fallback_should_invoke"], "false", "fallback invoke dimension")
    assert_true(namespace["log_events"], "suppression log event")


def run_tests():
    tests = [
        test_decision_modes_and_shared_acceptance_suppression,
        test_active_shared_orchestrator_records_suppressed_fallback_decision,
        test_observe_mode_suppresses_post_tool_side_effects_before_source_selection,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
