# functions_native_analysis_results.py
"""Adapt complete native tabular outputs, never their bounded handoff previews."""

from copy import deepcopy
import hashlib
import io
import json
import re

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from functions_analysis_access import AnalysisResultUnavailable, authorize_analysis_sources
from functions_document_analysis_results import (
    apply_document_analysis_options,
    build_document_analysis_report,
    normalize_analysis_options,
)
from functions_native_tabular_compute import (
    NATIVE_TABULAR_DATA_ONLY,
    NATIVE_TABULAR_RESULT_VERSION,
    native_compute_bytes,
    native_compute_handle,
    validate_native_compute_handle,
)


NATIVE_PENDING_STATES = {
    "pending", "queued", "running", "retrying", "processing", "finalizing",
    "publishing", "gate_disabled", "continuation_unavailable",
}


class NativeTabularResultReader:
    """Complete native checkpoints with fresh owner/source checks per batch."""

    def __init__(self, engine, run, output_name, *, require_current_sources=False):
        self._engine = engine
        self._handle = native_compute_handle(run)
        self._producer = deepcopy(run["compute_context"]["producer"])
        self._manifest = deepcopy(run["native_result_manifest"])
        self._output_name = output_name
        self._require_current_sources = require_current_sources
        descriptor = self._manifest["outputs"][output_name]
        self.kind = descriptor["kind"]
        self.columns = tuple(deepcopy(descriptor.get("columns") or []))
        self.schema = tuple(column["name"] for column in self.columns)
        self.item_count = descriptor["item_count"]
        self.sources = deepcopy(run["compute_context"]["sources"])
        self.coverage = deepcopy(self._manifest["coverage"])
        self.completeness = {
            "status": "complete", "expected_count": self.item_count, "actual_count": self.item_count,
            "coverage": deepcopy(self.coverage), "validation": "valid",
            "checks": list(self._manifest["checks"]), "preview": False,
            "limitations": list(self._manifest.get("limitations") or []),
        }

    def _load(self):
        run = _load_native_compute_run(
            self._engine, user_id=self._producer["user_id"],
            conversation_id=self._producer["conversation_id"], handle=self._handle,
            producer=self._producer, require_current_sources=self._require_current_sources,
        )
        if (
            run.get("status") != "completed" or run.get("computation_state") != "complete"
            or run.get("native_result_manifest") != self._manifest
        ):
            raise AnalysisResultUnavailable("native_compute_result_changed")
        return run

    def iter_records(self):
        if self.kind != "records-v1":
            raise ValueError("The native result does not contain records.")
        run = self._load()
        expected = self._manifest["outputs"][self._output_name]
        digest = hashlib.sha256()
        digest.update(b"[")
        size_bytes, count = 2, 0
        for row in self._engine.iter_tabular_output_records(run, check_callback=self._load):
            encoded = native_compute_bytes(row)
            if count:
                digest.update(b",")
                size_bytes += 1
            digest.update(encoded)
            size_bytes += len(encoded)
            count += 1
            yield row
        digest.update(b"]")
        self._load()
        if (
            count != expected["item_count"] or size_bytes != expected["size_bytes"]
            or digest.hexdigest() != expected["content_sha256"]
        ):
            raise ValueError("The complete native result failed its integrity check.")

    def read_value(self, *, max_bytes=8 * 1024 * 1024):
        if self.kind != "structured-v1":
            raise ValueError("The native result does not contain a structured value.")
        run = self._load()
        expected = self._manifest["outputs"][self._output_name]
        if type(max_bytes) is not int or max_bytes < 0 or expected["size_bytes"] > max_bytes:
            raise ValueError("The native result exceeds the requested read limit.")
        value = self._engine._download_json_blob(self._engine._analysis_final_blob_path(
            run["user_id"], run["conversation_id"], run["id"],
        ))
        encoded = native_compute_bytes(value)
        self._load()
        if (
            len(encoded) != expected["size_bytes"]
            or hashlib.sha256(encoded).hexdigest() != expected["content_sha256"]
        ):
            raise ValueError("The complete native result failed its integrity check.")
        return value

    def iter_value_bytes(self):
        yield native_compute_bytes(self.read_value())


def _load_native_compute_run(
    engine, *, user_id, conversation_id, handle, producer, require_current_sources,
):
    validate_native_compute_handle(handle, producer)
    if producer["user_id"] != user_id or producer["conversation_id"] != conversation_id:
        raise AnalysisResultUnavailable("native_compute_owner_unavailable")
    try:
        run = engine._read_run(user_id, handle["job_id"])
    except CosmosResourceNotFoundError as exc:
        raise AnalysisResultUnavailable("native_compute_result_unavailable") from exc
    if (
        not isinstance(run, dict) or run.get("user_id") != user_id
        or run.get("conversation_id") != conversation_id
        or run.get("execution_policy") != NATIVE_TABULAR_DATA_ONLY
        or (run.get("compute_context") or {}).get("producer") != producer
        or native_compute_handle(run) != handle
    ):
        raise AnalysisResultUnavailable("native_compute_identity_invalid")
    engine._authorize_tabular_export_run_execution(
        run, require_current_sources=require_current_sources, require_active_producer=False,
    )
    if require_current_sources:
        engine._get_versioned_source_blob_client(run["source_descriptor"])
    return run


def _validate_native_result_manifest(engine, run):
    manifest = run.get("native_result_manifest")
    expected_outputs = {
        "structured_export": {"records"},
        "hierarchical_analysis": {"analysis"},
        "combined": {"records", "analysis"},
    }.get(run.get("task_type"))
    if (
        run.get("computation_state") != "complete" or not isinstance(manifest, dict)
        or set(manifest) != {"version", "outputs", "coverage", "checks", "limitations"}
        or manifest["version"] != NATIVE_TABULAR_RESULT_VERSION
        or not isinstance(manifest["outputs"], dict) or set(manifest["outputs"]) != expected_outputs
        or not isinstance(manifest["checks"], list) or not manifest["checks"]
        or any(not isinstance(check, str) or not check for check in manifest["checks"])
        or not isinstance(manifest["limitations"], list)
        or any(not isinstance(item, str) for item in manifest["limitations"])
        or any(type(run.get(field)) is not int or run[field] < 0 for field in ("row_count", "batch_count"))
        or manifest["coverage"] != {
            "expected": run.get("batch_count"), "completed": run.get("batch_count"), "unit": "work_units",
        }
        or run.get("completed_batches") != run.get("batch_count")
        or run.get("processed_rows") != run.get("row_count")
    ):
        raise ValueError("The native computation has no validated complete result.")
    for name, output in manifest["outputs"].items():
        fields = {"kind", "item_count", "size_bytes", "content_sha256"}
        if name == "records":
            fields.add("columns")
        if (
            not isinstance(output, dict) or set(output) != fields
            or output["kind"] != ("records-v1" if name == "records" else "structured-v1")
            or type(output["item_count"]) is not int
            or output["item_count"] != (run["row_count"] if name == "records" else 1)
            or type(output["size_bytes"]) is not int or output["size_bytes"] < 2
            or not isinstance(output["content_sha256"], str)
            or re.fullmatch(r"[a-f0-9]{64}", output["content_sha256"]) is None
        ):
            raise ValueError("The native output descriptor is invalid.")
        if name == "records":
            columns = output["columns"]
            if not isinstance(columns, list) or not columns:
                raise ValueError("The native output schema is invalid.")
            for column in columns:
                if (
                    not isinstance(column, dict) or set(column) != {"name", "value_type", "nullable"}
                    or not isinstance(column["name"], str) or not column["name"]
                    or column["value_type"] not in {"string", "integer", "number", "boolean", "object", "array", "json"}
                    or type(column["nullable"]) is not bool
                ):
                    raise ValueError("The native output schema is invalid.")
            names = [column["name"] for column in columns]
            if len(set(names)) != len(names) or names != engine._get_tabular_run_serialized_public_schema(run):
                raise ValueError("The native output schema is invalid.")
    return manifest


def open_native_tabular_result(
    *, user_id, conversation_id, handle, producer, require_current_sources=False,
):
    """Open a native computation, never an artifact card or publication preview."""
    # The native engine requires bootstrap-owned clients; readers load it only
    # at the runtime boundary and never import a Flask route or construct an app.
    import functions_tabular_generated_exports as engine

    run = _load_native_compute_run(
        engine, user_id=user_id, conversation_id=conversation_id, handle=handle,
        producer=producer, require_current_sources=require_current_sources,
    )
    status = str(run.get("status") or "").lower()
    if status != "completed":
        if status in NATIVE_PENDING_STATES:
            status = "pending"
        elif status in {"canceled", "cancelled"}:
            status = "cancelled"
        elif status != "failed":
            raise ValueError("The native computation state is invalid.")
        return {"status": status, "handle": deepcopy(handle), "reader": None, "readers": {}}
    manifest = _validate_native_result_manifest(engine, run)
    readers = {
        name: NativeTabularResultReader(engine, run, name, require_current_sources=require_current_sources)
        for name in manifest["outputs"]
    }
    return {
        "status": "completed", "handle": deepcopy(handle),
        "reader": readers.get("records") or readers.get("analysis"), "readers": readers,
    }


def _identity(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))
    return "native-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_native_analysis_output(user_id, conversation_id, run_id, source):
    """Reuse the native run and validated output readers without resuming any work."""
    # The native engine needs bootstrap-owned storage and model clients.
    from functions_tabular_generated_exports import (
        _analysis_final_blob_path,
        _authorize_tabular_export_run_execution,
        _build_public_artifact_projection,
        _download_json_blob,
        _read_run,
        _revalidate_tabular_source_version_for_publication,
        _write_ordered_output_stream,
    )

    run = _read_run(user_id, run_id)
    if (
        not isinstance(run, dict) or run.get("id") != run_id or run.get("user_id") != user_id
        or run.get("conversation_id") != conversation_id
    ):
        raise AnalysisResultUnavailable("analysis_native_identity_invalid")
    _authorize_tabular_export_run_execution(run)
    native_source = run.get("source_descriptor") or run.get("source_authorization") or {}
    source_scope = {"workspace": "personal", "group": "group", "public": "public", "chat": "chat"}.get(
        native_source.get("source")
    )
    if (
        run.get("source_file_name") != source.get("file_name")
        or (native_source.get("document_id") and native_source["document_id"] != source["document_id"])
        or (source_scope and source_scope != source.get("scope"))
        or (
            source_scope in {"group", "public"} and native_source.get("scope_id") != source.get("scope_id")
        )
    ):
        raise AnalysisResultUnavailable("analysis_native_source_mismatch")
    state = str(run.get("status") or "unsupported").lower()
    if state != "completed":
        return {"status": state, "run_id": run_id}
    if source_scope is None:
        return {"status": "unsupported", "run_id": run_id}
    _revalidate_tabular_source_version_for_publication(run)
    artifact_set = run.get("artifact_set_manifest") or {}
    if artifact_set.get("lifecycle_state") not in (None, "completed"):
        return {"status": "failed", "run_id": run_id}

    task_type = run.get("task_type") or "structured_export"
    if task_type == "hierarchical_analysis":
        value = _download_json_blob(_analysis_final_blob_path(user_id, conversation_id, run_id))
        if not isinstance(value, dict) or not isinstance(value.get("summary"), str):
            raise ValueError("The native final analysis is unavailable.")
        if value.get("row_count") != run.get("row_count"):
            raise ValueError("The native final analysis has incomplete row coverage.")
        kind = "native_final"
    elif task_type in {"structured_export", "combined"}:
        with io.StringIO() as output:
            count = _write_ordered_output_stream({**run, "output_format": "json"}, output)
            value = json.loads(output.getvalue())
        if not isinstance(value, list) or count != len(value):
            raise ValueError("The native final output could not be read completely.")
        kind = "records"
    else:
        return {"status": "unsupported", "run_id": run_id}
    artifacts = {}
    for artifact in (
        list(run.get("combined_artifacts") or []) + list(run.get("structured_export_artifacts") or [])
        + [run.get("analysis_artifact"), run.get("final_artifact")]
    ):
        if isinstance(artifact, dict) and artifact.get("artifact_message_id"):
            artifacts[artifact["artifact_message_id"]] = {
                **_build_public_artifact_projection(artifact),
                "conversation_id": conversation_id, "run_id": run_id, "export_run_id": run_id,
                "status": "completed", "background_export": False,
            }
    return {
        "status": "completed", "kind": kind, "value": value, "run_id": run_id,
        "source_row_count": run.get("row_count"), "completed_batches": run.get("completed_batches"),
        "batch_count": run.get("batch_count"), "plan_hash": run.get("plan_hash"), "artifacts": list(artifacts.values()),
    }


def collect_native_foreground_output(invocations):
    """Use the native full-query page contract, including a proven empty result."""
    # These helpers live on the native chat adapter, which imports the workflow runner.
    from route_backend_chats import (
        _build_tabular_generated_output_source_candidate,
        get_tabular_invocation_error_message,
        get_tabular_invocation_result_payload,
    )

    candidate = _build_tabular_generated_output_source_candidate(invocations)
    if candidate and candidate.get("full_result_available"):
        return {
            "status": "completed", "kind": "records", "value": candidate["rows"],
            "source_row_count": candidate["row_count"], "source_file_name": candidate.get("filename"),
            "source_authorization": candidate.get("source_authorization") or candidate.get("source_descriptor"),
        }
    for invocation in invocations:
        if get_tabular_invocation_error_message(invocation):
            continue
        payload = get_tabular_invocation_result_payload(invocation) or {}
        if (
            payload.get("data") == [] and type(payload.get("returned_rows")) is int
            and type(payload.get("total_matches")) is int
            and payload["returned_rows"] == payload["total_matches"] == 0
            and not payload.get("has_more") and not payload.get("start_row")
        ):
            metadata = getattr(getattr(invocation, "result", None), "internal_metadata", {}) or {}
            return {
                "status": "completed", "kind": "records", "value": [], "source_row_count": 0,
                "source_file_name": payload.get("filename"),
                "source_authorization": metadata.get("tabular_source_authorization"),
            }
    return None


def native_analysis_state(source, status, *, run_id=None):
    """A durable pending/unsupported reference is not an authoritative text result."""
    status = str(status or "unsupported").lower()
    pending = status in NATIVE_PENDING_STATES
    execution = "pending" if pending else "cancelled" if status in {"canceled", "cancelled"} else (
        "failed" if status == "failed" else "unsupported"
    )
    reply = (
        "Native tabular analysis is still processing. Its complete saved result is not ready."
        if pending else "Native tabular analysis was cancelled before a complete result was saved."
        if execution == "cancelled" else "Native tabular analysis failed before a complete result was saved."
        if execution == "failed" else
        "The native engine did not expose a complete final output for saved-result reuse. "
        "Its preview is not a dataset; use a full-source native output before explaining or publishing it."
    )
    document = {
        "document_id": source["document_id"], "file_name": source.get("file_name"),
        "total_windows": 1, "processed_windows": 0, "failed_windows": int(not pending),
        "status": execution,
    }
    return {
        "analysis_result_version": "analyze-final-v1", "analysis_sources": [deepcopy(source)],
        "authoritative_result": {"kind": "records", "value": []}, "analysis_evidence": [],
        "execution_status": execution, "reply": reply, "analysis_reply": reply,
        "document_ids": [source["document_id"]], "documents": [document],
        "coverage": {
            "document_count": 1, "total_windows": 1, "processed_windows": 0,
            "failed_windows": int(not pending), "documents": [document],
            "progress_meta": {"status": execution, "phase": execution, "phase_label": reply},
        },
        "analysis_validation": {"status": "pending" if pending else "invalid", "limitations": [reply]},
        "native_result_references": [{"run_id": run_id, "status": status}] if run_id else [],
    }


def adapt_native_analysis_result(
    *, user_id, conversation_id, source, generated_outputs=None, complete_output=None,
    native_reader=None, source_resolver=None, analysis_producer=None, bind_artifacts=None,
    analysis_options=None, transformation_spec=None,
):
    """Bind the engine's accepted rows/final document to the trusted source snapshot."""
    authorize_analysis_sources(user_id, [source], require_snapshot=True, resolver=source_resolver)
    options = normalize_analysis_options(analysis_options, transformation_spec)
    has_requirements = bool(options["required_fields"] or options["transformation_spec"])
    outputs = list(generated_outputs or [])
    native = deepcopy(complete_output) if isinstance(complete_output, dict) else None
    for output in outputs:
        run_id = output.get("export_run_id") or output.get("run_id")
        if run_id:
            native = (native_reader or read_native_analysis_output)(user_id, conversation_id, run_id, source)
            if native.get("status") != "completed":
                return native_analysis_state(source, native.get("status"), run_id=run_id)
            break
        status = str(output.get("status") or "").lower()
        if status in NATIVE_PENDING_STATES or status in {"failed", "canceled", "cancelled"}:
            return native_analysis_state(source, status)
    if not native or native.get("status") != "completed":
        return native_analysis_state(source, "unsupported")
    if not native.get("run_id"):
        authorization = native.get("source_authorization") or {}
        scope = {"workspace": "personal", "chat": "chat", "group": "group", "public": "public"}.get(
            authorization.get("source")
        )
        if not native.get("source_file_name") or scope is None:
            return native_analysis_state(source, "unsupported")
        if (
            native["source_file_name"] != source.get("file_name") or scope != source.get("scope")
            or (scope in {"group", "public"} and authorization.get("scope_id") != source.get("scope_id"))
        ):
            raise AnalysisResultUnavailable("analysis_native_source_mismatch")
    kind, value = native.get("kind"), native.get("value")
    if kind == "records" and isinstance(value, list) and all(isinstance(row, dict) for row in value):
        values = value
    elif kind == "native_final" and isinstance(value, dict):
        values = [value]
    else:
        raise ValueError("The native result has no complete supported output.")
    if native.get("artifacts") and analysis_producer and not has_requirements:
        # Bind native artifacts after their own lifecycle completes; the shared result commits next.
        from functions_saved_analysis import bind_native_analysis_artifacts

        (bind_artifacts or bind_native_analysis_artifacts)(
            user_id, conversation_id, native["run_id"], native["artifacts"], analysis_producer,
        )
    record_source = {
        key: deepcopy(source[key]) for key in (
            "document_id", "scope", "scope_id", "source_kind", "file_name", "source_version", "source_revision",
        ) if key in source
    }
    records = [{
        "record_id": _identity([source, native.get("run_id"), native.get("plan_hash"), index, row]),
        "document_id": source["document_id"], "source": record_source,
        "values": deepcopy(row), "evidence_refs": [],
        "native_output": {
            "run_id": native.get("run_id"), "record_number": index + 1, "kind": kind,
            "plan_hash": native.get("plan_hash"),
        },
    } for index, row in enumerate(values)]
    document = {
        "document_id": source["document_id"], "file_name": source.get("file_name"),
        "total_windows": 1, "processed_windows": 1, "failed_windows": 0, "status": "completed",
        "native_source_row_count": native.get("source_row_count"),
    }
    reply = (
        value["summary"] if kind == "native_final" else
        f"Saved {len(records)} complete native output record(s) from {source.get('file_name') or source['document_id']}."
    )
    result = {
        "analysis_result_version": "analyze-final-v1", "analysis_sources": [deepcopy(source)],
        "authoritative_result": {"kind": "records", "value": records}, "analysis_evidence": [],
        "reply": reply, "analysis_reply": reply, "execution_status": "succeeded",
        "document_ids": [source["document_id"]], "documents": [document],
        "coverage": {
            "document_count": 1, "total_windows": 1, "processed_windows": 1, "failed_windows": 0,
            "documents": [document], "progress_meta": {"status": "completed"},
        },
        "analysis_validation": {
            "status": "valid",
            "issues": [],
            "coverage": {
                "assigned_sources": 1, "completed_sources": 1,
                "assigned_work_units": native.get("batch_count") or 1,
                "completed_work_units": native.get("completed_batches") or 1,
                "failed_work_units": 0, "pending_work_units": 0,
            },
            "checks": [
                {"name": "complete_native_output", "status": "passed"},
                {"name": "factual_accuracy_and_entailment", "status": "not_performed"},
                {"name": "mathematical_correctness", "status": "not_performed"},
                {"name": "requested_field_completeness", "status": "not_performed"},
            ],
            "limitations": [
                "These are the complete saved native outputs, not an independent review of the original source.",
                "Native findings and reported counts are not independently fact-checked.",
                "Native query/output coverage does not establish that every possible source finding was identified.",
            ],
        },
        "analysis_diagnostics": {},
        "analysis_request": {"analysis_options": options},
        "native_result_references": [{"run_id": native["run_id"], "status": "completed"}] if native.get("run_id") else [],
        # Native files predate these additional rules. Regenerate projections from
        # the checked values rather than advertise an older, conflicting export.
        "generated_tabular_outputs": [] if has_requirements else native.get("artifacts") or outputs,
    }
    apply_document_analysis_options(result, options)
    result["analysis_reply"] = build_document_analysis_report(result)
    result["reply"] = result["analysis_reply"]
    return result
