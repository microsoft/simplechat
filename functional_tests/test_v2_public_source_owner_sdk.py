# test_v2_public_source_owner_sdk.py
"""Representative SDK contracts for storage owners touched by V2 public sources.

Version: 0.261.373
Implemented in: 0.261.373

Point reads and writes use the installed CosmosDict through the existing atomic
container; queries remain plain dictionaries. Source-bound functions execute their
real bodies without cloud bootstrap or route registration. These tests cover the
named behaviors, not every branch of every inventoried function in these modules.
"""

import ast
import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest
from azure.core import MatchConditions
from azure.cosmos import exceptions
from azure.cosmos._cosmos_responses import CosmosDict
from flask import Flask, jsonify, request

import functions_chat_retry as retry
from test_support.orchestration_revisions import AtomicMemoryContainer


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"


class OwnerContainer(AtomicMemoryContainer):
    """Keep SDK-default points and add only the owners' bounded query predicates."""

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        rows = super().query_items(query, parameters, partition_key, **kwargs)
        values = {entry["name"]: entry["value"] for entry in parameters or []}
        for parameter in ("@message_id", "@file_id"):
            if parameter in values:
                rows = [row for row in rows if row["id"] == values[parameter]]
        if "@thread_id" in values:
            rows = [
                row for row in rows
                if (row.get("metadata") or {}).get("thread_info", {}).get("thread_id")
                == values["@thread_id"]
            ]
        if "c.role = 'user'" in query:
            rows = [row for row in rows if row.get("role") == "user"]
        if "@ids" in values:
            rows = [row for row in rows if row["id"] in values["@ids"]]
        if "@status" in values:
            rows = [row for row in rows if row.get("status") == values["@status"]]
        if "c.is_enabled = true" in query:
            rows = [row for row in rows if row.get("is_enabled", True) is True]
        return rows


def _source_owner(filename, names, namespace, *, registrar=None):
    """Bind unchanged owner bodies; HTTP decorators/bootstrap are tested elsewhere."""
    path = APP_ROOT / filename
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    selected = []
    found = set()
    for node in tree.body:
        candidates = node.body if isinstance(node, ast.FunctionDef) and node.name == registrar else [node]
        for candidate in candidates:
            if isinstance(candidate, (ast.FunctionDef, ast.ClassDef)) and candidate.name in names:
                if registrar:
                    candidate.decorator_list = []
                selected.append(candidate)
                found.add(candidate.name)
            elif isinstance(candidate, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in names for target in candidate.targets
            ):
                selected.append(candidate)
                found.update(target.id for target in candidate.targets if isinstance(target, ast.Name))
    missing = set(names) - found
    if missing:
        raise AssertionError(f"Missing real owner definitions in {filename}: {missing}")
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


@pytest.fixture
def storage():
    conversations = OwnerContainer("id")
    messages = OwnerContainer("conversation_id")
    point = conversations.create_item({"id": "conversation", "user_id": "reader", "tags": ["keep"]})
    assert type(point) is CosmosDict and point["_etag"]
    return conversations, messages


def test_retry_owner_preserves_sdk_points_conditional_writes_and_plain_queries(storage):
    conversations, messages = storage
    source_point = messages.create_item({
        "id": "question", "conversation_id": "conversation", "role": "user",
        "content": "Read the selected public document.",
        "metadata": {
            "user_info": {"user_id": "reader"},
            "thread_info": {"thread_id": "thread", "thread_attempt": 1, "active_thread": True},
        },
    })
    source, conversation = retry.load_owned_retry_message(
        messages, conversations, "reader", "question",
    )
    assert type(source) is dict and type(conversation) is CosmosDict
    assert source["_etag"] == source_point["_etag"] and conversation["tags"] == ["keep"]
    with pytest.raises(retry.ChatRetryError, match="own conversations"):
        retry.load_owned_retry_message(messages, conversations, "outsider", "question")

    body = {
        "message": source["content"], "conversation_id": "conversation",
        "public_source_policy": "all_available",
        "selected_document_ids": ["public-document"],
    }
    prepared = retry.prepare_retry_attempt(
        messages, conversations, "reader", source, body, submission_id="sdk-owner",
    )
    assert type(prepared) is CosmosDict and prepared["_etag"]
    assert prepared["metadata"]["workspace_search"]["public_source_policy"] == "all_available"
    assert prepared["metadata"]["workspace_search"]["selected_document_ids"] == ["public-document"]
    reconciled = retry.reconcile_prepared_retry(messages, conversations, "reader", prepared)
    assert type(reconciled) is dict and reconciled["id"] == prepared["id"]
    replayed = retry.prepare_retry_attempt(
        messages, conversations, "reader", source, body, submission_id="sdk-owner",
    )
    assert type(replayed) is CosmosDict and replayed["id"] == prepared["id"]
    thread = retry.retry_thread_messages(messages, "conversation", "thread")
    original = retry.retry_source_user(messages, {
        "id": "answer", "conversation_id": "conversation",
        "metadata": {"thread_info": {"thread_id": "thread", "thread_attempt": 1}},
    })
    assert all(type(row) is dict for row in thread) and original["id"] == source["id"]
    assert messages.queries[-1][2] == "conversation"

    claimed = retry.claim_retry_attempt(
        messages, conversations, "reader", "conversation", prepared["id"],
    )
    assert type(claimed) is CosmosDict and claimed["_etag"] != prepared["_etag"]
    assert claimed["metadata"]["response_attempt"]["state"] == "running"
    stale = dict(prepared)
    with pytest.raises(exceptions.CosmosAccessConditionFailedError):
        messages.replace_item(
            item=stale["id"], body=stale, etag=stale["_etag"],
            match_condition=MatchConditions.IfNotModified,
        )
    returned = retry.set_retry_attempt_state(messages, "conversation", prepared["id"], "completed")
    completed = messages.read_item(prepared["id"], "conversation")
    published = conversations.read_item("conversation", "conversation")
    assert returned is None and type(completed) is CosmosDict
    assert completed["metadata"]["response_attempt"]["state"] == "completed"
    assert completed["_etag"] != claimed["_etag"]
    assert published["retry_threads"]["thread"]["published"]


def test_workflow_context_owner_reads_plain_partitioned_query_rows(monkeypatch):
    config = ModuleType("config")
    for name in ("personal_agents", "global_agents", "personal_workflows"):
        container = OwnerContainer("user_id")
        container.create_item({
            "id": name, "user_id": "reader", "name": name,
            "is_enabled": True, "nested": {"retained": True},
        })
        container.create_item({"id": "other", "user_id": "outsider", "is_enabled": False})
        setattr(config, f"cosmos_{name}_container", container)
    monkeypatch.setitem(sys.modules, "config", config)
    owner = _source_owner("functions_orchestration_workflow_context.py", {
        "_AGENT_FIELDS", "WORKFLOW_SCAN_LIMIT", "_read_personal_agents", "_read_global_agents",
        "_read_workflows", "_read_wait_workflows",
    }, {})
    personal = owner["_read_personal_agents"]("reader")
    global_agents = owner["_read_global_agents"]()
    workflows = owner["_read_workflows"]("reader")
    waiting = owner["_read_wait_workflows"]("reader", ["personal_workflows"])
    empty = owner["_read_wait_workflows"]("reader", [])
    assert empty == []
    for rows, identity in (
        (personal, "personal_agents"), (global_agents, "global_agents"),
        (workflows, "personal_workflows"), (waiting, "personal_workflows"),
    ):
        assert len(rows) == 1 and type(rows[0]) is dict
        assert rows[0]["id"] == identity and type(rows[0]["nested"]) is dict
    assert config.cosmos_personal_agents_container.queries[-1][2] == "reader"
    assert config.cosmos_personal_workflows_container.queries[-1][2] == "reader"
    assert config.cosmos_global_agents_container.queries[-1][2] is None
    point = config.cosmos_personal_workflows_container.read_item("personal_workflows", "reader")
    assert type(point) is CosmosDict and point["_etag"]


def test_prompt_variable_owner_checks_sdk_conversation_identity(storage):
    conversations, _ = storage
    owner = _source_owner("functions_prompt_variables.py", {
        "PromptKnowledgeFillError", "_authorize_conversation",
    }, {"cosmos_conversations_container": conversations,
        "CosmosResourceNotFoundError": exceptions.CosmosResourceNotFoundError})
    data = {"conversation_id": "conversation", "conversation_kind": "personal"}
    result = owner["_authorize_conversation"](data, "reader", {})
    assert result is None
    for actor, conversation_id in (("outsider", "conversation"), ("reader", "missing")):
        with pytest.raises(owner["PromptKnowledgeFillError"]) as error:
            owner["_authorize_conversation"]({**data, "conversation_id": conversation_id}, actor, {})
        assert error.value.status_code == 403
    stored = conversations.read_item("conversation", "conversation")
    assert type(stored) is CosmosDict and stored["tags"] == ["keep"]


def test_tabular_export_owner_keeps_sdk_etags_and_public_scope_fences(storage):
    conversations, _ = storage
    runs = OwnerContainer("user_id")
    point = runs.create_item({
        "id": "export", "user_id": "reader", "conversation_id": "conversation",
        "status": "queued", "source_descriptor": {"source": "public", "scope_id": "public"},
    })
    checked = []
    checked_blobs = []
    owner = _source_owner("functions_tabular_generated_exports.py", {
        "_authorize_tabular_export_run_conversation", "_authorize_tabular_export_run_execution",
        "_read_run", "_replace_run", "_safe_int", "_query_scheduler_candidates_by_status",
        "TABULAR_EXPORT_DEFAULT_SCAN_LIMIT", "TABULAR_EXPORT_RUN_TYPE",
    }, {
        "cosmos_conversations_container": conversations, "cosmos_tabular_export_runs_container": runs,
        "CosmosResourceNotFoundError": exceptions.CosmosResourceNotFoundError,
        "MatchConditions": MatchConditions, "get_public_source_workspace_ids": lambda _user: ["public"],
        "storage_account_public_documents_container_name": "public-files",
        "assert_evidence_available": lambda evidence, **kwargs: checked.append((evidence, kwargs)),
        "assert_blob_available": lambda *args, **kwargs: checked_blobs.append((args, kwargs)),
        "_scheduler_candidate_reason": lambda row, _settings: row.get("status") == "queued",
        "log_event": lambda *_args, **_kwargs: None, "logging": logging,
    })
    loaded = owner["_read_run"]("reader", "export")
    authorized = owner["_authorize_tabular_export_run_execution"](loaded)
    assert type(loaded) is type(authorized) is CosmosDict
    assert loaded["_etag"] == point["_etag"] and authorized["id"] == "conversation"
    assert checked == [(loaded["source_descriptor"], {"user_id": "reader"})]
    blob_authorized = owner["_authorize_tabular_export_run_execution"]({
        **loaded, "source_descriptor": {
            "source": "public", "scope_id": "public", "container": "public-files",
            "blob_path": "public/file.csv",
        },
    })
    assert type(blob_authorized) is CosmosDict and checked_blobs == [
        (("public-files", "public/file.csv"), {"user_id": "reader", "purpose": "export"}),
    ]
    with pytest.raises(PermissionError, match="ownership changed"):
        owner["_authorize_tabular_export_run_conversation"]({**loaded, "user_id": "outsider"})
    with pytest.raises(PermissionError, match="no longer authorized"):
        owner["_authorize_tabular_export_run_execution"]({
            **loaded, "source_descriptor": {"source": "public", "scope_id": "revoked"},
        })
    with pytest.raises(PermissionError, match="no longer authorized"):
        owner["_authorize_tabular_export_run_execution"]({
            **loaded, "source_descriptor": {
                "source": "public", "scope_id": "public", "container": "public-files",
                "blob_path": "another-workspace/file.csv",
            },
        })
    loaded["completed_batches"] = 1
    replaced = owner["_replace_run"](loaded)
    assert type(replaced) is CosmosDict and replaced["_etag"] != loaded["_etag"]
    assert replaced["completed_batches"] == 1 and type(replaced["source_descriptor"]) is dict
    with pytest.raises(exceptions.CosmosAccessConditionFailedError):
        owner["_replace_run"](loaded)
    candidates = owner["_query_scheduler_candidates_by_status"]("queued", 1, {})
    assert len(candidates) == 1 and type(candidates[0]) is dict
    assert candidates[0]["id"] == "export" and runs.queries[-1][2] is None


def _route_namespace(storage):
    conversations, messages = storage
    return {
        "cosmos_conversations_container": conversations, "cosmos_messages_container": messages,
        "CosmosResourceNotFoundError": exceptions.CosmosResourceNotFoundError,
        "exceptions": exceptions, "get_current_user_id": lambda: "reader",
        "jsonify": jsonify, "request": request, "json": json, "traceback": traceback,
        "debug_print": lambda *_args, **_kwargs: None,
        "add_file_task_to_file_processing_log": lambda **_kwargs: None,
        "assert_evidence_available": lambda *_args, **_kwargs: None,
    }


def test_document_route_owner_consumes_sdk_conversation_and_plain_file_rows(storage):
    conversations, messages = storage
    point = messages.create_item({
        "id": "file", "conversation_id": "conversation", "role": "file",
        "filename": "source.txt", "file_content": "Public source text.", "metadata": {},
    })
    owner = _source_owner(
        "route_backend_documents.py", {"get_file_content"}, _route_namespace(storage),
        registrar="register_route_backend_documents",
    )
    app = Flask(__name__)
    with app.test_request_context(json={"conversation_id": "conversation", "file_id": "file"}):
        response, status = owner["get_file_content"]()
    assert status == 200 and response.get_json() == {
        "file_content": "Public source text.", "filename": "source.txt", "is_table": False,
    }
    assert type(point) is CosmosDict and messages.queries[-1][2] == "conversation"
    conversations.upsert_item({"id": "conversation", "user_id": "outsider"})
    query_count = len(messages.queries)
    with app.test_request_context(json={"conversation_id": "conversation", "file_id": "file"}):
        response, status = owner["get_file_content"]()
    assert status == 403 and response.get_json()["error"] == "Forbidden"
    assert len(messages.queries) == query_count


def test_document_share_owner_passes_sdk_upsert_mapping_to_index(storage):
    documents = OwnerContainer("id")
    original = documents.create_item({
        "id": "document", "user_id": "owner", "shared_user_ids": ["reader,pending"],
    })
    synchronized = []
    namespace = {
        **_route_namespace(storage), "cosmos_user_documents_container": documents,
        "datetime": datetime, "timezone": timezone, "document_is_available": lambda _document: True,
        "project_document_acl_to_chunks": lambda *_args, **_kwargs: None,
        "sync_document_access_index_for_document_fail_open": lambda document, **_kwargs: synchronized.append(document),
        "_clear_personal_document_share_pending_notifications": lambda *_args: None,
        "_create_personal_document_share_decision_notification": lambda *_args: None,
        "invalidate_personal_search_cache": lambda *_args: None,
    }
    owner = _source_owner(
        "route_backend_documents.py", {"api_approve_shared_document"}, namespace,
        registrar="register_route_backend_documents",
    )
    with Flask(__name__).test_request_context():
        response, status = owner["api_approve_shared_document"]("document")
    assert status == 200 and response.get_json()["message"] == "Share approved"
    assert len(synchronized) == 1 and type(synchronized[0]) is CosmosDict
    assert synchronized[0]["_etag"] != original["_etag"]
    assert synchronized[0]["shared_user_ids"] == ["reader,approved"]


def test_enhanced_citation_owner_returns_sdk_artifact_and_uses_plain_upload_rows(storage):
    conversations, messages = storage
    point = messages.create_item({
        "id": "artifact", "conversation_id": "conversation", "role": "file",
        "file_content_source": "blob", "blob_container": "chat-files",
        "blob_path": "reader/conversation/artifact.csv",
        "metadata": {"is_generated_chat_artifact": True},
    })
    observed = []

    def authorize_participant(user_id, conversation):
        observed.append(conversation)
        if conversation.get("user_id") != user_id:
            raise PermissionError("Conversation is unavailable.")

    namespace = {
        **_route_namespace(storage),
        "build_conversation_participation_context": authorize_participant,
        "assert_generated_file_approval_allows_download": lambda *_args: None,
        "assert_generated_chat_artifact_is_published_for_user": lambda *_args: None,
    }
    owner = _source_owner(
        "route_enhanced_citations.py", {"_get_authorized_chat_artifact_message"}, namespace,
    )
    artifact = owner["_get_authorized_chat_artifact_message"]("reader", "conversation", "artifact")
    assert type(artifact) is CosmosDict and artifact["_etag"] == point["_etag"]
    assert type(artifact["metadata"]) is dict and type(observed[-1]) is CosmosDict
    with pytest.raises(PermissionError):
        owner["_get_authorized_chat_artifact_message"]("outsider", "conversation", "artifact")
    with pytest.raises(LookupError, match="not found"):
        owner["_get_authorized_chat_artifact_message"]("reader", "conversation", "missing")
    messages.create_item({
        "id": "inline", "conversation_id": "conversation", "role": "file",
        "filename": "inline.csv", "file_content": "one,two", "metadata": {},
    })
    routes = _source_owner(
        "route_enhanced_citations.py", {"get_enhanced_citation_tabular"}, namespace,
        registrar="register_enhanced_citations_routes",
    )
    with Flask(__name__).test_request_context(
        "/api/enhanced_citations/tabular?conversation_id=conversation&file_id=inline",
    ):
        response, status = routes["get_enhanced_citation_tabular"]()
    assert status == 400 and response.get_json()["error"] == "File is not stored in blob storage"
    assert messages.queries[-1][2] == "conversation"
    conversations.upsert_item({"id": "conversation", "user_id": "outsider"})
    with Flask(__name__).test_request_context(
        "/api/enhanced_citations/tabular?conversation_id=conversation&file_id=inline",
    ):
        response, status = routes["get_enhanced_citation_tabular"]()
    assert status == 403 and response.get_json()["error"] == "Forbidden"
