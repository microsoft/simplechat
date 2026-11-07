# test_workflow_loop_reporting_integration.py
"""
Functional integration of exact Collect with the actual saved-record report dispatcher.
Version: 0.261.122
Implemented in: 0.261.117

The production task sequence and reporting adapter use private serialized results
and a closed fake provider. No upload, indexing, source service, or model is called.
"""

import copy
import json

import pytest

from test_workflow_for_each_execution import loop_definition, loop_runtime
from test_workflow_structured_flow import binding, task
from test_workflow_task_result_handoff import build_inventory_run
from functions_saved_analysis import explain_saved_analysis
from functions_workflow_execution import WorkflowSuspended, workflow_execution_scope
from functions_workflow_identity import workflow_execution_id
from functions_workflow_node_results import open_workflow_record_input
from functions_workflow_results import authorize_workflow_task_result_read, persist_workflow_task_result
from functions_workflow_runtime_store import WorkflowRuntimeLease
from functions_workflow_structured_execution import StructuredWorkflowExecution


@pytest.mark.parametrize("processing,context_tokens,pauses", [
    (None, 131072, False), ("saved_record_report", 131072, False), (None, 4096, True),
])
def test_collected_records_reach_reporting_without_an_upload_or_character_clip(monkeypatch, processing, context_tokens, pauses):
    definition = loop_definition()
    definition["tasks"].append(task(
        "report", inputs=[binding("collect", "findings", "records")], contract={"kind": "text"},
    ))
    if processing:
        definition["tasks"][-1]["input_processing"] = processing
    definition["flow"]["nodes"].append({"id": "report-node", "kind": "task", "task_id": "report"})
    definition["flow"]["outputs"] = [binding("report-node", "report", "text")]
    workflow, store, _, _ = loop_runtime(monkeypatch, definition=definition)
    rows = [{"id": index, "note": "x" * 1000} for index in range(20)]
    rows[10]["note"] += "MIDDLE-RETAINED-COLLECT-SENTINEL"
    assert len(json.dumps(rows)) > 12000
    runner, _, _, _, _, _ = build_inventory_run()
    calls, requests = [], []

    def dispatch(execution_workflow, *args, **kwargs):
        name = execution_workflow["active_task"]["id"]
        calls.append(name)
        if name == "source":
            return {"reply": "", "authoritative_result": {"kind": "records", "value": copy.deepcopy(rows)}}
        if name == "body":
            prompt = execution_workflow["task_prompt"].split("[Previous workflow task output]\n", 1)[1]
            value = json.loads(prompt.split("\n\nUse the previous task output", 1)[0])
            return {"reply": "", "authoritative_result": {
                "kind": "records", "value": [value["inputs"][0]["result"]["value"]["value"]],
            }}
        assert name == "report" and execution_workflow["chat_capabilities_enabled"] is False
        readers = execution_workflow["_saved_analysis_inputs"]
        assert len(readers) == 1 and readers[0].handle.record_count == 20
        assert readers[0].allow_bounded_reporting is (processing == "saved_record_report")

        def invoke(messages, **options):
            requests.append(copy.deepcopy(messages))
            return "The complete saved findings retain MIDDLE-RETAINED-COLLECT-SENTINEL."

        report = explain_saved_analysis(
            readers, [{"role": "user", "content": execution_workflow["task_prompt"]}], invoke,
            model={
                "modelName": "closed-fixture", "contextWindow": context_tokens,
                "inputTokenLimit": context_tokens - 1024, "outputTokenLimit": 1024,
                "outputTokenAccounting": "total_generation",
            }, output_tokens=512,
        )
        return {"reply": report["reply"], "analysis_consumption": report["analysis_consumption"]}

    runner.update(
        _execute_workflow_dispatch=dispatch, persist_workflow_task_result=persist_workflow_task_result,
        authorize_workflow_task_result_read=authorize_workflow_task_result_read,
    )
    with WorkflowRuntimeLease(store, owner_id="report-worker") as lease:
        execution = StructuredWorkflowExecution(store, lease, workflow, "run")
        with workflow_execution_scope(execution):
            if pauses:
                with pytest.raises(WorkflowSuspended):
                    runner["_execute_workflow_task_sequence"](
                        workflow, {}, "closed-conversation", "run", None, {}, actor_user_id="owner",
                    )
                assert store.read()["state"] == "paused" and "retained" in store.read()["gate"]["reason"]
                assert requests == []
                collected = store.journal_read(
                    "attempt", [workflow_execution_id(workflow, "run", "collect"), 1],
                )["payload"]["workflow_result"]
                retained = open_workflow_record_input(
                    workflow, "run", collected["producer"], collected["result_ref"], output_name="records",
                )
                assert list(retained.iter_records()) == rows
                return
            result = runner["_execute_workflow_task_sequence"](
                workflow, {}, "closed-conversation", "run", None, {}, actor_user_id="owner",
            )
    assert result["workflow_outcome"] == {"status": "completed", "success": True}
    assert calls.count("body") == 20 and calls.count("report") == 1
    assert len(requests) == 1
    submitted = json.dumps(requests[0])
    assert "MIDDLE-RETAINED-COLLECT-SENTINEL" in submitted and len(submitted) > 12000
    assert "MIDDLE-RETAINED-COLLECT-SENTINEL" in result["reply"]
    diagnostics = result["task_results"][-1]["workflow_result"]["reporting"]
    assert diagnostics["record_count"] == 20 and diagnostics["model_calls"] == 1
    assert "checkpoints" not in diagnostics and "supported_conclusions" not in diagnostics
    assert diagnostics["context_budget"]["input_tokens"] <= diagnostics["context_budget"]["input_budget_tokens"]
