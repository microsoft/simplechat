#!/usr/bin/env python3
# test_analyze_deliverable_contract.py
"""
Functional test for Analyze deliverable contract baselines.
Version: 0.250.185
Implemented in: 0.250.171; multi-format durable admission updated in 0.250.180; generated-output Analyze routing updated in 0.250.184

This test ensures Phase 1 defines a versioned Analyze deliverable contract,
keeps Analyze Markdown distinct from requested structured siblings, and uses
a deterministic 200-row oracle to detect source passthrough, lineage leakage,
schema drift, ordering failures, and known rule mismatches.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

from test_support.analyze_deliverable_contract_fixture import (
    FINANCIAL_REVIEW_OUTPUT_COLUMNS,
    FINANCIAL_REVIEW_PROMPT,
    KNOWN_FAULTY_SEARCH_VALUE_MISMATCHES,
    build_expected_financial_review_output_rows,
    build_faulty_search_output_rows,
    build_financial_review_source_rows,
    build_source_shaped_analyze_output_rows,
    find_value_mismatches,
)
from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from functions_analysis_deliverables import (  # noqa: E402
    ANALYSIS_ARTIFACT_ROLE_PRIMARY_ANALYSIS,
    ANALYSIS_ARTIFACT_ROLE_REQUESTED_OUTPUT,
    ANALYSIS_DELIVERABLE_EVENT_PLANNED,
    ANALYSIS_ORDERING_SOURCE_ORDER,
    ANALYSIS_ROW_CARDINALITY_ONE_PER_SOURCE_ROW,
    ANALYSIS_TRANSFORMATION_MODE_DETERMINISTIC,
    ANALYSIS_VALIDATION_PROFILE_EXACT_ROWS_SCHEMA_AND_RULES,
    build_analysis_deliverable_contract,
    build_safe_analysis_deliverable_event_properties,
    coerce_analysis_deliverable_contract,
    emit_analysis_deliverable_contract_event,
    normalize_analysis_artifact_role,
    validate_analysis_artifact_set,
    validate_structured_deliverable_rows,
)
from functions_tabular_orchestration import get_tabular_generated_output_task_type, plan_tabular_request  # noqa: E402


IMPLEMENTED_VERSION = "0.250.171"


def _build_fixture_contract(action_mode="analyze"):
    return build_analysis_deliverable_contract(
        action_mode=action_mode,
        requested_output_format="csv",
        public_output_schema=FINANCIAL_REVIEW_OUTPUT_COLUMNS,
        row_cardinality=ANALYSIS_ROW_CARDINALITY_ONE_PER_SOURCE_ROW,
        ordering=ANALYSIS_ORDERING_SOURCE_ORDER,
        transformation_mode=ANALYSIS_TRANSFORMATION_MODE_DETERMINISTIC,
        validation_profile=ANALYSIS_VALIDATION_PROFILE_EXACT_ROWS_SCHEMA_AND_RULES,
        source_fingerprint="fixture-source-fingerprint",
        request_fingerprint="fixture-request-fingerprint",
    )


def test_contract_roles_and_serialization_round_trip():
    print("Testing Analyze deliverable contract roles and serialization...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    analyze_contract = _build_fixture_contract("analyze")
    analyze_payload = analyze_contract.to_dict()
    assert analyze_payload["analysis_required"] is True
    assert analyze_payload["primary_artifact_role"] == ANALYSIS_ARTIFACT_ROLE_PRIMARY_ANALYSIS
    assert [artifact["role"] for artifact in analyze_payload["requested_artifacts"]] == [
        ANALYSIS_ARTIFACT_ROLE_PRIMARY_ANALYSIS,
        ANALYSIS_ARTIFACT_ROLE_REQUESTED_OUTPUT,
    ]
    assert [artifact["format"] for artifact in analyze_payload["requested_artifacts"]] == ["md", "csv"]

    search_contract = _build_fixture_contract("search")
    search_payload = search_contract.to_dict()
    assert search_payload["analysis_required"] is False
    assert search_payload["primary_artifact_role"] == ""
    assert [artifact["role"] for artifact in search_payload["requested_artifacts"]] == [
        ANALYSIS_ARTIFACT_ROLE_REQUESTED_OUTPUT,
    ]
    assert [artifact["format"] for artifact in search_payload["requested_artifacts"]] == ["csv"]
    assert search_payload["public_output_schema"] == analyze_payload["public_output_schema"]

    serialized = json.dumps(analyze_payload, sort_keys=True)
    reloaded = coerce_analysis_deliverable_contract(json.loads(serialized))
    assert reloaded.to_dict() == analyze_payload

    payload_with_future_field = dict(analyze_payload)
    payload_with_future_field["future_additive_field"] = "ignored"
    assert coerce_analysis_deliverable_contract(payload_with_future_field).to_dict() == analyze_payload

    try:
        normalize_analysis_artifact_role("not_a_role")
    except ValueError:
        pass
    else:
        raise AssertionError("Unknown artifact role was not rejected")


def test_artifact_set_requires_markdown_and_requested_sibling():
    print("Testing Analyze artifact set validation...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    contract = _build_fixture_contract("analyze")
    missing_markdown = validate_analysis_artifact_set(
        contract,
        artifacts=[{
            "artifact_id": "requested-csv",
            "role": ANALYSIS_ARTIFACT_ROLE_REQUESTED_OUTPUT,
            "format": "csv",
            "status": "completed",
        }],
    )
    assert not missing_markdown.valid
    assert "missing_required_artifact" in missing_markdown.reason_codes
    assert "wrong_primary_artifact_role" in missing_markdown.reason_codes

    wrong_descriptor = validate_analysis_artifact_set(
        contract,
        artifacts=[
            {
                "artifact_id": "analysis",
                "role": ANALYSIS_ARTIFACT_ROLE_REQUESTED_OUTPUT,
                "format": "csv",
                "status": "completed",
            },
            {
                "artifact_id": "requested-csv",
                "role": ANALYSIS_ARTIFACT_ROLE_REQUESTED_OUTPUT,
                "format": "csv",
                "status": "completed",
            },
        ],
    )
    assert not wrong_descriptor.valid
    assert "artifact_role_mismatch" in wrong_descriptor.reason_codes
    assert "artifact_format_mismatch" in wrong_descriptor.reason_codes

    valid_set = validate_analysis_artifact_set(
        contract,
        artifacts=[
            {
                "artifact_id": "analysis",
                "role": ANALYSIS_ARTIFACT_ROLE_PRIMARY_ANALYSIS,
                "format": "md",
                "status": "completed",
            },
            {
                "artifact_id": "requested-csv",
                "role": ANALYSIS_ARTIFACT_ROLE_REQUESTED_OUTPUT,
                "format": "csv",
                "status": "completed",
            },
        ],
    )
    assert valid_set.valid
    assert valid_set.counts["required_artifact_count"] == 2
    assert valid_set.counts["primary_artifact_count"] == 1


def test_financial_review_fixture_rejects_observed_failure_shapes():
    print("Testing 200-row fixture oracle against observed failure shapes...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    source_rows = build_financial_review_source_rows()
    expected_rows = build_expected_financial_review_output_rows(source_rows)
    assert len(source_rows) == 200
    assert len(expected_rows) == 200
    assert list(expected_rows[0].keys()) == FINANCIAL_REVIEW_OUTPUT_COLUMNS
    assert "2026-08-12" in FINANCIAL_REVIEW_PROMPT

    contract = _build_fixture_contract("analyze")
    source_passthrough_rows = build_source_shaped_analyze_output_rows(source_rows)
    passthrough_report = validate_structured_deliverable_rows(
        contract,
        source_passthrough_rows,
        source_rows=source_rows,
        expected_rows=expected_rows,
        identity_field="Item_ID",
    )
    assert not passthrough_report.valid
    assert "schema_mismatch" in passthrough_report.reason_codes
    assert passthrough_report.counts["output_row_count"] == 200
    assert passthrough_report.counts["actual_schema_field_count"] == 10
    assert passthrough_report.counts["public_schema_field_count"] == 9

    faulty_search_rows = build_faulty_search_output_rows(expected_rows, include_lineage=True)
    faulty_report = validate_structured_deliverable_rows(
        contract,
        faulty_search_rows,
        source_rows=source_rows,
        expected_rows=expected_rows,
        identity_field="Item_ID",
    )
    assert not faulty_report.valid
    assert "extra_internal_fields" in faulty_report.reason_codes
    assert "deterministic_value_mismatch" in faulty_report.reason_codes
    assert faulty_report.counts["extra_internal_field_count"] == 2
    assert faulty_report.counts["deterministic_mismatch_count"] == 5

    mismatches = find_value_mismatches(
        expected_rows,
        faulty_search_rows,
        field_names=FINANCIAL_REVIEW_OUTPUT_COLUMNS,
    )
    assert [(item["identity"], item["field"], item["actual"]) for item in mismatches] == [
        (item_id, field_name, actual_value)
        for item_id, field_name, actual_value in KNOWN_FAULTY_SEARCH_VALUE_MISMATCHES
    ]


def test_planner_attaches_shadow_deliverable_contract():
    print("Testing shared planner deliverable contract attachment...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    plan = plan_tabular_request(
        FINANCIAL_REVIEW_PROMPT + " Download the result as CSV.",
        [{"file_name": "financial_review.csv", "document_id": "doc-1", "source_version": "v1"}],
        action_mode="analyze",
        settings={"enable_tabular_hierarchical_analysis": True},
        requested_output_hints={"public_output_schema": FINANCIAL_REVIEW_OUTPUT_COLUMNS},
    )
    deliverable_contract = plan["deliverable_contract"]
    assert deliverable_contract["analysis_required"] is True
    assert deliverable_contract["public_output_schema"] == FINANCIAL_REVIEW_OUTPUT_COLUMNS
    assert [artifact["format"] for artifact in deliverable_contract["requested_artifacts"]] == ["md", "csv"]
    assert plan["durable_task_type"] == "combined"
    assert plan["execution_contract"] == "combined"


def test_phase2_planner_normalizes_ordered_artifact_intent():
    print("Testing Phase 2 normalized Analyze artifact intent...")
    assert_app_version_at_least("0.250.172")

    csv_plan = plan_tabular_request(
        "Analyze every row and create a CSV artifact.",
        [{"file_name": "financial_review.csv", "document_id": "doc-1", "source_version": "v1"}],
        action_mode="analyze",
        settings={"enable_tabular_hierarchical_analysis": True},
    )
    assert csv_plan["requested_output_formats"] == ["csv"]
    assert csv_plan["durable_task_type"] == "combined"
    assert [artifact["format"] for artifact in csv_plan["deliverable_contract"]["requested_artifacts"]] == [
        "md",
        "csv",
    ]

    multi_plan = plan_tabular_request(
        "Analyze every row and export as JSON, then create XML too. Do not create CSV.",
        [{"file_name": "financial_review.csv", "document_id": "doc-1", "source_version": "v1"}],
        action_mode="analyze",
        settings={"enable_tabular_hierarchical_analysis": True},
    )
    assert_app_version_at_least("0.250.180")
    assert multi_plan["requested_output_formats"] == ["json", "xml"]
    assert [artifact["format"] for artifact in multi_plan["deliverable_contract"]["requested_artifacts"]] == [
        "md",
        "json",
        "xml",
    ]
    assert multi_plan["durable_task_type"] == "combined"
    assert multi_plan["execution_contract"] == "combined"
    assert multi_plan["execution_state"] == "declined"
    assert multi_plan["reason_code"] == "durable_intent"

    generated_output_analyze_plan = plan_tabular_request(
        "Analyze every row and create a CSV artifact.",
        [{"file_name": "financial_review.csv", "document_id": "doc-1", "source_version": "v1"}],
        action_mode="analyze",
        settings={"enable_tabular_hierarchical_analysis": False},
    )
    assert generated_output_analyze_plan["durable_task_type"] == "combined"
    assert generated_output_analyze_plan["execution_contract"] == "combined"
    assert generated_output_analyze_plan["execution_state"] == "declined"
    assert generated_output_analyze_plan["reason_code"] == "durable_intent"
    assert get_tabular_generated_output_task_type(
        True,
        False,
        {"enable_tabular_hierarchical_analysis": False},
        action_mode="analyze",
    ) == "combined"
    assert get_tabular_generated_output_task_type(
        True,
        False,
        {"enable_tabular_hierarchical_analysis": False},
        action_mode="search",
    ) == "structured_export"

    search_markdown_plan = plan_tabular_request(
        "Search every row and write a Markdown report.",
        [{"file_name": "financial_review.csv", "document_id": "doc-1", "source_version": "v1"}],
        action_mode="search",
        settings={"enable_tabular_hierarchical_analysis": True},
    )
    assert search_markdown_plan["generated_output_requested"] is False
    assert [artifact["format"] for artifact in search_markdown_plan["deliverable_contract"]["requested_artifacts"]] == [
        "md",
    ]


def test_safe_deliverable_telemetry_excludes_prompt_and_row_values():
    print("Testing deliverable contract telemetry sanitization...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    contract = _build_fixture_contract("analyze")
    report = validate_structured_deliverable_rows(
        contract,
        build_faulty_search_output_rows(include_lineage=True),
        source_rows=build_financial_review_source_rows(),
        expected_rows=build_expected_financial_review_output_rows(),
        identity_field="Item_ID",
    )
    properties = build_safe_analysis_deliverable_event_properties(
        ANALYSIS_DELIVERABLE_EVENT_PLANNED,
        contract=contract,
        validation_report=report,
        dimensions={"error_type": "ValueError: secret/path/financial_review.csv"},
    )
    serialized = str(properties)
    assert "FRI-062" not in serialized
    assert "High Attention" not in serialized
    assert "financial_review" not in serialized
    assert "secret/path" not in serialized
    assert properties["dimension_error_type"] == "valueerror"
    assert properties["deterministic_mismatch_count"] == 5
    assert properties["extra_internal_field_count"] == 2

    assert emit_analysis_deliverable_contract_event(
        {},
        ANALYSIS_DELIVERABLE_EVENT_PLANNED,
        contract=contract,
    ) is None
    with patch("functions_analysis_deliverables.log_event") as log_event_mock:
        emitted = emit_analysis_deliverable_contract_event(
            {
                "enable_analysis_deliverable_contract_telemetry": True,
                "analysis_deliverable_contract_mode": "shadow",
            },
            ANALYSIS_DELIVERABLE_EVENT_PLANNED,
            contract=contract,
            validation_report=report,
        )
    assert emitted is not None
    assert log_event_mock.called


if __name__ == "__main__":
    tests = [
        test_contract_roles_and_serialization_round_trip,
        test_artifact_set_requires_markdown_and_requested_sibling,
        test_financial_review_fixture_rejects_observed_failure_shapes,
        test_planner_attaches_shadow_deliverable_contract,
        test_phase2_planner_normalizes_ordered_artifact_intent,
        test_safe_deliverable_telemetry_excludes_prompt_and_row_values,
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
