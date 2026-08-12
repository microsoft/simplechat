#!/usr/bin/env python3
# test_tabular_phase7_lifecycle_coverage.py
"""
Functional test for Phase 7 tabular lifecycle coverage hardening.
Version: 0.250.167
Implemented in: 0.250.163

This test ensures shared tabular planner coverage starts as planned pending
evidence, canceled durable tabular evidence remains terminal but incomplete,
and pending or canceled required sources cannot be represented as full coverage.
"""

import sys
import ast
import types
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
EXPORT_MODULE = APP_ROOT / "functions_tabular_generated_exports.py"
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

from functions_mixed_source_orchestration import (  # noqa: E402
    AUTHORIZATION_STATUS_AUTHORIZED,
    EVIDENCE_ENGINE_TABULAR_TOOLS,
    EVIDENCE_STATUS_CANCELED,
    EVIDENCE_STATUS_PENDING,
    SOURCE_KIND_TABULAR,
    build_evidence_envelope,
    build_mixed_source_evidence_handoff,
    evaluate_mixed_source_mode_outcome,
)
from functions_tabular_orchestration import plan_tabular_request  # noqa: E402


def load_lifecycle_public_fields_helper():
    source = EXPORT_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(EXPORT_MODULE))
    helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_build_tabular_run_lifecycle_public_fields"
    )
    namespace = {
        "TABULAR_EXPORT_STATUS_QUEUED": "queued",
        "TABULAR_EXPORT_STATUS_RUNNING": "running",
        "TABULAR_EXPORT_STATUS_COMPLETED": "completed",
        "TABULAR_EXPORT_STATUS_FAILED": "failed",
        "TABULAR_EXPORT_STATUS_CANCELED": "canceled",
        "TABULAR_EXPORT_TERMINAL_STATUSES": {"completed", "failed", "canceled"},
    }
    module = ast.Module(body=[helper], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(EXPORT_MODULE), "exec"), namespace)
    return namespace["_build_tabular_run_lifecycle_public_fields"]


def build_context(document_id="table-1", file_name="rows.csv"):
    return {
        "document_id": document_id,
        "file_name": file_name,
        "source_hint": "workspace",
        "source_version": f"etag-{document_id}",
        "storage_locator": {
            "container": "documents",
            "blob_path": f"user/{file_name}",
        },
    }


def test_planner_source_coverage_starts_as_nonterminal_pending_lifecycle():
    """Preflight source coverage must be planned pending evidence, not complete."""
    assert_app_version_at_least("0.250.163")
    plan = plan_tabular_request(
        "Analyze every row for risk patterns.",
        [build_context()],
        action_mode="analyze",
        settings={"enable_tabular_hierarchical_analysis": True},
        caller="analyze",
    )

    source_coverage = plan["source_coverage"]
    assert len(source_coverage) == 1
    assert source_coverage[0]["coverage_state"] == "planned"
    assert source_coverage[0]["execution_state"] == "planned"
    assert source_coverage[0]["evidence_status"] == EVIDENCE_STATUS_PENDING
    assert source_coverage[0]["terminal"] is False
    assert source_coverage[0]["required_for_composition"] is True
    assert source_coverage[0]["generated_reference_present"] is False


def test_canceled_durable_evidence_is_terminal_but_incomplete():
    """Canceled durable work must not be pending or complete coverage."""
    manifest = [{
        "document_id": "table-1",
        "display_name": "Rows.csv",
        "source_kind": SOURCE_KIND_TABULAR,
        "scope": "personal",
        "scope_id": "user-1",
        "source_version": "etag-table-1",
        "authorization_status": AUTHORIZATION_STATUS_AUTHORIZED,
    }]
    canceled_envelope = build_evidence_envelope(
        document_id="table-1",
        source_kind=SOURCE_KIND_TABULAR,
        engine=EVIDENCE_ENGINE_TABULAR_TOOLS,
        status=EVIDENCE_STATUS_CANCELED,
        summary="Full-source tabular analysis was canceled before completion.",
        generated_artifacts=[{
            "run_id": "run-1",
            "status": "canceled",
            "task_type": "hierarchical_analysis",
        }],
        coverage={
            "terminal": True,
            "execution_contract": "hierarchical_analysis",
            "required_for_composition": True,
        },
    )

    handoff = build_mixed_source_evidence_handoff(
        manifest,
        [canceled_envelope],
        "selected",
        mode="analyze",
        telemetry_settings={},
    )
    coverage = handoff["mixed_source_coverage"]
    assert coverage["completed_source_count"] == 0
    assert coverage["pending_source_count"] == 0
    assert coverage["canceled_source_count"] == 1
    assert coverage["partial_coverage"] is True

    ledger_entry = coverage["terminal_ledger"][0]
    assert ledger_entry["status"] == EVIDENCE_STATUS_CANCELED
    assert ledger_entry["reason"] == "durable_work_canceled"
    assert ledger_entry["terminal"] is True
    assert ledger_entry["required_for_composition"] is True
    assert ledger_entry["execution_contract"] == "hierarchical_analysis"
    assert ledger_entry["generated_reference_present"] is True

    outcome = evaluate_mixed_source_mode_outcome(
        "analyze",
        {
            "entries": coverage["terminal_ledger"],
            "partial_coverage": coverage["partial_coverage"],
        },
    )
    assert outcome["status"] == EVIDENCE_STATUS_CANCELED
    assert outcome["should_reduce"] is False
    assert outcome["canceled_source_count"] == 1
    assert outcome["reason"] == "required_evidence_canceled"

    mixed_terminal_outcome = evaluate_mixed_source_mode_outcome(
        "analyze",
        {
            "entries": [
                {"status": EVIDENCE_STATUS_CANCELED},
                {"status": "failed"},
            ],
            "partial_coverage": True,
        },
    )
    assert mixed_terminal_outcome["status"] == "failed"
    assert mixed_terminal_outcome["reason"] == "no_successful_source"


def test_generated_output_public_status_exposes_lifecycle_contract():
    """Run metadata must expose lifecycle state without leaking internals."""
    build_fields = load_lifecycle_public_fields_helper()

    queued_fields = build_fields({"status": "queued"}, status_detail={}, can_resume=False)
    assert queued_fields["lifecycle_state"] == "queued"
    assert queued_fields["evidence_status"] == EVIDENCE_STATUS_PENDING
    assert queued_fields["terminal"] is False
    assert queued_fields["safe_reason_code"] == "queued"

    retry_fields = build_fields(
        {"status": "queued"},
        status_detail={"waiting_for_retry": True},
        can_resume=True,
    )
    assert retry_fields["lifecycle_state"] == "retrying"
    assert retry_fields["evidence_status"] == EVIDENCE_STATUS_PENDING
    assert retry_fields["terminal"] is False
    assert retry_fields["safe_reason_code"] == "retry_scheduled"

    finalizing_fields = build_fields(
        {"status": "running", "publishing_started_at": "2026-08-11T00:00:00Z"},
        status_detail={},
        can_resume=False,
    )
    assert finalizing_fields["lifecycle_state"] == "finalizing"
    assert finalizing_fields["evidence_status"] == EVIDENCE_STATUS_PENDING
    assert finalizing_fields["terminal"] is False
    assert finalizing_fields["safe_reason_code"] == "finalizing_publication"

    canceled_fields = build_fields({"status": "canceled"}, status_detail={}, can_resume=False)
    assert canceled_fields["lifecycle_state"] == "canceled"
    assert canceled_fields["evidence_status"] == EVIDENCE_STATUS_CANCELED
    assert canceled_fields["terminal"] is True
    assert canceled_fields["required_for_composition"] is True
    assert canceled_fields["safe_reason_code"] == "durable_work_canceled"


if __name__ == "__main__":
    tests = [
        test_planner_source_coverage_starts_as_nonterminal_pending_lifecycle,
        test_canceled_durable_evidence_is_terminal_but_incomplete,
        test_generated_output_public_status_exposes_lifecycle_contract,
    ]
    failures = []
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:
            failures.append((test.__name__, exc))
            print(f"FAIL {test.__name__}: {exc}")

    if failures:
        sys.exit(1)
    sys.exit(0)
