#!/usr/bin/env python3
# test_orchestration_workflow_proposal_done_when.py
"""
Functional test for the Phase 4 "Done when": a recurring chat request becomes a scheduled workflow.
Version: 0.261.207
Implemented in: 0.261.207

This test ensures that "Every Monday read my email and tell me what I should do this week",
planned by the real planner from a scripted model reply, becomes this week's answer and a
workflow proposal. The real executor runs the plan: the workflow_propose step describes the
proposal with the real draft service dry run and creates nothing. The requester's proposal
routes then show the proposal, and Create & start stores one enabled personal workflow:
calendar weekly on Monday at 08:00 in the request's time zone, with the notify-only digest
alert rules, whose next run after a Sunday is Monday 08:00 local time. Accepting again returns
the same workflow with status 200, and a Deny afterwards is refused with 409.

The planner and answer models are the only stubs on the request's path. Storage is in memory
and the network is blocked.
"""

import importlib
import json
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from flask import Blueprint, Flask
from werkzeug.test import Client
from werkzeug.wrappers import Response

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_planning_context import (  # noqa: F401
    AGENT_SETTINGS,
    OWNER,
    PERSONAL_AGENT_ID,
    _build,
    _global_agents,
    _personal_agents,
    wf,
)
from test_orchestration_workflow_proposal_routes import WorkflowStore, accept, code, deny, login, status
from test_orchestration_workflow_propose_capability import (
    ANSWER,
    _handle,
    _plan_request,
    _propose,
    _raw_plan,
    _record,
    _step,
    assert_nothing_disclosed,
)
from test_support.orchestration_harness_execution import HarnessEnvironment, decoded_frames
from test_support.versioning import assert_app_version_at_least


ZONE = "America/New_York"
RUN = "run-1"
CONVERSATION = "conversation-1"
STEP = "propose"
NAME = "Monday email review"
INSTRUCTIONS = "Read my email from the past week and list what I should focus on this week."
PREVIEW = "This week, answer the budget review first and prepare Thursday's client call."
WEEKLY_MONDAY = {
    "kind": "calendar", "frequency": "weekly", "days_of_week": ["monday"], "time_of_day": "08:00", "timezone": ZONE,
}
# The first run after each Sunday. On 1 November 2026 New York leaves daylight saving time, so
# Monday 08:00 local time is 13:00 UTC there, and 12:00 UTC the Monday before.
NEXT_RUNS = (
    (datetime(2026, 10, 25, 12, 0, tzinfo=ZoneInfo(ZONE)), datetime(2026, 10, 26, 8, 0, tzinfo=ZoneInfo(ZONE))),
    (datetime(2026, 11, 1, 12, 0, tzinfo=ZoneInfo(ZONE)), datetime(2026, 11, 2, 8, 0, tzinfo=ZoneInfo(ZONE))),
)


def _blueprint(planning):
    # The planner leaves the time zone out; plan validation fills in the request's zone.
    return {
        "name": NAME,
        "description": "Reads my email every Monday and lists what to focus on that week.",
        "trigger": {"type": "calendar", "frequency": "weekly", "days_of_week": ["monday"], "time_of_day": "08:00"},
        "tasks": [{
            "title": "Weekly focus", "instructions": INSTRUCTIONS,
            "runner": {"type": "agent", "agent_ref": _handle(planning, "agents", "Mail helper")},
        }],
        "alerts": {"mode": "every_run", "severity": "info"},
        "run_as": "self",
    }


def _plan(monkeypatch, planning):
    """The real planner, answering with one scripted plan: this week's answer and the proposal."""
    record = _record()
    # The planner's scripted client applies to planning only; the answer step uses the harness's client.
    with monkeypatch.context() as scoped:
        kind, plan = _plan_request(
            scoped, planning, [_raw_plan([ANSWER, _propose(_blueprint(planning), task_actions=[["email"]])])], record,
        )
    assert kind == "plan"
    assert len(record.calls) == 1
    return plan


def _execute(monkeypatch, plan, planning):
    """Run the plan through the real executor, with the real workflow_propose adapter and dry run."""
    env = HarnessEnvironment(monkeypatch)
    env.settings.update(deepcopy(AGENT_SETTINGS))
    workflows = WorkflowStore("user_id")
    personal = importlib.import_module("functions_personal_workflows")
    for module in (importlib.import_module("config"), personal):
        monkeypatch.setattr(module, "cosmos_personal_workflows_container", workflows)
    # The agent reads a save would make, answered from the planning context's agent records.
    monkeypatch.setattr(personal, "get_personal_agents", lambda user_id: _personal_agents())
    monkeypatch.setattr(personal, "get_global_agents", _global_agents)
    real_normalize = env.schema.normalize_plan

    def normalize(raw, *args, **kwargs):
        # The harness creates the run from the planned steps, offering only its own capabilities.
        raw = {**raw, "deliverables": deepcopy(plan["deliverables"])}
        kwargs["available_capability_ids"] = [*(kwargs.get("available_capability_ids") or ()), "workflow_propose"]
        return real_normalize(raw, *args, **kwargs)

    monkeypatch.setattr(env.schema, "normalize_plan", normalize)
    env.create(
        deepcopy(plan["steps"]), replies=[PREVIEW], final_response=deepcopy(plan["final_response"]),
        workflow_planning=planning, time_zone=ZONE,
    )
    execution = env.prepare()
    progress = []
    try:
        frames = decoded_frames(execution.execute(emit=progress.append))
    finally:
        execution.close()
    return env, workflows, frames, decoded_frames(progress)


def _routes(modules, monkeypatch, env):  # noqa: F811
    """The production proposal routes over the executor's stores, signed in as the requester."""
    proposals = importlib.import_module("functions_orchestration_workflow_proposals")
    record = SimpleNamespace(created=[], connections=[])

    def connected(user_id, tenant_id):
        record.connections.append(user_id)
        return True

    monkeypatch.setattr(modules.auth, "check_user_access_status", lambda user_id: (True, None))
    monkeypatch.setattr(modules.route, "cosmos_conversations_container", env.conversations)
    monkeypatch.setattr(modules.route, "get_settings", lambda: deepcopy(env.settings))
    monkeypatch.setattr(modules.route, "log_workflow_creation", lambda **kwargs: record.created.append(kwargs))
    monkeypatch.setattr(proposals, "_m365_connected", connected)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="workflow-proposal-done-when")
    blueprint = Blueprint("backend_orchestration", __name__)
    blueprint.before_request(modules.auth.user_required_blueprint())
    modules.route.register_route_backend_orchestration(blueprint)
    app.register_blueprint(blueprint)
    ow = importlib.import_module("functions_orchestration_workflows")
    h = SimpleNamespace(app=app, client=Client(app, Response), proposal_id=ow.workflow_proposal_id(RUN, STEP))
    login(h)
    return h, record


def _only(response):
    assert response.status_code == 200, response.get_data(as_text=True)
    listed = response.get_json()["proposals"]
    assert len(listed) == 1
    return listed[0]


def test_version_includes_the_done_when():
    assert_app_version_at_least("0.261.207")


def test_a_monday_email_request_becomes_a_monday_workflow_once_approved(modules, wf, monkeypatch):  # noqa: F811
    drafts = importlib.import_module("functions_workflow_drafts")
    personal = importlib.import_module("functions_personal_workflows")
    planning = _build(wf, [])

    # The plan: this week's answer now, and a proposal for the Mondays to come.
    plan = _plan(monkeypatch, planning)
    assert [step["capability_id"] for step in plan["steps"]] == ["compose", "workflow_propose"]
    assert sorted(entry["kind"] for entry in plan["deliverables"]) == ["answer", "workflow"]
    planned = _step(plan, STEP)["arguments"]["blueprint"]
    assert planned["trigger"] == {"type": "calendar", **{k: v for k, v in WEEKLY_MONDAY.items() if k != "kind"}}

    # The executor answers and describes the proposal, and creates nothing.
    env, workflows, frames, streamed = _execute(monkeypatch, plan, planning)
    run = env.read()
    assert run["status"] == "completed", [
        (entry.get("step_id"), entry.get("status"), entry.get("failure")) for entry in run.get("execution_steps") or ()
    ]
    step = env.steps.read_item(f"{RUN}:{STEP}", RUN)
    sidecar = step["workflow_proposal"]
    assert (sidecar["status"], sidecar["reason"], sidecar["error_codes"]) == ("ready", None, [])
    assert sidecar["handles"]["agents"] == {
        _handle(planning, "agents", "Mail helper"): {"id": PERSONAL_AGENT_ID, "name": "mail_helper", "is_global": False},
    }
    assert workflows.items == {}
    answer = json.dumps(env.assistant_messages(), default=str)
    assert PREVIEW in answer
    # Only the card discloses the proposal: the stream, the step list and the message carry none of it.
    step_event = importlib.import_module("functions_orchestration_events").EVENT_TYPE_STEP
    assert any(frame.get("type") == step_event and frame.get("step_id") == STEP for frame in streamed)
    public = importlib.import_module("functions_orchestration_runs").list_run_steps(
        RUN, user_id=OWNER, conversation_id=CONVERSATION,
    )
    assert_nothing_disclosed((frames, streamed, public, env.assistant_messages()), sidecar, INSTRUCTIONS)

    # The requester's card: pending, with the full instructions and the Microsoft 365 need.
    h, record = _routes(modules, monkeypatch, env)
    workflow_id = drafts.orchestration_workflow_id(OWNER, h.proposal_id)
    shown = _only(status(h, run_id=RUN, conversation_id=CONVERSATION))
    assert shown["proposal_id"] == h.proposal_id and shown["state"] == "pending"
    assert shown["actions"] == {"accept": True, "edit": True, "deny": True, "create_again": False,
                                "open_workflow": False}
    summary = shown["summary"]
    assert (summary["trigger_type"], summary["schedule_label"], summary["time_zone"]) == (
        "calendar", "Mondays 08:00 America/New_York", ZONE,
    )
    assert [task["instructions"] for task in summary["tasks"]] == [INSTRUCTIONS]
    assert summary["tasks"][0]["agent_name"] == "Mail helper"
    assert shown["m365"]["required"] is True and shown["m365"]["run_as"] == "self"
    assert shown["m365"]["connected"] is True and shown["m365"]["approval_state"] is None

    # Create & start stores one enabled Monday 08:00 workflow in the request's zone.
    created = accept(h, run_id=RUN, conversation_id=CONVERSATION, mode="enabled")
    assert created.status_code == 201, created.get_data(as_text=True)
    body = created.get_json()
    assert body["state"] == "created_enabled" and body["created"] is True
    assert body["workflow"] == {"id": workflow_id, "name": NAME, "is_enabled": True}
    assert list(workflows.items) == [(OWNER, workflow_id)]
    workflow = workflows.items[(OWNER, workflow_id)]
    assert workflow["is_enabled"] is True and workflow["durable_execution"] is True
    assert workflow["trigger_type"] == "interval"
    assert workflow["schedule"] == {**WEEKLY_MONDAY, "day_of_month": None}
    assert workflow["tasks"][0]["instructions"] == INSTRUCTIONS
    assert workflow["tasks"][0]["runner"]["selected_agent"]["id"] == PERSONAL_AGENT_ID
    assert workflow["m365_run_as_user_id"] == OWNER and workflow["m365_binding_approval_id"] is None
    assert workflow["origin"]["source"] == "orchestration" and workflow["origin"]["proposal_id"] == h.proposal_id
    assert workflow["origin"]["orchestration_run_id"] == RUN and workflow["origin"]["edited"] is False

    # The digest reaches the notification bell and never opens a pop-up.
    assert (workflow["alert_mode"], workflow["alert_priority"]) == ("rules", "none")
    rules = [
        (rule["name"], rule["severity"], rule["delivery"], rule["condition"]["statuses"])
        for rule in workflow["alert_rules"]
    ]
    assert rules == [
        ("Run completed", "info", "notify_only", ["completed"]),
        ("Run had errors", "low", "notify_only", ["failed", "completed_with_task_errors"]),
    ]
    assert len(record.created) == 1 and record.created[0]["workflow_id"] == workflow_id

    # Its next run after a Sunday is Monday 08:00 in New York, across the clock change too.
    first = datetime.fromisoformat(workflow["next_run_at"]).astimezone(ZoneInfo(ZONE))
    assert (first.strftime("%A"), first.strftime("%H:%M")) == ("Monday", "08:00")
    for sunday, monday in NEXT_RUNS:
        next_run = personal.compute_next_run_at(workflow, from_time=sunday)
        assert datetime.fromisoformat(next_run) == monday, (sunday, next_run)

    # Accepting again returns the same workflow; denying it now is refused.
    again = accept(h, run_id=RUN, conversation_id=CONVERSATION, mode="enabled")
    assert again.status_code == 200, again.get_data(as_text=True)
    assert again.get_json()["workflow"]["id"] == workflow_id and again.get_json()["created"] is False
    refused = deny(h, run_id=RUN, conversation_id=CONVERSATION)
    assert refused.status_code == 409 and code(refused) == "proposal_accepted"
    assert list(workflows.items) == [(OWNER, workflow_id)] and len(record.created) == 1

    shown = _only(status(h, run_id=RUN, conversation_id=CONVERSATION))
    assert shown["state"] == "created_enabled"
    assert shown["workflow"] == {"id": workflow_id, "name": NAME, "is_enabled": True}
    assert shown["actions"] == {"accept": False, "edit": False, "deny": False, "create_again": False,
                                "open_workflow": True}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
