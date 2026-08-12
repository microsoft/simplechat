#!/usr/bin/env python3
# test_tabular_phase8_ui_telemetry_rollout.py
"""
Functional test for Phase 8 tabular UI telemetry and rollout metadata.
Version: 0.250.167
Implemented in: 0.250.164; planning-only metadata hardening in 0.250.167

This test ensures shared tabular planner rollout assignment is stable and
redacted, backend-only rollout controls remain sanitized from frontend
settings, public generated-output status metadata contains safe lifecycle
fields, and shared preflight telemetry includes only safe rollout dimensions.
"""

import ast
import json
import sys
import types
from collections import Counter
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
EXPORT_MODULE = APP_ROOT / "functions_tabular_generated_exports.py"
SETTINGS_MODULE = APP_ROOT / "functions_settings.py"
WORKFLOW_RUNNER = APP_ROOT / "functions_workflow_runner.py"
CHAT_ROUTES = APP_ROOT / "route_backend_chats.py"
IMPLEMENTED_VERSION = "0.250.164"
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
    build_tabular_parity_rollout_assignment,
    normalize_tabular_legacy_post_tool_fallback_mode,
    plan_tabular_request,
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
            "container": "user-documents",
            "blob_path": "user-1/survey.csv",
        },
    }


def load_public_status_helpers():
    source = EXPORT_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(EXPORT_MODULE))
    function_names = {
        "_normalize_tabular_run_rollout_assignment",
        "_build_planner_source_coverage_summary",
        "_normalize_tabular_run_planner_metadata",
        "_normalize_tabular_run_source_format",
        "_build_tabular_run_source_coverage_summary",
        "_build_tabular_run_deferred_composition_reference",
        "_build_tabular_run_rollout_assignment_public_fields",
        "_build_tabular_run_lifecycle_public_fields",
        "_build_run_public_status",
    }
    selected_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    assert_equal({node.name for node in selected_nodes}, function_names, "loaded helper set")

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

    def normalize_task_type(task_type):
        normalized_task_type = str(task_type or "").strip().lower()
        if normalized_task_type in {"structured_export", "hierarchical_analysis", "combined"}:
            return normalized_task_type
        return "structured_export"

    namespace = {
        "Counter": Counter,
        "os": __import__("os"),
        "_safe_int": safe_int,
        "_sync_tabular_generation_contract_fields": lambda run: dict(run or {}),
        "_normalize_tabular_run_task_type": normalize_task_type,
        "_is_retryable_failed_run": lambda run: False,
        "_can_resume_run": lambda run, settings=None: False,
        "_can_cancel_run": lambda run: False,
        "_build_run_status_detail": lambda run, settings, retryable_failure, can_resume: {
            "status_label": "Queued",
            "status_tone": "info",
            "status_detail": "Queued and waiting for a worker.",
        },
        "_build_checkpoint_summary": lambda completed_batches, batch_count, processed_rows, row_count: "",
        "TABULAR_EXPORT_STATUS_QUEUED": "queued",
        "TABULAR_EXPORT_STATUS_RUNNING": "running",
        "TABULAR_EXPORT_STATUS_COMPLETED": "completed",
        "TABULAR_EXPORT_STATUS_FAILED": "failed",
        "TABULAR_EXPORT_STATUS_CANCELED": "canceled",
        "TABULAR_EXPORT_TERMINAL_STATUSES": {"completed", "failed", "canceled"},
        "TABULAR_RUN_TASK_STRUCTURED_EXPORT": "structured_export",
        "TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS": "hierarchical_analysis",
        "TABULAR_RUN_TASK_COMBINED": "combined",
        "TABULAR_EXPORT_ARTIFACT_PREVIEW_MAX_ROWS": 3,
        "TABULAR_GENERATION_PLAN_MAX_FIELDS": 50,
        "TABULAR_EXPORT_ARTIFACT_PREVIEW_MAX_CHARS": 1200,
    }
    exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), str(EXPORT_MODULE), "exec"), namespace)
    return namespace


def load_sanitize_settings_for_user():
    source = SETTINGS_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SETTINGS_MODULE))
    selected_nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "TABULAR_GENERATION_BACKEND_SETTING_KEYS":
                    selected_nodes.append(node)
        if isinstance(node, ast.FunctionDef) and node.name == "sanitize_settings_for_user":
            selected_nodes.append(node)
    namespace = {
        "sanitize_model_endpoints_for_frontend": lambda endpoints: list(endpoints or []),
        "normalize_support_latest_features_visibility": lambda visibility: {},
        "has_visible_support_latest_features": lambda settings: False,
        "get_public_workspace_label_context": lambda settings: {},
    }
    exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), str(SETTINGS_MODULE), "exec"), namespace)
    return namespace["sanitize_settings_for_user"]


def test_rollout_assignment_is_stable_redacted_and_percent_gated():
    """Rollout assignment must be stable and contain only safe dimensions."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    settings = {
        "tabular_request_planner_mode": "active",
        "tabular_analyze_parity_rollout_percent": 100,
        "enable_tabular_search_shared_preflight": True,
        "enable_tabular_analyze_durable_preflight": True,
        "enable_tabular_mixed_deferred_composition_planning": True,
        "enable_tabular_multifile_execution_unit_planning": True,
        "tabular_legacy_post_tool_fallback_mode": "observe",
    }
    first_assignment = build_tabular_parity_rollout_assignment(
        settings,
        request_key="stable-request-key",
        mode="analyze",
    )
    second_assignment = build_tabular_parity_rollout_assignment(
        settings,
        request_key="stable-request-key",
        mode="analyze",
    )
    disabled_assignment = build_tabular_parity_rollout_assignment(
        {**settings, "tabular_analyze_parity_rollout_percent": 0},
        request_key="stable-request-key",
        mode="analyze",
    )

    assert_equal(first_assignment, second_assignment, "stable assignment")
    assert_true(first_assignment["assigned"], "100 percent assignment")
    assert_false(disabled_assignment["assigned"], "0 percent assignment")
    assert_equal(first_assignment["legacy_post_tool_fallback_mode"], "observe", "fallback mode")
    assert_equal(
        normalize_tabular_legacy_post_tool_fallback_mode({"tabular_legacy_post_tool_fallback_mode": "invalid"}),
        "enabled",
        "fallback default",
    )
    forbidden_keys = {"prompt", "user_id", "file_name", "blob_path", "source_locator", "source_content"}
    assert_false(forbidden_keys & set(first_assignment), "redacted assignment keys")

    plan = plan_tabular_request(
        "Analyze every row and create a CSV file.",
        [build_context()],
        action_mode="analyze",
        settings={**settings, "enable_tabular_hierarchical_analysis": True},
        caller="analyze",
    )
    assert_equal(plan["rollout_assignment"]["contract_version"], "tabular-parity-rollout-v1", "planner rollout contract")
    assert_true(plan["rollout_assignment"]["assigned"], "planner rollout assignment")
    serialized_plan_assignment = json.dumps(plan["rollout_assignment"], sort_keys=True)
    assert_false("survey.csv" in serialized_plan_assignment, "no filename in assignment")
    assert_false("blob_path" in serialized_plan_assignment, "no blob path in assignment")


def test_backend_rollout_settings_stay_sanitized():
    """Phase 8 backend rollout controls must not reach frontend settings."""
    sanitize_settings_for_user = load_sanitize_settings_for_user()
    raw_settings = {
        "app_title": "SimpleChat",
        "tabular_analyze_parity_rollout_percent": 25,
        "tabular_legacy_post_tool_fallback_mode": "observe",
        "tabular_request_planner_mode": "active",
        "enable_tabular_search_shared_preflight": True,
        "enable_tabular_analyze_durable_preflight": True,
        "enable_tabular_mixed_deferred_composition_planning": True,
        "enable_tabular_multifile_execution_unit_planning": True,
    }
    sanitized = sanitize_settings_for_user(raw_settings)
    assert_equal(sanitized["app_title"], "SimpleChat", "ordinary setting remains")
    for setting_key in (
        "tabular_analyze_parity_rollout_percent",
        "tabular_legacy_post_tool_fallback_mode",
        "tabular_request_planner_mode",
        "enable_tabular_search_shared_preflight",
        "enable_tabular_analyze_durable_preflight",
        "enable_tabular_mixed_deferred_composition_planning",
        "enable_tabular_multifile_execution_unit_planning",
    ):
        assert_false(setting_key in sanitized, f"sanitized {setting_key}")

    settings_source = SETTINGS_MODULE.read_text(encoding="utf-8")
    for setting_key in (
        "tabular_analyze_parity_rollout_percent",
        "tabular_legacy_post_tool_fallback_mode",
        "enable_tabular_mixed_deferred_composition_planning",
        "enable_tabular_multifile_execution_unit_planning",
    ):
        assert_true(f"'{setting_key}'" in settings_source, f"default setting {setting_key}")
        backend_key_start = settings_source.index("TABULAR_GENERATION_BACKEND_SETTING_KEYS = {")
        sanitizer_start = settings_source.index("def sanitize_settings_for_user")
        assert_true(
            f"'{setting_key}'" in settings_source[backend_key_start:sanitizer_start],
            f"backend-only setting {setting_key}",
        )


def test_public_generated_output_status_has_safe_phase8_metadata():
    """Public status metadata must expose normalized state without locators."""
    helpers = load_public_status_helpers()
    planner_metadata = helpers["_normalize_tabular_run_planner_metadata"]({
        "planner_contract_version": "tabular-orchestration-v1",
        "execution_contract": "combined",
        "execution_state": "queued",
        "durable_task_type": "combined",
        "reason_code": "active_execution_accepted",
        "execution_group_id": "execution-group-1",
        "source_coverage": [{
            "file_name": "do-not-echo.csv",
            "source_format": "csv",
            "blob_path": "do/not/echo.csv",
        }],
        "rollout_assignment": {
            "contract_version": "tabular-parity-rollout-v1",
            "mode": "analyze",
            "planner_mode": "active",
            "assigned": True,
            "cohort_bucket": 7,
            "rollout_percent": 25,
            "search_shared_preflight_enabled": True,
            "analyze_durable_preflight_enabled": True,
            "mixed_deferred_composition_planning_enabled": True,
            "multifile_execution_unit_planning_enabled": False,
            "legacy_post_tool_fallback_mode": "observe",
            "raw_prompt": "do not echo",
        },
    })
    public_status = helpers["_build_run_public_status"]({
        "id": "run-1",
        "conversation_id": "conversation-1",
        "task_type": "combined",
        "status": "queued",
        "source_file_name": "source.csv",
        "selected_sheet": "",
        "output_format": "csv",
        "row_count": 250,
        "processed_rows": 0,
        "batch_count": 5,
        "completed_batches": 0,
        "source_descriptor": {
            "source_format": "csv",
            "container": "private-container",
            "blob_path": "user/private/source.csv",
            "expected_row_count": 250,
        },
        "tabular_planner_metadata": planner_metadata,
        "deferred_composition": {
            "composition_id": "composition-1",
            "contract_version": "phase5.v1",
            "status": "continuation_unavailable",
            "enabled": False,
            "planning_enabled": True,
            "continuation_available": False,
            "pending_source_count": 1,
            "required_source_count": 2,
            "required_tabular_runs": [{"run_id": "run-1", "document_id": "table-1"}],
            "manifest_fingerprint": "do-not-echo",
        },
    })

    assert_equal(public_status["metadata_contract_version"], "phase8.v1", "metadata contract")
    assert_equal(public_status["planner_contract_version"], "tabular-orchestration-v1", "planner contract")
    assert_equal(public_status["execution_contract"], "combined", "execution contract")
    assert_equal(public_status["execution_group_id"], "execution-group-1", "execution group")
    assert_equal(public_status["source_coverage_summary"]["source_count"], 1, "source count")
    assert_equal(public_status["source_coverage_summary"]["format_class_counts"], {"csv": 1}, "format counts")
    assert_equal(public_status["source_coverage_summary"]["pending_source_count"], 1, "pending source count")
    assert_equal(public_status["deferred_composition"]["composition_id"], "composition-1", "composition id")
    assert_equal(public_status["deferred_composition"]["required_tabular_run_count"], 1, "required run count")
    assert_true(public_status["deferred_composition"]["planning_enabled"], "composition planning enabled")
    assert_false(public_status["deferred_composition"]["continuation_available"], "composition continuation")
    assert_equal(public_status["rollout_assignment"]["rollout_percent"], 25, "rollout percent")
    assert_equal(public_status["rollout_assignment"]["legacy_post_tool_fallback_mode"], "observe", "legacy fallback")

    serialized_status = json.dumps(public_status, sort_keys=True)
    for forbidden_value in (
        "private-container",
        "user/private/source.csv",
        "do/not/echo.csv",
        "do not echo",
        "manifest_fingerprint",
    ):
        assert_false(forbidden_value in serialized_status, f"redacted {forbidden_value}")


def test_shared_preflight_telemetry_uses_safe_rollout_dimensions():
    """Search and Analyze shared preflight emitters must expose only safe rollout dimensions."""
    chat_route_source = CHAT_ROUTES.read_text(encoding="utf-8")
    workflow_source = WORKFLOW_RUNNER.read_text(encoding="utf-8")
    for source, label in ((chat_route_source, "search"), (workflow_source, "analyze")):
        assert_true("rollout_contract_version" in source, f"{label} rollout contract telemetry")
        assert_true("rollout_assigned" in source, f"{label} rollout assignment telemetry")
        assert_true("rollout_cohort_bucket" in source, f"{label} rollout bucket telemetry")
        assert_true("legacy_post_tool_fallback_mode" in source, f"{label} fallback telemetry")
        assert_false("source_file_name" in source[source.index("rollout_contract_version"):source.index("rollout_contract_version") + 600], f"{label} no filenames near rollout telemetry")


if __name__ == "__main__":
    tests = [
        test_rollout_assignment_is_stable_redacted_and_percent_gated,
        test_backend_rollout_settings_stay_sanitized,
        test_public_generated_output_status_has_safe_phase8_metadata,
        test_shared_preflight_telemetry_uses_safe_rollout_dimensions,
    ]
    failures = []
    for test in tests:
        try:
            print(f"Running {test.__name__}...")
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:
            failures.append((test.__name__, exc))
            print(f"FAIL {test.__name__}: {exc}")

    if failures:
        sys.exit(1)
    sys.exit(0)
