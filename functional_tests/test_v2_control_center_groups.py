# test_v2_control_center_groups.py
"""
Functional tests for V2 Control Center Groups.
Version: 0.261.281
Implemented in: 0.261.281

Run real filters and routes over isolated Cosmos services and the real guarded
group writer. Cover selection caps before writes, audit parity, detail projections,
admin-only access, snapshot expiry, safe exports and approval-only actions.
"""

import ast
import copy
import importlib.util
import time
from contextlib import contextmanager
from io import StringIO
from pathlib import Path

import pytest
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from flask import Blueprint, Flask, Response, jsonify, request, session

from test_support.control_center_group_harness import control_center_group_environment
from test_support.versioning import assert_app_version_at_least


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
spec = importlib.util.spec_from_file_location("v2_group_inventory", APP / "functions_control_center_groups.py")
inventory_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory_module)
ROUTES = {
    "api_v2_control_center_groups", "api_v2_control_center_group_detail",
    "api_v2_control_center_groups_bulk_status", "api_v2_control_center_group_status",
    "api_v2_control_center_groups_export", "api_delete_group_admin",
    "api_delete_group_documents_admin", "api_admin_take_group_ownership",
    "api_admin_transfer_group_ownership",
}


class InventoryGroups:
    def __init__(self, env):
        self.env = env
        self.queries = []

    def query_items(self, query, **kwargs):
        self.queries.append(query)
        assert "SELECT c.id, c.name" in query and "FROM c" in query
        fields = ("id", "name", "description", "owner", "users", "admins", "documentManagers",
                  "status", "createdDate", "metrics")
        return [{key: copy.deepcopy(value) for key, value in row.items() if key in fields}
                for row in self.env.groups.records.values()]

    def read_item(self, **kwargs):
        return self.env.groups.read_item(**kwargs)


class InventoryDocuments:
    def __init__(self):
        self.queries = []

    def query_items(self, query, **kwargs):
        self.queries.append(query)
        assert "c.type = 'document_metadata'" in query
        assert "COUNT(1)" in query and "GROUP BY c.group_id" in query
        return [{"group_id": "group-1", "total": 2}]


class InventoryActivity:
    def __init__(self):
        self.queries = []

    def query_items(self, query, **kwargs):
        self.queries.append(query)
        if "SUM(c.usage.total_tokens)" in query:
            assert "GROUP BY c.workspace_context.group_id" in query
            return [{"group_id": "group-1", "total": 120}]
        if "MAX(c.timestamp)" in query:
            assert "IS_STRING(c.group_id) AND c.group_id != ''" in query
            assert "IS_STRING(c.group.group_id) AND c.group.group_id != ''" in query
            return [{"group_id": "group-1", "last_activity": "2026-10-06T00:00:00Z"}]
        if "TOP 20" in query:
            assert "c.group_id = @group_id" in query and "c.workspace_context.group_id = @group_id" in query
            return [{"id": "event-1", "activity_type": "group_status_change", "timestamp": "2026-10-06T00:00:00Z"}]
        raise AssertionError(f"Unexpected activity query: {query}")


@contextmanager
def group_routes():
    with control_center_group_environment() as env:
        env.seed_group("group-1", name="Research")
        env.seed_group("group-2", name="Archive", status="locked")
        blueprint = Blueprint("v2_cc_groups_test", __name__)
        ns = dict(env.cc.namespace)
        ns.update({name: getattr(inventory_module, name) for name in (
            "GROUP_SNAPSHOT_TTL", "GroupRequestError", "filter_group_inventory", "group_members", "group_row",
            "load_group_inventory", "parse_group_filters", "select_group_bulk_ids",
            "validate_group_id", "validate_group_status_payload",
        )})
        groups, documents, activity = InventoryGroups(env), InventoryDocuments(), InventoryActivity()
        approvals = []
        def create_approval_request(**kwargs):
            approvals.append(kwargs)
            return {"id": f"approval-{len(approvals)}"}
        ns.update({
            "bp": blueprint, "Response": Response, "StringIO": StringIO, "time": time,
            "csv": __import__("csv"), "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
            "cosmos_groups_container": groups, "cosmos_group_documents_container": documents,
            "cosmos_activity_logs_container": activity, "get_settings": env.get_settings,
            "get_user_role_in_group": env.modules.group.get_user_role_in_group,
            "create_approval_request": create_approval_request,
            "CONTROL_CENTER_MANAGEMENT_DEFAULT_PER_PAGE": 25, "CONTROL_CENTER_MANAGEMENT_MAX_PER_PAGE": 250,
        })
        source = APP / "route_backend_control_center.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        helpers = {"_control_center_group_inventory", "parse_control_center_management_pagination",
                   "get_control_center_total_pages", "clamp_control_center_page", "_control_center_csv_safe_cell"}
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in helpers]
        nodes += [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in ROUTES]
        assert {node.name for node in nodes} == helpers | ROUTES
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), ns)
        app = Flask("v2_control_center_groups_test")
        app.config.update(TESTING=True, SECRET_KEY="isolated-test-key")
        app.register_blueprint(blueprint)
        client = app.test_client()
        def sign_in(user=None):
            with client.session_transaction() as state:
                state.clear()
                if user is not None:
                    state["user"] = user
        sign_in(env.cc.admin)
        yield env, client, ns, (groups, documents, activity), approvals, sign_in


@pytest.fixture
def routes():
    with group_routes() as result:
        yield result


def test_list_filters_sort_paging_and_batched_cache(routes):
    _, client, ns, services, _, _ = routes
    response = client.get("/api/v2/control-center/groups?sort=tokens&direction=desc&per_page=1")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["groups"][0]["name"] == "Research"
    assert payload["pagination"]["total_items"] == 2
    assert payload["metrics_freshness"]["ttl_seconds"] == 90
    assert sum(len(service.queries) for service in services) == 4
    cached_response = client.get("/api/v2/control-center/groups?status=active&owner=olive&has_documents=yes&members_min=4&created_from=2026-09-01&activity_to=2026-10-07")
    assert [row["id"] for row in cached_response.get_json()["groups"]] == ["group-1"]
    assert sum(len(service.queries) for service in services) == 4
    next_page = client.get("/api/v2/control-center/groups?sort=name&per_page=1&page=2")
    assert next_page.get_json()["groups"][0]["id"] == "group-1"
    refreshed = client.get("/api/v2/control-center/groups?force_refresh=1")
    assert refreshed.status_code == 200
    assert sum(len(service.queries) for service in services) == 8
    ns["_control_center_group_snapshot_cache"]["inventory"]["expires_at"] = 0
    expired = client.get("/api/v2/control-center/groups")
    assert expired.status_code == 200
    assert sum(len(service.queries) for service in services) == 12


@pytest.mark.parametrize("query", [
    "status=bogus", "sort=settings", "direction=sideways", "has_documents=maybe",
    "members_min=-1", "members_min=8&members_max=1", "created_from=2026-02-30",
    "activity_from=2026-10-08&activity_to=2026-10-01", "owner=" + "x" * 201,
])
def test_invalid_filters_do_not_query_storage(routes, query):
    _, client, _, services, _, _ = routes
    response = client.get(f"/api/v2/control-center/groups?{query}")
    assert response.status_code == 400
    assert not any(service.queries for service in services)


@pytest.mark.parametrize("path", ["/api/v2/control-center/groups",
                                "/api/v2/control-center/groups/group-1",
                                "/api/v2/control-center/groups/export.csv"])
def test_inventory_failures_are_safe_not_validation_messages(routes, monkeypatch, path):
    _, client, _, services, _, _ = routes
    def fail_query(**kwargs):
        raise ValueError("secret-storage-credential")
    monkeypatch.setattr(services[1], "query_items", fail_query)
    response = client.get(path)
    assert response.status_code == 500
    assert "secret-storage-credential" not in response.get_data(as_text=True)


def test_missing_status_and_dates_and_all_sorts_are_consistent():
    first = inventory_module.group_row({"id": "a", "name": "Zulu", "owner": {"id": "person"},
                                        "users": [], "status": None}, 0, 0, None)
    second = inventory_module.group_row({"id": "b", "name": "Alpha", "owner": {"displayName": "B"}},
                                       2, 10, "2026-10-06T00:00:00Z")
    assert first["status"] == "active" and first["members"] == 1
    for field in inventory_module.GROUP_SORTS:
        result = inventory_module.filter_group_inventory([first, second], inventory_module.parse_group_filters({"sort": field}))
        assert len(result) == 2
    result = inventory_module.filter_group_inventory([first, second], inventory_module.parse_group_filters({"activity_to": "2026-10-07"}))
    assert [row["id"] for row in result] == ["b"]


def test_detail_shape_is_allowlisted_and_fresh_membership_has_roles(routes):
    env, client, _, _, _, _ = routes
    response = client.get("/api/v2/control-center/groups/group-1")
    data = response.get_json()
    assert response.status_code == 200
    assert {member["role"] for member in data["members"]} == {"Owner", "Admin", "DocumentManager", "User"}
    assert data["documents_summary"]["count"] == 2 and data["tokens"] == 120
    assert data["activity"][0]["id"] == "event-1"
    assert data["status_history"] == []
    assert not data["permissions"]["can_edit_members"]
    assert "sk-secret" not in response.get_data(as_text=True)
    assert "model_endpoints" not in response.get_data(as_text=True)
    assert data["retention"]["conversation_retention_days"] == "default"
    env.groups.records.clear()
    missing = client.get("/api/v2/control-center/groups/group-1")
    assert missing.status_code == 404


def test_bulk_reuses_legacy_writer_and_audits_each_transition_once(routes):
    env, client, _, _, _, _ = routes
    response = client.post("/api/v2/control-center/groups/bulk-status", json={
        "filter": {"status": "active"}, "exclude_ids": [], "status": "locked", "reason": "Review",
    })
    assert response.status_code == 200 and response.get_json()["success_count"] == 1
    stored = env.stored_group("group-1")
    assert stored["statusHistory"][-1]["reason"] == "Review"
    logs = [kwargs for name, _, kwargs in env.activity.calls if name == "log_group_status_change"]
    assert len(logs) == 1 and logs[0]["new_status"] == "locked"
    unchanged = client.put("/api/v2/control-center/groups/group-1/status", json={"status": "locked", "reason": "Review"})
    assert unchanged.status_code == 200
    assert len([entry for entry in env.activity.calls if entry[0] == "log_group_status_change"]) == 1


@pytest.mark.parametrize("data", [
    {"group_ids": ["group-1"], "status": "locked"},
    {"group_ids": ["group-1"], "status": "inactive", "reason": " "},
    {"group_ids": ["../admin"], "status": "active"},
    {"group_ids": ["group-1"] * 501, "status": "active"},
    {"group_ids": ["group-1"], "filter": {}, "status": "active"},
    {"filter": {"arbitrary": "field"}, "status": "active"},
    {"filter": {}, "exclude_ids": "group-1", "status": "active"},
    {"group_ids": [], "status": "active"},
])
def test_bulk_validation_precedes_all_writes(routes, data):
    env, client, _, _, _, _ = routes
    response = client.post("/api/v2/control-center/groups/bulk-status", json=data)
    assert response.status_code == 400
    assert not env.write_calls()


def test_filter_selection_cap_and_exclusions():
    rows = [inventory_module.group_row({"id": f"g-{index}"}, 0, 0, None) for index in range(501)]
    with pytest.raises(ValueError, match="500"):
        inventory_module.select_group_bulk_ids({"filter": {}}, lambda: {"rows": rows})
    selected = inventory_module.select_group_bulk_ids({"filter": {}, "exclude_ids": ["g-0"]}, lambda: {"rows": rows})
    assert len(selected) == 500 and "g-0" not in selected


def test_filter_selection_cap_is_enforced_by_route_before_writes(routes):
    env, client, _, _, _, _ = routes
    for index in range(499):
        env.seed_group(f"extra-{index}")
    response = client.post("/api/v2/control-center/groups/bulk-status", json={
        "filter": {}, "status": "locked", "reason": "Review",
    })
    assert response.status_code == 400
    assert not env.write_calls()


def test_bulk_partial_failures_are_explicit(routes):
    _, client, _, _, _, _ = routes
    response = client.post("/api/v2/control-center/groups/bulk-status", json={
        "group_ids": ["group-1", "missing"], "status": "inactive", "reason": "Archived",
    })
    data = response.get_json()
    assert data["success_count"] == 1 and data["failed_count"] == 1
    assert data["failed_groups"][0]["id"] == "missing"


@pytest.mark.parametrize("name", ["=1+1", " \t=1+1", "\r\n@SUM(A1:A2)"])
def test_exports_are_server_filtered_and_formula_safe(routes, name):
    env, client, _, _, _, _ = routes
    doc = env.stored_group("group-1")
    doc["name"] = name
    env.groups.seed(doc)
    response = client.get("/api/v2/control-center/groups/export.csv?has_documents=yes")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert f"'{name}" in text and "Archive" not in text


@pytest.mark.parametrize("user", [None, {"oid": "member-1", "roles": ["User"]},
                                 {"oid": "reader", "roles": ["ControlCenterDashboardReader"]}])
def test_readers_and_unauthenticated_callers_cannot_manage_groups(routes, user):
    env, client, _, services, _, sign_in = routes
    env.settings.update({"require_member_of_control_center_admin": True, "require_member_of_control_center_dashboard_reader": True})
    sign_in(user)
    for method, path, data in (
        ("GET", "/api/v2/control-center/groups", None),
        ("GET", "/api/v2/control-center/groups/group-1", None),
        ("GET", "/api/v2/control-center/groups/export.csv", None),
        ("PUT", "/api/v2/control-center/groups/group-1/status", {"status": "active"}),
        ("POST", "/api/v2/control-center/groups/bulk-status", {"group_ids": ["group-1"], "status": "active"}),
    ):
        response = client.open(path, method=method, json=data)
        assert response.status_code in (401, 403)
    assert not any(service.queries for service in services)
    assert not env.write_calls()


def test_destructive_and_ownership_actions_create_approvals_not_mutations(routes):
    env, client, _, _, approvals, _ = routes
    for method, suffix, data in (
        ("DELETE", "", {"reason": "Cleanup"}),
        ("POST", "/delete-documents", {"reason": "Cleanup"}),
        ("POST", "/take-ownership", {"reason": "Cover owner absence"}),
        ("POST", "/transfer-ownership", {"reason": "New owner", "newOwnerId": "member-1"}),
    ):
        response = client.open(f"/api/admin/control-center/groups/group-1{suffix}", method=method, json=data)
        assert response.status_code == 200 and response.get_json()["approval_id"]
    assert len(approvals) == 4
    assert not env.write_calls()
    assert env.stored_group("group-1")["owner"]["id"] == "owner-1"


def test_routes_have_explicit_admin_and_swagger_decorators():
    tree = ast.parse((APP / "route_backend_control_center.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ROUTES:
            decorators = [ast.unparse(decorator) for decorator in node.decorator_list]
            assert "login_required" in decorators and "control_center_required('admin')" in decorators
            assert "swagger_route(security=get_auth_security())" in decorators
    assert_app_version_at_least("0.261.281")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
