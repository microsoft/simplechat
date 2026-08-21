#!/usr/bin/env python3
# test_tabular_analyze_shared_preflight_adapter.py
"""
Functional test for the Analyze shared tabular preflight adapter.
Version: 0.250.199
Implemented in: 0.250.160; updated in 0.250.161 and 0.250.199

This test ensures Phase 4 routes pure single-source tabular Analyze durable
work through the shared planner before foreground tabular tools or immediate
synthesis can run, while preserving legacy foreground behavior when the gate
is disabled, shadow-only, or classified as bounded foreground work.
"""

import ast
import json
import logging
import sys
import time
import traceback
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
WORKFLOW_RUNNER = APP_ROOT / "functions_workflow_runner.py"
IMPLEMENTED_VERSION = "0.250.160"
sys.path.insert(0, str(APP_ROOT))

import functions_mixed_source_orchestration as orchestration  # noqa: E402


class FakeCancellationError(Exception):
    pass


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"Expected truthy value for {label}")


def build_manifest(document_id="table-1", file_name="survey.csv"):
    return [{
        "document_id": document_id,
        "display_name": file_name,
        "file_name": file_name,
        "source_kind": "tabular",
        "scope": "personal",
        "scope_id": "user-1",
        "source_version": "etag-1",
        "authorization_status": "authorized",
        "storage_locator": {
            "container": "user-documents",
            "blob_path": f"user-1/{file_name}",
        },
    }]


def load_workflow_namespace(orchestration_result=None, manifest=None):
    source = WORKFLOW_RUNNER.read_text(encoding="utf-8")
    module_tree = ast.parse(source, filename=str(WORKFLOW_RUNNER))
    function_names = {
        "_coerce_document_analysis_count",
        "_settings_bool",
        "_utc_now_iso",
        "_emit_analyze_shared_preflight_event",
        "_build_tabular_analyze_durable_handoff",
        "_get_tabular_generated_output_run_id",
        "_get_tabular_generated_output_status",
        "_is_nonterminal_tabular_generated_output",
        "_get_pending_tabular_generated_output",
        "_get_terminal_unsuccessful_tabular_generated_output",
        "_build_pending_tabular_run_reference",
        "_build_pending_tabular_evidence_envelope",
        "_build_terminal_unsuccessful_tabular_evidence_envelope",
        "_build_mixed_source_deferred_composition_descriptor",
        "_build_mixed_source_deferred_reply",
        "_maybe_execute_pure_tabular_analyze_preflight",
        "_build_mixed_source_analysis_coverage",
        "_execute_mixed_source_analyze_workflow",
    }
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    assert_equal({node.name for node in selected_nodes}, function_names, "loaded function set")

    source_manifest = list(manifest or build_manifest())
    foreground_calls = []
    orchestrator_calls = []
    reduction_calls = []
    log_events = []

    def fake_orchestrate_tabular_request(*args, **kwargs):
        orchestrator_calls.append({"args": args, "kwargs": kwargs})
        return dict(orchestration_result or {})

    def fake_execute_tabular(action_type, workflow, action_config, settings, **kwargs):
        foreground_calls.append({
            "action_type": action_type,
            "workflow": workflow,
            "action_config": action_config,
            "settings": settings,
            "kwargs": kwargs,
        })
        document_id = action_config["document_ids"][0]
        return {
            "result": {"analysis_reply": f"Computed {document_id}."},
            "agent_citations": [],
            "generated_tabular_outputs": [],
        }

    def fake_invoke_prompt(prompt, **kwargs):
        reduction_calls.append({"prompt": prompt, "kwargs": kwargs})
        return "Combined foreground answer."

    namespace = {
        "DOCUMENT_ACTION_TYPE_ANALYZE": "analyze",
        "EVIDENCE_ENGINE_DOCUMENT_ANALYSIS": orchestration.EVIDENCE_ENGINE_DOCUMENT_ANALYSIS,
        "EVIDENCE_ENGINE_TABULAR_TOOLS": orchestration.EVIDENCE_ENGINE_TABULAR_TOOLS,
        "EVIDENCE_STATUS_CANCELED": orchestration.EVIDENCE_STATUS_CANCELED,
        "EVIDENCE_STATUS_COMPLETED": orchestration.EVIDENCE_STATUS_COMPLETED,
        "EVIDENCE_STATUS_FAILED": orchestration.EVIDENCE_STATUS_FAILED,
        "EVIDENCE_STATUS_PENDING": orchestration.EVIDENCE_STATUS_PENDING,
        "MixedSourceCancellationError": FakeCancellationError,
        "SELECTION_MODE_SELECTED": "selected",
        "_get_document_action_source_ids": lambda config: (list(config.get("document_ids") or []), {}),
        "_resolve_tabular_document_action_model_name": lambda workflow, settings: "gpt-4o",
        "_build_workflow_model_context": lambda workflow, deployment_name, provider: {
            "endpoint_id": workflow.get("model_endpoint_id"),
            "model_id": workflow.get("model_id"),
            "model_deployment": deployment_name,
            "provider": provider,
        },
        "_resolve_analyze_all_document_ids": lambda *args, **kwargs: {},
        "_shared_orchestrate_tabular_request": fake_orchestrate_tabular_request,
        "_shared_queue_direct_tabular_generated_output_from_plan": object(),
        "_maybe_execute_tabular_document_action": fake_execute_tabular,
        "build_tabular_file_contexts_from_manifest": orchestration.build_tabular_file_contexts_from_manifest,
        "build_evidence_envelope": orchestration.build_evidence_envelope,
        "build_mixed_source_evidence_handoff": orchestration.build_mixed_source_evidence_handoff,
        "evaluate_mixed_source_mode_outcome": orchestration.evaluate_mixed_source_mode_outcome,
        "normalize_mixed_source_correlation_id": orchestration.normalize_mixed_source_correlation_id,
        "partition_source_manifest": orchestration.partition_source_manifest,
        "raise_if_mixed_source_cancelled": orchestration.raise_if_mixed_source_cancelled,
        "resolve_authorized_source_manifest": lambda *args, **kwargs: list(source_manifest),
        "run_document_analysis": lambda **kwargs: {},
        "emit_mixed_source_telemetry": lambda *args, **kwargs: False,
        "_build_mixed_source_analyze_reduction_prompt": lambda prompt, handoff: handoff["content"],
        "log_event": lambda *args, **kwargs: log_events.append({"args": args, "kwargs": kwargs}),
        "debug_print": lambda *args, **kwargs: None,
        "json": json,
        "logging": logging,
        "time": time,
    }
    exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), str(WORKFLOW_RUNNER), "exec"), namespace)
    namespace.update({
        "foreground_calls": foreground_calls,
        "orchestrator_calls": orchestrator_calls,
        "reduction_calls": reduction_calls,
        "log_events": log_events,
        "invoke_prompt": fake_invoke_prompt,
    })
    return namespace


def call_analyze(namespace, settings=None, document_ids=None):
    return namespace["_execute_mixed_source_analyze_workflow"](
        {
            "user_id": "user-1",
            "task_prompt": "Analyze every row and create a CSV file.",
            "model_endpoint_id": "endpoint-1",
            "model_id": "model-1",
            "model_provider": "aoai",
        },
        {"type": "analyze", "document_ids": document_ids or ["table-1"]},
        settings or {
            "enable_tabular_analyze_durable_preflight": True,
            "tabular_request_planner_mode": "active",
            "enable_tabular_hierarchical_analysis": True,
        },
        namespace["invoke_prompt"],
        conversation_id="conversation-1",
    )


def test_active_durable_preflight_short_circuits_foreground_and_synthesis():
    print("Testing active Analyze durable preflight short-circuit behavior...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    namespace = load_workflow_namespace(orchestration_result={
        "planner_mode": "active",
        "execution_contract": "combined",
        "execution_state": "queued",
        "reason_code": "active_execution_accepted",
        "planner_contract_version": "tabular-orchestration-v1",
        "durable_task_type": "combined",
        "generated_output_metadata": {
            "export_run_id": "run-123",
            "status": "queued",
            "task_type": "combined",
            "output_format": "csv",
        },
    })

    result = call_analyze(namespace)

    assert_equal(len(namespace["orchestrator_calls"]), 1, "shared orchestrator call count")
    assert_equal(len(namespace["foreground_calls"]), 0, "foreground tabular call count")
    assert_equal(len(namespace["reduction_calls"]), 0, "immediate synthesis call count")
    assert_equal(result["generated_tabular_outputs"][0]["export_run_id"], "run-123", "generated output metadata")
    assert_equal(result["coverage"]["documents"][0]["status"], "pending", "source coverage state")
    assert_equal(result["mixed_source_evidence"][0]["status"], "pending", "evidence status")
    assert_equal(result["tabular_execution_contract"], "combined", "execution contract")
    assert_true("accepted for full-source background processing" in result["analysis_reply"], "handoff reply")

    orchestrator_call = namespace["orchestrator_calls"][0]
    file_context = orchestrator_call["args"][1][0]
    assert_equal(file_context["document_id"], "table-1", "authorized context document id")
    assert_equal(file_context["storage_locator"]["blob_path"], "user-1/survey.csv", "authorized storage locator")
    assert_equal(orchestrator_call["kwargs"]["action_mode"], "analyze", "shared action mode")
    assert_equal(orchestrator_call["kwargs"]["planner_mode"], "active", "shared planner mode")
    assert_equal(
        orchestrator_call["kwargs"]["model_context"],
        {
            "endpoint_id": "endpoint-1",
            "model_id": "model-1",
            "model_deployment": "gpt-4o",
            "provider": "aoai",
        },
        "selected model context",
    )
    assert_true("token_usage_callback" not in orchestrator_call["kwargs"], "durable callback keyword compatibility")


def test_gate_off_preserves_foreground_analyze_path():
    print("Testing gate-off Analyze foreground behavior...")
    namespace = load_workflow_namespace()

    result = call_analyze(namespace, settings={"enable_tabular_analyze_durable_preflight": False})

    assert_equal(len(namespace["orchestrator_calls"]), 0, "gate-off orchestrator count")
    assert_equal(len(namespace["foreground_calls"]), 1, "gate-off foreground call count")
    assert_equal(len(namespace["reduction_calls"]), 1, "gate-off synthesis call count")
    assert_equal(result["reply"], "Combined foreground answer.", "gate-off reply")


def test_shadow_mode_compares_then_preserves_foreground_path():
    print("Testing shadow Analyze preflight behavior...")
    namespace = load_workflow_namespace(orchestration_result={
        "planner_mode": "shadow",
        "execution_contract": "combined",
        "execution_state": "declined",
        "reason_code": "durable_intent",
        "planner_contract_version": "tabular-orchestration-v1",
    })

    result = call_analyze(namespace, settings={
        "enable_tabular_analyze_durable_preflight": True,
        "tabular_request_planner_mode": "shadow",
    })

    assert_equal(len(namespace["orchestrator_calls"]), 1, "shadow orchestrator count")
    assert_equal(len(namespace["foreground_calls"]), 1, "shadow foreground call count")
    assert_equal(result["reply"], "Combined foreground answer.", "shadow reply")


def test_active_foreground_contract_declines_to_existing_foreground_path():
    print("Testing active foreground contract behavior...")
    namespace = load_workflow_namespace(orchestration_result={
        "planner_mode": "active",
        "execution_contract": "foreground_aggregate",
        "execution_state": "foreground",
        "reason_code": "foreground_contract",
        "planner_contract_version": "tabular-orchestration-v1",
        "generated_output_metadata": None,
    })

    result = call_analyze(namespace)

    assert_equal(len(namespace["orchestrator_calls"]), 1, "foreground contract orchestrator count")
    assert_equal(len(namespace["foreground_calls"]), 1, "foreground contract helper count")
    assert_equal(result["reply"], "Combined foreground answer.", "foreground contract reply")


def test_failed_durable_metadata_returns_honest_non_completion():
    print("Testing failed Analyze durable preflight metadata behavior...")
    namespace = load_workflow_namespace(orchestration_result={
        "planner_mode": "active",
        "execution_contract": "structured_export",
        "execution_state": "queued",
        "reason_code": "active_execution_accepted",
        "planner_contract_version": "tabular-orchestration-v1",
        "durable_task_type": "structured_export",
        "generated_output_metadata": {
            "status": "failed",
            "task_type": "structured_export",
            "output_format": "csv",
        },
    })

    result = call_analyze(namespace)

    assert_equal(len(namespace["foreground_calls"]), 0, "failed metadata foreground count")
    assert_equal(len(namespace["reduction_calls"]), 0, "failed metadata synthesis count")
    assert_equal(result["coverage"]["documents"][0]["status"], "failed", "failed source coverage state")
    assert_equal(result["mixed_source_evidence"][0]["status"], "failed", "failed evidence status")
    assert_true("could not be started" in result["analysis_reply"], "failed handoff reply")


def test_mixed_or_multi_source_requests_do_not_enter_single_source_preflight():
    print("Testing single-source Analyze preflight boundaries...")
    mixed_manifest = build_manifest() + [{
        "document_id": "narrative-1",
        "display_name": "brief.pdf",
        "file_name": "brief.pdf",
        "source_kind": "narrative",
        "scope": "personal",
        "scope_id": "user-1",
        "source_version": "etag-2",
        "authorization_status": "authorized",
    }]
    namespace = load_workflow_namespace(manifest=mixed_manifest)

    result = call_analyze(namespace, document_ids=["table-1", "narrative-1"])

    assert_equal(len(namespace["orchestrator_calls"]), 0, "mixed-source orchestrator count")
    assert_equal(len(namespace["foreground_calls"]), 1, "mixed-source foreground tabular count")
    assert_equal(result["reply"], "Combined foreground answer.", "mixed-source reply")


def run_tests():
    tests = [
        test_active_durable_preflight_short_circuits_foreground_and_synthesis,
        test_gate_off_preserves_foreground_analyze_path,
        test_shadow_mode_compares_then_preserves_foreground_path,
        test_active_foreground_contract_declines_to_existing_foreground_path,
        test_failed_durable_metadata_returns_honest_non_completion,
        test_mixed_or_multi_source_requests_do_not_enter_single_source_preflight,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            traceback.print_exc()
            results.append(False)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
