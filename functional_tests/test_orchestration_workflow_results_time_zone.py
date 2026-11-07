#!/usr/bin/env python3
# test_orchestration_workflow_results_time_zone.py
"""
Functional test for workflow_results local time-zone handling in planning, retry, answer notes, and compose fences.
Version: 0.261.217
Implemented in: 0.261.217
This test ensures stored workflow result times use the user's local time zone when workflow_results is the only workflow capability enabled.
"""

import importlib
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_orchestration_harness_routes import modules, real_http_harness  # noqa: E402,F401
from test_orchestration_workflow_run_planning_context import (  # noqa: E402,F401
    DIGEST_ID,
    DIGEST_REQUEST,
    PROPOSALS,
    RUNS,
    _frames,
    _names,
    _plan,
    _readers,
    _record_run_contexts,
    wf,
)
from test_orchestration_workflow_results_answer import (  # noqa: E402,F401
    COMPOSED_MARKER,
    EXCERPT_MARKER,
    NONCE,
    RESULTS_SETTINGS,
    WORKFLOW_NAME,
    _answer_record,
    _answer_step,
    _install_workflow_result_runtime,
    _model_user_payload,
    _planning,
    _run_harness,
    _workflow_results_step,
    input_binding,
    results_module,
)
from test_support.orchestration_harness_execution import HarnessEnvironment, compose_step  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


RESULTS = "enable_chat_workflow_results"
NEW_YORK_ZONE = "America/New_York"
TOKYO_ZONE = "Asia/Tokyo"
NEAR_LOCAL_MIDNIGHT = "2026-09-30T02:30:00+00:00"
NEW_YORK_RUN_TIME = "Tue Sep 29, 2026, 10:30 PM EDT"
UTC_RUN_TIME = "Wed Sep 30, 2026, 2:30 AM UTC"
TOKYO_RUN_TIME = "Wed Sep 30, 2026, 11:30 AM JST"
_MISSING = object()


def test_version_is_at_least_workflow_results_time_zone_release():
    assert_app_version_at_least("0.261.217")


def _enable_results_only(runtime, workflow_context_module, monkeypatch):
    runtime.harness.settings.update(
        enable_user_workspace=False,
        allow_user_workflows=True,
        **{PROPOSALS: False, RUNS: False, RESULTS: True},
    )
    calls = []
    for name, reader in _readers(calls).items():
        monkeypatch.setitem(workflow_context_module._DEFAULT_READERS, name, reader)
    return calls


def _record_route_run_contexts(monkeypatch, route_module):
    seen = []
    base = route_module.RunContext

    class RecordingRunContext(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            seen.append({
                "run_id": self.run_id,
                "time_zone": self.time_zone,
                "workflow_planning": deepcopy(self.workflow_planning),
            })

    monkeypatch.setattr(route_module, "RunContext", RecordingRunContext)
    return seen


def _near_midnight_planning(time_zone=_MISSING):
    planning = deepcopy(_planning())
    planning["request_local_time"] = "Tuesday, September 29, 2026, 10:30 PM EDT"
    if time_zone is _MISSING:
        planning.pop("time_zone", None)
    else:
        planning["time_zone"] = time_zone
    return planning


def _install_near_midnight_runtime(monkeypatch, results_module, planning):
    answer_helpers = importlib.import_module("test_orchestration_workflow_results_answer")
    monkeypatch.setattr(answer_helpers, "COMPLETED_AT", NEAR_LOCAL_MIDNIGHT)
    calls = _install_workflow_result_runtime(results_module, monkeypatch)
    monkeypatch.setattr(results_module, "refresh_workflow_planning_privacy", lambda current, conversation, user_id: planning)
    return calls


def _custom_time_zone_results_harness(
    monkeypatch,
    results_module,
    *,
    planning_zone=_MISSING,
    context_zone=NEW_YORK_ZONE,
    steps=None,
):
    env = HarnessEnvironment(monkeypatch)
    env.settings.update(RESULTS_SETTINGS)
    planning = _near_midnight_planning(planning_zone)
    real_normalize = env.schema.normalize_plan

    def normalize(raw, *args, **kwargs):
        capability_ids = kwargs.get("available_capability_ids")
        if capability_ids is not None and "workflow_results" not in capability_ids:
            kwargs["available_capability_ids"] = [*capability_ids, "workflow_results"]
        kwargs.setdefault("workflow_planning", planning)
        return real_normalize(raw, *args, **kwargs)

    monkeypatch.setattr(env.schema, "normalize_plan", normalize)
    calls = _install_near_midnight_runtime(monkeypatch, results_module, planning)
    env.create(
        steps or [_answer_step(), _workflow_results_step()],
        replies=[f"{COMPOSED_MARKER}: {EXCERPT_MARKER}"],
        final_response=input_binding("answer", "answer"),
        workflow_planning=planning,
        time_zone=context_zone,
    )
    return env, calls


def _run_harness_without_context_zone(env):
    emitted = []
    execution = env.prepare()
    # The record still has its saved zone; this isolates the record-zone fallback from context.time_zone.
    execution.context.time_zone = None
    try:
        frames = execution.execute(emit=emitted.append)
    finally:
        execution.close()
    return SimpleNamespace(emitted=emitted, frames=frames, messages=env.assistant_messages(), saved=env.read())


def _assert_note_uses_new_york_time(outcome):
    answer = _answer_record(outcome.saved)
    content = outcome.messages[0]["content"]
    assert outcome.saved["status"] == "completed"
    assert answer["status"] == "completed"
    assert "Saved workflow results:" in content
    assert WORKFLOW_NAME in content
    assert NEW_YORK_RUN_TIME in content
    assert UTC_RUN_TIME not in content
    return content


# Guards W02/E07: results-only turns preserve the request zone in the stored planning and execution context.
def test_results_only_planning_stores_local_zone_and_runs_with_it(real_http_harness, wf, monkeypatch):
    runtime = real_http_harness
    calls = _enable_results_only(runtime, wf, monkeypatch)
    seen = _record_run_contexts(monkeypatch)

    text, record = _plan(runtime, "results-zone-turn", message=DIGEST_REQUEST, time_zone=NEW_YORK_ZONE)
    planning = record["workflow_planning"]

    assert calls == ["workflows"]
    assert record["time_zone"] == NEW_YORK_ZONE
    assert planning["time_zone"] == NEW_YORK_ZONE
    assert planning["workflow_results"] == {"ready": True}
    assert planning["quota_reached"] is None
    assert _names(planning)[0] == "Weekly digest"
    for leaked in ("workflow_planning", "workflow_results", DIGEST_ID, "Weekly digest", "Filler workflow"):
        assert leaked not in text

    executed = runtime.client.post("/api/v2/orchestration/run", json={
        "conversation_id": "conversation-1",
        "run_id": record["id"],
    }, buffered=True)
    frames = _frames(executed)
    saved = runtime.harness.runs.read_item(record["id"], "conversation-1")

    assert executed.status_code == 200
    assert saved["status"] == "completed", frames
    assert seen
    assert seen[-1]["workflow_planning"] == planning
    assert seen[-1]["time_zone"] == NEW_YORK_ZONE


# Guards W01: retry validation rebuilds a results-only run context with the saved turn zone.
def test_results_only_retry_validation_keeps_saved_zone_and_workflow_context(real_http_harness, wf, monkeypatch, modules):
    runtime = real_http_harness
    harness = runtime.harness
    _enable_results_only(runtime, wf, monkeypatch)
    route_contexts = _record_route_run_contexts(monkeypatch, modules.route)
    execution_contexts = _record_run_contexts(monkeypatch)
    planning = {
        "conversation_private": True,
        "workflow_results": {"ready": True},
        "quota_reached": None,
        "time_zone": NEW_YORK_ZONE,
    }
    answer = compose_step("answer", inputs={
        "retained": {"binding": input_binding("retained"), "allow_partial": False},
        "failed": {"binding": input_binding("failed"), "allow_partial": False},
    })
    harness.create(
        [compose_step("retained"), compose_step("failed"), answer],
        replies=["Exact retained draft.", RuntimeError("private failed compose")],
        final_response=input_binding("answer"),
        time_zone=NEW_YORK_ZONE,
        workflow_planning=planning,
    )

    failed = runtime.client.post("/api/v2/orchestration/run", json={
        "conversation_id": "conversation-1",
        "run_id": "run-1",
    }, buffered=True)
    terminal = next(frame for frame in _frames(failed) if frame.get("type") == "orchestration_done")
    assert terminal["status"] == "failed"

    detail = runtime.client.get(
        "/api/v2/orchestration/runs/run-1",
        query_string={"conversation_id": "conversation-1"},
    ).get_json()["run"]
    retry = runtime.client.post("/api/v2/orchestration/runs/run-1/retry", json={
        "conversation_id": "conversation-1",
        "submission_id": "retry-results-zone-1",
        "expected_version": detail["recovery"]["expected_version"],
        "confirm_external_effects": True,
    })
    assert retry.status_code == 200, retry.get_data(as_text=True)
    child_id = retry.get_json()["run"]["run_id"]
    child = harness.runs.read_item(child_id, "conversation-1")

    assert route_contexts
    assert route_contexts[-1]["run_id"] == "run-1"
    assert route_contexts[-1]["time_zone"] == NEW_YORK_ZONE
    assert route_contexts[-1]["workflow_planning"] == planning
    assert child["time_zone"] == NEW_YORK_ZONE
    assert child["workflow_planning"] == planning

    harness.replies = ["Recovered draft.", "The final answer."]
    child_version = child.get("edit_version") or child["plan"].get("edit_version")
    resumed = runtime.client.post("/api/v2/orchestration/run", json={
        "conversation_id": "conversation-1",
        "run_id": child_id,
        "plan_id": child["plan"]["plan_id"],
        **({"expected_version": child_version} if child_version else {}),
    }, buffered=True)
    assert resumed.status_code == 200, resumed.get_data(as_text=True)[:2000]
    assert execution_contexts[-1]["time_zone"] == NEW_YORK_ZONE
    assert execution_contexts[-1]["workflow_planning"] == planning


# Guards E09: saved workflow result answer notes use the planning zone for local near-midnight runs.
def test_saved_workflow_result_note_uses_planning_zone_for_local_midnight(monkeypatch, results_module):
    env, calls = _custom_time_zone_results_harness(
        monkeypatch,
        results_module,
        planning_zone=NEW_YORK_ZONE,
        context_zone=TOKYO_ZONE,
    )
    outcome = _run_harness(env)
    content = _assert_note_uses_new_york_time(outcome)

    assert len(calls["reader"]) == 2
    assert TOKYO_RUN_TIME not in content


# Guards E09: when planning has no zone, saved workflow result notes use the run context zone.
def test_saved_workflow_result_note_uses_context_zone_when_planning_zone_is_absent(monkeypatch, results_module):
    env, calls = _custom_time_zone_results_harness(
        monkeypatch,
        results_module,
        planning_zone=_MISSING,
        context_zone=NEW_YORK_ZONE,
    )
    outcome = _run_harness(env)
    content = _assert_note_uses_new_york_time(outcome)

    assert len(calls["reader"]) == 2
    assert TOKYO_RUN_TIME not in content


# Guards E08/E09: when planning and context omit zones, results-only notes fall back to the record zone.
def test_saved_workflow_result_note_uses_record_zone_when_context_zone_is_absent(monkeypatch, results_module):
    env, calls = _custom_time_zone_results_harness(
        monkeypatch,
        results_module,
        planning_zone=_MISSING,
        context_zone=NEW_YORK_ZONE,
    )
    outcome = _run_harness_without_context_zone(env)
    content = _assert_note_uses_new_york_time(outcome)

    assert len(calls["reader"]) == 2
    assert TOKYO_RUN_TIME not in content


# Guards K04: compose fences prefer the planning zone over a different run context zone.
def test_compose_fence_uses_planning_zone_before_context_zone(monkeypatch, results_module):
    env, calls = _custom_time_zone_results_harness(
        monkeypatch,
        results_module,
        planning_zone=NEW_YORK_ZONE,
        context_zone=TOKYO_ZONE,
    )
    outcome = _run_harness(env)
    payload, _messages = _model_user_payload(env)
    input_value = payload["inputs"]["workflow_notes"]["value"]

    assert outcome.saved["status"] == "completed"
    assert len(calls["reader"]) == 2
    assert input_value.startswith(f"<<<WORKFLOW RESULT {NONCE} (untrusted data)>>>")
    assert f"Run completed: {NEW_YORK_RUN_TIME}" in input_value
    assert TOKYO_RUN_TIME not in input_value


# Guards K05: compose fences use the run context zone when the planning zone is absent.
def test_compose_fence_uses_context_zone_when_planning_zone_is_absent(monkeypatch, results_module):
    env, calls = _custom_time_zone_results_harness(
        monkeypatch,
        results_module,
        planning_zone=_MISSING,
        context_zone=NEW_YORK_ZONE,
    )
    outcome = _run_harness(env)
    payload, _messages = _model_user_payload(env)
    input_value = payload["inputs"]["workflow_notes"]["value"]

    assert outcome.saved["status"] == "completed"
    assert len(calls["reader"]) == 2
    assert input_value.startswith(f"<<<WORKFLOW RESULT {NONCE} (untrusted data)>>>")
    assert f"Run completed: {NEW_YORK_RUN_TIME}" in input_value
    assert UTC_RUN_TIME not in input_value


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
