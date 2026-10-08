#!/usr/bin/env python3
# test_v2_control_center_dashboard.py
"""
Functional test for the V2 Control Center dashboard.
Version: 0.261.300
Implemented in: 0.261.280

This test validates status aggregation, period comparisons, bounded cache behavior,
dashboard-reader authorization, and the summary and insights route contracts.
Since 0.261.292 every dashboard query also passes the Cosmos query guard, because the
Python Cosmos SDK cannot run cross-partition GROUP BY or COUNT over DISTINCT values.
Since 0.261.300 the aggregation lives in functions_control_center_dashboard.py, shared
with the Control Center action: rankings carry names instead of IDs, insights carry the
daily sign-in, conversation, upload and token-type series, and token data is cached
separately so changing a token filter does not re-read the period's other activity.
"""

import ast
import importlib.util
import json
import logging
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from importlib.metadata import version as package_version
from pathlib import Path
from unittest.mock import patch

import werkzeug
from flask import Blueprint, Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
ROUTE = APP / "route_backend_control_center.py"
MODULE = APP / "functions_control_center_dashboard.py"
AUTH = APP / "functions_authentication.py"
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.cosmos_query_guard import cosmos_query_problems
from test_support.versioning import assert_app_version_at_least


spec = importlib.util.spec_from_file_location("v2_control_center_dashboard", MODULE)
dashboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard)

DASHBOARD_ROUTES = {"api_v2_control_center_dashboard_summary", "api_v2_control_center_dashboard_insights"}
ROUTE_HELPERS = {"_control_center_dashboard_stores", "_dashboard_force_refresh"}


class NotFound(Exception):
    """Stands in for CosmosResourceNotFoundError without the SDK import."""


class GuardedContainer:
    """Answer queries by shape after proving the Python SDK could run each one."""

    def __init__(self, respond=None, documents=None):
        self.respond = respond or (lambda query, values: [])
        self.documents = documents or {}
        self.queries = []
        self.reads = []
        self.problems = []

    def query_items(self, query, parameters=None, **kwargs):
        self.queries.append({"query": query, "parameters": parameters or [], **kwargs})
        problems = cosmos_query_problems(query)
        if problems:
            self.problems.extend(problems)
            raise RuntimeError("Cosmos rejected the query shape.")
        return iter(self.respond(query, {item["name"]: item["value"] for item in parameters or []}))

    def read_item(self, item, partition_key):
        self.reads.append(item)
        assert item == partition_key
        if item not in self.documents:
            raise NotFound(item)
        return self.documents[item]


def reset_caches():
    dashboard._control_center_dashboard_cache.clear()
    dashboard._control_center_entity_name_cache.clear()


def stores(**containers):
    return dashboard.DashboardStores(**{
        "activity_logs": containers.pop("activity_logs", GuardedContainer()),
        **containers,
    })


def period(start, end):
    return dashboard.build_dashboard_period(date.fromisoformat(start), date.fromisoformat(end))


def _route_namespace(containers):
    """Execute the real dashboard routes against fake containers and the real module."""
    tree = ast.parse(ROUTE.read_text(encoding="utf-8"))
    helpers = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in ROUTE_HELPERS
    ]
    routes = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in DASHBOARD_ROUTES
    ]
    assert {node.name for node in helpers} == ROUTE_HELPERS
    assert {node.name for node in routes} == DASHBOARD_ROUTES
    blueprint = Blueprint("v2_dashboard_test", __name__)
    events = []

    def passthrough(*_args, **_kwargs):
        return lambda function: function

    namespace = {
        "logging": logging, "jsonify": jsonify, "request": request, "bp": blueprint,
        "swagger_route": passthrough, "get_auth_security": lambda: None,
        "login_required": lambda function: function, "control_center_required": passthrough,
        "log_event": lambda *args, **kwargs: events.append((args, kwargs)),
        "DashboardStores": dashboard.DashboardStores,
        "DASHBOARD_INVALID_RANGE_ERROR": dashboard.DASHBOARD_INVALID_RANGE_ERROR,
        "parse_dashboard_period": dashboard.parse_dashboard_period,
        "extract_token_filters": dashboard.extract_token_filters,
        "get_dashboard_summary": dashboard.get_dashboard_summary,
        "get_dashboard_insights": dashboard.get_dashboard_insights,
        **containers,
    }
    exec(compile(ast.Module(body=helpers + routes, type_ignores=[]), str(ROUTE), "exec"), namespace)
    app = Flask("v2_dashboard_test")
    app.config.update(TESTING=True)
    app.register_blueprint(blueprint)
    # Flask 2.x test clients read werkzeug.__version__, which Werkzeug 3 no longer defines.
    with patch.object(werkzeug, "__version__", package_version("werkzeug"), create=True):
        namespace["client"] = app.test_client()
    namespace["events"] = events
    return namespace


def test_group_and_workspace_status_counts_use_real_statuses():
    counts = dashboard.dashboard_status_counts(
        8,
        [
            {"status": "locked", "count": 2},
            {"status": "upload_disabled", "count": 1},
            {"status": "inactive", "count": 1},
            {"status": "active", "count": 1},
            {"status": "unexpected_legacy_value", "count": 1},
        ],
    )
    assert counts == {"active": 4, "locked": 2, "upload_disabled": 1, "inactive": 1}
    public_counts = dashboard.dashboard_status_counts(
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
    assert public_counts == {"active": 1, "locked": 1, "upload_disabled": 1, "inactive": 2}


def test_status_rows_are_tallied_without_group_by():
    container = GuardedContainer(lambda query, values: ["locked", "locked", None, " Inactive ", 7, "active"])
    rows = dashboard.status_rows(container)
    assert container.problems == []
    assert "SELECT VALUE c.status" in container.queries[0]["query"]
    assert container.queries[0]["enable_cross_partition_query"] is True
    assert sorted(rows, key=lambda row: str(row["status"])) == sorted([
        {"status": "locked", "count": 2}, {"status": None, "count": 1},
        {"status": " Inactive ", "count": 1}, {"status": "7", "count": 1},
        {"status": "active", "count": 1},
    ], key=lambda row: str(row["status"]))
    assert dashboard.dashboard_status_counts(9, rows) == {
        "active": 6, "locked": 2, "upload_disabled": 0, "inactive": 1,
    }
    assert dashboard.dashboard_status_counts(9, rows, unknown_status="inactive") == {
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
    counts = dashboard.count_document_uploads(
        container, datetime(2026, 9, 1), datetime(2026, 9, 7, 23, 59, 59),
    )
    assert counts == {"personal": 6, "group": 2, "public": 1}
    assert list(counts) == ["personal", "group", "public"]
    assert container.problems == []
    assert all("SELECT VALUE COUNT(1)" in item["query"] for item in container.queries)
    assert all(item["enable_cross_partition_query"] is True for item in container.queries)


def test_active_users_are_counted_from_distinct_values():
    container = GuardedContainer(lambda query, values: ["user-1", "user-2", "user-1", "user-3"])
    start = datetime(2026, 9, 1)
    end = datetime(2026, 9, 30, 23, 59, 59)
    assert dashboard.count_active_users(container, start, end) == 3
    query = container.queries[0]
    assert container.problems == []
    assert "SELECT DISTINCT VALUE c.user_id" in query["query"]
    assert "c.activity_type = 'user_login'" in query["query"]
    assert query["parameters"] == [
        {"name": "@start_date", "value": start.isoformat()},
        {"name": "@end_date", "value": end.isoformat()},
    ]


def test_token_aggregate_totals_models_types_and_consumers():
    rows = [
        {"timestamp": "2026-09-01T10:00:00", "model": "gpt-4o", "tokens": 100, "token_type": "chat",
         "user_id": "u1", "group_id": "g1"},
        {"timestamp": "2026-09-01T11:00:00", "model": "gpt-4o", "tokens": 50, "token_type": "embedding",
         "user_id": "u2", "public_workspace_id": "p1"},
        {"timestamp": "2026-09-02T09:00:00", "model": None, "tokens": 10.5, "token_type": "chat", "user_id": "u1"},
        {"timestamp": "2026-09-02T09:30:00", "tokens": 5, "token_type": "web_search", "user_id": "u3"},
        {"timestamp": "2026-09-03T09:00:00", "model": "gpt-4o", "tokens": "bad", "user_id": "u2"},
        {"model": "gpt-4o", "tokens": 7, "group_id": "g1"},
        {"timestamp": "2026-09-03T09:00:00", "model": "gpt-4o", "tokens": True, "user_id": ""},
        {"created_at": "2026-09-03T12:00:00", "model": "gpt-4o", "tokens": 3, "token_type": "chat", "user_id": "u3"},
    ]
    container = GuardedContainer(lambda query, values: rows)
    aggregate = dashboard.aggregate_token_usage(container, period("2026-09-01", "2026-09-03"), {"model": "gpt-4o"})
    assert container.problems == []
    query = container.queries[0]
    assert "c.activity_type = 'token_usage'" in query["query"]
    assert "c.usage.model = @token_model" in query["query"]
    assert "c.token_type AS token_type" in query["query"]
    assert {"name": "@token_model", "value": "gpt-4o"} in query["parameters"]
    assert aggregate["token_usage_by_model"] == [
        {"date": "2026-09-01", "model": "gpt-4o", "tokens": 150},
        {"date": "2026-09-02", "model": "Unknown model", "tokens": 10},
        {"date": "2026-09-03", "model": "gpt-4o", "tokens": 3},
    ]
    # Every day of the period is present so the stacked chart keeps a continuous axis.
    assert aggregate["token_usage_by_type"] == [
        {"date": "2026-09-01", "chat": 100, "embedding": 50, "web_search": 0},
        {"date": "2026-09-02", "chat": 10, "embedding": 0, "web_search": 5},
        {"date": "2026-09-03", "chat": 3, "embedding": 0, "web_search": 0},
    ]
    assert aggregate["by_type"] == {"chat": 113, "embedding": 50, "web_search": 5}
    assert aggregate["total"] == 175
    rankings = {
        key: dashboard.rank_totals(aggregate["consumers"][key], "tokens")
        for key in dashboard.DASHBOARD_ENTITY_KINDS
    }
    assert rankings == {
        "users": [{"id": "u1", "tokens": 110}, {"id": "u2", "tokens": 50}, {"id": "u3", "tokens": 8}],
        "groups": [{"id": "g1", "tokens": 107}],
        "public_workspaces": [{"id": "p1", "tokens": 50}],
    }


def test_rankings_are_limited_and_ties_are_stable():
    totals = {f"user-{index:02d}": 5 for index in range(12)}
    totals["user-99"] = 9
    ranked = dashboard.rank_totals(totals, "tokens")
    assert len(ranked) == dashboard.CONTROL_CENTER_DASHBOARD_RANKING_LIMIT == 10
    assert ranked[0] == {"id": "user-99", "tokens": 9}
    assert [item["id"] for item in ranked[1:]] == [f"user-{index:02d}" for index in range(9)]


def test_activity_aggregate_ranks_actors_daily_series_and_login_hours():
    rows = [
        {"timestamp": "2026-09-07T09:15:00", "activity_type": "user_login", "user_id": "u1"},
        {"timestamp": "2026-09-14T09:45:00", "activity_type": "user_login", "user_id": "u2"},
        {"timestamp": "2026-09-15T23:05:00", "activity_type": "user_login", "user_id": "u1"},
        {"timestamp": "2026-09-15", "activity_type": "user_login", "user_id": "u1"},
        {"timestamp": "2026-09-16T10:00:00", "activity_type": "token_usage", "user_id": "u1",
         "group_id": "g1", "public_workspace_id": "p1"},
        {"timestamp": "2026-09-16T11:00:00", "activity_type": "document_creation", "workspace_type": "group",
         "user_id": "u3", "group_id": "g1"},
        {"created_at": "2026-09-16T12:00:00", "activity_type": "document_creation", "user_id": "u3"},
        {"timestamp": "2026-09-16T13:00:00", "activity_type": "conversation_creation", "user_id": "u2"},
        {"activity_type": "user_login", "user_id": "u4"},
    ]
    container = GuardedContainer(lambda query, values: rows)
    aggregate = dashboard.aggregate_activity(container, period("2026-09-01", "2026-09-30"))
    assert container.problems == []
    query = container.queries[0]["query"]
    assert "c.timestamp >= @start_date" in query and "c.created_at >= @start_date" in query
    rankings = {
        key: dashboard.rank_totals(aggregate["actors"][key], "activity_count")
        for key in dashboard.DASHBOARD_ENTITY_KINDS
    }
    assert rankings == {
        "users": [{"id": "u1", "activity_count": 4}, {"id": "u2", "activity_count": 2},
                  {"id": "u3", "activity_count": 2}, {"id": "u4", "activity_count": 1}],
        "groups": [{"id": "g1", "activity_count": 2}],
        "public_workspaces": [{"id": "p1", "activity_count": 1}],
    }
    # 2026-09-07 and 2026-09-14 are both Mondays: one cell totals both logins.
    assert aggregate["login_cells"] == [
        {"weekday": 0, "hour": 9, "count": 2},
        {"weekday": 1, "hour": 23, "count": 1},
    ]
    daily = {row["date"]: row for row in aggregate["daily_activity"]}
    assert len(daily) == 30
    assert daily["2026-09-15"]["sign_ins"] == 2
    assert daily["2026-09-16"] == {
        "date": "2026-09-16", "sign_ins": 0, "conversations_created": 1,
        "uploads_personal": 1, "uploads_group": 1, "uploads_public": 0,
    }
    assert sum(row["sign_ins"] for row in aggregate["daily_activity"]) == 4


def test_filtered_daily_activity_keeps_sign_ins_to_the_user_filter():
    rows = [
        {"timestamp": "2026-09-02T08:00:00", "activity_type": "user_login", "user_id": "u1"},
        {"timestamp": "2026-09-02T09:00:00", "activity_type": "conversation_creation", "user_id": "u1",
         "workspace_type": "group", "group_id": "g1"},
        {"timestamp": "2026-09-02T10:00:00", "activity_type": "conversation_creation", "user_id": "u1",
         "workspace_type": "personal"},
        {"timestamp": "2026-09-02T11:00:00", "activity_type": "document_creation", "user_id": "u1",
         "workspace_type": "group", "group_id": "g2"},
    ]
    container = GuardedContainer(lambda query, values: rows)
    report = dashboard.filtered_daily_activity(
        container, period("2026-09-01", "2026-09-02"), {"user_id": "u1", "group_id": "g1"},
    )
    query = container.queries[0]
    assert "c.user_id = @activity_user_id" in query["query"]
    assert {"name": "@activity_user_id", "value": "u1"} in query["parameters"]
    assert report[1] == {
        "date": "2026-09-02", "sign_ins": 1, "conversations_created": 1,
        "uploads_personal": 0, "uploads_group": 0, "uploads_public": 0,
    }


def test_rankings_resolve_names_and_cache_the_answers():
    reset_caches()
    users = GuardedContainer(documents={
        "u1": {"id": "u1", "display_name": "Jane Doe", "email": "jane@contoso.com"},
        "u2": {"id": "u2", "email": "only-email@contoso.com"},
    })
    groups = GuardedContainer(documents={"g1": {"id": "g1", "name": "Finance"}})
    workspaces = GuardedContainer(documents={})
    data = stores(user_settings=users, groups=groups, public_workspaces=workspaces)
    names = dashboard.resolve_entity_names(
        data, {"users": ["u1", "u2", "u9", "u1"], "groups": ["g1"], "public_workspaces": ["p1"]}, now=10,
    )
    assert names["users"]["u1"] == {"name": "Jane Doe", "detail": "jane@contoso.com", "found": True}
    assert names["users"]["u2"] == {"name": "only-email@contoso.com", "detail": "", "found": True}
    assert names["users"]["u9"] == {"name": "Unknown user", "detail": "", "found": False}
    assert names["groups"]["g1"] == {"name": "Finance", "detail": "", "found": True}
    assert names["public_workspaces"]["p1"] == {"name": "Deleted public workspace", "detail": "", "found": False}
    assert users.reads == ["u1", "u2", "u9"]

    dashboard.resolve_entity_names(data, {"users": ["u1", "u9"]}, now=20)
    assert users.reads == ["u1", "u2", "u9"], "Names are cached for the dashboard's cache lifetime."
    dashboard.resolve_entity_names(data, {"users": ["u1"]}, now=200)
    assert users.reads[-1] == "u1", "An expired name is read again."

    named = dashboard.name_ranked_rows([{"id": "u1", "tokens": 4}], names["users"])
    assert named == [{"id": "u1", "tokens": 4, "name": "Jane Doe", "detail": "jane@contoso.com", "found": True}]


def _dashboard_containers():
    statuses = {"groups": ["locked", None, "inactive"], "workspaces": ["locked", "legacy"]}
    token_rows = [
        {"timestamp": "2026-09-20T10:00:00", "model": "gpt-4o", "tokens": 40, "token_type": "chat",
         "user_id": "u1", "group_id": "g1"},
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
        "cosmos_user_settings_container": GuardedContainer(
            users, documents={"u1": {"id": "u1", "display_name": "Jane Doe", "email": "jane@contoso.com"}},
        ),
        "cosmos_groups_container": GuardedContainer(
            statuses_for("groups"), documents={"g1": {"id": "g1", "name": "Finance"}},
        ),
        "cosmos_public_workspaces_container": GuardedContainer(statuses_for("workspaces")),
        "cosmos_activity_logs_container": GuardedContainer(activity),
        "cosmos_user_documents_container": GuardedContainer(lambda query, values: [1]),
        "cosmos_group_documents_container": GuardedContainer(lambda query, values: [0]),
        "cosmos_public_documents_container": GuardedContainer(lambda query, values: [0]),
        "cosmos_approvals_container": GuardedContainer(lambda query, values: [2]),
    }


def test_summary_and_insights_routes_succeed_with_supported_queries():
    reset_caches()
    containers = _dashboard_containers()
    namespace = _route_namespace(containers)
    client = namespace["client"]

    summary = client.get("/api/v2/control-center/dashboard/summary?start_date=2026-09-01&end_date=2026-09-30")
    insights = client.get("/api/v2/control-center/dashboard/insights?start_date=2026-09-01&end_date=2026-09-30")
    problems = [problem for container in containers.values() for problem in container.problems]
    assert problems == [], problems
    assert summary.status_code == 200, namespace["events"]
    assert insights.status_code == 200, namespace["events"]

    body = summary.get_json()
    assert body["period"] == {"start_date": "2026-09-01", "end_date": "2026-09-30", "days": 30, "timezone": "UTC"}
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
    assert data["top_tokens"]["groups"] == [
        {"id": "g1", "tokens": 40, "name": "Finance", "detail": "", "found": True},
    ]
    assert data["top_tokens"]["users"] == [
        {"id": "u1", "tokens": 40, "name": "Jane Doe", "detail": "jane@contoso.com", "found": True},
    ]
    assert data["top_activity"]["users"] == [
        {"id": "u1", "activity_count": 2, "name": "Jane Doe", "detail": "jane@contoso.com", "found": True},
    ]
    assert data["login_heatmap"]["cells"] == [{"weekday": 0, "hour": 8, "count": 1}]
    daily = {row["date"]: row for row in data["daily_activity"]}
    assert len(daily) == 30 and daily["2026-09-21"]["sign_ins"] == 1
    token_days = {row["date"]: row for row in data["token_usage_by_type"]}
    assert token_days["2026-09-20"] == {"date": "2026-09-20", "chat": 40, "embedding": 0, "web_search": 0}

    query_count = sum(len(container.queries) for container in containers.values())
    assert client.get(
        "/api/v2/control-center/dashboard/summary?start_date=2026-09-01&end_date=2026-09-30"
    ).get_json()["cached"] is True
    assert client.get(
        "/api/v2/control-center/dashboard/insights?start_date=2026-09-01&end_date=2026-09-30"
    ).get_json()["cached"] is True
    assert sum(len(container.queries) for container in containers.values()) == query_count


def test_changing_a_token_filter_only_recalculates_token_figures():
    reset_caches()
    containers = _dashboard_containers()
    client = _route_namespace(containers)["client"]
    activity = containers["cosmos_activity_logs_container"]
    base = "start_date=2026-09-01&end_date=2026-09-30"
    assert client.get(f"/api/v2/control-center/dashboard/summary?{base}").status_code == 200
    assert client.get(f"/api/v2/control-center/dashboard/insights?{base}").status_code == 200
    before = len(activity.queries)

    filtered_summary = client.get(f"/api/v2/control-center/dashboard/summary?{base}&model=gpt-4o")
    filtered_insights = client.get(f"/api/v2/control-center/dashboard/insights?{base}&model=gpt-4o")
    assert filtered_summary.get_json()["cached"] is False
    assert filtered_insights.get_json()["cached"] is False
    new_queries = [item["query"] for item in activity.queries[before:]]
    assert new_queries, "The filtered token figures must be read."
    assert all("token_usage" in query for query in new_queries), new_queries
    assert all("@token_model" in query for query in new_queries), new_queries


def test_refresh_bypasses_both_cached_halves():
    reset_caches()
    containers = _dashboard_containers()
    client = _route_namespace(containers)["client"]
    url = "/api/v2/control-center/dashboard/insights?start_date=2026-09-01&end_date=2026-09-30"
    assert client.get(url).get_json()["cached"] is False
    assert client.get(url).get_json()["cached"] is True
    activity = containers["cosmos_activity_logs_container"]
    before = len(activity.queries)
    assert client.get(f"{url}&force_refresh=1").get_json()["cached"] is False
    assert len(activity.queries) == before + 2


def test_dashboard_storage_failures_do_not_expose_details():
    reset_caches()
    containers = _dashboard_containers()
    groups = containers["cosmos_groups_container"]
    groups.respond = lambda query, values: (_ for _ in ()).throw(RuntimeError("secret-storage-detail"))
    namespace = _route_namespace(containers)
    response = namespace["client"].get("/api/v2/control-center/dashboard/summary?days=7&force_refresh=1")
    assert response.status_code == 500
    assert "secret-storage-detail" not in response.get_data(as_text=True)
    assert response.get_json() == {"error": "Failed to retrieve dashboard summary."}


def test_period_deltas_and_custom_range_boundaries():
    metric = dashboard.dashboard_metric
    assert metric(15, 10) == {"value": 15, "delta": 5, "previous": 10, "percent_change": 50.0}
    assert metric(7, 0)["percent_change"] is None
    assert metric(0, 0)["percent_change"] == 0.0
    assert metric(5)["delta"] is None

    seven = dashboard.parse_dashboard_period({"days": "7"}, today=date(2026, 10, 7))
    assert seven.days == 7
    assert seven.start_day == "2026-10-01" and seven.end_day == "2026-10-07"
    assert seven.previous_end + timedelta(microseconds=1) == seven.start
    assert (seven.start - seven.previous_start).days == 7

    custom = dashboard.parse_dashboard_period({"start_date": "2026-09-01", "end_date": "2026-09-30"})
    assert custom.describe() == {"start_date": "2026-09-01", "end_date": "2026-09-30", "days": 30, "timezone": "UTC"}
    assert custom.describe_previous()["start_date"] == "2026-08-02"
    assert custom.dates()[0] == "2026-09-01" and custom.dates()[-1] == "2026-09-30"
    for invalid in (
        {"days": "8"},
        {"start_date": "2026-09-01"},
        {"start_date": "2026-09-30", "end_date": "2026-09-01"},
        {"start_date": "2025-01-01", "end_date": "2026-09-01"},
        {"start_date": "09/01/2026", "end_date": "2026-09-30"},
    ):
        try:
            dashboard.parse_dashboard_period(invalid)
        except ValueError:
            continue
        raise AssertionError(f"Invalid range should be rejected: {invalid}")


def test_requested_periods_accept_any_day_count_up_to_a_year():
    today = date(2026, 10, 7)
    assert dashboard.resolve_requested_period(days=14, today=today).start_day == "2026-09-24"
    assert dashboard.resolve_requested_period(days="1", today=today).describe()["days"] == 1
    assert dashboard.resolve_requested_period(today=today).days == 30
    explicit = dashboard.resolve_requested_period("2026-01-01", "2026-01-31", today=today)
    assert (explicit.start_day, explicit.end_day, explicit.days) == ("2026-01-01", "2026-01-31", 31)
    for kwargs in (
        {"days": 0}, {"days": 367}, {"days": "many"}, {"days": True},
        {"start_date": "2026-01-01"}, {"start_date": "2026-01-31", "end_date": "2026-01-01"},
    ):
        try:
            dashboard.resolve_requested_period(today=today, **kwargs)
        except ValueError:
            continue
        raise AssertionError(f"Invalid requested period should be rejected: {kwargs}")


def test_dashboard_cache_expires_and_can_be_bypassed():
    reset_caches()
    dashboard.dashboard_cache_set("range", {"value": 3}, now=10)
    assert dashboard.dashboard_cache_get("range", now=99) == {"value": 3}
    assert dashboard.dashboard_cache_get("range", force_refresh=True, now=99) is None
    assert dashboard.dashboard_cache_get("range", now=100) is None
    for index in range(dashboard.CONTROL_CENTER_DASHBOARD_CACHE_MAX_ENTRIES + 5):
        dashboard.dashboard_cache_set(("bounded", index), index, now=500)
    assert len(dashboard._control_center_dashboard_cache) == dashboard.CONTROL_CENTER_DASHBOARD_CACHE_MAX_ENTRIES
    reset_caches()


def test_token_usage_report_groups_by_each_dimension():
    reset_caches()
    rows = [
        {"timestamp": "2026-09-01T10:00:00", "model": "gpt-4o", "tokens": 100, "token_type": "chat", "user_id": "u1"},
        {"timestamp": "2026-09-02T10:00:00", "model": "gpt-4.1", "tokens": 30, "token_type": "embedding", "user_id": "u2"},
    ]
    data = stores(
        activity_logs=GuardedContainer(lambda query, values: rows),
        user_settings=GuardedContainer(documents={"u1": {"id": "u1", "display_name": "Jane Doe", "email": "jane@contoso.com"}}),
    )
    window = period("2026-09-01", "2026-09-02")
    by_day = dashboard.token_usage_report(data, window, group_by="day")
    assert by_day["total_tokens"] == 130
    assert by_day["rows"] == [
        {"date": "2026-09-01", "total_tokens": 100, "chat": 100, "embedding": 0, "web_search": 0},
        {"date": "2026-09-02", "total_tokens": 30, "chat": 0, "embedding": 30, "web_search": 0},
    ]
    assert dashboard.token_usage_report(data, window, group_by="model")["rows"] == [
        {"model": "gpt-4o", "tokens": 100}, {"model": "gpt-4.1", "tokens": 30},
    ]
    assert dashboard.token_usage_report(data, window, group_by="token_type")["rows"] == [
        {"token_type": "chat", "tokens": 100}, {"token_type": "embedding", "tokens": 30},
        {"token_type": "web_search", "tokens": 0},
    ]
    by_user = dashboard.token_usage_report(data, window, group_by="user", limit=1)["rows"]
    assert by_user == [{"id": "u1", "tokens": 100, "name": "Jane Doe", "detail": "jane@contoso.com", "found": True}]
    try:
        dashboard.token_usage_report(data, window, group_by="conversation")
    except ValueError:
        pass
    else:
        raise AssertionError("An unsupported grouping should be rejected.")
    reset_caches()


def test_reports_return_copies_of_cached_rows():
    reset_caches()
    data = stores(activity_logs=GuardedContainer(lambda query, values: [
        {"timestamp": "2026-09-01T10:00:00", "activity_type": "user_login", "user_id": "u1"},
    ]))
    window = period("2026-09-01", "2026-09-01")
    first = dashboard.daily_activity_report(data, window)
    first[0]["sign_ins"] = 99
    assert dashboard.daily_activity_report(data, window)[0]["sign_ins"] == 1
    assert dashboard.sign_in_pattern_report(data, window) == [
        {"weekday": "Tuesday", "hour_utc": 10, "sign_ins": 1},
    ]
    reset_caches()


def test_find_entities_searches_by_name_with_bounded_parameterized_queries():
    users = GuardedContainer(lambda query, values: [
        {"id": "u1", "display_name": "Jane Doe", "email": "jane@contoso.com"},
        {"id": "", "display_name": "No ID"},
    ])
    groups = GuardedContainer(lambda query, values: [{"id": "g1", "name": "Finance"}])
    data = stores(user_settings=users, groups=groups)
    assert dashboard.find_entities(data, "users", "  JANE  ") == [
        {"id": "u1", "name": "Jane Doe", "email": "jane@contoso.com"},
    ]
    query = users.queries[0]
    assert "SELECT TOP @limit" in query["query"]
    assert {"name": "@search", "value": "jane"} in query["parameters"]
    assert {"name": "@limit", "value": 10} in query["parameters"]
    assert dashboard.find_entities(data, "groups", "fin", limit=500) == [{"id": "g1", "name": "Finance"}]
    assert {"name": "@limit", "value": 10} in groups.queries[0]["parameters"]
    for kind, search in (("users", "j"), ("users", "x" * 101), ("conversations", "jane")):
        try:
            dashboard.find_entities(data, kind, search)
        except ValueError:
            continue
        raise AssertionError(f"Invalid entity search should be rejected: {kind!r} {search!r}")


def test_summary_report_rows_explain_each_figure():
    payload = {
        "period": {"start_date": "2026-09-01", "end_date": "2026-09-30", "days": 30, "timezone": "UTC"},
        "users": {
            "total": {"value": 4}, "blocked": {"value": 1},
            "active": {"value": 2, "previous": 1, "delta": 1, "percent_change": 100.0},
            "dau": {"value": 1}, "wau": {"value": 2}, "mau": {"value": 2},
        },
        "conversations": {"value": 3, "previous": 3, "delta": 0, "percent_change": 0.0},
        "document_uploads": {"total": {"value": 5}, "by_workspace_type": {"group": {"value": 2}}},
        "document_processing_failures": {"value": None, "available": False},
        "tokens": {"value": 10},
        "groups": {"total": {"value": 5}, "by_status": {"upload_disabled": {"value": 1}}},
        "public_workspaces": {"total": {"value": 2}, "by_status": {}},
        "pending_approvals": None,
    }
    rows = {row["metric"]: row for row in dashboard.summary_report_rows(payload)}
    assert rows["Signed-in users"]["change"] == 1
    assert "each person counts once" in rows["Signed-in users"]["definition"]
    assert rows["Daily active users"]["definition"] == "People who signed in on 2026-09-30 (UTC)."
    assert "change" not in rows["Total users"]
    assert "Processing failures" not in rows
    assert "Pending approvals" not in rows
    assert rows["Groups (upload disabled)"]["value"] == 1


def test_dashboard_reader_can_call_summary_and_insights_routes():
    route_tree = ast.parse(ROUTE.read_text(encoding="utf-8"))
    route_functions = {
        node.name: node
        for node in ast.walk(route_tree)
        if isinstance(node, ast.FunctionDef)
    }
    for name in DASHBOARD_ROUTES:
        decorators = [ast.unparse(item) for item in route_functions[name].decorator_list]
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
    source = MODULE.read_text(encoding="utf-8")
    for required in (
        "c.settings.access.status = 'deny'",
        "conversation_creation",
        "document_creation",
        "usage.total_tokens",
        "c.status = 'pending'",
        "SELECT VALUE c.status",
        "SELECT DISTINCT VALUE c.user_id",
        "workspace_context.group_id",
        "workspace_context.public_workspace_id",
        "c.usage.model",
        "c.token_type AS token_type",
        "login_heatmap",
        "daily_activity",
        "token_usage_by_type",
        "CONTROL_CENTER_DASHBOARD_CACHE_TTL_SECONDS = 90",
    ):
        assert required in source, f"Dashboard contract is missing {required!r}."
    route_source = ROUTE.read_text(encoding="utf-8")
    assert "force_refresh" in route_source
    assert "cosmos_approvals_container" in route_source


def test_dashboard_module_imports_without_the_application_bootstrap():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(name=node.module or "")])
    }
    assert imported <= {
        "json", "logging", "threading", "time", "collections", "dataclasses", "datetime", "typing",
    }, imported


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
    assert_app_version_at_least("0.261.300")


TESTS = [
    test_group_and_workspace_status_counts_use_real_statuses,
    test_status_rows_are_tallied_without_group_by,
    test_document_uploads_are_counted_by_recorded_workspace_type,
    test_active_users_are_counted_from_distinct_values,
    test_token_aggregate_totals_models_types_and_consumers,
    test_rankings_are_limited_and_ties_are_stable,
    test_activity_aggregate_ranks_actors_daily_series_and_login_hours,
    test_filtered_daily_activity_keeps_sign_ins_to_the_user_filter,
    test_rankings_resolve_names_and_cache_the_answers,
    test_summary_and_insights_routes_succeed_with_supported_queries,
    test_changing_a_token_filter_only_recalculates_token_figures,
    test_refresh_bypasses_both_cached_halves,
    test_dashboard_storage_failures_do_not_expose_details,
    test_period_deltas_and_custom_range_boundaries,
    test_requested_periods_accept_any_day_count_up_to_a_year,
    test_dashboard_cache_expires_and_can_be_bypassed,
    test_token_usage_report_groups_by_each_dimension,
    test_reports_return_copies_of_cached_rows,
    test_find_entities_searches_by_name_with_bounded_parameterized_queries,
    test_summary_report_rows_explain_each_figure,
    test_dashboard_reader_can_call_summary_and_insights_routes,
    test_summary_and_insights_cover_recorded_dashboard_fields,
    test_dashboard_module_imports_without_the_application_bootstrap,
    test_invalid_period_errors_do_not_expose_exception_text,
    test_version_is_at_least_implementation_version,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(TESTS)}/{len(TESTS)} dashboard checks passed")
