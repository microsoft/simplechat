# test_control_center_usage.py
"""
Runtime usage aggregation, privacy, and query regression tests.
Version: 0.261.447
Implemented in: 0.261.447
"""

import csv
import json
import sys
from io import StringIO
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

import functions_control_center_usage as usage
from functions_control_center_activity import activity_query_context, parse_activity_filters
from runtime_usage import UsageTarget, build_usage_record, configured_host


class UsageQueryStore:
    """Query rows are plain dictionaries; this double has no point/write API."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def query_items(self, **kwargs):
        self.queries.append(kwargs)
        yield from self.rows


def event(index, *, user="user-1", entity_id="a1", scope="personal", duration=10, outcome="succeeded"):
    return build_usage_record(
        UsageTarget("action", entity_id, "Example action", scope, user, "openapi",
                    "api.example.test", "managed_identity", "get_items"),
        user_id=user, attempt_id=f"attempt-{index}", outcome=outcome, duration_ms=duration,
    )


def report(store, **kwargs):
    filters = parse_activity_filters({"start_date": "2026-01-01", "end_date": "2026-12-31", **kwargs})
    where, params = activity_query_context(filters)
    return usage.usage_report(store, where, params, refresh=True)


def test_counts_full_range_beyond_activity_sample_and_unions_users():
    rows = [event(i, entity_id=f"a{i % 2}") for i in range(5005)]
    rows.append(event(5006, user="user-2", outcome="failed", duration=None))
    result = report(UsageQueryStore(rows))
    total = result["totals"]["action"]
    assert result["complete"] is True
    assert total["invocations"] == 5006
    assert total["unique_users"] == 2
    assert sum(group["unique_users"] for group in result["entities"]) == 3
    assert total["duration_count"] == 5005
    assert total["average_duration_ms"] == 10
    assert total["outcomes"] == {"succeeded": 5005, "failed": 1}


def test_same_names_in_different_configuration_scopes_do_not_merge():
    first = event(1)
    second = event(2, scope="global")
    second["runtime_usage"]["scope_id"] = "global"
    result = report(UsageQueryStore([first, second]))
    assert len(result["entities"]) == 2
    assert result["totals"]["action"]["unique_users"] == 1


def test_legacy_fields_stay_unknown_and_raw_content_never_leaves_projection():
    row = {
        "id": "old", "timestamp": "2026-01-01", "activity_type": "workflow_run",
        "user_id": "u1", "workspace_type": "personal",
        "legacy_entity_id": "w1", "legacy_name": "Scheduled workflow", "legacy_outcome": "completed",
        "run": {"error": "PRIVATE_ERROR", "response_preview": "PRIVATE_RESPONSE"},
    }
    modern = event(2)
    modern["runtime_usage"]["arbitrary"] = "PRIVATE_PAYLOAD"
    result = report(UsageQueryStore([row, modern]))
    total = result["totals"]["workflow"]
    assert total["legacy_records"] == 1
    assert total["outcomes"] == {"succeeded": 1}
    assert total["average_duration_ms"] is None
    legacy = next(group for group in result["entities"] if group["kind"] == "workflow")
    assert legacy["auth_type"] == "unknown"
    encoded = json.dumps(result) + usage.usage_csv(result)
    assert "PRIVATE_" not in encoded
    assert '"_users"' not in encoded


def test_filter_values_are_parameters_and_dates_are_end_exclusive():
    filters = parse_activity_filters({
        "start_date": "2026-02-01", "end_date": "2026-02-02", "usage_kind": "action",
        "usage_entity_id": "' OR true", "usage_host": "api.example.test", "usage_auth": "api_key",
        "usage_operation": "get_items", "usage_outcome": "failed",
    })
    where, params = activity_query_context(filters)
    assert "' OR true" not in where
    values = {item["name"]: item["value"] for item in params}
    assert values["@usage_entity_id"] == "' OR true"
    assert values["@end"] == "2026-02-03"
    assert "c.runtime_usage.endpoint_host" in where
    assert values["@usage_outcome"] == "failed"


def test_legacy_public_scope_matches_report_and_drill_through():
    row = {
        "id": "public-old", "activity_type": "workflow_run", "user_id": "u1",
        "workspace_type": "public", "legacy_entity_id": "w1",
        "legacy_public_id": "workspace-1", "legacy_outcome": "completed",
    }
    result = report(UsageQueryStore([row]))
    assert result["entities"][0]["scope_id"] == "workspace-1"
    filters = parse_activity_filters({"usage_scope_id": "workspace-1"})
    where, params = activity_query_context(filters)
    assert "c.workspace_context.public_workspace_id" in where
    assert {"name": "@usage_scope_id", "value": "workspace-1"} in params


@pytest.mark.parametrize("args", [
    {"usage_kind": "prompt"}, {"usage_outcome": "PRIVATE"},
    {"usage_host": "x" * 257}, {"start_date": "2025-01-01", "end_date": "2026-12-31"},
])
def test_invalid_filters_are_rejected(args):
    with pytest.raises(ValueError):
        parse_activity_filters(args)


def test_query_failure_or_budget_exhaustion_never_returns_partial_totals(monkeypatch):
    monkeypatch.setattr(usage, "USAGE_SCAN_LIMIT", 1)
    with pytest.raises(usage.UsageQueryLimitError):
        report(UsageQueryStore([event(1), event(2)]))

    class FailedStore:
        def query_items(self, **kwargs):
            raise RuntimeError("PRIVATE_PROVIDER")

    with pytest.raises(RuntimeError):
        report(FailedStore())


def test_cache_is_bounded_copied_and_refreshable():
    store = UsageQueryStore([event(1)])
    where, params = activity_query_context(parse_activity_filters({}))
    first = usage.usage_report(store, where, params)
    first["totals"]["action"]["invocations"] = 999
    cached = usage.usage_report(store, where, params)
    assert cached["totals"]["action"]["invocations"] == 1
    assert len(store.queries) == 1
    store.rows.append(event(2))
    refreshed = usage.usage_report(store, where, params, refresh=True)
    assert refreshed["totals"]["action"]["invocations"] == 2


def test_export_is_metadata_only_and_escapes_spreadsheet_formulas():
    row = event(1)
    row["runtime_usage"]["name"] = "=PRIVATE_FORMULA"
    result = report(UsageQueryStore([row]))
    content = usage.usage_csv(result)
    parsed = list(csv.DictReader(StringIO(content)))
    assert parsed[0]["name"] == "'=PRIVATE_FORMULA"
    assert "raw_json" not in content
    query = UsageQueryStore([])
    report(query)
    sql = query.queries[0]["query"]
    assert "SELECT *" not in sql
    assert "run.error" not in sql


@pytest.mark.parametrize("url,host", [
    ("https://user:PRIVATE@api.example.test/path/PRIVATE?q=PRIVATE#PRIVATE", "api.example.test"),
    ("https://api.example.test:8443/path", "api.example.test"),
    ("not an endpoint", "unknown"),
    ("javascript:PRIVATE", "unknown"),  # xss-check: ignore -- invalid-scheme rejection fixture, never rendered.
    ("https://[::1]:8443/private", "::1"),
])
def test_configured_host_drops_all_url_content(url, host):
    value = configured_host(url)
    assert value == host
