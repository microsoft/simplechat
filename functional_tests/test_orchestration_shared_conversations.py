# test_orchestration_shared_conversations.py
#!/usr/bin/env python3
"""
Functional test for Orchestrate in shared conversations.
Version: 0.261.269
Implemented in: 0.261.269

Before 0.261.269 an orchestrated request in a shared conversation created a private
personal conversation under the shared conversation's id, so the question and answer were
never posted to the shared thread (microsoft/simplechat#1659). These tests drive the
production orchestration Blueprint over HTTP, with the real collaboration storage functions
over in-memory containers, and check that:

* the person who started the shared conversation plans in a hidden backing conversation that
  has the shared conversation's id and workspace lock, and no "new conversation" is announced;
* the question is posted to the shared thread with its mentions and AI target, and the run's
  answer is posted as a reply to it, each once, with a live event for every participant;
* other participants are told to turn off Orchestrate, and anyone else learns nothing.
"""

import importlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from azure.cosmos.exceptions import CosmosResourceNotFoundError

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "application" / "single_app"))
sys.path.insert(0, str(TESTS))

from test_orchestration_harness_routes import login, modules, real_http_harness  # noqa: E402,F401
from test_support.orchestration_harness_execution import compose_step, input_binding  # noqa: E402
from test_support.orchestration_revisions import AtomicMemoryContainer  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

SHARED_ID = "shared-conversation-1"
REQUEST = "@Assistant draft a short launch note for the team."
ANSWER = "Here is a short launch note for the team."
OWNER = {"user_id": "owner", "display_name": "Owner Person", "email": "owner@example.test"}
GUEST = {"user_id": "guest", "display_name": "Guest Person", "email": "guest@example.test"}
TARGET = {
    "target_type": "model", "display_name": "Assistant", "mention_text": "@Assistant",
    "source_mode": "mention", "ignored": "not kept",
}


class CollaborationMessages(AtomicMemoryContainer):
    """Collaboration message storage that also answers the source-message lookup."""

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        params = {entry["name"]: entry["value"] for entry in parameters or []}
        if "@source_message_id" not in params:
            return super().query_items(query, parameters, partition_key, **kwargs)
        rows = [
            deepcopy(item) for item in self.items.values()
            if item.get("conversation_id") == params["@conversation_id"]
            and (item.get("metadata") or {}).get("source_message_id") == params["@source_message_id"]
        ]
        return rows[:1]


@pytest.fixture
def shared(real_http_harness, modules, monkeypatch):
    collaboration = importlib.import_module("functions_collaboration")
    models = importlib.import_module("collaboration_models")
    conversations = AtomicMemoryContainer("id")
    messages = CollaborationMessages("conversation_id")
    events = []
    # The workspace document probe is not under test and would read public workspace settings.
    monkeypatch.setattr(modules.route, "resolve_candidate_documents", lambda *args, **kwargs: ([], False))
    document = models.build_personal_collaboration_conversation(
        "Launch plan", OWNER, invited_participants=[GUEST], conversation_id=SHARED_ID,
    )
    for participant in document["participants"]:
        participant["status"] = models.MEMBERSHIP_STATUS_ACCEPTED
    conversations.create_item(document)

    def participate(user_id, conversation):
        accepted = {
            participant["user_id"] for participant in conversation.get("participants") or []
            if participant.get("status") == models.MEMBERSHIP_STATUS_ACCEPTED
        }
        if user_id not in accepted:
            raise PermissionError("You are not a participant in this collaborative conversation")
        return {"membership_status": models.MEMBERSHIP_STATUS_ACCEPTED}

    monkeypatch.setattr(collaboration, "cosmos_collaboration_conversations_container", conversations)
    monkeypatch.setattr(collaboration, "cosmos_collaboration_messages_container", messages)
    monkeypatch.setattr(collaboration, "assert_user_can_participate_in_collaboration_conversation", participate)
    monkeypatch.setattr(
        collaboration, "COLLABORATION_EVENT_PUBLISHERS",
        [lambda conversation_id, event: events.append((conversation_id, deepcopy(event)))],
    )
    real_http_harness.shared = conversations
    real_http_harness.shared_messages = messages
    real_http_harness.events = events
    return real_http_harness


def frames(response):
    return [
        json.loads(frame.partition("data:")[2].strip())
        for frame in response.get_data(as_text=True).split("\n\n") if frame.startswith("data:")
    ]


def plan(runtime, **body):
    # A first question has no history, so the planner is the first model call.
    runtime.harness.replies = [
        json.dumps({"kind": "plan", "steps": [compose_step()], "final_response": input_binding("prepare")}),
        ANSWER,
    ]
    response = runtime.client.post("/api/v2/orchestration/plan", json={
        "conversation_id": SHARED_ID, "turn_id": "shared-turn", "message": REQUEST,
        "approval_mode": "manual", "planner_contract_version": 1, **body,
    }, buffered=True)
    assert response.status_code == 200
    return frames(response)


def shared_thread(runtime):
    return sorted(
        (deepcopy(item) for item in runtime.shared_messages.items.values()),
        key=lambda item: item.get("timestamp") or "",
    )


def test_version_includes_shared_orchestration():
    assert_app_version_at_least("0.261.269")


def test_owner_plan_and_answer_are_posted_to_the_shared_thread(shared):
    planning = plan(
        shared, invocation_target=TARGET, mentioned_participants=[GUEST, {"user_id": "stranger"}],
    )
    assert "plan" in planning[-1], planning
    assert not [frame for frame in planning if frame.get("type") == "conversation_metadata"]
    planned = planning[-1]["plan"]

    backing = shared.harness.conversations.read_item(SHARED_ID, SHARED_ID)
    assert backing["user_id"] == "owner" and backing["is_hidden"] is True
    assert backing["conversation_kind"] == "collaboration_source"
    assert backing["collaboration_conversation_id"] == SHARED_ID
    assert backing["scope_locked"] is True
    assert backing["locked_contexts"] == [{"scope": "personal", "id": "owner"}]
    record = shared.harness.runs.read_item(planned["run_id"], SHARED_ID)
    assert record["user_id"] == "owner"
    assert record["memory_audience"] == {"kind": "shared", "owner_id": "owner", "collaboration_id": SHARED_ID}

    question, = shared_thread(shared)
    source = shared.harness.messages.read_item(question["metadata"]["source_message_id"], SHARED_ID)
    assert source["role"] == "user" and source["content"] == REQUEST
    assert question["conversation_id"] == SHARED_ID and question["content"] == REQUEST
    assert question["message_kind"] == "ai_request"
    assert question["metadata"]["sender"]["user_id"] == "owner"
    # Only the bounded display fields of the AI target are kept.
    assert question["metadata"]["ai_invocation_target"] == {
        key: value for key, value in TARGET.items() if key != "ignored"
    }
    assert [mention["user_id"] for mention in question["metadata"]["mentioned_participants"]] == ["guest"]
    assert [event["event_type"] for _id, event in shared.events] == ["collaboration.message.created"]
    assert shared.events[0][1]["payload"]["message"]["id"] == question["id"]

    executed = frames(shared.client.post("/api/v2/orchestration/run", json={
        "conversation_id": SHARED_ID, "run_id": planned["run_id"],
    }, buffered=True))
    assert executed[-1]["status"] == "completed", executed
    answer = shared.harness.assistant_messages()[0]
    asked, replied = shared_thread(shared)
    assert asked["id"] == question["id"]
    assert replied["content"] == ANSWER and replied["message_kind"] == "assistant_response"
    assert replied["metadata"]["source_message_id"] == answer["id"]
    assert replied["reply_to_message_id"] == question["id"]
    assert [event["event_type"] for _id, event in shared.events] == ["collaboration.message.created"] * 2

    # Mirroring is idempotent: the same answer is never posted twice.
    mirror = importlib.import_module("functions_orchestration_collaboration")
    mirror.mirror_orchestration_answer(
        shared.harness.conversations.read_item(SHARED_ID, SHARED_ID), answer,
        user_message_id=source["id"], owner_user_id="owner",
    )
    assert len(shared_thread(shared)) == 2 and len(shared.events) == 2


def test_other_participants_are_asked_to_turn_off_orchestrate(shared):
    # Like the harness's other users, signed in with a role that skips the access-status lookup;
    # roles never grant access to a shared conversation.
    login(shared, user_id="guest")
    planning = plan(shared, invocation_target=TARGET)

    mirror = importlib.import_module("functions_orchestration_collaboration")
    assert planning[-1].get("error") == mirror.SHARED_ORCHESTRATION_OWNER_ONLY
    assert "plan" not in planning[-1]
    with pytest.raises(CosmosResourceNotFoundError):
        shared.harness.conversations.read_item(SHARED_ID, SHARED_ID)
    assert shared_thread(shared) == [] and shared.events == []


def test_anyone_else_cannot_tell_a_shared_conversation_exists(shared):
    login(shared, user_id="stranger")
    planning = plan(shared)

    assert planning[-1].get("error") == "That conversation could not be opened."
    with pytest.raises(CosmosResourceNotFoundError):
        shared.harness.conversations.read_item(SHARED_ID, SHARED_ID)
    assert shared_thread(shared) == [] and shared.events == []


def test_an_earlier_private_copy_becomes_the_owners_backing_conversation(shared):
    shared.harness.conversations.create_item({
        "id": SHARED_ID, "user_id": "owner", "title": "New Conversation", "context": [],
        "tags": [], "strict": False, "chat_type": "new",
    })
    planning = plan(shared, invocation_target=TARGET)

    assert "plan" in planning[-1], planning
    backing = shared.harness.conversations.read_item(SHARED_ID, SHARED_ID)
    assert backing["conversation_kind"] == "collaboration_source" and backing["is_hidden"] is True
    assert backing["collaboration_conversation_id"] == SHARED_ID
    assert len(shared_thread(shared)) == 1


def test_another_users_private_copy_is_never_adopted(shared):
    shared.harness.conversations.create_item({
        "id": SHARED_ID, "user_id": "guest", "title": "New Conversation", "chat_type": "new",
    })
    planning = plan(shared, invocation_target=TARGET)

    mirror = importlib.import_module("functions_orchestration_collaboration")
    # The person who started the conversation learns why, and how to continue.
    assert planning[-1].get("error") == mirror.SHARED_ORCHESTRATION_STALE_COPY
    assert shared.harness.conversations.read_item(SHARED_ID, SHARED_ID)["user_id"] == "guest"
    assert shared_thread(shared) == []


def run_shared_plan(shared):
    """Plan and run one shared turn; return the backing, the question copy and the answer."""
    planned = plan(shared, invocation_target=TARGET)[-1]["plan"]
    executed = frames(shared.client.post("/api/v2/orchestration/run", json={
        "conversation_id": SHARED_ID, "run_id": planned["run_id"],
    }, buffered=True))
    assert executed[-1]["status"] == "completed", executed
    backing = shared.harness.conversations.read_item(SHARED_ID, SHARED_ID)
    return backing, planned, shared.harness.assistant_messages()[0]


def test_a_republished_answer_updates_its_shared_copy(shared):
    mirror = importlib.import_module("functions_orchestration_collaboration")
    backing, _planned, answer = run_shared_plan(shared)
    question, copy = shared_thread(shared)

    final = {**answer, "content": "The final launch note, after the waiting step finished."}
    refreshed = mirror.mirror_orchestration_answer(
        backing, final, user_message_id=question["metadata"]["source_message_id"], owner_user_id="owner",
    )

    assert refreshed["id"] == copy["id"]
    _question, updated = shared_thread(shared)
    assert updated["content"] == final["content"]
    assert updated["reply_to_message_id"] == question["id"] and updated["timestamp"] == copy["timestamp"]
    assert updated["metadata"]["source_message_id"] == answer["id"]
    assert updated["metadata"]["source_conversation_id"] == SHARED_ID
    assert [event["event_type"] for _id, event in shared.events][-1] == "collaboration.message.updated"
    assert shared.events[-1][1]["payload"]["message"]["content"] == final["content"]
    # An unchanged republish posts and announces nothing.
    count = len(shared.events)
    mirror.mirror_orchestration_answer(backing, final, owner_user_id="owner")
    assert len(shared.events) == count and len(shared_thread(shared)) == 2


def test_nothing_is_posted_once_the_starter_leaves_the_conversation(shared):
    mirror = importlib.import_module("functions_orchestration_collaboration")
    backing, _planned, answer = run_shared_plan(shared)
    collaboration = shared.shared.read_item(SHARED_ID, SHARED_ID)
    for participant in collaboration["participants"]:
        if participant["user_id"] == "owner":
            participant["status"] = "removed"
    shared.shared.upsert_item(collaboration)
    posted, events = len(shared_thread(shared)), len(shared.events)

    with pytest.raises(PermissionError):
        mirror.mirror_orchestration_answer(backing, {**answer, "content": "Changed."}, owner_user_id="owner")
    with pytest.raises(PermissionError):
        mirror.mirror_orchestration_turn(
            backing, {"id": "user-later", "content": "Later question"}, OWNER,
        )
    assert len(shared_thread(shared)) == posted and len(shared.events) == events


def test_deleting_the_shared_conversation_deletes_its_backing(shared):
    mirror = importlib.import_module("functions_orchestration_collaboration")
    _backing, planned, _answer = run_shared_plan(shared)
    collaboration = shared.shared.read_item(SHARED_ID, SHARED_ID)

    def delete(**options):
        return mirror.delete_orchestration_backing(
            collaboration, archiving_enabled=False,
            conversation_container=shared.harness.conversations, message_container=shared.harness.messages,
            **options,
        )

    # A co-owner who didn't start the conversation leaves its creator's plans alone.
    assert delete(expected_user_id="guest") is None
    assert shared.harness.conversations.read_item(SHARED_ID, SHARED_ID)

    deleted = delete(expected_user_id="owner")
    assert deleted["id"] == SHARED_ID
    with pytest.raises(CosmosResourceNotFoundError):
        shared.harness.conversations.read_item(SHARED_ID, SHARED_ID)
    assert [
        message for message in shared.harness.messages.items.values() if message.get("conversation_id") == SHARED_ID
    ] == []
    run = shared.harness.runs.read_item(planned["run_id"], SHARED_ID)
    assert run["checkpoints_deleted"] is True and run["execution_lease"] is None
    # Nothing is left to delete the second time.
    assert delete() is None


def test_shared_conversation_deletion_removes_the_backing_first():
    """The shared conversation's own deletion path deletes the backing before anything else."""
    source = (Path(__file__).resolve().parents[1] / "application" / "single_app" / "functions_collaboration.py")
    text = source.read_text(encoding="utf-8")
    body = text[text.index("def _delete_collaboration_conversation_records("):]
    body = body[:body.index("\ndef ")]
    cancel = body.index("_cancel_collaboration_pending_deliveries(conversation_doc)")
    backing = body.index("delete_orchestration_backing(")
    assert cancel < backing < body.index("cosmos_collaboration_messages_container.query_items(")
    assert "expected_user_id=expected_source_user_id" in body
    assert "conversation_container=cosmos_conversations_container" in body
    assert "not_found_error=CosmosResourceNotFoundError" in body


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
