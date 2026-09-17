# test_workflow_execution_journal_policy.py
"""
Structured workflow execution API policy and exact result regression coverage.
Version: 0.261.116
Implemented in: 0.261.116

Production route helpers and journal readers execute with isolated Flask request
contexts and the shared transactional workflow fake, never a live application.
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

# Production and shared fixtures follow the worktree import setup.
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_execution_history import workflow_execution_history, workflow_execution_result_page
from functions_workflow_result_store import WorkflowResultStorageUnavailableError
from functions_workflow_runtime_store import RuntimeUnavailable, WorkflowRuntimeConflict
from test_workflow_structured_flow import runtime, run_flow


ROUTES = ROOT / "application" / "single_app" / "route_backend_workflows.py"


def test_all_eight_execution_routes_retain_blueprint_and_swagger_security():
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    registrar = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_workflows")
    routes = []
    for node in registrar.body:
        if not isinstance(node, ast.FunctionDef) or not node.decorator_list:
            continue
        route = node.decorator_list[0]
        path = route.args[0].value
        if "/executions" not in path and not path.endswith("/runtime/decisions"):
            continue
        routes.append(path)
        assert isinstance(route.func, ast.Attribute) and route.func.value.id == "bp"
        assert ast.unparse(node.decorator_list[1]) == "swagger_route(security=get_auth_security())"
        decorators = [ast.unparse(value) for value in node.decorator_list]
        assert "login_required" in decorators and "user_required" in decorators
        assert any("enabled_required" in value for value in decorators)
        if "/user/" in path:
            assert "workflow_user_required" in decorators
    assert len(routes) == 8


@pytest.fixture
def api(runtime, monkeypatch):
    workflow, store, _, _ = runtime
    flow, _ = run_flow(workflow, store)
    monkeypatch.setattr("functions_workflow_execution_history.workflow_runtime_store", lambda *args: store)
    access = {"group": True, "owner": True}

    def group_scope(user):
        if not access["group"]:
            raise PermissionError
        return "group", {}

    namespace = {
        "get_current_user_id": lambda: "owner", "jsonify": jsonify, "request": request, "logging": logging,
        "get_personal_workflow": lambda user, key: workflow if access["owner"] and key == workflow["id"] else None,
        "get_group_workflow": lambda group, key: workflow if key == workflow["id"] else None,
        "get_personal_workflow_run": lambda user, run: {"id": run, "workflow_id": workflow["id"]} if run == "run" else None,
        "get_group_workflow_run": lambda group, run: {"id": run, "workflow_id": workflow["id"]} if run == "run" else None,
        "_resolve_group_workflow_request_group": group_scope,
        "workflow_execution_history": workflow_execution_history,
        "workflow_execution_result_page": workflow_execution_result_page,
        "WorkflowRuntimeConflict": WorkflowRuntimeConflict, "RuntimeUnavailable": RuntimeUnavailable,
        "AnalysisResultUnavailable": AnalysisResultUnavailable,
        "WorkflowResultStorageUnavailableError": WorkflowResultStorageUnavailableError,
        "AzureError": AzureError, "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
        "log_event": lambda *args, **kwargs: None,
    }
    function = next(node for node in ast.parse(ROUTES.read_text(encoding="utf-8")).body
                    if isinstance(node, ast.FunctionDef) and node.name == "_workflow_execution_history_response")
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROUTES), "exec"), namespace)
    app = Flask("structured-history")
    app.add_url_rule("/<scope>/<workflow_id>/<run_id>/<kind>", endpoint="history", view_func=lambda scope, workflow_id, run_id, kind:
                     namespace["_workflow_execution_history_response"](workflow_id, run_id, group=scope == "group", kind=kind))
    app.add_url_rule("/result/<execution_id>/<int:attempt>", endpoint="result", view_func=lambda execution_id, attempt:
                     namespace["_workflow_execution_history_response"]("workflow", "run", execution_id=execution_id, attempt=attempt))
    return app.test_client(), access, flow


def test_safe_paging_and_exact_attempt_result_routes(api):
    client, access, flow = api
    page = client.get("/user/workflow/run/execution?limit=2")
    assert page.status_code == 200 and len(page.json["executions"]) == 2
    assert page.json["total_count"] == 6 and page.json["next_cursor"]
    assert "token" not in page.get_data(as_text=True)
    identity = flow.final_outputs[0]["producer"]
    response = client.get(f"/result/{identity['execution_id']}/1?limit=2000")
    assert response.status_code == 200 and response.json["output_name"] == "text"
    assert client.get(f"/result/{identity['execution_id']}/2").status_code == 404
    assert client.get("/result/" + "f" * 64 + "/1").status_code == 404
    join = flow.completed["joined"]["summary"]["producer"]
    join_page = client.get(f"/result/{join['execution_id']}/1?output=answer")
    assert join_page.status_code == 200 and join_page.json["output_name"] == "answer"


def test_cursors_ranges_and_current_object_authorization_fail_closed(api):
    client, access, _ = api
    assert client.get("/user/workflow/run/execution?limit=101").status_code == 400
    assert client.get("/user/workflow/run/execution?cursor=forged").status_code == 400
    assert client.get("/user/workflow/other-run/execution").status_code == 404
    access["owner"] = False
    assert client.get("/user/workflow/run/execution").status_code == 404
    access["group"] = False
    assert client.get("/group/workflow/run/execution").status_code == 403
