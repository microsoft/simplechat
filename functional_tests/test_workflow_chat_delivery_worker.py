#!/usr/bin/env python3
# test_workflow_chat_delivery_worker.py
"""
Functional test for the workflow chat delivery worker.
Version: 0.261.218
Implemented in: 0.261.218

This test ensures that the worker posts a chat-started workflow run's outcome back into the chat
that asked exactly once per delivery generation, under a dated label, with one unread mark and
one bell notice; that it posts nothing and sends one notice when the chat can't take it; and that
crashes, outages, deferrals, deletions and durable resumes never post twice or retry forever.

The worker and the delivery contract are real. Storage, the runtime store, the result reader, the
models and the notification helpers are the in-memory fakes in
``test_support/workflow_chat_delivery_fakes.py``.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "application" / "single_app", ROOT / "functional_tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402

import functions_workflow_chat_delivery_worker as worker  # noqa: E402
from functions_conversation_unread import clear_conversation_unread  # noqa: E402
from functions_workflow_chat_delivery import (  # noqa: E402
    COMPOSE_MAX_TOKENS,
    COMPOSE_TEMPERATURE,
    EXPIRED_NOTICE_MESSAGE,
    FALLBACK_QUESTION,
    KIND_ANALYSIS,
    KIND_CANCELLED,
    KIND_CONTENT_BLOCKED,
    KIND_FAILED,
    KIND_SKIPPED,
    KIND_STATUS,
    MAX_ATTEMPTS,
    REASON_CONTENT_BLOCKED,
    REASON_RESULT_UNAVAILABLE,
    REASON_RESULTS_OFF,
    SWEEP_LOCK_NAME,
    SWEEP_LOCK_SECONDS,
    SWEEP_MAX_RUNS,
    TRIMMED_FALLBACK_INTRO,
    UNDELIVERABLE_NOTICE_MESSAGE,
    assemble_delivery_content,
    delivery_note_text,
    delivery_thread_id,
    next_backoff_seconds,
    workflow_delivery_message_id,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_support.workflow_chat_delivery_fakes import (  # noqa: E402
    COMPOSED_REPLY,
    CONVERSATION_ID,
    OTHER_USER,
    ORCHESTRATION_RUN_ID,
    REQUEST_TEXT,
    REQUESTED_AT,
    RESULT_SHA,
    RESULT_TEXT,
    RUN_ID,
    SELECTED_MODEL,
    STEP_ID,
    USER,
    USER_MESSAGE_ID,
    WORKFLOW_ID,
    FakeResultUnavailable,
    FakeRuntimeUnavailable,
    cosmos_error,
    fake_response,
    make_record,
    make_run,
    make_world,
    parse_iso,
    shift,
)


LABEL = "Results from `Daily digest` \u00b7 you asked on May 4, 2026 at 10:05 AM (America/New_York)"
DISCLOSURE = "Source: workflow run from May 4, 2026."
M5 = workflow_delivery_message_id(RUN_ID, CONVERSATION_ID, 5)
M8 = workflow_delivery_message_id(RUN_ID, CONVERSATION_ID, 8)
NOTICE_LINK = f"/workflow-activity?workflowId={WORKFLOW_ID}&runId={RUN_ID}&scope=personal"
READY_TITLE = 'Results from "Daily digest" are ready'
DELIVERED_PREVIEW = 'Results from "Daily digest" are in your chat'


def deliver(world, run_id=RUN_ID, user_id=USER):
    return worker.process_workflow_chat_delivery(user_id, run_id, services=world.services)


def make_due(world, run_id=RUN_ID):
    """Move the clock just past the record's next attempt."""
    world.clock.now = shift(world.record(run_id)["next_attempt_at"], seconds=1)


def deliver_until(world, stop_outcomes, *, limit=40):
    """Deliver and move to the next attempt until an outcome in ``stop_outcomes`` comes back."""
    outcomes = []
    for _ in range(limit):
        outcome = deliver(world)
        outcomes.append(outcome)
        if outcome in stop_outcomes:
            return outcomes
        make_due(world)
    raise AssertionError(f"no outcome in {stop_outcomes} after {limit} attempts: {outcomes}")


def set_run_status(world, status, run_id=RUN_ID):
    run = world.run(run_id)
    run["status"] = status
    world.runs.put(run)


def delivered_notice(message_id=M5, generation=5):
    return {
        "type": "chat_response",
        "user_id": USER,
        "conversation_id": CONVERSATION_ID,
        "message_id": message_id,
        "conversation_title": "Planning chat",
        "response_preview": DELIVERED_PREVIEW,
        "idempotency_key": f"workflow-chat-delivery:{RUN_ID}:{generation}",
        "strict": True,
    }


def undeliverable_notice(title=READY_TITLE, generation=5):
    return {
        "type": "workflow_chat_delivery",
        "user_id": USER,
        "title": title,
        "message": UNDELIVERABLE_NOTICE_MESSAGE,
        "link_url": NOTICE_LINK,
        "metadata": {
            "workflow_id": WORKFLOW_ID,
            "run_id": RUN_ID,
            "workflow_scope": "personal",
            "delivery_status": "undeliverable",
        },
        "idempotency_key": f"workflow-chat-delivery-notice:{RUN_ID}:{generation}",
        "strict": True,
    }


def total_writes(world):
    return len(world.runs.writes()) + len(world.messages.writes()) + len(world.conversations.writes())


def note_content(kind, reason_code=None):
    return assemble_delivery_content(LABEL, delivery_note_text(kind, "Daily digest", reason_code=reason_code))


def result_contexts():
    return [{"workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "result_sha256": RESULT_SHA}]


def terminal_world(state):
    """A world whose run ended in ``state`` (the runtime control and the run document agree)."""
    return make_world(run=make_run(status=state), state=state)


def edit_request_message(world, **changes):
    message = world.messages.get(USER_MESSAGE_ID)
    message.update(changes)
    world.messages.put(message)


# ---------------------------------------------------------------------------------------------
# A. The delivered reply
# ---------------------------------------------------------------------------------------------


def test_app_version_includes_chat_delivery():
    assert_app_version_at_least("0.261.218")


def test_delivers_a_composed_reply_once_with_one_unread_mark_and_one_notice():
    world = make_world()

    outcome = deliver(world)

    assert outcome == worker.OUTCOME_DELIVERED
    messages = world.delivery_messages()
    assert [message["id"] for message in messages] == [M5]
    message = messages[0]
    assert message["role"] == "assistant"
    assert message["conversation_id"] == CONVERSATION_ID
    assert message["content"] == f"{LABEL}\n\n{COMPOSED_REPLY}\n\n{DISCLOSURE}"
    assert message["timestamp"] == "2026-05-04T15:00:00.000000"
    assert message["model_deployment_name"] == "gpt-selected"
    assert message["content_check"] == {"blocked": False, "categories": []}
    metadata = message["metadata"]
    assert metadata["workflow_delivery"] == {
        "version": 1,
        "kind": "result",
        "workflow_id": WORKFLOW_ID,
        "workflow_scope": "personal",
        "run_id": RUN_ID,
        "generation": 5,
        "run_status": "completed",
        "orchestration_run_id": ORCHESTRATION_RUN_ID,
        "step_id": STEP_ID,
        "requested_at": REQUESTED_AT,
    }
    assert metadata["token_usage"] == {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}
    assert metadata["user_info"] == {"user_id": USER}
    assert metadata["thread_info"] == {
        "thread_id": delivery_thread_id(M5),
        "previous_thread_id": "thread-request",
        "active_thread": True,
        "thread_attempt": 1,
    }
    assert metadata["workflow_result"]["result_sha256"] == RESULT_SHA
    assert metadata["workflow_result_contexts"] == [
        {"workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "result_sha256": RESULT_SHA},
    ]

    conversation = world.conversation()
    assert conversation["has_unread_assistant_response"] is True
    assert conversation["last_unread_assistant_message_id"] == M5
    assert conversation["last_unread_assistant_at"] == "2026-05-04T15:00:00.000000"
    assert [call["skip_if_read_since"] for call in world.unread_calls] == [None]
    assert world.unread_calls[0]["require_private"] is True
    assert world.cache_bumps.calls == [{"args": (USER,), "kwargs": {"reason": "workflow_chat_delivery"}}]

    record = world.record()
    assert record["status"] == "delivered"
    assert record["notice_kind"] == "chat_response"
    assert record["phase"] == "notified"
    assert record["generation"] == 5
    assert record["attempts"] == 1
    assert record["kind"] == "result"
    assert record["run_status"] == "completed"
    assert record["message_id"] == M5
    assert record["lease_id"] is None and record["lease_expires_at"] is None
    assert record["outcome_reason"] is None
    assert record["delivered_at"] == "2026-05-04T15:00:00.000000Z"

    assert world.notifications.chat_calls == [delivered_notice()]
    assert world.notifications.notice_calls == []

    assert [call["which"] for call in world.models.calls] == ["selected"]
    assert world.models.calls[0]["seeds"]["model"] == SELECTED_MODEL["model"]
    assert world.models.calls[0]["identity"] == {"identity": "captured"}
    assert world.identities.calls == [{"args": (USER,), "kwargs": {"conversation_id": CONVERSATION_ID}}]
    assert world.models.selected.closed == 1
    assert world.models.default.requests == []
    request = world.models.selected.requests[0]
    assert request["temperature"] == COMPOSE_TEMPERATURE
    assert request["max_tokens"] == COMPOSE_MAX_TOKENS
    assert world.prompts.calls == [
        {"budget": 48 * 1024, "question": REQUEST_TEXT, "nonce": "nonce-1", "time_zone": "America/New_York"},
    ]
    assert world.reader.calls[0]["budget"] == 48 * 1024
    assert world.checker.calls == [{"text": message["content"], "surface": "chat_output", "user_id": USER}]
    assert world.gates.calls == [("workflows", ["User"]), ("results", ["User"])]
    assert world.tokens.calls == [{
        "args": (),
        "kwargs": {
            "user_id": USER,
            "token_type": "chat",
            "conversation_id": CONVERSATION_ID,
            "message_id": M5,
            "model": "gpt-selected",
            "workspace_type": "personal",
            "total_tokens": 150,
            "prompt_tokens": 120,
            "completion_tokens": 30,
            "additional_context": {"workflow_result_delivery": True},
            "idempotency_key": f"workflow_result_delivery:{M5}:1",
        },
    }]


def test_reprocessing_a_delivered_run_changes_nothing():
    world = make_world()
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED
    writes = total_writes(world)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_NOT_APPLICABLE

    assert total_writes(world) == writes
    assert len(world.delivery_messages()) == 1
    assert len(world.notifications.chat_calls) == 1
    assert len(world.unread_calls) == 1
    assert len(world.models.requests) == 1


def test_a_token_log_failure_never_fails_delivery():
    world = make_world()
    world.tokens.errors.append(RuntimeError("token log down"))

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert len(world.tokens.calls) == 1
    assert world.delivery_messages()[0]["metadata"]["token_usage"]["total_tokens"] == 150
    assert world.record()["notice_kind"] == "chat_response"


def test_a_reply_without_usage_logs_no_tokens():
    world = make_world()
    world.models.selected.replies.append(fake_response(usage=None))

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert world.tokens.calls == []
    message = world.delivery_messages()[0]
    assert message["content"] == f"{LABEL}\n\n{COMPOSED_REPLY}\n\n{DISCLOSURE}"
    assert not message["metadata"].get("token_usage")


# ---------------------------------------------------------------------------------------------
# B. What gets posted
# ---------------------------------------------------------------------------------------------


def test_steps_the_excerpt_down_bound_to_the_first_digest_until_it_fits():
    world = make_world()
    world.budget.max_budget = 12 * 1024

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert [call["budget"] for call in world.reader.calls] == [48 * 1024, 24 * 1024, 12 * 1024], (
        "each smaller excerpt must be read in turn until the prompt fits"
    )
    assert [call["expected_sha256"] for call in world.reader.calls] == [None, RESULT_SHA, RESULT_SHA], (
        "a smaller excerpt must be bound to the digest first read"
    )
    assert [call["nonce"] for call in world.prompts.calls] == ["nonce-1", "nonce-2", "nonce-3"], (
        "every prompt must carry a fresh fence nonce"
    )
    assert len(world.models.requests) == 1, "only the prompt that fits may be sent"
    assert world.delivery_messages()[0]["content"] == f"{LABEL}\n\n{COMPOSED_REPLY}\n\n{DISCLOSURE}"


def test_a_result_too_large_for_any_excerpt_posts_the_status_note():
    world = make_world()
    world.budget.max_budget = 1024

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    message = world.delivery_messages()[0]
    assert message["content"] == note_content(KIND_STATUS)
    assert message["metadata"]["workflow_delivery"]["kind"] == KIND_STATUS
    assert "workflow_result" not in message["metadata"]
    assert "workflow_result_contexts" not in message["metadata"]
    assert [call["which"] for call in world.models.calls] == ["selected"]
    assert world.models.requests == []
    assert world.tokens.calls == []
    assert world.record()["outcome_reason"] == REASON_RESULT_UNAVAILABLE
    assert world.notifications.chat_calls == [delivered_notice()]


def test_uses_the_default_model_when_the_requests_model_is_unavailable():
    world = make_world()
    world.models.unavailable.add("selected")

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert [call["which"] for call in world.models.calls] == ["selected", "default"]
    message = world.delivery_messages()[0]
    assert message["model_deployment_name"] == "gpt-default"
    assert message["content"] == f"{LABEL}\n\n{COMPOSED_REPLY}\n\n{DISCLOSURE}"
    assert world.tokens.calls[0]["kwargs"]["model"] == "gpt-default"
    assert world.models.selected.requests == []


def test_uses_the_default_model_when_the_request_named_none():
    world = make_world()
    world.set_record(model_selection=None)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert [call["which"] for call in world.models.calls] == ["default"]
    assert world.delivery_messages()[0]["model_deployment_name"] == "gpt-default"


def test_falls_back_to_the_start_of_the_result_when_neither_model_answers():
    world = make_world()
    world.models.selected.replies.append(fake_response(finish_reason="content_filter"))
    world.models.default.replies.append(fake_response(refusal="I can't help with that."))

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    message = world.delivery_messages()[0]
    assert message["content"] == (
        f"{LABEL}\n\n{TRIMMED_FALLBACK_INTRO}\n\n```\n{RESULT_TEXT}\n```\n\n"
        "Source: workflow run from May 4, 2026 (truncated)."
    )
    assert message["model_deployment_name"] is None
    assert message["metadata"]["workflow_delivery"]["kind"] == "result"
    assert message["metadata"]["workflow_result_contexts"] == result_contexts()
    assert world.tokens.calls == [], "no compose answered, so there is nothing to count"
    assert [call["which"] for call in world.models.calls] == ["selected", "default"]
    assert world.models.selected.closed == 1 and world.models.default.closed == 1
    assert len(world.checker.calls) == 1, "the fallback text must be checked like a reply"


def test_the_fallback_fence_outgrows_backticks_in_the_result():
    world = make_world()
    world.reader.text = "Totals: ```` 3 files ````"
    world.models.selected.replies.append(fake_response(finish_reason="content_filter"))
    world.models.default.replies.append(fake_response(finish_reason="content_filter"))

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert "\n`````\nTotals: ```` 3 files ````\n`````" in world.delivery_messages()[0]["content"]


def test_never_asks_the_same_model_binding_twice():
    world = make_world()
    world.models.default = world.models.selected
    world.models.selected.replies.append(fake_response(finish_reason="content_filter"))

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert len(world.models.selected.requests) == 1
    assert world.delivery_messages()[0]["content"].startswith(f"{LABEL}\n\n{TRIMMED_FALLBACK_INTRO}")


def test_without_use_workflow_results_in_chat_nothing_of_the_result_is_read():
    world = make_world()
    world.gates.results = False

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert world.reader.calls == [], "the result must not be read when the results gate is off"
    assert world.models.calls == [], "no model may see the result when the results gate is off"
    message = world.delivery_messages()[0]
    assert message["content"] == note_content(KIND_STATUS)
    assert "workflow_result" not in message["metadata"]
    assert world.record()["outcome_reason"] == REASON_RESULTS_OFF
    assert ("results", ["User"]) in world.gates.calls


def test_a_saved_analysis_posts_the_analysis_note_with_its_result_context():
    world = make_world()
    world.reader.saved_inputs = [{"name": "report.csv"}]

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    message = world.delivery_messages()[0]
    assert message["content"] == note_content(KIND_ANALYSIS)
    assert message["metadata"]["workflow_delivery"]["kind"] == KIND_ANALYSIS
    assert message["metadata"]["workflow_result_contexts"] == result_contexts()
    assert world.models.calls == []


def test_a_closed_result_posts_the_status_note():
    world = make_world()
    world.reader.outcomes.append(FakeResultUnavailable("workflow_result_source_access_lost"))

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    message = world.delivery_messages()[0]
    assert message["content"] == note_content(KIND_STATUS)
    assert "workflow_result" not in message["metadata"]
    assert world.models.calls == []


def test_a_blocked_reply_posts_the_blocked_note_and_records_an_incident():
    world = make_world()
    world.checker.block = True

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    message = world.delivery_messages()[0]
    assert message["content"] == note_content(KIND_CONTENT_BLOCKED)
    assert COMPOSED_REPLY not in message["content"]
    assert message["metadata"]["workflow_delivery"]["kind"] == KIND_CONTENT_BLOCKED
    assert "workflow_result" not in message["metadata"]
    assert message["model_deployment_name"] is None
    assert world.record()["outcome_reason"] == REASON_CONTENT_BLOCKED
    assert world.incidents.calls == [{
        "args": ({
            "id": M5,
            "conversation_id": CONVERSATION_ID,
            "content_check": {"blocked": True, "categories": ["hate"]},
        }, USER),
        "kwargs": {},
    }]
    assert len(world.tokens.calls) == 1, "the compose still ran, so it is still counted"


def test_a_blocked_fallback_posts_the_blocked_note():
    world = make_world()
    world.checker.block = True
    world.models.selected.replies.append(fake_response(finish_reason="content_filter"))
    world.models.default.replies.append(fake_response(finish_reason="content_filter"))

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    message = world.delivery_messages()[0]
    assert message["content"] == note_content(KIND_CONTENT_BLOCKED), "the trimmed fallback must be checked too"
    assert RESULT_TEXT not in message["content"]
    assert TRIMMED_FALLBACK_INTRO in world.checker.calls[0]["text"]


def test_a_content_check_outage_retries_and_counts_each_compose_once():
    world = make_world()
    world.checker.error = RuntimeError("content safety down")

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_RETRY_SCHEDULED

    record = world.record()
    assert record["status"] == "ready"
    assert record["attempts"] == 1
    assert record["next_attempt_at"] == "2026-05-04T15:00:30.000000Z"
    assert world.delivery_messages() == []
    assert world.unread_calls == [], "the chat must not be marked unread before the content is ready"
    assert world.notifications.chat_calls == []

    world.checker.error = None
    make_due(world)
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert world.record()["attempts"] == 2
    assert [call["kwargs"]["idempotency_key"] for call in world.tokens.calls] == [
        f"workflow_result_delivery:{M5}:1",
        f"workflow_result_delivery:{M5}:2",
    ]
    assert len(world.delivery_messages()) == 1


@pytest.mark.parametrize(
    ("state", "gate_reason_code", "reason_code"),
    [
        ("failed", None, "failed"),
        ("invalid", None, "invalid"),
        ("incomplete", None, "incomplete"),
        ("failed", "deadline_exceeded", "deadline_exceeded"),
    ],
)
def test_a_failed_run_posts_the_failure_note(state, gate_reason_code, reason_code):
    world = terminal_world(state)
    if gate_reason_code:
        world.runtime.set(state=state, version=5, gate_reason_code=gate_reason_code)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    message = world.delivery_messages()[0]
    assert message["content"] == note_content(KIND_FAILED, reason_code=reason_code)
    delivery = message["metadata"]["workflow_delivery"]
    assert delivery["kind"] == KIND_FAILED
    assert delivery["run_status"] == state
    assert "workflow_result" not in message["metadata"]
    assert world.reader.calls == [] and world.models.calls == []
    assert world.notifications.chat_calls == [delivered_notice()]


@pytest.mark.parametrize(("state", "kind"), [("cancelled", KIND_CANCELLED), ("skipped", KIND_SKIPPED)])
def test_a_cancelled_or_skipped_run_posts_its_note(state, kind):
    world = terminal_world(state)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    message = world.delivery_messages()[0]
    assert message["content"] == note_content(kind)
    assert message["metadata"]["workflow_delivery"]["kind"] == kind
    assert world.reader.calls == [] and world.models.calls == []


@pytest.mark.parametrize("change", ["retracted", "removed", "not_a_user_message"])
def test_a_missing_or_retracted_request_uses_the_fixed_question(change):
    world = make_world()
    if change == "retracted":
        edit_request_message(world, retracted=True)
    elif change == "removed":
        world.messages.items.pop(USER_MESSAGE_ID)
    else:
        edit_request_message(world, role="assistant")

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert world.prompts.calls[0]["question"] == FALLBACK_QUESTION


def test_a_long_request_is_clipped_before_it_reaches_the_model():
    world = make_world()
    edit_request_message(world, content="x" * 5000)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert world.prompts.calls[0]["question"] == "x" * worker.QUESTION_MAX_CHARS
    assert worker.QUESTION_MAX_CHARS == 4000


# ---------------------------------------------------------------------------------------------
# C. Phases: a crash or outage at any step never posts twice
# ---------------------------------------------------------------------------------------------


def user_reads_chat(world):
    """What the mark-read route does: clear the unread state and keep ``last_updated``."""
    conversation = clear_conversation_unread(world.conversation())
    world.conversations.put(conversation)


def seconds_until_next_attempt(world):
    record = world.record()
    return (parse_iso(record["next_attempt_at"]) - parse_iso(world.clock.now)).total_seconds()


def test_a_failed_create_retries_without_a_second_unread_mark():
    world = make_world()
    world.messages.fail("create_item", cosmos_error(503))

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_RETRY_SCHEDULED
    assert world.record()["phase"] == "unread_marked"
    assert world.delivery_messages() == []
    user_reads_chat(world)
    make_due(world)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert [message["id"] for message in world.delivery_messages()] == [M5]
    assert len(world.unread_calls) == 1, "the retry must not mark the chat unread again"
    conversation = world.conversation()
    assert conversation["has_unread_assistant_response"] is False, (
        "a chat read between the mark and the create stays read (documented limitation)"
    )
    assert conversation["last_updated"] == "2026-05-04T15:00:00.000000"
    assert len(world.models.requests) == 2
    assert world.record()["attempts"] == 2


def test_a_failed_unread_mark_retries_with_the_earlier_planned_time():
    world = make_world()
    world.conversations.fail("replace_item", cosmos_error(503))

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_RETRY_SCHEDULED
    assert world.record()["phase"] == "publishing"
    make_due(world)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert [call["skip_if_read_since"] for call in world.unread_calls] == [None, "2026-05-04T15:00:00.000000"]
    assert [call["planned_at"] for call in world.unread_calls] == [
        "2026-05-04T15:00:00.000000",
        "2026-05-04T15:00:31.000000",
    ]
    conversation = world.conversation()
    assert conversation["has_unread_assistant_response"] is True
    assert conversation["last_unread_assistant_message_id"] == M5
    assert conversation["last_unread_assistant_at"] == "2026-05-04T15:00:31.000000"
    assert world.delivery_messages()[0]["timestamp"] == "2026-05-04T15:00:31.000000"


def test_a_mark_whose_phase_write_failed_is_not_repeated_after_the_user_reads():
    world = make_world()
    world.runs.fail("replace_item", None, None, cosmos_error(503))

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_RETRY_SCHEDULED
    assert world.record()["phase"] == "publishing"
    assert world.conversation()["last_unread_assistant_message_id"] == M5
    user_reads_chat(world)
    make_due(world)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert len(world.unread_calls) == 2
    assert world.unread_calls[1]["skip_if_read_since"] == "2026-05-04T15:00:00.000000"
    assert world.conversation()["has_unread_assistant_response"] is False
    assert len(world.cache_bumps.calls) == 1, "only the mark that landed bumps the chat list"
    assert [message["id"] for message in world.delivery_messages()] == [M5]


def test_a_message_that_already_exists_is_kept_not_duplicated():
    world = make_world()
    world.messages.put({
        "id": M5,
        "conversation_id": CONVERSATION_ID,
        "role": "assistant",
        "content": "posted by an earlier attempt",
        "timestamp": "2026-05-04T14:59:59.000000",
    })

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    messages = world.delivery_messages()
    assert [message["id"] for message in messages] == [M5]
    assert messages[0]["content"] == "posted by an earlier attempt"
    assert world.record()["phase"] == "notified"
    assert world.notifications.chat_calls == [delivered_notice()]


def test_a_create_whose_reply_was_lost_is_found_on_the_retry():
    world = make_world()
    original_create = world.messages.create_item

    def create_then_fail(body=None, **kwargs):
        world.messages.create_item = original_create
        original_create(body=body, **kwargs)
        raise cosmos_error(503)

    world.messages.create_item = create_then_fail

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_RETRY_SCHEDULED
    assert world.record()["phase"] == "unread_marked"
    make_due(world)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert [message["id"] for message in world.delivery_messages()] == [M5]
    assert len(world.models.requests) == 1, "a message found on the retry is never composed again"
    assert len(world.unread_calls) == 1
    assert world.notifications.chat_calls == [delivered_notice()]


def test_a_create_that_loses_a_race_keeps_the_message_already_posted():
    world = make_world()
    original_create = world.messages.create_item

    def another_attempt_posts_first(body=None, **kwargs):
        world.messages.create_item = original_create
        world.messages.put({**body, "content": "posted by a racing attempt"})
        return original_create(body=body, **kwargs)

    world.messages.create_item = another_attempt_posts_first

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED, "a 409 on create means the message is already in the chat"

    messages = world.delivery_messages()
    assert [message["id"] for message in messages] == [M5]
    assert messages[0]["content"] == "posted by a racing attempt", "the message already posted is kept"
    assert world.record()["phase"] == "notified"
    assert world.record()["attempts"] == 1, "a create that lost a race needs no retry"
    assert world.notifications.chat_calls == [delivered_notice()]


def test_a_failed_notice_is_sent_on_the_retry_without_reposting():
    world = make_world()
    world.notifications.chat_errors.append(RuntimeError("bell down"))

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_RETRY_SCHEDULED
    assert world.record()["phase"] == "message_created"
    make_due(world)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert len(world.notifications.chat_calls) == 2
    assert list(world.notifications.stored) == [f"workflow-chat-delivery:{RUN_ID}:5"]
    assert len(world.reader.calls) == 1
    assert len(world.unread_calls) == 1
    assert len(world.delivery_messages()) == 1
    assert world.record()["notice_kind"] == "chat_response"


def test_a_notice_that_never_lands_backs_off_then_closes_delivered_without_one():
    world = make_world()
    world.notifications.chat_errors.extend(RuntimeError("bell down") for _ in range(20))

    outcomes, waits = [], []
    for _ in range(MAX_ATTEMPTS):
        outcome = deliver(world)
        outcomes.append(outcome)
        if outcome != worker.OUTCOME_RETRY_SCHEDULED:
            break
        waits.append(seconds_until_next_attempt(world))
        make_due(world)

    assert outcomes == [worker.OUTCOME_RETRY_SCHEDULED] * 7 + [worker.OUTCOME_DELIVERED]
    assert waits == [next_backoff_seconds(attempt) for attempt in range(1, 8)]
    assert waits == [30, 60, 120, 240, 480, 900, 900]
    record = world.record()
    assert record["status"] == "delivered" and record["notice_kind"] == "none"
    assert record["attempts"] == MAX_ATTEMPTS
    assert len(world.notifications.chat_calls) == 9, "eight attempts plus one last best-effort notice"
    assert world.notifications.stored == {}
    assert len(world.delivery_messages()) == 1


def test_a_created_message_still_gets_its_notice_after_the_window_closes():
    world = make_world()
    world.notifications.chat_errors.append(RuntimeError("bell down"))
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_RETRY_SCHEDULED
    world.clock.now = shift(world.record()["expires_at"], days=1)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert world.record()["notice_kind"] == "chat_response"
    assert len(world.notifications.stored) == 1
    assert world.notifications.notice_calls == []


def test_a_lost_lease_stops_the_attempt_before_the_chat_changes():
    world = make_world()
    check = world.services.check_content

    def check_then_lose_lease(*args, **kwargs):
        world.set_record(lease_id="lease-other", lease_expires_at="2026-05-04T15:05:00.000000Z")
        return check(*args, **kwargs)

    world.services.check_content = check_then_lose_lease

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_LOST_LEASE

    assert world.unread_calls == []
    assert world.delivery_messages() == []
    assert world.notifications.chat_calls == [] and world.notifications.notice_calls == []
    assert world.record()["lease_id"] == "lease-other"


# ---------------------------------------------------------------------------------------------
# D. Closures: nothing posted, at most one notice
# ---------------------------------------------------------------------------------------------


EXPIRED_TITLE = "\"Daily digest\" didn't finish in time to post to chat"


def expired_notice():
    notice = undeliverable_notice(title=EXPIRED_TITLE)
    notice.update({
        "message": EXPIRED_NOTICE_MESSAGE,
        "idempotency_key": f"workflow-chat-delivery-notice:{RUN_ID}:expired",
    })
    notice["metadata"]["delivery_status"] = "expired"
    return notice


def assert_nothing_posted(world):
    assert world.delivery_messages() == []
    assert world.unread_calls == []
    assert world.notifications.chat_calls == []


def assert_closed(world, *, status="undeliverable", reason, notice_kind, attempts):
    record = world.record()
    assert record["status"] == status
    assert record["outcome_reason"] == reason
    assert record["notice_kind"] == notice_kind
    assert record["attempts"] == attempts
    assert record["lease_id"] is None and record["next_attempt_at"] is None


@pytest.mark.parametrize(
    "change",
    ["removed", "another_owner", "converted_to_collaboration", "shared", "deleted", "orchestration_deleted"],
)
def test_a_chat_that_cannot_take_the_delivery_gets_one_notice_instead(change):
    world = make_world()
    if change == "removed":
        world.conversations.items.pop(CONVERSATION_ID)
    else:
        conversation = world.conversation()
        conversation.update({
            "another_owner": {"user_id": OTHER_USER},
            "converted_to_collaboration": {"converted_to_collaboration_at": "2026-05-04T14:30:00Z"},
            "shared": {"collaboration_conversation_id": "collaboration-1"},
            "deleted": {"deleted": True},
            "orchestration_deleted": {"orchestration_deleted": True},
        }[change])
        world.conversations.put(conversation)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_UNDELIVERABLE

    assert_nothing_posted(world)
    assert world.notifications.notice_calls == [undeliverable_notice()]
    assert world.reader.calls == [] and world.models.calls == []
    assert_closed(world, reason="chat_unavailable", notice_kind="undeliverable", attempts=1)


def test_losing_workflow_access_gets_one_notice_instead():
    world = make_world()
    world.gates.workflows = False

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_UNDELIVERABLE

    assert_nothing_posted(world)
    assert world.notifications.notice_calls == [undeliverable_notice()]
    assert world.gates.calls == [("workflows", ["User"])]
    assert_closed(world, reason="access_lost", notice_kind="undeliverable", attempts=1)


@pytest.mark.parametrize("change", ["removed", "deleting", "status_deleting", "another_owner"])
def test_a_deleted_workflow_closes_silently(change):
    world = make_world()
    if change == "removed":
        world.workflows.items.pop(WORKFLOW_ID)
    else:
        workflow = world.workflows.get(WORKFLOW_ID)
        workflow.update({
            "deleting": {"deleting": True},
            "status_deleting": {"status": "deleting"},
            "another_owner": {"user_id": OTHER_USER},
        }[change])
        world.workflows.put(workflow)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_CLOSED_SILENTLY

    assert_nothing_posted(world)
    assert world.notifications.notice_calls == []
    assert_closed(world, reason="workflow_deleted", notice_kind="none", attempts=1)


def test_a_run_deleted_while_pending_closes_silently_without_an_attempt():
    world = make_world(run=make_run(status="running"), state="running", version=3)
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_PENDING
    world.runtime.tombstone()

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_CLOSED_SILENTLY

    assert_nothing_posted(world)
    assert world.notifications.notice_calls == []
    assert_closed(world, reason="workflow_deleted", notice_kind="none", attempts=0)


def test_a_run_deleted_while_ready_closes_silently_without_an_attempt():
    world = make_world()
    world.stream.active = True
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DEFERRED
    world.runtime.tombstone()
    make_due(world)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_CLOSED_SILENTLY

    assert_nothing_posted(world)
    assert world.notifications.notice_calls == []
    assert_closed(world, reason="workflow_deleted", notice_kind="none", attempts=0)


@pytest.mark.parametrize("change", ["tombstone", "remove"])
def test_a_run_deleted_after_delivery_stays_delivered(change):
    world = make_world()
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED
    getattr(world.runtime, change)()
    writes = total_writes(world)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_NOT_APPLICABLE

    assert total_writes(world) == writes
    assert len(world.delivery_messages()) == 1
    assert len(world.notifications.chat_calls) == 1
    assert world.notifications.notice_calls == []
    assert world.record()["status"] == "delivered"


def test_a_missing_runtime_control_closes_silently_without_an_attempt():
    world = make_world(control=False)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_CLOSED_SILENTLY

    assert_nothing_posted(world)
    assert world.notifications.notice_calls == []
    assert_closed(world, reason="runtime_missing", notice_kind="none", attempts=0)
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_NOT_APPLICABLE


def test_a_run_that_never_finishes_in_the_window_gets_the_expired_notice():
    world = make_world(run=make_run(status="running"), state="running", version=3)
    world.clock.now = shift(world.record()["expires_at"], seconds=1)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_EXPIRED

    assert_nothing_posted(world)
    assert world.notifications.notice_calls == [expired_notice()]
    record = world.record()
    assert record["status"] == "expired" and record["notice_kind"] == "expired"
    assert record["kind"] == "expired" and record["generation"] == 3

    world.runtime.update(state="completed", version=5)
    set_run_status(world, "completed")
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_NOT_APPLICABLE, "an expired record is never reopened"
    assert world.delivery_messages() == []
    assert len(world.notifications.notice_calls) == 1


def test_a_run_paused_at_its_deadline_gets_the_expired_notice_at_once():
    world = make_world(run=make_run(status="paused"), state="paused", version=4)
    world.runtime.set(state="paused", version=4, gate_reason_code="deadline_exceeded")

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_EXPIRED

    assert world.notifications.notice_calls == [expired_notice()]
    assert world.delivery_messages() == []


def test_an_expired_notice_that_keeps_failing_still_closes_as_expired():
    world = make_world(run=make_run(status="running"), state="running", version=3)
    world.clock.now = shift(world.record()["expires_at"], seconds=1)
    world.notifications.notice_errors.extend(RuntimeError("bell down") for _ in range(20))

    outcomes = deliver_until(world, {worker.OUTCOME_EXPIRED})

    assert outcomes == [worker.OUTCOME_RETRY_SCHEDULED] * 7 + [worker.OUTCOME_EXPIRED]
    record = world.record()
    assert record["status"] == "expired" and record["notice_kind"] == "none"
    assert world.notifications.stored == {}


def test_a_run_that_finished_after_the_window_gets_one_notice_and_no_post():
    world = make_world()
    world.clock.now = shift(world.record()["expires_at"], seconds=1)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_UNDELIVERABLE

    assert_nothing_posted(world)
    assert world.notifications.notice_calls == [undeliverable_notice()]
    assert world.reader.calls == []
    assert_closed(world, reason="expired_before_delivery", notice_kind="undeliverable", attempts=1)


def test_a_notice_sent_before_a_failed_close_is_not_sent_twice():
    world = make_world()
    world.conversations.items.pop(CONVERSATION_ID)
    world.runs.fail("replace_item", None, cosmos_error(503))

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_RETRY_SCHEDULED
    make_due(world)
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_UNDELIVERABLE

    assert len(world.notifications.notice_calls) == 2
    assert world.notifications.notices() == [undeliverable_notice()]
    assert_closed(world, reason="chat_unavailable", notice_kind="undeliverable", attempts=2)


def test_an_undeliverable_notice_that_never_lands_closes_without_one():
    world = make_world()
    world.conversations.items.pop(CONVERSATION_ID)
    world.notifications.notice_errors.extend(RuntimeError("bell down") for _ in range(20))

    outcomes = deliver_until(world, {worker.OUTCOME_UNDELIVERABLE})

    assert outcomes == [worker.OUTCOME_RETRY_SCHEDULED] * 7 + [worker.OUTCOME_UNDELIVERABLE]
    assert_closed(world, reason="delivery_failed", notice_kind="none", attempts=MAX_ATTEMPTS)
    assert world.notifications.stored == {}


# ---------------------------------------------------------------------------------------------
# E. Deferral while the chat is busy (D7)
# ---------------------------------------------------------------------------------------------


def add_user_message(world, timestamp, message_id="message-user-2"):
    world.messages.put({
        "id": message_id,
        "conversation_id": CONVERSATION_ID,
        "role": "user",
        "content": "Something else while the run worked.",
        "timestamp": timestamp,
        "metadata": {"thread_info": {"thread_id": "thread-later", "previous_thread_id": "thread-request",
                                     "active_thread": True, "thread_attempt": 1}},
    })


def test_an_active_stream_defers_without_spending_an_attempt():
    world = make_world()
    world.stream.active = True

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DEFERRED

    record = world.record()
    assert record["status"] == "ready" and record["attempts"] == 0
    assert record["first_deferred_at"] == "2026-05-04T15:00:00.000000Z"
    assert seconds_until_next_attempt(world) == 30
    assert world.reader.calls == [] and world.unread_calls == []
    assert world.stream.calls[0][:2] == (USER, CONVERSATION_ID)
    world.stream.active = False
    make_due(world)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert world.record()["attempts"] == 1


def test_a_recent_user_message_defers_until_the_chat_has_been_quiet_for_ten_minutes():
    world = make_world()
    add_user_message(world, "2026-05-04T14:59:00.000000")

    outcomes = deliver_until(world, {worker.OUTCOME_DELIVERED})

    assert outcomes == [worker.OUTCOME_DEFERRED] * 18 + [worker.OUTCOME_DELIVERED]
    message = world.delivery_messages()[0]
    assert message["timestamp"] == "2026-05-04T15:09:18.000000"
    assert message["metadata"]["thread_info"]["previous_thread_id"] == "thread-later"
    assert world.record()["attempts"] == 1


def test_an_older_user_message_does_not_defer():
    world = make_world()
    add_user_message(world, "2026-05-04T14:49:59.000000")

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED


def test_a_chat_that_stays_busy_gets_the_delivery_after_fifteen_minutes():
    world = make_world()
    world.stream.active = True

    outcomes = deliver_until(world, {worker.OUTCOME_DELIVERED})

    assert outcomes == [worker.OUTCOME_DEFERRED] * 30 + [worker.OUTCOME_DELIVERED]
    assert world.delivery_messages()[0]["timestamp"] == "2026-05-04T15:15:30.000000"
    assert world.record()["attempts"] == 1


def test_unreadable_chat_activity_backs_off_then_gives_up_with_one_notice():
    world = make_world()
    world.messages.fail("query_items", *[cosmos_error(503) for _ in range(20)])

    outcomes, waits = [], []
    for _ in range(MAX_ATTEMPTS):
        outcome = deliver(world)
        outcomes.append(outcome)
        if outcome != worker.OUTCOME_DEFERRED:
            break
        waits.append(seconds_until_next_attempt(world))
        make_due(world)

    assert outcomes == [worker.OUTCOME_DEFERRED] * 7 + [worker.OUTCOME_UNDELIVERABLE]
    assert waits == [30, 60, 120, 240, 480, 900, 900], "a counted deferral backs off like a failed attempt"
    assert_nothing_posted(world)
    assert world.reader.calls == []
    assert world.notifications.notices() == [undeliverable_notice()]
    assert_closed(world, reason="delivery_failed", notice_kind="undeliverable", attempts=MAX_ATTEMPTS)


def test_the_message_found_check_comes_before_the_busy_check():
    world = make_world()
    world.messages.fail("create_item", cosmos_error(503))
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_RETRY_SCHEDULED
    world.stream.active = True
    make_due(world)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED, "a marked chat is published even mid-stream"

    assert [message["id"] for message in world.delivery_messages()] == [M5]


# ---------------------------------------------------------------------------------------------
# F. Transient failures
# ---------------------------------------------------------------------------------------------


def run_until_settled(world, retry_outcome, final_outcome):
    outcomes, waits = [], []
    for _ in range(MAX_ATTEMPTS + 2):
        outcome = deliver(world)
        outcomes.append(outcome)
        if outcome != retry_outcome:
            break
        waits.append(seconds_until_next_attempt(world))
        make_due(world)
    assert outcomes[-1] == final_outcome, outcomes
    return outcomes, waits


def test_an_unreadable_runtime_control_backs_off_then_closes_silently():
    world = make_world()
    world.runtime.fail(RUN_ID, *[FakeRuntimeUnavailable() for _ in range(20)])

    outcomes, waits = run_until_settled(world, worker.OUTCOME_RETRY_SCHEDULED, worker.OUTCOME_CLOSED_SILENTLY)

    assert outcomes == [worker.OUTCOME_RETRY_SCHEDULED] * 7 + [worker.OUTCOME_CLOSED_SILENTLY]
    assert waits == [30, 60, 120, 240, 480, 900, 900]
    assert_nothing_posted(world)
    assert world.notifications.notice_calls == []
    assert_closed(world, reason="delivery_failed", notice_kind="none", attempts=MAX_ATTEMPTS)
    assert world.record()["generation"] is None, "no outcome was ever read"


def test_an_early_hint_never_spends_an_attempt_on_an_unreadable_control():
    world = make_world()
    world.runtime.fail(RUN_ID, FakeRuntimeUnavailable())
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_RETRY_SCHEDULED
    world.runtime.fail(RUN_ID, FakeRuntimeUnavailable())
    writes = total_writes(world)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_NOT_DUE

    assert total_writes(world) == writes
    assert world.record()["attempts"] == 1
    make_due(world)
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED
    assert world.record()["attempts"] == 2


def test_a_control_that_recovers_delivers_normally():
    world = make_world()
    world.runtime.fail(RUN_ID, FakeRuntimeUnavailable(), FakeRuntimeUnavailable())

    outcomes, _waits = run_until_settled(world, worker.OUTCOME_RETRY_SCHEDULED, worker.OUTCOME_DELIVERED)

    assert outcomes == [worker.OUTCOME_RETRY_SCHEDULED] * 2 + [worker.OUTCOME_DELIVERED]
    assert world.record()["attempts"] == 3
    assert [message["id"] for message in world.delivery_messages()] == [M5]


def test_unreadable_result_storage_backs_off_then_gives_up_with_one_notice():
    world = make_world()
    world.reader.outcomes.extend(FakeResultUnavailable("workflow_result_storage_unavailable") for _ in range(20))

    outcomes, waits = run_until_settled(world, worker.OUTCOME_RETRY_SCHEDULED, worker.OUTCOME_UNDELIVERABLE)

    assert outcomes == [worker.OUTCOME_RETRY_SCHEDULED] * 7 + [worker.OUTCOME_UNDELIVERABLE]
    assert waits == [30, 60, 120, 240, 480, 900, 900]
    assert len(world.reader.calls) == MAX_ATTEMPTS, "every attempt reads the result once"
    assert_nothing_posted(world)
    assert world.notifications.notices() == [undeliverable_notice()]
    assert_closed(world, reason="delivery_failed", notice_kind="undeliverable", attempts=MAX_ATTEMPTS)


def test_a_settings_read_failure_retries():
    world = make_world()
    calls = {"count": 0}
    read_settings = world.services.get_settings

    def flaky_settings():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("settings store down")
        return read_settings()

    world.services.get_settings = flaky_settings

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_RETRY_SCHEDULED
    assert world.record()["phase"] == "claimed"
    make_due(world)
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED


def test_an_unexpected_error_is_retried_like_a_failed_attempt():
    world = make_world()

    def broken_probe(*args, **kwargs):
        raise ValueError("unexpected")

    world.services.stream_activity_probe = broken_probe

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_RETRY_SCHEDULED

    record = world.record()
    assert record["status"] == "ready" and record["lease_id"] is None
    assert seconds_until_next_attempt(world) == 30
    assert world.delivery_messages() == [] and world.unread_calls == []
    world.services.stream_activity_probe = world.stream
    make_due(world)
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED
    assert world.record()["attempts"] == 2


def test_an_outcome_that_cannot_be_recorded_waits_for_the_lease_to_lapse():
    world = make_world()
    world.stream.active = True
    world.runs.fail("replace_item", None, cosmos_error(503))

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_UNAVAILABLE

    record = world.record()
    assert record["status"] == "delivering" and record["lease_id"]
    world.stream.active = False
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_BUSY
    world.clock.now = shift(record["lease_expires_at"], seconds=1)
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED
    assert world.record()["attempts"] == 2


# ---------------------------------------------------------------------------------------------
# G. Generations: a durable resume is a new outcome
# ---------------------------------------------------------------------------------------------


def resume_run(world, version, state="queued"):
    """What ``runtime/resume`` does to the control and the run document projection."""
    world.runtime.update(state=state, version=version)
    set_run_status(world, state)


def test_a_resumed_run_delivers_its_new_outcome_after_the_failed_note():
    world = terminal_world("failed")
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED
    assert world.delivery_messages()[0]["content"] == note_content(KIND_FAILED)
    resume_run(world, 6)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_PENDING

    record = world.record()
    assert record["status"] == "pending" and record["generation"] is None and record["attempts"] == 0
    assert record["history"] == [{
        "generation": 5,
        "status": "delivered",
        "kind": "failed",
        "outcome_reason": None,
        "message_id": M5,
        "delivered_at": "2026-05-04T15:00:00.000000Z",
        "notice_kind": "chat_response",
    }]
    resume_run(world, 8, state="completed")

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert [message["id"] for message in world.delivery_messages()] == [M5, M8]
    assert world.notifications.chat_calls == [delivered_notice(M5, 5), delivered_notice(M8, 8)]
    record = world.record()
    assert record["generation"] == 8 and record["kind"] == "result" and record["message_id"] == M8
    assert world.delivery_messages()[1]["metadata"]["workflow_delivery"]["generation"] == 8


def test_a_new_outcome_replaces_a_generation_that_was_never_posted():
    world = make_world()
    world.stream.active = True
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DEFERRED
    world.runtime.update(state="completed", version=8)
    world.stream.active = False
    make_due(world)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert [message["id"] for message in world.delivery_messages()] == [M8]
    assert world.notifications.chat_calls == [delivered_notice(M8, 8)]
    assert world.record()["history"] == [], "a generation that was never posted leaves no history"


def test_a_resume_that_finishes_during_a_delivery_is_delivered_next():
    world = make_world()
    notify = world.services.create_chat_response_notification

    def notify_then_resume(*args, **kwargs):
        world.services.create_chat_response_notification = notify
        world.runtime.update(state="completed", version=8)
        return notify(*args, **kwargs)

    world.services.create_chat_response_notification = notify_then_resume

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    assert world.hints.signals == [(USER, RUN_ID)]
    record = world.record()
    assert record["status"] == "ready" and record["generation"] == 8
    assert record["history"][-1]["generation"] == 5

    outcomes = worker.process_workflow_chat_delivery_hints(world.services)

    assert outcomes == [(RUN_ID, worker.OUTCOME_DELIVERED)]
    assert [message["id"] for message in world.delivery_messages()] == [M5, M8]
    assert world.hints.queue == []


def test_a_cancelled_resume_does_not_reopen_a_delivered_record():
    world = make_world()
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED
    world.runtime.update(state="completed", version=5)
    writes = total_writes(world)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_NOT_APPLICABLE

    assert total_writes(world) == writes
    assert world.record()["history"] == []


# ---------------------------------------------------------------------------------------------
# H. The sweep and the hints (D8)
# ---------------------------------------------------------------------------------------------


def add_runs(world, count):
    """``count`` finished runs in all, each with its own runtime control."""
    run_ids = [RUN_ID]
    for index in range(2, count + 1):
        run_id = f"{RUN_ID}-{index}"
        world.runs.put(make_run(id=run_id))
        world.runtime.set(run_id=run_id)
        run_ids.append(run_id)
    return run_ids


def sweep(world):
    return worker.run_workflow_chat_delivery_sweep(world.services)


def test_the_sweep_queries_nothing_without_the_lock():
    world = make_world()
    world.lock.available = False
    world.clock.advance(minutes=3)

    summary = sweep(world)
    assert summary == {"locked": False, "processed": 0, "outcomes": {}}

    assert world.runs.query_calls == []
    assert world.lock.released == []
    assert world.record()["status"] == "pending"


def test_the_sweep_leaves_a_just_finished_run_to_its_hint():
    world = make_world()

    summary = sweep(world)
    assert summary == {"locked": True, "processed": 0, "outcomes": {}}
    world.clock.advance(minutes=3)

    summary = sweep(world)
    assert summary == {"locked": True, "processed": 1, "outcomes": {worker.OUTCOME_DELIVERED: 1}}

    assert [message["id"] for message in world.delivery_messages()] == [M5]


def test_the_sweep_queries_across_users_under_its_lock():
    world = make_world()
    world.clock.advance(minutes=3)

    sweep(world)

    assert world.lock.acquired == [(SWEEP_LOCK_NAME, SWEEP_LOCK_SECONDS)]
    assert world.lock.released == [{"id": SWEEP_LOCK_NAME, "seconds": SWEEP_LOCK_SECONDS}]
    (call,) = world.runs.query_calls
    assert call["query"] == worker.SWEEP_QUERY
    assert call["enable_cross_partition_query"] is True and call["partition_key"] is None
    params = {entry["name"]: entry["value"] for entry in call["parameters"]}
    assert params["@now"] == "2026-05-04T15:03:00.000000Z"
    assert params["@grace_ts"] == int(parse_iso("2026-05-04T15:01:00+00:00").timestamp())


def test_a_failed_sweep_query_still_releases_the_lock():
    world = make_world()
    world.runs.fail("query_items", cosmos_error(503))

    summary = sweep(world)
    assert summary == {"locked": True, "processed": 0, "outcomes": {}}

    assert len(world.lock.released) == 1


@pytest.mark.parametrize("step, processed", [(40.0, 2), (50.0, 1)])
def test_the_sweep_stops_at_its_time_budget(step, processed):
    world = make_world()
    add_runs(world, 5)
    world.clock.advance(minutes=3)
    world.monotonic.step = step

    summary = sweep(world)
    assert summary["processed"] == processed


def test_the_sweep_processes_at_most_eight_runs_a_pass():
    world = make_world()
    run_ids = add_runs(world, 10)
    world.clock.advance(minutes=3)

    summary = sweep(world)
    assert summary == {
        "locked": True,
        "processed": SWEEP_MAX_RUNS,
        "outcomes": {worker.OUTCOME_DELIVERED: SWEEP_MAX_RUNS},
    }
    summary = sweep(world)
    assert summary["processed"] == 2

    assert [world.record(run_id)["status"] for run_id in run_ids] == ["delivered"] * 10
    assert len(world.delivery_messages()) == 10


def test_the_sweep_closes_a_run_without_a_runtime_control_in_one_pass():
    world = make_world(control=False)
    world.clock.advance(minutes=3)

    summary = sweep(world)
    assert summary["outcomes"] == {worker.OUTCOME_CLOSED_SILENTLY: 1}

    assert world.record()["outcome_reason"] == "runtime_missing"
    summary = sweep(world)
    assert summary["processed"] == 0
    assert world.notifications.notice_calls == []


def test_the_sweep_picks_up_a_retry_when_it_is_due():
    world = make_world()
    world.messages.fail("create_item", cosmos_error(503))
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_RETRY_SCHEDULED

    summary = sweep(world)
    assert summary["processed"] == 0
    make_due(world)
    summary = sweep(world)
    assert summary["outcomes"] == {worker.OUTCOME_DELIVERED: 1}


def test_hints_are_processed_without_the_sweep_lock():
    world = make_world()
    world.lock.available = False
    world.hints.signal(USER, RUN_ID)

    hint_outcomes = worker.process_workflow_chat_delivery_hints(world.services)
    assert hint_outcomes == [(RUN_ID, worker.OUTCOME_DELIVERED)]

    assert world.hints.queue == []
    assert world.lock.acquired == []


# ---------------------------------------------------------------------------------------------
# I. Guards
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("user_id, run_id", [("", RUN_ID), (None, RUN_ID), (USER, ""), (USER, None)])
def test_missing_ids_are_not_applicable(user_id, run_id):
    world = make_world()

    outcome = worker.process_workflow_chat_delivery(user_id, run_id, services=world.services)
    assert outcome == worker.OUTCOME_NOT_APPLICABLE

    assert total_writes(world) == 0


def test_a_run_without_a_delivery_record_is_not_applicable():
    run = make_run()
    run.pop("chat_delivery")
    world = make_world(run=run)

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_NOT_APPLICABLE
    assert total_writes(world) == 0


@pytest.mark.parametrize("user_id, run_id", [(USER, "run-missing"), (OTHER_USER, RUN_ID)])
def test_a_missing_or_foreign_run_is_not_applicable(user_id, run_id):
    world = make_world()

    outcome = deliver(world, run_id=run_id, user_id=user_id)
    assert outcome == worker.OUTCOME_NOT_APPLICABLE

    assert total_writes(world) == 0
    assert world.runtime.reads == []


def claimed_record(**changes):
    record = make_record(status="delivering", generation=5, kind="result", run_status="completed", phase="claimed",
                         attempts=1, lease_id="lease-other")
    record.update(changes)
    return record


def test_a_live_lease_is_left_alone():
    world = make_world(run=make_run(record=claimed_record(lease_expires_at="2026-05-04T15:04:00.000000Z")))

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_BUSY

    assert total_writes(world) == 0
    assert world.runtime.reads == []


def test_an_abandoned_claim_is_taken_over_after_its_lease_lapses():
    world = make_world(run=make_run(record=claimed_record(lease_expires_at="2026-05-04T14:59:59.000000Z")))

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED

    record = world.record()
    assert record["attempts"] == 2 and record["lease_id"] is None
    assert [message["id"] for message in world.delivery_messages()] == [M5]


def test_a_record_that_is_not_due_is_left_alone():
    record = make_record(status="ready", generation=5, kind="result", run_status="completed", attempts=1,
                         next_attempt_at="2026-05-04T15:01:00.000000Z")
    world = make_world(run=make_run(record=record))

    outcome = deliver(world)
    assert outcome == worker.OUTCOME_NOT_DUE

    assert total_writes(world) == 0


def test_a_closed_record_is_never_claimed_again():
    world = make_world()
    outcome = deliver(world)
    assert outcome == worker.OUTCOME_DELIVERED
    writes = total_writes(world)

    for _ in range(3):
        outcome = deliver(world)
        assert outcome == worker.OUTCOME_NOT_APPLICABLE

    assert total_writes(world) == writes
    assert len(world.notifications.chat_calls) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
