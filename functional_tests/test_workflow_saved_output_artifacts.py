# test_workflow_saved_output_artifacts.py
"""
Functional tests for immutable, source-authorized workflow saved-output files.
Version: 0.261.127
Implemented in: 0.261.119

Use real Collect, journal, result stores, shared renderer/uploader, and authorized
download functions with private in-memory service doubles. No live Azure access.
"""

from contextlib import contextmanager, ExitStack
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
from importlib import import_module
import json
import mimetypes
import os
import sys
import tempfile
from types import SimpleNamespace
from typing import Any, Dict, Optional
from urllib.parse import quote
import uuid

from azure.core.exceptions import ResourceExistsError
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError
from flask import Flask, Response, g
import pytest
from werkzeug.utils import secure_filename

from test_analysis_artifact_publication import (
    artifact_sources, load_functions, publication, saved_analysis,
)
from test_workflow_for_each_execution import execute_loop, loop_definition, loop_runtime
from test_workflow_result_store import FakeBlobService
from functions_analysis_access import AnalysisResultUnavailable
from content_screening.contracts import DocumentHeldError
from functions_workflow_artifacts import (
    WorkflowRecordExportSource,
    authorize_workflow_saved_output_artifact,
    load_workflow_artifact_binding,
    materialize_workflow_saved_output,
)
from functions_workflow_bindings import WorkflowInputError
from functions_workflow_execution import workflow_execution_scope
from functions_workflow_identity import workflow_execution_id
from functions_workflow_node_results import open_workflow_record_input
from functions_workflow_result_store import WorkflowResultStore
from functions_workflow_runtime_store import WorkflowRuntimeLease
from functions_workflow_structured_execution import StructuredWorkflowExecution


class ArtifactBlobs:
    def __init__(self):
        self.data = {}
        self.writes = 0
        self.reads = []
        self.fail_after_upload = False
        self.read_hook = None

    def get_blob_client(self, *, container, blob):
        service, key = self, (container, blob)

        class Blob:
            def exists(self):
                return key in service.data

            def upload_blob(self, data, *, overwrite, **kwargs):
                if key in service.data and not overwrite:
                    raise ResourceExistsError("existing")
                assert hasattr(data, "read"), "The production upload must receive a bounded stream."
                service.data[key] = b"".join(iter(lambda: data.read(65536), b""))
                service.writes += 1
                if service.fail_after_upload:
                    service.fail_after_upload = False
                    raise TimeoutError("closed-fixture lost upload acknowledgement")

            def download_blob(self):
                assert key in service.data, "No missing blob may be silently recreated."

                def chunks():
                    content = service.data[key]
                    for offset in range(0, len(content), 4096):
                        service.reads.append(4096)
                        if service.read_hook:
                            service.read_hook()
                        yield content[offset:offset + 4096]

                return SimpleNamespace(chunks=chunks)

        return Blob()


@pytest.fixture
def artifact_services(publication, monkeypatch):
    services = publication
    blobs = ArtifactBlobs()
    state = {"workflow_allowed": True, "conversation_allowed": True, "workflow": None, "store": None}
    settings = {}
    services.conversations.put({"id": "conversation-1", "user_id": "owner"})
    operations_module = sys.modules["functions_simplechat_operations"]
    original_queue = services.module.queue_generated_document_processing

    def queue_content(**values):
        content = values["file_content_bytes"]
        if hasattr(content, "read"):
            content.seek(0)
            values = {**values, "file_content_bytes": content.read()}
        return original_queue(**values)

    monkeypatch.setattr(services.module, "queue_generated_document_processing", queue_content)

    def conversation_access(user_id, conversation):
        if user_id != "owner" or not state["conversation_allowed"]:
            raise PermissionError("closed-fixture conversation revoked")
        return {"is_owner": True}

    monkeypatch.setattr(services.module, "build_conversation_participation_context", conversation_access)

    def create_message(body):
        if body["id"] in services.messages.records:
            raise CosmosResourceExistsError(status_code=409, message="existing")
        return services.messages.put(body)

    monkeypatch.setattr(services.messages, "create_item", create_message, raising=False)
    namespace = {
        "Any": Any, "Dict": Dict, "Optional": Optional, "hashlib": hashlib,
        "datetime": datetime, "timezone": timezone, "os": os, "uuid": uuid, "tempfile": tempfile,
        "ResourceExistsError": ResourceExistsError, "CosmosResourceExistsError": CosmosResourceExistsError,
        "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
        "cosmos_conversations_container": services.conversations, "cosmos_messages_container": services.messages,
        "build_conversation_participation_context": conversation_access,
        "analysis_artifact_metadata": saved_analysis.analysis_artifact_metadata,
        "authorize_analysis_artifact": saved_analysis.authorize_analysis_artifact,
        "requires_generated_file_approval": lambda *args, **kwargs: False,
        "CLIENTS": {"storage_account_office_docs_client": blobs},
        "storage_account_personal_chat_container_name": "chat",
        "_get_latest_personal_thread_id": lambda *args: None,
        "_build_generated_chat_artifact_lifecycle_metadata": lambda *args, **kwargs: {},
        "_build_generated_chat_artifact_lifecycle_response": lambda *args: {},
        "_generated_artifact_has_lifecycle_contract": lambda metadata: False,
        "_normalize_generated_document_file_name": lambda value: value,
        "allowed_file": lambda name: name.endswith(".json"),
        "get_settings": lambda: settings,
        "TABULAR_EXTENSIONS": {"csv", "json"}, "log_event": lambda *args, **kwargs: None,
        **{name: getattr(artifact_sources, name) for name in (
            "generated_chat_artifact_address", "generated_artifact_source_metadata",
            "authorize_generated_artifact_preparation", "authorize_generated_artifact_source",
            "has_generated_artifact_source",
        )},
    }
    operations = load_functions("functions_simplechat_operations.py", {
        "upload_generated_file_artifact_stream_for_user", "_upload_generated_chat_artifact_for_current_user",
        "_verify_generated_artifact_blob", "open_generated_chat_artifact_stream",
        "assert_generated_chat_artifact_is_published_for_user",
        "_write_temp_generated_file", "queue_generated_document_processing",
    }, namespace)
    operations["open_generated_chat_artifact_stream"] = contextmanager(operations["open_generated_chat_artifact_stream"])
    for name in (
        "upload_generated_file_artifact_stream_for_user", "open_generated_chat_artifact_stream",
        "assert_generated_chat_artifact_is_published_for_user",
    ):
        monkeypatch.setattr(operations_module, name, operations[name], raising=False)
    monkeypatch.setattr(services.module, "assert_generated_chat_artifact_is_published_for_user",
                        operations["assert_generated_chat_artifact_is_published_for_user"])
    monkeypatch.setattr(sys.modules["config"], "storage_account_personal_chat_container_name", "chat", raising=False)

    def lookup(scope_id, workflow_id):
        workflow = state["workflow"]
        if not state["workflow_allowed"] or not workflow or workflow_id != workflow["id"]:
            return None
        if scope_id != (workflow.get("group_id") or workflow["user_id"]):
            return None
        return deepcopy(workflow)

    def run_lookup(scope_id, run_id):
        workflow = state["workflow"]
        if not workflow or run_id != "run" or not lookup(scope_id, workflow["id"]):
            return None
        return {"id": "run", "workflow_id": workflow["id"], "conversation_id": "conversation-1"}

    personal = sys.modules["functions_personal_workflows"]
    monkeypatch.setattr(personal, "get_personal_workflow", lookup, raising=False)
    monkeypatch.setattr(personal, "get_personal_workflow_run", run_lookup, raising=False)
    monkeypatch.setitem(sys.modules, "functions_group_workflows", SimpleNamespace(
        get_group_workflow=lookup, get_group_workflow_run=run_lookup,
    ))
    monkeypatch.setattr("functions_workflow_artifacts.workflow_runtime_store", lambda *args: state["store"])
    monkeypatch.setattr("functions_workflow_runtime_store.workflow_runtime_store", lambda *args: state["store"])

    route_namespace = {
        "Response": Response, "ExitStack": ExitStack, "hashlib": hashlib, "os": os,
        "mimetypes": mimetypes, "quote": quote, "secure_filename": secure_filename,
        "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
        "cosmos_conversations_container": services.conversations, "cosmos_messages_container": services.messages,
        "build_conversation_participation_context": conversation_access,
        "assert_generated_file_approval_allows_download": services.module.assert_generated_file_approval_allows_download,
        "assert_generated_chat_artifact_is_published_for_user": operations["assert_generated_chat_artifact_is_published_for_user"],
        "assert_evidence_available": lambda *args: None,
        "has_generated_artifact_source": artifact_sources.has_generated_artifact_source,
        "is_orchestration_artifact_source": artifact_sources.is_orchestration_artifact_source,
        "download_blob_content": lambda *args: pytest.fail("Generic files must not use a whole-byte download."),
    }
    routes = load_functions("route_enhanced_citations.py", {
        "_get_authorized_chat_artifact_message", "_serve_chat_artifact_download",
        "_normalize_response_file_name", "_build_content_disposition", "_resolve_generated_artifact_file_name",
    }, route_namespace)
    monkeypatch.setitem(sys.modules, "route_enhanced_citations", SimpleNamespace(
        _get_authorized_chat_artifact_message=routes["_get_authorized_chat_artifact_message"],
    ))
    monkeypatch.setitem(sys.modules, "functions_artifact_publication", services.module)

    def bind(workflow, store):
        state.update(workflow=workflow, store=store)

    return SimpleNamespace(
        publication=services, blobs=blobs, state=state, bind=bind, operations=operations,
        download=routes["_serve_chat_artifact_download"], settings=settings,
    )


@pytest.fixture
def saved_output_artifact(artifact_services, monkeypatch, request):
    options = getattr(request, "param", None) or {}
    definition = deepcopy(options.get("definition") or loop_definition())
    if options.get("group"):
        definition["group_id"] = "workflow-group"
    workflow, store, container, clock = loop_runtime(monkeypatch, definition=definition)
    if options.get("storage") == "blob":
        results = FakeBlobService()
        configured = lambda *args, **kwargs: WorkflowResultStore(container, results, "workflow-results")
        monkeypatch.setattr("functions_workflow_result_store._configured_store", configured)
        monkeypatch.setattr("functions_workflow_result_store._configured_result_store", configured)
    artifact_services.bind(workflow, store)
    rows = options.get("rows", [
        {"index": 0, "value": {"flag": False, "unicode": "\u03bb"}},
        {"index": 1, "middle-only": "exact-record-not-a-preview"},
        {"index": 0, "value": {"flag": False, "unicode": "\u03bb"}},
    ])
    # One admitted input may produce any complete output count within the existing byte quota.
    flow, calls = execute_loop(
        workflow, store, options.get("inputs", [{"seed": 1}]), result_for_item=lambda item: rows,
    )
    receipt = flow.final_outputs[0]
    if options.get("source_node"):
        receipt = receipt_for_node(workflow, store, options["source_node"])

    def materialize(**kwargs):
        with WorkflowRuntimeLease(store, owner_id="file-worker") as lease:
            execution = StructuredWorkflowExecution(store, lease, workflow, "run", settings=artifact_services.settings)
            with workflow_execution_scope(execution):
                return materialize_workflow_saved_output(
                    execution, receipt, actor_user_id="owner", conversation_id="conversation-1", **kwargs,
                )

    return SimpleNamespace(
        services=artifact_services, workflow=workflow, store=store, container=container,
        rows=rows, receipt=receipt, materialize=materialize, calls=calls, clock=clock,
    )


def receipt_for_node(workflow, store, node_id):
    saved = store.journal_read("attempt", [workflow_execution_id(workflow, "run", node_id), 1])["payload"]["workflow_result"]
    return open_workflow_record_input(
        workflow, "run", saved["producer"], saved["result_ref"], output_name="records", inspection=True,
    ).receipt


def partial_definition():
    definition = loop_definition()
    loop = definition["flow"]["nodes"][1]
    loop["body"]["nodes"][0]["run_when"] = {
        "op": "lt", "left": {"input": "item", "path": "/index"}, "right": {"literal": 1},
    }
    loop["body"]["outputs"][0]["required"] = False
    definition["flow"]["nodes"][2]["output_contract"].update(allow_partial=True, require_complete_coverage=False)
    definition["flow"]["outputs"][0]["allow_partial"] = True
    return definition


@pytest.mark.parametrize("saved_output_artifact", [{"storage": value} for value in ("cosmos", "blob")], indirect=True)
def test_collect_is_a_truthful_authorized_file_and_downloads_exact_bytes(saved_output_artifact):
    fixture, services = saved_output_artifact, saved_output_artifact.services
    artifact = fixture.materialize()
    binding = artifact["source_binding"]
    assert "task_id" not in binding["producer"]
    assert binding["producer"]["node_id"] == "collect"
    context = load_workflow_artifact_binding("owner", binding, for_publication=True)
    assert context["source"].reader.manifest["analysis_origin"] is False
    assert binding["source_receipt"]["result_ref"]["storage"] in {"cosmos", "blob"}
    message = services.publication.messages.records[artifact["artifact_message_id"]]
    assert "analysis_producer" not in message["metadata"]
    assert "analysis_result_required" not in message["metadata"]
    assert "generated_artifact_run_id" not in message["metadata"]
    expected = json.dumps(fixture.rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    response = services.download("owner", "conversation-1", artifact["artifact_message_id"])
    try:
        assert response.get_data() == expected
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Content-Disposition"].startswith("attachment;")
        assert int(response.headers["Content-Length"]) == len(expected)
    finally:
        response.close()
    assert artifact["content_sha256"] == hashlib.sha256(expected).hexdigest()
    assert fixture.materialize() == artifact
    assert services.blobs.writes == 1
    assert len(fixture.calls) == 2


@pytest.mark.parametrize("boundary", ["prepared_committed", "uploaded", "message_created", "ready_committed"])
def test_lost_acknowledgements_reuse_the_prepared_bytes_and_address(saved_output_artifact, monkeypatch, boundary):
    fixture, services = saved_output_artifact, saved_output_artifact.services
    if boundary == "uploaded":
        services.blobs.fail_after_upload = True
    elif boundary == "message_created":
        original = services.publication.messages.create_item

        def lose_message_ack(body):
            result = original(body)
            monkeypatch.setattr(services.publication.messages, "create_item", original)
            raise TimeoutError("closed-fixture lost message acknowledgement")

        monkeypatch.setattr(services.publication.messages, "create_item", lose_message_ack)
    else:
        original = fixture.store.journal_commit

        def lose_ready_ack(token, kind, key, payload, **kwargs):
            result = original(token, kind, key, payload, **kwargs)
            expected_key = "generated-file-prepare" if boundary == "prepared_committed" else "generated-file-ready"
            if key[0] == expected_key:
                monkeypatch.setattr(fixture.store, "journal_commit", original)
                raise TimeoutError("closed-fixture lost journal acknowledgement")
            return result

        monkeypatch.setattr(fixture.store, "journal_commit", lose_ready_ack)
    with pytest.raises(TimeoutError):
        fixture.materialize()
    artifact = fixture.materialize()
    assert services.blobs.writes == 1
    assert load_workflow_artifact_binding("owner", artifact["source_binding"])["descriptor"]["content_sha256"] == artifact["content_sha256"]


def test_uploaded_but_uncommitted_file_is_not_readable(saved_output_artifact, monkeypatch):
    fixture, services = saved_output_artifact, saved_output_artifact.services
    original = fixture.store.journal_commit

    def stop_before_ready(token, kind, key, payload, **kwargs):
        if key[0] == "generated-file-ready":
            raise TimeoutError("closed-fixture no ready checkpoint")
        return original(token, kind, key, payload, **kwargs)

    monkeypatch.setattr(fixture.store, "journal_commit", stop_before_ready)
    with pytest.raises(TimeoutError):
        fixture.materialize()
    message = next(value for value in services.publication.messages.records.values()
                   if value.get("metadata", {}).get("generated_artifact_source_required"))
    with pytest.raises(AnalysisResultUnavailable):
        services.download("owner", "conversation-1", message["id"])
    with pytest.raises(AnalysisResultUnavailable):
        services.publication.module._authorize_artifact("owner", "conversation-1", message["id"])


@pytest.mark.parametrize("change", ["workflow", "conversation", "approval", "source_binding", "descriptor", "bytes"])
def test_revocation_and_binding_corruption_fail_closed(saved_output_artifact, change):
    fixture, services = saved_output_artifact, saved_output_artifact.services
    artifact = fixture.materialize()
    message = services.publication.messages.records[artifact["artifact_message_id"]]
    if change == "workflow":
        services.state["workflow_allowed"] = False
    elif change == "conversation":
        services.state["conversation_allowed"] = False
    elif change == "approval":
        services.publication.state["artifact_approved"] = False
    elif change == "source_binding":
        message["metadata"].pop("generated_artifact_source")
    elif change == "descriptor":
        message["metadata"]["generated_artifact_source"]["materialization"]["descriptor_ref"]["sha256"] = "0" * 64
    else:
        services.blobs.data[(artifact["blob_container"], artifact["blob_path"])] = b"[]"
    with pytest.raises((AnalysisResultUnavailable, PermissionError, ValueError)):
        services.download("owner", "conversation-1", artifact["artifact_message_id"])


def test_revocation_during_download_never_returns_an_authorized_prefix(saved_output_artifact):
    fixture, services = saved_output_artifact, saved_output_artifact.services
    artifact = fixture.materialize()
    services.blobs.read_hook = lambda: services.state.update(workflow_allowed=False)
    with pytest.raises(AnalysisResultUnavailable):
        services.download("owner", "conversation-1", artifact["artifact_message_id"])


def test_new_file_identity_is_not_an_authorization_grant(saved_output_artifact):
    fixture = saved_output_artifact
    artifact = fixture.materialize()
    binding = artifact["source_binding"]
    with pytest.raises(AnalysisResultUnavailable):
        load_workflow_artifact_binding("other-user", binding)
    for field, changed in (("attempt", 2), ("execution_id", "0" * 64), ("node_id", "source-node"), ("task_id", "invented")):
        bad = deepcopy(binding)
        bad["producer"][field] = changed
        bad["source_receipt"]["producer"][field] = changed
        with pytest.raises((AnalysisResultUnavailable, ValueError)):
            load_workflow_artifact_binding("owner", bad)


def test_queue_copies_a_stream_not_its_python_representation(artifact_services):
    queued = []

    def queue(**kwargs):
        path = kwargs["temp_file_path"]
        try:
            with open(path, "rb") as content:
                queued.append(content.read())
        finally:
            os.remove(path)

    artifact_services.operations["_queue_document_upload_background_task"] = queue
    content = b'[{"actual":"stream bytes"}]'
    artifact_services.operations["queue_generated_document_processing"](
        "document", "owner", "records.json", io.BytesIO(content),
    )
    assert queued == [content]


@pytest.mark.parametrize("saved_output_artifact", [
    {"storage": storage, "rows": rows}
    for storage in ("cosmos", "blob")
    for rows in ([], [{"index": index} for index in range(501)],
                 [{"index": index, "payload": "x" * 8192} for index in range(1100)])
], indirect=True)
def test_real_collections_export_empty_large_and_more_records_than_the_input_limit(saved_output_artifact):
    fixture, services = saved_output_artifact, saved_output_artifact.services
    artifact = fixture.materialize()
    content = services.blobs.data[(artifact["blob_container"], artifact["blob_path"])]
    assert json.loads(content) == fixture.rows
    assert artifact["record_count"] == len(fixture.rows)
    if len(fixture.rows) == 1100:
        assert len(content) > 8 * 1024 * 1024
    assert len([call for call in fixture.calls if call[0] == "body"]) == 1
    assert services.blobs.writes == 1
    assert fixture.materialize() == artifact


@pytest.mark.parametrize("saved_output_artifact", [{"source_node": "source-node"}], indirect=True)
def test_real_task_records_use_the_same_adapter_with_their_actual_task_identity(saved_output_artifact):
    fixture = saved_output_artifact
    artifact = fixture.materialize()
    assert artifact["source_binding"]["producer"]["task_id"] == "source"
    assert artifact["source_binding"]["producer"]["node_id"] == "source-node"
    assert json.loads(fixture.services.blobs.data[(artifact["blob_container"], artifact["blob_path"])]) == [{"seed": 1}]


@pytest.mark.parametrize("saved_output_artifact", [
    {"definition": partial_definition(), "inputs": [{"seed": 1}, {"seed": 2}]},
], indirect=True)
def test_partial_collect_needs_explicit_acceptance_and_retains_coverage(saved_output_artifact):
    fixture, services = saved_output_artifact, saved_output_artifact.services
    with pytest.raises(ValueError):
        fixture.materialize()
    assert services.blobs.writes == 0
    artifact = fixture.materialize(allow_partial=True)
    assert artifact["validation_status"] == "accepted_partial"
    source = load_workflow_artifact_binding("owner", artifact["source_binding"], for_publication=True)["source"]
    assert source.reader.manifest["coverage"]["skipped_count"] == 1
    assert list(source.iter_records()) == fixture.rows
    message = services.publication.messages.records[artifact["artifact_message_id"]]
    assert "accepted_partial" in message["metadata"]["generated_artifact_summary"]


def test_duplicate_business_keys_remain_saved_but_are_never_exported(artifact_services, monkeypatch):
    definition = loop_definition()
    definition["flow"]["nodes"][2]["output_contract"]["identity_field"] = "business_id"
    workflow, store, _, _ = loop_runtime(monkeypatch, definition=definition)
    artifact_services.bind(workflow, store)
    with pytest.raises(WorkflowInputError):
        execute_loop(workflow, store, [{"business_id": "same"}, {"business_id": "same"}])
    receipt = receipt_for_node(workflow, store, "collect")
    for accepted_partial in (False, True):
        with WorkflowRuntimeLease(store, owner_id="file-worker") as lease:
            execution = StructuredWorkflowExecution(store, lease, workflow, "run")
            with workflow_execution_scope(execution), pytest.raises((ValueError, AnalysisResultUnavailable)):
                materialize_workflow_saved_output(
                    execution, receipt, actor_user_id="owner", conversation_id="conversation-1",
                    allow_partial=accepted_partial,
                )
    original = open_workflow_record_input(
        workflow, "run", receipt["producer"], receipt["result_ref"], output_name="records", inspection=True,
    )
    assert list(original.iter_records()) == [{"business_id": "same"}, {"business_id": "same"}]
    assert artifact_services.blobs.writes == 0


@pytest.mark.parametrize("extra", [0, 1])
def test_real_export_quota_is_exact_and_never_publishes_a_prefix(artifact_services, monkeypatch, extra):
    rows = [{"value": "x" * 8177} for _ in range(128)]
    encoded = lambda: json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    rows[-1]["value"] += "x" * (1024 * 1024 - len(encoded()) + extra)
    workflow, store, _, _ = loop_runtime(monkeypatch)
    artifact_services.bind(workflow, store)
    flow, _ = execute_loop(workflow, store, [{"seed": 1}], result_for_item=lambda item: rows)
    receipt = flow.final_outputs[0]
    artifact_services.settings["max_generated_chat_artifact_size_mb"] = 1
    with WorkflowRuntimeLease(store, owner_id="file-worker") as lease:
        execution = StructuredWorkflowExecution(store, lease, workflow, "run", settings=artifact_services.settings)
        with workflow_execution_scope(execution):
            if extra:
                with pytest.raises(ValueError, match="size limit"):
                    materialize_workflow_saved_output(
                        execution, receipt, actor_user_id="owner", conversation_id="conversation-1",
                    )
                assert artifact_services.blobs.writes == 0
            else:
                artifact = materialize_workflow_saved_output(
                    execution, receipt, actor_user_id="owner", conversation_id="conversation-1",
                )
                assert artifact_services.blobs.data[(artifact["blob_container"], artifact["blob_path"])] == encoded()
    reader = open_workflow_record_input(workflow, "run", receipt["producer"], receipt["result_ref"], output_name="records")
    assert list(reader.iter_records()) == rows
    assert artifact_services.publication.calls["create"] == []


@pytest.mark.parametrize("saved_output_artifact", [{"group": True}], indirect=True)
@pytest.mark.parametrize("revocation", ["membership", "group_status", "conversation"])
def test_group_source_scope_and_conversation_are_independent_current_grants(saved_output_artifact, revocation):
    fixture, services = saved_output_artifact, saved_output_artifact.services
    artifact = fixture.materialize()
    assert artifact["source_binding"]["scope"] == {"type": "group", "id": "workflow-group"}
    assert load_workflow_artifact_binding("owner", artifact["source_binding"])["source"].record_count == len(fixture.rows)
    if revocation == "membership":
        services.publication.state["group_role"] = None
    elif revocation == "group_status":
        services.publication.state["workspace_status"] = "inactive"
    else:
        services.state["conversation_allowed"] = False
    with pytest.raises((PermissionError, AnalysisResultUnavailable)):
        services.download("owner", "conversation-1", artifact["artifact_message_id"])


@pytest.mark.parametrize("saved_output_artifact", [{"rows": [{"index": index} for index in range(501)]}], indirect=True)
def test_workflow_revocation_during_serialization_stops_before_upload(saved_output_artifact, monkeypatch):
    fixture, services = saved_output_artifact, saved_output_artifact.services
    original = WorkflowRecordExportSource.iter_records
    read = []

    def revoke(source):
        for record in original(source):
            read.append(record)
            if len(read) == 100:
                services.state["workflow_allowed"] = False
            yield record

    monkeypatch.setattr(WorkflowRecordExportSource, "iter_records", revoke)
    with pytest.raises(AnalysisResultUnavailable):
        fixture.materialize()
    assert len(read) == 100 and services.blobs.writes == 0


def test_tombstoned_workflow_never_resurrects_its_saved_file(saved_output_artifact):
    fixture = saved_output_artifact
    artifact = fixture.materialize()
    fixture.store.tombstone()
    with pytest.raises(AnalysisResultUnavailable):
        fixture.services.download("owner", "conversation-1", artifact["artifact_message_id"])
    assert fixture.services.blobs.writes == 1


@pytest.mark.parametrize("target", ["source", "descriptor", "prepare", "ready", "attempt"])
def test_missing_bound_data_never_falls_back_to_previews_or_other_attempts(saved_output_artifact, target):
    fixture, services = saved_output_artifact, saved_output_artifact.services
    artifact = fixture.materialize()
    if target in {"source", "descriptor"}:
        reference = {
            "source": fixture.receipt["result_ref"],
            "descriptor": artifact["source_binding"]["materialization"]["descriptor_ref"],
        }[target]
        key = next(key for key, row in fixture.container.items.items()
                   if row.get("type") == "workflow_result_chunk" and row.get("sha256") == reference["sha256"])
    else:
        kind = "attempt" if target == "attempt" else "unit"
        unit = (
            [fixture.receipt["producer"]["execution_id"], fixture.receipt["producer"]["attempt"]]
            if target == "attempt" else [f"generated-file-{target}", artifact["source_binding"]["export_key"]]
        )
        row = fixture.store.journal_read(kind, unit)
        key = ("run", row["id"])
    del fixture.container.items[key]
    with pytest.raises((AnalysisResultUnavailable, LookupError, ValueError)):
        services.download("owner", "conversation-1", artifact["artifact_message_id"])
    assert services.blobs.writes == 1


def test_missing_collection_index_cannot_become_a_file(saved_output_artifact):
    fixture, services = saved_output_artifact, saved_output_artifact.services
    reference = fixture.receipt["output_ref"]
    key = next(key for key, row in fixture.container.items.items()
               if row.get("type") == "workflow_result_chunk" and row.get("sha256") == reference["sha256"])
    del fixture.container.items[key]
    with pytest.raises((AnalysisResultUnavailable, ValueError, CosmosResourceNotFoundError)):
        fixture.materialize()
    assert services.blobs.writes == 0


def test_changed_unacknowledged_blob_is_never_overwritten(saved_output_artifact):
    fixture, services = saved_output_artifact, saved_output_artifact.services
    services.blobs.fail_after_upload = True
    with pytest.raises(TimeoutError):
        fixture.materialize()
    key = next(iter(services.blobs.data))
    services.blobs.data[key] = b"changed"
    with pytest.raises(ValueError, match="different bytes"):
        fixture.materialize()
    assert services.blobs.writes == 1 and services.blobs.data[key] == b"changed"
    assert not any(row.get("metadata", {}).get("generated_artifact_source_required")
                   for row in services.publication.messages.records.values())


def test_deleted_file_message_is_not_recreated_by_ready_checkpoint_replay(saved_output_artifact):
    fixture, services = saved_output_artifact, saved_output_artifact.services
    artifact = fixture.materialize()
    del services.publication.messages.records[artifact["artifact_message_id"]]
    assert fixture.materialize() == artifact
    with pytest.raises(LookupError):
        services.download("owner", "conversation-1", artifact["artifact_message_id"])
    assert services.blobs.writes == 1
    assert artifact["artifact_message_id"] not in services.publication.messages.records


def history_messages(services, messages):
    history = load_functions("content_screening\\access.py", {"public_history_messages"}, {
        "Mapping": Mapping, "deepcopy": deepcopy, "import_module": import_module,
        "_current_user_id": lambda user: user,
        "refresh_workspace_attachment": lambda message, user: message,
        "assert_evidence_available": lambda *args, **kwargs: None,
        "assert_current_request_sources_available": lambda *args: None,
        "ScreeningError": DocumentHeldError,
    })["public_history_messages"]
    return history(messages, "owner")


def test_history_and_message_export_keep_only_authorized_public_file_metadata(saved_output_artifact):
    fixture, services = saved_output_artifact, saved_output_artifact.services
    artifact = fixture.materialize()
    message = deepcopy(services.publication.messages.records[artifact["artifact_message_id"]])
    message.update(file_content="PRIVATE_PREVIEW_CANARY", extracted_text="PRIVATE_PREVIEW_CANARY")
    card = {
        "capability": "file_export", "source_kind": "workflow_saved_output",
        "conversation_id": "conversation-1", "artifact_message_id": artifact["artifact_message_id"],
        "file_name": artifact["file_name"], "output_format": "json", "row_source": "saved_records",
        "row_count": len(fixture.rows), "storage_scope": "chat",
        "blob_path": artifact["blob_path"], "source_binding": artifact["source_binding"],
        "preview": "PRIVATE_PREVIEW_CANARY",
    }
    assistant = {"id": "reply", "conversation_id": "conversation-1", "role": "assistant",
                 "content": "Publication recorded.", "metadata": {"generated_tabular_outputs": [card]}}
    safe = history_messages(services, [message, assistant])
    encoded = json.dumps(safe)
    for private in ("PRIVATE_PREVIEW_CANARY", "generated_artifact_source", "source_binding", "blob_path",
                    "descriptor_ref", "iteration_path"):
        assert private not in encoded
    assert safe[1]["metadata"]["generated_tabular_outputs"][0]["row_count"] == len(fixture.rows)
    export = load_functions("route_backend_conversation_export.py", {"_load_export_message_for_user"}, {
        "Dict": Dict, "Any": Any,
        "cosmos_conversations_container": services.publication.conversations,
        "cosmos_messages_container": services.publication.messages,
        "analysis_result_contexts": saved_analysis.analysis_result_contexts,
        "load_saved_analysis": lambda *args: pytest.fail("Collect must not load a fabricated Analyze context."),
        "authorize_analysis_artifact": lambda *args: pytest.fail("The generic source must use its typed reader."),
        "public_history_messages": lambda messages, user: history_messages(services, messages),
        "DocumentHeldError": DocumentHeldError,
    })["_load_export_message_for_user"]
    exported = export("owner", "conversation-1", artifact["artifact_message_id"])
    assert "generated_artifact_source" not in json.dumps(exported)
    services.state["workflow_allowed"] = False
    hidden = history_messages(services, [message, assistant])
    assert hidden[0]["content_unavailable"]
    unavailable = hidden[1]["metadata"]["generated_tabular_outputs"][0]
    assert unavailable["status"] == "unavailable"
    assert "artifact_message_id" not in unavailable and "preview" not in unavailable
    with pytest.raises(AnalysisResultUnavailable):
        export("owner", "conversation-1", artifact["artifact_message_id"])


def test_withheld_card_restores_request_screening_context(saved_output_artifact, monkeypatch):
    fixture = saved_output_artifact
    artifact = fixture.materialize()
    message = {
        "id": "reply", "conversation_id": "conversation-1", "role": "assistant",
        "metadata": {"generated_tabular_outputs": [{
            "source_kind": "workflow_saved_output", "conversation_id": "conversation-1",
            "artifact_message_id": artifact["artifact_message_id"],
        }]},
    }

    def held(*args):
        g.content_screening_error = DocumentHeldError()
        g.content_screening_sources["withheld"] = {"unavailable": True}
        raise g.content_screening_error

    monkeypatch.setattr(sys.modules["route_enhanced_citations"], "_get_authorized_chat_artifact_message", held)
    with Flask(__name__).test_request_context():
        g.content_screening_error = None
        g.content_screening_sources = {"existing": {"available": True}}
        safe = artifact_sources.sanitize_generated_artifact_history(message, "owner")
        assert safe["metadata"]["generated_tabular_outputs"][0]["status"] == "unavailable"
        assert g.content_screening_error is None
        assert g.content_screening_sources == {"existing": {"available": True}}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
