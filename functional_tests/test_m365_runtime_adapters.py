# test_m365_runtime_adapters.py
"""
Integration tests for staged file processing and subject-owned resume adapters.
Version: 0.261.035
Implemented in: 0.261.029

Real memory manifests and batch execution are used with mocked external model
I/O. Resume tests prove that authenticated decisions enqueue only their own job.
"""

import asyncio
from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import patch

from flask import Flask, Response, g, request, session
import pytest
from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Standalone test module resolution is configured before these imports.
from functions_conversation_memory import EvidenceChunk, EvidenceSource
from functions_m365_execution import M365ExecutionContext
from functions_m365_approvals import M365PolicyError
from conversation_memory_lifecycle import clone_owned_memory, remap_memory_references
import conversation_memory_lifecycle
from functions_m365_data_lifecycle import (
    is_live_m365_authorization, strip_m365_runtime_references, validate_m365_admin_record_edit,
)
from functions_azure_endpoint_validation import validate_configured_chat_blob_endpoint
from test_conversation_working_memory import MemoryHarness
from test_support.m365 import CosmosContainer
from test_support.m365 import Clock, Notifications
import functions_m365_approvals as approvals
import functions_m365_execution as execution


def load_module(name, replacements):
    spec = importlib.util.spec_from_file_location(f"test_{name}", APP / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, replacements):
        spec.loader.exec_module(module)
    return module


def module_stub(name, **values):
    module = types.ModuleType(name)
    module.__dict__.update(values)
    return module


def test_workflow_manifests_keep_agent_scope_and_actual_task_capabilities():
    personal_agent = {
        "id": "personal-agent", "name": "Assistant", "actions_to_load": ["mail"],
        "other_settings": {"action_capabilities": {"personal-mail": {"get_my_messages": False}}},
    }
    global_agent = {"id": "global-agent", "name": "Assistant", "actions_to_load": ["mail"]}
    action = {
        "name": "mail", "type": "m365_email",
        "enabled_functions": ["get_my_messages", "send_mail"],
        "additionalFields": {"m365_capabilities": {"send_mail": True}},
    }
    catalogs = {
        "functions_global_actions": module_stub("functions_global_actions", get_global_actions=lambda **kwargs: [{**action, "id": "global-mail"}]),
        "functions_global_agents": module_stub("functions_global_agents", get_global_agents=lambda: [global_agent]),
        "functions_personal_actions": module_stub("functions_personal_actions", get_personal_actions=lambda *args, **kwargs: [{**action, "id": "personal-mail"}]),
        "functions_personal_agents": module_stub("functions_personal_agents", get_personal_agents=lambda user_id: [personal_agent]),
        "functions_group_actions": module_stub("functions_group_actions", get_group_actions=lambda *args, **kwargs: []),
        "functions_group_agents": module_stub("functions_group_agents", get_group_agents=lambda *args: []),
        "functions_group": module_stub("functions_group", assert_group_role=lambda *args: None),
        "functions_keyvault": module_stub("functions_keyvault", SecretReturnType=types.SimpleNamespace(NAME="name")),
        "functions_settings": module_stub("functions_settings", get_settings=lambda: {}),
    }
    runtime = load_module("functions_m365_runtime", {
        "config": module_stub(
            "config", TENANT_ID="tenant", cosmos_conversations_container=None,
            cosmos_m365_execution_runs_container=None,
        ),
        "functions_appinsights": module_stub("functions_appinsights", log_event=lambda *args, **kwargs: None),
        "functions_collaboration": module_stub(
            "functions_collaboration",
            assert_user_can_participate_in_collaboration_conversation=lambda *args: None,
            build_conversation_participation_context=lambda *args: None,
            get_collaboration_conversation=lambda *args: None,
        ),
    })
    workflow = {
        "user_id": "owner",
        "selected_agent": {"id": "personal-agent", "name": "Assistant", "is_global": False},
    }
    with patch.dict(sys.modules, catalogs):
        personal, _ = runtime.workflow_m365_manifests(workflow)
        global_actions, _ = runtime.workflow_m365_manifests({
            **workflow, "selected_agent": {"id": "global-agent", "name": "Assistant", "is_global": True},
        })
        unused, _ = runtime.workflow_m365_manifests({
            **workflow, "tasks": [{"runner": {"type": "model"}}],
        })
        catalogs["functions_personal_actions"].get_personal_actions = lambda *args, **kwargs: [{
            "id": "legacy", "name": "mail", "type": "msgraph", "enabled_functions": ["get_my_messages"],
        }]
        legacy, _ = runtime.workflow_m365_manifests(workflow)
        app = Flask(__name__)
        context = M365ExecutionContext(
            actor_user_id="owner", data_user_id="owner", tenant_id="tenant", request_id="request",
        )
        with app.test_request_context():
            no_selection = runtime.resolve_m365_action_selection(context)
            g.m365_selected_agent_ref = workflow["selected_agent"]
            selected = runtime.resolve_m365_action_selection(context)
            personal_agent["actions_to_load"] = []
            removed = runtime.resolve_m365_action_selection(context)
        with pytest.raises(M365PolicyError):
            runtime.workflow_m365_manifests({
                **workflow, "selected_agent": {"id": "missing-agent", "name": "Assistant"},
            })
    assert [item["id"] for item in personal] == ["personal-mail"]
    assert personal[0]["enabled_functions"] == ["send_mail"]
    assert [item["id"] for item in global_actions] == ["global-mail"]
    assert unused == []
    assert legacy[0]["enabled_functions"] == ["get_my_messages"]
    assert no_selection == []
    assert selected == ["legacy"]
    assert removed == []


def test_cancelled_request_cannot_be_reopened_by_a_late_approval_callback():
    jobs = CosmosContainer("user_id")
    prior = jobs.create_item(body={
        "id": "request", "user_id": "owner", "actor_user_id": "owner",
        "conversation_id": "conversation", "status": "running",
    })
    runtime = load_module("functions_m365_runtime", {
        "config": module_stub(
            "config", TENANT_ID="tenant", cosmos_conversations_container=None,
            cosmos_m365_execution_runs_container=jobs,
        ),
        "functions_appinsights": module_stub("functions_appinsights", log_event=lambda *args, **kwargs: None),
        "functions_collaboration": module_stub(
            "functions_collaboration",
            assert_user_can_participate_in_collaboration_conversation=lambda *args: None,
            build_conversation_participation_context=lambda *args: None,
            get_collaboration_conversation=lambda *args: None,
        ),
    })
    context = M365ExecutionContext(
        actor_user_id="owner", data_user_id="owner", tenant_id="tenant",
        conversation_id="conversation", request_id="request",
    )
    stopped = jobs.upsert_item(body={**prior, "status": "cancelled"})
    waiting = {**prior, "status": "awaiting_approval", "payload": {"message": "A private prompt"}}
    with pytest.raises(M365PolicyError):
        runtime._save_m365_wait_record(waiting, prior, context)
    with pytest.raises(M365PolicyError):
        runtime._save_m365_wait_record(waiting, stopped, context)
    stored = jobs.read_item("request", "owner")
    assert stored["status"] == "cancelled"
    assert "payload" not in stored


def test_publication_rechecks_real_grants_without_rejecting_unrelated_action_refresh():
    container = CosmosContainer()
    service = approvals.M365ApprovalService(
        container_factory=lambda: container, clock=Clock(),
        notification_sender=Notifications(), decision_validator=lambda approval: True,
    )
    context = M365ExecutionContext(
        actor_user_id="owner", data_user_id="owner", tenant_id="tenant",
        conversation_id="conversation", request_id="request", shared=True, audience_version="audience",
        action_configs={"action": {
            "type": "m365_sharepoint", "source": "spo",
            "enabled_functions": ["read_file_chunk"],
            "maximum_sharing_acknowledgement": "always",
        }},
    )
    with pytest.raises(approvals.M365ApprovalRequired) as raised:
        service.authorize_sources(context, {"spo": "always"})
    service.decide(raised.value.approval_id, "owner", {
        "decisions": {"spo": {"duration": "always", "timezone": "UTC"}},
    })
    runtime = load_module("conversation_memory_runtime", {
        "config": module_stub(
            "config", CLIENTS={}, TENANT_ID="tenant", cosmos_conversations_container=None,
            cosmos_messages_container=None, build_enhanced_citations_blob_service_client=lambda settings: None,
        ),
        "functions_appinsights": module_stub("functions_appinsights", log_event=lambda *args, **kwargs: None),
        "functions_collaboration": module_stub("functions_collaboration", build_conversation_participation_context=lambda *args: None),
        "functions_settings": module_stub("functions_settings", get_settings=lambda: {}),
    })
    harness = MemoryHarness()
    current = replace(context, action_configs={**context.action_configs, "other": {"source": "email"}})
    run = {
        "run_id": "a" * 32, "request_id": "original-capture-request",
        "content_revision": 2, "purpose": "m365_file_spo",
        "principal_id": "owner",
    }
    grant_context = {
        "execution_context": context, "source": "spo",
        "action_id": "action", "operation_name": "read_file_chunk",
    }
    with patch.object(approvals, "_service", service), patch.object(execution, "_action_config_resolver", None):
        with execution.m365_execution_context(current):
            grant = runtime._authorize_memory_publication(harness.context, run, grant_context)
            with pytest.raises(runtime.MemoryAuthorizationError):
                runtime._authorize_memory_publication(
                    harness.context, {**run, "purpose": "m365_agent_history"}, grant_context,
                )
    assert grant.approval_ids == (raised.value.approval_id,)
    assert grant.principal_id == "owner"
    assert grant.request_id == "original-capture-request"
    assert grant.publication_request_id == "request"
    assert grant.authorization_id != raised.value.approval_id


def test_staged_model_analysis_commits_each_source_chunk_once():
    harness = MemoryHarness()
    memory_context = replace(harness.context, request_id="request")
    run = harness.store.create_run(memory_context, request_id="request", purpose="m365_file_spo")
    harness.store.add_evidence(
        memory_context, run["run_id"],
        source=EvidenceSource("spo", "file", "version", coverage_complete=True),
        chunks=[EvidenceChunk("First source section"), EvidenceChunk("Second source section")],
    )
    harness.store.complete_run(memory_context, run["run_id"])
    runtime = load_module("functions_m365_analysis_runtime", {
        "conversation_memory_runtime": module_stub(
            "conversation_memory_runtime",
            resolve_m365_memory=lambda context: (
                harness.store, replace(harness.context, request_id=context.request_id),
            ),
        ),
    })
    model_calls = []

    class Model:
        async def get_chat_message_contents(self, *, chat_history, settings):
            model_calls.append(str(chat_history))
            assert settings.function_choice_behavior is None
            assert settings.max_completion_tokens == 1536
            assert settings.max_tokens is None
            assert settings.tools is None
            return [types.SimpleNamespace(content=f"Findings from batch {len(model_calls)}")]

    class Agent:
        deployment_name = "gpt-5.6-terra"
        kernel = object()
        arguments = None

        async def _get_chat_completion_service_and_settings(self, **kwargs):
            return Model(), OpenAIChatPromptExecutionSettings(
                tools=[{"type": "function", "function": {"name": "must_not_be_called", "parameters": {"type": "object", "properties": {}}}}],
                max_completion_tokens=10000,
            )

    runtime.get_m365_analysis_agent = lambda context: Agent()
    runtime.get_m365_approval_service = lambda: types.SimpleNamespace(
        authorize_extended_analysis=lambda *args: {"mode": "extended"},
    )
    context = M365ExecutionContext(
        actor_user_id="owner", data_user_id="owner", tenant_id="tenant",
        conversation_id="conversation", request_id="request",
    )

    async def execute():
        first = await runtime.analyze_m365_memory(context, "spo", "action", run["run_id"], "Find the requirements")
        resumed_context = replace(context, request_id="next-request")
        second = await runtime.analyze_m365_memory(
            resumed_context, "spo", "action", run["run_id"], "Find the requirements", first["analysis_id"],
        )
        repeated = await runtime.analyze_m365_memory(
            resumed_context, "spo", "action", run["run_id"], "Find the requirements", first["analysis_id"],
        )
        return first, second, repeated

    first, second, repeated = asyncio.run(execute())
    assert first["continue_analysis"] is True
    assert second["coverage"] == {"completed_chunks": 2, "total_chunks": 2, "complete": True}
    assert repeated["status"] == "completed"
    assert len(model_calls) == 2


@pytest.mark.parametrize("interrupted_capture", [False, True])
def test_private_owner_fork_keeps_independent_evidence_and_rewrites_references(interrupted_capture):
    harness = MemoryHarness()
    target = replace(harness.context, conversation_id="owned-target")
    harness.members[("tenant", "owned-target", "owner", "personal-chat")] = {"owner"}
    run = harness.store.create_run(harness.context, purpose="m365_file_onedrive")
    if interrupted_capture:
        def interrupted_chunks():
            yield EvidenceChunk("Interrupted source")
            raise ValueError("Capture interrupted")
        with pytest.raises(ValueError):
            harness.store.add_evidence(
                harness.context, run["run_id"], source=EvidenceSource("onedrive", "interrupted", "v1"),
                chunks=interrupted_chunks(),
            )
        harness.store.resume(harness.context, run["run_id"])
        harness.store.recover_pending(harness.context, run["run_id"], discard=True)
    source = harness.store.add_evidence(
        harness.context, run["run_id"], source=EvidenceSource("onedrive", "file", "v1"),
        chunks=[EvidenceChunk("Original evidence")],
    )
    harness.store.complete_run(harness.context, run["run_id"])
    clone = clone_owned_memory(harness.store, harness.context, target, run["run_id"])
    harness.store.delete_conversation_memory(harness.context)
    rewritten = remap_memory_references(
        {"memory_id": f"{run['run_id']}:{source['evidence_id']}"}, clone["reference_map"],
    )
    copied = harness.store.read_evidence_range(
        target, clone["run_id"], rewritten["memory_id"].partition(":")[2],
    )
    assert copied["chunks"][0]["text"] == "Original evidence"
    assert clone["publication"] is None
    assert rewritten["memory_id"].startswith(clone["run_id"])


def test_inventory_cleanup_removes_evidence_without_message_artifact_references(monkeypatch):
    harness = MemoryHarness()
    run = harness.store.create_run(harness.context, purpose="m365_file_spo")
    harness.store.add_evidence(
        harness.context, run["run_id"], source=EvidenceSource("spo", "file", "v1"),
        chunks=[EvidenceChunk("Retained content without a registered message artifact")],
    )
    monkeypatch.setattr(conversation_memory_lifecycle, "ConversationMemoryStore", lambda *args, **kwargs: harness.store)
    deleted = conversation_memory_lifecycle.delete_referenced_conversation_memory(
        [], None, tenant_id="tenant",
        read_conversation=lambda conversation_id: {"id": conversation_id, "user_id": "owner"},
        log_event=lambda *args, **kwargs: None, conversation_context=harness.context,
    )
    assert deleted == 1
    assert all(
        b"Retained content without a registered message artifact" not in record.data
        for record in harness.transport.blobs.values()
    )


def test_memory_inventory_marker_is_saved_before_any_blob_run_is_created(monkeypatch):
    conversations = CosmosContainer("id")
    conversations.create_item(body={"id": "conversation", "user_id": "owner"})
    runtime = load_module("conversation_memory_runtime", {
        "config": module_stub(
            "config", CLIENTS={}, TENANT_ID="tenant", cosmos_conversations_container=conversations,
            cosmos_messages_container=None, build_enhanced_citations_blob_service_client=lambda settings: None,
        ),
        "functions_appinsights": module_stub("functions_appinsights", log_event=lambda *args, **kwargs: None),
        "functions_collaboration": module_stub("functions_collaboration", build_conversation_participation_context=lambda *args: None),
        "functions_settings": module_stub("functions_settings", get_settings=lambda: {}),
    })
    harness = MemoryHarness()
    monkeypatch.setattr(runtime, "get_conversation_memory_store", lambda: harness.store)
    monkeypatch.setattr(runtime, "resolve_memory_context", lambda execution: harness.context)
    monkeypatch.setattr(runtime, "_authorize_memory_access", lambda context, operation: True)
    store, context = runtime.resolve_m365_memory(object())
    conversation = conversations.read_item("conversation", "conversation")
    assert conversation["m365_working_memory"] is True
    assert harness.transport.blobs == {}
    assert store is harness.store and context == harness.context


def test_live_authority_is_not_restored_but_audit_is_preserved():
    assert is_live_m365_authorization({"record_kind": "m365_approval"})
    assert is_live_m365_authorization({"kind": "connection", "encrypted_cache": {"data": "ciphertext"}})
    assert not is_live_m365_authorization({"record_kind": "m365_audit"})
    assert is_live_m365_authorization({"type": "msgraph"})
    assert not is_live_m365_authorization({"type": "m365_sharepoint"})
    assert is_live_m365_authorization({"type": "Microsoft Graph Plugin"})
    assert is_live_m365_authorization({"id": "receipt", "_action_migration": True})
    restored = strip_m365_runtime_references({
        "m365_run_as_user_id": "reader", "m365_binding_approval_id": "old",
        "active_run_id": "old-run", "status": "awaiting_approval",
    })
    assert restored["m365_binding_approval_id"] is None
    assert restored["status"] == "idle"


def test_legacy_settings_transfer_and_admin_editor_cannot_mint_authority():
    events = []
    original = {"id": "settings", "settings": {"plugins": [
        {"id": "retired", "type": "Microsoft Graph Plugin"},
        {"id": "files", "type": "m365_sharepoint"},
    ]}}
    transferred = strip_m365_runtime_references(
        original, log_event=lambda *args, **kwargs: events.append(args),
    )
    assert transferred["settings"]["plugins"] == [{"id": "files", "type": "m365_sharepoint"}]
    assert len(original["settings"]["plugins"]) == 2
    assert len(events) == 1
    for previous, changed in (
        ({"id": "same", "type": "sql"}, {"id": "same", "type": "MicrosoftGraphPlugin"}),
        ({"id": "settings", "plugins": []}, {"id": "settings", "plugins": [{"id": "new", "type": "msgraph"}]}),
        ({"id": "grant", "record_kind": "m365_approval"}, {"id": "grant", "status": "approved"}),
        ({"id": "grant"}, {"id": "grant", "record_kind": "m365_user_policy"}),
        ({"id": "audit", "record_kind": "m365_audit"}, {"id": "audit"}),
    ):
        with pytest.raises(ValueError):
            validate_m365_admin_record_edit(previous, changed)
    validate_m365_admin_record_edit({"id": "old", "type": "msgraph"}, {"id": "old", "type": "msgraph"})

def test_custom_chat_storage_requires_the_deployment_suffix():
    endpoint = validate_configured_chat_blob_endpoint(
        "https://chatstore.blob.internal.example", "blob.internal.example",
    )
    assert endpoint == "https://chatstore.blob.internal.example"
    for value in (
        "https://chatstore.blob.core.windows.net",
        "https://chatstore.blob.internal.example.attacker.test",
        "https://user:password@chatstore.blob.internal.example",
        "https://chatstore.blob.internal.example/container",
    ):
        with pytest.raises(ValueError):
            validate_configured_chat_blob_endpoint(value, "blob.internal.example")


def test_approval_resume_enqueues_own_request_once_without_serializing_tokens():
    jobs = CosmosContainer("user_id")
    jobs.create_item(body={
        "id": "request", "user_id": "reader", "actor_user_id": "reader",
        "conversation_id": "conversation", "type": "m365_execution_request",
        "status": "awaiting_approval", "approval_id": "approval", "payload": {"message": "Read file"},
    })
    runtime = load_module("functions_m365_request_resume", {
        "config": module_stub(
            "config", cosmos_conversations_container=CosmosContainer("id"),
            cosmos_m365_execution_runs_container=jobs,
        ),
        "functions_appinsights": module_stub("functions_appinsights", log_event=lambda *args, **kwargs: None),
    })
    calls = []
    app = Flask(__name__)
    app.secret_key = "test-session-key"
    app.extensions["executor"] = types.SimpleNamespace(submit=lambda *args: calls.append(args))
    approval = {
        "id": "approval", "subject_user_id": "reader",
        "context": {"request_id": "request", "conversation_id": "conversation"},
    }
    with app.test_request_context(headers={"Cookie": "session=interactive-test-cookie"}):
        session["user"] = {"oid": "reader", "tid": "tenant"}
        session["token_cache"] = "test-token-cache"
        first = runtime.queue_approved_chat(approval, "reader")
        second = runtime.queue_approved_chat(approval, "reader")
        with pytest.raises(PermissionError):
            runtime.queue_approved_chat(approval, "other-reader")
    stored = jobs.read_item("request", "reader")
    assert first["resume_scheduled"] and second["resume_scheduled"]
    assert len(calls) == 1
    assert "token_cache" not in stored
    assert "test-token-cache" not in str(stored)
    assert "test-token-cache" not in str(calls)


@pytest.mark.parametrize("expired", [False, True])
def test_background_chat_reopens_the_live_session_without_cloning_credentials(expired):
    jobs = CosmosContainer("user_id")
    conversations = CosmosContainer("id")
    conversations.create_item(body={"id": "conversation", "user_id": "reader"})
    job = jobs.create_item(body={
        "id": "request", "user_id": "reader", "actor_user_id": "reader",
        "conversation_id": "conversation", "type": "m365_execution_request",
        "status": "ready_to_resume", "resume_queue_id": "queue",
        "payload": {"message": "Read the saved file"}, "user_message_id": "original-human-message",
    })
    runtime = load_module("functions_m365_request_resume", {
        "config": module_stub(
            "config", cosmos_conversations_container=conversations,
            cosmos_m365_execution_runs_container=jobs,
        ),
        "functions_appinsights": module_stub("functions_appinsights", log_event=lambda *args, **kwargs: None),
    })
    app = Flask(__name__)
    app.secret_key = "test-session-key"
    dispatched = []

    @app.route("/api/chat/stream", methods=["POST"])
    def stream():
        dispatched.append((session["user"]["oid"], request.get_json()))
        current = jobs.read_item("request", "reader")
        jobs.upsert_item(body={**current, "status": "completed"})
        return Response('data: {"done": true}\n\n', mimetype="text/event-stream")

    cookie = app.session_interface.get_signing_serializer(app).dumps({
        "user": {"oid": "reader", "tid": "tenant"}, "token_cache": "session-only-test-cache",
    })
    runtime._execute_chat_continuation(app, f"session={'expired' if expired else cookie}", job)
    stored = jobs.read_item("request", "reader")
    assert stored["status"] == ("awaiting_sign_in" if expired else "completed")
    assert len(dispatched) == (0 if expired else 1)
    if not expired:
        assert dispatched[0][0] == "reader"
        assert dispatched[0][1]["retry_user_message_id"] == "original-human-message"
    assert "token_cache" not in stored
    assert "session-only-test-cache" not in str(stored)


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve())]))
