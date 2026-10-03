#!/usr/bin/env python3
# test_orchestration_workflow_handoff_planner.py
"""
Functional test for the chat orchestration workflow hand-off planner guidance.
Version: 0.261.231
Implemented in: 0.261.231

This test ensures that the planner offers ``workflow_handoff`` only when every hand-off gate
passes, and that, when it does:

- the system prompt carries the hand-off instructions followed by a "Plan limits" section whose
  numbers are the budgets the plan validator enforces;
- the request carries the hand-off catalog, and workspace scope handles appear only there;
- a plan over the step budget or the document limit fails with the repairable
  ``plan_budget_exceeded`` code and gets one repair round that names hand-off, and a second one
  over budget fails with a message that says so;
- an answer deliverable without a final response is steered away from the handed-off work only in
  a plan that hands work off;
- a hand-off step that still breaks the rules after one repair is dropped and reported, without
  handles or ids in the logs, and a model can never write that report itself;
- a valid hand-off plan always waits for the user's manual approval.

When hand-off is not offered, none of this appears and budgets fail as before;
``test_orchestration_workflow_handoff_off_golden.py`` pins those requests byte for byte.

Checks use explicit raises, so they hold under ``python -O``.
"""

import importlib
import json
from copy import deepcopy

import pytest

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_handoff_off_golden import (
    ANSWER_STEP,
    DOCUMENT_OVERFLOW_PLAN,
    FINAL_RESPONSE,
    OVERFLOW_DOCUMENTS,
    PLAIN_PLAN,
    STEP_OVERFLOW_PLAN,
    VARIANTS,
    _build_context,
    _install_recorders,
    _plan,
    _settings,
)
from test_orchestration_workflow_runs_off_golden import AGENT_ID, DOCUMENT_ID, GLOBAL_AGENT_ID, OWNER
from test_support.versioning import assert_app_version_at_least


MINIMUM_VERSION = "0.261.231"
HANDOFF_CAPABILITY = "workflow_handoff"
DOCUMENTS = ["document-record-1"]
PLAN_LIMITS_HEADER = (
    "Plan limits. One chat plan must fit all of these; a request that needs more is what a "
    "workflow_handoff step is for."
)
STEER = (
    " This plan hands work off: remove the answer deliverable, and do not answer the handed-off "
    "part now."
)
GENERIC_FAILURE = "The request could not be planned. Please retry."
TASKS = [
    {"title": "Review one", "instructions": "Review this contract."},
    {"title": "Report", "instructions": "Write the report."},
]
ANSWER_DELIVERABLE = {
    "id": "answer", "kind": "answer", "requested": "explicit", "status": "planned",
    "description": "A review of every contract.",
}
# Every other gate on and hand-off offered; and each request that must not see hand-off.
OFFERED = [("on", "all_on")]
NOT_OFFERED = [
    ("absent", "all_on"),
    ("false", "all_on"),
    ("string", "all_on"),
    ("on", "orchestration_off"),
    ("on", "user_workflows_off"),
    ("on", "proposals_off"),
    ("on", "runs_off"),
    ("on", "results_off"),
    ("on", "role_missing"),
    ("on", "shared_conversation"),
    ("on", "not_allowlisted"),
]


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _same(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def _planner():
    return importlib.import_module("functions_orchestration_planner")


def _context(key_state="on", variant="all_on", changes=None):
    wf = importlib.import_module("functions_orchestration_workflow_context")
    variant_changes, conversation, overrides = VARIANTS[variant]
    settings = _settings(key_state, {**variant_changes, **(changes or {})})
    context, _reads = _build_context(wf, settings, conversation, overrides)
    return settings, context


def _catalog(context):
    marker = context.get("workflow_handoff")
    _require(isinstance(marker, dict) and isinstance(marker.get("catalog"), dict), "Hand-off must be ready.")
    return marker["catalog"]


def _handles(context):
    catalog = _catalog(context)
    return {
        "documents": [entry["handle"] for entry in catalog.get("documents") or ()],
        "scopes": [entry["handle"] for entry in catalog.get("scopes") or ()],
        "local_agents": [entry["handle"] for entry in catalog.get("agents") or () if entry.get("local") is True],
        "hosted_agents": [entry["handle"] for entry in catalog.get("agents") or () if entry.get("local") is not True],
    }


def _handoff_step(loop, tasks=None, **fields):
    return {
        "step_id": "handoff", "capability_id": HANDOFF_CAPABILITY,
        "arguments": {"blueprint": {"name": "Review contracts", "loop": deepcopy(loop), "tasks": deepcopy(tasks or TASKS)}},
        "inputs": {}, "outputs": [{"name": "handoff", "kind": "structured-v1"}],
        **fields,
    }


def _handoff_plan(step, **fields):
    return {"kind": "plan", "intent": {"summary": "Review every contract."}, "steps": [step], **fields}


def _mixed_plan(step):
    return {
        "kind": "plan", "intent": {"summary": "Review every contract and say what to do first."},
        "steps": [deepcopy(ANSWER_STEP), step], "final_response": deepcopy(FINAL_RESPONSE),
    }


def _messages(result, call=0):
    calls = result["calls"]
    _require(len(calls) > call, f"The planner was called {len(calls)} times.")
    system, user = calls[call][0], calls[call][1]
    _same(system["role"], "system", "the first message's role")
    _same(user["role"], "user", "the second message's role")
    return system["content"], user["content"]


def _repair(result):
    calls = result["calls"]
    _require(len(calls) == 2, f"Expected one repair round, got {len(calls)} planner calls.")
    last = calls[1][-1]
    _same(last["role"], "user", "the repair message's role")
    return last["content"]


def _codes(result):
    return [(error["code"], error["rule"]) for error in result["normalize_errors"]]


def _document(result):
    outcome = result["outcome"]
    _require("document" in outcome, f"The request was not planned: {outcome!r}")
    return outcome["document"]


def _step_capabilities(document):
    return [step.get("capability_id") for step in document.get("steps") or ()]


@pytest.fixture
def plan_with(monkeypatch, modules):
    """Plan through the real planner with scripted replies; one recorder serves every plan in a test."""
    recorder = _install_recorders(monkeypatch, _planner())

    def run(settings, context, replies, documents=DOCUMENTS):
        return _plan(monkeypatch, recorder, settings, context, replies, documents)

    return run


# ---------------------------------------------------------------------------
# What the planner is offered
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key_state,variant", OFFERED)
def test_an_offered_hand_off_adds_instructions_limits_and_its_own_catalog(plan_with, key_state, variant):
    assert_app_version_at_least(MINIMUM_VERSION)
    planner = _planner()
    registry = importlib.import_module("functions_orchestration_registry")
    timing = importlib.import_module("functions_orchestration_timing")
    settings, context = _context(key_state, variant)
    handles = _handles(context)
    result = plan_with(settings, context, [PLAIN_PLAN])
    system, user_text = _messages(result)
    user = json.loads(user_text)
    planning = user.get("workflow_planning")
    analyze_limit = registry.get_capability_document_limit(
        registry.get_capability("document_analyze"), settings=settings,
    )
    seconds = timing.execution_timeout_seconds(settings)

    instructions_at = system.find(planner.WORKFLOW_HANDOFF_INSTRUCTIONS)
    limits_at = system.find("\n\n" + PLAN_LIMITS_HEADER)
    _require(instructions_at >= 0, "The system prompt must carry the hand-off instructions.")
    _require(limits_at > instructions_at, "The Plan limits section must follow the hand-off instructions.")
    section = system[limits_at + 2:].splitlines()
    _same(section[:3], [
        PLAN_LIMITS_HEADER,
        "- At most 8 steps in one plan.",
        f"- At most {seconds // 60} minutes for the whole plan to run.",
    ], "the Plan limits section's opening lines")
    _require(seconds % 60 == 0, "The fixture's total timeout must be whole minutes.")
    _require(
        f"- At most {analyze_limit} documents in one document_analyze step." in section,
        f"The Plan limits section must state the validator's analyze limit: {section!r}",
    )
    _require(len(OVERFLOW_DOCUMENTS) > analyze_limit, "The overflow fixture must exceed the stated limit.")
    _require(len(STEP_OVERFLOW_PLAN["steps"]) > 8, "The step overflow fixture must exceed the stated budget.")
    handoff = planning["handoff"]
    _require(
        f"- One workflow_handoff step reviews at most {handoff['documents_max']} named documents, or at most "
        f"{handoff['max_loop_items']} documents from a workspace query." in section,
        f"The Plan limits section must state the hand-off bounds: {section!r}",
    )
    _same(handles["local_agents"], ["agent-researcher-06c604"], "the local agent handles")
    _same(
        section[-1],
        '- Hand-off tasks can run only these agents: agent-researcher-06c604. Leave out "runner" to use the default model.',
        "the Plan limits section's last line",
    )
    _require(system.endswith("\n".join(section)), "The system prompt must end with the Plan limits section.")

    _same(
        sorted(planning), ["catalog", "handoff", "limits", "request_local_time", "time_zone"],
        "the workflow planning projection's fields",
    )
    _same(
        sorted(handoff), ["catalog", "documents_max", "max_loop_items", "request_local_time", "time_zone"],
        "the hand-off projection's fields",
    )
    _require("scopes" not in planning["catalog"], "Scope handles belong only to the hand-off catalog.")
    shared_catalog = json.dumps(planning["catalog"])
    for handle in handles["scopes"]:
        _require(handle not in shared_catalog, "A scope handle leaked into the shared workflow catalog.")
        _require(handle in json.dumps(handoff["catalog"]), "The hand-off catalog must name each scope handle.")
    _require(user_text.count("scope-") == len(handles["scopes"]), "A scope handle appeared outside the hand-off catalog.")
    capability_ids = [entry.get("id") for entry in user.get("capabilities") or ()]
    _same(capability_ids[-1], HANDOFF_CAPABILITY, "the last offered capability")
    deliverables = user["capability_availability"]["deliverables"]
    _require(
        any(fact.startswith("workflow_handoff hands work that is too big for one chat plan") for fact in deliverables["facts"]),
        "The deliverables guidance must explain a hand-off.",
    )
    _require(
        any(recipe.get("for") == "Work too big for one chat plan" for recipe in deliverables["recipes"]),
        "The deliverables guidance must carry the hand-off recipe.",
    )
    _same(_step_capabilities(_document(result)), ["compose"], "the planned steps")


@pytest.mark.parametrize("key_state,variant", NOT_OFFERED)
def test_a_request_that_cannot_hand_off_sees_no_hand_off_guidance(plan_with, key_state, variant):
    planner = _planner()
    settings, context = _context(key_state, variant)
    result = plan_with(settings, context, [PLAIN_PLAN])
    system, user_text = _messages(result)
    user = json.loads(user_text)

    _require(planner.WORKFLOW_HANDOFF_INSTRUCTIONS not in system, "Hand-off instructions reached a request without it.")
    _require("Plan limits." not in system, "The Plan limits section reached a request without hand-off.")
    _require(HANDOFF_CAPABILITY not in system, "The system prompt named workflow_handoff.")
    _require(HANDOFF_CAPABILITY not in user_text, "The request named workflow_handoff.")
    _require("scope-" not in user_text, "A scope handle reached a request without hand-off.")
    _require("handoff" not in (user.get("workflow_planning") or {}), "The hand-off projection reached the planner.")
    _same(_step_capabilities(_document(result)), ["compose"], "the planned steps")


# ---------------------------------------------------------------------------
# The Plan limits section
# ---------------------------------------------------------------------------

ANALYZE = {"id": "document_analyze", "document_action_type": "analyze"}
COMPARE = {"id": "document_compare", "document_action_type": "compare"}
COMPOSE = {"id": "compose"}
HANDOFF_BOUNDS = {
    "documents_max": 25, "max_loop_items": 500,
    "catalog": {"agents": [
        {"handle": "agent-a", "local": True},
        {"handle": "agent-b", "local": False},
        {"handle": "agent-c", "local": True},
    ]},
}


def _limits(monkeypatch, settings, capabilities=(ANALYZE, COMPOSE), handoff=None, limits=None):
    planner = _planner()
    limits = {"analyze": 3, "compare": 5} if limits is None else limits

    def limit(capability, settings=None):
        value = limits.get(capability.get("document_action_type"))
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(planner, "get_capability_document_limit", limit)
    return planner._plan_limits_section(settings, list(capabilities), HANDOFF_BOUNDS if handoff is None else handoff)


def test_the_plan_limits_section_states_each_budget(monkeypatch, modules):
    text = _limits(
        monkeypatch, {"chat_orchestration_max_steps": 12, "chat_orchestration_total_timeout_seconds": 900},
        capabilities=(ANALYZE, COMPOSE, COMPARE),
    )

    _same(text.splitlines(), [
        PLAN_LIMITS_HEADER,
        "- At most 12 steps in one plan.",
        "- At most 15 minutes for the whole plan to run.",
        "- At most 3 documents in one document_analyze step.",
        "- At most 5 documents in one document_compare step.",
        "- One workflow_handoff step reviews at most 25 named documents, or at most 500 documents from a workspace query.",
        '- Hand-off tasks can run only these agents: agent-a, agent-c. Leave out "runner" to use the default model.',
    ], "the Plan limits section")


def test_the_plan_limits_section_uses_singular_counts(monkeypatch, modules):
    text = _limits(
        monkeypatch, {"chat_orchestration_max_steps": 1, "chat_orchestration_total_timeout_seconds": 60},
        handoff={**HANDOFF_BOUNDS, "documents_max": 1, "max_loop_items": 1}, limits={"analyze": 1},
    )

    _same(text.splitlines()[1:5], [
        "- At most 1 step in one plan.",
        "- At most 1 minute for the whole plan to run.",
        "- At most 1 document in one document_analyze step.",
        "- One workflow_handoff step reviews at most 1 named document, or at most 1 document from a workspace query.",
    ], "the singular Plan limits lines")


@pytest.mark.parametrize("value,expected", [
    (50, "- At most 30 steps in one plan."),
    (30, "- At most 30 steps in one plan."),
    (0, "- At most 8 steps in one plan."),
    (None, "- At most 8 steps in one plan."),
    ("many", "- At most 8 steps in one plan."),
    (-5, "- At most 1 step in one plan."),
])
def test_the_step_budget_is_clamped_like_the_validator(monkeypatch, modules, value, expected):
    schema = importlib.import_module("functions_orchestration_schema")
    text = _limits(monkeypatch, {"chat_orchestration_max_steps": value})

    _same(text.splitlines()[1], expected, f"the step budget line for {value!r}")
    _same(schema.PLAN_HARD_MAX_STEPS, 30, "the validator's hard step ceiling")


@pytest.mark.parametrize("value,expected", [
    (90, "- At most 90 seconds for the whole plan to run."),
    (1, "- At most 1 second for the whole plan to run."),
    (7200, "- At most 120 minutes for the whole plan to run."),
    (0, "- At most 10 minutes for the whole plan to run."),
    ("slow", "- At most 10 minutes for the whole plan to run."),
])
def test_the_run_time_comes_from_the_execution_timeout(monkeypatch, modules, value, expected):
    timing = importlib.import_module("functions_orchestration_timing")
    settings = {"chat_orchestration_total_timeout_seconds": value}
    text = _limits(monkeypatch, settings)
    seconds = timing.execution_timeout_seconds(settings)

    _same(text.splitlines()[2], expected, f"the run time line for {value!r}")
    _require(str(seconds // 60 if seconds % 60 == 0 else seconds) in expected, "The line must state the executor's timeout.")


def test_a_limit_that_cannot_be_read_is_left_out(monkeypatch, modules):
    registry = importlib.import_module("functions_orchestration_registry")
    text = _limits(
        monkeypatch, {}, capabilities=(ANALYZE, COMPARE, {"id": "document_extract", "document_action_type": "extract"}),
        limits={"analyze": registry.CapabilityResolutionError("unreadable"), "compare": 0, "extract": None},
    )

    _require("document_analyze" not in text, "An unreadable limit must be left out.")
    _require("document_compare" not in text, "A zero limit must be left out.")
    _require("document_extract" not in text, "A missing limit must be left out.")
    _require("- One workflow_handoff step reviews" in text, "The hand-off bounds must still be stated.")


@pytest.mark.parametrize("bounds", [
    {"documents_max": True, "max_loop_items": 500},
    {"documents_max": 25, "max_loop_items": "500"},
    {"documents_max": None, "max_loop_items": 500},
    {},
])
def test_hand_off_bounds_are_stated_only_when_both_are_integers(monkeypatch, modules, bounds):
    text = _limits(monkeypatch, {}, handoff={**bounds, "catalog": HANDOFF_BOUNDS["catalog"]})

    _require("workflow_handoff step reviews" not in text, f"Bounds {bounds!r} must not be stated.")


@pytest.mark.parametrize("agents", [
    [],
    [{"handle": "agent-b", "local": False}],
    [{"handle": "agent-d", "local": "true"}],
    [{"handle": 7, "local": True}],
    "agents",
])
def test_no_local_agent_tells_the_planner_to_leave_out_the_runner(monkeypatch, modules, agents):
    text = _limits(monkeypatch, {}, handoff={"documents_max": 25, "max_loop_items": 500, "catalog": {"agents": agents}})

    _same(
        text.splitlines()[-1], '- No catalog agent can run hand-off tasks, so leave out "runner".',
        f"the agents line for {agents!r}",
    )


@pytest.mark.parametrize("settings,handoff", [(None, None), ("settings", "handoff"), ([], [])])
def test_the_plan_limits_section_never_raises(monkeypatch, modules, settings, handoff):
    planner = _planner()
    monkeypatch.setattr(planner, "get_capability_document_limit", lambda capability, settings=None: 3)
    text = planner._plan_limits_section(settings, [ANALYZE, "compose", None], handoff)

    _same(text.splitlines(), [
        PLAN_LIMITS_HEADER,
        "- At most 8 steps in one plan.",
        "- At most 10 minutes for the whole plan to run.",
        "- At most 3 documents in one document_analyze step.",
        '- No catalog agent can run hand-off tasks, so leave out "runner".',
    ], "the Plan limits section without settings")


def test_plan_limits_are_added_only_when_passed(modules):
    planner = _planner()
    context = {"message": "Review my contracts."}
    plain = planner.build_planner_messages(context)
    limited = planner.build_planner_messages(context, plan_limits="Plan limits. Example.")

    _same(limited[0]["content"], plain[0]["content"] + "\n\nPlan limits. Example.", "the system prompt with limits")
    _same(limited[1], plain[1], "the request message")
    _same(planner.build_planner_messages(context, plan_limits=None), plain, "the messages without limits")
    _same(planner.build_planner_messages(context, plan_limits=""), plain, "the messages with empty limits")


# ---------------------------------------------------------------------------
# Budgets and repair
# ---------------------------------------------------------------------------

def test_a_budget_overflow_is_repaired_once_when_hand_off_is_offered(plan_with):
    settings, context = _context("on")
    steps = plan_with(settings, context, [STEP_OVERFLOW_PLAN, PLAIN_PLAN])
    step_repair = _repair(steps)
    documents = plan_with(settings, context, [DOCUMENT_OVERFLOW_PLAN, PLAIN_PLAN], OVERFLOW_DOCUMENTS)
    document_repair = _repair(documents)

    _same(_codes(steps), [("plan_budget_exceeded", "plan_step_budget")], "the step overflow errors")
    _require(
        step_repair.startswith(
            "The server rejected that plan: The complete plan exceeds the available step budget. Reduce the "
            "plan, or hand the work off with one workflow_handoff step.\n"
            "Reduce the plan to fit the Plan limits, or, when the work cannot fit them, hand it off with one "
            "workflow_handoff step instead of the steps that do not fit.\n"
        ),
        f"The step repair must name hand-off: {step_repair!r}",
    )
    _same(_step_capabilities(_document(steps)), ["compose"], "the repaired plan")
    _same(_codes(documents), [("plan_budget_exceeded", "plan_document_budget")], "the document overflow errors")
    _require(
        "The complete source selection exceeds the document limit. Reduce the plan, or hand the work off "
        "with one workflow_handoff step." in document_repair,
        f"The document repair must name hand-off: {document_repair!r}",
    )
    _same(_step_capabilities(_document(documents)), ["compose"], "the repaired plan")


def test_a_second_budget_overflow_says_the_request_is_too_big(plan_with):
    planner = _planner()
    settings, context = _context("on")
    result = plan_with(settings, context, [STEP_OVERFLOW_PLAN, STEP_OVERFLOW_PLAN])

    _same(len(result["calls"]), 2, "the planner calls")
    _same(result["outcome"], {"planner_error": {
        "reason": "invalid_plan_or_missing_requirement", "message": planner.PLAN_BUDGET_FAILURE_MESSAGE,
    }}, "the planner error")
    _require("hand the work off" in planner.PLAN_BUDGET_FAILURE_MESSAGE, "The failure must name hand-off.")


@pytest.mark.parametrize("key_state,variant", [("absent", "all_on"), ("on", "runs_off"), ("on", "shared_conversation")])
def test_a_budget_overflow_without_hand_off_fails_as_before(plan_with, key_state, variant):
    settings, context = _context(key_state, variant)
    steps = plan_with(settings, context, [STEP_OVERFLOW_PLAN, PLAIN_PLAN])
    documents = plan_with(settings, context, [DOCUMENT_OVERFLOW_PLAN, PLAIN_PLAN], OVERFLOW_DOCUMENTS)
    expected = {"planner_error": {"reason": "invalid_plan_or_missing_requirement", "message": GENERIC_FAILURE}}

    _same(_codes(steps), [("result_step_limit", None)], "the step overflow errors")
    _same(len(steps["calls"]), 1, "the planner calls for a step overflow")
    _same(steps["outcome"], expected, "the step overflow outcome")
    _same(_codes(documents), [("plan_invalid", None)], "the document overflow errors")
    _same(len(documents["calls"]), 1, "the planner calls for a document overflow")
    _same(documents["outcome"], expected, "the document overflow outcome")


def test_the_missing_answer_steer_is_only_for_a_plan_that_hands_work_off(plan_with):
    planner = _planner()
    schema = importlib.import_module("functions_orchestration_schema")
    error = schema.PlanValidationError("Bind the answer.", code="deliverables_invalid", rule="missing_final_response")
    other = schema.PlanValidationError("Bind the file.", code="deliverables_invalid", rule="unrendered_file")
    plain = planner.plan_repair_message(error)
    steered = planner.plan_repair_message(error, handoff_present=True)

    _same(steered, plain + STEER, "the steered repair message")
    _same(planner.plan_repair_message(error, handoff_present=False), plain, "the unsteered repair message")
    _require(STEER.strip() not in plain, "Only a hand-off plan is steered.")
    _same(planner.plan_repair_message(other, handoff_present=True), planner.plan_repair_message(other), "another rule")

    settings, context = _context("on")
    handles = _handles(context)
    handoff = _handoff_plan(
        _handoff_step({"source": "documents", "documents": handles["documents"]}),
        deliverables=[deepcopy(ANSWER_DELIVERABLE)],
    )
    answer = {
        "kind": "plan", "intent": {"summary": "Review every contract."},
        "deliverables": [deepcopy(ANSWER_DELIVERABLE)], "steps": [deepcopy(ANSWER_STEP)],
    }
    handed_off = plan_with(settings, context, [handoff, PLAIN_PLAN])
    handed_off_repair = _repair(handed_off)
    answered = plan_with(settings, context, [answer, PLAIN_PLAN])
    answered_repair = _repair(answered)

    _same(_codes(handed_off), [("deliverables_invalid", "missing_final_response")], "the hand-off plan's errors")
    _require(handed_off_repair.endswith(STEER), f"A hand-off plan must be steered: {handed_off_repair!r}")
    _same(_codes(answered), [("deliverables_invalid", "missing_final_response")], "the answer plan's errors")
    _require(STEER.strip() not in answered_repair, "A plan without a hand-off must not be steered.")
    _require(
        answered_repair.endswith("exact unavailable_reason capability_availability.deliverables gives, instead of "
                                 "dropping it or promising it."),
        f"The plain repair message must be unchanged: {answered_repair!r}",
    )


def test_a_disabled_hand_off_step_is_not_steered(modules):
    handoffs = importlib.import_module("functions_orchestration_workflow_handoffs")
    enabled = _handoff_plan(_handoff_step({"source": "documents", "documents": ["doc-a"]}))
    disabled = _handoff_plan(_handoff_step({"source": "documents", "documents": ["doc-a"]}, enabled=False))

    _require(handoffs.plan_has_workflow_handoff(enabled) is True, "An enabled hand-off step must count.")
    _require(handoffs.plan_has_workflow_handoff(disabled) is False, "A disabled hand-off step must not count.")
    _require(handoffs.plan_has_workflow_handoff(PLAIN_PLAN) is False, "A plan without hand-off must not count.")
    _require(handoffs.plan_has_workflow_handoff(None) is False, "Nothing is not a hand-off plan.")
    _require(handoffs.plan_has_workflow_handoff({"steps": "x"}) is False, "Malformed steps are not a hand-off plan.")


# ---------------------------------------------------------------------------
# A hand-off that cannot be repaired
# ---------------------------------------------------------------------------

def _hosted_agent_handoff(context):
    handles = _handles(context)
    _require(handles["hosted_agents"], "The fixture must offer an agent that is not local.")
    tasks = [{**TASKS[0], "runner": {"type": "agent", "agent_ref": handles["hosted_agents"][0]}}, TASKS[1]]
    return _handoff_step({"source": "documents", "documents": handles["documents"]}, tasks)


def _no_identifiers(text, context):
    handles = _handles(context)
    for value in [*handles["documents"], *handles["scopes"], *handles["local_agents"], *handles["hosted_agents"],
                  DOCUMENT_ID, AGENT_ID, GLOBAL_AGENT_ID]:
        _require(value not in text, f"An identifier reached the planner logs: {value!r}")
    _require(f'"{OWNER}"' not in text, "The user id reached the planner logs.")


def test_a_hand_off_that_breaks_the_rules_twice_is_dropped_and_reported(plan_with):
    handoffs = importlib.import_module("functions_orchestration_workflow_handoffs")
    settings, context = _context("on")
    plan = _mixed_plan(_hosted_agent_handoff(context))
    result = plan_with(settings, context, [plan, plan])
    repair = _repair(result)
    document = _document(result)
    reasons = [entry["extra"].get("reason") for entry in result["logs"]]
    dropped = [entry["extra"] for entry in result["logs"] if entry["extra"].get("reason") == "workflow_handoff_dropped"]
    expected_repair = handoffs.workflow_handoff_repair_text({"reason": "handoff_agent_unsupported"})

    _same(_codes(result), [("workflow_handoff_invalid", "handoff_agent_unsupported")] * 2, "the validation errors")
    _require(
        repair.startswith("The server rejected the workflow_handoff step in that plan:"),
        f"The repair must explain the hand-off rules: {repair!r}",
    )
    _same(_step_capabilities(document), ["compose"], "the degraded plan")
    _same(document.get("workflow_handoff_notes"), [{"reason": "handoff_agent_unsupported"}], "the hand-off notes")
    _same(document["validation"]["repairs"], [expected_repair], "the plan card's repairs")
    _same(
        expected_repair,
        "No workflow was handed off. A hand-off runs its tasks on the default model or on a local agent. Ask "
        "again without naming that agent.",
        "the repair text",
    )
    _require("floor" not in document["approval"], "A plan whose hand-off was dropped has no approval floor.")
    _require(
        reasons.index("workflow_handoff_invalid") < reasons.index("workflow_handoff_dropped"),
        f"The repair must be logged before the drop: {reasons!r}",
    )
    _same(len(dropped), 1, "the drop log entries")
    _same(
        {key: dropped[0][key] for key in ("validation_code", "validation_rule", "note_count", "remaining_count")},
        {"validation_code": "workflow_handoff_invalid", "validation_rule": "handoff_agent_unsupported",
         "note_count": 1, "remaining_count": 0},
        "the drop log fields",
    )
    _no_identifiers(json.dumps(result["logs"]), context)


def test_a_plan_of_only_an_unrepairable_hand_off_fails_with_its_reason(plan_with):
    handoffs = importlib.import_module("functions_orchestration_workflow_handoffs")
    settings, context = _context("on")
    plan = _handoff_plan(_hosted_agent_handoff(context))
    result = plan_with(settings, context, [plan, plan])

    _same(len(result["calls"]), 2, "the planner calls")
    _same(result["outcome"], {"planner_error": {
        "reason": "invalid_plan_or_missing_requirement",
        "message": handoffs.workflow_handoff_failure_message([{"reason": "handoff_agent_unsupported"}]),
    }}, "the planner error")
    _require(
        result["outcome"]["planner_error"]["message"].startswith("No workflow was handed off."),
        "The failure must say no workflow was handed off.",
    )
    _no_identifiers(json.dumps(result["logs"]), context)


@pytest.mark.parametrize("key_state", ["on", "absent"])
def test_a_model_cannot_report_a_dropped_hand_off(plan_with, key_state):
    settings, context = _context(key_state)
    forged = {**deepcopy(PLAIN_PLAN), "workflow_handoff_notes": [{"reason": "handoff_unavailable"}]}
    result = plan_with(settings, context, [forged])
    document = _document(result)

    _require("workflow_handoff_notes" not in document, "A model-written hand-off note must be stripped.")
    _same(_step_capabilities(document), ["compose"], "the planned steps")


def test_a_dropped_hand_off_reports_the_servers_reason_not_the_models(plan_with):
    settings, context = _context("on")
    plan = {**_mixed_plan(_hosted_agent_handoff(context)), "workflow_handoff_notes": [{"reason": "handoff_unavailable"}]}
    result = plan_with(settings, context, [plan, plan])

    _same(_document(result).get("workflow_handoff_notes"), [{"reason": "handoff_agent_unsupported"}], "the notes")


# ---------------------------------------------------------------------------
# A valid hand-off plan
# ---------------------------------------------------------------------------

def test_a_hand_off_plan_always_waits_for_manual_approval(plan_with):
    settings, context = _context("on", changes={"chat_orchestration_default_approval_mode": "auto"})
    handles = _handles(context)
    only = _handoff_plan(_handoff_step({"source": "documents", "documents": handles["documents"]}))
    mixed = _mixed_plan(_handoff_step({
        "source": "workspace_query", "scopes": handles["scopes"], "selection": "all_matches", "content": "indemnity",
    }))
    handed_off = plan_with(settings, context, [only])
    mixed_result = plan_with(settings, context, [mixed])
    plain = plan_with(settings, context, [PLAIN_PLAN])
    floor = {"mode": "manual", "reason": HANDOFF_CAPABILITY}

    for name, result, steps in (
        ("hand-off only", handed_off, [HANDOFF_CAPABILITY]),
        ("mixed", mixed_result, ["compose", HANDOFF_CAPABILITY]),
    ):
        document = _document(result)
        _same(len(result["calls"]), 1, f"the {name} planner calls")
        _same(sorted(_step_capabilities(document)), sorted(steps), f"the {name} steps")
        _same(document["approval"]["mode"], "manual", f"the {name} approval mode")
        _same(document["approval"].get("floor"), floor, f"the {name} approval floor")
        _same(document["status"], "awaiting_approval", f"the {name} status")
        _require("workflow_handoff_notes" not in document, f"The {name} plan must carry no notes.")
    _require("final_response" not in _document(handed_off), "A hand-off-only plan has no final response.")
    _same(_document(plain)["approval"]["mode"], "auto", "a plan without a floor keeps the requested mode")
    _require("floor" not in _document(plain)["approval"], "A plan without a hand-off has no floor.")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
