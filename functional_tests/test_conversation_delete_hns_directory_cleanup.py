# test_conversation_delete_hns_directory_cleanup.py
"""
Conversation deletion with real checkpoint and private-result cleanup.
Version: 0.261.306
Implemented in: 0.261.306

Authenticated single/bulk routes exercise hierarchical namespace directory
listings, ordinary Blob listings, retained generated-file enrollment, cleanup
retries, ownership boundaries, and sanitized Application Insights diagnostics.
Only external storage I/O is doubled; no model, source read, or deployment runs.
"""

import hashlib
import importlib
from copy import deepcopy
from unittest.mock import Mock

import pytest
from azure.core.exceptions import ResourceModifiedError, ServiceRequestError

from test_orchestration_cleanup_bootstrap import cleanup_root  # noqa: F401
from test_orchestration_output_cleanup import cleanup_lifecycle, production_modules  # noqa: F401
from test_orchestration_output_deletion_pipeline import (
    advance_cleanup_grace,
    assert_deletion_response,
    cleanup_tick,
    deletion_runtime,  # noqa: F401
    request_deletion,
)


CONVERSATION_ID = "conversation-1"
RUN_ID = "run-1"
PRIVATE_DETAIL = "private-provider-detail https://storage.example.test/?sig=private-token"


@pytest.fixture
def result_deletion_runtime(deletion_runtime, monkeypatch):
    runtime, world = deletion_runtime, deletion_runtime.world
    results = importlib.import_module("functions_workflow_result_store")
    recovery = importlib.import_module("functions_orchestration_recovery")
    telemetry = importlib.import_module("functions_appinsights")
    store = results.WorkflowResultStore(
        container=world.results.container,
        blob_client=world.results.blobs,
        blob_container_name="private-results",
    )
    monkeypatch.setattr(results, "_configured_result_store", lambda *args, **kwargs: store)
    logger = Mock()
    monkeypatch.setattr(telemetry, "get_appinsights_logger", lambda: logger)
    record_error = runtime.routes.log_event

    def record_event(message, **kwargs):
        record_error(message, **kwargs)
        telemetry.log_event(message, **kwargs)

    monkeypatch.setattr(runtime.routes, "log_event", record_event)
    monkeypatch.setattr(recovery, "log_event", record_event)
    runtime.private_store = store
    runtime.private_blobs = world.results.blobs
    runtime.result_module = results
    runtime.recovery = recovery
    runtime.logger = logger
    return runtime


def add_hns_directories(runtime):
    """Place explicit directory entries before their child result files."""
    blobs = runtime.private_blobs
    files = list(blobs.records)
    directories = set()
    blobs.hierarchical = True
    for container, name in files:
        parts = name.split("/")
        scope_depth = 6 if parts[0] == "orchestration-analysis-results" else 5
        for depth in range(scope_depth + 1, len(parts)):
            key = (container, "/".join(parts[:depth]))
            if key in directories:
                continue
            blobs.add_directory(
                key[1], container=container, metadata={"HDI_ISFOLDER": "TrUe"},
            )
            directories.add(key)
    return directories


def seed_chat_result(runtime, *, interrupted=False):
    runtime.private_store.save_chat(
        "owner", CONVERSATION_ID, "analysis-message", {"findings": ["retained chat analysis"]},
    )
    if interrupted:
        message = {
            "id": "analysis-request", "conversation_id": CONVERSATION_ID,
            "role": "user", "user_id": "owner", "content": "Analyze my document.",
            "metadata": {"analysis_attempt_message_id": "analysis-message"},
        }
    else:
        message = {
            "id": "analysis-message", "conversation_id": CONVERSATION_ID,
            "role": "assistant", "content": "Historical analysis.",
            "metadata": {"document_action": {"type": "analyze"}},
        }
    runtime.world.messages.create_item(message)


def cleanup_failure(response, route):
    body = response.get_json()
    return body if route == "single" else body["failures"][0]


def assert_history_preserved(runtime, messages):
    conversation = runtime.world.conversations.read_item(CONVERSATION_ID, CONVERSATION_ID)
    run = runtime.world.runs.read_item(RUN_ID, CONVERSATION_ID)
    guard = runtime.world.cleanup_guards.read_item("checkpoint:lifecycle", RUN_ID)
    assert conversation["orchestration_deleted"] is True
    assert run["checkpoints_deleted"] is True and run["execution_lease"] is None
    assert guard["deleted"] is True and guard["token"] is None
    publication_key = (CONVERSATION_ID, runtime.recovery._publication_id(RUN_ID))
    preserved = {
        key: message for key, message in runtime.world.messages.items.items()
        if key != publication_key
    }
    original = {key: message for key, message in messages.items() if key != publication_key}
    assert preserved == original
    publication = runtime.world.messages.items[publication_key]
    assert publication["user_id"] == "owner" and publication["run_id"] == RUN_ID
    assert publication["role"] == "assistant_artifact" and publication["content"] == ""
    assert publication["token"] is None
    assert publication["metadata"]["orchestration_publication_guard"] is True


def logged_events(runtime, *, stage=None):
    events = [call.kwargs["extra"] for call in runtime.logger.log.call_args_list]
    return events if stage is None else [event for event in events if event.get("sc_stage") == stage]


@pytest.mark.parametrize("route", ["single", "bulk"])
@pytest.mark.parametrize("hierarchical", [False, True])
@pytest.mark.parametrize("without_analyze", [False, True])
def test_owned_results_and_directories_are_removed_before_history(
    result_deletion_runtime, route, hierarchical, without_analyze,
):
    runtime, world = result_deletion_runtime, result_deletion_runtime.world
    output = world.run(world.prepare())
    if without_analyze:
        run = world.runs.read_item(RUN_ID, CONVERSATION_ID)
        run["plan"]["steps"] = [
            step for step in run["plan"]["steps"] if step["capability_id"] != "document_analyze"
        ]
        world.runs.upsert_item(run)
        for step in run["plan"]["steps"]:
            runtime.private_store.save_orchestration(
                "owner", CONVERSATION_ID, RUN_ID, step["step_id"], {"reply": "Retained non-Analyze result."},
            )
    runtime.private_store.save_chat(
        "another-owner", "another-conversation", "another-message", {"findings": ["outside scope"]},
    )
    directories = add_hns_directories(runtime) if hierarchical else set()
    foreign = {
        key: deepcopy(row) for key, row in runtime.private_blobs.records.items()
        if key[1].startswith("chat-analysis-results/")
    }
    owned_keys = set(runtime.private_blobs.records) - set(foreign)
    response = request_deletion(runtime, route)
    assert_deletion_response(response, route, succeeded=True)
    body = response.get_json()
    if route == "bulk":
        assert body["failures"] == []
    remaining = runtime.private_blobs.records
    owned_directories = directories & owned_keys
    assert not owned_keys.intersection(remaining)
    assert all(remaining[key] == row for key, row in foreign.items())
    assert owned_directories.issubset(runtime.private_blobs.deletes)
    assert runtime.private_blobs.deletes
    deleted_files = [key for key in runtime.private_blobs.deletes if key not in directories]
    assert runtime.private_blobs.deletes[:len(deleted_files)] == deleted_files
    assert (CONVERSATION_ID, CONVERSATION_ID) not in world.conversations.items
    parent = world.runs.read_item(RUN_ID, CONVERSATION_ID)
    retained = world.runs.read_item(output["output_id"], CONVERSATION_ID)
    assert parent["output_cleanup"]["state"] == "completed"
    assert retained["state"] == "cancelled" and retained["cleanup_pending"] is True
    assert world.blobs.deletes == 0 and world.blobs.data
    advance_cleanup_grace(world, [output])
    cleaned = cleanup_tick(runtime)
    assert cleaned["ok"] is True and cleaned["counts"]["outputs_processed"] == 1
    assert not world.blobs.data and world.blobs.deletes == 1
    assert len(world.render_calls) == 1


@pytest.mark.parametrize("route", ["single", "bulk"])
@pytest.mark.parametrize("interrupted", [False, True])
def test_chat_analysis_directories_are_cleaned_for_committed_and_interrupted_results(
    result_deletion_runtime, route, interrupted,
):
    runtime = result_deletion_runtime
    seed_chat_result(runtime, interrupted=interrupted)
    directories = add_hns_directories(runtime)
    response = request_deletion(runtime, route)
    assert_deletion_response(response, route, succeeded=True)
    assert not runtime.private_blobs.records
    assert directories.issubset(runtime.private_blobs.deletes)
    assert any(entry["prefix"].startswith("chat-analysis-results/") for entry in runtime.private_blobs.lists)
    assert not runtime.world.messages.items


@pytest.mark.parametrize("route", ["single", "bulk"])
@pytest.mark.parametrize("scope", ["orchestration", "chat"])
@pytest.mark.parametrize("fault", ["stray_file", "unmarked_directory", "nonempty_directory", "misnamed_directory"])
def test_real_unexpected_objects_keep_conversation_deletion_fail_closed(
    result_deletion_runtime, route, scope, fault,
):
    runtime = result_deletion_runtime
    if scope == "chat":
        seed_chat_result(runtime)
    directories = add_hns_directories(runtime)
    family = f"{scope}-analysis-results/"
    directory = next(key for key in directories if key[1].startswith(family))
    if fault == "unmarked_directory":
        runtime.private_blobs.records[directory]["metadata"] = {}
    elif fault == "nonempty_directory":
        runtime.private_blobs.records[directory]["data"] = b"Not a directory."
    else:
        bad_key = (
            directory[0], f"{directory[1].rsplit('/', 1)[0]}/"
            f"{'unexpected.txt' if fault == 'stray_file' else 'unexpected-directory'}",
        )
        bad_row = deepcopy(runtime.private_blobs.records[directory])
        if fault == "stray_file":
            bad_row.update(data=b"Private result bytes.", metadata={}, directory=False)
        runtime.private_blobs.records = {bad_key: bad_row, **runtime.private_blobs.records}
    messages = deepcopy(runtime.world.messages.items)
    response = request_deletion(runtime, route)
    assert_deletion_response(response, route, succeeded=False)
    detail = cleanup_failure(response, route)
    assert detail["code"] == "conversation_execution_integrity_failed"
    assert "administrator" in detail["error"]
    assert_history_preserved(runtime, messages)
    stage = "retained_result_cleanup" if scope == "orchestration" else "chat_analysis_cleanup"
    events = logged_events(runtime, stage=stage)
    assert events and events[-1]["sc_error_type"] == "WorkflowResultIntegrityError"


@pytest.mark.parametrize("route", ["single", "bulk"])
@pytest.mark.parametrize("scope", ["orchestration", "chat"])
@pytest.mark.parametrize("operation", ["listing", "conditional_delete"])
def test_storage_failure_preserves_fences_and_a_retry_completes(
    result_deletion_runtime, route, scope, operation, monkeypatch,
):
    runtime = result_deletion_runtime
    if scope == "chat":
        seed_chat_result(runtime)
    add_hns_directories(runtime)
    blobs = runtime.private_blobs
    original_container = blobs.get_container_client
    original_blob = blobs.get_blob_client
    family = f"{scope}-analysis-results/"

    def container_client(container):
        client = original_container(container)
        listing = client.list_blobs

        def fail_listing(*, name_starts_with, include):
            if name_starts_with.startswith(family):
                raise ServiceRequestError(PRIVATE_DETAIL)
            return listing(name_starts_with=name_starts_with, include=include)

        monkeypatch.setattr(client, "list_blobs", fail_listing)
        return client

    def blob_client(*, container, blob):
        client = original_blob(container=container, blob=blob)
        if blob.startswith(family):
            monkeypatch.setattr(client, "delete_blob", Mock(side_effect=ResourceModifiedError(PRIVATE_DETAIL)))
        return client

    with monkeypatch.context() as unavailable:
        unavailable.setattr(
            blobs, "get_container_client" if operation == "listing" else "get_blob_client",
            container_client if operation == "listing" else blob_client,
        )
        messages = deepcopy(runtime.world.messages.items)
        failed = request_deletion(runtime, route)
        assert_deletion_response(failed, route, succeeded=False)
        detail = cleanup_failure(failed, route)
        assert detail["code"] == "conversation_execution_storage_unavailable"
        assert_history_preserved(runtime, messages)
        body = failed.get_data(as_text=True)
        events = logged_events(runtime)
        assert PRIVATE_DETAIL not in body and "private-token" not in repr(events)
    retried = request_deletion(runtime, route)
    assert_deletion_response(retried, route, succeeded=True)
    assert not runtime.private_blobs.records
    assert not runtime.world.messages.items


@pytest.mark.parametrize("route", ["single", "bulk"])
def test_unauthorized_actor_cannot_start_private_result_cleanup(result_deletion_runtime, route):
    runtime, world = result_deletion_runtime, result_deletion_runtime.world
    add_hns_directories(runtime)
    before = deepcopy((
        world.conversations.items, world.runs.items, world.cleanup_guards.items,
        world.messages.items, runtime.private_blobs.records, world.results.container.items,
    ))
    serializer = runtime.app.session_interface.get_signing_serializer(runtime.app)
    cookie = serializer.dumps({"user": {"oid": "another-owner", "roles": ["Admin"]}})
    runtime.client.set_cookie(runtime.app.config["SESSION_COOKIE_NAME"], cookie)
    response = request_deletion(runtime, route)
    body = response.get_json()
    if route == "single":
        assert response.status_code == 403
    else:
        assert response.status_code == 200 and body["failed_ids"] == [CONVERSATION_ID]
        assert body["failures"][0]["code"] == "conversation_unavailable"
    after = (
        world.conversations.items, world.runs.items, world.cleanup_guards.items,
        world.messages.items, runtime.private_blobs.records, world.results.container.items,
    )
    assert before == after
    assert not runtime.private_blobs.lists and not runtime.private_blobs.deletes


def test_bulk_partial_failure_keeps_existing_fields_and_adds_safe_details(
    result_deletion_runtime,
):
    runtime, world = result_deletion_runtime, result_deletion_runtime.world
    add_hns_directories(runtime)
    runtime.private_blobs.list_error = ServiceRequestError(PRIVATE_DETAIL)
    for conversation_id, owner in (("other-owned", "owner"), ("foreign", "another-owner")):
        world.conversations.create_item({"id": conversation_id, "user_id": owner})
        world.messages.create_item({
            "id": f"{conversation_id}-message", "conversation_id": conversation_id,
            "role": "user", "content": "Historical message.",
        })
    foreign_messages = deepcopy({
        key: value for key, value in world.messages.items.items() if key[0] == "foreign"
    })
    response = runtime.client.post("/api/delete_multiple_conversations", json={
        "conversation_ids": [CONVERSATION_ID, "other-owned", "foreign"],
    })
    body = response.get_json()
    assert response.status_code == 200 and body["success"] is True
    assert body["deleted_count"] == 1 and body["failed_ids"] == [CONVERSATION_ID, "foreign"]
    assert [item["conversation_id"] for item in body["failures"]] == body["failed_ids"]
    assert body["failures"][0]["code"] == "conversation_execution_storage_unavailable"
    assert body["failures"][0]["status_code"] == 503
    assert body["failures"][1]["code"] == "conversation_unavailable"
    assert (CONVERSATION_ID, CONVERSATION_ID) in world.conversations.items
    assert ("other-owned", "other-owned") not in world.conversations.items
    assert ("foreign", "foreign") in world.conversations.items
    assert all(world.messages.items[key] == row for key, row in foreign_messages.items())
    assert PRIVATE_DETAIL not in repr(body) and "private-token" not in repr(logged_events(runtime))


@pytest.mark.parametrize("route", ["single", "bulk"])
def test_cleanup_telemetry_retains_safe_code_status_stage_and_hashed_run(
    result_deletion_runtime, route, monkeypatch,
):
    runtime, world = result_deletion_runtime, result_deletion_runtime.world
    world.run(world.prepare())
    failure = runtime.recovery.RecoveryError(
        PRIVATE_DETAIL, code="output_cleanup_required", status_code=503,
    )
    monkeypatch.setattr(
        runtime.root, "build_orchestration_cleanup_service", Mock(side_effect=failure),
    )
    response = request_deletion(runtime, route)
    assert_deletion_response(response, route, succeeded=False)
    enrollment = logged_events(runtime, stage="output_enrollment")
    boundary = logged_events(runtime, stage="orchestration_cleanup")
    assert len(enrollment) == len(boundary) == 1
    event = enrollment[0]
    assert event["sc_error_type"] == "RecoveryError"
    assert event["sc_failure_code"] == "output_cleanup_required" and event["sc_status_code"] == 503
    assert event["sc_conversation_id_hash"] == hashlib.sha256(CONVERSATION_ID.encode()).hexdigest()
    assert event["sc_run_id_hash"] == hashlib.sha256(RUN_ID.encode()).hexdigest()
    assert boundary[0]["sc_response_status_code"] == 503
    assert boundary[0]["sc_is_bulk_operation"] is (route == "bulk")
    assert "sc_conversation_id" not in event and "sc_run_id" not in event
    assert "private-token" not in repr(logged_events(runtime))
    assert all(call.kwargs["exc_info"] is False for call in runtime.logger.log.call_args_list)
    runtime.logger.exception.assert_not_called()
    body = response.get_data(as_text=True)
    assert PRIVATE_DETAIL not in body


def test_cleanup_diagnostics_drop_provider_codes_invalid_status_and_malformed_codes(
    result_deletion_runtime,
):
    runtime = result_deletion_runtime
    provider_error = ServiceRequestError(PRIVATE_DETAIL)
    provider_error.code = "provider_private_detail"
    provider_error.status_code = True
    provider = runtime.recovery.conversation_cleanup_failure_context(
        provider_error, CONVERSATION_ID, stage="retained_result_cleanup", run_id=RUN_ID,
    )
    invalid = runtime.recovery.conversation_cleanup_failure_context(
        runtime.recovery.RecoveryError(PRIVATE_DETAIL, code=PRIVATE_DETAIL, status_code=700),
        CONVERSATION_ID, stage="retained_result_cleanup",
    )
    assert "failure_code" not in provider and "status_code" not in provider
    assert "failure_code" not in invalid and "status_code" not in invalid
    assert PRIVATE_DETAIL not in repr((provider, invalid))
