# test_orchestration_continuation.py
"""Real same-attempt claims, lifecycle rollover and retained checkpoint recovery.

Version: 0.261.127
Implemented in: 0.261.127
Only external storage/model I/O is doubled; real lease and result-store CAS paths run.
"""

import importlib
import sys
from copy import copy, deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from azure.core import MatchConditions
from azure.core.exceptions import AzureError

from test_support import offline_bootstrap
from test_support.orchestration_revisions import AtomicMemoryContainer


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"

@pytest.fixture(scope="module")
def initialized_continuation():
    with patch.object(sys, "path", [str(APP), *sys.path]):
        helpers = importlib.import_module("test_support.orchestration_harness_execution")
        before = set(sys.modules)
        with patch.object(
            offline_bootstrap, "TemporaryDirectory", helpers.project_session_cache,
        ), offline_bootstrap.offline_app_imports() as environment:
            module = importlib.import_module("functions_orchestration_continuation")
            yield module
            if environment.network_attempts:
                raise AssertionError("Continuation swallowed a prohibited network request.")
        for name in set(sys.modules) - before:
            path = getattr(sys.modules[name], "__file__", "") or ""
            if str(APP) in path:
                sys.modules.pop(name, None)


@pytest.fixture
def harness(initialized_continuation, monkeypatch):
    helpers = importlib.import_module("test_support.orchestration_harness_execution")
    environment = helpers.HarnessEnvironment(monkeypatch)
    environment.helpers = helpers
    environment.continuation = initialized_continuation
    environment.continuation_leases = []
    yield environment
    for lease in environment.continuation_leases:
        lease.close()


def replace_record(container, item, partition, **updates):
    previous = container.read_item(item, partition)
    replacement = deepcopy(previous)
    replacement.update(updates)
    return container.replace_item(
        item=item, body=replacement, etag=previous["_etag"],
        match_condition=MatchConditions.IfNotModified,
    )


def saved_composition(harness, **turn_updates):
    harness.create(
        replies=["The complete saved answer."],
        final_response=harness.helpers.input_binding("prepare"), **turn_updates,
    )
    execution = harness.prepare()
    try:
        result = harness.run_engine(execution)
    finally:
        execution.close()
    if result["status"] != "completed":
        raise AssertionError(result)
    return harness.read(), execution


def claim(harness, *, mode="delivery"):
    result = harness.continuation.claim_run_continuation(
        "run-1", "owner", "conversation-1",
        authorize=lambda: harness.bootstrap.read_owned_conversation("owner", "conversation-1"),
        message_container=harness.messages, mode=mode,
    )
    if result is not None:
        harness.continuation_leases.append(result[1])
    return result


@pytest.fixture
def result_epoch(harness):
    store_module = importlib.import_module("functions_workflow_result_store")
    contract = importlib.import_module("functions_orchestration_result_contracts")
    harness.create(
        replies=["A result that remains immutable."],
        final_response=harness.helpers.input_binding("prepare"),
    )
    execution = harness.prepare()
    base = harness.services().results.store
    scoped = execution.services.results.store.for_orchestration_execution(
        "owner", "conversation-1", "run-1",
        guard_token=execution.lease.token, check_execution=execution.lease.read,
    )
    execution.services.results.store = scoped
    identity = store_module._orchestration_identity("owner", "conversation-1", "run-1", "prepare")
    try:
        scoped.begin_analysis_attempt(
            identity, {"operation": "fixture-work"}, [{"document_id": "fixture-source"}],
            token=execution.lease.token,
        )
        scoped.claim_analysis_unit(identity, "pending-unit", token=execution.lease.token)
        pending = scoped.read_analysis_checkpoint(identity, "unit", "pending-unit")
        outcome = harness.run_engine(execution)
        if outcome["status"] != "completed":
            raise AssertionError(outcome)
        record = harness.read()
        task = contract.TaskResult.from_dict(record["task_results"]["prepare"])
        checkpoint = harness.recovery.checkpoint_store(record, execution.lease.read).load("prepare")
        yield SimpleNamespace(
            execution=execution, base=base, scoped=scoped, identity=identity,
            pending=pending, producer=task.producer, fingerprint=checkpoint["input_fingerprint"],
            receipt_prefix=f"{contract.RESULT_RECEIPT_VERSION}:",
        )
    finally:
        execution.close()


def test_result_epoch_cutover_fences_old_writes_pending_reads_and_receipts(harness, result_epoch):
    data = result_epoch
    old_token = data.execution.lease.token
    before = deepcopy(harness.results.container.items)
    data.execution.close()
    record, lease = claim(harness, mode="outputs")
    lease.start()
    current = harness.continuation.bind_continuation_result_store(record, store=data.base, lease=lease)
    assert lease.token == old_token and current is not data.scoped
    assert lease.claim_id != data.execution.lease.claim_id
    operations = (
        lambda: data.scoped.save_orchestration(
            "owner", "conversation-1", "run-1", "prepare", {"forbidden": True},
            guard_token=old_token, require_analysis_guard=True,
        ),
        lambda: data.scoped.read_analysis_checkpoint(data.identity, "unit", "pending-unit"),
        lambda: data.scoped.load_orchestration_result_receipt(data.producer, data.fingerprint),
        lambda: data.scoped.load_orchestration_result_receipt(data.producer, "f" * 64),
    )
    for operation in operations:
        with pytest.raises(harness.continuation.CheckpointError):
            operation()
    store_module = importlib.import_module("functions_workflow_result_store")
    with pytest.raises(store_module.AnalysisWorkUnitConflictError):
        data.base.save_orchestration(
            "owner", "conversation-1", "run-1", "prepare", {"forbidden": True},
            guard_token=old_token, require_analysis_guard=True,
        )
    with pytest.raises(store_module.AnalysisWorkUnitConflictError):
        data.base.cancel_analysis_attempt(data.identity, token=old_token)
    pending = current.read_analysis_checkpoint(data.identity, "unit", "pending-unit")
    receipt = current.load_orchestration_result_receipt(data.producer, data.fingerprint)
    historical = data.base.load_orchestration_result_receipt(data.producer, data.fingerprint)
    assert pending == data.pending and receipt == historical and receipt is not None
    assert data.scoped._orchestration_execution.token == old_token
    assert current._orchestration_execution.token == lease.token
    assert current._orchestration_execution.claim_id == lease.claim_id
    for key, row in before.items():
        if row.get("record_kind") != "lifecycle":
            assert harness.results.container.items[key] == row
    lease.close(release=True)


@pytest.mark.parametrize("binding_api", ["continuation", "store"])
def test_initial_binding_prepares_only_claim_fences_and_rejects_token_only_writers(harness, binding_api):
    harness.create(
        steps=[harness.helpers.compose_step(), harness.helpers.compose_step("later")],
        replies=["Prepared only if executed.", "Not executed by binding."],
    )
    execution = harness.prepare()
    unbound = harness.services().results.store
    module = importlib.import_module("functions_workflow_result_store")
    try:
        if binding_api == "store":
            scoped = execution.services.results.store.bind_orchestration_execution(
                "owner", "conversation-1", "run-1",
                guard_token=execution.lease.token, check_execution=execution.lease.read,
            )
        else:
            scoped = harness.continuation.bind_orchestration_result_store(
                execution.record, store=execution.services.results.store, lease=execution.lease,
            )
        for step_id in ("prepare", "later"):
            identity = module._orchestration_identity("owner", "conversation-1", "run-1", step_id)
            guard = scoped._analysis_guard(identity)
            assert guard["token"] == execution.lease.token and guard["execution_claim_id"] is None
            with pytest.raises(module.AnalysisWorkUnitConflictError):
                unbound.save_orchestration(
                    "owner", "conversation-1", "run-1", step_id, {"stale": True},
                    guard_token=execution.lease.token, require_analysis_guard=True,
                )
        rows = list(harness.results.container.items.values())
        assert len(rows) == 2 and all(row["record_kind"] == "lifecycle" for row in rows)
        assert not harness.model_calls and harness.blobs.file_uploads == 0
    finally:
        execution.close()


def test_initial_headless_store_view_is_fenced_after_same_attempt_takeover(harness):
    original, execution = saved_composition(harness)
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    task = contracts.TaskResult.from_dict(original["task_results"]["prepare"])
    checkpoint = harness.recovery.checkpoint_store(
        original, lambda: harness.bootstrap.read_owned_conversation("owner", "conversation-1"),
    ).load("prepare")
    old_store = execution.services.results.store
    record, lease = claim(harness, mode="outputs")
    lease.start()
    current = harness.continuation.bind_continuation_result_store(
        record, store=harness.services().results.store, lease=lease,
    )
    receipt = current.load_orchestration_result_receipt(task.producer, checkpoint["input_fingerprint"])
    assert receipt is not None
    with pytest.raises(harness.continuation.CheckpointError):
        old_store.load_orchestration_result_receipt(task.producer, checkpoint["input_fingerprint"])
    with pytest.raises(harness.continuation.CheckpointError):
        old_store.load_orchestration_result_receipt(task.producer, "f" * 64)
    assert len(harness.model_calls) == 1
    lease.close(release=True)


@pytest.mark.parametrize("kind", ["pending", "receipt", "absent_receipt"])
def test_result_read_rechecks_epoch_after_the_control_point_read(harness, result_epoch, monkeypatch, kind):
    data = result_epoch
    row_kind = "unit" if kind == "pending" else "final"
    original_read = harness.results.container.read_item
    stolen = []

    def read_then_cut_over(item, partition_key, **kwargs):
        try:
            return original_read(item=item, partition_key=partition_key, **kwargs)
        finally:
            row = harness.results.container.items.get((partition_key, item))
            selected = (
                row is not None and row.get("record_kind") == row_kind
                and (kind == "pending" or row.get("key", "").startswith(data.receipt_prefix))
            ) or (kind == "absent_receipt" and row is None)
            if selected and not stolen:
                stolen.append(True)
                current = harness.read()
                data.execution.lease.close()
                replace_record(
                    harness.runs, "run-1", "conversation-1",
                    execution_lease={
                        **current["execution_lease"],
                        "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                    },
                )
                record, lease = claim(harness, mode="outputs")
                lease.start()
                harness.continuation.bind_continuation_result_store(record, store=data.base, lease=lease)

    monkeypatch.setattr(harness.results.container, "read_item", read_then_cut_over)
    with pytest.raises(harness.continuation.CheckpointError):
        if kind == "pending":
            data.scoped.read_analysis_checkpoint(data.identity, "unit", "pending-unit")
        else:
            stamp = "f" * 64 if kind == "absent_receipt" else data.fingerprint
            data.scoped.load_orchestration_result_receipt(data.producer, stamp)
    assert stolen == [True]


@pytest.mark.parametrize("kind", ["pending", "receipt"])
def test_result_execution_read_outage_is_not_a_missing_receipt(harness, result_epoch, monkeypatch, kind):
    data = result_epoch
    before = deepcopy(harness.results.container.items)
    with monkeypatch.context() as scoped:
        scoped.setattr(harness.runs, "fail_reads", True)
        with pytest.raises(AzureError):
            if kind == "pending":
                data.scoped.read_analysis_checkpoint(data.identity, "unit", "pending-unit")
            else:
                data.scoped.load_orchestration_result_receipt(data.producer, data.fingerprint)
    assert harness.results.container.items == before


@pytest.mark.parametrize("mutation", ["token", "owner", "conversation", "run"])
def test_result_execution_view_rejects_unclaimed_identity(harness, result_epoch, mutation):
    data = result_epoch
    values = {
        "user_id": "owner", "conversation_id": "conversation-1", "run_id": "run-1",
        "guard_token": data.execution.lease.token, "check_execution": data.execution.lease.read,
    }
    key = {"token": "guard_token", "owner": "user_id", "conversation": "conversation_id", "run": "run_id"}[mutation]
    values[key] = "different-identity"
    store_module = importlib.import_module("functions_workflow_result_store")
    before = deepcopy(harness.results.container.items)
    with pytest.raises(store_module.AnalysisWorkUnitConflictError):
        data.base.for_orchestration_execution(**values)
    assert harness.results.container.items == before


def test_claim_and_publication_preserve_original_attempt_and_all_retained_fields(harness):
    before, old_execution = saved_composition(harness)
    selected = claim(harness)
    record, lease = selected
    lease.start()
    lease.start()
    services = harness.services()
    with harness.publication_only(services):
        frames = harness.execution.refresh_harness_delivery(
            record, settings=harness.settings, services=services, lease=lease,
        )
    after = harness.read()
    done = harness.helpers.decoded_frames(frames)[-1]
    for key in (
        "id", "run_id", "attempt_index", "started_at", "execution_deadline_at", "execution_binding",
        "plan", "task_results", "pending_results", "execution_steps", "harness_prompt_token_usage",
        "harness_step_token_usage",
    ):
        assert after.get(key) == before.get(key), key
    assert lease.token == old_execution.lease.token
    assert lease.claim_id != old_execution.lease.claim_id
    assert record["continuation"]["generation"] == 1
    assert done["message_saved"] is True and done["status"] == "completed"
    assert done["full_content"] == "The complete saved answer."
    assert len(harness.model_calls) == 1
    assert after["execution_lease"] is None
    stopped, alive = lease.stopped.is_set(), lease.thread.is_alive()
    assert stopped and not alive
    with pytest.raises(harness.continuation.CheckpointError):
        old_execution.lease.read()


def test_live_and_duplicate_claims_do_not_replace_the_real_owner(harness):
    saved_composition(harness)
    first = claim(harness)
    duplicate = claim(harness)
    first[1].start()
    later = claim(harness)
    current = harness.read()
    assert duplicate is None and later is None
    assert current["execution_lease"]["token"] == first[1].token
    assert current["execution_lease"]["claim_id"] == first[1].claim_id
    assert current["continuation"]["generation"] == 1
    first[1].close(release=True)


def test_competing_cas_claim_admits_exactly_one_continuation(harness):
    saved_composition(harness)
    winners = []
    harness.runs.before_replace = lambda: winners.append(claim(harness))
    loser = claim(harness)
    record = harness.read()
    assert loser is None
    assert len(winners) == 1 and winners[0] is not None
    assert record["execution_lease"]["token"] == winners[0][1].token
    assert record["execution_lease"]["claim_id"] == winners[0][1].claim_id
    winners[0][1].close(release=True)


@pytest.mark.parametrize("change", [
    {"planner_contract_version": 1},
    {"planner_contract_version": True},
    {"superseded_by_run_id": "newer-plan"},
    {"latest_attempt_run_id": "newer-attempt"},
    {"latest_attempt_run_id": "run-1"},
    {"checkpoints_deleted": True},
    {"outputs_deleted": True},
    {"execution_deadline_at": "2026-09-21T10:00:00"},
])
def test_invalid_or_fenced_saved_run_never_gets_a_lease(harness, change):
    saved_composition(harness)
    replace_record(harness.runs, "run-1", "conversation-1", **change)
    before = deepcopy(harness.runs.items)
    with pytest.raises(harness.continuation.CheckpointError):
        claim(harness)
    assert harness.runs.items == before


@pytest.mark.parametrize("change", [
    {"deleted": True}, {"orchestration_deleted": True}, {"user_id": "another-owner"},
])
def test_selector_cannot_authorize_deleted_or_foreign_conversation(harness, change):
    saved_composition(harness)
    replace_record(harness.conversations, "conversation-1", "conversation-1", **change)
    before = deepcopy(harness.runs.items)
    with pytest.raises(PermissionError):
        claim(harness)
    assert harness.runs.items == before


def test_guard_rollover_fences_old_writes_without_mutating_completed_results(harness):
    before, execution = saved_composition(harness)
    record, lease = claim(harness, mode="outputs")
    lease.start()
    services = harness.services()
    store = services.results.store
    rows = deepcopy(harness.results.container.items)
    changed = store.rollover_orchestration_result_guard(
        "owner", "conversation-1", "run-1", "prepare",
        guard_token=lease.token, check_execution=lease.read,
    )
    repeated = store.rollover_orchestration_result_guard(
        "owner", "conversation-1", "run-1", "prepare",
        guard_token=lease.token, check_execution=lease.read,
    )
    assert changed is True and repeated is True
    for key, value in rows.items():
        current = harness.results.container.items[key]
        if value.get("record_kind") == "lifecycle":
            assert current["token"] == lease.token
            assert current["execution_claim_id"] == lease.claim_id
            for name in ("request_digest", "resume_from", "deleted", "request_registered"):
                assert current.get(name) == value.get(name)
        else:
            assert current == value
    result_store = importlib.import_module("functions_workflow_result_store")
    with pytest.raises(result_store.AnalysisWorkUnitConflictError):
        store.prepare_orchestration_result(
            "owner", "conversation-1", "run-1", "prepare", guard_token=execution.lease.token,
        )
    task_type = importlib.import_module("functions_orchestration_result_contracts").TaskResult
    task = task_type.from_dict(before["task_results"]["prepare"])
    reader = services.results.open_result(task.output("answer"))
    text = reader.read_text()
    assert text == "The complete saved answer."
    lease.close(release=True)


@pytest.mark.parametrize("mutation", ["cancelled", "deleted", "successor"])
def test_result_guard_rollover_never_revives_stopped_or_replaced_work(harness, mutation):
    saved_composition(harness)
    record, lease = claim(harness, mode="outputs")
    lease.start()
    store = harness.services().results.store
    result_store = importlib.import_module("functions_workflow_result_store")
    identity = result_store._orchestration_identity("owner", "conversation-1", "run-1", "prepare")
    guard = store._analysis_guard(identity)
    updates = {
        "cancelled": {"stopped": True, "stop_reason": "cancelled"},
        "deleted": {"deleted": True},
        "successor": {"successor": {"run_id": "another-attempt"}},
    }[mutation]
    replace_record(harness.results.container, guard["id"], "run-1", **updates)
    before = deepcopy(harness.results.container.items)
    with pytest.raises(result_store.AnalysisWorkUnitConflictError):
        store.rollover_orchestration_result_guard(
            "owner", "conversation-1", "run-1", "prepare",
            guard_token=lease.token, check_execution=lease.read,
        )
    assert harness.results.container.items == before
    lease.close(release=True)


def test_storage_outage_is_not_a_missing_or_denied_run(harness):
    saved_composition(harness)
    harness.runs.fail_reads = True
    with pytest.raises(AzureError):
        claim(harness)
    harness.runs.fail_reads = False
    record = harness.read()
    assert record["status"] == "completed"
    assert record["execution_lease"] is None


def test_expired_lease_can_be_claimed_without_resetting_deadline(harness):
    before, _ = saved_composition(harness)
    record, old_lease = claim(harness)
    replace_record(harness.runs, "run-1", "conversation-1", execution_lease={
        **record["execution_lease"],
        "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    })
    next_record, next_lease = claim(harness)
    next_lease.start()
    with pytest.raises(harness.continuation.CheckpointError):
        old_lease.read()
    assert next_lease.token == old_lease.token
    assert next_lease.claim_id != old_lease.claim_id
    assert next_record["continuation"]["generation"] == 2
    assert next_record["execution_deadline_at"] == before["execution_deadline_at"]
    next_lease.close(release=True)


def test_publication_guard_race_cannot_restore_a_stale_token(harness):
    saved_composition(harness)
    record, stale = claim(harness)
    winners = []

    def replace_owner():
        replace_record(harness.runs, "run-1", "conversation-1", execution_lease={
            **record["execution_lease"],
            "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        })
        owned = claim(harness)
        winners.append(owned)
        owned[1].start()

    harness.messages.before_replace = replace_owner
    with pytest.raises(harness.continuation.CheckpointError):
        stale.start()
    guard_id = f"orchestration_guard_{harness.continuation.fingerprint('run-1')[:40]}"
    guard = harness.messages.read_item(guard_id, "conversation-1")
    assert guard["token"] == winners[0][1].token
    assert guard["claim_id"] == winners[0][1].claim_id
    winners[0][1].close(release=True)


@pytest.mark.parametrize("planning_usage", [
    {}, {"prompt_tokens": 19, "completion_tokens": 8, "total_tokens": 27},
])
@pytest.mark.parametrize("admission_disabled", [False, True])
def test_completed_checkpoint_recovery_never_calls_the_producer_again(harness, planning_usage, admission_disabled):
    harness.settings["enable_chat_orchestration_harness"] = True
    original, _ = saved_composition(harness, planning_token_usage=planning_usage)
    replace_record(harness.runs, "run-1", "conversation-1", status="waiting")
    if admission_disabled:
        harness.settings["enable_chat_orchestration_harness"] = False
    record, lease = claim(harness, mode="execute")
    execution = harness.execution.prepare_harness_execution(
        record, settings=harness.settings, lease=lease,
    )
    try:
        result = harness.execution.execute_plan(
            record["plan"], execution.context, settings=harness.settings, user_id="owner",
            cancel_requested=lease.cancel_requested, persist=execution._persist,
            checkpoints=lambda context: harness.continuation.ContinuationCheckpoints(
                record, context, harness.settings, lease,
            ),
        )
    finally:
        execution.close()
    current = harness.read()
    assert result["status"] == "completed"
    assert len(harness.model_calls) == 1
    assert current["task_results"] == original["task_results"]
    assert current["harness_step_token_usage"] == original["harness_step_token_usage"]
    assert current["harness_prompt_token_usage"] == original["harness_prompt_token_usage"]
    assert current["planning_token_usage"] == original["planning_token_usage"] == planning_usage
    assert current["started_at"] == original["started_at"]
    assert current["execution_deadline_at"] == original["execution_deadline_at"]
    assert current["execution_steps"][0]["reused"] is True


def test_inherited_checkpoint_keeps_original_provenance_after_same_attempt_restart(harness):
    class LostProcess(BaseException):
        pass

    harness.create(
        steps=[
            harness.helpers.compose_step(),
            harness.helpers.compose_step("finish", inputs={
                "prepared": {"binding": harness.helpers.input_binding("prepare"), "allow_partial": False},
            }),
        ],
        replies=["Original retained content.", RuntimeError("INITIAL_FIXTURE_FAILURE")],
        final_response=harness.helpers.input_binding("finish"),
    )
    execution = harness.prepare()
    try:
        failed = harness.run_engine(execution)
    finally:
        execution.close()
    assert failed["status"] == "failed"
    parent = harness.read()
    authorize = lambda: harness.bootstrap.read_owned_conversation("owner", "conversation-1")
    probe = copy(execution.context)
    probe.result_service = harness.services().results
    parent_store = harness.recovery.checkpoint_store(parent, authorize)
    original_payload = parent_store.load("prepare")
    # Explicit user retry is fixture setup; the subsequent continuation cannot create a third attempt.
    child = harness.recovery.prepare_retry(
        "run-1", "owner", {
            "conversation_id": "conversation-1", "submission_id": "explicit-user-retry",
            "expected_version": parent["recovery_version"],
        },
        authorize=authorize, message_container=harness.messages,
        validate=lambda current: harness.recovery.validate_resume(
            current, probe, harness.settings, authorize, source_run_id=current["id"],
        ),
    )
    services = harness.services()
    claimed = harness.revisions.claim_plan_run(
        child["id"], "owner", "conversation-1", expected_version=child["edit_version"],
        result_alias_resolver=lambda current: harness.service_bindings.admitted_result_aliases(
            current, services.results,
        ),
    )
    initial_lease = harness.recovery.ExecutionLease(claimed, authorize, message_container=harness.messages)
    initial = harness.execution.prepare_harness_execution(claimed, settings=harness.settings, lease=initial_lease)

    def lose_process_before_checkpoint_copy():
        raise LostProcess()

    harness.steps.before_batch = lose_process_before_checkpoint_copy
    try:
        with pytest.raises(LostProcess):
            harness.run_engine(initial)
    finally:
        initial.close()
        harness.steps.before_batch = None
    before = harness.runs.read_item(child["id"], "conversation-1")
    child_store = harness.recovery.checkpoint_store(before, authorize)
    copied = child_store.has_manifest("prepare")
    assert copied is False and before["execution_deadline_at"] and len(harness.model_calls) == 2
    record, lease = harness.continuation.claim_run_continuation(
        child["id"], "owner", "conversation-1", authorize=authorize,
        message_container=harness.messages, mode="execute",
    )
    harness.continuation_leases.append(lease)
    continued = harness.execution.prepare_harness_execution(record, settings=harness.settings, lease=lease)
    harness.replies.append("The final answer reuses the original inherited content.")
    try:
        result = harness.execution.execute_plan(
            record["plan"], continued.context, settings=harness.settings, user_id="owner",
            cancel_requested=lease.cancel_requested, persist=continued._persist,
            checkpoints=lambda context: harness.continuation.ContinuationCheckpoints(
                record, context, harness.settings, lease,
            ),
        )
    finally:
        continued.close()
    current = harness.runs.read_item(child["id"], "conversation-1")
    copied_payload = child_store.load("prepare")
    parent_after = harness.read()
    assert result["status"] == "completed" and len(harness.model_calls) == 3
    assert current["task_results"]["prepare"] == parent["task_results"]["prepare"]
    assert copied_payload["provenance"] == original_payload["provenance"]
    assert copied_payload["input_fingerprint"] == original_payload["input_fingerprint"]
    assert current["id"] == child["id"] and current["attempt_index"] == before["attempt_index"] == 2
    assert current["started_at"] == before["started_at"]
    assert current["execution_deadline_at"] == before["execution_deadline_at"]
    assert parent_after["latest_attempt_run_id"] == child["id"]
    assert not current.get("latest_attempt_run_id")


@pytest.mark.parametrize("first", ["unavailable", "unverified"])
def test_direct_continuation_keeps_first_authority_failure_after_nested_catches(harness, first):
    from content_screening.access import raise_source_authority_error, strict_source_authority
    from content_screening.contracts import SourceAuthorityUnavailableError, SourceAuthorityUnverifiedError

    original, _ = saved_composition(harness)
    replace_record(harness.runs, "run-1", "conversation-1", status="waiting")
    record, lease = claim(harness, mode="execute")
    execution = harness.execution.prepare_harness_execution(record, settings=harness.settings, lease=lease)
    expected = SourceAuthorityUnavailableError() if first == "unavailable" else SourceAuthorityUnverifiedError()
    later = SourceAuthorityUnverifiedError() if first == "unavailable" else SourceAuthorityUnavailableError()

    def caught_source_reads():
        for failure in (expected, later):
            try:
                with strict_source_authority():
                    raise_source_authority_error(failure)
            except (SourceAuthorityUnavailableError, SourceAuthorityUnverifiedError):
                continue

    try:
        checkpoints = harness.continuation.ContinuationCheckpoints(
            record, execution.context, harness.settings, lease,
        )
        checkpoints.initialize()
        execution.context.revalidate_conversation_context = caught_source_reads
        with pytest.raises(type(expected)) as failure:
            checkpoints.before_step(record["plan"]["steps"][0])
        assert failure.value is expected
        assert failure.value.retryable is (first == "unavailable")
        assert len(harness.model_calls) == 1
        current = harness.read()
        assert current["task_results"] == original["task_results"]
        assert not current.get("failure")
    finally:
        execution.close()


@pytest.mark.parametrize("stopped_guard", [False, True])
def test_failed_optional_step_is_not_replayed_when_independent_work_resumes(harness, stopped_guard):
    class LostProcess(BaseException):
        pass

    harness.create(
        steps=[
            {**harness.helpers.compose_step("optional"), "optional": True},
            harness.helpers.compose_step("finish"),
        ],
        replies=[RuntimeError("PRIVATE_OPTIONAL_MODEL_FAILURE"), "Independent prepared answer."],
        final_response=harness.helpers.input_binding("finish"),
    )
    execution = harness.prepare()
    store = execution.services.results.store
    store_module = importlib.import_module("functions_workflow_result_store")
    identity = store_module._orchestration_identity("owner", "conversation-1", "run-1", "optional")
    if stopped_guard:
        store.prepare_orchestration_result(
            "owner", "conversation-1", "run-1", "optional", guard_token=execution.lease.token,
        )

    def interrupt_after_failure():
        failed = harness.steps.items.get(("run-1", "run-1:optional"))
        if failed is not None and failed.get("status") == "failed":
            raise LostProcess()
        harness.steps.before_batch = interrupt_after_failure

    harness.steps.before_batch = interrupt_after_failure
    try:
        with pytest.raises(LostProcess):
            harness.run_engine(execution)
        if stopped_guard:
            execution.lease.read()
            store.cancel_analysis_attempt(identity, token=execution.lease.token, reason="timed_out")
    finally:
        execution.close()
        harness.steps.before_batch = None
    original = harness.read()
    original_failure = next(row["failure"] for row in original["execution_steps"] if row["step_id"] == "optional")
    record, lease = claim(harness, mode="execute")
    continued = harness.execution.prepare_harness_execution(record, settings=harness.settings, lease=lease)
    try:
        outcome = harness.execution.execute_plan(
            record["plan"], continued.context, settings=harness.settings, user_id="owner",
            cancel_requested=lease.cancel_requested, persist=continued._persist,
            checkpoints=lambda context: harness.continuation.ContinuationCheckpoints(
                record, context, harness.settings, lease,
            ),
        )
        if stopped_guard:
            guard = continued.services.results.store._analysis_guard(identity)
    finally:
        continued.close()
    current = harness.read()
    rows = {row["step_id"]: row for row in current["execution_steps"]}
    assert outcome["status"] == "completed"
    assert rows["optional"]["status"] == "failed" and rows["optional"]["failure"] == original_failure
    assert rows["finish"]["status"] == "completed"
    assert len(harness.model_calls) == 2 and not harness.replies
    assert current["attempt_index"] == original["attempt_index"]
    assert current["started_at"] == original["started_at"]
    assert current["execution_deadline_at"] == original["execution_deadline_at"]
    if stopped_guard:
        assert guard["stopped"] is True and guard["token"] is None
        with pytest.raises(harness.continuation.CheckpointError):
            store._analysis_guard(identity)


def test_native_wait_reopens_original_handle_once_and_preserves_child_and_fingerprint(harness, monkeypatch):
    # This fixture initializes the native engine's external I/O after real app bootstrap.
    from test_orchestration_dependency_native_runtime import prepare
    from test_orchestration_native_results import (
        CONVERSATION, USER, bridge_runtime, finish_native, transformation_spec,
    )

    with bridge_runtime(monkeypatch) as runtime, monkeypatch.context() as scoped:
        runtime.native.settings["tabular_generated_output_inline_max_rows"] = 1
        prepare(runtime, columns=["Item_ID", "doubled"], transformation_spec=transformation_spec())
        runs = AtomicMemoryContainer("conversation_id")
        steps = AtomicMemoryContainer("run_id")
        messages = AtomicMemoryContainer("conversation_id")
        runtime.native.parents = runs
        scoped.setattr(harness.run_store, "cosmos_orchestration_runs_container", runs)
        scoped.setattr(harness.run_store, "cosmos_orchestration_run_steps_container", steps)
        scoped.setattr(runtime.native.engine, "cosmos_orchestration_runs_container", runs)
        scoped.setattr(sys.modules["config"], "cosmos_orchestration_runs_container", runs)
        runtime.service.access.read_run = lambda run_id: runs.read_item(run_id, CONVERSATION)
        original = harness.run_store.create_orchestration_run(
            runtime.plan, USER, CONVERSATION, turn_index=1,
            turn_context={"turn_id": runtime.plan["turn_id"]},
        )
        initial = harness.revisions.claim_plan_run(original["id"], USER, CONVERSATION)

        def authorize():
            conversation = runtime.native.conversations.read_item(CONVERSATION, CONVERSATION)
            if conversation["user_id"] != USER or conversation.get("deleted"):
                raise PermissionError("The native conversation is unavailable.")
            return conversation

        first_lease = harness.recovery.ExecutionLease(initial, authorize, message_container=messages)
        first_lease.start()
        runtime.context.plan_id = initial["plan"]["plan_id"]
        runtime.context._result_guard_token_for_step = lambda step_id: first_lease.token

        def persist(lease, kind, update):
            if kind == "run":
                value = {key: deepcopy(item) for key, item in update.items() if key != "run_id"}
                if "started_at" in value:
                    value["started_at"] = initial["started_at"]
                lease.update(value)

        try:
            waiting = harness.execution.execute_plan(
                initial["plan"], runtime.context, settings=runtime.settings, user_id=USER,
                cancel_requested=first_lease.cancel_requested,
                persist=lambda kind, data: persist(first_lease, kind, data),
                checkpoints=lambda context: harness.recovery.ExecutionCheckpoints(
                    initial, context, runtime.settings, first_lease,
                ),
            )
        finally:
            first_lease.close(release=True)
        saved = runs.read_item("parent-run", CONVERSATION)
        original_wait = deepcopy(saved["pending_results"]["compute"])
        original_task = deepcopy(saved["task_results"]["compute"])
        original_checkpoint = harness.recovery.checkpoint_store(saved, authorize).load("compute", waiting=True)
        jobs_created = runtime.native.jobs.created
        assert waiting["status"] == "waiting"
        assert jobs_created == 1

        def forbidden(*args, **kwargs):
            raise AssertionError("A native continuation attempted new planning or submission.")

        runtime.bound = replace(runtime.bound, request_builder=forbidden, model_resolver=forbidden)
        executor = importlib.import_module("functions_orchestration_executor")
        real_resume = executor.resume_native_dependency_step
        polls = []

        def resume_native(*args, **kwargs):
            polls.append(kwargs["input_fingerprint"])
            return real_resume(*args, **kwargs)

        scoped.setattr(executor, "resume_native_dependency_step", resume_native)

        def resume_once():
            record, lease = harness.continuation.claim_run_continuation(
                "parent-run", USER, CONVERSATION, authorize=authorize,
                message_container=messages, mode="execute",
            )
            harness.continuation_leases.append(lease)
            lease.start()
            context = harness.execution.RunContext(
                run_id="parent-run", plan_id=initial["plan"]["plan_id"],
                user_id=USER, conversation_id=CONVERSATION, plan_contract_version=2,
                result_service=copy(runtime.service), gpt_model="gpt-4o",
                result_guard_token_for_step=lambda step_id: lease.token,
                native_bridge_for_step=lambda step, context: runtime.bound,
                resolve_source_manifest=runtime.context.resolve_source_manifest,
            )
            try:
                result = harness.execution.execute_plan(
                    record["plan"], context, settings=runtime.settings, user_id=USER,
                    cancel_requested=lease.cancel_requested,
                    persist=lambda kind, data: persist(lease, kind, data),
                    checkpoints=lambda active: harness.continuation.ContinuationCheckpoints(
                        record, active, runtime.settings, lease,
                    ),
                )
            finally:
                lease.close(release=True)
            return result, context

        still_waiting, _ = resume_once()
        after_wait = runs.read_item("parent-run", CONVERSATION)
        assert still_waiting["status"] == "waiting"
        assert after_wait["pending_results"]["compute"] == original_wait
        assert after_wait["task_results"]["compute"] == original_task
        assert runtime.native.jobs.created == jobs_created
        assert polls == [original_checkpoint["input_fingerprint"]]
        native_status = runtime.native.jobs.read_item(original_wait["handle"]["job_id"], USER)
        assert native_status["status"] not in {"cancelled", "canceled"}
        finish_native(runtime, {"wait": original_wait})
        ready, context = resume_once()
        final = runs.read_item("parent-run", CONVERSATION)
        final_checkpoint = harness.recovery.checkpoint_store(final, authorize).load("compute")
        rows = list(runtime.service.open_result(context.task_results["compute"].output("records")).iter_records())
        assert ready["status"] == "completed"
        assert len(rows) == 37 and rows[-1]["Item_ID"] == "item-000037"
        assert runtime.native.jobs.created == jobs_created
        assert final["attempt_index"] == saved["attempt_index"]
        assert final["started_at"] == saved["started_at"]
        assert final["execution_deadline_at"] == saved["execution_deadline_at"]
        assert final_checkpoint["input_fingerprint"] == original_checkpoint["input_fingerprint"]
        assert final["task_results"]["compute"]["producer"] == original_task["producer"]
        assert final["pending_results"] == {}
        assert runtime.native.publications == []
        assert polls == [original_checkpoint["input_fingerprint"]] * 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
