# test_v2_control_center_activity_logs_routes.py
"""
Functional tests for the Activity Logs HTTP and capability contracts.
Version: 0.261.294
Implemented in: 0.261.284

Registers the actual new handlers with real authentication/capability decorators,
isolating unrelated Azure bootstrap. Checks authorization before query execution.
Since 0.261.294 the page returns readable presentation and names for its filters, search
also matches people, and two lookups back the person and workspace filters.
"""

import ast
import csv
import importlib.util
import logging
from functools import wraps
from importlib.metadata import version
from io import StringIO
from pathlib import Path

import pytest
import werkzeug
from flask import Blueprint, Flask, Response, jsonify, request, session, stream_with_context

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, APP / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


activity = _load("activity_route_queries", "functions_control_center_activity.py")
display = _load("activity_route_display", "functions_control_center_activity_display.py")
PATHS = ("/api/v2/control-center/activity-logs", "/api/v2/control-center/activity-logs/summary",
         "/api/v2/control-center/activity-logs/export.csv")
LOOKUP_PATHS = ("/api/v2/control-center/activity-logs/people?q=ada",
                "/api/v2/control-center/activity-logs/workspaces?q=res")
HANDLERS = {"api_v2_control_center_activity_logs", "api_v2_control_center_activity_summary",
            "api_v2_control_center_activity_export", "api_v2_control_center_activity_people",
            "api_v2_control_center_activity_workspaces"}
HELPERS = {"_activity_search_people", "_activity_names", "_activity_export_columns"}
RECORD = {"id": "r1", "timestamp": "2026-10-01T12:00:00", "user_id": "u1", "activity_type": "token_usage",
          "token_type": "chat", "usage": {"total_tokens": 120, "model": "gpt-4o"}, "workspace_type": "group",
          "workspace_context": {"group_id": "g1"}}


class Container:
    def __init__(self, queries, rows=(), name="activity"):
        self.queries = queries
        self.rows = list(rows)
        self.name = name
        self.failure = False

    def query_items(self, **kwargs):
        self.queries.append((self.name, kwargs))
        if self.failure:
            raise RuntimeError("SECRET connection provider error")
        query = kwargs["query"]
        if "ARRAY_CONTAINS(@ids, c.id)" in query:
            ids = next(item["value"] for item in kwargs["parameters"] if item["name"] == "@ids")
            return [row for row in self.rows if row["id"] in ids]
        if "@term" in query:
            return list(self.rows)
        return [dict(row) for row in self.rows]


@pytest.fixture
def environment(monkeypatch):
    if not hasattr(werkzeug, "__version__"):
        monkeypatch.setattr(werkzeug, "__version__", version("werkzeug"), raising=False)
    app = Flask(__name__)
    app.secret_key = "local-test-only"
    queries = []
    logs = []
    settings = {"require_member_of_control_center_admin": True, "require_member_of_control_center_dashboard_reader": True}
    auth = {"wraps": wraps, "session": session, "request": request, "jsonify": jsonify,
            "get_settings": lambda: settings, "debug_print": lambda *args, **kwargs: None}
    auth_tree = ast.parse((APP / "functions_authentication.py").read_text(encoding="utf-8"))
    functions = [node for node in auth_tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"login_required", "control_center_required", "get_control_center_capabilities"}]
    exec(compile(ast.Module(body=functions, type_ignores=[]), "authentication", "exec"), auth)

    containers = {
        "activity": Container(queries),
        "users": Container(queries, [{"id": "u1", "display_name": "Ada Admin", "email": "ada@example.test"}], "users"),
        "groups": Container(queries, [{"id": "g1", "name": "Research"}], "groups"),
        "public": Container(queries, [{"id": "p1", "name": "Library"}], "public"),
    }
    bp = Blueprint("backend_control_center", __name__)
    namespace = {**vars(activity), **vars(display), **auth, "bp": bp,
                 "cosmos_activity_logs_container": containers["activity"],
                 "cosmos_user_settings_container": containers["users"],
                 "cosmos_groups_container": containers["groups"],
                 "cosmos_public_workspaces_container": containers["public"],
                 "_control_center_activity_name_cache": display.ActivityNameCache(),
                 "swagger_route": lambda **kwargs: lambda function: function,
                 "get_auth_security": lambda: [], "Response": Response, "stream_with_context": stream_with_context,
                 "log_event": lambda *args, **kwargs: logs.append((args, kwargs)), "logging": logging}
    tree = ast.parse((APP / "route_backend_control_center.py").read_text(encoding="utf-8"))
    helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in HELPERS]
    assert {node.name for node in helpers} == HELPERS
    registrar = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_control_center")
    handlers = [node for node in registrar.body if isinstance(node, ast.FunctionDef) and node.name in HANDLERS]
    assert {node.name for node in handlers} == HANDLERS
    for handler in handlers:
        decorators = [ast.unparse(item) for item in handler.decorator_list]
        assert decorators[1] == "swagger_route(security=get_auth_security())"
        assert decorators[2] == "login_required"
        assert "control_center_required('activity_logs')" in decorators
    exec(compile(ast.Module(body=helpers + handlers, type_ignores=[]), "activity-routes", "exec"), namespace)
    app.register_blueprint(bp)
    yield app.test_client(), containers, queries, logs, settings


def login(client, roles):
    with client.session_transaction() as current:
        current["user"] = {"oid": "viewer", "roles": roles}


@pytest.mark.parametrize("roles", [None, ["User"], ["Admin"], ["ControlCenterDashboardReader"]])
def test_denied_roles_and_anonymous_never_query(environment, roles):
    client, _, queries, _, _ = environment
    if roles is not None:
        login(client, roles)
    for path in PATHS + LOOKUP_PATHS:
        response = client.get(path)
        assert response.status_code in (401, 302) if roles is None else response.status_code == 403
    assert not queries


def test_control_center_admin_and_regular_admin_settings(environment):
    client, _, queries, _, settings = environment
    login(client, ["ControlCenterAdmin"])
    for path in PATHS:
        response = client.get(path)
        assert response.status_code == 200
    assert [name for name, _ in queries] == ["activity", "activity", "activity"]
    settings["require_member_of_control_center_admin"] = False
    login(client, ["Admin"])
    response = client.get(PATHS[0])
    assert response.status_code == 200


def test_invalid_cursor_filters_and_page_size_return_400(environment):
    client, _, queries, _, _ = environment
    login(client, ["ControlCenterAdmin"])
    for suffix in ("?cursor=garbage", "?page_size=201", "?page_size=abc", "?start_date=invalid"):
        response = client.get(PATHS[0] + suffix)
        assert response.status_code == 400
    for path in LOOKUP_PATHS:
        response = client.get(path.split("?")[0] + "?q=" + "x" * 201)
        assert response.status_code == 400
    assert [name for name, _ in queries if name == "activity"] == []


def test_storage_failures_are_logged_without_provider_details(environment):
    client, containers, _, logs, _ = environment
    for container in containers.values():
        container.failure = True
    login(client, ["ControlCenterAdmin"])
    for path in PATHS + LOOKUP_PATHS:
        response = client.get(path)
        assert response.status_code == 500
        assert "SECRET" not in response.get_data(as_text=True)
    assert len(logs) == 5
    assert all(kwargs.get("level") == logging.ERROR for _, kwargs in logs)


def test_page_presents_names_labels_and_filter_names(environment):
    client, containers, queries, _, _ = environment
    containers["activity"].rows = [RECORD]
    login(client, ["ControlCenterAdmin"])
    response = client.get(PATHS[0] + "?user_id=u1&workspace_type=group&workspace_id=g1")
    data = response.get_json()
    assert response.status_code == 200
    assert data["items"] == [RECORD]
    view = data["presentation"][0]
    assert view["label"] == "Token usage" and view["summary"] == "120 tokens · gpt-4o"
    assert view["actor"] == {"id": "u1", "name": "Ada Admin", "email": "ada@example.test", "kind": "user", "resolved": True}
    assert view["workspace"] == {"type": "group", "id": "g1", "name": "Research", "resolved": True}
    assert data["filter_labels"]["person"]["name"] == "Ada Admin"
    assert data["filter_labels"]["workspace"]["name"] == "Research"
    assert data["search_people"] == {"matched": 0, "truncated": False}
    assert [name for name, _ in queries].count("users") == 1


def test_search_widens_to_matching_people_and_degrades_safely(environment):
    client, containers, queries, logs, _ = environment
    login(client, ["ControlCenterAdmin"])
    response = client.get(PATHS[0] + "?search=ada")
    assert response.get_json()["search_people"] == {"matched": 1, "truncated": False}
    activity_query = [kwargs for name, kwargs in queries if name == "activity"][-1]
    assert {"name": "@search_people", "value": ["u1"]} in activity_query["parameters"]
    lookups = [name for name, _ in queries].count("users")
    client.get(PATHS[1] + "?search=ADA")
    assert [name for name, _ in queries].count("users") == lookups, "The summary should reuse the page's people match."
    containers["users"].failure = True
    response = client.get(PATHS[0] + "?search=adam")
    assert response.status_code == 200 and response.get_json()["search_people"]["matched"] == 0
    assert any(kwargs.get("level") == logging.WARNING for _, kwargs in logs)


def test_name_lookup_failure_still_returns_the_page(environment):
    client, containers, _, logs, _ = environment
    containers["activity"].rows = [RECORD]
    containers["groups"].failure = True
    login(client, ["ControlCenterAdmin"])
    response = client.get(PATHS[0])
    data = response.get_json()
    assert response.status_code == 200
    assert data["presentation"][0]["actor"]["resolved"] is False
    assert data["presentation"][0]["workspace"]["id"] == "g1"
    assert "SECRET" not in response.get_data(as_text=True)
    assert any(kwargs.get("level") == logging.WARNING for _, kwargs in logs)


def test_summary_labels_facets_and_lists_the_type_catalog(environment):
    client, containers, _, _, _ = environment
    containers["activity"].rows = [RECORD]
    login(client, ["ControlCenterAdmin"])
    data = client.get(PATHS[1]).get_json()
    assert data["facets"] == [{"activity_type": "token_usage", "count": 1, "label": "Token usage", "category": "tokens"}]
    assert {"activity_type": "user_login", "label": "User login", "category": "sign_in",
            "category_label": "Sign-in and consent"} in data["type_catalog"]


def test_lookups_return_people_and_workspaces(environment):
    client, _, queries, _, _ = environment
    login(client, ["ControlCenterAdmin"])
    people = client.get(LOOKUP_PATHS[0]).get_json()
    assert people == {"people": [{"id": "u1", "display_name": "Ada Admin", "email": "ada@example.test"}]}
    workspaces = client.get(LOOKUP_PATHS[1]).get_json()
    assert workspaces == {"workspaces": [{"type": "group", "id": "g1", "name": "Research"},
                                         {"type": "public", "id": "p1", "name": "Library"}]}
    queries.clear()
    assert client.get("/api/v2/control-center/activity-logs/people?q=a").get_json() == {"people": []}
    assert not queries


def test_csv_response_is_attachment_uncached_bounded_and_readable(environment):
    client, containers, _, _, _ = environment
    containers["activity"].rows = [RECORD]
    login(client, ["ControlCenterAdmin"])
    response = client.get(PATHS[2] + "?date=2026-10-01")
    assert response.headers["X-Export-Row-Limit"] == "10000"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Content-Disposition"] == 'attachment; filename="activity_logs.csv"'
    rows = list(csv.reader(StringIO(response.get_data(as_text=True))))
    assert rows[0] == list(activity.ACTIVITY_EXPORT_HEADER)
    exported = dict(zip(rows[0], rows[1]))
    assert exported["user_name"] == "Ada Admin" and exported["workspace_name"] == "Research"
    assert exported["activity"] == "Token usage" and exported["user_id"] == "u1"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
