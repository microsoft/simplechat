# functions_workflow_readiness.py
"""Resume submitted native outputs through the shared authoritative reader."""

from copy import deepcopy

from functions_analysis_access import authorize_analysis_sources
from functions_native_analysis_results import adapt_native_analysis_result


class WorkflowOutputUnavailable(ValueError):
    """A child cannot supply the required final representation without new work."""


def pending_workflow_output_references(result):
    analysis = result.get("analysis_result") or result.get("comparison_result") or {}
    outputs = (
        list(result.get("generated_tabular_outputs") or analysis.get("generated_tabular_outputs") or [])
        + list(analysis.get("native_result_references") or result.get("native_result_references") or [])
    )
    references = {}
    for output in outputs:
        run_id = output.get("export_run_id") or output.get("run_id")
        if run_id:
            references[str(run_id)] = {"kind": "tabular", "run_id": str(run_id)}
    return list(references.values())


def _child_status(workflow, reference):
    # The native engine owns its lifecycle; polling does not resume or resubmit it.
    from functions_tabular_generated_exports import get_tabular_generated_output_run_status

    if reference.get("kind") != "tabular":
        raise WorkflowOutputUnavailable("This background output needs its producer's final-result adapter.")
    status = get_tabular_generated_output_run_status(workflow["user_id"], reference["run_id"])
    if not status or status.get("run_id") != reference["run_id"]:
        raise WorkflowOutputUnavailable("The required background run is unavailable.")
    return status


def workflow_outputs_ready(workflow, references, *, get_status=None):
    if not references:
        return False
    read = get_status or _child_status
    return all(
        read(workflow, reference).get("status") in {"completed", "failed", "cancelled", "canceled"}
        for reference in references
    )


def reconcile_workflow_pending_output(workflow, result, *, conversation_id, actor_user_id,
                                     run_id=None, get_status=None, native_adapter=None, source_resolver=None):
    references = pending_workflow_output_references(result)
    if not references:
        raise WorkflowOutputUnavailable("The producer has not supplied a resumable background-result reference.")
    statuses = [(reference, (get_status or _child_status)(workflow, reference)) for reference in references]
    if any(status.get("status") not in {"completed", "failed", "cancelled", "canceled"} for _, status in statuses):
        return None
    if any(status.get("status") != "completed" for _, status in statuses):
        raise WorkflowOutputUnavailable("A required background output failed or was cancelled.")
    analysis = result.get("analysis_result") or {}
    deferred = result.get("deferred_composition") or analysis.get("deferred_composition") or {}
    sources = analysis.get("analysis_sources") or analysis.get("mixed_source_manifest") or []
    if len(statuses) != 1 or len(sources) != 1 or deferred:
        raise WorkflowOutputUnavailable(
            "These outputs require their producer's final composition. "
            "They were not replaced with summaries or diagnostic Markdown."
        )
    status = statuses[0][1]
    if status.get("conversation_id") != conversation_id:
        raise PermissionError("The background output belongs to another workflow conversation.")
    source = sources[0]
    authorize_analysis_sources(actor_user_id, [source], require_snapshot=True, resolver=source_resolver)
    producer = workflow.get("_analysis_producer")
    if producer and (
        producer.get("kind") != "workflow" or producer.get("workflow_id") != workflow["id"]
        or producer.get("run_id") != run_id or not producer.get("task_id")
    ):
        raise WorkflowOutputUnavailable("The background output does not match this task's producer identity.")
    try:
        finalized = (native_adapter or adapt_native_analysis_result)(
            user_id=workflow["user_id"], conversation_id=conversation_id, source=source,
            generated_outputs=references, source_resolver=source_resolver, analysis_producer=producer,
            analysis_options=(analysis.get("analysis_request") or {}).get("analysis_options"),
        )
    except ValueError as exc:
        raise WorkflowOutputUnavailable("The native producer has not exposed a valid complete final output.") from exc
    if finalized.get("execution_status") == "pending":
        return None
    if finalized.get("execution_status") not in {"succeeded", "incomplete"}:
        raise WorkflowOutputUnavailable("The native producer could not finalize the saved output.")
    refreshed = deepcopy(result)
    refreshed.update(
        reply=finalized["reply"], analysis_result=finalized,
        authoritative_result=finalized["authoritative_result"],
        generated_tabular_outputs=finalized.get("generated_tabular_outputs") or [],
        analysis_coverage=finalized.get("coverage") or {},
        execution_status=finalized["execution_status"],
    )
    return refreshed
