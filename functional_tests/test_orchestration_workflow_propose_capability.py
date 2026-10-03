#!/usr/bin/env python3
# test_orchestration_workflow_propose_capability.py
"""
Functional test for the workflow_propose orchestration capability.
Version: 0.261.220
Implemented in: 0.261.207
Merge tasks added in: 0.261.220

This test ensures that chat orchestration offers workflow_propose only when workflow proposals
are turned on and available to the requester, and checks each proposal against the draft rules
and the request's handle catalog while a plan is validated. A rejected proposal is repaired
once; after that it is dropped with every binding to it, so the rest of the plan still runs.
The step runs as a write-free dry run. Its server-only sidecar describes the proposal for the
approval card without the task instructions, keeps its id across recovery and retries, and is
never streamed, listed or offered to a later plan. A proposed merge task is checked against the
merge rules when planned and described as a code merge that needs no model.
"""

import ast
import importlib
import json
from copy import copy, deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_planning_context import (  # noqa: F401
    AGENT_SETTINGS,
    OWNER,
    PERSONAL_AGENT_ID,
    PRIVATE,
    RAW_IDS,
    SETTING,
    SOURCE_ID,
    WATCHER_WORKFLOW_ID,
    WEEKLY_WORKFLOW_ID,
    _build,
    wf,
)
from test_orchestration_workflow_setting_off_golden import (
    ACTIONS,
    AGENTS,
    BASE_SETTINGS,
    CANDIDATES,
    IDENTITY,
    MESSAGE,
    _binding,
    _Completions,
)
from test_support.orchestration_harness_execution import (
    HarnessEnvironment,
    compose_step,
    decoded_frames,
    input_binding,
)
from test_support.versioning import assert_app_version_at_least


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
ZONE = "America/New_York"
CREATED_AT = datetime(2026, 9, 29, 12, 19, tzinfo=timezone.utc)
INSTRUCTIONS = "SECRET_INSTRUCTIONS: read my email and list what needs my attention."
UNKNOWN_AGENT = "agent-unknown-abc123"
WEEKLY_TRIGGER = {"type": "calendar", "frequency": "weekly", "days_of_week": ["monday"], "time_of_day": "08:00"}
DELIVERABLES = [
    {"id": "answer", "kind": "answer", "requested": "explicit", "status": "planned",
     "description": "This week's priorities."},
    {"id": "weekly_review", "kind": "workflow", "requested": "explicit", "status": "planned",
     "description": "A Monday email review."},
]
ANSWER = {
    "step_id": "answer", "capability_id": "compose",
    "arguments": {"instruction": "List what to focus on this week.", "knowledge_basis": "general_knowledge"},
    "inputs": {}, "outputs": [{"name": "answer", "kind": "markdown-v1"}],
}
WORKFLOW_SETTINGS = {SETTING: True, "allow_user_workflows": True, "require_member_of_workflow_user": False}
PRODUCER = SimpleNamespace(run_id="run-1", step_id="propose", conversation_id="conversation-1")
EDIT_FAILURE = "The requested change could not be planned. Your previous plan is unchanged."


@pytest.fixture
def ow(modules):
    return importlib.import_module("functions_orchestration_workflows")


@pytest.fixture
def schema(modules):
    return importlib.import_module("functions_orchestration_schema")


@pytest.fixture
def registry(modules):
    return importlib.import_module("functions_orchestration_registry")


@pytest.fixture
def planner(modules):
    return importlib.import_module("functions_orchestration_planner")


@pytest.fixture
def planning(wf):
    return _build(wf, [])


def _handle(planning, kind, name):
    return next(entry["handle"] for entry in planning["catalog"][kind] if entry["name"] == name)


def _task(agent_ref, title="Review email"):
    return {"title": title, "instructions": INSTRUCTIONS, "runner": {"type": "agent", "agent_ref": agent_ref}}


def _blueprint(planning, **changes):
    blueprint = {
        "name": "Monday email review",
        "trigger": deepcopy(WEEKLY_TRIGGER),
        "tasks": [_task(_handle(planning, "agents", "Mail helper"))],
        "run_as": "self",
    }
    blueprint.update(deepcopy(changes))
    return blueprint


def _propose(blueprint, task_actions=None, **extra):
    return {
        "step_id": "propose", "capability_id": "workflow_propose",
        "arguments": {
            "blueprint": deepcopy(blueprint),
            "task_actions": deepcopy([["email"]] if task_actions is None else task_actions),
        },
        "inputs": {}, "outputs": [{"name": "proposal", "kind": "structured-v1"}],
        **deepcopy(extra),
    }


def _raw_plan(steps, final="answer", deliverables=None):
    raw = {
        "kind": "plan", "intent": {"summary": "Weekly priorities and a Monday email review."},
        "deliverables": deepcopy(DELIVERABLES if deliverables is None else deliverables),
        "steps": deepcopy(steps),
    }
    if final is not None:
        raw["final_response"] = input_binding(final) if isinstance(final, str) else deepcopy(final)
    return raw


def _normalize(schema, planning, steps, final="answer", *, settings=None):
    return schema.normalize_plan(
        _raw_plan(steps, final), "conversation-1", OWNER, settings=deepcopy(settings or AGENT_SETTINGS),
        contract_version=2, available_capability_ids=["compose", "workflow_propose"],
        workflow_planning=planning,
    )


def _rejection(schema, planning, steps, final="answer"):
    with pytest.raises(schema.PlanValidationError) as caught:
        _normalize(schema, planning, steps, final)
    return caught.value


def _step(plan, step_id):
    return next(step for step in plan["steps"] if step["step_id"] == step_id)


def _workflow_deliverable(plan):
    return next(entry for entry in plan["deliverables"] if entry["kind"] == "workflow")


def _catalog_text(planning):
    """Every name and handle in the planning catalog; none of it may reach a log."""
    entries = [entry for kind in planning["catalog"].values() for entry in kind]
    return [entry["name"] for entry in entries] + [entry["handle"] for entry in entries]


def _assert_logs_carry_codes_only(logs, planning):
    text = json.dumps(logs, default=str, ensure_ascii=False)
    for secret in (INSTRUCTIONS, "Monday email review", UNKNOWN_AGENT, *_catalog_text(planning), *RAW_IDS):
        assert secret not in text, secret


def _record():
    return SimpleNamespace(calls=[], logs=[])


def _plan_request(monkeypatch, planning, replies, record, *, edit_context=None):
    """Plan one request through the real planner with scripted planner replies."""
    context_module = importlib.import_module("functions_orchestration_context")
    planner = importlib.import_module("functions_orchestration_planner")
    services = importlib.import_module("functions_orchestration_services")
    request_context = context_module.build_capability_request_context(
        OWNER, deepcopy(IDENTITY), MESSAGE, deepcopy(AGENTS), deepcopy(ACTIONS), allowed_user_urls=[],
        native_bridge_for_step=_binding, external_source_admission=_binding,
        external_source_authorizer=_binding, external_source_preflight=_binding,
        capture_external_source_configuration=_binding,
    )
    request_context["workflow_planning"] = planning
    planner_context = context_module.build_planner_context(
        MESSAGE, candidates=deepcopy(CANDIDATES), seeds={}, ledger=None,
        signals=context_module.build_conversation_signals([], MESSAGE), agents=deepcopy(AGENTS),
        original_message=MESSAGE,
        request_resolution={"relationship": "new_topic", "resolved_message": MESSAGE},
        actions=deepcopy(ACTIONS), answered_questions=[], memory_context=None,
    )
    planner_context["export_catalog"] = []
    client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions(deepcopy(replies), record.calls)))
    monkeypatch.setattr(planner, "resolve_planner_client", lambda _settings: (client, "deployment"))
    monkeypatch.setattr(
        planner, "log_event",
        lambda message, *args, **kwargs: record.logs.append((message, deepcopy(kwargs.get("extra")))),
    )
    return planner.plan_request(
        MESSAGE, planner_context, "conversation", OWNER, settings={**BASE_SETTINGS, SETTING: True},
        authorized_document_ids=["document-record-1"], revision=0, allow_elicitation=True, turn_id="turn",
        seeds={}, document_labels={"document-record-1": "Weekly priorities.docx"},
        request_context=request_context, planner_model=None, existing_results={},
        composition_profiles=services.composition_profiles(), export_catalog=[], edit_context=edit_context,
    )


def _describe(ow, planning, monkeypatch, blueprint, *, task_actions=None, outcome=None, context=None):
    """Build a proposal with a recorded dry run. Returns ``(sidecar, card, dry runs)``."""
    calls = []

    def dry_run(user_id, candidate, handles, **kwargs):
        calls.append({"user_id": user_id, "blueprint": deepcopy(candidate), "handles": deepcopy(handles),
                      **deepcopy(kwargs)})
        if isinstance(outcome, Exception):
            raise outcome
        return deepcopy(outcome) if outcome is not None else {"ok": True, "workflow": {}, "errors": []}

    monkeypatch.setattr(ow, "dry_run_workflow_blueprint", dry_run)
    step = {"step_id": "propose", "arguments": {
        "blueprint": deepcopy(blueprint), "task_actions": deepcopy([["email"]] if task_actions is None else task_actions),
    }}
    context = context or SimpleNamespace(
        workflow_planning=planning, time_zone=ZONE, user_email="owner@example.com", user_roles=["User"],
    )
    sidecar, card = ow.build_workflow_proposal(
        step, context, settings=deepcopy(AGENT_SETTINGS), user_id=OWNER, producer=PRODUCER, created_at=CREATED_AT,
    )
    return sidecar, card, calls


def test_version_includes_the_workflow_propose_capability():
    assert_app_version_at_least("0.261.207")


# ---------------------------------------------------------------------------
# The capability and when it is offered
# ---------------------------------------------------------------------------

def test_the_capability_is_a_low_cost_reason_step_with_one_proposal_output(modules, registry):
    adapters = importlib.import_module("functions_orchestration_adapters")
    capability = registry.get_capability("workflow_propose", contract_version=2)
    assert capability["role"] == "reason" and capability["cost_class"] == "low"
    assert capability["label"] == "Propose workflow" and capability["max_per_plan"] == 1
    assert capability["result_outputs"] == {"proposal": "structured-v1"}
    assert capability["result_input_kinds"] == {} and capability["partial_inputs_supported"] is False
    assert capability["settings_gates"] == ("enable_chat_orchestration", "allow_user_workflows", SETTING)
    assert capability["dormant_unless_setting"] == SETTING
    assert capability["inputs"]["required"] == ["blueprint"]
    kinds = capability["inputs"]["properties"]["task_actions"]["items"]["items"]["enum"]
    assert kinds == list(registry.WORKFLOW_TASK_ACTION_KINDS)
    assert capability["inputs"]["properties"]["task_actions"]["maxItems"] == registry.WORKFLOW_PROPOSAL_MAX_TASKS
    assert adapters.ADAPTER_REGISTRY["workflow_propose"] is adapters.run_workflow_propose


def _available(registry, settings, request_context):
    unavailable = {}
    ids = [
        capability["id"] for capability in registry.resolve_available_capabilities(
            settings, request_context=request_context, candidate_ids=["workflow_propose"], unavailable=unavailable,
        )
    ]
    return ids, unavailable


@pytest.mark.parametrize("value", ["missing", False, "true", 1, None])
def test_the_capability_is_dormant_until_the_setting_is_exactly_true(registry, planning, value):
    settings = deepcopy(AGENT_SETTINGS)
    if value == "missing":
        settings.pop(SETTING)
    else:
        settings[SETTING] = value
    ids, unavailable = _available(registry, settings, {"user_roles": ["User"], "workflow_planning": planning})
    # Dormant: skipped before every other check, with no reason the planner could be told.
    assert ids == [] and unavailable == {}
    deployment = registry.resolve_available_capability_ids(settings, candidate_ids=["workflow_propose"])
    assert deployment == []


def test_a_ready_private_request_may_propose_a_workflow(registry, planning):
    ids, unavailable = _available(registry, AGENT_SETTINGS, {"user_roles": ["User"], "workflow_planning": planning})
    assert ids == ["workflow_propose"] and unavailable == {}
    # Without a request, the answer describes the deployment for the admin surface.
    deployment = registry.resolve_available_capability_ids(AGENT_SETTINGS, candidate_ids=["workflow_propose"])
    assert deployment == ["workflow_propose"]


def _fail_read(*args):
    raise RuntimeError("storage failed")


def _unavailable_case(wf, case):
    settings, roles, planning = deepcopy(AGENT_SETTINGS), ["User"], _build(wf, [])
    if case == "shared":
        planning = _build(wf, [], conversation={**PRIVATE, "chat_type": "personal_multi_user"})
    elif case == "quota":
        settings["chat_orchestration_max_workflows_per_user"] = 2
        planning = _build(wf, [], settings, quota_count=lambda user_id: 2)
    elif case == "no_context":
        planning = None
    elif case == "failed_read":
        planning = _build(wf, [], sources=_fail_read)
    elif case == "role":
        settings["require_member_of_workflow_user"] = True
    elif case == "workflows_off":
        settings["allow_user_workflows"] = False
    elif case == "allowlist":
        settings["chat_orchestration_enabled_capabilities"] = ["compose"]
    context = {"user_roles": roles}
    if planning is not None:
        context["workflow_planning"] = planning
    return settings, context


@pytest.mark.parametrize(("case", "reason"), [
    ("shared", "workflow_shared_conversation"),
    ("quota", "workflow_quota_reached"),
    ("no_context", "workflow_context_unavailable"),
    ("failed_read", "workflow_context_unavailable"),
    ("role", "workflow_role_required"),
    ("workflows_off", "feature_disabled"),
    ("allowlist", "not_enabled_for_orchestration"),
])
def test_an_unavailable_request_records_one_closed_reason(registry, wf, case, reason):
    settings, context = _unavailable_case(wf, case)
    ids, unavailable = _available(registry, settings, context)
    assert ids == [] and unavailable == {"workflow_propose": reason}


def test_the_workflow_user_role_and_an_allowlist_that_names_it_admit_the_capability(registry, planning):
    settings = {
        **AGENT_SETTINGS, "require_member_of_workflow_user": True,
        "chat_orchestration_enabled_capabilities": ["compose", "workflow_propose"],
    }
    ids, unavailable = _available(registry, settings, {"user_roles": ["User", "WorkflowUser"], "workflow_planning": planning})
    assert ids == ["workflow_propose"] and unavailable == {}


def test_a_failing_access_check_never_raises_and_logs_only_the_error_type(registry, wf, planning, monkeypatch):
    logged = []
    monkeypatch.setattr(registry, "log_event", lambda message, **kwargs: logged.append((message, kwargs)))

    def fail(*args, **kwargs):
        raise RuntimeError(f"catalog text {INSTRUCTIONS}")

    monkeypatch.setattr(wf, "workflow_planning_unavailable_reason", fail)
    ids, unavailable = _available(registry, AGENT_SETTINGS, {"user_roles": ["User"], "workflow_planning": planning})
    assert ids == [] and unavailable == {"workflow_propose": "workflow_context_unavailable"}
    assert logged and logged[0][1]["extra"] == {"reason": "workflow_context_unavailable", "error_type": "RuntimeError"}
    assert INSTRUCTIONS not in json.dumps(logged, default=str)


# ---------------------------------------------------------------------------
# Plan checks
# ---------------------------------------------------------------------------

def test_a_valid_proposal_takes_the_request_zone_and_delivers_the_workflow(schema, planning):
    plan = _normalize(schema, planning, [ANSWER, _propose(_blueprint(planning))])
    step = _step(plan, "propose")
    assert (step["role"], step["estimated_cost"], step["title"]) == ("reason", "low", "Propose workflow")
    assert step["delivers"] == ["weekly_review"]
    assert step["arguments"]["blueprint"]["trigger"]["timezone"] == ZONE
    assert step["arguments"]["blueprint"]["tasks"][0]["instructions"] == INSTRUCTIONS
    assert step["arguments"]["task_actions"] == [["email"]]
    assert plan["final_response"]["step_id"] == "answer"


def test_the_zone_comes_from_the_request_unless_the_blueprint_names_one(schema, wf, planning):
    tokyo = _build(wf, [], time_zone="Asia/Tokyo")
    plan = _normalize(schema, tokyo, [ANSWER, _propose(_blueprint(tokyo))])
    assert _step(plan, "propose")["arguments"]["blueprint"]["trigger"]["timezone"] == "Asia/Tokyo"
    explicit = _blueprint(planning, trigger={**WEEKLY_TRIGGER, "timezone": "Europe/Paris"})
    plan = _normalize(schema, planning, [ANSWER, _propose(explicit)])
    assert _step(plan, "propose")["arguments"]["blueprint"]["trigger"]["timezone"] == "Europe/Paris"
    watcher = _blueprint(planning, trigger={
        "type": "file_sync", "source_ids": [_handle(planning, "sources", "Contracts folder")],
        "schedule": {"kind": "calendar", "frequency": "daily", "time_of_day": "07:30"},
    })
    plan = _normalize(schema, planning, [ANSWER, _propose(watcher)])
    assert _step(plan, "propose")["arguments"]["blueprint"]["trigger"]["schedule"]["timezone"] == ZONE


@pytest.mark.parametrize("extra", [
    {"inputs": {"notes": {"binding": input_binding("answer")}}},
    {"depends_on": ["answer"]},
])
def test_a_proposal_is_written_from_the_request_alone(schema, planning, extra):
    error = _rejection(schema, planning, [ANSWER, _propose(_blueprint(planning), **extra)])
    assert (error.code, error.rule) == ("workflow_blueprint_invalid", "workflow_static_input")


@pytest.mark.parametrize("agent_ref", [UNKNOWN_AGENT, "agent-mail-helper", PERSONAL_AGENT_ID])
def test_a_proposal_names_only_offered_handles_and_never_repeats_them(schema, planning, agent_ref):
    error = _rejection(schema, planning, [ANSWER, _propose(_blueprint(planning, tasks=[_task(agent_ref)]))])
    assert (error.code, error.rule) == ("workflow_blueprint_invalid", "reference_unknown")
    assert "/tasks/0/runner/agent_ref" in str(error)
    assert agent_ref not in str(error) and INSTRUCTIONS not in str(error)


def test_task_actions_list_known_action_kinds_for_every_task(schema, planning):
    mismatch = _rejection(schema, planning, [ANSWER, _propose(_blueprint(planning), task_actions=[["email"], []])])
    assert (mismatch.code, mismatch.rule) == ("workflow_blueprint_invalid", "task_actions_invalid")
    unknown = _rejection(schema, planning, [ANSWER, _propose(_blueprint(planning), task_actions=[["fax"]])])
    assert unknown.code == "plan_invalid"


def test_a_task_runs_on_an_offered_agent_that_has_its_actions(schema, planning):
    researcher = _handle(planning, "agents", "Researcher")
    error = _rejection(schema, planning, [ANSWER, _propose(_blueprint(planning), task_actions=[["mcp"]])])
    assert (error.code, error.rule) == ("workflow_blueprint_invalid", "agent_capability_mismatch")
    assert researcher in str(error)
    # No offered agent has both kinds, so the plan stands and the card explains it instead.
    plan = _normalize(schema, planning, [ANSWER, _propose(_blueprint(planning), task_actions=[["email", "mcp"]])])
    assert _step(plan, "propose")["arguments"]["task_actions"] == [["email", "mcp"]]


def test_a_microsoft_365_agent_runs_as_the_user(schema, planning):
    error = _rejection(schema, planning, [ANSWER, _propose(_blueprint(planning, run_as="none"))])
    assert (error.code, error.rule) == ("workflow_blueprint_invalid", "run_as_required")
    researcher = _blueprint(planning, run_as="none", tasks=[_task(_handle(planning, "agents", "Researcher"))])
    plan = _normalize(schema, planning, [ANSWER, _propose(researcher, task_actions=[["mcp"]])])
    assert _step(plan, "propose")["arguments"]["blueprint"]["run_as"] == "none"


def test_the_draft_rules_apply_to_every_proposal(schema, planning):
    fast = _blueprint(planning, trigger={"type": "interval", "unit": "minutes", "value": 30})
    error = _rejection(schema, planning, [ANSWER, _propose(fast)])
    assert (error.code, error.rule) == ("workflow_blueprint_invalid", "cadence_below_minimum")
    mail = _handle(planning, "agents", "Mail helper")
    many = _blueprint(planning, tasks=[_task(mail, f"Task {index}") for index in range(6)])
    error = _rejection(schema, planning, [ANSWER, _propose(many, task_actions=[["email"]] * 5)])
    assert (error.code, error.rule) == ("workflow_blueprint_invalid", "too_many_tasks")
    # The argument schema caps task_actions at the same limit, before the blueprint is read.
    error = _rejection(schema, planning, [ANSWER, _propose(many, task_actions=[["email"]] * 6)])
    assert error.code == "plan_invalid"


def test_a_merge_task_is_checked_when_planned_and_described_without_a_model(schema, ow, planning, monkeypatch):
    merge_task = {
        "title": "Merge the sales files", "instructions": "Merge every sales file into one workbook.",
        "merge": {"files": "all", "output_format": "xlsx"},
    }
    blueprint = _blueprint(planning, run_as="none", tasks=[merge_task], trigger={**WEEKLY_TRIGGER, "timezone": ZONE})
    plan = _normalize(schema, planning, [ANSWER, _propose(blueprint, task_actions=[[]])])
    assert _step(plan, "propose")["arguments"]["blueprint"]["tasks"][0]["merge"] == {
        "files": "all", "output_format": "xlsx",
    }

    document = _handle(planning, "documents", "Weekly priorities.docx")
    researcher = _handle(planning, "agents", "Researcher")
    for task, rule in (
        ({**merge_task, "merge": {"files": "inputs"}, "inputs": [document]}, "merge_inputs_required"),
        ({**merge_task, "merge": {"files": "changed"}}, "merge_trigger_required"),
        ({**merge_task, "runner": {"type": "agent", "agent_ref": researcher}}, "merge_runner_invalid"),
    ):
        error = _rejection(schema, planning, [ANSWER, _propose(
            _blueprint(planning, run_as="none", tasks=[task]), task_actions=[[]],
        )])
        assert (error.code, error.rule) == ("workflow_blueprint_invalid", rule)

    # A merge runs with code, so a default model that cannot run workflows does not block it.
    sidecar, _card, _calls = _describe(
        ow, {**planning, "default_model_valid": False}, monkeypatch, blueprint, task_actions=[[]],
    )
    assert sidecar["summary"]["tasks"] == [{
        "title": "Merge the sales files", "runner": "model", "agent_name": "", "action_kinds": [],
        "requested_actions": [], "inputs": [], "merge": {"files": "all", "output_format": "xlsx"},
    }]
    assert (sidecar["status"], sidecar["reason"]) == ("ready", None)


@pytest.mark.parametrize("wiring", ["input", "depends_on", "final_response"])
def test_no_other_step_or_final_response_may_read_the_proposal(schema, planning, wiring):
    answer, final = deepcopy(ANSWER), "answer"
    if wiring == "input":
        answer["inputs"] = {"proposal": {"binding": input_binding("propose", "proposal")}}
    elif wiring == "depends_on":
        answer["depends_on"] = ["propose"]
    else:
        final = input_binding("propose", "proposal")
    error = _rejection(schema, planning, [answer, _propose(_blueprint(planning))], final)
    assert (error.code, error.rule) == ("workflow_proposal_not_consumable", "workflow_proposal_consumed")


def test_one_plan_proposes_at_most_one_workflow(schema, planning):
    second = dict(_propose(_blueprint(planning, name="Second review")), step_id="propose_again")
    error = _rejection(schema, planning, [ANSWER, _propose(_blueprint(planning)), second])
    assert error.code == "result_step_limit"


def test_a_proposal_that_cannot_be_checked_gets_the_context_rule(schema, wf, ow, planning, monkeypatch):
    settings = {**AGENT_SETTINGS, "chat_orchestration_max_workflows_per_user": 2}
    at_cap = _build(wf, [], settings, quota_count=lambda user_id: 2)
    error = _rejection(schema, at_cap, [ANSWER, _propose(_blueprint(planning))])
    assert (error.code, error.rule) == ("workflow_blueprint_invalid", "workflow_context_unavailable")

    logged = []
    monkeypatch.setattr(ow, "log_event", lambda message, **kwargs: logged.append((message, kwargs)))

    def fail(*args, **kwargs):
        raise RuntimeError(f"storage failed: {INSTRUCTIONS}")

    monkeypatch.setattr(ow, "check_workflow_blueprint", fail)
    error = _rejection(schema, planning, [ANSWER, _propose(_blueprint(planning))])
    assert (error.code, error.rule) == ("workflow_blueprint_invalid", "workflow_context_unavailable")
    assert len(logged) == 1 and logged[0][1]["extra"]["error_type"] == "RuntimeError"
    assert logged[0][1]["extra"]["reason"] == "workflow_context_unavailable"
    assert INSTRUCTIONS not in json.dumps(logged, default=str)


def test_a_stored_proposal_is_rechecked_against_the_closed_schema_only(schema, ow, planning):
    plan = _normalize(schema, planning, [ANSWER, _propose(_blueprint(planning))])
    arguments = deepcopy(_step(plan, "propose")["arguments"])
    kept = ow.prepare_workflow_proposal_arguments({"inputs": {}}, arguments, settings={}, workflow_planning=None)
    assert kept is arguments
    broken = deepcopy(arguments)
    broken["blueprint"]["tasks"][0]["runner"] = {"type": "robot"}
    with pytest.raises(schema.PlanValidationError) as caught:
        ow.prepare_workflow_proposal_arguments({}, broken, settings={}, workflow_planning=None)
    assert caught.value.code == "workflow_blueprint_invalid"
    uneven = {**deepcopy(arguments), "task_actions": [["email"], ["email"]]}
    with pytest.raises(schema.PlanValidationError) as caught:
        ow.prepare_workflow_proposal_arguments({}, uneven, settings={}, workflow_planning=None)
    assert caught.value.rule == "task_actions_invalid"


# ---------------------------------------------------------------------------
# Planning: offer, repair, degrade
# ---------------------------------------------------------------------------

def test_the_planner_is_offered_the_capability_and_only_the_handle_catalog(monkeypatch, planning):
    record = _record()
    kind, plan = _plan_request(monkeypatch, planning, [_raw_plan([ANSWER, _propose(_blueprint(planning))])], record)
    assert kind == "plan"
    assert [step["capability_id"] for step in plan["steps"]] == ["compose", "workflow_propose"]
    assert _step(plan, "propose")["arguments"]["blueprint"]["trigger"]["timezone"] == ZONE
    assert len(record.calls) == 1
    system, user = record.calls[0][0]["content"], record.calls[0][1]["content"]
    assert "workflow_propose" in system and '"workflow_planning"' in user
    for raw in RAW_IDS:
        assert raw not in system and raw not in user
    _assert_logs_carry_codes_only(record.logs, planning)


def test_a_rejected_proposal_is_repaired_once_with_fixed_text(monkeypatch, planning):
    bad = _blueprint(planning, tasks=[_task(UNKNOWN_AGENT)])
    record = _record()
    kind, plan = _plan_request(monkeypatch, planning, [
        _raw_plan([ANSWER, _propose(bad)]), _raw_plan([ANSWER, _propose(_blueprint(planning))]),
    ], record)
    assert kind == "plan" and _step(plan, "propose")["capability_id"] == "workflow_propose"
    assert len(record.calls) == 2
    repair = record.calls[1][-1]["content"]
    assert repair.startswith("The server rejected the workflow proposal in that plan: ")
    assert "[reference_unknown] /tasks/0/runner/agent_ref" in repair
    assert UNKNOWN_AGENT not in repair and INSTRUCTIONS not in repair
    asked = [extra for message, extra in record.logs if "correct a rejected plan" in message]
    assert len(asked) == 1
    assert (asked[0]["validation_code"], asked[0]["validation_rule"]) == ("workflow_blueprint_invalid", "reference_unknown")
    _assert_logs_carry_codes_only(record.logs, planning)


def test_an_unrepaired_proposal_is_dropped_with_every_binding_to_it(modules, monkeypatch, planning):
    deliverables = importlib.import_module("functions_orchestration_deliverables")
    answer = dict(deepcopy(ANSWER), depends_on=["propose"],
                  inputs={"proposal": {"binding": input_binding("propose", "proposal")}})
    reply = _raw_plan([answer, _propose(_blueprint(planning, tasks=[_task(UNKNOWN_AGENT)]))])
    record = _record()
    kind, plan = _plan_request(monkeypatch, planning, [reply, reply], record)
    assert kind == "plan" and len(record.calls) == 2
    assert [step["step_id"] for step in plan["steps"]] == ["answer"]
    kept = plan["steps"][0]
    assert "propose" not in (kept.get("depends_on") or []) and "proposal" not in (kept.get("inputs") or {})
    assert '"propose"' not in json.dumps(plan)
    assert plan["final_response"]["step_id"] == "answer"
    workflow = _workflow_deliverable(plan)
    assert (workflow["status"], workflow["unavailable_reason"]) == ("unavailable", "workflow_draft_invalid")
    assert workflow["unavailable_message"] == deliverables.WORKFLOW_UNAVAILABLE_REASONS["workflow_draft_invalid"]
    dropped = [extra for message, extra in record.logs if "Planning without a workflow proposal" in message]
    assert len(dropped) == 1
    assert dropped[0]["reason"] == "workflow_proposal_dropped"
    assert dropped[0]["unavailable_reason"] == "workflow_draft_invalid"
    _assert_logs_carry_codes_only(record.logs, planning)


@pytest.mark.parametrize("shape", ["final_response", "proposal_only"])
def test_a_plan_left_with_nothing_to_answer_fails_with_fixed_text(monkeypatch, planner, planning, shape):
    bad = _propose(_blueprint(planning, tasks=[_task(UNKNOWN_AGENT)]))
    if shape == "final_response":
        reply = _raw_plan([ANSWER, bad], final=input_binding("propose", "proposal"))
    else:
        reply = _raw_plan([bad], final=None, deliverables=[DELIVERABLES[1]])
    record = _record()
    with pytest.raises(planner.PlannerError) as caught:
        _plan_request(monkeypatch, planning, [reply, reply], record)
    assert caught.value.reason == "invalid_plan_or_missing_requirement"
    assert caught.value.message == planner.WORKFLOW_FAILURE_MESSAGE
    assert len(record.calls) == 2
    _assert_logs_carry_codes_only(record.logs, planning)


def test_a_plan_edit_with_a_broken_proposal_keeps_the_previous_plan(monkeypatch, planner, planning):
    reply = dict(
        _raw_plan([ANSWER, _propose(_blueprint(planning, tasks=[_task(UNKNOWN_AGENT)]))]),
        revised_request="Also review my email every Monday.",
    )
    record = _record()
    with pytest.raises(planner.PlannerError) as caught:
        _plan_request(monkeypatch, planning, [reply, reply], record,
                      edit_context={"instruction": "Add a Monday review.", "current_plan": {}})
    assert caught.value.message == EDIT_FAILURE
    assert not any("Planning without a workflow proposal" in message for message, _extra in record.logs)


def test_a_proposal_check_that_cannot_run_plans_the_rest_without_it(modules, monkeypatch, ow, planning):
    deliverables = importlib.import_module("functions_orchestration_deliverables")
    record = _record()

    def fail(*args, **kwargs):
        raise RuntimeError(f"storage failed: {INSTRUCTIONS}")

    monkeypatch.setattr(ow, "check_workflow_blueprint", fail)
    monkeypatch.setattr(ow, "log_event", lambda message, **kwargs: record.logs.append((message, kwargs.get("extra"))))
    kind, plan = _plan_request(monkeypatch, planning, [_raw_plan([ANSWER, _propose(_blueprint(planning))])], record)
    # No repair round: nothing the planner writes can fix a check that could not run.
    assert kind == "plan" and len(record.calls) == 1
    assert [step["capability_id"] for step in plan["steps"]] == ["compose"]
    workflow = _workflow_deliverable(plan)
    assert (workflow["status"], workflow["unavailable_reason"]) == ("unavailable", "workflow_context_unavailable")
    assert workflow["unavailable_message"] == deliverables.WORKFLOW_UNAVAILABLE_REASONS["workflow_context_unavailable"]
    _assert_logs_carry_codes_only(record.logs, planning)


def test_a_proposal_step_the_drop_left_behind_is_still_refused(monkeypatch, planner, ow, planning):
    # The degraded plan is checked without workflow_propose, so a drop that missed the step cannot run it.
    monkeypatch.setattr(ow, "drop_workflow_proposals", lambda plan, truth, *, reason: (deepcopy(plan), deepcopy(truth)))
    reply = _raw_plan([ANSWER, _propose(_blueprint(planning, tasks=[_task(UNKNOWN_AGENT)]))])
    record = _record()
    with pytest.raises(planner.PlannerError) as caught:
        _plan_request(monkeypatch, planning, [reply, reply], record)
    assert caught.value.reason == "invalid_plan_or_missing_requirement"
    assert caught.value.message == planner.WORKFLOW_FAILURE_MESSAGE
    failed = [extra for message, extra in record.logs if "could not be planned" in message]
    assert [(extra["stage"], extra["validation_code"]) for extra in failed] == [
        ("plan_normalization", "capability_unavailable"),
    ]
    assert not any("Planning without a workflow proposal" in message for message, _extra in record.logs)


def test_dropping_a_proposal_removes_every_reference_and_copies_its_inputs(ow):
    plan = {
        "steps": [
            {"step_id": "propose", "capability_id": "workflow_propose", "delivers": ["weekly_review"]},
            {"step_id": "answer", "capability_id": "compose", "depends_on": ["propose", "search"],
             "inputs": {"proposal": {"binding": input_binding("propose", "proposal")},
                        "notes": {"binding": input_binding("search", "notes")}},
             "delivers": ["answer", "weekly_review"]},
        ],
        "deliverables": [
            {"id": "answer", "kind": "answer", "requested": "explicit", "status": "planned"},
            {"id": "weekly_review", "kind": "workflow", "requested": "explicit", "status": "planned",
             "unavailable_message": "planner text"},
            {"id": "maybe", "kind": "workflow", "requested": "implicit", "status": "planned"},
        ],
        "final_response": input_binding("propose", "proposal"),
    }
    availability = {"workflow": {"status": "available"}, "answer": {"status": "available"}}
    original_plan, original_availability = deepcopy(plan), deepcopy(availability)
    dropped, truth = ow.drop_workflow_proposals(plan, availability, reason="workflow_context_unavailable")
    assert plan == original_plan and availability == original_availability
    assert [step["step_id"] for step in dropped["steps"]] == ["answer"]
    answer = dropped["steps"][0]
    assert answer["depends_on"] == ["search"] and list(answer["inputs"]) == ["notes"]
    assert answer["delivers"] == ["answer"]
    assert "final_response" not in dropped
    assert dropped["deliverables"] == [
        {"id": "answer", "kind": "answer", "requested": "explicit", "status": "planned"},
        {"id": "weekly_review", "kind": "workflow", "requested": "explicit", "status": "unavailable",
         "unavailable_reason": "workflow_context_unavailable"},
    ]
    assert truth == {"workflow": {"status": "unavailable", "reason": "workflow_context_unavailable"},
                     "answer": {"status": "available"}}


# ---------------------------------------------------------------------------
# Describing a proposal
# ---------------------------------------------------------------------------

def test_the_proposal_describes_the_workflow_without_its_instructions(wf, ow, planning, monkeypatch):
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    document = _handle(planning, "documents", "Weekly priorities.docx")
    mail = _handle(planning, "agents", "Mail helper")
    blueprint = _blueprint(planning, trigger={**WEEKLY_TRIGGER, "timezone": ZONE})
    blueprint["tasks"][0]["inputs"] = [document]
    sidecar, card, calls = _describe(ow, planning, monkeypatch, blueprint)

    proposal_id = ow.workflow_proposal_id("run-1", "propose")
    handles = wf.workflow_draft_handles(planning)
    used = {"agents": {mail: handles["agents"][mail]}, "documents": {document: handles["documents"][document]},
            "sources": {}}
    assert set(sidecar) == {
        "version", "proposal_id", "origin_run_id", "step_id", "conversation_id", "requester_user_id",
        "created_at", "expires_at", "status", "reason", "error_codes", "blueprint_digest", "handles",
        "time_zone", "summary", "similar_workflows",
    }
    assert sidecar["proposal_id"] == proposal_id
    assert (sidecar["origin_run_id"], sidecar["step_id"], sidecar["conversation_id"]) == (
        "run-1", "propose", "conversation-1")
    assert sidecar["requester_user_id"] == OWNER
    assert sidecar["created_at"] == CREATED_AT.isoformat()
    assert sidecar["expires_at"] == (CREATED_AT + timedelta(days=14)).isoformat()
    assert (sidecar["status"], sidecar["reason"], sidecar["error_codes"]) == ("ready", None, [])
    assert sidecar["blueprint_digest"] == contracts.canonical_digest(blueprint)
    assert sidecar["handles"] == used and sidecar["time_zone"] == ZONE
    assert sidecar["summary"] == {
        "name": "Monday email review",
        "description": "",
        "trigger_type": "calendar",
        "schedule_label": "Mondays 08:00 America/New_York",
        "time_zone": ZONE,
        "runs_per_month": {"kind": "count", "value": 4},
        "tasks": [{
            "title": "Review email", "runner": "agent", "agent_name": "Mail helper",
            "action_kinds": ["email", "openapi"], "requested_actions": ["email"],
            "inputs": ["Weekly priorities.docx"],
        }],
        "file_sync_sources": [],
        "m365": {"sources": ["email", "calendar"], "can_send": True, "run_as": "self", "required": True},
        "alerts": {"mode": "every_run", "severity": "info"},
        "durable": True,
    }
    assert sidecar["similar_workflows"] == [{
        "workflow_id": WEEKLY_WORKFLOW_ID, "name": "Weekly mail review",
        "schedule_label": "Mondays 08:00 America/New_York", "why": ["same_schedule"],
    }]
    assert card == {
        "version": 1, "name": "Monday email review", "status": "ready", "reason": None,
        "schedule_label": "Mondays 08:00 America/New_York", "created_at": CREATED_AT.isoformat(),
    }
    text = json.dumps([sidecar, card], ensure_ascii=False)
    assert INSTRUCTIONS not in text

    assert len(calls) == 1
    call = calls[0]
    assert call["user_id"] == OWNER and call["blueprint"] == blueprint and call["handles"] == used
    assert call["origin"] == {
        "source": "orchestration", "conversation_id": "conversation-1", "orchestration_run_id": "run-1",
        "proposal_id": proposal_id, "created_at": CREATED_AT.isoformat(), "edited": False,
    }
    assert call["enabled"] is False and call["check_quota"] is True
    assert call["user_info"] == {"userId": OWNER, "email": "owner@example.com", "roles": ["User"]}
    assert call["settings"] == AGENT_SETTINGS


@pytest.mark.parametrize(("codes", "reason"), [
    (["quota_exceeded"], "quota_reached"),
    (["agent_unavailable"], "agent_unavailable"),
    (["file_sync_source_unavailable"], "file_sync_source_unavailable"),
    (["reference_unauthorized"], "reference_unavailable"),
    (["cadence_below_minimum"], "cadence_below_minimum"),
    (["workflows_unavailable", "quota_exceeded"], "workflows_unavailable"),
    (["workflow_conflict"], "proposal_unavailable"),
    ([], "proposal_unavailable"),
])
def test_a_blocked_proposal_is_still_described_with_one_reason(ow, planning, monkeypatch, codes, reason):
    outcome = {"ok": False, "workflow": None,
               "errors": [{"code": code, "message": "Fixed text.", "path": "/tasks"} for code in codes]}
    sidecar, card, _calls = _describe(ow, planning, monkeypatch, _blueprint(planning, trigger={**WEEKLY_TRIGGER, "timezone": ZONE}),
                                      outcome=outcome)
    assert (sidecar["status"], sidecar["reason"]) == ("unavailable", reason)
    assert sidecar["error_codes"] == (sorted(set(codes)) or ["blueprint_invalid"])
    assert (card["status"], card["reason"]) == ("unavailable", reason)
    assert sidecar["summary"]["name"] == "Monday email review"


def test_a_dry_run_that_fails_leaves_an_unavailable_proposal_and_logs_only_the_error_type(ow, planning, monkeypatch):
    logged = []
    monkeypatch.setattr(ow, "log_event", lambda message, **kwargs: logged.append((message, kwargs)))
    sidecar, _card, calls = _describe(ow, planning, monkeypatch, _blueprint(planning, trigger={**WEEKLY_TRIGGER, "timezone": ZONE}),
                                      outcome=RuntimeError(f"storage failed: {INSTRUCTIONS}"))
    assert len(calls) == 1
    assert (sidecar["status"], sidecar["reason"], sidecar["error_codes"]) == ("unavailable", "proposal_unavailable", [])
    assert logged and logged[0][1]["extra"]["error_type"] == "RuntimeError"
    assert INSTRUCTIONS not in json.dumps(logged, default=str)


def test_a_proposal_without_a_ready_context_is_unavailable_without_a_dry_run(ow, monkeypatch):
    context = SimpleNamespace(workflow_planning=None, time_zone=None, user_email=None, user_roles=None)
    blueprint = {"name": "Monday email review", "trigger": {**WEEKLY_TRIGGER, "timezone": ZONE},
                 "tasks": [_task("agent-mail-helper-a49ad7")], "run_as": "self"}
    sidecar, _card, calls = _describe(ow, {}, monkeypatch, blueprint, context=context)
    assert calls == []
    assert (sidecar["status"], sidecar["reason"]) == ("unavailable", "proposal_unavailable")
    assert sidecar["handles"] == {"agents": {}, "documents": {}, "sources": {}}
    assert sidecar["similar_workflows"] == [] and sidecar["time_zone"] == "UTC"


@pytest.mark.parametrize(("codes", "changes", "expected"), [
    ([], {}, None),
    (["quota_exceeded", "agent_unavailable"], {}, "quota_reached"),
    (["reference_unknown", "cadence_below_minimum"], {}, "reference_unavailable"),
    (["file_sync_source_unavailable", "reference_unauthorized"], {}, "file_sync_source_unavailable"),
    ([], {"task_actions": [["email", "mcp"]]}, "no_suitable_agent"),
    ([], {"model": True, "default_model_valid": False}, "model_unavailable"),
    ([], {"model": True, "default_model_valid": False, "task_actions": [["email"]]}, "model_unavailable"),
    (["quota_exceeded"], {"model": True, "default_model_valid": False}, "quota_reached"),
    ([], {"model": True}, None),
])
def test_the_first_reason_by_a_fixed_precedence_wins(ow, planning, codes, changes, expected):
    blueprint = _blueprint(planning)
    context = dict(planning)
    task_actions = changes.get("task_actions", [["email"]])
    if changes.get("model"):
        blueprint["tasks"] = [{"title": "Summarize", "instructions": INSTRUCTIONS, "runner": {"type": "model"}}]
        task_actions = changes.get("task_actions", [[]])
    if "default_model_valid" in changes:
        context["default_model_valid"] = changes["default_model_valid"]
    reason = ow.workflow_proposal_reason(codes, blueprint=blueprint, task_actions=task_actions, planning=context)
    assert reason == expected
    assert expected is None or expected in ow.WORKFLOW_PROPOSAL_REASONS


@pytest.mark.parametrize(("trigger_type", "schedule", "expected"), [
    ("interval", {"kind": "calendar", "frequency": "daily", "time_of_day": "08:00", "timezone": "UTC"},
     {"kind": "count", "value": 30}),
    ("interval", {"kind": "calendar", "frequency": "weekdays", "time_of_day": "08:00", "timezone": "UTC"},
     {"kind": "count", "value": 22}),
    ("interval", {"kind": "calendar", "frequency": "weekly", "days_of_week": ["monday", "thursday"],
                  "time_of_day": "08:00", "timezone": "UTC"}, {"kind": "count", "value": 9}),
    ("interval", {"kind": "calendar", "frequency": "monthly", "day_of_month": 1, "time_of_day": "08:00",
                  "timezone": "UTC"}, {"kind": "count", "value": 1}),
    ("interval", {"unit": "hours", "value": 2}, {"kind": "count", "value": 360}),
    ("interval", {"unit": "hours", "value": 24}, {"kind": "count", "value": 30}),
    ("interval", {"unit": "minutes", "value": 30}, {"kind": "count", "value": 1440}),
    ("file_sync", {"unit": "hours", "value": 1}, {"kind": "on_change", "value": None, "checks_per_month": 720}),
    ("manual", None, {"kind": "manual", "value": None}),
])
def test_runs_per_month_count_a_thirty_day_month(ow, trigger_type, schedule, expected):
    schedules = importlib.import_module("functions_workflow_schedules")
    normalized = schedules.normalize_workflow_schedule(schedule) if schedule else None
    runs = ow.workflow_proposal_runs_per_month(trigger_type, normalized)
    assert runs == expected


def test_a_blueprint_trigger_maps_to_the_stored_trigger_and_schedule(ow):
    calendar = ow.stored_workflow_trigger({**WEEKLY_TRIGGER, "timezone": ZONE})
    assert calendar == ("interval", {"kind": "calendar", "frequency": "weekly", "time_of_day": "08:00",
                                     "timezone": ZONE, "days_of_week": ["monday"]})
    watcher = ow.stored_workflow_trigger({"type": "file_sync", "source_ids": ["source-a"],
                                          "schedule": {"kind": "interval", "unit": "hours", "value": 1}})
    assert watcher == ("file_sync", {"unit": "hours", "value": 1})
    interval = ow.stored_workflow_trigger({"type": "interval", "unit": "hours", "value": 2})
    assert interval == ("interval", {"unit": "hours", "value": 2})
    for trigger in ({"type": "manual"}, None, {}):
        stored = ow.stored_workflow_trigger(trigger)
        assert stored == ("manual", None)


def test_a_file_sync_proposal_names_its_sources_and_the_workflow_already_watching_them(ow, planning, monkeypatch):
    source = _handle(planning, "sources", "Contracts folder")
    blueprint = {
        "name": "Watch contracts",
        "trigger": {"type": "file_sync", "source_ids": [source],
                    "schedule": {"kind": "interval", "unit": "hours", "value": 1}},
        "tasks": [{"title": "Summarize", "instructions": INSTRUCTIONS, "runner": {"type": "model"}}],
        "run_as": "none",
    }
    sidecar, card, _calls = _describe(ow, planning, monkeypatch, blueprint, task_actions=[[]])
    assert sidecar["status"] == "ready"
    assert sidecar["handles"] == {"agents": {}, "documents": {}, "sources": {
        source: {"scope_type": "personal", "scope_id": OWNER, "source_id": SOURCE_ID},
    }}
    summary = sidecar["summary"]
    assert summary["trigger_type"] == "file_sync" and summary["schedule_label"] == "Monitor File Sync every hour"
    assert summary["runs_per_month"] == {"kind": "on_change", "value": None, "checks_per_month": 720}
    assert summary["file_sync_sources"] == ["Contracts folder"]
    assert summary["m365"] == {"sources": [], "can_send": False, "run_as": "none", "required": False}
    assert summary["tasks"][0]["runner"] == "model" and summary["tasks"][0]["agent_name"] == ""
    assert sidecar["similar_workflows"] == [{
        "workflow_id": WATCHER_WORKFLOW_ID, "name": "Contract watcher",
        "schedule_label": "Monitor File Sync every hour", "why": ["same_sources", "same_schedule"],
    }]
    assert card["schedule_label"] == "Monitor File Sync every hour"


def test_at_most_three_similar_workflows_are_listed_most_reasons_first(ow):
    weekly = {"kind": "calendar", "frequency": "weekly", "days_of_week": ["monday"], "time_of_day": "08:00",
              "timezone": ZONE, "day_of_month": None}
    snapshots = {
        "workflow-0": {"name": "Other", "trigger_type": "interval", "schedule": weekly, "schedule_label": "Mondays"},
        "workflow-1": {"name": "Monday email review", "trigger_type": "manual", "schedule": None,
                       "schedule_label": "Manual"},
        "workflow-2": {"name": "Monday email review", "trigger_type": "interval", "schedule": weekly,
                       "schedule_label": "Mondays"},
        "workflow-3": {"name": "Unrelated", "trigger_type": "file_sync", "schedule": {"unit": "hours", "value": 1},
                       "schedule_label": "Hourly", "source_keys": ["personal:owner:elsewhere"]},
        "workflow-4": {"name": "Monday email reviews", "trigger_type": "interval", "schedule": weekly,
                       "schedule_label": "Mondays"},
        "workflow-5": {"name": "Monday email review", "trigger_type": "interval", "schedule": weekly,
                       "schedule_label": "Mondays"},
    }
    planning = {
        "catalog": {"workflows": [{"handle": handle} for handle in snapshots]},
        # workflow-5 has no stored record, so it can never be linked and is never listed.
        "handles": {"workflows": {f"workflow-{index}": {"id": f"id-{index}"} for index in range(5)}},
        "workflow_snapshots": snapshots,
    }
    matches = ow._similar_workflows(planning, name="Monday email review", trigger_type="interval",
                                    schedule=weekly, source_keys=[])
    assert [(match["workflow_id"], match["why"]) for match in matches] == [
        ("id-2", ["same_schedule", "similar_name"]),
        ("id-4", ["same_schedule", "similar_name"]),
        ("id-0", ["same_schedule"]),
    ]
    manual = ow._similar_workflows(planning, name="Monday email review", trigger_type="manual",
                                   schedule=None, source_keys=[])
    assert [(match["workflow_id"], match["why"]) for match in manual] == [
        ("id-1", ["similar_name"]), ("id-2", ["similar_name"]), ("id-4", ["similar_name"]),
    ]


# ---------------------------------------------------------------------------
# Running the step
# ---------------------------------------------------------------------------

def _harness(monkeypatch, ow, planning, steps, replies):
    env = HarnessEnvironment(monkeypatch)
    env.settings.update(WORKFLOW_SETTINGS)
    dry_runs, writes = [], []

    def dry_run(user_id, blueprint, handles, **kwargs):
        dry_runs.append({"user_id": user_id, "blueprint": deepcopy(blueprint), **deepcopy(kwargs)})
        return {"ok": True, "workflow": {"name": blueprint["name"]}, "errors": []}

    monkeypatch.setattr(ow, "dry_run_workflow_blueprint", dry_run)
    drafts = importlib.import_module("functions_workflow_drafts")
    for name in ("create_personal_workflow_from_blueprint", "create_personal_workflow_from_payload"):
        monkeypatch.setattr(drafts, name, lambda *args, _name=name, **kwargs: writes.append(_name))
    real_normalize = env.schema.normalize_plan

    def normalize(raw, *args, **kwargs):
        # The harness plans without deliverables and offers only its own capabilities.
        if "deliverables" not in raw:
            raw = {**raw, "deliverables": deepcopy(DELIVERABLES)}
        capability_ids = kwargs.get("available_capability_ids")
        if capability_ids is not None and "workflow_propose" not in capability_ids:
            kwargs["available_capability_ids"] = [*capability_ids, "workflow_propose"]
        return real_normalize(raw, *args, **kwargs)

    monkeypatch.setattr(env.schema, "normalize_plan", normalize)
    env.create(steps, replies=replies, final_response=input_binding("answer"), workflow_planning=planning,
               time_zone=ZONE)
    return env, dry_runs, writes


def _harness_proposal(planning):
    return _propose(_blueprint(planning, trigger={**WEEKLY_TRIGGER, "timezone": ZONE}))


def server_only_values(sidecar, instructions=INSTRUCTIONS):
    """What only the server may hold: the sidecar, its id and digest, the requester and the real ids behind handles."""
    real_ids = [entry["id"] for mapping in sidecar["handles"].values() for entry in mapping.values()]
    assert PERSONAL_AGENT_ID in real_ids
    return ["workflow_proposal", sidecar["proposal_id"], instructions, "requester_user_id", "blueprint_digest", *real_ids]


def assert_nothing_disclosed(surfaces, sidecar, instructions=INSTRUCTIONS):
    secrets = server_only_values(sidecar, instructions)
    for surface in surfaces:
        text = json.dumps(surface, default=str)
        for secret in secrets:
            assert secret not in text, secret


def test_the_step_keeps_its_description_on_the_server_and_retains_only_a_small_card(modules, wf, ow, monkeypatch):
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    events = importlib.import_module("functions_orchestration_events")
    runs = importlib.import_module("functions_orchestration_runs")
    services = importlib.import_module("functions_orchestration_services")
    planning = _build(wf, [])
    env, dry_runs, writes = _harness(monkeypatch, ow, planning, [compose_step("answer"), _harness_proposal(planning)],
                                     ["Your priorities."])
    execution = env.prepare()
    progress = []
    frames = decoded_frames(execution.execute(emit=progress.append))
    streamed = decoded_frames(progress)

    step = env.steps.read_item("run-1:propose", "run-1")
    sidecar = step["workflow_proposal"]
    assert step["status"] == "completed" and sidecar["status"] == "ready"
    assert sidecar["proposal_id"] == ow.workflow_proposal_id("run-1", "propose")
    assert writes == [] and len(dry_runs) == 1
    assert dry_runs[0]["origin"]["orchestration_run_id"] == "run-1"
    assert dry_runs[0]["origin"]["proposal_id"] == sidecar["proposal_id"]
    assert dry_runs[0]["blueprint"]["tasks"][0]["instructions"] == INSTRUCTIONS
    assert dry_runs[0]["enabled"] is False

    # The description never leaves the server: not streamed, listed or stored on the message.
    # The proposal step's own progress frames are streamed, so the stream checked here is real.
    assert any(frame.get("type") == events.EVENT_TYPE_STEP and frame.get("step_id") == "propose" for frame in streamed)
    public = runs.list_run_steps("run-1", user_id=OWNER, conversation_id="conversation-1")
    assert_nothing_disclosed((frames, streamed, public, env.assistant_messages()), sidecar)

    run = env.read()
    assert run["status"] == "completed"
    assert set(run["task_results"]) == {"answer", "propose"}
    task = contracts.TaskResult.from_dict(step["task_result"])
    results = env.services().results
    card = results.open_result(task.output("proposal"), allow_partial=False).read_value()
    assert card == {
        "version": 1, "name": "Monday email review", "status": "ready", "reason": None,
        "schedule_label": "Mondays 08:00 America/New_York", "created_at": sidecar["created_at"],
    }

    # A later plan is never offered the proposal as a saved result.
    found = services.discover_result_aliases([run], results)
    answer = contracts.TaskResult.from_dict(run["task_results"]["answer"])
    expected = sorted(json.dumps(ref.to_dict(), sort_keys=True) for ref in answer.outputs)
    offered = sorted(json.dumps(ref.to_dict(), sort_keys=True) for ref in found["aliases"].values())
    assert expected and offered == expected

    # A recovered step is described again with the same id, creation time and expiry.
    probe = copy(execution.context)
    probe.result_service = results
    plan_step = _step(run["plan"], "propose")
    rebuilt = ow.rebuild_workflow_proposal(plan_step, probe, settings=env.settings, user_id=OWNER, task=task)
    assert rebuilt == sidecar


def test_a_retried_run_reuses_the_proposal_it_already_made(modules, wf, ow, monkeypatch):
    planning = _build(wf, [])
    env, dry_runs, _writes = _harness(monkeypatch, ow, planning, [_harness_proposal(planning), compose_step("answer")],
                                      [RuntimeError("FIXTURE_FAILURE")])
    execution = env.prepare()
    try:
        failed = env.run_engine(execution)
    finally:
        execution.close()
    assert failed["status"] == "failed"
    parent = env.read()
    first = env.steps.read_item("run-1:propose", "run-1")
    assert first["status"] == "completed" and first["checkpoint_available"] is True

    def authorize():
        return env.bootstrap.read_owned_conversation(OWNER, "conversation-1")

    probe = copy(execution.context)
    probe.result_service = env.services().results
    child = env.recovery.prepare_retry(
        "run-1", OWNER,
        {"conversation_id": "conversation-1", "submission_id": "explicit-user-retry",
         "expected_version": parent["recovery_version"]},
        authorize=authorize, message_container=env.messages,
        validate=lambda current: env.recovery.validate_resume(
            current, probe, env.settings, authorize, source_run_id=current["id"],
        ),
    )
    assert child["time_zone"] == ZONE and "workflow_planning" in child
    services = env.services()
    claimed = env.revisions.claim_plan_run(
        child["id"], OWNER, "conversation-1", expected_version=child["edit_version"],
        result_alias_resolver=lambda current: env.service_bindings.admitted_result_aliases(current, services.results),
    )
    lease = env.recovery.ExecutionLease(claimed, authorize, message_container=env.messages)
    second = env.execution.prepare_harness_execution(claimed, settings=env.settings, lease=lease)
    env.replies.append("Your priorities.")
    try:
        done = env.run_engine(second)
    finally:
        second.close()
    assert done["status"] == "completed"
    again = env.steps.read_item(f"{child['id']}:propose", child["id"])
    assert again["status"] == "completed" and again["reused_from_run_id"] == "run-1"
    # The proposal keeps its id, creation time and expiry, so a card already shown still applies.
    assert again["workflow_proposal"] == first["workflow_proposal"]
    assert [call["origin"]["orchestration_run_id"] for call in dry_runs] == ["run-1"]


class _ProposeService:
    """The retained-result service the step writes through, recording each authorization and write."""

    def __init__(self):
        self.authorized = []
        self.persisted = []
        self.access = SimpleNamespace(authorize_producer=self._authorize)

    def _authorize(self, producer, for_write=False):
        self.authorized.append((producer.user_id, for_write))

    def persist_task_result(self, **kwargs):
        self.persisted.append(kwargs["producer"].user_id)


def _adapter_call(ow, planning, monkeypatch, *, user_id=OWNER, contract_version=2, cancel=None):
    """Run the production step adapter with a recorded dry run. Returns ``(call, service, dry runs)``."""
    service, dry_runs = _ProposeService(), []
    producer = SimpleNamespace(user_id=OWNER, run_id="run-1", step_id="propose", conversation_id="conversation-1")
    context = SimpleNamespace(
        result_service=service, plan_contract_version=contract_version, run_id="run-1",
        conversation_id="conversation-1", workflow_planning=planning, time_zone=ZONE,
        user_email="owner@example.com", user_roles=["User"], result_producer=lambda step: producer,
        result_guard_token_for_step=lambda step_id: "guard-1",
        result_input_fingerprint_for_step=lambda step_id: "fingerprint-1",
    )

    def dry_run(dry_run_user_id, blueprint, handles, **kwargs):
        dry_runs.append(dry_run_user_id)
        return {"ok": True, "workflow": {"name": blueprint["name"]}, "errors": []}

    monkeypatch.setattr(ow, "require_result_service", lambda current: current.result_service)
    monkeypatch.setattr(ow, "dry_run_workflow_blueprint", dry_run)

    def call():
        return ow.adapter_workflow_propose(
            _harness_proposal(planning), context, settings=deepcopy(AGENT_SETTINGS), user_id=user_id,
            cancel_requested=cancel,
        )

    return call, service, dry_runs


@pytest.mark.parametrize("case", ["another_user", "legacy_plan", "cancelled"])
def test_the_step_refuses_another_user_a_legacy_plan_and_a_cancelled_run_before_anything_runs(
    modules, ow, planning, monkeypatch, case,
):
    mixed = importlib.import_module("functions_mixed_source_orchestration")
    results = importlib.import_module("functions_orchestration_results")
    call, service, dry_runs = _adapter_call(
        ow, planning, monkeypatch, user_id="someone-else" if case == "another_user" else OWNER,
        contract_version=1 if case == "legacy_plan" else 2,
        cancel=(lambda: True) if case == "cancelled" else (lambda: False),
    )
    expected = mixed.MixedSourceCancellationError if case == "cancelled" else results.ResultUnavailableError
    with pytest.raises(expected) as caught:
        call()
    if case != "cancelled":
        assert caught.value.code == "result_owner_mismatch"
    # Nothing was described or retained: no dry run, no authorization for a write and no write.
    assert dry_runs == [] and service.authorized == [] and service.persisted == []


def test_the_step_writes_only_while_the_run_is_still_wanted(modules, ow, planning, monkeypatch):
    mixed = importlib.import_module("functions_mixed_source_orchestration")
    call, service, dry_runs = _adapter_call(ow, planning, monkeypatch, cancel=lambda: False)
    result = call()
    assert result["status"] == "completed" and result["workflow_proposal"]["status"] == "ready"
    assert dry_runs == [OWNER] and service.persisted == [OWNER]

    # Cancelled while the proposal was being described: it is never retained.
    answers = iter((False, True))
    call, service, dry_runs = _adapter_call(ow, planning, monkeypatch, cancel=lambda: next(answers))
    with pytest.raises(mixed.MixedSourceCancellationError):
        call()
    assert dry_runs == [OWNER] and service.persisted == []


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------

class _Opened:
    def __init__(self, value):
        self.value = value

    def read_value(self):
        if isinstance(self.value, Exception):
            raise self.value
        return deepcopy(self.value)


class _Results:
    def __init__(self, value):
        self.value = value
        self.opened = []

    def open_result(self, reference, allow_partial=True):
        self.opened.append((reference, allow_partial))
        return _Opened(self.value)


def _recovered_task():
    return SimpleNamespace(producer=PRODUCER, output=lambda name: f"reference:{name}")


def _rebuild(ow, planning, monkeypatch, value):
    results = _Results(value)
    monkeypatch.setattr(ow, "require_result_service", lambda context: results)
    monkeypatch.setattr(ow, "dry_run_workflow_blueprint", lambda *args, **kwargs: {"ok": True, "workflow": {}, "errors": []})
    context = SimpleNamespace(workflow_planning=planning, time_zone=ZONE, user_email="owner@example.com", user_roles=["User"])
    step = {"step_id": "propose", "arguments": {"blueprint": _blueprint(planning, trigger={**WEEKLY_TRIGGER, "timezone": ZONE}),
                                                 "task_actions": [["email"]]}}
    sidecar = ow.rebuild_workflow_proposal(step, context, settings=deepcopy(AGENT_SETTINGS), user_id=OWNER,
                                           task=_recovered_task())
    return sidecar, results


def test_a_recovered_proposal_keeps_its_id_and_creation_time(ow, planning, monkeypatch):
    sidecar, results = _rebuild(ow, planning, monkeypatch, {"created_at": CREATED_AT.isoformat()})
    assert results.opened == [("reference:proposal", False)]
    assert sidecar["proposal_id"] == ow.workflow_proposal_id("run-1", "propose")
    assert sidecar["created_at"] == CREATED_AT.isoformat()
    assert sidecar["expires_at"] == (CREATED_AT + timedelta(days=14)).isoformat()
    assert (sidecar["status"], sidecar["reason"]) == ("ready", None)


@pytest.mark.parametrize("value", [RuntimeError("storage failed"), {"created_at": "not a time"}, ["not", "a", "card"]])
def test_an_unreadable_recovered_proposal_is_unavailable_but_keeps_its_id(ow, planning, monkeypatch, value):
    logged = []
    monkeypatch.setattr(ow, "log_event", lambda message, **kwargs: logged.append((message, kwargs)))
    sidecar, _results = _rebuild(ow, planning, monkeypatch, value)
    assert sidecar["proposal_id"] == ow.workflow_proposal_id("run-1", "propose")
    assert (sidecar["status"], sidecar["reason"]) == ("unavailable", "proposal_unavailable")
    assert sidecar["created_at"] is None and sidecar["expires_at"] is None
    assert "storage failed" not in json.dumps(logged, default=str)


def test_a_recovered_proposal_that_cannot_be_described_is_skipped(ow, monkeypatch):
    logged = []
    monkeypatch.setattr(ow, "log_event", lambda message, **kwargs: logged.append((message, kwargs)))
    rebuilt = ow.rebuild_workflow_proposal({"step_id": "propose"}, SimpleNamespace(), settings={}, user_id=OWNER, task=None)
    assert rebuilt is None
    assert logged and logged[-1][1]["extra"]["error_type"] == "AttributeError"


def test_the_executor_restores_only_a_completed_proposal_without_its_description(modules, ow, schema, monkeypatch):
    executor = importlib.import_module("functions_orchestration_executor")
    rebuilt = []
    outcome = {"value": {"proposal_id": "restored"}}

    def rebuild(step, context, *, settings, user_id, task):
        rebuilt.append(task)
        if isinstance(outcome["value"], Exception):
            raise outcome["value"]
        return outcome["value"]

    monkeypatch.setattr(ow, "rebuild_workflow_proposal", rebuild)
    step = {"step_id": "propose", "capability_id": "workflow_propose"}
    task = object()
    completed, failed = schema.STEP_STATUS_COMPLETED, schema.STEP_STATUS_FAILED
    for candidate, status, result in (
        ({**step, "capability_id": "compose"}, completed, {"task_result": task}),
        (step, failed, {"task_result": task}),
        (step, completed, {"task_result": None}),
        (step, completed, {"task_result": task, "workflow_proposal": {"proposal_id": "kept"}}),
        (step, completed, None),
    ):
        restored = executor._restore_workflow_proposal(candidate, SimpleNamespace(), status, result,
                                                       settings={}, user_id=OWNER)
        assert restored is result
    assert rebuilt == []

    result = {"task_result": task}
    restored = executor._restore_workflow_proposal(step, SimpleNamespace(), completed, result, settings={}, user_id=OWNER)
    assert restored == {"task_result": task, "workflow_proposal": {"proposal_id": "restored"}}
    assert result == {"task_result": task} and rebuilt == [task]

    for value in (None, RuntimeError("storage failed")):
        outcome["value"] = value
        restored = executor._restore_workflow_proposal(step, SimpleNamespace(), completed, result,
                                                       settings={}, user_id=OWNER)
        assert restored is result


# ---------------------------------------------------------------------------
# Hygiene
# ---------------------------------------------------------------------------

def test_the_proposal_module_creates_nothing_and_never_imports_flask():
    source = (APP_ROOT / "functions_orchestration_workflows.py").read_text(encoding="utf-8")
    imported = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.setdefault(alias.name, set())
        elif isinstance(node, ast.ImportFrom):
            imported.setdefault(node.module, set()).update(alias.name for alias in node.names)
    assert not any(name.split(".")[0] == "flask" for name in imported)
    assert imported["functions_workflow_drafts"] == {
        "BLUEPRINT_TASK_TITLE_MAX_LENGTH", "WORKFLOW_ORIGIN_SOURCE_ORCHESTRATION", "check_workflow_blueprint",
        "dry_run_workflow_blueprint", "validate_workflow_blueprint",
    }
    assert not any(name.startswith(("functions_workflows", "functions_personal")) for name in imported)
    assert "cosmos_" not in source and "create_personal_workflow" not in source


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
