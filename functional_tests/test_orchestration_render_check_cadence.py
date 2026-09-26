#!/usr/bin/env python3
# test_orchestration_render_check_cadence.py
"""
Functional test for paced render execution checks and step time limits during rendering.
Version: 0.261.141
Implemented in: 0.261.141

This test ensures that a file render re-proves its claim, run, capability admission and
source access on a bounded cadence instead of on every record or block, that revocation
and lease renewal still happen on time, that publication boundaries keep their own full
checks, and that the owning step's time limit stops an unstaged render cleanly with a
clear, non-retryable failure while a staged file is always committed.
"""

import importlib
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from functions_orchestration_output_store import OutputError
from functions_orchestration_rendering import (
    OrchestrationRenderingService,
    OutputStepTimeLimitError,
    execute_render_file,
    output_failure,
)
from test_orchestration_output_lifecycle import lifecycle, production_modules  # noqa: F401
from test_orchestration_render_waiting_runtime import render_runtime  # noqa: F401


STEP_LIMIT_MESSAGE = "This file was stopped because its step reached the time limit."
RUN_LIMIT_MESSAGE = "This file was stopped because the run reached its time limit."
FACT_KEYS = {
    "total_ms", "full_checks", "light_checks", "source_rechecks", "paced_source_rechecks",
    "stop_observed", "status", "output_code",
}


class _Ticks:
    """The render attempt's monotonic clock, advanced explicitly by each test."""

    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class _ExecutorClock:
    """The executor's monotonic clock; everything else is the real time module."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def __getattr__(self, name):
        return getattr(importlib.import_module("time"), name)


def _paced(lifecycle):
    """Freeze the attempt clock; the fixture's 10 second lease caps the interval at 2.5 s."""
    ticks = _Ticks()
    lifecycle.service.monotonic = ticks
    lifecycle.service.full_check_interval = 5.0
    return ticks


def _wrap_renderer(lifecycle, before):
    real = lifecycle.service.renderer

    def renderer(**kwargs):
        before(kwargs)
        return real(**kwargs)

    lifecycle.service.renderer = renderer


def _render_checks(lifecycle):
    """Full "render" authorizations: the claim's own check plus every full attempt check."""
    return lifecycle.authorization_calls.count("render")


def test_frequent_render_checks_share_paced_full_checks(lifecycle):
    print("🔍 Testing per-record checks no longer re-authorize every call...")
    _paced(lifecycle)
    output = lifecycle.prepare()
    lifecycle.authorization_calls.clear()

    def chatty(kwargs):
        for _ in range(500):
            kwargs["check"]()

    _wrap_renderer(lifecycle, chatty)
    facts = []
    state = lifecycle.service.render_attempt(output["output_id"], observe=facts.append)
    assert state["state"] == "completed", state
    # The claim, the attempt's opening check and the one right before its intent is prepared.
    assert _render_checks(lifecycle) == 3
    assert "prepare" in lifecycle.authorization_calls and "commit" in lifecycle.authorization_calls
    assert facts[0]["full_checks"] == 2 and facts[0]["light_checks"] >= 500
    print("✅ 500 renderer checks cost two full checks.")


def test_a_full_check_runs_again_once_the_interval_elapses(lifecycle):
    print("🔍 Testing revocation is caught by the next paced full check...")
    ticks = _paced(lifecycle)
    output = lifecycle.prepare()
    lifecycle.authorization_calls.clear()
    seen = []

    def slow(kwargs):
        for index in range(10):
            ticks.value += 1.0
            seen.append(index)
            if index == 4:
                lifecycle.capabilities = False
            kwargs["check"]()

    _wrap_renderer(lifecycle, slow)
    state = lifecycle.run(output)
    assert state["state"] == "failed" and state["error_code"] == "output_capability_disabled"
    assert state["can_retry"] is False
    # The claim, then full checks at 0 s and 3 s; the capability revoked at 5 s was refused at 6 s.
    assert seen == [0, 1, 2, 3, 4, 5]
    assert _render_checks(lifecycle) == 4
    assert lifecycle.blobs.uploads == 0 and not lifecycle.messages.items
    print("✅ The revocation was refused one interval later, before anything was stored.")


def test_lease_renewal_is_not_delayed_by_pacing(lifecycle):
    print("🔍 Testing the lease is renewed on time even while the interval has not elapsed...")
    _paced(lifecycle)
    output = lifecycle.prepare()
    lifecycle.authorization_calls.clear()

    def long_wall_clock(kwargs):
        for _ in range(2):
            lifecycle.now += timedelta(seconds=6)
            kwargs["check"]()
            kwargs["check"]()

    _wrap_renderer(lifecycle, long_wall_clock)
    state = lifecycle.run(output)
    assert state["state"] == "completed", state
    # The claim, the opening check, one renewal per six seconds of a ten second lease, and
    # the pre-intent check.
    assert _render_checks(lifecycle) == 5
    print("✅ Each renewal-due check ran in full and the file completed.")


def test_renderer_source_rechecks_are_paced_but_revocation_is_still_refused(lifecycle):
    print("🔍 Testing renderer source rechecks are paced without weakening the final proof...")
    _paced(lifecycle)
    output = lifecycle.prepare()
    facts = []

    def rechecking(kwargs):
        for _ in range(50):
            kwargs["source"].recheck()

    _wrap_renderer(lifecycle, rechecking)
    completed = lifecycle.service.render_attempt(output["output_id"], observe=facts.append)
    assert completed["state"] == "completed", completed
    # The renderer's own rechecks share the same cadence as the 50 added here.
    assert facts[0]["source_rechecks"] == 1 and facts[0]["paced_source_rechecks"] >= 49

    revoked = lifecycle.prepare("csv")

    def revoking(kwargs):
        kwargs["source"].recheck()
        lifecycle.results.denied.add("document-1")
        kwargs["source"].recheck()

    _wrap_renderer(lifecycle, revoking)
    uploads = lifecycle.blobs.uploads
    state = lifecycle.run(revoked)
    assert state["state"] == "failed" and state["error_code"] == "output_access_denied"
    assert lifecycle.blobs.uploads == uploads
    print("✅ Rechecks were paced and the revoked source was still refused.")


def test_step_stop_fails_the_file_before_rendering_without_publishing(lifecycle):
    print("🔍 Testing a step stop ends an unstaged render cleanly...")
    output = lifecycle.prepare()
    probes = []

    def stop():
        probes.append(True)
        return True

    facts = []
    state = lifecycle.service.render_attempt(output["output_id"], stop=stop, observe=facts.append)
    assert state["state"] == "failed" and state["error_code"] == "output_step_time_limit"
    assert state["can_retry"] is False and state["next_retry_at"] is None
    assert state["message"] == STEP_LIMIT_MESSAGE
    assert lifecycle.raw(output)["retryable"] is False
    assert not lifecycle.render_calls and lifecycle.blobs.uploads == 0 and not lifecycle.messages.items
    assert len(probes) == 1
    assert facts[0]["stop_observed"] is True and facts[0]["status"] == "failed"
    assert facts[0]["output_code"] == "output_step_time_limit"
    with pytest.raises(OutputError):
        lifecycle.service.manual_retry(output["output_id"], "time-limit-retry")
    print("✅ The file failed without rendering, storing or offering a retry.")


def test_step_stop_during_staging_fails_the_file_and_schedules_cleanup(lifecycle):
    print("🔍 Testing a stop observed while staging leaves cleanup pending...")
    ticks = _paced(lifecycle)
    output = lifecycle.prepare()
    stopping = {"now": False}

    def reach_limit():
        stopping["now"] = True
        ticks.value += 10.0

    lifecycle.blobs.before_upload = reach_limit
    state = lifecycle.service.render_attempt(output["output_id"], stop=lambda: stopping["now"])
    record = lifecycle.raw(output)
    assert state["state"] == "failed" and state["error_code"] == "output_step_time_limit"
    assert state["message"] == STEP_LIMIT_MESSAGE and state["artifact_message_id"] is None
    assert record["cleanup_pending"] is True and record["intents"]
    assert not lifecycle.messages.items
    lifecycle.now += timedelta(seconds=11)
    lifecycle.service.reconcile(output["output_id"])
    assert not lifecycle.blobs.data and not lifecycle.messages.items
    print("✅ The partial upload was left for cleanup and nothing was published.")


def test_staged_file_is_committed_even_when_the_stop_arrives_after_staging(lifecycle):
    print("🔍 Testing staged bytes are always committed...")
    ticks = _paced(lifecycle)
    output = lifecycle.prepare()
    stopping = {"now": False}
    probes = []
    transport = lifecycle.service.transport
    real_reconcile = transport.reconcile

    def stop():
        probes.append(stopping["now"])
        return stopping["now"]

    def reconcile_after_limit(record, **kwargs):
        stopping["now"] = True
        ticks.value += 10.0
        return real_reconcile(record, **kwargs)

    transport.reconcile = reconcile_after_limit
    try:
        state = lifecycle.service.render_attempt(output["output_id"], stop=stop)
    finally:
        transport.reconcile = real_reconcile
    assert state["state"] == "completed", state
    assert state["artifact_message_id"] and lifecycle.blobs.uploads == 1
    assert probes and not any(probes)
    print("✅ The stop after staging did not discard the stored file.")


def test_user_cancellation_during_render_cancels_rather_than_times_out(lifecycle):
    print("🔍 Testing a user cancellation keeps its own outcome...")
    output = lifecycle.prepare()

    def cancel(kwargs):
        lifecycle.change_run(cancellation_requested_at=lifecycle.now.isoformat())

    def stop():
        run = lifecycle.runs.read_item("run-1", "conversation-1")
        return bool(run.get("cancellation_requested_at"))

    _wrap_renderer(lifecycle, cancel)
    state = lifecycle.service.render_attempt(output["output_id"], stop=stop)
    assert state["state"] == "cancelled" and state["error_code"] == "output_cancelled"
    assert state["message"] == "This file was cancelled."
    assert lifecycle.blobs.uploads == 0 and not lifecycle.messages.items
    print("✅ The render was cancelled, not reported as a time limit.")


def test_run_deadline_during_render_says_the_run_reached_its_limit(lifecycle):
    print("🔍 Testing a run deadline explains why the file stopped...")
    lifecycle.deadline = lifecycle.now + timedelta(seconds=1)
    output = lifecycle.prepare()

    def expire(kwargs):
        lifecycle.now += timedelta(seconds=2)

    _wrap_renderer(lifecycle, expire)
    state = lifecycle.run(output)
    assert state["state"] in {"failed", "cancelled"}
    assert state["error_code"] == "output_deadline_exceeded"
    assert state["message"] == RUN_LIMIT_MESSAGE
    print("✅ The stopped file named the run time limit.")


def test_observe_receives_identifier_free_render_facts(lifecycle):
    print("🔍 Testing render diagnostics carry timings and counts only...")
    output = lifecycle.prepare()
    facts = []
    state = lifecycle.service.render_attempt(output["output_id"], observe=facts.append)
    assert state["state"] == "completed"
    assert len(facts) == 1
    fact = facts[0]
    assert FACT_KEYS <= set(fact)
    assert {"render_ms", "verify_ms", "stage_ms", "commit_ms"} <= set(fact)
    assert fact["status"] == "completed" and fact["output_code"] is None
    assert fact["output_format"] == "json" and fact["size_bytes"] == state["size_bytes"]
    assert all(type(value) in (int, bool, str) or value is None for value in fact.values())
    text = json.dumps(fact)
    for private in (output["output_id"], "run-1", "conversation-1", "owner", "document-1", "json_file"):
        assert private not in text
    observed = []
    duplicate = lifecycle.service.render_attempt(output["output_id"], observe=observed.append)
    assert duplicate["state"] == "completed" and observed == []
    print("✅ Diagnostics were identifier-free and emitted only for a claimed attempt.")


def test_diagnostic_and_probe_failures_never_change_the_outcome(lifecycle):
    print("🔍 Testing failing telemetry or stop probes cannot fail a file...")

    def broken_observer(facts):
        raise RuntimeError("private observer failure")

    def broken_stop():
        raise RuntimeError("private probe failure")

    first = lifecycle.service.render_attempt(lifecycle.prepare()["output_id"], observe=broken_observer)
    second = lifecycle.service.render_attempt(lifecycle.prepare("csv")["output_id"], stop=broken_stop)
    assert first["state"] == second["state"] == "completed"
    print("✅ Both files completed.")


def test_invalid_pacing_configuration_is_refused(lifecycle):
    print("🔍 Testing invalid pacing inputs are refused...")
    service = lifecycle.service
    arguments = dict(
        authorize_execution=lifecycle.authorize, max_output_bytes=1024 * 1024, renderer=lifecycle.render,
    )
    for interval in (0, -1, float("inf"), float("nan"), "5", True):
        with pytest.raises(OutputError) as refused:
            OrchestrationRenderingService(
                service.store, service.results, service.transport, full_check_interval=interval, **arguments,
            )
        assert refused.value.code == "output_limit_invalid"
    with pytest.raises(OutputError) as refused:
        OrchestrationRenderingService(
            service.store, service.results, service.transport, monotonic="clock", **arguments,
        )
    assert refused.value.code == "output_service_required"
    output = lifecycle.prepare()
    for keyword in ("stop", "observe"):
        with pytest.raises(OutputError) as refused:
            service.render_attempt(output["output_id"], **{keyword: "not-callable"})
        assert refused.value.code == "output_service_required"
    assert lifecycle.raw(output)["state"] == "waiting"
    print("✅ Invalid pacing inputs were refused before any attempt.")


def test_step_time_limit_error_is_not_a_value_error():
    print("🔍 Testing the time-limit error escapes value-limit conversion...")
    error = OutputStepTimeLimitError()
    assert not isinstance(error, ValueError)
    assert output_failure(error) == ("output_step_time_limit", False)
    print("✅ The error is a non-retryable runtime stop.")


def test_execute_render_file_bounds_the_attempt_with_the_step_stop(lifecycle):
    print("🔍 Testing the render adapter passes its step stop into the attempt...")
    producer = lifecycle.add_render_step("json_file")
    reader = lifecycle.service.results.open_result(lifecycle.saved.output("findings"))
    context = SimpleNamespace(
        plan_contract_version=2, execution_deadline_at=lifecycle.deadline.isoformat(),
        result_producer=lambda step: producer,
    )
    step = {
        "step_id": "json_file", "capability_id": "render_file",
        "arguments": {"file_name": "json_file.json", "output_format": "json", "profile": "exact_records_v1"},
    }
    probes = []

    def cancel_requested():
        probes.append(True)
        return len(probes) > 1

    facts = []
    result = execute_render_file(
        step, context, service_factory=lambda *args, **kwargs: lifecycle.service,
        resolve_inputs=lambda step, context: {"source": reader},
        build_step_result=lifecycle.modules.schema.build_step_result,
        build_failure=lifecycle.modules.schema.build_failure, settings={}, user_id="owner",
        cancel_requested=cancel_requested, observe_render=facts.append,
    )
    assert result["status"] == "failed" and result["artifacts"] == []
    assert result["failure"]["code"] == "step_timeout"
    assert "Admin Settings > Orchestration > Chat Orchestration > Limits" in result["failure"]["message"]
    output = result["outputs"][0]
    assert output["state"] == "failed" and output["error_code"] == "output_step_time_limit"
    assert output["message"] == STEP_LIMIT_MESSAGE
    assert len(probes) == 2 and not lifecycle.render_calls and lifecycle.blobs.uploads == 0
    assert facts[0]["stop_observed"] is True
    print("✅ The adapter's stop ended the attempt as a step time limit.")


def test_executor_step_budget_reached_during_render_fails_the_step(render_runtime, monkeypatch):
    print("🔍 Testing a step budget reached during rendering fails the step cleanly...")
    case = render_runtime
    executor = importlib.import_module("functions_orchestration_executor")
    clock = _ExecutorClock()
    monkeypatch.setattr(executor, "time", clock)
    case.settings["chat_orchestration_step_timeout_seconds"] = 30

    def slow(kwargs):
        clock.now += 45

    _wrap_renderer(case.lifecycle, slow)
    with patch.object(executor, "log_event") as logged:
        result = case.execute(case.initial)
    step = next(entry for entry in result["steps"] if entry["step_id"] == "file")
    assert step["status"] == "failed" and step["failure"]["code"] == "step_timeout"
    outputs = case.lifecycle.service.list_public_outputs("run-1")
    assert len(outputs) == 1 and outputs[0]["state"] == "failed"
    assert outputs[0]["error_code"] == "output_step_time_limit"
    assert outputs[0]["message"] == STEP_LIMIT_MESSAGE
    assert case.lifecycle.blobs.uploads == 0 and not case.lifecycle.messages.items
    attempts = [call for call in logged.call_args_list if "file render attempt finished" in call.args[0]]
    assert len(attempts) == 1
    extra = attempts[0].kwargs["extra"]
    assert extra["status"] == "failed" and extra["output_code"] == "output_step_time_limit"
    assert extra["stop_observed"] is True and extra["capability_id"] == "render_file"
    assert extra["output_format"] == "md"
    assert "run-1" not in json.dumps(extra) and "conversation-1" not in json.dumps(extra)
    print("✅ The step failed with step_timeout and the file was never published.")
