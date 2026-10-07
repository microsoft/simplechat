# test_v2_control_center_activity_logs_routes.py
"""
Functional tests for the Activity Logs HTTP and capability contracts.
Version: 0.261.285
Implemented in: 0.261.284

Registers the actual new handlers with real authentication/capability decorators,
isolating unrelated Azure bootstrap. Checks authorization before query execution.
"""

import ast
import importlib.util
import logging
from functools import wraps
from importlib.metadata import version
from pathlib import Path

import pytest
import werkzeug
from flask import Blueprint, Flask, Response, jsonify, request, session, stream_with_context

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
SPEC = importlib.util.spec_from_file_location("activity_route_queries", APP / "functions_control_center_activity.py")
activity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(activity)
PATHS = ("/api/v2/control-center/activity-logs", "/api/v2/control-center/activity-logs/summary",
         "/api/v2/control-center/activity-logs/export.csv")
HANDLERS = {"api_v2_control_center_activity_logs", "api_v2_control_center_activity_summary",
            "api_v2_control_center_activity_export"}


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

    class Container:
        failure = False

        def query_items(self, **kwargs):
            queries.append(kwargs)
            if self.failure:
                raise RuntimeError("SECRET connection provider error")
            return []

    container = Container()
    bp = Blueprint("backend_control_center", __name__)
    namespace = {**vars(activity), **auth, "bp": bp, "cosmos_activity_logs_container": container,
                 "swagger_route": lambda **kwargs: lambda function: function,
                 "get_auth_security": lambda: [], "Response": Response, "stream_with_context": stream_with_context,
                 "log_event": lambda *args, **kwargs: logs.append((args, kwargs)), "logging": logging}
    tree = ast.parse((APP / "route_backend_control_center.py").read_text(encoding="utf-8"))
    registrar = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_control_center")
    handlers = [node for node in registrar.body if isinstance(node, ast.FunctionDef) and node.name in HANDLERS]
    assert len(handlers) == 3
    for handler in handlers:
        decorators = [ast.unparse(item) for item in handler.decorator_list]
        assert decorators[1] == "swagger_route(security=get_auth_security())"
        assert "control_center_required('activity_logs')" in decorators
    exec(compile(ast.Module(body=handlers, type_ignores=[]), "activity-routes", "exec"), namespace)
    app.register_blueprint(bp)
    yield app.test_client(), container, queries, logs, settings


def login(client, roles):
    with client.session_transaction() as current:
        current["user"] = {"oid": "viewer", "roles": roles}


@pytest.mark.parametrize("roles", [None, ["User"], ["Admin"], ["ControlCenterDashboardReader"]])
def test_denied_roles_and_anonymous_never_query(environment, roles):
    client, _, queries, _, _ = environment
    if roles is not None:
        login(client, roles)
    for path in PATHS:
        response = client.get(path)
        assert response.status_code in (401, 302) if roles is None else response.status_code == 403
    assert not queries


def test_control_center_admin_and_regular_admin_settings(environment):
    client, _, queries, _, settings = environment
    login(client, ["ControlCenterAdmin"])
    for path in PATHS:
        response = client.get(path)
        assert response.status_code == 200
    assert len(queries) == 3
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
    assert not queries


def test_storage_failures_are_logged_without_provider_details(environment):
    client, container, _, logs, _ = environment
    container.failure = True
    login(client, ["ControlCenterAdmin"])
    for path in PATHS:
        response = client.get(path)
        assert response.status_code == 500
        assert "SECRET" not in response.get_data(as_text=True)
    assert len(logs) == 3


def test_csv_response_is_attachment_uncached_and_bounded(environment):
    client, _, _, _, _ = environment
    login(client, ["ControlCenterAdmin"])
    response = client.get(PATHS[2] + "?date=2026-10-01")
    assert response.headers["X-Export-Row-Limit"] == "10000"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Content-Disposition"] == 'attachment; filename="activity_logs.csv"'
    assert response.get_data(as_text=True).startswith("timestamp,id,user_id,activity_type,workspace_type,raw_json")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
