#!/usr/bin/env python3
# test_workflow_handoff_lifecycle.py
"""
Functional test for the one-time workflow hand-off lifecycle.
Version: 0.261.233
Implemented in: 0.261.233

This test ensures that a workflow handed off from chat orchestration:

* records ``one_time_status`` ``{state, run_id, completed_at}`` on every terminal transition of
  the run it was handed off for, outside the definition revision and the execution fingerprint,
  without changing ``modified_at`` or ``is_enabled``, and keeps it across an editor save;
* still finalizes its run, readies chat delivery and goes idle when recording that status fails,
  and logs only the error type;
* records nothing for another hand-off's run, a run started some other way, a workflow that isn't
  one-time, or a run that is still going;
* pauses before reviewing any document when its workspace query matches more than its limit, with
  a gate the run's deadline doesn't expire and a status row that asks the user to open the run;
* ends in chat through 6b-1 while disabled: a cancelled hand-off posts its note once, and a paused
  one that is never resumed gets the expired notice once its delivery window closes.

Checks use explicit raises, so they hold under ``python -O``.
"""

import copy
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "application" / "single_app", ROOT / "functional_tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402

import functions_workflow_chat_delivery as delivery  # noqa: E402
import functions_workflow_chat_delivery_status as status  # noqa: E402
import functions_workflow_chat_delivery_worker as worker  # noqa: E402
import functions_workflow_handoff_builder as builder  # noqa: E402
import functions_workflow_runtime as runtime  # noqa: E402
from functions_m365_workflow_binding import workflow_execution_fingerprint  # noqa: E402
from functions_workflow_alert_safety import sanitize_workflow_alert_record  # noqa: E402
from functions_workflow_definition_store import save_workflow_definition_record  # noqa: E402
from functions_workflow_definitions import workflow_definition_for_editor, workflow_definition_revision  # noqa: E402
from functions_workflow_execution import WorkflowSuspended  # noqa: E402
from functions_workflow_limits import assert_workflow_loop_item_count  # noqa: E402
from functions_workflow_runtime_store import CONTROL_ID, CONTROL_TYPE, WorkflowRuntimeStore  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_support.workflow_chat_delivery_fakes import (  # noqa: E402
    CONVERSATION_ID,
    REQUESTED_AT,
    RUN_ID,
    STEP_ID,
    USER,
    WORKFLOW_ID,
    FakeClock,
    FakeContainer,
    make_invocation,
    make_record,
    make_run,
    make_workflow,
    make_world,
    require,
    shift,
)
from test_workflow_for_each_execution import execute_loop, loop_runtime  # noqa: E402


MINIMUM_VERSION = "0.261.233"
NOW = datetime(2026, 5, 4, 15, 0, tzinfo=timezone.utc)
NOW_ISO = NOW.isoformat()
REQUEST_ID = "63e581a5-a430-4821-b1f4-1398e214fa53"
HANDOFF_ID = "handoff-1"
OTHER_HANDOFF_ID = "handoff-2"
MODIFIED_AT = "2026-05-04T14:00:00+00:00"
FINISHED_AT = "2026-05-04T15:05:00+00:00"
LABEL = "Results from `Daily digest` \u00b7 you asked on May 4, 2026 at 10:05 AM (America/New_York)"
STATUS_LOG_MESSAGE = "[WORKFLOW_RUNTIME] A one-time workflow status was not recorded."


def one_time_origin(**overrides):
    origin = {
        "source": "orchestration",
        "conversation_id": CONVERSATION_ID,
        "orchestration_run_id": "orchestration-run-1",
        "proposal_id": HANDOFF_ID,
        "created_at": NOW_ISO,
        "edited": False,
        "one_time": True,
    }
    origin.update(overrides)
    return origin


def without_private(document):
    return {key: value for key, value in document.items() if not str(key).startswith("_")}


# ---------------------------------------------------------------------------------------------
# Projection harness (from test_workflow_chat_delivery_projection_and_seed.py), for a hand-off
# ---------------------------------------------------------------------------------------------


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
        "is_enabled": False,
        "origin": one_time_origin(),
        "modified_at": MODIFIED_AT,
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


def chat_invocation(handoff_id=HANDOFF_ID):
    body = {
        "version": 1,
        "source": delivery.CHAT_TRIGGER_SOURCE,
        "conversation_id": CONVERSATION_ID,
        "user_message_id": "message-user-1",
        "orchestration_run_id": "orchestration-run-1",
        "step_id": STEP_ID,
        "requested_by": USER,
        "requested_at": NOW_ISO,
    }
    if handoff_id is not None:
        body["handoff_id"] = handoff_id
    return body


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


def run_document(*, status="queued", chat_delivery=None, runtime_version=0, invocation=True, handoff_id=HANDOFF_ID):
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
        body["chat_invocation"] = chat_invocation(handoff_id)
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
            "completed_at": FINISHED_AT,
        },
    }


def stored_definition(world):
    definition = world.definitions.get(WORKFLOW_ID)
    require(definition is not None, "the hand-off workflow must still be stored")
    return definition


def finish(world, state, version=2):
    control_doc = control(state, version)
    put_run(world, run_document(chat_delivery=pending_record(control_doc)))
    project(world, control_doc, result=terminal_result(state))
    return stored_definition(world)


# ---------------------------------------------------------------------------------------------
# A. one_time_status on terminal transitions
# ---------------------------------------------------------------------------------------------


def test_version_is_at_least_the_handoff_release():
    assert_app_version_at_least(MINIMUM_VERSION)


@pytest.mark.parametrize("state", sorted(runtime.RUNTIME_TERMINAL_STATES))
def test_each_terminal_state_records_how_the_hand_off_ended(runtime_world, state):
    before = without_private(stored_definition(runtime_world))
    require("one_time_status" not in before, "a hand-off that hasn't finished has no one-time status")

    after = without_private(finish(runtime_world, state))

    recorded = after.get("one_time_status")
    expected = {"state": state, "run_id": RUN_ID, "completed_at": after.get("last_run_at")}
    require(recorded == expected, f"{state}: one_time_status should be {expected!r}, got {recorded!r}")
    if state != "cancelled":
        require(
            after["last_run_at"] == FINISHED_AT,
            f"{state}: the status should carry the run's completion time, got {after['last_run_at']!r}",
        )
    require(isinstance(recorded["completed_at"], str) and recorded["completed_at"], "completed_at must be a timestamp")
    require(
        after["active_run_id"] == "" and after["status"] == "idle" and after["last_run_status"] == state,
        f"{state}: the hand-off workflow should be finalized and idle: {after!r}",
    )
    require(after["modified_at"] == MODIFIED_AT, f"{state}: recording the status must not change modified_at")
    require(after["is_enabled"] is False, f"{state}: recording the status must leave the workflow disabled")
    require(after["origin"] == before["origin"], f"{state}: recording the status must not touch the origin")

    without_status = {key: value for key, value in after.items() if key != "one_time_status"}
    revisions = {
        workflow_definition_revision(before),
        workflow_definition_revision(after),
        workflow_definition_revision(without_status),
    }
    require(len(revisions) == 1, f"{state}: one_time_status must stay outside the definition revision")
    fingerprints = {
        workflow_execution_fingerprint(before),
        workflow_execution_fingerprint(after),
        workflow_execution_fingerprint(without_status),
    }
    require(len(fingerprints) == 1, f"{state}: one_time_status must stay outside the execution fingerprint")


def test_a_failing_status_write_never_breaks_finalization(runtime_world, monkeypatch):
    logged = []

    def explode(*_args, **_kwargs):
        raise RuntimeError("secret one-time failure text")

    def record_log(message, extra=None, level=None, **kwargs):
        logged.append({"message": message, "extra": copy.deepcopy(extra), "level": level, **kwargs})

    monkeypatch.setattr(runtime, "_one_time_status_value", explode)
    monkeypatch.setattr(runtime, "log_event", record_log)

    after = finish(runtime_world, "completed")
    run = stored_run(runtime_world)
    hints = delivery.drain_workflow_chat_delivery_hints()

    require("one_time_status" not in after, "a failed status write records nothing")
    require(
        after["active_run_id"] == "" and after["status"] == "idle"
        and after["last_run_id"] == RUN_ID and after["last_run_status"] == "completed",
        f"the run must still be finalized when the status write fails: {after!r}",
    )
    require(after["modified_at"] == MODIFIED_AT, "a failed status write must not change modified_at")
    require(run["status"] == "completed" and run["runtime_version"] == 2, f"the run document must be finalized: {run!r}")
    require(
        run[delivery.CHAT_DELIVERY_KEY]["status"] == delivery.STATUS_READY,
        "chat delivery must still become ready when the status write fails",
    )
    require(hints == [(USER, RUN_ID)], f"chat delivery must still be signalled once, got {hints!r}")

    warnings = [entry for entry in logged if entry["message"] == STATUS_LOG_MESSAGE]
    require(len(warnings) == 1, f"the failed status write should be logged once, got {logged!r}")
    require(warnings[0]["extra"] == {"error_type": "RuntimeError"}, f"the log must carry only the error type: {warnings!r}")
    require("secret one-time failure text" not in repr(logged), "the log must not carry exception text")


def _rewrite_definition(world, **overrides):
    world.definitions.put(workflow(**overrides))


@pytest.mark.parametrize("case", [
    "workflow_not_one_time",
    "chat_proposal_workflow",
    "other_hand_off_run",
    "run_without_hand_off_id",
    "run_without_chat_invocation",
    "another_run_is_active",
])
def test_nothing_is_recorded_for_a_run_the_workflow_was_not_handed_off_for(runtime_world, case):
    world = runtime_world
    invocation, handoff_id = True, HANDOFF_ID
    if case == "workflow_not_one_time":
        _rewrite_definition(world, origin=one_time_origin(one_time=False))
    elif case == "chat_proposal_workflow":
        origin = one_time_origin()
        origin.pop("one_time")
        _rewrite_definition(world, origin=origin, is_enabled=True)
    elif case == "other_hand_off_run":
        handoff_id = OTHER_HANDOFF_ID
    elif case == "run_without_hand_off_id":
        handoff_id = None
    elif case == "run_without_chat_invocation":
        invocation = False
    else:
        _rewrite_definition(world, active_run_id="run-other")
    before = without_private(stored_definition(world))
    control_doc = control("completed", 2)
    put_run(world, run_document(chat_delivery=pending_record(control_doc), invocation=invocation, handoff_id=handoff_id))

    project(world, control_doc, result=terminal_result("completed"))
    after = without_private(stored_definition(world))

    require("one_time_status" not in after, f"{case}: no one-time status may be recorded, got {after!r}")
    if case == "another_run_is_active":
        require(after == before, f"{case}: the definition must not be written at all")
    else:
        require(
            after["active_run_id"] == "" and after["last_run_status"] == "completed",
            f"{case}: the run must still be finalized: {after!r}",
        )


@pytest.mark.parametrize("state", ["running", "waiting_output", "paused"])
def test_a_run_that_is_still_going_records_nothing(runtime_world, state):
    control_doc = control(state, 2)
    put_run(runtime_world, run_document(chat_delivery=pending_record(control_doc)))

    project(runtime_world, control_doc)
    after = stored_definition(runtime_world)

    require("one_time_status" not in after, f"{state}: a run that is still going records no one-time status")
    require(after["active_run_id"] == RUN_ID and after["status"] == state, f"{state}: the run stays active: {after!r}")


def test_a_resumed_hand_off_records_its_later_ending(runtime_world):
    failed = finish(runtime_world, "failed")
    require(failed["one_time_status"]["state"] == "failed", "the first ending is recorded")
    run_count = failed["run_count"]

    resumed = without_private(failed)
    resumed.update(active_run_id=RUN_ID, active_runtime_version=2, status="queued")
    runtime_world.definitions.put(resumed)
    after = finish(runtime_world, "completed", version=3)

    require(
        after["one_time_status"] == {"state": "completed", "run_id": RUN_ID, "completed_at": FINISHED_AT},
        f"a resumed hand-off records how it finally ended, got {after['one_time_status']!r}",
    )
    require(after["run_count"] == run_count, "a resumed run is the same run, so it isn't counted again")


def test_an_editor_save_keeps_the_stored_status(runtime_world):
    stored = finish(runtime_world, "completed")
    recorded = copy.deepcopy(stored["one_time_status"])
    opened = workflow_definition_for_editor(without_private(stored))

    edited = copy.deepcopy(opened)
    edited["name"] = "Daily digest, renamed"
    edited["one_time_status"] = {"state": "failed", "run_id": "run-forged", "completed_at": NOW_ISO}
    save_workflow_definition_record(runtime_world.definitions, USER, edited, opened)
    saved = stored_definition(runtime_world)

    require(saved["name"] == "Daily digest, renamed", "the editor save must apply the edit")
    require(saved["one_time_status"] == recorded, f"an editor save must keep the stored status, got {saved['one_time_status']!r}")

    omitted = workflow_definition_for_editor(without_private(saved))
    edited = {key: value for key, value in omitted.items() if key != "one_time_status"}
    edited["name"] = "Daily digest, renamed again"
    save_workflow_definition_record(runtime_world.definitions, USER, edited, omitted)
    saved = stored_definition(runtime_world)

    require(saved["one_time_status"] == recorded, "a save that omits the status must keep the stored status")


# ---------------------------------------------------------------------------------------------
# B. A query that outgrows its limit pauses the hand-off before any review
# ---------------------------------------------------------------------------------------------


QUERY_BLUEPRINT = {
    "name": "Review all",
    "loop": {
        "source": "workspace_query",
        "scopes": ["scope-me"],
        "tags": ["legal"],
        "selection": "all_matches",
        "content": "indemnity",
    },
    "tasks": [
        {"title": "Review one", "instructions": "Review this contract."},
        {"title": "Report", "instructions": "Write the report."},
    ],
}
QUERY_HANDLES = {
    "documents": {},
    "scopes": {"scope-me": {"scope_type": "personal", "scope_id": "owner"}},
    "agents": {},
}


def _derived_id(workflow_id, kind, key):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"test-handoff:{workflow_id}:{kind}:{key}"))


def handoff_query_definition(max_items=10):
    definition = builder.build_handoff_definition(
        copy.deepcopy(QUERY_BLUEPRINT), copy.deepcopy(QUERY_HANDLES),
        workflow_id="workflow", max_items=max_items, derived_id=_derived_id,
        alert_fields=lambda _alerts, _workflow_id: {"alert_mode": "rules"},
    )
    definition.update(id="workflow", user_id="owner")
    return definition


def paused_handoff(monkeypatch):
    workflow_doc, store, _container, clock = loop_runtime(monkeypatch, definition=handoff_query_definition())
    queries = []

    def more_than_the_limit(_workflow, iterable, *, limit, **_kwargs):
        queries.append({"kind": iterable.get("kind"), "limit": limit})
        assert_workflow_loop_item_count(limit + 1, limit=limit, count_exact=False)
        raise AssertionError("the fake query must report more matches than the limit")

    monkeypatch.setattr("functions_workflow_loop_inputs._query_documents", more_than_the_limit)
    calls = []
    suspended = None
    try:
        execute_loop(workflow_doc, store, [], calls=calls)
    except WorkflowSuspended as exc:
        suspended = exc
    return SimpleNamespace(store=store, clock=clock, queries=queries, calls=calls, suspended=suspended)


def test_a_query_over_the_limit_pauses_before_reviewing_any_document(monkeypatch):
    run = paused_handoff(monkeypatch)
    control_doc = run.store.read()
    gate = control_doc.get("gate") or {}

    require(run.suspended is not None, "a hand-off whose query outgrows its limit must suspend")
    require(run.queries == [{"kind": "workspace_query", "limit": 10}], f"the query runs once at the limit: {run.queries!r}")
    require(run.calls == [], f"no document may be reviewed: {run.calls!r}")
    require(control_doc["state"] == "paused", f"the hand-off pauses, got {control_doc['state']!r}")
    require(gate.get("kind") == "pause" and gate.get("choices") == ["cancel"], f"the only choice is to cancel: {gate!r}")
    require(gate.get("reason_code") is None, f"the pause has no reason code a deadline expiry reads: {gate!r}")
    reason = str(gate.get("reason") or "")
    require("11" in reason and "10" in reason, f"the pause says how many matched and how many are allowed: {reason!r}")


def test_the_run_deadline_does_not_expire_the_paused_hand_off(monkeypatch):
    run = paused_handoff(monkeypatch)
    before = run.store.read()
    require(before.get("schema_version") == 2 and before.get("deadline_at"), "a v3 hand-off run has a deadline")

    run.clock.now = datetime.fromisoformat(before["deadline_at"]) + timedelta(seconds=1)
    run.store.expire_deadline()
    after = run.store.read()

    require(after["state"] == "paused", f"the deadline leaves the paused hand-off paused, got {after['state']!r}")
    require(after["version"] == before["version"], "the deadline check writes nothing")
    require(after["gate"] == before["gate"], "the deadline check keeps the pause gate")


# ---------------------------------------------------------------------------------------------
# C. The paused, disabled hand-off in 6b-1's status route
# ---------------------------------------------------------------------------------------------


def _path_value(document, dotted):
    current = document
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None, False
        current = current[part]
    return current, True


def _projection_pairs(query):
    import re

    select = re.search(r"SELECT TOP \d+ (.*?) FROM c ", query)
    require(select is not None, f"query must have a SELECT projection: {query!r}")
    pairs = re.findall(r"c\.([A-Za-z0-9_.]+) AS ([A-Za-z0-9_]+)", select.group(1))
    require(pairs, "status query must project aliased paths")
    return pairs, int(re.search(r"SELECT TOP (\d+)", query).group(1))


def status_query_handler(_container, query, params, partition_key):
    require(partition_key == params.get("@user_id"), "status query must use the signed-in user's partition")
    require("IS_DEFINED(c.chat_invocation)" in query, "status query must keep the chat invocation filter")
    pairs, top = _projection_pairs(query)
    rows = []
    for item in _container.items.values():
        invocation = item.get("chat_invocation")
        if item.get("user_id") != params.get("@user_id") or item.get("trigger_source") != params.get("@source"):
            continue
        if not isinstance(invocation, dict) or not invocation.get("requested_at"):
            continue
        if "@conversation_id" in params and invocation.get("conversation_id") != params["@conversation_id"]:
            continue
        rows.append(item)
    rows.sort(key=lambda row: str((row.get("chat_invocation") or {}).get("requested_at") or ""), reverse=True)
    projected = []
    for row in rows[:top]:
        entry = {}
        for path, alias in pairs:
            value, present = _path_value(row, path)
            if present:
                entry[alias] = copy.deepcopy(value)
        projected.append(entry)
    return projected


def with_revision(workflow_doc):
    value = copy.deepcopy(workflow_doc)
    cleaned = without_private(value)
    value["definition_revision"] = workflow_definition_revision(
        workflow_definition_for_editor(sanitize_workflow_alert_record(cleaned))
    )
    return value


def disabled_handoff_workflow():
    return make_workflow(is_enabled=False, origin=one_time_origin())


def test_the_status_route_shows_the_paused_disabled_hand_off_as_needing_the_user():
    run = make_run(
        status="paused",
        chat_invocation=make_invocation(handoff_id=HANDOFF_ID),
        chat_delivery=make_record(),
        runtime={"version": 4, "state": "paused", "can_resume": False, "gate": {"id": "gate-1"}},
        runtime_version=4,
        started_at=shift(REQUESTED_AT, minutes=-5),
    )
    live_calls = []

    def live_status(workflow_doc, run_id, *, reader_user_id):
        live_calls.append({"is_enabled": workflow_doc.get("is_enabled"), "run_id": run_id, "reader": reader_user_id})
        return None

    services = status.WorkflowRunStatusServices(
        runs=FakeContainer("runs", [run], query_handler=status_query_handler),
        workflows=FakeContainer("workflows", [with_revision(disabled_handoff_workflow())]),
        get_settings=lambda: {
            "enable_chat_orchestration": True,
            "allow_user_workflows": True,
            "require_member_of_workflow_user": False,
        },
        settings_gate=lambda _value: None,
        live_status=live_status,
        clock=FakeClock(),
    )

    payload = status.workflow_run_status_payload(USER, [CONVERSATION_ID], services=services)
    rows = payload.get("runs") or []

    require(len(rows) == 1, f"the hand-off run must show in its chat's status, got {payload!r}")
    row = rows[0]
    require(row["status"] == "waiting" and row["phase"] == "needs_you", f"a paused hand-off needs the user: {row!r}")
    require(
        row["waiting"] == {"reason": "paused", "action": status.WAITING_ACTION_OPEN_RUN, "gate_id": "gate-1"},
        f"the user is sent to the run to cancel it: {row['waiting']!r}",
    )
    actions = row["actions"]
    require(
        actions["cancel"] is True and actions["approve"] is False
        and actions["open_run"] is True and actions["retry"] is False,
        f"a paused hand-off can be cancelled or opened, nothing else: {actions!r}",
    )
    require(
        row.get("error") is None and row.get("error_code") is None and row.get("retry_blocked") is None,
        f"a paused hand-off reports no error: {row!r}",
    )
    require(
        live_calls == [{"is_enabled": False, "run_id": RUN_ID, "reader": USER}],
        f"the status route reads the disabled workflow's live status: {live_calls!r}",
    )


# ---------------------------------------------------------------------------------------------
# D. How a disabled hand-off ends in chat through 6b-1
# ---------------------------------------------------------------------------------------------


def handoff_delivery_world(state, *, version=5):
    world = make_world(
        run=make_run(status=state, chat_invocation=make_invocation(handoff_id=HANDOFF_ID)),
        state=state,
        version=version,
    )
    world.workflows.put(disabled_handoff_workflow())
    return world


def deliver(world):
    return worker.process_workflow_chat_delivery(USER, RUN_ID, services=world.services)


def expired_notice():
    return {
        "type": "workflow_chat_delivery",
        "user_id": USER,
        "title": "\"Daily digest\" didn't finish in time to post to chat",
        "message": delivery.EXPIRED_NOTICE_MESSAGE,
        "link_url": f"/workflow-activity?workflowId={WORKFLOW_ID}&runId={RUN_ID}&scope=personal",
        "metadata": {
            "workflow_id": WORKFLOW_ID,
            "run_id": RUN_ID,
            "workflow_scope": "personal",
            "delivery_status": "expired",
        },
        "idempotency_key": f"workflow-chat-delivery-notice:{RUN_ID}:expired",
        "strict": True,
    }


def test_a_cancelled_hand_off_posts_its_note_once():
    world = handoff_delivery_world("cancelled")

    first = deliver(world)
    messages = world.delivery_messages()
    second = deliver(world)
    again = world.delivery_messages()

    require(first == worker.OUTCOME_DELIVERED, f"the cancelled hand-off's note is delivered, got {first!r}")
    require(len(messages) == 1, f"exactly one note is posted, got {messages!r}")
    expected = delivery.assemble_delivery_content(LABEL, delivery.delivery_note_text(delivery.KIND_CANCELLED, "Daily digest"))
    require(messages[0]["content"] == expected, f"the note says the run was cancelled: {messages[0]['content']!r}")
    require(messages[0]["metadata"]["workflow_delivery"]["kind"] == delivery.KIND_CANCELLED, "the note is a cancelled note")
    require(world.reader.calls == [], "a cancelled run's results are never read")
    require(second != worker.OUTCOME_DELIVERED and len(again) == 1, f"a second delivery posts nothing: {second!r}")


def test_a_paused_hand_off_waits_then_gets_the_expired_notice():
    world = handoff_delivery_world("paused", version=4)

    waiting = deliver(world)
    pending = world.record()

    require(waiting == worker.OUTCOME_PENDING, f"a paused hand-off waits for the user, got {waiting!r}")
    require(pending["status"] == delivery.STATUS_PENDING, f"its delivery stays pending: {pending['status']!r}")
    require(world.delivery_messages() == [], "nothing is posted while the hand-off is paused")

    world.clock.now = shift(pending["expires_at"], seconds=1)
    expired = deliver(world)
    record = world.record()

    require(expired == worker.OUTCOME_EXPIRED, f"an unresumed hand-off expires with its window, got {expired!r}")
    require(world.delivery_messages() == [], "an expired hand-off posts nothing to chat")
    require(world.notifications.notice_calls == [expired_notice()], f"one expired notice: {world.notifications.notice_calls!r}")
    require(record["status"] == "expired" and record["notice_kind"] == "expired", f"the record closes as expired: {record!r}")


def test_only_a_deadline_pause_expires_at_once():
    world = handoff_delivery_world("paused", version=4)
    world.runtime.set(state="paused", version=4, gate_reason_code="deadline_exceeded")

    outcome = deliver(world)

    require(outcome == worker.OUTCOME_EXPIRED, f"a deadline pause expires at once, unlike the hand-off pause: {outcome!r}")
    require(world.notifications.notice_calls == [expired_notice()], "the deadline pause gets the expired notice")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
