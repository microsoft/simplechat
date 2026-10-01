#!/usr/bin/env python3
# test_workflow_draft_instructions_assistant_gate.py
"""
Functional test for the workflow draft-instructions AI assistant gate.
Version: 0.261.215
Implemented in: 0.261.215

This test ensures that ``POST /api/workflows/draft-instructions`` follows the admin's Enable AI
Workflow Assistant setting for personal workflows. When the assistant isn't available to the
signed-in user, the route answers 403 with the same body as ``workflow_assistant_required`` and
never creates or calls a model client. The personal-workflow 400, the WorkflowUser role 403,
group-scope drafting and the invalid-scope 400 keep their existing answers. It also ensures the
classic personal workspace receives a role-aware ``enable_workflow_ai_assistant`` flag and hides its
Task Brief and Draft Workflow Instructions controls when the flag is off, while the group workspace
keeps them.

The real route bodies, the real gate helpers from ``functions_settings.py`` and the real workflow
modal markup run on closed Flask and Jinja environments. The model client, group resolver and Cosmos
are fakes. No live application, credential, model or Azure service is used.
"""

import ast
import copy
import logging
import re
import sys
import traceback
from functools import wraps
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, jsonify, request
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(ROOT / "functional_tests"))

# Shared test helpers follow the worktree import setup.
from test_support.versioning import assert_app_version_at_least  # noqa: E402


ROUTES = APP / "route_backend_workflows.py"
SETTINGS_MODULE = APP / "functions_settings.py"
WORKSPACE_ROUTES = APP / "route_frontend_workspace.py"
TEMPLATE_DIR = APP / "templates"
DRAFT_PATH = "/api/workflows/draft-instructions"
USER_ID = "user-n9-0001"
GROUP_ID = "group-n9-0001"
SECRET = "SECRET-SETTING-VALUE-n9-4c1d"
MODEL_NAME = "draft-instructions-deployment"
DRAFTED = "1. Review the new tickets.\n2. Summarize the themes."
MISSING = object()

ASSISTANT_DISABLED = {
    "error": "The AI workflow assistant is not available.",
    "code": "workflow_assistant_disabled",
}
ROLE_REQUIRED = {"error": "Personal workflows require the WorkflowUser app role."}
PERSONAL_DISABLED = {"error": "Personal workflows are disabled."}
INVALID_SCOPE = {"error": "Invalid workflow scope."}
NO_DRAFT_INPUT = {"error": "Provide a task brief, workflow name, description, or existing instructions."}

SETTINGS_FUNCTIONS = (
    "normalize_app_role_claims", "has_workflow_user_app_role", "is_user_workflows_enabled_for_user",
    "is_workflow_assistant_enabled_for_user", "workflow_assistant_required", "enabled_required",
    "sanitize_settings_for_user",
)
DRAFT_HELPERS = (
    "_normalize_workflow_instruction_draft_input", "_build_workflow_instruction_messages",
    "_assert_personal_workflow_draft_access",
)
EXPECTED_DRAFT_DECORATORS = [
    f"bp.route('{DRAFT_PATH}', methods=['POST'])",
    "swagger_route(security=get_auth_security())",
    "login_required",
    "user_required",
]
DRAFT_CONTROL_IDS = ("workflow-task-brief", "workflow-draft-instructions-btn", "workflow-draft-instructions-status")
PERSONAL_DRAFT = {"workflow_scope": "personal", "name": "Nightly review", "brief": "Summarize new support tickets."}
GROUP_DRAFT = {"workflow_scope": "group", "name": "Group digest", "brief": "Summarize group tickets."}
# Every request shape that resolves to personal scope, including an empty body: the assistant
# gate answers before the route checks that there is something to draft from.
PERSONAL_REQUESTS = (
    PERSONAL_DRAFT,
    {"name": "Nightly review"},
    {"workflow_scope": "  PERSONAL ", "brief": "Summarize new support tickets."},
    {},
)
# The route uses the same strict helper as ``workflow_assistant_required``: only ``True`` is on.
ASSISTANT_OFF_VALUES = (False, None, "true", 1, MISSING)


def parsed_module(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def top_level_functions(path, names):
    found = {
        node.name: node for node in parsed_module(path).body
        if isinstance(node, ast.FunctionDef) and node.name in names
    }
    missing = sorted(set(names) - set(found))
    if missing:
        raise AssertionError(f"{path.name} no longer defines {missing}")
    return [found[name] for name in names]


def top_level_constant(path, name):
    for node in parsed_module(path).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path.name} no longer defines {name}")


def nested_route(path, registrar_name, route_path):
    registrar = next(
        (
            node for node in parsed_module(path).body
            if isinstance(node, ast.FunctionDef) and node.name == registrar_name
        ),
        None,
    )
    if registrar is None:
        raise AssertionError(f"{path.name} no longer defines {registrar_name}")
    matches = [
        node for node in registrar.body
        if isinstance(node, ast.FunctionDef)
        and node.decorator_list
        and isinstance(node.decorator_list[0], ast.Call)
        and node.decorator_list[0].args
        and getattr(node.decorator_list[0].args[0], "value", None) == route_path
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one route for {route_path} in {path.name}, found {len(matches)}")
    return matches[0]


def run_source(nodes, path, namespace):
    exec(compile(ast.Module(body=list(nodes), type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class Blueprint:
    """Registers a view the way ``bp.route`` does, on a closed Flask app."""

    def __init__(self, app):
        self.app = app

    def route(self, path, methods):
        def register(view):
            self.app.add_url_rule(path, endpoint=view.__name__, view_func=view, methods=methods)
            return view
        return register


def unchanged(view):
    return view


def refuse(name):
    def refused(*_args, **_kwargs):
        raise AssertionError(f"The code under test called {name}, which this test does not expect")
    return refused


def workflow_settings(**overrides):
    settings = {
        "allow_user_workflows": True,
        "require_member_of_workflow_user": False,
        "enable_workflow_ai_assistant": True,
        "allow_group_workflows": True,
        "enable_user_workspace": True,
        "enable_url_access": False,
        "document_action_capabilities": {"analyze": {"enabled": True}, "comparison": {"enabled": True}},
        "azure_openai_gpt_key": SECRET,
    }
    for key, value in overrides.items():
        if value is MISSING:
            settings.pop(key, None)
        else:
            settings[key] = value
    return settings


def load_settings_functions(session, get_settings):
    """The real gate helpers, decorators and settings sanitizer from ``functions_settings.py``."""
    return run_source(top_level_functions(SETTINGS_MODULE, SETTINGS_FUNCTIONS), SETTINGS_MODULE, {
        "wraps": wraps,
        "request": request,
        "jsonify": jsonify,
        "session": session,
        "get_settings": get_settings,
        "WORKFLOW_USER_APP_ROLE": top_level_constant(SETTINGS_MODULE, "WORKFLOW_USER_APP_ROLE"),
        "TABULAR_GENERATION_BACKEND_SETTING_KEYS": frozenset(),
        "sanitize_model_endpoints_for_frontend": lambda endpoints, include_connection_details=False: [],
        "normalize_support_latest_features_visibility": lambda value: {},
        "has_visible_support_latest_features": lambda settings: False,
        "get_public_workspace_label_context": lambda settings: {},
    })


class FakeCompletions:
    def __init__(self, harness):
        self.harness = harness

    def create(self, **params):
        self.harness.completions.append(copy.deepcopy(params))
        message = SimpleNamespace(content=self.harness.drafted)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class DraftHarness:
    """The real draft route, its helpers and gates on a closed Flask app with a fake model client."""

    def __init__(self, roles=(), group_error=None, **settings_overrides):
        self.settings = workflow_settings(**settings_overrides)
        self.session = {"user": {"roles": list(roles)}}
        self.group_error = group_error
        self.drafted = DRAFTED
        self.models_resolved = []
        self.clients_created = []
        self.completions = []
        self.groups_resolved = []
        self.logs = []

        gates = load_settings_functions(self.session, lambda: self.settings)
        helpers = run_source(top_level_functions(ROUTES, DRAFT_HELPERS), ROUTES, {
            "re": re,
            "session": self.session,
            "is_user_workflows_enabled_for_user": gates["is_user_workflows_enabled_for_user"],
            "WORKFLOW_INSTRUCTION_FIELD_LIMIT": top_level_constant(ROUTES, "WORKFLOW_INSTRUCTION_FIELD_LIMIT"),
        })
        app = Flask("workflow-draft-instructions-assistant-gate")
        run_source([nested_route(ROUTES, "register_route_backend_workflows", DRAFT_PATH)], ROUTES, {
            "bp": Blueprint(app),
            "swagger_route": lambda **_security: unchanged,
            "get_auth_security": lambda: [{"bearerAuth": []}],
            "login_required": unchanged,
            "user_required": unchanged,
            "request": request,
            "jsonify": jsonify,
            "session": self.session,
            "logging": logging,
            "get_settings": lambda: self.settings,
            "get_current_user_id": lambda: USER_ID,
            "log_event": self.log_event,
            "is_workflow_assistant_enabled_for_user": gates["is_workflow_assistant_enabled_for_user"],
            "_assert_personal_workflow_draft_access": helpers["_assert_personal_workflow_draft_access"],
            "_build_workflow_instruction_messages": helpers["_build_workflow_instruction_messages"],
            "_resolve_active_group_for_workflow_management": self.resolve_group,
            "_resolve_agent_instruction_model": self.resolve_model,
            "_create_agent_instruction_client": self.create_client,
            "_build_agent_instruction_api_params": lambda model_name, messages: {
                "model": model_name, "messages": messages,
            },
        })
        # The real decorator on a probe view gives the answer the route has to match.
        app.add_url_rule(
            "/decorator-probe",
            endpoint="decorator_probe",
            view_func=gates["workflow_assistant_required"](lambda: jsonify({"reached": True})),
            methods=["POST"],
        )
        self.client = app.test_client()

    def log_event(self, message, extra=None, level=None, **kwargs):
        self.logs.append((message, copy.deepcopy(extra), level, kwargs))

    def resolve_group(self, user_id):
        self.groups_resolved.append(user_id)
        if self.group_error is not None:
            raise self.group_error
        return {"id": GROUP_ID}

    def resolve_model(self, settings):
        self.models_resolved.append(settings is self.settings)
        return MODEL_NAME

    def create_client(self, settings):
        self.clients_created.append(settings is self.settings)
        return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(self)))

    def post(self, body=PERSONAL_DRAFT):
        return self.client.post(DRAFT_PATH, json=body)

    def decorator_probe(self):
        return self.client.post("/decorator-probe", json={})

    def model_work(self):
        return self.models_resolved, self.clients_created, self.completions


class WorkspaceHarness:
    """The real classic workspace route on a closed Flask app, capturing what it renders."""

    def __init__(self, roles=(), **settings_overrides):
        self.settings = workflow_settings(**settings_overrides)
        self.session = {"user": {"roles": list(roles)}}
        self.rendered = []
        self.gates = load_settings_functions(self.session, lambda: self.settings)
        app = Flask("workflow-draft-instructions-workspace")
        run_source([nested_route(WORKSPACE_ROUTES, "register_route_frontend_workspace", "/workspace")], WORKSPACE_ROUTES, {
            "bp": Blueprint(app),
            "swagger_route": lambda **_security: unchanged,
            "get_auth_security": lambda: [{"bearerAuth": []}],
            "login_required": unchanged,
            "user_required": unchanged,
            "enabled_required": self.gates["enabled_required"],
            "session": self.session,
            "logging": logging,
            "log_event": refuse("log_event"),
            "get_current_user_id": lambda: USER_ID,
            "get_current_user_info": lambda: {"userId": USER_ID},
            "get_settings": lambda: self.settings,
            "get_user_settings": lambda user_id: {"settings": {}},
            "sanitize_settings_for_user": self.gates["sanitize_settings_for_user"],
            "is_user_workflows_enabled_for_user": self.gates["is_user_workflows_enabled_for_user"],
            "is_workflow_assistant_enabled_for_user": self.gates["is_workflow_assistant_enabled_for_user"],
            "is_url_access_enabled_for_user": lambda settings, user_roles=None: bool(settings.get("enable_url_access")),
            "build_workspace_section_availability": lambda settings, user_id, user_info=None, user_roles=None: {
                "file_sync_enabled": False, "governance": {},
            },
            "cosmos_user_documents_container": SimpleNamespace(query_items=lambda **_query: iter([0])),
            "get_allowed_extension_categories": lambda **_options: {},
            "CLIENTS": {},
            "sanitize_model_endpoints_for_frontend": lambda endpoints: list(endpoints or []),
            "filter_governed_model_endpoints": lambda user_id, endpoints, governance_key: list(endpoints or []),
            "get_user_groups": lambda user_id: [],
            "get_user_visible_public_workspace_docs": lambda user_id: [],
            "redirect": refuse("redirect"),
            "url_for": refuse("url_for"),
            "render_template": self.render_template,
        })
        self.client = app.test_client()

    def render_template(self, template_name, **context):
        self.rendered.append((template_name, copy.deepcopy(context)))
        return "rendered"

    def page_settings(self):
        response = self.client.get("/workspace")
        if response.status_code != 200 or len(self.rendered) != 1:
            raise AssertionError(f"/workspace answered {response.status_code} with {len(self.rendered)} renders")
        template_name, context = self.rendered[0]
        if template_name != "workspace.html":
            raise AssertionError(f"/workspace rendered {template_name}")
        return context["settings"]


def workflow_modal_source(template_name, workflow_flag):
    """The classic workflow modal, from its opening ``{% if settings.<flag> %}`` to the matching endif."""
    lines = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8").splitlines()
    modal_lines = [index for index, line in enumerate(lines) if 'id="workflowModal"' in line]
    if len(modal_lines) != 1:
        raise AssertionError(f"{template_name} has {len(modal_lines)} workflow modals")
    opening = re.compile(r"\{%-?\s*if\s+settings\." + re.escape(workflow_flag) + r"\s*-?%\}")
    start = next((index for index in range(modal_lines[0], -1, -1) if opening.search(lines[index])), None)
    if start is None:
        raise AssertionError(f"{template_name} no longer wraps its workflow modal in settings.{workflow_flag}")
    depth = 0
    for end in range(start, len(lines)):
        for match in re.finditer(r"\{%-?\s*(if|endif)\b", lines[end]):
            depth += 1 if match.group(1) == "if" else -1
        if depth == 0:
            return "\n".join(lines[start:end + 1])
    raise AssertionError(f"{template_name} never closes its settings.{workflow_flag} block")


def render_workflow_modal(template_name, workflow_flag, settings):
    environment = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    return environment.from_string(workflow_modal_source(template_name, workflow_flag)).render(settings=settings)


def modal_settings(assistant):
    settings = {
        "allow_user_workflows": True,
        "allow_group_workflows": True,
        "enable_url_access": True,
        "document_action_capabilities": {"analyze": {"enabled": True}, "comparison": {"enabled": True}},
    }
    if assistant is not MISSING:
        settings["enable_workflow_ai_assistant"] = assistant
    return settings


def element_count(html, element_id):
    return len(re.findall(r'\bid="' + re.escape(element_id) + r'"', html))


# (settings overrides, session roles, expected flag)
WORKSPACE_FLAG_CASES = (
    ({}, (), True),
    ({"enable_workflow_ai_assistant": False}, (), False),
    ({"require_member_of_workflow_user": True}, (), False),
    ({"require_member_of_workflow_user": True}, ("WorkflowUser",), True),
    ({"require_member_of_workflow_user": True, "enable_workflow_ai_assistant": False}, ("WorkflowUser",), False),
    ({"allow_user_workflows": False}, (), False),
)


def test_personal_drafting_with_the_assistant_on_reaches_the_model():
    assert_app_version_at_least("0.261.215")
    for body in PERSONAL_REQUESTS[:-1]:
        harness = DraftHarness()
        response = harness.post(body)
        payload = response.get_json()

        assert response.status_code == 200, (body, payload)
        assert payload == {"success": True, "instructions": DRAFTED}
        assert harness.models_resolved == [True] and harness.clients_created == [True]
        assert len(harness.completions) == 1 and harness.completions[0]["model"] == MODEL_NAME
        assert harness.groups_resolved == []
        assert [entry[1]["workflow_scope"] for entry in harness.logs] == ["personal"]

    harness = DraftHarness()
    response = harness.post()
    assert response.status_code == 200 and len(harness.completions) == 1
    user_message = harness.completions[0]["messages"][1]["content"]
    assert "Task brief: Summarize new support tickets." in user_message
    assert "Workflow name: Nightly review" in user_message

    empty = DraftHarness()
    empty_response = empty.post({})
    assert (empty_response.status_code, empty_response.get_json()) == (400, NO_DRAFT_INPUT)
    assert empty.model_work() == ([], [], [])


def test_personal_drafting_with_the_assistant_off_is_refused_before_any_model_work():
    for value in ASSISTANT_OFF_VALUES:
        for body in PERSONAL_REQUESTS:
            harness = DraftHarness(enable_workflow_ai_assistant=value)
            response = harness.post(body)
            probe = harness.decorator_probe()
            text = response.get_data(as_text=True)

            assert response.status_code == 403, (value, body, response.get_json())
            assert response.get_json() == ASSISTANT_DISABLED
            assert (probe.status_code, probe.get_json()) == (403, response.get_json())
            assert harness.model_work() == ([], [], [])
            assert harness.groups_resolved == [] and harness.logs == []
            assert SECRET not in text and "Nightly review" not in text


def test_a_workflow_user_still_needs_the_assistant_for_personal_drafting():
    allowed = DraftHarness(roles=("WorkflowUser",), require_member_of_workflow_user=True)
    allowed_response = allowed.post()
    refused = DraftHarness(
        roles=("workflowuser",), require_member_of_workflow_user=True, enable_workflow_ai_assistant=False,
    )
    refused_response = refused.post()

    assert allowed_response.status_code == 200 and allowed_response.get_json()["success"] is True
    assert len(allowed.completions) == 1
    assert (refused_response.status_code, refused_response.get_json()) == (403, ASSISTANT_DISABLED)
    assert refused.model_work() == ([], [], [])


def test_personal_availability_and_role_answers_are_unchanged_and_come_first():
    cases = (
        ({"require_member_of_workflow_user": True}, (), 403, ROLE_REQUIRED),
        ({"require_member_of_workflow_user": True, "enable_workflow_ai_assistant": False}, (), 403, ROLE_REQUIRED),
        ({"require_member_of_workflow_user": True, "enable_workflow_ai_assistant": False}, ("Admin",), 403, ROLE_REQUIRED),
        ({"allow_user_workflows": False}, (), 400, PERSONAL_DISABLED),
        ({"allow_user_workflows": False, "enable_workflow_ai_assistant": False}, (), 400, PERSONAL_DISABLED),
        (
            {"allow_user_workflows": False, "require_member_of_workflow_user": True, "enable_workflow_ai_assistant": False},
            ("WorkflowUser",), 400, PERSONAL_DISABLED,
        ),
    )
    for overrides, roles, status, body in cases:
        harness = DraftHarness(roles=roles, **overrides)
        response = harness.post()

        assert (response.status_code, response.get_json()) == (status, body), (overrides, roles)
        assert harness.model_work() == ([], [], [])
        assert harness.groups_resolved == []


def test_group_drafting_does_not_follow_the_personal_assistant_setting():
    variants = (
        {"enable_workflow_ai_assistant": True},
        {"enable_workflow_ai_assistant": False},
        {"enable_workflow_ai_assistant": MISSING},
        {"enable_workflow_ai_assistant": False, "allow_user_workflows": False},
        {"enable_workflow_ai_assistant": False, "require_member_of_workflow_user": True},
    )
    for overrides in variants:
        harness = DraftHarness(**overrides)
        response = harness.post(GROUP_DRAFT)

        assert response.status_code == 200, (overrides, response.get_json())
        assert response.get_json() == {"success": True, "instructions": DRAFTED}
        assert harness.groups_resolved == [USER_ID]
        assert harness.clients_created == [True] and len(harness.completions) == 1
        assert [entry[1]["workflow_scope"] for entry in harness.logs] == ["group"]


def test_group_refusals_are_unchanged():
    refusals = (
        (PermissionError("You do not have permission to manage group workflows."), 403),
        (LookupError("No active group is selected."), 403),
        (ValueError("Group workflows are disabled."), 400),
    )
    for error, status in refusals:
        for assistant in (True, False):
            harness = DraftHarness(group_error=error, enable_workflow_ai_assistant=assistant)
            response = harness.post(GROUP_DRAFT)

            assert (response.status_code, response.get_json()) == (status, {"error": str(error)})
            assert harness.groups_resolved == [USER_ID]
            assert harness.model_work() == ([], [], [])


def test_an_invalid_scope_is_still_rejected():
    for assistant in (True, False):
        for scope in ("public", "global", "admin"):
            harness = DraftHarness(enable_workflow_ai_assistant=assistant)
            response = harness.post({"workflow_scope": scope, "brief": "Summarize new support tickets."})

            assert (response.status_code, response.get_json()) == (400, INVALID_SCOPE), (assistant, scope)
            assert harness.groups_resolved == []
            assert harness.model_work() == ([], [], [])


def test_the_route_is_not_wrapped_in_the_assistant_decorator():
    route = nested_route(ROUTES, "register_route_backend_workflows", DRAFT_PATH)
    decorators = [ast.unparse(decorator) for decorator in route.decorator_list]

    # A route-level ``workflow_assistant_required`` would also refuse group drafting.
    assert decorators == EXPECTED_DRAFT_DECORATORS


def test_the_classic_workspace_gets_a_role_aware_assistant_flag():
    for overrides, roles, expected in WORKSPACE_FLAG_CASES:
        harness = WorkspaceHarness(roles=roles, **overrides)
        page_settings = harness.page_settings()
        helper_answer = harness.gates["is_workflow_assistant_enabled_for_user"](harness.settings, user_roles=list(roles))

        assert page_settings["enable_workflow_ai_assistant"] is expected, (overrides, roles)
        assert helper_answer is expected
        assert "azure_openai_gpt_key" not in page_settings
        assert SECRET not in repr(harness.rendered)


def test_the_personal_modal_hides_the_draft_controls_when_the_assistant_is_off():
    on_html = render_workflow_modal("workspace.html", "allow_user_workflows", modal_settings(True))
    off_renders = [
        render_workflow_modal("workspace.html", "allow_user_workflows", modal_settings(value))
        for value in (False, MISSING)
    ]

    for element_id in DRAFT_CONTROL_IDS:
        assert element_count(on_html, element_id) == 1, element_id
    assert element_count(on_html, "workflow-task-prompt") == 1
    for off_html in off_renders:
        for element_id in DRAFT_CONTROL_IDS:
            assert element_count(off_html, element_id) == 0, element_id
        assert 'for="workflow-task-brief"' not in off_html
        assert element_count(off_html, "workflow-task-prompt") == 1
        assert element_count(off_html, "workflowModal") == 1


def test_the_group_modal_keeps_its_draft_controls():
    group_source = (TEMPLATE_DIR / "group_workspaces.html").read_text(encoding="utf-8")
    renders = [
        render_workflow_modal("group_workspaces.html", "allow_group_workflows", modal_settings(value))
        for value in (True, False, MISSING)
    ]

    assert "enable_workflow_ai_assistant" not in group_source
    for html in renders:
        for element_id in (*DRAFT_CONTROL_IDS, "workflow-task-prompt"):
            assert element_count(html, element_id) == 1, element_id


def test_the_workspace_route_and_template_hide_the_draft_button_together():
    for overrides, roles, expected in WORKSPACE_FLAG_CASES:
        harness = WorkspaceHarness(roles=roles, **overrides)
        page_settings = harness.page_settings()
        html = render_workflow_modal("workspace.html", "allow_user_workflows", page_settings)

        assert element_count(html, "workflow-draft-instructions-btn") == (1 if expected else 0), (overrides, roles)


TESTS = (
    test_personal_drafting_with_the_assistant_on_reaches_the_model,
    test_personal_drafting_with_the_assistant_off_is_refused_before_any_model_work,
    test_a_workflow_user_still_needs_the_assistant_for_personal_drafting,
    test_personal_availability_and_role_answers_are_unchanged_and_come_first,
    test_group_drafting_does_not_follow_the_personal_assistant_setting,
    test_group_refusals_are_unchanged,
    test_an_invalid_scope_is_still_rejected,
    test_the_route_is_not_wrapped_in_the_assistant_decorator,
    test_the_classic_workspace_gets_a_role_aware_assistant_flag,
    test_the_personal_modal_hides_the_draft_controls_when_the_assistant_is_off,
    test_the_group_modal_keeps_its_draft_controls,
    test_the_workspace_route_and_template_hide_the_draft_button_together,
)


def main():
    failures = 0
    for test in TESTS:
        try:
            test()
        except Exception as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc!r}")
            traceback.print_exc()
        else:
            print(f"PASS {test.__name__}")
    print(f"{len(TESTS) - failures}/{len(TESTS)} tests passed")
    return failures == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
