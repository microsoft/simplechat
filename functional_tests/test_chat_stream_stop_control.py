#!/usr/bin/env python3
# test_chat_stream_stop_control.py
"""
Functional test for chat stream stop control.
Version: 0.261.485
Implemented in: 0.241.097
Durable submission/terminal authority corrected in: 0.261.430

This test ensures chat streams expose a user-scoped cancellation endpoint,
persist cancellation state, wire collaborative streams through their source
conversation, and render a message-local Stop control in the frontend.
"""

import sys
import inspect
import json
from copy import deepcopy
from contextlib import nullcontext
from pathlib import Path
import traceback
from types import SimpleNamespace

from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos._cosmos_responses import CosmosDict
import pytest

from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
# Shared UI I/O fixtures must also resolve from this file's standalone entrypoint.
sys.path.insert(0, str(ROOT))
from ui_tests.fixtures.chat_stop_runtime import StopMessageContainer, stop_modules, stop_world  # noqa: E402,F401


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def assert_contains(content: str, expected: str, label: str) -> None:
    if expected not in content:
        raise AssertionError(f"Expected {label} to contain {expected!r}")


def test_chat_stream_stop_control_wiring() -> None:
    """Validate backend, collaboration, frontend, docs, and version wiring."""
    print("Testing chat stream stop control wiring...")

    route_content = read_text("application/single_app/route_backend_chats.py")
    collaboration_content = read_text("application/single_app/route_backend_collaboration.py")
    streaming_content = read_text("application/single_app/static/js/chat/chat-streaming.js")
    collaboration_js_content = read_text("application/single_app/static/js/chat/chat-collaboration.js")
    feature_doc_content = read_text("docs/explanation/features/v0.241.097/CHAT_STREAM_STOP_CONTROL.md")

    assert_app_version_at_least("0.250.070")

    assert_contains(route_content, "STREAM_STATUS_CANCEL_REQUESTED = 'cancel_requested'", "chat route")
    assert_contains(route_content, "STREAM_STATUS_CANCELED = 'canceled'", "chat route")
    assert_contains(route_content, "def request_cancel(self, reason='user_requested'):", "chat stream session")
    assert_contains(route_content, "def is_cancel_requested(self,", "chat stream session")
    assert_contains(route_content, "def _build_stream_cancel_event(", "cancel event builder")
    assert_contains(route_content, "@bp.route('/api/chat/stream/cancel/<conversation_id>', methods=['POST'])", "chat cancel route")
    assert_contains(route_content, "if stream_cancel_requested():", "stream cancellation checkpoints")
    assert_contains(route_content, "yield finalize_cancelled_stream_response()", "cancelled stream finalization")

    assert_contains(
        collaboration_content,
        "@bp.route('/api/collaboration/conversations/<conversation_id>/stream/cancel', methods=['POST'])",
        "collaboration cancel route",
    )
    assert_contains(collaboration_content, "source_conversation_id = str((conversation_doc or {}).get('source_conversation_id')", "source conversation lookup")
    assert_contains(collaboration_content, "CHAT_STREAM_REGISTRY.get_session(", "collaboration source stream lookup")
    assert_contains(collaboration_content, "stream_payload.get('cancelled') or stream_payload.get('canceled')", "collaboration cancel transform")

    assert_contains(streaming_content, "className = 'btn btn-sm stream-stop-btn", "message-local Stop button")
    assert_contains(streaming_content, "rounded-circle p-0 border-0", "compact icon-only Stop button")
    assert_contains(streaming_content, "async function requestStreamCancellation", "frontend cancel request")
    assert_contains(streaming_content, "fetch(streamContext.cancelEndpoint", "cancel endpoint POST")
    assert_contains(streaming_content, "finalizeCancelledStreamingMessage", "cancelled UI finalizer")
    assert_contains(streaming_content, "Stopped by you.", "stopped response banner")

    assert_contains(collaboration_js_content, "cancelEndpoint: `/api/collaboration/conversations/${encodeURIComponent(conversationId)}/stream/cancel`", "collaboration frontend cancel endpoint")
    assert_contains(feature_doc_content, "Implemented in version: **0.241.097**", "feature documentation")
    assert_contains(feature_doc_content, "Updated in version: **0.241.098**", "feature documentation refinement")
    assert_contains(feature_doc_content, "application/single_app/config.py", "feature documentation version reference")

    print("Chat stream stop control wiring verified")


def admit(world, store=None):
    store = store or world.store()
    store.begin({"message": "Question A"}, world.question)
    return store


def test_cancel_before_admission_is_accepted_by_the_real_route(stop_world):
    response = stop_world.app.test_client().post(
        "/api/chat/stream/cancel/chat", json={"submission_id": "submission-a"},
    )
    assert response.status_code == 200
    assert response.json["outcome"] == "accepted"
    assert response.json["dispatch_prevented"] is True
    assert len(stop_world.controls.items) == 1


def test_attempt_storage_owner_uses_sdk_points_and_cancel_before_dispatch(stop_world):
    store = stop_world.store()
    assert store.cancel()["outcome"] == "accepted"
    record = store.begin({"message": "Question A"}, stop_world.question)
    assert type(record) is dict
    assert record["_etag"]
    assert store.dispatch() is False
    saved = stop_world.messages.read_item("question-a", "chat")
    assert type(saved) is CosmosDict
    assert saved["metadata"]["response_attempt"]["submission_id"] == "submission-a"
    assert saved["metadata"]["response_attempt"]["state"] == "interrupted"
    assert len(stop_world.messages.items) == 1


def test_cancel_wins_the_terminal_cas_and_fences_a_stale_success_writer(stop_world):
    store = admit(stop_world)
    assert store.dispatch() is True
    stale_worker = stop_world.store()
    stop_world.controls.before_replace = lambda: store.cancel()
    with pytest.raises(stop_world.retry.ChatRetryError) as failure:
        stale_worker.commit(stop_world.reply)
    assert failure.value.code == "chat_attempt_canceled"
    assert ("chat", "reply-a") not in stop_world.messages.items
    partial = deepcopy(stop_world.reply)
    partial["metadata"].update({"incomplete": True, "canceled": True, "cancel_reason": "user_requested"})
    stored = stale_worker.commit(partial)
    assert stored["metadata"]["stream_status"] == "stopped"
    assert stored["metadata"]["complete"] is False
    assert stored["metadata"]["response_attempt"]["submission_id"] == "submission-a"


def test_committed_completion_wins_even_before_cross_container_materialization(stop_world):
    store = admit(stop_world)
    assert store.dispatch() is True
    stop_world.messages.fail_writes = True
    with pytest.raises(AzureError):
        store.commit(stop_world.reply)
    assert stop_world.store().cancel()["outcome"] == "already_completed"
    stop_world.messages.fail_writes = False
    stored = stop_world.store().materialize()
    assert stored["content"] == stop_world.reply["content"]
    assert stored["metadata"]["complete"] is True
    again = stop_world.store().materialize()
    assert again["id"] == stored["id"]
    assert len(stop_world.messages.items) == 2


def test_late_cancel_for_a_cannot_cancel_b_or_reuse_its_identity(stop_world):
    first = admit(stop_world)
    assert first.dispatch()
    first.commit(stop_world.reply)
    second = stop_world.store("submission-b")
    question = {**deepcopy(stop_world.question), "id": "question-b"}
    question["metadata"]["thread_info"]["thread_id"] = "thread-b"
    second.begin({"message": "Question B"}, question)
    assert second.dispatch()
    assert first.cancel()["outcome"] == "already_completed"
    assert second.read()["state"] == "running"
    with pytest.raises(stop_world.retry.ChatRetryError) as failure:
        first.begin({"message": "Conflicting content"}, question)
    assert failure.value.code == "submission_conflict"


def test_control_reads_and_intents_recheck_authority_before_storage(stop_world):
    before = len(stop_world.controls.items)
    with pytest.raises(PermissionError):
        stop_world.store(actor="other").cancel()
    with pytest.raises(PermissionError):
        stop_world.store(actor="other").read()
    assert len(stop_world.controls.items) == before
    stop_world.conversations.upsert_item({"id": "chat", "user_id": "other"})
    with pytest.raises(PermissionError):
        stop_world.store().cancel()


def test_stop_storage_failure_is_not_acknowledged_from_local_registry(stop_world):
    stop_world.controls.fail_writes = True
    response = stop_world.app.test_client().post(
        "/api/chat/stream/cancel/chat", json={"submission_id": "submission-a"},
    )
    assert response.status_code == 503
    assert response.json["outcome"] == "unconfirmed"
    assert "Private test" not in str(response.json)


def test_provider_interruption_is_not_projected_as_stopped_by_user(stop_world):
    store = admit(stop_world)
    assert store.dispatch()
    interrupted = deepcopy(stop_world.reply)
    interrupted["metadata"].update(incomplete=True, canceled=True, cancel_reason="user_requested", stop_reason="user_cancelled")
    saved = store.commit(interrupted)
    assert saved["metadata"]["stream_status"] == "interrupted"
    assert saved["metadata"]["stop_reason"] == "provider_interrupted"
    assert saved["metadata"].get("canceled") is not True
    assert saved["metadata"].get("cancel_reason") != "user_requested"
    assert store.cancel()["outcome"] == "already_completed"
    assert store.materialize()["metadata"]["stop_reason"] == "provider_interrupted"


def test_terminal_failure_cannot_be_overwritten_by_a_stale_success(stop_world):
    store = admit(stop_world)
    assert store.dispatch()
    store.finish_without_reply("failed")
    with pytest.raises(stop_world.retry.ChatRetryError) as failure:
        stop_world.store().commit(stop_world.reply)
    assert failure.value.code == "chat_attempt_terminal"


def test_bound_server_assistant_identity_cannot_be_replaced(stop_world):
    store = stop_world.store()
    store.begin({"message": "Question A"}, stop_world.question, assistant_message_id="reply-a")
    assert store.dispatch()
    wrong_reply = {**deepcopy(stop_world.reply), "id": "older-reply"}
    with pytest.raises(stop_world.retry.ChatRetryError) as failure:
        store.commit(wrong_reply)
    assert failure.value.code == "submission_conflict"
    assert store.read()["state"] == "running"
    assert store.commit(stop_world.reply)["id"] == "reply-a"


@pytest.mark.parametrize("edited", [False, True])
def test_existing_retry_and_edit_share_native_sdk_submission_and_attempt_binding(stop_world, edited):
    world = stop_world
    world.messages.create_item(body=world.question)
    world.messages.create_item(body=world.reply)
    source = world.messages.read_item("question-a", "chat")
    prepared = world.retry.prepare_retry_attempt(
        world.messages, world.conversations, "owner", source,
        {"message": "Edited question" if edited else "Question A", "conversation_id": "chat"},
        submission_id="retry-submission", edited=edited,
    )
    assert type(prepared) is CosmosDict
    claimed = world.retry.claim_retry_attempt(
        world.messages, world.conversations, "owner", "chat", prepared["id"],
        thread_id=prepared["metadata"]["thread_info"]["thread_id"],
        thread_attempt=prepared["metadata"]["thread_info"]["thread_attempt"],
    )
    assert type(claimed) is CosmosDict
    store = world.store("retry-submission")
    store.begin({"message": claimed["content"]}, claimed, assistant_message_id="retry-reply")
    assert store.dispatch()
    answer = {**deepcopy(world.reply), "id": "retry-reply"}
    saved = store.commit(answer)
    assert saved["metadata"]["response_attempt"]["submission_id"] == "retry-submission"
    assert saved["metadata"]["thread_info"]["thread_attempt"] == 2
    assert saved["metadata"]["thread_info"]["thread_id"] == "thread-a"


def test_materialization_never_resurrects_a_deleted_question(stop_world):
    world = stop_world
    store = admit(world)
    assert store.dispatch()
    question = world.messages.read_item("question-a", "chat")
    world.messages.delete_item("question-a", "chat", etag=question["_etag"])
    with pytest.raises(world.retry.ChatRetryError) as failure:
        store.commit(world.reply)
    assert failure.value.code == "message_not_found"
    assert ("chat", "question-a") not in world.messages.items
    assert ("chat", "reply-a") not in world.messages.items


def test_screened_safety_replacement_preserves_attempt_binding_without_publishing_rejected_text(stop_world, monkeypatch):
    import functions_chat_content_checks as checks

    store = stop_world.store()
    store.begin({"message": "Question A"}, stop_world.question, assistant_message_id="reply-a")
    assert store.dispatch()
    monkeypatch.setattr(checks, "check_chat_content", lambda *args, **kwargs: checks.ChatContentDecision(
        "chat_output", "findings", "block", {"attempted_at": "2026-11-16T20:00:01Z"}, "Response removed.",
    ))
    monkeypatch.setattr(stop_world.chats, "record_chat_content_incident", lambda *args: None)
    with stop_world.app.test_request_context("/"):
        saved = stop_world.chats._persist_screened_assistant(
            deepcopy(stop_world.reply), "owner", settings={}, attempt_store=store,
        )
    assert saved["role"] == "safety" and saved["content"] == "Response removed."
    assert saved["metadata"]["response_attempt"]["submission_id"] == "submission-a"
    assert store.read()["state"] == "failed"


def test_durable_terminal_status_overrides_stale_active_replay_cache(stop_world, monkeypatch):
    world = stop_world
    store = admit(world)
    assert store.dispatch()
    monkeypatch.setattr(world.chats, "get_settings", lambda *args, **kwargs: {})
    session = world.chats.CHAT_STREAM_REGISTRY.start_session(
        "owner", "chat", submission_id="submission-a", attempt_store=store,
    )
    store.commit(world.reply)
    assert session.is_active() is True
    response = world.app.test_client().get("/api/chat/stream/status/chat?submission_id=submission-a")
    assert response.status_code == 200 and response.json["pending"] is False
    assert response.json["attempt_state"] == "completed"
    world.controls.fail_reads = True
    response = world.app.test_client().get("/api/chat/stream/status/chat?submission_id=submission-a")
    assert response.status_code == 503 and response.json["outcome"] == "unconfirmed"


@pytest.mark.parametrize("completion_wins", [False, True])
def test_real_background_publisher_serializes_terminal_frames_with_durable_decision(stop_world, monkeypatch, completion_wins):
    world = stop_world
    store = admit(world)
    assert store.dispatch()
    jobs = []
    world.app.extensions["executor"] = SimpleNamespace(submit=jobs.append)
    monkeypatch.setattr(world.chats, "get_settings", lambda *args, **kwargs: {})
    monkeypatch.setattr(world.chats, "m365_action_card_events", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(world.chats, "_attach_request_m365_pending_action_cards", lambda payload, *args: payload)
    monkeypatch.setattr(world.chats, "complete_m365_request", lambda **kwargs: None)
    monkeypatch.setattr(world.chats, "log_chat_execution_outcome", lambda **kwargs: None)
    monkeypatch.setattr(world.chats, "_release_chat_destination_lease", lambda *args, **kwargs: None)
    session = world.chats.CHAT_STREAM_REGISTRY.start_session(
        "owner", "chat", submission_id="submission-a", attempt_store=store,
    )
    if completion_wins:
        store.commit(world.reply)
        assert store.cancel()["outcome"] == "already_completed"
        terminal = {"type": "cancelled", "done": True, "cancelled": True, "full_content": "stale partial"}
    else:
        store.cancel()
        terminal = {"done": True, "message_id": "older-reply", "full_content": "Must not publish success"}
    entry = world.app.view_functions["stop.chat_stream_api"]
    background = inspect.getclosurevars(inspect.unwrap(entry)).nonlocals["build_background_stream_response"]
    with world.app.test_request_context("/api/chat/stream", method="POST", json={}):
        response = background(lambda: iter([f"data: {json.dumps(terminal)}\n\n"]), stream_session=session)
    jobs[0]()
    frames = [json.loads(frame[6:]) for frame in response.get_data(as_text=True).strip().split("\n\n") if frame.startswith("data: ")]
    final = frames[-1]
    if completion_wins:
        assert final["cancelled"] is False and final["message_id"] == "reply-a"
        assert final["full_content"] == world.reply["content"]
    else:
        assert final["cancelled"] is True and final["user_message_id"] == "question-a"
        assert final["message_id"] is None
        assert "Must not publish success" not in str(final)


def test_real_history_route_recovers_committed_outbox_with_exact_identity(stop_world):
    store = admit(stop_world)
    assert store.dispatch()
    stop_world.messages.fail_writes = True
    with pytest.raises(AzureError):
        store.commit(stop_world.reply)
    stop_world.messages.fail_writes = False
    response = stop_world.app.test_client().get("/api/get_messages?conversation_id=chat")
    assert response.status_code == 200, response.json
    assistant = next(row for row in response.json["messages"] if row["role"] == "assistant")
    assert assistant["id"] == "reply-a"
    assert assistant["metadata"]["response_attempt"]["submission_id"] == "submission-a"
    assert assistant["metadata"]["complete"] is True


def test_undispatched_admission_recovers_the_original_question_and_dispatches_once(stop_world):
    world = stop_world
    store = world.store()
    world.messages.fail_writes = True
    with pytest.raises(AzureError):
        store.begin({"message": "Question A"}, world.question, assistant_message_id="reply-a")
    assert store.read()["admitted"] is True
    assert store.read()["dispatched"] is False
    world.messages.fail_writes = False
    proposed = {**deepcopy(world.question), "id": "must-not-replace-original-question"}
    recovered = world.store().begin(
        {"message": "Question A"}, proposed, assistant_message_id="must-not-replace-original-reply",
    )
    assert recovered["user_message_id"] == "question-a"
    assert recovered["assistant_message_id"] == "reply-a"
    assert set(world.messages.items) == {("chat", "question-a")}
    assert world.store().dispatch() is True
    with pytest.raises(world.retry.ChatRetryError) as duplicate:
        world.store().dispatch()
    assert duplicate.value.code == "retry_already_submitted"
    with pytest.raises(world.retry.ChatRetryError) as conflicting:
        world.store().begin({"message": "Different"}, world.question)
    assert conflicting.value.code == "submission_conflict"


def test_history_recovers_prepared_question_without_dispatching_it(stop_world):
    world = stop_world
    world.messages.fail_writes = True
    with pytest.raises(AzureError):
        admit(world)
    world.messages.fail_writes = False
    response = world.app.test_client().get("/api/get_messages?conversation_id=chat")
    assert response.status_code == 200, response.json
    assert [row["id"] for row in response.json["messages"]] == ["question-a"]
    assert world.store().read()["dispatched"] is False


def shared_attempt(world):
    shared = world.shared.read_item("shared", "shared")
    shared["source_conversation_id"] = "chat"
    world.shared.upsert_item(shared)
    source = world.conversations.read_item("chat", "chat")
    source.update(conversation_kind="collaboration_source", collaboration_conversation_id="shared")
    world.conversations.upsert_item(source)
    world.shared_messages.create_item({
        "id": "shared-question", "conversation_id": "shared", "role": "user",
        "content": "Question A", "message_kind": "ai_request",
        "metadata": {"sender": {"user_id": "owner"}, "source_conversation_id": "chat"},
    })

    def authorize():
        current = world.collaboration_owner.get_collaboration_conversation("shared")
        world.collaboration_owner.assert_user_can_participate_in_collaboration_conversation(
            world.actor["value"], current,
        )
        return current

    store = world.retry.ChatAttemptStore(
        world.controls, world.messages, actor_id="owner", conversation_id="chat",
        destination_id="shared", submission_id="submission-a", authorize=authorize,
    )
    store.begin({
        "message": "Question A", "m365_collaboration_message_id": "shared-question",
    }, world.question, assistant_message_id="reply-a")
    assert store.dispatch()
    return store


@pytest.mark.parametrize("viewer", ["owner", "collaborator"])
def test_shared_history_recovers_canonical_destination_outbox_without_execution_authority(stop_world, viewer):
    world = stop_world
    store = shared_attempt(world)
    world.messages.fail_writes = True
    with pytest.raises(AzureError):
        store.commit(world.reply)
    world.messages.fail_writes = False
    world.actor["value"] = viewer
    response = world.app.test_client().get("/api/collaboration/conversations/shared/messages")
    assert response.status_code == 200, response.json
    answers = [row for row in response.json["messages"] if row["role"] == "assistant"]
    assert len(answers) == 1
    answer = answers[0]
    assert answer["metadata"]["source_message_id"] == "reply-a"
    assert answer["metadata"]["response_attempt"]["submission_id"] == "submission-a"
    repeated = world.app.test_client().get("/api/collaboration/conversations/shared/messages")
    assert repeated.status_code == 200
    assert len([row for row in repeated.json["messages"] if row["role"] == "assistant"]) == 1
    assert store.read()["dispatched"] is True
    if viewer == "collaborator":
        stopped = world.app.test_client().post(
            "/api/collaboration/conversations/shared/stream/cancel",
            json={"submission_id": "submission-a"},
        )
        # A separate actor may reserve its own pre-admission intent with this
        # text ID; that is not authority over the generating owner's record.
        assert stopped.status_code in (200, 403, 404, 409)
        assert not store.read().get("cancel_reason")


@pytest.mark.parametrize("target,soft", [
    ("question-a", False), ("question-a", True), ("reply-a", False), ("reply-a", True),
])
def test_settled_interruption_history_honors_intentional_deletion(stop_world, target, soft):
    world = stop_world
    store = admit(world)
    assert store.dispatch()
    store.cancel()
    reply = deepcopy(world.reply)
    reply["metadata"]["incomplete"] = True
    store.commit(reply)
    current = world.messages.read_item(target, "chat")
    if soft:
        current.setdefault("metadata", {})["is_deleted"] = True
        world.messages.replace_item(
            target, current, etag=current["_etag"], match_condition=MatchConditions.IfNotModified,
        )
    else:
        world.messages.delete_item(target, "chat", etag=current["_etag"])
    for _ in range(2):
        response = world.app.test_client().get("/api/get_messages?conversation_id=chat")
        assert response.status_code == 200, response.json
        assert target not in {row["id"] for row in response.json["messages"]}
    if not soft:
        assert ("chat", target) not in world.messages.items


def test_late_stopped_partial_does_not_reactivate_a_prepared_retry(stop_world):
    world = stop_world
    store = admit(world)
    assert store.dispatch()
    store.cancel()
    source = world.messages.read_item("question-a", "chat")
    prepared = world.retry.prepare_retry_attempt(
        world.messages, world.conversations, "owner", source,
        {"message": "Question A", "conversation_id": "chat"}, submission_id="submission-b",
    )
    reply = deepcopy(world.reply)
    reply["metadata"]["incomplete"] = True
    saved = store.commit(reply)
    assert saved["metadata"]["thread_info"]["active_thread"] is False
    response = world.app.test_client().get("/api/get_messages?conversation_id=chat")
    assert response.status_code == 200
    assert [row["id"] for row in response.json["messages"]] == [prepared["id"]]


@pytest.mark.parametrize("selection_first", [False, True])
def test_retry_selection_and_late_publication_share_the_question_etag_fence(stop_world, selection_first):
    world = stop_world
    store = admit(world)
    assert store.dispatch()
    store.cancel()
    reply = deepcopy(world.reply)
    reply["metadata"]["incomplete"] = True
    prepared = []

    def prepare():
        prepared.append(world.retry.prepare_retry_attempt(
            world.messages, world.conversations, "owner",
            world.messages.read_item("question-a", "chat"),
            {"message": "Question A", "conversation_id": "chat"}, submission_id="submission-b",
        ))

    if selection_first:
        # A queried selection must retry if the missing reply is published before its batch.
        world.messages.before_batch = lambda: store.commit(reply)
        prepare()
    else:
        # Publication must retry if selecting B changes its question after its read.
        world.messages.before_batch = prepare
        store.commit(reply)
    assert prepared
    assert world.messages.read_item("question-a", "chat")["metadata"]["thread_info"]["active_thread"] is False
    assert world.messages.read_item("reply-a", "chat")["metadata"]["thread_info"]["active_thread"] is False
    assert world.messages.read_item(prepared[0]["id"], "chat")["metadata"]["thread_info"]["active_thread"] is True


@pytest.mark.parametrize("mutation", ["soft_delete", "edit", "hard_delete"])
def test_duplicate_outbox_materialization_preserves_intervening_message_mutation(stop_world, mutation):
    world = stop_world
    store = admit(world)
    assert store.dispatch()
    world.messages.fail_writes = True
    with pytest.raises(AzureError):
        store.commit(world.reply)
    world.messages.fail_writes = False
    # Match the production .430 publisher, including its dangerous fresh-ETag reread.
    store.publish = lambda message: world.chats.persist_chat_reply(world.messages, message)
    reached = []

    def concurrent_materializer(item, partition):
        assert (item, partition) == ("reply-a", "chat")
        winner = world.store().materialize()
        reached.append(winner["id"])
        current = world.messages.read_item(item, partition)
        if mutation == "hard_delete":
            world.messages.delete_item(item, partition, etag=current["_etag"])
        else:
            if mutation == "soft_delete":
                current["metadata"]["is_deleted"] = True
            else:
                current["content"] = "Legitimate revised answer"
                current["metadata"]["legitimate_note"] = "retain"
            world.messages.replace_item(
                item, current, etag=current["_etag"], match_condition=MatchConditions.IfNotModified,
            )

    world.messages.after_missing_read = concurrent_materializer
    store.materialize()
    assert reached == ["reply-a"]
    if mutation == "hard_delete":
        assert ("chat", "reply-a") not in world.messages.items
    else:
        current = world.messages.read_item("reply-a", "chat")
        if mutation == "soft_delete":
            assert current["metadata"]["is_deleted"] is True
        else:
            assert current["content"] == "Legitimate revised answer"
            assert current["metadata"]["legitimate_note"] == "retain"


@pytest.mark.parametrize("failure", ["membership", "source_binding", "source_storage"])
def test_shared_recovery_rechecks_membership_source_relationship_and_storage(stop_world, failure):
    world = stop_world
    store = shared_attempt(world)
    world.messages.fail_writes = True
    with pytest.raises(AzureError):
        store.commit(world.reply)
    world.messages.fail_writes = False
    world.actor["value"] = "collaborator"
    if failure == "membership":
        member = world.members.read_item("collaborator:shared", "collaborator")
        member["membership_status"] = "removed"
        world.members.upsert_item(member)
    elif failure == "source_binding":
        source = world.conversations.read_item("chat", "chat")
        source["collaboration_conversation_id"] = "different-destination"
        world.conversations.upsert_item(source)
    else:
        world.conversations.fail_reads = True
    response = world.app.test_client().get("/api/collaboration/conversations/shared/messages")
    assert response.status_code == (503 if failure == "source_storage" else 403)
    assert "Private test" not in str(response.json)
    assert store.controls.read_item(store.item_id, "shared").get("outbox")
    assert not world.shared_messages.items.get(("shared", "shared_chat_reply-a"))


def test_shared_recovery_retries_publication_failure_but_not_settled_shared_deletion(stop_world):
    world = stop_world
    store = shared_attempt(world)
    store.commit(world.reply)
    world.shared_messages.fail_writes = True
    response = world.app.test_client().get("/api/collaboration/conversations/shared/messages")
    assert response.status_code == 503
    assert store.read()["materialized"] is True
    assert not store.read().get("destination_materialized")
    world.shared_messages.fail_writes = False
    response = world.app.test_client().get("/api/collaboration/conversations/shared/messages")
    assert response.status_code == 200
    answer = next(row for row in response.json["messages"] if row["role"] == "assistant")
    saved = world.shared_messages.read_item(answer["id"], "shared")
    world.shared_messages.delete_item(answer["id"], "shared", etag=saved["_etag"])
    response = world.app.test_client().get("/api/collaboration/conversations/shared/messages")
    assert response.status_code == 200
    assert not any(row["role"] == "assistant" for row in response.json["messages"])
    assert ("shared", answer["id"]) not in world.shared_messages.items


def test_history_does_not_hide_unexpected_pending_outbox_storage_failure(stop_world):
    world = stop_world
    store = admit(world)
    store.dispatch()
    world.messages.fail_writes = True
    with pytest.raises(AzureError):
        store.commit(world.reply)
    failed = world.app.test_client().get("/api/get_messages?conversation_id=chat")
    assert failed.status_code == 503
    assert store.read().get("outbox")
    world.messages.fail_writes = False
    recovered = world.app.test_client().get("/api/get_messages?conversation_id=chat")
    assert recovered.status_code == 200
    assert next(row for row in recovered.json["messages"] if row["role"] == "assistant")["id"] == "reply-a"


def test_cancel_intent_is_bounded_and_expired_identity_cannot_dispatch(stop_world):
    store = stop_world.store()
    store.cancel()
    expired = stop_world.store(clock=lambda: 2000)
    with pytest.raises(stop_world.retry.ChatRetryError) as failure:
        expired.begin({"message": "Question A"}, stop_world.question)
    assert failure.value.code == "submission_expired"
    assert not stop_world.messages.items


@pytest.mark.parametrize("admitted_before_stop", [False, True])
def test_real_stream_route_honors_stop_at_admission_and_dispatch_barriers(
    stop_world, monkeypatch, admitted_before_stop,
):
    """Run the actual stream generator only after the cancel request has committed."""
    world = stop_world
    from functions_chat_content_checks import ChatContentDecision

    chats = world.chats
    older = {**deepcopy(world.reply), "id": "older-direct-reply"}
    world.messages.create_item(older)
    jobs = []
    world.app.extensions["executor"] = SimpleNamespace(submit=jobs.append)
    monkeypatch.setattr(chats, "get_settings", lambda *args, **kwargs: {})
    monkeypatch.setattr(chats, "get_current_user_info", lambda: {"userId": "owner"})
    monkeypatch.setattr(chats, "check_chat_content", lambda *args, **kwargs: ChatContentDecision("chat_input", "not_required", "allow", {}))
    monkeypatch.setattr(chats, "_get_authorized_chat_scope_context", lambda *args, **kwargs: {
        "active_group_id": None, "active_group_ids": [],
        "active_public_workspace_id": None, "active_public_workspace_ids": [],
    })
    monkeypatch.setattr(chats, "_apply_admin_new_conversation_model_defaults", lambda *args, **kwargs: None)
    monkeypatch.setattr(chats, "_acquire_chat_destination_lease", lambda *args, **kwargs: None)
    monkeypatch.setattr(chats, "_release_chat_destination_lease", lambda *args, **kwargs: None)
    monkeypatch.setattr(chats, "_resolve_chat_conversation_references", lambda *args, **kwargs: None)
    monkeypatch.setattr(chats, "m365_action_card_events", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(chats, "_attach_request_m365_pending_action_cards", lambda payload, *args: payload)
    monkeypatch.setattr(chats, "complete_m365_request", lambda **kwargs: None)
    monkeypatch.setattr(chats, "log_chat_execution_outcome", lambda **kwargs: None)
    monkeypatch.setattr(chats, "initialize_m365_chat_context",
                        lambda *args, **kwargs: pytest.fail("A canceled attempt must not enter producer preparation"))

    def open_stream():
        with world.app.test_request_context("/api/chat/stream", method="POST", json={
            "conversation_id": "chat", "message": "Question A", "submission_id": "submission-a",
        }):
            return world.app.make_response(world.app.view_functions["stop.chat_stream_api"]())

    response = open_stream() if admitted_before_stop else None
    canceled = world.app.test_client().post("/api/chat/stream/cancel/chat", json={"submission_id": "submission-a"})
    assert canceled.status_code == 200 and canceled.json["outcome"] == "accepted"
    response = response or open_stream()
    assert response.status_code == 200
    assert world.store().read()["assistant_message_id"].startswith("chat_assistant_")
    assert len(jobs) == 1
    jobs[0]()
    frames = response.get_data(as_text=True)
    assert '"cancelled": true' in frames
    assert '"submission_id": "submission-a"' in frames
    users = [value for value in world.messages.items.values() if value.get("role") == "user"]
    assert len(users) == 1 and len(world.messages.items) == 2
    assert users[0]["metadata"]["response_attempt"]["state"] == "interrupted"
    assert users[0]["metadata"]["thread_info"]["previous_thread_id"] == "thread-a"
    assert world.messages.read_item("older-direct-reply", "chat")["content"] == older["content"]


def test_registry_replay_keys_cannot_be_overwritten_by_the_previous_submission(stop_world):
    registry = stop_world.chats.CHAT_STREAM_REGISTRY
    first = registry.start_session("owner", "chat", submission_id="submission-a")
    first.publish('data: {"content":"A"}\n\n')
    second = registry.start_session("owner", "chat", submission_id="submission-b")
    first.publish('data: {"content":"late A"}\n\n')
    second.publish('data: {"content":"B"}\n\n')
    assert first.cache_key != second.cache_key
    assert registry.get_session("owner", "chat", submission_id="submission-a") is first
    assert registry.get_session("owner", "chat") is second
    assert second._get_metadata()["content_chars"] == 1


def test_collaborative_stop_before_hidden_source_admission_uses_authorized_canonical_destination(stop_world):
    world = stop_world
    response = world.app.test_client().post(
        "/api/collaboration/conversations/shared/stream/cancel",
        json={"submission_id": "submission-a", "user_id": "not-the-actor"},
    )
    assert response.status_code == 200 and response.json["outcome"] == "accepted"
    store = world.retry.ChatAttemptStore(
        world.controls, world.messages, actor_id="owner", conversation_id="chat",
        destination_id="shared", submission_id="submission-a", authorize=world.authorize,
        clock=lambda: 1000,
    )
    store.begin({"message": "Question A"}, world.question)
    assert store.dispatch() is False
    assert store.read()["user_id"] == "owner"
    assert store.read()["conversation_id"] == "chat"


def test_collaborator_cannot_cancel_the_generating_users_submission(stop_world):
    world = stop_world
    store = world.retry.ChatAttemptStore(
        world.controls, world.messages, actor_id="owner", conversation_id="chat",
        destination_id="shared", submission_id="submission-a", authorize=world.authorize,
    )
    store.begin({"message": "Question A"}, world.question)
    assert store.dispatch()
    world.actor["value"] = "collaborator"
    response = world.app.test_client().post(
        "/api/collaboration/conversations/shared/stream/cancel",
        json={"submission_id": "submission-a", "user_id": "owner"},
    )
    assert response.status_code == 200
    assert store.read()["state"] == "running"
    world.actor["value"] = "outsider"
    response = world.app.test_client().post(
        "/api/collaboration/conversations/shared/stream/cancel", json={"submission_id": "submission-a"},
    )
    assert response.status_code == 403


def registered_chat_helpers(world):
    """Reach real registrar closures, without AST extraction or cloned globals."""
    helpers, seen = {}, set()
    pending = list(world.app.view_functions.values())
    while pending:
        candidate = pending.pop()
        if not inspect.isfunction(candidate) or id(candidate) in seen:
            continue
        seen.add(id(candidate))
        if candidate.__module__ != world.chats.__name__:
            continue
        helpers[candidate.__name__] = inspect.unwrap(candidate)
        pending.extend(inspect.getclosurevars(candidate).nonlocals.values())
        if hasattr(candidate, "__wrapped__"):
            pending.append(candidate.__wrapped__)
    return helpers


def owner_response(world, endpoint, payload=None, **arguments):
    with world.app.test_request_context("/", method="POST", json=payload or {}):
        return world.app.make_response(world.app.view_functions[endpoint](**arguments))


def test_chat_metadata_owners_consume_installed_sdk_points(stop_world):
    world = stop_world
    question = deepcopy(world.question)
    question["metadata"]["user_info"] = {"user_id": "owner"}
    saved = world.chats._save_chat_user_metadata(question, False)
    assert type(saved) is CosmosDict and saved["_etag"]
    info, thread, _previous = world.chats._get_user_message_image_context("chat", "question-a")
    assert info == {"user_id": "owner"} and thread == "thread-a"
    response = world.chats._load_user_message_response_context("chat", "question-a")
    assert response["thread_id"] == "thread-a" and response["user_info"]["user_id"] == "owner"
    world.messages.create_item(world.reply)
    originating = world.retry.retry_source_user(
        world.messages, world.messages.read_item("reply-a", "chat"),
    )
    assert type(originating) is dict and originating["id"] == "question-a"
    conversation, context = world.chats._resolve_authorized_conversation_context("owner", "chat")
    assert type(conversation) is CosmosDict and context["is_owner"] is True
    with pytest.raises(PermissionError):
        world.chats._resolve_authorized_conversation_context("other", "chat")


def test_chat_query_and_citation_owners_keep_plain_query_rows(stop_world, monkeypatch):
    world = stop_world
    world.messages.create_item(body=world.reply)
    recent = world.chats._read_recent_assistant_messages("chat", 5)
    assert recent and type(recent[0]) is dict and recent[0]["id"] == "reply-a"
    citation = {
        "tool_name": "TabularProcessingPlugin.filter_rows", "function_name": "filter_rows",
        "plugin_name": "TabularProcessingPlugin", "function_arguments": {},
        "function_result": {"data": [{"value": index} for index in range(6)]}, "success": True,
    }
    compact = world.chats.persist_agent_citation_artifacts(
        "chat", "reply-a", [citation], "2026-11-16T20:00:01Z",
    )
    artifact_id = compact[0]["artifact_id"]
    assert type(world.messages.read_item(artifact_id, "chat")) is CosmosDict
    payloads = world.chats._read_agent_citation_artifact_payloads("chat", [artifact_id])
    assert payloads
    rollback = world.chats._rollback_agent_citation_artifacts("chat", compact)
    assert rollback == {"deleted_artifact_count": 1, "rollback_failure_count": 0}
    documents = StopMessageContainer("user_id")
    documents.create_item({
        "id": "data", "user_id": "owner", "file_name": "report.pdf", "title": "Inventory", "version": 1,
    })
    monkeypatch.setattr(world.chats, "cosmos_user_documents_container", documents)
    monkeypatch.setattr(world.chats, "assert_document_available", lambda row, **kwargs: row)
    catalog = world.chats._build_tabular_related_document_catalog("owner", "workspace")
    assert catalog["documents"][0]["document_id"] == "data"
    selected = world.chats._resolve_chat_selected_document_metadata("data", user_id="owner")
    assert selected["file_name"] == "report.pdf" and selected["source_hint"] == "workspace"
    assert type(documents.query_items("SELECT * FROM c")[0]) is dict


def test_registered_chat_helper_owners_use_real_sdk_bindings(stop_world, monkeypatch):
    world = stop_world
    world.messages.create_item(world.question)
    world.messages.create_item(world.reply)
    helpers = registered_chat_helpers(world)
    with world.app.test_request_context("/"):
        loaded, error = helpers["_load_block_revision_message"]("owner", "chat", "reply-a")
        assert error is None and type(loaded) is CosmosDict
        assert helpers["_find_originating_user_request"]("chat", world.reply) == "Question A"
        assert helpers["_get_latest_chat_thread_id"]("chat") == "thread-a"
        raced = world.app.make_response(helpers["_answer_raced_block_submission"](
            "chat", "reply-a", "mermaid", 0, "a" * 64, "graph TD; A-->B", "Update it", "submission-a",
        ))
        assert raced.status_code == 409
        existing = helpers["_load_or_create_analyze_conversation"]("owner", "chat")
        assert type(existing) is CosmosDict
        with pytest.raises(PermissionError):
            helpers["_load_or_create_analyze_conversation"]("other", "chat")
        documents = helpers["_resolve_document_action_selected_documents"](
            ["question-a"], "personal", user_id="owner", conversation_id="chat",
        )
        assert documents[0]["id"] == "question-a"


def test_nonstream_chat_owner_reads_sdk_retry_input_before_model_dispatch(stop_world, monkeypatch):
    world = stop_world
    world.messages.create_item(world.question)
    monkeypatch.setattr(world.chats, "get_settings", lambda: {})
    monkeypatch.setattr(world.chats, "_apply_admin_new_conversation_model_defaults", lambda *a, **k: None)
    monkeypatch.setattr(world.chats, "_get_authorized_chat_scope_context", lambda *a, **k: {
        "active_group_ids": [], "active_group_id": None,
        "active_public_workspace_ids": [], "active_public_workspace_id": None,
    })
    consumed = []

    class BeforeProvider(BaseException):
        pass

    def checked_input(text, *args, **kwargs):
        consumed.append(text)
        raise BeforeProvider()

    monkeypatch.setattr(world.chats, "check_chat_content", checked_input)
    with world.app.test_request_context("/", method="POST", json={
        "conversation_id": "chat", "retry_user_message_id": "question-a", "message": "tampered",
    }):
        with pytest.raises(BeforeProvider):
            inspect.unwrap(world.app.view_functions["stop.chat_api"])()
    assert consumed == ["Question A"]


def test_history_access_scope_and_rebuild_owners_accept_sdk_points(stop_world):
    world = stop_world
    owned = world.history_authorize("owner", "chat")
    assert type(owned) is CosmosDict
    with pytest.raises(PermissionError):
        world.history_authorize("other", "chat")
    scoped, kind = world.history._load_scope_lock_conversation("chat", "owner")
    assert type(scoped) is CosmosDict and kind == "personal"
    updated = world.history._persist_scope_lock_update(scoped, kind, "owner", True)
    assert updated["scope_locked"] is True
    world.messages.create_item(world.question)
    rebuilt = world.history._rebuild_authorized_personal_conversation_used_documents("owner", "chat")
    assert rebuilt is not None
    assert world.history._list_personal_conversation_generated_documents(owned) == []
    assert type(world.conversations.read_item("chat", "chat")) is CosmosDict


def test_history_query_owners_consume_rows_scalars_and_notification_projections(stop_world, monkeypatch):
    world = stop_world
    world.messages.create_item(world.question)
    world.messages.create_item({
        "id": "child", "conversation_id": "chat", "parent_message_id": "question-a",
        "role": "assistant_artifact", "metadata": {},
    })
    children = world.history._collect_child_message_documents("chat", ["question-a"])
    assert [row["id"] for row in children] == ["child"]
    matches = world.history._query_matching_messages(world.messages, "Question", "any")
    assert matches[0]["id"] == "question-a" and type(matches[0]) is dict
    feed = world.history._query_legacy_conversations_for_feed("owner")
    assert feed[0]["id"] == "chat" and type(feed[0]) is dict
    hidden = world.conversations.read_item("chat", "chat")
    hidden["is_hidden"] = True
    world.conversations.upsert_item(hidden)
    assert world.history._count_hidden_legacy_conversations("owner") == 1
    notifications = StopMessageContainer("user_id")
    notifications.create_item({
        "id": "notification", "user_id": "owner", "notification_type": "collaboration_message_received",
        "metadata": {"conversation_id": "shared", "message_id": "shared-answer"}, "created_at": "2026-11-16",
    })
    monkeypatch.setattr(world.history, "cosmos_notifications_container", notifications)
    unread = world.history._load_unread_collaboration_notification_map("owner")
    assert unread["shared"]["message_id"] == "shared-answer"


@pytest.mark.parametrize("endpoint,payload", [
    ("toggle_conversation_pin", {}), ("toggle_conversation_hide", {}),
    ("update_conversation_title", {"title": "Retained title"}),
    ("mark_conversation_read_api", {}),
    ("get_conversation_kind_api", {}), ("get_conversation_metadata_api", {}),
])
def test_history_metadata_route_owners_use_sdk_point_documents(stop_world, monkeypatch, endpoint, payload):
    world = stop_world
    history = world.history
    monkeypatch.setattr(history, "bump_conversation_cache_version", lambda *a, **k: None)
    monkeypatch.setattr(history, "mark_chat_response_notifications_read_for_conversation", lambda *a: 0)
    monkeypatch.setattr(history, "serialize_chat_upload_workspace_documents_for_conversation", lambda *a: [])
    conversation = world.conversations.read_item("chat", "chat")
    conversation.update(
        chat_type="personal_single_user", has_unread_assistant_response=True,
        last_unread_assistant_message_id="reply-a", last_unread_assistant_at="2026-11-16",
    )
    world.conversations.upsert_item(conversation)
    response = owner_response(world, "stop_history." + endpoint, payload, conversation_id="chat")
    assert response.status_code == 200, response.json
    assert type(world.conversations.read_item("chat", "chat")) is CosmosDict
    if endpoint == "update_conversation_title":
        assert world.conversations.read_item("chat", "chat")["title"] == "Retained title"


@pytest.mark.parametrize("endpoint", ["bulk_pin_conversations", "bulk_hide_conversations"])
def test_history_bulk_route_owners_mutate_only_owned_sdk_documents(stop_world, monkeypatch, endpoint):
    world = stop_world
    monkeypatch.setattr(world.history, "bump_conversation_cache_version", lambda *a, **k: None)
    world.conversations.create_item({"id": "foreign", "user_id": "other"})
    action = "pin" if endpoint == "bulk_pin_conversations" else "hide"
    response = owner_response(world, "stop_history." + endpoint, {
        "conversation_ids": ["chat", "foreign"], "action": action,
    })
    assert response.status_code == 200 and response.json["updated_count"] == 1
    assert response.json["failed_ids"] == ["foreign"]
    assert world.conversations.read_item("chat", "chat")["is_pinned" if action == "pin" else "is_hidden"] is True


def test_history_selection_and_promotion_owners_consume_real_query_rows(stop_world, monkeypatch):
    world = stop_world
    first = deepcopy(world.question)
    first["metadata"]["thread_info"]["active_thread"] = False
    second = deepcopy(first)
    second["id"] = "question-b"
    second["metadata"]["thread_info"].update(thread_attempt=2, active_thread=True)
    world.messages.create_item(first)
    world.messages.create_item(second)
    monkeypatch.setattr(world.history, "_invalidate_conversation_cache_after_message_mutation", lambda *a: None)
    response = owner_response(
        world, "stop_history.switch_attempt", {"direction": "prev"}, message_id="question-b",
    )
    assert response.status_code == 200, response.json
    assert world.messages.read_item("question-a", "chat")["metadata"]["thread_info"]["active_thread"] is True
    second = world.messages.read_item("question-b", "chat")
    second["metadata"]["is_deleted"] = True
    world.messages.upsert_item(second)
    promoted = world.history._promote_remaining_thread_attempt("chat", "thread-a", 2, {"question-b"})
    assert promoted == 1


def test_shared_read_query_and_metadata_sync_owners_use_sdk_documents(stop_world):
    world = stop_world
    world.messages.create_item(world.reply)
    loaded = world.collaboration._read_source_message_doc("chat", "reply-a")
    assert type(loaded) is CosmosDict and loaded["_etag"]
    user = {**deepcopy(world.question), "conversation_id": "shared"}
    world.shared_messages.create_item(user)
    assert world.collaboration._find_collaboration_originating_request("shared", world.reply) == "Question A"
    mirror = {
        "id": "shared-answer", "conversation_id": "shared", "role": "assistant", "content": "Answer",
        "metadata": {"source_conversation_id": "chat", "source_message_id": "reply-a", "masked": True},
    }
    world.shared_messages.create_item(mirror)
    world.collaboration._sync_collaboration_mask_metadata_to_source(mirror)
    assert world.messages.read_item("reply-a", "chat")["metadata"]["masked"] is True
    mirror["metadata"]["block_revisions"] = {"version": 1, "entries": {}}
    world.collaboration._sync_collaboration_block_revisions_to_source(mirror)
    world.collaboration._save_collaboration_block_revisions("shared", "shared-answer", mirror, "owner")
    assert type(world.shared_messages.read_item("shared-answer", "shared")) is CosmosDict
    world.collaboration._save_collaboration_image_revisions("shared", "shared-answer", mirror, loaded, "owner")
    assert type(world.messages.read_item("reply-a", "chat")) is CosmosDict


@pytest.mark.parametrize("kind", ["saved_analysis", "document_action"])
def test_analysis_chat_owners_consume_sdk_retry_inputs_without_replaying_producers(stop_world, monkeypatch, kind):
    world = stop_world
    world.messages.create_item(world.question)
    monkeypatch.setattr(world.chats, "get_settings", lambda: {})
    monkeypatch.setattr(world.chats, "initialize_m365_chat_context", lambda *a: None)
    monkeypatch.setattr(world.chats, "_get_authorized_chat_scope_context", lambda *a, **k: {
        "active_group_ids": [], "active_group_id": None,
        "active_public_workspace_ids": [], "active_public_workspace_id": None,
    })
    helpers = registered_chat_helpers(world)
    if kind == "saved_analysis":
        seen = []

        class BeforeProducer(BaseException):
            pass

        monkeypatch.setattr(world.chats, "saved_analysis_context", lambda value: value)

        def input_boundary(text, *args, **kwargs):
            seen.append(text)
            raise BeforeProducer()

        monkeypatch.setattr(world.chats, "check_chat_content", input_boundary)
        with world.app.test_request_context("/"):
            with pytest.raises(BeforeProducer):
                helpers["execute_saved_analysis_chat_request"]({
                    "conversation_id": "chat", "retry_user_message_id": "question-a",
                    "message": "tampered", "analysis_result_context": {"id": "retained"},
                })
        assert seen == ["Question A"]
    else:
        from functions_chat_content_checks import ChatContentDecision
        monkeypatch.setattr(world.chats, "check_chat_content", lambda *a, **k:
                            ChatContentDecision("chat_input", "not_required", "allow", {}))
        monkeypatch.setattr(world.chats, "normalize_document_action_config", lambda **kwargs: {
            "type": "analyze", "doc_scope": "personal", "document_ids": ["retained-document"],
        })
        with world.app.test_request_context("/"):
            payload, status = helpers["execute_document_action_chat_request"]({
                "conversation_id": "chat", "retry_user_message_id": "question-a", "message": "tampered",
                "document_action": {"type": "analyze", "document_ids": ["retained-document"]},
            })
        assert status == 409 and "Analyze request changed" in payload["error"]


def test_image_proposal_owners_consume_sdk_source_and_image_callback(stop_world, monkeypatch):
    world = stop_world
    world.messages.create_item(world.reply)
    image = {
        "id": "image", "conversation_id": "chat", "role": "image",
        "content": "data:image/png;base64,AA==", "created_at": "2026-11-16T20:00:02Z",
        "metadata": {"image_proposal": {"prompt": "A test diagram", "visualId": "visual"}},
    }
    world.messages.create_item(image)
    monkeypatch.setattr(world.chats, "get_settings", lambda: {"enable_image_generation": True})
    monkeypatch.setattr(world.chats, "image_generation_is_enabled", lambda settings: True)
    observed = []

    def planned(source, proposal, read_image):
        assert type(source) is CosmosDict and source["id"] == "reply-a"
        result = read_image("image")
        observed.append(type(result))
        return result

    monkeypatch.setattr(world.chats, "find_planned_proposal_image", planned)
    response = owner_response(world, "stop.generate_image_from_proposal", {
        "conversation_id": "chat", "assistant_message_id": "reply-a",
        "proposal": {"prompt": "A test diagram", "visualId": "visual"},
    })
    assert response.status_code == 200, response.json
    assert observed == [CosmosDict]
    status = owner_response(world, "stop.image_proposal_status", conversation_id="chat")
    assert status.status_code == 200, status.json
    assert status.json["results"][0]["message_id"] == "image"


def test_personal_mask_and_visual_style_owners_mutate_sdk_documents(stop_world, monkeypatch):
    world = stop_world
    world.messages.create_item(world.reply)
    monkeypatch.setattr(world.chats, "get_current_user_info", lambda: {"userId": "owner"})
    masked = owner_response(world, "stop.mask_message_api", {
        "conversation_id": "chat", "action": "mask_all",
    }, message_id="reply-a")
    assert masked.status_code == 200, masked.json
    assert world.messages.read_item("reply-a", "chat")["metadata"]["masked"] is True
    # This boundary test isolates the style validator (covered separately); the
    # real route must persist the SDK point document without losing its ETag/body.
    monkeypatch.setattr(world.chats, "apply_visual_style", lambda document, *a: {
        "retained": document["metadata"]["masked"],
    })
    styled = owner_response(world, "stop.set_message_visual_style_api", {
        "conversation_id": "chat", "block_kind": "mermaid", "block_index": 0,
    }, message_id="reply-a")
    assert styled.status_code == 200 and styled.json["visual_styles"]["retained"] is True


def test_image_revision_owner_consumes_sdk_reload_callback(stop_world, monkeypatch):
    world = stop_world
    image = {**deepcopy(world.reply), "id": "image", "role": "image",
             "content": "data:image/png;base64,AA=="}
    world.messages.create_item(image)
    monkeypatch.setattr(world.chats, "get_settings", lambda: {"enable_image_generation": True})
    monkeypatch.setattr(world.chats, "get_current_user_info", lambda: {"userId": "owner"})
    seen = []

    class BeforeImageProvider(BaseException):
        pass

    def image_boundary(*args, reload_message, **kwargs):
        reloaded = reload_message()
        seen.append((type(reloaded), reloaded["id"], reloaded["_etag"]))
        raise BeforeImageProvider()

    monkeypatch.setattr(world.chats, "revise_image_message", image_boundary)
    with pytest.raises(BeforeImageProvider):
        owner_response(world, "stop.add_message_image_revision_api", {
            "conversation_id": "chat", "instruction": "Change the colour",
        }, message_id="image")
    assert seen and seen[0][:2] == (CosmosDict, "image")


def test_history_feed_search_classification_and_summary_owners_consume_query_rows(stop_world, monkeypatch):
    world = stop_world
    conversation = world.conversations.read_item("chat", "chat")
    conversation.update(
        title="Question discussion", last_updated="2026-11-16T20:00:00Z",
        classification=["Internal"], chat_type="personal_single_user",
    )
    world.conversations.upsert_item(conversation)
    world.messages.create_item(world.question)
    monkeypatch.setattr(world.history, "_load_accessible_collaboration_search_conversations", lambda user: [])
    monkeypatch.setattr(world.history, "cosmos_collaboration_messages_container", world.shared_messages)
    listed = owner_response(world, "stop_history.get_conversations")
    assert listed.status_code == 200 and listed.json["conversations"][0]["id"] == "chat"
    classifications = owner_response(world, "stop_history.get_user_classifications")
    assert classifications.status_code == 200 and classifications.json["classifications"] == ["Internal"]
    searched = owner_response(world, "stop_history.search_conversations", {"search_term": "Question"})
    assert searched.status_code == 200 and searched.json["total_results"] == 1, searched.json
    # The export/model service is external to this query owner. Check the actual
    # normalized message DTO it receives, and do not call any provider.
    import route_backend_conversation_export as export
    summaries = []

    def summarize(**kwargs):
        summaries.append(kwargs["messages"])
        return {"summary": "Question summary"}

    monkeypatch.setattr(export, "generate_conversation_summary", summarize)
    summary = owner_response(world, "stop_history.generate_conversation_summary_api", conversation_id="chat")
    assert summary.status_code == 200, summary.json
    assert summaries[0][0]["content_text"] == "Question A"


@pytest.mark.parametrize("multiple", [False, True])
def test_conversation_delete_owners_use_real_sdk_queries_and_ignore_write_results(stop_world, monkeypatch, multiple):
    world = stop_world
    world.messages.create_item(world.question)
    # Only unrelated external cleanup/telemetry owners are isolated. Ownership,
    # scoped message queries, ordinary deletes and response semantics stay real.
    for name in (
        "cancel_m365_conversation_deliveries", "cleanup_conversation_checkpoints",
        "cleanup_chat_analysis_conversation", "delete_blob_backed_chat_message_files",
        "delete_thoughts_for_conversation", "log_conversation_deletion",
        "bump_conversation_cache_version",
    ):
        monkeypatch.setattr(world.history, name, lambda *a, **k: None)
    import functions_action_credential_state as credentials
    monkeypatch.setattr(credentials, "delete_private_state", lambda *a, **k: None)
    if multiple:
        response = owner_response(world, "stop_history.delete_multiple_conversations", {"conversation_ids": ["chat"]})
    else:
        response = owner_response(world, "stop_history.delete_conversation", conversation_id="chat")
    assert response.status_code == 200, response.json
    assert ("chat", "question-a") not in world.messages.items
    assert ("chat", "chat") not in world.conversations.items


def test_message_delete_owner_checks_sdk_conversation_before_deleting_query_row(stop_world, monkeypatch):
    world = stop_world
    world.messages.create_item(world.reply)
    monkeypatch.setattr(world.history, "_invalidate_conversation_cache_after_message_mutation", lambda *a: None)
    monkeypatch.setattr(world.history, "delete_blob_backed_chat_message_files", lambda *a, **k: None)
    response = owner_response(world, "stop_history.delete_message", message_id="reply-a")
    assert response.status_code == 200, response.json
    assert ("chat", "reply-a") not in world.messages.items


@pytest.mark.parametrize("endpoint", ["mask_collaboration_message_api", "set_collaboration_message_visual_style_api"])
def test_shared_metadata_write_owners_ignore_sdk_write_responses(stop_world, monkeypatch, endpoint):
    world = stop_world
    message = {
        "id": "shared-answer", "conversation_id": "shared", "role": "assistant", "content": "Answer",
        "metadata": {"sender": {"user_id": "owner"}},
    }
    world.shared_messages.create_item(message)
    monkeypatch.setattr(world.collaboration, "apply_visual_style", lambda document, *a: {})
    response = owner_response(world, "stop_collaboration." + endpoint, {
        "conversation_id": "shared", "action": "mask_all", "block_kind": "mermaid", "block_index": 0,
    }, conversation_id="shared", message_id="shared-answer")
    assert response.status_code == 200, response.json
    assert type(world.shared_messages.read_item("shared-answer", "shared")) is CosmosDict


def test_chat_creation_and_blocked_input_owners_discard_sdk_write_documents(stop_world, monkeypatch):
    world = stop_world
    from functions_chat_content_checks import ChatContentDecision
    monkeypatch.setattr(world.chats, "log_conversation_creation", lambda **kwargs: None)
    monkeypatch.setattr(world.chats, "invalidate_conversation_cache_for_item", lambda *a, **k: None)
    monkeypatch.setattr(world.chats, "record_chat_content_incident", lambda *a: None)
    monkeypatch.setattr(world.chats, "get_current_user_info", lambda: {"userId": "owner"})
    created = world.chats._create_personal_conversation("owner", "sdk-created")
    assert type(created) is dict and type(world.conversations.read_item("sdk-created", "sdk-created")) is CosmosDict
    with world.app.test_request_context("/"):
        blocked = world.chats._reject_chat_submission(
            world.conversations.read_item("sdk-created", "sdk-created"), "owner",
            ChatContentDecision("chat_input", "findings", "block", {}, "Message blocked."),
        )
    saved = world.messages.read_item(blocked["message_id"], "sdk-created")
    assert type(saved) is CosmosDict and saved["role"] == "safety"
    assert all("Message blocked." not in row.get("private_input", "") for row in world.messages.items.values())


def test_shared_image_revision_owner_consumes_sdk_source_reload(stop_world, monkeypatch):
    world = stop_world
    source = {
        "id": "image", "conversation_id": "chat", "role": "image",
        "user_id": "owner", "content": "data:image/png;base64,AA==", "metadata": {},
    }
    world.messages.create_item(source)
    world.shared_messages.create_item({
        **deepcopy(source), "id": "shared-image", "conversation_id": "shared",
        "metadata": {"source_conversation_id": "chat", "source_message_id": "image",
                     "sender": {"user_id": "owner"}},
    })
    monkeypatch.setattr(world.collaboration, "get_settings", lambda: {"enable_image_generation": True})
    seen = []

    class BeforeImageProvider(BaseException):
        pass

    def image_boundary(*args, reload_message, **kwargs):
        fresh = reload_message()
        seen.append((type(fresh), fresh["id"], fresh["_etag"]))
        raise BeforeImageProvider()

    monkeypatch.setattr(world.collaboration, "revise_image_message", image_boundary)
    with pytest.raises(BeforeImageProvider):
        owner_response(world, "stop_collaboration.add_collaboration_image_revision_api", {
            "instruction": "Change the colour",
        }, conversation_id="shared", message_id="shared-image")
    assert seen and seen[0][:2] == (CosmosDict, "image")


def test_live_shared_stream_owners_consume_sdk_source_and_public_message_points(stop_world, monkeypatch):
    world = stop_world
    from flask import Response
    from functions_chat_content_checks import ChatContentDecision
    shared = world.shared.read_item("shared", "shared")
    shared["source_conversation_id"] = "chat"
    world.shared.upsert_item(shared)
    source = world.conversations.read_item("chat", "chat")
    source.update(conversation_kind="collaboration_source", collaboration_conversation_id="shared")
    world.conversations.upsert_item(source)
    world.messages.create_item(world.question)
    world.messages.create_item(world.reply)
    monkeypatch.setattr(world.collaboration, "check_chat_content", lambda *a, **k:
                        ChatContentDecision("chat_input", "not_required", "allow", {}))
    monkeypatch.setattr(world.collaboration, "create_collaboration_message_notifications", lambda *a: None)

    def internal_stream():
        return Response("data: " + json.dumps({
            "done": True, "message_id": "reply-a", "user_message_id": "question-a",
            "full_content": "Safe partial answer",
        }) + "\n\n", mimetype="text/event-stream")

    monkeypatch.setattr(world.collaboration, "_resolve_internal_view_function", lambda name: internal_stream)
    response = world.app.test_client().post(
        "/api/collaboration/conversations/shared/stream", json={"content": "Question A"},
    )
    assert response.status_code == 200
    events = [json.loads(line[5:]) for line in response.get_data(as_text=True).splitlines()
              if line.startswith("data:")]
    final = next(event for event in events if event.get("done") and event.get("message_id"))
    saved = world.shared_messages.read_item(final["message_id"], "shared")
    assert type(saved) is CosmosDict and saved["content"] == "Safe partial answer"
    question = world.shared_messages.read_item(final["user_message_id"], "shared")
    assert type(question) is CosmosDict and question["metadata"]["source_message_id"] == "question-a"


def test_shared_stream_resumes_exact_undispatched_admission_without_another_public_question(stop_world, monkeypatch):
    world = stop_world
    from flask import Response, jsonify, request
    from functions_chat_content_checks import ChatContentDecision
    shared = world.shared.read_item("shared", "shared")
    shared["source_conversation_id"] = "chat"
    world.shared.upsert_item(shared)
    source = world.conversations.read_item("chat", "chat")
    source.update(conversation_kind="collaboration_source", collaboration_conversation_id="shared")
    world.conversations.upsert_item(source)
    monkeypatch.setattr(world.collaboration, "check_chat_content", lambda *a, **k:
                        ChatContentDecision("chat_input", "not_required", "allow", {}))
    monkeypatch.setattr(world.collaboration, "create_collaboration_message_notifications", lambda *a: None)
    invocations, dispatches = [], []

    def authorize():
        return world.collaboration_owner.assert_user_can_participate_in_collaboration_conversation(
            "owner", world.collaboration_owner.get_collaboration_conversation("shared"),
        )

    def internal_stream():
        data = request.get_json()
        invocations.append(data)
        store = world.retry.ChatAttemptStore(
            world.controls, world.messages, actor_id="owner", conversation_id="chat",
            destination_id="shared", submission_id=data["submission_id"], authorize=authorize,
        )
        question = {**deepcopy(world.question), "id": f"native-proposal-{len(invocations)}"}
        try:
            record = store.begin(data, question, assistant_message_id="reply-a")
        except (AzureError, world.retry.ChatRetryError):
            return jsonify({"error": "Response state unavailable."}), 503
        assert store.dispatch()
        dispatches.append(record["user_message_id"])
        store.commit(world.reply)
        return Response("data: " + json.dumps({
            "done": True, "message_id": "reply-a", "user_message_id": record["user_message_id"],
            "full_content": world.reply["content"],
        }) + "\n\n", mimetype="text/event-stream")

    monkeypatch.setattr(world.collaboration, "_resolve_internal_view_function", lambda name: internal_stream)
    client = world.app.test_client()
    world.messages.fail_writes = True
    first = client.post("/api/collaboration/conversations/shared/stream", json={
        "content": "Question A", "submission_id": "submission-a",
    })
    first.get_data()
    world.messages.fail_writes = False
    second = client.post("/api/collaboration/conversations/shared/stream", json={
        "content": "Question A", "submission_id": "submission-a",
    })
    second.get_data()
    users = [row for row in world.shared_messages.items.values() if row["role"] == "user"]
    answers = [row for row in world.shared_messages.items.values() if row["role"] == "assistant"]
    assert len(users) == len(answers) == 1
    assert dispatches == ["native-proposal-1"]
    assert invocations[0]["m365_collaboration_message_id"] == invocations[1]["m365_collaboration_message_id"]


def test_deleted_attempt_promotion_and_late_reply_share_the_selection_fence(stop_world):
    world = stop_world
    store = admit(world)
    store.dispatch()
    store.cancel()
    second = world.retry.prepare_retry_attempt(
        world.messages, world.conversations, "owner",
        world.messages.read_item("question-a", "chat"),
        {"message": "Question A", "conversation_id": "chat"}, submission_id="submission-b",
    )
    world.messages.delete_item(second["id"], "chat", etag=second["_etag"])
    partial = deepcopy(world.reply)
    partial["metadata"]["incomplete"] = True
    published = []

    def publish_late():
        if not published:
            published.append(True)
            store.commit(partial)

    # The old selector used point replacement; the corrected selector uses the
    # existing partition batch. The same interleaving must be safe in either order.
    world.messages.before_replace = publish_late
    world.messages.before_batch = publish_late
    assert world.history._promote_remaining_thread_attempt("chat", "thread-a", 2, {second["id"]}) == 1
    assert published
    assert world.messages.read_item("reply-a", "chat")["metadata"]["thread_info"]["active_thread"] is True


@pytest.mark.parametrize("stop_stage", ["input", "provider"])
def test_stream_generator_owner_consumes_sdk_retry_question_without_provider_work(stop_world, monkeypatch, stop_stage):
    world = stop_world
    from flask import g
    from functions_chat_content_checks import ChatContentDecision
    chats = world.chats
    world.messages.create_item(world.question)
    jobs, consumed = [], []
    world.app.extensions["executor"] = SimpleNamespace(submit=jobs.append)
    monkeypatch.setattr(chats, "get_settings", lambda *a, **k: {})
    monkeypatch.setattr(chats, "get_current_user_info", lambda: {"userId": "owner", "roles": ["User"]})
    monkeypatch.setattr(chats, "_apply_admin_new_conversation_model_defaults", lambda *a, **k: None)
    monkeypatch.setattr(chats, "_get_authorized_chat_scope_context", lambda *a, **k: {
        "active_group_id": None, "active_group_ids": [],
        "active_public_workspace_id": None, "active_public_workspace_ids": [],
    })
    for name in ("_acquire_chat_destination_lease", "_release_chat_destination_lease",
                 "_resolve_chat_conversation_references", "initialize_m365_chat_context",
                 "complete_m365_request", "log_chat_execution_outcome"):
        monkeypatch.setattr(chats, name, lambda *a, **k: None)
    monkeypatch.setattr(chats, "m365_action_card_events", lambda *a, **k: nullcontext())
    monkeypatch.setattr(chats, "_attach_request_m365_pending_action_cards", lambda payload, *a: payload)
    monkeypatch.setattr(chats, "get_plugin_logger", lambda: SimpleNamespace(
        clear_invocations_for_conversation=lambda *a: None,
    ))
    def provider_chunks(**kwargs):
        assert kwargs["stream"] is True
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="SDK partial answer"), finish_reason=None)],
            usage=None,
        )
        world.store().cancel()
        yield SimpleNamespace(choices=[], usage=None)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=provider_chunks)))
    monkeypatch.setattr(chats, "build_legacy_chat_client", lambda *a, **k: client)
    monkeypatch.setattr(chats, "build_model_endpoint_context", lambda **k: None)
    monkeypatch.setattr(chats, "_should_auto_merge_chat_upload_workspace_context", lambda *a, **k: False)

    class BeforeProvider(BaseException):
        pass

    def check_input(text, *args, **kwargs):
        record = world.store().read()
        if record and record.get("dispatched") and stop_stage == "input":
            consumed.append(text)
            raise BeforeProvider()
        return ChatContentDecision("chat_input", "not_required", "allow", {})

    monkeypatch.setattr(chats, "check_chat_content", check_input)
    with world.app.test_request_context("/", method="POST", json={
        "conversation_id": "chat", "retry_user_message_id": "question-a",
        "message": "Question A", "submission_id": "submission-a",
    }):
        g.chat_retry_question = world.messages.read_item("question-a", "chat")
        response = world.app.make_response(inspect.unwrap(world.app.view_functions["stop.chat_stream_api"])())
    assert response.status_code == 200 and len(jobs) == 1
    if stop_stage == "input":
        with pytest.raises(BeforeProvider):
            jobs[0]()
        assert consumed == ["Question A"]
    else:
        jobs[0]()
        frames = response.get_data(as_text=True)
        assert "SDK partial answer" in frames
        assert '"cancelled": true' in frames
        replies = [row for row in world.messages.items.values() if row.get("role") == "assistant"]
        assert len(replies) == 1 and replies[0]["metadata"]["stream_status"] == "stopped"


def run_tests() -> bool:
    tests = [test_chat_stream_stop_control_wiring]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("Test passed")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)