# test_workflow_editor_routes.py
"""
Functional tests for real native workflow authoring API/store integration.
Version: 0.261.108
Implemented in: 0.261.108

Flask route bodies call production store normalization and conditional writes
against isolated storage. Route registration/authentication decorators are
independently covered by the existing Blueprint policy suites.
"""

import ast
import logging
from pathlib import Path

import pytest
from flask import Flask, jsonify, request
from azure.core.exceptions import AzureError

from test_workflow_definition_store_integration import definition, load_group_store, load_personal_store
from functions_workflow_definitions import WorkflowDefinitionConflict, WorkflowDefinitionError
from functions_workflow_editor import build_workflow_editor_options


ROUTES = Path(__file__).resolve().parents[1] / "application" / "single_app" / "route_backend_workflows.py"


@pytest.fixture
def editor_api():
    personal, personal_container, personal_reads = load_personal_store()
    group, group_container, group_reads = load_group_store()
    state = {"role": "Admin", "active_group": "another-group", "actor": "owner"}
    role_checks = []

    def group_role(user_id, group_id, allowed_roles):
        role_checks.append((user_id, group_id, tuple(allowed_roles)))
        if group_id != "group-one" or state["role"] not in allowed_roles:
            raise PermissionError("Not a current authorized group member.")
        return state["role"]

    def options(user_id, settings, *, group_id=""):
        return build_workflow_editor_options(
            scope_type="group" if group_id else "personal", scope_id=group_id or user_id,
            can_manage=not group_id or state["role"] in {"Owner", "Admin"},
            max_tasks=50, agents=[], endpoints=[],
        )

    namespace = {
        "request": request, "jsonify": jsonify, "logging": logging,
        "WorkflowDefinitionConflict": WorkflowDefinitionConflict,
        "WorkflowDefinitionError": WorkflowDefinitionError,
        "AzureError": AzureError,
        "get_current_user_id": lambda: state["actor"],
        "get_settings": lambda: {"allow_group_workflows": True, "private_secret": "never-return"},
        "get_group_workflow_management_roles": lambda settings: ["Owner", "Admin"],
        "assert_group_role": group_role,
        "require_active_group": lambda user_id, **kwargs: state["active_group"],
        "is_group_workflows_enabled_for_group": lambda settings, group_id: group_id == "group-one",
        "GROUP_WORKFLOW_MEMBER_ROLES": ("Owner", "Admin", "DocumentManager", "User"),
        "_prepare_workflow_url_access_payload": lambda payload, user_id: payload,
        "_get_current_user_info_with_roles": lambda: {},
        "get_workflow_editor_options": options,
        "save_personal_workflow": personal["save_personal_workflow"],
        "save_group_workflow": group["save_group_workflow"],
        "get_personal_workflows": personal["get_personal_workflows"],
        "get_group_workflows": group["get_group_workflows"],
        "log_workflow_creation": lambda **kwargs: None,
        "log_workflow_update": lambda **kwargs: None,
        "log_event": lambda *args, **kwargs: None,
    }
    helpers = {
        "_normalize_identifier", "_assert_group_workflow_feature_enabled",
        "_workflow_definition_response",
        "_resolve_active_group_for_workflows", "_resolve_group_workflow_request_group",
        "_resolve_active_group_for_workflow_management",
    }
    functions = {
        "get_user_workflows": ("/api/user/workflows", "GET"),
        "save_user_workflow": ("/api/user/workflows", "POST"),
        "get_group_workflows_route": ("/api/group/workflows", "GET"),
        "save_group_workflow_route": ("/api/group/workflows", "POST"),
        "get_user_workflow_editor_options": ("/api/user/workflows/editor-options", "GET"),
        "get_group_workflow_editor_options_route": ("/api/group/workflows/editor-options", "GET"),
    }
    nodes = []
    for node in ast.walk(ast.parse(ROUTES.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef) and node.name in helpers | functions.keys():
            node.decorator_list = []
            nodes.append(node)
    assert len(nodes) == len(helpers) + len(functions)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROUTES), "exec"), namespace)
    app = Flask("workflow-editor-api")
    for name, (url, method) in functions.items():
        app.add_url_rule(url, endpoint=name, methods=[method], view_func=namespace[name])
    return app.test_client(), state, personal_container, group_container, role_checks


@pytest.mark.parametrize("scope", ["user", "group"])
def test_native_post_roundtrips_inputs_and_revision_through_real_store(editor_api, scope):
    client, state, personal, group, role_checks = editor_api
    suffix = "?group_id=group-one" if scope == "group" else ""
    url = f"/api/{scope}/workflows{suffix}"
    result = client.post(url, json=definition())
    assert result.status_code == 201
    saved = result.json["workflow"]
    assert saved["tasks"][2]["inputs"][0]["task_id"] == "extract"
    assert saved["reference_inputs"][0]["scope_id"] == "group-one"
    assert len(saved["definition_revision"]) == 64
    listed = client.get(url).json["workflows"][0]
    assert listed["definition_revision"] == saved["definition_revision"]
    updated = client.post(url, json={**listed, "description": "A native edit."})
    assert updated.status_code == 200
    assert updated.json["workflow"]["tasks"][2]["inputs"] == saved["tasks"][2]["inputs"]
    if scope == "group":
        assert state["active_group"] == "another-group"
        assert all(check[1] == "group-one" for check in role_checks)


@pytest.mark.parametrize("scope", ["user", "group"])
def test_legacy_downgrade_and_stale_post_return_conflict_not_success(editor_api, scope):
    client, state, personal, group, role_checks = editor_api
    suffix = "?group_id=group-one" if scope == "group" else ""
    url = f"/api/{scope}/workflows{suffix}"
    saved = client.post(url, json=definition()).json["workflow"]
    legacy = dict(saved)
    legacy.pop("definition_version")
    denied = client.post(url, json=legacy)
    assert denied.status_code == 409
    assert denied.json["code"] == "workflow_definition_conflict"
    assert "V2" in denied.json["error"]
    client.post(url, json={**saved, "name": "A concurrent edit"})
    stale = client.post(url, json={**saved, "description": "Old draft"})
    assert stale.status_code == 409
    assert client.get(url).json["workflows"][0]["name"] == "A concurrent edit"


def test_readonly_group_members_can_view_options_but_cannot_save(editor_api):
    client, state, personal, group, role_checks = editor_api
    state["role"] = "User"
    options = client.get("/api/group/workflows/editor-options?group_id=group-one")
    assert options.status_code == 200
    assert options.json["can_manage"] is False
    denied = client.post("/api/group/workflows?group_id=group-one", json=definition())
    assert denied.status_code == 403
    assert group.writes == 0


def test_unknown_group_and_secret_settings_are_not_exposed(editor_api):
    client, state, personal, group, role_checks = editor_api
    assert client.get("/api/group/workflows/editor-options?group_id=not-member").status_code == 403
    options = client.get("/api/user/workflows/editor-options")
    assert options.status_code == 200
    assert "never-return" not in options.get_data(as_text=True)
    assert options.json["definition_version"] == 2


def test_native_shape_errors_return_actionable_public_messages(editor_api):
    client, state, personal, group, role_checks = editor_api
    payload = definition()
    payload["tasks"][2]["inputs"][0]["task_id"] = "does-not-exist"
    response = client.post("/api/user/workflows", json=payload)
    assert response.status_code == 400
    assert response.json["code"] == "invalid_workflow_definition"
    assert "earlier tasks" in response.json["error"]
    assert personal.writes == 0


@pytest.mark.parametrize("scope", ["user", "group"])
def test_definition_post_rejects_nonobject_json(editor_api, scope):
    client, state, personal, group, role_checks = editor_api
    response = client.post(f"/api/{scope}/workflows?group_id=group-one", json=["not", "a", "definition"])
    assert response.status_code == 400
    assert "JSON object" in response.json["error"]
    assert personal.writes == group.writes == 0
