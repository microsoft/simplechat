# test_control_center_safe_exception_responses.py
"""
Functional test for safe Control Center exception responses.
Version: 0.261.286
Implemented in: 0.261.283

This test ensures validation exceptions in the V2 Control Center routes do not
expose provider or stack-trace details, and malformed stored expiry values keep
access restrictions fail-closed.
"""

import ast
import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
ROUTE = ROOT / "application" / "single_app" / "route_backend_control_center.py"
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least


SENSITIVE_ERROR = "provider-secret connection details"


class GroupRequestError(ValueError):
    """Test exception type caught by the group request handlers."""


def _load_route(name, failing_helper, error_type):
    tree = ast.parse(ROUTE.read_text(encoding="utf-8"))
    route_node = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    route_node = copy.deepcopy(route_node)
    route_node.decorator_list = []

    def fail(*_args, **_kwargs):
        raise error_type(SENSITIVE_ERROR)

    namespace = {
        "jsonify": jsonify,
        "request": request,
        "GroupRequestError": GroupRequestError,
        failing_helper: fail,
    }
    module = ast.fix_missing_locations(ast.Module(body=[route_node], type_ignores=[]))
    exec(compile(module, str(ROUTE), "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize(
    ("route_name", "helper", "error_type", "method", "json_body", "args", "safe_message"),
    [
        ("api_v2_control_center_users", "_control_center_parse_user_filters", ValueError,
         "GET", None, (), "Invalid user filters or pagination value."),
        ("api_v2_control_center_user_detail", "_control_center_validate_user_id", ValueError,
         "GET", None, ("user-1",), "Invalid user ID."),
        ("api_v2_control_center_users_bulk_action", "_control_center_validate_user_id", ValueError,
         "POST", {"action_type": "access", "settings": {"status": "allow"}, "user_ids": ["user-1"]},
         (), "Invalid bulk user action request."),
        ("api_v2_control_center_users_export", "_control_center_parse_user_filters", ValueError,
         "GET", None, (), "Invalid user export filters."),
        ("api_v2_control_center_groups", "parse_group_filters", GroupRequestError,
         "GET", None, (), "Invalid group filters."),
        ("api_v2_control_center_group_detail", "validate_group_id", GroupRequestError,
         "GET", None, ("group-1",), "Invalid group ID."),
        ("api_v2_control_center_groups_bulk_status", "validate_group_status_payload", GroupRequestError,
         "POST", {}, (), "Invalid bulk group status request."),
        ("api_v2_control_center_group_status", "validate_group_id", GroupRequestError,
         "PUT", None, ("group-1",), "Invalid group status request."),
        ("api_v2_control_center_groups_export", "parse_group_filters", GroupRequestError,
         "GET", None, (), "Invalid group export filters."),
        ("api_v2_control_center_public_workspaces", "parse_workspace_filters", GroupRequestError,
         "GET", None, (), "Invalid public workspace filters."),
        ("api_v2_control_center_public_workspace_detail", "validate_group_id", GroupRequestError,
         "GET", None, ("workspace-1",), "Invalid public workspace ID."),
        ("api_v2_control_center_public_workspaces_bulk_status", "validate_group_status_payload", GroupRequestError,
         "POST", {}, (), "Invalid bulk public workspace status request."),
        ("api_v2_control_center_public_workspace_status", "validate_group_id", GroupRequestError,
         "PUT", None, ("workspace-1",), "Invalid public workspace status request."),
        ("api_v2_control_center_public_workspaces_export", "parse_workspace_filters", GroupRequestError,
         "GET", None, (), "Invalid public workspace export filters."),
    ],
)
def test_validation_exceptions_return_stable_safe_messages(
    route_name, helper, error_type, method, json_body, args, safe_message
):
    route = _load_route(route_name, helper, error_type)
    app = Flask(__name__)
    with app.test_request_context("/", method=method, json=json_body):
        response, status_code = route(*args)

    assert status_code == 400
    assert response.get_json() == {"error": safe_message}
    assert SENSITIVE_ERROR not in response.get_data(as_text=True)


def test_malformed_stored_expiry_keeps_restriction_fail_closed():
    tree = ast.parse(ROUTE.read_text(encoding="utf-8"))
    helper_node = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_control_center_effective_restriction"
    )
    module = ast.fix_missing_locations(ast.Module(
        body=[copy.deepcopy(helper_node)],
        type_ignores=[],
    ))
    namespace = {"datetime": datetime, "timezone": timezone}
    exec(compile(module, str(ROUTE), "exec"), namespace)

    restriction = namespace["_control_center_effective_restriction"](
        {"access": {"status": "deny", "datetime_to_allow": "invalid timestamp"}},
        "access",
    )

    assert restriction == {"status": "deny", "expires_at": "invalid timestamp"}


def test_implementation_version_is_present():
    assert_app_version_at_least("0.261.283")
