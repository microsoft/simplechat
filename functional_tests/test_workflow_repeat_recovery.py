# test_workflow_repeat_recovery.py
"""
Functional tests for Repeat atomic recovery, live authority and lifetime budgets.
Version: 0.261.120
Implemented in: 0.261.120

Exercises the real journal and result store with fictional transactional Cosmos,
Blob and clock fixtures. External effects are local counters only.
"""

import copy
import json
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Production imports follow the isolated worktree import setup.
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_execution import WorkflowSuspended
from functions_workflow_execution_history import workflow_execution_history
from functions_workflow_identity import workflow_execution_id
from functions_workflow_node_results import load_workflow_node_input
from functions_workflow_repeat_history import workflow_repeat_iterations_page, workflow_repeat_state_page
from functions_workflow_result_store import WorkflowResultStore
from functions_workflow_runtime_store import WorkflowRuntimeConflict
from test_workflow_for_each_execution import execute_loop, loop_runtime
from test_workflow_repeat_execution import (
    continue_repeat, execute_repeat, repeat_definition, repeat_head, repeat_runtime,
)
from test_workflow_result_store import FakeBlobService


@pytest.mark.parametrize("stage", ["admission_before", "admission_after", "transition_before", "transition_after"])
def test_restart_reuses_sealed_state_and_committed_body_units(monkeypatch, stage):
    workflow, store, _, clock, _ = repeat_runtime(monkeypatch, maximum=3)
    original = store.journal_commit_many
    interrupted = []
    calls = []

    def stop(token, entries, **options):
        key = entries[0]["key"]
        wanted = "repeat-iteration" if stage.startswith("admission") else "repeat-transition"
        if not interrupted and key[0] == wanted and key[-1] == 1:
            interrupted.append(True)
            if stage.endswith("after"):
                original(token, entries, **options)
            raise SystemExit("Closed fixture crash.")
        return original(token, entries, **options)

    monkeypatch.setattr(store, "journal_commit_many", stop)
    with pytest.raises(SystemExit):
        execute_repeat(workflow, store, target=3, calls=calls)
    first = list(calls)
    clock.advance()
    flow, _ = execute_repeat(workflow, store, target=3, calls=calls)
    assert flow.finished
    assert len([call for call in calls if call[0] == "body"]) == 3
    assert len({call[2] for call in calls}) == len(calls)
    assert calls[:len(first)] == first and store.read()["admitted_count"] == 8
    assert repeat_head(workflow, store)["completed_count"] == 3


@pytest.mark.parametrize("kind", ["repeat-iteration", "repeat-transition", "grant"])
def test_lost_acknowledgement_does_not_duplicate_transitions_or_grants(monkeypatch, kind):
    workflow, store, container, clock, events = repeat_runtime(monkeypatch, maximum=1)
    original = container.execute_item_batch
    lost = []

    def commit_then_disconnect(batch_operations, partition_key):
        wanted = any(
            operation[0] == "create" and operation[1][0].get("record_kind") in {"admission", "decision"}
            and (
                operation[1][0].get("key", [None])[0] == kind
                or kind == "grant" and operation[1][0].get("payload", {}).get("choice") == "continue_repeat"
            )
            for operation in batch_operations
        )
        value = original(batch_operations, partition_key)
        if wanted and not lost:
            lost.append(True)
            raise CosmosHttpResponseError(status_code=503)
        return value

    monkeypatch.setattr(container, "execute_item_batch", commit_then_disconnect)
    calls = []
    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, target=2, calls=calls)
    continue_repeat(store)
    clock.advance()
    flow, _ = execute_repeat(workflow, store, target=2, calls=calls)
    assert flow.finished and lost
    assert store.read()["admitted_count"] == 6
    assert store.read()["repeat_counts"] == {"exhaustion_count": 1, "continuation_count": 1}
    assert len(events) == 2 and len([call for call in calls if call[0] == "body"]) == 2


def test_uncertain_effect_uses_existing_recovery_gate_not_manual_batch_grant(monkeypatch):
    workflow, store, _, clock, _ = repeat_runtime(monkeypatch)
    effects = []

    def effect(current, resolved, execution):
        if current["id"] == "source":
            value = {"count": 0, "ready": False}
        else:
            effects.append(execution.execution_id())
            if len(effects) == 1:
                raise SystemExit("Uncertain fictional effect.")
            value = {"count": 1, "ready": True}
        return {"reply": "", "authoritative_result": {"kind": "json", "value": value}}

    with pytest.raises(SystemExit):
        execute_repeat(workflow, store, result_for_task=effect, replay_safe=False)
    clock.advance()
    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, result_for_task=effect, replay_safe=False)
    control = store.read()
    gate = control["gate"]
    assert gate["kind"] == "recovery" and gate["iteration_path"] == [{"loop_id": "repeat", "iteration": 0}]
    with pytest.raises(WorkflowRuntimeConflict):
        continue_repeat(store, "not-a-recovery")
    store.decide(expected_version=control["version"], gate_id=gate["id"],
                 choice="retry", actor_user_id="owner", request_id="recover-effect")
    flow, _ = execute_repeat(workflow, store, result_for_task=effect, replay_safe=False)
    assert flow.finished and len(effects) == 2 and effects[0] == effects[1]
    assert repeat_head(workflow, store)["batch_usage"] == 1
    assert store.read()["admitted_count"] == 5


@pytest.mark.parametrize("budget", [3, 4])
def test_global_admission_limit_cannot_be_extended_by_any_repeat_decision(monkeypatch, budget):
    definition = repeat_definition(1)
    definition["limits"]["max_executions"] = budget
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, definition=definition)
    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, target=2)
    if budget == 4:
        assert store.read()["gate"]["reason_code"] == "repeat_iteration_limit"
        with pytest.raises(WorkflowRuntimeConflict) as error:
            continue_repeat(store)
        assert error.value.code == "execution_budget_exceeded"
    control = store.read()
    assert control["admitted_count"] == budget and control["gate"]["choices"] == ["cancel"]
    with pytest.raises(WorkflowRuntimeConflict):
        store.resume(expected_version=control["version"], actor_user_id="owner", request_id="reset")
    assert repeat_head(workflow, store)["continuation_count"] == 0


def test_human_wait_consumes_frozen_deadline_and_admin_snapshot_is_retained(monkeypatch):
    workflow, store, _, clock, _ = repeat_runtime(monkeypatch, maximum=2)
    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, target=3)
    before = store.read()
    # Initialization replay must not replace an active run's admitted policy.
    unchanged = store.initialize(
        snapshot_ref=before["snapshot_ref"], definition_revision=before["definition_revision"],
        actor_user_id="owner", request_id=before["request_id"], repeat_policy={"max_iterations": 1},
    )
    assert unchanged["repeat_policy"] == before["repeat_policy"]
    clock.now += timedelta(seconds=86400)
    with pytest.raises(WorkflowRuntimeConflict) as error:
        continue_repeat(store)
    assert error.value.code == "deadline_exceeded"
    assert store.read()["gate"]["reason_code"] == "deadline_exceeded"
    assert store.read()["deadline_at"] == before["deadline_at"] and repeat_head(workflow, store)["continuation_count"] == 0


@pytest.mark.parametrize("race", ["cancel", "tombstone", "lease"])
def test_transition_commit_is_fenced_after_preparing_next_state(monkeypatch, race):
    workflow, store, container, clock, _ = repeat_runtime(monkeypatch)
    original = store.journal_commit_many
    stopped = []

    def lose_ownership(token, entries, **options):
        if entries[0]["key"][0] == "repeat-transition" and not stopped:
            stopped.append(True)
            if race == "cancel":
                store.request_cancel(actor_user_id="owner", request_id="cancel-round")
            elif race == "tombstone":
                store.tombstone()
            else:
                clock.advance()
                store.claim(owner_id="replacement-worker")
        return original(token, entries, **options)

    monkeypatch.setattr(store, "journal_commit_many", lose_ownership)
    with pytest.raises(WorkflowRuntimeConflict):
        execute_repeat(workflow, store)
    assert stopped
    transitions = [row for row in container.items.values()
                   if row.get("record_kind") == "decision" and row.get("key", [None])[0] == "repeat-transition"]
    assert transitions == []
    heads = [row["payload"] for row in container.items.values() if row.get("record_kind") == "loop"]
    assert heads[0]["completed_count"] == 0
    if race == "tombstone":
        WorkflowResultStore(container).delete_run_results(workflow, "run")
        assert len(container.items) == 1 and next(iter(container.items.values()))["deleted"]


def test_live_state_authority_is_rechecked_before_grants_and_unfinished_history(monkeypatch):
    definition = repeat_definition(1)
    definition["tasks"][1]["approval"] = {"required": True, "message": "Review this exact fictional round."}
    workflow, store, container, _, _ = repeat_runtime(monkeypatch, definition=definition)
    allowed = {"value": True}
    source = {"document_id": "fictional-source", "scope": "personal", "scope_id": "owner", "source_version": 1}

    def authorize(user, sources, **options):
        if not allowed["value"]:
            raise AnalysisResultUnavailable("analysis_source_access_revoked")
        return {"sources": sources, "source_count": len(sources), "source_snapshot_changed": False}

    monkeypatch.setattr("functions_workflow_node_results.authorize_analysis_sources", authorize)

    def provenance(current, envelope):
        if current["id"] == "source":
            envelope["analysis_access"] = {"version": "analysis-source-access-v1", "sources": [source]}

    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, target=2, envelope_transform=provenance)
    repeat_id = repeat_head(workflow, store)["execution_id"]
    assert store.journal_read("execution", repeat_id)["payload"].get("workflow_result") is None
    allowed["value"] = False
    with pytest.raises(AnalysisResultUnavailable):
        workflow_execution_history(workflow, "run", reader_user_id="owner")
    with pytest.raises(AnalysisResultUnavailable):
        workflow_repeat_state_page(workflow, "run", repeat_id, 0, reader_user_id="owner")
    from functions_workflow_results import authorize_workflow_run_read

    monkeypatch.setitem(sys.modules, "config", SimpleNamespace(
        cosmos_personal_workflow_run_items_container=container, cosmos_group_workflow_run_items_container=container,
    ))
    monkeypatch.setattr("functions_workflow_runtime_store.workflow_runtime_store", lambda *args: store)
    with pytest.raises(AnalysisResultUnavailable):
        authorize_workflow_run_read(workflow, "run", reader_user_id="owner")
    allowed["value"] = True
    approval = store.read()
    store.decide(expected_version=approval["version"], gate_id=approval["gate"]["id"],
                 choice="approve", actor_user_id="owner", request_id="approved-round")
    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, target=2, envelope_transform=provenance)
    allowed["value"] = False
    before = store.read()["repeat_counts"]
    with pytest.raises(AnalysisResultUnavailable):
        continue_repeat(store)
    assert store.read()["repeat_counts"] == before


@pytest.mark.parametrize("backend", ["cosmos", "blob"])
def test_exact_state_history_uses_existing_storage_and_cleanup(monkeypatch, backend):
    workflow, store, container, _, _ = repeat_runtime(monkeypatch)
    blobs = FakeBlobService() if backend == "blob" else None
    results = WorkflowResultStore(container, blobs, "private-results" if blobs else None)
    monkeypatch.setattr("functions_workflow_result_store._configured_store", lambda *args, **kwargs: results)
    monkeypatch.setattr("functions_workflow_result_store._configured_result_store", lambda *args, **kwargs: results)
    flow, _ = execute_repeat(workflow, store, target=3)
    identity = flow.final_outputs[0]["producer"]
    page = workflow_repeat_iterations_page(workflow, "run", identity["execution_id"], reader_user_id="owner", limit=2)
    assert [item["iteration"] for item in page["iterations"]] == [0, 1] and page["next_cursor"]
    last = workflow_repeat_iterations_page(
        workflow, "run", identity["execution_id"], reader_user_id="owner", limit=2, cursor=page["next_cursor"],
    )
    assert [item["iteration"] for item in last["iterations"]] == [2]
    before = workflow_repeat_state_page(workflow, "run", identity["execution_id"], 1, reader_user_id="owner")
    after = workflow_repeat_state_page(workflow, "run", identity["execution_id"], 1, reader_user_id="owner", phase="after")
    assert before["available"] and after["available"]
    assert before["states"][0]["source"]["iteration_path"][-1]["iteration"] == 0
    assert after["states"][0]["source"]["iteration_path"][-1]["iteration"] == 1
    encoded = json.dumps(after)
    assert "state_ref" not in encoded and "result_ref" not in encoded and "count" not in after["states"][0]
    decisions = workflow_execution_history(workflow, "run", reader_user_id="owner", kind="decision")
    assert len([row for row in decisions["decisions"] if row.get("decision_kind") == "repeat_transition"]) == 3
    with pytest.raises(ValueError):
        workflow_repeat_state_page(
            workflow, "run", identity["execution_id"], 1, reader_user_id="owner", cursor=page["next_cursor"],
        )
    payload, _ = load_workflow_node_input(
        workflow, "run", identity, flow.final_outputs[0]["result_ref"], output_name="state",
    )
    assert json.loads(payload)["value"] == {"count": 3, "ready": True}
    store.tombstone()
    results.delete_run_results(workflow, "run")
    assert len(container.items) == 1
    if blobs:
        assert blobs.records == {}


def test_pending_after_state_is_explicitly_unavailable(monkeypatch):
    workflow, store, _, _, _ = repeat_runtime(monkeypatch)
    with pytest.raises(SystemExit):
        execute_repeat(workflow, store, interrupt_at=0)
    repeat_id = repeat_head(workflow, store)["execution_id"]
    before = workflow_repeat_state_page(workflow, "run", repeat_id, 0, reader_user_id="owner")
    after = workflow_repeat_state_page(workflow, "run", repeat_id, 0, reader_user_id="owner", phase="after")
    assert before["available"] and len(before["states"]) == 1
    assert after["available"] is False and after["states"] == [] and after["next_cursor"] is None


def test_batch_grant_does_not_approve_the_next_body_attempt(monkeypatch):
    definition = repeat_definition(1)
    definition["tasks"][1]["approval"] = {"required": True, "message": "Approve this exact fictional round."}
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, definition=definition)
    calls = []
    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, target=2, calls=calls)
    first = copy.deepcopy(store.read())
    store.decide(expected_version=first["version"], gate_id=first["gate"]["id"],
                 choice="approve", actor_user_id="owner", request_id="round-zero-approved")
    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, target=2, calls=calls)
    continue_repeat(store)
    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, target=2, calls=calls)
    second = store.read()
    assert second["gate"]["kind"] == "approval"
    assert second["gate"]["iteration_path"][-1]["iteration"] == 1
    assert second["gate"]["id"] != first["gate"]["id"]
    assert len([call for call in calls if call[0] == "body"]) == 1
    store.decide(expected_version=second["version"], gate_id=second["gate"]["id"],
                 choice="approve", actor_user_id="owner", request_id="round-one-approved")
    flow, _ = execute_repeat(workflow, store, target=2, calls=calls)
    assert flow.finished and repeat_head(workflow, store)["continuation_count"] == 1


@pytest.mark.parametrize("use_decision", [False, True])
def test_cancelled_exhaustion_retains_rounds_without_a_continuation_grant(monkeypatch, use_decision):
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, maximum=1)
    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, target=2)
    control = store.read()
    if use_decision:
        store.decide(expected_version=control["version"], gate_id=control["gate"]["id"],
                     choice="cancel", actor_user_id="owner", request_id="cancel-exhaustion")
    else:
        store.request_cancel(actor_user_id="owner", request_id="cancel-run")
    head = repeat_head(workflow, store)
    assert head["state"] == "cancelled" and head["completed_count"] == 1
    assert head["continuation_count"] == 0 and store.read()["repeat_progress"]["state"] == "cancelled"
    assert store.journal_read("attempt", [head["execution_id"], 1])["payload"]["state"] == "cancelled"


@pytest.mark.parametrize("stage", ["approval", "invalid_state"])
def test_cancelled_body_gate_marks_its_admitted_round_and_repeat(monkeypatch, stage):
    definition = repeat_definition()
    if stage == "approval":
        definition["tasks"][1]["approval"] = {"required": True, "message": "Approve this fictional round."}
    else:
        slot = definition["flow"]["nodes"][1]["state"][0]
        slot["output_contract"] = copy.deepcopy(slot["output_contract"])
        slot["output_contract"]["schema"]["properties"]["count"]["maximum"] = 0
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, definition=definition)

    def produce(current, resolved, execution):
        return {"reply": "", "authoritative_result": {"kind": "json", "value": {
            "count": int(current["id"] == "body"), "ready": False,
        }}}

    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, result_for_task=produce)
    control = store.read()
    store.decide(expected_version=control["version"], gate_id=control["gate"]["id"],
                 choice="reject" if stage == "approval" else "cancel",
                 actor_user_id="owner", request_id="cancel-body-gate")
    head = repeat_head(workflow, store)
    iteration = store.journal_read("iteration", [head["execution_id"], 0])["payload"]
    assert store.read()["state"] == head["state"] == iteration["state"] == "cancelled"
    assert head["completed_count"] == 0 and head["continuation_count"] == 0


@pytest.mark.parametrize("scenario", [
    "queued_repeat", "queued_without_repeat", "running_without_repeat", "running_for_each",
])
def test_cancellation_without_repeat_path_does_not_load_frozen_definition(monkeypatch, scenario):
    if scenario == "running_for_each":
        workflow, store, container, _ = loop_runtime(monkeypatch)

        def interrupt_body(*args, **kwargs):
            raise SystemExit("Closed For each worker interruption.")

        with pytest.raises(SystemExit, match="For each worker interruption"):
            execute_loop(workflow, store, [{"fictional": True}], result_for_item=interrupt_body)
        assert store.read()["cursor"]["iteration_path"]
    else:
        definition = repeat_definition()
        if scenario != "queued_repeat":
            definition["tasks"] = definition["tasks"][:1]
            definition["flow"]["nodes"] = definition["flow"]["nodes"][:1]
            definition["flow"]["outputs"][0]["source"].update(node_id="source-node", output="json")
        workflow, store, container, _, _ = repeat_runtime(monkeypatch, definition=definition)
        if scenario == "running_without_repeat":
            execute_repeat(workflow, store)
    assert not any("iteration" in frame for frame in (store.read().get("cursor") or {}).get("iteration_path", []))
    loop_rows = copy.deepcopy([row for row in container.items.values() if row.get("record_kind") == "loop"])
    admitted = store.read()["admitted_count"]

    def unexpected_snapshot():
        raise AssertionError("Cancellation without a Repeat path must not read a definition snapshot.")

    monkeypatch.setattr(store, "run_definition", unexpected_snapshot)
    cancelled = store.request_cancel(actor_user_id="owner", request_id=f"cancel-{scenario}")
    assert cancelled["state"] == "cancelled" and cancelled["admitted_count"] == admitted
    assert [row for row in container.items.values() if row.get("record_kind") == "loop"] == loop_rows


def test_cached_state_proof_never_caches_current_access_to_a_source(monkeypatch):
    workflow, store, _, _, _ = repeat_runtime(monkeypatch)
    allowed = {"value": True}
    original = store.journal_commit
    calls = []
    source = {"document_id": "fictional-source", "scope": "personal", "scope_id": "owner", "source_version": 1}

    def authorize(user, sources, **options):
        if not allowed["value"]:
            raise AnalysisResultUnavailable("analysis_source_access_revoked")
        return {"source_count": len(sources), "sources": sources, "source_snapshot_changed": False}

    def revoke_before_model(token, kind, key, payload, **options):
        row = original(token, kind, key, payload, **options)
        if kind == "unit" and key[-1] == "task:body" and payload["state"] == "running":
            allowed["value"] = False
        return row

    def provenance(current, envelope):
        if current["id"] == "source":
            envelope["analysis_access"] = {"version": "analysis-source-access-v1", "sources": [source]}

    monkeypatch.setattr("functions_workflow_node_results.authorize_analysis_sources", authorize)
    monkeypatch.setattr(store, "journal_commit", revoke_before_model)
    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, calls=calls, envelope_transform=provenance)
    assert [call[0] for call in calls] == ["source"]
    assert repeat_head(workflow, store)["completed_count"] == 0
    assert store.read()["gate"]["choices"] == ["cancel"]


def test_history_cursors_bind_phase_round_and_admitted_snapshot(monkeypatch):
    definition = repeat_definition(2)
    second_slot = copy.deepcopy(definition["flow"]["nodes"][1]["state"][0])
    second_slot["name"] = "copy"
    definition["flow"]["nodes"][1]["state"].append(second_slot)
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, definition=definition)
    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, target=3)
    repeat_id = repeat_head(workflow, store)["execution_id"]
    rounds = workflow_repeat_iterations_page(workflow, "run", repeat_id, reader_user_id="owner", limit=1)
    first = workflow_repeat_state_page(workflow, "run", repeat_id, 1, reader_user_id="owner", limit=1)
    second = workflow_repeat_state_page(
        workflow, "run", repeat_id, 1, reader_user_id="owner", limit=1, cursor=first["next_cursor"],
    )
    assert [row["name"] for row in first["states"] + second["states"]] == ["state", "copy"]
    for iteration, phase in ((0, "before"), (1, "after")):
        with pytest.raises(ValueError):
            workflow_repeat_state_page(
                workflow, "run", repeat_id, iteration, reader_user_id="owner", phase=phase, cursor=first["next_cursor"],
            )
    continue_repeat(store)
    execute_repeat(workflow, store, target=3)
    historical = workflow_repeat_iterations_page(
        workflow, "run", repeat_id, reader_user_id="owner", cursor=rounds["next_cursor"],
    )
    assert historical["total_count"] == 2 and [row["iteration"] for row in historical["iterations"]] == [1]
    history = workflow_execution_history(workflow, "run", reader_user_id="owner")
    encoded = json.dumps(history)
    assert '"state_ref"' not in encoded and '"repeat_state"' not in encoded


def test_monitoring_events_contain_only_stable_sanitized_correlation(monkeypatch):
    from functions_workflow_repeat_state import log_repeat_event

    captured = []
    monkeypatch.setitem(sys.modules, "functions_appinsights", SimpleNamespace(
        log_event=lambda message, **options: captured.append((message, options["extra"])),
    ))
    store = SimpleNamespace(identity={"workflow_id": "fictional-workflow", "run_id": "fictional-run",
                                     "scope_type": "personal", "scope_id": "fictional-owner"})
    decision = {
        "choice": "continue_repeat", "event_id": "a" * 64, "gate_id": "gate", "request_id": "request",
        "execution_id": "b" * 64, "node_id": "repeat", "actor_user_id": "fictional-owner",
        "decided_at": "2026-09-17T00:00:00+00:00", "prompt": "PRIVATE-SENTINEL",
        "repeat": {"batch_number": 1, "batch_size": 25, "completed_count": 25,
                   "exhaustion_count": 1, "continuation_count": 1, "state_ref": "PRIVATE-SENTINEL"},
    }
    log_repeat_event(store, decision)
    log_repeat_event(store, decision)
    assert captured[0] == captured[1]
    assert captured[0][1]["event_name"] == "workflow_repeat_manually_continued"
    assert "PRIVATE-SENTINEL" not in json.dumps(captured)


def test_deadline_is_rechecked_after_continuation_source_authorization(monkeypatch):
    from functions_workflow_repeat_state import prepare_repeat_grant

    workflow, store, _, clock, _ = repeat_runtime(monkeypatch, maximum=1)
    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, target=2)

    def authorize_then_expire(*args, **kwargs):
        prepared = prepare_repeat_grant(*args, **kwargs)
        clock.now += timedelta(seconds=86400)
        return prepared

    monkeypatch.setattr("functions_workflow_repeat_state.prepare_repeat_grant", authorize_then_expire)
    with pytest.raises(WorkflowRuntimeConflict) as error:
        continue_repeat(store)
    assert error.value.code == "deadline_exceeded"
    assert repeat_head(workflow, store)["continuation_count"] == 0
    assert store.read()["gate"]["choices"] == ["cancel"]
