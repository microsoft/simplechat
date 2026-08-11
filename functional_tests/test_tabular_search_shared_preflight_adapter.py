#!/usr/bin/env python3
# test_tabular_search_shared_preflight_adapter.py
"""
Functional test for the Search shared tabular preflight adapter.
Version: 0.250.159
Implemented in: 0.250.159

This test ensures Phase 3 routes Search durable tabular preflight through the
shared planner gate while preserving legacy direct preflight behavior when the
gate is disabled or shadow-only.
"""

import ast
import logging
import sys
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_ROUTE = REPO_ROOT / "application" / "single_app" / "route_backend_chats.py"
IMPLEMENTED_VERSION = "0.250.159"


class FakeCancellationError(Exception):
    pass


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"Expected truthy value for {label}")


def load_search_adapter_namespace(flag_enabled=True, orchestration_result=None, orchestration_error=None):
    source = CHAT_ROUTE.read_text(encoding="utf-8")
    module_tree = ast.parse(source, filename=str(CHAT_ROUTE))
    function_names = {
        "_build_search_shared_preflight_metrics",
        "_emit_search_shared_preflight_event",
        "maybe_queue_search_tabular_generated_output",
    }
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    namespace = {
        "MixedSourceCancellationError": FakeCancellationError,
        "logging": logging,
        "_safe_int": lambda value: int(value or 0),
    }
    legacy_calls = []
    orchestrator_calls = []
    log_events = []

    def fake_settings_flag_enabled(settings, key, default=False):
        assert_equal(key, "enable_tabular_search_shared_preflight", "settings flag key")
        return flag_enabled

    def fake_direct_preflight(**kwargs):
        legacy_calls.append(kwargs)
        return {"export_run_id": "legacy-run", "status": "queued"}

    def fake_orchestrate_tabular_request(*args, **kwargs):
        orchestrator_calls.append({"args": args, "kwargs": kwargs})
        if orchestration_error:
            raise orchestration_error
        return dict(orchestration_result or {})

    def fake_log_event(*args, **kwargs):
        log_events.append({"args": args, "kwargs": kwargs})

    namespace.update({
        "_settings_flag_enabled": fake_settings_flag_enabled,
        "maybe_queue_direct_tabular_generated_output": fake_direct_preflight,
        "_shared_orchestrate_tabular_request": fake_orchestrate_tabular_request,
        "_shared_queue_direct_tabular_generated_output_from_plan": object(),
        "log_event": fake_log_event,
    })
    compiled = compile(ast.Module(body=selected_nodes, type_ignores=[]), str(CHAT_ROUTE), "exec")
    exec(compiled, namespace)
    namespace["legacy_calls"] = legacy_calls
    namespace["orchestrator_calls"] = orchestrator_calls
    namespace["log_events"] = log_events
    return namespace


def call_adapter(namespace, settings=None):
    return namespace["maybe_queue_search_tabular_generated_output"](
        user_question="Analyze every row and create a CSV file.",
        file_contexts=[{"file_name": "survey.csv", "source_hint": "workspace"}],
        user_id="user-1",
        conversation_id="conversation-1",
        gpt_model="gpt-4o",
        settings=settings or {
            "enable_tabular_search_shared_preflight": True,
            "tabular_request_planner_mode": "active",
        },
    )


def test_gate_off_uses_legacy_direct_preflight():
    print("Testing Search shared preflight gate-off behavior...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    namespace = load_search_adapter_namespace(flag_enabled=False)

    result = call_adapter(namespace, settings={"enable_tabular_search_shared_preflight": False})

    assert_equal(result["export_run_id"], "legacy-run", "legacy metadata")
    assert_equal(len(namespace["legacy_calls"]), 1, "legacy call count")
    assert_equal(len(namespace["orchestrator_calls"]), 0, "shared orchestrator call count")


def test_gate_on_planner_off_preserves_legacy_direct_preflight():
    print("Testing Search shared preflight planner-off behavior...")
    namespace = load_search_adapter_namespace(flag_enabled=True)

    result = call_adapter(namespace, settings={"tabular_request_planner_mode": "off"})

    assert_equal(result["export_run_id"], "legacy-run", "planner-off legacy metadata")
    assert_equal(len(namespace["legacy_calls"]), 1, "planner-off legacy call count")
    assert_equal(len(namespace["orchestrator_calls"]), 0, "planner-off orchestrator call count")


def test_shadow_mode_compares_then_preserves_legacy_preflight():
    print("Testing Search shared preflight shadow behavior...")
    namespace = load_search_adapter_namespace(
        flag_enabled=True,
        orchestration_result={
            "planner_mode": "shadow",
            "execution_contract": "combined",
            "execution_state": "declined",
            "reason_code": "durable_intent",
            "planner_contract_version": "tabular-orchestration-v1",
            "source_count": 1,
        },
    )

    result = call_adapter(namespace, settings={"tabular_request_planner_mode": "shadow"})

    assert_equal(result["export_run_id"], "legacy-run", "shadow legacy metadata")
    assert_equal(len(namespace["legacy_calls"]), 1, "shadow legacy call count")
    assert_equal(len(namespace["orchestrator_calls"]), 1, "shadow orchestrator count")
    orchestrator_kwargs = namespace["orchestrator_calls"][0]["kwargs"]
    assert_equal(orchestrator_kwargs["action_mode"], "search", "shared action mode")
    assert_equal(orchestrator_kwargs["caller"], "search", "shared caller")
    assert_equal(orchestrator_kwargs["planner_mode"], "shadow", "shared planner mode")
    assert_true(
        any(event["args"][0].endswith("shadow_compared") for event in namespace["log_events"]),
        "shadow telemetry",
    )


def test_active_mode_returns_shared_metadata_without_legacy_duplicate():
    print("Testing Search shared preflight active accepted behavior...")
    namespace = load_search_adapter_namespace(
        flag_enabled=True,
        orchestration_result={
            "planner_mode": "active",
            "execution_contract": "combined",
            "execution_state": "queued",
            "reason_code": "active_execution_accepted",
            "planner_contract_version": "tabular-orchestration-v1",
            "source_count": 1,
            "generated_output_metadata": {
                "export_run_id": "shared-run",
                "status": "queued",
                "row_count": 42,
                "task_type": "combined",
                "output_format": "csv",
            },
        },
    )

    result = call_adapter(namespace)

    assert_equal(result["export_run_id"], "shared-run", "shared metadata")
    assert_equal(len(namespace["legacy_calls"]), 0, "legacy duplicate count")
    assert_equal(len(namespace["orchestrator_calls"]), 1, "active orchestrator count")
    assert_true(
        any(event["args"][0].endswith("accepted") for event in namespace["log_events"]),
        "accepted telemetry",
    )


def test_active_failed_metadata_emits_failed_preflight_event():
    print("Testing Search shared preflight active failed metadata telemetry...")
    namespace = load_search_adapter_namespace(
        flag_enabled=True,
        orchestration_result={
            "planner_mode": "active",
            "execution_contract": "structured_export",
            "execution_state": "queued",
            "reason_code": "active_execution_accepted",
            "planner_contract_version": "tabular-orchestration-v1",
            "source_count": 1,
            "generated_output_metadata": {
                "background_export": True,
                "status": "failed",
                "output_format": "csv",
                "row_count": 0,
            },
        },
    )

    result = call_adapter(namespace)

    assert_equal(result["status"], "failed", "failed metadata status")
    assert_equal(len(namespace["legacy_calls"]), 0, "failed metadata legacy duplicate count")
    assert_true(
        any(event["args"][0].endswith("failed") for event in namespace["log_events"]),
        "failed metadata telemetry",
    )


def test_active_foreground_contract_declines_to_existing_foreground_path():
    print("Testing Search shared preflight active foreground decline behavior...")
    namespace = load_search_adapter_namespace(
        flag_enabled=True,
        orchestration_result={
            "planner_mode": "active",
            "execution_contract": "foreground_aggregate",
            "execution_state": "foreground",
            "reason_code": "foreground_contract",
            "planner_contract_version": "tabular-orchestration-v1",
            "source_count": 1,
            "generated_output_metadata": None,
        },
    )

    result = call_adapter(namespace)

    assert_equal(result, None, "foreground adapter result")
    assert_equal(len(namespace["legacy_calls"]), 0, "foreground legacy call count")
    assert_true(
        any(event["args"][0].endswith("declined") for event in namespace["log_events"]),
        "declined telemetry",
    )


def test_shared_failure_falls_back_to_legacy_safety_net():
    print("Testing Search shared preflight failure fallback behavior...")
    namespace = load_search_adapter_namespace(
        flag_enabled=True,
        orchestration_error=RuntimeError("simulated shared planner failure"),
    )

    result = call_adapter(namespace)

    assert_equal(result["export_run_id"], "legacy-run", "failure fallback metadata")
    assert_equal(len(namespace["legacy_calls"]), 1, "failure legacy call count")
    assert_true(
        any(event["args"][0].endswith("failed") for event in namespace["log_events"]),
        "failed telemetry",
    )


def test_search_call_sites_use_phase_3_adapter():
    print("Testing Search direct preflight call-site migration...")
    module_tree = ast.parse(CHAT_ROUTE.read_text(encoding="utf-8"), filename=str(CHAT_ROUTE))
    search_adapter_calls = [
        call
        for call in ast.walk(module_tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "maybe_queue_search_tabular_generated_output"
    ]
    required_keyword_names = {
        "user_question",
        "file_contexts",
        "user_id",
        "conversation_id",
        "gpt_model",
        "settings",
    }

    assert_true(len(search_adapter_calls) >= 4, "Search adapter call count")
    for call in search_adapter_calls:
        keyword_names = {
            keyword.arg
            for keyword in call.keywords
            if keyword.arg
        }
        assert_true(required_keyword_names <= keyword_names, "required adapter keywords")


def run_tests():
    tests = [
        test_gate_off_uses_legacy_direct_preflight,
        test_gate_on_planner_off_preserves_legacy_direct_preflight,
        test_shadow_mode_compares_then_preserves_legacy_preflight,
        test_active_mode_returns_shared_metadata_without_legacy_duplicate,
        test_active_failed_metadata_emits_failed_preflight_event,
        test_active_foreground_contract_declines_to_existing_foreground_path,
        test_shared_failure_falls_back_to_legacy_safety_net,
        test_search_call_sites_use_phase_3_adapter,
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
