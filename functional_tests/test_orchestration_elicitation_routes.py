# test_orchestration_elicitation_routes.py
"""
Route-level clarification regressions for the single orchestration contract.
Version: 0.261.139
Implemented in: 0.261.139
Single orchestration contract updated in: 0.261.139

Ports still-relevant clarification route behavior from the removed legacy-plan tests
onto the Gather / Reason / Render plan and run routes.
"""

import json

from test_orchestration_harness_routes import modules, real_http_harness  # noqa: F401
from test_support.orchestration_harness_execution import compose_step, input_binding


def sse_frames(response):
    return [
        json.loads(frame.partition("data:")[2].strip())
        for frame in response.get_data(as_text=True).split("\n\n")
        if frame.startswith("data:")
    ]


def event_document(response, event_type):
    frames = sse_frames(response)
    match = next((item for item in frames if item.get("type") == event_type), None)
    assert match is not None, frames
    return match["elicitation" if event_type == "orchestration_elicitation" else "plan"]


def style_question(message="Choose a response style."):
    return {
        "kind": "elicitation", "message": message,
        "requested_schema": {
            "type": "object",
            "properties": {"style": {"type": "string", "enum": ["brief", "detailed"]}},
            "required": ["style"],
        },
    }


def plan_doc():
    return {"kind": "plan", "steps": [compose_step()], "final_response": input_binding("prepare")}


def resolution(message="Review my sources."):
    return {"relationship": "new_topic", "resolved_message": message, "message_ids": [], "requires_retrieval": False, "clarification": ""}


def begin(runtime, question=None, *, turn_id="turn-route", message="Review my sources."):
    runtime.harness.replies.extend([json.dumps(resolution(message)), json.dumps(question or style_question())])
    response = runtime.client.post("/api/v2/orchestration/plan", json={
        "conversation_id": "conversation-1", "turn_id": turn_id,
        "message": message, "approval_mode": "manual",
    }, buffered=True)
    assert response.status_code == 200, response.get_data(as_text=True)
    return event_document(response, "orchestration_elicitation")


def reply_payload(question, *, turn_id="turn-route", content=None, context=None, submission="answer-1"):
    return {
        "conversation_id": "conversation-1", "turn_id": turn_id,
        "elicitation_id": question["elicitation_id"],
        "elicitation_revision": question["revision"],
        "elicitation_submission_id": submission,
        "elicitation_response": {"action": "accept", "content": content or {"style": "brief"}},
        "elicitation_context": context or {},
        "message": "This tampered message must not replace the original.",
    }


def run_plan(runtime, plan, reply="Completed answer."):
    runtime.harness.replies.append(reply)
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "conversation_id": "conversation-1", "run_id": plan["run_id"],
    }, buffered=True)
    frames = sse_frames(response)
    assert response.status_code == 200, frames
    assert frames[-1]["status"] == "completed", frames
    return frames


def test_split_and_combined_answer_prompts_reach_execution_once(real_http_harness):
    runtime = real_http_harness
    for combined in (False, True):
        turn_id = f"route-prompt-{combined}"
        question = begin(runtime, turn_id=turn_id)
        answer_text = "Use British spelling."
        prompt_text = "Include a separate accessibility risk section."
        field_context = {
            "text": f"{prompt_text}\n\n{answer_text}" if combined else answer_text,
            "prompt_info": {"content": prompt_text, "user_text": answer_text},
        }
        runtime.harness.replies.extend([json.dumps(resolution()), json.dumps(plan_doc())])
        response = runtime.client.post("/api/v2/orchestration/plan", json=reply_payload(
            question, turn_id=turn_id, context={"style": field_context}, submission=f"sub-{combined}",
        ), buffered=True)
        plan = event_document(response, "orchestration_plan")
        run_plan(runtime, plan)
        messages = json.dumps(runtime.harness.model_calls[-1]["messages"])
        assert messages.count(answer_text) == 1
        assert messages.count(prompt_text) == 1


def test_answers_accumulate_across_questions_and_retries(real_http_harness):
    runtime = real_http_harness
    first = begin(runtime, turn_id="route-accumulate")
    runtime.harness.replies.extend([json.dumps(resolution()), json.dumps(style_question("What tone should I use?"))])
    first_payload = reply_payload(
        first, turn_id="route-accumulate", context={"style": {"text": "First clarification wording."}},
    )
    second = event_document(
        runtime.client.post("/api/v2/orchestration/plan", json=first_payload, buffered=True),
        "orchestration_elicitation",
    )
    replay = event_document(
        runtime.client.post("/api/v2/orchestration/plan", json=first_payload, buffered=True),
        "orchestration_elicitation",
    )
    assert replay["elicitation_id"] == second["elicitation_id"]
    runtime.harness.replies.extend([json.dumps(resolution()), json.dumps(plan_doc())])
    second_payload = reply_payload(
        second, turn_id="route-accumulate", submission="answer-2",
        context={"style": {"text": "Second clarification wording."}},
    )
    plan = event_document(
        runtime.client.post("/api/v2/orchestration/plan", json=second_payload, buffered=True),
        "orchestration_plan",
    )
    record = runtime.harness.runs.read_item(plan["run_id"], "conversation-1")
    assert len(record["answered_questions"]) == 2
    encoded_record = json.dumps(record)
    assert "First clarification wording." in encoded_record
    assert "Second clarification wording." in encoded_record
    stale = dict(first_payload)
    stale["elicitation_submission_id"] = "late-answer"
    assert runtime.client.post("/api/v2/orchestration/plan", json=stale).status_code == 409


def test_identity_binding_and_conditional_claims(real_http_harness):
    runtime = real_http_harness
    question = begin(runtime, turn_id="route-identity")
    valid = reply_payload(question, turn_id="route-identity")
    for overrides in (
        {"elicitation_id": "another-question"}, {"elicitation_revision": 20},
        {"turn_id": "another-turn"}, {"conversation_id": "missing-conversation"},
    ):
        payload = {**valid, **overrides, "elicitation_submission_id": f"bad-{len(str(overrides))}"}
        assert runtime.client.post("/api/v2/orchestration/plan", json=payload).status_code == 409
    runtime.harness.replies.extend([json.dumps(resolution()), json.dumps(plan_doc())])
    accepted = event_document(
        runtime.client.post("/api/v2/orchestration/plan", json=valid, buffered=True),
        "orchestration_plan",
    )
    duplicate = event_document(
        runtime.client.post("/api/v2/orchestration/plan", json=valid, buffered=True),
        "orchestration_plan",
    )
    assert duplicate["run_id"] == accepted["run_id"]
    changed = reply_payload(question, turn_id="route-identity", content={"style": "detailed"}, submission="answer-1")
    assert runtime.client.post("/api/v2/orchestration/plan", json=changed).status_code == 409


def test_pending_records_never_become_runs(real_http_harness):
    runtime = real_http_harness
    question = begin(runtime, turn_id="route-pending")
    pending = runtime.harness.run_store.get_pending_elicitation("owner", "conversation-1", "route-pending")
    pending_id = pending["id"]
    assert runtime.harness.run_store.get_orchestration_run(pending_id, "owner", "conversation-1") is None
    assert runtime.harness.run_store.update_orchestration_run(
        pending_id, "owner", {"status": "running"}, "conversation-1",
    ) is None
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "conversation_id": "conversation-1", "run_id": pending_id,
    })
    assert response.status_code == 404
    assert runtime.harness.run_store.list_conversation_runs("conversation-1", "owner") == []
    assert question["elicitation_id"] == pending["question"]["elicitation_id"]



def make_conversation_shared(runtime):
    conversation = runtime.harness.conversations.read_item("conversation-1", "conversation-1")
    conversation["collaboration_conversation_id"] = "now-shared"
    runtime.harness.conversations.upsert_item(conversation)


def assert_no_new_runs(runtime, before_ids):
    after_ids = {key[1] for key in runtime.harness.runs.items if key[0] == "conversation-1"}
    assert after_ids == before_ids


def test_pending_clarification_answer_rechecks_memory_audience(real_http_harness):
    runtime = real_http_harness
    question = begin(runtime, turn_id="route-memory-pending")
    pending = runtime.harness.run_store.get_pending_elicitation(
        "owner", "conversation-1", "route-memory-pending",
    )
    assert pending["turn_context"]["memory_audience"] == {
        "kind": "personal", "owner_id": "owner", "collaboration_id": "",
    }
    before_calls = len(runtime.harness.model_calls)
    before_runs = {key[1] for key in runtime.harness.runs.items if key[0] == "conversation-1"}
    make_conversation_shared(runtime)
    response = runtime.client.post(
        "/api/v2/orchestration/plan",
        json=reply_payload(question, turn_id="route-memory-pending", submission="memory-answer"),
        buffered=True,
    )
    frames = sse_frames(response) if response.status_code == 200 else []
    assert response.status_code == 409 or any(item.get("error") for item in frames), frames
    assert "orchestration_plan" not in {item.get("type") for item in frames}
    # Request resolution reads only the conversation and may run first; the audience is
    # rechecked before saved memory is read, so the planner itself is never called.
    planner_prompt = runtime.harness.planner.PLANNER_SYSTEM_PROMPT[:60]
    assert not any(
        planner_prompt in json.dumps(call.get("messages")) for call in runtime.harness.model_calls[before_calls:]
    )
    assert_no_new_runs(runtime, before_runs)


def test_completed_submission_replay_rechecks_memory_audience(real_http_harness):
    runtime = real_http_harness
    question = begin(runtime, turn_id="route-memory-replay")
    payload = reply_payload(question, turn_id="route-memory-replay", submission="memory-replay")
    runtime.harness.replies.extend([json.dumps(resolution()), json.dumps(plan_doc())])
    first = runtime.client.post("/api/v2/orchestration/plan", json=payload, buffered=True)
    plan = event_document(first, "orchestration_plan")
    calls_after_first = len(runtime.harness.model_calls)
    unchanged_replay = runtime.client.post("/api/v2/orchestration/plan", json=payload, buffered=True)
    replay_plan = event_document(unchanged_replay, "orchestration_plan")
    assert replay_plan["run_id"] == plan["run_id"]
    assert len(runtime.harness.model_calls) == calls_after_first
    make_conversation_shared(runtime)
    changed_replay = runtime.client.post("/api/v2/orchestration/plan", json=payload, buffered=True)
    frames = sse_frames(changed_replay) if changed_replay.status_code == 200 else []
    assert changed_replay.status_code == 409 or any(item.get("error") for item in frames), frames
    assert "orchestration_plan" not in {item.get("type") for item in frames}
    assert len(runtime.harness.model_calls) == calls_after_first
