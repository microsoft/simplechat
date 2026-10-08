# test_workflow_delete_recovery_routes.py
"""
Functional tests for retryable workflow deletion and cancellation conflicts.
Version: 0.261.305
Implemented in: 0.261.305

Execute the real personal/group route bodies and cancellation helper over
scoped storage doubles. Route authentication policies are verified separately
by functional_tests/route_tests and group fixture parity tests.
"""

import ast
import logging
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.core.exceptions import AzureError
from flask import Blueprint, Flask, jsonify

from functions_workflow_result_store import (
    AnalysisWorkUnitConflictError,
    WorkflowResultIntegrityError,
    WorkflowResultStorageUnavailableError,
)
from test_workflow_cancellation import (
    ROUTES_FILE,
    RUNTIME_STORE_FILE,
    _load_cancellation_route_helpers,
    _load_nodes,
)


@pytest.fixture
def recovery_routes():
    workflow = {
        "id": "workflow-one", "user_id": "owner", "name": "Review",
        "active_run_id": "run-one", "status": "running",
    }
    run = {
        "id": "run-one", "workflow_id": workflow["id"],
        "status": "running", "durable_execution": True,
    }
    get_workflow = Mock(side_effect=lambda scope_id, workflow_id: deepcopy(workflow))
    delete_workflow = Mock(return_value=True)
    get_run = Mock(side_effect=lambda scope_id, run_id: deepcopy(run))
    save_run = Mock(side_effect=lambda scope_id, record: record)
    update_workflow = Mock(side_effect=lambda scope_id, workflow_id, updates: {**workflow, **updates})
    cancel_durable = Mock(return_value={"workflow": workflow, "run": run})
    deletion_log = Mock()
    events = Mock()
    runtime = _load_nodes(
        RUNTIME_STORE_FILE, class_names=("WorkflowRuntimeConflict", "RuntimeUnavailable"),
    )
    helpers = _load_cancellation_route_helpers(namespace={
        **runtime, "cancel_durable_workflow_run": cancel_durable,
    })
    namespace = _load_nodes(
        ROUTES_FILE,
        function_names=("_workflow_delete_failure_response",),
        assignment_names=("WORKFLOW_DELETE_FAILURE_ERRORS", "WORKFLOW_DELETE_FAILED_MESSAGE"),
        namespace={
            **helpers,
            "AzureError": AzureError,
            "AnalysisWorkUnitConflictError": AnalysisWorkUnitConflictError,
            "WorkflowResultIntegrityError": WorkflowResultIntegrityError,
            "WorkflowResultStorageUnavailableError": WorkflowResultStorageUnavailableError,
            "jsonify": jsonify,
            "logging": logging,
            "log_event": events,
            "sanitize_log_message": lambda value: str(value).replace("\n", " ").replace("\r", " "),
            "get_current_user_id": lambda: "owner",
            "_resolve_active_group_for_workflow_management": Mock(return_value=("group-one", {})),
            "_resolve_group_workflow_request_group": Mock(return_value=("group-one", {})),
            "get_personal_workflow": get_workflow,
            "get_group_workflow": get_workflow,
            "delete_personal_workflow": delete_workflow,
            "delete_group_workflow": delete_workflow,
            "get_personal_workflow_run": get_run,
            "get_group_workflow_run": get_run,
            "save_personal_workflow_run": save_run,
            "save_group_workflow_run": save_run,
            "update_personal_workflow_runtime_fields": update_workflow,
            "update_group_workflow_runtime_fields": update_workflow,
            "log_workflow_deletion": deletion_log,
        },
    )
    routes = (
        ("delete_user_workflow", "/api/user/workflows/<workflow_id>", "DELETE"),
        ("delete_group_workflow_route", "/api/group/workflows/<workflow_id>", "DELETE"),
        ("cancel_active_user_workflow_run", "/api/user/workflows/<workflow_id>/cancel", "POST"),
        ("cancel_user_workflow_run", "/api/user/workflows/<workflow_id>/runs/<run_id>/cancel", "POST"),
        ("cancel_active_group_workflow_run", "/api/group/workflows/<workflow_id>/cancel", "POST"),
        ("cancel_group_workflow_run", "/api/group/workflows/<workflow_id>/runs/<run_id>/cancel", "POST"),
    )
    names = {name for name, _, _ in routes}
    nodes = []
    for node in ast.walk(ast.parse(ROUTES_FILE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node.decorator_list = []
            nodes.append(node)
    assert {node.name for node in nodes} == names
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROUTES_FILE), "exec"), namespace)

    app = Flask("workflow-delete-recovery")
    app.config["TESTING"] = True
    blueprint = Blueprint("backend_workflows", __name__)
    for name, path, method in routes:
        blueprint.add_url_rule(path, view_func=namespace[name], methods=[method])
    app.register_blueprint(blueprint)
    return SimpleNamespace(
        client=app.test_client(), workflow=workflow, run=run, helpers=namespace,
        get_workflow=get_workflow, delete_workflow=delete_workflow,
        get_run=get_run, save_run=save_run, update_workflow=update_workflow,
        cancel_durable=cancel_durable, deletion_log=deletion_log, events=events,
    )


@pytest.mark.parametrize("scope, scope_id", [("user", "owner"), ("group", "group-one")])
@pytest.mark.parametrize("failure", ["integrity", "analysis", "azure", "storage", "runtime", "conflict"])
def test_delete_failures_are_safe_json_and_retryable(recovery_routes, scope, scope_id, failure):
    harness = recovery_routes
    failures = {
        "integrity": WorkflowResultIntegrityError("PRIVATE PROVIDER DETAILS"),
        "analysis": AnalysisWorkUnitConflictError("analysis_work_deleted"),
        "azure": AzureError("PRIVATE PROVIDER DETAILS"),
        "storage": WorkflowResultStorageUnavailableError("PRIVATE PROVIDER DETAILS"),
        "runtime": harness.helpers["RuntimeUnavailable"](),
        "conflict": harness.helpers["WorkflowRuntimeConflict"]("not_found"),
    }
    harness.delete_workflow.side_effect = [failures[failure], True]
    path = f"/api/{scope}/workflows/workflow-one"
    failed = harness.client.delete(path)
    assert failed.status_code == 500
    assert failed.is_json
    assert failed.json == {"error": harness.helpers["WORKFLOW_DELETE_FAILED_MESSAGE"]}
    assert "PRIVATE" not in failed.get_data(as_text=True)
    harness.delete_workflow.assert_called_with(scope_id, "workflow-one")
    harness.deletion_log.assert_not_called()
    harness.events.assert_called_once()
    fields = harness.events.call_args.kwargs
    assert fields["extra"]["error_type"] == type(failures[failure]).__name__
    assert fields["exceptionTraceback"] is True
    assert fields["extra"]["workspace_type"] == ("personal" if scope == "user" else "group")

    harness.workflow.update({"deleting": True, "status": "deleting"})
    retried = harness.client.delete(path)
    assert retried.status_code == 200
    assert retried.json == {"success": True}
    harness.deletion_log.assert_called_once()


@pytest.mark.parametrize("scope", ["user", "group"])
@pytest.mark.parametrize("missing_at", ["lookup", "delete"])
def test_missing_workflows_remain_404(recovery_routes, scope, missing_at):
    harness = recovery_routes
    if missing_at == "lookup":
        harness.get_workflow.side_effect = None
        harness.get_workflow.return_value = None
    else:
        harness.delete_workflow.return_value = False
    response = harness.client.delete(f"/api/{scope}/workflows/workflow-one")
    assert response.status_code == 404
    assert response.json == {"error": "Workflow not found."}
    harness.events.assert_not_called()
    harness.deletion_log.assert_not_called()
    if missing_at == "lookup":
        harness.delete_workflow.assert_not_called()


@pytest.mark.parametrize("scope", ["user", "group"])
@pytest.mark.parametrize("explicit_run", [False, True])
@pytest.mark.parametrize("failure", ["deleting", "status_only", "no_active", "missing_runtime", "terminal"])
def test_all_cancel_endpoints_return_json_conflicts(recovery_routes, scope, explicit_run, failure):
    harness = recovery_routes
    if failure in ("deleting", "status_only", "no_active"):
        harness.workflow["status"] = "deleting"
        if failure == "deleting":
            harness.workflow["deleting"] = True
        if failure == "no_active":
            harness.workflow["active_run_id"] = ""
        expected = harness.helpers["WORKFLOW_DELETE_PENDING_MESSAGE"]
    elif failure == "missing_runtime":
        harness.cancel_durable.side_effect = harness.helpers["WorkflowRuntimeConflict"]("not_found")
        expected = harness.helpers["WORKFLOW_RUNTIME_MISSING_MESSAGE"]
    else:
        expected = "The run is already finished."
        harness.cancel_durable.side_effect = harness.helpers["WorkflowRuntimeConflict"]("run_terminal", expected)
    suffix = "/runs/run-one/cancel" if explicit_run else "/cancel"
    response = harness.client.post(f"/api/{scope}/workflows/workflow-one{suffix}")
    assert response.status_code == 409
    assert response.is_json
    assert response.json == {"error": expected}
    harness.save_run.assert_not_called()
    harness.update_workflow.assert_not_called()
    if failure in ("deleting", "status_only", "no_active"):
        harness.get_run.assert_not_called()
        harness.cancel_durable.assert_not_called()


@pytest.mark.parametrize("scope, scope_id", [("user", "owner"), ("group", "group-one")])
@pytest.mark.parametrize("explicit_run", [False, True])
def test_cancel_success_preserves_existing_status_and_scoped_reads(recovery_routes, scope, scope_id, explicit_run):
    harness = recovery_routes
    suffix = "/runs/run-one/cancel" if explicit_run else "/cancel"
    response = harness.client.post(f"/api/{scope}/workflows/workflow-one{suffix}")
    assert response.status_code == 202
    assert response.json["success"] is True
    harness.get_workflow.assert_called_once_with(scope_id, "workflow-one")
    harness.get_run.assert_called_once_with(scope_id, "run-one")
    harness.cancel_durable.assert_called_once_with(harness.workflow, "run-one", actor_user_id="owner")


@pytest.mark.parametrize("scope", ["user", "group"])
def test_cancel_never_accepts_a_run_from_another_workflow(recovery_routes, scope):
    harness = recovery_routes
    harness.run["workflow_id"] = "other-workflow"
    response = harness.client.post(f"/api/{scope}/workflows/workflow-one/runs/run-one/cancel")
    assert response.status_code == 404
    harness.cancel_durable.assert_not_called()
    harness.save_run.assert_not_called()
    harness.update_workflow.assert_not_called()


def test_group_delete_checks_management_access_before_storage(recovery_routes):
    harness = recovery_routes
    harness.helpers["_resolve_active_group_for_workflow_management"].side_effect = PermissionError("Forbidden.")
    response = harness.client.delete("/api/group/workflows/workflow-one")
    assert response.status_code == 403
    harness.get_workflow.assert_not_called()
    harness.delete_workflow.assert_not_called()
