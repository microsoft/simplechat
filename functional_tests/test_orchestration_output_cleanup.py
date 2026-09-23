# test_orchestration_output_cleanup.py
"""
Deletion-only cleanup against real output/transport code and storage I/O doubles.
Version: 0.261.127
Implemented in: 0.261.127

An owned conversation tombstone or a matching irreversible run deletion guard
authorizes cleanup. A missing conversation alone is never deletion authority.
"""

import importlib
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest
from azure.core.exceptions import AzureError

from functions_generated_export_contracts import GeneratedFileExportRequest
from functions_orchestration_artifacts import OrchestrationOutputCleanupService
from functions_orchestration_checkpoints import CHECKPOINT_VERSION, CheckpointStore
from functions_orchestration_output_store import (
    OrchestrationOutputStore,
    OutputConflictError,
    OutputStorageError,
    OutputUnavailableError,
    enumerate_due_outputs,
)
from test_orchestration_output_lifecycle import Crash, Lifecycle, production_modules
from test_support.orchestration_revisions import AtomicMemoryContainer


@pytest.fixture
def cleanup_lifecycle(production_modules, monkeypatch):
    fixture = Lifecycle(production_modules, monkeypatch)
    fixture.cleanup_guards = AtomicMemoryContainer("run_id")
    yield fixture
    if any(not stream.closed for stream in fixture.output_streams):
        raise AssertionError("A render stream escaped deletion-only cleanup tests.")


def cleanup_service(fixture, *, reader=None):
    store = OrchestrationOutputStore(
        fixture.runs, user_id="owner", conversation_id="conversation-1",
        read_conversation=reader if reader is not None else lambda cid: fixture.conversations.read_item(cid, cid),
        clock=lambda: fixture.now, lease_seconds=10,
        read_run_tombstone=lambda rid: fixture.cleanup_guards.read_item("checkpoint:lifecycle", rid),
    )
    return OrchestrationOutputCleanupService(
        store, fixture.messages, fixture.blobs, blob_container="chat",
    )


def interrupted_output(fixture, boundary="message"):
    output = fixture.prepare()

    def crash():
        raise Crash(boundary)

    if boundary == "before_blob":
        fixture.blobs.before_upload = crash
    elif boundary == "blob":
        fixture.blobs.after_upload = crash
    else:
        fixture.messages.after_create = crash
    with pytest.raises(Crash):
        fixture.run(output)
    return output


def retain_run_deletion_tombstone(fixture, run_id="run-1"):
    def authorize():
        conversation = fixture.conversations.read_item("conversation-1", "conversation-1")
        if conversation.get("user_id") != "owner" or not (
            conversation.get("deleted") or conversation.get("orchestration_deleted")
        ):
            raise PermissionError("The fixture conversation has not been logically deleted by its owner.")

    run = fixture.runs.read_item(run_id, "conversation-1")
    turn_id = run.get("turn_id") or run["plan"].get("turn_id") or f"turn-{run_id}"
    run.update(checkpoints_deleted=True, checkpoint_version=CHECKPOINT_VERSION, turn_id=turn_id)
    fixture.runs.upsert_item(run)
    guard = CheckpointStore(
        fixture.cleanup_guards, run_id=run_id, user_id="owner",
        conversation_id="conversation-1", turn_id=turn_id, authorize=authorize,
    )
    guard.fence(deleted=True, allow_missing=True)


def delete_conversation(fixture, mode, *, retain_guard=True):
    conversation = fixture.conversations.read_item("conversation-1", "conversation-1")
    if mode == "missing":
        if retain_guard:
            conversation["orchestration_deleted"] = True
            fixture.conversations.upsert_item(conversation)
            retain_run_deletion_tombstone(fixture)
            conversation = fixture.conversations.read_item("conversation-1", "conversation-1")
        fixture.conversations.delete_item(
            "conversation-1", "conversation-1", etag=conversation["_etag"],
        )
    else:
        conversation[mode] = True
        fixture.conversations.upsert_item(conversation)


@pytest.mark.parametrize("mode", ["missing", "deleted", "orchestration_deleted"])
@pytest.mark.parametrize("boundary", ["blob", "message"])
def test_deleted_conversation_cleanup_uses_real_retained_ownership(cleanup_lifecycle, mode, boundary, monkeypatch):
    fixture = cleanup_lifecycle
    output = interrupted_output(fixture, boundary)
    before = fixture.raw(output)
    delete_conversation(fixture, mode)
    fixture.results.sources.clear()
    fixture.results.container.fail_reads = True
    monkeypatch.setattr(importlib.import_module("functions_orchestration_artifacts"), "_service_factory", None)
    with pytest.raises(OutputUnavailableError):
        fixture.service.reconcile(output["output_id"])
    cleanup = cleanup_service(fixture)
    deferred = cleanup.cleanup(output["output_id"])
    fenced = fixture.runs.read_item(output["output_id"], "conversation-1")
    assert deferred["cleanup_status"] == "deferred" and deferred["processed_intents"] == 0
    assert fenced["state"] == "cancelled" and fenced["deleted_at"]
    assert fenced["lease"] is None and fixture.blobs.data
    assert fenced["attempt_count"] == before["attempt_count"] == 1
    fixture.now += timedelta(seconds=11)
    due = enumerate_due_outputs(fixture.runs, now=fixture.now)
    assert any(selector["output_id"] == output["output_id"] for selector in due)
    complete = cleanup.cleanup(output["output_id"])
    repeated = cleanup.cleanup(output["output_id"])
    saved = fixture.runs.read_item(output["output_id"], "conversation-1")
    assert complete["cleanup_status"] == "complete" and complete["processed_intents"] == 1
    assert repeated["cleanup_status"] == "complete" and repeated["processed_intents"] == 0
    assert saved["cleanup_pending"] is False and not fixture.blobs.data and not fixture.messages.items
    assert saved["automatic_attempts"] == before["automatic_attempts"] == 1
    assert len(fixture.render_calls) == fixture.blobs.uploads == fixture.blobs.deletes == 1
    assert set(complete) == {"output_id", "state", "cleanup_status", "cleanup_pending", "processed_intents"}
    with pytest.raises(OutputUnavailableError):
        fixture.service.read(output["output_id"])


@pytest.mark.parametrize("mode", ["missing", "deleted", "orchestration_deleted"])
def test_initialized_cleanup_factory_never_requires_a_live_conversation(cleanup_lifecycle, mode, monkeypatch):
    fixture = cleanup_lifecycle
    output = interrupted_output(fixture)
    delete_conversation(fixture, mode)
    fixture.now += timedelta(seconds=11)
    fixture.results.sources.clear()
    fixture.results.container.fail_reads = True
    bootstrap = importlib.import_module("functions_orchestration_bootstrap")
    monkeypatch.setattr(fixture.modules.config, "cosmos_orchestration_runs_container", fixture.runs)
    monkeypatch.setattr(fixture.modules.config, "cosmos_orchestration_run_steps_container", fixture.cleanup_guards)
    monkeypatch.setattr(fixture.modules.config, "storage_account_personal_chat_container_name", "chat")
    monkeypatch.setattr(importlib.import_module("functions_orchestration_artifacts"), "_service_factory", None)

    def forbidden(*args, **kwargs):
        raise AssertionError("Deletion-only cleanup entered the live authorization/rendering factory.")

    monkeypatch.setattr(bootstrap, "read_owned_conversation", forbidden)
    monkeypatch.setattr(bootstrap, "build_orchestration_services", forbidden)
    cleanup = bootstrap.build_orchestration_cleanup_service("owner", "conversation-1")
    cleanup.store.clock = lambda: fixture.now
    result = cleanup.cleanup(output["output_id"])
    saved = fixture.runs.read_item(output["output_id"], "conversation-1")
    assert result["cleanup_status"] == "complete" and result["processed_intents"] == 1
    assert saved["state"] == "cancelled" and saved["deleted_at"] and not saved["cleanup_pending"]
    assert not fixture.blobs.data and not fixture.messages.items
    assert len(fixture.render_calls) == fixture.blobs.uploads == fixture.blobs.deletes == 1


@pytest.mark.parametrize("state", ["cancelled", "failed"])
def test_terminal_cleanup_does_not_need_current_source_access(cleanup_lifecycle, state):
    fixture = cleanup_lifecycle
    output = interrupted_output(fixture)
    if state == "cancelled":
        fixture.service.store.cancel(output["output_id"])
    else:
        fixture.now += timedelta(seconds=11)
        fixture.service.store.fail(output["output_id"], code="output_access_denied", retryable=False)
    fixture.results.sources.clear()
    fixture.results.container.fail_reads = True
    fixture.now += timedelta(seconds=11)
    result = cleanup_service(fixture).cleanup(output["output_id"])
    assert result["cleanup_status"] == "complete"
    assert not fixture.blobs.data and not fixture.messages.items


def test_live_running_output_cannot_be_deleted_by_cleanup(cleanup_lifecycle):
    fixture = cleanup_lifecycle
    output = interrupted_output(fixture)
    before = fixture.raw(output)
    with pytest.raises(OutputUnavailableError) as failure:
        cleanup_service(fixture).cleanup(output["output_id"])
    after = fixture.raw(output)
    assert failure.value.code == "output_cleanup_denied"
    assert before == after and fixture.blobs.data and fixture.messages.items
    assert fixture.blobs.deletes == 0


def test_completed_output_requires_explicit_tombstone_even_after_owner_deletion(cleanup_lifecycle):
    fixture = cleanup_lifecycle
    completed = fixture.run(fixture.prepare())
    before = fixture.raw(completed)
    cleanup = cleanup_service(fixture)
    untouched = cleanup.cleanup(completed["output_id"])
    after = fixture.raw(completed)
    assert untouched["cleanup_status"] == "complete" and untouched["processed_intents"] == 0
    assert before == after and fixture.blobs.deletes == 0
    delete_conversation(fixture, "missing")
    preserved = cleanup.cleanup(completed["output_id"])
    preserved_record = fixture.runs.read_item(completed["output_id"], "conversation-1")
    assert preserved["processed_intents"] == 0 and preserved_record["state"] == "completed"
    assert preserved_record["deleted_at"] is None and fixture.blobs.deletes == 0
    withdrawal = cleanup.tombstone(completed["output_id"])
    deferred = cleanup.cleanup(completed["output_id"])
    fixture.now += timedelta(seconds=11)
    cleaned = cleanup.cleanup(completed["output_id"])
    tombstone = fixture.runs.read_item(completed["output_id"], "conversation-1")
    assert deferred["cleanup_status"] == "deferred"
    assert withdrawal["state"] == "cancelled"
    assert cleaned["cleanup_status"] == "complete" and not fixture.blobs.data and not fixture.messages.items
    assert tombstone["attempts"][0]["state"] == "completed"
    assert tombstone["committed_intent"] == before["committed_intent"]


def test_cleanup_removes_only_obsolete_intents_of_a_successful_live_output(cleanup_lifecycle):
    fixture = cleanup_lifecycle
    output = interrupted_output(fixture, "before_blob")
    fixture.now += timedelta(seconds=11)
    recovered = fixture.service.reconcile(output["output_id"])
    fixture.advance_due(output)
    completed = fixture.run(output)
    before = fixture.raw(completed)
    fixture.now += timedelta(seconds=11)
    cleaned = cleanup_service(fixture).cleanup(output["output_id"])
    after = fixture.raw(completed)
    payload = fixture.download(completed)
    assert recovered["state"] == "retry_scheduled" and completed["state"] == "completed"
    assert len(before["intents"]) == 2 and before["cleanup_pending"] is True
    assert cleaned["processed_intents"] == 1 and cleaned["cleanup_status"] == "complete"
    assert before["committed_intent"] == after["committed_intent"] and after["state"] == "completed"
    assert payload and len(fixture.messages.items) == len(fixture.blobs.data) == 1
    assert len(fixture.render_calls) == 2 and fixture.blobs.deletes == 0


def test_deleted_run_cleanup_preserves_other_successful_runs(cleanup_lifecycle):
    fixture = cleanup_lifecycle
    completed = fixture.run(fixture.prepare())
    other_source = fixture.retain_source("document-2")
    other_run = fixture.runs.read_item("run-1", "conversation-1")
    other_run.update(id="run-2", render_output_ids=[])
    fixture.runs.create_item(other_run)
    other = fixture.service.ensure_output(
        producer=replace(fixture.add_render_step("json_file"), run_id="run-2"),
        source_ref=other_source, export_request=GeneratedFileExportRequest("json"),
        file_name="other.json", approved_work_id="run-2", deadline_at=fixture.deadline.isoformat(),
    )
    other = fixture.run(other)
    other_before = fixture.raw(other)
    fixture.change_run(outputs_deleted=True)
    fixture.results.container.fail_reads = True
    fixture.now += timedelta(seconds=11)
    cleanup = cleanup_service(fixture)
    cleanup.tombstone(completed["output_id"])
    cleaned = cleanup.cleanup(completed["output_id"])
    stored = fixture.runs.read_item(completed["output_id"], "conversation-1")
    other_after = fixture.raw(other)
    fixture.results.container.fail_reads = False
    other_bytes = fixture.download(other)
    assert cleaned["cleanup_status"] == "complete" and stored["state"] == "cancelled"
    assert stored["deleted_at"] and len(fixture.messages.items) == len(fixture.blobs.data) == 1
    assert other_before == other_after and other_after["state"] == "completed" and other_bytes


@pytest.mark.parametrize("authority", [
    "run_missing", "run_owner", "admission_missing", "conversation_owner", "conversation_flag",
    "conversation_metadata", "null_reader",
])
def test_cleanup_rejects_missing_or_foreign_authority(cleanup_lifecycle, authority):
    fixture = cleanup_lifecycle
    output = interrupted_output(fixture)
    fixture.service.store.cancel(output["output_id"])
    fixture.now += timedelta(seconds=11)
    run = fixture.runs.read_item("run-1", "conversation-1")
    reader = None
    if authority == "run_missing":
        fixture.runs.delete_item("run-1", "conversation-1", etag=run["_etag"])
    elif authority in {"run_owner", "admission_missing"}:
        run.update({"user_id": "other-owner"} if authority == "run_owner" else {"render_output_ids": []})
        fixture.runs.upsert_item(run)
    elif authority == "conversation_owner":
        conversation = fixture.conversations.read_item("conversation-1", "conversation-1")
        conversation.update(user_id="other-owner", deleted=True)
        fixture.conversations.upsert_item(conversation)
    elif authority == "conversation_flag":
        conversation = fixture.conversations.read_item("conversation-1", "conversation-1")
        conversation["deleted"] = "true"
        fixture.conversations.upsert_item(conversation)
    elif authority == "conversation_metadata":
        reader = lambda cid: {
            name: value for name, value in fixture.conversations.read_item(cid, cid).items()
            if name != "_etag"
        }
    else:
        reader = lambda cid: None
    with pytest.raises(OutputUnavailableError):
        cleanup_service(fixture, reader=reader).cleanup(output["output_id"])
    assert fixture.blobs.deletes == 0 and fixture.blobs.data and fixture.messages.items


@pytest.mark.parametrize("boundary", ["conversation", "run", "message", "blob"])
def test_cleanup_storage_outage_is_not_deletion_authority(cleanup_lifecycle, boundary, monkeypatch):
    fixture = cleanup_lifecycle
    output = interrupted_output(fixture)
    fixture.service.store.cancel(output["output_id"])
    fixture.now += timedelta(seconds=11)
    if boundary == "conversation":
        fixture.conversations.fail_reads = True
    elif boundary == "run":
        fixture.runs.fail_reads = True
    elif boundary == "message":
        fixture.messages.fail_reads = True
    else:
        def fail(**kwargs):
            raise AzureError("Private Blob outage details")

        monkeypatch.setattr(fixture.blobs, "get_blob_client", fail)
    with pytest.raises(OutputStorageError):
        cleanup_service(fixture).cleanup(output["output_id"])
    assert fixture.blobs.deletes == 0 and fixture.blobs.data and fixture.messages.items


def test_cleanup_recomputes_intent_paths_before_storage_deletion(cleanup_lifecycle):
    fixture = cleanup_lifecycle
    output = interrupted_output(fixture)
    saved = fixture.service.store.cancel(output["output_id"])
    fixture.now += timedelta(seconds=11)
    for intent in [saved["intent"], *saved["intents"]]:
        intent["artifact"]["blob_path"] = "other-owner/private-file"
    fixture.runs.upsert_item(saved)
    with pytest.raises(OutputUnavailableError) as failure:
        cleanup_service(fixture).cleanup(output["output_id"])
    assert failure.value.code == "output_intent_invalid" and fixture.blobs.deletes == 0


def test_cleanup_rechecks_owner_before_deleting_bytes(cleanup_lifecycle, monkeypatch):
    fixture = cleanup_lifecycle
    output = interrupted_output(fixture)
    fixture.service.store.cancel(output["output_id"])
    fixture.now += timedelta(seconds=11)
    original = fixture.messages.read_item

    def replace_owner(item, partition_key):
        message = original(item, partition_key)
        run = fixture.runs.read_item("run-1", "conversation-1")
        run["user_id"] = "new-owner"
        fixture.runs.upsert_item(run)
        return message

    monkeypatch.setattr(fixture.messages, "read_item", replace_owner)
    with pytest.raises(OutputUnavailableError):
        cleanup_service(fixture).cleanup(output["output_id"])
    assert fixture.blobs.deletes == 0 and fixture.blobs.data and fixture.messages.items


def test_cleanup_message_delete_is_conditional_and_can_reconcile(cleanup_lifecycle, monkeypatch):
    fixture = cleanup_lifecycle
    output = interrupted_output(fixture)
    fixture.service.store.cancel(output["output_id"])
    fixture.now += timedelta(seconds=11)
    original = fixture.messages.delete_item

    def concurrent_edit(item, partition_key, **kwargs):
        message = fixture.messages.read_item(item, partition_key)
        message["metadata"]["concurrent_edit"] = True
        fixture.messages.upsert_item(message)
        return original(item, partition_key, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(fixture.messages, "delete_item", concurrent_edit)
        with pytest.raises(OutputConflictError):
            cleanup_service(fixture).cleanup(output["output_id"])
    pending = fixture.runs.read_item(output["output_id"], "conversation-1")
    assert pending["cleanup_pending"] is True and fixture.messages.items
    cleaned = cleanup_service(fixture).cleanup(output["output_id"])
    assert cleaned["cleanup_status"] == "complete" and not fixture.messages.items and not fixture.blobs.data


def test_cleanup_finish_cas_preserves_uncertain_acknowledgements(cleanup_lifecycle, monkeypatch):
    fixture = cleanup_lifecycle
    output = interrupted_output(fixture)
    fixture.service.store.cancel(output["output_id"])
    fixture.now += timedelta(seconds=11)
    original = fixture.runs.execute_item_batch
    fired = []

    def lose_response(batch_operations, partition_key, **kwargs):
        result = original(batch_operations, partition_key, **kwargs)
        body = batch_operations[-1][1][-1]
        if body.get("cleanup_pending") is False and not fired:
            fired.append(True)
            raise AzureError("Private lost cleanup acknowledgement")
        return result

    monkeypatch.setattr(fixture.runs, "execute_item_batch", lose_response)
    cleaned = cleanup_service(fixture).cleanup(output["output_id"])
    saved = fixture.runs.read_item(output["output_id"], "conversation-1")
    assert fired == [True] and cleaned["cleanup_status"] == "complete"
    assert saved["cleanup_pending"] is False and not fixture.messages.items and not fixture.blobs.data


def test_cleanup_propagates_failed_fencing_without_deleting_bytes(cleanup_lifecycle):
    fixture = cleanup_lifecycle
    output = interrupted_output(fixture)
    before = deepcopy(fixture.runs.read_item(output["output_id"], "conversation-1"))
    delete_conversation(fixture, "missing")
    fixture.runs.fail_writes = True
    with pytest.raises(OutputStorageError):
        cleanup_service(fixture).cleanup(output["output_id"])
    after = fixture.runs.read_item(output["output_id"], "conversation-1")
    assert before == after and fixture.blobs.deletes == 0


@pytest.mark.parametrize("marker", [None, "outputs_deleted", "checkpoints_deleted", "status"])
def test_missing_conversation_is_not_parent_run_deletion_proof(cleanup_lifecycle, marker):
    fixture = cleanup_lifecycle
    output = interrupted_output(fixture)
    before = fixture.raw(output)
    delete_conversation(fixture, "missing", retain_guard=False)
    if marker:
        fixture.change_run(**{marker: "deleted" if marker == "status" else True})
    with pytest.raises(OutputUnavailableError) as failure:
        cleanup_service(fixture).cleanup(output["output_id"])
    after = fixture.runs.read_item(output["output_id"], "conversation-1")
    assert failure.value.code == "output_cleanup_tombstone_required"
    assert before == after and fixture.blobs.deletes == 0 and fixture.blobs.data


@pytest.mark.parametrize("defect", [
    "reader_missing", "guard_missing", "null_guard", "owner", "conversation", "run", "turn",
    "type", "schema", "deleted", "token", "token_missing", "etag", "run_version", "run_marker",
])
def test_missing_conversation_rejects_wrong_or_incomplete_deletion_guard(cleanup_lifecycle, defect):
    fixture = cleanup_lifecycle
    output = interrupted_output(fixture)
    delete_conversation(fixture, "missing")
    fixture.now += timedelta(seconds=11)
    cleanup = cleanup_service(fixture)
    guard = fixture.cleanup_guards.read_item("checkpoint:lifecycle", "run-1")
    if defect == "reader_missing":
        cleanup.store.read_run_tombstone = None
    elif defect == "guard_missing":
        fixture.cleanup_guards.delete_item(guard["id"], "run-1", etag=guard["_etag"])
    elif defect == "null_guard":
        cleanup.store.read_run_tombstone = lambda rid: None
    elif defect == "etag":
        cleanup.store.read_run_tombstone = lambda rid: {
            key: value for key, value in fixture.cleanup_guards.read_item("checkpoint:lifecycle", rid).items()
            if key != "_etag"
        }
    elif defect == "run_version":
        fixture.change_run(checkpoint_version=2)
    elif defect == "run_marker":
        fixture.change_run(checkpoints_deleted=False)
    else:
        if defect == "token_missing":
            del guard["token"]
        else:
            key, value = {
                "owner": ("user_id", "other-owner"),
                "conversation": ("conversation_id", "other-conversation"),
                "run": ("run_id", "other-run"),
                "turn": ("turn_id", "other-turn"),
                "type": ("record_type", "some_other_guard"),
                "schema": ("schema_version", True),
                "deleted": ("deleted", False),
                "token": ("token", "still-an-active-writer"),
            }[defect]
            guard[key] = value
        fixture.cleanup_guards.upsert_item(guard)
        if defect == "run":
            cleanup.store.read_run_tombstone = lambda rid: fixture.cleanup_guards.read_item(
                "checkpoint:lifecycle", "other-run",
            )
    before = fixture.runs.read_item(output["output_id"], "conversation-1")
    with pytest.raises(OutputUnavailableError):
        cleanup.cleanup(output["output_id"])
    after = fixture.runs.read_item(output["output_id"], "conversation-1")
    assert before == after and fixture.blobs.deletes == 0 and fixture.blobs.data and fixture.messages.items


def test_run_deletion_guard_storage_outage_never_authorizes_cleanup(cleanup_lifecycle):
    fixture = cleanup_lifecycle
    output = interrupted_output(fixture)
    delete_conversation(fixture, "missing")
    fixture.cleanup_guards.fail_reads = True
    with pytest.raises(OutputStorageError):
        cleanup_service(fixture).cleanup(output["output_id"])
    assert fixture.blobs.deletes == 0 and fixture.blobs.data and fixture.messages.items


@pytest.mark.parametrize("change", ["replaced", "removed", "parent_owner"])
def test_cleanup_pins_and_rechecks_the_retained_parent_deletion_guard(cleanup_lifecycle, change):
    fixture = cleanup_lifecycle
    output = interrupted_output(fixture)
    delete_conversation(fixture, "missing")
    cleanup = cleanup_service(fixture)
    deferred = cleanup.cleanup(output["output_id"])
    saved = fixture.runs.read_item(output["output_id"], "conversation-1")
    guard = fixture.cleanup_guards.read_item("checkpoint:lifecycle", "run-1")
    if change == "removed":
        fixture.cleanup_guards.delete_item(guard["id"], "run-1", etag=guard["_etag"])
    elif change == "parent_owner":
        fixture.change_run(user_id="other-owner")
    else:
        guard["claim_id"] = "replacement-lifecycle"
        fixture.cleanup_guards.upsert_item(guard)
    fixture.now += timedelta(seconds=11)
    with pytest.raises(OutputUnavailableError):
        cleanup.cleanup(output["output_id"])
    assert deferred["cleanup_status"] == "deferred" and saved["cleanup_run_tombstone"]
    assert fixture.blobs.deletes == 0 and fixture.blobs.data and fixture.messages.items


@pytest.mark.parametrize("mode", ["deleted", "orchestration_deleted", "missing"])
def test_deletion_cleanup_never_tombstones_a_committed_sibling_implicitly(cleanup_lifecycle, mode):
    fixture = cleanup_lifecycle
    committed = fixture.run(fixture.prepare("csv"))
    descriptor = fixture.raw(committed)["committed_intent"]
    output = interrupted_output(fixture)
    delete_conversation(fixture, mode)
    fixture.now += timedelta(seconds=11)
    cleanup = cleanup_service(fixture)
    staged = cleanup.cleanup(output["output_id"])
    preserved = cleanup.cleanup(committed["output_id"])
    successful = fixture.runs.read_item(committed["output_id"], "conversation-1")
    address = descriptor["artifact"]
    assert staged["cleanup_status"] == "complete"
    assert preserved["processed_intents"] == 0 and successful["state"] == "completed"
    assert successful["committed_intent"] == descriptor and successful["deleted_at"] is None
    assert (address["blob_container"], address["blob_path"]) in fixture.blobs.data
    assert len(fixture.messages.items) == len(fixture.blobs.data) == 1


def test_cleanup_tombstone_cannot_withdraw_a_live_successful_output(cleanup_lifecycle):
    fixture = cleanup_lifecycle
    completed = fixture.run(fixture.prepare())
    before = fixture.raw(completed)
    with pytest.raises(OutputUnavailableError):
        cleanup_service(fixture).tombstone(completed["output_id"])
    after = fixture.raw(completed)
    assert before == after and fixture.blobs.data and fixture.messages.items


@pytest.mark.parametrize("defect", ["missing", "boolean", "malformed", "state"])
def test_committed_intent_requires_a_consistent_explicit_output_tombstone(cleanup_lifecycle, defect):
    fixture = cleanup_lifecycle
    completed = fixture.run(fixture.prepare())
    delete_conversation(fixture, "deleted")
    cleanup = cleanup_service(fixture)
    cleanup.tombstone(completed["output_id"])
    record = fixture.runs.read_item(completed["output_id"], "conversation-1")
    if defect == "state":
        record["state"] = "completed"
    else:
        record["deleted_at"] = {"missing": None, "boolean": True, "malformed": "not-a-time"}[defect]
    fixture.runs.upsert_item(record)
    fixture.now += timedelta(seconds=11)
    with pytest.raises(OutputUnavailableError):
        cleanup.cleanup(completed["output_id"])
    assert fixture.blobs.deletes == 0 and fixture.blobs.data and fixture.messages.items


@pytest.mark.parametrize("mode", ["deleted", "orchestration_deleted", "missing"])
def test_late_blob_completion_rearms_only_owned_cleanup_after_grace(cleanup_lifecycle, mode, monkeypatch):
    fixture = cleanup_lifecycle
    output = fixture.prepare()
    entered, release = threading.Event(), threading.Event()
    original = fixture.blobs.get_blob_client

    def delayed_blob(*, container, blob):
        client = original(container=container, blob=blob)
        upload = client.upload_blob

        def delayed_upload(stream, **kwargs):
            payload = b"".join(iter(lambda: stream.read(65536), b""))
            entered.set()
            if not release.wait(30):
                raise AssertionError("The late-upload test was not released.")
            with io.BytesIO(payload) as buffered:
                return upload(buffered, **kwargs)

        client.upload_blob = delayed_upload
        return client

    monkeypatch.setattr(fixture.blobs, "get_blob_client", delayed_blob)
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(fixture.run, output)
        try:
            if not entered.wait(30):
                raise AssertionError("The actual uploader did not reach its in-flight storage boundary.")
            delete_conversation(fixture, mode)
            cleanup = cleanup_service(fixture)
            deferred = cleanup.cleanup(output["output_id"])
            fixture.now += timedelta(seconds=11)
            initial = cleanup.cleanup(output["output_id"])
        finally:
            release.set()
        with pytest.raises(OutputUnavailableError):
            future.result(timeout=30)
    pending = fixture.runs.read_item(output["output_id"], "conversation-1")
    due = enumerate_due_outputs(fixture.runs, now=fixture.now)
    final = cleanup.cleanup(output["output_id"])
    saved = fixture.runs.read_item(output["output_id"], "conversation-1")
    assert deferred["cleanup_status"] == "deferred" and initial["cleanup_status"] == "complete"
    assert pending["cleanup_pending"] is True and pending["cleanup_generation"] == 1
    assert pending["state"] == "cancelled" and pending["lease"] is None
    assert any(item["output_id"] == output["output_id"] for item in due)
    assert final["cleanup_status"] == "complete" and not fixture.blobs.data and not fixture.messages.items
    assert saved["attempt_count"] == saved["automatic_attempts"] == 1
    assert len(fixture.render_calls) == fixture.blobs.uploads == fixture.blobs.deletes == 1


def test_cleanup_completion_cannot_overwrite_a_late_io_generation(cleanup_lifecycle, monkeypatch):
    fixture = cleanup_lifecycle
    captured = []
    original_stage = fixture.service._stage

    def capture(claim, record, stream, **kwargs):
        captured.append(claim)
        return original_stage(claim, record, stream, **kwargs)

    monkeypatch.setattr(fixture.service, "_stage", capture)
    output = interrupted_output(fixture)
    record = fixture.raw(output)
    intent = record["intent"]
    address = intent["artifact"]
    key = (address["blob_container"], address["blob_path"])
    payload = fixture.blobs.data[key]
    fixture.service.store.cancel(output["output_id"])
    fixture.now += timedelta(seconds=11)
    cleanup = cleanup_service(fixture)
    original_finish = cleanup.store.finish_cleanup

    def late_io(output_id, *, generation):
        fixture.blobs.data[key] = payload
        fixture.service.store.rearm_staging_cleanup(captured[0], intent["intent_id"])
        return original_finish(output_id, generation=generation)

    with monkeypatch.context() as scoped:
        scoped.setattr(cleanup.store, "finish_cleanup", late_io)
        pending = cleanup.cleanup(output["output_id"])
    finished = cleanup.cleanup(output["output_id"])
    before = fixture.runs.read_item(output["output_id"], "conversation-1")
    with pytest.raises(OutputConflictError):
        fixture.service.store.rearm_staging_cleanup(
            replace(captured[0], token="guessed-guard"), intent["intent_id"],
        )
    after = fixture.runs.read_item(output["output_id"], "conversation-1")
    assert pending["cleanup_status"] == "deferred" and pending["cleanup_pending"] is True
    assert finished["cleanup_status"] == "complete" and before == after
    assert not fixture.blobs.data and not fixture.messages.items


def test_late_staging_notification_never_advances_a_replacement_worker(cleanup_lifecycle):
    fixture = cleanup_lifecycle
    output = fixture.prepare()
    claim = fixture.service.claim_due(output["output_id"], worker_id="original-writer")

    def crash():
        raise Crash("message")

    fixture.messages.after_create = crash
    with pytest.raises(Crash):
        fixture.service.render_attempt(output["output_id"], claim=claim)
    intent_id = fixture.raw(output)["intent"]["intent_id"]
    fixture.now += timedelta(seconds=11)
    replacement = fixture.service.store.claim_due(
        output["output_id"], worker_id="replacement-writer", reconcile_only=True,
    )
    before = fixture.raw(output)
    rearmed = fixture.service.store.rearm_staging_cleanup(claim, intent_id)
    after = fixture.raw(output)
    assert replacement is not None and replacement.token != claim.token
    assert rearmed is False and before == after
    assert after["lease"]["token"] == replacement.token and after["attempt_count"] == 1


@pytest.mark.parametrize("condition", ["denied", "held", "deleted", "storage"])
def test_nested_output_history_without_any_cards_uses_only_current_authority(cleanup_lifecycle, condition):
    fixture = cleanup_lifecycle
    completed = fixture.run(fixture.prepare())
    message = {
        "id": "assistant-without-cards", "conversation_id": "conversation-1", "role": "assistant",
        "content": "Saved delivery summary.",
        "metadata": {"orchestration": {"run_id": "run-1", "outputs": [completed]}},
    }
    original = deepcopy(message)
    if condition == "denied":
        fixture.results.denied.add("document-1")
    elif condition == "held":
        fixture.results.held.add("document-1")
    elif condition == "deleted":
        delete_conversation(fixture, "deleted")
    else:
        fixture.runs.fail_reads = True
    with fixture.app.test_request_context():
        if condition == "storage":
            with pytest.raises(OutputStorageError):
                fixture.modules.sources.sanitize_generated_artifact_history(message, "owner")
        else:
            refreshed = fixture.modules.sources.sanitize_generated_artifact_history(message, "owner")
            outputs = refreshed["metadata"]["orchestration"]["outputs"]
            if condition == "deleted":
                assert outputs == []
            else:
                assert len(outputs) == 1 and outputs[0]["available"] is False
                assert outputs[0]["artifact_message_id"] is None and outputs[0]["can_retry"] is False
                assert outputs[0]["size_bytes"] is None
    assert message == original and len(fixture.render_calls) == 1
