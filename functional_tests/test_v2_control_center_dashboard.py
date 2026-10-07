#!/usr/bin/env python3
# test_v2_control_center_dashboard.py
"""
Functional test for the V2 Control Center dashboard.
Version: 0.261.292
Implemented in: 0.261.280

This test validates status aggregation, period comparisons, bounded cache behavior,
dashboard-reader authorization, and the summary and insights route contracts.
Since 0.261.292 every dashboard query also passes the Cosmos query guard, because the
Python Cosmos SDK cannot run cross-partition GROUP BY or COUNT over DISTINCT values.
"""

import ast
import json
import logging
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from importlib.metadata import version as package_version
from pathlib import Path
from unittest.mock import patch

import werkzeug
from flask import Blueprint, Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
ROUTE = APP / "route_backend_control_center.py"
AUTH = APP / "functions_authentication.py"
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.cosmos_query_guard import cosmos_query_problems
from test_support.versioning import assert_app_version_at_least


DASHBOARD_HELPERS = {
    "_dashboard_cache_get", "_dashboard_cache_set", "_dashboard_metric", "_dashboard_status_counts",
    "_dashboard_parse_period", "_dashboard_query_count", "_dashboard_count_active_users",
    "_dashboard_activity_count", "_dashboard_document_upload_counts", "_dashboard_status_rows",
    "_dashboard_token_total", "_dashboard_document_failure_count", "_dashboard_document_failures",
    "_dashboard_token_value", "_dashboard_ranked", "_dashboard_token_insights",
    "_dashboard_activity_insights", "normalize_token_filter_value", "extract_token_filters",
    "append_token_usage_filters", "build_token_usage_query_context",
}
DASHBOARD_CONSTANTS = {
    "CONTROL_CENTER_DASHBOARD_CACHE_TTL_SECONDS", "CONTROL_CENTER_DASHBOARD_CACHE_MAX_ENTRIES",
    "CONTROL_CENTER_DASHBOARD_RANKING_LIMIT", "CONTROL_CENTER_DASHBOARD_RANKED_FIELDS",
    "DASHBOARD_INVALID_RANGE_ERROR", "_control_center_dashboard_cache",
}
DASHBOARD_ROUTES = {"api_v2_control_center_dashboard_summary", "api_v2_control_center_dashboard_insights"}


def _function_namespace(path, names, initial=None):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    wanted = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    assert {node.name for node in wanted} == set(names)
    namespace = initial or {}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def _dashboard_namespace(containers, extra=None):
    """Execute the real dashboard helpers, constants and routes against fake containers."""
    tree = ast.parse(ROUTE.read_text(encoding="utf-8"))
    constants = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id in DASHBOARD_CONSTANTS for target in node.targets)
    ]
    helpers = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in DASHBOARD_HELPERS
    ]
    routes = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in DASHBOARD_ROUTES
    ]
    assert {node.name for node in helpers} == DASHBOARD_HELPERS
    assert {node.name for node in routes} == DASHBOARD_ROUTES
    blueprint = Blueprint("v2_dashboard_test", __name__)
    events = []

    def passthrough(*_args, **_kwargs):
        return lambda function: function

    namespace = {
        "Counter": Counter, "defaultdict": defaultdict, "datetime": datetime, "timedelta": timedelta,
        "timezone": timezone, "json": json, "logging": logging, "time": time,
        "jsonify": jsonify, "request": request, "bp": blueprint,
        "swagger_route": passthrough, "get_auth_security": lambda: None,
        "login_required": lambda function: function, "control_center_required": passthrough,
        "log_event": lambda *args, **kwargs: events.append((args, kwargs)),
        **containers, **(extra or {}),
    }
    exec(compile(ast.Module(body=constants + helpers + routes, type_ignores=[]), str(ROUTE), "exec"), namespace)
    app = Flask("v2_dashboard_test")
    app.config.update(TESTING=True)
    app.register_blueprint(blueprint)
    # Flask 2.x test clients read werkzeug.__version__, which Werkzeug 3 no longer defines.
    with patch.object(werkzeug, "__version__", package_version("werkzeug"), create=True):
        namespace["client"] = app.test_client()
    namespace["events"] = events
    return namespace


class GuardedContainer:
    """Answer queries by shape after proving the Python SDK could run each one."""

    def __init__(self, respond):
        self.respond = respond
        self.queries = []
        self.problems = []

    def query_items(self, query, parameters=None, **kwargs):
        self.queries.append({"query": query, "parameters": parameters or [], **kwargs})
        problems = cosmos_query_problems(query)
        if problems:
            self.problems.extend(problems)
            raise RuntimeError("Cosmos rejected the query shape.")
        return iter(self.respond(query, {item["name"]: item["value"] for item in parameters or []}))


def test_group_and_workspace_status_counts_use_real_statuses():
    functions = _function_namespace(ROUTE, {"_dashboard_status_counts"})
    counts = functions["_dashboard_status_counts"](
        8,
        [
            {"status": "locked", "count": 2},
            {"status": "upload_disabled", "count": 1},
            {"status": "inactive", "count": 1},
            {"status": "active", "count": 1},
            {"status": "unexpected_legacy_value", "count": 1},
        ],
    )
    assert counts == {
        "active": 4,
        "locked": 2,
        "upload_disabled": 1,
        "inactive": 1,
    }
    public_counts = functions["_dashboard_status_counts"](
        5,
        [
            {"status": "active", "count": 1},
            {"status": "locked", "count": 1},
            {"status": "upload_disabled", "count": 1},
            {"status": "inactive", "count": 1},
            {"status": "unexpected_legacy_value", "count": 1},
        ],
        unknown_status="inactive",
    )
    assert public_counts == {
        "active": 1,
        "locked": 1,
        "upload_disabled": 1,
        "inactive": 2,
    }


def test_status_rows_are_tallied_without_group_by():
    container = GuardedContainer(lambda query, values: ["locked", "locked", None, " Inactive ", 7, "active"])
    functions = _function_namespace(
        ROUTE,
        {"_dashboard_status_rows", "_dashboard_status_counts"},
        {"Counter": Counter},
    )
    rows = functions["_dashboard_status_rows"](container)
    assert container.problems == []
    assert "SELECT VALUE c.status" in container.queries[0]["query"]
    assert container.queries[0]["enable_cross_partition_query"] is True
    assert sorted(rows, key=lambda row: str(row["status"])) == sorted([
        {"status": "locked", "count": 2}, {"status": None, "count": 1},
        {"status": " Inactive ", "count": 1}, {"status": "7", "count": 1},
        {"status": "active", "count": 1},
    ], key=lambda row: str(row["status"]))
    assert functions["_dashboard_status_counts"](9, rows) == {
        "active": 6, "locked": 2, "upload_disabled": 0, "inactive": 1,
    }
    assert functions["_dashboard_status_counts"](9, rows, unknown_status="inactive") == {
        "active": 5, "locked": 2, "upload_disabled": 0, "inactive": 2,
    }


def test_document_uploads_are_counted_by_recorded_workspace_type():
    records = [{"workspace_type": value} for value in (
        "personal", "personal", "personal", "group", "group", "public", None, "legacy",
    )] + [{}]

    def respond(query, values):
        assert "c.activity_type = 'document_creation'" in query
        assert {"@start_date", "@end_date"} <= set(values)
        if "@workspace_type" in values:
            return [sum(record.get("workspace_type") == values["@workspace_type"] for record in records)]
        return [len(records)]

    container = GuardedContainer(respond)
    functions = _function_namespace(
        ROUTE,
        {"_dashboard_document_upload_counts", "_dashboard_query_count"},
        {"cosmos_activity_logs_container": container},
    )
    counts = functions["_dashboard_document_upload_counts"](
        datetime(2026, 9, 1), datetime(2026, 9, 7, 23, 59, 59),
    )
    assert counts == {"personal": 6, "group": 2, "public": 1}
    assert list(counts) == ["personal", "group", "public"]
    assert container.problems == []
    assert all("SELECT VALUE COUNT(1)" in item["query"] for item in container.queries)
    assert all(item["enable_cross_partition_query"] is True for item in container.queries)


def test_active_users_are_counted_from_distinct_values():
    container = GuardedContainer(lambda query, values: ["user-1", "user-2", "user-1", "user-3"])
    functions = _function_namespace(
        ROUTE,
        {"_dashboard_count_active_users"},
        {"cosmos_activity_logs_container": container},
    )
    start = datetime(2026, 9, 1)
    end = datetime(2026, 9, 30, 23, 59, 59)
    assert functions["_dashboard_count_active_users"](start, end) == 3
    query = container.queries[0]
    assert container.problems == []
    assert "SELECT DISTINCT VALUE c.user_id" in query["query"]
    assert "c.activity_type = 'user_login'" in query["query"]
    assert query["parameters"] == [
        {"name": "@start_date", "value": start.isoformat()},
        {"name": "@end_date", "value": end.isoformat()},
    ]


def test_token_insights_total_models_and_rank_consumers():
    rows = [
        {"timestamp": "2026-09-01T10:00:00", "model": "gpt-4o", "tokens": 100,
         "user_id": "u1", "group_id": "g1"},
        {"timestamp": "2026-09-01T11:00:00", "model": "gpt-4o", "tokens": 50,
         "user_id": "u2", "public_workspace_id": "p1"},
        {"timestamp": "2026-09-02T09:00:00", "model": None, "tokens": 10.5, "user_id": "u1"},
        {"timestamp": "2026-09-02T09:30:00", "tokens": 5, "user_id": "u3"},
        {"timestamp": "2026-09-03T09:00:00", "model": "gpt-4o", "tokens": "bad", "user_id": "u2"},
        {"model": "gpt-4o", "tokens": 7, "group_id": "g1"},
        {"timestamp": "2026-09-03T09:00:00", "model": "gpt-4o", "tokens": True, "user_id": ""},
    ]
    container = GuardedContainer(lambda query, values: rows)
    namespace = _dashboard_namespace({"cosmos_activity_logs_container": container})
    by_model, top_tokens = namespace["_dashboard_token_insights"](
        datetime(2026, 9, 1), datetime(2026, 9, 30, 23, 59, 59), {"model": "gpt-4o"},
    )
    assert container.problems == []
    query = container.queries[0]
    assert "c.activity_type = 'token_usage'" in query["query"]
    assert "c.usage.model = @token_model" in query["query"]
    assert {"name": "@token_model", "value": "gpt-4o"} in query["parameters"]
    assert by_model == [
        {"date": "2026-09-01", "model": "gpt-4o", "tokens": 150},
        {"date": "2026-09-02", "model": "Unknown model", "tokens": 10},
        {"date": "2026-09-03", "model": "gpt-4o", "tokens": 0},
    ]
    assert top_tokens == {
        "users": [{"id": "u1", "tokens": 110}, {"id": "u2", "tokens": 50}, {"id": "u3", "tokens": 5}],
        "groups": [{"id": "g1", "tokens": 107}],
        "public_workspaces": [{"id": "p1", "tokens": 50}],
    }


def test_rankings_are_limited_and_ties_are_stable():
    namespace = _dashboard_namespace({})
    totals = {f"user-{index:02d}": 5 for index in range(12)}
    totals["user-99"] = 9
    ranked = namespace["_dashboard_ranked"](totals, "tokens")
    assert len(ranked) == namespace["CONTROL_CENTER_DASHBOARD_RANKING_LIMIT"] == 10
    assert ranked[0] == {"id": "user-99", "tokens": 9}
    assert [item["id"] for item in ranked[1:]] == [f"user-{index:02d}" for index in range(9)]


def test_activity_insights_rank_actors_and_total_each_login_hour():
    rows = [
        {"timestamp": "2026-09-07T09:15:00", "activity_type": "user_login", "user_id": "u1"},
        {"timestamp": "2026-09-14T09:45:00", "activity_type": "user_login", "user_id": "u2"},
        {"timestamp": "2026-09-15T23:05:00", "activity_type": "user_login", "user_id": "u1"},
        {"timestamp": "2026-09-15", "activity_type": "user_login", "user_id": "u1"},
        {"timestamp": "2026-09-16T10:00:00", "activity_type": "token_usage", "user_id": "u1",
         "group_id": "g1", "public_workspace_id": "p1"},
        {"timestamp": "2026-09-16T11:00:00", "activity_type": "document_creation", "user_id": "u3",
         "group_id": "g1"},
        {"activity_type": "user_login", "user_id": "u4"},
    ]
    container = GuardedContainer(lambda query, values: rows)
    namespace = _dashboard_namespace({"cosmos_activity_logs_container": container})
    top_activity, cells = namespace["_dashboard_activity_insights"](
        datetime(2026, 9, 1), datetime(2026, 9, 30, 23, 59, 59),
    )
    assert container.problems == []
    assert "c.timestamp >= @start_date" in container.queries[0]["query"]
    assert top_activity == {
        "users": [{"id": "u1", "activity_count": 4}, {"id": "u2", "activity_count": 1},
                  {"id": "u3", "activity_count": 1}, {"id": "u4", "activity_count": 1}],
        "groups": [{"id": "g1", "activity_count": 2}],
        "public_workspaces": [{"id": "p1", "activity_count": 1}],
    }
    # 2026-09-07 and 2026-09-14 are both Mondays: one cell totals both logins.
    assert cells == [
        {"weekday": 0, "hour": 9, "count": 2},
        {"weekday": 1, "hour": 23, "count": 1},
    ]


def _dashboard_store():
    statuses = {"groups": ["locked", None, "inactive"], "workspaces": ["locked", "legacy"]}
    token_rows = [
        {"timestamp": "2026-09-20T10:00:00", "model": "gpt-4o", "tokens": 40, "user_id": "u1", "group_id": "g1"},
    ]
    activity_rows = [
        {"timestamp": "2026-09-21T08:00:00", "activity_type": "user_login", "user_id": "u1"},
        {"timestamp": "2026-09-21T08:30:00", "activity_type": "token_usage", "user_id": "u1", "group_id": "g1"},
    ]

    def users(query, values):
        if "c.settings.access.status = 'deny'" in query:
            return [1]
        return [4]

    def statuses_for(key):
        def respond(query, values):
            if "SELECT VALUE c.status" in query:
                return statuses[key]
            return [len(statuses[key]) + 2]
        return respond

    def activity(query, values):
        if "SELECT DISTINCT VALUE c.user_id" in query:
            return ["u1", "u2"]
        if "SELECT VALUE SUM(c.usage.total_tokens)" in query:
            return [1234]
        if "document_creation" in query and "SELECT VALUE COUNT(1)" in query:
            return [{"group": 2, "public": 1}.get(values.get("@workspace_type"), 5)]
        if "SELECT VALUE COUNT(1)" in query:
            return [3]
        if "c.usage.total_tokens AS tokens" in query:
            return token_rows
        if "c.activity_type," in query:
            return activity_rows
        raise AssertionError(f"Unexpected activity query: {query}")

    return {
        "cosmos_user_settings_container": GuardedContainer(users),
        "cosmos_groups_container": GuardedContainer(statuses_for("groups")),
        "cosmos_public_workspaces_container": GuardedContainer(statuses_for("workspaces")),
        "cosmos_activity_logs_container": GuardedContainer(activity),
        "cosmos_user_documents_container": GuardedContainer(lambda query, values: [1]),
        "cosmos_group_documents_container": GuardedContainer(lambda query, values: [0]),
        "cosmos_public_documents_container": GuardedContainer(lambda query, values: [0]),
        "cosmos_approvals_container": GuardedContainer(lambda query, values: [2]),
    }


def test_summary_and_insights_routes_succeed_with_supported_queries():
    containers = _dashboard_store()
    namespace = _dashboard_namespace(containers)
    client = namespace["client"]

    summary = client.get("/api/v2/control-center/dashboard/summary?days=30")
    insights = client.get("/api/v2/control-center/dashboard/insights?days=30")
    problems = [problem for container in containers.values() for problem in container.problems]
    assert problems == [], problems
    assert summary.status_code == 200, namespace["events"]
    assert insights.status_code == 200, namespace["events"]

    body = summary.get_json()
    assert body["users"]["total"]["value"] == 4
    assert body["users"]["blocked"]["value"] == 1
    assert body["users"]["active"]["value"] == 2
    assert body["users"]["dau"]["value"] == 2
    assert body["groups"]["total"]["value"] == 5
    assert body["groups"]["by_status"]["locked"]["value"] == 1
    assert body["groups"]["by_status"]["inactive"]["value"] == 1
    assert body["groups"]["by_status"]["active"]["value"] == 3
    assert body["public_workspaces"]["by_status"]["inactive"]["value"] == 1
    assert body["public_workspaces"]["by_status"]["active"]["value"] == 2
    assert body["document_uploads"]["by_workspace_type"]["personal"]["value"] == 2
    assert body["document_uploads"]["total"]["value"] == 5
    assert body["tokens"]["value"] == 1234
    assert body["pending_approvals"]["value"] == 2
    assert body["document_processing_failures"]["value"] == 1
    assert body["cached"] is False

    data = insights.get_json()
    assert data["token_usage_by_model"] == [{"date": "2026-09-20", "model": "gpt-4o", "tokens": 40}]
    assert data["top_tokens"]["groups"] == [{"id": "g1", "tokens": 40}]
    assert data["top_activity"]["users"] == [{"id": "u1", "activity_count": 2}]
    assert data["login_heatmap"]["cells"] == [{"weekday": 0, "hour": 8, "count": 1}]

    query_count = sum(len(container.queries) for container in containers.values())
    assert client.get("/api/v2/control-center/dashboard/summary?days=30").get_json()["cached"] is True
    assert sum(len(container.queries) for container in containers.values()) == query_count


def test_dashboard_storage_failures_do_not_expose_details():
    containers = _dashboard_store()
    groups = containers["cosmos_groups_container"]
    groups.respond = lambda query, values: (_ for _ in ()).throw(RuntimeError("secret-storage-detail"))
    namespace = _dashboard_namespace(containers)
    response = namespace["client"].get("/api/v2/control-center/dashboard/summary?days=7&force_refresh=1")
    assert response.status_code == 500
    assert "secret-storage-detail" not in response.get_data(as_text=True)
    assert response.get_json() == {"error": "Failed to retrieve dashboard summary."}


def test_period_deltas_and_custom_range_boundaries():
    functions = _function_namespace(
        ROUTE,
        {"_dashboard_metric", "_dashboard_parse_period"},
        {"datetime": datetime, "timedelta": timedelta},
    )
    metric = functions["_dashboard_metric"]
    assert metric(15, 10) == {
        "value": 15,
        "delta": 5,
        "previous": 10,
        "percent_change": 50.0,
    }
    assert metric(7, 0)["percent_change"] is None
    assert metric(0, 0)["percent_change"] == 0.0
    assert metric(5)["delta"] is None

    parse_period = functions["_dashboard_parse_period"]
    start, end, previous_start, previous_end, days = parse_period({"days": "7"})
    assert days == 7
    assert (end - start).days == 6
    assert previous_end + timedelta(microseconds=1) == start
    assert (start - previous_start).days == 7

    custom_start, custom_end, _, _, custom_days = parse_period({
        "start_date": "2026-09-01",
        "end_date": "2026-09-30",
    })
    assert custom_start.date().isoformat() == "2026-09-01"
    assert custom_end.date().isoformat() == "2026-09-30"
    assert custom_days == 30
    try:
        parse_period({"days": "8"})
    except ValueError:
        pass
    else:
        raise AssertionError("Unsupported preset range should be rejected.")


def test_dashboard_cache_expires_and_can_be_bypassed():
    functions = _function_namespace(
        ROUTE,
        {"_dashboard_cache_get", "_dashboard_cache_set"},
        {
            "_control_center_dashboard_cache": {},
            "CONTROL_CENTER_DASHBOARD_CACHE_TTL_SECONDS": 90,
            "CONTROL_CENTER_DASHBOARD_CACHE_MAX_ENTRIES": 128,
            "time": time,
        },
    )
    functions["_dashboard_cache_set"]("range", {"value": 3}, now=10)
    assert functions["_dashboard_cache_get"]("range", now=99) == {"value": 3}
    assert functions["_dashboard_cache_get"]("range", force_refresh=True, now=99) is None
    assert functions["_dashboard_cache_get"]("range", now=100) is None


def test_dashboard_reader_can_call_summary_and_insights_routes():
    route_source = ROUTE.read_text(encoding="utf-8")
    route_tree = ast.parse(route_source)
    route_functions = {
        node.name: node
        for node in ast.walk(route_tree)
        if isinstance(node, ast.FunctionDef)
    }
    for name in DASHBOARD_ROUTES:
        route = route_functions[name]
        decorators = [
            ast.unparse(item) for item in route.decorator_list
        ]
        assert any("swagger_route" in item and "get_auth_security" in item for item in decorators)
        assert "login_required" in decorators
        assert "control_center_required('dashboard')" in decorators

    auth_tree = ast.parse(AUTH.read_text(encoding="utf-8"))
    capabilities_node = next(
        node for node in auth_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_control_center_capabilities"
    )
    namespace = {}
    exec(compile(ast.Module(body=[capabilities_node], type_ignores=[]), str(AUTH), "exec"), namespace)
    capabilities = namespace["get_control_center_capabilities"]
    reader_settings = {
        "require_member_of_control_center_admin": True,
        "require_member_of_control_center_dashboard_reader": True,
    }
    assert capabilities({"roles": ["ControlCenterDashboardReader"]}, reader_settings)["can_view_dashboard"]
    assert not capabilities({"roles": ["User"]}, reader_settings)["can_view_dashboard"]


def test_summary_and_insights_cover_recorded_dashboard_fields():
    source = ROUTE.read_text(encoding="utf-8")
    for required in (
        "cosmos_user_settings_container",
        "c.settings.access.status = 'deny'",
        "conversation_creation",
        "document_creation",
        "usage.total_tokens",
        "cosmos_approvals_container",
        "SELECT VALUE c.status",
        "SELECT DISTINCT VALUE c.user_id",
        "workspace_context.group_id",
        "workspace_context.public_workspace_id",
        "c.usage.model",
        "login_heatmap",
        "force_refresh",
        "CONTROL_CENTER_DASHBOARD_CACHE_TTL_SECONDS = 90",
    ):
        assert required in source, f"Dashboard contract is missing {required!r}."


def test_invalid_period_errors_do_not_expose_exception_text():
    route_tree = ast.parse(ROUTE.read_text(encoding="utf-8"))
    route_functions = {
        node.name: node
        for node in ast.walk(route_tree)
        if isinstance(node, ast.FunctionDef)
    }
    for name in DASHBOARD_ROUTES:
        handlers = [
            handler
            for node in ast.walk(route_functions[name])
            if isinstance(node, ast.Try)
            for handler in node.handlers
            if isinstance(handler.type, ast.Name) and handler.type.id == "ValueError"
        ]
        assert len(handlers) == 1
        handler_source = "\n".join(ast.unparse(statement) for statement in handlers[0].body)
        assert "str(ex)" not in handler_source
        assert "DASHBOARD_INVALID_RANGE_ERROR" in handler_source


def test_version_is_at_least_implementation_version():
    assert_app_version_at_least("0.261.292")


TESTS = [
    test_group_and_workspace_status_counts_use_real_statuses,
    test_status_rows_are_tallied_without_group_by,
    test_document_uploads_are_counted_by_recorded_workspace_type,
    test_active_users_are_counted_from_distinct_values,
    test_token_insights_total_models_and_rank_consumers,
    test_rankings_are_limited_and_ties_are_stable,
    test_activity_insights_rank_actors_and_total_each_login_hour,
    test_summary_and_insights_routes_succeed_with_supported_queries,
    test_dashboard_storage_failures_do_not_expose_details,
    test_period_deltas_and_custom_range_boundaries,
    test_dashboard_cache_expires_and_can_be_bypassed,
    test_dashboard_reader_can_call_summary_and_insights_routes,
    test_summary_and_insights_cover_recorded_dashboard_fields,
    test_invalid_period_errors_do_not_expose_exception_text,
    test_version_is_at_least_implementation_version,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(TESTS)}/{len(TESTS)} dashboard checks passed")
