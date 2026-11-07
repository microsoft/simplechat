# test_orchestration_recovery_safety.py
"""Regression coverage for current orchestration recovery safety properties.

Version: 0.261.139
Implemented in: 0.261.105
Ported to Gather / Reason / Render in: 0.261.139
These tests cover retry idempotence, external-effect confirmation, fencing,
checkpoint integrity, publication ambiguity, and cancellation safety.
"""

import json
import threading
from datetime import timedelta
from unittest.mock import patch

from azure.core.exceptions import AzureError
import pytest

from test_support.orchestration_recovery import RecoveryFixture, frames
from test_support.versioning import assert_app_version_at_least


def _retry_children(fixture):
    return [row for row in fixture.runs.items.values() if row.get("retry_of_run_id")]


def _crash_retry(fixture, child, phase):
    namespace = fixture.route.prepare_retry.__globals__
    manager_type = namespace["ExecutionCheckpoints"]
    original_initialize = manager_type.initialize
    original_save = manager_type.save_step

    def crash(manager):
        manager.lease.close()
        fixture.runs.items[(fixture.conversation_id, child["run_id"])]["execution_lease"]["expires_at"] = (
            namespace["_now"]() - timedelta(seconds=2)
        ).isoformat()
        raise namespace["CheckpointError"]("ownership_lost")

    def initialize(manager):
        if phase == "before_initialize":
            crash(manager)
        original_initialize(manager)
        if phase == "after_initialize":
            crash(manager)

    def save(manager, record):
        original_save(manager, record)
        if phase == "after_first_copy" and record["step_id"] == "a":
            crash(manager)

    with patch.object(manager_type, "initialize", initialize), patch.object(manager_type, "save_step", save):
        frames(fixture.run_attempt(child["plan"]))


def test_application_version():
    assert_app_version_at_least("0.261.139")


def test_retry_is_idempotent_and_old_attempt_cannot_branch():
    with RecoveryFixture() as fixture:
        plan = fixture.plan_attempt()
        fixture.run_attempt(plan)

        first = fixture.retry(plan["run_id"])
        assert first.status_code == 200, first.get_data(as_text=True)
        again = fixture.retry(plan["run_id"])
        assert again.status_code == 200, again.get_data(as_text=True)
        assert first.get_json()["run"]["run_id"] == again.get_json()["run"]["run_id"]

        changed = fixture.retry(plan["run_id"], confirm_external_effects=False)
        assert changed.status_code == 409
        assert changed.get_json()["code"] == "recovery_changed"

        competing = fixture.retry(plan["run_id"], submission_id="another-tab")
        assert competing.status_code == 409
        assert competing.get_json()["code"] == "recovery_changed"
        assert len(_retry_children(fixture)) == 1
        assert fixture.calls == ["a", "b"]


def test_two_tabs_racing_publish_only_one_successor():
    with RecoveryFixture() as fixture:
        plan = fixture.plan_attempt()
        fixture.run_attempt(plan)
        competitor = []
        fixture.runs.before_batch = lambda: competitor.append(
            fixture.retry(plan["run_id"], submission_id="tab-two"),
        )

        response = fixture.retry(plan["run_id"], submission_id="tab-one")

        assert competitor[0].status_code == 200, competitor[0].get_data(as_text=True)
        assert response.status_code == 409
        assert response.get_json()["code"] == "recovery_changed"
        assert len(_retry_children(fixture)) == 1


def test_lost_publication_response_returns_the_committed_attempt():
    with RecoveryFixture() as fixture:
        plan = fixture.plan_attempt()
        fixture.run_attempt(plan)

        def lose_response():
            raise AzureError("private lost reply")

        fixture.runs.after_batch = lose_response
        response = fixture.retry(plan["run_id"])

        assert response.status_code == 200, response.get_data(as_text=True)
        assert response.get_json()["run"]["attempt_index"] == 2
        assert len(_retry_children(fixture)) == 1


def test_failed_agent_step_requires_confirmation_and_keeps_completed_work():
    with RecoveryFixture() as fixture:
        plan = fixture.plan_attempt()
        events = frames(fixture.run_attempt(plan))
        done = next(event for event in events if event.get("type") == "orchestration_done")
        assert done["status"] == "failed"
        assert done["recovery"]["eligible"] is True
        assert done["recovery"]["requires_confirmation"] is True
        assert done["recovery"]["reused_step_ids"] == ["a"]

        denied = fixture.retry(plan["run_id"], confirm_external_effects=False)
        assert denied.status_code == 409
        assert denied.get_json()["code"] == "confirmation_required"
        assert len(_retry_children(fixture)) == 0

        response = fixture.retry(plan["run_id"], submission_id="confirmed-retry")
        assert response.status_code == 200, response.get_data(as_text=True)
        child = response.get_json()["run"]
        assert child["recovery"]["reused_step_ids"] == ["a"]
        fixture.fail_b = False
        fixture.run_attempt(child["plan"])
        assert fixture.calls == ["a", "b", "b", "c"]


def test_committed_producer_with_a_lost_checkpoint_is_recovered_from_its_receipt_not_rerun():
    # The agent's result was committed but its checkpoint write failed. The attempt is not
    # offered as retryable until a confirmed retry proves the committed receipt, and the
    # recovered attempt reuses that exact result instead of running the agent again.
    with RecoveryFixture() as fixture:
        fixture.fail_b = False
        plan = fixture.plan_attempt()

        def fail_commit(step, context, kwargs):
            if step["step_id"] == "b":
                fixture.steps.fail_writes = True

        fixture.before_adapter = fail_commit
        events = frames(fixture.run_attempt(plan))
        done = next(event for event in events if event.get("type") == "orchestration_done")
        assert done["status"] == "failed"
        assert done["recovery"]["eligible"] is False
        assert done["recovery"]["reason_code"] == "result_commit_unconfirmed"

        fixture.steps.fail_writes = False
        fixture.before_adapter = None
        unconfirmed = fixture.retry(plan["run_id"], confirm_external_effects=False, submission_id="retry-unconfirmed")
        assert unconfirmed.status_code == 409
        assert unconfirmed.get_json()["code"] == "confirmation_required"
        assert len(_retry_children(fixture)) == 0

        confirmed = fixture.retry(plan["run_id"], submission_id="retry-confirmed")
        assert confirmed.status_code == 200, confirmed.get_data(as_text=True)
        child = confirmed.get_json()["run"]
        assert child["recovery"]["reused_step_ids"] == ["a", "b"]
        assert child["recovery"]["retry_step_ids"] == ["c", "answer"]
        child_events = frames(fixture.run_attempt(child["plan"]))
        child_done = next(event for event in child_events if event.get("type") == "orchestration_done")
        assert child_done["status"] == "completed"
        assert fixture.calls == ["a", "b", "c"]


def test_inherited_success_does_not_waive_confirmation_for_new_failed_effects():
    with RecoveryFixture() as fixture:
        plan = fixture.plan_attempt()
        fixture.run_attempt(plan)
        child = fixture.retry(plan["run_id"]).get_json()["run"]
        fixture.run_attempt(child["plan"])

        detail = fixture.detail(child["run_id"])
        assert detail["recovery"]["reused_step_ids"] == ["a"]
        assert detail["recovery"]["requires_confirmation"] is True

        denied = fixture.retry(child["run_id"], confirm_external_effects=False)
        assert denied.status_code == 409
        assert denied.get_json()["code"] == "confirmation_required"
        assert len(_retry_children(fixture)) == 1
        assert fixture.calls == ["a", "b", "b"]


def _expire_lease(fixture, plan):
    namespace = fixture.route.prepare_retry.__globals__
    fixture.runs.items[(fixture.conversation_id, plan["run_id"])]["execution_lease"]["expires_at"] = (
        namespace["_now"]() - timedelta(seconds=2)
    ).isoformat()


def _published_for(fixture, run_id):
    return [
        row for row in fixture.messages.items.values()
        if (row.get("metadata") or {}).get("orchestration", {}).get("run_id") == run_id
    ]


def _assert_fenced_worker_saved_nothing(fixture, plan, events):
    done = [event for event in events if event.get("type") == "orchestration_done"]
    assert len(done) == 1
    assert done[0]["message_saved"] is False
    assert done[0]["finalization_status"] == "failed"
    assert done[0]["full_content"] == ""
    assert done[0]["failure"]["code"] == "message_not_saved"
    assert not _published_for(fixture, plan["run_id"])
    assert not fixture.runs.items[(fixture.conversation_id, plan["run_id"])].get("assistant_message_id")


def test_retry_cannot_be_claimed_while_a_producer_completion_is_unconfirmed():
    with RecoveryFixture() as fixture:
        plan = fixture.plan_attempt()
        prepared = []

        def expire_and_retry(step, context, kwargs):
            if step["step_id"] == "b":
                _expire_lease(fixture, plan)
                prepared.append(fixture.retry(plan["run_id"]))

        fixture.before_adapter = expire_and_retry
        events = frames(fixture.run_attempt(plan))

        body = prepared[0].get_json()
        assert prepared[0].status_code == 409
        assert body["recovery"]["reason_code"] == "result_commit_unconfirmed"
        _assert_fenced_worker_saved_nothing(fixture, plan, events)

        # The worker is gone and no completion was committed, so the producer is never retried.
        later = fixture.retry(plan["run_id"], submission_id="retry-after-worker-loss")
        assert later.status_code == 409
        assert later.get_json()["recovery"]["reason_code"] == "result_commit_unconfirmed"
        assert len(_retry_children(fixture)) == 0
        assert fixture.calls == ["a", "b"]


def test_expired_worker_cannot_publish_after_retry_claim():
    with RecoveryFixture() as fixture:
        plan = fixture.plan_attempt()
        manager_type = fixture.route.prepare_retry.__globals__["ExecutionCheckpoints"]
        original_save = manager_type.save_step
        prepared = []

        def save(manager, record):
            original_save(manager, record)
            if record["step_id"] == "b" and record.get("status") == "failed" and not prepared:
                _expire_lease(fixture, plan)
                prepared.append(fixture.retry(plan["run_id"]))

        with patch.object(manager_type, "save_step", save):
            events = frames(fixture.run_attempt(plan))

        assert prepared[0].status_code == 200, prepared[0].get_data(as_text=True)
        child = prepared[0].get_json()["run"]
        assert fixture.runs.items[(fixture.conversation_id, plan["run_id"])]["latest_attempt_run_id"] == child["run_id"]
        assert [row["run_id"] for row in _retry_children(fixture)] == [child["run_id"]]
        _assert_fenced_worker_saved_nothing(fixture, plan, events)
        assert fixture.calls == ["a", "b"]


def test_message_publication_batch_rejects_a_worker_fenced_after_its_last_read():
    with RecoveryFixture() as fixture:
        plan = fixture.plan_attempt()
        recovery = fixture.route.prepare_retry.__globals__
        children = []

        def fence_before_publish():
            fixture.runs.items[(fixture.conversation_id, plan["run_id"])]["execution_lease"]["expires_at"] = (
                recovery["_now"]() - timedelta(seconds=1)
            ).isoformat()
            children.append(fixture.retry(plan["run_id"]))

        fixture.messages.before_batch = fence_before_publish
        events = frames(fixture.run_attempt(plan))

        assert children[0].status_code == 200, children[0].get_data(as_text=True)
        child = children[0].get_json()["run"]
        assert fixture.runs.items[(fixture.conversation_id, plan["run_id"])]["latest_attempt_run_id"] == child["run_id"]
        _assert_fenced_worker_saved_nothing(fixture, plan, events)


def test_heartbeat_runs_during_blocked_adapter_and_preserves_concurrent_stop():
    with RecoveryFixture() as fixture:
        plan = fixture.plan_attempt()
        recovery = fixture.route.prepare_retry.__globals__
        observed = []

        def block_and_stop(step, context, kwargs):
            if step["step_id"] != "a":
                return
            before = fixture.runs.read_item(plan["run_id"], fixture.conversation_id)["execution_lease"]["heartbeat_at"]
            threading.Event().wait(0.06)
            current = fixture.runs.read_item(plan["run_id"], fixture.conversation_id)
            observed.append(current["execution_lease"]["heartbeat_at"] != before)
            lease = fixture.route.ExecutionLease(current, lambda: True)
            fixture.runs.before_replace = lambda: recovery["request_cancellation"](
                plan["run_id"], fixture.user_id, fixture.conversation_id, lambda: True,
            )
            lease.renew()
            observed.append(lease.cancel_requested())

        fixture.before_adapter = block_and_stop
        with patch.dict(recovery, {"HEARTBEAT_SECONDS": 0.01}):
            events = frames(fixture.run_attempt(plan))

        assert observed == [True, True]
        done = next(event for event in events if event.get("type") == "orchestration_done")
        assert done["status"] == "cancelled"


@pytest.mark.parametrize(
    "damage",
    [
        "missing_run", "deleted", "deleted_checkpoint", "missing_manifest",
        "owner", "turn", "plan", "binding", "digest", "missing_reference",
    ],
)
def test_invalid_inherited_checkpoints_block_without_repeating_effects(damage):
    with RecoveryFixture() as fixture:
        fixture.fail_b = False
        fixture.model.answer_error = RuntimeError("answer failed")
        plan = fixture.plan_attempt()
        fixture.run_attempt(plan)
        child = fixture.retry(plan["run_id"], confirm_external_effects=False).get_json()["run"]
        _crash_retry(fixture, child, "after_first_copy")
        original = fixture.runs.items[(fixture.conversation_id, plan["run_id"])]
        interrupted = fixture.runs.items[(fixture.conversation_id, child["run_id"])]

        if damage == "missing_run":
            del fixture.runs.items[(fixture.conversation_id, plan["run_id"])]
        elif damage == "deleted":
            original["checkpoints_deleted"] = True
        elif damage == "deleted_checkpoint":
            fixture.steps.items[(plan["run_id"], "checkpoint:lifecycle")]["deleted"] = True
        elif damage == "missing_manifest":
            key = next(
                key for key, row in fixture.steps.items.items()
                if key[0] == plan["run_id"] and row.get("step_id") == "b"
                and row.get("record_type") == "checkpoint_manifest"
            )
            del fixture.steps.items[key]
        elif damage == "owner":
            original["user_id"] = "other-user"
        elif damage == "turn":
            original["turn_id"] = "other-turn"
        elif damage == "plan":
            original["plan"]["steps"][1]["arguments"]["task"] = "Different external action"
        elif damage == "binding":
            original["execution_binding"] = "different-binding"
        elif damage == "digest":
            interrupted["inherited_checkpoints"]["b"]["payload_digest"] = "different-digest"
        else:
            interrupted["inherited_checkpoints"].pop("b")

        response = fixture.client.post(f"/api/v2/orchestration/runs/{child['run_id']}/retry", json={
            "conversation_id": fixture.conversation_id,
            "submission_id": "damaged-retry",
            "expected_version": interrupted["recovery_version"],
            "confirm_external_effects": False,
        })

        assert response.status_code in (404, 409, 503), response.get_data(as_text=True)
        assert fixture.calls == ["a", "b", "c"]
        assert not interrupted.get("latest_attempt_run_id")
        detail = fixture.client.get(
            f"/api/v2/orchestration/runs/{child['run_id']}?conversation_id={fixture.conversation_id}",
        )
        assert detail.status_code == 503
        assert detail.get_json()["code"] == "recovery_unavailable"


def test_json_byte_bounds_immutability_integrity_and_authorization():
    with RecoveryFixture() as fixture:
        recovery = fixture.route.prepare_retry.__globals__
        checkpoint_type = recovery["CheckpointStore"]
        error_type = recovery["CheckpointError"]
        namespace = checkpoint_type.commit.__globals__
        authorized = [True]
        store = checkpoint_type(
            fixture.steps, run_id="codec-run", user_id=fixture.user_id, conversation_id=fixture.conversation_id,
            turn_id="codec-turn", token="codec-token", authorize=lambda: authorized[0],
        )
        store.initialize()
        context = fixture.route.RunContext(
            run_id="codec-run", user_id=fixture.user_id, conversation_id=fixture.conversation_id,
        )
        context.pending_results = {"big": "漢字🙂" * 300000}
        step = {"step_id": "a"}
        result = recovery["build_step_result"](notes=["large checkpoint payload"])
        payload = store.commit(step, result, context, input_fingerprint="input", binding="binding")

        loaded = store.load("a")
        assert loaded == payload
        chunks = [row for row in fixture.steps.items.values() if row.get("record_type") == "checkpoint_chunk"]
        assert len(chunks) > 1
        assert all(len(namespace["json_bytes"](row)) < namespace["MAX_DOCUMENT_BYTES"] for row in fixture.steps.items.values())
        with pytest.raises(error_type), patch.dict(namespace, {"MAX_CHECKPOINT_BYTES": 100}):
            store.commit({"step_id": "large"}, result, context, input_fingerprint="input", binding="binding")
        bad = next(row for row in fixture.steps.items.values() if row.get("record_type") == "checkpoint_chunk")
        bad["data"] = "broken"
        with pytest.raises(error_type):
            store.load("a")
        authorized[0] = False
        with pytest.raises(error_type):
            store.load("a")
        for value in (float("nan"), object(), {1: "non-string key"}):
            with pytest.raises(error_type):
                namespace["json_bytes"](value)
        conflict_store = checkpoint_type(
            fixture.steps, run_id="conflict-run", user_id=fixture.user_id, conversation_id=fixture.conversation_id,
            turn_id="codec-turn", token="conflict-token", authorize=lambda: True,
        )
        conflict_store.initialize()
        saved = conflict_store.commit(step, result, context, input_fingerprint="input", binding="binding")
        # A step's message is not retained, so this replay is byte-identical and idempotent.
        replayed = conflict_store.commit(
            step, {**result, "message": "different"}, context,
            input_fingerprint="input", binding="binding",
        )
        assert replayed == saved
        with pytest.raises(error_type):
            conflict_store.commit(step, result, context, input_fingerprint="different-input", binding="binding")
        kept = conflict_store.load("a")
        assert kept == saved


@pytest.mark.parametrize(
    "damage",
    [
        "no_commit", "missing_message", "missing_guard", "read_failure", "content", "citations",
        "metadata", "guard_token", "guard_owner", "guard_run", "guard_digest", "deleted_run", "expired_run",
    ],
)
def test_ambiguous_publication_rejects_missing_or_different_durable_documents(damage):
    with RecoveryFixture() as fixture:
        plan = fixture.plan_attempt()
        namespace = fixture.route.prepare_retry.__globals__

        def damage_commit():
            guard = fixture.messages.items[(fixture.conversation_id, namespace["_publication_id"](plan["run_id"]))]
            key = (fixture.conversation_id, guard["published_message_id"])
            if damage == "missing_message":
                del fixture.messages.items[key]
            elif damage == "missing_guard":
                del fixture.messages.items[(fixture.conversation_id, guard["id"])]
            elif damage == "read_failure":
                fixture.messages.fail_reads = True
            elif damage == "content":
                fixture.messages.items[key]["content"] = "Different saved content"
            elif damage == "citations":
                fixture.messages.items[key]["hybrid_citations"] = [{"document_id": "different-document"}]
            elif damage == "metadata":
                fixture.messages.items[key]["metadata"]["orchestration"]["run_id"] = "other-run"
            elif damage == "guard_token":
                guard["token"] = "different-worker"
            elif damage == "guard_owner":
                guard["user_id"] = "other-user"
            elif damage == "guard_run":
                guard["run_id"] = "other-run"
            elif damage == "guard_digest":
                guard["document_digest"] = "different-digest"
            elif damage == "deleted_run":
                fixture.runs.items[(fixture.conversation_id, plan["run_id"])]["checkpoints_deleted"] = True
            elif damage == "expired_run":
                fixture.runs.items[(fixture.conversation_id, plan["run_id"])]["execution_lease"]["expires_at"] = (
                    "2020-01-01T00:00:00Z"
                )
            raise AzureError("private ambiguous publication")

        if damage == "no_commit":
            fixture.messages.before_batch = lambda: setattr(fixture.messages, "fail_writes", True)
        else:
            fixture.messages.after_batch = damage_commit
        events = frames(fixture.run_attempt(plan))
        done = [event for event in events if event.get("type") == "orchestration_done"]
        stored = fixture.runs.items[(fixture.conversation_id, plan["run_id"])]

        assert not any(event.get("message_saved") for event in done)
        assert not stored.get("assistant_message_id")
        if damage not in ("deleted_run", "expired_run"):
            assert done[0]["finalization_status"] == "failed"
            detail = fixture.detail(plan["run_id"])
            assert detail["recovery"]["eligible"] is False
        assert "private ambiguous publication" not in json.dumps(events)


def _fence_calls(fixture, plan):
    return [
        (fixture.user_id, fixture.conversation_id, plan["run_id"], step_id)
        for step_id in ("a", "b", "c", "answer")
    ]


@pytest.mark.parametrize("capability", ["document_search", "document_analyze", "tabular_analyze"])
def test_stop_fences_every_retained_producer_step_before_acknowledgement(capability):
    # Every Gather / Reason / Render step retains producer results, so a stop fences each
    # planned step, whatever its capability, before the cancellation is acknowledged.
    with RecoveryFixture() as fixture:
        plan = fixture.plan_attempt()
        fixture.runs.items[(fixture.conversation_id, plan["run_id"])]["plan"]["steps"][0]["capability_id"] = capability
        recovery = fixture.route.prepare_retry.__globals__
        calls = []

        stopped = recovery["request_cancellation"](
            plan["run_id"], fixture.user_id, fixture.conversation_id, lambda: True,
            analysis_cancel=lambda *args: calls.append(args),
        )

        assert calls == _fence_calls(fixture, plan)
        assert stopped["cancellation_requested_by"] == fixture.user_id
        assert stopped["cancellation_requested_at"]


def test_stop_does_not_claim_confirmation_when_fencing_fails():
    with RecoveryFixture() as fixture:
        plan = fixture.plan_attempt()
        recovery = fixture.route.prepare_retry.__globals__

        def unavailable(*args):
            raise AzureError("Private unavailable write fence")

        with pytest.raises(recovery["RecoveryError"]) as failure:
            recovery["request_cancellation"](
                plan["run_id"], fixture.user_id, fixture.conversation_id, lambda: True,
                analysis_cancel=unavailable,
            )
        assert failure.value.status_code == 503
        assert "Private unavailable" not in failure.value.message

        calls = []
        recovery["request_cancellation"](
            plan["run_id"], fixture.user_id, fixture.conversation_id, lambda: True,
            analysis_cancel=lambda *args: calls.append(args),
        )
        assert calls == _fence_calls(fixture, plan)
