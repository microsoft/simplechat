# functions_workflow_repeat_execution.py
"""Serial post-body Repeat traversal using the existing operation units and journal."""

import json
from copy import deepcopy

from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_bindings import WorkflowInputError
from functions_workflow_collections import COLLECTION_MATERIALIZATION_BYTES
from functions_workflow_execution import WorkflowSuspended
from functions_workflow_flow import evaluate_predicate
from functions_workflow_identity import canonical_digest
from functions_workflow_node_results import (
    WorkflowLineageAuthorization, authorize_workflow_node_result_read, load_node_result,
    load_workflow_node_input, result_selectors,
)
from functions_workflow_repeat_state import (
    _plain_receipt, load_repeat_admission, load_repeat_head, log_repeat_event,
    prepare_repeat_state, repeat_identity, repeat_iteration_receipt, repeat_summary,
)
from functions_workflow_results import WorkflowResultNotReadyError, workflow_result_summary


def _boundary_payload(execution, node, region_id, identity, **fields):
    previous = execution.store.journal_read("execution", identity["execution_id"])
    return {
        **((previous or {}).get("payload") or {}),
        "execution_id": identity["execution_id"], "node_id": node["id"], "node_kind": "repeat_until",
        "region_id": region_id, "iteration_path": deepcopy(identity["iteration_path"]),
        "iteration_inputs": deepcopy(execution.iteration_inputs), "attempt": 1, **fields,
    }


def repeat_limit_gate(workflow, head, transition):
    return {
        "id": transition["gate_id"], "kind": "pause", "reason_code": "repeat_iteration_limit",
        "unit_id": head["node_id"], "input_digest": canonical_digest(transition),
        **result_selectors(head["identity"]), "definition_revision": workflow["definition_revision"],
        "reason": "The stop condition is still unmet. Saved state is retained. Explicit continuation grants one more batch without resetting the run's admission or elapsed-time limits.",
        "choices": ["continue_repeat", "cancel"], "repeat": repeat_summary(head),
    }


def _final_result(flow, node, identity, state, reference, outputs, controls):
    exports = {}
    receipts = list(controls)
    partial = state["partial"]
    for export in node["exports"]:
        receipt = outputs.get(export["output"])
        if receipt is None:
            continue
        manifest = load_node_result(
            flow.workflow, flow.run_id, receipt["producer"], receipt["result_ref"],
            load_result=flow.execution.load_result,
        )
        descriptor = manifest["outputs"][receipt["output_name"]]
        exports[export["name"]] = {
            "kind": descriptor["kind"], "result_ref": deepcopy(receipt["output_ref"]),
            "selected_producer": deepcopy(receipt),
        }
        receipts.append(receipt)
        partial |= (manifest.get("workflow_validation") or {}).get("status") == "accepted_partial"
    validation = {
        "version": 1, "status": "accepted_partial" if partial else "valid", "eligible": True,
        "reason_codes": ["repeat_partial_state_retained"] if partial else [],
    }
    manifest = {
        "contract_version": "workflow-result-v2", "identity": deepcopy(identity),
        "execution": {"status": "succeeded"}, "analysis_origin": False,
        "authoritative_output": next(iter(exports), None), "outputs": exports,
        "consumed_inputs": flow._receipts(receipts),
        "iteration_inputs": deepcopy(flow.execution.iteration_inputs),
        "repeat_state_proof": {"producer": deepcopy(identity), "state_ref": deepcopy(reference)},
        "workflow_validation": validation, "validation": {"status": "partial" if partial else "valid"},
        "coverage": {"status": "incomplete" if partial else "completed", "partial_coverage": partial},
    }
    result_ref = flow.execution.save_result(
        flow.workflow, flow.run_id, None, manifest, settings=flow.execution.settings, **result_selectors(identity),
    )
    return workflow_result_summary(manifest, result_ref)


def run_repeat_until(flow, node, region_id):
    execution, store = flow.execution, flow.execution.store
    parent_path = deepcopy(execution.iteration_path)
    parent_receipts = deepcopy(execution.iteration_inputs)
    controls = list(flow.control_receipts)
    identity = repeat_identity(flow.workflow, flow.run_id, node["id"], parent_path)
    flow._admit_control(node)
    existing = store.journal_read("loop", identity["execution_id"])
    if existing is None:
        try:
            initial, initial_ref = prepare_repeat_state(flow, node, identity)
        except AnalysisResultUnavailable:
            execution.pause_input("The Repeat state's original sources are no longer available.", code="workflow_repeat_source_unavailable")
        except (WorkflowInputError, WorkflowResultNotReadyError, ValueError):
            execution.pause_input(
                "The required initial Repeat state did not satisfy its contract. Saved originals are retained.",
                code="workflow_repeat_state_invalid",
            )
        head = {
            "kind": "repeat_until", "execution_id": identity["execution_id"], "node_id": node["id"],
            "identity": identity, "initial_state_ref": initial_ref, "current_state_ref": initial_ref,
            "next_iteration": 0, "completed_count": 0, "batch_number": 0, "batch_start_iteration": 0,
            "batch_size": node["max_iterations"], "batch_usage": 0, "exhaustion_count": 0,
            "continuation_count": 0, "grant_gate_id": None, "partial": initial["partial"], "state": "running",
        }
        store.journal_commit(execution.lease.token, "loop", identity["execution_id"], head, immutable=True)
    _, head, _ = load_repeat_head(flow.workflow, flow.run_id, identity, store=store)
    if head["state"] == "completed":
        row = store.journal_read("execution", identity["execution_id"])
        summary = row["payload"]["workflow_result"]
        authorize_workflow_node_result_read(
            flow.workflow, flow.run_id, identity, summary["result_ref"],
            reader_user_id=flow.actor_user_id, load_result=execution.load_result,
        )
        flow.partial |= head["partial"]
        flow._remember(node["id"], {"state": "completed", "summary": summary, "structured_validated": True})
        return
    if head["state"] == "waiting_manual_continue":
        transition = store.journal_read(
            "decision", ["repeat-transition", identity["execution_id"], head["next_iteration"] - 1],
        )["payload"]
        store.wait(execution.lease.token, state="paused", gate=repeat_limit_gate(flow.workflow, head, transition))
        raise WorkflowSuspended("paused")
    execution.record_execution(state="running", attempt=1, reason_code="")
    execution._attempt(1, state="running")
    while head["state"] == "running":
        execution.set_node(node, region_id, iteration_path=parent_path, iteration_inputs=parent_receipts)
        execution.check()
        iteration = head["next_iteration"]
        path = parent_path + [{"loop_id": node["id"], "iteration": iteration}]
        admission_key = ["repeat-iteration", identity["execution_id"], iteration]
        admitted = store.journal_read("admission", admission_key)
        if admitted is None:
            if head["batch_usage"] >= head["batch_size"]:
                raise WorkflowInputError("This Repeat batch requires an explicit continuation grant.")
            admission = {
                "execution_id": identity["execution_id"], "node_id": node["id"], "iteration": iteration,
                "iteration_path": path, "definition_revision": store.read()["definition_revision"],
                "before_state_ref": deepcopy(head["current_state_ref"]),
                "batch_number": head["batch_number"], "batch_start_iteration": head["batch_start_iteration"],
                "batch_size": head["batch_size"], "batch_usage": head["batch_usage"] + 1,
                "grant_gate_id": head["grant_gate_id"],
            }
            next_head = {**head, "batch_usage": head["batch_usage"] + 1}
            store.journal_commit_many(execution.lease.token, [
                {"kind": "admission", "key": admission_key, "payload": admission, "immutable": True, "admission": True},
                {"kind": "iteration", "key": [identity["execution_id"], iteration],
                 "payload": {**admission, "state": "running"}, "expected": None},
                {"kind": "loop", "key": identity["execution_id"], "payload": next_head, "expected": head},
            ], updates={"cursor": execution.cursor(), "phase": node["id"], "repeat_progress": repeat_summary(next_head)})
            head = next_head
        admission, iteration_receipt = load_repeat_admission(flow.workflow, flow.run_id, identity, iteration, store=store)
        try:
            authorization = WorkflowLineageAuthorization(
                flow.workflow, flow.run_id, reader_user_id=flow.actor_user_id, store=store, load_result=execution.load_result,
            )
            before = authorization.authorize_repeat(identity, admission["before_state_ref"])
            if authorization.access()["source_snapshot_changed"]:
                raise AnalysisResultUnavailable("analysis_source_snapshot_changed")
            execution.set_node(
                None, node["body"]["id"], iteration_path=path, iteration_inputs=parent_receipts + [iteration_receipt],
            )
            yield from flow._region(node["body"])
            resolved = flow.resolve(node["body"]["outputs"], metadata_only=True)
            outputs = {receipt["input_name"]: _plain_receipt(receipt) for receipt in resolved["bound_inputs"]}
            after, after_ref = prepare_repeat_state(
                flow, node, identity, previous=before, previous_ref=admission["before_state_ref"], outputs=outputs,
                consumed_inputs=resolved["consumed_inputs"],
            )
            values = {}
            for name in flow._predicate_names(node["until"]):
                receipt = after["slots"][name]["receipt"]
                payload, _ = load_workflow_node_input(
                    flow.workflow, flow.run_id, receipt["producer"], receipt["result_ref"],
                    output_name=receipt["output_name"], reader_user_id=flow.actor_user_id,
                    allow_partial=True, load_result=execution.load_result, max_bytes=COLLECTION_MATERIALIZATION_BYTES,
                )
                values[name] = json.loads(payload)["value"]
            condition = evaluate_predicate(node["until"], values)
        except AnalysisResultUnavailable:
            execution.set_node(node, region_id, iteration_path=parent_path, iteration_inputs=parent_receipts)
            execution.pause_input(
                "The Repeat state's original sources are no longer available. Saved originals are retained.",
                code="workflow_repeat_source_unavailable",
            )
        except (WorkflowInputError, WorkflowResultNotReadyError, ValueError):
            execution.set_node(node, region_id, iteration_path=parent_path, iteration_inputs=parent_receipts)
            execution.pause_input(
                "The required Repeat state or stop condition could not be validated. Saved originals are retained.",
                code="workflow_repeat_state_invalid",
            )
        finally:
            flow.control_receipts = list(controls)
            execution.set_node(node, region_id, iteration_path=parent_path, iteration_inputs=parent_receipts)
        exhausted = not condition and head["batch_usage"] == head["batch_size"]
        outcome = "completed" if condition else "exhausted" if exhausted else "continue"
        next_head = {
            **head, "current_state_ref": after_ref, "next_iteration": iteration + 1, "completed_count": iteration + 1,
            "partial": after["partial"], "state": "completed" if condition else "waiting_manual_continue" if exhausted else "running",
            "exhaustion_count": head["exhaustion_count"] + int(exhausted),
        }
        transition = {
            "decision_kind": "repeat_transition", "execution_id": identity["execution_id"], "node_id": node["id"],
            "iteration_path": parent_path, "iteration_inputs": parent_receipts, "body_path": path,
            "definition_revision": store.read()["definition_revision"], "attempt": 1,
            "iteration": iteration, "batch_number": head["batch_number"], "batch_size": head["batch_size"],
            "batch_usage": head["batch_usage"], "before_state_ref": admission["before_state_ref"], "after_state_ref": after_ref,
            "body_outputs_sha256": canonical_digest(outputs), "predicate_sha256": canonical_digest(node["until"]),
            "condition_result": condition, "outcome": outcome, "next_iteration": iteration + 1,
            "decided_at": store._now().isoformat(),
        }
        if exhausted:
            transition["gate_id"] = canonical_digest(["repeat-limit", identity, iteration, after_ref])
            transition["event_id"] = canonical_digest(["workflow_repeat_batch_exhausted", transition["gate_id"]])
            transition["reason_code"] = "repeat_iteration_limit"
            transition["repeat"] = repeat_summary(next_head)
        iteration_row = store.journal_read("iteration", [identity["execution_id"], iteration])
        rows = [
            {"kind": "decision", "key": ["repeat-transition", identity["execution_id"], iteration],
             "payload": transition, "immutable": True},
            {"kind": "iteration", "key": [identity["execution_id"], iteration], "expected": iteration_row["payload"],
             "payload": {**admission, "state": "completed_partial" if after["partial"] else "completed",
                         "after_state_ref": after_ref, "condition_result": condition, "completed_at": transition["decided_at"]}},
            {"kind": "loop", "key": identity["execution_id"], "payload": next_head, "expected": head},
        ]
        updates = {"cursor": execution.cursor(), "repeat_progress": repeat_summary(next_head), "phase": node["id"]}
        summary = None
        if condition:
            summary = _final_result(flow, node, identity, after, after_ref, outputs, controls)
            payload = _boundary_payload(
                execution, node, region_id, identity, state="completed", workflow_result=summary,
                workflow_validation=summary["workflow_validation"], consumed_inputs=summary["consumed_inputs"],
                structured_validated=True, reason_code="", completed_at=transition["decided_at"],
            )
            rows.extend([
                {"kind": "execution", "key": identity["execution_id"], "payload": payload},
                {"kind": "attempt", "key": [identity["execution_id"], 1], "payload": payload},
            ])
        elif exhausted:
            updates.update(state="paused", lease=None, gate=repeat_limit_gate(flow.workflow, next_head, transition))
            payload = _boundary_payload(
                execution, node, region_id, identity, state="paused", reason_code="repeat_iteration_limit",
            )
            rows.extend([
                {"kind": "execution", "key": identity["execution_id"], "payload": payload},
                {"kind": "attempt", "key": [identity["execution_id"], 1], "payload": payload},
            ])
        store.journal_commit_many(
            execution.lease.token, rows, updates=updates, counters={"exhaustion_count": 1} if exhausted else None,
        )
        head = next_head
        flow.partial |= after["partial"]
        flow.task_results[:] = [
            result for result in flow.task_results
            if not ((result.get("result") or {}).get("workflow_result") or {}).get("producer", {}).get("iteration_path")
            and not result.get("iteration_path")
        ]
        if exhausted:
            log_repeat_event(store, transition)
            raise WorkflowSuspended("paused")
        if condition:
            flow._remember(node["id"], {"state": "completed", "summary": summary, "structured_validated": True})
            return
