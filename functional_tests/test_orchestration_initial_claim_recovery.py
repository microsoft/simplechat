# test_orchestration_initial_claim_recovery.py
"""Initial V2 claims survive interruption before the first execution checkpoint.

Version: 0.261.129
Implemented in: 0.261.129
Real claims, preparation, scheduler and checkpoint owners run with external I/O
doubled. Tests never fabricate an initial deadline or substitute checkpoint owners.
"""

import importlib
import subprocess
import sys
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from azure.core import MatchConditions
from azure.core.exceptions import ServiceResponseError

from test_orchestration_continuation import claim, replace_record
from test_orchestration_harness_scheduler import harness, initialized_continuation, tick  # noqa: F401


@contextmanager
def resumed_before_checkpoint(harness, *, default_factory=False):
    harness.create(
        replies=["Recovered prepared content."],
        final_response=harness.helpers.input_binding("prepare"),
    )
    initial = harness.prepare()
    before = harness.read()
    initial.close()
    owned = claim(harness, mode="execute")
    if owned is None:
        raise AssertionError("The interrupted attempt was not reclaimed.")
    record, lease = owned
    execution = harness.execution.prepare_harness_execution(
        record, settings=harness.settings, lease=lease,
        checkpoint_factory=None if default_factory else harness.continuation.ContinuationCheckpoints,
    )
    try:
        yield before, execution
    finally:
        execution.close()


@pytest.fixture
def execution_clock(harness, monkeypatch):
    current = [datetime.now(timezone.utc)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current[0].astimezone(tz) if tz is not None else current[0].replace(tzinfo=None)

    for module in (harness.revisions, harness.recovery, harness.continuation):
        monkeypatch.setattr(module, "_now", lambda: current[0])
    for module in (
        harness.execution, importlib.import_module("functions_orchestration_executor"),
    ):
        monkeypatch.setattr(module, "datetime", Clock)
    return current


@pytest.mark.parametrize("configured, expected", [
    (173, 173),
    ("173", 173),
    (None, 600),
    (0, 600),
    (-2, 600),
    ("invalid", 600),
    ([], 600),
])
def test_initial_claim_persists_the_deadline_in_its_own_conditional_write(
    harness, monkeypatch, configured, expected,
):
    harness.settings["chat_orchestration_total_timeout_seconds"] = configured
    harness.create()
    writes = []
    replace_item = harness.runs.replace_item

    def capture(item, body, **kwargs):
        saved = replace_item(item=item, body=body, **kwargs)
        writes.append(deepcopy(saved))
        return saved

    monkeypatch.setattr(harness.runs, "replace_item", capture)
    record, lease = harness.claim()
    harness.continuation_leases.append(lease)
    saved = harness.read()
    assert len(writes) == 1
    assert writes[0] == saved == record
    assert isinstance(record.get("execution_deadline_at"), str)
    started = datetime.fromisoformat(record["started_at"])
    deadline = datetime.fromisoformat(record["execution_deadline_at"])
    assert (deadline - started).total_seconds() == expected
    assert started.utcoffset() is not None and deadline.utcoffset() is not None
    assert record["status"] == "running" and record["execution_lease"]["token"] == lease.token
    assert not record.get("execution_binding") and not record.get("execution_steps")
    assert harness.model_calls == [] and harness.clients == []
    assert harness.blobs.file_uploads == 0


@pytest.mark.parametrize("stage", ["claimed", "prepared"])
def test_scheduler_recovers_an_interruption_before_first_checkpoint(harness, stage):
    harness.settings["chat_orchestration_total_timeout_seconds"] = 173
    harness.create(
        replies=["Recovered prepared content."],
        final_response=harness.helpers.input_binding("prepare"),
    )
    if stage == "prepared":
        execution = harness.prepare()
        before = harness.read()
        context_deadline = execution.context.execution_deadline_at
        execution.close()
    else:
        before, lease = harness.claim()
        context_deadline = before.get("execution_deadline_at")
        lease.close(release=True)

    closed_clients = list(harness.clients)
    assert not before.get("execution_binding") and not before.get("execution_steps")
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0
    assert all(client.closed for client in closed_clients)
    result, _, _ = tick(harness)
    saved = harness.read()
    assert result["ok"], result["errors"]
    assert result["counts"]["runs_executed"] == 1
    assert saved["status"] == "completed" and saved["message_saved"] is True
    assert saved["started_at"] == before["started_at"]
    assert saved["execution_deadline_at"] == before["execution_deadline_at"] == context_deadline
    assert saved["attempt_index"] == before["attempt_index"] == 1
    assert saved["checkpoint_version"] == harness.recovery.CHECKPOINT_VERSION
    assert saved["execution_binding"] and saved["task_results"]["prepare"]["status"] == "complete"
    assert len(harness.model_calls) == 1 and harness.blobs.file_uploads == 0
    assert all(client.closed for client in harness.clients)


@pytest.mark.parametrize("default_factory", [False, True])
def test_first_binding_reconciles_lost_acknowledgement_and_freezes_exact_value(
    harness, monkeypatch, default_factory,
):
    with resumed_before_checkpoint(harness, default_factory=default_factory) as (before, execution):
        original = deepcopy(execution.lease.original)
        writes = []
        replace_item = harness.runs.replace_item

        def lose_acknowledgement(item, body, **kwargs):
            previous = harness.runs.read_item(item, body["conversation_id"])
            saved = replace_item(item=item, body=body, **kwargs)
            if previous.get("execution_binding") is None and body.get("execution_binding") is not None:
                writes.append(deepcopy(saved))
                assert harness.model_calls == [] and harness.blobs.file_uploads == 0
                raise ServiceResponseError("Private first-binding acknowledgement was lost.")
            return saved

        monkeypatch.setattr(harness.runs, "replace_item", lose_acknowledgement)
        execution.execute()
        saved = harness.read()
        original["execution_binding"] = saved.get("execution_binding")
        assert len(writes) == 1
        assert execution.lease.original == original
        assert saved["execution_binding"] == writes[0]["execution_binding"]
        assert saved["status"] == "completed" and saved["message_saved"] is True
        assert saved["started_at"] == before["started_at"]
        assert saved["execution_deadline_at"] == before["execution_deadline_at"]
        assert len(harness.model_calls) == 1 and harness.blobs.file_uploads == 0


@pytest.mark.parametrize("race", ["takeover", "cancel", "delete", "foreign_binding", "progress"])
def test_first_binding_cas_cannot_overwrite_a_concurrent_owner_or_stop(harness, monkeypatch, race):
    with resumed_before_checkpoint(harness) as (_, execution):
        checkpoints = harness.continuation.ContinuationCheckpoints(
            execution.record, execution.context, harness.settings, execution.lease,
        )
        replace_item = harness.runs.replace_item
        raced = []
        winners = []

        def change_owner(item, body, **kwargs):
            if item == "run-1" and body.get("execution_binding") == checkpoints.binding and not raced:
                raced.append(race)
                if race == "takeover":
                    execution.lease.close(release=True)
                    winner = claim(harness, mode="execute")
                    if winner is None:
                        raise AssertionError("The competing owner did not acquire its claim.")
                    winner[1].start()
                    winners.append(winner)
                elif race == "cancel":
                    harness.recovery.request_cancellation(
                        "run-1", "owner", "conversation-1", execution.lease.authorize,
                    )
                elif race == "delete":
                    def authorize_cleanup():
                        conversation = harness.conversations.read_item("conversation-1", "conversation-1")
                        if conversation["user_id"] != "owner":
                            raise PermissionError("The deletion actor no longer owns the conversation.")
                        return conversation

                    harness.recovery.cleanup_conversation_checkpoints(
                        "conversation-1", "owner", authorize_cleanup,
                        conversation_container=harness.conversations, message_container=harness.messages,
                    )
                else:
                    updates = (
                        {"execution_binding": "f" * 64} if race == "foreign_binding"
                        else {"execution_steps": [{"step_id": "prepare", "status": "running"}]}
                    )
                    replace_record(harness.runs, "run-1", "conversation-1", **updates)
            return replace_item(item=item, body=body, **kwargs)

        monkeypatch.setattr(harness.runs, "replace_item", change_owner)
        with pytest.raises((
            harness.recovery.CheckpointError, harness.recovery.RecoveryError,
            harness.bootstrap.OutputUnavailableError,
        )):
            checkpoints.initialize()
        saved = harness.read()
        assert raced == [race]
        assert execution.lease.original["execution_binding"] is None
        assert saved.get("execution_binding") == ("f" * 64 if race == "foreign_binding" else None)
        assert harness.model_calls == [] and harness.blobs.file_uploads == 0
        if race == "takeover":
            assert saved["execution_lease"]["claim_id"] == winners[0][1].claim_id
        elif race == "cancel":
            assert saved["cancellation_requested_at"]
        elif race == "delete":
            assert saved["checkpoints_deleted"] is True


@pytest.mark.parametrize("field", ["execution_binding", "execution_deadline_at", "attempt_index", "plan"])
def test_adopting_first_binding_does_not_relax_subsequent_immutable_reads(harness, field):
    with resumed_before_checkpoint(harness) as (_, execution):
        checkpoints = harness.continuation.ContinuationCheckpoints(
            execution.record, execution.context, harness.settings, execution.lease,
        )
        checkpoints.initialize()
        saved = execution.lease.read()
        if field == "execution_binding":
            changed = "f" * 64
        elif field == "execution_deadline_at":
            changed = (datetime.fromisoformat(saved[field]) + timedelta(seconds=1)).isoformat()
        elif field == "attempt_index":
            changed = saved[field] + 1
        else:
            changed = deepcopy(saved[field])
            changed["steps"][0]["arguments"]["instruction"] = "A different plan."
        replace_record(harness.runs, "run-1", "conversation-1", **{field: changed})
        with pytest.raises(harness.recovery.CheckpointError) as raised:
            execution.lease.read()
        assert raised.value.code == "ownership_lost"
        assert harness.model_calls == [] and harness.blobs.file_uploads == 0


@pytest.mark.parametrize("value, expected_code", [
    (None, "checkpoint_unavailable"),
    ("missing", "checkpoint_unavailable"),
    ("not-a-timestamp", "scheduler_invalid_state"),
    ("2030-01-01T00:00:00", "scheduler_invalid_state"),
])
def test_scheduler_does_not_invent_timing_for_an_invalid_saved_claim(harness, value, expected_code):
    harness.create()
    record, lease = harness.claim()
    lease.close(release=True)
    if value == "missing":
        current = harness.read()
        current.pop("execution_deadline_at")
        harness.runs.replace_item(
            item="run-1", body=current, etag=current["_etag"],
            match_condition=MatchConditions.IfNotModified,
        )
    else:
        replace_record(harness.runs, "run-1", "conversation-1", execution_deadline_at=value)
    before = harness.read()
    result, _, _ = tick(harness)
    saved = harness.read()
    assert result["ok"] is False
    assert len(result["errors"]) == 1 and result["errors"][0]["code"] == expected_code
    assert saved == before and saved["started_at"] == record["started_at"]
    assert harness.model_calls == [] and harness.clients == [] and harness.blobs.file_uploads == 0


@pytest.mark.parametrize("new_timeout", [30, 3600])
def test_precheckpoint_continuation_keeps_claim_timing_after_settings_change(harness, new_timeout):
    harness.settings["chat_orchestration_total_timeout_seconds"] = 173
    harness.create(
        replies=["The original execution budget is unchanged."],
        final_response=harness.helpers.input_binding("prepare"),
    )
    initial = harness.prepare()
    before = harness.read()
    initial.close()
    harness.settings["chat_orchestration_total_timeout_seconds"] = new_timeout
    result, _, _ = tick(harness)
    saved = harness.read()
    assert result["ok"], result["errors"]
    assert saved["status"] == "completed" and len(harness.model_calls) == 1
    assert saved["started_at"] == before["started_at"]
    assert saved["execution_deadline_at"] == before["execution_deadline_at"]


def test_expired_initial_claim_does_not_receive_a_new_budget(harness, execution_clock):
    harness.settings["chat_orchestration_total_timeout_seconds"] = 173
    harness.create(final_response=harness.helpers.input_binding("prepare"))
    before, lease = harness.claim()
    lease.close(release=True)
    execution_clock[0] += timedelta(seconds=174)
    harness.settings["chat_orchestration_total_timeout_seconds"] = 3600
    result, _, _ = tick(harness, clock=lambda: execution_clock[0])
    saved = harness.read()
    assert result["ok"], result["errors"]
    assert result["counts"]["runs_executed"] == 0
    assert saved["status"] == "failed" and saved["failure"]["code"] == "run_timeout"
    assert saved["started_at"] == before["started_at"]
    assert saved["execution_deadline_at"] == before["execution_deadline_at"]
    assert not saved.get("execution_binding") and not saved.get("task_results")
    assert harness.model_calls == [] and harness.clients == [] and harness.blobs.file_uploads == 0


def test_lost_initial_claim_acknowledgement_recovers_without_restarting_the_budget(
    harness, monkeypatch, execution_clock,
):
    harness.settings["chat_orchestration_total_timeout_seconds"] = 173
    harness.create(
        replies=["The original claim survived its lost acknowledgement."],
        final_response=harness.helpers.input_binding("prepare"),
    )
    writes = []
    replace_item = harness.runs.replace_item

    def lose_acknowledgement(item, body, **kwargs):
        previous = harness.runs.read_item(item, body["conversation_id"])
        saved = replace_item(item=item, body=body, **kwargs)
        if not previous.get("started_at") and body.get("started_at"):
            writes.append(deepcopy(saved))
            raise ServiceResponseError("Private initial-claim acknowledgement was lost.")
        return saved

    monkeypatch.setattr(harness.runs, "replace_item", lose_acknowledgement)
    with pytest.raises((harness.revisions.PlanRevisionError, ServiceResponseError)):
        harness.claim()
    before = harness.read()
    assert len(writes) == 1 and before == writes[0]
    assert harness.model_calls == [] and harness.clients == []
    execution_clock[0] += timedelta(seconds=harness.recovery.LEASE_SECONDS + 1)
    result, _, _ = tick(harness, clock=lambda: execution_clock[0])
    saved = harness.read()
    assert result["ok"], result["errors"]
    assert saved["status"] == "completed" and len(harness.model_calls) == 1
    assert saved["started_at"] == before["started_at"]
    assert saved["execution_deadline_at"] == before["execution_deadline_at"]
    assert saved["attempt_index"] == before["attempt_index"] == 1


def test_lost_first_binding_acknowledgement_cannot_adopt_a_successor_claim(
    harness, monkeypatch, execution_clock,
):
    with resumed_before_checkpoint(harness) as (before, execution):
        checkpoints = harness.continuation.ContinuationCheckpoints(
            execution.record, execution.context, harness.settings, execution.lease,
        )
        replace_item = harness.runs.replace_item
        winners = []

        def take_over_after_commit(item, body, **kwargs):
            previous = harness.runs.read_item(item, body["conversation_id"])
            saved = replace_item(item=item, body=body, **kwargs)
            if previous.get("execution_binding") is None and body.get("execution_binding") is not None:
                execution_clock[0] += timedelta(seconds=harness.recovery.LEASE_SECONDS + 1)
                winner = claim(harness, mode="execute")
                if winner is None:
                    raise AssertionError("The successor did not acquire the expired claim.")
                winner[1].start()
                winners.append(winner)
                raise ServiceResponseError("Private acknowledgement was lost after takeover.")
            return saved

        monkeypatch.setattr(harness.runs, "replace_item", take_over_after_commit)
        with pytest.raises(ServiceResponseError):
            checkpoints.initialize()
        saved = harness.read()
        assert len(winners) == 1
        assert execution.lease.original["execution_binding"] is None
        assert saved["execution_binding"] == checkpoints.binding
        assert saved["execution_lease"]["claim_id"] == winners[0][1].claim_id
        assert harness.model_calls == [] and harness.blobs.file_uploads == 0
        winners[0][1].close(release=True)
    result, _, _ = tick(harness, clock=lambda: execution_clock[0])
    saved = harness.read()
    assert result["ok"], result["errors"]
    assert saved["status"] == "completed" and len(harness.model_calls) == 1
    assert saved["started_at"] == before["started_at"]
    assert saved["execution_deadline_at"] == before["execution_deadline_at"]


@pytest.mark.parametrize("mode", ["outputs", "delivery"])
def test_nonexecution_claim_cannot_establish_the_first_binding(harness, mode):
    harness.create()
    initial = harness.prepare()
    initial.close()
    owned = claim(harness, mode=mode)
    if owned is None:
        raise AssertionError("The nonexecution claim fixture was not acquired.")
    record, lease = owned
    lease.start()
    checkpoints = harness.continuation.ContinuationCheckpoints(
        record, initial.context, harness.settings, lease,
    )
    with pytest.raises(harness.recovery.CheckpointError) as raised:
        checkpoints.initialize()
    saved = harness.read()
    assert raised.value.code == "recovery_changed"
    assert saved.get("execution_binding") is None
    assert lease.original["execution_binding"] is None
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0


@pytest.mark.parametrize("manifest_options", [{}, {"waiting": True}, {"input_only": True}])
def test_first_binding_cannot_erase_existing_private_checkpoint_evidence(harness, manifest_options):
    with resumed_before_checkpoint(harness) as (_, execution):
        checkpoints = harness.continuation.ContinuationCheckpoints(
            execution.record, execution.context, harness.settings, execution.lease,
        )
        module = importlib.import_module("functions_orchestration_checkpoints")
        manifest_id, _ = module._manifest_address("prepare", **manifest_options)
        harness.steps.create_item({"id": manifest_id, "run_id": "run-1"})
        with pytest.raises(harness.recovery.CheckpointError) as raised:
            checkpoints.initialize()
        saved = harness.read()
        assert raised.value.code == "recovery_changed"
        assert saved.get("execution_binding") is None
        assert execution.lease.original["execution_binding"] is None
        assert harness.model_calls == [] and harness.blobs.file_uploads == 0


@pytest.mark.parametrize("field, value", [
    ("checkpoint_version", True),
    ("attempt_index", True),
    ("attempt_index", 2),
    ("execution_steps", ()),
    ("execution_deadline_at", None),
    ("execution_deadline_at", "2030-01-01T00:00:00+00:00"),
    ("execution_initial_manifest", {}),
    ("execution_binding", "g" * 64),
    ("unexpected_field", True),
])
def test_first_binding_rejects_malformed_or_changed_initialization_without_writing(harness, field, value):
    with resumed_before_checkpoint(harness) as (_, execution):
        checkpoints = harness.continuation.ContinuationCheckpoints(
            execution.record, execution.context, harness.settings, execution.lease,
        )
        module = importlib.import_module("functions_orchestration_checkpoints")
        state = module.context_state(execution.context)
        updates = {
            "checkpoint_version": module.CHECKPOINT_VERSION,
            "execution_binding": checkpoints.binding,
            "execution_steps": [],
            "attempt_index": execution.record["attempt_index"],
            "execution_initial_manifest": state["execution_manifest"],
            "execution_deadline_at": execution.record["execution_deadline_at"],
            field: value,
        }
        before = harness.read()
        with pytest.raises(harness.recovery.CheckpointError) as raised:
            execution.lease.initialize_checkpoint_state(updates)
        saved = harness.read()
        assert raised.value.code == "recovery_changed"
        assert saved == before and execution.lease.original["execution_binding"] is None
        assert harness.model_calls == [] and harness.blobs.file_uploads == 0


@pytest.mark.parametrize("optimized", [False, True])
def test_timing_policy_cold_import_needs_no_initialized_application(optimized):
    application = Path(__file__).resolve().parents[1] / "application" / "single_app"
    probe = """
import sys
from datetime import datetime, timezone

network_attempts = []
def deny_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        network_attempts.append(event)
        raise RuntimeError("The cold timing import attempted network access.")

sys.addaudithook(deny_network)
sys.path.insert(0, sys.argv[1])
from functions_orchestration_timing import execution_timeout_seconds, initial_execution_deadline

loaded_owners = {"config", "functions_appinsights", "functions_settings"}.intersection(sys.modules)
if loaded_owners:
    raise SystemExit("Timing imported an application owner.")
started = datetime(2030, 1, 1, tzinfo=timezone.utc)
for configured, expected in ((173, 173), ("173", 173), (None, 600), (0, 600), ("bad", 600)):
    settings = {"chat_orchestration_total_timeout_seconds": configured}
    seconds = execution_timeout_seconds(settings)
    deadline = initial_execution_deadline(started, settings)
    elapsed = (datetime.fromisoformat(deadline) - started).total_seconds()
    if seconds != expected or elapsed != expected:
        raise SystemExit("Initial and runtime timeout policies diverged.")
if network_attempts:
    raise SystemExit("Timing swallowed a network failure.")
sys.stdout.write("timing-policy-ready")
"""
    completed = subprocess.run(
        [sys.executable, *(["-O"] if optimized else []), "-I", "-S", "-c", probe, str(application)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "timing-policy-ready"
