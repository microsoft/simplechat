# test_analysis_artifact_publication.py
"""
Functional tests for explicit existing-artifact publication and retry receipts.
Version: 0.261.118
Implemented in: 0.261.109

Exercise real publication, normalization, and route bodies with Cosmos/queue
doubles. No Azure calls, model calls, temporary files, or result materialization.
"""

import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import threading
import types
from typing import Any, Dict, Iterable, Optional
import uuid

from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from flask import Flask, jsonify, request
import pytest

from test_support.app_stubs import import_app_module


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
saved_analysis = import_app_module("functions_saved_analysis")
definitions = import_app_module("functions_workflow_definitions")


def load_functions(filename, names, namespace):
    tree = ast.parse((APP / filename).read_text(encoding="utf-8"))
    selected = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(selected) == len(names)
    for node in selected:
        node.decorator_list = []
    exec(compile(ast.Module(body=selected, type_ignores=[]), filename, "exec"), namespace)
    return namespace


def normalizers():
    return load_functions("functions_personal_workflows.py", {
        "_normalize_text", "normalize_workflow_publication", "normalize_workflow_max_tasks", "_normalize_workflow_tasks",
    }, {
        "uuid": uuid, "WORKFLOW_TASK_LIMIT_DEFAULT": 50, "WORKFLOW_TASK_LIMIT_MIN": 1,
        "WORKFLOW_TASK_LIMIT_MAX": 100, "WORKFLOW_MAX_TASKS": 50,
        "WORKFLOW_TASK_INSTRUCTIONS_MAX_LENGTH": 12000, "WORKFLOW_TASK_NAME_MAX_LENGTH": 120,
        "WORKFLOW_TASK_RUNNER_TYPES": {"inherit", "agent", "model"},
        "normalize_publication_completion_policy": definitions.normalize_publication_completion_policy,
    })


class MemoryContainer:
    def __init__(self, *records):
        self.records = {}
        self.lock = threading.RLock()
        self.reads = 0
        self.writes = 0
        self.revision = 0
        self.lost_write = False
        for record in records:
            self.put(record)
        self.writes = 0

    def put(self, record):
        with self.lock:
            value = deepcopy(record)
            self.writes += 1
            self.revision += 1
            value["_etag"] = str(self.revision)
            self.records[value["id"]] = value
            return deepcopy(value)

    def read_item(self, item, partition_key):
        with self.lock:
            self.reads += 1
            if item not in self.records:
                raise CosmosResourceNotFoundError(status_code=404, message="missing")
            value = self.records[item]
            assert partition_key == value.get("conversation_id", value["id"])
            return deepcopy(value)

    def replace_item(self, item, body, etag, match_condition):
        with self.lock:
            if self.records[item]["_etag"] != etag:
                raise CosmosHttpResponseError(status_code=412, message="etag changed")
            result = self.put(body)
            if self.lost_write:
                self.lost_write = False
                raise TimeoutError("Provider acknowledgement lost")
            return result

    def query_items(self, *, parameters, **kwargs):
        parameters = {item["name"]: item["value"] for item in parameters}
        with self.lock:
            return [
                {"id": row["id"]} for row in self.records.values()
                if row["metadata"].get("publication_receipt_id") == parameters["@receipt"]
                and row["notification_type"] == parameters["@notification_type"]
            ]


@pytest.fixture
def publication(monkeypatch):
    content = b"# Accepted findings\n\nExact existing bytes: 12.3400\n"
    artifact = {
        "id": "artifact-1", "conversation_id": "conversation-1", "role": "file",
        "filename": "accepted.md", "file_content_source": "blob",
        "blob_container": "chat", "blob_path": "actor/conversation-1/accepted.md",
        "metadata": {
            "is_generated_chat_artifact": True,
            "generated_artifact_output_format": "markdown",
            "generated_artifact_content_sha256": hashlib.sha256(content).hexdigest(),
            **saved_analysis.analysis_artifact_metadata({
                "kind": "chat", "conversation_id": "conversation-1", "message_id": "assistant-1",
            }),
        },
    }
    parent = {
        "id": "assistant-1", "conversation_id": "conversation-1", "role": "assistant",
        "metadata": {"saved_analysis": {
            "conversation_id": "conversation-1", "message_id": "assistant-1", "result_sha256": "saved-digest",
            "binding": artifact["metadata"]["analysis_producer"],
        }},
    }
    messages = MemoryContainer(artifact)
    conversations = MemoryContainer({"id": "conversation-1", "user_id": "actor"})
    destinations = {scope: MemoryContainer() for scope in ("personal", "group", "public")}
    notifications = MemoryContainer()
    state = {
        "content": content, "execution": "succeeded", "validation": "valid", "source_allowed": True,
        "parents": [parent], "artifact_approved": True, "group_role": "User", "public_role": "DocumentManager",
        "workspace_status": "active", "failure": None, "create_hook": None,
    }
    calls = {"create": [], "update": [], "queue": [], "download": [], "notify": [], "group_auth": []}

    def install(name, **attributes):
        module = types.ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)

    def destination_for(values):
        scope = "group" if values.get("group_id") else "public" if values.get("public_workspace_id") else "personal"
        return destinations[scope]

    def create_document(**values):
        calls["create"].append(deepcopy(values))
        if state["create_hook"]:
            state["create_hook"]()
        if state["failure"] == "create_before":
            raise TimeoutError("Create not acknowledged")
        destination_for(values).put({"id": values["document_id"], "version": 1, **values})
        if state["failure"] == "create_after":
            raise TimeoutError("Create acknowledgement lost")

    def update_document(**values):
        calls["update"].append(deepcopy(values))
        container = destination_for(values)
        current = container.records[values["document_id"]]
        container.put({**current, **values})
        if state["failure"] == "prepare_after":
            raise TimeoutError("Update acknowledgement lost")

    def queue(**values):
        calls["queue"].append(deepcopy(values))
        if state["failure"] == "queue_after":
            raise TimeoutError("Dispatch acknowledgement lost")

    def download(container, path):
        calls["download"].append((container, path))
        return state["content"]

    def notify(**values):
        calls["notify"].append(deepcopy(values))
        is_workspace = values["notification_type"] == "approval_request_pending"
        if state["failure"] == "notification_unknown" and is_workspace:
            return None
        value = {"id": str(uuid.uuid4()), **values}
        notifications.put(value)
        if state["failure"] == "notification_after":
            return None
        return value

    def notify_workspace(target, kind, title, message, **kwargs):
        return notify(notification_type=kind, title=title, message=message, target=target, **kwargs)

    def check_conversation(user_id, conversation):
        if user_id != conversation["user_id"]:
            raise PermissionError("Conversation access denied")

    def check_artifact(*args):
        if not state["artifact_approved"]:
            raise PermissionError("Artifact is staged")

    def read_saved_result(user_id, context):
        assert user_id == "actor"
        assert context["result_sha256"] == "saved-digest"
        if not state["source_allowed"]:
            raise PermissionError("Contributing source access revoked")
        return {"execution": {"status": state["execution"]}, "validation": {"status": state["validation"]}}, None, {}

    def authorize_analysis(user_id, source, **kwargs):
        return saved_analysis.authorize_analysis_artifact(
            user_id, source, parents_loader=lambda *args: state["parents"],
            result_reader=read_saved_result, **kwargs,
        )

    def group_doc(group_id):
        return {"id": group_id, "name": "Fixed group", "status": state["workspace_status"]}

    group_helpers = load_functions("functions_group.py", {"assert_group_role", "check_group_status_allows_operation"}, {
        "Iterable": Iterable, "find_group_by_id": group_doc,
        "get_user_role_in_group": lambda doc, user: state["group_role"],
    })

    def assert_group_role(user, group, **kwargs):
        calls["group_auth"].append((user, group))
        return group_helpers["assert_group_role"](user, group, **kwargs)

    public_helpers = load_functions("functions_public_workspaces.py", {"check_public_workspace_status_allows_operation"}, {})
    install("config",
        cosmos_conversations_container=conversations, cosmos_messages_container=messages,
        cosmos_group_documents_container=destinations["group"], cosmos_user_documents_container=destinations["personal"],
        cosmos_public_documents_container=destinations["public"], cosmos_notifications_container=notifications,
    )
    install("functions_appinsights", log_event=lambda *args, **kwargs: None)
    install("functions_collaboration", build_conversation_participation_context=check_conversation)
    install("functions_documents", create_document=create_document, update_document=update_document,
        allowed_file=lambda name: name.endswith((".md", ".csv", ".json", ".xml", ".docx", ".pdf")))
    install("functions_generated_file_approvals", assert_generated_file_approval_allows_download=check_artifact)
    install("functions_group", assert_group_role=assert_group_role, find_group_by_id=group_doc,
        check_group_status_allows_operation=group_helpers["check_group_status_allows_operation"])
    install("functions_notifications", create_group_notification=notify_workspace,
        create_public_workspace_notification=notify_workspace, create_notification=notify)
    install("functions_personal_workflows", normalize_workflow_publication=normalizers()["normalize_workflow_publication"])
    install("functions_public_workspaces",
        find_public_workspace_by_id=lambda target: {"id": target, "name": "Fixed public", "status": state["workspace_status"]},
        get_user_role_in_public_workspace=lambda workspace, user: state["public_role"],
        check_public_workspace_status_allows_operation=public_helpers["check_public_workspace_status_allows_operation"],
    )
    install("functions_saved_analysis", authorize_analysis_artifact=authorize_analysis)
    install("functions_simplechat_operations", assert_generated_chat_artifact_is_published_for_user=check_artifact,
        download_blob_content=download, queue_generated_document_processing=queue)
    install("utils_cache", invalidate_group_search_cache=lambda *args: None, invalidate_personal_search_cache=lambda *args: None)
    spec = importlib.util.spec_from_file_location("publication_under_test", APP / "functions_artifact_publication.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return types.SimpleNamespace(
        module=module, state=state, calls=calls, messages=messages, destinations=destinations,
        notifications=notifications, conversations=conversations, artifact=artifact,
    )


def publish(fixture, scope="personal", **kwargs):
    destination = {"workspace_scope": scope}
    if scope != "personal":
        destination["group_id" if scope == "group" else "public_workspace_id"] = f"fixed-{scope}"
    return fixture.module.publish_generated_chat_artifact_for_user(
        "actor", conversation_id="conversation-1", message_id="artifact-1",
        destination=destination, request_id="workflow-real:run-real:publication-task-real", **kwargs,
    )


def test_no_intent_has_no_reads_writes_or_model_work(publication):
    result = publication.module.publish_workflow_analysis_artifact(
        "actor", publication=None, artifact_reference=None, request_id=None,
    )
    assert result["publication"]["state"] == "not_requested"
    assert result["model_calls"] == 0
    assert all(not calls for calls in publication.calls.values())
    assert publication.messages.reads == 0
    assert publication.messages.writes == 0


def test_personal_publication_reuses_bytes_and_receipt(publication):
    first = publish(publication)
    second = publish(publication)
    assert first["publication"] == second["publication"]
    assert first["publication"]["state"] == "queued"
    assert len(publication.calls["create"]) == len(publication.calls["queue"]) == 1
    assert len(publication.calls["download"]) == 1
    assert publication.calls["queue"][0]["file_content_bytes"] == publication.state["content"]
    assert not publication.calls["notify"]
    document = next(iter(publication.destinations["personal"].records.values()))
    assert not any(field.startswith("analysis_") for field in document)


@pytest.mark.parametrize("scope", ["group", "public"])
def test_shared_destinations_create_pending_approvals_once(publication, scope):
    first = publish(publication, scope)
    second = publish(publication, scope)
    assert first["publication"] == second["publication"]
    assert first["publication"]["state"] == "pending_approval"
    assert first["approval_required"] is True
    assert len(publication.calls["create"]) == 1
    assert len(publication.calls["notify"]) == 2
    assert not publication.calls["queue"]
    document = next(iter(publication.destinations[scope].records.values()))
    assert document["generated_artifact_source_blob_path"] == publication.artifact["blob_path"]
    assert document["generated_artifact_promotion_status"] == "pending_approval"
    assert not any(field.startswith("analysis_") for field in document)


@pytest.mark.parametrize("scope,role", [("group", None), ("group", "Reader"), ("public", "User"), ("public", None)])
def test_destination_roles_are_checked_before_side_effects(publication, scope, role):
    publication.state[f"{scope}_role"] = role
    with pytest.raises(PermissionError):
        publish(publication, scope)
    assert not publication.calls["create"]
    assert not publication.calls["download"]
    assert not publication.calls["notify"]
    assert publication.messages.writes == 0


@pytest.mark.parametrize("scope", ["group", "public"])
@pytest.mark.parametrize("status", ["inactive", "locked", "upload_disabled"])
def test_destination_status_is_rechecked(publication, scope, status):
    publication.state["workspace_status"] = status
    with pytest.raises(PermissionError):
        publish(publication, scope)
    assert not publication.calls["create"]


@pytest.mark.parametrize("execution,validation", [
    ("pending", "valid"), ("running", "valid"), ("failed", "valid"), ("partial", "valid"),
    ("succeeded", "pending"), ("succeeded", "partial"), ("succeeded", "invalid"), ("succeeded", "not_validated"),
])
def test_only_valid_succeeded_final_results_can_be_published(publication, execution, validation):
    publication.state.update(execution=execution, validation=validation)
    with pytest.raises(PermissionError):
        publish(publication)
    assert not publication.calls["create"]
    assert not publication.calls["download"]
    assert publication.messages.writes == 0


def test_unregistered_projections_and_staged_artifacts_are_blocked(publication):
    publication.state["parents"] = []
    with pytest.raises(PermissionError):
        publish(publication)
    publication.state["artifact_approved"] = False
    with pytest.raises(PermissionError):
        publish(publication)
    assert not publication.calls["create"]


def test_source_revocation_blocks_republication_not_existing_destination_copy(publication):
    result = publish(publication)
    destination_id = result["document"]["id"]
    publication.state["source_allowed"] = False
    with pytest.raises(PermissionError):
        publish(publication)
    destination = publication.destinations["personal"].read_item(destination_id, destination_id)
    assert destination["user_id"] == "actor"
    assert "analysis_result_required" not in destination
    assert len(publication.calls["create"]) == len(publication.calls["queue"]) == 1


@pytest.mark.parametrize("failure", ["create_after", "prepare_after", "notification_after"])
def test_lost_acknowledgements_reconcile_without_duplicate_approvals(publication, failure):
    publication.state["failure"] = failure
    first = publish(publication, "group")
    second = publish(publication, "group")
    assert first["publication"]["state"] == second["publication"]["state"] == "pending_approval"
    assert len(publication.calls["create"]) == 1
    assert len(publication.calls["notify"]) == 2


def test_unconfirmed_notification_is_not_blindly_repeated(publication):
    publication.state["failure"] = "notification_unknown"
    first = publish(publication, "group")
    publication.state["failure"] = None
    second = publish(publication, "group")
    assert first["publication"]["state"] == second["publication"]["state"] == "uncertain"
    assert second["publication"]["unresolved_stages"] == ["workspace_notification"]
    assert len(publication.calls["create"]) == 1
    assert len(publication.calls["notify"]) == 2


def test_unconfirmed_create_and_conditional_write_do_not_grant_a_retry_copy(publication):
    publication.messages.lost_write = True
    with pytest.raises(TimeoutError):
        publish(publication)
    assert not publication.calls["create"]
    publication.state["failure"] = "create_before"
    first = publish(publication)
    publication.state["failure"] = None
    second = publish(publication)
    assert first["publication"]["state"] == second["publication"]["state"] == "uncertain"
    assert len(publication.calls["create"]) == 1
    assert not publication.calls["queue"]


def test_lost_queue_ack_stays_explicit_until_destination_confirms_processing(publication):
    publication.state["failure"] = "queue_after"
    first = publish(publication)
    second = publish(publication)
    assert first["publication"]["state"] == second["publication"]["state"] == "uncertain"
    assert second["publication"]["unresolved_stages"] == ["queue"]
    assert len(publication.calls["queue"]) == 1
    document = publication.destinations["personal"].records[first["document"]["id"]]
    document["status"] = "Processing complete"
    third = publish(publication)
    assert third["publication"]["state"] == "queued"
    assert len(publication.calls["queue"]) == 1


@pytest.mark.parametrize("scope", ["personal", "group", "public"])
def test_concurrent_requests_claim_only_one_destination_copy(publication, scope):
    created = threading.Event()
    release = threading.Event()

    def pause_create():
        created.set()
        assert release.wait(5)

    publication.state["create_hook"] = pause_create
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(publish, publication, scope)
        assert created.wait(5)
        try:
            concurrent = publish(publication, scope)
            assert concurrent["publication"]["state"] == "uncertain"
        finally:
            release.set()
        result = first.result(timeout=5)
    again = publish(publication, scope)
    assert result["publication"] == again["publication"]
    assert len(publication.calls["create"]) == 1
    assert len(publication.calls["queue"]) == (1 if scope == "personal" else 0)
    assert len(publication.calls["notify"]) == (0 if scope == "personal" else 2)


def test_altered_bytes_cannot_create_a_workspace_document(publication):
    publication.state["content"] = b"not the accepted artifact"
    with pytest.raises(ValueError):
        publish(publication, "group")
    assert not publication.calls["create"]
    assert not publication.calls["notify"]


def test_deleted_or_denied_request_is_not_resubmitted(publication):
    first = publish(publication, "group")
    publication.destinations["group"].records.clear()
    publication.notifications.records.clear()
    second = publish(publication, "group")
    assert first["document"]["id"] == second["document"]["id"]
    assert second["publication"]["state"] == "uncertain"
    assert len(publication.calls["create"]) == 1
    assert len(publication.calls["notify"]) == 2


def test_workflow_uses_fixed_destination_and_existing_format_without_a_model(publication):
    result = publication.module.publish_workflow_analysis_artifact(
        "actor", publication={"artifact_format": "markdown", "workspace_scope": "group", "group_id": "configured-group"},
        artifact_reference={"conversation_id": "conversation-1", "artifact_message_id": "artifact-1"},
        request_id="workflow-actual/run-actual/task-actual",
    )
    assert result["execution_status"] == "succeeded"
    assert result["model_calls"] == 0
    assert result["publication"]["destination"]["group_id"] == "configured-group"
    assert publication.calls["group_auth"]
    assert set(publication.calls["group_auth"]) == {("actor", "configured-group")}
    assert publication.calls["create"][0]["group_id"] == "configured-group"
    assert result["authoritative_result"]["value"]["publication"] == result["publication"]


def test_missing_format_never_invokes_export_or_reconstruction(publication):
    with pytest.raises(ValueError, match="not available"):
        publication.module.publish_workflow_analysis_artifact(
            "actor", publication={"artifact_format": "csv", "workspace_scope": "personal"},
            artifact_reference={"conversation_id": "conversation-1", "artifact_message_id": "artifact-1"}, request_id="request",
        )
    assert not publication.calls["create"]
    assert not publication.calls["download"]


def test_access_is_rechecked_after_reading_existing_artifact_bytes(publication, monkeypatch):
    def revoke_during_download(*args):
        publication.state["source_allowed"] = False
        return publication.state["content"]

    monkeypatch.setattr(publication.module, "download_blob_content", revoke_during_download)
    with pytest.raises(PermissionError):
        publish(publication)
    assert not publication.calls["create"]
    assert not publication.calls["queue"]
    assert publication.messages.writes == 0


def test_revocation_after_shell_creation_prevents_processing_and_approval(publication):
    publication.state["create_hook"] = lambda: publication.state.update(source_allowed=False)
    with pytest.raises(PermissionError):
        publish(publication, "group")
    assert len(publication.calls["create"]) == 1
    assert not publication.calls["update"]
    assert not publication.calls["notify"]
    publication.state["create_hook"] = None
    publication.state["source_allowed"] = True
    assert publish(publication, "group")["publication"]["state"] == "pending_approval"
    assert len(publication.calls["create"]) == 1


@pytest.mark.parametrize("destination", [{}, {"workspace_scope": "group"}, {"workspace_scope": "public"}])
def test_missing_explicit_destination_is_rejected(publication, destination):
    with pytest.raises(ValueError):
        publication.module.publish_generated_chat_artifact_for_user(
            "actor", conversation_id="conversation-1", message_id="artifact-1", destination=destination, request_id="request",
        )
    assert not publication.calls["create"]


def test_task_normalization_keeps_ordinary_tasks_and_persists_explicit_publication():
    normalize = normalizers()["_normalize_workflow_tasks"]
    ordinary = {"id": "analyze", "name": "Analyze", "instructions": "Explain the risks."}
    task = {"id": "publish", "publication": {
        "artifact_format": "markdown", "workspace_scope": "group", "group_id": "fixed-group",
    }}
    normalized = normalize({"tasks": [ordinary, task]})
    assert "publication" not in normalized[0]
    assert normalized[1]["publication"] == {
        "artifact_format": "md", "workspace_scope": "group", "group_id": "fixed-group",
    }
    assert normalized[1]["runner"] == {"type": "inherit"}
    assert normalize({}, existing_workflow={"tasks": normalized}) == normalized
    with pytest.raises(ValueError, match="before"):
        normalize({"tasks": [task]})


@pytest.mark.parametrize("config", [
    {}, True, {"artifact_format": "md"}, {"artifact_format": "md", "workspace_scope": "group"},
    {"artifact_format": "md", "workspace_scope": "personal", "group_id": "unexpected"},
    {"artifact_format": "md", "workspace_scope": "personal", "instructions": "publish secretly"},
])
def test_publication_configuration_never_infers_missing_intent_or_destination(config):
    with pytest.raises(ValueError):
        normalizers()["normalize_workflow_publication"](config)


def test_manual_route_uses_same_receipt_service_and_safe_errors(publication):
    namespace = {
        "request": request, "jsonify": jsonify, "get_current_user_id": lambda: "actor",
        "get_current_user_info": lambda: {"displayName": "Actor"},
        "_get_authorized_chat_artifact_message": publication.module._authorize_artifact,
        "authorize_analysis_artifact": publication.module.authorize_analysis_artifact,
        "publish_generated_chat_artifact_for_user": publication.module.publish_generated_chat_artifact_for_user,
        "log_event": lambda *args, **kwargs: None, "os": os,
    }
    helpers = load_functions("route_enhanced_citations.py", {
        "promote_chat_artifact_to_workspace", "_normalize_generated_artifact_target_scope",
        "_resolve_generated_artifact_file_name",
    }, namespace)
    app = Flask(__name__)
    app.add_url_rule("/api/chat_artifacts/promote", view_func=helpers["promote_chat_artifact_to_workspace"], methods=["POST"])
    client = app.test_client()
    payload = {"conversation_id": "conversation-1", "message_id": "artifact-1", "workspace_scope": "personal"}
    first = client.post("/api/chat_artifacts/promote", json=payload)
    second = client.post("/api/chat_artifacts/promote", json=payload)
    assert first.status_code == second.status_code == 200
    assert first.get_json()["publication"] == second.get_json()["publication"]
    assert len(publication.calls["create"]) == 1
    assert client.post("/api/chat_artifacts/promote", json={**payload, "workspace_scope": ""}).status_code == 400
    publication.state["source_allowed"] = False
    denied = client.post("/api/chat_artifacts/promote", json=payload)
    assert denied.status_code == 403
    assert "revoked" not in denied.get_json()["error"]
    assert len(publication.calls["create"]) == 1


def test_upload_digest_binds_idempotent_streams_to_actual_bytes_and_producer():
    stored = {}
    uploaded = []

    class Messages:
        def read_item(self, item, partition_key):
            if item not in stored:
                raise CosmosResourceNotFoundError(status_code=404, message="missing")
            return deepcopy(stored[item])

        def upsert_item(self, body):
            stored[body["id"]] = deepcopy(body)

    class Blob:
        def exists(self):
            return bool(uploaded)

        def upload_blob(self, content, **kwargs):
            payload = b"".join(iter(lambda: content.read(16), b"")) if hasattr(content, "read") else content
            uploaded.append(payload)

    blob = Blob()
    namespace = load_functions("functions_simplechat_operations.py", {"_upload_generated_chat_artifact_for_current_user"}, {
        "Any": Any, "Dict": Dict, "Optional": Optional, "hashlib": hashlib, "os": os, "uuid": uuid,
        "datetime": datetime, "timezone": timezone, "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
        "cosmos_conversations_container": types.SimpleNamespace(read_item=lambda **kwargs: {"user_id": "actor"}),
        "build_conversation_participation_context": lambda *args: {"is_owner": True},
        "analysis_artifact_metadata": saved_analysis.analysis_artifact_metadata,
        "requires_generated_file_approval": lambda *args, **kwargs: False,
        "CLIENTS": {"storage_account_office_docs_client": types.SimpleNamespace(get_blob_client=lambda **kwargs: blob)},
        "storage_account_personal_chat_container_name": "chat",
        "cosmos_messages_container": Messages(), "_get_latest_personal_thread_id": lambda *args: None,
        "_build_generated_chat_artifact_lifecycle_metadata": lambda *args, **kwargs: {},
        "_build_generated_chat_artifact_lifecycle_response": lambda *args: {},
        "TABULAR_EXTENSIONS": {"csv", "json"}, "log_event": lambda *args, **kwargs: None,
    })
    upload = namespace["_upload_generated_chat_artifact_for_current_user"]
    producer = {"kind": "workflow", "workflow_id": "workflow", "run_id": "run", "task_id": "analyze"}

    def invoke(content, actual_producer=producer):
        return upload(
            "actor", "conversation-1", "accepted.md", io.BytesIO(content),
            artifact_metadata={"analysis_producer": actual_producer}, artifact_idempotency_key="stable-export",
        )

    first = invoke(b"accepted bytes")
    second = invoke(b"accepted bytes")
    assert first["message"]["id"] == second["message"]["id"]
    metadata = stored[first["message"]["id"]]["metadata"]
    assert metadata["analysis_result_required"] is True
    assert metadata["analysis_producer"] == producer
    assert metadata["generated_artifact_content_sha256"] == hashlib.sha256(b"accepted bytes").hexdigest()
    with pytest.raises(ValueError, match="different bytes"):
        invoke(b"changed bytes")
    with pytest.raises(ValueError, match="different analysis"):
        invoke(b"accepted bytes", {**producer, "task_id": "another-task"})
    assert uploaded == [b"accepted bytes"]
