#!/usr/bin/env python3
# test_control_center_dashboard_owner_runtime.py
"""
Functional test for the Control Center dashboard's storage readers.
Version: 0.261.489
Implemented in: 0.261.489

This test ensures that the dashboard functions which read Cosmos run correctly against the
installed SDK's response types: query rows are plain values, and a point read returns the
SDK's CosmosDict with its ETag. It also ensures the token source filter reaches the queries
those functions send.
"""

import sys
from datetime import date
from pathlib import Path

from azure.cosmos._cosmos_responses import CosmosDict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))

# The application path is established above, before application imports.
import functions_control_center_dashboard as dashboard  # noqa: E402


class DashboardSdkContainer:
    """Plain query rows and installed-SDK point documents, as the real container returns."""

    def __init__(self, rows=(), documents=None):
        self.rows = list(rows)
        self.documents = documents or {}
        self.queries = []
        self.reads = []

    def query_items(self, query, parameters=None, enable_cross_partition_query=False):
        self.queries.append({
            "query": query,
            "parameters": {item["name"]: item["value"] for item in parameters or ()},
            "cross_partition": enable_cross_partition_query,
        })
        return iter(self.rows)

    def read_item(self, item, partition_key):
        self.reads.append((item, partition_key))
        if item not in self.documents:
            raise LookupError(item)
        return CosmosDict(
            {"id": item, "_etag": f'"{item}-etag"', **self.documents[item]}, response_headers={},
        )


PERIOD = dashboard.build_dashboard_period(date(2026, 11, 1), date(2026, 11, 2))


def test_count_queries_read_plain_aggregate_rows():
    """Counts and status tallies consume plain scalar rows from cross-partition queries."""
    counted = DashboardSdkContainer([7])
    assert dashboard.query_count(counted, "SELECT VALUE COUNT(1) FROM c") == 7
    assert dashboard.query_count(DashboardSdkContainer(), "SELECT VALUE COUNT(1) FROM c") == 0
    assert counted.queries[0]["cross_partition"] is True

    logins = DashboardSdkContainer(["u1", "u2", "u1"])
    assert dashboard.count_active_users(logins, PERIOD.start, PERIOD.end) == 2
    assert set(logins.queries[0]["parameters"]) == {"@start_date", "@end_date"}

    statuses = dashboard.status_rows(DashboardSdkContainer(["active", "active", None, 3]))
    assert {row["status"]: row["count"] for row in statuses} == {"active": 2, None: 1, "3": 1}


def test_token_readers_apply_the_source_filter():
    """The total and the breakdown send the selected source's predicate with the query."""
    filters = dashboard.extract_token_filters({"token_source": "plan"})
    clause = dashboard.token_source_clause("plan")
    assert clause

    total = DashboardSdkContainer([1500])
    assert dashboard.token_total(total, PERIOD.start, PERIOD.end, filters) == 1500
    assert clause in total.queries[0]["query"]
    assert dashboard.token_total(DashboardSdkContainer([None]), PERIOD.start, PERIOD.end, {}) == 0

    rows = [
        {"timestamp": "2026-11-01T10:00:00", "token_type": "chat", "model": "gpt-4o", "tokens": 1000,
         "user_id": "u1", "group_id": "g1"},
        {"timestamp": "2026-11-02T09:00:00", "token_type": "chat", "model": "gpt-4o-mini", "tokens": 500,
         "user_id": "u1"},
    ]
    breakdown = DashboardSdkContainer(rows)
    usage = dashboard.aggregate_token_usage(breakdown, PERIOD, filters)
    assert clause in breakdown.queries[0]["query"]
    assert usage["total"] == 1500
    assert usage["by_model"] == {"gpt-4o": 1000, "gpt-4o-mini": 500}
    assert usage["by_type"]["chat"] == 1500
    assert usage["consumers"]["users"] == {"u1": 1500}
    assert [day["date"] for day in usage["token_usage_by_type"]] == ["2026-11-01", "2026-11-02"]

    # Without a source the queries carry no source predicate at all.
    unfiltered = DashboardSdkContainer(rows)
    dashboard.aggregate_token_usage(unfiltered, PERIOD, dashboard.extract_token_filters({}))
    assert clause not in unfiltered.queries[0]["query"]


def test_activity_rows_are_streamed_for_one_user_or_all():
    """The activity projection is returned as it arrives and narrows to a user on request."""
    row = {"timestamp": "2026-11-01T10:00:00", "activity_type": "user_login", "user_id": "u1"}
    container = DashboardSdkContainer([row])
    assert list(dashboard._activity_rows(container, PERIOD)) == [row]
    assert "@activity_user_id" not in container.queries[0]["parameters"]
    assert list(dashboard._activity_rows(container, PERIOD, user_id="u1")) == [row]
    assert container.queries[1]["parameters"]["@activity_user_id"] == "u1"


def test_entity_names_resolve_from_sdk_point_documents():
    """A point read's CosmosDict is described by field access; a missing record is not an error."""
    dashboard._control_center_entity_name_cache.clear()
    users = DashboardSdkContainer(documents={"u1": {"display_name": "Avery Lee", "email": "avery@example.test"}})
    groups = DashboardSdkContainer(documents={"g1": {"name": "Finance"}})
    stores = dashboard.DashboardStores(activity_logs=None, user_settings=users, groups=groups)
    try:
        names = dashboard.resolve_entity_names(stores, {"users": ["u1", "gone"], "groups": ["g1"]})
        assert names["users"]["u1"] == {"name": "Avery Lee", "detail": "avery@example.test", "found": True}
        assert names["users"]["gone"]["found"] is False
        assert names["groups"]["g1"] == {"name": "Finance", "detail": "", "found": True}
        # Each record is read by its own ID as the partition key, and only once while cached.
        assert users.reads == [("u1", "u1"), ("gone", "gone")]
        dashboard.resolve_entity_names(stores, {"users": ["u1"]})
        assert users.reads == [("u1", "u1"), ("gone", "gone")]
    finally:
        dashboard._control_center_entity_name_cache.clear()


def test_entity_search_reads_plain_query_rows():
    """Search results are built from plain rows, skipping any without an ID."""
    users = DashboardSdkContainer([
        {"id": "u1", "display_name": "Avery Lee", "email": "avery@example.test"},
        {"display_name": "No identifier"},
    ])
    stores = dashboard.DashboardStores(activity_logs=None, user_settings=users)
    assert dashboard.find_entities(stores, "users", "  Avery ") == [
        {"id": "u1", "name": "Avery Lee", "email": "avery@example.test"},
    ]
    assert users.queries[0]["parameters"]["@search"] == "avery"
    assert dashboard.find_entities(stores, "groups", "finance") == []


def run_all():
    tests = [
        test_count_queries_read_plain_aggregate_rows,
        test_token_readers_apply_the_source_filter,
        test_activity_rows_are_streamed_for_one_user_or_all,
        test_entity_names_resolve_from_sdk_point_documents,
        test_entity_search_reads_plain_query_rows,
    ]
    for test in tests:
        print(f"Testing {test.__name__}...")
        try:
            test()
            print("Test passed!")
        except Exception as error:
            print(f"Test failed: {error}")
            import traceback
            traceback.print_exc()
            return False
    return True


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
