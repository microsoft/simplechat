# test_orchestration_deletion_enrollment.py
"""Exercise checkpoint deletion and canonical output enrollment together.

Version: 0.261.129
Implemented in: 0.261.127
Default initialized cleanup coverage added in: 0.261.129

Real checkpoint/output stores, initialized cleanup composition and scheduler
replay use deterministic storage I/O. The native source-cleanup callback is an
explicit observation/failure boundary; no producer or model runs during cleanup.
"""

import importlib
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from functions_generated_export_contracts import GeneratedFileExportRequest
from functions_orchestration_output_store import OutputError, OutputStorageError, OutputUnavailableError
from test_orchestration_cleanup_bootstrap import cleanup_root  # noqa: F401
from test_orchestration_output_cleanup import (
    cleanup_lifecycle, interrupted_output, production_modules,  # noqa: F401
)
from test_orchestration_output_deletion_pipeline import (
    advance_cleanup_grace, cleanup_tick, deletion_runtime,  # noqa: F401
)
from test_orchestration_output_lifecycle import Crash


@pytest.fixture
def deletion_api(deletion_runtime):
    runtime = deletion_runtime
    # Recovery imports initialized app owners, so load it inside the offline fixture.
    recovery = importlib.import_module("functions_orchestration_recovery")
    source_cleanup, source_fence = Mock(), Mock()

    def enroll(run_id):
        service = runtime.root.build_orchestration_cleanup_service("owner", "conversation-1")
        return service.enroll_run_cleanup(run_id)

    def cleanup(**overrides):
        options = {
            "message_container": runtime.world.messages,
            "conversation_container": runtime.world.conversations,
            "analysis_cleanup": source_cleanup,
            "analysis_fence": source_fence,
        }
        options.update(overrides)
        return recovery.cleanup_conversation_checkpoints(
            "conversation-1", "owner",
            lambda: runtime.routes._authorize_personal_conversation_read("owner", "conversation-1"),
            **options,
        )

    return SimpleNamespace(
        runtime=runtime, world=runtime.world, recovery=recovery, cleanup=cleanup,
        enroll=enroll, source_cleanup=source_cleanup, source_fence=source_fence,
    )


def second_run_output(world):
    run = deepcopy(world.runs.read_item("run-1", "conversation-1"))
    run = {key: value for key, value in run.items() if not key.startswith("_")}
    run.update(id="run-2", turn_id="turn-2", render_output_ids=[])
    run["plan"].update(
        run_id="run-2", turn_id="turn-2",
        steps=[{"step_id": "second_file", "enabled": True, "capability_id": "render_file", "role": "render"}],
    )
    world.runs.create_item(run)
    producer = replace(
        world.results.producer, run_id="run-2", step_id="second_file",
        capability_id="render_file", contract_version="render-file-v1",
    )
    output = world.service.ensure_output(
        producer=producer, source_ref=world.saved.output("findings"),
        export_request=GeneratedFileExportRequest("json", "exact_records_v1"),
        file_name="second.json", approved_work_id="run-2", deadline_at=world.deadline.isoformat(),
    )
    return world.run(output)


@pytest.mark.parametrize("state", ["completed", "blob", "message"])
@pytest.mark.parametrize("retain_committed", [False, True])
def test_cleanup_fences_and_enrolls_before_any_payload_sweep(
    deletion_api, monkeypatch, state, retain_committed,
):
    api, world = deletion_api, deletion_api.world
    output = world.run(world.prepare()) if state == "completed" else interrupted_output(world, state)
    before = world.raw(output)
    replace_run = world.runs.replace_item
    parent_writes = []

    def observe_parent_write(*, item, body, **kwargs):
        if body.get("checkpoints_deleted"):
            guard = world.cleanup_guards.read_item("checkpoint:lifecycle", item)
            assert guard["deleted"] is True and guard["token"] is None
            assert body["output_cleanup"] == {
                "version": 1, "state": "pending", "retain_committed": retain_committed,
                "output_ids": [output["output_id"]],
            }
            parent_writes.append(item)
        return replace_run(item=item, body=body, **kwargs)

    def observe_source_cleanup(*args):
        parent = world.runs.read_item("run-1", "conversation-1")
        saved = world.runs.read_item(output["output_id"], "conversation-1")
        assert parent["output_cleanup"]["state"] == "completed"
        assert saved["state"] == ("completed" if retain_committed and state == "completed" else "cancelled")
        assert world.blobs.deletes == 0

    monkeypatch.setattr(world.runs, "replace_item", observe_parent_write)
    api.source_cleanup.side_effect = observe_source_cleanup
    result = api.cleanup(retain_committed=retain_committed)
    after = world.runs.read_item(output["output_id"], "conversation-1")
    guard = world.cleanup_guards.read_item("checkpoint:lifecycle", "run-1")
    assert result is None and parent_writes == ["run-1"]
    assert guard["deleted"] is True and guard["token"] is None
    assert api.source_cleanup.call_count == 1
    assert after["attempt_count"] == before["attempt_count"]
    assert after["automatic_attempts"] == before["automatic_attempts"]
    assert after["committed_intent"] == before["committed_intent"]
    assert world.blobs.deletes == 0 and world.blobs.data
    if retain_committed and state == "completed":
        assert after == before
    else:
        assert after["state"] == "cancelled" and after["deleted_at"] and after["cleanup_pending"]


@pytest.mark.parametrize("explicit_none", [False, True])
def test_default_cleanup_uses_one_initialized_service_after_all_run_fences(
    deletion_api, monkeypatch, explicit_none,
):
    api, world = deletion_api, deletion_api.world
    outputs = [world.run(world.prepare()), second_run_output(world)]
    before = [world.raw(output) for output in outputs]
    real_factory = api.runtime.root.build_orchestration_cleanup_service

    def initialize(user_id, conversation_id):
        for run_id in ("run-1", "run-2"):
            parent = world.runs.read_item(run_id, "conversation-1")
            guard = world.cleanup_guards.read_item("checkpoint:lifecycle", run_id)
            assert parent["checkpoints_deleted"] is True
            assert parent["output_cleanup"]["state"] == "pending"
            assert guard["deleted"] is True and guard["token"] is None
        return real_factory(user_id, conversation_id)

    factory = Mock(side_effect=initialize)
    no_blob_io = Mock(side_effect=AssertionError("Deletion enrollment must not access Blob storage."))
    monkeypatch.setattr(api.runtime.root, "build_orchestration_cleanup_service", factory)
    monkeypatch.setattr(world.blobs, "get_blob_client", no_blob_io)
    options = {"output_cleanup": None} if explicit_none else {}
    result = api.cleanup(**options)
    parents = [world.runs.read_item(run_id, "conversation-1") for run_id in ("run-1", "run-2")]
    saved = [world.runs.read_item(output["output_id"], "conversation-1") for output in outputs]
    factory.assert_called_once_with("owner", "conversation-1")
    assert result is None and no_blob_io.call_count == 0
    assert api.source_cleanup.call_count == 2
    assert all(parent["output_cleanup"]["state"] == "completed" for parent in parents)
    for original, current in zip(before, saved):
        assert original["state"] == "completed" and original["cleanup_pending"] is False
        assert current["state"] == "cancelled" and current["deleted_at"] and current["cleanup_pending"]
        assert current["committed_intent"] == original["committed_intent"]
        assert current["attempt_count"] == original["attempt_count"]


def test_default_cleanup_initialization_failure_keeps_durable_intent_for_retry(deletion_api, monkeypatch):
    api, world = deletion_api, deletion_api.world
    output = world.run(world.prepare())
    before = world.raw(output)
    with monkeypatch.context() as unavailable:
        unavailable.setitem(api.runtime.root.config.CLIENTS, "storage_account_office_docs_client", None)
        with pytest.raises(OutputError) as raised:
            api.cleanup()
    parent = world.runs.read_item("run-1", "conversation-1")
    guard = world.cleanup_guards.read_item("checkpoint:lifecycle", "run-1")
    saved = world.runs.read_item(output["output_id"], "conversation-1")
    assert raised.value.code == "output_cleanup_service_required"
    assert parent["checkpoints_deleted"] is True and parent["output_cleanup"]["state"] == "pending"
    assert guard["deleted"] is True and guard["token"] is None
    assert saved == before and api.source_cleanup.call_count == api.source_fence.call_count == 0
    assert world.blobs.deletes == 0

    result = api.cleanup()
    parent = world.runs.read_item("run-1", "conversation-1")
    saved = world.runs.read_item(output["output_id"], "conversation-1")
    assert result is None and parent["output_cleanup"]["state"] == "completed"
    assert saved["state"] == "cancelled" and saved["cleanup_pending"]
    assert saved["committed_intent"] == before["committed_intent"]
    assert api.source_cleanup.call_count == 1 and world.blobs.deletes == 0


@pytest.mark.parametrize("version", [1, 2])
def test_empty_admissions_do_not_initialize_output_cleanup(deletion_api, monkeypatch, version):
    api, world = deletion_api, deletion_api.world
    run = world.runs.read_item("run-1", "conversation-1")
    run["plan"]["planner_contract_version"] = version
    world.runs.upsert_item(run)
    forbidden = Mock(side_effect=AssertionError("Empty/legacy cleanup initialized output storage."))
    monkeypatch.setattr(api.runtime.root, "build_orchestration_cleanup_service", forbidden)
    result = api.cleanup()
    saved = world.runs.read_item("run-1", "conversation-1")
    assert result is None and forbidden.call_count == 0
    assert saved["checkpoints_deleted"] is True
    if version == 2:
        assert saved["output_cleanup"] == {
            "version": 1, "state": "completed", "retain_committed": False, "output_ids": [],
        }
    else:
        assert "output_cleanup" not in saved


@pytest.mark.parametrize("dependency", [False, True, {}, "uninitialized-cleanup"])
def test_noncallable_cleanup_override_is_rejected(deletion_api, dependency):
    api, world = deletion_api, deletion_api.world
    output = world.run(world.prepare())
    with pytest.raises(api.recovery.RecoveryError) as raised:
        api.cleanup(output_cleanup=dependency)
    saved = world.runs.read_item(output["output_id"], "conversation-1")
    assert raised.value.code == "output_cleanup_required"
    assert saved["state"] == "completed" and not saved["deleted_at"]
    assert api.source_cleanup.call_count == api.source_fence.call_count == 0
    assert world.blobs.deletes == 0


@pytest.mark.parametrize("fault", ["malformed", "missing", "foreign_run"])
def test_default_cleanup_rejects_invalid_admission_proof_before_payload_sweep(
    deletion_api, monkeypatch, fault,
):
    api, world = deletion_api, deletion_api.world
    output = world.run(world.prepare())
    surviving = [output]
    run = world.runs.read_item("run-1", "conversation-1")
    if fault == "malformed":
        run["render_output_ids"] = ["not-an-output-id"]
    elif fault == "missing":
        current = world.raw(output)
        world.runs.delete_item(output["output_id"], "conversation-1", etag=current["_etag"])
        surviving = []
    else:
        foreign = second_run_output(world)
        surviving.append(foreign)
        run["render_output_ids"] = [foreign["output_id"]]
    world.runs.upsert_item(run)
    before = [world.raw(item) for item in surviving]
    no_blob_io = Mock(side_effect=AssertionError("Invalid deletion proof must not reach Blob storage."))
    monkeypatch.setattr(world.blobs, "get_blob_client", no_blob_io)

    with pytest.raises((OutputError, OutputUnavailableError)):
        api.cleanup()
    conversation = world.conversations.read_item("conversation-1", "conversation-1")
    after = [world.runs.read_item(item["output_id"], "conversation-1") for item in surviving]
    assert conversation["orchestration_deleted"] is True
    assert after == before
    assert api.source_cleanup.call_count == api.source_fence.call_count == 0
    assert no_blob_io.call_count == 0 and world.blobs.data


@pytest.mark.parametrize("reply", [None, False, "unpersisted"])
def test_enrollment_must_be_confirmed_by_its_actual_persisted_intent(deletion_api, reply):
    api, world = deletion_api, deletion_api.world
    output = world.run(world.prepare())

    def incomplete(run_id):
        if reply == "unpersisted":
            return {
                "run_id": run_id, "enrollment_status": "completed",
                "output_count": 1, "retain_committed": False,
            }
        return reply

    with pytest.raises(api.recovery.RecoveryError) as raised:
        api.cleanup(output_cleanup=incomplete)
    parent = world.runs.read_item("run-1", "conversation-1")
    saved = world.runs.read_item(output["output_id"], "conversation-1")
    assert raised.value.code == "output_cleanup_unconfirmed"
    assert parent["output_cleanup"]["state"] == "pending"
    assert saved["state"] == "completed" and not saved["cleanup_pending"]
    assert api.source_cleanup.call_count == api.source_fence.call_count == 0


@pytest.mark.parametrize("version", [None, 0, True])
def test_admitted_outputs_cannot_invent_missing_checkpoint_version_proof(deletion_api, version):
    api, world = deletion_api, deletion_api.world
    world.run(world.prepare())
    run = world.runs.read_item("run-1", "conversation-1")
    run["checkpoint_version"] = version
    world.runs.upsert_item(run)
    with pytest.raises(api.recovery.CheckpointError) as raised:
        api.cleanup()
    assert raised.value.code == "checkpoint_invalid"
    assert api.source_cleanup.call_count == 0 and not world.cleanup_guards.items


def test_legacy_plan_cannot_silently_ignore_an_existing_retained_output_index(deletion_api):
    api, world = deletion_api, deletion_api.world
    output = world.run(world.prepare())
    run = world.runs.read_item("run-1", "conversation-1")
    run["plan"]["planner_contract_version"] = 1
    world.runs.upsert_item(run)
    with pytest.raises(api.recovery.CheckpointError) as raised:
        api.cleanup()
    saved = world.runs.read_item(output["output_id"], "conversation-1")
    assert raised.value.code == "checkpoint_invalid"
    assert saved["state"] == "completed" and not saved["deleted_at"]
    assert api.source_cleanup.call_count == api.source_fence.call_count == 0
    assert not world.cleanup_guards.items and world.blobs.deletes == 0


def test_authority_is_rechecked_after_enrollment_before_source_cleanup(deletion_api):
    api, world = deletion_api, deletion_api.world
    world.run(world.prepare())

    def enroll_then_revoke(run_id):
        result = api.enroll(run_id)
        conversation = world.conversations.read_item("conversation-1", "conversation-1")
        conversation["user_id"] = "another-owner"
        world.conversations.upsert_item(conversation)
        return result

    with pytest.raises(PermissionError):
        api.cleanup(output_cleanup=enroll_then_revoke)
    assert api.source_cleanup.call_count == api.source_fence.call_count == 0
    assert world.blobs.deletes == 0


@pytest.mark.parametrize("retain_committed", [False, True])
def test_replay_cannot_change_the_frozen_retention_policy(deletion_api, retain_committed):
    api, world = deletion_api, deletion_api.world
    output = world.run(world.prepare())
    api.cleanup(retain_committed=retain_committed)
    before = deepcopy(world.runs.items)
    api.source_cleanup.reset_mock()
    with pytest.raises(OutputUnavailableError) as raised:
        api.cleanup(retain_committed=not retain_committed)
    saved = world.runs.read_item(output["output_id"], "conversation-1")
    assert raised.value.code == "output_cleanup_policy_changed"
    assert world.runs.items == before and api.source_cleanup.call_count == 0
    assert saved["state"] == ("completed" if retain_committed else "cancelled")


def test_lost_parent_ack_has_real_guard_proof_for_missing_conversation_replay(deletion_api, monkeypatch):
    api, world = deletion_api, deletion_api.world
    output = world.run(world.prepare())
    replace_run = world.runs.replace_item
    interrupted = False

    def lose_parent_ack(*args, **kwargs):
        nonlocal interrupted
        saved = replace_run(*args, **kwargs)
        if not interrupted and saved.get("checkpoints_deleted") is True:
            interrupted = True
            raise Crash("The deletion CAS committed before acknowledgment.")
        return saved

    monkeypatch.setattr(world.runs, "replace_item", lose_parent_ack)
    with pytest.raises(Crash):
        api.cleanup()
    parent = world.runs.read_item("run-1", "conversation-1")
    guard = world.cleanup_guards.read_item("checkpoint:lifecycle", "run-1")
    saved = world.runs.read_item(output["output_id"], "conversation-1")
    assert interrupted and parent["output_cleanup"]["state"] == "pending"
    assert guard["deleted"] is True and guard["token"] is None
    assert saved["state"] == "completed" and not saved["cleanup_pending"]
    assert api.source_cleanup.call_count == 0
    conversation = world.conversations.read_item("conversation-1", "conversation-1")
    world.conversations.delete_item("conversation-1", "conversation-1", etag=conversation["_etag"])
    world.results.sources.clear()
    world.results.container.fail_reads = True
    enrolled = cleanup_tick(api.runtime, max_cleanup_runs=1)
    assert enrolled["ok"] is True and enrolled["counts"]["cleanup_runs_enrolled"] == 1, enrolled
    advance_cleanup_grace(world, [output])
    cleaned = cleanup_tick(api.runtime)
    assert cleaned["ok"] is True and cleaned["counts"]["outputs_processed"] == 1, cleaned
    assert not world.blobs.data and world.blobs.deletes == 1


@pytest.mark.parametrize("boundary", ["checkpoint", "output"])
def test_failed_fences_stop_payload_purge_and_preserve_retriable_work(deletion_api, boundary):
    api, world = deletion_api, deletion_api.world
    output = world.run(world.prepare())
    if boundary == "checkpoint":
        world.cleanup_guards.fail_writes = True
        failure_type = api.recovery.CheckpointError
    else:
        world.runs.fail_batch_at = 1
        failure_type = OutputStorageError
    with pytest.raises(failure_type):
        api.cleanup()
    parent = world.runs.read_item("run-1", "conversation-1")
    saved = world.runs.read_item(output["output_id"], "conversation-1")
    assert saved["state"] == "completed" and not saved["deleted_at"]
    assert api.source_cleanup.call_count == api.source_fence.call_count == 0
    assert world.blobs.deletes == 0
    if boundary == "output":
        assert parent["output_cleanup"]["state"] == "pending"
    else:
        assert not parent.get("checkpoints_deleted") and "output_cleanup" not in parent
    world.cleanup_guards.fail_writes = False
    world.runs.fail_batch_at = None
    result = api.cleanup()
    parent = world.runs.read_item("run-1", "conversation-1")
    assert result is None and parent["output_cleanup"]["state"] == "completed"
    assert api.source_cleanup.call_count == 1


def test_parent_cas_retry_freezes_the_fresh_complete_admission_index(deletion_api):
    api, world = deletion_api, deletion_api.world
    outputs = [world.run(world.prepare("json")), world.run(world.prepare("csv"))]
    output_ids = [output["output_id"] for output in outputs]
    run = world.runs.read_item("run-1", "conversation-1")
    run["render_output_ids"] = output_ids[:1]
    world.runs.upsert_item(run)

    def finish_racing_admission():
        current = world.runs.read_item("run-1", "conversation-1")
        current["render_output_ids"] = list(output_ids)
        world.runs.upsert_item(current)

    world.runs.before_replace = finish_racing_admission
    result = api.cleanup()
    parent = world.runs.read_item("run-1", "conversation-1")
    saved = [world.runs.read_item(output_id, "conversation-1") for output_id in output_ids]
    assert result is None and parent["output_cleanup"]["output_ids"] == output_ids
    assert parent["output_cleanup"]["state"] == "completed"
    assert all(row["state"] == "cancelled" and row["cleanup_pending"] for row in saved)
    assert api.source_cleanup.call_count == 1 and world.blobs.deletes == 0


@pytest.mark.parametrize("boundary", ["enrollment", "source_cleanup"])
def test_every_owned_run_has_replayable_enrollment_before_any_source_failure(
    deletion_api, boundary,
):
    api, world = deletion_api, deletion_api.world
    first = world.run(world.prepare())
    second = second_run_output(world)

    def interrupted(*args):
        raise Crash("The process stopped after all run deletion intents were durable.")

    if boundary == "enrollment":
        options = {"output_cleanup": interrupted}
    else:
        options = {"analysis_cleanup": interrupted}
    with pytest.raises(Crash):
        api.cleanup(**options)
    parents = [world.runs.read_item(run_id, "conversation-1") for run_id in ("run-1", "run-2")]
    guards = [world.cleanup_guards.read_item("checkpoint:lifecycle", run_id) for run_id in ("run-1", "run-2")]
    expected_state = "pending" if boundary == "enrollment" else "completed"
    assert all(parent["output_cleanup"]["state"] == expected_state for parent in parents)
    assert all(parent["checkpoints_deleted"] is True for parent in parents)
    assert all(guard["deleted"] is True and guard["token"] is None for guard in guards)
    assert world.blobs.deletes == 0
    world.results.sources.clear()
    world.results.container.fail_reads = True
    enrolled = cleanup_tick(api.runtime, max_cleanup_runs=2)
    assert enrolled["ok"] is True, enrolled
    assert enrolled["counts"]["cleanup_runs_enrolled"] == (2 if boundary == "enrollment" else 0)
    advance_cleanup_grace(world, [first, second])
    cleaned = cleanup_tick(api.runtime)
    assert cleaned["ok"] is True and cleaned["counts"]["outputs_processed"] == 2, cleaned
    assert not world.blobs.data and world.blobs.deletes == 2
