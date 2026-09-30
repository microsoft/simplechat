#!/usr/bin/env python3
# test_orchestration_workflow_run_capability.py
"""
Functional test for the workflow_run orchestration capability and its plan checks.
Version: 0.261.211
Implemented in: 0.261.211

This test ensures that chat orchestration offers workflow_run only while starting saved workflows
from chat is turned on and available to the requester, and that a plan names each workflow to
start by a catalog handle in the run step's own arguments: never from another step's result, only
a durable workflow the request offered, each once, and at most three per plan. No step and no
answer may read a run step. A rejected run step is repaired once; after that each run step that
still breaks the rules is dropped with every binding to it, so the rest of the plan runs, and the
plan records why each workflow will not be started. The model cannot write that record, and the
planner is told about starting workflows only while the setting is on.
"""

import importlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_planning_context import AGENT_SETTINGS
from test_orchestration_workflow_planning_context import _build as _build_proposal_context
from test_orchestration_workflow_propose_capability import (
    DELIVERABLES as PROPOSAL_DELIVERABLES,
    EDIT_FAILURE,
    UNKNOWN_AGENT,
    _blueprint,
    _propose,
    _task,
)
from test_orchestration_workflow_run_planning_context import (  # noqa: F401
    DIGEST_ID,
    NOT_DURABLE_ID,
    OWNER,
    PRIVATE,
    PROPOSALS,
    RUN_SETTINGS,
    RUNS,
    SHARED_CHANGES,
    UUID_PATTERN,
    _build,
    _workflows,
    wf,
)
from test_orchestration_workflow_setting_off_golden import (
    ACTIONS,
    AGENTS,
    BASE_SETTINGS,
    CANDIDATES,
    IDENTITY,
    _binding,
    _Completions,
)
from test_support.orchestration_harness_execution import input_binding
from test_support.versioning import assert_app_version_at_least


WORKFLOW_RUN = "workflow_run"
INVALID = "workflow_run_invalid"
RUN_ONLY = {**BASE_SETTINGS, RUNS: True}
BOTH = {**BASE_SETTINGS, PROPOSALS: True, RUNS: True}
MESSAGE = "Run my weekly digest now, and tell me what to focus on this week."
# The request the planning context ranks for: it names a durable and a non-durable workflow.
NAMING_BOTH = "Run my weekly digest and the contract watcher now."
HOSTILE_NAME = '<img src=x onerror="alert(1)">'
LETTER_ID = "abcdef01-2345-4678-9abc-def012345678"
ANSWER = {
    "step_id": "answer", "capability_id": "compose",
    "arguments": {"instruction": "List what to focus on this week.", "knowledge_basis": "general_knowledge"},
    "inputs": {}, "outputs": [{"name": "answer", "kind": "markdown-v1"}],
}


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
def runs(modules):
    return importlib.import_module("functions_orchestration_workflow_runs")


@pytest.fixture
def deliverables(modules):
    return importlib.import_module("functions_orchestration_deliverables")


@pytest.fixture
def planning(wf):
    return _build(wf, [], RUN_SETTINGS, request_text=NAMING_BOTH)


def _handle(planning, name):
    return next(entry["handle"] for entry in planning["catalog"]["workflows"] if entry["name"] == name)


def _durable_handles(planning):
    return [entry["handle"] for entry in planning["catalog"]["workflows"] if entry["durable"] is True]


def _run(handle, step_id="run_digest", **extra):
    step = {
        "step_id": step_id, "capability_id": WORKFLOW_RUN, "arguments": {"workflow": handle},
        "inputs": {}, "outputs": [{"name": "run", "kind": "structured-v1"}],
    }
    step.update(deepcopy(extra))
    return step


def _raw_plan(steps, final="answer", deliverables=None):
    raw = {
        "kind": "plan", "intent": {"summary": "Start my weekly digest and list this week's priorities."},
        "steps": deepcopy(steps),
    }
    if deliverables is not None:
        raw["deliverables"] = deepcopy(deliverables)
    if final is not None:
        raw["final_response"] = input_binding(final) if isinstance(final, str) else deepcopy(final)
    return raw


def _normalize(schema, planning, steps, final="answer", *, available=("compose", "web_search", WORKFLOW_RUN)):
    return schema.normalize_plan(
        _raw_plan(steps, final), "conversation-1", OWNER, settings=deepcopy(RUN_ONLY),
        contract_version=2, available_capability_ids=list(available), workflow_planning=planning,
    )


def _rejection(schema, planning, steps, final="answer"):
    with pytest.raises(schema.PlanValidationError) as caught:
        _normalize(schema, planning, steps, final)
    return caught.value


def _step(plan, step_id):
    return next(step for step in plan["steps"] if step["step_id"] == step_id)


def _record():
    return SimpleNamespace(calls=[], logs=[])


def _secrets(planning):
    """Every workflow name, handle and record id; none of it may reach a log."""
    entries = planning["catalog"]["workflows"]
    ids = [record["id"] for record in planning["handles"]["workflows"].values()]
    return [entry["name"] for entry in entries] + [entry["handle"] for entry in entries] + ids


def _assert_logs_carry_codes_only(logs, planning):
    text = json.dumps(logs, default=str, ensure_ascii=False)
    for secret in _secrets(planning):
        assert secret not in text, secret


def _plan_request(monkeypatch, planning, replies, record, *, settings=RUN_ONLY, edit_context=None):
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
        lambda text, *args, **kwargs: record.logs.append((text, deepcopy(kwargs.get("extra")))),
    )
    return planner.plan_request(
        MESSAGE, planner_context, "conversation", OWNER, settings=deepcopy(settings),
        authorized_document_ids=["document-record-1"], revision=0, allow_elicitation=True, turn_id="turn",
        seeds={}, document_labels={"document-record-1": "Weekly priorities.docx"},
        request_context=request_context, planner_model=None, existing_results={},
        composition_profiles=services.composition_profiles(), export_catalog=[], edit_context=edit_context,
    )


def _dropped_logs(record):
    return [extra for message, extra in record.logs if "Planning without workflow runs" in message]


def test_version_includes_the_workflow_run_capability():
    assert_app_version_at_least("0.261.211")


# ---------------------------------------------------------------------------
# The capability and when it is offered
# ---------------------------------------------------------------------------

def test_the_capability_is_a_low_cost_gather_step_named_by_one_static_handle(modules, registry, runs, wf):
    adapters = importlib.import_module("functions_orchestration_adapters")
    capability = registry.get_capability(WORKFLOW_RUN, contract_version=2)
    assert capability["role"] == "gather" and capability["cost_class"] == "low"
    assert capability["label"] == "Run workflow"
    assert capability["max_per_plan"] == registry.WORKFLOW_RUNS_MAX_PER_PLAN == 3
    assert capability["result_outputs"] == {"run": "structured-v1"}
    assert capability["result_input_kinds"] == {} and capability["partial_inputs_supported"] is False
    assert capability["settings_gates"] == ("enable_chat_orchestration", "allow_user_workflows", RUNS)
    assert capability["dormant_unless_setting"] == RUNS
    # A failed start is never retried on its own: a second attempt could start a second run.
    assert not capability.get("retry_on_transient")
    assert capability["inputs"] == {
        "type": "object",
        "properties": {"workflow": {
            "type": "string", "minLength": 1, "maxLength": 64, "pattern": registry.WORKFLOW_HANDLE_PATTERN,
        }},
        "required": ["workflow"],
        "additionalProperties": False,
    }
    # One pattern: the planning context issues handles with it, and the plan checks read it.
    assert registry.WORKFLOW_HANDLE_PATTERN == wf._HANDLE_RE.pattern == runs._HANDLE.pattern
    assert adapters.ADAPTER_REGISTRY[WORKFLOW_RUN] is adapters.run_workflow_run


def test_every_handle_the_context_issues_is_a_valid_argument(runs, planning):
    handles = [entry["handle"] for entry in planning["catalog"]["workflows"]]
    matched = [bool(runs._HANDLE.fullmatch(handle)) for handle in handles]
    assert handles and all(matched)
    assert list(planning["handles"]["workflows"]) == handles


def _available(registry, settings, request_context):
    unavailable = {}
    ids = [
        capability["id"] for capability in registry.resolve_available_capabilities(
            settings, request_context=request_context, candidate_ids=[WORKFLOW_RUN], unavailable=unavailable,
        )
    ]
    return ids, unavailable


@pytest.mark.parametrize("value", ["missing", False, "true", 1, None])
def test_the_capability_is_dormant_until_the_setting_is_exactly_true(registry, planning, value):
    settings = deepcopy(RUN_SETTINGS)
    if value == "missing":
        settings.pop(RUNS)
    else:
        settings[RUNS] = value
    ids, unavailable = _available(registry, settings, {"user_roles": ["User"], "workflow_planning": planning})
    deployment = registry.resolve_available_capability_ids(settings, candidate_ids=[WORKFLOW_RUN])
    everything = registry.resolve_available_capability_ids(settings)
    # Dormant: skipped before every other check, with no reason the planner could be told, even
    # though the empty capability allowlist admits every capability.
    assert settings["chat_orchestration_enabled_capabilities"] == []
    assert ids == [] and unavailable == {}
    assert deployment == [] and WORKFLOW_RUN not in everything


def test_a_ready_private_request_may_start_a_workflow(registry, planning):
    ids, unavailable = _available(registry, RUN_SETTINGS, {"user_roles": ["User"], "workflow_planning": planning})
    # Without a request, the answer describes the deployment for the admin surface.
    deployment = registry.resolve_available_capability_ids(RUN_SETTINGS, candidate_ids=[WORKFLOW_RUN])
    assert ids == [WORKFLOW_RUN] and unavailable == {}
    assert deployment == [WORKFLOW_RUN]


def _fail_read(*args):
    raise RuntimeError("storage failed")


def _unavailable_case(wf, case):
    settings, roles = deepcopy(RUN_SETTINGS), ["User"]
    planning = _build(wf, [], RUN_SETTINGS)
    if case == "no_context":
        planning = None
    elif case == "failed_read":
        planning = _build(wf, [], RUN_SETTINGS, workflows=_fail_read)
    elif case == "role":
        settings["require_member_of_workflow_user"] = True
    elif case == "workflows_off":
        settings["allow_user_workflows"] = False
    elif case == "orchestration_off":
        settings["enable_chat_orchestration"] = False
    elif case == "allowlist":
        settings["chat_orchestration_enabled_capabilities"] = ["compose"]
    elif case == "proposal_allowlist":
        settings["chat_orchestration_enabled_capabilities"] = ["compose", "workflow_propose"]
    elif case == "made_shared":
        # Planned in a private conversation that became shared before the plan ran.
        planning = importlib.import_module("functions_orchestration_workflow_context").refresh_workflow_planning_privacy(
            planning, {**PRIVATE, "chat_type": "personal_multi_user"}, OWNER,
        )
    context = {"user_roles": roles}
    if planning is not None:
        context["workflow_planning"] = planning
    return settings, context


@pytest.mark.parametrize(("case", "reason"), [
    ("no_context", "workflow_context_unavailable"),
    ("failed_read", "workflow_context_unavailable"),
    ("role", "workflow_role_required"),
    ("workflows_off", "feature_disabled"),
    ("orchestration_off", "feature_disabled"),
    ("allowlist", "not_enabled_for_orchestration"),
    ("proposal_allowlist", "not_enabled_for_orchestration"),
    ("made_shared", "workflow_shared_conversation"),
])
def test_an_unavailable_request_records_one_closed_reason(registry, wf, case, reason):
    settings, context = _unavailable_case(wf, case)
    ids, unavailable = _available(registry, settings, context)
    assert ids == [] and unavailable == {WORKFLOW_RUN: reason}


@pytest.mark.parametrize("changes", SHARED_CHANGES)
def test_a_shared_or_collaborative_conversation_never_offers_it(registry, wf, changes):
    calls = []
    planning = _build(wf, calls, RUN_SETTINGS, conversation={**PRIVATE, **changes})
    ids, unavailable = _available(registry, RUN_SETTINGS, {"user_roles": ["User"], "workflow_planning": planning})
    assert calls == []
    assert ids == [] and unavailable == {WORKFLOW_RUN: "workflow_shared_conversation"}


def test_the_proposal_cap_does_not_make_starting_a_workflow_unavailable(registry, wf):
    settings = {**RUN_SETTINGS, PROPOSALS: True, "chat_orchestration_max_workflows_per_user": 2}
    planning = _build(wf, [], settings, quota_count=lambda user_id: 2)
    unavailable = {}
    ids = [
        capability["id"] for capability in registry.resolve_available_capabilities(
            settings, request_context={"user_roles": ["User"], "workflow_planning": planning},
            candidate_ids=["workflow_propose", WORKFLOW_RUN], unavailable=unavailable,
        )
    ]
    assert planning["quota_reached"] is True
    assert ids == [WORKFLOW_RUN] and unavailable == {"workflow_propose": "workflow_quota_reached"}


def test_the_workflow_user_role_and_an_allowlist_that_names_it_admit_the_capability(registry, planning):
    settings = {
        **RUN_SETTINGS, "require_member_of_workflow_user": True,
        "chat_orchestration_enabled_capabilities": ["compose", WORKFLOW_RUN],
    }
    ids, unavailable = _available(registry, settings, {"user_roles": ["User", "WorkflowUser"], "workflow_planning": planning})
    assert ids == [WORKFLOW_RUN] and unavailable == {}


def test_a_failing_access_check_never_raises_and_logs_only_the_error_type(registry, wf, planning, monkeypatch):
    logged = []
    monkeypatch.setattr(registry, "log_event", lambda message, **kwargs: logged.append((message, kwargs)))

    def fail(*args, **kwargs):
        raise RuntimeError("catalog text Weekly digest")

    monkeypatch.setattr(wf, "workflow_run_unavailable_reason", fail)
    ids, unavailable = _available(registry, RUN_SETTINGS, {"user_roles": ["User"], "workflow_planning": planning})
    assert ids == [] and unavailable == {WORKFLOW_RUN: "workflow_context_unavailable"}
    assert logged and logged[0][1]["extra"] == {"reason": "workflow_context_unavailable", "error_type": "RuntimeError"}
    assert "Weekly digest" not in json.dumps(logged, default=str)


# ---------------------------------------------------------------------------
# Plan checks
# ---------------------------------------------------------------------------

def test_a_valid_run_step_names_a_durable_workflow_the_request_offered(schema, planning):
    digest = _handle(planning, "Weekly digest")
    plan = _normalize(schema, planning, [ANSWER, _run(digest)])
    step = _step(plan, "run_digest")
    assert (step["role"], step["estimated_cost"], step["title"]) == ("gather", "low", "Run workflow")
    assert step["arguments"] == {"workflow": digest}
    assert step["depends_on"] == [] and step["inputs"] == {}
    assert step["outputs"] == [{"name": "run", "kind": "structured-v1"}]
    assert "delivers" not in step and plan["final_response"]["step_id"] == "answer"
    # The plan names the workflow by its handle only; the record id stays in the server's map.
    assert DIGEST_ID not in json.dumps(plan)


def test_a_paused_workflow_may_be_started(schema, planning):
    entry = next(entry for entry in planning["catalog"]["workflows"] if entry["name"] == "Weekly digest")
    plan = _normalize(schema, planning, [ANSWER, _run(entry["handle"])])
    assert entry["enabled"] is False
    assert [step["capability_id"] for step in plan["steps"]] == ["compose", WORKFLOW_RUN]


def test_a_plan_that_only_starts_a_workflow_needs_no_deliverable_and_no_answer(schema, planning):
    plan = _normalize(schema, planning, [_run(_handle(planning, "Weekly digest"))], final=None)
    assert [step["capability_id"] for step in plan["steps"]] == [WORKFLOW_RUN]
    assert "final_response" not in plan or plan["final_response"] is None
    assert [deliverable["kind"] for deliverable in plan["deliverables"]] == ["answer"]


@pytest.mark.parametrize("shape", [
    "depends_on", "bound_input", "bound_argument", "extra_argument", "no_argument", "record_id",
    "saved_name", "search_result",
])
def test_a_run_step_names_its_workflow_in_its_own_arguments_only(schema, planning, shape):
    digest = _handle(planning, "Weekly digest")
    steps = [ANSWER]
    if shape == "depends_on":
        run = _run(digest, depends_on=["answer"])
    elif shape == "bound_input":
        run = _run(digest, inputs={"workflow": {"binding": input_binding("answer")}})
    elif shape == "bound_argument":
        run = _run(digest, arguments={"workflow": {"binding": input_binding("answer")}})
    elif shape == "extra_argument":
        run = _run(digest, arguments={"workflow": digest, "note": "now"})
    elif shape == "no_argument":
        run = _run(digest, arguments={})
    elif shape == "record_id":
        run = _run(digest, arguments={"workflow": DIGEST_ID})
    elif shape == "saved_name":
        run = _run(digest, arguments={"workflow": "Weekly digest"})
    else:
        # Web, email or document content can never choose which workflow runs.
        steps = [ANSWER, {
            "step_id": "search", "capability_id": "web_search", "arguments": {"query": "which workflow"},
            "inputs": {},
        }]
        run = _run(digest, inputs={"workflow": {"binding": input_binding("search", "results")}})
    error = _rejection(schema, planning, [*steps, run])
    assert (error.code, error.rule) == (INVALID, "workflow_run_static_input")
    for secret in _secrets(planning):
        assert secret not in str(error)


@pytest.mark.parametrize("handle", [
    "workflow-not-offered-abc123", "propose", "answer", "run_digest",
])
def test_a_run_step_names_only_a_workflow_the_request_offered(schema, planning, handle):
    error = _rejection(schema, planning, [ANSWER, _run(handle)])
    other = _rejection(schema, planning, [ANSWER, _run("workflow-something-else")])
    assert (error.code, error.rule) == (INVALID, "workflow_run_unknown")
    # Closed text: the message is the same whichever handle the planner wrote.
    assert str(error) == str(other) and "workflow-" not in str(error)


def test_a_record_id_that_fits_the_handle_pattern_is_still_unknown(schema, runs, wf):
    def letter_workflows(user_id):
        return [{
            "id": LETTER_ID, "name": "Weekly digest", "trigger_type": "manual", "is_enabled": True,
            "durable_execution": True, "updated_at": "2026-09-01T00:00:00+00:00",
        }]

    planning = _build(wf, [], RUN_SETTINGS, workflows=letter_workflows)
    fits = bool(runs._HANDLE.fullmatch(LETTER_ID))
    assert fits
    error = _rejection(schema, planning, [ANSWER, _run(LETTER_ID)])
    assert (error.code, error.rule) == (INVALID, "workflow_run_unknown")
    plan = _normalize(schema, planning, [ANSWER, _run(_handle(planning, "Weekly digest"))])
    assert LETTER_ID not in json.dumps(plan)


def test_the_catalog_entry_needs_both_the_catalog_and_a_record_id(runs, planning):
    digest = _handle(planning, "Weekly digest")
    found = runs.workflow_run_catalog_entry(planning, digest)
    no_record = deepcopy(planning)
    no_record["handles"]["workflows"][digest] = {"id": " "}
    not_listed = deepcopy(planning)
    not_listed["catalog"]["workflows"] = [
        entry for entry in not_listed["catalog"]["workflows"] if entry["handle"] != digest
    ]
    missing = [
        runs.workflow_run_catalog_entry(no_record, digest),
        runs.workflow_run_catalog_entry(not_listed, digest),
        runs.workflow_run_catalog_entry(planning, None),
        runs.workflow_run_catalog_entry(None, digest),
        runs.workflow_run_catalog_entry({"handles": "x", "catalog": "y"}, digest),
    ]
    assert found["name"] == "Weekly digest"
    assert missing == [None] * 5


def test_a_workflow_without_durable_execution_cannot_be_started_from_chat(schema, planning):
    error = _rejection(schema, planning, [ANSWER, _run(_handle(planning, "Contract watcher"), step_id="run_watcher")])
    assert (error.code, error.rule) == (INVALID, "workflow_not_durable")
    assert "Contract watcher" not in str(error)


def test_a_plan_starts_each_workflow_once(schema, planning):
    digest = _handle(planning, "Weekly digest")
    error = _rejection(schema, planning, [ANSWER, _run(digest), _run(digest, step_id="run_again")])
    assert (error.code, error.rule) == (INVALID, "workflow_run_duplicate")


def test_a_plan_starts_at_most_three_workflows(schema, planning):
    handles = _durable_handles(planning)[:4]
    steps = [_run(handle, step_id=f"run_{index}") for index, handle in enumerate(handles)]
    plan = _normalize(schema, planning, [ANSWER, *steps[:3]])
    error = _rejection(schema, planning, [ANSWER, *steps])
    assert len(handles) == 4
    assert [step["capability_id"] for step in plan["steps"]].count(WORKFLOW_RUN) == 3
    assert (error.code, error.rule) == (INVALID, "workflow_run_limit")


@pytest.mark.parametrize("wiring", ["input", "depends_on", "final_response"])
def test_no_other_step_or_final_response_may_read_a_run_step(schema, planning, wiring):
    answer, final = deepcopy(ANSWER), "answer"
    if wiring == "input":
        answer["inputs"] = {"run": {"binding": input_binding("run_digest", "run")}}
    elif wiring == "depends_on":
        answer["depends_on"] = ["run_digest"]
    else:
        final = input_binding("run_digest", "run")
    error = _rejection(schema, planning, [answer, _run(_handle(planning, "Weekly digest"))], final)
    assert (error.code, error.rule) == (INVALID, "workflow_run_consumed")


@pytest.mark.parametrize("context", ["empty", "shared", "marker_missing"])
def test_a_new_plan_without_a_ready_context_gets_the_context_rule(schema, planning, context):
    digest = _handle(planning, "Weekly digest")
    broken = {"empty": {}, "shared": {**planning, "conversation_private": False}}.get(context)
    if broken is None:
        broken = {key: value for key, value in planning.items() if key != "workflow_runs"}
    error = _rejection(schema, broken, [ANSWER, _run(digest)])
    assert (error.code, error.rule) == (INVALID, "workflow_context_unavailable")


def test_a_run_step_is_checked_against_the_context_even_at_the_proposal_cap(schema, wf):
    settings = {**RUN_SETTINGS, PROPOSALS: True, "chat_orchestration_max_workflows_per_user": 2}
    at_cap = _build(wf, [], settings, quota_count=lambda user_id: 2, request_text=NAMING_BOTH)
    plan = _normalize(schema, at_cap, [ANSWER, _run(_handle(at_cap, "Weekly digest"))])
    error = _rejection(schema, at_cap, [ANSWER, _run(_handle(at_cap, "Contract watcher"))])
    assert at_cap["quota_reached"] is True
    assert [step["capability_id"] for step in plan["steps"]] == ["compose", WORKFLOW_RUN]
    assert error.rule == "workflow_not_durable"


def test_a_stored_plan_is_rechecked_for_its_shape_but_not_its_catalog(schema, runs, planning):
    digest = _handle(planning, "Weekly digest")
    plan = _normalize(schema, planning, [ANSWER, _run(digest)])
    revalidated = schema.normalize_plan(
        deepcopy(plan), "conversation-1", OWNER, settings=deepcopy(RUN_ONLY), contract_version=2,
        available_capability_ids=["compose", WORKFLOW_RUN],
    )
    # Without the context, the step resolves and checks its workflow again when it runs.
    kept = runs.prepare_workflow_run_arguments({}, {"workflow": "workflow-anything"}, seen=set())
    with pytest.raises(schema.PlanValidationError) as caught:
        runs.prepare_workflow_run_arguments({"depends_on": ["answer"]}, {"workflow": digest}, seen=set())
    assert _step(revalidated, "run_digest")["arguments"] == {"workflow": digest}
    assert kept == {"workflow": "workflow-anything"}
    assert caught.value.rule == "workflow_run_static_input"


# ---------------------------------------------------------------------------
# Degrading a plan
# ---------------------------------------------------------------------------

def test_dropping_run_steps_checks_each_one_and_keeps_the_good_ones(runs, planning):
    digest, watcher = _handle(planning, "Weekly digest"), _handle(planning, "Contract watcher")
    raw = _raw_plan([
        ANSWER, _run("workflow-not-offered-abc123", step_id="run_unknown"), _run(digest),
        _run(digest, step_id="run_again"), _run(watcher, step_id="run_watcher"),
    ])
    before = deepcopy(raw)
    plan, notes, remaining = runs.drop_workflow_runs(raw, workflow_planning=planning)
    assert raw == before
    assert [step["step_id"] for step in plan["steps"]] == ["answer", "run_digest"]
    assert remaining == 1
    assert notes == [
        {"reason": "workflow_run_unknown", "name": None},
        {"reason": "workflow_run_duplicate", "name": "Weekly digest"},
        {"reason": "workflow_not_durable", "name": "Contract watcher"},
    ]


def test_dropping_a_run_step_that_is_read_removes_every_binding_to_it(runs, planning):
    digest = _handle(planning, "Weekly digest")
    answer = dict(deepcopy(ANSWER), depends_on=["run_digest"], inputs={
        "run": {"binding": input_binding("run_digest", "run")},
        "notes": {"binding": input_binding("answer_notes")},
    })
    raw = _raw_plan([answer, _run(digest)], final=input_binding("run_digest", "run"))
    plan, notes, remaining = runs.drop_workflow_runs(raw, workflow_planning=planning)
    kept = plan["steps"][0]
    assert [step["step_id"] for step in plan["steps"]] == ["answer"] and remaining == 0
    assert kept["depends_on"] == [] and list(kept["inputs"]) == ["notes"]
    assert "final_response" not in plan
    assert notes == [{"reason": "workflow_run_invalid", "name": "Weekly digest"}]


def test_only_the_run_step_another_step_reads_is_dropped(runs, planning):
    digest = _handle(planning, "Weekly digest")
    other = next(handle for handle in _durable_handles(planning) if handle != digest)
    answer = dict(deepcopy(ANSWER), depends_on=["run_digest"])
    raw = _raw_plan([answer, _run(digest), _run(other, step_id="run_other")])
    plan, notes, remaining = runs.drop_workflow_runs(raw, workflow_planning=planning)
    assert [step["step_id"] for step in plan["steps"]] == ["answer", "run_other"]
    assert plan["steps"][0]["depends_on"] == [] and remaining == 1
    assert notes == [{"reason": "workflow_run_invalid", "name": "Weekly digest"}]


def test_dropping_everything_when_the_context_cannot_be_checked(runs, planning):
    digest, watcher = _handle(planning, "Weekly digest"), _handle(planning, "Contract watcher")
    raw = _raw_plan([ANSWER, _run(digest), _run(watcher, step_id="run_watcher")])
    plan, notes, remaining = runs.drop_workflow_runs(raw, workflow_planning=None, drop_all=True)
    assert [step["step_id"] for step in plan["steps"]] == ["answer"] and remaining == 0
    assert notes == [{"reason": "workflow_context_unavailable", "name": None}]


def test_when_no_single_run_step_fails_every_one_is_dropped(runs, planning):
    raw = _raw_plan([ANSWER, _run(_handle(planning, "Weekly digest"))])
    plan, notes, remaining = runs.drop_workflow_runs(raw, workflow_planning=planning)
    assert [step["step_id"] for step in plan["steps"]] == ["answer"] and remaining == 0
    assert notes == [{"reason": "workflow_run_invalid", "name": "Weekly digest"}]


def test_the_texts_are_closed_and_names_only_reach_the_plan_card(runs):
    named = runs.workflow_run_repair_text({"reason": "workflow_not_durable", "name": HOSTILE_NAME})
    unnamed = runs.workflow_run_repair_text({"reason": "not-a-reason", "name": None})
    failure = runs.workflow_run_failure_message([
        {"reason": "workflow_not_durable", "name": HOSTILE_NAME},
        {"reason": "workflow_not_durable", "name": "Other"},
        {"reason": "invented", "name": None},
    ])
    assert named == f'"{HOSTILE_NAME}" will not be started. {runs.WORKFLOW_RUN_SKIP_REASONS["workflow_not_durable"]}'
    assert unnamed == runs.WORKFLOW_RUN_SKIP_REASONS["workflow_run_invalid"]
    # The failure message may render as Markdown, so it never carries a name.
    assert failure == f'No workflow was started. {runs.WORKFLOW_RUN_SKIP_REASONS["workflow_not_durable"]}'
    assert "Select Run" not in failure and "select Run" in failure


# ---------------------------------------------------------------------------
# Planning: offer, repair, degrade
# ---------------------------------------------------------------------------

def test_the_planner_is_offered_the_capability_and_only_the_workflows_catalog(monkeypatch, planner, planning):
    digest = _handle(planning, "Weekly digest")
    record = _record()
    kind, plan = _plan_request(monkeypatch, planning, [_raw_plan([ANSWER, _run(digest)])], record)
    assert kind == "plan"
    assert [step["capability_id"] for step in plan["steps"]] == ["compose", WORKFLOW_RUN]
    assert len(record.calls) == 1
    system, user = record.calls[0][0]["content"], record.calls[0][1]["content"]
    payload = json.loads(user)
    assert planner.WORKFLOW_RUN_INSTRUCTIONS in system
    assert planner.WORKFLOW_PROPOSAL_INSTRUCTIONS not in system
    assert payload["workflow_planning"] == {"catalog": {"workflows": planning["catalog"]["workflows"]}}
    assert not UUID_PATTERN.search(system) and not UUID_PATTERN.search(user)
    assert "workflow_run starts one of the user's saved workflows" in user
    _assert_logs_carry_codes_only(record.logs, planning)


def test_with_both_settings_the_planner_gets_both_instructions(monkeypatch, planner, wf):
    planning = _build_proposal_context(wf, [], {**AGENT_SETTINGS, RUNS: True})
    record = _record()
    kind, _plan = _plan_request(monkeypatch, planning, [_raw_plan([ANSWER])], record, settings=BOTH)
    system = record.calls[0][0]["content"]
    payload = json.loads(record.calls[0][1]["content"])
    assert kind == "plan"
    assert planner.WORKFLOW_PROPOSAL_INSTRUCTIONS in system and planner.WORKFLOW_RUN_INSTRUCTIONS in system
    assert set(payload["workflow_planning"]["catalog"]) == {"agents", "sources", "documents", "workflows"}


def test_with_only_proposals_the_planner_is_never_told_about_runs(monkeypatch, planner, wf):
    planning = _build_proposal_context(wf, [])
    record = _record()
    _plan_request(monkeypatch, planning, [_raw_plan([ANSWER])], record, settings={**BASE_SETTINGS, PROPOSALS: True})
    system, user = record.calls[0][0]["content"], record.calls[0][1]["content"]
    assert planner.WORKFLOW_RUN_INSTRUCTIONS not in system and WORKFLOW_RUN not in system
    assert "saved workflows" not in user.lower()


def test_a_rejected_run_step_is_repaired_once_with_fixed_text(monkeypatch, planning):
    bad, good = _run("workflow-not-offered-abc123"), _run(_handle(planning, "Weekly digest"))
    record = _record()
    kind, plan = _plan_request(monkeypatch, planning, [_raw_plan([ANSWER, bad]), _raw_plan([ANSWER, good])], record)
    assert kind == "plan" and _step(plan, "run_digest")["arguments"] == good["arguments"]
    assert len(record.calls) == 2
    repair = record.calls[1][-1]["content"]
    assert repair.startswith("The server rejected a workflow_run step in that plan: ")
    assert "workflow-not-offered-abc123" not in repair
    asked = [extra for message, extra in record.logs if "correct a rejected plan" in message]
    assert [(extra["validation_code"], extra["validation_rule"]) for extra in asked] == [(INVALID, "workflow_run_unknown")]
    assert "workflow_run_notes" not in plan and not _dropped_logs(record)
    _assert_logs_carry_codes_only(record.logs, planning)


def test_an_unrepaired_run_step_is_dropped_and_the_rest_of_the_plan_runs(monkeypatch, runs, planning):
    digest, watcher = _handle(planning, "Weekly digest"), _handle(planning, "Contract watcher")
    reply = _raw_plan([ANSWER, _run(digest), _run(watcher, step_id="run_watcher")])
    record = _record()
    kind, plan = _plan_request(monkeypatch, planning, [reply, reply], record)
    assert kind == "plan" and len(record.calls) == 2
    assert [step["step_id"] for step in plan["steps"]] == ["answer", "run_digest"]
    assert plan["final_response"]["step_id"] == "answer"
    assert plan["workflow_run_notes"] == [{"reason": "workflow_not_durable", "name": "Contract watcher"}]
    assert runs.workflow_run_repair_text(plan["workflow_run_notes"][0]) in plan["validation"]["repairs"]
    dropped = _dropped_logs(record)
    assert len(dropped) == 1
    assert (dropped[0]["reason"], dropped[0]["validation_rule"]) == ("workflow_run_dropped", "workflow_not_durable")
    assert (dropped[0]["note_count"], dropped[0]["remaining_count"]) == (1, 1)
    _assert_logs_carry_codes_only(record.logs, planning)


def test_a_run_step_that_is_read_is_dropped_with_every_binding_to_it(monkeypatch, planning):
    answer = dict(deepcopy(ANSWER), depends_on=["run_digest"], inputs={"run": {"binding": input_binding("run_digest", "run")}})
    reply = _raw_plan([answer, _run(_handle(planning, "Weekly digest"))])
    record = _record()
    kind, plan = _plan_request(monkeypatch, planning, [reply, reply], record)
    kept = plan["steps"][0]
    assert kind == "plan" and [step["step_id"] for step in plan["steps"]] == ["answer"]
    assert kept["depends_on"] == [] and kept["inputs"] == {}
    assert plan["workflow_run_notes"] == [{"reason": "workflow_run_invalid", "name": "Weekly digest"}]
    _assert_logs_carry_codes_only(record.logs, planning)


@pytest.mark.parametrize("name", ["Weekly digest", "Contract watcher"])
def test_a_plan_left_with_nothing_to_do_fails_with_fixed_text(monkeypatch, planner, runs, planning, name):
    handle = _handle(planning, name) if name == "Contract watcher" else "workflow-not-offered-abc123"
    reply = _raw_plan([_run(handle)], final=None)
    record = _record()
    with pytest.raises(planner.PlannerError) as caught:
        _plan_request(monkeypatch, planning, [reply, reply], record)
    reason = "workflow_not_durable" if name == "Contract watcher" else "workflow_run_unknown"
    assert caught.value.reason == "invalid_plan_or_missing_requirement"
    assert caught.value.message == runs.workflow_run_failure_message([{"reason": reason, "name": None}])
    assert name not in caught.value.message
    assert len(record.calls) == 2 and not _dropped_logs(record)
    _assert_logs_carry_codes_only(record.logs, planning)


def test_a_context_that_cannot_be_checked_drops_every_run_step_without_a_repair_round(monkeypatch, runs, planning):
    monkeypatch.setattr(runs, "workflow_run_ready", lambda context: False)
    reply = _raw_plan([ANSWER, _run(_handle(planning, "Weekly digest"))])
    record = _record()
    kind, plan = _plan_request(monkeypatch, planning, [reply], record)
    assert kind == "plan" and len(record.calls) == 1
    assert [step["capability_id"] for step in plan["steps"]] == ["compose"]
    assert plan["workflow_run_notes"] == [{"reason": "workflow_context_unavailable", "name": "Weekly digest"}]
    assert _dropped_logs(record)[0]["validation_rule"] == "workflow_context_unavailable"


def test_a_plan_edit_with_a_broken_run_step_keeps_the_previous_plan(monkeypatch, planner, planning):
    reply = dict(
        _raw_plan([ANSWER, _run(_handle(planning, "Contract watcher"))]),
        revised_request="Also run the contract watcher.",
    )
    record = _record()
    with pytest.raises(planner.PlannerError) as caught:
        _plan_request(monkeypatch, planning, [reply, reply], record,
                      edit_context={"instruction": "Run the watcher too.", "current_plan": {}})
    assert caught.value.message == EDIT_FAILURE
    assert not _dropped_logs(record)


def test_the_model_cannot_write_why_a_workflow_was_not_started(monkeypatch, planning):
    forged = [{"reason": "workflow_not_durable", "name": HOSTILE_NAME}]
    clean = dict(_raw_plan([ANSWER, _run(_handle(planning, "Weekly digest"))]), workflow_run_notes=forged)
    record = _record()
    kind, plan = _plan_request(monkeypatch, planning, [clean], record)
    assert kind == "plan" and "workflow_run_notes" not in plan

    broken = dict(_raw_plan([ANSWER, _run(_handle(planning, "Contract watcher"))]), workflow_run_notes=forged)
    record = _record()
    kind, plan = _plan_request(monkeypatch, planning, [broken, broken], record)
    assert kind == "plan"
    assert plan["workflow_run_notes"] == [{"reason": "workflow_not_durable", "name": "Contract watcher"}]
    assert HOSTILE_NAME not in json.dumps(plan)


def test_after_a_proposal_is_dropped_the_run_steps_are_still_checked(monkeypatch, wf):
    planning = _build_proposal_context(wf, [], {**AGENT_SETTINGS, RUNS: True})
    watcher = _handle(planning, "Contract watcher")
    bad_proposal = _propose(_blueprint(planning, tasks=[_task(UNKNOWN_AGENT)]))
    reply = _raw_plan(
        [ANSWER, bad_proposal, _run(watcher, step_id="run_watcher")], deliverables=PROPOSAL_DELIVERABLES,
    )
    record = _record()
    kind, plan = _plan_request(monkeypatch, planning, [reply, reply], record, settings=BOTH)
    workflow = next(entry for entry in plan["deliverables"] if entry["kind"] == "workflow")
    assert kind == "plan" and [step["step_id"] for step in plan["steps"]] == ["answer"]
    assert workflow["status"] == "unavailable"
    assert plan["workflow_run_notes"] == [{"reason": "workflow_not_durable", "name": "Contract watcher"}]
    messages = [message for message, _extra in record.logs]
    assert any("Planning without a workflow proposal" in message for message in messages)
    assert _dropped_logs(record)[0]["validation_rule"] == "workflow_not_durable"


# ---------------------------------------------------------------------------
# What the planner is told about deliverables
# ---------------------------------------------------------------------------

def _truth(deliverables, settings, available, unavailable=None):
    return deliverables.build_deliverable_availability(
        settings, capabilities=[{"id": capability_id} for capability_id in available], unavailable=unavailable or {},
    )


def test_starting_workflows_is_described_only_while_the_setting_is_on(deliverables):
    base = _truth(deliverables, BASE_SETTINGS, ["compose"])
    off = [
        _truth(deliverables, {**BASE_SETTINGS, RUNS: value}, ["compose", WORKFLOW_RUN])
        for value in (False, "true", 1, None)
    ]
    on = _truth(deliverables, RUN_ONLY, ["compose", WORKFLOW_RUN])
    assert all(truth == base for truth in off)
    assert "workflow" not in json.dumps(base).lower()
    added_facts = [fact for fact in on["facts"] if fact not in base["facts"]]
    added_recipes = [recipe for recipe in on["recipes"] if recipe not in base["recipes"]]
    assert len(added_facts) == 1 and added_facts[0].startswith("workflow_run starts one of the user's saved workflows")
    assert "never say that a workflow started, ran or finished" in added_facts[0]
    assert [recipe["for"] for recipe in added_recipes] == ["A saved workflow the user asks to run now"]
    assert on["unavailable_reasons"] == base["unavailable_reasons"] and "workflow" not in on


@pytest.mark.parametrize(("reason", "text_key"), [
    ("not_enabled_for_orchestration", "capability_not_enabled_for_orchestration"),
    ("workflow_shared_conversation", "workflow_shared_conversation"),
    ("workflow_role_required", "workflow_role_required"),
    ("workflow_context_unavailable", "workflow_context_unavailable"),
    ("workflow_runs_disabled", "workflow_runs_disabled"),
    ("feature_disabled", "workflow_runs_disabled"),
    (None, "workflow_runs_disabled"),
])
def test_an_unavailable_run_is_explained_with_closed_text(deliverables, reason, text_key):
    unavailable = {WORKFLOW_RUN: reason} if reason is not None else {}
    base = _truth(deliverables, BASE_SETTINGS, ["compose"], unavailable)
    truth = _truth(deliverables, RUN_ONLY, ["compose"], unavailable)
    added = [fact for fact in truth["facts"] if fact not in base["facts"]]
    assert added == [
        "Starting saved workflows is unavailable for this request. "
        f"{deliverables.WORKFLOW_RUN_UNAVAILABLE_REASONS[text_key]} "
        "When the user asks to run a workflow, say why in the answer."
    ]
    assert truth["recipes"] == base["recipes"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
