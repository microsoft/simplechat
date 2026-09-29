#!/usr/bin/env python3
# test_workflow_assist_policy.py
"""
Functional policy tests for the AI workflow assistant route.
Version: 0.261.205
Implemented in: 0.261.205

This test ensures that ``POST /api/user/workflows/assist`` keeps its Blueprint, Swagger and gate
order, that each gate refuses before any service starts, that the body is read as bounded strict
JSON, and that every refusal keeps its status, closed code and ``Retry-After`` header without
echoing request content, model output or settings.

The real route body, its helpers and the real gate decorators from ``functions_settings.py`` run on
a closed Flask app over the real assist core. The services are the shared fakes with a scripted
model. No live application, permissions, credentials, model or Azure service is used.
"""

import ast
import copy
import json
import logging
import sys
from functools import wraps
from pathlib import Path

import pytest
from flask import Flask, jsonify, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "functional_tests"))

# Shared test helpers follow the isolated worktree import setup.
import functions_workflow_assist as core  # noqa: E402
from test_support import workflow_assist as wa  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


ROUTES = APP / "route_backend_workflows.py"
SETTINGS_MODULE = APP / "functions_settings.py"
ROUTE_PATH = "/api/user/workflows/assist"
GATE_FUNCTIONS = (
    "normalize_app_role_claims", "has_workflow_user_app_role", "is_user_workflows_enabled_for_user",
    "is_workflow_assistant_enabled_for_user", "_is_api_request", "workflow_user_required",
    "workflow_assistant_required", "enabled_required",
)
ROUTE_HELPERS = ("_workflow_assist_client", "_read_workflow_assist_body", "_workflow_assist_response")
SECRET = "SECRET-SETTING-VALUE-7f3a"
SENTINEL = "SENTINEL-ROUTE-CONTENT-91b2"
DRAFT_INSTRUCTIONS_MODEL = "draft-instructions-deployment"
RENAMED = wa.reply("changed", "Renamed the workflow.", [{"op": "set_name", "name": "Nightly review"}])


def parsed_module(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def top_level_functions(path, names):
    found = {
        node.name: node for node in parsed_module(path).body
        if isinstance(node, ast.FunctionDef) and node.name in names
    }
    missing = sorted(set(names) - set(found))
    assert missing == [], f"{path.name} no longer defines {missing}"
    return [found[name] for name in names]


def top_level_constant(path, name):
    for node in parsed_module(path).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path.name} no longer defines {name}")


def route_function():
    registrar = next(
        node for node in parsed_module(ROUTES).body
        if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_workflows"
    )
    matches = [
        node for node in registrar.body
        if isinstance(node, ast.FunctionDef)
        and node.decorator_list
        and isinstance(node.decorator_list[0], ast.Call)
        and node.decorator_list[0].args
        and getattr(node.decorator_list[0].args[0], "value", None) == ROUTE_PATH
    ]
    assert len(matches) == 1, f"expected one route for {ROUTE_PATH}, found {len(matches)}"
    return matches[0]


def run_source(nodes, filename, namespace):
    exec(compile(ast.Module(body=list(nodes), type_ignores=[]), str(filename), "exec"), namespace)
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


class Harness:
    """The real route, helpers and gates over the real assist core, with fake services."""

    def __init__(self):
        self.settings = {
            "allow_user_workflows": True,
            "enable_workflow_ai_assistant": True,
            "require_member_of_workflow_user": False,
            "azure_openai_gpt_key": SECRET,
        }
        self.session = {"user": {"roles": []}}
        self.logs = []
        self.built = []
        self.parsed = []
        self.runs = []
        self.factory_calls = []
        self.build_error = None
        self.stored = wa.stored_workflow()
        self.model = wa.ScriptedModel(RENAMED)
        self.limiter = wa.FakeLimiter()
        self.bundle = None

        gates = run_source(top_level_functions(SETTINGS_MODULE, GATE_FUNCTIONS), SETTINGS_MODULE, {
            "wraps": wraps, "request": request, "session": self.session, "jsonify": jsonify,
            "get_settings": lambda: self.settings,
            "WORKFLOW_USER_APP_ROLE": top_level_constant(SETTINGS_MODULE, "WORKFLOW_USER_APP_ROLE"),
        })
        app = Flask("workflow-assist-policy")
        run_source([*top_level_functions(ROUTES, ROUTE_HELPERS), route_function()], ROUTES, {
            "bp": Blueprint(app),
            "swagger_route": lambda **_security: unchanged,
            "get_auth_security": lambda: [{"bearerAuth": []}],
            "login_required": unchanged,
            "user_required": unchanged,
            "enabled_required": gates["enabled_required"],
            "workflow_user_required": gates["workflow_user_required"],
            "workflow_assistant_required": gates["workflow_assistant_required"],
            "request": request,
            "jsonify": jsonify,
            "logging": logging,
            "get_settings": lambda: self.settings,
            "get_current_user_id": lambda: wa.USER_ID,
            "log_event": self.log_event,
            "build_workflow_assist_services": self.build_services,
            "run_workflow_assist": self.run_workflow_assist,
            "WorkflowAssistError": core.WorkflowAssistError,
            "ASSIST_MAX_BODY_BYTES": core.ASSIST_MAX_BODY_BYTES,
            "parse_assist_body": self.parse_assist_body,
            "RequestEntityTooLarge": RequestEntityTooLarge,
            "BadRequest": BadRequest,
            "_resolve_agent_instruction_model": self.resolve_model,
            "_create_agent_instruction_client": self.create_client,
        })
        self.client = app.test_client()

    def log_event(self, message, extra=None, level=None, **_kwargs):
        self.logs.append((message, copy.deepcopy(extra), level))

    def parse_assist_body(self, raw):
        self.parsed.append(len(raw))
        return core.parse_assist_body(raw)

    def build_services(self, settings, *, client_factory):
        self.built.append((settings, client_factory))
        if self.build_error is not None:
            raise self.build_error
        self.bundle = wa.services(self.model, stored=self.stored, limiter=self.limiter)
        return self.bundle

    def run_workflow_assist(self, body, *, user_id, services):
        self.runs.append(user_id)
        return core.run_workflow_assist(body, user_id=user_id, services=services)

    def resolve_model(self, settings):
        self.factory_calls.append(("model", settings))
        return DRAFT_INSTRUCTIONS_MODEL

    def create_client(self, settings):
        self.factory_calls.append(("client", settings))
        return "draft-instructions-client"

    def post(self, body=None, **kwargs):
        if body is None:
            body = wa.request_body(stored=self.stored, instruction=f"Rename it to Nightly review. {SENTINEL}")
        if "data" not in kwargs:
            kwargs["data"] = json.dumps(body)
            kwargs.setdefault("content_type", "application/json")
        return self.client.post(ROUTE_PATH, **kwargs)

    def reached_nothing(self):
        """No service started: nothing was built, parsed into a request, limited or modelled."""
        return self.built == [] and self.runs == [] and self.limiter.events == [] and self.model.calls == []


@pytest.fixture
def harness():
    return Harness()


def response_text(response):
    return response.get_data(as_text=True)


def assert_closed_error(response, status, code):
    assert response.status_code == status
    assert response.headers["Cache-Control"] == "no-store, private"
    assert response.json["code"] == code
    assert response.json["error"]
    assert SENTINEL not in response_text(response) and SECRET not in response_text(response)


def test_the_route_keeps_its_blueprint_swagger_and_gate_order():
    assert_app_version_at_least("0.261.205")
    function = route_function()
    decorators = [ast.unparse(value) for value in function.decorator_list]

    assert function.name == "assist_user_workflow"
    assert decorators == [
        "bp.route('/api/user/workflows/assist', methods=['POST'])",
        "swagger_route(security=get_auth_security())",
        "login_required",
        "user_required",
        "enabled_required('allow_user_workflows')",
        "workflow_user_required",
        "workflow_assistant_required",
    ]


def test_an_available_assistant_answers_with_an_uncached_candidate(harness):
    response = harness.post()

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, private"
    assert "Retry-After" not in response.headers
    assert (response.json["outcome"], response.json["candidate"]["name"]) == ("changed", "Nightly review")
    assert response.json["submission_id"] == "submission-0001"
    assert SECRET not in response_text(response)
    # The core ran once, as the signed-in user, over the services built from the raw settings.
    assert harness.runs == [wa.USER_ID]
    [(settings, _factory)] = harness.built
    assert settings is harness.settings
    assert harness.bundle.recorder.named("read_base") == [(wa.USER_ID, wa.WORKFLOW_ID)]
    assert len(harness.model.calls) == 1


def test_the_model_client_is_the_draft_instructions_deployment(harness):
    harness.post()
    [(_settings, client_factory)] = harness.built

    client = client_factory()

    assert client == ("draft-instructions-client", DRAFT_INSTRUCTIONS_MODEL)
    assert [(kind, settings is harness.settings) for kind, settings in harness.factory_calls] == [
        ("model", True), ("client", True),
    ]


@pytest.mark.parametrize("value", [False, None, "true", 1, "missing"], ids=[
    "off", "null", "string true", "integer one", "missing",
])
def test_the_assistant_setting_gates_the_route_before_any_service(harness, value):
    if value == "missing":
        del harness.settings["enable_workflow_ai_assistant"]
    else:
        harness.settings["enable_workflow_ai_assistant"] = value

    response = harness.post()

    assert response.status_code == 403
    assert response.json == {
        "error": "The AI workflow assistant is not available.", "code": "workflow_assistant_disabled",
    }
    assert harness.reached_nothing() and harness.parsed == []


@pytest.mark.parametrize("assistant", [True, False], ids=["assistant on", "assistant off"])
def test_personal_workflows_off_is_refused_by_the_shared_gate_first(harness, assistant):
    harness.settings.update({"allow_user_workflows": False, "enable_workflow_ai_assistant": assistant})

    response = harness.post()

    # The shared personal-workflow gate answers first, with its existing 400.
    assert response.status_code == 400
    assert response.json == {"error": "Allow User Workflows is disabled."}
    assert harness.reached_nothing() and harness.parsed == []


@pytest.mark.parametrize(("roles", "status"), [
    ([], 403), (["Reader"], 403), (["WorkflowUser"], 200), (["workflowuser"], 200),
], ids=["no roles", "another role", "workflow user", "role case-insensitive"])
def test_the_workflow_user_role_is_required_when_admins_require_it(harness, roles, status):
    harness.settings["require_member_of_workflow_user"] = True
    harness.session["user"]["roles"] = roles

    response = harness.post()

    assert response.status_code == status
    if status == 403:
        assert response.json == {
            "error": "Forbidden", "message": "Personal workflows require the WorkflowUser app role.",
        }
        assert harness.reached_nothing()
    else:
        assert response.json["outcome"] == "changed"


def test_the_role_does_not_bypass_the_assistant_setting(harness):
    harness.settings.update({"require_member_of_workflow_user": True, "enable_workflow_ai_assistant": False})
    harness.session["user"]["roles"] = ["WorkflowUser"]

    response = harness.post()

    assert (response.status_code, response.json["code"]) == (403, "workflow_assistant_disabled")
    assert harness.reached_nothing()


@pytest.mark.parametrize(("data", "content_type"), [
    (b'{"instruction": "' + SENTINEL.encode() + b'"}', "text/plain"),
    (b'{"instruction": "' + SENTINEL.encode() + b'"', "application/json"),
    (b'{"instruction": NaN}', "application/json"),
    (b'{"instruction": "\xff\xfe"}', "application/json"),
    (b"", "application/json"),
], ids=["not json", "malformed", "nan", "invalid utf-8", "empty"])
def test_a_body_that_is_not_strict_json_is_refused_before_any_service(harness, data, content_type):
    response = harness.post(data=data, content_type=content_type)

    assert_closed_error(response, 400, "invalid_request")
    assert set(response.json) == {"error", "code"}
    assert harness.reached_nothing()
    assert harness.logs == [("[WorkflowAssist] Assist request refused", {
        "user_id": wa.USER_ID, "status": 400, "code": "invalid_request", "stage": "body",
    }, logging.INFO)]


@pytest.mark.parametrize("body", [[], "text", 7, None], ids=["array", "string", "number", "null"])
def test_json_that_is_not_an_object_is_refused_before_the_limit(harness, body):
    response = harness.post(data=json.dumps(body), content_type="application/json")

    assert_closed_error(response, 400, "invalid_request")
    assert harness.limiter.events == [] and harness.model.calls == []


def test_a_body_declared_over_the_bound_is_refused_unread(harness):
    oversized = b'{"instruction": "' + b"x" * core.ASSIST_MAX_BODY_BYTES + b'"}'

    response = harness.post(data=oversized, content_type="application/json")

    assert_closed_error(response, 413, "request_too_large")
    assert harness.parsed == [] and harness.reached_nothing()


def test_a_chunked_body_is_read_only_up_to_the_bound(harness):
    chunked = {"headers": {"Transfer-Encoding": "chunked"}, "environ_overrides": {"wsgi.input_terminated": True}}
    oversized = b'{"instruction": "' + b"x" * core.ASSIST_MAX_BODY_BYTES + b'"}'

    refused = harness.post(data=oversized, content_type="application/json", **chunked)

    assert_closed_error(refused, 413, "request_too_large")
    # Only the bound plus one byte was read, then refused.
    assert harness.parsed == [core.ASSIST_MAX_BODY_BYTES + 1] and harness.reached_nothing()

    body = wa.request_body(stored=harness.stored)
    answered = harness.post(data=json.dumps(body).encode(), content_type="application/json", **chunked)

    assert (answered.status_code, answered.json["outcome"]) == (200, "changed")


def stale_base(harness):
    harness.stored = wa.stored_workflow(definition_revision="rev-0002-newer")
    return wa.request_body(stored=wa.stored_workflow(), instruction=SENTINEL)


def missing_base(harness):
    return wa.request_body(stored=wa.stored_workflow(id="workflow-0009-missing"), instruction=SENTINEL)


def busy(harness):
    harness.limiter.acquire_error = core.WorkflowAssistError("assistant_busy", retry_after=1)
    return None


def rate_limited(harness):
    harness.limiter.acquire_error = core.WorkflowAssistError("assistant_rate_limited", retry_after=120)
    return None


def throttled(harness):
    harness.model = wa.ScriptedModel(core.WorkflowAssistError("assistant_unavailable", retry_after=10))
    return None


def invalid_output(harness):
    harness.model = wa.ScriptedModel(f"not json {SENTINEL}", f"still not json {SENTINEL}")
    return None


def group_draft(harness):
    draft = wa.new_draft(group_id="group-0004-stuvwx")
    return wa.request_body(draft, instruction=SENTINEL)


def long_instruction(harness):
    return wa.request_body(stored=harness.stored, instruction=SENTINEL * 100)


@pytest.mark.parametrize(("arrange", "status", "code", "retry_after"), [
    (stale_base, 409, "workflow_definition_conflict", None),
    (missing_base, 404, "workflow_not_found", None),
    (busy, 429, "assistant_busy", "1"),
    (rate_limited, 429, "assistant_rate_limited", "120"),
    (throttled, 503, "assistant_unavailable", "10"),
    (invalid_output, 502, "assistant_output_invalid", None),
    (group_draft, 400, "group_workflow_unsupported", None),
    (long_instruction, 400, "instruction_invalid", None),
], ids=["stale base", "missing base", "busy", "rate limited", "throttled", "invalid output", "group draft",
        "long instruction"])
def test_each_refusal_keeps_its_status_code_and_retry_after(harness, arrange, status, code, retry_after):
    body = arrange(harness)

    response = harness.post(body)

    assert_closed_error(response, status, code)
    assert response.headers.get("Retry-After") == retry_after
    if status == 429:
        assert response.json["rate_limited"] is True
        assert response.json["retry_after_seconds"] == int(retry_after)
    else:
        assert set(response.json) == {"error", "code"}
    # The core logged its content-free record through the services, not through the route.
    assert SENTINEL not in json.dumps(harness.bundle.logs, default=str)
    assert harness.logs == []


def test_services_that_cannot_start_fail_without_detail(harness):
    harness.build_error = RuntimeError(f"cannot connect {SENTINEL} {SECRET}")

    response = harness.post()

    assert_closed_error(response, 500, "assistant_failed")
    assert set(response.json) == {"error", "code"}
    assert harness.runs == [] and harness.limiter.events == []
    assert harness.logs == [("[WorkflowAssist] Assist services could not start", {
        "user_id": wa.USER_ID, "error_type": "RuntimeError",
    }, logging.ERROR)]


def test_the_route_logs_no_request_content_or_settings(harness):
    harness.post()
    harness.post(data=b'{"instruction": "' + SENTINEL.encode() + b'"', content_type="application/json")

    logged = json.dumps([harness.logs, harness.bundle.logs], default=str)
    assert SENTINEL not in logged and SECRET not in logged and "Nightly review" not in logged


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-q"]))
