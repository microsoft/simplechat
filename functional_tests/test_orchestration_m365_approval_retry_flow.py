# test_orchestration_m365_approval_retry_flow.py
#!/usr/bin/env python3
"""
Functional test for the orchestration Microsoft 365 approval and retry flow.
Version: 0.261.302
Implemented in: 0.261.302

A plan step that had to read more of a SharePoint or OneDrive file than a quick read covers
stops for the user's extended-analysis approval. These tests cover the server half of letting
the user decide that approval in the chat and continue at once:

* the step failure carries the pending approval's id, and only an id the application minted;
* an action step that stopped for Microsoft 365 retries without the "may already have acted
  outside this chat" confirmation, enforced by the real retry route, while agent steps and
  other action failures still need it;
* once a retry exists, the attempt it replaced stays saved but is left out of what the model
  reads on later turns, in both orchestration and normal chat, and out of exports.
"""

import ast
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask

TESTS = Path(__file__).resolve().parent
APP = TESTS.parent / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(TESTS))

from test_support.offline_bootstrap import offline_app_imports  # noqa: E402 - the test path is set above
from test_support.orchestration_recovery import RecoveryFixture, frames  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

import functions_orchestration_attempts as attempts  # noqa: E402 - standard library only

APPROVAL_ID = "m365-" + "0123456789abcdef" * 4


def test_application_version():
    assert_app_version_at_least("0.261.302")


# --------------------------------------------------------------------------------------
# The failure carries the pending approval
# --------------------------------------------------------------------------------------

def test_approval_stops_carry_only_minted_approval_ids():
    with offline_app_imports():
        import functions_orchestration_m365 as orchestration_m365
        import functions_orchestration_schema as schema

        failure = schema.build_failure("m365_approval_required", step_id="search", approval_id=APPROVAL_ID)
        assert failure["approval_id"] == APPROVAL_ID
        assert schema.safe_failure(failure) == failure, "A saved failure must keep its approval through a re-read."

        for invalid in (
            None, "", 42, "m365-" + "A" * 64, "m365-" + "a" * 63, "m365-" + "a" * 65,
            "x365-" + "a" * 64, "m365-" + "g" * 64, f"{APPROVAL_ID}\n", "javascript:alert(1)",
        ):
            assert "approval_id" not in schema.build_failure("m365_approval_required", approval_id=invalid), invalid
        for code in ("m365_sign_in_required", "m365_unavailable", "step_failed"):
            assert "approval_id" not in schema.build_failure(code, approval_id=APPROVAL_ID), code

        stop = orchestration_m365.OrchestrationM365Error(
            "m365_approval_required", m365_code="m365_approval_required", sources=("spo",),
            approval_id=APPROVAL_ID,
        )
        wrapped = RuntimeError("An action function could not complete.")
        wrapped.__cause__ = stop
        for error in (stop, wrapped):
            reported = schema.failure_from_exception(error)
            assert reported["code"] == "m365_approval_required"
            assert reported["approval_id"] == APPROVAL_ID
            assert reported["m365_sources"] == ["spo"]


# --------------------------------------------------------------------------------------
# A Microsoft 365 stop retries without external-effect consent, through the real route
# --------------------------------------------------------------------------------------

def _stop_step_b(fixture, run_id, *, capability_id, failure):
    """Record the failed step as the kind of step and stop under test, as the executor saves it."""
    record = fixture.runs.items[(fixture.conversation_id, run_id)]
    step = next(step for step in record["execution_steps"] if step["step_id"] == "b")
    assert step["status"] == "failed" and step["effects_uncertain"] is True
    step.update(capability_id=capability_id, failure=failure)


def test_microsoft_365_action_stop_retries_without_external_effect_consent():
    with RecoveryFixture() as fixture:
        plan = fixture.plan_attempt()
        frames(fixture.run_attempt(plan))
        schema = fixture.modules.schema
        _stop_step_b(
            fixture, plan["run_id"], capability_id="action_invoke",
            failure=schema.build_failure("m365_approval_required", step_id="b", approval_id=APPROVAL_ID),
        )

        recovery = fixture.detail(plan["run_id"])["recovery"]
        assert recovery["eligible"] is True
        assert recovery["requires_confirmation"] is False

        response = fixture.retry(plan["run_id"], confirm_external_effects=False)
        assert response.status_code == 200, response.get_data(as_text=True)
        child = response.get_json()["run"]
        assert child["recovery"]["reused_step_ids"] == ["a"]
        fixture.fail_b = False
        frames(fixture.run_attempt(child["plan"]))
        assert fixture.calls == ["a", "b", "b", "c"], "Only the stopped work runs again."


def test_other_failed_effect_steps_still_require_consent():
    cases = (
        # An agent may load actions that send or change data, so its stop proves nothing.
        ("agent_invoke", "m365_approval_required"),
        # An action step that failed for another reason may already have acted.
        ("action_invoke", "step_timeout"),
    )
    for capability_id, code in cases:
        with RecoveryFixture() as fixture:
            plan = fixture.plan_attempt()
            frames(fixture.run_attempt(plan))
            schema = fixture.modules.schema
            _stop_step_b(
                fixture, plan["run_id"], capability_id=capability_id,
                failure=schema.build_failure(code, step_id="b", approval_id=APPROVAL_ID),
            )
            assert fixture.detail(plan["run_id"])["recovery"]["requires_confirmation"] is True, capability_id

            refused = fixture.retry(plan["run_id"], confirm_external_effects=False)
            assert refused.status_code == 409, (capability_id, refused.get_data(as_text=True))
            assert refused.get_json()["code"] == "confirmation_required"
            assert not [row for row in fixture.runs.items.values() if row.get("retry_of_run_id")]


# --------------------------------------------------------------------------------------
# A replaced attempt leaves model history and exports
# --------------------------------------------------------------------------------------

def _message(message_id, role, content, timestamp, *, run_id=None, retry_of=None, turn_id=None):
    metadata = {}
    if run_id:
        metadata["orchestration"] = {
            "run_id": run_id, "turn_id": turn_id, "retry_of_run_id": retry_of,
            "outcome": "completed" if retry_of else "failed",
        }
    return {
        "id": message_id, "conversation_id": "conversation-1", "role": role, "content": content,
        "timestamp": timestamp, "metadata": metadata,
    }


def _retried_conversation():
    return [
        _message("q1", "user", "What is the EVA Swab Tool?", "2026-10-08T10:00:00+00:00"),
        _message(
            "a1", "assistant", "STOPPED_ATTEMPT_CANARY The request could not be completed.",
            "2026-10-08T10:00:10+00:00", run_id="run-1", turn_id="turn-1",
        ),
        _message(
            "a2", "assistant", "The EVA Swab Tool is a NASA sampling kit.",
            "2026-10-08T10:02:00+00:00", run_id="run-2", retry_of="run-1", turn_id="turn-1",
        ),
        _message("q2", "user", "Who designed it?", "2026-10-08T10:05:00+00:00"),
    ]


def test_replaced_attempts_are_found_from_saved_message_lineage():
    messages = _retried_conversation()
    assert attempts.superseded_orchestration_run_ids(messages) == {"run-1"}
    kept = attempts.exclude_superseded_orchestration_attempts(messages)
    assert [message["id"] for message in kept] == ["q1", "a2", "q2"]

    # A chain of retries keeps only the latest attempt.
    third = _message("a3", "assistant", "Third", "2026-10-08T10:03:00+00:00", run_id="run-3", retry_of="run-2")
    assert [m["id"] for m in attempts.exclude_superseded_orchestration_attempts(messages + [third])] == [
        "q1", "q2", "a3",
    ]
    # Only assistant answers are replaced; malformed lineage and self-references change nothing.
    odd = [
        {"id": "u", "role": "user", "metadata": {"orchestration": {"run_id": "run-1"}}},
        {"id": "s", "role": "assistant", "metadata": {"orchestration": {"run_id": "run-9", "retry_of_run_id": "run-9"}}},
        {"id": "m", "role": "assistant", "metadata": {"orchestration": ["not", "a", "mapping"]}},
        {"id": "n", "role": "assistant", "metadata": None},
    ]
    assert [m["id"] for m in attempts.exclude_superseded_orchestration_attempts(messages + odd)] == [
        "q1", "a2", "q2", "u", "s", "m", "n",
    ]
    assert attempts.exclude_superseded_orchestration_attempts(None) == []


def test_orchestration_history_leaves_out_a_replaced_attempt():
    with offline_app_imports():
        import functions_orchestration_context as context

        snapshot = context.build_conversation_snapshot(_retried_conversation())
        ids = [message["id"] for message in snapshot["messages"]]
        assert ids == ["q1", "a2", "q2"], ids
        assert "STOPPED_ATTEMPT_CANARY" not in str(snapshot)


def test_chat_history_leaves_out_a_replaced_attempt():
    with offline_app_imports():
        import route_backend_chats as chats

        with Flask("superseded-attempt-history").test_request_context("/"):
            segments = chats.build_conversation_history_segments(
                _retried_conversation(), 10, user_message_id="q2", fallback_user_message="Who designed it?",
            )
    history = str(segments["history_messages"])
    assert "STOPPED_ATTEMPT_CANARY" not in history, "A replaced attempt reached the model history."
    assert "NASA sampling kit" in history and "Who designed it?" in history


def _load_function(file_name, function_name, namespace):
    tree = ast.parse((APP / file_name).read_text(encoding="utf-8"))
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function_name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(APP / file_name), "exec"), namespace)
    return namespace[function_name]


def test_export_leaves_out_a_replaced_attempt():
    namespace = {
        "Any": Any, "Dict": Dict, "List": List, "Mapping": Mapping,
        "Counter": Counter, "defaultdict": defaultdict,
        "TRANSCRIPT_ROLES": {"user", "assistant"},
        "build_message_artifact_payload_map": lambda messages: {},
        "_filter_messages_for_export": list,
        "sanitize_saved_analysis_messages": lambda messages, user_id: messages,
        "hydrate_agent_citations_from_artifacts": lambda messages, payloads: messages,
        "public_history_messages": lambda messages, user_id: messages,
        "exclude_superseded_orchestration_attempts": attempts.exclude_superseded_orchestration_attempts,
        "sort_messages_by_thread": list,
        "is_collaboration_conversation": lambda conversation: False,
        "get_thoughts_for_conversation": lambda *args: [],
        "get_accessible_collaboration_message_thoughts": lambda *args: [],
        "is_saved_analysis_unavailable": lambda message: False,
        "_sanitize_thought": deepcopy,
        "_sanitize_message": lambda message, **kwargs: {"id": message["id"], "content": message["content"]},
        "_sanitize_conversation": lambda conversation, **kwargs: conversation,
        "_build_summary_intro": lambda **kwargs: None,
    }
    export = _load_function("route_backend_conversation_export.py", "_build_export_entry", namespace)
    entry = export({"id": "conversation-1"}, _retried_conversation(), "user-1", {})
    assert [message["id"] for message in entry["messages"]] == ["q1", "a2", "q2"]


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
