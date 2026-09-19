# test_workflow_repeat_policy.py
"""
Functional policy tests for authorized Repeat iteration and state inspection.
Version: 0.261.120
Implemented in: 0.261.120

Real route helpers and readers use closed Flask and transactional store fixtures.
No live application, permissions, credentials or services are used.
"""

import ast
import logging
import sys
from pathlib import Path

import pytest
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
sys.path.insert(0, str(ROOT / "functional_tests"))

# Shared test helpers follow the isolated worktree import setup.
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_identity import workflow_execution_id
from functions_workflow_node_results import WorkflowRecordPageTooLarge
from functions_workflow_repeat_history import workflow_repeat_iterations_page, workflow_repeat_state_page
from functions_workflow_result_store import WorkflowResultStorageUnavailableError
from functions_workflow_runtime_store import RuntimeUnavailable, WorkflowRuntimeConflict
from test_workflow_repeat_execution import execute_repeat, repeat_runtime


ROUTES = ROOT / "application" / "single_app" / "route_backend_workflows.py"


def test_repeat_routes_keep_exact_existing_blueprint_swagger_and_scope_policies():
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    registrar = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_workflows")
    paths = []
    for function in registrar.body:
        if not isinstance(function, ast.FunctionDef) or not function.decorator_list:
            continue
        route = function.decorator_list[0]
        path = route.args[0].value
        if not (path.endswith("/iterations") or path.endswith("/iterations/<int:iteration>/state")):
            continue
        decorators = [ast.unparse(value) for value in function.decorator_list]
        assert ast.unparse(route.func) == "bp.route"
        assert decorators[1] == "swagger_route(security=get_auth_security())"
        assert "login_required" in decorators and "user_required" in decorators
        if "/user/" in path:
            assert "workflow_user_required" in decorators
            assert "enabled_required('allow_user_workflows')" in decorators
        else:
            assert "enabled_required('enable_group_workspaces')" in decorators
            assert "enabled_required('allow_group_workflows')" in decorators
        paths.append(path)
    assert len(paths) == 4


@pytest.fixture
def repeat_api(monkeypatch):
    workflow, store, _, _, _ = repeat_runtime(monkeypatch)
    execute_repeat(workflow, store, target=3)
    access = {"owner": True, "group": True}

    def group_scope(user):
        if not access["group"]:
            raise PermissionError
        assert request.args.get("group_id") == "fictional-group"
        return "fictional-group", {}

    namespace = {
        "get_current_user_id": lambda: "owner", "jsonify": jsonify, "request": request, "logging": logging,
        "get_personal_workflow": lambda user, key: workflow if access["owner"] and key == workflow["id"] else None,
        "get_group_workflow": lambda group, key: workflow if key == workflow["id"] else None,
        "get_personal_workflow_run": lambda user, run: {"id": run, "workflow_id": workflow["id"]} if run == "run" else None,
        "get_group_workflow_run": lambda group, run: {"id": run, "workflow_id": workflow["id"]} if run == "run" else None,
        "_resolve_group_workflow_request_group": group_scope,
        "workflow_repeat_iterations_page": workflow_repeat_iterations_page,
        "workflow_repeat_state_page": workflow_repeat_state_page,
        "WorkflowRuntimeConflict": WorkflowRuntimeConflict, "RuntimeUnavailable": RuntimeUnavailable,
        "WorkflowResultStorageUnavailableError": WorkflowResultStorageUnavailableError,
        "WorkflowRecordPageTooLarge": WorkflowRecordPageTooLarge,
        "AnalysisResultUnavailable": AnalysisResultUnavailable,
        "AzureError": AzureError, "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
        "log_event": lambda *args, **kwargs: None,
    }
    function = next(node for node in ast.parse(ROUTES.read_text(encoding="utf-8")).body
                    if isinstance(node, ast.FunctionDef) and node.name == "_workflow_execution_history_response")
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROUTES), "exec"), namespace)
    app = Flask("workflow-repeat")

    def inspect(scope, run_id, execution_id, kind, iteration=None):
        return namespace["_workflow_execution_history_response"](
            "workflow", run_id, group=scope == "group", execution_id=execution_id, kind=kind, iteration=iteration,
        )

    app.add_url_rule("/<scope>/<run_id>/<execution_id>/iterations", endpoint="iterations",
                     view_func=lambda scope, run_id, execution_id: inspect(scope, run_id, execution_id, "iterations"))
    app.add_url_rule("/<scope>/<run_id>/<execution_id>/iterations/<int:iteration>/state", endpoint="states",
                     view_func=lambda scope, run_id, execution_id, iteration: inspect(scope, run_id, execution_id, "states", iteration))
    return app.test_client(), workflow_execution_id(workflow, "run", "repeat"), access


def test_iteration_and_state_route_shapes_and_exact_scope_binding(repeat_api):
    client, execution_id, access = repeat_api
    base = f"/user/run/{execution_id}/iterations"
    page = client.get(base, query_string={"limit": 2})
    assert page.status_code == 200 and len(page.json["iterations"]) == 2
    assert page.json["total_count"] == 3 and page.json["next_cursor"]
    state = client.get(f"{base}/1/state?phase=after")
    assert state.status_code == 200 and state.json["available"]
    assert state.json["states"][0]["source"]["iteration_path"][-1]["iteration"] == 1
    assert client.get(f"{base}/1/state?phase=current").status_code == 400
    assert client.get(f"{base}/1/state", query_string={"cursor": page.json["next_cursor"]}).status_code == 400
    assert client.get(base, query_string={"limit": 101}).status_code == 400
    assert client.get(f"{base}/1001/state").status_code == 404
    assert client.get(f"/user/foreign-run/{execution_id}/iterations").status_code == 404
    assert client.get(f"/user/run/{'f' * 64}/iterations").status_code == 404
    assert client.get(f"/group/run/{execution_id}/iterations?group_id=fictional-group").status_code == 200
    access["owner"] = False
    assert client.get(base).status_code == 404
    access["group"] = False
    assert client.get(f"/group/run/{execution_id}/iterations?group_id=fictional-group").status_code == 403
