# test_user_search_hardening.py
"""
Functional test for the /api/userSearch hardening.
Version: 0.261.150
Implemented in: 0.261.150

``/api/userSearch`` backs the classic and V2 people pickers, including the group
member add. This test runs the real route function against a fake Graph and pins:

- the success shape is unchanged: a bare array of ``{id, displayName, email}``,
  with the ``(no name)`` and ``userPrincipalName`` fallbacks, and the same Graph
  request, now bounded by a timeout;
- a Graph error keeps Graph's status and ``error``, and no longer returns Graph's
  body as ``details``;
- a timeout is a data-free 504, and a transport failure or an unreadable Graph
  answer a data-free 502;
- a failure is logged through ``log_event`` with the Graph status only, never
  Graph's body or the exception text, and nothing is printed.
"""

import ast
import json
import logging
import types
from pathlib import Path

import pytest
import requests
from flask import Flask, jsonify, request


USERS_ROUTE = Path(__file__).resolve().parents[1] / "application" / "single_app" / "route_backend_users.py"
GRAPH_USERS = "https://graph.example.test/v1.0/users"
SECRET = "tenant-7f3c-secret-detail"
FAILED = {"error": "Graph API request failed"}
TIMED_OUT = {"error": "Graph API request timed out"}


def _route_source():
    return USERS_ROUTE.read_text(encoding="utf-8")


def _route_function(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "api_user_search":
            return node
    raise AssertionError("api_user_search not found")


def _load_route(namespace):
    """The real ``api_user_search`` and the module values it reads, without its decorators."""
    tree = ast.parse(_route_source())
    wanted = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_escape_graph_odata_literal":
            wanted.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id.startswith("USER_SEARCH_") for target in node.targets
        ):
            wanted.append(node)
    route = _route_function(tree)
    route.decorator_list = []
    module = ast.Module(body=[*wanted, route], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(USERS_ROUTE), "exec"), namespace)
    return namespace["api_user_search"]


def graph_response(status, body, content_type="application/json"):
    response = requests.models.Response()
    response.status_code = status
    response._content = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    response.headers["Content-Type"] = content_type
    response.url = GRAPH_USERS
    return response


class FakeGraph:
    def __init__(self):
        self.calls = []
        self.answer = graph_response(200, {"value": []})

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


class Environment:
    def __init__(self):
        self.graph = FakeGraph()
        self.token = "delegated-token"
        self.logs = []
        self.printed = []
        namespace = {
            "request": request,
            "jsonify": jsonify,
            "logging": logging,
            "requests": types.SimpleNamespace(get=self.graph.get, exceptions=requests.exceptions),
            "get_valid_access_token": lambda: self.token,
            "get_graph_endpoint": lambda path: "https://graph.example.test/v1.0" + path,
            "log_event": lambda message, extra=None, level=logging.INFO, **kwargs: self.logs.append(
                (message, extra, level, kwargs),
            ),
            "print": lambda *args, **kwargs: self.printed.append(args),
        }
        self.route = _load_route(namespace)
        self.namespace = namespace
        self.app = Flask(__name__)
        self.app.add_url_rule("/api/userSearch", "api_user_search", self.route)
        self.client = self.app.test_client()

    def search(self, query="ada"):
        response = self.client.get("/api/userSearch", query_string={"query": query})
        return response.status_code, response.get_json(), response.get_data(as_text=True)


@pytest.fixture
def env():
    return Environment()


def test_the_success_shape_is_unchanged(env):
    env.graph.answer = graph_response(200, {"value": [
        {"id": "u-1", "displayName": "Ada Lovelace", "mail": "ada@example.test", "userPrincipalName": "ada@corp.test"},
        {"id": "u-2", "mail": "nameless@example.test"},
        {"id": "u-3", "displayName": "Upn Only", "mail": None, "userPrincipalName": "upn.only@corp.test"},
        {"id": "u-4", "displayName": "No Address"},
    ]})
    status, body, _text = env.search("ada")
    assert status == 200
    assert body == [
        {"id": "u-1", "displayName": "Ada Lovelace", "email": "ada@example.test"},
        {"id": "u-2", "displayName": "(no name)", "email": "nameless@example.test"},
        {"id": "u-3", "displayName": "Upn Only", "email": "upn.only@corp.test"},
        {"id": "u-4", "displayName": "No Address", "email": ""},
    ]
    assert env.logs == [] and env.printed == []


def test_the_graph_request_is_unchanged_and_bounded(env):
    env.search("o'hare")
    [(url, kwargs)] = env.graph.calls
    assert url == GRAPH_USERS
    assert kwargs["headers"] == {"Authorization": "Bearer delegated-token", "Content-Type": "application/json"}
    assert kwargs["params"] == {
        "$filter": (
            "startswith(displayName, 'o''hare') or startswith(mail, 'o''hare') "
            "or startswith(userPrincipalName, 'o''hare')"
        ),
        "$top": 10,
        "$select": "id,displayName,mail,userPrincipalName",
    }
    assert kwargs["timeout"] == env.namespace["USER_SEARCH_GRAPH_TIMEOUT_SECONDS"] == 20


def test_an_empty_query_answers_an_empty_list_without_graph(env):
    assert env.search("   ")[:2] == (200, [])
    assert env.graph.calls == []


def test_a_missing_token_is_the_classic_401(env):
    env.token = None
    assert env.search()[:2] == (401, {"error": "Could not acquire access token"})
    assert env.graph.calls == []


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
@pytest.mark.parametrize("body,content_type", [
    ({"error": {"code": "Authorization_RequestDenied", "message": f"Insufficient privileges for {SECRET}"}},
     "application/json"),
    (f"<html>{SECRET}</html>".encode("utf-8"), "text/html"),
])
def test_a_graph_error_keeps_its_status_and_drops_the_details(env, status, body, content_type):
    env.graph.answer = graph_response(status, body, content_type)
    answered, payload, text = env.search()
    assert (answered, payload) == (status, FAILED)
    assert SECRET not in text and "details" not in text
    assert env.logs == [("[USERS] Graph user search failed", {"status_code": status}, logging.WARNING, {})]
    assert env.printed == []


@pytest.mark.parametrize("error", [
    requests.exceptions.ReadTimeout(f"read timed out {SECRET}"),
    requests.exceptions.ConnectTimeout(f"connect timed out {SECRET}"),
    requests.exceptions.Timeout(SECRET),
])
def test_a_timeout_is_a_data_free_504(env, error):
    env.graph.answer = error
    answered, payload, text = env.search()
    assert (answered, payload) == (504, TIMED_OUT)
    assert SECRET not in text
    assert env.logs == [("[USERS] Graph user search timed out", {"status_code": None}, logging.WARNING, {})]
    assert env.printed == []


@pytest.mark.parametrize("answer", [
    requests.exceptions.ConnectionError(f"connection refused {SECRET}"),
    requests.exceptions.RequestException(SECRET),
    graph_response(200, f"<html>{SECRET}</html>".encode("utf-8"), "text/html"),
])
def test_a_transport_failure_or_an_unreadable_answer_is_a_data_free_502(env, answer):
    env.graph.answer = answer
    answered, payload, text = env.search()
    assert (answered, payload) == (502, FAILED)
    assert SECRET not in text
    assert env.logs == [("[USERS] Graph user search failed", {"status_code": None}, logging.WARNING, {})]
    assert env.printed == []


def test_a_graph_error_without_an_error_status_is_a_bad_gateway(env):
    """A request error that carries a non-error response never answers as a success."""
    env.graph.answer = requests.exceptions.RequestException(SECRET, response=graph_response(200, {"value": []}))
    assert env.search()[:2] == (502, FAILED)
    assert env.logs == [("[USERS] Graph user search failed", {"status_code": 200}, logging.WARNING, {})]


def test_the_route_prints_nothing_returns_no_details_and_keeps_its_decorators():
    route = _route_function(ast.parse(_route_source()))
    calls = [node for node in ast.walk(route) if isinstance(node, ast.Call)]
    assert not [call for call in calls if isinstance(call.func, ast.Name) and call.func.id == "print"]
    assert not [
        node for node in ast.walk(route)
        if isinstance(node, ast.Constant) and node.value == "details"
    ]
    [graph_get] = [
        call for call in calls
        if isinstance(call.func, ast.Attribute) and call.func.attr == "get"
        and isinstance(call.func.value, ast.Name) and call.func.value.id == "requests"
    ]
    assert [keyword.arg for keyword in graph_get.keywords] == ["headers", "params", "timeout"]
    assert [ast.unparse(decorator) for decorator in route.decorator_list] == [
        "bp.route('/api/userSearch', methods=['GET'])",
        "swagger_route(security=get_auth_security())",
        "login_required",
        "user_required",
    ]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
