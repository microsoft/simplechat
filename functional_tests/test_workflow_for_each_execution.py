# test_workflow_for_each_execution.py
"""
Production-backed serial For each, frozen membership, and exact Collect regression tests.
Version: 0.261.117
Implemented in: 0.261.117

Real compiler, runner, journal, authorization, and result transport run against
the existing JSON-copying transactional fixtures. All provider calls are closed
fictional operations; no real document, workspace, model, or Azure service is used.
"""

import copy
import json
import sys
from pathlib import Path

import pytest
from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Production imports follow the isolated worktree import setup.
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_execution import WorkflowSuspended, workflow_execution_scope
from functions_workflow_bindings import WorkflowInputError
from functions_workflow_flow_runner import WorkflowFlowRunner
from functions_workflow_identity import workflow_execution_id
from functions_workflow_iterations import authorize_iteration_path
from functions_workflow_loop_history import workflow_execution_records_page, workflow_loop_items_page
from functions_workflow_node_results import open_workflow_record_input
from functions_workflow_results import build_workflow_task_result, persist_workflow_task_result, workflow_result_summary
from functions_workflow_runtime_store import WorkflowRuntimeConflict, WorkflowRuntimeLease
from functions_workflow_structured_execution import StructuredWorkflowExecution
from functions_workflow_validation import validate_workflow_task_output
from test_workflow_structured_flow import JournalContainer, binding, create_structured_runtime, task


class LoopJournalContainer(JournalContainer):
    def execute_item_batch(self, batch_operations, partition_key):
        # _store always replaces a JSON-copy; rollback needs the old mapping,
        # not a quadratic deep copy of every unrelated result page per write.
        before = self.items.copy()
        results = []
        try:
            for operation in batch_operations:
                name, arguments = operation[:2]
                options = operation[2] if len(operation) > 2 else {}
                if name == "replace":
                    identifier, body = arguments
                    result = self.replace_item(
                        identifier, body, etag=options.get("if_match_etag"),
                        match_condition=MatchConditions.IfNotModified,
                    )
                elif name == "create":
                    result = self.create_item(arguments[0])
                elif name == "upsert":
                    body = arguments[0]
                    result = self._store((partition_key, body["id"]), body)
                else:
                    raise AssertionError(f"Unexpected batch operation {name}.")
                results.append({"statusCode": 200, "resourceBody": result})
        except (CosmosHttpResponseError, AssertionError):
            self.items = before
            raise
        return results


def loop_definition(*, maximum=500, second_task=False):
    contract = {"kind": "records", "schema": {"type": "array", "items": {"type": "object"}}}
    item_input = {
        "name": "item", "source": {"kind": "loop_item", "loop_id": "each", "scope": "current"},
        "required": True, "expected_kind": "json", "allow_partial": False,
    }
    tasks = [task("source", contract=contract), task("body", inputs=[item_input], contract=contract)]
    body = [{"id": "body-node", "kind": "task", "task_id": "body"}]
    output_node = "body-node"
    if second_task:
        tasks.append(task("copy", inputs=[binding("body-node", "rows", "records")], contract=contract))
        body.append({"id": "copy-node", "kind": "task", "task_id": "copy"})
        output_node = "copy-node"
    return {
        "id": "workflow", "user_id": "owner", "definition_version": 3, "durable_execution": True,
        "runner_type": "model", "chat_capabilities_enabled": False,
        "limits": {"max_executions": 5000, "deadline_seconds": 86400},
        "error_handling": {"strategy": "halt", "retry_count": 0},
        "tasks": tasks,
        "flow": {"id": "root", "nodes": [
            {"id": "source-node", "kind": "task", "task_id": "source"},
            {
                "id": "each", "kind": "for_each", "inputs": [binding("source-node", "rows", "records")],
                "iterable": {"kind": "input", "name": "rows"}, "item_key": "source_identity",
                "max_items": maximum,
                "body": {"id": "body-region", "nodes": body, "outputs": [binding(output_node, "findings", "records")]},
            },
            {"id": "collect", "kind": "collect", "source": {"loop_id": "each", "output": "findings"},
             "output_contract": {**contract, "require_complete_coverage": True, "allow_partial": False}},
        ], "outputs": [binding("collect", "findings", "records")]},
    }


def loop_runtime(monkeypatch, *, definition=None, **definition_options):
    monkeypatch.setattr("test_workflow_structured_flow.JournalContainer", LoopJournalContainer)
    workflow, store, container, clock = create_structured_runtime(definition or loop_definition(**definition_options), monkeypatch)
    for module in ("functions_workflow_iterations", "functions_workflow_loop_history", "functions_workflow_execution_history"):
        monkeypatch.setattr(f"{module}.workflow_runtime_store", lambda *args: store)
    return workflow, store, container, clock


def execute_loop(workflow, store, records, *, calls=None, interrupt_at=None, result_for_item=None,
                 result_for_task=None, settings=None):
    calls = calls if calls is not None else []
    outcomes = []
    with WorkflowRuntimeLease(store, owner_id="loop-worker") as lease:
        execution = StructuredWorkflowExecution(store, lease, workflow, "run", settings=settings)
        with workflow_execution_scope(execution):
            flow = WorkflowFlowRunner(workflow, "run", execution, outcomes, actor_user_id="owner")
            for current in flow.tasks():
                if current["id"] == "body" and execution.iteration_path[-1]["index"] == interrupt_at:
                    raise SystemExit("Closed fixture interruption.")
                resolved = flow.resolve(current["inputs"])

                def invoke():
                    calls.append((current["id"], copy.deepcopy(execution.iteration_path), execution.execution_id()))
                    if result_for_task:
                        value = result_for_task(current, resolved, execution)
                    elif current["id"] == "source":
                        value = copy.deepcopy(records)
                    elif current["id"] == "body":
                        item = resolved["values"]["item"]
                        value = result_for_item(item) if result_for_item else [item["value"]]
                    else:
                        value = resolved["values"]["rows"]
                    return {"reply": "", "authoritative_result": {"kind": "records", "value": value}}

                result = execution.run_unit(
                    f"task:{current['id']}", invoke,
                    inputs={"task": current, "receipts": resolved["consumed_inputs"],
                            "iteration_inputs": resolved["iteration_inputs"]},
                    replay_safe=True, approval=current.get("approval"),
                )
                attempt = execution.unit(f"task:{current['id']}")["attempt"]
                envelope = build_workflow_task_result(result, workflow=workflow, run_id="run", task=current, attempt_count=attempt)
                envelope["consumed_inputs"] = resolved["consumed_inputs"]
                envelope["workflow_validation"] = validate_workflow_task_output(envelope, current["output_contract"])
                manifest, reference = persist_workflow_task_result(
                    envelope, workflow=workflow, run_id="run", task_id=current["id"], settings={},
                )
                summary = workflow_result_summary(manifest, reference)
                outcomes.append({
                    "task": current, "status": "succeeded", "attempt_count": attempt,
                    "execution_id": execution.execution_id(), "iteration_path": copy.deepcopy(execution.iteration_path),
                    "consumed_inputs": resolved["consumed_inputs"],
                    "result": {**result, "workflow_result": summary, "workflow_validation": envelope["workflow_validation"]},
                })
            return flow, calls


@pytest.mark.parametrize("count", [0, 1, 10, 100, 500])
def test_serial_loop_collects_every_item_with_exact_identity(monkeypatch, count):
    workflow, store, _, _ = loop_runtime(monkeypatch)
    rows = [{"record": index, "value": f"value-{index}"} for index in range(count)]
    flow, calls = execute_loop(workflow, store, rows)
    assert flow.finished and not flow.failed
    body_calls = [call for call in calls if call[0] == "body"]
    assert len(body_calls) == count and len({call[2] for call in body_calls}) == count
    assert [call[1][-1]["index"] for call in body_calls] == list(range(count))
    receipt = flow.final_outputs[0]
    reader = open_workflow_record_input(workflow, "run", receipt["producer"], receipt["result_ref"], output_name="records")
    assert list(reader.iter_records()) == rows
    assert reader.record_count == count and reader.manifest["analysis_origin"] is False
    assert reader.manifest["coverage"]["processed_count"] == count
    assert len(json.dumps(store.read())) < 16384


def test_restart_uses_frozen_membership_and_does_not_revisit_completed_siblings(monkeypatch):
    workflow, store, _, clock = loop_runtime(monkeypatch)
    rows = [{"index": index} for index in range(10)]
    calls = []
    with pytest.raises(SystemExit):
        execute_loop(workflow, store, rows, calls=calls, interrupt_at=7)
    first = list(calls)
    clock.advance()
    flow, _ = execute_loop(workflow, store, [{"changed": True}], calls=calls)
    assert [call[1][-1]["index"] for call in calls[len(first):] if call[0] == "body"] == [7, 8, 9]
    receipt = flow.final_outputs[0]
    assert list(open_workflow_record_input(
        workflow, "run", receipt["producer"], receipt["result_ref"], output_name="records",
    ).iter_records()) == rows
    clock.advance()
    _, resumed = execute_loop(workflow, store, [], calls=[])
    assert resumed == []


def test_item_limit_rejects_before_any_body_call_and_keeps_full_producer(monkeypatch):
    workflow, store, _, _ = loop_runtime(monkeypatch, maximum=10)
    calls = []
    with pytest.raises(WorkflowSuspended):
        execute_loop(workflow, store, [{"id": index} for index in range(11)], calls=calls)
    assert [call[0] for call in calls] == ["source"]
    assert store.read()["state"] == "paused"
    assert "11" in store.read()["gate"]["reason"] and "10" in store.read()["gate"]["reason"]
    assert store.read()["gate"]["choices"] == ["cancel"]


def test_zero_and_multiple_records_preserve_payloads_not_value_deduplication(monkeypatch):
    workflow, store, _, _ = loop_runtime(monkeypatch)
    flow, _ = execute_loop(
        workflow, store, [{"index": 0}, {"index": 1}, {"index": 2}],
        result_for_item=lambda item: [] if item["index"] == 1 else [{"equal": True}, {"equal": True}],
    )
    receipt = flow.final_outputs[0]
    reader = open_workflow_record_input(workflow, "run", receipt["producer"], receipt["result_ref"], output_name="records")
    assert list(reader.iter_records()) == [{"equal": True}] * 4
    assert reader.manifest["coverage"]["empty_count"] == 1
    assert reader.manifest["coverage"]["processed_count"] == 3


def test_large_multinode_loop_has_paged_exact_history_and_records(monkeypatch):
    workflow, store, _, _ = loop_runtime(monkeypatch, second_task=True)
    rows = [{"id": index, "data": "x" * 40} for index in range(500)]
    rows[251]["data"] = "MIDDLE-ONLY-SENTINEL"
    flow, _ = execute_loop(workflow, store, rows)
    assert store.read()["journal_counts"]["execution"] > 1000
    receipt = flow.final_outputs[0]
    page = workflow_execution_records_page(
        workflow, "run", receipt["producer"]["execution_id"], 1, reader_user_id="owner", limit=100,
    )
    gathered = page["records"]
    while page["next_cursor"]:
        page = workflow_execution_records_page(
            workflow, "run", receipt["producer"]["execution_id"], 1,
            reader_user_id="owner", limit=100, cursor=page["next_cursor"],
        )
        gathered.extend(page["records"])
    assert gathered == rows and gathered[251]["data"] == "MIDDLE-ONLY-SENTINEL"
    loop_id = workflow_execution_id(workflow, "run", "each")
    items = workflow_loop_items_page(workflow, "run", loop_id, reader_user_id="owner", limit=10)
    assert len(items["items"]) == 10 and items["next_cursor"] and items["total_count"] == 500
    assert len(items["items"][0]["execution_ids"]) == 2
    with pytest.raises(ValueError):
        workflow_execution_records_page(
            workflow, "run", receipt["producer"]["execution_id"], 1,
            reader_user_id="owner", cursor=items["next_cursor"],
        )


def test_declared_business_duplicates_are_invalid_and_never_deduplicated(monkeypatch):
    definition = loop_definition()
    definition["flow"]["nodes"][2]["output_contract"]["identity_field"] = "business_id"
    workflow, store, _, _ = loop_runtime(monkeypatch, definition=definition)
    with pytest.raises(WorkflowInputError):
        execute_loop(workflow, store, [{"business_id": "same"}, {"business_id": "same"}])
    identifier = workflow_execution_id(workflow, "run", "collect")
    saved = store.journal_read("attempt", [identifier, 1])["payload"]["workflow_result"]
    assert saved["workflow_validation"]["status"] == "invalid"
    assert "duplicate_output_identity" in saved["workflow_validation"]["reason_codes"]
    reader = open_workflow_record_input(
        workflow, "run", saved["producer"], saved["result_ref"], output_name="records", inspection=True,
    )
    assert list(reader.iter_records()) == [{"business_id": "same"}, {"business_id": "same"}]


def test_nested_serial_loops_keep_outer_and_inner_items_distinct(monkeypatch):
    definition = loop_definition()
    outer = definition["flow"]["nodes"][1]
    contract = {"kind": "records", "schema": {"type": "array", "items": {"type": "object"}}}
    definition["tasks"].append(task("leaf", inputs=[
        {"name": "child", "source": {"kind": "loop_item", "loop_id": "children", "scope": "current"}},
        {"name": "parent", "source": {"kind": "loop_item", "loop_id": "each", "scope": "current"}},
    ], contract=contract))
    outer["body"]["nodes"].extend([
        {"id": "children", "kind": "for_each", "inputs": [binding("body-node", "rows", "records")],
         "iterable": {"kind": "input", "name": "rows"}, "item_key": "source_identity", "max_items": 5,
         "body": {"id": "children-body", "nodes": [{"id": "leaf-node", "kind": "task", "task_id": "leaf"}],
                  "outputs": [binding("leaf-node", "records", "records")]}},
        {"id": "child-collect", "kind": "collect", "source": {"loop_id": "children", "output": "records"},
         "output_contract": contract},
    ])
    outer["body"]["outputs"] = [binding("child-collect", "findings", "records")]
    workflow, store, _, _ = loop_runtime(monkeypatch, definition=definition)

    def produce(current, resolved, execution):
        if current["id"] == "source":
            return [{"parent": "A"}, {"parent": "B"}]
        if current["id"] == "body":
            return [{"child": 0}, {"child": 1}]
        return [{
            "parent": resolved["values"]["parent"]["value"]["parent"],
            "child": resolved["values"]["child"]["value"]["child"],
        }]

    flow, calls = execute_loop(workflow, store, [], result_for_task=produce)
    assert all(len(path) == 2 for name, path, _ in calls if name == "leaf")
    receipt = flow.final_outputs[0]
    assert list(open_workflow_record_input(
        workflow, "run", receipt["producer"], receipt["result_ref"], output_name="records",
    ).iter_records()) == [
        {"parent": "A", "child": 0}, {"parent": "A", "child": 1},
        {"parent": "B", "child": 0}, {"parent": "B", "child": 1},
    ]


def test_identical_values_still_have_item_bound_approval_and_membership(monkeypatch):
    definition = loop_definition()
    definition["tasks"][1]["approval"] = {"required": True, "message": "Review this item."}
    workflow, store, _, clock = loop_runtime(monkeypatch, definition=definition)
    records, calls = [{"equal": True}, {"equal": True}], []
    with pytest.raises(WorkflowSuspended):
        execute_loop(workflow, store, records, calls=calls)
    control = store.read()
    first = copy.deepcopy(control["gate"])
    assert first["iteration_path"][0]["index"] == 0
    store.decide(
        expected_version=control["version"], gate_id=first["id"],
        choice="approve", actor_user_id="owner", request_id="approve-first-item",
    )
    clock.advance()
    with pytest.raises(WorkflowSuspended):
        execute_loop(workflow, store, records, calls=calls)
    control = store.read()
    second = control["gate"]
    assert second["iteration_path"][0]["index"] == 1 and first["execution_id"] != second["execution_id"]
    assert len([call for call in calls if call[0] == "body"]) == 1
    with pytest.raises(WorkflowRuntimeConflict):
        store.decide(
            expected_version=control["version"], gate_id=first["id"],
            choice="approve", actor_user_id="owner", request_id="stale-item-approval",
        )
    forged = copy.deepcopy(second)
    forged["iteration_path"][0]["index"] = 0
    with pytest.raises(AnalysisResultUnavailable):
        authorize_iteration_path(workflow, "run", forged, reader_user_id="owner", store=store)
    cancelled = store.request_cancel(actor_user_id="owner", request_id="cancel-second")
    assert cancelled["state"] == "cancelled"
    row = store.journal_read("attempt", [second["execution_id"], second["attempt"]])
    assert row["payload"]["state"] == "cancelled"


def test_optional_skips_require_explicit_partial_collection_and_keep_coverage(monkeypatch):
    definition = loop_definition()
    loop = definition["flow"]["nodes"][1]
    loop["body"]["nodes"][0]["run_when"] = {
        "op": "lt", "left": {"input": "item", "path": "/index"}, "right": {"literal": 1},
    }
    loop["body"]["outputs"][0]["required"] = False
    definition["flow"]["nodes"][2]["output_contract"]["allow_partial"] = True
    definition["flow"]["nodes"][2]["output_contract"]["require_complete_coverage"] = False
    definition["flow"]["outputs"][0]["allow_partial"] = True
    workflow, store, _, _ = loop_runtime(monkeypatch, definition=definition)
    flow, calls = execute_loop(workflow, store, [{"id": "first"}, {"id": "skipped"}])
    assert len([call for call in calls if call[0] == "body"]) == 1
    assert flow.partial and flow.finished
    receipt = flow.final_outputs[0]
    reader = open_workflow_record_input(
        workflow, "run", receipt["producer"], receipt["result_ref"], output_name="records", allow_partial=True,
    )
    assert list(reader.iter_records()) == [{"id": "first"}]
    assert reader.manifest["workflow_validation"]["status"] == "accepted_partial"
    assert reader.manifest["coverage"]["skipped_count"] == 1
    assert reader.manifest["coverage"]["empty_count"] == 0
    with pytest.raises(ValueError):
        open_workflow_record_input(workflow, "run", receipt["producer"], receipt["result_ref"], output_name="records")


def test_admitted_loop_policy_is_not_reset_by_new_controller_settings(monkeypatch):
    workflow, store, _, _ = loop_runtime(monkeypatch)
    assert store.read()["loop_policy"]["max_items"] == 500
    flow, calls = execute_loop(
        workflow, store, [{"id": "first"}, {"id": "second"}], settings={"workflow_max_loop_items": 1},
    )
    assert flow.finished and len([call for call in calls if call[0] == "body"]) == 2
    assert store.read()["loop_policy"]["max_items"] == 500
