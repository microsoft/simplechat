# test_workflow_loop_policy.py
"""
Functional policy tests for M4B frozen items and semantic record inspection.
Version: 0.261.117
Implemented in: 0.261.117

Real route helpers and readers run against isolated Flask requests and the
transactional workflow fixture. No live app, document, model, or Azure is used.
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

# Shared test helpers follow the worktree import setup.
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_execution_history import workflow_execution_history, workflow_execution_result_page
from functions_workflow_identity import workflow_execution_id
from functions_workflow_node_results import WorkflowRecordPageTooLarge
from functions_workflow_loop_history import (
    workflow_execution_records_page, workflow_execution_provenance_page, workflow_loop_items_page,
)
from functions_workflow_result_store import WorkflowResultStorageUnavailableError
from functions_workflow_runtime_store import RuntimeUnavailable, WorkflowRuntimeConflict
from test_workflow_for_each_execution import loop_runtime, execute_loop


ROUTES = ROOT / "application" / "single_app" / "route_backend_workflows.py"


def test_new_loop_routes_have_exact_existing_scope_and_swagger_policies():
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    registrar = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_workflows")
    matched = []
    for function in registrar.body:
        if not isinstance(function, ast.FunctionDef) or not function.decorator_list:
            continue
        route = function.decorator_list[0]
        path = route.args[0].value
        if not any(path.endswith(suffix) for suffix in ("/items", "/records", "/provenance", "/loop-inputs/preview")):
            continue
        if "/executions/" not in path and not path.endswith("/loop-inputs/preview"):
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
        matched.append(path)
    assert len(matched) == 8


@pytest.fixture
def loop_api(monkeypatch):
    workflow, store, _, _ = loop_runtime(monkeypatch)
    flow, _ = execute_loop(workflow, store, [{"id": index} for index in range(3)])
    access = {"owner": True, "group": True}

    def group_scope(user):
        if not access["group"]:
            raise PermissionError
        assert request.args.get("group_id") == "group-one"
        return "group-one", {}

    namespace = {
        "get_current_user_id": lambda: "owner", "jsonify": jsonify, "request": request, "logging": logging,
        "get_personal_workflow": lambda user, key: workflow if access["owner"] and key == workflow["id"] else None,
        "get_group_workflow": lambda group, key: workflow if key == workflow["id"] else None,
        "get_personal_workflow_run": lambda user, run: {"id": run, "workflow_id": workflow["id"]} if run == "run" else None,
        "get_group_workflow_run": lambda group, run: {"id": run, "workflow_id": workflow["id"]} if run == "run" else None,
        "_resolve_group_workflow_request_group": group_scope,
        "workflow_execution_history": workflow_execution_history,
        "workflow_execution_result_page": workflow_execution_result_page,
        "workflow_execution_records_page": workflow_execution_records_page,
        "workflow_execution_provenance_page": workflow_execution_provenance_page,
        "workflow_loop_items_page": workflow_loop_items_page,
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
    app = Flask("workflow-loops")

    def inspect(scope, execution_id, representation):
        return namespace["_workflow_execution_history_response"](
            "workflow", "run", group=scope == "group", execution_id=execution_id,
            kind="items" if representation == "items" else "execution",
            attempt=None if representation == "items" else 1, representation=representation,
        )

    app.add_url_rule("/<scope>/<execution_id>/<representation>", endpoint="inspect", view_func=inspect)
    return app.test_client(), workflow, flow, access


def test_complete_record_and_item_pages_bind_cursor_to_the_exact_kind(loop_api):
    client, workflow, flow, _ = loop_api
    producer = flow.final_outputs[0]["producer"]
    records = client.get(f"/user/{producer['execution_id']}/records?limit=2")
    assert records.status_code == 200
    assert records.json["records"] == [{"id": 0}, {"id": 1}]
    assert records.json["total_count"] == 3 and records.json["next_cursor"]
    next_page = client.get(f"/user/{producer['execution_id']}/records", query_string={"cursor": records.json["next_cursor"]})
    assert next_page.json["records"] == [{"id": 2}] and next_page.json["next_cursor"] is None
    loop_id = workflow_execution_id(workflow, "run", "each")
    invalid = client.get(f"/user/{loop_id}/items", query_string={"cursor": records.json["next_cursor"]})
    assert invalid.status_code == 400
    items = client.get(f"/user/{loop_id}/items?limit=2")
    assert items.status_code == 200 and len(items.json["items"]) == 2
    assert items.json["items"][0]["iteration_path"][0]["loop_id"] == "each"


def test_provenance_and_source_scope_checks_cannot_use_another_reader(loop_api):
    client, _, flow, access = loop_api
    producer = flow.final_outputs[0]["producer"]
    provenance = client.get(f"/user/{producer['execution_id']}/provenance?limit=2")
    assert provenance.status_code == 200 and len(provenance.json["contributors"]) == 2
    assert provenance.json["contributors"][0]["producer"]["iteration_path"][0]["index"] == 0
    assert client.get(f"/user/{producer['execution_id']}/records?limit=101").status_code == 400
    assert client.get(f"/user/{'f' * 64}/records").status_code == 404
    access["owner"] = False
    assert client.get(f"/user/{producer['execution_id']}/records").status_code == 404
    access["group"] = False
    assert client.get(f"/group/{producer['execution_id']}/records?group_id=group-one").status_code == 403
