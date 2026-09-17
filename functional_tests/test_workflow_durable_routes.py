# test_workflow_durable_routes.py
"""
Functional tests for durable workflow HTTP control boundaries.
Version: 0.261.111
Implemented in: 0.261.111

Production route helpers run in Flask with isolated runtime services. Decisions
are scope-authorized and version/request-bound; native runs return queued202.
"""

import ast
import logging
import sys
from pathlib import Path

import pytest
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from flask import Flask, jsonify, request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Application imports follow the worktree module-path setup.
from functions_workflow_runtime_store import RuntimeUnavailable, WorkflowRuntimeConflict


ROUTES = Path(__file__).resolve().parents[1] / "application" / "single_app" / "route_backend_workflows.py"


@pytest.fixture
def runtime_api():
    workflow = {"id": "workflow", "user_id": "owner", "durable_execution": True}
    state = {"can_manage": True, "allowed": True}
    calls = []
    runtime = {
        "version": 4, "state": "waiting_approval", "phase": "task:send",
        "gate": {"id": "gate", "kind": "approval", "unit_id": "task:send", "choices": ["approve", "reject"]},
    }

    def group_scope(user_id):
        if not state["allowed"]:
            raise PermissionError("Access revoked.")
        return "group", {}

    def assert_role(*args, **kwargs):
        if not state["can_manage"]:
            raise PermissionError("No management role.")
        return "Admin"

    def status(workflow, run_id, **kwargs):
        if state.get("unavailable"):
            raise RuntimeUnavailable()
        calls.append(("read", run_id, kwargs))
        return runtime

    def decision(workflow, run_id, data, **kwargs):
        calls.append(("decision", run_id, data, kwargs))
        if data["expected_version"] != runtime["version"]:
            raise WorkflowRuntimeConflict("workflow_version_conflict")
        return {**runtime, "version": 5, "state": "queued"}

    namespace = {
        "jsonify": jsonify, "request": request, "AzureError": AzureError, "logging": logging,
        "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
        "WorkflowRuntimeConflict": WorkflowRuntimeConflict,
        "RuntimeUnavailable": RuntimeUnavailable,
        "get_current_user_id": lambda: "owner",
        "get_personal_workflow": lambda user_id, workflow_id: workflow if workflow_id == workflow["id"] else None,
        "get_group_workflow": lambda group_id, workflow_id: workflow if workflow_id == workflow["id"] else None,
        "_resolve_group_workflow_request_group": group_scope,
        "assert_group_role": assert_role,
        "get_group_workflow_management_roles": lambda settings: ["Owner", "Admin"],
        "workflow_runtime_status": status,
        "decide_workflow_runtime": decision,
        "queue_durable_workflow_run": lambda workflow, **kwargs: calls.append(("queue", kwargs)) or {
            "success": True, "run": {"id": "run", "status": "queued", "durable_execution": True},
            "runtime": runtime, "workflow": workflow,
        },
        "log_event": lambda *args, **kwargs: None,
    }
    names = {"_workflow_runtime_response", "_queue_workflow_response", "_workflow_definition_response"}
    nodes = [node for node in ast.parse(ROUTES.read_text(encoding="utf-8")).body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROUTES), "exec"), namespace)
    app = Flask("workflow-runtime-api")
    app.add_url_rule("/queue", endpoint="queue", view_func=lambda: namespace["_queue_workflow_response"](workflow, "owner"), methods=["POST"])
    app.add_url_rule("/<scope>/<workflow_id>/<run_id>/runtime", endpoint="read",
                     view_func=lambda scope, workflow_id, run_id: namespace["_workflow_runtime_response"](
                         workflow_id, run_id, group=scope == "group",
                     ))
    app.add_url_rule("/<scope>/<workflow_id>/<run_id>/runtime/<action>", endpoint="decision",
                     view_func=lambda scope, workflow_id, run_id, action: namespace["_workflow_runtime_response"](
                         workflow_id, run_id, group=scope == "group", action=action,
                     ), methods=["POST"])
    return app.test_client(), state, calls


def test_durable_start_returns_queued_without_executing_a_model(runtime_api):
    client, state, calls = runtime_api
    response = client.post("/queue", json={})
    assert response.status_code == 202
    assert response.json["run"]["status"] == "queued"
    assert calls[0][0] == "queue"


def test_approval_posts_exact_gate_and_version(runtime_api):
    client, state, calls = runtime_api
    payload = {"expected_version": 4, "gate_id": "gate", "choice": "approve", "request_id": "request"}
    response = client.post("/user/workflow/run/runtime/decision", json=payload)
    assert response.status_code == 200
    assert response.json["runtime"]["state"] == "queued"
    assert calls[-1][2] == payload


def test_stale_approval_is_a_conflict_not_an_automatic_retry(runtime_api):
    client, state, calls = runtime_api
    response = client.post("/user/workflow/run/runtime/decision", json={
        "expected_version": 3, "gate_id": "gate", "choice": "approve", "request_id": "request",
    })
    assert response.status_code == 409
    assert len(calls) == 1


def test_readonly_group_members_can_view_but_not_approve(runtime_api):
    client, state, calls = runtime_api
    state["can_manage"] = False
    response = client.get("/group/workflow/run/runtime")
    assert response.status_code == 200
    assert response.json["can_decide"] is False
    response = client.post("/group/workflow/run/runtime/decision", json={
        "expected_version": 4, "gate_id": "gate", "choice": "approve", "request_id": "request",
    })
    assert response.status_code == 403
    assert [call[0] for call in calls] == ["read"]


def test_group_membership_is_checked_again_after_reload(runtime_api):
    client, state, calls = runtime_api
    state["allowed"] = False
    assert client.get("/group/workflow/run/runtime").status_code == 403
    assert calls == []


def test_runtime_decisions_cannot_inject_private_claim_fields(runtime_api):
    client, state, calls = runtime_api
    assert client.post("/user/workflow/run/runtime/decision", json={
        "expected_version": 4, "gate_id": "gate", "choice": "approve", "request_id": "request", "token": "forged",
    }).status_code == 400
    assert calls == []


@pytest.mark.parametrize("body", ["false", "[]", "{bad", "null"])
def test_malformed_submissions_are_not_silently_accepted(runtime_api, body):
    client, state, calls = runtime_api
    assert client.post("/queue", data=body, content_type="application/json").status_code == 400
    assert calls == []


def test_runtime_storage_failure_returns_a_safe_retryable_response(runtime_api):
    client, state, calls = runtime_api
    state["unavailable"] = True
    response = client.get("/user/workflow/run/runtime")
    assert response.status_code == 503
    assert response.json == {"error": "Workflow progress is temporarily unavailable."}
