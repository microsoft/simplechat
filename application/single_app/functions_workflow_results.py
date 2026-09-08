# functions_workflow_results.py
"""Versioned workflow task outputs, distinct from chat presentation."""

import json
import re
from collections.abc import Mapping

from functions_workflow_result_store import load_workflow_task_result, save_workflow_task_result


WORKFLOW_RESULT_CONTRACT_VERSION = "workflow-result-v1"
PENDING_OUTPUT_STATES = frozenset({
    "pending", "queued", "running", "retrying", "finalizing", "processing",
    "gate_disabled", "continuation_unavailable",
})


class WorkflowResultNotReadyError(ValueError):
    """A downstream task cannot consume an unfinished output as final data."""


def _json_copy(value):
    return json.loads(json.dumps(value, ensure_ascii=True, allow_nan=False))


def _structured_output(text):
    fenced = re.fullmatch(r"\s*```(?:json)?\s*\n(.*?)\n```\s*", text, flags=re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, (dict, list)) else None


def get_workflow_analysis_result(result):
    """Find retained analysis data before considering its presentation reply."""
    for field in ("analysis_result", "comparison_result"):
        value = result.get(field)
        if isinstance(value, Mapping):
            return value
    return {}


def get_workflow_result_text(result):
    analysis = get_workflow_analysis_result(result)
    for value in (
        analysis.get("analysis_reply"),
        analysis.get("reply"),
        result.get("analysis_reply"),
        result.get("reply"),
    ):
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _execution_state(result, analysis, artifacts):
    deferred = result.get("deferred_composition") or analysis.get("deferred_composition") or {}
    if isinstance(deferred, Mapping) and deferred.get("status") in PENDING_OUTPUT_STATES:
        return "pending"
    coverage = result.get("analysis_coverage") or analysis.get("coverage") or {}
    state = str((coverage.get("progress_meta") or {}).get("status") or "").lower()
    if state in PENDING_OUTPUT_STATES:
        return "pending"
    if state in {"failed", "cancelled", "canceled"}:
        return state
    if state == "partial":
        return "incomplete"
    for artifact in artifacts:
        status = str(artifact.get("status") or artifact.get("run_status") or "").lower()
        if status in PENDING_OUTPUT_STATES:
            return "pending"
        if not status and artifact.get("background_export"):
            return "pending"
        if status in {"failed", "cancelled", "canceled"}:
            return status
    return "succeeded"


def _final_output(text, declared=None):
    if declared is not None:
        if not isinstance(declared, Mapping) or declared.get("kind") not in {"text", "records", "json"}:
            raise ValueError("The task's authoritative output is invalid.")
        kind, value = declared["kind"], declared.get("value")
        if kind == "text" and not isinstance(value, str):
            raise ValueError("The authoritative text output is invalid.")
        if kind == "records" and (
            not isinstance(value, list) or not all(isinstance(row, dict) for row in value)
        ):
            raise ValueError("The authoritative record output is invalid.")
        if kind == "json" and not isinstance(value, (dict, list)):
            raise ValueError("The authoritative JSON output is invalid.")
        return kind, _json_copy(value)
    value = _structured_output(text)
    if value is None:
        return "text", text
    kind = "records" if isinstance(value, list) and all(isinstance(row, dict) for row in value) else "json"
    return kind, value


def _provenance_references(values):
    fields = {
        "id", "document_id", "document_name", "file_name", "scope", "scope_type", "scope_id",
        "group_id", "public_workspace_id", "version", "source_version", "etag", "_etag",
        "citation_id", "plugin_name", "function_name", "page_number", "chunk_id",
    }
    return [
        {key: value for key, value in item.items() if key in fields}
        for item in values if isinstance(item, Mapping)
    ]


def build_workflow_task_result(result, *, workflow, run_id, task, attempt_count=1):
    """Capture complete produced data without changing the existing chat reply."""
    if not isinstance(result, Mapping):
        raise ValueError("Workflow execution did not return a task result.")
    analysis = get_workflow_analysis_result(result)
    text = get_workflow_result_text(result)
    outputs = {"text": {"kind": "text", "value": text}}
    declared = result["authoritative_result"] if "authoritative_result" in result else analysis.get("authoritative_result")
    kind, value = _final_output(text, declared)
    outputs[kind] = {"kind": kind, "value": value}
    authoritative_output = kind
    if analysis.get("per_document"):
        documents = []
        for document in analysis.get("document_results") or []:
            final = document.get("full_result")
            if not isinstance(final, Mapping):
                raise ValueError("A per-document task is missing its authoritative source result.")
            item_kind, item_value = _final_output(
                str(final.get("text") or ""), final.get("authoritative_result"),
            )
            documents.append({
                "document_id": document.get("document_id"),
                "kind": item_kind,
                "value": item_value,
            })
        outputs["documents"] = {"kind": "document_results", "value": documents}
        authoritative_output = "documents"

    artifacts = [
        _json_copy(artifact)
        for field in ("generated_analysis_artifacts", "generated_tabular_outputs")
        for artifact in result.get(field) or []
        if isinstance(artifact, Mapping)
    ]
    coverage = result.get("analysis_coverage") or analysis.get("coverage") or result.get("coverage") or {}
    validation = result.get("validation") or analysis.get("validation") or {"status": "not_requested"}
    if not isinstance(coverage, Mapping) or not isinstance(validation, Mapping):
        raise ValueError("The task's coverage or validation metadata is invalid.")
    presentation = str(result.get("reply") or "")
    envelope = {
        "contract_version": WORKFLOW_RESULT_CONTRACT_VERSION,
        "identity": {
            "workflow_id": str(workflow.get("id") or ""),
            "run_id": str(run_id),
            "task_id": str(task.get("id") or ""),
            "attempt": int(attempt_count),
        },
        "execution": {
            "status": _execution_state(result, analysis, artifacts),
            "deferred_composition": _json_copy(
                result.get("deferred_composition") or analysis.get("deferred_composition") or {}
            ),
        },
        "summary": presentation[:4000],
        "authoritative_output": authoritative_output,
        "outputs": outputs,
        "presentation": {
            "summary": presentation[:4000],
            "preview_truncated": len(presentation) > 4000,
            "artifacts": artifacts,
        },
        "diagnostics": {
            "analysis": {key: _json_copy(value) for key, value in analysis.items()
                         if key not in {"analysis_reply", "reply", "authoritative_result"}},
        },
        "artifacts": [
            {key: value for key, value in artifact.items() if key in {
                "artifact_message_id", "conversation_id", "file_name", "output_format",
                "capability", "run_id", "export_run_id", "row_count", "status",
            }}
            for artifact in artifacts
        ],
        "coverage": _json_copy(coverage),
        "validation": _json_copy(validation),
        "provenance": {
            "sources": _provenance_references(
                result.get("mixed_source_manifest") or analysis.get("mixed_source_manifest")
                or analysis.get("documents") or []
            ),
            "citations": {
                field: _provenance_references(result.get(field) or [])
                for field in ("agent_citations", "hybrid_citations", "web_search_citations")
            },
        },
    }
    # Reject unsupported SDK objects/NaN before any output is marked durable.
    return _json_copy(envelope)


def _require_completed_result(envelope):
    if envelope.get("contract_version") != WORKFLOW_RESULT_CONTRACT_VERSION:
        raise ValueError("This workflow task result version is not supported.")
    state = (envelope.get("execution") or {}).get("status")
    if state != "succeeded":
        raise WorkflowResultNotReadyError(
            "The previous task has no completed authoritative output. Its result and diagnostics "
            "are retained; a preview or unfinished output cannot replace the required input."
        )


def persist_workflow_task_result(envelope, *, workflow, run_id, task_id, settings=None,
                                 save_result=save_workflow_task_result):
    """Commit independently readable sections, then their small result manifest."""
    manifest = {key: _json_copy(value) for key, value in envelope.items()
                if key not in {"outputs", "presentation", "diagnostics"}}
    sections = dict(envelope["outputs"])
    sections["presentation"] = {"kind": "presentation", "value": envelope["presentation"]}
    sections["diagnostics"] = {"kind": "diagnostics", "value": envelope["diagnostics"]}
    manifest["outputs"] = {}
    for name, output in sections.items():
        section = {
            "contract_version": WORKFLOW_RESULT_CONTRACT_VERSION,
            "producer": envelope["identity"],
            "output_name": name,
            "kind": output["kind"],
            "value": output["value"],
        }
        reference = save_result(workflow, run_id, task_id, section, settings=settings)
        manifest["outputs"][name] = {"kind": output["kind"], "result_ref": reference}
    reference = save_result(workflow, run_id, task_id, manifest, settings=settings)
    return manifest, reference


def load_workflow_task_input(workflow, run_id, task_id, reference,
                             *, load_result=load_workflow_task_result):
    """Read only the producer-selected final output, with immutable consumption identity."""
    manifest = load_result(workflow, run_id, task_id, reference)
    _require_completed_result(manifest)
    identity = manifest.get("identity") or {}
    if (
        identity.get("workflow_id") != str(workflow.get("id") or "")
        or identity.get("run_id") != str(run_id)
        or identity.get("task_id") != str(task_id)
    ):
        raise ValueError("The saved result does not match the requested producer.")
    name = manifest.get("authoritative_output")
    if name in {"presentation", "diagnostics"} or name not in (manifest.get("outputs") or {}):
        raise ValueError("The saved task has no authoritative output binding.")
    output_ref = manifest["outputs"][name]["result_ref"]
    output = load_result(workflow, run_id, task_id, output_ref)
    if (
        output.get("contract_version") != WORKFLOW_RESULT_CONTRACT_VERSION
        or output.get("producer") != manifest.get("identity")
        or output.get("output_name") != name
        or output.get("kind") != manifest["outputs"][name].get("kind")
    ):
        raise ValueError("The saved output does not match its producer's manifest.")
    consumed = {
        "producer": manifest["identity"],
        "output_name": name,
        "result_ref": dict(reference),
        "output_ref": dict(output_ref),
    }
    prompt = json.dumps({
        "consumed_result": consumed,
        "provenance": manifest.get("provenance") or {},
        "kind": output["kind"],
        "value": output["value"],
    }, ensure_ascii=False, allow_nan=False)
    return prompt, consumed


def workflow_result_summary(envelope, reference):
    """Small, non-secret history projection; full outputs stay in the result store."""
    return {
        "contract_version": envelope["contract_version"],
        "result_ref": dict(reference),
        "output_kinds": list(envelope.get("outputs") or {}),
        "authoritative_output": envelope.get("authoritative_output"),
        "outputs": _json_copy(envelope.get("outputs") or {}),
        "output_state": (envelope.get("execution") or {}).get("status"),
        "validation_status": (envelope.get("validation") or {}).get("status", "not_requested"),
        "consumed_inputs": _json_copy(envelope.get("consumed_inputs") or []),
    }
