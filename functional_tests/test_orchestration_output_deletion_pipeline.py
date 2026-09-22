# test_orchestration_output_deletion_pipeline.py
"""
Exercise authenticated conversation deletion through durable output cleanup.
Version: 0.261.127
Implemented in: 0.261.127

Real routes, recovery, the initialized cleanup factory and the scheduler must
discover admitted files without caller-supplied output IDs. Storage I/O is
doubled; no provider, model, producer replay or permissive artifact factory is
used to make deletion succeed.
"""

import importlib
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Blueprint
from werkzeug.test import Client
from werkzeug.wrappers import Response

from functions_generated_artifact_sources import is_orchestration_artifact_source
from functions_orchestration_checkpoints import CHECKPOINT_VERSION
from functions_orchestration_output_store import OutputUnavailableError, enumerate_due_outputs, parse_time
from test_orchestration_cleanup_bootstrap import cleanup_root  # noqa: F401
from test_orchestration_output_cleanup import (
    cleanup_lifecycle, interrupted_output, production_modules,  # noqa: F401
)
from test_orchestration_output_lifecycle import Crash, MessageContainer
from test_support.orchestration_revisions import AtomicMemoryContainer


def retained_output_message(message):
    return is_orchestration_artifact_source(
        (message.get("metadata") or {}).get("generated_artifact_source"),
    )


@pytest.fixture
def deletion_runtime(cleanup_root, monkeypatch):
    world, root = cleanup_root.world, cleanup_root.module
    routes = importlib.import_module("route_backend_conversations")
    authentication = importlib.import_module("functions_authentication")
    run_store = importlib.import_module("functions_orchestration_runs")
    scheduler = importlib.import_module("functions_orchestration_scheduler")
    monkeypatch.setattr(run_store, "cosmos_orchestration_runs_container", world.runs)
    monkeypatch.setattr(run_store, "cosmos_orchestration_run_steps_container", world.cleanup_guards)
    monkeypatch.setattr(routes, "cosmos_conversations_container", world.conversations)
    monkeypatch.setattr(routes, "cosmos_messages_container", world.messages)
    monkeypatch.setattr(
        routes, "cosmos_archived_conversations_container", AtomicMemoryContainer("id"), raising=False,
    )
    monkeypatch.setattr(routes, "cosmos_archived_messages_container", MessageContainer(), raising=False)
    monkeypatch.setattr(routes, "get_settings", lambda: {"enable_conversation_archiving": False})
    for name in (
        "cancel_m365_conversation_deliveries", "delete_thoughts_for_conversation",
        "archive_thoughts_for_conversation", "log_conversation_archival",
        "log_conversation_deletion", "bump_conversation_cache_version",
    ):
        monkeypatch.setattr(routes, name, Mock())
    deletion_errors = []

    def record_deletion_error(*args, **kwargs):
        error = sys.exception()
        if error is not None:
            deletion_errors.append(error)

    monkeypatch.setattr(routes, "log_event", record_deletion_error)

    def blob_container_client(container):
        def list_blobs(*, name_starts_with, include=None):
            with world.blobs.lock:
                return [
                    SimpleNamespace(name=name, metadata={})
                    for stored_container, name in world.blobs.data
                    if stored_container == container and name.startswith(name_starts_with)
                ]

        return SimpleNamespace(
            list_blobs=list_blobs,
            get_blob_client=lambda blob: world.blobs.get_blob_client(container=container, blob=blob),
        )

    monkeypatch.setattr(world.blobs, "get_container_client", blob_container_client, raising=False)
    run = world.runs.read_item("run-1", "conversation-1")
    run.update(checkpoint_version=CHECKPOINT_VERSION, turn_id="turn-1")
    run["plan"].update(
        planner_contract_version=2, plan_id="plan-1", run_id="run-1",
        conversation_id="conversation-1", user_id="owner", turn_id="turn-1",
    )
    world.runs.upsert_item(run)

    delete_conversation_item = world.conversations.delete_item

    def azure_delete_conversation(item, partition_key, **kwargs):
        if "etag" not in kwargs:
            current = world.conversations.read_item(item, partition_key)
            kwargs["etag"] = current["_etag"]
        return delete_conversation_item(item, partition_key, **kwargs)

    monkeypatch.setattr(world.conversations, "delete_item", azure_delete_conversation)
    delete_message = world.messages.delete_item

    def conditional_artifact_delete(item, partition_key, **kwargs):
        current = world.messages.read_item(item, partition_key)
        if retained_output_message(current) and kwargs.get("etag") != current["_etag"]:
            raise AssertionError("A retained output bypassed conditional intent cleanup.")
        return delete_message(item, partition_key, **kwargs)

    monkeypatch.setattr(world.messages, "delete_item", conditional_artifact_delete)
    app = world.app
    app.config.update(TESTING=True, SECRET_KEY="local-output-deletion-test")
    blueprint = Blueprint("backend_conversations", __name__)
    blueprint.before_request(authentication.user_required_blueprint())
    routes.register_route_backend_conversations(blueprint)
    app.register_blueprint(blueprint)
    client = Client(app, Response)
    serializer = app.session_interface.get_signing_serializer(app)
    cookie = serializer.dumps({"user": {"oid": "owner", "roles": ["Admin"]}})
    client.set_cookie(app.config["SESSION_COOKIE_NAME"], cookie)

    forbidden_live_access = Mock(side_effect=AssertionError(
        "Deleted-output cleanup entered ordinary execution or source access.",
    ))
    execution = importlib.import_module("functions_orchestration_execution")
    continuation = importlib.import_module("functions_orchestration_continuation")
    for name in ("prepare_harness_execution", "refresh_harness_delivery", "finalize_harness_failure"):
        monkeypatch.setattr(execution, name, forbidden_live_access)
    for name in ("claim_run_continuation", "reconcile_run_outputs"):
        monkeypatch.setattr(continuation, name, forbidden_live_access)

    def cleanup_factory(user_id, conversation_id):
        service = root.build_orchestration_cleanup_service(user_id, conversation_id)
        service.store.clock = lambda: world.now
        return service

    logs = []
    resources = scheduler.OrchestrationSchedulerResources(
        runs_container=world.runs, messages_container=world.messages, settings={},
        read_conversation=forbidden_live_access, read_run=forbidden_live_access,
        build_services=forbidden_live_access,
        build_cleanup_service=cleanup_factory,
        log=lambda message, **kwargs: logs.append((message, kwargs)), clock=lambda: world.now,
    )
    yield SimpleNamespace(
        world=world, root=root, routes=routes, app=app, client=client,
        scheduler=scheduler, resources=resources, deletion_errors=deletion_errors, logs=logs,
    )
    if forbidden_live_access.call_count:
        raise AssertionError("Deletion cleanup attempted forbidden live execution.")


def request_deletion(runtime, route):
    runtime.deletion_errors.clear()
    if route == "single":
        response = runtime.client.delete("/api/conversations/conversation-1")
    else:
        response = runtime.client.post(
            "/api/delete_multiple_conversations", json={"conversation_ids": ["conversation-1"]},
        )
    response.deletion_errors = list(runtime.deletion_errors)
    return response


def assert_deletion_response(response, route, *, succeeded):
    body = response.get_json()
    if succeeded and response.deletion_errors:
        raise AssertionError(body) from response.deletion_errors[-1]
    if route == "single":
        assert response.status_code == (200 if succeeded else 503), body
        if succeeded:
            assert body["success"] is True
    else:
        assert response.status_code == 200, body
        assert body["deleted_count"] == int(succeeded)
        assert body["failed_ids"] == ([] if succeeded else ["conversation-1"])


def cleanup_tick(runtime, *, max_cleanup_runs=0):
    return runtime.scheduler.check_due_orchestration_runs_once(
        max_runs=0, max_outputs=8, max_cleanup_runs=max_cleanup_runs, resources=runtime.resources,
    )


def advance_cleanup_grace(world, outputs):
    records = [world.runs.read_item(output["output_id"], "conversation-1") for output in outputs]
    if not records or any(not record.get("cleanup_pending") or not record.get("cleanup_after") for record in records):
        raise AssertionError("Deletion did not persist per-file cleanup scheduling and grace.")
    cleanup_times = [parse_time(record["cleanup_after"]) for record in records]
    world.now = max(world.now, *cleanup_times) + timedelta(seconds=1)


@pytest.mark.parametrize("route", ["single", "bulk"])
@pytest.mark.parametrize("state", ["completed", "blob", "message"])
def test_real_deletion_discovers_and_schedules_admitted_outputs(deletion_runtime, route, state):
    runtime, world = deletion_runtime, deletion_runtime.world
    output = world.run(world.prepare()) if state == "completed" else interrupted_output(world, state)
    before = world.raw(output)
    initial_selectors = enumerate_due_outputs(world.runs, now=world.now)
    assert initial_selectors == []
    assert before["cleanup_pending"] is False
    authority_calls = list(world.authorization_calls)
    world.results.sources.clear()
    world.results.container.fail_reads = True

    response = request_deletion(runtime, route)
    assert_deletion_response(response, route, succeeded=True)
    queued = world.runs.read_item(output["output_id"], "conversation-1")
    parent = world.runs.read_item("run-1", "conversation-1")
    guard = world.cleanup_guards.read_item("checkpoint:lifecycle", "run-1")
    assert ("conversation-1", "conversation-1") not in world.conversations.items
    assert parent["checkpoints_deleted"] is True and guard["deleted"] is True
    assert guard["token"] is None and guard["user_id"] == "owner"
    assert queued["state"] == "cancelled" and queued["deleted_at"]
    assert queued["cleanup_pending"] is True and queued["lease"] is None
    assert queued["committed_intent"] == before["committed_intent"]
    assert queued["attempt_count"] == before["attempt_count"] == 1
    assert queued["automatic_attempts"] == before["automatic_attempts"] == 1
    assert world.blobs.deletes == 0 and world.blobs.data
    with pytest.raises(OutputUnavailableError):
        world.service.read(output["output_id"])

    advance_cleanup_grace(world, [output])
    selectors = enumerate_due_outputs(world.runs, now=world.now)
    assert [item["output_id"] for item in selectors] == [output["output_id"]]
    cleaned = cleanup_tick(runtime)
    repeated = cleanup_tick(runtime)
    saved = world.runs.read_item(output["output_id"], "conversation-1")
    retained_guard = world.cleanup_guards.read_item("checkpoint:lifecycle", "run-1")
    assert cleaned["ok"] is True and cleaned["counts"]["output_selectors"] == 1, cleaned
    assert cleaned["counts"]["outputs_processed"] == 1
    assert cleaned["counts"]["cleanup_run_selectors"] == cleaned["counts"]["cleanup_runs_enrolled"] == 0
    assert cleaned["counts"]["runs_executed"] == 0
    assert repeated["ok"] is True and repeated["counts"]["output_selectors"] == 0, repeated
    assert saved["state"] == "cancelled" and saved["cleanup_pending"] is False
    assert retained_guard["deleted"] is True
    assert not world.blobs.data and not any(retained_output_message(item) for item in world.messages.items.values())
    assert world.authorization_calls == authority_calls
    assert len(world.render_calls) == world.blobs.uploads == world.blobs.deletes == 1


@pytest.mark.parametrize("route", ["single", "bulk"])
def test_deletion_uses_admissions_when_history_has_no_file_cards(deletion_runtime, route):
    runtime, world = deletion_runtime, deletion_runtime.world
    completed = [world.run(world.prepare("json")), world.run(world.prepare("csv"))]
    world.messages.create_item({
        "id": "card-free-history", "conversation_id": "conversation-1",
        "role": "assistant", "content": "The requested files were generated.",
        "metadata": {"orchestration": {"run_id": "run-1", "outputs": []}},
    })
    response = request_deletion(runtime, route)
    assert_deletion_response(response, route, succeeded=True)
    advance_cleanup_grace(world, completed)
    selectors = enumerate_due_outputs(world.runs, now=world.now)
    assert {item["output_id"] for item in selectors} == {item["output_id"] for item in completed}
    cleaned = cleanup_tick(runtime)
    assert cleaned["ok"] is True and cleaned["counts"]["output_selectors"] == 2, cleaned
    assert cleaned["counts"]["outputs_processed"] == 2 and cleaned["counts"]["cleanup_runs_enrolled"] == 0
    assert not world.blobs.data and world.blobs.deletes == 2
    assert len(world.render_calls) == world.blobs.uploads == 2


@pytest.mark.parametrize("route", ["single", "bulk"])
def test_another_actor_cannot_enqueue_owned_files_for_deletion(deletion_runtime, route):
    runtime, world = deletion_runtime, deletion_runtime.world
    output = world.run(world.prepare())
    before = deepcopy((world.runs.items, world.messages.items, world.conversations.items, world.blobs.data))
    serializer = runtime.app.session_interface.get_signing_serializer(runtime.app)
    cookie = serializer.dumps({"user": {"oid": "someone-else", "roles": ["Admin"]}})
    runtime.client.set_cookie(runtime.app.config["SESSION_COOKIE_NAME"], cookie)
    response = request_deletion(runtime, route)
    if route == "single":
        assert response.status_code == 403
    else:
        assert_deletion_response(response, route, succeeded=False)
    after = (world.runs.items, world.messages.items, world.conversations.items, world.blobs.data)
    saved = world.runs.read_item(output["output_id"], "conversation-1")
    assert before == after and saved["cleanup_pending"] is False
    assert world.blobs.deletes == 0 and len(world.render_calls) == 1


@pytest.mark.parametrize("route", ["single", "bulk"])
@pytest.mark.parametrize("boundary", ["output_fence", "checkpoint_fence"])
def test_failed_deletion_fences_prevent_purge_and_can_be_retried(deletion_runtime, route, boundary):
    runtime, world = deletion_runtime, deletion_runtime.world
    output = world.run(world.prepare())
    if boundary == "output_fence":
        world.runs.fail_batch_at = 1
    else:
        world.cleanup_guards.fail_writes = True
    failed = request_deletion(runtime, route)
    assert_deletion_response(failed, route, succeeded=False)
    conversation = world.conversations.read_item("conversation-1", "conversation-1")
    saved = world.runs.read_item(output["output_id"], "conversation-1")
    assert conversation["orchestration_deleted"] is True
    assert saved["state"] == "completed" and not saved["deleted_at"]
    assert world.blobs.deletes == 0 and world.blobs.data
    with pytest.raises(OutputUnavailableError):
        world.service.read(output["output_id"])
    world.runs.fail_batch_at = None
    world.cleanup_guards.fail_writes = False
    retried = request_deletion(runtime, route)
    assert_deletion_response(retried, route, succeeded=True)
    advance_cleanup_grace(world, [output])
    cleaned = cleanup_tick(runtime)
    assert cleaned["ok"] is True and cleaned["counts"]["output_selectors"] == 1, cleaned
    assert not world.blobs.data and world.blobs.deletes == 1


@pytest.mark.parametrize("route", ["single", "bulk"])
@pytest.mark.parametrize("boundary", ["parent_ack", "source_cleanup", "output_ack"])
def test_interrupted_deletion_enrollment_is_replayed_without_another_delete_request(
    deletion_runtime, route, boundary, monkeypatch,
):
    runtime, world = deletion_runtime, deletion_runtime.world
    outputs = [world.run(world.prepare("json")), world.run(world.prepare("csv"))]
    original = {output["output_id"]: world.raw(output) for output in outputs}
    initial_selectors = enumerate_due_outputs(world.runs, now=world.now)
    assert initial_selectors == []
    authority_calls = list(world.authorization_calls)
    interrupted = False
    if boundary == "parent_ack":
        replace_run = world.runs.replace_item

        def lose_parent_ack(*args, **kwargs):
            nonlocal interrupted
            saved = replace_run(*args, **kwargs)
            if not interrupted and saved["id"] == "run-1" and saved.get("checkpoints_deleted") is True:
                interrupted = True
                raise Crash("The parent deletion fence committed before its acknowledgment was lost.")
            return saved

        monkeypatch.setattr(world.runs, "replace_item", lose_parent_ack)
    elif boundary == "output_ack":
        output_batch = world.runs.execute_item_batch

        def lose_output_ack(*args, **kwargs):
            nonlocal interrupted
            saved = output_batch(*args, **kwargs)
            records = [
                world.runs.read_item(output_id, "conversation-1") for output_id in original
            ]
            if not interrupted and any(record.get("deleted_at") for record in records):
                interrupted = True
                raise Crash("An output deletion fence committed before its acknowledgment was lost.")
            return saved

        monkeypatch.setattr(world.runs, "execute_item_batch", lose_output_ack)
    else:
        native_results = importlib.import_module("functions_workflow_result_store")

        def lose_source_cleanup(*args, **kwargs):
            nonlocal interrupted
            interrupted = True
            raise Crash("The process stopped at retained source cleanup.")

        monkeypatch.setattr(native_results, "delete_orchestration_analysis_results", lose_source_cleanup)

    with pytest.raises(Crash):
        request_deletion(runtime, route)
    parent = world.runs.read_item("run-1", "conversation-1")
    conversation = world.conversations.read_item("conversation-1", "conversation-1")
    before_replay = [world.runs.read_item(output_id, "conversation-1") for output_id in original]
    assert interrupted and parent["checkpoints_deleted"] is True
    assert conversation["orchestration_deleted"] is True and world.blobs.deletes == 0
    intent = parent.get("output_cleanup")
    assert type(intent) is dict and set(intent) == {"version", "state", "retain_committed", "output_ids"}
    assert intent["version"] == 1 and intent["retain_committed"] is False
    assert intent["output_ids"] == parent["render_output_ids"] == [output["output_id"] for output in outputs]
    assert intent["state"] in {"pending", "completed"}
    if boundary == "parent_ack":
        assert intent["state"] == "pending"
        assert all(record["state"] == "completed" and not record["cleanup_pending"] for record in before_replay)
    world.results.sources.clear()
    world.results.container.fail_reads = True
    first = cleanup_tick(runtime, max_cleanup_runs=1)
    assert first["ok"] is True, (first, runtime.logs)
    assert first["counts"]["cleanup_run_selectors"] == first["counts"]["cleanup_runs_enrolled"] == (
        int(intent["state"] == "pending")
    )
    advance_cleanup_grace(world, outputs)
    second = cleanup_tick(runtime)
    saved = [world.runs.read_item(output_id, "conversation-1") for output_id in original]
    assert first["ok"] is True and second["ok"] is True, (first, second)
    assert first["counts"]["runs_executed"] == second["counts"]["runs_executed"] == 0
    assert second["counts"]["output_selectors"] == second["counts"]["outputs_processed"] == 2
    retained_parent = world.runs.read_item("run-1", "conversation-1")
    assert retained_parent["output_cleanup"] == {**intent, "state": "completed"}
    assert retained_parent["render_output_ids"] == parent["render_output_ids"]
    assert all(record["state"] == "cancelled" and record["deleted_at"] for record in saved)
    assert all(record["cleanup_pending"] is False for record in saved)
    assert all(
        record["attempt_count"] == record["automatic_attempts"] == 1
        and record["committed_intent"] == original[record["id"]]["committed_intent"]
        for record in saved
    )
    assert world.authorization_calls == authority_calls
    assert len(world.render_calls) == world.blobs.uploads == world.blobs.deletes == 2
    assert not world.blobs.data and not any(retained_output_message(item) for item in world.messages.items.values())


@pytest.mark.parametrize("route", ["single", "bulk"])
def test_missing_admitted_output_is_not_successful_conversation_cleanup(deletion_runtime, route):
    runtime, world = deletion_runtime, deletion_runtime.world
    output = world.run(world.prepare())
    before = world.raw(output)
    world.runs.delete_item(output["output_id"], "conversation-1", etag=before["_etag"])
    response = request_deletion(runtime, route)
    assert_deletion_response(response, route, succeeded=False)
    conversation = world.conversations.read_item("conversation-1", "conversation-1")
    assert conversation["orchestration_deleted"] is True
    assert world.blobs.deletes == 0 and world.blobs.data
    assert ("conversation-1", output["output_id"]) not in world.runs.items


@pytest.mark.parametrize("route", ["single", "bulk"])
def test_legacy_chat_upload_deletion_does_not_enter_the_output_factory(deletion_runtime, route, monkeypatch):
    runtime, world = deletion_runtime, deletion_runtime.world
    run = world.runs.read_item("run-1", "conversation-1")
    run["plan"]["planner_contract_version"] = 1
    world.runs.upsert_item(run)
    world.blobs.data[("chat", "legacy-upload")] = b"ordinary uploaded bytes"
    world.messages.create_item({
        "id": "legacy-upload", "conversation_id": "conversation-1", "role": "file",
        "file_name": "ordinary.txt", "file_content_source": "blob",
        "blob_container": "chat", "blob_path": "legacy-upload",
    })
    forbidden = Mock(side_effect=AssertionError("Legacy deletion initialized retained-output cleanup."))
    monkeypatch.setattr(runtime.root, "build_orchestration_cleanup_service", forbidden)
    response = request_deletion(runtime, route)
    assert_deletion_response(response, route, succeeded=True)
    assert forbidden.call_count == 0 and not world.blobs.data and world.blobs.deletes == 1
    assert len(world.render_calls) == world.blobs.uploads == 0


@pytest.mark.parametrize("route", ["single", "bulk"])
def test_archival_policy_preserves_committed_siblings_while_cleaning_staging(
    deletion_runtime, route, monkeypatch,
):
    runtime, world = deletion_runtime, deletion_runtime.world
    monkeypatch.setattr(runtime.routes, "get_settings", lambda: {"enable_conversation_archiving": True})
    completed = world.run(world.prepare("csv"))
    staged = interrupted_output(world)
    before = world.raw(completed)
    committed_message = world.messages.read_item(completed["artifact_message_id"], "conversation-1")
    descriptor = before["committed_intent"]["artifact"]
    blob_key = (descriptor["blob_container"], descriptor["blob_path"])
    committed_bytes = world.blobs.data[blob_key]
    authority_calls = list(world.authorization_calls)
    world.results.sources.clear()
    world.results.container.fail_reads = True

    response = request_deletion(runtime, route)
    assert_deletion_response(response, route, succeeded=True)
    parent = world.runs.read_item("run-1", "conversation-1")
    assert parent["output_cleanup"] == {
        "version": 1, "state": "completed", "retain_committed": True,
        "output_ids": parent["render_output_ids"],
    }
    advance_cleanup_grace(world, [staged])
    cleaned = cleanup_tick(runtime)
    assert cleaned["ok"] is True and cleaned["counts"]["cleanup_runs_enrolled"] == 0, (cleaned, runtime.logs)
    assert cleaned["counts"]["output_selectors"] == cleaned["counts"]["outputs_processed"] == 1
    after = world.runs.read_item(completed["output_id"], "conversation-1")
    staged_after = world.runs.read_item(staged["output_id"], "conversation-1")
    message_after = world.messages.read_item(completed["artifact_message_id"], "conversation-1")
    assert after == before and message_after == committed_message
    assert staged_after["state"] == "cancelled" and staged_after["cleanup_pending"] is False
    assert world.blobs.data == {blob_key: committed_bytes} and world.blobs.deletes == 1
    assert world.authorization_calls == authority_calls
    assert len(world.render_calls) == world.blobs.uploads == 2


@pytest.mark.parametrize("route", ["single", "bulk"])
def test_actual_deletion_reconciles_an_upload_finishing_after_cleanup(deletion_runtime, route):
    runtime, world = deletion_runtime, deletion_runtime.world
    output = world.prepare()
    upload_entered, release_upload = threading.Event(), threading.Event()

    def buffered_upload():
        upload_entered.set()
        if not release_upload.wait(timeout=15):
            raise AssertionError("The controlled upload was not released.")

    world.blobs.before_upload = buffered_upload
    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(world.run, output)
        try:
            entered = upload_entered.wait(timeout=10)
            assert entered
            response = request_deletion(runtime, route)
            assert_deletion_response(response, route, succeeded=True)
            advance_cleanup_grace(world, [output])
            first = cleanup_tick(runtime)
            before_acknowledgment = world.runs.read_item(output["output_id"], "conversation-1")
            assert first["ok"] is True and first["counts"]["output_selectors"] == 1, first
            assert before_acknowledgment["cleanup_pending"] is False and not world.blobs.data
        finally:
            release_upload.set()
        with pytest.raises(OutputUnavailableError):
            writer.result(timeout=10)

    after_acknowledgment = world.runs.read_item(output["output_id"], "conversation-1")
    assert after_acknowledgment["state"] == "cancelled" and after_acknowledgment["cleanup_pending"] is True
    assert after_acknowledgment["cleanup_generation"] > before_acknowledgment.get("cleanup_generation", 0)
    advance_cleanup_grace(world, [output])
    second = cleanup_tick(runtime)
    saved = world.runs.read_item(output["output_id"], "conversation-1")
    assert second["ok"] is True and second["counts"]["output_selectors"] == 1, second
    assert saved["cleanup_pending"] is False and saved["state"] == "cancelled"
    assert saved["attempt_count"] == saved["automatic_attempts"] == 1
    assert len(world.render_calls) == world.blobs.uploads == world.blobs.deletes == 1
    assert not world.blobs.data and not any(retained_output_message(item) for item in world.messages.items.values())
