# test_orchestration_output_parent_claim.py
"""
Fence output writers across same-token parent continuation claims.
Version: 0.261.127
Implemented in: 0.261.127

Real continuation claims, checkpoint/publication guards, output CAS, rendering,
private transport and reconciliation run over external-I/O doubles.
"""

import importlib
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from azure.core import MatchConditions

from functions_orchestration_output_store import OutputConflictError, parse_time
from test_orchestration_output_lifecycle import Crash, lifecycle, production_modules  # noqa: F401
from test_support.orchestration_revisions import AtomicMemoryContainer


@pytest.fixture
def parent_claims(lifecycle, monkeypatch):
    world = lifecycle
    continuation = importlib.import_module("functions_orchestration_continuation")
    recovery = importlib.import_module("functions_orchestration_recovery")
    checkpoints = AtomicMemoryContainer("run_id")
    monkeypatch.setattr(recovery.run_store, "cosmos_orchestration_runs_container", world.runs)
    monkeypatch.setattr(recovery.run_store, "cosmos_orchestration_run_steps_container", checkpoints)
    monkeypatch.setattr(recovery, "_now", lambda: world.now)
    monkeypatch.setattr(continuation, "_now", lambda: world.now)
    record = world.runs.read_item("run-1", "conversation-1")
    record.update(
        run_id="run-1", turn_id="turn-1", planner_contract_version=2,
        record_type="orchestration_run", started_at=world.now.isoformat(),
        status="waiting", execution_lease=None,
    )
    record["plan"].update({
        "run_id": "run-1", "user_id": "owner", "conversation_id": "conversation-1",
        "turn_id": "turn-1", "plan_id": "plan-1", "planner_contract_version": 2,
    })
    world.runs.upsert_item(record)
    world.add_render_step("json_file")
    leases = []

    def claim_parent():
        claimed = continuation.claim_run_continuation(
            "run-1", "owner", "conversation-1",
            authorize=lambda: world.conversations.read_item("conversation-1", "conversation-1"),
            message_container=world.messages, mode="outputs",
        )
        if claimed is None:
            raise AssertionError("The real parent continuation was not acquired.")
        _, lease = claimed
        leases.append(lease)
        lease.start()
        return lease

    yield SimpleNamespace(world=world, claim=claim_parent, checkpoints=checkpoints)
    for lease in leases:
        lease.close()


def stage_output(world, output, claim):
    def crash():
        raise Crash("Process loss after staging the private artifact message.")

    world.messages.after_create = crash
    with pytest.raises(Crash):
        world.service.render_attempt(output["output_id"], claim=claim)
    return world.raw(output)["intent"]


def test_parent_heartbeat_preserves_the_exact_output_owner(parent_claims):
    world = parent_claims.world
    parent = parent_claims.claim()
    output = world.prepare()
    claim = world.service.claim_due(output["output_id"])
    parent.renew()
    owned = world.service.store.owned(claim)
    world.service.store.renew(claim)
    completed = world.service.render_attempt(output["output_id"], claim=claim)
    assert owned["lease"]["run_token"] == parent.token
    assert owned["lease"]["run_claim_id"] == parent.claim_id
    assert completed["state"] == "completed"
    assert completed["attempt_count"] == completed["automatic_attempts"] == 1
    assert len(world.render_calls) == world.blobs.uploads == 1


@pytest.mark.parametrize("initial_claim_id", [None, "first-owner"])
@pytest.mark.parametrize("operation", ["owned", "renew"])
def test_expired_parent_epoch_fences_a_still_live_output_lease(lifecycle, initial_claim_id, operation):
    world = lifecycle
    parent = {
        "token": "server-attempt-token", "expires_at": (world.now + timedelta(seconds=45)).isoformat(),
    }
    if initial_claim_id is not None:
        parent["claim_id"] = initial_claim_id
    world.change_run(execution_lease=parent)
    world.service.store.lease_seconds = 120
    output = world.prepare()
    claim = world.service.claim_due(output["output_id"], worker_id="original-output-worker")
    original = world.raw(output)
    world.now += timedelta(seconds=46)
    current = world.runs.read_item("run-1", "conversation-1")
    replacement = {key: value for key, value in current.items() if not key.startswith("_")}
    replacement["execution_lease"] = {
        "token": parent["token"], "claim_id": "replacement-owner",
        "expires_at": (world.now + timedelta(seconds=45)).isoformat(),
    }
    world.runs.replace_item(
        "run-1", replacement, etag=current["_etag"], match_condition=MatchConditions.IfNotModified,
    )
    before = deepcopy((world.runs.items, world.messages.items, world.blobs.data))
    with pytest.raises(OutputConflictError):
        getattr(world.service.store, operation)(claim)
    after = world.raw(output)
    assert parse_time(original["lease"]["expires_at"]) > world.now
    assert original["lease"]["run_token"] == replacement["execution_lease"]["token"]
    assert original["lease"]["run_claim_id"] == initial_claim_id
    assert after == original and before == (world.runs.items, world.messages.items, world.blobs.data)
    assert after["attempt_count"] == after["automatic_attempts"] == 1
    assert not world.render_calls and world.blobs.uploads == 0


@pytest.mark.parametrize("operation", [
    "owned", "renew", "prepare", "staging", "commit", "fail", "release",
])
def test_same_token_successor_fences_every_output_write(parent_claims, operation):
    world = parent_claims.world
    original = parent_claims.claim()
    output = world.prepare()
    claim = world.service.claim_due(output["output_id"])
    intent = stage_output(world, output, claim)
    original.close(release=True)
    successor = parent_claims.claim()
    before = deepcopy((world.runs.items, world.messages.items, world.blobs.data, world.results.container.items))
    store = world.service.store
    check = lambda record: world.service._authorize(record, "commit").recheck()
    operations = {
        "owned": lambda: store.owned(claim),
        "renew": lambda: store.renew(claim),
        "prepare": lambda: store.prepare_intent(claim, intent, check=check),
        "staging": lambda: store.register_staging(claim, intent["intent_id"]),
        "commit": lambda: store.commit(claim, intent_id=intent["intent_id"], check=check),
        "fail": lambda: store.fail(
            output["output_id"], code="output_transport_unavailable", retryable=True, claim=claim,
        ),
        "release": lambda: store.release_reconciliation(claim),
    }
    with pytest.raises(OutputConflictError):
        operations[operation]()
    observed = world.service.render_attempt(output["output_id"], claim=claim)
    artifacts = world.service.committed_artifacts("run-1")
    assert successor.token == original.token and successor.claim_id != original.claim_id
    assert before == (world.runs.items, world.messages.items, world.blobs.data, world.results.container.items)
    assert observed["state"] == "rendering" and observed["attempt_count"] == 1 and artifacts == []
    assert len(world.render_calls) == world.blobs.uploads == 1


@pytest.mark.parametrize("previous_parent", [False, True])
@pytest.mark.parametrize("release_successor", [False, True])
def test_parentless_output_cannot_survive_an_intervening_parent_claim(
    parent_claims, previous_parent, release_successor,
):
    world = parent_claims.world
    if previous_parent:
        parent_claims.claim().close(release=True)
    output = world.prepare()
    claim = world.service.claim_due(output["output_id"])
    successor = parent_claims.claim()
    if release_successor:
        successor.close(release=True)
    before = world.raw(output)
    with pytest.raises(OutputConflictError):
        world.service.store.owned(claim)
    with pytest.raises(OutputConflictError):
        world.service.store.renew(claim)
    contender = world.service.claim_due(output["output_id"], worker_id="another-output-worker")
    after = world.raw(output)
    assert contender is None and before == after
    assert before["lease"]["run_token"] is None
    assert not world.render_calls and world.blobs.uploads == 0


def test_parent_claim_cutover_inside_commit_cas_is_rechecked(parent_claims):
    world = parent_claims.world
    original = parent_claims.claim()
    output = world.prepare()
    claim = world.service.claim_due(output["output_id"])
    intent = stage_output(world, output, claim)
    before = world.raw(output)
    successors = []

    def replace_parent():
        original.close(release=True)
        successors.append(parent_claims.claim())

    world.runs.before_batch = replace_parent
    with pytest.raises(OutputConflictError):
        world.service.store.commit(
            claim, intent_id=intent["intent_id"],
            check=lambda record: world.service._authorize(record, "commit").recheck(),
        )
    after = world.raw(output)
    artifacts = world.service.committed_artifacts("run-1")
    assert len(successors) == 1 and successors[0].token == original.token
    assert successors[0].claim_id != original.claim_id
    assert before == after and artifacts == [] and world.blobs.uploads == 1


@pytest.mark.parametrize("boundary", ["before_blob", "after_blob", "after_message"])
def test_parent_takeover_during_transport_never_publishes_a_late_worker(parent_claims, boundary):
    world = parent_claims.world
    original = parent_claims.claim()
    output = world.prepare()
    claim = world.service.claim_due(output["output_id"])
    successors = []

    def replace_parent():
        original.close(release=True)
        successors.append(parent_claims.claim())

    if boundary == "before_blob":
        world.blobs.before_upload = replace_parent
    elif boundary == "after_blob":
        world.blobs.after_upload = replace_parent
    else:
        world.messages.after_create = replace_parent
    observed = world.service.render_attempt(output["output_id"], claim=claim)
    saved = world.raw(output)
    artifacts = world.service.committed_artifacts("run-1")
    assert len(successors) == 1 and successors[0].token == original.token
    assert successors[0].claim_id != original.claim_id
    assert observed["state"] == "rendering" and saved["committed_intent"] is None and artifacts == []
    assert saved["lease"]["run_claim_id"] == original.claim_id
    assert saved["attempt_count"] == saved["automatic_attempts"] == 1
    assert len(world.render_calls) == world.blobs.uploads == 1


def test_committed_output_does_not_depend_on_a_previous_parent_claim(parent_claims):
    world = parent_claims.world
    original = parent_claims.claim()
    completed = world.run(world.prepare())
    before = world.raw(completed)
    original.close(release=True)
    successor = parent_claims.claim()
    current = world.service.read(completed["output_id"])
    artifacts = world.service.committed_artifacts("run-1")
    after = world.raw(completed)
    assert successor.token == original.token and successor.claim_id != original.claim_id
    assert current == completed and before == after and len(artifacts) == 1
    assert len(world.render_calls) == world.blobs.uploads == 1


def test_old_output_lease_without_claim_identity_cannot_adopt_a_live_continuation(parent_claims):
    world = parent_claims.world
    parent_claims.claim()
    output = world.prepare()
    claim = world.service.claim_due(output["output_id"])
    record = world.raw(output)
    record["lease"].pop("run_claim_id")
    world.runs.upsert_item(record)
    before = world.raw(output)
    with pytest.raises(OutputConflictError):
        world.service.store.owned(claim)
    with pytest.raises(OutputConflictError):
        world.service.store.renew(claim)
    after = world.raw(output)
    assert before == after and not world.render_calls and world.blobs.uploads == 0


def test_parentless_takeover_recovery_reuses_bytes_without_duplicate_visibility(parent_claims):
    world = parent_claims.world
    output = world.prepare()
    claim = world.service.claim_due(output["output_id"])
    intent = stage_output(world, output, claim)
    successor = parent_claims.claim()
    successor.close(release=True)
    with pytest.raises(OutputConflictError):
        world.service.store.owned(claim)
    contender = world.service.claim_due(output["output_id"])
    assert contender is None
    world.now += timedelta(seconds=11)
    retry = world.service.reconcile(output["output_id"])
    assert retry["state"] == "retry_scheduled" and retry["automatic_attempts"] == 2
    world.advance_due(retry)
    completed = world.run(output)
    artifacts = world.service.committed_artifacts("run-1")
    assert completed["state"] == "completed" and completed["automatic_attempts"] == 2
    assert len(world.render_calls) == world.blobs.uploads == len(artifacts) == 1
    assert artifacts[0]["artifact_message_id"] == intent["artifact"]["artifact_message_id"]
    with world.service.open_download(output["output_id"]) as stream:
        content = stream.read()
    assert content and world.results.container.sequence == world.producer_writes


@pytest.mark.parametrize("claim_id", ["", " ", False, 0, [], {}])
def test_invalid_parent_claim_identity_cannot_start_output_work(lifecycle, claim_id):
    output = lifecycle.prepare()
    lifecycle.change_run(execution_lease={
        "token": "parent-token", "claim_id": claim_id,
        "expires_at": (lifecycle.now + timedelta(minutes=1)).isoformat(),
    })
    before = lifecycle.raw(output)
    with pytest.raises(OutputConflictError):
        lifecycle.service.claim_due(output["output_id"])
    after = lifecycle.raw(output)
    assert before == after and not lifecycle.render_calls and lifecycle.blobs.uploads == 0


def test_initial_parent_without_claim_id_remains_supported(lifecycle):
    lifecycle.change_run(execution_lease={
        "token": "initial-parent", "expires_at": (lifecycle.now + timedelta(minutes=1)).isoformat(),
    })
    output = lifecycle.prepare()
    claim = lifecycle.service.claim_due(output["output_id"])
    owned = lifecycle.service.store.owned(claim)
    completed = lifecycle.service.render_attempt(output["output_id"], claim=claim)
    assert owned["lease"]["run_claim_id"] is None and completed["state"] == "completed"
