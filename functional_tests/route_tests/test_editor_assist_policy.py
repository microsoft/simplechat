#!/usr/bin/env python3
# test_editor_assist_policy.py
"""
Functional policy tests for the agent and action editor Ask AI routes.
Version: 0.261.278
Implemented in: 0.261.278

This test ensures that ``POST /api/agents/assist`` and ``POST /api/actions/assist`` keep their
Blueprint, Swagger and authentication decorators, refuse before any service starts when the admin
toggle or Semantic Kernel is off, authorize the requested scope (personal, group, global) with the
same roles that may edit agents and actions there, and answer with uncached strict JSON that never
echoes settings. The real route bodies run over the real editor assist runtime and core on a closed
Flask app, with a scripted model and an in-memory limiter. No Azure service is used.
"""

import ast
import json
import sys
from pathlib import Path

import pytest
from flask import Flask, session

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "functional_tests"))

import functions_editor_assist as core  # noqa: E402
import functions_editor_assist_runtime as runtime  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


AGENT_ROUTES = APP / "route_backend_agents.py"
ACTION_ROUTES = APP / "route_backend_plugins.py"
SETTINGS_MODULE = APP / "functions_settings.py"
USER_ID = "user-0001"
GROUP_ID = "group-0001"
SECRET = "SECRET-SETTING-VALUE-5c1d"
SUBMISSION_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"
ROUTES = {
    "agent": (AGENT_ROUTES, "/api/agents/assist", "assist_agent_editor", "bpa"),
    "action": (ACTION_ROUTES, "/api/actions/assist", "assist_action_editor", "bpap"),
}


def parsed(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def route_function(kind):
    path, route_path, _name, _bp = ROUTES[kind]
    matches = [
        node for node in parsed(path).body
        if isinstance(node, ast.FunctionDef)
        and node.decorator_list
        and isinstance(node.decorator_list[0], ast.Call)
        and node.decorator_list[0].args
        and getattr(node.decorator_list[0].args[0], "value", None) == route_path
    ]
    assert len(matches) == 1, f"expected one route for {route_path}, found {len(matches)}"
    return matches[0]


def settings_functions(*names):
    found = {
        node.name: node for node in parsed(SETTINGS_MODULE).body
        if isinstance(node, ast.FunctionDef) and node.name in names
    }
    assert sorted(found) == sorted(names)
    namespace = {}
    exec(compile(ast.Module(body=[found[name] for name in names], type_ignores=[]), str(SETTINGS_MODULE), "exec"), namespace)
    return namespace


class FakeBlueprint:
    def __init__(self, app):
        self.app = app

    def route(self, path, methods):
        def register(view):
            self.app.add_url_rule(path, endpoint=view.__name__, view_func=view, methods=methods)
            return view
        return register


def unchanged(view):
    return view


class FakeLimiter:
    def __init__(self):
        self.events = []

    def acquire(self, user_id):
        self.events.append(("acquire", user_id))
        return "lease"

    def release(self, lease, refund=False):
        self.events.append(("release", refund))


class ScriptedModel:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def __call__(self, messages, timeout):
        self.calls.append(messages)
        return json.dumps(self.reply), "stop"


def agent_body(**extra):
    body = {
        "submission_id": SUBMISSION_ID,
        "instruction": "Name it Helper.",
        "fields": [{"path": "/display_name", "label": "Name", "kind": "text"}],
        "values": {"/display_name": "Old"},
    }
    body.update(extra)
    return body


def action_body(**extra):
    body = {
        "submission_id": SUBMISSION_ID,
        "instruction": "Name it Helper.",
        "fields": [
            {"path": "/displayName", "label": "Name", "kind": "text"},
            {"path": "/additionalFields/api_key", "label": "API key", "kind": "text"},
        ],
        "values": {"/displayName": "Old", "/additionalFields/api_key": SECRET},
    }
    body.update(extra)
    return body


class Harness:
    def __init__(self, kind, monkeypatch):
        self.kind = kind
        self.settings = {
            "enable_semantic_kernel": True,
            "allow_user_agents": True,
            "allow_user_plugins": True,
            "azure_openai_gpt_key": SECRET,
        }
        self.roles = []
        self.group_available = (True, None)
        self.group_error = None
        self.group_calls = []
        self.limiter = FakeLimiter()
        path = "/display_name" if kind == "agent" else "/displayName"
        self.model = ScriptedModel({"reply": "Renamed.", "operations": [{"op": "set", "path": path, "value": "Helper"}]})
        self.built = []

        def build_services(*, client_factory, limiter=None):
            self.built.append(client_factory)
            return core.EditorAssistServices(limiter=self.limiter, call_model=self.model)

        monkeypatch.setattr(runtime, "build_editor_assist_services", build_services)

        import functions_agent_delegation

        def resolve_scope(user_id, group_id=None, *, allowed_roles):
            self.group_calls.append((user_id, group_id, tuple(allowed_roles)))
            if self.group_error is not None:
                raise self.group_error
            return group_id or GROUP_ID

        monkeypatch.setattr(functions_agent_delegation, "resolve_delegation_group_scope", resolve_scope)

        app = Flask(f"editor-assist-{kind}")
        app.secret_key = "test"
        _path, _route, _name, bp_name = ROUTES[kind]
        gates = settings_functions("is_agent_assistant_enabled", "is_action_assistant_enabled")
        namespace = {
            bp_name: FakeBlueprint(app),
            "swagger_route": lambda **_security: unchanged,
            "get_auth_security": lambda: [{"bearerAuth": []}],
            "login_required": unchanged,
            "user_required": unchanged,
            "session": session,
            "get_settings": lambda: self.settings,
            "get_current_user_id": lambda: USER_ID,
            "is_agent_assistant_enabled": gates["is_agent_assistant_enabled"],
            "is_action_assistant_enabled": gates["is_action_assistant_enabled"],
            "EditorAssistError": core.EditorAssistError,
            "editor_assist_error_response": runtime.editor_assist_error_response,
            "handle_editor_assist_request": runtime.handle_editor_assist_request,
            "authorize_group_editor_scope": runtime.authorize_group_editor_scope,
            "is_session_admin": runtime.is_session_admin,
            "group_agent_write_roles": lambda settings: ("Owner", "Admin"),
            "group_agents_available": lambda user_id, settings: self.group_available,
            "group_action_write_roles": lambda settings: ("Owner", "Admin"),
            "group_actions_available": lambda user_id, settings: self.group_available,
            "_create_agent_instruction_client": lambda settings: "client",
            "_resolve_agent_instruction_model": lambda settings: "draft-model",
        }
        exec(compile(ast.Module(body=[route_function(kind)], type_ignores=[]), str(_path), "exec"), namespace)
        self.app = app
        self.route = _route

    def post(self, body=None, **kwargs):
        if body is None:
            body = agent_body() if self.kind == "agent" else action_body()
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user"] = {"roles": list(self.roles)}
            if "data" not in kwargs:
                kwargs["data"] = json.dumps(body)
                kwargs.setdefault("content_type", "application/json")
            return client.post(self.route, **kwargs)

    def reached_nothing(self):
        return self.built == [] and self.limiter.events == [] and self.model.calls == []


@pytest.fixture(params=["agent", "action"])
def harness(request, monkeypatch):
    return Harness(request.param, monkeypatch)


def assert_closed_error(response, status, code):
    assert response.status_code == status
    assert response.headers["Cache-Control"] == "no-store, private"
    assert response.json["code"] == code
    assert response.json["error"]
    assert SECRET not in response.get_data(as_text=True)


@pytest.mark.parametrize("kind", ["agent", "action"])
def test_the_routes_keep_their_blueprint_swagger_and_auth_decorators(kind):
    assert_app_version_at_least("0.261.278")
    _path, route_path, name, bp_name = ROUTES[kind]
    function = route_function(kind)
    assert function.name == name
    assert [ast.unparse(value) for value in function.decorator_list] == [
        f"{bp_name}.route('{route_path}', methods=['POST'])",
        "swagger_route(security=get_auth_security())",
        "login_required",
        "user_required",
    ]


def test_an_allowed_personal_request_answers_with_an_uncached_candidate(harness):
    response = harness.post()

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, private"
    assert response.json["outcome"] == "changed"
    values = response.json["candidate"]["values"]
    assert "Helper" in values.values()
    assert SECRET not in response.get_data(as_text=True)
    assert harness.limiter.events == [("acquire", USER_ID), ("release", False)]
    # The model client is the draft-instructions deployment.
    assert harness.built[0]() == ("client", "draft-model")


def test_secret_fields_never_reach_the_model(harness):
    harness.post()
    [messages] = harness.model.calls
    assert SECRET not in json.dumps(messages)


@pytest.mark.parametrize("change", [
    {"enable_semantic_kernel": False},
    {"enable_agent_ai_assistant": False, "enable_action_ai_assistant": False},
])
def test_a_turned_off_assistant_refuses_before_any_service(harness, change):
    harness.settings.update(change)
    response = harness.post()
    code = "agent_assistant_disabled" if harness.kind == "agent" else "action_assistant_disabled"
    assert_closed_error(response, 403, code)
    assert harness.reached_nothing()


def test_personal_scope_follows_the_personal_toggle(harness):
    harness.settings["allow_user_agents" if harness.kind == "agent" else "allow_user_plugins"] = False
    assert_closed_error(harness.post(), 403, "scope_forbidden")
    assert harness.reached_nothing()


def test_global_scope_requires_the_admin_role(harness):
    body = (agent_body if harness.kind == "agent" else action_body)(scope="global")
    assert_closed_error(harness.post(body), 403, "scope_forbidden")
    assert harness.reached_nothing()

    harness.roles = ["Admin"]
    assert harness.post(body).status_code == 200


def test_group_scope_authorizes_the_named_group_with_editor_roles(harness):
    body = (agent_body if harness.kind == "agent" else action_body)(scope="group", group_id=GROUP_ID)
    assert harness.post(body).status_code == 200
    assert harness.group_calls == [(USER_ID, GROUP_ID, ("Owner", "Admin"))]


@pytest.mark.parametrize("error, status, code", [
    (PermissionError("no"), 403, "scope_forbidden"),
    (ValueError("bad"), 403, "scope_forbidden"),
    (LookupError("missing"), 404, "scope_not_found"),
])
def test_group_scope_refusals_are_closed(harness, error, status, code):
    harness.group_error = error
    body = (agent_body if harness.kind == "agent" else action_body)(scope="group", group_id=GROUP_ID)
    assert_closed_error(harness.post(body), status, code)
    assert harness.reached_nothing()


def test_unavailable_group_surface_refuses(harness):
    harness.group_available = (False, "Group agents are not enabled.")
    body = (agent_body if harness.kind == "agent" else action_body)(scope="group", group_id=GROUP_ID)
    assert_closed_error(harness.post(body), 403, "scope_forbidden")
    assert harness.group_calls == [] and harness.reached_nothing()


@pytest.mark.parametrize("extra", [{"scope": "tenant"}, {"scope": "group", "group_id": 7}])
def test_an_invalid_scope_is_a_bad_request(harness, extra):
    body = (agent_body if harness.kind == "agent" else action_body)(**extra)
    assert_closed_error(harness.post(body), 400, "invalid_request")
    assert harness.reached_nothing()


def test_a_non_json_body_is_a_bad_request(harness):
    response = harness.post(data="name it", content_type="text/plain")
    assert_closed_error(response, 400, "invalid_request")
    assert harness.reached_nothing()


def test_an_oversized_body_is_refused_unread(harness):
    response = harness.post(data=b"{" + b" " * core.EDITOR_ASSIST_MAX_BODY_BYTES + b"}", content_type="application/json")
    assert_closed_error(response, 413, "request_too_large")
    assert harness.reached_nothing()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
