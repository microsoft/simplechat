# test_orchestration_single_contract.py
"""
Functional tests for Gather / Reason / Render as the only chat orchestration contract.
Version: 0.261.139
Implemented in: 0.261.139

This test ensures that new plans always use the single contract with no admin toggle, that
the toggle is gone from settings, admin fields and the admin template, that the legacy
planner prompt and the respond capability are gone, that the one planner prompt carries
the legacy planner guidance worth keeping, and that a saved run from the removed legacy
contract fails closed on every entry point with one stable message.

The HTTP checks run the production orchestration Blueprint through the shared offline
route fixture; only settings and storage I/O are replaced.
"""

import importlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from test_orchestration_harness_routes import OUTPUT_ID, RETRY_ID, login, modules, runtime  # noqa: F401
from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TOGGLE = "enable_chat_orchestration_harness"
MESSAGE = (
    "This plan was created by an earlier orchestration version and can't be opened or "
    "rerun. Start a new request."
)
# Saved plans from the removed contract carry the same identity fields as current plans,
# so ownership still passes and only the contract marker makes them unreadable.
LEGACY_IDENTITY = {
    "plan_id": "legacy-plan", "run_id": "legacy-run", "conversation_id": "conversation",
    "user_id": "owner", "turn_id": "legacy-turn", "kind": "plan",
    "intent": {"summary": "An earlier question"},
}
LEGACY_PLANS = {
    "missing_marker": {
        **LEGACY_IDENTITY,
        "steps": [{"step_id": "step_1", "capability_id": "respond"}],
    },
    "earlier_marker": {
        **LEGACY_IDENTITY,
        "planner_contract_version": 1,
        "steps": [{"step_id": "step_1", "capability_id": "respond", "phase": "reasoning"}],
    },
}


def _legacy_record(plan, *, run_id="legacy-run", status="completed"):
    saved_plan = deepcopy(plan)
    if isinstance(saved_plan, dict) and "run_id" in saved_plan:
        saved_plan["run_id"] = run_id
    return {
        "id": run_id, "run_id": run_id, "record_type": "orchestration_run",
        "conversation_id": "conversation", "user_id": "owner", "turn_id": "legacy-turn",
        "status": status, "plan": saved_plan, "user_message": "An earlier question",
        "checkpoint_version": 1, "execution_binding": "legacy-binding",
        "recovery_version": "legacy-version", "started_at": "2026-01-01T00:00:00+00:00",
    }


def _collapsed(text):
    return " ".join(text.split())


def _legacy_body(response):
    return response.status_code, response.get_json()


def test_version_includes_the_single_contract():
    assert_app_version_at_least("0.261.139")


# ------------------------------------------------------------------------------------------
# No admission module, toggle or legacy planner
# ------------------------------------------------------------------------------------------

def test_admission_module_and_toggle_are_gone():
    assert importlib.util.find_spec("functions_orchestration_admission") is None
    assert not (APP / "functions_orchestration_admission.py").exists()
    template = (APP / "templates" / "admin" / "_panes" / "chat-orchestration.html").read_text(encoding="utf-8")
    route = (APP / "route_backend_orchestration.py").read_text(encoding="utf-8")
    admin_route = (APP / "route_frontend_admin_settings.py").read_text(encoding="utf-8")
    fields = (APP / "admin_settings_fields.py").read_text(encoding="utf-8")
    checkpoints = (APP / "functions_orchestration_checkpoints.py").read_text(encoding="utf-8")
    for source in (template, route, admin_route, fields, checkpoints):
        assert TOGGLE not in source
    for text in ("harness", "preview", "Legacy"):
        assert text not in template
    assert "_new_plan_contract_version" not in route and "harness_admission" not in route
    for name in ("features.yml", "app_surface.yml"):
        assert TOGGLE not in (ROOT / "docs" / "_data" / name).read_text(encoding="utf-8")


def test_settings_defaults_no_longer_offer_the_toggle(modules):
    settings = importlib.import_module("functions_settings")
    source = (APP / "functions_settings.py").read_text(encoding="utf-8")
    defaults = source.split("def get_settings(", 1)[1].split("def normalize_loaded_settings", 1)[0]
    sanitize = source.split("def sanitize_settings_for_user(", 1)[1].split("\ndef ", 1)[0]
    assert TOGGLE not in defaults
    assert TOGGLE not in sanitize
    assert settings.RETIRED_SETTING_KEYS == (TOGGLE,)
    # Loading and saving both retire the stored switch.
    assert source.count("normalize_retired_orchestration_settings(") == 3


def test_a_stored_toggle_is_dropped_and_a_saved_allowlist_is_left_as_stored(modules):
    settings = importlib.import_module("functions_settings")
    stored = {
        TOGGLE: True, "enable_chat_orchestration": True,
        "chat_orchestration_enabled_capabilities": ["document_search", "respond", "compose"],
    }
    changed = settings.normalize_retired_orchestration_settings(stored)
    assert changed is True
    assert TOGGLE not in stored
    # Saved runs are bound to the settings they ran under, so the list is never rewritten;
    # the registry reads a stored `respond` as `compose` instead.
    assert stored["chat_orchestration_enabled_capabilities"] == ["document_search", "respond", "compose"]
    changed_again = settings.normalize_retired_orchestration_settings(stored)
    assert changed_again is False
    assert not hasattr(settings, "RETIRED_ORCHESTRATION_CAPABILITIES")
    untouched = {"chat_orchestration_enabled_capabilities": []}
    untouched_changed = settings.normalize_retired_orchestration_settings(untouched)
    assert untouched_changed is False
    assert untouched == {"chat_orchestration_enabled_capabilities": []}


def _v2_admin_settings_helper(registry):
    """The real V2 admin settings preparation helper, with its redaction inputs isolated."""
    import ast

    tree = ast.parse((APP / "route_backend_v2.py").read_text(encoding="utf-8"))
    helper = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_redact_admin_settings_for_v2"
    )
    namespace = {
        "redact_admin_settings_secrets_for_api": deepcopy,
        "get_secret_storage_paths": list,
        "read_nested_setting": lambda settings, path: None,
        "write_nested_setting": lambda settings, path, value: None,
        "SECRET_REDACTED_VALUE": "REDACTED",
        "sanitize_model_endpoints_for_frontend": lambda endpoints: endpoints,
        "effective_capability_ids": registry.effective_capability_ids,
    }
    exec(compile(ast.Module(body=[helper], type_ignores=[]), "route_backend_v2.py", "exec"), namespace)
    return namespace["_redact_admin_settings_for_v2"]


def test_both_admin_pages_show_a_saved_answering_step_as_prepare_content(modules):
    registry = importlib.import_module("functions_orchestration_registry")
    prepare = _v2_admin_settings_helper(registry)
    stored = {"chat_orchestration_enabled_capabilities": ["web_search", "respond"], "enable_chat_orchestration": True}
    shown = prepare(stored)
    assert shown["chat_orchestration_enabled_capabilities"] == ["web_search", "compose"]
    assert stored["chat_orchestration_enabled_capabilities"] == ["web_search", "respond"]
    # The PATCH echo carries only submitted keys, so a missing list is never added.
    echo = prepare({"enable_chat_orchestration": False})
    assert echo == {"enable_chat_orchestration": False}
    admin_route = (APP / "route_frontend_admin_settings.py").read_text(encoding="utf-8")
    assert "effective_capability_ids(settings.get('chat_orchestration_enabled_capabilities'))" in admin_route


def test_admin_fields_offer_no_toggle_and_no_answering_step(modules):
    fields = importlib.import_module("admin_settings_fields")
    definition = fields.get_field_definition("chat_orchestration_enabled_capabilities")
    options = [option["value"] for option in definition["options"]]
    assert TOGGLE not in fields.get_declared_setting_keys()
    assert fields.get_field_definition(TOGGLE) is None
    assert "respond" not in options and {"compose", "render_file", "generate_image"} <= set(options)
    assert "harness" not in definition["help"].lower() and "legacy" not in definition["help"].lower()


def test_registry_has_one_contract_with_no_phases_or_answering_step(modules):
    registry = importlib.import_module("functions_orchestration_registry")
    capabilities = registry.capabilities_for_contract()
    identifiers = [capability["id"] for capability in capabilities]
    assert "respond" not in identifiers
    assert identifiers == registry.all_capability_ids()
    assert all(capability["role"] in ("gather", "reason", "render") for capability in capabilities)
    assert all("phase" not in capability and "terminal" not in capability for capability in capabilities)
    assert all(capability["plan_contract_version"] == 2 for capability in capabilities)
    assert all("documents_from_step" not in json.dumps(capability["inputs"]) for capability in capabilities)
    for removed in (
        "PHASE_KNOWLEDGE", "CAPABILITY_PHASES", "CAPABILITY_RESPOND", "TERMINAL_CAPABILITY_ID",
        "phase_index", "CAPABILITY_BY_ID", "CAPABILITY_REGISTRY_CONTRACT_VERSION",
    ):
        assert not hasattr(registry, removed), removed
    assert registry.get_capability("respond") is None
    with pytest.raises(ValueError):
        registry.get_capability("compose", contract_version=1)
    with pytest.raises(ValueError):
        registry.resolve_available_capabilities({}, contract_version=1)
    assert registry.describe_registry() == {
        "contract_version": 2, "capability_ids": identifiers, "roles": ["gather", "reason", "render"],
    }


def test_catalog_discovery_checks_gates_without_runtime_services(modules):
    """Agent and action discovery ask whether settings allow them, not whether services are bound."""
    registry = importlib.import_module("functions_orchestration_registry")
    settings = {
        "enable_chat_orchestration": True, "enable_semantic_kernel": True,
        "enable_chat_orchestration_actions": True, "enable_web_search": True,
    }
    bound = registry.resolve_available_capability_ids(
        settings, candidate_ids=("agent_invoke", "action_invoke", "web_search"),
    )
    discovered = registry.resolve_available_capability_ids(
        settings, candidate_ids=("agent_invoke", "action_invoke", "web_search"),
        include_runtime_bindings=False,
    )
    # Without request-time services, planning and execution may not offer external work...
    assert bound == []
    # ...but discovery still sees what the deployment permits.
    assert discovered == ["web_search", "action_invoke", "agent_invoke"]
    disabled = registry.resolve_available_capability_ids(
        {**settings, "enable_semantic_kernel": False}, candidate_ids=("agent_invoke",),
        include_runtime_bindings=False,
    )
    assert disabled == []


def test_adapters_and_executor_have_no_answering_step(modules):
    adapters = importlib.import_module("functions_orchestration_adapters")
    executor = importlib.import_module("functions_orchestration_executor")
    routing = importlib.import_module("functions_orchestration_model_routing")
    visuals = importlib.import_module("functions_orchestration_visuals")
    for name in ("run_respond", "RESPONSE_CONTEXT_POLICY", "_build_respond_prompt", "synthesize_source_manifest_from_evidence"):
        assert not hasattr(adapters, name), name
    assert "respond" not in adapters.ADAPTER_REGISTRY
    assert adapters.get_adapter("respond") is None
    assert adapters.get_adapter("compose") is not None
    assert adapters.get_adapter("compose", contract_version=1) is None
    for name in ("_run_single_step", "_topological_order", "_find_terminal_step_id", "_reauthorize_before_finalization"):
        assert not hasattr(executor, name), name
    assert "respond" not in routing.STEP_TASKS
    assert not hasattr(visuals, "requested_visual_outputs")
    with pytest.raises(Exception):
        executor.RunContext(plan_contract_version=1)


def test_the_one_planner_prompt_has_no_legacy_phase_language(modules):
    planner = importlib.import_module("functions_orchestration_planner")
    prompt = planner.PLANNER_SYSTEM_PROMPT
    assert not hasattr(planner, "DEPENDENCY_PLANNER_SYSTEM_PROMPT")
    for name in ("triage_request", "build_trivial_plan"):
        assert not hasattr(planner, name), name
    for phrase in ('"respond"', "phases run in a fixed order", "documents_from_step", "contract 2", "harness"):
        assert phrase not in prompt
    assert "respond step" not in planner.PLAN_EDIT_INSTRUCTIONS
    messages = planner.build_planner_messages({"message": "hi"})
    assert messages[0]["content"] == prompt
    edit = planner.build_planner_messages({"message": "hi"}, edit_context={"instruction": "x"})
    assert planner.PLAN_EDIT_INSTRUCTIONS.strip() in edit[0]["content"]
    with pytest.raises(Exception):
        planner.build_planner_messages({}, contract_version=1)


@pytest.mark.parametrize("guidance", [
    # Capability authority and neutral controls.
    "never claim that a listed capability is disabled or unauthorized",
    "An unchecked or absent control is neutral, NOT a prohibition",
    "A selection cannot enable an unavailable capability",
    # Agents and actions.
    "set\nagent_name to a name from that list, spelled exactly",
    "if the list is empty there is no agent to call",
    "Prefer a directly relevant\naction to loading an agent solely for that integration",
    "A user-selected agent is a constraint, not a suggestion",
    # Documents and depth.
    "Only name a document ID that appears in candidate_documents or that the user selected",
    "Searching documents is much cheaper\nthan analysing them",
    "bind document_analyze's \"sources\" input\nto that search's \"sources\" output",
    # Research depth selection.
    "web_search suits focused lookups and limited discovery",
    "Consider deep_research when deliberate\ndiscovery across different perspectives",
    "do not add a web_search step just to\nseed it",
    "capability_availability.web_discovery_enabled",
    "In each gathering step's rationale, briefly explain why that depth fits",
    # Conversation, memory, and ledger.
    '"original_message" as the user\'s unchanged words',
    '"request_time_utc"',
    "the ledger records activity, not source\nevidence",
    "Earlier assistant claims do not establish current facts or opening hours",
    # Self-contained work and brevity.
    'fragments such as "open on\nWednesdays"',
    "a one-step compose plan is a good\nplan when the question is simple",
    # Visual planning.
    "Plan the gathering each\nvisual needs",
    "Never assume an\nintegration itself produces a plot or an image",
    # Clarifications and file answers.
    'set ui_hints.fields[field].input to "files"',
    "NEVER put an enum on a file field",
    "Tags and\nworkspaces can supplement a file answer",
    "Do not repeat a\nquestion that clarifications or earlier runs already answered or declined",
    "Only ask when you\ntruly cannot proceed",
])
def test_the_one_planner_prompt_keeps_the_legacy_planner_guidance(modules, guidance):
    planner = importlib.import_module("functions_orchestration_planner")
    assert _collapsed(guidance) in _collapsed(planner.PLANNER_SYSTEM_PROMPT)


def test_new_plans_always_use_the_single_contract(modules):
    schema = importlib.import_module("functions_orchestration_schema")
    planner = importlib.import_module("functions_orchestration_planner")
    route = importlib.import_module("route_backend_orchestration")
    import inspect

    assert inspect.signature(schema.normalize_plan).parameters["contract_version"].default == 2
    assert inspect.signature(planner.plan_request).parameters["contract_version"].default == 2
    source = inspect.getsource(route)
    assert "'planner_contract_version': DEPENDENCY_PLAN_CONTRACT_VERSION," in source
    assert "turn_context.get('planner_contract_version', 1)" not in source
    plan = schema.normalize_plan(
        {
            "kind": "plan", "intent": {"summary": "Say hello"},
            "steps": [{
                "step_id": "answer", "capability_id": "compose",
                "arguments": {"instruction": "Say hello.", "knowledge_basis": "general_knowledge"},
                "inputs": {}, "outputs": [{"name": "answer", "kind": "markdown-v1"}],
            }],
            "final_response": {
                "version": "orchestration-input-binding-v1", "step_id": "answer",
                "output_name": "answer", "existing_result": None,
            },
        },
        "conversation", "owner", settings={"enable_chat_orchestration": True},
        available_capability_ids=["compose"],
    )
    assert plan["planner_contract_version"] == 2
    assert plan["steps"][0]["role"] == "reason"
    assert "phase" not in plan["steps"][0]
    with pytest.raises(schema.LegacyPlanError):
        schema.normalize_plan({}, "conversation", "owner", contract_version=1)


# ------------------------------------------------------------------------------------------
# Legacy records fail closed
# ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("plan", [*LEGACY_PLANS.values(), None])
def test_legacy_plans_are_detected_and_never_read_as_the_current_contract(modules, plan):
    schema = importlib.import_module("functions_orchestration_schema")
    assert schema.LEGACY_PLAN_MESSAGE == MESSAGE and schema.LEGACY_PLAN_CODE == "legacy_plan"
    assert schema.is_legacy_plan(plan) is True
    with pytest.raises(schema.LegacyPlanError) as refused:
        schema.plan_contract_version(plan)
    assert refused.value.code == "legacy_plan" and str(refused.value) == MESSAGE
    assert schema.build_failure("legacy_plan")["message"] == MESSAGE
    with pytest.raises(schema.LegacyPlanError):
        schema.validate_plan(deepcopy(plan) if plan else plan)
    with pytest.raises(schema.LegacyPlanError):
        schema.apply_plan_edits(deepcopy(plan) if plan else plan, {"disabled_step_ids": []})


@pytest.mark.parametrize("version", [3, "2", True, 2.0])
def test_unknown_markers_are_refused_without_being_called_legacy(modules, version):
    schema = importlib.import_module("functions_orchestration_schema")
    plan = {"planner_contract_version": version, "steps": []}
    assert schema.is_legacy_plan(plan) is False
    with pytest.raises(schema.PlanValidationError) as refused:
        schema.plan_contract_version(plan)
    assert not isinstance(refused.value, schema.LegacyPlanError)
    assert refused.value.code == "plan_version_unsupported"


@pytest.mark.parametrize("plan", list(LEGACY_PLANS.values()))
def test_legacy_runs_fail_closed_in_the_executor_runtime_and_checkpoints(modules, plan):
    executor = importlib.import_module("functions_orchestration_executor")
    execution = importlib.import_module("functions_orchestration_execution")
    checkpoints = importlib.import_module("functions_orchestration_checkpoints")
    recovery = importlib.import_module("functions_orchestration_recovery")
    context = executor.RunContext(run_id="legacy-run", user_id="owner", conversation_id="conversation")
    with pytest.raises(importlib.import_module("functions_orchestration_schema").LegacyPlanError):
        executor.execute_plan(deepcopy(plan), context, settings={}, user_id="owner")
    with pytest.raises(execution.HarnessExecutionError) as refused:
        execution._claimed_harness_execution(_legacy_record(plan), lease=None)
    assert refused.value.code == "legacy_plan" and refused.value.message == MESSAGE
    with pytest.raises(checkpoints.CheckpointError):
        checkpoints.CheckpointStore(
            None, run_id="r", user_id="owner", conversation_id="c", turn_id="t",
            authorize=lambda: True, plan_contract_version=1,
        )
    legacy_state = {key: [] for key in checkpoints.STATE_FIELDS}
    with pytest.raises(checkpoints.CheckpointError) as invalid:
        checkpoints.restore_context(context, {"state": legacy_state})
    assert invalid.value.code == "checkpoint_invalid"
    projection = recovery.recovery_projection(_legacy_record(plan))
    assert projection["eligible"] is False
    assert projection["reason_code"] == "legacy_plan" and projection["message"] == MESSAGE


@pytest.mark.parametrize("plan", list(LEGACY_PLANS.values()))
def test_legacy_runs_fail_closed_in_revisions_recovery_and_continuation(runtime, plan):
    revisions = importlib.import_module("functions_orchestration_plan_revisions")
    recovery = importlib.import_module("functions_orchestration_recovery")
    continuation = importlib.import_module("functions_orchestration_continuation")
    checkpoints = importlib.import_module("functions_orchestration_checkpoints")
    runtime.runs.create_item(_legacy_record(plan))
    with pytest.raises(revisions.PlanRevisionError) as refused:
        revisions.read_revision_run("legacy-run", "owner", "conversation")
    assert (refused.value.code, refused.value.status_code, refused.value.message) == ("legacy_plan", 409, MESSAGE)
    with pytest.raises(revisions.PlanRevisionError):
        revisions.read_revision_run("legacy-run", "owner", "conversation", follow_current=True)
    # Only conversation deletion reads a legacy run, so it can remove the run's saved data.
    assert revisions.read_revision_run("legacy-run", "owner", "conversation", allow_legacy=True)["id"] == "legacy-run"
    with pytest.raises(recovery.RecoveryError) as retry:
        recovery.prepare_retry(
            "legacy-run", "owner",
            {"conversation_id": "conversation", "submission_id": RETRY_ID, "expected_version": "legacy-version"},
            authorize=lambda: True, validate=Mock(side_effect=AssertionError("never validated")),
        )
    assert (retry.value.code, retry.value.status_code, retry.value.message) == ("legacy_plan", 409, MESSAGE)
    with pytest.raises(checkpoints.CheckpointError) as continued:
        continuation._read_owned("legacy-run", "owner", "conversation", lambda: True)
    assert continued.value.code == "legacy_plan" and continued.value.failure["message"] == MESSAGE
    with pytest.raises(checkpoints.CheckpointError) as saved:
        continuation._saved_v2(_legacy_record(plan))
    assert saved.value.code == "legacy_plan"


def test_legacy_runs_are_omitted_from_listings_the_planner_reads(runtime):
    runs = importlib.import_module("functions_orchestration_runs")
    runtime.runs.create_item(_legacy_record(LEGACY_PLANS["missing_marker"], run_id="legacy-a"))
    runtime.runs.create_item(_legacy_record(LEGACY_PLANS["earlier_marker"], run_id="legacy-b"))
    current = _legacy_record({"planner_contract_version": 2, "steps": []}, run_id="current")
    runtime.runs.create_item(current)
    listed = runs.list_conversation_runs("conversation", "owner", limit=10)
    assert [run["id"] for run in listed] == ["current"]


def test_legacy_turns_are_recognized_before_any_replanning(modules):
    route = importlib.import_module("route_backend_orchestration")
    assert route._legacy_turn({"user_message": "old"}) is True
    assert route._legacy_turn({"planner_contract_version": 1}) is True
    assert route._legacy_turn(None) is True
    current = {"planner_contract_version": 2}
    assert route._legacy_turn(current) is False
    assert route._legacy_turn(current, {"kind": "elicitation", "document": {}}) is False
    assert route._legacy_turn(current, {"kind": "plan", "document": {"steps": []}}) is True
    assert route._legacy_turn(current, {"kind": "plan", "document": {"planner_contract_version": 2}}) is False


@pytest.mark.parametrize("plan_name", list(LEGACY_PLANS))
def test_every_by_id_route_refuses_a_legacy_run_with_one_message(runtime, monkeypatch, plan_name):
    login(runtime)
    runtime.runs.create_item(_legacy_record(LEGACY_PLANS[plan_name]))
    services = Mock(side_effect=AssertionError("A legacy run must not bind execution services."))
    monkeypatch.setattr(runtime.modules.route, "_orchestration_services", services)
    client = runtime.client
    query = {"conversation_id": "conversation"}
    responses = {
        "detail": client.get("/api/v2/orchestration/runs/legacy-run", query_string=query),
        "steps": client.get("/api/v2/orchestration/runs/legacy-run/steps", query_string=query),
        "editor": client.get("/api/v2/orchestration/runs/legacy-run/editor", query_string=query),
        "edit": client.post("/api/v2/orchestration/runs/legacy-run/edit", json=query),
        "revisions": client.post("/api/v2/orchestration/runs/legacy-run/revisions", json={
            **query, "expected_version": "legacy-version", "submission_id": RETRY_ID,
            "action": "ask", "instruction": "Change it",
        }),
        "retry": client.post("/api/v2/orchestration/runs/legacy-run/retry", json={
            **query, "submission_id": RETRY_ID, "expected_version": "legacy-version",
        }),
        "file_retry": client.post(
            f"/api/v2/orchestration/runs/legacy-run/outputs/{OUTPUT_ID}/retry",
            json={**query, "submission_id": RETRY_ID},
        ),
        "run": client.post("/api/v2/orchestration/run", json={**query, "run_id": "legacy-run"}),
        "cancel": client.post("/api/v2/orchestration/cancel/legacy-run", json=query),
        "export_catalog": client.get(
            "/api/v2/orchestration/export-catalog", query_string={**query, "run_id": "legacy-run"},
        ),
    }
    for name, response in responses.items():
        status, body = _legacy_body(response)
        assert status == 409, (name, status, body)
        assert body == {"error": MESSAGE, "code": "legacy_plan"}, (name, body)
    listed = runtime.client.get("/api/v2/orchestration/runs", query_string={"conversation_id": "conversation"})
    assert listed.status_code == 200 and listed.get_json()["runs"] == []
    saved = runtime.runs.read_item("legacy-run", "conversation")
    assert saved["plan"] == _legacy_record(LEGACY_PLANS[plan_name])["plan"]
    assert not saved.get("cancellation_requested_at") and not saved.get("edit_claim")
    assert not runtime.messages.items and not runtime.results.items
    services.assert_not_called()
