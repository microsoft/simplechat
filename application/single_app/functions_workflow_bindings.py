# functions_workflow_bindings.py
"""Resolve named workflow inputs through authorized output/document loaders."""

import hashlib
import json
from collections.abc import Mapping

from functions_workflow_definitions import WorkflowDefinitionError, normalize_workflow_references, workflow_output_kind_matches
from functions_analysis_access import build_analysis_access


class WorkflowInputError(WorkflowDefinitionError):
    """A required workflow input is unavailable or does not match its contract."""


def attach_workflow_reference_sources(result, sources):
    """Merge already-authorized reference contributors with existing producer lineage."""
    contributors = list(sources)
    for result_part in (
        result, result.get("analysis_result") or {}, result.get("comparison_result") or {},
    ):
        for source in result_part.get("mixed_source_manifest") or []:
            if source.get("authorization_status") == "authorized":
                contributors.append(source)
    if not contributors:
        return result
    prepared = dict(result)
    inherited = []
    if "analysis_access" in result:
        inherited.append(result["analysis_access"])
    for name in ("analysis_result", "comparison_result"):
        analysis = result.get(name)
        if isinstance(analysis, dict) and "analysis_access" in analysis:
            inherited.append(analysis["analysis_access"])
    access = build_analysis_access(contributors, inherited=inherited)
    prepared["analysis_access"] = access
    for name in ("analysis_result", "comparison_result"):
        analysis = result.get(name)
        if isinstance(analysis, dict) and "analysis_access" in analysis:
            prepared[name] = {**analysis, "analysis_access": access}
    return prepared

def _source_helpers():
    # Search service initializes application dependencies; resolve it only at
    # an authorized input operation, keeping definition tests import-safe.
    from functions_search_service import get_document_chunks_payload, resolve_document_context

    return resolve_document_context, get_document_chunks_payload


def _reference_arguments(workflow, reference, actor_user_id):
    normalized = normalize_workflow_references(
        [reference], user_id=workflow["user_id"], group_id=workflow.get("group_id") or "",
    )[0]
    return normalized, {
        "document_id": normalized["document_id"],
        "user_id": str(actor_user_id or workflow["user_id"]),
        "doc_scope": normalized["scope_type"],
        "active_group_ids": [normalized["scope_id"]] if normalized["scope_type"] == "group" else [],
        "active_public_workspace_id": [normalized["scope_id"]] if normalized["scope_type"] == "public" else [],
    }


def authorize_workflow_reference(workflow, reference, *, actor_user_id=None, resolve_document=None):
    """Prove the exact document belongs to the requested, authorized source scope."""
    normalized, arguments = _reference_arguments(workflow, reference, actor_user_id)
    resolver = resolve_document if resolve_document is not None else _source_helpers()[0]
    context = resolver(**arguments, include_content=False)
    if not isinstance(context, Mapping) or context.get("scope") != normalized["scope_type"]:
        raise WorkflowInputError("A shared reference is not available in the selected source scope.")
    document = context.get("document") or {}
    actual_scope = {
        "personal": document.get("user_id"),
        "group": context.get("group_id") or document.get("group_id"),
        "public": context.get("public_workspace_id") or document.get("public_workspace_id"),
    }[normalized["scope_type"]]
    if str(actual_scope or "") != normalized["scope_id"]:
        raise WorkflowInputError("A shared reference does not match its authorized workspace.")
    if str(document.get("id") or document.get("document_id") or "") != normalized["document_id"]:
        raise WorkflowInputError("A shared reference does not match the requested document.")
    return context


def load_workflow_reference(workflow, reference, *, actor_user_id=None, snapshot=None,
                            resolve_document=None, load_chunks=None):
    """Return full indexed reference text, rechecking access and source identity."""
    context = authorize_workflow_reference(
        workflow, reference, actor_user_id=actor_user_id, resolve_document=resolve_document,
    )
    normalized, arguments = _reference_arguments(workflow, reference, actor_user_id)
    document = context["document"]
    source_version = document.get("_etag") or document.get("source_version") or document.get("version")
    if snapshot is not None and source_version:
        prior = snapshot.get("source", {})
        if all((
            prior.get("source_version") == str(source_version),
            prior.get("document_id") == normalized["document_id"],
            prior.get("scope_type") == normalized["scope_type"],
            prior.get("scope_id") == normalized["scope_id"],
        )):
            return snapshot
    reader = load_chunks if load_chunks is not None else _source_helpers()[1]
    payload = reader(**arguments)
    chunks = payload.get("chunks") or []
    if (
        payload.get("scope") != normalized["scope_type"]
        or str(payload.get("scope_id") or "") != normalized["scope_id"]
        or not chunks
        or payload.get("returned_chunk_count") != payload.get("chunk_count")
        or len(chunks) != payload.get("chunk_count")
    ):
        raise WorkflowInputError("The complete shared reference is not available for this run.")
    text_parts = []
    for chunk in chunks:
        text = chunk.get("chunk_text")
        if not isinstance(text, str):
            raise WorkflowInputError("A shared reference contains unreadable indexed content.")
        text_parts.append(text)
    text = "\n\n".join(text_parts)
    if not text.strip():
        raise WorkflowInputError("A shared reference has no readable indexed text.")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    source = {
        "document_id": normalized["document_id"],
        "scope_type": normalized["scope_type"],
        "scope_id": normalized["scope_id"],
        "source_version": str(source_version) if source_version is not None else digest,
        "content_sha256": digest,
    }
    if snapshot is not None and snapshot.get("source") != source:
        raise WorkflowInputError("A shared reference changed during this run. Start a new run to use the updated source.")
    return {"reference_id": normalized["id"], "name": normalized["name"], "source": source, "text": text}


def resolve_workflow_task_inputs(workflow, task, completed_results, *, previous_task_id=None,
                                 load_output, load_reference=None, reference_cache=None):
    """Bind exact predecessor outputs; loaders retain all object/lineage authorization."""
    bindings = task.get("inputs")
    if bindings is None:
        bindings = [{
            "name": "previous", "task_id": previous_task_id, "output": "authoritative",
            "required": True, "expected_kind": "any",
        }] if previous_task_id else []
    inputs = []
    consumed_inputs = []
    for binding in bindings:
        producer = completed_results.get(binding["task_id"])
        if producer is None:
            if binding.get("required", True):
                raise WorkflowInputError("A required input's producer did not complete successfully in this run.")
            inputs.append({"name": binding["name"], "status": "unavailable"})
            continue
        validation = producer.get("workflow_validation") or {}
        if validation.get("eligible") is False:
            raise WorkflowInputError("A task input did not satisfy its producer's output requirements.")
        selector = binding.get("output", "authoritative")
        if selector != "authoritative" and "outputs" in producer and selector not in producer["outputs"]:
            if binding.get("required", True):
                raise WorkflowInputError("A required named task output was not produced.")
            inputs.append({"name": binding["name"], "status": "unavailable"})
            continue
        read_options = {"output_name": selector}
        if validation.get("status") == "accepted_partial":
            read_options["allow_partial"] = True
        prompt, receipt = load_output(
            workflow, producer["run_id"], binding["task_id"], producer["result_ref"],
            **read_options,
        )
        payload = json.loads(prompt)
        expected = binding.get("expected_kind", "any")
        if not workflow_output_kind_matches(payload.get("kind"), expected):
            raise WorkflowInputError("A task input does not match the required output kind.")
        inputs.append({"name": binding["name"], "status": "available", "result": payload})
        consumed_inputs.append({**receipt, "input_name": binding["name"]})

    references = workflow.get("reference_inputs") or []
    selected_ids = task.get("reference_ids")
    if selected_ids is not None:
        selected_ids = set(selected_ids)
        if selected_ids - {reference["id"] for reference in references}:
            raise WorkflowInputError("A selected shared reference is missing from this workflow.")
        references = [reference for reference in references if reference["id"] in selected_ids]
    reference_data = []
    cache = reference_cache if reference_cache is not None else {}
    for reference in references:
        if load_reference is None:
            raise WorkflowInputError("Shared reference loading is not available for this run.")
        # Call even for cached snapshots: source authorization is not cached.
        snapshot = load_reference(reference, snapshot=cache.get(reference["id"]))
        cache[reference["id"]] = snapshot
        reference_data.append(snapshot)
    return {
        "task_context": json.dumps({"inputs": inputs}, ensure_ascii=False, sort_keys=True) if inputs else "",
        "reference_context": json.dumps({"shared_references": reference_data}, ensure_ascii=False, sort_keys=True) if reference_data else "",
        "consumed_inputs": consumed_inputs,
        "reference_sources": [dict(reference["source"]) for reference in reference_data],
    }
