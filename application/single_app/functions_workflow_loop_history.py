# functions_workflow_loop_history.py
"""Authorized, bounded item, record, and contributor inspection for structured runs."""

import base64
import binascii
import json

from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_flow import compile_workflow_flow
from functions_workflow_identity import canonical_digest, workflow_execution_id, workflow_node_identity
from functions_workflow_iterations import (
    authorize_frozen_loop, load_frozen_loop, load_frozen_item_value, read_frozen_item,
)
from functions_workflow_node_results import (
    authorize_workflow_node_result_read, open_workflow_record_input, result_selectors,
)
from functions_workflow_result_store import load_workflow_node_result
from functions_workflow_results import read_result_records
from functions_workflow_runtime_store import workflow_runtime_store


def _page_position(scope, cursor, limit):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Inspection pages require a limit between 1 and 100.")
    if not cursor:
        return 0
    try:
        if not isinstance(cursor, str) or len(cursor) > 1024:
            raise ValueError
        value = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        if set(value) != {"scope", "offset"} or value["scope"] != canonical_digest(scope):
            raise ValueError
        if type(value["offset"]) is not int or value["offset"] < 0:
            raise ValueError
        return value["offset"]
    except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
        raise ValueError("Invalid workflow inspection cursor.") from exc


def _next_cursor(scope, offset, total):
    if offset >= total:
        return None
    return base64.urlsafe_b64encode(json.dumps({
        "scope": canonical_digest(scope), "offset": offset,
    }, separators=(",", ":")).encode("ascii")).decode("ascii")


def _attempt(workflow, run_id, execution_id, attempt):
    store = workflow_runtime_store(workflow, run_id)
    workflow = store.run_definition()
    if type(attempt) is not int or attempt < 1:
        raise ValueError("Invalid execution attempt.")
    row = store.journal_read("attempt", [execution_id, attempt])
    if row is None:
        raise LookupError("Execution attempt not found.")
    payload = row["payload"]
    summary = payload.get("workflow_result") or {}
    identity = workflow_node_identity(
        workflow, run_id, payload["node_id"], execution_id, attempt,
        task_id=payload.get("task_id"), iteration_path=payload.get("iteration_path") or [],
    )
    if summary.get("producer") != identity or not summary.get("result_ref"):
        raise LookupError("No result was committed for this execution attempt.")
    return workflow, identity, summary["result_ref"]


def workflow_execution_records_page(workflow, run_id, execution_id, attempt, *, reader_user_id,
                                    output="authoritative", cursor=None, limit=100):
    workflow, identity, reference = _attempt(workflow, run_id, execution_id, attempt)
    reader = open_workflow_record_input(
        workflow, run_id, identity, reference, output_name=output,
        reader_user_id=reader_user_id, inspection=True,
    )
    scope = {"producer": identity, "result_ref": reference, "output": reader.name, "kind": "records"}
    offset = _page_position(scope, cursor, limit)
    records, total = reader.record_page(offset=offset, limit=limit)
    return {
        "records": records, "record_offset": offset, "total_count": total,
        "next_cursor": _next_cursor(scope, offset + len(records), total), "output_name": reader.name,
        "workflow_validation": reader.manifest.get("workflow_validation") or {},
        "coverage": {key: value for key, value in (reader.manifest.get("coverage") or {}).items()
                     if type(value) in {str, int, bool} or value is None},
    }


def workflow_execution_provenance_page(workflow, run_id, execution_id, attempt, *, reader_user_id,
                                       cursor=None, limit=50):
    workflow, identity, reference = _attempt(workflow, run_id, execution_id, attempt)
    manifest, _ = authorize_workflow_node_result_read(
        workflow, run_id, identity, reference, reader_user_id=reader_user_id,
    )
    scope = {"producer": identity, "result_ref": reference, "kind": "contributors"}
    offset = _page_position(scope, cursor, limit)
    descriptor = manifest.get("contributors_index") or manifest.get("consumed_inputs_index")
    if descriptor:
        name = "contributors" if manifest.get("contributors_index") else "lineage"
        synthetic = {**manifest, "outputs": {name: descriptor}}
        loader = lambda ref: load_workflow_node_result(
            workflow, run_id, identity.get("task_id"), ref, **result_selectors(identity),
        )
        values, total = read_result_records(synthetic, name, loader, offset=offset, limit=limit)
    else:
        values = manifest.get("consumed_inputs") or []
        total = len(values)
        if offset > total:
            raise ValueError("The contributor cursor exceeds the result.")
        values = values[offset:offset + limit]
    allowed = {
        "producer", "input_name", "output_name", "result_ref", "output_ref", "analysis_result", "control",
        "item_id", "item_index", "record_offset", "record_count", "producer_record_offset",
    }
    contributors = [{key: value for key, value in receipt.items() if key in allowed} for receipt in values]
    return {
        "contributors": contributors, "total_count": total,
        "next_cursor": _next_cursor(scope, offset + len(values), total),
    }


def workflow_loop_items_page(workflow, run_id, execution_id, *, reader_user_id, cursor=None, limit=50):
    store = workflow_runtime_store(workflow, run_id)
    workflow = store.run_definition()
    row = store.journal_read("loop", execution_id)
    if row is None:
        raise LookupError("Frozen loop inputs not found.")
    identity = row["payload"]["identity"]
    manifest, reference, state = load_frozen_loop(workflow, run_id, identity, store=store)
    authorize_frozen_loop(
        workflow, run_id, {"producer": identity, "manifest_ref": reference},
        reader_user_id=reader_user_id, store=store,
    )
    scope = {"producer": identity, "manifest_ref": reference, "kind": "items"}
    offset = _page_position(scope, cursor, limit)
    if offset > manifest["count"]:
        raise ValueError("The item cursor exceeds the frozen collection.")
    compiled = compile_workflow_flow(workflow)
    ancestors = [frame["loop_id"] for frame in identity["iteration_path"]] + [identity["node_id"]]
    nodes = [
        node_id for node_id, loop_ids in compiled.get("node_loop_ids", {}).items()
        if loop_ids == ancestors and node_id in compiled["nodes"]
    ]
    items = []
    for index in range(offset, min(manifest["count"], offset + limit)):
        item = read_frozen_item(workflow, run_id, manifest, index)
        current = load_frozen_item_value(workflow, run_id, manifest, item, reader_user_id=reader_user_id)
        outcome = store.journal_read("iteration", [execution_id, item["item_id"]])
        payload = (outcome or {}).get("payload") or {}
        path = identity["iteration_path"] + [{
            "loop_id": identity["node_id"], "item_id": item["item_id"], "index": index,
        }]
        executions = []
        for node_id in nodes:
            child_id = workflow_execution_id(workflow, run_id, node_id, path)
            if store.journal_read("execution", child_id) is not None:
                executions.append(child_id)
        projected = {
            "item_id": item["item_id"], "index": index, "iteration_path": path,
            "label": str(current["value"].get("file_name") or f"Item {index + 1}")[:256]
            if item["kind"] == "document" else f"Item {index + 1}",
            "state": payload.get("state", "queued"), "execution_ids": executions,
        }
        if len(json.dumps(items + [projected], ensure_ascii=True).encode("ascii")) > 240 * 1024:
            if not items:
                raise ValueError("This item's inspection metadata is too large.")
            break
        items.append(projected)
    return {
        "items": items, "total_count": manifest["count"],
        "next_cursor": _next_cursor(scope, offset + len(items), manifest["count"]),
        "loop_execution_id": execution_id, "limit": state["max_items"], "frozen_at": manifest["frozen_at"],
        "selection": {
            key: value for key, value in (manifest.get("capture") or {}).items()
            if key in {
                "query_mode", "exhaustive", "ranking", "candidate_limitations", "candidate_window",
                "semantic_rerank_window", "candidate_expansion", "candidate_expansion_rounds",
            }
        },
    }
