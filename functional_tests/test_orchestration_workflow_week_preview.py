#!/usr/bin/env python3
# test_orchestration_workflow_week_preview.py
"""
Functional test for answering a recurring request's current period while proposing its workflow.
Version: 0.261.204
Implemented in: 0.261.204

This test ensures that a request such as "every Monday, tell me what to focus on this week" is
planned as an answer for the current week plus a workflow proposal for the weeks to come. The
planner is told this preview pattern only when workflow proposals are offered. In a turn that
may propose a workflow, the answer-writing step is told the user's local time in the wording a
calendar workflow's run gives each task, so the preview and the scheduled runs resolve "this week"
the same way. Every other answer is written from exactly the messages it was written from before.
"""

import importlib
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_planning_context import AGENT_SETTINGS, PRIVATE, SETTING, _build, wf  # noqa: F401
from test_orchestration_workflow_propose_capability import (  # noqa: F401
    ANSWER,
    DELIVERABLES,
    WORKFLOW_SETTINGS,
    ZONE,
    _blueprint,
    _handle,
    _harness,
    _harness_proposal,
    _plan_request,
    _propose,
    _raw_plan,
    _record,
    _step,
    ow,
    planning,
)
from test_support.orchestration_harness_execution import (
    HarnessEnvironment,
    compose_step,
    decoded_frames,
    input_binding,
)
from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
NOW = datetime(2026, 9, 29, 12, 19, tzinfo=timezone.utc)
NEW_YORK_LINE = "Current date and time: Tuesday, 29 September 2026, 08:19 (America/New_York)"
TIME_LINE_PREFIX = "Current date and time: "
PREVIEW_PATTERN = "answer the current period now as a preview of one run"
RELATIVE_INSTRUCTIONS = "List what I should focus on this week from my email."


def test_version_includes_the_week_preview():
    assert_app_version_at_least("0.261.204")


# ---------------------------------------------------------------------------
# The answer's local time line
# ---------------------------------------------------------------------------

def test_the_line_uses_a_calendar_runs_wording(wf, planning):
    schedules = importlib.import_module("functions_workflow_schedules")
    monday_eight = {
        "kind": "calendar", "frequency": "weekly", "days_of_week": ["monday"],
        "time_of_day": "08:00", "timezone": ZONE,
    }
    line = wf.workflow_answer_time_line(planning, ZONE, NOW)
    run_line = schedules.workflow_run_time_context(monday_eight, NOW)
    assert line == run_line == NEW_YORK_LINE


def test_only_a_turn_that_may_propose_a_workflow_gets_the_line(wf, planning):
    contexts = {
        "none": None,
        "empty": {},
        "not a dict": "planning",
        "setting off": _build(wf, [], {**AGENT_SETTINGS, SETTING: False}),
        "shared": _build(wf, [], conversation={**PRIVATE, "chat_type": "personal_multi_user"}),
        "collaboration": _build(wf, [], conversation={**PRIVATE, "collaboration_conversation_id": "collaboration-1"}),
        "quota reached": {**deepcopy(planning), "quota_reached": True},
        "context unavailable": {**deepcopy(planning), "context_unavailable": True},
        "no catalog": {**deepcopy(planning), "catalog": None},
    }
    lines = {name: wf.workflow_answer_time_line(context, ZONE, NOW) for name, context in contexts.items()}
    assert lines == {name: "" for name in contexts}


def test_the_turns_zone_names_the_time_and_the_planning_zone_stands_in(wf, planning):
    turn_zone = wf.workflow_answer_time_line(planning, "Asia/Tokyo", NOW)
    fallbacks = {
        repr(value): wf.workflow_answer_time_line(planning, value, NOW)
        for value in (None, "", "Mars/Olympus", "america/chicago", 42)
    }
    no_zone_anywhere = wf.workflow_answer_time_line({**deepcopy(planning), "time_zone": None}, None, NOW)
    assert planning["time_zone"] == ZONE
    assert turn_zone == "Current date and time: Tuesday, 29 September 2026, 21:19 (Asia/Tokyo)"
    assert fallbacks == {name: NEW_YORK_LINE for name in fallbacks}
    assert no_zone_anywhere == "Current date and time: Tuesday, 29 September 2026, 12:19 (UTC)"


# ---------------------------------------------------------------------------
# The answer-writing step
# ---------------------------------------------------------------------------

def _time_lines(wf):
    """The line as it reads now; a run spans at most one minute boundary between two reads."""
    return wf.request_local_time_line(ZONE)


def _compose_messages(monkeypatch, **turn_updates):
    env = HarnessEnvironment(monkeypatch)
    env.settings.update(WORKFLOW_SETTINGS)
    env.create([compose_step("answer")], replies=["Your priorities."], final_response=input_binding("answer"),
               **turn_updates)
    execution = env.prepare()
    decoded_frames(execution.execute())
    run = env.read()
    assert run["status"] == "completed"
    assert len(env.model_calls) == 1
    return env.model_calls[0]["messages"]


def test_the_answer_in_a_proposing_turn_is_told_the_local_time_just_before_the_request(modules, wf, ow, monkeypatch):
    planning = _build(wf, [])
    env, dry_runs, writes = _harness(monkeypatch, ow, planning, [compose_step("answer"), _harness_proposal(planning)],
                                     ["This week: reply to the budget thread first."])
    before = _time_lines(wf)
    execution = env.prepare()
    decoded_frames(execution.execute())
    after = _time_lines(wf)
    run = env.read()
    assert run["status"] == "completed"
    assert len(dry_runs) == 1 and writes == []
    assert len(env.model_calls) == 1
    messages = env.model_calls[0]["messages"]
    lines = [message for message in messages if message["content"].startswith(TIME_LINE_PREFIX)]
    assert len(lines) == 1
    assert lines[0]["role"] == "system" and lines[0]["content"] in {before, after}
    assert lines[0]["content"].endswith(f"({ZONE})")
    assert messages[-2] == lines[0] and messages[-1]["role"] == "user"
    assert TIME_LINE_PREFIX not in messages[-1]["content"]


def test_every_other_answer_is_written_from_the_same_messages_as_before(modules, wf, monkeypatch):
    plain = _compose_messages(monkeypatch, time_zone=ZONE)
    shared = _compose_messages(
        monkeypatch, time_zone=ZONE,
        workflow_planning=_build(wf, [], conversation={**PRIVATE, "chat_type": "personal_multi_user"}),
    )
    before = _time_lines(wf)
    proposing = _compose_messages(monkeypatch, time_zone=ZONE, workflow_planning=_build(wf, []))
    after = _time_lines(wf)
    assert not any(message["content"].startswith(TIME_LINE_PREFIX) for message in plain)
    assert shared == plain
    added = proposing[-2]
    assert added["role"] == "system" and added["content"] in {before, after}
    assert proposing[:-2] + proposing[-1:] == plain


# ---------------------------------------------------------------------------
# Planning the preview and the proposal together
# ---------------------------------------------------------------------------

def test_a_recurring_request_is_planned_as_a_preview_and_a_proposal(modules, wf, monkeypatch):
    planning = _build(wf, [])
    task = {
        "title": "Weekly focus", "instructions": RELATIVE_INSTRUCTIONS,
        "runner": {"type": "agent", "agent_ref": _handle(planning, "agents", "Mail helper")},
    }
    record = _record()
    kind, plan = _plan_request(
        monkeypatch, planning, [_raw_plan([ANSWER, _propose(_blueprint(planning, tasks=[task]))])], record,
    )
    assert kind == "plan"
    assert len(record.calls) == 1
    system, user = record.calls[0][0]["content"], record.calls[0][1]["content"]
    assert PREVIEW_PATTERN in system
    assert '"request_local_time"' in user
    assert [step["capability_id"] for step in plan["steps"]] == ["compose", "workflow_propose"]
    assert sorted(entry["kind"] for entry in plan["deliverables"]) == ["answer", "workflow"]
    assert all(entry["status"] == "planned" for entry in plan["deliverables"])
    assert plan["final_response"]["step_id"] == "answer"
    assert "this week" in _step(plan, "answer")["arguments"]["instruction"]
    blueprint = _step(plan, "propose")["arguments"]["blueprint"]
    assert blueprint["tasks"][0]["instructions"] == RELATIVE_INSTRUCTIONS
    assert blueprint["trigger"]["timezone"] == ZONE


def test_the_planner_is_not_told_the_preview_pattern_without_workflow_planning(modules, monkeypatch):
    record = _record()
    kind, plan = _plan_request(monkeypatch, None, [_raw_plan([ANSWER], deliverables=DELIVERABLES[:1])], record)
    assert kind == "plan"
    assert [step["capability_id"] for step in plan["steps"]] == ["compose"]
    system = record.calls[0][0]["content"]
    assert PREVIEW_PATTERN not in system
    assert "workflow_propose" not in system


# ---------------------------------------------------------------------------
# Cold imports
# ---------------------------------------------------------------------------

PROBE = r'''
import importlib
import sys

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

with offline_app_imports() as environment:
    for name in sys.argv[3:]:
        importlib.import_module(name)
    adapters = importlib.import_module("functions_orchestration_adapters")
    compose = adapters.get_adapter("compose")
    composition = importlib.import_module("functions_orchestration_composition")
    context = importlib.import_module("functions_orchestration_workflow_context")
    if compose is not composition.adapter_compose:
        raise AssertionError("The compose adapter resolved a different module")
    if composition.workflow_answer_time_line is not context.workflow_answer_time_line:
        raise AssertionError("Composition resolved a different time line helper")
    if context.workflow_answer_time_line(None, "America/New_York") != "":
        raise AssertionError("A turn without workflow planning was given a time line")
    if environment.network_attempts:
        raise AssertionError("A cold import swallowed a network attempt")
print("PASS: composition cold imports")
'''


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("first", [
    "functions_orchestration_composition",
    "functions_orchestration_adapters",
    "functions_orchestration_workflow_context",
])
def test_composition_loads_cold_in_either_import_order(first, optimized):
    command = [sys.executable, "-B", *(["-O"] if optimized else []), "-c", PROBE, str(APP), str(TESTS), first]
    process = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    assert process.returncode == 0, process.stdout[-8000:] + process.stderr[-8000:]
    assert "PASS:" in process.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
