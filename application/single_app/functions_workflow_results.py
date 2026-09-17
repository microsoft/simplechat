# functions_workflow_results.py
"""Versioned workflow task outputs, distinct from chat presentation."""

import json
import re
from collections.abc import Mapping

from functions_analysis_access import (
    AnalysisResultUnavailable,
    analysis_source_snapshot,
    authorize_analysis_sources,
)
from functions_workflow_result_store import (
    DEFAULT_MAX_RESULT_SIZE_MB,
    _quota_bytes,
    load_workflow_task_result,
    load_workflow_node_result,
    save_workflow_node_result,
    save_workflow_task_result,
)


WORKFLOW_RESULT_CONTRACT_VERSION = "workflow-result-v1"
ANALYSIS_SOURCE_ACCESS_VERSION = "analysis-source-access-v1"
ANALYSIS_RECORD_PAGE_BYTES = 128 * 1024
ANALYSIS_RECORD_PAGE_SIZE = 100
ANALYSIS_MATERIALIZATION_BYTES = 8 * 1024 * 1024
PENDING_OUTPUT_STATES = frozenset({
    "pending", "queued", "running", "retrying", "finalizing", "processing",
    "gate_disabled", "continuation_unavailable",
})
PUBLIC_ANALYSIS_VALIDATION_STATES = frozenset({"valid", "partial", "invalid", "pending", "not_validated"})


class WorkflowResultNotReadyError(ValueError):
    """A downstream task cannot consume an unfinished output as final data."""


def public_analysis_validation(validation):
    """Project legacy or unknown statuses without claiming an unperformed check."""
    public = _json_copy(validation) if isinstance(validation, Mapping) else {}

    def without_superseded_values(value):
        if isinstance(value, dict):
            return {
                key: without_superseded_values(item)
                for key, item in value.items() if key != "reported_value"
            }
        if isinstance(value, list):
            return [without_superseded_values(item) for item in value]
        return value

    public = without_superseded_values(public)
    status = public.get("status")
    public["status"] = status if isinstance(status, str) and status in PUBLIC_ANALYSIS_VALIDATION_STATES else "not_validated"
    return public


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
    explicit = result.get("execution_status") or analysis.get("execution_status")
    if explicit in {"pending", "incomplete", "failed", "cancelled", "canceled", "blocked", "unsupported", "skipped"}:
        return explicit
    deferred = result.get("deferred_composition") or analysis.get("deferred_composition") or {}
    if isinstance(deferred, Mapping) and deferred.get("status") in PENDING_OUTPUT_STATES:
        return "pending"
    coverage = result.get("analysis_coverage") or analysis.get("coverage") or {}
    state = str((coverage.get("progress_meta") or {}).get("status") or "").lower()
    if (
        analysis.get("analysis_result_version") == "analyze-final-v1"
        and (coverage.get("progress_meta") or {}).get("phase") == "ready_to_save"
    ):
        validation_state = (analysis.get("analysis_validation") or {}).get("status")
        state = {"valid": "completed", "partial": "partial", "invalid": "failed", "pending": "pending"}.get(
            validation_state, state,
        )
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
        "group_id", "public_workspace_id", "version", "source_version", "source_revision", "etag", "_etag",
        "citation_id", "plugin_name", "function_name", "page_number", "chunk_id",
    }
    return [
        {key: value for key, value in item.items() if key in fields}
        for item in values if isinstance(item, Mapping)
    ]


def build_workflow_task_result(result, *, workflow, run_id, task, attempt_count=1):
    """Capture complete produced data without changing the existing chat reply."""
    if workflow.get("definition_version") == 3:
        from functions_workflow_execution import current_workflow_execution
        from functions_workflow_identity import workflow_node_identity

        execution = current_workflow_execution()
        if execution is None or execution.node.get("task_id") != task.get("id"):
            raise ValueError("A v3 task result requires its admitted execution.")
        selectors = execution.selectors(attempt=attempt_count)
        return _build_task_result(result, workflow_node_identity(
            workflow, run_id, selectors["node_id"], selectors["execution_id"], attempt_count,
            task_id=task["id"], iteration_path=[],
        ), "workflow-result-v2")
    return _build_task_result(
        result,
        {
            "workflow_id": str(workflow.get("id") or ""),
            "run_id": str(run_id),
            "task_id": str(task.get("id") or ""),
            "attempt": int(attempt_count),
        },
        WORKFLOW_RESULT_CONTRACT_VERSION,
    )


def build_chat_analysis_result(result, *, user_id, conversation_id, message_id):
    """Use the same result sections with a genuine chat producer identity."""
    if not all(isinstance(value, str) and value.strip() for value in (user_id, conversation_id, message_id)):
        raise ValueError("An analysis result requires a user, conversation, and message identity.")
    envelope = _build_task_result(
        result,
        {
            "kind": "chat",
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
        },
        "analyze-final-v1",
    )
    if not envelope.get("analysis_access"):
        raise AnalysisResultUnavailable("analysis_source_manifest_missing")
    return envelope


def build_orchestration_analysis_result(result, *, user_id, conversation_id, run_id, step_id):
    """Bind an Analyze result to the real orchestration step that produced it."""
    if not all(isinstance(value, str) and value.strip() for value in (user_id, conversation_id, run_id, step_id)):
        raise ValueError("An analysis result requires a complete orchestration identity.")
    envelope = _build_task_result(
        result,
        {
            "kind": "orchestration", "user_id": user_id, "conversation_id": conversation_id,
            "run_id": run_id, "step_id": step_id,
        },
        "analyze-final-v1",
    )
    if not envelope.get("analysis_access"):
        raise AnalysisResultUnavailable("analysis_source_manifest_missing")
    return envelope


def _build_task_result(result, identity, contract_version):
    if not isinstance(result, Mapping):
        raise ValueError("Workflow execution did not return a task result.")
    analysis = get_workflow_analysis_result(result)
    text = get_workflow_result_text(result)
    outputs = {"text": {"kind": "text", "value": text}}
    declared = result["authoritative_result"] if "authoritative_result" in result else analysis.get("authoritative_result")
    kind, value = _final_output(text, declared)
    outputs[kind] = {"kind": kind, "value": value}
    authoritative_output = kind
    if analysis.get("analysis_evidence") is not None:
        outputs["evidence"] = {"kind": "evidence", "value": _json_copy(analysis["analysis_evidence"])}
    if analysis.get("per_document") and not (
        analysis.get("analysis_result_version") == "analyze-final-v1" and declared is not None
    ):
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
    validation = (
        result.get("validation") or analysis.get("analysis_validation")
        or analysis.get("validation") or {"status": "not_requested"}
    )
    if not isinstance(coverage, Mapping) or not isinstance(validation, Mapping):
        raise ValueError("The task's coverage or validation metadata is invalid.")
    presentation = str(result.get("reply") or "")
    envelope = {
        "contract_version": contract_version,
        "identity": _json_copy(identity),
        "execution": {
            "status": _execution_state(result, analysis, artifacts),
            "deferred_composition": _json_copy(
                result.get("deferred_composition") or analysis.get("deferred_composition") or {}
            ),
        },
        "summary": presentation[:4000],
        "record_count": (
            sum(len(item["value"]) if item["kind"] == "records" else 1 for item in documents)
            if authoritative_output == "documents" else len(value) if kind == "records" else 1
        ),
        "authoritative_output": authoritative_output,
        "outputs": outputs,
        "presentation": {
            "summary": presentation[:4000],
            "preview_truncated": len(presentation) > 4000,
            "artifacts": artifacts,
        },
        "diagnostics": {
            "validation_audit": _json_copy(validation),
            "analysis": {key: _json_copy(value) for key, value in analysis.items()
                         if key not in {
                             "analysis_reply", "reply", "authoritative_result", "analysis_evidence",
                             "analysis_validation", "validation", "analysis_access",
                         }},
        },
        "artifacts": [
            {key: value for key, value in artifact.items() if key in {
                "artifact_message_id", "conversation_id", "file_name", "output_format",
                "capability", "run_id", "export_run_id", "row_count", "status",
            }}
            for artifact in artifacts if not artifact.get("reused_analysis_artifact")
        ],
        "coverage": _json_copy(coverage),
        "validation": public_analysis_validation(validation) if analysis.get("analysis_result_version") == "analyze-final-v1" else _json_copy(validation),
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
    access = analysis["analysis_access"] if "analysis_access" in analysis else result.get("analysis_access")
    if access is None and analysis.get("analysis_result_version") == "analyze-final-v1":
        sources = (
            analysis.get("analysis_sources") or analysis.get("mixed_source_manifest") or analysis.get("source_manifest")
            or analysis.get("documents") or []
        )
        access = {
            "version": ANALYSIS_SOURCE_ACCESS_VERSION,
            "sources": [
                source for source in sources
                if isinstance(source, Mapping)
                and source.get("authorization_status") in (None, "authorized")
            ],
        }
    if access is not None:
        if not isinstance(access, Mapping) or access.get("version") != ANALYSIS_SOURCE_ACCESS_VERSION:
            raise AnalysisResultUnavailable("analysis_source_manifest_invalid")
        sources = analysis_source_snapshot(access.get("sources"))
        if not sources:
            raise AnalysisResultUnavailable("analysis_source_manifest_missing")
        envelope["analysis_access"] = {"version": ANALYSIS_SOURCE_ACCESS_VERSION, "sources": sources}
        envelope["analysis_origin"] = (
            analysis.get("analysis_result_version") == "analyze-final-v1"
            and (result.get("analysis_consumption") or {}).get("mode") != "format_only"
        )
    if result.get("analysis_consumption"):
        envelope["analysis_consumption"] = _json_copy(result["analysis_consumption"])
    if analysis.get("native_result_references"):
        envelope["native_result_references"] = _json_copy(analysis["native_result_references"])
    # Reject unsupported SDK objects/NaN before any output is marked durable.
    return _json_copy(envelope)


def authorize_workflow_task_result_read(
    workflow, run_id, task_id, reference, *, reader_user_id=None, manifest=None,
    load_result=load_workflow_task_result, source_resolver=None, **selectors,
):
    """Recheck contributors of this result and every actually consumed ancestor."""
    if selectors:
        from functions_workflow_identity import workflow_node_identity
        from functions_workflow_node_results import authorize_workflow_node_result_read

        identity = workflow_node_identity(
            workflow, run_id, selectors.get("node_id"), selectors.get("execution_id"), selectors.get("attempt"),
            task_id=task_id, iteration_path=selectors.get("iteration_path"),
        )
        return authorize_workflow_node_result_read(
            workflow, run_id, identity, reference, reader_user_id=reader_user_id, manifest=manifest,
            load_result=load_workflow_node_result if load_result is load_workflow_task_result else load_result,
            source_resolver=source_resolver,
        )
    root = manifest if manifest is not None else load_result(workflow, run_id, task_id, reference)
    sources = []
    active = set()
    visited = set()
    loaded = {}

    def load_parent(parent_task_id, parent_ref):
        if not isinstance(parent_ref.get("sha256"), str) or not parent_ref["sha256"]:
            raise AnalysisResultUnavailable("analysis_lineage_invalid")
        key = (parent_task_id, parent_ref["sha256"])
        if key in loaded:
            prior_reference, parent = loaded[key]
            if prior_reference != parent_ref:
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
            return parent
        parent = load_result(workflow, run_id, parent_task_id, parent_ref)
        loaded[key] = (dict(parent_ref), parent)
        return parent

    def visit(current, current_task_id, current_ref):
        identity = current.get("identity") if isinstance(current, Mapping) else None
        if (
            not isinstance(identity, Mapping)
            or identity.get("workflow_id") != str(workflow.get("id") or "")
            or identity.get("run_id") != str(run_id)
            or identity.get("task_id") != str(current_task_id)
            or current.get("contract_version") != WORKFLOW_RESULT_CONTRACT_VERSION
            or not isinstance(current_ref, Mapping)
            or not isinstance(current_ref.get("sha256"), str)
        ):
            raise AnalysisResultUnavailable("analysis_lineage_invalid")
        key = (str(current_task_id), current_ref["sha256"])
        if key in active:
            raise AnalysisResultUnavailable("analysis_lineage_invalid")
        if key in visited:
            return
        if len(visited) + len(active) >= 256:
            raise AnalysisResultUnavailable("analysis_lineage_invalid")
        active.add(key)
        access = current.get("analysis_access")
        if access is not None:
            if not isinstance(access, Mapping) or access.get("version") != ANALYSIS_SOURCE_ACCESS_VERSION:
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
            direct_sources = analysis_source_snapshot(access.get("sources"))
            if not direct_sources:
                raise AnalysisResultUnavailable("analysis_source_manifest_missing")
            sources.extend(direct_sources)
        consumed_inputs = current.get("consumed_inputs") or []
        if not isinstance(consumed_inputs, list):
            raise AnalysisResultUnavailable("analysis_lineage_invalid")
        for consumed in consumed_inputs:
            producer = consumed.get("producer") if isinstance(consumed, Mapping) else None
            if (
                not isinstance(producer, Mapping)
                or producer.get("workflow_id") != str(workflow.get("id") or "")
                or producer.get("run_id") != str(run_id)
                or not isinstance(producer.get("task_id"), str) or not producer["task_id"]
                or not isinstance(consumed.get("result_ref"), Mapping)
            ):
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
            parent = load_parent(producer["task_id"], consumed["result_ref"])
            if not isinstance(parent, Mapping) or parent.get("identity") != producer:
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
            output = (parent.get("outputs") or {}).get(consumed.get("output_name"))
            if not isinstance(output, Mapping) or output.get("result_ref") != consumed.get("output_ref"):
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
            visit(parent, producer["task_id"], consumed["result_ref"])
        active.remove(key)
        visited.add(key)

    if isinstance(reference, Mapping) and isinstance(reference.get("sha256"), str):
        loaded[(str(task_id), reference["sha256"])] = (dict(reference), root)
    visit(root, task_id, reference)
    snapshots = analysis_source_snapshot(sources)
    access = (
        authorize_analysis_sources(
            reader_user_id if reader_user_id is not None else workflow.get("user_id"),
            snapshots, resolver=source_resolver,
        )
        if snapshots else {"source_count": 0, "source_snapshot_changed": False}
    )
    return root, {**access, "sources": snapshots}


def authorize_workflow_run_read(workflow, run_id, *, reader_user_id=None, result_items=None,
                                load_result=load_workflow_task_result, source_resolver=None):
    """Guard history/activity with every stored task result, without a UI item cap."""
    structured_run = False
    if result_items is None:
        # These are already scope-authorized workflow/run reads. Query only task
        # metadata directly so a failed store read cannot become an empty list.
        from config import cosmos_group_workflow_run_items_container, cosmos_personal_workflow_run_items_container
        if workflow.get("definition_version") == 3:
            from functions_workflow_runtime_store import WorkflowRuntimeConflict, workflow_runtime_store

            store = workflow_runtime_store(workflow, run_id)
            try:
                control = store.read()
            except WorkflowRuntimeConflict as exc:
                if exc.code != "not_found":
                    raise
                control = None
            if control and control.get("schema_version") == 2:
                workflow = store.run_definition()
                structured_run = True

        container = (
            cosmos_group_workflow_run_items_container if workflow.get("group_id")
            else cosmos_personal_workflow_run_items_container
        )
        result_items = container.query_items(
            query=(
                "SELECT c.workflow_id, c.run_id, c.task_id, c.workflow_result FROM c "
                "WHERE c.run_id = @run_id AND c.workflow_id = @workflow_id AND c.item_type = 'task'"
            ),
            parameters=[
                {"name": "@run_id", "value": run_id},
                {"name": "@workflow_id", "value": workflow["id"]},
            ],
            partition_key=run_id,
        )
    cache = {}

    def cached_load(bound_workflow, bound_run_id, task_id, reference, **selectors):
        key = (bound_run_id, task_id, json.dumps(reference, sort_keys=True), json.dumps(selectors, sort_keys=True))
        if key not in cache:
            loader = load_workflow_node_result if selectors and load_result is load_workflow_task_result else load_result
            cache[key] = loader(bound_workflow, bound_run_id, task_id, reference, **selectors)
        return cache[key]

    for item in result_items:
        if item.get("item_type") not in (None, "task"):
            continue
        reference = (item.get("workflow_result") or {}).get("result_ref")
        if reference is None:
            continue
        if item.get("workflow_id") != workflow["id"] or item.get("run_id") != run_id:
            raise AnalysisResultUnavailable("analysis_lineage_invalid")
        authorize_workflow_task_result_read(
            workflow, run_id, item.get("task_id"), reference,
            reader_user_id=reader_user_id, source_resolver=source_resolver, load_result=cached_load,
            **({key: item['workflow_result']['producer'][key] for key in ('node_id', 'execution_id', 'iteration_path', 'attempt')}
               if (item.get('workflow_result') or {}).get('contract_version') == 'workflow-result-v2' else {}),
        )
    if structured_run:
        from functions_workflow_execution_history import workflow_execution_history

        cursor = None
        while True:
            page = workflow_execution_history(workflow, run_id, reader_user_id=reader_user_id, cursor=cursor, limit=100)
            cursor = page["next_cursor"]
            if cursor is None:
                break


def _require_completed_result(envelope, *, allow_partial=False):
    if envelope.get("contract_version") not in {WORKFLOW_RESULT_CONTRACT_VERSION, "workflow-result-v2"}:
        raise ValueError("This workflow task result version is not supported.")
    state = (envelope.get("execution") or {}).get("status")
    validation = (envelope.get("validation") or {}).get("status")
    workflow_validation = envelope.get("workflow_validation")
    workflow_status = None
    if workflow_validation is not None:
        if (
            not isinstance(workflow_validation, Mapping) or workflow_validation.get("version") != 1
            or workflow_validation.get("eligible") is not True
        ):
            raise WorkflowResultNotReadyError("The task's output requirements were not satisfied.")
        workflow_status = workflow_validation.get("status")
        if workflow_status not in {"valid", "not_requested", "accepted_partial"}:
            raise WorkflowResultNotReadyError("The task's output requirements were not satisfied.")
    if type(allow_partial) is not bool:
        raise ValueError("Partial-result eligibility must be an explicit boolean.")
    partial = (validation == "partial" or workflow_status == "accepted_partial") and state in {"succeeded", "incomplete"}
    if state == "succeeded" and validation not in {"invalid", "pending"} and (not partial or allow_partial):
        return
    if (
        allow_partial and partial and validation not in {"invalid", "pending"}
        and state in {"succeeded", "incomplete"}
    ):
        if validation == "partial":
            require_readable_analysis_result(envelope)
        return
    raise WorkflowResultNotReadyError(
        "The previous task has no completed authoritative output. Its result and diagnostics "
        "are retained; accepted partial findings require an explicit reporting opt-in, and "
        "invalid or pending results cannot replace the required input."
    )


def require_readable_analysis_result(manifest):
    """Accepted partial findings are readable, but unfinished/invalid work is not final data."""
    state = (manifest.get("execution") or {}).get("status")
    validation = (manifest.get("validation") or {}).get("status")
    if (
        state not in {"succeeded", "incomplete", "pending"}
        or validation in {"pending", "invalid"}
        or (state in {"incomplete", "pending"} and validation != "partial")
    ):
        raise WorkflowResultNotReadyError(
            "This analysis has no readable accepted result yet. Its native execution state "
            "and diagnostics are retained; an unfinished summary cannot replace final records."
        )


def persist_workflow_task_result(envelope, *, workflow, run_id, task_id, settings=None,
                                 save_result=None):
    """Commit independently readable sections, then their small result manifest."""
    if save_result is None:
        save_result = save_workflow_node_result if envelope.get("contract_version") == "workflow-result-v2" else save_workflow_task_result
        if settings is None:
            # Production callers need the actual quota, including paged result sections.
            from functions_settings import get_settings
            settings = get_settings()
    selectors = {}
    if envelope.get("contract_version") == "workflow-result-v2":
        from functions_workflow_node_results import result_selectors

        selectors = result_selectors(envelope["identity"])
    return persist_result_sections(
        envelope,
        lambda section: save_result(workflow, run_id, task_id, section, settings=settings, **selectors),
        max_result_bytes=_quota_bytes(settings or {}),
    )


def _encoded_result_size(value):
    return len(json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")))


def _save_record_pages(envelope, name, rows, save_section, max_result_bytes, kind="records"):
    pages = []
    page = []
    page_bytes = 2
    total_bytes = _encoded_result_size({
        "contract_version": envelope["contract_version"], "producer": envelope["identity"],
        "output_name": name, "kind": kind, "value": [],
    })
    for record_index, record in enumerate(rows):
        size = _encoded_result_size(record) + 1
        total_bytes += size - 1 + int(record_index > 0)
        if total_bytes > max_result_bytes:
            raise ValueError("The complete analysis record collection exceeds its configured size limit.")
        if page and (len(page) >= ANALYSIS_RECORD_PAGE_SIZE or page_bytes + size > ANALYSIS_RECORD_PAGE_BYTES):
            pages.append(page)
            page = []
            page_bytes = 2
        page.append(record)
        page_bytes += size
    if page:
        pages.append(page)
    if len(pages) <= 1:
        return None
    entries = []
    offset = 0
    for index, records in enumerate(pages):
        page_name = f"{name}:page:{index}"
        reference = save_section({
            "contract_version": envelope["contract_version"], "producer": envelope["identity"],
            "output_name": page_name, "kind": kind, "value": records,
        })
        entries.append({"output_name": page_name, "offset": offset, "count": len(records), "result_ref": reference})
        offset += len(records)
    reference = save_section({
        "contract_version": envelope["contract_version"], "producer": envelope["identity"],
        "output_name": name, "kind": "record_pages",
        "value": {"record_count": len(rows), "pages": entries},
    })
    return {"kind": kind, "storage_kind": "record_pages", "result_ref": reference, "record_count": len(rows)}


def persist_result_sections(
    envelope, save_section, *, max_result_bytes=DEFAULT_MAX_RESULT_SIZE_MB * 1024 * 1024,
):
    """Share section persistence without inventing a workflow identity for chat."""
    if type(max_result_bytes) is not int or max_result_bytes <= 0:
        raise ValueError("The result size limit is invalid.")
    if _encoded_result_size(envelope) > max_result_bytes:
        raise ValueError("The complete analysis result exceeds its configured size limit.")
    manifest = {key: _json_copy(value) for key, value in envelope.items()
                if key not in {"outputs", "presentation", "diagnostics"}}
    sections = dict(envelope["outputs"])
    sections["presentation"] = {"kind": "presentation", "value": envelope["presentation"]}
    sections["diagnostics"] = {"kind": "diagnostics", "value": envelope["diagnostics"]}
    manifest["outputs"] = {}
    if envelope.get("contract_version") == "workflow-result-v2" and len(envelope.get("consumed_inputs") or []) > 100:
        index = _save_record_pages(envelope, "lineage", envelope["consumed_inputs"], save_section, max_result_bytes)
        if index:
            manifest.pop("consumed_inputs", None)
            manifest["consumed_inputs_index"] = index
    for name, output in sections.items():
        if output["kind"] in {"records", "evidence", "document_results"} and (
            envelope.get("analysis_access") or envelope.get("contract_version") == "workflow-result-v2"
        ) and isinstance(output["value"], list):
            paged = _save_record_pages(envelope, name, output["value"], save_section, max_result_bytes, output["kind"])
            if paged is not None:
                manifest["outputs"][name] = paged
                continue
        section = {
            "contract_version": envelope["contract_version"],
            "producer": envelope["identity"],
            "output_name": name,
            "kind": output["kind"],
            "value": output["value"],
        }
        reference = save_section(section)
        manifest["outputs"][name] = {"kind": output["kind"], "result_ref": reference}
    reference = save_section(manifest)
    return manifest, reference


def read_result_records(manifest, name, load_section, *, offset=0, limit=None):
    """Read a complete-record range without loading unrelated record pages."""
    output = (manifest.get("outputs") or {}).get(name)
    if not isinstance(output, Mapping) or output.get("kind") not in {"records", "evidence", "document_results"}:
        raise ValueError("The requested output is not a record collection.")
    if type(offset) is not int or offset < 0 or (limit is not None and (type(limit) is not int or limit < 1)):
        raise ValueError("The record range is invalid.")
    reference = output.get("result_ref") or {}
    if reference.get("size_bytes", 0) > ANALYSIS_MATERIALIZATION_BYTES:
        raise ValueError("This result requires a bounded record reader rather than whole-result materialization.")

    def load_checked(ref, output_name, kind):
        section = load_section(ref)
        if (
            not isinstance(section, Mapping)
            or section.get("contract_version") != manifest.get("contract_version")
            or section.get("producer") != manifest.get("identity")
            or section.get("output_name") != output_name or section.get("kind") != kind
        ):
            raise ValueError("The saved record page does not match its result.")
        return section.get("value")

    if output.get("storage_kind") != "record_pages":
        rows = load_checked(reference, name, output["kind"])
        if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
            raise ValueError("The saved record collection is invalid.")
        if offset > len(rows):
            raise ValueError("The record offset exceeds the result.")
        return rows[offset:offset + limit] if limit is not None else rows[offset:], len(rows)

    index = load_checked(reference, name, "record_pages")
    if (
        not isinstance(index, Mapping) or type(index.get("record_count")) is not int or index["record_count"] < 0
        or type(output.get("record_count")) is not int or output["record_count"] != index["record_count"]
    ):
        raise ValueError("The saved record index is invalid.")
    pages = index.get("pages")
    if not isinstance(pages, list):
        raise ValueError("The saved record index has no pages.")
    expected_offset = 0
    total_bytes = 0
    for page_index, page in enumerate(pages):
        if (
            not isinstance(page, Mapping) or page.get("output_name") != f"{name}:page:{page_index}"
            or type(page.get("offset")) is not int or page["offset"] != expected_offset
            or type(page.get("count")) is not int or page["count"] < 1
            or not isinstance(page.get("result_ref"), Mapping)
            or type(page["result_ref"].get("size_bytes")) is not int
            or page["result_ref"]["size_bytes"] <= 0
        ):
            raise ValueError("The saved record index contains a gap or invalid page.")
        expected_offset += page["count"]
        total_bytes += page["result_ref"]["size_bytes"]
    if expected_offset != index["record_count"] or offset > expected_offset:
        raise ValueError("The saved record index count does not match.")
    if limit is None and total_bytes > ANALYSIS_MATERIALIZATION_BYTES:
        raise ValueError("The complete analysis requires explicit record batches; it was not truncated.")
    end = min(expected_offset, offset + limit) if limit is not None else expected_offset
    records = []
    for page in pages:
        start = page["offset"]
        page_end = start + page["count"]
        if page_end <= offset or start >= end:
            continue
        if page["result_ref"]["size_bytes"] > ANALYSIS_MATERIALIZATION_BYTES:
            raise ValueError("A saved record is too large to materialize safely.")
        rows = load_checked(page["result_ref"], page["output_name"], output["kind"])
        if not isinstance(rows, list) or len(rows) != page["count"] or any(not isinstance(row, Mapping) for row in rows):
            raise ValueError("The saved record page count or shape is invalid.")
        records.extend(rows[max(0, offset - start):min(len(rows), end - start)])
    if len(records) != end - offset:
        raise ValueError("The requested records could not be reconstructed completely.")
    return records, expected_offset


def iter_result_records(manifest, name, load_section):
    """Walk a complete collection using bounded, independently verified pages."""
    offset = 0
    while True:
        rows, total = read_result_records(
            manifest, name, load_section, offset=offset, limit=ANALYSIS_RECORD_PAGE_SIZE,
        )
        yield from rows
        offset += len(rows)
        if offset >= total:
            return
        if not rows:
            raise ValueError("The saved record collection has an unreadable gap.")


def load_workflow_task_input(workflow, run_id, task_id, reference,
                             *, load_result=load_workflow_task_result, reader_user_id=None,
                             source_resolver=None, output_name="authoritative",
                             allow_partial=False, bounded=False, **selectors):
    """Read one exact final representation and its immutable consumption receipt.

    The default selects the producer's authoritative output. Explicit names
    select only text/records/json/documents, never presentation or diagnostics.
    Partial accepted Analyze findings require an explicit reporting opt-in;
    neither that opt-in nor a named output admits pending or invalid results.
    """
    if selectors:
        from functions_workflow_identity import workflow_node_identity
        from functions_workflow_node_results import load_workflow_node_input

        return load_workflow_node_input(
            workflow, run_id, workflow_node_identity(
                workflow, run_id, selectors.get("node_id"), selectors.get("execution_id"), selectors.get("attempt"),
                task_id=task_id, iteration_path=selectors.get("iteration_path"),
            ), reference, output_name=output_name, allow_partial=allow_partial,
            reader_user_id=reader_user_id,
            load_result=load_workflow_node_result if load_result is load_workflow_task_result else load_result,
            source_resolver=source_resolver,
        )
    final_kinds = {"text": "text", "records": "records", "json": "json", "documents": "document_results"}
    if not isinstance(output_name, str) or output_name not in {"authoritative", *final_kinds}:
        raise ValueError("The requested workflow output must be an exact final representation.")
    if type(allow_partial) is not bool:
        raise ValueError("The partial-result reporting option must be a boolean.")
    manifest = load_result(workflow, run_id, task_id, reference)
    identity = manifest.get("identity") or {}
    if (
        identity.get("workflow_id") != str(workflow.get("id") or "")
        or identity.get("run_id") != str(run_id)
        or identity.get("task_id") != str(task_id)
    ):
        raise ValueError("The saved result does not match the requested producer.")
    manifest, access = authorize_workflow_task_result_read(
        workflow, run_id, task_id, reference, manifest=manifest,
        reader_user_id=reader_user_id, load_result=load_result, source_resolver=source_resolver,
    )
    _require_completed_result(manifest, allow_partial=allow_partial)
    name = manifest.get("authoritative_output") if output_name == "authoritative" else output_name
    if not isinstance(name, str) or name not in final_kinds:
        raise ValueError("The saved task has no authoritative output binding.")
    output_descriptor = (manifest.get("outputs") or {}).get(name)
    if (
        not isinstance(output_descriptor, Mapping)
        or output_descriptor.get("kind") != final_kinds[name]
        or not isinstance(output_descriptor.get("result_ref"), Mapping)
    ):
        raise ValueError("The saved task has no authoritative output binding.")
    output_ref = output_descriptor["result_ref"]
    consumed = {
        "producer": manifest["identity"], "output_name": name,
        "result_ref": dict(reference), "output_ref": dict(output_ref),
    }
    if access["source_count"]:
        consumed["analysis_result"] = True
        if bounded and output_name == "authoritative" and not manifest.get("analysis_access"):
            parents = manifest.get("consumed_inputs") or []
            if len(parents) != 1:
                raise WorkflowResultNotReadyError(
                    "This report has multiple analysis ancestors. Select a saved analysis instead of substituting its report text for records."
                )
            parent = parents[0]
            saved_input, _ = load_workflow_task_input(
                workflow, run_id, parent["producer"]["task_id"], parent["result_ref"],
                load_result=load_result, reader_user_id=reader_user_id, source_resolver=source_resolver,
                bounded=True, allow_partial=allow_partial,
            )
            return saved_input, consumed
        if bounded and manifest.get("analysis_access") and name == manifest.get("authoritative_output"):
            # Saved analysis depends on this contract; defer the inverse import.
            from functions_saved_analysis import SavedAnalysisInput

            return SavedAnalysisInput(
                manifest, lambda ref: load_result(workflow, run_id, task_id, ref), access,
                {"producer": manifest["identity"], "result_sha256": reference["sha256"]},
                reauthorize=lambda: authorize_workflow_task_result_read(
                    workflow, run_id, task_id, reference, reader_user_id=reader_user_id,
                    load_result=load_result, source_resolver=source_resolver,
                )[1],
            ), consumed
    if output_descriptor.get("storage_kind") == "record_pages":
        records, _ = read_result_records(
            manifest, name, lambda ref: load_result(workflow, run_id, task_id, ref),
        )
        output = {
            "contract_version": manifest["contract_version"], "producer": manifest["identity"],
            "output_name": name, "kind": output_descriptor["kind"], "value": records,
        }
    else:
        output = load_result(workflow, run_id, task_id, output_ref)
    if (
        not isinstance(output, Mapping)
        or output.get("contract_version") != WORKFLOW_RESULT_CONTRACT_VERSION
        or output.get("producer") != manifest.get("identity")
        or output.get("output_name") != name
        or output.get("kind") != output_descriptor.get("kind")
    ):
        raise ValueError("The saved output does not match its producer's manifest.")
    prompt = json.dumps({
        "consumed_result": consumed,
        "provenance": manifest.get("provenance") or {},
        "coverage": manifest.get("coverage") or {},
        "validation": public_analysis_validation(manifest.get("validation")) if access["source_count"] else manifest.get("validation") or {},
        "source_snapshot_changed": access["source_snapshot_changed"],
        "kind": output["kind"],
        "value": output["value"],
        **({
            "accepted_subset_only": True, "execution": manifest.get("execution") or {},
        } if (manifest.get("validation") or {}).get("status") == "partial" else {}),
    }, ensure_ascii=False, allow_nan=False, sort_keys=True)
    return prompt, consumed


def workflow_result_summary(envelope, reference):
    """Small, non-secret history projection; full outputs stay in the result store."""
    summary = {
        "contract_version": envelope["contract_version"],
        "result_ref": dict(reference),
        "output_kinds": list(envelope.get("outputs") or {}),
        "authoritative_output": envelope.get("authoritative_output"),
        "outputs": _json_copy(envelope.get("outputs") or {}),
        "output_state": (envelope.get("execution") or {}).get("status"),
        "validation_status": public_analysis_validation(envelope.get("validation"))["status"],
        "consumed_inputs": _json_copy(envelope.get("consumed_inputs") or []),
        "workflow_validation": _json_copy(envelope.get("workflow_validation") or {}),
    }
    if envelope.get("contract_version") == "workflow-result-v2":
        summary["producer"] = _json_copy(envelope["identity"])
        if envelope.get("consumed_inputs_index"):
            summary["consumed_input_count"] = envelope["consumed_inputs_index"]["record_count"]
    if envelope.get("analysis_access") or any(
        item.get("analysis_result") for item in envelope.get("consumed_inputs") or []
        if isinstance(item, Mapping)
    ):
        summary["analysis_result"] = True
        summary["producer"] = _json_copy(envelope["identity"])
        summary["analysis_origin"] = envelope.get("analysis_origin") is True
        summary["record_count"] = envelope.get("record_count")
        summary["source_count"] = len((envelope.get("analysis_access") or {}).get("sources") or [])
    return summary
