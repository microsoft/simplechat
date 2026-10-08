# test_v2_scope_and_bootstrap_timings.py
"""
Functional contracts for the lightweight V2 active-scope read and phase timings.

Version: 0.261.306
Implemented in: 0.261.305

The real route bodies, scope helper, timer, and authentication decorators execute
against isolated storage seams, without importing Azure client initialization.
This validates request behavior, not live Azure latency or cold-import safety.
"""

import ast
import logging
import time
from functools import wraps
from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Blueprint, Flask, jsonify, request, session

from test_support.agent_delegation import APP_ROOT, execute_functions
from test_support.versioning import assert_app_version_at_least


@pytest.fixture
def environment():
    groups = [{"id": "group-a", "name": "Group A"}]
    preferences = {
        "activeGroupOid": "group-a", "activePublicWorkspaceOid": "public-a",
        "publicDirectorySettings": {"public-a": True, "hidden": False},
        "private_key": "fixture-private-settings",
    }
    logs = Mock()
    app = Flask("scope_and_timings")
    app.config.update(TESTING=True, SECRET_KEY="fixture-only-signing")
    bp = Blueprint("backend_v2", __name__)
    namespace = {
        "__name__": __name__, "bp": bp, "jsonify": jsonify, "request": request,
        "session": session, "wraps": wraps, "logging": logging, "time": time,
        "VERSION": "0.261.306", "log_event": logs, "debug_print": Mock(),
        "logger": logging.getLogger(__name__),
        "get_auth_security": lambda: [{"sessionAuth": []}],
        "swagger_route": lambda **kwargs: lambda function: function,
        "check_user_access_status": Mock(return_value=(True, None)),
        "get_settings": Mock(return_value={"private_key": "fixture-private-settings"}),
        "sanitize_settings_for_user": Mock(return_value={"enable_group_workspaces": True}),
        "get_user_settings": Mock(side_effect=lambda user_id: {"settings": preferences}),
        "get_current_user_info": lambda: {"userId": session.get("user", {}).get("oid")},
        "get_user_groups": Mock(side_effect=lambda user_id: groups),
        "find_group_by_id": Mock(side_effect=lambda group_id: next(
            (group for group in groups if group["id"] == group_id), None,
        )),
        "find_public_workspace_by_id": Mock(side_effect=lambda workspace_id:
                                            {"id": workspace_id, "name": "Public A"}
                                            if workspace_id == "public-a" else None),
        "get_all_public_workspaces": Mock(return_value=[{"id": "public-a"}]),
        "get_user_visible_public_workspace_ids_from_settings": Mock(return_value=["public-a"]),
        "build_accessible_agent_catalog": Mock(return_value=[]),
        "_is_chat_agent_allowed_by_governance": Mock(return_value=True),
        "_build_chat_model_catalog": Mock(return_value=[]),
        "_build_chat_prompt_catalog": Mock(return_value=[]),
        "_build_initial_chat_model_selection": Mock(return_value=None),
        "build_workspace_section_availability": Mock(return_value={"enabled": False, "sections": {}}),
        "count_pending_safety_warnings": Mock(return_value=0),
        "ADMIN_NAV": [],
    }
    for name in (
        "is_chat_file_upload_enabled_for_user", "is_user_workflows_enabled_for_user",
        "is_workflow_assistant_enabled_for_user", "is_agent_assistant_enabled",
        "is_action_assistant_enabled", "is_admin_review_assistant_enabled",
        "is_chat_workflow_results_enabled_for_user", "is_source_review_enabled_for_user",
        "is_url_access_enabled_for_user", "is_conversation_contents_drawer_enabled",
    ):
        namespace[name] = Mock(return_value=True)
    for name in (
        "_build_branding", "_build_navigation", "_build_feature_flags", "_build_capabilities",
        "get_control_center_capabilities", "_build_orchestration", "_build_notices",
        "_build_workspace_uploads",
    ):
        namespace[name] = Mock(return_value={})
    execute_functions("functions_authentication.py", {
        "get_current_user_id", "login_required", "user_required",
    }, namespace)
    execute_functions("functions_public_workspaces.py", {
        "visible_public_workspace_ids_from_user_settings",
    }, namespace)
    tree = ast.parse((APP_ROOT / "route_backend_v2.py").read_text(encoding="utf-8"))
    wanted = {"BootstrapPhaseTimer", "_resolve_active_scope", "v2_scope", "v2_bootstrap"}
    nodes = [node for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in wanted]
    assert {node.name for node in nodes} == wanted
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP_ROOT / "route_backend_v2.py"), "exec"), namespace)
    app.register_blueprint(bp)
    client = app.test_client()
    with client.session_transaction() as state:
        state["user"] = {"oid": "viewer", "roles": ["User"]}
    return SimpleNamespace(
        client=client, namespace=namespace, preferences=preferences, groups=groups, logs=logs,
    )


def test_scope_is_private_uncached_and_does_not_build_catalogs(environment):
    assert_app_version_at_least("0.261.305")
    response = environment.client.get("/api/v2/scope")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {
        "user": {"id": "viewer"},
        "scope": {
            "active_group_id": "group-a", "active_group_name": "Group A",
            "active_public_workspace_id": "public-a",
        },
    }
    assert "fixture-private-settings" not in response.get_data(as_text=True)
    environment.namespace["get_user_settings"].assert_called_once_with("viewer")
    for name in ("get_settings", "_build_chat_model_catalog", "_build_chat_prompt_catalog",
                 "build_accessible_agent_catalog", "sanitize_settings_for_user"):
        environment.namespace[name].assert_not_called()


@pytest.mark.parametrize("group_id,workspace_id", [
    ("revoked-group", "hidden"), ("group-a", "missing-public"), (None, None),
])
def test_stale_preferences_are_filtered_and_match_bootstrap(environment, group_id, workspace_id):
    environment.preferences.update(activeGroupOid=group_id, activePublicWorkspaceOid=workspace_id)
    scope_response = environment.client.get("/api/v2/scope")
    bootstrap_response = environment.client.get("/api/v2/bootstrap")
    assert scope_response.status_code == bootstrap_response.status_code == 200
    active = scope_response.get_json()["scope"]
    full = bootstrap_response.get_json()["scope"]
    assert active == {key: full[key] for key in active}
    assert active["active_group_id"] == ("group-a" if group_id == "group-a" else None)
    assert active["active_public_workspace_id"] is None


def test_deleted_active_group_is_not_echoed(environment):
    environment.namespace["find_group_by_id"].return_value = None
    environment.namespace["find_group_by_id"].side_effect = None
    response = environment.client.get("/api/v2/scope")
    assert response.status_code == 200
    assert response.get_json()["scope"]["active_group_id"] is None


def test_scope_failures_are_explicit_and_do_not_expose_provider_errors(environment):
    environment.namespace["get_user_groups"].side_effect = RuntimeError("fixture-private-provider-error")
    response = environment.client.get("/api/v2/scope")
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {"error": "Failed to load active scope"}
    assert environment.logs.call_args.kwargs["extra"] == {"error_type": "RuntimeError"}


def test_scope_requires_a_signed_in_user(environment):
    with environment.client.session_transaction() as state:
        state.clear()
    response = environment.client.get("/api/v2/scope")
    assert response.status_code == 401
    environment.namespace["get_user_settings"].assert_not_called()


@pytest.mark.parametrize("outcome,expected_status", [
    ("success", 200), ("missing_identity", 401), ("storage_failure", 503),
])
def test_scope_body_returns_consistent_response_tuples(environment, outcome, expected_status):
    """All scope body return paths preserve response, status, and no-store headers."""
    route = unwrap(environment.namespace["v2_scope"])
    with environment.client.application.test_request_context("/api/v2/scope"):
        if outcome != "missing_identity":
            session["user"] = {"oid": "viewer", "roles": ["User"]}
        if outcome == "storage_failure":
            environment.namespace["get_user_groups"].side_effect = RuntimeError("fixture failure")
        result = route()
    assert isinstance(result, tuple)
    assert len(result) == 3
    response, status, headers = result
    assert response.is_json
    assert status == expected_status
    assert headers == {"Cache-Control": "no-store"}


@pytest.mark.parametrize("fails", [False, True])
def test_bootstrap_emits_one_flat_numeric_timing_event_even_on_failure(environment, fails):
    if fails:
        environment.namespace["get_settings"].side_effect = RuntimeError("fixture failure")
    response = environment.client.get("/api/v2/bootstrap")
    assert response.status_code == (500 if fails else 200)
    timings = [call for call in environment.logs.call_args_list
               if call.args[0] == "[V2_BOOTSTRAP] Phase timings"]
    assert len(timings) == 1
    properties = timings[0].kwargs["extra"]
    assert properties["total_ms"] >= 0
    assert all(isinstance(value, (int, float)) and value >= 0 for value in properties.values())
    if not fails:
        assert {"phase_settings_ms", "phase_source_review_ms", "phase_model_catalog_ms",
                "phase_serialize_ms", "phase_active_scope_ms"} <= properties.keys()
        environment.namespace["_build_navigation"].assert_called_once_with(
            environment.namespace["get_settings"].return_value, ["User"],
        )
        assert response.get_json()["settings"] == {"enable_group_workspaces": True}


def test_timer_measures_elapsed_work_and_failed_calls(environment):
    ticks = iter([0.0, 0.2, 0.3, 0.7, 0.8])
    timer = environment.namespace["BootstrapPhaseTimer"](clock=lambda: next(ticks))
    timer.mark("settings")
    failing = Mock(side_effect=ValueError("fixture failure"))
    with pytest.raises(ValueError):
        timer.measure("failed_catalog", failing)
    timer.emit()
    properties = environment.logs.call_args.kwargs["extra"]
    assert properties == {"total_ms": 800.0, "phase_settings_ms": 200.0, "phase_failed_catalog_ms": 400.0}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
