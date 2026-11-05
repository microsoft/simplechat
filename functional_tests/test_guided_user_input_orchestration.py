# test_guided_user_input_orchestration.py
"""Functional tests for durable user-input waits in real orchestration execution.

Version: 0.261.411
Implemented in: 0.261.411
Uses the existing initialized application and SDK-default offline harness.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import time
from flask import Flask, session

from test_action_credentials_orchestration_continuation import (
    configure_real_credentials, harness, initialized_continuation,  # noqa: F401
)
from test_orchestration_action_chart_delivery import ACTION, _enable_action, _normalize, _store
from test_action_personal_credentials import CredentialContainer, manifest
from test_support.orchestration_harness_execution import compose_step, input_binding


class QuestionContainer(CredentialContainer):
    """SDK-default point/write documents with plain, scoped query projections."""

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        parameters = {item["name"]: item["value"] for item in parameters or []}
        rows = [
            row for (partition, _key), row in self.items.items()
            if partition == partition_key and row.get("user_id") == parameters["@user"]
            and row.get("record_type") == "pending_elicitation"
            and row["status"] in {"pending", "processing"}
        ]
        return [{"question": deepcopy(row["question"])} for row in rows[:1]]


def test_human_input_wait_uses_the_bounded_existing_deadline_allowance():
    clock = importlib.import_module("action_credential_deadline")
    now = datetime.now(timezone.utc)
    original = now + timedelta(seconds=30)
    record = {
        "execution_deadline_at": original.isoformat(), "status": "waiting",
        "credential_wait_started_at": now.isoformat(),
        "pending_results": {"step": {"kind": "user_input", "request_id": "input-one"}},
    }
    deadline = clock.execution_deadline(record, now=now + timedelta(minutes=10))
    assert deadline == original + timedelta(minutes=10)
    bounded = clock.execution_deadline(record, now=now + timedelta(days=2))
    assert bounded == original + timedelta(days=1)


def test_user_input_wait_requires_its_claim_and_preserves_completed_steps(harness, monkeypatch):
    state = importlib.import_module("functions_action_credential_state")
    owner = importlib.import_module("functions_user_input")
    adapters = importlib.import_module("functions_orchestration_adapters")
    executor = importlib.import_module("functions_orchestration_executor")
    stops = importlib.import_module("agent_interaction_contracts")
    monkeypatch.setattr(state, "_container", CredentialContainer("user_id"))
    completed_calls = _enable_action(harness, monkeypatch, with_chart=False)
    configure_real_credentials(harness, monkeypatch, manifest())
    resolver = executor._dependency_adapter
    action = resolver("action_invoke")
    item_id = "input-orchestration-test"

    def wait_then_act(step, context, **kwargs):
        try:
            item = owner.read_request("owner", item_id)
        except LookupError:
            descriptor = adapters._credential_step_continuation(step, context)
            item = state.create("owner", {
                "id": item_id, "record_type": "user_input_request", "conversation_id": "conversation-1",
                "status": "pending", "continuation": descriptor,
                "expires_at": time.time() + 86400,
            })
        if item["status"] == "continuing":
            return action(step, context, **kwargs)
        return adapters._credential_wait_result(stops.UserInputRequired({"id": item_id}), kwargs.get("emit"))

    monkeypatch.setattr(executor, "_dependency_adapter", lambda capability_id:
                        wait_then_act if capability_id == "action_invoke" else resolver(capability_id))
    plan = _normalize(harness, {"steps": [
        compose_step("before"),
        {"step_id": "question", "capability_id": "action_invoke",
         "arguments": {"action_ref": ACTION["action_ref"], "task": "Read one ticket."}},
        compose_step("answer", inputs={"source": {"binding": input_binding("question", "prepared"), "allow_partial": False}}),
    ], "final_response": input_binding("answer")})
    _store(harness, plan, replies=["Retain the completed work.", "Finish after the answers."])
    execution = harness.prepare()
    progress = []
    frames = list(execution.execute(emit=progress.append))
    waiting = harness.read()
    assert waiting["status"] == "waiting" and "user_input_required" in "".join([*progress, *frames])
    before = deepcopy(waiting["task_results"]["before"])
    authorize = lambda: harness.bootstrap.read_owned_conversation("owner", "conversation-1")
    unclaimed = harness.continuation.claim_run_continuation(
        "run-1", "owner", "conversation-1", authorize=authorize, message_container=harness.messages,
    )
    assert unclaimed is None
    item = owner.read_request("owner", item_id)
    state.replace("owner", item, {"status": "continuing", "continuation_claim": "owned"}, item["_etag"])
    claimed = harness.continuation.claim_run_continuation(
        "run-1", "owner", "conversation-1", authorize=authorize, message_container=harness.messages,
        input_request_id=item_id,
    )
    assert claimed is not None
    record, lease = claimed
    app = Flask("input-continuation")
    app.secret_key = "local-test-only"
    contexts = importlib.import_module("agent_execution_context")
    with app.test_request_context("/", headers={"X-SimpleChat-UI": "v2"}):
        session["user"] = {"oid": "owner"}
        identity = contexts.capture_execution_identity("owner", "conversation-1")
    resumed = harness.execution.prepare_harness_execution(
        record, settings=harness.settings, lease=lease, checkpoint_factory=harness.continuation.ContinuationCheckpoints,
        execution_identity=identity,
    )
    list(resumed.execute())
    completed = harness.read()
    assert completed["status"] == "completed"
    assert completed["task_results"]["before"] == before
    assert len(completed_calls) == 1


def test_planner_question_projection_and_cancellation_keep_sdk_etags(harness, monkeypatch):
    runs = importlib.import_module("functions_orchestration_runs")
    container = QuestionContainer("conversation_id")
    monkeypatch.setattr(runs, "cosmos_orchestration_runs_container", container)
    question = harness.schema.normalize_elicitation({
        "message": "Which policy applies?",
        "requested_schema": {"properties": {"policy": {"type": "string"}}, "required": ["policy"]},
    }, "run-question")
    question.update(turn_id="turn-question")
    stored = runs.create_pending_elicitation(
        question, {"user_message": "PRIVATE_ORIGINAL", "seeds": {}},
        "owner", "conversation-1", "turn-question",
    )
    assert stored["_etag"]
    projected = runs.list_pending_questions("owner", "conversation-1")
    assert projected == [question]
    assert "PRIVATE_ORIGINAL" not in str(projected)
    runs.cancel_pending_question(
        "owner", "conversation-1", "turn-question", question["elicitation_id"], question["revision"],
    )
    cancelled = runs.get_pending_elicitation("owner", "conversation-1", "turn-question")
    assert cancelled["status"] == "completed" and cancelled["cancelled"]
    remaining = runs.list_pending_questions("owner", "conversation-1")
    assert remaining == []
