# test_workflow_assist_chat_results.py
"""
Functional tests for capability/results authoring and group Ask AI.
Version: 0.261.364
Implemented in: 0.261.343
Chat-execution contract fix: 0.261.364

Validate closed operations, inherited task execution, actual save projections,
canonical audiences, scope isolation, stale revisions and group route policy.
All model replies and external services are scripted; no workflow is saved.
"""

import ast
import copy
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

from flask import Flask, session
import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "functional_tests"))

import functions_workflow_assist as core  # noqa: E402
from functions_workflow_assist_operations import (  # noqa: E402
    AssistApplyContext, AssistApplyError, AssistHandles, apply_assist_operations, validate_assist_output,
)
from functions_workflow_configuration import (  # noqa: E402
    WorkflowConfigurationError, normalize_chat_execution, normalize_results_delivery,
)
from test_support import workflow_assist as wa  # noqa: E402


GROUP = "group-scope-343"
ALICE = "a1000000-0000-4000-8000-000000000001"
BOB = "b2000000-0000-4000-8000-000000000002"


def execution(mode="selected", capabilities=None, visuals=None):
    return {"version": 1, "mode": mode, "required_capabilities": capabilities or [],
            "visual_requirements": visuals or []}


def options(group=False):
    choices = copy.deepcopy(wa.OPTIONS)
    choices["chat_execution"] = {
        "modes": [{"id": mode, "available": True, "label": mode} for mode in ("orchestration", "selected", "off")],
        "capabilities": [{"id": name, "label": name, "available": name != "deep_research"}
                         for name in ("web_search", "url_fetch", "deep_research", "generate_image", "render_file")],
        "visual_requirements": [{"id": name, "label": name, "available": True}
                                for name in ("chart", "diagram", "image_proposal")],
    }
    choices["results_delivery"] = {
        "modes": [{"id": name, "label": name} for name in ("history", "conversation", "task")],
        "conversation_types": [{"id": name, "label": name}
                               for name in (("group", "group_shared") if group else ("personal", "shared"))],
        "recipient_choices": [{"id": ALICE, "label": "Alice (alice@example.org)"},
                              {"id": BOB, "label": "Bob (bob@example.org)"}],
        "allow_all_group_members": group,
    }
    if group:
        choices["document_workspaces"] = [{"scope_type": "group", "scope_id": GROUP, "name": "This group"}]
    return choices


def apply(operations, *, draft=None, group=False, audience="Share with Alice"):
    draft = copy.deepcopy(draft or wa.new_draft())
    if group:
        draft["group_id"] = GROUP
    output = json.loads(wa.reply(operations=operations))
    errors = validate_assist_output(output)
    assert not errors, errors
    handles = AssistHandles(draft, user_id=wa.USER_ID, options=options(group))
    candidate, _info = apply_assist_operations(
        draft, output, handles, AssistApplyContext(audience_instruction=audience),
    )
    return candidate


def test_chat_and_results_are_actual_save_fields_not_prompt_only():
    operations = [
        {"op": "set_workflow_chat_execution", **{k: v for k, v in execution("orchestration").items() if k != "version"}},
        {"op": "set_task_chat_execution", "task": "task_1", "mode": "selected",
         "required_capabilities": ["web_search", "render_file"], "visual_requirements": ["chart"]},
        {"op": "set_results_delivery", "mode": "conversation", "conversation_type": "shared"},
        {"op": "set_results_recipients", "recipients": ["recipient_1"]},
    ]
    model = wa.ScriptedModel(wa.reply(operations=operations))
    bundle = wa.services(model, options=options())
    draft = wa.new_draft()
    before = copy.deepcopy(draft)
    result = wa.run(wa.request_body(draft, instruction="Use web search and share results with Alice."), bundle)
    candidate = result["candidate"]
    assert result["outcome"] == "changed"
    assert candidate["chat_execution"] == execution("orchestration")
    assert candidate["tasks"][0]["chat_execution"]["required_capabilities"] == ["web_search", "render_file"]
    assert candidate["results_delivery"]["recipient_ids"] == [ALICE]
    payload = bundle.recorder.named("dry_run")[0][1]
    assert payload["chat_execution"] == candidate["chat_execution"]
    assert payload["tasks"][0]["chat_execution"] == candidate["tasks"][0]["chat_execution"]
    assert payload["results_delivery"] == candidate["results_delivery"]
    assert before == draft
    envelope = model.envelope()
    assert ALICE not in json.dumps(envelope)
    assert envelope["choices"]["results_delivery"]["recipients"][0]["recipient"] == "recipient_1"


def test_task_override_replaces_then_returns_to_inheritance():
    draft = wa.new_draft(chat_execution=execution("selected", ["web_search"]))
    draft["tasks"][0]["chat_execution"] = execution("selected", ["url_fetch"])
    changed = apply([{"op": "set_task_chat_execution", "task": "task_1", "mode": "selected",
                      "required_capabilities": ["render_file"], "visual_requirements": []}], draft=draft)
    assert changed["tasks"][0]["chat_execution"]["required_capabilities"] == ["render_file"]
    inherited = apply([{"op": "inherit_task_chat_execution", "task": "task_1"}], draft=changed)
    assert "chat_execution" not in inherited["tasks"][0]
    assert inherited["chat_execution"] == draft["chat_execution"]


@pytest.mark.parametrize("scope", ["workflow", "task"])
@pytest.mark.parametrize("mode", ["orchestration", "selected", "off"])
@pytest.mark.parametrize("capabilities,visuals", [
    ([], []), (["web_search"], []), ([], ["diagram"]), (["web_search"], ["diagram"]),
])
def test_chat_operation_schemas_match_runtime_mode_constraints(scope, mode, capabilities, visuals):
    value = execution(mode, capabilities, visuals)
    operation = {"op": f"set_{scope}_chat_execution", **{key: item for key, item in value.items() if key != "version"}}
    if scope == "task":
        operation["task"] = "task_1"
    try:
        normalize_chat_execution(value)
    except WorkflowConfigurationError:
        runtime_valid = False
    else:
        runtime_valid = True
    errors = validate_assist_output(json.loads(wa.reply(operations=[operation])))
    assert bool(errors) is not runtime_valid
    if errors:
        guidance = "at least one" if mode == "selected" else "empty"
        assert any(guidance in message for message in errors), errors


@pytest.mark.parametrize("scope", ["workflow", "task"])
@pytest.mark.parametrize("mode,capabilities,visuals", [
    ("selected", [], []), ("orchestration", ["web_search"], []), ("off", [], ["diagram"]),
])
def test_runtime_still_rejects_invalid_chat_combinations_with_specific_safe_feedback(scope, mode, capabilities, visuals):
    draft = wa.new_draft()
    before = copy.deepcopy(draft)
    operation = {"op": f"set_{scope}_chat_execution", "mode": mode,
                 "required_capabilities": capabilities, "visual_requirements": visuals}
    if scope == "task":
        operation["task"] = "task_1"
    handles = AssistHandles(draft, user_id=wa.USER_ID, options=options())
    with pytest.raises(AssistApplyError) as caught:
        apply_assist_operations(draft, {"operations": [operation]}, handles, AssistApplyContext())
    assert caught.value.diagnostics == [{
        "assist_rule": "chat_execution_invalid", "operation_index": 1, "assist_operation": operation["op"],
    }]
    guidance = "at least one" if mode == "selected" else "Only selected mode"
    assert guidance in caught.value.messages[0]
    assert draft == before


@pytest.mark.parametrize("scope", ["workflow", "task"])
@pytest.mark.parametrize("kind,mode,capabilities,visuals,rule", [
    ("modes", "orchestration", [], [], "chat_mode_unavailable"),
    ("capabilities", "selected", ["web_search"], [], "chat_capability_unavailable"),
    ("visual_requirements", "selected", [], ["diagram"], "chat_output_unavailable"),
])
def test_unavailable_chat_choices_remain_rejected_with_distinct_rules(scope, kind, mode, capabilities, visuals, rule):
    choices = options()
    for choice in choices["chat_execution"][kind]:
        choice["available"] = False
    draft = wa.new_draft()
    before = copy.deepcopy(draft)
    operation = {"op": f"set_{scope}_chat_execution", "mode": mode,
                 "required_capabilities": capabilities, "visual_requirements": visuals}
    if scope == "task":
        operation["task"] = "task_1"
    handles = AssistHandles(draft, user_id=wa.USER_ID, options=choices)
    with pytest.raises(AssistApplyError) as caught:
        apply_assist_operations(draft, {"operations": [operation]}, handles, AssistApplyContext())
    assert caught.value.diagnostics == [{
        "assist_rule": rule, "operation_index": 1, "assist_operation": operation["op"],
    }]
    assert "unavailable" in caught.value.messages[0]
    assert draft == before


@pytest.mark.parametrize("scope", ["workflow", "task"])
@pytest.mark.parametrize("mode", ["selected", "orchestration", "off"])
@pytest.mark.parametrize("corrected", [False, True], ids=["persistent rejection", "successful correction"])
def test_blank_wednesday_email_draft_corrects_atomically_without_inventing_run_time(scope, mode, corrected):
    draft = wa.new_draft(name="", description="")
    draft["tasks"] = [draft["tasks"][0]]
    draft["tasks"][0].update(name="Task 1", instructions="")
    invalid = {"op": f"set_{scope}_chat_execution", "mode": mode,
               "required_capabilities": [] if mode == "selected" else ["agent_invoke"],
               "visual_requirements": []}
    if scope == "task":
        invalid["task"] = "task_1"
    valid = {**invalid, "required_capabilities": ["agent_invoke"] if mode == "selected" else []}
    operations = [
        {"op": "set_name", "name": "Wednesday email review"},
        {"op": "set_description", "description": "Review emails received on Monday and Tuesday each Wednesday."},
        {"op": "set_task_name", "task": "task_1", "name": "Review Monday and Tuesday emails"},
        {"op": "set_task_instructions", "task": "task_1",
         "instructions": "Use an authorized Microsoft 365 agent to summarize emails received on Monday and Tuesday. "
                         "Report missing access instead of claiming to have read emails."},
        invalid,
        {"op": "set_schedule_calendar", "frequency": "weekly", "days_of_week": ["wednesday"], "time_of_day": ""},
    ]
    clarification = {"question": "What time on Wednesday should this run?", "fields": ["schedule_time"]}
    first = wa.reply(operations=operations, clarification=clarification)
    second = wa.reply(operations=[*operations[:4], valid, operations[-1]], clarification=clarification) if corrected else first
    model = wa.ScriptedModel(first, second)
    choices = options()
    choices["chat_execution"]["capabilities"].append({"id": "agent_invoke", "available": True})
    bundle = wa.services(model, options=choices)
    body = wa.request_body(draft, instruction="Review my Monday and Tuesday emails every Wednesday.")
    before = copy.deepcopy(body)
    if corrected:
        result = wa.run(body, bundle)
        assert result["outcome"] == "changed"
        candidate = result["candidate"]
        assert candidate["name"] == "Wednesday email review"
        assert len(candidate["tasks"]) == 1
        assert candidate["tasks"][0]["instructions"] == operations[3]["instructions"]
        assert candidate["schedule"] == {
            "kind": "calendar", "frequency": "weekly", "days_of_week": ["wednesday"], "day_of_month": None,
            "time_of_day": "", "timezone": wa.TIME_ZONE,
        }
        assert result["clarification"] == clarification
        owner = candidate if scope == "workflow" else candidate["tasks"][0]
        assert owner["chat_execution"] == execution(mode, valid["required_capabilities"])
        assert candidate.get("m365_run_as_user_id") == draft.get("m365_run_as_user_id")
        assert candidate.get("results_delivery") == draft.get("results_delivery")
    else:
        failure = wa.refusal(body, bundle)
        assert (failure.status, failure.code) == (502, "assistant_output_invalid")
        assert not bundle.recorder.named("dry_run")
    assert len(model.calls) == 2
    messages = model.envelope(1)["previous_attempt_errors"]
    guidance = "at least one" if mode == "selected" else "empty"
    assert any(guidance in message for message in messages), messages
    assert body == before
    assert bundle.limiter.events[-1] == ("release", "lease-1", False)


@pytest.mark.parametrize("flags", [[], ["-O"]], ids=["normal Python", "optimized Python"])
def test_chat_contract_and_correction_execute_in_fresh_network_blocked_processes(flags):
    probe = """
import copy
import json
import socket
import sys
sys.path[:0] = sys.argv[1:]
def blocked(*args, **kwargs):
    raise AssertionError("Network access is forbidden")
socket.socket.connect = blocked
socket.create_connection = blocked
socket.getaddrinfo = blocked
from functions_assist_diagnostics import AssistDiagnostics, safe_assist_diagnostics
from functions_workflow_assist_operations import OPERATION_SCHEMAS, validate_assist_output
from test_support import workflow_assist as wa
for name in OPERATION_SCHEMAS:
    safe = safe_assist_diagnostics({"assist_operation": name})
    if safe.get("assist_operation") != name:
        raise AssertionError("A supported operation is missing from diagnostics")
invalid = {"op": "set_workflow_chat_execution", "mode": "selected",
           "required_capabilities": [], "visual_requirements": []}
errors = validate_assist_output(json.loads(wa.reply(operations=[invalid])))
if not errors or not any("at least one" in message for message in errors):
    raise AssertionError("The schema did not explain the invalid selection")
valid = {**invalid, "mode": "off"}
model = wa.ScriptedModel(wa.reply(operations=[invalid]), wa.reply(operations=[valid]))
bundle = wa.services(model, options={
    "chat_execution": {"modes": [{"id": "off", "available": True}]},
})
events = []
bundle.diagnostics = AssistDiagnostics(events.append)
body = wa.request_body()
before = copy.deepcopy(body)
result = wa.run(body, bundle)
if result["outcome"] != "changed" or result["candidate"]["chat_execution"]["mode"] != "off":
    raise AssertionError("The corrected response did not produce a candidate")
if body != before or len(model.calls) != 2:
    raise AssertionError("Correction changed the input or did not make both calls")
rejected = [event for event in events if event["assist_event"] == "validation_rejected"]
if not rejected or rejected[0].get("assist_operation") != invalid["op"]:
    raise AssertionError("The operation name was lost")
if bundle.limiter.events[-1] != ("release", "lease-1", False):
    raise AssertionError("The limiter was not released")
sys.stdout.write(json.dumps({"outcome": result["outcome"], "calls": len(model.calls)}))
"""
    completed = subprocess.run(
        [sys.executable, "-B", *flags, "-c", probe, str(APP), str(ROOT / "functional_tests")],
        cwd=ROOT, capture_output=True, text=True, timeout=60, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"outcome": "changed", "calls": 2}


@pytest.mark.parametrize("identity", ["invented_tool", "deep_research"])
def test_unknown_or_unavailable_capabilities_do_not_fallback(identity):
    operation = {"op": "set_workflow_chat_execution", "mode": "selected",
                 "required_capabilities": [identity], "visual_requirements": []}
    errors = validate_assist_output(json.loads(wa.reply(operations=[operation])))
    if identity == "invented_tool":
        assert errors
        return
    with pytest.raises(AssistApplyError):
        apply([operation])


@pytest.mark.parametrize("operation", [
    {"op": "set_workflow_chat_execution", "mode": "off", "required_capabilities": [],
     "visual_requirements": [], "url_access_authorized": True},
    {"op": "set_results_recipients", "recipients": [ALICE]},
    {"op": "set_results_delivery", "mode": "conversation", "conversation_type": "group", "group_id": GROUP},
])
def test_closed_operations_reject_authority_routing_and_raw_identity_fields(operation):
    errors = validate_assist_output(json.loads(wa.reply(operations=[operation])))
    assert errors


def test_recipient_forgery_ambiguity_and_unrequested_audiences_are_refused():
    operations = [
        {"op": "set_results_delivery", "mode": "conversation", "conversation_type": "shared"},
        {"op": "set_results_recipients", "recipients": ["recipient_99"]},
    ]
    with pytest.raises(AssistApplyError):
        apply(operations)
    operations[-1]["recipients"] = ["recipient_2"]
    with pytest.raises(AssistApplyError):
        apply(operations, audience="Share with Alice")
    duplicate = options()
    duplicate["results_delivery"]["recipient_choices"][1]["label"] = "Alice (alice2@example.org)"
    draft = wa.new_draft()
    handles = AssistHandles(draft, user_id=wa.USER_ID, options=duplicate)
    operations[-1]["recipients"] = ["recipient_1"]
    with pytest.raises(AssistApplyError):
        apply_assist_operations(draft, {"operations": operations}, handles,
                                AssistApplyContext(audience_instruction="Share with Alice"))
    candidate, _info = apply_assist_operations(
        draft, {"operations": operations}, handles,
        AssistApplyContext(audience_instruction="Share with alice@example.org"),
    )
    assert candidate["results_delivery"]["recipient_ids"] == [ALICE]


def test_group_all_members_is_scoped_explicit_and_draft_only():
    operations = [
        {"op": "set_results_delivery", "mode": "conversation", "conversation_type": "group_shared"},
        {"op": "set_results_all_group_members", "enabled": True},
    ]
    changed = apply(operations, group=True, audience="Share with all current group members")
    delivery = normalize_results_delivery(changed["results_delivery"], workflow_scope="group")
    assert delivery["all_group_members"] is True
    assert delivery["recipient_ids"] == []
    assert changed["group_id"] == GROUP
    assert "conversation_id" not in changed
    with pytest.raises(AssistApplyError):
        apply(operations, group=True, audience="Rename the workflow")
    with pytest.raises(AssistApplyError):
        apply(operations, group=False, audience="Share with all members")


def test_group_request_cannot_rebind_scope_or_use_foreign_base_or_stale_revision():
    body = wa.request_body(wa.new_draft(group_id=GROUP))
    parsed = core.parse_assist_request(body, wa.USER_ID, group_id=GROUP)
    assert parsed.draft["group_id"] == GROUP
    with pytest.raises(core.WorkflowAssistError):
        core.parse_assist_request(body, wa.USER_ID, group_id="another-group")
    for stored, code in (
        (wa.stored_workflow(group_id="another-group"), "workflow_not_found"),
        (wa.stored_workflow(group_id=GROUP, definition_revision="new"), "workflow_definition_conflict"),
    ):
        model = wa.ScriptedModel()
        bundle = wa.services(model, stored=stored, options=options(True))
        bundle.group_id = GROUP
        base = wa.stored_workflow(group_id=GROUP)
        failure = wa.refusal(wa.request_body(stored=base), bundle)
        assert failure.code == code
        assert not model.calls


def test_group_candidate_dry_run_keeps_route_scope_and_creator_not_current_manager():
    stored = wa.stored_workflow(group_id=GROUP, user_id=wa.OTHER_USER_ID)
    model = wa.ScriptedModel(wa.reply(operations=[{"op": "set_name", "name": "Group review"}]))
    bundle = wa.services(model, stored=stored, options=options(True))
    bundle.group_id = GROUP
    result = wa.run(wa.request_body(stored=stored), bundle)
    assert result["candidate"]["group_id"] == GROUP
    assert result["candidate"]["user_id"] == wa.OTHER_USER_ID
    assert bundle.recorder.named("dry_run")[0][1]["group_id"] == GROUP


def test_group_revision_changed_during_model_call_returns_conflict_not_candidate():
    stored = wa.stored_workflow(group_id=GROUP)
    model = wa.ScriptedModel(wa.reply(operations=[{"op": "set_name", "name": "Group review"}]))
    bundle = wa.services(model, stored=stored, options=options(True), dry_run=lambda *_args: {
        "ok": False, "errors": [{"code": "workflow_definition_conflict", "path": "",
                               "message": "The saved workflow changed."}],
    })
    bundle.group_id = GROUP
    failure = wa.refusal(wa.request_body(stored=stored), bundle)
    assert failure.status == 409
    assert failure.code == "workflow_definition_conflict"
    assert len(model.calls) == 1


def test_ambiguous_recipient_corrects_to_question_without_applying_a_partial_audience():
    choices = options()
    choices["results_delivery"]["recipient_choices"][1]["label"] = "Alice (alice2@example.org)"
    model = wa.ScriptedModel(
        wa.reply(operations=[
            {"op": "set_results_delivery", "mode": "conversation", "conversation_type": "shared"},
            {"op": "set_results_recipients", "recipients": ["recipient_1"]},
        ]),
        wa.reply("question", "Which Alice should receive the results?"),
    )
    bundle = wa.services(model, options=choices)
    result = wa.run(wa.request_body(instruction="Share results with Alice"), bundle)
    assert result["outcome"] == "question"
    assert result["candidate"] is None
    assert not result["changes"]
    assert not bundle.recorder.named("dry_run")


def test_group_references_cannot_escape_route_group_before_excerpt_or_model():
    model = wa.ScriptedModel()
    bundle = wa.services(model, options=options(True))
    bundle.group_id = GROUP
    failure = wa.refusal(
        wa.request_body(wa.new_draft(group_id=GROUP), references=[wa.CHECKLIST]), bundle,
    )
    assert failure.code == "reference_unavailable"
    assert not model.calls
    assert not bundle.recorder.named("load_excerpt")


def test_editor_configuration_options_are_sanitized_existing_registry_choices(monkeypatch):
    import functions_orchestration_registry as registry
    from functions_workflow_configuration import WORKFLOW_CAPABILITY_IDS
    from functions_workflow_editor import build_workflow_configuration_options

    captured = []
    def resolve(settings, **kwargs):
        captured.append(kwargs)
        return [{"id": "web_search"}, {"id": "url_fetch"}, {"id": "deep_research"}, {"id": "compose"}]
    monkeypatch.setattr(registry, "resolve_available_capabilities", resolve)
    source = ModuleType("functions_source_review")
    source.is_url_access_enabled_for_user = lambda *_args, **_kwargs: False
    source.is_source_review_enabled_for_user = lambda *_args, **_kwargs: False
    monkeypatch.setitem(sys.modules, "functions_source_review", source)
    result = build_workflow_configuration_options({
        "enable_chat_orchestration": True, "secret": "DO-NOT-EXPOSE",
        "internal_endpoint": "PRIVATE-ENDPOINT",
    }, user_id=wa.USER_ID)
    capabilities = {row["id"]: row for row in result["chat_execution"]["capabilities"]}
    assert capabilities["web_search"]["available"] is True
    assert capabilities["url_fetch"]["available"] is False
    assert capabilities["deep_research"]["available"] is False
    assert capabilities["url_fetch"]["reason"] == "caller_access_required"
    assert result["chat_execution"]["default"]["mode"] == "orchestration"
    assert result["results_delivery"]["default"]["conversation_type"] == "personal"
    assert "DO-NOT-EXPOSE" not in json.dumps(result)
    assert "PRIVATE-ENDPOINT" not in json.dumps(result)
    assert all(not key.startswith("workflow_") for key in capabilities)
    assert set(capabilities) == set(WORKFLOW_CAPABILITY_IDS)
    assert captured[0]["include_runtime_bindings"] is False
    legacy = build_workflow_configuration_options(
        {"enable_collaborative_conversations": True}, user_id=wa.USER_ID, group_id=GROUP,
    )
    assert legacy["chat_execution"]["default"] is None
    assert legacy["results_delivery"]["default"]["conversation_type"] == "group"
    assert legacy["results_delivery"]["allow_all_group_members"] is True


@pytest.mark.parametrize("assistant,personal,group,expected", [
    (True, False, True, True), (False, True, True, False), (True, True, False, False),
])
def test_group_assistant_flag_is_independent_of_personal_workflows(monkeypatch, assistant, personal, group, expected):
    from functions_workflow_editor import workflow_assist_available

    names = ("is_group_workflows_enabled_for_group", "is_user_workflows_enabled_for_user",
             "is_workflow_assistant_enabled_for_user")
    tree = ast.parse((APP / "functions_settings.py").read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "scoped-setting", "exec"), namespace)
    module = ModuleType("functions_settings")
    module.__dict__.update(namespace)
    monkeypatch.setitem(sys.modules, "functions_settings", module)
    result = workflow_assist_available({
        "allow_user_workflows": personal, "allow_group_workflows": group,
        "enable_workflow_ai_assistant": assistant,
    }, group_id=GROUP)
    assert result is expected


def source_function(filename, name):
    path = APP / filename
    module = ast.parse(path.read_text(encoding="utf-8"))
    found = [node for node in ast.walk(module) if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(found) == 1
    return found[0]


@pytest.mark.parametrize("authorized", [False, True])
def test_group_route_rechecks_manager_and_has_no_personal_enablement_gate(authorized):
    route = source_function("route_backend_workflows.py", "assist_group_workflow")
    decorators = [ast.unparse(value) for value in route.decorator_list]
    assert decorators[:4] == [
        "bp.route('/api/groups/<group_id>/workflows/assist', methods=['POST'])",
        "swagger_route(security=get_auth_security())", "login_required", "user_required",
    ]
    assert not any("allow_user_workflows" in value or "workflow_user_required" in value for value in decorators)
    route.decorator_list = []
    calls = []
    def role(*args, **kwargs):
        calls.append(("role", args, kwargs))
        if not authorized:
            raise PermissionError("private")
    def response(payload, status, **kwargs):
        return payload, status
    namespace = {
        "get_current_user_id": lambda: wa.USER_ID, "get_settings": lambda: {"allow_user_workflows": False},
        "get_group_workflow_management_roles": lambda _settings: ["Owner", "Admin"],
        "assert_group_role": role, "_assert_group_workflow_feature_enabled": lambda *_args: None,
        "workflow_assist_available": lambda *_args, **kwargs: kwargs.get("group_id") == GROUP,
        "_workflow_assist_response": response, "session": session, "logging": logging,
        "_read_workflow_assist_body": lambda: {"instruction": "Rename"},
        "build_workflow_assist_services": lambda *_args, **kwargs: calls.append(("services", kwargs)),
        "_get_current_user_info_with_roles": lambda: {"user_id": wa.USER_ID},
        "_workflow_assist_client": lambda _settings: None,
        "run_workflow_assist": lambda *_args, **_kwargs: {"outcome": "explained"},
        "WorkflowAssistError": core.WorkflowAssistError, "log_event": lambda *_args, **_kwargs: None,
    }
    exec(compile(ast.Module(body=[route], type_ignores=[]), "group-route", "exec"), namespace)
    app = Flask(__name__)
    app.secret_key = "test-key"
    with app.test_request_context(method="POST"):
        body, status = namespace["assist_group_workflow"](GROUP)
    assert status == (200 if authorized else 403)
    assert calls[0][0] == "role"
    assert any(call[0] == "services" for call in calls) is authorized
    if authorized:
        service_call = next(call[1] for call in calls if call[0] == "services")
        assert service_call["group_id"] == GROUP


@pytest.mark.parametrize("mode,has_role,expected", [
    ("orchestration", True, True), ("orchestration", False, False), ("off", True, False),
    ("default", True, True), ("default", False, False),
    ("selected", True, True), ("selected", False, False),
])
def test_save_discards_forged_grants_and_captures_only_signed_in_roles(mode, has_role, expected):
    node = source_function("route_backend_workflows.py", "_prepare_workflow_url_access_payload")
    namespace = {
        "get_settings": lambda: {"enable_chat_orchestration": True},
        "session": session, "datetime": datetime, "timezone": timezone,
        "_normalize_bool": bool, "is_url_access_enabled_for_user": lambda *_args, **_kwargs: True,
        "is_source_review_enabled_for_user": lambda *_args, **_kwargs: True,
        "has_url_access_app_role": lambda roles: "UrlAccessUser" in roles,
        "has_deep_research_app_role": lambda roles: "DeepResearchUser" in roles,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "save-grants", "exec"), namespace)
    app = Flask(__name__)
    app.secret_key = "test"
    payload = {"chat_execution": execution(mode), "url_access_authorized": True,
               "url_access_authorized_by": "forged", "deep_research_authorized": True,
               "deep_research_authorized_by": "forged"}
    if mode == "default":
        payload.pop("chat_execution")
    if mode == "selected":
        payload["chat_execution"]["required_capabilities"] = ["url_fetch", "deep_research"]
    with app.test_request_context():
        session["user"] = {"roles": ["UrlAccessUser", "DeepResearchUser"] if has_role else []}
        prepared = namespace["_prepare_workflow_url_access_payload"](payload, wa.USER_ID)
    for prefix in ("url_access", "deep_research"):
        assert prepared[f"{prefix}_authorized"] is expected
        assert prepared[f"{prefix}_authorized_by"] == (wa.USER_ID if expected else "")
        assert bool(prepared[f"{prefix}_authorized_at"]) is expected


if __name__ == "__main__":
    raise SystemExit(pytest.main([str(Path(__file__).resolve())]))
