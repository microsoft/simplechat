#!/usr/bin/env python3
# test_workflow_chat_delivery_placement_and_masking.py
"""
Functional test for workflow chat delivery placement and masking parity.
Version: 0.261.227
Implemented in: 0.261.227

This test ensures delivered workflow-result chat messages are placed like normal assistant replies and are masked on read exactly like 6a Follow up answers with the same lineage.
"""

import copy
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "application" / "single_app", ROOT / "functional_tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402

import functions_workflow_chat_delivery_worker as worker  # noqa: E402
from functions_workflow_chat_delivery import workflow_delivery_message_id  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_support.workflow_chat_delivery_fakes import (  # noqa: E402
    CONVERSATION_ID,
    RESULT_TEXT,
    RUN_ID,
    USER,
    WORKFLOW_ID,
    fake_response,
    make_conversation,
    make_invocation,
    make_request_messages,
    make_run,
    make_workflow,
    make_world,
    parse_iso,
    require,
    shift,
)
from test_support.workflow_result_chat import (  # noqa: E402
    RUN_ID as RESULT_RUN_ID,
    USER as RESULT_USER,
    WORKFLOW_ID as RESULT_WORKFLOW_ID,
)
from test_support.workflow_result_offline_app import offline_workflow_result_app  # noqa: E402


DELIVERED_CANARY = "DELIVERED-WORKFLOW-RESULT-CANARY"
FOLLOWUP_CANARY = "FOLLOWUP-WORKFLOW-RESULT-CANARY"
LATER_USER_CANARY = "Can you compare those two workflow answers?"


@pytest.fixture(scope="module", autouse=True)
def remove_reused_session_directory():
    # app.py binds sessions to the first offline app's directory, so the later offline apps here recreate it.
    yield
    application = getattr(sys.modules.get("app"), "app", None)
    session_dir = application.config.get("SESSION_FILE_DIR") if application is not None else None
    if not session_dir:
        return
    path = Path(session_dir).resolve()
    if path.parent == ROOT / "functional_tests" and path.name.startswith(".workflow-result-chat-state-"):
        shutil.rmtree(path, ignore_errors=True)


def test_version_is_at_least_the_chat_delivery_release():
    assert_app_version_at_least("0.261.227")


def deliver(world, *, user_id=USER, run_id=RUN_ID):
    outcome = worker.process_workflow_chat_delivery(user_id, run_id, services=world.services)
    require(outcome == worker.OUTCOME_DELIVERED, f"delivery did not complete: {outcome}")
    messages = world.delivery_messages()
    require(len(messages) == 1, f"expected one delivered message, got {messages}")
    return messages[0]


def descriptor_result(descriptor, *, text=RESULT_TEXT):
    def read_with_budget(excerpt_budget_bytes):
        return {
            "descriptor": copy.deepcopy(descriptor),
            "excerpts": [{"text": text}],
            "truncated": False,
            "partial": False,
            "analysis_only": False,
            "skipped_reports": False,
            "saved_inputs": [],
            "budget": excerpt_budget_bytes,
        }

    return read_with_budget


def make_offline_delivery_world(descriptor, *, reply=DELIVERED_CANARY):
    run = make_run(
        id=RESULT_RUN_ID,
        user_id=RESULT_USER,
        workflow_id=RESULT_WORKFLOW_ID,
        workflow_name="Weekly digest",
        chat_invocation=make_invocation(requested_by=RESULT_USER),
    )
    world = make_world(run=run, control=False)
    world.runtime.set(run_id=RESULT_RUN_ID, state="completed", version=5)
    world.workflows.put(make_workflow(id=RESULT_WORKFLOW_ID, user_id=RESULT_USER, name="Weekly digest"))
    world.conversations.put(make_conversation(user_id=RESULT_USER, chat_type="new", title="Workflow delivery chat"))
    world.reader.outcomes.append(descriptor_result(descriptor))
    world.models.selected.replies.append(fake_response(reply))
    return world


def seed_chat(config, delivery_world, *extra_messages):
    conversation = delivery_world.conversation()
    conversation["user_id"] = RESULT_USER
    conversation["chat_type"] = "new"
    config.cosmos_conversations_container.upsert_item(conversation)
    for message in [*make_request_messages(), *extra_messages]:
        item = copy.deepcopy(message)
        item["conversation_id"] = CONVERSATION_ID
        config.cosmos_messages_container.upsert_item(item)


def six_a_followup_answer_like(delivered):
    delivered_thread = delivered["metadata"]["thread_info"]["thread_id"]
    metadata = {
        "workflow_result": copy.deepcopy(delivered["metadata"]["workflow_result"]),
        "workflow_result_contexts": copy.deepcopy(delivered["metadata"]["workflow_result_contexts"]),
        "token_usage": {"total_tokens": 7},
        "user_info": {"user_id": RESULT_USER},
        "thread_info": {
            "thread_id": "thread-six-a-followup-answer",
            "previous_thread_id": delivered_thread,
            "active_thread": True,
            "thread_attempt": 1,
        },
        "masked": False,
    }
    return {
        "id": "assistant-six-a-followup-answer",
        "conversation_id": CONVERSATION_ID,
        "role": "assistant",
        "content": FOLLOWUP_CANARY,
        "timestamp": shift(delivered["timestamp"], microseconds=1),
        "model_deployment_name": "gpt-4o",
        "augmented": False,
        "hybrid_citations": [],
        "hybridsearch_query": None,
        "agent_citations": [],
        "web_search_citations": [],
        "metadata": metadata,
    }


def later_user_message(after_message):
    return {
        "id": "message-user-after-results",
        "conversation_id": CONVERSATION_ID,
        "role": "user",
        "content": LATER_USER_CANARY,
        "timestamp": shift(after_message["timestamp"], microseconds=1),
        "metadata": {
            "thread_info": {
                "thread_id": "thread-user-after-results",
                "previous_thread_id": after_message["metadata"]["thread_info"]["thread_id"],
                "active_thread": True,
                "thread_attempt": 1,
            },
        },
    }


def response_messages(response, route_name):
    require(response.status_code == 200, f"{route_name} failed: {response.status_code} {response.get_data(as_text=True)[:500]}")
    payload = response.get_json()
    require(isinstance(payload, dict) and isinstance(payload.get("messages"), list), f"{route_name} returned {payload}")
    return payload["messages"]


def v2_messages(client):
    return response_messages(
        client.get("/api/get_messages", query_string={"conversation_id": CONVERSATION_ID}),
        "V2 message loader",
    )


def classic_messages(client):
    return response_messages(client.get(f"/conversation/{CONVERSATION_ID}/messages"), "classic message loader")


def search_count(client, term):
    response = client.post("/api/search_conversations", json={"search_term": term})
    require(response.status_code == 200, f"search failed: {response.status_code} {response.get_data(as_text=True)[:500]}")
    payload = response.get_json()
    results = payload.get("results") if isinstance(payload, dict) else None
    require(isinstance(results, list), f"search returned {payload}")
    return sum(
        len(result.get("messages") or [])
        for result in results
        if (result.get("conversation") or {}).get("id") == CONVERSATION_ID
    )


def history_text(world, monkeypatch):
    monkeypatch.setattr(world.chats, "get_current_user_id", lambda: RESULT_USER)
    messages = sorted(
        [copy.deepcopy(item) for item in world.config.cosmos_messages_container.items.values()],
        key=lambda item: item.get("timestamp") or "",
    )
    with world.web.test_request_context("/"):
        segments = world.chats.build_conversation_history_segments(
            messages,
            20,
            include_assistant_citation_context=False,
        )
    return "\n".join(message.get("content", "") for message in segments["history_messages"])


def require_surface_visibility(world, client, monkeypatch, *, delivered_visible, followup_visible, label):
    loaded = v2_messages(client)
    by_id = {message["id"]: message for message in loaded}
    delivered = by_id[workflow_delivery_message_id(RESULT_RUN_ID, CONVERSATION_ID, 5)]
    followup = by_id["assistant-six-a-followup-answer"]
    require((DELIVERED_CANARY in delivered["content"]) is delivered_visible, f"{label}: V2 delivered mismatch")
    require((FOLLOWUP_CANARY in followup["content"]) is followup_visible, f"{label}: V2 follow-up mismatch")

    search_matches = search_count(client, "WORKFLOW-RESULT-CANARY")
    expected_matches = int(delivered_visible) + int(followup_visible)
    require(search_matches == expected_matches, f"{label}: search had {search_matches}, expected {expected_matches}")

    context_text = history_text(world, monkeypatch)
    require((DELIVERED_CANARY in context_text) is delivered_visible, f"{label}: history delivered mismatch")
    require((FOLLOWUP_CANARY in context_text) is followup_visible, f"{label}: history follow-up mismatch")


def test_delivered_message_is_placed_after_the_newest_existing_thread_and_updates_the_conversation():
    world = make_world()
    newest = world.messages.get("message-assistant-1")

    message = deliver(world)

    thread_info = message["metadata"]["thread_info"]
    conversation = world.conversation()
    require(thread_info["previous_thread_id"] == "thread-request", f"wrong previous thread: {thread_info}")
    require(parse_iso(message["timestamp"]) > parse_iso(newest["timestamp"]), "delivery timestamp must follow newest")
    require(
        parse_iso(conversation["last_updated"]) >= parse_iso(message["timestamp"]),
        f"conversation was not updated after delivery: {conversation}",
    )
    require(thread_info["active_thread"] is True, f"delivery must be active: {thread_info}")
    require(thread_info["thread_attempt"] == 1, f"delivery must not be a retry attempt: {thread_info}")


def test_delivered_message_is_stamped_after_newer_assistant_messages():
    cases = [
        ("future", "2026-05-04T15:00:05.000000", "2026-05-04T15:00:05.000001"),
        ("same", "2026-05-04T15:00:00.000000", "2026-05-04T15:00:00.000001"),
    ]
    for label, newest_timestamp, expected_timestamp in cases:
        world = make_world()
        newest_thread_id = f"thread-newest-{label}"
        world.messages.put({
            "id": f"message-assistant-newest-{label}",
            "conversation_id": CONVERSATION_ID,
            "role": "assistant",
            "content": "A newer assistant message that delivery must follow.",
            "timestamp": newest_timestamp,
            "metadata": {
                "thread_info": {
                    "thread_id": newest_thread_id,
                    "previous_thread_id": "thread-request",
                    "active_thread": True,
                    "thread_attempt": 1,
                },
            },
        })

        message = deliver(world)

        require(
            message["timestamp"] == expected_timestamp,
            f"{label}: delivery timestamp should be newest + 1 microsecond; got {message['timestamp']!r}",
        )
        thread_info = message["metadata"]["thread_info"]
        require(
            thread_info["previous_thread_id"] == newest_thread_id,
            f"{label}: delivery should follow newest assistant thread, got {thread_info}",
        )


def test_delivered_result_shape_is_assistant_and_failed_notes_do_not_carry_result_lineage():
    result_world = make_world()
    message = deliver(result_world)
    metadata = message["metadata"]

    require(message["role"] == "assistant", f"unexpected role: {message}")
    require(message["conversation_id"] == CONVERSATION_ID, f"unexpected conversation: {message}")
    require(message["id"] == workflow_delivery_message_id(RUN_ID, CONVERSATION_ID, 5), f"unexpected id: {message}")
    require(metadata["workflow_delivery"]["workflow_id"] == WORKFLOW_ID, f"wrong workflow delivery: {metadata}")
    require(metadata["workflow_delivery"]["run_id"] == RUN_ID, f"wrong workflow delivery: {metadata}")
    require("workflow_result" in metadata, "result delivery must carry the 6a public descriptor")
    require("workflow_result_contexts" in metadata, "result delivery must carry 6a lineage contexts")

    failed_world = make_world(run=make_run(status="failed"), state="failed")
    failed_message = deliver(failed_world)
    failed_metadata = failed_message["metadata"]
    require("workflow_delivery" in failed_metadata, "failed note must keep delivery metadata")
    for key in ("workflow_result", "workflow_result_context", "workflow_result_contexts"):
        require(key not in failed_metadata, f"failed note must not carry {key}: {failed_metadata}")


def test_classic_and_v2_loaders_return_the_delivered_message_last_and_active(monkeypatch):
    with offline_workflow_result_app() as world:
        delivery_world = make_offline_delivery_world(world.fixture.read()["descriptor"])
        delivered = deliver(delivery_world, user_id=RESULT_USER, run_id=RESULT_RUN_ID)
        seed_chat(world.config, delivery_world, delivered)
        client = world.signed_in(RESULT_USER, "Owner")

        for route_name, loader in (("classic", classic_messages), ("V2", v2_messages)):
            messages = loader(client)
            ids = [message["id"] for message in messages]
            require(ids[-1] == delivered["id"], f"{route_name} loader did not return delivery last: {ids}")
            thread_info = messages[-1]["metadata"]["thread_info"]
            require(thread_info["active_thread"] is True, f"{route_name} loader lost active thread: {thread_info}")
            require(thread_info["thread_attempt"] == 1, f"{route_name} loader changed attempt: {thread_info}")
            require(thread_info["previous_thread_id"] == "thread-request", f"{route_name} loader changed placement")


def test_masking_surfaces_show_delivered_result_and_matching_followup_while_source_is_intact(monkeypatch):
    with offline_workflow_result_app() as world:
        delivery_world = make_offline_delivery_world(world.fixture.read()["descriptor"])
        delivered = deliver(delivery_world, user_id=RESULT_USER, run_id=RESULT_RUN_ID)
        followup = six_a_followup_answer_like(delivered)
        seed_chat(world.config, delivery_world, delivered, followup, later_user_message(followup))
        client = world.signed_in(RESULT_USER, "Owner")

        require_surface_visibility(
            world,
            client,
            monkeypatch,
            delivered_visible=True,
            followup_visible=True,
            label="intact result",
        )


def test_masking_surfaces_withhold_delivered_result_and_matching_followup_after_run_deleted(monkeypatch):
    with offline_workflow_result_app() as world:
        delivery_world = make_offline_delivery_world(world.fixture.read()["descriptor"])
        delivered = deliver(delivery_world, user_id=RESULT_USER, run_id=RESULT_RUN_ID)
        followup = six_a_followup_answer_like(delivered)
        seed_chat(world.config, delivery_world, delivered, followup, later_user_message(followup))
        client = world.signed_in(RESULT_USER, "Owner")
        world.fixture.containers["runs"].documents.clear()

        require_surface_visibility(
            world,
            client,
            monkeypatch,
            delivered_visible=False,
            followup_visible=False,
            label="deleted run",
        )


def test_masking_surfaces_withhold_delivered_result_and_matching_followup_after_result_changes(monkeypatch):
    with offline_workflow_result_app() as world:
        delivery_world = make_offline_delivery_world(world.fixture.read()["descriptor"])
        delivered = deliver(delivery_world, user_id=RESULT_USER, run_id=RESULT_RUN_ID)
        followup = six_a_followup_answer_like(delivered)
        seed_chat(world.config, delivery_world, delivered, followup, later_user_message(followup))
        client = world.signed_in(RESULT_USER, "Owner")
        world.fixture.add_task("task-summary-72", {"reply": "A revised digest."}, order=2, label="Write the digest")

        require_surface_visibility(
            world,
            client,
            monkeypatch,
            delivered_visible=False,
            followup_visible=False,
            label="changed result",
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
