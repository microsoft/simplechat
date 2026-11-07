# test_orchestration_planning_persistence.py
"""
Regression coverage for durable initial orchestration turns.
Version: 0.261.420
Implemented in: 0.261.415
Typed planner failure persistence added in: 0.261.419

Real authenticated routes and SDK-default offline storage exercise admission,
clarification, failure, disconnect, Auto handoff, cancellation, and explicit retry.
Only external model/storage I/O is replaced by the existing harness.
"""

from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import json
import importlib
import threading

import pytest
from flask import Blueprint

import functions_orchestration_planning as planning
from test_orchestration_elicitation_routes import (
    empty_history_runtime, plan_doc, sse_frames, style_question,
)
from test_orchestration_harness_routes import login, modules, real_http_harness
from test_support.orchestration_revisions import AtomicMemoryContainer


CONVERSATION = "conversation-1"
TURN = "durable-turn"
MESSAGE = "Write a short source-free explanation."
PLAN_PATH = "/api/v2/orchestration/plan"
STATUS_PATH = f"/api/v2/orchestration/turns/{TURN}"


def body(**changes):
    return {
        "conversation_id": CONVERSATION, "turn_id": TURN,
        "message": MESSAGE, "approval_mode": "manual",
        "planning_submission_id": "submission-1", **changes,
    }


def questions(runtime):
    return [
        item for item in runtime.harness.messages.items.values()
        if item.get("role") == "user" and item.get("content") == MESSAGE
    ]


def status(runtime, *, include_request=False):
    response = runtime.client.get(
        STATUS_PATH, query_string={
            "conversation_id": CONVERSATION,
            **({"include_request": "1"} if include_request else {}),
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["turn"]


@pytest.mark.parametrize("outcome", ["failed", "clarification", "success"])
def test_initial_question_and_outcome_are_saved(empty_history_runtime, outcome):
    runtime = empty_history_runtime
    proposal = {"kind": "plan", "steps": []} if outcome == "failed" else (
        style_question() if outcome == "clarification" else plan_doc()
    )
    runtime.harness.replies.append(json.dumps(proposal))
    response = runtime.client.post(PLAN_PATH, json=body(), buffered=True)
    frames = sse_frames(response)
    saved = questions(runtime)
    current = status(runtime, include_request=True)
    assert response.status_code == 200
    assert len(saved) == 1
    assert saved[0]["metadata"]["orchestration_turn_id"] == TURN
    acknowledgement = next(frame for frame in frames if frame.get("type") == "user_message_persisted")
    assert acknowledgement["user_message_id"] == saved[0]["id"]
    assert acknowledgement["server_managed"] is True
    expected = {"failed": "failed", "clarification": "awaiting_clarification", "success": "awaiting_review"}
    assert current["status"] == expected[outcome]
    assert current["request"]["message"] == MESSAGE
    assert current["user_message_id"] == saved[0]["id"]
    assert "claim_id" not in json.dumps(current)
    if outcome == "clarification":
        assert current["elicitation"]["message"] == "Choose a response style."
    if outcome == "failed":
        assert current["error"] and current["error_code"] == "invalid_plan_work"
    if outcome == "success":
        record = runtime.harness.runs.read_item(current["run_id"], CONVERSATION)
        assert record["conversation_context"]["messages"] == []


def hold_planner(runtime, modules, monkeypatch):
    entered, release, settled = threading.Event(), threading.Event(), threading.Event()
    original_plan = modules.route.plan_request
    original_update = modules.route._update_planning_owner

    def held(*args, **kwargs):
        entered.set()
        if not release.wait(timeout=10):
            raise RuntimeError("The test did not release its planner.")
        return original_plan(*args, **kwargs)

    def updated(*args, **kwargs):
        result = original_update(*args, **kwargs)
        if kwargs.get("status") in {"awaiting_review", "awaiting_clarification", "failed", "completed"}:
            settled.set()
        return result

    monkeypatch.setattr(modules.route, "plan_request", held)
    monkeypatch.setattr(modules.route, "_update_planning_owner", updated)
    return entered, release, settled


@pytest.mark.parametrize("automatic", [False, True])
def test_disconnect_does_not_own_planning_or_auto_execution(
    empty_history_runtime, modules, monkeypatch, automatic,
):
    runtime = empty_history_runtime
    runtime.harness.replies.append(json.dumps(plan_doc()))
    if automatic:
        runtime.harness.replies.append("The answer completed without a browser.")
    entered, release, settled = hold_planner(runtime, modules, monkeypatch)
    response = runtime.client.post(
        PLAN_PATH, json=body(approval_mode="auto" if automatic else "manual"), buffered=False,
    )
    try:
        planner_entered = entered.wait(timeout=10)
        assert planner_entered
        current = status(runtime)
        assert current["status"] == "planning"
        assert len(questions(runtime)) == 1
        response.close()
    finally:
        release.set()
    worker_settled = settled.wait(timeout=10)
    assert worker_settled
    current = status(runtime)
    assert current["status"] == ("completed" if automatic else "awaiting_review")
    assert len(questions(runtime)) == 1
    if automatic:
        answers = runtime.harness.assistant_messages()
        assert len(answers) == 1
        assert answers[0]["content"] == "The answer completed without a browser."


def test_duplicate_submission_observes_one_planner(empty_history_runtime, modules, monkeypatch):
    runtime = empty_history_runtime
    runtime.harness.replies.append(json.dumps(plan_doc()))
    entered, release, settled = hold_planner(runtime, modules, monkeypatch)
    first = runtime.client.post(PLAN_PATH, json=body(), buffered=False)
    try:
        planner_entered = entered.wait(timeout=10)
        assert planner_entered
        second = runtime.client.post(PLAN_PATH, json=body(), buffered=True)
        frames = sse_frames(second)
        adopted = next(frame["turn"] for frame in frames if frame.get("type") == "orchestration_turn")
        assert adopted["status"] == "planning"
        assert len(questions(runtime)) == 1
        assert runtime.harness.model_calls == []
    finally:
        first.close()
        release.set()
    worker_settled = settled.wait(timeout=10)
    assert worker_settled


@pytest.mark.parametrize("same_request", [False, True])
def test_concurrent_question_creation_never_upserts_over_the_winner(
    empty_history_runtime, modules, monkeypatch, same_request,
):
    runtime = empty_history_runtime
    save = modules.route._save_message
    competing_content = MESSAGE if same_request else "A different concurrent question."

    def raced_save(conversation_id, role, content, **kwargs):
        state = kwargs["metadata"][planning.PLANNING_METADATA]
        competing = planning.new_planning_attempt(
            {**state["request"], "message": competing_content}, TURN, state["submission_id"],
        )
        runtime.harness.messages.create_item({
            "id": kwargs["message_id"], "conversation_id": conversation_id, "role": role,
            "content": competing_content, "timestamp": "2026-01-01T10:00:00Z",
            "metadata": {**kwargs["metadata"], planning.PLANNING_METADATA: competing},
        })
        return save(conversation_id, role, content, **kwargs)

    monkeypatch.setattr(modules.route, "_save_message", raced_save)
    response = runtime.client.post(PLAN_PATH, json=body(), buffered=True)
    frames = sse_frames(response)
    stored = runtime.harness.messages.read_item(planning.planning_question_id(CONVERSATION, TURN), CONVERSATION)
    assert stored["content"] == competing_content
    assert stored["timestamp"] == "2026-01-01T10:00:00Z"
    assert runtime.harness.model_calls == []
    assert len(runtime.harness.messages.items) == 1
    if same_request:
        assert any(frame.get("type") == "orchestration_turn" for frame in frames)
    else:
        assert any(frame.get("error") for frame in frames)
        assert not any(frame.get("message_persisted") for frame in frames)


def test_save_failure_never_starts_the_planner(empty_history_runtime):
    runtime = empty_history_runtime
    runtime.harness.messages.fail_writes = True
    response = runtime.client.post(PLAN_PATH, json=body(), buffered=True)
    frames = sse_frames(response)
    assert any(frame.get("error") for frame in frames)
    assert not any(frame.get("message_persisted") for frame in frames)
    assert runtime.harness.model_calls == []
    assert questions(runtime) == []


def test_real_history_endpoint_restores_the_question_without_private_claims(
    empty_history_runtime, modules, monkeypatch,
):
    runtime = empty_history_runtime
    history = importlib.import_module("route_backend_conversations")
    for name, value in (
        ("cosmos_conversations_container", runtime.harness.conversations),
        ("cosmos_messages_container", runtime.harness.messages),
        ("get_settings", lambda: dict(runtime.harness.settings)),
        ("get_user_settings", lambda *args, **kwargs: {"settings": {}}),
    ):
        monkeypatch.setattr(history, name, value)
    blueprint = Blueprint("planning_history_probe", __name__)
    blueprint.before_request(modules.auth.user_required_blueprint())
    history.register_route_backend_conversations(blueprint)
    runtime.app.register_blueprint(blueprint)
    runtime.harness.replies.append(json.dumps({"kind": "plan", "steps": []}))
    runtime.client.post(PLAN_PATH, json=body(), buffered=True)
    response = runtime.client.get("/api/get_messages", query_string={"conversation_id": CONVERSATION})
    assert response.status_code == 200, response.get_data(as_text=True)
    messages = response.get_json()["messages"]
    assert len(messages) == 1
    assert messages[0]["content"] == MESSAGE
    assert messages[0]["metadata"]["orchestration"]["planning_status"] == "failed"
    assert planning.PLANNING_METADATA not in messages[0]["metadata"]
    assert "claim_id" not in response.get_data(as_text=True)
    assert "input_fingerprint" not in response.get_data(as_text=True)


def test_source_scope_failure_after_admission_keeps_the_question(empty_history_runtime, modules, monkeypatch):
    runtime = empty_history_runtime

    @contextmanager
    def unavailable(*args, **kwargs):
        raise RuntimeError("PRIVATE_SOURCE_DIAGNOSTIC")
        yield

    monkeypatch.setattr(modules.route, "public_chat_execution_scope", unavailable)
    response = runtime.client.post(PLAN_PATH, json=body(), buffered=True)
    frames = sse_frames(response)
    current = status(runtime)
    assert any(frame.get("message_persisted") for frame in frames)
    assert any(frame.get("error") for frame in frames)
    assert current["status"] == "failed"
    assert len(questions(runtime)) == 1
    assert runtime.harness.model_calls == []
    assert "PRIVATE_SOURCE_DIAGNOSTIC" not in response.get_data(as_text=True)


def test_explicit_retry_uses_saved_inputs_and_one_question(empty_history_runtime):
    runtime = empty_history_runtime
    runtime.harness.replies.append(json.dumps({"kind": "plan", "steps": []}))
    failed = runtime.client.post(PLAN_PATH, json=body(), buffered=True)
    failed_frames = sse_frames(failed)
    assert any(frame.get("error") for frame in failed_frames)
    saved = status(runtime, include_request=True)
    request = {
        **saved["request"], "planning_submission_id": "submission-retry",
        "requires_fresh_review": True, "approval_mode": "manual",
    }
    runtime.harness.replies.append(json.dumps(plan_doc()))
    retried = runtime.client.post(PLAN_PATH, json=request, buffered=True)
    frames = sse_frames(retried)
    plan = next(frame["plan"] for frame in frames if frame.get("type") == "orchestration_plan")
    current = status(runtime)
    assert len(questions(runtime)) == 1
    assert plan["requires_fresh_review"] is True
    assert plan["approval"]["mode"] == "manual"
    assert current["status"] == "awaiting_review"


def test_typed_contract_failure_survives_reload_and_clears_on_explicit_retry(empty_history_runtime):
    runtime = empty_history_runtime
    invalid = plan_doc()
    invalid["steps"][0]["outputs"] = []
    runtime.harness.replies.extend([json.dumps(invalid), json.dumps(invalid)])
    response = runtime.client.post(PLAN_PATH, json=body(), buffered=True)
    failure = next(frame for frame in sse_frames(response) if frame.get("error"))
    expected = {
        "error_stage": "plan_normalization",
        "error_rule": "outputs_list_required",
        "error_attempt": 2,
    }
    assert failure["code"] == "plan_outputs_invalid"
    assert all(failure.get(key) == value for key, value in expected.items())
    calls = len(runtime.harness.model_calls)
    saved = status(runtime, include_request=True)
    reloaded = status(runtime)
    assert calls == len(runtime.harness.model_calls) == 2
    assert saved["status"] == reloaded["status"] == "failed"
    assert saved["error_code"] == reloaded["error_code"] == failure["code"]
    assert all(saved.get(key) == reloaded.get(key) == value for key, value in expected.items())
    assert not runtime.harness.runs.items and not runtime.harness.assistant_messages()
    runtime.harness.replies.append(json.dumps(plan_doc()))
    retried = runtime.client.post(PLAN_PATH, json={
        **saved["request"], "planning_submission_id": "contract-retry",
        "requires_fresh_review": True, "approval_mode": "manual",
    }, buffered=True)
    assert any(frame.get("type") == "orchestration_plan" for frame in sse_frames(retried))
    current = status(runtime)
    assert current["status"] == "awaiting_review" and len(questions(runtime)) == 1
    assert not any(key in current for key in ("error", "error_code", *expected))


def test_stop_before_acknowledgement_is_durable(empty_history_runtime):
    runtime = empty_history_runtime
    stopped = runtime.client.post(
        f"{STATUS_PATH}/cancel",
        json={"conversation_id": CONVERSATION, "submission_id": "submission-1"},
    )
    response = runtime.client.post(PLAN_PATH, json=body(approval_mode="auto"), buffered=True)
    frames = sse_frames(response)
    current = status(runtime)
    assert stopped.status_code == 200
    assert any(frame.get("message_persisted") for frame in frames)
    assert current["status"] == "cancelled"
    assert len(questions(runtime)) == 1
    assert runtime.harness.model_calls == []
    assert runtime.harness.assistant_messages() == []


def test_early_stop_is_not_erased_by_an_unrelated_conversation_write(empty_history_runtime):
    runtime = empty_history_runtime
    before_stop = runtime.harness.conversations.read_item(CONVERSATION, CONVERSATION)
    stopped = runtime.client.post(
        f"{STATUS_PATH}/cancel",
        json={"conversation_id": CONVERSATION, "submission_id": "submission-1"},
    )
    runtime.harness.conversations.upsert_item({**before_stop, "title": "Concurrent title update"})
    response = runtime.client.post(PLAN_PATH, json=body(approval_mode="auto"), buffered=True)
    frames = sse_frames(response)
    current = status(runtime)
    assert stopped.status_code == 200
    assert any(frame.get("message_persisted") for frame in frames)
    assert current["status"] == "cancelled"
    assert runtime.harness.model_calls == []


def test_stop_fences_a_late_auto_plan(empty_history_runtime, modules, monkeypatch):
    runtime = empty_history_runtime
    runtime.harness.replies.append(json.dumps(plan_doc()))
    entered, release, _settled = hold_planner(runtime, modules, monkeypatch)
    response = runtime.client.post(PLAN_PATH, json=body(approval_mode="auto"), buffered=False)
    try:
        planner_entered = entered.wait(timeout=10)
        assert planner_entered
        stopped = runtime.client.post(
            f"{STATUS_PATH}/cancel",
            json={"conversation_id": CONVERSATION, "submission_id": "submission-1"},
        )
        assert stopped.status_code == 200
    finally:
        release.set()
    frames = sse_frames(response)
    current = status(runtime)
    saved_runs = modules.runs.list_conversation_runs(CONVERSATION, "owner", strict=True)
    assert any(frame.get("error") for frame in frames)
    assert current["status"] == "cancelled"
    assert saved_runs == []
    assert {item["record_type"] for item in runtime.harness.runs.items.values()} == {"planning_cancellation"}
    assert runtime.harness.assistant_messages() == []


def test_turn_reads_and_stop_require_conversation_ownership(empty_history_runtime):
    runtime = empty_history_runtime
    runtime.harness.replies.append(json.dumps({"kind": "plan", "steps": []}))
    runtime.client.post(PLAN_PATH, json=body(), buffered=True)
    login(runtime, user_id="another-user")
    read = runtime.client.get(STATUS_PATH, query_string={"conversation_id": CONVERSATION})
    stop = runtime.client.post(
        f"{STATUS_PATH}/cancel",
        json={"conversation_id": CONVERSATION, "submission_id": "submission-1"},
    )
    assert read.status_code == stop.status_code == 404


@pytest.mark.parametrize("authenticated", [False, True])
def test_turn_routes_keep_login_and_user_role_guards(empty_history_runtime, authenticated):
    runtime = empty_history_runtime
    if authenticated:
        login(runtime, roles=())
    else:
        runtime.client.delete_cookie(runtime.app.config["SESSION_COOKIE_NAME"])
    read = runtime.client.get(STATUS_PATH, query_string={"conversation_id": CONVERSATION})
    stop = runtime.client.post(
        f"{STATUS_PATH}/cancel",
        json={"conversation_id": CONVERSATION, "submission_id": "submission-1"},
    )
    assert read.status_code == stop.status_code == (403 if authenticated else 401)


def test_auto_admission_failure_keeps_an_explicit_manual_retry(empty_history_runtime, modules, monkeypatch):
    runtime = empty_history_runtime
    prepare = modules.route._prepare_execution_stream
    monkeypatch.setattr(
        modules.route, "_prepare_execution_stream",
        lambda *args, **kwargs: (modules.route.jsonify({"error": "Execution is temporarily unavailable."}), 503),
    )
    runtime.harness.replies.append(json.dumps(plan_doc()))
    runtime.client.post(PLAN_PATH, json=body(approval_mode="auto"), buffered=True)
    failed = status(runtime, include_request=True)
    assert failed["status"] == "failed"
    assert failed["error_code"] == "auto_admission_failed"
    assert failed["run_started"] is False
    assert runtime.harness.assistant_messages() == []
    monkeypatch.setattr(modules.route, "_prepare_execution_stream", prepare)
    runtime.harness.replies.append(json.dumps(plan_doc()))
    response = runtime.client.post(PLAN_PATH, json={
        **failed["request"], "approval_mode": "manual", "requires_fresh_review": True,
        "planning_submission_id": "explicit-manual-retry",
    }, buffered=True)
    frames = sse_frames(response)
    current = status(runtime)
    assert any(frame.get("type") == "orchestration_plan" for frame in frames)
    assert current["status"] == "awaiting_review"
    assert len(questions(runtime)) == 1
    assert runtime.harness.assistant_messages() == []


@pytest.mark.parametrize("new_submission", [False, True])
def test_changed_inputs_cannot_reuse_the_saved_question(empty_history_runtime, new_submission):
    runtime = empty_history_runtime
    runtime.harness.replies.append(json.dumps({"kind": "plan", "steps": []}))
    runtime.client.post(PLAN_PATH, json=body(), buffered=True)
    count = len(runtime.harness.model_calls)
    changed = body(selected_document_ids=["different-source"])
    if new_submission:
        changed.update(planning_submission_id="changed-selection", requires_fresh_review=True)
    response = runtime.client.post(PLAN_PATH, json=changed, buffered=True)
    frames = sse_frames(response)
    current = status(runtime, include_request=True)
    assert any(frame.get("error") for frame in frames)
    assert len(runtime.harness.model_calls) == count
    assert current["request"]["selected_document_ids"] == []
    assert len(questions(runtime)) == 1


def test_sdk_claim_fencing_stale_worker_and_public_history(monkeypatch):
    messages = AtomicMemoryContainer("conversation_id")
    prepared = planning.new_planning_attempt(body(), TURN, "submission-1")
    question = {
        "id": planning.planning_question_id(CONVERSATION, TURN),
        "conversation_id": CONVERSATION, "role": "user", "content": MESSAGE,
        "timestamp": prepared["updated_at"],
        "metadata": {"orchestration_turn_id": TURN, planning.PLANNING_METADATA: prepared},
    }
    messages.create_item(question)
    claimed, owned = planning.claim_planning_attempt(messages, CONVERSATION, question["id"], prepared)
    assert owned and claimed["claim_id"] == prepared["claim_id"]
    duplicate = planning.new_planning_attempt(body(), TURN, "submission-1")
    _state, duplicate_owned = planning.claim_planning_attempt(messages, CONVERSATION, question["id"], duplicate)
    assert not duplicate_owned
    public = planning.public_planning_message(question)
    assert planning.PLANNING_METADATA not in public["metadata"]
    assert public["metadata"]["orchestration"]["planning_status"] == "planning"
    now = planning._now()
    monkeypatch.setattr(planning, "_now", lambda: now + timedelta(seconds=planning.PLANNING_LEASE_SECONDS + 1))
    _question, stale = planning.read_planning_attempt(messages, CONVERSATION, question["id"], TURN)
    assert type(_question) is dict
    assert stale["status"] == "interrupted"
    with pytest.raises(planning.PlanningStateError):
        planning.require_planning_claim(messages, CONVERSATION, question["id"], TURN, claimed["claim_id"])
    changed = deepcopy(body())
    changed["selected_document_ids"] = ["different-source"]
    replacement = planning.new_planning_attempt(changed, TURN, "submission-1")
    with pytest.raises(planning.PlanningStateError):
        planning.claim_planning_attempt(messages, CONVERSATION, question["id"], replacement)


def test_a_racing_stop_cannot_be_overwritten_by_a_heartbeat():
    messages = AtomicMemoryContainer("conversation_id")
    prepared = planning.new_planning_attempt(body(), TURN, "submission-1")
    message_id = planning.planning_question_id(CONVERSATION, TURN)
    messages.create_item({
        "id": message_id, "conversation_id": CONVERSATION, "role": "user", "content": MESSAGE,
        "metadata": {"orchestration_turn_id": TURN, planning.PLANNING_METADATA: prepared},
    })
    messages.before_replace = lambda: planning.cancel_planning_attempt(
        messages, CONVERSATION, message_id, TURN, submission_id=prepared["submission_id"],
    )
    with pytest.raises(planning.PlanningStateError):
        planning.heartbeat_planning_attempt(messages, CONVERSATION, message_id, TURN, prepared["claim_id"])
    question, current = planning.read_planning_attempt(messages, CONVERSATION, message_id, TURN)
    assert current["status"] == "cancelled"
    assert question["_etag"]


def test_a_late_stop_cannot_cancel_a_newer_planning_submission():
    messages = AtomicMemoryContainer("conversation_id")
    prepared = planning.new_planning_attempt(body(), TURN, "submission-1")
    message_id = planning.planning_question_id(CONVERSATION, TURN)
    messages.create_item({
        "id": message_id, "conversation_id": CONVERSATION, "role": "user", "content": MESSAGE,
        "metadata": {"orchestration_turn_id": TURN, planning.PLANNING_METADATA: prepared},
    })
    planning.update_planning_attempt(
        messages, CONVERSATION, message_id, TURN, {"status": "awaiting_review"},
        claim_id=prepared["claim_id"],
    )
    replacement = planning.new_planning_attempt(
        body(revision=1, planning_submission_id="submission-2"), TURN, "submission-2", revision=1,
    )
    messages.before_replace = lambda: planning.claim_planning_attempt(
        messages, CONVERSATION, message_id, replacement,
    )
    with pytest.raises(planning.PlanningStateError):
        planning.cancel_planning_attempt(
            messages, CONVERSATION, message_id, TURN,
            submission_id=prepared["submission_id"], claim_id=prepared["claim_id"],
        )
    _question, current = planning.read_planning_attempt(messages, CONVERSATION, message_id, TURN)
    assert current["submission_id"] == "submission-2"
    assert current["status"] == "planning"
    planning.require_planning_claim(messages, CONVERSATION, message_id, TURN, replacement["claim_id"])
