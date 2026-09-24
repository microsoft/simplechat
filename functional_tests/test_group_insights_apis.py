# test_group_insights_apis.py
"""
Functional test for the native group insights: activity, statistics and the document count.
Version: 0.261.153
Implemented in: 0.261.153

``GET /api/groups/<group_id>/insights/activity``, ``/insights/stats`` and
``/insights/file-count`` run for real in ``test_support/group_settings_harness.py``.
Its activity logs container evaluates exactly the aliased activity query and the four
classic statistics queries, as Cosmos evaluates them, and refuses any other query, so
the classic routes run beside the native ones over the same records. This test pins:

- the activity feed: the records the classic feed reads, in its order and limits,
  each projected to ``{id, occurred_at, type, summary, actor}`` with a reviewed
  summary, and nothing identifying beyond a current member's display name, although
  the stored records carry file names, titles, emails, errors and conversation ids;
- the statistics: the classic figures over the same window, without the invented
  ``storageLimit``; strict window parameters with a 366-day cap on custom ranges; and
  a 503 rather than a zero figure when any query fails;
- the document count: the owner only, from ``count_current_group_documents``;
- access in every group status, and the session, role and feature gates.
"""

from datetime import datetime, timedelta

import pytest

from test_support.group_directory_harness import person
from test_support.group_settings_harness import EXPECTED_NATIVE_ACTIVITY_QUERY, group_settings_environment


GROUP = "group-1"
ACTIVITY_PATH = f"/api/groups/{GROUP}/insights/activity"
STATS_PATH = f"/api/groups/{GROUP}/insights/stats"
FILE_COUNT_PATH = f"/api/groups/{GROUP}/insights/file-count"
STATS_UNAVAILABLE = {"error": "Group statistics are unavailable right now. Try again.",
                     "error_code": "group_stats_unavailable"}
ACTIVITY_UNAVAILABLE = {"error": "Group activity is unavailable right now. Try again.",
                        "error_code": "group_activity_unavailable"}
STATUSES = ("active", "upload_disabled", "locked", "inactive", "archived")


@pytest.fixture(scope="module")
def module_env():
    with group_settings_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    module_env.seed_group(GROUP, status="active")
    module_env.as_user("owner-1")
    yield module_env
    module_env.reset()


def answer(response):
    assert response.headers["Cache-Control"] == "no-store", dict(response.headers)
    return response.get_json()


def assert_error(response, status, error_code, message=None):
    body = answer(response)
    assert response.status_code == status, body
    assert set(body) == {"error", "error_code"}, body
    assert body["error_code"] == error_code
    if message is not None:
        assert body["error"] == message
    return body


def record(record_id, activity_type, when, user_id="member-1", group_id=GROUP, **fields):
    """An activity record shaped as the activity logging writers shape it."""
    body = {"id": record_id, "user_id": user_id, "activity_type": activity_type, "timestamp": when,
            "created_at": when, "workspace_type": "group", "workspace_context": {"group_id": group_id}}
    body.update(fields)
    return body


def seed(env, *records):
    for body in records:
        env.activity_logs.seed_activity(body)


def feed(env, **query):
    response = env.call("GET", ACTIVITY_PATH, query_string=query or None)
    body = answer(response)
    assert response.status_code == 200, body
    return body


def one(env, body):
    env.activity_logs.records.clear()
    seed(env, body)
    [entry] = feed(env)["activity"]
    return entry


def iso(days_ago=0, hours=0):
    return (datetime.utcnow() - timedelta(days=days_ago, hours=hours)).isoformat()


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------

def seed_sensitive_history(env):
    status_change = record(
        "status-1", "group_status_change", "2026-09-20T07:00:00", user_id="",
        group={"group_id": GROUP, "group_name": "Secret Group Name"},
        status_change={"old_status": "active", "new_status": "locked", "changed_at": "2026-09-20T07:00:00",
                       "reason": "Legal hold on Project Falcon"},
        changed_by={"user_id": "control-center-admin", "email": "root.admin@example.test"},
    )
    seed(
        env,
        record("doc-1", "document_creation", "2026-09-20T10:00:00",
               document={"document_id": "doc-secret-id", "file_name": "merger-plan.docx", "file_type": ".docx",
                         "file_size_bytes": 1234, "page_count": 3, "version": 1},
               embedding_usage={"total_tokens": 99, "model_deployment_name": "embed-secret"},
               document_metadata={"author": "Ana Applicant", "title": "Project Falcon",
                                  "abstract": "Confidential abstract", "keywords": ["acquisition"]}),
        record("tok-1", "token_usage", "2026-09-20T09:00:00", token_type="chat",
               usage={"total_tokens": 1234, "model": "gpt-secret-deployment", "prompt_tokens": 1000,
                      "completion_tokens": 234},
               chat_details={"conversation_id": "conv-secret", "message_id": "msg-secret"}),
        record("tok-2", "token_usage", "2026-09-20T08:00:00", token_type="embedding",
               usage={"total_tokens": 1, "model": "embed-secret"},
               embedding_details={"document_id": "doc-secret-id", "file_name": "merger-plan.docx"}),
        status_change,
        record("sync-1", "file_sync", "2026-09-20T06:00:00", user_id=GROUP, action="run_failed",
               description="File Sync run failed",
               workspace_context={"scope_type": "group", "source_id": "src-secret",
                                  "source_name": "Finance SharePoint", "group_id": GROUP,
                                  "public_workspace_id": None},
               additional_context={"error": "401 from https://contoso.sharepoint.com token=abc"}),
        record("conv-1", "conversation_creation", "2026-09-20T05:00:00",
               conversation={"conversation_id": "conv-secret", "title": "Salary review"}),
        record("wf-1", "workflow_run", "2026-09-20T04:00:00", user_id="gone-1",
               workflow={"name": "Nightly digest", "error": "Traceback (most recent call last)"}),
        record("odd-1", "user_login", "2026-09-20T03:00:00", login_method="sso", email="max.member@example.test"),
    )


SENSITIVE_VALUES = (
    "merger-plan", "Project Falcon", "Confidential abstract", "Ana Applicant", "acquisition", "embed-secret",
    "gpt-secret", "conv-secret", "msg-secret", "Secret Group Name", "Legal hold", "root.admin",
    "control-center-admin", "src-secret", "Finance SharePoint", "contoso", "token=abc", "Salary review", "gone-1",
    "Nightly digest", "Traceback", "sso", "@example.test", "member-1", "owner-1", "doc-secret-id", "prompt_tokens",
    "workspace_context", "_etag",
)


def test_the_feed_projects_each_record_to_reviewed_fields(env):
    seed_sensitive_history(env)
    body = feed(env)
    assert body == {"limit": 50, "activity": [
        {"id": "doc-1", "occurred_at": "2026-09-20T10:00:00Z", "type": "document_creation",
         "summary": "Uploaded a document", "actor": {"kind": "member", "display_name": "Max Member"}},
        {"id": "tok-1", "occurred_at": "2026-09-20T09:00:00Z", "type": "token_usage",
         "summary": "Used 1,234 tokens in chat", "actor": {"kind": "member", "display_name": "Max Member"}},
        {"id": "tok-2", "occurred_at": "2026-09-20T08:00:00Z", "type": "token_usage",
         "summary": "Used 1 token processing a document", "actor": {"kind": "member", "display_name": "Max Member"}},
        {"id": "status-1", "occurred_at": "2026-09-20T07:00:00Z", "type": "group_status_change",
         "summary": "Changed the group status from Active to Locked", "actor": {"kind": "system"}},
        {"id": "sync-1", "occurred_at": "2026-09-20T06:00:00Z", "type": "file_sync",
         "summary": "File Sync failed", "actor": {"kind": "system"}},
        {"id": "conv-1", "occurred_at": "2026-09-20T05:00:00Z", "type": "conversation_creation",
         "summary": "Started a conversation", "actor": {"kind": "member", "display_name": "Max Member"}},
        {"id": "wf-1", "occurred_at": "2026-09-20T04:00:00Z", "type": "workflow_run",
         "summary": "Ran a workflow", "actor": {"kind": "former_member"}},
        {"id": "odd-1", "occurred_at": "2026-09-20T03:00:00Z", "type": "other",
         "summary": "Other activity", "actor": {"kind": "member", "display_name": "Max Member"}},
    ]}


def test_nothing_identifying_leaves_the_feed(env):
    seed_sensitive_history(env)
    native = env.call("GET", ACTIVITY_PATH).get_data(as_text=True)
    classic = env.call("GET", f"/api/groups/{GROUP}/activity").get_data(as_text=True)
    for value in SENSITIVE_VALUES:
        assert value not in native, value
    # The fixture does carry them: the classic feed returns the raw records.
    assert all(value in classic for value in ("merger-plan", "Project Falcon", "token=abc", "root.admin"))


def test_only_the_aliased_fields_are_read(env):
    seed_sensitive_history(env)
    feed(env, limit="20")
    assert env.activity_logs.queries == [
        {"query": EXPECTED_NATIVE_ACTIVITY_QUERY, "parameters": {"@limit": 20, "@group_id": GROUP}},
    ]


@pytest.mark.parametrize("activity_type,summary", [
    ("document_creation", "Uploaded a document"),
    ("document_deletion", "Deleted a document"),
    ("document_metadata_update", "Updated a document's details"),
    ("conversation_creation", "Started a conversation"),
    ("conversation_deletion", "Deleted a conversation"),
    ("conversation_archival", "Archived a conversation"),
    ("agent_creation", "Created an agent"),
    ("agent_update", "Updated an agent"),
    ("agent_deletion", "Deleted an agent"),
    ("agent_run", "Ran an agent"),
    ("action_creation", "Created an action"),
    ("action_update", "Updated an action"),
    ("action_deletion", "Deleted an action"),
    ("workflow_creation", "Created a workflow"),
    ("workflow_update", "Updated a workflow"),
    ("workflow_deletion", "Deleted a workflow"),
    ("workflow_run", "Ran a workflow"),
    ("user_login", "Other activity"),
    ("", "Other activity"),
])
def test_each_activity_type_has_a_reviewed_summary(env, activity_type, summary):
    entry = one(env, record("r-1", activity_type, "2026-09-20T10:00:00"))
    assert entry["summary"] == summary
    assert entry["type"] == (activity_type if summary != "Other activity" else "other")


@pytest.mark.parametrize("usage,token_type,summary", [
    ({"total_tokens": 1}, "chat", "Used 1 token in chat"),
    ({"total_tokens": 2}, "chat", "Used 2 tokens in chat"),
    ({"total_tokens": 1234567}, "embedding", "Used 1,234,567 tokens processing a document"),
    ({"total_tokens": 0}, "chat", "Used 0 tokens in chat"),
    ({"total_tokens": 12.9}, None, "Used 12 tokens"),
    ({"total_tokens": 7}, "image", "Used 7 tokens"),
    ({"total_tokens": None}, "chat", "Used tokens in chat"),
    ({"total_tokens": True}, "chat", "Used tokens in chat"),
    ({"total_tokens": -5}, "chat", "Used tokens in chat"),
    ({"total_tokens": "100"}, "chat", "Used tokens in chat"),
    ({}, "embedding", "Used tokens processing a document"),
    (None, None, "Used tokens"),
])
def test_token_usage_summaries_take_only_a_whole_count(env, usage, token_type, summary):
    body = record("t-1", "token_usage", "2026-09-20T10:00:00", token_type=token_type)
    if usage is not None:
        body["usage"] = usage
    assert one(env, body)["summary"] == summary


@pytest.mark.parametrize("old,new,summary", [
    ("active", "locked", "Changed the group status from Active to Locked"),
    ("upload_disabled", "inactive", "Changed the group status from Uploads disabled to Inactive"),
    ("locked", "active", "Changed the group status from Locked to Active"),
    ("active", "archived", "Changed the group status"),
    (None, "locked", "Changed the group status"),
])
def test_status_changes_name_only_known_statuses(env, old, new, summary):
    body = record("s-1", "group_status_change", "2026-09-20T10:00:00",
                  status_change={"old_status": old, "new_status": new, "reason": "Do not show"})
    entry = one(env, body)
    assert entry["summary"] == summary


@pytest.mark.parametrize("action,summary", [
    ("source_created", "Added a File Sync source"),
    ("source_updated", "Updated a File Sync source"),
    ("source_deleted", "Removed a File Sync source"),
    ("run_completed", "File Sync finished"),
    ("run_failed", "File Sync failed"),
    ("source_tested", "File Sync activity"),
    (None, "File Sync activity"),
])
def test_file_sync_summaries(env, action, summary):
    assert one(env, record("f-1", "file_sync", "2026-09-20T10:00:00", action=action))["summary"] == summary


@pytest.mark.parametrize("user_id,actor", [
    ("owner-1", {"kind": "member", "display_name": "Olive Owner"}),
    ("admin-1", {"kind": "member", "display_name": "Adam Admin"}),
    ("member-1", {"kind": "member", "display_name": "Max Member"}),
    ("quiet-1", {"kind": "member", "display_name": ""}),
    ("gone-1", {"kind": "former_member"}),
    ("", {"kind": "system"}),
    (GROUP, {"kind": "system"}),
    (42, {"kind": "system"}),
])
def test_the_actor_is_named_only_when_they_are_a_current_member(env, user_id, actor):
    stored = env.stored_group(GROUP)
    stored["users"].append({"userId": "quiet-1", "email": "quiet@example.test"})
    env.groups.seed(stored)
    assert one(env, record("a-1", "agent_run", "2026-09-20T10:00:00", user_id=user_id))["actor"] == actor


@pytest.mark.parametrize("changed_by,actor", [
    ({"user_id": "admin-1", "email": "adam.admin@example.test"}, {"kind": "member", "display_name": "Adam Admin"}),
    ({"user_id": "control-center-admin", "email": "root@example.test"}, {"kind": "system"}),
    ({}, {"kind": "system"}),
    (None, {"kind": "system"}),
])
def test_a_status_change_is_attributed_to_whoever_changed_it(env, changed_by, actor):
    body = record("s-1", "group_status_change", "2026-09-20T10:00:00", user_id="member-1",
                  status_change={"old_status": "active", "new_status": "locked"})
    if changed_by is not None:
        body["changed_by"] = changed_by
    assert one(env, body)["actor"] == actor


@pytest.mark.parametrize("stored,shown", [
    ("2026-09-20T10:00:00", "2026-09-20T10:00:00Z"),
    ("2026-09-20T10:00:00.123456", "2026-09-20T10:00:00.123456Z"),
    ("2026-09-20T12:00:00+02:00", "2026-09-20T10:00:00Z"),
    ("2026-09-20T10:00:00Z", "2026-09-20T10:00:00Z"),
    ("yesterday", None),
    ("   ", None),
])
def test_timestamps_are_utc_with_a_z(env, stored, shown):
    assert one(env, record("t-1", "agent_run", stored))["occurred_at"] == shown


def test_a_record_id_that_is_not_text_is_omitted(env):
    assert one(env, record(7, "agent_run", "2026-09-20T10:00:00"))["id"] is None


def seed_long_history(env):
    seed(env, *(record(f"r-{index:02d}", "agent_run", f"2026-09-{1 + index // 24:02d}T{index % 24:02d}:00:00")
                for index in range(55)))
    seed(env, record("other-group", "agent_run", "2026-09-30T10:00:00", group_id="group-2"))
    seed(env, {"id": "membership", "user_id": "owner-1", "activity_type": "group_member_added",
               "timestamp": "2026-09-30T11:00:00", "group_id": GROUP, "group": {"group_id": GROUP}})


@pytest.mark.parametrize("limit", [None, "10", "20", "50"])
def test_the_feed_reads_the_records_the_classic_feed_reads_in_its_order(env, limit):
    seed_long_history(env)
    query = {"limit": limit} if limit else None
    native = [entry["id"] for entry in feed(env, **(query or {}))["activity"]]
    classic = [entry["id"] for entry in env.call("GET", f"/api/groups/{GROUP}/activity", query_string=query).get_json()]
    assert native == classic
    assert len(native) == int(limit or 50)
    assert native[0] == "r-54" and "other-group" not in native and "membership" not in native


@pytest.mark.parametrize("value", ["5", "0", "-10", "abc", "10.0", "010", " 10", "100", ""])
def test_the_limit_is_10_20_or_50(env, value):
    assert_error(env.call("GET", ACTIVITY_PATH, query_string={"limit": value}), 400, "invalid_request",
                 "The limit must be 10, 20 or 50.")
    assert env.activity_logs.queries == []


def test_the_feed_takes_only_one_limit(env):
    assert_error(env.call("GET", f"{ACTIVITY_PATH}?limit=10&limit=20"), 400, "invalid_request",
                 "Give each query parameter only once.")
    assert_error(env.call("GET", ACTIVITY_PATH, query_string={"page": "2"}), 400, "invalid_request",
                 "Use only the limit query parameter.")


def test_a_failed_activity_query_is_a_data_free_503(env):
    seed_sensitive_history(env)
    env.activity_logs.fail_queries = 1
    response = env.call("GET", ACTIVITY_PATH)
    assert response.status_code == 503
    assert answer(response) == ACTIVITY_UNAVAILABLE
    assert env.logs[-1][0] == "[WORKSPACE_ROUTE] Group activity read failed."
    assert env.logs[-1][2] == {"error_type": "CosmosHttpResponseError"}


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def seed_stats_history(env):
    env.groups.records.clear()
    env.seed_group(GROUP, status="active", metrics={"document_metrics": {
        "total_documents": 12, "storage_account_size": 2048, "ai_search_size": 512,
    }})
    created_only = record("u-created", "document_creation", None, created_at=iso(5))
    created_only.pop("timestamp")
    seed(
        env,
        record("t-1", "token_usage", iso(1), usage={"total_tokens": 100, "model": "m"}),
        record("t-2", "token_usage", iso(3), usage={"total_tokens": 250, "model": "m"}),
        record("t-3", "token_usage", iso(20), usage={"total_tokens": 1000, "model": "m"}),
        record("t-4", "token_usage", iso(60), usage={"total_tokens": 5000, "model": "m"}),
        record("t-5", "token_usage", iso(200), usage={"total_tokens": 7, "model": "m"}),
        record("u-1", "document_creation", iso(0, hours=1)),
        record("u-2", "document_creation", iso(2)),
        record("u-3", "document_creation", iso(2)),
        record("u-4", "document_creation", iso(45)),
        created_only,
        record("d-1", "document_deletion", iso(4)),
        record("d-2", "document_deletion", iso(80)),
        record("x-1", "token_usage", iso(1), group_id="group-2", usage={"total_tokens": 999999}),
        record("x-2", "document_creation", iso(1), group_id="group-2"),
    )


def stats(env, **query):
    response = env.call("GET", STATS_PATH, query_string=query or None)
    body = answer(response)
    assert response.status_code == 200, body
    assert set(body) == {"stats"}
    return body["stats"]


def custom_range(days):
    end = datetime.utcnow().date()
    return {"start_date": (end - timedelta(days=days - 1)).isoformat(), "end_date": end.isoformat()}


@pytest.mark.parametrize("query,tokens,uploads,deletes", [
    ({}, 1350, 4, 1),
    ({"days": "7"}, 350, 4, 1),
    ({"days": "30"}, 1350, 4, 1),
    ({"days": "90"}, 6350, 5, 2),
    ("custom-10", 350, 4, 1),
])
def test_the_statistics_are_the_classic_figures_without_the_storage_limit(env, query, tokens, uploads, deletes):
    seed_stats_history(env)
    query = custom_range(10) if query == "custom-10" else query
    native = stats(env, **query)
    classic = env.call("GET", f"/api/groups/{GROUP}/stats", query_string=query or None).get_json()
    assert classic.pop("storageLimit") == 10737418240
    assert "storageLimit" not in native
    assert native == classic
    assert native["totalTokens"] == tokens
    assert sum(native["documentActivity"]["uploads"]) == uploads
    assert sum(native["documentActivity"]["deletes"]) == deletes
    assert sum(native["tokenUsage"]["data"]) == tokens
    assert (native["totalDocuments"], native["storageUsed"], native["totalMembers"]) == (12, 2048, 4)
    assert native["storage"] == {"ai_search_size": 512, "storage_account_size": 2048}


def test_the_window_is_reported_as_the_classic_window(env):
    window = stats(env, days="7")["window"]
    assert (window["type"], window["days"], window["label"]) == ("days", 7, "Last 7 Days")
    window = stats(env, **custom_range(366))["window"]
    assert (window["type"], window["days"]) == ("custom", 366)


@pytest.mark.parametrize("query,message", [
    ({"days": "14"}, "The days must be 7, 30 or 90."),
    ({"days": "abc"}, "The days must be 7, 30 or 90."),
    ({"days": "07"}, "The days must be 7, 30 or 90."),
    ({"days": ""}, "The days must be 7, 30 or 90."),
    ({"days": "7", "start_date": "2026-09-01", "end_date": "2026-09-02"},
     "Use days or a start_date and end_date, not both."),
    ({"start_date": "2026-09-01"}, "end_date is required."),
    ({"end_date": "2026-09-01"}, "start_date is required."),
    ({"start_date": "", "end_date": ""}, "start_date is required."),
    ({"start_date": "2026-09-01", "end_date": " "}, "end_date is required."),
    ({"start_date": "yesterday", "end_date": "2026-09-01"}, "start_date must use YYYY-MM-DD format."),
    ({"start_date": "2026-09-05", "end_date": "2026-09-01"}, "start_date must be before or equal to end_date."),
    ({"week": "1"}, "Use only the days, start_date and end_date query parameters."),
])
def test_the_window_parameters_are_strict(env, query, message):
    assert_error(env.call("GET", STATS_PATH, query_string=query), 400, "invalid_request", message)
    assert env.activity_logs.queries == []


def test_a_custom_range_is_at_most_366_days(env):
    stats(env, **custom_range(366))
    assert_error(env.call("GET", STATS_PATH, query_string=custom_range(367)), 400, "invalid_request",
                 "Choose a date range of 366 days or fewer.")


def test_each_window_parameter_is_given_once(env):
    assert_error(env.call("GET", f"{STATS_PATH}?days=7&days=30"), 400, "invalid_request",
                 "Give each query parameter only once.")


@pytest.mark.parametrize("failing_query", [1, 2, 3, 4])
def test_any_failed_statistics_query_is_a_503_not_a_zero(env, monkeypatch, failing_query):
    seed_stats_history(env)
    real_query = env.activity_logs.query_items
    calls = []

    def query_items(*args, **kwargs):
        calls.append(1)
        if len(calls) == failing_query:
            env.activity_logs.fail_queries = 1
        return real_query(*args, **kwargs)

    monkeypatch.setattr(env.activity_logs, "query_items", query_items)
    response = env.call("GET", STATS_PATH)
    assert response.status_code == 503
    assert answer(response) == STATS_UNAVAILABLE
    assert env.logs[-1] == ("[WORKSPACE_ROUTE] Group statistics read failed.", 40,
                            {"error_type": "CosmosHttpResponseError"})


def test_malformed_stored_figures_count_as_zero(env):
    env.groups.records.clear()
    env.seed_group(GROUP, status="active", users="not a list", metrics={"document_metrics": {
        "total_documents": "12", "storage_account_size": True, "ai_search_size": None,
    }})
    seed(env,
         record("t-1", "token_usage", iso(1), usage=None),
         record("t-2", "token_usage", iso(1), usage={"total_tokens": "100"}),
         record("t-3", "token_usage", iso(1), usage={"total_tokens": 12.5}),
         record("u-1", "document_creation", "not a timestamp"))
    result = stats(env)
    assert (result["totalDocuments"], result["storageUsed"], result["totalMembers"]) == (0, 0, 0)
    assert result["storage"] == {"ai_search_size": 0, "storage_account_size": 0}
    assert result["totalTokens"] == 12


@pytest.mark.parametrize("metrics", [None, "metrics", {"document_metrics": "none"}])
def test_missing_metrics_count_as_zero(env, metrics):
    env.groups.records.clear()
    env.seed_group(GROUP, status="active", metrics=metrics)
    result = stats(env)
    assert (result["totalDocuments"], result["storageUsed"]) == (0, 0)


# ---------------------------------------------------------------------------
# The document count
# ---------------------------------------------------------------------------

def test_the_owner_reads_the_count_of_current_documents(env):
    env.file_count = 7
    response = env.call("GET", FILE_COUNT_PATH)
    assert answer(response) == {"file_count": 7}
    assert env.file_count_calls == [GROUP]
    assert env.group_documents.queries == []


@pytest.mark.parametrize("caller", ["admin-1", "manager-1", "member-1"])
def test_only_the_owner_reads_the_count(env, caller):
    env.as_user(caller)
    assert_error(env.call("GET", FILE_COUNT_PATH), 403, "group_owner_required", "Only the group owner can do this.")
    assert env.file_count_calls == []


def test_the_count_takes_no_query_parameters(env):
    assert_error(env.call("GET", FILE_COUNT_PATH, query_string={"group_id": "group-2"}), 400, "invalid_request",
                 "This request does not accept query parameters.")
    assert env.file_count_calls == []


# ---------------------------------------------------------------------------
# Access and the boundary
# ---------------------------------------------------------------------------

INSIGHTS = [ACTIVITY_PATH, STATS_PATH, FILE_COUNT_PATH]


@pytest.mark.parametrize("path", INSIGHTS)
@pytest.mark.parametrize("status", STATUSES)
def test_the_owner_reads_every_insight_in_every_status(env, path, status):
    env.groups.records.clear()
    env.seed_group(GROUP, status=status)
    assert env.call("GET", path).status_code == 200


@pytest.mark.parametrize("path", [ACTIVITY_PATH, STATS_PATH])
@pytest.mark.parametrize("caller,expected", [
    ("admin-1", 200), ("manager-1", "group_manager_required"), ("member-1", "group_manager_required"),
])
def test_activity_and_statistics_need_the_owner_or_an_admin(env, path, caller, expected):
    env.as_user(caller)
    response = env.call("GET", path)
    if expected == 200:
        assert response.status_code == 200
    else:
        assert_error(response, 403, expected, "Only the group owner or an admin can do this.")
        assert env.activity_logs.queries == []


@pytest.mark.parametrize("path", INSIGHTS)
def test_a_missing_group_and_a_non_member_are_refused(env, path):
    env.as_user("outsider-1")
    assert_error(env.call("GET", path), 403, "group_access_denied")
    env.as_user("owner-1")
    assert_error(env.call("GET", path.replace(GROUP, "group-9")), 404, "group_not_found", "Group not found.")
    assert env.activity_logs.queries == [] and env.file_count_calls == []


@pytest.mark.parametrize("path", INSIGHTS)
def test_every_insight_needs_a_session_the_user_role_and_group_workspaces(env, path):
    env.sign_out()
    assert env.call("GET", path).status_code == 401
    env.as_user("owner-1", ["CreateGroups"])
    assert env.call("GET", path).status_code == 403
    env.as_user("owner-1")
    env.settings["enable_group_workspaces"] = False
    disabled = env.call("GET", path)
    assert disabled.status_code == 400
    assert disabled.get_json() == {"error": "Enable Group Workspaces is disabled."}
    assert env.activity_logs.queries == [] and env.file_count_calls == []


@pytest.mark.parametrize("path", INSIGHTS)
def test_an_insight_read_takes_no_body(env, path):
    assert_error(env.call("GET", path, {"x": 1}), 400, "invalid_request", "This request does not accept a request body.")


def test_a_membership_change_is_reflected_in_the_next_feed(env):
    seed(env, record("r-1", "agent_run", "2026-09-20T10:00:00", user_id="applicant-1"))
    assert feed(env)["activity"][0]["actor"] == {"kind": "former_member"}
    stored = env.stored_group(GROUP)
    stored["users"].append(person("applicant-1"))
    env.groups.seed(stored)
    assert feed(env)["activity"][0]["actor"] == {"kind": "member", "display_name": "Ana Applicant"}
