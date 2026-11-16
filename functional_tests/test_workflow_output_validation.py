# test_workflow_output_validation.py
"""
Functional tests for deterministic workflow output requirements and outcomes.
Version: 0.261.379
Implemented in: 0.261.108

Model prose cannot prove completion. Type, schema, identity, coverage and count
checks are reported separately from execution and explicit partial acceptance.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Import after the worktree module path is established.
from functions_workflow_results import build_workflow_task_result
from functions_workflow_validation import (
    failed_workflow_tool_citation_count,
    validate_workflow_task_output,
    workflow_output_contract_instruction,
    workflow_run_outcome,
)


def envelope(value=None, **kwargs):
    return {
        "execution": {"status": "succeeded"},
        "authoritative_output": "records",
        "outputs": {"records": {"kind": "records", "value": [] if value is None else value}},
        "validation": {"status": "not_requested"},
        "coverage": {},
        **kwargs,
    }


def test_unconfigured_legacy_output_remains_explicitly_unvalidated():
    report = validate_workflow_task_output(envelope([{"id": "one"}]))
    assert report["status"] == "not_requested"
    assert report["eligible"] is True


@pytest.mark.parametrize("completed,eligible", [(2, True), (1, False)])
def test_modern_analyze_uses_final_coverage_not_ready_to_save_presentation(completed, eligible):
    report = validate_workflow_task_output(envelope(
        [{"id": "one"}], analysis_origin=True,
        coverage={"progress_meta": {"phase": "ready_to_save", "status": "running"}},
        validation={"status": "valid", "coverage": {
            "status": "complete", "assigned_work_units": 2, "completed_work_units": completed,
        }},
    ))
    assert report["eligible"] is eligible


def test_accepting_any_output_does_not_claim_validation_occurred():
    report = validate_workflow_task_output(envelope(), {"kind": "any"})
    assert report["status"] == "not_requested"


def test_records_are_a_valid_json_array_representation():
    report = validate_workflow_task_output(envelope([{"id": "one"}]), {
        "kind": "json", "schema": {"type": "array"}, "expected_count": 1,
    })
    assert report["status"] == "valid"


def test_output_requirements_are_explained_without_fabrication_instructions():
    instructions = workflow_output_contract_instruction({
        "kind": "records", "expected_count": 3, "identity_field": "id",
    })
    assert "JSON array" in instructions
    assert "Expected collection size: 3" in instructions
    assert "Never invent records" in instructions
    assert workflow_output_contract_instruction(None) == ""

def test_typed_record_schema_and_exact_count_are_checked_without_model_judgment():
    data = [{"id": "item-1", "quantity": 7}, {"id": "item-2", "quantity": 3}]
    report = validate_workflow_task_output(envelope(data), {
        "kind": "records", "expected_count": 2, "identity_field": "id",
        "schema": {"type": "array", "items": {
            "type": "object", "required": ["id", "quantity"],
            "properties": {"id": {"type": "string"}, "quantity": {"type": "integer", "minimum": 0}},
            "additionalProperties": False,
        }},
    })
    assert report["status"] == "valid"
    assert report["counts"]["actual_count"] == 2


def test_success_looking_text_does_not_satisfy_record_contract():
    report = validate_workflow_task_output({
        **envelope(), "authoritative_output": "text",
        "outputs": {"text": {"kind": "text", "value": "PASS: Everything is complete."}},
    }, {"kind": "records"})
    assert report["status"] == "invalid"
    assert report["eligible"] is False
    assert report["reason_codes"] == ["output_kind_mismatch"]


@pytest.mark.parametrize("rows,reason", [
    ([{"id": "one"}, {"id": "one"}], "duplicate_output_identity"),
    ([{"id": "one"}, {}], "missing_output_identity"),
    ([{"id": True}], "missing_output_identity"),
])
def test_invalid_identities_cannot_be_accepted_as_partial(rows, reason):
    report = validate_workflow_task_output(envelope(rows), {
        "kind": "records", "identity_field": "id", "allow_partial": True,
    })
    assert report["status"] == "invalid"
    assert report["eligible"] is False
    assert reason in report["reason_codes"]


def test_zero_identity_and_distinct_typed_ids_are_not_false_duplicates():
    report = validate_workflow_task_output(envelope([{"id": 0}, {"id": "0"}]), {
        "kind": "records", "identity_field": "id",
    })
    assert report["status"] == "valid"


def test_legitimately_empty_output_has_exact_zero_cardinality():
    report = validate_workflow_task_output(envelope(), {"kind": "records", "expected_count": 0})
    assert report["status"] == "valid"


def test_incomplete_collection_requires_explicit_partial_acceptance():
    report = validate_workflow_task_output(envelope([{"id": "one"}]), {"kind": "records", "expected_count": 2})
    assert report["status"] == "incomplete"
    assert report["eligible"] is False
    accepted = validate_workflow_task_output(envelope([{"id": "one"}]), {
        "kind": "records", "expected_count": 2, "allow_partial": True,
    })
    assert accepted["status"] == "accepted_partial"
    assert workflow_run_outcome([{"status": "succeeded", "workflow_validation": accepted}]) == {
        "status": "completed_partial", "success": True,
    }


@pytest.mark.parametrize("coverage", [
    {},
    {"partial_coverage": True},
    {"total_windows": 10, "processed_windows": 9},
    {"progress_meta": {"status": "completed"}, "failed_windows": 1},
    {"progress_meta": {"status": "completed"}, "failed_windows": "1"},
    {"progress_meta": {"status": "completed"}, "total_windows": 10},
])
def test_required_coverage_cannot_be_assumed(coverage):
    report = validate_workflow_task_output(envelope(coverage=coverage), {
        "kind": "records", "require_complete_coverage": True,
    })
    assert report["status"] == "incomplete"


def test_completed_processing_with_exact_counts_satisfies_required_coverage():
    report = validate_workflow_task_output(envelope(coverage={
        "total_windows": 5, "processed_windows": 5, "failed_windows": 0,
    }), {"kind": "records", "require_complete_coverage": True})
    assert report["status"] == "valid"


def test_pending_background_result_is_never_accepted_as_partial():
    report = validate_workflow_task_output(envelope(execution={"status": "pending"}), {
        "kind": "records", "allow_partial": True,
    })
    assert report["status"] == "incomplete"
    assert report["eligible"] is False


def test_generic_validation_does_not_erase_stricter_analyze_validation():
    report = validate_workflow_task_output(envelope(validation={"valid": False}), {"kind": "records"})
    assert report["status"] == "invalid"
    assert report["reason_codes"] == ["producer_validation_failed"]


def test_partial_producer_report_keeps_its_explicit_partial_policy():
    report = validate_workflow_task_output(envelope(validation={"status": "partial", "valid": False}), {
        "kind": "records", "allow_partial": True,
    })
    assert report["status"] == "accepted_partial"


def test_known_missing_coverage_is_visible_even_without_a_user_schema():
    report = validate_workflow_task_output(envelope(coverage={
        "progress_meta": {"status": "completed"}, "failed_documents": ["one"],
    }))
    assert report["status"] == "incomplete"
    assert report["eligible"] is False


def test_report_never_echoes_private_model_values():
    report = validate_workflow_task_output(envelope([{"id": "PRIVATE-OUTPUT"}]), {
        "kind": "records", "schema": {"type": "array", "items": {"type": "integer"}},
    })
    assert report["status"] == "invalid"
    assert "PRIVATE-OUTPUT" not in str(report)


def test_final_run_includes_all_task_outcomes_not_only_last_success():
    tasks = [
        {"status": "succeeded", "workflow_validation": {"status": "invalid"}},
        {"status": "succeeded", "workflow_validation": {"status": "valid"}},
    ]
    assert workflow_run_outcome(tasks) == {"status": "invalid", "success": False}


def test_failed_tool_citation_invalidates_task_even_when_model_fabricates_schema_json():
    schema_contract = {
        "kind": "json",
        "schema": {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["Evaluation"]}},
            "required": ["status"],
        },
    }
    task_envelope = build_workflow_task_result(
        {
            "reply": '{"status":"Evaluation"}',
            "agent_citations": [
                {
                    "tool_name": "OpenApiPlugin.getSyntheticAcquisition",
                    "plugin_name": "OpenApiPlugin",
                    "function_name": "getSyntheticAcquisition",
                    "function_arguments": {"kwargs": {"acquisition_id": "DEMO-ACQ-ERROR503"}},
                    "success": False,
                    "error_message": "HTTP 503",
                }
            ],
        },
        workflow={"id": "wf-1"},
        run_id="run-1",
        task={"id": "task-1"},
    )
    assert task_envelope["execution"]["status"] == "failed"
    report = validate_workflow_task_output(task_envelope, schema_contract)
    assert report["status"] == "invalid"
    assert report["eligible"] is False
    assert "tool_invocation_failed" in report["reason_codes"]
    assert report["counts"]["failed_tool_calls"] == 1


def test_recovered_same_tool_call_in_task_does_not_fail_validation():
    citations = [
        {
            "tool_name": "OpenApiPlugin.getSyntheticAcquisition",
            "plugin_name": "OpenApiPlugin",
            "function_name": "getSyntheticAcquisition",
            "function_arguments": {"kwargs": {"acquisition_id": "DEMO-ACQ-001"}},
            "success": False,
            "error_message": "HTTP 503",
        },
        {
            "tool_name": "OpenApiPlugin.getSyntheticAcquisition",
            "plugin_name": "OpenApiPlugin",
            "function_name": "getSyntheticAcquisition",
            "function_arguments": {"kwargs": {"acquisition_id": "DEMO-ACQ-001"}},
            "success": True,
        },
    ]
    assert failed_workflow_tool_citation_count(citations) == 0
    task_envelope = build_workflow_task_result(
        {"reply": '{"id":"DEMO-ACQ-001","status":"Evaluation"}', "agent_citations": citations},
        workflow={"id": "wf-1"},
        run_id="run-1",
        task={"id": "task-1"},
    )
    assert task_envelope["execution"]["status"] == "succeeded"


def test_single_fenced_json_block_with_surrounding_prose_is_extracted_while_multiple_blocks_stay_text():
    single_block = build_workflow_task_result(
        {
            "reply": (
                "Here is the acquisition record:\n"
                "```json\n"
                '{"id": "DEMO-ACQ-001", "status": "Evaluation", "response_days": 15}\n'
                "```"
            )
        },
        workflow={"id": "wf-1"},
        run_id="run-1",
        task={"id": "task-1"},
    )
    assert single_block["authoritative_output"] == "json"
    assert single_block["outputs"]["json"]["value"] == {
        "id": "DEMO-ACQ-001",
        "status": "Evaluation",
        "response_days": 15,
    }

    competing_blocks = build_workflow_task_result(
        {
            "reply": (
                "Draft:\n```json\n{\"status\": \"Draft\"}\n```\n"
                "Final:\n```json\n{\"status\": \"Evaluation\"}\n```"
            )
        },
        workflow={"id": "wf-1"},
        run_id="run-1",
        task={"id": "task-1"},
    )
    assert competing_blocks["authoritative_output"] == "text"

    unclosed_fence = build_workflow_task_result(
        {"reply": "```\n" + ("\n " * 5000)},
        workflow={"id": "wf-1"},
        run_id="run-1",
        task={"id": "task-1"},
    )
    assert unclosed_fence["authoritative_output"] == "text"


def test_object_schema_instruction_requests_all_task_fields_when_additional_properties_allowed():
    open_schema_instructions = workflow_output_contract_instruction({
        "kind": "json",
        "schema": {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["Evaluation"]}},
            "required": ["status"],
        },
    })
    assert "Include all fields and details requested by the task instructions" in open_schema_instructions

    closed_schema_instructions = workflow_output_contract_instruction({
        "kind": "json",
        "schema": {
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
            "additionalProperties": False,
        },
    })
    assert "Include all fields and details requested by the task instructions" not in closed_schema_instructions

