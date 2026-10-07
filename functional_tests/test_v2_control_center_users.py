#!/usr/bin/env python3
# test_v2_control_center_users.py
"""
Functional test for V2 Control Center user management.
Version: 0.261.280
Implemented in: 0.261.280

This test validates Users filtering, sorting, paging, detail data boundaries,
bulk-action limits, admin-only authorization, cached metric freshness and CSV safety.
"""

import ast
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
ROUTE = APP / "route_backend_control_center.py"
AUTH = APP / "functions_authentication.py"
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least


HELPERS = {
    "_control_center_validate_user_id",
    "_control_center_parse_user_filters",
    "_control_center_user_where",
    "_control_center_effective_restriction",
    "_control_center_user_row",
    "_control_center_csv_safe_cell",
}


def _route_helpers():
    tree = ast.parse(ROUTE.read_text(encoding="utf-8"))
    assignments = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id in {"CONTROL_CENTER_USER_ID_PATTERN", "CONTROL_CENTER_USER_SORTS"}
            for target in node.targets
        )
    ]
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in HELPERS
    ]
    assert {node.name for node in functions} == HELPERS
    namespace = {
        "re": re,
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
    }
    exec(compile(ast.Module(body=assignments + functions, type_ignores=[]), str(ROUTE), "exec"), namespace)
    return namespace


def _route_functions(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }


def test_filter_contract_is_parameterized_and_supports_dashboard_drillthrough():
    helpers = _route_helpers()
    now = datetime(2026, 10, 7, tzinfo=timezone.utc)
    filters = helpers["_control_center_parse_user_filters"]({
        "search": "x' OR 1=1 --",
        "filter": "active",
        "status": "blocked",
        "sort": "tokens",
        "direction": "desc",
        "has_documents": "yes",
    }, now=now)
    where, parameters = helpers["_control_center_user_where"](filters)
    parameter_values = {item["name"]: item["value"] for item in parameters}
    assert filters["last_login"] == "30"
    assert filters["access_status"] == "deny"
    assert filters["sort"] == "tokens"
    assert filters["direction"] == "desc"
    assert parameter_values["@search"] == "x' or 1=1 --"
    assert "@search" in where and "x' OR 1=1" not in where
    assert "c.settings.metrics.token_metrics.total_tokens" in helpers["CONTROL_CENTER_USER_SORTS"]["tokens"]
    assert "IS_DEFINED(c.settings.metrics.document_metrics.total_documents)" in where
    assert {item["name"] for item in parameters} >= {
        "@search", "@access_status", "@access_now", "@last_login_cutoff",
    }

    route = ROUTE.read_text(encoding="utf-8")
    assert "OFFSET @offset LIMIT @limit" in route
    assert '"total_items": total' in route
    assert '"metrics_freshness"' in route
    assert "CONTROL_CENTER_USER_SORTS[filters[\"sort\"]]" in route


def test_filter_validation_rejects_unbounded_or_unknown_fields():
    parse_filters = _route_helpers()["_control_center_parse_user_filters"]
    for query, message in (
        ({"sort": "settings"}, "sort"),
        ({"direction": "sideways"}, "direction"),
        ({"last_login": "365"}, "last-login"),
        ({"search": "x" * 201}, "Search"),
    ):
        try:
            parse_filters(query)
        except ValueError as error:
            assert message.lower() in str(error).lower()
        else:
            raise AssertionError(f"Invalid query was accepted: {query!r}")


def test_user_ids_expiry_and_cached_row_projection_are_validated():
    helpers = _route_helpers()
    validate_id = helpers["_control_center_validate_user_id"]
    assert validate_id("abc-123") == "abc-123"
    for value in ("", "../admin", "a/b", "x" * 129):
        try:
            validate_id(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid user ID was accepted: {value!r}")

    now = datetime(2026, 10, 7, tzinfo=timezone.utc)
    effective = helpers["_control_center_effective_restriction"]
    assert effective({"access": {"status": "deny", "datetime_to_allow": "2026-10-06T00:00:00Z"}}, "access", now)["status"] == "allow"
    assert effective({"access": {"status": "deny", "datetime_to_allow": "2026-10-08T00:00:00Z"}}, "access", now)["status"] == "deny"

    row = helpers["_control_center_user_row"]({
        "id": "user-1",
        "email": "person@example.test",
        "display_name": "Person",
        "settings": {
            "metrics": {
                "calculated_at": "2026-10-07T00:00:00Z",
                "login_metrics": {"last_login": "2026-10-06T00:00:00Z", "total_logins": 4},
                "chat_metrics": {"total_conversations": 9},
                "document_metrics": {"total_documents": 2},
                "token_metrics": {"total_tokens": 120},
            },
        },
    }, now)
    assert row["access"]["status"] == "allow"
    assert (row["last_login"], row["conversations"], row["documents"], row["tokens"]) == (
        "2026-10-06T00:00:00Z", 9, 2, 120,
    )
    assert row["metrics_calculated_at"] == "2026-10-07T00:00:00Z"


def test_allow_filters_exclude_active_denials_with_null_or_future_expiry():
    parse_filters = _route_helpers()["_control_center_parse_user_filters"]
    build_where = _route_helpers()["_control_center_user_where"]
    filters = parse_filters({"access_status": "allow", "upload_status": "allow"})
    where, _ = build_where(filters)
    for field, parameter in (("access", "@access_now"), ("file_uploads", "@upload_now")):
        assert (
            f"IS_DEFINED(c.settings.{field}.datetime_to_allow) "
            f"AND NOT IS_NULL(c.settings.{field}.datetime_to_allow) "
            f"AND c.settings.{field}.datetime_to_allow <= {parameter}"
        ) in where
        assert f"OR IS_NULL(c.settings.{field}.datetime_to_allow)" not in where


def test_bulk_selection_is_filter_based_exclusion_aware_and_capped():
    source = ROUTE.read_text(encoding="utf-8")
    route = _route_functions(ROUTE)["api_v2_control_center_users_bulk_action"]
    route_source = ast.get_source_segment(source, route)
    assert "CONTROL_CENTER_USERS_MAX_BULK = 500" in source
    assert "data.get(\"user_ids\")" in route_source
    assert "data.get(\"filter\")" in route_source
    assert "data.get(\"exclude_ids\", [])" in route_source
    assert "CONTROL_CENTER_USERS_MAX_BULK + 1" in route_source
    assert "update_user_settings(" in route_source
    assert '"failed_user_ids": failed_ids' in route_source


def test_detail_contract_uses_authorized_snapshot_and_batched_memberships():
    source = ROUTE.read_text(encoding="utf-8")
    route = _route_functions(ROUTE)["api_v2_control_center_user_detail"]
    route_source = ast.get_source_segment(source, route)
    assert "read_user_settings_snapshot(" in route_source
    assert "allow_cross_user=True" in route_source
    assert "TOP 20" in route_source
    assert "partition_key=normalized_user_id" in route_source
    assert '"groups": group_memberships' in route_source
    assert '"public_workspaces": public_memberships' in route_source
    assert '"usage": {' in route_source


def test_csv_cells_neutralize_all_formula_prefixes_and_export_is_streamed():
    helpers = _route_helpers()
    safe_cell = helpers["_control_center_csv_safe_cell"]
    for prefix in ("=", "+", "-", "@"):
        assert safe_cell(f"{prefix}1+1") == f"'{prefix}1+1"
    assert safe_cell("ordinary text") == "ordinary text"
    assert safe_cell(None) == ""

    source = ROUTE.read_text(encoding="utf-8")
    route_source = ast.get_source_segment(
        source,
        _route_functions(ROUTE)["api_v2_control_center_users_export"],
    )
    assert "stream_with_context(stream_csv())" in route_source
    assert "_control_center_user_where(filters)" in route_source
    assert "_control_center_csv_safe_cell(value)" in route_source


def test_routes_require_full_control_center_admin_not_dashboard_reader():
    route_functions = _route_functions(ROUTE)
    for name in (
        "api_v2_control_center_users",
        "api_v2_control_center_user_detail",
        "api_v2_control_center_users_bulk_action",
        "api_v2_control_center_users_export",
    ):
        route = route_functions[name]
        decorators = [ast.unparse(decorator) for decorator in route.decorator_list]
        assert any("swagger_route" in decorator and "get_auth_security" in decorator for decorator in decorators)
        assert "login_required" in decorators
        assert "control_center_required('admin')" in decorators

    auth_functions = _route_functions(AUTH)
    capabilities = auth_functions["get_control_center_capabilities"]
    namespace = {}
    exec(compile(ast.Module(body=[capabilities], type_ignores=[]), str(AUTH), "exec"), namespace)
    reader_capabilities = namespace["get_control_center_capabilities"](
        {"roles": ["ControlCenterDashboardReader"]},
        {
            "require_member_of_control_center_admin": True,
            "require_member_of_control_center_dashboard_reader": True,
        },
    )
    assert reader_capabilities["can_view_dashboard"]
    assert not reader_capabilities["can_manage_users"]


def test_version_is_at_least_the_implementation_version():
    assert_app_version_at_least("0.261.280")


TESTS = [
    test_filter_contract_is_parameterized_and_supports_dashboard_drillthrough,
    test_filter_validation_rejects_unbounded_or_unknown_fields,
    test_user_ids_expiry_and_cached_row_projection_are_validated,
    test_allow_filters_exclude_active_denials_with_null_or_future_expiry,
    test_bulk_selection_is_filter_based_exclusion_aware_and_capped,
    test_detail_contract_uses_authorized_snapshot_and_batched_memberships,
    test_csv_cells_neutralize_all_formula_prefixes_and_export_is_streamed,
    test_routes_require_full_control_center_admin_not_dashboard_reader,
    test_version_is_at_least_the_implementation_version,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(TESTS)}/{len(TESTS)} V2 user management checks passed")
