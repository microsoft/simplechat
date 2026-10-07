#!/usr/bin/env python3
# test_v2_control_center_dashboard.py
"""
Functional test for the V2 Control Center dashboard.
Version: 0.261.279
Implemented in: 0.261.279

This test validates status aggregation, period comparisons, bounded cache behavior,
dashboard-reader authorization, and the summary and insights route contracts.
"""

import ast
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
ROUTE = APP / "route_backend_control_center.py"
AUTH = APP / "functions_authentication.py"
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least


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


def test_document_uploads_are_aggregated_by_recorded_workspace_type():
    class ActivityContainer:
        def query_items(self, **kwargs):
            self.query = kwargs
            return iter([
                {"workspace_type": "personal", "count": 3},
                {"workspace_type": "group", "count": 2},
                {"workspace_type": "public", "count": 1},
                {"workspace_type": None, "count": 1},
                {"workspace_type": "legacy", "count": 1},
            ])

    container = ActivityContainer()
    functions = _function_namespace(
        ROUTE,
        {"_dashboard_document_upload_counts"},
        {"cosmos_activity_logs_container": container},
    )
    start = datetime(2026, 9, 1)
    end = datetime(2026, 9, 7, 23, 59, 59)
    counts = functions["_dashboard_document_upload_counts"](start, end)
    assert counts == {"personal": 5, "group": 2, "public": 1}
    assert "GROUP BY c.workspace_type" in container.query["query"]
    assert container.query["enable_cross_partition_query"] is True


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
    for name in (
        "api_v2_control_center_dashboard_summary",
        "api_v2_control_center_dashboard_insights",
    ):
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
        "GROUP BY c.status",
        "workspace_context.group_id",
        "workspace_context.public_workspace_id",
        "c.usage.model",
        "login_heatmap",
        "force_refresh",
        "CONTROL_CENTER_DASHBOARD_CACHE_TTL_SECONDS = 90",
    ):
        assert required in source, f"Dashboard contract is missing {required!r}."


def test_version_is_at_least_implementation_version():
    assert_app_version_at_least("0.261.279")


TESTS = [
    test_group_and_workspace_status_counts_use_real_statuses,
    test_document_uploads_are_aggregated_by_recorded_workspace_type,
    test_period_deltas_and_custom_range_boundaries,
    test_dashboard_cache_expires_and_can_be_bypassed,
    test_dashboard_reader_can_call_summary_and_insights_routes,
    test_summary_and_insights_cover_recorded_dashboard_fields,
    test_version_is_at_least_implementation_version,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(TESTS)}/{len(TESTS)} dashboard checks passed")
