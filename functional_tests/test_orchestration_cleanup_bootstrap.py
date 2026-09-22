# test_orchestration_cleanup_bootstrap.py
"""Exercise the initialized deletion-only composition root against real services.

Version: 0.261.127
Implemented in: 0.261.127

Private storage I/O and the clock are doubled. The root must preserve genuine
conversation deletion/errors, retained ownership, grace periods and live files,
without reading source data or constructing ordinary rendering/identity services.
"""

import importlib
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from functions_orchestration_output_store import OutputStorageError, OutputUnavailableError
from test_orchestration_output_cleanup import (
    cleanup_lifecycle, delete_conversation, interrupted_output, production_modules,  # noqa: F401
)


@pytest.fixture
def cleanup_root(cleanup_lifecycle, monkeypatch):
    world = cleanup_lifecycle
    root = importlib.import_module("functions_orchestration_bootstrap")
    for name, value in {
        "cosmos_orchestration_runs_container": world.runs,
        "cosmos_orchestration_run_steps_container": world.cleanup_guards,
        "cosmos_conversations_container": world.conversations,
        "cosmos_messages_container": world.messages,
        "storage_account_personal_chat_container_name": "chat",
        "CLIENTS": {"storage_account_office_docs_client": world.blobs},
    }.items():
        monkeypatch.setattr(root.config, name, value)
    actual_store = root.OrchestrationOutputStore

    def timed_store(*args, **kwargs):
        return actual_store(*args, **kwargs, clock=lambda: world.now, lease_seconds=10)

    monkeypatch.setattr(root, "OrchestrationOutputStore", timed_store)
    for name in (
        "build_orchestration_services", "build_external_identity_reader",
        "get_settings", "read_orchestration_source_metadata",
    ):
        monkeypatch.setattr(root, name, Mock(side_effect=AssertionError(f"Cleanup called {name}.")))
    return SimpleNamespace(world=world, module=root)


@pytest.mark.parametrize("mode", ["missing", "deleted", "orchestration_deleted"])
@pytest.mark.parametrize("boundary", ["blob", "message"])
def test_root_cleans_actual_deleted_conversations_without_live_or_source_access(cleanup_root, mode, boundary):
    world, root = cleanup_root.world, cleanup_root.module
    output = interrupted_output(world, boundary)
    delete_conversation(world, mode)
    world.results.sources.clear()
    world.results.container.fail_reads = True
    with pytest.raises((OutputUnavailableError, CosmosResourceNotFoundError)):
        root.read_owned_conversation("owner", "conversation-1")
    cleanup = root.build_orchestration_cleanup_service("owner", "conversation-1")
    deferred = cleanup.cleanup(output["output_id"])
    before_cleanup = world.runs.read_item(output["output_id"], "conversation-1")
    world.now += timedelta(seconds=11)
    complete = cleanup.cleanup(output["output_id"])
    repeated = cleanup.cleanup(output["output_id"])
    after_cleanup = world.runs.read_item(output["output_id"], "conversation-1")
    assert deferred["cleanup_status"] == "deferred"
    assert before_cleanup["deleted_at"] and before_cleanup["state"] == "cancelled"
    assert complete["cleanup_status"] == repeated["cleanup_status"] == "complete"
    assert complete["processed_intents"] == 1 and repeated["processed_intents"] == 0
    assert after_cleanup["cleanup_pending"] is False
    assert before_cleanup["automatic_attempts"] == after_cleanup["automatic_attempts"] == 1
    assert not world.blobs.data and not world.messages.items
    assert len(world.render_calls) == world.blobs.uploads == world.blobs.deletes == 1
    assert set(complete) == {"output_id", "state", "cleanup_status", "cleanup_pending", "processed_intents"}


@pytest.mark.parametrize("authority", ["actor", "run", "admission", "conversation_owner"])
def test_root_cannot_turn_missing_or_foreign_authority_into_cleanup_permission(cleanup_root, authority):
    world, root = cleanup_root.world, cleanup_root.module
    output = interrupted_output(world)
    delete_conversation(world, "deleted")
    actor = "owner"
    run = world.runs.read_item("run-1", "conversation-1")
    if authority == "actor":
        actor = "someone-else"
    elif authority == "run":
        world.runs.delete_item("run-1", "conversation-1", etag=run["_etag"])
    elif authority == "admission":
        run["render_output_ids"] = []
        world.runs.upsert_item(run)
    else:
        conversation = world.conversations.read_item("conversation-1", "conversation-1")
        conversation["user_id"] = "someone-else"
        world.conversations.upsert_item(conversation)
    cleanup = root.build_orchestration_cleanup_service(actor, "conversation-1")
    with pytest.raises(OutputUnavailableError):
        cleanup.cleanup(output["output_id"])
    assert world.blobs.deletes == 0 and world.blobs.data and world.messages.items


def test_root_keeps_conversation_storage_failure_distinct_from_a_real_404(cleanup_root):
    world, root = cleanup_root.world, cleanup_root.module
    output = interrupted_output(world)
    world.service.store.cancel(output["output_id"])
    world.now += timedelta(seconds=11)
    world.conversations.fail_reads = True
    cleanup = root.build_orchestration_cleanup_service("owner", "conversation-1")
    with pytest.raises(OutputStorageError):
        cleanup.cleanup(output["output_id"])
    assert world.blobs.deletes == 0 and world.blobs.data and world.messages.items


def test_root_preserves_a_live_committed_file_even_when_its_source_is_unavailable(cleanup_root):
    world, root = cleanup_root.world, cleanup_root.module
    completed = world.run(world.prepare())
    before = world.raw(completed)
    blobs = deepcopy(world.blobs.data)
    messages = deepcopy(world.messages.items)
    world.results.sources.clear()
    world.results.container.fail_reads = True
    cleanup = root.build_orchestration_cleanup_service("owner", "conversation-1")
    result = cleanup.cleanup(completed["output_id"])
    after = world.raw(completed)
    assert result["cleanup_status"] == "complete" and result["processed_intents"] == 0
    assert before == after and world.blobs.deletes == 0
    assert world.blobs.data == blobs and world.messages.items == messages


def test_root_never_treats_a_bare_missing_conversation_as_deletion_authority(cleanup_root):
    world, root = cleanup_root.world, cleanup_root.module
    output = interrupted_output(world)
    before = world.runs.read_item(output["output_id"], "conversation-1")
    delete_conversation(world, "missing", retain_guard=False)
    cleanup = root.build_orchestration_cleanup_service("owner", "conversation-1")
    with pytest.raises(OutputUnavailableError) as raised:
        cleanup.cleanup(output["output_id"])
    after = world.runs.read_item(output["output_id"], "conversation-1")
    assert raised.value.code == "output_cleanup_tombstone_required"
    assert before == after and world.blobs.deletes == 0
    assert world.blobs.data and world.messages.items


def test_root_does_not_substitute_a_deletion_guard_when_its_storage_is_unavailable(cleanup_root):
    world, root = cleanup_root.world, cleanup_root.module
    output = interrupted_output(world)
    delete_conversation(world, "missing")
    world.cleanup_guards.fail_reads = True
    cleanup = root.build_orchestration_cleanup_service("owner", "conversation-1")
    with pytest.raises(OutputStorageError):
        cleanup.cleanup(output["output_id"])
    assert world.blobs.deletes == 0 and world.blobs.data and world.messages.items


def test_root_requires_explicit_withdrawal_before_deleting_a_committed_file(cleanup_root):
    world, root = cleanup_root.world, cleanup_root.module
    completed = world.run(world.prepare())
    delete_conversation(world, "missing")
    world.results.container.fail_reads = True
    cleanup = root.build_orchestration_cleanup_service("owner", "conversation-1")
    preserved = cleanup.cleanup(completed["output_id"])
    before = world.runs.read_item(completed["output_id"], "conversation-1")
    withdrawal = cleanup.tombstone(completed["output_id"])
    deferred = cleanup.cleanup(completed["output_id"])
    world.now += timedelta(seconds=11)
    removed = cleanup.cleanup(completed["output_id"])
    after = world.runs.read_item(completed["output_id"], "conversation-1")
    assert preserved["processed_intents"] == 0 and before["state"] == "completed"
    assert before["deleted_at"] is None and withdrawal["state"] == "cancelled"
    assert deferred["cleanup_status"] == "deferred" and removed["cleanup_status"] == "complete"
    assert after["deleted_at"] and after["committed_intent"] == before["committed_intent"]
    assert not world.blobs.data and not world.messages.items
