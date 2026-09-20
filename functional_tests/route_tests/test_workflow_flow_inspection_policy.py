# test_workflow_flow_inspection_policy.py
"""
Offline route policy tests for saved, draft and frozen-run Flow inspection.
Version: 0.261.121
Implemented in: 0.261.121

Real route helpers, compiler and snapshot readers use closed Flask/WSGI fixtures
and fictional stores. No application clients, credentials or live work are used.
"""

import ast
import copy
import json
import logging
import sys
from functools import wraps
from pathlib import Path

import pytest
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from flask import Blueprint, Flask, jsonify, request, session
from werkzeug.test import Client

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
sys.path.insert(0, str(ROOT / "functional_tests"))

# Production imports follow the isolated worktree import setup.
import functions_workflow_inspection as inspection
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_definitions import WorkflowDefinitionConflict, WorkflowDefinitionError
from functions_workflow_execution_history import workflow_execution_history, workflow_execution_result_page
from functions_workflow_identity import workflow_execution_id
from functions_workflow_inspection import (
    WorkflowFlowDetailTooLarge, WorkflowFlowUnsupported, authorize_workflow_flow_sources, preview_workflow_flow,
    workflow_flow_inspection, workflow_run_flow_inspection,
)
from functions_workflow_journal import journal_record_id
from functions_workflow_node_results import WorkflowRecordPageTooLarge
from functions_workflow_result_store import WorkflowResultStorageUnavailableError, WorkflowResultStore
from functions_workflow_runtime_store import CONTROL_ID, RuntimeUnavailable, WorkflowRuntimeConflict, WorkflowRuntimeStore
from test_workflow_structured_flow import create_structured_runtime, definition, run_flow


ROUTES = ROOT / "application" / "single_app" / "route_backend_workflows.py"
FLOW_FUNCTIONS = {
    "get_user_workflow_flow", "get_group_workflow_flow",
    "get_user_workflow_run_flow", "get_group_workflow_run_flow",
    "preview_user_workflow_flow", "preview_group_workflow_flow",
}


def test_all_six_flow_routes_keep_existing_blueprint_swagger_and_feature_policies():
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    registrar = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_workflows")
    found = set()
    for function in registrar.body:
        if not isinstance(function, ast.FunctionDef) or function.name not in FLOW_FUNCTIONS:
            continue
        route = function.decorator_list[0]
        path = route.args[0].value
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
        methods = next(keyword.value for keyword in route.keywords if keyword.arg == "methods")
        assert ast.literal_eval(methods) == (["POST"] if "preview" in function.name else ["GET"])
        found.add(function.name)
    assert found == FLOW_FUNCTIONS


@pytest.fixture
def api(monkeypatch):
    state = {
        "user": "owner", "login": True, "user_role": True, "workflow_role": True,
        "group_role": "User", "source": True, "own": True, "reads": [],
        "settings": {"allow_user_workflows": True, "allow_group_workflows": True, "enable_group_workspaces": True},
    }
    workspaces = {}
    for group_id in (None, "fictional-group"):
        workflow = definition()
        if group_id:
            workflow["group_id"] = group_id
        workflow["reference_inputs"] = [{
            "id": "context", "name": "context", "document_id": "fictional-document",
            "scope_type": "group" if group_id else "personal", "scope_id": group_id or "owner",
        }]
        workflow, store, container, clock = create_structured_runtime(workflow, monkeypatch)
        run_flow(workflow, store)
        run = {"id": "run", "workflow_id": "workflow", "user_id": "owner", "durable_execution": True}
        if group_id:
            run["group_id"] = group_id
        workspaces[group_id] = {"workflow": workflow, "run": run, "container": container, "clock": clock}

    def result_store(workflow):
        return WorkflowResultStore(workspaces[workflow.get("group_id")]["container"])

    def runtime_store(workflow, run_id):
        state["reads"].append(("snapshot", workflow.get("group_id"), run_id))
        workspace = workspaces[workflow.get("group_id")]
        return WorkflowRuntimeStore(workspace["container"], workflow, run_id, clock=workspace["clock"])

    monkeypatch.setattr("functions_workflow_result_store._configured_store", result_store)
    monkeypatch.setattr(inspection, "workflow_runtime_store", runtime_store)
    monkeypatch.setattr("functions_workflow_execution_history.workflow_runtime_store", runtime_store)

    def resolve_document(**arguments):
        assert arguments["include_content"] is False
        state["reads"].append(("source", arguments["document_id"]))
        if not state["source"]:
            raise PermissionError("Fictional revoked source")
        scope = arguments["doc_scope"]
        return {
            "scope": scope, "group_id": "fictional-group" if scope == "group" else None,
            "document": {"id": arguments["document_id"], "user_id": "owner"},
        }

    def no_content(*args, **kwargs):
        raise AssertionError("Flow inspection must not load document content.")

    monkeypatch.setattr("functions_workflow_bindings._source_helpers", lambda: (resolve_document, no_content))

    def read(group_id, kind, identifier, user_id=None):
        state["reads"].append((kind, group_id, identifier))
        if group_id not in workspaces or group_id is None and (not state["own"] or user_id != "owner"):
            return None
        item = workspaces[group_id][kind]
        return copy.deepcopy(item) if item["id"] == identifier else None

    def assert_role(user_id, group_id, *, allowed_roles):
        assert user_id == state["user"]
        if group_id != "fictional-group" or state["group_role"] not in allowed_roles:
            raise PermissionError("Fictional current membership denied")

    def guard(allowed, code=403):
        def decorate(function):
            @wraps(function)
            def guarded(*args, **kwargs):
                if not allowed():
                    return jsonify({"error": "Not allowed"}), code
                return function(*args, **kwargs)
            return guarded
        return decorate

    namespace = {
        "json": json, "jsonify": jsonify, "request": request, "session": session, "logging": logging,
        "get_current_user_id": lambda: state["user"], "get_settings": lambda: state["settings"],
        "is_user_workflows_enabled_for_user": lambda settings, **kwargs: settings["allow_user_workflows"] and state["workflow_role"],
        "is_group_workflows_enabled_for_group": lambda settings, group_id: group_id == "fictional-group" and settings["allow_group_workflows"],
        "get_group_workflow_management_roles": lambda settings: ("Owner", "Admin", "DocumentManager"),
        "GROUP_WORKFLOW_MEMBER_ROLES": ("Owner", "Admin", "DocumentManager", "User"),
        "assert_group_role": assert_role,
        "require_active_group": no_content,
        "get_personal_workflow": lambda user, key: read(None, "workflow", key, user),
        "get_group_workflow": lambda group, key: read(group, "workflow", key),
        "get_personal_workflow_run": lambda user, key: read(None, "run", key, user),
        "get_group_workflow_run": lambda group, key: read(group, "run", key),
        "authorize_workflow_flow_sources": authorize_workflow_flow_sources,
        "workflow_flow_inspection": workflow_flow_inspection,
        "workflow_run_flow_inspection": workflow_run_flow_inspection,
        "preview_workflow_flow": preview_workflow_flow,
        "workflow_execution_history": workflow_execution_history,
        "workflow_execution_result_page": workflow_execution_result_page,
        "WorkflowFlowDetailTooLarge": WorkflowFlowDetailTooLarge, "WorkflowFlowUnsupported": WorkflowFlowUnsupported,
        "WorkflowDefinitionConflict": WorkflowDefinitionConflict, "WorkflowDefinitionError": WorkflowDefinitionError,
        "WorkflowRuntimeConflict": WorkflowRuntimeConflict, "RuntimeUnavailable": RuntimeUnavailable,
        "WorkflowResultStorageUnavailableError": WorkflowResultStorageUnavailableError,
        "WorkflowRecordPageTooLarge": WorkflowRecordPageTooLarge, "AnalysisResultUnavailable": AnalysisResultUnavailable,
        "CosmosResourceNotFoundError": CosmosResourceNotFoundError, "AzureError": AzureError,
        "log_event": lambda *args, **kwargs: None,
        "swagger_route": lambda **kwargs: lambda function: function, "get_auth_security": lambda: [],
        "login_required": guard(lambda: state["login"], 401),
        "user_required": guard(lambda: state["user_role"]),
        "workflow_user_required": guard(lambda: state["workflow_role"]),
        "enabled_required": lambda feature: guard(lambda: state["settings"][feature]),
    }
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    helpers = {
        "_normalize_identifier", "_assert_personal_workflow_draft_access", "_assert_group_workflow_feature_enabled",
        "_resolve_active_group_for_workflows", "_resolve_group_workflow_request_group",
        "_resolve_active_group_for_workflow_management", "_assert_workflow_flow_reader_scope",
        "_workflow_flow_response", "_workflow_execution_history_response", "_workflow_inspection_cache_response",
    }
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in helpers]
    registrar = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_workflows")
    registrar.body = [
        node for node in registrar.body
        if isinstance(node, ast.FunctionDef) and (
            node.name in FLOW_FUNCTIONS
            or node.name.startswith("get_") and any(
                isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id in {"_workflow_execution_history_response", "_workflow_runtime_response"}
                for call in ast.walk(node)
            )
        )
        or isinstance(node, ast.Expr) and ast.unparse(node) == "bp.after_request(_workflow_inspection_cache_response)"
    ]
    exec(compile(ast.Module(body=[*functions, registrar], type_ignores=[]), str(ROUTES), "exec"), namespace)
    app = Flask("workflow-flow")
    app.config.update(TESTING=True, SECRET_KEY="fictional-closed-test")
    blueprint = Blueprint("backend_workflows", __name__)
    blueprint.before_request(lambda: None if state["login"] else (jsonify({"error": "Login required"}), 401))
    namespace["register_route_backend_workflows"](blueprint)
    app.register_blueprint(blueprint)
    return Client(app, app.response_class), state, workspaces


def test_saved_draft_and_run_routes_return_source_bound_shapes(api):
    client, state, _ = api
    saved = client.get("/api/user/workflows/workflow/flow")
    assert saved.status_code == 200 and saved.json["source"]["kind"] == "saved"
    assert saved.cache_control.no_store and saved.cache_control.private
    run = client.get("/api/user/workflows/workflow/runs/run/flow")
    assert run.status_code == 200 and run.json["source"]["kind"] == "run"
    assert run.cache_control.no_store and run.cache_control.private
    assert run.json["source"]["run_id"] == "run" and run.json["source"]["snapshot_sha256"]
    detail = client.get("/api/user/workflows/workflow/flow", query_string={
        "node_id": "report-node", "section": "inputs", "revision": saved.json["source"]["definition_revision"],
    })
    assert detail.status_code == 200 and detail.json["items"][0]["value"]["source"]["node_id"] == "joined"
    assert detail.cache_control.no_store and detail.cache_control.private
    state["reads"].clear()
    draft = {**definition(), "id": "foreign-workflow", "user_id": "foreign", "group_id": "foreign-group"}
    preview = client.post("/api/user/workflows/flow-preview", json={"definition": draft})
    assert preview.status_code == 200 and preview.json["source"]["kind"] == "draft"
    assert preview.cache_control.no_store and preview.cache_control.private
    assert preview.json["source"]["scope_id"] == "owner" and state["reads"] == []
    assert "definition_revision" not in draft


def test_group_reader_and_author_permissions_are_distinct_and_current(api):
    client, state, _ = api
    state["user"] = "member"
    query = {"group_id": "fictional-group"}
    saved = client.get("/api/group/workflows/workflow/flow", query_string=query)
    run = client.get("/api/group/workflows/workflow/runs/run/flow", query_string=query)
    assert saved.status_code == run.status_code == 200
    assert saved.json["source"]["scope_id"] == "fictional-group"
    assert client.post("/api/group/workflows/flow-preview", query_string=query, json={"definition": definition()}).status_code == 403
    state["group_role"] = "Owner"
    preview = client.post("/api/group/workflows/flow-preview", query_string=query, json={"definition": definition()})
    assert preview.status_code == 200 and preview.json["source"]["scope_type"] == "group"
    state["group_role"] = None
    assert client.get("/api/group/workflows/workflow/flow", query_string=query).status_code == 403
    assert client.get("/api/group/workflows/workflow/runs/run/flow", query_string=query).status_code == 403
    assert client.get("/api/group/workflows/workflow/flow").status_code == 400


def test_workflow_run_and_scope_ids_are_not_authorization(api):
    client, state, workspaces = api
    assert client.get("/api/user/workflows/foreign/flow").status_code == 404
    assert client.get("/api/user/workflows/workflow/runs/foreign/flow").status_code == 404
    assert client.get("/api/group/workflows/workflow/flow?group_id=foreign").status_code == 403
    workspaces[None]["workflow"]["user_id"] = "foreign"
    assert client.get("/api/user/workflows/workflow/flow").status_code == 404
    workspaces[None]["workflow"]["user_id"] = "owner"
    workspaces[None]["run"]["workflow_id"] = "foreign"
    assert client.get("/api/user/workflows/workflow/runs/run/flow").status_code == 404
    workspaces[None]["run"]["workflow_id"] = "workflow"
    workspaces[None]["run"]["user_id"] = "foreign"
    assert client.get("/api/user/workflows/workflow/runs/run/flow").status_code == 404
    workspaces["fictional-group"]["workflow"]["group_id"] = "foreign"
    assert client.get("/api/group/workflows/workflow/flow?group_id=fictional-group").status_code == 404
    state["own"] = False
    assert client.get("/api/user/workflows/workflow/flow").status_code == 404


@pytest.mark.parametrize("scope", ["user", "group"])
def test_saved_and_frozen_source_revocation_clears_topology_and_details(api, scope):
    client, state, _ = api
    if scope == "group":
        state["user"] = "member"
    query = {"group_id": "fictional-group"} if scope == "group" else {}
    base = f"/api/{scope}/workflows/workflow"
    paths = [f"{base}/flow", f"{base}/runs/run/flow"]
    sources = {}
    for path in paths:
        response = client.get(path, query_string=query)
        assert response.status_code == 200 and response.cache_control.no_store
        sources[path] = response.json["source"]
    assert ("source", "fictional-document") in state["reads"]
    state["source"] = False
    for path in paths:
        for selectors in ({}, {
            "node_id": "report-node", "section": "configuration",
            "revision": sources[path]["definition_revision"],
        }):
            state["reads"].clear()
            response = client.get(path, query_string={**query, **selectors})
            assert response.status_code == 403 and "nodes" not in response.json and "items" not in response.json
            assert response.cache_control.no_store and response.cache_control.private
            assert ("source", "fictional-document") in state["reads"]


def test_detail_revision_bounds_conflicts_and_unsupported_snapshots(api, monkeypatch):
    client, _, workspaces = api
    base = "/api/user/workflows/workflow/flow"
    saved = client.get(base).json
    selectors = {"node_id": "report-node", "section": "configuration", "revision": saved["source"]["definition_revision"]}
    assert client.get(base, query_string={**selectors, "limit": 101}).status_code == 400
    assert client.get(base, query_string={**selectors, "cursor": "forged"}).status_code == 400
    assert client.get(base, query_string={"node_id": "report-node"}).status_code == 400
    assert client.get(base, query_string={**selectors, "revision": "stale"}).status_code == 409
    assert client.get(base, query_string={**selectors, "node_id": "foreign"}).status_code == 404
    workspaces[None]["workflow"]["tasks"][0]["instructions"] = "New live instructions."
    assert client.get(base, query_string=selectors).status_code == 409
    run = client.get("/api/user/workflows/workflow/runs/run/flow")
    assert run.status_code == 200 and run.json["source"]["definition_revision"] == saved["source"]["definition_revision"]
    monkeypatch.setattr(inspection, "FLOW_DETAIL_MAX_BYTES", 100)
    response = client.get("/api/user/workflows/workflow/runs/run/flow", query_string=selectors)
    assert response.status_code == 413 and "items" not in response.json
    workspaces[None]["container"].items["run", CONTROL_ID]["schema_version"] = 1
    assert client.get("/api/user/workflows/workflow/runs/run/flow").status_code == 409


def test_unsupported_saved_versions_do_not_read_sources_or_fall_back(api):
    client, state, workspaces = api
    for version in (1, 2, 4, True, "3"):
        workspaces[None]["workflow"]["definition_version"] = version
        state["reads"].clear()
        response = client.get("/api/user/workflows/workflow/flow")
        assert response.status_code == 409 and response.json["code"] == "workflow_flow_unsupported"
        assert response.cache_control.no_store and response.cache_control.private
        assert all(read[0] not in {"source", "snapshot"} for read in state["reads"])


@pytest.mark.parametrize("body", [
    None, [], {}, {"definition": None}, {"definition": definition(), "save": True},
    {"definition": definition(), "node_id": "report-node", "section": "configuration", "revision": "stale"},
])
def test_invalid_preview_never_uses_stored_draft_id(api, body):
    client, state, _ = api
    state["reads"].clear()
    assert client.post("/api/user/workflows/flow-preview", json=body).status_code in {400, 409}
    assert state["reads"] == []


def test_exact_selector_routes_use_frozen_identity_and_reject_conflicts(api, monkeypatch):
    client, state, workspaces = api
    base = "/api/user/workflows/workflow/runs/run/executions"
    history = client.get(base, query_string={"limit": 1})
    assert history.status_code == 200 and history.cache_control.no_store and history.cache_control.private
    before = copy.deepcopy(workspaces[None]["workflow"])
    workspaces[None]["workflow"]["tasks"][0]["instructions"] = "Updated live."
    monkeypatch.setattr(workspaces[None]["container"], "query_items", lambda **kwargs: pytest.fail("Exact read scanned history"))
    query = {"node_id": "report-node", "iteration_path": "[]"}
    response = client.get(base, query_string=query)
    assert response.status_code == 200 and response.json["total_count"] == 1
    assert response.cache_control.no_store and response.cache_control.private
    assert response.json["executions"][0]["execution_id"] == workflow_execution_id(before, "run", "report-node")
    for invalid in (
        {"node_id": "report-node"}, {"iteration_path": "[]"},
        {**query, "cursor": "anything"}, {**query, "attempt": 2},
        {**query, "iteration_path": "null"}, {**query, "iteration_path": "[broken"},
        {**query, "iteration_path": "[{}]"}, {**query, "node_id": "positive"},
        {**query, "limit": 101},
    ):
        response = client.get(base, query_string=invalid)
        assert response.status_code == 400 and response.cache_control.no_store
    state["own"] = False
    assert client.get(base, query_string=query).status_code == 404


def test_group_exact_selector_retains_current_reader_access(api):
    client, state, workspaces = api
    state["user"] = "member"
    base = "/api/group/workflows/workflow/runs/run/executions"
    query = {"group_id": "fictional-group", "node_id": "report-node", "iteration_path": "[]"}
    response = client.get(base, query_string=query)
    assert response.status_code == 200
    assert response.json["executions"][0]["execution_id"] == workflow_execution_id(
        workspaces["fictional-group"]["workflow"], "run", "report-node",
    )
    assert client.get(base, query_string={**query, "group_id": "foreign"}).status_code == 403
    state["group_role"] = None
    assert client.get(base, query_string=query).status_code == 403


@pytest.mark.parametrize("scope", ["user", "group"])
def test_missing_exact_record_is_metadata_not_a_missing_resource_or_result(api, monkeypatch, scope):
    client, state, workspaces = api
    group_id = "fictional-group" if scope == "group" else None
    workspace = workspaces[group_id]
    if group_id:
        state["user"] = "member"
    query = {"group_id": group_id} if group_id else {}
    base = f"/api/{scope}/workflows/workflow/runs/run/executions"
    for node_id in ("root", "report-node"):
        execution_id = workflow_execution_id(workspace["workflow"], "run", node_id, [])
        workspace["container"].items.pop(("run", journal_record_id("execution", execution_id)), None)
    workspace["workflow"]["tasks"][0]["instructions"] = "Changed after this frozen run."
    workspace["workflow"]["reference_inputs"] = []
    monkeypatch.setattr(workspace["container"], "query_items", lambda **kwargs: pytest.fail("Exact lookup scanned history"))
    for node_id in ("root", "report-node"):
        response = client.get(base, query_string={**query, "node_id": node_id, "iteration_path": "[]"})
        assert response.status_code == 200
        assert response.json == {"executions": [], "next_cursor": None, "total_count": 0}
        assert response.cache_control.no_store and response.cache_control.private
        assert ("source", "fictional-document") in state["reads"]
    state["source"] = False
    selectors = {**query, "node_id": "report-node", "iteration_path": "[]"}
    response = client.get(base, query_string=selectors)
    assert response.status_code == 403 and "executions" not in response.json
    state["source"] = True
    assert client.get(base.replace("/runs/run/", "/runs/foreign/"), query_string=selectors).status_code == 404
    assert client.get(base, query_string={**selectors, "node_id": "foreign-node"}).status_code == 400
    workspace["container"].items = {
        key: value for key, value in workspace["container"].items.items() if key[1] == CONTROL_ID
    }
    response = client.get(base, query_string=selectors)
    assert response.status_code == 404 and "executions" not in response.json


def test_all_flow_routes_enforce_login_user_and_feature_gates(api):
    client, state, _ = api
    requests = [
        ("get", "/api/user/workflows/workflow/flow", {}),
        ("get", "/api/user/workflows/workflow/runs/run/flow", {}),
        ("post", "/api/user/workflows/flow-preview", {"json": {"definition": definition()}}),
        ("get", "/api/group/workflows/workflow/flow?group_id=fictional-group", {}),
        ("get", "/api/group/workflows/workflow/runs/run/flow?group_id=fictional-group", {}),
        ("post", "/api/group/workflows/flow-preview?group_id=fictional-group", {"json": {"definition": definition()}}),
    ]
    for field, code in (("login", 401), ("user_role", 403)):
        state[field] = False
        for method, path, arguments in requests:
            assert getattr(client, method)(path, **arguments).status_code == code
        state[field] = True
    state["settings"].update(allow_user_workflows=False, allow_group_workflows=False)
    for method, path, arguments in requests:
        assert getattr(client, method)(path, **arguments).status_code == 403


def test_blueprint_cache_policy_covers_all_flow_and_execution_overlay_denials(api):
    client, state, _ = api
    rules = [rule for rule in client.application.url_map.iter_rules() if rule.endpoint.startswith("backend_workflows.")]
    assert len(rules) == 26
    for gate, status in (("login", 401), ("user_role", 403)):
        state[gate] = False
        for rule in rules:
            path = rule.rule
            for parameter, value in (
                ("workflow_id", "workflow"), ("run_id", "run"), ("execution_id", "execution"),
                ("int:attempt", "1"), ("int:iteration", "0"),
            ):
                path = path.replace(f"<{parameter}>", value)
            response = client.open(path, method="GET" if "GET" in rule.methods else "POST")
            assert response.status_code == status, rule.endpoint
            assert response.cache_control.no_store and response.cache_control.private, rule.endpoint
        state[gate] = True


def test_inspection_cache_policy_does_not_change_other_workflow_endpoints(api):
    client, _, _ = api
    client.application.add_url_rule(
        "/api/user/workflows/editor-options",
        endpoint="backend_workflows.get_user_workflow_editor_options",
        view_func=lambda: (jsonify({"options": []}), 200, {"Cache-Control": "private, max-age=60"}),
    )
    response = client.get("/api/user/workflows/editor-options")
    assert response.status_code == 200 and response.headers["Cache-Control"] == "private, max-age=60"
