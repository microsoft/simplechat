# functions_workflow_execution_history.py
"""Authorized safe projections of the schema-2 execution journal."""

from functions_analysis_access import authorize_analysis_sources, build_analysis_access
from functions_workflow_identity import workflow_node_identity
from functions_workflow_limits import WORKFLOW_MAX_EXECUTION_ADMISSIONS
from functions_workflow_node_results import (
    WorkflowLineageAuthorization, authorize_workflow_node_result_read, load_node_result, result_selectors,
)
from functions_workflow_result_store import read_workflow_node_result_page
from functions_workflow_runtime_store import workflow_runtime_store


def authorize_execution_payload(workflow, run_id, payload, *, reader_user_id, authorization=None):
    authorization = authorization or WorkflowLineageAuthorization(
        workflow, run_id, reader_user_id=reader_user_id, store=workflow_runtime_store(workflow, run_id),
    )
    if payload.get("iteration_path"):
        authorization.walk([("path", payload, payload.get("iteration_inputs") or [])])
    if payload.get("node_kind") == "for_each":
        store = authorization.store
        loop = store.journal_read("loop", payload["execution_id"])
        if loop:
            authorization.walk([("frozen", {
                "producer": loop["payload"]["identity"], "manifest_ref": loop["payload"]["manifest_ref"],
            })])
    if payload.get("node_kind") == "repeat_until" or payload.get("decision_kind") == "repeat_transition" or payload.get("repeat"):
        loop = authorization.store.journal_read("loop", payload["execution_id"])
        if loop:
            head = loop["payload"]
            reference = payload.get("after_state_ref") or head["current_state_ref"]
            authorization.authorize_repeat(head["identity"], reference)
    references = payload.get("reference_sources") or []
    if references:
        policy = build_analysis_access(references)
        authorize_analysis_sources(reader_user_id, policy["sources"])
    summary = payload.get("workflow_result") or {}
    if summary.get("result_ref"):
        authorization.authorize_result(summary["producer"], summary["result_ref"])
    authorization.walk(("receipt", receipt) for receipt in payload.get("consumed_inputs") or [])


def workflow_execution_history(workflow, run_id, *, reader_user_id, kind="execution", execution_id=None,
                               cursor=None, limit=50, authorization=None):
    store = workflow_runtime_store(workflow, run_id)
    if store.read().get("schema_version") != 2:
        raise ValueError("Execution history is available only for structured workflow runs.")
    workflow = store.run_definition()
    authorization = authorization or WorkflowLineageAuthorization(workflow, run_id, reader_user_id=reader_user_id, store=store)
    if execution_id:
        execution = store.journal_read("execution", execution_id)
        if execution is None:
            raise LookupError("Execution not found.")
    page = store.journal_page(kind, execution_id=execution_id, cursor=cursor, limit=limit)
    # Read the bound internal records too: safe decision projections intentionally omit source references.
    for item in page["items"]:
        if kind == "decision":
            key = (
                ["repeat-transition", item["execution_id"], item["iteration"]] if item.get("decision_kind") == "repeat_transition"
                else ["gate", item["gate_id"]] if item.get("gate_id") else ["control", item["execution_id"]]
            )
            row = store.journal_read("decision", key)
            payload = row["payload"]
        else:
            key = item["execution_id"] if kind == "execution" else [item["execution_id"], item["attempt"]]
            row = store.journal_read(kind, key)
            if row is None:
                raise LookupError("The execution journal changed while it was being read.")
            payload = row["payload"]
        authorize_execution_payload(workflow, run_id, payload, reader_user_id=reader_user_id, authorization=authorization)
    name = {"execution": "executions", "attempt": "attempts", "decision": "decisions"}[kind]
    result = {name: page["items"], "next_cursor": page["next_cursor"]}
    if kind == "execution":
        result["total_count"] = page["total_count"]
    return result


def workflow_execution_result_page(workflow, run_id, execution_id, attempt, *, reader_user_id,
                                   output="authoritative", offset=0, limit=2000):
    store = workflow_runtime_store(workflow, run_id)
    workflow = store.run_definition()
    record = store.journal_read("attempt", [execution_id, attempt])
    if record is None:
        raise LookupError("Execution attempt not found.")
    payload = record["payload"]
    summary = payload.get("workflow_result") or {}
    identity = summary.get("producer") or {}
    expected = workflow_node_identity(
        workflow, run_id, payload["node_id"], execution_id, attempt,
        task_id=payload.get("task_id"), iteration_path=payload.get("iteration_path") or [],
    )
    if identity != expected or not summary.get("result_ref"):
        raise ValueError("This exact attempt has no saved result.")
    manifest, _ = authorize_workflow_node_result_read(
        workflow, run_id, identity, summary["result_ref"], reader_user_id=reader_user_id,
    )
    name = manifest.get("authoritative_output") if output == "authoritative" else output
    reference = summary["result_ref"] if name == "manifest" else (manifest.get("outputs", {}).get(name) or {}).get("result_ref")
    if not reference:
        raise LookupError("The selected output was not produced.")
    descriptor = (manifest.get("outputs") or {}).get(name) or {}
    for _ in range(WORKFLOW_MAX_EXECUTION_ADMISSIONS):
        selected = descriptor.get("selected_producer")
        if not selected or name == "manifest":
            break
        identity = selected["producer"]
        manifest = load_node_result(workflow, run_id, identity, selected["result_ref"])
        descriptor = (manifest.get("outputs") or {}).get(selected["output_name"]) or {}
        if descriptor.get("result_ref") != selected["output_ref"]:
            raise ValueError("The selected producer output changed.")
        reference = descriptor["result_ref"]
    else:
        raise ValueError("The selected producer lineage is invalid.")
    return {
        **read_workflow_node_result_page(
            workflow, run_id, identity.get("task_id"), reference, **result_selectors(identity), offset=offset, limit=limit,
        ), "output_name": name,
    }
