# test_v2_control_center_activity_logs_queries.py
"""
Functional tests for bounded Control Center activity queries, paging and export.
Version: 0.261.296
Implemented in: 0.261.284

Executes the actual dependency-neutral helper module with a query-contract storage fake.
No cloud calls, Flask bootstrap replacement, or production module mutations.
Since 0.261.296 every generated query also passes the Cosmos query guard, which rejects
reserved keywords used as dotted property names: the search field group.group_name made
every Activity Logs search fail with an HTTP 400 syntax error.
"""

import base64
import csv
import importlib.util
import json
import sys
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pytest
from werkzeug.datastructures import MultiDict

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(ROOT / "functional_tests"))
SPEC = importlib.util.spec_from_file_location("activity_queries", APP / "functions_control_center_activity.py")
activity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(activity)
NOW = datetime(2026, 10, 7, 14, tzinfo=timezone.utc)
ACTIVITY_INDEXES = [[(entry["path"], entry["order"]) for entry in activity.ACTIVITY_COMPOSITE_INDEX]]

from test_support.cosmos_query_guard import assert_cosmos_query_supported, reserved_word_problems


def filters(**values):
    return activity.parse_activity_filters(MultiDict({"date": "2026-10-01", **values}), NOW)


def partition_key(row):
    value = row.get("user_id")
    return (2, value) if isinstance(value, str) else (1, "") if "user_id" in row else (0, "")


def order_key(row):
    return row["timestamp"], row["id"], partition_key(row)


class QueryContainer:
    """Implements only the new feed's parameterized query and deterministic ordering."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def query_items(self, **kwargs):
        self.calls.append(kwargs)
        query = kwargs["query"]
        assert_cosmos_query_supported(query, ACTIVITY_INDEXES)
        assert query.startswith("SELECT TOP @limit ")
        assert query.endswith(activity.ACTIVITY_ORDER)
        assert "OFFSET" not in query and "COUNT" not in query
        assert kwargs["enable_cross_partition_query"] is True
        assert kwargs["max_item_count"] <= 200
        params = {item["name"]: item["value"] for item in kwargs["parameters"]}
        rows = []
        for row in self.rows:
            if not isinstance(row.get("timestamp"), str) or not isinstance(row.get("id"), str):
                continue
            if row.get("user_id") is not None and not isinstance(row["user_id"], str):
                continue
            if not params["@start"] <= row["timestamp"] < params["@end"] or row["timestamp"] > params["@snapshot"]:
                continue
            if "@types" in params and row.get("activity_type") not in params["@types"]:
                continue
            if "@user" in params and row.get("user_id") != params["@user"]:
                continue
            if "@model" in params and row.get("usage", {}).get("model") != params["@model"]:
                continue
            if "@cursor_time" in params:
                cursor_user = (2, params["@cursor_user"]) if "@cursor_user" in params else (
                    (1, "") if "AND NOT IS_DEFINED(c.user_id)" in query else (0, "")
                )
                boundary = (params["@cursor_time"], params["@cursor_id"], cursor_user)
                if order_key(row) >= boundary:
                    continue
            rows.append(row.copy())
        return sorted(rows, key=order_key, reverse=True)[:params["@limit"]]


def test_keyset_equal_timestamps_and_duplicate_ids_across_partitions():
    records = [
        {"id": f"record-{index:03d}", "timestamp": f"2026-10-01T12:00:0{index % 3}", "user_id": user}
        for index in range(70) for user in ("user-a", "user-z")
    ]
    records += [{"id": "shared", "timestamp": "2026-10-01T12:00:02", "user_id": None},
                {"id": "shared", "timestamp": "2026-10-01T12:00:02"}]
    container = QueryContainer(records)
    selected = filters()
    seen = []
    cursor = None
    while True:
        page = activity.activity_page(container, selected, page_size=7, cursor_value=cursor)
        seen.extend(page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert [order_key(row) for row in seen] == [order_key(row) for row in sorted(records, key=order_key, reverse=True)]
    assert len(seen) == len({order_key(row) for row in seen}) == 142
    assert len(container.calls) == 21


def test_partition_null_and_undefined_ties_on_page_boundaries():
    rows = [{"id": "same", "timestamp": "2026-10-01T12:00:00", "user_id": "u"},
            {"id": "same", "timestamp": "2026-10-01T12:00:00", "user_id": None},
            {"id": "same", "timestamp": "2026-10-01T12:00:00"}]
    container = QueryContainer(rows)
    selected = filters()
    seen = []
    cursor = None
    for _ in range(3):
        page = activity.activity_page(container, selected, page_size=1, cursor_value=cursor)
        seen.extend(page["items"])
        cursor = page["next_cursor"]
    assert [order_key(row) for row in seen] == [order_key(row) for row in rows]
    assert cursor is None


def test_malformed_partition_values_are_not_used_as_cursor_keys():
    container = QueryContainer([
        {"id": "array", "timestamp": "2026-10-01T12:00:00", "user_id": ["legacy"]},
        {"id": "valid", "timestamp": "2026-10-01T12:00:00", "user_id": "u", "activity_type": {}},
    ])
    page = activity.activity_page(container, filters())
    assert [row["id"] for row in page["items"]] == ["valid"]
    summary = activity.activity_summary(container, filters())
    assert summary["facets"] == [{"activity_type": "unknown", "count": 1}]


def test_timestamp_cutoff_survives_newer_inserts_and_cursor_keeps_stored_spelling():
    container = QueryContainer([
        {"id": "a", "timestamp": "2026-10-01T12:00:00.000001Z", "user_id": "u"},
        {"id": "b", "timestamp": "2026-10-01T12:00:00.000001+00:00", "user_id": "u"},
    ])
    selected = filters()
    first = activity.activity_page(container, selected, page_size=1)
    decoded = activity.decode_activity_cursor(first["next_cursor"], selected)
    assert decoded["timestamp"] == first["items"][0]["timestamp"]
    container.rows.append({"id": "new", "timestamp": "2099-01-01T00:00:00", "user_id": "u"})
    second = activity.activity_page(container, selected, page_size=1, cursor_value=first["next_cursor"])
    assert len(second["items"]) == 1
    assert second["snapshot"] == first["snapshot"]
    assert second["items"][0]["id"] != first["items"][0]["id"]


@pytest.mark.parametrize("size", [0, -1, 201])
def test_page_size_is_bounded(size):
    with pytest.raises(ValueError):
        activity.activity_page(QueryContainer([]), filters(), page_size=size)


def test_cursor_rejects_malformed_and_different_filter_scope():
    selected = filters()
    valid = activity.encode_activity_cursor(
        {"id": "x", "timestamp": "2026-10-01T01:00:00", "user_id": "u"}, selected, NOW.isoformat(),
    )
    for value in ("not base64", "x" * 4097, base64.b64encode(b"[]").decode()):
        with pytest.raises(ValueError):
            activity.decode_activity_cursor(value, selected)
    with pytest.raises(ValueError):
        activity.decode_activity_cursor(valid, filters(user_id="different"))


def test_filters_match_dashboard_contract_and_bind_every_value():
    selected = filters(
        activity_type=["token_usage", "chat_activity"], workspace_type="group",
        workspace_id="group' OR true", user_id="admin-id", token_type="chat", model="model'",
        status="failed", search="' OR true --",
    )
    where, parameters = activity.activity_query_context(selected)
    params = {item["name"]: item["value"] for item in parameters}
    assert params["@types"] == ["chat_activity", "token_usage"]
    assert params["@group"] == "group' OR true"
    assert params["@search"] == "' OR true --"
    assert params["@end"] == "2026-10-02"
    assert "OR true" not in where
    assert "c.changed_by.user_id = @user" in where and "c.admin_user_id = @user" in where
    assert "c['group'].group_id = @group" in where and "c.workspace_context.group_id = @group" in where
    assert "c.group." not in where
    assert "c.document.status" in where
    assert "c.usage.model = @model" in where
    assert not reserved_word_problems(where)
    public_where, public_params = activity.activity_query_context(filters(workspace_type="public_workspace", workspace_id="pub"))
    assert {"name": "@public", "value": "pub"} in public_params
    assert "c.workspace_type" not in public_where
    public_type_where, public_type_params = activity.activity_query_context(filters(workspace_type="public"))
    assert "c.workspace_type IN ('public', 'public_workspace')" in public_type_where
    assert "IS_STRING(c.workspace_context.public_workspace_id)" in public_type_where
    assert not [item for item in public_type_params if item["name"] == "@workspace_type"]


def test_person_filter_matches_every_actor_field():
    """Approvals, membership and status records name the actor outside the partition key."""
    where, parameters = activity.activity_query_context(filters(user_id="person-1"))
    for path in ("c.user_id", "c.admin_user_id", "c.requester_id", "c.added_by_user_id",
                 "c.changed_by_user_id", "c.changed_by.user_id", "c.removed_by.user_id",
                 "c.admin.user_id", "c.actor.user_id"):
        assert f"{path} = @user" in where
    assert [item["value"] for item in parameters if item["name"] == "@user"] == ["person-1"]


def test_a_specific_workspace_matches_records_without_a_workspace_type():
    """Member removals and role changes record the group but no workspace_type."""
    where, parameters = activity.activity_query_context(
        filters(workspace_type="group", workspace_id="group-1", group_id="group-1"))
    assert "c.workspace_type" not in where
    assert "c.group_id = @group" in where and "c['group'].group_id = @group" in where
    assert "c.workspace_context.group_workspace_id = @group" in where
    assert [item["value"] for item in parameters if item["name"] == "@group"] == ["group-1"]
    type_only, _ = activity.activity_query_context(filters(workspace_type="group"))
    assert "(c.workspace_type = 'group' OR IS_STRING(c.workspace_context.group_id)" in type_only
    assert "IS_STRING(c['group'].group_id)" in type_only
    public, _ = activity.activity_query_context(filters(workspace_type="public", workspace_id="p1"))
    for path in ("c.workspace_context.public_workspace_id", "c.public_workspace_id",
                 "c.public_workspace.public_workspace_id", "c.public_workspace.workspace_id", "c.workspace_id"):
        assert f"{path} = @public" in public, path
    public_type_only, _ = activity.activity_query_context(filters(workspace_type="public"))
    assert "IS_STRING(c.public_workspace.public_workspace_id)" in public_type_only
    assert not reserved_word_problems(public) and not reserved_word_problems(public_type_only)
    personal, personal_params = activity.activity_query_context(filters(workspace_type="personal", workspace_id="u1"))
    assert "c.workspace_type = @workspace_type" in personal and "c.user_id = @personal" in personal
    assert {"name": "@personal", "value": "u1"} in personal_params


def test_search_matches_people_without_changing_the_cursor_scope():
    selected = filters(search="jane")
    plain, plain_params = activity.activity_query_context(selected)
    assert "@search_people" not in plain and not [p for p in plain_params if p["name"] == "@search_people"]
    widened, params = activity.activity_query_context(selected, search_user_ids=["u-jane", "u-janet"])
    assert "ARRAY_CONTAINS(@search_people, c.user_id)" in widened
    assert "ARRAY_CONTAINS(@search_people, c.changed_by.user_id)" in widened
    assert {"name": "@search_people", "value": ["u-jane", "u-janet"]} in params
    assert "CONTAINS(c['group'].group_name, @search, true)" in widened
    assert not reserved_word_problems(widened)
    ignored, ignored_params = activity.activity_query_context(filters(), search_user_ids=["u-jane"])
    assert "@search_people" not in ignored and not [p for p in ignored_params if p["name"] == "@search_people"]
    rows = [{"id": f"r{index}", "timestamp": f"2026-10-01T12:00:0{index}", "user_id": "u-jane",
             "activity_type": "user_login"} for index in range(3)]
    container = QueryContainer(rows)
    first = activity.activity_page(container, selected, page_size=1, search_user_ids=["u-jane"])
    second = activity.activity_page(container, selected, page_size=1, cursor_value=first["next_cursor"],
                                    search_user_ids=["u-jane", "u-new"])
    assert second["items"] and second["items"][0]["id"] != first["items"][0]["id"]
    assert all({"name": "@search_people", "value": ids} in call["parameters"]
               for call, ids in zip(container.calls, (["u-jane"], ["u-jane", "u-new"])))


@pytest.mark.parametrize("values", [
    {"start_date": "2026-01-01", "end_date": "2027-01-02"},
    {"start_date": "2026-10-02", "end_date": "2026-10-01"},
    {"date": "invalid"}, {"workspace_type": "alien"},
    {"workspace_id": "missing-type"}, {"search": "x" * 201},
    {"activity_type": [str(index) for index in range(31)]},
])
def test_invalid_filters(values):
    with pytest.raises(ValueError):
        filters(**values)


def test_query_applies_date_type_user_and_model_filters():
    rows = [
        {"id": "in", "timestamp": "2026-10-01T23:59:59.999999Z", "user_id": "u", "activity_type": "token_usage", "usage": {"model": "m"}},
        {"id": "out", "timestamp": "2026-10-02T00:00:00", "user_id": "u", "activity_type": "token_usage"},
        {"id": "wrong-user", "timestamp": "2026-10-01T12:00:00", "user_id": "v", "activity_type": "token_usage"},
        {"id": "wrong-type", "timestamp": "2026-10-01T12:00:00", "user_id": "u", "activity_type": "user_login"},
    ]
    page = activity.activity_page(QueryContainer(rows), filters(user_id="u", activity_type="token_usage", model="m"))
    assert [row["id"] for row in page["items"]] == ["in"]


def test_summary_is_bounded_discloses_sampling_and_bucket_counts(monkeypatch):
    monkeypatch.setattr(activity, "ACTIVITY_SUMMARY_MAX", 3)
    rows = [{"id": str(index), "timestamp": "2026-10-01T12:00:00", "user_id": "u",
             "activity_type": "user_login"} for index in range(6)]
    container = QueryContainer(rows)
    summary = activity.activity_summary(container, filters())
    assert summary["truncated"] is True and summary["sample_size"] == 3
    assert summary["facets"] == [{"activity_type": "user_login", "count": 3}]
    assert sum(bin["count"] for bin in summary["histogram"]) == 3
    wide = activity.activity_summary(QueryContainer([]), filters(start_date="2026-01-01", end_date="2026-12-31"))
    assert len(wide["histogram"]) <= 31
    assert container.calls[0]["query"].startswith("SELECT TOP @limit c.timestamp, c.id, c.user_id, c.activity_type")


@pytest.mark.parametrize("value", ["=SUM(1)", "+1", "-1", "@cmd", "\tfoo", "\rfoo", "   =1", "\n@formula"])
def test_csv_injection(value):
    assert activity.activity_csv_cell(value).startswith("'")


def test_streamed_csv_reuses_filters_pages_and_caps_records(monkeypatch):
    monkeypatch.setattr(activity, "ACTIVITY_EXPORT_MAX", 4)
    rows = [{"id": str(index), "timestamp": "2026-10-01T12:00:00", "user_id": "=1",
             "activity_type": "user_login"} for index in range(7)]
    container = QueryContainer(rows)
    selected = filters(user_id="=1")
    first, snapshot = activity.query_activity_rows(container, selected, 2)
    stream = activity.activity_csv_stream(container, selected, first, snapshot)
    header = next(stream)
    assert header.strip() == ",".join(activity.ACTIVITY_EXPORT_HEADER)
    assert header.startswith("timestamp,id,user_id,activity_type,workspace_type,")
    assert header.strip().endswith(",raw_json")
    assert len(container.calls) == 1
    contents = header + "".join(stream)
    exported = list(csv.reader(StringIO(contents)))
    assert len(exported) == 6
    assert all(len(row) == len(activity.ACTIVITY_EXPORT_HEADER) for row in exported)
    assert all(row[2] == "'=1" for row in exported[1:-1])
    assert exported[-1][3] == "export_limit_reached"
    assert len({row[1] for row in exported[1:-1]}) == 4
    assert all({"name": "@user", "value": "=1"} in call["parameters"] for call in container.calls)
    assert json.loads(exported[1][-1])["user_id"] == "=1"


def test_csv_readable_columns_come_from_the_presenter_and_are_formula_safe():
    rows = [{"id": "a", "timestamp": "2026-10-01T12:00:01", "user_id": "u1", "activity_type": "token_usage",
             "workspace_type": "group"},
            {"id": "b", "timestamp": "2026-10-01T12:00:00", "user_id": "u2", "activity_type": "user_login"}]
    container = QueryContainer(rows)
    selected = filters(search="ada")
    first, snapshot = activity.query_activity_rows(container, selected, 200, search_user_ids=["u1"])
    batches = []

    def present(batch):
        batches.append([row["id"] for row in batch])
        return [("=Ada", "ada@example.test", "Token usage", "120 tokens · gpt", "group-1", "Research")
                if row["id"] == "a" else ("", "", "User login", "Signed in", "", "") for row in batch]

    contents = "".join(activity.activity_csv_stream(
        container, selected, first, snapshot, search_user_ids=["u1"], present_rows=present,
    ))
    exported = list(csv.reader(StringIO(contents)))
    assert batches == [["a", "b"]]
    by_id = {row[1]: dict(zip(activity.ACTIVITY_EXPORT_HEADER, row)) for row in exported[1:]}
    assert by_id["a"]["user_name"] == "'=Ada" and by_id["a"]["workspace_name"] == "Research"
    assert by_id["a"]["summary"] == "120 tokens · gpt" and by_id["b"]["activity"] == "User login"
    assert json.loads(by_id["a"]["raw_json"])["id"] == "a"
    broken = "".join(activity.activity_csv_stream(container, selected, first, snapshot, present_rows=lambda batch: []))
    assert all(len(row) == len(activity.ACTIVITY_EXPORT_HEADER) for row in csv.reader(StringIO(broken)))
    assert all({"name": "@search_people", "value": ["u1"]} in call["parameters"] for call in container.calls[:1])


def test_new_container_and_maintenance_index_contract():
    import ast
    tree = ast.parse((APP / "config.py").read_text(encoding="utf-8"))
    node = next(node for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "ACTIVITY_LOGS_INDEXING_POLICY" for target in node.targets))
    policy = ast.literal_eval(node.value)
    assert policy["compositeIndexes"] == [activity.ACTIVITY_COMPOSITE_INDEX]
    maintenance = (APP / "functions_cosmos_indexing.py").read_text(encoding="utf-8")
    assert "'container_name': cosmos_activity_logs_container_name" in maintenance
    assert "('/timestamp', 'descending'), ('/id', 'descending'), ('/user_id', 'descending')" in maintenance


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
