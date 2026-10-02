#!/usr/bin/env python3
# test_workflow_chat_delivery_save_guard.py
"""
Functional test for the workflow chat delivery guarded run save.
Version: 0.261.227
Implemented in: 0.261.227

This test ensures chat-started workflow run saves preserve delivered chat-delivery state across stale full-document writes and worker retries.
"""

import copy
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "application" / "single_app", ROOT / "functional_tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402
from azure.cosmos.exceptions import CosmosHttpResponseError  # noqa: E402

import functions_workflow_chat_delivery_worker as worker  # noqa: E402
from functions_conversation_unread import clear_conversation_unread  # noqa: E402
from functions_workflow_chat_delivery import (  # noqa: E402
    CHAT_TRIGGER_SOURCE,
    PHASE_MESSAGE_CREATED,
    STATUS_DELIVERED,
    merge_stored_run_fields,
)
from test_orchestration_harness_routes import modules  # noqa: F401, E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_support.workflow_chat_delivery_fakes import (  # noqa: E402
    CONVERSATION_ID,
    RUN_ID,
    USER,
    FakeContainer,
    cosmos_error,
    make_record,
    make_run,
    make_world,
    require,
    shift,
)


M5 = f"assistant_workflow_delivery_{RUN_ID}_{CONVERSATION_ID}_5"
COSMOS_SYSTEM_FIELDS = ("_rid", "_self", "_etag", "_attachments", "_ts")


@pytest.fixture
def personal_workflows(modules, monkeypatch):
    module = importlib.import_module("functions_personal_workflows")
    logs = []

    def delivery_log(message, **kwargs):
        logs.append({"message": message, **kwargs})

    monkeypatch.setattr(module, "delivery_log", delivery_log)
    return SimpleNamespace(module=module, logs=logs)


def deliver(world, run_id=RUN_ID, user_id=USER):
    return worker.process_workflow_chat_delivery(user_id, run_id, services=world.services)


def sweep(world):
    return worker.run_workflow_chat_delivery_sweep(world.services)


def make_due(world, run_id=RUN_ID):
    world.clock.now = shift(world.record(run_id)["next_attempt_at"], seconds=1)


def user_reads_chat(world):
    conversation = clear_conversation_unread(world.conversation())
    world.conversations.put(conversation)


def install_run_container(monkeypatch, personal_workflows, container):
    monkeypatch.setattr(
        personal_workflows.module,
        "cosmos_personal_workflow_runs_container",
        container,
    )


def save_run(personal_workflows, run_record, user_id=USER):
    return personal_workflows.module.save_personal_workflow_run(user_id, copy.deepcopy(run_record))


def delivery_counts(world):
    calls = world.notifications.chat_calls + world.notifications.notice_calls
    return {
        "messages": len(world.delivery_messages()),
        # Each idempotency key stores one notice, like the real helpers: a repeated call with the
        # same key returns the stored notice instead of ringing the bell again.
        "notices": len(world.notifications.notices()),
        "notice_keys": len({call["idempotency_key"] for call in calls}),
        "unread": len(world.unread_calls),
        "model_requests": len(world.models.requests),
    }


def assert_exactly_once(world, *, model_requests=1, unread=1):
    counts = delivery_counts(world)
    require(counts["messages"] == 1, f"expected one delivery message, got {counts}")
    require(counts["notices"] == 1, f"expected one bell notice, got {counts}")
    require(counts["notice_keys"] == 1, f"every notice call must reuse the generation's key, got {counts}")
    require(counts["unread"] == unread, f"expected {unread} unread mark(s), got {counts}")
    require(counts["model_requests"] == model_requests, f"expected {model_requests} model call(s), got {counts}")


def delivered_world_with_stale_copy():
    world = make_world()
    stale = copy.deepcopy(world.run())
    outcome = deliver(world)
    require(outcome == worker.OUTCOME_DELIVERED, f"initial delivery failed with {outcome}")
    assert_exactly_once(world)
    return world, stale


def reset_model_observations(world):
    world.models.selected.requests.clear()
    world.models.default.requests.clear()
    world.models.calls.clear()


def reverted_pending_copy(stale):
    reverted = copy.deepcopy(stale)
    reverted["status"] = "completed"
    return reverted


def replace_calls(container):
    return container.writes("replace_item")


def upsert_calls(container):
    return container.writes("upsert_item")


def test_version_is_at_least_the_chat_delivery_release():
    assert_app_version_at_least("0.261.227")


def test_guarded_stale_save_preserves_delivery_and_sweep_stays_exactly_once(personal_workflows, monkeypatch):
    world, stale = delivered_world_with_stale_copy()
    install_run_container(monkeypatch, personal_workflows, world.runs)
    delivered = copy.deepcopy(world.record())
    stale["progress"] = {"step": "runner-finished-after-delivery"}
    stale["status"] = "completed_with_progress"
    reset_model_observations(world)

    saved = save_run(personal_workflows, stale)

    stored = world.run()
    require(saved["chat_delivery"] == delivered, "guarded save must return the stored delivered record")
    require(stored["chat_delivery"] == delivered, "guarded save must preserve delivered chat_delivery")
    require(stored["progress"] == {"step": "runner-finished-after-delivery"}, "incoming progress must be applied")
    require(stored["status"] == "completed_with_progress", "incoming non-delivery status must be applied")
    require(len(replace_calls(world.runs)) >= 1, "guarded save must use an ETag replace")
    require(upsert_calls(world.runs) == [], "guarded stale save must not blind upsert when replace succeeds")

    summary = sweep(world)

    require(summary["processed"] == 0, f"delivered record should not sweep again: {summary}")
    assert_exactly_once(world, model_requests=0)


def test_worker_is_idempotent_after_guard_bypassed_stale_upsert_and_hints():
    world, stale = delivered_world_with_stale_copy()
    world.runs.upsert_item(body=reverted_pending_copy(stale))
    reset_model_observations(world)
    world.hints.signal(USER, RUN_ID)

    hint_outcomes = worker.process_workflow_chat_delivery_hints(world.services)
    summary = sweep(world)
    outcome = deliver(world)

    require(hint_outcomes == [(RUN_ID, worker.OUTCOME_DELIVERED)], f"unexpected hint outcomes: {hint_outcomes}")
    require(summary["processed"] == 0, f"sweep should find no extra work after hint: {summary}")
    require(outcome == worker.OUTCOME_NOT_APPLICABLE, f"delivered record should be closed: {outcome}")
    assert_exactly_once(world, model_requests=0)


def test_worker_does_not_mark_unread_again_when_user_read_after_guard_bypass():
    world, stale = delivered_world_with_stale_copy()
    user_reads_chat(world)
    world.runs.upsert_item(body=reverted_pending_copy(stale))
    reset_model_observations(world)
    world.hints.signal(USER, RUN_ID)

    hint_outcomes = worker.process_workflow_chat_delivery_hints(world.services)
    summary = sweep(world)

    require(hint_outcomes == [(RUN_ID, worker.OUTCOME_DELIVERED)], f"unexpected hint outcomes: {hint_outcomes}")
    require(summary["processed"] == 0, f"sweep should not post after check-before-compose: {summary}")
    assert_exactly_once(world, model_requests=0)
    conversation = world.conversation()
    require(conversation["has_unread_assistant_response"] is False, "a read chat must stay read after stale revert")


def test_guard_restores_missing_delivery_and_invocation_on_chat_trigger(personal_workflows, monkeypatch):
    stored = make_run()
    container = FakeContainer("runs", [stored])
    install_run_container(monkeypatch, personal_workflows, container)
    incoming = {
        "id": RUN_ID,
        "user_id": USER,
        "workflow_id": stored["workflow_id"],
        "trigger_source": CHAT_TRIGGER_SOURCE,
        "status": "completed",
        "progress": {"phase": "done"},
    }

    save_run(personal_workflows, incoming)

    saved = container.get(RUN_ID)
    require(saved["chat_delivery"] == stored["chat_delivery"], "stored chat_delivery must be restored")
    require(saved["chat_invocation"] == stored["chat_invocation"], "stored chat_invocation must be restored")
    require(saved["progress"] == {"phase": "done"}, "incoming runner field must be retained")


def test_guard_retries_412_and_keeps_concurrent_delivery(personal_workflows, monkeypatch):
    stored = make_run()
    container = FakeContainer("runs", [stored])
    install_run_container(monkeypatch, personal_workflows, container)
    concurrent_delivery = make_record(
        status=STATUS_DELIVERED,
        generation=7,
        phase=PHASE_MESSAGE_CREATED,
        message_id="assistant_workflow_delivery_concurrent",
    )
    original_replace = container.replace_item
    state = {"failed": False}

    def replace_with_concurrent_delivery(item=None, body=None, etag=None, match_condition=None, **kwargs):
        if not state["failed"]:
            state["failed"] = True
            item_id = item.get("id") if isinstance(item, dict) else item
            container.calls.append(("replace_item", item_id, etag))
            current = container.get(RUN_ID)
            current["chat_delivery"] = copy.deepcopy(concurrent_delivery)
            container.put(current)
            raise cosmos_error(412, "concurrent delivery")
        return original_replace(item=item, body=body, etag=etag, match_condition=match_condition, **kwargs)

    container.replace_item = replace_with_concurrent_delivery
    incoming = copy.deepcopy(stored)
    incoming["progress"] = {"runner": "after-conflict"}
    incoming["chat_delivery"] = make_record(status="pending")

    save_run(personal_workflows, incoming)

    saved = container.get(RUN_ID)
    read_count = sum(1 for call in container.calls if call[0] == "read_item")
    replace_count = sum(1 for call in container.calls if call[0] == "replace_item")
    require(read_count == 2, f"412 must re-read before retrying, calls={container.calls}")
    require(replace_count == 2, f"412 must retry replace, calls={container.calls}")
    require(saved["chat_delivery"] == concurrent_delivery, "concurrent stored chat_delivery must win")
    require(saved["progress"] == {"runner": "after-conflict"}, "incoming runner fields must survive retry")


def test_guarded_replace_uses_read_etag_so_real_conflict_preserves_concurrent_delivery(personal_workflows, monkeypatch):
    """A concurrent write must only be detected by the guarded replace ETag."""

    stored = make_run()
    container = FakeContainer("runs", [stored])
    install_run_container(monkeypatch, personal_workflows, container)
    concurrent_delivery = make_record(
        status=STATUS_DELIVERED,
        generation=9,
        phase=PHASE_MESSAGE_CREATED,
        message_id="assistant_workflow_delivery_etag_concurrent",
    )
    original_read = container.read_item
    original_replace = container.replace_item
    read_etags = []
    state = {"concurrent_write_done": False}

    def read_item_recording_etag(item=None, partition_key=None, **kwargs):
        document = original_read(item=item, partition_key=partition_key, **kwargs)
        read_etags.append((document["id"], document.get("_etag")))
        return document

    def replace_after_concurrent_write(item=None, body=None, etag=None, match_condition=None, **kwargs):
        if not state["concurrent_write_done"]:
            state["concurrent_write_done"] = True
            current = container.get(RUN_ID)
            current["chat_delivery"] = copy.deepcopy(concurrent_delivery)
            container.put(current)
        return original_replace(item=item, body=body, etag=etag, match_condition=match_condition, **kwargs)

    container.read_item = read_item_recording_etag
    container.replace_item = replace_after_concurrent_write
    incoming = copy.deepcopy(stored)
    incoming["progress"] = {"runner": "after-real-etag-conflict"}
    incoming["chat_delivery"] = make_record(status="pending")

    save_run(personal_workflows, incoming)

    saved = container.get(RUN_ID)
    recorded_replace_calls = replace_calls(container)
    require(
        state["concurrent_write_done"] is True,
        f"test hook should perform one concurrent write, state={state!r}",
    )
    require(len(read_etags) == 2, f"guarded save must read before initial replace and retry, read_etags={read_etags!r}")
    require(len(recorded_replace_calls) == 2, f"guarded save must attempt replace twice, calls={container.calls}")
    for call, read_etag in zip(recorded_replace_calls, read_etags):
        _operation, item_id, etag = call
        read_item_id, expected_etag = read_etag
        require(
            item_id == read_item_id and etag == expected_etag,
            f"replace ETag must match immediately preceding read: call={call!r}, read_etag={read_etag!r}",
        )
    require(saved["chat_delivery"] == concurrent_delivery, f"concurrent chat_delivery must win, got {saved.get('chat_delivery')!r}")
    require(saved["progress"] == {"runner": "after-real-etag-conflict"}, f"incoming fields must survive retry, got {saved!r}")


def test_guard_read_404_upserts_run_record_unchanged(personal_workflows, monkeypatch):
    container = FakeContainer("runs")
    install_run_container(monkeypatch, personal_workflows, container)
    incoming = make_run(record=make_record(status="pending"))

    save_run(personal_workflows, incoming)

    saved = container.get(RUN_ID)
    require(saved["chat_delivery"] == incoming["chat_delivery"], "read 404 must upsert incoming delivery unchanged")
    require(len(upsert_calls(container)) == 1, f"read 404 must upsert once, calls={container.calls}")
    require(replace_calls(container) == [], f"read 404 must not replace, calls={container.calls}")


def test_guard_read_failure_logs_and_upserts_current_merge(personal_workflows, monkeypatch):
    incoming = make_run(record=make_record(status="pending"))
    container = FakeContainer("runs", [incoming])
    container.fail("read_item", cosmos_error(503, "read outage"))
    install_run_container(monkeypatch, personal_workflows, container)
    incoming["progress"] = {"runner": "read-failed"}

    save_run(personal_workflows, incoming)

    saved = container.get(RUN_ID)
    reasons = [entry.get("reason") for entry in personal_workflows.logs]
    require("read_failed" in reasons, f"read failure must be logged, logs={personal_workflows.logs}")
    require(saved["chat_delivery"] == incoming["chat_delivery"], "read_failed path upserts the incoming merge as-is")
    require(saved["progress"] == {"runner": "read-failed"}, "read_failed upsert must include incoming fields")
    require(len(upsert_calls(container)) == 1, f"read failure must upsert once, calls={container.calls}")


def test_guard_replace_404_upserts_merged_record(personal_workflows, monkeypatch):
    stored = make_run()
    container = FakeContainer("runs", [stored])
    container.fail("replace_item", cosmos_error(404, "deleted"))
    install_run_container(monkeypatch, personal_workflows, container)
    incoming = copy.deepcopy(stored)
    incoming["chat_delivery"] = make_record(status="pending")
    incoming["progress"] = {"runner": "deleted-before-replace"}

    save_run(personal_workflows, incoming)

    saved = container.get(RUN_ID)
    expected = merge_stored_run_fields(incoming, stored)
    require(saved["chat_delivery"] == expected["chat_delivery"], "replace 404 must upsert merged delivery")
    require(saved["progress"] == expected["progress"], "replace 404 must upsert merged runner fields")
    require(len(replace_calls(container)) == 1, f"replace 404 must attempt one replace, calls={container.calls}")
    require(len(upsert_calls(container)) == 1, f"replace 404 must upsert once, calls={container.calls}")


def test_guard_conflicts_exhausted_logs_and_upserts_merged_record(personal_workflows, monkeypatch):
    stored = make_run()
    container = FakeContainer("runs", [stored])
    container.fail("replace_item", *(cosmos_error(412, "conflict") for _ in range(8)))
    install_run_container(monkeypatch, personal_workflows, container)
    incoming = copy.deepcopy(stored)
    incoming["chat_delivery"] = make_record(status="pending")
    incoming["progress"] = {"runner": "after-eight-conflicts"}

    save_run(personal_workflows, incoming)

    saved = container.get(RUN_ID)
    expected = merge_stored_run_fields(incoming, stored)
    reasons = [entry.get("reason") for entry in personal_workflows.logs]
    require("conflicts_exhausted" in reasons, f"exhausted conflicts must be logged, logs={personal_workflows.logs}")
    require(len(replace_calls(container)) == 8, f"must attempt exactly 8 replaces, calls={container.calls}")
    require(len(upsert_calls(container)) == 1, f"must upsert once after conflicts, calls={container.calls}")
    require(saved["chat_delivery"] == expected["chat_delivery"], "conflict exhaustion must upsert merged delivery")
    require(saved["progress"] == {"runner": "after-eight-conflicts"}, "incoming runner fields must survive conflicts")


def test_guard_non_412_replace_error_propagates_without_upsert(personal_workflows, monkeypatch):
    stored = make_run()
    container = FakeContainer("runs", [stored])
    container.fail("replace_item", cosmos_error(500, "replace broke"))
    install_run_container(monkeypatch, personal_workflows, container)
    incoming = copy.deepcopy(stored)
    incoming["progress"] = {"runner": "will-not-write"}

    with pytest.raises(CosmosHttpResponseError):
        save_run(personal_workflows, incoming)

    require(len(replace_calls(container)) == 1, f"replace should be attempted once, calls={container.calls}")
    require(upsert_calls(container) == [], f"replace 500 must not upsert, calls={container.calls}")
    saved = container.get(RUN_ID)
    require("progress" not in saved, "failed replace must not persist incoming fields")


def test_non_chat_run_uses_plain_upsert_without_read(personal_workflows, monkeypatch):
    container = FakeContainer("runs")
    install_run_container(monkeypatch, personal_workflows, container)
    incoming = {
        "id": "manual-run-1",
        "user_id": USER,
        "workflow_id": "workflow-manual",
        "trigger_source": "manual",
        "status": "completed",
    }

    save_run(personal_workflows, incoming)

    read_count = sum(1 for call in container.calls if call[0] == "read_item")
    require(read_count == 0, f"non-chat save must not read before upsert, calls={container.calls}")
    require(len(upsert_calls(container)) == 1, f"non-chat save must plain upsert once, calls={container.calls}")


def test_incoming_cosmos_system_fields_are_not_written_by_merge(personal_workflows, monkeypatch):
    stored = make_run()
    container = FakeContainer("runs", [stored])
    install_run_container(monkeypatch, personal_workflows, container)
    incoming = copy.deepcopy(stored)
    incoming.update({
        "_rid": "incoming-rid",
        "_self": "incoming-self",
        "_etag": "incoming-etag",
        "_attachments": "incoming-attachments",
        "_ts": 12345,
        "progress": {"runner": "system-fields"},
    })

    save_run(personal_workflows, incoming)

    saved = container.get(RUN_ID)
    for field in COSMOS_SYSTEM_FIELDS:
        value = saved.get(field)
        require(value != incoming[field], f"incoming {field} must not be written back as-is")
    require(saved["progress"] == {"runner": "system-fields"}, "ordinary incoming fields must still be written")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
