# test_workflow_data_flow_execution.py
"""
Functional tests for native data-flow execution through real workflow functions.
Version: 0.261.108
Implemented in: 0.261.108

Production Analyze, dispatch, immutable persistence/reload, binding, validation
and source-lineage readers run together; only provider and source I/O are faked.
"""

import json

import pytest

from test_workflow_task_result_handoff import build_inventory_run
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_bindings import load_workflow_reference
from functions_workflow_results import authorize_workflow_task_result_read, load_workflow_task_input


def run(runner, workflow):
    return runner["_execute_workflow_task_sequence"](
        workflow, {}, "conversation-inventory", "run-inventory", None, {}, actor_user_id="owner",
    )


def test_nonadjacent_binding_consumes_exact_original_records_not_intermediate_text():
    runner, workflow, records, requests, artifacts, items = build_inventory_run(100, 160)
    workflow["definition_version"] = 2
    workflow["tasks"].insert(1, {
        "id": "note", "name": "Interim note", "instructions": "Write only an unrelated note.",
        "inputs": [], "document_action": {"type": "none"},
    })
    workflow["tasks"][2]["inputs"] = [{
        "name": "inventory", "task_id": "extract", "output": "records", "expected_kind": "records",
    }]
    workflow["tasks"][0]["output_contract"] = {"kind": "records", "expected_count": 100, "identity_field": "item_id"}
    result = run(runner, workflow)
    assert result["workflow_outcome"] == {"status": "completed", "success": True}
    assert result["reply"].endswith("Inventory contains 100 items and 5050 units.")
    assert "An intermediate note" not in requests[-1]["messages"][-1]["content"]
    receipts = result["task_results"][2]["consumed_inputs"]
    assert receipts[0]["producer"]["task_id"] == "extract"
    assert receipts[0]["output_name"] == "records"
    assert receipts[0]["input_name"] == "inventory"
    assert result["task_results"][0]["workflow_validation"]["status"] == "valid"
    assert result["task_results"][1]["consumed_inputs"] == []


def test_invalid_output_is_persisted_but_required_downstream_task_is_not_invoked():
    runner, workflow, records, requests, artifacts, items = build_inventory_run(10)
    workflow["definition_version"] = 2
    workflow["tasks"][0]["output_contract"] = {
        "kind": "records", "schema": {"type": "array", "items": {"type": "object", "required": ["missing_field"]}},
    }
    result = run(runner, workflow)
    assert len(requests) == 1
    assert result["workflow_outcome"] == {"status": "invalid", "success": False}
    task = result["task_results"][0]
    assert task["status"] == "invalid"
    assert task["workflow_validation"]["eligible"] is False
    assert task["workflow_result"]["result_ref"]["sha256"]
    with pytest.raises(ValueError, match="requirements"):
        runner["load_workflow_task_input"](
            workflow, "run-inventory", "extract", task["workflow_result"]["result_ref"],
        )


def test_partial_acceptance_is_explicit_and_never_reports_full_completion():
    runner, workflow, records, requests, artifacts, items = build_inventory_run(10)
    workflow["definition_version"] = 2
    workflow["tasks"][0]["output_contract"] = {
        "kind": "records", "expected_count": 11, "allow_partial": True,
    }
    result = run(runner, workflow)
    assert len(requests) == 2
    assert result["workflow_outcome"] == {"status": "completed_partial", "success": True}
    assert result["task_results"][0]["workflow_validation"]["status"] == "accepted_partial"
    assert "missing_output_items" in result["task_results"][0]["workflow_validation"]["reason_codes"]


def test_continue_runs_independent_work_but_never_uses_an_invalid_required_producer():
    runner, workflow, records, requests, artifacts, items = build_inventory_run(10)
    workflow["definition_version"] = 2
    workflow["error_handling"] = {"strategy": "continue", "retry_count": 0}
    workflow["tasks"][0]["output_contract"] = {"kind": "records", "expected_count": 5}
    workflow["tasks"].insert(1, {
        "id": "note", "name": "Independent", "instructions": "Write only an unrelated note.",
        "inputs": [], "document_action": {"type": "none"},
    })
    workflow["tasks"][2]["inputs"] = [{"name": "original", "task_id": "extract", "output": "records"}]
    result = run(runner, workflow)
    assert len(requests) == 2
    assert [task["status"] for task in result["task_results"]] == ["invalid", "succeeded", "failed"]
    assert result["workflow_outcome"]["success"] is False


def test_shared_reference_lineage_survives_reload_and_revocation_blocks_reuse():
    runner, workflow, records, requests, artifacts, items = build_inventory_run(10)
    workflow["definition_version"] = 2
    reference = {
        "id": "criteria", "name": "criteria", "document_id": "criteria-source",
        "scope_type": "personal", "scope_id": "owner",
    }
    workflow["reference_inputs"] = [reference]
    allowed = True
    reference_loads = []

    def context(**kwargs):
        reference_loads.append(kwargs["document_id"])
        if not allowed:
            return None
        return {"scope": "personal", "document": {"id": "criteria-source", "user_id": "owner", "_etag": "etag-1"}}

    def chunks(**kwargs):
        return {
            "scope": "personal", "scope_id": "owner", "chunk_count": 1, "returned_chunk_count": 1,
            "chunks": [{"chunk_text": "Shared inventory policy: preserve every item identity."}],
        }

    def source_resolver(ids, **kwargs):
        return [{
            "document_id": source_id, "scope": "personal", "scope_id": "owner", "source_version": "etag-1",
            "authorization_status": "authorized" if allowed else "unresolved",
        } for source_id in ids]

    runner["load_workflow_reference"] = lambda workflow, ref, **kwargs: load_workflow_reference(
        workflow, ref, resolve_document=context, load_chunks=chunks, **kwargs,
    )
    runner["load_workflow_task_input"] = lambda *args, **kwargs: load_workflow_task_input(
        *args, load_result=runner["_load_result_section"], source_resolver=source_resolver, **kwargs,
    )
    runner["authorize_workflow_task_result_read"] = lambda *args, **kwargs: authorize_workflow_task_result_read(
        *args, load_result=runner["_load_result_section"], source_resolver=source_resolver, **kwargs,
    )
    result = run(runner, workflow)
    assert len(reference_loads) == 3
    assert all("Shared inventory policy" in request["messages"][-1]["content"] for request in requests)
    first = result["task_results"][0]["workflow_result"]
    manifest = runner["_load_result_section"](workflow, "run-inventory", "extract", first["result_ref"])
    assert manifest["analysis_access"]["sources"][0]["document_id"] == "criteria-source"
    assert manifest["analysis_origin"] is False
    last = result["task_results"][1]["workflow_result"]
    allowed = False
    with pytest.raises(AnalysisResultUnavailable):
        runner["load_workflow_task_input"](workflow, "run-inventory", "consume", last["result_ref"])


@pytest.mark.parametrize("expected_count,allow_partial,status,success", [
    (10, False, "completed", True),
    (11, False, "incomplete", False),
    (11, True, "completed_partial", True),
])
def test_real_run_entrypoint_persists_the_deliverable_outcome(expected_count, allow_partial, status, success):
    runner, workflow, records, requests, artifacts, items = build_inventory_run(10)
    workflow["definition_version"] = 2
    workflow["tasks"][0]["output_contract"] = {
        "kind": "records", "expected_count": expected_count, "allow_partial": allow_partial,
    }
    saved_runs = []
    activity = []
    runner.update({
        "WorkflowRunCancelledError": type("WorkflowRunCancelledError", (BaseException,), {}),
        "_save_workflow_run_record": lambda workflow, record: saved_runs.append(json.loads(json.dumps(record))) or record,
        "_execute_workflow_file_sync": lambda *args: None,
        "_ensure_workflow_conversation": lambda workflow: {"id": "conversation-inventory", "user_id": "owner"},
        "_create_user_message": lambda *args: {"id": "user-message"},
        "_initialize_workflow_assistant_tracking": lambda *args: ("assistant-message", None),
        "_prepare_workflow_url_access_context": lambda *args, **kwargs: {},
        "_attach_workflow_url_access_result": lambda result, context: result,
        "_create_assistant_message": lambda *args, **kwargs: {"id": "assistant-message"},
        "_mirror_workflow_visualizations_to_created_conversations": lambda *args: None,
        "_add_workflow_activity_thought": lambda *args, **kwargs: activity.append(kwargs),
        "_create_workflow_priority_alert": lambda *args, **kwargs: None,
        "log_workflow_run": lambda **kwargs: None,
    })
    result = runner["_run_personal_workflow_impl"](
        workflow, run_id="run-inventory", actor_user_id="owner",
    )
    assert result["run"]["status"] == status
    assert result["success"] is success
    assert saved_runs[-1]["status"] == status
    assert saved_runs[-1]["success"] is success
    assert result["workflow_updates"]["last_run_status"] == status
    assert result["workflow_updates"]["last_run_id"] == "run-inventory"
    assert any(event.get("kind") == "workflow_run" and event.get("status") == status for event in activity)
    assert len(requests) == (2 if success else 1)
