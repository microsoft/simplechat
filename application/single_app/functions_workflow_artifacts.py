# functions_workflow_artifacts.py
"""Authorized workflow record sources and fenced shared-export materialization."""

from copy import deepcopy
import re

from azure.core.exceptions import ResourceNotFoundError
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from functions_analysis_access import AnalysisResultUnavailable
from functions_appinsights import log_event
from functions_generated_artifact_sources import generated_chat_artifact_address
from functions_generated_file_exports import GeneratedFileExportRequest, build_generated_file_export
from functions_workflow_definitions import workflow_definition_revision
from functions_workflow_identity import canonical_digest, workflow_execution_id, workflow_node_identity
from functions_workflow_node_results import open_workflow_record_input, result_selectors
from functions_workflow_result_store import _quota_bytes, load_workflow_node_result
from functions_workflow_runtime_store import WorkflowRuntimeConflict, workflow_runtime_store


EXPORT_CONTRACT = "generated-file-export-v1"
EXPORT_PROFILE = "exact_records_v1"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_RECEIPT_FIELDS = ("producer", "result_ref", "output_name", "output_ref")


def _source_receipt(value):
    if (
        not isinstance(value, dict) or not all(name in value for name in _RECEIPT_FIELDS)
        or not all(isinstance(value[name], dict) for name in ("producer", "result_ref", "output_ref"))
        or not isinstance(value["output_name"], str) or not value["output_name"]
    ):
        raise AnalysisResultUnavailable("generated_artifact_source_unbound")
    return {name: deepcopy(value[name]) for name in _RECEIPT_FIELDS}


def _scope(workflow):
    return {"type": "group" if workflow.get("group_id") else "personal",
            "id": workflow.get("group_id") or workflow["user_id"]}


def _export_key(workflow, receipt, allow_partial):
    return canonical_digest({
        "contract": EXPORT_CONTRACT, "workflow_scope": _scope(workflow),
        "definition_revision": workflow_definition_revision(workflow),
        **_source_receipt(receipt), "allow_partial": allow_partial,
        "profile": EXPORT_PROFILE, "output_format": "json",
    })


def _root_selectors(workflow, run_id):
    root = workflow["flow"]["id"]
    return {"node_id": root, "execution_id": workflow_execution_id(workflow, run_id, root),
            "iteration_path": [], "attempt": 1}


def validate_workflow_artifact_binding(value):
    if (
        not isinstance(value, dict) or value.keys() != {
            "version", "kind", "scope", "producer", "source_receipt", "allow_partial",
            "export_key", "profile", "output_format", "materialization",
        }
        or type(value.get("version")) is not int or value["version"] != 1
        or value.get("kind") != "workflow_saved_output"
        or value.get("profile") != EXPORT_PROFILE or value.get("output_format") != "json"
        or type(value.get("allow_partial")) is not bool
        or not isinstance(value.get("export_key"), str) or not _DIGEST.fullmatch(value["export_key"])
    ):
        raise AnalysisResultUnavailable("generated_artifact_source_unbound")
    scope, materialization = value["scope"], value["materialization"]
    if (
        not isinstance(scope, dict) or scope.keys() != {"type", "id"}
        or scope.get("type") not in {"personal", "group"}
        or not isinstance(scope.get("id"), str) or not scope["id"] or len(scope["id"]) > 1024
        or not isinstance(materialization, dict) or materialization.keys() != {"descriptor_ref"}
        or not isinstance(materialization["descriptor_ref"], dict)
        or value["producer"] != _source_receipt(value["source_receipt"])["producer"]
    ):
        raise AnalysisResultUnavailable("generated_artifact_source_unbound")
    producer = value["producer"]
    if not all(isinstance(producer.get(key), str) and producer[key] for key in (
        "workflow_id", "run_id", "node_id", "execution_id",
    )):
        raise AnalysisResultUnavailable("generated_artifact_source_unbound")
    return deepcopy(value)


def _authorize_workflow_scope(user_id, binding):
    # Application stores and current membership are resolved only at the access boundary.
    from functions_group import assert_group_role, check_group_status_allows_operation, find_group_by_id
    from functions_group_workflows import get_group_workflow, get_group_workflow_run
    from functions_personal_workflows import get_personal_workflow, get_personal_workflow_run

    scope, producer = binding["scope"], binding["producer"]
    if scope["type"] == "group":
        assert_group_role(user_id, scope["id"], allowed_roles=("Owner", "Admin", "DocumentManager", "User"))
        allowed, _ = check_group_status_allows_operation(find_group_by_id(scope["id"]), "view")
        if not allowed:
            raise AnalysisResultUnavailable("generated_artifact_source_unavailable")
        workflow = get_group_workflow(scope["id"], producer["workflow_id"])
        run = get_group_workflow_run(scope["id"], producer["run_id"])
    else:
        if scope["id"] != user_id:
            raise AnalysisResultUnavailable("generated_artifact_source_unavailable")
        workflow = get_personal_workflow(user_id, producer["workflow_id"])
        run = get_personal_workflow_run(user_id, producer["run_id"])
    if (
        not workflow or workflow.get("id") != producer["workflow_id"] or _scope(workflow) != scope
        or not run or run.get("id") != producer["run_id"] or run.get("workflow_id") != workflow["id"]
    ):
        raise AnalysisResultUnavailable("generated_artifact_source_unavailable")
    return workflow, run


class WorkflowRecordExportSource:
    kind = "records"

    def __init__(self, workflow, run_id, receipt, *, actor_user_id, store, allow_partial=False,
                 load_result=load_workflow_node_result, inspection=False):
        self.workflow, self.run_id, self.store = workflow, run_id, store
        self.actor_user_id = actor_user_id
        self.receipt = _source_receipt(receipt)
        self.allow_partial = allow_partial
        identity = self.receipt["producer"]
        expected = workflow_node_identity(
            workflow, run_id, identity.get("node_id"), identity.get("execution_id"), identity.get("attempt"),
            task_id=identity.get("task_id"), iteration_path=identity.get("iteration_path"),
        )
        if identity != expected:
            raise AnalysisResultUnavailable("generated_artifact_source_unbound")
        self._check_scope()
        self._check_attempt()
        self.reader = open_workflow_record_input(
            workflow, run_id, identity, self.receipt["result_ref"], output_name=self.receipt["output_name"],
            reader_user_id=actor_user_id, allow_partial=allow_partial, load_result=load_result, inspection=inspection,
        )
        if self.reader.kind != "records" or _source_receipt(self.reader.receipt) != self.receipt:
            raise AnalysisResultUnavailable("generated_artifact_source_unbound")
        self.record_count = self.reader.record_count

    def _check_attempt(self):
        identity = self.receipt["producer"]
        row = self.store.journal_read("attempt", [identity["execution_id"], identity["attempt"]])
        payload = row["payload"] if row else {}
        summary = payload.get("workflow_result") or {}
        if (
            payload.get("state") not in {"completed", "succeeded"}
            or any(payload.get(key) != identity.get(key) for key in (
                "node_id", "execution_id", "iteration_path", "attempt", "task_id",
            ))
            or summary.get("producer") != identity or summary.get("result_ref") != self.receipt["result_ref"]
        ):
            raise AnalysisResultUnavailable("generated_artifact_source_uncommitted")

    def _check_scope(self):
        _authorize_workflow_scope(self.actor_user_id, {
            "scope": _scope(self.workflow), "producer": self.receipt["producer"],
        })

    def recheck(self) -> None:
        self._check_scope()
        self._check_attempt()
        self.reader.recheck()

    def iter_records(self):
        for index, record in enumerate(self.reader.iter_records()):
            if index % 100 == 0:
                self._check_scope()
                self._check_attempt()
            yield record


def load_workflow_artifact_binding(user_id, value, *, require_ready=True, for_publication=False):
    try:
        return _load_workflow_artifact_binding(
            user_id, value, require_ready=require_ready, for_publication=for_publication,
        )
    except (ValueError, WorkflowRuntimeConflict, ResourceNotFoundError, CosmosResourceNotFoundError) as exc:
        log_event(
            "[SIMPLE_CHAT] Saved-output artifact source unavailable",
            {"exception_type": type(exc).__name__},
        )
        raise AnalysisResultUnavailable("generated_artifact_source_unavailable") from exc


def _load_workflow_artifact_binding(user_id, value, *, require_ready, for_publication):
    binding = validate_workflow_artifact_binding(value)
    workflow, run = _authorize_workflow_scope(user_id, binding)
    store = workflow_runtime_store(workflow, binding["producer"]["run_id"])
    workflow = store.run_definition()
    run_id, key = binding["producer"]["run_id"], binding["export_key"]
    if _scope(workflow) != binding["scope"] or key != _export_key(workflow, binding["source_receipt"], binding["allow_partial"]):
        raise AnalysisResultUnavailable("generated_artifact_source_unbound")
    source = WorkflowRecordExportSource(
        workflow, run_id, binding["source_receipt"], actor_user_id=user_id, store=store,
        allow_partial=binding["allow_partial"], inspection=not for_publication,
    )
    selectors = _root_selectors(workflow, run_id)
    reference = binding["materialization"]["descriptor_ref"]
    prepared = store.journal_read("unit", ["generated-file-prepare", key])
    expected_prepared = {"state": "completed", "selectors": selectors, "result_ref": reference}
    if not prepared or prepared["payload"] != expected_prepared:
        raise AnalysisResultUnavailable("generated_artifact_source_uncommitted")
    descriptor = load_workflow_node_result(workflow, run_id, None, reference, **selectors)
    if not isinstance(descriptor, dict):
        raise AnalysisResultUnavailable("generated_artifact_source_unbound")
    expected_source = {name: field for name, field in binding.items() if name != "materialization"}
    address = descriptor.get("artifact") or {}
    if (
        descriptor.get("contract_version") != EXPORT_CONTRACT or descriptor.get("source") != expected_source
        or address.get("conversation_id") != run.get("conversation_id")
        or not address.get("blob_container") or not address.get("conversation_id")
        or descriptor.get("record_count") != source.record_count
        or type(descriptor.get("size_bytes")) is not int or descriptor["size_bytes"] < 2
        or not isinstance(descriptor.get("content_sha256"), str) or not _DIGEST.fullmatch(descriptor["content_sha256"])
        or address != generated_chat_artifact_address(
            workflow["user_id"], address.get("conversation_id"), f"workflow-output-{key}.json",
            f"generated-export:v1:{key}", address.get("blob_container"),
        )
    ):
        raise AnalysisResultUnavailable("generated_artifact_source_unbound")
    if require_ready:
        ready = store.journal_read("unit", ["generated-file-ready", key])
        if not ready or ready["payload"] != {"state": "completed", "descriptor_ref": reference}:
            raise AnalysisResultUnavailable("generated_artifact_source_uncommitted")
    return {"binding": binding, "descriptor": descriptor, "source": source}


def authorize_workflow_saved_output_artifact(user_id, artifact, *, for_publication=False):
    metadata = artifact.get("metadata") or {}
    context = load_workflow_artifact_binding(
        user_id, metadata.get("generated_artifact_source"), for_publication=for_publication,
    )
    descriptor, binding = context["descriptor"], context["binding"]
    expected = descriptor["artifact"]
    if (
        artifact.get("id") != expected["artifact_message_id"]
        or artifact.get("filename") != expected["file_name"] or artifact.get("role") != "file"
        or any(artifact.get(key) != expected[key] for key in ("conversation_id", "blob_container", "blob_path"))
        or metadata.get("generated_artifact_content_sha256") != descriptor["content_sha256"]
        or metadata.get("generated_artifact_size_bytes") != descriptor["size_bytes"]
        or metadata.get("generated_artifact_output_format") != "json"
        or metadata.get("generated_artifact_idempotency_key") != f"generated-export:v1:{binding['export_key']}"
    ):
        raise AnalysisResultUnavailable("generated_artifact_source_unbound")
    return context


def materialize_workflow_saved_output(execution, receipt, *, actor_user_id, conversation_id,
                                      allow_partial=False, upload=None, artifact_container=None):
    """Commit a shared exact export without creating a task, scheduler, or publication ledger."""
    workflow, run_id = execution.workflow, execution.run_id
    execution.check()
    source = WorkflowRecordExportSource(
        workflow, run_id, receipt, actor_user_id=actor_user_id, store=execution.store,
        allow_partial=allow_partial, load_result=execution.load_result,
    )
    key = _export_key(workflow, source.receipt, allow_partial)
    prepared_key, ready_key = ["generated-file-prepare", key], ["generated-file-ready", key]
    prepared = execution.store.journal_read("unit", prepared_key)
    selectors = _root_selectors(workflow, run_id)
    descriptor, reference = None, None
    if prepared:
        if (
            prepared["payload"].get("state") != "completed" or prepared["payload"].get("selectors") != selectors
            or not isinstance(prepared["payload"].get("result_ref"), dict)
        ):
            raise AnalysisResultUnavailable("generated_artifact_source_unbound")
        reference = prepared["payload"]["result_ref"]
        descriptor = execution.load_result(workflow, run_id, None, reference, **selectors)
    if descriptor is None or execution.store.journal_read("unit", ready_key) is None:
        if artifact_container is None:
            # Reuse the configured private generated-file transport at materialization time.
            from config import storage_account_personal_chat_container_name

            artifact_container = storage_account_personal_chat_container_name
        if upload is None:
            from functions_simplechat_operations import upload_generated_file_artifact_stream_for_user

            upload = upload_generated_file_artifact_stream_for_user
        base_binding = {
            "version": 1, "kind": "workflow_saved_output", "scope": _scope(workflow),
            "producer": deepcopy(source.receipt["producer"]), "source_receipt": source.receipt,
            "allow_partial": allow_partial, "export_key": key, "profile": EXPORT_PROFILE, "output_format": "json",
        }
        with build_generated_file_export(
            source=source, export_request=GeneratedFileExportRequest("json", EXPORT_PROFILE),
            max_output_bytes=_quota_bytes(execution.settings), check=execution.check,
        ) as exported:
            candidate = {
                "contract_version": EXPORT_CONTRACT, "source": base_binding,
                "artifact": generated_chat_artifact_address(
                    workflow["user_id"], conversation_id, f"workflow-output-{key}.json",
                    f"generated-export:v1:{key}", artifact_container,
                ),
                "content_sha256": exported.content_sha256, "size_bytes": exported.size_bytes,
                "record_count": exported.record_count,
                "validation_status": (source.reader.manifest.get("workflow_validation") or {}).get("status"),
            }
            if descriptor is not None and candidate != descriptor:
                raise AnalysisResultUnavailable("generated_artifact_content_changed")
            if descriptor is None:
                descriptor = candidate
                reference = execution.save_result(
                    workflow, run_id, None, descriptor, settings=execution.settings, **selectors,
                )
                execution.store.journal_commit(execution.lease.token, "unit", prepared_key, {
                    "state": "completed", "selectors": selectors, "result_ref": reference,
                }, immutable=True)
            binding = {**base_binding, "materialization": {"descriptor_ref": reference}}
            execution.check()
            source.recheck()
            upload(
                actor_user_id, conversation_id, descriptor["artifact"]["file_name"],
                exported.file_content, exported.size_bytes, capability="file_export", output_format="json",
                summary=f"{exported.record_count} exact saved records ({descriptor['validation_status']}).",
                artifact_idempotency_key=f"generated-export:v1:{key}", generated_artifact_source=binding,
                execution_check=execution.check,
            )
            execution.check()
            source.recheck()
            execution.store.journal_commit(execution.lease.token, "unit", ready_key, {
                "state": "completed", "descriptor_ref": reference,
            }, immutable=True)
    binding = {**descriptor["source"], "materialization": {"descriptor_ref": reference}}
    load_workflow_artifact_binding(actor_user_id, binding, for_publication=True)
    source.recheck()
    execution.check()
    return {
        **descriptor["artifact"], "output_format": "json", "capability": "file_export",
        "record_count": descriptor["record_count"], "content_sha256": descriptor["content_sha256"],
        "validation_status": descriptor["validation_status"], "source_binding": binding,
    }
