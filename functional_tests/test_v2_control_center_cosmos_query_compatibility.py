#!/usr/bin/env python3
# test_v2_control_center_cosmos_query_compatibility.py
"""
Functional test for V2 Control Center Cosmos query compatibility.
Version: 0.261.297
Implemented in: 0.261.292

The Dashboard, Users and Groups sections returned HTTP 500 because Cosmos DB rejected
their queries with HTTP 400. The azure-cosmos Python SDK cannot run cross-partition
GROUP BY or COUNT over DISTINCT values, and a two-property ORDER BY needs a composite
index that user_settings does not have. This test scans every SQL string in the V2
Control Center code paths and fails if one of those query shapes returns.

Since 0.261.296 it also rejects reserved keywords used as dotted property names, such as
c.group.group_id, in every Control Center query, classic routes included. Cosmos answers
those with an HTTP 400 syntax error, which kept the Groups list, group details, the
Activity Logs group filter and every Activity Logs search failing after 0.261.292.

Since 0.261.297 the dashboard queries live in functions_control_center_dashboard.py, which
the Control Center action shares, so that module is scanned too.
"""

import ast
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
ROUTE = APP / "route_backend_control_center.py"
CONFIG = APP / "config.py"
CONTROL_CENTER_MODULES = (
    APP / "functions_control_center_dashboard.py",
    APP / "functions_control_center_groups.py",
    APP / "functions_control_center_public_workspaces.py",
    APP / "functions_control_center_activity.py",
    APP / "functions_control_center_activity_display.py",
)
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.cosmos_query_guard import (
    assert_cosmos_query_supported,
    cosmos_query_problems,
    reserved_word_problems,
)
from test_support.versioning import assert_app_version_at_least


SQL_PATTERN = re.compile(r"\b(SELECT|ORDER\s+BY|GROUP\s+BY)\b", re.IGNORECASE)
V2_ROUTE_PREFIXES = ("api_v2_control_center_", "_dashboard_", "_control_center_")


def _activity_log_composite_indexes():
    """Read the composite index that config.py declares for the activity_logs container."""
    tree = ast.parse(CONFIG.read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "ACTIVITY_LOGS_INDEXING_POLICY"
                        for target in node.targets)):
            policy = ast.literal_eval(node.value)
            return [
                [(entry["path"], entry["order"]) for entry in index]
                for index in policy["compositeIndexes"]
            ]
    raise AssertionError("ACTIVITY_LOGS_INDEXING_POLICY is missing from config.py.")


def _docstring_ids(tree):
    """Return the AST node IDs of docstrings, which describe queries rather than run them."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def _sql_strings(node, skipped_ids):
    """Yield SQL-bearing string literals and f-strings, with f-string values as placeholders."""
    for child in ast.walk(node):
        if id(child) in skipped_ids:
            continue
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            text = child.value
        elif isinstance(child, ast.JoinedStr):
            text = "".join(
                part.value if isinstance(part, ast.Constant) else "{expr}" for part in child.values
            )
        else:
            continue
        if SQL_PATTERN.search(text):
            yield child.lineno, text


def _scanned_sql():
    """Return (location, sql, composite indexes) for every V2 Control Center query string."""
    found = []
    route_tree = ast.parse(ROUTE.read_text(encoding="utf-8"))
    route_docstrings = _docstring_ids(route_tree)
    for node in ast.walk(route_tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith(V2_ROUTE_PREFIXES):
            found.extend(
                (f"{ROUTE.name}:{line} ({node.name})", text, ())
                for line, text in _sql_strings(node, route_docstrings)
            )
    for module, indexes in (
        (APP / "functions_control_center_dashboard.py", ()),
        (APP / "functions_control_center_groups.py", ()),
        (APP / "functions_control_center_public_workspaces.py", ()),
        (APP / "functions_control_center_activity.py", _activity_log_composite_indexes()),
        (APP / "functions_control_center_activity_display.py", ()),
    ):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        found.extend(
            (f"{module.name}:{line}", text, indexes)
            for line, text in _sql_strings(tree, _docstring_ids(tree))
        )
    return found


def _every_control_center_sql():
    """Return (location, sql) for every query string in the Control Center modules, V1 included."""
    found = []
    for module in (ROUTE, *CONTROL_CENTER_MODULES):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        found.extend((f"{module.name}:{line}", text) for line, text in _sql_strings(tree, _docstring_ids(tree)))
    return found


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_guard_rejects_reserved_keywords_as_property_names_and_aliases():
    for query in (
        "SELECT c.id FROM c WHERE c.group.group_id = @group_id",
        "SELECT TOP 20 c.id, c.group FROM c WHERE c.group_id = @group_id",
        "SELECT VALUE c.id FROM c WHERE CONTAINS(c.group.group_name, @search, true)",
        "SELECT c.value FROM c",
        "SELECT c.id FROM c ORDER BY c.order.top",
        "SELECT c.id AS value FROM c",
    ):
        problems = reserved_word_problems(query)
        assert problems, f"Guard accepted a reserved keyword: {query}"
        assert cosmos_query_problems(query), f"Combined guard accepted a reserved keyword: {query}"
    for query in (
        "SELECT c.id FROM c WHERE c['group']['group_id'] = @group_id",
        "SELECT c['group'] FROM c WHERE c['group'].group_name = @name",
        "SELECT c.group_id, c.grouping, c.values, c.first, c.last, c.all FROM c",
        "SELECT VALUE c.group_id FROM c WHERE c.type = 'document_metadata' GROUP BY c.group_id",
        "SELECT c.workspace_context.group_id AS group_id FROM c ORDER BY c.timestamp DESC",
    ):
        assert not reserved_word_problems(query), f"Guard rejected a valid property name: {query}"


def test_every_control_center_query_avoids_reserved_property_names():
    scanned = _every_control_center_sql()
    assert len(scanned) >= 60, f"Expected to scan the Control Center queries, found {len(scanned)}."
    failures = [
        f"{location}: {'; '.join(problems)}"
        for location, text in scanned
        for problems in [reserved_word_problems(text)]
        if problems
    ]
    assert not failures, "Reserved keywords used as Cosmos property names:\n" + "\n".join(failures)


def test_generated_activity_and_group_queries_avoid_reserved_property_names():
    """The search and group filters are generated, so the static scan cannot see them."""
    from werkzeug.datastructures import MultiDict

    activity = _load("compat_activity", APP / "functions_control_center_activity.py")
    groups = _load("compat_groups", APP / "functions_control_center_groups.py")
    filters = activity.parse_activity_filters(MultiDict({
        "search": "finance", "workspace_type": "group", "workspace_id": "group-1",
        "group_id": "group-1", "user_id": "user-1", "status": "failed",
        "activity_type": ["token_usage", "group_status_change"],
    }))
    where, _ = activity.activity_query_context(filters, search_user_ids=["user-2"])
    assert not reserved_word_problems(where), reserved_word_problems(where)
    assert "c['group'].group_name" in where and "c['group'].group_id" in where
    assert activity.cosmos_property_path("group.group_name") == "c['group'].group_name"
    assert activity.cosmos_property_path("workspace_context.group_id") == "c.workspace_context.group_id"
    assert not reserved_word_problems(groups.NESTED_GROUP_ID)


def test_guard_rejects_query_shapes_the_python_sdk_cannot_run():
    for query in (
        "SELECT c.group_id, COUNT(1) AS total FROM c WHERE c.type = 'document_metadata' GROUP BY c.group_id",
        "SELECT VALUE COUNT(1) FROM ( SELECT DISTINCT c.user_id FROM c WHERE c.activity_type = 'user_login' )",
        "SELECT VALUE COUNT(DISTINCT c.user_id) FROM c",
        "SELECT c.id FROM c WHERE 1=1 ORDER BY c.display_name ASC, c.id ASC OFFSET @offset LIMIT @limit",
        "SELECT c.id FROM c ORDER BY {expr} {expr}, c.id ASC",
    ):
        assert cosmos_query_problems(query), f"Guard accepted an unsupported query: {query}"


def test_guard_allows_supported_query_shapes():
    activity_indexes = _activity_log_composite_indexes()
    for query in (
        "SELECT DISTINCT VALUE c.user_id FROM c WHERE c.activity_type = 'user_login'",
        "SELECT VALUE COUNT(1) FROM c WHERE c.workspace_type = @workspace_type",
        "SELECT VALUE c.status FROM c WHERE IS_DEFINED(c.status)",
        "SELECT c.id FROM c WHERE (1=1) AND (IS_DEFINED(c.email)) ORDER BY c.email DESC OFFSET @offset LIMIT @limit",
        "SELECT TOP 20 c.id FROM c WHERE c.group_id = @group_id ORDER BY c.timestamp DESC",
    ):
        assert_cosmos_query_supported(query)
    assert_cosmos_query_supported(
        "SELECT * FROM c ORDER BY c.timestamp DESC, c.id DESC, c.user_id DESC", activity_indexes,
    )
    assert cosmos_query_problems("SELECT * FROM c ORDER BY c.timestamp DESC, c.id DESC, c.user_id DESC")


def test_every_v2_control_center_query_is_supported_by_the_python_sdk():
    scanned = _scanned_sql()
    assert len(scanned) >= 25, f"Expected to scan the V2 Control Center queries, found {len(scanned)}."
    failures = [
        f"{location}: {'; '.join(problems)}"
        for location, text, indexes in scanned
        for problems in [cosmos_query_problems(text, indexes)]
        if problems
    ]
    assert not failures, "Unsupported Cosmos query shapes:\n" + "\n".join(failures)


def test_scan_covers_the_previously_failing_sections():
    locations = " ".join(location for location, _, _ in _scanned_sql())
    for expected in (
        "functions_control_center_dashboard.py", "_control_center_query_user_page",
        "_control_center_iter_users", "functions_control_center_groups.py",
        "api_v2_control_center_group_detail", "functions_control_center_activity_display.py",
    ):
        assert expected in locations, f"The compatibility scan no longer reaches {expected}."
    dashboard_sql = " ".join(
        text for location, text, _ in _scanned_sql()
        if location.startswith("functions_control_center_dashboard.py")
    )
    for expected in (
        "SELECT DISTINCT VALUE c.user_id", "SELECT VALUE c.status", "c.usage.total_tokens AS tokens",
        "c.activity_type,", "SELECT TOP @limit",
    ):
        assert expected in dashboard_sql, f"The dashboard scan no longer reaches {expected!r}."


def test_version_is_at_least_the_implementation_version():
    assert_app_version_at_least("0.261.297")


TESTS = [
    test_guard_rejects_query_shapes_the_python_sdk_cannot_run,
    test_guard_allows_supported_query_shapes,
    test_guard_rejects_reserved_keywords_as_property_names_and_aliases,
    test_every_v2_control_center_query_is_supported_by_the_python_sdk,
    test_every_control_center_query_avoids_reserved_property_names,
    test_generated_activity_and_group_queries_avoid_reserved_property_names,
    test_scan_covers_the_previously_failing_sections,
    test_version_is_at_least_the_implementation_version,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(TESTS)}/{len(TESTS)} Cosmos query compatibility checks passed")
