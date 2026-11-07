# test_orchestration_output_metadata_reads.py
"""
Keep metadata I/O permission faults distinct from source authorization denial.
Version: 0.261.127
Implemented in: 0.261.127

Actual output services use isolated metadata I/O faults. Public reads must not
publish unavailable-source overlays or cached facts for failed metadata reads,
and must not change stored files, attempts, leases, results or transport state.
"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from content_screening.contracts import DocumentHeldError
from functions_orchestration_output_store import OutputStorageError, OutputUnavailableError
from functions_orchestration_rendering import output_failure, raise_output_read_infrastructure_failure
from functions_orchestration_results import ResultUnavailableError
from test_orchestration_output_lifecycle import lifecycle, production_modules  # noqa: F401
from test_orchestration_render_resume import forbid_execution, persistence_snapshot


@pytest.mark.parametrize("boundary", ["record", "parent", "message"])
@pytest.mark.parametrize("surface", ["read", "list_public_outputs", "committed_artifacts", "history"])
def test_raw_metadata_permission_faults_are_operational(lifecycle, monkeypatch, boundary, surface):
    world = lifecycle
    completed = world.run(world.prepare())
    history = world.output_history(with_cards=True)
    original_history = deepcopy(history)
    error = PermissionError("PRIVATE metadata credential failure")
    target, method = {
        "record": (world.service.store, "get"),
        "parent": (world.service.store, "current_run"),
        "message": (world.service.transport, "read_message"),
    }[boundary]
    failure = Mock(side_effect=error)
    monkeypatch.setattr(target, method, failure)
    observation = SimpleNamespace(world=world, context=SimpleNamespace(), forbidden=None, effect_snapshot=None)
    forbidden = forbid_execution(observation, monkeypatch)
    before = persistence_snapshot(world)
    with pytest.raises(OutputStorageError) as caught:
        if surface == "read":
            world.service.read(completed["output_id"])
        elif surface == "history":
            with world.app.test_request_context():
                world.modules.sources.sanitize_generated_artifact_history(history, "owner")
        else:
            getattr(world.service, surface)("run-1")
    after = persistence_snapshot(world)
    assert caught.value.__cause__ is error
    assert caught.value.code == "output_storage_unavailable" and "PRIVATE" not in str(caught.value)
    assert before == after and history == original_history and not forbidden.call_count
    assert failure.call_count == 1


@pytest.mark.parametrize("boundary", ["enumeration", "record_recheck"])
@pytest.mark.parametrize("surface", ["list_public_outputs", "committed_artifacts"])
def test_metadata_enumeration_and_recheck_cannot_become_source_denials(
    lifecycle, monkeypatch, boundary, surface,
):
    world = lifecycle
    world.run(world.prepare())
    error = PermissionError("PRIVATE metadata enumeration failure")
    read = world.service.store.get
    calls = []

    def recheck(output_id):
        calls.append(output_id)
        if len(calls) == 2:
            raise error
        return read(output_id)

    if boundary == "enumeration":
        monkeypatch.setattr(world.service.store, "list_outputs", Mock(side_effect=error))
    else:
        monkeypatch.setattr(world.service.store, "get", recheck)
    before = persistence_snapshot(world)
    with pytest.raises(OutputStorageError) as caught:
        getattr(world.service, surface)("run-1")
    after = persistence_snapshot(world)
    assert caught.value.__cause__ is error and before == after
    assert len(calls) == (2 if boundary == "record_recheck" else 0)


@pytest.mark.parametrize("boundary", ["record", "parent", "enumeration"])
def test_typed_metadata_denial_is_not_reclassified_as_storage(lifecycle, monkeypatch, boundary):
    world = lifecycle
    completed = world.run(world.prepare())
    denied = OutputUnavailableError("output_conversation_unavailable")
    method = {"record": "get", "parent": "current_run", "enumeration": "list_outputs"}[boundary]
    monkeypatch.setattr(world.service.store, method, Mock(side_effect=denied))
    before = persistence_snapshot(world)
    with pytest.raises(OutputUnavailableError) as caught:
        if boundary == "enumeration":
            world.service.list_public_outputs("run-1")
        else:
            world.service.read(completed["output_id"])
    after = persistence_snapshot(world)
    assert caught.value is denied and before == after


@pytest.mark.parametrize("change", ["foreign_owner", "deleted"])
def test_real_conversation_authorization_remains_denied(lifecycle, change):
    world = lifecycle
    world.run(world.prepare())
    conversation = world.conversations.read_item("conversation-1", "conversation-1")
    conversation.update({"user_id": "someone-else"} if change == "foreign_owner" else {"deleted": True})
    world.conversations.upsert_item(conversation)
    before = persistence_snapshot(world)
    with pytest.raises(OutputUnavailableError) as caught:
        world.service.list_public_outputs("run-1")
    after = persistence_snapshot(world)
    assert caught.value.code == "output_conversation_unavailable" and before == after


@pytest.mark.parametrize("failure_type", [
    PermissionError, ResultUnavailableError, OutputUnavailableError, DocumentHeldError,
])
def test_genuine_source_denials_remain_unavailable_not_operational(lifecycle, failure_type):
    world = lifecycle
    completed = world.run(world.prepare())
    denied = failure_type()
    world.service.authorize_execution = Mock(side_effect=denied)
    before = persistence_snapshot(world)
    current = world.service.list_public_outputs("run-1")
    cards = world.service.committed_artifacts("run-1")
    after = persistence_snapshot(world)
    assert current[0]["output_id"] == completed["output_id"] and current[0]["available"] is False
    assert current[0]["artifact_message_id"] is current[0]["row_count"] is current[0]["size_bytes"] is None
    assert current[0]["can_retry"] is False and cards == [] and before == after


def test_context_free_permission_classification_is_unchanged():
    denied = PermissionError("PRIVATE source denial")
    classified = output_failure(denied)
    raise_output_read_infrastructure_failure(denied)
    assert classified == ("output_access_denied", False)
