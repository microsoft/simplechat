#!/usr/bin/env python3
# test_workflow_chat_delivery_control_pins.py
"""
Functional test for workflow chat delivery control generation pins.
Version: 0.261.226
Implemented in: 0.261.226

This test pins that terminal workflow runtime controls only advance delivery generation on resume
or tombstone, so chat delivery records reopen exactly when the durable control version really moves.
"""

import copy
import inspect
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "application" / "single_app", ROOT / "functional_tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402

from functions_workflow_alert_safety import sanitize_workflow_alert_record  # noqa: E402
from functions_workflow_chat_delivery import (  # noqa: E402
    PHASE_MESSAGE_CREATED,
    REASON_RUNTIME_MISSING,
    REASON_WORKFLOW_DELETED,
    STATUS_DELIVERED,
    STATUS_PENDING,
    STATUS_READY,
    STATUS_UNDELIVERABLE,
    control_summary,
    reconcile_chat_delivery,
)
from functions_workflow_definitions import workflow_definition_for_editor, workflow_definition_revision  # noqa: E402
from functions_workflow_runtime_store import (  # noqa: E402
    WorkflowRuntimeConflict,
    WorkflowRuntimeStore,
    RuntimeUnavailable,
    TERMINAL_STATES,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_support.workflow_chat_delivery_fakes import (  # noqa: E402
    NOW,
    RUN_ID,
    USER,
    WORKFLOW_ID,
    make_record,
    parse_iso,
    require,
)
from test_workflow_durable_execution import Clock, RuntimeContainer  # noqa: E402
from test_workflow_structured_flow import create_structured_runtime, definition  # noqa: E402


READ_ONLY = {
    "assert_owned",
    "journal_page",
    "journal_read",
    "read",
    "run_definition",
}
NON_RESUME_MUTATORS = {
    "claim",
    "decide",
    "expire_deadline",
    "heartbeat",
    "initialize",
    "journal_commit",
    "journal_commit_many",
    "journal_decide",
    "journal_request",
    "pause_execution_limit",
    "release",
    "requeue_m365",
    "requeue_output",
    "request_cancel",
    "transition",
    "update",
    "wait",
    "write_record",
}
VERSION_BUMPERS = {"resume", "tombstone"}

TERMINAL_STATE_IDS = tuple(sorted(TERMINAL_STATES))
SCHEMA_IDS = ("schema1", "schema2")
EXPECTED_REFUSALS = (WorkflowRuntimeConflict, RuntimeUnavailable, ValueError, PermissionError)


def editor_workflow(workflow):
    cleaned = {key: value for key, value in workflow.items() if not str(key).startswith("_")}
    return workflow_definition_for_editor(sanitize_workflow_alert_record(cleaned))


def with_revision(workflow):
    value = copy.deepcopy(workflow)
    value["definition_revision"] = workflow_definition_revision(editor_workflow(value))
    return value


def schema_one_runtime():
    workflow = with_revision({"id": WORKFLOW_ID, "user_id": USER, "durable_execution": True, "active_run_id": ""})
    container = RuntimeContainer()
    clock = Clock()
    store = WorkflowRuntimeStore(container, workflow, RUN_ID, clock=clock)
    store.initialize(
        snapshot_ref={"storage": "cosmos", "schema_version": 1, "sha256": "a" * 64, "size_bytes": 100, "chunk_count": 1},
        definition_revision=workflow_definition_revision(editor_workflow(workflow)),
        actor_user_id=USER,
        request_id="request-one",
    )
    return workflow, store, container, clock


def runtime_for_schema(schema_id, monkeypatch):
    if schema_id == "schema1":
        return schema_one_runtime()
    return create_structured_runtime(definition(), monkeypatch)


def terminal_runtime(schema_id, terminal_state, monkeypatch, *, advance_past_deadline=True):
    workflow, store, container, clock = runtime_for_schema(schema_id, monkeypatch)
    token = store.claim(owner_id="worker", ttl_seconds=1)
    require(token is not None, f"{schema_id}/{terminal_state}: expected the store to issue a lease")
    control = store.transition(token, state=terminal_state)
    require(control["state"] == terminal_state, f"{schema_id}/{terminal_state}: transition did not reach terminal state")
    if advance_past_deadline:
        clock.now += timedelta(days=3)
    return workflow, store, container, clock, token, control


def snapshot(control):
    return control["version"], control["state"], bool(control.get("deleted"))


def gate_id(control):
    gate = control.get("gate") if isinstance(control.get("gate"), dict) else {}
    return gate.get("id") or "gate-pin"


def initialization_args(control, *, request_id=None):
    return {
        "snapshot_ref": copy.deepcopy(control["snapshot_ref"]),
        "definition_revision": copy.deepcopy(control["definition_revision"]),
        "actor_user_id": control["actor_user_id"],
        "request_id": request_id or control["request_id"],
    }


def request_id(method, schema_id, state, index):
    return f"pin-{schema_id}-{state}-{method}-{index}"


def non_resume_calls(store, token, control, schema_id, state):
    current_version = control["version"]
    gate = gate_id(control)
    common_record = {
        "id": f"pin-record-{schema_id}-{state}",
        "run_id": store.identity["run_id"],
        "payload": {"ok": True},
    }
    waiting_gate = {
        "id": "pin-wait-gate",
        "kind": "approval",
        "choices": ["approve", "reject"],
    }
    entries = [{
        "kind": "request",
        "key": ["pin", schema_id, state],
        "payload": {"action": "cancel", "actor_user_id": USER},
        "immutable": True,
    }]
    return [
        ("claim", lambda: store.claim(owner_id="worker-two", ttl_seconds=1)),
        ("decide", lambda: store.decide(
            expected_version=current_version,
            gate_id=gate,
            choice="approve",
            actor_user_id=USER,
            request_id=request_id("decide", schema_id, state, 1),
        )),
        ("expire_deadline", store.expire_deadline),
        ("heartbeat", lambda: store.heartbeat(token, ttl_seconds=1)),
        ("initialize-replay", lambda: store.initialize(**initialization_args(control))),
        ("initialize-conflict", lambda: store.initialize(
            **initialization_args(control, request_id=request_id("initialize", schema_id, state, 1)),
        )),
        ("journal_commit", lambda: store.journal_commit(
            token,
            "request",
            ["direct-commit", schema_id, state],
            {"action": "cancel", "actor_user_id": USER},
            immutable=True,
        )),
        ("journal_commit_many", lambda: store.journal_commit_many(token, entries)),
        ("journal_decide", lambda: store.journal_decide(
            expected_version=current_version,
            gate_id=gate,
            choice="approve",
            actor_user_id=USER,
            request_id=request_id("journal-decide", schema_id, state, 1),
        )),
        ("journal_request_cancel", lambda: store.journal_request(
            "cancel",
            actor_user_id=USER,
            request_id=request_id("journal-cancel", schema_id, state, 1),
        )),
        ("journal_request_bad_action", lambda: store.journal_request(
            "pause",
            actor_user_id=USER,
            request_id=request_id("journal-pause", schema_id, state, 1),
        )),
        ("pause_execution_limit", lambda: store.pause_execution_limit(token, "deadline_exceeded")),
        ("release", lambda: store.release(token)),
        ("requeue_m365", lambda: store.requeue_m365(expected_version=current_version, gate_id=gate)),
        ("requeue_output", lambda: store.requeue_output(expected_version=current_version, gate_id=gate)),
        ("request_cancel", lambda: store.request_cancel(
            actor_user_id=USER,
            request_id=request_id("cancel", schema_id, state, 1),
        )),
        ("transition", lambda: store.transition(token, state="failed")),
        ("update", lambda: store.update(token, {"progress": {"phase": "pin"}}, expected_version=current_version)),
        ("wait", lambda: store.wait(token, state="waiting_approval", gate=waiting_gate)),
        ("write_record", lambda: store.write_record(token, common_record, immutable=True)),
    ]


def require_control_unchanged(store, before, label, log):
    after = store.read(allow_deleted=True)
    if snapshot(after) != snapshot(before):
        require(
            False,
            f"{label}: terminal control changed after non-resume call. "
            f"Before={snapshot(before)} After={snapshot(after)} Log={log}",
        )
    return after


def exercise_non_resume_mutators(store, token, schema_id, state):
    before = store.read(allow_deleted=True)
    log = []
    for index, (name, call) in enumerate(non_resume_calls(store, token, before, schema_id, state), start=1):
        outcome = "returned"
        try:
            call()
        except EXPECTED_REFUSALS as exc:
            outcome = f"raised {type(exc).__name__}"
        log.append(f"{schema_id}/{state}/{name}: {outcome}")
        before = require_control_unchanged(store, before, f"{schema_id}/{state}/{name}", log)
    return log


def delivered_record(generation):
    return make_record(
        status=STATUS_DELIVERED,
        generation=generation,
        phase=PHASE_MESSAGE_CREATED,
        message_id=f"message-{generation}",
        delivered_at=NOW,
    )


def ready_record(generation):
    return make_record(status=STATUS_READY, generation=generation)


def reconcile(record, control):
    return reconcile_chat_delivery(record, control_summary(control), now=parse_iso(NOW))


def test_version_is_at_least_the_chat_delivery_release():
    assert_app_version_at_least("0.261.226")


def test_store_public_methods_are_classified_for_terminal_generation_rules():
    public_methods = {
        name for name, member in inspect.getmembers(WorkflowRuntimeStore, callable)
        if not name.startswith("_")
    }
    classified = READ_ONLY | NON_RESUME_MUTATORS | VERSION_BUMPERS
    missing = sorted(public_methods - classified)
    unknown = sorted(classified - public_methods)
    overlaps = sorted(
        (READ_ONLY & NON_RESUME_MUTATORS)
        | (READ_ONLY & VERSION_BUMPERS)
        | (NON_RESUME_MUTATORS & VERSION_BUMPERS)
    )
    for name in missing + unknown + overlaps:
        require(
            False,
            f"Classify {name} and check the reopen rule in reconcile_chat_delivery "
            "(functions_workflow_chat_delivery.py): a terminal control's version may only move on resume or tombstone.",
        )


@pytest.mark.parametrize("schema_id", SCHEMA_IDS)
@pytest.mark.parametrize("terminal_state", TERMINAL_STATE_IDS)
def test_non_resume_mutators_leave_terminal_controls_pinned(schema_id, terminal_state, monkeypatch):
    _workflow, store, _container, _clock, token, _control = terminal_runtime(schema_id, terminal_state, monkeypatch)
    exercise_non_resume_mutators(store, token, schema_id, terminal_state)


@pytest.mark.parametrize("schema_id", SCHEMA_IDS)
@pytest.mark.parametrize("terminal_state", ["completed", "failed"])
def test_tombstone_bumps_and_then_non_resume_mutators_stay_pinned(schema_id, terminal_state, monkeypatch):
    _workflow, store, _container, _clock, token, control = terminal_runtime(schema_id, terminal_state, monkeypatch)
    before_version = control["version"]
    tombstoned = store.tombstone()
    require(tombstoned["version"] > before_version, f"{schema_id}/{terminal_state}: tombstone should bump version")
    require(tombstoned.get("deleted") is True, f"{schema_id}/{terminal_state}: tombstone should set deleted")
    require(tombstoned["state"] == "cancelled", f"{schema_id}/{terminal_state}: tombstone should cancel")
    with pytest.raises(WorkflowRuntimeConflict):
        store.read()
    allowed = store.read(allow_deleted=True)
    require(snapshot(allowed) == snapshot(tombstoned), f"{schema_id}/{terminal_state}: allow_deleted should read tombstone")
    exercise_non_resume_mutators(store, token, schema_id, f"{terminal_state}-tombstoned")


@pytest.mark.parametrize("schema_id", SCHEMA_IDS)
@pytest.mark.parametrize("terminal_state", TERMINAL_STATE_IDS)
def test_resume_is_the_only_non_delete_terminal_version_bumper(schema_id, terminal_state, monkeypatch):
    _workflow, store, _container, _clock, _token, control = terminal_runtime(
        schema_id,
        terminal_state,
        monkeypatch,
        advance_past_deadline=False,
    )
    before = snapshot(control)
    if terminal_state in {"failed", "invalid", "incomplete"}:
        with pytest.raises(WorkflowRuntimeConflict):
            store.resume(expected_version=control["version"] - 1, actor_user_id=USER, request_id="resume-stale")
        stale_after = store.read(allow_deleted=True)
        require(snapshot(stale_after) == before, f"{schema_id}/{terminal_state}: stale resume must not write")
        resumed = store.resume(expected_version=control["version"], actor_user_id=USER, request_id="resume-ok")
        require(resumed["version"] > control["version"], f"{schema_id}/{terminal_state}: resume should bump version")
        require(resumed["state"] == "queued", f"{schema_id}/{terminal_state}: resume should queue")
        require(resumed.get("deleted") is False, f"{schema_id}/{terminal_state}: resume should not delete")
    else:
        with pytest.raises(WorkflowRuntimeConflict):
            store.resume(expected_version=control["version"], actor_user_id=USER, request_id="resume-refuse")
        after = store.read(allow_deleted=True)
        require(snapshot(after) == before, f"{schema_id}/{terminal_state}: non-resumable resume must not write")


def test_delivery_reconcile_reopens_only_for_real_resume_generations(monkeypatch):
    _workflow, store, _container, _clock, token, control = terminal_runtime("schema1", "failed", monkeypatch)
    generation = control["version"]
    record = delivered_record(generation)
    for line in exercise_non_resume_mutators(store, token, "schema1", "failed-delivery"):
        updated, changed, _ready = reconcile(record, store.read(allow_deleted=True))
        require(not changed, f"{line}: delivered record should not change")
        require(updated["status"] == STATUS_DELIVERED, f"{line}: delivered record should stay delivered")

    tombstoned = store.tombstone()
    delivered_after_delete, changed, _ready = reconcile(record, tombstoned)
    require(not changed, "deleted controls must not reopen delivered records")
    require(delivered_after_delete["status"] == STATUS_DELIVERED, "delivered records stay delivered after delete")
    closed, changed, _ready = reconcile(ready_record(generation), tombstoned)
    require(changed, "ready record should close when workflow is deleted")
    require(closed["status"] == STATUS_UNDELIVERABLE, "deleted workflow should be undeliverable")
    require(closed["outcome_reason"] == REASON_WORKFLOW_DELETED, "deleted workflow reason should be pinned")

    _workflow, resume_store, _container, _clock, _token, failed = terminal_runtime(
        "schema2",
        "failed",
        monkeypatch,
        advance_past_deadline=False,
    )
    resumed = resume_store.resume(expected_version=failed["version"], actor_user_id=USER, request_id="resume-delivery")
    reopened, changed, _ready = reconcile(delivered_record(failed["version"]), resumed)
    require(changed, "resume should reopen a delivered generation")
    require(reopened["status"] == STATUS_PENDING, "resume should reset delivery to pending")
    require(reopened["generation"] is None, "resume should clear current generation")
    require(reopened["history"][-1]["generation"] == failed["version"], "resume should retain prior generation in history")

    missing_summary = control_summary(None)
    missing_closed, changed, _ready = reconcile_chat_delivery(ready_record(7), missing_summary, now=parse_iso(NOW))
    require(changed, "missing control should close a ready record")
    require(missing_closed["outcome_reason"] == REASON_RUNTIME_MISSING, "missing control reason should be pinned")
    second, changed, _ready = reconcile_chat_delivery(missing_closed, missing_summary, now=parse_iso(NOW))
    require(not changed, "missing control closure should be stable on a second reconcile")
    require(second["status"] == STATUS_UNDELIVERABLE, "missing control closure should stay undeliverable")

    deleted_summary = {
        "exists": True,
        "deleted": True,
        "version": generation + 1,
        "state": "cancelled",
        "phase": None,
        "gate_reason_code": None,
        "deadline_at": None,
        "deadline_seconds": None,
        "schema_version": 1,
    }
    guarded, changed, _ready = reconcile_chat_delivery(delivered_record(generation), deleted_summary, now=parse_iso(NOW))
    require(not changed, "deleted summary with newer version must not reopen")
    require(guarded["status"] == STATUS_DELIVERED, "deleted summary should leave delivered status")
    same_version = control_summary(control)
    guarded, changed, _ready = reconcile_chat_delivery(delivered_record(generation), same_version, now=parse_iso(NOW))
    require(not changed, "same generation must not reopen")
    require(guarded["status"] == STATUS_DELIVERED, "same generation should leave delivered status")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
