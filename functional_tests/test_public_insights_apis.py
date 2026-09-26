# test_public_insights_apis.py
"""
Functional test for the native public workspace insights: the activity feed and the statistics.
Version: 0.261.181
Implemented in: 0.261.181

``GET /api/public-workspaces/<workspace_id>/insights/activity`` and ``/insights/stats``
run for real in ``test_support/public_settings_harness.py``. Its activity logs container
evaluates exactly the aliased activity query and the four classic statistics queries, as
Cosmos evaluates them, and refuses any other query, so the classic routes run beside the
native ones over the same records. This test pins:

- the activity feed: the records the classic feed reads, in its order and limits, each
  projected to ``{id, occurred_at, type, summary, actor}`` with a reviewed summary, and
  nothing identifying beyond a member's stored display name, although the stored records
  carry file names, titles, emails, errors and conversation ids. A reader who chats with
  the workspace is a ``non_member``, never a named person or a "former member";
- a failed activity read: a data-free 503, never an empty feed;
- the statistics: the classic figures over the same window, without the invented
  ``storageLimit``, and ``totalMembers`` as classic counts it; strict window parameters
  with a 366-day cap on custom ranges and dates between 2000-01-01 and 9998-12-31, every
  refusal a reviewed 400 before the workspace is read; and a 503 rather than a zero figure
  when a query fails, and only then;
- access in every workspace status: the owner or an admin for the activity, and any
  stored role for the statistics, with the session, role and feature gates;
- the document count for the Settings danger zone: the owner only, from
  ``count_current_public_documents``, beside the classic ``/fileCount``, which answers any
  signed-in caller and counts every stored document record.
"""

import logging
from datetime import datetime, timedelta

import pytest

from test_support.public_settings_harness import EXPECTED_NATIVE_ACTIVITY_QUERY, public_settings_environment


WORKSPACE = "public-1"
ACTIVITY_PATH = f"/api/public-workspaces/{WORKSPACE}/insights/activity"
STATS_PATH = f"/api/public-workspaces/{WORKSPACE}/insights/stats"
FILE_COUNT_PATH = f"/api/public-workspaces/{WORKSPACE}/insights/file-count"
CLASSIC_ACTIVITY_PATH = f"/api/public_workspaces/{WORKSPACE}/activity"
CLASSIC_STATS_PATH = f"/api/public_workspaces/{WORKSPACE}/stats"
CLASSIC_FILE_COUNT_PATH = f"/api/public_workspaces/{WORKSPACE}/fileCount"
STATS_UNAVAILABLE = {"error": "Workspace statistics are unavailable right now. Try again.",
                     "error_code": "public_workspace_stats_unavailable"}
ACTIVITY_UNAVAILABLE = {"error": "Workspace activity is unavailable right now. Try again.",
                        "error_code": "public_workspace_activity_unavailable"}
STATUSES = ("active", "upload_disabled", "locked", "inactive", "archived")
# The admin is stored as a {userId, email, displayName} entry and the document manager as a
# bare id, as older data stores it, so the feed names the admin and not the manager.
MEMBERS = {"admins": (("admin-1", "dict"),), "managers": ("manager-1",)}


@pytest.fixture(scope="module")
def module_env():
    with public_settings_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    module_env.seed_workspace(WORKSPACE, status="active", **MEMBERS)
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


def record(record_id, activity_type, when, user_id="reader-1", workspace_id=WORKSPACE, **fields):
    """An activity record shaped as the activity logging writers shape it."""
    body = {"id": record_id, "user_id": user_id, "activity_type": activity_type, "timestamp": when,
            "created_at": when, "workspace_type": "public",
            "workspace_context": {"public_workspace_id": workspace_id}}
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


def workspace_reads(env):
    return [call for call in env.public_workspaces.calls if call[0] == "read_item"]


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------

def seed_sensitive_history(env):
    status_change = record(
        "status-1", "public_workspace_status_change", "2026-09-20T07:00:00", user_id="",
        public_workspace={"workspace_id": WORKSPACE, "workspace_name": "Secret Workspace Name"},
        status_change={"old_status": "active", "new_status": "locked", "changed_at": "2026-09-20T07:00:00",
                       "reason": "Legal hold on Project Falcon"},
        changed_by={"user_id": "control-center-admin", "email": "root.admin@example.test"},
    )
    seed(
        env,
        record("doc-1", "document_creation", "2026-09-20T10:00:00", user_id="admin-1",
               document={"document_id": "doc-secret-id", "file_name": "merger-plan.docx", "file_type": ".docx",
                         "file_size_bytes": 1234, "page_count": 3, "version": 1},
               embedding_usage={"total_tokens": 99, "model_deployment_name": "embed-secret"},
               document_metadata={"author": "Ana Applicant", "title": "Project Falcon",
                                  "abstract": "Confidential abstract", "keywords": ["acquisition"]}),
        record("tok-1", "token_usage", "2026-09-20T09:00:00", token_type="chat",
               usage={"total_tokens": 1234, "model": "gpt-secret-deployment", "prompt_tokens": 1000,
                      "completion_tokens": 234},
               chat_details={"conversation_id": "conv-secret", "message_id": "msg-secret"}),
        record("tok-2", "token_usage", "2026-09-20T08:00:00", user_id="manager-1", token_type="embedding",
               usage={"total_tokens": 1, "model": "embed-secret"},
               embedding_details={"document_id": "doc-secret-id", "file_name": "merger-plan.docx"}),
        status_change,
        record("sync-1", "file_sync", "2026-09-20T06:00:00", user_id=WORKSPACE, action="run_failed",
               description="File Sync run failed",
               workspace_context={"scope_type": "public", "source_id": "src-secret",
                                  "source_name": "Finance SharePoint", "group_id": None,
                                  "public_workspace_id": WORKSPACE},
               additional_context={"error": "401 from https://contoso.sharepoint.com token=abc"}),
        record("conv-1", "conversation_creation", "2026-09-20T05:00:00",
               conversation={"conversation_id": "conv-secret", "title": "Salary review"}),
        record("wf-1", "workflow_run", "2026-09-20T04:00:00", user_id="gone-1",
               workflow={"name": "Nightly digest", "error": "Traceback (most recent call last)"}),
        record("odd-1", "user_login", "2026-09-20T03:00:00", user_id="owner-1", login_method="sso",
               email="olive.owner@example.test"),
    )


SENSITIVE_VALUES = (
    "merger-plan", "Project Falcon", "Confidential abstract", "Ana Applicant", "acquisition", "embed-secret",
    "gpt-secret", "conv-secret", "msg-secret", "Secret Workspace Name", "Legal hold", "root.admin",
    "control-center-admin", "src-secret", "Finance SharePoint", "contoso", "token=abc", "Salary review", "gone-1",
    "Nightly digest", "Traceback", "sso", "@example.test", "reader-1", "manager-1", "owner-1", "admin-1",
    "doc-secret-id", "prompt_tokens", "workspace_context", "_etag",
)


def test_the_feed_projects_each_record_to_reviewed_fields(env):
    seed_sensitive_history(env)
    body = feed(env)
    assert body == {"limit": 50, "activity": [
        {"id": "doc-1", "occurred_at": "2026-09-20T10:00:00Z", "type": "document_creation",
         "summary": "Uploaded a document", "actor": {"kind": "member", "display_name": "Adam Admin"}},
        {"id": "tok-1", "occurred_at": "2026-09-20T09:00:00Z", "type": "token_usage",
         "summary": "Used 1,234 tokens in chat", "actor": {"kind": "non_member"}},
        {"id": "tok-2", "occurred_at": "2026-09-20T08:00:00Z", "type": "token_usage",
         "summary": "Used 1 token processing a document", "actor": {"kind": "member", "display_name": ""}},
        {"id": "status-1", "occurred_at": "2026-09-20T07:00:00Z", "type": "public_workspace_status_change",
         "summary": "Changed the workspace status from Active to Locked", "actor": {"kind": "system"}},
        {"id": "sync-1", "occurred_at": "2026-09-20T06:00:00Z", "type": "file_sync",
         "summary": "File Sync failed", "actor": {"kind": "system"}},
        {"id": "conv-1", "occurred_at": "2026-09-20T05:00:00Z", "type": "conversation_creation",
         "summary": "Started a conversation", "actor": {"kind": "non_member"}},
        {"id": "wf-1", "occurred_at": "2026-09-20T04:00:00Z", "type": "workflow_run",
         "summary": "Ran a workflow", "actor": {"kind": "non_member"}},
        {"id": "odd-1", "occurred_at": "2026-09-20T03:00:00Z", "type": "other",
         "summary": "Other activity", "actor": {"kind": "member", "display_name": "Olive Owner"}},
    ]}


def test_nothing_identifying_leaves_the_feed(env):
    seed_sensitive_history(env)
    native = env.call("GET", ACTIVITY_PATH).get_data(as_text=True)
    classic = env.call("GET", CLASSIC_ACTIVITY_PATH).get_data(as_text=True)
    for value in SENSITIVE_VALUES:
        assert value not in native, value
    # The fixture does carry them: the classic feed returns the raw records.
    assert all(value in classic for value in ("merger-plan", "Project Falcon", "token=abc", "root.admin", "reader-1"))


def test_only_the_aliased_fields_are_read(env):
    seed_sensitive_history(env)
    feed(env, limit="20")
    assert env.activity_logs.queries == [
        {"query": EXPECTED_NATIVE_ACTIVITY_QUERY, "parameters": {"@limit": 20, "@workspace_id": WORKSPACE}},
    ]


@pytest.mark.parametrize("activity_type,summary", [
    ("document_creation", "Uploaded a document"),
    ("document_deletion", "Deleted a document"),
    ("document_metadata_update", "Updated a document's details"),
    ("conversation_creation", "Started a conversation"),
    ("conversation_deletion", "Deleted a conversation"),
    ("conversation_archival", "Archived a conversation"),
    ("workflow_creation", "Created a workflow"),
    ("workflow_update", "Updated a workflow"),
    ("workflow_deletion", "Deleted a workflow"),
    ("workflow_run", "Ran a workflow"),
    # Recorded for groups only: a record like this is not something public workspaces write.
    ("agent_run", "Other activity"),
    ("group_status_change", "Other activity"),
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
    ({"total_tokens": 7}, "web_search", "Used 7 tokens"),
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
    ("active", "locked", "Changed the workspace status from Active to Locked"),
    ("upload_disabled", "inactive", "Changed the workspace status from Uploads disabled to Inactive"),
    ("locked", "active", "Changed the workspace status from Locked to Active"),
    ("active", "archived", "Changed the workspace status"),
    (None, "locked", "Changed the workspace status"),
])
def test_status_changes_name_only_known_statuses(env, old, new, summary):
    body = record("s-1", "public_workspace_status_change", "2026-09-20T10:00:00",
                  status_change={"old_status": old, "new_status": new, "reason": "Do not show"})
    assert one(env, body)["summary"] == summary


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
    ("manager-1", {"kind": "member", "display_name": ""}),
    ("quiet-1", {"kind": "member", "display_name": ""}),
    ("reader-1", {"kind": "non_member"}),
    ("gone-1", {"kind": "non_member"}),
    ("", {"kind": "system"}),
    (WORKSPACE, {"kind": "system"}),
    (42, {"kind": "system"}),
])
def test_the_actor_is_named_only_when_the_workspace_names_them(env, user_id, actor):
    stored = env.stored_workspace(WORKSPACE)
    stored["documentManagers"].append({"userId": "quiet-1", "email": "quiet@example.test"})
    env.public_workspaces.seed(stored)
    assert one(env, record("a-1", "workflow_run", "2026-09-20T10:00:00", user_id=user_id))["actor"] == actor


def test_a_stored_name_wins_over_a_bare_id(env):
    stored = env.stored_workspace(WORKSPACE)
    stored["admins"] = ["manager-1"]
    stored["documentManagers"] = [{"userId": "manager-1", "displayName": "Mia Manager"}, "manager-1"]
    env.public_workspaces.seed(stored)
    entry = one(env, record("a-1", "document_creation", "2026-09-20T10:00:00", user_id="manager-1"))
    assert entry["actor"] == {"kind": "member", "display_name": "Mia Manager"}


@pytest.mark.parametrize("changed_by,actor", [
    ({"user_id": "admin-1", "email": "adam.admin@example.test"}, {"kind": "member", "display_name": "Adam Admin"}),
    ({"user_id": "control-center-admin", "email": "root@example.test"}, {"kind": "system"}),
    ({}, {"kind": "system"}),
    (None, {"kind": "system"}),
])
def test_a_status_change_is_attributed_to_whoever_changed_it(env, changed_by, actor):
    body = record("s-1", "public_workspace_status_change", "2026-09-20T10:00:00", user_id="reader-1",
                  status_change={"old_status": "active", "new_status": "locked"})
    if changed_by is not None:
        body["changed_by"] = changed_by
    assert one(env, body)["actor"] == actor


@pytest.mark.parametrize("stored,shown", [
    ("2026-09-20T10:00:00", "2026-09-20T10:00:00Z"),
    ("2026-09-20T10:00:00.123456", "2026-09-20T10:00:00.123456Z"),
    ("2026-09-20T12:00:00+02:00", "2026-09-20T10:00:00Z"),
    ("2026-09-20T10:00:00Z", "2026-09-20T10:00:00Z"),
    # A UTC offset that moves the time past the calendar's first day can't be shown.
    ("0001-01-01T00:30:00+01:00", None),
    ("yesterday", None),
    ("   ", None),
])
def test_timestamps_are_utc_with_a_z(env, stored, shown):
    assert one(env, record("t-1", "workflow_run", stored))["occurred_at"] == shown


def test_a_record_id_that_is_not_text_is_omitted(env):
    assert one(env, record(7, "workflow_run", "2026-09-20T10:00:00"))["id"] is None


def seed_long_history(env):
    seed(env, *(record(f"r-{index:02d}", "workflow_run", f"2026-09-{1 + index // 24:02d}T{index % 24:02d}:00:00")
                for index in range(55)))
    seed(env, record("other-workspace", "workflow_run", "2026-09-30T10:00:00", workspace_id="public-2"))
    # A chat activity record names the workspace at the top level, not in workspace_context,
    # and so does anything else recorded elsewhere: neither feed reads them.
    seed(env, {"id": "chat-activity", "user_id": "reader-1", "activity_type": "chat_activity",
               "timestamp": "2026-09-30T11:00:00", "public_workspace_id": WORKSPACE})
    seed(env, {"id": "named-elsewhere", "user_id": "owner-1", "activity_type": "member_added",
               "timestamp": "2026-09-30T12:00:00", "public_workspace": {"workspace_id": WORKSPACE}})


@pytest.mark.parametrize("limit", [None, "10", "20", "50"])
def test_the_feed_reads_the_records_the_classic_feed_reads_in_its_order(env, limit):
    seed_long_history(env)
    query = {"limit": limit} if limit else None
    native = [entry["id"] for entry in feed(env, **(query or {}))["activity"]]
    classic = [entry["id"] for entry in env.call("GET", CLASSIC_ACTIVITY_PATH, query_string=query).get_json()]
    assert native == classic
    assert len(native) == int(limit or 50)
    assert native[0] == "r-54"
    assert not {"other-workspace", "chat-activity", "named-elsewhere"} & set(native)


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


def test_a_failed_activity_query_is_a_data_free_503_not_an_empty_feed(env):
    seed_sensitive_history(env)
    env.activity_logs.fail_queries = 1
    response = env.call("GET", ACTIVITY_PATH)
    assert response.status_code == 503
    assert answer(response) == ACTIVITY_UNAVAILABLE
    assert env.logs[-1] == ("[PUBLIC_SETTINGS] Public workspace activity read failed.", logging.ERROR,
                            {"error_type": "CosmosHttpResponseError", "status_code": 503})
    # The classic feed answers the same failure with an empty timeline.
    env.activity_logs.fail_queries = 1
    classic = env.call("GET", CLASSIC_ACTIVITY_PATH)
    assert (classic.status_code, classic.get_json()) == (200, [])


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def seed_stats_history(env):
    env.public_workspaces.records.clear()
    env.seed_workspace(WORKSPACE, status="active", **MEMBERS, metrics={"document_metrics": {
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
        record("x-1", "token_usage", iso(1), workspace_id="public-2", usage={"total_tokens": 999999}),
        record("x-2", "document_creation", iso(1), workspace_id="public-2"),
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
    classic = env.call("GET", CLASSIC_STATS_PATH, query_string=query or None).get_json()
    assert classic.pop("storageLimit") == 10737418240
    assert "storageLimit" not in native
    assert native == classic
    assert native["totalTokens"] == tokens
    assert sum(native["documentActivity"]["uploads"]) == uploads
    assert sum(native["documentActivity"]["deletes"]) == deletes
    assert sum(native["tokenUsage"]["data"]) == tokens
    assert (native["totalDocuments"], native["storageUsed"]) == (12, 2048)
    assert native["storage"] == {"ai_search_size": 512, "storage_account_size": 2048}


@pytest.mark.parametrize("admins,managers,members", [
    ((("admin-1", "dict"),), ("manager-1",), 3),
    ((), (), 1),
    (("admin-1", "reader-1"), (("manager-1", "dict"), "outsider-1"), 5),
])
def test_members_are_counted_as_classic_counts_them(env, admins, managers, members):
    env.public_workspaces.records.clear()
    env.seed_workspace(WORKSPACE, status="active", admins=admins, managers=managers)
    native = stats(env)
    classic = env.call("GET", CLASSIC_STATS_PATH).get_json()
    assert native["totalMembers"] == classic["totalMembers"] == members


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


DATE_RANGE = "Choose dates between 2000-01-01 and 9998-12-31."
OUT_OF_RANGE_WINDOWS = {
    # A UTC offset moves the first day before 0001-01-01, which the shared parser can't represent.
    "offset_before_the_calendar": {"start_date": "0001-01-01T00:00:00+01:00", "end_date": "0001-01-02"},
    # ... or the last day after 9999-12-31.
    "offset_after_the_calendar": {"start_date": "9998-12-01", "end_date": "9999-12-31T23:59:59-23:59"},
    # A short range whose day-by-day series would step past 9999-12-31.
    "series_past_the_calendar": {"start_date": "9999-12-01", "end_date": "9999-12-31"},
    "before_the_earliest_date": {"start_date": "1999-12-31", "end_date": "2000-01-01"},
    "after_the_latest_date": {"start_date": "9998-12-31", "end_date": "9999-01-01"},
    "offset_moves_the_start_before_it": {"start_date": "2000-01-01T00:30:00+01:00", "end_date": "2000-01-02"},
    "offset_moves_the_end_after_it": {"start_date": "9998-12-30", "end_date": "9998-12-31T23:00:00-05:00"},
    # Out of range is reported before the length.
    "outside_and_too_long": {"start_date": "0001-01-01", "end_date": "9999-12-30"},
}


def error_logs(env):
    return [entry for entry in env.logs if entry[1] == logging.ERROR]


@pytest.mark.parametrize("caller", ["owner-1", "reader-1"])
@pytest.mark.parametrize("window", OUT_OF_RANGE_WINDOWS)
def test_dates_outside_the_supported_range_are_a_reviewed_400(env, window, caller):
    env.as_user(caller)
    response = env.call("GET", STATS_PATH, query_string=OUT_OF_RANGE_WINDOWS[window])
    assert_error(response, 400, "invalid_request", DATE_RANGE)
    assert error_logs(env) == []
    assert env.activity_logs.queries == []
    # Refused before the workspace is read, as every other window refusal is.
    assert workspace_reads(env) == []


@pytest.mark.parametrize("query,first,last,days", [
    ({"start_date": "2000-01-01", "end_date": "2000-01-31"}, "2000-01-01", "2000-01-31", 31),
    ({"start_date": "9998-12-01", "end_date": "9998-12-31"}, "9998-12-01", "9998-12-31", 31),
    ({"start_date": "9998-01-01", "end_date": "9998-12-31"}, "9998-01-01", "9998-12-31", 365),
    ({"start_date": "2000-01-01T00:00:00Z", "end_date": "2000-01-01T23:59:59Z"}, "2000-01-01", "2000-01-01", 1),
])
def test_windows_at_the_edges_of_the_supported_range_are_read(env, query, first, last, days):
    native = stats(env, **query)
    assert (native["window"]["type"], native["window"]["days"]) == ("custom", days)
    assert (native["dateRange"][0], native["dateRange"][-1], len(native["dateRange"])) == (first, last, days)
    assert len(env.activity_logs.queries) == 4
    assert error_logs(env) == []
    classic = env.call("GET", CLASSIC_STATS_PATH, query_string=query).get_json()
    assert classic.pop("storageLimit") == 10737418240
    assert native == classic


def test_a_stored_timestamp_that_cannot_be_read_is_left_out_rather_than_failing(env):
    # Only the storage reads can be the 503, and building the figures never fails: a stored
    # timestamp whose offset moves it past the calendar's start is left out, as any other
    # unreadable timestamp is.
    seed(env,
         record("u-edge", "document_creation", "0001-01-01T00:30:00+01:00", created_at=iso(1)),
         record("u-ok", "document_creation", iso(1)))
    result = stats(env)
    assert sum(result["documentActivity"]["uploads"]) == 1
    assert error_logs(env) == []


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
    assert env.logs[-1] == ("[PUBLIC_SETTINGS] Public workspace statistics read failed.", logging.ERROR,
                            {"error_type": "CosmosHttpResponseError", "status_code": 503})


def test_malformed_stored_figures_count_as_zero(env):
    env.public_workspaces.records.clear()
    env.seed_workspace(WORKSPACE, status="active", managers=(), metrics={"document_metrics": {
        "total_documents": "12", "storage_account_size": True, "ai_search_size": None,
    }})
    stored = env.stored_workspace(WORKSPACE)
    stored["admins"] = "not a list"
    env.public_workspaces.seed(stored)
    seed(env,
         record("t-1", "token_usage", iso(1), usage=None),
         record("t-2", "token_usage", iso(1), usage={"total_tokens": "100"}),
         record("t-3", "token_usage", iso(1), usage={"total_tokens": 12.5}),
         record("u-1", "document_creation", "not a timestamp"))
    result = stats(env)
    assert (result["totalDocuments"], result["storageUsed"], result["totalMembers"]) == (0, 0, 1)
    assert result["storage"] == {"ai_search_size": 0, "storage_account_size": 0}
    assert result["totalTokens"] == 12


@pytest.mark.parametrize("metrics", [None, "metrics", {"document_metrics": "none"}])
def test_missing_metrics_count_as_zero(env, metrics):
    env.public_workspaces.records.clear()
    env.seed_workspace(WORKSPACE, status="active", metrics=metrics)
    result = stats(env)
    assert (result["totalDocuments"], result["storageUsed"]) == (0, 0)


# ---------------------------------------------------------------------------
# The document count
# ---------------------------------------------------------------------------

def test_the_owner_reads_the_count_of_current_documents(env):
    env.file_count = 7
    response = env.call("GET", FILE_COUNT_PATH)
    assert answer(response) == {"file_count": 7}
    assert env.file_count_calls == [WORKSPACE]
    assert env.public_documents.queries == []


@pytest.mark.parametrize("caller", ["admin-1", "manager-1", "reader-1", "outsider-1"])
def test_only_the_owner_reads_the_count(env, caller):
    env.as_user(caller)
    assert_error(env.call("GET", FILE_COUNT_PATH), 403, "public_workspace_owner_required",
                 "Only the workspace owner can do this.")
    assert env.file_count_calls == []


def test_the_count_takes_no_query_parameters(env):
    assert_error(env.call("GET", FILE_COUNT_PATH, query_string={"workspace_id": "public-2"}), 400, "invalid_request",
                 "This request does not accept query parameters.")
    assert env.file_count_calls == []


@pytest.mark.parametrize("caller", ["owner-1", "reader-1"])
def test_the_classic_count_answers_anyone_and_counts_every_stored_record(env, caller):
    """What the classic manage page checks before it offers to delete a workspace: every
    stored document record, superseded revisions included, for any signed-in caller."""
    for document_id, version in (("report-v1", 1), ("report-v2", 2), ("report-v3", 3)):
        env.seed_document(document_id, revision_family_id="report", version=version,
                          is_current_version=version == 3)
    env.seed_document("elsewhere", ws_id="public-2")
    env.as_user(caller)
    response = env.call("GET", CLASSIC_FILE_COUNT_PATH)
    assert (response.status_code, response.get_json()) == (200, {"fileCount": 3})
    assert env.file_count_calls == []


# ---------------------------------------------------------------------------
# Access and the boundary
# ---------------------------------------------------------------------------

INSIGHTS = [ACTIVITY_PATH, STATS_PATH, FILE_COUNT_PATH]


@pytest.mark.parametrize("path", INSIGHTS)
@pytest.mark.parametrize("status", STATUSES)
def test_the_owner_reads_every_insight_in_every_status(env, path, status):
    env.public_workspaces.records.clear()
    env.seed_workspace(WORKSPACE, status=status, **MEMBERS)
    assert env.call("GET", path).status_code == 200


@pytest.mark.parametrize("admins", [("admin-1",), (("admin-1", "dict"),)])
@pytest.mark.parametrize("caller,expected", [
    ("admin-1", 200), ("manager-1", "public_workspace_manager_required"),
    ("reader-1", "public_workspace_manager_required"), ("outsider-1", "public_workspace_manager_required"),
])
def test_the_activity_needs_the_owner_or_an_admin(env, admins, caller, expected):
    env.public_workspaces.records.clear()
    env.seed_workspace(WORKSPACE, status="active", admins=admins, managers=("manager-1",))
    env.as_user(caller)
    response = env.call("GET", ACTIVITY_PATH)
    if expected == 200:
        assert response.status_code == 200
    else:
        assert_error(response, 403, expected, "Only the workspace owner or an admin can do this.")
        assert env.activity_logs.queries == []


@pytest.mark.parametrize("managers", [("manager-1",), (("manager-1", "dict"),)])
@pytest.mark.parametrize("caller,expected", [
    ("admin-1", 200), ("manager-1", 200),
    ("reader-1", "public_workspace_member_required"), ("outsider-1", "public_workspace_member_required"),
])
def test_the_statistics_need_a_stored_role(env, managers, caller, expected):
    env.public_workspaces.records.clear()
    env.seed_workspace(WORKSPACE, status="active", admins=("admin-1",), managers=managers)
    env.as_user(caller)
    response = env.call("GET", STATS_PATH)
    if expected == 200:
        assert response.status_code == 200
    else:
        assert_error(response, 403, expected, "Only the workspace owner, an admin or a document manager can do this.")
        assert env.activity_logs.queries == []


@pytest.mark.parametrize("path", INSIGHTS)
def test_a_missing_workspace_is_refused(env, path):
    assert_error(env.call("GET", path.replace(WORKSPACE, "public-9")), 404, "public_workspace_not_found",
                 "The selected public workspace was not found.")
    assert env.activity_logs.queries == [] and env.file_count_calls == []


@pytest.mark.parametrize("path", INSIGHTS)
def test_every_insight_needs_a_session_the_user_role_and_public_workspaces(env, path):
    env.sign_out()
    assert env.call("GET", path).status_code == 401
    env.as_user("owner-1", ["CreatePublicWorkspaces"])
    assert env.call("GET", path).status_code == 403
    env.as_user("owner-1")
    env.settings["enable_public_workspaces"] = False
    disabled = env.call("GET", path)
    assert disabled.status_code == 400
    assert disabled.get_json() == {"error": "Enable Public Workspaces is disabled."}
    assert env.activity_logs.queries == [] and env.file_count_calls == []


@pytest.mark.parametrize("path", INSIGHTS)
def test_an_insight_read_takes_no_body(env, path):
    assert_error(env.call("GET", path, {"x": 1}), 400, "invalid_request", "This request does not accept a request body.")


@pytest.mark.parametrize("path", INSIGHTS)
def test_an_invalid_workspace_id_never_reaches_storage(env, path):
    assert_error(env.call("GET", path.replace(WORKSPACE, "public,1")), 400, "invalid_request",
                 "Invalid public workspace identifier.")
    assert workspace_reads(env) == [] and env.activity_logs.queries == [] and env.file_count_calls == []


def test_a_membership_change_is_reflected_in_the_next_feed(env):
    seed(env, record("r-1", "workflow_run", "2026-09-20T10:00:00", user_id="reader-1"))
    assert feed(env)["activity"][0]["actor"] == {"kind": "non_member"}
    stored = env.stored_workspace(WORKSPACE)
    stored["documentManagers"].append({"userId": "reader-1", "email": "rhea.reader@example.test",
                                       "displayName": "Rhea Reader"})
    env.public_workspaces.seed(stored)
    assert feed(env)["activity"][0]["actor"] == {"kind": "member", "display_name": "Rhea Reader"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
