#!/usr/bin/env python3
# test_orchestration_server_continuation.py
"""
Functional test for the server-side next attempt after a failed orchestration run.
Version: 0.261.467
Implemented in: 0.261.462

This test ensures that a failed attempt is followed by its next one on the server, after the
browser's response has ended and without any request from a page, and that nothing is started
when the setting is off.
"""

import json
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_orchestration_harness_routes import modules, real_http_harness  # noqa: E402,F401 (fixtures)
from test_support.orchestration_harness_execution import compose_step, input_binding  # noqa: E402


def _answer_report(status):
    return json.dumps({"requirements": [{
        "id": "details", "requirement": "Include status, proposal deadline and response days.",
        "status": status, "reason": "Requested facts omitted." if status == "missing" else "",
        "evidence_refs": [], "answer_quote": "Evaluation" if status == "satisfied" else "",
    }]})


def _wait_for_attempts(harness, count, *, seconds=60):
    """The next attempt runs on the server after the response has ended."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        attempts = [
            item for item in harness.runs.items.values()
            if isinstance(item, dict) and isinstance(item.get("plan"), dict) and item.get("turn_id")
        ]
        if len(attempts) >= count and all(
            item.get("status") in ("completed", "failed", "cancelled") and not item.get("execution_lease")
            for item in attempts
        ):
            return sorted(attempts, key=lambda item: item.get("attempt_index") or 1)
        time.sleep(0.2)
    raise AssertionError("The server did not finish the expected attempts in time: " + json.dumps([
        {key: item.get(key) for key in ("id", "status", "attempt_index", "retry_of_run_id", "latest_attempt_run_id")}
        | {"lease": bool(item.get("execution_lease")), "failure": (item.get("failure") or {}).get("code")}
        for item in attempts
    ]))


def test_the_server_runs_the_next_attempt_after_the_response_has_ended(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    harness.settings.update(
        enable_chat_orchestration_completeness_check=True,
        enable_chat_orchestration_reactive_loop=True,
        # No recovery inside the run, so the failed attempt itself is what gets followed.
        chat_orchestration_max_recovery_rounds=1,
    )
    record = harness.create(
        steps=[compose_step()],
        replies=[
            "Evaluation", _answer_report("missing"), "Evaluation first", _answer_report("missing"),
            "Evaluation final", _answer_report("missing"),
            # One round inside the run: checked again, corrected twice, still incomplete.
            _answer_report("missing"), "Evaluation third", _answer_report("missing"),
            "Evaluation fourth", _answer_report("missing"),
            # The attempt the server starts by itself checks the retained answer again.
            _answer_report("satisfied"),
        ],
        final_response=input_binding("prepare"),
    )
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "run_id": record["id"], "conversation_id": "conversation-1",
    }, buffered=True)
    frames = [
        json.loads(frame.partition("data:")[2].strip())
        for frame in response.get_data(as_text=True).split("\n\n") if frame.startswith("data:")
    ]
    # The browser's response ends with the failed attempt; nothing else is asked of it.
    assert response.status_code == 200 and frames[-1]["status"] == "failed"
    first, second = _wait_for_attempts(harness, 2)
    assert first["id"] == record["id"] and first["status"] == "failed"
    assert first["latest_attempt_run_id"] == second["id"]
    assert second["retry_of_run_id"] == record["id"] and second["attempt_index"] == 2
    assert second["status"] == "completed", second.get("failure")
    assert len(harness.model_calls) == 12


def test_the_server_starts_nothing_when_the_setting_is_off(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    harness.settings.update(enable_chat_orchestration_completeness_check=True)
    record = harness.create(
        steps=[compose_step()],
        replies=[
            "Evaluation", _answer_report("missing"), "Evaluation first", _answer_report("missing"),
            "Evaluation final", _answer_report("missing"),
        ],
        final_response=input_binding("prepare"),
    )
    runtime.client.post("/api/v2/orchestration/run", json={
        "run_id": record["id"], "conversation_id": "conversation-1",
    }, buffered=True)
    attempts = _wait_for_attempts(harness, 1)
    time.sleep(1.5)
    assert len(_wait_for_attempts(harness, 1)) == len(attempts) == 1
    assert len(harness.model_calls) == 6


def test_a_refused_next_attempt_logs_which_check_refused_it(modules):
    """Most refusals share one public code; the log must name the check behind it."""
    from functions_orchestration_checkpoints import CheckpointError
    from functions_orchestration_recovery import RecoveryError

    try:
        try:
            raise CheckpointError(
                "recovery_changed", rule="execution_binding_changed", stage="resume_binding",
                producer_capability_id="tabular_analyze",
            )
        except CheckpointError as inner:
            raise RecoveryError("Saved progress changed.", recovery={"reason_code": "recovery_changed"}) from inner
    except RecoveryError as refused:
        detail = modules.route._refusal_detail(refused)
        assert refused.code == "recovery_unavailable"
    assert detail["cause_type"] == "CheckpointError" and detail["cause_code"] == "recovery_changed"
    assert detail["validation_rule"] == "execution_binding_changed" and detail["refusal_stage"] == "resume_binding"
    assert detail["reason_code"] == "recovery_changed" and detail["producer_capability_id"] == "tabular_analyze"
    assert detail["error_site"].startswith("test_orchestration_server_continuation.py:")
    # A plain error from rebuilding the context has no rule; its type and raise site still show.
    try:
        try:
            raise ValueError("private detail that must not be logged")
        except ValueError as inner:
            raise RecoveryError() from inner
    except RecoveryError as refused:
        detail = modules.route._refusal_detail(refused)
    assert detail["cause_type"] == "ValueError" and "private" not in json.dumps(detail)
    assert set(detail) == {"cause_type", "error_site"}
