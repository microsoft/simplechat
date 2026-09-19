# functions_workflow_repeat_history.py
"""Authorized, bounded Repeat round and state-slot metadata inspection."""

import base64
import binascii
import json

from functions_workflow_execution_history import authorize_execution_payload
from functions_workflow_flow import compile_workflow_flow
from functions_workflow_identity import canonical_digest, workflow_execution_id
from functions_workflow_loop_history import _next_cursor, _page_position
from functions_workflow_node_results import WorkflowLineageAuthorization
from functions_workflow_repeat_state import load_repeat_admission, load_repeat_head, repeat_summary
from functions_workflow_runtime_store import workflow_runtime_store


def _repeat(workflow, run_id, execution_id, reader_user_id):
    store = workflow_runtime_store(workflow, run_id)
    workflow = store.run_definition()
    row = store.journal_read("loop", execution_id)
    if row is None or row["payload"].get("kind") != "repeat_until":
        raise LookupError("Repeat execution not found.")
    identity = row["payload"]["identity"]
    node, head, _ = load_repeat_head(workflow, run_id, identity, store=store)
    authorization = WorkflowLineageAuthorization(workflow, run_id, reader_user_id=reader_user_id, store=store)
    return workflow, store, node, head, identity, authorization


def workflow_repeat_iterations_page(workflow, run_id, execution_id, *, reader_user_id, cursor=None, limit=50):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Repeat pages require between 1 and 100 rounds.")
    workflow, store, node, head, identity, authorization = _repeat(workflow, run_id, execution_id, reader_user_id)
    scope = canonical_digest({"producer": identity, "initial_state_ref": head["initial_state_ref"], "kind": "repeat_iterations"})
    running = store.journal_read("admission", ["repeat-iteration", execution_id, head["next_iteration"]])
    total = head["next_iteration"] + int(running is not None)
    offset, through = 0, total
    anchor = None
    if cursor:
        try:
            if not isinstance(cursor, str) or len(cursor) > 1024:
                raise ValueError
            value = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
            if set(value) != {"scope", "offset", "through", "anchor"} or value["scope"] != scope:
                raise ValueError
            offset, through, anchor = value["offset"], value["through"], value["anchor"]
            if type(offset) is not int or type(through) is not int or not 0 <= offset < through <= total:
                raise ValueError
        except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
            raise ValueError("Invalid Repeat iteration cursor.") from exc
    if through:
        last, _ = load_repeat_admission(workflow, run_id, identity, through - 1, store=store)
        expected_anchor = canonical_digest(last)
        if anchor is not None and anchor != expected_anchor:
            raise ValueError("The Repeat iteration snapshot changed.")
        anchor = expected_anchor
    authorization.authorize_repeat(identity, head["initial_state_ref"])
    compiled = compile_workflow_flow(workflow)
    ancestors = [frame["loop_id"] for frame in identity["iteration_path"]] + [node["id"]]
    body_nodes = [
        node_id for node_id, enclosing in compiled["node_loop_ids"].items()
        if enclosing == ancestors and node_id in compiled["nodes"]
    ]
    items, used = [], 2
    for iteration in range(offset, min(through, offset + limit)):
        admission, _ = load_repeat_admission(workflow, run_id, identity, iteration, store=store)
        authorization.walk([("admission", identity, iteration)])
        row = store.journal_read("iteration", [execution_id, iteration])
        payload = row["payload"]
        if payload.get("after_state_ref"):
            authorization.authorize_repeat(identity, payload["after_state_ref"])
        executions = []
        for node_id in body_nodes:
            child_id = workflow_execution_id(workflow, run_id, node_id, admission["iteration_path"])
            child = store.journal_read("execution", child_id)
            if child is not None:
                authorize_execution_payload(
                    workflow, run_id, child["payload"], reader_user_id=reader_user_id, authorization=authorization,
                )
                executions.append(child_id)
        item = {
            "iteration": iteration, "iteration_path": admission["iteration_path"],
            "batch_number": admission["batch_number"], "batch_size": admission["batch_size"],
            "batch_usage": admission["batch_usage"], "state": payload["state"],
            "condition_result": payload.get("condition_result"), "execution_ids": executions,
            "before_available": True, "after_available": bool(payload.get("after_state_ref")),
            "partial": payload["state"] == "completed_partial",
        }
        size = len(json.dumps(item, ensure_ascii=True).encode("ascii")) + 1
        if used + size > 240 * 1024:
            if not items:
                raise ValueError("This round's complete inspection metadata is too large.")
            break
        items.append(item)
        used += size
    following = offset + len(items)
    next_cursor = None
    if following < through:
        next_cursor = base64.urlsafe_b64encode(json.dumps({
            "scope": scope, "offset": following, "through": through, "anchor": anchor,
        }, separators=(",", ":")).encode("ascii")).decode("ascii")
    return {
        "iterations": items, "total_count": through, "next_cursor": next_cursor,
        "repeat_execution_id": execution_id, "repeat": repeat_summary(head),
        "source_snapshot_changed": authorization.access()["source_snapshot_changed"],
    }


def workflow_repeat_state_page(workflow, run_id, execution_id, iteration, *, reader_user_id,
                               phase="before", cursor=None, limit=50):
    if phase not in {"before", "after"} or type(iteration) is not int or iteration < 0:
        raise ValueError("Select an exact Repeat round and before or after state.")
    workflow, store, node, _, identity, authorization = _repeat(workflow, run_id, execution_id, reader_user_id)
    if store.journal_read("admission", ["repeat-iteration", execution_id, iteration]) is None:
        raise LookupError("This Repeat round was not admitted.")
    admission, _ = load_repeat_admission(workflow, run_id, identity, iteration, store=store)
    payload = store.journal_read("iteration", [execution_id, iteration])["payload"]
    reference = admission["before_state_ref"] if phase == "before" else payload.get("after_state_ref")
    result = {"iteration": iteration, "phase": phase, "repeat_execution_id": execution_id}
    if reference is None:
        _page_position({"producer": identity, "iteration": iteration, "phase": phase}, cursor, limit)
        if cursor:
            raise ValueError("An uncommitted state has no page cursor.")
        authorization.authorize_repeat(identity, admission["before_state_ref"])
        return {**result, "states": [], "available": False, "total_count": 0, "next_cursor": None}
    state = authorization.authorize_repeat(identity, reference)
    scope = {"producer": identity, "iteration": iteration, "phase": phase, "state_ref": reference, "kind": "repeat_state"}
    offset = _page_position(scope, cursor, limit)
    declarations = node["state"]
    if offset > len(declarations):
        raise ValueError("The state cursor exceeds its immutable snapshot.")
    states, used = [], 2
    for declaration in declarations[offset:offset + limit]:
        slot = state["slots"][declaration["name"]]
        receipt = slot["receipt"]
        source = {
            **{name: value for name, value in receipt["producer"].items()
               if name in {"node_id", "execution_id", "task_id", "iteration_path", "attempt"}},
            "output_name": receipt["output_name"],
        }
        item = {
            "name": declaration["name"], "kind": slot["kind"], "source": source,
            "workflow_validation": slot["workflow_validation"],
            "coverage": {name: value for name, value in slot.get("coverage", {}).items()
                         if type(value) in {str, int, bool} or value is None},
            "limitations": slot.get("limitations") or [],
        }
        if slot.get("prior_coverage"):
            item["prior_coverage"] = {
                name: value for name, value in slot["prior_coverage"].items()
                if type(value) in {str, int, bool} or value is None
            }
        size = len(json.dumps(item, ensure_ascii=True).encode("ascii")) + 1
        if used + size > 240 * 1024:
            if not states:
                raise ValueError("This state's complete inspection metadata is too large.")
            break
        states.append(item)
        used += size
    return {
        **result, "states": states, "available": True, "total_count": len(declarations),
        "next_cursor": _next_cursor(scope, offset + len(states), len(declarations)),
        "partial": state["partial"], "source_snapshot_changed": authorization.access()["source_snapshot_changed"],
    }
