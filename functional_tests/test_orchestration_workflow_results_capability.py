# test_orchestration_workflow_results_capability.py
"""
Functional test for the workflow_results orchestration capability (registry, gates, catalog, schema, planner).
Version: 0.261.217
Implemented in: 0.261.217

This test ensures stored workflow results are offered, planned, validated, degraded, and surfaced only through the approved read-only workflow_results path.
"""

import importlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_orchestration_harness_routes import modules  # noqa: E402,F401
from test_orchestration_workflow_run_capability import (  # noqa: E402
    ANSWER,
    CANDIDATES,
    IDENTITY,
    MESSAGE,
    _Completions,
    _binding,
    _handle,
    _raw_plan,
    _record,
    _run,
)
from test_orchestration_workflow_run_planning_context import (  # noqa: E402,F401
    DIGEST_ID,
    OWNER,
    PROPOSALS,
    RUNS,
    UUID_PATTERN,
    _build,
    _fail,
    wf,
)
from test_support.orchestration_harness_execution import input_binding, render_step  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


WORKFLOW_RESULTS = "workflow_results"
RESULTS = "enable_chat_workflow_results"
INVALID = "workflow_results_invalid"
RESULTS_ONLY = {
    "enable_chat_orchestration": True,
    RESULTS: True,
    "allow_user_workflows": True,
    "require_member_of_workflow_user": False,
    "chat_orchestration_enabled_capabilities": [],
}
PROPOSALS_RESULTS = {**RESULTS_ONLY, PROPOSALS: True}
RUNS_RESULTS = {**RESULTS_ONLY, RUNS: True}
ALL_WORKFLOW_SETTINGS = {**RESULTS_ONLY, PROPOSALS: True, RUNS: True}
AVAILABLE = ("compose", "web_search", "workflow_run", WORKFLOW_RESULTS, "render_file")
LOCAL_ZONE = "America/New_York"


@pytest.fixture
def registry(modules):
    return importlib.import_module("functions_orchestration_registry")


@pytest.fixture
def schema(modules):
    return importlib.import_module("functions_orchestration_schema")


@pytest.fixture
def planner(modules):
    return importlib.import_module("functions_orchestration_planner")


@pytest.fixture
def results(modules):
    return importlib.import_module("functions_orchestration_workflow_results")


@pytest.fixture
def deliverables(modules):
    return importlib.import_module("functions_orchestration_deliverables")


@pytest.fixture
def admin_fields(modules):
    return importlib.import_module("admin_settings_fields")


@pytest.fixture
def planning(wf):
    return _build(wf, [], RESULTS_ONLY, request_text="What did my weekly digest find?")


def _result(handle, step_id="read_digest", **extra):
    step = {
        "step_id": step_id,
        "capability_id": WORKFLOW_RESULTS,
        "arguments": {"workflow": handle, "selector": "latest"},
        "inputs": {},
        "outputs": [{"name": "result", "kind": "structured-v1"}],
    }
    step.update(deepcopy(extra))
    return step


def _answer_from(step_id="read_digest", output="result", *, step_id_answer="answer"):
    answer = deepcopy(ANSWER)
    answer["step_id"] = step_id_answer
    answer["inputs"] = {"workflow_notes": {"binding": input_binding(step_id, output), "allow_partial": False}}
    return answer


def _normalize(schema, planning, steps, final="answer", *, settings=RESULTS_ONLY, available=AVAILABLE):
    normalized = schema.normalize_plan(
        _raw_plan(steps, final),
        "conversation-1",
        OWNER,
        settings=deepcopy(settings),
        available_capability_ids=list(available),
        contract_version=2,
        workflow_planning=planning,
    )
    return schema.validate_plan(
        normalized,
        settings=deepcopy(settings),
        available_capability_ids=list(available),
        contract_version=2,
        workflow_planning=planning,
    )


def _rejection(schema, planning, steps, final="answer", *, settings=RESULTS_ONLY, available=AVAILABLE):
    with pytest.raises(schema.PlanValidationError) as caught:
        _normalize(schema, planning, steps, final, settings=settings, available=available)
    return caught.value


def _available(registry, settings, request_context):
    unavailable = {}
    ids = [
        capability["id"] for capability in registry.resolve_available_capabilities(
            settings,
            request_context=request_context,
            candidate_ids=[WORKFLOW_RESULTS],
            unavailable=unavailable,
        )
    ]
    return ids, unavailable


def _settings(**changes):
    settings = deepcopy(RESULTS_ONLY)
    settings.update(changes)
    return settings


def _workflow_projection_keys(projection):
    return [set(entry) for entry in projection["catalog"]["workflows"]]


def _assert_results_catalog_is_ready_and_no_richer_than_runs(wf, context):
    results_ready = wf.workflow_results_ready(context)
    results_projection = wf.workflow_results_projection(context)
    run_projection = wf.workflow_run_projection({**context, "workflow_runs": {"ready": True}})
    assert results_ready is True
    assert context["time_zone"] == LOCAL_ZONE
    assert "request_local_time" in context and "29 September 2026" in context["request_local_time"]
    assert results_projection is not None and run_projection is not None
    assert results_projection["time_zone"] == LOCAL_ZONE
    assert "request_local_time" in results_projection
    assert [entry["name"] for entry in results_projection["catalog"]["workflows"]]
    assert UUID_PATTERN.search(json.dumps(results_projection)) is None
    assert _workflow_projection_keys(results_projection) == _workflow_projection_keys(run_projection)
    for result_entry, run_entry in zip(
        results_projection["catalog"]["workflows"],
        run_projection["catalog"]["workflows"],
    ):
        assert set(result_entry).issubset(set(run_entry))
        assert "id" not in result_entry and "workflow_id" not in result_entry
    result_handles = {entry["handle"] for entry in results_projection["catalog"]["workflows"]}
    run_handles = {entry["handle"] for entry in run_projection["catalog"]["workflows"]}
    assert result_handles and result_handles.issubset(run_handles)


def _plan_request(monkeypatch, planning, replies, record, *, settings=RESULTS_ONLY, **options):
    context_module = importlib.import_module("functions_orchestration_context")
    planner = importlib.import_module("functions_orchestration_planner")
    services = importlib.import_module("functions_orchestration_services")
    request_context = context_module.build_capability_request_context(
        OWNER,
        deepcopy(IDENTITY),
        MESSAGE,
        [],
        [],
        allowed_user_urls=[],
        native_bridge_for_step=_binding,
        external_source_admission=_binding,
        external_source_authorizer=_binding,
        external_source_preflight=_binding,
        capture_external_source_configuration=_binding,
    )
    request_context["workflow_planning"] = planning
    planner_context = context_module.build_planner_context(
        MESSAGE,
        candidates=deepcopy(CANDIDATES),
        seeds={},
        ledger=None,
        signals=context_module.build_conversation_signals([], MESSAGE),
        agents=[],
        original_message=MESSAGE,
        request_resolution={"relationship": "new_topic", "resolved_message": MESSAGE},
        actions=[],
        answered_questions=[],
        memory_context=None,
    )
    planner_context["export_catalog"] = []
    client = type("Client", (), {})()
    client.chat = type("Chat", (), {"completions": _Completions(deepcopy(replies), record.calls)})()
    monkeypatch.setattr(planner, "resolve_planner_client", lambda _settings: (client, "deployment"))
    monkeypatch.setattr(
        planner,
        "log_event",
        lambda text, *args, **kwargs: record.logs.append((text, deepcopy(kwargs.get("extra")))),
    )
    return planner.plan_request(
        MESSAGE,
        planner_context,
        "conversation",
        OWNER,
        settings=deepcopy(settings),
        authorized_document_ids=[],
        revision=0,
        allow_elicitation=True,
        turn_id="turn",
        seeds={},
        document_labels={},
        request_context=request_context,
        planner_model=None,
        existing_results={},
        composition_profiles=services.composition_profiles(),
        export_catalog=[],
        edit_context=None,
        **options,
    )


def test_version_includes_the_workflow_results_capability():
    assert_app_version_at_least("0.261.217")


def test_the_registry_descriptor_is_read_only_dormant_and_ordered(registry, planning):
    ids = registry.all_capability_ids()
    capability = registry.get_capability(WORKFLOW_RESULTS, contract_version=2)
    dormant = deepcopy(RESULTS_ONLY)
    dormant[RESULTS] = False
    available, unavailable = _available(registry, dormant, {"user_roles": ["User"], "workflow_planning": planning})
    deployment = registry.resolve_available_capability_ids(dormant, candidate_ids=[WORKFLOW_RESULTS])
    assert registry.CAPABILITY_WORKFLOW_RESULTS == WORKFLOW_RESULTS
    assert ids.index("workflow_run") < ids.index(WORKFLOW_RESULTS) < ids.index("render_file")
    assert capability["role"] == "gather"
    assert capability.get("external_effects", False) is False
    assert "approval_floor" not in capability
    assert capability["max_per_plan"] == registry.WORKFLOW_RESULTS_MAX_PER_PLAN == 2
    assert capability["retry_on_transient"] is True
    assert capability["dormant_unless_setting"] == RESULTS
    assert capability["settings_gates"] == ("enable_chat_orchestration", "allow_user_workflows", RESULTS)
    assert available == [] and unavailable == {}
    assert deployment == []


@pytest.mark.parametrize(("changes", "roles", "reason"), [
    ({RESULTS: False}, ["User"], "workflow_results_disabled"),
    ({"allow_user_workflows": False}, ["User"], "workflow_results_disabled"),
    ({"chat_orchestration_enabled_capabilities": ["compose"]}, ["User"], "workflow_results_disabled"),
    ({"require_member_of_workflow_user": True}, ["User"], "workflow_role_required"),
])
def test_results_gates_are_role_aware_and_fail_closed(wf, planning, changes, roles, reason):
    settings = _settings(**changes)
    settings_reason = wf.workflow_results_settings_gate(settings)
    gate_reason = wf.workflow_results_gate(settings, roles)
    unavailable = wf.workflow_results_unavailable_reason(
        settings,
        {"user_roles": roles, "workflow_planning": planning},
    )
    expected_settings_reason = None if reason == "workflow_role_required" else reason
    assert settings_reason == expected_settings_reason
    assert gate_reason == reason
    assert unavailable == reason


def test_results_gate_accepts_workflow_user_when_the_role_is_required(wf, planning):
    settings = _settings(require_member_of_workflow_user=True)
    gate_reason = wf.workflow_results_gate(settings, ["User", "WorkflowUser"])
    unavailable = wf.workflow_results_unavailable_reason(
        settings,
        {"user_roles": ["User", "WorkflowUser"], "workflow_planning": planning},
    )
    assert gate_reason is None
    assert unavailable is None


@pytest.mark.parametrize("context", [None, {}, {"conversation_private": False}, {"conversation_private": True}])
def test_results_unavailable_reason_needs_a_ready_private_catalog(wf, context):
    reason = wf.workflow_results_unavailable_reason(
        RESULTS_ONLY,
        {"user_roles": ["User"], "workflow_planning": context},
    )
    assert reason in {"workflow_context_unavailable", "workflow_shared_conversation"}


@pytest.mark.parametrize(("name", "settings", "overrides"), [
    ("R", RESULTS_ONLY, {}),
    ("P+R", PROPOSALS_RESULTS, {}),
    ("Ru+R", RUNS_RESULTS, {}),
    ("P+Ru+R", ALL_WORKFLOW_SETTINGS, {}),
    ("R_at_proposal_quota", {**PROPOSALS_RESULTS, "chat_orchestration_max_workflows_per_user": 2}, {
        "quota_count": lambda user_id: 2,
    }),
    ("R_proposal_context_unavailable", PROPOSALS_RESULTS, {"quota_count": _fail}),
])
def test_results_catalog_is_reachable_with_or_without_proposals_or_runs(wf, name, settings, overrides):
    calls = []
    context = _build(wf, calls, settings, **overrides)
    assert name
    _assert_results_catalog_is_ready_and_no_richer_than_runs(wf, context)


def test_results_off_with_no_other_workflow_capability_reads_nothing(wf):
    calls = []
    context = _build(wf, calls, {**RESULTS_ONLY, RESULTS: False})
    projection = wf.workflow_results_projection(context)
    assert context == {"conversation_private": True, "quota_reached": None}
    assert calls == []
    assert projection is None


@pytest.mark.parametrize("arguments", [
    {"selector": "latest"},
    {"selector": "latest", "status": "completed"},
    {"selector": "completed_on", "completed_on": "2026-09-29"},
    {"selector": "completed_on", "completed_on": "2026-09-29", "status": "failed"},
])
def test_valid_results_arguments_and_plan_inputs_list_handles_and_names_only(schema, planning, arguments):
    digest = _handle(planning, "Weekly digest")
    result = _result(digest, arguments={"workflow": digest, **arguments})
    plan = _normalize(schema, planning, [_answer_from(), result])
    assert [step["capability_id"] for step in plan["steps"]] == [WORKFLOW_RESULTS, "compose"]
    assert plan["inputs"]["workflow_results"] == [{"handle": digest, "name": "Weekly digest"}]
    assert DIGEST_ID not in json.dumps(plan["inputs"]["workflow_results"])


@pytest.mark.parametrize(("arguments", "rule"), [
    ({"workflow": "workflow-not-offered", "selector": "latest"}, "workflow_results_unknown"),
    ({"workflow": "Weekly digest", "selector": "latest"}, "workflow_results_static_input"),
    ({"workflow": "workflow-digest", "selector": "soon"}, "workflow_results_static_input"),
    ({"workflow": "workflow-digest"}, "workflow_results_static_input"),
    ({"workflow": "workflow-digest", "selector": "completed_on"}, "workflow_results_static_input"),
    ({"workflow": "workflow-digest", "selector": "completed_on", "completed_on": "2025-1-6"}, "workflow_results_date"),
    (
        {"workflow": "workflow-digest", "selector": "completed_on", "completed_on": "2025-01-06T00:00:00Z"},
        "workflow_results_date",
    ),
    ({"workflow": "workflow-digest", "selector": "completed_on", "completed_on": "2999-01-01"}, "workflow_results_date"),
    ({"workflow": "workflow-digest", "selector": "completed_on", "completed_on": "2025-09-01"}, "workflow_results_date"),
])
def test_invalid_handles_selectors_and_dates_fail_closed(schema, planning, arguments, rule):
    digest = _handle(planning, "Weekly digest")
    arguments = {key: (digest if value == "workflow-digest" else value) for key, value in arguments.items()}
    error = _rejection(schema, planning, [ANSWER, _result(digest, arguments=arguments)])
    assert (error.code, error.rule) == (INVALID, rule)


@pytest.mark.parametrize("status", [
    "running",
    "in_progress",
    "completed_partial",
    "skipped",
    "invalid",
    "incomplete",
    "Completed",
    "",
    None,
    ["completed"],
])
def test_status_filter_is_a_closed_enum(schema, planning, status):
    digest = _handle(planning, "Weekly digest")
    error = _rejection(
        schema,
        planning,
        [ANSWER, _result(digest, arguments={"workflow": digest, "selector": "latest", "status": status})],
    )
    assert error.code == INVALID or "Step arguments do not match" in str(error)
    if status is not None:
        assert error.rule == "workflow_results_static_input"


@pytest.mark.parametrize("shape", ["depends_on", "bound_input", "bound_argument"])
def test_results_workflow_handle_must_be_static_and_not_bound(schema, planning, shape):
    digest = _handle(planning, "Weekly digest")
    search = {
        "step_id": "search",
        "capability_id": "web_search",
        "arguments": {"query": "which workflow"},
        "inputs": {},
    }
    if shape == "depends_on":
        result = _result(digest, depends_on=["search"])
    elif shape == "bound_input":
        result = _result(digest, inputs={"workflow": {"binding": input_binding("search", "results")}})
    else:
        result = _result(
            digest,
            arguments={"workflow": {"binding": input_binding("search", "results")}, "selector": "latest"},
        )
    error = _rejection(schema, planning, [search, ANSWER, result])
    assert (error.code, error.rule) == (INVALID, "workflow_results_static_input")


def test_duplicate_limit_and_same_plan_run_rules(schema, planning, wf):
    handles = [entry["handle"] for entry in planning["catalog"]["workflows"][:3]]
    all_planning = _build(wf, [], RUNS_RESULTS, request_text="Run my weekly digest and read it.")
    same_handle = _handle(all_planning, "Weekly digest")
    duplicate = _rejection(schema, planning, [
        ANSWER,
        _result(handles[0], step_id="read_one"),
        _result(handles[0], step_id="read_again"),
    ])
    limit = _rejection(schema, planning, [
        ANSWER,
        *[_result(handle, step_id=f"read_{index}") for index, handle in enumerate(handles)],
    ])
    same_plan_run = _rejection(schema, all_planning, [
        ANSWER,
        _run(same_handle),
        _result(same_handle),
    ], settings=RUNS_RESULTS)
    assert (duplicate.code, duplicate.rule) == (INVALID, "workflow_results_duplicate")
    assert (limit.code, limit.rule) == (INVALID, "workflow_results_limit")
    assert (same_plan_run.code, same_plan_run.rule) == (INVALID, "workflow_results_same_plan_run")


@pytest.mark.parametrize("wiring", ["render_binding", "transitive_render", "final_results_step"])
def test_only_compose_may_consume_workflow_results(schema, planning, wiring):
    digest = _handle(planning, "Weekly digest")
    result = _result(digest)
    if wiring == "render_binding":
        render = render_step("report", "md", source="read_digest", output="result")
        steps = [result, render]
        final = None
    elif wiring == "transitive_render":
        answer = _answer_from()
        render = render_step("report", "md", source="answer", output="answer")
        steps = [result, answer, render]
        final = "answer"
    else:
        steps = [result]
        final = input_binding("read_digest", "result")
    error = _rejection(schema, planning, steps, final)
    assert (error.code, error.rule) == (INVALID, "workflow_results_consumed")


def test_compose_may_consume_results_and_final_response_may_select_that_compose(schema, planning):
    digest = _handle(planning, "Weekly digest")
    plan = _normalize(schema, planning, [_answer_from(), _result(digest)])
    assert [step["step_id"] for step in plan["steps"]] == ["read_digest", "answer"]
    assert plan["final_response"]["step_id"] == "answer"


def test_planner_offers_results_only_when_ready_and_projects_time_zone(monkeypatch, planner, registry, planning):
    digest = _handle(planning, "Weekly digest")
    record = _record()
    kind, plan = _plan_request(monkeypatch, planning, [_raw_plan([_answer_from(), _result(digest)])], record)
    unavailable = {}
    not_ready_ids = [
        capability["id"] for capability in registry.resolve_available_capabilities(
            RESULTS_ONLY,
            request_context={"user_roles": ["User"], "workflow_planning": {"conversation_private": True}},
            candidate_ids=[WORKFLOW_RESULTS],
            unavailable=unavailable,
        )
    ]
    system = record.calls[0][0]["content"]
    payload = json.loads(record.calls[0][1]["content"])
    assert kind == "plan"
    assert [step["capability_id"] for step in plan["steps"]] == [WORKFLOW_RESULTS, "compose"]
    assert planner.WORKFLOW_RESULTS_INSTRUCTIONS in system
    assert planner.WORKFLOW_RUN_INSTRUCTIONS not in system
    assert planner.WORKFLOW_PROPOSAL_INSTRUCTIONS not in system
    assert payload["workflow_planning"]["time_zone"] == LOCAL_ZONE
    assert "request_local_time" in payload["workflow_planning"]
    assert not_ready_ids == []
    assert unavailable == {WORKFLOW_RESULTS: "workflow_context_unavailable"}


def test_planner_keeps_proposal_instructions_off_for_a_results_only_turn(monkeypatch, planner, planning):
    record = _record()
    _plan_request(monkeypatch, planning, [_raw_plan([ANSWER])], record)
    system = record.calls[0][0]["content"]
    assert planner.WORKFLOW_RESULTS_INSTRUCTIONS in system
    assert planner.WORKFLOW_PROPOSAL_INSTRUCTIONS not in system


def test_drop_workflow_results_removes_invalid_steps_and_writes_fixed_notes(results, planning):
    digest = _handle(planning, "Weekly digest")
    raw = _raw_plan([ANSWER, _result(digest), _result(digest, step_id="read_again")])
    plan, notes, remaining = results.drop_workflow_results(raw, workflow_planning=planning)
    all_dropped, all_notes, all_remaining = results.drop_workflow_results(
        raw,
        workflow_planning=planning,
        drop_all=True,
    )
    fixed = results.workflow_results_failure_message(notes + all_notes)
    assert [step["step_id"] for step in plan["steps"]] == ["answer", "read_digest"]
    assert notes == [{"reason": "workflow_results_duplicate", "name": "Weekly digest"}]
    assert remaining == 1
    assert [step["step_id"] for step in all_dropped["steps"]] == ["answer"]
    assert all_notes == [{"reason": "workflow_context_unavailable", "name": "Weekly digest"}]
    assert all_remaining == 0
    assert fixed.startswith(results.NO_WORKFLOW_RESULT_READ)
    assert digest not in fixed and DIGEST_ID not in fixed and "Weekly digest" not in fixed


def test_degraded_normalize_keeps_remaining_valid_results_with_plan_inputs(monkeypatch, planning):
    digest = _handle(planning, "Weekly digest")
    reply = _raw_plan([ANSWER, _result(digest), _result(digest, step_id="read_again")])
    record = _record()
    kind, plan = _plan_request(monkeypatch, planning, [reply, reply], record)
    assert kind == "plan"
    assert [step["step_id"] for step in plan["steps"]] == ["answer", "read_digest"]
    assert plan["workflow_results_notes"] == [{"reason": "workflow_results_duplicate", "name": "Weekly digest"}]
    assert plan["inputs"]["workflow_results"] == [{"handle": digest, "name": "Weekly digest"}]


def test_results_catalog_is_used_when_proposals_are_at_quota_or_unavailable(wf):
    at_quota = _build(
        wf,
        [],
        {**PROPOSALS_RESULTS, "chat_orchestration_max_workflows_per_user": 1},
        quota_count=lambda user_id: 1,
    )
    unavailable = _build(wf, [], PROPOSALS_RESULTS, quota_count=_fail)
    assert wf.workflow_results_projection(at_quota)["catalog"]["workflows"]
    assert wf.workflow_results_projection(unavailable)["catalog"]["workflows"]
    assert at_quota["quota_reached"] is True
    assert unavailable["context_unavailable"] is True


def test_admin_capability_option_sits_after_workflow_run_with_the_expected_help(admin_fields):
    field = admin_fields.get_field_definition("chat_orchestration_enabled_capabilities")
    options = field["options"]
    values = [option["value"] for option in options]
    assert values.index(WORKFLOW_RESULTS) == values.index("workflow_run") + 1
    assert options[values.index(WORKFLOW_RESULTS)] == {"value": WORKFLOW_RESULTS, "label": "Read workflow results"}
    assert "Read workflow results also requires Use Workflow Results In Chat and personal workflows." in field["help"]


@pytest.mark.parametrize(("settings", "expected"), [
    ({**RESULTS_ONLY, RESULTS: False, PROPOSALS: True}, True),
    (RESULTS_ONLY, True),
    ({**RESULTS_ONLY, RESULTS: False, RUNS: True}, False),
    ({**RESULTS_ONLY, RESULTS: False}, False),
    ({**ALL_WORKFLOW_SETTINGS, "enable_chat_orchestration": False}, False),
])
def test_time_zone_is_needed_for_proposals_or_results_but_not_runs_only(wf, settings, expected):
    configured = wf.workflow_time_zone_configured(settings)
    assert configured is expected


def test_empty_results_catalog_is_unavailable_and_not_offered(registry, wf):
    calls = []
    context = _build(wf, calls, RESULTS_ONLY, workflows=lambda user_id=None: [])
    request_context = {"user_roles": ["User"], "workflow_planning": context}
    reason = wf.workflow_results_unavailable_reason(RESULTS_ONLY, request_context)
    ids, unavailable = _available(registry, RESULTS_ONLY, request_context)
    projection = wf.workflow_results_projection(context)
    assert context["conversation_private"] is True
    assert context["workflow_results"] == {"ready": True}
    assert context["catalog"]["workflows"] == []
    assert context["handles"]["workflows"] == {}
    assert reason == "workflow_results_no_workflows"
    assert ids == []
    assert unavailable == {WORKFLOW_RESULTS: "workflow_results_no_workflows"}
    assert projection is None


def test_the_model_cannot_write_why_a_workflow_result_was_not_read(monkeypatch, planning):
    digest = _handle(planning, "Weekly digest")
    forged = [{"reason": "workflow_results_unknown_workflow", "name": "<b>Forged</b>"}]
    clean = dict(_raw_plan([_answer_from(), _result(digest)]), workflow_results_notes=forged)
    record = _record()
    kind, plan = _plan_request(monkeypatch, planning, [clean], record)
    assert kind == "plan"
    assert "workflow_results_notes" not in plan

    broken = dict(
        _raw_plan([_answer_from(), _result(digest), _result(digest, step_id="read_again")]),
        workflow_results_notes=forged,
    )
    record = _record()
    kind, plan = _plan_request(monkeypatch, planning, [broken, broken], record)
    text = json.dumps(plan)
    assert kind == "plan"
    assert plan["workflow_results_notes"] == [{"reason": "workflow_results_duplicate", "name": "Weekly digest"}]
    assert "Forged" not in text
    assert "<b>Forged</b>" not in text


def _results_truth(deliverables, settings, available, unavailable=None):
    capabilities = [{"id": capability_id} for capability_id in available]
    return deliverables.build_deliverable_availability(
        settings,
        capabilities=capabilities,
        unavailable=unavailable or {},
    )


@pytest.mark.parametrize(("reason", "text"), [
    (
        "not_enabled_for_orchestration",
        "Reading saved workflow results is not enabled for chat orchestration.",
    ),
    (
        "workflow_shared_conversation",
        "Saved workflow results can be read only in your own conversations, not in shared ones.",
    ),
    (
        "workflow_results_no_workflows",
        "You have no saved workflows whose results could be read.",
    ),
    (
        "workflow_role_required",
        "Your account does not have access to saved workflow results in chat.",
    ),
    (
        "workflow_context_unavailable",
        "Your saved workflows could not be loaded for this request. Try again later.",
    ),
    (
        "workflow_results_disabled",
        "Reading saved workflow results in chat is turned off for this deployment.",
    ),
    (
        "feature_disabled",
        "Reading saved workflow results in chat is turned off for this deployment.",
    ),
    (
        None,
        "Reading saved workflow results in chat is turned off for this deployment.",
    ),
])
def test_unavailable_results_are_explained_with_closed_text(deliverables, reason, text):
    unavailable = {WORKFLOW_RESULTS: reason} if reason is not None else {}
    base = _results_truth(deliverables, {**RESULTS_ONLY, RESULTS: False}, ["compose"], unavailable)
    truth = _results_truth(deliverables, RESULTS_ONLY, ["compose"], unavailable)
    added = [fact for fact in truth["facts"] if fact not in base["facts"]]
    assert added == [
        "Reading saved workflow results is unavailable for this request. "
        f"{text} "
        "When the user asks what a saved workflow found, say why in the answer."
    ]
    assert truth["recipes"] == base["recipes"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
