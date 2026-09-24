# test_v2_group_workspace_context.py
"""
Selected-group context authorization, safe projection, and activation contracts.

Version: 0.261.129
Implemented in: 0.261.126
Shared shell and native delegation integration: 0.261.127

The real context module and Flask route body run against isolated service seams.
Existing group-role/status and Flask authentication definitions execute unchanged.
These are request-boundary tests, not a claim of full Azure bootstrap coverage.
"""

import ast
import importlib.util
import logging
import re
import subprocess
import sys
from copy import deepcopy
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable
from unittest.mock import Mock

import pytest
from flask import Blueprint, Flask, jsonify, request, session

from test_support.agent_delegation import APP_ROOT, execute_functions, module_stub
from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_PATH = "/api/v2/workspaces/group/group-a"


@pytest.fixture
def environment(monkeypatch):
    settings = {
        "enable_group_workspaces": True,
        "enable_semantic_kernel": True,
        "per_user_semantic_kernel": True,
        "allow_group_agents": True,
        "allow_group_plugins": True,
        "allow_group_custom_endpoints": True,
        "enable_multi_model_endpoints": True,
        "allow_group_workflows": True,
    }
    group = {
        "id": "group-a", "name": "Workspace A", "description": "Shared references",
        "owner": {"id": "owner", "displayName": "Owner", "email": "owner@example.test"},
        "admins": ["admin"], "documentManagers": ["manager"],
        "users": [{"userId": "reader"}], "status": "active",
        "heroColor": "#123456", "logoBase64": "fixture-only-logo", "logoVersion": 3,
        "model_endpoints": [{"key": "fixture-only-private-value", "endpoint": "internal"}],
        "connection_string": "fixture-only-private-value",
        "pendingUsers": [{"userId": "private-pending-user"}],
    }
    records = {"group-a": group, "group-b": {**deepcopy(group), "id": "group-b", "name": "Workspace B"}}
    find = Mock(side_effect=lambda group_id: deepcopy(records.get(group_id)))
    group_namespace = {"find_group_by_id": find, "Iterable": Iterable}
    execute_functions("functions_group.py", {
        "assert_group_role", "get_user_role_in_group", "check_group_status_allows_operation",
    }, group_namespace)
    groups = module_stub("functions_group", **{
        name: group_namespace[name] for name in (
            "assert_group_role", "get_user_role_in_group", "check_group_status_allows_operation",
        )
    }, find_group_by_id=find)

    sync_enabled = Mock(return_value=True)
    downloads_enabled = Mock(return_value=True)
    governance = Mock(return_value=True)
    action_governance = Mock(return_value=True)
    settings_namespace = {
        "normalize_group_workflow_allowed_group_ids": lambda value: value or [],
    }
    # The download capability is the real predicate: the settings policy behind
    # settings_management calls it.
    execute_functions("functions_settings.py", {
        "is_group_workflows_enabled_for_group", "get_group_workflow_management_roles",
        "is_group_workspace_file_download_admin_enabled", "_get_workspace_policy_target_id",
        "normalize_file_download_allowed_group_ids",
    }, settings_namespace)
    branding_namespace = {
        "DEFAULT_WORKSPACE_HERO_COLOR": "#0078d4",
        "WORKSPACE_HERO_COLOR_PATTERN": re.compile(r"^#(?:[0-9a-fA-F]{6})$"),
    }
    execute_functions("functions_workspace_branding.py", {
        "normalize_workspace_hero_color", "get_workspace_logo_metadata",
    }, branding_namespace)
    sections_tree = ast.parse((APP_ROOT / "functions_workspace_sections.py").read_text(encoding="utf-8"))
    section_groups = next(
        ast.literal_eval(node.value)
        for node in sections_tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "WORKSPACE_SECTION_GROUPS" for target in node.targets)
    )
    modules = {
        "functions_group": groups,
        "functions_file_sync": module_stub("functions_file_sync", is_file_sync_enabled_for_group=sync_enabled),
        "functions_governance": module_stub(
            "functions_governance", is_governance_access_allowed=governance,
            is_action_scope_access_allowed=action_governance,
        ),
        "functions_settings": module_stub(
            "functions_settings", **settings_namespace,
            is_group_workspace_file_download_enabled=downloads_enabled,
            is_public_workspace_file_download_enabled=Mock(return_value=True),
        ),
        "functions_workspace_branding": module_stub("functions_workspace_branding", **branding_namespace),
        "functions_workspace_sections": module_stub(
            "functions_workspace_sections", WORKSPACE_SECTION_GROUPS=section_groups,
        ),
        # Public workspaces are out of scope here, but the context module imports their
        # lookups at load time. These stand in for the Cosmos-backed functions only.
        "functions_public_workspaces": module_stub(
            "functions_public_workspaces",
            check_public_workspace_status_allows_operation=Mock(return_value=(True, None)),
            find_public_workspace_by_id=Mock(return_value=None),
            get_user_role_in_public_workspace=Mock(return_value=None),
        ),
    }
    # The document and prompt policy modules are pure, with no config or network, so
    # they load for real. The group context's advertised operations are then computed
    # by the same policy the routes enforce. A stub here would let a policy change
    # pass unnoticed.
    for name in ("functions_group_document_policy", "functions_group_prompt_policy",
                 "functions_public_document_policy", "functions_group_settings_policy"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.syspath_prepend(str(APP_ROOT))
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("tested_workspace_context", APP_ROOT / "functions_workspace_context.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)

    app = Flask("workspace_context_contract")
    app.config.update(TESTING=True, SECRET_KEY="fixture-only-session-signing")
    logs = Mock()
    namespace = {
        "__name__": __name__, "Blueprint": Blueprint, "jsonify": jsonify,
        "request": request, "session": session, "wraps": wraps, "logging": logging,
        "get_settings": lambda: settings, "log_event": logs, "debug_print": Mock(),
        "get_current_user_info": lambda: {"userId": session.get("user", {}).get("oid")},
        "check_user_access_status": Mock(return_value=(True, None)),
        "get_auth_security": lambda: [{"sessionAuth": []}],
        "swagger_route": lambda **kwargs: lambda function: function,
        "build_group_workspace_context": helper.build_group_workspace_context,
        "WorkspaceContextError": helper.WorkspaceContextError,
    }
    execute_functions("functions_authentication.py", {
        "login_required", "user_required", "get_current_user_id",
    }, namespace)
    execute_functions("functions_settings.py", {"enabled_required"}, namespace)
    bp = Blueprint("backend_v2", __name__)
    namespace["bp"] = bp
    tree = ast.parse((APP_ROOT / "route_backend_v2.py").read_text(encoding="utf-8"))
    route = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "v2_group_workspace_context")
    exec(compile(ast.Module(body=[route], type_ignores=[]), "route_backend_v2.py", "exec"), namespace)
    app.register_blueprint(bp)
    client = app.test_client()
    with client.session_transaction() as state:
        state["user"] = {"oid": "owner", "roles": ["User"]}

    return SimpleNamespace(
        helper=helper, settings=settings, records=records, client=client, namespace=namespace,
        find=find, sync=sync_enabled, downloads=downloads_enabled, governance=governance,
        action_governance=action_governance, logs=logs,
    )


def read_as(environment, user_id="owner", group_id="group-a"):
    with environment.client.session_transaction() as state:
        state["user"] = {"oid": user_id, "roles": ["User"]}
    return environment.client.get(f"/api/v2/workspaces/group/{group_id}")


def test_projection_is_allowlisted_explicit_and_uncached(environment):
    response = read_as(environment, group_id="group-b")
    body = response.get_json()
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert body["scope"] == {"kind": "group", "id": "group-b"}
    assert body["viewer_id"] == "owner"
    assert body["enabled"] is True
    assert body["sections"]["documents"]["group"] == "knowledge"
    assert body["sections"]["agents"]["group"] == "automation"
    assert body["sections"]["identities"]["group"] == "connections"
    assert body["workspace"]["name"] == "Workspace B"
    assert body["workspace"]["logo_url"] == "/api/groups/group-b/logo?v=3"
    assert body["workspace"]["hero_color"] == "#123456"
    assert body["document_queries"] == {
        "sort_fields": [
            "_ts", "file_name", "title", "upload_date", "file_size",
            "number_of_pages", "version", "document_classification",
        ],
        "facets": True, "places": True,
    }
    assert all(call.args == ("group-b",) for call in environment.find.call_args_list)
    text = response.get_data(as_text=True)
    for private_value in ("fixture-only-private-value", "fixture-only-logo", "private-pending-user", "model_endpoints"):
        assert private_value not in text


@pytest.mark.parametrize("actor,status,expected", [
    ("owner", "active", ["upload", "edit_metadata", "tag_documents", "manage_tags", "delete", "download", "reprocess"]),
    ("admin", "locked", ["download"]),
    ("manager", "upload_disabled", ["delete", "download", "reprocess"]),
    ("reader", "active", []),
    ("owner", "inactive", []),
    ("owner", "unknown", []),
])
def test_management_handshake_matches_current_role_and_status(environment, actor, status, expected):
    environment.records["group-a"]["status"] = status
    response = read_as(environment, actor)
    body = response.get_json()
    assert response.status_code == 200
    assert body["document_management"] == {"schema_version": 1, "operations": expected}


def test_management_handshake_respects_extraction_and_download_settings(environment):
    environment.settings["enable_extract_meta_data"] = True
    environment.downloads.return_value = False
    response = read_as(environment)
    operations = response.get_json()["document_management"]["operations"]
    assert "extract_metadata" in operations
    assert "download" not in operations


@pytest.mark.parametrize("user_id,role,manage,automation", [
    ("owner", "Owner", True, True), ("admin", "Admin", True, True),
    ("manager", "DocumentManager", True, False), ("reader", "User", False, False),
])
def test_roles_and_document_download_boundary(environment, user_id, role, manage, automation):
    response = read_as(environment, user_id)
    body = response.get_json()
    assert response.status_code == 200
    assert body["role"] == role
    assert body["sections"]["documents"]["enabled"] is True
    assert body["sections"]["documents"]["can_manage"] is manage
    assert body["document_permissions"]["can_upload"] is manage
    assert body["document_permissions"]["can_download"] is manage
    assert body["sections"]["prompts"]["can_manage"] is manage
    assert body["sections"]["agents"]["can_manage"] is automation
    assert body["sections"]["actions"]["can_manage"] is automation
    assert body["sections"]["workflows"]["can_manage"] is automation
    assert body["sections"]["identities"]["enabled"] is manage
    assert body["sections"]["sync"]["enabled"] is manage


@pytest.mark.parametrize("status,view,upload,delete", [
    ("active", True, True, True), ("locked", True, False, False),
    ("upload_disabled", True, False, True), ("inactive", False, False, False),
    ("unexpected-status", False, False, False),
])
def test_statuses_never_advertise_unavailable_operations(environment, status, view, upload, delete):
    environment.records["group-a"]["status"] = status
    response = read_as(environment)
    body = response.get_json()
    assert response.status_code == 200
    assert body["document_permissions"]["can_view"] is view
    assert body["document_permissions"]["can_chat"] is view
    assert body["document_permissions"]["can_upload"] is upload
    assert body["document_permissions"]["can_delete"] is delete
    assert body["sections"]["documents"]["enabled"] is view
    if status != "active":
        assert all(not section["can_manage"] for section in body["sections"].values())
    if not view:
        assert all(not section["enabled"] and section["reason"] for section in body["sections"].values())


def test_owner_only_management_does_not_change_endpoint_roles(environment):
    environment.settings["require_owner_for_group_agent_management"] = True
    response = read_as(environment, "admin")
    body = response.get_json()
    for section in ("agents", "actions", "workflows"):
        assert body["sections"][section]["can_manage"] is False
    assert body["sections"]["endpoints"]["can_manage"] is True


def test_existing_delegation_is_not_gated_by_the_personal_kernel(environment):
    environment.settings["per_user_semantic_kernel"] = False
    response = read_as(environment)
    body = response.get_json()
    assert body["sections"]["agents"]["enabled"] is False
    assert body["sections"]["actions"]["enabled"] is False
    assert body["native_delegation"]["enabled"] is True
    assert body["native_delegation"]["can_manage"] is True
    environment.settings["allow_group_plugins"] = False
    restricted = read_as(environment)
    restricted_body = restricted.get_json()
    assert restricted_body["native_delegation"]["enabled"] is True
    assert restricted_body["native_delegation"]["can_manage"] is False


def test_native_delegation_respects_agent_governance_and_group_status(environment):
    environment.governance.side_effect = lambda feature, user_id: feature != "governance_group_agents"
    response = read_as(environment)
    body = response.get_json()
    assert body["native_delegation"]["enabled"] is False
    environment.governance.side_effect = None
    environment.governance.return_value = True
    environment.records["group-a"]["status"] = "locked"
    response = read_as(environment)
    body = response.get_json()
    assert body["native_delegation"]["enabled"] is True
    assert body["native_delegation"]["can_manage"] is False


@pytest.mark.parametrize("actor,status,expected", [
    ("owner", "active", ["create", "edit", "delete"]),
    ("admin", "active", ["create", "edit", "delete"]),
    ("manager", "active", ["create", "edit", "delete"]),
    ("reader", "active", []),
    ("admin", "locked", []),
    ("owner", "inactive", []),
    ("owner", "unknown", []),
])
def test_identity_management_matches_role_and_status(environment, actor, status, expected):
    # B2: identity_management joins action/agent management in the selected-group
    # context, so the frontend reads one workspace-level handshake, and it agrees
    # with the immutable identity list envelope for every role and status.
    environment.records["group-a"]["status"] = status
    response = read_as(environment, actor)
    body = response.get_json()
    assert response.status_code == 200
    assert body["identity_management"] == {"schema_version": 1, "operations": expected}


def test_identity_management_is_built_by_the_shared_policy_with_context_availability(environment):
    # The context must advertise exactly what the routes enforce: one availability
    # predicate resolved once and fed to the shared operations helper.
    helper = environment.helper
    for actor, role in (("owner", "Owner"), ("admin", "Admin"),
                        ("manager", "DocumentManager"), ("reader", "User")):
        available, _reason = helper.group_identities_available(
            environment.settings, "group-a",
            user_info={"userId": actor, "roles": ["User"]},
            file_sync_enabled=True,
        )
        expected = helper.group_identity_management_operations(
            role, deepcopy(environment.records["group-a"]),
            environment.settings, available=available,
        )
        body = read_as(environment, actor).get_json()
        assert body["identity_management"]["operations"] == expected


def test_identity_management_unavailable_when_semantic_kernel_and_file_sync_off(environment):
    environment.settings["enable_semantic_kernel"] = False
    environment.sync.return_value = False
    response = read_as(environment)
    body = response.get_json()
    assert response.status_code == 200
    assert body["identity_management"]["operations"] == []


@pytest.mark.parametrize("actor,status,expected", [
    ("owner", "active", ["create", "edit", "delete", "sync", "test"]),
    ("admin", "active", ["create", "edit", "delete", "sync", "test"]),
    ("manager", "active", ["create", "edit", "delete", "sync", "test"]),
    ("reader", "active", []),
    ("admin", "locked", []),
    ("owner", "inactive", []),
    ("owner", "unknown", []),
])
def test_file_source_management_matches_role_and_status(environment, actor, status, expected):
    # B2 seam: file_source_management rides the selected-group context alongside
    # identity/action/agent management, so the frontend reads one handshake that
    # agrees with the immutable file-source list envelope for every role/status.
    environment.records["group-a"]["status"] = status
    response = read_as(environment, actor)
    body = response.get_json()
    assert response.status_code == 200
    assert body["file_source_management"] == {"schema_version": 1, "operations": expected}


def test_file_source_management_is_built_by_the_shared_policy_with_context_availability(environment):
    # The context must advertise exactly what the routes enforce: one File Sync
    # availability predicate resolved once and fed to the shared operations helper.
    helper = environment.helper
    for actor, role in (("owner", "Owner"), ("admin", "Admin"),
                        ("manager", "DocumentManager"), ("reader", "User")):
        available, _reason = helper.group_file_sources_available(
            environment.settings, "group-a",
            user_info={"userId": actor, "roles": ["User"]},
            file_sync_enabled=True,
        )
        expected = helper.group_file_source_management_operations(
            role, deepcopy(environment.records["group-a"]),
            environment.settings, available=available,
        )
        body = read_as(environment, actor).get_json()
        assert body["file_source_management"]["operations"] == expected


def test_file_source_management_unavailable_when_file_sync_off(environment):
    # File sources require File Sync specifically; Semantic Kernel does not enable
    # them, so turning File Sync off empties the surface even with SK on.
    environment.sync.return_value = False
    response = read_as(environment)
    body = response.get_json()
    assert response.status_code == 200
    assert body["file_source_management"]["operations"] == []


@pytest.mark.parametrize("key,sections", [
    ("per_user_semantic_kernel", ("agents", "actions", "endpoints")),
    ("enable_semantic_kernel", ("agents", "actions", "endpoints")),
    ("allow_group_agents", ("agents", "actions")),
    ("allow_group_plugins", ("actions",)),
    ("enable_multi_model_endpoints", ("endpoints",)),
    ("allow_group_custom_endpoints", ("endpoints",)),
    ("allow_group_workflows", ("workflows",)),
])
def test_feature_gates_are_independent_of_personal_availability(environment, key, sections):
    environment.settings[key] = False
    response = read_as(environment)
    body = response.get_json()
    for section in sections:
        assert body["sections"][section]["enabled"] is False
        assert body["sections"][section]["reason"]
    assert body["sections"]["documents"]["enabled"] is True


def test_policy_helpers_receive_explicit_scope_and_current_app_roles(environment):
    environment.settings.update({
        "require_group_assignment_for_group_workflows": True,
        "group_workflow_allowed_group_ids": ["group-b"],
    })
    environment.governance.return_value = False
    environment.action_governance.return_value = False
    environment.sync.return_value = False
    environment.downloads.return_value = False
    with environment.client.session_transaction() as state:
        state["user"] = {"oid": "owner", "roles": ["User", "Admin"]}
    response = environment.client.get(CONTEXT_PATH)
    body = response.get_json()
    assert response.status_code == 200
    for section in ("agents", "actions", "endpoints", "workflows", "sync"):
        assert body["sections"][section]["enabled"] is False
    assert body["document_permissions"]["can_download"] is False
    assert environment.sync.call_args.args[1] == "group-a"
    assert environment.sync.call_args.kwargs["user_info"]["roles"] == ["User", "Admin"]
    environment.action_governance.assert_called_once_with("governance_group_actions", "owner", "group")
    response_b = read_as(environment, group_id="group-b")
    body_b = response_b.get_json()
    assert body_b["sections"]["workflows"]["enabled"] is True


@pytest.mark.parametrize("user_id,group_id,code", [
    ("outsider", "group-a", 403), ("owner", "missing", 404),
])
def test_foreign_or_deleted_groups_do_not_fall_back_to_active_scope(environment, user_id, group_id, code):
    response = read_as(environment, user_id, group_id)
    body = response.get_json()
    assert response.status_code == code
    assert "workspace" not in body


def test_membership_is_revalidated_on_the_metadata_snapshot(environment):
    initial = deepcopy(environment.records["group-a"])
    revoked = {**deepcopy(initial), "owner": {"id": "someone-else"}}
    environment.find.side_effect = [initial, revoked]
    response = read_as(environment)
    body = response.get_json()
    assert response.status_code == 403
    assert "workspace" not in body


@pytest.mark.parametrize("group_id", ["", ".", "..", " padded", "padded ", "bad/id", "bad\\id", "bad?id", "bad#id", "bad\nid"])
def test_invalid_explicit_ids_never_reach_storage(environment, group_id):
    with pytest.raises(environment.helper.WorkspaceContextError) as failure:
        environment.helper.build_group_workspace_context("owner", group_id, environment.settings)
    assert failure.value.status_code == 400
    environment.find.assert_not_called()


def test_auth_and_deployment_gates_precede_group_reads(environment):
    with environment.client.session_transaction() as state:
        state.clear()
    unauthenticated = environment.client.get(CONTEXT_PATH)
    assert unauthenticated.status_code in (302, 401)
    environment.find.assert_not_called()
    with environment.client.session_transaction() as state:
        state["user"] = {"oid": "owner", "roles": []}
    unauthorized = environment.client.get(CONTEXT_PATH)
    assert unauthorized.status_code == 403
    environment.find.assert_not_called()
    environment.settings["enable_group_workspaces"] = False
    disabled = read_as(environment)
    assert disabled.status_code == 400
    environment.find.assert_not_called()


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError, KeyError, PermissionError])
def test_policy_failure_is_explicit_not_permissive_or_an_empty_success(environment, error_type):
    environment.governance.side_effect = error_type("fixture-only-sensitive-provider-detail")
    response = read_as(environment)
    response_text = response.get_data(as_text=True)
    assert response.status_code == 503
    assert "fixture-only-sensitive-provider-detail" not in response_text
    environment.logs.assert_called_once()
    assert environment.logs.call_args.kwargs["extra"]["error_type"] == error_type.__name__


def test_browser_activation_and_race_contracts():
    result = subprocess.run(
        ["node", str(ROOT / "functional_tests" / "test_v2_group_workspace_context_logic.mjs")],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_implementation_version():
    assert_app_version_at_least("0.261.126")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
