# test_orchestration_harness_chat_checks.py
"""Harness replies use chat content checks; Auto routing never yields unenforced bindings.

Version: 0.261.131
Implemented in: 0.261.131

The initialized headless runner, lease, publication guard, retained results and
renderer are real. Only the chat checkpoint baseline is supplied in memory, with
the shared evaluator and a deterministic starter rule; no scanner is contacted.
"""

import importlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from azure.core import MatchConditions

from functions_orchestration_execution import HarnessExecutionError
from test_orchestration_harness_execution import harness, initialized_application  # noqa: F401
from test_support.orchestration_harness_execution import (
    compose_step, decoded_frames, input_binding, render_step,
)


FINDING = "alice@example.test"


@pytest.fixture
def chat_checks(harness, monkeypatch):
    checks = importlib.import_module("functions_chat_content_checks")
    review = importlib.import_module("functions_chat_content_review")
    policies = importlib.import_module("content_screening.policies")
    policy = policies.default_policy()
    policy["enabled"] = True
    policy["rules"] = [deepcopy(policies.STARTER_RULE_TEMPLATES["email"])]
    harness.settings.update({
        "enable_content_screening": True,
        "enable_content_screening_chat_input": False,
        "enable_content_screening_chat_output": True,
    })
    state = SimpleNamespace(checks=checks, calls=[], incidents=[])

    def evaluate(text, checkpoint, *, user_id, settings=None, required_scanners=None):
        state.calls.append((checkpoint, text, deepcopy(settings)))
        result = checks.evaluate_chat_content(
            text, checkpoint, settings if settings is not None else harness.settings,
            baseline_loader=lambda: policy, required_scanners=required_scanners,
        )
        if result.metadata:
            result.metadata["actor_user_id"] = user_id
        return result

    monkeypatch.setattr(checks, "check_chat_content", evaluate)
    monkeypatch.setattr(
        review, "record_chat_content_incident",
        lambda message, user_id: state.incidents.append((deepcopy(message), user_id)),
    )
    return state


def _message_id():
    fingerprint = importlib.import_module("functions_orchestration_checkpoints").fingerprint
    return f"assistant_orchestration_{fingerprint('run-1')[:40]}"


def test_blocked_harness_reply_publishes_only_the_safety_notice(harness, chat_checks):
    checks = chat_checks.checks
    harness.create(
        [compose_step(), render_step("report", "md")],
        replies=[f"Send the completed report to {FINDING}."],
        final_response=input_binding("prepare"),
    )
    execution = harness.prepare()
    frames = execution.execute()
    done = decoded_frames(frames)[-1]
    saved = harness.read()
    message = harness.messages.read_item(_message_id(), "conversation-1")
    public = json.dumps(decoded_frames(frames))

    assert [call[0] for call in chat_checks.calls] == ["chat_output"]
    assert FINDING in chat_checks.calls[0][1]
    assert done["blocked"] is True and done["role"] == "safety" and done["replace_content"] is True
    assert done["full_content"] == checks.REMOVED_REPLY_MESSAGE
    assert done["outputs"] == [] and not done.get("generated_artifacts")
    assert FINDING not in public and checks.CHECK_METADATA not in public
    assert message["role"] == "safety" and message["content"] == checks.REMOVED_REPLY_MESSAGE
    assert message["metadata"]["orchestration"]["run_id"] == "run-1"
    assert message["metadata"][checks.CHECK_METADATA]["status"] == "findings"
    assert message["metadata"]["content_moderation"]["removed"] is True
    assert message["generated_artifacts"] == [] and message["hybrid_citations"] == []
    assert saved["message"] == checks.REMOVED_REPLY_MESSAGE and FINDING not in json.dumps(saved)
    assert saved["chat_content_checked_output"] is True
    assert saved["chat_content_output_pending"] is False
    assert saved["status"] == "completed" and saved["message_saved"] is True
    assert len(chat_checks.incidents) == 1 and chat_checks.incidents[0][0]["role"] == "safety"
    # The rendered file stays private with the removed reply rather than being deleted.
    assert harness.blobs.file_uploads == 1 and len(harness.model_calls) == 1
    assert saved["execution_lease"] is None and all(client.closed for client in harness.clients)


def test_passing_check_keeps_the_harness_reply_without_private_metadata(harness, chat_checks):
    checks = chat_checks.checks
    harness.create(replies=["The complete retained answer."], final_response=input_binding("prepare"))
    execution = harness.prepare()
    frames = execution.execute()
    done = decoded_frames(frames)[-1]
    saved = harness.read()
    message = harness.messages.read_item(_message_id(), "conversation-1")

    assert done["blocked"] is False and done["role"] == "assistant"
    assert done["full_content"] == message["content"] == "The complete retained answer."
    assert checks.CHECK_METADATA not in json.dumps(decoded_frames(frames))
    assert message["role"] == "assistant"
    assert message["metadata"][checks.CHECK_METADATA]["status"] == "passed"
    assert saved["chat_content_checked_output"] is True and saved["chat_content_output_pending"] is False
    assert len(harness.model_calls) == 1


def test_check_before_display_keeps_run_files_pending_until_publication(harness, chat_checks):
    harness.settings["chat_content_output_mode"] = "check_before_display"
    observed = []

    def reply():
        observed.append(harness.read().get("chat_content_output_pending"))
        return "Prepared content without findings."

    harness.create(
        [compose_step(), render_step("report", "md")],
        replies=[reply], final_response=input_binding("prepare"),
    )
    execution = harness.prepare()
    done = decoded_frames(execution.execute())[-1]
    saved = harness.read()

    assert observed == [True]
    assert done["blocked"] is False and len(done["outputs"]) == 1
    assert saved["chat_content_output_pending"] is False and saved["chat_content_checked_output"] is True


def test_model_free_republication_preserves_an_administrator_retraction(harness, chat_checks):
    checks = chat_checks.checks
    harness.create(replies=["A later retained answer."], final_response=input_binding("prepare"))
    execution = harness.prepare()
    decision = checks.ChatContentDecision(
        "chat_output", "findings", "block", {
            "schema_version": 1, "checkpoint": "chat_output", "origin": "assistant",
            "status": "findings", "complete": True, "decision": "block",
            "attempted_at": "2026-09-23T12:00:00+00:00", "scanners": [],
        }, checks.REMOVED_REPLY_MESSAGE,
    )
    retracted = checks.retract_message_content({
        "id": _message_id(), "conversation_id": "conversation-1", "role": "assistant",
        "content": "An earlier removed reply.", "metadata": {"orchestration": {"run_id": "run-1"}},
    }, decision)
    harness.messages.create_item(retracted)
    frames = execution.execute()
    done = decoded_frames(frames)[-1]
    message = harness.messages.read_item(_message_id(), "conversation-1")

    assert done["blocked"] is True and done["full_content"] == checks.REMOVED_REPLY_MESSAGE
    assert "A later retained answer." not in json.dumps(decoded_frames(frames))
    assert {key: value for key, value in message.items() if not key.startswith("_")} == retracted
    assert harness.read()["message_saved"] is True


def test_dependency_plan_with_auto_bindings_fails_closed_before_model_setup(harness):
    harness.create(replies=["Must not be generated."], final_response=input_binding("prepare"))
    current = harness.read()
    current["plan"]["model_routing"] = "auto"
    harness.runs.replace_item(
        item="run-1", body=current, etag=current["_etag"], match_condition=MatchConditions.IfNotModified,
    )
    record, lease = harness.claim()
    assert record["plan"]["model_routing"] == "auto"
    with pytest.raises(HarnessExecutionError) as failure:
        harness.execution.prepare_harness_execution(record, settings=harness.settings, lease=lease)
    saved = harness.read()

    assert failure.value.code == "model_routing_changed"
    assert saved["status"] == "failed" and saved["failure"]["code"] == "model_routing_changed"
    assert harness.model_calls == [] and harness.clients == [] and harness.blobs.file_uploads == 0
    assert lease.stopped.is_set()


def test_dependency_planning_rejects_auto_routing_before_candidates_or_models(harness, monkeypatch):
    catalog = importlib.import_module("functions_model_catalog")
    candidates = []
    monkeypatch.setattr(
        harness.planner, "authorized_routing_candidates",
        lambda *args, **kwargs: candidates.append(args) or [],
    )
    with pytest.raises(catalog.ModelCatalogError) as failure:
        harness.planner.plan_request(
            "Prepare the requested report.", {}, "conversation-1", "owner",
            settings=harness.settings, seeds={"model_routing": "auto"}, contract_version=2,
        )

    assert failure.value.code == "model_routing_unsupported" and failure.value.field == "model_routing"
    assert candidates == [] and harness.model_calls == [] and harness.clients == []
