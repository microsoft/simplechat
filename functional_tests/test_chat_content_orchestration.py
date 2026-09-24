# test_chat_content_orchestration.py
"""
Functional tests for chat content checks through real orchestration routes.
Version: 0.261.139
Implemented in: 0.261.127
Single orchestration contract updated in: 0.261.139

Reuse the real planning, execution lease, message publication, and Flask/SSE
fixture with synthetic completions and an injected deterministic scanner.
"""

import copy
import json

import pytest

from content_screening.policies import STARTER_RULE_TEMPLATES, default_policy
import functions_chat_content_checks as checks
import functions_chat_content_review as review
from test_orchestration_harness_routes import modules, real_http_harness  # noqa: F401
from test_support.orchestration_harness_execution import compose_step, input_binding
from test_support.versioning import assert_app_version_at_least


IMPLEMENTED_IN = "0.261.127"
SINGLE_CONTRACT_UPDATED_IN = "0.261.139"


def frames(response):
    return [
        json.loads(line[5:].strip())
        for line in response.get_data(as_text=True).splitlines()
        if line.startswith("data:") and line[5:].strip() != "[DONE]"
    ]


@pytest.fixture
def content_runtime(real_http_harness, modules, monkeypatch):
    runtime = real_http_harness
    harness = runtime.harness
    harness.settings.update({
        "enable_content_screening": True,
        "enable_content_screening_chat_input": False,
        "enable_content_screening_chat_output": True,
    })
    policy = default_policy()
    policy["enabled"] = True
    policy["rules"] = [copy.deepcopy(STARTER_RULE_TEMPLATES["email"])]
    # A test sets policy_ref[0] to None to make the real checker fail to complete.
    policy_ref = [policy]
    audit_calls = []
    blocked_calls = []

    def evaluate(text, checkpoint, *, user_id, settings=None, required_scanners=None):
        result = checks.evaluate_chat_content(
            text, checkpoint, settings if settings is not None else harness.settings,
            baseline_loader=lambda: policy_ref[0],
            required_scanners=required_scanners,
        )
        if result.metadata:
            result.metadata["actor_user_id"] = user_id
        return result

    monkeypatch.setattr(checks, "check_chat_content", evaluate)
    monkeypatch.setattr(modules.route, "check_chat_content", evaluate, raising=False)
    monkeypatch.setattr(modules.route, "record_chat_content_incident", lambda *a, **k: audit_calls.append((a, k)), raising=False)
    monkeypatch.setattr(modules.route, "record_blocked_chat_attempt", lambda *a, **k: blocked_calls.append((a, k)), raising=False)
    monkeypatch.setattr(runtime.harness.execution, "check_chat_content", evaluate, raising=False)
    monkeypatch.setattr(runtime.harness.execution, "record_chat_content_incident", lambda *a, **k: audit_calls.append((a, k)), raising=False)
    monkeypatch.setattr(runtime.harness.execution, "record_blocked_chat_attempt", lambda *a, **k: blocked_calls.append((a, k)), raising=False)
    monkeypatch.setattr(runtime.harness.bootstrap, "check_chat_content", evaluate, raising=False)
    monkeypatch.setattr(runtime.harness.bootstrap, "record_chat_content_incident", lambda *a, **k: audit_calls.append((a, k)), raising=False)
    monkeypatch.setattr(runtime.harness.bootstrap, "record_blocked_chat_attempt", lambda *a, **k: blocked_calls.append((a, k)), raising=False)
    # Execution imports the incident recorder from the review module when it publishes.
    monkeypatch.setattr(review, "record_chat_content_incident", lambda *a, **k: audit_calls.append((a, k)))
    yield {"runtime": runtime, "harness": harness, "policy_ref": policy_ref, "audit": audit_calls, "blocked": blocked_calls}


def test_version_includes_single_contract_update():
    assert_app_version_at_least(IMPLEMENTED_IN)
    assert_app_version_at_least(SINGLE_CONTRACT_UPDATED_IN)


def _run_compose(runtime, reply):
    harness = runtime.harness
    record = harness.create([compose_step()], replies=[reply], final_response=input_binding("prepare"))
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "conversation_id": "conversation-1", "run_id": record["id"],
    }, buffered=True)
    return record, response, frames(response)


def test_flagged_output_is_published_as_safety_with_the_reserved_run_identity(content_runtime, monkeypatch):
    runtime = content_runtime["runtime"]
    harness = content_runtime["harness"]
    record, response, events = _run_compose(runtime, "alice@example.test")
    done = next(event for event in events if event.get("done"))
    saved = harness.messages.read_item(done["message_id"], "conversation-1")
    assert response.status_code == 200
    assert done["blocked"] is True
    assert done["role"] == "safety"
    assert "alice@example.test" not in done["full_content"]
    assert checks.CHECK_METADATA not in json.dumps(done)
    assert saved["role"] == "safety"
    assert saved["metadata"]["orchestration"]["run_id"] == record["id"]
    assert saved["metadata"][checks.CHECK_METADATA]["status"] == "findings"
    assert len(content_runtime["audit"]) == 1


def test_checker_failure_is_private_and_keeps_the_reply_usable(content_runtime):
    runtime = content_runtime["runtime"]
    harness = content_runtime["harness"]
    # The saved policy cannot be read, so the required check does not complete.
    content_runtime["policy_ref"][0] = None
    _, response, events = _run_compose(runtime, "alice@example.test")
    done = next(event for event in events if event.get("done"))
    saved = harness.messages.read_item(done["message_id"], "conversation-1")
    assert response.status_code == 200
    assert done["blocked"] is False
    assert done["full_content"] == "alice@example.test"
    assert "not_checked" not in json.dumps(done)
    assert saved["metadata"][checks.CHECK_METADATA]["status"] == "not_checked"
    assert saved["metadata"][checks.CHECK_METADATA]["decision"] == "allow_unchecked"


def test_input_finding_stops_the_planning_model(content_runtime):
    runtime = content_runtime["runtime"]
    harness = content_runtime["harness"]
    harness.settings["enable_content_screening_chat_input"] = True
    response = runtime.client.post("/api/v2/orchestration/plan", json={
        "conversation_id": "conversation-1", "turn_id": "turn-1",
        "message": "Please process alice@example.test", "approval_mode": "manual",
    }, buffered=True)
    events = frames(response)
    assert response.status_code == 200
    assert any(event.get("error") for event in events)
    assert harness.model_calls == []
