# functions_native_tabular_compute.py
"""Server-owned, route-free native tabular computation and durable ownership.

The native runner is loaded only when a runtime owner calls the service: it
depends on initialized application storage and model clients. Contract and
authorization helpers remain safe to import before application bootstrap.
"""

from copy import deepcopy
import hashlib
import json
import os
import re
import uuid

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from content_screening.access import PROVENANCE_FIELD, assert_evidence_available
from functions_analysis_access import (
    AnalysisResultUnavailable,
    analysis_source_snapshot,
    authorize_analysis_sources,
)
from functions_tabular_csv_query import validate_tabular_csv_query_expression


NATIVE_TABULAR_DATA_ONLY = "data_only"
NATIVE_TABULAR_COMPUTE_VERSION = "native-tabular-compute-v1"
NATIVE_TABULAR_RESULT_VERSION = "native-tabular-result-v1"
_PRODUCER_FIELDS = {
    "user_id", "conversation_id", "run_id", "attempt_index", "step_id",
    "capability_id", "contract_version",
}
_CONTEXT_FIELDS = {"version", "producer", "sources", "request_fingerprint", "operation"}
_HANDLE_FIELDS = {"version", "job_id", "request_fingerprint"}
_OPERATIONS = {"query", "transform", "analysis"}


class NativeTabularComputeError(ValueError):
    """A stable service error, without source locators or provider error text."""

    def __init__(self, code):
        self.code = code
        super().__init__("The native tabular computation request could not be accepted.")


def native_compute_digest(value):
    return hashlib.sha256(native_compute_bytes(value)).hexdigest()


def native_compute_bytes(value):
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def normalize_native_compute_producer(producer):
    if not isinstance(producer, dict) or set(producer) != _PRODUCER_FIELDS:
        raise NativeTabularComputeError("native_compute_producer_invalid")
    if type(producer["attempt_index"]) is not int or producer["attempt_index"] < 1:
        raise NativeTabularComputeError("native_compute_producer_invalid")
    for key in _PRODUCER_FIELDS - {"attempt_index"}:
        value = producer[key]
        if not isinstance(value, str) or not value.strip() or len(value) > 256:
            raise NativeTabularComputeError("native_compute_producer_invalid")
    if producer["capability_id"] not in {"tabular_analyze", "document_analyze"}:
        raise NativeTabularComputeError("native_compute_producer_invalid")
    return deepcopy(producer)


def native_compute_job_id(producer):
    normalized = normalize_native_compute_producer(producer)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{NATIVE_TABULAR_COMPUTE_VERSION}:{native_compute_digest(normalized)}"))


def validate_native_compute_context(context):
    if not isinstance(context, dict) or set(context) != _CONTEXT_FIELDS:
        raise NativeTabularComputeError("native_compute_context_invalid")
    normalize_native_compute_producer(context["producer"])
    sources = analysis_source_snapshot(context["sources"])
    if (
        context["version"] != NATIVE_TABULAR_COMPUTE_VERSION
        or len(sources) != 1 or sources != context["sources"]
        or context["operation"] not in _OPERATIONS
        or not isinstance(context["request_fingerprint"], str)
        or re.fullmatch(r"[a-f0-9]{64}", context["request_fingerprint"]) is None
    ):
        raise NativeTabularComputeError("native_compute_context_invalid")
    return context


def native_compute_handle(run):
    context = validate_native_compute_context(run.get("compute_context"))
    if run.get("id") != native_compute_job_id(context["producer"]):
        raise NativeTabularComputeError("native_compute_identity_invalid")
    return {
        "version": NATIVE_TABULAR_COMPUTE_VERSION,
        "job_id": run["id"],
        "request_fingerprint": context["request_fingerprint"],
    }


def validate_native_compute_handle(handle, producer):
    if (
        not isinstance(handle, dict) or set(handle) != _HANDLE_FIELDS
        or handle.get("version") != NATIVE_TABULAR_COMPUTE_VERSION
        or handle.get("job_id") != native_compute_job_id(producer)
        or not isinstance(handle.get("request_fingerprint"), str)
        or re.fullmatch(r"[a-f0-9]{64}", handle["request_fingerprint"]) is None
    ):
        raise AnalysisResultUnavailable("native_compute_identity_invalid")


def authorize_native_compute_owner(
    run, *, conversation, read_producer, require_active=True,
    require_current_sources=True, source_resolver=None, source_metadata_reader=None,
):
    """Revalidate the persisted owner and source snapshots, including on restart."""
    context = validate_native_compute_context(run.get("compute_context"))
    producer = context["producer"]
    if (
        run.get("execution_policy") != NATIVE_TABULAR_DATA_ONLY
        or run.get("id") != native_compute_job_id(producer)
        or run.get("user_id") != producer["user_id"]
        or run.get("conversation_id") != producer["conversation_id"]
        or not isinstance(conversation, dict)
        or conversation.get("id") != producer["conversation_id"]
        or conversation.get("user_id") != producer["user_id"]
        or conversation.get("orchestration_deleted") or conversation.get("deleted")
        or conversation.get("deleted_at")
    ):
        raise AnalysisResultUnavailable("native_compute_owner_unavailable")
    try:
        parent = read_producer(producer["run_id"])
    except CosmosResourceNotFoundError as exc:
        raise AnalysisResultUnavailable("native_compute_producer_unavailable") from exc
    if (
        not isinstance(parent, dict) or parent.get("id") != producer["run_id"]
        or parent.get("user_id") != producer["user_id"]
        or parent.get("conversation_id") != producer["conversation_id"]
        or parent.get("checkpoints_deleted") or parent.get("deleted_at")
        or type(parent.get("attempt_index", 1)) is not int
        or parent.get("attempt_index", 1) != producer["attempt_index"]
    ):
        raise AnalysisResultUnavailable("native_compute_producer_unavailable")
    steps = (parent.get("plan") or {}).get("steps")
    if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
        raise AnalysisResultUnavailable("native_compute_producer_unavailable")
    matching = [step for step in steps if step.get("step_id") == producer["step_id"]]
    if (
        len(matching) != 1 or matching[0].get("enabled", True) is not True
        or matching[0].get("capability_id") != producer["capability_id"]
    ):
        raise AnalysisResultUnavailable("native_compute_producer_unavailable")
    if (
        parent.get("status") in {"canceled", "cancelled"}
        or parent.get("cancellation_requested_at")
        or run.get("status") in {"canceled", "cancelled"} or run.get("deleted_at")
        or (require_active and (
            parent.get("status") not in {"running", "waiting"}
            or parent.get("latest_attempt_run_id")
        ))
    ):
        raise AnalysisResultUnavailable("native_compute_producer_stopped")
    access = authorize_analysis_sources(
        producer["user_id"], context["sources"],
        require_snapshot=require_current_sources, resolver=source_resolver,
    )
    assert_evidence_available(
        context["sources"], user_id=producer["user_id"], metadata_reader=source_metadata_reader,
    )
    return access


def _compute_request(plan, user_question):
    if not isinstance(plan, dict) or not isinstance(user_question, str) or not user_question.strip():
        raise NativeTabularComputeError("native_compute_plan_invalid")
    if len(user_question) > 24000:
        raise NativeTabularComputeError("native_compute_request_too_large")
    hints = plan.get("requested_output_hints") or {}
    contract = plan.get("deliverable_contract") or {}
    if not isinstance(hints, dict) or not isinstance(contract, dict):
        raise NativeTabularComputeError("native_compute_plan_invalid")
    task_type = plan.get("durable_task_type") or plan.get("execution_contract")
    if task_type not in {"foreground_aggregate", "structured_export", "combined", "hierarchical_analysis"}:
        raise NativeTabularComputeError("native_compute_operation_unsupported")
    operation = hints.get("native_operation")
    transformation = contract.get("transformation_spec") or {}
    schema = contract.get("public_output_schema") or []
    if (
        not isinstance(transformation, dict) or not isinstance(schema, list) or len(schema) > 50
        or any(not isinstance(name, str) or not name.strip() or len(name) > 128 for name in schema)
        or len(set(schema)) != len(schema)
    ):
        raise NativeTabularComputeError("native_compute_schema_invalid")
    if operation is None:
        operation = "analysis" if task_type == "hierarchical_analysis" else "transform"
    if operation not in _OPERATIONS:
        raise NativeTabularComputeError("native_compute_operation_unsupported")
    if task_type == "foreground_aggregate":
        # A prose aggregate plan is not a computed table. Admit only a declared
        # row query/transformation; do not silently replace aggregation with rows.
        if operation == "transform" and not transformation and not schema:
            raise NativeTabularComputeError("native_compute_foreground_contract_required")
        task_type = "hierarchical_analysis" if operation == "analysis" else "structured_export"
    if operation == "query" and (
        task_type != "structured_export" or transformation or not schema
        or not isinstance(hints.get("query_expression"), str)
    ):
        raise NativeTabularComputeError("native_compute_query_contract_invalid")
    if operation == "analysis" and (task_type != "hierarchical_analysis" or transformation):
        raise NativeTabularComputeError("native_compute_operation_unsupported")
    if operation == "transform" and task_type not in {"structured_export", "combined"}:
        raise NativeTabularComputeError("native_compute_operation_unsupported")
    query = validate_tabular_csv_query_expression(hints.get("query_expression") or "index == index")
    return {
        "task_type": task_type, "operation": operation, "query_expression": query,
        "selected_sheet": hints.get("selected_sheet"),
        "deliverable_contract": deepcopy(contract),
        "row_analysis_mode": plan.get("row_analysis_mode"),
        "row_analysis_questions": deepcopy(plan.get("row_analysis_questions") or []),
        "question_sha256": native_compute_digest(user_question),
    }


def _prepare_native_source(engine, source, request, user_id):
    """Use the foreground query engine to pin a replay, never its sample as output."""
    locator = source.get("storage_locator") or {}
    if not isinstance(locator, dict) or not locator.get("container") or not locator.get("blob_path"):
        raise NativeTabularComputeError("native_compute_source_not_replayable")
    filename = source.get("file_name")
    source_format = os.path.splitext(filename or "")[1].lower().lstrip(".")
    if source_format not in {"csv", "xlsx", "xls", "xlsm"}:
        raise NativeTabularComputeError("native_compute_source_unsupported")
    plugin = engine.TabularProcessingPlugin(authorized_user_id=user_id)
    container, blob_path = locator["container"], locator["blob_path"]
    query = request["query_expression"]
    if source_format == "csv":
        result = plugin._query_csv_data_in_bounded_chunks(
            container, blob_path, filename, query, return_columns=None, start_row=0, max_rows=5,
        )
        payload = json.loads(str(result))
        descriptor = deepcopy(result.internal_metadata.get("tabular_generated_export_source"))
        samples = payload.get("data") or []
        count = payload.get("total_matches")
    else:
        selected_sheet = request["selected_sheet"]
        metadata = plugin._get_workbook_metadata(container, blob_path)
        if selected_sheet:
            selected_sheet, _ = plugin._resolve_sheet_selection(
                container, blob_path, sheet_name=selected_sheet, require_explicit_sheet=True,
            )
            sheets = [selected_sheet]
        else:
            sheets = list(metadata.get("sheet_names") or [])
        if not sheets:
            raise NativeTabularComputeError("native_compute_source_not_replayable")
        version = plugin._get_tabular_blob_version(container, blob_path, refresh=True)
        descriptor = plugin._build_generated_export_query_descriptor_from_location(
            container_name=container, blob_path=blob_path, filename=filename,
            query_expression=query, blob_version=version, selected_sheet=selected_sheet, sheet_names=sheets,
        )
        count, samples = 0, []
        for _, row in engine._iter_versioned_tabular_source_rows(
            descriptor, source_format, 1000, 0, user_id=user_id,
        ):
            count += 1
            if len(samples) < 5:
                samples.append(row)
        descriptor["expected_row_count"] = count
    if type(count) is not int or count < 0 or not isinstance(descriptor, dict):
        raise NativeTabularComputeError("native_compute_source_invalid")
    if descriptor.get("expected_row_count") != count or descriptor.get("query_expression") != query:
        raise NativeTabularComputeError("native_compute_source_invalid")
    provenance = descriptor.get(PROVENANCE_FIELD)
    if isinstance(provenance, dict) and str(provenance.get("document_id")) != str(source["document_id"]):
        # The replay location resolved to another document or revision than the approved source.
        raise NativeTabularComputeError("native_compute_source_identity_mismatch")
    descriptor["document_id"] = source["document_id"]
    candidate = {
        "filename": filename, "selected_sheet": descriptor.get("selected_sheet"),
        "rows": samples, "row_count": len(samples), "total_matches": count,
        "full_result_available": False, "source_authorization": descriptor,
    }
    return candidate, descriptor


def build_native_tabular_compute_callback(
    *, user_id, conversation_id, producer, source_manifest, gpt_model, settings,
    model_context=None, cancel_requested=None,
):
    """Bind a production callback to one authorized producer, not browser identity.

    The returned callback handles both planner foreground and durable contracts.
    It returns ``status``, ``handle`` and an optional complete ``reader``. The
    callback itself and its reader are runtime-only; persist only the handle.
    """
    producer = normalize_native_compute_producer(producer)
    if producer["user_id"] != user_id or producer["conversation_id"] != conversation_id:
        raise AnalysisResultUnavailable("native_compute_owner_unavailable")
    if cancel_requested is not None and not callable(cancel_requested):
        raise TypeError("The native cancellation callback must be callable.")
    if (
        not isinstance(source_manifest, list) or len(source_manifest) != 1
        or not isinstance(source_manifest[0], dict)
        or source_manifest[0].get("source_kind") != "tabular"
    ):
        raise NativeTabularComputeError("native_compute_multi_source_unsupported")
    source = deepcopy(source_manifest[0])
    sources = analysis_source_snapshot([source])
    settings = dict(settings or {})
    model_context = deepcopy(model_context)

    def execute(*, plan, user_question, file_contexts=None, **execution_context):
        del execution_context
        if cancel_requested is not None and cancel_requested():
            return {"status": "cancelled", "handle": None, "reader": None, "readers": {}}
        request = _compute_request(plan, user_question)
        coverage = plan.get("source_coverage")
        if (
            plan.get("source_count") != 1 or not isinstance(coverage, list) or len(coverage) != 1
            or not isinstance(coverage[0], dict)
            or coverage[0].get("file_name") != source.get("file_name")
            or coverage[0].get("document_id") not in (None, "", source["document_id"])
            or (
                coverage[0].get("source_version") not in (None, "")
                and str(coverage[0]["source_version"]) != str(source.get("source_version"))
            )
            or (file_contexts is not None and (
                not isinstance(file_contexts, list) or len(file_contexts) != 1
                or not isinstance(file_contexts[0], dict)
                or file_contexts[0].get("file_name") != source.get("file_name")
                or file_contexts[0].get("document_id") not in (None, "", source["document_id"])
            ))
        ):
            raise NativeTabularComputeError("native_compute_source_selection_changed")
        context = {
            "version": NATIVE_TABULAR_COMPUTE_VERSION, "producer": producer,
            "sources": sources, "operation": request["operation"],
            "request_fingerprint": native_compute_digest({"request": request, "sources": sources}),
        }
        # Runtime storage/model ownership belongs to the initialized native
        # engine, not this import-safe contract module or a Flask route.
        from functions_native_analysis_results import open_native_tabular_result
        import functions_tabular_generated_exports as engine

        identity = {
            "id": native_compute_job_id(producer), "user_id": user_id,
            "conversation_id": conversation_id, "execution_policy": NATIVE_TABULAR_DATA_ONLY,
            "compute_context": context, "status": "queued",
        }
        engine._authorize_tabular_export_run_execution(identity)
        try:
            existing = engine._read_run(user_id, identity["id"])
        except CosmosResourceNotFoundError:
            existing = None
        if existing is not None:
            if (
                existing.get("execution_policy") != NATIVE_TABULAR_DATA_ONLY
                or existing.get("compute_context") != context
            ):
                raise NativeTabularComputeError("native_compute_request_changed")
            engine._revalidate_tabular_source_version_for_publication(existing)
            return open_native_tabular_result(
                user_id=user_id, conversation_id=conversation_id,
                handle=native_compute_handle(existing), producer=producer, require_current_sources=True,
            )

        candidate, descriptor = _prepare_native_source(engine, source, request, user_id)
        engine._authorize_tabular_export_run_execution({**identity, "source_descriptor": descriptor})
        if cancel_requested is not None and cancel_requested():
            return {"status": "cancelled", "handle": None, "reader": None, "readers": {}}
        run = engine.queue_tabular_generated_output_run(
            user_id=user_id, conversation_id=conversation_id, user_question=user_question,
            source_candidate=candidate, output_format="json", row_batches=None, gpt_model=gpt_model,
            settings=settings, model_context=model_context, source_descriptor=descriptor,
            passthrough_input_rows=request["operation"] == "query",
            task_type=request["task_type"],
            analysis_objective=user_question if request["task_type"] in {"combined", "hierarchical_analysis"} else None,
            planner_metadata=plan, execution_policy=NATIVE_TABULAR_DATA_ONLY,
            compute_context=context, submit=False,
        )
        foreground = (
            plan.get("execution_contract") == "foreground_aggregate"
            and not engine.should_queue_tabular_generated_output_background(
                run["row_count"], run["batch_count"], settings,
            )
        )
        if foreground:
            engine.process_tabular_generated_output_run(run["id"], user_id)
        else:
            engine.submit_tabular_generated_output_run(run["id"], user_id)
        return open_native_tabular_result(
            user_id=user_id, conversation_id=conversation_id,
            handle=native_compute_handle(run), producer=producer, require_current_sources=True,
        )

    return execute
