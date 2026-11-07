#!/usr/bin/env python3
# test_workflow_result_context_policy.py
"""
Functional policy tests for the workflow result descriptor route.
Version: 0.261.214
Implemented in: 0.261.214

This test ensures that ``GET /api/user/workflows/<workflow_id>/runs/<run_id>/result-context``
keeps its Blueprint, Swagger and gate order, that each gate refuses before anything is read,
that only the run's owner gets the public descriptor, that someone else's run answers exactly
like a missing one, that every closed reason keeps its status and fixed wording without echoing
exception text, and that no cache may answer for the route.

The real route body and the real gate decorators from ``functions_settings.py`` run on a closed
Flask app over the real reader. The containers, the result store and the source resolver are
fakes; no live application, credential or Azure service is used.
"""

import ast
import sys
from functools import wraps
from pathlib import Path

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "functional_tests"))

import functions_workflow_result_reader as reader  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_support.workflow_result_chat import (  # noqa: E402
    OTHER_USER,
    RUN_ID,
    USER,
    WORKFLOW_ID,
    RunFixture,
    two_text_tasks,
)


ROUTES = APP / "route_backend_workflows.py"
SETTINGS_MODULE = APP / "functions_settings.py"
ROUTE_PATH = "/api/user/workflows/<workflow_id>/runs/<run_id>/result-context"
GATE_FUNCTIONS = (
    "normalize_app_role_claims", "has_workflow_user_app_role", "is_user_workflows_enabled_for_user",
    "is_chat_workflow_results_enabled_for_user", "_is_api_request", "workflow_user_required",
    "workflow_results_required", "enabled_required",
)
SENTINEL = "SENTINEL-STORAGE-DETAIL-4c1e"
PUBLIC_KEYS = {
    "version", "workflow_id", "run_id", "workflow_name", "status", "completed_at", "result_sha256", "available",
}


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
    """The real route and gates over the real reader, with fake storage."""

    def __init__(self):
        self.settings = {
            "allow_user_workflows": True,
            "enable_chat_workflow_results": True,
            "require_member_of_workflow_user": False,
        }
        self.session = {"user": {"roles": []}}
        self.user_id = USER
        self.fixture = RunFixture()
        two_text_tasks(self.fixture)
        self.fixture.reset_counters()
        self.calls = []
        self.raise_code = None

        gates = run_source(top_level_functions(SETTINGS_MODULE, GATE_FUNCTIONS), SETTINGS_MODULE, {
            "wraps": wraps, "request": request, "session": self.session, "jsonify": jsonify,
            "get_settings": lambda: self.settings,
            "WORKFLOW_USER_APP_ROLE": top_level_constant(SETTINGS_MODULE, "WORKFLOW_USER_APP_ROLE"),
        })
        app = Flask("workflow-result-context-policy")
        run_source([route_function()], ROUTES, {
            "bp": Blueprint(app),
            "swagger_route": lambda **_security: unchanged,
            "get_auth_security": lambda: [{"bearerAuth": []}],
            "login_required": unchanged,
            "user_required": unchanged,
            "enabled_required": gates["enabled_required"],
            "workflow_user_required": gates["workflow_user_required"],
            "workflow_results_required": gates["workflow_results_required"],
            "jsonify": jsonify,
            "get_current_user_id": lambda: self.user_id,
            "read_workflow_result": self.read_workflow_result,
            "WorkflowResultUnavailable": reader.WorkflowResultUnavailable,
            "workflow_result_error_payload": reader.workflow_result_error_payload,
        })
        self.client = app.test_client()

    def read_workflow_result(self, user_id, workflow_id, run_id, **options):
        self.calls.append((user_id, workflow_id, run_id, dict(options)))
        if self.raise_code is not None:
            raise reader.WorkflowResultUnavailable(self.raise_code)
        return self.fixture.read(user_id, workflow_id, run_id, **options)

    def get(self, workflow_id=WORKFLOW_ID, run_id=RUN_ID):
        return self.client.get(f"/api/user/workflows/{workflow_id}/runs/{run_id}/result-context")

    def read_nothing(self):
        containers = self.fixture.containers
        return (
            self.calls == []
            and all(not container.reads and not container.queries for container in containers.values())
            and self.fixture.store.loads == [] and self.fixture.store.pages == []
        )


@pytest.fixture
def harness():
    return Harness()


def assert_closed(response, status, code):
    assert response.status_code == status
    assert response.headers["Cache-Control"] == "no-store, private"
    assert response.json == {"error": reader._REASONS[code][1], "code": code}


def test_version_is_at_least_the_workflow_results_release():
    assert_app_version_at_least("0.261.214")


def test_the_route_keeps_its_blueprint_swagger_and_gate_order():
    function = route_function()
    decorators = [ast.unparse(value) for value in function.decorator_list]

    assert function.name == "get_user_workflow_run_result_context"
    assert decorators == [
        f"bp.route('{ROUTE_PATH}', methods=['GET'])",
        "swagger_route(security=get_auth_security())",
        "login_required",
        "user_required",
        "enabled_required('allow_user_workflows')",
        "workflow_user_required",
        "workflow_results_required",
    ]


def test_the_route_module_binds_the_real_reader_and_gate():
    """The names the harness injects are the ones the route module really imports."""
    imports = {}
    for node in parsed_module(ROUTES).body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports.setdefault(alias.asname or alias.name, node.module)

    assert imports["read_workflow_result"] == "functions_workflow_result_reader"
    assert imports["workflow_result_error_payload"] == "functions_workflow_result_reader"
    assert imports["WorkflowResultUnavailable"] == "functions_workflow_result_reader"
    assert imports["workflow_results_required"] == "functions_settings"


def test_the_owner_gets_only_the_public_descriptor_uncached(harness):
    response = harness.get()

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, private"
    assert set(response.json) == {"workflow_result"}
    descriptor = response.json["workflow_result"]
    assert set(descriptor) == PUBLIC_KEYS
    assert (descriptor["workflow_id"], descriptor["run_id"], descriptor["available"]) == (WORKFLOW_ID, RUN_ID, True)
    assert descriptor["workflow_name"] == "Weekly digest"
    # The reader ran once as the signed-in user, asking for no excerpts.
    assert [(user, workflow, run) for user, workflow, run, _ in harness.calls] == [(USER, WORKFLOW_ID, RUN_ID)]
    assert harness.calls[0][3] == {}
    # No result content was read and no store reference or preview reached the browser.
    assert harness.fixture.store.pages == []
    body = response.get_data(as_text=True)
    stored_digests = {item["workflow_result"]["result_ref"]["sha256"] for item in harness.fixture.items}
    assert len(stored_digests) == 2 and all(digest not in body for digest in stored_digests)
    for leaked in ("result_ref", "ITEM-PREVIEW-TEXT", "RUN-PREVIEW-TEXT", "markets rose", "Collect news"):
        assert leaked not in body


@pytest.mark.parametrize("value", [False, None, "true", 1, "missing"], ids=[
    "off", "null", "string true", "integer one", "missing",
])
def test_the_setting_gates_the_route_before_anything_is_read(harness, value):
    if value == "missing":
        del harness.settings["enable_chat_workflow_results"]
    else:
        harness.settings["enable_chat_workflow_results"] = value

    response = harness.get()

    assert response.status_code == 403
    assert response.json == {
        "error": "Workflow results in chat are not available.", "code": "workflow_results_disabled",
    }
    assert harness.read_nothing()


def test_personal_workflows_off_is_refused_by_the_shared_gate_first(harness):
    harness.settings["allow_user_workflows"] = False

    response = harness.get()

    assert response.status_code == 400
    assert response.json == {"error": "Allow User Workflows is disabled."}
    assert harness.read_nothing()


@pytest.mark.parametrize(("roles", "status"), [
    ([], 403), (["Reader"], 403), (["WorkflowUser"], 200), (["workflowuser"], 200),
], ids=["no roles", "another role", "workflow user", "role case-insensitive"])
def test_the_workflow_user_role_is_required_when_the_admin_requires_it(harness, roles, status):
    harness.settings["require_member_of_workflow_user"] = True
    harness.session["user"]["roles"] = roles

    response = harness.get()

    assert response.status_code == status
    if status == 403:
        assert harness.read_nothing()


def test_someone_elses_run_answers_exactly_like_a_missing_one(harness):
    missing = harness.get(run_id="run-that-does-not-exist")
    harness.user_id = OTHER_USER
    foreign = harness.get()

    assert_closed(missing, 404, "workflow_result_not_found")
    assert_closed(foreign, 404, "workflow_result_not_found")
    assert foreign.get_data() == missing.get_data()
    # The other user's reads stayed in their own partition.
    assert ("wf-digest-3c1", OTHER_USER) in harness.fixture.containers["workflows"].reads


def test_a_run_of_another_workflow_answers_like_a_missing_run(harness):
    harness.fixture.containers["workflows"].documents.append(
        {"id": "wf-other-5d2", "user_id": USER, "name": "Other workflow"},
    )

    response = harness.get(workflow_id="wf-other-5d2")

    assert_closed(response, 404, "workflow_result_not_found")


def test_a_run_still_in_progress_is_a_conflict(harness):
    harness.fixture.run["status"] = "running"

    assert_closed(harness.get(), 409, "workflow_result_in_progress")


@pytest.mark.parametrize("code", sorted(reader._REASONS))
def test_every_closed_reason_keeps_its_status_and_fixed_wording(harness, code):
    harness.raise_code = code

    response = harness.get()

    assert_closed(response, reader._REASONS[code][0], code)


def test_storage_failures_answer_503_without_echoing_the_error(harness):
    harness.fixture.containers["runs"].read_error = CosmosHttpResponseError(status_code=503, message=SENTINEL)

    response = harness.get()

    assert_closed(response, 503, "workflow_result_storage_unavailable")
    assert SENTINEL not in response.get_data(as_text=True)


def test_a_request_without_a_signed_in_user_is_refused_before_any_read(harness):
    harness.user_id = None

    response = harness.get()

    assert response.status_code == 401
    assert response.json == {"error": "User not authenticated."}
    assert harness.read_nothing()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
