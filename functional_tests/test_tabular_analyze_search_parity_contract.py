#!/usr/bin/env python3
# test_tabular_analyze_search_parity_contract.py
"""
Functional test for tabular Analyze/Search parity contract observation.
Version: 0.250.158
Implemented in: 0.250.158

This test ensures Phase 1 defines executable tabular request contracts,
keeps durable work pending until completed, emits only safe telemetry fields,
and captures the current Search-before-foreground versus Analyze-after-foreground baseline.
"""

import sys
from pathlib import Path
from unittest.mock import patch

from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from functions_tabular_parity_contract import (  # noqa: E402
    TABULAR_PARITY_CONTRACT_COMBINED,
    TABULAR_PARITY_CONTRACT_FOREGROUND_AGGREGATE,
    TABULAR_PARITY_CONTRACT_HIERARCHICAL_ANALYSIS,
    TABULAR_PARITY_CONTRACT_STRUCTURED_EXPORT,
    TABULAR_PARITY_EVIDENCE_COMPLETE,
    TABULAR_PARITY_EVIDENCE_PENDING,
    TABULAR_PARITY_EVENT_DURABLE_PREFLIGHT_ACCEPTED,
    TABULAR_PARITY_EVENT_DURABLE_PREFLIGHT_ATTEMPTED,
    TABULAR_PARITY_EVENT_FIRST_FOREGROUND_TABULAR_INVOCATION,
    TABULAR_PARITY_EVENT_POST_TOOL_FALLBACK_ATTEMPTED,
    TABULAR_PARITY_EVENT_POST_TOOL_FALLBACK_USED,
    TABULAR_PARITY_STATE_COMPLETED,
    TABULAR_PARITY_STATE_QUEUED,
    build_safe_tabular_parity_event_properties,
    build_tabular_parity_planner_result,
    classify_tabular_parity_request,
    is_tabular_parity_telemetry_enabled,
)


IMPLEMENTED_VERSION = "0.250.158"


def test_request_classification_matrix_is_format_neutral():
    print("Testing tabular parity request classification matrix...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    cases = [
        (
            "Export every row to CSV with no omissions",
            TABULAR_PARITY_CONTRACT_STRUCTURED_EXPORT,
            "csv",
            True,
            True,
        ),
        (
            "Generate a JSON object for each transaction in the full dataset",
            TABULAR_PARITY_CONTRACT_STRUCTURED_EXPORT,
            "json",
            True,
            True,
        ),
        (
            "Analyze every row in the entire workbook and summarize the risks",
            TABULAR_PARITY_CONTRACT_HIERARCHICAL_ANALYSIS,
            "",
            True,
            False,
        ),
        (
            "Analyze every row and save the findings as an XML output",
            TABULAR_PARITY_CONTRACT_COMBINED,
            "xml",
            True,
            True,
        ),
        (
            "Count rows by status and show the average amount",
            TABULAR_PARITY_CONTRACT_FOREGROUND_AGGREGATE,
            "",
            False,
            False,
        ),
        (
            "Inspect the columns and show a sample",
            TABULAR_PARITY_CONTRACT_FOREGROUND_AGGREGATE,
            "",
            False,
            False,
        ),
    ]

    for question, contract, output_format, requires_full_source, requires_artifact in cases:
        result = classify_tabular_parity_request(question)
        assert result.execution_contract == contract, question
        assert result.requested_output_format == output_format, question
        assert result.requires_full_source is requires_full_source, question
        assert result.requires_structured_artifact is requires_artifact, question

    small_result = classify_tabular_parity_request("Analyze every row in the entire table")
    large_result = classify_tabular_parity_request("Analyze every row in the entire table")
    assert small_result.execution_contract == large_result.execution_contract
    assert small_result.decision_reason_code == large_result.decision_reason_code


def test_planner_result_states_distinguish_pending_from_complete():
    print("Testing normalized planner result evidence states...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    queued_result = build_tabular_parity_planner_result(
        TABULAR_PARITY_CONTRACT_STRUCTURED_EXPORT,
        execution_state=TABULAR_PARITY_STATE_QUEUED,
        requires_full_source=True,
        requires_structured_artifact=True,
        requested_output_format="csv",
        decision_reason_code="explicit_structured_artifact",
        generated_tabular_outputs=[{"status": "queued"}],
    )
    completed_result = build_tabular_parity_planner_result(
        TABULAR_PARITY_CONTRACT_STRUCTURED_EXPORT,
        execution_state=TABULAR_PARITY_STATE_COMPLETED,
        requires_full_source=True,
        requires_structured_artifact=True,
        requested_output_format="csv",
        decision_reason_code="explicit_structured_artifact",
        generated_tabular_outputs=[{"status": "completed"}],
    )
    foreground_result = build_tabular_parity_planner_result(
        TABULAR_PARITY_CONTRACT_FOREGROUND_AGGREGATE,
        execution_state=TABULAR_PARITY_STATE_COMPLETED,
        decision_reason_code="bounded_aggregate_or_inspection",
    )

    assert queued_result.evidence_state == TABULAR_PARITY_EVIDENCE_PENDING
    assert completed_result.evidence_state == TABULAR_PARITY_EVIDENCE_COMPLETE
    assert foreground_result.evidence_state == TABULAR_PARITY_EVIDENCE_COMPLETE


def test_safe_telemetry_properties_exclude_prompt_and_source_values():
    print("Testing tabular parity telemetry sanitization...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    assert not is_tabular_parity_telemetry_enabled({})
    assert not is_tabular_parity_telemetry_enabled({
        "enable_tabular_parity_contract_telemetry": True,
        "tabular_parity_contract_mode": "off",
    })
    assert is_tabular_parity_telemetry_enabled({
        "enable_tabular_parity_contract_telemetry": True,
        "tabular_parity_contract_mode": "shadow",
    })

    manifest = [{
        "document_id": "secret-doc-id",
        "scope": "personal",
        "scope_id": "secret-scope-id",
        "source_kind": "tabular",
        "authorization_status": "authorized",
        "source_version": "etag-secret",
        "title": "Payroll.xlsx",
        "blob_path": "secret/path/Payroll.xlsx",
    }]
    result = classify_tabular_parity_request(
        "Export every row in Payroll.xlsx to CSV",
        source_manifest=manifest,
    )
    properties = build_safe_tabular_parity_event_properties(
        TABULAR_PARITY_EVENT_DURABLE_PREFLIGHT_ATTEMPTED,
        "search",
        planner_result=result,
        dimensions={"error_type": "ValueError: secret/path/Payroll.xlsx"},
    )
    serialized = str(properties)

    assert "Payroll" not in serialized
    assert "payroll" not in serialized
    assert "secret-doc-id" not in serialized
    assert "secret-scope-id" not in serialized
    assert "secret/path" not in serialized
    assert properties["dimension_error_type"] == "valueerror"
    assert properties["tabular_source_count"] == 1
    assert len(properties["source_manifest_fingerprint"]) == 24


def test_current_baseline_ordering_with_controlled_fakes():
    print("Testing current Search and Analyze call-order baseline with fakes...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    events = []

    def record(event_name):
        events.append(event_name)

    def fake_search_direct_preflight():
        record(TABULAR_PARITY_EVENT_DURABLE_PREFLIGHT_ATTEMPTED)
        record(TABULAR_PARITY_EVENT_DURABLE_PREFLIGHT_ACCEPTED)
        return {"export_run_id": "run-search", "status": "queued"}

    def fake_analyze_foreground_then_fallback():
        record(TABULAR_PARITY_EVENT_FIRST_FOREGROUND_TABULAR_INVOCATION)
        record(TABULAR_PARITY_EVENT_POST_TOOL_FALLBACK_ATTEMPTED)
        record(TABULAR_PARITY_EVENT_POST_TOOL_FALLBACK_USED)
        return {"export_run_id": "run-analyze", "status": "queued"}

    with patch("functions_tabular_parity_contract.log_event"):
        search_metadata = fake_search_direct_preflight()
        analyze_metadata = fake_analyze_foreground_then_fallback()

    assert search_metadata["status"] == "queued"
    assert analyze_metadata["status"] == "queued"
    assert events.index(TABULAR_PARITY_EVENT_DURABLE_PREFLIGHT_ACCEPTED) < events.index(
        TABULAR_PARITY_EVENT_FIRST_FOREGROUND_TABULAR_INVOCATION
    )
    assert events.index(TABULAR_PARITY_EVENT_POST_TOOL_FALLBACK_ATTEMPTED) > events.index(
        TABULAR_PARITY_EVENT_FIRST_FOREGROUND_TABULAR_INVOCATION
    )


if __name__ == "__main__":
    tests = [
        test_request_classification_matrix_is_format_neutral,
        test_planner_result_states_distinguish_pending_from_complete,
        test_safe_telemetry_properties_exclude_prompt_and_source_values,
        test_current_baseline_ordering_with_controlled_fakes,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            results.append(False)
    passed_count = sum(1 for result in results if result)
    print(f"\nResults: {passed_count}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
