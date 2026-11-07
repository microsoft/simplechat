# test_orchestration_output_enrollment.py
"""
Durable admission-index enrollment for interrupted conversation deletion.
Version: 0.261.127
Implemented in: 0.261.127

The real initialized cleanup root fences independently committed outputs using
a frozen parent intent. Storage I/O is doubled; source access, render replay and
transport deletion cannot substitute for durable cleanup enrollment.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.core import MatchConditions
from azure.core.exceptions import AzureError

from functions_orchestration_output_store import (
    OutputError,
    OutputStorageError,
    OutputUnavailableError,
    build_output_cleanup_intent,
    enumerate_due_outputs,
    enumerate_output_cleanup_enrollments,
)
from test_orchestration_cleanup_bootstrap import cleanup_root  # noqa: F401
from test_orchestration_output_cleanup import (
    cleanup_lifecycle, production_modules, retain_run_deletion_tombstone,  # noqa: F401
)
from test_orchestration_output_lifecycle import Crash


@pytest.fixture
def enrollment_runtime(cleanup_root):
    world = cleanup_root.world
    run = world.runs.read_item("run-1", "conversation-1")
    run["plan"]["planner_contract_version"] = 2
    world.runs.upsert_item(run)
    return cleanup_root


def persist_deletion_intent(world, *, retain_committed=False, missing=False):
    conversation = world.conversations.read_item("conversation-1", "conversation-1")
    conversation["orchestration_deleted"] = True
    world.conversations.upsert_item(conversation)
    run = world.runs.read_item("run-1", "conversation-1")
    intent = build_output_cleanup_intent(run, retain_committed=retain_committed)
    replacement = {key: value for key, value in run.items() if not key.startswith("_")}
    replacement.update(checkpoints_deleted=True, execution_lease=None, output_cleanup=intent)
    world.runs.replace_item(
        "run-1", replacement, etag=run["_etag"], match_condition=MatchConditions.IfNotModified,
    )
    retain_run_deletion_tombstone(world)
    if missing:
        conversation = world.conversations.read_item("conversation-1", "conversation-1")
        world.conversations.delete_item("conversation-1", "conversation-1", etag=conversation["_etag"])
    return intent


def cleanup_service(runtime):
    return runtime.module.build_orchestration_cleanup_service("owner", "conversation-1")


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("retain_committed", [False, True])
def test_root_enrolls_complete_and_staged_outputs_without_source_or_blob_io(
    enrollment_runtime, missing, retain_committed,
):
    runtime, world = enrollment_runtime, enrollment_runtime.world
    complete = world.run(world.prepare("json"))
    staged = world.prepare("csv")

    def interrupted_upload():
        raise Crash("The file uploaded before its message was written.")

    world.blobs.after_upload = interrupted_upload
    with pytest.raises(Crash):
        world.run(staged)
    before = world.raw(complete)
    persist_deletion_intent(world, retain_committed=retain_committed, missing=missing)
    world.results.sources.clear()
    world.results.container.fail_reads = True
    authority_calls = list(world.authorization_calls)
    ordinary = enumerate_due_outputs(world.runs, now=world.now)
    selectors = enumerate_output_cleanup_enrollments(world.runs)
    assert ordinary == []
    assert selectors == [{"run_id": "run-1", "user_id": "owner", "conversation_id": "conversation-1"}]

    cleanup = cleanup_service(runtime)
    result = cleanup.enroll_run_cleanup(selectors[0]["run_id"])
    repeated = cleanup.enroll_run_cleanup(selectors[0]["run_id"])
    parent = world.runs.read_item("run-1", "conversation-1")
    committed = world.runs.read_item(complete["output_id"], "conversation-1")
    interrupted = world.runs.read_item(staged["output_id"], "conversation-1")
    remaining = enumerate_output_cleanup_enrollments(world.runs)
    assert result == repeated == {
        "run_id": "run-1", "enrollment_status": "completed",
        "output_count": 2, "retain_committed": retain_committed,
    }
    assert parent["output_cleanup"]["state"] == "completed" and remaining == []
    assert interrupted["state"] == "cancelled" and interrupted["cleanup_pending"] is True
    assert committed["committed_intent"] == before["committed_intent"]
    assert committed["state"] == ("completed" if retain_committed else "cancelled")
    assert bool(committed["deleted_at"]) is not retain_committed
    assert world.blobs.deletes == 0 and len(world.blobs.data) == 2
    assert world.authorization_calls == authority_calls
    world.now += timedelta(seconds=11)
    due = enumerate_due_outputs(world.runs, now=world.now)
    assert len(due) == (1 if retain_committed else 2)
    for selected in due:
        cleaned = cleanup.cleanup(selected["output_id"])
        assert cleaned["cleanup_status"] == "complete"
    assert len(world.blobs.data) == int(retain_committed)
    assert len(world.render_calls) == world.blobs.uploads == 2


def test_enrollment_restarts_after_one_output_commits(enrollment_runtime):
    runtime, world = enrollment_runtime, enrollment_runtime.world
    outputs = [world.run(world.prepare("json")), world.run(world.prepare("csv"))]
    persist_deletion_intent(world)

    def lose_acknowledgment():
        raise Crash("The first output fence committed.")

    world.runs.after_batch = lose_acknowledgment
    with pytest.raises(Crash):
        cleanup_service(runtime).enroll_run_cleanup("run-1")
    parent = world.runs.read_item("run-1", "conversation-1")
    partial = [world.runs.read_item(output["output_id"], "conversation-1") for output in outputs]
    assert parent["output_cleanup"]["state"] == "pending"
    assert [item["state"] for item in partial] == ["cancelled", "completed"]
    assert world.blobs.deletes == 0
    resumed = cleanup_service(runtime).enroll_run_cleanup("run-1")
    saved = [world.runs.read_item(output["output_id"], "conversation-1") for output in outputs]
    assert resumed["enrollment_status"] == "completed"
    assert all(item["deleted_at"] and item["cleanup_pending"] for item in saved)
    assert all(item["attempt_count"] == item["automatic_attempts"] == 1 for item in saved)
    assert len(world.render_calls) == world.blobs.uploads == 2


def test_competing_enrollment_workers_keep_one_durable_fence_per_output(enrollment_runtime, monkeypatch):
    runtime, world = enrollment_runtime, enrollment_runtime.world
    outputs = [world.run(world.prepare("json")), world.run(world.prepare("csv"))]
    persist_deletion_intent(world)
    execute_batch = world.runs.execute_item_batch
    barrier, lock, entered = threading.Barrier(2), threading.Lock(), set()

    def competing_batch(*args, **kwargs):
        worker = threading.get_ident()
        with lock:
            first_write = worker not in entered
            entered.add(worker)
        if first_write:
            barrier.wait(timeout=10)
        return execute_batch(*args, **kwargs)

    monkeypatch.setattr(world.runs, "execute_item_batch", competing_batch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        workers = [pool.submit(cleanup_service(runtime).enroll_run_cleanup, "run-1") for _ in range(2)]
        results = [worker.result(timeout=15) for worker in workers]
    records = [world.runs.read_item(output["output_id"], "conversation-1") for output in outputs]
    parent = world.runs.read_item("run-1", "conversation-1")
    assert results[0] == results[1] and results[0]["enrollment_status"] == "completed"
    assert parent["output_cleanup"]["state"] == "completed"
    assert all(record["deleted_at"] and record["attempt_count"] == 1 for record in records)
    assert world.blobs.deletes == 0 and len(world.render_calls) == world.blobs.uploads == 2


def test_enrollment_rechecks_retention_intent_after_a_cas_conflict(enrollment_runtime):
    runtime, world = enrollment_runtime, enrollment_runtime.world
    output = world.run(world.prepare())
    persist_deletion_intent(world)
    before = world.runs.read_item(output["output_id"], "conversation-1")

    def change_policy():
        parent = world.runs.read_item("run-1", "conversation-1")
        parent["output_cleanup"]["retain_committed"] = True
        world.runs.upsert_item(parent)

    world.runs.before_batch = change_policy
    with pytest.raises(OutputUnavailableError):
        cleanup_service(runtime).enroll_run_cleanup("run-1")
    after = world.runs.read_item(output["output_id"], "conversation-1")
    assert before == after and world.blobs.deletes == 0


def test_enrollment_pins_missing_conversation_deletion_proof(enrollment_runtime):
    runtime, world = enrollment_runtime, enrollment_runtime.world
    world.run(world.prepare("json"))
    world.run(world.prepare("csv"))
    persist_deletion_intent(world, missing=True)

    def replace_guard():
        guard = world.cleanup_guards.read_item("checkpoint:lifecycle", "run-1")
        guard["unexpected_replacement"] = True
        world.cleanup_guards.upsert_item(guard)

    world.runs.after_batch = replace_guard
    with pytest.raises(OutputUnavailableError):
        cleanup_service(runtime).enroll_run_cleanup("run-1")
    parent = world.runs.read_item("run-1", "conversation-1")
    assert parent["output_cleanup"]["state"] == "pending" and world.blobs.deletes == 0


@pytest.mark.parametrize("lost_ack", [False, True])
def test_completion_marker_requires_persistence_and_reconciles_uncertain_ack(
    enrollment_runtime, lost_ack, monkeypatch,
):
    runtime, world = enrollment_runtime, enrollment_runtime.world
    output = world.run(world.prepare())
    persist_deletion_intent(world)
    execute_batch = world.runs.execute_item_batch
    failed = False

    def completion_fault(*args, **kwargs):
        nonlocal failed
        operations = kwargs["batch_operations"]
        completing = len(operations) == 1
        if completing and not failed:
            failed = True
            if lost_ack:
                execute_batch(*args, **kwargs)
            raise AzureError("The enrollment marker acknowledgment was interrupted.")
        return execute_batch(*args, **kwargs)

    monkeypatch.setattr(world.runs, "execute_item_batch", completion_fault)
    if lost_ack:
        result = cleanup_service(runtime).enroll_run_cleanup("run-1")
    else:
        with pytest.raises(OutputStorageError):
            cleanup_service(runtime).enroll_run_cleanup("run-1")
        pending = world.runs.read_item("run-1", "conversation-1")
        assert pending["output_cleanup"]["state"] == "pending"
        result = cleanup_service(runtime).enroll_run_cleanup("run-1")
    stored = world.runs.read_item(output["output_id"], "conversation-1")
    assert result["enrollment_status"] == "completed" and failed
    assert stored["deleted_at"] and stored["cleanup_pending"] and stored["attempt_count"] == 1
    assert world.blobs.deletes == 0 and len(world.render_calls) == 1


@pytest.mark.parametrize("defect", [
    "intent_missing", "intent_version", "intent_extra_field", "intent_policy",
    "index_missing", "index_changed", "index_duplicate", "index_limit", "index_invalid",
    "parent_owner", "parent_fence", "conversation_owner", "guard_missing",
])
def test_enrollment_rejects_incomplete_or_foreign_authority(enrollment_runtime, defect):
    runtime, world = enrollment_runtime, enrollment_runtime.world
    output = world.run(world.prepare())
    persist_deletion_intent(world, missing=defect == "guard_missing")
    run = world.runs.read_item("run-1", "conversation-1")
    if defect == "intent_missing":
        run.pop("output_cleanup")
    elif defect == "intent_version":
        run["output_cleanup"]["version"] = True
    elif defect == "intent_extra_field":
        run["output_cleanup"]["blob_path"] = "foreign-file"
    elif defect == "intent_policy":
        run["output_cleanup"]["retain_committed"] = "false"
    elif defect == "index_missing":
        run.pop("render_output_ids")
    elif defect == "index_changed":
        run["render_output_ids"] = []
    elif defect in {"index_duplicate", "index_limit", "index_invalid"}:
        invalid = {
            "index_duplicate": [output["output_id"], output["output_id"]],
            "index_limit": [f"orender_{number:064x}" for number in range(33)],
            "index_invalid": ["guessed-file-path"],
        }[defect]
        run["render_output_ids"] = invalid
        run["output_cleanup"]["output_ids"] = deepcopy(invalid)
    elif defect == "parent_owner":
        run["user_id"] = "someone-else"
    elif defect == "parent_fence":
        run["checkpoints_deleted"] = False
    elif defect == "conversation_owner":
        conversation = world.conversations.read_item("conversation-1", "conversation-1")
        conversation["user_id"] = "someone-else"
        world.conversations.upsert_item(conversation)
    else:
        guard = world.cleanup_guards.read_item("checkpoint:lifecycle", "run-1")
        world.cleanup_guards.delete_item("checkpoint:lifecycle", "run-1", etag=guard["_etag"])
    world.runs.upsert_item(run)
    before = world.runs.read_item(output["output_id"], "conversation-1")
    with pytest.raises(OutputUnavailableError):
        cleanup_service(runtime).enroll_run_cleanup("run-1")
    after = world.runs.read_item(output["output_id"], "conversation-1")
    assert before == after and world.blobs.deletes == 0


def test_enrollment_cannot_borrow_another_runs_valid_output(enrollment_runtime):
    runtime, world = enrollment_runtime, enrollment_runtime.world
    output = world.run(world.prepare())
    persist_deletion_intent(world)
    before = world.runs.read_item(output["output_id"], "conversation-1")
    other = world.runs.read_item("run-1", "conversation-1")
    other.update(id="other-run")
    world.runs.create_item(other)
    with pytest.raises(OutputUnavailableError):
        cleanup_service(runtime).enroll_run_cleanup("other-run")
    after = world.runs.read_item(output["output_id"], "conversation-1")
    assert after == before and world.blobs.deletes == 0


def test_retention_policy_and_admission_snapshot_cannot_change_on_retry(enrollment_runtime):
    world = enrollment_runtime.world
    world.run(world.prepare())
    initial = persist_deletion_intent(world, retain_committed=True)
    run = world.runs.read_item("run-1", "conversation-1")
    repeated = build_output_cleanup_intent(run, retain_committed=True)
    assert repeated == initial
    with pytest.raises(OutputUnavailableError):
        build_output_cleanup_intent(run, retain_committed=False)
    run["render_output_ids"] = []
    with pytest.raises(OutputUnavailableError):
        build_output_cleanup_intent(run, retain_committed=True)


@pytest.mark.parametrize("limit", [0, 201, True, "2"])
def test_enrollment_selection_has_a_strict_bound(enrollment_runtime, limit):
    world = enrollment_runtime.world
    before = len(world.runs.queries)
    with pytest.raises(OutputError):
        enumerate_output_cleanup_enrollments(world.runs, limit=limit)
    assert len(world.runs.queries) == before


@pytest.mark.parametrize("select", [
    pytest.param(enumerate_due_outputs, id="due"),
    pytest.param(enumerate_output_cleanup_enrollments, id="enrollment"),
])
@pytest.mark.parametrize("limit", [1, 64, 200])
@pytest.mark.parametrize("tail", ["malformed", "error"])
def test_selectors_do_not_advance_the_iterator_past_the_limit(select, limit, tail):
    consumed = []

    def rows():
        for index in range(limit):
            consumed.append(index)
            yield {
                "id": f"orender_{index:064x}" if select is enumerate_due_outputs else f"run-{index}",
                "user_id": "owner", "conversation_id": "conversation-1", "run_id": "run-1",
            }
        consumed.append("outside-budget")
        if tail == "error":
            raise AzureError("A new provider page must not be fetched beyond the budget.")
        yield None

    container = SimpleNamespace(query_items=Mock(return_value=rows()))
    selected = select(container, limit=limit)
    assert len(selected) == limit and consumed == list(range(limit))
    assert container.query_items.call_args.kwargs["max_item_count"] == limit


@pytest.mark.parametrize("select", [enumerate_due_outputs, enumerate_output_cleanup_enrollments])
def test_selectors_still_reject_a_malformed_row_inside_the_budget(select):
    container = SimpleNamespace(query_items=Mock(return_value=iter([None])))
    with pytest.raises(OutputError) as caught:
        select(container, limit=1)
    assert caught.value.code == "output_record_invalid"


def test_enrollment_selection_outage_is_not_empty_success(enrollment_runtime):
    world = enrollment_runtime.world
    world.runs.fail_queries = True
    with pytest.raises(OutputStorageError):
        enumerate_output_cleanup_enrollments(world.runs)


def test_enrollment_selection_honors_its_positive_limit(enrollment_runtime):
    world = enrollment_runtime.world
    world.run(world.prepare())
    persist_deletion_intent(world)
    other = world.runs.read_item("run-1", "conversation-1")
    other["id"] = "other-run"
    world.runs.create_item(other)
    limited = enumerate_output_cleanup_enrollments(world.runs, limit=1)
    both = enumerate_output_cleanup_enrollments(world.runs, limit=2)
    assert len(limited) == 1 and len(both) == 2
    assert set(limited[0]) == {"run_id", "user_id", "conversation_id"}


def test_empty_admission_index_finishes_without_file_mutation(enrollment_runtime):
    runtime, world = enrollment_runtime, enrollment_runtime.world
    initial = persist_deletion_intent(world)
    before = deepcopy(world.runs.items)
    result = cleanup_service(runtime).enroll_run_cleanup("run-1")
    assert initial["state"] == "completed" and result["output_count"] == 0
    assert world.runs.items == before and world.blobs.deletes == 0
