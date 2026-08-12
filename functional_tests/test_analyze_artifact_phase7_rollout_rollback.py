#!/usr/bin/env python3
# test_analyze_artifact_phase7_rollout_rollback.py
"""
Functional test for Analyze artifact Phase 7 rollout rollback controls.
Version: 0.250.177
Implemented in: 0.250.177

This test ensures Phase 7 can stop new shared tabular parity assignments
through a backend-only rollback state without exposing prompts, filenames,
storage locators, or breaking already-persisted run readers.
"""

import ast
import sys
import traceback
import types
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
EXPORT_MODULE = APP_ROOT / "functions_tabular_generated_exports.py"
SETTINGS_MODULE = APP_ROOT / "functions_settings.py"
IMPLEMENTED_VERSION = "0.250.177"
sys.path.insert(0, str(APP_ROOT))


def install_lightweight_planner_dependency_stubs():
    assistant_exports_module = types.ModuleType("functions_assistant_table_exports")
    assistant_exports_module.assistant_table_export_requested = (
        lambda prompt: "csv" in str(prompt or "").lower()
    )
    generated_exports_module = types.ModuleType("functions_generated_file_exports")

    def get_requested_artifact_formats(prompt):
        normalized_prompt = str(prompt or "").lower()
        return [output_format for output_format in ("json", "xml", "csv") if output_format in normalized_prompt]

    generated_exports_module.get_requested_artifact_formats = get_requested_artifact_formats
    generated_exports_module.get_requested_structured_artifact_format = (
        lambda prompt: next(iter(get_requested_artifact_formats(prompt)), None)
    )
    generated_exports_module.get_requested_structured_artifact_formats = get_requested_artifact_formats
    sys.modules.setdefault("functions_assistant_table_exports", assistant_exports_module)
    sys.modules.setdefault("functions_generated_file_exports", generated_exports_module)


install_lightweight_planner_dependency_stubs()

from functions_tabular_orchestration import (  # noqa: E402
    build_tabular_parity_rollout_assignment,
    normalize_tabular_parity_rollout_state,
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
        "file_name": "phase7-private-source.csv",
        "source_hint": "workspace",
        "source_version": "etag-table-1",
        "storage_locator": {
            "container": "private-documents",
            "blob_path": "user-1/private/phase7-private-source.csv",
        },
    }


def load_public_rollout_normalizer():
    source = EXPORT_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(EXPORT_MODULE))
    selected_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_normalize_tabular_run_rollout_assignment"
    ]
    assert_equal(len(selected_nodes), 1, "loaded rollout normalizer")

    def safe_int(value, default=0, minimum=None, maximum=None):
        try:
            normalized_value = int(value)
        except (TypeError, ValueError):
            normalized_value = int(default)
        if minimum is not None:
            normalized_value = max(int(minimum), normalized_value)
        if maximum is not None:
            normalized_value = min(int(maximum), normalized_value)
        return normalized_value

    namespace = {"_safe_int": safe_int}
    exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), str(EXPORT_MODULE), "exec"), namespace)
    return namespace["_normalize_tabular_run_rollout_assignment"]


def test_rollout_state_normalization_and_assignment_reasons():
    """Rollout states must be deterministic, safe, and assignment-gating."""
    print("Testing Phase 7 rollout state assignment gates...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    base_settings = {
        "tabular_request_planner_mode": "active",
        "tabular_analyze_parity_rollout_percent": 100,
        "tabular_legacy_post_tool_fallback_mode": "observe",
    }
    active_assignment = build_tabular_parity_rollout_assignment(
        base_settings,
        request_key="stable-phase7-request",
        mode="analyze",
    )
    repeated_assignment = build_tabular_parity_rollout_assignment(
        base_settings,
        request_key="stable-phase7-request",
        mode="analyze",
    )
    paused_assignment = build_tabular_parity_rollout_assignment(
        {**base_settings, "tabular_analyze_parity_rollout_state": "paused"},
        request_key="stable-phase7-request",
        mode="analyze",
    )
    rollback_assignment = build_tabular_parity_rollout_assignment(
        {**base_settings, "tabular_analyze_parity_rollout_state": "rollback"},
        request_key="stable-phase7-request",
        mode="analyze",
    )
    excluded_assignment = build_tabular_parity_rollout_assignment(
        {**base_settings, "tabular_analyze_parity_rollout_percent": 0},
        request_key="stable-phase7-request",
        mode="analyze",
    )

    assert_equal(active_assignment, repeated_assignment, "stable active assignment")
    assert_equal(active_assignment["rollout_state"], "active", "active rollout state")
    assert_true(active_assignment["assigned"], "active rollout assignment")
    assert_equal(active_assignment["assignment_reason_code"], "assigned", "active reason")
    assert_equal(paused_assignment["assignment_reason_code"], "rollout_paused", "paused reason")
    assert_false(paused_assignment["assigned"], "paused assignment")
    assert_equal(rollback_assignment["assignment_reason_code"], "rollback_active", "rollback reason")
    assert_false(rollback_assignment["assigned"], "rollback assignment")
    assert_equal(excluded_assignment["assignment_reason_code"], "outside_rollout_cohort", "cohort reason")
    assert_false(excluded_assignment["assigned"], "cohort assignment")
    assert_equal(normalize_tabular_parity_rollout_state(state="invalid"), "active", "invalid default")

    serialized_assignment = str(rollback_assignment)
    assert_false("phase7-private-source.csv" in serialized_assignment, "no filenames in assignment")
    assert_false("blob_path" in serialized_assignment, "no blob paths in assignment")


def test_rollback_state_declines_new_execution_without_calling_executor():
    """Rollback must stop new durable assignment before side effects."""
    print("Testing Phase 7 rollback execution gate...")
    calls = []

    def fake_durable_executor(plan, **execution_context):
        calls.append({"plan": plan, "execution_context": execution_context})
        return {
            "export_run_id": "run-phase7",
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
            "tabular_request_planner_mode": "active",
            "tabular_analyze_parity_rollout_percent": 100,
            "tabular_analyze_parity_rollout_state": "rollback",
        },
        planner_mode="active",
        durable_execution_callback=fake_durable_executor,
    )

    assert_equal(calls, [], "durable executor calls")
    assert_equal(result["execution_state"], "declined", "execution state")
    assert_equal(result["reason_code"], "rollout_not_assigned", "execution reason")
    assert_equal(result["rollout_assignment"]["rollout_state"], "rollback", "rollout state")
    assert_equal(
        result["rollout_assignment"]["assignment_reason_code"],
        "rollback_active",
        "assignment reason",
    )
    assert_equal(result["generated_output_metadata"], None, "generated metadata")


def test_rollout_state_is_backend_only_and_status_safe():
    """Rollback settings must stay backend-only and public status metadata-safe."""
    print("Testing Phase 7 backend setting and public status safety...")
    settings_source = SETTINGS_MODULE.read_text(encoding="utf-8")
    assert_true("'tabular_analyze_parity_rollout_state'" in settings_source, "default rollout state setting")
    backend_key_start = settings_source.index("TABULAR_GENERATION_BACKEND_SETTING_KEYS = {")
    sanitizer_start = settings_source.index("def sanitize_settings_for_user")
    assert_true(
        "'tabular_analyze_parity_rollout_state'" in settings_source[backend_key_start:sanitizer_start],
        "backend-only rollout state setting",
    )

    normalize_public_assignment = load_public_rollout_normalizer()
    public_assignment = normalize_public_assignment({
        "contract_version": "tabular-parity-rollout-v1",
        "mode": "analyze",
        "planner_mode": "active",
        "rollout_state": "rollback",
        "assigned": False,
        "assignment_reason_code": "rollback_active",
        "cohort_bucket": 7,
        "rollout_percent": 100,
        "legacy_post_tool_fallback_mode": "observe",
        "prompt": "do not echo",
        "file_name": "phase7-private-source.csv",
        "blob_path": "user-1/private/phase7-private-source.csv",
    })

    assert_equal(public_assignment["rollout_state"], "rollback", "public rollout state")
    assert_equal(public_assignment["assignment_reason_code"], "rollback_active", "public reason")
    serialized_public_assignment = str(public_assignment)
    for forbidden_value in (
        "do not echo",
        "phase7-private-source.csv",
        "user-1/private/phase7-private-source.csv",
        "blob_path",
    ):
        assert_false(forbidden_value in serialized_public_assignment, f"redacted {forbidden_value}")


def run_tests():
    tests = [
        test_rollout_state_normalization_and_assignment_reasons,
        test_rollback_state_declines_new_execution_without_calling_executor,
        test_rollout_state_is_backend_only_and_status_safe,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
            print(f"PASS {test.__name__}")
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            traceback.print_exc()
            results.append(False)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
