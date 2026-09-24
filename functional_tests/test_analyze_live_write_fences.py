# test_analyze_live_write_fences.py
"""
Conditional Analyze cancellation, retry and conversation deletion integration.
Version: 0.261.139
Implemented in: 0.261.109
Single orchestration contract updated in: 0.261.139

Use the real saved service, recovery controls and transactional result store.
Only Cosmos/authorization I/O is doubled; no source extraction or live calls run.
"""

from copy import deepcopy
from datetime import datetime
import json
import logging
import sys
import threading
from types import SimpleNamespace

import pytest
from azure.core import MatchConditions
from flask import Flask, jsonify, request

from test_analyze_backend_saved_integration import access, budget, chat, final_analysis, followup_body, load_functions, runner_namespace, saved
from test_analyze_orchestration_saved_integration import orchestration
from test_document_analysis_work_recovery import AnalysisMemoryContainer, calculation_spec
from test_document_analysis_final_results import source_manifest_for
from test_saved_analysis_service import saved_chat
from test_support.app_stubs import import_app_module
from test_support.orchestration_revisions import AtomicMemoryContainer
from test_support.document_analysis import USER_ID, FixtureAnalysisClient, document_analysis_runtime, original_document
from test_workflow_task_result_handoff import build_inventory_run


storage = import_app_module("functions_workflow_result_store")
checkpoints_module = import_app_module("functions_document_analysis_checkpoints")


@pytest.fixture
def fenced(saved_chat, monkeypatch):
    conversation = {"id": "conversation-1", "user_id": "owner", "title": "Analysis"}
    conversations = AtomicMemoryContainer("id")
    conversations.create_item(body=conversation)
    messages = AtomicMemoryContainer("conversation_id")
    messages.create_item(body={
        "id": "user-1", "conversation_id": "conversation-1", "role": "user",
        "content": "Explain risks.", "metadata": {"user_info": {"user_id": "owner"}},
    })
    results = AnalysisMemoryContainer()
    store = storage.WorkflowResultStore(results, None, "private-results")
    analysis = final_analysis(saved_chat)

    def authorize(user_id, item):
        if item.get("user_id") != user_id:
            raise PermissionError("not authorized")

    monkeypatch.setitem(sys.modules, "config", SimpleNamespace(
        cosmos_conversations_container=conversations, cosmos_messages_container=messages,
    ))
    monkeypatch.setitem(sys.modules, "functions_collaboration", SimpleNamespace(
        build_conversation_participation_context=authorize,
    ))
    monkeypatch.setitem(sys.modules, "functions_document_analysis_checkpoints", checkpoints_module)
    monkeypatch.setattr(storage, "_configured_result_store", lambda *args, **kwargs: store)

    def factory(*args, **kwargs):
        return checkpoints_module.analysis_checkpoints_for_chat(
            *args, store=store,
            source_authorizer=lambda user, sources, **options: saved.authorize_analysis_sources(
                user, sources, resolver=saved_chat["source_resolver"], **options,
            ),
            **kwargs,
        )

    def prepare(message_id="assistant-1", previous=None):
        return saved.prepare_chat_analysis(
            "owner", "conversation-1", message_id, resume_message_id=previous, checkpoint_factory=factory,
        )

    def save(attempt):
        return saved.save_chat_analysis(
            {"reply": analysis["reply"], "analysis_result": deepcopy(analysis)},
            user_id="owner", conversation_id="conversation-1", message_id=attempt.binding["message_id"],
            guard_token=attempt.token, source_resolver=saved_chat["source_resolver"],
            save_result=lambda user, conv, message, value, **kwargs: store.save_chat(
                user, conv, message, value, guard_token=kwargs["guard_token"], require_analysis_guard=True,
            ),
        )

    def delete_marker():
        current = conversations.read_item("conversation-1", "conversation-1")
        conversations.replace_item(
            item=current["id"], body={**current, "orchestration_deleted": True},
            etag=current["_etag"], match_condition=MatchConditions.IfNotModified,
        )

    return SimpleNamespace(
        conversations=conversations, messages=messages, results=results, store=store,
        prepare=prepare, save=save, delete_marker=delete_marker, analysis=analysis,
    )


def test_deletion_marker_blocks_direct_saved_access_and_preparation(fenced):
    fenced.delete_marker()
    with pytest.raises(saved.AnalysisResultUnavailable) as failure:
        saved._authorize_conversation("owner", "conversation-1")
    assert failure.value.code == "analysis_conversation_deleted"
    with pytest.raises(saved.AnalysisResultUnavailable):
        fenced.prepare()
    assert fenced.results.items == {}


def test_delete_between_preparation_checks_stops_the_new_guard(fenced, monkeypatch):
    original = fenced.store.prepare_analysis_attempt

    def prepare_after_delete(*args, **kwargs):
        fenced.delete_marker()
        return original(*args, **kwargs)

    monkeypatch.setattr(fenced.store, "prepare_analysis_attempt", prepare_after_delete)
    with pytest.raises(saved.AnalysisResultUnavailable):
        fenced.prepare()
    guard = fenced.store._analysis_guard(storage._chat_identity("owner", "conversation-1", "assistant-1"), required=True)
    assert guard["stopped"] is True
    assert not any(row.get("record_kind") == "chunk" for row in fenced.results.items.values())


def test_stop_before_prepare_prevents_a_late_worker_from_starting(fenced):
    storage.cancel_chat_analysis_results("owner", "conversation-1", "assistant-1")
    with pytest.raises(storage.AnalysisWorkUnitConflictError):
        fenced.prepare()
    assert not any(row.get("record_kind") == "chunk" for row in fenced.results.items.values())


def test_stop_between_guard_read_and_payload_batch_is_conditional(fenced, monkeypatch):
    attempt = fenced.prepare()
    original = fenced.results.execute_item_batch
    interrupted = []

    def cancel_before_batch(*args, **kwargs):
        if not interrupted:
            interrupted.append(True)
            storage.cancel_chat_analysis_results("owner", "conversation-1", "assistant-1")
        return original(*args, **kwargs)

    monkeypatch.setattr(fenced.results, "execute_item_batch", cancel_before_batch)
    with pytest.raises(storage.AnalysisWorkUnitConflictError):
        fenced.save(attempt)
    assert interrupted == [True]
    assert not any(row.get("record_kind") in {"chunk", "manifest"} for row in fenced.results.items.values())


def test_retry_successor_fences_old_worker_and_keeps_new_attempt_writable(fenced):
    old = fenced.prepare()
    new = fenced.prepare("assistant-2", previous="assistant-1")
    with pytest.raises(storage.AnalysisWorkUnitConflictError):
        fenced.save(old)
    descriptor = fenced.save(new)
    assert descriptor["message_id"] == "assistant-2"
    saved.assert_analysis_attempt_current(new)
    with pytest.raises(storage.AnalysisWorkUnitConflictError):
        saved.assert_analysis_attempt_current(old)


def test_user_turn_retry_association_is_conditional_and_actor_bound(fenced, monkeypatch):
    assert saved.bind_chat_analysis_attempt("owner", "conversation-1", "user-1", "assistant-1") is None
    assert saved.bind_chat_analysis_attempt("owner", "conversation-1", "user-1", "assistant-2") == "assistant-1"
    original = fenced.messages.replace_item
    changed = []

    def concurrent_retry(**kwargs):
        if not changed:
            changed.append(True)
            current = fenced.messages.read_item("user-1", "conversation-1")
            original(
                item="user-1", body={**current, "metadata": {
                    **current["metadata"], "analysis_attempt_message_id": "another-accepted-attempt",
                }}, etag=current["_etag"], match_condition=MatchConditions.IfNotModified,
            )
        return original(**kwargs)

    monkeypatch.setattr(fenced.messages, "replace_item", concurrent_retry)
    with pytest.raises(saved.AnalysisResultUnavailable):
        saved.bind_chat_analysis_attempt("owner", "conversation-1", "user-1", "stale-attempt")
    assert fenced.messages.read_item("user-1", "conversation-1")["metadata"]["analysis_attempt_message_id"] == "another-accepted-attempt"


def test_cached_conversation_update_cannot_erase_a_racing_deletion_marker(fenced, monkeypatch):
    cached = fenced.conversations.read_item("conversation-1", "conversation-1")
    original = fenced.conversations.replace_item
    changed = []

    def delete_before_replace(**kwargs):
        if not changed:
            changed.append(True)
            current = fenced.conversations.read_item("conversation-1", "conversation-1")
            original(
                item=current["id"], body={**current, "orchestration_deleted": True},
                etag=current["_etag"], match_condition=MatchConditions.IfNotModified,
            )
        return original(**kwargs)

    monkeypatch.setattr(fenced.conversations, "replace_item", delete_before_replace)
    with pytest.raises(saved.AnalysisResultUnavailable):
        saved.update_analysis_conversation("owner", {**cached, "title": "Late result"})
    current = fenced.conversations.read_item("conversation-1", "conversation-1")
    assert current["orchestration_deleted"] is True
    assert current["title"] != "Late result"


def test_cancel_route_fences_server_selected_attempt_before_acknowledging(fenced, monkeypatch):
    monkeypatch.setitem(sys.modules, "functions_workflow_result_store", storage)
    attempt = fenced.prepare()
    session = SimpleNamespace(
        request_cancel=lambda **kwargs: {"status": "cancel_requested"},
        get_analysis_message_id=lambda: "assistant-1",
    )
    app = Flask(__name__)
    namespace = {
        "jsonify": jsonify, "request": request, "get_current_user_id": lambda: "owner",
        "CHAT_STREAM_REGISTRY": SimpleNamespace(get_session=lambda *args, **kwargs: session),
        "authorize_analysis_conversation": saved._authorize_conversation,
    }
    load_functions("route_backend_chats.py", {"chat_stream_cancel_api"}, namespace)
    app.add_url_rule("/cancel", "cancel", lambda: namespace["chat_stream_cancel_api"]("conversation-1"), methods=["POST"])
    response = app.test_client().post("/cancel", json={"analysis_message_id": "not-the-server-attempt"})
    assert response.status_code == 200
    with pytest.raises(storage.AnalysisWorkUnitConflictError):
        fenced.save(attempt)


def test_stream_exposes_a_stable_server_attempt_before_work_not_in_public_status():
    cache = {}
    namespace = {
        "threading": threading, "logging": logging, "datetime": datetime,
        "_utcnow_iso": lambda: "2026-09-16T17:10:00",
        "STREAM_STATUS_STARTED": "started", "TERMINAL_STREAM_STATUSES": set(),
        "_safe_int": lambda value: int(value or 0), "_parse_iso_datetime": lambda value: None,
        "log_event": lambda *args, **kwargs: None,
        "app_settings_cache": SimpleNamespace(
            initialize_stream_session_cache=lambda key, value, **kwargs: cache.update({key: dict(value)}),
            get_stream_session_meta=lambda key: deepcopy(cache.get(key)),
        ),
    }
    load_functions("route_backend_chats.py", {"ActiveConversationStreamSession", "_build_stream_status_payload"}, namespace)
    stream = namespace["ActiveConversationStreamSession"](
        "owner", "conversation-1", analysis_message_id="server-created-assistant",
    )
    stream.initialize()
    assert stream.get_analysis_message_id() == "server-created-assistant"
    assert "analysis_message_id" not in stream.get_status_snapshot()
    assert "token" not in str(cache)


def test_live_runner_forwards_work_units_and_reuses_the_guarded_final_checkpoint():
    documents = {"source-1": original_document("source-1", ["The contract relies on a sole supplier."])}
    manifest = [{
        **source, "source_kind": "narrative", "file_name": "source-1.txt",
    } for source in source_manifest_for(documents)]
    store = storage.WorkflowResultStore(AnalysisMemoryContainer(), None, "private-results")

    def source_authorizer(user, sources, **kwargs):
        return saved.authorize_analysis_sources(
            user, sources, resolver=lambda ids, **context: deepcopy(manifest), **kwargs,
        )

    def attempt(message, previous=None):
        value = checkpoints_module.analysis_checkpoints_for_chat(
            USER_ID, "conversation-1", message, authorize=lambda: True,
            store=store, source_authorizer=source_authorizer, resume_message_id=previous,
        )
        value.prepare()
        return value

    first = attempt("assistant-first")
    model = FixtureAnalysisClient()
    with document_analysis_runtime(documents) as runtime:
        runner = runner_namespace(
            analysis_source_snapshot=access.analysis_source_snapshot,
            run_document_analysis=runtime.producer.run_document_analysis,
            resolve_analysis_source_manifest=lambda *args, **kwargs: deepcopy(manifest),
        )
        workflow = {"user_id": USER_ID, "task_prompt": "Explain the risks.", "_analysis_checkpoints": first}
        action = {"type": "analyze", "document_ids": ["source-1"], "window_size": 1}
        result = runner["_execute_mixed_source_analyze_workflow"](
            workflow, action, {}, model.invoke_prompt, conversation_id="conversation-1",
        )
        assert len(model.calls) == 1
        source_reads = len(runtime.source_reads)
        second = attempt("assistant-retry", previous="assistant-first")
        recovered = runner["_execute_mixed_source_analyze_workflow"](
            {**workflow, "_analysis_checkpoints": second}, action, {}, model.invoke_prompt,
            conversation_id="conversation-1",
        )
        assert recovered["authoritative_result"] == result["authoritative_result"]
        assert len(model.calls) == 1 and len(runtime.source_reads) == source_reads


def test_live_runner_applies_declared_calculations_before_reporting():
    documents = {"source-1": original_document("source-1", ["Amount: 2.675."])}
    manifest = [{**source, "source_kind": "narrative"} for source in source_manifest_for(documents)]
    model = FixtureAnalysisClient(lambda prompt: json.dumps({"findings": [{
        "finding_key": "amount", "values": {"amount": "2.675", "total": 93847},
        "status": "supported", "issues": [],
        "evidence": [{"chunk_sequence": 1, "quote": "Amount: 2.675."}],
    }]}))
    with document_analysis_runtime(documents) as runtime:
        runner = runner_namespace(
            run_document_analysis=runtime.producer.run_document_analysis,
            resolve_analysis_source_manifest=lambda *args, **kwargs: deepcopy(manifest),
        )
        result = runner["_execute_mixed_source_analyze_workflow"](
            {"user_id": USER_ID, "task_prompt": "Round the amount to two decimal places."},
            {
                "type": "analyze", "document_ids": ["source-1"],
                "analysis_options": {"transformation_spec": calculation_spec()},
            },
            {}, model.invoke_prompt, conversation_id="conversation-1",
        )
    assert result["authoritative_result"]["value"][0]["values"]["total"] == 2.68
    assert "2.68" in result["analysis_reply"]
    assert "93847" not in result["analysis_reply"]
    assert "93847" not in json.dumps(result["analysis_validation"])
    assert len(model.calls) == 1


@pytest.mark.parametrize("prepare_first", [False, True])
def test_deleting_pending_user_turn_fences_its_preallocated_assistant(fenced, prepare_first):
    saved.bind_chat_analysis_attempt("owner", "conversation-1", "user-1", "assistant-pending")
    attempt = fenced.prepare("assistant-pending") if prepare_first else None
    user_message = fenced.messages.read_item("user-1", "conversation-1")
    removed = []

    def delete_result(user_id, conversation_id, message_id):
        removed.append((user_id, conversation_id, message_id))
        fenced.store.delete_chat_results(user_id, conversation_id, message_id)

    saved.cleanup_chat_analysis_messages(
        [user_message], conversation_id="conversation-1", owner_user_id="owner",
        delete_result=delete_result, delete_thoughts=lambda *args: None,
        fence_result=lambda user, conversation, message: fenced.store.fence_analysis_attempt(
            storage._chat_identity(user, conversation, message),
        ),
    )
    assert removed == [("owner", "conversation-1", "assistant-pending")]
    with pytest.raises(storage.AnalysisWorkUnitConflictError):
        if attempt is not None:
            fenced.save(attempt)
        else:
            fenced.prepare("assistant-pending")


def test_workflow_task_retry_reuses_its_real_checkpointed_producer(monkeypatch):
    documents = {"source-1": original_document("source-1", ["The contract relies on a sole supplier."])}
    manifest = source_manifest_for(documents)
    store = storage.WorkflowResultStore(AnalysisMemoryContainer(), None, "private-results")
    original_factory = checkpoints_module.analysis_checkpoints_for_workflow
    prepared = []

    def factory(*args, **kwargs):
        result = original_factory(
            *args, **kwargs, store=store,
            source_authorizer=lambda user, sources, **options: saved.authorize_analysis_sources(
                user, sources, resolver=lambda ids, **context: deepcopy(manifest), **options,
            ),
        )
        prepared.append(result)
        return result

    monkeypatch.setattr(checkpoints_module, "analysis_checkpoints_for_workflow", factory)
    monkeypatch.setitem(sys.modules, "functions_document_analysis_checkpoints", checkpoints_module)
    runner, workflow, *_ = build_inventory_run()
    workflow.update(user_id=USER_ID, error_handling={"retry_count": 1})
    workflow["tasks"] = [{
        "id": "extract", "name": "Analyze", "instructions": "Explain the risks.",
        "document_action": {"type": "analyze", "document_ids": ["source-1"]},
    }]
    runner.update({
        "_get_current_workflow_runtime": lambda value: workflow,
        "_get_workflow_run_record": lambda value, run_id: {"id": run_id, "workflow_id": workflow["id"], "status": "running"},
    })
    load_functions("functions_workflow_runner.py", {"_prepare_workflow_analysis_checkpoints"}, runner)
    model = FixtureAnalysisClient()
    dispatched = []
    with document_analysis_runtime(documents) as runtime:
        def dispatch(attempt_workflow, *args, **kwargs):
            checkpoints = attempt_workflow["_analysis_checkpoints"]
            dispatched.append(checkpoints)
            result = runtime.producer.run_document_analysis(
                USER_ID, "Explain the risks.", ["source-1"], model.invoke_prompt,
                result_version="analyze-final-v1", source_manifest=manifest, work_unit_checkpoints=checkpoints,
            )
            if len(dispatched) == 1:
                raise RuntimeError("Reporting interrupted after extraction.")
            return {"analysis_result": result, "reply": result["analysis_reply"]}

        runner["_execute_workflow_dispatch"] = dispatch
        result = runner["_execute_workflow_task_sequence"](
            workflow, {}, "conversation-1", "run-1", None, {}, actor_user_id=USER_ID,
        )
    assert len(prepared) == 1
    assert len(dispatched) == 2 and dispatched[0] is dispatched[1]
    assert len(model.calls) == 1
    assert result["task_results"][0]["status"] == "succeeded"


def test_orchestration_live_adapter_prepares_and_passes_the_conditional_token(orchestration):
    fixture = orchestration
    store = storage.WorkflowResultStore(AnalysisMemoryContainer(), None, "private-results")
    prepared = []

    def factory(step_id):
        value = checkpoints_module.analysis_checkpoints_for_orchestration(
            "owner", "conversation-1", "run-1", step_id, authorize=lambda: True,
            store=store, attempt_token="existing-execution-lease-token",
        )
        fixture.context._guard_token = value.token
        prepared.append(value)
        return value

    fixture.context.analysis_checkpoint_factory = factory
    save_tokens = []
    original_save = fixture.store.save

    def save(*args, **kwargs):
        save_tokens.append(kwargs.get("guard_token"))
        return original_save(*args, **kwargs)

    fixture.store.save = save
    result = fixture.modules.adapters.run_document_analyze(
        {
            "step_id": "analyze-1", "capability_id": "document_analyze",
            "arguments": {"document_ids": ["source-1"], "analysis_prompt": "Find risks."},
        },
        fixture.context, settings={}, user_id="owner", emit=None, cancel_requested=lambda: False,
    )
    assert result["status"] == "completed", result
    guard = store._analysis_guard(prepared[0].binding, required=True)
    assert guard["token"] == "existing-execution-lease-token"
    assert fixture.state["producer_calls"][0][1]["work_unit_checkpoints"] is prepared[0]
    assert save_tokens and set(save_tokens) == {"existing-execution-lease-token"}


def test_direct_route_prepares_before_execution_and_persists_with_that_token(fenced, chat):
    prepared = []
    executed = []
    tokens = []
    namespace = chat.namespace
    original_execute = namespace["_execute_document_action_workflow"]

    def prepare(user, conversation, message, **kwargs):
        value = fenced.prepare(message, previous=kwargs.get("resume_message_id"))
        prepared.append(value)
        return value

    def execute(workflow, *args, **kwargs):
        guard = fenced.store._analysis_guard(prepared[-1].binding, required=True, writable=True, token=prepared[-1].token)
        assert guard["prepared"] is True
        assert workflow["_analysis_checkpoints"] is prepared[-1]
        executed.append(True)
        return original_execute(workflow, *args, **kwargs)

    def save_result(user, conversation, message, section, **kwargs):
        tokens.append(kwargs["guard_token"])
        return fenced.store.save_chat(
            user, conversation, message, section, guard_token=kwargs["guard_token"], require_analysis_guard=True,
        )

    namespace.update({
        "cosmos_messages_container": fenced.messages, "cosmos_conversations_container": fenced.conversations,
        "_load_or_create_analyze_conversation": lambda *args, **kwargs: fenced.conversations.read_item(
            "conversation-1", "conversation-1",
        ),
        "bind_chat_analysis_attempt": saved.bind_chat_analysis_attempt,
        "prepare_chat_analysis": prepare,
        "assert_analysis_attempt_current": saved.assert_analysis_attempt_current,
        "update_analysis_conversation": saved.update_analysis_conversation,
        "_execute_document_action_workflow": execute,
        "save_chat_analysis": lambda result, **kwargs: saved.save_chat_analysis(
            result, **kwargs, save_result=save_result, source_resolver=chat.options["source_resolver"],
        ),
    })
    body = {
        "conversation_id": "conversation-1", "message": "Find risks.", "model_id": "selected-model",
        "document_action": {"type": "analyze", "document_ids": ["document-1"], "doc_scope": "personal"},
    }
    response = chat.client.post("/api/chat/document-action", json=body)
    assert response.status_code == 200, response.get_json()
    assert executed == [True]
    assert tokens and set(tokens) == {prepared[0].token}
    descriptor = response.get_json()["metadata"]["saved_analysis"]
    assert descriptor["message_id"] == prepared[0].binding["message_id"]


@pytest.mark.parametrize("delete_at", ["model", "assistant_write"])
def test_deleted_followup_turn_cannot_publish_a_late_explanation(fenced, chat, monkeypatch, delete_at):
    namespace = chat.namespace
    original_upsert = fenced.messages.upsert_item
    original_delete = fenced.messages.delete_item
    deleted_turns = []

    def remove(item, partition_key, **kwargs):
        kwargs.setdefault("etag", fenced.messages.read_item(item, partition_key)["_etag"])
        return original_delete(item, partition_key, **kwargs)

    monkeypatch.setattr(fenced.messages, "delete_item", remove)

    def delete_pending_turn():
        user = next(
            row for row in fenced.messages.items.values()
            if row.get("role") == "user" and (row.get("metadata") or {}).get("analysis_attempt_message_id")
        )
        saved.cleanup_chat_analysis_messages(
            [user], conversation_id="conversation-1", owner_user_id="owner",
            fence_result=lambda actor, conv, message: fenced.store.fence_analysis_attempt(
                storage._chat_identity(actor, conv, message),
            ),
            delete_result=fenced.store.delete_chat_results, delete_thoughts=lambda *args: None,
        )
        remove(user["id"], "conversation-1")
        deleted_turns.append(user["id"])

    def upsert(body, **kwargs):
        if body.get("role") == "assistant" and delete_at == "assistant_write":
            delete_pending_turn()
        return original_upsert(body, **kwargs)

    monkeypatch.setattr(fenced.messages, "upsert_item", upsert)

    def complete(**kwargs):
        if delete_at == "model":
            delete_pending_turn()
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="A late saved-result explanation."))],
            usage=None,
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    namespace.update({
        "cosmos_messages_container": fenced.messages,
        "cosmos_conversations_container": fenced.conversations,
        "_load_or_create_analyze_conversation": lambda *args, **kwargs: fenced.conversations.read_item(
            "conversation-1", "conversation-1",
        ),
        "bind_chat_analysis_attempt": saved.bind_chat_analysis_attempt,
        "prepare_chat_analysis": lambda user, conv, message, **kwargs: fenced.prepare(
            message, previous=kwargs.get("resume_message_id"),
        ),
        "assert_analysis_attempt_current": saved.assert_analysis_attempt_current,
        "update_analysis_conversation": saved.update_analysis_conversation,
        "_resolve_model_workflow_client": lambda *args: (
            budget.WorkflowModelClient(client, {"id": "actual-selected-model"}, "aoai"),
            "actual-selected-deployment", "aoai",
        ),
    })
    response = chat.client.post("/api/chat", json=followup_body(chat))
    assert response.status_code != 200
    assert len(deleted_turns) == 1
    assert not any(row.get("role") == "assistant" for row in fenced.messages.items.values())
