# test_v2_control_center_public_workspaces.py
"""
Functional tests for V2 Control Center public workspace management.
Version: 0.261.283
Implemented in: 0.261.283

Execute real query builders, guarded status writes, authentication, approval
creation and dispatch against isolated Cosmos containers. No Azure calls.
"""

import ast
import copy
import csv
import importlib.util
import logging
import sys
from functools import wraps
from io import StringIO
from pathlib import Path

import pytest
from flask import Blueprint, Flask, Response, jsonify, request, session
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from test_control_center_public_writers import _build_env, seed_workspace
from test_support.app_source import definitions
from test_support.agent_delegation import module_stub


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
spec = importlib.util.spec_from_file_location("workspace_queries", APP / "functions_control_center_public_workspaces.py")
module = importlib.util.module_from_spec(spec)
# This pure module's sibling import is loaded without initializing the Azure config.
group_spec = importlib.util.spec_from_file_location("functions_control_center_groups", APP / "functions_control_center_groups.py")
group_module = importlib.util.module_from_spec(group_spec)
group_spec.loader.exec_module(group_module)


class WorkspaceQueries:
    """Model emitted WHERE/ORDER/OFFSET queries, refusing unbounded row fetches."""

    def __init__(self, container):
        self.container = container
        self.queries = []

    def read_item(self, **kwargs):
        return self.container.read_item(**kwargs)

    def query_items(self, query, parameters=None, **kwargs):
        self.queries.append((query, parameters))
        values = {item["name"]: item["value"] for item in parameters or []}
        rows = [copy.deepcopy(row) for row in self.container.records.values()]
        # FakeContainer keys are opaque; values are raw workspace documents.
        def matches(row):
            if "@search" in values and values["@search"] not in f"{row.get('name', '')} {row.get('description', '')}".lower():
                return False
            if "@owner" in values:
                owner = row.get("owner") or {}
                text = " ".join(str(owner.get(key, "")) for key in ("userId", "displayName", "email")) if isinstance(owner, dict) else owner
                if values["@owner"] not in text.lower():
                    return False
            if "@status" in values and (row.get("status") or "active") != values["@status"]:
                return False
            if "@known_statuses" in values and (row.get("status") or "active") in ["active", "locked", "upload_disabled"]:
                return False
            return row["id"] not in values.get("@excluded", [])
        rows = [row for row in rows if matches(row)]
        field = next((path for path in module.WORKSPACE_SORTS.values() if f"IS_DEFINED({path})" in query), None)
        def field_value(row, path):
            value = row
            for key in path.removeprefix("c.").split("."):
                value = value.get(key) if isinstance(value, dict) else None
            return value
        if field:
            recorded = "AND NOT (IS_DEFINED" not in query
            rows = [row for row in rows if (field_value(row, field) is not None) == recorded]
        if "COUNT(1)" in query:
            return [len(rows)]
        if "TOP 501" in query:
            return [{"id": row["id"]} for row in rows[:501]]
        assert "OFFSET @offset LIMIT @limit" in query, query
        sort_field = query.split("ORDER BY ")[1].split(" ")[0]
        rows.sort(key=lambda row: field_value(row, sort_field), reverse=f"{sort_field} DESC" in query)
        rows = rows[values["@offset"]:values["@offset"] + values["@limit"]]
        return rows


class Documents:
    def __init__(self):
        self.deleted = []

    def query_items(self, query, parameters=None, **kwargs):
        if "COUNT" in query:
            return [2]
        assert "c.public_workspace_id = @workspace_id" in query
        return [{"id": "doc-1"}, {"id": "doc-2"}]


class Activity:
    def __init__(self):
        self.records = []

    def query_items(self, query, **kwargs):
        if "SUM" in query:
            return [120]
        assert "TOP 20" in query
        return [{"id": "event-1", "activity_type": "public_workspace_status_change", "description": "=danger"}]

    def create_item(self, body):
        self.records.append(body)


@pytest.fixture
def routes(monkeypatch):
    monkeypatch.setitem(sys.modules, "functions_control_center_groups", group_module)
    spec.loader.exec_module(module)
    env = _build_env()
    monkeypatch.setitem(sys.modules, "functions_activity_logging", env.activity_stub)
    seed_workspace(env, workspace_id="public-1", status=None, metrics={
        "calculated_at": "2026-10-07T00:00:00Z", "document_metrics": {"total_documents": 3},
    })
    seed_workspace(env, workspace_id="public-2", status="locked")
    settings = {"require_member_of_control_center_admin": False, "require_member_of_control_center_dashboard": True,
                "enable_public_workspaces": True, "enable_retention_policy_public": True}
    auth = {"wraps": wraps, "session": session, "request": request, "jsonify": jsonify,
            "get_settings": lambda: settings, "debug_print": lambda *a, **k: None}
    exec(compile(definitions("functions_authentication.py", {
        "login_required", "control_center_required", "get_control_center_capabilities",
    }), "functions_authentication.py", "exec"), auth)
    blueprint = Blueprint("workspace_test", __name__)
    queries, docs, activity = WorkspaceQueries(env.workspaces), Documents(), Activity()
    approvals, executions = [], []
    def approval(**kwargs):
        item = {"id": f"approval-{len(approvals)}", **kwargs}
        approvals.append(item)
        return item
    ns = dict(env.route_ns)
    ns.update({name: getattr(module, name) for name in (
        "WORKSPACE_EXPORT_LIMIT", "parse_workspace_filters", "query_workspaces",
        "select_workspace_ids", "workspace_members", "workspace_row",
    )})
    ns.update({
        "bp": blueprint, "request": request, "session": session, "jsonify": jsonify, "Response": Response,
        "StringIO": StringIO, "csv": csv, "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
        "login_required": auth["login_required"], "control_center_required": auth["control_center_required"],
        "GroupRequestError": group_module.GroupRequestError, "validate_group_id": group_module.validate_group_id,
        "validate_group_status_payload": group_module.validate_group_status_payload,
        "cosmos_public_workspaces_container": queries, "cosmos_public_documents_container": docs,
        "cosmos_activity_logs_container": activity, "get_settings": lambda: settings,
        "create_approval_request": approval,
        "TYPE_TAKE_OWNERSHIP": "take_ownership", "TYPE_TRANSFER_OWNERSHIP": "transfer_ownership",
        "TYPE_DELETE_DOCUMENTS": "delete_documents", "TYPE_DELETE_GROUP": "delete_group",
        "TYPE_DELETE_USER_DOCUMENTS": "delete_user_documents", "TYPE_WARN_USER": "warn",
        "TYPE_SUSPEND_USER": "suspend", "TYPE_BLOCK_USER": "block", "is_m365_approval": lambda _: False,
        "mark_approval_executed": lambda **kw: executions.append(kw),
        "delete_document_chunks": lambda **kw: docs.deleted.append(("chunks", kw)),
        "delete_document": lambda **kw: docs.deleted.append(("metadata", kw)),
    })
    exec(compile(definitions("functions_public_workspaces.py", {"get_user_role_in_public_workspace"}),
                 "roles", "exec"), ns)
    routes_to_extract = {
        "api_v2_control_center_public_workspaces", "api_v2_control_center_public_workspace_detail",
        "api_v2_control_center_public_workspaces_bulk_status", "api_v2_control_center_public_workspace_status",
        "api_v2_control_center_public_workspaces_export", "api_update_public_workspace_status",
        "api_admin_add_workspace_member", "api_admin_take_workspace_ownership", "api_update_public_workspace_ownership",
        "api_delete_public_workspace_documents_admin", "api_delete_public_workspace_admin",
        "_execute_approved_action", "_execute_delete_public_workspace", "_execute_delete_public_workspace_documents",
    }
    source = definitions("route_backend_control_center.py", {"_control_center_csv_safe_cell"},
                         register="register_route_backend_control_center", nested=routes_to_extract)
    exec(compile(source, "route_backend_control_center.py", "exec"), ns)
    monkeypatch.setitem(sys.modules, "functions_public_workspaces", module_stub(
        "functions_public_workspaces",
        PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE=env.ws_ns["PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE"],
        PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE=env.ws_ns["PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE"],
        PublicWorkspaceDocumentWriteConflict=env.ws_ns["PublicWorkspaceDocumentWriteConflict"],
        find_public_workspace_by_id=lambda identifier: env.workspaces.get(identifier, identifier),
        get_user_role_in_public_workspace=ns["get_user_role_in_public_workspace"],
        update_public_workspace_document_with_etag_guard=env.ws_ns["update_public_workspace_document_with_etag_guard"],
    ))
    ns.update({"get_current_user_id": lambda: session["user"]["oid"], "user_required": lambda function: function})
    exec(compile(definitions("route_backend_retention_policy.py", set(),
                             register="register_route_backend_retention_policy",
                             nested={"update_public_workspace_retention_settings"}), "retention", "exec"), ns)
    app = Flask("v2_workspace")
    app.config.update(TESTING=True, SECRET_KEY="isolated-key")
    app.register_blueprint(blueprint)
    client = app.test_client()
    with client.session_transaction() as state:
        state["user"] = {"oid": "cc-admin", "roles": ["Admin"], "preferred_username": "cc@example.test"}
    yield env, client, ns, queries, approvals, executions, docs


def test_query_filters_pagination_and_missing_status_active(routes):
    _, client, _, queries, _, _, _ = routes
    result = client.get("/api/v2/control-center/public-workspaces?status=active&search=public&owner=owner&per_page=1")
    assert result.status_code == 200
    data = result.get_json()
    assert data["pagination"]["total_items"] == 1
    assert data["workspaces"][0]["id"] == "public-1"
    assert data["workspaces"][0]["tokens"] is None
    assert len(queries.queries) == 3
    for query, params in queries.queries:
        assert "NOT IS_DEFINED(c.status) OR IS_NULL(c.status)" in query
        assert {"name": "@search", "value": "public"} in params
    page = client.get("/api/v2/control-center/public-workspaces?per_page=1&page=2")
    assert page.get_json()["pagination"]["page"] == 2
    assert any({"name": "@offset", "value": 1} in params for _, params in queries.queries)


@pytest.mark.parametrize("query", ["status=bad", "sort=password", "direction=bad", "page=0",
                                  "page=-1", "page=100001", "per_page=251", "per_page=x",
                                  "search=" + "a" * 201, "owner=" + "a" * 201])
def test_invalid_requests_do_not_query(routes, query):
    _, client, _, queries, _, _, _ = routes
    result = client.get(f"/api/v2/control-center/public-workspaces?{query}")
    assert result.status_code == 400
    assert not queries.queries


def test_sort_recorded_values_then_missing_without_dropping_workspaces(routes):
    _, client, _, _, _, _, _ = routes
    for direction in ("asc", "desc"):
        result = client.get(f"/api/v2/control-center/public-workspaces?sort=documents&direction={direction}&per_page=1&page=2")
        assert result.status_code == 200
        assert result.get_json()["workspaces"][0]["id"] == "public-2"
        assert result.get_json()["pagination"]["total_items"] == 2
    owner = client.get("/api/v2/control-center/public-workspaces?sort=owner")
    assert owner.status_code == 200


def test_unknown_status_is_inactive_and_search_is_bound_not_interpolated(routes):
    env, client, _, queries, _, _, _ = routes
    workspace = env.workspaces.get("public-2", "public-2")
    workspace["status"] = "legacy-unknown"
    env.workspaces.seed(workspace)
    result = client.get("/api/v2/control-center/public-workspaces?status=inactive")
    assert result.status_code == 200
    assert result.get_json()["workspaces"][0]["status"] == "inactive"
    malicious = "' OR 1=1 --"
    searched = client.get("/api/v2/control-center/public-workspaces", query_string={"search": malicious})
    assert searched.status_code == 200 and searched.get_json()["pagination"]["total_items"] == 0
    assert all(malicious not in query for query, _ in queries.queries)
    assert any({"name": "@search", "value": malicious.lower()} in params for _, params in queries.queries)


@pytest.mark.parametrize("path,method", [
    ("", "GET"), ("/public-1", "GET"), ("/export.csv", "GET"),
    ("/public-1/status", "PUT"), ("/bulk-status", "POST"),
])
@pytest.mark.parametrize("user,status", [(None, 401), ({"oid": "reader", "roles": ["ControlCenterDashboardReader"]}, 403)])
def test_admin_only(routes, path, method, user, status):
    _, client, _, queries, _, _, _ = routes
    with client.session_transaction() as state:
        state.clear()
        if user:
            state["user"] = user
    result = client.open("/api/v2/control-center/public-workspaces" + path, method=method, json={})
    assert result.status_code == status
    assert not queries.queries


def test_details_roles_and_live_totals_without_raw_settings(routes):
    _, client, _, _, _, _, _ = routes
    result = client.get("/api/v2/control-center/public-workspaces/public-1")
    assert result.status_code == 200
    data = result.get_json()
    assert data["documents_summary"]["count"] == 2 and data["tokens"] == 120
    assert {member["role"] for member in data["members"]} == {"Owner", "Admin", "DocumentManager"}
    assert not data["permissions"]["can_edit_members"]
    assert not data["retention"]["can_edit"]
    assert "settings" not in data and "model_endpoints" not in data


def test_bulk_real_writer_partial_results_and_validation_before_writes(routes):
    env, client, _, _, _, _, _ = routes
    invalid = client.post("/api/v2/control-center/public-workspaces/bulk-status", json={"workspace_ids": ["public-1"], "status": "locked"})
    assert invalid.status_code == 400
    result = client.post("/api/v2/control-center/public-workspaces/bulk-status", json={
        "workspace_ids": ["public-1", "missing"], "status": "locked", "reason": "Review",
    })
    assert result.status_code == 200
    assert result.get_json()["success_count"] == 1 and result.get_json()["failed_count"] == 1
    stored = env.workspaces.get("public-1", "public-1")
    assert stored["statusHistory"][-1]["reason"] == "Review"
    assert len(env.status_logs) == 1
    unchanged = client.put("/api/v2/control-center/public-workspaces/public-1/status", json={"status": "locked", "reason": "Review"})
    assert unchanged.status_code == 200 and len(env.status_logs) == 1


def test_filter_selection_cap_and_exclusions_precede_writes(routes):
    env, client, _, queries, _, _, _ = routes
    excluded = module.select_workspace_ids(queries, {"filter": {}, "exclude_ids": ["public-1"]})
    assert excluded == ["public-2"]
    for index in range(2, 502):
        seed_workspace(env, workspace_id=f"w-{index}", status="active")
    capped = client.post("/api/v2/control-center/public-workspaces/bulk-status", json={
        "filter": {}, "status": "active",
    })
    assert capped.status_code == 400
    assert not env.status_logs
    assert any("TOP 501" in query for query, _ in queries.queries)
    selected = module.select_workspace_ids(queries, {"filter": {"status": "locked"}, "exclude_ids": []})
    assert selected == ["public-2"]
    with pytest.raises(group_module.GroupRequestError):
        module.select_workspace_ids(queries, {"filter": {"arbitrary": "field"}})
    with pytest.raises(group_module.GroupRequestError):
        module.select_workspace_ids(queries, {"workspace_ids": ["public-1"] * 501})


@pytest.mark.parametrize("payload", [
    {"workspace_ids": ["../admin"], "status": "active"},
    {"workspace_ids": [], "status": "active"},
    {"workspace_ids": ["public-1"], "filter": {}, "status": "active"},
    {"filter": {}, "exclude_ids": "public-1", "status": "active"},
    {"workspace_ids": ["public-1"], "status": "locked", "reason": "x" * 2001},
])
def test_invalid_bulk_payloads_never_write(routes, payload):
    env, client, _, _, _, _, _ = routes
    result = client.post("/api/v2/control-center/public-workspaces/bulk-status", json=payload)
    assert result.status_code == 400 and not env.status_logs


def test_safe_filtered_csv_and_failures(routes, monkeypatch):
    env, client, _, queries, _, _, _ = routes
    row = env.workspaces.get("public-1", "public-1")
    row["name"] = " =HYPERLINK(\"bad\")"
    env.workspaces.seed(row)
    result = client.get("/api/v2/control-center/public-workspaces/export.csv?status=active")
    assert result.status_code == 200
    cells = list(csv.reader(StringIO(result.get_data(as_text=True))))
    assert len(cells) == 2 and cells[1][1].startswith("'")
    assert cells[1][6] == ""
    def fail(**kwargs):
        raise RuntimeError("sensitive-credential")
    monkeypatch.setattr(queries, "query_items", fail)
    failed = client.get("/api/v2/control-center/public-workspaces")
    assert failed.status_code == 500 and "sensitive-credential" not in failed.get_data(as_text=True)


@pytest.mark.parametrize("suffix,kind", [("", "delete_group"), ("/documents", "delete_documents"), ("/take-ownership", "take_ownership")])
def test_existing_approval_creation_does_not_mutate_workspace(routes, suffix, kind):
    env, client, _, _, approvals, _, _ = routes
    method = "POST" if suffix == "/take-ownership" else "DELETE"
    result = client.open(f"/api/admin/control-center/public-workspaces/public-1{suffix}", method=method, json={"reason": "Governance"})
    assert result.status_code in (200, 201)
    assert result.get_json()["approval_id"]
    assert approvals[-1]["request_type"] == kind
    assert approvals[-1]["metadata"]["entity_type"] == "workspace"
    assert approvals[-1]["group_id"] == "public-1"
    assert env.workspaces.get("public-1", "public-1") is not None


def test_actual_approval_dispatch_deletes_public_scope_not_groups(routes):
    env, client, ns, queries, approvals, executions, docs = routes
    created = client.delete("/api/admin/control-center/public-workspaces/public-1", json={"reason": "Governance"})
    assert created.status_code == 200
    # Query wrapper forwards only the actual public-container deletion.
    queries.delete_item = env.workspaces.delete_item
    approval = {**approvals[-1], "requester_id": "cc-admin", "requester_email": "cc@example.test"}
    result = ns["_execute_approved_action"](approval, "other-admin", "other@example.test", "Other")
    assert result["success"] is True
    assert executions[-1]["success"] is True and executions[-1]["group_id"] == "public-1"
    assert all(item["public_workspace_id"] == "public-1" for _, item in docs.deleted)
    assert len(docs.deleted) == 4
    with pytest.raises(CosmosResourceNotFoundError):
        env.workspaces.read_item(item="public-1", partition_key="public-1")
    assert env.workspaces.get("public-2", "public-2") is not None


def test_existing_member_add_and_transfer_validate_recorded_roles(routes):
    env, client, _, _, approvals, _, _ = routes
    added = client.post("/api/admin/control-center/public-workspaces/public-1/add-member", json={
        "userId": "new-manager", "displayName": "New", "email": "new@example.test",
        "role": "document_manager", "source": "csv",
    })
    assert added.status_code == 200 and not added.get_json()["skipped"]
    workspace = env.workspaces.get("public-1", "public-1")
    assert any(member["userId"] == "new-manager" for member in workspace["documentManagers"])
    env.user_settings.seed({"id": "new-manager", "email": "new@example.test", "display_name": "New"})
    transferred = client.put("/api/admin/control-center/public-workspaces/public-1/ownership",
                             json={"newOwnerId": "new-manager", "reason": "New steward"})
    assert transferred.status_code == 201 and transferred.get_json()["requires_approval"]
    assert approvals[-1]["metadata"]["new_owner_id"] == "new-manager"
    assert approvals[-1]["metadata"]["entity_type"] == "workspace"
    workspace = env.workspaces.get("public-1", "public-1")
    assert workspace["owner"]["userId"] == "owner"


def test_existing_public_retention_requires_membership_and_rejects_default(routes):
    env, client, _, _, _, _, _ = routes
    base = "/api/retention-policy/public/public-1"
    denied = client.post(base, json={"document_retention_days": 90})
    assert denied.status_code == 403
    with client.session_transaction() as state:
        state["user"] = {**state["user"], "oid": "owner"}
    inherited = client.post(base, json={"document_retention_days": "default"})
    assert inherited.status_code == 400
    saved = client.post(base, json={"document_retention_days": "90"})
    assert saved.status_code == 200
    workspace = env.workspaces.get("public-1", "public-1")
    assert workspace["retention_policy"]["document_retention_days"] == 90
    unlimited = client.post(base, json={"document_retention_days": "none"})
    assert unlimited.status_code == 200
