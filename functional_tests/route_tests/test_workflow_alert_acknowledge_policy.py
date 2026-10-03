# test_workflow_alert_acknowledge_policy.py
"""
Functional policy tests for the workflow alert acknowledgment route.
Version: 0.261.234
Implemented in: 0.261.234

POST /api/notifications/<notification_id>/acknowledge clears a must-acknowledge workflow alert
for everyone who receives it. The real route body runs on a closed Flask app with a recording
acknowledgment function, so these tests pin the route's decorators, the identity it passes on,
and every response shape, including that failures never echo exception text. No live
application, permissions, credentials or services are used.
"""

import ast
import logging
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "functional_tests"))

# Shared test helpers follow the isolated worktree import setup.
from test_support.versioning import assert_app_version_at_least


ROUTES = APP / "route_backend_notifications.py"
ROUTE_PATH = "/api/notifications/<notification_id>/acknowledge"


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


@pytest.fixture
def acknowledge_api():
    """The real route body, without its decorators, over a recording acknowledgment function."""
    state = {"result": ("acknowledged", None), "error": None}
    calls = []
    bumps = []
    log_event = Mock()

    def acknowledge(notification_id, user_id, display_name=""):
        calls.append({"notification_id": notification_id, "user_id": user_id, "display_name": display_name})
        if state["error"]:
            raise state["error"]
        return state["result"]

    namespace = {
        "request": request,
        "jsonify": jsonify,
        "logging": logging,
        "log_event": log_event,
        "get_current_user_id": lambda: "member-1",
        "get_current_user_info": lambda: {"userId": "member-1", "displayName": "Jane Operator", "email": "jane@example.com"},
        "acknowledge_workflow_alert": acknowledge,
        "bump_conversation_cache_version": lambda user_id, reason="": bumps.append((user_id, reason)),
    }
    function = route_function()
    function.decorator_list = []
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROUTES), "exec"), namespace)
    app = Flask("workflow-alert-acknowledge")
    app.add_url_rule(ROUTE_PATH, endpoint="acknowledge", view_func=namespace[function.name], methods=["POST"])
    return app.test_client(), state, calls, bumps, log_event


def acknowledged(notification_id="alert-1", already=False):
    status = "already_acknowledged" if already else "acknowledged"
    return status, {
        "id": notification_id,
        "acknowledged_at": "2026-10-03T15:00:00+00:00",
        "acknowledged_by_name": "Jane Operator",
    }


def test_route_keeps_its_blueprint_swagger_and_auth_policy():
    assert_app_version_at_least("0.261.234")
    decorators = [ast.unparse(value) for value in route_function().decorator_list]

    assert decorators == [
        "bp.route('/api/notifications/<notification_id>/acknowledge', methods=['POST'])",
        "swagger_route(security=get_auth_security())",
        "login_required",
        "user_required",
    ]


def test_acknowledging_passes_the_signed_in_identity_and_reports_who_and_when(acknowledge_api):
    client, state, calls, bumps, _ = acknowledge_api
    state["result"] = acknowledged()

    response = client.post("/api/notifications/alert-1/acknowledge")

    assert response.status_code == 200
    assert response.json == {
        "success": True,
        "notification_id": "alert-1",
        "acknowledged_at": "2026-10-03T15:00:00+00:00",
        "acknowledged_by_name": "Jane Operator",
        "already_acknowledged": False,
    }
    # The identity comes from the session, never from the request.
    assert calls == [{"notification_id": "alert-1", "user_id": "member-1", "display_name": "Jane Operator"}]
    assert bumps == [("member-1", "workflow_alert_acknowledged")]


def test_an_alert_someone_already_acknowledged_reports_the_first_acknowledgment(acknowledge_api):
    client, state, _, _, _ = acknowledge_api
    state["result"] = acknowledged(already=True)

    response = client.post("/api/notifications/alert-1/acknowledge")

    assert response.status_code == 200
    assert response.json["already_acknowledged"] is True
    assert response.json["acknowledged_by_name"] == "Jane Operator"


def test_an_alert_the_caller_cannot_receive_is_not_found(acknowledge_api):
    client, state, _, bumps, _ = acknowledge_api
    state["result"] = ("not_found", None)

    response = client.post("/api/notifications/someone-elses-alert/acknowledge")

    assert response.status_code == 404
    assert response.json == {"success": False, "error": "Alert not found."}
    assert bumps == []


def test_an_alert_that_needs_no_acknowledgment_is_refused(acknowledge_api):
    client, state, _, bumps, _ = acknowledge_api
    state["result"] = ("not_required", None)

    response = client.post("/api/notifications/alert-1/acknowledge")

    assert response.status_code == 400
    assert response.json == {"success": False, "error": "This alert does not need acknowledgment."}
    assert bumps == []


def test_a_failure_is_logged_without_echoing_its_text(acknowledge_api):
    client, state, _, _, log_event = acknowledge_api
    state["error"] = RuntimeError("cosmos://secret-endpoint exploded")

    response = client.post("/api/notifications/alert-1/acknowledge")

    assert response.status_code == 500
    assert response.json == {"success": False, "error": "Unable to acknowledge the alert."}
    assert "secret-endpoint" not in response.get_data(as_text=True)
    log_event.assert_called_once()
    assert log_event.call_args.kwargs["extra"] == {"user_id": "member-1", "error_type": "RuntimeError"}


def test_get_is_not_an_acknowledgment(acknowledge_api):
    client, _, calls, _, _ = acknowledge_api

    response = client.get("/api/notifications/alert-1/acknowledge")

    assert response.status_code == 405
    assert calls == []


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-q"]))
