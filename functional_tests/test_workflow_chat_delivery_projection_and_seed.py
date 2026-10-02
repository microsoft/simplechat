#!/usr/bin/env python3
# test_workflow_chat_delivery_projection_and_seed.py
"""
Functional test for workflow chat delivery projection and seeding.
Version: 0.261.226
Implemented in: 0.261.226

This test ensures chat-started workflow runs seed delivery records and runtime projection reconciles them without blocking durable progress.
"""

import copy
import importlib
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "application" / "single_app", ROOT / "functional_tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402

import functions_workflow_chat_delivery as delivery  # noqa: E402
import functions_workflow_runtime as runtime  # noqa: E402
from functions_workflow_runtime_store import CONTROL_ID, CONTROL_TYPE, WorkflowRuntimeStore  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_support.workflow_chat_delivery_fakes import (  # noqa: E402
    CONVERSATION_ID,
    RUN_ID,
    STEP_ID,
    USER,
    WORKFLOW_ID,
    FakeCheckFailed,
    FakeContainer,
    require,
)


NOW = datetime(2026, 5, 4, 15, 0, tzinfo=timezone.utc)
NOW_ISO = NOW.isoformat()
REQUEST_ID = "63e581a5-a430-4821-b1f4-1398e214fa53"


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now

    def set(self, value):
        self.now = value


def workflow(**overrides):
    body = {
        "id": WORKFLOW_ID,
        "user_id": USER,
        "name": "Daily digest",
        "task_prompt": "Summarize the daily digest.",
        "durable_execution": True,
        "definition_version": 1,
        "active_run_id": RUN_ID,
        "active_runtime_version": 1,
        "status": "queued",
    }
    body.update(overrides)
    return body


def definition_revision():
    return runtime.workflow_definition_revision(workflow(active_run_id="", active_runtime_version=0, status="idle"))


def control(state="queued", version=1, *, schema_version=1, deleted=False, **overrides):
    body = {
        "id": CONTROL_ID,
        "type": CONTROL_TYPE,
        "item_type": CONTROL_TYPE,
        "kind": "run",
        "schema_version": schema_version,
        "workflow_id": WORKFLOW_ID,
        "user_id": USER,
        "group_id": None,
        "scope_type": "personal",
        "scope_id": USER,
        "run_id": RUN_ID,
        "snapshot_ref": {"kind": "test-snapshot"},
        "definition_revision": definition_revision(),
        "actor_user_id": USER,
        "request_id": REQUEST_ID,
        "created_at": NOW_ISO,
        "updated_at": NOW_ISO,
        "state": state,
        "version": version,
        "units": {},
        "memory": {},
        "gate": None,
        "lease": None,
        "deleted": deleted,
    }
    body.update(overrides)
    return body


def chat_invocation():
    return {
        "version": 1,
        "source": delivery.CHAT_TRIGGER_SOURCE,
        "conversation_id": CONVERSATION_ID,
        "user_message_id": "message-user-1",
        "orchestration_run_id": "orchestration-run-1",
        "step_id": STEP_ID,
        "requested_by": USER,
        "requested_at": NOW_ISO,
    }


def pending_record(control_doc=None):
    seed = delivery.build_chat_delivery_seed(
        time_zone="America/New_York",
        model_selection={"model": {"model_deployment": "gpt-4o"}, "reasoning_effort": "medium"},
        requester_roles=["WorkflowUser"],
        now=NOW,
    )
    record = delivery.finalize_chat_delivery_seed(seed, control_doc or control())
    record["expires_at"] = "2099-01-01T00:00:00+00:00"
    return record


def run_document(*, status="queued", chat_delivery=None, runtime_version=0, invocation=True):
    body = {
        "id": RUN_ID,
        "workflow_id": WORKFLOW_ID,
        "workflow_name": "Daily digest",
        "user_id": USER,
        "workspace_type": "personal",
        "trigger_source": delivery.CHAT_TRIGGER_SOURCE,
        "triggered_by": USER,
        "durable_execution": True,
        "status": status,
        "success": False,
        "definition_version": 1,
        "started_at": NOW_ISO,
        "completed_at": None,
        "definition_revision": definition_revision(),
        "runtime_version": runtime_version,
    }
    if invocation:
        body["chat_invocation"] = chat_invocation()
    if chat_delivery is not None:
        body[delivery.CHAT_DELIVERY_KEY] = copy.deepcopy(chat_delivery)
    return body


@pytest.fixture(autouse=True)
def clean_hints():
    delivery.clear_workflow_chat_delivery_hints()
    yield
    delivery.clear_workflow_chat_delivery_hints()


@pytest.fixture
def runtime_world(monkeypatch):
    clock = Clock()
    wf = workflow()
    definitions = FakeContainer("definitions", [wf], clock=lambda: clock().isoformat())
    runs = FakeContainer("runs", clock=lambda: clock().isoformat())
    controls = FakeContainer("controls", clock=lambda: clock().isoformat())
    snapshots = {}
    state = SimpleNamespace(
        clock=clock,
        workflow=wf,
        definitions=definitions,
        runs=runs,
        controls=controls,
        snapshots=snapshots,
    )

    def services(_workflow):
        return {
            "definitions": definitions,
            "runs": runs,
            "partition": USER,
            "load_workflow": lambda: definitions.read_item(item=WORKFLOW_ID, partition_key=USER),
            "settings": lambda: {"allow_user_workflows": True},
        }

    def make_store(current_workflow, run_id):
        return WorkflowRuntimeStore(controls, current_workflow, run_id, clock=clock)

    def save_result(_workflow, run_id, task_id, result, **_kwargs):
        reference = {"kind": "test-result", "run_id": run_id, "task_id": task_id}
        snapshots[(run_id, task_id)] = copy.deepcopy(result)
        return reference

    def load_result(_workflow, run_id, task_id, reference):
        if isinstance(reference, dict) and (reference.get("run_id"), reference.get("task_id")) in snapshots:
            return copy.deepcopy(snapshots[(reference["run_id"], reference["task_id"])])
        return copy.deepcopy(wf)

    monkeypatch.setattr(runtime, "_services", services)
    monkeypatch.setattr(runtime, "_authorize_execution", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runtime, "workflow_runtime_store", make_store)
    monkeypatch.setattr(runtime, "save_workflow_task_result", save_result)
    monkeypatch.setattr(runtime, "load_workflow_task_result", load_result)
    monkeypatch.setattr(runtime, "delete_workflow_run_results", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        runtime,
        "workflow_runtime_status",
        lambda current_workflow, run_id, *, reader_user_id: runtime.workflow_runtime_projection(
            make_store(current_workflow, run_id).read()
        ),
    )
    return state


def put_control(world, body):
    world.controls.put(body)
    return copy.deepcopy(body)


def put_run(world, body):
    world.runs.put(body)
    return copy.deepcopy(body)


def stored_run(world):
    return world.runs.read_item(item=RUN_ID, partition_key=USER)


def project(world, control_doc, *, result=None):
    put_control(world, control_doc)
    return runtime._project_runtime_run(  # noqa: SLF001 - functional test pins projection contract.
        {"definitions": world.definitions, "runs": world.runs, "partition": USER, "load_workflow": lambda: world.workflow},
        world.workflow,
        RUN_ID,
        control_doc,
        result=result,
    )


def terminal_result(state):
    return {
        "run": {
            "status": state,
            "success": state in {"completed", "completed_partial"},
            "completed_at": "2026-05-04T15:05:00+00:00",
        },
    }


def test_version_is_at_least_the_chat_delivery_release():
    assert_app_version_at_least("0.261.226")


def test_projection_reconciles_terminal_states_and_signals_once(runtime_world):
    cases = [
        ("completed", delivery.KIND_RESULT),
        ("failed", delivery.KIND_FAILED),
        ("cancelled", delivery.KIND_CANCELLED),
    ]
    for index, (state, expected_kind) in enumerate(cases, start=1):
        delivery.clear_workflow_chat_delivery_hints()
        runtime_world.controls.items.clear()
        runtime_world.runs.items.clear()
        control_doc = control(state=state, version=10 + index)
        put_run(runtime_world, run_document(chat_delivery=pending_record(control_doc)))
        project(runtime_world, control_doc, result=terminal_result(state))
        saved = stored_run(runtime_world)
        record = saved[delivery.CHAT_DELIVERY_KEY]
        require(record["status"] == delivery.STATUS_READY, f"{state} should make chat delivery ready")
        require(record["kind"] == expected_kind, f"{state} should map to {expected_kind}")
        require(record["generation"] == control_doc["version"], f"{state} should use the control version")
        hints = delivery.drain_workflow_chat_delivery_hints()
        require(hints == [(USER, RUN_ID)], f"{state} should queue exactly one in-process delivery hint")

    delivery.clear_workflow_chat_delivery_hints()
    runtime_world.controls.items.clear()
    runtime_world.runs.items.clear()
    waiting = control(state="waiting_output", version=30)
    put_run(runtime_world, run_document(chat_delivery=pending_record(waiting)))
    project(runtime_world, waiting)
    saved = stored_run(runtime_world)
    require(saved[delivery.CHAT_DELIVERY_KEY]["status"] == delivery.STATUS_PENDING, "waiting runs must stay pending")
    hints = delivery.drain_workflow_chat_delivery_hints()
    require(hints == [], "waiting runs must not queue a delivery hint")


def test_projection_keeps_stored_chat_delivery_before_reconciling(runtime_world):
    control_doc = control(state="completed", version=7)
    stored_record = pending_record(control_doc)
    stored_record["time_zone"] = "America/Los_Angeles"
    stale_record = pending_record(control_doc)
    stale_record["time_zone"] = "UTC"
    put_run(runtime_world, run_document(chat_delivery=stored_record))
    result = terminal_result("completed")
    result["run"][delivery.CHAT_DELIVERY_KEY] = stale_record
    project(runtime_world, control_doc, result=result)
    record = stored_run(runtime_world)[delivery.CHAT_DELIVERY_KEY]
    require(record["time_zone"] == "America/Los_Angeles", "stored chat_delivery must win over result payload copies")
    require(record["status"] == delivery.STATUS_READY, "the preserved stored record should still be reconciled")


def test_projection_without_chat_delivery_does_not_create_record_or_hint(runtime_world):
    control_doc = control(state="completed", version=4)
    put_run(runtime_world, run_document(invocation=False))
    project(runtime_world, control_doc, result=terminal_result("completed"))
    saved = stored_run(runtime_world)
    require(delivery.CHAT_DELIVERY_KEY not in saved, "non-chat-started runs must not gain chat_delivery")
    hints = delivery.drain_workflow_chat_delivery_hints()
    require(hints == [], "non-chat-started runs must not queue a delivery hint")


def test_projection_drops_result_chat_delivery_when_stored_run_has_none(runtime_world):
    control_doc = control(state="completed", version=4)
    delivery.clear_workflow_chat_delivery_hints()
    put_run(runtime_world, run_document(invocation=False))
    result = terminal_result("completed")
    result["run"][delivery.CHAT_DELIVERY_KEY] = pending_record(control_doc)
    project(runtime_world, control_doc, result=result)
    saved = stored_run(runtime_world)
    require(
        delivery.CHAT_DELIVERY_KEY not in saved,
        f"runtime result chat_delivery must not be saved when the stored run has none: {saved!r}",
    )
    hints = delivery.drain_workflow_chat_delivery_hints()
    require(hints == [], f"discarded runtime result chat_delivery must not queue a delivery hint: {hints!r}")


def test_projection_survives_reconcile_failure_and_still_writes_runtime(monkeypatch, runtime_world):
    control_doc = control(state="completed", version=8)
    original_record = pending_record(control_doc)
    put_run(runtime_world, run_document(chat_delivery=original_record))

    def fail_reconcile(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(runtime, "reconcile_chat_delivery", fail_reconcile)
    try:
        projected = project(runtime_world, control_doc, result=terminal_result("completed"))
    except AssertionError:
        raise
    except Exception as exc:
        raise FakeCheckFailed(
            f"a delivery reconcile failure must never fail the runtime projection; the projection raised {exc!r}"
        ) from exc
    saved = stored_run(runtime_world)
    require(projected["status"] == "completed", "projection should return normally after reconcile failure")
    require(saved["status"] == "completed", "projection should still write terminal runtime status")
    require(saved["runtime_version"] == control_doc["version"], "projection should still write runtime version")
    require(saved[delivery.CHAT_DELIVERY_KEY] == original_record, "reconcile failure should leave stored record unchanged")


def test_projection_survives_broken_hint_queue_and_direct_signal_returns_false(monkeypatch, runtime_world):
    class BrokenLock:
        def __enter__(self):
            raise RuntimeError("lock unavailable")

        def __exit__(self, *_args):
            return False

    control_doc = control(state="completed", version=9)
    put_run(runtime_world, run_document(chat_delivery=pending_record(control_doc)))
    monkeypatch.setattr(delivery, "_HINT_LOCK", BrokenLock())
    try:
        direct = delivery.signal_workflow_chat_delivery(USER, RUN_ID)
    except AssertionError:
        raise
    except Exception as exc:
        raise FakeCheckFailed(
            f"signaling a delivery hint must never raise, even when the hint queue is broken; it raised {exc!r}"
        ) from exc
    require(direct is False, "direct signal should fail closed when hint internals raise")
    try:
        projected = project(runtime_world, control_doc, result=terminal_result("completed"))
    except AssertionError:
        raise
    except Exception as exc:
        raise FakeCheckFailed(
            f"a broken delivery hint queue must never fail the runtime projection; the projection raised {exc!r}"
        ) from exc
    saved = stored_run(runtime_world)
    record = saved[delivery.CHAT_DELIVERY_KEY]
    require(projected["status"] == "completed", "projection should return normally when hint signaling fails")
    require(record["status"] == delivery.STATUS_READY, "ready record must be persisted even when signal fails")
    require(record["next_attempt_at"] is None, "a later sweep can find the ready record immediately")


def test_resume_reopens_delivered_generation_and_expired_never_reopens(runtime_world):
    failed = control(state="failed", version=5)
    delivered = pending_record(failed)
    delivered.update({
        "status": delivery.STATUS_DELIVERED,
        "generation": 5,
        "kind": delivery.KIND_FAILED,
        "message_id": "assistant-delivery-1",
        "delivered_at": "2026-05-04T15:10:00+00:00",
    })
    put_control(runtime_world, failed)
    put_run(runtime_world, run_document(status="failed", chat_delivery=delivered, runtime_version=5))
    request_id = str(uuid.uuid4())
    runtime.decide_workflow_runtime(
        runtime_world.workflow,
        RUN_ID,
        {"expected_version": 5, "request_id": request_id},
        actor_user_id=USER,
        resume=True,
    )
    reopened = stored_run(runtime_world)[delivery.CHAT_DELIVERY_KEY]
    require(reopened["status"] == delivery.STATUS_PENDING, "resume should reopen a delivered previous generation")
    require(reopened["generation"] is None, "reopened records wait for the next terminal generation")
    require(len(reopened["history"]) == 1, "resume should archive the previous delivered outcome")
    require(reopened["history"][0]["generation"] == 5, "history should preserve the delivered generation")

    runtime_world.controls.items.clear()
    runtime_world.runs.items.clear()
    later = control(state="completed", version=8)
    expired = pending_record(later)
    expired.update({"status": delivery.STATUS_EXPIRED, "generation": 5, "kind": delivery.KIND_EXPIRED})
    put_run(runtime_world, run_document(chat_delivery=expired, runtime_version=5))
    project(runtime_world, later, result=terminal_result("completed"))
    record = stored_run(runtime_world)[delivery.CHAT_DELIVERY_KEY]
    require(record["status"] == delivery.STATUS_EXPIRED, "expired records must not reopen on a later projection")
    require(record["generation"] == 5, "expired records should preserve their closed generation")


def test_deleted_control_closes_delivery_as_workflow_deleted_without_hint(runtime_world):
    deleted = control(state="cancelled", version=3, deleted=True)
    body = run_document(chat_delivery=pending_record(deleted))
    ready = runtime._reconcile_chat_delivery(body, deleted, RUN_ID)  # noqa: SLF001 - pins runtime reconcile wrapper.
    record = body[delivery.CHAT_DELIVERY_KEY]
    require(ready is False, "deleted controls should not signal delivery")
    require(record["status"] == delivery.STATUS_UNDELIVERABLE, "deleted controls should close as undeliverable")
    require(record["outcome_reason"] == delivery.REASON_WORKFLOW_DELETED, "deleted controls should use workflow_deleted")
    hints = delivery.drain_workflow_chat_delivery_hints()
    require(hints == [], "deleted controls should not queue hints")


def test_deadline_expiration_projects_expired_kind(runtime_world):
    deadline = (NOW - timedelta(minutes=1)).isoformat()
    schema_two = control(
        state="queued",
        version=2,
        schema_version=2,
        cursor={"region_id": "flow", "node_id": "node-1"},
        journal_counts={},
        completed_unit_count=0,
        admitted_count=0,
        max_executions=10,
        deadline_seconds=60,
        deadline_at=deadline,
        snapshot_identity={"node_id": "flow", "execution_id": "execution-1", "attempt": 1, "iteration_path": []},
    )
    put_control(runtime_world, schema_two)
    put_run(runtime_world, run_document(chat_delivery=pending_record(schema_two)))
    store = WorkflowRuntimeStore(runtime_world.controls, runtime_world.workflow, RUN_ID, clock=runtime_world.clock)
    expired_control = store.expire_deadline()
    project(runtime_world, expired_control)
    record = stored_run(runtime_world)[delivery.CHAT_DELIVERY_KEY]
    require(expired_control["state"] == "paused", "deadline expiry should pause the schema-v2 control")
    require(record["status"] == delivery.STATUS_READY, "deadline-expired controls should be ready for notice delivery")
    require(record["kind"] == delivery.KIND_EXPIRED, "deadline-expired controls should project the expired kind")
    require(record["generation"] == expired_control["version"], "deadline-expired generation should match control version")


def test_chat_delivery_seed_gates_fields_and_logs_warning(monkeypatch):
    wr = importlib.import_module("functions_orchestration_workflow_runs")
    settings_module = ModuleType("functions_settings")
    settings_module.is_chat_workflow_results_enabled_for_user = lambda settings, user_roles=None: True
    monkeypatch.setitem(sys.modules, "functions_settings", settings_module)
    logs = []
    monkeypatch.setattr(wr, "_log", lambda *args, **kwargs: logs.append((args, kwargs)))
    context = SimpleNamespace(
        user_roles=["WorkflowUser", "WorkflowUser", "", "Admin"],
        time_zone="America/New_York",
        seeds={
            "model": {
                "model_deployment": "gpt-4o",
                "model_provider": "aoai",
                "model_endpoint_id": "endpoint-1",
                "model_id": "model-1",
            },
            "reasoning_effort": "high",
            "active_group_ids": ["group-1", "group-1", "group-2"],
        },
        active_group_ids=["fallback-group"],
        run_id="orchestration-run-1",
    )

    closed = wr._chat_delivery_seed({}, context, {"time_zone": "UTC"})  # noqa: SLF001
    require(closed is None, "closed workflow-results setting should not create a seed")
    off = wr._chat_delivery_seed({"enable_chat_workflow_results": False}, context, {"time_zone": "UTC"})  # noqa: SLF001
    require(off is None, "6a results gate off should not create a seed")
    seed = wr._chat_delivery_seed({"enable_chat_workflow_results": True}, context, {"time_zone": "UTC"})  # noqa: SLF001
    require(seed["time_zone"] == "America/New_York", "context time zone should win when present")
    require(seed["model_selection"]["model"]["model_deployment"] == "gpt-4o", "model deployment should be normalized")
    require(seed["model_selection"]["reasoning_effort"] == "high", "reasoning effort should be normalized")
    require(seed["model_selection"]["active_group_ids"] == ["group-1", "group-2"], "active groups should be deduped")
    require(seed["requester_roles"] == ["WorkflowUser", "Admin"], "requester roles should be normalized")

    fallback_context = SimpleNamespace(user_roles=[], time_zone=None, seeds={}, active_group_ids=[])
    fallback = wr._chat_delivery_seed(  # noqa: SLF001
        {"enable_chat_workflow_results": True},
        fallback_context,
        {"time_zone": "Europe/Berlin"},
    )
    require(fallback["time_zone"] == "Europe/Berlin", "planning time zone should be used as fallback")

    def fail_gate(_settings, user_roles=None):
        raise RuntimeError("gate failed")

    monkeypatch.setattr(settings_module, "is_chat_workflow_results_enabled_for_user", fail_gate)
    failed = wr._chat_delivery_seed({"enable_chat_workflow_results": True}, context, {"time_zone": "UTC"})  # noqa: SLF001
    require(failed is None, "seed gate exceptions should fail closed")
    require(logs, "seed gate exceptions should be warning-logged")


def test_queue_durable_workflow_run_finalizes_chat_delivery_seed(monkeypatch, runtime_world):
    monkeypatch.setattr(runtime, "_now", lambda: NOW_ISO)
    runtime_world.definitions.items.clear()
    runtime_world.definitions.put(workflow(active_run_id="", active_runtime_version=0, status="idle"))
    seed = pending_record(control())
    queued = runtime.queue_durable_workflow_run(
        {"id": WORKFLOW_ID, "user_id": USER},
        actor_user_id=USER,
        request_id=REQUEST_ID,
        chat_invocation=chat_invocation(),
        chat_delivery=seed,
    )
    record = queued["run"][delivery.CHAT_DELIVERY_KEY]
    require(record["status"] == delivery.STATUS_PENDING, "queued chat delivery should start pending")
    require(isinstance(record["expires_at"], str) and record["expires_at"], "queued chat delivery should have expires_at")
    require(queued["run"]["chat_invocation"]["requested_at"] == NOW_ISO, "chat invocation should preserve requested_at")

    other_world = runtime_world
    other_world.controls.items.clear()
    other_world.runs.items.clear()
    other_world.definitions.items.clear()
    other_world.definitions.put(workflow(active_run_id="", active_runtime_version=0))
    without = runtime.queue_durable_workflow_run(
        {"id": WORKFLOW_ID, "user_id": USER},
        actor_user_id=USER,
        request_id=str(uuid.uuid4()),
        chat_invocation=chat_invocation(),
    )
    require(delivery.CHAT_DELIVERY_KEY not in without["run"], "queue without a seed must not add chat_delivery")


def test_start_sets_chat_delivery_sidecar_only_when_seed_applies(monkeypatch):
    wr = importlib.import_module("functions_orchestration_workflow_runs")
    settings_module = ModuleType("functions_settings")
    settings_module.is_user_workflows_enabled_for_user = lambda settings, user_roles=None: True
    settings_module.is_chat_workflow_results_enabled_for_user = lambda settings, user_roles=None: True
    monkeypatch.setitem(sys.modules, "functions_settings", settings_module)
    monkeypatch.setattr(wr, "_read_conversation", lambda conversation_id: {"id": conversation_id, "user_id": USER})
    monkeypatch.setattr(wr, "refresh_workflow_planning_privacy", lambda planning, conversation, user_id: planning)
    monkeypatch.setattr(wr, "_read_workflow", lambda user_id, workflow_id: workflow(id=workflow_id, active_run_id=""))
    monkeypatch.setattr(wr, "_read_workflow_run", lambda user_id, run_id: None)
    step = {"step_id": STEP_ID, "capability_id": wr.CAPABILITY_WORKFLOW_RUN, "arguments": {"workflow": "digest"}}
    planning = {
        "conversation_private": True,
        "time_zone": "America/New_York",
        "workflow_runs": {"ready": True},
        "handles": {"workflows": {"digest": {"id": WORKFLOW_ID, "name": "Daily digest"}}},
        "catalog": {"workflows": [{"handle": "digest", "name": "Daily digest"}]},
    }
    context = SimpleNamespace(
        conversation_id=CONVERSATION_ID,
        workflow_planning=planning,
        signed_in_session=True,
        user_roles=["WorkflowUser"],
        run_id="orchestration-run-1",
        attempt_root_run_id="orchestration-run-1",
        user_message_id="message-user-1",
        seeds={},
        active_group_ids=[],
        time_zone="America/New_York",
    )
    queued_options = []

    def queue_run(_workflow, **options):
        queued_options.append(copy.deepcopy(options))
        chat_delivery = options.get("chat_delivery")
        run = run_document(
            chat_delivery=delivery.finalize_chat_delivery_seed(chat_delivery, control())
            if chat_delivery is not None else None
        )
        run["chat_invocation"] = copy.deepcopy(options["chat_invocation"])
        return {"run": run}

    monkeypatch.setattr(wr, "_queue_workflow_run", queue_run)
    settings = {
        "enable_chat_orchestration": True,
        "enable_chat_orchestration_workflow_runs": True,
        "allow_user_workflows": True,
        "enable_chat_workflow_results": True,
        "chat_orchestration_enabled_capabilities": [wr.CAPABILITY_WORKFLOW_RUN],
    }
    outcome = wr._start(step, context, settings=settings, user_id=USER, recheck=lambda: None, requested_at=NOW_ISO)  # noqa: SLF001
    sidecar = wr._sidecar(step, context, user_id=USER, producer_run_id=context.run_id, outcome=outcome)  # noqa: SLF001
    require(outcome.get("chat_delivery") is True, f"start outcome should flag applicable chat delivery: {outcome!r}")
    require(sidecar.get("chat_delivery") is True, "sidecar should flag applicable chat delivery")
    require(delivery.CHAT_DELIVERY_KEY in queued_options[0], "start should pass the seed when the 6a gate is on")

    queued_options.clear()
    off_settings = dict(settings, enable_chat_workflow_results=False)
    outcome_off = wr._start(step, context, settings=off_settings, user_id=USER, recheck=lambda: None, requested_at=NOW_ISO)  # noqa: SLF001
    sidecar_off = wr._sidecar(step, context, user_id=USER, producer_run_id=context.run_id, outcome=outcome_off)  # noqa: SLF001
    require(
        outcome_off["status"] == wr.WORKFLOW_RUN_STATUS_QUEUED,
        f"6a gate off should still reach a queued workflow start, got {outcome_off!r}",
    )
    require(outcome_off.get("chat_delivery") is not True, "start outcome must not flag delivery when 6a gate is off")
    require("chat_delivery" not in sidecar_off, "sidecar must not flag delivery when 6a gate is off")
    require(delivery.CHAT_DELIVERY_KEY not in queued_options[0], "start must not pass a seed when the 6a gate is off")


def _workflow_start_harness(monkeypatch):
    """Wire _start to a private chat, an idle durable workflow and both gates on; return (wr, start)."""
    wr = importlib.import_module("functions_orchestration_workflow_runs")
    settings_module = ModuleType("functions_settings")
    settings_module.is_user_workflows_enabled_for_user = lambda settings, user_roles=None: True
    settings_module.is_chat_workflow_results_enabled_for_user = lambda settings, user_roles=None: True
    monkeypatch.setitem(sys.modules, "functions_settings", settings_module)
    monkeypatch.setattr(wr, "_read_conversation", lambda conversation_id: {"id": conversation_id, "user_id": USER})
    monkeypatch.setattr(wr, "refresh_workflow_planning_privacy", lambda planning, conversation, user_id: planning)
    monkeypatch.setattr(wr, "_read_workflow", lambda user_id, workflow_id: workflow(id=workflow_id, active_run_id=""))
    monkeypatch.setattr(wr, "_read_workflow_run", lambda user_id, run_id: None)
    step = {"step_id": STEP_ID, "capability_id": wr.CAPABILITY_WORKFLOW_RUN, "arguments": {"workflow": "digest"}}
    planning = {
        "conversation_private": True,
        "time_zone": "America/New_York",
        "workflow_runs": {"ready": True},
        "handles": {"workflows": {"digest": {"id": WORKFLOW_ID, "name": "Daily digest"}}},
        "catalog": {"workflows": [{"handle": "digest", "name": "Daily digest"}]},
    }
    context = SimpleNamespace(
        conversation_id=CONVERSATION_ID,
        workflow_planning=planning,
        signed_in_session=True,
        user_roles=["WorkflowUser"],
        run_id="orchestration-run-1",
        attempt_root_run_id="orchestration-run-1",
        user_message_id="message-user-1",
        seeds={},
        active_group_ids=[],
        time_zone="America/New_York",
    )
    settings = {
        "enable_chat_orchestration": True,
        "enable_chat_orchestration_workflow_runs": True,
        "allow_user_workflows": True,
        "enable_chat_workflow_results": True,
        "chat_orchestration_enabled_capabilities": [wr.CAPABILITY_WORKFLOW_RUN],
    }

    def start(build_run):
        """Start the step against a queue fake that returns build_run(options); return (outcome, sidecar)."""

        def queue_run(_workflow, **options):
            return {"run": build_run(options)}

        monkeypatch.setattr(wr, "_queue_workflow_run", queue_run)
        outcome = wr._start(step, context, settings=settings, user_id=USER, recheck=lambda: None, requested_at=NOW_ISO)  # noqa: SLF001
        sidecar = wr._sidecar(step, context, user_id=USER, producer_run_id=context.run_id, outcome=outcome)  # noqa: SLF001
        return outcome, sidecar

    return wr, start


def test_start_does_not_flag_completed_already_started_run_for_delivery(monkeypatch):
    wr, start = _workflow_start_harness(monkeypatch)

    def completed_run(options):
        record = delivery.finalize_chat_delivery_seed(options["chat_delivery"], control(state="completed"))
        run = run_document(status="completed", chat_delivery=record)
        run["chat_invocation"] = copy.deepcopy(options["chat_invocation"])
        return run

    outcome, sidecar = start(completed_run)
    require(
        outcome["status"] == wr.WORKFLOW_RUN_STATUS_ALREADY_STARTED,
        f"completed queued result should be classified as already_started, got {outcome!r}",
    )
    require(
        outcome.get("chat_delivery") is not True,
        f"already-started terminal runs must not flag chat delivery on the start outcome: {outcome!r}",
    )
    require(
        "chat_delivery" not in sidecar,
        f"already-started terminal runs must not flag chat delivery on the sidecar: {sidecar!r}",
    )


def test_start_requires_queued_run_delivery_record_to_apply_before_flagging(monkeypatch):
    wr, start = _workflow_start_harness(monkeypatch)
    cases = [
        ("missing record", lambda options: run_document()),
        (
            "other conversation",
            lambda options: {
                **run_document(chat_delivery=delivery.finalize_chat_delivery_seed(options["chat_delivery"], control())),
                "chat_invocation": {**chat_invocation(), "conversation_id": "other-chat"},
            },
        ),
        (
            "wrong record version",
            lambda options: {
                **run_document(chat_delivery={
                    **delivery.finalize_chat_delivery_seed(options["chat_delivery"], control()),
                    "version": 999,
                }),
                "chat_invocation": chat_invocation(),
            },
        ),
    ]

    for label, build_run in cases:
        outcome, sidecar = start(build_run)
        require(
            outcome["status"] == wr.WORKFLOW_RUN_STATUS_QUEUED,
            f"{label} should still start the workflow as queued, got {outcome!r}",
        )
        require(
            outcome.get("chat_delivery") is not True,
            f"{label} must not flag chat delivery on the start outcome: {outcome!r}",
        )
        require("chat_delivery" not in sidecar, f"{label} must not flag chat delivery on the sidecar: {sidecar!r}")
        note = wr.workflow_run_note(
            {
                "steps": [{
                    "step_id": STEP_ID,
                    "capability_id": wr.CAPABILITY_WORKFLOW_RUN,
                    "arguments": {"workflow": "digest"},
                }],
            },
            [{
                "step_id": STEP_ID,
                "capability_id": wr.CAPABILITY_WORKFLOW_RUN,
                "status": wr.STEP_STATUS_COMPLETED,
                "workflow_run": sidecar,
            }],
        )
        require(wr.WORKFLOW_RUN_FOLLOW_UP in note, f"{label} should use the plain follow-up text: {note!r}")
        require(
            wr.WORKFLOW_RUN_DELIVERY_FOLLOW_UP not in note,
            f"{label} must not promise chat delivery in the note: {note!r}",
        )

def test_workflow_run_note_uses_delivery_follow_up_texts():
    wr = importlib.import_module("functions_orchestration_workflow_runs")
    one_plan = {
        "steps": [{"step_id": "run-one", "capability_id": wr.CAPABILITY_WORKFLOW_RUN, "arguments": {"workflow": "digest"}}],
    }
    one_record = [{
        "step_id": "run-one",
        "capability_id": wr.CAPABILITY_WORKFLOW_RUN,
        "status": wr.STEP_STATUS_COMPLETED,
        "workflow_run": {"status": wr.WORKFLOW_RUN_STATUS_QUEUED, "name": "Daily digest", "chat_delivery": True},
    }]
    one = wr.workflow_run_note(one_plan, one_record)
    require(wr.WORKFLOW_RUN_DELIVERY_FOLLOW_UP in one, "one delivered run should use the delivery follow-up")

    many_plan = {
        "steps": [
            {"step_id": "run-one", "capability_id": wr.CAPABILITY_WORKFLOW_RUN, "arguments": {"workflow": "digest"}},
            {"step_id": "run-two", "capability_id": wr.CAPABILITY_WORKFLOW_RUN, "arguments": {"workflow": "digest2"}},
        ],
    }
    many_records = [
        {
            "step_id": "run-one",
            "capability_id": wr.CAPABILITY_WORKFLOW_RUN,
            "status": wr.STEP_STATUS_COMPLETED,
            "workflow_run": {"status": wr.WORKFLOW_RUN_STATUS_QUEUED, "name": "Daily digest", "chat_delivery": True},
        },
        {
            "step_id": "run-two",
            "capability_id": wr.CAPABILITY_WORKFLOW_RUN,
            "status": wr.STEP_STATUS_COMPLETED,
            "workflow_run": {"status": wr.WORKFLOW_RUN_STATUS_QUEUED, "name": "Weekly digest", "chat_delivery": True},
        },
    ]
    many = wr.workflow_run_note(many_plan, many_records)
    require(wr.WORKFLOW_RUN_DELIVERY_FOLLOW_UP_MANY in many, "many delivered runs should use the many delivery follow-up")

    mixed_many_records = copy.deepcopy(many_records)
    mixed_many_records[1]["workflow_run"].pop("chat_delivery")
    mixed_many = wr.workflow_run_note(many_plan, mixed_many_records)
    require(
        wr.WORKFLOW_RUN_FOLLOW_UP_MANY in mixed_many,
        f"mixed delivery across multiple started runs should use the plain many follow-up: {mixed_many!r}",
    )
    require(
        wr.WORKFLOW_RUN_DELIVERY_FOLLOW_UP_MANY not in mixed_many,
        f"mixed delivery across multiple started runs must not use the delivery many follow-up: {mixed_many!r}",
    )

    without_delivery_records = copy.deepcopy(one_record)
    without_delivery_records[0]["workflow_run"].pop("chat_delivery")
    without = wr.workflow_run_note(one_plan, without_delivery_records)
    require(wr.WORKFLOW_RUN_FOLLOW_UP in without, "runs without delivery should use the original follow-up")
    require(wr.WORKFLOW_RUN_DELIVERY_FOLLOW_UP not in without, "original follow-up should be byte-for-byte distinct")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
