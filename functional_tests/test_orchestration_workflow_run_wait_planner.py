#!/usr/bin/env python3
# test_orchestration_workflow_run_wait_planner.py
"""
Functional test for planning a chat orchestration plan that waits for a quick saved workflow.
Version: 0.261.309
Implemented in: 0.261.309

This test ensures that the workflow planning context marks a catalog workflow "waitable" only
when Wait For Quick Workflows In Chat is configured with everything it needs, personal workflows
don't require the WorkflowUser role and the saved definition passes the quick-run rule; that a
failed or foreign read marks nothing; that normalization records the server's wait marker for a
plan whose compose step reads one quick run, rejects the same plan without the marker exactly as
before, and ignores a marker the model wrote; that a stored plan keeps its marker only while it
still fits; that the degrade path keeps a run step only when the plan may wait for it and
otherwise drops it with its own reason; that the planner is told about waiting only when a
catalog entry may be waited for, while a waiting plan stays on the manual approval floor; and that
a plan revision checks the marker again under the current settings.

Checks raise ``AssertionError`` explicitly, so they also run under ``python -O``.
"""

import importlib
import json
from copy import deepcopy

import pytest

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_run_capability import (  # noqa: F401
    RUN_ONLY,
    _handle,
    _normalize,
    _plan_request,
    _raw_plan,
    _record,
    _run,
    planner,
    runs,
    schema,
)
from test_orchestration_workflow_run_planning_context import (  # noqa: F401
    DIGEST_ID,
    OWNER,
    PRIVATE,
    RUN_SETTINGS,
    RUNS,
    SHARED_CHANGES,
    USER_INFO,
    _build,
    _fail,
    _settings,
    wf,
)
from test_orchestration_workflow_run_wait_eligibility import _quick, _task
from test_orchestration_workflow_setting_off_golden import IDENTITY
from test_support.orchestration_harness_execution import input_binding
from test_support.versioning import assert_app_version_at_least


WAIT = "enable_chat_orchestration_workflow_run_wait"
RESULTS = "enable_chat_workflow_results"
CONTEXT_ON = {**RUN_SETTINGS, RESULTS: True, WAIT: True}
PLANNER_ON = {**RUN_ONLY, RESULTS: True, WAIT: True}
ROLE_USER = {**USER_INFO, "roles": ["User", "WorkflowUser"]}
HEADLESS = ["compose", "workflow_run"]
NOT_WAITABLE = "workflow_run_not_waitable"
INVALID = "workflow_run_invalid"


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _definitions(workflow_ids, quick=(DIGEST_ID,), user_id=OWNER):
    """Full saved definitions: the named ones are quick, the rest have too many tasks."""
    definitions = []
    for workflow_id in workflow_ids:
        if workflow_id in quick:
            definitions.append(_quick(id=workflow_id, user_id=user_id, name="Weekly digest"))
        else:
            definitions.append(_quick(id=workflow_id, user_id=user_id, tasks=[_task(index) for index in range(1, 8)]))
    return definitions


def _wait_reader(seen, **options):
    def read(user_id, workflow_ids):
        seen.append((user_id, list(workflow_ids)))
        return _definitions(workflow_ids, **options)
    return read


def _refusing_reader(user_id, workflow_ids):
    raise AssertionError("The saved definitions must not be read while the wait is off.")


def _ready(wf, **options):
    """A planning context with the wait marker and the headless ids the planner adds."""
    planning = _build(wf, [], CONTEXT_ON, wait_workflows=_wait_reader([], **options))
    planning["workflow_run_wait"] = {**planning["workflow_run_wait"], "headless_capability_ids": list(HEADLESS)}
    return planning


def _reader_answer(step_id="answer", producer="run_digest", **extra):
    step = {
        "step_id": step_id, "capability_id": "compose",
        "arguments": {"instruction": "Compare the digest's totals with last week.", "knowledge_basis": "general_knowledge"},
        "inputs": {"digest": {"binding": input_binding(producer, "run")}},
        "outputs": [{"name": "answer", "kind": "markdown-v1"}],
    }
    step.update(deepcopy(extra))
    return step


def _rejected(schema, planning, steps, final="answer"):
    try:
        _normalize(schema, planning, steps, final)
    except schema.PlanValidationError as exc:
        return exc
    raise AssertionError("The plan should have been rejected.")


# ---------------------------------------------------------------------------
# The planning context
# ---------------------------------------------------------------------------

def test_version_is_at_least_the_implementation():
    """Planning a wait ships in 0.261.309."""
    assert_app_version_at_least("0.261.309")


def test_only_quick_catalog_workflows_are_marked_waitable(wf):
    """One read of exactly the catalog's workflows; only the quick definition is marked."""
    calls, seen = [], []
    context = _build(wf, calls, CONTEXT_ON, wait_workflows=_wait_reader(seen))
    _require(context.get("workflow_run_wait") == {"ready": True}, f"Expected the wait marker, got {context.get('workflow_run_wait')!r}.")
    entries = context["catalog"]["workflows"]
    waitable = [entry["name"] for entry in entries if entry.get("waitable") is True]
    _require(waitable == ["Weekly digest"], f"Only the quick workflow should be waitable, got {waitable!r}.")
    _require(all("waitable" not in entry for entry in entries if entry["name"] != "Weekly digest"),
             "A workflow that is not quick must carry no waitable flag at all.")
    ids = sorted({context["handles"]["workflows"][entry["handle"]]["id"] for entry in entries})
    _require(seen == [(OWNER, ids)], f"Expected one read of the catalog's workflows, got {seen!r}.")
    _require(calls.count("wait_workflows") == 1, "The definitions should be read once.")


@pytest.mark.parametrize("label, changes", [
    ("wait off", {WAIT: False}),
    ("wait unset", {WAIT: None}),
    ("wait as text", {WAIT: "true"}),
    ("workflow results off", {RESULTS: False}),
    ("workflow runs off", {RUNS: False}),
    ("user workflows off", {"allow_user_workflows": False}),
    ("WorkflowUser role required", {"require_member_of_workflow_user": True}),
])
def test_without_a_configured_wait_the_context_is_unchanged(wf, label, changes):
    """Anything short of a configured wait leaves the context as it was, with no extra read."""
    settings = _settings(CONTEXT_ON, **changes)
    calls, baseline_calls = [], []
    context = _build(wf, calls, settings, user_info=ROLE_USER, wait_workflows=_refusing_reader)
    baseline = _build(wf, baseline_calls, _settings(settings, **{WAIT: None}), user_info=ROLE_USER)
    _require(context == baseline, f"{label}: the context should be exactly the one without the wait.")
    _require("wait_workflows" not in calls, f"{label}: the saved definitions must not be read.")
    _require("workflow_run_wait" not in context, f"{label}: no wait marker expected.")
    if label == "WorkflowUser role required":
        _require(wf.workflow_run_ready(context), "The role case should still be able to start workflows.")


def test_a_failed_foreign_or_shared_read_marks_nothing(wf):
    """A failed read changes nothing; another user's definition and a shared chat mark nothing."""
    baseline = _build(wf, [], _settings(CONTEXT_ON, **{WAIT: None}))
    failed = _build(wf, [], CONTEXT_ON, wait_workflows=_fail)
    _require(failed == baseline, "A failed read should leave the context exactly as it was.")
    foreign = _build(wf, [], CONTEXT_ON, wait_workflows=_wait_reader([], user_id="someone-else"))
    _require(foreign.get("workflow_run_wait") == {"ready": True}, "The marker should still be set.")
    _require(not any("waitable" in entry for entry in foreign["catalog"]["workflows"]),
             "Another user's definition must not make a workflow waitable.")
    for changes in SHARED_CHANGES:
        calls, seen = [], []
        shared = _build(wf, calls, CONTEXT_ON, conversation={**PRIVATE, **changes}, wait_workflows=_wait_reader(seen))
        _require("workflow_run_wait" not in shared and not seen, f"A shared chat ({changes!r}) must not wait.")


# ---------------------------------------------------------------------------
# Normalization and stored plans
# ---------------------------------------------------------------------------

def test_normalization_records_the_server_wait_marker(schema, wf):
    """A compose step may read a quick run; the server records that the run step waits."""
    planning = _ready(wf)
    handle = _handle(planning, "Weekly digest")
    plan = _normalize(schema, planning, [_run(handle), _reader_answer()])
    expected = {"run_digest": {"version": 1, "workflow": handle}}
    _require(plan.get("workflow_run_waits") == expected, f"Expected {expected!r}, got {plan.get('workflow_run_waits')!r}.")
    stored = schema.validate_plan(deepcopy(plan), settings=deepcopy(RUN_ONLY), available_capability_ids=["compose", "workflow_run"])
    _require(stored.get("workflow_run_waits") == expected, "A stored plan should keep a marker that still fits.")


def test_without_the_server_marker_a_reader_is_rejected_as_before(schema, wf):
    """No marker, a workflow that is not quick, or a headless gap: the consumer rule applies."""
    plain = _build(wf, [], RUN_SETTINGS)
    handle = _handle(plain, "Weekly digest")
    not_quick = _ready(wf, quick=())
    no_compose = _ready(wf)
    no_compose["workflow_run_wait"]["headless_capability_ids"] = ["workflow_run"]
    for label, planning in (("no marker", plain), ("not quick", not_quick), ("compose not headless", no_compose)):
        error = _rejected(schema, planning, [_run(handle), _reader_answer()])
        _require((error.code, error.rule) == (INVALID, "workflow_run_consumed"), f"{label}: got {(error.code, error.rule)!r}.")
    two_runs = _ready(wf)
    other = next(entry["handle"] for entry in two_runs["catalog"]["workflows"] if entry["handle"] != handle and entry["durable"])
    error = _rejected(schema, two_runs, [_run(handle), _run(other, "run_other"), _reader_answer()])
    _require(error.rule == "workflow_run_consumed", "A plan that starts two workflows must not wait.")


def test_a_marker_the_model_wrote_is_ignored(schema, wf):
    """The model can neither make a run wait nor choose which step waits."""
    plain = _build(wf, [], RUN_SETTINGS)
    handle = _handle(plain, "Weekly digest")
    forged = {"run_digest": {"version": 1, "workflow": handle}}
    raw = _raw_plan([_run(handle), _reader_answer()])
    raw["workflow_run_waits"] = deepcopy(forged)
    try:
        schema.normalize_plan(
            raw, "conversation-1", OWNER, settings=deepcopy(RUN_ONLY), contract_version=2,
            available_capability_ids=["compose", "workflow_run"], workflow_planning=plain,
        )
    except schema.PlanValidationError as exc:
        _require(exc.rule == "workflow_run_consumed", f"Expected the consumer rule, got {exc.rule!r}.")
    else:
        raise AssertionError("A forged marker must not let a step read a run.")
    ready = _ready(wf)
    raw = _raw_plan([_run(handle), _reader_answer()])
    raw["workflow_run_waits"] = {"answer": {"version": 1, "workflow": handle}, "extra": True}
    plan = schema.normalize_plan(
        raw, "conversation-1", OWNER, settings=deepcopy(RUN_ONLY), contract_version=2,
        available_capability_ids=["compose", "workflow_run"], workflow_planning=ready,
    )
    _require(plan.get("workflow_run_waits") == forged, "Only the server's marker should be kept.")


def test_a_stored_marker_must_still_fit(schema, wf):
    """A saved plan whose marker no longer fits is refused rather than run without its wait."""
    planning = _ready(wf)
    handle = _handle(planning, "Weekly digest")
    plan = _normalize(schema, planning, [_run(handle), _reader_answer()])
    for label, marker in (
        ("missing", None),
        ("another version", {"run_digest": {"version": 2, "workflow": handle}}),
        ("another workflow", {"run_digest": {"version": 1, "workflow": "w-other"}}),
        ("another step", {"answer": {"version": 1, "workflow": handle}}),
    ):
        stored = deepcopy(plan)
        if marker is None:
            stored.pop("workflow_run_waits")
        else:
            stored["workflow_run_waits"] = marker
        try:
            schema.validate_plan(stored, settings=deepcopy(RUN_ONLY), available_capability_ids=["compose", "workflow_run"])
        except schema.PlanValidationError as exc:
            _require(exc.rule == "workflow_run_consumed", f"{label}: expected the consumer rule, got {exc.rule!r}.")
        else:
            raise AssertionError(f"{label}: a marker that no longer fits must be refused.")


# ---------------------------------------------------------------------------
# The degrade path
# ---------------------------------------------------------------------------

def test_the_degrade_path_keeps_only_a_run_the_plan_may_wait_for(runs, wf):
    """Kept when it may wait; dropped as invalid with the wait off; as not waitable otherwise."""
    ready = _ready(wf)
    handle = _handle(ready, "Weekly digest")
    raw = _raw_plan([_run(handle), _reader_answer()])
    kept, notes, remaining = runs.drop_workflow_runs(deepcopy(raw), workflow_planning=ready)
    _require((notes, remaining) == ([], 1), f"The waited run should be kept, got {(notes, remaining)!r}.")
    _require(kept == raw, "Nothing in the plan should change.")

    plain = _build(wf, [], RUN_SETTINGS)
    off, notes, remaining = runs.drop_workflow_runs(deepcopy(raw), workflow_planning=plain)
    _require((notes, remaining) == ([{"reason": INVALID, "name": "Weekly digest"}], 0), f"Wait off: got {notes!r}.")
    answer = next(step for step in off["steps"] if step["step_id"] == "answer")
    _require(answer["inputs"] == {} and [step["step_id"] for step in off["steps"]] == ["answer"],
             "With the wait off the run step and every binding to it are dropped, as before.")

    not_quick = _ready(wf, quick=())
    _plan, notes, remaining = runs.drop_workflow_runs(deepcopy(raw), workflow_planning=not_quick)
    _require((notes, remaining) == ([{"reason": NOT_WAITABLE, "name": "Weekly digest"}], 0), f"Not quick: got {notes!r}.")

    searching = _raw_plan([_run(handle), _reader_answer(), {
        "step_id": "news", "capability_id": "web_search", "arguments": {"query": "sales news"},
        "inputs": {}, "outputs": [{"name": "results", "kind": "search-results-v1"}],
    }])
    _plan, notes, remaining = runs.drop_workflow_runs(searching, workflow_planning=ready)
    _require((notes, remaining) == ([{"reason": NOT_WAITABLE, "name": "Weekly digest"}], 0),
             f"A plan that needs the user's session must not wait, got {notes!r}.")
    _plan, notes, remaining = runs.drop_workflow_runs(deepcopy(raw), workflow_planning=ready, drop_all=True)
    _require(remaining == 0, "An unavailable context drops every run step, as before.")
    _require(NOT_WAITABLE in runs.WORKFLOW_RUN_SKIP_REASONS, "The new reason needs its own user text.")


# ---------------------------------------------------------------------------
# The planner and plan revisions
# ---------------------------------------------------------------------------

def test_the_planner_is_told_about_waiting_only_for_a_waitable_workflow(monkeypatch, wf):
    """The hint and the waitable flags reach the planner only when a plan could wait."""
    instructions = importlib.import_module("functions_orchestration_planner").WORKFLOW_RUN_WAIT_INSTRUCTIONS
    planning = _build(wf, [], CONTEXT_ON, wait_workflows=_wait_reader([]))
    handle = _handle(planning, "Weekly digest")
    reply = _raw_plan([_run(handle), _reader_answer()])
    reply["workflow_run_waits"] = {"answer": {"version": 1, "workflow": handle}}
    record = _record()
    kind, plan = _plan_request(monkeypatch, planning, [reply], record, settings=PLANNER_ON, approval_mode="auto")
    _require(kind == "plan", f"Expected a plan, got {kind!r}.")
    system, user = record.calls[0][0]["content"], json.loads(record.calls[0][1]["content"])
    _require(instructions in system, "The wait instructions should be offered.")
    catalog = user["workflow_planning"]["catalog"]["workflows"]
    _require([entry["name"] for entry in catalog if entry.get("waitable") is True] == ["Weekly digest"],
             "Only the quick workflow should be flagged to the planner.")
    _require(plan.get("workflow_run_waits") == {"run_digest": {"version": 1, "workflow": handle}},
             f"The server's marker should be recorded, got {plan.get('workflow_run_waits')!r}.")
    approval = plan["approval"]
    _require((approval["mode"], approval["state"], plan["status"]) == ("manual", "pending", "awaiting_approval"),
             "A plan that starts a workflow must still wait for the user's approval.")
    _require(bool(approval.get("floor")), "The approval floor should be recorded.")

    # The same request with the wait off: no hint, no flags, and the reader is dropped as before.
    plain = _build(wf, [], {**RUN_SETTINGS, RESULTS: True})
    record = _record()
    kind, plan = _plan_request(
        monkeypatch, plain, [reply, reply], record, settings={**PLANNER_ON, WAIT: False},
    )
    system, user = record.calls[0][0]["content"], json.loads(record.calls[0][1]["content"])
    _require(instructions not in system, "With the wait off the planner must not be told about waiting.")
    _require(not any("waitable" in entry for entry in user["workflow_planning"]["catalog"]["workflows"]),
             "With the wait off no catalog entry is flagged.")
    _require(kind == "plan" and "workflow_run_waits" not in plan, "With the wait off nothing waits.")
    _require("workflow_run" not in [step["capability_id"] for step in plan["steps"]],
             "With the wait off a run step that is read is dropped, as before.")


def test_the_hint_is_withheld_when_no_plan_could_wait(monkeypatch, wf):
    """With no quick workflow in the catalog, the prompt is the one without waits."""
    instructions = importlib.import_module("functions_orchestration_planner").WORKFLOW_RUN_WAIT_INSTRUCTIONS
    planning = _build(wf, [], CONTEXT_ON, wait_workflows=_wait_reader([], quick=()))
    handle = _handle(planning, "Weekly digest")
    record = _record()
    _plan_request(monkeypatch, planning, [_raw_plan([_run(handle), {
        "step_id": "answer", "capability_id": "compose",
        "arguments": {"instruction": "Say the digest started.", "knowledge_basis": "general_knowledge"},
        "inputs": {}, "outputs": [{"name": "answer", "kind": "markdown-v1"}],
    }])], record, settings=PLANNER_ON)
    _require(instructions not in record.calls[0][0]["content"], "No quick workflow: no wait instructions.")


def test_a_plan_revision_checks_the_marker_again(modules, monkeypatch, schema, wf):
    """A revised plan keeps its wait only while the wait is still configured."""
    editing = importlib.import_module("functions_orchestration_plan_editing")
    monkeypatch.setattr(editing, "resolve_agent_catalog", lambda *args, **kwargs: [])
    monkeypatch.setattr(editing, "resolve_action_catalog", lambda *args, **kwargs: [])
    planning = _build(wf, [], CONTEXT_ON, wait_workflows=_wait_reader([]))
    ready = deepcopy(planning)
    ready["workflow_run_wait"]["headless_capability_ids"] = list(HEADLESS)
    handle = _handle(planning, "Weekly digest")
    plan = _normalize(schema, ready, [_run(handle), _reader_answer()])
    context = {
        "conversation_id": "conversation-1", "turn_id": "turn-1", "user_message": "Run my digest.",
        "resolved_message": "Run my digest.", "seeds": {}, "planner_contract_version": 2,
        "workflow_planning": planning,
    }
    checked = editing.validate_edited_plan(deepcopy(plan), deepcopy(context), OWNER, deepcopy(PLANNER_ON), deepcopy(IDENTITY))
    _require(checked.get("workflow_run_waits") == plan["workflow_run_waits"], "The revision should keep the wait.")
    revisions = importlib.import_module("functions_orchestration_plan_revisions")
    try:
        editing.validate_edited_plan(
            deepcopy(plan), deepcopy(context), OWNER, {**PLANNER_ON, WAIT: False}, deepcopy(IDENTITY),
        )
    except revisions.PlanRevisionError as exc:
        cause = exc.__cause__
        _require(exc.code == "source_changed", f"Expected the unchanged-plan refusal, got {exc.code!r}.")
        _require(isinstance(cause, schema.PlanValidationError) and cause.rule == "workflow_run_consumed",
                 f"Expected the consumer rule underneath, got {cause!r}.")
    else:
        raise AssertionError("With the wait turned off a revision must not keep a waiting run step.")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
