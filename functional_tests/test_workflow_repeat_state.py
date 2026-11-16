# test_workflow_repeat_state.py
"""
Functional tests for typed Repeat state, mixed nesting and retained partial data.
Version: 0.261.120
Implemented in: 0.261.120

All cases use the production serial runner and exact result transport with local
fictional records. Large data is never replaced by a preview or prefix.
"""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Production imports follow the isolated worktree import setup.
from functions_workflow_execution import WorkflowSuspended
from functions_workflow_identity import workflow_execution_id
from functions_workflow_node_results import load_workflow_node_input, open_workflow_record_input
from functions_workflow_repeat_history import workflow_repeat_state_page
from functions_workflow_runtime_store import WorkflowRuntimeConflict
from functions_workflow_validation import validate_workflow_task_output
from test_workflow_repeat_execution import (
    continue_repeat, execute_repeat, repeat_definition, repeat_head, repeat_runtime, state_binding,
)
from test_workflow_structured_flow import binding, task


def result(kind, value):
    return {"reply": "", "authoritative_result": {"kind": kind, "value": value}}


@pytest.mark.parametrize("kind", ["text", "json", "records", "document_results"])
def test_state_preserves_exact_supported_kind_and_original_passthrough_receipt(monkeypatch, kind):
    definition = repeat_definition()
    value = (
        "Exact fictional text " + chr(0x3A9) if kind == "text" else
        {"nested": {"ready": False, "zero": 0, "null": None}} if kind == "json" else
        [{"same": [False, 0, None, chr(0x3A9)]}, {"same": [False, 0, None, chr(0x3A9)]}]
    )
    if kind == "document_results":
        value = [{"document_id": f"fictional-{index}", "kind": "json", "value": record}
                 for index, record in enumerate(value)]
    contract = {"kind": kind}
    if kind == "json":
        contract["schema"] = {"type": "object", "required": ["nested"], "properties": {"nested": {"type": "object"}}}
    if kind in {"records", "document_results"}:
        contract["schema"] = {"type": "array", "items": {"type": "object"}}
    definition["tasks"][0]["output_contract"] = copy.deepcopy(contract)
    definition["tasks"][1]["inputs"] = [state_binding(kind=kind)]
    definition["tasks"][1]["output_contract"] = {"kind": "text"}
    loop = definition["flow"]["nodes"][1]
    loop["state"][0]["output_contract"] = contract
    loop["state"][0]["initial"]["output"] = {"document_results": "documents"}.get(kind, kind)
    loop["body"]["outputs"] = [state_binding("next", kind=kind)]
    loop["until"] = {"op": "eq", "left": {"literal": True}, "right": {"literal": True}}
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, definition=definition)

    def produce(current, resolved, execution):
        if current["id"] == "source":
            if kind == "document_results":
                return {"reply": "", "analysis_result": {
                    "per_document": True,
                    "document_results": [
                        {"document_id": item["document_id"], "full_result": {
                            "authoritative_result": {"kind": item["kind"], "value": item["value"]},
                        }} for item in value
                    ],
                }}
            return result(kind, value)
        actual = resolved["values"]["state"]
        assert (list(actual.iter_records()) if kind in {"records", "document_results"} else actual) == value
        return {"reply": "The fictional body ran once."}

    flow, calls = execute_repeat(workflow, store, result_for_task=produce, stream_collections=True)
    assert flow.finished and len(calls) == 2
    summary = store.journal_read("execution", workflow_execution_id(workflow, "run", "repeat"))["payload"]["workflow_result"]
    assert summary["outputs"]["state"]["selected_producer"]["producer"]["node_id"] == "source-node"
    payload, _ = load_workflow_node_input(
        workflow, "run", flow.final_outputs[0]["producer"], flow.final_outputs[0]["result_ref"], output_name="state",
    )
    assert json.loads(payload)["value"] == value


def test_partial_state_requires_opt_in_and_retains_limitations_after_valid_later_output(monkeypatch):
    definition = repeat_definition(2)
    for current in definition["tasks"]:
        current["output_contract"]["allow_partial"] = True
    loop = definition["flow"]["nodes"][1]
    loop["state"][0]["output_contract"]["allow_partial"] = True
    definition["tasks"][1]["inputs"][0]["allow_partial"] = True
    definition["flow"]["outputs"][0]["allow_partial"] = True
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, definition=definition)

    def partial_seed(current, envelope):
        if current["id"] == "source":
            envelope["coverage"] = {"status": "incomplete", "expected_count": 2, "processed_count": 1, "failed_count": 1}
            envelope["workflow_validation"] = validate_workflow_task_output(envelope, current["output_contract"])

    flow, _ = execute_repeat(workflow, store, target=2, envelope_transform=partial_seed)
    assert flow.finished and flow.partial
    head = repeat_head(workflow, store)
    final = store.journal_read("execution", head["execution_id"])["payload"]["workflow_result"]
    assert final["workflow_validation"]["status"] == "accepted_partial"
    state = workflow_repeat_state_page(
        workflow, "run", head["execution_id"], 1, reader_user_id="owner", phase="after",
    )
    assert state["partial"] and state["states"][0]["workflow_validation"]["status"] == "accepted_partial"
    assert "producer_coverage_incomplete" in state["states"][0]["limitations"]


def test_default_state_contract_rejects_partial_seed_without_running_body(monkeypatch):
    definition = repeat_definition()
    definition["tasks"][0]["output_contract"] = {**definition["tasks"][0]["output_contract"], "allow_partial": True}
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, definition=definition)
    calls = []

    def partial(current, envelope):
        envelope["coverage"] = {"status": "incomplete", "partial_coverage": True}
        envelope["workflow_validation"] = validate_workflow_task_output(envelope, current["output_contract"])

    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, calls=calls, envelope_transform=partial)
    assert [call[0] for call in calls] == ["source"]
    assert store.read()["gate"]["choices"] == ["cancel"]
    with pytest.raises(WorkflowRuntimeConflict):
        continue_repeat(store)


def test_partial_export_outside_state_survives_completed_repeat_replay(monkeypatch):
    definition = repeat_definition()
    definition["tasks"].append(task("report", contract={
        "kind": "json", "schema": {"type": "object"}, "allow_partial": True,
    }))
    loop = definition["flow"]["nodes"][1]
    loop["body"]["nodes"].append({"id": "report-node", "kind": "task", "task_id": "report"})
    loop["body"]["outputs"].append({**binding("report-node", "report", "json"), "allow_partial": True})
    loop["exports"].append({"name": "report", "output": "report"})
    definition["flow"]["outputs"] = []
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, definition=definition)

    def produce(current, resolved, execution):
        if current["id"] == "report":
            return result("json", {"fictional": "retained incomplete report"})
        return result("json", {"count": int(current["id"] == "body"), "ready": current["id"] == "body"})

    def partial_report(current, envelope):
        if current["id"] == "report":
            envelope["coverage"] = {"status": "incomplete", "partial_coverage": True}
            envelope["workflow_validation"] = validate_workflow_task_output(envelope, current["output_contract"])

    flow, _ = execute_repeat(workflow, store, result_for_task=produce, envelope_transform=partial_report)
    assert flow.finished and flow.partial and repeat_head(workflow, store)["partial"]
    head = repeat_head(workflow, store)
    state = workflow_repeat_state_page(workflow, "run", head["execution_id"], 0, reader_user_id="owner", phase="after")
    assert state["partial"] and state["states"][0]["workflow_validation"]["status"] == "valid"
    replayed, calls = execute_repeat(workflow, store)
    assert replayed.finished and replayed.partial and calls == []


def test_invalid_next_state_is_not_a_false_condition_or_manual_override(monkeypatch):
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, maximum=1)

    def produce(current, resolved, execution):
        return result("json", {"count": 0, "ready": False} if current["id"] == "source"
                      else {"count": "invalid fictional value", "ready": True})

    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, result_for_task=produce)
    head = repeat_head(workflow, store)
    assert head["completed_count"] == 0 and head["exhaustion_count"] == 0
    assert store.read()["gate"]["choices"] == ["cancel"]
    assert store.journal_read("decision", ["repeat-transition", head["execution_id"], 0]) is None


@pytest.mark.parametrize("third_frame", [False, True])
def test_nested_repeat_seeds_from_enclosing_state_and_grant_is_instance_bound(monkeypatch, third_frame):
    definition = repeat_definition()
    outer = definition["flow"]["nodes"][1]
    inner = copy.deepcopy(outer)
    inner.update(id="inner", max_iterations=1)
    inner["state"][0]["initial"] = state_binding(loop_id="repeat")["source"]
    inner["body"]["id"] = "inner-body"
    definition["tasks"][1]["inputs"] = [state_binding(loop_id="inner")]
    outer["body"]["nodes"] = [inner]
    outer["body"]["outputs"] = [binding("inner", "next", "state")]
    outer["until"] = {"op": "eq", "left": {"input": "state", "path": "/count"}, "right": {"literal": 3}}
    if third_frame:
        contract = {"kind": "records", "schema": {"type": "array", "items": {"type": "object"}}}
        definition["tasks"].extend([
            task("rows-source", contract=contract),
            task("leaf", inputs=[{"name": "item", "source": {"kind": "loop_item", "loop_id": "third", "scope": "current"}}],
                 contract=contract),
        ])
        definition["flow"]["nodes"].insert(1, {"id": "rows-source-node", "kind": "task", "task_id": "rows-source"})
        inner["body"]["nodes"].append({
            "id": "third", "kind": "for_each", "max_items": 1, "item_key": "source_identity",
            "inputs": [binding("rows-source-node", "rows", "records")], "iterable": {"kind": "input", "name": "rows"},
            "body": {"id": "third-body", "nodes": [{"id": "leaf-node", "kind": "task", "task_id": "leaf"}], "outputs": []},
        })
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, definition=definition)
    calls = []

    def produce(current, resolved, execution):
        if current["id"] == "source":
            return result("json", {"count": 0, "ready": False})
        if current["id"] == "rows-source":
            return result("records", [{"fictional": True}])
        if current["id"] == "leaf":
            return result("records", [resolved["values"]["item"]["value"]])
        count = resolved["values"]["state"]["count"] + 1
        return result("json", {"count": count, "ready": count >= 2})

    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, target=2, calls=calls, result_for_task=produce)
    gate = store.read()["gate"]
    assert gate["node_id"] == "inner" and gate["iteration_path"] == [{"loop_id": "repeat", "iteration": 0}]
    continue_repeat(store)
    flow, _ = execute_repeat(workflow, store, target=2, calls=calls, result_for_task=produce)
    body = [call for call in calls if call[0] == "body"]
    assert flow.finished and [call[1] for call in body] == [
        [{"loop_id": "repeat", "iteration": 0}, {"loop_id": "inner", "iteration": 0}],
        [{"loop_id": "repeat", "iteration": 0}, {"loop_id": "inner", "iteration": 1}],
        [{"loop_id": "repeat", "iteration": 1}, {"loop_id": "inner", "iteration": 0}],
    ]
    assert store.read()["repeat_counts"] == {"exhaustion_count": 1, "continuation_count": 1}
    if third_frame:
        leaves = [call for call in calls if call[0] == "leaf"]
        assert len(leaves) == 3 and all(len(call[1]) == 3 for call in leaves)
        assert all(set(call[1][-1]) == {"loop_id", "item_id", "index"} for call in leaves)


def test_for_each_inside_repeat_uses_exact_current_state_collection(monkeypatch):
    definition = repeat_definition()
    contract = {"kind": "records", "schema": {"type": "array", "items": {"type": "object"}}}
    definition["tasks"].extend([
        task("rows-source", contract=contract),
        task("leaf", inputs=[{"name": "item", "source": {"kind": "loop_item", "loop_id": "each", "scope": "current"}}],
             contract=contract),
    ])
    definition["flow"]["nodes"].insert(1, {"id": "rows-source-node", "kind": "task", "task_id": "rows-source"})
    loop = definition["flow"]["nodes"][2]
    loop["state"].append({
        "name": "rows", "initial": {"kind": "node_output", "node_id": "rows-source-node", "output": "records", "scope": "current"},
        "next": "rows", "output_contract": contract,
    })
    loop["body"]["nodes"].extend([
        {"id": "each", "kind": "for_each", "max_items": 2, "item_key": "source_identity",
         "inputs": [state_binding("rows", slot="rows", kind="records")], "iterable": {"kind": "input", "name": "rows"},
         "body": {"id": "each-body", "nodes": [{"id": "leaf-node", "kind": "task", "task_id": "leaf"}],
                  "outputs": [binding("leaf-node", "findings", "records")]}},
        {"id": "collect", "kind": "collect", "source": {"loop_id": "each", "output": "findings"}, "output_contract": contract},
    ])
    loop["body"]["outputs"].extend([
        state_binding("rows", slot="rows", kind="records"), binding("collect", "findings", "records"),
    ])
    loop["exports"] = [{"name": "state", "output": "findings"}]
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, definition=definition)
    rows = [{"key": 0}, {"key": 0}]

    def produce(current, resolved, execution):
        if current["id"] == "source":
            return result("json", {"count": 0, "ready": False})
        if current["id"] == "rows-source":
            return result("records", rows)
        if current["id"] == "leaf":
            return result("records", [resolved["values"]["item"]["value"]])
        count = resolved["values"]["state"]["count"] + 1
        return result("json", {"count": count, "ready": count >= 2})

    flow, calls = execute_repeat(workflow, store, result_for_task=produce)
    leaves = [call for call in calls if call[0] == "leaf"]
    assert flow.finished and len(leaves) == 4
    assert [call[1][0]["iteration"] for call in leaves] == [0, 0, 1, 1]
    assert all(set(call[1][1]) == {"loop_id", "item_id", "index"} for call in leaves)
    receipt = flow.final_outputs[0]
    assert list(open_workflow_record_input(
        workflow, "run", receipt["producer"], receipt["result_ref"], output_name="state",
    ).iter_records()) == rows


def test_large_record_state_stays_reference_only_and_streams_all_originals(monkeypatch):
    definition = repeat_definition(1)
    contract = {"kind": "records", "schema": {"type": "array", "items": {"type": "object"}}}
    definition["tasks"][0]["output_contract"] = contract
    definition["tasks"][1]["inputs"] = [state_binding(kind="records")]
    definition["tasks"][1]["output_contract"] = {"kind": "text"}
    loop = definition["flow"]["nodes"][1]
    loop["state"][0]["output_contract"] = contract
    loop["state"][0]["initial"]["output"] = "records"
    loop["body"]["outputs"] = [state_binding("next", kind="records")]
    loop["until"] = {"op": "eq", "left": {"literal": True}, "right": {"literal": True}}
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, definition=definition)
    records = [{"index": index, "payload": "x" * 5000, "null": None, "false": False} for index in range(1800)]
    observed = []

    def produce(current, resolved, execution):
        if current["id"] == "source":
            return result("records", records)
        reader = resolved["values"]["state"]
        observed.extend(row["index"] for row in reader.iter_records())
        return {"reply": "All complete fictional records were supplied separately."}

    flow, _ = execute_repeat(workflow, store, result_for_task=produce, stream_collections=True)
    assert flow.finished and observed == list(range(len(records)))
    head = repeat_head(workflow, store)
    assert head["current_state_ref"]["size_bytes"] < 8192 and len(json.dumps(head)) < 8192
    receipt = flow.final_outputs[0]
    reader = open_workflow_record_input(workflow, "run", receipt["producer"], receipt["result_ref"], output_name="state")
    assert list(reader.iter_records()) == records
