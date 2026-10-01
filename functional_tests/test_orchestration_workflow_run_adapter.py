#!/usr/bin/env python3
# test_orchestration_workflow_run_adapter.py
"""
Functional test for the chat orchestration workflow_run step adapter.
Version: 0.261.212
Implemented in: 0.261.212

This test ensures that a plan's workflow_run step starts the requester's saved durable workflow
through the durable queue at most once. The request id comes from the plan's first attempt and
the step, so a second tab, a retry that reuses or re-executes the step, and a crash between
queueing and saving the step all link the run the plan already started instead of queueing
another. A new plan starts a new run. The run the plan started is looked up before anything is
queued, so a later active run never hides it.

Every refusal maps to a closed reason and no exception text: settings, role, a shared chat, a
missing, foreign, deleting, not durable or Microsoft 365-waiting workflow, runtime conflicts,
a tombstoned request, lost access and an unrunnable definition. Storage outages fail the step
retryably. The run records who asked in chat_invocation and leaves mcp_invocation to MCP. The
step's workflow and run ids stay on the server, its retained result carries only the name and
status, and the adapter runs on a plain thread with no Flask context.
"""

import ast
import hashlib
import importlib
import json
import threading
import uuid
from copy import copy, deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from flask import has_app_context, has_request_context

from test_orchestration_harness_routes import modules, real_http_harness  # noqa: F401
from test_orchestration_workflow_run_approval_floor import CONVERSATION, FLOOR, _assert_waits_for_the_user
from test_orchestration_workflow_run_capability import (  # noqa: F401
    HOSTILE_NAME,
    WORKFLOW_RUN,
    _assert_logs_carry_codes_only,
    _handle,
    _run,
    planning,
)
from test_orchestration_workflow_run_planning_context import (  # noqa: F401
    DIGEST_ID,
    DIGEST_REQUEST,
    NOT_DURABLE_ID,
    NOW,
    OWNER,
    PRIVATE,
    PROPOSALS_ONLY,
    RUN_SETTINGS,
    RUNS,
    SHARED_CHANGES,
    _build,
    _frames,
    _readers,
    _workflows,
    wf,
)
from test_support.orchestration_harness_execution import HarnessEnvironment, compose_step, decoded_frames, input_binding
from test_support.orchestration_revisions import AtomicMemoryContainer
from test_support.versioning import assert_app_version_at_least


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
SECRET = "private storage detail 5f1c"

# Pinned so a change to how a plan's request id or run id is derived fails here: a different
# derivation would start a second run for a plan approved before the change.
NAMESPACE = "650ed228-1040-5f47-8898-4c9af42c2cde"
REQUEST_ID = "023264b5-a9ca-5c85-a03e-f351f8b7f984"      # plan attempt "run-1", step "run_digest"
RUN_ID = "88417c5f-aa7b-5964-a897-cba2212302ec"          # OWNER's Weekly digest for REQUEST_ID
REQUEST_ID_9 = "5e28d2ed-1ba3-5cf4-95ce-4e8099f073b3"    # plan attempt "run-9", step "run_digest"
RUN_ID_9 = "25449996-f279-5dd4-a6f4-7109f2cf0dc7"
GROUP_RUN_ID = "1ac370ec-51c0-5be3-aacc-12eba6bcb846"    # the same request for a group-7 workflow
STARTED = {"queued", "running", "already_started"}
STARTED_SUMMARY = "Started the saved workflow."
LINKED_SUMMARY = "Linked the run this plan already started for the saved workflow."
NOT_STARTED_SUMMARY = "The saved workflow was not started."


def test_the_version_includes_workflow_runs_from_chat():
    assert_app_version_at_least("0.261.212")


# ---------------------------------------------------------------------------
# Storage and runtime doubles
# ---------------------------------------------------------------------------

class Items(AtomicMemoryContainer):
    """A memory container that records point reads and can fail the next one."""

    def __init__(self, partition_field):
        super().__init__(partition_field)
        self.reads = []
        self.read_error = None

    def read_item(self, item, partition_key):
        self.reads.append((partition_key, item))
        error, self.read_error = self.read_error, None
        if error is not None:
            raise error
        return super().read_item(item, partition_key)

    def delete_item(self, item, partition_key, **kwargs):
        # The runtime deletes an unbound run record without an etag.
        with self._lock:
            super().read_item(item, partition_key)
            del self.items[(partition_key, item)]

    def get(self, partition, item_id):
        record = self.items.get((partition, item_id))
        return deepcopy(record) if record is not None else None

    def patch(self, partition, item_id, **changes):
        record = {key: value for key, value in self.items[(partition, item_id)].items() if not key.startswith("_")}
        self.upsert_item({**record, **changes})


@pytest.fixture
def wr(modules):
    return importlib.import_module("functions_orchestration_workflow_runs")


@pytest.fixture
def world(modules, monkeypatch):
    """The real durable queue over memory containers for OWNER's saved workflows."""
    runtime = importlib.import_module("functions_workflow_runtime")
    store = importlib.import_module("functions_workflow_runtime_store")
    config = importlib.import_module("config")
    definitions, runs, controls = Items("user_id"), Items("user_id"), Items("run_id")
    for workflow in _workflows():
        definitions.upsert_item({**workflow, "user_id": OWNER, "active_run_id": "", "status": "idle"})
    state = SimpleNamespace(
        definitions=definitions, runs=runs, controls=controls, settings={"allow_user_workflows": True},
        snapshots={}, deleted_results=[], queued=[], contexts=[],
        fail_queue=None, after_queue=None, after_load=None,
    )

    def services(workflow):
        assert not workflow.get("group_id")
        user_id, workflow_id = workflow["user_id"], workflow["id"]

        def load_workflow():
            try:
                current = definitions.read_item(item=workflow_id, partition_key=user_id)
            except CosmosResourceNotFoundError:
                return None
            hook, state.after_load = state.after_load, None
            if hook:
                hook()
            return current

        return {
            "definitions": definitions, "runs": runs, "partition": user_id,
            "load_workflow": load_workflow, "settings": lambda: dict(state.settings),
        }

    def save(workflow, run_id, task_id, result, *, settings=None):
        reference = {"kind": "test-result", "run_id": run_id, "task_id": task_id}
        state.snapshots[(run_id, task_id)] = deepcopy(result)
        return reference

    def load(workflow, run_id, task_id, reference):
        return deepcopy(state.snapshots[(reference["run_id"], reference["task_id"])])

    real_queue = runtime.queue_durable_workflow_run

    def queue(workflow, **options):
        state.queued.append(deepcopy(options))
        state.contexts.append((has_app_context(), has_request_context(), threading.current_thread().name))
        error, state.fail_queue = state.fail_queue, None
        if error is not None:
            raise error
        queued = real_queue(workflow, **options)
        hook, state.after_queue = state.after_queue, None
        if hook:
            hook()
        return queued

    monkeypatch.setattr(runtime, "_services", services)
    monkeypatch.setattr(
        runtime, "workflow_runtime_store",
        lambda workflow, run_id: store.WorkflowRuntimeStore(controls, workflow, run_id, clock=lambda: NOW),
    )
    monkeypatch.setattr(runtime, "save_workflow_task_result", save)
    monkeypatch.setattr(runtime, "load_workflow_task_result", load)
    monkeypatch.setattr(runtime, "delete_workflow_run_results",
                        lambda workflow, run_id: state.deleted_results.append(run_id))
    monkeypatch.setattr(runtime, "queue_durable_workflow_run", queue)
    monkeypatch.setattr(config, "cosmos_personal_workflows_container", definitions, raising=False)
    monkeypatch.setattr(config, "cosmos_personal_workflow_runs_container", runs, raising=False)
    return state


@pytest.fixture
def chat(modules, monkeypatch):
    """The requester's private conversation, for the adapter's own point read."""
    config = importlib.import_module("config")
    conversations = Items("id")
    conversations.upsert_item(deepcopy(PRIVATE))
    monkeypatch.setattr(config, "cosmos_conversations_container", conversations, raising=False)
    return conversations


@pytest.fixture
def adapter(wr, monkeypatch):
    """The adapter module with a stand-in result service and recorded logs. Returns ``(module, logs)``."""
    logs = []
    monkeypatch.setattr(wr, "require_result_service", lambda context: context.result_service)
    monkeypatch.setattr(wr, "log_event", lambda message, **kwargs: logs.append((message, kwargs)))
    return wr, logs


class _Service:
    """The retained-result service the step writes through, recording each authorization and write."""

    def __init__(self):
        self.authorized = []
        self.persisted = []
        self.fail_persist = None
        self.access = SimpleNamespace(authorize_producer=self._authorize)

    def _authorize(self, producer, for_write=False):
        self.authorized.append((producer.user_id, for_write))

    def persist_task_result(
        self, *, producer, role, status, outputs, sources, origin, guard_token, upstream, input_fingerprint,
    ):
        error, self.fail_persist = self.fail_persist, None
        if error is not None:
            raise error
        self.persisted.append({
            "user_id": producer.user_id, "role": role, "status": status, "sources": list(sources),
            "origin": origin, "guard_token": guard_token, "upstream": tuple(upstream),
            "input_fingerprint": input_fingerprint,
            "outputs": [(output.name, output.kind, deepcopy(output.value)) for output in outputs],
        })


def _context(planning, service, *, run_id="run-1", root="run-1", roles=("User",), signed_in=True, guards=None,
             producer_user=OWNER, contract_version=2):
    producer = SimpleNamespace(user_id=producer_user, run_id=run_id, step_id="run_digest", conversation_id=CONVERSATION)
    tokens = iter(guards) if guards is not None else None
    return SimpleNamespace(
        result_service=service, plan_contract_version=contract_version, run_id=run_id, attempt_root_run_id=root,
        conversation_id=CONVERSATION, user_message_id="user-turn-1", workflow_planning=planning,
        user_roles=list(roles), signed_in_session=signed_in, result_producer=lambda step: producer,
        result_guard_token_for_step=(lambda step_id: next(tokens)) if tokens is not None else (lambda step_id: "guard-1"),
        result_input_fingerprint_for_step=lambda step_id: "fingerprint-1",
    )


def _call(module, planning, *, name="Weekly digest", step=None, settings=RUN_SETTINGS, user_id=OWNER, cancel=None,
          service=None, **options):
    """Run the production step adapter once. Returns ``(result, service)``."""
    service = service or _Service()
    context = _context(planning, service, **options)
    step = step or _run(_handle(planning, name))
    result = module.adapter_workflow_run(
        step, context, settings=deepcopy(settings), user_id=user_id, cancel_requested=cancel,
    )
    return result, service


def _sidecar(planning, status, *, reason=None, name="Weekly digest", workflow_id=DIGEST_ID, run_id=RUN_ID,
             orchestration_run_id="run-1", root="run-1"):
    return {
        "version": 1, "step_id": "run_digest", "orchestration_run_id": orchestration_run_id,
        "attempt_root_run_id": root, "conversation_id": CONVERSATION, "requested_by": OWNER,
        "handle": _handle(planning, name), "workflow_id": workflow_id,
        "run_id": run_id if status in STARTED else None, "name": name, "status": status, "reason": reason,
    }


def _retained(module, status, *, reason=None, name="Weekly digest"):
    return [(module.WORKFLOW_RUN_OUTPUT, module.WORKFLOW_RUN_OUTPUT_KIND,
             {"version": 1, "name": name, "status": status, "reason": reason})]


def _unavailable(result, planning, reason, *, workflow_id=DIGEST_ID, name="Weekly digest", **options):
    assert result["status"] == "completed" and result["summary"] == NOT_STARTED_SUMMARY
    assert result["workflow_run"] == _sidecar(planning, "unavailable", reason=reason, name=name,
                                              workflow_id=workflow_id, **options)


def _failed(result, code):
    assert result["status"] == "failed" and result["failure"]["code"] == code
    assert "workflow_run" not in result and "task_result" not in result


def _no_run_started(world):
    assert world.runs.items == {} and world.controls.items == {}
    assert world.definitions.get(OWNER, DIGEST_ID)["active_run_id"] == ""


# ---------------------------------------------------------------------------
# Request ids, run ids and links
# ---------------------------------------------------------------------------

def test_the_request_and_run_ids_are_pinned_and_match_the_queue(wr):
    runtime = importlib.import_module("functions_workflow_runtime")
    assert str(wr.WORKFLOW_RUN_REQUEST_NAMESPACE) == NAMESPACE
    assert wr.WORKFLOW_RUN_REQUEST_NAMESPACE == uuid.uuid5(uuid.NAMESPACE_URL, "urn:simplechat:orchestration-workflow-runs")
    first = wr.workflow_run_request_id("run-1", "run_digest")
    ninth = wr.workflow_run_request_id("run-9", "run_digest")
    other_step = wr.workflow_run_request_id("run-1", "run_watcher")
    assert (first, ninth) == (REQUEST_ID, REQUEST_ID_9)
    assert other_step not in (REQUEST_ID, REQUEST_ID_9)

    personal = {"id": DIGEST_ID, "user_id": OWNER}
    computed = [
        runtime.workflow_run_id_for_request(personal, request_id)
        for request_id in (REQUEST_ID, REQUEST_ID.upper(), "{" + REQUEST_ID + "}", REQUEST_ID_9)
    ]
    assert computed == [RUN_ID, RUN_ID, RUN_ID, RUN_ID_9]
    group = runtime.workflow_run_id_for_request({**personal, "group_id": "group-7"}, REQUEST_ID)
    assert group == GROUP_RUN_ID
    # The same formula the queue uses when it creates the run.
    queued = runtime._run_id(OWNER, DIGEST_ID, runtime._request_id(REQUEST_ID))
    assert queued == RUN_ID

    for request_id in (None, 7, "", "not-a-uuid"):
        with pytest.raises(ValueError):
            runtime.workflow_run_id_for_request(personal, request_id)
    for root, step_id in ((None, "run_digest"), ("", "run_digest"), (5, "run_digest"), ("run-1", None), ("run-1", "")):
        with pytest.raises(ValueError):
            wr.workflow_run_request_id(root, step_id)


def test_the_started_run_id_is_the_queue_formula_for_the_first_attempt_and_step(wr):
    started = wr.started_workflow_run_id(OWNER, DIGEST_ID, attempt_root_run_id="run-1", step_id="run_digest")
    ninth = wr.started_workflow_run_id(OWNER, DIGEST_ID, attempt_root_run_id="run-9", step_id="run_digest")
    assert (started, ninth) == (RUN_ID, RUN_ID_9)
    for root, step_id in ((None, "run_digest"), ("", "run_digest"), ("run-1", None)):
        with pytest.raises(ValueError):
            wr.started_workflow_run_id(OWNER, DIGEST_ID, attempt_root_run_id=root, step_id=step_id)


def test_a_link_is_computed_from_the_handle_the_first_attempt_and_the_step(adapter, planning):
    module, logs = adapter
    handle = _handle(planning, "Weekly digest")
    good = {"user_id": OWNER, "attempt_root_run_id": "run-1", "step_id": "run_digest"}
    link = module.workflow_run_link(planning, handle, **good)
    assert link == {"workflow_id": DIGEST_ID, "run_id": RUN_ID}
    ninth = module.workflow_run_link(planning, handle, **{**good, "attempt_root_run_id": "run-9"})
    assert ninth == {"workflow_id": DIGEST_ID, "run_id": RUN_ID_9}

    missing = [
        module.workflow_run_link(planning, "wf-unknown-000000", **good),
        module.workflow_run_link(planning, None, **good),
        module.workflow_run_link(None, handle, **good),
        module.workflow_run_link({}, handle, **good),
    ]
    for change in ({"user_id": ""}, {"user_id": None}, {"attempt_root_run_id": ""},
                   {"attempt_root_run_id": None}, {"step_id": ""}):
        missing.append(module.workflow_run_link(planning, handle, **{**good, **change}))
    assert missing == [None] * 9
    assert logs and {entry[1]["extra"]["error_type"] for entry in logs} == {"ValueError"}
    _assert_logs_carry_codes_only(logs, planning)


# ---------------------------------------------------------------------------
# Starting and linking
# ---------------------------------------------------------------------------

def test_the_step_starts_the_workflow_once_and_links_it_when_asked_again(adapter, world, chat, planning):
    module, logs = adapter
    result, service = _call(module, planning)

    assert result["status"] == "completed" and result["summary"] == STARTED_SUMMARY
    assert result["workflow_run"] == _sidecar(planning, "queued")
    assert service.persisted == [{
        "user_id": OWNER, "role": "gather", "status": "complete", "sources": [], "origin": "generated",
        "guard_token": "guard-1", "upstream": (), "input_fingerprint": "fingerprint-1",
        "outputs": _retained(module, "queued"),
    }]
    assert (module.WORKFLOW_RUN_OUTPUT, module.WORKFLOW_RUN_OUTPUT_KIND) == ("run", "structured-v1")
    # Authorized to write when the step began and again just before the queue.
    assert service.authorized == [(OWNER, True), (OWNER, True)]

    assert len(world.queued) == 1
    options = world.queued[0]
    requested_at = options["chat_invocation"].pop("requested_at")
    assert datetime.fromisoformat(requested_at).utcoffset().total_seconds() == 0
    assert options == {
        "actor_user_id": OWNER, "trigger_source": "chat_orchestration", "request_id": REQUEST_ID,
        "chat_invocation": {
            "version": 1, "source": "chat_orchestration", "conversation_id": CONVERSATION,
            "user_message_id": "user-turn-1", "orchestration_run_id": "run-1", "attempt_root_run_id": "run-1",
            "step_id": "run_digest", "requested_by": OWNER,
        },
    }

    run = world.runs.get(OWNER, RUN_ID)
    assert (run["workflow_id"], run["user_id"], run["status"]) == (DIGEST_ID, OWNER, "queued")
    assert (run["trigger_source"], run["triggered_by"]) == ("chat_orchestration", OWNER)
    assert run["chat_invocation"] == {**options["chat_invocation"], "requested_at": requested_at}
    assert "mcp_invocation" not in run
    workflow = world.definitions.get(OWNER, DIGEST_ID)
    # Starting a paused workflow runs it once, as the Run button does; it stays paused.
    assert (workflow["active_run_id"], workflow["status"], workflow["is_enabled"]) == (RUN_ID, "queued", False)

    # Reached again, as from a second tab or a repeated request: the run is linked, never queued again.
    again, service = _call(module, planning)
    assert again["status"] == "completed" and again["summary"] == LINKED_SUMMARY
    assert again["workflow_run"] == _sidecar(planning, "already_started")
    assert service.persisted[0]["outputs"] == _retained(module, "already_started")
    assert service.authorized == [(OWNER, True), (OWNER, True)]
    assert len(world.queued) == 1 and list(world.runs.items) == [(OWNER, RUN_ID)]
    _assert_logs_carry_codes_only(logs, planning)
    assert all(DIGEST_ID not in json.dumps(entry, default=str) for entry in logs)


@pytest.mark.parametrize("state, expected", [
    ("running", "running"), ("queued", "queued"), ("completed", "already_started"), ("failed", "already_started"),
])
def test_the_start_status_is_what_the_queue_returned(adapter, world, chat, planning, monkeypatch, state, expected):
    module, _logs = adapter
    runtime = importlib.import_module("functions_workflow_runtime")
    queued = []

    def queue(workflow, **options):
        queued.append(options["request_id"])
        return {"success": True, "run": {"id": RUN_ID, "status": state}}

    monkeypatch.setattr(runtime, "queue_durable_workflow_run", queue)
    result, _service = _call(module, planning)
    assert queued == [REQUEST_ID]
    assert result["workflow_run"] == _sidecar(planning, expected)
    assert result["summary"] == (LINKED_SUMMARY if expected == "already_started" else STARTED_SUMMARY)


def test_a_retry_of_the_plan_links_the_run_its_first_attempt_started(adapter, world, chat, planning):
    module, _logs = adapter
    _call(module, planning)
    # A recovery retry is a new run of the plan that keeps its first attempt as its root.
    retry, service = _call(module, planning, run_id="run-2", root="run-1")
    assert retry["workflow_run"] == _sidecar(planning, "already_started", orchestration_run_id="run-2")
    assert len(world.queued) == 1 and list(world.runs.items) == [(OWNER, RUN_ID)]
    assert service.persisted[0]["outputs"] == _retained(module, "already_started")

    # A root that is missing or not a string falls back to the run itself.
    for root in (None, "", 5):
        fallback, _service = _call(module, planning, run_id="run-1", root=root)
        assert fallback["workflow_run"]["attempt_root_run_id"] == "run-1"
        assert fallback["workflow_run"]["run_id"] == RUN_ID
    assert len(world.queued) == 1


def test_a_finished_run_is_linked_even_when_a_later_run_is_active(adapter, world, chat, planning):
    module, _logs = adapter
    _call(module, planning)
    world.runs.patch(OWNER, RUN_ID, status="completed")
    world.definitions.patch(OWNER, DIGEST_ID, active_run_id="a-later-run", status="running")

    # The plan's own run is found first, so the later run does not hide it.
    linked, _service = _call(module, planning, run_id="run-2", root="run-1")
    assert linked["workflow_run"] == _sidecar(planning, "already_started", orchestration_run_id="run-2")
    assert len(world.queued) == 1

    # A new plan is a new request: while the later run is active, it is refused as already running.
    busy, _service = _call(module, planning, run_id="run-9", root="run-9")
    _unavailable(busy, planning, "workflow_already_running", orchestration_run_id="run-9", root="run-9")
    assert len(world.queued) == 2 and world.runs.get(OWNER, RUN_ID_9) is None

    # Once the workflow is idle again, the new plan starts its own run.
    world.definitions.patch(OWNER, DIGEST_ID, active_run_id="", status="completed")
    started, _service = _call(module, planning, run_id="run-9", root="run-9")
    assert started["workflow_run"] == _sidecar(planning, "queued", run_id=RUN_ID_9,
                                               orchestration_run_id="run-9", root="run-9")
    assert len(world.queued) == 3
    assert sorted(item_id for _partition, item_id in world.runs.items) == sorted([RUN_ID, RUN_ID_9])


def test_a_run_record_the_workflow_never_took_is_finished_by_queueing_the_same_request(adapter, world, chat, planning):
    module, _logs = adapter
    # Storage failed while the run was being bound: the run record and its control are left behind.
    world.definitions.before_replace = lambda: (_ for _ in ()).throw(
        CosmosHttpResponseError(status_code=503, message=SECRET))
    first, _service = _call(module, planning)
    _failed(first, "workflow_runtime_unavailable")
    assert world.runs.get(OWNER, RUN_ID) is not None
    assert world.definitions.get(OWNER, DIGEST_ID)["active_run_id"] == ""

    retry, _service = _call(module, planning, run_id="run-2", root="run-1")
    assert retry["workflow_run"] == _sidecar(planning, "queued", orchestration_run_id="run-2")
    assert len(world.queued) == 2 and list(world.runs.items) == [(OWNER, RUN_ID)]
    assert world.definitions.get(OWNER, DIGEST_ID)["active_run_id"] == RUN_ID
    assert SECRET not in json.dumps(first, default=str)


def _another_run(world):
    world.definitions.patch(OWNER, DIGEST_ID, active_run_id="another-run", status="running")


def _edited(world):
    world.definitions.patch(OWNER, DIGEST_ID, description="Summarizes my month.")


def _deleted(world):
    del world.definitions.items[(OWNER, DIGEST_ID)]


def _deleting(world):
    world.definitions.patch(OWNER, DIGEST_ID, deleting=True)


@pytest.mark.parametrize("change, reason", [
    (_another_run, "workflow_already_running"),
    (_edited, "workflow_definition_changed"),
    (_deleted, "workflow_unavailable"),
    (_deleting, "workflow_unavailable"),
])
def test_a_workflow_that_changes_while_its_run_is_bound_is_refused_and_leaves_no_run(
    adapter, world, chat, planning, change, reason,
):
    module, logs = adapter
    world.after_load = lambda: change(world)
    result, _service = _call(module, planning)
    _unavailable(result, planning, reason)
    # The queue took the request back: its control is a tombstone and nothing else remains.
    control = next(iter(world.controls.items.values()))
    assert (control["run_id"], control["deleted"], control["state"]) == (RUN_ID, True, "cancelled")
    assert world.runs.items == {} and world.deleted_results == [RUN_ID]
    _assert_logs_carry_codes_only(logs, planning)


def test_a_request_the_queue_took_back_is_never_started_and_a_new_plan_is(adapter, world, chat, planning):
    module, _logs = adapter
    world.after_load = lambda: _edited(world)
    refused, _service = _call(module, planning)
    _unavailable(refused, planning, "workflow_definition_changed")

    # The same plan asking again gets the tombstone for good, with its own closed reason.
    again, _service = _call(module, planning, run_id="run-2", root="run-1")
    _unavailable(again, planning, "workflow_run_tombstoned", orchestration_run_id="run-2")
    assert module.WORKFLOW_RUN_REASON_TEXT["workflow_run_tombstoned"]
    assert world.runs.items == {}

    # A new plan has a new first attempt, so it can start the workflow.
    fresh, _service = _call(module, planning, run_id="run-9", root="run-9")
    assert fresh["workflow_run"] == _sidecar(planning, "queued", run_id=RUN_ID_9,
                                             orchestration_run_id="run-9", root="run-9")
    assert len(world.queued) == 3 and list(world.runs.items) == [(OWNER, RUN_ID_9)]


def test_a_crash_after_the_queue_is_healed_by_a_retry_without_a_second_run(adapter, world, chat, planning):
    module, logs = adapter
    service = _Service()
    service.fail_persist = RuntimeError(SECRET)
    crashed, service = _call(module, planning, service=service)
    # The run started, but the step could not record it.
    _failed(crashed, "step_failed")
    assert service.persisted == [] and len(world.queued) == 1
    assert world.runs.get(OWNER, RUN_ID) is not None

    retry, service = _call(module, planning, run_id="run-2", root="run-1")
    assert retry["workflow_run"] == _sidecar(planning, "already_started", orchestration_run_id="run-2")
    assert service.persisted[0]["outputs"] == _retained(module, "already_started")
    assert len(world.queued) == 1 and list(world.runs.items) == [(OWNER, RUN_ID)]
    assert SECRET not in json.dumps([crashed, logs], default=str)


# ---------------------------------------------------------------------------
# Closed reasons and failures
# ---------------------------------------------------------------------------

def _conflict(code):
    return lambda store: store.WorkflowRuntimeConflict(code, SECRET)


@pytest.mark.parametrize("error, reason", [
    (_conflict("workflow_already_running"), "workflow_already_running"),
    (_conflict("workflow_definition_changed"), "workflow_definition_changed"),
    (_conflict("workflow_deleting"), "workflow_unavailable"),
    (_conflict("workflow_deleted"), "workflow_unavailable"),
    (_conflict("tombstoned"), "workflow_run_tombstoned"),
    (_conflict("initialize_conflict"), "workflow_run_not_started"),
    (_conflict(None), "workflow_run_not_started"),
    (_conflict(["tombstoned"]), "workflow_run_not_started"),
    (lambda store: PermissionError(SECRET), "workflow_access_lost"),
    (lambda store: ValueError(SECRET), "workflow_unavailable"),
    (lambda store: LookupError(SECRET), "workflow_unavailable"),
    (lambda store: KeyError(SECRET), "workflow_unavailable"),
])
def test_each_refusal_from_the_queue_is_a_closed_reason(adapter, world, chat, planning, error, reason):
    module, logs = adapter
    store = importlib.import_module("functions_workflow_runtime_store")
    world.fail_queue = error(store)
    result, service = _call(module, planning)
    _unavailable(result, planning, reason)
    assert module.WORKFLOW_RUN_REASON_TEXT[reason]
    assert service.persisted[0]["outputs"] == _retained(module, "unavailable", reason=reason)
    assert len(world.queued) == 1
    _no_run_started(world)
    assert SECRET not in json.dumps([result, service.persisted, logs], default=str)
    _assert_logs_carry_codes_only(logs, planning)


@pytest.mark.parametrize("error, code", [
    (lambda store: store.RuntimeUnavailable(), "workflow_runtime_unavailable"),
    (lambda store: AzureError(SECRET), "workflow_runtime_unavailable"),
    (lambda store: CosmosHttpResponseError(status_code=503, message=SECRET), "workflow_runtime_unavailable"),
    (lambda store: RuntimeError(SECRET), "step_failed"),
])
def test_an_unavailable_runtime_fails_the_step_so_it_can_be_retried(adapter, world, chat, planning, error, code):
    module, logs = adapter
    schema = importlib.import_module("functions_orchestration_schema")
    store = importlib.import_module("functions_workflow_runtime_store")
    world.fail_queue = error(store)
    result, service = _call(module, planning)
    _failed(result, code)
    assert result["failure"]["message"] == schema.FAILURE_MESSAGES[code] == result["error"]
    assert service.persisted == [] and len(world.queued) == 1
    assert SECRET not in json.dumps([result, logs], default=str)


def test_the_new_failures_are_retried_only_by_the_user(modules):
    schema = importlib.import_module("functions_orchestration_schema")
    registry = importlib.import_module("functions_orchestration_registry")
    for code in ("workflow_runtime_unavailable", "external_session_required"):
        failure = schema.build_failure(code)
        assert failure["code"] == code and failure["message"] == schema.FAILURE_MESSAGES[code]
        assert schema.failure_is_transient(failure) is False
        assert schema.failure_repeats_on_retry(failure) is False
    assert "start a saved workflow" in schema.FAILURE_MESSAGES["external_session_required"]
    assert not registry.get_capability(WORKFLOW_RUN).get("retry_on_transient")


M365_STATES = (
    "awaiting_approval", "awaiting_sharing_approval", "awaiting_analysis_approval", "awaiting_run_as_approval",
    "awaiting_sign_in", "ready_to_resume", "resuming",
)


def test_the_microsoft_365_states_are_the_ones_the_run_button_refuses(wr):
    routes = importlib.import_module("route_backend_workflows")
    assert set(wr.M365_ACTIVE_STATES) == set(M365_STATES)
    assert wr.M365_ACTIVE_STATES is routes.M365_ACTIVE_STATES


@pytest.mark.parametrize("status", M365_STATES)
def test_a_workflow_waiting_for_microsoft_365_is_not_started(adapter, world, chat, planning, status):
    module, _logs = adapter
    world.definitions.patch(OWNER, DIGEST_ID, status=status)
    result, _service = _call(module, planning)
    _unavailable(result, planning, "workflow_waiting_for_microsoft_365")
    assert world.queued == []


@pytest.mark.parametrize("change", ["not_durable", "microsoft_365", "role", "signed_out"])
def test_a_started_run_is_linked_even_when_starting_it_now_would_be_refused(adapter, world, chat, planning, change):
    module, _logs = adapter
    _call(module, planning)
    settings, options = RUN_SETTINGS, {}
    if change == "not_durable":
        world.definitions.patch(OWNER, DIGEST_ID, durable_execution=False)
    elif change == "microsoft_365":
        world.definitions.patch(OWNER, DIGEST_ID, status="awaiting_sign_in")
    elif change == "role":
        settings = {**RUN_SETTINGS, "require_member_of_workflow_user": True}
    else:
        options = {"signed_in": False}
    linked, _service = _call(module, planning, settings=settings, run_id="run-2", root="run-1", **options)
    assert linked["workflow_run"] == _sidecar(planning, "already_started", orchestration_run_id="run-2")
    assert len(world.queued) == 1


def test_a_workflow_without_durable_execution_is_not_started(adapter, world, chat, planning):
    module, _logs = adapter
    watcher, _service = _call(module, planning, name="Contract watcher")
    _unavailable(watcher, planning, "workflow_not_durable", workflow_id=NOT_DURABLE_ID, name="Contract watcher")

    # Durable execution turned off after the plan was made.
    world.definitions.patch(OWNER, DIGEST_ID, durable_execution=False)
    digest, _service = _call(module, planning)
    _unavailable(digest, planning, "workflow_not_durable")
    assert world.queued == []


@pytest.mark.parametrize("change", [{"tasks": ["not a task"]}, {"definition_version": 4}, {"definition_version": "1"}])
def test_a_definition_the_runtime_cannot_run_is_unavailable(adapter, world, chat, planning, change):
    module, _logs = adapter
    world.definitions.patch(OWNER, DIGEST_ID, **change)
    result, _service = _call(module, planning)
    _unavailable(result, planning, "workflow_unavailable")
    assert len(world.queued) == 1
    _no_run_started(world)


@pytest.mark.parametrize("change", ["missing", "foreign", "deleting", "other_id"])
def test_a_workflow_that_is_gone_or_not_the_requesters_is_unavailable(adapter, world, chat, planning, change):
    module, _logs = adapter
    record = world.definitions.items[(OWNER, DIGEST_ID)]
    if change == "missing":
        del world.definitions.items[(OWNER, DIGEST_ID)]
    elif change == "foreign":
        world.definitions.items[(OWNER, DIGEST_ID)] = {**record, "user_id": "someone-else"}
    elif change == "other_id":
        world.definitions.items[(OWNER, DIGEST_ID)] = {**record, "id": NOT_DURABLE_ID}
    else:
        world.definitions.patch(OWNER, DIGEST_ID, deleting=True)
    result, _service = _call(module, planning)
    _unavailable(result, planning, "workflow_unavailable", workflow_id=None)
    assert world.queued == [] and world.runs.reads == []


def test_a_run_record_that_is_not_this_workflows_is_never_linked(adapter, world, chat, planning):
    module, _logs = adapter
    world.runs.upsert_item({"id": RUN_ID, "user_id": OWNER, "workflow_id": NOT_DURABLE_ID, "status": "completed"})
    result, _service = _call(module, planning)
    _unavailable(result, planning, "workflow_unavailable")
    assert world.queued == []


def test_losing_workflow_access_after_planning_is_a_closed_reason(adapter, world, chat, planning):
    module, _logs = adapter
    # The deployment turned personal workflows off after the step's settings were read.
    world.settings["allow_user_workflows"] = False
    result, _service = _call(module, planning)
    _unavailable(result, planning, "workflow_access_lost")
    assert len(world.queued) == 1
    _no_run_started(world)


# ---------------------------------------------------------------------------
# Stops, sessions and storage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", ["another_user", "legacy_plan"])
def test_the_step_refuses_another_user_and_a_legacy_plan_before_anything_runs(adapter, world, chat, planning, case):
    module, _logs = adapter
    results = importlib.import_module("functions_orchestration_results")
    service = _Service()
    options = {"user_id": "someone-else"} if case == "another_user" else {"contract_version": 1}
    with pytest.raises(results.ResultUnavailableError) as caught:
        _call(module, planning, service=service, **options)
    assert caught.value.code == "result_owner_mismatch"
    assert service.authorized == [] and chat.reads == [] and world.queued == []


def test_a_stop_before_the_queue_prevents_the_run(adapter, world, chat, planning):
    module, _logs = adapter
    mixed = importlib.import_module("functions_mixed_source_orchestration")
    service = _Service()
    with pytest.raises(mixed.MixedSourceCancellationError):
        _call(module, planning, service=service, cancel=lambda: True)
    assert service.authorized == [] and chat.reads == []

    # Stopped while the step was checking the workflow: the queue is never called.
    answers, service = iter((False, True)), _Service()
    with pytest.raises(mixed.MixedSourceCancellationError):
        _call(module, planning, service=service, cancel=lambda: next(answers))
    assert service.authorized == [(OWNER, True)] and service.persisted == []
    assert world.queued == []
    _no_run_started(world)


def test_a_stop_after_the_queue_still_records_the_run_it_started(adapter, world, chat, planning):
    module, _logs = adapter
    mixed = importlib.import_module("functions_mixed_source_orchestration")
    asked = []

    def cancel():
        asked.append(True)
        return len(asked) > 2

    result, service = _call(module, planning, cancel=cancel)
    assert result["workflow_run"] == _sidecar(planning, "queued")
    assert len(asked) == 2 and len(service.persisted) == 1

    # A link starts nothing, so a stop before it is recorded ends the step.
    answers, service = iter((False, True)), _Service()
    with pytest.raises(mixed.MixedSourceCancellationError):
        _call(module, planning, service=service, cancel=lambda: next(answers))
    assert service.persisted == [] and len(world.queued) == 1


def test_a_newer_attempt_of_the_step_stops_this_one_before_the_queue(adapter, world, chat, planning):
    module, _logs = adapter
    result, service = _call(module, planning, guards=("guard-1", "guard-1", "guard-2"))
    _failed(result, "result_unavailable")
    assert world.queued == [] and service.persisted == []
    _no_run_started(world)


@pytest.mark.parametrize("signed_in", [False, None, 1, "true"])
def test_starting_a_run_needs_a_signed_in_session(adapter, world, chat, planning, signed_in):
    module, _logs = adapter
    result, service = _call(module, planning, signed_in=signed_in)
    _failed(result, "external_session_required")
    assert world.queued == [] and service.persisted == []


@pytest.mark.parametrize("container", ["conversation", "workflow", "run"])
def test_unavailable_storage_fails_the_step_so_it_can_be_retried(adapter, world, chat, planning, container):
    module, logs = adapter
    target = {"conversation": chat, "workflow": world.definitions, "run": world.runs}[container]
    target.read_error = AzureError(SECRET)
    result, service = _call(module, planning)
    _failed(result, "workflow_runtime_unavailable")
    assert world.queued == [] and service.persisted == []
    assert SECRET not in json.dumps([result, logs], default=str)


# ---------------------------------------------------------------------------
# Gates the step checks again
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("change", SHARED_CHANGES)
def test_a_conversation_shared_after_planning_never_starts_a_workflow(adapter, world, chat, planning, change):
    module, _logs = adapter
    chat.patch(CONVERSATION, CONVERSATION, **change)
    result, _service = _call(module, planning)
    _unavailable(result, planning, "workflow_shared_conversation", workflow_id=None)
    assert world.definitions.reads == [] and world.queued == []


def test_a_conversation_recorded_as_shared_stays_shared(adapter, world, chat, planning):
    module, _logs = adapter
    result, _service = _call(module, {**planning, "conversation_private": False})
    assert (result["workflow_run"]["status"], result["workflow_run"]["reason"]) == (
        "unavailable", "workflow_shared_conversation")
    assert world.definitions.reads == [] and world.queued == []


@pytest.mark.parametrize("change", ["missing", "foreign", "deleted"])
def test_a_conversation_the_requester_no_longer_owns_starts_nothing(adapter, world, chat, planning, change):
    module, _logs = adapter
    if change == "missing":
        del chat.items[(CONVERSATION, CONVERSATION)]
    elif change == "foreign":
        chat.patch(CONVERSATION, CONVERSATION, user_id="someone-else")
    else:
        chat.patch(CONVERSATION, CONVERSATION, orchestration_deleted=True)
    result, _service = _call(module, planning)
    _unavailable(result, planning, "workflow_context_unavailable", workflow_id=None)
    assert world.definitions.reads == [] and world.queued == []


@pytest.mark.parametrize("change", [
    {RUNS: False}, {RUNS: "true"}, {RUNS: 1}, {RUNS: None}, {"enable_chat_orchestration": False},
    {"allow_user_workflows": False}, {"chat_orchestration_enabled_capabilities": ["compose"]},
])
def test_with_workflow_runs_off_the_step_reads_and_starts_nothing(adapter, world, chat, planning, change):
    module, _logs = adapter
    result, _service = _call(module, planning, settings={**RUN_SETTINGS, **change})
    _unavailable(result, planning, "workflow_runs_disabled", workflow_id=None)
    assert chat.reads == [] and world.definitions.reads == [] and world.runs.reads == [] and world.queued == []


def test_an_allowlist_naming_workflow_runs_admits_the_step(adapter, world, chat, planning):
    module, _logs = adapter
    settings = {**RUN_SETTINGS, "chat_orchestration_enabled_capabilities": ["compose", WORKFLOW_RUN]}
    result, _service = _call(module, planning, settings=settings)
    assert result["workflow_run"] == _sidecar(planning, "queued")


def test_the_workflow_user_role_is_required_when_the_deployment_asks_for_it(adapter, world, chat, planning):
    module, _logs = adapter
    settings = {**RUN_SETTINGS, "require_member_of_workflow_user": True}
    refused, _service = _call(module, planning, settings=settings, roles=("User",))
    _unavailable(refused, planning, "workflow_role_required")
    assert world.queued == []
    started, _service = _call(module, planning, settings=settings, roles=("User", "WorkflowUser"))
    assert started["workflow_run"] == _sidecar(planning, "queued")


def test_a_step_without_a_ready_planning_context_starts_nothing(adapter, world, chat, planning, wf):
    module, _logs = adapter
    proposals_only = _build(wf, [], PROPOSALS_ONLY, request_text=DIGEST_REQUEST)
    handle = _handle(planning, "Weekly digest")
    cases = [
        (None, _run(handle)),
        (proposals_only, _run(handle)),
        ({**planning, "workflow_runs": {**planning["workflow_runs"], "ready": False}}, _run(handle)),
        (planning, _run("wf-unknown-000000")),
        (planning, _run(_handle(planning, "Weekly digest").upper())),
    ]
    for context_planning, step in cases:
        result, _service = _call(module, context_planning, step=step)
        run = result["workflow_run"]
        assert (result["status"], run["status"], run["reason"]) == (
            "completed", "unavailable", "workflow_context_unavailable")
        assert run["workflow_id"] is None and run["run_id"] is None
    assert world.definitions.reads == [] and world.queued == []


def test_the_step_runs_on_a_plain_thread_without_flask(adapter, world, chat, planning):
    module, _logs = adapter
    outcome = {}

    def work():
        outcome["contexts"] = (has_app_context(), has_request_context())
        outcome["result"] = _call(module, planning)[0]

    thread = threading.Thread(target=work, name="orchestration-step-test")
    thread.start()
    thread.join(60)
    assert not thread.is_alive()
    assert outcome["contexts"] == (False, False)
    assert outcome["result"]["workflow_run"] == _sidecar(planning, "queued")
    assert world.contexts == [(False, False, "orchestration-step-test")]


def test_mcp_keeps_its_own_invocation_record(world):
    runtime = importlib.import_module("functions_workflow_runtime")
    metadata = {"version": 1, "source": "inbound_mcp", "client_id": "client-1"}
    queued = runtime.queue_durable_workflow_run(
        {"id": DIGEST_ID, "user_id": OWNER}, actor_user_id=OWNER, trigger_source="inbound_mcp",
        invocation_metadata=metadata,
    )
    run = world.runs.get(OWNER, queued["run"]["id"])
    assert run["mcp_invocation"] == metadata and run["trigger_source"] == "inbound_mcp"
    assert "chat_invocation" not in run

    # The MCP tool passes its own metadata and nothing meant for chat.
    tree = ast.parse((APP_ROOT / "functions_mcp_server_tools.py").read_text(encoding="utf-8"))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "queue_durable_workflow_run"
    ]
    assert len(calls) == 1
    keywords = {keyword.arg for keyword in calls[0].keywords}
    assert {"invocation_metadata", "trigger_source"} <= keywords and "chat_invocation" not in keywords


def test_a_workflow_name_is_kept_as_one_plain_bounded_line_and_never_logged(adapter, world, chat, planning):
    module, logs = adapter
    limit = importlib.import_module("functions_orchestration_workflow_context").NAME_MAX_LENGTH
    world.definitions.patch(OWNER, DIGEST_ID, name=f"  {HOSTILE_NAME}\n\t{'x' * 300}")
    result, service = _call(module, planning)
    name = result["workflow_run"]["name"]
    # Markup stays as the text it is; the browser renders it as text.
    assert name.startswith(f"{HOSTILE_NAME} x") and "\n" not in name and "\t" not in name
    assert len(name) == limit and name.endswith("\u2026")
    assert service.persisted[0]["outputs"] == _retained(module, "queued", name=name)
    assert HOSTILE_NAME not in json.dumps(logs, default=str)


# ---------------------------------------------------------------------------
# Describing again a step recovered or reused without its sidecar
# ---------------------------------------------------------------------------

class _Opened:
    def __init__(self, value):
        self.value = value

    def read_value(self):
        if isinstance(self.value, Exception):
            raise self.value
        return deepcopy(self.value)


class _Results:
    def __init__(self, value):
        self.value = value
        self.opened = []

    def open_result(self, reference, allow_partial=True):
        self.opened.append((reference, allow_partial))
        return _Opened(self.value)


def _rebuild(module, planning, monkeypatch, value, *, known=True):
    """Describe again the step as plan attempt "run-2", a retry of first attempt "run-1"."""
    results = _Results(value)
    monkeypatch.setattr(module, "require_result_service", lambda context: results)
    context = SimpleNamespace(
        workflow_planning=planning if known else None, run_id="run-2", attempt_root_run_id="run-1",
        conversation_id=CONVERSATION,
    )
    task = SimpleNamespace(producer=SimpleNamespace(run_id="run-2"), output=lambda name: f"reference:{name}")
    rebuilt = module.rebuild_workflow_run(_run(_handle(planning, "Weekly digest")), context, user_id=OWNER, task=task)
    return rebuilt, results


def _retained_value(status, *, reason=None, name="Weekly digest"):
    return {"version": 1, "name": name, "status": status, "reason": reason}


@pytest.mark.parametrize("status", sorted(STARTED))
def test_a_recovered_step_links_the_run_its_first_attempt_started(adapter, planning, monkeypatch, status):
    module, _logs = adapter
    rebuilt, results = _rebuild(module, planning, monkeypatch, _retained_value(status))
    assert results.opened == [("reference:run", False)]
    assert rebuilt == _sidecar(planning, status, orchestration_run_id="run-2")


def test_a_recovered_step_that_started_nothing_keeps_its_reason_and_links_no_run(adapter, planning, monkeypatch):
    module, _logs = adapter
    rebuilt, _results = _rebuild(module, planning, monkeypatch, _retained_value("unavailable", reason="workflow_not_durable"))
    assert rebuilt == _sidecar(planning, "unavailable", reason="workflow_not_durable", orchestration_run_id="run-2")
    assert rebuilt["run_id"] is None


def test_a_recovered_reason_the_application_does_not_own_is_dropped(adapter, planning, monkeypatch):
    module, logs = adapter
    rebuilt, _results = _rebuild(module, planning, monkeypatch, _retained_value("unavailable", reason=SECRET))
    assert rebuilt == _sidecar(planning, "unavailable", orchestration_run_id="run-2")
    assert SECRET not in json.dumps([rebuilt, logs], default=str)


@pytest.mark.parametrize("name", [None, "", "   ", 7])
def test_a_recovered_step_without_a_name_is_called_workflow(adapter, planning, monkeypatch, name):
    module, _logs = adapter
    rebuilt, _results = _rebuild(module, planning, monkeypatch, _retained_value("queued", name=name))
    assert rebuilt == {**_sidecar(planning, "queued", orchestration_run_id="run-2"), "name": "Workflow"}


def test_a_recovered_step_whose_planning_context_is_gone_keeps_its_status_without_a_link(adapter, planning, monkeypatch):
    module, _logs = adapter
    rebuilt, _results = _rebuild(module, planning, monkeypatch, _retained_value("queued"), known=False)
    assert rebuilt == {**_sidecar(planning, "queued", orchestration_run_id="run-2"), "workflow_id": None, "run_id": None}


@pytest.mark.parametrize("value", [
    RuntimeError(SECRET), _retained_value(SECRET), ["not", "a", "run"], None,
], ids=["unreadable", "unknown_status", "not_a_record", "empty"])
def test_a_recovered_step_that_cannot_be_read_is_not_described(adapter, planning, monkeypatch, value):
    module, logs = adapter
    rebuilt, _results = _rebuild(module, planning, monkeypatch, value)
    assert rebuilt is None
    assert SECRET not in json.dumps(logs, default=str)


def test_a_step_that_cannot_be_described_at_all_is_skipped(adapter):
    module, logs = adapter
    rebuilt = module.rebuild_workflow_run(
        {"step_id": "run_digest"}, SimpleNamespace(run_id="run-1"), user_id=OWNER, task=None,
    )
    assert rebuilt is None
    assert logs and logs[-1][1]["extra"]["error_type"] == "AttributeError"
    assert logs[-1][1]["extra"]["run_id_hash"] == hashlib.sha256(b"run-1").hexdigest()
    assert logs[-1][1]["extra"]["step_id_hash"] == hashlib.sha256(b"run_digest").hexdigest()


def test_the_executor_restores_only_a_completed_run_step_without_its_sidecar(wr, monkeypatch):
    executor = importlib.import_module("functions_orchestration_executor")
    schema = importlib.import_module("functions_orchestration_schema")
    rebuilt, logs = [], []
    outcome = {"value": {"run_id": "restored"}}

    def rebuild(step, context, *, user_id, task):
        rebuilt.append((user_id, task))
        if isinstance(outcome["value"], Exception):
            raise outcome["value"]
        return outcome["value"]

    monkeypatch.setattr(wr, "rebuild_workflow_run", rebuild)
    monkeypatch.setattr(executor, "log_event", lambda message, **kwargs: logs.append((message, kwargs)))
    step = {"step_id": "run_digest", "capability_id": WORKFLOW_RUN}
    task = object()
    completed, failed = schema.STEP_STATUS_COMPLETED, schema.STEP_STATUS_FAILED
    for candidate, status, result in (
        ({**step, "capability_id": "workflow_propose"}, completed, {"task_result": task}),
        (step, failed, {"task_result": task}),
        (step, completed, {"task_result": None}),
        (step, completed, {"task_result": task, "workflow_run": {"run_id": "kept"}}),
        (step, completed, None),
    ):
        restored = executor._restore_workflow_run(candidate, SimpleNamespace(), status, result, user_id=OWNER)
        assert restored is result
    assert rebuilt == []

    result = {"task_result": task}
    restored = executor._restore_workflow_run(step, SimpleNamespace(), completed, result, user_id=OWNER)
    assert restored == {"task_result": task, "workflow_run": {"run_id": "restored"}}
    assert result == {"task_result": task} and rebuilt == [(OWNER, task)]

    for value in (None, ["not", "a", "sidecar"], RuntimeError(SECRET)):
        outcome["value"] = value
        restored = executor._restore_workflow_run(step, SimpleNamespace(), completed, result, user_id=OWNER)
        assert restored is result
    assert SECRET not in json.dumps(logs, default=str)


# ---------------------------------------------------------------------------
# Hygiene
# ---------------------------------------------------------------------------

def _imports(nodes):
    imported = {}
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.setdefault(alias.name, set())
        elif isinstance(node, ast.ImportFrom):
            imported.setdefault(node.module, set()).update(alias.name for alias in node.names)
    return imported


def _calls_by_function(tree):
    calls = {}
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
                if name:
                    calls.setdefault(name, set()).add(function.name)
    return calls


def test_the_run_module_writes_only_through_the_queue_and_never_imports_flask():
    tree = ast.parse((APP_ROOT / "functions_orchestration_workflow_runs.py").read_text(encoding="utf-8"))
    everything = _imports(ast.walk(tree))
    top_level = _imports(tree.body)
    lazy = _imports(
        node for function in ast.walk(tree) if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(function)
    )
    assert not any(name.split(".")[0] == "flask" for name in everything)
    # The workflow runtime, its store and the containers load only when a step runs, which keeps
    # the queue, runner and plugin loader out of the orchestration import graph.
    assert not {"config", "functions_workflow_runtime", "functions_workflow_runtime_store"} & set(top_level)
    assert lazy == {
        "config": {
            "cosmos_conversations_container", "cosmos_personal_workflows_container",
            "cosmos_personal_workflow_runs_container",
        },
        "functions_workflow_runtime": {
            "RUNTIME_TERMINAL_STATES", "queue_durable_workflow_run", "workflow_run_id_for_request",
        },
        "functions_workflow_runtime_store": {"RuntimeUnavailable", "WorkflowRuntimeConflict"},
    }
    calls = _calls_by_function(tree)
    writes = {"create_item", "upsert_item", "replace_item", "delete_item", "patch_item", "execute_item_batch"}
    assert not writes & set(calls)
    assert calls["read_item"] == {"_point_read"}
    assert calls["queue_durable_workflow_run"] == {"_queue_workflow_run"}
    assert calls["_queue_workflow_run"] == {"_start"}
    assert calls["log_event"] == {"_log"}


def test_the_run_module_logs_constant_messages_only():
    tree = ast.parse((APP_ROOT / "functions_orchestration_workflow_runs.py").read_text(encoding="utf-8"))
    logged = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_log"]
    assert logged
    for call in logged:
        assert call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str), call.lineno
        # The fields are codes and ids the application made or checked, never text a user wrote.
        assert {keyword.arg for keyword in call.keywords} <= {
            "run_id", "step_id", "status", "reason", "failure_code", "error_type",
        }, call.lineno


@pytest.mark.parametrize("signed_in, kept_codes", [
    (True, {"sc_status": "queued", "sc_reason": None}),
    (False, {"sc_failure_code": "external_session_required"}),
])
def test_the_run_step_log_keeps_its_codes_and_only_hashed_ids(adapter, world, chat, planning, signed_in, kept_codes):
    module, logs = adapter
    appinsights = importlib.import_module("functions_appinsights")
    _call(module, planning, signed_in=signed_in)
    assert len(logs) == 1
    message, kwargs = logs[0]
    assert "run-1" not in json.dumps(kwargs, default=str) and "run_digest" not in json.dumps(kwargs, default=str)
    # What Application Insights receives: the logger keeps allowlisted codes and hashes, and only
    # the length of any other text.
    kept = appinsights._build_logger_extra(message, appinsights.sanitize_log_properties(kwargs["extra"]))
    assert kept["sc_stage"] == "workflow_run"
    assert {key: kept.get(key, "dropped") for key in kept_codes} == kept_codes
    assert kept["sc_run_id_hash"] == hashlib.sha256(b"run-1").hexdigest()
    assert kept["sc_step_id_hash"] == hashlib.sha256(b"run_digest").hexdigest()
    assert [key for key in kept if key.endswith("_length") and key[:-len("_length")] not in kept] == []


def test_every_run_context_knows_its_first_attempt_and_whether_a_user_is_signed_in():
    sites = []
    for path in sorted(APP_ROOT.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "RunContext(" not in source:
            continue
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "RunContext":
                sites.append((path.name, node.lineno, {
                    keyword.arg: ast.unparse(keyword.value) for keyword in node.keywords if keyword.arg
                }))
    assert {name for name, _line, _keywords in sites} >= {
        "functions_orchestration_execution.py", "route_backend_orchestration.py",
    }
    for name, line, keywords in sites:
        assert {"attempt_root_run_id", "signed_in_session"} <= set(keywords), (name, line)
        # Each reads the plan's first attempt from its run record, never the attempt's own id
        # alone, and the session from the principal's request bridge, never a constant.
        assert "attempt_root_run_id" in keywords["attempt_root_run_id"], (name, line)
        assert "bridge" in keywords["signed_in_session"], (name, line)


@pytest.mark.parametrize("root, expected", [(None, "r"), ("", "r"), (5, "r"), ("run-1", "run-1")])
def test_a_run_context_without_a_first_attempt_is_its_own_first_attempt(modules, root, expected):
    executor = importlib.import_module("functions_orchestration_executor")
    context = executor.RunContext(run_id="r", attempt_root_run_id=root)
    assert context.attempt_root_run_id == expected
    assert executor.RunContext(run_id="r").attempt_root_run_id == "r"


@pytest.mark.parametrize("value, expected", [(None, False), (False, False), (1, False), ("true", False), (True, True)])
def test_only_a_real_signed_in_session_counts(modules, value, expected):
    executor = importlib.import_module("functions_orchestration_executor")
    assert executor.RunContext(run_id="r", signed_in_session=value).signed_in_session is expected
    assert executor.RunContext(run_id="r").signed_in_session is False


# ---------------------------------------------------------------------------
# Running the step in a plan
# ---------------------------------------------------------------------------

def _harness(monkeypatch, planning, steps, replies):
    env = HarnessEnvironment(monkeypatch)
    env.settings.update(RUN_SETTINGS)
    real_normalize = env.schema.normalize_plan

    def normalize(raw, *args, **kwargs):
        # The harness offers only its own capabilities and plans without a workflow context.
        capability_ids = kwargs.get("available_capability_ids")
        if capability_ids is not None and WORKFLOW_RUN not in capability_ids:
            kwargs["available_capability_ids"] = [*capability_ids, WORKFLOW_RUN]
        kwargs.setdefault("workflow_planning", planning)
        return real_normalize(raw, *args, **kwargs)

    monkeypatch.setattr(env.schema, "normalize_plan", normalize)
    env.create(steps, replies=replies, final_response=input_binding("answer"), workflow_planning=planning)
    return env


def _signed_in(execution):
    # The harness prepares a run outside a request, so it has no signed-in session of its own.
    execution.context.signed_in_session = True
    return execution


def _plan_step(plan, step_id):
    return next(step for step in plan["steps"] if step["step_id"] == step_id)


def _retry(env, execution, *, confirm=False):
    """Retry run-1 as the user would and prepare the child attempt. Returns ``(child, prepared)``."""
    parent = env.read()

    def authorize():
        return env.bootstrap.read_owned_conversation(OWNER, CONVERSATION)

    probe = copy(execution.context)
    probe.result_service = env.services().results
    request = {"conversation_id": CONVERSATION, "submission_id": "explicit-user-retry",
               "expected_version": parent["recovery_version"]}
    if confirm:
        request["confirm_external_effects"] = True
    child = env.recovery.prepare_retry(
        "run-1", OWNER, request, authorize=authorize, message_container=env.messages,
        validate=lambda current: env.recovery.validate_resume(
            current, probe, env.settings, authorize, source_run_id=current["id"],
        ),
    )
    services = env.services()
    claimed = env.revisions.claim_plan_run(
        child["id"], OWNER, CONVERSATION, expected_version=child["edit_version"],
        result_alias_resolver=lambda current: env.service_bindings.admitted_result_aliases(current, services.results),
    )
    lease = env.recovery.ExecutionLease(claimed, authorize, message_container=env.messages)
    return child, _signed_in(env.execution.prepare_harness_execution(claimed, settings=env.settings, lease=lease))


def _run_to_end(env, execution):
    try:
        return env.run_engine(execution)
    finally:
        execution.close()


def test_the_plan_starts_the_workflow_once_and_keeps_its_ids_on_the_server(world, wr, planning, monkeypatch):
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    events = importlib.import_module("functions_orchestration_events")
    runs = importlib.import_module("functions_orchestration_runs")
    services = importlib.import_module("functions_orchestration_services")
    logs = []
    monkeypatch.setattr(wr, "log_event", lambda message, **kwargs: logs.append((message, kwargs)))
    env = _harness(monkeypatch, planning, [compose_step("answer"), _run(_handle(planning, "Weekly digest"))],
                   ["Your priorities."])
    _assert_waits_for_the_user(env.read()["plan"])
    execution = _signed_in(env.prepare())
    progress = []
    frames = decoded_frames(execution.execute(emit=progress.append))
    streamed = decoded_frames(progress)

    step = env.steps.read_item("run-1:run_digest", "run-1")
    assert step["status"] == "completed" and step["workflow_run"] == _sidecar(planning, "queued")
    assert len(world.queued) == 1 and list(world.runs.items) == [(OWNER, RUN_ID)]
    started = world.runs.get(OWNER, RUN_ID)
    invocation = started["chat_invocation"]
    assert started["trigger_source"] == "chat_orchestration" and "mcp_invocation" not in started
    assert invocation == {
        "version": 1, "source": "chat_orchestration", "conversation_id": CONVERSATION,
        "user_message_id": "user-turn-1", "orchestration_run_id": "run-1", "attempt_root_run_id": "run-1",
        "step_id": "run_digest", "requested_by": OWNER, "requested_at": invocation["requested_at"],
    }
    assert datetime.fromisoformat(invocation["requested_at"]).tzinfo is not None
    assert world.definitions.get(OWNER, DIGEST_ID)["active_run_id"] == RUN_ID

    # The workflow and run ids never leave the server: not streamed, listed or stored on the message.
    # The run step's own progress frames are streamed, so the stream checked here is real.
    assert any(frame.get("type") == events.EVENT_TYPE_STEP and frame.get("step_id") == "run_digest" for frame in streamed)
    public = runs.list_run_steps("run-1", user_id=OWNER, conversation_id=CONVERSATION)
    for surface in (frames, streamed, public, env.assistant_messages()):
        text = json.dumps(surface, default=str)
        for secret in (RUN_ID, DIGEST_ID, REQUEST_ID, "chat_invocation", "requested_by"):
            assert secret not in text, secret
    _assert_logs_carry_codes_only(logs, planning)

    run = env.read()
    assert run["status"] == "completed" and set(run["task_results"]) == {"answer", "run_digest"}
    task = contracts.TaskResult.from_dict(step["task_result"])
    results = env.services().results
    assert results.open_result(task.output("run"), allow_partial=False).read_value() == _retained_value("queued")

    # A later plan is never offered the run as a saved result: only the answer is.
    found = services.discover_result_aliases([run], results)
    answer = contracts.TaskResult.from_dict(run["task_results"]["answer"])
    expected = sorted(json.dumps(ref.to_dict(), sort_keys=True) for ref in answer.outputs)
    offered = sorted(json.dumps(ref.to_dict(), sort_keys=True) for ref in found["aliases"].values())
    assert expected and offered == expected

    # A recovered step is described again with the same ids.
    probe = copy(execution.context)
    probe.result_service = results
    rebuilt = wr.rebuild_workflow_run(_plan_step(run["plan"], "run_digest"), probe, user_id=OWNER, task=task)
    assert rebuilt == step["workflow_run"]


def test_a_retry_that_reuses_the_step_keeps_its_link_and_starts_nothing(world, wr, planning, monkeypatch):
    env = _harness(monkeypatch, planning, [_run(_handle(planning, "Weekly digest")), compose_step("answer")],
                   [RuntimeError("FIXTURE_FAILURE")])
    execution = _signed_in(env.prepare())
    assert _run_to_end(env, execution)["status"] == "failed"
    first = env.steps.read_item("run-1:run_digest", "run-1")
    assert first["status"] == "completed" and first["checkpoint_available"] is True
    assert first["workflow_run"] == _sidecar(planning, "queued")

    child, second = _retry(env, execution, confirm=True)
    assert child["plan"]["approval"]["floor"] == FLOOR and child["attempt_root_run_id"] == "run-1"
    env.replies.append("Your priorities.")
    assert _run_to_end(env, second)["status"] == "completed"
    again = env.steps.read_item(f"{child['id']}:run_digest", child["id"])
    assert again["status"] == "completed" and again["reused_from_run_id"] == "run-1"
    assert again["workflow_run"] == first["workflow_run"]
    assert len(world.queued) == 1 and list(world.runs.items) == [(OWNER, RUN_ID)]


def test_a_retry_that_runs_the_step_again_links_the_run_the_first_attempt_started(world, wr, planning, monkeypatch):
    env = _harness(monkeypatch, planning, [_run(_handle(planning, "Weekly digest")), compose_step("answer")],
                   ["Your priorities."])

    def lost_reply():
        raise AzureError(SECRET)

    # The run is queued, but the step never hears back, so it fails without its sidecar.
    world.after_queue = lost_reply
    execution = _signed_in(env.prepare())
    assert _run_to_end(env, execution)["status"] == "failed"
    first = env.steps.read_item("run-1:run_digest", "run-1")
    assert first["status"] == "failed" and first["failure"]["code"] == "workflow_runtime_unavailable"
    assert "workflow_run" not in first and SECRET not in json.dumps(first)
    assert list(world.runs.items) == [(OWNER, RUN_ID)]

    child, second = _retry(env, execution, confirm=True)
    assert child["plan"]["approval"]["floor"] == FLOOR and child["attempt_root_run_id"] == "run-1"
    assert _run_to_end(env, second)["status"] == "completed"
    again = env.steps.read_item(f"{child['id']}:run_digest", child["id"])
    assert again["status"] == "completed" and not again["reused_from_run_id"]
    assert again["workflow_run"] == _sidecar(planning, "already_started", orchestration_run_id=child["id"])
    assert len(world.queued) == 1 and list(world.runs.items) == [(OWNER, RUN_ID)]


def test_a_step_whose_checkpoint_was_lost_after_the_queue_is_reused_with_its_link(world, wr, planning, monkeypatch):
    checkpoints = importlib.import_module("functions_orchestration_checkpoints")
    env = _harness(monkeypatch, planning, [_run(_handle(planning, "Weekly digest")), compose_step("answer")],
                   ["Your priorities."])
    real_commit = checkpoints.CheckpointStore.commit
    lost = []

    def commit(store, step, result, context, **kwargs):
        if step["step_id"] == "run_digest" and not lost:
            lost.append(step["step_id"])
            raise checkpoints.CheckpointError("checkpoint_unavailable")
        return real_commit(store, step, result, context, **kwargs)

    # The run is queued and the step's result retained, then the step's checkpoint is lost, so a
    # retry can recover the step only from the retained result, which never carries its ids.
    monkeypatch.setattr(checkpoints.CheckpointStore, "commit", commit)
    execution = _signed_in(env.prepare())
    with pytest.raises(checkpoints.CheckpointError):
        _run_to_end(env, execution)
    assert lost == ["run_digest"] and len(world.queued) == 1
    env.recovery._replace(env.read(), {"status": "failed", "execution_lease": None})

    child, second = _retry(env, execution, confirm=True)
    assert child["attempt_root_run_id"] == "run-1"
    assert _run_to_end(env, second)["status"] == "completed"
    again = env.steps.read_item(f"{child['id']}:run_digest", child["id"])
    assert again["status"] == "completed" and again["reused_from_run_id"] == "run-1"
    # The ids are computed again from the plan's first attempt and the step, so the link holds.
    assert again["workflow_run"] == _sidecar(planning, "queued")
    assert len(world.queued) == 1 and list(world.runs.items) == [(OWNER, RUN_ID)]


def test_a_plan_run_without_a_signed_in_session_never_starts_a_workflow(world, wr, planning, monkeypatch):
    env = _harness(monkeypatch, planning, [_run(_handle(planning, "Weekly digest")), compose_step("answer")],
                   ["Your priorities."])
    # Prepared outside a request, the run has no signed-in session to start a workflow for.
    execution = env.prepare()
    assert execution.context.signed_in_session is False
    assert _run_to_end(env, execution)["status"] == "failed"
    step = env.steps.read_item("run-1:run_digest", "run-1")
    assert step["status"] == "failed" and step["failure"]["code"] == "external_session_required"
    assert world.queued == []
    _no_run_started(world)


def test_a_plan_run_with_a_signed_in_session_starts_the_workflow(world, wr, planning, monkeypatch):
    identity = importlib.import_module("agent_execution_context")
    env = _harness(monkeypatch, planning, [_run(_handle(planning, "Weekly digest")), compose_step("answer")],
                   ["Your priorities."])
    principal = identity.ExecutionIdentity(OWNER, CONVERSATION, bridge=lambda agent: None)
    execution = env.prepare(execution_identity=principal)
    assert execution.context.signed_in_session is True
    assert _run_to_end(env, execution)["status"] == "completed"
    assert len(world.queued) == 1 and list(world.runs.items) == [(OWNER, RUN_ID)]


def test_real_http_an_approved_plan_starts_one_run_and_a_second_run_request_starts_none(
    real_http_harness, world, wf, wr, monkeypatch,
):
    runtime = real_http_harness
    harness = runtime.harness
    harness.settings.update(enable_user_workspace=False, allow_user_workflows=True, **{RUNS: True})
    for name, reader in _readers([]).items():
        monkeypatch.setitem(wf._DEFAULT_READERS, name, reader)
    digest = _handle(_build(wf, [], RUN_SETTINGS, request_text=DIGEST_REQUEST), "Weekly digest")
    harness.replies = [
        json.dumps({
            "relationship": "new_topic", "resolved_message": DIGEST_REQUEST,
            "message_ids": [], "requires_retrieval": False, "clarification": "",
        }),
        json.dumps({"kind": "plan", "steps": [compose_step(), _run(digest)], "final_response": input_binding("prepare")}),
        "The complete note.",
    ]
    planned = runtime.client.post("/api/v2/orchestration/plan", json={
        "conversation_id": CONVERSATION, "turn_id": "run-turn", "message": DIGEST_REQUEST,
        "approval_mode": "auto", "planner_contract_version": 1,
    }, buffered=True)
    frames = _frames(planned)
    assert planned.status_code == 200 and "plan" in frames[-1], frames
    plan = frames[-1]["plan"]
    _assert_waits_for_the_user(plan)
    assert world.queued == [] and world.runs.items == {}

    executed = runtime.client.post("/api/v2/orchestration/run", json={
        "conversation_id": CONVERSATION, "run_id": plan["run_id"],
    }, buffered=True)
    saved = harness.runs.read_item(plan["run_id"], CONVERSATION)
    assert executed.status_code == 200 and saved["status"] == "completed", _frames(executed)
    run_id = importlib.import_module("functions_workflow_runtime").workflow_run_id_for_request(
        {"id": DIGEST_ID, "user_id": OWNER}, wr.workflow_run_request_id(plan["run_id"], "run_digest"),
    )
    assert len(world.queued) == 1 and list(world.runs.items) == [(OWNER, run_id)]
    invocation = world.runs.get(OWNER, run_id)["chat_invocation"]
    assert (invocation["orchestration_run_id"], invocation["attempt_root_run_id"]) == (plan["run_id"], plan["run_id"])
    assert invocation["user_message_id"] == saved["user_message_id"] and invocation["requested_by"] == OWNER
    step = harness.steps.read_item(f"{plan['run_id']}:run_digest", plan["run_id"])
    assert step["workflow_run"]["run_id"] == run_id and step["workflow_run"]["status"] == "queued"
    for response in (planned, executed):
        text = response.get_data(as_text=True)
        assert run_id not in text and DIGEST_ID not in text

    again = runtime.client.post("/api/v2/orchestration/run", json={
        "conversation_id": CONVERSATION, "run_id": plan["run_id"],
    }, buffered=True)
    assert again.status_code == 409 and again.get_json()["code"] == "already_run"
    assert len(world.queued) == 1 and list(world.runs.items) == [(OWNER, run_id)]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
