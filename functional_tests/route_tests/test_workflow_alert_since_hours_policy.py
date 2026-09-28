# test_workflow_alert_since_hours_policy.py
"""
Functional policy tests for the workflow alert pop-up route's since_hours window.
Version: 0.261.199
Implemented in: 0.261.199

The real route body runs on a closed Flask app with the real since_hours parser and a
recording reader. No live application, permissions, credentials or services are used.
"""

import ast
import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import Mock, patch

import pytest
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "functional_tests"))

# Shared test helpers follow the isolated worktree import setup.
from test_support.versioning import assert_app_version_at_least


ROUTES = APP / "route_backend_notifications.py"
ROUTE_PATH = "/api/notifications/workflow-alerts"


def route_function():
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    registrar = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_notifications"
    )
    return next(
        node for node in registrar.body
        if isinstance(node, ast.FunctionDef)
        and node.decorator_list
        and isinstance(node.decorator_list[0], ast.Call)
        and node.decorator_list[0].args
        and getattr(node.decorator_list[0].args[0], "value", None) == ROUTE_PATH
    )


def load_since_hours_parser():
    """Load the real parser from functions_notifications.py with storage stubbed out."""
    replacements = {}
    for name, values in {
        "config": {"cosmos_notifications_container": types.SimpleNamespace(query_items=Mock())},
        "functions_appinsights": {"log_event": Mock()},
        "functions_debug": {"debug_print": Mock()},
        "functions_group": {"find_group_by_id": Mock(), "get_user_groups": lambda user: []},
        "functions_public_workspaces": {
            "find_public_workspace_by_id": Mock(),
            "get_user_public_workspaces": lambda user: [],
        },
    }.items():
        module = types.ModuleType(name)
        module.__dict__.update(values)
        replacements[name] = module
    spec = importlib.util.spec_from_file_location("test_since_hours_notifications", APP / "functions_notifications.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, replacements):
        spec.loader.exec_module(module)
    return module.parse_workflow_alert_since_hours


def test_route_keeps_its_blueprint_swagger_and_auth_policy():
    assert_app_version_at_least("0.261.199")
    function = route_function()
    decorators = [ast.unparse(value) for value in function.decorator_list]

    assert decorators == [
        "bp.route('/api/notifications/workflow-alerts', methods=['GET'])",
        "swagger_route(security=get_auth_security())",
        "login_required",
        "user_required",
    ]


@pytest.fixture
def alerts_api():
    calls = []
    state = {"fail": False}

    def reader(user_id, limit=5, since_hours=None):
        calls.append({"user_id": user_id, "limit": limit, "since_hours": since_hours})
        if state["fail"]:
            raise RuntimeError("storage unavailable")
        return [{"id": "alert-1", "priority": "high", "delivery": "popup"}]

    namespace = {
        "request": request,
        "jsonify": jsonify,
        "get_current_user_id": lambda: "owner",
        "get_unread_workflow_priority_notifications": reader,
        "parse_workflow_alert_since_hours": load_since_hours_parser(),
        "debug_print": Mock(),
    }
    function = route_function()
    function.decorator_list = []
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROUTES), "exec"), namespace)
    app = Flask("workflow-alert-since-hours")
    app.add_url_rule(ROUTE_PATH, endpoint="alerts", view_func=namespace[function.name])
    return app.test_client(), calls, state


def test_classic_request_is_unchanged(alerts_api):
    client, calls, _ = alerts_api

    response = client.get(ROUTE_PATH, query_string={"limit": 5})

    assert response.status_code == 200
    assert response.json == {
        "success": True,
        "notifications": [{"id": "alert-1", "priority": "high", "delivery": "popup"}],
    }
    assert calls == [{"user_id": "owner", "limit": 5, "since_hours": None}]


def test_v2_request_passes_a_validated_window(alerts_api):
    client, calls, _ = alerts_api

    response = client.get(ROUTE_PATH, query_string={"limit": 10, "since_hours": 24})

    assert response.status_code == 200
    assert set(response.json) == {"success", "notifications"}
    assert calls == [{"user_id": "owner", "limit": 10, "since_hours": 24}]


@pytest.mark.parametrize(("limit", "expected"), [("0", 5), ("11", 5), ("1", 1), ("10", 10)])
def test_out_of_range_limits_fall_back_as_before(alerts_api, limit, expected):
    client, calls, _ = alerts_api

    assert client.get(ROUTE_PATH, query_string={"limit": limit}).status_code == 200
    assert calls[-1]["limit"] == expected


@pytest.mark.parametrize("since_hours", ["", "0", "1441", "-1", "24.5", "abc", "<script>", "99999"])
def test_invalid_windows_are_rejected_without_reading(alerts_api, since_hours):
    client, calls, _ = alerts_api

    response = client.get(ROUTE_PATH, query_string={"since_hours": since_hours})

    assert response.status_code == 400
    assert response.json["success"] is False
    assert response.json["notifications"] == []
    assert response.json["error"]
    assert "<script>" not in response.json["error"]
    assert calls == []


def test_reader_failure_keeps_the_existing_error_shape(alerts_api):
    client, _, state = alerts_api
    state["fail"] = True

    response = client.get(ROUTE_PATH, query_string={"since_hours": 24})

    assert response.status_code == 500
    assert response.json == {"success": False, "notifications": []}


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-q"]))
