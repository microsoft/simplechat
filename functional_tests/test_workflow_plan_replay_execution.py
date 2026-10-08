# test_workflow_plan_replay_execution.py
"""
Functional test for the headless plan replay execution.
Version: 0.261.306
Implemented in: 0.261.306

This test ensures that a saved plan replays end to end under the real headless orchestration
executor, with only the model stubbed: the creator is the only actor, the run lands in the
workflow's own private conversation and never in the chat it came from (even after that chat is
shared), the planner is never called, the frozen instruction and the run-time line reach the
model, and the task result is typed with durable ids. A cancelled workflow run, a lost workflow
lease or an exhausted budget cancels the orchestration run and fences its publication, so nothing
is published afterwards.

Checks raise AssertionError explicitly so they still run under ``python -O``.
"""

import hashlib
import importlib
import json
import sys
import threading
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceExistsError, CosmosResourceNotFoundError

from test_orchestration_harness_execution import harness, initialized_application  # noqa: F401
from test_support.orchestration_harness_execution import input_binding
from test_support.versioning import assert_app_version_at_least


OWNER = "owner"
SOURCE_CONVERSATION = "conversation-1"
WORKFLOW_ID = "workflow-1"
WORKFLOW_CONVERSATION = "workflow-conv"
WORKFLOW_RUN = "wf-run-1"
WORKFLOW_TURN = "workflow-turn-1"
TASK_ID = "task-1"
UNIT_KEY = f"task:{TASK_ID}"
NOW = datetime(2026, 9, 28, 13, 0, tzinfo=timezone.utc)
FROZEN_INSTRUCTION = "Prepare the complete requested content."
REPLAY_SETTINGS = {
    "enable_workflow_plan_replay": True,
    "enable_chat_orchestration": True,
    "allow_user_workflows": True,
    "enable_user_workspace": True,
    "chat_orchestration_enabled_capabilities": [],
}
HOSTILE_NAME = '<img src=x onerror="alert(1)">Weekly"\'</script>'
LATE_TEXT = "Late content that must never be published."


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def _wait_for(predicate, message, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(message)
        time.sleep(0.01)


@pytest.fixture
def replay(initialized_application):
    return importlib.import_module("functions_workflow_plan_replay")


@pytest.fixture
def runner_helpers(initialized_application):
    """The runner's real task sequence in this import generation, forgotten afterwards like the app."""
    before = set(sys.modules)
    tests = Path(__file__).resolve().parent
    try:
        yield importlib.import_module("test_workflow_task_sequence").load_runner_helpers
    finally:
        for name in set(sys.modules) - before:
            path = getattr(sys.modules.get(name), "__file__", None)
            if path and Path(path).resolve().is_relative_to(tests):
                sys.modules.pop(name, None)


def _settings(harness):
    return {**deepcopy(harness.settings), **REPLAY_SETTINGS}


def _frozen_task(harness, replay):
    harness.create(replies=["The prepared content."], final_response=input_binding("prepare"))
    harness.prepare().execute()
    freeze = replay.freeze_source_run(harness.read(), harness.conversation, OWNER, _settings(harness))
    require(freeze["refusals"] == [], f"The harness plan must be eligible: {freeze['refusals']}")
    payload = replay.build_plan_replay_payload(freeze, OWNER, "2026-09-28T09:00:00+00:00")
    return replay.attach_plan_replay({"id": TASK_ID, "type": "instructions"}, payload)


def _workflow(task, **changes):
    workflow = {
        "id": WORKFLOW_ID, "user_id": OWNER, "created_by": OWNER, "scope": "personal",
        "name": HOSTILE_NAME, "tasks": [task], "schedule": {"timezone": "America/New_York"},
    }
    workflow.update(changes)
    return workflow


def _workflow_conversation(harness, **changes):
    conversation = {
        "id": WORKFLOW_CONVERSATION, "user_id": OWNER, "title": HOSTILE_NAME,
        "chat_type": "workflow", "workflow_id": WORKFLOW_ID,
    }
    conversation.update(changes)
    harness.conversations.upsert_item(conversation)
    harness.messages.upsert_item({
        "id": WORKFLOW_TURN, "conversation_id": WORKFLOW_CONVERSATION, "role": "user",
        "content": "Run saved workflow", "timestamp": "2026-09-28T13:00:00+00:00",
    })
    return conversation


def _run(replay, harness, workflow, task, **overrides):
    kwargs = {
        "conversation_id": WORKFLOW_CONVERSATION, "run_id": WORKFLOW_RUN, "actor_user_id": OWNER,
        "user_message_id": WORKFLOW_TURN, "now": NOW, "poll_seconds": 0.05,
        "load_workflow": lambda user_id, workflow_id: deepcopy(workflow),
        "check_cancelled": lambda: None,
    }
    kwargs.update(overrides)
    settings = kwargs.pop("settings", None) or _settings(harness)
    return replay.execute_plan_replay_task(workflow, task, settings, **kwargs)


def _replay_run_id(replay, attempt=0):
    return replay._deterministic_id("run", WORKFLOW_RUN, TASK_ID, attempt, "run")


def _partition(container, partition):
    return {key: deepcopy(value) for key, value in container.items.items() if key[0] == partition}


def _answer_id(run_id):
    return importlib.import_module("functions_orchestration_checkpoints").orchestration_answer_message_id(run_id)


def _refused(replay, call, code):
    with pytest.raises(replay.PlanReplayRefused) as caught:
        call()
    require(caught.value.code == code, f"Expected {code}, got {caught.value.code}")
    require(caught.value.public_message == replay.REFUSAL_MESSAGES[code], "Refusals carry their fixed text.")
    return caught.value


def _join_worker(run_id):
    for thread in threading.enumerate():
        if thread.name == f"plan-replay-{run_id}":
            thread.join(30)
            require(not thread.is_alive(), "The replay worker must stop after a cancel.")


def _require_cancelled_and_fenced(harness, run_id):
    _join_worker(run_id)
    record = harness.runs.read_item(run_id, WORKFLOW_CONVERSATION)
    require(record.get("cancellation_requested_at"), "The orchestration run must be cancelled.")
    require(record.get("cancellation_requested_by") == OWNER, "The creator cancels the replay.")
    require(record.get("status") != "completed", "A cancelled replay never completes.")
    _require_fenced(harness, run_id)
    published = json.dumps(list(_partition(harness.messages, WORKFLOW_CONVERSATION).values()), default=str)
    require(LATE_TEXT not in published, "The late model output must never be published.")


def _require_fenced(harness, run_id):
    guards = [
        message for (partition, _), message in harness.messages.items.items()
        if partition == WORKFLOW_CONVERSATION and message.get("run_id") == run_id
        and (message.get("metadata") or {}).get("orchestration_publication_guard")
    ]
    require(guards and all(guard.get("token") is None for guard in guards), f"{run_id} must be fenced.")
    require((WORKFLOW_CONVERSATION, _answer_id(run_id)) not in harness.messages.items, f"{run_id} never publishes.")


class BlockingReply:
    """Holds the replay's model call open until the cancellation path fences publication."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self):
        self.entered.set()
        self.release.wait(20)
        return LATE_TEXT


def _releasing_fence(gate, fenced):
    recovery = importlib.import_module("functions_orchestration_recovery")

    def fence(record, container):
        fenced.append(record["id"])
        try:
            recovery.fence_publication(record, container)
        finally:
            gate.release.set()

    return fence


class RuntimeContainer:
    """In-memory, ETag-checked control storage for the real workflow runtime store."""

    def __init__(self):
        self.items = {}
        self.version = 0
        self.lock = threading.Lock()

    def create_item(self, body):
        with self.lock:
            key = (body["run_id"], body["id"])
            if key in self.items:
                raise CosmosResourceExistsError(status_code=409)
            return self._store(key, body)

    def read_item(self, item, partition_key):
        with self.lock:
            if (partition_key, item) not in self.items:
                raise CosmosResourceNotFoundError(status_code=404)
            return deepcopy(self.items[(partition_key, item)])

    def replace_item(self, item, body, etag=None, match_condition=None):
        with self.lock:
            key = (body["run_id"], item)
            if key not in self.items:
                raise CosmosResourceNotFoundError(status_code=404)
            if etag != self.items[key]["_etag"] or match_condition != MatchConditions.IfNotModified:
                raise CosmosHttpResponseError(status_code=412)
            return self._store(key, body)

    def _store(self, key, value):
        self.version += 1
        self.items[key] = {**deepcopy(value), "_etag": str(self.version)}
        return deepcopy(self.items[key])


class RuntimeClock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class SavedResults:
    """Content-addressed JSON storage standing in for the durable unit's result store."""

    def __init__(self):
        self.contents = {}

    def save(self, workflow, run_id, task_id, payload, **kwargs):
        content = json.dumps(payload, ensure_ascii=True, allow_nan=False, sort_keys=True)
        digest = hashlib.sha256(content.encode("ascii")).hexdigest()
        self.contents[digest] = content
        return {"task_id": task_id, "size_bytes": len(content), "sha256": digest}

    def load(self, workflow, run_id, task_id, reference):
        return json.loads(self.contents[reference["sha256"]])


class ProcessDied(BaseException):
    """A worker process that stops without running any cleanup."""


def _dying_claim(*args, **kwargs):
    importlib.import_module("functions_orchestration_plan_revisions").claim_plan_run(*args, **kwargs)
    raise ProcessDied()


def _runtime_store(clock):
    store = importlib.import_module("functions_workflow_runtime_store").WorkflowRuntimeStore(
        RuntimeContainer(), {"id": WORKFLOW_ID, "user_id": OWNER, "durable_execution": True}, WORKFLOW_RUN,
        clock=clock,
    )
    store.initialize(
        snapshot_ref={"storage": "cosmos", "schema_version": 1, "sha256": "a" * 64, "size_bytes": 100,
                      "chunk_count": 1},
        definition_revision="b" * 64, actor_user_id=OWNER, request_id="request-one",
    )
    return store


def _durable_execution(store, lease, results, polls=None):
    execution = importlib.import_module("functions_workflow_execution").DurableWorkflowExecution(
        store, lease, {"id": WORKFLOW_ID, "user_id": OWNER}, WORKFLOW_RUN,
        save_result=results.save, load_result=results.load,
    )
    if polls is not None:
        original_check = execution.check

        def counting_check():
            current = original_check()
            polls["ok"] += 1
            return current

        execution.check = counting_check
    return execution


def _durable_replay(replay, harness, workflow, task, **overrides):
    """Run the replay as the runner does: one replay-safe unit numbered by its durable attempt."""
    durable = importlib.import_module("functions_workflow_execution")
    execution = durable.current_workflow_execution()

    def operation():
        kwargs = {"check_cancelled": None, **overrides, "attempt": execution.unit(UNIT_KEY)["attempt"]}
        return _run(replay, harness, workflow, task, **kwargs)

    return durable.workflow_unit(UNIT_KEY, operation, inputs={"task": task}, replay_safe=True)


def _renew_past_the_ttl(store, clock, polls):
    """Advance the store clock past one lease TTL while the heartbeat and the join keep up."""
    store_module = importlib.import_module("functions_workflow_runtime_store")

    def expires_at():
        return store_module._parse_timestamp(store.read()["lease"]["expires_at"])

    for _ in range(3):
        clock.now += timedelta(seconds=20)
        target = clock.now + timedelta(seconds=store_module.DEFAULT_LEASE_SECONDS)
        _wait_for(lambda: expires_at() >= target, "The heartbeat must renew the workflow lease.")
        seen = polls["ok"]
        _wait_for(lambda: polls["ok"] > seen, "The join must confirm ownership after each renewal.")


def _replay_runs(harness):
    return {
        record["id"]: record for record in _partition(harness.runs, WORKFLOW_CONVERSATION).values()
        if (record.get("workflow_replay") or {}).get("workflow_run_id") == WORKFLOW_RUN
    }


def test_version_includes_plan_replay():
    assert_app_version_at_least("0.261.306")


def test_a_frozen_plan_replays_end_to_end_in_the_workflow_conversation(harness, replay):
    task = _frozen_task(harness, replay)
    workflow = _workflow(task)
    _workflow_conversation(harness)
    source_messages = _partition(harness.messages, SOURCE_CONVERSATION)
    source_runs = _partition(harness.runs, SOURCE_CONVERSATION)
    calls_before = len(harness.model_calls)
    execution = importlib.import_module("functions_orchestration_execution")
    prepared = []

    def prepare(claimed, **kwargs):
        prepared.append(deepcopy(kwargs.get("identity_context")))
        require(kwargs.get("execution_identity") is None, "No request identity crosses into the replay.")
        return execution.prepare_harness_execution(claimed, **kwargs)

    harness.replies = ["The replayed content."]
    result = _run(replay, harness, workflow, task, prepare_execution=prepare)

    run_id = _replay_run_id(replay)
    require(run_id == _replay_run_id(replay) and run_id.startswith("run_"), "The run id is deterministic.")
    require(prepared == [{"user_roles": [], "user_enable_agents": False}], f"Replay is role-free: {prepared}")
    require(len(harness.model_calls) == calls_before + 1, "Only the frozen compose step calls the model.")
    prompt = json.dumps(harness.model_calls[-1].get("messages"), ensure_ascii=False)
    require(FROZEN_INSTRUCTION in prompt, "The frozen instruction reaches the model.")
    time_line = importlib.import_module("functions_orchestration_workflow_context").request_local_time_line(
        "America/New_York", NOW,
    )
    require(time_line and "(America/New_York)" in time_line and time_line in prompt, prompt)

    record = harness.runs.read_item(run_id, WORKFLOW_CONVERSATION)
    frozen_steps = task["plan_replay"]["frozen_plan"]["steps"]
    require(
        [(step["step_id"], step["capability_id"], step.get("arguments")) for step in record["plan"]["steps"]]
        == [(step["step_id"], step["capability_id"], step.get("arguments")) for step in frozen_steps],
        "The replay runs exactly the frozen steps.",
    )
    require(record["user_id"] == OWNER and record["conversation_id"] == WORKFLOW_CONVERSATION, "Creator-owned run.")
    require(record["workflow_replay"] == {
        "workflow_id": WORKFLOW_ID, "workflow_run_id": WORKFLOW_RUN, "task_id": TASK_ID,
        "plan_sha256": task["plan_replay"]["plan_sha256"], "attempt": 0,
    }, record.get("workflow_replay"))
    require(record["user_message_id"] == WORKFLOW_TURN, "The saved workflow turn anchors the replay.")

    value = result["authoritative_result"]["value"]
    require(result["authoritative_result"]["kind"] == "json", "The task result is typed JSON.")
    require(result["plan_replay"] == {**value, "final_response": {**value["final_response"], "truncated": False}},
            "The run item's projection is the typed result with the answer's cap flag.")
    require(value["contract"] == "plan-replay-result-v1", value)
    require(value["orchestration_run_id"] == run_id, "The result names the durable orchestration run.")
    require(value["conversation_id"] == WORKFLOW_CONVERSATION, "The result lands in the workflow conversation.")
    require(value["plan_sha256"] == task["plan_replay"]["plan_sha256"], "The result names the frozen plan.")
    require(value["status"] == "completed", value)
    require(value["steps"] == [{
        "step_id": "prepare", "capability_id": "compose", "label": "Prepare content", "status": "completed",
    }], value["steps"])
    require(value["final_response"]["message_id"] == _answer_id(run_id), value["final_response"])
    require("The replayed content." in value["final_response"]["text"], value["final_response"])
    require(result["reply"] == value["final_response"]["text"], "The reply is the engine's final response.")
    require(value["artifacts"] == [], "A compose-only replay produces no artifacts.")
    answer = harness.messages.read_item(_answer_id(run_id), WORKFLOW_CONVERSATION)
    require(answer["role"] == "assistant", "The answer is published in the workflow conversation.")
    require(_partition(harness.messages, SOURCE_CONVERSATION) == source_messages, "The source chat is untouched.")
    require(_partition(harness.runs, SOURCE_CONVERSATION) == source_runs, "No run is added to the source chat.")


def test_the_typed_result_normalizes_ids_and_caps_the_inspector_copy(replay):
    record = {
        "id": 42, "conversation_id": WORKFLOW_CONVERSATION, "status": "completed", "outcome": "completed",
        "message": "x" * (replay.PLAN_REPLAY_RUN_ITEM_TEXT_LIMIT + 5),
        "workflow_replay": {"plan_sha256": "a" * 64},
        "plan": {"steps": []},
        "artifacts": [{"artifact_id": 7, "kind": "spreadsheet"}, {"id": "img", "type": "image"}],
    }
    answer = {"id": "answer-1", "metadata": {"orchestration": {"generated_images": [{"visual_id": 9, "message_id": 3}]}}}
    value = replay.build_plan_replay_result(record, answer)
    require(value["orchestration_run_id"] == "42", "Execution ids are strings, never model prose.")
    require(value["artifacts"] == [
        {"id": "9", "kind": "image", "message_id": "3"},
        {"id": "7", "kind": "file"},
        {"id": "img", "kind": "image"},
    ], value["artifacts"])
    require(len(value["final_response"]["text"]) == replay.PLAN_REPLAY_RUN_ITEM_TEXT_LIMIT + 5,
            "The stored json result keeps the whole answer.")

    projection = replay.plan_replay_run_item_projection(value)
    require(projection["final_response"] == {
        "message_id": "answer-1", "text": "x" * replay.PLAN_REPLAY_RUN_ITEM_TEXT_LIMIT, "truncated": True,
    }, "The run inspector's copy is capped and says so.")
    require({k: v for k, v in projection.items() if k != "final_response"}
            == {k: v for k, v in value.items() if k != "final_response"}, "Only the answer text is capped.")
    require(len(value["final_response"]["text"]) == replay.PLAN_REPLAY_RUN_ITEM_TEXT_LIMIT + 5,
            "Projecting never changes the stored result.")

    # An answer that carries no orchestration metadata, or none at all, still yields a typed result.
    for bare in (None, {"id": "answer-2"}, {"id": "answer-2", "metadata": {"orchestration": "prose"}}):
        bare_value = replay.build_plan_replay_result(record, bare)
        require([item["id"] for item in bare_value["artifacts"]] == ["7", "img"], bare_value["artifacts"])


@pytest.mark.parametrize("readable", [True, False])
def test_a_withheld_result_also_withholds_the_typed_projection(readable):
    from functions_saved_analysis import UNVERIFIED_WORKFLOW_OUTPUT_MESSAGE, sanitize_workflow_analysis_history

    workflow = {"id": "workflow-1", "user_id": "owner"}
    run_record = {"id": "run-1", "task_results": []}
    summary = {
        "contract_version": "workflow-result-v2",
        "producer": {"workflow_id": "workflow-1", "run_id": "run-1", "task_id": "replay"},
        "result_ref": {"sha256": "b" * 64},
    }
    item = {"task_id": "replay", "workflow_result": summary, "reply": "the answer",
            "plan_replay": {"contract": "plan-replay-result-v1", "final_response": {"text": "the answer"}}}
    reads = []

    def reader(*args, **kwargs):
        reads.append(args)
        if not readable:
            raise PermissionError("source access lost")

    _record, items, verified = sanitize_workflow_analysis_history(
        workflow, run_record, "owner", items=[item], result_reader=reader,
    )
    require(reads, "The stored result is checked before its preview is shown.")
    require(verified is readable, verified)
    if readable:
        require(items[0]["plan_replay"] == item["plan_replay"], "A verified result keeps its typed projection.")
    else:
        require("plan_replay" not in items[0], "A withheld result never leaks its answer through the projection.")
        require(items[0]["reply"] == UNVERIFIED_WORKFLOW_OUTPUT_MESSAGE, items[0])
    require("plan_replay" in item, "The stored item is never changed in place.")


def test_sharing_the_source_chat_later_changes_nothing(harness, replay):
    task = _frozen_task(harness, replay)
    _workflow_conversation(harness)
    shared = {
        **harness.conversation, "collaboration_conversation_id": "collaboration-1",
        "converted_to_collaboration_at": "2026-09-29T08:00:00+00:00",
    }
    harness.conversations.upsert_item(shared)
    source_messages = _partition(harness.messages, SOURCE_CONVERSATION)
    harness.replies = ["The replayed content."]

    result = _run(replay, harness, _workflow(task), task)

    require(result["plan_replay"]["conversation_id"] == WORKFLOW_CONVERSATION, "The replay stays private.")
    require(_partition(harness.messages, SOURCE_CONVERSATION) == source_messages, "The shared chat gets nothing.")
    require(
        harness.conversations.read_item(SOURCE_CONVERSATION, SOURCE_CONVERSATION)["converted_to_collaboration_at"],
        "The fixture shared the source chat.",
    )


def test_the_source_chat_is_never_the_replay_conversation(harness, replay):
    task = _frozen_task(harness, replay)
    runs_before = deepcopy(harness.runs.items)

    _refused(replay, lambda: _run(
        replay, harness, _workflow(task), task, conversation_id=SOURCE_CONVERSATION,
        user_message_id=harness.turn["id"],
    ), "conversation_context_not_replayable")

    require(harness.runs.items == runs_before, "A refused replay creates no orchestration run.")


@pytest.mark.parametrize("changes", [
    {"chat_type": "personal"},
    {"workflow_id": "another-workflow"},
    {"group_id": "group-1"},
    {"user_id": "someone-else"},
    {"converted_to_collaboration_at": "2026-09-29T08:00:00+00:00", "collaboration_conversation_id": "c-1"},
    {"orchestration_deleted": True},
])
def test_only_the_private_workflow_conversation_is_accepted(harness, replay, changes):
    task = _frozen_task(harness, replay)
    _workflow_conversation(harness, **changes)
    runs_before = deepcopy(harness.runs.items)
    context_error = importlib.import_module("functions_orchestration_context").ConversationContextError

    with pytest.raises(context_error):
        _run(replay, harness, _workflow(task), task)

    require(harness.runs.items == runs_before, "A refused conversation creates no orchestration run.")


def test_only_the_creator_runs_the_replay(harness, replay):
    task = _frozen_task(harness, replay)
    _workflow_conversation(harness)
    workflow = _workflow(task)
    runs_before = deepcopy(harness.runs.items)

    _refused(replay, lambda: _run(replay, harness, workflow, task, actor_user_id="intruder"), "creator_mismatch")
    _refused(replay, lambda: _run(
        replay, harness, _workflow(task, created_by="someone-else"), task,
    ), "creator_mismatch")
    _refused(replay, lambda: _run(replay, harness, _workflow(task, scope="group", group_id="g-1"), task),
             "group_not_supported")

    require(harness.runs.items == runs_before, "A refused actor creates no orchestration run.")


def test_a_deleted_or_changed_workflow_stops_before_step_one(harness, replay):
    task = _frozen_task(harness, replay)
    _workflow_conversation(harness)
    workflow = _workflow(task)
    changed = deepcopy(task)
    changed["plan_replay"]["plan_sha256"] = "0" * 64
    runs_before = deepcopy(harness.runs.items)
    calls_before = len(harness.model_calls)

    _refused(replay, lambda: _run(replay, harness, workflow, task, load_workflow=lambda u, w: None),
             "workflow_unavailable")
    _refused(replay, lambda: _run(
        replay, harness, workflow, task, load_workflow=lambda u, w: {**deepcopy(workflow), "deleting": True},
    ), "workflow_unavailable")
    _refused(replay, lambda: _run(
        replay, harness, workflow, task, load_workflow=lambda u, w: _workflow(changed),
    ), "plan_hash_mismatch")
    _refused(replay, lambda: _run(
        replay, harness, workflow, task, settings={**_settings(harness), "enable_workflow_plan_replay": False},
    ), "replay_disabled")
    _refused(replay, lambda: _run(
        replay, harness, workflow, task, settings={**_settings(harness), "allow_user_workflows": False},
    ), "personal_workflows_disabled")
    _refused(replay, lambda: _run(
        replay, harness, workflow, task, settings={**_settings(harness), "enable_chat_orchestration": False},
    ), "orchestration_disabled")
    with pytest.raises(replay.PlanReplayRefused) as removed:
        _run(replay, harness, workflow, task,
             settings={**_settings(harness), "chat_orchestration_enabled_capabilities": ["document_search"]})
    require(removed.value.code == "capability_unavailable", removed.value.code)
    require(removed.value.public_message.startswith("Step 1 (")
            and "is turned off or no longer available" in removed.value.public_message,
            removed.value.public_message)

    require(harness.runs.items == runs_before, "Nothing runs once the workflow is gone or changed.")
    require(len(harness.model_calls) == calls_before, "No model call happens before re-authorization.")


def test_the_replay_needs_the_saved_workflow_turn(harness, replay):
    task = _frozen_task(harness, replay)
    _workflow_conversation(harness)
    workflow = _workflow(task)

    _refused(replay, lambda: _run(
        replay, harness, workflow, task, user_message_id=None, read_workflow_run=lambda u, r: {},
    ), "replay_execution_failed")
    harness.messages.upsert_item({
        "id": "assistant-turn", "conversation_id": WORKFLOW_CONVERSATION, "role": "assistant",
        "content": "Not a user turn", "timestamp": "2026-09-28T13:00:01+00:00",
    })
    _refused(replay, lambda: _run(replay, harness, workflow, task, user_message_id="assistant-turn"),
             "replay_execution_failed")


def test_a_cancelled_workflow_run_cancels_and_fences_the_replay(harness, replay):
    task = _frozen_task(harness, replay)
    _workflow_conversation(harness)
    gate, fenced = BlockingReply(), []
    harness.replies = [gate]

    class StopRequested(Exception):
        pass

    def check_cancelled():
        if gate.entered.is_set():
            raise StopRequested()

    with pytest.raises(StopRequested):
        _run(replay, harness, _workflow(task), task, check_cancelled=check_cancelled,
             fence=_releasing_fence(gate, fenced))

    run_id = _replay_run_id(replay)
    require(fenced == [run_id], f"The cancel fences the replay's publication: {fenced}")
    _require_cancelled_and_fenced(harness, run_id)


def test_an_exhausted_budget_cancels_and_fences_the_replay(harness, replay):
    task = _frozen_task(harness, replay)
    _workflow_conversation(harness)
    gate, fenced, reads = BlockingReply(), [], []
    harness.replies = [gate]

    def clock():
        reads.append(1)
        if len(reads) == 1:
            return 0.0
        return 10_000.0 if gate.entered.is_set() else 0.0

    _refused(replay, lambda: _run(
        replay, harness, _workflow(task), task, clock=clock, max_seconds=60,
        fence=_releasing_fence(gate, fenced),
    ), "replay_budget_exceeded")

    run_id = _replay_run_id(replay)
    require(fenced == [run_id], f"The budget stop fences the replay's publication: {fenced}")
    _require_cancelled_and_fenced(harness, run_id)


def test_a_lost_workflow_lease_cancels_and_fences_the_replay(harness, replay):
    task = _frozen_task(harness, replay)
    _workflow_conversation(harness)
    store_module = importlib.import_module("functions_workflow_runtime_store")
    durable = importlib.import_module("functions_workflow_execution")
    clock = RuntimeClock()
    store = _runtime_store(clock)
    gate, fenced, problems, polls, joined = BlockingReply(), [], [], {"ok": 0}, []
    renewed = threading.Event()

    def renewing_reply():
        try:
            _renew_past_the_ttl(store, clock, polls)
            renewed.set()
            clock.now += timedelta(minutes=5)
        except BaseException as exc:
            problems.append(exc)
        return gate()

    harness.replies = [renewing_reply]
    with pytest.raises(store_module.WorkflowRuntimeConflict):
        with store_module.WorkflowRuntimeLease(store, owner_id="replay-worker", heartbeat_seconds=0.02) as lease:
            execution = _durable_execution(store, lease, SavedResults(), polls)
            with durable.workflow_execution_scope(execution):
                try:
                    _durable_replay(replay, harness, _workflow(task), task, fence=_releasing_fence(gate, fenced))
                except store_module.WorkflowRuntimeConflict as exc:
                    joined.append(exc)
                    raise

    require(problems == [], f"The renewal phase failed: {problems}")
    require(renewed.is_set(), "The lease outlived its first expiry because the heartbeat renewed it.")
    require(joined and joined[0].code == "ownership_lost", f"The join stops on a lost lease: {joined}")
    run_id = _replay_run_id(replay, 1)
    require(fenced == [run_id], f"A lost lease fences the replay's publication: {fenced}")
    _require_cancelled_and_fenced(harness, run_id)
    unit = store.read()["units"][UNIT_KEY]
    require(unit.get("state") == "running" and unit.get("attempt") == 1, f"The lost unit stays claimable: {unit}")


def test_executor_failures_map_to_fixed_codes(harness, replay):
    task = _frozen_task(harness, replay)
    _workflow_conversation(harness)
    workflow = _workflow(task)
    execution = importlib.import_module("functions_orchestration_execution")

    def failing(error):
        def prepare(claimed, **kwargs):
            raise error
        return prepare

    _refused(replay, lambda: _run(
        replay, harness, workflow, task,
        prepare_execution=failing(execution.HarnessExecutionError("model_routing_changed")),
    ), "model_unavailable")
    refusal = _refused(replay, lambda: _run(
        replay, harness, workflow, task, attempt=1, prepare_execution=failing(RuntimeError("provider secret detail")),
    ), "replay_execution_failed")
    require("provider secret detail" not in refusal.public_message, "Provider text never reaches the user.")
    calls_before = len(harness.model_calls)
    _refused(replay, lambda: _run(replay, harness, workflow, task), "replay_execution_failed")
    require(len(harness.model_calls) == calls_before, "A re-entered attempt never runs a second time.")


def test_a_durable_replay_unit_keeps_its_lease_past_the_ttl_and_completes(harness, replay):
    task = _frozen_task(harness, replay)
    _workflow_conversation(harness)
    store_module = importlib.import_module("functions_workflow_runtime_store")
    durable = importlib.import_module("functions_workflow_execution")
    clock, results, problems, polls = RuntimeClock(), SavedResults(), [], {"ok": 0}
    store = _runtime_store(clock)

    def renewing_reply():
        try:
            _renew_past_the_ttl(store, clock, polls)
        except BaseException as exc:
            problems.append(exc)
        return "The replayed content."

    harness.replies = [renewing_reply]
    with store_module.WorkflowRuntimeLease(store, owner_id="replay-worker", heartbeat_seconds=0.02) as lease:
        with durable.workflow_execution_scope(_durable_execution(store, lease, results, polls)):
            result = _durable_replay(replay, harness, _workflow(task), task)

    require(problems == [], f"The renewal phase failed: {problems}")
    require(clock.now - NOW >= timedelta(seconds=store_module.DEFAULT_LEASE_SECONDS), "The unit outlived one TTL.")
    unit = store.read()["units"][UNIT_KEY]
    require(
        unit.get("state") == "completed" and unit.get("attempt") == 1 and unit.get("replay_safe") is True,
        f"The replay unit completes once and is replay-safe: {unit}",
    )
    run_id = _replay_run_id(replay, 1)
    require(result["authoritative_result"]["value"]["orchestration_run_id"] == run_id, "Attempt 1 names its run.")
    require(harness.runs.read_item(run_id, WORKFLOW_CONVERSATION).get("status") == "completed", "The run completes.")
    require(results.load(None, None, None, unit["result_ref"])["value"] == result, "The unit saves the typed result.")


def test_a_durable_restart_settles_the_dead_attempt_and_replays_once(harness, replay):
    task = _frozen_task(harness, replay)
    _workflow_conversation(harness)
    workflow = _workflow(task)
    store_module = importlib.import_module("functions_workflow_runtime_store")
    durable = importlib.import_module("functions_workflow_execution")
    clock, results = RuntimeClock(), SavedResults()
    store = _runtime_store(clock)
    run_one, run_two = _replay_run_id(replay, 1), _replay_run_id(replay, 2)

    dead = store_module.WorkflowRuntimeLease(store, owner_id="worker-one", heartbeat_seconds=0)
    dead.__enter__()
    with pytest.raises(ProcessDied):
        with durable.workflow_execution_scope(_durable_execution(store, dead, results)):
            _durable_replay(replay, harness, workflow, task, claim_run=_dying_claim)
    unit = store.read()["units"][UNIT_KEY]
    require(unit.get("state") == "running" and unit.get("attempt") == 1, f"The dead worker left its unit: {unit}")
    left = harness.runs.read_item(run_one, WORKFLOW_CONVERSATION)
    require(left.get("status") == "running" and left.get("execution_lease"), "The dead worker left its run open.")

    left["execution_lease"]["expires_at"] = "2000-01-01T00:00:00+00:00"
    harness.runs.upsert_item(left)
    clock.now += timedelta(minutes=5)
    harness.replies = ["The replayed content."]
    with store_module.WorkflowRuntimeLease(store, owner_id="worker-two", heartbeat_seconds=0.02) as lease:
        with durable.workflow_execution_scope(_durable_execution(store, lease, results)):
            result = _durable_replay(replay, harness, workflow, task)

    require(result["authoritative_result"]["value"]["orchestration_run_id"] == run_two, "The restart replays once.")
    unit = store.read()["units"][UNIT_KEY]
    require(unit.get("state") == "completed" and unit.get("attempt") == 2, f"The restart completes the unit: {unit}")
    settled = harness.runs.read_item(run_one, WORKFLOW_CONVERSATION)
    require(settled.get("status") == "failed", "The dead attempt's run is settled, not left running.")
    require((settled.get("failure") or {}).get("code") == "ownership_lost", f"Settled as lost: {settled.get('failure')}")
    require(settled.get("execution_lease") is None, "The dead attempt's lease is cleared.")
    _require_fenced(harness, run_one)
    statuses = {run_id: record.get("status") for run_id, record in _replay_runs(harness).items()}
    require(statuses == {run_one: "failed", run_two: "completed"}, f"Never two live runs: {statuses}")
    require((WORKFLOW_CONVERSATION, _answer_id(run_two)) in harness.messages.items, "The restart publishes once.")


def test_a_completed_prior_attempt_is_adopted_not_repeated(harness, replay):
    task = _frozen_task(harness, replay)
    _workflow_conversation(harness)
    workflow = _workflow(task)
    harness.replies = ["The replayed content."]
    first = _run(replay, harness, workflow, task, attempt=1)
    calls_before = len(harness.model_calls)
    second = _run(replay, harness, workflow, task, attempt=2)

    require(second == first, "A restart after completion returns the completed attempt's result.")
    require(set(_replay_runs(harness)) == {_replay_run_id(replay, 1)}, "Adoption creates no second run.")
    require(len(harness.model_calls) == calls_before, "Adoption never calls the model again.")


def test_a_completed_prior_attempt_of_another_plan_is_refused(harness, replay):
    task = _frozen_task(harness, replay)
    _workflow_conversation(harness)
    workflow = _workflow(task)
    harness.replies = ["The replayed content."]
    _run(replay, harness, workflow, task, attempt=1)
    run_one = _replay_run_id(replay, 1)
    record = harness.runs.read_item(run_one, WORKFLOW_CONVERSATION)
    record["workflow_replay"]["plan_sha256"] = "f" * 64
    harness.runs.upsert_item(record)

    _refused(replay, lambda: _run(replay, harness, workflow, task, attempt=2), "replay_execution_failed")
    require(set(_replay_runs(harness)) == {run_one}, "A prior run of another plan is never adopted or repeated.")


def test_a_live_prior_attempt_is_stopped_and_fenced_but_never_taken_over(harness, replay):
    task = _frozen_task(harness, replay)
    _workflow_conversation(harness)
    workflow = _workflow(task)
    with pytest.raises(ProcessDied):
        _run(replay, harness, workflow, task, attempt=1, claim_run=_dying_claim)
    run_one = _replay_run_id(replay, 1)
    token = harness.runs.read_item(run_one, WORKFLOW_CONVERSATION)["execution_lease"]["token"]

    _refused(replay, lambda: _run(
        replay, harness, workflow, task, attempt=2, reconcile_seconds=0.2,
    ), "replay_execution_failed")
    record = harness.runs.read_item(run_one, WORKFLOW_CONVERSATION)
    require(record.get("cancellation_requested_at"), "The live prior attempt is asked to stop.")
    require(record.get("cancellation_requested_by") == OWNER, "Only the creator asks it to stop.")
    require(record.get("status") == "running", "A live lease is never settled by another attempt.")
    require((record.get("execution_lease") or {}).get("token") == token, "A live lease is never taken over.")
    _require_fenced(harness, run_one)
    require(set(_replay_runs(harness)) == {run_one}, "No second run starts while the first is live.")


def test_an_interrupted_attempt_settles_its_own_run(harness, replay):
    task = _frozen_task(harness, replay)
    _workflow_conversation(harness)

    def interrupted(claimed, **kwargs):
        raise RuntimeError("The worker stopped.")

    _refused(replay, lambda: _run(
        replay, harness, _workflow(task), task, attempt=1, prepare_execution=interrupted,
    ), "replay_execution_failed")
    record = harness.runs.read_item(_replay_run_id(replay, 1), WORKFLOW_CONVERSATION)
    require(record.get("status") == "failed", "A stopped attempt never leaves its run running.")
    require((record.get("failure") or {}).get("code") == "execution_interrupted", f"{record.get('failure')}")
    require(record.get("execution_lease") is None, "The stopped attempt releases its own lease.")
    _require_fenced(harness, _replay_run_id(replay, 1))


def test_the_runner_replays_one_durable_unit_numbered_by_its_own_attempt(replay, runner_helpers, monkeypatch):
    store_module = importlib.import_module("functions_workflow_runtime_store")
    durable = importlib.import_module("functions_workflow_execution")
    calls = []

    def executor(workflow, task, settings, *, conversation_id, run_id, actor_user_id, attempt, check_cancelled):
        unit = durable.current_workflow_execution().unit(UNIT_KEY)
        calls.append({"attempt": attempt, "replay_safe": unit.get("replay_safe"), "actor": actor_user_id,
                      "conversation": conversation_id, "run": run_id})
        if len(calls) == 1:
            raise ProcessDied()
        check_cancelled()
        value = replay.build_plan_replay_result({
            "id": f"replay-attempt-{attempt}", "conversation_id": conversation_id, "status": "completed",
            "outcome": "completed", "message": "The replayed content.",
            "workflow_replay": {"plan_sha256": "a" * 64},
        })
        return {"reply": "The replayed content.", "authoritative_result": {"kind": "json", "value": value},
                "plan_replay": replay.plan_replay_run_item_projection(value)}

    monkeypatch.setattr(replay, "execute_plan_replay_task", executor)
    helpers, saved_items = runner_helpers(lambda *args, **kwargs: pytest.fail("No runner answers a saved plan."))
    # Bound to this import generation, whichever generation first loaded the shared helpers.
    helpers.update({
        "current_workflow_execution": durable.current_workflow_execution,
        "workflow_unit": durable.workflow_unit,
        "assert_workflow_execution_owned": durable.assert_workflow_execution_owned,
        "_raise_if_workflow_run_cancelled": lambda *_args: durable.assert_workflow_execution_owned(),
    })
    workflow = {
        "id": WORKFLOW_ID, "name": HOSTILE_NAME, "user_id": OWNER, "created_by": OWNER,
        "definition_version": 2, "durable_execution": True, "runner_type": "model",
        "document_action": {"type": "none"}, "error_handling": {"strategy": "halt", "retry_count": 2},
        "tasks": [{"id": TASK_ID, "name": replay.PLAN_REPLAY_TASK_NAME, "type": replay.PLAN_REPLAY_TASK_TYPE,
                   "instructions": FROZEN_INSTRUCTION, "plan_replay": {"plan_sha256": "a" * 64}}],
    }
    clock, results = RuntimeClock(), SavedResults()
    store = _runtime_store(clock)

    def run_sequence(lease):
        with durable.workflow_execution_scope(_durable_execution(store, lease, results)):
            return helpers["_execute_workflow_task_sequence"](
                workflow, dict(REPLAY_SETTINGS), WORKFLOW_CONVERSATION, WORKFLOW_RUN, None, {},
                actor_user_id=OWNER,
            )

    dead = store_module.WorkflowRuntimeLease(store, owner_id="worker-one", heartbeat_seconds=0)
    dead.__enter__()
    with pytest.raises(ProcessDied):
        run_sequence(dead)
    clock.now += timedelta(minutes=5)
    with store_module.WorkflowRuntimeLease(store, owner_id="worker-two", heartbeat_seconds=0.02) as lease:
        result = run_sequence(lease)

    # The unit's own attempt numbers the replay, so a restart never reuses the dead worker's run
    # identity; and the unit is replay-safe, so the restart replays instead of pausing for review.
    require([call["attempt"] for call in calls] == [1, 2], f"The durable attempt numbers each replay: {calls}")
    require(all(call["replay_safe"] is True for call in calls), f"The replay unit is replay-safe: {calls}")
    require({(call["actor"], call["conversation"], call["run"]) for call in calls}
            == {(OWNER, WORKFLOW_CONVERSATION, WORKFLOW_RUN)}, f"The creator replays in the workflow run: {calls}")
    state = store.read()
    unit = state["units"][UNIT_KEY]
    require(unit.get("state") == "completed" and unit.get("attempt") == 2, f"The restart completes the unit: {unit}")
    require(not state.get("gate"), f"A restart never pauses a replay for review: {state.get('gate')}")
    require([task["status"] for task in result["task_results"]] == ["succeeded"], result["task_results"])
    final = [item for item in saved_items if item.get("plan_replay")]
    require(len(final) == 1, f"One run item carries the typed result: {saved_items}")
    require((final[0].get("plan_replay") or {}).get("orchestration_run_id") == "replay-attempt-2",
            f"The run item carries the typed result of the replay that completed: {final[0].get('plan_replay')}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:langsmith_plugin", "-p", "no:cacheprovider"]))
